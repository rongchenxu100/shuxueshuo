"""Conditions belong to scopes, goals only describe what to find."""

import json
from copy import deepcopy

import pytest
from test_math_notation_workflow import OK, Sequence, candidate, finding, run

from shuxueshuo_server.problem_understanding.batch_smoke import CASES, NOTATION_FIXTURES
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_contract import (
    TEMPLATE_FILES,
    schema,
)
from shuxueshuo_server.problem_understanding.notation_semantics import compare
from shuxueshuo_server.problem_understanding.repair_guard import guard_changes
from shuxueshuo_server.problem_understanding.review_contract import (
    EXAMPLES_PATH,
    FILES,
    request_for,
)


def scoped():
    return candidate(
        ["P=(t,t^2)"],
        goals=[{"kind": "find_minimum", "expression": "y(P)"}],
        children=[
            {
                "facts": ["y(P)=min(y(P))"],
                "goals": [{"kind": "find_coordinates", "object": "P"}],
            }
        ],
    )


@pytest.mark.parametrize(
    "variant", schema()["$defs"]["Scope"]["properties"]["goals"]["items"]["oneOf"]
)
@pytest.mark.parametrize("value", [None, "", "t=1"])
def test_removed_goal_field_is_rejected_for_every_kind_and_value(variant, value):
    target = next(
        k for k in ("expression", "object", "symbol") if k in variant["required"]
    )
    goal = {"kind": variant["properties"]["kind"]["const"], target: "t", "at": value}
    original = candidate(["t>0"], goals=[goal])
    report = NotationValidator().validate(original)
    assert not report.ok and not report.normalized and not report.semantic
    assert all(issue["code"] == "schema.invalid" for issue in report.issues)
    assert original["root"]["goals"][0]["at"] == value


def test_state_fact_is_bound_to_child_while_minimum_goal_uses_parent_scope():
    source = scoped()
    report = NotationValidator().validate(source)
    assert report.ok, report.issues
    parent, child = report.semantic, report.semantic["children"][0]
    assert len(parent["facts"]) == 1 and len(child["facts"]) == 1
    assert parent["goals"][0]["kind"] == "find_minimum"
    assert child["goals"][0]["target"][1] == parent["goals"][0]["target"][2][1]
    assert compare(source, source)["ok"]


@pytest.mark.parametrize(
    "change", ["remove", "promote", "sibling", "value_only", "maximum", "target"]
)
def test_state_and_scope_changes_are_semantic_differences(change):
    source, changed = scoped(), scoped()
    child = changed["root"]["children"][0]
    if change == "remove":
        child["facts"].clear()
    elif change == "promote":
        changed["root"]["facts"].append(child["facts"].pop())
    elif change == "sibling":
        changed["root"]["children"].append({"facts": child.pop("facts")})
    elif change == "value_only":
        child["facts"] = ["min(y(P))=0"]
    elif change == "maximum":
        child["facts"] = ["y(P)=max(y(P))"]
    else:
        child["goals"][0] = {"kind": "find_value", "expression": "t^2"}
    assert NotationValidator().validate(changed).ok
    assert not compare(source, changed)["ok"]
    assert not guard_changes(source, changed, [])["ok"]


def test_missing_state_is_repaired_as_fact_then_reviewed_again(tmp_path):
    complete = scoped()
    incomplete = deepcopy(complete)
    incomplete["root"]["children"][0]["facts"] = []
    review = finding("/root/children/0/facts", message="漏掉取得最小值时的状态")
    review["findings"][0]["source_excerpt"] = "取得最小值时P的坐标"
    model = Sequence(incomplete, review, complete, OK)
    result = run(tmp_path, model)
    assert result["source_reviewed"] and result["candidate"] == complete
    assert result["content_calls"] == result["review_calls"] == 2
    payload = json.loads(model.requests[2].prompt.user_prefix)
    assert payload["allowed_changes"] == [
        {
            "path": "/root/children/0/facts",
            "mode": "append",
            "reason": "missing_condition",
        },
        {
            "path": "/root/uncertainties",
            "mode": "append",
            "reason": "source_stop_diagnostic",
        },
    ]
    for request in model.requests:
        assert '"at"' not in request.prompt.user_prefix
    review_request = model.requests[-1]
    repair_request = request_for(model.requests[0], "repair", complete, [])
    for request in (review_request, repair_request):
        payload = json.loads(request.prompt.user_prefix)
        assert "attained_extremum" in json.dumps(payload["math_expression_catalog"])
    assert (
        "at"
        not in json.loads(review_request.prompt.user_prefix)["candidate_contract"][
            "goal_fields"
        ]
    )


@pytest.mark.parametrize("case", CASES)
def test_all_seven_authored_gold_candidates_compile_under_current_contract(case):
    payload = json.loads((NOTATION_FIXTURES / f"{case}.json").read_text())
    assert '"at"' not in json.dumps(payload)
    report = NotationValidator().validate(payload)
    assert report.ok, report.issues
    assert compare(payload, payload)["ok"]


def test_current_model_contract_and_instructions_do_not_offer_removed_field():
    for path in {*TEMPLATE_FILES, *FILES}:
        text = path.read_text()
        assert '"at"' not in text and "goals.at" not in text and "goal_at" not in text


def test_review_examples_accept_local_scope_and_repair_promoted_state(tmp_path):
    examples = {e["id"]: e for e in json.loads(EXAMPLES_PATH.read_text())}
    correct, wrong = examples["local_state_scope"], examples["promoted_state_scope"]
    assert correct["candidate"]["root"] == scoped()["root"]
    assert NotationValidator().validate(wrong["candidate"]).ok
    assert not compare(correct["candidate"], wrong["candidate"])["ok"]
    model = Sequence(
        wrong["candidate"], wrong["review"], correct["candidate"], correct["review"]
    )
    result = run(tmp_path, model)
    assert result["source_reviewed"] and result["candidate"] == correct["candidate"]
    assert result["content_calls"] == result["review_calls"] == 2
    rules = json.loads(model.requests[2].prompt.user_prefix)["allowed_changes"]
    assert rules[0] == {"path": "/root", "mode": "subtree", "reason": "wrong_scope"}
