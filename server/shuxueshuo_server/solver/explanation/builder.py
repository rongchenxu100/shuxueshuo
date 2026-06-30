"""EB1 文字版 ExplanationBuilder。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import json
import re
from typing import Any, Protocol

import sympy as sp

from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.student_display import student_math_display

from .models import ExplanationSnapshot, LessonCandidateGroup, LessonIR, LessonSection, LessonStep, TeachingTraceEntry
from .target_labels import (
    target_point_label_for_group as _target_point_label_for_group,
    target_point_labels_from_groups_and_pieces as _target_point_labels_for_groups,
)
from .teaching_expansion import explanation_payload_for_group


class LessonIRValidationError(ValueError):
    """LessonIR 校验失败。"""


@dataclass(frozen=True)
class LessonDraftBlocker:
    """LessonIR draft 的可修复 blocker。"""

    code: str
    message: str
    step_id: str = ""
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.step_id:
            payload["step_id"] = self.step_id
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class LessonDraftDiagnostic:
    """LessonIR draft 诊断摘要。"""

    accepted_steps: tuple[dict[str, Any], ...] = ()
    blockers: tuple[LessonDraftBlocker, ...] = ()
    warnings: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "accepted_steps": list(self.accepted_steps),
            "blockers": [item.to_payload() for item in self.blockers],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class LessonDraftValidationResult:
    """LessonIR draft 规范化和校验结果。"""

    lesson: LessonIR | None
    normalized_lesson_draft: dict[str, Any] | None
    diagnostic: LessonDraftDiagnostic

    @property
    def ok(self) -> bool:
        return self.lesson is not None and not self.diagnostic.blockers


class LessonTextPlanner(Protocol):
    """受限文本 planner 接口。

    实现可以是真实 LLM，也可以是测试用 mock。它只允许返回文字字段；结构字段由
    ExplanationBuilder 固定。
    """

    def plan_text(
        self,
        *,
        group: "LessonCandidateGroup",
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        ...


class LessonDraftPlanner(Protocol):
    """整份 LessonIR 的受限 planner，可由 LLM 实现 step 分组和文字优化。"""

    def plan_lesson(
        self,
        *,
        groups: tuple["LessonCandidateGroup", ...],
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LessonMergeRule:
    """相邻 capability 合并规则的唯一事实源。"""

    rule_id: str
    sequence: tuple[str, ...]
    title_hint: str
    nav_title_hint: str
    reason: str


@dataclass(frozen=True)
class DuplicateLessonStepMergeRule:
    """同一 recipe 连续产出重复讲解步骤时的合并规则。"""

    capability_ids: tuple[str, ...]
    title: str
    nav_title: str


LESSON_MERGE_RULES: tuple[LessonMergeRule, ...] = (
    LessonMergeRule(
        rule_id="simple_quadratic_foundation",
        sequence=(
            "quadratic_from_constraints",
            "quadratic_vertex_point",
            "quadratic_x_axis_intercept_point",
        ),
        title_hint="代入已知条件，求解析式、顶点和 x 轴交点",
        nav_title_hint="求解析式、顶点和交点",
        reason="同一小问内的二次函数基础信息计算较短，合并后更符合学生阅读粒度。",
    ),
    LessonMergeRule(
        rule_id="quadratic_foundation_axis_point",
        sequence=(
            "quadratic_from_constraints",
            "quadratic_axis_x_intercept_point",
        ),
        title_hint="化简函数解析式，求对称轴与X轴交点",
        nav_title_hint="化简解析式求交点",
        reason="对称轴与 x 轴交点是由当前抛物线直接读出的短结论，通常应和解析式步骤合并。",
    ),
    LessonMergeRule(
        rule_id="axis_parameter_square_adjacent_locus",
        sequence=(
            "quadratic_axis_parameterized_point",
            "square_adjacent_vertex_from_side",
            "parameterized_point_locus_line",
        ),
        title_hint="正方形求顶点轨迹",
        nav_title_hint="正方形求顶点轨迹",
        reason="设参数点、用正方形表示相邻顶点、读出该点轨迹直线是连续的短推导，合并后学生更容易看出参数如何消去。",
    ),
    LessonMergeRule(
        rule_id="axis_parameter_square_adjacent",
        sequence=(
            "quadratic_axis_parameterized_point",
            "square_adjacent_vertex_from_side",
        ),
        title_hint="设对称轴上的参数点，并由正方形边求相邻顶点",
        nav_title_hint="参数点与正方形顶点",
        reason="设参数点本身较短，通常应和紧随其后的正方形相邻顶点表达合并。",
    ),
    LessonMergeRule(
        rule_id="parameter_value_point_evaluation_minimum_point",
        sequence=(
            "parameter_from_expression_value",
            "evaluate_point_at_parameter",
            "line_locus_minimum_point",
        ),
        title_hint="由最小值反求参数，并求点坐标",
        nav_title_hint="反求参数求点",
        reason="反求参数、代入含参点、再由轨迹确定最短状态动点是同一个最值收束动作，合并后标题需要点明求出的点。",
    ),
    LessonMergeRule(
        rule_id="parameter_value_point_evaluation",
        sequence=(
            "parameter_from_expression_value",
            "evaluate_point_at_parameter",
        ),
        title_hint="由表达式取值反求参数，并求点坐标",
        nav_title_hint="反求参数求点",
        reason="表达式取值反求参数后紧接代入含参点坐标，通常应作为同一学生步骤。",
    ),
)


DUPLICATE_LESSON_STEP_MERGE_RULES: tuple[DuplicateLessonStepMergeRule, ...] = (
    DuplicateLessonStepMergeRule(
        capability_ids=("broken_path_straightening_minimum_expression",),
        title="将军饮马计算最小值表达式",
        nav_title="将军饮马算最小值",
    ),
)

_DUPLICATE_LESSON_STEP_MERGE_RULE_BY_CAPABILITIES = {
    rule.capability_ids: rule for rule in DUPLICATE_LESSON_STEP_MERGE_RULES
}


class DeterministicLessonTextPlanner:
    """CI 默认文本 planner：不调用 LLM，直接使用 verified trace。"""

    def plan_text(
        self,
        *,
        group: "LessonCandidateGroup",
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        step = group.step
        draft_payload = explanation_payload_for_group(group, snapshot)
        draft = draft_payload.get("teaching_expansion_draft")
        draft_boxes = tuple(
            str(item)
            for item in (draft.get("box", ()) if isinstance(draft, dict) else ())
            if str(item)
        )
        if isinstance(draft, dict):
            proof = _proof_draft_derive_items(draft.get("proof_draft", ()))
            if proof:
                return {
                    "title": group.teaching_substep_title
                    or str(draft.get("student_title") or "")
                    or _short_title(step),
                    "nav_title": group.teaching_substep_nav_title
                    or str(draft.get("student_nav_title") or "")
                    or _nav_title_for_recipe(str(step.get("recipe_hint") or "")),
                    "goal": str(draft.get("student_intent_draft") or group.teaching_focus or ""),
                    "derive": proof,
                    "box": draft_boxes or _produced_boxes(step),
                }
        title = group.teaching_substep_title or _short_title(step)
        nav_title = group.teaching_substep_nav_title or _nav_title_for_recipe(str(step.get("recipe_hint") or ""))
        goal = str(step.get("strategy") or step.get("goal_type") or "推进当前解题步骤")
        derive = []
        if step.get("reason"):
            derive.append(("因为", str(step["reason"])))
        if step.get("strategy"):
            derive.append(("所以", str(step["strategy"])))
        if not derive:
            methods = "、".join(group.method_ids) or str(step.get("recipe_hint") or "method")
            derive.append(("执行", f"使用 {methods} 得到当前结论"))
        return {
            "title": title,
            "nav_title": nav_title,
            "goal": goal,
            "derive": derive,
            "box": draft_boxes or _produced_boxes(step),
        }


class ExplanationBuilder:
    """从 ExplanationSnapshot 构建 EB1 LessonIR。"""

    def __init__(
        self,
        text_planner: LessonTextPlanner | None = None,
        lesson_planner: LessonDraftPlanner | None = None,
    ) -> None:
        self.text_planner = text_planner or DeterministicLessonTextPlanner()
        self.lesson_planner = lesson_planner

    def build_lesson(self, snapshot: ExplanationSnapshot) -> LessonIR:
        groups = tuple(_build_lesson_groups(snapshot))
        if self.lesson_planner is not None:
            try:
                planned = self.lesson_planner.plan_lesson(
                    groups=groups,
                    snapshot=snapshot,
                )
                lesson = _lesson_from_llm_draft(planned, groups, snapshot)
                LessonIRValidator().validate(lesson, snapshot)
                return lesson
            except Exception:
                # LLM 讲解失败不影响 EB1：回退到 deterministic skeleton。
                pass
        group_clusters = _deterministic_lesson_group_clusters(groups)
        steps = []
        rendered_answer_boxes: set[str] = set()
        for index, source_groups in enumerate(group_clusters):
            if len(source_groups) == 1:
                group = source_groups[0]
                fallback = DeterministicLessonTextPlanner().plan_text(
                    group=group,
                    snapshot=snapshot,
                )
                try:
                    planned = self.text_planner.plan_text(group=group, snapshot=snapshot)
                    text = _validate_text_output(planned, snapshot)
                except Exception:
                    text = fallback
                    text.setdefault("gaps", []).append("lesson_text_planner_fallback")
            else:
                text = _deterministic_merged_text(source_groups, snapshot)
            step_answer_boxes = _answer_boxes_for_groups(source_groups, snapshot.answers)
            if len(source_groups) == 1 and source_groups[0].teaching_substep_id and text.get("box"):
                step_answer_boxes = ()
            if step_answer_boxes:
                text["box"] = _merge_answer_boxes(
                    text.get("box", ()),
                    step_answer_boxes,
                    snapshot.answers,
                )
            rendered_answer_boxes.update(
                _rendered_answer_box_fingerprints(text.get("box", ()), snapshot.answers)
            )
            if index == len(group_clusters) - 1:
                missing_answers = _missing_answer_boxes(snapshot.answers, rendered_answer_boxes)
                text["box"] = _merge_answer_boxes(
                    text.get("box", ()),
                    missing_answers,
                    snapshot.answers,
                )
            steps.append(_lesson_step_from_source_groups(source_groups, text))
        lesson = LessonIR(
            problem_id=snapshot.problem_id,
            family_id=snapshot.family_id,
            sections=_build_sections(steps),
            steps=tuple(steps),
        )
        LessonIRValidator().validate(lesson, snapshot)
        return lesson


def _proof_draft_derive_items(raw: Any) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if not isinstance(raw, tuple | list):
        return items
    for item in raw:
        text = str(item).strip()
        if not text:
            continue
        match = re.match(r"^(作|设|∵|∴)\s*(.*)$", text)
        if match:
            label, body = match.groups()
            if body.strip():
                items.append((label, body.strip()))
            continue
        items.append(("说明", text))
    return items


class LessonIRValidator:
    """LessonIR 的安全和引用校验。"""

    def validate(self, lesson: LessonIR, snapshot: ExplanationSnapshot) -> None:
        payload = lesson.to_payload()
        text = str(payload)
        for forbidden in ("$problem.", "$question.", "$subquestion.", "<html", "<svg", "<script"):
            if forbidden in text:
                raise LessonIRValidationError(f"LessonIR contains forbidden content: {forbidden}")
        source_ids = {step["step_id"] for step in snapshot.effective_steps}
        trace_ids = {entry.trace_id for entry in snapshot.teaching_trace}
        allowed_handles = _allowed_handles(snapshot)
        for step in lesson.steps:
            unknown_sources = sorted(set(step.source_step_ids) - source_ids)
            if unknown_sources:
                raise LessonIRValidationError(f"unknown source_step_ids: {unknown_sources}")
            unknown_traces = sorted(set(step.trace_refs) - trace_ids)
            if unknown_traces:
                raise LessonIRValidationError(f"unknown trace_refs: {unknown_traces}")
            unknown_handles = sorted(_handle_refs(step.to_payload()) - allowed_handles)
            if unknown_handles:
                raise LessonIRValidationError(f"unknown handle refs: {unknown_handles}")
            _assert_student_readable_box(step.box)
        _assert_answers_present(lesson, snapshot.answers)


def _build_lesson_groups(snapshot: ExplanationSnapshot) -> list[LessonCandidateGroup]:
    traces_by_step: dict[str, list[TeachingTraceEntry]] = defaultdict(list)
    for entry in snapshot.teaching_trace:
        traces_by_step[entry.source_step_id].append(entry)
    groups = []
    for step in snapshot.effective_steps:
        traces = tuple(traces_by_step.get(str(step["step_id"]), ()))
        if traces and all(entry.hidden_reason for entry in traces):
            continue
        groups.extend(_split_lesson_group(LessonCandidateGroup(step, traces)))
    return groups


def _deterministic_lesson_group_clusters(
    groups: tuple[LessonCandidateGroup, ...],
) -> tuple[tuple[LessonCandidateGroup, ...], ...]:
    clusters: list[tuple[LessonCandidateGroup, ...]] = []
    index = 0
    while index < len(groups):
        _, cluster = lesson_merge_cluster_at(groups, index)
        if cluster:
            clusters.append(cluster)
            index += len(cluster)
            continue
        clusters.append((groups[index],))
        index += 1
    return tuple(clusters)


def lesson_merge_cluster_at(
    groups: tuple[LessonCandidateGroup, ...],
    start: int,
) -> tuple[LessonMergeRule | None, tuple[LessonCandidateGroup, ...]]:
    for rule in LESSON_MERGE_RULES:
        selected = _capability_sequence_cluster(groups, start, rule.sequence)
        if selected:
            return rule, selected
    return None, ()


def _capability_sequence_cluster(
    groups: tuple[LessonCandidateGroup, ...],
    start: int,
    sequence: tuple[str, ...],
) -> tuple[LessonCandidateGroup, ...]:
    end = start + len(sequence)
    if end > len(groups):
        return ()
    selected = groups[start:end]
    if tuple(group.capability_id for group in selected) != sequence:
        return ()
    if any(group.teaching_substep_id for group in selected):
        return ()
    if len({group.scope_id for group in selected}) != 1:
        return ()
    return tuple(selected)


def _split_lesson_group(group: LessonCandidateGroup) -> tuple[LessonCandidateGroup, ...]:
    """把单个 executable step 拆成更细的学生认知步骤。

    拆分边界来自 recipe explanation spec；method 是默认最小讲解单元。
    """
    spec = _recipe_spec_for_group(group)
    explanation = spec.explanation if spec is not None else None
    substeps = explanation.teaching_substep_specs if explanation is not None else ()
    if not substeps:
        return (group,)
    return tuple(
        LessonCandidateGroup(
            group.step,
            group.traces,
            teaching_substep_id=substep.substep_id,
            teaching_substep_title=substep.title,
            teaching_substep_nav_title=substep.nav_title,
            teaching_substep_title_required_terms=substep.title_required_terms,
            teaching_substep_nav_title_required_terms=substep.nav_title_required_terms,
            teaching_focus=substep.focus,
            preferred_method_ids=substep.preferred_method_ids,
            forbid_merge_with_sibling_substeps=substep.forbid_merge_with_sibling_substeps,
        )
        for substep in substeps
    )


def _recipe_spec_for_group(group: LessonCandidateGroup):
    return _recipe_registry_for_builder().get(group.capability_id)


@lru_cache(maxsize=1)
def _recipe_registry_for_builder() -> RecipeSpecRegistry:
    return RecipeSpecRegistry.load_from_code()


def _lesson_step_from_group(group: LessonCandidateGroup, text: dict[str, Any]) -> LessonStep:
    return _lesson_step_from_source_groups((group,), text)


def _lesson_step_from_source_groups(
    source_groups: tuple[LessonCandidateGroup, ...],
    text: dict[str, Any],
) -> LessonStep:
    source_groups_list = list(source_groups)
    title = _student_title_for_source_groups(source_groups_list, text)
    nav_title = _student_nav_title_for_source_groups(source_groups_list, text, title)
    step_id = _lesson_step_id_for_source_groups(source_groups)
    return LessonStep(
        id=step_id,
        scope_id=source_groups[0].scope_id,
        source_step_ids=tuple(dict.fromkeys(group.step_id for group in source_groups)),
        capability_ids=tuple(dict.fromkeys(group.capability_id for group in source_groups)),
        trace_refs=tuple(
            trace_id
            for group in source_groups
            for trace_id in group.trace_refs
        ),
        title=title,
        goal=_student_goal_text(text.get("goal"), source_groups[0].step.get("target")),
        nav_title=nav_title,
        derive=_derive_items(text.get("derive", ())),
        box=tuple(str(item) for item in text.get("box", ()) if str(item)),
        gaps=tuple(str(item) for item in text.get("gaps", ()) if str(item)),
        teaching_substep_ids=tuple(
            dict.fromkeys(
                group.teaching_substep_id
                for group in source_groups
                if group.teaching_substep_id
            )
        ),
    )


def _lesson_step_id_for_source_groups(
    source_groups: tuple[LessonCandidateGroup, ...],
) -> str:
    if len(source_groups) == 1:
        return f"explain_{source_groups[0].candidate_group_id.replace('.', '_')}"
    rule = _lesson_merge_rule_for_groups(source_groups)
    if rule is not None and rule.rule_id == "simple_quadratic_foundation":
        return f"explain_{source_groups[0].step_id}_foundation"
    joined = "_".join(group.candidate_group_id.replace(".", "_") for group in source_groups)
    return f"explain_{joined}"


def _lesson_merge_rule_for_groups(
    groups: tuple[LessonCandidateGroup, ...],
) -> LessonMergeRule | None:
    capabilities = tuple(group.capability_id for group in groups)
    return _lesson_merge_rule_for_capabilities(capabilities)


def _lesson_merge_rule_for_capabilities(
    capabilities: tuple[str, ...],
) -> LessonMergeRule | None:
    for rule in LESSON_MERGE_RULES:
        if capabilities == rule.sequence:
            return rule
    return None


def _deterministic_merged_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    rule = _lesson_merge_rule_for_groups(source_groups)
    if rule is not None:
        builder = _DETERMINISTIC_MERGE_TEXT_BUILDERS.get(rule.rule_id)
        if builder is not None:
            return builder(source_groups, snapshot)
    fallback = DeterministicLessonTextPlanner().plan_text(
        group=source_groups[0],
        snapshot=snapshot,
    )
    return fallback


def _deterministic_simple_quadratic_foundation_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    pieces = [
        DeterministicLessonTextPlanner().plan_text(group=group, snapshot=snapshot)
        for group in source_groups
    ]
    derive: list[tuple[str, str]] = []
    for piece in pieces:
        derive.extend(_derive_items(piece.get("derive", ())))
    boxes = tuple(str(item) for item in pieces[0].get("box", ()) if str(item))
    return {
        "title": "代入已知条件，求解析式、顶点和 x 轴交点",
        "nav_title": "求解析式、顶点和交点",
        "goal": "先确定当前抛物线，再读出顶点并求与 x 轴的交点。",
        "derive": tuple(derive),
        "box": boxes,
    }


def _deterministic_quadratic_foundation_axis_point_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    pieces = [
        DeterministicLessonTextPlanner().plan_text(group=group, snapshot=snapshot)
        for group in source_groups
    ]
    derive: list[tuple[str, str]] = []
    boxes: list[str] = []
    for piece in pieces:
        derive.extend(_derive_items(piece.get("derive", ())))
        boxes.extend(str(item) for item in piece.get("box", ()) if str(item))
    prefix_title = str(pieces[0].get("title") or "求函数解析式")
    prefix_nav = str(pieces[0].get("nav_title") or "求解析式")
    axis_label = _target_point_label_for_group(source_groups[1])
    axis_title = f"求对称轴与X轴交点{axis_label}" if axis_label else "求对称轴与X轴交点"
    nav_title = f"{prefix_nav}求{axis_label}" if axis_label else f"{prefix_nav}和对称轴交点"
    return {
        "title": f"{prefix_title}，{axis_title}",
        "nav_title": nav_title,
        "goal": "先确定当前抛物线，再求对称轴与 x 轴的交点。",
        "derive": tuple(derive),
        "box": tuple(dict.fromkeys(boxes)),
    }


def _deterministic_axis_parameter_square_adjacent_locus_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    pieces = [
        DeterministicLessonTextPlanner().plan_text(group=group, snapshot=snapshot)
        for group in source_groups[:2]
    ]
    derive: list[tuple[str, str]] = []
    boxes: list[str] = []
    for piece in pieces:
        derive.extend(_derive_items(piece.get("derive", ())))
        boxes.extend(str(item) for item in piece.get("box", ()) if str(item))
    line_display = _locus_line_display_for_group(source_groups[2], snapshot)
    point_label = _locus_point_label_for_group(source_groups[2])
    if line_display and point_label:
        derive.append(("∴", f"{point_label} 始终在直线 {line_display} 上"))
        boxes.append(line_display)
    else:
        fallback_piece = DeterministicLessonTextPlanner().plan_text(
            group=source_groups[2],
            snapshot=snapshot,
        )
        derive.extend(_derive_items(fallback_piece.get("derive", ())))
        boxes.extend(str(item) for item in fallback_piece.get("box", ()) if str(item))
        pieces.append(fallback_piece)
    target_label = (
        point_label
        or _target_point_label_for_group(source_groups[1])
        or _last_target_point_label_for_groups(source_groups, pieces)
    )
    title = f"正方形求顶点{target_label}轨迹" if target_label else "正方形求顶点轨迹"
    return {
        "title": title,
        "nav_title": title,
        "goal": "先用参数表示对称轴上的点，再由正方形关系表示顶点，并确定该顶点的轨迹直线。",
        "derive": tuple(derive),
        "box": tuple(dict.fromkeys(boxes)),
    }


def _deterministic_axis_parameter_square_adjacent_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    pieces = [
        DeterministicLessonTextPlanner().plan_text(group=group, snapshot=snapshot)
        for group in source_groups
    ]
    derive: list[tuple[str, str]] = []
    boxes: list[str] = []
    for piece in pieces:
        derive.extend(_derive_items(piece.get("derive", ())))
        boxes.extend(str(item) for item in piece.get("box", ()) if str(item))
    square_piece = _piece_for_capability(source_groups, pieces, "square_adjacent_vertex_from_side")
    title = str(square_piece.get("title") or "由正方形边求相邻顶点")
    nav_title = str(square_piece.get("nav_title") or _nav_title_from_title(title))
    return {
        "title": title,
        "nav_title": nav_title,
        "goal": "先用参数表示对称轴上的点，再利用正方形相邻边关系表示另一个顶点。",
        "derive": tuple(derive),
        "box": tuple(dict.fromkeys(boxes)),
    }


def _deterministic_parameter_value_point_evaluation_minimum_point_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    pieces = [
        DeterministicLessonTextPlanner().plan_text(group=group, snapshot=snapshot)
        for group in source_groups
    ]
    derive: list[tuple[str, str]] = []
    boxes: list[str] = []
    for piece in pieces:
        derive.extend(_derive_items(piece.get("derive", ())))
        boxes.extend(str(item) for item in piece.get("box", ()) if str(item))
    labels = _target_point_labels_for_groups(source_groups, pieces)
    labels_text = "、".join(labels)
    title = f"由最小值反求参数，并求{labels_text}坐标" if labels_text else "由最小值反求参数，并求点坐标"
    nav_title = f"反求参数求{labels_text}" if labels_text else "反求参数求点"
    return {
        "title": title,
        "nav_title": nav_title,
        "goal": "先由最小值条件反求参数，再把参数代入含参点坐标，并确定最短状态下的动点。",
        "derive": tuple(derive),
        "box": _dedupe_visible_texts(boxes),
    }


def _deterministic_parameter_value_point_evaluation_text(
    source_groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any]:
    pieces = [
        DeterministicLessonTextPlanner().plan_text(group=group, snapshot=snapshot)
        for group in source_groups
    ]
    derive: list[tuple[str, str]] = []
    boxes: list[str] = []
    for piece in pieces:
        derive.extend(_derive_items(piece.get("derive", ())))
        boxes.extend(str(item) for item in piece.get("box", ()) if str(item))
    labels = _target_point_labels_for_groups(source_groups, pieces)
    labels_text = "、".join(labels)
    return {
        "title": f"由表达式取值反求参数，并求{labels_text}坐标" if labels_text else "由表达式取值反求参数，并代入求点坐标",
        "nav_title": f"反求参数求{labels_text}" if labels_text else "反求参数并代入",
        "goal": "先由表达式取值条件反求参数，再把参数代入含参点坐标。",
        "derive": tuple(derive),
        "box": _dedupe_visible_texts(boxes),
    }


_DETERMINISTIC_MERGE_TEXT_BUILDERS = {
    "simple_quadratic_foundation": _deterministic_simple_quadratic_foundation_text,
    "quadratic_foundation_axis_point": _deterministic_quadratic_foundation_axis_point_text,
    "axis_parameter_square_adjacent_locus": _deterministic_axis_parameter_square_adjacent_locus_text,
    "axis_parameter_square_adjacent": _deterministic_axis_parameter_square_adjacent_text,
    "parameter_value_point_evaluation_minimum_point": _deterministic_parameter_value_point_evaluation_minimum_point_text,
    "parameter_value_point_evaluation": _deterministic_parameter_value_point_evaluation_text,
}


def _piece_for_capability(
    groups: tuple[LessonCandidateGroup, ...],
    pieces: list[dict[str, Any]],
    capability_id: str,
) -> dict[str, Any]:
    for group, piece in zip(groups, pieces, strict=False):
        if group.capability_id == capability_id:
            return piece
    return pieces[-1] if pieces else {}


def _locus_line_display_for_group(
    group: LessonCandidateGroup,
    snapshot: ExplanationSnapshot,
) -> str:
    for handle, fact in snapshot.fact_index.items():
        if not str(handle).startswith("runtime:"):
            continue
        if not isinstance(fact, dict) or fact.get("type") != "Line":
            continue
        if str(fact.get("scope_id") or "") != str(group.step_id):
            continue
        line = fact.get("value")
        if isinstance(line, dict):
            return _line_equation_display(line)
    return ""


def _line_equation_display(line: dict[str, Any]) -> str:
    equation = str(line.get("equation") or "")
    if "=" not in equation:
        return student_math_display(equation, fullwidth_operators=True)
    left, right = equation.split("=", 1)
    try:
        expr = sp.factor(sp.sympify(right.strip(), locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs}))
        right_text = student_math_display(str(expr), fullwidth_operators=True)
    except Exception:
        right_text = student_math_display(right.strip(), fullwidth_operators=True)
    return f"{left.strip()}＝{right_text}"


def _locus_point_label_for_group(group: LessonCandidateGroup) -> str:
    for handle in group.step.get("reads", ()):
        if not isinstance(handle, str) or not handle.startswith("fact:"):
            continue
        name = handle.rsplit(":", 1)[-1]
        for suffix in ("_parametric_coordinate", "_parameterized_point", "_coordinate"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", name):
            return name
    target = str(group.step.get("target") or "").rsplit(":", 1)[-1]
    for suffix in ("_locus_line", "_line", "_locus"):
        if target.endswith(suffix):
            target = target[: -len(suffix)]
            break
    return target if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", target) else ""


def _last_target_point_label_for_groups(
    groups: tuple[LessonCandidateGroup, ...],
    pieces: list[dict[str, Any]],
) -> str:
    labels = _target_point_labels_for_groups(groups, pieces)
    return labels[-1] if labels else ""


def _answer_boxes_for_groups(
    source_groups: tuple[LessonCandidateGroup, ...],
    answers: dict[str, Any],
) -> tuple[str, ...]:
    boxes: list[str] = []
    for group in source_groups:
        boxes.extend(_answer_boxes_for_step(group.step, answers))
    return tuple(dict.fromkeys(boxes))


def _lesson_from_llm_draft(
    raw: dict[str, Any],
    groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> LessonIR:
    result = validate_lesson_draft(raw, groups, snapshot)
    if result.lesson is None:
        blocker = result.diagnostic.blockers[0] if result.diagnostic.blockers else None
        message = blocker.message if blocker else "lesson planner output is invalid"
        raise LessonIRValidationError(message)
    return result.lesson


def validate_lesson_draft(
    raw: dict[str, Any],
    groups: tuple[LessonCandidateGroup, ...],
    snapshot: ExplanationSnapshot,
) -> LessonDraftValidationResult:
    """规范化并校验 LLM LessonIR draft，返回 repair-friendly diagnostic。"""
    if not isinstance(raw, dict):
        return _lesson_draft_failure(
            "schema_invalid",
            "lesson planner output must be an object",
        )
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return _lesson_draft_failure(
            "schema_invalid",
            "lesson planner output requires non-empty steps",
        )
    groups_by_candidate = {group.candidate_group_id: group for group in groups}
    groups_by_source: dict[str, list[LessonCandidateGroup]] = defaultdict(list)
    for group in groups:
        groups_by_source[group.step_id].append(group)
    lesson_steps: list[LessonStep] = []
    used_candidate_ids: set[str] = set()
    rendered_answer_boxes: set[str] = set()
    accepted_steps: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            return _lesson_draft_failure(
                "schema_invalid",
                "lesson planner steps must be objects",
                accepted_steps=accepted_steps,
                warnings=warnings,
            )
        try:
            source_groups = _source_groups_from_lesson_step(
                raw_step,
                groups_by_candidate=groups_by_candidate,
                groups_by_source=groups_by_source,
                used_candidate_ids=used_candidate_ids,
            )
        except LessonIRValidationError as exc:
            return _lesson_draft_failure(
                _lesson_error_code(str(exc)),
                str(exc),
                step_id=str(raw_step.get("id", "")),
                accepted_steps=accepted_steps,
                warnings=warnings,
            )
        if not source_groups:
            return _lesson_draft_failure(
                "schema_invalid",
                "lesson planner step requires candidate_group_ids or source_step_ids",
                step_id=str(raw_step.get("id", "")),
                accepted_steps=accepted_steps,
                warnings=warnings,
            )
        blocker = _cognitive_merge_blocker(raw_step, source_groups)
        if blocker is not None:
            return _lesson_draft_failure(
                blocker.code,
                blocker.message,
                step_id=blocker.step_id,
                details=blocker.details,
                accepted_steps=accepted_steps,
                warnings=warnings,
            )
        used_candidate_ids.update(group.candidate_group_id for group in source_groups)
        scopes = {group.scope_id for group in source_groups}
        if len(scopes) != 1:
            return _lesson_draft_failure(
                "cross_scope_merge_not_allowed",
                "lesson planner cannot merge different scopes",
                step_id=str(raw_step.get("id", "")),
                accepted_steps=accepted_steps,
                warnings=warnings,
            )
        warnings.extend(_normalization_warnings(raw_step))
        try:
            text = _validate_text_output(raw_step, snapshot)
        except LessonIRValidationError as exc:
            return _lesson_draft_failure(
                _lesson_error_code(str(exc)),
                str(exc),
                step_id=str(raw_step.get("id", "")),
                accepted_steps=accepted_steps,
                warnings=warnings,
            )
        rendered_answer_boxes.update(
            _rendered_answer_box_fingerprints(text.get("box", ()), snapshot.answers)
        )
        if index == len(raw_steps):
            text["box"] = _merge_answer_boxes(
                text.get("box", ()),
                _missing_answer_boxes(snapshot.answers, rendered_answer_boxes),
                snapshot.answers,
            )
        title = _student_title_for_source_groups(source_groups, text)
        nav_title = _student_nav_title_for_source_groups(source_groups, text, title)
        derive_items = _filter_redundant_derive_items(
            _derive_items(text.get("derive", ())),
            source_groups,
        )
        lesson_step = LessonStep(
            id=str(raw_step.get("id") or f"explain_{index}"),
            scope_id=source_groups[0].scope_id,
            source_step_ids=tuple(dict.fromkeys(group.step_id for group in source_groups)),
            capability_ids=tuple(dict.fromkeys(group.capability_id for group in source_groups)),
            trace_refs=tuple(
                trace_id
                for group in source_groups
                for trace_id in group.trace_refs
            ),
            title=title,
            goal=_student_goal_text(text.get("goal"), source_groups[0].step.get("target")),
            nav_title=nav_title,
            derive=derive_items,
            box=tuple(str(item) for item in text.get("box", ()) if str(item)),
            gaps=tuple(str(item) for item in text.get("gaps", ()) if str(item)),
            teaching_substep_ids=tuple(
                dict.fromkeys(
                    group.teaching_substep_id
                    for group in source_groups
                    if group.teaching_substep_id
                )
            ),
        )
        lesson_steps.append(lesson_step)
        accepted_steps.append(_accepted_step_payload(lesson_step, source_groups))
    if not used_candidate_ids:
        return _lesson_draft_failure(
            "schema_invalid",
            "lesson planner did not use any source steps",
            accepted_steps=accepted_steps,
            warnings=warnings,
        )
    missing_candidate_ids = [
        group.candidate_group_id
        for group in groups
        if group.candidate_group_id not in used_candidate_ids
    ]
    if missing_candidate_ids:
        return _lesson_draft_failure(
            "missing_required_candidate_group",
            f"lesson planner omitted candidate_group_ids: {missing_candidate_ids}",
            details={"missing_candidate_group_ids": missing_candidate_ids},
            accepted_steps=accepted_steps,
            warnings=warnings,
            partial_steps=lesson_steps,
        )
    lesson_steps = _merge_adjacent_lesson_steps(lesson_steps)
    lesson = LessonIR(
        problem_id=snapshot.problem_id,
        family_id=snapshot.family_id,
        sections=_build_sections(lesson_steps),
        steps=tuple(lesson_steps),
    )
    try:
        LessonIRValidator().validate(lesson, snapshot)
    except LessonIRValidationError as exc:
        return _lesson_draft_failure(
            _lesson_error_code(str(exc)),
            str(exc),
            accepted_steps=accepted_steps,
            warnings=warnings,
            partial_steps=lesson_steps,
        )
    return LessonDraftValidationResult(
        lesson=lesson,
        normalized_lesson_draft=lesson.to_payload(),
        diagnostic=LessonDraftDiagnostic(
            accepted_steps=tuple(accepted_steps),
            blockers=(),
            warnings=tuple(_dedupe_warnings(warnings)),
        ),
    )


def _merge_adjacent_lesson_steps(
    steps: list[LessonStep],
) -> list[LessonStep]:
    previous: list[LessonStep] | None = None
    current = list(steps)
    while previous != current:
        previous = current
        current = _merge_adjacent_duplicate_recipe_steps(current)
        current = _merge_adjacent_capability_sequence_steps(current)
    return current


def _merge_adjacent_duplicate_recipe_steps(
    steps: list[LessonStep],
) -> list[LessonStep]:
    merged: list[LessonStep] = []
    index = 0
    while index < len(steps):
        current = steps[index]
        duplicates = [current]
        cursor = index + 1
        while cursor < len(steps) and _should_merge_duplicate_recipe_steps(current, steps[cursor]):
            duplicates.append(steps[cursor])
            cursor += 1
        if len(duplicates) == 1:
            merged.append(current)
        else:
            merged.append(_merge_duplicate_recipe_steps(duplicates))
        index = cursor
    return merged


def _should_merge_duplicate_recipe_steps(left: LessonStep, right: LessonStep) -> bool:
    if left.scope_id != right.scope_id:
        return False
    if left.source_step_ids != right.source_step_ids:
        return False
    if left.capability_ids != right.capability_ids:
        return False
    if left.teaching_substep_ids or right.teaching_substep_ids:
        return False
    return _duplicate_lesson_step_merge_rule(left) is not None


def _duplicate_lesson_step_merge_rule(step: LessonStep) -> DuplicateLessonStepMergeRule | None:
    return _DUPLICATE_LESSON_STEP_MERGE_RULE_BY_CAPABILITIES.get(step.capability_ids)


def _merge_adjacent_capability_sequence_steps(
    steps: list[LessonStep],
) -> list[LessonStep]:
    merged: list[LessonStep] = []
    index = 0
    while index < len(steps):
        rule, selected = _lesson_step_merge_rule_at(steps, index)
        if rule is not None and selected:
            merged.append(_merge_lesson_steps_for_rule(rule, selected))
            index += len(selected)
            continue
        merged.append(steps[index])
        index += 1
    return merged


def _lesson_step_merge_rule_at(
    steps: list[LessonStep],
    start: int,
) -> tuple[LessonMergeRule | None, list[LessonStep]]:
    for rule in LESSON_MERGE_RULES:
        selected = _adjacent_steps_for_capability_sequence(steps, start, rule.sequence)
        if selected:
            return rule, selected
    return None, []


def _adjacent_steps_for_capability_sequence(
    steps: list[LessonStep],
    start: int,
    sequence: tuple[str, ...],
) -> list[LessonStep]:
    selected: list[LessonStep] = []
    capabilities: list[str] = []
    scope_id = steps[start].scope_id if start < len(steps) else ""
    for cursor in range(start, len(steps)):
        step = steps[cursor]
        if step.scope_id != scope_id or step.teaching_substep_ids:
            return []
        selected.append(step)
        capabilities.extend(step.capability_ids)
        if len(capabilities) >= len(sequence):
            break
    if len(selected) <= 1 or tuple(capabilities) != sequence:
        return []
    return selected


def _merge_lesson_steps_for_rule(rule: LessonMergeRule, steps: list[LessonStep]) -> LessonStep:
    builder = _LESSON_STEP_MERGE_BUILDERS[rule.rule_id]
    return builder(steps)


def _merge_simple_quadratic_foundation_steps(steps: list[LessonStep]) -> LessonStep:
    return _merge_lesson_step_sequence(
        steps,
        title="代入已知条件，求解析式、顶点和 x 轴交点",
        nav_title="求解析式、顶点和交点",
    )


def _merge_quadratic_foundation_axis_point_steps(steps: list[LessonStep]) -> LessonStep:
    first = steps[0]
    prefix_title = first.title or "求函数解析式"
    prefix_nav = first.nav_title or _nav_title_from_title(prefix_title) or "求解析式"
    axis_label = _last_point_label_from_lesson_steps([steps[-1]])
    axis_title = f"求对称轴与X轴交点{axis_label}" if axis_label else "求对称轴与X轴交点"
    nav_title = f"{prefix_nav}求{axis_label}" if axis_label else f"{prefix_nav}和对称轴交点"
    return _merge_lesson_step_sequence(
        steps,
        title=f"{prefix_title}，{axis_title}",
        nav_title=nav_title,
    )


def _merge_axis_square_steps(steps: list[LessonStep]) -> LessonStep:
    square_step = steps[-1]
    title = square_step.title or "由正方形边求相邻顶点"
    nav_title = square_step.nav_title or _nav_title_from_title(title)
    return _merge_lesson_step_sequence(
        steps,
        title=title,
        nav_title=nav_title,
    )


def _merge_axis_square_locus_steps(steps: list[LessonStep]) -> LessonStep:
    label = _axis_square_locus_target_label_from_lesson_steps(steps)
    title = f"正方形求顶点{label}轨迹" if label else "正方形求顶点轨迹"
    return _merge_lesson_step_sequence(
        steps,
        title=title,
        nav_title=title,
    )


def _merge_parameter_point_evaluation_steps(steps: list[LessonStep]) -> LessonStep:
    labels = _point_labels_from_lesson_steps(steps)
    labels_text = "、".join(labels)
    return _merge_lesson_step_sequence(
        steps,
        title=f"由表达式取值反求参数，并求{labels_text}坐标" if labels_text else "由表达式取值反求参数，并代入求点坐标",
        nav_title=f"反求参数求{labels_text}" if labels_text else "反求参数并代入",
    )


def _merge_parameter_point_minimum_steps(steps: list[LessonStep]) -> LessonStep:
    labels = _point_labels_from_lesson_steps(steps)
    labels_text = "、".join(labels)
    return _merge_lesson_step_sequence(
        steps,
        title=f"由最小值反求参数，并求{labels_text}坐标" if labels_text else "由最小值反求参数，并求点坐标",
        nav_title=f"反求参数求{labels_text}" if labels_text else "反求参数求点",
    )


_LESSON_STEP_MERGE_BUILDERS = {
    "simple_quadratic_foundation": _merge_simple_quadratic_foundation_steps,
    "quadratic_foundation_axis_point": _merge_quadratic_foundation_axis_point_steps,
    "axis_parameter_square_adjacent_locus": _merge_axis_square_locus_steps,
    "axis_parameter_square_adjacent": _merge_axis_square_steps,
    "parameter_value_point_evaluation_minimum_point": _merge_parameter_point_minimum_steps,
    "parameter_value_point_evaluation": _merge_parameter_point_evaluation_steps,
}


def _merge_lesson_step_sequence(
    steps: list[LessonStep],
    *,
    title: str,
    nav_title: str,
) -> LessonStep:
    first = steps[0]
    derive: list[tuple[str, str]] = []
    box: list[str] = []
    gaps: list[str] = []
    trace_refs: list[str] = []
    source_step_ids: list[str] = []
    capability_ids: list[str] = []
    teaching_substep_ids: list[str] = []
    for step in steps:
        derive.extend(step.derive)
        box.extend(step.box)
        gaps.extend(step.gaps)
        trace_refs.extend(step.trace_refs)
        source_step_ids.extend(step.source_step_ids)
        capability_ids.extend(step.capability_ids)
        teaching_substep_ids.extend(step.teaching_substep_ids)
    return LessonStep(
        id=first.id,
        scope_id=first.scope_id,
        source_step_ids=tuple(dict.fromkeys(source_step_ids)),
        capability_ids=tuple(dict.fromkeys(capability_ids)),
        trace_refs=tuple(dict.fromkeys(trace_refs)),
        title=title,
        goal=first.goal,
        nav_title=nav_title,
        derive=tuple(dict.fromkeys(derive)),
        box=tuple(_dedupe_visible_texts(box)),
        gaps=tuple(dict.fromkeys(item for item in gaps if str(item))),
        teaching_substep_ids=tuple(dict.fromkeys(teaching_substep_ids)),
    )


def _point_labels_from_lesson_steps(steps: list[LessonStep]) -> tuple[str, ...]:
    labels: list[str] = []
    for step in steps:
        labels.extend(_point_labels_from_texts((*step.box, step.title, step.nav_title or "")))
    return tuple(dict.fromkeys(label for label in labels if label))


def _axis_square_locus_target_label_from_lesson_steps(steps: list[LessonStep]) -> str:
    for step in reversed(steps):
        label = _locus_label_from_texts((*step.box, step.title, step.nav_title or ""))
        if label:
            return label
    return _last_point_label_from_lesson_steps(steps)


def _last_point_label_from_lesson_steps(steps: list[LessonStep]) -> str:
    labels = _point_labels_from_lesson_steps(steps)
    return labels[-1] if labels else ""


def _locus_label_from_texts(texts: tuple[str, ...]) -> str:
    for text in texts:
        raw = str(text)
        for match in re.finditer(r"(?:点|顶点|动点)?([A-Z][A-Za-z0-9_′]*)\s*(?:的)?轨迹", raw):
            return match.group(1)
        for match in re.finditer(r"([A-Z][A-Za-z0-9_′]*)\s*始终在", raw):
            return match.group(1)
    return ""


def _point_labels_from_texts(texts: tuple[str, ...]) -> list[str]:
    labels: list[str] = []
    for text in texts:
        for match in re.finditer(r"([A-Z])(?:′)?[（(]", str(text)):
            label = match.group(1)
            if label not in labels:
                labels.append(label)
        for match in re.finditer(r"(?:点|顶点|动点)([A-Z])", str(text)):
            label = match.group(1)
            if label not in labels:
                labels.append(label)
    return labels


def _merge_duplicate_recipe_steps(steps: list[LessonStep]) -> LessonStep:
    first = steps[0]
    rule = _duplicate_lesson_step_merge_rule(first)
    derive: list[tuple[str, str]] = []
    box: list[str] = []
    gaps: list[str] = []
    trace_refs: list[str] = []
    for step in steps:
        derive.extend(step.derive)
        box.extend(step.box)
        gaps.extend(step.gaps)
        trace_refs.extend(step.trace_refs)
    return LessonStep(
        id=first.id,
        scope_id=first.scope_id,
        source_step_ids=first.source_step_ids,
        capability_ids=first.capability_ids,
        trace_refs=tuple(dict.fromkeys(trace_refs)),
        title=rule.title if rule is not None else first.title,
        goal=first.goal,
        nav_title=rule.nav_title if rule is not None else first.nav_title,
        derive=tuple(dict.fromkeys(derive)),
        box=tuple(dict.fromkeys(item for item in box if str(item))),
        gaps=tuple(dict.fromkeys(item for item in gaps if str(item))),
        teaching_substep_ids=(),
    )


def _lesson_draft_failure(
    code: str,
    message: str,
    *,
    step_id: str = "",
    details: dict[str, Any] | None = None,
    accepted_steps: list[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
    partial_steps: list[LessonStep] | None = None,
) -> LessonDraftValidationResult:
    lesson = None
    normalized = None
    if partial_steps:
        normalized = {
            "steps": [step.to_payload() for step in partial_steps],
            "partial": True,
        }
    return LessonDraftValidationResult(
        lesson=lesson,
        normalized_lesson_draft=normalized,
        diagnostic=LessonDraftDiagnostic(
            accepted_steps=tuple(accepted_steps or ()),
            blockers=(
                LessonDraftBlocker(
                    code=code,
                    message=message,
                    step_id=step_id,
                    details=details,
                ),
            ),
            warnings=tuple(_dedupe_warnings(list(warnings or ()))),
        ),
    )


def _accepted_step_payload(
    step: LessonStep,
    groups: tuple[LessonCandidateGroup, ...],
) -> dict[str, Any]:
    return {
        "id": step.id,
        "candidate_group_ids": [group.candidate_group_id for group in groups],
        "source_step_ids": list(step.source_step_ids),
        "scope_id": step.scope_id,
        "title": step.title,
        "teaching_substep_ids": list(step.teaching_substep_ids),
    }


def _cognitive_merge_blocker(
    raw_step: dict[str, Any],
    source_groups: tuple[LessonCandidateGroup, ...],
) -> LessonDraftBlocker | None:
    by_source: dict[str, list[LessonCandidateGroup]] = defaultdict(list)
    for group in source_groups:
        if group.teaching_substep_id and group.forbid_merge_with_sibling_substeps:
            by_source[group.step_id].append(group)
    for source_id, groups in by_source.items():
        substeps = {
            str(group.teaching_substep_id)
            for group in groups
            if group.teaching_substep_id
        }
        if len(substeps) > 1:
            return LessonDraftBlocker(
                code="cognitive_action_merge_not_allowed",
                message=(
                    "teaching substeps marked as separate cognitive actions must be separate LessonIR steps"
                ),
                step_id=str(raw_step.get("id", "")),
                details={
                    "source_step_id": source_id,
                    "teaching_substep_ids": sorted(substeps),
                },
            )
    return None


def _lesson_error_code(message: str) -> str:
    if "unknown candidate_group_ids" in message:
        return "unknown_candidate_group_id"
    if "unknown planned source steps" in message or "unknown source_step_ids" in message:
        return "unknown_source_step_id"
    if "unknown trace_refs" in message:
        return "unknown_trace_ref"
    if "unknown handle" in message or "introduced unknown handles" in message:
        return "unknown_handle"
    if "answer values missing" in message:
        return "answer_values_missing"
    if "derive item" in message or "derive" in message:
        return "derive_style_invalid"
    if "cross" in message or "different scopes" in message:
        return "cross_scope_merge_not_allowed"
    return "lesson_validation_failed"


def _normalization_warnings(raw_step: dict[str, Any]) -> list[dict[str, Any]]:
    """记录系统已规范化的 LLM 风格问题，供下一轮直接写对。"""
    raw_pairs: list[tuple[str, str]] = []
    derive = raw_step.get("derive", ())
    if isinstance(derive, tuple | list):
        for item in derive:
            if isinstance(item, tuple | list) and len(item) == 2:
                raw_pairs.append((_strip_sentence(str(item[0])), _strip_sentence(str(item[1]))))
    normalized = list(_derive_items(derive))
    if raw_pairs and raw_pairs != normalized:
        return [
            {
                "code": "derive_normalized",
                "step_id": str(raw_step.get("id", "")),
                "message": (
                    "derive labels or mixed reason/conclusion were normalized; "
                    "write them directly as 作/∵/∴ lines next time"
                ),
            }
        ]
    return []


def _dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for warning in warnings:
        key = json.dumps(warning, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(warning)
    return result


def _source_groups_from_lesson_step(
    raw_step: dict[str, Any],
    *,
    groups_by_candidate: dict[str, LessonCandidateGroup],
    groups_by_source: dict[str, list[LessonCandidateGroup]],
    used_candidate_ids: set[str],
) -> tuple[LessonCandidateGroup, ...]:
    candidate_ids = tuple(str(item) for item in raw_step.get("candidate_group_ids", ()))
    if candidate_ids:
        unknown = sorted(set(candidate_ids) - set(groups_by_candidate))
        if unknown:
            raise LessonIRValidationError(f"unknown candidate_group_ids: {unknown}")
        return tuple(groups_by_candidate[item] for item in candidate_ids)

    source_step_ids = tuple(str(item) for item in raw_step.get("source_step_ids", ()))
    if not source_step_ids:
        return ()
    unknown = sorted(set(source_step_ids) - set(groups_by_source))
    if unknown:
        raise LessonIRValidationError(f"unknown planned source steps: {unknown}")
    selected: list[LessonCandidateGroup] = []
    for source_id in source_step_ids:
        candidates = groups_by_source[source_id]
        available = [
            group
            for group in candidates
            if group.candidate_group_id not in used_candidate_ids
            and group.candidate_group_id not in {item.candidate_group_id for item in selected}
        ]
        selected.append(available[0] if available else candidates[0])
    return tuple(selected)


def _build_sections(steps: list[LessonStep]) -> tuple[LessonSection, ...]:
    by_scope: dict[str, list[str]] = defaultdict(list)
    for step in steps:
        by_scope[step.scope_id].append(step.id)
    return tuple(
        LessonSection(
            scope_id=scope_id,
            title=_section_title(scope_id),
            steps=tuple(step_ids),
        )
        for scope_id, step_ids in by_scope.items()
    )


def _student_title_for_group(group: LessonCandidateGroup, text: dict[str, Any]) -> str:
    candidate = str(text.get("title") or "")
    if group.teaching_substep_title:
        return _constrained_title(
            candidate=candidate,
            fallback=group.teaching_substep_title,
            required_terms=group.teaching_substep_title_required_terms,
        )
    return candidate or _short_title(group.step)


def _student_nav_title_for_group(
    group: LessonCandidateGroup,
    text: dict[str, Any],
    title: str,
) -> str:
    candidate = str(text.get("nav_title") or "")
    if group.teaching_substep_nav_title:
        return _constrained_title(
            candidate=candidate,
            fallback=group.teaching_substep_nav_title,
            required_terms=group.teaching_substep_nav_title_required_terms,
        )
    spec_nav_title = _nav_title_for_recipe(str(group.step.get("recipe_hint") or ""))
    if spec_nav_title:
        return candidate or spec_nav_title
    return candidate or _nav_title_from_title(title)


def _student_title_for_source_groups(
    source_groups: list[LessonCandidateGroup],
    text: dict[str, Any],
) -> str:
    candidate = str(text.get("title") or "")
    if len(source_groups) == 1 and source_groups[0].teaching_substep_title:
        group = source_groups[0]
        return _constrained_title(
            candidate=candidate,
            fallback=group.teaching_substep_title,
            required_terms=group.teaching_substep_title_required_terms,
        )
    return candidate or _short_title(source_groups[0].step)


def _student_nav_title_for_source_groups(
    source_groups: list[LessonCandidateGroup],
    text: dict[str, Any],
    title: str,
) -> str:
    candidate = str(text.get("nav_title") or "")
    if len(source_groups) == 1 and source_groups[0].teaching_substep_nav_title:
        group = source_groups[0]
        return _constrained_title(
            candidate=candidate,
            fallback=group.teaching_substep_nav_title,
            required_terms=group.teaching_substep_nav_title_required_terms,
        )
    if len(source_groups) == 1:
        spec_nav_title = _nav_title_for_recipe(str(source_groups[0].step.get("recipe_hint") or ""))
        if spec_nav_title:
            return candidate or spec_nav_title
    return candidate or _nav_title_from_title(title)


def _constrained_title(
    *,
    candidate: str,
    fallback: str,
    required_terms: tuple[str, ...],
) -> str:
    if candidate and _contains_required_terms(candidate, required_terms):
        return candidate
    return fallback


def _contains_required_terms(text: str, required_terms: tuple[str, ...]) -> bool:
    if not required_terms:
        return bool(text)
    compact = _compact_title_text(text)
    return all(_compact_title_text(term) in compact for term in required_terms)


def _compact_title_text(text: str) -> str:
    return "".join(str(text).split())


def _validate_text_output(raw: dict[str, Any], snapshot: ExplanationSnapshot) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LessonIRValidationError("lesson text planner output must be an object")
    _assert_raw_derive_shape(raw.get("derive", ()))
    payload = {
        "title": str(raw.get("title", "")),
        "nav_title": str(raw.get("nav_title") or _nav_title_from_title(str(raw.get("title", "")))),
        "goal": str(raw.get("goal", "")),
        "derive": _derive_items(raw.get("derive", ())),
        "box": tuple(_normalize_visible_text_spacing(str(item)) for item in raw.get("box", ()) if str(item)),
        "gaps": tuple(str(item) for item in raw.get("gaps", ()) if str(item)),
    }
    unknown_handles = _handle_refs(payload) - _allowed_handles(snapshot)
    if unknown_handles:
        raise LessonIRValidationError(f"LLM introduced unknown handles: {sorted(unknown_handles)}")
    _assert_derive_style(payload["derive"])
    _assert_student_readable_box(payload["box"])
    return payload


def _assert_raw_derive_shape(raw: Any) -> None:
    if raw in (None, ()):
        return
    if not isinstance(raw, tuple | list):
        raise LessonIRValidationError("derive must be a two-dimensional array")
    for item in raw:
        if not isinstance(item, tuple | list) or len(item) != 2:
            raise LessonIRValidationError("derive item must be [label, text]")


def _derive_items(raw: Any) -> tuple[tuple[str, str], ...]:
    items = []
    if isinstance(raw, tuple | list):
        for item in raw:
            if isinstance(item, tuple | list) and len(item) == 2:
                items.extend(_split_derive_item(str(item[0]), str(item[1])))
            elif isinstance(item, str):
                items.extend(_split_derive_item("说明", item))
    return tuple(items)


def _filter_redundant_derive_items(
    items: tuple[tuple[str, str], ...],
    source_groups: list[LessonCandidateGroup],
) -> tuple[tuple[str, str], ...]:
    if not _is_equal_length_path_reduction_group(source_groups):
        return items
    filtered: list[tuple[str, str]] = []
    for label, text in items:
        if _is_redundant_equal_length_collinearity_text(text):
            continue
        filtered.append((label, text))
    return tuple(filtered)


def _is_equal_length_path_reduction_group(source_groups: list[LessonCandidateGroup]) -> bool:
    return any(
        group.capability_id == "equal_length_ray_path_reduction"
        and group.teaching_substep_id == "path_reduction"
        for group in source_groups
    )


def _is_redundant_equal_length_collinearity_text(text: str) -> bool:
    normalized = _strip_sentence(str(text))
    return bool(_COLLINEARITY_STATEMENT_RE.search(normalized))


_POINT_LIST_TOKEN_RE = r"(?:[A-Za-z][A-Za-z0-9_]*|[一-龥])"
_COLLINEARITY_STATEMENT_RE = re.compile(
    rf"{_POINT_LIST_TOKEN_RE}(?:[、,，]\s*{_POINT_LIST_TOKEN_RE}){{1,}}\s*共线"
)


def _split_derive_item(label: str, text: str) -> list[tuple[str, str]]:
    """把“依据，所以结论”这类混写拆成独立 derive items。"""
    label = _normalize_derive_label(label)
    text = _normalize_visible_text_spacing(_normalize_intercept_angle_reference(_strip_sentence(text)))
    if not text:
        return []
    leading_variable_split = _split_on_leading_variable_definition(text)
    if leading_variable_split is not None:
        return leading_variable_split
    standalone_variable = _standalone_variable_definition(text)
    if label in {"∵", "作", "说明"} and standalone_variable:
        return [("设", standalone_variable)]
    split = _split_on_conclusion_marker(text)
    if split is None:
        variable_split = _split_on_variable_definition_marker(label, text)
        if variable_split is not None:
            return variable_split
        derived_split = _split_on_derived_result_marker(label, text)
        if derived_split is not None:
            cause, result = derived_split
            return [("∵", cause), ("∴", result)]
        return [(_label_for_unsplit(label, text), text)]
    cause, conclusion = split
    items: list[tuple[str, str]] = []
    if cause:
        items.append((_cause_label(label, cause), cause))
    if conclusion:
        items.append(("∴", conclusion))
    return items or [(label, text)]


def _split_on_conclusion_marker(text: str) -> tuple[str, str] | None:
    match = re.search(r"(?:，|,|；|;)?\s*(所以|因此|∴)\s*", text)
    if match is None or match.start() == 0:
        return None
    cause = _strip_sentence(text[: match.start()])
    conclusion = _strip_sentence(text[match.end() :])
    if not cause or not conclusion:
        return None
    return cause, conclusion


def _normalize_intercept_angle_reference(text: str) -> str:
    """把提前出现的轴截点角，改写回同一直线上的已知端点角。

    LLM 有时会把“F 是 BE 与 y 轴的交点”提前塞进上一讲解步，并把
    ∠OBE 写成 ∠OBF。由于 F 还未由后续 method 产生，这里只利用文本中
    已声明的“截点在某条直线上”关系做等价角改写；不引入新数学事实。
    """
    out = text
    for match in re.finditer(r"([A-Z])是([A-Z])([A-Z])与[xyXYｘｙ]轴的交点", text):
        intercept, line_start, line_end = match.groups()

        def replace_angle(angle_match: re.Match[str]) -> str:
            ray_a, vertex, ray_b = angle_match.groups()
            if ray_b == intercept:
                if vertex == line_start:
                    return f"∠{ray_a}{vertex}{line_end}"
                if vertex == line_end:
                    return f"∠{ray_a}{vertex}{line_start}"
            if ray_a == intercept:
                if vertex == line_start:
                    return f"∠{line_end}{vertex}{ray_b}"
                if vertex == line_end:
                    return f"∠{line_start}{vertex}{ray_b}"
            return angle_match.group(0)

        out = re.sub(rf"∠([A-Z])([A-Z])({intercept})", replace_angle, out)
        out = re.sub(rf"∠({intercept})([A-Z])([A-Z])", replace_angle, out)
        out = re.sub(r"[（(]\s*" + re.escape(match.group(0)) + r"\s*[）)]", "", out)
    return _strip_sentence(out)


def _split_on_derived_result_marker(label: str, text: str) -> tuple[str, str] | None:
    if label != "∵":
        return None
    match = re.search(r"(?:，|,|；|;)\s*(代入得|计算得|整理得|化简得|联立得|解得)\s*", text)
    if match is None:
        return None
    cause = _strip_sentence(text[: match.start()])
    result = _strip_sentence(text[match.start() + 1 :])
    if not cause or not _looks_like_derived_result(result):
        return None
    return cause, result


def _split_on_variable_definition_marker(label: str, text: str) -> list[tuple[str, str]] | None:
    match = re.search(r"(?:，|,|；|;)\s*(?:令|设)\s*([^，,；;。]+)$", text)
    if match is None:
        return None
    previous = _strip_sentence(text[: match.start()])
    definition = _strip_sentence(match.group(1))
    if not previous or not definition or not re.search(r"=|＝", definition):
        return None
    if re.search(r"(?:得|则)", definition):
        return None
    return [(_label_for_unsplit(label, previous), previous), ("设", definition)]


def _split_on_leading_variable_definition(text: str) -> list[tuple[str, str]] | None:
    match = re.match(r"^(?:令|设)\s*([^，,；;。]+?)\s*(?:，|,|；|;)\s*(?:得|则)?\s*(.+)$", text)
    if match is None:
        return None
    definition = _strip_sentence(match.group(1))
    result = _strip_sentence(match.group(2))
    if not definition or not result or not re.search(r"=|＝", definition):
        return None
    if not _looks_like_derived_result(result):
        return None
    return [("设", definition), ("∴", result)]


def _standalone_variable_definition(text: str) -> str:
    match = re.match(r"^(?:令|设)\s*(.+)$", text)
    if match is None:
        return ""
    definition = _strip_sentence(match.group(1))
    if not definition or not re.search(r"=|＝", definition):
        return ""
    return definition


def _normalize_visible_text_spacing(text: str) -> str:
    return re.sub(r"(?<=[A-Za-z0-9√)）])或(?=[A-Za-z(（])", " 或 ", text)


def _looks_like_derived_result(text: str) -> bool:
    return bool(re.search(r"=|＝|→|⇒|坐标|解析式|表达式|[a-zA-Z]\s*[）)]", text))


def _normalize_derive_label(label: str) -> str:
    label = label.strip()
    aliases = {
        "因为": "∵",
        "由于": "∵",
        "所以": "∴",
        "因此": "∴",
        "结论": "∴",
        "代入": "∴",
        "联立": "∴",
        "化简": "∴",
        "解": "∴",
        "筛选": "∴",
    }
    return aliases.get(label, label or "说明")


def _cause_label(label: str, text: str) -> str:
    if label in {"∴", "说明"}:
        return "∵"
    return label


def _label_for_unsplit(label: str, text: str) -> str:
    if label == "∵" and re.match(r"\s*(代入得|计算得|整理得|化简得|联立得|解得)", text):
        return "∴"
    return label


def _strip_sentence(text: str) -> str:
    return text.strip().strip("。；;，, ")


def _assert_derive_style(items: tuple[tuple[str, str], ...]) -> None:
    for label, text in items:
        if label != "∴" and re.search(r"所以|因此|∴", text):
            raise LessonIRValidationError(
                "derive item mixes reason and conclusion; split into ∵/∴ lines"
            )
        if label == "∵" and re.search(r"所以|因此|∴", text):
            raise LessonIRValidationError(
                "∵ derive item must not contain conclusion marker"
            )
        if label == "∴" and re.search(r"因为|由于|∵", text):
            raise LessonIRValidationError(
                "∴ derive item must not contain reason marker"
            )


def _short_title(step: dict[str, Any]) -> str:
    recipe = str(step.get("recipe_hint") or "")
    goal = str(step.get("goal_type") or "")
    if recipe:
        title = _title_for_recipe(recipe, goal)
        if title:
            return title
    if goal:
        title = _title_for_goal(goal)
        if title:
            return title
        return goal.replace("_", " ")
    description = _first_produced_description(step)
    if description:
        return description
    if step.get("target"):
        return _title_from_handle(str(step["target"]))
    return str(step.get("step_id", "讲解步骤"))


def _title_for_recipe(recipe: str, goal: str) -> str:
    method_spec = _method_spec(recipe)
    if method_spec is not None:
        title = _title_from_explanation_spec(method_spec.explanation, goal)
        return title or method_spec.title
    recipe_spec = _recipe_spec_registry().get(recipe)
    if recipe_spec is not None:
        title = _title_from_explanation_spec(recipe_spec.explanation, goal)
        return title or recipe_spec.title
    return ""


def _title_from_explanation_spec(explanation: Any, goal: str) -> str:
    if explanation is None:
        return ""
    by_goal = getattr(explanation, "student_title_templates_by_goal", None) or {}
    if goal and isinstance(by_goal, dict) and by_goal.get(goal):
        return _safe_unbound_template_literal(by_goal[goal])
    return _safe_unbound_template_literal(
        getattr(explanation, "student_title_template", "")
    )


def _nav_title_for_recipe(recipe: str) -> str:
    method_spec = _method_spec(recipe)
    if method_spec is not None:
        return _nav_title_from_explanation_spec(method_spec.explanation)
    recipe_spec = _recipe_spec_registry().get(recipe)
    if recipe_spec is not None:
        return _nav_title_from_explanation_spec(recipe_spec.explanation)
    return ""


def _nav_title_from_explanation_spec(explanation: Any) -> str:
    if explanation is None:
        return ""
    return _safe_unbound_template_literal(
        getattr(explanation, "student_nav_title_template", "")
    )


def _safe_unbound_template_literal(template: Any) -> str:
    text = str(template or "").strip()
    if "{" in text or "}" in text:
        return ""
    return text


@lru_cache(maxsize=1)
def _method_spec_registry() -> MethodSpecRegistry:
    return MethodSpecRegistry.load_from_code()


@lru_cache(maxsize=1)
def _recipe_spec_registry() -> RecipeSpecRegistry:
    return RecipeSpecRegistry.load_from_code()


def _method_spec(method_id: str):
    try:
        return _method_spec_registry().require(method_id)
    except KeyError:
        return None


def _title_for_goal(goal: str) -> str:
    mapping = {
        "derive_y_axis_intercept_point": "求抛物线与 y 轴交点",
        "derive_translated_point": "由平移关系求点坐标",
        "derive_parabola": "求抛物线解析式",
        "derive_parametric_parabola": "用参数表示抛物线解析式",
        "derive_axis_intercept_point": "求抛物线与 x 轴交点",
        "derive_equal_angle": "推出等角关系",
        "derive_angle_constructed_point": "由等角关系求辅助点",
        "derive_curve_intersection_point": "联立直线与抛物线求交点",
        "derive_path_minimum_expression": "求路径最小值表达式",
        "derive_parameter": "反求参数",
    }
    return mapping.get(goal, "")


def _first_produced_description(step: dict[str, Any]) -> str:
    for produced in step.get("produces", ()):
        if not isinstance(produced, dict):
            continue
        description = str(produced.get("description") or "")
        if description:
            return description
    return ""


def _title_from_handle(handle: str) -> str:
    name = handle.rsplit(":", 1)[-1].replace("_", " ").replace(".", " ")
    return name or "讲解步骤"


def _student_goal_text(raw_goal: Any, fallback_target: Any) -> str:
    goal = str(raw_goal or "")
    if goal and not _handle_refs(goal):
        return goal
    target = str(fallback_target or "")
    if target.startswith("answer:"):
        return "写出当前问答案"
    if target.startswith(("fact:", "runtime:", "point:")):
        return "得到当前步骤结论"
    return _title_from_handle(target) if target else ""


def _nav_title_from_title(title: str) -> str:
    """从正文标题派生短导航标题；LLM/fixture 可显式覆盖。"""
    title = re.sub(r"^第\s*\d+\s*步[:：]\s*", "", str(title)).strip()
    title = title.replace("，", "，")
    if len(title) <= 12:
        return title
    return title[:12]


def _produced_boxes(step: dict[str, Any]) -> tuple[str, ...]:
    boxes = []
    for produced in step.get("produces", ()):
        description = str(produced.get("description", ""))
        handle = str(produced.get("handle", ""))
        if description:
            boxes.append(description)
        elif handle:
            boxes.append(handle)
    return tuple(boxes)


def _answer_box_entries(answers: dict[str, Any]) -> tuple[tuple[str, str, Any, str], ...]:
    entries: list[tuple[str, str, Any, str]] = []
    for scope_id, values in answers.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            key_text = str(key)
            entries.append((str(scope_id), key_text, value, _student_answer_box(key_text, value)))
    return tuple(entries)


def _answer_boxes(answers: dict[str, Any]) -> tuple[str, ...]:
    boxes = []
    for _, _, _, box in _answer_box_entries(answers):
        boxes.append(box)
    return tuple(boxes)


def _answer_box_fingerprint(box: str) -> str:
    return str(box)


def _missing_answer_boxes(
    answers: dict[str, Any],
    rendered_fingerprints: set[str],
) -> tuple[str, ...]:
    return tuple(
        box
        for _, _, _, box in _answer_box_entries(answers)
        if _answer_box_fingerprint(box) not in rendered_fingerprints
    )


def _rendered_answer_box_fingerprints(raw: Any, answers: dict[str, Any]) -> set[str]:
    if not isinstance(raw, tuple | list):
        return set()
    visible_boxes = tuple(str(item) for item in raw if str(item))
    normalized_visible_boxes = tuple(_normalize_visible_math(item) for item in visible_boxes)
    rendered: set[str] = set()
    for _, key, value, box in _answer_box_entries(answers):
        if _is_point_answer_value(key, value):
            candidates = tuple(
                dict.fromkeys(
                    _normalize_visible_math(candidate)
                    for candidate in _student_answer_candidates(key, value)
                    if str(candidate)
                )
            )
            boxes_to_scan = normalized_visible_boxes
        else:
            candidates = (box,)
            boxes_to_scan = visible_boxes
        if any(
            _answer_candidate_matches_box(candidate, visible_box)
            for visible_box in boxes_to_scan
            for candidate in candidates
        ):
            rendered.add(_answer_box_fingerprint(box))
    return rendered


def _answer_candidate_matches_box(candidate: str, visible_box: str) -> bool:
    if not candidate:
        return False
    if candidate == visible_box:
        return True
    if len(candidate) < 3:
        return False
    start = 0
    while True:
        index = visible_box.find(candidate, start)
        if index < 0:
            return False
        before = visible_box[index - 1] if index > 0 else ""
        after_index = index + len(candidate)
        after = visible_box[after_index] if after_index < len(visible_box) else ""
        if _answer_match_boundary(before) and _answer_match_boundary(after):
            return True
        start = index + 1


def _answer_match_boundary(char: str) -> bool:
    if not char:
        return True
    return not (char.isalnum() or char in "_²³√/+-")


def _answer_boxes_for_step(step: dict[str, Any], answers: dict[str, Any]) -> tuple[str, ...]:
    boxes: list[str] = []
    for produced in step.get("produces", ()):
        if not isinstance(produced, dict):
            continue
        handle = str(produced.get("handle") or "")
        if not handle.startswith("answer:"):
            continue
        resolved = _answer_for_handle(handle, answers)
        if resolved is None:
            continue
        scope_id, key, value = resolved
        boxes.append(_student_answer_box(key, value))
    return tuple(dict.fromkeys(boxes))


def _answer_for_handle(handle: str, answers: dict[str, Any]) -> tuple[str, str, Any] | None:
    tail = handle.split(":", 1)[-1]
    for scope_id in sorted(answers, key=len, reverse=True):
        values = answers.get(scope_id)
        if not isinstance(values, dict):
            continue
        prefix = f"{scope_id}_"
        if tail.startswith(prefix):
            key = tail[len(prefix):]
        elif tail.startswith(f"{scope_id}."):
            key = tail[len(scope_id) + 1:]
        else:
            continue
        if key in values:
            return scope_id, key, values[key]
    return None


def _answer_text(value: Any) -> str:
    if isinstance(value, list):
        return "(" + ", ".join(_answer_text(item) for item in value) + ")"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_answer_text(v)}" for k, v in value.items()) + "}"
    return str(value)


def _student_answer_box(key: str, value: Any) -> str:
    if key == "parabola":
        return f"y={_display_math_expr(value)}"
    if _is_answer_point_list(value):
        rendered = "或".join(_student_point_answer_box(key, point) for point in _sorted_answer_points(value))
        return rendered
    if isinstance(value, list):
        rendered = ",".join(_display_math_expr(item) for item in value)
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", key):
            return f"{key}({rendered})"
        return f"({rendered})"
    if re.fullmatch(r"[a-zA-Z][A-Za-z0-9_]*", key):
        return f"{key}={_display_math_expr(value)}"
    return _display_math_expr(value)


def _student_point_answer_box(key: str, value: Any) -> str:
    rendered = ",".join(_display_math_expr(item) for item in value)
    if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", key):
        return f"{key}({rendered})"
    return f"({rendered})"


def _is_point_answer_value(key: str, value: Any) -> bool:
    return _is_answer_point_list(value) or (
        isinstance(value, list | tuple)
        and len(value) == 2
        and re.fullmatch(r"[A-Z][A-Za-z0-9_]*", key) is not None
    )


def _sorted_answer_points(value: Any) -> list[Any]:
    points = [item for item in value if isinstance(item, list | tuple) and len(item) == 2]
    try:
        import sympy as sp

        return sorted(
            points,
            key=lambda item: tuple(float(sp.N(sp.sympify(str(coord)))) for coord in reversed(item)),
            reverse=True,
        )
    except Exception:
        return points


def _is_answer_point_list(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and bool(value)
        and all(isinstance(item, list | tuple) and len(item) == 2 for item in value)
    )


def _display_math_expr(value: Any) -> str:
    return student_math_display(_answer_text(value), simplify_sympy=False)


def _merge_boxes(
    raw: Any,
    extra: tuple[str, ...],
    *,
    dedupe_math_equivalent: bool = True,
) -> tuple[str, ...]:
    boxes = _dedupe_visible_texts(raw) if dedupe_math_equivalent else _dedupe_exact_texts(raw)
    for item in extra:
        normalized = _normalize_visible_math(item)
        if item in boxes:
            continue
        if dedupe_math_equivalent and any(_normalize_visible_math(box) == normalized for box in boxes):
            continue
        boxes.append(item)
    return tuple(boxes)


def _merge_answer_boxes(raw: Any, extra: tuple[str, ...], answers: dict[str, Any]) -> tuple[str, ...]:
    boxes = _dedupe_exact_texts(raw)
    point_answer_fingerprints = {
        _normalize_visible_math(box)
        for _, key, value, box in _answer_box_entries(answers)
        if _is_point_answer_value(key, value)
    }
    for item in extra:
        if item in boxes:
            continue
        normalized = _normalize_visible_math(item)
        if normalized in point_answer_fingerprints and any(
            _normalize_visible_math(box) == normalized for box in boxes
        ):
            continue
        boxes.append(item)
    return tuple(boxes)


def _dedupe_exact_texts(raw: Any) -> list[str]:
    boxes: list[str] = []
    if not isinstance(raw, tuple | list):
        return boxes
    for item in raw:
        text = str(item)
        if text and text not in boxes:
            boxes.append(text)
    return boxes


def _dedupe_visible_texts(raw: Any) -> list[str]:
    boxes: list[str] = []
    if not isinstance(raw, tuple | list):
        return boxes
    for item in raw:
        text = str(item)
        if not text:
            continue
        normalized = _normalize_visible_math(text)
        if any(_normalize_visible_math(box) == normalized for box in boxes):
            continue
        boxes.append(text)
    return boxes


def _assert_answers_present(lesson: LessonIR, answers: dict[str, Any]) -> None:
    text = _normalize_visible_math(str(lesson.to_payload()))
    missing = []
    for values in answers.values():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            candidates = _student_answer_candidates(str(key), value)
            if candidates and not any(
                _answer_candidate_matches_box(_normalize_visible_math(candidate), text)
                for candidate in candidates
            ):
                missing.append(_student_answer_box(str(key), value))
    if missing:
        raise LessonIRValidationError(f"answer values missing from LessonIR: {missing}")


def _student_answer_candidates(key: str, value: Any) -> tuple[str, ...]:
    candidates = [_student_answer_box(key, value), _answer_text(value), _display_math_expr(value)]
    if key == "parabola":
        candidates.append(f"y={_display_math_expr(value)}")
    if isinstance(value, list) and re.fullmatch(r"[A-Z][A-Za-z0-9_]*", key):
        candidates.append(f"{key}({_display_math_expr(value)})")
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _normalize_visible_math(text: str) -> str:
    normalized = (
        str(text)
        .replace(" ", "")
        .replace("　", "")
        .replace("，", ",")
        .replace("＝", "=")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("−", "-")
        .replace("（", "(")
        .replace("）", ")")
        .replace("**2", "²")
        .replace("*", "")
    )
    return re.sub(r"√\(([A-Za-z0-9]+)\)", r"√\1", normalized)


_MACHINE_BOX_RE = re.compile(r"\b[a-z]+(?:_[0-9]+)?\.[A-Za-z_][A-Za-z0-9_]*\s*=")


def _assert_student_readable_box(boxes: tuple[str, ...]) -> None:
    text = "\n".join(boxes)
    if _HANDLE_RE.search(text):
        raise LessonIRValidationError("box must not contain internal handles")
    if _MACHINE_BOX_RE.search(text):
        raise LessonIRValidationError("box must use student-readable conclusions, not internal answer keys")
    if re.search(r"\b[a-zA-Z_][A-Za-z0-9_]*\s*=\s*[^，,;\n]*\*\*", text):
        raise LessonIRValidationError("box must not contain Python/SymPy style expressions")


def _section_title(scope_id: str) -> str:
    parts = scope_id.split("_", 1)
    root = parts[0]
    root_title = {
        "i": "第（Ⅰ）问",
        "ii": "第（Ⅱ）问",
        "iii": "第（Ⅲ）问",
    }.get(root, f"{scope_id} 问")
    if len(parts) == 1:
        return root_title
    sub_title = {
        "1": "①",
        "2": "②",
        "3": "③",
        "4": "④",
    }.get(parts[1], parts[1])
    return root_title.replace("问", f"{sub_title}问")


_HANDLE_RE = re.compile(
    r"\b(?:point|fact|answer|function|symbol|segment|line|ray|angle):[A-Za-z0-9_:.\\-]+"
)


def _handle_refs(value: Any) -> set[str]:
    return set(_HANDLE_RE.findall(str(value)))


def _allowed_handles(snapshot: ExplanationSnapshot) -> set[str]:
    handles = set(snapshot.fact_index)
    for step in snapshot.effective_steps:
        handles.update(str(item) for item in step.get("reads", ()))
        for created in step.get("creates", ()):
            handles.add(str(created.get("handle", "")))
        for produced in step.get("produces", ()):
            handles.add(str(produced.get("handle", "")))
    for entity in snapshot.problem.get("entities", ()):
        if isinstance(entity, dict) and "handle" in entity:
            handles.add(str(entity["handle"]))
    for fact in snapshot.problem.get("facts", ()):
        if isinstance(fact, dict) and "handle" in fact:
            handles.add(str(fact["handle"]))
    for goal in snapshot.problem.get("question_goals", ()):
        if isinstance(goal, dict):
            if "handle" in goal:
                handles.add(str(goal["handle"]))
            if "target_handle" in goal:
                handles.add(str(goal["target_handle"]))
    return {handle for handle in handles if handle}
