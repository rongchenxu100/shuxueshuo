"""Batch-1 affine preimage branches for M2 abstract-function domain."""

from hashlib import sha256
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_three import (
    abstract_function_domain,
    verification,
)
from shuxueshuo_server.graph_lesson.stage_three.abstract_function_domain import (
    admitted,
    affine_preimage,
    independent_verify,
    solve_abstract_domain,
    solve_abstract_function_domain,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.problem_understanding.notation_parser import parse


def test_affine_preimage_positive_slope_closed():
    domain = sp.Interval(-3, 2)
    assert affine_preimage(domain, 2, -1) == sp.Interval(-1, sp.Rational(3, 2))


def test_affine_preimage_negative_slope_swaps_openness():
    domain = sp.Interval(-1, 2, left_open=True, right_open=False)
    assert affine_preimage(domain, -2, 3) == sp.Interval(
        sp.Rational(1, 2), 2, left_open=False, right_open=True,
    )


def test_affine_preimage_zero_slope_member_is_reals():
    assert affine_preimage(sp.Interval(-1, 1), 0, 0) == sp.S.Reals


def test_affine_preimage_zero_slope_nonmember_is_empty():
    assert affine_preimage(sp.Interval(-1, 1), 0, 2) == sp.S.EmptySet


def test_affine_preimage_singleton():
    assert affine_preimage(sp.FiniteSet(1), 2, -1) == sp.FiniteSet(1)


def test_affine_preimage_unbounded():
    domain = sp.Interval(0, sp.oo, left_open=True)
    assert affine_preimage(domain, -1, 0) == sp.Interval(-sp.oo, 0, right_open=True)


def _description(*, known='[-3,2]', slope='2', intercept='-1', outer=None, latex='2x-1'):
    domain = parse(known)
    if domain[0] == 'tuple':
        domain = ['interval', False, False, *domain[1:]]
    outer_ast = ['real']
    if outer:
        outer_ast = parse(outer)
        if outer_ast[0] == 'tuple':
            outer_ast = ['interval', False, False, *outer_ast[1:]]
    return {
        'structure_supported': True,
        'known_form': 'identity',
        'known_strength': 'exact',
        'function_name': 'f',
        'variable': 'x',
        'known_domain_ast': domain,
        'outer_domain_ast': outer_ast,
        'target_slope': slope,
        'target_intercept': intercept,
        'target_argument_latex': latex,
    }


def test_q25_solve_identity_affine():
    result = solve_abstract_domain(_description())
    assert result['outputs']['candidate_set'] == sp.Interval(-1, sp.Rational(3, 2))
    assert result['outputs']['input_range'] == sp.Interval(-3, 2)
    assert result['outputs']['board']['lower_label'].startswith('$f$')


def test_q25_with_outer_restriction():
    result = solve_abstract_domain(_description(outer='(0,2)'))
    assert result['outputs']['candidate_set'] == sp.Interval(
        0, sp.Rational(3, 2), left_open=True, right_open=False,
    )


def _candidate(known='[-3,2]', target='f(2*x-1)', *, known_call='f(x)', outer=None):
    goal = {'kind': 'find_abstract_domain', 'known_call': known_call,
            'known_domain': known, 'strength': 'exact', 'target_call': target}
    if outer is not None:
        goal['input_domain'] = outer
    return {'original_text': '抽象函数定义域回归', 'root': {'goals': [goal]}}


@pytest.mark.parametrize(('candidate', 'expected'), [
    (_candidate(), sp.Interval(-1, sp.Rational(3, 2))),
    (_candidate('(-1,2]', 'f(3-2*x)'), sp.Interval.Ropen(sp.Rational(1, 2), 2)),
    (_candidate('[-1,1]', 'f(1)'), sp.S.Reals),
    (_candidate('[-1,1]', 'f(2)'), sp.S.EmptySet),
    (_candidate('[-1,1]', 'f(1)', outer='(0,2]'), sp.Interval.Lopen(0, 2)),
    (_candidate('[-1,1]', 'f(2)', outer='(0,2]'), sp.S.EmptySet),
    (_candidate('ℝ'), sp.S.Reals),
    (_candidate('(-∞,∞)'), sp.S.Reals),
    (_candidate('ℝ', 'f(1)', outer='{2}'), sp.FiniteSet(2)),
    (_candidate('{1}'), sp.FiniteSet(1)),
    (_candidate('(0,∞)', 'f(-x)'), sp.Interval.open(-sp.oo, 0)),
    (_candidate('(-∞,2]', 'f(2-x)'), sp.Interval(0, sp.oo)),
    (_candidate(outer='(0,2)'), sp.Interval.Lopen(0, sp.Rational(3, 2))),
    (_candidate('[1,2]', 'f(x)', outer='(-∞,0)'), sp.S.EmptySet),
    (_candidate(known_call='f(t)'), sp.Interval(-1, sp.Rational(3, 2))),
    (_candidate(target='f(2*u-1)', known_call='f(t)'), sp.Interval(-1, sp.Rational(3, 2))),
    (_candidate('[-1,1]', 'f(x-x+1)', known_call='f(t)'), sp.S.Reals),
    (_candidate('ℝ∖{0,1}', 'f(2*x)'), sp.S.Reals - sp.FiniteSet(0, sp.Rational(1, 2))),
])
def test_source_admission_solver_and_independent_verifier(candidate, expected):
    target = '/root/goals/0'
    features = extract_features(candidate)['features']
    description = next(row['value'] for row in features
                       if row['feature_id'] == 'abstract_function_domain')
    assert description['structure_supported'] is True, description['reason']
    context = build_context(candidate, target)
    assert admitted(context)
    result = solve_abstract_function_domain(context)
    assert result['outputs']['candidate_set'] == expected
    verified = independent_verify(candidate, target, expected)
    assert verified['status'] == 'verified'
    assert verified['checks'][1]['kind'] == 'abstract_original_relation_partition'
    assert verification.endpoint_check(candidate, target, expected)['status'] == 'passed'


def test_known_dummy_and_target_variable_have_separate_identities():
    context = build_context(_candidate(known_call='f(t)'), '/root/goals/0')
    description = context['abstract_domain_goal']
    assert description['known_variable'] == 't'
    assert description['variable'] == 'x'
    assert description['known_argument_latex'] == 't'
    assert 'x' in description['target_argument_latex']


def test_wrong_solver_output_cannot_certify_itself(monkeypatch):
    candidate = _candidate()
    target = '/root/goals/0'
    context = build_context(candidate, target)
    wrong = sp.Interval(-3, 2)
    monkeypatch.setattr(abstract_function_domain, 'affine_preimage', lambda *_: wrong)
    assert solve_abstract_function_domain(context)['outputs']['candidate_set'] == wrong
    assert independent_verify(candidate, target, wrong)['status'] == 'verification_failed'
    assert verification.verify(candidate, target, context, wrong)['status'] == 'math_failed'
    endpoints = verification.endpoint_check(candidate, target, wrong)
    assert endpoints['status'] == 'failed'
    assert [row['holds'] for row in endpoints['points']] == [False, False]
    assert [row['evidence']['complete_input']['expression']
            for row in endpoints['points']] == ['-7', '3']
    assert all(row['passed'] is False for row in endpoints['points'])


def test_verifier_ignores_solver_coefficients_and_set_conversion(monkeypatch):
    candidate = _candidate()
    context = build_context(candidate, '/root/goals/0')
    context['abstract_domain_goal']['target_slope'] = '1'
    context['abstract_domain_goal']['target_intercept'] = '0'
    wrong = solve_abstract_function_domain(context)['outputs']['candidate_set']
    assert wrong == sp.Interval(-3, 2)
    monkeypatch.setattr(abstract_function_domain, '_domain_set', lambda *_: sp.S.Reals)
    assert independent_verify(candidate, '/root/goals/0', wrong)['status'] == 'verification_failed'
    assert independent_verify(candidate, '/root/goals/0', sp.Interval(-1, sp.Rational(3, 2)))[
        'status'] == 'verified'


def test_endpoint_membership_checks_outer_range_and_original_input():
    candidate = _candidate(outer='(0,2)')
    answer = sp.Interval.Lopen(0, sp.Rational(3, 2))
    endpoints = verification.endpoint_check(candidate, '/root/goals/0', answer)
    assert endpoints['status'] == 'passed'
    first, last = endpoints['points']
    assert first['holds'] is False
    assert first['evidence']['input_in_known_domain'] is True
    assert first['evidence']['outer_domain_contains'] is False
    assert last['holds'] is True
    assert last['evidence']['complete_input']['expression'] == '2'


@pytest.mark.parametrize('wrong', [
    sp.Interval.open(-1, sp.Rational(3, 2)),
    sp.Interval(-1, sp.Rational(3, 2)) - sp.FiniteSet(0),
    sp.Interval(-2, sp.Rational(3, 2)),
    sp.S.EmptySet,
])
def test_independent_partition_rejects_endpoint_interior_and_empty_tampering(wrong):
    assert independent_verify(_candidate(), '/root/goals/0', wrong)['status'] == 'verification_failed'


@pytest.mark.parametrize('relative', [
    'server/shuxueshuo_server/graph_lesson/stage_one/abstract_function_domain.py',
    'server/shuxueshuo_server/graph_lesson/stage_three/abstract_function_domain.py',
    'server/shuxueshuo_server/problem_understanding/notation_abstract_domain.py',
])
def test_abstract_domain_source_bytes_are_frozen_in_math_fingerprint(tmp_path, monkeypatch, relative):
    from shuxueshuo_server.graph_lesson.stage_three import runner

    source = runner.ROOT / relative
    read_bytes = Path.read_bytes
    original = read_bytes(source)
    frozen = runner.fingerprint()
    assert frozen[relative] == sha256(original).hexdigest()
    # Exercise real changed source bytes from a copy, without racing developers
    # or other tests by writing the live checked-out implementation.
    copy = tmp_path / source.name
    copy.write_bytes(original + b'\n# changed mathematical implementation\n')

    def dependency_bytes(path):
        return read_bytes(copy) if path.resolve() == source.resolve() else read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', dependency_bytes)
    changed = runner.fingerprint()
    assert {key for key in frozen if frozen[key] != changed[key]} == {relative}
    copy.write_bytes(original)
    assert runner.fingerprint() == frozen
