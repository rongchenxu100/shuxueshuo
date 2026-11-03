"""The existing extraction/review budget binds the complete public candidate."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from shuxueshuo_server.graph_lesson.stage_one.extraction import (
    GraphStageOneContract,
    validate_candidate,
)
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.extraction import (
    SearchStageOneContract,
    review_schema,
)
from shuxueshuo_server.search.identity import IdentityUnavailable, build_identity
from shuxueshuo_server.search.stage_one import run_question_image
from shuxueshuo_server.search.text_extraction import text_schema
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider,
)
from tests.search.test_identity import CORPUS, public_candidate

CONFIRMED = {"status": "confirmed", "findings": []}


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def prepare_request(self, request):
        return DeepSeekMultimodalExtractionProvider(
            api_key="offline", base_url="https://api.deepseek.com", model="deepseek-flash",
            request_timeout=300, max_output_tokens=16384,
        ).prepare_request(request)

    def complete(self, request):
        self.requests.append(request)
        assert self.responses, "unexpected extra model call"
        text = json.dumps(self.responses.pop(0), ensure_ascii=False)
        return SimpleNamespace(text=text, finish_reason="stop", raw_payload={
            "choices": [{"message": {"content": text}, "finish_reason": "stop"}]},
            provider_attempts=({"attempt": 1},), metadata_payload=lambda: {"model": "offline"})


def run(tmp_path, provider):
    return run_question_image((CORPUS / "q01/source.png").read_bytes(), tmp_path / "run", provider, problem_id="private-search")


def correction(path):
    return {"status": "correction_required", "findings": [{"path": path, "kind": "wrong_public_content",
            "source_excerpt": "原图完整题干", "message": "公开题干漏字，恢复原图文字。"}]}


def test_two_calls_review_the_full_candidate_and_preserve_math_projection(tmp_path):
    candidate = public_candidate()
    provider = Responses(candidate, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert len(provider.requests) == 2
    assert result["public_candidate"] == candidate
    assert result["reviewed_candidate_revision"] == revision(candidate)
    assert "public_content" not in result["candidate"]
    assert validate_candidate(result["candidate"])["contract_valid"]
    assert build_identity(result)["statement"]
    reviewed = json.loads(provider.requests[1].prompt.user_prefix)
    assert reviewed["candidate"] == candidate
    assert reviewed["code_validation"]["candidate_revision"] == revision(candidate)
    assert reviewed["response_schema"] == review_schema()


def test_public_repair_requires_fresh_full_review(tmp_path):
    original = public_candidate()
    repaired = deepcopy(original)
    path = "/public_content/scopes/0/statement"
    original["public_content"]["scopes"][0]["statement"] = "求范围。"
    provider = Responses(original, correction(path), repaired, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert len(provider.requests) == 4
    assert result["reviewed_candidate_revision"] == revision(repaired)
    assert result["public_candidate"] == repaired
    assert json.loads(provider.requests[2].prompt.user_prefix)["response_schema"] == text_schema()
    assert build_identity(result)["statement"] != "求范围。"


def test_public_review_cannot_authorize_mathematical_or_other_public_changes():
    original = public_candidate()
    changed = deepcopy(original)
    changed["public_content"]["scopes"][0]["statement"] = "修正"
    changed["public_content"]["privacy"] = "uncertain"
    changed["root"]["facts"][1] = changed["root"]["facts"][1].replace("≤", "<")
    contract = SearchStageOneContract()
    review = correction("/public_content/scopes/0/statement")
    diagnostics = contract.review_diagnostics(review, original)
    failures = contract.repair_diagnostics(original, changed, diagnostics)
    assert {item["path"] for item in failures} >= {"/root/facts/1", "/public_content/privacy"}


@pytest.mark.parametrize("path,kind", [("/root", "wrong_public_content"), ("/public_content", "wrong_scope"), ("/public_content", "wrong_transcription")])
def test_review_field_authority_is_not_interchangeable(path, kind):
    review = correction(path)
    review["findings"][0]["kind"] = kind
    with pytest.raises(ValueError):
        SearchStageOneContract().validate_review(json.dumps(review), public_candidate())


def test_confirmed_incomplete_content_remains_private_without_extra_call(tmp_path):
    candidate = public_candidate()
    candidate["public_content"]["completeness"] = "incomplete"
    provider = Responses(candidate, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert len(provider.requests) == 2
    with pytest.raises(IdentityUnavailable, match="identity.incomplete_problem"):
        build_identity(result)


def test_old_graph_contract_is_unchanged_and_missing_public_metadata_is_invalid():
    candidate = public_candidate()
    old = {key: value for key, value in candidate.items() if key != "public_content"}
    assert validate_candidate(old)["contract_valid"]
    assert "public_content" not in GraphStageOneContract().schema()["properties"]
    checked = SearchStageOneContract().parse(json.dumps(old), problem_id="sample", source_hash="source", registry=[], store=None)
    assert not checked["contract_valid"]
    assert any(item["code"] == "schema.invalid" for item in checked["reports"]["ir"]["issues"])


def test_source_label_classification_is_reviewed_and_cannot_change_with_unrelated_repair(tmp_path):
    candidate = public_candidate()
    candidate["root"]["label"] = "甲方案"
    candidate["public_content"]["root_label_role"] = "content"
    changed = deepcopy(candidate)
    changed["public_content"]["scopes"][0]["statement"] = "修正题干"
    changed["public_content"]["root_label_role"] = "source"
    contract = SearchStageOneContract()
    diagnostics = contract.review_diagnostics(correction("/public_content/scopes/0/statement"), candidate)
    assert any(issue["path"] == "/public_content/root_label_role"
               for issue in contract.repair_diagnostics(candidate, changed, diagnostics))
    provider = Responses(candidate, CONFIRMED)
    result = run(tmp_path, provider)
    assert json.loads(provider.requests[1].prompt.user_prefix)["candidate"]["public_content"]["root_label_role"] == "content"
    assert build_identity(result)["identity"]["root"]["label"] == "甲方案"


def test_bad_public_option_repair_cannot_change_quantifier_or_other_choices(tmp_path):
    from tests.search.test_identity import choices

    candidate = public_candidate()
    choices(candidate)
    path = "/public_content/scopes/0/choices/0/options/0/text"
    malicious = deepcopy(candidate)
    malicious["public_content"]["scopes"][0]["choices"][0]["options"][0]["text"] = "$a≤1$"
    malicious["public_content"]["scopes"][0]["choices"][0]["options"][1]["text"] = "$a>1$"
    malicious["root"]["facts"][1] = malicious["root"]["facts"][1].replace("∀", "∃")
    repaired = deepcopy(candidate)
    repaired["public_content"]["scopes"][0]["choices"][0]["options"][0]["text"] = "$a≤1$"
    provider = Responses(candidate, correction(path), malicious, repaired, CONFIRMED)
    result = run(tmp_path, provider)
    assert result["status"] == "reviewed_candidate", result
    assert result["public_candidate"] == repaired
    assert result["reviewed_candidate_revision"] == revision(repaired)
    feedback = json.loads(provider.requests[3].prompt.user_prefix)["repair_feedback"]
    assert {issue["path"] for issue in feedback} >= {
        "/root/facts/1", "/public_content/scopes/0/choices/0/options/1/text"}
