"""C1 transactional execution shadow for canonical Functional calls.

The legacy whole-plan replay remains authoritative. This module reuses its
compiled StepPlans as a migration bridge, but executes each public Functional
call in an isolated RuntimeContext branch and commits only verified calls.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Mapping, Sequence

from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.canonical_draft_finalizer import (
    CanonicalDraftFinalizer,
)
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
)
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
)
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraph,
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCallReconciliation,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalReturnAllocation,
    SemanticRef,
)
from shuxueshuo_server.solver.runtime.functional_transaction_shadow import (
    FunctionalCallExecutionState,
    FunctionalTransactionEvent,
    FunctionalTransactionShadowMismatch,
    WorkingPlannerState,
    build_working_state,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    PlannerOutput,
    StepPlan,
    TypedValue,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    RuntimeDestinationKey,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StateWriteProvenance,
    StepIntentExecutionDiagnostic,
    StepIntentRuntimeResult,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    project_functional_state_dependencies,
    project_functional_state_writes,
)
from shuxueshuo_server.solver.runtime.student_symbolic_complexity import (
    runtime_free_symbol_names,
)
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalCallTransactionStatus = Literal["verified", "failed"]
_NON_BLOCKING_BEHAVIOR_DELTA_CODES = frozenset(
    {"transactional_independent_branch_verified"}
)


@dataclass(frozen=True)
class PreparedFunctionalCall:
    """One canonical public call with call-time typed state reads."""

    call_id: str
    capability_id: str
    step_ids: tuple[str, ...]
    dependency_call_ids: tuple[str, ...]
    reconciliation: FunctionalCallReconciliation
    required_return_names: tuple[str, ...] = ()
    state_reads: tuple["PreparedFunctionalStateRead", ...] = ()


@dataclass(frozen=True)
class PreparedFunctionalStateRead:
    """One call-time exact/latest StateVersion selection."""

    arg_name: str
    item_index: int
    selection: Literal["exact", "latest"]
    original_version_id: StateVersionId
    selected_version_id: StateVersionId
    original_runtime_path: str
    snapshot_runtime_path: str
    runtime_value: TypedValue


@dataclass(frozen=True)
class CompiledPublicReturn:
    return_name: str
    allocation: FunctionalReturnAllocation
    expected_write: StateWriteProvenance | None
    required: bool
    max_independent_free_parameters: int | None = None


@dataclass(frozen=True)
class CompiledFunctionalCall:
    call_id: str
    step_ids: tuple[str, ...]
    declarations: tuple[ContextDeclaration, ...]
    plans: tuple[StepPlan, ...]
    public_returns: tuple[CompiledPublicReturn, ...]


@dataclass(frozen=True)
class FunctionalCallExecutionResult:
    call_id: str
    status: FunctionalCallTransactionStatus
    runtime_results: tuple[StepIntentRuntimeResult, ...] = ()
    state_writes: tuple[StateWriteProvenance, ...] = ()
    committed_versions: tuple[IndexedStateVersion, ...] = ()
    checks: tuple[Any, ...] = ()
    root_issues: tuple[PlannerRetryIssue, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "status": self.status,
            "runtime_results": [
                item.to_payload() for item in self.runtime_results
            ],
            "state_writes": [item.to_payload() for item in self.state_writes],
            "committed_versions": [
                item.to_payload() for item in self.committed_versions
            ],
            "checks": [_payload(item) for item in self.checks],
            "root_issues": [item.to_payload() for item in self.root_issues],
        }


@dataclass(frozen=True)
class FunctionalTransactionBehaviorDelta:
    code: str
    call_id: str
    detail: Any

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "call_id": self.call_id,
            "detail": _payload(self.detail),
        }


@dataclass(frozen=True)
class FunctionalTransactionalExecutionReport:
    graph: LogicalFunctionalGraph
    call_states: tuple[FunctionalCallExecutionState, ...]
    events: tuple[FunctionalTransactionEvent, ...]
    committed_versions: tuple[IndexedStateVersion, ...]
    call_results: tuple[FunctionalCallExecutionResult, ...]
    goal_verification: dict[str, Any] | None = None
    compatibility_mismatches: tuple[
        FunctionalTransactionShadowMismatch, ...
    ] = ()
    behavior_deltas: tuple[FunctionalTransactionBehaviorDelta, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.compatibility_mismatches and all(
            item.code in _NON_BLOCKING_BEHAVIOR_DELTA_CODES
            for item in self.behavior_deltas
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "graph": self.graph.to_payload(),
            "call_states": [item.to_payload() for item in self.call_states],
            "events": [item.to_payload() for item in self.events],
            "committed_versions": [
                item.to_payload() for item in self.committed_versions
            ],
            "call_results": [item.to_payload() for item in self.call_results],
            "goal_verification": self.goal_verification,
            "compatibility_mismatches": [
                item.to_payload() for item in self.compatibility_mismatches
            ],
            "behavior_deltas": [
                item.to_payload() for item in self.behavior_deltas
            ],
        }


class FunctionalCallPreparationService:
    """Prepare a canonical call from typed reconciliation state.

    B5b supplies the typed identity baseline. C1 preserves exact CallResult
    reads, while wire semantic reads and resolver/context-owned arguments
    select the latest visible committed StateVersion at call time.
    """

    def prepare(
        self,
        *,
        call_id: str,
        graph: LogicalFunctionalGraph,
        reconciliation: FunctionalPlanReconciliationResult,
        working: WorkingPlannerState,
        runtime_context: RuntimeContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> PreparedFunctionalCall:
        calls = {item.call_id: item for item in reconciliation.calls}
        reconciled = calls.get(call_id)
        node = next(
            (item for item in graph.calls if item.call_id == call_id),
            None,
        )
        if reconciled is None or node is None:
            raise ValueError(
                "planner_configuration_error: "
                f"planner.transactional_call_unresolved: call={call_id}"
            )
        projection = next(
            (
                item
                for item in reconciliation.projection_map
                if item.call_id == call_id
            ),
            None,
        )
        if projection is None or not projection.step_ids:
            raise ValueError(
                "planner_configuration_error: "
                f"planner.transactional_projection_missing: call={call_id}"
            )
        missing_versions = tuple(
            value.state_version_id
            for values in reconciled.resolved_args.values()
            for value in values
            if (
                value.state_version_id is not None
                and working.identity_index.version(value.state_version_id)
                is None
            )
        )
        if missing_versions:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_input_version_unresolved: "
                f"call={call_id}, versions="
                f"{[item.to_payload() for item in missing_versions]}"
            )
        wire_call = next(
            (
                item
                for item in reconciliation.plan.calls
                if item.call_id == call_id
            ),
            None,
        )
        capability = capability_catalog.get(reconciled.capability_id)
        if capability is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_capability_unavailable: "
                f"call={call_id}, capability={reconciled.capability_id}"
            )
        arg_specs = {item.name: item for item in capability.args}
        runtime_bindings = CanonicalRuntimeBindingIndex.from_context(
            runtime_context,
            handle_registry=handle_registry,
            question_goals=inputs.question_goals,
            functional_consumer_identity_mode="authoritative",
        )
        dependency_sources = {
            (item.arg_name, item.state_version_id): item.source
            for item in project_functional_state_dependencies(
                reconciliation.plan,
                reconciliation.calls,
                catalog=capability_catalog,
            )
            if item.step_id == call_id
            and item.arg_name is not None
            and item.state_version_id is not None
        }
        state_reads: list[PreparedFunctionalStateRead] = []
        snapshot_paths: dict[StateVersionId, str] = {}
        for arg_name, values in reconciled.resolved_args.items():
            wire_refs = (
                wire_call.args.get(arg_name, ())
                if wire_call is not None
                else ()
            )
            arg_spec = arg_specs.get(arg_name)
            for item_index, value in enumerate(values):
                if value.state_version_id is None:
                    continue
                original = working.identity_index.version(
                    value.state_version_id
                )
                if original is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.transactional_input_version_unresolved: "
                        f"call={call_id}, arg={arg_name}, "
                        f"version={value.state_version_id.to_payload()}"
                    )
                if not working.identity_index.visibility.is_visible(
                    original.valid_scope_id,
                    consumer_scope_id=node.execution_scope_id,
                ):
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.transactional_input_version_invisible: "
                        f"call={call_id}, arg={arg_name}, "
                        f"version={value.state_version_id.to_payload()}"
                    )
                wire_uses_semantic_latest = any(
                    isinstance(ref, SemanticRef) for ref in wire_refs
                )
                resolver_uses_latest = (
                    (
                        arg_spec is not None
                        and arg_spec.binding_authority == "resolver"
                    )
                    or dependency_sources.get(
                        (arg_name, value.state_version_id)
                    )
                    in {"resolver", "context"}
                )
                selection: Literal["exact", "latest"] = (
                    "latest"
                    if wire_uses_semantic_latest or resolver_uses_latest
                    else "exact"
                )
                selected = original
                if selection == "latest":
                    selected = (
                        working.identity_index.latest_visible(
                            original.version_id.slot_id.logical_key,
                            consumer_scope_id=node.execution_scope_id,
                        )
                        or original
                    )
                runtime_value = working.runtime_version_values.get(
                    selected.version_id
                )
                if runtime_value is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.transactional_runtime_value_missing: "
                        f"call={call_id}, arg={arg_name}, "
                        f"version={selected.version_id.to_payload()}"
                    )
                original_path = _indexed_runtime_path(original)
                if original_path is None:
                    try:
                        original_path = runtime_bindings.path_for(
                            value.handle,
                            expected_type=value.runtime_type,
                        )
                    except Exception as exc:
                        raise ValueError(
                            "planner_configuration_error: "
                            "planner.transactional_runtime_binding_missing: "
                            f"call={call_id}, arg={arg_name}, "
                            f"version={original.version_id.to_payload()}"
                        ) from exc
                state_reads.append(
                    PreparedFunctionalStateRead(
                        arg_name=arg_name,
                        item_index=item_index,
                        selection=selection,
                        original_version_id=original.version_id,
                        selected_version_id=selected.version_id,
                        original_runtime_path=original_path,
                        snapshot_runtime_path=snapshot_paths.setdefault(
                            selected.version_id,
                            _transaction_snapshot_path(
                                runtime_context,
                                scope_id=node.execution_scope_id,
                                call_id=call_id,
                                item_index=len(snapshot_paths),
                            ),
                        ),
                        runtime_value=runtime_value,
                    )
                )
                support_version_ids = (
                    unique_ordered(
                        source_version_id
                        for role in value.lineage.object_roles
                        if role.state_requirement == "materialized"
                        for source_version_id in role.source_version_ids
                    )
                    if value.runtime_type == "PathTransformation"
                    else ()
                )
                for support_index, support_version_id in enumerate(
                    support_version_ids
                ):
                    if support_version_id == value.state_version_id:
                        continue
                    support = working.identity_index.version(
                        support_version_id
                    )
                    if support is None:
                        raise ValueError(
                            "planner_configuration_error: "
                            "planner.transactional_input_version_unresolved: "
                            f"call={call_id}, arg={arg_name}, "
                            f"support={support_version_id.to_payload()}"
                        )
                    if not working.identity_index.visibility.is_visible(
                        support.valid_scope_id,
                        consumer_scope_id=node.execution_scope_id,
                    ):
                        raise ValueError(
                            "planner_configuration_error: "
                            "planner.transactional_input_version_invisible: "
                            f"call={call_id}, arg={arg_name}, "
                            f"support={support_version_id.to_payload()}"
                        )
                    support_value = working.runtime_version_values.get(
                        support_version_id
                    )
                    support_path = _indexed_runtime_path(support)
                    if (
                        support_path is None
                        and support.produced_handle is not None
                    ):
                        try:
                            support_path = runtime_bindings.path_for(
                                support.produced_handle,
                                expected_type=(
                                    support.version_id.slot_id.logical_key
                                    .runtime_type
                                ),
                            )
                        except Exception:
                            support_path = None
                    if support_value is None or support_path is None:
                        raise ValueError(
                            "planner_configuration_error: "
                            "planner.transactional_runtime_value_missing: "
                            f"call={call_id}, arg={arg_name}, "
                            f"support={support_version_id.to_payload()}"
                        )
                    state_reads.append(
                        PreparedFunctionalStateRead(
                            arg_name=(
                                f"{arg_name}.__support_{support_index}"
                            ),
                            item_index=support_index,
                            selection="exact",
                            original_version_id=support_version_id,
                            selected_version_id=support_version_id,
                            original_runtime_path=support_path,
                            snapshot_runtime_path=snapshot_paths.setdefault(
                                support_version_id,
                                _transaction_snapshot_path(
                                    runtime_context,
                                    scope_id=node.execution_scope_id,
                                    call_id=call_id,
                                    item_index=len(snapshot_paths),
                                ),
                            ),
                            runtime_value=support_value,
                        )
                    )
        required_return_names = set(
            wire_call.return_bindings if wire_call is not None else ()
        )
        required_return_names.update(
            value.return_name
            for consumer in reconciliation.plan.calls
            for values in consumer.args.values()
            for value in values
            if (
                isinstance(value, CallResultRef)
                and value.from_call == call_id
            )
        )
        return PreparedFunctionalCall(
            call_id=call_id,
            capability_id=reconciled.capability_id,
            step_ids=projection.step_ids,
            dependency_call_ids=node.dependency_call_ids,
            reconciliation=reconciled,
            required_return_names=tuple(sorted(required_return_names)),
            state_reads=tuple(state_reads),
        )


class FunctionalCallBridgeCompiler:
    """Slice one public call from the legacy compiled PlannerOutput.

    This is the C1 migration bridge. It never runs a fresh-prefix trial and
    never includes dependency StepPlans in the returned transaction.
    """

    def compile(
        self,
        prepared_call: PreparedFunctionalCall,
        *,
        output: PlannerOutput,
        diagnostic: StepIntentExecutionDiagnostic,
        capability_catalog: FunctionalCapabilityCatalog,
    ) -> CompiledFunctionalCall:
        step_ids = frozenset(prepared_call.step_ids)
        plans_by_id = {item.step_id: item for item in output.step_plans}
        missing = tuple(
            step_id
            for step_id in prepared_call.step_ids
            if step_id not in plans_by_id
        )
        if missing:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_compiled_steps_missing: "
                f"call={prepared_call.call_id}, steps={list(missing)}"
            )
        plans = tuple(
            plans_by_id[step_id] for step_id in prepared_call.step_ids
        )
        path_rewrites: dict[str, str] = {}
        for read in prepared_call.state_reads:
            existing = path_rewrites.get(read.original_runtime_path)
            if (
                existing is not None
                and existing != read.snapshot_runtime_path
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.transactional_arg_path_ambiguous: "
                    f"call={prepared_call.call_id}, "
                    f"path={read.original_runtime_path}"
                )
            path_rewrites[read.original_runtime_path] = (
                read.snapshot_runtime_path
            )
        plans = tuple(
            _rewrite_plan_input_paths(plan, path_rewrites)
            for plan in plans
        )
        referenced_paths = _plan_paths(plans)
        declarations = tuple(
            item
            for item in output.context_declarations
            if item.path in referenced_paths
        )
        writes = {
            item.return_name: item
            for item in diagnostic.state_write_provenance
            if item.step_id in step_ids and item.return_name is not None
        }
        capability = capability_catalog.get(prepared_call.capability_id)
        if capability is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_capability_unavailable: "
                f"call={prepared_call.call_id}, "
                f"capability={prepared_call.capability_id}"
            )
        return_specs = {item.name: item for item in capability.returns}
        public_returns = tuple(
            CompiledPublicReturn(
                return_name=allocation.return_name,
                allocation=allocation,
                expected_write=writes.get(allocation.return_name),
                required=(
                    return_specs[allocation.return_name].required
                    if allocation.return_name in return_specs
                    else True
                )
                or allocation.return_name
                in prepared_call.required_return_names,
                max_independent_free_parameters=(
                    return_specs[
                        allocation.return_name
                    ].max_independent_free_parameters
                    if allocation.return_name in return_specs
                    else None
                ),
            )
            for allocation in prepared_call.reconciliation.returns
        )
        return CompiledFunctionalCall(
            call_id=prepared_call.call_id,
            step_ids=prepared_call.step_ids,
            declarations=declarations,
            plans=plans,
            public_returns=public_returns,
        )


class FunctionalRuntimeWriteCommitter:
    """Validate actual branch outputs and create an atomic commit payload."""

    def commit_payload(
        self,
        compiled: CompiledFunctionalCall,
        *,
        prepared: PreparedFunctionalCall,
        branch: RuntimeContext,
        plan: FunctionalPlan,
        working: WorkingPlannerState,
    ) -> tuple[
        tuple[StepIntentRuntimeResult, ...],
        tuple[StateWriteProvenance, ...],
        tuple[IndexedStateVersion, ...],
        dict[StateVersionId, TypedValue],
        tuple[PlannerRetryIssue, ...],
    ]:
        wire_call = next(
            (item for item in plan.calls if item.call_id == compiled.call_id),
            None,
        )
        expectations = (
            dict(wire_call.return_expectations)
            if wire_call is not None
            else {}
        )
        runtime_results: list[StepIntentRuntimeResult] = []
        actual_writes: list[StateWriteProvenance] = []
        versions: list[IndexedStateVersion] = []
        runtime_values: dict[StateVersionId, TypedValue] = {}
        issues: list[PlannerRetryIssue] = []
        version_rewrites = {
            item.original_version_id: item.selected_version_id
            for item in prepared.state_reads
            if item.original_version_id != item.selected_version_id
        }
        pending_ids = {
            item.expected_write.selected_version_id
            for item in compiled.public_returns
            if item.expected_write is not None
            and item.expected_write.selected_version_id is not None
        }
        for returned in compiled.public_returns:
            write = returned.expected_write
            if write is None:
                if returned.required:
                    issues.append(
                        _issue(
                            compiled.call_id,
                            "planner.contract_required_return_missing",
                            f"required return has no compiled write: "
                            f"{returned.return_name}",
                        )
                    )
                continue
            path = (
                write.runtime_destination_key.runtime_path
                if write.runtime_destination_key is not None
                else None
            )
            path = path or _runtime_path_for_write(
                compiled.plans,
                write,
            )
            if not path:
                if returned.required:
                    issues.append(
                        _issue(
                            compiled.call_id,
                            "planner.contract_runtime_destination_drift",
                            f"return has no runtime destination: "
                            f"{returned.return_name}",
                        )
                    )
                continue
            try:
                typed = branch.read_path(
                    path,
                    from_scope_id=write.scope_id,
                    expected_type=write.runtime_type,
                )
            except (KeyError, PermissionError, TypeError) as exc:
                if returned.required:
                    issues.append(
                        _issue(
                            compiled.call_id,
                            "planner.contract_required_return_missing",
                            f"return {returned.return_name} was not "
                            f"materialized: {exc}",
                        )
                    )
                continue
            free_symbols = tuple(
                item
                for item in runtime_free_symbol_names(typed.value)
                if item not in write.closure_ignored_symbol_names
            )
            expected_form = expectations.get(returned.return_name)
            actual_form = _actual_form(expected_form, free_symbols)
            if (
                expected_form in {"closed_state", "closed_value"}
                and free_symbols
            ):
                issues.append(
                    _issue(
                        compiled.call_id,
                        "functional.return_form_mismatch",
                        f"return {returned.return_name} expected "
                        f"{expected_form} "
                        f"but retains {list(free_symbols)}",
                    )
                )
                continue
            if (
                returned.max_independent_free_parameters is not None
                and len(free_symbols)
                > returned.max_independent_free_parameters
            ):
                issues.append(
                    _issue(
                        compiled.call_id,
                        "functional.return_complexity_exceeded",
                        f"return {returned.return_name} retains "
                        f"{len(free_symbols)} free symbols; maximum is "
                        f"{returned.max_independent_free_parameters}",
                    )
                )
                continue
            write = _rewrite_write_input_versions(
                write,
                version_rewrites,
            )
            runtime_destination = write.runtime_destination_key
            if (
                runtime_destination is None
                and write.logical_state_key is not None
            ):
                runtime_destination = RuntimeDestinationKey(
                    write.logical_state_key.object_id,
                    write.logical_state_key.state_kind,
                    write.logical_state_key.runtime_type,
                    path,
                )
            actual_write = replace(
                write,
                free_symbol_names=free_symbols,
                result_form=actual_form,
                runtime_destination_key=runtime_destination,
            )
            actual_writes.append(actual_write)
            runtime_results.append(
                _runtime_result(
                    branch,
                    write=write,
                    value=typed.value,
                )
            )
            if write.selected_version_id is None:
                continue
            missing_sources = tuple(
                item
                for item in (
                    *(
                        (write.previous_version_id,)
                        if write.previous_version_id is not None
                        else ()
                    ),
                    *write.source_version_ids,
                )
                if (
                    working.identity_index.version(item) is None
                    and item not in pending_ids
                )
            )
            if missing_sources:
                issues.append(
                    _issue(
                        compiled.call_id,
                        "planner.state_version_source_unavailable",
                        f"return {returned.return_name} has unavailable "
                        f"source versions",
                        details={
                            "source_version_ids": [
                                item.to_payload() for item in missing_sources
                            ]
                        },
                    )
                )
                continue
            versions.append(
                IndexedStateVersion(
                    version_id=actual_write.selected_version_id,
                    valid_scope_id=(
                        actual_write.valid_scope_id
                        or actual_write.scope_id
                    ),
                    producer_call_id=compiled.call_id,
                    produced_handle=actual_write.produced_handle,
                    computation_key=actual_write.computation_key,
                    state_effect_key=actual_write.state_effect_key,
                    free_symbol_refs=free_symbols,
                    previous_version_id=actual_write.previous_version_id,
                    source_version_ids=actual_write.source_version_ids,
                    runtime_destination=runtime_destination,
                    result_form=actual_form,
                )
            )
            runtime_values[actual_write.selected_version_id] = typed
        if issues:
            return (
                tuple(runtime_results),
                tuple(actual_writes),
                (),
                {},
                tuple(issues),
            )
        return (
            tuple(runtime_results),
            tuple(actual_writes),
            tuple(versions),
            runtime_values,
            (),
        )


class FunctionalTransactionalInterpreter:
    """Execute canonical Functional calls transactionally in shadow mode."""

    def __init__(
        self,
        *,
        executor_factory: Callable[
            [PlannerInputs, RuntimeContext],
            Any,
        ]
        | None = None,
    ) -> None:
        self._executor_factory = (
            executor_factory or _default_executor_factory
        )

    def execute(
        self,
        *,
        raw_plan: FunctionalPlan,
        reconciliation: FunctionalPlanReconciliationResult,
        legacy_output: PlannerOutput,
        legacy_diagnostic: StepIntentExecutionDiagnostic,
        runtime_context: RuntimeContext,
        parent_context: PlannerStateContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        goal_verification_report: Any | None = None,
    ) -> FunctionalTransactionalExecutionReport:
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

        current_context = runtime_context.fork()
        _capture_initial_runtime_version_values(
            working,
            current_context,
            inputs=inputs,
            handle_registry=handle_registry,
        )
        capability_catalog = FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
        preparer = FunctionalCallPreparationService()
        bridge = FunctionalCallBridgeCompiler()
        committer = FunctionalRuntimeWriteCommitter()
        results: list[FunctionalCallExecutionResult] = []
        for call_id in graph.canonical_order:
            state = working.call_states[call_id]
            dependency_statuses = tuple(
                working.call_states[item].status
                for item in state.dependency_call_ids
                if item in working.call_states
            )
            if any(
                item in {"failed", "blocked_by_dependency"}
                for item in dependency_statuses
            ):
                working.set_status(call_id, "blocked_by_dependency")
                working.emit(call_id, "blocked")
                continue
            if not all(item == "verified" for item in dependency_statuses):
                mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "transactional_dependency_not_ready",
                        call_id,
                        "all dependencies verified",
                        dependency_statuses,
                    )
                )
                working.set_status(call_id, "failed")
                working.emit(call_id, "failed")
                continue
            working.set_status(call_id, "ready")
            working.emit(call_id, "became_ready")
            working.set_status(call_id, "running")
            working.emit(call_id, "running")
            try:
                prepared = preparer.prepare(
                    call_id=call_id,
                    graph=graph,
                    reconciliation=reconciliation,
                    working=working,
                    runtime_context=current_context,
                    inputs=inputs,
                    handle_registry=handle_registry,
                    capability_catalog=capability_catalog,
                )
                compiled = bridge.compile(
                    prepared,
                    output=legacy_output,
                    diagnostic=legacy_diagnostic,
                    capability_catalog=capability_catalog,
                )
                branch = current_context.fork()
                _apply_missing_declarations(branch, compiled.declarations)
                _materialize_transaction_state_reads(
                    branch,
                    prepared.state_reads,
                    scope_id=(
                        next(
                            item.execution_scope_id
                            for item in graph.calls
                            if item.call_id == call_id
                        )
                    ),
                )
                executor = self._executor_factory(inputs, branch)
                execution = executor.execute_plan(
                    branch,
                    list(compiled.plans),
                )
                failed_checks = tuple(
                    item
                    for item in execution.checks
                    if not bool(getattr(item, "ok", False))
                )
                if failed_checks:
                    raise RuntimeError(
                        "transactional runtime checks failed: "
                        + ", ".join(
                            str(getattr(item, "name", item))
                            for item in failed_checks
                        )
                    )
                (
                    runtime_results,
                    writes,
                    versions,
                    runtime_values,
                    issues,
                ) = committer.commit_payload(
                    compiled,
                    prepared=prepared,
                    branch=branch,
                    plan=reconciliation.plan,
                    working=working,
                )
                if issues:
                    working.set_status(
                        call_id,
                        "failed",
                        issue_codes=tuple(item.code for item in issues),
                    )
                    working.emit(call_id, "failed")
                    results.append(
                        FunctionalCallExecutionResult(
                            call_id,
                            "failed",
                            runtime_results=runtime_results,
                            state_writes=writes,
                            checks=tuple(execution.checks),
                            root_issues=issues,
                        )
                    )
                    continue
                projected_writes = tuple(
                    item
                    for item in project_functional_state_writes(
                        reconciliation.plan,
                        reconciliation.calls,
                    )
                    if item.step_id == call_id
                )
                CanonicalDraftFinalizer().finalize_compiled_state_writes(
                    projected_state_writes=projected_writes,
                    provenance=writes,
                    plans=compiled.plans,
                    question_goals=tuple(inputs.question_goals),
                    handle_registry=handle_registry,
                )
                working.commit_verified_transaction(
                    call_id,
                    versions,
                    runtime_values,
                )
                current_context = branch
                results.append(
                    FunctionalCallExecutionResult(
                        call_id,
                        "verified",
                        runtime_results=runtime_results,
                        state_writes=writes,
                        committed_versions=versions,
                        checks=tuple(execution.checks),
                    )
                )
            except Exception as exc:
                issue = _issue(
                    call_id,
                    (
                        "planner.transactional_configuration_error"
                        if "planner_configuration_error" in str(exc)
                        else "functional.transactional_call_failed"
                    ),
                    f"{type(exc).__name__}: {exc}",
                )
                working.set_status(
                    call_id,
                    "failed",
                    issue_codes=(issue.code,),
                )
                working.emit(call_id, "failed")
                results.append(
                    FunctionalCallExecutionResult(
                        call_id,
                        "failed",
                        root_issues=(issue,),
                    )
                )

        compatibility, deltas = _compare_with_legacy(
            graph,
            working=working,
            reconciliation=reconciliation,
            diagnostic=legacy_diagnostic,
            call_results=tuple(results),
        )
        mismatches.extend(compatibility)
        return FunctionalTransactionalExecutionReport(
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
            committed_versions=tuple(working.committed_versions.values()),
            call_results=tuple(results),
            goal_verification=(
                goal_verification_report.to_payload()
                if hasattr(goal_verification_report, "to_payload")
                else None
            ),
            compatibility_mismatches=tuple((*mismatches,)),
            behavior_deltas=deltas,
        )


def failed_execution_report(
    *,
    message: str,
) -> FunctionalTransactionalExecutionReport:
    empty = LogicalFunctionalGraph((), (), (), (), (), ())
    return FunctionalTransactionalExecutionReport(
        graph=empty,
        call_states=(),
        events=(),
        committed_versions=(),
        call_results=(),
        compatibility_mismatches=(
            FunctionalTransactionShadowMismatch(
                "transactional_execution_shadow_failed",
                None,
                "transactional execution succeeds",
                message,
            ),
        ),
    )


def _compare_with_legacy(
    graph: LogicalFunctionalGraph,
    *,
    working: WorkingPlannerState,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: StepIntentExecutionDiagnostic,
    call_results: tuple[FunctionalCallExecutionResult, ...],
) -> tuple[
    tuple[FunctionalTransactionShadowMismatch, ...],
    tuple[FunctionalTransactionBehaviorDelta, ...],
]:
    projection = {
        item.call_id: frozenset(item.step_ids)
        for item in reconciliation.projection_map
    }
    accepted = {
        item.step_id for item in diagnostic.accepted_prefix
    }
    legacy_verified = {
        call_id
        for call_id in graph.canonical_order
        if projection.get(call_id)
        and projection[call_id] <= accepted
    }
    actual_states = working.call_states
    mismatches: list[FunctionalTransactionShadowMismatch] = []
    deltas: list[FunctionalTransactionBehaviorDelta] = []
    independently_verified: set[str] = set()
    for call_id in graph.canonical_order:
        actual = actual_states[call_id].status
        if call_id in legacy_verified and actual != "verified":
            mismatches.append(
                FunctionalTransactionShadowMismatch(
                    "legacy_verified_transaction_failed",
                    call_id,
                    "verified",
                    actual,
                )
            )
        elif call_id not in legacy_verified and actual == "verified":
            independently_verified.add(call_id)
            deltas.append(
                FunctionalTransactionBehaviorDelta(
                    "transactional_independent_branch_verified",
                    call_id,
                    "legacy prefix replay did not verify this call",
                )
            )
    legacy_writes = {
        (item.step_id, item.return_name): item
        for item in diagnostic.state_write_provenance
        if item.return_name is not None
    }
    for result in call_results:
        if result.status != "verified":
            continue
        for write in result.state_writes:
            legacy = legacy_writes.get((write.step_id, write.return_name))
            if legacy is None:
                if result.call_id in independently_verified:
                    continue
                mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "transactional_runtime_write_missing_legacy",
                        result.call_id,
                        "legacy runtime write",
                        write.return_name,
                    )
                )
                continue
            expected = (
                legacy.selected_version_id,
                legacy.previous_version_id,
                legacy.source_version_ids,
                legacy.result_form,
                tuple(legacy.free_symbol_names),
            )
            actual = (
                write.selected_version_id,
                write.previous_version_id,
                write.source_version_ids,
                write.result_form,
                tuple(write.free_symbol_names),
            )
            if expected != actual:
                mismatches.append(
                    FunctionalTransactionShadowMismatch(
                        "transactional_runtime_write_drift",
                        result.call_id,
                        expected,
                        actual,
                    )
                )
                continue
    return tuple(mismatches), tuple(deltas)


def _capture_initial_runtime_version_values(
    working: WorkingPlannerState,
    context: RuntimeContext,
    *,
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
) -> None:
    runtime_bindings = CanonicalRuntimeBindingIndex.from_context(
        context,
        handle_registry=handle_registry,
        question_goals=inputs.question_goals,
        functional_consumer_identity_mode="authoritative",
    )
    for version in working.identity_index.all_versions():
        if version.version_id in working.runtime_version_values:
            continue
        if (
            version.version_id.ordinal != 0
            and version.producer_call_id is not None
        ):
            continue
        path = _indexed_runtime_path(version)
        if path is None and version.produced_handle is not None:
            try:
                path = runtime_bindings.path_for(
                    version.produced_handle,
                    expected_type=(
                        version.version_id.slot_id.logical_key.runtime_type
                    ),
                )
            except Exception:
                path = None
        if path is None:
            continue
        try:
            value = context.read_path(
                path,
                from_scope_id=version.valid_scope_id,
                expected_type=(
                    version.version_id.slot_id.logical_key.runtime_type
                ),
            )
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        working.runtime_version_values[version.version_id] = value


def _materialize_transaction_state_reads(
    context: RuntimeContext,
    reads: Sequence[PreparedFunctionalStateRead],
    *,
    scope_id: str,
) -> None:
    written: set[str] = set()
    for read in reads:
        if read.snapshot_runtime_path in written:
            continue
        context.write_path(
            read.snapshot_runtime_path,
            read.runtime_value,
            from_scope_id=scope_id,
            allow_overwrite=True,
        )
        written.add(read.snapshot_runtime_path)


def _indexed_runtime_path(version: IndexedStateVersion) -> str | None:
    destination = version.runtime_destination
    return destination.runtime_path if destination is not None else None


def _transaction_snapshot_path(
    context: RuntimeContext,
    *,
    scope_id: str,
    call_id: str,
    item_index: int,
) -> str:
    scope = context.get_scope(scope_id)
    key = (
        "__functional_transaction_"
        + "".join(
            character if character.isalnum() else "_"
            for character in call_id
        )
        + f"_{item_index}"
    )
    if scope.scope_type == "problem":
        return f"$problem.facts.{key}"
    return f"${scope.scope_type}.{scope.scope_id}.facts.{key}"


def _rewrite_plan_input_paths(
    plan: StepPlan,
    rewrites: Mapping[str, str],
) -> StepPlan:
    if not rewrites:
        return plan

    def rewrite(value: str | tuple[str, ...]) -> str | tuple[str, ...]:
        if isinstance(value, tuple):
            return tuple(rewrites.get(item, item) for item in value)
        return rewrites.get(value, value)

    return replace(
        plan,
        invocations=[
            replace(
                invocation,
                inputs={
                    name: rewrite(value)
                    for name, value in invocation.inputs.items()
                },
            )
            for invocation in plan.invocations
        ],
    )


def _rewrite_write_input_versions(
    write: StateWriteProvenance,
    rewrites: Mapping[StateVersionId, StateVersionId],
) -> StateWriteProvenance:
    if not rewrites:
        return write

    def rewrite(
        version_id: StateVersionId | None,
    ) -> StateVersionId | None:
        return rewrites.get(version_id, version_id)

    computation_key = write.computation_key
    if computation_key is not None:
        computation_key = replace(
            computation_key,
            arg_bindings=tuple(
                replace(
                    binding,
                    version_id=rewrite(binding.version_id),
                )
                for binding in computation_key.arg_bindings
            ),
        )
    lineage = replace(
        write.lineage,
        source_version_ids=tuple(
            rewrite(item) for item in write.lineage.source_version_ids
        ),
        object_roles=tuple(
            replace(
                role,
                source_version_ids=tuple(
                    rewrite(item) for item in role.source_version_ids
                ),
            )
            for role in write.lineage.object_roles
        ),
    )
    return replace(
        write,
        previous_version_id=rewrite(write.previous_version_id),
        source_version_ids=tuple(
            rewrite(item) for item in write.source_version_ids
        ),
        computation_key=computation_key,
        lineage=lineage,
    )


def _plan_paths(plans: Sequence[StepPlan]) -> frozenset[str]:
    paths: set[str] = set()
    for plan in plans:
        for invocation in plan.invocations:
            for value in invocation.inputs.values():
                if isinstance(value, tuple):
                    paths.update(value)
                else:
                    paths.add(value)
            paths.update(invocation.outputs.values())
        paths.update(plan.promote_outputs)
        paths.update(plan.promote_outputs.values())
    return frozenset(paths)


def _runtime_path_for_write(
    plans: Sequence[StepPlan],
    write: StateWriteProvenance,
) -> str | None:
    for plan in plans:
        if plan.step_id != write.step_id:
            continue
        for invocation in plan.invocations:
            source = invocation.outputs.get(write.output_key)
            if source is None:
                source = invocation.outputs.get(
                    write.output_key.rsplit(".", 1)[-1]
                )
            if source is None:
                continue
            return plan.promote_outputs.get(source, source)
    return None


def _apply_missing_declarations(
    context: RuntimeContext,
    declarations: Sequence[ContextDeclaration],
) -> None:
    missing: list[ContextDeclaration] = []
    for declaration in declarations:
        try:
            path = declaration.path
            parsed_scope = context.get_scope(declaration.scope_id)
            from shuxueshuo_server.solver.runtime.models import ContextPath

            parsed = ContextPath.parse(path)
            if parsed.key in parsed_scope.container(parsed.container):
                continue
        except (KeyError, ValueError):
            pass
        missing.append(declaration)
    if not missing:
        return
    validator = DeclarationValidator()
    validator.validate_declarations(context, missing)
    context.apply_declarations(missing)


def _actual_form(
    expected_form: str | None,
    free_symbols: tuple[str, ...],
) -> str:
    if expected_form in {"open_expression", "closed_value"}:
        return "open_expression" if free_symbols else "closed_value"
    return "open_state" if free_symbols else "closed_state"


def _issue(
    call_id: str,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> PlannerRetryIssue:
    return PlannerRetryIssue(
        layer="trial_execution",
        code=code,
        step_id=call_id,
        repair_target="call",
        preserve_policy="preserve_graph",
        message=message,
        details=details,
    )


def _runtime_result(
    context: RuntimeContext,
    *,
    write: StateWriteProvenance,
    value: Any,
) -> StepIntentRuntimeResult:
    try:
        projected = context.to_answer_value(value)
    except Exception as exc:
        return StepIntentRuntimeResult(
            step_id=write.step_id,
            scope_id=write.scope_id,
            capability_id=write.capability_id,
            produced_handle=write.produced_handle,
            output_key=write.output_key,
            runtime_type=write.runtime_type,
            value_omitted_reason=(
                f"unsupported_transaction_snapshot:{type(exc).__name__}"
            ),
        )
    return StepIntentRuntimeResult(
        step_id=write.step_id,
        scope_id=write.scope_id,
        capability_id=write.capability_id,
        produced_handle=write.produced_handle,
        output_key=write.output_key,
        runtime_type=write.runtime_type,
        value=projected,
    )


def _default_executor_factory(
    inputs: PlannerInputs,
    context: RuntimeContext,
) -> InvocationExecutor:
    return InvocationExecutor(
        inputs.method_specs,
        methods=default_stateless_registry(),
        kernel=context.kernel,
    )


def _payload(value: Any) -> Any:
    if hasattr(value, "to_payload"):
        return value.to_payload()
    if isinstance(value, Mapping):
        return {str(key): _payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_payload(item) for item in value]
    return value


__all__ = [
    "CompiledFunctionalCall",
    "CompiledPublicReturn",
    "FunctionalCallBridgeCompiler",
    "FunctionalCallExecutionResult",
    "FunctionalCallPreparationService",
    "FunctionalRuntimeWriteCommitter",
    "FunctionalTransactionBehaviorDelta",
    "FunctionalTransactionalExecutionReport",
    "FunctionalTransactionalInterpreter",
    "PreparedFunctionalCall",
    "failed_execution_report",
]
