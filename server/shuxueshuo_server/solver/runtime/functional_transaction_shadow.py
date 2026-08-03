"""C0 shadow state machine for transactional Functional execution."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    FunctionalCallLifecycleStatus,
    LogicalFunctionalGraph,
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    MathObjectId,
    MathObjectRegistry,
    ScopeVisibilityResolver,
    StateIdentityFactory,
    StateIdentityIndex,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryState,
    StateWriteProvenance,
    FunctionalExecutionDiagnostic,
)
from shuxueshuo_server.solver.runtime.models import TypedValue
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalTransactionMode = Literal[
    "shadow",
    "context_authoritative",
]
FunctionalTransactionEventKind = Literal[
    "became_ready",
    "running",
    "verified",
    "failed",
    "blocked",
    "eliminated",
    "aliased",
    "state_version_committed",
]


@dataclass(frozen=True)
class FunctionalCallExecutionState:
    call_id: str
    status: FunctionalCallLifecycleStatus
    dependency_call_ids: tuple[str, ...]
    return_version_ids: tuple[StateVersionId, ...] = ()
    root_issue_codes: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "status": self.status,
            "dependency_call_ids": list(self.dependency_call_ids),
            "return_version_ids": [
                item.to_payload() for item in self.return_version_ids
            ],
            "root_issue_codes": list(self.root_issue_codes),
        }


@dataclass(frozen=True)
class FunctionalTransactionEvent:
    sequence: int
    call_id: str
    event: FunctionalTransactionEventKind
    version_id: StateVersionId | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "sequence": self.sequence,
            "call_id": self.call_id,
            "event": self.event,
        }
        if self.version_id is not None:
            payload["version_id"] = self.version_id.to_payload()
        return payload


@dataclass
class WorkingPlannerState:
    parent_context_id: str
    identity_index: StateIdentityIndex
    call_states: dict[str, FunctionalCallExecutionState]
    committed_versions: dict[StateVersionId, IndexedStateVersion] = field(
        default_factory=dict
    )
    runtime_version_values: dict[StateVersionId, TypedValue] = field(
        default_factory=dict
    )
    runtime_version_symbol_bindings: dict[
        StateVersionId,
        dict[Any, MathObjectId],
    ] = field(default_factory=dict)
    events: list[FunctionalTransactionEvent] = field(default_factory=list)

    def emit(
        self,
        call_id: str,
        event: FunctionalTransactionEventKind,
        *,
        version_id: StateVersionId | None = None,
    ) -> None:
        self.events.append(
            FunctionalTransactionEvent(
                len(self.events),
                call_id,
                event,
                version_id,
            )
        )

    def set_status(
        self,
        call_id: str,
        status: FunctionalCallLifecycleStatus,
        *,
        issue_codes: tuple[str, ...] = (),
    ) -> None:
        current = self.call_states[call_id]
        self.call_states[call_id] = replace(
            current,
            status=status,
            root_issue_codes=issue_codes,
        )

    def commit_version(
        self,
        call_id: str,
        version: IndexedStateVersion,
    ) -> None:
        self.identity_index.register(version)
        self.committed_versions[version.version_id] = version
        current = self.call_states[call_id]
        self.call_states[call_id] = replace(
            current,
            return_version_ids=unique_ordered(
                (*current.return_version_ids, version.version_id)
            ),
        )
        self.emit(
            call_id,
            "state_version_committed",
            version_id=version.version_id,
        )

    def commit_verified_transaction(
        self,
        call_id: str,
        versions: tuple[IndexedStateVersion, ...],
        runtime_values: dict[StateVersionId, TypedValue],
        runtime_symbol_bindings: Mapping[
            StateVersionId,
            Mapping[Any, MathObjectId],
        ] | None = None,
    ) -> None:
        """Commit call status and every returned version as one state change."""

        missing_values = tuple(
            version.version_id
            for version in versions
            if version.version_id not in runtime_values
        )
        if missing_values:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_runtime_value_missing: "
                f"versions={[item.to_payload() for item in missing_values]}"
            )
        next_index = self.identity_index.clone()
        for version in versions:
            next_index.register(version)
        next_versions = dict(self.committed_versions)
        next_versions.update(
            (version.version_id, version) for version in versions
        )
        next_runtime_values = dict(self.runtime_version_values)
        next_runtime_values.update(runtime_values)
        next_symbol_bindings = dict(self.runtime_version_symbol_bindings)
        next_symbol_bindings.update(
            (version_id, dict(bindings))
            for version_id, bindings in (runtime_symbol_bindings or {}).items()
        )
        current = self.call_states[call_id]
        next_call_state = replace(
            current,
            status="verified",
            return_version_ids=unique_ordered(
                (
                    *current.return_version_ids,
                    *(version.version_id for version in versions),
                )
            ),
        )
        next_events = [
            *self.events,
            FunctionalTransactionEvent(
                len(self.events),
                call_id,
                "verified",
            ),
        ]
        commit_sequence = len(next_events)
        next_events.extend(
            FunctionalTransactionEvent(
                commit_sequence + index,
                call_id,
                "state_version_committed",
                version.version_id,
            )
            for index, version in enumerate(versions)
        )

        self.identity_index = next_index
        self.committed_versions = next_versions
        self.runtime_version_values = next_runtime_values
        self.runtime_version_symbol_bindings = next_symbol_bindings
        self.call_states[call_id] = next_call_state
        self.events = next_events


@dataclass(frozen=True)
class FunctionalTransactionShadowMismatch:
    code: str
    call_id: str | None
    expected: Any
    actual: Any

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "call_id": self.call_id,
            "expected": _payload(self.expected),
            "actual": _payload(self.actual),
        }


@dataclass(frozen=True)
class FunctionalTransactionShadowReport:
    graph: LogicalFunctionalGraph
    call_states: tuple[FunctionalCallExecutionState, ...]
    events: tuple[FunctionalTransactionEvent, ...]
    mismatches: tuple[FunctionalTransactionShadowMismatch, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "graph": self.graph.to_payload(),
            "call_states": [
                item.to_payload() for item in self.call_states
            ],
            "events": [item.to_payload() for item in self.events],
            "mismatches": [
                item.to_payload() for item in self.mismatches
            ],
        }


class FunctionalTransactionShadowObserver:
    """Interpret existing replay evidence without executing any capability."""

    def observe(
        self,
        *,
        raw_plan: FunctionalPlan,
        reconciliation: FunctionalPlanReconciliationResult,
        diagnostic: FunctionalExecutionDiagnostic | None,
        retry_state: PlannerRetryState | None,
        goal_verification_report: Any | None,
        parent_context: PlannerStateContext,
        handle_registry: CanonicalHandleRegistry,
    ) -> FunctionalTransactionShadowReport:
        build = LogicalFunctionalGraphBuilder().build(
            raw_plan,
            reconciliation,
            handle_registry=handle_registry,
        )
        graph = build.graph
        mismatches = [
            FunctionalTransactionShadowMismatch(
                item.code,
                item.call_id,
                "complete typed logical graph",
                item.detail,
            )
            for item in build.issues
        ]
        if diagnostic is not None:
            mismatches.extend(
                FunctionalTransactionShadowMismatch(
                    str(
                        item.get(
                            "code",
                            "runtime_consumer_identity_mismatch",
                        )
                    ),
                    (
                        str(item["call_id"])
                        if item.get("call_id") is not None
                        else None
                    ),
                    item.get("expected", "typed runtime consumer binding"),
                    item.get("actual", item),
                )
                for item in diagnostic.runtime_consumer_mismatches
            )
            if diagnostic.legacy_runtime_identity_fallback_count:
                mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "legacy_runtime_identity_fallback",
                        None,
                        0,
                        diagnostic.legacy_runtime_identity_fallback_count,
                    )
                )
        working = build_working_state(
            graph,
            parent_context=parent_context,
            handle_registry=handle_registry,
        )
        for call_id in graph.alias_call_ids:
            if call_id in working.call_states:
                working.set_status(call_id, "aliased")
                working.emit(call_id, "aliased")
        for call_id in graph.eliminated_call_ids:
            if call_id in working.call_states:
                working.set_status(call_id, "eliminated")
                working.emit(call_id, "eliminated")

        observed = _observed_call_statuses(
            graph,
            reconciliation=reconciliation,
            diagnostic=diagnostic,
            retry_state=retry_state,
        )
        issue_codes = _call_issue_codes(
            reconciliation,
            diagnostic=diagnostic,
        )
        mismatches.extend(
            _unmapped_runtime_write_mismatches(
                reconciliation,
                diagnostic=diagnostic,
            )
        )
        for call_id in graph.canonical_order:
            state = working.call_states[call_id]
            dependency_states = tuple(
                working.call_states[item].status
                for item in state.dependency_call_ids
                if item in working.call_states
            )
            if any(
                status in {"failed", "blocked_by_dependency"}
                for status in dependency_states
            ):
                working.set_status(call_id, "blocked_by_dependency")
                working.emit(call_id, "blocked")
                if observed.get(call_id) == "verified":
                    mismatches.append(
                        FunctionalTransactionShadowMismatch(
                            "dependency_accepted_before_verified",
                            call_id,
                            "blocked_by_dependency",
                            "verified",
                        )
                    )
                continue
            if all(status == "verified" for status in dependency_states):
                working.set_status(call_id, "ready")
                working.emit(call_id, "became_ready")
            observed_status = observed.get(call_id, "pending")
            if observed_status == "verified":
                if working.call_states[call_id].status != "ready":
                    mismatches.append(
                        FunctionalTransactionShadowMismatch(
                            "dependency_accepted_before_verified",
                            call_id,
                            "ready",
                            working.call_states[call_id].status,
                        )
                    )
                    continue
                working.set_status(call_id, "verified")
                working.emit(call_id, "verified")
                commit_mismatches = _commit_observed_writes(
                    working,
                    reconciliation=reconciliation,
                    diagnostic=diagnostic,
                    call_ids=(call_id,),
                )
                mismatches.extend(commit_mismatches)
                if commit_mismatches:
                    working.set_status(
                        call_id,
                        "failed",
                        issue_codes=unique_ordered(
                            item.code for item in commit_mismatches
                        ),
                    )
                    working.emit(call_id, "failed")
            elif observed_status == "failed":
                working.set_status(
                    call_id,
                    "failed",
                    issue_codes=issue_codes.get(call_id, ()),
                )
                working.emit(call_id, "failed")
            elif observed_status == "blocked_by_dependency":
                working.set_status(call_id, "blocked_by_dependency")
                working.emit(call_id, "blocked")

        mismatches.extend(
            _answer_mismatches(
                graph,
                working=working,
                goal_verification_report=goal_verification_report,
                reconciliation=reconciliation,
            )
        )
        return FunctionalTransactionShadowReport(
            graph=graph,
            call_states=tuple(
                working.call_states[call_id]
                for call_id in (
                    *graph.canonical_order,
                    *graph.alias_call_ids,
                    *graph.eliminated_call_ids,
                )
                if call_id in working.call_states
            ),
            events=tuple(working.events),
            mismatches=tuple(mismatches),
        )


def failed_shadow_report(
    _raw_plan: FunctionalPlan,
    *,
    message: str,
) -> FunctionalTransactionShadowReport:
    """Return a non-authoritative report when the observer itself fails."""

    empty = LogicalFunctionalGraph((), (), (), (), (), ())
    return FunctionalTransactionShadowReport(
        graph=empty,
        call_states=(),
        events=(),
        mismatches=(
            FunctionalTransactionShadowMismatch(
                "shadow_observer_failed",
                None,
                "shadow observation succeeds",
                message,
            ),
        ),
    )


def build_working_state(
    graph: LogicalFunctionalGraph,
    *,
    parent_context: PlannerStateContext,
    handle_registry: CanonicalHandleRegistry,
) -> WorkingPlannerState:
    registry = MathObjectRegistry.from_sources(
        handle_registry,
        math_objects=parent_context.state.math_objects,
    )
    identity_index = StateIdentityIndex.from_context(
        state_slots=parent_context.state.state_slots,
        factory=StateIdentityFactory(registry),
        visibility=ScopeVisibilityResolver(handle_registry),
    )
    calls = {
        item.call_id: FunctionalCallExecutionState(
            item.call_id,
            "pending",
            item.dependency_call_ids,
        )
        for item in graph.calls
    }
    calls.update(
        {
            call_id: FunctionalCallExecutionState(call_id, "pending", ())
            for call_id in (
                *graph.alias_call_ids,
                *graph.eliminated_call_ids,
            )
            if call_id not in calls
        }
    )
    return WorkingPlannerState(
        parent_context.manifest.context_id,
        identity_index,
        calls,
    )


def _observed_call_statuses(
    graph: LogicalFunctionalGraph,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: FunctionalExecutionDiagnostic | None,
    retry_state: PlannerRetryState | None,
) -> dict[str, FunctionalCallLifecycleStatus]:
    result: dict[str, FunctionalCallLifecycleStatus] = {}
    projection = {
        item.call_id: (item.call_id,)
        for item in reconciliation.execution_entries
    }
    step_to_call = {
        item.call_id: item.canonical_call_id
        for item in reconciliation.execution_entries
    }
    accepted = {
        item.step_id
        for item in (
            diagnostic.accepted_prefix if diagnostic is not None else ()
        )
    }
    blocked_steps = {
        item.step_id
        for item in (diagnostic.blockers if diagnostic is not None else ())
    }
    skipped_steps = {
        item.step_id
        for item in (
            diagnostic.skipped_steps if diagnostic is not None else ()
        )
    }
    runtime_verified = {
        item.get("call_id")
        for item in (
            retry_state.call_memory if retry_state is not None else ()
        )
        if isinstance(item, Mapping)
        and item.get("execution_status") == "runtime_verified"
    }
    reports = {item.call_id: item for item in reconciliation.call_reports}
    for call_id in graph.canonical_order:
        steps = projection.get(call_id, ())
        report = reports.get(call_id)
        if report is not None and report.status == "invalid":
            result[call_id] = "failed"
        elif report is not None and report.status == "blocked_by_dependency":
            result[call_id] = "blocked_by_dependency"
        elif call_id in runtime_verified:
            result[call_id] = "verified"
        elif steps and all(step_id in accepted for step_id in steps):
            result[call_id] = "verified"
        elif any(step_id in blocked_steps for step_id in steps):
            result[call_id] = "failed"
        elif any(step_id in skipped_steps for step_id in steps):
            result[call_id] = "blocked_by_dependency"
        elif not steps and any(
            issue.call_id == call_id for issue in reconciliation.issues
        ):
            result[call_id] = "failed"
    for step_id in blocked_steps:
        call_id = step_to_call.get(step_id)
        if call_id is not None:
            result[call_id] = "failed"
    return result


def _call_issue_codes(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    diagnostic: FunctionalExecutionDiagnostic | None,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for issue in reconciliation.issues:
        if issue.call_id is not None:
            result.setdefault(issue.call_id, []).append(issue.code)
    step_to_call = {
        item.call_id: item.canonical_call_id
        for item in reconciliation.execution_entries
    }
    for blocker in diagnostic.blockers if diagnostic is not None else ():
        call_id = step_to_call.get(blocker.step_id)
        if call_id is not None:
            result.setdefault(call_id, []).append(blocker.code)
    return {
        call_id: unique_ordered(codes)
        for call_id, codes in result.items()
    }


def _unmapped_runtime_write_mismatches(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    diagnostic: FunctionalExecutionDiagnostic | None,
) -> tuple[FunctionalTransactionShadowMismatch, ...]:
    if diagnostic is None:
        return ()
    known_step_ids = {
        item.call_id
        for item in reconciliation.execution_entries
    }
    return tuple(
        FunctionalTransactionShadowMismatch(
            "runtime_write_step_unmapped",
            None,
            "projected Functional call",
            write.step_id,
        )
        for write in diagnostic.state_write_provenance
        if write.step_id not in known_step_ids
    )


def _commit_observed_writes(
    working: WorkingPlannerState,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: FunctionalExecutionDiagnostic | None,
    call_ids: tuple[str, ...],
) -> tuple[FunctionalTransactionShadowMismatch, ...]:
    if diagnostic is None:
        return ()
    step_to_call = {
        item.call_id: item.canonical_call_id
        for item in reconciliation.execution_entries
    }
    allocations = {
        (item.call_id, returned.return_name): returned
        for item in reconciliation.calls
        for returned in item.returns
    }
    writes_by_call: dict[str, list[StateWriteProvenance]] = {}
    for write in diagnostic.state_write_provenance:
        call_id = (
            write.canonical_producer_call_id
            or step_to_call.get(write.step_id)
        )
        if call_id is None:
            continue
        writes_by_call.setdefault(call_id, []).append(write)
    mismatches: list[FunctionalTransactionShadowMismatch] = []
    for call_id in call_ids:
        pending_versions: dict[StateVersionId, IndexedStateVersion] = {}
        writes_by_version: dict[StateVersionId, StateWriteProvenance] = {}
        call_mismatches: list[FunctionalTransactionShadowMismatch] = []
        observed_return_names = {
            write.return_name
            for write in writes_by_call.get(call_id, ())
            if write.return_name is not None
            and write.selected_version_id is not None
        }
        for (owner_call_id, return_name), allocation in allocations.items():
            if (
                owner_call_id == call_id
                and allocation.selected_version_id is not None
                and return_name not in observed_return_names
            ):
                call_mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "verified_return_missing_runtime_write",
                        call_id,
                        allocation.selected_version_id,
                        None,
                    )
                )
        for write in writes_by_call.get(call_id, ()):
            if write.selected_version_id is None:
                continue
            if working.call_states[call_id].status != "verified":
                call_mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "failed_call_produced_state_write",
                        call_id,
                        "no StateVersion",
                        write.selected_version_id,
                    )
                )
                continue
            return_name = write.return_name
            allocation = (
                allocations.get((call_id, return_name))
                if return_name is not None
                else None
            )
            if allocation is None:
                call_mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "runtime_write_without_allocation",
                        call_id,
                        "B3 allocation",
                        return_name,
                    )
                )
                continue
            identity_mismatches = _write_identity_mismatches(
                call_id,
                allocation,
                write,
            )
            call_mismatches.extend(identity_mismatches)
            if identity_mismatches:
                continue
            pending_versions.setdefault(
                write.selected_version_id,
                IndexedStateVersion(
                    version_id=write.selected_version_id,
                    valid_scope_id=write.valid_scope_id,
                    producer_call_id=call_id,
                    produced_handle=write.produced_handle,
                    computation_key=write.computation_key,
                    state_effect_key=write.state_effect_key,
                    free_symbol_refs=tuple(write.free_symbol_names),
                    free_symbol_ids=write.free_symbol_ids,
                    previous_version_id=write.previous_version_id,
                    source_version_ids=write.source_version_ids,
                    runtime_destination=write.runtime_destination_key,
                    result_form=write.result_form,
                ),
            )
            writes_by_version.setdefault(write.selected_version_id, write)
        mismatches.extend(call_mismatches)
        if call_mismatches:
            continue
        pending_version_ids = frozenset(pending_versions)
        source_mismatches: list[FunctionalTransactionShadowMismatch] = []
        for version_id, write in writes_by_version.items():
            missing_sources = tuple(
                source_version_id
                for source_version_id in (
                    *(
                        (write.previous_version_id,)
                        if write.previous_version_id
                        else ()
                    ),
                    *write.source_version_ids,
                )
                if not _source_version_is_available(
                    source_version_id,
                    working=working,
                    pending_version_ids=pending_version_ids,
                )
            )
            if missing_sources:
                source_mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "state_version_source_unavailable",
                        call_id,
                        (
                            "committed predecessor/source versions or "
                            "typed writes in the same public call"
                        ),
                        {
                            "version_id": version_id,
                            "missing_source_version_ids": missing_sources,
                        },
                    )
                )
        mismatches.extend(source_mismatches)
        if source_mismatches:
            continue
        for version in pending_versions.values():
            working.commit_version(call_id, version)
    return tuple(mismatches)


def _source_version_is_available(
    version_id: StateVersionId,
    *,
    working: WorkingPlannerState,
    pending_version_ids: frozenset[StateVersionId],
) -> bool:
    return (
        working.identity_index.version(version_id) is not None
        or version_id in pending_version_ids
    )


def _write_identity_mismatches(
    call_id: str,
    allocation: Any,
    write: StateWriteProvenance,
) -> tuple[FunctionalTransactionShadowMismatch, ...]:
    allocation_missing = tuple(
        name
        for name, value in (
            ("math_object_id", allocation.math_object_id),
            ("logical_state_key", allocation.logical_state_key),
            ("typed_slot_id", allocation.typed_slot_id),
            ("selected_version_id", allocation.selected_version_id),
            ("computation_key", allocation.computation_key),
            ("allocation_action", allocation.allocation_action),
            ("valid_scope", allocation.valid_scope),
        )
        if value is None
    )
    write_missing = tuple(
        name
        for name, value in (
            ("math_object_id", write.math_object_id),
            ("logical_state_key", write.logical_state_key),
            ("typed_slot_id", write.typed_slot_id),
            ("selected_version_id", write.selected_version_id),
            ("computation_key", write.computation_key),
            ("allocation_action", write.allocation_action),
            ("valid_scope_id", write.valid_scope_id),
        )
        if value is None
    )
    if allocation_missing or write_missing:
        return (
            FunctionalTransactionShadowMismatch(
                "state_write_identity_incomplete",
                call_id,
                {"allocation_missing": (), "write_missing": ()},
                {
                    "allocation_missing": allocation_missing,
                    "write_missing": write_missing,
                },
            ),
        )
    expected = (
        allocation.math_object_id,
        allocation.selected_version_id,
        allocation.logical_state_key,
        allocation.typed_slot_id,
        allocation.previous_version_id,
        tuple(allocation.source_version_ids),
        allocation.valid_scope,
        allocation.computation_key,
    )
    actual = (
        write.math_object_id,
        write.selected_version_id,
        write.logical_state_key,
        write.typed_slot_id,
        write.previous_version_id,
        tuple(write.source_version_ids),
        write.valid_scope_id,
        write.computation_key,
    )
    if expected == actual:
        return ()
    return (
        FunctionalTransactionShadowMismatch(
            "state_write_identity_drift",
            call_id,
            expected,
            actual,
        ),
    )


def _answer_mismatches(
    graph: LogicalFunctionalGraph,
    *,
    working: WorkingPlannerState,
    goal_verification_report: Any | None,
    reconciliation: FunctionalPlanReconciliationResult,
) -> tuple[FunctionalTransactionShadowMismatch, ...]:
    if goal_verification_report is None:
        return ()
    step_to_call = {
        item.call_id: item.canonical_call_id
        for item in reconciliation.execution_entries
    }
    answer_by_handle = {
        item.answer_handle: item for item in graph.answer_bindings
    }
    allocations = {
        (item.call_id, returned.return_name): returned
        for item in reconciliation.calls
        for returned in item.returns
    }
    result: list[FunctionalTransactionShadowMismatch] = []
    for goal in goal_verification_report.goals:
        if goal.status != "passed":
            continue
        answer = answer_by_handle.get(goal.goal_handle)
        producer_call_id = step_to_call.get(goal.producer_step_id or "")
        if answer is None:
            result.append(
                FunctionalTransactionShadowMismatch(
                    "passed_answer_binding_missing",
                    producer_call_id,
                    goal.goal_handle,
                    None,
                )
            )
        elif (
            (
                allocation := allocations.get(
                    (answer.producer_call_id, answer.return_name)
                )
            )
            is not None
            and allocation.selected_version_id is not None
            and (
                allocation.selected_version_id
                not in working.call_states[
                    answer.producer_call_id
                ].return_version_ids
                or working.identity_index.version(
                    allocation.selected_version_id
                )
                is None
            )
        ):
            result.append(
                FunctionalTransactionShadowMismatch(
                    "passed_answer_version_not_committed",
                    answer.producer_call_id,
                    allocation.selected_version_id,
                    working.call_states[
                        answer.producer_call_id
                    ].return_version_ids,
                )
            )
        elif working.call_states[answer.producer_call_id].status != "verified":
            result.append(
                FunctionalTransactionShadowMismatch(
                    "passed_answer_producer_not_verified",
                    answer.producer_call_id,
                    "verified",
                    working.call_states[answer.producer_call_id].status,
                )
            )
        elif (
            producer_call_id is not None
            and producer_call_id != answer.producer_call_id
        ):
            result.append(
                FunctionalTransactionShadowMismatch(
                    "answer_producer_drift",
                    answer.producer_call_id,
                    answer.producer_call_id,
                    producer_call_id,
                )
            )
    return tuple(result)


def _payload(value: Any) -> Any:
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if isinstance(value, tuple):
        return [_payload(item) for item in value]
    if isinstance(value, list):
        return [_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _payload(item) for key, item in value.items()}
    return value


__all__ = [
    "FunctionalCallExecutionState",
    "FunctionalTransactionEvent",
    "FunctionalTransactionMode",
    "FunctionalTransactionShadowMismatch",
    "FunctionalTransactionShadowObserver",
    "FunctionalTransactionShadowReport",
    "WorkingPlannerState",
    "build_working_state",
    "failed_shadow_report",
]
