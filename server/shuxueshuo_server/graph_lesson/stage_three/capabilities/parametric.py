"""Certified parameter cases for quadratic bounds on fixed rational intervals.

The deciding polynomials have complete exact root lists. Their signs and the
selected extremum are invariant on each resulting open parameter cell; isolated
roots are checked separately. Samples only decide a sign after that certificate.
This module does not import the independent original-problem verifier.
"""

from copy import deepcopy
from functools import cmp_to_key, lru_cache
from itertools import combinations, pairwise

import sympy as sp

from ....problem_understanding.notation_semantics import bounded_expand
from . import CapabilityGap, LocalCheckFailed, polynomial, result
from .cases import _rational_poly, _real_roots, exact_set_equal
from .ranges import _sign, interval_domain


def _compare(left, right):
    if left == right:
        return 0
    if left is -sp.oo or right is sp.oo:
        return -1
    if left is sp.oo or right is -sp.oo:
        return 1
    return _sign(left - right)


def _sample(left, right):
    if left is -sp.oo:
        return sp.S.Zero if right is sp.oo else sp.floor(right) - 1
    if right is sp.oo:
        return sp.ceiling(left) + 1
    scale = 1
    for _ in range(256):
        sample = (sp.floor(left * scale) + 1) / scale
        if _compare(left, sample) < 0 and _compare(sample, right) < 0:
            return sample
        scale *= 2
    raise CapabilityGap("parameter_cell_sample_unknown")


def _partition_polynomials(expressions, parameter):
    roots, records = [], []
    for name, expression in expressions:
        poly = _rational_poly(bounded_expand(expression), parameter)
        values = [] if poly.is_zero or poly.degree() <= 0 else _real_roots(poly)
        roots.extend(values)
        records.append({"id": name, "polynomial": poly.as_expr(), "roots": values,
                        "identically_zero": bool(poly.is_zero),
                        "root_count": len(values), "complete": True})
    ordered = []
    for root in sorted(roots, key=cmp_to_key(_compare)):
        if not ordered or _compare(root, ordered[-1]):
            ordered.append(root)
    cells = []
    for index, (left, right) in enumerate(pairwise([-sp.oo, *ordered, sp.oo])):
        cells.append({"domain": sp.Interval.open(left, right), "value": None,
                      "sample": _sample(left, right)})
        if index < len(ordered):
            value = ordered[index]
            cells.append({"domain": sp.FiniteSet(value), "value": value, "sample": value})
    for cell in cells:
        cell["signs"] = {row["id"]: _sign(row["polynomial"].subs(parameter, cell["sample"]))
                         for row in records}
    return cells, records


def _input(expression, variable, parameter, domain, policy):
    interval_domain(domain)
    if variable == parameter or expression.free_symbols - {variable, parameter}:
        raise CapabilityGap("single_parameter_quadratic_required")
    if any(point not in (-sp.oo, sp.oo) and point.is_Rational is not True
           for point in (domain.start, domain.end)):
        raise CapabilityGap("rational_interval_endpoints_required")
    if policy.get("bound") not in ("inf", "sup"):
        raise CapabilityGap("extremum_bound_required")
    poly = polynomial(expression, variable)
    for coefficient in poly.all_coeffs():
        _rational_poly(coefficient, parameter)
    return poly


def _cell_bound(expression, variable, parameter, domain, bound, cell):
    expression = (expression if cell["value"] is None else
                  sp.simplify(expression.subs(parameter, cell["value"])))
    poly = polynomial(expression, variable)
    a, b, c = (poly.nth(index) for index in (2, 1, 0))
    sample = cell["sample"]
    a_sign, b_sign = (_sign(value.subs(parameter, sample)) for value in (a, b))
    kind = "quadratic" if a_sign else "linear" if b_sign else "constant"
    candidates = []
    if kind == "constant":
        candidates.append({"value": c, "point": _sample(domain.start, domain.end),
                           "attained": True, "location": "constant"})
    else:
        for location, point, attained in (("left_endpoint", domain.start, not domain.left_open),
                                           ("right_endpoint", domain.end, not domain.right_open)):
            if point in (-sp.oo, sp.oo):
                sign = a_sign or (b_sign if point is sp.oo else -b_sign)
                value = sp.oo if sign > 0 else -sp.oo
            else:
                value = bounded_expand(expression.subs(variable, point))
            candidates.append({"value": value, "point": point,
                               "attained": attained, "location": location})
        if kind == "quadratic":
            vertex = sp.cancel(-b / (2*a))
            sample_vertex = sp.simplify(vertex.subs(parameter, sample))
            contained = domain.contains(sample_vertex)
            if contained is not sp.true and contained is not sp.false:
                raise CapabilityGap("parameter_vertex_membership_unknown")
            if contained is sp.true:
                candidates.append({"value": sp.cancel(c - b*b / (4*a)), "point": vertex,
                                   "attained": True, "location": "vertex"})
    evaluated = [sp.simplify(row["value"].subs(parameter, sample)) for row in candidates]
    extreme = (min if bound == "inf" else max)(evaluated, key=cmp_to_key(_compare))
    ties = [row for row, value in zip(candidates, evaluated, strict=True)
            if _compare(value, extreme) == 0]
    selected = next((row for row in ties if row["attained"]), ties[0])
    attained = any(row["attained"] for row in ties)
    bounds = {"bound": bound, bound: selected["value"], bound + "_attained": attained,
              "candidates": [{"value": selected["value"], "point": selected["point"],
                              "attained": attained, "location": selected["location"]}]}
    return {"kind": kind, "expression": expression,
            "numeric": not bool(expression.free_symbols - {variable}), "range": bounds,
            "coefficient": a, "vertex": sp.cancel(-b / (2*a)) if a_sign else None,
            "candidates": candidates}


def _singleton_value(case):
    domain = case["domain"]
    return next(iter(domain)) if isinstance(domain, sp.FiniteSet) and len(domain) == 1 else None


def _same_value(left, right):
    if left.has(sp.nan, sp.zoo) or right.has(sp.nan, sp.zoo):
        return False
    if left in (-sp.oo, sp.oo) or right in (-sp.oo, sp.oo):
        return left == right
    return sp.cancel(left - right) == 0


def _same_bound(left, right, parameter):
    if left["kind"] != right["kind"]:
        return False
    a, b = left["range"], right["range"]
    key = a["bound"]
    if b["bound"] != key or a[key + "_attained"] != b[key + "_attained"]:
        return False
    first, second = a["candidates"][0], b["candidates"][0]
    if first["location"] != second["location"]:
        return False
    values = (a[key], b[key], first["point"], second["point"])
    left_point, right_point = _singleton_value(left), _singleton_value(right)
    if (left_point is None) != (right_point is None):
        # A critical point was evaluated independently. Rejoin it only when
        # the adjacent formula has the same bound and extremum location there.
        point = right_point if left_point is None else left_point
        values = tuple(value.subs(parameter, point) for value in values)
        if any(value.is_extended_real is not True for value in values):
            return False
    return _same_value(values[0], values[1]) and _same_value(values[2], values[3])


def _partition(expression, variable, parameter, domain, policy):
    poly = _input(expression, variable, parameter, domain, policy)
    sources = [("leading", poly.nth(2)), ("slope", poly.nth(1))]
    finite = [point for point in (domain.start, domain.end) if point not in (-sp.oo, sp.oo)]
    for index, point in enumerate(finite):
        sources.append((f"axis_boundary_{index}", 2*poly.nth(2)*point + poly.nth(1)))
    if len(finite) == 2:
        sources.append(("endpoint_order", expression.subs(variable, finite[0]) -
                        expression.subs(variable, finite[1])))
    cells, critical = _partition_polynomials(sources, parameter)
    groups = []
    for cell in cells:
        selected = _cell_bound(expression, variable, parameter, domain, policy["bound"], cell)
        cell["candidates"] = selected.pop("candidates")
        cell["range"] = deepcopy(selected["range"])
        item = {**selected, "domain": cell["domain"], "value": cell["value"], "cells": [cell]}
        if groups and _same_bound(groups[-1], item, parameter):
            prior = groups[-1]
            if _singleton_value(prior) is not None and _singleton_value(item) is None:
                # Keep the formula certified on the open cell, never extend a
                # substituted point value over a nontrivial parameter range.
                prior["range"] = deepcopy(item["range"])
            prior["domain"] = sp.Union(prior["domain"], item["domain"])
            prior["value"] = None
            prior["expression"] = expression
            prior["numeric"] = not bool(expression.free_symbols - {variable})
            prior["coefficient"] = poly.nth(2)
            prior["vertex"] = sp.cancel(-poly.nth(1) / (2*poly.nth(2))) if prior["kind"] == "quadratic" else None
            prior["cells"].extend(item["cells"])
        else:
            groups.append(item)
    for index, case in enumerate(groups):
        case.update(id=f"interval-case-{index + 1}", condition=case["domain"].as_relational(parameter),
                    parameter=parameter, mode="parametric", critical_polynomials=critical)
    return groups, critical


@lru_cache(maxsize=32)
def _session_partition(expression, variable, parameter, domain, policy_key):
    """Keep derived certificates private to this mathematical worker.

    A policy is a flat scalar mapping produced by select_quantifier_policy;
    retain all its fields in the key, not only the requested bound. Exceptions
    are not cached. A restored route in a new worker computes a fresh partition.
    """
    return _partition(expression, variable, parameter, domain, dict(policy_key))


def _partition_snapshot(expression, variable, parameter, domain, policy):
    # Incoming cases never form part of the cache. No public result may share
    # mutable case or evidence containers with these computed certificates.
    key = tuple(sorted(policy.items()))
    return deepcopy(_session_partition(expression, variable, parameter, domain, key))


def partition_interval_cases(expression, variable, parameter, domain, policy):
    cases, critical = _partition_snapshot(expression, variable, parameter, domain, policy)
    return result({"cases": cases, "critical_polynomials": critical}, ["interval_case_partition"], [
        {"kind": "complete_decision_roots", "passed": True, "polynomials": critical},
        {"kind": "complete_disjoint_interval_cases", "passed": True,
         "case_domains": [case["domain"] for case in cases],
         "reason": "Complete roots fix coefficient signs, axis position and endpoint order on every open cell."},
    ])


def parametric_interval_extremum(expression, variable, parameter, domain, policy, case):
    cases, critical = _partition_snapshot(expression, variable, parameter, domain, policy)
    expected = next((row for row in cases if row["id"] == case["id"]), None)
    if expected is None or expected != case:
        raise LocalCheckFailed("parametric_case_certificate_mismatch")
    return result({"range": deepcopy(expected["range"]), "coefficient": expected["coefficient"],
                   "vertex": expected["vertex"], "case_kind": expected["kind"], "case_domain": expected["domain"]},
                  ["interval_extrema"], [
        {"kind": "complete_decision_roots", "passed": True, "polynomials": critical},
        {"kind": "invariant_case_bound", "passed": True, "condition": expected["condition"],
         "cells": expected["cells"], "range": expected["range"],
         "reason": "All critical points and endpoint limits are compared on the exact invariant cells."},
    ])


def _rational_relation_set(condition, variable):
    if condition is sp.true or condition is sp.false:
        return (sp.S.Reals if condition is sp.true else sp.S.EmptySet), []
    if isinstance(condition, (sp.And, sp.Or)):
        children = [_rational_relation_set(child, variable) for child in condition.args]
        operation = sp.Intersection if isinstance(condition, sp.And) else sp.Union
        return operation(*(value for value, _ in children)), [check for _, checks in children for check in checks]
    if isinstance(condition, sp.Contains):
        member, domain = condition.args
        if member != variable or not isinstance(domain, sp.Set) or domain.free_symbols:
            raise CapabilityGap("single_parameter_membership_required")
        return domain, [{"kind": "parameter_membership", "passed": True, "domain": domain}]
    if getattr(condition, "rel_op", None) not in ("<", "<=", ">", ">=", "==", "!="):
        raise CapabilityGap("parameter_condition_required")
    # Case domains may have algebraic endpoints even though the polynomials
    # that produced them have rational coefficients. Reading an explicit bound
    # does not require solving a polynomial over an algebraic coefficient field.
    if condition.lhs == variable or condition.rhs == variable:
        endpoint = condition.rhs if condition.lhs == variable else condition.lhs
        operator = condition.rel_op
        if condition.rhs == variable:
            operator = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}[operator]
        if not endpoint.free_symbols and endpoint.is_real is True and endpoint.is_algebraic is True:
            domains = {"<": sp.Interval.open(-sp.oo, endpoint), "<=": sp.Interval(-sp.oo, endpoint),
                       ">": sp.Interval.open(endpoint, sp.oo), ">=": sp.Interval(endpoint, sp.oo),
                       "==": sp.FiniteSet(endpoint), "!=": sp.S.Reals - sp.FiniteSet(endpoint)}
            return domains[operator], [{"kind": "exact_parameter_bound", "passed": True, "condition": condition}]
    expression = sp.together(condition.lhs - condition.rhs)
    if not expression.free_symbols:
        sign = _sign(expression)
        holds = {"<": sign < 0, "<=": sign <= 0, ">": sign > 0, ">=": sign >= 0,
                 "==": sign == 0, "!=": sign != 0}[condition.rel_op]
        return (sp.S.Reals if holds else sp.S.EmptySet), [
            {"kind": "exact_constant_condition", "passed": True, "value": expression,
             "sign": sign, "condition": condition, "holds": holds},
        ]
    numerator, denominator = sp.fraction(expression)
    cells, critical = _partition_polynomials([("numerator", numerator), ("denominator", denominator)], variable)
    accepted, checks = [], [{"kind": "complete_rational_condition_roots", "passed": True,
                             "condition": condition, "polynomials": critical}]
    for cell in cells:
        signs = cell["signs"]
        sign = signs["numerator"] * signs["denominator"]
        holds = signs["denominator"] != 0 and {
            "<": sign < 0, "<=": sign <= 0, ">": sign > 0, ">=": sign >= 0,
            "==": sign == 0, "!=": sign != 0,
        }[condition.rel_op]
        if holds:
            accepted.append(cell["domain"])
        checks.append({"kind": "rational_condition_cell", "passed": True, **cell, "holds": holds})
    return sp.Union(*accepted), checks


def solve_interval_conditions(conditions, combiner, variable, case_domain):
    if not conditions or combiner not in ("all", "any"):
        raise CapabilityGap("condition_combination_required")
    solutions, checks = [], []
    for condition in conditions:
        solution, evidence = _rational_relation_set(condition, variable)
        solutions.append(solution)
        checks.append({"kind": "interval_case_condition_solution", "passed": True,
                       "condition": condition, "solution": solution, "evidence": evidence})
    solution = (sp.Intersection if combiner == "all" else sp.Union)(*solutions).intersect(case_domain)
    checks.append({"kind": "same_case_intersection", "passed": True,
                   "case_domain": case_domain, "condition_sets": solutions, "combiner": combiner})
    return result({"solution": solution, "solutions": solutions}, ["interval_condition_sets"], checks)


def merge_interval_cases(cases, results):
    if not cases or len(cases) != len(results):
        raise LocalCheckFailed("incomplete_case_results")
    identifiers = [case["id"] for case in cases]
    if len(set(identifiers)) != len(cases) or [row["case_id"] for row in results] != identifiers:
        raise LocalCheckFailed("case_result_identity")
    symbols = set().union(*(case["condition"].free_symbols for case in cases))
    if len(symbols) > 1:
        raise CapabilityGap("single_parameter_cases_required")
    parameter = next(iter(symbols), sp.Symbol("_case_parameter", real=True))
    domains = []
    for case in cases:
        expected, _ = _rational_relation_set(case["condition"], parameter)
        if not exact_set_equal(expected, case["domain"]):
            raise LocalCheckFailed("case_condition_domain_mismatch")
        domains.append(case["domain"])
    if not exact_set_equal(sp.Union(*domains), sp.S.Reals):
        raise LocalCheckFailed("incomplete_case_partition")
    if any(not exact_set_equal(left.intersect(right), sp.S.EmptySet)
           for left, right in combinations(domains, 2)):
        raise LocalCheckFailed("overlapping_case_partition")
    solutions, checks = [], [{"kind": "complete_disjoint_cases", "passed": True,
                              "case_ids": identifiers, "domains": domains}]
    for case, record in zip(cases, results, strict=True):
        path = record.get("case_path")
        valid_path = (isinstance(path, list) and
                      ((path and path[-1] == case["id"]) or
                       # The driver omits an unconditional single case from
                       # the path, including when its method has a parent case.
                       (len(cases) == 1 and exact_set_equal(case["domain"], sp.S.Reals))))
        if (record["condition"] != case["condition"] or
                not exact_set_equal(record["domain"], case["domain"]) or
                not valid_path or not record.get("source_refs")):
            raise LocalCheckFailed("case_result_provenance")
        solution = record["outputs"]["solution"]
        if not exact_set_equal(sp.Complement(solution, case["domain"]), sp.S.EmptySet):
            raise LocalCheckFailed("case_solution_outside_domain")
        solutions.append(solution)
        checks.append({"kind": "case_result", "passed": True, "case_id": case["id"],
                       "condition": case["condition"], "domain": case["domain"],
                       "solution": solution, "source_refs": record["source_refs"]})
    return result({"solution": sp.Union(*solutions), "case_solutions": solutions},
                  ["interval_case_union"], checks)
