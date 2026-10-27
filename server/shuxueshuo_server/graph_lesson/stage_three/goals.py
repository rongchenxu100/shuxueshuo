"""Typed goal closure after independent feasibility verification."""

import sympy as sp

from .trajectory import decode_value, encode_value
from .verification import (
    VerificationGap,
    _algebraic_sign,
    _contains_exact,
    _extended_compare,
    _supported_set,
    _sympy_gap_boundary,
    math_value,
)


class GoalClosureMismatch(ValueError):
    """A proposed typed answer contradicts the original goal and feasible set."""


class _InvalidGoalAnswer(VerificationGap):
    """An answer violates its data contract, before mathematical comparison."""


def _exact_math(value):
    try:
        exact = encode_value(value)
    except (TypeError, ValueError) as exc:
        raise VerificationGap("goal_finalize.exact_value_encoding_unsupported") from exc
    return {**math_value(value), "exact": exact}


def _components(feasible_set):
    if feasible_set == sp.S.EmptySet:
        return []
    if isinstance(feasible_set, sp.Union):
        return [part for member in feasible_set.args for part in _components(member)]
    return [feasible_set]


def _choose_bound(values, direction):
    selected = values[0]
    for value in values[1:]:
        comparison = _extended_compare(value, selected)
        if (direction == "lower" and comparison < 0) or (direction == "upper" and comparison > 0):
            selected = value
    return selected


def _component_bound(component, direction):
    if component == sp.S.Reals:
        return -sp.oo if direction == "lower" else sp.oo
    if isinstance(component, sp.Interval):
        return component.start if direction == "lower" else component.end
    if isinstance(component, sp.FiniteSet):
        if any(value in (-sp.oo, sp.oo) for value in component):
            raise VerificationGap("goal_finalize.real_feasible_set_required")
        return _choose_bound(list(component), direction)
    raise VerificationGap("goal_finalize.unsupported_feasible_set")


@_sympy_gap_boundary
def finalize_goal_with_evidence(goal, feasible_set):
    """Close the original goal from a verified finite union of exact real sets.

    Extrema use structural interval/point bounds and exact algebraic comparison;
    no symbolic truth value or numerical approximation decides attainment.
    Range answers retain their existing wire format, including empty sets.
    """
    kind = goal["kind"]
    if kind not in ("find_range", "find_domain", "match_domain", "find_minimum", "find_maximum"):
        raise VerificationGap("goal_finalize.unsupported_kind:" + kind)
    if not isinstance(feasible_set, sp.Set):
        raise TypeError("goal_finalize.expected_set")
    if kind in ("find_range", "find_domain", "match_domain"):
        answer = {"kind": kind, "status": "set", "set": math_value(feasible_set)}
        check_kind = (
            "domain_identity" if kind == "find_domain"
            else "domain_parameter_identity" if kind == "match_domain"
            else "range_identity"
        )
        return answer, {"kind": "goal_closure", "goal_kind": kind, "status": "set",
                        "feasible_set": math_value(feasible_set), "direction": None,
                        "checks": [{"kind": check_kind, "passed": True}]}

    _supported_set(feasible_set)
    components = _components(feasible_set)
    direction = "lower" if kind == "find_minimum" else "upper"
    evidence = {"kind": "goal_closure", "goal_kind": kind,
                "feasible_set": _exact_math(feasible_set), "direction": direction,
                "empty": not components, "bounded": None, "bound": None,
                "member": None, "attained": None,
                "checks": [{"kind": "finite_union_emptiness", "passed": True,
                            "component_count": len(components), "empty": not components}]}
    if not components:
        status = "empty_feasible_set"
        evidence["status"] = status
        return {"kind": kind, "status": status}, evidence

    bounds = [_component_bound(component, direction) for component in components]
    bound = _choose_bound(bounds, direction)
    bounded = bound not in (-sp.oo, sp.oo)
    evidence.update(bounded=bounded, bound=_exact_math(bound))
    evidence["checks"].append({
        "kind": "finite_union_bound", "passed": True, "direction": direction,
        "components": [{"set": _exact_math(component), "bound": _exact_math(value)}
                       for component, value in zip(components, bounds, strict=True)],
        "bound": _exact_math(bound), "bounded": bounded,
    })
    if not bounded:
        expected = -sp.oo if direction == "lower" else sp.oo
        if bound != expected:
            raise VerificationGap("goal_finalize.invalid_infinite_bound")
        status = "unbounded_below" if direction == "lower" else "unbounded_above"
        evidence.update(status=status, member=False, attained=False)
        evidence["checks"].append({"kind": "infinite_bound_not_a_value", "passed": True})
        return {"kind": kind, "status": status}, evidence

    member = _contains_exact(feasible_set, bound)
    if type(member) is not bool:
        raise VerificationGap("goal_finalize.bound_membership_unknown")
    status = "attained" if member else "not_attained"
    evidence.update(status=status, member=member, attained=member)
    evidence["checks"].append({"kind": "finite_bound_membership", "passed": True,
                               "bound": _exact_math(bound), "member": member})
    return {"kind": kind, "status": status,
            "value" if member else "bound": _exact_math(bound)}, evidence


def finalize_goal(goal, feasible_set):
    """Compatibility entry point returning only the typed answer."""
    return finalize_goal_with_evidence(goal, feasible_set)[0]


def _answer_value(answer, field):
    payload = answer.get(field)
    if not isinstance(payload, dict) or "exact" not in payload:
        raise _InvalidGoalAnswer("goal_finalize.exact_answer_required")
    try:
        value = decode_value(payload["exact"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise _InvalidGoalAnswer("goal_finalize.invalid_exact_answer") from exc
    if (not isinstance(value, sp.Expr) or value.free_symbols or value.has(sp.Float)
            or value.is_real is not True or value.is_algebraic is not True):
        raise _InvalidGoalAnswer("goal_finalize.finite_algebraic_answer_required")
    return value


def equivalent_answers(first, second):
    """Compare typed mathematical meaning, never display strings.

    Range answers intentionally keep the legacy display-only set payload. For
    range goals this checks the answer type only: callers MUST separately prove
    equality of the complete exact feasible sets, as route consistency does.
    Extrema also require the feasible-set comparison at that boundary, since
    equal extrema alone do not prove two routes found the same feasible set.
    """
    if not all(isinstance(answer, dict) for answer in (first, second)):
        raise _InvalidGoalAnswer("goal_finalize.answer_object_required")
    kind, status = first.get("kind"), first.get("status")
    if (kind, status) != (second.get("kind"), second.get("status")):
        return False
    if kind in ("find_range", "find_domain", "match_domain") and status == "set":
        if not all(set(answer) == {"kind", "status", "set"}
                   and isinstance(answer["set"], dict) for answer in (first, second)):
            raise _InvalidGoalAnswer("goal_finalize.range_answer_required")
        return True
    if kind not in ("find_minimum", "find_maximum"):
        raise _InvalidGoalAnswer("goal_finalize.unsupported_answer_kind")
    allowed = {"attained", "not_attained", "empty_feasible_set",
               "unbounded_below" if kind == "find_minimum" else "unbounded_above"}
    if status not in allowed:
        raise _InvalidGoalAnswer("goal_finalize.unsupported_answer_status")
    field = "value" if status == "attained" else "bound" if status == "not_attained" else None
    if any(name in answer for answer in (first, second) for name in ("value", "bound") if name != field):
        raise _InvalidGoalAnswer("goal_finalize.unexpected_answer_value")
    expected_fields = {"kind", "status"} | ({field} if field else set())
    if any(set(answer) != expected_fields for answer in (first, second)):
        raise _InvalidGoalAnswer("goal_finalize.invalid_answer_fields")
    if field is None:
        return True
    return _algebraic_sign(_answer_value(first, field) - _answer_value(second, field)) == 0


def verify_goal_answer(goal, feasible_set, answer):
    """Recompute closure from the original goal/set; trust no answer evidence.

    The legacy range answer carries no exact set object, so its expression must
    match the canonical rendering freshly derived from the given exact set.
    Extrema compare the codec values mathematically and ignore display text.
    Invalid answer data is a mismatch; inability to recompute or compare exact
    mathematical values remains a verification capability gap.
    """
    expected, evidence = finalize_goal_with_evidence(goal, feasible_set)
    try:
        matches = equivalent_answers(expected, answer)
    except _InvalidGoalAnswer as exc:
        raise GoalClosureMismatch("goal_finalize.answer_mismatch") from exc
    if not matches:
        raise GoalClosureMismatch("goal_finalize.answer_mismatch")
    if goal["kind"] in ("find_range", "find_domain", "match_domain") and answer["set"].get("expression") != expected["set"]["expression"]:
        raise GoalClosureMismatch("goal_finalize.answer_mismatch")
    evidence["checks"].append({"kind": "goal_answer_matches_feasible_set", "passed": True,
                               "answer_kind": expected["kind"], "answer_status": expected["status"]})
    return evidence
