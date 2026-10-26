"""Exact quantifier/attainment policies and checked endpoint condition sets."""

import sympy as sp

from . import CapabilityGap, relation, residual, result


def select_quantifier_policy(quantifier, operator, domain):
    if operator not in (">", ">=", "<", "<="):
        raise CapabilityGap("unsupported_comparison")
    if quantifier not in ("∀", "∃"):
        raise CapabilityGap("unsupported_quantifier")
    greater = operator in (">", ">=")
    policy = {
        "bound": "sup" if greater == (quantifier == "∀") else "inf",
        "strict": operator in (">", "<"),
        "quantifier": quantifier,
        "operator": operator,
    }
    if domain == sp.S.EmptySet:
        policy["empty"] = True
    return result({"policy": policy},
                  ["universal" if quantifier == "∀" else "existential", "quantified_bound"],
                  [{"kind": "quantifier_bound_policy", "passed": True, "policy": policy}])


def _condition(policy, value, attained, parameter_expression):
    if type(attained) is not bool:
        raise CapabilityGap("bound_attainment_required")
    greater = policy["operator"] in (">", ">=")
    if value in (-sp.oo, sp.oo):
        truth = (value is -sp.oo) == greater
        return relation(sp.S.One if truth else -sp.S.One, ">=")
    # A universal strict condition may admit the unattained bound. An
    # existential weak condition cannot use it as a witness.
    strict = (policy["strict"] and attained if policy["quantifier"] == "∀"
              else policy["strict"] or not attained)
    operator = (">" if strict else ">=") if greater else ("<" if strict else "<=")
    return relation(parameter_expression, operator, value)


def apply_quantifier_policy(policy, range, parameter_expression):
    quantifier = policy["quantifier"]
    if quantifier not in ("∀", "∃"):
        raise CapabilityGap("unsupported_quantifier")
    expected = "sup" if (policy["operator"] in (">", ">=")) == (quantifier == "∀") else "inf"
    if policy.get("bound", expected) != expected:
        raise CapabilityGap("inconsistent_quantifier_policy")
    if policy.get("empty"):
        conditions = [relation(sp.S.One if quantifier == "∀" else -sp.S.One, ">=")]
        evidence = [{"kind": "empty_domain_quantifier", "passed": True, "quantifier": quantifier}]
    else:
        if "candidates" in range:
            if range.get("bound") != expected or not range["candidates"]:
                raise CapabilityGap("endpoint_bound_mismatch")
            candidates = range["candidates"]
        else:
            candidates = [{"value": range[expected], "attained": range[expected + "_attained"]}]
        conditions = [_condition(policy, row["value"], row["attained"], parameter_expression)
                      for row in candidates]
        evidence = [{"kind": "quantified_bound_attainment", "passed": True,
                     "policy": policy, "candidates": candidates, "conditions": conditions}]
    return result(
        {"condition": conditions[0] if len(conditions) == 1 else None,
         "conditions": conditions, "combiner": "all" if quantifier == "∀" else "any"},
        ["quantified_bound"], evidence,
    )


def solve_conditions(conditions, combiner, variable, purpose="quantified"):
    if purpose not in ("quantified", "domain"):
        raise CapabilityGap("condition_purpose_unknown")
    from .cases import _rational_poly, _relation_set

    if not conditions or combiner not in ("all", "any"):
        raise CapabilityGap("condition_combination_required")
    solutions, checks = [], []
    operations = ["domain_condition_sets" if purpose == "domain" else "quantified_condition_sets"]
    for condition in conditions:
        solution, evidence = _relation_set(condition, variable)
        solutions.append(solution)
        checks.append({"kind": "domain_condition_solution" if purpose == "domain" else "endpoint_condition_solution", "passed": True,
                       "condition": condition, "solution": solution, "evidence": evidence})
        if (
            purpose == "domain"
            and getattr(condition, "rel_op", None) in (">", ">=", "<", "<=")
            and _rational_poly(residual(condition), variable).degree() == 2
            and "quadratic_signs" not in operations
        ):
            # Lights quadratic-inequality#signs via basis-operations.
            operations.append("quadratic_signs")
    solution = (sp.Intersection if combiner == "all" else sp.Union)(*solutions)
    checks.append({"kind": "domain_condition_combination" if purpose == "domain" else "quantified_condition_combination", "passed": True,
                   "combiner": combiner, "condition_sets": solutions})
    return result({"solution": solution, "solutions": solutions}, operations, checks)
