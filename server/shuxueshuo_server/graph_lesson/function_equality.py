"""Domain-first real-function comparison with independently checked certificates.

Domain admission belongs to M1. Correspondence simplification cannot prevent
a domain counterexample. Equal domains use either the existing polynomial
rules or bounded rational / radical-product identities, with sign proofs in
addition to squared identities. An unproved comparison remains unresolved.
"""

from copy import deepcopy
from fractions import Fraction
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

VERSION = "function-equality-domain-first-radical/v3"
VARIABLE = sp.Symbol("u", real=True)
MAX_CORRESPONDENCE_DEGREE = 24
MAX_SQUARE_DEGREE = 48
MAX_SIGN_CUTS = 48


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
    """Admit original domains; correspondence families are only display metadata."""
    try:
        if not all(isinstance(descriptor.get(key), str) and descriptor[key]
                   for key in ("source_ref", "function_ref", "variable")):
            raise NotationError("function_equality.source_binding_required")
        _inspect_expression(descriptor["expression_ast"])
        _input_domain(descriptor.get("input_domain_ast", ["real"]))
        try:
            family, _ = _family(descriptor["expression_ast"])
        except NotationError:
            family = "domain_only"
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


def _rational_parts(value, limit=MAX_CORRESPONDENCE_DEGREE):
    """Check exact coefficient/degree budgets before further polynomial work."""
    numerator, denominator = sp.fraction(value)
    parts = [sp.Poly(part, VARIABLE, domain=sp.QQ) for part in (numerator, denominator)]
    if parts[1].is_zero:
        raise NotationError("function_equality.zero_divisor")
    for part in parts:
        _polynomial_budget(part, limit)
    return parts


def _polynomial_budget(polynomial, limit):
    if polynomial.degree() > limit:
        raise NotationError("function_equality.correspondence_degree_limit")
    for coefficient in polynomial.all_coeffs():
        _coefficient_budget(Fraction(int(coefficient.p), int(coefficient.q)))


def _rational_op(left, right, operation, *, limit=MAX_CORRESPONDENCE_DEGREE):
    ln, ld = _rational_parts(left, limit)
    rn, rd = _rational_parts(right, limit)

    def multiply(first, second):
        if not first.is_zero and not second.is_zero and first.degree() + second.degree() > limit:
            raise NotationError("function_equality.correspondence_degree_limit")
        return first * second

    if operation in ("+", "-"):
        numerator = multiply(ln, rd) + (1 if operation == "+" else -1) * multiply(rn, ld)
        denominator = multiply(ld, rd)
    elif operation == "*":
        numerator, denominator = multiply(ln, rn), multiply(ld, rd)
    elif operation == "/" and not rn.is_zero:
        numerator, denominator = multiply(ln, rd), multiply(ld, rn)
    else:
        raise NotationError("function_equality.zero_divisor")
    # Check before cancellation as well: cancellation cannot conceal an
    # oversized intermediate polynomial or coefficients.
    _polynomial_budget(numerator, limit)
    _polynomial_budget(denominator, limit)
    raw = numerator.as_expr() / denominator.as_expr()
    _rational_parts(raw, limit)
    value = sp.cancel(raw)
    _rational_parts(value, limit)
    return value


def _rational_power(value, exponent, *, limit=MAX_CORRESPONDENCE_DEGREE):
    numerator, denominator = _rational_parts(value, limit)
    if any(not part.is_zero and part.degree() * exponent > limit for part in (numerator, denominator)):
        raise NotationError("function_equality.correspondence_degree_limit")
    for part in (numerator, denominator):
        if part.degree() <= 0:
            _coefficient_budget(Fraction(part.nth(0)) ** exponent)
    result = sp.cancel(numerator.as_expr() ** exponent / denominator.as_expr() ** exponent)
    _rational_parts(result, limit)
    return result


def _radical_monomial(ast):
    """Producer E=R*sqrt(S); sums are admitted only when both operands are rational.

    R and S have rational coefficients. Source-domain guards, including every
    original zero-power and divisor restriction, were solved before this step.
    This algebra never extends the function's domain.
    """
    if ast == ["bound", "function_argument"]:
        return VARIABLE, sp.S.One
    kind = ast[0]
    if kind == "number":
        return sp.Rational(ast[1]), sp.S.One
    if kind == "neg":
        coefficient, radicand = _radical_monomial(ast[1])
        return -coefficient, radicand
    if kind == "call" and ast[1] in ("sqrt", "abs"):
        argument, nested = _radical_monomial(ast[2])
        if nested != 1:
            raise NotationError("function_equality.radical_sum_unsupported")
        return sp.S.One, (argument if ast[1] == "sqrt" else _rational_power(argument, 2))
    if kind == "^":
        exponent = _integer_exponent(ast[2])
        coefficient, radicand = _radical_monomial(ast[1])
        coefficient = _rational_op(_rational_power(coefficient, exponent),
                                   _rational_power(radicand, exponent // 2), "*")
        return coefficient, radicand if exponent % 2 else sp.S.One
    if kind in ("+", "-", "*", "/"):
        lc, lr = _radical_monomial(ast[1])
        rc, rr = _radical_monomial(ast[2])
        if kind in ("+", "-"):
            if lr != 1 or rr != 1:
                raise NotationError("function_equality.radical_sum_unsupported")
            return _rational_op(lc, rc, kind), sp.S.One
        return _rational_op(lc, rc, kind), _rational_op(lr, rr, kind)
    raise NotationError("function_equality.structure_unsupported")


def _source_rational(ast):
    """Verifier: reconstruct rational arithmetic directly from the source tree."""
    if ast == ["bound", "function_argument"]:
        return VARIABLE
    if ast[0] == "number":
        result = sp.Rational(ast[1])
        _rational_parts(result)
        return result
    if ast[0] == "neg":
        return -_source_rational(ast[1])
    if ast[0] == "^":
        exponent = _integer_exponent(ast[2])
        try:
            base = _source_rational(ast[1])
        except NotationError as exc:
            if exc.code != "function_equality.rational_source_required" or exponent % 2:
                raise
            # Even powers erase the sign of a real base. Reconstruct its
            # square from source operations instead of requiring the inner
            # absolute value / radical to have constant sign on this cell.
            return _rational_power(_source_squared_rational(ast[1]), exponent // 2)
        return _rational_power(base, exponent)
    if ast[0] in ("+", "-", "*", "/"):
        return _rational_op(_source_rational(ast[1]), _source_rational(ast[2]), ast[0])
    raise NotationError("function_equality.rational_source_required")


def _source_squared_rational(ast):
    """Independent algebraic E² reconstruction; domain validity is already proved."""
    try:
        rational = _source_rational(ast)
    except NotationError as exc:
        if exc.code != "function_equality.rational_source_required":
            raise
    else:
        return _rational_power(rational, 2, limit=MAX_SQUARE_DEGREE)
    if ast[:2] == ["call", "sqrt"]:
        return _source_rational(ast[2])
    if ast[:2] == ["call", "abs"]:
        return _rational_power(_source_rational(ast[2]), 2, limit=MAX_SQUARE_DEGREE)
    if ast[0] == "neg":
        return _source_squared_rational(ast[1])
    if ast[0] == "^":
        return _rational_power(_source_squared_rational(ast[1]), _integer_exponent(ast[2]),
                               limit=MAX_SQUARE_DEGREE)
    if ast[0] in ("*", "/"):
        return _rational_op(_source_squared_rational(ast[1]), _source_squared_rational(ast[2]),
                            ast[0], limit=MAX_SQUARE_DEGREE)
    raise NotationError("function_equality.rational_source_required")


def _rational_cuts(value):
    points = set()
    for polynomial in _rational_parts(value):
        if polynomial.is_zero:
            continue
        roots = polynomial.ground_roots()
        # ground_roots supplies rational roots; Sturm counting independently
        # bounds the entire real root set, including repeated roots only once.
        if len(roots) != polynomial.count_roots(-sp.oo, sp.oo):
            raise NotationError("function_equality.rational_critical_points_required")
        points.update(roots)
    return points


def _partition_at(domain, points):
    boundaries = list(domain.boundary) if isinstance(domain.boundary, sp.FiniteSet) else []
    points = sorted({*boundaries, *points})
    if len(points) > MAX_SIGN_CUTS:
        raise NotationError("function_equality.sign_partition_limit")
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


def _rational_sign(value, cell, sample, *, verify=False):
    parts = _rational_parts(value, MAX_SQUARE_DEGREE)
    if verify:
        for polynomial in parts:
            if polynomial.is_zero:
                continue
            roots = polynomial.count_roots(cell.start, cell.end)
            for endpoint, opened in ((cell.start, cell.left_open), (cell.end, cell.right_open)):
                if opened and endpoint not in (-sp.oo, sp.oo) and polynomial.eval(endpoint) == 0:
                    roots -= 1
            if roots:
                raise NotationError("function_equality.sign_cell_not_invariant")
    evaluated = value.subs(VARIABLE, sample)
    sign = sp.sign(evaluated)
    if sign not in (-1, 0, 1) or (sign == 0 and not parts[0].is_zero):
        raise NotationError("function_equality.sign_unknown")
    return int(sign)


def _source_rules(ast):
    def contains(name, value):
        return (value[:2] == ["call", name]
                or any(contains(name, child) for child in value if isinstance(child, list)))

    return {"from_square_root": contains("sqrt", ast), "from_absolute": contains("abs", ast)}


def _signed_square_rule(square, sign, ast):
    return {"rule": "signed_square_on_sign_cell", "square": square, "sign": sign,
            "basis": "square-root-expression#meaning", **_source_rules(ast)}


def _rational_rule(value, ast):
    return {"rule": "bounded_rational_normal_form", "normal_form": value,
            "basis": "rational-expression#cancellation", **_source_rules(ast)}


def _monomial_square(monomial, cell, sample):
    coefficient, radicand = monomial
    radical_sign = _rational_sign(radicand, cell, sample)
    if radical_sign < 0:
        raise NotationError("function_equality.nonreal_radical")
    sign = _rational_sign(coefficient, cell, sample) if radical_sign else 0
    square = _rational_op(_rational_power(coefficient, 2, limit=MAX_SQUARE_DEGREE),
                          radicand, "*", limit=MAX_SQUARE_DEGREE)
    return square, sign


def _verified_square(ast, cell, sample):
    """Independent original-tree square/sign proof, never using E=R*sqrt(S).

    Each source rational expression is checked for all interior zeros/poles.
    A sample merely chooses the sign after Sturm counting proves invariance.
    Multiplication and division propagate exact squared values and signs.
    """
    try:
        rational = _source_rational(ast)
    except NotationError as exc:
        if exc.code != "function_equality.rational_source_required":
            raise
    else:
        return (_rational_power(rational, 2, limit=MAX_SQUARE_DEGREE),
                _rational_sign(rational, cell, sample, verify=True))
    if ast[:2] in (["call", "sqrt"], ["call", "abs"]):
        argument = _source_rational(ast[2])
        sign = _rational_sign(argument, cell, sample, verify=True)
        if ast[1] == "sqrt":
            if sign < 0:
                raise NotationError("function_equality.nonreal_radical")
            return argument, int(sign != 0)
        return _rational_power(argument, 2, limit=MAX_SQUARE_DEGREE), int(sign != 0)
    if ast[0] == "neg":
        square, sign = _verified_square(ast[1], cell, sample)
        return square, -sign
    if ast[0] == "^":
        exponent = _integer_exponent(ast[2])
        square, sign = _verified_square(ast[1], cell, sample)
        return _rational_power(square, exponent, limit=MAX_SQUARE_DEGREE), sign ** exponent
    if ast[0] in ("*", "/"):
        lsq, lsign = _verified_square(ast[1], cell, sample)
        rsq, rsign = _verified_square(ast[2], cell, sample)
        if ast[0] == "/" and rsign == 0:
            raise NotationError("function_equality.zero_divisor")
        return _rational_op(lsq, rsq, ast[0], limit=MAX_SQUARE_DEGREE), lsign * rsign
    raise NotationError("function_equality.radical_sum_unsupported")


def _generic_cell(descriptor, monomial, cell, sample, *, rational):
    if isinstance(cell, sp.FiniteSet):
        valid, value = _evaluate(descriptor["expression_ast"], sample)
        if not valid:
            raise NotationError("function_equality.undefined_proof_point")
        return value, {"rule": "original_point_evaluation", "point": sample}
    if rational:
        return monomial[0], _rational_rule(monomial[0], descriptor["expression_ast"])
    square, sign = _monomial_square(monomial, cell, sample)
    return sign * sp.sqrt(square), _signed_square_rule(square, sign, descriptor["expression_ast"])


def _verified_generic_cell(descriptor, cell, sample, rule):
    if not isinstance(sample, sp.Rational) or cell.contains(sample) is not sp.true:
        raise NotationError("function_equality.invalid_proof_cell")
    ast = descriptor["expression_ast"]
    if isinstance(cell, sp.FiniteSet):
        valid, value = _evaluate(ast, sample)
        if not valid or cell != sp.FiniteSet(sample):
            raise NotationError("function_equality.undefined_proof_point")
        return value, {"rule": "original_point_evaluation", "point": sample}
    if not isinstance(cell, sp.Interval):
        raise NotationError("function_equality.invalid_proof_cell")
    if rule.get("rule") == "bounded_rational_normal_form":
        try:
            value = _source_rational(ast)
        except NotationError as exc:
            if exc.code != "function_equality.rational_source_required":
                raise
            # Even powers can make a radical product rational. Check the
            # claimed rational value through the independent square/sign
            # proof; never reuse the producer's radical cancellation.
            value = rule["normal_form"]
            _rational_parts(value)
            square, sign = _verified_square(ast, cell, sample)
            if (_rational_power(value, 2, limit=MAX_SQUARE_DEGREE) != square
                    or _rational_sign(value, cell, sample, verify=True) != sign):
                raise NotationError("function_equality.identity_certificate_mismatch")
        return value, _rational_rule(value, ast)
    square, sign = _verified_square(ast, cell, sample)
    return sign * sp.sqrt(square), _signed_square_rule(square, sign, ast)


def _exact_output_witness(left, right, cell, sample):
    # At most 96 zeros can hide a nonzero squared rational difference. Even
    # outside that bound a failed search stays unresolved, never affirmative.
    point = sample
    for _ in range(2 * MAX_SQUARE_DEGREE + 1):
        lv, lhs = _evaluate(left["expression_ast"], point)
        rv, rhs = _evaluate(right["expression_ast"], point)
        difference = sp.simplify(lhs - rhs) if lv and rv else sp.S.Zero
        if lv and rv and difference.is_zero is False:
            return {"point": point, "left_value": lhs, "right_value": rhs}
        if not isinstance(cell, sp.Interval):
            break
        point = _rational_between(point, cell.end)
    raise NotationError("function_equality.witness_verification_failed")


def _generic_comparison(left, right, result):
    domain = result["left"]["domain"]
    if isinstance(domain, sp.FiniteSet):
        # This enumerates the proven *entire* domain, not a few observations
        # extrapolated to an interval. No correspondence-family gate applies.
        cells = []
        for point in sorted(domain):
            values = [_evaluate(item["expression_ast"], point) for item in (left, right)]
            if not all(valid for valid, _ in values):
                raise NotationError("function_equality.undefined_proof_point")
            lhs, rhs = (value for _, value in values)
            zero = sp.simplify(lhs - rhs).is_zero
            if zero is False:
                result.update(relation="different", reason="outputs_differ",
                              proof={"kind": "output_counterexample"},
                              counterexample={"point": point, "left_value": lhs, "right_value": rhs})
                return result
            if zero is not True:
                raise NotationError("function_equality.comparison_incomplete")
            rule = {"rule": "original_point_evaluation", "point": point}
            cells.append({"domain": sp.FiniteSet(point), "sample": point,
                          "left_polynomial": lhs, "right_polynomial": rhs,
                          "left_rule": deepcopy(rule), "right_rule": deepcopy(rule)})
        result.update(relation="equal", reason="same_domain_and_correspondence",
                      proof={"kind": "complete_piecewise_algebraic_identity", "cells": cells})
        return result
    monomials = [_radical_monomial(descriptor["expression_ast"]) for descriptor in (left, right)]
    rational = all(radicand == 1 for _, radicand in monomials)
    points = set()
    if not rational:
        for coefficient, radicand in monomials:
            points.update(_rational_cuts(coefficient))
            points.update(_rational_cuts(radicand))
    certificates = []
    for cell, sample in _partition_at(domain, points):
        lhs, left_rule = _generic_cell(left, monomials[0], cell, sample, rational=rational)
        rhs, right_rule = _generic_cell(right, monomials[1], cell, sample, rational=rational)
        if isinstance(cell, sp.Interval) and not rational:
            equal = (left_rule["sign"] == right_rule["sign"]
                     and _rational_op(left_rule["square"], right_rule["square"], "-",
                                      limit=2 * MAX_SQUARE_DEGREE) == 0)
        else:
            equal = sp.cancel(lhs - rhs) == 0
        if not equal:
            result.update(relation="different", reason="outputs_differ", proof={"kind": "output_counterexample"},
                          counterexample=_exact_output_witness(left, right, cell, sample))
            return result
        certificates.append({"domain": cell, "sample": sample,
                             "left_polynomial": lhs, "right_polynomial": rhs,
                             "left_rule": left_rule, "right_rule": right_rule})
    result.update(relation="equal", reason="same_domain_and_correspondence",
                  proof={"kind": "complete_piecewise_algebraic_identity", "cells": certificates})
    return result


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
        try:
            _family(left["expression_ast"])
            _family(right["expression_ast"])
        except NotationError:
            return _generic_comparison(left, right, result)
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
                if (not lv or not rv or sp.simplify(lhs - rhs).is_zero is not False
                        or witness.get("left_value") != lhs or witness.get("right_value") != rhs):
                    raise NotationError("function_equality.invalid_output_witness")
            else:
                raise NotationError("function_equality.proof_kind_mismatch")
        else:
            if (domains[0] != domains[1] or proof["kind"] not in {
                    "complete_piecewise_polynomial_identity", "complete_piecewise_algebraic_identity"}
                    or result.get("reason") != "same_domain_and_correspondence"):
                raise NotationError("function_equality.identity_domain_mismatch")
            if proof["kind"] == "complete_piecewise_algebraic_identity":
                claimed_domains = []
                if not 1 <= len(proof["cells"]) <= 2 * MAX_SIGN_CUTS + 1:
                    raise NotationError("function_equality.identity_partition_incomplete")
                for claim in proof["cells"]:
                    cell, sample = claim["domain"], claim["sample"]
                    if cell is sp.S.EmptySet or cell - domains[0] != sp.S.EmptySet:
                        raise NotationError("function_equality.identity_domain_mismatch")
                    lhs, left_rule = _verified_generic_cell(left, cell, sample, claim["left_rule"])
                    rhs, right_rule = _verified_generic_cell(right, cell, sample, claim["right_rule"])
                    expected = {"domain": cell, "sample": sample,
                                "left_polynomial": lhs, "right_polynomial": rhs,
                                "left_rule": left_rule, "right_rule": right_rule}
                    if claim != expected or sp.cancel(lhs - rhs) != 0:
                        raise NotationError("function_equality.identity_certificate_mismatch")
                    claimed_domains.append(cell)
                if sp.Union(*claimed_domains) != domains[0]:
                    raise NotationError("function_equality.identity_partition_incomplete")
                return {"status": "verified", "diagnostics": [], "version": VERSION}
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
