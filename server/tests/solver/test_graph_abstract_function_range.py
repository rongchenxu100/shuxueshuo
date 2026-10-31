"""Exact coverage, independent output verification, and negative information cases."""
from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import abstract_function_range as ar
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.function_range import (
    admitted as range_admitted,
)
from tests.solver.test_graph_abstract_function_domain_q13 import RANGE_TARGET, candidate


@pytest.mark.parametrize('known,domain,target,outer,image,expected_domain', [
    ('f(x)', '[1,2]', 'f(x+1)', None, '[0,1/2]', sp.Interval(0, 1)),
    ('f(2*x)', '[1,2]', 'f(x+1)', None, '[0,1/2]', sp.Interval(1, 3)),
    ('f(x)', '(1,2]', 'f(3-2*x)', None, '[-5,-1)', sp.Interval.Ropen(sp.Rational(1,2), 1)),
    ('f(2*x-1)', '[-1,2)', 'f(2-x)', None, '[0,5)', sp.Interval.Lopen(-1, 5)),
    ('f(1-3*x)', '(-2,1]', 'f(2*x+4)', None, '{3}', sp.Interval.Ropen(-3, sp.Rational(3,2))),
    ('f(x)', 'ℝ', 'f(-2*x+7)', None, '[0,+∞)', sp.S.Reals),
    ('f(x)', '[1,2]', 'f(x+1)', '[-1,3]', '[0,1/2]', sp.Interval(0, 1)),
    ('f(x)', '[1,1]', 'f(1)', None, '{7}', sp.S.Reals),
])
def test_transfer_requires_full_coverage_and_preserves_exact_range(known, domain, target, outer, image, expected_domain):
    value = candidate()
    goal = value['root']['goals'][1]
    for sibling in value['root']['goals']:
        sibling.update(known_call=known, known_domain=domain, known_range=image)
    goal['target_call'] = target
    if outer:
        goal['input_domain'] = outer
    before = deepcopy(value)
    ctx = build_context(value, RANGE_TARGET)
    assert ar.admitted(ctx)
    assert range_admitted(ctx, 'method-substitution-range')
    assert not range_admitted(ctx, 'method-quadratic-interval-range')
    result = ar.transfer_abstract_range(ctx)['outputs']
    assert result['domain'] == expected_domain
    actual = result['feasible_set']
    assert ar.independent_verify(value, RANGE_TARGET, actual)['status'] == 'verified'
    assert ar.image_endpoints(value, RANGE_TARGET, actual)['status'] == 'passed'
    assert ar.independent_verify(value, RANGE_TARGET, actual ^ sp.FiniteSet(1000))['status'] == 'math_failed'
    assert before == value


@pytest.mark.parametrize('changes', [
    {'input_domain': '[0,1/2]'},  # Only part of the known inputs.
    {'input_domain': '(0,1]'},  # A missing endpoint also loses coverage.
    {'input_domain': '[5,6]'},  # No valid input.
    {'target_call': 'f(1)'},  # Constant map cannot cover a nontrivial domain.
    {'target_call': 'f(x+1)/(x+2)'},  # Output arithmetic is not an input substitution.
    {'target_call': 'f(x^2)'},  # Non-affine transfer remains outside this contract.
])
def test_incomplete_or_unsupported_input_transfer_cannot_claim_known_image(changes):
    value = candidate()
    value['root']['goals'][1].update(changes)
    ctx = build_context(value, RANGE_TARGET)
    assert not ar.admitted(ctx)
    assert not range_admitted(ctx)
    if set(changes) == {'input_domain'}:
        assert ar.independent_verify(value, RANGE_TARGET, sp.Interval(0, sp.Rational(1, 2)))['status'] == 'math_failed'


def test_arbitrary_extra_facts_do_not_disappear_during_transfer():
    value = candidate()
    value['root']['facts'] = ['x>0']
    assert not ar.admitted(build_context(value, RANGE_TARGET))


def test_domain_card_recovers_inputs_in_the_known_calls_variable_before_target_domain():
    from shuxueshuo_server.graph_lesson.stage_three.abstract_range_presentation import (
        domain_prerequisite,
    )

    value = candidate()
    for goal in value['root']['goals']:
        goal.update(known_call='f(2*t)', known_domain='(-1,2]', target_call='f(x+1)')
    card = domain_prerequisite(build_context(value, RANGE_TARGET)['abstract_range_goal'])
    given = card['stem_board']['items'][0]['math']
    assert r't\in\left(-1, 2\right]' in given
    assert r'2\cdot t\in D_{f}=\left(-2, 4\right]' in given
    assert r'x+1\in\left(-2, 4\right]' in given
    assert r'x\in\left(-1, 2\right]' not in given
    assert card['stem_board']['items'][1]['math'] is None
    assert card['completion_board']['items'][1]['math'] == r'x\in\left(-3, 3\right]'
    assert RANGE_TARGET + '/known_call' in card['source_refs']


def test_singleton_input_cannot_claim_multiple_outputs():
    value = candidate()
    for goal in value['root']['goals']:
        goal['known_domain'] = '[1,1]'
    value['root']['goals'][1]['target_call'] = 'f(1)'
    assert not ar.admitted(build_context(value, RANGE_TARGET))
    assert ar.independent_verify(value, RANGE_TARGET, sp.Interval(0, sp.Rational(1, 2)))['status'] == 'math_failed'


def test_missing_known_range_repair_is_local_and_append_only():
    from shuxueshuo_server.graph_lesson.stage_one.repair_authority import (
        repair_violations,
    )
    value = candidate()
    value['root']['goals'][0].pop('known_range')
    grant = [{'path': '/root/goals/0', 'code': 'missing_condition', 'action': 'repair'}]
    repaired = deepcopy(value)
    repaired['root']['goals'][0]['known_range'] = '[0,1/2]'
    assert repair_violations(value, repaired, grant) == []
    for field, change in [('known_domain', '[0,2]'), ('target_call', 'f(x+2)'), ('kind', 'find_abstract_range')]:
        altered = deepcopy(repaired)
        altered['root']['goals'][0][field] = change
        assert repair_violations(value, altered, grant)
    assert repair_violations(value, repaired, [{'path': '/root', 'code': 'missing_condition', 'action': 'repair'}])
    altered = deepcopy(repaired)
    altered['root']['goals'][1]['known_range'] = '[0,1]'
    assert repair_violations(value, altered, grant)
