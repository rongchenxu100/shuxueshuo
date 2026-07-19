"""Recipe explanation role binders."""

from __future__ import annotations

import re
from typing import Any, Protocol

import sympy as sp

from shuxueshuo_server.solver.runtime.recipes._spec import RecipeExplanationSpec, RecipeSpec
from shuxueshuo_server.solver.student_display import student_math_display as _student_expr

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


class BrokenPathStraighteningMinimumRoleBinder:
    """Binder for one-moving-point broken-path straightening recipes."""

    def bind(
        self,
        *,
        recipe_spec: RecipeSpec,
        group: LessonCandidateGroup,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        return _broken_path_straightening_minimum_draft(
            recipe_spec.explanation,
            group,
            snapshot,
        )


def recipe_role_binders() -> dict[str, RecipeRoleBinder]:
    return {
        "generic_recipe": GenericRecipeRoleBinder(),
        "equal_length_ray_path_reduction": EqualLengthRayPathReductionRoleBinder(),
        "broken_path_straightening_minimum_expression": BrokenPathStraighteningMinimumRoleBinder(),
    }


def _broken_path_straightening_minimum_draft(
    explanation: RecipeExplanationSpec | None,
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    assert explanation is not None
    selected = _selected_straightening_candidate(group, snapshot)
    if not selected:
        return GenericRecipeRoleBinder().bind(
            recipe_spec=RecipeSpec(
                recipe_id="broken_path_straightening_minimum_expression",
                title="将军饮马折线最值",
                summary="",
                method_sequence=(),
                execution_strategy="",
                outputs={},
                explanation=explanation,
            ),
            group=group,
            snapshot=snapshot,
        )

    source = str(selected.get("reflect_source") or "")
    reflected = _student_point_label(str(selected.get("reflected_point_name") or ""))
    moving = str(selected.get("moving_point") or "")
    other = str(selected.get("other_fixed_point") or "")
    transformed_path = _student_path_label(str(selected.get("transformed_path") or ""))
    straightened_path = _student_path_label(str(selected.get("straightened_path") or ""))
    segment_equality = _student_path_label(str(selected.get("segment_equality") or ""))
    minimum_segment = _student_path_label(str(selected.get("minimum_segment") or ""))
    moving_locus = _student_line_label(str(selected.get("moving_line") or ""))
    reflected_pair = _point_pair_from_value(selected.get("reflected_point"))
    reflected_text = _point_text(reflected, reflected_pair) if reflected_pair else ""
    minimum_expression = _minimum_expression_from_distance_trace(group) or _minimum_expression_from_fact(
        group,
        snapshot,
    )
    minimum_display = _student_expr(minimum_expression, fullwidth_operators=True) if minimum_expression else ""
    distance_formula = _straightening_distance_formula(
        selected,
        minimum_segment=minimum_segment,
        minimum_display=minimum_display,
    )
    roles: dict[str, Any] = {
        "moving_point": moving,
        "moving_locus": moving_locus,
        "source_point": source,
        "reflected_point": reflected,
        "other_fixed_point": other,
        "transformed_path": transformed_path,
        "straightened_path": straightened_path,
        "segment_equality": segment_equality,
        "straightened_segment": minimum_segment,
        "minimum_expression": minimum_display,
    }
    if reflected_text:
        roles["reflected_point_coordinate"] = reflected_text
    if distance_formula:
        roles["distance_formula"] = distance_formula

    proof_templates: list[str] = [
        "∵由上一步，{transformed_path} 是等价后的单动点折线。",
        "∵{moving_point} 在直线 {moving_locus} 上运动。",
        "作 {source_point} 关于 {moving_locus} 的对称点 {reflected_point}。",
    ]
    if reflected_text:
        proof_templates.append("∴{reflected_point_coordinate}。")
    proof_templates.extend(
        [
            "∴{segment_equality}。",
            "∴{transformed_path}={straightened_path}。",
            "∴当 {reflected_point}、{moving_point}、{other_fixed_point} 共线时，路径取得最小值 {straightened_segment}。",
        ]
    )
    if distance_formula:
        proof_templates.append("∴{distance_formula}。")
    elif minimum_display:
        proof_templates.append("∴{straightened_segment}={minimum_expression}。")

    proof = [format_template(template, roles) for template in proof_templates]
    box: list[str] = []
    if reflected_text:
        box.append(reflected_text)
    if distance_formula:
        box.append(distance_formula)
    elif minimum_display:
        box.append(format_template("路径最小值＝{minimum_expression}", roles))

    return {
        "confidence": "complete",
        "bound_roles": roles,
        "unbound_roles": [],
        "student_intent_draft": format_template(
            explanation.student_intent_template,
            roles,
        ),
        "proof_draft": proof,
        "box": box,
        "recommended_lesson_splits": list(explanation.recommended_lesson_splits),
        "llm_can_complete": list(explanation.allowed_llm_completion),
        "llm_must_not_invent": generic_must_not_invent()
        + [
            "不得改变选中的对称点、最短线段端点或最小值表达式。",
            "不得把未选中的拉直候选写成最终方案。",
        ],
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
        roles["minimum_expression_display"] = _student_expr(minimum_expression)
    roles.update(_minimum_segment_calculation_roles(group, snapshot, roles, entities))
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
    )
    if roles.get("auxiliary_coordinate"):
        minimum_templates += (
            "由 {auxiliary_equal_length} 且 {auxiliary_point} 在 {ray_name} 上，得到 {auxiliary_coordinate}。",
        )
    if roles.get("minimum_distance_formula"):
        minimum_templates += ("{minimum_distance_formula}。",)
    else:
        minimum_templates += (
            "由已验算的距离计算，得到最小值表达式 {minimum_expression_display}。",
        )
    minimum_proof = [
        format_template(template, roles)
        for template in minimum_templates
    ]
    minimum_box = []
    if roles.get("auxiliary_coordinate"):
        minimum_box.append(format_template("{auxiliary_coordinate}", roles))
    if roles.get("minimum_expression_display"):
        minimum_box.append(format_template("路径最小值 = {minimum_expression_display}", roles))
    elif roles.get("minimum_expression"):
        minimum_box.append(format_template("路径最小值 = {minimum_expression}", roles))
    else:
        minimum_box.append(format_template("路径最小值对应 {minimum_segment}", roles))
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
            "box": minimum_box,
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


def _selected_straightening_candidate(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    scored: list[tuple[int, dict[str, Any]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict):
            continue
        if item.get("type") != "StraighteningCandidate":
            continue
        if item.get("source") != "select_straightening_candidate":
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        scope_id = str(item.get("scope_id") or "")
        score = 1
        if scope_id == group.step_id:
            score += 4
        if scope_id == group.scope_id:
            score += 3
        if _scope_root(scope_id) == _scope_root(group.scope_id):
            score += 1
        scored.append((score, value))
    if not scored:
        return {}
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1]


def _scope_root(scope_id: str | None) -> str:
    if not scope_id:
        return "problem"
    text = str(scope_id)
    return text.split("_", 1)[0] or "problem"


def _student_point_label(label: str) -> str:
    return str(label).replace("_prime", "′")


def _student_path_label(text: str) -> str:
    return _student_point_label(str(text)).replace(" ", "")


def _student_line_label(text: str) -> str:
    raw = str(text).strip()
    if raw.startswith("y="):
        expr = _sympify(raw.split("=", 1)[1])
        if expr is not None:
            return f"y＝{_student_expr(sp.factor(expr), fullwidth_operators=True, simplify_sympy=False)}"
    return _student_path_label(raw).replace("=", "＝")


def _minimum_expression_from_fact(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    scored: list[tuple[int, str]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "MinimumExpression":
            continue
        if item.get("source") != "distance_between_points":
            continue
        value = str(item.get("value") or "")
        if not value:
            continue
        scope_id = str(item.get("scope_id") or "")
        score = 1
        if scope_id == group.step_id:
            score += 4
        if scope_id == group.scope_id:
            score += 3
        if _scope_root(scope_id) == _scope_root(group.scope_id):
            score += 1
        scored.append((score, value))
    if not scored:
        return ""
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[0][1]


def _straightening_distance_formula(
    selected: dict[str, Any],
    *,
    minimum_segment: str,
    minimum_display: str,
) -> str:
    endpoints = selected.get("minimum_endpoints")
    if not isinstance(endpoints, list | tuple) or len(endpoints) != 2:
        return f"{minimum_segment}＝{minimum_display}" if minimum_segment and minimum_display else ""
    p1 = _point_pair_from_value(endpoints[0])
    p2 = _point_pair_from_value(endpoints[1])
    if p1 is None or p2 is None:
        return f"{minimum_segment}＝{minimum_display}" if minimum_segment and minimum_display else ""
    dx = sp.simplify(p2[0] - p1[0])
    dy = sp.simplify(p2[1] - p1[1])
    distance = minimum_display
    if not distance:
        distance = _student_expr(sp.sqrt(dx**2 + dy**2), fullwidth_operators=True)
    return (
        f"{minimum_segment}＝"
        f"√(({_student_expr(sp.factor(dx), fullwidth_operators=True, simplify_sympy=False)})²"
        f"＋({_student_expr(sp.factor(dy), fullwidth_operators=True, simplify_sympy=False)})²)＝{distance}"
    )


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


def _minimum_segment_calculation_roles(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
    roles: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    auxiliary = _point_pair_for_auxiliary(group, snapshot)
    fixed = _point_pair_for_role("fixed_point", group, snapshot, roles, entities)
    if auxiliary is None or fixed is None:
        return {}
    aux_label = str((roles.get("auxiliary_point") or {}).get("label") or "辅助点")
    fixed_label = str((roles.get("fixed_point") or {}).get("label") or "固定点")
    anchor_label = str((roles.get("anchor") or {}).get("label") or "")
    reference_label = str((roles.get("segment_reference_point") or {}).get("label") or "")
    dx = sp.simplify(auxiliary[0] - fixed[0])
    dy = sp.simplify(auxiliary[1] - fixed[1])
    distance = sp.simplify(sp.sqrt(dx**2 + dy**2))
    minimum_expression = roles.get("minimum_expression")
    if minimum_expression:
        parsed_minimum = _sympify(minimum_expression)
        if parsed_minimum is not None:
            distance = sp.simplify(parsed_minimum)
    result = {
        "auxiliary_coordinate": _point_text(aux_label, auxiliary),
        "minimum_distance_formula": (
            f"{fixed_label}{aux_label}=√(({_student_expr(dx)})²+({_student_expr(dy)})²)"
            f"={_student_expr(distance)}"
        ),
    }
    if anchor_label and reference_label:
        result["auxiliary_equal_length"] = f"{anchor_label}{aux_label}={anchor_label}{reference_label}"
    return result


def _point_pair_for_role(
    role: str,
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
    roles: dict[str, Any],
    entities: dict[str, dict[str, Any]],
) -> tuple[sp.Expr, sp.Expr] | None:
    value = roles.get(role)
    if not isinstance(value, dict):
        return None
    handle = str(value.get("handle") or "")
    label = str(value.get("label") or "")
    entity_pair = _point_pair_from_entity(handle, entities)
    if entity_pair is not None:
        return entity_pair
    return _point_pair_for_label(label, group.scope_id, snapshot)


def _point_pair_for_auxiliary(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> tuple[sp.Expr, sp.Expr] | None:
    candidates: list[tuple[int, tuple[sp.Expr, sp.Expr]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        if str(item.get("source") or "") != "equal_length_ray_point":
            continue
        pair = _point_pair_from_value(item.get("value"))
        if pair is None:
            continue
        scope_id = str(item.get("scope_id") or "")
        score = 0
        if scope_id == group.step_id:
            score = 3
        elif scope_id == group.scope_id:
            score = 2
        candidates.append((score, pair))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _point_pair_for_label(
    label: str,
    preferred_scope: str,
    snapshot: ExplanationSnapshot,
) -> tuple[sp.Expr, sp.Expr] | None:
    if not label:
        return None
    candidates: list[tuple[int, tuple[sp.Expr, sp.Expr]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        pair = _point_pair_from_value(item.get("value"))
        if pair is None:
            continue
        name = str(item.get("name") or "")
        handle = str(item.get("handle") or "")
        if name != label and not name.startswith(f"{label}_coordinate") and f":{label}" not in handle:
            continue
        score = 1
        if str(item.get("scope_id") or "") == preferred_scope:
            score += 3
        if item.get("container") == "outputs":
            score += 1
        candidates.append((score, pair))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _point_pair_from_entity(
    handle: str,
    entities: dict[str, dict[str, Any]],
) -> tuple[sp.Expr, sp.Expr] | None:
    entity = entities.get(handle)
    if not entity:
        return None
    coordinate = entity.get("coordinate")
    pair = _point_pair_from_value(coordinate)
    if pair is not None:
        return pair
    if str(entity.get("definition") or "") == "coordinate_origin":
        return (sp.Integer(0), sp.Integer(0))
    return None


def _point_pair_from_value(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    x = _sympify(value[0])
    y = _sympify(value[1])
    if x is None or y is None:
        return None
    return (x, y)


def _sympify(value: Any) -> sp.Expr | None:
    try:
        return sp.sympify(
            str(value).replace("^", "**"),
            locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs},
        )
    except Exception:
        return None


def _point_text(label: str, pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{label}({_student_expr(pair[0])},{_student_expr(pair[1])})"


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
