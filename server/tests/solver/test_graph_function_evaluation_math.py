"""M9 bound substitution, original domains, proof and occurrence regressions."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import sympy as sp
from shuxueshuo_server.graph_lesson import function_evaluation as m9
from shuxueshuo_server.graph_lesson.stage_one.function_evaluation import inspect_evaluation_target
from shuxueshuo_server.problem_understanding.notation_parser import NotationError

FIXTURES = Path(__file__).parent / 'fixtures/function-evaluation'
U = ['bound', 'function_argument']
X = ['ref', 'outer:x', 'scalar']
N = lambda value: ['number', str(value)]
CALL = lambda name, argument: ['function_call', ['ref', name, 'function'], argument]


def function(name, body, domain=None):
    result = {'function_ref': name, 'function_name': name, 'source_ref': f'def:{name}', 'expression_ast': body}
    if domain is not None:
        result.update(input_domain_ast=domain, explicit_domain=True, input_domain_source_ref=f'domain:{name}')
    return result


def description(expression, functions, *, variable=True, kind='find_value', domain=None):
    return {'kind': kind, 'target_ref': '/root/goals/0', 'expression_ast': expression,
            'functions': functions, 'variable_ref': X[1] if variable else '', 'variable': 'x',
            'input_domain_ast': domain if domain is not None else ['real']}


def solved(desc):
    assert m9.structural_inspect(desc)['structure_supported']
    result = m9.evaluate(desc)
    assert m9.verify(desc, result)
    return result


def test_all_nine_compiled_development_targets():
    expected = {'q28a': [sp.Integer(2), sp.Rational(1, 3)], 'q28b': [sp.Rational(-1, 4), sp.Integer(1)],
                'q28c': [None, None], 'q28d': [None], 'q29b': [sp.Integer(3), sp.Rational(603, 2)]}
    for name, values in expected.items():
        candidate = json.loads((FIXTURES / f'{name}-candidate.json').read_text())
        for index, value in enumerate(values):
            desc = inspect_evaluation_target(candidate, f'/root/goals/{index}')
            result = solved(desc)
            if value is not None:
                assert result['value'] == value, (name, index, result)
            if name == 'q29b' and index == 1:
                assert (result['term_count'], result['pair_count'], result['leftover_count']) == (201, 100, 1)


def test_bound_names_and_nested_order():
    f = function('f', ['-', ['*', N(3), ['^', U, N(2)]], N(1)])
    g = function('g', ['/', N(1), ['+', U, N(2)]])
    left = solved(description(CALL('f', CALL('g', N(0))), [f, g], variable=False))
    right = solved(description(CALL('g', CALL('f', N(0))), [f, g], variable=False))
    assert left['value'] == sp.Rational(-1, 4) and right['value'] == 1
    assert [row['function_ref'] for row in left['calls']] == ['g', 'f']
    assert [row['function_ref'] for row in right['calls']] == ['f', 'g']
    result = solved(description(CALL('f', ['-', X, N(1)]), [f]))
    x = result['variable']
    assert sp.expand(result['expression']) == 3*x*x - 6*x + 2


def test_original_conditions_survive_cancellation_and_constant_body():
    g = function('g', ['/', N(1), ['+', U, N(2)]])
    desc = description(CALL('g', ['-', ['/', N(1), X], N(1)]), [g])
    result = solved(desc)
    assert result['domain'] == sp.S.Reals - sp.FiniteSet(0, -1)
    assert len(result['constraints']) == 2
    assert {row['source_ref'] for row in result['constraints']} == {'/root/goals/0', 'def:g'}
    bad = deepcopy(result)
    bad['domain'] = sp.S.Reals - sp.FiniteSet(-1)
    assert not m9.verify(desc, bad)
    constant = solved(description(CALL('h', ['/', N(1), X]), [function('h', N(5))]))
    assert constant['expression'] == 5 and constant['domain'] == sp.S.Reals - sp.FiniteSet(0)


def test_uncancelled_body_and_illegal_numeric_input():
    h = function('h', ['/', ['-', ['^', U, N(2)], N(1)], ['-', U, N(1)]])
    result = solved(description(CALL('h', X), [h]))
    assert result['expression'] == result['variable'] + 1
    assert result['domain'] == sp.S.Reals - sp.FiniteSet(1)
    result = solved(description(CALL('h', N(1)), [h], variable=False))
    assert not result['defined'] and result['value'] is None


def test_explicit_domain_preimage_singletons_and_conflicts():
    f = function('f', ['^', U, N(2)], ['interval', True, True, N(0), N(2)])
    assert solved(description(CALL('f', ['-', X, N(1)]), [f]))['domain'] == sp.Interval(1, 3)
    h = function('h', ['/', N(1), U], ['interval', True, True, N(0), N(2)])
    with pytest.raises(NotationError, match='declared_domain_conflict'):
        m9.evaluate(description(CALL('h', N(1)), [h], variable=False))
    result = solved(description(CALL('f', X), [function('f', U, ['set', N(2)])], kind='check_constant'))
    assert result['is_constant'] is True and result['value'] == 2


def test_composite_quadratic_denominator_keeps_irrational_roots_and_empty_domain():
    f = function('f', ['^', U, N(2)])
    g = function('g', ['/', N(1), ['-', U, N(2)]])
    result = solved(description(CALL('g', CALL('f', X)), [f, g]))
    assert result['domain'] == sp.S.Reals - sp.FiniteSet(-sp.sqrt(2), sp.sqrt(2))
    result = solved(description(CALL('g', CALL('f', X)), [function('f', N(2)), g]))
    assert not result['defined'] and result['domain'] == sp.S.EmptySet


def test_constant_verdict_uses_actual_domain():
    h = function('h', U)
    expr = ['+', CALL('h', X), CALL('h', ['/', N(1), X])]
    desc = description(expr, [h], kind='check_constant')
    result = solved(desc)
    assert result['is_constant'] is False and len(result['witness']) == 2
    forged = deepcopy(result)
    forged.update(is_constant=True, value=sp.Integer(2))
    assert not m9.verify(desc, forged)
    desc['input_domain_ast'] = ['set', N(1)]
    result = solved(desc)
    assert result['is_constant'] and result['value'] == 2
    desc['input_domain_ast'] = ['set']
    result = solved(desc)
    assert not result['defined'] and result['is_constant'] is None


def summation(n=7, extra=()):
    f = function('f', ['/', ['+', U, N(2)], ['+', U, N(1)]])
    index = ['ref', 'sum:n', 'scalar']
    return {'kind': 'finite_sum', 'target_ref': '/root/goals/1', 'functions': [f], 'terms': [
        {'expression_ast': CALL('f', index), 'index_ref': index[1], 'lower': 1, 'upper': n},
        {'expression_ast': CALL('f', ['/', N(1), index]), 'index_ref': index[1], 'lower': 2, 'upper': n},
        *({'expression_ast': CALL('f', N(value))} for value in extra)]}


@pytest.mark.parametrize('n', [1, 2, 7, 29])
def test_pair_counts_vary_with_indices(n):
    result = solved(summation(n))
    assert result['total'] == 3*n-sp.Rational(3, 2)
    assert (result['term_count'], result['pair_count'], result['leftover_count']) == (2*n-1, n-1, 1)


def test_sum_duplicates_leftovers_invalid_terms_and_tampering():
    desc = summation(5, extra=(1, 7, 7))
    result = solved(desc)
    assert result['leftover_count'] == 4 and result['total'] == sp.Rational(69, 4)
    for mutate in (lambda r: r.update(pair_count=99), lambda r: r['leftovers'].pop(),
                   lambda r: r['terms'].pop(), lambda r: r.update(total=sp.Integer(99)),
                   lambda r: r['pairs'][0].update(right_id=r['pairs'][0]['left_id'])):
        bad = deepcopy(result)
        mutate(bad)
        assert not m9.verify(desc, bad)
    result = solved(summation(5, extra=(-1,)))
    assert not result['defined'] and result['total'] is None


def test_nonconstant_pair_falls_back_to_exact_sum():
    desc = summation(3)
    desc['functions'][0]['expression_ast'] = U
    result = solved(desc)
    assert result['pairing'] is None and result['pair_count'] == 0
    assert result['total'] == sp.Rational(41, 6)


def test_budgets_undeclared_variables_and_recursion_fail_closed():
    f = function('f', U)
    desc = description(CALL('f', CALL('f', CALL('f', X))), [f])
    assert not m9.structural_inspect(desc)['structure_supported']
    desc = description(CALL('f', ['ref', 'other:x', 'scalar']), [f])
    assert not m9.structural_inspect(desc)['structure_supported']
    desc = description(CALL('f', X), [function('f', CALL('f', U))])
    assert not m9.structural_inspect(desc)['structure_supported']
    desc = summation(m9.MAX_SUM_TERMS)
    assert not m9.structural_inspect(desc)['structure_supported']
    with pytest.raises(NotationError, match='sum_budget'):
        m9.evaluate(desc)


def test_codec_roundtrip_preserves_results_and_substitution_teaching_text():
    from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value, decode_value
    for name in ('q28a', 'q28b', 'q28c', 'q28d', 'q29b'):
        candidate = json.loads((FIXTURES / f'{name}-candidate.json').read_text())
        for index in range(len(candidate['root']['goals'])):
            desc = inspect_evaluation_target(candidate, f'/root/goals/{index}')
            result = solved(desc)
            restored = decode_value(encode_value(result))
            assert m9.verify(desc, restored)
            assert [row['substitution_latex'] for row in restored['calls']] == [row['substitution_latex'] for row in result['calls']]


def test_metadata_trials_and_pairing_evidence_cannot_be_forged():
    candidate = json.loads((FIXTURES / 'q29b-candidate.json').read_text())
    desc = inspect_evaluation_target(candidate, '/root/goals/0')
    result = solved(desc)
    assert len(result['trials']) == 2
    for mutate in (lambda r: r['constraints'].pop(), lambda r: r['calls'][0].update(output=sp.Integer(999)),
                   lambda r: r['trials'][0].update(total=sp.Integer(999)),
                   lambda r: r['calls'][0].update(substitution_latex='0')):
        bad = deepcopy(result)
        mutate(bad)
        assert not m9.verify(desc, bad)
    desc = summation(3)
    result = solved(desc)
    for mutate in (lambda r: r['pairing'].update(expression=sp.Integer(999)),
                   lambda r: r['pairs'][0].update(left_input=sp.Integer(10)),
                   lambda r: r['terms'][0].update(input=sp.Integer(10))):
        bad = deepcopy(result)
        mutate(bad)
        assert not m9.verify(desc, bad)


def test_expansion_is_bounded_before_sympy_expands():
    expression = X
    for _ in range(20):
        expression = ['^', expression, N(2)]
    desc = description(CALL('f', expression), [function('f', U)])
    assert m9.structural_inspect(desc)['reason'] == 'function_evaluation.expansion_budget'
    desc = description(['+', N(1), N(2)], [function('f', U)], variable=False)
    assert m9.structural_inspect(desc)['reason'] == 'function_evaluation.function_call_required'


def test_invalid_argument_and_invalid_function_never_publish_placeholder_outputs():
    desc = description(CALL('h', ['/', N(1), N(0)]), [function('h', N(5))], variable=False)
    result = solved(desc)
    assert not result['defined'] and result['value'] is None
    assert result['calls'][0]['output'] is None
    assert result['calls'][0]['input'] is None and not result['calls'][0]['input_defined']
    assert not result['calls'][0]['defined']
    desc = description(CALL('g', N(-2)), [function('g', ['/', N(1), ['+', U, N(2)]])], variable=False)
    result = solved(desc)
    assert result['calls'][0]['input'] == -2 and result['calls'][0]['input_defined']
    assert result['calls'][0]['output'] is None
    desc = description(CALL('g', N(0)), [function('g', ['/', N(1), N(0)])], variable=False)
    assert not m9.structural_inspect(desc)['structure_supported']


def test_empty_index_block_and_negative_fixed_point_occurrences():
    desc = summation(0)
    result = solved(desc)
    assert (result['term_count'], result['pair_count'], result['leftover_count'], result['total']) == (0, 0, 0, 0)
    desc = summation(0, extra=(-1, -1, 2))
    desc['functions'][0]['expression_ast'] = ['/', U, ['^', ['+', U, N(2)], N(0)]]
    # Use a valid affine body with no poles: inverse-pair sum is nonconstant,
    # so each fixed-point occurrence is explicitly retained by direct summation.
    desc['functions'][0]['expression_ast'] = U
    result = solved(desc)
    assert result['total'] == 0 and result['leftover_count'] == 3
    assert len({row['occurrence_id'] for row in result['terms']}) == 3


def test_explicit_multi_point_domain_and_constant_claim_certificate():
    desc = description(CALL('h', X), [function('h', ['^', U, N(2)], ['set', N(-1), N(1)])], kind='check_constant')
    result = solved(desc)
    assert result['is_constant'] and result['value'] == 1
    bad = deepcopy(result)
    bad['proof']['inputs'] = [sp.Integer(1)]
    assert not m9.verify(desc, bad)


def restricted_square_sum(domain, inputs):
    return {'kind': 'finite_sum', 'target_ref': '/root/goals/0',
            'functions': [function('f', ['^', U, N(2)], domain)],
            'terms': [{'expression_ast': CALL('f', N(value))} for value in inputs]}


def test_optional_pairing_singleton_domain_does_not_block_direct_sum():
    desc = restricted_square_sum(['interval', True, True, N(1), N(2)], (1, 2))
    result = solved(desc)
    assert result['total'] == 5
    assert result['pair_count'] == 0 and result['leftover_count'] == 2
    assert result['pairing']['domain'] == sp.FiniteSet(1)
    assert result['pairing']['constant'] == 2
    assert result['pairing']['proof'] == {'kind': 'complete_finite_domain', 'inputs': [sp.Integer(1)]}


def test_pairing_can_use_a_complete_finite_domain_proof():
    desc = restricted_square_sum(['set', N(2), N('1/2')], (2, '1/2'))
    result = solved(desc)
    assert result['total'] == sp.Rational(17, 4)
    assert result['pair_count'] == 1 and result['leftover_count'] == 0
    assert result['pairing']['proof'] == {'kind': 'complete_finite_domain',
                                         'inputs': [sp.Rational(1, 2), sp.Integer(2)]}
    for mutate in (
            lambda r: r['pairing'].update(constant=sp.Integer(3)),
            lambda r: r['pairing']['proof'].update(inputs=[sp.Integer(2)]),
            lambda r: r['pairing'].update(domain=sp.FiniteSet(2)),
            lambda r: r['pairing'].pop('proof'),
            lambda r: r['pairing'].update(proof={'kind': 'rational_identity', 'residual': sp.S.Zero})):
        bad = deepcopy(result)
        mutate(bad)
        assert not m9.verify(desc, bad)


def test_pairing_checks_every_legal_point_before_using_the_claim():
    desc = restricted_square_sum(['set', N(1), N(2), N('1/2')], (2, '1/2'))
    result = solved(desc)
    assert result['total'] == sp.Rational(17, 4)
    assert result['pairing'] is None and result['pair_count'] == 0
    # A true claim on two selected points cannot erase the third legal input.
    subset = solved(restricted_square_sum(['set', N(2), N('1/2')], (2, '1/2')))
    forged = deepcopy(result)
    forged['pairing'] = subset['pairing']
    assert not m9.verify(desc, forged)
