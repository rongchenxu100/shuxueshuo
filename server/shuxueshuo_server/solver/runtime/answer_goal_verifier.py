"""Final answer goal verification for transactional Functional replay.

This module checks proof-shape obligations that do not require knowing the
expected answer. Runtime methods can be locally executable while the final
answer is still not shown to satisfy the authored question goal. The verifier
turns those cases into structured retry issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

import sympy as sp

from shuxueshuo_server.solver.family.models import GoalEvidenceTag, SolverFamilySpec
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
    _handle_scope,
)
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraph,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectRegistry,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    FunctionalExecutionDiagnostic,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import is_object_handle
from shuxueshuo_server.solver.utils import unique_ordered


AnswerGoalVerificationStatus = Literal[
    "passed",
    "failed",
    "not_executed",
    "unbound",
]


@dataclass(frozen=True)
class FunctionalGoalArtifact:
    """Minimal typed-graph projection used by legacy-shaped goal helpers."""

    handle: str


@dataclass(frozen=True)
class FunctionalGoalProducer:
    """Typed Functional producer view used by goal verification."""

    step_id: str
    scope_id: str
    goal_type: str
    target: str
    reads: tuple[str, ...] = ()
    creates: tuple[FunctionalGoalArtifact, ...] = ()
    produces: tuple[FunctionalGoalArtifact, ...] = ()


@dataclass(frozen=True)
class FunctionalGoalVerificationContext:
    logical_graph: LogicalFunctionalGraph | None
    state_read_index: FunctionalStateReadIndex
    runtime_writes_by_version: Mapping[StateVersionId, Any]
    answer_version_ids: Mapping[str, StateVersionId]
    verified_call_ids: frozenset[str]
    goal_producers: Mapping[str, FunctionalGoalProducer] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class AnswerGoalVerificationItem:
    goal_handle: str
    status: AnswerGoalVerificationStatus
    producer_step_id: str | None = None
    issues: tuple[PlannerRetryIssue, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "goal_handle": self.goal_handle,
            "status": self.status,
            "producer_step_id": self.producer_step_id,
            "issues": [item.to_payload() for item in self.issues],
        }


@dataclass(frozen=True)
class AnswerGoalVerificationReport:
    goals: tuple[AnswerGoalVerificationItem, ...] = ()

    @property
    def issues(self) -> tuple[PlannerRetryIssue, ...]:
        return tuple(
            issue
            for goal in self.goals
            for issue in goal.issues
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "goals": [item.to_payload() for item in self.goals],
        }


@dataclass(frozen=True)
class AnswerGoalVerifier:
    """Verify that final answer steps carry enough goal evidence.

    A free symbol is valid only when the ProblemIR answer contract declares it
    as an independent function variable. An earlier ParameterValue state can
    improve repair guidance, but it never makes an undeclared free symbol valid.
    """

    def verify(
        self,
        *,
        problem_payload: Mapping[str, Any] | None,
        handle_registry: CanonicalHandleRegistry,
        diagnostic: FunctionalExecutionDiagnostic | None = None,
        family_spec: SolverFamilySpec | None = None,
        functional_context: FunctionalGoalVerificationContext | None = None,
    ) -> tuple[PlannerRetryIssue, ...]:
        """Return goal verification issues for an executable Functional graph."""
        return self.verify_report(
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            diagnostic=diagnostic,
            family_spec=family_spec,
            functional_context=functional_context,
        ).issues

    def verify_report(
        self,
        *,
        problem_payload: Mapping[str, Any] | None,
        handle_registry: CanonicalHandleRegistry,
        diagnostic: FunctionalExecutionDiagnostic | None = None,
        family_spec: SolverFamilySpec | None = None,
        functional_context: FunctionalGoalVerificationContext | None = None,
    ) -> AnswerGoalVerificationReport:
        """Return per-goal status without treating unexecuted goals as passed."""
        if problem_payload is None:
            return AnswerGoalVerificationReport()
        if functional_context is None:
            return AnswerGoalVerificationReport()
        goals = _canonical_question_goals(problem_payload)
        if not goals:
            return AnswerGoalVerificationReport()
        accepted_step_ids = (
            {item.step_id for item in diagnostic.accepted_prefix}
            if diagnostic is not None and not diagnostic.ok
            else None
        )
        results: list[AnswerGoalVerificationItem] = []
        for goal in goals:
            if not bool(goal.get("required", True)):
                continue
            goal_handle = str(goal.get("handle", "")).strip()
            if not goal_handle:
                continue
            step = functional_context.goal_producers.get(goal_handle)
            if step is None:
                results.append(
                    AnswerGoalVerificationItem(goal_handle, "unbound")
                )
                continue
            if accepted_step_ids is not None and step.step_id not in accepted_step_ids:
                # A failed trial has not executed this answer producer yet. The
                # first runtime blocker owns the repair window; diagnosing the
                # unexecuted suffix would hide that earlier failure.
                results.append(
                    AnswerGoalVerificationItem(
                        goal_handle,
                        "not_executed",
                        producer_step_id=step.step_id,
                    )
                )
                continue
            goal_issues: list[PlannerRetryIssue] = []
            unresolved_symbol_issue = _unresolved_answer_symbol_issue(
                goal,
                step=step,
                draft=None,
                problem_payload=problem_payload,
                handle_registry=handle_registry,
                diagnostic=diagnostic,
                functional_context=functional_context,
            )
            if unresolved_symbol_issue is not None:
                goal_issues.append(unresolved_symbol_issue)
            else:
                value_type = str(goal.get("value_type", "")).strip()
                if value_type == "Point":
                    issue = _point_goal_issue(
                        goal,
                        step=step,
                        handle_registry=handle_registry,
                        diagnostic=diagnostic,
                        family_spec=family_spec,
                        functional_context=functional_context,
                    )
                    if issue is not None:
                        goal_issues.append(issue)
                elif value_type == "MinimumExpression":
                    issue = _minimum_goal_issue(
                        goal,
                        step=step,
                        handle_registry=handle_registry,
                        diagnostic=diagnostic,
                        family_spec=family_spec,
                        functional_context=functional_context,
                    )
                    if issue is not None:
                        goal_issues.append(issue)
                elif value_type == "ParameterValue":
                    issue = _parameter_goal_constraint_issue(
                        goal,
                        step=step,
                        problem_payload=problem_payload,
                        handle_registry=handle_registry,
                        diagnostic=diagnostic,
                    )
                    if issue is not None:
                        goal_issues.append(issue)
            results.append(
                AnswerGoalVerificationItem(
                    goal_handle,
                    "failed" if goal_issues else "passed",
                    producer_step_id=step.step_id,
                    issues=tuple(goal_issues),
                )
            )
        return AnswerGoalVerificationReport(tuple(results))


def _unresolved_answer_symbol_issue(
    goal: Mapping[str, Any],
    *,
    step: FunctionalGoalProducer,
    draft: None,
    problem_payload: Mapping[str, Any],
    handle_registry: CanonicalHandleRegistry,
    diagnostic: FunctionalExecutionDiagnostic | None,
    functional_context: FunctionalGoalVerificationContext | None = None,
) -> PlannerRetryIssue | None:
    """Reject final answers that retain non-contractual free symbols."""
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

    step_positions = (
        {
            current.step_id: index
            for index, current in enumerate(draft.steps)
        }
        if draft is not None
        else {
            call_id: index
            for index, call_id in enumerate(
                functional_context.logical_graph.canonical_order
                if functional_context is not None
                and functional_context.logical_graph is not None
                else ()
            )
        }
    )
    answer_position = step_positions.get(step.step_id)
    if answer_position is None:
        return None

    allowed_symbols = set(
        _allowed_answer_free_symbols(goal, problem_payload=problem_payload)
    )
    unresolved_symbols = tuple(
        name
        for name in answer_write.free_symbol_names
        if name not in allowed_symbols
    )
    if not unresolved_symbols:
        return None
    symbol_states = _unresolved_symbol_states(
        unresolved_symbols,
        provenance=diagnostic.state_write_provenance,
    )
    expected_object_refs = {
        runtime_symbol: {
            str(item["object_ref"])
            for item in symbol_states
            if item["runtime_symbol"] == runtime_symbol
            and item.get("object_ref")
        }
        for runtime_symbol in unresolved_symbols
    }
    if functional_context is not None:
        expected_object_ids = {
            runtime_symbol: set(
                _typed_runtime_symbol_object_ids(
                    runtime_symbol,
                    answer_write=answer_write,
                    goal_handle=goal_handle,
                    functional_context=functional_context,
                    provenance=diagnostic.state_write_provenance,
                )
            )
            for runtime_symbol in unresolved_symbols
        }
    else:
        object_registry = MathObjectRegistry.from_sources(handle_registry)
        expected_object_ids = {
            runtime_symbol: {
                object_id
                for object_id in (
                    object_registry.resolve(runtime_symbol),
                    *(
                        object_registry.resolve(ref)
                        for ref in expected_object_refs[runtime_symbol]
                    ),
                )
                if object_id is not None
            }
            for runtime_symbol in unresolved_symbols
        }
    if functional_context is not None:
        missing_symbol_identities = tuple(
            runtime_symbol
            for runtime_symbol in unresolved_symbols
            if not expected_object_ids[runtime_symbol]
        )
        if missing_symbol_identities:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.state_identity_incomplete: "
                "unresolved_symbols="
                f"{','.join(missing_symbol_identities)}"
            )
    free_symbols = set(unresolved_symbols)
    available: list[tuple[str, str, str]] = []
    incompatible: list[dict[str, str]] = []
    for item in diagnostic.state_write_provenance:
        if item.runtime_type != "ParameterValue":
            continue
        if functional_context is not None:
            if item.math_object_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.state_identity_incomplete: "
                    f"parameter={item.produced_handle}"
                )
            symbol_name = (
                _symbol_name_from_object_ref(item.object_ref)
                or item.math_object_id.value
            )
        else:
            symbol_name = _symbol_name_from_object_ref(item.object_ref)
            if symbol_name is None:
                continue
        producer_position = step_positions.get(item.step_id)
        if producer_position is None or producer_position >= answer_position:
            continue
        if functional_context is not None:
            if item.selected_version_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"parameter={item.produced_handle}"
                )
            parameter_state = (
                functional_context.state_read_index.version(
                    item.selected_version_id
                )
            )
            if parameter_state is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"parameter={item.produced_handle}"
                )
            if not functional_context.state_read_index.visibility.is_visible(
                parameter_state.valid_scope_id,
                consumer_scope_id=step.scope_id,
            ):
                continue
            functional_context.state_read_index.require_version(
                item.selected_version_id,
                consumer_scope_id=step.scope_id,
                consumer=f"goal_symbol:{step.step_id}",
            )
        elif not _provenance_write_is_visible(
            item.produced_handle,
            producer_scope_id=item.scope_id,
            consumer_scope_id=step.scope_id,
            handle_registry=handle_registry,
        ):
            continue
        matching_runtime_symbols = tuple(
            runtime_symbol
            for runtime_symbol in unresolved_symbols
            if (
                item.math_object_id in expected_object_ids[runtime_symbol]
                if functional_context is not None
                else (
                    item.object_ref in expected_object_refs[runtime_symbol]
                    if expected_object_refs[runtime_symbol]
                    else symbol_name == runtime_symbol
                )
            )
        )
        if matching_runtime_symbols:
            available.extend(
                (
                    runtime_symbol,
                    item.produced_handle,
                    item.object_ref or "",
                )
                for runtime_symbol in matching_runtime_symbols
            )
            continue
        if item.produced_handle in answer_write.source_handles:
            incompatible.append(
                {
                    "parameter": symbol_name,
                    "state": item.produced_handle,
                    "object_ref": item.object_ref or "",
                    "reason": "symbol_identity_mismatch",
                }
            )

    available_symbols = unique_ordered(item[0] for item in available)
    available_handles = unique_ordered(item[1] for item in available)
    symbol_refs = unique_ordered(item[2] for item in available if item[2])
    unresolved_descriptions = unique_ordered(
        str(item["description"]) for item in symbol_states
    )
    unresolved_display = (
        "、".join(unresolved_descriptions)
        if unresolved_descriptions
        else "、".join(unresolved_symbols)
    )
    incompatible_parameters = unique_ordered(
        item["parameter"] for item in incompatible
    )
    identity_hints = (
        (
            f"当前传入的参数值 {'、'.join(incompatible_parameters)} "
            f"与 {unresolved_display} 的 Symbol identity 不同；"
            "不能因为它是唯一可见参数值就强行代入。"
        ),
    ) if incompatible_parameters else ()
    return PlannerRetryIssue(
        layer="goal_verification",
        code="answer_unresolved_symbol_state",
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target=goal_handle or step.target,
        message=(
            f"{step.step_id} 写入的最终答案仍含 {unresolved_display}。"
            + (
                "前序步骤已经产生同一 Symbol identity 的 ParameterValue。"
                if available
                else (
                    "当前消费的参数值 "
                    f"{'、'.join(incompatible_parameters)} 属于其他 Symbol，"
                    "不能闭合该状态。"
                    if incompatible_parameters
                    else "当前没有可见的同身份 ParameterValue 能闭合该状态。"
                )
            )
        ),
        hints=(
            (
                "最终 answer 不应直接绑定仍含自由参数的中间状态；"
                "请让 answer producer 消费已存在的参数值状态。"
                if available
                else "最终 answer 仍含未确定参数；请先由题设条件确定该参数，"
                "再让 answer producer 消费其值状态。"
            ),
            *identity_hints,
            "函数类答案只允许保留 ProblemIR 明确声明的函数自变量，"
            "不能保留未定系数或动态参数。",
        ),
        related_handles=unique_ordered(
            (goal_handle, *symbol_refs, *available_handles)
        ),
        details={
            "unresolved_symbols": list(unresolved_symbols),
            "allowed_free_symbols": sorted(allowed_symbols),
            "available_parameter_symbols": list(available_symbols),
            "available_parameter_states": list(available_handles),
            **(
                {"unresolved_symbol_states": symbol_states}
                if symbol_states
                else {}
            ),
            **(
                {"incompatible_parameter_states": incompatible}
                if incompatible
                else {}
            ),
        },
    )


def _typed_runtime_symbol_object_ids(
    runtime_symbol: str,
    *,
    answer_write: Any,
    goal_handle: str,
    functional_context: FunctionalGoalVerificationContext,
    provenance: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Resolve one runtime Symbol to the answer version's typed Symbol set."""

    root_version = (
        answer_write.selected_version_id
        or functional_context.answer_version_ids.get(goal_handle)
    )
    if root_version is None:
        return ()
    reachable_symbol_ids: set[Any] = set()
    visited: set[StateVersionId] = set()
    pending = [root_version]
    while pending:
        version_id = pending.pop()
        if version_id in visited:
            continue
        binding = functional_context.state_read_index.version(version_id)
        if binding is None:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_version_unresolved: "
                f"version={version_id.to_payload()}, "
                f"runtime_symbol={runtime_symbol}"
            )
        visited.add(version_id)
        reachable_symbol_ids.update(binding.free_symbol_ids)
        if binding.math_object_id.kind == "symbol":
            reachable_symbol_ids.add(binding.math_object_id)
        if binding.previous_version_id is not None:
            pending.append(binding.previous_version_id)
        pending.extend(binding.source_version_ids)
    if answer_write.free_symbol_names and not answer_write.free_symbol_ids:
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.runtime_symbol_identity_unresolved: "
            f"version={root_version.to_payload()}, "
            f"runtime_symbol={runtime_symbol}"
        )
    if answer_write.free_symbol_ids:
        matching = reachable_symbol_ids.intersection(
            answer_write.free_symbol_ids
        )
        return tuple(sorted(matching))
    if len(reachable_symbol_ids) == 1:
        return tuple(reachable_symbol_ids)
    registry = MathObjectRegistry.from_sources(
        functional_context.state_read_index.handle_registry
    )
    runtime_object_id = registry.resolve(runtime_symbol)
    if (
        runtime_object_id is None
        or runtime_object_id.kind != "symbol"
        or runtime_object_id not in reachable_symbol_ids
    ):
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.runtime_symbol_identity_unresolved: "
            f"runtime_symbol={runtime_symbol}"
        )
    return (runtime_object_id,)


def _parameter_goal_constraint_issue(
    goal: Mapping[str, Any],
    *,
    step: FunctionalGoalProducer,
    problem_payload: Mapping[str, Any],
    handle_registry: CanonicalHandleRegistry,
    diagnostic: FunctionalExecutionDiagnostic | None,
) -> PlannerRetryIssue | None:
    """Reject a closed Symbol answer that violates a structured range fact."""

    if diagnostic is None:
        return None
    symbol_name = str(goal.get("answer_key", "")).strip()
    if not symbol_name:
        target_handle = str(goal.get("target_handle", "")).strip()
        symbol_name = _symbol_name_from_object_ref(target_handle) or ""
    if not symbol_name:
        return None

    constraints = tuple(
        item
        for item in problem_payload.get("facts", ())
        if isinstance(item, Mapping)
        and item.get("type") == "symbol_constraint"
        and _constraint_subject_name(item) == symbol_name
        and _constraint_visible_to_scope(
            item,
            scope_id=step.scope_id,
            handle_registry=handle_registry,
        )
    )
    if not constraints:
        return None

    goal_handle = str(goal.get("handle", "")).strip()
    runtime_result = next(
        (
            item
            for item in reversed(diagnostic.runtime_results)
            if item.step_id == step.step_id
            and item.runtime_type == "ParameterValue"
            and (
                item.produced_handle == goal_handle
                or item.produced_handle == step.target
            )
        ),
        None,
    )
    if runtime_result is None or runtime_result.value is None:
        return None
    try:
        value = sp.sympify(runtime_result.value)
    except (TypeError, ValueError, sp.SympifyError):
        return None
    if value.free_symbols:
        return None

    violated = tuple(
        constraint
        for constraint in constraints
        if _symbol_constraint_truth(value, constraint) is False
    )
    if not violated:
        return None

    descriptions = unique_ordered(
        str(item.get("description", "")).strip()
        or (
            f"{symbol_name} {item.get('operator', '')} "
            f"{item.get('value', '')}"
        ).strip()
        for item in violated
    )
    constraint_refs = unique_ordered(
        str(item.get("handle") or item.get("semantic_ref") or "").strip()
        for item in violated
        if str(item.get("handle") or item.get("semantic_ref") or "").strip()
    )
    return PlannerRetryIssue(
        layer="goal_verification",
        code="answer_symbol_constraint_violated",
        step_id=step.step_id,
        scope_id=step.scope_id,
        repair_target=goal_handle or step.target,
        message=(
            f"{step.step_id} produced {symbol_name}={sp.sstr(value)}, which "
            "violates the structured condition "
            f"{'、'.join(descriptions)}."
        ),
        hints=(
            "多分支方程必须使用题面中同一 Symbol 的范围条件筛选；"
            "不能接受仅满足等式但违反范围条件的分支。",
            "若先求另一个系数，请沿已建立的系数关系把目标系数条件"
            "传递到候选分支，再重新计算最终 ParameterValue。",
        ),
        related_handles=unique_ordered(
            (goal_handle, *constraint_refs)
        ),
        details={
            "symbol": symbol_name,
            "actual_value": sp.sstr(value),
            "violated_constraints": [
                {
                    "semantic_ref": item.get("semantic_ref")
                    or item.get("handle"),
                    "operator": item.get("operator"),
                    "value": item.get("value"),
                    "description": item.get("description"),
                }
                for item in violated
            ],
        },
    )


def _constraint_subject_name(constraint: Mapping[str, Any]) -> str:
    subject = str(constraint.get("subject", "")).strip()
    return _symbol_name_from_object_ref(subject) or subject


def _constraint_visible_to_scope(
    constraint: Mapping[str, Any],
    *,
    scope_id: str,
    handle_registry: CanonicalHandleRegistry,
) -> bool:
    valid_scope = str(
        constraint.get("valid_scope")
        or constraint.get("scope_id")
        or "problem"
    )
    try:
        return valid_scope in handle_registry.ancestor_scopes(scope_id)
    except Exception:
        return False


def _symbol_constraint_truth(
    value: sp.Expr,
    constraint: Mapping[str, Any],
) -> bool | None:
    try:
        boundary = sp.sympify(constraint.get("value"))
    except (TypeError, ValueError, sp.SympifyError):
        return None
    operator = str(constraint.get("operator", "")).strip()
    relations = {
        ">": sp.Gt,
        ">=": sp.Ge,
        "≥": sp.Ge,
        "<": sp.Lt,
        "<=": sp.Le,
        "≤": sp.Le,
        "=": sp.Eq,
        "==": sp.Eq,
        "!=": sp.Ne,
        "≠": sp.Ne,
    }
    relation = relations.get(operator)
    if relation is None:
        return None
    result = sp.simplify(relation(value, boundary))
    if result is sp.true:
        return True
    if result is sp.false:
        return False
    return None


def _unresolved_symbol_states(
    runtime_symbols: tuple[str, ...],
    *,
    provenance: tuple[Any, ...],
) -> list[dict[str, str]]:
    """Project runtime symbols through companion-state semantic identity."""
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for runtime_symbol in runtime_symbols:
        for item in provenance:
            if (
                item.runtime_type != "Symbol"
                or runtime_symbol not in item.free_symbol_names
                or item.identity_role != "axis_parameter"
            ):
                continue
            object_ref = (
                item.object_ref
                if _symbol_name_from_object_ref(item.object_ref) is not None
                else None
            )
            source_point = next(
                (
                    handle
                    for handle in item.source_handles
                    if handle.startswith("point:")
                ),
                None,
            )
            key = (runtime_symbol, object_ref or "")
            if key in seen:
                continue
            seen.add(key)
            point_name = (
                source_point.rsplit(":", 1)[-1]
                if source_point is not None
                else ""
            )
            description = (
                f"点 {point_name} 的未定坐标参数"
                if point_name
                else "目标点的未定坐标参数"
            )
            state = {
                "runtime_symbol": runtime_symbol,
                "semantic_role": item.identity_role,
                "description": description,
            }
            if object_ref is not None:
                state["object_ref"] = object_ref
                state["semantic_ref"] = object_ref.rsplit(":", 1)[-1]
            if source_point is not None:
                state["source_object_ref"] = source_point
            result.append(state)
    return result


def _allowed_answer_free_symbols(
    goal: Mapping[str, Any],
    *,
    problem_payload: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return ProblemIR-declared independent variables allowed by the goal."""
    if str(goal.get("value_type", "")).strip() not in {
        "Expression",
        "Equation",
        "Function",
        "Parabola",
    }:
        return ()
    entities = problem_payload.get("entities")
    if not isinstance(entities, list):
        return ()
    return unique_ordered(
        str(item.get("name") or str(item.get("handle", "")).rsplit(":", 1)[-1])
        for item in entities
        if isinstance(item, Mapping)
        and item.get("entity_type") == "symbol"
        and item.get("role") == "function_variable"
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


def _point_goal_issue(
    goal: Mapping[str, Any],
    *,
    step: FunctionalGoalProducer,
    handle_registry: CanonicalHandleRegistry,
    diagnostic: FunctionalExecutionDiagnostic | None,
    family_spec: SolverFamilySpec | None,
    functional_context: FunctionalGoalVerificationContext | None = None,
) -> PlannerRetryIssue | None:
    target_handle = str(goal.get("target_handle", "")).strip()
    if not target_handle:
        return None
    if diagnostic is not None:
        answer_provenance = next(
            (
                item
                for item in reversed(diagnostic.state_write_provenance)
                if item.produced_handle == str(goal.get("handle", ""))
            ),
            None,
        )
        if answer_provenance is None:
            if functional_context is not None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"answer={goal.get('handle')}"
                )
            return _point_provenance_issue(
                goal,
                step=step,
                target_handle=target_handle,
                actual_object_ref=None,
                source_step_id=None,
                source_handles=(),
                handle_registry=handle_registry,
            )
        provenance = _canonical_state_provenance(
            answer_provenance,
            diagnostic=diagnostic,
            functional_context=functional_context,
        )
        identity_matches = provenance.object_ref == target_handle
        if functional_context is not None:
            answer_handle = str(goal.get("handle", ""))
            answer_version_id = (
                functional_context.answer_version_ids.get(answer_handle)
            )
            if answer_version_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"answer={answer_handle}"
                )
            if (
                provenance.selected_version_id is not None
                and provenance.selected_version_id != answer_version_id
            ):
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_binding_drift: "
                    f"answer={answer_handle}, reason=version_mismatch"
                )
            if (
                answer_version_id
                not in functional_context.runtime_writes_by_version
            ):
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"answer={answer_handle}, reason=not_runtime_written"
                )
            target_object_id = MathObjectRegistry.from_sources(
                handle_registry
            ).resolve(target_handle)
            if target_object_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.state_identity_incomplete: "
                    f"goal_target={target_handle}"
                )
            answer_state = functional_context.state_read_index.require_version(
                answer_version_id,
                consumer_scope_id=step.scope_id,
                consumer=f"goal:{goal.get('handle')}",
            )
            identity_matches = (
                answer_state.math_object_id == target_object_id
            )
            if functional_context.logical_graph is not None:
                logical_bindings = tuple(
                    item
                    for item in functional_context.logical_graph.answer_bindings
                    if item.answer_handle == answer_handle
                )
                if len(logical_bindings) != 1:
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: "
                        "planner.state_identity_incomplete: "
                        f"answer={answer_handle}, "
                        f"binding_count={len(logical_bindings)}"
                    )
                identity_matches = (
                    identity_matches
                    and logical_bindings[0].math_object_id
                    == target_object_id
                )
        if not identity_matches:
            return _point_provenance_issue(
                goal,
                step=step,
                target_handle=target_handle,
                actual_object_ref=provenance.object_ref,
                source_step_id=provenance.source_step_id,
                source_handles=provenance.source_handles,
                handle_registry=handle_registry,
            )
        required_evidence_tags = _goal_required_evidence_tags(
            goal,
            step=step,
            family_spec=family_spec,
        )
        lineage = (
            (provenance,)
            if provenance is not answer_provenance
            else _state_write_lineage(
                provenance,
                diagnostic=diagnostic,
                functional_context=functional_context,
                consumer_scope_id=step.scope_id,
            )
        )
        actual_evidence_tags = {
            tag
            for item in lineage
            for tag in (
                *item.evidence_roles,
                *item.lineage.evidence_tags,
            )
        }
        required_evidence_roles = {
            tag: _goal_evidence_roles(family_spec, tag)
            if family_spec is not None
            else ()
            for tag in required_evidence_tags
        }
        required_evidence_goal_types = {
            tag: _goal_evidence_producer_goal_types(
                family_spec,
                tag,
            )
            if family_spec is not None
            else ()
            for tag in required_evidence_tags
        }
        missing_evidence_tags = tuple(
            tag
            for tag in required_evidence_tags
            if tag not in actual_evidence_tags
            and step.goal_type not in required_evidence_goal_types[tag]
            and not (
                set(required_evidence_roles[tag])
                & actual_evidence_tags
            )
        )
        if missing_evidence_tags:
            return PlannerRetryIssue(
                layer="goal_verification",
                code="point_goal_evidence_unproven",
                step_id=step.step_id,
                scope_id=step.scope_id,
                repair_target=str(goal.get("handle") or step.target),
                message=(
                    f"{step.step_id} writes the correct Point object, but its "
                    "producer does not prove the evidence required by the "
                    f"question goal: {', '.join(missing_evidence_tags)}."
                ),
                hints=(
                    "最终点不仅要有正确对象身份，还必须由题目目标要求的完整"
                    "几何证据链推出；不要用部分端点或无关直线拼出一个可执行交点。",
                ),
                related_handles=unique_ordered(
                    (
                        target_handle,
                        *provenance.source_handles,
                    )
                ),
                details={
                    "required_evidence_tags": list(required_evidence_tags),
                    "required_evidence_roles": {
                        tag: list(roles)
                        for tag, roles in required_evidence_roles.items()
                    },
                    "required_evidence_goal_types": {
                        tag: list(goal_types)
                        for tag, goal_types in (
                            required_evidence_goal_types.items()
                        )
                    },
                    "actual_evidence_tags": sorted(actual_evidence_tags),
                },
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
    step: FunctionalGoalProducer,
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


def _canonical_state_provenance(
    provenance: StateWriteProvenance,
    *,
    diagnostic: FunctionalExecutionDiagnostic,
    functional_context: FunctionalGoalVerificationContext | None = None,
) -> StateWriteProvenance:
    """Prefer the full state write over its answer alias projection."""
    if functional_context is not None:
        version_id = (
            provenance.selected_version_id
            or functional_context.answer_version_ids.get(
                provenance.produced_handle
            )
        )
        if version_id is None:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_version_unresolved: "
                f"write={provenance.produced_handle}"
            )
        canonical = functional_context.runtime_writes_by_version.get(
            version_id
        )
        if canonical is None:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                "planner.runtime_state_version_unresolved: "
                f"version={version_id.to_payload()}, reason=no_runtime_write"
            )
        return canonical
    if provenance.state_slot_id is None:
        return provenance
    candidates = tuple(
        item
        for item in diagnostic.state_write_provenance
        if item.step_id == provenance.step_id
        and item.state_slot_id == provenance.state_slot_id
        and not item.produced_handle.startswith("answer:")
    )
    return candidates[-1] if candidates else provenance


def _goal_required_evidence_tags(
    goal: Mapping[str, Any],
    *,
    step: FunctionalGoalProducer,
    family_spec: SolverFamilySpec | None,
) -> tuple[str, ...]:
    raw = goal.get("required_evidence_tags", ())
    explicit = (
        tuple(
            item.strip()
            for item in raw
            if isinstance(item, str) and item.strip()
        )
        if isinstance(raw, (list, tuple))
        else ()
    )
    policies = (
        family_spec.goal_evidence_policies
        if family_spec is not None
        else ()
    )
    selected_packs = (
        {
            *family_spec.base_packs,
            *family_spec.mechanism_packs,
        }
        if family_spec is not None
        else set()
    )
    inferred = tuple(
        tag
        for policy in policies
        if (not policy.goal_types or step.goal_type in policy.goal_types)
        and (
            not policy.value_types
            or str(goal.get("value_type") or "") in policy.value_types
        )
        and (
            policy.mechanism_pack_id is None
            or policy.mechanism_pack_id in selected_packs
        )
        for tag in policy.required_evidence_tags
    )
    return unique_ordered((*explicit, *inferred))


def _goal_evidence_producer_goal_types(
    family_spec: SolverFamilySpec,
    tag: str,
) -> tuple[str, ...]:
    return unique_ordered(
        goal_type
        for policy in family_spec.goal_evidence_policies
        if tag in policy.required_evidence_tags
        for goal_type in policy.producer_goal_types
    )


def _minimum_goal_issue(
    goal: Mapping[str, Any],
    *,
    step: FunctionalGoalProducer,
    handle_registry: CanonicalHandleRegistry,
    diagnostic: FunctionalExecutionDiagnostic | None,
    family_spec: SolverFamilySpec | None,
    functional_context: FunctionalGoalVerificationContext | None = None,
) -> PlannerRetryIssue | None:
    if diagnostic is None or family_spec is None:
        return None
    expression_roles = _goal_evidence_roles(
        family_spec,
        "path_minimum_expression",
    )
    witness_roles = _goal_evidence_roles(
        family_spec,
        "verified_path_minimum_subplan",
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
        if (
            functional_context is not None
            and (
                answer_write.selected_version_id is not None
                or answer_write.produced_handle
                in functional_context.answer_version_ids
            )
        ):
            answer_write = _canonical_state_provenance(
                answer_write,
                diagnostic=diagnostic,
                functional_context=functional_context,
            )
        lineage = _state_write_lineage(
            answer_write,
            diagnostic=diagnostic,
            functional_context=(
                functional_context
                if answer_write.selected_version_id is not None
                else None
            ),
            consumer_scope_id=step.scope_id,
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
    diagnostic: FunctionalExecutionDiagnostic,
    functional_context: FunctionalGoalVerificationContext | None = None,
    consumer_scope_id: str | None = None,
) -> tuple[Any, ...]:
    """Return the provenance subgraph that actually contributes to ``root``."""
    if functional_context is not None:
        by_version = {
            item.selected_version_id: item
            for item in diagnostic.state_write_provenance
            if item.selected_version_id is not None
        }
        result: list[Any] = []
        seen: set[StateVersionId] = set()
        pending = [root]
        while pending:
            item = pending.pop()
            version_id = item.selected_version_id
            if version_id is None:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"write={item.produced_handle}"
                )
            if version_id in seen:
                continue
            seen.add(version_id)
            result.append(item)
            binding = functional_context.state_read_index.require_version(
                version_id,
                consumer_scope_id=(
                    consumer_scope_id or item.scope_id
                ),
                consumer=f"goal_lineage:{item.step_id}",
            )
            source_versions = (
                *binding.source_version_ids,
                *(
                    (binding.previous_version_id,)
                    if binding.previous_version_id is not None
                    else ()
                ),
            )
            for source_version in source_versions:
                producer = by_version.get(source_version)
                if producer is not None:
                    pending.append(producer)
                    continue
                if (
                    functional_context.state_read_index.version(
                        source_version
                    )
                    is None
                ):
                    raise StrategyDraftValidationError(
                        "planner_configuration_error: "
                        "planner.runtime_state_version_unresolved: "
                        f"source={source_version.to_payload()}"
                    )
        return tuple(result)
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
    step: FunctionalGoalProducer,
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
    diagnostic: FunctionalExecutionDiagnostic,
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


def _step_mentions_handle(
    step: FunctionalGoalProducer,
    handle: str,
) -> bool:
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
