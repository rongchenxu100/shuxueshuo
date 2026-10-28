"""Bounded real-function comparison with original domains and exact certificates.

The bounded families are quadratic polynomials, abs(Q), sqrt(Q^2),
P + abs(Q), (Q*L)/L and sqrt(affine)^2. Q's real zeros must be rational;
L is a nonzero affine polynomial. Original divisor restrictions survive.
An unsupported expression is unresolved, never unequal.
Descriptors come from the scoped notation compiler, not from model answers.
"""

from copy import deepcopy
from itertools import pairwise
from math import isqrt

import sympy as sp

from ..problem_understanding.notation_parser import NotationError
from .stage_one.function_domain import (
    _affine,
    _coefficient_budget,
    _fixed_poly,
    _input_domain,
    _inspect_expression,
    _integer_exponent,
    _rational_root_radicand,
)
from .stage_three.function_domain import (
    _critical,
    _evaluate,
    _holds,
    extract_domain_conditions,
    input_set,
    prepare_domain_conditions,
)
from .stage_three.verification import _rational_between

VERSION = "function-equality-quadratic-absolute/v2"
VARIABLE = sp.Symbol("u", real=True)


def _square(ast):
    return ast[0] == "^" and _integer_exponent(ast[2]) == 2


def _polynomial(ast, *, max_degree=2, sign_partition=False):
    coefficients = _fixed_poly(ast, max_degree=max_degree)
    for value in coefficients:
        _coefficient_budget(value)
    if sign_partition and not _rational_root_radicand(coefficients):
        raise NotationError("function_equality.rational_critical_points_required")
    return coefficients


def _polynomial_value(ast):
    return sum((sp.Rational(c.numerator, c.denominator) * VARIABLE**i
                for i, c in enumerate(_polynomial(ast))), sp.S.Zero)


def _rational_zeros(ast):
    """All distinct zeros, by exact degree <= 2 formulas; zero has no cuts."""
    coefficients = _polynomial(ast, sign_partition=True)
    if len(coefficients) == 1:
        return []
    c, b = coefficients[:2]
    if len(coefficients) == 2:
        return [sp.Rational(-c / b)]
    a = coefficients[2]
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return []
    root = sp.Rational(isqrt(discriminant.numerator), isqrt(discriminant.denominator))
    return sorted({(-sp.Rational(b) - root) / (2 * sp.Rational(a)),
                   (-sp.Rational(b) + root) / (2 * sp.Rational(a))})


def _cancelled_product(ast):
    if ast[0] != "/" or ast[1][0] != "*":
        raise NotationError("function_equality.structure_unsupported")
    denominator = _polynomial(ast[2], max_degree=1)
    if not any(denominator):
        raise NotationError("function_equality.nonzero_affine_factor_required")
    for factor_index, quotient_index in ((1, 2), (2, 1)):
        factor, quotient = ast[1][factor_index], ast[1][quotient_index]
        try:
            if _polynomial(factor, max_degree=1) != denominator:
                continue
            _polynomial(quotient)
            return {"quotient": quotient, "factor": factor, "denominator": ast[2],
                    "factor_path": [1, factor_index]}
        except NotationError:
            continue
    raise NotationError("function_equality.structure_unsupported")


def _family(ast):
    # This also enforces the shared AST, coefficient and expansion budgets.
    _inspect_expression(ast)
    try:
        _polynomial(ast)
        return "polynomial", ast
    except NotationError:
        pass
    if ast[:2] == ["call", "abs"]:
        coefficients = _polynomial(ast[2], sign_partition=True)
        return ("absolute_affine" if len(coefficients) <= 2 else "absolute_quadratic"), ast[2]
    if ast[:2] == ["call", "sqrt"] and _square(ast[2]):
        _polynomial(ast[2][1], sign_partition=True)
        return "square_root_square", ast[2][1]
    if _square(ast) and ast[1][:2] == ["call", "sqrt"]:
        _affine(ast[1][2])
        return "square_root_squared", ast[1][2]
    if ast[0] == "+":
        for absolute_index, polynomial_index in ((1, 2), (2, 1)):
            absolute = ast[absolute_index]
            if absolute[:2] == ["call", "abs"]:
                _polynomial(absolute[2], sign_partition=True)
                _polynomial(ast[polynomial_index])
                return "polynomial_plus_absolute", {
                    "absolute": absolute[2], "polynomial": ast[polynomial_index],
                    "absolute_path": [absolute_index, 2], "polynomial_path": [polynomial_index]}
    if ast[0] == "/":
        return "cancelled_affine_factor", _cancelled_product(ast)
    raise NotationError("function_equality.structure_unsupported")


def structural_inspect(descriptor):
    """No solving: identify the admitted family and declared-domain syntax."""
    try:
        if not all(isinstance(descriptor.get(key), str) and descriptor[key]
                   for key in ("source_ref", "function_ref", "variable")):
            raise NotationError("function_equality.source_binding_required")
        family, _ = _family(descriptor["expression_ast"])
        _input_domain(descriptor.get("input_domain_ast", ["real"]))
        return {"structure_supported": True, "reason": "", "family": family}
    except (NotationError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        return {"structure_supported": False,
                "reason": getattr(exc, "code", "function_equality.invalid_descriptor")}


def _description(descriptor, *, natural=False):
    inspected = structural_inspect(descriptor)
    if not inspected["structure_supported"]:
        raise NotationError(inspected["reason"])
    return {**deepcopy(descriptor), "structure_supported": True,
            "input_domain_ast": (["real"] if natural else deepcopy(descriptor.get("input_domain_ast", ["real"]))),
            "input_domain_source_ref": "" if natural else descriptor.get("input_domain_source_ref", "")}


def _declared(descriptor):
    return (descriptor.get("explicit_domain") is True
            or bool(descriptor.get("input_domain_source_ref"))
            or descriptor.get("input_domain_ast", ["real"]) != ["real"])


def domain_context(descriptor, *, natural=True):
    """Scoped M1 binding; every source remains the original option function."""
    description = _description(descriptor, natural=natural)
    target = ["ref", description["function_ref"]]
    return {"goal": {"kind": "find_domain", "object": description.get("function_name", "f")},
            "goal_ast": {"target": target, "input_domain": description["input_domain_ast"]},
            "domain_goal": description,
            "entries": [{"source_ref": description["source_ref"],
                         "ast": ["function_definition", target, description["expression_ast"]]}]}


def _source_domain(descriptor):
    """Independent full domain reconstruction from original syntax, not guards."""
    description = _description(descriptor, natural=True)
    points, critical = _critical(description)
    cells, accepted = [], []
    for index, (left, right) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        interval = sp.Interval.open(left, right)
        sample = _rational_between(left, right)
        holds, evidence = _holds(description, sample)
        cells.append({"domain": interval, "sample": sample, "holds": holds, "evidence": evidence})
        if holds:
            accepted.append(interval)
        if index < len(points):
            point = points[index]
            holds, evidence = _holds(description, point)
            singleton = sp.FiniteSet(point)
            cells.append({"domain": singleton, "sample": point, "holds": holds, "evidence": evidence})
            if holds:
                accepted.append(singleton)
    natural = sp.Union(*accepted)
    declared = input_set(_description(descriptor))
    if _declared(descriptor) and declared - natural != sp.S.EmptySet:
        raise NotationError("function_equality.declared_domain_conflict")
    domain = natural.intersect(declared)
    if domain is sp.S.EmptySet:
        raise NotationError("function_equality.empty_function_domain")
    return domain, natural, {"kind": "original_domain_partition", "critical": critical, "cells": cells}


def _solve_domain(descriptor):
    """Use the existing M1 extraction/normalization/inequality capabilities."""
    from .stage_three.capabilities import REGISTRY

    context = domain_context(descriptor)
    extracted = extract_domain_conditions(context)["outputs"]
    conditions = prepare_domain_conditions(extracted["constraints"], extracted["variable"])["outputs"]["conditions"]
    solved = REGISTRY["solve_conditions"](
        conditions=conditions, combiner="all", variable=extracted["variable"], purpose="domain")
    natural = solved["outputs"]["solution"]
    declared = input_set(_description(descriptor))
    if _declared(descriptor) and declared - natural != sp.S.EmptySet:
        raise NotationError("function_equality.declared_domain_conflict")
    domain = natural.intersect(declared)
    if domain is sp.S.EmptySet:
        raise NotationError("function_equality.empty_function_domain")
    checked_domain, checked_natural, certificate = _source_domain(descriptor)
    if (checked_domain, checked_natural) != (domain, natural):
        raise NotationError("function_equality.domain_verification_failed")
    return {"function_ref": descriptor["function_ref"], "source_ref": descriptor["source_ref"],
            "expression_ast": deepcopy(descriptor["expression_ast"]),
            "input_domain_ast": deepcopy(descriptor.get("input_domain_ast", ["real"])),
            "domain": domain, "natural_domain": natural,
            "constraints": extracted["constraints"], "domain_evidence": certificate}


def _breakpoints(descriptor):
    family, body = _family(descriptor["expression_ast"])
    if family == "polynomial_plus_absolute":
        body = body["absolute"]
    elif family not in {"absolute_affine", "absolute_quadratic", "square_root_square"}:
        return []
    return _rational_zeros(body)


def _partition(domain, left, right):
    boundaries = list(domain.boundary) if isinstance(domain.boundary, sp.FiniteSet) else []
    points = sorted({*boundaries, *_breakpoints(left), *_breakpoints(right)})
    cells = []
    for index, (low, high) in enumerate(pairwise([-sp.oo, *points, sp.oo])):
        cell = sp.Interval.open(low, high).intersect(domain)
        if cell is not sp.S.EmptySet:
            if not isinstance(cell, sp.Interval):
                raise NotationError("function_equality.partition_unsupported")
            cells.append((cell, _rational_between(cell.start, cell.end)))
        if index < len(points) and domain.contains(points[index]) is sp.true:
            cells.append((sp.FiniteSet(points[index]), points[index]))
    if sp.Union(*(cell for cell, _ in cells)) != domain:
        raise NotationError("function_equality.partition_incomplete")
    return cells


def _absolute_rule(family, body, value, sample, sign, roots):
    rule = {"rule": "absolute_value_on_sign_cell", "sign": int(sign),
            "absolute_argument": value, "from_square_root": family == "square_root_square",
            "basis": "absolute-value-concept#rules",
            "sign_evidence": {"kind": "complete_polynomial_sign_partition",
                              "real_zeros": roots, "sample_value": value.subs(VARIABLE, sample)}}
    if family == "polynomial_plus_absolute":
        rule.update(polynomial_offset=_polynomial_value(body["polynomial"]),
                    absolute_ast_path=body["absolute_path"], polynomial_ast_path=body["polynomial_path"])
    return rule


def _cancellation_rule(body):
    return {"rule": "cancel_common_nonzero_factor", "common_factor": _polynomial_value(body["factor"]),
            "factor_ast_path": body["factor_path"], "divisor_ast_path": [2],
            "nonzero_on_cell": True, "basis": "rational-expression#cancellation"}


def _normal_form(descriptor, cell, sample):
    ast = descriptor["expression_ast"]
    family, body = _family(ast)
    if isinstance(cell, sp.FiniteSet):
        valid, value = _evaluate(ast, sample)
        if not valid:
            raise NotationError("function_equality.undefined_proof_point")
        return sp.expand(value), {"rule": "original_point_evaluation", "point": sample}
    if family == "cancelled_affine_factor":
        return _polynomial_value(body["quotient"]), _cancellation_rule(body)
    absolute = body["absolute"] if family == "polynomial_plus_absolute" else body
    value = _polynomial_value(absolute)
    if family == "polynomial":
        return value, {"rule": "polynomial_expansion"}
    if family == "square_root_squared":
        return value, {"rule": "square_of_real_square_root", "basis": "square-root-expression#meaning"}
    sign = sp.sign(value.subs(VARIABLE, sample))
    if sign not in (-1, 0, 1) or (sign == 0 and value != 0):
        raise NotationError("function_equality.sign_unknown")
    offset = _polynomial_value(body["polynomial"]) if family == "polynomial_plus_absolute" else sp.S.Zero
    return sp.expand(offset + sign * value), _absolute_rule(
        family, body, value, sample, sign, _rational_zeros(absolute))


def _verified_normal_form(descriptor, cell, sample):
    """Recheck the original rule without invoking the comparison normalizer.

    The producer cuts cells using rational quadratic formulas. The verifier
    independently counts roots of the source polynomial on each interval, so
    a missed sign change cannot be certified by a single sample observation.
    """
    ast = descriptor["expression_ast"]
    family, body = _family(ast)
    if isinstance(cell, sp.FiniteSet):
        defined, value = _evaluate(ast, sample)
        if not defined or cell != sp.FiniteSet(sample):
            raise NotationError("function_equality.undefined_proof_point")
        return sp.expand(value), {"rule": "original_point_evaluation", "point": sample}
    if not isinstance(cell, sp.Interval) or cell.contains(sample) is not sp.true:
        raise NotationError("function_equality.invalid_proof_cell")
    if family == "cancelled_affine_factor":
        divisor = _polynomial_value(body["denominator"])
        if any(cell.contains(root) is sp.true for root in sp.Poly(divisor, VARIABLE).real_roots()):
            raise NotationError("function_equality.cancellation_at_zero")
        return _polynomial_value(body["quotient"]), _cancellation_rule(body)
    absolute = body["absolute"] if family == "polynomial_plus_absolute" else body
    value = _polynomial_value(absolute)
    if family == "polynomial":
        return value, {"rule": "polynomial_expansion"}
    if family == "square_root_squared":
        # The source-domain certificate already proves the root is real on
        # the entire cell; this identity cannot extend the original domain.
        return value, {"rule": "square_of_real_square_root", "basis": "square-root-expression#meaning"}
    polynomial = sp.Poly(value, VARIABLE)
    roots = sorted(set(polynomial.real_roots())) if not polynomial.is_zero else []
    if any(not isinstance(root, sp.Rational) for root in roots):
        raise NotationError("function_equality.rational_critical_points_required")
    if not polynomial.is_zero:
        interior_roots = polynomial.count_roots(cell.start, cell.end)
        for endpoint, is_open in ((cell.start, cell.left_open), (cell.end, cell.right_open)):
            if is_open and endpoint not in (-sp.oo, sp.oo) and polynomial.eval(endpoint) == 0:
                interior_roots -= 1
        if interior_roots != 0:
            raise NotationError("function_equality.sign_cell_not_invariant")
    sign = sp.sign(polynomial.eval(sample))
    if sign not in (-1, 0, 1) or (sign == 0 and not polynomial.is_zero):
        raise NotationError("function_equality.sign_unknown")
    offset = _polynomial_value(body["polynomial"]) if family == "polynomial_plus_absolute" else sp.S.Zero
    return sp.expand(offset + sign * value), _absolute_rule(family, body, value, sample, sign, roots)


def _sample_set(domain):
    if isinstance(domain, sp.FiniteSet):
        return min(domain)
    if isinstance(domain, sp.Interval):
        return _rational_between(domain.start, domain.end)
    if isinstance(domain, sp.Union):
        return _sample_set(domain.args[0])
    if domain is sp.S.Reals:
        return sp.S.Zero
    raise NotationError("function_equality.witness_unavailable")


def _counterexample(left, right, cell, sample, polynomial):
    # A nonzero polynomial of degree <= 2 cannot vanish at three distinct
    # interior points. This is a bounded construction of a negative witness,
    # never an affirmative identity test by sampling.
    point = sample
    for _ in range(3):
        if sp.expand(polynomial.subs(VARIABLE, point)) != 0:
            valid_left, value_left = _evaluate(left["expression_ast"], point)
            valid_right, value_right = _evaluate(right["expression_ast"], point)
            if valid_left and valid_right and sp.simplify(value_left - value_right) != 0:
                return {"point": point, "left_value": value_left, "right_value": value_right}
        if not isinstance(cell, sp.Interval):
            break
        point = _rational_between(point, cell.end)
    raise NotationError("function_equality.witness_verification_failed")


def compare_pair(left, right):
    """Return an exact decision or an explicit unresolved capability/validity gap."""
    try:
        result = {"version": VERSION, "left": _solve_domain(left), "right": _solve_domain(right)}
        left_domain, right_domain = result["left"]["domain"], result["right"]["domain"]
        if left_domain != right_domain:
            point = _sample_set((left_domain - right_domain).union(right_domain - left_domain))
            result.update(relation="different", reason="domains_differ",
                          proof={"kind": "domain_counterexample"}, counterexample={
                              "point": point, "left_in_domain": left_domain.contains(point) is sp.true,
                              "right_in_domain": right_domain.contains(point) is sp.true})
            return result
        certificates = []
        for cell, sample in _partition(left_domain, left, right):
            lhs, left_rule = _normal_form(left, cell, sample)
            rhs, right_rule = _normal_form(right, cell, sample)
            difference = sp.expand(lhs - rhs)
            if difference != 0:
                result.update(relation="different", reason="outputs_differ",
                              proof={"kind": "output_counterexample"},
                              counterexample=_counterexample(left, right, cell, sample, difference))
                return result
            certificates.append({"domain": cell, "sample": sample,
                                 "left_polynomial": lhs, "right_polynomial": rhs,
                                 "left_rule": left_rule, "right_rule": right_rule})
        result.update(relation="equal", reason="same_domain_and_correspondence",
                      proof={"kind": "complete_piecewise_polynomial_identity", "cells": certificates})
        return result
    except (NotationError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, NotImplementedError) as exc:
        return {"version": VERSION, "relation": "unresolved",
                "reason": getattr(exc, "code", "function_equality.comparison_incomplete")}


def verify_pair(left, right, result):
    """Check domain certificates, complete polynomial identities or exact witnesses.

    Reconstruct domains directly from the original syntax rather than repeating
    M1's condition solver, and inspect every claimed proof cell and rule. A
    finite collection of observations can only disprove, never prove, identity.
    """
    try:
        if result.get("version") != VERSION or result.get("relation") not in {"equal", "different"}:
            raise NotationError("function_equality.complete_result_required")
        domains = []
        for side, descriptor in (("left", left), ("right", right)):
            domain, natural, certificate = _source_domain(descriptor)
            actual = result[side]
            expected = {"function_ref": descriptor["function_ref"], "source_ref": descriptor["source_ref"],
                        "expression_ast": descriptor["expression_ast"],
                        "input_domain_ast": descriptor.get("input_domain_ast", ["real"]),
                        "domain": domain, "natural_domain": natural, "domain_evidence": certificate}
            if any(actual.get(key) != value for key, value in expected.items()):
                raise NotationError("function_equality.domain_certificate_mismatch")
            # Source guards are presentational evidence, but cannot be forged.
            guards = extract_domain_conditions(domain_context(descriptor))["outputs"]["constraints"]
            if actual.get("constraints") != guards:
                raise NotationError("function_equality.source_conditions_mismatch")
            domains.append(domain)
        proof = result["proof"]
        if result["relation"] == "different":
            witness = result["counterexample"]
            point = witness["point"]
            # This family always has a rational witness; floating point
            # substitution must never be accepted as an exact certificate.
            if not isinstance(point, sp.Rational):
                raise NotationError("function_equality.invalid_witness")
            memberships = [domain.contains(point) is sp.true for domain in domains]
            if proof["kind"] == "domain_counterexample":
                if (memberships[0] == memberships[1] or result.get("reason") != "domains_differ"
                        or witness.get("left_in_domain") is not memberships[0]
                        or witness.get("right_in_domain") is not memberships[1]):
                    raise NotationError("function_equality.invalid_domain_witness")
            elif proof["kind"] == "output_counterexample":
                if domains[0] != domains[1] or not all(memberships) or result.get("reason") != "outputs_differ":
                    raise NotationError("function_equality.invalid_output_witness")
                lv, lhs = _evaluate(left["expression_ast"], point)
                rv, rhs = _evaluate(right["expression_ast"], point)
                if (not lv or not rv or sp.simplify(lhs - rhs) == 0
                        or witness.get("left_value") != lhs or witness.get("right_value") != rhs):
                    raise NotationError("function_equality.invalid_output_witness")
            else:
                raise NotationError("function_equality.proof_kind_mismatch")
        else:
            if (domains[0] != domains[1] or proof["kind"] != "complete_piecewise_polynomial_identity"
                    or result.get("reason") != "same_domain_and_correspondence"):
                raise NotationError("function_equality.identity_domain_mismatch")
            partition = _partition(domains[0], left, right)
            if len(proof["cells"]) != len(partition):
                raise NotationError("function_equality.identity_partition_incomplete")
            for (cell, sample), claim in zip(partition, proof["cells"], strict=True):
                lhs, left_rule = _verified_normal_form(left, cell, sample)
                rhs, right_rule = _verified_normal_form(right, cell, sample)
                expected = {"domain": cell, "sample": sample,
                            "left_polynomial": lhs, "right_polynomial": rhs,
                            "left_rule": left_rule, "right_rule": right_rule}
                if claim != expected or sp.expand(lhs - rhs) != 0:
                    raise NotationError("function_equality.identity_certificate_mismatch")
        return {"status": "verified", "diagnostics": [], "version": VERSION}
    except (NotationError, ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, NotImplementedError) as exc:
        return {"status": "math_failed", "diagnostics": [{
            "code": getattr(exc, "code", "function_equality.verification_incomplete")}]}
