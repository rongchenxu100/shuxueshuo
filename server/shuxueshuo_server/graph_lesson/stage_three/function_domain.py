"""Original-syntax domain conditions and an independent exact domain verifier.

Extraction does not solve. Verification does not consume extracted conditions:
it evaluates the original tree on a complete sign-invariant partition.
"""

from copy import deepcopy
from itertools import pairwise

import sympy as sp
from sympy.polys.polyerrors import BasePolynomialError

from ...problem_understanding.notation_parser import NotationError
from ...problem_understanding.notation_semantics import bounded_expand
from ..domain_expression import expression
from ..stage_one.function_domain import (
    ARGUMENT,
    MAX_FIXED_POLYNOMIAL_DEGREE,
    _fixed_poly,
    _input_domain,
    _inspect_expression,
    _integer_exponent,
    _square_radicand_base,
    inspect_domain_target,
)
from .math_values import math_value


def _is_zero(value):
    """Exact algebraic zero; unsimplified radicals at roots must not slip through."""
    expanded = bounded_expand(value)
    return expanded == 0 or expanded.is_zero is True


def _is_negative(value):
    expanded = bounded_expand(value)
    return expanded.is_negative is True


def _poly_roots(ast, max_degree=MAX_FIXED_POLYNOMIAL_DEGREE):
    """Exact real roots of a fixed rational univariate polynomial AST."""
    return _poly_roots_proof(ast, max_degree)[0]


def _poly_roots_proof(ast, max_degree):
    coeffs = _fixed_poly(ast, max_degree=max_degree)
    if len(coeffs) <= 1:
        return [], {"method": "constant_polynomial", "passed": True,
                    "identically_zero": coeffs[0] == 0, "critical_points_required": False}
    variable = sp.Dummy("x")
    expr = sum(
        (sp.Rational(c.numerator, c.denominator) * variable**i for i, c in enumerate(coeffs)),
        sp.Integer(0),
    )
    poly = sp.Poly(expr, variable, domain=sp.QQ)
    roots = list(dict.fromkeys(sp.polys.polytools.real_roots(poly)))
    if any(root.is_Rational is not True for root in roots):
        raise ValueError("domain.rational_critical_points_required")
    if poly.count_roots(-sp.oo, sp.oo) != len(roots):
        raise ValueError("domain.parameter_root_count")
    if any(poly.eval(root) != 0 for root in roots):
        raise ValueError("domain.original_root_substitution_failed")
    return roots, {"method": "exact_real_roots_and_sturm_count", "passed": True,
                   "distinct_real_roots": len(roots), "all_rational": True}


def input_set(description):
    ast = description["input_domain_ast"]
    _input_domain(ast)
    if ast[0] == "set_difference":
        base = input_set({**description, "input_domain_ast": ast[1]})
        variable = sp.Symbol(description["variable"], real=True)
        return base - sp.FiniteSet(*(expression(point, variable) for point in ast[2][1:]))
    if ast == ["real"]:
        return sp.S.Reals
    variable = sp.Symbol(description["variable"], real=True)
    if ast[0] == "set" and len(ast) == 2:
        return sp.FiniteSet(expression(ast[1], variable))
    return sp.Interval(
        expression(ast[3], variable),
        expression(ast[4], variable),
        left_open=not ast[1],
        right_open=not ast[2],
    )


def admitted(context):
    value = context.get("domain_goal", {})
    if (
        context.get("goal", {}).get("kind") != "find_domain"
        or value.get("structure_supported") is not True
    ):
        return False
    entries = context.get("entries", [])
    if len(entries) != 1 or entries[0]["ast"] != [
        "function_definition",
        context["goal_ast"]["target"],
        value["expression_ast"],
    ]:
        return False
    if entries[0]["source_ref"] != value["source_ref"]:
        return False
    if value["input_domain_ast"] != context["goal_ast"].get("input_domain", ["real"]):
        return False
    try:
        _inspect_expression(value["expression_ast"])
        _input_domain(value["input_domain_ast"])
    except ValueError:
        return False
    return True


def admitted_parameter(context):
    """Recheck the original M6 source family and its prescribed input domain."""
    value = context.get("domain_goal", {})
    goal = context.get("goal", {})
    goal_ast = context.get("goal_ast", {})
    if goal.get("kind") != "match_domain" or value.get("structure_supported") is not True:
        return False
    if value.get("task") != "match_domain":
        return False
    if goal_ast.get("domain", ["real"]) != value.get("prescribed_domain_ast"):
        return False
    parameter = goal_ast.get("parameter")
    if not parameter or parameter[0] != "ref" or value.get("parameter_ref") != parameter[1]:
        return False
    entries = context.get("entries", [])
    if len(entries) != 1 or entries[0]["ast"] != [
        "function_definition",
        goal_ast["target"],
        value["expression_ast"],
    ]:
        return False
    if entries[0]["source_ref"] != value["source_ref"]:
        return False
    try:
        from ..stage_one.function_domain_parameter import _inspect_parameter_structure

        counts = _inspect_parameter_structure(value["expression_ast"], parameter[1], value["prescribed_domain_ast"])
        if any(value.get(key) != expected for key, expected in counts.items()):
            return False
        if value.get("parameter_family") != counts.get("parameter_family"):
            return False
    except (NotationError, ValueError):
        return False
    return True


def extract_domain_conditions(context):
    from .capabilities import CapabilityGap, result

    if not admitted(context):
        raise CapabilityGap("domain.original_structure_unsupported")
    description = deepcopy(context["domain_goal"])
    variable = sp.Symbol(description["variable"], real=True)
    rows = []

    def add(ast, path, kind, basis):
        value = expression(ast, variable)
        condition = (
            sp.Ge(value, 0, evaluate=False)
            if kind == "radicand_nonnegative"
            else sp.Ne(value, 0, evaluate=False)
        )
        rows.append(
            {
                "condition_id": f"c{len(rows) + 1}",
                "source_ref": description["source_ref"],
                "ast_path": list(path),
                "expression_ast": deepcopy(ast),
                "kind": kind,
                "basis_refs": [basis],
                "condition": condition,
            }
        )

    def add_denominator(ast, path):
        # Product and zero-power factors keep one ≠0 condition per solvable piece;
        # a^0 itself is never 0 once the base is nonzero.
        if ast[0] == "neg":
            # Negation preserves zeroes; retain the child's original source path.
            add_denominator(ast[1], (*path, 1))
            return
        if ast[0] == "*":
            add_denominator(ast[1], (*path, 1))
            add_denominator(ast[2], (*path, 2))
            return
        if ast[0] == "^" and _integer_exponent(ast[2]) == 0:
            return
        add(ast, path, "denominator_nonzero", "rational-expression#meaning")

    def visit(ast, path=()):
        if ast[0] == "^" and _integer_exponent(ast[2]) == 0:
            add(ast[1], (*path, 1), "zero_power_base_nonzero", "integer-power#zero-exponent")
        if ast[:2] == ["call", "sqrt"]:
            add(
                ast[2],
                (*path, 2),
                "radicand_nonnegative",
                "square-root-expression#meaning",
            )
        if ast[0] == "/":
            # Traverse numerator first, matching the original reading order.
            visit(ast[1], (*path, 1))
            add_denominator(ast[2], (*path, 2))
            visit(ast[2], (*path, 2))
            return
        for index, child in enumerate(ast[1:], 1):
            if isinstance(child, list):
                visit(child, (*path, index))

    visit(description["expression_ast"])
    return result(
        {
            "constraints": rows,
            "conditions": [row["condition"] for row in rows],
            "description": description,
            "variable": variable,
            "input_domain": input_set(description),
        },
        sorted(
            {
                {
                    "radicand_nonnegative": "domain_radicand_conditions",
                    "denominator_nonzero": "domain_denominator_conditions",
                    "zero_power_base_nonzero": "domain_zero_power_conditions",
                }[row["kind"]]
                for row in rows
            }
        )
        or ["domain_unrestricted_expression"],
        [
            {
                "kind": "original_syntax_conditions",
                "passed": True,
                "source_ref": description["source_ref"],
                "expression_ast": description["expression_ast"],
                "condition_count": len(rows),
            }
        ],
    )


def extract_domain_parameter_conditions(context):
    """S3 for match_domain: same location rules, with free parameter symbols kept."""
    from .capabilities import CapabilityGap, result

    if not admitted_parameter(context):
        raise CapabilityGap("domain.parameter_structure_unsupported")
    description = deepcopy(context["domain_goal"])
    variable = sp.Symbol(description["variable"], real=True)
    parameter = sp.Symbol(description["parameter"], real=True)
    symbols = {description["parameter_ref"]: parameter}
    rows = []

    def add(ast, path, kind, basis):
        value = expression(ast, variable, symbols)
        condition = (
            sp.Ge(value, 0, evaluate=False)
            if kind == "radicand_nonnegative"
            else sp.Ne(value, 0, evaluate=False)
        )
        rows.append(
            {
                "condition_id": f"c{len(rows) + 1}",
                "source_ref": description["source_ref"],
                "ast_path": list(path),
                "expression_ast": deepcopy(ast),
                "kind": kind,
                "basis_refs": [basis],
                "condition": condition,
            }
        )

    body = description["expression_ast"]
    denominator = body[0] == "/"
    radical, path = (body[2], (2,)) if denominator else (body, ())
    if description.get("parameter_family") == "halfline_root_ratio":
        add(body[1][2], (1, 2), "radicand_nonnegative", "square-root-expression#meaning")
    add(radical[2], (*path, 2), "radicand_nonnegative", "square-root-expression#meaning")
    if denominator:
        # Preserve the denominator itself and its source even when N is zero
        # or shares polynomial factors with P. No simplified quotient is read.
        add(radical, path, "denominator_nonzero", "rational-expression#meaning")
    return result(
        {
            "constraints": rows,
            "conditions": [row["condition"] for row in rows],
            "description": description,
            "variable": variable,
            "parameter": parameter,
            "goal": context["goal"],
            "context": context,
        },
        ["domain_radicand_conditions", *(["domain_denominator_conditions"] if denominator else [])],
        [
            {
                "kind": "original_syntax_conditions",
                "passed": True,
                "source_ref": description["source_ref"],
                "expression_ast": description["expression_ast"],
                "condition_count": len(rows),
                "task": "match_domain",
            }
        ],
    )


def reduce_domain_equality_to_universal(constraints, description, variable, parameter, goal, context):
    """Combine original root/denominator conditions before adding ∀x∈R."""
    from .capabilities import CapabilityGap, LocalCheckFailed, result

    if not admitted_parameter(context):
        raise CapabilityGap("domain.parameter_structure_unsupported")
    original = extract_domain_parameter_conditions(context)["outputs"]
    if any(original[key] != value for key, value in (
            ("constraints", constraints), ("description", description), ("variable", variable),
            ("parameter", parameter), ("goal", goal))):
        raise LocalCheckFailed("domain.parameter_source_mismatch")
    halfline = description.get("parameter_family") == "halfline_root_ratio"
    strict = description["expression_ast"][0] == "/" and not halfline
    domain = input_set({**description, "input_domain_ast": description["prescribed_domain_ast"]})
    equivalence = None
    if halfline:
        from .domain_halfline import domain_equivalence, source_problem

        equivalence = domain_equivalence(source_problem(description, with_bound=False))
    radicand = constraints[0]["condition"].lhs
    relation = (sp.Gt if strict else sp.Ge)(radicand, 0, evaluate=False)
    expression_value = sp.together(relation.lhs - relation.rhs)
    return result(
        {
            "relation": relation,
            "expression": expression_value,
            "x": variable,
            "parameter": parameter,
            "domain": domain,
            "quantifier": "∀",
            "strict": strict,
            "goal": goal,
            "constraint_context": context,
            "universal_statement": relation,
            "borrowed_method": "method-separation" if halfline else "method-discriminant",
            "denominator_domain": domain if halfline else None,
            "domain_equivalence": equivalence,
        },
        ["domain_equality_to_universal"],
        [
            {
                "kind": "domain_equality_to_universal",
                "passed": True,
                "prescribed_domain": domain if halfline else "ℝ",
                "quantifier": "∀",
                "relation": relation,
                "strict": strict,
                "condition_ids": [row["condition_id"] for row in constraints],
            },
            *([equivalence] if equivalence else []),
        ],
    )


def prepare_domain_conditions(constraints, variable):
    from .capabilities import CapabilityGap, result

    conditions, checks, operations = [], [], []
    for row in constraints:
        ast = row["expression_ast"]
        condition = row["condition"]
        square = None
        if row["kind"] == "denominator_nonzero" and ast[:2] == ["call", "sqrt"]:
            # sqrt(t) != 0 iff t != 0 on the separately retained t >= 0 domain.
            radial = expression(ast[2], variable)
            if not any(
                r["kind"] == "radicand_nonnegative" and r["expression_ast"] == ast[2]
                for r in constraints
            ):
                raise CapabilityGap("domain.sqrt_guard_missing")
            condition = sp.Ne(radial, 0, evaluate=False)
            ast = ast[2]
            operations.append("domain_condition_normalization")
        base = _square_radicand_base(ast)
        if base is not None:
            # The original square remains in extraction evidence. Only this
            # explicit, admitted real polynomial square is reduced here.
            square = {"kind": "original_polynomial_square", "passed": True,
                      "expression_ast": deepcopy(ast), "base_ast": deepcopy(base),
                      "basis_refs": ["square-nonnegative#nonnegative"]}
            if row["kind"] == "radicand_nonnegative":
                condition = sp.true
            else:
                condition = sp.Ne(expression(base, variable), 0, evaluate=False)
            ast = base
            operations.extend(["domain_condition_normalization", "square_nonnegative"])
        # The source converter deliberately keeps powers unevaluated. Rebuild
        # admitted condition polynomials exactly before the shared solver so
        # constants such as 0**2 and (-3)**2 are rational coefficients too.
        coefficients = _fixed_poly(ast, max_degree=MAX_FIXED_POLYNOMIAL_DEGREE)
        canonical = sum((sp.Rational(c.numerator, c.denominator) * variable**i
                         for i, c in enumerate(coefficients)), sp.S.Zero)
        if condition is not sp.true and condition.lhs != canonical:
            condition = condition.func(canonical, 0, evaluate=False)
            operations.append("domain_condition_normalization")
        conditions.append(condition)
        checks.append(
            {
                "kind": "domain_condition_normalization",
                "passed": True,
                "condition_id": row["condition_id"],
                "original": row["condition"],
                "normalized": condition,
                **({"square_structure": square} if square else {}),
            }
        )
    return result(
        {"conditions": conditions or [sp.true]},
        sorted(set(operations)),
        checks or [{"kind": "unrestricted_expression", "passed": True}],
    )


def intersect_domain(solution, input_domain):
    from .capabilities import result

    answer = solution.intersect(input_domain)
    return result(
        {"domain": answer},
        ["domain_intersection"],
        [
            {
                "kind": "input_domain_intersection",
                "passed": answer == solution.intersect(input_domain),
                "expression_domain": solution,
                "input_domain": input_domain,
                "domain": answer,
            }
        ],
    )


def process_context(context, candidate_set):
    from .capabilities import CapabilityGap

    if not admitted(context):
        raise CapabilityGap("domain.original_structure_unsupported")
    domain = input_set(context["domain_goal"])
    return candidate_set.intersect(domain), [
        {"source_ref": entry["source_ref"], "status": "original_function_domain"}
        for entry in context["entries"]
    ] + (
        [
            {
                "source_ref": context["domain_goal"]["input_domain_source_ref"],
                "status": "intersected",
                "constraint_set": math_value(domain),
                "result": math_value(candidate_set.intersect(domain)),
            }
        ]
        if context["domain_goal"]["input_domain_source_ref"]
        else []
    )


def process_parameter_context(context, candidate_set):
    from .capabilities import CapabilityGap

    if not admitted_parameter(context):
        raise CapabilityGap("domain.parameter_structure_unsupported")
    return candidate_set, [
        {"source_ref": entry["source_ref"], "status": "original_function_domain_parameter"}
        for entry in context["entries"]
    ]


def _radicand_nonnegative_certificate(value, variable, *, strict=False):
    """Decide the original real polynomial, including every degree degeneration."""
    from .verification import VerificationGap, _algebraic_sign

    poly = sp.Poly(bounded_expand(value), variable, domain=sp.EX)
    if poly.degree() > 2:
        raise VerificationGap("domain.parameter_degree_unsupported")
    a, b, c = (poly.nth(i) for i in (2, 1, 0))
    signs = [_algebraic_sign(coefficient) for coefficient in (a, b, c)]
    discriminant = bounded_expand(b**2 - 4 * a * c)
    discriminant_sign = _algebraic_sign(discriminant)
    holds = (
        signs[0] > 0 and (discriminant_sign < 0 if strict else discriminant_sign <= 0)
        or signs[0] == signs[1] == 0 and (signs[2] > 0 if strict else signs[2] >= 0)
    )
    return holds, {
        "degree": 2 if signs[0] else 1 if signs[1] else 0,
        "coefficients": {name: math_value(coefficient) for name, coefficient in zip("ABC", (a, b, c), strict=True)},
        "coefficient_signs": dict(zip("ABC", signs, strict=True)),
        "discriminant": math_value(discriminant),
        "discriminant_sign": discriminant_sign,
        "strict": strict,
        "criterion": ("A>0 and discriminant<0, or A=B=0 and C>0" if strict else
                      "A>0 and discriminant<=0, or A=B=0 and C>=0"),
    }


def _radicand_always_nonnegative(poly, variable):
    return _radicand_nonnegative_certificate(poly, variable)[0]


def _domain_parameter_problem(candidate, target_ref):
    """Read coefficients from source notation, never from a method's bindings."""
    from ..stage_one.function_domain_parameter import inspect_match_domain_target
    from .verification import VerificationGap, _poly

    description = inspect_match_domain_target(candidate, target_ref)
    if description["structure_supported"] is not True:
        raise VerificationGap(description["reason"] or "domain.parameter_structure_unsupported")
    if description.get("parameter_family") == "halfline_root_ratio":
        from .domain_halfline import source_problem

        return source_problem(description)
    variable = sp.Symbol(description["variable"], real=True)
    parameter = sp.Symbol(description["parameter"], real=True)
    body = description["expression_ast"]
    strict = body[0] == "/"
    radical = body[2] if strict else body
    if radical[:2] != ["call", "sqrt"]:
        raise VerificationGap("domain.parameter_structure_unsupported")
    radicand = bounded_expand(expression(radical[2], variable, {description["parameter_ref"]: parameter}))
    poly = sp.Poly(radicand, variable)
    if poly.degree() != 2:
        raise VerificationGap("domain.parameter_degree_unsupported")
    coefficients = [poly.nth(i) for i in (2, 1, 0)]
    if any(_poly(value, parameter).degree() > 1 for value in coefficients):
        raise VerificationGap("domain.parameter_coefficients_unsupported")
    return {"description": description, "variable": variable, "parameter": parameter,
            "radicand": radicand, "coefficients": coefficients, "strict": strict,
            "radicand_path": [2, 2] if strict else [2]}


def _domain_parameter_critical(problem):
    from .verification import _critical_sources

    a, b, c = problem["coefficients"]
    sources = [(coefficient, problem["description"]["source_ref"], name)
               for coefficient, name in zip((a, b, c), ("coefficient_A", "coefficient_B", "coefficient_C"), strict=True)]
    sources.append((bounded_expand(b**2 - 4*a*c), problem["description"]["source_ref"], "discriminant"))
    if problem.get("family") == "halfline_root_ratio":
        from .domain_halfline import critical_expression

        boundary_condition = critical_expression(problem)
        if boundary_condition is not None:
            sources.append((boundary_condition, problem["description"]["source_ref"], "halfline_infimum"))
    points, records = _critical_sources(sources, problem["parameter"])
    for record in records:
        record["ast_path"] = problem["radicand_path"]
    return points, records


def _domain_parameter_at(problem, point):
    if problem.get("family") == "halfline_root_ratio":
        from .domain_halfline import at_parameter

        return at_parameter(problem, point)
    value = bounded_expand(problem["radicand"].subs(problem["parameter"], point))
    holds, certificate = _radicand_nonnegative_certificate(value, problem["variable"], strict=problem["strict"])
    return holds, {"source_ref": problem["description"]["source_ref"], "ast_path": problem["radicand_path"],
                   "kind": ("original_denominator_radicand_universally_positive" if problem["strict"] else
                            "original_radicand_universally_nonnegative"), "holds": holds,
                   "polynomial": math_value(value), "certificate": certificate}


def domain_parameter_endpoints(candidate, target_ref, feasible_set):
    """Boundary membership of the parameter answer against Dom(f)=R."""
    from functools import cmp_to_key

    from .verification import _compare, _contains_exact, _set_boundaries, _supported_set

    _supported_set(feasible_set)
    problem = _domain_parameter_problem(candidate, target_ref)
    critical, _ = _domain_parameter_critical(problem)
    points = []
    for point in sorted([*critical, *_set_boundaries(feasible_set)], key=cmp_to_key(_compare)):
        if not points or _compare(point, points[-1]):
            points.append(point)
    rows = []
    for point in points:
        included = _contains_exact(feasible_set, point)
        holds, evidence = _domain_parameter_at(problem, point)
        rows.append({"point": math_value(point), "included": included, "holds": holds,
                     "passed": included == holds, "evidence": evidence})
    return {
        "status": "passed" if all(row["passed"] for row in rows) else "failed",
        "points": rows,
    }


def verify_domain_parameter(candidate, target_ref, constraint_context, feasible_set):
    """Prove the entire parameter set on original-coefficient invariant cells."""
    from .verification import (
        ContextMismatch,
        VerificationGap,
        _contains_exact,
        _rational_between,
        _set_mismatch,
        _supported_set,
        check_context,
        collect_original,
    )

    result = {"status": "capability_gap", "proof": {}, "diagnostics": []}
    try:
        check_context(collect_original(candidate, target_ref), constraint_context)
        problem = _domain_parameter_problem(candidate, target_ref)
        description = problem["description"]
        if constraint_context.get("domain_goal") != description:
            raise ContextMismatch("constraint_context_mismatch:domain_goal")
        _supported_set(feasible_set)
        points, critical = _domain_parameter_critical(problem)
        cells, accepted = [], []
        for index, (left, right) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
            interval = sp.Interval.open(left, right)
            sample = _rational_between(left, right)
            holds, evidence = _domain_parameter_at(problem, sample)
            cells.append({"kind": "open_interval", "domain": math_value(interval),
                          "sample": math_value(sample), "holds": holds, "evidence": evidence})
            if holds:
                accepted.append(interval)
            if index < len(points):
                point = points[index]
                holds, evidence = _domain_parameter_at(problem, point)
                cells.append({"kind": "critical_point", "domain": math_value(sp.FiniteSet(point)),
                              "sample": math_value(point), "holds": holds, "evidence": evidence})
                if holds:
                    accepted.append(sp.FiniteSet(point))
        reconstructed = sp.Union(*accepted)
        result["proof"] = {
            "category": "original-domain-parameter-complete-coefficient-partition/v1",
            "source_refs": [description["source_ref"], target_ref],
            "expression_ast": deepcopy(description["expression_ast"]),
            "prescribed_domain": "ℝ",
            "strict": problem["strict"],
            "critical_polynomials": critical,
            "critical_points": [math_value(point) for point in points],
            "invariance": {
                "proved": True,
                "reason": ("The signs of original A(k), B(k), C(k) and B(k)^2-4*A(k)*C(k) are constant between all their exact real roots. Every open cell and each critical point is checked using "
                           + ("A>0 and discriminant<0, or A=B=0 and C>0" if problem["strict"] else
                              "A>0 and discriminant<=0, or A=B=0 and C>=0")
                           + ", including affine and constant degeneration. Strict positivity is required when the original square root is a denominator, regardless of its numerator."),
            },
            "cells": cells,
            "reconstructed_set": math_value(reconstructed),
            "candidate_set": math_value(feasible_set),
        }
        if problem.get("family") == "halfline_root_ratio":
            from .domain_halfline import source_certificate

            result["proof"].update(
                category="original-domain-parameter-halfline-offset-partition/v1",
                prescribed_domain=math_value(problem["domain"]),
                domain_equivalence=source_certificate(problem),
                invariance={"proved": True, "reason": (
                    "The original denominator is defined and nonzero exactly on the prescribed halfline. "
                    "The original numerator is a fixed quadratic, affine or constant polynomial plus d*m. "
                    "Its infimum follows from the leading coefficient, tail direction, and exact vertex position; "
                    "its sign is constant between the exact parameter roots. All open cells and roots are checked."
                )},
            )
        mismatch = _set_mismatch(reconstructed, feasible_set)
        if mismatch is None:
            result["status"] = "verified"
        else:
            holds, evidence = _domain_parameter_at(problem, mismatch)
            result.update(status="math_failed", counterexample={
                "parameter": math_value(mismatch), "original_holds": holds,
                "candidate_includes": _contains_exact(feasible_set, mismatch), "evidence": evidence,
            })
            result["diagnostics"] = [{"code": "verification.set_mismatch", "path": target_ref}]
    except ContextMismatch as exc:
        result.update(status="math_failed", diagnostics=[{
            "code": "constraint_context_mismatch", "message": str(exc), "path": target_ref,
        }])
    except (VerificationGap, NotationError, BasePolynomialError, NotImplementedError) as exc:
        result["diagnostics"] = [{"code": "verification_incomplete", "message": str(exc), "path": target_ref}]
    return result


def _original(candidate, target_ref):
    from .verification import VerificationGap

    description = inspect_domain_target(candidate, target_ref)
    if description["structure_supported"] is not True:
        raise VerificationGap(description["reason"])
    return description


def _evaluate(ast, point):
    """Definedness before arithmetic: cancellation never erases a source guard."""
    if ast == ARGUMENT:
        return True, point
    if ast[0] == "number":
        return True, sp.Rational(ast[1])
    if ast[0] == "neg":
        defined, value = _evaluate(ast[1], point)
        return defined, -value if defined else None
    if ast[:2] == ["call", "sqrt"]:
        defined, value = _evaluate(ast[2], point)
        if not defined or _is_negative(value):
            return False, None
        return True, sp.Integer(0) if _is_zero(value) else sp.sqrt(value)
    if ast[:2] == ["call", "abs"]:
        defined, value = _evaluate(ast[2], point)
        return defined, sp.Abs(value) if defined else None
    if ast[0] == "^":
        defined, value = _evaluate(ast[1], point)
        exponent = _integer_exponent(ast[2])
        if not defined or (exponent == 0 and _is_zero(value)):
            return False, None
        return True, value ** exponent
    lhs_ok, lhs = _evaluate(ast[1], point)
    rhs_ok, rhs = _evaluate(ast[2], point)
    if not lhs_ok or not rhs_ok or (ast[0] == "/" and _is_zero(rhs)):
        return False, None
    return True, {
        "+": lambda: lhs + rhs,
        "-": lambda: lhs - rhs,
        "*": lambda: lhs * rhs,
        "/": lambda: lhs / rhs,
    }[ast[0]]()


def _critical(description):
    rows, points, by_path = [], set(), {}

    def record(child, polynomial_path, source, max_degree=MAX_FIXED_POLYNOMIAL_DEGREE, square_origin=None):
        # A sqrt divisor and its own real-definedness condition use the
        # same polynomial at the same original position. Keep both
        # requirements, but produce its critical-polynomial evidence once.
        key = (description["source_ref"], polynomial_path)
        row = by_path.get(key)
        if row is None:
            roots, root_completeness = _poly_roots_proof(child, max_degree)
            points.update(roots)
            row = {
                "source_ref": description["source_ref"],
                "ast_path": list(polynomial_path),
                "expression_ast": deepcopy(child),
                "roots": [math_value(p) for p in roots],
                "root_completeness": root_completeness,
                "condition_sources": [],
                **({"square_structure": square_origin} if square_origin else {}),
            }
            rows.append(row)
            by_path[key] = row
        if source not in row["condition_sources"]:
            row["condition_sources"].append(source)

    def record_radical(ast, path, source):
        base = _square_radicand_base(ast[2])
        if base is None:
            record(ast[2], (*path, 2), source)
        else:
            record(base, (*path, 2, 1), source, square_origin={
                "ast_path": [*path, 2], "expression_ast": deepcopy(ast[2]),
                "basis_refs": ["square-nonnegative#nonnegative"], "passed": True,
            })

    def record_divisor(ast, path):
        if ast[0] == "neg":
            record_divisor(ast[1], (*path, 1))
            return
        if ast[0] == "*":
            record_divisor(ast[1], (*path, 1))
            record_divisor(ast[2], (*path, 2))
            return
        if ast[:2] == ["call", "sqrt"]:
            # Polynomial evidence is the radicand; the nonzero condition points
            # at the whole square-root divisor in the original tree.
            record_radical(
                ast,
                path,
                {
                    "source_ref": description["source_ref"],
                    "ast_path": list(path),
                    "kind": "denominator_nonzero",
                },
            )
            return
        if ast[0] == "^" and _integer_exponent(ast[2]) == 0:
            return
        record(
            ast,
            path,
            {
                "source_ref": description["source_ref"],
                "ast_path": list(path),
                "kind": "denominator_nonzero",
            },
            max_degree=MAX_FIXED_POLYNOMIAL_DEGREE,
        )

    def visit(ast, path=()):
        if ast[:2] == ["call", "sqrt"]:
            record_radical(
                ast,
                path,
                {
                    "source_ref": description["source_ref"],
                    "ast_path": [*path, 2],
                    "kind": "radicand_nonnegative",
                },
            )
        elif ast[0] == "^" and _integer_exponent(ast[2]) == 0:
            record(
                ast[1],
                (*path, 1),
                {
                    "source_ref": description["source_ref"],
                    "ast_path": [*path, 1],
                    "kind": "zero_power_base_nonzero",
                },
                max_degree=MAX_FIXED_POLYNOMIAL_DEGREE,
            )
        elif ast[0] == "/":
            record_divisor(ast[2], (*path, 2))
        for index, child in enumerate(ast[1:], 1):
            if isinstance(child, list):
                visit(child, (*path, index))

    visit(description["expression_ast"])
    domain = input_set(description)
    points.update(
        p for p in getattr(domain.boundary, "args", ()) if p not in (-sp.oo, sp.oo)
    )
    return sorted(points), rows


def _holds(description, point):
    included = input_set(description).contains(point) is sp.true
    defined, _ = _evaluate(description["expression_ast"], point)
    return included and defined, {
        "input_domain_member": included,
        "original_expression_defined": defined,
    }


def verify_domain(candidate, target_ref, context, proposed):
    from .verification import (
        ContextMismatch,
        VerificationGap,
        _contains_exact,
        _rational_between,
        _set_mismatch,
        _supported_set,
        check_context,
        collect_original,
    )

    result_value = {"status": "capability_gap", "proof": {}, "diagnostics": []}
    try:
        check_context(collect_original(candidate, target_ref), context)
        description = _original(candidate, target_ref)
        if context.get("domain_goal") != description:
            raise ContextMismatch("constraint_context_mismatch:domain_goal")
        _supported_set(proposed)
        points, roots = _critical(description)
        cells, accepted = [], []
        for index, (left, right) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
            cell = sp.Interval.open(left, right)
            sample = _rational_between(left, right)
            holds, evidence = _holds(description, sample)
            cells.append(
                {
                    "kind": "open_interval",
                    "domain": math_value(cell),
                    "sample": math_value(sample),
                    "holds": holds,
                    "evidence": evidence,
                }
            )
            if holds:
                accepted.append(cell)
            if index < len(points):
                sample = points[index]
                holds, evidence = _holds(description, sample)
                cells.append(
                    {
                        "kind": "critical_point",
                        "domain": math_value(sp.FiniteSet(sample)),
                        "sample": math_value(sample),
                        "holds": holds,
                        "evidence": evidence,
                    }
                )
                if holds:
                    accepted.append(sp.FiniteSet(sample))
        rebuilt = sp.Union(*accepted)
        mismatch = _set_mismatch(rebuilt, proposed)
        result_value.update(
            status="verified" if mismatch is None else "math_failed",
            proof={
                "category": "original-fixed-rational-polynomial-function-domain/v6",
                "source_refs": [description["source_ref"]],
                "expression_ast": description["expression_ast"],
                "critical_polynomials": roots,
                "critical_points": [math_value(p) for p in points],
                "invariance": {
                    "proved": True,
                    "reason": "Every original fixed rational radicand, polynomial divisor factor and zero-power base (degree ≤6) is checked on a complete rational-root partition, independently certified by exact real-root isolation and Sturm root counting. A source square is nonnegative wherever its recursively retained base is defined. Positive integer powers and absolute values retain their argument's definedness. Original syntax and explicit input-domain membership are evaluated independently at every critical point.",
                },
                "cells": cells,
                "reconstructed_set": math_value(rebuilt),
                "candidate_set": math_value(proposed),
            },
        )
        if mismatch is not None:
            holds, evidence = _holds(description, mismatch)
            result_value["counterexample"] = {
                "variable": math_value(mismatch),
                "original_holds": holds,
                "candidate_includes": _contains_exact(proposed, mismatch),
                "evidence": evidence,
            }
            result_value["diagnostics"] = [
                {"code": "verification.set_mismatch", "path": target_ref}
            ]
    except ContextMismatch as exc:
        result_value.update(
            status="math_failed",
            diagnostics=[
                {
                    "code": "constraint_context_mismatch",
                    "message": str(exc),
                    "path": target_ref,
                }
            ],
        )
    except (VerificationGap, ValueError, NotationError) as exc:
        result_value["diagnostics"] = [
            {"code": "verification_incomplete", "message": str(exc), "path": target_ref}
        ]
    return result_value


def domain_endpoints(candidate, target_ref, proposed):
    from .trajectory import encode_value
    from .verification import _contains_exact

    description = _original(candidate, target_ref)
    points, _ = _critical(description)
    # Includes excluded isolated points and every original restriction boundary,
    # even if a redundant restriction is absent from the final set's boundary.
    rows = []
    for point in points:
        holds, evidence = _holds(description, point)
        included = _contains_exact(proposed, point)
        sources = []

        def visit(ast, path=(), *, at=point, evidence_rows=sources):
            if ast[:2] == ["call", "sqrt"] or ast[0] == "/" or (ast[0] == "^" and _integer_exponent(ast[2]) == 0):
                radical = ast[:2] == ["call", "sqrt"]
                zero_power = ast[0] == "^"
                index = 1 if zero_power else 2
                defined, value = _evaluate(ast[index], at)
                holds_here = bool(
                    defined
                    and (
                        not _is_negative(value) if radical else not _is_zero(value)
                    )
                )
                evidence_rows.append(
                    {
                        "source_ref": description["source_ref"],
                        "ast_path": [*path, index],
                        "kind": "zero_power_base_nonzero" if zero_power else
                        "radicand_nonnegative" if radical else "denominator_nonzero",
                        "basis_refs": [
                            "integer-power#zero-exponent" if zero_power else
                            "square-root-expression#meaning" if radical else "rational-expression#meaning"
                        ],
                        "expression_defined": defined,
                        "holds": holds_here,
                    }
                )
            for index, child in enumerate(ast[1:], 1):
                if isinstance(child, list):
                    visit(child, (*path, index))

        visit(description["expression_ast"])
        if description["input_domain_source_ref"]:
            sources.append(
                {
                    "source_ref": description["input_domain_source_ref"],
                    "ast_path": [],
                    "kind": "explicit_input_domain",
                    "basis_refs": ["function-concept#elements"],
                    "holds": evidence["input_domain_member"],
                }
            )
        evidence["sources"] = sources
        rows.append(
            {
                "point": {**math_value(point), "exact": encode_value(point)},
                "included": included,
                "holds": holds,
                "passed": included == holds,
                "evidence": evidence,
            }
        )
    return {
        "status": "passed" if all(row["passed"] for row in rows) else "failed",
        "points": rows,
    }
