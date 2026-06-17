"""Build LLM-facing teaching expansion drafts from method/recipe specs."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodSpec
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.runtime.recipes._spec import RecipeSpec

from .models import ExplanationSnapshot, LessonCandidateGroup
from .role_binders import RoleBinderRegistry
from .role_binders.common import format_template, generic_must_not_invent


def explanation_payload_for_group(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    """Return recipe/method explanation metadata and a teaching draft for a group."""
    payload: dict[str, Any] = {}
    recipe_spec = _recipe_registry().get(group.capability_id)
    if recipe_spec is not None and recipe_spec.explanation is not None:
        payload["recipe_explanation"] = _recipe_explanation_payload(recipe_spec)
        payload["teaching_expansion_draft"] = _recipe_teaching_draft(
            recipe_spec,
            group,
            snapshot,
        )
    method_specs = _method_explanation_specs(group.method_ids)
    if method_specs:
        payload["method_explanation"] = {
            method_id: _method_explanation_payload(spec.explanation)
            for method_id, spec in method_specs.items()
            if spec.explanation is not None
        }
        if "teaching_expansion_draft" not in payload:
            payload["teaching_expansion_draft"] = _method_teaching_draft(
                group,
                method_specs,
                snapshot,
            )
    elif group.method_ids:
        payload["method_explanation"] = {
            method_id: {"confidence": "trace_only"}
            for method_id in group.method_ids
        }
    return payload


@lru_cache(maxsize=1)
def _recipe_registry() -> RecipeSpecRegistry:
    return RecipeSpecRegistry.load_from_code()


@lru_cache(maxsize=1)
def _method_registry() -> MethodSpecRegistry:
    return MethodSpecRegistry.load_from_code()


@lru_cache(maxsize=1)
def _role_binder_registry() -> RoleBinderRegistry:
    return RoleBinderRegistry.default()


def _recipe_explanation_payload(recipe_spec: RecipeSpec) -> dict[str, Any]:
    explanation = recipe_spec.explanation
    assert explanation is not None
    return {
        "recipe_id": recipe_spec.recipe_id,
        "title": recipe_spec.title,
        "summary": recipe_spec.summary,
        "method_sequence": list(recipe_spec.method_sequence),
        **explanation.to_payload(),
    }


def _method_explanation_specs(method_ids: tuple[str, ...]) -> dict[str, MethodSpec]:
    result: dict[str, MethodSpec] = {}
    registry = _method_registry()
    for method_id in method_ids:
        spec = registry.specs.get(method_id)
        if spec is not None and spec.explanation is not None:
            result[method_id] = spec
    return result


def _method_explanation_payload(explanation: MethodExplanationSpec | None) -> dict[str, Any]:
    assert explanation is not None
    return {
        "role_schema": dict(explanation.role_schema),
        "student_goal_template": explanation.student_goal_template,
        "student_title_template": explanation.student_title_template,
        "student_nav_title_template": explanation.student_nav_title_template,
        "student_title_templates_by_goal": dict(explanation.student_title_templates_by_goal),
        "derive_templates": list(explanation.derive_templates),
        "box_templates": list(explanation.box_templates),
        "explanation_level": explanation.explanation_level,
        "role_binding_strategy": explanation.role_binding_strategy,
        "role_binder_id": explanation.role_binder_id,
    }


def _method_teaching_draft(
    group: LessonCandidateGroup,
    method_specs: dict[str, MethodSpec],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    proofs: list[str] = []
    boxes: list[str] = []
    unbound: list[str] = []
    bound_roles: dict[str, Any] = {}
    for method_id in group.method_ids:
        spec = method_specs.get(method_id)
        explanation = spec.explanation if spec is not None else None
        if explanation is None:
            continue
        binder_id = _method_role_binder_id(explanation)
        binder = _role_binder_registry().require_method(binder_id)
        local_roles = binder.bind(
            method_id=method_id,
            explanation=explanation,
            group=group,
            snapshot=snapshot,
        )
        for role in explanation.role_schema:
            if role in local_roles:
                bound_roles[role] = local_roles[role]
            elif role not in unbound:
                unbound.append(role)
        for template in explanation.derive_templates:
            proofs.append(format_template(str(template), local_roles))
        for template in explanation.box_templates:
            box = format_template(str(template), local_roles).strip()
            if box and box not in boxes:
                boxes.append(box)
    if not proofs:
        for trace in group.traces:
            for fragment in trace.trace_fragments:
                if fragment.get("reason"):
                    proofs.append(str(fragment["reason"]))
                if fragment.get("calculation"):
                    proofs.append(str(fragment["calculation"]))
    return {
        "confidence": "complete" if not unbound else "partial",
        "bound_roles": bound_roles,
        "unbound_roles": unbound,
        "proof_draft": proofs,
        "box": boxes,
        "llm_can_complete": [
            "可以把 method 计算草稿改写成更自然的初中数学推导。",
            "可以根据 trace 中的 calculation/conclusion 补充代入、化简、筛选等过渡句。",
        ],
        "llm_must_not_invent": generic_must_not_invent(),
    }


def _recipe_teaching_draft(
    recipe_spec: RecipeSpec,
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    explanation = recipe_spec.explanation
    assert explanation is not None
    binder = _role_binder_registry().require_recipe(explanation.role_binder_id)
    return binder.bind(
        recipe_spec=recipe_spec,
        group=group,
        snapshot=snapshot,
    )


def _method_role_binder_id(explanation: MethodExplanationSpec) -> str:
    if explanation.role_binder_id != "generic_trace":
        return explanation.role_binder_id
    # Compatibility for specs that predate role_binder_id.
    if explanation.role_binding_strategy == "role_name_registry":
        return "role_name_registry"
    return explanation.role_binder_id


__all__ = ["explanation_payload_for_group"]
