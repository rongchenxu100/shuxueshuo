from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonAuthoringPipeline,
    LessonIRValidationError,
    RecursiveLessonIRAssembler,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "server/tests/solver/fixtures/lesson_scope_authoring_vnext"


@pytest.fixture(scope="module")
def snapshot():
    return explanation_snapshot_from_payload(
        json.loads(
            (FIXTURES / "heping_ermo_b1/snapshot.json").read_text(
                encoding="utf-8"
            )
        )
    )


def test_pipeline_without_llm_assembles_valid_deterministic_tree(snapshot) -> None:
    result = LessonAuthoringPipeline().build(snapshot)
    assert len(result.lesson.steps) == 13
    assert result.generation is None
    assert result.lesson.source_snapshot_hash == result.assembly_authority["snapshot_hash"]


def test_assembler_rejects_projection_snapshot_hash_drift(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    validation = validator.validate_payload(validator.deterministic_fallback)
    bad_authority = dict(projection.authority)
    bad_authority["snapshot_hash"] = "0" * 64

    with pytest.raises(
        LessonIRValidationError,
        match="lesson_assembly_snapshot_hash_drift",
    ):
        RecursiveLessonIRAssembler().assemble(
            snapshot,
            replace(projection, authority=bad_authority),
            validation,
        )


def test_assembler_rejects_missing_bound_container(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    validation = validator.validate_payload(validator.deterministic_fallback)
    reduced = dict(validation.bound_steps)
    reduced.pop(next(iter(reduced)))

    with pytest.raises(
        LessonIRValidationError,
        match="lesson_assembly_container_coverage_invalid",
    ):
        RecursiveLessonIRAssembler().assemble(
            snapshot,
            projection,
            replace(validation, bound_steps=reduced),
        )


def test_assembler_rejects_bound_provenance_drift(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    validation = validator.validate_payload(validator.deterministic_fallback)
    bound = dict(validation.bound_steps)
    container_ref = "scope:i"
    rows = list(bound[container_ref])
    rows[0] = replace(rows[0], source_step_ids=("tampered_step",))
    bound[container_ref] = tuple(rows)

    with pytest.raises(
        LessonIRValidationError,
        match="lesson_assembly_provenance_drift",
    ):
        RecursiveLessonIRAssembler().assemble(
            snapshot,
            projection,
            replace(validation, bound_steps=bound),
        )


def test_assembler_rejects_material_coverage_drift(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    validation = validator.validate_payload(validator.deterministic_fallback)
    bound = dict(validation.bound_steps)
    bound["scope:i"] = bound["scope:i"][:1]

    with pytest.raises(
        LessonIRValidationError,
        match="lesson_assembly_material_coverage_invalid",
    ):
        RecursiveLessonIRAssembler().assemble(
            snapshot,
            projection,
            replace(validation, bound_steps=bound),
        )


def test_assembler_rejects_independent_material_merge(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    validation = validator.validate_payload(validator.deterministic_fallback)
    bound = dict(validation.bound_steps)
    rows = list(bound["goal:ii.E"])
    first, second = rows[1:3]
    rows[1:3] = [
        replace(
            first,
            material_positions=(1, 2),
            teaching_step_refs=(
                *first.teaching_step_refs,
                *second.teaching_step_refs,
            ),
            source_step_ids=first.source_step_ids,
            capability_ids=first.capability_ids,
            unit_keys=(*first.unit_keys, *second.unit_keys),
            evidence_refs=first.evidence_refs,
            box=(*first.box, *second.box),
        )
    ]
    bound["goal:ii.E"] = tuple(rows)

    with pytest.raises(
        LessonIRValidationError,
        match="lesson_assembly_independent_material_merge_forbidden",
    ):
        RecursiveLessonIRAssembler().assemble(
            snapshot,
            projection,
            replace(validation, bound_steps=bound),
        )


def test_assembler_rechecks_verified_answer_box(snapshot) -> None:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    validation = validator.validate_payload(validator.deterministic_fallback)
    bound = dict(validation.bound_steps)
    rows = list(bound["goal:i_1.P"])
    rows[0] = replace(rows[0], box=("与验算答案无关的结论",))
    bound["goal:i_1.P"] = tuple(rows)

    with pytest.raises(
        LessonIRValidationError,
        match="lesson_ir_answer_producer_missing",
    ):
        RecursiveLessonIRAssembler().assemble(
            snapshot,
            projection,
            replace(validation, bound_steps=bound),
        )
