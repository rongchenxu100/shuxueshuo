"""EB1 文字版 ExplanationBuilder。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
import json
import re
from typing import Any, Protocol

from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry

from .models import ExplanationSnapshot, LessonCandidateGroup, LessonIR, LessonSection, LessonStep, TeachingTraceEntry
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
        if isinstance(draft, dict) and group.teaching_substep_id:
            proof = [
                ("说明", str(item))
                for item in draft.get("proof_draft", ())
                if str(item)
            ]
            boxes = tuple(
                str(item)
                for item in draft.get("box", ())
                if str(item)
            )
            if proof:
                return {
                    "title": group.teaching_substep_title or _short_title(step),
                    "goal": str(draft.get("student_intent_draft") or group.teaching_focus or ""),
                    "derive": proof,
                    "box": boxes or _produced_boxes(step),
                }
        title = group.teaching_substep_title or _short_title(step)
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
            "goal": goal,
            "derive": derive,
            "box": _produced_boxes(step),
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
        steps = []
        for index, group in enumerate(groups):
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
            if index == len(groups) - 1:
                text["box"] = _merge_boxes(text.get("box", ()), _answer_boxes(snapshot.answers))
            steps.append(_lesson_step_from_group(group, text))
        lesson = LessonIR(
            problem_id=snapshot.problem_id,
            family_id=snapshot.family_id,
            sections=_build_sections(steps),
            steps=tuple(steps),
        )
        LessonIRValidator().validate(lesson, snapshot)
        return lesson


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


def _split_lesson_group(group: LessonCandidateGroup) -> tuple[LessonCandidateGroup, ...]:
    """把单个 executable step 拆成更细的学生认知步骤。

    拆分边界来自 recipe explanation spec；执行层仍共享同一个 StepIntent source。
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
    return LessonStep(
        id=f"explain_{group.candidate_group_id.replace('.', '_')}",
        scope_id=group.scope_id,
        source_step_ids=(group.step_id,),
        capability_ids=(group.capability_id,),
        trace_refs=group.trace_refs,
        title=str(text.get("title") or _short_title(group.step)),
        goal=str(text.get("goal") or group.step.get("target") or ""),
        derive=_derive_items(text.get("derive", ())),
        box=tuple(str(item) for item in text.get("box", ()) if str(item)),
        gaps=tuple(str(item) for item in text.get("gaps", ()) if str(item)),
        teaching_substep_ids=(
            (group.teaching_substep_id,) if group.teaching_substep_id else ()
        ),
    )


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
        if index == len(raw_steps):
            text["box"] = _merge_boxes(text.get("box", ()), _answer_boxes(snapshot.answers))
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
            title=str(text.get("title") or _short_title(source_groups[0].step)),
            goal=str(text.get("goal") or source_groups[0].step.get("target") or ""),
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
                    "recipe teaching substeps marked as separate cognitive actions must be separate LessonIR steps"
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
            title=f"{scope_id} 问",
            steps=tuple(step_ids),
        )
        for scope_id, step_ids in by_scope.items()
    )


def _validate_text_output(raw: dict[str, Any], snapshot: ExplanationSnapshot) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise LessonIRValidationError("lesson text planner output must be an object")
    _assert_raw_derive_shape(raw.get("derive", ()))
    payload = {
        "title": str(raw.get("title", "")),
        "goal": str(raw.get("goal", "")),
        "derive": _derive_items(raw.get("derive", ())),
        "box": tuple(str(item) for item in raw.get("box", ()) if str(item)),
        "gaps": tuple(str(item) for item in raw.get("gaps", ()) if str(item)),
    }
    unknown_handles = _handle_refs(payload) - _allowed_handles(snapshot)
    if unknown_handles:
        raise LessonIRValidationError(f"LLM introduced unknown handles: {sorted(unknown_handles)}")
    _assert_derive_style(payload["derive"])
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


def _split_derive_item(label: str, text: str) -> list[tuple[str, str]]:
    """把“依据，所以结论”这类混写拆成独立 derive items。"""
    label = _normalize_derive_label(label)
    text = _strip_sentence(text)
    if not text:
        return []
    split = _split_on_conclusion_marker(text)
    if split is None:
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


def _looks_like_derived_result(text: str) -> bool:
    return bool(re.search(r"=|→|⇒|坐标|解析式|表达式|[a-zA-Z]\s*[）)]", text))


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
    if step.get("target"):
        return str(step["target"])
    if step.get("goal_type"):
        return str(step["goal_type"]).replace("_", " ")
    return str(step.get("step_id", "讲解步骤"))


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


def _answer_boxes(answers: dict[str, Any]) -> tuple[str, ...]:
    boxes = []
    for scope_id, values in answers.items():
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            boxes.append(f"{scope_id}.{key} = {_answer_text(value)}")
    return tuple(boxes)


def _answer_text(value: Any) -> str:
    if isinstance(value, list):
        return "(" + ", ".join(_answer_text(item) for item in value) + ")"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_answer_text(v)}" for k, v in value.items()) + "}"
    return str(value)


def _merge_boxes(raw: Any, extra: tuple[str, ...]) -> tuple[str, ...]:
    boxes = [str(item) for item in raw if str(item)] if isinstance(raw, tuple | list) else []
    for item in extra:
        if item not in boxes:
            boxes.append(item)
    return tuple(boxes)


def _assert_answers_present(lesson: LessonIR, answers: dict[str, Any]) -> None:
    text = str(lesson.to_payload())
    missing = []
    for values in answers.values():
        if not isinstance(values, dict):
            continue
        for value in values.values():
            rendered = _answer_text(value)
            if rendered and rendered not in text:
                missing.append(rendered)
    if missing:
        raise LessonIRValidationError(f"answer values missing from LessonIR: {missing}")


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
