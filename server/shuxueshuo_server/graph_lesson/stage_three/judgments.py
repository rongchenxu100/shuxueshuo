"""Explicit deterministic decisions; no model fallback."""

import sympy as sp

from .capabilities import CapabilityGap, execute, polynomial, residual
from .capabilities.cases import partition_cases


def nondegenerate(expression, variable):
    p = polynomial(expression, variable)
    if p.degree() != 2 or p.LC().free_symbols or p.LC().is_nonzero is not True:
        raise CapabilityGap("degenerate_branches_unavailable")
    return {
        "selected": "nondegenerate",
        "evidence": {
            "coefficient": p.LC(),
            "nonzero": True,
            "reason": "constant_nonzero_no_cases",
        },
    }


def degenerate_branches(relation, variable, parameter, domain, quantifier):
    coefficient, zeros, cases = partition_cases(
        relation, variable, parameter, domain, quantifier
    )
    has_degenerate = zeros != sp.S.EmptySet
    return {
        "selected": "degenerate" if has_degenerate else "nondegenerate",
        "cases": cases,
        "coefficient": coefficient,
        "has_degenerate": has_degenerate,
        "evidence": {
            "coefficient": coefficient, "zero_set": zeros,
            "conditions": [case["condition"] for case in cases],
            "domains": [case["domain"] for case in cases],
            "reason": "zero_and_nonzero_coefficient_partition",
        },
    }


def parameter_solver(relation, variable):
    degree = polynomial(residual(relation), variable, maximum=48).degree()
    choice = "quadratic" if degree <= 2 else "polynomial"
    return {"selected": choice, "choice": choice, "evidence": {"degree": degree}}


def polynomial_relation(relation, variable):
    if relation.rhs != 0:
        raise CapabilityGap("normalization_required")
    expression = residual(relation)
    polynomial(expression, variable)
    return {
        "selected": "normalized",
        "expression": expression,
        "strict": relation.rel_op in (">", "<"),
    }


def range_skill(expression, variable, domain, reserved_symbols=()):
    if expression.free_symbols - {variable}:
        raise CapabilityGap("range_skill_unavailable")
    denominator = None
    affine = None
    if not expression.is_polynomial(variable):
        from .capabilities.reciprocal import inspect_reciprocal

        try:
            execute("reciprocal_range", {"expression": expression, "variable": variable, "domain": domain})
            choice = "reciprocal"
        except CapabilityGap:
            try:
                denominator = inspect_reciprocal(expression, variable)["denominator"]
                bounds = execute("quadratic_interval_range", {
                    "expression": denominator, "variable": variable, "domain": domain,
                })["outputs"]["range"]
                execute("reciprocal_of_range", {"range": bounds})
                choice = "inverse"
            except CapabilityGap:
                from .capabilities.substitution import (
                    inspect_affine_reciprocal, inspect_reciprocal_quadratic,
                )
                try:
                    affine = inspect_affine_reciprocal(expression, variable, domain,
                                                      reserved_symbols=reserved_symbols)
                    choice = "affine_reciprocal"
                except CapabilityGap:
                    affine = inspect_reciprocal_quadratic(expression, variable, domain,
                                                          reserved_symbols=reserved_symbols)
                    choice = "reciprocal_quadratic"
        degree = None
    else:
        poly = polynomial(expression, variable)
        degree = int(poly.degree()) if poly.degree() != -sp.oo else 0
        choice = "linear" if degree <= 1 else "square" if domain == sp.S.Reals else "interval"
        if choice == "interval":
            execute("quadratic_interval_range", {"expression": expression, "variable": variable, "domain": domain})
    return {
        "selected": choice,
        "choice": choice,
        "denominator": denominator,
        "affine": affine,
        "evidence": {"degree": degree, "domain": domain},
    }


def interval_case_plan(expression, variable, parameter, domain, policy):
    """Retain the endpoint shortcut; otherwise prove a complete parameter split."""
    try:
        current = interval_skill(expression, variable, parameter, domain, policy)
    except CapabilityGap:
        computed = execute("partition_interval_cases", {
            "expression": expression, "variable": variable, "parameter": parameter,
            "domain": domain, "policy": policy,
        })
        cases = computed["outputs"]["cases"]
        return {"selected": "classified", "cases": cases, "has_cases": True,
                "evidence": computed["checks"]}
    mode = "endpoint" if current["parametric"] else "numeric"
    return {"selected": "direct", "cases": [{
        "id": "direct", "kind": "nondegenerate", "condition": sp.true,
        "domain": sp.S.Reals, "value": None, "mode": mode,
    }], "has_cases": False, "evidence": current["evidence"]}


def interval_case_skill(expression, variable, parameter, case):
    mode = case.get("mode", "classified")
    if mode == "parametric":
        mode = "classified"
    numeric_expression = expression
    if case["kind"] in ("linear", "constant"):
        if case["value"] is not None:
            numeric_expression = expression.subs(parameter, case["value"])
        if numeric_expression.has(parameter):
            raise CapabilityGap("numeric_degenerate_interval_required")
        mode, choice = "linear", "linear"
    else:
        choice = "quadratic"
    return {"selected": choice, "choice": choice, "mode": mode,
            "expression": numeric_expression, "evidence": {
                "kind": case["kind"], "condition": case["condition"], "domain": case["domain"],
            }}


def interval_skill(expression, variable, parameter, domain, policy):
    poly = polynomial(expression, variable)
    if poly.degree() != 2:
        raise CapabilityGap("interval_skill_unavailable")
    parametric = expression.has(parameter)
    inputs = {"expression": expression, "variable": variable, "domain": domain}
    if parametric:
        execute("endpoint_values_extremum", {**inputs, "parameter": parameter, "policy": policy})
    else:
        execute("quadratic_interval_range", inputs)
    return {"selected": "quadratic", "choice": "quadratic", "parametric": parametric,
            "evidence": {"degree": 2, "domain": domain, "parameter_cases": False,
                         "reason": "endpoint_envelope" if parametric else "constant_coefficients"}}


def interval_requirement(domain):
    whole_real = domain == sp.S.Reals
    return {
        "selected": "whole_real" if whole_real else "restricted",
        "requires_interval": not whole_real,
        "evidence": {
            "domain": domain,
            "reason": "whole_real_square_range" if whole_real else "restricted_domain",
        },
    }


def variable_roles(variable, parameter, domain, quantifier):
    if not isinstance(variable, sp.Symbol) or not isinstance(parameter, sp.Symbol) or variable == parameter:
        raise CapabilityGap("distinct_variable_roles_required")
    if quantifier not in ("∀", "∃") or domain.free_symbols:
        raise CapabilityGap("fixed_quantified_domain_required")
    return {"selected": "identified", "evidence": {
        "quantified_variable": variable, "sought_variable": parameter,
        "domain": domain, "quantifier": quantifier,
    }}


def affine_slope_decision(certificate):
    sign = certificate.get("sign", "zero" if certificate.get("kind") == "identically_zero_affine_slope" else None)
    if certificate.get("passed") is not True or sign not in ("positive", "negative", "zero", "unknown"):
        raise CapabilityGap("missing_affine_slope_certificate")
    return {"selected": sign, "evidence": certificate}


def endpoint_condition_plan(conditions, variable):
    if len(conditions) not in (1, 2):
        raise CapabilityGap("one_or_two_endpoint_conditions_required")
    kinds = ["quadratic" if polynomial(residual(condition), variable).degree() == 2 else "affine"
             for condition in conditions]
    return {"selected": "single" if len(conditions) == 1 else "both",
            "first": conditions[0], "first_kind": kinds[0],
            "second": conditions[1] if len(conditions) == 2 else None,
            "second_kind": kinds[1] if len(conditions) == 2 else "absent", "absent": None,
            "evidence": {"conditions": conditions, "degrees": kinds}}


from .capabilities.variable_swap import variable_case_plan

REGISTRY = {
    fn.__name__: fn
    for fn in (nondegenerate, degenerate_branches, parameter_solver,
               polynomial_relation, range_skill, interval_requirement, interval_skill,
               interval_case_plan, interval_case_skill, variable_roles,
               affine_slope_decision, endpoint_condition_plan, variable_case_plan)
}


def piecewise_range_parameter_route(description, fixed_range):
    from ..piecewise_range_parameter import choose_route
    return choose_route(description, fixed_range)


REGISTRY['piecewise_range_parameter_route'] = piecewise_range_parameter_route
