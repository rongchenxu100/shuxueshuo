"""Bounded symmetry plots retain exact teaching and fall back to number lines."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.symmetry_presentation import compile_cards
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from shuxueshuo_server.graph_lesson.stage_three.symmetry_relation_presentation import (
    _example_graph,
    phase_views,
)
from shuxueshuo_server.graph_lesson.symmetry_relation_math import solve, verify
from tests.solver.test_graph_symmetry_relation import a10, candidate, description


@pytest.mark.parametrize('step,span', [
    (sp.Rational(1, 500), ()),
    (sp.Integer(2), (sp.Integer(1000),)),
])
def test_oversized_plot_falls_back_before_evaluating_samples(step, span):
    def forbidden(_):
        pytest.fail('An over-budget plot must not evaluate any samples')

    example = forbidden, [sp.S.Zero, step/2], step
    assert _example_graph({'function': 'f'}, {}, example, '', span=span) is None


@pytest.mark.parametrize('facts,target,answer,label,mode', [
    (['parity(f,odd)', 'graph_symmetry(f,axis,1/1000)', 'f(1/1000)=1'], 'f(3/1000)', -1,
     r'$f(\frac{3}{1000})=-1$', 'walk'),
    (['parity(f,odd)', 'graph_symmetry(f,axis,1)'], 'f(10000)', 0, '$f(10000)=0$', 'period'),
])
def test_unplottable_walks_keep_their_steps_and_exact_answer(facts, target, answer, label, mode):
    d = description(candidate(['Dom(f)=ℝ', *facts], target))
    m = solve(d)
    assert m['proof']['value'] == answer and verify(d, m)
    cards = phase_views({'description': d, 'phase': 'rewrite'})
    assert cards and all(card['interaction']['type'] in ('choice', 'read') for card in cards)
    if mode == 'period':
        assert any(r'周期为' in card['proof'] for card in cards)
    else:
        assert any('对称点' in card['question'] for card in cards)
    conclusion, = phase_views({'description': d, 'phase': 'conclude'})
    correct = [o['label'] for o in conclusion['interaction']['options']
               if o['value'] in conclusion['expected_answer']['one_of']]
    assert correct == [label]


def test_a10_first_question_walks_each_value_on_the_graph():
    cards = phase_views({'description': description(a10()), 'phase': 'rewrite'})
    assert [c['card_group_title'] for c in cards] == ['先找出图像上确定的点', '求 $f(2)$', '求 $f(3)$', '求 $f(3)$',
                                                      '求 $f(4)$', '求 $f(4)$']
    assert all('graph' in card and 'completion_graph' in card for card in cards)
    kinds = [r['kind'] for c in cards[1:] for r in c['completion_graph']['params']['reflections']]
    assert kinds == ['axis', 'center', 'axis', 'center', 'axis']
    conclusion, = phase_views({'description': description(a10()), 'phase': 'conclude'})
    assert '1+0+\\left(-1\\right)+0=0' in conclusion['proof']


def test_each_card_group_keeps_its_own_derivation():
    seed = {'values': encode_value({'description': description(a10()), 'phase': 'rewrite'})}
    parts = compile_cards([seed], 'i')['parts']
    proofs = {p['card_group_title']: p['completion_proof'] for p in parts if 'completion_proof' in p}
    assert list(proofs) == ['先找出图像上确定的点', '求 $f(2)$', '求 $f(3)$']
    assert '2f(0)=0' in proofs['先找出图像上确定的点'] and 'f(-1)=-f(1)=-1' in proofs['求 $f(3)$'] and 'f(3)=f(-1)=-1' in proofs['求 $f(3)$']
    assert 'completion_proof' not in parts[-1]


def test_a10_sum_derives_the_period_from_a_generic_point():
    cards = phase_views({'description': description(a10(True)), 'phase': 'rewrite'})
    period = [c for c in cards if c['card_group'] == 'period']
    assert len(period) == 5 and period[0]['question'].startswith('在图像上任取一点 $(x,m)$。求横坐标为 $x+2$ 的点')
    assert period[-1]['title'] == '两点一样高，得出周期'
    assert 'f(x+4)=f(-x-2)=-f(x+2)=-f(-x)=f(x)' in period[-1]['proof']
    assert period[-1]['completion_graph']['params']['level'] == 0.5
    values, = [c for c in cards if c['card_group'] == 'values']
    assert 'f(3)=f(-1)=-f(1)=-1' in values['proof']


def test_plot_sampling_does_not_depend_on_distance_from_origin():
    center = sp.Integer(10000)
    seen = []

    def linear(t):
        assert center-1 <= t <= center+3
        seen.append(t)
        return t-center

    example = linear, [center, center+1], sp.Integer(2)
    graph = _example_graph({'function': 'f'}, {}, example, '')
    assert graph is not None
    assert 0 < len(seen) < 10
    assert graph['params']['segments'] == [{'coefficients': [0, 1, -10000],
                                           'interval': [9999, 10003], 'interval_closed': [True, True]}]
