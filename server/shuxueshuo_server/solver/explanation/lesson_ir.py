"""F5-F5B4 recursive, owner-preserving LessonIR.

The LLM never authors this structure.  B3 validates one Scope-owned response
and binds every returned row to canonical teaching materials; this module then
copies the Snapshot topology and commits the accepted rows atomically.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Iterator, Mapping, Sequence

from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)

from .annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    AnnotatedTeachingProjection,
)
from .models import (
    ExplanationSnapshot,
    TeachingScope,
    explanation_snapshot_content_hash,
)
from .scope_lesson import (
    BoundLessonStep,
    LessonScopeContentValidator,
    ScopeLessonAuthoringService,
    ScopeLessonGenerationResult,
    ScopeLessonValidationResult,
    answer_display_is_covered,
)


LESSON_IR_CONTRACT = "lesson-ir/v2"
LESSON_ASSEMBLY_AUTHORITY_CONTRACT = "lesson-assembly-authority/v1"


class LessonIRValidationError(ValueError):
    """A recursive LessonIR or its assembly authority is inconsistent."""


@dataclass(frozen=True)
class LessonStep:
    """One student-facing step; ownership comes only from its tree container."""

    lesson_step_id: str
    source_step_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    teaching_unit_keys: tuple[str, ...]
    title: str
    nav_title: str
    goal: str
    derive: tuple[tuple[str, str], ...]
    box: tuple[str, ...]

    @property
    def id(self) -> str:
        """Derived spelling used by the pre-G1 VisualStepIR implementation."""

        return self.lesson_step_id

    @property
    def visual_unit_ids(self) -> tuple[str, ...]:
        """Derived unit tails consumed by the pre-G1 visual adapter."""

        return tuple(key.rsplit("/", 1)[-1] for key in self.teaching_unit_keys)

    def to_payload(self) -> dict[str, Any]:
        return {
            "lesson_step_id": self.lesson_step_id,
            "source_step_ids": list(self.source_step_ids),
            "capability_ids": list(self.capability_ids),
            "teaching_unit_keys": list(self.teaching_unit_keys),
            "title": self.title,
            "nav_title": self.nav_title,
            "goal": self.goal,
            "derive": [list(item) for item in self.derive],
            "box": list(self.box),
        }


@dataclass(frozen=True)
class LessonGoal:
    goal_ref: str
    steps: tuple[LessonStep, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {"steps": [step.to_payload() for step in self.steps]}


@dataclass(frozen=True)
class LessonScope:
    scope_ref: str
    steps: tuple[LessonStep, ...] = ()
    goals: tuple[LessonGoal, ...] = ()
    children: tuple["LessonScope", ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_ref": self.scope_ref,
            "steps": [step.to_payload() for step in self.steps],
            "goals": {
                goal.goal_ref: goal.to_payload()
                for goal in self.goals
            },
            "children": [child.to_payload() for child in self.children],
        }


@dataclass(frozen=True)
class OwnedLessonStep:
    """Read-only flat view for consumers not yet recursive before G1."""

    step: LessonStep
    scope_ref: str
    goal_ref: str | None

    @property
    def id(self) -> str:
        return self.step.lesson_step_id

    @property
    def lesson_step_id(self) -> str:
        return self.step.lesson_step_id

    @property
    def scope_id(self) -> str:
        return self.scope_ref

    @property
    def source_step_ids(self) -> tuple[str, ...]:
        return self.step.source_step_ids

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return self.step.capability_ids

    @property
    def teaching_unit_keys(self) -> tuple[str, ...]:
        return self.step.teaching_unit_keys

    @property
    def visual_unit_ids(self) -> tuple[str, ...]:
        return self.step.visual_unit_ids

    @property
    def title(self) -> str:
        return self.step.title

    @property
    def nav_title(self) -> str:
        return self.step.nav_title

    @property
    def goal(self) -> str:
        return self.step.goal

    @property
    def derive(self) -> tuple[tuple[str, str], ...]:
        return self.step.derive

    @property
    def box(self) -> tuple[str, ...]:
        return self.step.box


@dataclass(frozen=True)
class LessonSectionView:
    scope_id: str
    title: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class LessonTraversalIndex:
    preorder_steps: tuple[OwnedLessonStep, ...]
    lesson_step_by_id: Mapping[str, OwnedLessonStep]
    lesson_step_owner_by_id: Mapping[str, tuple[str, str | None]]
    scope_by_ref: Mapping[str, LessonScope]
    goal_by_ref: Mapping[str, LessonGoal]
    derived_sections: tuple[LessonSectionView, ...]

    @classmethod
    def build(cls, root: LessonScope) -> "LessonTraversalIndex":
        rows: list[OwnedLessonStep] = []
        scopes: dict[str, LessonScope] = {}
        goals: dict[str, LessonGoal] = {}
        section_steps: dict[str, list[str]] = {}

        def visit(scope: LessonScope) -> None:
            if scope.scope_ref in scopes:
                raise LessonIRValidationError(
                    f"lesson_scope_duplicated: {scope.scope_ref}"
                )
            scopes[scope.scope_ref] = scope
            section_steps.setdefault(scope.scope_ref, [])
            for step in scope.steps:
                row = OwnedLessonStep(step, scope.scope_ref, None)
                rows.append(row)
                section_steps[scope.scope_ref].append(step.lesson_step_id)
            for goal in scope.goals:
                if goal.goal_ref in goals:
                    raise LessonIRValidationError(
                        f"lesson_goal_duplicated: {goal.goal_ref}"
                    )
                goals[goal.goal_ref] = goal
                for step in goal.steps:
                    row = OwnedLessonStep(step, scope.scope_ref, goal.goal_ref)
                    rows.append(row)
                    section_steps[scope.scope_ref].append(step.lesson_step_id)
            for child in scope.children:
                visit(child)

        visit(root)
        by_id = {row.id: row for row in rows}
        if len(by_id) != len(rows):
            raise LessonIRValidationError("lesson_step_id_duplicated")
        owners = {
            row.id: (row.scope_ref, row.goal_ref)
            for row in rows
        }
        sections = tuple(
            LessonSectionView(
                scope_id=scope_ref,
                title=scope_ref,
                steps=tuple(step_ids),
            )
            for scope_ref, step_ids in section_steps.items()
            if step_ids
        )
        return cls(
            preorder_steps=tuple(rows),
            lesson_step_by_id=by_id,
            lesson_step_owner_by_id=owners,
            scope_by_ref=scopes,
            goal_by_ref=goals,
            derived_sections=sections,
        )


@dataclass(frozen=True)
class LessonIR:
    problem_id: str
    problem_revision: str
    source_snapshot_hash: str
    root_scope: LessonScope
    schema_version: str = LESSON_IR_CONTRACT

    def __post_init__(self) -> None:
        if self.schema_version != LESSON_IR_CONTRACT:
            raise LessonIRValidationError(
                f"lesson_ir_schema_version_invalid: {self.schema_version}"
            )
        if not self.problem_id or not self.problem_revision:
            raise LessonIRValidationError("lesson_ir_identity_missing")
        if re.fullmatch(r"[0-9a-f]{64}", self.source_snapshot_hash) is None:
            raise LessonIRValidationError("lesson_ir_snapshot_hash_invalid")
        LessonTraversalIndex.build(self.root_scope)

    @property
    def traversal(self) -> LessonTraversalIndex:
        return LessonTraversalIndex.build(self.root_scope)

    @property
    def steps(self) -> tuple[OwnedLessonStep, ...]:
        """Temporary derived view; it is absent from ``to_payload``."""

        return self.traversal.preorder_steps

    @property
    def sections(self) -> tuple[LessonSectionView, ...]:
        """Temporary derived view for the existing page shell."""

        return self.traversal.derived_sections

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "problem_id": self.problem_id,
            "problem_revision": self.problem_revision,
            "source_snapshot_hash": self.source_snapshot_hash,
            "root_scope": self.root_scope.to_payload(),
        }


@dataclass(frozen=True)
class RecursiveLessonBuildResult:
    lesson: LessonIR
    assembly_authority: Mapping[str, Any]
    projection: AnnotatedTeachingProjection
    validation: ScopeLessonValidationResult
    generation: ScopeLessonGenerationResult | None = None


class RecursiveLessonIRAssembler:
    """Atomically assemble B3 bound rows into the Snapshot topology."""

    def assemble(
        self,
        snapshot: ExplanationSnapshot,
        projection: AnnotatedTeachingProjection,
        validation: ScopeLessonValidationResult,
        *,
        generation: ScopeLessonGenerationResult | None = None,
    ) -> RecursiveLessonBuildResult:
        snapshot_hash = explanation_snapshot_content_hash(snapshot)
        if projection.authority.get("snapshot_hash") != snapshot_hash:
            raise LessonIRValidationError("lesson_assembly_snapshot_hash_drift")
        expected_containers = projection.authority.get("containers")
        if not isinstance(expected_containers, Mapping):
            raise LessonIRValidationError("lesson_assembly_authority_invalid")
        if set(validation.bound_steps) != set(expected_containers):
            raise LessonIRValidationError(
                "lesson_assembly_container_coverage_invalid: "
                f"expected={sorted(expected_containers)}, "
                f"observed={sorted(validation.bound_steps)}"
            )

        authority_steps: dict[str, Any] = {}
        used_ids: set[str] = set()

        def build_steps(container_ref: str) -> tuple[LessonStep, ...]:
            rows = validation.bound_steps.get(container_ref, ())
            records = expected_containers.get(container_ref, ())
            if not isinstance(records, Sequence) or isinstance(records, str | bytes):
                raise LessonIRValidationError(
                    f"lesson_assembly_container_authority_invalid: {container_ref}"
                )
            result: list[LessonStep] = []
            consumed_positions: list[int] = []
            for row in rows:
                _validate_bound_row(
                    container_ref=container_ref,
                    row=row,
                    records=records,
                )
                consumed_positions.extend(row.material_positions)
                lesson_step_id = _lesson_step_id(
                    container_ref=container_ref,
                    row=row,
                    records=records,
                )
                if lesson_step_id in used_ids:
                    raise LessonIRValidationError(
                        f"lesson_step_id_duplicated: {lesson_step_id}"
                    )
                used_ids.add(lesson_step_id)
                step = LessonStep(
                    lesson_step_id=lesson_step_id,
                    source_step_ids=tuple(row.source_step_ids),
                    capability_ids=tuple(row.capability_ids),
                    teaching_unit_keys=tuple(row.unit_keys),
                    title=row.title,
                    nav_title=row.nav_title,
                    goal=row.goal,
                    derive=tuple(row.derive),
                    box=tuple(row.box),
                )
                result.append(step)
                authority_steps[lesson_step_id] = {
                    "container_ref": container_ref,
                    "material_positions": list(row.material_positions),
                    "source_step_ids": list(row.source_step_ids),
                    "capability_ids": list(row.capability_ids),
                    "unit_keys": list(row.unit_keys),
                    "evidence_refs": list(row.evidence_refs),
                }
            expected_positions = list(range(len(records)))
            if consumed_positions != expected_positions:
                raise LessonIRValidationError(
                    "lesson_assembly_material_coverage_invalid: "
                    f"{container_ref}: expected={expected_positions}, "
                    f"observed={consumed_positions}"
                )
            return tuple(result)

        def build_scope(source: TeachingScope) -> LessonScope:
            return LessonScope(
                scope_ref=source.scope_ref,
                steps=build_steps(f"scope:{source.scope_ref}"),
                goals=tuple(
                    LessonGoal(
                        goal_ref=goal.goal_ref,
                        steps=build_steps(f"goal:{goal.goal_ref}"),
                    )
                    for goal in source.goals
                ),
                children=tuple(build_scope(child) for child in source.children),
            )

        lesson = LessonIR(
            problem_id=snapshot.problem_id,
            problem_revision=snapshot.problem_revision,
            source_snapshot_hash=snapshot_hash,
            root_scope=build_scope(snapshot.root_scope),
        )
        lesson_hash = _stable_hash(lesson.to_payload())
        authority = {
            "schema_version": LESSON_ASSEMBLY_AUTHORITY_CONTRACT,
            "snapshot_hash": snapshot_hash,
            "annotated_plan_hash": projection.authority.get(
                "annotated_plan_hash"
            ),
            "lesson_ir_hash": lesson_hash,
            "lesson_steps": authority_steps,
        }
        RecursiveLessonIRValidator().validate(
            lesson,
            snapshot=snapshot,
            projection=projection,
            validation=validation,
            assembly_authority=authority,
        )
        _validate_b3_result_is_canonical(projection, validation)
        return RecursiveLessonBuildResult(
            lesson=lesson,
            assembly_authority=authority,
            projection=projection,
            validation=validation,
            generation=generation,
        )


class RecursiveLessonIRValidator:
    def validate(
        self,
        lesson: LessonIR,
        *,
        snapshot: ExplanationSnapshot,
        projection: AnnotatedTeachingProjection,
        validation: ScopeLessonValidationResult,
        assembly_authority: Mapping[str, Any],
    ) -> None:
        snapshot_hash = explanation_snapshot_content_hash(snapshot)
        if lesson.problem_id != snapshot.problem_id:
            raise LessonIRValidationError("lesson_ir_problem_id_mismatch")
        if lesson.problem_revision != snapshot.problem_revision:
            raise LessonIRValidationError("lesson_ir_problem_revision_mismatch")
        if lesson.source_snapshot_hash != snapshot_hash:
            raise LessonIRValidationError("lesson_ir_snapshot_hash_mismatch")
        _validate_topology(lesson.root_scope, snapshot.root_scope)
        traversal = lesson.traversal
        expected_rows = sum(len(rows) for rows in validation.bound_steps.values())
        if len(traversal.preorder_steps) != expected_rows:
            raise LessonIRValidationError("lesson_ir_step_count_mismatch")
        if set(assembly_authority.get("lesson_steps", {})) != set(
            traversal.lesson_step_by_id
        ):
            raise LessonIRValidationError("lesson_ir_authority_step_ids_mismatch")
        if assembly_authority.get("snapshot_hash") != snapshot_hash:
            raise LessonIRValidationError("lesson_ir_authority_snapshot_mismatch")
        if assembly_authority.get("lesson_ir_hash") != _stable_hash(
            lesson.to_payload()
        ):
            raise LessonIRValidationError("lesson_ir_authority_hash_mismatch")
        if contains_private_path_projection_marker(lesson.to_payload()):
            raise LessonIRValidationError("lesson_ir_private_identity_leak")
        restored = lesson_ir_from_payload(lesson.to_payload())
        if restored.to_payload() != lesson.to_payload():
            raise LessonIRValidationError("lesson_ir_round_trip_mismatch")
        _validate_answer_producers(lesson, snapshot, projection)


class LessonAuthoringPipeline:
    """Production B4 entry: B3 authoring/fallback followed by one assembler."""

    def __init__(
        self,
        *,
        authoring_service: ScopeLessonAuthoringService | None = None,
    ) -> None:
        self.authoring_service = authoring_service

    def build(self, snapshot: ExplanationSnapshot) -> RecursiveLessonBuildResult:
        if self.authoring_service is not None:
            generation = self.authoring_service.generate(snapshot)
            return RecursiveLessonIRAssembler().assemble(
                snapshot,
                generation.projection,
                generation.validation,
                generation=generation,
            )
        projection = AnnotatedTeachingPlanProjector().project(snapshot)
        validator = LessonScopeContentValidator(
            plan=projection.plan,
            authority=projection.authority,
        )
        validation = validator.validate_payload(validator.deterministic_fallback)
        if validation.fallback_used:
            # This is an intentional deterministic authoring mode, not a rejected
            # LLM body.  The bound result is nevertheless identical to B3 fallback.
            pass
        return RecursiveLessonIRAssembler().assemble(
            snapshot,
            projection,
            validation,
        )


def lesson_ir_from_payload(payload: Mapping[str, Any]) -> LessonIR:
    """Strictly hydrate only the recursive v2 contract."""

    _require_keys(
        payload,
        {
            "schema_version",
            "problem_id",
            "problem_revision",
            "source_snapshot_hash",
            "root_scope",
        },
        "$",
    )
    if payload.get("schema_version") != LESSON_IR_CONTRACT:
        raise LessonIRValidationError("lesson_ir_schema_version_invalid")
    return LessonIR(
        schema_version=str(payload["schema_version"]),
        problem_id=str(payload["problem_id"]),
        problem_revision=str(payload["problem_revision"]),
        source_snapshot_hash=str(payload["source_snapshot_hash"]),
        root_scope=_scope_from_payload(payload["root_scope"], path="$.root_scope"),
    )


def _scope_from_payload(raw: Any, *, path: str) -> LessonScope:
    if not isinstance(raw, Mapping):
        raise LessonIRValidationError(f"lesson_scope_invalid: {path}")
    _require_keys(raw, {"scope_ref", "steps", "goals", "children"}, path)
    goals = raw["goals"]
    if not isinstance(goals, Mapping):
        raise LessonIRValidationError(f"lesson_goals_invalid: {path}.goals")
    return LessonScope(
        scope_ref=_nonempty_string(raw["scope_ref"], f"{path}.scope_ref"),
        steps=_steps_from_payload(raw["steps"], path=f"{path}.steps"),
        goals=tuple(
            _goal_from_payload(goal_ref, value, path=f"{path}.goals[{goal_ref!r}]")
            for goal_ref, value in goals.items()
        ),
        children=tuple(
            _scope_from_payload(value, path=f"{path}.children[{index}]")
            for index, value in enumerate(_array(raw["children"], f"{path}.children"))
        ),
    )


def _goal_from_payload(goal_ref: Any, raw: Any, *, path: str) -> LessonGoal:
    if not isinstance(raw, Mapping):
        raise LessonIRValidationError(f"lesson_goal_invalid: {path}")
    _require_keys(raw, {"steps"}, path)
    return LessonGoal(
        goal_ref=_nonempty_string(goal_ref, f"{path}.goal_ref"),
        steps=_steps_from_payload(raw["steps"], path=f"{path}.steps"),
    )


def _steps_from_payload(raw: Any, *, path: str) -> tuple[LessonStep, ...]:
    return tuple(
        _step_from_payload(value, path=f"{path}[{index}]")
        for index, value in enumerate(_array(raw, path))
    )


def _step_from_payload(raw: Any, *, path: str) -> LessonStep:
    if not isinstance(raw, Mapping):
        raise LessonIRValidationError(f"lesson_step_invalid: {path}")
    _require_keys(
        raw,
        {
            "lesson_step_id",
            "source_step_ids",
            "capability_ids",
            "teaching_unit_keys",
            "title",
            "nav_title",
            "goal",
            "derive",
            "box",
        },
        path,
    )
    derive: list[tuple[str, str]] = []
    for index, pair in enumerate(_array(raw["derive"], f"{path}.derive")):
        if not isinstance(pair, Sequence) or isinstance(pair, str | bytes) or len(pair) != 2:
            raise LessonIRValidationError(
                f"lesson_step_derive_invalid: {path}.derive[{index}]"
            )
        derive.append(
            (
                _nonempty_string(pair[0], f"{path}.derive[{index}][0]"),
                _nonempty_string(pair[1], f"{path}.derive[{index}][1]"),
            )
        )
    return LessonStep(
        lesson_step_id=_nonempty_string(raw["lesson_step_id"], f"{path}.lesson_step_id"),
        source_step_ids=_string_tuple(raw["source_step_ids"], f"{path}.source_step_ids"),
        capability_ids=_string_tuple(raw["capability_ids"], f"{path}.capability_ids"),
        teaching_unit_keys=_string_tuple(
            raw["teaching_unit_keys"],
            f"{path}.teaching_unit_keys",
            allow_duplicates=True,
        ),
        title=_nonempty_string(raw["title"], f"{path}.title"),
        nav_title=_nonempty_string(raw["nav_title"], f"{path}.nav_title"),
        goal=_nonempty_string(raw["goal"], f"{path}.goal"),
        derive=tuple(derive),
        box=_string_tuple(raw["box"], f"{path}.box", allow_empty=True),
    )


def _lesson_step_id(
    *,
    container_ref: str,
    row: BoundLessonStep,
    records: Sequence[Any],
) -> str:
    selected: list[Mapping[str, Any]] = []
    for position in row.material_positions:
        if position < 0 or position >= len(records) or not isinstance(records[position], Mapping):
            raise LessonIRValidationError(
                f"lesson_assembly_material_position_invalid: {container_ref}[{position}]"
            )
        selected.append(records[position])
    if len(selected) == 1:
        record = selected[0]
        source_step_id = str(record.get("source_step_id") or "")
        unit_key = str(record.get("unit_key") or "")
        kind = str(record.get("capability_kind") or "")
        if not source_step_id or not unit_key or kind not in {"function", "macro"}:
            raise LessonIRValidationError(
                f"lesson_assembly_material_authority_invalid: {container_ref}"
            )
        if kind == "function":
            return f"teach:{source_step_id}"
        return f"teach:{source_step_id}:{unit_key}"
    signature = {
        "container_ref": container_ref,
        "materials": [
            {
                "position": int(record.get("position", -1)),
                "source_step_id": str(record.get("source_step_id") or ""),
                "unit_key": str(record.get("unit_key") or ""),
            }
            for record in selected
        ],
    }
    return f"teach:group:{_stable_hash(signature)[:16]}"


def _validate_bound_row(
    *,
    container_ref: str,
    row: BoundLessonStep,
    records: Sequence[Any],
) -> None:
    """Re-establish B3 material authority before committing LessonIR.

    ``ScopeLessonValidationResult`` is an internal value, but B4 must not trust
    a stale or accidentally modified instance.  Every public provenance field
    is therefore derived again from the selected B2 authority records.
    """

    if not isinstance(row, BoundLessonStep):
        raise LessonIRValidationError(
            f"lesson_assembly_bound_row_invalid: {container_ref}"
        )
    if row.container_ref != container_ref:
        raise LessonIRValidationError(
            "lesson_assembly_owner_drift: "
            f"expected={container_ref}, observed={row.container_ref}"
        )
    positions = row.material_positions
    if not positions:
        raise LessonIRValidationError(
            f"lesson_assembly_material_span_empty: {container_ref}"
        )
    expected_span = tuple(range(positions[0], positions[0] + len(positions)))
    if positions != expected_span:
        raise LessonIRValidationError(
            "lesson_assembly_material_span_invalid: "
            f"{container_ref}: observed={list(positions)}"
        )

    selected: list[Mapping[str, Any]] = []
    for position in positions:
        if position < 0 or position >= len(records):
            raise LessonIRValidationError(
                f"lesson_assembly_material_position_invalid: "
                f"{container_ref}[{position}]"
            )
        record = records[position]
        if not isinstance(record, Mapping):
            raise LessonIRValidationError(
                f"lesson_assembly_material_authority_invalid: "
                f"{container_ref}[{position}]"
            )
        if record.get("position") != position:
            raise LessonIRValidationError(
                f"lesson_assembly_material_authority_position_drift: "
                f"{container_ref}[{position}]"
            )
        if not isinstance(record.get("requires_independent_lesson_step"), bool):
            raise LessonIRValidationError(
                "lesson_assembly_independent_material_authority_invalid: "
                f"{container_ref}[{position}]"
            )
        selected.append(record)

    if len(selected) > 1 and any(
        record["requires_independent_lesson_step"] for record in selected
    ):
        independent_refs = [
            str(record.get("teaching_step_ref") or "")
            for record in selected
            if record["requires_independent_lesson_step"]
        ]
        raise LessonIRValidationError(
            "lesson_assembly_independent_material_merge_forbidden: "
            f"{container_ref}: {independent_refs}"
        )

    expected_refs = tuple(str(item.get("teaching_step_ref") or "") for item in selected)
    expected_sources = _ordered_unique(
        str(item.get("source_step_id") or "") for item in selected
    )
    expected_capabilities = _ordered_unique(
        str(item.get("capability_id") or "") for item in selected
    )
    expected_units = tuple(str(item.get("unit_key") or "") for item in selected)
    expected_evidence = _ordered_unique(
        str(ref)
        for item in selected
        for ref in item.get("evidence_refs", ())
    )
    observed = {
        "teaching_step_refs": row.teaching_step_refs,
        "source_step_ids": row.source_step_ids,
        "capability_ids": row.capability_ids,
        "unit_keys": row.unit_keys,
        "evidence_refs": row.evidence_refs,
    }
    expected = {
        "teaching_step_refs": expected_refs,
        "source_step_ids": expected_sources,
        "capability_ids": expected_capabilities,
        "unit_keys": expected_units,
        "evidence_refs": expected_evidence,
    }
    required_provenance = (
        expected_refs,
        expected_sources,
        expected_capabilities,
        expected_units,
    )
    if any(
        not value or any(not item for item in value)
        for value in required_provenance
    ) or any(not item for item in expected_evidence):
        raise LessonIRValidationError(
            f"lesson_assembly_material_authority_invalid: {container_ref}"
        )
    if observed != expected:
        raise LessonIRValidationError(
            "lesson_assembly_provenance_drift: "
            f"{container_ref}: expected={expected}, observed={observed}"
        )


def _validate_topology(lesson: LessonScope, source: TeachingScope) -> None:
    if lesson.scope_ref != source.scope_ref:
        raise LessonIRValidationError("lesson_ir_scope_topology_mismatch")
    if tuple(goal.goal_ref for goal in lesson.goals) != tuple(
        goal.goal_ref for goal in source.goals
    ):
        raise LessonIRValidationError(
            f"lesson_ir_goal_topology_mismatch: {source.scope_ref}"
        )
    if len(lesson.children) != len(source.children):
        raise LessonIRValidationError(
            f"lesson_ir_child_topology_mismatch: {source.scope_ref}"
        )
    for child, source_child in zip(lesson.children, source.children, strict=True):
        _validate_topology(child, source_child)


def _validate_answer_producers(
    lesson: LessonIR,
    snapshot: ExplanationSnapshot,
    projection: AnnotatedTeachingProjection,
) -> None:
    traversal = lesson.traversal

    def visit(scope: TeachingScope) -> Iterator[Any]:
        yield from scope.goals
        for child in scope.children:
            yield from visit(child)

    for goal in visit(snapshot.root_scope):
        producer = str(goal.answer_from.get("step_id") or "")
        if not producer:
            raise LessonIRValidationError(
                f"lesson_ir_answer_from_invalid: {goal.goal_ref}"
            )
        if goal.goal_ref not in traversal.goal_by_ref:
            raise LessonIRValidationError(
                f"lesson_ir_answer_goal_missing: {goal.goal_ref}"
            )
        producer_steps = [
            row.step
            for row in traversal.preorder_steps
            if producer in row.source_step_ids
        ]
        answer = projection.plan.answers.get(goal.goal_ref)
        display = (
            str(answer.get("display") or "")
            if isinstance(answer, Mapping)
            else ""
        )
        matching_boxes = [
            step
            for step in producer_steps
            if step.box
            and answer_display_is_covered(display, "\n".join(step.box))
        ]
        if not display or len(matching_boxes) != 1:
            raise LessonIRValidationError(
                "lesson_ir_answer_producer_missing: "
                f"{goal.goal_ref}: producer={producer}, answer={display!r}, "
                f"matching_steps={len(matching_boxes)}"
            )


def _validate_b3_result_is_canonical(
    projection: AnnotatedTeachingProjection,
    validation: ScopeLessonValidationResult,
) -> None:
    """Reject a stale or mutated B3 validation object.

    Revalidating the already accepted body is deterministic and performs the
    complete B3 text/object/future-result authority audit without exposing a
    second public contract.  Scope fallback provenance may differ on this
    replay, but the accepted body and all bound rows must be byte-equivalent.
    """

    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    replayed = validator.validate_payload(
        _scope_content_wire_payload(validation.accepted_content)
    )
    if (
        replayed.accepted_content != validation.accepted_content
        or replayed.bound_steps != validation.bound_steps
    ):
        raise LessonIRValidationError("lesson_assembly_b3_validation_drift")


def _scope_content_wire_payload(
    accepted_content: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Remove only B3's deterministic ``box`` injection before replay.

    The compact LLM contract deliberately has no ``box`` field.  B3 appends
    verified conclusions to its accepted internal body, so those conclusions
    must be removed to reconstruct the exact validator input shape.
    """

    def strip_steps(raw: Any) -> Any:
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
            return raw
        result: list[Any] = []
        for item in raw:
            if not isinstance(item, Mapping):
                result.append(item)
                continue
            normalized = dict(item)
            normalized.pop("box", None)
            derive = normalized.get("derive")
            if (
                isinstance(derive, Sequence)
                and not isinstance(derive, str | bytes)
                and all(
                    isinstance(pair, Sequence)
                    and not isinstance(pair, str | bytes)
                    and len(pair) == 2
                    for pair in derive
                )
            ):
                normalized["derive"] = [
                    f"{pair[0]} {pair[1]}" for pair in derive
                ]
            result.append(normalized)
        return result

    payload: dict[str, Any] = {}
    for scope_ref, raw_body in accepted_content.items():
        if not isinstance(raw_body, Mapping):
            payload[str(scope_ref)] = raw_body
            continue
        body = dict(raw_body)
        if "steps" in body:
            body["steps"] = strip_steps(body["steps"])
        goals = body.get("goals")
        if isinstance(goals, Mapping):
            body["goals"] = {
                str(goal_ref): strip_steps(raw_steps)
                for goal_ref, raw_steps in goals.items()
            }
        payload[str(scope_ref)] = body
    return payload


def _require_keys(raw: Mapping[str, Any], expected: set[str], path: str) -> None:
    if set(raw) != expected:
        raise LessonIRValidationError(
            f"lesson_ir_fields_invalid: {path}: "
            f"expected={sorted(expected)}, observed={sorted(raw)}"
        )


def _array(raw: Any, path: str) -> Sequence[Any]:
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise LessonIRValidationError(f"lesson_ir_array_invalid: {path}")
    return raw


def _nonempty_string(raw: Any, path: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise LessonIRValidationError(f"lesson_ir_string_invalid: {path}")
    return raw


def _string_tuple(
    raw: Any,
    path: str,
    *,
    allow_empty: bool = False,
    allow_duplicates: bool = False,
) -> tuple[str, ...]:
    values = tuple(
        _nonempty_string(value, f"{path}[{index}]")
        for index, value in enumerate(_array(raw, path))
    )
    if not allow_empty and not values:
        raise LessonIRValidationError(f"lesson_ir_array_empty: {path}")
    if not allow_duplicates and len(values) != len(set(values)):
        raise LessonIRValidationError(f"lesson_ir_array_duplicates: {path}")
    return values


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _stable_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "LESSON_ASSEMBLY_AUTHORITY_CONTRACT",
    "LESSON_IR_CONTRACT",
    "LessonAuthoringPipeline",
    "LessonGoal",
    "LessonIR",
    "LessonIRValidationError",
    "LessonScope",
    "LessonSectionView",
    "LessonStep",
    "LessonTraversalIndex",
    "OwnedLessonStep",
    "RecursiveLessonBuildResult",
    "RecursiveLessonIRAssembler",
    "RecursiveLessonIRValidator",
    "lesson_ir_from_payload",
]
