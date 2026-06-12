"""Recipe explanation role binders."""

from __future__ import annotations

import re
from typing import Any, Protocol

from shuxueshuo_server.solver.runtime.recipes._spec import RecipeExplanationSpec, RecipeSpec

from ..models import ExplanationSnapshot, LessonCandidateGroup
from .common import (
    after_equals,
    format_template,
    generic_must_not_invent,
    handle_name,
    minimum_expression_from_conclusion,
)


class RecipeRoleBinder(Protocol):
    """Bind recipe explanation draft from a candidate group and snapshot."""

    def bind(
        self,
        *,
        recipe_spec: RecipeSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        ...


class GenericRecipeRoleBinder:
    """Fallback recipe binder using static recipe templates only."""

    def bind(
        self,
        *,
        recipe_spec: RecipeSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        explanation = recipe_spec.explanation
        assert explanation is not None
        roles = sorted(explanation.role_schema)
        return {
            "confidence": "gap",
            "bound_roles": {},
            "unbound_roles": roles,
            "proof_draft": list(explanation.proof_outline_templates),
            "llm_can_complete": list(explanation.allowed_llm_completion),
            "llm_must_not_invent": generic_must_not_invent(),
        }


class EqualLengthRayPathReductionRoleBinder:
    """Binder for equal-length ray path reduction teaching drafts."""

    def bind(
        self,
        *,
        recipe_spec: RecipeSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        return _equal_length_ray_path_reduction_draft(recipe_spec.explanation, group, snapshot)


def recipe_role_binders() -> dict[str, RecipeRoleBinder]:
    return {
        "generic_recipe": GenericRecipeRoleBinder(),
        "equal_length_ray_path_reduction": EqualLengthRayPathReductionRoleBinder(),
    }


def _equal_length_ray_path_reduction_draft(
    explanation: RecipeExplanationSpec | None,
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    assert explanation is not None
    facts = _facts_by_handle(snapshot)
    entities = _entities_by_handle(snapshot)
    step = group.step
    read_facts = [
        facts[handle]
        for handle in step.get("reads", [])
        if isinstance(handle, str) and handle in facts
    ]
    ray_fact = _first_fact(read_facts, "point_on_ray")
    segment_fact = _first_fact(read_facts, "point_on_segment")
    equal_fact = _first_fact(read_facts, "equal_length_condition")
    target_fact = _first_fact(read_facts, "path_minimum_target")

    roles: dict[str, Any] = {}
    unbound: list[str] = []
    if ray_fact and segment_fact:
        ray_entity = entities.get(str(ray_fact.get("ray", "")), {})
        segment_entity = entities.get(str(segment_fact.get("segment", "")), {})
        anchor = str(ray_entity.get("origin", ""))
        ray_direction = str(ray_entity.get("through", ""))
        segment_moving = str(segment_fact.get("point", ""))
        ray_moving = str(ray_fact.get("point", ""))
        reference = _segment_reference_point(segment_entity, anchor)
        _bind_role(roles, "anchor", anchor, entities)
        _bind_role(roles, "segment_moving_point", segment_moving, entities)
        _bind_role(roles, "ray_moving_point", ray_moving, entities)
        _bind_role(roles, "segment_reference_point", reference, entities)
        _bind_role(roles, "ray_direction_point", ray_direction, entities)
        fixed = _fixed_point_from_path_target(
            target_fact,
            segment_moving=_label_for_handle(segment_moving, entities),
            ray_moving=_label_for_handle(ray_moving, entities),
            reference=_label_for_handle(reference, entities),
            group=group,
            entities=entities,
        )
        _bind_role(roles, "fixed_point", fixed, entities)
        auxiliary = _auxiliary_label(entities)
        roles["auxiliary_point"] = {
            "label": auxiliary,
            "explanation_only_label": True,
        }
        _bind_path_roles(
            roles,
            fixed=_label_for_handle(fixed, entities),
            segment_moving=_label_for_handle(segment_moving, entities),
            ray_moving=_label_for_handle(ray_moving, entities),
            reference=_label_for_handle(reference, entities),
            auxiliary=auxiliary,
            target_fact=target_fact,
        )
        roles["ray_name"] = str(ray_entity.get("name") or handle_name(str(ray_fact.get("ray", ""))))
        if equal_fact:
            roles["equal_length_fact"] = str(equal_fact.get("description") or equal_fact.get("handle"))
    else:
        unbound.extend(["point_on_ray", "point_on_segment"])

    for role in explanation.role_schema:
        if role not in roles and role not in {
            "ray_name",
            "equal_length_fact",
            "minimum_expression",
        }:
            unbound.append(role)
    minimum_expression = _minimum_expression_from_distance_trace(group)
    if minimum_expression:
        roles["minimum_expression"] = minimum_expression
    proof = [
        format_template(template, roles)
        for template in explanation.proof_outline_templates
    ]
    substep_drafts = _equal_length_ray_path_substep_drafts(
        explanation,
        roles=roles,
        unbound=sorted(dict.fromkeys(unbound)),
    )
    draft = {
        "confidence": "complete" if not unbound else "partial",
        "bound_roles": roles,
        "unbound_roles": sorted(dict.fromkeys(unbound)),
        "student_intent_draft": format_template(
            explanation.student_intent_template,
            roles,
        ),
        "proof_draft": proof,
        "substep_drafts": substep_drafts,
        "recommended_lesson_splits": list(explanation.recommended_lesson_splits),
        "llm_can_complete": list(explanation.allowed_llm_completion),
        "llm_must_not_invent": generic_must_not_invent()
        + [
            "不要把讲解用辅助点当作 StepIntent creates 或 runtime fact。",
            "如果 proof_draft 中仍有占位符，只能用泛称解释，不能自造具体点名。",
        ],
    }
    substep_id = getattr(group, "teaching_substep_id", None)
    if substep_id:
        for substep in substep_drafts:
            if substep.get("teaching_substep_id") == substep_id:
                return {
                    **substep,
                    "parent_recipe_id": "equal_length_ray_path_reduction",
                    "all_substep_ids": [
                        str(item.get("teaching_substep_id"))
                        for item in substep_drafts
                    ],
                }
    return draft


def _equal_length_ray_path_substep_drafts(
    explanation: RecipeExplanationSpec,
    *,
    roles: dict[str, Any],
    unbound: list[str],
) -> list[dict[str, Any]]:
    common = {
        "confidence": "complete" if not unbound else "partial",
        "bound_roles": roles,
        "unbound_roles": unbound,
        "llm_can_complete": list(explanation.allowed_llm_completion),
        "llm_must_not_invent": generic_must_not_invent()
        + [
            "不要把讲解用辅助点当作 StepIntent creates 或 runtime fact。",
            "如果 proof_draft 中仍有占位符，只能用泛称解释，不能自造具体点名。",
        ],
    }
    reduction_proof = [
        format_template(template, roles)
        for template in explanation.proof_outline_templates
    ]
    minimum_templates = (
        "由上一步已经得到 {original_path} = {reduced_path}。",
        "转化后只剩一个动点，路径最小值对应两端点间的最短线段 {minimum_segment}。",
        "由已验算的距离计算，得到最小值表达式 {minimum_expression}。",
    )
    minimum_proof = [
        format_template(template, roles)
        for template in minimum_templates
    ]
    return [
        {
            **common,
            "teaching_substep_id": "path_reduction",
            "student_intent_draft": "构造等长辅助点，证明原路径中的一段距离可以被替换。",
            "proof_draft": reduction_proof,
            "box": [
                format_template("{original_path} = {reduced_path}", roles),
            ],
        },
        {
            **common,
            "teaching_substep_id": "minimum_by_segment",
            "student_intent_draft": "在已经降维的单动点路径中，用两点之间线段最短求最小值表达式。",
            "proof_draft": minimum_proof,
            "box": [
                format_template("路径最小值 = {minimum_expression}", roles)
                if roles.get("minimum_expression")
                else format_template("路径最小值对应 {minimum_segment}", roles),
            ],
        },
    ]


def _facts_by_handle(snapshot: ExplanationSnapshot) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("handle")): item
        for item in snapshot.problem.get("facts", [])
        if isinstance(item, dict) and item.get("handle")
    }


def _entities_by_handle(snapshot: ExplanationSnapshot) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("handle")): item
        for item in snapshot.problem.get("entities", [])
        if isinstance(item, dict) and item.get("handle")
    }


def _first_fact(facts: list[dict[str, Any]], fact_type: str) -> dict[str, Any] | None:
    return next((fact for fact in facts if fact.get("type") == fact_type), None)


def _segment_reference_point(segment_entity: dict[str, Any], anchor: str) -> str:
    endpoints = [
        str(item)
        for item in segment_entity.get("endpoints", [])
    ]
    for endpoint in endpoints:
        if endpoint != anchor:
            return endpoint
    return ""


def _bind_role(
    roles: dict[str, Any],
    role: str,
    handle: str,
    entities: dict[str, dict[str, Any]],
) -> None:
    if not handle:
        return
    roles[role] = {
        "handle": handle,
        "label": _label_for_handle(handle, entities),
    }


def _bind_path_roles(
    roles: dict[str, Any],
    *,
    fixed: str,
    segment_moving: str,
    ray_moving: str,
    reference: str,
    auxiliary: str,
    target_fact: dict[str, Any] | None,
) -> None:
    original_path = str((target_fact or {}).get("path") or "")
    original_replace_segment = _path_term_containing(original_path, (reference, ray_moving))
    if not original_replace_segment:
        original_replace_segment = f"{reference}{ray_moving}"
    replacement_segment = f"{segment_moving}{auxiliary}"
    fixed_segment = _path_term_containing(original_path, (fixed, segment_moving))
    if not fixed_segment:
        fixed_segment = f"{fixed}{segment_moving}"
    reduced_path = f"{fixed_segment}+{replacement_segment}"
    roles["original_replace_segment"] = original_replace_segment
    roles["replacement_segment"] = replacement_segment
    roles["original_path"] = original_path or f"{fixed_segment}+{original_replace_segment}"
    roles["reduced_path"] = reduced_path
    roles["minimum_segment"] = f"{fixed}{auxiliary}"


def _fixed_point_from_path_target(
    target_fact: dict[str, Any] | None,
    *,
    segment_moving: str,
    ray_moving: str,
    reference: str,
    group: LessonCandidateGroup,
    entities: dict[str, dict[str, Any]],
) -> str:
    path = str((target_fact or {}).get("path") or "")
    for term in _path_terms(path):
        if segment_moving in term:
            other = term.replace(segment_moving, "", 1)
            handle = _handle_for_label(other, entities)
            if handle:
                return handle
    excluded = {segment_moving, ray_moving, reference}
    for handle in group.step.get("reads", []):
        if not isinstance(handle, str) or not handle.startswith("point:"):
            continue
        label = _label_for_handle(handle, entities)
        if label and label not in excluded:
            return handle
    return ""


def _path_term_containing(path: str, labels: tuple[str, ...]) -> str:
    for term in _path_terms(path):
        if all(label and label in term for label in labels):
            return term
    return ""


def _path_terms(path: str) -> list[str]:
    return [
        re.sub(r"\s+", "", item)
        for item in re.split(r"[+＋]", path)
        if re.sub(r"\s+", "", item)
    ]


def _minimum_expression_from_distance_trace(group: LessonCandidateGroup) -> str:
    for trace in getattr(group, "traces", ()):
        if getattr(trace, "method_id", "") != "distance_between_points":
            continue
        for fragment in getattr(trace, "trace_fragments", ()):
            if not isinstance(fragment, dict):
                continue
            conclusion = str(fragment.get("conclusion") or "")
            value = minimum_expression_from_conclusion(conclusion)
            if value:
                return value
            calculation = str(fragment.get("calculation") or "")
            if calculation:
                value = after_equals(calculation)
                if value:
                    return value
    return ""


def _label_for_handle(handle: str, entities: dict[str, dict[str, Any]]) -> str:
    entity = entities.get(handle, {})
    if entity.get("name"):
        return str(entity["name"])
    return handle_name(handle)


def _handle_for_label(label: str, entities: dict[str, dict[str, Any]]) -> str:
    if not label:
        return ""
    for handle, entity in entities.items():
        if str(entity.get("name") or handle_name(handle)) == label:
            return handle
    return ""


def _auxiliary_label(entities: dict[str, dict[str, Any]]) -> str:
    used = {str(entity.get("name") or handle_name(handle)) for handle, entity in entities.items()}
    for label in ("G", "P", "Q", "R", "S", "T", "U", "V", "W"):
        if label not in used:
            return label
    index = 1
    while f"Aux{index}" in used:
        index += 1
    return f"Aux{index}"
