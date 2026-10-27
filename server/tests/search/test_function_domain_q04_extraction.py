"""The actual Q04 failure, and repair boundaries for its canonical domain goal.

These provider responses are deterministic offline scenarios, not live model
acceptance. The separate retained photo recording covers the real model run.
"""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.extraction import SearchStageOneContract
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.test_public_extraction import CONFIRMED, Responses

FAILURE = Path(__file__).parent / "fixtures/function-domain/q04-failed-20261027"


def read(path):
    return json.loads(path.read_text())


def canonical_candidate():
    candidate = deepcopy(read(FAILURE / "failure.json")["calls"][0]["response"])
    candidate["root"].pop("facts")
    candidate["root"]["goals"] = [
        {"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "m"},
    ]
    return candidate


def run(tmp_path, provider):
    return run_question_image(
        (FAILURE / "question.png").read_bytes(), tmp_path, provider,
        problem_id="q04-source-rules-regression",
    )


def test_actual_failed_responses_reproduce_rejected_deletion_without_expanding_authority(tmp_path):
    failure = read(FAILURE / "failure.json")
    assert sha256((FAILURE / "question.png").read_bytes()).hexdigest() == failure["question_sha256"]
    original = failure["calls"][0]["response"]
    assert original["original_text"].startswith("4.")
    assert not original["public_content"]["scopes"][0]["statement"].startswith("4.")
    provider = Responses(*(call["response"] for call in failure["calls"]))
    result = run(tmp_path, provider)
    assert result["status"] == "workflow.budget_exhausted"
    assert result["source_reviewed"] is False
    assert result["public_candidate"] == original
    workflow = read(tmp_path / "workflow/workflow-result.json")
    for key, value in failure["workflow"].items():
        assert workflow[key] == value
    rejected = [event for event in workflow["events"] if event.get("repair_rejected")]
    assert len(rejected) == 2
    assert all(event["adopted"] is False for event in rejected)
    assert all(event["repair_rejected"][0]["path"] == "/root/definitions/0" for event in rejected)
    # A model's prose suggestion cannot grant deletion under wrong_expression.
    for request in provider.requests[2:]:
        payload = json.loads(request.prompt.user_prefix)
        assert payload["base_candidate"] == original
    assert not list((tmp_path / "candidates").glob("0[34]-adopted.json"))


def test_known_input_range_uses_domain_equality_without_invented_conditions(tmp_path):
    candidate = canonical_candidate()
    provider = Responses(candidate, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["source_reviewed"] is True
    assert result["features_ok"] is True
    assert result["candidate"]["root"] == candidate["root"]
    (goal,) = [row for row in result["features"] if row["feature_id"] == "goal"]
    assert goal["target_ref"] == "/root/goals/0"
    assert goal["value"] == {"kind": "match_domain", "object": "f", "symbol": "m"}
    assert result["reviewed_candidate_revision"] == revision(candidate)
    assert len(provider.requests) == 2
    assert candidate["original_text"].startswith("4.")
    statement = candidate["public_content"]["scopes"][0]["statement"]
    assert not statement.startswith("4.")
    assert "y=" in statement and "f(x)" not in statement
    assert "3/4" not in statement and "3/4" not in candidate["original_text"]
    for request in provider.requests:
        assert request.images[0].content == (FAILURE / "question.png").read_bytes()


def test_domain_goal_and_derived_condition_are_repaired_only_under_separate_findings(tmp_path):
    original = deepcopy(read(FAILURE / "failure.json")["calls"][0]["response"])
    repaired = canonical_candidate()
    review = {"status": "correction_required", "findings": [
        {"kind": "wrong_goal", "path": "/root/goals/0",
         "source_excerpt": "x 的取值范围为 R，则 m 的取值范围",
         "message": "题给定义域，原位改为 match_domain，保留函数定义。"},
        {"kind": "unsupported_addition", "path": "/root/facts/0",
         "source_excerpt": "x 的取值范围为 R",
         "message": "非负恒成立是由定义域推导的解题条件，题面没有直接给出，应删除此项。"},
    ]}
    contract = SearchStageOneContract()
    diagnostics = contract.review_diagnostics(review, original)
    assert contract.repair_diagnostics(original, repaired, diagnostics) == []
    unauthorized = deepcopy(repaired)
    unauthorized["root"].pop("definitions")
    assert any(item["path"] == "/root/definitions/0"
               for item in contract.repair_diagnostics(original, unauthorized, diagnostics))
    provider = Responses(original, review, repaired, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["public_candidate"] == repaired
    assert result["reviewed_candidate_revision"] == revision(repaired)
    assert len(provider.requests) == 4
    assert json.loads(provider.requests[3].prompt.user_prefix)["candidate"] == repaired


def test_wrong_expression_replaces_formula_in_place_and_cannot_delete_it(tmp_path):
    repaired = canonical_candidate()
    original = deepcopy(repaired)
    original["root"]["definitions"][0] = "f(x) = sqrt(m*x^2+4*m*x+2)"
    review = {"status": "correction_required", "findings": [
        {"kind": "wrong_expression", "path": "/root/definitions/0",
         "source_excerpt": "mx^2+4mx+3", "message": "常数项应为 3，原位改正定义。"},
    ]}
    contract = SearchStageOneContract()
    diagnostics = contract.review_diagnostics(review, original)
    assert contract.repair_diagnostics(original, repaired, diagnostics) == []
    deleted = deepcopy(original)
    deleted["root"].pop("definitions")
    assert any(item["path"] == "/root/definitions/0"
               for item in contract.repair_diagnostics(original, deleted, diagnostics))
    provider = Responses(original, review, deleted, repaired, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["public_candidate"] == repaired
    assert result["reviewed_candidate_revision"] == revision(repaired)
    assert len(provider.requests) == 5
    second_repair = json.loads(provider.requests[3].prompt.user_prefix)
    assert second_repair["base_candidate"] == original
    assert second_repair["repair_feedback"][0]["path"] == "/root/definitions/0"
    assert json.loads(provider.requests[4].prompt.user_prefix)["candidate"] == repaired
