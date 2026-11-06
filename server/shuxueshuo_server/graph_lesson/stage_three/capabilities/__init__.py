"""Bounded exact algebra, independent of orchestration and problem identities."""

from itertools import pairwise

import sympy as sp

from ....problem_understanding.notation_semantics import bounded_expand


class CapabilityGap(ValueError):
    pass


class LocalCheckFailed(ValueError):
    def __init__(self, message, *, evidence=None):
        super().__init__(message)
        self.evidence = evidence


def result(outputs, operations=(), checks=None):
    checks = (
        [{"kind": "declared_domain", "passed": True}]
        if checks is None
        else list(checks)
    )
    if not checks:
        raise LocalCheckFailed(
            "capability.missing_local_evidence",
            evidence={
                "outputs": outputs,
                "operations": list(operations),
                "checks": [{"kind": "missing_local_evidence", "passed": False}],
            },
        )
    if any(c["passed"] is not True for c in checks):
        raise LocalCheckFailed(
            "capability.postcondition_failed",
            evidence={
                "outputs": outputs,
                "operations": list(operations),
                "checks": checks,
            },
        )
    return {"outputs": outputs, "operations": list(operations), "checks": checks}


def relation(lhs, operator, rhs=sp.S.Zero):
    return {">=": sp.Ge, ">": sp.Gt, "<=": sp.Le, "<": sp.Lt}[operator](
        lhs, rhs, evaluate=False
    )


def residual(value):
    return bounded_expand(
        value.lhs - value.rhs if value.rel_op in (">", ">=") else value.rhs - value.lhs
    )


def polynomial(expression, variable, maximum=2):
    try:
        poly = sp.Poly(expression, variable)
    except sp.PolynomialError as exc:
        raise CapabilityGap("nonpolynomial") from exc
    if poly.degree() > maximum:
        raise CapabilityGap("polynomial_degree")
    return poly


def normalize_to_zero(relation, variable):
    value = residual(relation)
    poly = polynomial(value, variable)
    operator = ">" if relation.rel_op in (">", "<") else ">="
    normalized = globals()["relation"](value, operator)
    operations = ["add_both_sides"]
    if poly.LC().is_negative:
        value = -value
        normalized = globals()["relation"](value, "<" if operator == ">" else "<=")
        operations.append("multiply_negative")
    return result(
        {"relation": normalized, "expression": value},
        operations,
        [
            {
                "kind": "direction_residual",
                "passed": bounded_expand(residual(normalized) - residual(relation))
                == 0,
            }
        ],
    )


def simplify_expression(expression):
    value = bounded_expand(expression)
    return result(
        {"expression": value},
        ["identity"],
        [{"kind": "identity", "passed": bounded_expand(value - expression) == 0}],
    )


def quadratic_sign_condition(relation, variable, domain, quantifier, case_domain, mode):
    from .cases import coefficient_zeros, exact_set_equal, parameter_symbols

    # The sign theorem applies to the direction residual, including when an
    # earlier normalization multiplied by a negative number. Strictness is part
    # of the relation and cannot drift in a separate boolean binding.
    if relation.rel_op not in (">", ">=", "<", "<="):
        raise CapabilityGap("ordered_relation_required")
    expression = residual(relation)
    poly = polynomial(expression, variable)
    if domain != sp.S.Reals or quantifier not in ("∀", "∃") or poly.degree() != 2:
        raise CapabilityGap("all_real_quantified_quadratic_required")
    a, b, c = poly.all_coeffs()
    symbols = parameter_symbols(expression, variable)
    zeros = coefficient_zeros(a, next(iter(symbols)) if symbols else None)
    if not exact_set_equal(sp.Intersection(case_domain, zeros), sp.S.EmptySet):
        raise CapabilityGap("nondegenerate_case_required")
    strict = relation.rel_op in (">", "<")
    delta = bounded_expand(b * b - 4 * a * c)
    combiner = "all" if quantifier == "∀" else "any"
    delta_operator = ("<" if strict else "<=") if quantifier == "∀" else (">" if strict else ">=")
    condition = globals()["relation"](delta, delta_operator)
    checks = [
        {"kind": "nonzero_leading_coefficient_on_case", "passed": True,
         "coefficient": a, "case_domain": case_domain, "zero_set": zeros},
        {"kind": "direction_and_strictness", "passed": True,
         "relation": relation, "residual": expression, "strict": strict},
        {"kind": "quadratic_square_identity", "passed": bounded_expand(
            4 * a * expression - ((2 * a * variable + b)**2 - delta)) == 0},
        {"kind": "quantified_quadratic_sign_rule", "passed": True,
         "quantifier": quantifier, "combiner": combiner, "delta_condition": condition,
         "positive_leading_is_sufficient": quantifier == "∃"},
    ]
    if mode == "opening":
        return result(
            {"opening": sp.Gt(a, 0, evaluate=False), "delta": delta,
             "coefficient": a, "basis_expression": expression,
             "quantifier": quantifier, "condition_combiner": combiner},
            ["quadratic_zeros", "all_real_sign"],
            checks,
        )
    if mode != "delta":
        raise CapabilityGap("unknown_quadratic_condition_mode")
    return result(
        {"condition": condition, "delta": delta, "coefficient": a,
         "basis_expression": expression, "quantifier": quantifier, "condition_combiner": combiner},
        ["discriminant_condition", "all_real_sign"],
        checks,
    )


def transform_param_inequality(relation, variable):
    value = residual(relation)
    poly = polynomial(value, variable, maximum=48)
    scale = abs(poly.LC()) if poly.LC().is_nonzero else sp.S.One
    if scale.free_symbols or scale.is_positive is not True:
        raise CapabilityGap("constant_transform_required")
    expression = bounded_expand(value / scale)
    transformed = globals()["relation"](
        expression, ">" if relation.rel_op in (">", "<") else ">="
    )
    return result(
        {"relation": transformed, "expression": expression},
        ["multiply_constant"],
        [
            {
                "kind": "positive_scaled_residual",
                "passed": bounded_expand(
                    residual(transformed) * scale - residual(relation)
                )
                == 0,
            }
        ],
    )


def _root_certificate(expression, variable, roots, all_zero):
    poly = polynomial(expression, variable)
    if expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_coefficients_required")
    if expression == 0:
        expected = 0
    elif poly.degree() < 2:
        expected = int(poly.degree())
    else:
        a, b, c = poly.all_coeffs()
        discriminant = bounded_expand(b * b - 4 * a * c)
        if discriminant.is_positive:
            expected = 2
        elif discriminant.is_zero:
            expected = 1
        elif discriminant.is_negative:
            expected = 0
        else:
            raise CapabilityGap("root_count_unknown")
    valid = (
        all_zero == (expression == 0)
        and len(roots) == expected
        and len(set(roots)) == expected
        and all(
            r.is_real is True and bounded_expand(expression.subs(variable, r)) == 0
            for r in roots
        )
        and all((right - left).is_positive is True for left, right in pairwise(roots))
    )
    if not valid:
        raise LocalCheckFailed("incomplete_or_invalid_real_roots")
    return {"kind": "complete_real_roots", "passed": True, "count": expected}


def solve_quadratic(expression, variable):
    poly = polynomial(expression, variable)
    if poly.degree() not in (0, 1, 2) and expression != 0:
        raise CapabilityGap("constant_linear_quadratic_required")
    if expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_coefficients_required")
    roots = sp.solveset(expression, variable, domain=sp.S.Reals)
    if roots == sp.S.Reals:
        values = []
    elif isinstance(roots, sp.FiniteSet) or roots == sp.S.EmptySet:
        values = sorted(roots, key=lambda x: x)
    else:
        raise CapabilityGap("real_roots_unknown")
    return result(
        {"roots": values, "all_zero": expression == 0},
        ["quadratic_roots"],
        [_root_certificate(expression, variable, values, expression == 0)],
    )


def quadratic_sign_pattern(expression, variable, roots, strict, all_zero=False):
    complete = _root_certificate(expression, variable, roots, all_zero)
    # Exhaustive exact partition: intervals contain no roots; roots checked separately.
    if all_zero:
        return result(
            {"solution": sp.S.EmptySet if strict else sp.S.Reals},
            ["quadratic_signs"],
            [complete],
        )
    boundaries = [-sp.oo, *roots, sp.oo]
    parts, checks = [], [complete]
    for left, right in pairwise(boundaries):
        sample = (
            right - 1
            if left == -sp.oo and right != sp.oo
            else left + 1
            if right == sp.oo and left != -sp.oo
            else sp.S.Zero
            if left == -sp.oo
            else (left + right) / 2
        )
        value = bounded_expand(expression.subs(variable, sample))
        if value.is_positive is None:
            raise CapabilityGap("sign_undecidable")
        checks.append(
            {"kind": "root_partition", "passed": True, "sample": sample, "value": value}
        )
        if value.is_positive:
            parts.append(sp.Interval.open(left, right))
    if not strict:
        parts.extend(sp.FiniteSet(r) for r in roots)
    return result({"solution": sp.Union(*parts)}, ["quadratic_signs"], checks)


def complete_square(expression, variable):
    poly = polynomial(expression, variable)
    if poly.degree() != 2 or expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_quadratic_required")
    a, b, c = poly.all_coeffs()
    vertex = -b / (2 * a)
    value = bounded_expand(c - b * b / (4 * a))
    square = a * (variable - vertex) ** 2 + value
    return result(
        {"square": square, "coefficient": a, "vertex": vertex, "value": value},
        ["identity", "square_nonnegative"],
        [
            {
                "kind": "square_identity",
                "passed": bounded_expand(square - expression) == 0,
            }
        ],
    )


def square_extremum(expression, variable, domain, square, coefficient, vertex, value):
    if domain != sp.S.Reals or coefficient.is_positive is None:
        raise CapabilityGap("whole_real_square_required")
    poly = polynomial(expression, variable)
    if (
        poly.degree() != 2
        or bounded_expand(square - expression) != 0
        or poly.LC() != coefficient
        or bounded_expand(sp.diff(expression, variable).subs(variable, vertex)) != 0
    ):
        raise LocalCheckFailed("invalid_square_range_certificate")
    minimum = coefficient.is_positive
    bounds = {
        "inf": value if minimum else -sp.oo,
        "sup": sp.oo if minimum else value,
        "inf_attained": minimum,
        "sup_attained": not minimum,
        "point": vertex,
        "set": sp.Interval(value, sp.oo) if minimum else sp.Interval(-sp.oo, value),
    }
    return result(
        {"range": bounds},
        ["square_nonnegative"],
        [
            {
                "kind": "vertex_substitution",
                "passed": bounded_expand(expression.subs(variable, vertex) - value) == 0
                and domain.contains(vertex) is sp.true,
            }
        ],
    )


from ..function_domain import (
    extract_domain_conditions,
    extract_domain_parameter_conditions,
    intersect_domain,
    prepare_domain_conditions,
    reduce_domain_equality_to_universal,
)
from .cases import (
    combine_condition_solutions,
    degenerate_case_check,
    merge_cases,
    solve_parameter_relation,
)
from .openings import quadratic_opening_solutions
from .parametric import (
    merge_interval_cases,
    parametric_interval_extremum,
    partition_interval_cases,
    solve_interval_conditions,
)
from .quantified import (
    apply_quantifier_policy,
    select_quantifier_policy,
    solve_conditions,
)
from .ranges import (
    endpoint_values_extremum,
    linear_range,
    quadratic_interval_range,
    reciprocal_range,
)
from .reciprocal import reciprocal_of_range
from .separation import inspect_separation as inspect_separation
from .separation import separate_parameter, separation_division
from .substitution import restore_substitution_range, substitution
from .variable_swap import (
    combine_variable_solutions,
    intersect_variable_case_solution,
    merge_variable_cases,
    normalize_parameter_conditions,
    parameter_linear_case_range,
    parameter_linear_range,
    reorder_by_variable,
    solve_affine_condition,
    solve_variable_conditions,
)

REGISTRY = {
    fn.__name__: fn
    for fn in (
        extract_domain_conditions,
        extract_domain_parameter_conditions,
        reduce_domain_equality_to_universal,
        prepare_domain_conditions,
        intersect_domain,
        normalize_to_zero,
        simplify_expression,
        quadratic_sign_condition,
        quadratic_opening_solutions,
        transform_param_inequality,
        solve_quadratic,
        quadratic_sign_pattern,
        separate_parameter,
        separation_division,
        substitution,
        restore_substitution_range,
        reciprocal_range,
        reciprocal_of_range,
        linear_range,
        quadratic_interval_range,
        endpoint_values_extremum,
        partition_interval_cases,
        parametric_interval_extremum,
        solve_interval_conditions,
        merge_interval_cases,
        solve_conditions,
        select_quantifier_policy,
        apply_quantifier_policy,
        complete_square,
        square_extremum,
        degenerate_case_check,
        combine_condition_solutions,
        merge_cases,
        solve_parameter_relation,
        reorder_by_variable,
        parameter_linear_range,
        normalize_parameter_conditions,
        solve_variable_conditions,
        solve_affine_condition,
        combine_variable_solutions,
        parameter_linear_case_range,
        intersect_variable_case_solution,
        merge_variable_cases,
    )
}


def _comparison_operation(name):
    def invoke(**inputs):
        from .. import equality_runtime
        return getattr(equality_runtime, name)(**inputs)
    return invoke


REGISTRY.update({name: _comparison_operation(name) for name in (
    'prepare_function_comparisons', 'prepare_function_pair', 'compare_function_pair',
    'collect_function_comparisons',
)})


def _abstract_domain_operation(name):
    def invoke(**inputs):
        from .. import abstract_function_domain
        return getattr(abstract_function_domain, name)(**inputs)
    return invoke


REGISTRY.update({name: _abstract_domain_operation(name) for name in (
    'solve_abstract_function_domain', 'extract_abstract_concrete_conditions',
)})


def _abstract_domain_parameter_operation(**inputs):
    from ..abstract_domain_parameter import solve_abstract_domain_parameter

    return solve_abstract_domain_parameter(**inputs)


REGISTRY['solve_abstract_domain_parameter'] = _abstract_domain_parameter_operation
PLANNED = frozenset(
    {
        "elimination",
    }
)


def execute(capability, inputs):
    if capability in PLANNED:
        raise CapabilityGap(capability)
    return REGISTRY[capability](**inputs)


def _function_formula_operation(name):
    def run(**inputs):
        from .. import formula_runtime
        return getattr(formula_runtime, name)(**inputs)
    return run


for _name in ('solve_function_formula', 'extract_formula_conditions', 'substitute_formula_input',
              'simplify_formula_expression', 'verify_formula_identity'):
    REGISTRY[_name] = _function_formula_operation(_name)


def _function_matching_operation(name):
    def run(**inputs):
        from .. import matching_runtime
        return getattr(matching_runtime, name)(**inputs)
    return run


for _name in ('solve_function_matching', 'complete_matching_identity', 'simplify_matching_expression'):
    REGISTRY[_name] = _function_matching_operation(_name)


def _function_evaluation_operation(name):
    def run(**inputs):
        from .. import evaluation_runtime
        return getattr(evaluation_runtime, name)(**inputs)
    return run


for _name in ('solve_function_evaluation', 'extract_evaluation_conditions',
              'resolve_evaluation_domain', 'check_evaluation_quadratic_conditions',
              'simplify_evaluation_expressions', 'verify_evaluation_identities'):
    REGISTRY[_name] = _function_evaluation_operation(_name)


def _function_range_operation(name):
    def run(**inputs):
        from .. import function_range
        return getattr(function_range, name)(**inputs)
    return run


for _name in ('prepare_function_range', 'polynomial_image', 'transform_function_range',
              'prepare_range_substitution', 'return_range_substitution',
              'prepare_fraction_range', 'return_fraction_range'):
    REGISTRY[_name] = _function_range_operation(_name)


def _range_equation_operation(name):
    def run(**inputs):
        from .. import range_equation
        return getattr(range_equation, name)(**inputs)
    return run


for _name in ('prepare_equation_range', 'solve_equation_range'):
    REGISTRY[_name] = _range_equation_operation(_name)


def _solve_fraction_intermediate(**inputs):
    from ..fraction_range import solve_fraction_intermediate
    return solve_fraction_intermediate(**inputs)


REGISTRY['solve_fraction_intermediate'] = _solve_fraction_intermediate


def _transfer_abstract_range(context):
    from ..abstract_function_range import transfer_abstract_range
    return transfer_abstract_range(context)


REGISTRY['transfer_abstract_range'] = _transfer_abstract_range


def _finite_range_operation(name):
    def run(**inputs):
        from .. import finite_range
        return getattr(finite_range, name)(**inputs)
    return run


for _name in ('prepare_finite_range', 'prepare_finite_input', 'collect_finite_range'):
    REGISTRY[_name] = _finite_range_operation(_name)


def _translate_range(context):
    from ..translation_range import translate_range
    return translate_range(context)


REGISTRY['translate_range'] = _translate_range


def _range_task_operation(name):
    def run(**inputs):
        from .. import range_tasks
        return getattr(range_tasks, name)(**inputs)
    return run


for _capability, _operation in (('prepare_range_options', 'prepare_options'),
                              ('prepare_range_case', 'prepare_case'),
                              ('compare_range_option', 'compare_option'),
                              ('collect_range_options', 'collect_options')):
    REGISTRY[_capability] = _range_task_operation(_operation)


def _function_coefficients_operation(name):
    def execute(**inputs):
        from .. import coefficients_runtime
        return getattr(coefficients_runtime, name)(**inputs)
    return execute


for _name in ('prepare_function_coefficients', 'expand_coefficient_relations', 'compare_polynomial_coefficients',
              'solve_function_coefficient_system', 'verify_function_coefficients',
              'coefficient_target_roots', 'coefficient_target_signs'):
    REGISTRY[_name] = _function_coefficients_operation(_name)


def _function_system_operation(name):
    def operation(**inputs):
        from .. import system_runtime
        return getattr(system_runtime, name)(**inputs)
    return operation


for _name in ('prepare_function_system', 'interchange_function_inputs', 'eliminate_function_values',
              'simplify_system_formula', 'verify_system_formula'):
    REGISTRY[_name] = _function_system_operation(_name)


def _function_assignment_operation(name):
    def operation(**inputs):
        from .. import assignment_runtime
        return getattr(assignment_runtime, name)(**inputs)
    return operation


for _name in ('prepare_function_assignment', 'specialize_function_relation', 'solve_assignment_equations',
              'simplify_assignment_formula', 'verify_assignment_formula'):
    REGISTRY[_name] = _function_assignment_operation(_name)


def _transform_function_graph(**inputs):
    from ..graph_transform_runtime import transform_function_graph
    return transform_function_graph(**inputs)


REGISTRY['transform_function_graph'] = _transform_function_graph


def _construct_absolute_graph(**inputs):
    from ..absolute_graph_runtime import construct
    return construct(**inputs)


def _solve_absolute_graph_inequality(**inputs):
    from ..absolute_graph_runtime import construct
    return construct(**inputs, inequality=True)


REGISTRY['construct_absolute_graph'] = _construct_absolute_graph
REGISTRY['solve_absolute_graph_inequality'] = _solve_absolute_graph_inequality


def _solve_piecewise_branches(context):
    from ...piecewise_equation import solve_branches
    return solve_branches(context)


def _filter_piecewise_branches(description, branch_roots):
    from ...piecewise_equation import filter_branches
    return filter_branches(description, branch_roots)


REGISTRY['solve_piecewise_branches'] = _solve_piecewise_branches
REGISTRY['filter_piecewise_branches'] = _filter_piecewise_branches


def _evaluate_piecewise_level(context):
    from ...piecewise_inequality import evaluate_level
    return evaluate_level(context)


REGISTRY['evaluate_piecewise_level'] = _evaluate_piecewise_level


def _solve_piecewise_inequality_roots(description, level):
    from ...piecewise_inequality import solve_roots
    return solve_roots(description, level)


REGISTRY['solve_piecewise_inequality_roots'] = _solve_piecewise_inequality_roots


def _solve_piecewise_signs(description, level, branch_roots):
    from ...piecewise_inequality import solve_signs
    return solve_signs(description, level, branch_roots)


REGISTRY['solve_piecewise_signs'] = _solve_piecewise_signs


def _filter_piecewise_inequality(description, level, branch_solutions):
    from ...piecewise_inequality import filter_branches
    return filter_branches(description, level, branch_solutions)


REGISTRY['filter_piecewise_inequality'] = _filter_piecewise_inequality


def _piecewise_range_capability(name):
    def run(**kwargs):
        from ... import piecewise_range
        return getattr(piecewise_range, name)(**kwargs)
    return run


for _name in ('prepare_piecewise_range', 'bind_piecewise_range', 'merge_piecewise_range'):
    REGISTRY[_name] = _piecewise_range_capability(_name)


def _piecewise_parameter_capability(name):
    def call(**kwargs):
        from ... import piecewise_range_parameter
        return getattr(piecewise_range_parameter, name)(**kwargs)
    return call


def _build_piecewise_model(context):
    from ...piecewise_modeling import build
    return build(context)


REGISTRY['build_piecewise_model'] = _build_piecewise_model
REGISTRY['prepare_piecewise_range_parameter'] = _piecewise_parameter_capability('prepare')
REGISTRY['solve_piecewise_range_parameter'] = _piecewise_parameter_capability('solve')
REGISTRY['reduce_piecewise_range_to_universal'] = _piecewise_parameter_capability('reduce_to_universal')
REGISTRY['accept_piecewise_range_subproblem'] = _piecewise_parameter_capability('accept_subproblem')


def _extremum_capability(name):
    def call(**inputs):
        from .. import extremum_runtime
        return getattr(extremum_runtime, name)(**inputs)
    return call


for _name, _function in {'analyze_extremum': 'analyze', 'confirm_extremum': 'confirm', 'prepare_extremum_children': 'prepare_children',
                         'bind_extremum_child': 'bind_child', 'confirm_extremum_children': 'confirm_children',
                         'prepare_extremum_parameter_children': 'prepare_parameter_children',
                         'bind_extremum_parameter_child': 'bind_parameter_child',
                         'extremum_reciprocal_piece': 'reciprocal_parameter_piece',
                         'verify_extremum_independent_piece': 'independent_parameter_piece',
                         'check_extremum_ranges': 'check_ranges',
                         'accept_extremum_parameter_children': 'accept_parameter_children'}.items():
    REGISTRY[_name] = _extremum_capability(_function)


def _monotonicity_capability(name):
    def call(**inputs):
        from .. import monotonicity_runtime
        return getattr(monotonicity_runtime, name)(**inputs)
    return call


for _name, _function in {'prepare_monotonicity_difference': 'prepare_difference', 'factor_monotonicity_difference': 'factor_difference',
                         'prepare_monotonicity': 'prepare', 'analyze_monotonicity': 'analyze',
                         'split_monotonicity': 'split', 'bind_monotonicity': 'bind',
                         'confirm_monotonicity': 'confirm', 'transfer_monotonicity': 'transfer', 'join_monotonicity': 'join', 'prove_monotonicity_difference': 'difference_proof'}.items():
    REGISTRY[_name] = _monotonicity_capability(_function)
