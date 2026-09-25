from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation import lesson_prompt
from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.lesson_authoring_support import (
    load_teaching_rubric,
)
from shuxueshuo_server.solver.lesson_recursive_ir_review import (
    LessonRecursiveIRReviewError,
    build_recursive_lesson_review,
    write_recursive_lesson_review,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "server/tests/solver/fixtures/lesson_scope_authoring_vnext"
B4 = FIXTURES / "heping_ermo_b4"


@pytest.fixture(scope="module")
def raw_inputs():
    snapshot = explanation_snapshot_from_payload(
        json.loads(
            (FIXTURES / "heping_ermo_b1/snapshot.json").read_text(
                encoding="utf-8"
            )
        )
    )
    approved_scope_content = json.loads(
        (FIXTURES / "heping_ermo_b3/scope-content.json").read_text(
            encoding="utf-8"
        )
    )
    rubric = load_teaching_rubric(
        FIXTURES / "heping_ermo_b0/rubric.json"
    )
    return snapshot, approved_scope_content, rubric


@pytest.fixture(scope="module")
def artifacts(raw_inputs):
    snapshot, approved_scope_content, rubric = raw_inputs
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    approved = validator.validate_payload(approved_scope_content)
    assert approved.direct_acceptance
    assert not approved.independent_material_merge_repaired
    return build_recursive_lesson_review(
        snapshot,
        approved_scope_content=approved_scope_content,
        rubric=rubric,
    )


def test_review_accepts_current_human_approved_b3_body(raw_inputs) -> None:
    snapshot, approved_scope_content, rubric = raw_inputs
    result = build_recursive_lesson_review(
        snapshot,
        approved_scope_content=approved_scope_content,
        rubric=rubric,
    )
    assert result.audit["checks"]["approved_body_compatible"] is True
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    prompt = render_annotated_teaching_prompt(projection.plan, authority=projection.authority)
    assert result.audit["hashes"]["prompt"] == stable_hash(prompt.messages)
    assert result.audit["prompt_assets"] == list(prompt.assets)


def test_review_audits_template_changes_without_reapproving_history(
    raw_inputs, artifacts, tmp_path, monkeypatch,
) -> None:
    for source in lesson_prompt.TEMPLATE_ROOT.glob("*.jinja"):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    shared = tmp_path / "shared-v1.jinja"
    shared.write_text(shared.read_text() + "\n请保持讲解简洁。\n")
    monkeypatch.setattr(lesson_prompt, "TEMPLATE_ROOT", tmp_path)
    snapshot, body, rubric = raw_inputs
    result = build_recursive_lesson_review(snapshot, approved_scope_content=body, rubric=rubric)
    assert result.audit["hashes"]["prompt"] != artifacts.audit["hashes"]["prompt"]
    assert result.audit["prompt_assets"] != artifacts.audit["prompt_assets"]
    assert result.audit["human_review_approved"] is False
    assert result.approved.build.lesson.to_payload() == artifacts.approved.build.lesson.to_payload()


def test_review_still_rejects_incompatible_recorded_body(raw_inputs) -> None:
    snapshot, _, rubric = raw_inputs
    with pytest.raises(LessonRecursiveIRReviewError, match="approved_body_rejected"):
        build_recursive_lesson_review(snapshot, approved_scope_content={}, rubric=rubric)


def test_review_builds_both_recursive_branches(artifacts) -> None:
    assert artifacts.audit["status"] == "ready_for_human_review"
    assert artifacts.audit["human_review_approved"] is False
    assert artifacts.audit["counts"] == {
        "scope_count": 5,
        "goal_count": 4,
        "approved_lesson_step_count": 12,
        "fallback_lesson_step_count": 13,
        "approved_visual_step_count": 12,
        "fallback_visual_step_count": 13,
    }
    assert all(artifacts.audit["checks"].values())
    assert artifacts.audit["forbidden_fields"] == []
    assert len(artifacts.review["cards"]) == 12
    assert len(artifacts.review["answer_links"]) == 4


def test_human_approved_b4_golden_matches_rebuilt_artifacts(artifacts) -> None:
    approved = json.loads(
        (B4 / "approved-lesson-ir.json").read_text(encoding="utf-8")
    )
    deterministic = json.loads(
        (B4 / "deterministic-lesson-ir.json").read_text(encoding="utf-8")
    )
    visual = json.loads(
        (B4 / "visual-step-ir.json").read_text(encoding="utf-8")
    )
    visual_authority = json.loads(
        (B4 / "visual-state-authority.json").read_text(encoding="utf-8")
    )
    assembly_authority = json.loads(
        (B4 / "lesson-assembly-authority.json").read_text(encoding="utf-8")
    )
    review = json.loads(
        (B4 / "human-review-summary.json").read_text(encoding="utf-8")
    )
    hashes = json.loads(
        (B4 / "artifact-hashes.json").read_text(encoding="utf-8")
    )

    assert approved == artifacts.approved.build.lesson.to_payload()
    assert deterministic == artifacts.fallback.build.lesson.to_payload()
    assert assembly_authority == artifacts.approved.build.assembly_authority
    assert visual == artifacts.approved.visual_ir.to_payload()
    assert visual_authority == artifacts.approved.visual_ir.state_authority
    assert review["review_status"] == "approved"
    assert review["checks"]["human_page_review"] is True
    # Historical approvals are compared to their own request audit, never to
    # the current template wording. Keep all golden files untouched.
    historical_audit = json.loads((FIXTURES / "heping_ermo_b2/projection-audit.json").read_text())
    b3_review = json.loads((FIXTURES / "heping_ermo_b3/review-summary.json").read_text())
    assert hashes["semantic_hashes"]["prompt"] == historical_audit["hashes"]["prompt"]
    assert hashes["semantic_hashes"]["prompt"] == b3_review["source"]["prompt_hash"]
    for filename, expected in hashes["fixture_file_hashes"].items():
        observed = hashlib.sha256((B4 / filename).read_bytes()).hexdigest()
        assert observed == expected


def test_review_writer_compiles_pages_and_exposes_auditable_artifacts(
    artifacts,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "f5-f5b4-review"
    write_recursive_lesson_review(artifacts, output_dir=output_dir)

    expected = (
        "assembly-audit.json",
        "review.json",
        "review.html",
        "approved/lesson-ir.json",
        "approved/lesson-assembly-authority.json",
        "approved/visual-step-ir.json",
        "approved/lesson.html",
        "deterministic-fallback/lesson-ir.json",
        "deterministic-fallback/lesson-assembly-authority.json",
        "deterministic-fallback/visual-step-ir.json",
        "deterministic-fallback/lesson.html",
    )
    assert all((output_dir / relative).is_file() for relative in expected)
    review_html = (output_dir / "review.html").read_text(encoding="utf-8")
    assert "Approved assembly authority" in review_html
    assert "Approved VisualStepIR" in review_html
    assert "等待人工审阅" in review_html
