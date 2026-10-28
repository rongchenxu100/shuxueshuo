"""Q19's M1 extension preserves original guards within a shared exact boundary."""

from copy import deepcopy

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_one.function_domain import (
    ARGUMENT,
    MAX_EXCLUDED_POINTS,
    _fixed_poly,
    _input_domain,
    inspect_domain_target,
)
from shuxueshuo_server.graph_lesson.stage_three import driver, function_domain
from shuxueshuo_server.problem_understanding.notation_parser import NotationError
from tests.solver.test_graph_stage_three_function_domain import (
    TARGET,
    candidate,
    execute,
)


@pytest.mark.parametrize('body', [
    '2*x^2+1', '-2*x^2-1', 'x^2-1', '1-x^2', '(x-1)^2', '-(x-1)^2',
    '2*x-3', '-2*x+3', '0*x^2+2*x-3', '0*x^2+0*x+3', '3', '-3', '0',
])
@pytest.mark.parametrize('wrapper', ['sqrt(({body})^2)', 'abs({body})'])
def test_polynomial_square_and_absolute_domains_cover_all_rational_sign_branches(body, wrapper):
    original = candidate(wrapper.format(body=body))
    frozen = deepcopy(original)
    context, state = execute(original)
    assert context['domain_goal']['structure_supported']
    assert state['status'] == 'method_complete', state['diagnostics']
    assert driver.export_values(state)['feasible_set'] == sp.S.Reals
    assert state['verification']['status'] == 'verified'
    assert function_domain.verify_domain(original, TARGET, context, sp.S.EmptySet)['status'] == 'math_failed'
    assert original == frozen


@pytest.mark.parametrize('expression,excluded', [
    ('((2*x^2+1)*(x+1))/(x+1)', [-1]),
    ('((x^2-1)*(-2*x+3))/(-2*x+3)', [sp.Rational(3, 2)]),
    ('((0*x^2)*(x-1))/(x-1)', [1]),
    ('abs(x^2-1)/(x-1)', [1]),
    ('sqrt((x^2-1)^2)/(x+1)', [-1]),
    ('1/sqrt((x^2-1)^2)', [-1, 1]),
    ('1/sqrt(((x-1)^2)^2)', [1]),
    ('1/sqrt((-2*x+3)^2)', [sp.Rational(3, 2)]),
])
def test_original_divisor_guards_survive_cancellation_and_square_reduction(expression, excluded):
    original = candidate(expression)
    context, state = execute(original)
    expected = sp.S.Reals - sp.FiniteSet(*excluded)
    assert state['status'] == 'method_complete', state['diagnostics']
    assert driver.export_values(state)['feasible_set'] == expected
    assert state['verification']['status'] == 'verified'
    assert function_domain.verify_domain(original, TARGET, context, sp.S.Reals)['status'] == 'math_failed'
    constraints = function_domain.extract_domain_conditions(context)['outputs']['constraints']
    assert any(row['kind'] == 'denominator_nonzero' for row in constraints)
    endpoints = function_domain.domain_endpoints(original, TARGET, expected)
    assert endpoints['status'] == 'passed'
    assert all(row['passed'] for row in endpoints['points'])


def test_square_normalization_retains_source_and_independent_base_root_evidence():
    original = candidate('1/sqrt((x^2-1)^2)')
    context, state = execute(original)
    extracted = function_domain.extract_domain_conditions(context)['outputs']
    rows = extracted['constraints']
    radical = next(row for row in rows if row['kind'] == 'radicand_nonnegative')
    assert radical['ast_path'] == [2, 2]
    assert radical['expression_ast'][0] == '^'
    assert radical['condition'].lhs == (extracted['variable']**2 - 1)**2
    prepared = function_domain.prepare_domain_conditions(rows, extracted['variable'])
    assert sp.true in prepared['outputs']['conditions']
    assert all(check['square_structure']['passed'] for check in prepared['checks'])
    critical = state['verification']['proof']['critical_polynomials']
    assert len(critical) == 1
    assert critical[0]['ast_path'] == [2, 2, 1]
    assert critical[0]['square_structure']['ast_path'] == [2, 2]
    assert {source['kind'] for source in critical[0]['condition_sources']} == {
        'denominator_nonzero', 'radicand_nonnegative'}


@pytest.mark.parametrize('expression,expected', [
    ('1/sqrt((0*x)^2)', sp.S.EmptySet),
    ('1/sqrt((-3)^2)', sp.S.Reals),
    ('sqrt((x^2-1)^2)/0', sp.S.EmptySet),
])
def test_squared_radicand_zero_and_nonzero_constant_denominators(expression, expected):
    _, state = execute(candidate(expression))
    assert state['status'] == 'method_complete', state['diagnostics']
    assert driver.export_values(state)['feasible_set'] == expected
    assert state['verification']['status'] == 'verified'


@pytest.mark.parametrize('expression', [
    'sqrt(x^7+1)', 'sqrt((x^4-1)^2)', 'sqrt((x^2-2)^2)',
    'abs(x^2-2)', 'abs(x^7)', 'sqrt(((x-1)/(x-1))^2)',
    'sqrt(((x-1)^0)^2)', 'sqrt((sqrt(x))^2)', 'sqrt((a*x^2+1)^2)',
])
def test_square_extension_respects_degree_and_rational_root_limits_and_internal_restrictions(expression):
    original = candidate(expression)
    description = inspect_domain_target(original, TARGET)
    assert not description['structure_supported']
    context, state = execute(original)
    assert state['status'] == 'capability_gap'
    assert function_domain.verify_domain(original, TARGET, context, sp.S.Reals)['status'] == 'capability_gap'


def test_coefficient_budget_applies_after_polynomial_arithmetic():
    large = ['number', str(2**127)]
    with pytest.raises(NotationError, match='domain.coefficient_limit'):
        _fixed_poly(['+', large, large], max_degree=2)


def test_finite_rational_exclusions_share_admission_and_set_semantics():
    base = ['interval', True, False, ['number', '-2'], ['number', '3']]
    domain = ['set_difference', base, ['set', ['number', '-1'], ['/', ['number', '1'], ['number', '2']]]]
    _input_domain(domain)
    assert function_domain.input_set({'input_domain_ast': domain, 'variable': 'x'}) == (
        sp.Interval.Ropen(-2, 3) - sp.FiniteSet(-1, sp.Rational(1, 2)))
    removed_singleton = ['set_difference', ['set', ['number', '0']], ['set', ['number', '0']]]
    assert function_domain.input_set({'input_domain_ast': removed_singleton, 'variable': 'x'}) == sp.S.EmptySet
    limit = ['set_difference', ['real'], ['set', *[['number', str(i)] for i in range(MAX_EXCLUDED_POINTS)]]]
    _input_domain(limit)
    assert function_domain.input_set({'input_domain_ast': limit, 'variable': 'x'}) == sp.S.Reals - sp.FiniteSet(*range(MAX_EXCLUDED_POINTS))
    for invalid in [
        ['set_difference', ['real'], ['set', *limit[2][1:], ['number', '20']]],
        ['set_difference', domain, ['set', ['number', '0']]],
        ['set_difference', ['real'], ['set', ARGUMENT]],
        ['set_difference', ['real'], ['set', ['infinity']]],
    ]:
        with pytest.raises(NotationError):
            _input_domain(invalid)
        with pytest.raises(NotationError):
            function_domain.input_set({'input_domain_ast': invalid, 'variable': 'x'})


@pytest.mark.parametrize('domain,expected', [
    ('ℝ∖{-1,1/2}', sp.S.Reals - sp.FiniteSet(-1, sp.Rational(1, 2))),
    ('[-2,3)∖{-1,1/2}', sp.Interval.Ropen(-2, 3) - sp.FiniteSet(-1, sp.Rational(1, 2))),
    ('(0,2) setminus {1}', sp.Union(sp.Interval.open(0, 1), sp.Interval.open(1, 2))),
    ('[0,0]∖{0}', sp.S.EmptySet),
    ('[0,1]∖{2,2}', sp.Interval(0, 1)),
])
def test_compiled_explicit_exclusions_reach_m1_and_original_source_verification(domain, expected):
    original = candidate('sqrt((2*x^2+1)^2)', domain)
    context, state = execute(original)
    description = context['domain_goal']
    assert description['structure_supported']
    assert description['input_domain_ast'][0] == 'set_difference'
    assert description['input_domain_source_ref'] == '/root/goals/0/input_domain'
    assert state['status'] == 'method_complete', state['diagnostics']
    assert driver.export_values(state)['feasible_set'] == expected
    assert state['verification']['status'] == 'verified'
    assert function_domain.domain_endpoints(original, TARGET, expected)['status'] == 'passed'
