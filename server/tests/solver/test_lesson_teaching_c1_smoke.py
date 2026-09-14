from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.models import iter_teaching_sources
from support.lesson_teaching_c1_smoke import (
    C1_BATCH_CONFIG_CONTRACT,
    C1_BATCH_SUMMARY_CONTRACT,
    C1_CASE_IDS,
    C1_REVIEW_CONTRACT,
    LessonTeachingC1SmokeError,
    build_c1_cases,
    run_teaching_c1_batch,
)


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def c1_cases(tmp_path_factory: pytest.TempPathFactory):
    return build_c1_cases(
        root=ROOT,
        authority_root=tmp_path_factory.mktemp("lesson-c1-authority"),
    )


def test_c1_cases_are_rebuilt_from_all_five_verified_snapshots(c1_cases) -> None:
    assert tuple(item.problem_id for item in c1_cases) == C1_CASE_IDS
    assert len({item.prompt_hash for item in c1_cases}) == len(C1_CASE_IDS)

    for case in c1_cases:
        assert case.snapshot.problem_id == case.problem_id
        assert case.rubric["schema_version"] == "lesson-teaching-rubric/v1"
        assert case.rubric["problem_id"] == case.problem_id
        assert len(case.rubric["points"]) == 5
        assert len({item["point_id"] for item in case.rubric["points"]}) == 5


def test_c1_rubrics_are_evaluation_only_and_never_enter_provider_prompt(
    c1_cases,
) -> None:
    forbidden = (
        "lesson-teaching-rubric/v1",
        "required_pattern_groups",
        '"point_id"',
        '"rubric"',
    )

    for case in c1_cases:
        projection = AnnotatedTeachingPlanProjector().project(case.snapshot)
        assert projection.diagnostics == ()
        output_schema = lesson_scope_content_schema(projection.plan)
        prompt = render_annotated_teaching_prompt(
            projection.plan,
            authority=projection.authority,
            output_schema=output_schema,
        )
        provider_text = f"{prompt.system}\n{prompt.user}"
        assert case.problem_id not in provider_text
        for marker in forbidden:
            assert marker not in provider_text


def test_c1_prompts_expose_positive_merge_ranges_and_no_private_auxiliary(
    c1_cases,
) -> None:
    prompts = {}
    for case in c1_cases:
        projection = AnnotatedTeachingPlanProjector().project(case.snapshot)
        output_schema = lesson_scope_content_schema(projection.plan)
        prompts[case.problem_id] = render_annotated_teaching_prompt(
            projection.plan,
            authority=projection.authority,
            output_schema=output_schema,
        ).user

    nankai = prompts["tj-2026-nankai-yimo-25"]
    assert (
        '- Scope ii：必须分别输出 ["s1"]、["s2"]、["s5"]、["s6"]'
        in nankai
    )
    assert '- Scope ii：["s3","s4"]' in nankai

    xiqing_case = next(
        case
        for case in c1_cases
        if case.problem_id == "tj-2026-xiqing-yimo-25"
    )
    weighted_source = next(
        source
        for source in iter_teaching_sources(xiqing_case.snapshot.root_scope)
        if source.capability_id == "weighted_axis_path_minimum"
    )
    evidence = xiqing_case.snapshot.evidence_for_step(
        weighted_source.source_step_id
    )
    student_auxiliary = evidence[0]["constructions"][0][
        "student_auxiliary_point"
    ]
    xiqing = prompts[xiqing_case.problem_id]
    assert student_auxiliary["label"] in xiqing
    assert "AauxiliaryM" not in xiqing
    assert "auxiliaryM" not in xiqing
    assert '"auxiliary_point"' not in xiqing


def test_recorded_five_case_batch_is_atomic_isolated_and_reviewable(
    tmp_path: Path,
    c1_cases,
) -> None:
    batch_dir = tmp_path / "five-case-recorded"
    config = {
        "schema_version": C1_BATCH_CONFIG_CONTRACT,
        "batch_id": "five-case-recorded",
        "same_problem_few_shot": False,
        "rubric_is_evaluation_only": True,
    }
    summary = run_teaching_c1_batch(
        c1_cases,
        mode="recorded",
        batch_dir=batch_dir,
        samples_per_case=2,
        concurrency=10,
        max_transport_attempts=2,
        thinking_effort="disabled",
        batch_config=config,
    )

    assert summary["schema_version"] == C1_BATCH_SUMMARY_CONTRACT
    assert summary["automated_gate_ok"] is True
    assert summary["review_status"] == "awaiting_human_review"
    assert summary["case_count"] == 5
    assert summary["sample_count"] == 10
    assert summary["completed_sample_count"] == 10
    assert summary["direct_acceptance_count"] == 10
    assert summary["contract_pass_count"] == 10
    assert summary["authority_pass_count"] == 10
    assert summary["rubric_full_coverage_count"] == 10
    assert summary["fallback_count"] == 0
    assert summary["syntax_repair_count"] == 0
    assert summary["source_step_completion_repair_count"] == 0
    assert summary["independent_material_merge_repair_count"] == 0
    assert summary["unclassified_failure_count"] == 0
    assert summary["thinking"] == "disabled"
    assert summary["semantic_attempt_count"] == 10
    assert summary["transport_request_count"] == 10
    assert summary["usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert summary["human_review_approved"] is False

    stored_config = json.loads(
        (batch_dir / "batch-config.json").read_text(encoding="utf-8")
    )
    assert stored_config == config
    review = json.loads(
        (batch_dir / "review.json").read_text(encoding="utf-8")
    )
    assert review["schema_version"] == C1_REVIEW_CONTRACT
    assert review["status"] == "awaiting_human_review"
    assert [item["problem_id"] for item in review["cases"]] == list(
        C1_CASE_IDS
    )

    html = (batch_dir / "review.html").read_text(encoding="utf-8")
    assert html.count("打开三份正文横向 Review") == 5
    assert "<script src=" not in html
    assert "<link rel=" not in html

    for case in c1_cases:
        case_dir = batch_dir / "cases" / case.problem_id
        assert (case_dir / "review.html").is_file()
        for sample_id in ("sample-01", "sample-02"):
            sample_dir = case_dir / sample_id
            result = json.loads(
                (sample_dir / "sample-result.json").read_text(
                    encoding="utf-8"
                )
            )
            assert result["problem_id"] == case.problem_id
            assert result["sample_id"] == sample_id
            assert result["teaching_point_count"] == 5
            assert result["teaching_coverage_rate"] == 1.0
            prompt_text = (
                (sample_dir / "prompt.system.md").read_text(encoding="utf-8")
                + (sample_dir / "prompt.user.md").read_text(encoding="utf-8")
            )
            assert "lesson-teaching-rubric/v1" not in prompt_text
            assert "required_pattern_groups" not in prompt_text

    with pytest.raises(LessonTeachingC1SmokeError, match="output_exists"):
        run_teaching_c1_batch(
            c1_cases,
            mode="recorded",
            batch_dir=batch_dir,
            samples_per_case=1,
            concurrency=5,
            max_transport_attempts=2,
        )


def test_hexi_rubric_accepts_equivalent_radical_serializations(c1_cases) -> None:
    hexi = next(
        item for item in c1_cases if item.problem_id == "tj-2026-hexi-yimo-25"
    )
    candidate_filter = next(
        point
        for point in hexi.rubric["points"]
        if point["point_id"] == "candidate_filter_and_parameter"
    )
    alternatives = candidate_filter["required_pattern_groups"]
    assert any("b=-1+sqrt(2)" in group for group in alternatives)
