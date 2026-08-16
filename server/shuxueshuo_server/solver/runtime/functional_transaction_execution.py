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

from shuxueshuo_server.solver.contracts import PointRef
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    FunctionalProblemBindingContext,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash

from shuxueshuo_server.solver.runtime.answer_goal_verifier import (
    AnswerGoalVerificationReport,
    AnswerGoalVerifier,
    FunctionalGoalArtifact,
    FunctionalGoalProducer,
    FunctionalGoalVerificationContext,
)
from shuxueshuo_server.solver.runtime.context import RuntimeContext
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
    build_functional_runtime_arg_bindings_from_context,
)
from shuxueshuo_server.solver.runtime.functional_direct_compiler import (
    FunctionalCompileRequest,
    FunctionalDirectCompiler,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FunctionalDiagnosticAuthority,
    StatelessMethodError,
    diagnostic_authority_from_issue,
    method_check_failed,
    normalize_macro_diagnostic_authority,
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
from shuxueshuo_server.solver.runtime.problem_source_provenance import (
    ProblemCallSourceProvenance,
    ProblemSourceProvenanceError,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    ExactCompiledStep,
    FunctionalCapabilityCompiler,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ArgVersionBinding,
    IndexedStateVersion,
    MathObjectId,
    MathObjectRegistry,
    RuntimeDestinationKey,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    ProjectedFunctionArgBinding,
    ProjectedStateDependency,
    ProjectedStateWrite,
    StateWriteProvenance,
    FunctionalAcceptedStep,
    FunctionalExecutionDiagnostic,
    FunctionalRuntimeResult,
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
from shuxueshuo_server.solver.runtime.symbolic_closure_audit import (
    SymbolicClosureWriteAuditRecord,
    audit_symbolic_closure_writes,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationService,
    build_functional_state_write_manifest,
)
from shuxueshuo_server.solver.runtime.student_symbolic_complexity import (
    runtime_free_symbol_names,
)
from shuxueshuo_server.solver.utils import unique_ordered


class SymbolicClosureProvenanceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


FunctionalCallTransactionStatus = Literal["verified", "failed"]


@dataclass(frozen=True)
class PreparedFunctionalCall:
    """One canonical public call with call-time typed state reads."""

    call_id: str
    capability_id: str
    step_ids: tuple[str, ...]
    dependency_call_ids: tuple[str, ...]
    execution_scope_id: str
    reconciliation: FunctionalCallReconciliation
    required_return_names: tuple[str, ...] = ()
    state_reads: tuple["PreparedFunctionalStateRead", ...] = ()
    arg_bindings: tuple["PreparedFunctionalArgBinding", ...] = ()
    parameter_selector_object_ids: frozenset[MathObjectId] = frozenset()


@dataclass(frozen=True)
class PreparedFunctionalArgBinding:
    logical_binding: FunctionalArgBinding
    source_handle: str | None = None
    source_math_object_id: MathObjectId | None = None
    selected_state_version_id: StateVersionId | None = None
    runtime_path: str | None = None
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
class _RuntimeParameterClosure:
    runtime_value: TypedValue
    parameter_versions: tuple[IndexedStateVersion, ...] = ()


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
    compile_mismatches: tuple[dict[str, Any], ...] = ()
    problem_source_provenance: ProblemCallSourceProvenance | None = None


@dataclass(frozen=True)
class FunctionalCallExecutionResult:
    call_id: str
    status: FunctionalCallTransactionStatus
    runtime_results: tuple[FunctionalRuntimeResult, ...] = ()
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
    restored_call_ids: tuple[str, ...] = ()
    runtime_version_values: Mapping[StateVersionId, TypedValue] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    runtime_version_symbol_bindings: Mapping[
        StateVersionId,
        Mapping[Any, MathObjectId],
    ] = field(default_factory=dict, repr=False, compare=False)
    runtime_result_values: Mapping[tuple[str, str], TypedValue] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    runtime_equivalent_aliases: tuple[
        "FunctionalRuntimeEquivalentCallAlias", ...
    ] = ()

    @property
    def functional_compile_count(self) -> int:
        return len(self.compiled_calls)

    @property
    def functional_compile_drift_count(self) -> int:
        return sum(
            item.code == "planner.functional_compile_drift"
            for item in self.compatibility_mismatches
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
        return not self.compatibility_mismatches

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
            "binding_consumption_decisions": [
                dict(item)
                for compiled in self.compiled_calls
                for item in compiled.binding_consumption_decisions
            ],
            "functional_compile_count": self.functional_compile_count,
            "functional_compile_drift_count": (
                self.functional_compile_drift_count
            ),
            "restored_call_ids": list(self.restored_call_ids),
            "restored_call_count": len(self.restored_call_ids),
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
            "runtime_equivalent_aliases": [
                item.to_payload() for item in self.runtime_equivalent_aliases
            ],
        }


@dataclass(frozen=True)
class FunctionalRuntimeEquivalentCallAlias:
    """A duplicate call proven equivalent by its actual typed runtime writes."""

    duplicate_call_id: str
    canonical_call_id: str
    return_aliases: tuple[tuple[str, str], ...]
    selected_version_ids: tuple[StateVersionId, ...]
    comparison_signature: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "duplicate_call_id": self.duplicate_call_id,
            "canonical_call_id": self.canonical_call_id,
            "return_aliases": {
                duplicate: canonical
                for duplicate, canonical in self.return_aliases
            },
            "selected_version_ids": [
                item.to_payload() for item in self.selected_version_ids
            ],
            "comparison_signature": self.comparison_signature,
        }


@dataclass(frozen=True)
class FunctionalTransactionalAttemptResult:
    execution_report: FunctionalTransactionalExecutionReport
    compiled_output: PlannerOutput | None
    diagnostic: FunctionalExecutionDiagnostic
    goal_report: AnswerGoalVerificationReport
    verified_call_ids: frozenset[str]
    failed_call_ids: frozenset[str]
    blocked_call_ids: frozenset[str]
    goal_reachable_call_ids: frozenset[str]
    runtime_results: tuple[FunctionalRuntimeResult, ...]
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


@dataclass(frozen=True)
class FunctionalRestoredCallSeed:
    """In-process runtime values authenticated by an F5-D checkpoint."""

    call_results: tuple[FunctionalCallExecutionResult, ...] = ()
    compiled_calls: tuple[CompiledFunctionalCall, ...] = ()
    runtime_version_values: Mapping[StateVersionId, TypedValue] = field(
        default_factory=dict
    )
    runtime_version_symbol_bindings: Mapping[
        StateVersionId,
        Mapping[Any, MathObjectId],
    ] = field(default_factory=dict)
    runtime_result_values: Mapping[tuple[str, str], TypedValue] = field(
        default_factory=dict
    )
    call_binding_authorities: Mapping[str, str] = field(default_factory=dict)
    call_binding_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    allowed_consumer_goal_delta_ids: tuple[str, ...] = ()

    @property
    def call_ids(self) -> tuple[str, ...]:
        return tuple(item.call_id for item in self.call_results)


class FunctionalRestoredCallBindingError(ValueError):
    """A checkpointed call no longer has the same executable binding."""

    def __init__(
        self,
        call_id: str,
        message: str,
        *,
        code: str = "planner.retry_problem_source_binding_drift",
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.path = f"$.restored_calls[{call_id!r}]"
        self.call_id = call_id
        self.message = message
        self.details = dict(details or {})
        super().__init__(
            "planner_configuration_error: "
            f"{self.code}: {message}"
        )


def rebase_restored_call_seed(
    seed: FunctionalRestoredCallSeed | None,
    reconciliation: FunctionalPlanReconciliationResult,
) -> FunctionalRestoredCallSeed | None:
    """Prove restored calls unchanged, then stamp current Goal provenance.

    Partial F5-F2 execution can omit a failed Goal from a shared scope call's
    consumer set. A repaired complete graph may add that authenticated Goal
    without changing the call's inputs, outputs, placement, or source reads.
    """

    if seed is None or not seed.call_results:
        return seed
    binding_context = reconciliation.functional_problem_binding_context
    if binding_context is None:
        raise ValueError(
            "planner_configuration_error: "
            "planner.retry_problem_source_binding_drift: "
            "restored calls require F5-C binding authority"
        )
    calls = {item.call_id: item for item in reconciliation.calls}
    compiled_by_call = {item.call_id: item for item in seed.compiled_calls}
    allowed_consumer_goal_deltas = set(
        seed.allowed_consumer_goal_delta_ids
    )
    rebased_results: list[FunctionalCallExecutionResult] = []
    rebased_compiled: list[CompiledFunctionalCall] = []
    for result in seed.call_results:
        call_id = result.call_id
        call = calls.get(call_id)
        compiled = compiled_by_call.get(call_id)
        expected_binding = seed.call_binding_authorities.get(call_id)
        if call is None or compiled is None or expected_binding is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.retry_problem_source_binding_drift: "
                f"restored call authority is missing for {call_id}"
            )
        actual_binding = _restorable_call_binding_signature(
            call,
            binding_context=binding_context,
        )
        if actual_binding != expected_binding:
            expected_payload = seed.call_binding_payloads.get(call_id)
            actual_payload = _restorable_call_binding_payload(
                call,
                binding_context=binding_context,
            )
            raise FunctionalRestoredCallBindingError(
                call_id,
                f"typed binding changed for restored call {call_id}",
                details={
                    "expected_signature": expected_binding,
                    "actual_signature": actual_binding,
                    "first_difference": (
                        _first_payload_difference(
                            expected_payload,
                            actual_payload,
                        )
                        if expected_payload is not None
                        else None
                    ),
                    "expected_binding": expected_payload,
                    "actual_binding": actual_payload,
                },
            )
        previous = compiled.problem_source_provenance
        current = binding_context.source_provenance_for_call(call_id)
        source_difference = (
            {"path": "$", "expected": "present", "actual": None}
            if previous is None
            else _restored_problem_source_authority_difference(
                previous,
                current,
            )
        )
        if source_difference is not None:
            raise FunctionalRestoredCallBindingError(
                call_id,
                f"Problem source authority changed for restored call {call_id}",
                details={"first_difference": source_difference},
            )
        assert previous is not None
        unauthorized_goal_deltas = _unauthorized_consumer_goal_deltas(
            previous,
            current,
            allowed_consumer_goal_delta_ids=(
                allowed_consumer_goal_deltas
            ),
        )
        if unauthorized_goal_deltas:
            raise FunctionalRestoredCallBindingError(
                call_id,
                f"Problem Goal consumers changed for restored call {call_id}",
                code="planner.retry_problem_goal_consumer_drift",
                details={
                    "previous_goal_unit_ids": list(previous.goal_unit_ids),
                    "current_goal_unit_ids": list(current.goal_unit_ids),
                    "allowed_consumer_goal_delta_ids": sorted(
                        allowed_consumer_goal_deltas
                    ),
                    "unauthorized_goal_unit_ids": list(
                        unauthorized_goal_deltas
                    ),
                },
            )
        rebased_results.append(
            replace(
                result,
                runtime_results=tuple(
                    replace(item, problem_source_provenance=current)
                    for item in result.runtime_results
                ),
                state_writes=tuple(
                    replace(item, problem_source_provenance=current)
                    for item in result.state_writes
                ),
            )
        )
        rebased_compiled.append(
            replace(
                compiled,
                public_returns=tuple(
                    replace(
                        item,
                        expected_write=(
                            replace(
                                item.expected_write,
                                problem_source_provenance=current,
                            )
                            if item.expected_write is not None
                            else None
                        ),
                    )
                    for item in compiled.public_returns
                ),
                problem_source_provenance=current,
            )
        )
    return replace(
        seed,
        call_results=tuple(rebased_results),
        compiled_calls=tuple(rebased_compiled),
    )


def functional_restored_call_binding_signature(
    reconciliation: FunctionalPlanReconciliationResult,
    call_id: str,
) -> str:
    """Hash the immutable call binding while excluding consumer Goal growth."""

    binding_context = reconciliation.functional_problem_binding_context
    call = next(
        (item for item in reconciliation.calls if item.call_id == call_id),
        None,
    )
    if binding_context is None or call is None:
        raise ValueError(
            "planner_configuration_error: "
            "planner.retry_problem_source_binding_drift: "
            f"missing restored call binding for {call_id}"
        )
    return stable_hash(
        _restorable_call_binding_payload(
            call,
            binding_context=binding_context,
        )
    )


def functional_restored_call_binding_payload(
    reconciliation: FunctionalPlanReconciliationResult,
    call_id: str,
) -> dict[str, Any]:
    """Return the auditable binding payload authenticated by a checkpoint."""

    binding_context = reconciliation.functional_problem_binding_context
    call = next(
        (item for item in reconciliation.calls if item.call_id == call_id),
        None,
    )
    if binding_context is None or call is None:
        raise ValueError(
            "planner_configuration_error: "
            "planner.retry_problem_source_binding_drift: "
            f"missing restored call binding for {call_id}"
        )
    return _restorable_call_binding_payload(
        call,
        binding_context=binding_context,
    )


def _restorable_call_binding_signature(
    call: FunctionalCallReconciliation,
    *,
    binding_context: FunctionalProblemBindingContext,
) -> str:
    return stable_hash(
        _restorable_call_binding_payload(
            call,
            binding_context=binding_context,
        )
    )


def _restorable_call_binding_payload(
    call: FunctionalCallReconciliation,
    *,
    binding_context: FunctionalProblemBindingContext,
) -> dict[str, Any]:
    return {
        "planning_context_id": binding_context.planning_context_id,
        "problem_revision_id": binding_context.problem_revision_id,
        "problem_semantic_hash": binding_context.problem_semantic_hash,
        "call": call.to_payload(),
        "inputs": [
            item.to_payload()
            for item in binding_context.inputs_for_call(call.call_id)
        ],
        "returns": [
            item.to_payload()
            for item in binding_context.returns_for_call(call.call_id)
        ],
    }


def _first_payload_difference(
    expected: Any,
    actual: Any,
    *,
    path: str = "$",
) -> dict[str, Any] | None:
    if type(expected) is not type(actual):
        return {"path": path, "expected": expected, "actual": actual}
    if isinstance(expected, Mapping):
        for key in sorted(set(expected) | set(actual)):
            child_path = f"{path}.{key}"
            if key not in expected:
                return {
                    "path": child_path,
                    "expected": None,
                    "actual": actual[key],
                }
            if key not in actual:
                return {
                    "path": child_path,
                    "expected": expected[key],
                    "actual": None,
                }
            difference = _first_payload_difference(
                expected[key],
                actual[key],
                path=child_path,
            )
            if difference is not None:
                return difference
        return None
    if isinstance(expected, (list, tuple)):
        if len(expected) != len(actual):
            return {
                "path": f"{path}.length",
                "expected": len(expected),
                "actual": len(actual),
            }
        for index, (expected_item, actual_item) in enumerate(
            zip(expected, actual, strict=True)
        ):
            difference = _first_payload_difference(
                expected_item,
                actual_item,
                path=f"{path}[{index}]",
            )
            if difference is not None:
                return difference
        return None
    if expected != actual:
        return {"path": path, "expected": expected, "actual": actual}
    return None


def _restored_problem_source_authority_difference(
    previous: ProblemCallSourceProvenance,
    current: ProblemCallSourceProvenance,
) -> dict[str, Any] | None:
    """Compare only immutable execution-source authority, not consumers."""

    for field_name in (
        "planning_context_id",
        "problem_revision_id",
        "problem_semantic_hash",
        "canonical_call_id",
        "input_source_unit_ids",
    ):
        expected = getattr(previous, field_name)
        actual = getattr(current, field_name)
        if expected != actual:
            return {
                "path": f"$.{field_name}",
                "expected": expected,
                "actual": actual,
            }
    return None


def _unauthorized_consumer_goal_deltas(
    previous: ProblemCallSourceProvenance,
    current: ProblemCallSourceProvenance,
    *,
    allowed_consumer_goal_delta_ids: set[str],
) -> tuple[str, ...]:
    """Return Goal-membership changes outside the authenticated repair cone."""

    changed = set(previous.goal_unit_ids) ^ set(current.goal_unit_ids)
    return tuple(sorted(changed - allowed_consumer_goal_delta_ids))


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
        object_registry: MathObjectRegistry | None = None,
    ) -> PreparedFunctionalCall:
        object_registry = object_registry or MathObjectRegistry.from_sources(
            handle_registry,
        )
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
        execution_entry = next(
            (
                item
                for item in reconciliation.execution_entries
                if item.call_id == call_id
            ),
            None,
        )
        if execution_entry is None:
            raise ValueError(
                "planner_configuration_error: "
                f"planner.transactional_execution_entry_missing: call={call_id}"
            )
        missing_versions = tuple(
            value.state_version_id
            for values in reconciled.resolved_args.values()
            for value in values
            if (
                value.state_version_id is not None
                and working.identity_index.version(
                    working.resolve_runtime_version_id(value.state_version_id)
                ) is None
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
        problem_binding_context = (
            reconciliation.functional_problem_binding_context
        )
        if problem_binding_context is not None and not isinstance(
            problem_binding_context,
            FunctionalProblemBindingContext,
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_source_binding_drift: "
                f"call={call_id}, invalid F5-C sidecar"
            )
        logical_bindings = binding_context.for_call(call_id)
        runtime_bindings = CanonicalRuntimeBindingIndex.from_context(
            runtime_context,
            handle_registry=handle_registry,
            question_goals=inputs.question_goals,
            functional_consumer_identity_mode="authoritative",
            problem_binding_authority=(problem_binding_context is not None),
        )
        state_reads: list[PreparedFunctionalStateRead] = []
        snapshot_paths: dict[StateVersionId, str] = {}
        for arg_name, values in reconciled.resolved_args.items():
            for item_index, value in enumerate(values):
                if value.state_version_id is None:
                    continue
                resolved_version_id = working.resolve_runtime_version_id(
                    value.state_version_id
                )
                original = working.identity_index.version(
                    resolved_version_id
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
                        original_version_id=value.state_version_id,
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
                    resolved_support_version_id = (
                        working.resolve_runtime_version_id(support_version_id)
                    )
                    support = working.identity_index.version(
                        resolved_support_version_id
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
                        resolved_support_version_id
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
                            selected_version_id=resolved_support_version_id,
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
        parameter_selector_object_ids = _parameter_selector_object_ids(
            reconciled.resolved_args,
            object_registry=object_registry,
            compiler_selectors=(
                item.selector for item in capability.auto_args
            ),
        )
        state_reads = list(
            _materialize_prepared_parameter_reads(
                state_reads,
                call_id=call_id,
                consumer_scope_id=node.execution_scope_id,
                working=working,
                runtime_context=runtime_context,
                object_registry=object_registry,
                ignored_parameter_ids=parameter_selector_object_ids,
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
        resolved_by_key = {
            (arg_name, item_index): value
            for arg_name, values in reconciled.resolved_args.items()
            for item_index, value in enumerate(values)
        }
        prepared_bindings: list[PreparedFunctionalArgBinding] = []
        for item in logical_bindings:
            key = (item.key.arg_name, item.key.item_index)
            value = resolved_by_key.get(key)
            state_read = reads_by_key.get(key)
            runtime_path = (
                state_read.snapshot_runtime_path
                if state_read is not None
                else _prepare_non_state_runtime_path(
                    item,
                    value=value,
                    runtime_bindings=runtime_bindings,
                    consumer_scope_id=node.execution_scope_id,
                )
            )
            if (
                item.consumption_mode == "runtime_input"
                and item.runtime_input_required
                and runtime_path is None
                and item.source.kind != "call_result"
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.functional_compile_input_mapping_drift: "
                    f"call={call_id}, arg={item.key.arg_name}"
                    f"[{item.key.item_index}]"
                )
            prepared_bindings.append(
                PreparedFunctionalArgBinding(
                    logical_binding=item,
                    source_handle=(
                        value.handle if value is not None else None
                    ),
                    source_math_object_id=(
                        value.math_object_id if value is not None else None
                    ),
                    selected_state_version_id=(
                        state_read.selected_version_id
                        if state_read is not None
                        else None
                    ),
                    runtime_path=runtime_path,
                    runtime_value=(
                        state_read.runtime_value
                        if state_read is not None
                        else None
                    ),
                )
            )
        if problem_binding_context is not None:
            _audit_problem_binding_preparation(
                call_id=call_id,
                wire_call=wire_call,
                logical_bindings=logical_bindings,
                prepared_bindings=tuple(prepared_bindings),
                problem_binding_context=problem_binding_context,
            )
        return PreparedFunctionalCall(
            call_id=call_id,
            capability_id=reconciled.capability_id,
            step_ids=(call_id,),
            dependency_call_ids=node.dependency_call_ids,
            execution_scope_id=node.execution_scope_id,
            reconciliation=reconciled,
            required_return_names=tuple(sorted(required_return_names)),
            state_reads=tuple(state_reads),
            arg_bindings=tuple(prepared_bindings),
            parameter_selector_object_ids=parameter_selector_object_ids,
        )


def _audit_problem_binding_preparation(
    *,
    call_id: str,
    wire_call: Any | None,
    logical_bindings: Sequence[FunctionalArgBinding],
    prepared_bindings: Sequence[PreparedFunctionalArgBinding],
    problem_binding_context: FunctionalProblemBindingContext,
) -> None:
    goal_ids = problem_binding_context.call_goal_bindings.get(call_id, ())
    if not goal_ids:
        raise ValueError(
            "planner_configuration_error: "
            "functional.call_goal_unresolved: "
            f"call={call_id}"
        )
    prepared_by_key = {
        (
            item.logical_binding.key.arg_name,
            item.logical_binding.key.item_index,
        ): item
        for item in prepared_bindings
    }
    for logical in logical_bindings:
        sidecar = problem_binding_context.input_binding_for(
            call_id,
            logical.key.arg_name,
            logical.key.item_index,
        )
        if sidecar is None or sidecar.typed_source != logical.source:
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_source_binding_drift: "
                f"call={call_id}, arg={logical.key.arg_name}"
                f"[{logical.key.item_index}]"
            )
        if sidecar.selection_policy != logical.selection_policy:
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_source_binding_drift: "
                f"call={call_id}, selection policy drift"
            )
        if sidecar.source_kind == "problem_source" and (
            not sidecar.source_unit_ids or sidecar.runtime_node_id is None
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_source_binding_unresolved: "
                f"call={call_id}, arg={logical.key.arg_name}"
            )
        prepared = prepared_by_key.get(
            (logical.key.arg_name, logical.key.item_index)
        )
        if prepared is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_source_binding_drift: "
                f"call={call_id}, prepared binding missing"
            )
        if logical.source.kind == "state_version":
            if (
                logical.selection_policy != "exact"
                or prepared.selected_state_version_id
                != logical.source.state_version_id
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.problem_source_binding_drift: "
                    f"call={call_id}, source StateVersion was replaced"
                )
    if len(problem_binding_context.inputs_for_call(call_id)) != len(
        logical_bindings
    ):
        raise ValueError(
            "planner_configuration_error: "
            "planner.problem_source_binding_drift: "
            f"call={call_id}, input sidecar cardinality drift"
        )
    expected_returns = set(
        wire_call.return_bindings if wire_call is not None else ()
    )
    sidecar_returns = {
        item.return_name
        for item in problem_binding_context.returns_for_call(call_id)
    }
    if expected_returns != sidecar_returns:
        raise ValueError(
            "planner_configuration_error: "
            "planner.problem_source_binding_drift: "
            f"call={call_id}, return sidecar drift"
        )


def _prepare_non_state_runtime_path(
    binding: FunctionalArgBinding,
    *,
    value: Any | None,
    runtime_bindings: CanonicalRuntimeBindingIndex,
    consumer_scope_id: str,
) -> str | None:
    if binding.consumption_mode != "runtime_input":
        return None
    if binding.source.kind == "compiler_selector":
        return None
    if value is None:
        return None
    consumer = (
        f"{binding.key.call_id}.{binding.key.arg_name}"
        f"[{binding.key.item_index}]"
    )
    if binding.source.kind == "condition":
        physical = runtime_bindings.bindings.get(value.handle)
        return runtime_bindings.runtime_path_for_condition_identity(
            binding.source.condition_id or "",
            source_handle=value.handle,
            expected_type=(
                physical.value_type
                if physical is not None
                else binding.runtime_type
            ),
            consumer_scope_id=consumer_scope_id,
            consumer=consumer,
        )
    if binding.source.kind == "call_result":
        # Call-local public returns are registered by the per-call compiler
        # from already committed CompiledFunctionalCall manifests. They have
        # no StateVersion and therefore cannot be resolved from WorkingState
        # during preparation.
        return None
    if binding.source.kind == "math_object":
        object_id = binding.source.math_object_id
        if object_id is None:
            return None
        physical = runtime_bindings.bindings.get(object_id.value)
        return runtime_bindings.runtime_path_for_object_identity(
            object_id,
            expected_type=(
                physical.value_type
                if physical is not None
                else binding.runtime_type
            ),
            consumer_scope_id=consumer_scope_id,
            consumer=consumer,
        )
    return None


def _canonicalize_projected_state_dependency_version(
    dependency: ProjectedStateDependency,
    *,
    working: WorkingPlannerState,
) -> ProjectedStateDependency:
    """Project a proven runtime-equivalent read onto its canonical version."""

    if dependency.state_version_id is None:
        return dependency
    selected = working.resolve_runtime_version_id(
        dependency.state_version_id
    )
    if selected == dependency.state_version_id:
        return dependency
    return replace(dependency, state_version_id=selected)


def _canonicalize_projected_state_write_versions(
    write: ProjectedStateWrite,
    *,
    working: WorkingPlannerState,
) -> ProjectedStateWrite:
    """Keep projected producer provenance aligned with runtime aliases."""

    selected = (
        working.resolve_runtime_version_id(write.selected_version_id)
        if write.selected_version_id is not None
        else None
    )
    previous = (
        working.resolve_runtime_version_id(write.previous_version_id)
        if write.previous_version_id is not None
        else None
    )
    sources = tuple(
        working.resolve_runtime_version_id(item)
        for item in write.source_version_ids
    )
    lineage_sources = tuple(
        working.resolve_runtime_version_id(item)
        for item in write.lineage.source_version_ids
    )
    object_roles = tuple(
        replace(
            role,
            source_version_ids=tuple(
                working.resolve_runtime_version_id(item)
                for item in role.source_version_ids
            ),
        )
        for role in write.lineage.object_roles
    )
    lineage = replace(
        write.lineage,
        source_version_ids=lineage_sources,
        object_roles=object_roles,
    )
    if (
        selected == write.selected_version_id
        and previous == write.previous_version_id
        and sources == write.source_version_ids
        and lineage == write.lineage
    ):
        return write
    return replace(
        write,
        selected_version_id=selected,
        previous_version_id=previous,
        source_version_ids=sources,
        lineage=lineage,
    )


class FunctionalCallCompilerService:
    """Compile one canonical Functional call against the working Context."""

    def __init__(
        self,
        *,
        capability_compiler: FunctionalCapabilityCompiler | None = None,
    ) -> None:
        capability_compiler = (
            capability_compiler or FunctionalCapabilityCompiler()
        )
        self._direct_compiler = FunctionalDirectCompiler(
            capability_compiler=capability_compiler,
        )

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
        return self._compile_direct(
            prepared_call,
            reconciliation=reconciliation,
            runtime_context=runtime_context,
            working=working,
            inputs=inputs,
            handle_registry=handle_registry,
            capability_catalog=capability_catalog,
            committed_state_writes=committed_state_writes,
            committed_calls=committed_calls,
        )

    def _compile_direct(
        self,
        prepared_call: PreparedFunctionalCall,
        *,
        reconciliation: FunctionalPlanReconciliationResult,
        runtime_context: RuntimeContext,
        working: WorkingPlannerState,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        capability_catalog: FunctionalCapabilityCatalog,
        committed_state_writes: tuple[StateWriteProvenance, ...],
        committed_calls: tuple[CompiledFunctionalCall, ...],
    ) -> CompiledFunctionalCall:
        capability = capability_catalog.get(prepared_call.capability_id)
        if capability is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.functional_compile_contract_incomplete: "
                f"call={prepared_call.call_id}, "
                f"capability={prepared_call.capability_id}"
            )
        all_writes = build_functional_state_write_manifest(
            reconciliation.plan,
            reconciliation.calls,
        )
        all_writes = tuple(
            _canonicalize_projected_state_write_versions(
                item,
                working=working,
            )
            for item in all_writes
        )
        all_dependencies = tuple(
            _canonicalize_projected_state_dependency_version(
                item,
                working=working,
            )
            for item in reconciliation.state_dependencies
        )
        available_call_ids = {
            prepared_call.call_id,
            *(call.call_id for call in committed_calls),
        }
        call_dependencies = tuple(
            item for item in all_dependencies
            if item.step_id in available_call_ids
        )
        request = FunctionalCompileRequest(
            prepared_call=prepared_call,
            capability=capability,
            execution_scope_id=prepared_call.execution_scope_id,
            arg_bindings=prepared_call.arg_bindings,
            state_reads=prepared_call.state_reads,
            return_allocations=prepared_call.reconciliation.returns,
            state_dependencies=call_dependencies,
            known_versions=working.identity_index.all_versions(),
            required_return_names=prepared_call.required_return_names,
            state_writes=tuple(
                item
                for item in all_writes
                if item.step_id in available_call_ids
            ),
            known_state_writes=committed_state_writes,
            known_runtime_bindings=_known_call_local_runtime_bindings(
                committed_calls,
            ),
            known_object_refs=frozenset(
                handle_registry.initial_handles
            ),
            problem_binding_authority=(
                reconciliation.functional_problem_binding_context is not None
            ),
        )
        try:
            compiled = self._direct_compiler.compile(
                request,
                runtime_context,
                inputs=inputs,
                handle_registry=handle_registry,
            )
        except Exception as exc:
            classified = _classified_direct_compile_error(
                prepared_call.call_id,
                exc,
            )
            if classified is exc:
                raise
            raise classified from exc
        wrapped = _wrap_exact_compiled_call(
            compiled,
            prepared_call=prepared_call,
            capability_catalog=capability_catalog,
        )
        problem_context = reconciliation.functional_problem_binding_context
        if isinstance(problem_context, FunctionalProblemBindingContext):
            wrapped = _stamp_compiled_problem_source_provenance(
                wrapped,
                problem_context.source_provenance_for_call(
                    prepared_call.call_id
                ),
            )
        return wrapped


def build_functional_runtime_arg_bindings(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[ProjectedFunctionArgBinding, ...]:
    """Project C3 wire bindings into the direct-compiler input manifest."""
    del catalog
    context = reconciliation.functional_binding_context
    if not isinstance(context, FunctionalBindingContext):
        raise ValueError(
            "planner_configuration_error: "
            "planner.functional_binding_context_incomplete"
        )
    return build_functional_runtime_arg_bindings_from_context(
        reconciliation.calls,
        context,
    )


def _classified_direct_compile_error(
    call_id: str,
    exc: Exception,
) -> Exception:
    if isinstance(exc, StatelessMethodError):
        return exc
    message = str(exc)
    if (
        "planner_configuration_error" in message
        or "functional." in message
        or "function." in message
    ):
        return exc
    return ValueError(
        "planner_configuration_error: "
        "planner.functional_compile_contract_incomplete: "
        f"call={call_id}: {type(exc).__name__}: {message}"
    )


def _known_call_local_runtime_bindings(
    committed_calls: tuple[CompiledFunctionalCall, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (handle, runtime_path, returned.expected_write.runtime_type, f"step:{call.call_id}")
        for call in committed_calls
        for returned in call.public_returns
        if (
            returned.expected_write is not None
            and returned.allocation.allocation_action == "call_local_value"
        )
        for runtime_path in (
            _runtime_path_for_write(call.plans, returned.expected_write),
        )
        if runtime_path is not None
        for handle in unique_ordered(
            (
                returned.expected_write.produced_handle,
                returned.allocation.handle,
                returned.allocation.state_handle,
            )
        )
        if isinstance(handle, str) and handle
    )


def _wrap_exact_compiled_call(
    compiled: ExactCompiledStep,
    *,
    prepared_call: PreparedFunctionalCall,
    capability_catalog: FunctionalCapabilityCatalog,
) -> CompiledFunctionalCall:
    path_rewrites = _prepared_path_rewrites(prepared_call)
    replay_plans = (compiled.plan,)
    plans = (_rewrite_plan_input_paths(compiled.plan, path_rewrites),)
    audit = audit_compiled_functional_arg_consumption(
        tuple(item.logical_binding for item in prepared_call.arg_bindings),
        plans,
        expected_runtime_paths={
            item.logical_binding.key: (
                item.runtime_path
                if item.logical_binding.consumption_mode == "runtime_input"
                else None
            )
            for item in prepared_call.arg_bindings
        },
        arg_repairs=tuple(
            repair
            for event in compiled.function_binding_events
            if event.status == "success"
            for repair in event.arg_repairs
        ),
    )
    if audit.mismatches:
        first = audit.mismatches[0]
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
            "planner.functional_compile_contract_incomplete: "
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
            or allocation.return_name in prepared_call.required_return_names,
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
    declarations_by_path = {
        str(item.path): item
        for item in compiled.declarations
        if item.path in referenced_paths
    }
    declarations = tuple(declarations_by_path.values())
    return CompiledFunctionalCall(
        call_id=prepared_call.call_id,
        step_ids=prepared_call.step_ids,
        declarations=declarations,
        plans=plans,
        public_returns=public_returns,
        replay_plans=replay_plans,
        binding_consumption_decisions=audit.decisions,
    )


def _compiled_call_signature(
    compiled: CompiledFunctionalCall,
) -> tuple[Any, ...]:
    return (
        tuple(
            (
                plan.step_id,
                plan.scope,
                tuple(
                    (
                        invocation.method_id,
                        tuple(sorted(invocation.inputs.items())),
                        tuple(sorted(invocation.outputs.items())),
                    )
                    for invocation in plan.invocations
                ),
                tuple(sorted(plan.promote_outputs.items())),
            )
            for plan in compiled.plans
        ),
        tuple(
            sorted(
                (item.path, item.type)
                for item in compiled.declarations
            )
        ),
        tuple(
            (
                item.return_name,
                item.required,
                (
                    item.expected_write.output_key,
                    item.expected_write.runtime_type,
                    item.expected_write.math_object_id,
                    item.expected_write.logical_state_key,
                    item.expected_write.selected_version_id,
                    item.expected_write.previous_version_id,
                    item.expected_write.source_version_ids,
                    item.expected_write.runtime_destination_key,
                )
                if item.expected_write is not None else None,
            )
            for item in compiled.public_returns
        ),
        (
            compiled.problem_source_provenance.semantic_signature()
            if compiled.problem_source_provenance is not None
            else None
        ),
    )


def _stamp_compiled_problem_source_provenance(
    compiled: CompiledFunctionalCall,
    provenance: ProblemCallSourceProvenance,
) -> CompiledFunctionalCall:
    if provenance.canonical_call_id != compiled.call_id:
        raise ProblemSourceProvenanceError(
            "planner.runtime_problem_provenance_drift",
            f"call={compiled.call_id}, authority call mismatch"
        )
    return replace(
        compiled,
        public_returns=tuple(
            replace(
                returned,
                expected_write=(
                    replace(
                        returned.expected_write,
                        problem_source_provenance=provenance,
                    )
                    if returned.expected_write is not None
                    else None
                ),
            )
            for returned in compiled.public_returns
        ),
        problem_source_provenance=provenance,
    )


def _audit_compiled_problem_source_provenance(
    compiled: CompiledFunctionalCall,
) -> None:
    expected = compiled.problem_source_provenance
    observed = tuple(
        returned.expected_write.problem_source_provenance
        for returned in compiled.public_returns
        if returned.expected_write is not None
    )
    if expected is None:
        if any(item is not None for item in observed):
            raise ProblemSourceProvenanceError(
                "planner.runtime_problem_provenance_drift",
                f"call={compiled.call_id}, unexpected write authority"
            )
        return
    if not observed or any(item is None for item in observed):
        raise ProblemSourceProvenanceError(
            "planner.runtime_problem_provenance_missing",
            f"call={compiled.call_id}",
        )
    expected_signature = expected.semantic_signature()
    for item in observed:
        if item is None:
            continue
        if (
            item.planning_context_id != expected.planning_context_id
            or item.problem_revision_id != expected.problem_revision_id
            or item.problem_semantic_hash != expected.problem_semantic_hash
        ):
            raise ProblemSourceProvenanceError(
                "planner.problem_revision_drift",
                f"call={compiled.call_id}, Problem revision drift",
            )
        if item.semantic_signature() != expected_signature:
            raise ProblemSourceProvenanceError(
                "planner.runtime_problem_provenance_drift",
                f"call={compiled.call_id}, companion return authority drift"
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
        tuple[FunctionalRuntimeResult, ...],
        tuple[StateWriteProvenance, ...],
        tuple[IndexedStateVersion, ...],
        dict[StateVersionId, TypedValue],
        tuple[PlannerRetryIssue, ...],
    ]:
        _audit_compiled_problem_source_provenance(compiled)
        wire_call = next(
            (item for item in plan.calls if item.call_id == compiled.call_id),
            None,
        )
        expectations = (
            dict(wire_call.return_expectations)
            if wire_call is not None
            else {}
        )
        runtime_results: list[FunctionalRuntimeResult] = []
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
            path = _materialized_runtime_path(compiled, write)
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
    """Execute canonical Functional calls in isolated transactions."""

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
        runtime_context: RuntimeContext,
        parent_context: PlannerStateContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        goal_verification_report: Any | None = None,
        restored_seed: FunctionalRestoredCallSeed | None = None,
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
        exact_compiler = FunctionalCallCompilerService()
        committer = FunctionalRuntimeWriteCommitter()
        object_registry = MathObjectRegistry.from_sources(
            handle_registry,
            math_objects=parent_context.state.math_objects,
        )
        results: list[FunctionalCallExecutionResult] = []
        compiled_calls: list[CompiledFunctionalCall] = []
        runtime_result_values: dict[tuple[str, str], TypedValue] = {}
        runtime_equivalent_aliases: list[
            FunctionalRuntimeEquivalentCallAlias
        ] = []
        restored_call_ids = _restore_verified_calls(
            restored_seed,
            graph=graph,
            working=working,
            current_context=current_context,
            results=results,
            compiled_calls=compiled_calls,
            runtime_result_values=runtime_result_values,
        )
        for call_id in graph.canonical_order:
            if call_id in restored_call_ids:
                continue
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
            prepared: Any | None = None
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
                    object_registry=object_registry,
                )
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
                _audit_compiled_problem_source_provenance(compiled)
                branch = current_context.fork()
                for plan in compiled.plans:
                    branch.ensure_step_scope(plan.step_id, plan.scope)
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
                compiled, prepared = _materialize_compiled_parameter_inputs(
                    compiled,
                    prepared=prepared,
                    branch=branch,
                    working=working,
                    object_registry=object_registry,
                    execution_scope_id=prepared.execution_scope_id,
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
                            details=_closure_failure_details(
                                closure_result,
                                call_id=call_id,
                                graph=graph,
                            ),
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
                    raise method_check_failed(
                        failed_checks,
                        method_id=next(
                            (
                                str(getattr(item, "method_id"))
                                for item in failed_checks
                                if getattr(item, "method_id", None)
                            ),
                            None,
                        ),
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
                    _validate_symbolic_closure_write_set(
                        writes,
                        closure_result=closure_result,
                        compiled=compiled,
                    )
                projected_writes = tuple(
                    item
                    for item in build_functional_state_write_manifest(
                        reconciliation.plan,
                        reconciliation.calls,
                    )
                    if item.step_id == call_id
                )
                # B3 finalization is the single authority for compiled writes.
                StateFinalizationService().finalize_compiled_graph(
                    projected_writes,
                    writes,
                    compiled.plans,
                    question_goals=tuple(inputs.question_goals),
                    handle_registry=handle_registry,
                    mode="authoritative",
                )
                runtime_alias, equivalence_issue = (
                    _compare_provisional_runtime_state(
                        call_id=call_id,
                        writes=writes,
                        runtime_values=runtime_values,
                        reconciliation=reconciliation,
                        working=working,
                        branch=branch,
                        object_registry=object_registry,
                    )
                )
                if equivalence_issue is not None:
                    working.set_status(
                        call_id,
                        "failed",
                        issue_codes=(equivalence_issue.code,),
                    )
                    working.emit(call_id, "failed")
                    results.append(
                        FunctionalCallExecutionResult(
                            call_id,
                            "failed",
                            runtime_results=runtime_results,
                            state_writes=writes,
                            checks=tuple(execution.checks),
                            root_issues=(equivalence_issue,),
                            symbolic_closure=closure_result,
                        )
                    )
                    continue
                if runtime_alias is not None:
                    # The isolated branch proved that every reused typed state
                    # is unchanged. Keep an answer alias so the Goal remains
                    # bound to the proven existing StateVersion, but never
                    # commit a second object-state write.
                    answer_alias_writes = tuple(
                        write
                        for write in writes
                        if write.produced_handle.startswith("answer:")
                    )
                    working.set_status(call_id, "verified")
                    working.emit(call_id, "verified")
                    for write in writes:
                        if write.selected_version_id is None:
                            continue
                        typed = runtime_values.get(write.selected_version_id)
                        if typed is not None:
                            runtime_result_values[(call_id, write.output_key)] = typed
                        if (
                            write.previous_version_id is not None
                            and write.allocation_action == "transition"
                        ):
                            working.register_runtime_equivalent_version_alias(
                                write.selected_version_id,
                                write.previous_version_id,
                            )
                    current_context = branch
                    compiled_calls.append(compiled)
                    runtime_equivalent_aliases.append(runtime_alias)
                    results.append(
                        FunctionalCallExecutionResult(
                            call_id,
                            "verified",
                            runtime_results=runtime_results,
                            state_writes=answer_alias_writes,
                            committed_versions=(),
                            checks=tuple(execution.checks),
                            symbolic_closure=closure_result,
                        )
                    )
                    continue
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
                for write in writes:
                    destination = write.runtime_destination_key
                    if destination is None or destination.runtime_path is None:
                        continue
                    runtime_result_values[(call_id, write.output_key)] = (
                        branch.read_path(
                            destination.runtime_path,
                            from_scope_id=write.scope_id,
                            expected_type=write.runtime_type,
                        )
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
                diagnostic: FunctionalDiagnosticAuthority | None = None
                if isinstance(exc, StatelessMethodError):
                    enriched = exc.with_context(
                        capability_id=(
                            prepared.capability_id
                            if prepared is not None
                            else None
                        ),
                        scope_id=(
                            prepared.execution_scope_id
                            if prepared is not None
                            else None
                        ),
                        step_id=call_id,
                    )
                    diagnostic = enriched.authority
                    if prepared is not None:
                        failed_capability = capability_catalog.get(
                            prepared.capability_id
                        )
                        if (
                            failed_capability is not None
                            and failed_capability.kind == "macro"
                        ):
                            diagnostic = normalize_macro_diagnostic_authority(
                                diagnostic,
                                macro_spec=failed_capability.source,
                                provided_arg_names=tuple(
                                    prepared.reconciliation.resolved_args
                                ),
                            )
                    issue_code = diagnostic.code
                elif isinstance(exc, ProblemSourceProvenanceError):
                    issue_code = exc.code
                elif isinstance(exc, SymbolicClosureProvenanceError):
                    issue_code = exc.code
                elif isinstance(exc, SymbolicClosureRuntimeDriftError):
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
                    details=(
                        dict(diagnostic.authority_details)
                        if diagnostic is not None
                        else None
                    ),
                    diagnostic_authority=(
                        diagnostic.to_payload()
                        if diagnostic is not None
                        else None
                    ),
                )
                if diagnostic is None:
                    diagnostic = diagnostic_authority_from_issue(
                        issue,
                        stage="transaction",
                        capability_id=(
                            prepared.capability_id
                            if prepared is not None
                            else None
                        ),
                        scope_id=(
                            prepared.execution_scope_id
                            if prepared is not None
                            else None
                        ),
                        step_id=call_id,
                    )
                    issue = replace(
                        issue,
                        diagnostic_authority=diagnostic.to_payload(),
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
            compiled_calls=tuple(compiled_calls),
            known_versions=working.identity_index.all_versions(),
            restored_call_ids=tuple(
                call_id
                for call_id in graph.canonical_order
                if call_id in restored_call_ids
            ),
            runtime_version_values=dict(working.runtime_version_values),
            runtime_version_symbol_bindings={
                version_id: dict(bindings)
                for version_id, bindings in (
                    working.runtime_version_symbol_bindings.items()
                )
            },
            runtime_result_values=runtime_result_values,
            runtime_equivalent_aliases=tuple(runtime_equivalent_aliases),
        )

    def execute_attempt(
        self,
        *,
        raw_plan: FunctionalPlan,
        reconciliation: FunctionalPlanReconciliationResult,
        runtime_context: RuntimeContext,
        parent_context: PlannerStateContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        problem_payload: Mapping[str, Any],
        restored_seed: FunctionalRestoredCallSeed | None = None,
    ) -> FunctionalTransactionalAttemptResult:
        """Execute C2 and derive goal, output and retry facts from runtime."""
        report = self.execute(
            raw_plan=raw_plan,
            reconciliation=reconciliation,
            runtime_context=runtime_context,
            parent_context=parent_context,
            inputs=inputs,
            handle_registry=handle_registry,
            restored_seed=restored_seed,
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
        projected_writes = build_functional_state_write_manifest(
            reconciliation.plan,
            reconciliation.calls,
        )
        read_index = FunctionalStateReadIndex.from_sources(
            handle_registry=handle_registry,
            mode="authoritative",
            projected_state_writes=projected_writes,
            projected_state_dependencies=(
                reconciliation.state_dependencies
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
            runtime_writes_by_version=_canonical_runtime_writes_by_version(
                state_writes
            ),
            answer_version_ids=answer_version_ids,
            verified_call_ids=verified_call_ids,
            goal_producers=_functional_goal_producers(
                report.graph,
                reconciliation=reconciliation,
                capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
                    inputs.family_spec,
                    inputs.method_specs,
                ),
                state_writes=state_writes,
            ),
        )
        goal_report = AnswerGoalVerifier().verify_report(
            problem_payload=problem_payload,
            handle_registry=handle_registry,
            diagnostic=diagnostic,
            family_spec=inputs.family_spec,
            functional_context=goal_context,
        )
        required_goal_handles = frozenset(
            f"answer:{goal.id}" for goal in inputs.question_goals
        )
        goal_report = replace(
            goal_report,
            goals=tuple(
                item
                for item in goal_report.goals
                if item.goal_handle in required_goal_handles
            ),
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


def _restore_verified_calls(
    seed: FunctionalRestoredCallSeed | None,
    *,
    graph: LogicalFunctionalGraph,
    working: WorkingPlannerState,
    current_context: RuntimeContext,
    results: list[FunctionalCallExecutionResult],
    compiled_calls: list[CompiledFunctionalCall],
    runtime_result_values: dict[tuple[str, str], TypedValue],
) -> frozenset[str]:
    """Restore solved calls without invoking their capabilities again."""

    if seed is None:
        return frozenset()
    known = set(graph.canonical_order)
    result_by_call = {item.call_id: item for item in seed.call_results}
    compiled_by_call = {item.call_id: item for item in seed.compiled_calls}
    if len(result_by_call) != len(seed.call_results):
        raise ValueError(
            "planner_configuration_error: "
            "planner.retry_problem_source_binding_drift: duplicate restored call"
        )
    restored = frozenset(result_by_call)
    if not restored <= known or set(compiled_by_call) != set(restored):
        raise ValueError(
            "planner_configuration_error: "
            "planner.retry_problem_source_binding_drift: restored graph drift"
        )
    for call_id in graph.canonical_order:
        if call_id not in restored:
            continue
        result = result_by_call[call_id]
        compiled = compiled_by_call[call_id]
        state = working.call_states[call_id]
        if result.status != "verified" or compiled.call_id != call_id:
            raise ValueError(
                "planner_configuration_error: "
                "planner.retry_problem_source_binding_drift: invalid restored call"
            )
        if any(
            dependency not in restored
            and working.call_states[dependency].status != "verified"
            for dependency in state.dependency_call_ids
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.retry_problem_source_binding_drift: restored dependency missing"
            )
        versions = tuple(result.committed_versions)
        _apply_missing_declarations(current_context, compiled.declarations)
        for plan in compiled.plans:
            current_context.ensure_step_scope(plan.step_id, plan.scope)
        runtime_values: dict[StateVersionId, TypedValue] = {}
        writes_by_version = {
            item.selected_version_id: item
            for item in result.state_writes
            if item.selected_version_id is not None
        }
        runtime_result_by_return = {
            item.output_key: item for item in result.runtime_results
        }
        for version in versions:
            write = writes_by_version.get(version.version_id)
            if write is None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.retry_problem_source_binding_drift: restored write missing"
                )
            runtime_result = runtime_result_by_return.get(write.output_key)
            typed = seed.runtime_version_values.get(version.version_id)
            if runtime_result is None or typed is None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.transactional_runtime_value_missing: "
                    f"restored call={call_id}, return={write.output_key}"
                )
            runtime_values[version.version_id] = typed
            destination = version.runtime_destination
            if destination is None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.contract_runtime_destination_drift: "
                    f"restored call={call_id}, return={write.output_key}"
                )
            current_context.write_path(
                destination.runtime_path,
                typed,
                from_scope_id=write.scope_id,
                allow_overwrite=True,
                allow_ancestor_write=True,
            )
        for returned in compiled.public_returns:
            write = returned.expected_write
            if write is None:
                continue
            key = (call_id, write.output_key)
            typed = seed.runtime_result_values.get(key)
            destination = write.runtime_destination_key
            if (
                typed is None
                or destination is None
                or destination.runtime_path is None
            ):
                continue
            current_context.write_path(
                destination.runtime_path,
                typed,
                from_scope_id=write.scope_id,
                allow_overwrite=True,
                allow_ancestor_write=True,
            )
        working.commit_verified_transaction(
            call_id,
            versions,
            runtime_values,
            runtime_symbol_bindings={
                version_id: seed.runtime_version_symbol_bindings.get(
                    version_id,
                    {},
                )
                for version_id in runtime_values
            },
        )
        for runtime_result in result.runtime_results:
            key = (call_id, runtime_result.output_key)
            typed = seed.runtime_result_values.get(key)
            if typed is None:
                continue
            runtime_result_values[key] = typed
        results.append(result)
        compiled_calls.append(compiled)
    return restored


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


_IMPLICIT_PARAMETER_ARG = "__implicit_parameter__"


def _parameter_selector_object_ids(
    resolved_args: Mapping[str, Sequence[Any]],
    *,
    object_registry: MathObjectRegistry,
    compiler_selectors: Sequence[str] = (),
) -> frozenset[MathObjectId]:
    """Return symbols a method explicitly asks to keep as selectors."""

    result: set[MathObjectId] = set()
    for values in resolved_args.values():
        for value in values:
            if value.runtime_type not in {
                "ParameterValue",
                "Symbol",
                "SymbolList",
            }:
                continue
            if value.math_object_id is not None:
                result.add(value.math_object_id)
            result.update(value.free_symbol_ids)
            if value.object_ref is not None:
                object_id = object_registry.resolve(value.object_ref)
                if object_id is not None and object_id.kind == "symbol":
                    result.add(object_id)
    for selector in compiler_selectors:
        object_id = object_registry.resolve(selector)
        if object_id is None and selector.startswith("symbol:"):
            object_id = object_registry.resolve(selector.removeprefix("symbol:"))
        if object_id is not None and object_id.kind == "symbol":
            result.add(object_id)
    return frozenset(result)


def _materialize_prepared_parameter_reads(
    reads: Sequence[PreparedFunctionalStateRead],
    *,
    call_id: str,
    consumer_scope_id: str,
    working: WorkingPlannerState,
    runtime_context: RuntimeContext,
    object_registry: MathObjectRegistry,
    ignored_parameter_ids: frozenset[MathObjectId],
) -> tuple[PreparedFunctionalStateRead, ...]:
    """Close direct state snapshots over verified visible parameters."""

    materialized: list[PreparedFunctionalStateRead] = []
    parameter_versions: dict[StateVersionId, IndexedStateVersion] = {}
    declared = _context_runtime_symbol_bindings(
        runtime_context,
        registry=object_registry,
    )
    for read in reads:
        read_declared = _merge_runtime_symbol_bindings(
            declared,
            working.runtime_version_symbol_bindings.get(
                read.selected_version_id,
                {},
            ),
        )
        closure = _materialize_runtime_parameter_closure(
            read.runtime_value,
            consumer_scope_id=consumer_scope_id,
            working=working,
            runtime_context=runtime_context,
            object_registry=object_registry,
            declared_runtime_symbols=read_declared,
            ignored_parameter_ids=ignored_parameter_ids,
        )
        materialized.append(
            replace(read, runtime_value=closure.runtime_value)
        )
        parameter_versions.update(
            (item.version_id, item) for item in closure.parameter_versions
        )
    materialized.extend(
        _implicit_parameter_reads(
            tuple(parameter_versions.values()),
            existing_reads=materialized,
            call_id=call_id,
            consumer_scope_id=consumer_scope_id,
            working=working,
            runtime_context=runtime_context,
            object_registry=object_registry,
            ignored_parameter_ids=ignored_parameter_ids,
        )
    )
    return tuple(materialized)


def _materialize_compiled_parameter_inputs(
    compiled: CompiledFunctionalCall,
    *,
    prepared: PreparedFunctionalCall,
    branch: RuntimeContext,
    working: WorkingPlannerState,
    object_registry: MathObjectRegistry,
    execution_scope_id: str,
) -> tuple[CompiledFunctionalCall, PreparedFunctionalCall]:
    """Close call-result and other physical inputs before method execution."""

    declared = _merge_runtime_symbol_bindings(
        _context_runtime_symbol_bindings(branch, registry=object_registry),
        _prepared_runtime_symbol_bindings(prepared, working=working),
    )
    ignored_parameter_ids = prepared.parameter_selector_object_ids
    parameter_versions = {
        read.selected_version_id: working.identity_index.version(
            read.selected_version_id
        )
        for read in prepared.state_reads
        if read.arg_name.startswith(_IMPLICIT_PARAMETER_ARG)
    }
    parameter_versions = {
        version_id: version
        for version_id, version in parameter_versions.items()
        if version is not None
    }
    rewrites: dict[str, str] = {}
    materialized_values: dict[str, TypedValue] = {}
    next_index = len(
        {item.snapshot_runtime_path for item in prepared.state_reads}
    )
    for plan in compiled.plans:
        for invocation in plan.invocations:
            paths = (
                path
                for raw in invocation.inputs.values()
                for path in ((raw,) if isinstance(raw, str) else raw)
            )
            for path in paths:
                if path in rewrites:
                    continue
                try:
                    runtime_value = branch.read_path(
                        path,
                        from_scope_id=plan.scope,
                    )
                except (KeyError, PermissionError, TypeError, ValueError):
                    # A path produced by an earlier invocation in this same
                    # compiled call does not exist until execution begins.
                    continue
                closure = _materialize_runtime_parameter_closure(
                    runtime_value,
                    consumer_scope_id=execution_scope_id,
                    working=working,
                    runtime_context=branch,
                    object_registry=object_registry,
                    declared_runtime_symbols=declared,
                    ignored_parameter_ids=ignored_parameter_ids,
                )
                if not closure.parameter_versions:
                    continue
                snapshot_path = _transaction_snapshot_path(
                    branch,
                    scope_id=execution_scope_id,
                    call_id=f"{compiled.call_id}_parameter_closure",
                    item_index=next_index,
                )
                next_index += 1
                branch.write_path(
                    snapshot_path,
                    closure.runtime_value,
                    from_scope_id=execution_scope_id,
                    allow_overwrite=True,
                )
                rewrites[path] = snapshot_path
                materialized_values[path] = closure.runtime_value
                parameter_versions.update(
                    (item.version_id, item)
                    for item in closure.parameter_versions
                )

    extra_reads = _implicit_parameter_reads(
        tuple(parameter_versions.values()),
        existing_reads=prepared.state_reads,
        call_id=compiled.call_id,
        consumer_scope_id=execution_scope_id,
        working=working,
        runtime_context=branch,
        object_registry=object_registry,
        ignored_parameter_ids=ignored_parameter_ids,
    )
    _materialize_transaction_state_reads(
        branch,
        extra_reads,
        scope_id=execution_scope_id,
    )
    prepared = replace(
        prepared,
        state_reads=tuple((*prepared.state_reads, *extra_reads)),
        arg_bindings=tuple(
            replace(
                binding,
                runtime_path=rewrites.get(
                    binding.runtime_path,
                    binding.runtime_path,
                ),
                runtime_value=materialized_values.get(
                    binding.runtime_path,
                    binding.runtime_value,
                ),
            )
            for binding in prepared.arg_bindings
        ),
    )
    parameter_version_ids = tuple(
        sorted(
            parameter_versions,
            key=lambda item: stable_hash(item.to_payload()),
        )
    )
    compiled = replace(
        compiled,
        plans=tuple(
            _rewrite_plan_input_paths(plan, rewrites)
            for plan in compiled.plans
        ),
        public_returns=tuple(
            replace(
                returned,
                expected_write=(
                    _with_runtime_parameter_sources(
                        returned.expected_write,
                        parameter_version_ids,
                    )
                    if returned.expected_write is not None
                    else None
                ),
            )
            for returned in compiled.public_returns
        ),
    )
    return compiled, prepared


def _implicit_parameter_reads(
    versions: Sequence[IndexedStateVersion],
    *,
    existing_reads: Sequence[PreparedFunctionalStateRead],
    call_id: str,
    consumer_scope_id: str,
    working: WorkingPlannerState,
    runtime_context: RuntimeContext,
    object_registry: MathObjectRegistry,
    ignored_parameter_ids: frozenset[MathObjectId],
) -> tuple[PreparedFunctionalStateRead, ...]:
    existing_version_ids = {
        item.selected_version_id for item in existing_reads
    }
    snapshot_paths = {
        item.selected_version_id: item.snapshot_runtime_path
        for item in existing_reads
    }
    result: list[PreparedFunctionalStateRead] = []
    ordered = sorted(
        {item.version_id: item for item in versions}.values(),
        key=lambda item: stable_hash(item.version_id.to_payload()),
    )
    for index, version in enumerate(ordered):
        if version.version_id in existing_version_ids:
            continue
        runtime_value = working.runtime_version_values.get(version.version_id)
        runtime_path = _indexed_runtime_path(version)
        if runtime_value is None or runtime_path is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_parameter_state_unavailable: "
                f"version={version.version_id.to_payload()}"
            )
        closure = _materialize_runtime_parameter_closure(
            runtime_value,
            consumer_scope_id=consumer_scope_id,
            working=working,
            runtime_context=runtime_context,
            object_registry=object_registry,
            declared_runtime_symbols=(
                working.runtime_version_symbol_bindings.get(
                    version.version_id,
                    {},
                )
            ),
            resolving=(version.version_id,),
            ignored_parameter_ids=ignored_parameter_ids,
        )
        result.append(
            PreparedFunctionalStateRead(
                arg_name=f"{_IMPLICIT_PARAMETER_ARG}{index}",
                item_index=index,
                selection="exact",
                original_version_id=version.version_id,
                selected_version_id=version.version_id,
                original_runtime_path=runtime_path,
                snapshot_runtime_path=snapshot_paths.setdefault(
                    version.version_id,
                    _transaction_snapshot_path(
                        runtime_context,
                        scope_id=consumer_scope_id,
                        call_id=call_id,
                        item_index=len(snapshot_paths),
                    ),
                ),
                runtime_value=closure.runtime_value,
            )
        )
        existing_version_ids.add(version.version_id)
    return tuple(result)


def _materialize_runtime_parameter_closure(
    runtime_value: TypedValue,
    *,
    consumer_scope_id: str,
    working: WorkingPlannerState,
    runtime_context: RuntimeContext,
    object_registry: MathObjectRegistry,
    declared_runtime_symbols: Mapping[sp.Symbol, MathObjectId],
    resolving: tuple[StateVersionId, ...] = (),
    ignored_parameter_ids: frozenset[MathObjectId] = frozenset(),
) -> _RuntimeParameterClosure:
    # Symbol-valued inputs select an identity (for example the parameter to
    # solve or substitute).  Replacing that selector with its latest value
    # would change the method contract rather than materialize object state.
    if runtime_value.type in {"Symbol", "SymbolList"}:
        return _RuntimeParameterClosure(runtime_value)
    substitutions: dict[sp.Symbol, Any] = {}
    versions: list[IndexedStateVersion] = []
    for symbol in runtime_free_symbols(runtime_value.value):
        object_ids = runtime_free_symbol_ids(
            symbol,
            context=runtime_context,
            registry=object_registry,
            declared_runtime_symbols=declared_runtime_symbols,
        )
        if len(object_ids) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={symbol}"
            )
        if object_ids[0] in ignored_parameter_ids:
            continue
        version = _latest_visible_parameter_version(
            object_ids[0],
            consumer_scope_id=consumer_scope_id,
            working=working,
        )
        if version is None:
            continue
        if version.version_id in resolving:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_parameter_state_cycle: "
                f"versions={[item.to_payload() for item in resolving]}"
            )
        parameter_value = working.runtime_version_values.get(
            version.version_id
        )
        if parameter_value is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_parameter_state_unavailable: "
                f"version={version.version_id.to_payload()}"
            )
        nested = _materialize_runtime_parameter_closure(
            parameter_value,
            consumer_scope_id=consumer_scope_id,
            working=working,
            runtime_context=runtime_context,
            object_registry=object_registry,
            declared_runtime_symbols=_merge_runtime_symbol_bindings(
                declared_runtime_symbols,
                working.runtime_version_symbol_bindings.get(
                    version.version_id,
                    {},
                ),
            ),
            resolving=(*resolving, version.version_id),
            ignored_parameter_ids=ignored_parameter_ids,
        )
        substitutions[symbol] = nested.runtime_value.value
        versions.extend((version, *nested.parameter_versions))
    if not substitutions:
        return _RuntimeParameterClosure(runtime_value)
    return _RuntimeParameterClosure(
        replace(
            runtime_value,
            value=_substitute_runtime_parameters(
                runtime_value.value,
                substitutions,
            ),
        ),
        tuple(
            {item.version_id: item for item in versions}.values()
        ),
    )


def _latest_visible_parameter_version(
    object_id: MathObjectId,
    *,
    consumer_scope_id: str,
    working: WorkingPlannerState,
) -> IndexedStateVersion | None:
    visible = tuple(
        item
        for item in working.identity_index.all_versions()
        if (
            item.version_id.slot_id.logical_key.object_id == object_id
            and item.version_id.slot_id.logical_key.runtime_type
            == "ParameterValue"
            and item.version_id in working.runtime_version_values
            and working.identity_index.visibility.is_visible(
                item.valid_scope_id,
                consumer_scope_id=consumer_scope_id,
            )
            and (
                item.producer_call_id is None
                or (
                    item.producer_call_id in working.call_states
                    and working.call_states[item.producer_call_id].status
                    == "verified"
                )
            )
        )
    )
    if not visible:
        return None
    ancestors = working.identity_index.visibility.registry.ancestor_scopes(
        consumer_scope_id
    )
    ranks = {scope_id: index for index, scope_id in enumerate(ancestors)}
    closest_rank = min(
        ranks.get(item.valid_scope_id, len(ancestors)) for item in visible
    )
    closest = tuple(
        item
        for item in visible
        if ranks.get(item.valid_scope_id, len(ancestors)) == closest_rank
    )
    maximal = tuple(
        candidate
        for candidate in closest
        if not any(
            other.version_id != candidate.version_id
            and _runtime_version_descends_from(
                other.version_id,
                candidate.version_id,
                working=working,
            )
            for other in closest
        )
    )
    if len(maximal) != 1:
        raise ValueError(
            "planner_configuration_error: "
            "planner.runtime_parameter_state_ambiguous: "
            f"object_id={object_id.to_payload()}, versions="
            f"{[item.version_id.to_payload() for item in maximal]}"
        )
    return maximal[0]


def _runtime_version_descends_from(
    candidate_id: StateVersionId,
    ancestor_id: StateVersionId,
    *,
    working: WorkingPlannerState,
) -> bool:
    pending = [candidate_id]
    visited: set[StateVersionId] = set()
    while pending:
        current = pending.pop()
        if current == ancestor_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        version = working.identity_index.version(current)
        if version is None:
            continue
        if version.previous_version_id is not None:
            pending.append(version.previous_version_id)
        pending.extend(version.source_version_ids)
    return False


def _substitute_runtime_parameters(
    value: Any,
    substitutions: Mapping[sp.Symbol, Any],
) -> Any:
    if isinstance(value, sp.Basic):
        return sp.simplify(value.subs(substitutions))
    if isinstance(value, PointRef):
        return replace(
            value,
            definition=_substitute_runtime_parameters(
                value.definition,
                substitutions,
            ),
        )
    if isinstance(value, Mapping):
        return {
            key: _substitute_runtime_parameters(item, substitutions)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            _substitute_runtime_parameters(item, substitutions)
            for item in value
        )
    if isinstance(value, list):
        return [
            _substitute_runtime_parameters(item, substitutions)
            for item in value
        ]
    return value


def _with_runtime_parameter_sources(
    write: StateWriteProvenance,
    parameter_version_ids: Sequence[StateVersionId],
) -> StateWriteProvenance:
    if not parameter_version_ids:
        return write
    source_version_ids = unique_ordered(
        (*write.source_version_ids, *parameter_version_ids)
    )
    lineage = replace(
        write.lineage,
        source_version_ids=unique_ordered(
            (*write.lineage.source_version_ids, *parameter_version_ids)
        ),
    )
    computation_key = write.computation_key
    if computation_key is not None:
        existing_versions = {
            item.version_id for item in computation_key.arg_bindings
        }
        additions = tuple(
            ArgVersionBinding(
                arg_name=_IMPLICIT_PARAMETER_ARG,
                item_index=index,
                version_id=version_id,
            )
            for index, version_id in enumerate(parameter_version_ids)
            if version_id not in existing_versions
        )
        computation_key = replace(
            computation_key,
            arg_bindings=tuple(
                (*computation_key.arg_bindings, *additions)
            ),
        )
    return replace(
        write,
        source_version_ids=source_version_ids,
        lineage=lineage,
        computation_key=computation_key,
    )


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


def _validate_symbolic_closure_write_set(
    writes: Sequence[StateWriteProvenance],
    *,
    closure_result: Any,
    compiled: CompiledFunctionalCall,
) -> None:
    provenance = closure_result.provenance
    affected = set(closure_result.affected_returns)
    materialized = tuple(
        write for write in writes if write.return_name in affected
    )
    expected_returns = affected & {
        returned.return_name
        for returned in compiled.public_returns
    }
    issues = audit_symbolic_closure_writes(
        tuple(
            SymbolicClosureWriteAuditRecord(
                return_name=write.return_name,
                runtime_type=write.runtime_type,
                math_object_id=write.math_object_id,
                free_symbol_ids=write.free_symbol_ids,
                provenance=write.symbolic_closure_provenance,
            )
            for write in materialized
        ),
        expected_provenance=provenance,
        expected_return_names=frozenset(expected_returns),
    )
    if issues:
        issue = issues[0]
        detail = (
            f": {issue.details}"
            if issue.details is not None
            else ""
        )
        raise SymbolicClosureProvenanceError(
            issue.code,
            issue.message + detail,
        )


def _closure_failure_details(
    result: Any,
    *,
    call_id: str,
    graph: LogicalFunctionalGraph,
) -> dict[str, Any]:
    """Project actionable closure facts without leaking typed runtime IDs."""
    node_by_id = {item.call_id: item for item in graph.calls}
    repair_calls: list[str] = []

    # Repair mathematical sources upstream of the failed closure.
    pending = [call_id]
    while pending:
        current = pending.pop()
        if current in repair_calls:
            continue
        repair_calls.append(current)
        node = node_by_id.get(current)
        if node is not None:
            pending.extend(node.dependency_call_ids)

    # Also unlock the failed call's own route to its answer, without walking
    # sideways from an upstream source into unrelated consumer branches.
    pending = list(
        node_by_id.get(call_id).consumer_call_ids
        if call_id in node_by_id
        else ()
    )
    while pending:
        current = pending.pop()
        if current in repair_calls:
            continue
        repair_calls.append(current)
        node = node_by_id.get(current)
        if node is not None:
            pending.extend(node.consumer_call_ids)
    provenance = result.provenance
    details: dict[str, Any] = {
        "status": result.status,
        "branch_count": result.branch_count,
        "repair_call_ids": repair_calls,
    }
    if result.target_object_id is not None:
        details["target"] = result.target_object_id.value.rsplit(":", 1)[-1]
    if result.residual_symbol_ids:
        details["remaining_free"] = [
            item.value.rsplit(":", 1)[-1]
            for item in result.residual_symbol_ids
        ]
    if provenance is not None:
        if provenance.equation_sources:
            details["equation_sources"] = list(
                provenance.equation_sources[:3]
            )
        if provenance.constraint_filter is not None:
            details["constraint_used"] = True
    elif result.validation_build is not None:
        equation_sources = result.validation_build.equation_sources
        if equation_sources:
            details["equation_sources"] = list(equation_sources[:3])
    return details


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


def _materialized_runtime_path(
    compiled: CompiledFunctionalCall,
    write: StateWriteProvenance,
) -> str | None:
    """Return the path that contains this call's actual materialized value.

    A reuse allocation still points at the selected canonical destination in
    typed state authority. Its candidate value must instead be read from the
    isolated runtime probe emitted by the compiler; reading the canonical path
    would make every comparison vacuously equal.
    """

    plan_path = _runtime_path_for_write(compiled.plans, write)
    if write.allocation_action == "reuse" and plan_path is not None:
        return plan_path
    if write.runtime_destination_key is not None:
        return write.runtime_destination_key.runtime_path
    return plan_path


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
        path = _materialized_runtime_path(compiled, write)
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
        path = _materialized_runtime_path(compiled, write)
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
        path = _materialized_runtime_path(compiled, write)
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


def _compare_provisional_runtime_state(
    *,
    call_id: str,
    writes: Sequence[StateWriteProvenance],
    runtime_values: Mapping[StateVersionId, TypedValue],
    reconciliation: FunctionalPlanReconciliationResult,
    working: WorkingPlannerState,
    branch: RuntimeContext,
    object_registry: MathObjectRegistry,
) -> tuple[
    FunctionalRuntimeEquivalentCallAlias | None,
    PlannerRetryIssue | None,
]:
    """Resolve possible duplicate writers using actual typed runtime values.

    Static allocation only identifies a candidate.  Equal values reuse the
    existing version, a runtime-proven dependency refinement commits the new
    version, and every other result is rejected before the branch is exposed.
    """

    if not writes:
        return None, None
    calls = {item.call_id: item for item in reconciliation.calls}
    current = calls.get(call_id)
    if current is None:
        return None, None
    allocations = {
        item.return_name: item for item in current.returns
    }
    rows: list[
        tuple[
            StateWriteProvenance,
            FunctionalReturnAllocation,
            StateVersionId,
            str,
        ]
    ] = []
    for write in writes:
        if write.selected_version_id is None or write.return_name is None:
            return None, None
        allocation = allocations.get(write.return_name)
        if allocation is None:
            return None, None
        if write.allocation_action == "reuse":
            existing_version_id = write.selected_version_id
            producer_id = write.canonical_producer_call_id or call_id
        elif (
            write.allocation_action == "transition"
            and allocation.allocation_reason_code
            == "runtime_state_equivalence_probe"
            and write.previous_version_id is not None
        ):
            existing_version_id = write.previous_version_id
            producer_id = allocation.previous_write_step_id or call_id
        else:
            return None, None
        rows.append(
            (write, allocation, existing_version_id, producer_id)
        )

    producer_ids = {item[3] for item in rows}
    if len(producer_ids) != 1:
        return None, _issue(
            call_id,
            "planner.runtime_state_equivalence_conflict",
            "provisional typed writes do not identify one prior producer",
            details={"canonical_producer_call_ids": sorted(producer_ids)},
        )
    producer_id = next(iter(producer_ids))
    source_state_reuse = producer_id == call_id
    if not source_state_reuse and (
        producer_id in working.call_states
        and working.call_states[producer_id].status != "verified"
    ):
        return None, _issue(
            call_id,
            "planner.runtime_state_equivalence_conflict",
            "reused typed state was not produced by a verified prior call",
            details={"canonical_producer_call_id": producer_id},
        )

    producer = calls.get(producer_id)
    if producer is None and not source_state_reuse:
        return None, _issue(
            call_id,
            "planner.runtime_state_equivalence_conflict",
            "canonical producer is absent from the reconciled plan",
            details={"canonical_producer_call_id": producer_id},
        )

    return_aliases: list[tuple[str, str]] = []
    comparison_rows: list[dict[str, Any]] = []
    selected_version_ids: list[StateVersionId] = []
    conflicts: list[dict[str, Any]] = []
    refinement_seen = False
    declared = _context_runtime_symbol_bindings(
        branch,
        registry=object_registry,
    )
    for write, _allocation, existing_version_id, _ in rows:
        candidate_version_id = write.selected_version_id
        assert candidate_version_id is not None
        candidate = runtime_values.get(candidate_version_id)
        existing = working.runtime_version_values.get(existing_version_id)
        indexed = working.identity_index.version(existing_version_id)
        canonical_returns = (
            (str(write.return_name),)
            if source_state_reuse
            else (
                tuple(
                    allocation.return_name
                    for allocation in producer.returns
                    if allocation.selected_version_id == existing_version_id
                )
                if producer is not None
                else (str(write.return_name),)
            )
        )
        reasons: list[str] = []
        comparison = "equivalent"
        if candidate is None or existing is None or indexed is None:
            reasons.append("runtime_value_or_state_version_missing")
        else:
            if not (
                runtime_type_compatible(existing.type, candidate.type)
                and runtime_type_compatible(candidate.type, existing.type)
            ):
                reasons.append("runtime_type_mismatch")
            raw_equivalent = _symbolic_values_equivalent(
                existing.value,
                candidate.value,
            )
            same_symbols = frozenset(indexed.free_symbol_ids) == frozenset(
                write.free_symbol_ids
            )
            if not (raw_equivalent and same_symbols):
                materialized_existing = (
                    _materialize_runtime_parameter_closure(
                        existing,
                        consumer_scope_id=(
                            write.valid_scope_id or write.scope_id
                        ),
                        working=working,
                        runtime_context=branch,
                        object_registry=object_registry,
                        declared_runtime_symbols=_merge_runtime_symbol_bindings(
                            declared,
                            working.runtime_version_symbol_bindings.get(
                                existing_version_id,
                                {},
                            ),
                        ),
                    )
                )
                strictly_closes_symbols = set(
                    write.free_symbol_ids
                ) < set(indexed.free_symbol_ids)
                if (
                    strictly_closes_symbols
                    and _symbolic_values_equivalent(
                        materialized_existing.runtime_value.value,
                        candidate.value,
                    )
                ):
                    if source_state_reuse:
                        comparison = "equivalent_materialized_source"
                    else:
                        comparison = "dependency_refinement"
                        refinement_seen = True
                else:
                    if not raw_equivalent:
                        reasons.append("runtime_value_mismatch")
                    if not same_symbols:
                        reasons.append("free_symbol_identity_mismatch")
        if len(canonical_returns) != 1:
            reasons.append("canonical_return_ambiguous")
        if reasons:
            conflicts.append(
                {
                    "return": write.return_name,
                    "candidate_version_id": candidate_version_id.to_payload(),
                    "existing_version_id": existing_version_id.to_payload(),
                    "reasons": reasons,
                    "canonical_return_candidates": list(canonical_returns),
                }
            )
            continue
        return_aliases.append(
            (str(write.return_name), canonical_returns[0])
        )
        selected_version_ids.append(existing_version_id)
        comparison_rows.append(
            {
                "duplicate_return": write.return_name,
                "canonical_return": canonical_returns[0],
                "candidate_version_id": candidate_version_id.to_payload(),
                "selected_version_id": existing_version_id.to_payload(),
                "runtime_type": candidate.type,
                "value": _runtime_equivalence_value_payload(candidate.value),
                "comparison": comparison,
                "free_symbol_ids": sorted(
                    (
                        item.to_payload()
                        for item in write.free_symbol_ids
                    ),
                    key=lambda item: stable_hash(item),
                ),
            }
        )
    if conflicts:
        return None, _issue(
            call_id,
            "planner.runtime_state_equivalence_conflict",
            "a possible duplicate call produced a different typed runtime state",
            details={
                "canonical_producer_call_id": producer_id,
                "comparisons": conflicts,
            },
        )
    if refinement_seen:
        return None, None
    alias_payload = {
        "duplicate_call_id": call_id,
        "canonical_call_id": producer_id,
        "return_aliases": sorted(return_aliases),
        "comparisons": comparison_rows,
    }
    return (
        FunctionalRuntimeEquivalentCallAlias(
            duplicate_call_id=call_id,
            canonical_call_id=producer_id,
            return_aliases=tuple(sorted(return_aliases)),
            selected_version_ids=unique_ordered(selected_version_ids),
            comparison_signature=stable_hash(alias_payload),
        ),
        None,
    )


def _runtime_equivalence_value_payload(value: Any) -> Any:
    if isinstance(value, sp.Basic):
        return {"sympy": sp.srepr(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _runtime_equivalence_value_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_runtime_equivalence_value_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "to_payload"):
        return _runtime_equivalence_value_payload(value.to_payload())
    return repr(value)


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


def _canonical_runtime_writes_by_version(
    state_writes: Sequence[StateWriteProvenance],
) -> dict[StateVersionId, StateWriteProvenance]:
    """Index each version by its real object write, not an answer alias."""

    result: dict[StateVersionId, StateWriteProvenance] = {}
    for write in state_writes:
        version_id = write.selected_version_id
        if version_id is None:
            continue
        existing = result.get(version_id)
        if existing is None or (
            existing.produced_handle.startswith("answer:")
            and not write.produced_handle.startswith("answer:")
        ):
            result[version_id] = write
    return result


def _transactional_diagnostic(
    report: FunctionalTransactionalExecutionReport,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    runtime_results: tuple[FunctionalRuntimeResult, ...],
    state_writes: tuple[StateWriteProvenance, ...],
) -> FunctionalExecutionDiagnostic:
    calls = {item.call_id: item for item in reconciliation.calls}
    compiled = {item.call_id: item for item in report.compiled_calls}
    accepted = tuple(
        FunctionalAcceptedStep(
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
    return FunctionalExecutionDiagnostic(
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
        for item in build_functional_state_write_manifest(
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
    # Aggregate output reuses the same B3 authority as each call transaction.
    StateFinalizationService().finalize_compiled_graph(
        projected_writes,
        goal_writes,
        plans,
        question_goals=tuple(inputs.question_goals),
        handle_registry=handle_registry,
        mode="authoritative",
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


def _functional_goal_producers(
    graph: LogicalFunctionalGraph,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    capability_catalog: FunctionalCapabilityCatalog,
    state_writes: Sequence[StateWriteProvenance],
) -> dict[str, FunctionalGoalProducer]:
    """Project typed answer producers from canonical transactional calls."""

    calls = {item.call_id: item for item in graph.calls}
    reconciled_calls = {
        item.call_id: item for item in reconciliation.calls
    }
    writes_by_call: dict[str, list[StateWriteProvenance]] = {}
    for write in state_writes:
        writes_by_call.setdefault(write.step_id, []).append(write)
    result: dict[str, FunctionalGoalProducer] = {}
    for binding in graph.answer_bindings:
        call = calls.get(binding.producer_call_id)
        if call is None:
            continue
        capability = capability_catalog.get(call.capability_id)
        reconciled_call = reconciled_calls.get(call.call_id)
        if capability is None or reconciled_call is None:
            continue
        writes = writes_by_call.get(call.call_id, ())
        reads = tuple(
            unique_ordered(
                (
                    *(
                        handle
                        for values in reconciled_call.resolved_args.values()
                        for value in values
                        for handle in (
                            value.handle,
                            value.object_ref,
                            *value.supporting_handles,
                        )
                        if isinstance(handle, str) and handle
                    ),
                    *(
                        handle
                        for write in writes
                        for handle in write.source_handles
                        if isinstance(handle, str) and handle
                    ),
                )
            )
        )
        creates = tuple(
            FunctionalGoalArtifact(allocation.math_object_id.value)
            for allocation in reconciled_call.returns
            if allocation.math_object_id is not None
            and allocation.write_mode == "create"
        )
        produces = tuple(
            FunctionalGoalArtifact(handle)
            for handle in unique_ordered(
                handle
                for allocation in reconciled_call.returns
                for handle in (
                    allocation.state_handle,
                    allocation.handle,
                )
                if isinstance(handle, str) and handle
            )
        )
        result[binding.answer_handle] = FunctionalGoalProducer(
            step_id=call.call_id,
            scope_id=call.execution_scope_id,
            goal_type=capability.goal_type,
            target=binding.answer_handle,
            reads=reads,
            creates=creates,
            produces=produces,
        )
    return result


def _issue(
    call_id: str | None,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    diagnostic_authority: dict[str, Any] | None = None,
) -> PlannerRetryIssue:
    return PlannerRetryIssue(
        layer="trial_execution",
        code=code,
        step_id=call_id,
        repair_target="call",
        preserve_policy="preserve_graph",
        message=message,
        details=details,
        diagnostic_authority=diagnostic_authority,
    )


def _runtime_result(
    context: RuntimeContext,
    *,
    write: StateWriteProvenance,
    value: Any,
) -> FunctionalRuntimeResult:
    try:
        projected = context.to_answer_value(value)
    except Exception as exc:
        return FunctionalRuntimeResult(
            step_id=write.step_id,
            scope_id=write.scope_id,
            capability_id=write.capability_id,
            produced_handle=write.produced_handle,
            output_key=write.output_key,
            runtime_type=write.runtime_type,
            value_omitted_reason=(
                f"unsupported_transaction_snapshot:{type(exc).__name__}"
            ),
            problem_source_provenance=write.problem_source_provenance,
        )
    return FunctionalRuntimeResult(
        step_id=write.step_id,
        scope_id=write.scope_id,
        capability_id=write.capability_id,
        produced_handle=write.produced_handle,
        output_key=write.output_key,
        runtime_type=write.runtime_type,
        value=projected,
        problem_source_provenance=write.problem_source_provenance,
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
    "FunctionalCallCompilerService",
    "FunctionalCallExecutionResult",
    "FunctionalCallPreparationService",
    "FunctionalRuntimeWriteCommitter",
    "FunctionalRuntimeEquivalentCallAlias",
    "FunctionalRestoredCallSeed",
    "FunctionalTransactionalAttemptResult",
    "FunctionalTransactionalExecutionReport",
    "FunctionalTransactionalInterpreter",
    "PreparedFunctionalCall",
    "build_functional_runtime_arg_bindings",
]
