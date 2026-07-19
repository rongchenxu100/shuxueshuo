"""ExplanationBuilder 的轻量数据模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .presentation import StudentScopeReference, StudentStepPlacement


@dataclass(frozen=True)
class TeachingTraceEntry:
    """一次 method invocation 的讲解级 trace。

    这里刻意不暴露 ContextPath。输入输出只保留槽位名，具体值通过 fact_index 或
    Lesson step 的已绑定文本展示。
    """

    trace_id: str
    source_step_id: str
    scope_id: str
    capability_id: str
    method_id: str
    input_slots: tuple[str, ...] = ()
    output_slots: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    trace_fragments: tuple[dict[str, Any], ...] = ()
    hidden_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["input_slots"] = list(self.input_slots)
        payload["output_slots"] = list(self.output_slots)
        payload["checks"] = list(self.checks)
        payload["trace_fragments"] = list(self.trace_fragments)
        return payload


@dataclass(frozen=True)
class ExplanationSnapshot:
    """ExplanationBuilder 的唯一事实输入。"""

    problem_id: str
    family_id: str
    problem: dict[str, Any]
    effective_steps: tuple[dict[str, Any], ...]
    teaching_trace: tuple[TeachingTraceEntry, ...]
    fact_index: dict[str, dict[str, Any]]
    student_step_placements: tuple[StudentStepPlacement, ...] = ()
    student_scope_references: tuple[StudentScopeReference, ...] = ()
    planner_insights: tuple[dict[str, Any], ...] = ()
    answers: dict[str, Any] = field(default_factory=dict)
    checks: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "problem": self.problem,
            "effective_steps": list(self.effective_steps),
            "teaching_trace": [entry.to_payload() for entry in self.teaching_trace],
            "fact_index": self.fact_index,
            "student_step_placements": [
                item.to_payload() for item in self.student_step_placements
            ],
            "student_scope_references": [
                item.to_payload() for item in self.student_scope_references
            ],
            "planner_insights": list(self.planner_insights),
            "answers": self.answers,
            "checks": list(self.checks),
        }


@dataclass(frozen=True)
class LessonCandidateGroup:
    """LessonIR LLM 可选择的讲解候选组。

    它连接可执行 StepIntent、method invocation trace 和讲解层拆分后的认知子步骤。
    """

    step: dict[str, Any]
    traces: tuple[TeachingTraceEntry, ...]
    teaching_substep_id: str | None = None
    teaching_substep_title: str | None = None
    teaching_substep_nav_title: str | None = None
    teaching_substep_title_required_terms: tuple[str, ...] = ()
    teaching_substep_nav_title_required_terms: tuple[str, ...] = ()
    teaching_focus: str | None = None
    preferred_method_ids: tuple[str, ...] = ()
    forbid_merge_with_sibling_substeps: bool = True
    presentation_scope_id: str | None = None
    required_reference_lines: tuple[str, ...] = ()

    @property
    def step_id(self) -> str:
        return str(self.step["step_id"])

    @property
    def candidate_group_id(self) -> str:
        if not self.teaching_substep_id:
            return self.step_id
        return f"{self.step_id}.{self.teaching_substep_id}"

    @property
    def scope_id(self) -> str:
        return self.presentation_scope_id or str(self.step["scope_id"])

    @property
    def capability_id(self) -> str:
        return str(self.step.get("recipe_hint") or self.step.get("goal_type") or "unknown")

    @property
    def method_ids(self) -> tuple[str, ...]:
        return tuple(entry.method_id for entry in self._visible_traces)

    @property
    def trace_refs(self) -> tuple[str, ...]:
        return tuple(entry.trace_id for entry in self._visible_traces)

    @property
    def _visible_traces(self) -> tuple[TeachingTraceEntry, ...]:
        traces = tuple(entry for entry in self.traces if entry.hidden_reason is None)
        if not self.preferred_method_ids:
            return traces
        preferred = set(self.preferred_method_ids)
        filtered = tuple(entry for entry in traces if entry.method_id in preferred)
        return filtered or traces


@dataclass(frozen=True)
class LessonStep:
    """面向学生讲解的一步。"""

    id: str
    scope_id: str
    source_step_ids: tuple[str, ...]
    capability_ids: tuple[str, ...]
    trace_refs: tuple[str, ...]
    title: str
    goal: str
    nav_title: str | None = None
    derive: tuple[tuple[str, str], ...] = ()
    box: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()
    teaching_substep_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "scope_id": self.scope_id,
            "source_step_ids": list(self.source_step_ids),
            "capability_ids": list(self.capability_ids),
            "trace_refs": list(self.trace_refs),
            "title": self.title,
            "goal": self.goal,
            "derive": [list(item) for item in self.derive],
            "box": list(self.box),
            "gaps": list(self.gaps),
            "teaching_substep_ids": list(self.teaching_substep_ids),
        }
        if self.nav_title:
            payload["nav_title"] = self.nav_title
        return payload


@dataclass(frozen=True)
class LessonSection:
    """一个 question/subquestion 的讲解 section。"""

    scope_id: str
    title: str
    steps: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "title": self.title,
            "steps": list(self.steps),
        }


@dataclass(frozen=True)
class LessonIR:
    """文字版教学 IR。"""

    problem_id: str
    family_id: str
    sections: tuple[LessonSection, ...]
    steps: tuple[LessonStep, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "sections": [section.to_payload() for section in self.sections],
            "steps": [step.to_payload() for step in self.steps],
        }


def lesson_ir_from_payload(payload: dict[str, Any]) -> LessonIR:
    """Restore LessonIR from a JSON payload."""
    return LessonIR(
        problem_id=str(payload["problem_id"]),
        family_id=str(payload["family_id"]),
        sections=tuple(
            LessonSection(
                scope_id=str(item["scope_id"]),
                title=str(item["title"]),
                steps=tuple(str(step_id) for step_id in item.get("steps", ())),
            )
            for item in payload.get("sections", ())
            if isinstance(item, dict)
        ),
        steps=tuple(
            LessonStep(
                id=str(item["id"]),
                scope_id=str(item["scope_id"]),
                source_step_ids=tuple(str(value) for value in item.get("source_step_ids", ())),
                capability_ids=tuple(str(value) for value in item.get("capability_ids", ())),
                trace_refs=tuple(str(value) for value in item.get("trace_refs", ())),
                title=str(item.get("title") or ""),
                goal=str(item.get("goal") or ""),
                nav_title=str(item["nav_title"]) if item.get("nav_title") else None,
                derive=tuple(
                    (str(pair[0]), str(pair[1]))
                    for pair in item.get("derive", ())
                    if isinstance(pair, list | tuple) and len(pair) == 2
                ),
                box=tuple(str(value) for value in item.get("box", ()) if str(value)),
                gaps=tuple(str(value) for value in item.get("gaps", ()) if str(value)),
                teaching_substep_ids=tuple(
                    str(value) for value in item.get("teaching_substep_ids", ())
                ),
            )
            for item in payload.get("steps", ())
            if isinstance(item, dict)
        ),
    )
