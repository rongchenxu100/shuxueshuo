"""R0 coefficient identities, source restrictions and complete parameter sets."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parity_parameter_math as math
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import (
    decode_value,
    encode_value,
)

TARGET = '/root/goals/0'


def candidate(expression='x^2+(2-m)*x+m^2+12', prop='even', *, parameter='m', variable='x',
              facts=(), goal_kind='find_value'):
    labels = {'even': '偶函数', 'odd': '奇函数', 'both': '既是奇函数又是偶函数',
              'odd_only': '奇函数但不是偶函数', 'even_only': '偶函数但不是奇函数'}
    goal = ({'kind': goal_kind, 'expression': parameter} if goal_kind == 'find_value'
            else {'kind': goal_kind, 'symbol': parameter})
    return {'original_text': f'已知函数 $f({variable})={expression}$ 为{labels[prop]}，'
                             + ''.join(f'${text}$，' for text in facts)
                             + f'求 ${parameter}$ 的' + ('值。' if goal_kind == 'find_value' else '取值范围。'),
            'root': {'definitions': [f'f({variable})={expression}'],
                     'facts': [f'parity(f,{prop})', *facts], 'goals': [goal]}}


def description(value):
    d = build_context(value, TARGET)['parity_parameter_goal']
    assert d['structure_supported'], d['reason']
    return d


@pytest.mark.parametrize('expr,prop,facts,answer', [
    ('x^2+(2-m)*x+m^2+12', 'even', (), sp.FiniteSet(2)),
    ('m*x', 'odd', (), sp.S.Reals),
    ('m*x', 'odd_only', (), sp.S.Reals-sp.FiniteSet(0)),
    ('m*x', 'even', (), sp.FiniteSet(0)),
    ('m', 'odd', (), sp.FiniteSet(0)),
    ('x^2+m*x', 'odd', (), sp.S.EmptySet),
    ('(m^2-1)*x^2+m*x', 'odd', (), sp.FiniteSet(-1, 1)),
    ('(m^2-1)*x^2+m*x', 'odd', ('m>0',), sp.FiniteSet(1)),
    ('(m^2-2)*x^2+m*x', 'odd', (), sp.FiniteSet(-sp.sqrt(2), sp.sqrt(2))),
    ('m*x^2', 'even', (), sp.S.Reals),
    ('m*x^2', 'even', ('degree(f)=2',), sp.S.Reals-sp.FiniteSet(0)),
    ('m*x^2', 'even_only', ('m∈[-2,2]',), sp.Interval(-2, 0, False, True)|sp.Interval(0, 2, True, False)),
    ('m*x^2', 'both', (), sp.FiniteSet(0)),
    ('0', 'even', (), sp.S.Reals),
    ('0', 'odd_only', (), sp.S.EmptySet),
    ('(m^2-1)*x^2', 'even', ('degree(f)=2', 'm<=1'), sp.Interval.open(-sp.oo, -1)|sp.Interval.open(-1, 1)),
    ('m*x', 'odd', ('m^2<2',), sp.Interval.open(-sp.sqrt(2), sp.sqrt(2))),
])
def test_complete_parameter_sets(expr, prop, facts, answer):
    d = description(candidate(expr, prop, facts=facts, goal_kind='find_range'))
    model = math.solve(d)
    assert model['feasible_set'] == answer
    assert math.verify(d, model)
    assert math.verify(d, decode_value(encode_value(model)))


def test_old_coefficient_guard_and_unevaluated_identity_roundtrip():
    from shuxueshuo_server.graph_lesson.function_coefficients import (
        compare_coefficients,
    )
    d = description(candidate('m*x^2'))
    identities, variable, parameters, domain = math.identities(d)
    assert compare_coefficients(identities, variable, parameters, domain)['equations'] == []
    assert isinstance(decode_value(encode_value(identities))[0], sp.Equality)
    with pytest.raises(ValueError, match='equality_required'):
        compare_coefficients([sp.true], variable, parameters, domain)


def test_independent_verifier_detects_missing_roots_and_dropped_exclusion(monkeypatch):
    d = description(candidate('(m^2-1)*x^2+m*x', 'odd', goal_kind='find_range'))
    model = math.solve(d)
    def forbidden(*args, **kwargs):
        pytest.fail('verification must not invoke the production solver')
    monkeypatch.setattr(math, 'solve', forbidden)
    monkeypatch.setattr(math, 'compare_coefficients', forbidden)
    monkeypatch.setattr(math, 'condition_set', forbidden)
    assert math.verify(d, model)
    for field, wrong in [('feasible_set', sp.FiniteSet(1)), ('domain', sp.Interval(-1, 1)),
                         ('parameter_space', sp.Interval.open(0, sp.oo))]:
        changed = deepcopy(model)
        changed[field] = wrong
        assert not math.verify(d, changed)


@pytest.mark.parametrize('expr,facts', [
    ('(x^2-1)^3+m*x', ()), ('sqrt(x^2+m*x)', ()), ('m/(x^2-m)', ()),
    ('(x-m^2)/(x-m^2)', ()), ('m*x^2', ('Dom(f)=[-m^2,m]',)),
    ('a*x^2+m*x', ()), ('m^3*x', ()), ('m*x', ('f(1)=2',)),
    ('((10000000000^2)^2)^2+m*x', ()),
])
def test_outside_supported_structure_is_capability_gap_not_empty_set(expr, facts):
    d = build_context(candidate(expr, facts=facts), TARGET)['parity_parameter_goal']
    assert not d['structure_supported'] and d['reason']


def test_parameter_and_bound_input_names_are_not_guessed():
    d = description(candidate('t^2+(2-x)*t+x^2+12', parameter='x', variable='t'))
    assert math.solve(d)['feasible_set'] == sp.FiniteSet(2)
    fact, = d['parity_facts']
    assert fact['function_ref'] == 'r:function:f'
    assert fact['variable_ref'].endswith('#function_argument')
    assert fact['origin'] == 'given'


def test_extra_parity_condition_and_declared_degree_cannot_disappear():
    d = description(candidate('m*x', 'odd', facts=('parity(f,even)',)))
    assert math.solve(d)['feasible_set'] == sp.FiniteSet(0)
    d = description(candidate('m*x^2', 'both', facts=('degree(f)=2',)))
    assert math.solve(d)['feasible_set'] == sp.S.EmptySet
