"""Prompt-safe memory for validated and executed FunctionalPlan calls."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.runtime.answer_goal_verifier import (
    AnswerGoalVerificationReport,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalPlanReconciliationResult,
    FunctionalReturnAllocation,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StateWriteProvenance,
    StepIntentRuntimeResult,
)
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalCallExecutionStatus = Literal[
    "validated",
    "runtime_verified",
]
FunctionalCallCommitStatus = Literal[
    "provisional",
    "goal_committed",
]


@dataclass(frozen=True)
class FunctionalResultSnapshot:
    return_name: str
    value_type: str
    semantic_ref: str | None
    value: Any | None = None
    actual_form: str | None = None
    free_parameters: tuple[str, ...] = ()
    semantic_roles: tuple[str, ...] = ()
    object_roles: dict[str, tuple[str, ...]] | None = None
    valid_scope: str | None = None
    value_omitted_reason: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "return": self.return_name,
            "type": self.value_type,
        }
        if self.semantic_ref is not None:
            payload["semantic_ref"] = self.semantic_ref
        if self.value is not None:
            payload["value"] = self.value
        if self.actual_form is not None:
            payload["actual_form"] = self.actual_form
        if self.free_parameters:
            payload["free_parameters"] = list(self.free_parameters)
        if self.semantic_roles:
            payload["semantic_roles"] = list(self.semantic_roles)
        if self.object_roles:
            payload["object_roles"] = {
                role: list(refs)
                for role, refs in self.object_roles.items()
            }
        if self.valid_scope is not None:
            payload["valid_scope"] = self.valid_scope
        if self.value_omitted_reason is not None:
            payload["value_omitted_reason"] = self.value_omitted_reason
        return payload


@dataclass(frozen=True)
class FunctionalCallMemoryEntry:
    call_id: str
    capability_id: str
    scope_id: str
    execution_status: FunctionalCallExecutionStatus
    commit_status: FunctionalCallCommitStatus = "provisional"
    repair_required: bool = False
    result_snapshots: tuple[FunctionalResultSnapshot, ...] = ()
    committed_goal_handles: tuple[str, ...] = ()
    source_attempt: int = 0

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "call_id": self.call_id,
            "capability_id": self.capability_id,
            "scope_id": self.scope_id,
            "execution_status": self.execution_status,
            "commit_status": self.commit_status,
            "repair_required": self.repair_required,
            "source_attempt": self.source_attempt,
        }
        if self.result_snapshots:
            payload["results"] = [
                item.to_payload() for item in self.result_snapshots
            ]
        if self.committed_goal_handles:
            payload["committed_goals"] = list(self.committed_goal_handles)
        return payload


@dataclass(frozen=True)
class FunctionalCallMemory:
    entries: tuple[FunctionalCallMemoryEntry, ...] = ()
    committed_call_ids: tuple[str, ...] = ()
    runtime_verified_call_ids: tuple[str, ...] = ()
    validated_call_ids: tuple[str, ...] = ()

    def to_payload(self) -> list[dict[str, Any]]:
        return [item.to_payload() for item in self.entries]


def build_functional_call_memory(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
    runtime_verified_call_ids: Sequence[str],
    runtime_results: Sequence[StepIntentRuntimeResult],
    provenance: Sequence[StateWriteProvenance],
    goal_report: AnswerGoalVerificationReport | None,
    active_issues: Sequence[PlannerRetryIssue],
    attempt: int,
    allow_goal_commit: bool = True,
) -> FunctionalCallMemory:
    """Classify calls and project only their declared Functional returns."""
    repair_cone = _active_repair_cone(
        reconciliation,
        active_issues=active_issues,
    )
    commit_blockers = _active_issue_call_cone(
        reconciliation,
        active_issues=active_issues,
    )
    verified = set(runtime_verified_call_ids)
    committed_goals = (
        _committed_goals_by_call(
            reconciliation,
            goal_report=goal_report,
            verified_call_ids=verified,
            invalid_call_ids=commit_blockers,
        )
        if allow_goal_commit
        else {}
    )
    committed = set(committed_goals)
    valid = {
        item.call_id
        for item in reconciliation.call_reports
        if item.status == "valid"
    }
    runtime_by_step_handle = {
        (item.step_id, item.produced_handle): item
        for item in runtime_results
    }
    provenance_by_step_handle = {
        (item.step_id, item.produced_handle): item
        for item in provenance
    }
    projected_steps_by_call = {
        item.call_id: item.step_ids
        for item in reconciliation.projection_map
    }
    capabilities = catalog.items
    entries: list[FunctionalCallMemoryEntry] = []
    for call in reconciliation.calls:
        if call.call_id not in valid:
            continue
        execution_status: FunctionalCallExecutionStatus = (
            "runtime_verified"
            if call.call_id in verified
            else "validated"
        )
        commit_status: FunctionalCallCommitStatus = (
            "goal_committed"
            if call.call_id in committed
            else "provisional"
        )
        capability = capabilities.get(call.capability_id)
        return_specs = (
            {item.name: item for item in capability.returns}
            if capability is not None
            else {}
        )
        snapshots: list[FunctionalResultSnapshot] = []
        if execution_status == "runtime_verified":
            projected_step_ids = projected_steps_by_call.get(
                call.call_id,
                (call.call_id,),
            )
            for allocation in call.returns:
                produced_handle = allocation.state_handle or allocation.handle
                runtime = _latest_projected_result(
                    projected_step_ids,
                    produced_handle=produced_handle,
                    values=runtime_by_step_handle,
                )
                write = _latest_projected_result(
                    projected_step_ids,
                    produced_handle=produced_handle,
                    values=provenance_by_step_handle,
                )
                snapshots.append(
                    _result_snapshot(
                        allocation,
                        return_spec=return_specs.get(allocation.return_name),
                        runtime=runtime,
                        write=write,
                    )
                )
        entries.append(
            FunctionalCallMemoryEntry(
                call_id=call.call_id,
                capability_id=call.capability_id,
                scope_id=call.scope_id,
                execution_status=execution_status,
                commit_status=commit_status,
                repair_required=call.call_id in repair_cone,
                result_snapshots=tuple(snapshots),
                committed_goal_handles=committed_goals.get(call.call_id, ()),
                source_attempt=attempt,
            )
        )
    return FunctionalCallMemory(
        entries=tuple(entries),
        committed_call_ids=tuple(
            call.call_id
            for call in reconciliation.plan.calls
            if call.call_id in committed
        ),
        runtime_verified_call_ids=tuple(
            call.call_id
            for call in reconciliation.plan.calls
            if call.call_id in verified and call.call_id not in committed
        ),
        validated_call_ids=tuple(
            call.call_id
            for call in reconciliation.plan.calls
            if call.call_id in valid and call.call_id not in verified
        ),
    )


def attach_actual_result_refs(
    issues: Sequence[PlannerRetryIssue],
    *,
    memory: FunctionalCallMemory,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> tuple[PlannerRetryIssue, ...]:
    """Link repair tickets to successful results without copying values."""
    all_executed = {
        item.call_id: item
        for item in memory.entries
        if (
            item.execution_status == "runtime_verified"
            and any(
                snapshot.value_omitted_reason != "runtime_value_unavailable"
                for snapshot in item.result_snapshots
            )
        )
    }
    provisional = {
        call_id: item
        for call_id, item in all_executed.items()
        if item.commit_status == "provisional"
    }
    committed = {
        call_id: item
        for call_id, item in all_executed.items()
        if item.commit_status == "goal_committed"
    }
    result: list[PlannerRetryIssue] = []
    for issue in issues:
        if issue.step_id is None:
            result.append(issue)
            continue
        relevant_calls = _dependency_closure(
            issue.step_id,
            dependency_graph,
        )
        selected_calls = {
            call_id
            for call_id in relevant_calls
            for entry in (provisional.get(call_id),)
            if entry is not None and entry.repair_required
        }
        selected_calls.update(
            _nearest_executed_dependencies(
                issue.step_id,
                dependency_graph=dependency_graph,
                executed_call_ids=set(provisional),
            )
        )
        if issue.step_id in provisional:
            selected_calls.add(issue.step_id)
        locked_context_calls = _nearest_executed_dependencies(
            issue.step_id,
            dependency_graph=dependency_graph,
            executed_call_ids=set(committed),
        )
        refs = tuple(
            unique_ordered(
                f"{entry.call_id}.{snapshot.return_name}"
                for entry in memory.entries
                if entry.call_id in selected_calls
                for snapshot in entry.result_snapshots
                if snapshot.value_omitted_reason != "runtime_value_unavailable"
            )
        )
        locked_refs = tuple(
            unique_ordered(
                f"{entry.call_id}.{snapshot.return_name}"
                for entry in memory.entries
                if entry.call_id in locked_context_calls
                for snapshot in entry.result_snapshots
                if snapshot.value_omitted_reason != "runtime_value_unavailable"
            )
        )
        if not refs and not locked_refs:
            result.append(issue)
            continue
        details = dict(issue.details or {})
        if refs:
            details["actual_result_refs"] = list(refs)
        if locked_refs:
            details["locked_result_refs"] = list(locked_refs)
            details["locked_context_call_ids"] = list(
                unique_ordered(
                    ref.rsplit(".", 1)[0] for ref in locked_refs
                )
            )
        result.append(replace(issue, details=details))
    return tuple(result)


def _nearest_executed_dependencies(
    call_id: str,
    *,
    dependency_graph: Mapping[str, tuple[str, ...]],
    executed_call_ids: set[str],
) -> set[str]:
    """Find the closest successful producers feeding a failed repair call."""
    result: set[str] = set()
    pending = list(dependency_graph.get(call_id, ()))
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        if current in executed_call_ids:
            result.add(current)
            continue
        pending.extend(dependency_graph.get(current, ()))
    return result


def _latest_projected_result(
    step_ids: Sequence[str],
    *,
    produced_handle: str,
    values: Mapping[tuple[str, str], Any],
) -> Any | None:
    """Read the latest version written by this call, never a later transition."""
    return next(
        (
            values[(step_id, produced_handle)]
            for step_id in reversed(tuple(step_ids))
            if (step_id, produced_handle) in values
        ),
        None,
    )


def _result_snapshot(
    allocation: FunctionalReturnAllocation,
    *,
    return_spec: Any | None,
    runtime: StepIntentRuntimeResult | None,
    write: StateWriteProvenance | None,
) -> FunctionalResultSnapshot:
    free_symbols = tuple(
        unique_ordered(
            write.free_symbol_names
            if write is not None
            else (
                item.rsplit(":", 1)[-1]
                for item in allocation.free_symbol_refs
            )
        )
    )
    possible_forms = tuple(
        getattr(return_spec, "possible_forms", ()) or ()
    )
    actual_form = _actual_form(possible_forms, free_symbols)
    lineage = write.lineage if write is not None else allocation.lineage
    semantic_roles = unique_ordered(
        (
            *allocation.provides_semantic_roles,
            *lineage.semantic_roles,
            *lineage.evidence_tags,
        )
    )
    object_roles = {
        item.role: tuple(
            _short_semantic_ref(ref) for ref in item.object_refs
        )
        for item in lineage.object_roles
        if item.object_refs
    }
    return FunctionalResultSnapshot(
        return_name=allocation.return_name,
        value_type=allocation.runtime_type,
        semantic_ref=_allocation_semantic_ref(allocation),
        value=runtime.value if runtime is not None else None,
        actual_form=actual_form,
        free_parameters=tuple(_short_semantic_ref(item) for item in free_symbols),
        semantic_roles=tuple(semantic_roles),
        object_roles=object_roles or None,
        valid_scope=allocation.valid_scope,
        value_omitted_reason=(
            runtime.value_omitted_reason
            if runtime is not None
            else "runtime_value_unavailable"
        ),
    )


def _actual_form(
    possible_forms: Sequence[str],
    free_symbols: Sequence[str],
) -> str | None:
    forms = set(possible_forms)
    if {"open_state", "closed_state"} <= forms:
        return "open_state" if free_symbols else "closed_state"
    if {"open_expression", "closed_value"} <= forms:
        return "open_expression" if free_symbols else "closed_value"
    return None


def _allocation_semantic_ref(
    allocation: FunctionalReturnAllocation,
) -> str | None:
    if allocation.bound_ref is not None:
        return allocation.bound_ref.ref
    if allocation.object_ref is not None:
        return _short_semantic_ref(allocation.object_ref)
    return _short_semantic_ref(allocation.handle)


def _short_semantic_ref(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def _active_repair_cone(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    active_issues: Sequence[PlannerRetryIssue],
) -> set[str]:
    roots = {
        item.step_id
        for item in active_issues
        if item.step_id is not None
    }
    roots.update(
        call_id
        for item in active_issues
        if isinstance(item.details, Mapping)
        for call_id in item.details.get("repair_call_ids", ())
        if isinstance(call_id, str)
    )
    changed = True
    invalid = set(roots)
    while changed:
        changed = False
        for call_id, dependencies in reconciliation.dependency_graph.items():
            if call_id in invalid or not invalid.intersection(dependencies):
                continue
            invalid.add(call_id)
            changed = True
    return invalid


def _active_issue_call_cone(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    active_issues: Sequence[PlannerRetryIssue],
) -> set[str]:
    """Calls proven invalid by an issue, excluding contextual repair inputs.

    ``details.repair_call_ids`` may include an otherwise valid producer merely
    because its result was connected to the failing call. Such a producer can
    remain goal-committed and serve as immutable retry context. Only the call
    carrying the active issue, and calls depending on it, block commitment.
    """

    invalid = {
        item.step_id
        for item in active_issues
        if item.step_id is not None
    }
    changed = True
    while changed:
        changed = False
        for call_id, dependencies in reconciliation.dependency_graph.items():
            if call_id in invalid or not invalid.intersection(dependencies):
                continue
            invalid.add(call_id)
            changed = True
    return invalid


def _committed_goals_by_call(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    goal_report: AnswerGoalVerificationReport | None,
    verified_call_ids: set[str],
    invalid_call_ids: set[str],
) -> dict[str, tuple[str, ...]]:
    if goal_report is None:
        return {}
    step_to_call = {
        step_id: item.call_id
        for item in reconciliation.projection_map
        for step_id in item.step_ids
    }
    goals_by_call: dict[str, list[str]] = {}
    for goal in goal_report.goals:
        if goal.status != "passed" or goal.producer_step_id is None:
            continue
        producer = step_to_call.get(goal.producer_step_id)
        if producer is None:
            continue
        closure = _dependency_closure(
            producer,
            reconciliation.dependency_graph,
        )
        if (
            not closure <= verified_call_ids
            or closure.intersection(invalid_call_ids)
        ):
            continue
        for call_id in closure:
            goals_by_call.setdefault(call_id, []).append(goal.goal_handle)
    return {
        call_id: tuple(unique_ordered(goal_handles))
        for call_id, goal_handles in goals_by_call.items()
    }


def _dependency_closure(
    call_id: str,
    graph: Mapping[str, tuple[str, ...]],
) -> set[str]:
    result: set[str] = set()
    pending = [call_id]
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(graph.get(current, ()))
    return result


__all__ = [
    "FunctionalCallMemory",
    "FunctionalCallCommitStatus",
    "FunctionalCallMemoryEntry",
    "FunctionalCallExecutionStatus",
    "FunctionalResultSnapshot",
    "attach_actual_result_refs",
    "build_functional_call_memory",
]
