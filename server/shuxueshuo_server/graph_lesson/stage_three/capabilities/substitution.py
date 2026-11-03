"""Checked affine coordinate changes and transport of interval-range evidence."""

from copy import deepcopy

import sympy as sp
from sympy.calculus.util import continuous_domain

from . import CapabilityGap, LocalCheckFailed, polynomial, result
from .cases import exact_set_equal
from .ranges import (
    _bounds,
    _contains,
    _sign,
    interval_domain,
    nonzero_interval_sign,
    reciprocal_coefficients,
    reciprocal_range,
)


def _equal(left, right):
    return left == right or sp.simplify(left - right) == 0


def _real_symbol(value):
    return isinstance(value, sp.Symbol) and value.is_real is True


def _denominator_bases(expression):
    # Inspect the original tree before cancel/simplify: removable holes are
    # still restrictions of the expression supplied by the caller.
    return sorted({node.base for node in sp.preorder_traversal(expression)
                   if isinstance(node, sp.Pow) and node.exp.is_negative is True},
                  key=sp.default_sort_key)


def _defined_on_interval(expression, variable, domain):
    excluded = sp.S.EmptySet
    for base in _denominator_bases(expression):
        try:
            zeros = sp.solveset(base, variable, domain=sp.S.Reals)
            intersection = sp.Intersection(domain, zeros)
        except (NotImplementedError, ValueError, TypeError) as exc:
            raise CapabilityGap("substitution_definition_domain_unknown") from exc
        if not exact_set_equal(intersection, sp.S.EmptySet):
            raise CapabilityGap("substitution_original_domain_contains_pole")
        excluded = sp.Union(excluded, zeros)
    try:
        continuous = continuous_domain(expression, variable, sp.S.Reals)
        covered = exact_set_equal(sp.Intersection(domain, continuous), domain)
    except (NotImplementedError, ValueError, TypeError) as exc:
        raise CapabilityGap("substitution_definition_domain_unknown") from exc
    if not covered:
        raise CapabilityGap("substitution_expression_not_defined_on_interval")
    return excluded


def _affine_interval(domain, slope, intercept):
    increasing = _sign(slope) > 0
    first = sp.simplify(slope * domain.start + intercept)
    last = sp.simplify(slope * domain.end + intercept)
    return (sp.Interval(first, last, left_open=domain.left_open, right_open=domain.right_open)
            if increasing else
            sp.Interval(last, first, left_open=domain.right_open, right_open=domain.left_open))


def _prepare_substitution(expression, variable, domain, new_variable, forward):
    interval_domain(domain)
    if not _real_symbol(variable) or not _real_symbol(new_variable):
        raise CapabilityGap("substitution_real_symbols_required")
    if not isinstance(expression, sp.Expr) or not isinstance(forward, sp.Expr):
        raise CapabilityGap("substitution_expression_required")
    if (new_variable.name == variable.name or
            new_variable.name in {symbol.name for symbol in expression.free_symbols}):
        raise CapabilityGap("substitution_fresh_variable_required")
    if any(symbol.is_real is not True for symbol in expression.free_symbols):
        raise CapabilityGap("substitution_real_symbols_required")
    if forward == 1 / variable:
        return _prepare_reciprocal(expression, variable, domain, new_variable)
    affine = polynomial(forward, variable, maximum=1)
    slope, intercept = affine.nth(1), affine.nth(0)
    if any(value.free_symbols or value.is_real is not True or value.is_finite is not True
           for value in (slope, intercept)) or slope.is_zero is not False:
        raise CapabilityGap("substitution_nonzero_numeric_affine_required")
    excluded = _defined_on_interval(expression, variable, domain)
    inverse = (new_variable - intercept) / slope
    target_domain = _affine_interval(domain, slope, intercept)
    target_expression = sp.simplify(expression.subs(variable, inverse))
    _defined_on_interval(target_expression, new_variable, target_domain)
    mapping = {
        "original_expression": expression, "original_variable": variable,
        "original_domain": domain, "new_variable": new_variable,
        "forward": forward, "inverse": inverse,
        "expression": target_expression, "domain": target_domain,
        "slope": slope, "intercept": intercept,
    }
    checks = [
        {"kind": "affine_substitution_identity", "passed":
         _equal(target_expression.subs(new_variable, forward), expression),
         "original": expression, "transformed": target_expression},
        {"kind": "affine_inverse_identities", "passed":
         _equal(inverse.subs(new_variable, forward), variable)
         and _equal(forward.subs(variable, inverse), new_variable),
         "forward": forward, "inverse": inverse},
        {"kind": "affine_interval_bijection", "passed": exact_set_equal(
            _affine_interval(target_domain, 1 / slope, -intercept / slope), domain),
         "original_domain": domain, "domain": target_domain,
         "orientation": "increasing" if _sign(slope) > 0 else "decreasing"},
        {"kind": "original_definition_domain_preserved", "passed": True,
         "domain": domain, "excluded_points": excluded},
    ]
    if any(check["passed"] is not True for check in checks):
        raise LocalCheckFailed("substitution_identity_or_bijection_failed", evidence=checks)
    return mapping, checks


def substitution(expression, variable, domain, new_variable, forward):
    """Apply an affine or reciprocal bijection, preserving the exact domain."""
    mapping, checks = _prepare_substitution(expression, variable, domain, new_variable, forward)
    return result({"expression": mapping["expression"], "variable": new_variable,
                   "domain": mapping["domain"], "mapping": mapping},
                  ["substitution"], checks)


def _reciprocal_interval(domain):
    sign = nonzero_interval_sign(domain)
    def inverse(point):
        return sign * sp.oo if point == 0 else 1 / point
    return sp.Interval(inverse(domain.end), inverse(domain.start),
                       left_open=domain.right_open, right_open=domain.left_open)


def _prepare_reciprocal(expression, variable, domain, new_variable):
    target_domain = _reciprocal_interval(domain)
    excluded = _defined_on_interval(expression, variable, domain)
    target = sp.cancel(expression.subs(variable, 1 / new_variable))
    _defined_on_interval(target, new_variable, target_domain)
    mapping = {
        "original_expression": expression, "original_variable": variable,
        "original_domain": domain, "new_variable": new_variable,
        "forward": 1 / variable, "inverse": 1 / new_variable,
        "expression": target, "domain": target_domain,
        "slope": None, "intercept": None, "kind": "reciprocal",
    }
    checks = [
        {"kind": "reciprocal_substitution_identity", "passed":
         _equal(target.subs(new_variable, 1 / variable), expression)},
        {"kind": "reciprocal_interval_bijection", "passed":
         exact_set_equal(_reciprocal_interval(target_domain), domain),
         "original_domain": domain, "domain": target_domain},
        {"kind": "original_definition_domain_preserved", "passed": True,
         "excluded_points": excluded},
    ]
    if any(row["passed"] is not True for row in checks):
        raise LocalCheckFailed("substitution_identity_or_bijection_failed", evidence=checks)
    return mapping, checks


def inspect_reciprocal_quadratic(expression, variable, domain, *, reserved_symbols=()):
    """Recognise A/x²+B/x+C on a nonzero interval; no problem-specific formula."""
    if expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_reciprocal_quadratic_required")
    t = _fresh_variable(expression, variable, domain, reserved_symbols)
    mapping, _ = _prepare_substitution(expression, variable, domain, t, 1 / variable)
    poly = polynomial(mapping["expression"], t)
    if poly.degree() != 2:
        raise CapabilityGap("reciprocal_quadratic_required")
    return {"new_variable": t, "forward": 1 / variable, **{
        key: mapping[key] for key in ("expression", "domain")}, "mapping": mapping}


def _fresh_variable(expression, variable, domain, reserved_symbols):
    names = {symbol.name for symbol in expression.free_symbols | domain.free_symbols | {variable}}
    names.update(str(symbol) for symbol in reserved_symbols)
    for name in ("t", "u", "v"):
        if name not in names:
            return sp.Symbol(name, real=True)
    index = 1
    while f"t_{index}" in names:
        index += 1
    return sp.Symbol(f"t_{index}", real=True)


def inspect_affine_reciprocal(expression, variable, domain, *, reserved_symbols=()):
    """Admit a translated linear denominator yielding A*t+B/t+C exactly.

    This is a pure admission probe. It does not emit successful capability
    executions; actual execution must still call substitution and reciprocal_range.
    """
    if not isinstance(expression, sp.Expr) or expression.free_symbols - {variable}:
        raise CapabilityGap("numeric_affine_reciprocal_required")
    interval_domain(domain)
    new_variable = _fresh_variable(expression, variable, domain, reserved_symbols)
    bases = _denominator_bases(expression)
    # A combined rational expression can expose the same denominator in one
    # fraction. Original-domain validation still uses its untouched tree.
    bases.append(sp.fraction(sp.cancel(expression))[1])
    for denominator in dict.fromkeys(bases):
        try:
            affine = polynomial(denominator, variable, maximum=1)
            if affine.degree() != 1 or affine.nth(0).is_zero is not False:
                continue
            forward = affine.as_expr()
            mapping, _ = _prepare_substitution(expression, variable, domain, new_variable, forward)
            reciprocal_coefficients(mapping["expression"], new_variable)
            reciprocal_range(mapping["expression"], new_variable, mapping["domain"])
        except CapabilityGap:
            continue
        return {"new_variable": new_variable, "forward": forward,
                "denominator": denominator, "expression": mapping["expression"],
                "domain": mapping["domain"], "mapping": mapping}
    raise CapabilityGap("affine_reciprocal_substitution_unavailable")


def _validate_mapping(mapping):
    keys = {"original_expression", "original_variable", "original_domain", "new_variable",
            "forward", "inverse", "expression", "domain", "slope", "intercept"}
    if not isinstance(mapping, dict) or not keys <= mapping.keys():
        raise LocalCheckFailed("substitution_mapping_required")
    expected, checks = _prepare_substitution(
        mapping["original_expression"], mapping["original_variable"], mapping["original_domain"],
        mapping["new_variable"], mapping["forward"],
    )
    for key in ("inverse", "expression", "slope", "intercept"):
        if mapping[key] is None and expected[key] is None:
            continue
        if not isinstance(mapping[key], sp.Expr) or not _equal(mapping[key], expected[key]):
            raise LocalCheckFailed("substitution_mapping_disagrees")
    if not exact_set_equal(mapping["domain"], expected["domain"]):
        raise LocalCheckFailed("substitution_mapping_disagrees")
    return expected, checks


def _numeric_value(value, *, finite=False):
    return (isinstance(value, sp.Expr) and not value.free_symbols
            and value.is_extended_real is True
            and (not finite or value.is_finite is True))


def _endpoint_value(expression, variable, point, domain):
    if domain.contains(point) is sp.true:
        value = sp.simplify(expression.subs(variable, point))
    else:
        direction = "+" if point == domain.start else "-"
        try:
            value = sp.limit(expression, variable, point, dir=direction)
        except (NotImplementedError, ValueError) as exc:
            raise CapabilityGap("substitution_endpoint_limit_unknown") from exc
    if not _numeric_value(value):
        raise CapabilityGap("substitution_real_endpoint_value_required")
    return value


def _point_row(row, mapping, *, endpoint=False):
    if not isinstance(row, dict) or not {"point", "value", "attained"} <= row.keys():
        raise LocalCheckFailed("substitution_point_evidence_required")
    point, value, attained = row["point"], row["value"], row["attained"]
    if not _numeric_value(point, finite=not endpoint) or not _numeric_value(value):
        raise LocalCheckFailed("substitution_real_point_evidence_required")
    domain, source_domain = mapping["domain"], mapping["original_domain"]
    variable, source_variable = mapping["new_variable"], mapping["original_variable"]
    expression, source_expression = mapping["expression"], mapping["original_expression"]
    restored = (_endpoint_value(mapping["inverse"], variable, point, domain) if endpoint
                else sp.simplify(mapping["inverse"].subs(variable, point)))
    roundtrip = (_endpoint_value(mapping["forward"], source_variable, restored, source_domain)
                 if endpoint else mapping["forward"].subs(source_variable, restored))
    if not _equal(roundtrip, point):
        raise LocalCheckFailed("substitution_point_roundtrip_failed")
    expected_attained = _contains(domain, point)
    if type(attained) is not bool or attained is not expected_attained:
        raise LocalCheckFailed("substitution_point_attainment_disagrees")
    if _contains(source_domain, restored) is not expected_attained:
        raise LocalCheckFailed("substitution_original_point_attainment_disagrees")
    if endpoint:
        if point not in (domain.start, domain.end) or restored not in (source_domain.start, source_domain.end):
            raise LocalCheckFailed("substitution_endpoint_coordinate_disagrees")
        transformed_value = _endpoint_value(expression, variable, point, domain)
        source_value = _endpoint_value(source_expression, source_variable, restored, source_domain)
    else:
        if not attained:
            raise LocalCheckFailed("substitution_critical_point_outside_domain")
        transformed_value = sp.simplify(expression.subs(variable, point))
        source_value = sp.simplify(source_expression.subs(source_variable, restored))
        if not _equal(sp.diff(expression, variable).subs(variable, point), sp.S.Zero):
            raise LocalCheckFailed("substitution_critical_point_not_stationary")
    if not _equal(value, transformed_value) or not _equal(value, source_value):
        raise LocalCheckFailed("substitution_point_value_disagrees")
    return {**deepcopy(row), "point": restored, "transformed_point": point}


def _restore_turn(turn, mapping, critical_points):
    if turn is None:
        return None
    if not isinstance(turn, dict) or not {"point", "value", "minimum"} <= turn.keys():
        raise LocalCheckFailed("substitution_turning_point_evidence_required")
    point, value = turn["point"], turn["value"]
    if not _numeric_value(point, finite=True) or not _numeric_value(value, finite=True):
        raise LocalCheckFailed("substitution_turning_point_evidence_required")
    variable, source_variable = mapping["new_variable"], mapping["original_variable"]
    expression, source_expression = mapping["expression"], mapping["original_expression"]
    restored = sp.simplify(mapping["inverse"].subs(variable, point))
    if (not _equal(expression.subs(variable, point), value)
            or not _equal(source_expression.subs(source_variable, restored), value)
            or not _equal(sp.diff(expression, variable).subs(variable, point), sp.S.Zero)
            or not _equal(mapping["forward"].subs(source_variable, restored), point)):
        raise LocalCheckFailed("substitution_turning_point_disagrees")
    curvature = _sign(sp.diff(expression, variable, 2).subs(variable, point))
    if not curvature or type(turn["minimum"]) is not bool or turn["minimum"] is not (curvature > 0):
        raise LocalCheckFailed("substitution_turning_point_direction_disagrees")
    attained = _contains(mapping["domain"], point)
    if _contains(mapping["original_domain"], restored) is not attained:
        raise LocalCheckFailed("substitution_turning_point_attainment_disagrees")
    if "attained" in turn and turn["attained"] is not attained:
        raise LocalCheckFailed("substitution_turning_point_attainment_disagrees")
    if attained and not any(_equal(row["point"], point) for row in critical_points):
        raise LocalCheckFailed("substitution_turning_point_missing_from_critical_points")
    return {**deepcopy(turn), "point": restored, "transformed_point": point, "attained": attained}


def _complete_reciprocal_stationary_evidence(mapping, critical_points, turning_point):
    """Check completeness from the quadratic derivative numerator, not a range solve."""
    variable, domain = mapping["new_variable"], mapping["domain"]
    if mapping.get("kind") == "reciprocal":
        poly = polynomial(mapping["expression"], variable)
        vertex = -poly.nth(1) / (2 * poly.nth(2))
        expected = [vertex] if _contains(domain, vertex) else []
        actual = [row["point"] for row in critical_points]
        if actual != expected or turning_point is not None:
            raise LocalCheckFailed("substitution_incomplete_critical_point_evidence")
        return {"kind": "complete_quadratic_stationary_evidence", "passed": True,
                "points": actual, "domain": domain}
    a, _, b = reciprocal_coefficients(mapping["expression"], variable)
    domain_sign = nonzero_interval_sign(domain)
    expected_turn = None
    if a != 0 and _sign(b / a) > 0:
        expected_turn = domain_sign * sp.sqrt(b / a)
    expected_points = ([expected_turn] if expected_turn is not None and _contains(domain, expected_turn)
                       else [])
    actual_points = [row["point"] for row in critical_points]
    if len(actual_points) != len(expected_points) or any(
            not any(_equal(point, expected) for expected in expected_points) for point in actual_points):
        raise LocalCheckFailed("substitution_incomplete_critical_point_evidence")
    if ((expected_turn is None) != (turning_point is None)
            or (expected_turn is not None and not _equal(turning_point["point"], expected_turn))):
        raise LocalCheckFailed("substitution_incomplete_turning_point_evidence")
    return {"kind": "complete_reciprocal_stationary_evidence", "passed": True,
            "derivative_numerator": a * variable**2 - b,
            "domain": domain, "points": actual_points, "turning_point": expected_turn}


def restore_substitution_range(mapping, range, critical_points, endpoint_values, turning_point):
    """Transport already computed extrema evidence; do not solve the range again."""
    mapping, checks = _validate_mapping(mapping)
    if (not isinstance(critical_points, (list, tuple))
            or not isinstance(endpoint_values, (list, tuple)) or len(endpoint_values) != 2):
        raise LocalCheckFailed("substitution_complete_endpoint_evidence_required")
    if {row.get("point") for row in endpoint_values if isinstance(row, dict)} != {
            mapping["domain"].start, mapping["domain"].end}:
        raise LocalCheckFailed("substitution_complete_endpoint_evidence_required")
    points = [_point_row(row, mapping) for row in critical_points]
    endpoints = [_point_row(row, mapping, endpoint=True) for row in endpoint_values]
    # Returning original-coordinate order is essential for negative affine maps.
    if endpoints[0]["point"] != mapping["original_domain"].start:
        endpoints.reverse()
    turn = _restore_turn(turning_point, mapping, critical_points)
    checks.append(_complete_reciprocal_stationary_evidence(mapping, critical_points, turning_point))
    candidates = [*endpoint_values, *critical_points]
    expected = _bounds(candidates)
    if not isinstance(range, dict) or not expected.keys() <= range.keys():
        raise LocalCheckFailed("substitution_range_evidence_required")
    if (any(type(range[key]) is not bool or range[key] is not expected[key]
            for key in ("inf_attained", "sup_attained"))
            or any(not _numeric_value(range[key]) or not _equal(range[key], expected[key])
                   for key in ("inf", "sup"))
            or not exact_set_equal(range["set"], expected["set"])):
        raise LocalCheckFailed("substitution_range_evidence_disagrees")
    checks.extend([
        {"kind": "substitution_coordinates_and_values_restored", "passed": True,
         "critical_points": points, "endpoint_values": endpoints, "turning_point": turn},
        {"kind": "substitution_attainment_preserved", "passed": True,
         "original_domain": mapping["original_domain"], "transformed_domain": mapping["domain"]},
        {"kind": "substitution_range_bounds_preserved", "passed": True, "range": range},
    ])
    return result({"range": deepcopy(range), "critical_points": points, "endpoint_values": endpoints,
                   "turning_point": turn, "expression": mapping["original_expression"],
                   "variable": mapping["original_variable"], "domain": mapping["original_domain"]},
                  ["substitution_range_restore"], checks)
