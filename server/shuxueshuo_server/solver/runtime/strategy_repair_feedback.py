"""LLM-facing repair feedback for Strategy StepIntent loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntentDraft,
    StepIntentExecutionBlocker,
    StepIntentExecutionDiagnostic,
    StepIntentPlannerInsight,
    StepIntentPreflightIssue,
)


@dataclass(frozen=True)
class RepairHintSpec:
    """Capability-owned LLM repair hint."""

    code: str
    message: str
    next_actions: tuple[str, ...] = ()
    do_not: tuple[str, ...] = ()
    already_handled: tuple[str, ...] = ()
    applies_to: tuple[str, ...] = ("generic",)
    source: str = "default"

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RepairHintSpec":
        """Parse a hint payload from method/family/binding metadata."""
        return cls(
            code=str(payload.get("code", "")),
            message=str(payload.get("message", "")),
            next_actions=tuple(str(item) for item in payload.get("next_actions", ())),
            do_not=tuple(str(item) for item in payload.get("do_not", ())),
            already_handled=tuple(str(item) for item in payload.get("already_handled", ())),
            applies_to=tuple(str(item) for item in payload.get("applies_to", ("generic",))),
            source=str(payload.get("source", "method_spec")),
        )


class RepairHintRegistry:
    """Lookup capability-owned repair hints for a runtime blocker."""

    def __init__(self, hints: tuple[RepairHintSpec, ...]) -> None:
        self.hints = hints

    @classmethod
    def default(cls) -> "RepairHintRegistry":
        """Build the default runtime hint registry."""
        hints: list[RepairHintSpec] = []
        try:
            method_specs = MethodSpecRegistry.load_from_code()
        except Exception:
            method_specs = None
        if method_specs is not None:
            for spec in method_specs.specs.values():
                for raw in spec.repair_hints:
                    hint = RepairHintSpec.from_payload(raw)
                    if hint.applies_to == ("generic",):
                        hint = RepairHintSpec(
                            code=hint.code,
                            message=hint.message,
                            next_actions=hint.next_actions,
                            do_not=hint.do_not,
                            already_handled=hint.already_handled,
                            applies_to=(f"method:{spec.method_id}",),
                            source=hint.source,
                        )
                    hints.append(hint)
        hints.extend(_DEFAULT_REPAIR_HINTS)
        return cls(tuple(hints))

    def find(self, blocker: StepIntentExecutionBlocker | None) -> RepairHintSpec | None:
        """Return the best matching hint for a blocker."""
        if blocker is None:
            return None
        text = _blocker_text(blocker)
        matches = [
            (self._score(hint, blocker=blocker, text=text), hint)
            for hint in self.hints
            if _hint_matches_code(hint, blocker=blocker, text=text)
        ]
        matches = [(score, hint) for score, hint in matches if score > 0]
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def _score(
        self,
        hint: RepairHintSpec,
        *,
        blocker: StepIntentExecutionBlocker,
        text: str,
    ) -> int:
        score = 1
        if hint.source == "method_spec":
            score += 10
        elif hint.source in {"family_spec", "binding_spec", "recipe_spec"}:
            score += 8
        applies = set(hint.applies_to)
        if "generic" in applies:
            score += 1
        for target in applies:
            if target == "generic":
                continue
            capability_id = target.removeprefix("method:")
            recipe_id = target.removeprefix("recipe:")
            selector = target.removeprefix("binding_selector:")
            if blocker.capability_id == capability_id or capability_id in text:
                score += 20
            if blocker.capability_id == recipe_id or recipe_id in text:
                score += 20
            if selector in text:
                score += 20
        if blocker.code == hint.code:
            score += 5
        return score


@dataclass(frozen=True)
class RepairFeedbackBuilder:
    """Build a compact repair summary from execution diagnostics.

    The summary is intentionally LLM-facing: it keeps semantic handles and short
    instructions, but never exposes RuntimePath, MethodInvocation, traceback, or
    expected answers.
    """

    diagnostic: StepIntentExecutionDiagnostic | None
    errors: tuple[str, ...] = ()
    effective_draft: StepIntentDraft | None = None
    hint_registry: RepairHintRegistry = field(default_factory=RepairHintRegistry.default)

    def build(self) -> dict[str, Any]:
        """Return a safe JSON payload for ``previous_attempts[].repair_summary``."""
        diagnostic = self.diagnostic
        summary: dict[str, Any] = {
            "frozen_prefix": [],
            "planner_state": {},
            "current_blocker": None,
            "already_handled": [],
            "next_actions": [],
            "do_not": [],
            "warnings": [],
        }
        if diagnostic is None:
            summary["next_actions"].append(
                "根据 errors 修复并重新输出完整 StepIntent JSON；不要输出 patch。"
            )
            summary["do_not"].append("不要引入 RuntimePath、ContextPath 或 expected answer。")
            return summary

        summary["frozen_prefix"] = [
            {
                "step_id": item.step_id,
                "scope_id": item.scope_id,
                "capability_id": item.capability_id,
            }
            for item in diagnostic.accepted_prefix
        ]
        summary["planner_state"] = _planner_state_from_insights(
            diagnostic.planner_insights
        )
        summary["already_handled"] = _already_handled(diagnostic)
        summary["warnings"] = _warnings(diagnostic.preflight_issues)
        blocker = diagnostic.first_blocker
        hint = self.hint_registry.find(blocker)
        if blocker is not None:
            summary["current_blocker"] = _current_blocker(blocker, hint=hint)
        summary["next_actions"] = _next_actions(
            blocker=blocker,
            hint=hint,
            planner_state=summary["planner_state"],
            already_handled=summary["already_handled"],
            errors=self.errors,
        )
        summary["do_not"] = _do_not(
            blocker=blocker,
            hint=hint,
            has_frozen_prefix=bool(diagnostic.accepted_prefix),
            has_already_handled=bool(summary["already_handled"]),
        )
        return summary


def _planner_state_from_insights(
    insights: tuple[StepIntentPlannerInsight, ...],
) -> dict[str, Any]:
    """Merge all planner insights into stable state buckets."""
    state: dict[str, Any] = {}
    other: list[dict[str, Any]] = []
    for insight in insights:
        if insight.output_type == "PathTransformation":
            state["reduced_path"] = {
                "source_step": insight.step_id,
                "produced_handle": insight.produced_handle,
                "moving_point": insight.facts.get("moving_point"),
                "fixed_points": insight.facts.get("fixed_points", []),
                "transformed_path": insight.facts.get("transformed_path"),
                "next_locus_step": insight.facts.get("next_locus_step"),
                "repair_note": insight.repair_note,
            }
            continue
        if insight.output_type == "StraighteningMinimum":
            points = _preferred_minimum_points(insight.facts.get("minimum_points"))
            state["straightening_minimum"] = {
                "source_step": insight.step_id,
                "produced_handle": insight.produced_handle,
                "minimum_points": points,
                "next_method": insight.facts.get("next_method"),
                "repair_note": insight.repair_note,
            }
            continue
        other.append(insight.to_payload())
    if other:
        state["other_insights"] = other
    return state


def _preferred_minimum_points(value: Any) -> list[str]:
    """Expose canonical path_minimum_point handles before lower-level aliases."""
    if not isinstance(value, list):
        return []
    handles = [str(item) for item in value if isinstance(item, str)]
    preferred = [item for item in handles if "path_minimum_point" in item]
    return _unique_ordered(preferred or handles)


def _already_handled(diagnostic: StepIntentExecutionDiagnostic) -> list[dict[str, str]]:
    """Return fills and code-fillable preflight issues that should not become steps."""
    items: list[dict[str, str]] = []
    for fill in diagnostic.applied_fills:
        items.append(
            {
                "kind": "applied_fill",
                "step_id": fill.step_id,
                "scope_id": fill.scope_id,
                "input_handle": fill.input_handle,
                "required_type": fill.required_type,
                "resolved_handle": fill.resolved_handle,
                "reason": fill.reason,
                "instruction": "代码已能补齐该输入；不要为此新增 utility step。",
            }
        )
    for issue in diagnostic.preflight_issues:
        if issue.category != "code_fillable":
            continue
        items.append(
            {
                "kind": "code_fillable_preflight",
                "step_id": issue.step_id,
                "scope_id": issue.scope_id,
                "code": issue.code,
                "message": issue.message,
                "instruction": "代码可临时补位；不要为此新增 utility step。",
            }
        )
    return items


def _warnings(
    issues: tuple[StepIntentPreflightIssue, ...],
) -> list[dict[str, Any]]:
    """Return non-code-fillable preflight warnings."""
    return [
        {
            "step_id": issue.step_id,
            "scope_id": issue.scope_id,
            "code": issue.code,
            "category": issue.category,
            "message": issue.message,
            "repair": issue.repair,
            "related_steps": list(issue.related_steps),
        }
        for issue in issues
        if issue.category != "code_fillable"
    ]


def _current_blocker(
    blocker: StepIntentExecutionBlocker,
    *,
    hint: RepairHintSpec | None,
) -> dict[str, Any]:
    """Return a short current blocker summary."""
    return {
        "step_id": blocker.step_id,
        "scope_id": blocker.scope_id,
        "stage": blocker.stage,
        "code": blocker.code,
        "message": hint.message if hint is not None else blocker.message,
    }


def _next_actions(
    *,
    blocker: StepIntentExecutionBlocker | None,
    hint: RepairHintSpec | None,
    planner_state: dict[str, Any],
    already_handled: list[dict[str, str]],
    errors: tuple[str, ...],
) -> list[str]:
    """Return concise actions for the next LLM attempt."""
    actions: list[str] = []
    if blocker is not None:
        actions.append(f"从 blocker step `{blocker.step_id}` 开始修复后续 steps。")
        if hint is not None:
            actions.extend(hint.next_actions)
    reduced = planner_state.get("reduced_path")
    straightening = planner_state.get("straightening_minimum")
    if isinstance(reduced, dict) and reduced.get("moving_point"):
        actions.append(
            f"后续轨迹、拉直和最短状态点围绕 moving_point={reduced['moving_point']}；"
            "最终答案若不是该点，再用几何关系恢复。"
        )
        if _is_missing_line_blocker(blocker):
            next_locus = reduced.get("next_locus_step")
            if isinstance(next_locus, dict):
                reads = next_locus.get("recommended_reads")
                produces = next_locus.get("recommended_produces")
                capability = next_locus.get("recommended_next_capability")
                before = next_locus.get("before_capability")
                if capability and reads and produces:
                    actions.append(
                        f"在 `{blocker.step_id if blocker else before}` 前先新增/保留 `{capability}` step："
                        f"reads {reads}，produces `{produces}`。"
                    )
                    if before:
                        actions.append(
                            f"`{before}` step 必须 reads `{reduced.get('produced_handle')}` 和 `{produces}`。"
                        )
    if isinstance(straightening, dict) and straightening.get("minimum_points"):
        actions.append(
            "将军饮马已给出最短线段端点；后续求极值状态动点时读取 "
            + ", ".join(straightening["minimum_points"])
            + "。"
        )
    if already_handled:
        actions.append("`already_handled` 中的问题由代码处理，不需要新增对应 step。")
    if not actions and errors:
        actions.append("根据 errors 修复并重新输出完整 StepIntent JSON。")
    return _unique_ordered(actions)


def _is_missing_line_blocker(blocker: StepIntentExecutionBlocker | None) -> bool:
    """判断 blocker 是否是将军饮马 recipe 缺少动点轨迹 Line。"""
    if blocker is None:
        return False
    if (
        blocker.capability_id == "broken_path_straightening_minimum_expression"
        and blocker.missing_runtime_type == "Line"
    ):
        return True
    text = _blocker_text(blocker)
    return (
        "broken_path_straightening_minimum_expression" in text
        and "binding_type_not_found" in text
        and "type=Line" in text
    )


def _do_not(
    *,
    blocker: StepIntentExecutionBlocker | None,
    hint: RepairHintSpec | None,
    has_frozen_prefix: bool,
    has_already_handled: bool,
) -> list[str]:
    """Return explicit guardrails for the next attempt."""
    items: list[str] = ["不要输出 patch；仍需输出完整 StepIntent JSON。"]
    if has_frozen_prefix:
        items.append("不要重写 frozen_prefix 中已通过步骤的语义。")
    if has_already_handled:
        items.append("不要为 already_handled 中的代码补位新增 utility step。")
    if blocker is not None and hint is not None:
        items.extend(hint.do_not)
    return _unique_ordered(items)


def _blocker_text(blocker: StepIntentExecutionBlocker) -> str:
    """Join blocker message and capability errors for matching."""
    return "\n".join((blocker.message, *blocker.capability_errors))


def _hint_matches_code(
    hint: RepairHintSpec,
    *,
    blocker: StepIntentExecutionBlocker,
    text: str,
) -> bool:
    """Whether a hint code matches a blocker code or error fragment."""
    if not hint.code:
        return False
    if blocker.code == hint.code:
        return True
    return hint.code in text


def _unique_ordered(items: list[str]) -> list[str]:
    """Deduplicate while preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


_DEFAULT_REPAIR_HINTS: tuple[RepairHintSpec, ...] = (
    RepairHintSpec(
        code="binding_type_not_found",
        message="将军饮马 recipe 缺少动点轨迹 Line；应先根据降维后的 moving point 求轨迹线。",
        next_actions=(
            "不要直接进入 `broken_path_straightening_minimum_expression`；先用 `parameterized_point_locus_line` 产生 moving point 的 locus line。",
        ),
        do_not=(
            "不要让 `square_path_dimension_reduction` 直接产出 Line；轨迹线应由 `parameterized_point_locus_line` 产生。",
        ),
        applies_to=("recipe:broken_path_straightening_minimum_expression",),
    ),
    RepairHintSpec(
        code="binding_type_not_found",
        message="缺少可绑定的输入状态；如果同一对象会被多步复用，应先产生公共 fact 后再读取。",
        next_actions=(
            "如果缺少的是 Parabola，且后续多步都要使用同一抛物线，先用 `quadratic_from_constraints` produces `fact:<scope>:parabola_expression`，后续 step 直接 reads 它。",
        ),
        do_not=(
            "不要为代码已经能临时补位的输入新增 utility step。",
        ),
        applies_to=("generic",),
    ),
    RepairHintSpec(
        code="no_typed_outputs_for_step",
        message="该 step 产物不是任何 catalog capability 的输出；应删除自由 utility step 或改用已有 method/recipe。",
        next_actions=(
            "删除自由 utility step，改用 Recipe/Method Catalog 中已有能力。",
        ),
        do_not=(
            "不要输出 method/recipe catalog 外的自由 segment、Equation 或 utility fact step。",
        ),
        applies_to=("generic",),
    ),
)


__all__ = [
    "RepairFeedbackBuilder",
    "RepairHintRegistry",
    "RepairHintSpec",
]
