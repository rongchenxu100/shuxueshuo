"""Transactional execution for canonical Functional calls.

C1 keeps this interpreter as an execution shadow. C2 can promote its actual
call results, StateVersions, goal closure, Context and retry projection to the
Functional authority while legacy replay remains available as a comparison
oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Literal, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.runtime.answer_goal_verifier import (
    AnswerGoalVerificationReport,
    AnswerGoalVerifier,
    FunctionalGoalVerificationContext,
)
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
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalArgBinding,
    FunctionalBindingContext,
    audit_compiled_functional_arg_consumption,
    project_functional_arg_bindings_from_context,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
)
from shuxueshuo_server.solver.runtime.functional_symbol_identity import (
    runtime_free_symbol_ids,
    runtime_free_symbols,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCallReconciliation,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalReturnAllocation,
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
    MethodInvocation,
    PlannerOutput,
    StepGoal,
    StepPlan,
    TypedValue,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    RecipeTrialExecutor,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    MathObjectId,
    MathObjectRegistry,
    RuntimeDestinationKey,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    ProjectedFunctionArgBinding,
    StateWriteProvenance,
    StepIntentAcceptedStep,
    StepIntentExecutionDiagnostic,
    StepIntentRuntimeResult,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    FunctionalSymbolicClosureMode,
    SymbolicClosureConfigurationError,
    SymbolicClosureExecutionResult,
    SymbolicClosureRuntimeDriftError,
    closure_failure_code,
    execute_symbolic_closure,
    substitute_symbolic_closure_output,
    validate_symbolic_closure_outputs,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    project_functional_state_writes,
)
from shuxueshuo_server.solver.runtime.student_symbolic_complexity import (
    runtime_free_symbol_names,
)
from shuxueshuo_server.solver.utils import unique_ordered


FunctionalCallTransactionStatus = Literal["verified", "failed"]
FunctionalCallCompileMode = Literal["legacy_bridge", "exact"]
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
    arg_bindings: tuple["PreparedFunctionalArgBinding", ...] = ()


@dataclass(frozen=True)
class PreparedFunctionalArgBinding:
    logical_binding: FunctionalArgBinding
    selected_state_version_id: StateVersionId | None = None
    snapshot_runtime_path: str | None = None
    runtime_value: TypedValue | None = None


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
    replay_plans: tuple[StepPlan, ...] = ()
    binding_consumption_decisions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class FunctionalCallExecutionResult:
    call_id: str
    status: FunctionalCallTransactionStatus
    runtime_results: tuple[StepIntentRuntimeResult, ...] = ()
    state_writes: tuple[StateWriteProvenance, ...] = ()
    committed_versions: tuple[IndexedStateVersion, ...] = ()
    checks: tuple[Any, ...] = ()
    root_issues: tuple[PlannerRetryIssue, ...] = ()
    symbolic_closure: SymbolicClosureExecutionResult | None = None

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
            "symbolic_closure": (
                self.symbolic_closure.to_payload()
                if self.symbolic_closure is not None
                else None
            ),
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
    compiled_calls: tuple[CompiledFunctionalCall, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    known_versions: tuple[IndexedStateVersion, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    @property
    def symbolic_closure_execution_count(self) -> int:
        return sum(
            item.symbolic_closure is not None
            and item.symbolic_closure.status != "not_applicable"
            for item in self.call_results
        )

    @property
    def symbolic_closure_execution_by_capability(self) -> dict[str, int]:
        capabilities = {
            call.call_id: call.capability_id for call in self.graph.calls
        }
        counts: dict[str, int] = {}
        for item in self.call_results:
            if (
                item.symbolic_closure is None
                or item.symbolic_closure.status == "not_applicable"
            ):
                continue
            capability_id = capabilities.get(item.call_id, "<unknown>")
            counts[capability_id] = counts.get(capability_id, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def symbolic_closure_drift_count(self) -> int:
        return sum(
            item.code
            in {
                "symbolic_closure_output_drift",
                "symbolic_closure_output_contract_drift",
            }
            for item in self.compatibility_mismatches
        )

    @property
    def symbolic_closure_drift_by_capability(self) -> dict[str, int]:
        capabilities = {
            call.call_id: call.capability_id for call in self.graph.calls
        }
        counts: dict[str, int] = {}
        for item in self.compatibility_mismatches:
            if item.code not in {
                "symbolic_closure_output_drift",
                "symbolic_closure_output_contract_drift",
            }:
                continue
            capability_id = capabilities.get(item.call_id or "", "<unknown>")
            counts[capability_id] = counts.get(capability_id, 0) + 1
        return dict(sorted(counts.items()))

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
            "binding_consumption_decisions": [
                dict(item)
                for compiled in self.compiled_calls
                for item in compiled.binding_consumption_decisions
            ],
            "symbolic_closure_execution_count": (
                self.symbolic_closure_execution_count
            ),
            "symbolic_closure_drift_count": (
                self.symbolic_closure_drift_count
            ),
            "symbolic_closure_execution_by_capability": (
                self.symbolic_closure_execution_by_capability
            ),
            "symbolic_closure_drift_by_capability": (
                self.symbolic_closure_drift_by_capability
            ),
        }


@dataclass(frozen=True)
class FunctionalTransactionalAttemptResult:
    execution_report: FunctionalTransactionalExecutionReport
    compiled_output: PlannerOutput | None
    diagnostic: StepIntentExecutionDiagnostic
    goal_report: AnswerGoalVerificationReport
    verified_call_ids: frozenset[str]
    failed_call_ids: frozenset[str]
    blocked_call_ids: frozenset[str]
    goal_reachable_call_ids: frozenset[str]
    runtime_results: tuple[StepIntentRuntimeResult, ...]
    state_writes: tuple[StateWriteProvenance, ...]
    root_issues: tuple[PlannerRetryIssue, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "execution_report": self.execution_report.to_payload(),
            "compiled_output_ok": self.compiled_output is not None,
            "diagnostic": self.diagnostic.to_payload(),
            "goal_report": self.goal_report.to_payload(),
            "verified_call_ids": sorted(self.verified_call_ids),
            "failed_call_ids": sorted(self.failed_call_ids),
            "blocked_call_ids": sorted(self.blocked_call_ids),
            "goal_reachable_call_ids": sorted(
                self.goal_reachable_call_ids
            ),
            "runtime_results": [
                item.to_payload() for item in self.runtime_results
            ],
            "state_writes": [
                item.to_payload() for item in self.state_writes
            ],
            "root_issues": [
                item.to_payload() for item in self.root_issues
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
        binding_context = reconciliation.functional_binding_context
        if not isinstance(binding_context, FunctionalBindingContext):
            raise ValueError(
                "planner_configuration_error: "
                "planner.functional_binding_context_incomplete: "
                f"call={call_id}"
            )
        logical_bindings = binding_context.for_call(call_id)
        runtime_bindings = CanonicalRuntimeBindingIndex.from_context(
            runtime_context,
            handle_registry=handle_registry,
            question_goals=inputs.question_goals,
            functional_consumer_identity_mode="authoritative",
        )
        state_reads: list[PreparedFunctionalStateRead] = []
        snapshot_paths: dict[StateVersionId, str] = {}
        for arg_name, values in reconciled.resolved_args.items():
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
                logical_binding = binding_context.binding_for(
                    call_id,
                    arg_name,
                    item_index,
                )
                if logical_binding is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.functional_binding_context_incomplete: "
                        f"call={call_id}, arg={arg_name}[{item_index}]"
                    )
                selection: Literal["exact", "latest"] = (
                    "latest"
                    if logical_binding.selection_policy == "latest"
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
        reads_by_key = {
            (item.arg_name, item.item_index): item
            for item in state_reads
            if ".__support_" not in item.arg_name
        }
        prepared_bindings = tuple(
            PreparedFunctionalArgBinding(
                logical_binding=item,
                selected_state_version_id=(
                    reads_by_key[(item.key.arg_name, item.key.item_index)]
                    .selected_version_id
                    if (item.key.arg_name, item.key.item_index) in reads_by_key
                    else None
                ),
                snapshot_runtime_path=(
                    reads_by_key[(item.key.arg_name, item.key.item_index)]
                    .snapshot_runtime_path
                    if (item.key.arg_name, item.key.item_index) in reads_by_key
                    else None
                ),
                runtime_value=(
                    reads_by_key[(item.key.arg_name, item.key.item_index)]
                    .runtime_value
                    if (item.key.arg_name, item.key.item_index) in reads_by_key
                    else None
                ),
            )
            for item in logical_bindings
        )
        return PreparedFunctionalCall(
            call_id=call_id,
            capability_id=reconciled.capability_id,
            step_ids=projection.step_ids,
            dependency_call_ids=node.dependency_call_ids,
            reconciliation=reconciled,
            required_return_names=tuple(sorted(required_return_names)),
            state_reads=tuple(state_reads),
            arg_bindings=prepared_bindings,
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
            replay_plans=tuple(
                plans_by_id[step_id]
                for step_id in prepared_call.step_ids
            ),
        )


class FunctionalCallCompilerService:
    """Compile one canonical Functional call against the working Context."""

    def __init__(
        self,
        *,
        trial_executor: RecipeTrialExecutor | None = None,
    ) -> None:
        self._trial_executor = trial_executor or RecipeTrialExecutor()

    def compile(
        self,
        prepared_call: PreparedFunctionalCall,
        *,
        reconciliation: FunctionalPlanReconciliationResult,
        runtime_context: RuntimeContext,
        working: WorkingPlannerState,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        capability_catalog: FunctionalCapabilityCatalog,
        committed_state_writes: tuple[StateWriteProvenance, ...] = (),
        committed_calls: tuple[CompiledFunctionalCall, ...] = (),
    ) -> CompiledFunctionalCall:
        projected = reconciliation.projected_draft
        if projected is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_projected_draft_missing"
            )
        step_by_id = {item.step_id: item for item in projected.steps}
        if len(prepared_call.step_ids) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_call_projection_ambiguous: "
                f"call={prepared_call.call_id}, "
                f"steps={list(prepared_call.step_ids)}"
            )
        step = step_by_id.get(prepared_call.step_ids[0])
        if step is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.transactional_projected_step_missing: "
                f"call={prepared_call.call_id}"
            )
        all_projected_writes = project_functional_state_writes(
            reconciliation.plan,
            reconciliation.calls,
        )
        projected_writes = tuple(
            item
            for item in all_projected_writes
            if item.step_id == prepared_call.call_id
        )
        all_projected_dependencies = (
            reconciliation.projected_state_dependencies
        )
        projected_dependencies = tuple(
            item
            for item in all_projected_dependencies
            if item.step_id == prepared_call.call_id
        )
        projected_bindings = project_functional_arg_bindings(
            reconciliation,
            catalog=capability_catalog,
        )
        compiled = self._trial_executor.compile_exact_step(
            step,
            capability_id=prepared_call.capability_id,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=runtime_context,
            question_goals=tuple(inputs.question_goals),
            projected_state_writes=projected_writes,
            available_state_writes=all_projected_writes,
            projected_state_dependencies=projected_dependencies,
            available_state_dependencies=all_projected_dependencies,
            projected_function_arg_bindings=projected_bindings,
            known_state_versions=working.identity_index.all_versions(),
            known_state_writes=committed_state_writes,
            # Call-local public values have no StateVersion, but downstream
            # CallResultRef inputs still need their exact producer binding.
            # Materialized returns are registered only from committed typed
            # StateVersion/StateWriteProvenance so they cannot overwrite an
            # immutable object identity (notably Symbol -> ParameterValue).
            known_runtime_bindings=tuple(
                (
                    returned.expected_write.produced_handle,
                    runtime_path,
                    returned.expected_write.runtime_type,
                    f"step:{call.call_id}",
                )
                for call in committed_calls
                for returned in call.public_returns
                if (
                    returned.expected_write is not None
                    and returned.allocation.allocation_action
                    == "call_local_value"
                )
                for runtime_path in (
                    _runtime_path_for_write(
                        call.plans,
                        returned.expected_write,
                    ),
                )
                if runtime_path is not None
            ),
        )
        path_rewrites = _prepared_path_rewrites(prepared_call)
        replay_plans = (compiled.plan,)
        plans = (_rewrite_plan_input_paths(compiled.plan, path_rewrites),)
        binding_consumption_audit = audit_compiled_functional_arg_consumption(
            tuple(item.logical_binding for item in prepared_call.arg_bindings),
            plans,
            expected_runtime_paths={
                item.logical_binding.key: (
                    item.snapshot_runtime_path
                    if item.logical_binding.consumption_mode == "runtime_input"
                    else None
                )
                for item in prepared_call.arg_bindings
            },
        )
        if binding_consumption_audit.mismatches:
            first = binding_consumption_audit.mismatches[0]
            raise ValueError(
                "planner_configuration_error: "
                "planner.functional_runtime_input_mapping_drift: "
                f"call={prepared_call.call_id}, "
                f"arg={first['arg_name']}[{first['item_index']}], "
                f"target={first['runtime_target']}, "
                f"details={first['details']}"
            )
        writes = {
            item.return_name: item
            for item in compiled.state_write_provenance
            if item.return_name is not None
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
        referenced_paths = _plan_paths(plans)
        declarations = tuple(
            item
            for item in compiled.declarations
            if item.path in referenced_paths
        )
        return CompiledFunctionalCall(
            call_id=prepared_call.call_id,
            step_ids=prepared_call.step_ids,
            declarations=declarations,
            plans=plans,
            public_returns=public_returns,
            replay_plans=replay_plans,
            binding_consumption_decisions=(
                binding_consumption_audit.decisions
            ),
        )


def project_functional_arg_bindings(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[ProjectedFunctionArgBinding, ...]:
    """Project C3 wire bindings into the StepIntent compatibility sidecar."""
    del catalog
    context = reconciliation.functional_binding_context
    if not isinstance(context, FunctionalBindingContext):
        raise ValueError(
            "planner_configuration_error: "
            "planner.functional_binding_context_incomplete"
        )
    return project_functional_arg_bindings_from_context(
        reconciliation.calls,
        context,
    )


def _prepared_path_rewrites(
    prepared_call: PreparedFunctionalCall,
) -> dict[str, str]:
    rewrites: dict[str, str] = {}
    for read in prepared_call.state_reads:
        existing = rewrites.get(read.original_runtime_path)
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
        rewrites[read.original_runtime_path] = read.snapshot_runtime_path
    return rewrites


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
        object_registry: MathObjectRegistry,
        runtime_symbol_bindings: Mapping[sp.Symbol, MathObjectId],
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
            free_symbol_ids = runtime_free_symbol_ids(
                typed.value,
                context=branch,
                registry=object_registry,
                declared_runtime_symbols=runtime_symbol_bindings,
                ignored_symbol_names=write.closure_ignored_symbol_names,
            )
            expected_form = expectations.get(returned.return_name)
            actual_form = _actual_form(expected_form, free_symbols)
            if (
                expected_form in {"closed_state", "closed_value"}
                and free_symbol_ids
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
                and len(free_symbol_ids)
                > returned.max_independent_free_parameters
            ):
                issues.append(
                    _issue(
                        compiled.call_id,
                        "functional.return_complexity_exceeded",
                        f"return {returned.return_name} retains "
                        f"{len(free_symbol_ids)} free symbols; maximum is "
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
                free_symbol_ids=free_symbol_ids,
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
                    free_symbol_ids=free_symbol_ids,
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
        symbolic_closure_mode: FunctionalSymbolicClosureMode = "disabled",
    ) -> None:
        self._executor_factory = (
            executor_factory or _default_executor_factory
        )
        self._symbolic_closure_mode = symbolic_closure_mode

    def execute(
        self,
        *,
        raw_plan: FunctionalPlan,
        reconciliation: FunctionalPlanReconciliationResult,
        legacy_output: PlannerOutput | None,
        legacy_diagnostic: StepIntentExecutionDiagnostic | None,
        runtime_context: RuntimeContext,
        parent_context: PlannerStateContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        goal_verification_report: Any | None = None,
        compile_mode: FunctionalCallCompileMode = "legacy_bridge",
        compare_legacy: bool = True,
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
        legacy_bridge = FunctionalCallBridgeCompiler()
        exact_compiler = FunctionalCallCompilerService()
        committer = FunctionalRuntimeWriteCommitter()
        object_registry = MathObjectRegistry.from_sources(
            handle_registry,
            math_objects=parent_context.state.math_objects,
        )
        results: list[FunctionalCallExecutionResult] = []
        compiled_calls: list[CompiledFunctionalCall] = []
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
            closure_result: SymbolicClosureExecutionResult | None = None
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
                if compile_mode == "exact":
                    compiled = exact_compiler.compile(
                        prepared,
                        reconciliation=reconciliation,
                        runtime_context=current_context,
                        working=working,
                        inputs=inputs,
                        handle_registry=handle_registry,
                        capability_catalog=capability_catalog,
                        committed_state_writes=tuple(
                            write
                            for result in results
                            if result.status == "verified"
                            for write in result.state_writes
                        ),
                        committed_calls=tuple(compiled_calls),
                    )
                else:
                    if legacy_output is None or legacy_diagnostic is None:
                        raise ValueError(
                            "planner_configuration_error: legacy bridge "
                            "requires a complete PlannerOutput and diagnostic"
                        )
                    compiled = legacy_bridge.compile(
                        prepared,
                        output=legacy_output,
                        diagnostic=legacy_diagnostic,
                        capability_catalog=capability_catalog,
                    )
                branch = current_context.fork()
                _apply_missing_declarations(branch, compiled.declarations)
                for plan in compiled.plans:
                    branch.ensure_step_scope(plan.step_id, plan.scope)
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
                capability = capability_catalog.get(
                    prepared.capability_id
                )
                symbolic_spec = (
                    getattr(capability.source, "symbolic_closure", None)
                    if capability is not None
                    else None
                )
                if (
                    self._symbolic_closure_mode != "disabled"
                    and symbolic_spec is not None
                ):
                    invocation = _symbolic_closure_invocation(
                        compiled,
                        method_id=getattr(
                            capability.source,
                            "method_id",
                            None,
                        ),
                    )
                    closure_args = executor.resolve_inputs(
                        branch,
                        invocation,
                    )
                    pre_execution_symbol_bindings = (
                        _merge_runtime_symbol_bindings(
                            _context_runtime_symbol_bindings(
                                branch,
                                registry=object_registry,
                            ),
                            _prepared_runtime_symbol_bindings(
                                prepared,
                                working=working,
                            ),
                        )
                    )
                    target_binding = _prepared_binding(
                        prepared,
                        symbolic_spec.target_arg,
                    )
                    closure_result = execute_symbolic_closure(
                        symbolic_spec,
                        args=closure_args,
                        target_object_id=(
                            _binding_math_object_id(target_binding)
                            if target_binding is not None
                            else None
                        ),
                        runtime_symbol_bindings=(
                            pre_execution_symbol_bindings
                        ),
                        kernel=branch.kernel,
                        target_binding=(
                            target_binding.logical_binding.semantic_role
                            if target_binding is not None
                            else None
                        ),
                        arg_object_ids=(
                            _prepared_runtime_arg_object_ids(
                                prepared,
                                runtime_args=closure_args,
                            )
                        ),
                    )
                    if (
                        self._symbolic_closure_mode == "authoritative"
                        and closure_result.status
                        not in {"not_applicable", "unique"}
                    ):
                        issue = _issue(
                            call_id,
                            closure_failure_code(closure_result.status),
                            "symbolic closure did not determine a unique "
                            f"target: status={closure_result.status}, "
                            f"branches={closure_result.branch_count}",
                            details=closure_result.to_payload(),
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
                                symbolic_closure=closure_result,
                            )
                        )
                        continue
                execution = executor.execute_plan(
                    branch,
                    list(compiled.plans),
                )
                call_symbol_bindings = _declared_runtime_symbol_bindings(
                    compiled,
                    branch=branch,
                )
                effective_symbol_bindings = _merge_runtime_symbol_bindings(
                    _merge_runtime_symbol_bindings(
                        _context_runtime_symbol_bindings(
                            branch,
                            registry=object_registry,
                        ),
                        _prepared_runtime_symbol_bindings(
                            prepared,
                            working=working,
                        ),
                    ),
                    call_symbol_bindings,
                )
                if (
                    closure_result is not None
                    and closure_result.status == "unique"
                ):
                    closure_mismatches = _apply_symbolic_closure_returns(
                        compiled,
                        branch=branch,
                        result=closure_result,
                        mode=self._symbolic_closure_mode,
                    )
                    mismatches.extend(closure_mismatches)
                    if self._symbolic_closure_mode == "authoritative":
                        closure_checks = (
                            _validate_compiled_symbolic_closure_returns(
                                compiled,
                                branch=branch,
                                result=closure_result,
                            )
                        )
                        failed_closure_checks = tuple(
                            item.name
                            for item in closure_checks
                            if not item.ok
                        )
                        if failed_closure_checks:
                            raise SymbolicClosureRuntimeDriftError(
                                "rewritten outputs violate closure: "
                                + ", ".join(failed_closure_checks)
                            )
                        execution.checks.extend(closure_checks)
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
                    object_registry=object_registry,
                    runtime_symbol_bindings=effective_symbol_bindings,
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
                            symbolic_closure=closure_result,
                        )
                    )
                    continue
                if (
                    self._symbolic_closure_mode == "authoritative"
                    and closure_result is not None
                    and closure_result.status == "unique"
                    and closure_result.provenance is not None
                ):
                    writes = tuple(
                        replace(
                            write,
                            symbolic_closure_provenance=(
                                closure_result.provenance
                                if write.return_name
                                in closure_result.affected_returns
                                else write.symbolic_closure_provenance
                            ),
                        )
                        for write in writes
                    )
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
                    runtime_symbol_bindings=(
                        _version_runtime_symbol_bindings(
                            versions,
                            runtime_values=runtime_values,
                            call_bindings=effective_symbol_bindings,
                        )
                    ),
                )
                current_context = branch
                compiled_calls.append(compiled)
                results.append(
                    FunctionalCallExecutionResult(
                        call_id,
                        "verified",
                        runtime_results=runtime_results,
                        state_writes=writes,
                        committed_versions=versions,
                        checks=tuple(execution.checks),
                        symbolic_closure=closure_result,
                    )
                )
            except Exception as exc:
                if isinstance(exc, SymbolicClosureRuntimeDriftError):
                    issue_code = "planner.contract_runtime_symbol_drift"
                elif isinstance(exc, SymbolicClosureConfigurationError):
                    issue_code = "planner.symbolic_closure_spec_invalid"
                elif "planner_configuration_error" in str(exc):
                    issue_code = "planner.transactional_configuration_error"
                else:
                    issue_code = "functional.transactional_call_failed"
                issue = _issue(
                    call_id,
                    issue_code,
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
                        symbolic_closure=closure_result,
                    )
                )

        if compare_legacy and legacy_diagnostic is not None:
            compatibility, deltas = _compare_with_legacy(
                graph,
                working=working,
                reconciliation=reconciliation,
                diagnostic=legacy_diagnostic,
                call_results=tuple(results),
            )
        else:
            compatibility, deltas = (), ()
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
            compiled_calls=tuple(compiled_calls),
            known_versions=working.identity_index.all_versions(),
        )

    def execute_attempt(
        self,
        *,
        raw_plan: FunctionalPlan,
        reconciliation: FunctionalPlanReconciliationResult,
        legacy_output: PlannerOutput | None,
        legacy_diagnostic: StepIntentExecutionDiagnostic | None,
        runtime_context: RuntimeContext,
        parent_context: PlannerStateContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        problem_payload: Mapping[str, Any],
        compare_legacy: bool,
    ) -> FunctionalTransactionalAttemptResult:
        """Execute C2 and derive goal, output and retry facts from runtime."""
        report = self.execute(
            raw_plan=raw_plan,
            reconciliation=reconciliation,
            legacy_output=legacy_output,
            legacy_diagnostic=legacy_diagnostic,
            runtime_context=runtime_context,
            parent_context=parent_context,
            inputs=inputs,
            handle_registry=handle_registry,
            compile_mode="exact",
            compare_legacy=compare_legacy,
        )
        verified_call_ids = frozenset(
            item.call_id
            for item in report.call_states
            if item.status == "verified"
        )
        failed_call_ids = frozenset(
            item.call_id
            for item in report.call_states
            if item.status == "failed"
        )
        blocked_call_ids = frozenset(
            item.call_id
            for item in report.call_states
            if item.status == "blocked_by_dependency"
        )
        runtime_results = tuple(
            result
            for call in report.call_results
            if call.status == "verified"
            for result in call.runtime_results
        )
        state_writes = tuple(
            write
            for call in report.call_results
            if call.status == "verified"
            for write in call.state_writes
        )
        diagnostic = _transactional_diagnostic(
            report,
            reconciliation=reconciliation,
            runtime_results=runtime_results,
            state_writes=state_writes,
        )
        projected_writes = project_functional_state_writes(
            reconciliation.plan,
            reconciliation.calls,
        )
        read_index = FunctionalStateReadIndex.from_sources(
            handle_registry=handle_registry,
            mode="authoritative",
            projected_state_writes=projected_writes,
            projected_state_dependencies=(
                reconciliation.projected_state_dependencies
            ),
            state_write_provenance=state_writes,
            known_state_versions=report.known_versions,
        )
        answer_version_ids = _transactional_answer_version_ids(
            report.graph,
            reconciliation=reconciliation,
            committed_version_ids=frozenset(
                item.version_id for item in report.committed_versions
            ),
            projected_writes=projected_writes,
        )
        goal_context = FunctionalGoalVerificationContext(
            logical_graph=report.graph,
            state_read_index=read_index,
            runtime_writes_by_version={
                item.selected_version_id: item
                for item in state_writes
                if item.selected_version_id is not None
            },
            answer_version_ids=answer_version_ids,
            verified_call_ids=verified_call_ids,
        )
        goal_report = AnswerGoalVerifier().verify_report(
            reconciliation.projected_draft,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            diagnostic=diagnostic,
            family_spec=inputs.family_spec,
            functional_context=goal_context,
        )
        goal_reachable_call_ids = _passed_goal_reachable_calls(
            report.graph,
            goal_report,
        )
        required_goal_call_ids = _goal_dependency_closure(
            report.graph,
            {
                item.producer_step_id
                for item in goal_report.goals
                if item.producer_step_id is not None
            },
        )
        all_required_goals_passed = bool(goal_report.goals) and all(
            item.status == "passed" for item in goal_report.goals
        )
        all_goal_calls_verified = (
            goal_reachable_call_ids <= verified_call_ids
        )
        root_issues = _unique_issues(
            (
                *(
                    issue
                    for call in report.call_results
                    if call.status == "failed"
                    for issue in call.root_issues
                    if (
                        call.call_id in required_goal_call_ids
                        or _configuration_issue(issue)
                    )
                ),
                *goal_report.issues,
                *(
                    _issue(
                        mismatch.call_id,
                        "planner.transactional_authority_mismatch",
                        (
                            "transactional authority mismatch: "
                            f"{mismatch.code}"
                        ),
                        details={"mismatch": mismatch.to_payload()},
                    )
                    for mismatch in report.compatibility_mismatches
                ),
            )
        )
        compiled_output = None
        if (
            all_required_goals_passed
            and all_goal_calls_verified
            and not report.compatibility_mismatches
        ):
            try:
                compiled_output = _aggregate_transactional_output(
                    report,
                    goal_reachable_call_ids=goal_reachable_call_ids,
                    reconciliation=reconciliation,
                    state_writes=state_writes,
                    inputs=inputs,
                    handle_registry=handle_registry,
                )
            except Exception as exc:
                root_issues = _unique_issues(
                    (
                        *root_issues,
                        _issue(
                            None,
                            "planner.transactional_aggregate_output_failed",
                            f"{type(exc).__name__}: {exc}",
                        ),
                    )
                )
        report = replace(
            report,
            goal_verification=goal_report.to_payload(),
        )
        return FunctionalTransactionalAttemptResult(
            execution_report=report,
            compiled_output=compiled_output,
            diagnostic=diagnostic,
            goal_report=goal_report,
            verified_call_ids=verified_call_ids,
            failed_call_ids=failed_call_ids,
            blocked_call_ids=blocked_call_ids,
            goal_reachable_call_ids=goal_reachable_call_ids,
            runtime_results=runtime_results,
            state_writes=state_writes,
            root_issues=root_issues,
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


def _declared_runtime_symbol_bindings(
    compiled: CompiledFunctionalCall,
    *,
    branch: RuntimeContext,
) -> dict[sp.Symbol, MathObjectId]:
    """Bind method-created Symbols through declared public return identity."""

    result: dict[sp.Symbol, MathObjectId] = {}
    for returned in compiled.public_returns:
        write = returned.expected_write
        if (
            write is None
            or write.runtime_type != "Symbol"
            or write.math_object_id is None
        ):
            continue
        path = (
            write.runtime_destination_key.runtime_path
            if write.runtime_destination_key is not None
            else None
        ) or _runtime_path_for_write(compiled.plans, write)
        if path is None:
            continue
        try:
            value = branch.read_path(
                path,
                from_scope_id=write.scope_id,
                expected_type="Symbol",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            continue
        if not isinstance(value, sp.Symbol):
            continue
        existing = result.get(value)
        if existing is not None and existing != write.math_object_id:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={value} has multiple declared identities"
            )
        result[value] = write.math_object_id
    return result


def _merge_runtime_symbol_bindings(
    existing: Mapping[sp.Symbol, MathObjectId],
    incoming: Mapping[sp.Symbol, MathObjectId],
) -> dict[sp.Symbol, MathObjectId]:
    result = dict(existing)
    for symbol, object_id in incoming.items():
        previous = result.get(symbol)
        if previous is not None and previous != object_id:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={symbol} has conflicting identities"
            )
        result[symbol] = object_id
    return result


def _prepared_runtime_symbol_bindings(
    prepared: PreparedFunctionalCall,
    *,
    working: WorkingPlannerState,
) -> dict[sp.Symbol, MathObjectId]:
    result: dict[sp.Symbol, MathObjectId] = {}
    for read in prepared.state_reads:
        bindings = working.runtime_version_symbol_bindings.get(
            read.selected_version_id,
            {},
        )
        result = _merge_runtime_symbol_bindings(result, bindings)
    return result


def _prepared_binding(
    prepared: PreparedFunctionalCall,
    arg_name: str,
) -> PreparedFunctionalArgBinding | None:
    matches = tuple(
        item
        for item in prepared.arg_bindings
        if item.logical_binding.key.arg_name == arg_name
    )
    if len(matches) > 1:
        raise ValueError(
            "planner_configuration_error: "
            "planner.functional_binding_context_incomplete: "
            f"call={prepared.call_id}, arg={arg_name}, cardinality=many"
        )
    return matches[0] if matches else None


def _binding_math_object_id(
    binding: PreparedFunctionalArgBinding,
) -> MathObjectId | None:
    if binding.selected_state_version_id is not None:
        return (
            binding.selected_state_version_id.slot_id.logical_key.object_id
        )
    source = binding.logical_binding.source
    if source.math_object_id is not None:
        return source.math_object_id
    if source.state_version_id is not None:
        return source.state_version_id.slot_id.logical_key.object_id
    return None


def _prepared_runtime_arg_object_ids(
    prepared: PreparedFunctionalCall,
    *,
    runtime_args: Mapping[str, Any],
) -> dict[str, tuple[MathObjectId, ...]]:
    result: dict[str, list[tuple[int, MathObjectId]]] = {}
    for item in prepared.arg_bindings:
        object_id = _binding_math_object_id(item)
        if object_id is None:
            continue
        targets = tuple(
            dict.fromkeys(
                (
                    item.logical_binding.key.arg_name,
                    *item.logical_binding.runtime_input_targets,
                )
            )
        )
        for target in targets:
            if target not in runtime_args:
                continue
            result.setdefault(target, []).append(
                (item.logical_binding.key.item_index, object_id)
            )
    return {
        target: tuple(
            object_id
            for _index, object_id in sorted(
                values,
                key=lambda pair: pair[0],
            )
        )
        for target, values in result.items()
    }


def _symbolic_closure_invocation(
    compiled: CompiledFunctionalCall,
    *,
    method_id: str | None,
) -> MethodInvocation:
    matches = tuple(
        invocation
        for plan in compiled.plans
        for invocation in plan.invocations
        if method_id is None or invocation.method_id == method_id
    )
    if len(matches) != 1:
        raise ValueError(
            "planner_configuration_error: "
            "planner.symbolic_closure_spec_invalid: "
            f"call={compiled.call_id}, method={method_id}, "
            f"invocation_count={len(matches)}"
        )
    return matches[0]


def _apply_symbolic_closure_returns(
    compiled: CompiledFunctionalCall,
    *,
    branch: RuntimeContext,
    result: SymbolicClosureExecutionResult,
    mode: FunctionalSymbolicClosureMode,
) -> tuple[FunctionalTransactionShadowMismatch, ...]:
    mismatches: list[FunctionalTransactionShadowMismatch] = []
    for returned in compiled.public_returns:
        if returned.return_name not in result.affected_returns:
            continue
        write = returned.expected_write
        if write is None:
            continue
        path = (
            write.runtime_destination_key.runtime_path
            if write.runtime_destination_key is not None
            else None
        ) or _runtime_path_for_write(compiled.plans, write)
        if path is None:
            raise SymbolicClosureRuntimeDriftError(
                f"return path missing: {returned.return_name}"
            )
        try:
            current = branch.read_path(
                path,
                from_scope_id=write.scope_id,
                expected_type=write.runtime_type,
            )
        except (KeyError, PermissionError, TypeError):
            if returned.required:
                raise
            continue
        normalized = substitute_symbolic_closure_output(
            current,
            result,
            return_name=returned.return_name,
            validate_output=False,
        )
        closure_checks = validate_symbolic_closure_outputs(
            {returned.return_name: normalized},
            result,
        )
        failed_closure_checks = tuple(
            item.name for item in closure_checks if not item.ok
        )
        if failed_closure_checks:
            mismatch = FunctionalTransactionShadowMismatch(
                "symbolic_closure_output_contract_drift",
                compiled.call_id,
                {
                    "return_name": returned.return_name,
                    "checks": [],
                },
                {
                    "return_name": returned.return_name,
                    "checks": list(failed_closure_checks),
                },
            )
            if mode == "shadow":
                mismatches.append(mismatch)
                continue
            if mode == "authoritative":
                raise SymbolicClosureRuntimeDriftError(
                    "companion output does not match closure: "
                    + ", ".join(failed_closure_checks)
                )
        if not _symbolic_values_equivalent(
            current.value,
            normalized.value,
        ):
            mismatch = FunctionalTransactionShadowMismatch(
                "symbolic_closure_output_drift",
                compiled.call_id,
                {
                    "return_name": returned.return_name,
                    "value": _payload(normalized.value),
                },
                {
                    "return_name": returned.return_name,
                    "value": _payload(current.value),
                },
            )
            if mode == "shadow":
                mismatches.append(mismatch)
            elif mode == "authoritative":
                branch.write_path(
                    path,
                    normalized,
                    from_scope_id=write.scope_id,
                    allow_overwrite=True,
                )
    return tuple(mismatches)


def _validate_compiled_symbolic_closure_returns(
    compiled: CompiledFunctionalCall,
    *,
    branch: RuntimeContext,
    result: SymbolicClosureExecutionResult,
) -> tuple[Any, ...]:
    outputs: dict[str, TypedValue] = {}
    for returned in compiled.public_returns:
        if returned.return_name not in result.affected_returns:
            continue
        write = returned.expected_write
        if write is None:
            continue
        path = (
            write.runtime_destination_key.runtime_path
            if write.runtime_destination_key is not None
            else None
        ) or _runtime_path_for_write(compiled.plans, write)
        if path is None:
            raise SymbolicClosureRuntimeDriftError(
                f"return path missing: {returned.return_name}"
            )
        try:
            outputs[returned.return_name] = branch.read_path(
                path,
                from_scope_id=write.scope_id,
                expected_type=write.runtime_type,
            )
        except (KeyError, PermissionError, TypeError):
            if returned.required:
                raise
    return validate_symbolic_closure_outputs(outputs, result)


def _symbolic_values_equivalent(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return False
        return all(
            _symbolic_values_equivalent(left[key], right[key])
            for key in left
        )
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(
            _symbolic_values_equivalent(a, b)
            for a, b in zip(left, right, strict=True)
        )
    try:
        return sp.simplify(sp.sympify(left) - sp.sympify(right)) == 0
    except (TypeError, ValueError, sp.SympifyError):
        return left == right


def _context_runtime_symbol_bindings(
    context: RuntimeContext,
    *,
    registry: MathObjectRegistry,
) -> dict[sp.Symbol, MathObjectId]:
    result: dict[sp.Symbol, MathObjectId] = {}
    for name, symbol in context.symbols.items():
        object_id = registry.resolve(name)
        if object_id is None or object_id.kind != "symbol":
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={name}"
            )
        result[symbol] = object_id
    return result


def _version_runtime_symbol_bindings(
    versions: Sequence[IndexedStateVersion],
    *,
    runtime_values: Mapping[StateVersionId, TypedValue],
    call_bindings: Mapping[sp.Symbol, MathObjectId],
) -> dict[StateVersionId, dict[sp.Symbol, MathObjectId]]:
    result: dict[StateVersionId, dict[sp.Symbol, MathObjectId]] = {}
    for version in versions:
        value = runtime_values.get(version.version_id)
        if value is None:
            continue
        symbols = runtime_free_symbols(value.value)
        bindings = {
            symbol: call_bindings[symbol]
            for symbol in symbols
            if (
                symbol in call_bindings
                and call_bindings[symbol] in version.free_symbol_ids
            )
        }
        if set(bindings.values()) != set(version.free_symbol_ids):
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"version={version.version_id.to_payload()}, "
                "expected="
                f"{[item.to_payload() for item in version.free_symbol_ids]}, "
                "actual="
                f"{[item.to_payload() for item in bindings.values()]}"
            )
        result[version.version_id] = bindings
    return result


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


def _transactional_diagnostic(
    report: FunctionalTransactionalExecutionReport,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    runtime_results: tuple[StepIntentRuntimeResult, ...],
    state_writes: tuple[StateWriteProvenance, ...],
) -> StepIntentExecutionDiagnostic:
    calls = {item.call_id: item for item in reconciliation.calls}
    compiled = {item.call_id: item for item in report.compiled_calls}
    accepted = tuple(
        StepIntentAcceptedStep(
            step_id=call_id,
            scope_id=calls[call_id].scope_id,
            capability_id=calls[call_id].capability_id,
            method_ids=tuple(
                invocation.method_id
                for plan in compiled[call_id].plans
                for invocation in plan.invocations
            ),
            produced_handles=tuple(
                write.produced_handle
                for write in state_writes
                if write.step_id == call_id
            ),
        )
        for call_id in report.graph.canonical_order
        if call_id in compiled
        and any(
            item.call_id == call_id and item.status == "verified"
            for item in report.call_states
        )
    )
    failed = any(
        item.status in {"failed", "blocked_by_dependency"}
        for item in report.call_states
        if item.call_id in report.graph.canonical_order
    )
    answer_alias_writes = tuple(
        replace(
            source,
            produced_handle=binding.answer_handle,
        )
        for binding in report.graph.answer_bindings
        for source in (
            next(
                (
                    item
                    for item in state_writes
                    if (
                        item.step_id == binding.producer_call_id
                        and item.return_name == binding.return_name
                    )
                ),
                None,
            ),
        )
        if source is not None
    )
    return StepIntentExecutionDiagnostic(
        ok=not failed,
        accepted_prefix=accepted,
        state_write_provenance=(
            *state_writes,
            *answer_alias_writes,
        ),
        runtime_results=runtime_results,
    )


def _transactional_answer_version_ids(
    graph: LogicalFunctionalGraph,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    committed_version_ids: frozenset[StateVersionId],
    projected_writes: Sequence[Any],
) -> dict[str, StateVersionId]:
    calls = {item.call_id: item for item in reconciliation.calls}
    result = {
        item.produced_handle: item.selected_version_id
        for item in projected_writes
        if (
            item.produced_handle.startswith("answer:")
            and item.selected_version_id in committed_version_ids
        )
    }
    for binding in graph.answer_bindings:
        call = calls.get(binding.producer_call_id)
        allocation = next(
            (
                item
                for item in (call.returns if call is not None else ())
                if item.return_name == binding.return_name
            ),
            None,
        )
        if (
            allocation is not None
            and allocation.selected_version_id in committed_version_ids
        ):
            result[binding.answer_handle] = allocation.selected_version_id
    return result


def _passed_goal_reachable_calls(
    graph: LogicalFunctionalGraph,
    report: AnswerGoalVerificationReport,
) -> frozenset[str]:
    roots = {
        item.producer_step_id
        for item in report.goals
        if item.status == "passed"
        and item.producer_step_id is not None
    }
    return _goal_dependency_closure(graph, roots)


def _goal_dependency_closure(
    graph: LogicalFunctionalGraph,
    roots: set[str],
) -> frozenset[str]:
    dependencies = {
        item.call_id: frozenset(item.dependency_call_ids)
        for item in graph.calls
    }
    reachable: set[str] = set()
    stack = list(roots)
    while stack:
        call_id = stack.pop()
        if call_id in reachable:
            continue
        reachable.add(call_id)
        stack.extend(dependencies.get(call_id, ()))
    return frozenset(reachable)


def _configuration_issue(issue: PlannerRetryIssue) -> bool:
    return (
        issue.code.startswith("planner.")
        or "planner_configuration_error" in issue.message
    )


def _aggregate_transactional_output(
    report: FunctionalTransactionalExecutionReport,
    *,
    goal_reachable_call_ids: frozenset[str],
    reconciliation: FunctionalPlanReconciliationResult,
    state_writes: tuple[StateWriteProvenance, ...],
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
) -> PlannerOutput:
    compiled = {
        item.call_id: item for item in report.compiled_calls
    }
    declarations_by_path: dict[str, ContextDeclaration] = {}
    plans_by_step: dict[str, StepPlan] = {}
    for call_id in report.graph.canonical_order:
        if call_id not in goal_reachable_call_ids:
            continue
        call = compiled.get(call_id)
        if call is None:
            raise ValueError(
                "planner_configuration_error: verified goal call has no "
                f"compiled fragment: {call_id}"
            )
        for declaration in call.declarations:
            declarations_by_path.setdefault(
                declaration.path,
                declaration,
            )
        for plan in call.replay_plans or call.plans:
            existing_plan = plans_by_step.get(plan.step_id)
            if existing_plan is not None and existing_plan != plan:
                raise ValueError(
                    "planner_configuration_error: conflicting transactional "
                    f"StepPlan: {plan.step_id}"
                )
            plans_by_step[plan.step_id] = plan
    plans = tuple(
        plans_by_step[step_id]
        for call_id in report.graph.canonical_order
        if call_id in goal_reachable_call_ids
        for step_id in (
            compiled[call_id].step_ids
            if call_id in compiled
            else ()
        )
        if step_id in plans_by_step
    )
    plans = (
        *plans,
        *_transactional_answer_projection_plans(
            report,
            compiled=compiled,
            goal_reachable_call_ids=goal_reachable_call_ids,
            question_goals=tuple(inputs.question_goals),
        ),
    )
    projected_writes = tuple(
        item
        for item in project_functional_state_writes(
            reconciliation.plan,
            reconciliation.calls,
        )
        if item.step_id in goal_reachable_call_ids
    )
    goal_writes = tuple(
        item
        for item in state_writes
        if item.step_id in goal_reachable_call_ids
    )
    CanonicalDraftFinalizer().finalize_compiled_state_writes(
        projected_state_writes=projected_writes,
        provenance=goal_writes,
        plans=plans,
        question_goals=tuple(inputs.question_goals),
        handle_registry=handle_registry,
    )
    return PlannerOutput(
        context_declarations=list(declarations_by_path.values()),
        step_plans=list(plans),
    )


def _transactional_answer_projection_plans(
    report: FunctionalTransactionalExecutionReport,
    *,
    compiled: Mapping[str, CompiledFunctionalCall],
    goal_reachable_call_ids: frozenset[str],
    question_goals: tuple[Any, ...],
) -> tuple[StepPlan, ...]:
    """Project a committed state to every required QuestionGoal destination.

    A public return may be both a reusable object state and an answer.  The
    bridge can physically promote a method output only once, so calls hoisted
    above an answer scope publish the canonical object path first.  These
    invocation-free plans copy that already committed value into the answer
    scope without introducing another mathematical writer.
    """

    goals_by_handle = {
        f"answer:{goal.id}": goal for goal in question_goals
    }
    result: list[StepPlan] = []
    seen_targets: set[str] = set()
    for binding in report.graph.answer_bindings:
        if binding.producer_call_id not in goal_reachable_call_ids:
            continue
        goal = goals_by_handle.get(binding.answer_handle)
        call = compiled.get(binding.producer_call_id)
        if goal is None or call is None:
            raise ValueError(
                "planner_configuration_error: transactional answer "
                f"projection unresolved: {binding.answer_handle}"
            )
        returned = next(
            (
                item
                for item in call.public_returns
                if item.return_name == binding.return_name
            ),
            None,
        )
        if returned is None or returned.expected_write is None:
            raise ValueError(
                "planner_configuration_error: transactional answer return "
                f"unresolved: {binding.answer_handle}"
            )
        source_path = _runtime_path_for_write(
            call.replay_plans or call.plans,
            returned.expected_write,
        )
        if source_path is None:
            raise ValueError(
                "planner_configuration_error: transactional answer source "
                f"unresolved: {binding.answer_handle}"
            )
        target_path = goal.target_path
        if source_path == target_path or target_path in seen_targets:
            continue
        seen_targets.add(target_path)
        step_id = (
            f"{binding.producer_call_id}__answer_projection__{goal.id}"
            .replace(":", "_")
        )
        result.append(
            StepPlan(
                step_id=step_id,
                goal=StepGoal(
                    goal_id=f"functional_answer_projection:{goal.id}",
                    type="functional_answer_projection",
                    target_path=target_path,
                    scope_id=goal.question_id,
                ),
                scope=goal.question_id,
                invocations=[],
                expected_outputs=[target_path],
                promote_outputs={source_path: target_path},
            )
        )
    return tuple(result)


def _unique_issues(
    issues: Sequence[PlannerRetryIssue],
) -> tuple[PlannerRetryIssue, ...]:
    result: list[PlannerRetryIssue] = []
    seen: set[tuple[str, str, str | None]] = set()
    for issue in issues:
        key = (issue.layer, issue.code, issue.step_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return tuple(result)


def _issue(
    call_id: str | None,
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
    "FunctionalCallCompilerService",
    "FunctionalCallExecutionResult",
    "FunctionalCallPreparationService",
    "FunctionalRuntimeWriteCommitter",
    "FunctionalTransactionBehaviorDelta",
    "FunctionalTransactionalAttemptResult",
    "FunctionalTransactionalExecutionReport",
    "FunctionalTransactionalInterpreter",
    "PreparedFunctionalCall",
    "failed_execution_report",
    "project_functional_arg_bindings",
]
