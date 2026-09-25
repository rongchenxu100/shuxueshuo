from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    build_projection_audit,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LESSON_IR_CONTRACT,
    LessonIRValidationError,
    RecursiveLessonIRAssembler,
    lesson_ir_from_payload,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
)
from shuxueshuo_server.solver.visual import (
    VisualStepBuilder,
    VisualStepIRValidator,
    forward_compile,
)


ROOT = Path(__file__).resolve().parents[3]
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
REVIEWED_PROMPT_HASH = (
    "a4826d362374ffacf405a4188c7a63b4d516a5bd67bba8c61272390b027fa257"
)


@pytest.fixture(scope="module")
def snapshot():
    return explanation_snapshot_from_payload(
        json.loads((B1 / "snapshot.json").read_text(encoding="utf-8"))
    )


def _projection_and_validator(snapshot):
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    return projection, LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )


def _scope_shape(scope) -> tuple:
    return (
        scope.scope_ref,
        tuple(goal.goal_ref for goal in scope.goals),
        tuple(_scope_shape(child) for child in scope.children),
    )


def test_approved_scope_content_assembles_recursive_lesson_ir(snapshot) -> None:
    projection, validator = _projection_and_validator(snapshot)
    validation = validator.validate_payload(
        json.loads((B3 / "scope-content.json").read_text(encoding="utf-8"))
    )

    assert validation.direct_acceptance
    assert not validation.independent_material_merge_repaired

    result = RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validation,
    )

    assert result.lesson.schema_version == LESSON_IR_CONTRACT
    assert len(result.lesson.steps) == 12
    assert len(result.lesson.traversal.scope_by_ref) == 5
    assert len(result.lesson.traversal.goal_by_ref) == 4
    assert _scope_shape(result.lesson.root_scope) == _scope_shape(snapshot.root_scope)
    assert result.lesson.to_payload() == lesson_ir_from_payload(
        result.lesson.to_payload()
    ).to_payload()
    assert "steps" not in {
        key for key in result.lesson.to_payload() if key != "root_scope"
    }
    assert "sections" not in result.lesson.to_payload()
    assert "trace_refs" not in json.dumps(
        result.lesson.to_payload(), ensure_ascii=False
    )

    macro_steps = [
        row
        for row in result.lesson.steps
        if "derive_path_minimum_ii" in row.source_step_ids
    ]
    assert len(macro_steps) == 2
    assert [len(row.teaching_unit_keys) for row in macro_steps] == [1, 1]
    assert all(
        row.lesson_step_id.startswith("teach:derive_path_minimum_ii:")
        for row in macro_steps
    )


def test_deterministic_fallback_uses_same_assembler(snapshot) -> None:
    projection, validator = _projection_and_validator(snapshot)
    validation = validator.validate_payload(validator.deterministic_fallback)
    result = RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validation,
    )

    assert len(result.lesson.steps) == 13
    macro_steps = [
        row
        for row in result.lesson.steps
        if "derive_path_minimum_ii" in row.source_step_ids
    ]
    assert len(macro_steps) == 2
    assert all(
        row.lesson_step_id.startswith("teach:derive_path_minimum_ii:")
        for row in macro_steps
    )


def test_recursive_lesson_drives_existing_visual_and_page_compiler(snapshot) -> None:
    projection, validator = _projection_and_validator(snapshot)
    validation = validator.validate_payload(
        json.loads((B3 / "scope-content.json").read_text(encoding="utf-8"))
    )
    lesson = RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validation,
    ).lesson

    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir, lesson=lesson)
    compiled = forward_compile(visual_ir)

    assert len(visual_ir.steps) == len(lesson.steps) == 12
    assert len(compiled.lesson_data["steps"]) == 12
    assert set(compiled.step_decorations["steps"]) == {
        row.lesson_step_id for row in lesson.steps
    }


def test_ids_are_independent_of_authored_wording(snapshot) -> None:
    projection, validator = _projection_and_validator(snapshot)
    payload = json.loads((B3 / "scope-content.json").read_text(encoding="utf-8"))
    first = RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validator.validate_payload(payload),
    ).lesson
    payload["i"]["steps"][0]["title"] += "（润色）"
    second = RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validator.validate_payload(payload),
    ).lesson

    assert [row.id for row in first.steps] == [row.id for row in second.steps]
    assert first.to_payload() != second.to_payload()


def test_parser_rejects_old_flat_contract(snapshot) -> None:
    with pytest.raises(LessonIRValidationError):
        lesson_ir_from_payload(
            {
                "schema_version": "lesson-ir/v1",
                "problem_id": snapshot.problem_id,
                "family_id": snapshot.family_id,
                "sections": [],
                "steps": [],
            }
        )


def test_checked_in_schema_accepts_recursive_payload_and_rejects_flat(
    snapshot,
) -> None:
    projection, validator = _projection_and_validator(snapshot)
    lesson = RecursiveLessonIRAssembler().assemble(
        snapshot,
        projection,
        validator.validate_payload(validator.deterministic_fallback),
    ).lesson
    schema = json.loads(
        (ROOT / "internal/schemas/lesson-ir.schema.json").read_text(
            encoding="utf-8"
        )
    )
    checked = Draft202012Validator(schema)

    assert list(checked.iter_errors(lesson.to_payload())) == []
    assert list(
        checked.iter_errors(
            {
                "schema_version": "lesson-ir/v1",
                "problem_id": snapshot.problem_id,
                "sections": [],
                "steps": [],
            }
        )
    )


def test_historical_b2_request_retains_its_reviewed_identity():
    from hashlib import sha256

    messages = [{"role": role, "content": (B2 / f"prompt.{role}.md").read_text().removesuffix("\n")}
                for role in ("system", "user")]
    digest = sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":")).encode()).hexdigest()
    assert digest == REVIEWED_PROMPT_HASH


def test_visual_boundary_contract_preserves_reviewed_materials(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    schema = lesson_scope_content_schema(projection.plan)
    prompt = render_annotated_teaching_prompt(
        projection.plan,
        authority=projection.authority,
        output_schema=schema,
    )
    audit = build_projection_audit(
        projection,
        prompt=prompt,
        output_schema=schema,
    )

    assert audit["status"] == "ready_for_human_review"
    assert "shared-v1.jinja" in {asset["id"] for asset in audit["prompt_assets"]}
    assert "必须独立的教学材料" in prompt.user
    assert projection.plan.to_payload() == json.loads(
        (B2 / "annotated-teaching-plan.json").read_text(encoding="utf-8")
    )
    assert schema == json.loads(
        (B2 / "output-schema.json").read_text(encoding="utf-8")
    )
