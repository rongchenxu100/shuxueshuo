"""Parameter-answer projection with independent cases and adversarial changes."""

from copy import deepcopy
from itertools import product

import pytest

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_normalization import (
    normalize_bound,
)
from shuxueshuo_server.problem_understanding.notation_semantics import compare

pytestmark = pytest.mark.generated_gate


def problem(parameter="p", operation="min", hint=""):
    body = "2*DP+AP" if operation == "min" else "-(2*DP+AP)"
    operator = operation + ("_{" + hint + "}" if hint else "")
    payload = {
        "root": {
            "definitions": [f"Γ:y=x^2+{parameter}*x+q"],
            "facts": [f"{parameter}>0", "A=(-3,0)"],
            "children": [
                {
                    "facts": [
                        f"D=({parameter}+3,y_D)",
                        "D∈Γ",
                        "P=(t,0)",
                        "t>0",
                        f"{operator}({body})=9",
                    ],
                    "goals": [{"kind": "find_value", "expression": parameter}],
                }
            ],
        },
        "match_status": "unmatched",
        "family_id": None,
        "match_reason": "synthetic",
    }
    actual = deepcopy(payload)
    actual["root"]["children"][0]["facts"].insert(-1, f"{body}={operator}({body})")
    return payload, actual


@pytest.mark.parametrize(
    "parameter,operation,hint,reversed",
    product(("p", "h"), ("min", "max"), ("", "P", "t"), (False, True)),
)
def test_parameter_projection_family(parameter, operation, hint, reversed):
    expected, actual = problem(parameter, operation, hint)
    if reversed:
        facts = actual["root"]["children"][0]["facts"]
        lhs, rhs = facts[-2].split("=")
        facts[-2] = rhs + "=" + lhs.replace("2*DP+AP", "AP+DP+DP")
    before = deepcopy(actual)
    result = compare(expected, actual)
    assert result["ok"], result
    assert compare(actual, expected)["ok"]
    assert actual == before  # source output, pointers, and min fact stay intact
    proof = next(
        p for p in result["proofs"] if p["rule"] == "parameter_state_extremum_witness"
    )
    assert proof["premises"] and proof["existence"] == "local_attained_extremum_value"
    assert proof["parameter"][1].endswith(":" + parameter)
    assert proof["witness_coordinate"][-1][1].endswith(":P")
    report = NotationValidator().validate(actual)
    normalized = report.semantic_normalization
    assert (
        normalize_bound(normalized["root"], normalized["objects"])["root"]
        == normalized["root"]
    )


@pytest.mark.parametrize("name,value", [("p", None), ("p", ""), ("P", None), ("P", 1)])
def test_incomplete_owner_table_leaves_state_unproved(monkeypatch, name, value):
    from shuxueshuo_server.problem_understanding import notation_normalization

    original = notation_normalization.parameter_state_witness

    def incomplete(goal, condition, local, inherited, owners, scope, budget):
        changed = {k: v for k, v in owners.items() if not k.endswith(":" + name)}
        if value is not None:
            changed.update({k: value for k in owners if k.endswith(":" + name)})
        return original(goal, condition, local, inherited, changed, scope, budget)

    monkeypatch.setattr(notation_normalization, "parameter_state_witness", incomplete)
    expected, actual = problem()
    report = NotationValidator().validate(actual)
    assert report.ok, report.issues
    assert not any(
        p["rule"] == "parameter_state_extremum_witness"
        for p in report.semantic_normalization["proofs"]
    )
    assert not compare(expected, actual)["ok"]


@pytest.mark.parametrize(
    "mutation",
    [
        "no_minimum",
        "ordinary_value",
        "value_inequality",
        "or_value",
        "quantified_value",
        "parent_value",
        "sibling_value",
        "wrong_body",
        "max_instead",
        "extra_state",
        "state_optimizes_parameter",
        "fact_optimizes_parameter",
        "extra_variable",
        "moving_target",
        "position_target",
        "range_target",
        "equation_target",
        "answer_depends_on_motion",
        "unknown_endpoint",
        "parameter_is_coordinate",
        "not_axis",
        "parameter_value",
        "same_scope_parameter",
    ],
)
def test_unproved_or_meaningful_state_is_never_ignored(mutation):
    expected, actual = problem()
    child = actual["root"]["children"][0]
    goal, facts = child["goals"][0], child["facts"]
    state = facts.pop(-2)
    if mutation == "no_minimum":
        facts.pop()
    elif mutation == "ordinary_value":
        facts[-1] = "2*DP+AP=9"
    elif mutation == "value_inequality":
        facts[-1] = "min(2*DP+AP)<=9"
    elif mutation == "or_value":
        facts[-1] = "min(2*DP+AP)=9 ∨ p=2"
    elif mutation == "quantified_value":
        facts[-1] = "∀z∈ℝ: min(2*DP+AP)=9"
    elif mutation in ("parent_value", "sibling_value"):
        minimum = facts.pop()
        # Keep all point definitions visible; only the minimum's logical scope differs.
        actual["root"]["facts"].extend(facts)
        facts.clear()
        if mutation == "parent_value":
            actual["root"]["facts"].append(minimum)
            facts.append("x(P)>100")
        else:
            actual["root"]["children"].insert(0, {"facts": [minimum]})
    elif mutation == "wrong_body":
        state = "DP+AP=min(DP+AP)"
    elif mutation == "max_instead":
        state = "2*DP+AP=max(2*DP+AP)"
    elif mutation == "extra_state":
        state += " ∧ p>2"
    elif mutation in ("state_optimizes_parameter", "extra_variable"):
        state = state.replace(
            "min(",
            "min_{p}(" if mutation == "state_optimizes_parameter" else "min_{P,D}(",
        )
    elif mutation == "fact_optimizes_parameter":
        facts[-1] = facts[-1].replace("min(", "min_{p}(")
    elif mutation == "moving_target":
        goal["expression"] = "t"
    elif mutation == "position_target":
        goal.update(kind="find_coordinates", object="P")
        goal.pop("expression")
    elif mutation == "range_target":
        goal.update(kind="find_range", symbol="p")
        goal.pop("expression")
    elif mutation == "equation_target":
        goal.update(kind="find_equation", object="Γ")
        goal.pop("expression")
    elif mutation == "answer_depends_on_motion":
        goal["in_terms_of"] = ["t"]
    elif mutation == "unknown_endpoint":
        facts.remove("D∈Γ")
    elif mutation == "parameter_is_coordinate":
        facts[2] = "P=(p,0)"
    elif mutation == "not_axis":
        facts[2] = "P=(t,1)"
    elif mutation == "parameter_value":
        facts[-1] = "min(2*DP+AP)=q"
    elif mutation == "same_scope_parameter":
        facts.extend(actual["root"].pop("definitions"))
        facts.extend(actual["root"].pop("facts"))
    # Compare each otherwise identical pair, so rejection cannot be explained
    # by the mutation itself: the sole difference here is the extra state fact.
    expected = deepcopy(actual)
    facts.append(state)
    result = compare(expected, actual)
    assert not result["ok"], (mutation, result)
    report = NotationValidator().validate(actual)
    if mutation != "extra_state":
        assert not any(
            p["rule"] == "parameter_state_extremum_witness"
            for p in report.semantic_normalization.get("proofs", [])
        )


@pytest.mark.parametrize("placement", ["same_scope", "child"])
def test_parameter_projection_never_erases_state_needed_by_other_goals(placement):
    expected, actual = problem()
    for payload in (expected, actual):
        scope = payload["root"]["children"][0]
        coordinates = {"kind": "find_coordinates", "object": "P"}
        if placement == "same_scope":
            scope["goals"].append(coordinates)
        else:
            scope["children"] = [{"goals": [coordinates]}]
    assert not compare(expected, actual)["ok"]
    report = NotationValidator().validate(actual)
    assert report.ok
    assert not any(
        p["rule"] == "parameter_state_extremum_witness"
        for p in report.semantic_normalization["proofs"]
    )


def test_deleting_value_condition_is_not_hidden_by_witness_projection():
    expected, actual = problem()
    actual["root"]["children"][0]["facts"].pop()
    assert not compare(expected, actual)["ok"]


def test_domain_change_and_sibling_parameter_identity_remain_distinct():
    expected, actual = problem()
    actual["root"]["children"][0]["facts"][3] = "t>=0"
    assert not compare(expected, actual)["ok"]
    expected, actual = problem()
    actual["root"]["children"].append({"facts": ["s=2"]})
    assert not compare(expected, actual)["ok"]
