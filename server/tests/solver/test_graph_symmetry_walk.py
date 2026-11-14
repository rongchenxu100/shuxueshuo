"""Teaching walks replay every reflection and must reproduce the linear certificate."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.symmetry_relation_math import solve
from shuxueshuo_server.graph_lesson.symmetry_walk import replay, teaching_plan
from tests.solver.test_graph_symmetry_relation import a10, candidate, description


def plan_for(facts, target):
    d = description(candidate(['Dom(f)=ℝ', *facts], target))
    m = solve(d)
    return d, m, teaching_plan(d, m)


def test_a10_first_question_reaches_each_value_from_known_points():
    d = description(a10())
    m = solve(d)
    plan = teaching_plan(d, m)
    assert plan['mode'] == 'walk'
    assert {k: v['value'] for k, v in plan['known'].items()} == {1: 1, 0: 0}
    assert [(w['target'], [s['to'] for s in w['steps']], w['value']) for w in plan['walks']] == [
        (2, [2], 0), (3, [-1, 3], -1), (4, [-2, 4], 0)]


def test_long_sum_and_spread_targets_derive_the_period_first():
    d = description(a10(True))
    plan = teaching_plan(d, solve(d))
    assert plan['mode'] == 'period' and plan['period'] == 4 and plan['reps'] == [1, 2, 3, 4]
    assert [s['to'] for s in plan['cycle']['steps']] == [-sp.Symbol('x', real=True), sp.Symbol('x', real=True)+2,
                                                         -sp.Symbol('x', real=True)-2, sp.Symbol('x', real=True)+4]
    _, _, plan = plan_for(['parity(f,odd)', 'graph_symmetry(f,axis,1/2)'], 'f(1)+f(2)+f(3)+f(4)+f(5)')
    assert plan['mode'] == 'period' and plan['period'] == 2


def test_two_axes_have_a_one_round_period():
    _, _, plan = plan_for(['graph_symmetry(f,axis,0)', 'graph_symmetry(f,axis,3)', 'f(1)=7'], 'f(13)')
    assert plan['mode'] == 'period' and plan['period'] == 6 and len(plan['cycle']['steps']) == 2


def test_unclosed_translation_keeps_the_older_presentation():
    _, _, plan = plan_for(['graph_symmetry(f,center,0,0)', 'graph_symmetry(f,center,1,2)'], 'f(6)')
    assert plan is None


@pytest.mark.parametrize('field,change', [('value_to', 1), ('to', 1)])
def test_tampered_steps_do_not_replay(field, change):
    d = description(a10())
    m = solve(d)
    plan = teaching_plan(d, m)
    walks = deepcopy(plan['walks'])
    walks[1]['steps'][0][field] += change
    assert not replay(m, plan['known'], walks)
