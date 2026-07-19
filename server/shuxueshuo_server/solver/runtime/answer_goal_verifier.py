"""Final answer goal verification for StepIntent replay.

This module checks proof-shape obligations that do not require knowing the
expected answer. Runtime methods can be locally executable while the final
answer is still not shown to satisfy the authored question goal. The verifier
turns those cases into structured retry issues.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shuxueshuo_server.solver.family.models import GoalEvidenceTag, SolverFamilySpec
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
from shuxueshuo_server.solver.state_semantics import is_object_handle
from shuxueshuo_server.solver.utils import unique_ordered


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
        family_spec: SolverFamilySpec | None = None,
    ) -> tuple[PlannerRetryIssue, ...]:
        """Return goal verification issues for an otherwise executable draft."""
        if draft is None or problem_payload is None:
            return ()
        goals = _canonical_question_goals(problem_payload)
        if not goals:
            return ()
        accepted_step_ids = (
            {item.step_id for item in diagnostic.accepted_prefix}
            if diagnostic is not None and not diagnostic.ok
            else None
        )
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
            if accepted_step_ids is not None and step.step_id not in accepted_step_ids:
                # A failed trial has not executed this answer producer yet. The
                # first runtime blocker owns the repair window; diagnosing the
                # unexecuted suffix would hide that earlier failure.
                continue
            unresolved_symbol_issue = _unresolved_answer_symbol_issue(
                goal,
                step=step,
                draft=draft,
                handle_registry=handle_registry,
                diagnostic=diagnostic,
            )
            if unresolved_symbol_issue is not None:
                issues.append(unresolved_symbol_issue)
                continue
            value_type = str(goal.get("value_type", "")).strip()
            if value_type == "Point":
                issue = _point_goal_issue(
                    goal,
                    step=step,
                    handle_registry=handle_registry,
                    diagnostic=diagnostic,
                )
                if issue is not None:
                    issues.append(issue)
            elif value_type == "MinimumExpression":
                issue = _minimum_goal_issue(
                    goal,
                    step=step,
                    handle_registry=handle_registry,
                    diagnostic=diagnostic,
                    family_spec=family_spec,
                )
                if issue is not None:
                    issues.append(issue)
        return tuple(issues)


def _unresolved_answer_symbol_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    draft: StepIntentDraft,
    handle_registry: CanonicalHandleRegistry,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> PlannerRetryIssue | None:
    """Reject a symbolic final value when matching substitutions already exist.

    A final answer may legitimately depend on a free symbol. It becomes a
    planner error only when an earlier, visible ``ParameterValue`` state for
    that same Symbol identity already exists: in that case the answer producer
    failed to consume available state rather than intentionally returning a
    parameterized result.
    """
    if diagnostic is None:
        return None
    goal_handle = str(goal.get("handle", "")).strip()
    answer_write = next(
        (
            item
            for item in reversed(diagnostic.state_write_provenance)
            if item.produced_handle == goal_handle
        ),
        None,
    )
    if answer_write is None or not answer_write.free_symbol_names:
        return None

    step_positions = {
        current.step_id: index
        for index, current in enumerate(draft.steps)
    }
    answer_position = step_positions.get(step.step_id)
    if answer_position is None:
        return None

    free_symbols = set(answer_write.free_symbol_names)
    available: list[tuple[str, str, str]] = []
    for item in diagnostic.state_write_provenance:
        if item.runtime_type != "ParameterValue":
            continue
        symbol_name = _symbol_name_from_object_ref(item.object_ref)
        if symbol_name is None or symbol_name not in free_symbols:
            continue
        producer_position = step_positions.get(item.step_id)
        if producer_position is None or producer_position >= answer_position:
            continue
        if not _provenance_write_is_visible(
            item.produced_handle,
            producer_scope_id=item.scope_id,
            consumer_scope_id=step.scope_id,
            handle_registry=handle_registry,
        ):
            continue
        available.append((symbol_name, item.produced_handle, item.object_ref or ""))

    if not available:
        return None
    available_symbols = unique_ordered(item[0] for item in available)
    available_handles = unique_ordered(item[1] for item in available)
    symbol_refs = unique_ordered(item[2] for item in available if item[2])
    return PlannerRetryIssue(
        layer="goal_verification",
        code="answer_unresolved_symbol_state",
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target=goal_handle or step.target,
        message=(
            f"{step.step_id} writes the final answer with unresolved symbols "
            f"{', '.join(available_symbols)}, even though matching visible "
            "ParameterValue states were produced earlier."
        ),
        hints=(
            "最终 answer 不应直接绑定仍含自由参数的中间状态；请让 answer producer 消费已存在的参数值状态。",
            "保持现有参数求值 call，并从该 answer producer 起修复数据连接或增加确定性代入 call。",
        ),
        related_handles=unique_ordered(
            (goal_handle, *symbol_refs, *available_handles)
        ),
        details={
            "unresolved_symbols": list(answer_write.free_symbol_names),
            "available_parameter_symbols": list(available_symbols),
            "available_parameter_states": list(available_handles),
        },
    )


def _symbol_name_from_object_ref(object_ref: str | None) -> str | None:
    if object_ref is None or not object_ref.startswith("symbol:"):
        return None
    name = object_ref.rsplit(":", 1)[-1].strip()
    return name or None


def _provenance_write_is_visible(
    produced_handle: str,
    *,
    producer_scope_id: str,
    consumer_scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    valid_scope = (
        handle_registry.handle_valid_scopes.get(produced_handle)
        or producer_scope_id
    )
    try:
        return valid_scope in handle_registry.ancestor_scopes(consumer_scope_id)
    except Exception:
        return False


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


def _point_goal_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> PlannerRetryIssue | None:
    target_handle = str(goal.get("target_handle", "")).strip()
    if not target_handle or not target_handle.startswith("point:"):
        return None
    if diagnostic is not None:
        provenance = next(
            (
                item
                for item in reversed(diagnostic.state_write_provenance)
                if item.produced_handle == str(goal.get("handle", ""))
            ),
            None,
        )
        if provenance is None:
            return _point_provenance_issue(
                goal,
                step=step,
                target_handle=target_handle,
                actual_object_ref=None,
                source_step_id=None,
                source_handles=(),
                handle_registry=handle_registry,
            )
        if provenance.object_ref != target_handle:
            return _point_provenance_issue(
                goal,
                step=step,
                target_handle=target_handle,
                actual_object_ref=provenance.object_ref,
                source_step_id=provenance.source_step_id,
                source_handles=provenance.source_handles,
                handle_registry=handle_registry,
            )
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


def _point_provenance_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    target_handle: str,
    actual_object_ref: str | None,
    source_step_id: str | None,
    source_handles: tuple[str, ...],
    handle_registry: CanonicalHandleRegistry,
) -> PlannerRetryIssue:
    issue_step_id = source_step_id or step.step_id
    code = (
        "point_goal_source_mismatch"
        if actual_object_ref is not None
        else "point_goal_identity_unproven"
    )
    related = unique_ordered(
        (
            *_related_handles_for_point_goal(
                target_handle,
                scope_id=step.scope_id,
                handle_registry=handle_registry,
            ),
            *source_handles,
        )
    )
    return PlannerRetryIssue(
        layer="goal_verification",
        code=code,
        step_id=issue_step_id,
        scope_id=step.scope_id,
        repair_target=str(goal.get("handle") or step.target),
        message=(
            f"Point answer requires object {target_handle}, but its state write "
            f"provenance resolves to {actual_object_ref or 'no object identity'}."
        ),
        hints=(
            "从最早写错对象身份的 producer 起重写 suffix；端点、辅助点或候选点"
            "不能仅通过改名满足另一个目标点。",
            "最终 Point answer 的状态必须由同一目标对象的坐标状态推导。",
        ),
        related_handles=related,
    )


def _minimum_goal_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    handle_registry: CanonicalHandleRegistry,
    diagnostic: StepIntentExecutionDiagnostic | None,
    family_spec: SolverFamilySpec | None,
) -> PlannerRetryIssue | None:
    if diagnostic is None or family_spec is None:
        return None
    expression_roles = _goal_evidence_roles(
        family_spec,
        "path_minimum_expression",
    )
    witness_roles = _goal_evidence_roles(
        family_spec,
        "path_minimum_witness",
    )
    if not expression_roles or not witness_roles:
        return None
    path_targets = _visible_facts_by_type(
        "path_minimum_target",
        scope_id=step.scope_id,
        handle_registry=handle_registry,
    )
    if not path_targets:
        return None
    goal_handle = str(goal.get("handle", ""))
    answer_write = next(
        (
            item
            for item in reversed(diagnostic.state_write_provenance)
            if item.produced_handle == goal_handle
        ),
        None,
    )
    if answer_write is not None:
        lineage = _state_write_lineage(
            answer_write,
            diagnostic=diagnostic,
        )
        lineage_roles = {
            role
            for item in lineage
            for role in (item.identity_role, *item.evidence_roles)
        }
        lineage_handles = unique_ordered(
            handle
            for item in lineage
            for handle in (item.produced_handle, *item.source_handles)
        )
        has_expression = bool(lineage_roles & expression_roles)
        has_witness = bool(lineage_roles & witness_roles)
        has_path_target = bool(set(lineage_handles) & set(path_targets))
        if not has_expression:
            return _minimum_goal_provenance_issue(
                goal,
                step=step,
                code="minimum_goal_source_unproven",
                message=(
                    f"{step.step_id} writes a path-minimum answer from states "
                    "whose provenance does not contain a declared "
                    "path_minimum_expression role."
                ),
                path_targets=path_targets,
                lineage_handles=lineage_handles,
                missing_roles=tuple(sorted(expression_roles)),
            )
        if not has_witness or not has_path_target:
            missing_role_items = (
                list(sorted(witness_roles)) if not has_witness else []
            )
            if not has_path_target:
                missing_role_items.append("path_minimum_target")
            return _minimum_goal_provenance_issue(
                goal,
                step=step,
                code="minimum_goal_lineage_incomplete",
                message=(
                    f"{step.step_id} writes a path-minimum answer, but its "
                    "provenance dependency graph does not contain the required "
                    "path target and straightening witnesses."
                ),
                path_targets=path_targets,
                lineage_handles=lineage_handles,
                missing_roles=tuple(missing_role_items),
            )
        return None

    # Compatibility fallback for diagnostics recorded before answer-write
    # provenance was available.
    expression_handles = _goal_evidence_handles(
        diagnostic,
        roles=expression_roles,
        scope_id=step.scope_id,
        handle_registry=handle_registry,
    )
    if not set(step.reads) & set(expression_handles):
        return None
    straightening_witnesses = _goal_evidence_handles(
        diagnostic,
        roles=witness_roles,
        scope_id=step.scope_id,
        handle_registry=handle_registry,
    )
    if not straightening_witnesses:
        return None
    if any(handle in set(step.reads) for handle in straightening_witnesses):
        return None
    related = unique_ordered((*path_targets, *straightening_witnesses, *step.reads))
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


def _state_write_lineage(
    root: Any,
    *,
    diagnostic: StepIntentExecutionDiagnostic,
) -> tuple[Any, ...]:
    """Return the provenance subgraph that actually contributes to ``root``."""
    by_handle = {
        item.produced_handle: item
        for item in diagnostic.state_write_provenance
    }
    by_step: dict[str, list[Any]] = {}
    for item in diagnostic.state_write_provenance:
        by_step.setdefault(item.step_id, []).append(item)
    result: list[Any] = []
    seen: set[tuple[str, str, str]] = set()
    pending = [root]
    while pending:
        item = pending.pop()
        key = (item.step_id, item.produced_handle, item.output_key)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        pending.extend(by_step.get(item.step_id, ()))
        pending.extend(
            producer
            for handle in item.source_handles
            if (producer := by_handle.get(handle)) is not None
        )
    return tuple(result)


def _minimum_goal_provenance_issue(
    goal: Mapping[str, Any],
    *,
    step: StepIntent,
    code: str,
    message: str,
    path_targets: tuple[str, ...],
    lineage_handles: tuple[str, ...],
    missing_roles: tuple[str, ...],
) -> PlannerRetryIssue:
    return PlannerRetryIssue(
        layer="goal_verification",
        code=code,
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target=str(goal.get("handle") or step.target),
        message=message,
        hints=(
            "最终路径最值 answer 必须消费 contract 标注的 path-minimum expression，而不是旁路普通距离或独立表达式。",
            "独立执行但未进入 answer provenance 子图的拉直步骤不构成证明；请修复 call result 数据连接。",
        ),
        related_handles=unique_ordered(
            (*path_targets, *lineage_handles)
        ),
        details={
            "missing_semantic_roles": list(missing_roles),
        },
    )


def _goal_evidence_roles(
    family_spec: SolverFamilySpec,
    tag: GoalEvidenceTag,
) -> frozenset[str]:
    return frozenset(
        output.semantic_role
        for recipe in family_spec.step_recipes
        if recipe.execution is not None
        for output in recipe.execution.output_aliases
        if tag in output.goal_evidence_tags
    )


def _goal_evidence_handles(
    diagnostic: StepIntentExecutionDiagnostic,
    *,
    roles: frozenset[str],
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[str, ...]:
    if not roles:
        return ()
    return unique_ordered(
        item.produced_handle
        for item in diagnostic.state_write_provenance
        if item.identity_role in roles
        and _is_visible(
            item.produced_handle,
            scope_id=scope_id,
            handle_registry=handle_registry,
        )
    )


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
    return unique_ordered(related)


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


def _looks_like_handle(value: str) -> bool:
    return is_object_handle(value) or value.startswith(("fact:", "answer:"))
