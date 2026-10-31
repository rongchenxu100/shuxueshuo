"""Recover an abstract function's input range, then take an affine preimage."""

from copy import deepcopy
from fractions import Fraction
from itertools import pairwise

import sympy as sp

from ...problem_understanding.notation_parser import NotationError
from ..stage_one.abstract_function_domain import VERSION, inspect_abstract_domain_target
from ..stage_one.function_domain import (
    ARGUMENT,
    MAX_COEFFICIENT_BITS,
    MAX_INTEGER_EXPONENT,
    _affine,
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
    if value.get("known_form") not in ("identity", "affine") or value.get("known_strength") != "exact":
        return False
    if context.get("entries"):
        return False
    try:
        _input_domain(value["known_domain_ast"])
        _input_domain(value["outer_domain_ast"])
        known_slope, _ = _known_coeffs(value)
        if known_slope == 0:
            return False
        Fraction(value["target_slope"])
        Fraction(value["target_intercept"])
        _concrete_projection_ast(value)
    except (NotationError, KeyError, ValueError, TypeError, ZeroDivisionError):
        return False
    return True


def _domain_set(description, field):
    return input_set({
        "variable": description["variable"],
        "input_domain_ast": description[field],
    })


def _affine_coeffs(description):
    return Fraction(description["target_slope"]), Fraction(description["target_intercept"])


def _known_coeffs(description):
    if description.get("known_form") == "identity":
        return Fraction(1), Fraction(0)
    return Fraction(description["known_slope"]), Fraction(description["known_intercept"])


def _concrete_projection_ast(description):
    """Keep the denominator's source positions in a denominator-only projection."""
    form = description.get("target_form", "plain")
    original = description.get("target_call_ast")
    if form == "plain":
        if original is not None and original[0] != "function_call":
            raise NotationError("abstract_domain.target_form_mismatch")
        return None
    if form not in ("affine_denominator", "sqrt_affine_denominator"):
        raise NotationError("abstract_domain.target_form_unsupported")
    denominator = description["concrete_denominator_ast"]
    if (original[0] != "/" or original[2] != denominator
            or original[1][0] != "function_call"
            or original[1][2] != description["target_argument_ast"]):
        raise NotationError("abstract_domain.target_form_mismatch")

    def rewrite(ast):
        if not isinstance(ast, list) or not ast:
            return ast
        if ast[0] == "ref":
            if ast[2] != "scalar" or ast[1].rsplit(":", 1)[-1] != description["variable"]:
                raise NotationError("abstract_domain.single_outer_variable_required")
            return deepcopy(ARGUMENT)
        return [ast[0], *(rewrite(child) for child in ast[1:])]

    rewritten = rewrite(denominator)
    radical = form == "sqrt_affine_denominator"
    if radical and rewritten[:2] != ["call", "sqrt"]:
        raise NotationError("abstract_domain.target_form_mismatch")
    slope, intercept = _affine(rewritten[2] if radical else rewritten)
    if slope == 0 and (intercept <= 0 if radical else intercept == 0):
        raise NotationError("abstract_domain.invalid_constant_denominator")
    return ["/", ["number", "1"], rewritten]


def extract_abstract_concrete_conditions(description):
    """Reuse S3 on a denominator-only projection, with source paths retained.

    The abstract numerator is replaced by 1 only while extracting concrete
    denominator restrictions. This projection is not the whole target's domain.
    """
    from .capabilities import CapabilityGap, result
    from .function_domain import extract_domain_conditions

    if description.get("structure_supported") is not True:
        raise CapabilityGap("abstract_domain.structure_unsupported")
    try:
        body = _concrete_projection_ast(description)
    except (NotationError, KeyError, TypeError, ValueError) as exc:
        raise CapabilityGap("abstract_domain.concrete_structure_unsupported") from exc
    if body is None:
        return result(
            {"concrete_constraints": [], "raw_concrete_conditions": [], "concrete_description": None,
             "has_concrete_conditions": False},
            [], [{"kind": "abstract_no_concrete_restrictions", "passed": True}],
        )
    source_ref = description["target_call_source_ref"]
    concrete = {
        "structure_supported": True, "variable": description["variable"],
        "expression_ast": body, "input_domain_ast": ["real"],
        "source_ref": source_ref, "projection": "denominator_only",
        "original_target_ast": deepcopy(description["target_call_ast"]),
        "denominator_ast_path": [2],
    }
    projected_function = ["ref", source_ref + ":denominator_projection", "function"]
    extracted = extract_domain_conditions({
        "goal": {"kind": "find_domain"}, "goal_ast": {"target": projected_function},
        "domain_goal": concrete,
        "entries": [{"ast": ["function_definition", projected_function, body],
                     "source_ref": source_ref}],
    })
    rows = extracted["outputs"]["constraints"]
    return result(
        {"concrete_constraints": rows, "raw_concrete_conditions": extracted["outputs"]["conditions"],
         "concrete_description": concrete, "has_concrete_conditions": True},
        extracted["operations"],
        [{"kind": "abstract_denominator_only_projection", "passed": True,
          "source_ref": source_ref, "original_target_ast": deepcopy(description["target_call_ast"]),
          "denominator_ast_path": [2], "projection_expression_ast": body,
          "whole_target_equivalence_claimed": False}, *extracted["checks"]],
    )


def _solve_concrete_conditions(description, variable):
    from .capabilities import result, solve_conditions
    from .function_domain import prepare_domain_conditions

    extracted = extract_abstract_concrete_conditions(description)
    rows = extracted["outputs"]["concrete_constraints"]
    if not rows:
        return result({**extracted["outputs"], "concrete_conditions": [],
                       "concrete_solutions": [], "concrete_domain": sp.S.Reals},
                      extracted["operations"], extracted["checks"])
    normalized = prepare_domain_conditions(rows, variable)
    solved = solve_conditions(normalized["outputs"]["conditions"], "all", variable, purpose="domain")
    return result(
        {**extracted["outputs"], "concrete_conditions": normalized["outputs"]["conditions"],
         "concrete_solutions": solved["outputs"]["solutions"],
         "concrete_domain": solved["outputs"]["solution"]},
        sorted(set(extracted["operations"] + normalized["operations"] + solved["operations"])),
        extracted["checks"] + normalized["checks"] + solved["checks"],
    )


def affine_image(domain, slope, intercept):
    """Exact image under a nonzero rational affine bijection of the reals."""
    slope, intercept = sp.Rational(slope), sp.Rational(intercept)
    if slope == 0:
        raise NotationError("abstract_domain.nonzero_known_slope_required")
    if isinstance(domain, sp.Interval):
        return _affine_interval(domain, slope, intercept)
    if domain == sp.S.EmptySet:
        return sp.S.EmptySet
    if isinstance(domain, sp.FiniteSet):
        return sp.FiniteSet(*(slope * point + intercept for point in domain))
    if isinstance(domain, sp.Union):
        return sp.Union(*(affine_image(part, slope, intercept) for part in domain.args))
    raise NotationError("abstract_domain.unsupported_known_domain_shape")


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
    """Recover D_f from the known full domain and return the target domain."""
    from .capabilities import CapabilityGap, result

    if description.get("structure_supported") is not True:
        raise CapabilityGap("abstract_domain.structure_unsupported")
    if description.get("known_form") not in ("identity", "affine"):
        raise CapabilityGap("abstract_domain.affine_known_form_required")
    if description.get("known_strength") != "exact":
        raise CapabilityGap("abstract_domain.exact_strength_required")
    known_domain = _domain_set(description, "known_domain_ast")
    if known_domain == sp.S.EmptySet:
        raise CapabilityGap("abstract_domain.empty_known_domain")
    known_slope, known_intercept = map(sp.Rational, _known_coeffs(description))
    if known_slope == 0:
        raise CapabilityGap("abstract_domain.nonzero_known_slope_required")
    known = affine_image(known_domain, known_slope, known_intercept)
    known_variable = sp.Symbol(description.get("known_variable", description["variable"]), real=True)
    known_expr = known_slope * known_variable + known_intercept
    input_variable = sp.Dummy("input", real=True)
    known_inverse = (input_variable - known_intercept) / known_slope
    outer = _domain_set(description, "outer_domain_ast")
    slope, intercept = _affine_coeffs(description)
    slope_sym = sp.Rational(slope)
    intercept_sym = sp.Rational(intercept)
    preimage = affine_preimage(known, slope_sym, intercept_sym)
    abstract_domain = sp.Intersection(preimage, outer)
    variable = sp.Symbol(description["variable"], real=True)
    concrete = _solve_concrete_conditions(description, variable)
    concrete_domain = concrete["outputs"]["concrete_domain"]
    answer = sp.Intersection(abstract_domain, concrete_domain)
    target_expr = slope_sym * variable + intercept_sym
    target = description.get("target_latex") or f"{description['function_name']}({description['target_argument_latex']})"
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
            "kind": ("abstract_known_identity_alignment" if description["known_form"] == "identity"
                     else "abstract_known_affine_recovery"),
            "passed": True,
            "known_form": description["known_form"],
            "known_domain": math_value(known_domain),
            "input_range": math_value(known),
            "forward": math_value(known_expr),
            "inverse": math_value(known_inverse),
            "full_domain": True,
            "covers_all_real_inputs": known_slope != 0,
            "inverse_identities": bool(
                sp.expand(known_expr.subs(known_variable, known_inverse) - input_variable) == 0
                and sp.expand(known_inverse.subs(input_variable, known_expr) - known_variable) == 0
            ),
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
            "passed": exact_set_equal(abstract_domain, sp.Intersection(preimage, outer)),
            "outer_domain": math_value(outer),
            "answer": math_value(abstract_domain),
        },
        *concrete["checks"],
        {"kind": "abstract_concrete_intersection", "passed": True,
         "abstract_domain": math_value(abstract_domain), "concrete_domain": math_value(concrete_domain),
         "answer": math_value(answer)},
    ]
    return result(
        {
            "candidate_set": answer,
            "known_domain": known_domain,
            "input_range": known,
            "preimage": preimage,
            "abstract_domain": abstract_domain,
            **concrete["outputs"],
            "outer_domain": outer,
            "variable": variable,
            "complete_input": target_expr,
            "description": description,
            "board": board,
            "abstract_domain_result": {
                "kind": "find_abstract_domain",
                "known_domain": known_domain,
                "input_range": known,
                "domain": answer,
                "slope": slope_sym,
                "intercept": intercept_sym,
            },
        },
        ["abstract_affine_preimage", "abstract_outer_intersection", *concrete["operations"]],
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


def _verification_source(candidate, target_ref, *, range_goal=False):
    description = inspect_abstract_domain_target(candidate, target_ref, range_goal=range_goal)
    if not description.get("structure_supported"):
        raise NotationError("abstract_domain.verification_source_unsupported")

    def references(ast):
        if not isinstance(ast, list) or not ast:
            return set()
        if ast[0] == "ref":
            if ast[2] == "function":
                return set()
            if ast[2] != "scalar":
                raise NotationError("abstract_domain.verification_scalar_required")
            return {ast[1]}
        return set().union(*(references(child) for child in ast[1:]))

    target_ast = description["target_call_ast"]
    denominator_ast = target_ast[2] if target_ast[0] == "/" else None
    abstract_call = target_ast[1] if denominator_ast is not None else target_ast
    if (abstract_call[0] != "function_call"
            or abstract_call[1] != description["known_call_ast"][1]):
        raise NotationError("abstract_domain.verification_original_target_unsupported")
    known_refs = references(description["known_argument_ast"])
    target_refs = references(target_ast)
    if len(known_refs) != 1 or len(target_refs) > 1:
        raise NotationError("abstract_domain.verification_single_variable_required")
    known_ref = next(iter(known_refs))
    variable_ref = next(iter(target_refs), known_ref)
    variable = sp.Symbol(variable_ref.rsplit(":", 1)[-1], real=True)
    expression = _verification_expression(abstract_call[2], variable_ref, variable)
    concrete_expression, concrete_radical = None, False
    if denominator_ast is not None:
        concrete_radical = denominator_ast[:2] == ["call", "sqrt"]
        concrete_expression = _verification_expression(
            denominator_ast[2] if concrete_radical else denominator_ast, variable_ref, variable,
        )
        if variable not in concrete_expression.free_symbols and (
            concrete_expression <= 0 if concrete_radical else concrete_expression == 0
        ):
            raise NotationError("abstract_domain.verification_invalid_constant_denominator")
    # A fresh symbol keeps the known call's dummy input separate from the
    # target's outer variable, even when both are written x in the source.
    known_variable = sp.Dummy(known_ref.rsplit(":", 1)[-1], real=True)
    known_expression = _verification_expression(
        description["known_argument_ast"], known_ref, known_variable,
    )
    if known_variable not in known_expression.free_symbols:
        raise NotationError("abstract_domain.verification_nonzero_known_slope_required")
    input_variable = sp.Dummy("input", real=True)
    roots = sp.solveset(known_expression - input_variable, known_variable, domain=sp.S.Reals)
    if not isinstance(roots, sp.FiniteSet) or len(roots) != 1:
        raise NotationError("abstract_domain.verification_known_inverse_unknown")
    inverse = next(iter(roots))
    if (sp.expand(known_expression.subs(known_variable, inverse) - input_variable) != 0
            or sp.expand(inverse.subs(input_variable, known_expression) - known_variable) != 0):
        raise NotationError("abstract_domain.verification_known_coverage_failed")
    membership_expression = sp.expand(inverse.subs(input_variable, expression))
    known = _verification_set(description["known_domain_ast"])
    outer = _verification_set(description["outer_domain_ast"])
    if known == sp.S.EmptySet:
        raise NotationError("abstract_domain.verification_empty_known_domain")
    return {"description": description, "variable": variable, "expression": expression,
            "known_expression": known_expression, "known_inverse": inverse,
            "membership_expression": membership_expression, "known": known, "outer": outer,
            "concrete_expression": concrete_expression, "concrete_radical": concrete_radical,
            "original_target_ast": target_ast}


def _membership(domain, point):
    value = domain.contains(point)
    if value not in (sp.true, sp.false):
        raise NotationError("abstract_domain.verification_membership_unknown")
    return value is sp.true


def _source_holds(source, point):
    complete_input = source["expression"].subs(source["variable"], point)
    known_outer_input = source["membership_expression"].subs(source["variable"], point)
    input_holds = _membership(source["known"], known_outer_input)
    outer_holds = _membership(source["outer"], point)
    concrete_holds, concrete_checks = _source_concrete_holds(source, point)
    return input_holds and outer_holds and concrete_holds, {
        "complete_input": math_value(complete_input),
        "known_outer_input": math_value(known_outer_input),
        "input_in_known_domain": input_holds,
        "outer_domain_contains": outer_holds,
        "concrete_conditions_hold": concrete_holds,
        "concrete_conditions": concrete_checks,
    }


def _source_concrete_holds(source, point):
    expression = source["concrete_expression"]
    if expression is None:
        return True, []
    value = expression.subs(source["variable"], point)
    source_ref = source["description"]["target_call_source_ref"]
    if source["concrete_radical"]:
        defined = bool(value >= 0)
        nonzero = bool(value > 0)
        checks = [
            {"kind": "radicand_nonnegative", "source_ref": source_ref, "ast_path": [2, 2],
             "value": math_value(value), "holds": defined},
            {"kind": "denominator_nonzero", "source_ref": source_ref, "ast_path": [2],
             "defined": defined, "value": math_value(sp.sqrt(value)) if defined else None,
             "holds": nonzero},
        ]
        return defined and nonzero, checks
    nonzero = bool(value != 0)
    return nonzero, [{"kind": "denominator_nonzero", "source_ref": source_ref, "ast_path": [2],
                      "value": math_value(value), "holds": nonzero}]


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
    if source["variable"] in source["membership_expression"].free_symbols:
        for boundary in _boundary_points(source["known"]):
            roots = sp.solveset(source["membership_expression"] - boundary,
                               source["variable"], domain=sp.S.Reals)
            if not isinstance(roots, sp.FiniteSet):
                raise NotationError("abstract_domain.verification_boundary_roots_unknown")
            cuts.update(roots)
    concrete = source["concrete_expression"]
    if concrete is not None and source["variable"] in concrete.free_symbols:
        roots = sp.solveset(concrete, source["variable"], domain=sp.S.Reals)
        if not isinstance(roots, sp.FiniteSet):
            raise NotationError("abstract_domain.verification_concrete_roots_unknown")
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
             "known_complete_input": math_value(source["known_expression"]),
             "known_inverse": math_value(source["known_inverse"]),
             "membership_expression": math_value(source["membership_expression"]),
             "known_bijection_verified": True,
             "known_domain": math_value(source["known"]),
             "original_target_ast": deepcopy(source["original_target_ast"]),
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
