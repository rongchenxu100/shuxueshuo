"""Bounded symmetry plots retain exact teaching and fall back to number lines."""
import pytest
import sympy as sp

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


@pytest.mark.parametrize('facts,target,answer,label', [
    (['parity(f,odd)', 'graph_symmetry(f,axis,1/1000)', 'f(1/1000)=1'], 'f(3/1000)', -1,
     r'$f(\frac{3}{1000})=-1$'),
    (['parity(f,odd)', 'graph_symmetry(f,axis,1)'], 'f(10000)', 0, '$f(10000)=0$'),
])
def test_plot_fallback_preserves_pairing_period_and_exact_answer(facts, target, answer, label):
    d = description(candidate(['Dom(f)=ℝ', *facts], target))
    m = solve(d)
    assert m['proof']['value'] == answer and verify(d, m)
    cards = phase_views({'description': d, 'phase': 'rewrite'})
    for card in cards[:2]:
        assert card['condition_number_lines']
        assert 'graph' not in card and 'completion_graph' not in card
    assert any(r'周期为' in card['proof'] for card in cards)
    conclusion, = phase_views({'description': d, 'phase': 'conclude'})
    correct = [o['label'] for o in conclusion['interaction']['options']
               if o['value'] in conclusion['expected_answer']['one_of']]
    assert correct == [label]


def test_normal_period_keeps_the_existing_interactive_graphs():
    cards = phase_views({'description': description(a10()), 'phase': 'rewrite'})
    assert len(cards) == 5
    assert all('graph' in card for card in cards)
    assert all('completion_graph' in cards[i] for i in (0, 1, 3, 4))


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
