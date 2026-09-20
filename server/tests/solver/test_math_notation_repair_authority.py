"""Review pointers must never grant replacement of a complete candidate."""

import json
from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator, ValidationError
from test_math_notation_workflow import Sequence, candidate, finding, run

from shuxueshuo_server.problem_understanding.repair_guard import guard_changes
from shuxueshuo_server.problem_understanding.review_contract import (
    review_schema,
    validate_review,
)
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    permissions,
    repair_permissions,
    review_diagnostics,
)

NON_TRANSCRIPTION_KINDS = [
    kind
    for kind in review_schema()["properties"]["findings"]["items"]["properties"]["kind"]["enum"]
    if kind != "wrong_transcription"
]


@pytest.mark.parametrize("kind", ["wrong_expression", "wrong_scope"])
def test_empty_review_path_cannot_authorize_replacing_entire_candidate(kind):
    original = candidate(["t>0"], goals=[{"kind": "find_value", "expression": "t"}])
    proposed = candidate(["s=9"], goals=[{"kind": "find_coordinates", "object": "P"}])
    proposed.update(family_id="invented", match_status="matched", match_reason="rewritten")
    diagnostics = review_diagnostics(finding("", kind), original)
    grants = permissions(original, diagnostics)
    assert not guard_changes(original, proposed, grants)["ok"]
    assert grants == []


@pytest.mark.parametrize("kind", NON_TRANSCRIPTION_KINDS)
@pytest.mark.parametrize("status", ["correction_required", "uncertain"])
def test_review_schema_rejects_empty_pointer_outside_missing_transcription(kind, status):
    response = {**finding("", kind), "status": status}
    assert not Draft202012Validator(review_schema()).is_valid(response)
    with pytest.raises((ValidationError, ValueError)):
        validate_review(json.dumps(response), candidate(["t>0"]))


@pytest.mark.parametrize("path", ["", "/not_a_field", "/root/missing/facts/0", "/root/facts/999"])
def test_authority_does_not_fall_back_to_an_ancestor_for_invalid_review_paths(path):
    original = candidate(["t>0"])
    diagnostics = review_diagnostics(finding(path, "wrong_expression"))
    assert permissions(original, diagnostics) == []


@pytest.mark.parametrize("mode", ["source_edit", "subtree", "replace", "append", "reextract"])
def test_guard_rejects_global_grants_even_if_the_authority_builder_is_bypassed(mode):
    original = candidate(["t>0"])
    guard = guard_changes(original, candidate(["t<0"]), [{"path": "", "mode": mode}])
    assert not guard["ok"]
    assert guard["violations"][0]["path"] == ""
    assert guard["violations"][0]["code"] == "repair.outside_authority"


@pytest.mark.parametrize("path", ["/root", "/root/children/0"])
def test_source_edit_cannot_replace_a_scope_without_math_fields(path):
    original = candidate()
    if path == "/root":
        original["root"] = {"label": "题目"}
        proposed = candidate(["t=9"])
    else:
        original["root"]["children"] = [{"label": "(1)"}]
        proposed = deepcopy(original)
        proposed["root"]["children"][0] = {"facts": ["t=9"]}
    assert not guard_changes(original, proposed, [{"path": path, "mode": "source_edit"}])["ok"]


@pytest.mark.parametrize("kind", ["wrong_expression", "wrong_scope", "wrong_goal", "unsupported_addition"])
def test_invalid_global_review_stops_before_repair_and_retains_candidate(tmp_path, kind):
    original = candidate(["t>0"])
    model = Sequence(original, finding("", kind), candidate(["t<0"]))
    result = run(tmp_path, model)
    assert result["status"] == "review.invalid_response"
    assert result["candidate"] == original
    assert not result["source_reviewed"]
    assert result["semantic_calls"] == 2 and result["content_calls"] == 1
    assert [event["stage"] for event in result["events"]] == ["extract", "review"]
    assert len(model.requests) == 2
    # The same conditional restriction must be present on the model-facing wire.
    wire = json.loads(model.requests[1].prompt.user_prefix)
    assert wire["response_schema"] == model.requests[1].contract_schema == review_schema()
    assert not Draft202012Validator(wire["response_schema"]).is_valid(finding("", kind))


def test_exact_expression_correction_still_has_only_local_authority():
    original = candidate(["t>0", "s=2"])
    review = validate_review(json.dumps(finding("/root/facts/0", "wrong_expression")), original)
    grants = permissions(original, review_diagnostics(review, original))
    corrected = candidate(["t>=0", "s=2"])
    assert guard_changes(original, corrected, grants)["ok"]
    corrected["root"]["facts"][1] = "s=9"
    assert not guard_changes(original, corrected, grants)["ok"]


def test_global_reextract_is_still_allowed_when_no_usable_candidate_exists():
    assert guard_changes(None, candidate(["t>0"]), permissions(None, []))["ok"]


def test_missing_transcription_source_stays_compact_during_diagnostic_enrichment():
    original = candidate(["t>0"], children=[{"facts": ["s=2"]}])
    review = validate_review(json.dumps(finding("", "wrong_transcription")), original)
    diagnostics = review_diagnostics(review, original)
    assert diagnostics[0]["source"] is None
    # Internal callers may provide a diagnostic before its source is enriched.
    del diagnostics[0]["source"]
    allowed = repair_permissions(original, diagnostics)
    assert diagnostics[0]["source"] is None
    assert allowed[0]["path"] == "/original_text"
    assert diagnostics[0]["path"] == ""
    corrected = {**deepcopy(original), "original_text": "已知t>0，第一问有s=2。"}
    assert guard_changes(original, corrected, allowed)["ok"]
    corrected["root"]["facts"] = ["t<0"]
    assert not guard_changes(original, corrected, allowed)["ok"]
