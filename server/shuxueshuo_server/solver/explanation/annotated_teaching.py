"""F5-F5B2 annotated teaching input and final request projection.

This module is intentionally disconnected from the production Lesson builder.
It turns one verified ``ExplanationSnapshot`` into the exact student-safe input
that the B3 Lesson LLM will consume, plus an internal provenance authority used
only by validators and debug artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.contracts import TeachingUnitSpec
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)
from shuxueshuo_server.solver.student_display import (
    find_internal_math_tokens,
    student_math_display,
)

from .models import (
    ExplanationSnapshot,
    TeachingScope,
    TeachingSource,
    explanation_snapshot_content_hash,
    iter_teaching_scopes,
    iter_teaching_sources,
)
from .teaching_specs import (
    BoundTeachingSelection,
    BoundTeachingUnit,
    TeachingSeparationBoundaryResolver,
    TeachingSpecBinder,
    TeachingSpecBindingError,
)


ANNOTATED_TEACHING_PLAN_CONTRACT = "functional-annotated-teaching-plan/v1"
TEACHING_AUTHORITY_CONTRACT = "lesson-teaching-authority/v1"
LESSON_SCOPE_CONTENT_CONTRACT = "lesson-scope-content/v1"
PROJECTION_AUDIT_CONTRACT = "lesson-annotated-teaching-audit/v1"

DERIVE_MARKERS = ("作", "设", "∵", "∴", "计算")

FORBIDDEN_LLM_TOKENS = (
    "expected_answers",
    "ContextPath",
    "point:problem:",
    "segment:problem:",
    "function:problem:",
    "symbol:problem:",
    "fact:",
    "#quadratic-square-reflection",
    "PathTransformation",
    "StateVersion",
    "checkpoint",
    "replay trace",
    "symbolic closure",
    "_axis_param_",
    '"handle"',
    '"resolved_from"',
    '"output_targets"',
    '"return_expectations"',
    '"calculation_id"',
    '"check_id"',
    '"checks"',
    '"fact_id"',
    '"evidence_ref"',
    '"evidence_refs"',
    '"unit_key"',
    '"unit_id"',
    '"guide_id"',
    '"teaching_case"',
    '"variant_key"',
    '"teaching_variants"',
    '"cross_scope_references"',
    '"teaching_guides"',
    '"important_calculation_ids"',
    '"merge_policy"',
    '"must_separate"',
    '"scope_steps"',
    '"lesson_steps"',
    '"schema_version"',
    '"step_id"',
    '"capability_id"',
    '"intent"',
    '"ref"',
    '"required_answer"',
    '"answer_from"',
    '"runtime_type"',
    '"execution"',
    '"teaching_materials"',
    '"suggested_title"',
    '"suggested_nav_title"',
    '"suggested_goal"',
    '"suggested_derive"',
    '"suggested_box"',
    '"available_visuals"',
    '"material_count"',
    '"box"',
    '"visuals"',
)


class AnnotatedTeachingProjectionError(ValueError):
    """A complete student-safe teaching request cannot be constructed."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class TeachingProjectionDiagnostic:
    code: str
    step_id: str
    capability_id: str
    message: str
    fallback: str
    unit_key: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "step_id": self.step_id,
            "capability_id": self.capability_id,
            "message": self.message,
            "fallback": self.fallback,
        }
        if self.unit_key is not None:
            payload["unit_key"] = self.unit_key
        return payload


@dataclass(frozen=True)
class AnnotatedTeachingMaterial:
    suggested_title: str
    suggested_nav_title: str
    suggested_goal: str
    suggested_derive: tuple[tuple[str, str], ...]
    suggested_box: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "title": self.suggested_title,
            "nav_title": self.suggested_nav_title,
            "goal": self.suggested_goal,
            "derive": [
                f"{marker} {text}" for marker, text in self.suggested_derive
            ],
            "conclusions": list(self.suggested_box),
        }


@dataclass(frozen=True)
class AnnotatedTeachingStep:
    step_id: str
    capability_id: str
    intent: str | None
    inputs: Mapping[str, tuple[Mapping[str, Any], ...]]
    outputs: Mapping[str, Mapping[str, Any]]
    calculations: tuple[Mapping[str, Any], ...]
    teaching_materials: tuple[AnnotatedTeachingMaterial, ...]

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.inputs:
            payload["inputs"] = {
                name: [_json_clone(item) for item in items]
                for name, items in self.inputs.items()
            }
        if self.outputs:
            payload["outputs"] = {
                name: _json_clone(value) for name, value in self.outputs.items()
            }
        if self.calculations:
            payload["calculations"] = [
                _json_clone(item) for item in self.calculations
            ]
        payload["materials"] = [
            item.to_payload() for item in self.teaching_materials
        ]
        return payload


@dataclass(frozen=True)
class AnnotatedTeachingGoal:
    goal_ref: str
    required_answer: Mapping[str, str]
    steps: tuple[AnnotatedTeachingStep, ...]
    answer_from: Mapping[str, str]

    def to_payload(self) -> list[dict[str, Any]]:
        return _container_steps_payload(self.steps)


@dataclass(frozen=True)
class AnnotatedTeachingScope:
    scope_ref: str
    steps: tuple[AnnotatedTeachingStep, ...]
    goals: tuple[AnnotatedTeachingGoal, ...]
    children: tuple["AnnotatedTeachingScope", ...]

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"scope_ref": self.scope_ref}
        steps = _container_steps_payload(self.steps)
        if steps:
            payload["steps"] = steps
        goals = {
            goal.goal_ref: _container_steps_payload(goal.steps)
            for goal in self.goals
            if goal.steps
        }
        if goals:
            payload["goals"] = goals
        children = [
            item.to_payload()
            for item in self.children
            if _scope_has_materials(item)
        ]
        if children:
            payload["children"] = children
        return payload


def _container_steps_payload(
    steps: Sequence[AnnotatedTeachingStep],
) -> list[dict[str, Any]]:
    """Project local teaching-step refs without exposing canonical Step IDs.

    Refs restart inside every Scope/Goal container because grouping is only
    legal within that container.  A Macro may contribute more than one ref;
    the internal authority keeps both refs mapped to its one canonical Step.
    """

    result: list[dict[str, Any]] = []
    next_number = 1
    for step in steps:
        payload = step.to_payload()
        materials = []
        for material in payload["materials"]:
            materials.append(
                {
                    "step_ref": f"s{next_number}",
                    **material,
                }
            )
            next_number += 1
        payload["materials"] = materials
        result.append(payload)
    return result


@dataclass(frozen=True)
class AnnotatedTeachingPlan:
    problem: Mapping[str, Any]
    answers: Mapping[str, Mapping[str, Any]]
    root_scope: AnnotatedTeachingScope
    schema_version: str = ANNOTATED_TEACHING_PLAN_CONTRACT

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem": _json_clone(self.problem),
            "answers": {
                goal_ref: _json_clone(answer)
                for goal_ref, answer in self.answers.items()
            },
            "root_scope": self.root_scope.to_payload(),
        }


@dataclass(frozen=True)
class AnnotatedTeachingPrompt:
    system: str
    user: str

    @property
    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


@dataclass(frozen=True)
class AnnotatedTeachingProjection:
    plan: AnnotatedTeachingPlan
    authority: Mapping[str, Any]
    diagnostics: tuple[TeachingProjectionDiagnostic, ...]


@dataclass(frozen=True)
class _ProjectedMaterialSet:
    materials: tuple[AnnotatedTeachingMaterial, ...]
    kind: str
    unit_keys: tuple[str, ...]
    requires_independent_lesson_steps: tuple[bool, ...]
    variant_key: str | None
    evidence_match: Mapping[str, Any] | None
    diagnostics: tuple[TeachingProjectionDiagnostic, ...]


class TeachingMaterialProjector:
    """Bind B1 specs and expose only complete LLM-facing suggestions."""

    def __init__(
        self,
        *,
        binder: TeachingSpecBinder | None = None,
        separation_resolver: TeachingSeparationBoundaryResolver | None = None,
    ) -> None:
        self._binder = binder or TeachingSpecBinder()
        self._separation = (
            separation_resolver or TeachingSeparationBoundaryResolver()
        )

    def project(
        self,
        source: TeachingSource,
        *,
        snapshot: ExplanationSnapshot,
        calculations: tuple[Mapping[str, Any], ...],
        checks: tuple[Mapping[str, Any], ...],
    ) -> _ProjectedMaterialSet:
        # Classification is an authority invariant.  Unlike an incomplete
        # template, an unknown/double-registered capability cannot be hidden by
        # a generic teaching fallback.
        generic_spec = self._binder.generic_spec_payload(source)
        kind = str(generic_spec["kind"])
        diagnostics: list[TeachingProjectionDiagnostic] = []

        def fallback(
            unit: TeachingUnitSpec,
            error: TeachingSpecBindingError,
        ) -> BoundTeachingUnit:
            diagnostics.append(
                _binding_diagnostic(
                    source,
                    error,
                    unit_key=unit.unit_key,
                )
            )
            return _generic_bound_unit(
                source,
                unit_key=unit.unit_key,
                calculations=calculations,
                checks=checks,
            )

        try:
            selection = self._binder.bind_source_selection(
                source,
                snapshot=snapshot,
                on_unit_error=fallback,
            )
        except TeachingSpecBindingError as exc:
            diagnostics.append(_binding_diagnostic(source, exc))
            generic = _generic_bound_unit(
                source,
                unit_key=f"{source.capability_id}/generic",
                calculations=calculations,
                checks=checks,
            )
            selection = BoundTeachingSelection(
                kind=kind,
                units=(generic,),
            )

        if not selection.units:
            raise AnnotatedTeachingProjectionError(
                "teaching_material_projection_empty",
                f"$.steps[{source.source_step_id!r}]",
                "every verified Step must expose at least one teaching material",
            )
        materials = tuple(_public_material(item) for item in selection.units)
        unit_keys = tuple(item.unit_key for item in selection.units)
        return _ProjectedMaterialSet(
            materials=materials,
            kind=selection.kind,
            unit_keys=unit_keys,
            requires_independent_lesson_steps=tuple(
                self._separation.requires_independent_lesson_step(
                    source,
                    capability_kind=selection.kind,
                    unit_key=unit_key,
                )
                for unit_key in unit_keys
            ),
            variant_key=selection.variant_key,
            evidence_match=selection.evidence_match,
            diagnostics=tuple(diagnostics),
        )


class AnnotatedTeachingPlanProjector:
    """Project one verified Snapshot into the strict B2 LLM input contract."""

    def __init__(
        self,
        *,
        material_projector: TeachingMaterialProjector | None = None,
    ) -> None:
        self._materials = material_projector or TeachingMaterialProjector()

    def project(
        self,
        snapshot: ExplanationSnapshot,
    ) -> AnnotatedTeachingProjection:
        problem = _project_problem(snapshot)
        sources = tuple(iter_teaching_sources(snapshot.root_scope))
        source_by_id = {item.source_step_id: item for item in sources}
        if len(source_by_id) != len(sources):
            raise AnnotatedTeachingProjectionError(
                "teaching_source_step_id_duplicated",
                "$.root_scope",
                "Canonical teaching Step IDs must be globally unique",
            )
        question_goals = _question_goal_authority(snapshot)
        _validate_question_goal_owners(
            snapshot.root_scope,
            question_goals=question_goals,
        )
        student_object_aliases, student_output_labels = _student_object_projection(
            snapshot,
            sources=sources,
        )
        answers = _project_answers(
            snapshot,
            source_by_id=source_by_id,
            question_goals=question_goals,
            student_object_aliases=student_object_aliases,
            student_output_labels=student_output_labels,
        )
        authority_containers: dict[str, list[dict[str, Any]]] = {}
        diagnostics: list[TeachingProjectionDiagnostic] = []

        def project_step(
            source: TeachingSource,
            *,
            container_ref: str,
        ) -> AnnotatedTeachingStep:
            inputs = _project_inputs(
                source,
                source_by_id=source_by_id,
                student_object_aliases=student_object_aliases,
                student_output_labels=student_output_labels,
            )
            outputs = {
                name: _project_runtime_result(
                    value,
                    student_object_aliases=student_object_aliases,
                    display_label=student_output_labels.get(
                        (source.source_step_id, name)
                    ),
                    path=(
                        f"$.root_scope.steps[{source.source_step_id!r}]"
                        f".execution.outputs[{name!r}]"
                    ),
                )
                for name, value in source.outputs.items()
            }
            calculations = tuple(
                _project_calculation(
                    item,
                    path=(
                        f"$.root_scope.steps[{source.source_step_id!r}]"
                        f".execution.calculations[{index}]"
                    ),
                )
                for index, item in enumerate(source.calculations)
            )
            checks = tuple(
                _project_check(
                    item,
                    path=(
                        f"$.root_scope.steps[{source.source_step_id!r}]"
                        f".execution.checks[{index}]"
                    ),
                )
                for index, item in enumerate(source.checks)
            )
            projected_materials = self._materials.project(
                source,
                snapshot=snapshot,
                calculations=calculations,
                checks=checks,
            )
            diagnostics.extend(projected_materials.diagnostics)
            evidence_refs = sorted(
                str(key)
                for key, payload in snapshot.evidence.items()
                if str(payload.get("step_id") or "") == source.source_step_id
            )
            records = authority_containers.setdefault(container_ref, [])
            for material, unit_key, requires_independent in zip(
                projected_materials.materials,
                projected_materials.unit_keys,
                projected_materials.requires_independent_lesson_steps,
                strict=True,
            ):
                teaching_step_ref = f"s{len(records) + 1}"
                records.append(
                    {
                        "position": len(records),
                        "teaching_step_ref": teaching_step_ref,
                        "source_step_id": source.source_step_id,
                        "capability_id": source.capability_id,
                        "capability_kind": projected_materials.kind,
                        "unit_key": unit_key,
                        "requires_independent_lesson_step": (
                            requires_independent
                        ),
                        "variant_key": projected_materials.variant_key,
                        "variant_evidence_match": _json_clone(
                            projected_materials.evidence_match
                        ),
                        "evidence_refs": evidence_refs,
                        "suggestion_hash": _stable_hash(material.to_payload()),
                    }
                )
            return AnnotatedTeachingStep(
                step_id=source.source_step_id,
                capability_id=source.capability_id,
                intent=source.intent,
                inputs=inputs,
                outputs=outputs,
                calculations=calculations,
                teaching_materials=projected_materials.materials,
            )

        def project_scope(scope: TeachingScope) -> AnnotatedTeachingScope:
            scope_container = f"scope:{scope.scope_ref}"
            steps = tuple(
                project_step(source, container_ref=scope_container)
                for source in scope.steps
            )
            goals: list[AnnotatedTeachingGoal] = []
            for goal in scope.goals:
                question_goal = question_goals[goal.goal_ref]
                goal_steps = tuple(
                    project_step(
                        source,
                        container_ref=f"goal:{goal.goal_ref}",
                    )
                    for source in goal.steps
                )
                answer = answers[goal.goal_ref]
                goals.append(
                    AnnotatedTeachingGoal(
                        goal_ref=goal.goal_ref,
                        required_answer={
                            "answer_key": str(question_goal["answer_key"]),
                            "runtime_type": str(answer["type"]),
                        },
                        steps=goal_steps,
                        answer_from=dict(goal.answer_from),
                    )
                )
            return AnnotatedTeachingScope(
                scope_ref=scope.scope_ref,
                steps=steps,
                goals=tuple(goals),
                children=tuple(project_scope(child) for child in scope.children),
            )

        root_scope = project_scope(snapshot.root_scope)
        plan = AnnotatedTeachingPlan(
            problem=problem,
            answers=answers,
            root_scope=root_scope,
        )
        plan_payload = plan.to_payload()
        _validate_json_schema(
            plan_payload,
            annotated_teaching_plan_schema(),
            code="annotated_teaching_plan_schema_invalid",
        )
        _assert_llm_safe(
            plan_payload,
            path="$.annotated_teaching_plan",
        )
        authority = {
            "schema_version": TEACHING_AUTHORITY_CONTRACT,
            "canonical_plan_hash": snapshot.canonical_plan_hash,
            "verified_execution_hash": snapshot.verified_execution_hash,
            "snapshot_hash": explanation_snapshot_content_hash(snapshot),
            "annotated_plan_hash": _stable_hash(plan_payload),
            "student_object_aliases": dict(student_object_aliases),
            "student_output_labels": {
                f"{step_id}.{return_name}": label
                for (step_id, return_name), label in student_output_labels.items()
            },
            "containers": authority_containers,
            "independent_step_refs": {
                container_ref: [
                    str(record["teaching_step_ref"])
                    for record in records
                    if record["requires_independent_lesson_step"]
                ]
                for container_ref, records in authority_containers.items()
            },
            "diagnostics": [item.to_payload() for item in diagnostics],
        }
        return AnnotatedTeachingProjection(
            plan=plan,
            authority=authority,
            diagnostics=tuple(diagnostics),
        )


def annotated_teaching_plan_schema() -> dict[str, Any]:
    runtime_result = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "value", "display"],
        "properties": {
            "type": {"type": "string", "minLength": 1},
            "value": {},
            "display": {"type": "string", "minLength": 1},
        },
    }
    input_value = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "value", "display"],
        "properties": {
            "type": {"type": "string", "minLength": 1},
            "value": {},
            "display": {"type": "string", "minLength": 1},
        },
    }
    calculation = {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value", "display"],
        "properties": {
            "kind": {"type": "string", "minLength": 1},
            "value": {},
            "display": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    derive_item = {
        "type": "string",
        "pattern": r"^(作|设|∵|∴|计算)\s+\S",
    }
    material = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "step_ref",
            "title",
            "nav_title",
            "goal",
            "derive",
            "conclusions",
        ],
        "properties": {
            "step_ref": {
                "type": "string",
                "pattern": r"^s[1-9][0-9]*$",
            },
            "title": {"type": "string", "minLength": 1},
            "nav_title": {"type": "string", "minLength": 1},
            "goal": {"type": "string", "minLength": 1},
            "derive": {
                "type": "array",
                "minItems": 1,
                "items": derive_item,
            },
            "conclusions": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    step = {
        "type": "object",
        "additionalProperties": False,
        "required": ["materials"],
        "properties": {
            "inputs": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "array",
                    "minItems": 1,
                    "items": input_value,
                },
            },
            "outputs": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": runtime_result,
            },
            "calculations": {
                "type": "array",
                "minItems": 1,
                "items": calculation,
            },
            "materials": {
                "type": "array",
                "minItems": 1,
                "items": material,
            },
        },
    }
    scope: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["scope_ref"],
        "properties": {
            "scope_ref": {"type": "string", "minLength": 1},
            "steps": {"type": "array", "minItems": 1, "items": step},
            "goals": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "array",
                    "minItems": 1,
                    "items": step,
                },
            },
            "children": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/scope"},
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            "https://shuxueshuo.local/schemas/"
            "functional-annotated-teaching-plan.schema.json"
        ),
        "title": "Functional Annotated Teaching Plan v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["problem", "answers", "root_scope"],
        "properties": {
            "problem": {
                "type": "object",
                "additionalProperties": False,
                "required": ["original_text", "scope_labels"],
                "properties": {
                    "original_text": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 1},
                    },
                    "scope_labels": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": {
                            "type": "string",
                            "minLength": 1,
                        },
                    },
                },
            },
            "answers": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": runtime_result,
            },
            "root_scope": {"$ref": "#/$defs/scope"},
        },
        "$defs": {"scope": scope},
    }


def lesson_scope_content_schema(plan: AnnotatedTeachingPlan) -> dict[str, Any]:
    """Build the final B3 response Schema without invoking an LLM."""

    lesson_step = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "source_steps",
            "title",
            "nav_title",
            "goal",
            "derive",
        ],
        "properties": {
            "source_steps": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": r"^s[1-9][0-9]*$",
                },
            },
            "title": {"type": "string", "minLength": 1},
            "nav_title": {"type": "string", "minLength": 1},
            "goal": {"type": "string", "minLength": 1},
            "derive": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "string",
                    "pattern": r"^(作|设|∵|∴|计算)\s+\S",
                },
            },
        },
    }

    scope_properties: dict[str, Any] = {}
    required_scopes: list[str] = []
    for scope in _iter_annotated_scopes(plan.root_scope):
        scope_material_count = sum(
            len(step.teaching_materials) for step in scope.steps
        )
        goal_counts = {
            goal.goal_ref: sum(
                len(step.teaching_materials) for step in goal.steps
            )
            for goal in scope.goals
        }
        if scope_material_count + sum(goal_counts.values()) == 0:
            continue
        required_scopes.append(scope.scope_ref)
        goal_properties = {
            goal.goal_ref: _lesson_step_array_schema(goal_counts[goal.goal_ref])
            for goal in scope.goals
            if goal_counts[goal.goal_ref]
        }
        required_fields: list[str] = []
        properties: dict[str, Any] = {}
        if scope_material_count:
            required_fields.append("steps")
            properties["steps"] = _lesson_step_array_schema(
                scope_material_count
            )
        if goal_properties:
            required_fields.append("goals")
            properties["goals"] = {
                "type": "object",
                "additionalProperties": False,
                "required": list(goal_properties),
                "properties": goal_properties,
            }
        scope_properties[scope.scope_ref] = {
            "type": "object",
            "additionalProperties": False,
            "required": required_fields,
            "properties": properties,
        }

    if not required_scopes:
        raise AnnotatedTeachingProjectionError(
            "lesson_scope_output_schema_empty",
            "$.root_scope",
            "no Scope contains teaching materials",
        )
    # Inject the shared item definition after container construction so every
    # array uses the same final LessonStepDraft contract.
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Lesson Scope Content v1",
        "type": "object",
        "additionalProperties": False,
        "required": required_scopes,
        "properties": scope_properties,
        "$defs": {"lesson_step": lesson_step},
    }
    Draft202012Validator.check_schema(schema)
    return schema


def llm_facing_annotated_plan_payload(
    plan: AnnotatedTeachingPlan,
) -> dict[str, Any]:
    """Keep typed authority intact while hiding CAS notation from the LLM."""

    payload = _studentize_internal_math_value(plan.to_payload())
    hits = find_internal_math_tokens(payload)
    if hits:
        raise AnnotatedTeachingProjectionError(
            "teaching_prompt_internal_math_syntax",
            "$.root_scope",
            f"LLM-facing plan contains internal math syntax: {hits}",
        )
    return payload


def render_annotated_teaching_prompt(
    plan: AnnotatedTeachingPlan,
    *,
    authority: Mapping[str, Any],
    output_schema: Mapping[str, Any] | None = None,
) -> AnnotatedTeachingPrompt:
    """Render the exact B3 request without making a provider call."""

    schema = dict(output_schema or lesson_scope_content_schema(plan))
    if authority.get("annotated_plan_hash") != _stable_hash(plan.to_payload()):
        raise AnnotatedTeachingProjectionError(
            "teaching_prompt_authority_drift",
            "$.authority",
            "authority is not bound to the rendered Annotated Teaching Plan",
        )
    independent_materials = _independent_material_prompt_section(authority)
    system = """你是中学数学讲解编排器。
你的目标是把已经验证的解题材料整理成学生容易理解的完整讲解。
学生步骤的边界应对应一次需要理解的新数学思考，而不是一次代码调用。逐项审视同一 Scope/Goal 内相邻的 materials，判断学生在其间是否需要转换思路。
若后续 material 引入新的解题策略、定理、几何构造、证明、候选分支判断或题目单独要求的结果，应另起一步。若后续 material 只是把刚得到的结论代入已有表达式、坐标或对象，或完成同一推理下的直接计算、化简和结果展开，不需要新的选择或理由，则应与产生该结论的 material 合为一个学生步骤。
输入输出依赖可以帮助识别同一认知动作，但“相邻”“较短”或“存在依赖”本身都不是合并理由。合并的目的是减少没有新教学意义的步骤切换，而不是压缩数学内容；合并后必须完整保留关键依据、计算和每个必要结果。
列为“必须独立”的 step_ref 必须各自单独输出：任何包含该 step_ref 的 source_steps 数组都必须恰好只有这一个元素。Prompt 同时会列出可考虑合并的连续区间；它们只是允许范围，仍须按学生是否需要转换思路来判断，不要求机械合并。
完善并润色 title、nav_title、goal 和 derive，让学生清楚每一步为什么成立、得到什么以及如何衔接下一步。数学语言为主，只补充少量必要的自然语言。
derive 可以改写已有推导的措辞、合并重复表达，并补充不产生新数学事实的自然语言衔接；只能使用当前 materials 的 derive、calculations 和 conclusions 中已经明确给出的计算，不得自行新增代入、化简、方程、坐标计算或数值运算。
输入中的数学事实、计算结果、conclusions 和最终 answers 已经由解题器验证；不要重新解题或修改它们。结论由代码写入课程，你不需要返回 conclusions 或 box。
必须在输出 Schema 固定的 Scope/Goal 中返回完整教学正文，不能移动材料所属容器。
输入的 root_scope 仅按真实父子关系递归展示上下文；输出 Schema 已由代码把本轮需要填写的 Scope 展开为固定顶层 key。只按同名 scope_ref/goal_ref 填写正文，不要重建 children；未出现在输出 Schema 中的上下文 Scope 不返回。
每个 Scope/Goal 只能改写自己 materials 中已有的数学内容。父 Scope 的结果可以作为 child Scope 的既有上下文；child Scope 或 sibling Scope 的结果绝不能提前写回父 Scope或其他容器。
每份 material 都有当前 Scope/Goal 内的局部 step_ref。每个输出步骤用 source_steps 列出它合并的 step_ref；只能合并同一容器内相邻步骤，编号必须保持原顺序，所有编号必须恰好使用一次。
derive 的每一行必须是一个字符串，并以“作 ”“设 ”“∵ ”“∴ ”或“计算 ”开头。
所有数学内容必须写成学生在试卷上使用的形式：根式写“√”，分段结果用中文分情况叙述，等式与不等式使用数学符号。严禁输出 Eq(...)、sqrt(...)、Piecewise(...)、**、True、False 等计算机代数内部字符串。
只能使用输入已经给出的对象、数值、关系和结论，不得编造数学事实或内部标识。
返回严格符合给定 JSON Schema 的单个 JSON 对象，不要输出 Markdown、HTML 或解释性前言。"""
    llm_plan_payload = llm_facing_annotated_plan_payload(plan)
    sections = [
            "## 输出 JSON Schema\n\n"
            + _compact_json(schema),
            "## 全题型共享示例\n\n"
            "示例的学生认知分析：s1 需要理解的新思考是根据周长建立方程并求参数；"
            "s2、s3 只是把刚得到的参数代入两个已有对象，没有引入新策略、定理或判断。"
            "因此三份材料属于同一次“求参数并应用”的认知动作，应在不省略计算和结果的前提下合为一步。"
            "如果后续材料需要新的几何构造、证明或分支选择，就应另起一步。"
            "示例不是当前题条件。\n\n"
            + _compact_json(_shared_scope_lesson_few_shot()),
    ]
    if independent_materials:
        sections.append(independent_materials)
    sections.append(
        "## Annotated Teaching Plan\n\n"
        + _compact_json(llm_plan_payload)
    )
    user = "\n\n".join(sections)
    prompt = AnnotatedTeachingPrompt(system=system, user=user)
    _assert_llm_safe(
        {"system": prompt.system, "user": prompt.user},
        path="$.prompt",
    )
    return prompt


def _independent_material_prompt_section(
    authority: Mapping[str, Any],
) -> str:
    raw = authority.get("independent_step_refs")
    containers = authority.get("containers")
    if not isinstance(raw, Mapping) or not isinstance(containers, Mapping):
        raise AnnotatedTeachingProjectionError(
            "teaching_prompt_separation_authority_invalid",
            "$.authority.independent_step_refs",
            "independent material authority must be an object",
        )
    independent_rows: list[str] = []
    merge_candidate_rows: list[str] = []
    for container_ref, records in containers.items():
        if not isinstance(records, Sequence) or isinstance(records, str | bytes):
            raise AnnotatedTeachingProjectionError(
                "teaching_prompt_separation_authority_invalid",
                f"$.authority.containers[{container_ref!r}]",
                "container authority must be an array",
            )
        expected = [
            str(record.get("teaching_step_ref") or "")
            for record in records
            if isinstance(record, Mapping)
            and record.get("requires_independent_lesson_step") is True
        ]
        observed = raw.get(container_ref)
        if not isinstance(observed, Sequence) or isinstance(
            observed, str | bytes
        ):
            raise AnnotatedTeachingProjectionError(
                "teaching_prompt_separation_authority_invalid",
                f"$.authority.independent_step_refs[{container_ref!r}]",
                "every material container must provide an array",
            )
        observed_refs = [str(item) for item in observed]
        if observed_refs != expected or any(
            re.fullmatch(r"s[1-9][0-9]*", item) is None
            for item in observed_refs
        ):
            raise AnnotatedTeachingProjectionError(
                "teaching_prompt_separation_authority_drift",
                f"$.authority.independent_step_refs[{container_ref!r}]",
                f"expected {expected}, observed {observed_refs}",
            )
        owner_kind, _, owner_ref = str(container_ref).partition(":")
        label = "Scope" if owner_kind == "scope" else "Goal"
        if observed_refs:
            singleton_arrays = "、".join(
                f'["{step_ref}"]' for step_ref in observed_refs
            )
            independent_rows.append(
                f"- {label} {owner_ref}：必须分别输出 {singleton_arrays}"
            )

        independent = set(observed_refs)
        mergeable_runs: list[list[str]] = []
        current_run: list[str] = []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            step_ref = str(record.get("teaching_step_ref") or "")
            if step_ref in independent:
                if len(current_run) >= 2:
                    mergeable_runs.append(current_run)
                current_run = []
                continue
            current_run.append(step_ref)
        if len(current_run) >= 2:
            mergeable_runs.append(current_run)
        if mergeable_runs:
            rendered_runs = "、".join(
                "[" + ",".join(f'\"{item}\"' for item in run) + "]"
                for run in mergeable_runs
            )
            merge_candidate_rows.append(
                f"- {label} {owner_ref}：{rendered_runs}"
            )
    unknown = sorted(set(raw) - set(containers))
    if unknown:
        raise AnnotatedTeachingProjectionError(
            "teaching_prompt_separation_authority_drift",
            "$.authority.independent_step_refs",
            f"unknown material containers: {unknown}",
        )
    if not independent_rows and not merge_candidate_rows:
        return ""
    sections: list[str] = []
    if independent_rows:
        sections.extend(
            (
                "## 必须独立的教学材料",
                "",
                "以下每个 step_ref 都必须作为 source_steps 的唯一元素单独成步；严禁把同一行中的两个 ref 放入同一个数组：",
                *independent_rows,
            )
        )
    if merge_candidate_rows:
        if sections:
            sections.append("")
        sections.extend(
            (
                "## 可考虑合并的连续材料",
                "",
                "以下是代码按独立边界计算出的最大连续区间。只能在同一列出的区间内考虑合并；是否合并仍由学生是否需要转换思路决定：",
                *merge_candidate_rows,
            )
        )
    return "\n".join(sections)


def build_projection_audit(
    projection: AnnotatedTeachingProjection,
    *,
    prompt: AnnotatedTeachingPrompt,
    output_schema: Mapping[str, Any],
) -> dict[str, Any]:
    plan_payload = projection.plan.to_payload()
    plan_hits = find_forbidden_llm_tokens(plan_payload)
    prompt_hits = find_forbidden_llm_tokens(
        {"system": prompt.system, "user": prompt.user}
    )
    scopes = tuple(_iter_annotated_scopes(projection.plan.root_scope))
    steps = tuple(_iter_annotated_steps(projection.plan.root_scope))
    goals = tuple(goal for scope in scopes for goal in scope.goals)
    material_count = sum(len(step.teaching_materials) for step in steps)
    independent_step_refs = {
        str(container_ref): [str(item) for item in refs]
        for container_ref, refs in (
            projection.authority.get("independent_step_refs") or {}
        ).items()
        if refs
    }
    status = (
        "ready_for_human_review"
        if not plan_hits and not prompt_hits and not projection.diagnostics
        else "invalid"
    )
    return {
        "schema_version": PROJECTION_AUDIT_CONTRACT,
        "status": status,
        "counts": {
            "scope_count": len(scopes),
            "goal_count": len(goals),
            "step_count": len(steps),
            "teaching_material_count": material_count,
            "independent_teaching_material_count": sum(
                len(refs) for refs in independent_step_refs.values()
            ),
            "verified_answer_count": len(projection.plan.answers),
        },
        "hashes": {
            "annotated_plan": _stable_hash(plan_payload),
            "output_schema": _stable_hash(output_schema),
            "prompt": _stable_hash(prompt.messages),
        },
        "prompt_chars": {
            "system": len(prompt.system),
            "user": len(prompt.user),
            "total": len(prompt.system) + len(prompt.user),
            "b0_total": 54_707,
            "smaller_than_b0": (
                len(prompt.system) + len(prompt.user) < 54_707
            ),
        },
        "forbidden_hits": {
            "annotated_plan": plan_hits,
            "prompt": prompt_hits,
        },
        "projection_diagnostics": [
            item.to_payload() for item in projection.diagnostics
        ],
        "independent_step_refs": independent_step_refs,
        "shared_few_shot": {
            "count": 1,
            "same_problem": False,
            "mechanism": "student_cognitive_action_boundary",
        },
        "llm_invoked": False,
    }


def find_forbidden_llm_tokens(value: Any) -> list[str]:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    lowered = serialized.lower()
    return sorted(
        token
        for token in FORBIDDEN_LLM_TOKENS
        if token.lower() in lowered
    )


def _project_problem(snapshot: ExplanationSnapshot) -> dict[str, Any]:
    original_text = snapshot.problem.get("original_text")
    if not isinstance(original_text, Sequence) or isinstance(
        original_text,
        str | bytes,
    ):
        raise AnnotatedTeachingProjectionError(
            "teaching_problem_text_invalid",
            "$.problem.original_text",
            "expected a non-empty sequence of problem statements",
        )
    text = [str(item).strip() for item in original_text]
    if not text or any(not item for item in text):
        raise AnnotatedTeachingProjectionError(
            "teaching_problem_text_invalid",
            "$.problem.original_text",
            "problem statements must be non-empty strings",
        )
    raw_scopes = snapshot.problem.get("scopes")
    if not isinstance(raw_scopes, Sequence) or isinstance(raw_scopes, str | bytes):
        raise AnnotatedTeachingProjectionError(
            "teaching_problem_scope_labels_invalid",
            "$.problem.scopes",
            "scope labels are required",
        )
    labels: dict[str, str] = {}
    for index, item in enumerate(raw_scopes):
        if not isinstance(item, Mapping):
            raise AnnotatedTeachingProjectionError(
                "teaching_problem_scope_labels_invalid",
                f"$.problem.scopes[{index}]",
                "scope label entry must be an object",
            )
        scope_ref = str(item.get("scope_id") or "")
        label = str(item.get("label") or "")
        if not scope_ref or not label or scope_ref in labels:
            raise AnnotatedTeachingProjectionError(
                "teaching_problem_scope_labels_invalid",
                f"$.problem.scopes[{index}]",
                "scope refs and labels must be non-empty and unique",
            )
        labels[scope_ref] = label
    canonical_scope_refs = {
        scope.scope_ref for scope in iter_teaching_scopes(snapshot.root_scope)
    }
    if set(labels) != canonical_scope_refs:
        raise AnnotatedTeachingProjectionError(
            "teaching_problem_scope_labels_mismatch",
            "$.problem.scope_labels",
            "problem scope labels must match the Canonical Scope tree",
        )
    result = {"original_text": text, "scope_labels": labels}
    _assert_llm_safe(result, path="$.problem")
    return result


def _question_goal_authority(
    snapshot: ExplanationSnapshot,
) -> dict[str, Mapping[str, Any]]:
    raw = snapshot.problem.get("question_goals")
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise AnnotatedTeachingProjectionError(
            "teaching_question_goals_invalid",
            "$.problem.question_goals",
            "question goal authority is missing",
        )
    result: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise AnnotatedTeachingProjectionError(
                "teaching_question_goals_invalid",
                f"$.problem.question_goals[{index}]",
                "question goal must be an object",
            )
        handle = str(item.get("handle") or "")
        scope_ref = str(item.get("scope_id") or "")
        answer_key = str(item.get("answer_key") or "")
        goal_ref = (
            handle.removeprefix("answer:")
            if handle.startswith("answer:")
            else f"{scope_ref}.{answer_key}"
        )
        if not goal_ref or not scope_ref or not answer_key or goal_ref in result:
            raise AnnotatedTeachingProjectionError(
                "teaching_question_goals_invalid",
                f"$.problem.question_goals[{index}]",
                "goal identity is empty or duplicated",
            )
        result[goal_ref] = {
            "scope_ref": scope_ref,
            "answer_key": answer_key,
            "runtime_type": str(item.get("value_type") or "Unknown"),
        }
    canonical_goal_refs = {
        goal.goal_ref
        for scope in iter_teaching_scopes(snapshot.root_scope)
        for goal in scope.goals
    }
    if set(result) != canonical_goal_refs:
        raise AnnotatedTeachingProjectionError(
            "teaching_question_goals_mismatch",
            "$.problem.question_goals",
            "question goals must match the Canonical Goal tree",
        )
    return result


def _validate_question_goal_owners(
    root_scope: TeachingScope,
    *,
    question_goals: Mapping[str, Mapping[str, Any]],
) -> None:
    for scope in iter_teaching_scopes(root_scope):
        for goal in scope.goals:
            authority = question_goals[goal.goal_ref]
            if str(authority["scope_ref"]) != scope.scope_ref:
                raise AnnotatedTeachingProjectionError(
                    "teaching_goal_owner_mismatch",
                    f"$.root_scope.goals[{goal.goal_ref!r}]",
                    "question Goal owner differs from the Canonical Scope tree",
                )


def _student_object_projection(
    snapshot: ExplanationSnapshot,
    *,
    sources: Sequence[TeachingSource],
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Assign student labels to anonymous public objects by typed provenance.

    A producer such as ``AngleEquality`` can mention the identity of a point
    that a later Step materializes.  That identity is intentionally stable for
    the runtime, but it is not a student-facing point name.  Resolve the
    producer/consumer edge and the consumer's public ``Point`` return first,
    then allocate one unused label shared by both values.  No Step-ID parsing
    or string replacement participates in the decision.
    """

    used_labels = {
        str(entity.get("name") or "")
        for entity in (snapshot.problem or {}).get("entities") or ()
        if isinstance(entity, Mapping)
        and entity.get("entity_type") == "point"
        and entity.get("name")
    }
    for source in sources:
        for return_name, output in source.outputs.items():
            label = _declared_student_point_label(source, return_name, output)
            if label:
                used_labels.add(label)

    identity_aliases: dict[str, str] = {}
    output_labels: dict[tuple[str, str], str] = {}
    for producer in sources:
        for return_name, output in producer.outputs.items():
            if str(output.get("runtime_type") or "") != "AngleEquality":
                continue
            value = output.get("value")
            if not isinstance(value, Mapping):
                continue
            angle_points = _angle_equality_point_names(value)
            anonymous_names = tuple(
                dict.fromkeys(
                    name
                    for name in angle_points
                    if name not in used_labels and name not in identity_aliases
                )
            )
            if not anonymous_names:
                continue

            consumers = [
                source
                for source in sources
                if _source_consumes_result(
                    source,
                    producer_step_id=producer.source_step_id,
                    return_name=return_name,
                )
            ]
            point_outputs = [
                (consumer, output_name, child)
                for consumer in consumers
                for output_name, child in consumer.outputs.items()
                if str(child.get("runtime_type") or "") == "Point"
            ]
            if len(anonymous_names) != 1 or len(point_outputs) != 1:
                raise AnnotatedTeachingProjectionError(
                    "teaching_student_object_alias_ambiguous",
                    f"$.steps[{producer.source_step_id!r}].outputs[{return_name!r}]",
                    "anonymous relation object must resolve to exactly one public Point return",
                )

            consumer, point_return, point_output = point_outputs[0]
            public_label = _declared_student_point_label(
                consumer,
                point_return,
                point_output,
            )
            if not public_label:
                public_label = _first_unused_student_point_label(used_labels)
            used_labels.add(public_label)
            identity_aliases[anonymous_names[0]] = public_label
            output_labels[(consumer.source_step_id, point_return)] = public_label

    return identity_aliases, output_labels


def _angle_equality_point_names(value: Mapping[str, Any]) -> tuple[str, ...]:
    result: list[str] = []
    for field in ("left_angle_points", "right_angle_points"):
        points = value.get(field)
        if not isinstance(points, Sequence) or isinstance(points, str | bytes):
            raise AnnotatedTeachingProjectionError(
                "teaching_angle_equality_projection_invalid",
                f"$.{field}",
                "AngleEquality point roles must be an ordered list",
            )
        result.extend(str(point) for point in points if str(point))
    return tuple(result)


def _source_consumes_result(
    source: TeachingSource,
    *,
    producer_step_id: str,
    return_name: str,
) -> bool:
    for items in source.inputs.values():
        for item in items:
            for field in ("resolved_from", "ref"):
                ref = item.get(field)
                if not isinstance(ref, Mapping) or ref.get("kind") != "step_result":
                    continue
                if (
                    str(ref.get("step_id") or "") == producer_step_id
                    and str(ref.get("return") or "") == return_name
                ):
                    return True
    return False


def _declared_student_point_label(
    source: TeachingSource,
    return_name: str,
    output: Mapping[str, Any],
) -> str:
    target = str(source.output_targets.get(return_name) or "").rsplit(":", 1)[-1]
    if _is_student_point_label(target):
        return target
    display = str(output.get("display") or "")
    match = re.match(r"\s*([A-Z][A-Za-z0-9_′']*)\s*\(", display)
    return match.group(1) if match and _is_student_point_label(match.group(1)) else ""


def _is_student_point_label(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z](?:[0-9]+|[′']+)?", value))


def _first_unused_student_point_label(used: set[str]) -> str:
    for codepoint in range(ord("A"), ord("Z") + 1):
        label = chr(codepoint)
        if label not in used:
            return label
    suffix = 1
    while True:
        for codepoint in range(ord("A"), ord("Z") + 1):
            label = f"{chr(codepoint)}{suffix}"
            if label not in used:
                return label
        suffix += 1


def _project_answers(
    snapshot: ExplanationSnapshot,
    *,
    source_by_id: Mapping[str, TeachingSource],
    question_goals: Mapping[str, Mapping[str, Any]],
    student_object_aliases: Mapping[str, str],
    student_output_labels: Mapping[tuple[str, str], str],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for scope in iter_teaching_scopes(snapshot.root_scope):
        for goal in scope.goals:
            producer_id = str(goal.answer_from.get("step_id") or "")
            return_name = str(goal.answer_from.get("return") or "")
            producer = source_by_id.get(producer_id)
            output = producer.outputs.get(return_name) if producer is not None else None
            if output is None:
                raise AnnotatedTeachingProjectionError(
                    "teaching_answer_source_missing",
                    f"$.root_scope.goals[{goal.goal_ref!r}].answer_from",
                    "answer_from must resolve to one materialized public output",
                )
            authority = question_goals[goal.goal_ref]
            question_id = str(authority["scope_ref"])
            answer_key = str(authority["answer_key"])
            observed_group = snapshot.answers.get(question_id)
            observed = (
                observed_group.get(answer_key)
                if isinstance(observed_group, Mapping)
                else None
            )
            projected = _project_runtime_result(
                output,
                student_object_aliases=student_object_aliases,
                display_label=student_output_labels.get(
                    (producer_id, return_name)
                ),
                path=f"$.answers[{goal.goal_ref!r}]",
            )
            if not _answer_values_equal(
                observed,
                projected["value"],
                runtime_type=str(projected["type"]),
            ):
                raise AnnotatedTeachingProjectionError(
                    "teaching_answer_value_mismatch",
                    f"$.answers[{goal.goal_ref!r}]",
                    "verified Solver answer differs from answer_from output",
                )
            expected_type = str(authority["runtime_type"])
            if expected_type not in {"", "Unknown", projected["type"]}:
                raise AnnotatedTeachingProjectionError(
                    "teaching_answer_type_mismatch",
                    f"$.answers[{goal.goal_ref!r}]",
                    "question goal type differs from answer_from output type",
                )
            result[goal.goal_ref] = projected
    return result


def _answer_values_equal(
    observed: Any,
    produced: Any,
    *,
    runtime_type: str,
) -> bool:
    observed_value = _json_clone(observed)
    produced_value = _json_clone(produced)
    if runtime_type != "PointList":
        return observed_value == produced_value
    if not isinstance(observed_value, list) or not isinstance(produced_value, list):
        return False
    canonical = lambda item: json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sorted(map(canonical, observed_value)) == sorted(
        map(canonical, produced_value)
    )


def _project_student_runtime_value(
    value: Any,
    *,
    runtime_type: str,
    student_object_aliases: Mapping[str, str],
    path: str,
) -> Any:
    projected = _json_clone(value)
    if runtime_type != "AngleEquality" or not student_object_aliases:
        return projected
    if not isinstance(projected, Mapping):
        raise AnnotatedTeachingProjectionError(
            "teaching_angle_equality_projection_invalid",
            path,
            "AngleEquality must be an object",
        )

    result = dict(projected)
    for field, angle_field in (
        ("left_angle_points", "left_angle"),
        ("right_angle_points", "right_angle"),
    ):
        raw_points = result.get(field)
        if not isinstance(raw_points, Sequence) or isinstance(
            raw_points,
            str | bytes,
        ):
            raise AnnotatedTeachingProjectionError(
                "teaching_angle_equality_projection_invalid",
                f"{path}.{field}",
                "AngleEquality point roles must be an ordered list",
            )
        points = [
            student_object_aliases.get(str(point), str(point))
            for point in raw_points
        ]
        result[field] = points
        result[angle_field] = "".join(points)

    leaked = sorted(
        alias
        for alias in student_object_aliases
        if _contains_exact_string(result, alias)
    )
    if leaked:
        raise AnnotatedTeachingProjectionError(
            "teaching_student_object_alias_incomplete",
            path,
            f"typed relation still contains internal object identities: {leaked}",
        )
    return result


def _studentize_internal_math_value(value: Any) -> Any:
    """Remove CAS spellings from every value exposed to the Lesson LLM."""

    if isinstance(value, Mapping):
        return {
            str(key): _studentize_internal_math_value(child)
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [_studentize_internal_math_value(child) for child in value]
    if not isinstance(value, str) or not find_internal_math_tokens(value):
        return value
    result: str
    try:
        encoded = json.loads(value)
    except (TypeError, ValueError):
        encoded = None
    if isinstance(encoded, (Mapping, list)):
        result = json.dumps(
            _studentize_internal_math_value(encoded),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        result = student_math_display(value, fullwidth_operators=True)
    remaining = find_internal_math_tokens(result)
    if remaining:
        raise AnnotatedTeachingProjectionError(
            "teaching_value_internal_math_syntax",
            "$.runtime_value",
            f"student projection still contains internal math syntax: {remaining}",
        )
    return result


def _contains_exact_string(value: Any, target: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            _contains_exact_string(key, target)
            or _contains_exact_string(child, target)
            for key, child in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return any(_contains_exact_string(child, target) for child in value)
    return isinstance(value, str) and value == target


def _project_student_runtime_display(
    *,
    runtime_type: str,
    value: Any,
    fallback: str,
    label: str | None = None,
) -> str:
    if runtime_type == "AngleEquality" and isinstance(value, Mapping):
        left = str(value.get("left_angle") or "")
        right = str(value.get("right_angle") or "")
        if left and right:
            return f"∠{left}＝∠{right}"
    if (
        runtime_type == "Point"
        and label
        and isinstance(value, Sequence)
        and not isinstance(value, str | bytes)
        and len(value) == 2
    ):
        return f"{label}{_display_point(value)}"
    return fallback


def _referenced_student_output_label(
    ref: Any,
    *,
    student_output_labels: Mapping[tuple[str, str], str],
) -> str | None:
    if not isinstance(ref, Mapping) or ref.get("kind") != "step_result":
        return None
    return student_output_labels.get(
        (
            str(ref.get("step_id") or ""),
            str(ref.get("return") or ""),
        )
    )


def _project_inputs(
    source: TeachingSource,
    *,
    source_by_id: Mapping[str, TeachingSource],
    student_object_aliases: Mapping[str, str],
    student_output_labels: Mapping[tuple[str, str], str],
) -> dict[str, tuple[Mapping[str, Any], ...]]:
    result: dict[str, tuple[Mapping[str, Any], ...]] = {}
    for arg_name, items in source.inputs.items():
        projected: list[Mapping[str, Any]] = []
        for index, item in enumerate(items):
            ref = item.get("resolved_from") or item.get("ref")
            _project_reference(
                ref,
                source_by_id=source_by_id,
                path=(
                    f"$.steps[{source.source_step_id!r}]"
                    f".inputs[{arg_name!r}][{index}].ref"
                ),
            )
            runtime_type = str(item.get("runtime_type") or "")
            display = str(item.get("display") or "")
            if not runtime_type or not display or "value" not in item:
                raise AnnotatedTeachingProjectionError(
                    "teaching_input_projection_incomplete",
                    (
                        f"$.steps[{source.source_step_id!r}]"
                        f".inputs[{arg_name!r}][{index}]"
                    ),
                    "ref/runtime_type/value/display must all be present",
                )
            value = _project_student_runtime_value(
                item["value"],
                runtime_type=runtime_type,
                student_object_aliases=student_object_aliases,
                path=(
                    f"$.steps[{source.source_step_id!r}]"
                    f".inputs[{arg_name!r}][{index}].value"
                ),
            )
            display = _project_student_runtime_display(
                runtime_type=runtime_type,
                value=value,
                fallback=display,
                label=_referenced_student_output_label(
                    ref,
                    student_output_labels=student_output_labels,
                ),
            )
            _assert_public_value(
                value,
                path=(
                    f"$.steps[{source.source_step_id!r}]"
                    f".inputs[{arg_name!r}][{index}].value"
                ),
            )
            _assert_public_value(
                display,
                path=(
                    f"$.steps[{source.source_step_id!r}]"
                    f".inputs[{arg_name!r}][{index}].display"
                ),
            )
            projected.append(
                {
                    "type": runtime_type,
                    "value": value,
                    "display": display,
                }
            )
        result[str(arg_name)] = tuple(projected)
    return result


def _project_reference(
    value: Any,
    *,
    source_by_id: Mapping[str, TeachingSource],
    path: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise AnnotatedTeachingProjectionError(
            "teaching_input_reference_invalid",
            path,
            "input ref must be SourceRef or StepResultRef",
        )
    kind = str(value.get("kind") or "")
    if kind == "source":
        ref = str(value.get("ref") or "")
        if not ref:
            raise AnnotatedTeachingProjectionError(
                "teaching_input_reference_invalid",
                path,
                "SourceRef is empty",
            )
        return {"kind": "source", "ref": ref}
    if kind == "step_result":
        step_id = str(value.get("step_id") or "")
        return_name = str(value.get("return") or "")
        producer = source_by_id.get(step_id)
        if producer is None or return_name not in producer.outputs:
            raise AnnotatedTeachingProjectionError(
                "teaching_input_reference_unknown",
                path,
                "StepResultRef does not resolve to a public producer output",
            )
        return {
            "kind": "step_result",
            "step_id": step_id,
            "return": return_name,
        }
    raise AnnotatedTeachingProjectionError(
        "teaching_input_reference_invalid",
        path,
        f"unsupported input ref kind {kind!r}",
    )


def _project_runtime_result(
    value: Mapping[str, Any],
    *,
    student_object_aliases: Mapping[str, str],
    display_label: str | None = None,
    path: str,
) -> dict[str, Any]:
    runtime_type = str(value.get("runtime_type") or "")
    display = str(value.get("display") or "")
    if not runtime_type or not display or "value" not in value:
        raise AnnotatedTeachingProjectionError(
            "teaching_runtime_result_incomplete",
            path,
            "runtime_type/value/display must all be present",
        )
    public_value = _project_student_runtime_value(
        value["value"],
        runtime_type=runtime_type,
        student_object_aliases=student_object_aliases,
        path=f"{path}.value",
    )
    display = _project_student_runtime_display(
        runtime_type=runtime_type,
        value=public_value,
        fallback=display,
        label=display_label,
    )
    _assert_public_value(public_value, path=f"{path}.value")
    _assert_public_value(display, path=f"{path}.display")
    return {
        "type": runtime_type,
        "value": public_value,
        "display": display,
    }


def _project_calculation(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    kind = str(item.get("kind") or "")
    if not kind:
        raise AnnotatedTeachingProjectionError(
            "teaching_calculation_kind_missing",
            path,
            "calculation kind must be non-empty",
        )
    value = {
        str(key): _json_clone(child)
        for key, child in item.items()
        if key not in {"calculation_id", "kind", "evidence_ref", "evidence_refs"}
    }
    display = _calculation_display(kind, value)
    if not display:
        raise AnnotatedTeachingProjectionError(
            "teaching_calculation_display_missing",
            path,
            "calculation has no complete student-safe display",
        )
    _assert_public_value(value, path=f"{path}.value")
    _assert_public_value(display, path=f"{path}.display")
    return {"kind": kind, "value": value, "display": display}


def _project_check(
    item: Mapping[str, Any],
    *,
    path: str,
) -> dict[str, Any]:
    internal_kind = str(item.get("kind") or "")
    if not internal_kind or "passed" not in item:
        raise AnnotatedTeachingProjectionError(
            "teaching_check_projection_incomplete",
            path,
            "check kind and passed status are required",
        )
    kind = _public_check_kind(internal_kind, item)
    display = _check_display(kind, item)
    _assert_public_value(display, path=f"{path}.display")
    return {
        "kind": kind,
        "passed": bool(item["passed"]),
        "display": display,
    }


def _calculation_display(
    kind: str,
    value: Mapping[str, Any],
) -> list[str]:
    if kind == "equivalence_chain":
        statements = [_display_math(item) for item in value.get("statements", ())]
        result = _display_math(value.get("result"))
        return _unique_nonempty((*statements, result))
    if kind == "equation_system":
        return _unique_nonempty(
            _display_math(item) for item in value.get("equations", ())
        )
    if kind == "substitution":
        return _unique_nonempty(
            f"{_display_math(item.get('symbol'))}＝{_display_math(item.get('value'))}"
            for item in value.get("values", ())
            if isinstance(item, Mapping)
        )
    if kind == "solution":
        return _unique_nonempty(
            (
                f"{_display_math(value.get('target'))}＝"
                f"{_display_math(value.get('value'))}",
            )
        )
    if kind == "minimum":
        return _unique_nonempty(
            (f"最小值为{_display_math(value.get('expression'))}",)
        )
    if kind == "attainment":
        points = value.get("points")
        if isinstance(points, Mapping):
            return _unique_nonempty(
                f"取等点为{name}{_display_point(coords)}"
                for name, coords in points.items()
            )
    if kind == "line_reflection":
        facts = value.get("facts")
        if isinstance(facts, Mapping):
            reflected_name = _display_math(
                facts.get("reflected_point_name") or "对称点"
            )
            reflected_point = _display_point(facts.get("reflected_point"))
            lines = [
                f"构造{reflected_name}{reflected_point}",
                _display_math(facts.get("segment_equality")),
                (
                    f"{_display_math(facts.get('transformed_path'))}＝"
                    f"{_display_math(facts.get('straightened_path'))}"
                ),
                (
                    f"最短线段为{_display_math(facts.get('minimum_segment'))}"
                ),
            ]
            return _unique_nonempty(lines)
    facts = value.get("facts")
    if isinstance(facts, Mapping) and facts.get("moving_locus") is not None:
        return _unique_nonempty(
            (f"动点轨迹为{_display_math(facts['moving_locus'])}",)
        )
    return _unique_nonempty(
        (json.dumps(value, ensure_ascii=False, separators=(",", ":")),)
    )


def _check_display(kind: str, item: Mapping[str, Any]) -> str:
    for field in ("detail", "summary"):
        if item.get(field):
            return _student_safe_check_text(str(item[field]))
    messages = {
        "point_on_moving_locus": "取等点位于动点轨迹上",
        "point_on_minimum_segment": "取等点位于最短线段上",
        "unique_solution_branch": "方程与题设约束筛选出唯一合法分支",
        "constraint_filter": "题设约束已用于筛选合法分支",
    }
    message = messages.get(kind)
    if message is not None:
        return message
    return f"{kind.replace('_', ' ')}校验{'通过' if item.get('passed') else '未通过'}"


def _public_check_kind(
    internal_kind: str,
    item: Mapping[str, Any],
) -> str:
    if internal_kind != "runtime_method_check":
        return internal_kind
    check_id = str(item.get("check_id") or "")
    exact = {
        "known_coefficients_preserved": "coefficient_preservation",
        "x_axis_y_is_zero": "coordinate_condition",
        "point_on_parabola": "curve_membership",
        "left_x_axis_intercept": "target_selection",
        "vertex_x_derivative_zero": "vertex_condition",
        "axis_x_derivative_zero": "axis_condition",
        "square_adjacent_side_perpendicular": "perpendicularity",
        "square_adjacent_side_equal_length": "equal_length",
        "candidate_count_positive": "candidate_nonempty",
        "parameter_domain": "parameter_domain",
        "expression_value_matches": "expression_value_match",
        "closure_parameter_value_matches": "solution_consistency",
        "closure_equation_0_satisfied": "equation_satisfaction",
        "point_parameter_substituted": "parameter_substitution",
    }
    if check_id in exact:
        return exact[check_id]
    if check_id.startswith("curve_point_") and check_id.endswith(
        ("_on_curve", "_on_parabola")
    ):
        return "curve_membership"
    return "verified_condition"


def _student_safe_check_text(value: str) -> str:
    replacements = {
        "顶点横坐标使一阶导数为 0": "所求点是抛物线的顶点",
        "参数值输出与 symbolic closure 一致": "参数值与已验证方程的解一致",
        "参数值满足 symbolic closure 方程": "参数值满足已验证方程",
    }
    result = replacements.get(value, value)
    return result.replace("symbolic closure", "已验证方程")


def _display_math(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("A_prime", "A′").replace("_prime", "′")
    equation = _unwrap_equation(text)
    if equation is not None:
        left, right = equation
        return f"{_display_math(left)}＝{_display_math(right)}"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    return student_math_display(text).replace("=", "＝")


def _unwrap_equation(value: str) -> tuple[str, str] | None:
    if not value.startswith("Eq(") or not value.endswith(")"):
        return None
    body = value[3:-1]
    depth = 0
    for index, character in enumerate(body):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            left = body[:index].strip()
            right = body[index + 1 :].strip()
            if left and right:
                return left, right
            return None
    return None


def _display_point(value: Any) -> str:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ""
    return "(" + ",".join(_display_math(item) for item in value) + ")"


def _unique_nonempty(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for raw in values:
        value = str(raw).strip()
        if value and value not in result:
            result.append(value)
    return result


def _binding_diagnostic(
    source: TeachingSource,
    error: Exception,
    *,
    unit_key: str | None = None,
) -> TeachingProjectionDiagnostic:
    message = str(error)
    prefix = message.split(":", 1)[0].strip()
    code = prefix if prefix.startswith("teaching_") else "teaching_material_binding_invalid"
    return TeachingProjectionDiagnostic(
        code=code,
        step_id=source.source_step_id,
        capability_id=source.capability_id,
        unit_key=unit_key,
        message=message,
        fallback="complete_generic_material",
    )


def _generic_bound_unit(
    source: TeachingSource,
    *,
    unit_key: str,
    calculations: tuple[Mapping[str, Any], ...],
    checks: tuple[Mapping[str, Any], ...],
) -> BoundTeachingUnit:
    title = str(source.intent or source.capability_id).strip()
    nav_title = title.rstrip("。")
    derive: list[tuple[str, str]] = []
    for calculation in calculations:
        marker = "作" if "construction" in str(calculation.get("kind")) else "计算"
        for display in calculation.get("display", ()):
            derive.append((marker, str(display)))
    if not derive:
        for output in source.outputs.values():
            display = str(output.get("display") or "").strip()
            if display:
                derive.append(("∴", f"得到{display}"))
    if not derive:
        for check in checks:
            display = str(check.get("display") or "").strip()
            if display:
                derive.append(("∵", display))
    if not derive:
        derive.append(("计算", "完成本步已经验证的计算"))
    box = tuple(
        dict.fromkeys(
            str(output.get("display") or "").strip()
            for output in source.outputs.values()
            if str(output.get("display") or "").strip()
        )
    )
    return BoundTeachingUnit(
        source_step_id=source.source_step_id,
        unit_key=unit_key,
        nav_title=nav_title,
        title=title,
        goal=title,
        derive=tuple(derive),
        box=box,
    )


def _public_material(unit: BoundTeachingUnit) -> AnnotatedTeachingMaterial:
    derive = tuple((str(marker), str(text)) for marker, text in unit.derive)
    if not derive or any(marker not in DERIVE_MARKERS or not text for marker, text in derive):
        raise AnnotatedTeachingProjectionError(
            "teaching_material_derive_invalid",
            f"$.teaching_materials[{unit.source_step_id!r}]",
            "derive must contain non-empty student math lines",
        )
    material = AnnotatedTeachingMaterial(
        suggested_title=unit.title,
        suggested_nav_title=unit.nav_title,
        suggested_goal=unit.goal,
        suggested_derive=derive,
        suggested_box=tuple(unit.box),
    )
    internal_math_hits = find_internal_math_tokens(material.to_payload())
    if internal_math_hits:
        raise AnnotatedTeachingProjectionError(
            "teaching_material_internal_math_syntax",
            f"$.teaching_materials[{unit.source_step_id!r}]",
            f"student text contains internal math syntax: {internal_math_hits}",
        )
    _assert_llm_safe(
        material.to_payload(),
        path=f"$.teaching_materials[{unit.source_step_id!r}]",
    )
    return material


def _lesson_step_array_schema(material_count: int) -> dict[str, Any]:
    if material_count == 0:
        return {"type": "array", "maxItems": 0}
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": material_count,
        "items": {"$ref": "#/$defs/lesson_step"},
    }


def _shared_scope_lesson_few_shot() -> dict[str, Any]:
    return {
        "input": {"materials": [
            {
                "step_ref": "s1",
                "title": "由周长条件求参数 m",
                "nav_title": "求参数 m",
                "goal": "由长方形周长建立方程并求出参数。",
                "derive": [
                    "∵ 长方形的长为 m＋2，宽为 m－1，周长为 18",
                    "∴ 2[(m＋2)＋(m－1)]＝18",
                    "计算 m＝4",
                ],
                "conclusions": ["m＝4"],
            },
            {
                "step_ref": "s2",
                "title": "代入参数求点 U",
                "nav_title": "求点 U",
                "goal": "把参数值代入已有含参点。",
                "derive": ["∵ U(m,2m)，m＝4", "∴ U(4,8)"],
                "conclusions": ["U(4,8)"],
            },
            {
                "step_ref": "s3",
                "title": "代入参数写出直线 l",
                "nav_title": "写出直线 l",
                "goal": "把同一参数值代入已有直线表达式。",
                "derive": ["∵ l：y＝mx＋1，m＝4", "∴ l：y＝4x＋1"],
                "conclusions": ["l：y＝4x＋1"],
            },
        ]},
        "output": {
            "example": {
                "goals": {
                    "example.result": [
                        {
                            "source_steps": ["s1", "s2", "s3"],
                            "title": "求参数并代入相关对象",
                            "nav_title": "求参并代入",
                            "goal": "先求出公共参数，再连续代入已有的点和直线。",
                            "derive": [
                                "∵ 2[(m＋2)＋(m－1)]＝18",
                                "计算 m＝4",
                                "∵ U(m,2m)，m＝4",
                                "∴ U(4,8)",
                                "∵ l：y＝mx＋1，m＝4",
                                "∴ l：y＝4x＋1",
                            ],
                        }
                    ]
                }
            }
        },
    }


def _iter_annotated_scopes(
    root: AnnotatedTeachingScope,
) -> Sequence[AnnotatedTeachingScope]:
    result: list[AnnotatedTeachingScope] = []

    def visit(scope: AnnotatedTeachingScope) -> None:
        result.append(scope)
        for child in scope.children:
            visit(child)

    visit(root)
    return tuple(result)


def _scope_has_materials(scope: AnnotatedTeachingScope) -> bool:
    return bool(
        scope.steps
        or any(goal.steps for goal in scope.goals)
        or any(_scope_has_materials(child) for child in scope.children)
    )


def _iter_annotated_steps(
    root: AnnotatedTeachingScope,
) -> Sequence[AnnotatedTeachingStep]:
    return tuple(
        step
        for scope in _iter_annotated_scopes(root)
        for step in (
            *scope.steps,
            *(item for goal in scope.goals for item in goal.steps),
        )
    )


def _assert_public_value(value: Any, *, path: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AnnotatedTeachingProjectionError(
            "teaching_public_value_invalid",
            path,
            str(exc),
        ) from exc
    if contains_private_path_projection_marker(value):
        raise AnnotatedTeachingProjectionError(
            "teaching_private_identity_leak",
            path,
            "private runtime identity cannot enter the Lesson prompt",
        )
    hits = find_forbidden_llm_tokens(value)
    if hits:
        raise AnnotatedTeachingProjectionError(
            "teaching_private_identity_leak",
            path,
            f"forbidden values: {hits}",
        )


def _assert_llm_safe(value: Any, *, path: str) -> None:
    _assert_public_value(value, path=path)


def _validate_json_schema(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    *,
    code: str,
) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if not errors:
        return
    first = errors[0]
    location = "$" + "".join(f"[{part!r}]" for part in first.path)
    raise AnnotatedTeachingProjectionError(code, location, first.message)


def _json_clone(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    )


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


def _compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    )


__all__ = [
    "ANNOTATED_TEACHING_PLAN_CONTRACT",
    "AnnotatedTeachingMaterial",
    "AnnotatedTeachingPlan",
    "AnnotatedTeachingPlanProjector",
    "AnnotatedTeachingProjection",
    "AnnotatedTeachingProjectionError",
    "AnnotatedTeachingPrompt",
    "AnnotatedTeachingScope",
    "AnnotatedTeachingStep",
    "FORBIDDEN_LLM_TOKENS",
    "LESSON_SCOPE_CONTENT_CONTRACT",
    "PROJECTION_AUDIT_CONTRACT",
    "TEACHING_AUTHORITY_CONTRACT",
    "TeachingMaterialProjector",
    "TeachingProjectionDiagnostic",
    "annotated_teaching_plan_schema",
    "build_projection_audit",
    "find_forbidden_llm_tokens",
    "lesson_scope_content_schema",
    "llm_facing_annotated_plan_payload",
    "render_annotated_teaching_prompt",
]
