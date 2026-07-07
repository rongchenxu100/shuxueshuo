"""Final answer goal verification for StepIntent replay.

This module checks proof-shape obligations that do not require knowing the
expected answer. Runtime methods can be locally executable while the final
answer is still not shown to satisfy the authored question goal. The verifier
turns those cases into structured retry issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_scope,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StepIntent,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
)


@dataclass(frozen=True)
class AnswerGoalVerifier:
    """Verify that final answer steps carry enough goal evidence."""

    def verify(
        self,
        draft: StepIntentDraft | None,
        *,
        problem_payload: Mapping[str, Any] | None,
        handle_registry: CanonicalHandleRegistry,
        diagnostic: StepIntentExecutionDiagnostic | None = None,
    ) -> tuple[PlannerRetryIssue, ...]:
        """Return goal verification issues for an otherwise executable draft."""
        if draft is None or problem_payload is None:
            return ()
        goals = _canonical_question_goals(problem_payload)
        if not goals:
            return ()
        produced = _produced_output_types(draft)
        issues: list[PlannerRetryIssue] = []
        for goal in goals:
            if not bool(goal.get("required", True)):
                continue
            goal_handle = str(goal.get("handle", "")).strip()
            if not goal_handle:
                continue
            step = _producing_step(draft, goal_handle)
            if step is None:
                continue
            value_type = str(goal.get("value_type", "")).strip()
            if value_type == "Point":
                issue = _point_goal_issue(
                    goal,
                    step=step,
                    handle_registry=handle_registry,
                )
                if issue is not None:
                    issues.append(issue)
            elif value_type == "MinimumExpression":
                issue = _minimum_goal_issue(
                    goal,
                    step=step,
                    draft=draft,
                    produced_output_types=produced,
                    handle_registry=handle_registry,
                    diagnostic=diagnostic,
                )
                if issue is not None:
                    issues.append(issue)
        return tuple(issues)


def _canonical_question_goals(
    problem_payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    goals = problem_payload.get("question_goals")
    if not isinstance(goals, list):
        return ()
    return tuple(item for item in goals if isinstance(item, Mapping))


def _producing_step(draft: StepIntentDraft, handle: str) -> StepIntent | None:
    for step in draft.steps:
        if step.target == handle:
            return step
        if any(item.handle == handle for item in step.produces):
            return step
    return None


def _produced_output_types(draft: StepIntentDraft) -> dict[str, str]:
    result: dict[str, str] = {}
    for step in draft.steps:
        for item in step.produces:
            if item.output_type:
                result[item.handle] = item.output_type
    return result


def _point_goal_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
) -> PlannerRetryIssue | None:
    target_handle = str(goal.get("target_handle", "")).strip()
    if not target_handle or not target_handle.startswith("point:"):
        return None
    if not _point_goal_requires_explicit_identity(
        target_handle,
        scope_id=step.scope_id,
        handle_registry=handle_registry,
    ):
        return None
    if _step_mentions_handle(step, target_handle):
        return None
    related = _related_handles_for_point_goal(
        target_handle,
        scope_id=step.scope_id,
        handle_registry=handle_registry,
    )
    return PlannerRetryIssue(
        layer="goal_verification",
        code="point_goal_identity_unproven",
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target=str(goal.get("handle") or step.target),
        message=(
            f"{step.step_id} produces a Point answer but does not read or "
            f"create the target point {target_handle}; the answer identity is "
            "not proven from the question goal."
        ),
        hints=(
            "最终 Point answer 必须绑定到 question_goals.target_handle；"
            "请从该 step 起重写 suffix，使 producing step 读取目标点及其题面条件。",
            "不要只求一个可执行交点；需要证明该点就是题目要求的目标点。",
        ),
        related_handles=related,
    )


def _minimum_goal_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    draft: StepIntentDraft,
    produced_output_types: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> PlannerRetryIssue | None:
    if step.recipe_hint != "evaluate_expression_at_parameter":
        return None
    path_targets = _visible_facts_by_type(
        "path_minimum_target",
        scope_id=step.scope_id,
        handle_registry=handle_registry,
    )
    if not path_targets:
        return None
    straightening_witnesses = _straightening_witness_handles(
        draft,
        scope_id=step.scope_id,
        produced_output_types=produced_output_types,
        handle_registry=handle_registry,
        diagnostic=diagnostic,
    )
    if not straightening_witnesses:
        return None
    if any(handle in set(step.reads) for handle in straightening_witnesses):
        return None
    related = _unique_ordered((*path_targets, *straightening_witnesses, *step.reads))
    return PlannerRetryIssue(
        layer="goal_verification",
        code="minimum_goal_lineage_incomplete",
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target=str(goal.get("handle") or step.target),
        message=(
            f"{step.step_id} directly evaluates a MinimumExpression for a path "
            "minimum answer, but does not read the path target or straightening "
            "witnesses that prove this expression is the requested final goal."
        ),
        hints=(
            "路径最值 final answer 需要保留从 path_minimum_target 到拉直方案、端点/距离 witness 的证明链。",
            "请从该 step 起重写 suffix；不要只把一个 MinimumExpression 当普通表达式代入。",
        ),
        related_handles=related,
    )


def _straightening_witness_handles(
    draft: StepIntentDraft,
    *,
    scope_id: str,
    produced_output_types: Mapping[str, str],
    handle_registry: CanonicalHandleRegistry,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> tuple[str, ...]:
    handles: list[str] = []
    for handle, output_type in produced_output_types.items():
        if output_type == "StraighteningCandidate" and _is_visible(
            handle,
            scope_id=scope_id,
            handle_registry=handle_registry,
        ):
            handles.append(handle)
        elif (
            output_type == "Point"
            and _semantic_name(handle).startswith("path_minimum_point_")
            and _is_visible(handle, scope_id=scope_id, handle_registry=handle_registry)
        ):
            handles.append(handle)
    if diagnostic is not None:
        for insight in diagnostic.planner_insights:
            if insight.output_type == "StraighteningMinimum":
                handles.append(insight.produced_handle)
                minimum_points = insight.facts.get("minimum_points")
                if isinstance(minimum_points, list):
                    handles.extend(str(item) for item in minimum_points if item)
    return _unique_ordered(handles)


def _visible_facts_by_type(
    fact_type: str,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    result: list[str] = []
    for handle, current_type in handle_registry.fact_types.items():
        if current_type != fact_type:
            continue
        if _is_visible(handle, scope_id=scope_id, handle_registry=handle_registry):
            result.append(handle)
    return tuple(result)


def _related_handles_for_point_goal(
    target_handle: str,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    related: list[str] = [target_handle]
    for fact_handle, payload in handle_registry.fact_payloads.items():
        if not _is_visible(
            fact_handle,
            scope_id=scope_id,
            handle_registry=handle_registry,
        ):
            continue
        if _payload_mentions(payload, target_handle):
            related.append(fact_handle)
            for value in payload.values():
                if isinstance(value, str) and _looks_like_handle(value):
                    related.append(value)
                elif isinstance(value, list):
                    related.extend(
                        item for item in value
                        if isinstance(item, str) and _looks_like_handle(item)
                    )
    return _unique_ordered(related)


def _point_goal_requires_explicit_identity(
    target_handle: str,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    payload = handle_registry.entity_payloads.get(target_handle, {})
    definition = str(payload.get("definition", "")).strip()
    if definition == "point_on_segment":
        return True
    for fact_handle, fact_payload in handle_registry.fact_payloads.items():
        if not _is_visible(
            fact_handle,
            scope_id=scope_id,
            handle_registry=handle_registry,
        ):
            continue
        if fact_payload.get("point") == target_handle and fact_payload.get("type") == "segment_membership":
            return True
    return False


def _step_mentions_handle(step: StepIntent, handle: str) -> bool:
    return (
        step.target == handle
        or handle in step.reads
        or any(item.handle == handle for item in step.creates)
        or any(item.handle == handle for item in step.produces)
    )


def _payload_mentions(payload: Mapping[str, Any], handle: str) -> bool:
    for value in payload.values():
        if value == handle:
            return True
        if isinstance(value, list) and handle in value:
            return True
    return False


def _is_visible(
    handle: str,
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    valid_scope = handle_registry.handle_valid_scopes.get(handle) or _handle_scope(handle)
    try:
        return valid_scope in handle_registry.ancestor_scopes(scope_id)
    except Exception:
        return False


def _semantic_name(handle: str) -> str:
    if handle.startswith("answer:"):
        return handle.rsplit(".", 1)[-1]
    parts = handle.split(":")
    return parts[-1] if parts else handle


def _looks_like_handle(value: str) -> bool:
    return value.startswith(("point:", "line:", "segment:", "ray:", "fact:", "answer:"))


def _unique_ordered(items: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
