"""Original-source certificates for sqrt(Q(x)+d*m)/sqrt(u*x+v).

This module never calls a method or range capability. The denominator proves
the exact open halfline, and continuity/vertex position proves the numerator's
infimum there, including every linear and constant degeneration.
"""

import sympy as sp

from ...problem_understanding.notation_semantics import bounded_expand
from .math_values import math_value


def source_problem(description, *, with_bound=True):
    from .function_domain import expression, input_set
    from .verification import VerificationGap

    variable = sp.Symbol(description["variable"], real=True)
    parameter = sp.Symbol(description["parameter"], real=True)
    body = description["expression_ast"]
    original_radicand = expression(body[1][2], variable, {description["parameter_ref"]: parameter})
    radicand = bounded_expand(original_radicand)
    denominator = expression(body[2][2], variable)
    polynomial = sp.Poly(radicand, variable)
    a, b, constant = (polynomial.nth(i) for i in (2, 1, 0))
    offset = sp.Poly(constant, parameter)
    c, d = offset.nth(0), offset.nth(1)
    line = sp.Poly(denominator, variable)
    slope, intercept = line.nth(1), line.nth(0)
    if (polynomial.degree() > 2 or offset.degree() != 1 or line.degree() != 1
            or any(value.is_Rational is not True for value in (a, b, c, d, slope, intercept))
            or a.has(parameter) or b.has(parameter) or slope == 0 or d == 0):
        raise VerificationGap("domain.parameter_halfline_structure_unsupported")
    boundary = -intercept / slope
    direction = 1 if slope > 0 else -1
    denominator_domain = (sp.Interval.open(boundary, sp.oo) if direction > 0
                          else sp.Interval.open(-sp.oo, boundary))
    domain = input_set({**description, "input_domain_ast": description["prescribed_domain_ast"]})
    if domain != denominator_domain:
        raise VerificationGap("domain.parameter_denominator_domain_mismatch")
    problem = {
        "description": description, "variable": variable, "parameter": parameter,
        "radicand": radicand, "original_radicand": original_radicand,
        "coefficients": [a, b, constant], "strict": False,
        "radicand_path": [1, 2], "family": "halfline_root_ratio",
        "denominator": denominator, "denominator_slope": slope, "boundary": boundary,
        "domain": domain, "direction": direction, "base_coefficients": [a, b, c],
        "parameter_coefficient": d,
    }
    if with_bound:
        problem["lower_bound"] = _lower_bound(problem)
    return problem


def _lower_bound(problem):
    a, b, c = problem["base_coefficients"]
    boundary, direction = problem["boundary"], problem["direction"]
    endpoint = a * boundary**2 + b * boundary + c
    if a < 0 or a == 0 and b * direction < 0:
        return {"infimum": -sp.oo, "attained": False, "kind": "unbounded_below",
                "tail_direction": direction, "vertex": None}
    if a == 0:
        return {"infimum": c if b == 0 else endpoint, "attained": b == 0,
                "kind": "constant" if b == 0 else "linear_boundary_limit", "vertex": None}
    vertex = -b / (2 * a)
    inside = direction * (vertex - boundary) > 0
    return {
        "infimum": c - b**2 / (4*a) if inside else endpoint,
        "attained": bool(inside), "vertex": vertex,
        "kind": "interior_vertex" if inside else "vertex_at_boundary" if vertex == boundary else "vertex_outside_domain",
    }


def domain_equivalence(problem):
    """The denominator permits exactly D, so numerator validity on D is sufficient."""
    variable, denominator = problem["variable"], problem["denominator"]
    return {
        "kind": "original_denominator_exact_halfline", "passed": True,
        "source_refs": [problem["description"]["source_ref"]],
        "condition_ids": ["c1", "c2", "c3"],
        "denominator_condition_ids": ["c2", "c3"],
        "denominator_ast_path": [2], "radicand_ast_path": [2, 2],
        "basis_refs": ["square-root-expression#meaning", "rational-expression#meaning"],
        "prescribed_domain": problem["domain"], "denominator_domain": problem["domain"],
        "denominator_condition": sp.Gt(denominator, 0, evaluate=False),
        "inside_condition": sp.Ge(problem["original_radicand"], 0, evaluate=False),
        "outside_domain": sp.Complement(sp.S.Reals, problem["domain"]),
        "outside_condition": sp.Le(denominator, 0, evaluate=False),
        "outside_excluded": True, "boundary": problem["boundary"],
        "slope": problem["denominator_slope"], "variable": variable,
        "reason": "L>0 is exactly D; outside D, L<0 makes the square root undefined and L=0 makes the denominator zero.",
    }


def critical_expression(problem):
    bound = problem["lower_bound"]["infimum"]
    return None if bound is -sp.oo else bound + problem["parameter_coefficient"] * problem["parameter"]


def source_certificate(problem):
    return {key: math_value(value) if isinstance(value, sp.Basic) else value
            for key, value in domain_equivalence(problem).items()}


def at_parameter(problem, point):
    from .verification import _algebraic_sign

    lower = problem["lower_bound"]
    bound = lower["infimum"]
    value = bound if bound is -sp.oo else bound + problem["parameter_coefficient"] * point
    holds = value is not -sp.oo and _algebraic_sign(value) >= 0
    return holds, {
        "source_ref": problem["description"]["source_ref"], "ast_path": [1, 2],
        "kind": "original_numerator_nonnegative_on_exact_denominator_domain",
        "holds": holds, "polynomial": math_value(problem["radicand"].subs(problem["parameter"], point)),
        "certificate": {
            "degree": 2 if problem["base_coefficients"][0] else 1 if problem["base_coefficients"][1] else 0,
            "kind": lower["kind"], "strict": False, "infimum": math_value(value),
            "infimum_attained": lower["attained"],
            "vertex": math_value(lower["vertex"]) if lower["vertex"] is not None else None,
            "domain": math_value(problem["domain"]), "boundary": math_value(problem["boundary"]),
            "criterion": "P is continuous and bounded below on D with infimum >= 0; an open input endpoint does not force a strict parameter bound.",
        },
    }
