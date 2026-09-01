from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import (
    BASELINE_SCHEMA,
    CASE_ID,
    COVERAGE_SCHEMA,
    EVALUATION_SCHEMA,
    LessonAuthoringSmokeError,
    _write_compiled_page,
    build_baseline_manifest,
    build_recorded_lesson_artifacts,
    build_teaching_spec_coverage,
    canonical_b0_snapshot_payload,
    current_lesson_prompt,
    evaluate_lesson_teaching,
    load_teaching_rubric,
    main,
    normalize_teaching_math_text,
    run_smoke_batch,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b0"
)
RECORDED_LESSON = (
    ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.lesson-ir.json"
)


def _snapshot():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture(CASE_ID)
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


@pytest.fixture(scope="module")
def b0_artifacts():
    snapshot = _snapshot()
    prompt = current_lesson_prompt(snapshot)
    recorded = build_recorded_lesson_artifacts(snapshot)
    rubric = load_teaching_rubric(FIXTURE_ROOT / "rubric.json")
    evaluation = evaluate_lesson_teaching(recorded.lesson, rubric)
    coverage = build_teaching_spec_coverage(
        snapshot,
        lesson_evaluation=evaluation,
    )
    return snapshot, prompt, recorded, rubric, evaluation, coverage


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _json_wire(payload):
    """Project model payloads through the same JSON boundary as goldens."""

    return json.loads(json.dumps(payload, ensure_ascii=False))


def test_b0_checked_in_goldens_rebuild_from_verified_recorded_solver(b0_artifacts) -> None:
    snapshot, prompt, recorded, _rubric, evaluation, coverage = b0_artifacts

    assert canonical_b0_snapshot_payload(snapshot) == canonical_b0_snapshot_payload(
        _json(FIXTURE_ROOT / "snapshot.json")
    )
    assert list(snapshot.macro_evidence) == _json(FIXTURE_ROOT / "macro-evidence.json")
    assert prompt.payload == _json(FIXTURE_ROOT / "payload.explanation.json")
    assert prompt.prompt.system == (FIXTURE_ROOT / "prompt.system.md").read_text(
        encoding="utf-8"
    )
    assert prompt.prompt.user == (FIXTURE_ROOT / "prompt.user.md").read_text(
        encoding="utf-8"
    )
    assert recorded.lesson.to_payload() == _json(FIXTURE_ROOT / "lesson-ir.json")
    assert recorded.lesson.to_payload() == _json(RECORDED_LESSON)
    assert evaluation == _json(FIXTURE_ROOT / "lesson-evaluation.json")
    assert coverage == _json(FIXTURE_ROOT / "teaching-spec-coverage.json")
    assert _json_wire(recorded.visual_ir.to_payload()) == _json(
        FIXTURE_ROOT / "visual-step-ir.json"
    )
    assert recorded.compiled.geometry_spec == _json(
        FIXTURE_ROOT / "compiled/geometry-spec.json"
    )
    assert recorded.compiled.step_decorations == _json(
        FIXTURE_ROOT / "compiled/step-decorations.json"
    )
    assert recorded.compiled.lesson_data == _json(
        FIXTURE_ROOT / "compiled/lesson-data.json"
    )

    expected_baseline = _json(FIXTURE_ROOT / "baseline.json")
    rebuilt = build_baseline_manifest(
        snapshot,
        current_prompt=prompt,
        recorded=recorded,
        coverage=coverage,
        live_observation=expected_baseline["live_observation"],
    )
    assert rebuilt["authority"]["observed_verified_execution_hash"] != ""
    rebuilt["authority"]["observed_verified_execution_hash"] = "<observed>"
    expected_baseline["authority"]["observed_verified_execution_hash"] = "<observed>"
    assert rebuilt == expected_baseline


def test_b0_baseline_freezes_current_counts_and_prompt(b0_artifacts) -> None:
    _snapshot_value, _prompt, _recorded, _rubric, _evaluation, coverage = b0_artifacts
    baseline = _json(FIXTURE_ROOT / "baseline.json")

    assert baseline["schema_version"] == BASELINE_SCHEMA
    assert baseline["source_revision"] == "b42f0e2"
    assert baseline["counts"] == {
        "canonical_source_steps": 12,
        "unique_capabilities": 9,
        "function_capabilities": 8,
        "macro_capabilities": 1,
        "macro_evidence": 1,
        "candidate_groups": 12,
        "deterministic_lesson_steps": 10,
        "visual_steps": 10,
        "nonempty_visual_scenes": 10,
        "compiled_lesson_steps": 10,
    }
    assert baseline["prompt"] == {
        "allow_same_problem_few_shot": False,
        "few_shot_count": 1,
        "system_chars": 947,
        "user_chars": 53760,
        "total_chars": 54707,
        "prompt_hash": "8b2d81ab74584a5a12823867d8aeece888b9ff686d34a0098c36571b47a4893f",
    }
    assert coverage["schema_version"] == COVERAGE_SCHEMA


def test_b0_coverage_is_canonical_and_identifies_b1_macro_gaps(b0_artifacts) -> None:
    _snapshot_value, _prompt, _recorded, _rubric, _evaluation, coverage = b0_artifacts
    assert coverage["source_step_occurrence_count"] == 12
    assert coverage["unique_capability_count"] == 9
    assert coverage["function_capability_count"] == 8
    assert coverage["macro_capability_count"] == 1

    macro = next(
        item
        for item in coverage["capabilities"]
        if item["capability_id"] == "quadratic_square_path_minimum"
    )
    assert macro["kind"] == "macro"
    assert macro["occurrences"] == [
        {
            "step_id": "derive_path_minimum_ii",
            "owner_scope_ref": "ii",
            "owner_goal_ref": "ii.E",
            "public_returns": ["minimum_expression", "attainment_point"],
            "evidence_refs": macro["occurrences"][0]["evidence_refs"],
            "evidence_schemas": ["path-minimum-prompt-witness/v1"],
        }
    ]
    assert macro["current"]["evidence_projection"] == (
        "path_minimum_hardcoded_projector"
    )
    assert macro["vnext_b1"]["recommended_unit_source"] == (
        "explicit_units_required"
    )
    assert macro["vnext_b1"]["suggested_unit_count"] == 2
    assert macro["vnext_b1"]["actions"] == [
        "explicit_units_required",
        "evidence_projector_registry_required",
    ]
    assert macro["vnext_b1"]["observed_teaching_point_gaps"] == [
        "moving_point_locus",
        "reflection_construction",
        "reflection_segment_equality",
    ]
    assert all(
        item["vnext_b1"]["teaching_unit_contract"] == "not_implemented_in_b0"
        for item in coverage["capabilities"]
    )


def test_b0_rubric_reports_current_deterministic_teaching_gaps(b0_artifacts) -> None:
    _snapshot_value, prompt, _recorded, _rubric, evaluation, _coverage = b0_artifacts
    assert evaluation["schema_version"] == EVALUATION_SCHEMA
    assert evaluation["covered"] == [
        "path_reduction_equivalence",
        "minimum_and_parameterized_attainment",
    ]
    assert evaluation["missing"] == [
        "moving_point_locus",
        "reflection_construction",
        "reflection_segment_equality",
    ]
    assert evaluation["coverage_rate"] == 0.4

    serialized_input = json.dumps(prompt.payload, ensure_ascii=False)
    rendered_prompt = f"{prompt.prompt.system}\n{prompt.prompt.user}"
    for rubric_only_field in (
        "required_pattern_groups",
        "path_reduction_equivalence",
        "reflection_segment_equality",
    ):
        assert rubric_only_field not in serialized_input
        assert rubric_only_field not in rendered_prompt


def test_b0_rubric_normalizes_fullwidth_math_and_prime_variants(b0_artifacts) -> None:
    _snapshot_value, _prompt, recorded, rubric, _evaluation, _coverage = b0_artifacts
    payload = copy.deepcopy(recorded.lesson.to_payload())
    minimum = next(
        step
        for step in payload["steps"]
        if "derive_path_minimum_ii" in step["source_step_ids"]
    )
    minimum["derive"] = [
        ["∴", "ＨＦ ＋ ＦＭ ＋ ＭＧ ＝ ＡＧ ＋ ＭＧ"],
        ["∴", "点 G 的轨迹为直线 y＝－（c＋1）／2"],
        ["作", "A' 是 A 关于该轨迹直线的对称点"],
        ["∴", "ＡＧ＝Ａ'Ｇ"],
        ["∴", "最小值为 √5｜c＋1｜／2"],
        ["∴", "取等点为 G（（1－3c）／4，－（c＋1）／2）"],
    ]
    minimum["box"] = []

    evaluation = evaluate_lesson_teaching(payload, rubric)
    assert evaluation["missing"] == []
    assert evaluation["coverage_rate"] == 1.0
    assert normalize_teaching_math_text("Ａ′ ＝ A'") == "a'=a'"


def test_b0_rubric_schema_is_strict() -> None:
    rubric = _json(FIXTURE_ROOT / "rubric.json")
    rubric["generator_hint"] = "forbidden"
    with pytest.raises(LessonAuthoringSmokeError, match="root fields"):
        evaluate_lesson_teaching(_json(FIXTURE_ROOT / "lesson-ir.json"), rubric)


def test_b0_recorded_compiled_page_uses_repository_compiler(
    b0_artifacts,
    tmp_path: Path,
) -> None:
    _snapshot_value, _prompt, recorded, _rubric, _evaluation, _coverage = b0_artifacts
    html_path = _write_compiled_page(tmp_path, compiled=recorded.compiled)
    html = html_path.read_text(encoding="utf-8")
    assert "STEPS" in html
    assert "第（Ⅱ）问" in html
    assert "E(－2, 3/2)" in html or "E(-2,3/2)" in html


class _FakeLessonClient:
    provider_name = "fake"
    model = "fake-lesson-model"
    last_response_model = "fake-lesson-model"
    last_provider_reasoning = ()

    def __init__(self, raw_response: str) -> None:
        self.raw_response = raw_response
        self.last_usage = {}
        self.last_provider_attempts = ()
        self.calls = 0

    def complete(self, _payload: dict) -> str:
        self.calls += 1
        self.last_usage = {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
        }
        self.last_provider_attempts = (
            {
                "provider_attempt": 1,
                "usage": dict(self.last_usage),
                "visible_content": True,
            },
        )
        return self.raw_response


def _valid_lesson_response(lesson) -> str:
    steps = []
    for item in lesson.to_payload()["steps"]:
        steps.append(
            {
                "id": item["id"],
                "source_step_ids": item["source_step_ids"],
                "title": item["title"],
                "nav_title": item["nav_title"],
                "goal": item["goal"],
                "derive": [
                    ["∵", "使用当前步骤已经验证的输入条件"],
                    ["∴", "得到当前步骤已经验证的结论"],
                ],
                "box": item["box"],
            }
        )
    return json.dumps({"steps": steps}, ensure_ascii=False)


def _fake_page_writer(sample_dir: Path, *, compiled) -> Path:
    del compiled
    html_path = sample_dir / "lesson.html"
    html_path.write_text("<html>fake compiled lesson</html>", encoding="utf-8")
    return html_path


def test_b0_fake_live_batch_keeps_three_samples_and_usage_separate(
    b0_artifacts,
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot, _prompt, recorded, rubric, _evaluation, _coverage = b0_artifacts
    monkeypatch.setattr(
        "shuxueshuo_server.solver.lesson_scope_authoring_smoke._write_compiled_page",
        _fake_page_writer,
    )
    raw = _valid_lesson_response(recorded.lesson)

    summary = run_smoke_batch(
        snapshot,
        rubric,
        mode="live",
        batch_dir=tmp_path / "live-batch",
        samples_per_case=3,
        concurrency=3,
        max_attempts=3,
        client_factory=lambda _sample_id: _FakeLessonClient(raw),
        batch_config={"schema_version": "test-config/v1"},
    )

    assert summary["completion_gate_ok"] is True
    assert summary["sample_count"] == 3
    assert summary["llm_accepted_count"] == 3
    assert summary["fallback_count"] == 0
    assert summary["semantic_attempts"] == 3
    assert summary["usage"] == {
        "prompt_tokens": 300,
        "completion_tokens": 60,
        "total_tokens": 360,
    }
    durations = [item["duration_seconds"] for item in summary["samples"]]
    assert summary["duration_seconds"]["total"] == round(sum(durations), 6)
    assert summary["duration_seconds"]["average"] == round(
        sum(durations) / len(durations),
        6,
    )
    assert summary["duration_seconds"]["p50"] == sorted(durations)[1]
    assert summary["duration_seconds"]["p95"] == max(durations)
    for index in range(1, 4):
        sample_dir = tmp_path / "live-batch" / CASE_ID / f"sample-{index:02d}"
        result = _json(sample_dir / "sample-result.json")
        assert result["completion_ok"] is True
        assert result["lesson_source"] == "llm"
        assert result["semantic_attempt_count"] == 1
        attempt_metadata = _json(
            sample_dir / "explanation/attempt-1.llm-metadata.json"
        )
        assert attempt_metadata["provider"] == "fake"
        assert attempt_metadata["request_model"] == "fake-lesson-model"
        assert attempt_metadata["response_model"] == "fake-lesson-model"
        assert attempt_metadata["usage"]["total_tokens"] == 120
        assert attempt_metadata["first_token_seconds"] is None
        assert attempt_metadata["first_token_unavailable_reason"] == (
            "provider_client_uses_non_streaming_chat_completions"
        )
        assert (sample_dir / "explanation/attempt-1.parsed-lesson-draft.json").exists()
        assert (sample_dir / "explanation/attempt-1.validation-diagnostic.json").exists()
        assert (sample_dir / "lesson.html").exists()


def test_b0_invalid_live_response_observes_legacy_retry_then_falls_back(
    b0_artifacts,
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot, _prompt, _recorded, rubric, _evaluation, _coverage = b0_artifacts
    monkeypatch.setattr(
        "shuxueshuo_server.solver.lesson_scope_authoring_smoke._write_compiled_page",
        _fake_page_writer,
    )
    summary = run_smoke_batch(
        snapshot,
        rubric,
        mode="live",
        batch_dir=tmp_path / "fallback-batch",
        samples_per_case=1,
        concurrency=1,
        max_attempts=2,
        client_factory=lambda _sample_id: _FakeLessonClient("{}"),
    )
    sample = summary["samples"][0]
    assert summary["completion_gate_ok"] is True
    assert sample["lesson_source"] == "deterministic_fallback"
    assert sample["fallback_used"] is True
    assert sample["semantic_attempt_count"] == 2
    assert sample["usage"]["total_tokens"] == 240


def test_b0_cli_dry_run_does_not_require_provider_or_write_batch(
    tmp_path: Path,
    capsys,
) -> None:
    result = main(
        [
            "--mode",
            "recorded",
            "--batch-id",
            "dry-run",
            "--output-root",
            str(tmp_path),
            "--dry-run",
        ]
    )
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["case_ids"] == [CASE_ID]
    assert payload["visual_llm_enabled"] is False
    assert not (tmp_path / "dry-run").exists()
