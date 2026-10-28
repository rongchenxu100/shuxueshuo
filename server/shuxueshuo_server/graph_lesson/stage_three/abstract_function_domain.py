"""Batch-1 abstract-function domain: identity known form, affine target preimage."""

from fractions import Fraction
from itertools import pairwise

import sympy as sp

from ...problem_understanding.notation_parser import NotationError
from ..stage_one.abstract_function_domain import VERSION, inspect_abstract_domain_target
from ..stage_one.function_domain import (
    MAX_COEFFICIENT_BITS,
    MAX_INTEGER_EXPONENT,
    _input_domain,
)
from .capabilities.cases import exact_set_equal
from .capabilities.substitution import _affine_interval
from .function_domain import input_set
from .math_values import math_value


def admitted(context):
    value = context.get("abstract_domain_goal", {})
    goal = context.get("goal", {})
    if goal.get("kind") != "find_abstract_domain":
        return False
    if value.get("structure_supported") is not True:
        return False
    if value.get("known_form") != "identity" or value.get("known_strength") != "exact":
        return False
    if context.get("entries"):
        return False
    try:
        _input_domain(value["known_domain_ast"])
        _input_domain(value["outer_domain_ast"])
        Fraction(value["target_slope"])
        Fraction(value["target_intercept"])
    except (NotationError, ValueError, TypeError, ZeroDivisionError):
        return False
    return True


def _domain_set(description, field):
    return input_set({
        "variable": description["variable"],
        "input_domain_ast": description[field],
    })


def _affine_coeffs(description):
    return Fraction(description["target_slope"]), Fraction(description["target_intercept"])


def affine_preimage(domain, slope, intercept):
    """Exact preimage of a real set under ``x ↦ slope·x + intercept``."""
    slope = sp.Rational(slope)
    intercept = sp.Rational(intercept)
    if slope == 0:
        contains = domain.contains(intercept)
        if contains is sp.true:
            return sp.S.Reals
        if contains is sp.false:
            return sp.S.EmptySet
        raise NotationError("abstract_domain.constant_membership_unknown")
    # Image under the inverse map recovers the preimage for intervals and finite
    # unions thereof; FiniteSet and EmptySet are handled by SymPy set mapping.
    inverse_slope = 1 / slope
    inverse_intercept = -intercept / slope
    if isinstance(domain, sp.Interval):
        return _affine_interval(domain, inverse_slope, inverse_intercept)
    if domain == sp.S.EmptySet:
        return sp.S.EmptySet
    if isinstance(domain, sp.FiniteSet):
        return sp.FiniteSet(*((point - intercept) / slope for point in domain))
    if isinstance(domain, sp.Union):
        parts = [affine_preimage(part, slope, intercept) for part in domain.args]
        return sp.Union(*parts) if parts else sp.S.EmptySet
    raise NotationError("abstract_domain.unsupported_known_domain_shape")


def solve_abstract_domain(description):
    """Return the outer-variable domain and dual-track board evidence."""
    from .capabilities import CapabilityGap, result

    if description.get("structure_supported") is not True:
        raise CapabilityGap("abstract_domain.structure_unsupported")
    if description.get("known_form") != "identity":
        raise CapabilityGap("abstract_domain.identity_known_form_required")
    known = _domain_set(description, "known_domain_ast")
    if known == sp.S.EmptySet:
        raise CapabilityGap("abstract_domain.empty_known_domain")
    outer = _domain_set(description, "outer_domain_ast")
    slope, intercept = _affine_coeffs(description)
    slope_sym = sp.Rational(slope)
    intercept_sym = sp.Rational(intercept)
    preimage = affine_preimage(known, slope_sym, intercept_sym)
    answer = sp.Intersection(preimage, outer)
    variable = sp.Symbol(description["variable"], real=True)
    target_expr = slope_sym * variable + intercept_sym
    target = f"{description['function_name']}({description['target_argument_latex']})"
    board = {
        "upper_label": f"${target}$ 的定义域（自变量 ${description['variable']}$）",
        "lower_label": f"${description['function_name']}$ 的输入范围",
        "complete_input": description["target_argument_latex"],
        "lower_set": math_value(known),
        "upper_set": math_value(answer),
        "phase": "conclusion",
        "known_aligned": True,
    }
    checks = [
        {
            "kind": "abstract_known_identity_alignment",
            "passed": True,
            "known_form": "identity",
            "input_range": math_value(known),
        },
        {
            "kind": "abstract_affine_preimage",
            "passed": True,
            "slope": math_value(slope_sym),
            "intercept": math_value(intercept_sym),
            "complete_input": math_value(target_expr),
            "preimage": math_value(preimage),
        },
        {
            "kind": "abstract_outer_intersection",
            "passed": exact_set_equal(answer, sp.Intersection(preimage, outer)),
            "outer_domain": math_value(outer),
            "answer": math_value(answer),
        },
    ]
    return result(
        {
            "candidate_set": answer,
            "input_range": known,
            "preimage": preimage,
            "outer_domain": outer,
            "variable": variable,
            "complete_input": target_expr,
            "description": description,
            "board": board,
            "abstract_domain_result": {
                "kind": "find_abstract_domain",
                "input_range": known,
                "domain": answer,
                "slope": slope_sym,
                "intercept": intercept_sym,
            },
        },
        ["abstract_affine_preimage", "abstract_outer_intersection"],
        checks,
    )


def solve_abstract_function_domain(context):
    """Capability entry: read the re-inspected goal description from context."""
    from .capabilities import CapabilityGap

    description = context.get("abstract_domain_goal")
    if not admitted(context):
        raise CapabilityGap("abstract_domain.not_admitted")
    return solve_abstract_domain(description)


def _verification_expression(ast, variable_ref, variable, depth=0):
    """Interpret source arithmetic independently of the solver's coefficients."""
    if depth > 24:
        raise NotationError("abstract_domain.verification_structure_limit")
    kind = ast[0]
    read = lambda child: _verification_expression(child, variable_ref, variable, depth + 1)
    if kind == "number":
        value = sp.Rational(ast[1])
    elif kind == "ref" and ast == ["ref", variable_ref, "scalar"]:
        value = variable
    elif kind == "neg":
        value = -read(ast[1])
    elif kind in ("+", "-", "*", "/"):
        left, right = read(ast[1]), read(ast[2])
        if kind == "/":
            if right.is_Rational is not True or right == 0:
                raise NotationError("abstract_domain.verification_constant_divisor_required")
            value = left / right
        else:
            value = {"+": lambda: left + right, "-": lambda: left - right,
                     "*": lambda: left * right}[kind]()
    elif kind == "^" and ast[2][0] == "number":
        exponent = sp.Rational(ast[2][1])
        if exponent.is_Integer is not True or not 1 <= exponent <= MAX_INTEGER_EXPONENT:
            raise NotationError("abstract_domain.verification_power_unsupported")
        value = read(ast[1]) ** exponent
    else:
        raise NotationError("abstract_domain.verification_expression_unsupported")
    polynomial = sp.Poly(value, variable, domain=sp.QQ)
    if polynomial.degree() > 1:
        raise NotationError("abstract_domain.verification_affine_required")
    for coefficient in polynomial.all_coeffs():
        numerator, denominator = coefficient.as_numer_denom()
        if max(int(numerator).bit_length(), int(denominator).bit_length()) > MAX_COEFFICIENT_BITS:
            raise NotationError("abstract_domain.verification_coefficient_limit")
    return polynomial.as_expr()


def _verification_set(ast):
    """Read the original set AST without the solver's input_set conversion."""
    if ast == ["real"]:
        return sp.S.Reals

    def scalar(node):
        return _verification_expression(node, None, sp.Dummy("constant"))

    if ast[0] == "interval":
        def endpoint(node):
            if node[0] == "infinity":
                return sp.oo if node[1] == 1 else -sp.oo
            return scalar(node)

        return sp.Interval(endpoint(ast[3]), endpoint(ast[4]),
                           left_open=not ast[1], right_open=not ast[2])
    if ast[0] == "set":
        return sp.FiniteSet(*(scalar(point) for point in ast[1:]))
    if ast[0] == "set_difference":
        return _verification_set(ast[1]) - _verification_set(ast[2])
    raise NotationError("abstract_domain.verification_set_unsupported")


def _verification_source(candidate, target_ref):
    description = inspect_abstract_domain_target(candidate, target_ref)
    if not description.get("structure_supported"):
        raise NotationError("abstract_domain.verification_source_unsupported")
    known_argument = description["known_argument_ast"]
    if known_argument[0] != "ref" or known_argument[2] != "scalar":
        raise NotationError("abstract_domain.verification_identity_required")
    references = set()

    def collect(ast):
        if not isinstance(ast, list) or not ast:
            return
        if ast[0] == "ref":
            references.add(ast[1])
        for child in ast[1:]:
            collect(child)

    collect(description["target_argument_ast"])
    if len(references) > 1:
        raise NotationError("abstract_domain.verification_single_variable_required")
    variable_ref = next(iter(references), known_argument[1])
    variable = sp.Symbol(variable_ref.rsplit(":", 1)[-1], real=True)
    expression = _verification_expression(description["target_argument_ast"], variable_ref, variable)
    known = _verification_set(description["known_domain_ast"])
    outer = _verification_set(description["outer_domain_ast"])
    if known == sp.S.EmptySet:
        raise NotationError("abstract_domain.verification_empty_known_domain")
    return {"description": description, "variable": variable, "expression": expression,
            "known": known, "outer": outer}


def _membership(domain, point):
    value = domain.contains(point)
    if value not in (sp.true, sp.false):
        raise NotationError("abstract_domain.verification_membership_unknown")
    return value is sp.true


def _source_holds(source, point):
    complete_input = source["expression"].subs(source["variable"], point)
    input_holds = _membership(source["known"], complete_input)
    outer_holds = _membership(source["outer"], point)
    return input_holds and outer_holds, {
        "complete_input": math_value(complete_input),
        "input_in_known_domain": input_holds,
        "outer_domain_contains": outer_holds,
    }


def _boundary_points(domain):
    boundary = domain.boundary
    if boundary == sp.S.EmptySet:
        return []
    if not isinstance(boundary, sp.FiniteSet):
        raise NotationError("abstract_domain.verification_finite_boundary_required")
    return sorted(boundary)


def _verify_partition(source):
    """Check every constant-truth cell of the original affine membership relation.

    Each possible transition comes from an original input-domain boundary or
    an outer-domain boundary. Root solving and source substitution are separate
    from the execution path's affine interval transport.
    """
    cuts = set(_boundary_points(source["outer"]))
    if source["variable"] in source["expression"].free_symbols:
        for boundary in _boundary_points(source["known"]):
            roots = sp.solveset(source["expression"] - boundary,
                               source["variable"], domain=sp.S.Reals)
            if not isinstance(roots, sp.FiniteSet):
                raise NotationError("abstract_domain.verification_boundary_roots_unknown")
            cuts.update(roots)
    cuts = sorted(cuts)
    intervals, checks = [], []
    edges = [-sp.oo, *cuts, sp.oo]
    for left, right in pairwise(edges):
        point = (sp.S.Zero if left == -sp.oo and right == sp.oo else
                 right - 1 if left == -sp.oo else
                 left + 1 if right == sp.oo else (left + right) / 2)
        holds, evidence = _source_holds(source, point)
        cell = sp.Interval.open(left, right)
        checks.append({"cell": math_value(cell), "sample": math_value(point),
                       "holds": holds, **evidence})
        if holds:
            intervals.append(cell)
    for point in cuts:
        holds, evidence = _source_holds(source, point)
        checks.append({"point": math_value(point), "holds": holds, **evidence})
        if holds:
            intervals.append(sp.FiniteSet(point))
    expected = sp.Union(*intervals) if intervals else sp.S.EmptySet
    return expected, checks


def independent_verify(candidate, target_ref, candidate_set):
    """Verify original membership on a complete partition, without the solver."""
    source = _verification_source(candidate, target_ref)
    expected, cells = _verify_partition(source)
    passed = isinstance(candidate_set, sp.Set) and exact_set_equal(candidate_set, expected)
    return {
        "status": "verified" if passed else "verification_failed",
        "expected": math_value(expected),
        "actual": math_value(candidate_set),
        "checks": [
            {
                "kind": "abstract_domain_identity",
                "passed": passed,
                "expected": math_value(expected),
                "actual": math_value(candidate_set),
                "structure_version": VERSION,
            },
            {"kind": "abstract_original_relation_partition", "passed": True,
             "complete_input": math_value(source["expression"]),
             "known_domain": math_value(source["known"]),
             "outer_domain": math_value(source["outer"]), "cells": cells},
        ],
        "diagnostics": [] if passed else [{"code": "abstract_domain.answer_mismatch"}],
    }


def abstract_domain_endpoints(candidate, target_ref, candidate_set):
    """Substitute each reported endpoint into the original source relation."""
    source = _verification_source(candidate, target_ref)
    verified = independent_verify(candidate, target_ref, candidate_set)
    rows = []
    for point in _boundary_points(candidate_set):
        included = _membership(candidate_set, point)
        holds, evidence = _source_holds(source, point)
        passed = included == holds
        rows.append({
            "point": math_value(point), "included": included, "holds": holds,
            "passed": passed,
            "evidence": {"kind": "abstract_domain_endpoint", "passed": passed, **evidence},
        })
    passed = verified["status"] == "verified" and all(row["passed"] for row in rows)
    return {"status": "passed" if passed else "failed", "points": rows,
            "diagnostics": verified["diagnostics"]}
