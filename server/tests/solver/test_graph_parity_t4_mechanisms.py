"""FP-T4 R4: §8.1 mechanism rows not already pinned by the R0–R3 suites."""
import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson import parity_order_math as order
from shuxueshuo_server.graph_lesson.parity_inequality_math import solve, verify
from shuxueshuo_server.graph_lesson.stage_three import parity_inequality_runtime as runtime
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import encode_value
from tests.solver.test_graph_parity_even_order import a20
from tests.solver.test_graph_parity_order import TARGET, described
from tests.solver.test_graph_parity_sign import a19
from tests.solver.test_graph_parity_sign import given as sign_given

A = sp.Rational(1, 3)
o = sp.Interval.open


def whole(relation, strict=True):
    mono = {'function': 'f', 'domain': 'ℝ', 'function_domain': 'ℝ', 'direction': 'increasing', 'strict': strict,
            'basis': {'kind': 'stated', 'statement': ''}}
    return {'original_text': '', 'root': {'facts': ['Dom(f)=ℝ', 'parity(f,odd)', relation], 'goals': [
        {'kind': 'find_range', 'symbol': 'x', 'function_monotonicity': mono}]}}


@pytest.mark.parametrize('op,expected', [('<', o(-sp.oo, A)), ('<=', sp.Interval(-sp.oo, A)),
                                         ('>', o(A, sp.oo)), ('>=', sp.Interval(A, sp.oo))])
def test_four_relations_keep_strictness_apart_from_direction(op, expected):
    desc = described(whole(f'f(x-1)+f(2*x){op}0'))
    model = solve(desc)
    assert model['solution'] == expected and verify(desc, model)


def test_non_strict_direction_is_rejected_before_any_route():
    with pytest.raises(ValueError, match='context.invalid_candidate'):
        build_context(whole('f(x-1)+f(2*x)<0', strict=False), TARGET)


@pytest.mark.parametrize('op,expected', [('<', sp.S.EmptySet), ('<=', sp.Interval(-sp.oo, sp.oo))])
def test_equal_original_inputs(op, expected):
    desc = described(whole(f'f(x)+f(-x){op}0'))
    model = solve(desc)
    assert model['solution'] == expected and verify(desc, model)


@pytest.mark.parametrize('facts,expected', [
    (['Dom(f)=ℝ', 'parity(f,odd)', 'f(1)=0', 'f(x)/(x-1)^2>=0'], sp.Interval(-1, 0) | o(1, sp.oo)),
    (['parity(f,odd)', 'f(2)=0', 'f(x^2-2)<0'],
     o(-2, -sp.sqrt(2)) | o(sp.sqrt(2), 2)),
])
def test_repeated_denominator_and_quadratic_input(facts, expected):
    desc = described(sign_given(facts))
    assert desc['structure_supported'], desc['reason']
    model = solve(desc)
    assert model['solution'] == expected and verify(desc, model)


def test_cubic_input_is_a_budget_gap():
    desc = described(sign_given(['parity(f,odd)', 'f(2)=0', 'f(x^3)<0']))
    assert not desc['structure_supported'] and desc['reason'] == 'parity_ineq.degree_budget'


@pytest.mark.parametrize('values,reason', [(sp.FiniteSet(1, 2), 'parameter_candidates_unsupported'),
                                           (sp.Interval(0, 1), 'parameter_family_unsupported')])
def test_several_parameter_candidates_are_a_gap(values, reason):
    desc = described(a20())
    with pytest.raises(ValueError, match=reason):
        order._solve_borrowed(desc, {'parameter_set': values, 'instantiated_domain': sp.Interval(-2, 2)})


def test_frozen_result_is_rechecked_against_the_original_statement():
    value = a19()
    context = build_context(value, TARGET)
    model = solve(context['parity_inequality_goal'])
    encoded = encode_value(model)
    assert runtime.verify_frozen(value, TARGET, context, encoded)['status'] == 'verified'
    changed = a19(relation='f(x-1)/x>0')
    assert runtime.verify_frozen(changed, TARGET, context, encoded)['status'] == 'math_failed'
    bad = encode_value({**model, 'solution': o(-1, 0) | sp.Interval(1, 3)})
    assert runtime.verify_frozen(value, TARGET, context, bad)['status'] == 'math_failed'
