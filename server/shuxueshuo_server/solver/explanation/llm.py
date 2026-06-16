"""LLM-backed LessonIR planner for ExplanationBuilder EB1."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient

from .builder import (
    LessonDraftBlocker,
    LessonDraftDiagnostic,
    LessonDraftValidationResult,
    validate_lesson_draft,
)
from .few_shots import (
    equal_length_ray_lesson_mock_few_shot,
    generic_lesson_mock_few_shot,
    select_lesson_few_shot_examples,
)
from .models import ExplanationSnapshot, LessonCandidateGroup, LessonIR
from .teaching_expansion import explanation_payload_for_group


@dataclass(frozen=True)
class ExplanationPrompt:
    """Explanation LLM prompt."""

    system: str
    user: str

    @property
    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


class ExplanationRepairLoopError(RuntimeError):
    """Explanation LLM 多轮 repair 后仍未生成合法 LessonIR draft。"""


_LESSON_FALLBACK_FEW_SHOT_BUILDERS = {
    "QuadraticEqualLengthRayPathMinimumSolver": equal_length_ray_lesson_mock_few_shot,
}


class ExplanationRepairFeedbackBuilder:
    """把 LessonIR draft diagnostic 整理成 LLM-facing repair summary。"""

    def build(
        self,
        *,
        diagnostic: LessonDraftDiagnostic,
    ) -> dict[str, Any]:
        blocker = diagnostic.blockers[0] if diagnostic.blockers else None
        already_normalized = [
            warning
            for warning in diagnostic.warnings
            if warning.get("code") == "derive_normalized"
        ]
        return {
            "current_blocker": blocker.to_payload() if blocker is not None else None,
            "next_actions": _repair_next_actions(blocker),
            "do_not": _repair_do_not(blocker),
            "already_normalized": already_normalized,
            "accepted_steps": list(diagnostic.accepted_steps),
        }


class LLMLessonPlanner:
    """用 LLM 做 step 分组和讲解文字优化。

    LLM 不接触解题执行，也不能修改 fact/value/answer。它只返回 Lesson step 的
    分组选择与文字字段，后续由 ExplanationBuilder 校验。
    """

    def __init__(
        self,
        *,
        client: LLMPlannerClient,
        debug_dir: str | Path | None = None,
        few_shot_dir: str | Path | None = None,
        allow_same_problem_few_shot: bool = True,
        max_attempts: int = 3,
    ) -> None:
        self.client = client
        self.debug_dir = Path(debug_dir) if debug_dir is not None else None
        self.few_shot_dir = Path(few_shot_dir) if few_shot_dir is not None else None
        self.allow_same_problem_few_shot = allow_same_problem_few_shot
        self.max_attempts = max(1, int(max_attempts))
        self.last_payload: dict[str, Any] | None = None
        self.last_prompt: ExplanationPrompt | None = None
        self.last_raw_response: str | None = None
        self.last_parsed: dict[str, Any] | None = None
        self.last_previous_attempts: list[dict[str, Any]] = []

    def plan_lesson(
        self,
        *,
        groups: tuple[LessonCandidateGroup, ...],
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        previous_attempts: list[dict[str, Any]] = []
        self.last_previous_attempts = previous_attempts
        latest_raw = ""
        latest_parsed: dict[str, Any] | None = None
        for attempt in range(1, self.max_attempts + 1):
            payload = build_lesson_planner_payload(
                snapshot,
                groups,
                few_shot_dir=self.few_shot_dir,
                allow_same_problem_few_shot=self.allow_same_problem_few_shot,
                previous_attempts=previous_attempts,
            )
            prompt = render_lesson_prompt(payload)
            raw = self.client.complete(
                {
                    "messages": prompt.messages,
                    "problem_id": snapshot.problem_id,
                    "family_id": snapshot.family_id,
                    "explanation_payload": payload,
                }
            )
            parsed: dict[str, Any] | None = None
            validation: LessonDraftValidationResult | None = None
            try:
                parsed = _parse_json_object(raw)
                validation = validate_lesson_draft(parsed, groups, snapshot)
            except Exception as exc:
                validation = _validation_result_for_parse_error(exc)
            self.last_payload = payload
            self.last_prompt = prompt
            self.last_raw_response = raw
            self.last_parsed = parsed
            self.last_previous_attempts = previous_attempts
            latest_raw = raw
            latest_parsed = parsed
            attempt_payload = _lesson_repair_attempt_payload(
                attempt=attempt,
                lesson_draft=parsed,
                validation=validation,
            )
            if self.debug_dir is not None:
                _write_explanation_attempt_artifacts(
                    self.debug_dir,
                    attempt=attempt,
                    payload=payload,
                    prompt=prompt,
                    raw_response=raw,
                    parsed=parsed,
                    validation=validation,
                    previous_attempt_payload=attempt_payload,
                )
            if validation.ok:
                if self.debug_dir is not None:
                    write_explanation_debug_artifacts(
                        self.debug_dir,
                        payload=payload,
                        prompt=prompt,
                        raw_response=raw,
                        parsed=parsed,
                    )
                return parsed or {}
            previous_attempts.append(attempt_payload)
        if self.debug_dir is not None and self.last_payload is not None and self.last_prompt is not None:
            write_explanation_debug_artifacts(
                self.debug_dir,
                payload=self.last_payload,
                prompt=self.last_prompt,
                raw_response=latest_raw,
                parsed=latest_parsed,
            )
        raise ExplanationRepairLoopError(
            f"explanation lesson planner failed after {self.max_attempts} attempts"
        )


def build_lesson_planner_payload(
    snapshot: ExplanationSnapshot,
    groups: tuple[LessonCandidateGroup, ...],
    *,
    few_shot_dir: str | Path | None = None,
    allow_same_problem_few_shot: bool = True,
    previous_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构造给 LLM 的讲解规划输入。"""
    candidate_groups = [
        _group_payload(group, snapshot)
        for group in groups
    ]
    return {
        "task": "group_steps_and_write_student_explanation",
        "problem_id": snapshot.problem_id,
        "family_id": snapshot.family_id,
        "problem": {
            "original_text": snapshot.problem.get("original_text", {}),
            "scopes": snapshot.problem.get("scopes", []),
            "question_goals": snapshot.problem.get("question_goals", []),
        },
        "answers": snapshot.answers,
        "planner_insights": list(snapshot.planner_insights),
        "previous_attempts": list(previous_attempts or ()),
        "teaching_step_policy": _teaching_step_policy(groups),
        "explanation_few_shots": _lesson_few_shot_examples(
            snapshot=snapshot,
            candidate_groups=candidate_groups,
            few_shot_dir=few_shot_dir,
            allow_same_problem=allow_same_problem_few_shot,
        ),
        "candidate_groups": candidate_groups,
        "output_schema": {
            "steps": [
                {
                    "candidate_group_ids": ["一个或多个 candidate_groups 中的 candidate_group_id"],
                    "id": "string",
                    "source_step_ids": ["兼容字段；优先使用 candidate_group_ids"],
                    "title": "string",
                    "nav_title": "string",
                    "goal": "string",
                    "derive": [["标签", "面向学生的讲解句"]],
                    "box": ["重要结论文字"],
                }
            ]
        },
        "rules": [
            "只返回 JSON，不要使用 Markdown 代码块。",
            "优先用 candidate_group_ids 引用候选步骤；只能组合 candidate_groups 中已有的 candidate_group_id，不要发明新的 id。",
            "source_step_ids 是真实解题来源引用，若同一个 source_step_id 被拆成多个 candidate_group_id，不要只用 source_step_ids 合并它们。",
            "不要新增 handle、事实、数值、答案、点、线或条件。",
            "不要提到 runtime ContextPath 或内部 method 路径。",
            "讲解文字使用适合初中生的中文表达。",
            "不要只按大问/小问整体分组；较长小问通常需要拆成多个讲解步骤。",
            "若 candidate_group 提供 teaching_expansion_draft，优先使用该草稿，不要根据 method_id 自己猜证明。",
            "可以把一个 executable recipe 拆成多个 LessonIR steps，但 source_step_ids 必须仍来自 candidate_groups。",
            "teaching_expansion_draft 中 explanation_only_label=true 的辅助点只用于讲解，不是新的 StepIntent creates。",
            "示例讲解只用于学习标题、derive 标签、步骤粒度和讲解风格；不要复制示例题的点名、数值、答案或 source_step_ids。",
            "title 尽量使用“第 N 步：动作 + 目的”的格式，不要写“第一部分/第二部分”这类系统拆分词。",
            "derive 标签优先使用证明流标签：作、∵、∴。代入、化简、解方程、筛选等动作词应写在正文里，不作为标签。",
            "每个 derive item 只表达一个逻辑动作：∵ 只写依据/前提，∴ 只写由前文推出的方程、化简结果、解或结论。",
            "不要在同一个 derive item 中写“……所以/因此/∴……”；必须拆成相邻的 ∵/代入/化简/解 与 ∴ 两行。",
            "不要输出标签“代入”“化简”“解”“筛选”；例如写成 [\"∴\", \"代入得 a-b=3\"] 或 [\"∴\", \"解得 a=1，b=-2\"]。",
            "title 写带当前题上下文的解题思路，例如“第1步：求 C、D 点坐标，代入求函数解析式”。",
            "nav_title 写短导航标题，不必带所有点名，例如“代入已知点求解析式”。",
            "box 只能写学生可读关键结论，例如 C(0,-3)、y=x²-2x-3、a=3/4；不要写 answer:*、fact:*、i_1.parabola = ... 或 Python/SymPy 表达式。",
            "answers 中的每个最终答案都必须以学生可读形式出现在相关最终讲解步骤的 box 中。",
        ],
    }


def render_lesson_prompt(payload: dict[str, Any]) -> ExplanationPrompt:
    """用 Jinja prompt 模板渲染 explanation LLM 输入。"""
    env = Environment(
        loader=FileSystemLoader(str(_default_template_dir())),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pretty_json"] = _pretty_json
    system = env.get_template("explanation-system.jinja").render().strip()
    user = env.get_template("explanation-user.jinja").render(payload=payload).strip()
    return ExplanationPrompt(system=system, user=user)


def write_explanation_debug_artifacts(
    debug_dir: str | Path,
    *,
    payload: dict[str, Any],
    prompt: ExplanationPrompt,
    raw_response: str,
    parsed: dict[str, Any] | None = None,
    lesson: LessonIR | None = None,
) -> None:
    """写出 explanation LLM 的输入输出，便于 debug。"""
    path = Path(debug_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.explanation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / "prompt.system.txt").write_text(prompt.system, encoding="utf-8")
    (path / "prompt.user.txt").write_text(prompt.user, encoding="utf-8")
    (path / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    if parsed is not None:
        (path / "parsed-lesson-draft.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if payload.get("explanation_few_shots") is not None:
        (path / "payload.explanation_few_shots.json").write_text(
            json.dumps(payload["explanation_few_shots"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if lesson is not None:
        (path / "lesson-ir.json").write_text(
            json.dumps(lesson.to_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _write_explanation_attempt_artifacts(
    debug_dir: str | Path,
    *,
    attempt: int,
    payload: dict[str, Any],
    prompt: ExplanationPrompt,
    raw_response: str,
    parsed: dict[str, Any] | None,
    validation: LessonDraftValidationResult,
    previous_attempt_payload: dict[str, Any],
) -> None:
    path = Path(debug_dir)
    path.mkdir(parents=True, exist_ok=True)
    prefix = f"attempt-{attempt}"
    (path / f"{prefix}.payload.explanation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / f"{prefix}.prompt.system.txt").write_text(prompt.system, encoding="utf-8")
    (path / f"{prefix}.prompt.user.txt").write_text(prompt.user, encoding="utf-8")
    (path / f"{prefix}.raw-response.txt").write_text(raw_response, encoding="utf-8")
    if parsed is not None:
        (path / f"{prefix}.parsed-lesson-draft.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if validation.normalized_lesson_draft is not None:
        (path / f"{prefix}.normalized-lesson-draft.json").write_text(
            json.dumps(validation.normalized_lesson_draft, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (path / f"{prefix}.validation-diagnostic.json").write_text(
        json.dumps(validation.diagnostic.to_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / f"{prefix}.previous-attempt-payload.json").write_text(
        json.dumps(previous_attempt_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _validation_result_for_parse_error(exc: Exception) -> LessonDraftValidationResult:
    message = f"lesson planner returned invalid JSON: {exc}"
    return LessonDraftValidationResult(
        lesson=None,
        normalized_lesson_draft=None,
        diagnostic=LessonDraftDiagnostic(
            blockers=(
                LessonDraftBlocker(
                    code="schema_invalid",
                    message=message,
                ),
            ),
        ),
    )


def _lesson_repair_attempt_payload(
    *,
    attempt: int,
    lesson_draft: dict[str, Any] | None,
    validation: LessonDraftValidationResult,
) -> dict[str, Any]:
    diagnostic = validation.diagnostic.to_payload()
    repair_summary = ExplanationRepairFeedbackBuilder().build(diagnostic=validation.diagnostic)
    return _sanitize_for_prompt(
        {
            "attempt": attempt,
            "lesson_draft": lesson_draft,
            "normalized_lesson_draft": validation.normalized_lesson_draft,
            "diagnostic": diagnostic,
            "repair_summary": repair_summary,
        }
    )


def _repair_next_actions(blocker: LessonDraftBlocker | None) -> list[str]:
    if blocker is None:
        return []
    code = blocker.code
    if code == "schema_invalid":
        return ["输出完整 JSON 对象，且必须包含非空 steps 数组；每个 derive item 必须是 [label, text]。"]
    if code == "unknown_candidate_group_id":
        return ["只使用当前 prompt 的 candidate_groups[].candidate_group_id，不要发明 candidate id。"]
    if code == "unknown_source_step_id":
        return ["优先使用 candidate_group_ids；不要复制 few-shot 的 source_step_ids。"]
    if code == "cross_scope_merge_not_allowed":
        return ["把不同 scope 的讲解拆成不同 LessonIR steps。"]
    if code == "unknown_handle":
        return ["删除 draft/trace 没有提供的 handle、点名、事实或结论，只使用当前题已给 facts。"]
    if code == "answer_values_missing":
        return ["把 answers 中每个最终答案写入相关最终讲解步骤的 box。"]
    if code == "derive_style_invalid":
        return ["把 derive 改成二维数组，并使用 作/∵/∴；原因和结论必须拆成相邻行。"]
    if code == "cognitive_action_merge_not_allowed":
        return ["把路径转化和求最值拆成两个 LessonIR steps：先讲 path_reduction，再讲 minimum_by_segment。"]
    if code == "missing_required_candidate_group":
        missing = (blocker.details or {}).get("missing_candidate_group_ids", [])
        return [f"补上遗漏的 candidate_group_ids：{missing}，不要把它们静默并入大步骤。"]
    return ["从 current_blocker 所在步骤开始修正，保留已接受步骤的分组意图。"]


def _repair_do_not(blocker: LessonDraftBlocker | None) -> list[str]:
    base = [
        "不要新增数学事实、点名、数值、答案或 handle。",
        "不要复制 few-shot 的 source ids、点名、数值或答案。",
        "不要把 already_normalized 的 derive 风格问题继续原样输出。",
    ]
    if blocker is None:
        return base
    if blocker.code == "cognitive_action_merge_not_allowed":
        base.append("不要把“构造/路径转化”和“求最值/计算表达式”写进同一个 Lesson step。")
    if blocker.code in {"unknown_candidate_group_id", "unknown_source_step_id"}:
        base.append("不要发明 candidate_group_id 或 source_step_id。")
    return base


def _sanitize_for_prompt(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in {"expected", "traceback"}:
                continue
            result[key_text] = _sanitize_for_prompt(child)
        return result
    if isinstance(value, list):
        return [_sanitize_for_prompt(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_for_prompt(item) for item in value]
    if isinstance(value, str):
        text = value
        for forbidden in ("$problem.", "$question.", "$subquestion."):
            text = text.replace(forbidden, "[context-path].")
        text = text.replace("Traceback", "[traceback]")
        return text
    return value


def _group_payload(group: LessonCandidateGroup, snapshot: ExplanationSnapshot) -> dict[str, Any]:
    step = group.step
    payload = {
        "candidate_group_id": group.candidate_group_id,
        "source_step_id": group.step_id,
        "teaching_substep_id": group.teaching_substep_id,
        "teaching_substep_title": group.teaching_substep_title,
        "teaching_focus": group.teaching_focus,
        "scope_id": group.scope_id,
        "capability_id": group.capability_id,
        "method_ids": list(group.method_ids),
        "target": step.get("target"),
        "goal_type": step.get("goal_type"),
        "strategy": step.get("strategy"),
        "reason": step.get("reason"),
        "reads": step.get("reads", []),
        "produces": step.get("produces", []),
        "trace_refs": list(group.trace_refs),
        "trace_summaries": _trace_summaries(group, snapshot),
    }
    payload.update(explanation_payload_for_group(group, snapshot))
    return payload


def _lesson_few_shot_examples(
    *,
    snapshot: ExplanationSnapshot,
    candidate_groups: list[dict[str, Any]],
    few_shot_dir: str | Path | None,
    allow_same_problem: bool,
) -> list[dict[str, Any]]:
    goal_types = [
        str(group.get("goal_type"))
        for group in candidate_groups
        if group.get("goal_type")
    ]
    capability_ids = [
        str(group.get("capability_id"))
        for group in candidate_groups
        if group.get("capability_id")
    ]
    selected = select_lesson_few_shot_examples(
        family_id=snapshot.family_id,
        goal_types=goal_types,
        capability_ids=capability_ids,
        problem_id=snapshot.problem_id,
        allow_same_problem=allow_same_problem,
        top_k=1,
        few_shot_dir=few_shot_dir,
    )
    if selected:
        return selected
    builder = _LESSON_FALLBACK_FEW_SHOT_BUILDERS.get(
        snapshot.family_id,
        generic_lesson_mock_few_shot,
    )
    return [builder(snapshot.family_id)]


def _teaching_step_policy(groups: tuple[LessonCandidateGroup, ...]) -> dict[str, Any]:
    """给 LLM 的教学步粒度策略。

    已验证复杂 25 题 lesson-data 的有效粒度是“认知动作”，不是“小问整体”：
    求解析式、角度转化、联立求点、参数化、双动点转单动点、最短路径、反求参数。
    """
    group_count = len(groups)
    target_min = max(3, min(group_count, round(group_count * 0.45)))
    target_max = max(target_min, min(group_count, round(group_count * 0.75)))
    return {
        "granularity": "每个 lesson step 只讲一个认知动作",
        "do_not": [
            "不要把一个完整小问直接合并成一个 lesson step，除非它本来只有一个认知动作。",
            "不要机械地保持 one method per lesson step；相邻的纯坐标/代数准备可以合并。",
            "不要跨 scope 合并。",
        ],
        "keep_separate_when_present": [
            "求/化简函数解析式或含参解析式",
            "由角度、等长、旋转、正方形等几何关系得到辅助对象",
            "联立直线/曲线或筛选候选点",
            "把多动点路径转化为单动点路径",
            "用将军饮马、两点距离或几何不等式说明最小值",
            "由最小值或条件反求参数",
            "极值状态下恢复最终答案点",
        ],
        "merge_when_adjacent": [
            "同一认知动作内的坐标准备和代入验算",
            "同一 recipe 内部的候选生成与选择，若学生只需要理解一个动作",
            "纯代数化简链条，若没有新的几何思想",
        ],
        "target_step_count_hint": {
            "candidate_group_count": group_count,
            "recommended_min": target_min,
            "recommended_max": target_max,
            "note": "这是软约束；优先保证认知动作清晰。",
        },
        "style_reference": (
            "目标粒度类似人工 lesson-data：一个复杂 25 题通常拆成约 6-8 个学生步骤，"
            "而不是每个小问一个步骤。"
        ),
    }


def _trace_summaries(group: LessonCandidateGroup, snapshot: ExplanationSnapshot) -> list[dict[str, Any]]:
    traces = {entry.trace_id: entry for entry in snapshot.teaching_trace}
    result = []
    for trace_id in group.trace_refs:
        entry = traces.get(trace_id)
        if entry is None:
            continue
        result.append(
            {
                "trace_id": entry.trace_id,
                "method_id": entry.method_id,
                "trace_fragments": list(entry.trace_fragments),
                "checks": list(entry.checks),
            }
        )
    return result


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("explanation LLM must return a JSON object")
    return parsed


def _default_template_dir() -> Path:
    return repo_root() / "internal" / "llm-prompts"


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
