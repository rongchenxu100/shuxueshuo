from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
    evaluate_scope_lesson_content,
)
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import (
    load_teaching_rubric,
)
from shuxueshuo_server.solver.lesson_scope_content_smoke import (
    REVIEW_CONTRACT,
    run_scope_lesson_batch,
)


ROOT = Path(__file__).resolve().parents[3]
B0 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b0"
)
B1 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b1"
)
B2 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b2"
)
B3 = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b3"
)


@pytest.fixture(scope="module")
def snapshot():
    return explanation_snapshot_from_payload(
        json.loads((B1 / "snapshot.json").read_text(encoding="utf-8"))
    )


@pytest.fixture(scope="module")
def rubric():
    return load_teaching_rubric(B0 / "rubric.json")


@pytest.fixture(scope="module")
def reviewed_prompt_hash():
    return json.loads(
        (B2 / "projection-audit.json").read_text(encoding="utf-8")
    )["hashes"]["prompt"]


def test_recorded_three_sample_batch_is_complete_and_create_once(
    tmp_path: Path,
    snapshot,
    rubric,
    reviewed_prompt_hash,
) -> None:
    batch_dir = tmp_path / "recorded"
    summary = run_scope_lesson_batch(
        snapshot,
        rubric,
        mode="recorded",
        batch_dir=batch_dir,
        samples_per_case=3,
        concurrency=3,
        max_transport_attempts=2,
        reviewed_prompt_hash=reviewed_prompt_hash,
        batch_config={"batch_id": "recorded"},
    )

    assert summary["automated_gate_ok"] is True
    assert summary["direct_acceptance_count"] == 3
    assert summary["contract_pass_count"] == 3
    assert summary["authority_pass_count"] == 3
    assert summary["rubric_5_of_5_count"] == 3
    assert summary["fallback_count"] == 0
    assert summary["syntax_repair_count"] == 0
    assert summary["source_step_completion_repair_count"] == 0
    assert summary["semantic_attempt_count"] == 3
    assert summary["transport_request_count"] == 3
    assert summary["prompt_hashes"] == [reviewed_prompt_hash]
    assert summary["human_review_approved"] is False

    for index in range(1, 4):
        sample = batch_dir / f"sample-{index:02d}"
        assert {
            "snapshot.json",
            "teaching-authority.json",
            "annotated-teaching-plan.json",
            "output-schema.json",
            "prompt.system.md",
            "prompt.user.md",
            "projection-audit.json",
            "transport-attempt-01.raw-response.txt",
            "transport-attempt-01.metadata.json",
            "transport-attempt-01.reasoning.json",
            "raw-response.txt",
            "parsed-scope-content.json",
            "validation-diagnostics.json",
            "accepted-scope-content.json",
            "deterministic-fallback.json",
            "lesson-evaluation.json",
            "llm-metadata.json",
            "sample-result.json",
        } == {item.name for item in sample.iterdir()}
        reasoning = json.loads(
            (sample / "transport-attempt-01.reasoning.json").read_text(
                encoding="utf-8"
            )
        )
        assert reasoning == {
            "schema_version": "lesson-provider-reasoning-debug/v1",
            "debug_only": True,
            "transport_attempt": 1,
            "prompt_hash": reviewed_prompt_hash,
            "provider": "recorded",
            "request_model": "recorded-scope-lesson",
            "response_model": "recorded-scope-lesson",
            "reasoning_content_available": False,
            "reasoning_content_chars": 0,
            "captured_reasoning_content_chars": 0,
            "capture_complete": True,
            "provider_attempts": [],
        }

    review = json.loads((batch_dir / "review.json").read_text(encoding="utf-8"))
    assert review["schema_version"] == REVIEW_CONTRACT
    assert all(item["materials"] for item in review["containers"])
    assert len(review["samples"]) == 3
    html = (batch_dir / "review.html").read_text(encoding="utf-8")
    assert html.count("sample-01") >= 1
    assert html.count("sample-02") >= 1
    assert html.count("sample-03") >= 1
    assert "横向对比" in html
    assert "<script src=" not in html
    assert "<link rel=" not in html

    with pytest.raises(Exception, match="output_exists"):
        run_scope_lesson_batch(
            snapshot,
            rubric,
            mode="recorded",
            batch_dir=batch_dir,
            samples_per_case=1,
            concurrency=1,
            max_transport_attempts=2,
            reviewed_prompt_hash=reviewed_prompt_hash,
        )


def test_human_approved_b3_fixture_is_valid_and_regression_only(
    snapshot,
    rubric,
    reviewed_prompt_hash,
) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    result = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    ).validate_payload(
        json.loads((B3 / "scope-content.json").read_text(encoding="utf-8"))
    )
    evaluation = evaluate_scope_lesson_content(
        result,
        problem_id=snapshot.problem_id,
        rubric=rubric,
    )
    expected_evaluation = json.loads(
        (B3 / "lesson-evaluation.json").read_text(encoding="utf-8")
    )
    review = json.loads(
        (B3 / "review-summary.json").read_text(encoding="utf-8")
    )

    assert result.direct_acceptance is True
    assert result.fallback_used is False
    assert result.syntax_repaired is False
    assert result.source_step_completion_repaired is False
    assert result.diagnostics == ()
    assert set(result.scope_sources.values()) == {"llm"}
    assert sum(len(items) for items in result.bound_steps.values()) == 11
    assert evaluation == expected_evaluation
    assert review["review_status"] == "approved"
    assert review["source"]["prompt_hash"] == reviewed_prompt_hash
    assert review["validation"]["rubric_coverage"] == "5/5"
    assert review["fixture_policy"] == {
        "regression_only": True,
        "generator_input_allowed": False,
        "few_shot_allowed": False,
    }

    import shuxueshuo_server.solver.explanation.scope_lesson as module

    assert "heping_ermo_b3" not in inspect.getsource(module)


class _InvalidClient:
    provider_name = "fake"
    model = "fake"
    last_response_model = "fake"
    last_provider_attempts = ()
    last_usage = {
        "prompt_tokens": 10,
        "completion_tokens": 1,
        "total_tokens": 11,
    }

    def complete(self, _payload):
        return "not json"


class _ReasoningClient:
    provider_name = "fake"
    model = "fake-thinking"
    last_response_model = "fake-thinking-response"

    def __init__(self, response: str) -> None:
        self.response = response
        self.last_usage = {
            "prompt_tokens": 10,
            "completion_tokens": 7,
            "total_tokens": 17,
        }
        self.last_provider_attempts = (
            {
                "provider_attempt": 1,
                "reasoning_content_available": True,
                "reasoning_content_chars": 42,
            },
        )
        self.last_provider_reasoning = (
            {
                "provider_attempt": 1,
                "reasoning_content": "debug-only provider reasoning for test run",
            },
        )

    def complete(self, _payload):
        return self.response


def test_live_invalid_response_is_audited_but_fails_strict_gate(
    tmp_path: Path,
    snapshot,
    rubric,
    reviewed_prompt_hash,
) -> None:
    summary = run_scope_lesson_batch(
        snapshot,
        rubric,
        mode="live",
        batch_dir=tmp_path / "invalid-live",
        samples_per_case=1,
        concurrency=1,
        max_transport_attempts=2,
        reviewed_prompt_hash=reviewed_prompt_hash,
        client_factory=lambda _sample_id: _InvalidClient(),
    )

    assert summary["automated_gate_ok"] is False
    assert summary["completed_sample_count"] == 1
    assert summary["direct_acceptance_count"] == 0
    assert summary["fallback_count"] == 1
    assert summary["transport_request_count"] == 1
    assert summary["rubric_5_of_5_count"] == 1


def test_provider_reasoning_is_saved_only_in_dedicated_debug_artifact(
    tmp_path: Path,
    snapshot,
    rubric,
    reviewed_prompt_hash,
) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    response = json.dumps(validator.deterministic_fallback, ensure_ascii=False)
    batch_dir = tmp_path / "reasoning-debug"

    summary = run_scope_lesson_batch(
        snapshot,
        rubric,
        mode="live",
        batch_dir=batch_dir,
        samples_per_case=1,
        concurrency=1,
        max_transport_attempts=2,
        reviewed_prompt_hash=reviewed_prompt_hash,
        client_factory=lambda _sample_id: _ReasoningClient(response),
    )

    assert summary["automated_gate_ok"] is True
    sample = batch_dir / "sample-01"
    reasoning_path = sample / "transport-attempt-01.reasoning.json"
    reasoning = json.loads(reasoning_path.read_text(encoding="utf-8"))
    assert reasoning["schema_version"] == "lesson-provider-reasoning-debug/v1"
    assert reasoning["debug_only"] is True
    assert reasoning["capture_complete"] is True
    assert reasoning["captured_reasoning_content_chars"] == 42
    assert reasoning["provider_attempts"] == [
        {
            "provider_attempt": 1,
            "reasoning_content": "debug-only provider reasoning for test run",
            "reasoning_content_chars": 42,
            "reasoning_content_hash": (
                "5c3c90a7fd536d830dc49c5ba4172514e4dfa9a7db14a7a32eeab13b0c643830"
            ),
        }
    ]
    metadata_text = (sample / "llm-metadata.json").read_text(encoding="utf-8")
    assert "transport-attempt-01.reasoning.json" in metadata_text
    assert "debug-only provider reasoning for test run" not in metadata_text
    assert "debug-only provider reasoning for test run" not in (
        batch_dir / "review.json"
    ).read_text(encoding="utf-8")
    assert "debug-only provider reasoning for test run" not in (
        batch_dir / "review.html"
    ).read_text(encoding="utf-8")


def test_single_omitted_source_step_is_completed_and_audited(
    tmp_path: Path,
    snapshot,
    rubric,
    reviewed_prompt_hash,
) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    response = validator.deterministic_fallback
    response["i"]["steps"] = response["i"]["steps"][:1]
    batch_dir = tmp_path / "single-material-completion"

    summary = run_scope_lesson_batch(
        snapshot,
        rubric,
        mode="live",
        batch_dir=batch_dir,
        samples_per_case=1,
        concurrency=1,
        max_transport_attempts=2,
        reviewed_prompt_hash=reviewed_prompt_hash,
        client_factory=lambda _sample_id: _ReasoningClient(
            json.dumps(response, ensure_ascii=False)
        ),
    )

    assert summary["automated_gate_ok"] is True
    assert summary["direct_acceptance_count"] == 1
    assert summary["fallback_count"] == 0
    assert summary["source_step_completion_repair_count"] == 1
    sample_result = json.loads(
        (batch_dir / "sample-01/sample-result.json").read_text(
            encoding="utf-8"
        )
    )
    assert sample_result["source_step_completion_repaired"] is True
    validation = json.loads(
        (batch_dir / "sample-01/validation-diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert validation["source_step_completion_repaired"] is True
    assert any(
        item["code"] == "lesson_scope_single_source_step_completed"
        and item["severity"] == "warning"
        for item in validation["diagnostics"]
    )
    accepted = json.loads(
        (batch_dir / "sample-01/accepted-scope-content.json").read_text(
            encoding="utf-8"
        )
    )
    assert [step["source_steps"] for step in accepted["i"]["steps"]] == [
        ["s1"],
        ["s2"],
    ]

def test_review_data_derives_provenance_without_llm_authored_ids(
    tmp_path: Path,
    snapshot,
    rubric,
    reviewed_prompt_hash,
) -> None:
    batch_dir = tmp_path / "authority"
    run_scope_lesson_batch(
        snapshot,
        rubric,
        mode="recorded",
        batch_dir=batch_dir,
        samples_per_case=1,
        concurrency=1,
        max_transport_attempts=2,
        reviewed_prompt_hash=reviewed_prompt_hash,
    )
    review = json.loads((batch_dir / "review.json").read_text(encoding="utf-8"))
    macro = review["samples"][0]["bound_steps"]["goal:ii.E"][1:3]
    assert [item["material_positions"] for item in macro] == [[1], [2]]
    assert [item["source_step_ids"] for item in macro] == [
        ["derive_path_minimum_ii"],
        ["derive_path_minimum_ii"],
    ]
    raw = review["samples"][0]["raw_response"]
    assert '"source_steps"' in raw
    assert '"material_count"' not in raw
    assert "source_step_ids" not in raw
    assert "unit_key" not in raw
    assert "evidence_refs" not in raw


def test_b3_harness_does_not_construct_lesson_or_visual_ir() -> None:
    import shuxueshuo_server.solver.lesson_scope_content_smoke as module

    source = inspect.getsource(module)
    assert "ExplanationBuilder(" not in source
    assert "LessonIR(" not in source
    assert "VisualStepBuilder(" not in source


def test_recorded_response_matches_b2_dynamic_contract(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    content = validator.deterministic_fallback

    assert set(content) == {"i", "i_1", "i_2", "ii"}
    serialized = json.dumps(content, ensure_ascii=False)
    assert '"box"' not in serialized
    assert '"visuals"' not in serialized
