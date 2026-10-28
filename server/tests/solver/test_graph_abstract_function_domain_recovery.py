"""Recover D_f from a known nonzero affine composite's exact full domain."""

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_function_domain as domain,
)
from shuxueshuo_server.graph_lesson.stage_three import verification
from shuxueshuo_server.graph_lesson.stage_three.capabilities import CapabilityGap
from shuxueshuo_server.graph_lesson.stage_three.context import build_context

TARGET = '/root/goals/0'


def _candidate(known_call='f(x+2)', known='[-3,2]', target='f(2*x-1)', *, outer=None):
    goal = {'kind': 'find_abstract_domain', 'known_call': known_call,
            'known_domain': known, 'strength': 'exact', 'target_call': target}
    if outer is not None:
        goal['input_domain'] = outer
    return {'original_text': '抽象函数定义域恢复回归', 'root': {'goals': [goal]}}


@pytest.mark.parametrize(('candidate', 'input_range', 'expected'), [
    (_candidate(), sp.Interval(-1, 4), sp.Interval(0, sp.Rational(5, 2))),
    (_candidate('f(3-2*t)', '(-1,2]', 'f(2*u+1)'), sp.Interval.Ropen(-1, 5),
     sp.Interval.Ropen(-1, 2)),
    (_candidate('f(-t)', '(0,∞)', 'f(-2*x)'), sp.Interval.open(-sp.oo, 0),
     sp.Interval.open(0, sp.oo)),
    (_candidate('f(t/2-3)', '(-∞,2]', 'f(x+1)'), sp.Interval(-sp.oo, -2),
     sp.Interval(-sp.oo, -3)),
    (_candidate('f(2*t+1)', '{3}', 'f(1-x)'), sp.FiniteSet(7), sp.FiniteSet(-6)),
    (_candidate('f(2*t+1)', 'ℝ∖{0,1}', 'f(2*x+1)'), sp.S.Reals - sp.FiniteSet(1, 3),
     sp.S.Reals - sp.FiniteSet(0, 1)),
    (_candidate('f(2*t+3)', 'ℝ', 'f(0)', outer='(-1,1]'), sp.S.Reals,
     sp.Interval.Lopen(-1, 1)),
    (_candidate(target='f(4)'), sp.Interval(-1, 4), sp.S.Reals),
    (_candidate(target='f(5)'), sp.Interval(-1, 4), sp.S.EmptySet),
    (_candidate(known='(-3,2]', target='f(-1)'), sp.Interval.Lopen(-1, 4), sp.S.EmptySet),
    (_candidate('f(t)', '[-1,1]'), sp.Interval(-1, 1), sp.Interval(0, 1)),
    (_candidate('f(2*t-1)', '[0,0]', 'f(x)'), sp.FiniteSet(-1), sp.FiniteSet(-1)),
    (_candidate(outer='(0,2)'), sp.Interval(-1, 4), sp.Interval.open(0, 2)),
])
def test_affine_recovery_solver_and_original_relation_verification(candidate, input_range, expected):
    context = build_context(candidate, TARGET)
    assert domain.admitted(context), context['abstract_domain_goal']
    solved = domain.solve_abstract_function_domain(context)
    assert solved['outputs']['input_range'] == input_range
    assert solved['outputs']['candidate_set'] == expected
    recovery = solved['checks'][0]
    assert recovery['full_domain'] is True
    assert recovery['covers_all_real_inputs'] is True
    assert recovery['inverse_identities'] is True
    verified = domain.independent_verify(candidate, TARGET, expected)
    assert verified['status'] == 'verified'
    assert verified['checks'][1]['known_bijection_verified'] is True
    assert verification.endpoint_check(candidate, TARGET, expected)['status'] == 'passed'


def test_q26_preserves_known_domain_and_distinct_recovered_input_range():
    solved = domain.solve_abstract_function_domain(build_context(_candidate(), TARGET))
    assert solved['outputs']['known_domain'] == sp.Interval(-3, 2)
    assert solved['outputs']['input_range'] == sp.Interval(-1, 4)
    assert solved['outputs']['abstract_domain_result']['known_domain'] == sp.Interval(-3, 2)
    assert solved['checks'][0]['kind'] == 'abstract_known_affine_recovery'


def test_q26_endpoints_substitute_through_both_original_inputs():
    checked = verification.endpoint_check(_candidate(), TARGET, sp.Interval(0, sp.Rational(5, 2)))
    assert checked['status'] == 'passed'
    assert [row['evidence']['complete_input']['expression'] for row in checked['points']] == ['-1', '4']
    assert [row['evidence']['known_outer_input']['expression'] for row in checked['points']] == ['-3', '2']
    assert all(row['included'] and row['holds'] for row in checked['points'])


@pytest.mark.parametrize('known_call', ['f(0*x+1)', 'f(x-x+1)', 'f(x^2)'])
def test_non_bijective_known_call_is_not_admitted(known_call):
    context = build_context(_candidate(known_call), TARGET)
    assert domain.admitted(context) is False
    with pytest.raises(CapabilityGap):
        domain.solve_abstract_function_domain(context)


def test_zero_known_slope_description_is_rejected_at_capability_boundary():
    context = build_context(_candidate(), TARGET)
    context['abstract_domain_goal']['known_slope'] = '0'
    assert domain.admitted(context) is False
    with pytest.raises(CapabilityGap, match='nonzero_known_slope_required'):
        domain.solve_abstract_domain(context['abstract_domain_goal'])


def test_wrong_recovery_image_cannot_certify_itself(monkeypatch):
    candidate = _candidate()
    context = build_context(candidate, TARGET)
    monkeypatch.setattr(domain, 'affine_image', lambda *_: sp.Interval(-3, 2))
    wrong = domain.solve_abstract_function_domain(context)['outputs']['candidate_set']
    assert wrong == sp.Interval(-1, sp.Rational(3, 2))
    assert domain.independent_verify(candidate, TARGET, wrong)['status'] == 'verification_failed'
    assert verification.verify(candidate, TARGET, context, wrong)['status'] == 'math_failed'


def test_independent_recovery_uses_original_ast_and_no_solver_helpers(monkeypatch):
    candidate = _candidate()
    context = build_context(candidate, TARGET)
    context['abstract_domain_goal']['known_slope'] = '-1'
    context['abstract_domain_goal']['known_intercept'] = '0'
    wrong = domain.solve_abstract_function_domain(context)['outputs']['candidate_set']
    assert wrong != sp.Interval(0, sp.Rational(5, 2))

    def unavailable(*_):
        raise AssertionError('independent verification called execution helper')

    for name in ('solve_abstract_domain', 'affine_image', 'affine_preimage', '_domain_set', '_known_coeffs'):
        monkeypatch.setattr(domain, name, unavailable)
    assert domain.independent_verify(candidate, TARGET, wrong)['status'] == 'verification_failed'
    assert domain.independent_verify(candidate, TARGET, sp.Interval(0, sp.Rational(5, 2)))[
        'status'] == 'verified'


@pytest.mark.parametrize('wrong', [
    sp.Interval.open(0, sp.Rational(5, 2)),
    sp.Interval(0, sp.Rational(5, 2)) - sp.FiniteSet(1),
    sp.Interval(-1, sp.Rational(5, 2)),
    sp.S.EmptySet,
])
def test_recovery_verifier_rejects_boundary_interior_and_empty_tampering(wrong):
    assert domain.independent_verify(_candidate(), TARGET, wrong)['status'] == 'verification_failed'
