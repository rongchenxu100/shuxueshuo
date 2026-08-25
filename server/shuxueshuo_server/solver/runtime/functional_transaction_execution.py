"""Transactional execution for canonical Functional calls.

C1 keeps this interpreter as an execution shadow. C2 can promote its actual
call results, StateVersions, goal closure, Context and retry projection to the
Functional authority while legacy replay remains available as a comparison
oracle.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    CoefficientExtractionDerivationSpec,
    EntityIdentitySourceSpec,
    ExactCallResultSourceSpec,
    FreeSymbolBasisDerivationSpec,
    LatestStateSourceSpec,
    MacroPreparedRoleSourceSpec,
    MethodInputBindingSpec,
    OrdinalZeroTemplateDerivationSpec,
    PointRef,
    PreviousOutputIdentityDerivationSpec,
    TypedValue,
    VerificationOutcome,
)
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    FunctionalProblemBindingLedger,
    FunctionalProblemBindingContext,
    FunctionalProblemCallBinding,
    FunctionalProblemInputBinding,
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
from shuxueshuo_server.solver.runtime.method_output_write_authority import (
    CallResultOutputDestinationAuthority,
    MethodOutputWriteAuthority,
    StateOutputDestinationAuthority,
)
from shuxueshuo_server.solver.runtime.predicate_condition_publication import (
    PredicateConditionPublicationService,
    PredicatePublicationAuthority,
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
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
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
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedDerivedResultRef,
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
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroCandidateEvaluation as LegacyMacroCandidateEvaluation,
    MacroRoleResolution,
    MacroRuntimeSearchError,
    MacroRuntimeSearchReport,
)
from shuxueshuo_server.solver.runtime.functional_subplan import (
    CandidateEvaluation,
    CandidateSearchReport,
    FragmentRuntimeSource,
    FunctionalPlanFragmentExecution,
    FunctionalPlanFragmentTransactionalRunner,
    MacroSearchSelection,
    VerifiedSubplanExecution,
    VerifiedSubplanCleanExecution,
    VerifiedSubplanWitness,
    fragment_published_condition_refs,
)
from shuxueshuo_server.solver.runtime.macro_definitions import (
    default_macro_definition_registry,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroCandidateBindingAuthority,
    MacroPreparationEnvironment,
    MacroPreparationRequest,
    MacroPreparationService,
    PreparedMacroInvocation,
)
from shuxueshuo_server.solver.runtime.planner_failure_classification import (
    is_planner_configuration_failure_code,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpec
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CallResultReadSource,
    ConditionReadSource,
    DerivedInputReadSource,
    EntityIdentityReadSource,
    InvocationResultReadSource,
    MethodInputReadAuthority,
    StateVersionReadSource,
)
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.models import (
    ContextDeclaration,
    ContextPath,
    MethodInvocation,
    PlanExecutionResult,
    PlannerOutput,
    StepExecutionResult,
    StepGoal,
    StepPlan,
    TypedValue,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    Condition,
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.output_type_inference import (
    semantic_name_from_handle,
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
    StateRuntimeEquivalenceProbe,
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
from shuxueshuo_server.solver.state_semantics import (
    merge_state_semantic_lineages,
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
    problem_call_binding: FunctionalProblemCallBinding | None = None
    macro_role_overrides: Mapping[str, str] = field(default_factory=dict)
    macro_candidate_binding: MacroCandidateBindingAuthority | None = None
    prepared_macro: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "macro_role_overrides",
            MappingProxyType(dict(sorted(self.macro_role_overrides.items()))),
        )


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
    runtime_path: str | None = None


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
    problem_call_binding: FunctionalProblemCallBinding | None = None
    macro_preparation_authority: Any | None = None
    macro_search_report: CandidateSearchReport | None = None
    fragment_execution: FunctionalPlanFragmentExecution | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    verified_subplan_execution: VerifiedSubplanExecution | None = None
    materialized_state_sources: tuple[tuple[str, StateVersionId], ...] = ()
    output_write_authorities: tuple[MethodOutputWriteAuthority, ...] = ()
    predicate_publication_authorities: tuple[
        PredicatePublicationAuthority, ...
    ] = ()


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
    macro_preparation_authority: Any | None = None
    macro_search_report: CandidateSearchReport | None = None
    verified_subplan_execution: VerifiedSubplanExecution | None = None
    verification_outcomes: tuple[VerificationOutcome, ...] = ()
    published_conditions: tuple[Condition, ...] = ()
    step_results: tuple[StepExecutionResult, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

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
            "macro_search_report": (
                self.macro_search_report.to_payload()
                if self.macro_search_report is not None
                else None
            ),
            "macro_preparation_authority": (
                self.macro_preparation_authority.authority_payload()
                if self.macro_preparation_authority is not None
                else None
            ),
            "verified_subplan_execution": (
                self.verified_subplan_execution.to_payload()
                if self.verified_subplan_execution is not None
                else None
            ),
            "verification_outcomes": [
                item.to_payload() for item in self.verification_outcomes
            ],
            "published_conditions": [
                item.to_payload() for item in self.published_conditions
            ],
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
    conditions: Mapping[str, Condition] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    runtime_version_aliases: Mapping[
        StateVersionId,
        StateVersionId,
    ] = field(default_factory=dict, repr=False, compare=False)
    runtime_equivalent_aliases: tuple[
        "FunctionalRuntimeEquivalentCallAlias", ...
    ] = ()
    runtime_state_equivalence_probe_results: tuple[dict[str, Any], ...] = ()
    functional_problem_binding_ledger: FunctionalProblemBindingLedger | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    runtime_context: RuntimeContext | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def executed_call_ids(self) -> tuple[str, ...]:
        """Calls that actually entered the runtime, excluding restores."""

        return tuple(
            dict.fromkeys(
                event.call_id
                for event in self.events
                if event.event == "running"
            )
        )

    def resolve_runtime_version_id(
        self,
        version_id: StateVersionId,
    ) -> StateVersionId:
        current = version_id
        visited: set[StateVersionId] = set()
        while current in self.runtime_version_aliases:
            if current in visited:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_equivalent_version_alias_cycle"
                )
            visited.add(current)
            current = self.runtime_version_aliases[current]
        return current

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
            "executed_call_ids": list(self.executed_call_ids),
            "executed_call_count": len(self.executed_call_ids),
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
            "runtime_state_equivalence_probe_results": [
                dict(item)
                for item in self.runtime_state_equivalence_probe_results
            ],
            "functional_problem_binding_ledger": (
                {
                    "schema_version": (
                        self.functional_problem_binding_ledger.schema_version
                    ),
                    "draft_signature": (
                        self.functional_problem_binding_ledger
                        .draft.draft_signature
                    ),
                    "ledger_signature": (
                        self.functional_problem_binding_ledger.ledger_signature
                    ),
                    "calls": {
                        call_id: binding.authority_payload()
                        for call_id, binding in (
                            self.functional_problem_binding_ledger.calls.items()
                        )
                    },
                }
                if self.functional_problem_binding_ledger is not None
                else None
            ),
            "runtime_version_aliases": [
                {
                    "candidate_version_id": candidate.to_payload(),
                    "canonical_version_id": canonical.to_payload(),
                }
                for candidate, canonical in sorted(
                    self.runtime_version_aliases.items()
                )
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
class FunctionalRestoredCallResult:
    """One exact anonymous/public return restored with its typed authority."""

    call_id: str
    return_name: str
    scope_id: str
    runtime_type: str
    runtime_value: TypedValue
    problem_source_provenance: ProblemCallSourceProvenance | None = None

    @property
    def prompt_ref(self) -> dict[str, str]:
        return {"step_id": self.call_id, "return": self.return_name}


@dataclass(frozen=True)
class FunctionalRestoredTypedValueIndex:
    """Exact typed namespaces restored from one authenticated checkpoint."""

    state_versions: Mapping[StateVersionId, TypedValue] = field(
        default_factory=dict
    )
    call_results: Mapping[
        tuple[str, str], FunctionalRestoredCallResult
    ] = field(
        default_factory=dict
    )
    conditions: Mapping[str, Condition] = field(default_factory=dict)

    def state_value(self, version_id: StateVersionId) -> TypedValue | None:
        return self.state_versions.get(version_id)

    def call_result_value(
        self,
        call_id: str,
        return_name: str,
    ) -> TypedValue | None:
        result = self.call_results.get((call_id, return_name))
        return result.runtime_value if result is not None else None

    def call_result(
        self,
        call_id: str,
        return_name: str,
    ) -> FunctionalRestoredCallResult | None:
        return self.call_results.get((call_id, return_name))

    def condition_value(self, condition_id: str) -> Condition | None:
        return self.conditions.get(condition_id)


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
    call_result_records: Mapping[
        tuple[str, str], FunctionalRestoredCallResult
    ] = field(
        default_factory=dict
    )
    conditions: Mapping[str, Condition] = field(
        default_factory=dict
    )
    source_read_authorities: Mapping[str, str] = field(default_factory=dict)
    source_read_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    runtime_write_authorities: Mapping[str, str] = field(default_factory=dict)
    runtime_write_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    publication_authorities: Mapping[str, str] = field(default_factory=dict)
    publication_payloads: Mapping[str, Mapping[str, Any]] = field(
        default_factory=dict
    )
    mutable_publication_goal_unit_ids: tuple[str, ...] = ()
    call_reconciliations: Mapping[
        str,
        FunctionalCallReconciliation,
    ] = field(default_factory=dict)

    @property
    def call_ids(self) -> tuple[str, ...]:
        return tuple(item.call_id for item in self.call_results)

    @property
    def typed_value_index(self) -> FunctionalRestoredTypedValueIndex:
        return FunctionalRestoredTypedValueIndex(
            state_versions=self.runtime_version_values,
            call_results=self.call_result_records,
            conditions=self.conditions,
        )


def build_functional_execution_restore_seed(
    report: FunctionalTransactionalExecutionReport,
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    call_ids: frozenset[str] | None = None,
    mutable_publication_goal_unit_ids: tuple[str, ...] = (),
) -> FunctionalRestoredCallSeed:
    """Build the one typed restore authority from a verified transaction."""

    selected = (
        frozenset(call_ids)
        if call_ids is not None
        else frozenset(
            item.call_id
            for item in report.call_results
            if item.status == "verified"
        )
    )
    result_by_call = {item.call_id: item for item in report.call_results}
    compiled_by_call = {item.call_id: item for item in report.compiled_calls}
    reconciliation_by_call = {
        item.call_id: item for item in reconciliation.calls
    }
    missing = tuple(
        sorted(
            call_id
            for call_id in selected
            if (
                call_id not in result_by_call
                or result_by_call[call_id].status != "verified"
                or call_id not in compiled_by_call
                or call_id not in reconciliation_by_call
            )
        )
    )
    if missing:
        raise ValueError(
            "planner_configuration_error: "
            "functional.goal_retry_restore_drift: "
            f"verified restore authority is missing calls {list(missing)}"
        )
    version_ids = {
        version.version_id
        for call_id in selected
        for version in result_by_call[call_id].committed_versions
    }
    result_keys = {
        key for key in report.runtime_result_values if key[0] in selected
    }
    call_result_records = _build_restored_call_result_records(
        report,
        result_keys=result_keys,
    )
    logical_binding_context = reconciliation.functional_binding_context
    condition_ids = {
        binding.source.condition_id
        for binding in (
            logical_binding_context.bindings
            if logical_binding_context is not None
            else ()
        )
        if binding.key.call_id in selected
        and binding.source.kind == "condition"
        and binding.source.condition_id is not None
    }
    missing_conditions = condition_ids - set(report.conditions)
    if missing_conditions:
        raise ValueError(
            "planner_configuration_error: "
            "functional.goal_retry_restore_drift: "
            "verified restore authority is missing Conditions "
            f"{sorted(missing_conditions)}"
        )
    authority_payloads = {
        call_id: functional_restored_call_authority_payloads(
            reconciliation,
            call_id,
        )
        for call_id in selected
    }
    authority_signatures = {
        call_id: {
            key: stable_hash(value)
            for key, value in payloads.items()
        }
        for call_id, payloads in authority_payloads.items()
    }
    return FunctionalRestoredCallSeed(
        call_results=tuple(
            result_by_call[call_id]
            for call_id in report.graph.canonical_order
            if call_id in selected
        ),
        compiled_calls=tuple(
            compiled_by_call[call_id]
            for call_id in report.graph.canonical_order
            if call_id in selected
        ),
        runtime_version_values={
            version_id: value
            for version_id, value in report.runtime_version_values.items()
            if version_id in version_ids
        },
        runtime_version_symbol_bindings={
            version_id: bindings
            for version_id, bindings in (
                report.runtime_version_symbol_bindings.items()
            )
            if version_id in version_ids
        },
        call_result_records=call_result_records,
        conditions={
            condition_id: report.conditions[condition_id]
            for condition_id in sorted(condition_ids)
        },
        source_read_authorities={
            call_id: authority_signatures[call_id]["source_read"]
            for call_id in selected
        },
        source_read_payloads={
            call_id: authority_payloads[call_id]["source_read"]
            for call_id in selected
        },
        runtime_write_authorities={
            call_id: authority_signatures[call_id]["runtime_write"]
            for call_id in selected
        },
        runtime_write_payloads={
            call_id: authority_payloads[call_id]["runtime_write"]
            for call_id in selected
        },
        publication_authorities={
            call_id: authority_signatures[call_id]["answer_publication"]
            for call_id in selected
        },
        publication_payloads={
            call_id: authority_payloads[call_id]["answer_publication"]
            for call_id in selected
        },
        mutable_publication_goal_unit_ids=(
            mutable_publication_goal_unit_ids
        ),
        call_reconciliations={
            call_id: reconciliation_by_call[call_id]
            for call_id in selected
        },
    )


def _build_restored_call_result_records(
    report: FunctionalTransactionalExecutionReport,
    *,
    result_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], FunctionalRestoredCallResult]:
    runtime_results = {
        (call.call_id, item.output_key): item
        for call in report.call_results
        for item in call.runtime_results
    }
    compiled_returns: dict[tuple[str, str], tuple[Any, CompiledPublicReturn]] = {}
    for compiled in report.compiled_calls:
        for returned in compiled.public_returns:
            keys = {returned.return_name}
            if returned.expected_write is not None:
                keys.add(returned.expected_write.output_key)
            for output_key in keys:
                compiled_returns[(compiled.call_id, output_key)] = (
                    compiled,
                    returned,
                )
    records: dict[tuple[str, str], FunctionalRestoredCallResult] = {}
    for key in sorted(result_keys):
        compiled_return = compiled_returns.get(key)
        if compiled_return is None:
            raise ValueError(
                "planner_configuration_error: "
                "functional.goal_retry_restore_drift: "
                f"CallResultId {key!r} has no compiled return authority"
            )
        compiled, returned = compiled_return
        runtime_result = runtime_results.get(key)
        records[key] = FunctionalRestoredCallResult(
            call_id=key[0],
            return_name=key[1],
            scope_id=returned.allocation.valid_scope,
            runtime_type=returned.allocation.runtime_type,
            runtime_value=report.runtime_result_values[key],
            problem_source_provenance=(
                runtime_result.problem_source_provenance
                if runtime_result is not None
                else compiled.problem_source_provenance
            ),
        )
    return records


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
    rebased_results: list[FunctionalCallExecutionResult] = []
    rebased_compiled: list[CompiledFunctionalCall] = []
    for result in seed.call_results:
        call_id = result.call_id
        call = calls.get(call_id)
        compiled = compiled_by_call.get(call_id)
        expected_source = seed.source_read_authorities.get(call_id)
        expected_write = seed.runtime_write_authorities.get(call_id)
        expected_publication = seed.publication_authorities.get(call_id)
        if (
            call is None
            or compiled is None
            or expected_source is None
            or expected_write is None
            or expected_publication is None
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.retry_problem_source_binding_drift: "
                f"restored call authority is missing for {call_id}"
            )
        actual_source_payload = _restorable_call_source_read_payload(
            call,
            binding_context=binding_context,
        )
        actual_source = stable_hash(actual_source_payload)
        if actual_source != expected_source:
            expected_payload = seed.source_read_payloads.get(call_id)
            raise FunctionalRestoredCallBindingError(
                call_id,
                f"source reads changed for restored call {call_id}",
                details={
                    "authority_kind": "source_read",
                    "expected_signature": expected_source,
                    "actual_signature": actual_source,
                    "first_difference": (
                        _first_payload_difference(
                            expected_payload,
                            actual_source_payload,
                        )
                        if expected_payload is not None
                        else None
                    ),
                    "expected_binding": expected_payload,
                    "actual_binding": actual_source_payload,
                },
            )
        actual_write_payload = _restorable_call_runtime_write_payload(call)
        actual_write = stable_hash(actual_write_payload)
        if actual_write != expected_write:
            expected_payload = seed.runtime_write_payloads.get(call_id)
            raise FunctionalRestoredCallBindingError(
                call_id,
                f"runtime writes changed for restored call {call_id}",
                code="planner.contract_runtime_destination_drift",
                details={
                    "authority_kind": "runtime_write",
                    "expected_signature": expected_write,
                    "actual_signature": actual_write,
                    "first_difference": (
                        _first_payload_difference(
                            expected_payload,
                            actual_write_payload,
                        )
                        if expected_payload is not None
                        else None
                    ),
                    "expected_binding": expected_payload,
                    "actual_binding": actual_write_payload,
                },
            )
        actual_publication_payload = _restorable_call_publication_payload(
            call,
            binding_context=binding_context,
        )
        comparable_actual_publication = _filter_mutable_publication_authority(
            actual_publication_payload,
            mutable_goal_unit_ids=seed.mutable_publication_goal_unit_ids,
        )
        expected_publication_payload = seed.publication_payloads.get(call_id)
        comparable_expected_publication = _filter_mutable_publication_authority(
            expected_publication_payload or {},
            mutable_goal_unit_ids=seed.mutable_publication_goal_unit_ids,
        )
        if stable_hash(comparable_actual_publication) != stable_hash(
            comparable_expected_publication
        ):
            raise FunctionalRestoredCallBindingError(
                call_id,
                f"answer publication changed for restored call {call_id}",
                details={
                    "authority_kind": "answer_publication",
                    "expected_signature": expected_publication,
                    "actual_signature": stable_hash(actual_publication_payload),
                    "first_difference": _first_payload_difference(
                        comparable_expected_publication,
                        comparable_actual_publication,
                    ),
                    "expected_binding": expected_publication_payload,
                    "actual_binding": actual_publication_payload,
                    "comparable_expected_binding": (
                        comparable_expected_publication
                    ),
                    "comparable_actual_binding": (
                        comparable_actual_publication
                    ),
                },
            )
        previous = compiled.problem_source_provenance
        current = binding_context.source_provenance_for_call(call_id)
        if previous is not None and previous.macro_search_signature is not None:
            # The checkpoint owns the finalized Macro winner. Reconciliation
            # may refresh Goal consumers, but it must not rebuild or extend the
            # winner binding after execution.
            current = ProblemCallSourceProvenance(
                planning_context_id=current.planning_context_id,
                problem_revision_id=current.problem_revision_id,
                problem_semantic_hash=current.problem_semantic_hash,
                canonical_call_id=current.canonical_call_id,
                goal_unit_ids=current.goal_unit_ids,
                input_source_unit_ids=previous.input_source_unit_ids,
                call_binding_signature=previous.call_binding_signature,
                macro_search_signature=previous.macro_search_signature,
                macro_role_resolutions=previous.macro_role_resolutions,
            )
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


def functional_restored_call_authority_payloads(
    reconciliation: FunctionalPlanReconciliationResult,
    call_id: str,
) -> dict[str, dict[str, Any]]:
    """Return the three independently audited restore authorities."""

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
    return {
        "source_read": _restorable_call_source_read_payload(
            call,
            binding_context=binding_context,
        ),
        "runtime_write": _restorable_call_runtime_write_payload(call),
        "answer_publication": _restorable_call_publication_payload(
            call,
            binding_context=binding_context,
        ),
    }


def functional_restored_call_authority_signatures(
    reconciliation: FunctionalPlanReconciliationResult,
    call_id: str,
) -> dict[str, Any]:
    """Hash each restore authority independently."""

    return {
        key: stable_hash(value)
        for key, value in functional_restored_call_authority_payloads(
            reconciliation,
            call_id,
        ).items()
    }


def _restorable_call_source_read_payload(
    call: FunctionalCallReconciliation,
    *,
    binding_context: FunctionalProblemBindingContext,
) -> dict[str, Any]:
    return {
        "planning_context_id": binding_context.planning_context_id,
        "problem_revision_id": binding_context.problem_revision_id,
        "problem_semantic_hash": binding_context.problem_semantic_hash,
        "call_id": call.call_id,
        "scope_id": call.scope_id,
        "capability_id": call.capability_id,
        "resolved_args": {
            name: [item.to_payload() for item in values]
            for name, values in sorted(call.resolved_args.items())
        },
        "inputs": [
            item.to_payload()
            for item in binding_context.inputs_for_call(call.call_id)
        ],
    }


def _restorable_call_runtime_write_payload(
    call: FunctionalCallReconciliation,
) -> dict[str, Any]:
    publication_only_fields = {"bound_ref"}
    return {
        "call_id": call.call_id,
        "scope_id": call.scope_id,
        "capability_id": call.capability_id,
        "returns": [
            {
                key: value
                for key, value in item.to_payload().items()
                if key not in publication_only_fields
            }
            for item in call.returns
        ],
    }


def _restorable_call_publication_payload(
    call: FunctionalCallReconciliation,
    *,
    binding_context: FunctionalProblemBindingContext,
) -> dict[str, Any]:
    return {
        "call_id": call.call_id,
        "goal_unit_ids": list(
            binding_context.call_goal_bindings.get(call.call_id, ())
        ),
        "returns": [
            item.to_payload()
            for item in binding_context.returns_for_call(call.call_id)
        ],
    }


def _filter_mutable_publication_authority(
    payload: Mapping[str, Any],
    *,
    mutable_goal_unit_ids: Sequence[str],
) -> dict[str, Any]:
    """Keep only frozen Goal answer publications in restore comparison.

    Non-answer named returns are reconstructed from the canonical runtime
    write allocation. Their object, scope, type, and destination are already
    covered by ``runtime_write`` authority, so a partial graph omitting and a
    repaired graph restoring that public catalog entry are equivalent here.
    The call-to-Goal consumer closure is likewise rebuilt from the complete
    dependency graph; it is scheduling authority, not call identity.
    """

    mutable = set(mutable_goal_unit_ids)
    return {
        "call_id": payload.get("call_id"),
        "goal_unit_ids": [],
        "returns": [
            item
            for item in payload.get("returns", ())
            if isinstance(item, Mapping)
            and item.get("goal_unit_id") is not None
            and item.get("goal_unit_id") not in mutable
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


def _execution_problem_binding_ledger(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    compiled_calls: Sequence[CompiledFunctionalCall],
) -> FunctionalProblemBindingLedger | None:
    base = reconciliation.functional_problem_binding_ledger
    if base is None:
        return None
    if not isinstance(base, FunctionalProblemBindingLedger):
        raise ValueError(
            "planner_configuration_error: invalid F5-C binding ledger"
        )
    calls = dict(base.calls)
    for compiled in compiled_calls:
        binding = compiled.problem_call_binding
        if binding is not None:
            calls[compiled.call_id] = binding
    return FunctionalProblemBindingLedger(draft=base.draft, calls=calls)


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
        problem_binding_ledger = (
            reconciliation.functional_problem_binding_ledger
        )
        if problem_binding_ledger is not None and not isinstance(
            problem_binding_ledger,
            FunctionalProblemBindingLedger,
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_source_binding_drift: "
                f"call={call_id}, invalid F5-C ledger"
            )
        problem_call_binding = (
            problem_binding_ledger.call_binding(call_id)
            if problem_binding_ledger is not None
            else (
                problem_binding_context.call_binding(call_id)
                if problem_binding_context is not None
                else None
            )
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
                if logical_binding.consumption_mode == "resolver_evidence":
                    # Planner-authored Macro role hints influence candidate
                    # ordering only. They are not runtime read authority.
                    continue
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
        existing_state_read_keys = {
            (item.arg_name, item.item_index)
            for item in state_reads
            if ".__support_" not in item.arg_name
        }
        for logical_binding in logical_bindings:
            key = (
                logical_binding.key.arg_name,
                logical_binding.key.item_index,
            )
            if key in existing_state_read_keys:
                continue
            declaration = logical_binding.input_binding
            if (
                logical_binding.consumption_mode != "typed_binding"
                or declaration is None
                or logical_binding.source.state_version_id is None
            ):
                continue
            original_version_id = logical_binding.source.state_version_id
            selected_version_id = working.resolve_runtime_version_id(
                original_version_id
            )
            selected = working.identity_index.version(selected_version_id)
            if selected is None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.transactional_input_version_unresolved: "
                    f"call={call_id}, arg={logical_binding.key.arg_name}, "
                    f"version={original_version_id.to_payload()}"
                )
            if not working.identity_index.visibility.is_visible(
                selected.valid_scope_id,
                consumer_scope_id=node.execution_scope_id,
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.transactional_input_version_invisible: "
                    f"call={call_id}, arg={logical_binding.key.arg_name}, "
                    f"version={selected_version_id.to_payload()}"
                )
            runtime_value = working.runtime_version_values.get(
                selected_version_id
            )
            original_path = _indexed_runtime_path(selected)
            if runtime_value is None or original_path is None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.transactional_runtime_value_missing: "
                    f"call={call_id}, arg={logical_binding.key.arg_name}, "
                    f"version={selected_version_id.to_payload()}"
                )
            state_reads.append(
                PreparedFunctionalStateRead(
                    arg_name=logical_binding.key.arg_name,
                    item_index=logical_binding.key.item_index,
                    selection="exact",
                    original_version_id=original_version_id,
                    selected_version_id=selected_version_id,
                    original_runtime_path=original_path,
                    snapshot_runtime_path=snapshot_paths.setdefault(
                        selected_version_id,
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
        parameter_selector_object_ids = _parameter_selector_object_ids(
            reconciled.resolved_args,
            object_registry=object_registry,
        )
        parameter_selector_object_ids = frozenset(
            (
                *parameter_selector_object_ids,
                *(
                    object_id
                    for binding in logical_bindings
                    if (
                        (object_id := _functional_binding_object_id(binding))
                        is not None
                        and object_id.kind == "symbol"
                        and binding.consumption_mode == "typed_binding"
                    )
                ),
            )
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
        problem_inputs_by_key = {
            (item.arg_name, item.item_index): item
            for item in (
                problem_call_binding.input_bindings
                if problem_call_binding is not None
                else ()
            )
        }
        prepared_bindings: list[PreparedFunctionalArgBinding] = []
        for item in logical_bindings:
            key = (item.key.arg_name, item.key.item_index)
            value = resolved_by_key.get(key)
            state_read = reads_by_key.get(key)
            derived_source_version_id = (
                working.resolve_runtime_version_id(
                    item.source.state_version_id
                )
                if (
                    state_read is None
                    and item.consumption_mode == "typed_binding"
                    and item.input_binding is not None
                    and item.input_binding.derivation is not None
                    and item.source.state_version_id is not None
                )
                else None
            )
            runtime_path = (
                state_read.snapshot_runtime_path
                if state_read is not None
                else _prepare_non_state_runtime_path(
                    item,
                    value=value,
                    problem_input_binding=problem_inputs_by_key.get(key),
                    runtime_bindings=runtime_bindings,
                    consumer_scope_id=node.execution_scope_id,
                    condition_authority_index=(
                        reconciliation.condition_binding_authority_index
                    ),
                )
            )
            if (
                item.consumption_mode in {"runtime_input", "typed_binding"}
                and item.runtime_input_required
                and runtime_path is None
                and item.source.kind != "call_result"
                and not (
                    item.input_binding is not None
                    and isinstance(
                        item.input_binding.derivation,
                        OrdinalZeroTemplateDerivationSpec,
                    )
                )
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
                        value.handle
                        if value is not None
                        else (
                            problem_inputs_by_key[key].runtime_node_id
                            if key in problem_inputs_by_key
                            and problem_inputs_by_key[key].runtime_node_id
                            is not None
                            else _functional_binding_source_handle(item)
                        )
                    ),
                    source_math_object_id=(
                        value.math_object_id
                        if value is not None
                        else _functional_binding_object_id(item)
                    ),
                    selected_state_version_id=(
                        state_read.selected_version_id
                        if state_read is not None
                        else derived_source_version_id
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
                reconciled_returns=reconciled.returns,
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
            problem_call_binding=problem_call_binding,
        )


def _audit_problem_binding_preparation(
    *,
    call_id: str,
    wire_call: Any | None,
    reconciled_returns: Sequence[Any],
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
        if (
            logical.source.kind == "state_version"
            and logical.consumption_mode in {"runtime_input", "typed_binding"}
        ):
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
    expected_returns.update(
        allocation.return_name
        for allocation in reconciled_returns
        if allocation.bound_ref is not None
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
    problem_input_binding: FunctionalProblemInputBinding | None,
    runtime_bindings: CanonicalRuntimeBindingIndex,
    consumer_scope_id: str,
    condition_authority_index: Any | None,
) -> str | None:
    if binding.consumption_mode not in {"runtime_input", "typed_binding"}:
        return None
    declaration = binding.input_binding
    if declaration is not None and isinstance(
        declaration.derivation,
        CoefficientExtractionDerivationSpec,
    ):
        return "$problem.symbol_lists.quadratic_coefficients"
    if declaration is not None and isinstance(
        declaration.derivation,
        OrdinalZeroTemplateDerivationSpec,
    ):
        return None
    consumer = (
        f"{binding.key.call_id}.{binding.key.arg_name}"
        f"[{binding.key.item_index}]"
    )
    if binding.source.kind == "condition":
        if condition_authority_index is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_missing: "
                f"call={binding.key.call_id}, arg={binding.key.arg_name}, "
                "Condition authority index is unavailable"
            )
        condition_id = binding.source.condition_id or ""
        authority = condition_authority_index.require(condition_id)
        source_handle = (
            value.handle
            if value is not None
            else (
                problem_input_binding.runtime_node_id
                if problem_input_binding is not None
                else authority.runtime_handle
            )
        )
        if source_handle is None:
            return None
        physical = runtime_bindings.bindings.get(source_handle)
        return runtime_bindings.runtime_path_for_condition_identity(
            condition_id,
            source_handle=source_handle,
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
        identity_resolver = (
            runtime_bindings.runtime_path_for_return_object_identity
            if (
                problem_input_binding is not None
                and problem_input_binding.source_kind == "return_allocation"
            )
            or (
                declaration is not None
                and isinstance(
                    declaration.derivation,
                    PreviousOutputIdentityDerivationSpec,
                )
            )
            or (
                declaration is not None
                and isinstance(
                    declaration.source,
                    EntityIdentitySourceSpec,
                )
                and declaration.source.arg_name == binding.key.arg_name
                and binding.binding_authority == "compiler"
                and binding.key.arg_name == "target"
            )
            else runtime_bindings.runtime_path_for_object_identity
        )
        return identity_resolver(
            object_id,
            expected_type=(
                physical.value_type
                if physical is not None
                else binding.runtime_type
            ),
            consumer_scope_id=consumer_scope_id,
            consumer=consumer,
        )
    if value is None:
        return None


def _functional_binding_object_id(
    binding: FunctionalArgBinding,
) -> MathObjectId | None:
    source = binding.source
    if source.math_object_id is not None:
        return source.math_object_id
    if source.state_version_id is not None:
        return source.state_version_id.slot_id.logical_key.object_id
    return None


def _functional_binding_source_handle(
    binding: FunctionalArgBinding,
) -> str | None:
    object_id = _functional_binding_object_id(binding)
    if object_id is not None:
        return object_id.value
    source = binding.source
    if source.condition_id is not None:
        return source.condition_id
    if source.source_call_id is not None and source.source_return_name is not None:
        return f"{source.source_call_id}.{source.source_return_name}"
    return None


def _canonicalize_projected_state_dependency_version(
    dependency: ProjectedStateDependency,
    *,
    resolve_version_id: Callable[[StateVersionId], StateVersionId],
) -> ProjectedStateDependency:
    """Project a proven runtime-equivalent read onto its canonical version."""

    if dependency.state_version_id is None:
        return dependency
    selected = resolve_version_id(dependency.state_version_id)
    if selected == dependency.state_version_id:
        return dependency
    return replace(dependency, state_version_id=selected)


def _canonicalize_projected_state_write_versions(
    write: ProjectedStateWrite,
    *,
    resolve_version_id: Callable[[StateVersionId], StateVersionId],
) -> ProjectedStateWrite:
    """Keep projected producer provenance aligned with runtime aliases."""

    selected = (
        resolve_version_id(write.selected_version_id)
        if write.selected_version_id is not None
        else None
    )
    previous = (
        resolve_version_id(write.previous_version_id)
        if write.previous_version_id is not None
        else None
    )
    sources = tuple(
        resolve_version_id(item)
        for item in write.source_version_ids
    )
    lineage_sources = tuple(
        resolve_version_id(item)
        for item in write.lineage.source_version_ids
    )
    object_roles = tuple(
        replace(
            role,
            source_version_ids=tuple(
                resolve_version_id(item)
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
    computation_key = write.computation_key
    if computation_key is not None:
        computation_key = replace(
            computation_key,
            arg_bindings=tuple(
                replace(
                    binding,
                    version_id=(
                        resolve_version_id(binding.version_id)
                        if binding.version_id is not None
                        else None
                    ),
                )
                for binding in computation_key.arg_bindings
            ),
        )
    if (
        selected == write.selected_version_id
        and previous == write.previous_version_id
        and sources == write.source_version_ids
        and lineage == write.lineage
        and computation_key == write.computation_key
    ):
        return write
    return replace(
        write,
        selected_version_id=selected,
        previous_version_id=previous,
        source_version_ids=sources,
        lineage=lineage,
        computation_key=computation_key,
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
        candidate_binding = prepared_call.macro_candidate_binding
        if candidate_binding is not None:
            authored_sources = frozenset(prepared_call.macro_role_overrides.values())
            if not authored_sources <= frozenset(
                candidate_binding.allowed_source_handles
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.macro_candidate_binding_drift: "
                    f"call={prepared_call.call_id}"
                )
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
                resolve_version_id=working.resolve_runtime_version_id,
            )
            for item in all_writes
        )
        all_dependencies = tuple(
            _canonicalize_projected_state_dependency_version(
                item,
                resolve_version_id=working.resolve_runtime_version_id,
            )
            for item in reconciliation.state_dependencies
        )
        if isinstance(
            prepared_call.prepared_macro,
            PreparedMacroInvocation,
        ):
            wrapped = _compile_verified_subplan_publication_envelope(
                prepared_call,
                capability=capability,
                projected_state_writes=all_writes,
                runtime_context=runtime_context,
            )
            problem_call_binding = prepared_call.problem_call_binding
            if (
                isinstance(problem_call_binding, FunctionalProblemCallBinding)
                and problem_call_binding.status == "finalized"
            ):
                wrapped = _stamp_compiled_problem_source_provenance(
                    wrapped,
                    problem_call_binding.source_provenance(),
                )
                wrapped = replace(
                    wrapped,
                    problem_call_binding=problem_call_binding,
                )
            elif (
                isinstance(problem_call_binding, FunctionalProblemCallBinding)
                and problem_call_binding.status != "pending_macro"
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.problem_call_binding_pending: "
                    f"call={prepared_call.call_id}"
                )
            return wrapped
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
        problem_call_binding = prepared_call.problem_call_binding
        if (
            isinstance(problem_call_binding, FunctionalProblemCallBinding)
            and problem_call_binding.status == "finalized"
        ):
            wrapped = _stamp_compiled_problem_source_provenance(
                wrapped,
                problem_call_binding.source_provenance(),
            )
            wrapped = replace(
                wrapped,
                problem_call_binding=problem_call_binding,
            )
        elif (
            isinstance(problem_call_binding, FunctionalProblemCallBinding)
            and problem_call_binding.status != "pending_macro"
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.problem_call_binding_pending: "
                f"call={prepared_call.call_id}"
            )
        return wrapped


def _stamp_method_input_read_authorities(
    compiled: CompiledFunctionalCall,
    *,
    prepared_call: PreparedFunctionalCall,
    method_specs: Any,
    branch: RuntimeContext,
    working: WorkingPlannerState,
    condition_authority_index: Any | None = None,
) -> CompiledFunctionalCall:
    """Attach the only runtime-readable source choice to every Method input."""

    debug_authority = prepared_call.problem_call_binding is None
    problem_inputs_by_key = {
        (item.arg_name, item.item_index): item
        for item in (
            prepared_call.problem_call_binding.input_bindings
            if prepared_call.problem_call_binding is not None
            else ()
        )
    }
    parent_dependency_object_refs = frozenset(
        object_ref
        for values in prepared_call.reconciliation.resolved_args.values()
        for value in values
        for object_ref in (
            *value.dependency_object_refs,
            *((value.object_ref,) if value.object_ref is not None else ()),
            *(
                role_ref
                for _role, role_refs in value.object_roles
                for role_ref in role_refs
            ),
        )
    )

    bindings_by_path = {
        item.runtime_path: item
        for item in prepared_call.arg_bindings
        if item.runtime_path is not None
    }
    typed_bindings_by_target: dict[
        tuple[str, int], PreparedFunctionalArgBinding
    ] = {}
    for item in prepared_call.arg_bindings:
        if item.logical_binding.consumption_mode != "typed_binding":
            continue
        for target in item.logical_binding.runtime_input_targets:
            key = (target, item.logical_binding.key.item_index)
            previous = typed_bindings_by_target.setdefault(key, item)
            if previous is not item:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"call={prepared_call.call_id}, input={target}, "
                    "multiple typed bindings target one Method input"
                )
    state_reads_by_path: dict[str, PreparedFunctionalStateRead] = {}
    for item in prepared_call.state_reads:
        for runtime_path in (
            item.original_runtime_path,
            item.snapshot_runtime_path,
        ):
            previous = state_reads_by_path.setdefault(runtime_path, item)
            if previous.selected_version_id != item.selected_version_id:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"call={prepared_call.call_id}, path={runtime_path}, "
                    "multiple exact StateVersions"
                )
    lineage_state_sources_by_path: dict[str, StateVersionReadSource] = {}

    def register_lineage_state_source(
        runtime_path: str,
        version_id: StateVersionId,
    ) -> None:
        source = StateVersionReadSource(version_id, runtime_path)
        previous = lineage_state_sources_by_path.setdefault(
            runtime_path,
            source,
        )
        if previous.state_version_id != version_id:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={prepared_call.call_id}, path={runtime_path}, "
                "multiple exact lineage StateVersions"
            )

    for values in prepared_call.reconciliation.resolved_args.values():
        for value in values:
            if value.state_version_id is not None:
                selected_version_id = working.resolve_runtime_version_id(
                    value.state_version_id
                )
                selected = working.identity_index.version(selected_version_id)
                if selected is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.method_input_view_authority_missing: "
                        f"call={prepared_call.call_id}, selected_version="
                        f"{selected_version_id.to_payload()}"
                    )
                register_lineage_state_source(
                    value.handle,
                    selected_version_id,
                )
                register_lineage_state_source(
                    _indexed_runtime_path(selected),
                    selected_version_id,
                )
            for version_id in value.source_version_ids:
                runtime_version_id = working.resolve_runtime_version_id(
                    version_id
                )
                indexed = working.identity_index.version(runtime_version_id)
                if indexed is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.method_input_view_authority_missing: "
                        f"call={prepared_call.call_id}, source_version="
                        f"{runtime_version_id.to_payload()}"
                    )
                runtime_path = _indexed_runtime_path(indexed)
                register_lineage_state_source(
                    runtime_path,
                    runtime_version_id,
                )
    materialized_state_sources = dict(compiled.materialized_state_sources)
    declared_entity_handles = {
        declaration.path: (
            f"point:{declaration.scope_id}:{declaration.name}"
            if declaration.type == "PointRef"
            else f"{declaration.type.lower()}:{declaration.scope_id}:"
            f"{declaration.name}"
        )
        for declaration in compiled.declarations
    }
    producer_by_path: dict[str, tuple[str, str]] = {}
    output_paths_by_key: dict[str, list[str]] = {}
    promotion_targets: dict[str, str] = {}
    for plan in compiled.plans:
        for invocation in plan.invocations:
            for return_name, path in invocation.outputs.items():
                producer_by_path[path] = (invocation.invocation_id, return_name)
                for key in (
                    return_name,
                    f"{invocation.method_id}.{return_name}",
                    f"{invocation.invocation_id}.{return_name}",
                ):
                    output_paths_by_key.setdefault(key, []).append(path)
        promotion_targets.update(plan.promote_outputs)
        pending_promotions = dict(plan.promote_outputs)
        while pending_promotions:
            progressed = False
            for source_path, target_path in tuple(pending_promotions.items()):
                producer = producer_by_path.get(source_path)
                if producer is None:
                    continue
                producer_by_path[target_path] = producer
                del pending_promotions[source_path]
                progressed = True
            if not progressed:
                break

    return_identity_by_path: dict[str, str] = {}

    def register_return_identity(path: str, object_ref: str) -> None:
        previous = return_identity_by_path.setdefault(path, object_ref)
        if previous != object_ref:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={prepared_call.call_id}, path={path}, "
                f"return_objects={[previous, object_ref]}"
            )

    for public_return in compiled.public_returns:
        allocation = public_return.allocation
        object_ref = (
            allocation.math_object_id.value
            if allocation.math_object_id is not None
            else allocation.object_ref
        )
        expected_write = public_return.expected_write
        if object_ref is None or expected_write is None:
            continue
        source_paths = tuple(
            dict.fromkeys(
                output_paths_by_key.get(expected_write.output_key, ())
            )
        )
        if len(source_paths) > 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={prepared_call.call_id}, return="
                f"{public_return.return_name}, output_key="
                f"{expected_write.output_key}, paths={source_paths}"
            )
        if not source_paths:
            continue
        path = source_paths[0]
        register_return_identity(path, object_ref)
        visited: set[str] = set()
        while path in promotion_targets and path not in visited:
            visited.add(path)
            path = promotion_targets[path]
            register_return_identity(path, object_ref)

    def latest_state_source(
        path: str,
        *,
        scope_id: str,
    ) -> StateVersionReadSource | None:
        visible = tuple(
            item
            for item in working.identity_index.all_versions()
            if _indexed_runtime_path(item) == path
            and working.identity_index.visibility.is_visible(
                item.valid_scope_id,
                consumer_scope_id=scope_id,
            )
        )
        if not visible:
            return None
        object_ids = {
            item.version_id.slot_id.logical_key.object_id
            for item in visible
        }
        if len(object_ids) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"path={path}, scope={scope_id}, "
                f"object_count={len(object_ids)}"
            )
        selected = max(
            visible,
            key=lambda item: (
                item.version_id.ordinal,
                item.producer_call_id or "",
            ),
        )
        return StateVersionReadSource(selected.version_id, path)

    def condition_source_for_path(
        path: str,
        *,
        input_name: str,
    ) -> ConditionReadSource | None:
        if condition_authority_index is None:
            return None
        try:
            condition_value = branch.read_path(
                path,
                from_scope_id=prepared_call.execution_scope_id,
                expected_type="Condition",
            ).value
        except (KeyError, PermissionError, TypeError, ValueError):
            return None
        authority = None
        if isinstance(condition_value, Condition):
            authority = condition_authority_index.require(
                condition_value.condition_id
            )
        elif isinstance(condition_value, Mapping):
            condition_id = condition_value.get("condition_id")
            if isinstance(condition_id, str) and condition_id:
                authority = condition_authority_index.require(condition_id)
            else:
                runtime_handle = condition_value.get("handle")
                condition_kind = condition_value.get("type")
                if (
                    isinstance(runtime_handle, str)
                    and runtime_handle
                    and isinstance(condition_kind, str)
                    and condition_kind
                ):
                    authority = condition_authority_index.resolve_runtime_handle(
                        runtime_handle,
                        condition_kinds=(condition_kind,),
                        scope_id=prepared_call.execution_scope_id,
                    )
            owner_scope = condition_value.get("scope_id")
            if (
                authority is not None
                and isinstance(owner_scope, str)
                and owner_scope
                and owner_scope != authority.owner_scope_id
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    f"condition={authority.condition_id}, "
                    f"expected_owner={authority.owner_scope_id}, "
                    f"observed_owner={owner_scope}"
                )
        if authority is None:
            return None
        related_refs = frozenset(authority.related_object_refs)
        if (
            parent_dependency_object_refs
            and not related_refs.issubset(parent_dependency_object_refs)
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={prepared_call.call_id}, input={input_name}, "
                f"condition={authority.condition_id}, "
                "related objects are outside the parent provenance"
            )
        return ConditionReadSource(authority.condition_id, path)

    def source_for(
        path: str,
        *,
        input_name: str,
        item_index: int,
        view_mode: str,
        identity_companion_path: str | None = None,
        input_binding: MethodInputBindingSpec | None = None,
        invocation_inputs: Mapping[str, str | tuple[str, ...]] | None = None,
    ) -> Any:
        def typed_prepared_source(
            prepared: PreparedFunctionalArgBinding | None,
        ) -> Any | None:
            if prepared is None:
                return None
            declaration = prepared.logical_binding.input_binding
            if declaration is None:
                return None
            source = prepared.logical_binding.source
            selected_version_id = (
                prepared.selected_state_version_id
                or source.state_version_id
            )
            if isinstance(
                declaration.derivation,
                CoefficientExtractionDerivationSpec,
            ):
                if selected_version_id is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.method_input_view_authority_missing: "
                        f"call={prepared_call.call_id}, input={input_name}, "
                        "derivation=coefficient_extraction"
                    )
                source_version = working.identity_index.version(
                    working.resolve_runtime_version_id(selected_version_id)
                )
                source_path = (
                    _indexed_runtime_path(source_version)
                    if source_version is not None
                    else None
                )
                if source_path is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.method_input_view_authority_missing: "
                        f"call={prepared_call.call_id}, input={input_name}, "
                        "derivation=coefficient_extraction"
                    )
                return DerivedInputReadSource(
                    declaration,
                    StateVersionReadSource(selected_version_id, source_path),
                    path,
                )
            if source.kind == "condition" and source.condition_id is not None:
                return ConditionReadSource(source.condition_id, path)
            if (
                source.kind == "call_result"
                and source.source_call_id is not None
                and source.source_return_name is not None
            ):
                return CallResultReadSource(
                    source.source_call_id,
                    source.source_return_name,
                    path,
                )
            if view_mode == "identity" and (
                prepared.source_math_object_id is not None
                or prepared.source_handle is not None
            ):
                return EntityIdentityReadSource(
                    (
                        prepared.source_math_object_id.value
                        if prepared.source_math_object_id is not None
                        else prepared.source_handle
                    ),
                    path,
                )
            if selected_version_id is not None:
                return StateVersionReadSource(selected_version_id, path)
            return None

        state_read = state_reads_by_path.get(path)
        original_binding = (
            bindings_by_path.get(state_read.original_runtime_path)
            if state_read is not None
            else None
        )
        resolved_values = prepared_call.reconciliation.resolved_args.get(
            input_name,
            (),
        )
        resolved_value = (
            resolved_values[item_index]
            if item_index < len(resolved_values)
            else None
        )
        problem_input = problem_inputs_by_key.get((input_name, item_index))
        if (
            view_mode == "exact_result"
            and problem_input is not None
            and problem_input.typed_source is not None
            and problem_input.typed_source.kind == "call_result"
        ):
            typed_source = problem_input.typed_source
            if (
                typed_source.source_call_id is None
                or typed_source.source_return_name is None
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_missing: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    "view=exact_result"
                )
            if (
                resolved_value is None
                or resolved_value.source_call_id
                != typed_source.source_call_id
                or resolved_value.return_name
                != typed_source.source_return_name
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    f"expected={typed_source.source_call_id}."
                    f"{typed_source.source_return_name}, observed="
                    f"{getattr(resolved_value, 'source_call_id', None)}."
                    f"{getattr(resolved_value, 'return_name', None)}"
                )
            return CallResultReadSource(
                typed_source.source_call_id,
                typed_source.source_return_name,
                path,
            )
        if view_mode == "latest_state":
            lineage_source = lineage_state_sources_by_path.get(path)
            if lineage_source is not None:
                if (
                    problem_input is not None
                    and problem_input.typed_source.kind == "call_result"
                    and (
                        resolved_value is None
                        or resolved_value.source_call_id
                        != problem_input.typed_source.source_call_id
                        or resolved_value.return_name
                        != problem_input.typed_source.source_return_name
                    )
                ):
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.method_input_view_authority_drift: "
                        f"call={prepared_call.call_id}, input={input_name}, "
                        "the exact state producer differs from the finalized "
                        "call-result binding"
                    )
                return lineage_source
        if (
            not debug_authority
            and view_mode == "immutable_value"
            and condition_authority_index is not None
        ):
            exact_condition = condition_source_for_path(
                path,
                input_name=input_name,
            )
            if exact_condition is not None:
                return exact_condition
        if state_read is not None and view_mode == "identity":
            object_id = (
                state_read.selected_version_id
                .slot_id.logical_key.object_id
            )
            return EntityIdentityReadSource(
                object_id.value,
                path,
            )
        materialized_version_id = materialized_state_sources.get(path)
        if materialized_version_id is not None:
            if view_mode == "identity":
                return EntityIdentityReadSource(
                    materialized_version_id.slot_id.logical_key.object_id.value,
                    path,
                )
            if view_mode == "latest_state":
                return StateVersionReadSource(materialized_version_id, path)
        if view_mode == "identity" and path in return_identity_by_path:
            return EntityIdentityReadSource(
                return_identity_by_path[path],
                path,
            )
        if (
            state_read is not None
            and view_mode == "exact_result"
            and original_binding is not None
            and original_binding.logical_binding.source.kind == "call_result"
            and original_binding.logical_binding.source.source_call_id is not None
            and original_binding.logical_binding.source.source_return_name is not None
        ):
            source = original_binding.logical_binding.source
            return CallResultReadSource(
                source.source_call_id,
                source.source_return_name,
                path,
            )
        if (
            state_read is not None
            and view_mode == "exact_result"
            and resolved_value is not None
            and resolved_value.source_call_id is not None
            and resolved_value.return_name is not None
        ):
            return CallResultReadSource(
                resolved_value.source_call_id,
                resolved_value.return_name,
                path,
            )
        if (
            state_read is not None
            and view_mode == "immutable_value"
            and original_binding is not None
            and original_binding.logical_binding.source.kind == "condition"
            and original_binding.logical_binding.source.condition_id is not None
        ):
            return ConditionReadSource(
                original_binding.logical_binding.source.condition_id,
                path,
            )
        if state_read is not None and view_mode == "exact_result":
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={prepared_call.call_id}, input={input_name}, "
                f"view=exact_result, original_path="
                f"{state_read.original_runtime_path}, source="
                f"{getattr(getattr(original_binding, 'logical_binding', None), 'source', None)!r}"
            )
        if state_read is not None:
            return StateVersionReadSource(
                state_version_id=state_read.selected_version_id,
                runtime_path=path,
            )
        binding = bindings_by_path.get(path)
        if binding is not None:
            source = binding.logical_binding.source
            exact_typed_source = typed_prepared_source(binding)
            if exact_typed_source is not None:
                return exact_typed_source
            if view_mode == "identity" and (
                binding.source_math_object_id is not None
                or binding.source_handle is not None
            ):
                return EntityIdentityReadSource(
                    (
                        binding.source_math_object_id.value
                        if binding.source_math_object_id is not None
                        else binding.source_handle
                    ),
                    path,
                )
            if source.kind == "condition" and source.condition_id is not None:
                return ConditionReadSource(source.condition_id, path)
            if (
                source.kind == "call_result"
                and source.source_call_id is not None
                and source.source_return_name is not None
            ):
                return CallResultReadSource(
                    source.source_call_id,
                    source.source_return_name,
                    path,
                )
            if source.kind == "state_version" and (
                binding.selected_state_version_id is not None
            ):
                return StateVersionReadSource(
                    binding.selected_state_version_id,
                    path,
                )
            if (
                debug_authority
                and view_mode == "latest_state"
                and binding.source_handle is not None
            ):
                object_versions = tuple(
                    item
                    for item in working.identity_index.all_versions()
                    if (
                        item.version_id.slot_id.logical_key.object_id.value
                        == binding.source_handle
                    )
                )
                object_ids = {
                    item.version_id.slot_id.logical_key.object_id
                    for item in object_versions
                }
                if len(object_ids) > 1:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.method_input_view_authority_drift: "
                        f"call={prepared_call.call_id}, input={input_name}, "
                        f"source_handle={binding.source_handle}, "
                        f"object_count={len(object_ids)}"
                    )
                if object_ids:
                    selected = working.identity_index.latest_visible_for_object(
                        next(iter(object_ids)),
                        consumer_scope_id=prepared_call.execution_scope_id,
                    )
                    if selected is not None:
                        return StateVersionReadSource(
                            selected.version_id,
                            path,
                        )
            if (
                binding.source_handle is not None
                and view_mode in {"identity", "immutable_value"}
            ):
                return EntityIdentityReadSource(binding.source_handle, path)
        exact_typed_source = typed_prepared_source(
            typed_bindings_by_target.get((input_name, item_index))
        )
        if exact_typed_source is not None:
            return exact_typed_source
        if view_mode == "identity" and path in declared_entity_handles:
            return EntityIdentityReadSource(
                declared_entity_handles[path],
                path,
            )
        if (
            view_mode == "identity"
            and input_binding is not None
            and isinstance(
                input_binding.derivation,
                CanonicalSymbolDerivationSpec,
            )
        ):
            return EntityIdentityReadSource(
                f"symbol:problem:{input_binding.derivation.symbol_name}",
                path,
            )
        if (
            debug_authority
            and input_binding is not None
            and isinstance(
                input_binding.derivation,
                CoefficientExtractionDerivationSpec,
            )
        ):
            source_value = (invocation_inputs or {}).get(
                input_binding.derivation.source_input
            )
            source_paths = (
                (source_value,)
                if isinstance(source_value, str)
                else tuple(source_value or ())
            )
            if len(source_paths) != 1:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    "derivation=coefficient_extraction, "
                    f"source_count={len(source_paths)}"
                )
            source_path = source_paths[0]
            upstream: Any | None = None
            source_read = state_reads_by_path.get(source_path)
            if source_read is not None:
                upstream = StateVersionReadSource(
                    source_read.selected_version_id,
                    source_path,
                )
            materialized_version = materialized_state_sources.get(source_path)
            if upstream is None and materialized_version is not None:
                upstream = StateVersionReadSource(
                    materialized_version,
                    source_path,
                )
            source_producer = producer_by_path.get(source_path)
            if upstream is None and source_producer is not None:
                upstream = InvocationResultReadSource(
                    source_producer[0],
                    source_producer[1],
                    source_path,
                )
            if upstream is None:
                parsed_source = ContextPath.parse(source_path)
                object_kind = {
                    "functions": "function",
                    "object_refs": "object",
                }.get(parsed_source.container)
                if object_kind is not None:
                    upstream = EntityIdentityReadSource(
                        f"{object_kind}:{parsed_source.scope_id}:"
                        f"{parsed_source.key}",
                        source_path,
                    )
            if upstream is None:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_missing: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    "derivation=coefficient_extraction, "
                    f"source_path={source_path}"
                )
            return DerivedInputReadSource(input_binding, upstream, path)
        if (
            view_mode == "identity"
            and input_binding is not None
            and isinstance(
                input_binding.derivation,
                FreeSymbolBasisDerivationSpec,
            )
        ):
            exact_conditions: dict[str, ConditionReadSource] = {}
            exact_states: dict[StateVersionId, StateVersionReadSource] = {}
            for source_input in input_binding.derivation.source_inputs:
                source_value = (invocation_inputs or {}).get(source_input)
                source_paths = (
                    (source_value,)
                    if isinstance(source_value, str)
                    else tuple(source_value or ())
                )
                for source_path in source_paths:
                    prepared = bindings_by_path.get(source_path)
                    prepared_source = typed_prepared_source(prepared)
                    if (
                        prepared_source is None
                        and prepared is not None
                        and prepared.logical_binding.source.condition_id
                        is not None
                    ):
                        prepared_source = ConditionReadSource(
                            prepared.logical_binding.source.condition_id,
                            source_path,
                        )
                    if prepared_source is None:
                        prepared_source = lineage_state_sources_by_path.get(
                            source_path
                        )
                    if prepared_source is None and not debug_authority:
                        prepared_source = condition_source_for_path(
                            source_path,
                            input_name=input_name,
                        )
                    if prepared_source is None and debug_authority:
                        try:
                            exact_condition = branch.read_path(
                                source_path,
                                from_scope_id=prepared_call.execution_scope_id,
                                expected_type="Condition",
                            ).value
                        except (KeyError, PermissionError, TypeError, ValueError):
                            exact_condition = None
                        if isinstance(exact_condition, Condition):
                            prepared_source = ConditionReadSource(
                                exact_condition.condition_id,
                                source_path,
                            )
                        elif isinstance(exact_condition, Mapping):
                            condition_id = exact_condition.get("condition_id")
                            if isinstance(condition_id, str) and condition_id:
                                prepared_source = ConditionReadSource(
                                    condition_id,
                                    source_path,
                                )
                            else:
                                parsed_source = ContextPath.parse(source_path)
                                if parsed_source.container in {
                                    "conditions",
                                    "constraints",
                                }:
                                    prepared_source = ConditionReadSource(
                                        f"condition:{parsed_source.key}@"
                                        f"{parsed_source.scope_id}",
                                        source_path,
                                    )
                    if isinstance(prepared_source, ConditionReadSource):
                        exact_conditions[prepared_source.condition_id] = (
                            prepared_source
                        )
                    selected = state_reads_by_path.get(source_path)
                    if selected is not None:
                        state_source = StateVersionReadSource(
                            selected.selected_version_id,
                            source_path,
                        )
                        exact_states[state_source.state_version_id] = state_source
            if len(exact_conditions) > 1:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    f"condition_count={len(exact_conditions)}"
                )
            upstream = (
                next(iter(exact_conditions.values()))
                if exact_conditions
                else (
                    next(iter(exact_states.values()))
                    if len(exact_states) == 1
                    else None
                )
            )
            if upstream is None:
                declared_source_paths = {
                    source_input: (invocation_inputs or {}).get(source_input)
                    for source_input in input_binding.derivation.source_inputs
                }
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_missing: "
                    f"call={prepared_call.call_id}, input={input_name}, "
                    "derivation=free_symbol_basis, "
                    f"source_paths={declared_source_paths}, "
                    f"prepared_paths={sorted(bindings_by_path)}"
                )
            return DerivedInputReadSource(input_binding, upstream, path)
        if view_mode == "identity" and identity_companion_path is not None:
            companion_read = state_reads_by_path.get(identity_companion_path)
            if companion_read is not None:
                return EntityIdentityReadSource(
                    companion_read.selected_version_id.slot_id.logical_key.object_id.value,
                    path,
                )
            companion_version = materialized_state_sources.get(
                identity_companion_path
            )
            if companion_version is not None:
                return EntityIdentityReadSource(
                    companion_version.slot_id.logical_key.object_id.value,
                    path,
                )
        producer = producer_by_path.get(path)
        if producer is not None and view_mode != "identity":
            return InvocationResultReadSource(producer[0], producer[1], path)
        if (
            debug_authority
            and view_mode == "exact_result"
            and resolved_value is not None
            and resolved_value.source_call_id is not None
            and resolved_value.return_name is not None
        ):
            return CallResultReadSource(
                resolved_value.source_call_id,
                resolved_value.return_name,
                path,
            )
        if (
            debug_authority
            and view_mode == "latest_state"
            and resolved_value is not None
            and resolved_value.state_version_id is not None
        ):
            return StateVersionReadSource(
                resolved_value.state_version_id,
                path,
            )
        if (
            debug_authority
            and view_mode == "identity"
            and resolved_value is not None
            and (
                resolved_value.math_object_id is not None
                or resolved_value.object_ref is not None
            )
        ):
            return EntityIdentityReadSource(
                (
                    resolved_value.math_object_id.value
                    if resolved_value.math_object_id is not None
                    else resolved_value.object_ref
                ),
                path,
            )
        if debug_authority and view_mode == "identity":
            parsed_source = ContextPath.parse(path)
            debug_object_kind = {
                "symbols": "symbol",
                "points": "point",
                "functions": "function",
            }.get(parsed_source.container)
            if debug_object_kind is not None:
                return EntityIdentityReadSource(
                    f"{debug_object_kind}:{parsed_source.scope_id}:"
                    f"{parsed_source.key}",
                    path,
                )
            selected_state = latest_state_source(
                path,
                scope_id=prepared_call.execution_scope_id,
            )
            if selected_state is not None:
                return EntityIdentityReadSource(
                    selected_state.state_version_id.slot_id.logical_key.object_id.value,
                    path,
                )
        if debug_authority and view_mode == "immutable_value":
            try:
                condition_value = branch.read_path(
                    path,
                    from_scope_id=prepared_call.execution_scope_id,
                    expected_type="Condition",
                ).value
            except (KeyError, PermissionError, TypeError):
                condition_value = None
            if isinstance(condition_value, Condition):
                return ConditionReadSource(condition_value.condition_id, path)
            if isinstance(condition_value, Mapping):
                condition_id = condition_value.get("condition_id")
                if isinstance(condition_id, str) and condition_id:
                    return ConditionReadSource(condition_id, path)
                handle = condition_value.get("handle")
                owner_scope = condition_value.get("scope_id")
                if (
                    isinstance(handle, str)
                    and handle
                    and isinstance(owner_scope, str)
                    and owner_scope
                ):
                    return ConditionReadSource(
                        f"condition:{semantic_name_from_handle(handle)}@{owner_scope}",
                        path,
                    )
            parsed_source = ContextPath.parse(path)
            if parsed_source.container in {"conditions", "constraints"}:
                return ConditionReadSource(
                    f"condition:{parsed_source.key}@"
                    f"{parsed_source.scope_id}",
                    path,
                )
            return InvocationResultReadSource(
                f"debug:{prepared_call.call_id}",
                input_name,
                path,
            )
        if debug_authority and view_mode == "latest_state":
            selected_state = latest_state_source(
                path,
                scope_id=prepared_call.execution_scope_id,
            )
            if selected_state is not None:
                return selected_state
        raise ValueError(
            "planner_configuration_error: "
            "planner.method_input_view_authority_missing: "
            f"call={prepared_call.call_id}, input={input_name}, "
            f"view={view_mode}, path={path}"
        )

    def symbolic_basis_authority(
        *,
        plan: StepPlan,
        invocation: MethodInvocation,
        authorities: Mapping[str, tuple[MethodInputReadAuthority, ...]],
    ) -> MethodInputReadAuthority | None:
        spec = method_specs.require(invocation.method_id)
        anchor_names = tuple(
            name
            for name, input_spec in spec.inputs.items()
            if input_spec.symbolic_basis_role == "state_anchor"
            and name in invocation.inputs
        )
        aligned_names = tuple(
            name
            for name, input_spec in spec.inputs.items()
            if input_spec.symbolic_basis_role == "align_to_anchor"
            and name in invocation.inputs
        )
        if not anchor_names and not aligned_names:
            return None
        if len(anchor_names) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_missing: "
                f"method={invocation.method_id}, "
                f"invocation={invocation.invocation_id}, "
                f"state_anchors={anchor_names!r}"
            )

        anchor_authorities = authorities.get(anchor_names[0], ())
        anchor_object_id: MathObjectId | None = None
        if len(anchor_authorities) == 1 and isinstance(
            anchor_authorities[0].source,
            StateVersionReadSource,
        ):
            anchor_object_id = (
                anchor_authorities[0]
                .source.state_version_id.slot_id.logical_key.object_id
            )

        def eligible(version: IndexedStateVersion) -> bool:
            if version.version_id.ordinal != 0:
                return False
            if not working.identity_index.visibility.is_visible(
                version.valid_scope_id,
                consumer_scope_id=plan.scope,
            ):
                return False
            value = working.runtime_version_values.get(version.version_id)
            if value is None or value.type not in {"Expression", "Parabola"}:
                return False
            return isinstance(value.value, sp.Basic)

        candidates = tuple(
            item
            for item in working.identity_index.all_versions()
            if eligible(item)
            and (
                anchor_object_id is None
                or item.version_id.slot_id.logical_key.object_id
                == anchor_object_id
            )
        )
        if not candidates and anchor_object_id is not None:
            candidates = tuple(
                item
                for item in working.identity_index.all_versions()
                if eligible(item)
            )
        unique_candidates = {
            item.version_id: item for item in candidates
        }
        if len(unique_candidates) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_missing: "
                f"method={invocation.method_id}, "
                f"invocation={invocation.invocation_id}, "
                "input=symbolic_basis_source, "
                f"candidate_count={len(unique_candidates)}"
            )
        source_version = next(iter(unique_candidates.values()))
        runtime_value = working.runtime_version_values.get(
            source_version.version_id
        )
        if runtime_value is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_missing: "
                f"method={invocation.method_id}, "
                f"invocation={invocation.invocation_id}, "
                "input=symbolic_basis_source"
            )
        support_path = _indexed_runtime_path(source_version)
        if support_path is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_missing: "
                f"method={invocation.method_id}, "
                f"invocation={invocation.invocation_id}, "
                "input=symbolic_basis_source, source_path=missing"
            )
        try:
            branch.read_path(
                support_path,
                from_scope_id=invocation.scope,
                expected_type=runtime_value.type,
            )
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"method={invocation.method_id}, "
                f"invocation={invocation.invocation_id}, "
                "input=symbolic_basis_source"
            ) from exc
        return MethodInputReadAuthority(
            method_id=invocation.method_id,
            invocation_id=invocation.invocation_id,
            input_name="symbolic_basis_source",
            item_index=0,
            view_mode="immutable_value",
            domain_type="QuadraticFunction",
            runtime_type=runtime_value.type,
            scope_id=invocation.scope,
            source=StateVersionReadSource(
                state_version_id=source_version.version_id,
                runtime_path=support_path,
            ),
        )

    def polynomial_template_authority(
        *,
        plan: StepPlan,
        invocation: MethodInvocation,
        authorities: Mapping[str, tuple[MethodInputReadAuthority, ...]],
    ) -> MethodInputReadAuthority | None:
        spec = method_specs.require(invocation.method_id)
        declarations = tuple(
            (input_name, input_spec, input_spec.binding.derivation)
            for input_name, input_spec in spec.inputs.items()
            if input_spec.binding is not None
            and isinstance(
                input_spec.binding.derivation,
                OrdinalZeroTemplateDerivationSpec,
            )
        )
        if not declarations:
            return None
        if len(declarations) != 1:
            raise StatelessMethodError(
                "planner.method_input_binding_contract_invalid",
                "Method must declare exactly one ordinal-zero template input",
                category="configuration",
                retryability="configuration",
                method_id=invocation.method_id,
                scope_id=invocation.scope,
                step_id=invocation.invocation_id,
                arg_name="quadratic_template",
                role="coefficient_identity_template",
                expected={"declaration_count": 1},
                observed={"declaration_count": len(declarations)},
                repair_action="fix_method_spec",
                details={
                    "declared_inputs": [item[0] for item in declarations],
                },
            )
        template_input_name, input_spec, derivation = declarations[0]
        source_input_name = derivation.source_input
        if input_spec.functional_exposed:
            raise StatelessMethodError(
                "planner.method_input_view_authority_drift",
                "polynomial coefficient templates must be code-owned inputs",
                category="configuration",
                retryability="configuration",
                method_id=invocation.method_id,
                scope_id=invocation.scope,
                step_id=invocation.invocation_id,
                arg_name=template_input_name,
                role="coefficient_identity_template",
                expected={"functional_exposed": False},
                observed={"functional_exposed": True},
                repair_action="fix_method_spec",
            )
        if template_input_name in invocation.inputs:
            raise StatelessMethodError(
                "planner.method_input_view_authority_drift",
                "compiler supplied a code-owned polynomial template input",
                category="configuration",
                retryability="configuration",
                method_id=invocation.method_id,
                scope_id=invocation.scope,
                step_id=invocation.invocation_id,
                arg_name=template_input_name,
                role="coefficient_identity_template",
                expected={"authority": "method_input_read_stamp"},
                observed={"authority": "compiler_invocation_input"},
                repair_action="remove_compiler_owned_hidden_input",
            )

        anchor_authorities = tuple(
            authority
            for authority in authorities.get(source_input_name, ())
        )
        anchor_version: IndexedStateVersion | None = None
        anchor_object_id: MathObjectId | None = None
        if len(anchor_authorities) == 1 and isinstance(
            anchor_authorities[0].source,
            StateVersionReadSource,
        ):
            anchor_version_id = anchor_authorities[0].source.state_version_id
            anchor_object_id = (
                anchor_version_id.slot_id.logical_key.object_id
            )
            anchor_version = next(
                (
                    item
                    for item in working.identity_index.all_versions()
                    if item.version_id == anchor_version_id
                ),
                None,
            )

        def eligible(version: IndexedStateVersion) -> bool:
            if version.version_id.ordinal != 0:
                return False
            if anchor_object_id is not None and (
                version.version_id.slot_id.logical_key.object_id
                != anchor_object_id
            ):
                return False
            if not working.identity_index.visibility.is_visible(
                version.valid_scope_id,
                consumer_scope_id=plan.scope,
            ):
                return False
            value = working.runtime_version_values.get(version.version_id)
            return bool(
                value is not None
                and value.type in {"Expression", "Parabola"}
                and isinstance(value.value, sp.Basic)
            )

        candidates = {
            item.version_id: item
            for item in working.identity_index.all_versions()
            if eligible(item)
        }
        lineage_roots = tuple(
            candidate
            for candidate in candidates.values()
            if all(
                working.identity_index.is_same_or_descendant(
                    other.version_id,
                    candidate.version_id,
                )
                for other in candidates.values()
            )
        )
        template_version = (
            lineage_roots[0]
            if len(lineage_roots) == 1
            else None
        )
        template_value = (
            working.runtime_version_values.get(template_version.version_id)
            if template_version is not None
            else None
        )
        observed_value = (
            working.runtime_version_values.get(anchor_version.version_id)
            if anchor_version is not None
            else None
        )
        expected_expression = (
            sp.sstr(template_value.value)
            if template_value is not None
            else "ordinal_0_polynomial_template"
        )
        observed_expression = (
            sp.sstr(observed_value.value)
            if observed_value is not None
            and isinstance(observed_value.value, sp.Basic)
            else "unavailable"
        )
        missing_symbols = tuple(
            sorted(
                (
                    set(template_value.value.free_symbols)
                    - set(observed_value.value.free_symbols)
                )
                if template_value is not None
                and observed_value is not None
                and isinstance(template_value.value, sp.Basic)
                and isinstance(observed_value.value, sp.Basic)
                else (),
                key=lambda item: item.name,
            )
        )
        detail = {
            "expected_template": expected_expression,
            "observed_state": observed_expression,
            "missing_symbol_roles": [item.name for item in missing_symbols],
            "candidate_count": len(candidates),
            "lineage_root_count": len(lineage_roots),
            "candidate_version_ids": [
                item.to_payload() for item in sorted(candidates)
            ],
        }
        if len(missing_symbols) == 1:
            detail["missing_symbol_role"] = missing_symbols[0].name

        if template_version is None:
            raise StatelessMethodError(
                "planner.method_input_view_authority_missing",
                "polynomial closure requires the ordinal-0 function template",
                category="configuration",
                retryability="configuration",
                method_id=invocation.method_id,
                scope_id=invocation.scope,
                step_id=invocation.invocation_id,
                arg_name=template_input_name,
                role="coefficient_identity_template",
                expected={
                    "template": expected_expression,
                    "state": "ordinal_0",
                },
                observed={
                    "state": observed_expression,
                    **(
                        {"missing_symbol_role": missing_symbols[0].name}
                        if len(missing_symbols) == 1
                        else {}
                    ),
                },
                repair_action="fix_runtime_contract",
                details=detail,
            )
        source_path = _indexed_runtime_path(template_version)
        if source_path is None:
            raise StatelessMethodError(
                "planner.method_input_view_authority_missing",
                "ordinal-0 template has no runtime address",
                category="configuration",
                retryability="configuration",
                method_id=invocation.method_id,
                scope_id=invocation.scope,
                step_id=invocation.invocation_id,
                arg_name=template_input_name,
                role="coefficient_identity_template",
                expected={"template": expected_expression, "state": "ordinal_0"},
                observed={"state": observed_expression},
                repair_action="fix_runtime_contract",
                details={
                    **detail,
                    "expected_runtime_path": source_path,
                    "observed_runtime_path": None,
                },
            )
        return MethodInputReadAuthority(
            method_id=invocation.method_id,
            invocation_id=invocation.invocation_id,
            input_name=template_input_name,
            item_index=0,
            view_mode=input_spec.view.mode,
            domain_type=input_spec.domain_type,
            runtime_type=input_spec.runtime_type,
            scope_id=invocation.scope,
            source=StateVersionReadSource(
                state_version_id=template_version.version_id,
                runtime_path=source_path,
            ),
        )

    def stamp_plan(plan: StepPlan) -> StepPlan:
        invocations: list[MethodInvocation] = []
        for invocation in plan.invocations:
            spec = method_specs.require(invocation.method_id)
            invocation_inputs = dict(invocation.inputs)
            authorities: dict[str, tuple[MethodInputReadAuthority, ...]] = {}
            unknown_prestamped = set(invocation.input_read_authorities) - set(
                invocation.inputs
            )
            if unknown_prestamped:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_input_view_authority_drift: "
                    f"invocation={invocation.invocation_id}, "
                    f"unknown_inputs={sorted(unknown_prestamped)}"
                )
            for input_name, raw in invocation.inputs.items():
                input_spec = spec.inputs[input_name]
                paths = raw if isinstance(raw, tuple) else (raw,)
                item_runtime_type = (
                    _aggregate_method_input_item_type(input_spec.runtime_type)
                    if isinstance(raw, tuple)
                    else input_spec.runtime_type
                )
                prestamped = tuple(
                    invocation.input_read_authorities.get(input_name, ())
                )
                if prestamped:
                    if len(prestamped) != len(paths):
                        raise ValueError(
                            "planner_configuration_error: "
                            "planner.method_input_view_authority_drift: "
                            f"invocation={invocation.invocation_id}, "
                            f"input={input_name}, paths={len(paths)}, "
                            f"authorities={len(prestamped)}"
                        )
                    for index, (path, authority) in enumerate(
                        zip(paths, prestamped, strict=True)
                    ):
                        authority.verify(
                            method_id=invocation.method_id,
                            invocation_id=invocation.invocation_id,
                            input_name=input_name,
                            item_index=index,
                            view_mode=input_spec.view.mode,
                            domain_type=input_spec.domain_type,
                            runtime_type=item_runtime_type,
                            scope_id=invocation.scope,
                            raw_path=path,
                            production=True,
                        )
                    authorities[input_name] = prestamped
                    continue
                authorities[input_name] = tuple(
                    MethodInputReadAuthority(
                        method_id=invocation.method_id,
                        invocation_id=invocation.invocation_id,
                        input_name=input_name,
                        item_index=index,
                        view_mode=input_spec.view.mode,
                        domain_type=input_spec.domain_type,
                        runtime_type=item_runtime_type,
                        scope_id=invocation.scope,
                        source=source_for(
                            path,
                            input_name=input_name,
                            item_index=index,
                            view_mode=input_spec.view.mode,
                            input_binding=input_spec.binding,
                            invocation_inputs=invocation.inputs,
                            identity_companion_path=(
                                invocation.inputs.get(f"{input_name}_value")
                                if input_spec.view.mode == "identity"
                                and isinstance(
                                    invocation.inputs.get(
                                        f"{input_name}_value"
                                    ),
                                    str,
                                )
                                else None
                            ),
                        ),
                    )
                    for index, path in enumerate(paths)
                )
            template_authority = polynomial_template_authority(
                plan=plan,
                invocation=invocation,
                authorities=authorities,
            )
            if template_authority is not None:
                # Hidden coefficient identity is injected only after the
                # exact ordinal-0 state authority has been proved.
                invocation_inputs[template_authority.input_name] = (
                    template_authority.runtime_path
                )
                authorities[template_authority.input_name] = (
                    template_authority,
                )
            supporting_authority = symbolic_basis_authority(
                plan=plan,
                invocation=invocation,
                authorities=authorities,
            )
            invocations.append(
                replace(
                    invocation,
                    inputs=invocation_inputs,
                    input_read_authorities=authorities,
                    supporting_input_read_authorities=(
                        {
                            "symbolic_basis_source": (
                                supporting_authority,
                            )
                        }
                        if supporting_authority is not None
                        else {}
                    ),
                )
            )
        return replace(plan, invocations=invocations)

    stamped_plans = tuple(stamp_plan(plan) for plan in compiled.plans)
    stamped_replay_plans = tuple(
        stamp_plan(plan) for plan in compiled.replay_plans
    )
    typed_bindings = tuple(
        item.logical_binding
        for item in prepared_call.arg_bindings
        if item.logical_binding.consumption_mode == "typed_binding"
    )
    decisions = compiled.binding_consumption_decisions
    if typed_bindings:
        typed_audit = audit_compiled_functional_arg_consumption(
            typed_bindings,
            stamped_plans,
            expected_runtime_paths={item.key: None for item in typed_bindings},
        )
        if typed_audit.mismatches:
            first = typed_audit.mismatches[0]
            raise ValueError(
                "planner_configuration_error: "
                "planner.functional_runtime_input_mapping_drift: "
                f"call={prepared_call.call_id}, "
                f"arg={first['arg_name']}[{first['item_index']}], "
                f"target={first['runtime_target']}, "
                f"details={first['details']}"
            )
        typed_decisions = {
            (
                item["arg_name"],
                item["item_index"],
                item["runtime_target"],
            ): item
            for item in typed_audit.decisions
        }
        decisions = tuple(
            typed_decisions.get(
                (
                    item["arg_name"],
                    item["item_index"],
                    item["runtime_target"],
                ),
                item,
            )
            for item in decisions
        )

    return replace(
        compiled,
        plans=stamped_plans,
        replay_plans=stamped_replay_plans,
        binding_consumption_decisions=decisions,
    )


def _aggregate_method_input_item_type(runtime_type: str) -> str:
    aggregate = {
        "Coefficients": "ParameterValue",
        "PointList": "Point",
        "SymbolList": "Symbol",
    }.get(runtime_type)
    if aggregate is not None:
        return aggregate
    for prefix in ("tuple[", "list["):
        if runtime_type.startswith(prefix) and runtime_type.endswith("]"):
            return runtime_type[len(prefix) : -1]
    return runtime_type


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
            returned.runtime_path
            or _runtime_path_for_write(call.plans, returned.expected_write),
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


def _compile_verified_subplan_publication_envelope(
    prepared_call: PreparedFunctionalCall,
    *,
    capability: Any,
    projected_state_writes: Sequence[ProjectedStateWrite],
    runtime_context: RuntimeContext,
) -> CompiledFunctionalCall:
    """Compile only public return allocation for a prepared Macro fragment.

    Candidate and winner Functions are executed by the fragment runner.  This
    envelope contains no recipe Method graph; it only gives transaction commit
    an exact destination and typed write authority for each public export.
    """

    return_specs = {item.name: item for item in capability.returns}
    source_handles = tuple(
        unique_ordered(
            value.handle
            for values in prepared_call.reconciliation.resolved_args.values()
            for value in values
            if isinstance(value.handle, str) and value.handle
        )
    )
    public_returns: list[CompiledPublicReturn] = []
    for allocation in prepared_call.reconciliation.returns:
        return_spec = return_specs.get(allocation.return_name)
        if return_spec is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.functional_compile_contract_incomplete: "
                f"call={prepared_call.call_id}, unknown Macro return="
                f"{allocation.return_name}"
            )
        matches = tuple(
            item
            for item in projected_state_writes
            if item.step_id == prepared_call.call_id
            and (
                item.return_name == allocation.return_name
                or item.produced_handle
                in {allocation.handle, allocation.state_handle}
            )
        )
        unique_matches = tuple(
            {
                stable_hash(item.to_payload()): item
                for item in matches
            }.values()
        )
        if len(unique_matches) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_missing: "
                f"call={prepared_call.call_id}, return="
                f"{allocation.return_name}, projected_writes="
                f"{len(unique_matches)}"
            )
        projected = unique_matches[0]
        runtime_path = _verified_subplan_publication_path(
            runtime_context,
            scope_id=allocation.valid_scope,
            call_id=prepared_call.call_id,
            return_name=allocation.return_name,
        )
        runtime_destination = (
            RuntimeDestinationKey(
                projected.logical_state_key.object_id,
                projected.logical_state_key.state_kind,
                projected.logical_state_key.runtime_type,
                runtime_path,
            )
            if projected.logical_state_key is not None
            else None
        )
        write = StateWriteProvenance(
            step_id=prepared_call.call_id,
            scope_id=allocation.valid_scope,
            capability_id=prepared_call.capability_id,
            produced_handle=allocation.state_handle or allocation.handle,
            output_key=allocation.return_name,
            runtime_type=allocation.runtime_type,
            identity_policy=allocation.identity_policy,
            identity_role=return_spec.semantic_role or allocation.return_name,
            evidence_roles=tuple(
                unique_ordered(
                    (
                        return_spec.semantic_role or allocation.return_name,
                        *return_spec.provides_semantic_roles,
                    )
                )
            ),
            object_ref=projected.object_ref,
            source_handles=source_handles,
            state_slot_id=(
                projected.state_slot_id
                if projected.logical_state_key is not None
                else None
            ),
            write_mode=projected.write_mode,
            previous_write_step_id=projected.previous_write_step_id,
            transition_kind=projected.transition_kind,
            dependency_object_refs=projected.dependency_object_refs,
            source_state_slot_ids=projected.source_state_slot_ids,
            lineage=projected.lineage,
            math_object_id=projected.math_object_id,
            logical_state_key=projected.logical_state_key,
            typed_slot_id=projected.typed_slot_id,
            selected_version_id=projected.selected_version_id,
            previous_version_id=projected.previous_version_id,
            computation_key=projected.computation_key,
            source_version_ids=projected.source_version_ids,
            allocation_action=projected.allocation_action,
            free_symbol_ids=projected.free_symbol_ids,
            return_name=allocation.return_name,
            runtime_destination_key=runtime_destination,
            canonical_producer_call_id=projected.canonical_producer_call_id,
            valid_scope_id=projected.valid_scope_id or allocation.valid_scope,
        )
        public_returns.append(
            CompiledPublicReturn(
                return_name=allocation.return_name,
                allocation=allocation,
                expected_write=write,
                required=(
                    return_spec.required
                    or allocation.return_name
                    in prepared_call.required_return_names
                ),
                max_independent_free_parameters=(
                    return_spec.max_independent_free_parameters
                ),
                runtime_path=runtime_path,
            )
        )
    return CompiledFunctionalCall(
        call_id=prepared_call.call_id,
        step_ids=prepared_call.step_ids,
        declarations=(),
        plans=(),
        public_returns=tuple(public_returns),
        replay_plans=(),
        binding_consumption_decisions=(),
        output_write_authorities=(),
    )


def _verified_subplan_publication_path(
    context: RuntimeContext,
    *,
    scope_id: str,
    call_id: str,
    return_name: str,
) -> str:
    scope = context.get_scope(scope_id)
    key = "__verified_subplan_" + stable_hash(
        {
            "scope_id": scope_id,
            "call_id": call_id,
            "return_name": return_name,
        }
    )[:20]
    if scope.scope_type == "problem":
        return f"$problem.outputs.{key}"
    return f"${scope.scope_type}.{scope.scope_id}.outputs.{key}"


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
            runtime_path=(
                _runtime_path_for_write(
                    plans,
                    writes[allocation.return_name],
                )
                if allocation.return_name in writes
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
    output_write_authorities = tuple(
        authority
        for plan in plans
        for invocation in plan.invocations
        for _output_name, authority in sorted(
            invocation.output_write_authorities.items()
        )
    )
    wrapped = CompiledFunctionalCall(
        call_id=prepared_call.call_id,
        step_ids=prepared_call.step_ids,
        declarations=declarations,
        plans=plans,
        public_returns=public_returns,
        replay_plans=replay_plans,
        binding_consumption_decisions=audit.decisions,
        output_write_authorities=output_write_authorities,
    )
    _audit_method_output_write_authorities(wrapped)
    return wrapped


def _audit_method_output_write_authorities(
    compiled: CompiledFunctionalCall,
) -> None:
    allocations = {
        item.return_name: item.allocation
        for item in compiled.public_returns
    }
    writes = {
        item.return_name: item.expected_write
        for item in compiled.public_returns
    }
    invocations = {
        invocation.invocation_id: (plan, invocation)
        for plan in compiled.plans
        for invocation in plan.invocations
    }
    seen: set[tuple[str, str]] = set()
    for authority in compiled.output_write_authorities:
        key = (authority.invocation_id, authority.output_name)
        if key in seen:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_binding_contract_invalid: "
                f"call={compiled.call_id}, duplicate={key!r}"
            )
        seen.add(key)
        allocation = allocations.get(authority.function_return_name)
        if allocation is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_missing: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=public return allocation missing"
            )
        invocation_entry = invocations.get(authority.invocation_id)
        if invocation_entry is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_missing: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=compiled invocation missing"
            )
        plan, invocation = invocation_entry
        source_path = invocation.outputs.get(authority.output_name)
        runtime_path = plan.promote_outputs.get(source_path or "")
        if source_path is None or runtime_path is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_missing: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=compiled destination missing"
            )
        try:
            authority.verify(
                allocation=allocation,
                runtime_path=runtime_path,
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        write = writes.get(authority.function_return_name)
        if write is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_missing: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=compiled write provenance missing"
            )
        common_expected = (
            authority.function_return_name,
            authority.runtime_type,
            authority.valid_scope,
        )
        common_observed = (
            write.return_name,
            write.runtime_type,
            write.valid_scope_id,
        )
        if common_observed != common_expected:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_drift: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=compiled write differs from authority, "
                f"expected={common_expected!r}, observed={common_observed!r}"
            )
        if isinstance(authority.destination, StateOutputDestinationAuthority):
            state_expected = (
                authority.destination.logical_state_key,
                authority.destination.selected_version_id,
                authority.destination.previous_version_id,
            )
            state_observed = (
                write.logical_state_key,
                write.selected_version_id,
                write.previous_version_id,
            )
            if state_observed != state_expected:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_output_write_authority_drift: "
                    f"call={compiled.call_id}, output={authority.output_name}, "
                    "reason=compiled StateVersion differs from authority, "
                    f"expected={state_expected!r}, observed={state_observed!r}"
                )
        elif not isinstance(
            authority.destination,
            CallResultOutputDestinationAuthority,
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_binding_contract_invalid: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=unknown output destination"
            )


def _audit_committed_method_output_writes(
    compiled: CompiledFunctionalCall,
    *,
    writes: tuple[StateWriteProvenance, ...],
) -> None:
    writes_by_return = {
        write.return_name: write
        for write in writes
        if write.return_name is not None
    }
    for authority in compiled.output_write_authorities:
        write = writes_by_return.get(authority.function_return_name)
        if write is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_missing: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=committed write missing"
            )
        if isinstance(authority.destination, StateOutputDestinationAuthority):
            runtime_path = (
                write.runtime_destination_key.runtime_path
                if write.runtime_destination_key is not None
                else None
            )
            expected = (
                authority.destination.logical_state_key,
                authority.destination.selected_version_id,
                authority.destination.previous_version_id,
                authority.runtime_path,
            )
            observed = (
                write.logical_state_key,
                write.selected_version_id,
                write.previous_version_id,
                runtime_path,
            )
            if observed != expected:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.method_output_write_authority_drift: "
                    f"call={compiled.call_id}, output={authority.output_name}, "
                    "reason=committed destination differs from authority"
                )


def _audit_method_output_runtime_results(
    compiled: CompiledFunctionalCall,
    *,
    branch: RuntimeContext,
) -> None:
    for authority in compiled.output_write_authorities:
        try:
            branch.read_path(
                authority.runtime_path,
                from_scope_id=authority.valid_scope,
                expected_type=authority.runtime_type,
            )
        except (KeyError, PermissionError, TypeError, ValueError) as exc:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_output_write_authority_drift: "
                f"call={compiled.call_id}, output={authority.output_name}, "
                "reason=runtime result does not match authorized destination"
            ) from exc


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
                        tuple(
                            sorted(
                                (
                                    input_name,
                                    tuple(
                                        authority.authority_signature
                                        for authority in authorities
                                    ),
                                )
                                for input_name, authorities in (
                                    invocation.input_read_authorities.items()
                                )
                            )
                        ),
                        tuple(
                            sorted(
                                (
                                    input_name,
                                    tuple(
                                        authority.authority_signature
                                        for authority in authorities
                                    ),
                                )
                                for input_name, authorities in (
                                    invocation.supporting_input_read_authorities.items()
                                )
                            )
                        ),
                        tuple(
                            sorted(
                                authority.authority_signature
                                for authority in invocation.output_write_authorities.values()
                            )
                        ),
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
        (
            compiled.problem_call_binding.binding_signature
            if compiled.problem_call_binding is not None
            else None
        ),
        (
            compiled.macro_preparation_authority.preparation_signature
            if compiled.macro_preparation_authority is not None
            else None
        ),
        (
            compiled.macro_search_report.search_signature
            if compiled.macro_search_report is not None
            else None
        ),
        (
            compiled.verified_subplan_execution.execution_signature
            if compiled.verified_subplan_execution is not None
            else None
        ),
        tuple(
            authority.authority_signature
            for authority in compiled.output_write_authorities
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


def _require_macro_canonical_plan_id(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    call_id: str,
) -> str:
    plan_id = reconciliation.canonical_plan_id
    if plan_id is None:
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "runtime-search Macro requires the canonical scoped v3 plan id",
            retryability="configuration",
            details={
                "call_id": call_id,
                "missing_authority": "canonical_plan_id",
            },
        )
    return plan_id


def _prepare_runtime_search_macro(
    prepared: PreparedFunctionalCall,
    *,
    capability: Any,
    graph: LogicalFunctionalGraph,
    reconciliation: FunctionalPlanReconciliationResult,
    runtime_context: RuntimeContext,
    working: WorkingPlannerState,
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
    capability_catalog: FunctionalCapabilityCatalog,
    compiler: FunctionalCallCompilerService,
    committer: Any,
    object_registry: MathObjectRegistry,
    committed_state_writes: tuple[StateWriteProvenance, ...],
    committed_calls: tuple[CompiledFunctionalCall, ...],
    executor_factory: Callable[[PlannerInputs, RuntimeContext], Any],
) -> PreparedFunctionalCall:
    """Choose a Macro winner in disposable branches before final compilation."""

    macro = capability.source if capability is not None else None
    if (
        not isinstance(macro, MacroSpec)
        or macro.execution_mode != "runtime_search"
        or macro.search is None
    ):
        return prepared
    problem_context = reconciliation.functional_problem_binding_context
    ledger = reconciliation.functional_problem_binding_ledger
    debug_preparation = problem_context is None and ledger is None
    if not debug_preparation and not isinstance(
        problem_context,
        FunctionalProblemBindingContext,
    ):
        raise ValueError(
            "planner.macro_contract_invalid: runtime-search Macro has no "
            f"F5-C draft authority: call={prepared.call_id}"
        )
    definitions = default_macro_definition_registry()
    definitions.require_catalog_contract(
        macro.macro_id,
        macro.search,
        execution_strategy=macro.adapter.execution_strategy,
        internal_call_ids=tuple(item.call_id for item in macro.internal_calls),
        export_names=tuple(item.name for item in macro.returns),
    )
    request = MacroPreparationRequest(
        planning_context_id=(
            problem_context.planning_context_id
            if isinstance(problem_context, FunctionalProblemBindingContext)
            else stable_hash(
                {
                    "debug_macro_preparation": "planning_context",
                    "problem_id": inputs.problem_id,
                }
            )
        ),
        problem_revision_id=(
            problem_context.problem_revision_id
            if isinstance(problem_context, FunctionalProblemBindingContext)
            else stable_hash(
                {
                    "debug_macro_preparation": "problem_revision",
                    "problem_id": inputs.problem_id,
                }
            )
        ),
        problem_semantic_hash=(
            problem_context.problem_semantic_hash
            if isinstance(problem_context, FunctionalProblemBindingContext)
            else stable_hash(
                {
                    "debug_macro_preparation": "problem_semantics",
                    "problem": repr(inputs.problem),
                }
            )
        ),
        plan_id=_require_macro_canonical_plan_id(
            reconciliation,
            call_id=prepared.call_id,
        ),
        call_id=prepared.call_id,
        goal_unit_ids=(
            problem_context.call_goal_bindings.get(prepared.call_id, ())
            if isinstance(problem_context, FunctionalProblemBindingContext)
            else ()
        ),
        scope_id=prepared.execution_scope_id,
        macro_id=macro.macro_id,
        catalog_signature=stable_hash(macro.to_payload()),
        authored_roles=_authored_macro_roles(prepared, macro),
        candidate_dependency_envelope=(),
        environment=MacroPreparationEnvironment(
            prepared_call=prepared,
            handle_registry=handle_registry,
            binding_catalog=(
                ledger.draft.source_catalog
                if isinstance(ledger, FunctionalProblemBindingLedger)
                else getattr(problem_context, "source_catalog", None)
            ),
            max_candidates=macro.search.max_candidates,
        ),
        upstream_exact_state_signature=_macro_upstream_state_signature(
            prepared
        ),
    )

    def evaluate(
        candidate: MacroCandidateBindingAuthority,
    ) -> CandidateEvaluation:
        candidate_prepared = replace(
            prepared,
            macro_role_overrides=dict(candidate.candidate.role_bindings),
            macro_candidate_binding=candidate,
        )
        shadow_working = working.fork()
        shadow_context = runtime_context.fork()
        try:
            fragment_execution = _execute_transparent_macro_fragment(
                candidate,
                prepared=candidate_prepared,
                reconciliation=reconciliation,
                working=shadow_working,
                object_registry=object_registry,
                handle_registry=handle_registry,
                inputs=inputs,
                branch=shadow_context,
            )
            if not fragment_execution.passed:
                return CandidateEvaluation(
                    candidate_id=candidate.candidate.candidate_id,
                    passed=False,
                    failure_code=fragment_execution.failure_code,
                    verification=fragment_execution.verification,
                )
            return CandidateEvaluation(
                candidate_id=candidate.candidate.candidate_id,
                passed=True,
                standard_outputs={
                    name: _candidate_standard_output(value)
                    for name, value in fragment_execution.standard_outputs.items()
                },
                verification=fragment_execution.verification,
                shadow_execution_signature=fragment_execution.execution_signature,
            )
        except Exception as exc:
            return _macro_candidate_failure_or_raise(
                exc,
                macro_id=macro.macro_id,
                call_id=prepared.call_id,
                candidate_id=candidate.candidate.candidate_id,
            )

    selected = MacroPreparationService(definitions).prepare(
        request,
        search_spec=macro.search,
        evaluator=evaluate,
    )
    if debug_preparation:
        debug_prepared = replace(
            prepared,
            macro_role_overrides=dict(
                selected.authority.winner.candidate.role_bindings
            ),
            macro_candidate_binding=selected.authority.winner,
            prepared_macro=replace(selected, debug_only=True),
        )
        return debug_prepared
    if not isinstance(ledger, FunctionalProblemBindingLedger):
        raise ValueError(
            "planner.macro_contract_invalid: runtime-search Macro has no "
            f"F5-C ledger: call={prepared.call_id}"
        )
    finalized_ledger = ledger.finalize_macro(
        prepared.call_id,
        preparation_authority=selected.authority,
    )
    finalized_binding = finalized_ledger.call_binding(prepared.call_id)
    finalized_prepared = replace(
        prepared,
        macro_role_overrides=dict(
            selected.authority.winner.candidate.role_bindings
        ),
        macro_candidate_binding=selected.authority.winner,
        prepared_macro=selected,
        problem_call_binding=finalized_binding,
    )
    return finalized_prepared


def _macro_failure_retryability(value: Any) -> str:
    """Classify only explicit candidate failures as search misses."""

    retryability = getattr(value, "retryability", None)
    if retryability in {
        "planner_repairable",
        "problem_semantics",
        "configuration",
    }:
        return str(retryability)
    authority = getattr(value, "diagnostic_authority", None)
    if isinstance(authority, Mapping):
        retryability = authority.get("retryability")
        if retryability in {
            "planner_repairable",
            "problem_semantics",
            "configuration",
        }:
            return str(retryability)
    details = getattr(value, "details", None)
    if isinstance(details, Mapping):
        retryability = details.get("retryability")
        if retryability in {
            "planner_repairable",
            "problem_semantics",
            "configuration",
        }:
            return str(retryability)
    code = getattr(value, "code", None)
    if is_planner_configuration_failure_code(
        str(code) if code is not None else None
    ):
        return "configuration"
    # An unclassified candidate failure is a runtime contract defect, never a
    # mathematical search miss.
    return "configuration"


def _macro_candidate_failure_or_raise(
    exc: Exception,
    *,
    macro_id: str,
    call_id: str,
    candidate_id: str,
) -> CandidateEvaluation:
    retryability = _macro_failure_retryability(exc)
    if retryability == "planner_repairable":
        return CandidateEvaluation(
            candidate_id=candidate_id,
            passed=False,
            failure_code=str(
                getattr(exc, "code", "functional.macro_candidate_failed")
            ),
            verification=(
                VerificationOutcome(
                    passed=False,
                    check_code=str(
                        getattr(
                            exc,
                            "code",
                            "functional.macro_candidate_failed",
                        )
                    ),
                    expected=dict(getattr(exc, "expected", {}) or {}),
                    observed={
                        "message": str(exc),
                        "details": dict(getattr(exc, "details", {}) or {}),
                    },
                    evidence=tuple(
                        str(value)
                        for value in (
                            getattr(exc, "step_id", None),
                            getattr(exc, "arg_name", None),
                        )
                        if value
                    ),
                ),
            ),
        )
    if isinstance(exc, MacroRuntimeSearchError):
        raise exc
    raise MacroRuntimeSearchError(
        "planner.macro_candidate_execution_error",
        "Macro shadow candidate raised a non-repairable exception",
        retryability=retryability,
        details={
            "macro_id": macro_id,
            "call_id": call_id,
            "candidate_id": candidate_id,
            "exception_type": type(exc).__name__,
            "exception_code": getattr(exc, "code", None),
            "message": str(exc),
            "exception_details": dict(getattr(exc, "details", {}) or {}),
        },
    ) from exc


def _macro_upstream_state_signature(
    prepared: PreparedFunctionalCall,
) -> str:
    return stable_hash(
        {
            "state_reads": [
                {
                    "arg_name": item.arg_name,
                    "item_index": item.item_index,
                    "version": item.selected_version_id.to_payload(),
                    "runtime_type": item.runtime_value.type,
                    "value": _runtime_authority_value_payload(
                        item.runtime_value.value
                    ),
                }
                for item in prepared.state_reads
            ],
            "dependencies": list(prepared.dependency_call_ids),
        }
    )


def _macro_transaction_output_signature(
    runtime_results: Sequence[Any],
    writes: Sequence[Any],
) -> str:
    return stable_hash(
        {
            "results": [
                {
                    "output_key": item.output_key,
                    "runtime_type": item.runtime_type,
                    "value": _runtime_authority_value_payload(item.value),
                }
                for item in runtime_results
            ],
            "writes": [
                {
                    "return_name": item.return_name,
                    "runtime_type": item.runtime_type,
                    "result_form": item.result_form,
                    "free_symbol_names": list(item.free_symbol_names),
                }
                for item in writes
            ],
        }
    )


def _runtime_authority_value_payload(value: Any) -> Any:
    """Canonicalize values used by Macro preparation/replay authority."""

    if isinstance(value, sp.Basic):
        return {"sympy": sp.srepr(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _runtime_authority_value_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_runtime_authority_value_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        return _runtime_authority_value_payload(to_payload())
    raise MacroRuntimeSearchError(
        "planner.macro_contract_invalid",
        "Macro authority encountered a runtime value without canonical serialization",
        retryability="configuration",
        details={"runtime_value_type": type(value).__name__},
    )


def _candidate_standard_output(value: Any) -> Any:
    """Keep searchable scalar exports symbolic while remaining JSON-safe."""

    if isinstance(value, sp.Basic):
        return str(sp.simplify(value))
    if isinstance(value, Mapping):
        return {
            str(key): _candidate_standard_output(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_candidate_standard_output(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    to_payload = getattr(value, "to_payload", None)
    if callable(to_payload):
        return _candidate_standard_output(to_payload())
    raise MacroRuntimeSearchError(
        "planner.macro_contract_invalid",
        "fragment export has no canonical standard-output representation",
        retryability="configuration",
        details={"runtime_value_type": type(value).__name__},
    )


def _execute_transparent_macro_fragment(
    candidate: MacroCandidateBindingAuthority,
    *,
    prepared: PreparedFunctionalCall,
    reconciliation: FunctionalPlanReconciliationResult,
    working: WorkingPlannerState,
    object_registry: MathObjectRegistry,
    handle_registry: CanonicalHandleRegistry,
    inputs: PlannerInputs,
    branch: RuntimeContext,
) -> FunctionalPlanFragmentExecution:
    """Execute one fragment through typed Method read authorities."""

    binding_context = reconciliation.functional_problem_binding_context
    ledger = reconciliation.functional_problem_binding_ledger
    source_catalog = (
        ledger.draft.source_catalog
        if isinstance(ledger, FunctionalProblemBindingLedger)
        else getattr(binding_context, "source_catalog", None)
    )
    allowed_handles = frozenset(candidate.allowed_source_handles)
    materialized_paths: dict[tuple[str, str, str], str] = {}

    def materialize(
        semantic_ref: str,
        view_mode: str,
        runtime_type: str,
        value: TypedValue,
    ) -> str:
        key = (semantic_ref, view_mode, runtime_type)
        path = materialized_paths.get(key)
        if path is not None:
            return path
        token = stable_hash(
            {
                "call_id": prepared.call_id,
                "fragment": candidate.candidate.fragment.fragment_signature,
                "semantic_ref": semantic_ref,
                "view_mode": view_mode,
                "runtime_type": runtime_type,
            }
        )[:20]
        path = _fragment_source_snapshot_path(
            branch,
            scope_id=prepared.execution_scope_id,
            token=token,
        )
        branch.write_path(
            path,
            value,
            from_scope_id=prepared.execution_scope_id,
        )
        materialized_paths[key] = path
        return path

    def resolve_source(
        semantic_ref: str,
        view_mode: str,
        runtime_type: str,
    ) -> FragmentRuntimeSource:
        handles: set[str] = set()
        if source_catalog is not None:
            handles.update(
                str(item.runtime_node_id)
                for item in source_catalog.bindings.values()
                if item.usage == "input"
                and item.semantic_ref.ref == semantic_ref
                and item.runtime_node_id in allowed_handles
            )
        if semantic_ref in allowed_handles:
            handles.add(semantic_ref)
        if source_catalog is None:
            handles.update(
                handle
                for handle in allowed_handles
                if handle.rsplit(":", 1)[-1] == semantic_ref
                or str(
                    handle_registry.entity_payloads.get(handle, {}).get(
                        "name", ""
                    )
                )
                == semantic_ref
            )
        if len(handles) != 1:
            raise MacroRuntimeSearchError(
                "planner.method_input_view_authority_drift",
                "transparent fragment source is not uniquely pinned",
                retryability="configuration",
                details={
                    "call_id": prepared.call_id,
                    "semantic_ref": semantic_ref,
                    "candidate_count": len(handles),
                },
            )
        handle = next(iter(handles))
        fact_payload = handle_registry.fact_payloads.get(handle)
        if fact_payload is not None:
            path = materialize(
                semantic_ref,
                view_mode,
                runtime_type,
                TypedValue("Condition", dict(fact_payload), source=handle),
            )
            return FragmentRuntimeSource(
                semantic_ref=semantic_ref,
                runtime_type="Condition",
                value=dict(fact_payload),
                authority_signature=stable_hash(
                    {
                        "kind": "problem_condition",
                        "handle": handle,
                        "payload": dict(fact_payload),
                    }
                ),
                runtime_path=path,
                read_source=ConditionReadSource(handle, path),
            )

        object_id = object_registry.resolve(handle)
        if object_id is None:
            raise MacroRuntimeSearchError(
                "planner.method_input_view_authority_missing",
                "transparent fragment Entity has no MathObject identity",
                retryability="configuration",
                details={
                    "call_id": prepared.call_id,
                    "semantic_ref": semantic_ref,
                },
            )
        if view_mode == "identity":
            point_ref = PointRef(
                name=semantic_ref,
                path=handle,
                definition={
                    "definition": "typed_entity_identity",
                    "entity_handle": handle,
                },
                scope_id=prepared.execution_scope_id,
            )
            path = materialize(
                semantic_ref,
                view_mode,
                runtime_type,
                TypedValue("PointRef", point_ref, source=handle),
            )
            return FragmentRuntimeSource(
                semantic_ref=semantic_ref,
                runtime_type=runtime_type,
                value=point_ref,
                authority_signature=stable_hash(
                    {
                        "kind": "entity_identity",
                        "handle": handle,
                        "object_id": object_id.to_payload(),
                    }
                ),
                runtime_path=path,
                read_source=EntityIdentityReadSource(handle, path),
            )
        selected = working.identity_index.latest_visible_for_object(
            object_id,
            consumer_scope_id=prepared.execution_scope_id,
        )
        if selected is None:
            raise MacroRuntimeSearchError(
                "planner.method_input_view_authority_missing",
                "transparent fragment Entity has no visible exact state",
                retryability="configuration",
                details={
                    "call_id": prepared.call_id,
                    "semantic_ref": semantic_ref,
                },
            )
        runtime_value = working.runtime_version_values.get(selected.version_id)
        if runtime_value is None:
            raise MacroRuntimeSearchError(
                "planner.method_input_view_authority_missing",
                "transparent fragment exact state has no runtime value",
                retryability="configuration",
                details={
                    "call_id": prepared.call_id,
                    "semantic_ref": semantic_ref,
                },
            )
        path = materialize(
            semantic_ref,
            view_mode,
            runtime_type,
            runtime_value,
        )
        return FragmentRuntimeSource(
            semantic_ref=semantic_ref,
            runtime_type=runtime_type,
            value=runtime_value.value,
            authority_signature=stable_hash(
                {
                    "kind": "state_version",
                    "handle": handle,
                    "version_id": selected.version_id.to_payload(),
                    "runtime_value": _runtime_authority_value_payload(
                        runtime_value.value
                    ),
                }
            ),
            runtime_path=path,
            read_source=StateVersionReadSource(selected.version_id, path),
        )

    return FunctionalPlanFragmentTransactionalRunner(
        FunctionSpecRegistry.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
        inputs.method_specs,
    ).execute(
        candidate.candidate.fragment,
        context=branch,
        source_resolver=resolve_source,
    )


def _fragment_source_snapshot_path(
    context: RuntimeContext,
    *,
    scope_id: str,
    token: str,
) -> str:
    scope = context.get_scope(scope_id)
    key = f"__fragment_source_{token}"
    if scope.scope_type == "problem":
        return f"$problem.facts.{key}"
    return f"${scope.scope_type}.{scope.scope_id}.facts.{key}"


def _validate_macro_winner_clean_replay(
    compiled: CompiledFunctionalCall,
    *,
    runtime_results: Sequence[Any],
    writes: Sequence[Any],
) -> None:
    authority = compiled.macro_preparation_authority
    if authority is None:
        return
    winner = tuple(
        item
        for item in authority.search_report.evaluations
        if item.candidate_id
        == authority.search_report.winner_candidate_id
    )
    if (
        len(winner) != 1
        or not winner[0].output_signature
        or not winner[0].shadow_execution_signature
        or compiled.fragment_execution is None
    ):
        raise MacroRuntimeSearchError(
            "planner.macro_contract_invalid",
            "Macro winner has no authenticated shadow output signature",
            retryability="configuration",
            details={"call_id": compiled.call_id},
        )
    observed_execution_signature = compiled.fragment_execution.execution_signature
    observed_output_signature = stable_hash(
        {
            name: _candidate_standard_output(value)
            for name, value in compiled.fragment_execution.standard_outputs.items()
        }
    )
    if (
        observed_execution_signature != winner[0].shadow_execution_signature
        or observed_output_signature != winner[0].output_signature
    ):
        raise MacroRuntimeSearchError(
            "planner.macro_winner_replay_drift",
            "Macro clean replay differs from its shadow winner",
            retryability="configuration",
            details={
                "call_id": compiled.call_id,
                "winner_candidate_id": winner[0].candidate_id,
                "expected_fragment_execution_signature": (
                    winner[0].shadow_execution_signature
                ),
                "observed_fragment_execution_signature": (
                    observed_execution_signature
                ),
                "expected_output_signature": winner[0].output_signature,
                "observed_output_signature": observed_output_signature,
            },
        )


def _materialize_fragment_public_returns(
    compiled: CompiledFunctionalCall,
    *,
    fragment_execution: FunctionalPlanFragmentExecution,
    branch: RuntimeContext,
    execution_scope_id: str,
) -> None:
    """Publish only selected fragment exports into the Macro return envelope."""

    for returned in compiled.public_returns:
        write = returned.expected_write
        value = fragment_execution.standard_outputs.get(returned.return_name)
        if write is None:
            if returned.required:
                raise MacroRuntimeSearchError(
                    "planner.method_output_write_authority_missing",
                    "Macro public return has no finalized write authority",
                    retryability="configuration",
                    details={
                        "call_id": compiled.call_id,
                        "return_name": returned.return_name,
                    },
                )
            continue
        if value is None:
            if returned.required:
                raise MacroRuntimeSearchError(
                    "planner.macro_contract_invalid",
                    "selected fragment omitted a required Macro export",
                    retryability="configuration",
                    details={
                        "call_id": compiled.call_id,
                        "return_name": returned.return_name,
                    },
                )
            continue
        path = _materialized_runtime_path(compiled, write)
        if path is None:
            raise MacroRuntimeSearchError(
                "planner.method_output_write_authority_missing",
                "Macro public return has no materialization destination",
                retryability="configuration",
                details={
                    "call_id": compiled.call_id,
                    "return_name": returned.return_name,
                },
            )
        branch.write_path(
            path,
            TypedValue(write.runtime_type, value, source="verified_subplan"),
            from_scope_id=execution_scope_id,
            allow_overwrite=True,
            allow_ancestor_write=True,
        )


def _stamp_prepared_macro_authority(
    compiled: CompiledFunctionalCall,
    *,
    prepared: PreparedFunctionalCall,
) -> CompiledFunctionalCall:
    selected = prepared.prepared_macro
    if not isinstance(selected, PreparedMacroInvocation):
        return compiled
    authority = selected.authority
    report = authority.search_report
    provenance = compiled.problem_source_provenance
    call_binding = compiled.problem_call_binding
    if selected.debug_only:
        if provenance is not None or call_binding is not None:
            raise ValueError(
                "planner.macro_contract_invalid: debug Macro preparation "
                f"received production F5-C authority: call={compiled.call_id}"
            )
        return replace(
            compiled,
            macro_preparation_authority=authority,
            macro_search_report=report,
        )
    if provenance is None or not isinstance(
        call_binding,
        FunctionalProblemCallBinding,
    ):
        raise ValueError(
            "planner.macro_contract_invalid: finalized Macro call has no "
            f"F5-C binding: call={compiled.call_id}"
        )
    if (
        call_binding.macro_preparation_signature
        != authority.preparation_signature
        or provenance.call_binding_signature
        != call_binding.binding_signature
        or provenance.macro_search_signature != report.search_signature
    ):
        raise ValueError(
            "planner.macro_contract_invalid: Macro preparation and F5-C "
            f"binding differ: call={compiled.call_id}"
        )
    return replace(
        compiled,
        macro_preparation_authority=authority,
        macro_search_report=report,
    )


def _with_prepared_macro_evidence(
    compiled: CompiledFunctionalCall,
    *,
    prepared: PreparedFunctionalCall,
) -> CompiledFunctionalCall:
    selected = prepared.prepared_macro
    if not isinstance(selected, PreparedMacroInvocation):
        return compiled
    fragment_execution = compiled.fragment_execution
    if fragment_execution is None or not fragment_execution.passed:
        raise ValueError(
            "planner.macro_contract_invalid: verified Macro has no clean "
            "fragment execution"
        )
    authority = selected.authority
    provenance = compiled.problem_source_provenance
    standard_results = {
        name: _candidate_standard_output(value)
        for name, value in fragment_execution.standard_outputs.items()
    }
    clean_execution = VerifiedSubplanCleanExecution(
        member_step_ids=tuple(
            item.step_id for item in authority.winner.candidate.fragment.steps
        ),
        fragment_execution_signature=fragment_execution.execution_signature,
        exported_results=standard_results,
        verification=fragment_execution.verification,
        provenance=(
            {
                "call_id": compiled.call_id,
                "problem_source_signature": (
                    provenance.semantic_signature()
                    if provenance is not None
                    else None
                ),
                "preparation_signature": authority.preparation_signature,
            },
        ),
    )
    subplan_witness = VerifiedSubplanWitness(
        standard_entities=dict(
            authority.winner.candidate.role_bindings
        ),
        standard_conditions=fragment_published_condition_refs(
            authority.winner.candidate.fragment,
            fragment_execution,
        ),
        standard_results=standard_results,
        provenance=(
            *clean_execution.provenance,
            *_fragment_derived_output_provenance(
                authority.winner.candidate.fragment,
                fragment_execution,
            ),
        ),
    )
    verified_subplan = VerifiedSubplanExecution(
        plan_id=authority.plan_id,
        scope_id=authority.scope_id,
        selected_fragment=authority.winner.candidate.fragment,
        selection=MacroSearchSelection(
            macro_id=authority.macro_id,
            preparation_signature=authority.preparation_signature,
            search_report=authority.search_report,
        ),
        clean_execution=clean_execution,
        witness=subplan_witness,
    )
    return replace(
        compiled,
        verified_subplan_execution=verified_subplan,
    )


def _fragment_derived_output_provenance(
    fragment: FunctionalPlanFragment,
    execution: FunctionalPlanFragmentExecution,
) -> tuple[Mapping[str, Any], ...]:
    """Preserve verified intermediate outputs without a domain-specific witness."""

    executions = {item.step_id: item for item in execution.step_executions}
    derived_authorities = {
        (value.step_id, value.return_name): value
        for consumer in fragment.steps
        for values in consumer.args.values()
        for value in values
        if isinstance(value, ScopedDerivedResultRef)
    }
    result: list[Mapping[str, Any]] = []
    for step in fragment.steps:
        executed = executions.get(step.step_id)
        if executed is None:
            continue
        for return_name, binding in step.return_bindings.items():
            if binding.kind != "derived" or return_name not in executed.outputs:
                continue
            authority = derived_authorities.get((step.step_id, return_name))
            payload = {
                "kind": "fragment_derived_output",
                "ref": binding.ref,
                "producer_step_id": step.step_id,
                "capability_id": step.capability_id,
                "return_name": return_name,
                "value": _candidate_standard_output(
                    executed.outputs[return_name]
                ),
            }
            if authority is not None:
                payload.update(
                    {
                        "domain_type": authority.domain_type,
                        "semantic_role": authority.semantic_role,
                        "owner_scope": authority.owner_scope,
                    }
                )
            result.append(payload)
    return tuple(result)


def _authored_macro_roles(
    prepared: PreparedFunctionalCall,
    macro: MacroSpec,
) -> dict[str, str]:
    assert macro.search is not None
    return dict(prepared.reconciliation.authored_macro_roles)


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
        dict[str, TypedValue],
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
        result_values: dict[str, TypedValue] = {}
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
                        details={
                            "return": returned.return_name,
                            "expected_form": expected_form,
                            "observed_form": actual_form,
                            "observed_free_symbol_names": list(free_symbols),
                            "repair_action": "provide_visible_state_producer",
                        },
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
            result_values[write.output_key] = typed
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
                result_values,
                tuple(issues),
            )
        return (
            tuple(runtime_results),
            tuple(actual_writes),
            tuple(versions),
            runtime_values,
            result_values,
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
        conditions = _restored_conditions(
            restored_seed,
            parent_context=parent_context,
        )
        runtime_equivalent_aliases: list[
            FunctionalRuntimeEquivalentCallAlias
        ] = []
        runtime_state_equivalence_probe_results: list[dict[str, Any]] = []
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
            compiled: CompiledFunctionalCall | None = None
            predicate_outcomes: tuple[VerificationOutcome, ...] = ()
            pending_conditions: tuple[Condition, ...] = ()
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
                capability = capability_catalog.get(
                    prepared.capability_id
                )
                committed_state_writes = tuple(
                    write
                    for result in results
                    if result.status == "verified"
                    for write in result.state_writes
                )
                prepared = _prepare_runtime_search_macro(
                    prepared,
                    capability=capability,
                    graph=graph,
                    reconciliation=reconciliation,
                    runtime_context=current_context,
                    working=working,
                    inputs=inputs,
                    handle_registry=handle_registry,
                    capability_catalog=capability_catalog,
                    compiler=exact_compiler,
                    committer=committer,
                    object_registry=object_registry,
                    committed_state_writes=committed_state_writes,
                    committed_calls=tuple(compiled_calls),
                    executor_factory=self._executor_factory,
                )
                compiled = exact_compiler.compile(
                    prepared,
                    reconciliation=reconciliation,
                    runtime_context=current_context,
                    working=working,
                    inputs=inputs,
                    handle_registry=handle_registry,
                    capability_catalog=capability_catalog,
                    committed_state_writes=committed_state_writes,
                    committed_calls=tuple(compiled_calls),
                )
                compiled = _stamp_prepared_macro_authority(
                    compiled,
                    prepared=prepared,
                )
                _audit_compiled_problem_source_provenance(compiled)
                branch = current_context.fork()
                if isinstance(
                    prepared.prepared_macro,
                    PreparedMacroInvocation,
                ):
                    branch.ensure_step_scope(
                        prepared.call_id,
                        prepared.execution_scope_id,
                    )
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
                if not isinstance(
                    prepared.prepared_macro,
                    PreparedMacroInvocation,
                ):
                    compiled, prepared = _materialize_compiled_parameter_inputs(
                        compiled,
                        prepared=prepared,
                        branch=branch,
                        working=working,
                        object_registry=object_registry,
                        execution_scope_id=prepared.execution_scope_id,
                    )
                    compiled = _stamp_method_input_read_authorities(
                        compiled,
                        prepared_call=prepared,
                        method_specs=inputs.method_specs,
                        branch=branch,
                        working=working,
                        condition_authority_index=(
                            reconciliation.condition_binding_authority_index
                        ),
                    )
                _audit_method_output_write_authorities(compiled)
                executor = self._executor_factory(inputs, branch)
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
                                macro_preparation_authority=(
                                    compiled.macro_preparation_authority
                                ),
                                macro_search_report=(
                                    compiled.macro_search_report
                                ),
                            )
                        )
                        continue
                fragment_execution: FunctionalPlanFragmentExecution | None = None
                if isinstance(prepared.prepared_macro, PreparedMacroInvocation):
                    candidate = prepared.macro_candidate_binding
                    if not isinstance(candidate, MacroCandidateBindingAuthority):
                        raise MacroRuntimeSearchError(
                            "planner.macro_contract_invalid",
                            "prepared transparent Macro has no selected fragment",
                            retryability="configuration",
                            details={"call_id": call_id},
                        )
                    fragment_execution = _execute_transparent_macro_fragment(
                        candidate,
                        prepared=prepared,
                        reconciliation=reconciliation,
                        working=working,
                        object_registry=object_registry,
                        handle_registry=handle_registry,
                        inputs=inputs,
                        branch=branch,
                    )
                    if not fragment_execution.passed:
                        raise MacroRuntimeSearchError(
                            fragment_execution.failure_code
                            or "functional.macro_candidate_failed",
                            "clean winner fragment failed verification",
                            retryability="planner_repairable",
                            details={
                                "call_id": call_id,
                                "fragment_signature": (
                                    fragment_execution.fragment_signature
                                ),
                            },
                        )
                    _materialize_fragment_public_returns(
                        compiled,
                        fragment_execution=fragment_execution,
                        branch=branch,
                        execution_scope_id=prepared.execution_scope_id,
                    )
                    compiled = replace(
                        compiled,
                        fragment_execution=fragment_execution,
                    )
                    execution = PlanExecutionResult()
                else:
                    execution = executor.execute_plan(
                        branch,
                        list(compiled.plans),
                    )
                    _audit_method_output_runtime_results(
                        compiled,
                        branch=branch,
                    )
                if capability is None:
                    raise ValueError(
                        "planner_configuration_error: "
                        "planner.functional_compile_contract_incomplete: "
                        f"call={call_id}, capability missing"
                    )
                if fragment_execution is not None:
                    predicate_outcomes = fragment_execution.verification
                else:
                    predicate_publication = (
                        PredicateConditionPublicationService().materialize(
                            call_id=call_id,
                            capability=capability,
                            plans=compiled.plans,
                            allocations=prepared.reconciliation.returns,
                            resolved_args=(
                                prepared.reconciliation.resolved_args
                            ),
                            branch=branch,
                            method_specs=inputs.method_specs,
                        )
                    )
                    predicate_outcomes = predicate_publication.outcomes
                    pending_conditions = predicate_publication.conditions
                    if predicate_publication.authorities:
                        compiled = replace(
                            compiled,
                            predicate_publication_authorities=(
                                predicate_publication.authorities
                            ),
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
                                + ", ".join(failed_closure_checks),
                                details=_symbolic_closure_drift_details(
                                    closure_result,
                                    failed_closure_checks,
                                ),
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
                compiled = _with_prepared_macro_evidence(
                    compiled,
                    prepared=prepared,
                )
                (
                    runtime_results,
                    writes,
                    versions,
                    runtime_values,
                    call_result_values,
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
                            step_results=tuple(execution.step_results),
                            root_issues=issues,
                            symbolic_closure=closure_result,
                            macro_preparation_authority=(
                                compiled.macro_preparation_authority
                            ),
                            macro_search_report=compiled.macro_search_report,
                            verified_subplan_execution=(
                                compiled.verified_subplan_execution
                            ),
                            verification_outcomes=predicate_outcomes,
                        )
                    )
                    continue
                _audit_committed_method_output_writes(
                    compiled,
                    writes=writes,
                )
                _validate_macro_winner_clean_replay(
                    compiled,
                    runtime_results=runtime_results,
                    writes=writes,
                )
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
                    _canonicalize_projected_state_write_versions(
                        item,
                        resolve_version_id=(
                            working.resolve_runtime_version_id
                        ),
                    )
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
                (
                    runtime_alias,
                    equivalence_issue,
                    probe_results,
                ) = (
                    _compare_provisional_runtime_state(
                        call_id=call_id,
                        writes=writes,
                        runtime_values=runtime_values,
                        reconciliation=reconciliation,
                        working=working,
                        branch=branch,
                        object_registry=object_registry,
                        runtime_result_values={
                            **runtime_result_values,
                            **{
                                (call_id, output_key): typed
                                for output_key, typed in call_result_values.items()
                            },
                        },
                        restored_call_ids=restored_call_ids,
                    )
                )
                runtime_state_equivalence_probe_results.extend(probe_results)
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
                            step_results=tuple(execution.step_results),
                            root_issues=(equivalence_issue,),
                            symbolic_closure=closure_result,
                            macro_preparation_authority=(
                                compiled.macro_preparation_authority
                            ),
                            macro_search_report=compiled.macro_search_report,
                            verified_subplan_execution=(
                                compiled.verified_subplan_execution
                            ),
                        )
                    )
                    continue
                lineage_edges = _scope_create_runtime_lineage_edges(
                    probe_results=probe_results,
                    reconciliation=reconciliation,
                    working=working,
                    current_versions=versions,
                )
                macro_search_report = compiled.macro_search_report
                if runtime_alias is not None:
                    if lineage_edges:
                        raise ValueError(
                            "planner_configuration_error: "
                            "planner.runtime_state_lineage_alias_conflict"
                        )
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
                    runtime_result_values.update(
                        {
                            (call_id, output_key): typed
                            for output_key, typed in call_result_values.items()
                        }
                    )
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
                    conditions.update(
                        {item.condition_id: item for item in pending_conditions}
                    )
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
                            step_results=tuple(execution.step_results),
                            symbolic_closure=closure_result,
                            macro_preparation_authority=(
                                compiled.macro_preparation_authority
                            ),
                            macro_search_report=macro_search_report,
                            verified_subplan_execution=(
                                compiled.verified_subplan_execution
                            ),
                            verification_outcomes=predicate_outcomes,
                            published_conditions=pending_conditions,
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
                writes, versions = _commit_scope_create_runtime_lineage(
                    edges=lineage_edges,
                    working=working,
                    prior_results=results,
                    current_writes=writes,
                    current_versions=versions,
                    probe_results=probe_results,
                    reconciliation=reconciliation,
                )
                runtime_result_values.update(
                    {
                        (call_id, output_key): typed
                        for output_key, typed in call_result_values.items()
                    }
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
                conditions.update(
                    {item.condition_id: item for item in pending_conditions}
                )
                compiled_calls.append(compiled)
                results.append(
                    FunctionalCallExecutionResult(
                        call_id,
                        "verified",
                        runtime_results=runtime_results,
                        state_writes=writes,
                        committed_versions=versions,
                        checks=tuple(execution.checks),
                        step_results=tuple(execution.step_results),
                        symbolic_closure=closure_result,
                        macro_preparation_authority=(
                            compiled.macro_preparation_authority
                        ),
                        macro_search_report=macro_search_report,
                        verified_subplan_execution=(
                            compiled.verified_subplan_execution
                        ),
                        verification_outcomes=predicate_outcomes,
                        published_conditions=pending_conditions,
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
                elif isinstance(exc, MacroRuntimeSearchError):
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
                        else (
                            dict(getattr(exc, "details", {}) or {})
                            if getattr(exc, "details", None) is not None
                            else None
                        )
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
                        macro_preparation_authority=(
                            compiled.macro_preparation_authority
                            if compiled is not None
                            else None
                        ),
                        macro_search_report=(
                            compiled.macro_search_report
                            if compiled is not None
                            else None
                        ),
                        verified_subplan_execution=(
                            compiled.verified_subplan_execution
                            if compiled is not None
                            else None
                        ),
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
            conditions=conditions,
            runtime_version_aliases=dict(
                working.runtime_equivalent_version_aliases
            ),
            runtime_equivalent_aliases=tuple(runtime_equivalent_aliases),
            runtime_state_equivalence_probe_results=tuple(
                runtime_state_equivalence_probe_results
            ),
            functional_problem_binding_ledger=(
                _execution_problem_binding_ledger(
                    reconciliation,
                    compiled_calls=compiled_calls,
                )
            ),
            runtime_context=current_context,
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
        projected_writes = tuple(
            _canonicalize_projected_state_write_versions(
                item,
                resolve_version_id=report.resolve_runtime_version_id,
            )
            for item in build_functional_state_write_manifest(
                reconciliation.plan,
                reconciliation.calls,
            )
        )
        projected_dependencies = tuple(
            _canonicalize_projected_state_dependency_version(
                item,
                resolve_version_id=report.resolve_runtime_version_id,
            )
            for item in reconciliation.state_dependencies
        )
        read_index = FunctionalStateReadIndex.from_sources(
            handle_registry=handle_registry,
            mode="authoritative",
            projected_state_writes=projected_writes,
            projected_state_dependencies=projected_dependencies,
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
    typed_index = seed.typed_value_index
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
            typed = typed_index.state_value(version.version_id)
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
            typed = typed_index.call_result_value(call_id, write.output_key)
            destination = write.runtime_destination_key
            runtime_path = (
                destination.runtime_path
                if destination is not None
                and destination.runtime_path is not None
                else returned.runtime_path
                or _runtime_path_for_write(compiled.plans, write)
            )
            if typed is None or runtime_path is None:
                continue
            current_context.write_path(
                runtime_path,
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
        for key, restored_result in typed_index.call_results.items():
            if key[0] == call_id:
                runtime_result_values[key] = restored_result.runtime_value
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


def _restored_conditions(
    seed: FunctionalRestoredCallSeed | None,
    *,
    parent_context: PlannerStateContext,
) -> dict[str, Condition]:
    """Audit exact immutable Condition records before restoring solved calls."""

    current = {
        item.condition_id: item for item in parent_context.state.conditions
    }
    if seed is None:
        return current
    for condition_id, expected in seed.conditions.items():
        actual = current.get(condition_id)
        if actual is None or actual.to_payload() != expected.to_payload():
            raise ValueError(
                "planner_configuration_error: "
                "planner.retry_problem_source_binding_drift: "
                f"restored condition {condition_id!r} changed"
            )
    return current


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
) -> frozenset[MathObjectId]:
    """Return symbols a method explicitly asks to retain in its basis."""

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
    materialized_state_sources = dict(compiled.materialized_state_sources)

    def exact_source_version(path: str) -> StateVersionId | None:
        pinned = {
            item.selected_version_id
            for item in prepared.state_reads
            if path in {
                item.original_runtime_path,
                item.snapshot_runtime_path,
            }
        }
        if len(pinned) > 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={compiled.call_id}, path={path}, "
                f"pinned_version_count={len(pinned)}"
            )
        if pinned:
            return next(iter(pinned))
        visible = tuple(
            item
            for item in working.identity_index.all_versions()
            if _indexed_runtime_path(item) == path
            and working.identity_index.visibility.is_visible(
                item.valid_scope_id,
                consumer_scope_id=execution_scope_id,
            )
        )
        object_ids = {
            item.version_id.slot_id.logical_key.object_id for item in visible
        }
        if len(object_ids) > 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.method_input_view_authority_drift: "
                f"call={compiled.call_id}, path={path}, "
                f"object_count={len(object_ids)}"
            )
        if not visible:
            return None
        return max(
            visible,
            key=lambda item: (
                item.version_id.ordinal,
                item.producer_call_id or "",
            ),
        ).version_id

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
                source_version_id = exact_source_version(path)
                if source_version_id is not None:
                    materialized_state_sources[snapshot_path] = (
                        source_version_id
                    )
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
        materialized_state_sources=tuple(
            sorted(materialized_state_sources.items())
        ),
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
    supplemental_parameter_values: Mapping[MathObjectId, Any] | None = None,
    resolving: tuple[StateVersionId, ...] = (),
    resolving_parameter_ids: tuple[MathObjectId, ...] = (),
    ignored_parameter_ids: frozenset[MathObjectId] = frozenset(),
) -> _RuntimeParameterClosure:
    supplemental_parameter_values = supplemental_parameter_values or {}
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
        object_id = object_ids[0]
        version = _latest_visible_parameter_version(
            object_id,
            consumer_scope_id=consumer_scope_id,
            working=working,
        )
        if version is None:
            if object_id not in supplemental_parameter_values:
                continue
            if object_id in resolving_parameter_ids:
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_parameter_state_cycle: "
                    f"objects={[item.to_payload() for item in resolving_parameter_ids]}"
                )
            supplemental = supplemental_parameter_values[object_id]
            if _symbolic_values_equivalent(supplemental, symbol):
                continue
            nested = _materialize_runtime_parameter_closure(
                TypedValue(
                    "ParameterValue",
                    supplemental,
                    source="verified_runtime_scalar_assignment",
                ),
                consumer_scope_id=consumer_scope_id,
                working=working,
                runtime_context=runtime_context,
                object_registry=object_registry,
                declared_runtime_symbols=declared_runtime_symbols,
                supplemental_parameter_values=supplemental_parameter_values,
                resolving=resolving,
                resolving_parameter_ids=(*resolving_parameter_ids, object_id),
                ignored_parameter_ids=ignored_parameter_ids,
            )
            substitutions[symbol] = nested.runtime_value.value
            versions.extend(nested.parameter_versions)
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
            supplemental_parameter_values=supplemental_parameter_values,
            resolving=(*resolving, version.version_id),
            resolving_parameter_ids=resolving_parameter_ids,
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

    def rewrite_authorities(
        authorities: Mapping[str, tuple[MethodInputReadAuthority, ...]],
    ) -> dict[str, tuple[MethodInputReadAuthority, ...]]:
        return {
            name: tuple(
                replace(
                    authority,
                    source=replace(
                        authority.source,
                        runtime_path=rewrites.get(
                            authority.source.runtime_path,
                            authority.source.runtime_path,
                        ),
                    ),
                )
                for authority in values
            )
            for name, values in authorities.items()
        }

    return replace(
        plan,
        invocations=[
            replace(
                invocation,
                inputs={
                    name: rewrite(value)
                    for name, value in invocation.inputs.items()
                },
                input_read_authorities=rewrite_authorities(
                    invocation.input_read_authorities
                ),
                supporting_input_read_authorities=rewrite_authorities(
                    invocation.supporting_input_read_authorities
                ),
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

    public_path = next(
        (
            item.runtime_path
            for item in compiled.public_returns
            if item.expected_write is write
            or (
                write.return_name is not None
                and item.return_name == write.return_name
            )
        ),
        None,
    )
    plan_path = public_path or _runtime_path_for_write(compiled.plans, write)
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


def _symbolic_closure_drift_details(
    result: SymbolicClosureExecutionResult,
    failed_checks: Sequence[str],
) -> dict[str, Any]:
    args = dict(result.validation_args or {})
    template = args.get("quadratic_template")
    observed = args.get("quadratic")
    try:
        missing_roles = tuple(
            sorted(
                str(symbol)
                for symbol in (
                    sp.sympify(template).free_symbols
                    - sp.sympify(observed).free_symbols
                )
            )
        )
    except (TypeError, ValueError, sp.SympifyError):
        missing_roles = ()
    details: dict[str, Any] = {
        "expected_template": (
            sp.sstr(template)
            if template is not None
            else "ordinal_0_polynomial_template"
        ),
        "observed_state": (
            sp.sstr(observed) if observed is not None else "unavailable"
        ),
        "missing_symbol_roles": list(missing_roles),
        "failed_checks": list(failed_checks),
        "subjects": [
            {
                "role": "coefficient_identity_template",
                "arg_name": "quadratic_template",
                "expected_type": "Expression",
                "expected_state": "ordinal_0",
                "observed_type": type(observed).__name__,
                "observed_state": "coefficient_identity_incomplete",
            }
        ],
    }
    if len(missing_roles) == 1:
        details["missing_symbol_role"] = missing_roles[0]
    return details


def _compare_scope_create_runtime_probes(
    *,
    call_id: str,
    writes: Sequence[StateWriteProvenance],
    runtime_values: Mapping[StateVersionId, TypedValue],
    reconciliation: FunctionalPlanReconciliationResult,
    working: WorkingPlannerState,
    branch: RuntimeContext,
    object_registry: MathObjectRegistry,
    runtime_result_values: Mapping[tuple[str, str], TypedValue],
    restored_call_ids: frozenset[str],
) -> tuple[tuple[dict[str, Any], ...], PlannerRetryIssue | None]:
    probes = tuple(
        probe
        for probe in reconciliation.state_runtime_equivalence_probes
        if call_id in {probe.ancestor_call_id, probe.descendant_call_id}
    )
    if not probes:
        return (), None
    current_values = {
        working.resolve_runtime_version_id(version_id): value
        for version_id, value in runtime_values.items()
    }
    declared = _context_runtime_symbol_bindings(
        branch,
        registry=object_registry,
    )
    results: list[dict[str, Any]] = []
    for probe in probes:
        ancestor_version_id = working.resolve_runtime_version_id(
            probe.ancestor_version_id
        )
        descendant_version_id = working.resolve_runtime_version_id(
            probe.descendant_version_id
        )
        ancestor = current_values.get(ancestor_version_id)
        if ancestor is None:
            ancestor = working.runtime_version_values.get(
                ancestor_version_id
            )
        descendant = current_values.get(descendant_version_id)
        if descendant is None:
            descendant = working.runtime_version_values.get(
                descendant_version_id
            )
        current_version_id = (
            ancestor_version_id
            if call_id == probe.ancestor_call_id
            else descendant_version_id
        )
        if current_version_id not in current_values:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_equivalence_probe_value_missing: "
                f"call={call_id}, version={current_version_id.to_payload()}"
            )
        if ancestor is None or descendant is None:
            other_call_id = (
                probe.descendant_call_id
                if call_id == probe.ancestor_call_id
                else probe.ancestor_call_id
            )
            other_state = working.call_states.get(other_call_id)
            if other_state is not None and other_state.status == "verified":
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_state_equivalence_probe_checkpoint_missing: "
                    f"call={other_call_id}"
                )
            continue

        supplemental = _visible_runtime_scalar_assignments(
            consumer_scope_id=probe.comparison_scope_id,
            current_call_id=call_id,
            runtime_result_values=runtime_result_values,
            reconciliation=reconciliation,
            working=working,
            runtime_context=branch,
            object_registry=object_registry,
            declared_runtime_symbols=declared,
        )
        materialized_ancestor = _materialize_runtime_parameter_closure(
            ancestor,
            consumer_scope_id=probe.comparison_scope_id,
            working=working,
            runtime_context=branch,
            object_registry=object_registry,
            declared_runtime_symbols=_merge_runtime_symbol_bindings(
                declared,
                working.runtime_version_symbol_bindings.get(
                    ancestor_version_id,
                    {},
                ),
            ),
            supplemental_parameter_values=supplemental,
        ).runtime_value
        materialized_descendant = _materialize_runtime_parameter_closure(
            descendant,
            consumer_scope_id=probe.comparison_scope_id,
            working=working,
            runtime_context=branch,
            object_registry=object_registry,
            declared_runtime_symbols=_merge_runtime_symbol_bindings(
                declared,
                working.runtime_version_symbol_bindings.get(
                    descendant_version_id,
                    {},
                ),
            ),
            supplemental_parameter_values=supplemental,
        ).runtime_value
        comparison = "runtime_equivalent"
        substitutions: dict[sp.Symbol, Any] = {}
        if not (
            runtime_type_compatible(ancestor.type, descendant.type)
            and runtime_type_compatible(descendant.type, ancestor.type)
        ):
            comparison = "runtime_type_mismatch"
        elif _symbolic_values_equivalent(
            ancestor.value,
            descendant.value,
        ):
            comparison = "runtime_equivalent"
        elif _symbolic_values_equivalent(
            materialized_ancestor.value,
            materialized_descendant.value,
        ):
            comparison = "equivalent_after_parameter_closure"
        else:
            substitutions = _runtime_refinement_substitutions(
                materialized_ancestor.value,
                materialized_descendant.value,
            )
            comparison = (
                "strict_runtime_refinement"
                if substitutions
                else "runtime_value_mismatch"
            )
        result_payload = {
            "probe_signature": stable_hash(probe.to_payload()),
            "current_call_id": call_id,
            "ancestor_call_id": probe.ancestor_call_id,
            "descendant_call_id": probe.descendant_call_id,
            "comparison_scope_id": probe.comparison_scope_id,
            "comparison": comparison,
            "lineage_parent_version_id": (
                ancestor_version_id.to_payload()
            ),
            "lineage_child_version_id": (
                descendant_version_id.to_payload()
            ),
            "lineage_rule": (
                "descendant_create_consumes_nearest_verified_ancestor_create"
            ),
            "ancestor_value": _runtime_equivalence_value_payload(
                ancestor.value
            ),
            "descendant_value": _runtime_equivalence_value_payload(
                descendant.value
            ),
            "substitutions": {
                str(symbol): _runtime_equivalence_value_payload(value)
                for symbol, value in sorted(
                    substitutions.items(),
                    key=lambda item: str(item[0]),
                )
            },
            "used_checkpoint_value": (
                (
                    probe.descendant_call_id
                    if call_id == probe.ancestor_call_id
                    else probe.ancestor_call_id
                )
                in restored_call_ids
            ),
        }
        results.append(result_payload)
        if comparison in {
            "runtime_type_mismatch",
            "runtime_value_mismatch",
        }:
            return (
                tuple(results),
                _issue(
                    call_id,
                    "planner.runtime_state_equivalence_conflict",
                    (
                        "scope-comparable create writers produced different "
                        "typed runtime states"
                    ),
                    details={
                        "probe": probe.to_payload(),
                        "comparison": result_payload,
                    },
                ),
            )
    return tuple(results), None


@dataclass(frozen=True)
class _RuntimeCreateLineageEdge:
    child_version_id: StateVersionId
    parent_version_id: StateVersionId
    root_version_id: StateVersionId
    probe_signature: str


def _scope_create_runtime_lineage_edges(
    *,
    probe_results: Sequence[dict[str, Any]],
    reconciliation: FunctionalPlanReconciliationResult,
    working: WorkingPlannerState,
    current_versions: Sequence[IndexedStateVersion],
) -> tuple[_RuntimeCreateLineageEdge, ...]:
    """Resolve successful create probes into one deterministic version line."""

    successful = {
        str(item["probe_signature"]): item
        for item in probe_results
        if item.get("comparison")
        in {
            "runtime_equivalent",
            "equivalent_after_parameter_closure",
            "strict_runtime_refinement",
        }
    }
    if not successful:
        return ()

    versions = {
        item.version_id: item
        for item in (
            *working.identity_index.all_versions(),
            *current_versions,
        )
    }
    candidates_by_child: dict[
        StateVersionId,
        list[tuple[StateVersionId, StateRuntimeEquivalenceProbe, str]],
    ] = {}
    for probe in reconciliation.state_runtime_equivalence_probes:
        signature = stable_hash(probe.to_payload())
        if signature not in successful:
            continue
        parent_id = working.resolve_runtime_version_id(
            probe.ancestor_version_id
        )
        child_id = working.resolve_runtime_version_id(
            probe.descendant_version_id
        )
        parent = versions.get(parent_id)
        child = versions.get(child_id)
        if parent is None or child is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_lineage_version_missing: "
                f"probe={signature}"
            )
        if (
            parent.version_id.slot_id.logical_key
            != child.version_id.slot_id.logical_key
        ):
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_lineage_object_drift: "
                f"probe={signature}"
            )
        candidates_by_child.setdefault(child_id, []).append(
            (parent_id, probe, signature)
        )

    selected: dict[
        StateVersionId,
        tuple[StateVersionId, StateRuntimeEquivalenceProbe, str],
    ] = {}
    scope_registry = working.identity_index.visibility.registry
    for child_id, candidates in candidates_by_child.items():
        child_scope = candidates[0][1].descendant_scope_id
        scope_rank = {
            scope_id: index
            for index, scope_id in enumerate(
                scope_registry.ancestor_scopes(child_scope)
            )
        }
        ranked = [
            (
                scope_rank.get(
                    candidate[1].ancestor_scope_id,
                    len(scope_rank),
                ),
                candidate,
            )
            for candidate in candidates
        ]
        best_rank = min(item[0] for item in ranked)
        nearest = tuple(
            item[1] for item in ranked if item[0] == best_rank
        )
        nearest_parent_ids = {item[0] for item in nearest}
        if len(nearest_parent_ids) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_lineage_parent_ambiguous: "
                f"child={child_id.to_payload()}"
            )
        selected[child_id] = nearest[0]

    prospective = dict(versions)
    for child_id, (parent_id, _probe, _signature) in selected.items():
        child = prospective[child_id]
        prospective[child_id] = replace(
            child,
            source_version_ids=unique_ordered(
                (*child.source_version_ids, parent_id)
            ),
        )

    def lineage_roots(
        version_id: StateVersionId,
        *,
        visiting: frozenset[StateVersionId] = frozenset(),
    ) -> frozenset[StateVersionId]:
        if version_id in visiting:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_lineage_cycle"
            )
        version = prospective.get(version_id)
        if version is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_lineage_version_missing: "
                f"version={version_id.to_payload()}"
            )
        same_state_sources = tuple(
            source_id
            for source_id in version.source_version_ids
            if source_id.slot_id.logical_key
            == version_id.slot_id.logical_key
        )
        if not same_state_sources:
            return frozenset({version_id})
        return frozenset(
            root
            for source_id in same_state_sources
            for root in lineage_roots(
                source_id,
                visiting=frozenset((*visiting, version_id)),
            )
        )

    edges: list[_RuntimeCreateLineageEdge] = []
    for child_id, (parent_id, _probe, signature) in selected.items():
        roots = lineage_roots(child_id)
        if len(roots) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_lineage_root_ambiguous: "
                f"child={child_id.to_payload()}, "
                f"roots={[item.to_payload() for item in sorted(roots)]}"
            )
        edges.append(
            _RuntimeCreateLineageEdge(
                child_version_id=child_id,
                parent_version_id=parent_id,
                root_version_id=next(iter(roots)),
                probe_signature=signature,
            )
        )
    return tuple(sorted(edges, key=lambda item: item.child_version_id))


def _commit_scope_create_runtime_lineage(
    *,
    edges: Sequence[_RuntimeCreateLineageEdge],
    working: WorkingPlannerState,
    prior_results: list[FunctionalCallExecutionResult],
    current_writes: Sequence[StateWriteProvenance],
    current_versions: Sequence[IndexedStateVersion],
    probe_results: Sequence[dict[str, Any]],
    reconciliation: FunctionalPlanReconciliationResult,
) -> tuple[
    tuple[StateWriteProvenance, ...],
    tuple[IndexedStateVersion, ...],
]:
    """Persist a proved lineage in every checkpoint-facing namespace."""

    if not edges:
        return tuple(current_writes), tuple(current_versions)
    parent_by_child = {
        item.child_version_id: item.parent_version_id for item in edges
    }
    parent_call_by_child = {
        child_id: (
            working.committed_versions[parent_id].producer_call_id
            if parent_id in working.committed_versions
            else None
        )
        for child_id, parent_id in parent_by_child.items()
    }

    def update_version(version: IndexedStateVersion) -> IndexedStateVersion:
        parent_id = parent_by_child.get(version.version_id)
        if parent_id is None:
            return version
        return replace(
            version,
            source_version_ids=unique_ordered(
                (*version.source_version_ids, parent_id)
            ),
        )

    def update_write(write: StateWriteProvenance) -> StateWriteProvenance:
        version_id = write.selected_version_id
        parent_id = (
            parent_by_child.get(version_id)
            if version_id is not None
            else None
        )
        if parent_id is None:
            return write
        parent_call_id = parent_call_by_child.get(version_id)
        return replace(
            write,
            source_version_ids=unique_ordered(
                (*write.source_version_ids, parent_id)
            ),
            lineage=merge_state_semantic_lineages(
                write.lineage,
                evidence_tags=("runtime_verified_create_lineage",),
                source_version_ids=(parent_id,),
                source_call_ids=(
                    (parent_call_id,) if parent_call_id is not None else ()
                ),
            ),
        )

    for child_id in parent_by_child:
        current = working.committed_versions[child_id]
        updated = update_version(current)
        working.committed_versions[child_id] = updated
        working.identity_index.update_version(
            child_id,
            free_symbol_refs=updated.free_symbol_refs,
            source_version_ids=updated.source_version_ids,
        )

    for index, result in enumerate(prior_results):
        updated_versions = tuple(
            update_version(item) for item in result.committed_versions
        )
        updated_writes = tuple(
            update_write(item) for item in result.state_writes
        )
        if (
            updated_versions != result.committed_versions
            or updated_writes != result.state_writes
        ):
            prior_results[index] = replace(
                result,
                committed_versions=updated_versions,
                state_writes=updated_writes,
            )

    edges_by_signature = {item.probe_signature: item for item in edges}
    for payload in probe_results:
        edge = edges_by_signature.get(str(payload.get("probe_signature")))
        if edge is None:
            continue
        payload["lineage_committed"] = True
        payload["lineage_root_version_id"] = (
            edge.root_version_id.to_payload()
        )
        payload["latest_state_authority"] = {
            "scope_id": next(
                probe.descendant_scope_id
                for probe in reconciliation.state_runtime_equivalence_probes
                if stable_hash(probe.to_payload()) == edge.probe_signature
            ),
            "version_id": edge.child_version_id.to_payload(),
        }

    return (
        tuple(update_write(item) for item in current_writes),
        tuple(update_version(item) for item in current_versions),
    )


def _runtime_refinement_substitutions(
    ancestor: Any,
    descendant: Any,
) -> dict[sp.Symbol, Any]:
    ancestor_symbols = _symbolic_value_free_symbols(ancestor)
    descendant_symbols = _symbolic_value_free_symbols(descendant)
    solve_symbols = tuple(
        sorted(ancestor_symbols - descendant_symbols, key=str)
    )
    if not solve_symbols:
        return {}
    equations = _symbolic_value_equations(ancestor, descendant)
    if equations is None or not equations:
        return {}
    try:
        raw_solutions = sp.solve(
            equations,
            solve_symbols,
            dict=True,
        )
    except (NotImplementedError, TypeError, ValueError):
        return {}
    valid: list[dict[sp.Symbol, Any]] = []
    for solution in raw_solutions:
        if not all(symbol in solution for symbol in solve_symbols):
            continue
        if any(
            _symbolic_value_free_symbols(value) - descendant_symbols
            for value in solution.values()
        ):
            continue
        substituted = _substitute_symbolic_value(ancestor, solution)
        if _symbolic_values_equivalent(substituted, descendant):
            valid.append(dict(solution))
    return valid[0] if len(valid) == 1 else {}


def _symbolic_value_free_symbols(value: Any) -> frozenset[sp.Symbol]:
    if isinstance(value, Mapping):
        return frozenset(
            symbol
            for item in value.values()
            for symbol in _symbolic_value_free_symbols(item)
        )
    if isinstance(value, (tuple, list)):
        return frozenset(
            symbol
            for item in value
            for symbol in _symbolic_value_free_symbols(item)
        )
    try:
        return frozenset(sp.sympify(value).free_symbols)
    except (TypeError, ValueError, sp.SympifyError):
        return frozenset()


def _symbolic_value_equations(
    left: Any,
    right: Any,
) -> tuple[sp.Expr, ...] | None:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            return None
        result: list[sp.Expr] = []
        for key in sorted(left, key=str):
            equations = _symbolic_value_equations(left[key], right[key])
            if equations is None:
                return None
            result.extend(equations)
        return tuple(result)
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        if len(left) != len(right):
            return None
        result = []
        for left_item, right_item in zip(left, right, strict=True):
            equations = _symbolic_value_equations(left_item, right_item)
            if equations is None:
                return None
            result.extend(equations)
        return tuple(result)
    try:
        return (sp.together(sp.sympify(left) - sp.sympify(right)),)
    except (TypeError, ValueError, sp.SympifyError):
        return None


def _substitute_symbolic_value(
    value: Any,
    substitutions: Mapping[sp.Symbol, Any],
) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _substitute_symbolic_value(item, substitutions)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            _substitute_symbolic_value(item, substitutions)
            for item in value
        )
    if isinstance(value, list):
        return [
            _substitute_symbolic_value(item, substitutions)
            for item in value
        ]
    try:
        return sp.sympify(value).subs(substitutions)
    except (TypeError, ValueError, sp.SympifyError):
        return value


def _compare_provisional_runtime_state(
    *,
    call_id: str,
    writes: Sequence[StateWriteProvenance],
    runtime_values: Mapping[StateVersionId, TypedValue],
    reconciliation: FunctionalPlanReconciliationResult,
    working: WorkingPlannerState,
    branch: RuntimeContext,
    object_registry: MathObjectRegistry,
    runtime_result_values: Mapping[tuple[str, str], TypedValue],
    restored_call_ids: frozenset[str] = frozenset(),
) -> tuple[
    FunctionalRuntimeEquivalentCallAlias | None,
    PlannerRetryIssue | None,
    tuple[dict[str, Any], ...],
]:
    """Resolve possible duplicate writers using actual typed runtime values.

    Static allocation only identifies a candidate.  Equal values reuse the
    existing version, a runtime-proven dependency refinement commits the new
    version, and every other result is rejected before the branch is exposed.
    """

    probe_results, probe_issue = _compare_scope_create_runtime_probes(
        call_id=call_id,
        writes=writes,
        runtime_values=runtime_values,
        reconciliation=reconciliation,
        working=working,
        branch=branch,
        object_registry=object_registry,
        runtime_result_values=runtime_result_values,
        restored_call_ids=restored_call_ids,
    )
    if probe_issue is not None:
        return None, probe_issue, probe_results
    if not writes:
        return None, None, probe_results
    calls = {item.call_id: item for item in reconciliation.calls}
    current = calls.get(call_id)
    if current is None:
        return None, None, probe_results
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
            return None, None, probe_results
        allocation = allocations.get(write.return_name)
        if allocation is None:
            return None, None, probe_results
        if write.allocation_action == "reuse":
            existing_version_id = write.selected_version_id
            producer_id = write.canonical_producer_call_id or call_id
        elif (
            write.allocation_action == "transition"
            and allocation.allocation_reason_code
            in {
                "runtime_state_equivalence_probe",
                "dependency_refines_visible_state",
            }
            and write.previous_version_id is not None
        ):
            existing_version_id = write.previous_version_id
            producer_id = allocation.previous_write_step_id or call_id
        else:
            return None, None, probe_results
        rows.append(
            (write, allocation, existing_version_id, producer_id)
        )

    producer_ids = {item[3] for item in rows}
    if len(producer_ids) != 1:
        return (
            None,
            _issue(
                call_id,
                "planner.runtime_state_equivalence_conflict",
                "provisional typed writes do not identify one prior producer",
                details={
                    "canonical_producer_call_ids": sorted(producer_ids)
                },
            ),
            probe_results,
        )
    producer_id = next(iter(producer_ids))
    source_state_reuse = producer_id == call_id
    if not source_state_reuse and (
        producer_id in working.call_states
        and working.call_states[producer_id].status != "verified"
    ):
        return (
            None,
            _issue(
                call_id,
                "planner.runtime_state_equivalence_conflict",
                "reused typed state was not produced by a verified prior call",
                details={"canonical_producer_call_id": producer_id},
            ),
            probe_results,
        )

    producer = calls.get(producer_id)
    if producer is None and not source_state_reuse:
        return (
            None,
            _issue(
                call_id,
                "planner.runtime_state_equivalence_conflict",
                "canonical producer is absent from the reconciled plan",
                details={"canonical_producer_call_id": producer_id},
            ),
            probe_results,
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
                consumer_scope_id = write.valid_scope_id or write.scope_id
                existing_symbols = _runtime_value_symbol_object_ids(
                    existing,
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
                candidate_symbols = _runtime_value_symbol_object_ids(
                    candidate,
                    runtime_context=branch,
                    object_registry=object_registry,
                    declared_runtime_symbols=declared,
                )
                supplemental_parameter_values = (
                    _visible_runtime_scalar_assignments(
                        consumer_scope_id=consumer_scope_id,
                        current_call_id=call_id,
                        runtime_result_values=runtime_result_values,
                        reconciliation=reconciliation,
                        working=working,
                        runtime_context=branch,
                        object_registry=object_registry,
                        declared_runtime_symbols=declared,
                    )
                )
                materialized_existing = _materialize_runtime_parameter_closure(
                    existing,
                    consumer_scope_id=consumer_scope_id,
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
                    supplemental_parameter_values=supplemental_parameter_values,
                )
                materialized_candidate = _materialize_runtime_parameter_closure(
                    candidate,
                    consumer_scope_id=consumer_scope_id,
                    working=working,
                    runtime_context=branch,
                    object_registry=object_registry,
                    declared_runtime_symbols=declared,
                    supplemental_parameter_values=supplemental_parameter_values,
                )
                materialized_equivalent = _symbolic_values_equivalent(
                    materialized_existing.runtime_value.value,
                    materialized_candidate.runtime_value.value,
                )
                strictly_closes_symbols = (
                    candidate_symbols < existing_symbols
                )
                if materialized_equivalent:
                    if strictly_closes_symbols and not source_state_reuse:
                        comparison = "dependency_refinement"
                        refinement_seen = True
                    else:
                        comparison = "equivalent_after_parameter_closure"
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
                    "existing_value": _runtime_equivalence_value_payload(
                        existing.value if existing is not None else None
                    ),
                    "candidate_value": _runtime_equivalence_value_payload(
                        candidate.value if candidate is not None else None
                    ),
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
        return (
            None,
            _issue(
                call_id,
                "planner.runtime_state_equivalence_conflict",
                (
                    "a possible duplicate call produced a different typed "
                    "runtime state"
                ),
                details={
                    "canonical_producer_call_id": producer_id,
                    "comparisons": conflicts,
                },
            ),
            probe_results,
        )
    if refinement_seen:
        return None, None, probe_results
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
        probe_results,
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


def _visible_runtime_scalar_assignments(
    *,
    consumer_scope_id: str,
    current_call_id: str,
    runtime_result_values: Mapping[tuple[str, str], TypedValue],
    reconciliation: FunctionalPlanReconciliationResult,
    working: WorkingPlannerState,
    runtime_context: RuntimeContext,
    object_registry: MathObjectRegistry,
    declared_runtime_symbols: Mapping[sp.Symbol, MathObjectId],
) -> dict[MathObjectId, Any]:
    """Collect the closest verified scalar assignments for structural closure.

    Some methods publish a value-only aggregate, such as ``Coefficients``,
    instead of allocating one ``ParameterValue`` state per Symbol. Those values
    are still verified runtime facts and must close later Point/Expression
    states before equivalence is decided. Scope visibility and execution order
    select the authoritative assignment; sibling results never participate.
    """

    calls = {item.call_id: item for item in reconciliation.calls}
    placements = {
        item.canonical_call_id: item.execution_scope_id
        for item in reconciliation.call_placements
    }
    call_order = {
        item.call_id: index for index, item in enumerate(reconciliation.calls)
    }
    ancestors = working.identity_index.visibility.registry.ancestor_scopes(
        consumer_scope_id
    )
    scope_rank = {
        scope_id: index for index, scope_id in enumerate(ancestors)
    }
    candidates: dict[
        MathObjectId,
        tuple[tuple[int, int], Any, str],
    ] = {}
    for (producer_call_id, _output_key), typed in runtime_result_values.items():
        if typed.type != "Coefficients" or not isinstance(typed.value, Mapping):
            continue
        call = calls.get(producer_call_id)
        if call is None:
            continue
        if producer_call_id != current_call_id:
            state = working.call_states.get(producer_call_id)
            if state is None or state.status != "verified":
                continue
        producer_scope_id = placements.get(
            producer_call_id,
            call.scope_id,
        )
        if not working.identity_index.visibility.is_visible(
            producer_scope_id,
            consumer_scope_id=consumer_scope_id,
        ):
            continue
        rank = (
            scope_rank.get(producer_scope_id, len(ancestors)),
            -call_order.get(producer_call_id, -1),
        )
        for symbol, value in typed.value.items():
            if not isinstance(symbol, sp.Symbol):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_scalar_assignment_invalid: "
                    f"call={producer_call_id}, key={symbol!r}"
                )
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
            object_id = next(iter(object_ids))
            existing = candidates.get(object_id)
            if existing is None or rank < existing[0]:
                candidates[object_id] = (rank, value, producer_call_id)
                continue
            if rank == existing[0] and not _symbolic_values_equivalent(
                existing[1],
                value,
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_parameter_state_ambiguous: "
                    f"object_id={object_id.to_payload()}, "
                    f"calls={[existing[2], producer_call_id]}"
                )
    return {
        object_id: candidate[1]
        for object_id, candidate in candidates.items()
    }


def _runtime_value_symbol_object_ids(
    runtime_value: TypedValue,
    *,
    runtime_context: RuntimeContext,
    object_registry: MathObjectRegistry,
    declared_runtime_symbols: Mapping[sp.Symbol, MathObjectId],
) -> frozenset[MathObjectId]:
    """Resolve actual runtime free symbols to canonical object identities.

    State-write metadata is an audit projection and may still describe the
    pre-materialized expression. Runtime equivalence must use the values that
    were actually produced, otherwise a valid open-to-closed convergence can
    be rejected solely because stale metadata retained a parameter id.
    """

    result: set[MathObjectId] = set()
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
        result.add(object_ids[0])
    return frozenset(result)


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
        _canonicalize_projected_state_write_versions(
            item,
            resolve_version_id=report.resolve_runtime_version_id,
        )
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
        require_input_read_authority=True,
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
