"""Mixed abstract-call and concrete-denominator domains, with source verification."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_function_domain as domain,
)
from shuxueshuo_server.graph_lesson.stage_three import verification
from shuxueshuo_server.graph_lesson.stage_three.context import build_context

TARGET = '/root/goals/0'


def _candidate(target='f(3-4*x)/sqrt(x-1)', known='[-3,1]', *, known_call='f(2*x-1)', outer=None):
    return {'original_text': '抽象函数与具体分母条件回归', 'root': {'goals': [{
        'kind': 'find_abstract_domain', 'known_call': known_call, 'known_domain': known,
        'target_call': target, 'strength': 'exact', **({'input_domain': outer} if outer else {}),
    }]}}


@pytest.mark.parametrize(('candidate', 'abstract', 'concrete', 'answer'), [
    (_candidate(), sp.Interval(sp.Rational(1, 2), sp.Rational(5, 2)),
     sp.Interval.open(1, sp.oo), sp.Interval.Lopen(1, sp.Rational(5, 2))),
    (_candidate('f(x)/sqrt(2-x)', '[-1,3]', known_call='f(t)'), sp.Interval(-1, 3),
     sp.Interval.open(-sp.oo, 2), sp.Interval.Ropen(-1, 2)),
    (_candidate('f(x)/(x-1)', '[-1,3]', known_call='f(t)'), sp.Interval(-1, 3),
     sp.S.Reals - sp.FiniteSet(1), sp.Interval(-1, 3) - sp.FiniteSet(1)),
    (_candidate('f(1)/(x-1)', '[-1,1]', known_call='f(t)'), sp.S.Reals,
     sp.S.Reals - sp.FiniteSet(1), sp.S.Reals - sp.FiniteSet(1)),
    (_candidate('f(2)/sqrt(x)', '[-1,1]', known_call='f(t)'), sp.S.EmptySet,
     sp.Interval.open(0, sp.oo), sp.S.EmptySet),
    (_candidate('f(x)/sqrt(2)', '[-1,1]', known_call='f(t)'), sp.Interval(-1, 1),
     sp.S.Reals, sp.Interval(-1, 1)),
    (_candidate('f(x)/(-2)', '[-1,1]', known_call='f(t)'), sp.Interval(-1, 1),
     sp.S.Reals, sp.Interval(-1, 1)),
    (_candidate('f(x)/(x+5)', '[0,1]', known_call='f(t)'), sp.Interval(0, 1),
     sp.S.Reals - sp.FiniteSet(-5), sp.Interval(0, 1)),
    (_candidate('f(x)/sqrt(x)', '[-2,-1]', known_call='f(t)'), sp.Interval(-2, -1),
     sp.Interval.open(0, sp.oo), sp.S.EmptySet),
    (_candidate(outer='(1,2)'), sp.Interval.open(1, 2), sp.Interval.open(1, sp.oo),
     sp.Interval.open(1, 2)),
    (_candidate('f(1)/sqrt(x)', 'ℝ', known_call='f(t)', outer='[-1,1]'), sp.Interval(-1, 1),
     sp.Interval.open(0, sp.oo), sp.Interval.Lopen(0, 1)),
    (_candidate('f(x)/(1-2*x)', '{1}', known_call='f(t)'), sp.FiniteSet(1),
     sp.S.Reals - sp.FiniteSet(sp.Rational(1, 2)), sp.FiniteSet(1)),
    (_candidate('f(x)/sqrt(x-1)', '{1}', known_call='f(t)'), sp.FiniteSet(1),
     sp.Interval.open(1, sp.oo), sp.S.EmptySet),
    (_candidate('f(2-x)/sqrt(3*x+1)', '(0,2]', known_call='f(1-2*t)'), sp.Interval.Lopen(1, 5),
     sp.Interval.open(-sp.Rational(1, 3), sp.oo), sp.Interval.Lopen(1, 5)),
])
def test_mixed_exact_domains(candidate, abstract, concrete, answer):
    context = build_context(candidate, TARGET)
    assert domain.admitted(context), context['abstract_domain_goal']
    solved = domain.solve_abstract_function_domain(context)
    outputs = solved['outputs']
    assert outputs['has_concrete_conditions'] is True
    assert outputs['abstract_domain'] == abstract
    assert outputs['concrete_domain'] == concrete
    assert outputs['candidate_set'] == answer
    assert sp.Intersection(*outputs['concrete_solutions']) == concrete
    assert domain.independent_verify(candidate, TARGET, answer)['status'] == 'verified'
    assert verification.endpoint_check(candidate, TARGET, answer)['status'] == 'passed'


def test_s3_preserves_both_radical_denominator_sources_and_normalization():
    context = build_context(_candidate(), TARGET)
    extracted = domain.extract_abstract_concrete_conditions(context['abstract_domain_goal'])
    rows = extracted['outputs']['concrete_constraints']
    by_kind = {row['kind']: row for row in rows}
    assert len(rows) == 2
    assert by_kind['denominator_nonzero']['ast_path'] == [2]
    assert by_kind['radicand_nonnegative']['ast_path'] == [2, 2]
    assert all(row['source_ref'] == TARGET + '/target_call' for row in rows)
    x = sp.Symbol('x', real=True)
    assert by_kind['denominator_nonzero']['condition'] == sp.Ne(sp.sqrt(x - 1), 0, evaluate=False)
    assert by_kind['radicand_nonnegative']['condition'] == sp.Ge(x - 1, 0, evaluate=False)
    projection = extracted['checks'][0]
    assert projection['kind'] == 'abstract_denominator_only_projection'
    assert projection['whole_target_equivalence_claimed'] is False
    assert projection['original_target_ast'] == context['abstract_domain_goal']['target_call_ast']
    assert projection['projection_expression_ast'][1] == ['number', '1']
    assert projection['original_target_ast'][1][0] == 'function_call'
    solved = domain.solve_abstract_function_domain(context)
    assert solved['outputs']['raw_concrete_conditions'] == extracted['outputs']['raw_concrete_conditions']
    assert set(solved['outputs']['concrete_conditions']) == {
        sp.Ne(x - 1, 0, evaluate=False), sp.Ge(x - 1, 0, evaluate=False),
    }


def test_redundant_denominator_still_keeps_its_source_and_solution():
    solved = domain.solve_abstract_function_domain(build_context(
        _candidate('f(x)/(x+5)', '[0,1]', known_call='f(t)'), TARGET,
    ))
    outputs = solved['outputs']
    assert outputs['candidate_set'] == outputs['abstract_domain']
    assert len(outputs['concrete_constraints']) == len(outputs['concrete_solutions']) == 1
    assert outputs['concrete_constraints'][0]['kind'] == 'denominator_nonzero'
    assert outputs['concrete_solutions'][0] == sp.S.Reals - sp.FiniteSet(-5)


def test_endpoint_at_radical_zero_retains_both_original_truth_values():
    checked = verification.endpoint_check(_candidate(), TARGET, sp.Interval.Lopen(1, sp.Rational(5, 2)))
    lower = checked['points'][0]
    assert lower['point']['expression'] == '1'
    assert lower['included'] is lower['holds'] is False
    assert lower['evidence']['input_in_known_domain'] is True
    assert lower['evidence']['concrete_conditions_hold'] is False
    rows = {row['kind']: row for row in lower['evidence']['concrete_conditions']}
    assert rows['radicand_nonnegative']['holds'] is True
    assert rows['denominator_nonzero']['holds'] is False


@pytest.mark.parametrize('target', ['f(x)/0', 'f(x)/sqrt(0)', 'f(x)/sqrt(-1)',
                                   'f(x)/(x-x)', 'f(x)/sqrt(x-x-1)'])
def test_invalid_constant_original_expressions_never_enter_public_solver(target):
    candidate = _candidate(target)
    features = extract_features(candidate)
    if features['ok']:
        description = next(row['value'] for row in features['features']
                           if row['feature_id'] == 'abstract_function_domain')
        assert description['structure_supported'] is False
        assert domain.admitted(build_context(candidate, TARGET)) is False


def test_concrete_solver_omission_cannot_verify_itself(monkeypatch):
    original = domain._solve_concrete_conditions

    def omit_concrete(description, variable):
        result = deepcopy(original(description, variable))
        result['outputs']['concrete_domain'] = sp.S.Reals
        return result

    monkeypatch.setattr(domain, '_solve_concrete_conditions', omit_concrete)
    candidate = _candidate()
    context = build_context(candidate, TARGET)
    wrong = domain.solve_abstract_function_domain(context)['outputs']['candidate_set']
    assert wrong == sp.Interval(sp.Rational(1, 2), sp.Rational(5, 2))
    assert domain.independent_verify(candidate, TARGET, wrong)['status'] == 'verification_failed'
    assert verification.verify(candidate, TARGET, context, wrong)['status'] == 'math_failed'


def test_mixed_verifier_reads_raw_target_without_s3_or_solver(monkeypatch):
    def forbidden(*_):
        raise AssertionError('verification reused extraction or solving')

    for name in ('extract_abstract_concrete_conditions', '_solve_concrete_conditions',
                 '_concrete_projection_ast', 'affine_image', 'affine_preimage', '_domain_set'):
        monkeypatch.setattr(domain, name, forbidden)
    correct = sp.Interval.Lopen(1, sp.Rational(5, 2))
    assert domain.independent_verify(_candidate(), TARGET, correct)['status'] == 'verified'
    assert domain.independent_verify(_candidate(), TARGET, sp.Interval(1, sp.Rational(5, 2)))[
        'status'] == 'verification_failed'


def test_plain_target_keeps_empty_concrete_outputs_and_full_real_concrete_domain():
    context = build_context(_candidate('f(3-4*x)'), TARGET)
    outputs = domain.solve_abstract_function_domain(context)['outputs']
    assert outputs['has_concrete_conditions'] is False
    assert outputs['concrete_constraints'] == outputs['raw_concrete_conditions'] == []
    assert outputs['concrete_conditions'] == outputs['concrete_solutions'] == []
    assert outputs['concrete_domain'] == sp.S.Reals
    assert outputs['candidate_set'] == outputs['abstract_domain']
