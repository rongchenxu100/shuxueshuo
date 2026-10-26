"""Original-syntax domain conditions and an independent exact domain verifier.

Extraction does not solve. Verification does not consume extracted conditions:
it evaluates the original tree on a complete sign-invariant partition.
"""

from copy import deepcopy
from itertools import pairwise

import sympy as sp

from ..stage_one.function_domain import (
    ARGUMENT,
    _affine,
    _input_domain,
    _inspect_expression,
    inspect_domain_target,
)
from .math_values import math_value


def expression(ast, variable):
    if ast == ARGUMENT:
        return variable
    kind = ast[0]
    if kind == "number":
        return sp.Rational(ast[1])
    if kind == "infinity":
        return sp.oo
    if kind == "neg":
        return -expression(ast[1], variable)
    if kind == "call" and ast[1] == "sqrt":
        return sp.Pow(expression(ast[2], variable), sp.Rational(1, 2), evaluate=False)
    left, right = (expression(a, variable) for a in ast[1:])
    return {
        "+": lambda: left + right,
        "-": lambda: left - right,
        "*": lambda: left * right,
        "/": lambda: left / right,
    }[kind]()


def input_set(description):
    ast = description["input_domain_ast"]
    if ast == ["real"]:
        return sp.S.Reals
    variable = sp.Symbol(description["variable"], real=True)
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

    def visit(ast, path=()):
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
            add(
                ast[2], (*path, 2), "denominator_nonzero", "rational-expression#meaning"
            )
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
                "domain_radicand_conditions"
                if row["kind"] == "radicand_nonnegative"
                else "domain_denominator_conditions"
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


def prepare_domain_conditions(constraints, variable):
    from .capabilities import CapabilityGap, result

    conditions, checks, operations = [], [], []
    for row in constraints:
        ast = row["expression_ast"]
        condition = row["condition"]
        if row["kind"] == "denominator_nonzero" and ast[:2] == ["call", "sqrt"]:
            # sqrt(t) != 0 iff t != 0 on the separately retained t >= 0 domain.
            radial = expression(ast[2], variable)
            if not any(
                r["kind"] == "radicand_nonnegative" and r["expression_ast"] == ast[2]
                for r in constraints
            ):
                raise CapabilityGap("domain.sqrt_guard_missing")
            condition = sp.Ne(radial, 0, evaluate=False)
            operations.append("domain_condition_normalization")
        conditions.append(condition)
        checks.append(
            {
                "kind": "domain_condition_normalization",
                "passed": True,
                "condition_id": row["condition_id"],
                "original": row["condition"],
                "normalized": condition,
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
        if not defined or value < 0:
            return False, None
        return True, sp.sqrt(value)
    lhs_ok, lhs = _evaluate(ast[1], point)
    rhs_ok, rhs = _evaluate(ast[2], point)
    if not lhs_ok or not rhs_ok or (ast[0] == "/" and rhs == 0):
        return False, None
    return True, {
        "+": lambda: lhs + rhs,
        "-": lambda: lhs - rhs,
        "*": lambda: lhs * rhs,
        "/": lambda: lhs / rhs,
    }[ast[0]]()


def _critical(description):
    rows, points, by_path = [], set(), {}

    def visit(ast, path=()):
        if ast[:2] == ["call", "sqrt"] or ast[0] == "/":
            child, polynomial_path = ast[2], (*path, 2)
            if child[:2] == ["call", "sqrt"]:
                child, polynomial_path = child[2], (*polynomial_path, 2)
            source = {
                "source_ref": description["source_ref"],
                "ast_path": [*path, 2],
                "kind": "radicand_nonnegative" if ast[:2] == ["call", "sqrt"] else "denominator_nonzero",
            }
            # A sqrt divisor and its own real-definedness condition use the
            # same polynomial at the same original position. Keep both
            # requirements, but produce its critical-polynomial evidence once.
            key = (description["source_ref"], polynomial_path)
            row = by_path.get(key)
            if row is None:
                slope, constant = _affine(child)
                roots = [] if not slope else [sp.Rational(-constant / slope)]
                points.update(roots)
                row = {
                    "source_ref": description["source_ref"],
                    "ast_path": list(polynomial_path),
                    "expression_ast": deepcopy(child),
                    "roots": [math_value(p) for p in roots],
                    "condition_sources": [],
                }
                rows.append(row)
                by_path[key] = row
            if source not in row["condition_sources"]:
                row["condition_sources"].append(source)
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
                "category": "original-fixed-affine-radical-division-domain/v1",
                "source_refs": [description["source_ref"]],
                "expression_ast": description["expression_ast"],
                "critical_polynomials": roots,
                "critical_points": [math_value(p) for p in points],
                "invariance": {
                    "proved": True,
                    "reason": "Every original radicand and divisor has fixed sign between all affine roots; original syntax and explicit interval membership are evaluated independently at every critical point.",
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
    except VerificationGap as exc:
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
            if ast[:2] == ["call", "sqrt"] or ast[0] == "/":
                radical = ast[:2] == ["call", "sqrt"]
                defined, value = _evaluate(ast[2], at)
                holds_here = bool(defined and (value >= 0 if radical else value != 0))
                evidence_rows.append(
                    {
                        "source_ref": description["source_ref"],
                        "ast_path": [*path, 2],
                        "kind": "radicand_nonnegative"
                        if radical
                        else "denominator_nonzero",
                        "basis_refs": [
                            "square-root-expression#meaning"
                            if radical
                            else "rational-expression#meaning"
                        ],
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
