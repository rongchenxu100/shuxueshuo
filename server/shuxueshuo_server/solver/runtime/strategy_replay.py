"""Deterministic replay pipeline for planner retry state generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.runtime.answer_goal_verifier import (
    AnswerGoalVerificationReport,
    AnswerGoalVerifier,
    FunctionalGoalVerificationContext,
)
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalBindingContext,
    build_functional_runtime_arg_bindings_from_context,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
)
from shuxueshuo_server.solver.runtime.functional_call_memory import (
    FunctionalCallMemory,
    attach_actual_result_refs,
    build_functional_call_memory,
)
from shuxueshuo_server.solver.runtime.functional_repair_feedback import (
    apply_capability_repair_feedback,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
    build_functional_retry_graph_checkpoint,
    expand_retry_dependency_graph_with_versions,
    latest_functional_retry_graph_checkpoint,
    preserve_committed_retry_checkpoint,
    validate_checkpoint_manifest,
    verify_restored_checkpoint,
    verify_restored_runtime_checkpoint,
)
from shuxueshuo_server.solver.runtime.canonical_draft_finalizer import (
    CanonicalDraftFinalizer,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.functional_plan import (
    CallResultRef,
    FunctionalCapabilityCatalog,
    FunctionalPlan,
    FunctionalPlanIssue,
    FunctionalPlanReconciler,
    FunctionalPlanReconciliationResult,
    FunctionalPlanValidationReport,
    FunctionalPlanValidator,
    prepare_functional_plan_raw_response,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_retry import (
    functional_repair_instruction,
    latest_functional_retry_state,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.functional_result_forms import (
    canonicalize_verified_result_forms,
    verify_functional_input_closures,
    verify_functional_result_forms,
)
from shuxueshuo_server.solver.runtime.functional_transaction_shadow import (
    FunctionalTransactionMode,
    FunctionalTransactionShadowObserver,
    FunctionalTransactionShadowReport,
    failed_shadow_report,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalTransactionalAttemptResult,
    FunctionalTransactionalExecutionReport,
    FunctionalTransactionalInterpreter,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    FunctionalSymbolicClosureMode,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
    PlannerStateContextBuilder,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.recipe_compiler import RecipeTrialExecutor
from shuxueshuo_server.solver.runtime.planner_retry_projection import (
    PlannerRetryStateProjector,
)
from shuxueshuo_server.solver.runtime.strategy_draft_merge import (
    merge_previous_accepted_prefix,
    prepare_step_intent_raw_response,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutablePlanResolutionReport,
    PlannerOutputFormat,
    ProjectedFunctionArgBinding,
    ProjectedStateDependency,
    ProjectedStateWrite,
    PlannerRetryState,
    PlannerRetryIssue,
    PlannerRepairAttempt,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationReport,
    StepIntentNormalizationAction,
    StepIntentScope,
    StepIntentValidationReport,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer
from shuxueshuo_server.solver.runtime.strategy_output_types import (
    canonicalize_produced_output_types,
)
from shuxueshuo_server.solver.runtime.state_dependency_graph import (
    drop_dead_pure_function_steps,
)
from shuxueshuo_server.solver.runtime.strategy_repair_feedback import RepairFeedbackBuilder
from shuxueshuo_server.solver.runtime.strategy_repair_guidance import RepairGuidanceResolver
from shuxueshuo_server.solver.runtime.strategy_resolver import StepIntentCandidateResolver
from shuxueshuo_server.solver.runtime.strategy_retry_state import (
    build_planner_retry_state,
    retry_state_from_attempt,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    expand_functional_dependency_graph,
    build_functional_state_dependencies,
    build_functional_state_write_manifest,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    MathObjectRegistry,
    ScopeVisibilityResolver,
    StateIdentityFactory,
    StateIdentityIndex,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.straightening_metadata import (
    canonical_straightening_endpoint_name,
)
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class PlannerRetryReplayResult:
    """Artifacts from one legacy or Functional planner replay."""

    attempt: int
    errors: tuple[str, ...] = ()
    raw_draft: StepIntentDraft | None = None
    validation_report: StepIntentValidationReport | None = None
    normalized_draft: StepIntentDraft | None = None
    normalization_report: StepIntentNormalizationReport | None = None
    finalization_report: dict[str, Any] | None = None
    resolution_report: ExecutablePlanResolutionReport | None = None
    effective_draft: StepIntentDraft | None = None
    diagnostic: StepIntentExecutionDiagnostic | None = None
    goal_verification_issues: tuple[Any, ...] = ()
    goal_verification_report: AnswerGoalVerificationReport | None = None
    retry_state: PlannerRetryState | None = None
    output: Any | None = None
    planner_state_context: PlannerStateContext | None = None
    functional_plan: FunctionalPlan | None = None
    functional_validation_report: FunctionalPlanValidationReport | None = None
    functional_reconciliation: FunctionalPlanReconciliationResult | None = None
    transactional_shadow_report: (
        FunctionalTransactionShadowReport | None
    ) = None
    transactional_execution_report: (
        FunctionalTransactionalExecutionReport | None
    ) = None
    transactional_attempt_result: (
        FunctionalTransactionalAttemptResult | None
    ) = None
    state_observation_authority: Literal[
        "legacy",
        "transactional",
    ] = "legacy"

    def to_payload(self) -> dict[str, Any]:
        """转成 debug JSON。"""
        return {
            "attempt": self.attempt,
            "errors": list(self.errors),
            "raw_draft": self.raw_draft.to_payload() if self.raw_draft else None,
            "validation_report": (
                self.validation_report.to_payload()
                if self.validation_report is not None
                else None
            ),
            "normalized_draft": (
                self.normalized_draft.to_payload()
                if self.normalized_draft is not None
                else None
            ),
            "normalization_report": (
                self.normalization_report.to_payload()
                if self.normalization_report is not None
                else None
            ),
            "finalization_report": self.finalization_report,
            "resolution_report": (
                self.resolution_report.to_payload()
                if self.resolution_report is not None
                else None
            ),
            "effective_draft": (
                self.effective_draft.to_payload()
                if self.effective_draft is not None
                else None
            ),
            "diagnostic": (
                self.diagnostic.to_payload()
                if self.diagnostic is not None
                else None
            ),
            "goal_verification_issues": [
                issue.to_payload()
                for issue in self.goal_verification_issues
            ],
            "goal_verification_report": (
                self.goal_verification_report.to_payload()
                if self.goal_verification_report is not None
                else None
            ),
            "retry_state": (
                self.retry_state.to_payload()
                if self.retry_state is not None
                else None
            ),
            "output_ok": self.output is not None,
            "planner_state_context": (
                self.planner_state_context.to_payload()
                if self.planner_state_context is not None
                else None
            ),
            "functional_plan": (
                self.functional_plan.to_payload()
                if self.functional_plan is not None
                else None
            ),
            "functional_validation_report": (
                self.functional_validation_report.to_payload()
                if self.functional_validation_report is not None
                else None
            ),
            "functional_reconciliation": (
                self.functional_reconciliation.to_payload()
                if self.functional_reconciliation is not None
                else None
            ),
            "transactional_shadow_report": (
                self.transactional_shadow_report.to_payload()
                if self.transactional_shadow_report is not None
                else None
            ),
            "transactional_execution_report": (
                self.transactional_execution_report.to_payload()
                if self.transactional_execution_report is not None
                else None
            ),
            "transactional_attempt_result": (
                self.transactional_attempt_result.to_payload()
                if self.transactional_attempt_result is not None
                else None
            ),
            "state_observation_authority": (
                self.state_observation_authority
            ),
        }


@dataclass(frozen=True)
class _FunctionalProjectionRecovery:
    """Verified remainder of a Functional graph after bridge validation fails."""

    issues: tuple[FunctionalPlanIssue, ...]
    verified_call_ids: frozenset[str] = frozenset()
    blocked_call_ids: tuple[str, ...] = ()
    validation_reports: tuple[dict[str, Any], ...] = ()
    runtime_results: tuple[Any, ...] = ()
    state_write_provenance: tuple[Any, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "verified_call_ids": sorted(self.verified_call_ids),
            "blocked_call_ids": list(self.blocked_call_ids),
            "validation_reports": [dict(item) for item in self.validation_reports],
            "runtime_results": [
                item.to_payload() for item in self.runtime_results
            ],
            "state_write_provenance": [
                item.to_payload() for item in self.state_write_provenance
            ],
        }


@dataclass(frozen=True)
class _FunctionalGraphVerification:
    verified_call_ids: frozenset[str] = frozenset()
    runtime_results: tuple[Any, ...] = ()
    state_write_provenance: tuple[Any, ...] = ()


class PlannerRetryReplayService:
    """Replay legacy StepIntent or authoritative Functional candidates."""

    def __init__(
        self,
        *,
        functional_transaction_mode: FunctionalTransactionMode = (
            "context_authoritative"
        ),
        functional_symbolic_closure_mode: FunctionalSymbolicClosureMode = (
            "disabled"
        ),
    ) -> None:
        if functional_transaction_mode not in {
            "shadow",
            "context_authoritative",
        }:
            raise ValueError(
                "unsupported Functional transaction mode: "
                f"{functional_transaction_mode}"
            )
        self._functional_transaction_mode = functional_transaction_mode
        self._functional_symbolic_closure_mode = (
            functional_symbolic_closure_mode
        )

    def replay_functional_raw_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        errors: tuple[str, ...] = (),
        problem_payload: dict[str, Any] | None = None,
    ) -> PlannerRetryReplayResult:
        """Parse and replay a strict FunctionalPlan response."""
        planner_state_context = _initial_planner_state_context(
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
            attempt=attempt,
            previous_attempts=inputs.previous_errors,
        )
        retry_checkpoint = latest_functional_retry_graph_checkpoint(
            inputs.previous_errors
        )
        if retry_checkpoint is not None:
            validate_checkpoint_manifest(
                retry_checkpoint,
                context=planner_state_context,
            )
        raw_response = prepare_functional_plan_raw_response(
            raw_response,
            previous_attempts=inputs.previous_errors,
            handle_registry=handle_registry,
            shareable_capability_ids=frozenset(
                capability_id
                for capability_id, capability in (
                    FunctionalCapabilityCatalog.from_family_spec(
                        inputs.family_spec,
                        inputs.method_specs,
                    ).items.items()
                )
                if capability.is_pure
            ),
        )
        plan, report = FunctionalPlanValidator().validate_json_with_report(
            raw_response,
            handle_registry=handle_registry,
            question_goals=inputs.question_goals,
        )
        if plan is None:
            retry_state = _functional_validation_retry_state(
                attempt=attempt,
                issues=report.issues,
                partially_parsed_payload=report.partially_parsed_payload,
                errors=errors,
                previous_attempts=inputs.previous_errors,
                validation_report=report,
            )
            replay = PlannerRetryReplayResult(
                attempt=attempt,
                errors=errors or tuple(issue.message for issue in report.issues),
                retry_state=retry_state,
                functional_validation_report=report,
            )
            return _with_planner_state_context(
                replay,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
            )
        return self.replay_functional_plan(
            plan,
            inputs=inputs,
            handle_registry=handle_registry,
            context=context,
            attempt=attempt,
            errors=errors,
            problem_payload=problem_payload,
            planner_state_context=planner_state_context,
            validation_report=report,
            retry_checkpoint=retry_checkpoint,
        )

    def replay_functional_plan(
        self,
        plan: FunctionalPlan,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        errors: tuple[str, ...] = (),
        problem_payload: dict[str, Any] | None = None,
        planner_state_context: PlannerStateContext | None = None,
        validation_report: FunctionalPlanValidationReport | None = None,
        retry_checkpoint: FunctionalRetryGraphCheckpoint | None = None,
    ) -> PlannerRetryReplayResult:
        """Reconcile and execute a FunctionalPlan through typed authority."""
        planner_state_context = planner_state_context or _initial_planner_state_context(
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
            attempt=attempt,
            previous_attempts=inputs.previous_errors,
        )
        functional_catalog = FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
        reconciliation = FunctionalPlanReconciler().reconcile(
            plan,
            planner_state_context=planner_state_context,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            question_goals=inputs.question_goals,
            pinned_canonical_call_ids=(
                retry_checkpoint.committed_call_ids
                if retry_checkpoint is not None
                else ()
            ),
            pinned_execution_scopes=(
                retry_checkpoint.pinned_execution_scopes
                if retry_checkpoint is not None
                else {}
            ),
            pinned_return_scopes=(
                retry_checkpoint.pinned_return_scopes
                if retry_checkpoint is not None
                else {}
            ),
            pinned_resolver_arg_names=(
                {
                    item.canonical_call_id: item.resolver_bound_arg_names
                    for item in retry_checkpoint.committed_calls
                }
                if retry_checkpoint is not None
                else {}
            ),
        )
        # A retryable reconciliation issue can leave ``calls`` as a partial
        # graph. Auditing committed versions against that partial view masks
        # the actionable issue as checkpoint drift. Checkpoint structure
        # remains fail-loud; defer only the graph comparison until complete.
        if retry_checkpoint is not None:
            verify_restored_checkpoint(
                retry_checkpoint,
                reconciliation=reconciliation,
                handle_registry=handle_registry,
                verify_reconciled_graph=reconciliation.ok,
            )
        authoritative_output_types = {
            handle: output.runtime_type
            for call in reconciliation.calls
            for output in call.returns
            for handle in (
                output.handle,
                *((output.state_handle,) if output.state_handle is not None else ()),
            )
        }
        state_write_manifest = _functional_state_write_manifest(
            reconciliation
        )
        state_dependencies = build_functional_state_dependencies(
            reconciliation.effective_plan,
            reconciliation.calls,
            catalog=functional_catalog,
        )
        reconciliation = replace(
            reconciliation,
            dependency_graph=expand_functional_dependency_graph(
                reconciliation.dependency_graph,
                projected_state_writes=state_write_manifest,
                projected_state_dependencies=state_dependencies,
            ),
        )
        functional_retry = (
            _functional_retry_state(
                attempt=attempt,
                issues=reconciliation.issues,
                baseline_candidate=reconciliation.plan.to_payload(),
                errors=errors,
                replay_report=reconciliation.to_payload(),
                repair_call_ids=_root_repair_call_ids(reconciliation),
            )
            if reconciliation.issues
            else None
        )
        if functional_retry is not None:
            functional_retry = _functional_feedback_retry_state(
                functional_retry,
                plan=reconciliation.plan,
                reconciliation=reconciliation,
                catalog=functional_catalog,
                semantic_index=FunctionalSemanticIndex.from_context(
                    planner_state_context,
                    handle_registry=handle_registry,
                ),
            )
        replay = PlannerRetryReplayResult(
            attempt=attempt,
            errors=(
                errors
                or tuple(issue.message for issue in reconciliation.issues)
            ),
            retry_state=functional_retry,
            functional_plan=reconciliation.plan,
            functional_validation_report=validation_report,
            functional_reconciliation=reconciliation,
        )
        return self._finalize_functional_replay(
            replay,
            raw_plan=plan,
            parent_context=planner_state_context,
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
            runtime_context=context,
        )

    def _finalize_functional_replay(
        self,
        replay: PlannerRetryReplayResult,
        *,
        raw_plan: FunctionalPlan,
        parent_context: PlannerStateContext,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        problem_payload: dict[str, Any] | None,
        runtime_context: Any,
    ) -> PlannerRetryReplayResult:
        if (
            self._functional_transaction_mode
            in {"shadow", "context_authoritative"}
            and replay.functional_reconciliation is not None
        ):
            try:
                report = FunctionalTransactionShadowObserver().observe(
                    raw_plan=raw_plan,
                    reconciliation=replay.functional_reconciliation,
                    diagnostic=replay.diagnostic,
                    retry_state=replay.retry_state,
                    goal_verification_report=(
                        replay.goal_verification_report
                    ),
                    parent_context=parent_context,
                    handle_registry=handle_registry,
                )
            except Exception as exc:
                report = failed_shadow_report(
                    raw_plan,
                    message=f"{type(exc).__name__}: {exc}",
                )
            replay = replace(
                replay,
                transactional_shadow_report=report,
            )
        if (
            self._functional_transaction_mode == "context_authoritative"
            and replay.functional_reconciliation is not None
            and not replay.functional_reconciliation.issues
        ):
            context_problem_payload, _warnings = _problem_payload_for_context(
                inputs,
                problem_payload,
            )
            try:
                transactional_attempt = (
                    FunctionalTransactionalInterpreter(
                        symbolic_closure_mode=(
                            self._functional_symbolic_closure_mode
                        ),
                    ).execute_attempt(
                        raw_plan=raw_plan,
                        reconciliation=replay.functional_reconciliation,
                        runtime_context=runtime_context,
                        parent_context=parent_context,
                        inputs=inputs,
                        handle_registry=handle_registry,
                        problem_payload=context_problem_payload,
                    )
                )
            except Exception as exc:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: "
                    "planner.transactional_attempt_failed: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            else:
                execution_report = (
                    transactional_attempt.execution_report
                )
            replay = replace(
                replay,
                transactional_execution_report=execution_report,
                transactional_attempt_result=transactional_attempt,
            )
            if transactional_attempt is not None:
                retry_state = _transactional_functional_retry_state(
                    replay,
                    attempt_result=transactional_attempt,
                    parent_context=parent_context,
                    inputs=inputs,
                    handle_registry=handle_registry,
                )
                replay = replace(
                    replay,
                    diagnostic=transactional_attempt.diagnostic,
                    goal_verification_report=(
                        transactional_attempt.goal_report
                    ),
                    goal_verification_issues=(
                        transactional_attempt.goal_report.issues
                    ),
                    retry_state=retry_state,
                    output=transactional_attempt.compiled_output,
                    effective_draft=None,
                    state_observation_authority="transactional",
                )
        return _with_planner_state_context(
            replay,
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
        )

    def replay_raw_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        errors: tuple[str, ...] = (),
        merge_previous_prefix: bool = True,
        problem_payload: dict[str, Any] | None = None,
    ) -> PlannerRetryReplayResult:
        """从 LLM raw JSON 开始 replay。"""
        raw_response = prepare_step_intent_raw_response(
            raw_response,
            previous_attempts=inputs.previous_errors,
        )
        planner_state_context = _initial_planner_state_context(
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
            attempt=attempt,
            previous_attempts=inputs.previous_errors,
        )
        draft, validation_report = StepIntentValidator().validate_json_with_report(
            raw_response,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
            planner_state_context=planner_state_context,
        )
        if draft is None:
            replay_errors = errors or tuple(validation_report.errors)
            retry_state = build_planner_retry_state(
                attempt=attempt,
                errors=replay_errors,
                validation_report=validation_report,
                handle_registry=handle_registry,
            )
            replay = PlannerRetryReplayResult(
                attempt=attempt,
                errors=replay_errors,
                validation_report=validation_report,
                retry_state=retry_state,
            )
            return _with_planner_state_context(
                replay,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
            )
        return self.replay_draft(
            draft,
            inputs=inputs,
            handle_registry=handle_registry,
            context=context,
            attempt=attempt,
            errors=errors,
            validation_report=validation_report,
            merge_previous_prefix=merge_previous_prefix,
            problem_payload=problem_payload,
        )

    def replay_draft(
        self,
        draft: StepIntentDraft,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        errors: tuple[str, ...] = (),
        validation_report: StepIntentValidationReport | None = None,
        merge_previous_prefix: bool = True,
        problem_payload: dict[str, Any] | None = None,
        partial_candidate: bool = False,
        authoritative_output_types: dict[str, str] | None = None,
        allow_shared_derivation_scopes: bool = False,
        candidate_format: PlannerOutputFormat = "step_intent",
        projected_state_writes: tuple[ProjectedStateWrite, ...] = (),
        projected_state_dependencies: tuple[ProjectedStateDependency, ...] = (),
        projected_function_arg_bindings: tuple[
            ProjectedFunctionArgBinding, ...
        ] = (),
        known_state_versions: tuple[IndexedStateVersion, ...] = (),
        functional_plan: FunctionalPlan | None = None,
        functional_reconciliation: (
            FunctionalPlanReconciliationResult | None
        ) = None,
    ) -> PlannerRetryReplayResult:
        """从已通过 validation 的 draft 开始 replay。"""
        raw_draft = draft
        replay_draft = (
            merge_previous_accepted_prefix(
                draft,
                previous_attempts=inputs.previous_errors,
                handle_registry=handle_registry,
                inputs=inputs,
            )
            if merge_previous_prefix
            else draft
        )
        try:
            if candidate_format == "functional_plan":
                # Functional reconciliation has already established a typed
                # call graph. Legacy StepIntent folds/drops/backfills may
                # change that topology and sever validated CallResultRef
                # dependencies, so the compatibility projection only receives
                # type canonicalization and final handle validation below.
                normalized = replay_draft
                normalization_report = StepIntentNormalizationReport(
                    warnings=("functional_call_graph_topology_preserved",),
                )
            else:
                normalized, normalization_report = StepIntentNormalizer().normalize(
                    replay_draft,
                    family_spec=inputs.family_spec,
                    question_goals=inputs.question_goals,
                    handle_registry=handle_registry,
                )
            normalized, output_type_actions = canonicalize_produced_output_types(
                normalized,
                family_spec=inputs.family_spec,
                method_specs=inputs.method_specs,
                handle_registry=handle_registry,
                authoritative_types_by_handle=authoritative_output_types,
            )
            normalization_report = _append_normalization_actions(
                normalization_report,
                output_type_actions,
            )
            if candidate_format != "functional_plan":
                normalized, dead_step_actions = drop_dead_pure_function_steps(
                    normalized,
                    family_spec=inputs.family_spec,
                    method_specs=inputs.method_specs,
                )
                normalization_report = _append_normalization_actions(
                    normalization_report,
                    dead_step_actions,
                )
            normalized, finalization_report = CanonicalDraftFinalizer().finalize(
                normalized,
                family_spec=inputs.family_spec,
                question_goals=inputs.question_goals,
                handle_registry=handle_registry,
                allow_shared_derivation_scopes=allow_shared_derivation_scopes,
                projected_state_writes=projected_state_writes,
                projected_state_dependencies=projected_state_dependencies,
                known_state_versions=known_state_versions,
            )
        except Exception as exc:
            if "planner_configuration_error" in str(exc):
                raise
            replay_errors = errors or (str(exc),)
            retry_state = build_planner_retry_state(
                attempt=attempt,
                errors=replay_errors,
                normalized_draft=replay_draft,
                validation_report=validation_report,
                normalization_errors=(str(exc),),
                handle_registry=handle_registry,
            )
            retry_state = _retry_state_with_candidate_format(
                retry_state,
                candidate_format,
            )
            replay = PlannerRetryReplayResult(
                attempt=attempt,
                errors=replay_errors,
                raw_draft=raw_draft,
                validation_report=validation_report,
                normalized_draft=replay_draft,
                retry_state=retry_state,
            )
            return _with_planner_state_context(
                replay,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
            )

        resolution_report = StepIntentCandidateResolver().resolve(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
        )
        output, diagnostic, effective_draft = RecipeTrialExecutor().diagnose(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=context,
            question_goals=inputs.question_goals,
            allow_shared_derivation_scopes=allow_shared_derivation_scopes,
            preserve_call_graph=(candidate_format == "functional_plan"),
            projected_state_writes=projected_state_writes,
            projected_state_dependencies=projected_state_dependencies,
            projected_function_arg_bindings=projected_function_arg_bindings,
            known_state_versions=known_state_versions,
            functional_consumer_identity_mode=(
                "authoritative"
                if candidate_format == "functional_plan"
                else None
            ),
        )
        blocker = diagnostic.first_blocker
        if blocker is not None and not blocker.retryable:
            raise StrategyDraftValidationError(
                "planner_configuration_error: "
                f"code={blocker.code}, step={blocker.step_id}, "
                f"message={blocker.message}"
            )
        context_problem_payload, _context_warnings = _problem_payload_for_context(
            inputs,
            problem_payload,
        )
        functional_goal_context = None
        if (
            candidate_format == "functional_plan"
            and not partial_candidate
            and functional_reconciliation is not None
        ):
            state_read_index = FunctionalStateReadIndex.from_sources(
                handle_registry=handle_registry,
                mode="authoritative",
                projected_state_writes=projected_state_writes,
                projected_state_dependencies=(
                    projected_state_dependencies
                ),
                state_write_provenance=(
                    diagnostic.state_write_provenance
                ),
                known_state_versions=known_state_versions,
            )
            logical_graph = None
            answer_version_ids = {
                item.produced_handle: item.selected_version_id
                for item in projected_state_writes
                if item.produced_handle.startswith("answer:")
                and item.selected_version_id is not None
            }
            if functional_plan is not None:
                graph_result = LogicalFunctionalGraphBuilder().build(
                    functional_plan,
                    functional_reconciliation,
                    handle_registry=handle_registry,
                )
                if not graph_result.issues:
                    logical_graph = graph_result.graph
                resolved_calls = {
                    item.call_id: item
                    for item in functional_reconciliation.calls
                }
                for answer_binding in (
                    logical_graph.answer_bindings
                    if logical_graph is not None
                    else ()
                ):
                    resolved = resolved_calls.get(
                        answer_binding.producer_call_id
                    )
                    returned = next(
                        (
                            item
                            for item in (
                                resolved.returns if resolved is not None else ()
                            )
                            if item.return_name
                            == answer_binding.return_name
                        ),
                        None,
                    )
                    if (
                        returned is not None
                        and returned.selected_version_id is not None
                    ):
                        answer_version_ids[
                            answer_binding.answer_handle
                        ] = returned.selected_version_id
            resolved_calls = {
                item.call_id: item
                for item in functional_reconciliation.calls
            }
            for call in functional_reconciliation.effective_plan.calls:
                resolved = resolved_calls.get(call.call_id)
                if resolved is None:
                    continue
                for return_name, semantic_ref in call.return_bindings.items():
                    if semantic_ref.kind != "answer":
                        continue
                    returned = next(
                        (
                            item
                            for item in resolved.returns
                            if item.return_name == return_name
                        ),
                        None,
                    )
                    if (
                        returned is not None
                        and returned.selected_version_id is not None
                    ):
                        answer_version_ids[
                            f"answer:{semantic_ref.ref}"
                        ] = returned.selected_version_id
            functional_goal_context = FunctionalGoalVerificationContext(
                logical_graph=logical_graph,
                state_read_index=state_read_index,
                runtime_writes_by_version={
                    item.selected_version_id: item
                    for item in diagnostic.state_write_provenance
                    if item.selected_version_id is not None
                },
                answer_version_ids=answer_version_ids,
                verified_call_ids=frozenset(
                    item.step_id for item in diagnostic.accepted_prefix
                ),
            )
        goal_verification_report = AnswerGoalVerifier().verify_report(
            effective_draft,
            problem_payload=context_problem_payload,
            handle_registry=handle_registry,
            diagnostic=diagnostic,
            family_spec=inputs.family_spec,
            functional_context=functional_goal_context,
        )
        if functional_goal_context is not None:
            diagnostic = replace(
                diagnostic,
                runtime_consumer_decisions=tuple(
                    (
                        *diagnostic.runtime_consumer_decisions,
                        *(
                            item.to_payload()
                            for item in functional_goal_context
                            .state_read_index.decisions
                        ),
                    )
                ),
                runtime_consumer_mismatches=tuple(
                    (
                        *diagnostic.runtime_consumer_mismatches,
                        *functional_goal_context.state_read_index.mismatches,
                    )
                ),
                legacy_runtime_identity_fallback_count=(
                    diagnostic.legacy_runtime_identity_fallback_count
                    + functional_goal_context
                    .state_read_index.legacy_identity_fallback_count
                ),
            )
        goal_verification_issues = (
            ()
            if partial_candidate
            else goal_verification_report.issues
        )
        retry_state = build_planner_retry_state(
            attempt=attempt,
            errors=errors,
            effective_draft=effective_draft,
            normalized_draft=normalized,
            validation_report=validation_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
            handle_registry=handle_registry,
            goal_verification_issues=goal_verification_issues,
            guidance_resolver=RepairGuidanceResolver(
                inputs.family_spec,
                inputs.method_specs,
                handle_registry,
            ),
        )
        retry_state = _retry_state_with_candidate_format(
            retry_state,
            candidate_format,
        )
        replay = PlannerRetryReplayResult(
            attempt=attempt,
            errors=errors,
            raw_draft=raw_draft,
            validation_report=validation_report,
            normalized_draft=normalized,
            normalization_report=normalization_report,
            finalization_report=finalization_report.to_payload(),
            resolution_report=resolution_report,
            effective_draft=effective_draft,
            diagnostic=diagnostic,
            goal_verification_issues=goal_verification_issues,
            goal_verification_report=goal_verification_report,
            retry_state=retry_state,
            output=None if goal_verification_issues else output,
        )
        return _with_planner_state_context(
            replay,
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
        )

    def replay_from_artifacts(
        self,
        *,
        attempt: int,
        errors: tuple[str, ...],
        raw_draft: StepIntentDraft | None = None,
        validation_report: StepIntentValidationReport | None = None,
        normalized_draft: StepIntentDraft | None = None,
        normalization_report: StepIntentNormalizationReport | None = None,
        finalization_report: dict[str, Any] | None = None,
        resolution_report: ExecutablePlanResolutionReport | None = None,
        effective_draft: StepIntentDraft | None = None,
        diagnostic: StepIntentExecutionDiagnostic | None = None,
        goal_verification_issues: tuple[Any, ...] = (),
        output: Any | None = None,
        planner_state_context: PlannerStateContext | None = None,
        inputs: PlannerInputs | None = None,
        handle_registry: CanonicalHandleRegistry | None = None,
        problem_payload: dict[str, Any] | None = None,
    ) -> PlannerRetryReplayResult:
        """从已存在 artifacts 生成同一形态 replay result。"""
        retry_state = build_planner_retry_state(
            attempt=attempt,
            errors=errors,
            effective_draft=effective_draft,
            normalized_draft=normalized_draft,
            validation_report=validation_report,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            diagnostic=diagnostic,
            goal_verification_issues=goal_verification_issues,
        )
        replay = PlannerRetryReplayResult(
            attempt=attempt,
            errors=errors,
            raw_draft=raw_draft,
            validation_report=validation_report,
            normalized_draft=normalized_draft,
            normalization_report=normalization_report,
            finalization_report=finalization_report,
            resolution_report=resolution_report,
            effective_draft=effective_draft,
            diagnostic=diagnostic,
            goal_verification_issues=goal_verification_issues,
            retry_state=retry_state,
            output=output,
            planner_state_context=planner_state_context,
        )
        if (
            planner_state_context is None
            and inputs is not None
            and handle_registry is not None
        ):
            return _with_planner_state_context(
                replay,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
            )
        if planner_state_context is not None:
            projected = PlannerRetryStateProjector.from_context(planner_state_context)
            if projected is not None:
                return replace(replay, retry_state=projected)
        return replay


def _functional_state_write_manifest(
    reconciliation: FunctionalPlanReconciliationResult,
) -> tuple[ProjectedStateWrite, ...]:
    """Build the typed write manifest consumed by B3 and execution."""
    return build_functional_state_write_manifest(
        reconciliation.effective_plan,
        reconciliation.calls,
    )


def _functional_state_dependencies(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[ProjectedStateDependency, ...]:
    """Build exact typed dependencies for B3 and execution."""

    return build_functional_state_dependencies(
        reconciliation.effective_plan,
        reconciliation.calls,
        catalog=catalog,
    )


def _functional_known_state_versions(
    context: PlannerStateContext,
    *,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[IndexedStateVersion, ...]:
    registry = MathObjectRegistry.from_sources(
        handle_registry,
        math_objects=context.state.math_objects,
    )
    factory = StateIdentityFactory(registry)
    index = StateIdentityIndex.from_context(
        state_slots=context.state.state_slots,
        factory=factory,
        visibility=ScopeVisibilityResolver(handle_registry),
    )
    return index.all_versions()


def _apply_function_arg_binding_repairs(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> FunctionalPlanReconciliationResult:
    """Write analyzer-selected argument sources back to the canonical plan.

    Constraint analyzers run where typed RuntimeContext values are available.
    Their repair sidecar is the authoritative bridge back to FunctionalPlan;
    replay never reimplements the analyzer's mathematics.
    """

    if diagnostic is None:
        return reconciliation
    resolved_by_id = {item.call_id: item for item in reconciliation.calls}
    updates: dict[str, Any] = {}
    repair_payloads: list[dict[str, Any]] = []
    calls_by_id = {call.call_id: call for call in reconciliation.plan.calls}
    for event in diagnostic.function_binding_events:
        if event.status != "success" or not event.arg_repairs:
            continue
        call = updates.get(event.step_id) or calls_by_id.get(event.step_id)
        resolved = resolved_by_id.get(event.step_id)
        if call is None or resolved is None:
            continue
        args = dict(call.args)
        changed = False
        for repair in event.arg_repairs:
            refs = tuple(args.get(repair.arg_name, ()))
            values = tuple(resolved.resolved_args.get(repair.arg_name, ()))
            if len(refs) != len(values):
                continue
            selected = set(repair.source_handles)
            selected_refs = tuple(
                ref
                for ref, value in zip(refs, values, strict=True)
                if value.handle in selected
            )
            if selected and len(selected_refs) != len(selected):
                continue
            if selected_refs == refs:
                continue
            if selected_refs:
                args[repair.arg_name] = selected_refs
            else:
                args.pop(repair.arg_name, None)
            changed = True
            repair_payloads.append(
                {
                    "call_id": event.step_id,
                    "action": repair.reason,
                    "from": _functional_refs_label(refs),
                    "to": _functional_refs_label(selected_refs),
                }
            )
        if changed:
            updates[event.step_id] = replace(call, args=args)
    if not updates:
        return reconciliation
    normalized_plan = replace(
        reconciliation.plan,
        scopes=tuple(
            replace(
                scope,
                calls=tuple(updates.get(call.call_id, call) for call in scope.calls),
            )
            for scope in reconciliation.plan.scopes
        ),
    )
    elaboration = dict(reconciliation.elaboration or {})
    deterministic_repairs = list(elaboration.get("deterministic_repairs", ()))
    deterministic_repairs.extend(repair_payloads)
    elaboration["deterministic_repairs"] = deterministic_repairs
    elaboration["plan"] = normalized_plan.to_payload()
    return replace(
        reconciliation,
        plan=normalized_plan,
        elaboration=elaboration,
    )


def _functional_refs_label(refs: tuple[Any, ...]) -> str:
    if not refs:
        return "<omitted>"
    return ",".join(
        (
            f"{ref.from_call}.{ref.return_name}"
            if isinstance(ref, CallResultRef)
            else f"{ref.kind}:{ref.ref}"
        )
        for ref in refs
    )


def _functional_runtime_arg_bindings(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[ProjectedFunctionArgBinding, ...]:
    """Build runtime bindings from the authoritative C3 ledger."""
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


def repair_attempt_payload_from_replay(
    replay: PlannerRetryReplayResult,
) -> dict[str, Any] | None:
    """从 replay result 生成 previous_attempts 可携带的 repair context。"""
    diagnostic = replay.diagnostic
    if (
        replay.retry_state is None
        and not replay.errors
        and (diagnostic is None or diagnostic.ok)
    ):
        return None
    effective = replay.effective_draft
    repair_summary = RepairFeedbackBuilder(
        diagnostic=diagnostic,
        errors=replay.errors,
        effective_draft=effective,
    ).build()
    retry_state = replay.retry_state
    is_functional = (
        replay.functional_plan is not None
        or replay.functional_reconciliation is not None
        or (
            retry_state is not None
            and retry_state.candidate_format == "functional_plan"
        )
    )
    repair_instruction = (
        retry_state.repair_instruction
        if retry_state is not None
        else (
            functional_repair_instruction(
                stable_candidate_calls=(),
                repair_call_ids=(),
                issue_count=max(1, len(replay.errors)),
            )
            if is_functional
            else (
                "请根据 errors 修复并重新输出完整 StepIntent JSON。"
                "不要输出 patch。"
            )
        )
    )
    payload = PlannerRepairAttempt(
        attempt=replay.attempt,
        effective_draft=effective.to_payload() if effective is not None else None,
        diagnostic=diagnostic,
        repair_summary=repair_summary,
        planner_retry_state=retry_state,
        repair_instruction=repair_instruction,
        errors=replay.errors,
        candidate_format=(
            "functional_plan" if is_functional else "step_intent"
        ),
    ).to_payload()
    if replay.planner_state_context is not None:
        context = replay.planner_state_context
        payload["planner_state_context_ref"] = {
            "context_id": context.manifest.context_id,
            "parent_context_id": context.manifest.parent_context_id,
            "schema_version": context.manifest.schema_version,
        }
        payload["context_retry_memory"] = context.state.retry_memory.to_payload()
        checkpoint = (
            context.state.retry_memory.functional_retry_graph_checkpoint
        )
        if checkpoint is not None:
            payload["functional_retry_graph_checkpoint"] = dict(checkpoint)
        if retry_state is not None:
            payload["context_derived_retry_state"] = retry_state.to_payload()
    return payload


def transactional_repair_attempt_payload_from_replay(
    replay: PlannerRetryReplayResult,
    *,
    attempt: int,
    errors: tuple[str, ...],
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
    problem_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Reproject an external answer failure from C2 runtime evidence.

    The Orchestrator performs semantic answer comparison after planner
    execution. A failed comparison revokes goal commitment, but the call
    results remain useful provisional evidence. Rebuilding this state through
    legacy replay would lose the transactional version boundary.
    """

    attempt_result = replay.transactional_attempt_result
    if (
        replay.state_observation_authority != "transactional"
        or attempt_result is None
        or not errors
    ):
        return repair_attempt_payload_from_replay(replay)
    parent_context = _initial_planner_state_context(
        inputs=inputs,
        handle_registry=handle_registry,
        problem_payload=problem_payload,
        attempt=attempt,
        previous_attempts=inputs.previous_errors,
    )
    failed_replay = replace(
        replay,
        attempt=attempt,
        errors=errors,
        output=None,
        retry_state=None,
        planner_state_context=None,
    )
    retry_state = _transactional_functional_retry_state(
        failed_replay,
        attempt_result=attempt_result,
        parent_context=parent_context,
        inputs=inputs,
        handle_registry=handle_registry,
    )
    failed_replay = _with_planner_state_context(
        replace(failed_replay, retry_state=retry_state),
        inputs=inputs,
        handle_registry=handle_registry,
        problem_payload=problem_payload,
    )
    return repair_attempt_payload_from_replay(failed_replay)


def _functional_retry_state(
    *,
    attempt: int,
    issues: tuple[Any, ...],
    baseline_candidate: dict[str, Any] | None,
    errors: tuple[str, ...],
    replay_report: dict[str, Any] | None = None,
    repair_call_ids: tuple[str, ...] = (),
) -> PlannerRetryState:
    retry_issues = tuple(
        PlannerRetryIssue(
            layer=issue.layer,
            code=issue.code,
            step_id=issue.call_id,
            scope_id=issue.scope_id,
            repair_target="functional_call",
            preserve_policy="none",
            message=issue.message,
            details=issue.details,
        )
        for issue in issues
    )
    if not retry_issues and errors:
        retry_issues = tuple(
            PlannerRetryIssue(
                layer="functional_reconciliation",
                code="functional.error",
                preserve_policy="none",
                message=error,
            )
            for error in errors
        )
    primary = retry_issues[0] if retry_issues else None
    if not repair_call_ids:
        repair_call_ids = tuple(
            dict.fromkeys(
                issue.step_id for issue in retry_issues if issue.step_id is not None
            )
        )
    repair_suffix_start = (
        {
            "call_id": primary.step_id,
            "step_id": primary.step_id,
            "scope_id": primary.scope_id,
        }
        if primary is not None
        else None
    )
    return PlannerRetryState(
        attempt=attempt,
        baseline_draft=None,
        repair_suffix_start=repair_suffix_start,
        issues=retry_issues,
        preserve_policy="none",
        repair_instruction=functional_repair_instruction(
            stable_candidate_calls=(),
            repair_call_ids=repair_call_ids,
            issue_count=len(retry_issues),
        ),
        replay_depth=primary.layer if primary is not None else None,
        selected_repair_layer=primary.layer if primary is not None else None,
        replay_timeline=(
            {
                "layer": primary.layer if primary is not None else "functional_reconciliation",
                "status": "failed",
            },
        ),
        replay_reports=(
            {"functional_reconciliation": replay_report}
            if replay_report is not None
            else {}
        ),
        candidate_format="functional_plan",
        baseline_candidate=baseline_candidate,
        repair_call_ids=repair_call_ids,
    )


def _functional_validation_retry_state(
    *,
    attempt: int,
    issues: tuple[Any, ...],
    partially_parsed_payload: dict[str, Any] | None,
    errors: tuple[str, ...],
    previous_attempts: list[Any],
    validation_report: FunctionalPlanValidationReport,
) -> PlannerRetryState:
    """Preserve verified graph memory when the new wire payload is invalid."""
    previous = latest_functional_retry_state(previous_attempts)
    previous_baseline = (
        previous.get("baseline_candidate")
        if isinstance(previous, dict)
        else None
    )
    baseline_candidate = (
        previous_baseline
        if isinstance(previous_baseline, dict)
        else partially_parsed_payload
    )
    retry_state = _functional_retry_state(
        attempt=attempt,
        issues=issues,
        baseline_candidate=baseline_candidate,
        errors=errors,
    )
    previous_stable = (
        (
            previous.get("committed_candidate_calls")
            or previous.get("stable_candidate_calls")
        )
        if isinstance(previous, dict)
        and isinstance(
            previous.get("functional_retry_graph_checkpoint"),
            dict,
        )
        else None
    )
    stable_candidate_calls = tuple(
        dict(item)
        for item in previous_stable or ()
        if isinstance(item, dict)
    )
    preserve_graph = bool(
        stable_candidate_calls and isinstance(baseline_candidate, dict)
    )
    return replace(
        retry_state,
        stable_candidate_prefix=stable_candidate_calls,
        stable_candidate_calls=stable_candidate_calls,
        committed_candidate_calls=stable_candidate_calls,
        runtime_verified_calls=tuple(
            _normalize_call_memory_entry(dict(item))
            for item in (
                previous.get("runtime_verified_calls", ())
                if isinstance(previous, dict)
                else ()
            )
            if isinstance(item, dict)
        ),
        validated_call_ids=tuple(
            item
            for item in (
                previous.get("validated_call_ids", ())
                if isinstance(previous, dict)
                else ()
            )
            if isinstance(item, str)
        ),
        call_memory=tuple(
            _normalize_call_memory_entry(
                dict(item),
                force_provisional=not isinstance(
                    previous.get("functional_retry_graph_checkpoint"),
                    dict,
                ),
            )
            for item in (
                previous.get("call_memory", ())
                if isinstance(previous, dict)
                else ()
            )
            if isinstance(item, dict)
        ),
        preserve_policy=("preserve_graph" if preserve_graph else "none"),
        repair_instruction=functional_repair_instruction(
            stable_candidate_calls=stable_candidate_calls,
            repair_call_ids=retry_state.repair_call_ids,
            issue_count=len(retry_state.issues),
        ),
        replay_reports={
            "functional_validation": validation_report.to_payload(),
        },
        functional_retry_graph_checkpoint=(
            dict(previous["functional_retry_graph_checkpoint"])
            if isinstance(previous, dict)
            and isinstance(
                previous.get("functional_retry_graph_checkpoint"),
                dict,
            )
            else None
        ),
    )


def _functional_feedback_retry_state(
    retry_state: PlannerRetryState,
    *,
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> PlannerRetryState:
    """Apply dynamic feedback even when no partial graph can execute."""
    enriched = _enrich_functional_retry_issues(
        retry_state.issues,
        plan=plan,
        reconciliation=reconciliation,
        catalog=catalog,
        semantic_index=semantic_index,
    )
    issues = apply_capability_repair_feedback(
        enriched,
        plan=plan,
        reconciliation=reconciliation,
        catalog=catalog,
        locked_call_ids=(),
    )
    roots = unique_ordered(
        (
            *retry_state.repair_call_ids,
            *(
                call_id
                for issue in issues
                for details in (issue.details,)
                if isinstance(details, dict)
                for call_id in details.get("repair_call_ids", ())
                if isinstance(call_id, str)
            ),
        )
    )
    return replace(
        retry_state,
        issues=issues,
        repair_call_ids=_ordered_functional_repair_cone(
            roots,
            reconciliation=reconciliation,
        ),
    )



def _diagnostic_field(message: str, name: str) -> str | None:
    marker = f"{name}="
    if marker not in message:
        return None
    value = message.split(marker, 1)[1]
    for separator in (",", ";"):
        value = value.split(separator, 1)[0]
    value = value.strip()
    return value or None



def _normalize_call_memory_entry(
    item: dict[str, Any],
    *,
    force_provisional: bool = False,
) -> dict[str, Any]:
    """Read the one-round mutually exclusive status payload compatibly."""
    legacy_status = item.pop("status", None)
    if "execution_status" not in item:
        item["execution_status"] = (
            "runtime_verified"
            if legacy_status in {"runtime_verified", "goal_committed"}
            else "validated"
        )
    if "commit_status" not in item:
        item["commit_status"] = (
            "goal_committed"
            if legacy_status == "goal_committed"
            else "provisional"
        )
    if force_provisional:
        item["commit_status"] = "provisional"
        item["committed_goals"] = []
    item.setdefault("repair_required", False)
    return item


def _functional_runtime_retry_state(
    retry_state: PlannerRetryState | None,
    *,
    runtime_retry_state: PlannerRetryState | None = None,
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: StepIntentExecutionDiagnostic | None,
    verified_call_ids: set[str] | None = None,
    verified_runtime_results: tuple[Any, ...] = (),
    verified_state_write_provenance: tuple[Any, ...] = (),
    goal_verification_report: AnswerGoalVerificationReport | None = None,
    attempt: int = 0,
    functional_catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
    planner_state_context: PlannerStateContext | None = None,
    expected_retry_checkpoint: FunctionalRetryGraphCheckpoint | None = None,
    allow_goal_commit: bool = True,
    preserve_committed_checkpoint: FunctionalRetryGraphCheckpoint | None = None,
    observed_symbolic_closures: Mapping[str, Any] | None = None,
) -> PlannerRetryState | None:
    if retry_state is None and runtime_retry_state is None:
        return None
    retry_state = retry_state or runtime_retry_state
    assert retry_state is not None
    reconciliation = replace(
        reconciliation,
        dependency_graph=expand_retry_dependency_graph_with_versions(
            reconciliation,
            checkpoint=expected_retry_checkpoint,
        ),
    )
    accepted_step_ids = {
        item.step_id
        for item in (diagnostic.accepted_prefix if diagnostic is not None else ())
    }
    projected_verified = (
        verified_call_ids
        if verified_call_ids is not None
        else {
            item.call_id
            for item in reconciliation.execution_entries
            if item.call_id in accepted_step_ids
        }
    )
    runtime_issues = (
        runtime_retry_state.issues
        if runtime_retry_state is not None
        else retry_state.issues
    )
    provenance_repair_roots = _runtime_provenance_repair_roots(
        runtime_issues,
        diagnostic=diagnostic,
    )
    issues = _unique_retry_issues(
        (*retry_state.issues, *runtime_issues)
    )
    issues = _enrich_functional_retry_issues(
        issues,
        plan=plan,
        reconciliation=reconciliation,
        catalog=functional_catalog,
        semantic_index=semantic_index,
    )
    all_runtime_results = tuple(
        {
            (item.step_id, item.produced_handle): item
            for item in (
                *(diagnostic.runtime_results if diagnostic is not None else ()),
                *verified_runtime_results,
            )
        }.values()
    )
    all_provenance = tuple(
        {
            (item.step_id, item.produced_handle): item
            for item in (
                *(
                    diagnostic.state_write_provenance
                    if diagnostic is not None
                    else ()
                ),
                *verified_state_write_provenance,
            )
        }.values()
    )
    call_memory = build_functional_call_memory(
        reconciliation,
        catalog=functional_catalog,
        runtime_verified_call_ids=tuple(projected_verified),
        runtime_results=all_runtime_results,
        provenance=all_provenance,
        goal_report=goal_verification_report,
        active_issues=issues,
        attempt=attempt,
        allow_goal_commit=(
            allow_goal_commit
            and not any(issue.layer == "answer_check" for issue in issues)
        ),
        symbolic_closures_by_call=observed_symbolic_closures,
    )
    retry_checkpoint = (
        build_functional_retry_graph_checkpoint(
            context=planner_state_context,
            reconciliation=reconciliation,
            call_memory=call_memory,
            provenance=all_provenance,
        )
        if planner_state_context is not None
        else None
    )
    if (
        preserve_committed_checkpoint is not None
        and retry_checkpoint is not None
    ):
        retry_checkpoint = preserve_committed_retry_checkpoint(
            preserve_committed_checkpoint,
            retry_checkpoint,
        )
    call_memory = _with_checkpoint_commit_status(
        call_memory,
        checkpoint=retry_checkpoint,
    )
    if (
        expected_retry_checkpoint is not None
        and retry_checkpoint is not None
    ):
        verify_restored_runtime_checkpoint(
            expected_retry_checkpoint,
            retry_checkpoint,
            require_complete_evidence=False,
        )
    issues = attach_actual_result_refs(
        issues,
        memory=call_memory,
        dependency_graph=reconciliation.dependency_graph,
    )
    committed_candidate_calls = (
        _checkpoint_committed_candidate_calls(retry_checkpoint)
    )
    committed_call_ids = {
        item["call"]["call_id"]
        for item in committed_candidate_calls
    }
    issues = apply_capability_repair_feedback(
        issues,
        plan=plan,
        reconciliation=reconciliation,
        catalog=functional_catalog,
        locked_call_ids=tuple(committed_call_ids),
    )
    repair_call_ids = tuple(
        dict.fromkeys(
            (
                *retry_state.repair_call_ids,
                *provenance_repair_roots,
                *(
                    issue.step_id
                    for issue in issues
                    if issue.step_id is not None
                ),
                *(
                    call_id
                    for issue in issues
                    for details in (issue.details,)
                    if isinstance(details, dict)
                    for call_id in details.get("repair_call_ids", ())
                    if isinstance(call_id, str)
                ),
            )
        )
    )
    repair_call_ids = tuple(
        call_id
        for call_id in repair_call_ids
        if call_id not in committed_call_ids
    )
    repair_call_ids = _ordered_functional_repair_cone(
        repair_call_ids,
        reconciliation=reconciliation,
    )
    repair_suffix_start = dict(retry_state.repair_suffix_start or {})
    if repair_suffix_start.get("step_id") is not None:
        repair_suffix_start["call_id"] = repair_suffix_start["step_id"]
    return replace(
        retry_state,
        candidate_format="functional_plan",
        baseline_candidate=plan.to_payload(),
        stable_candidate_prefix=committed_candidate_calls,
        stable_candidate_calls=committed_candidate_calls,
        committed_candidate_calls=committed_candidate_calls,
        runtime_verified_calls=tuple(
            item.to_payload()
            for item in call_memory.entries
            if (
                item.execution_status == "runtime_verified"
                and item.commit_status != "goal_committed"
                and item.call_id not in committed_call_ids
            )
        ),
        validated_call_ids=call_memory.validated_call_ids,
        call_memory=tuple(call_memory.to_payload()),
        functional_retry_graph_checkpoint=(
            retry_checkpoint.to_payload()
            if retry_checkpoint is not None
            else None
        ),
        repair_call_ids=repair_call_ids,
        issues=issues,
        preserve_policy=(
            "preserve_graph" if committed_candidate_calls else "none"
        ),
        repair_suffix_start=repair_suffix_start or None,
        repair_instruction=functional_repair_instruction(
            stable_candidate_calls=committed_candidate_calls,
            repair_call_ids=repair_call_ids,
            issue_count=len(issues),
        ),
    )


def _transactional_functional_retry_state(
    replay: PlannerRetryReplayResult,
    *,
    attempt_result: FunctionalTransactionalAttemptResult,
    parent_context: PlannerStateContext,
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
) -> PlannerRetryState | None:
    reconciliation = replay.functional_reconciliation
    if reconciliation is None:
        return None
    base_retry = build_planner_retry_state(
        attempt=replay.attempt,
        errors=replay.errors,
        effective_draft=None,
        normalized_draft=replay.normalized_draft,
        validation_report=replay.validation_report,
        normalization_report=replay.normalization_report,
        resolution_report=replay.resolution_report,
        diagnostic=attempt_result.diagnostic,
        handle_registry=handle_registry,
        goal_verification_issues=attempt_result.root_issues,
        guidance_resolver=RepairGuidanceResolver(
            inputs.family_spec,
            inputs.method_specs,
            handle_registry,
        ),
    )
    if (
        attempt_result.compiled_output is not None
        and not replay.errors
        and not attempt_result.root_issues
    ):
        return None
    if base_retry is None:
        return None
    semantic_index = FunctionalSemanticIndex.from_context(
        parent_context,
        handle_registry=handle_registry,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)
    return _functional_runtime_retry_state(
        base_retry,
        runtime_retry_state=base_retry,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=attempt_result.diagnostic,
        verified_call_ids=set(attempt_result.verified_call_ids),
        verified_runtime_results=attempt_result.runtime_results,
        verified_state_write_provenance=attempt_result.state_writes,
        goal_verification_report=attempt_result.goal_report,
        attempt=replay.attempt,
        functional_catalog=catalog,
        semantic_index=semantic_index,
        planner_state_context=parent_context,
        expected_retry_checkpoint=(
            latest_functional_retry_graph_checkpoint(
                inputs.previous_errors
            )
        ),
        observed_symbolic_closures={
            item.call_id: item.symbolic_closure
            for item in attempt_result.execution_report.call_results
            if item.symbolic_closure is not None
        },
    )


def _checkpoint_committed_candidate_calls(
    checkpoint: FunctionalRetryGraphCheckpoint | None,
) -> tuple[dict[str, Any], ...]:
    if checkpoint is None:
        return ()
    return tuple(
        {
            "scope_id": committed.declared_scope_id,
            "call": dict(committed.call_payload),
        }
        for committed in checkpoint.committed_calls
    )


def _with_checkpoint_commit_status(
    memory: FunctionalCallMemory,
    *,
    checkpoint: FunctionalRetryGraphCheckpoint | None,
) -> FunctionalCallMemory:
    """Project existing typed hard locks into prompt-facing call memory."""

    if checkpoint is None or not checkpoint.committed_calls:
        return memory
    goals_by_call = {
        item.canonical_call_id: item.committed_goal_handles
        for item in checkpoint.committed_calls
    }
    committed_ids = tuple(checkpoint.committed_call_ids)
    committed_set = set(committed_ids)
    return replace(
        memory,
        entries=tuple(
            replace(
                item,
                commit_status="goal_committed",
                committed_goal_handles=goals_by_call.get(
                    item.call_id,
                    item.committed_goal_handles,
                ),
            )
            if (
                item.call_id in committed_set
                and item.execution_status == "runtime_verified"
            )
            else item
            for item in memory.entries
        ),
        committed_call_ids=committed_ids,
        runtime_verified_call_ids=tuple(
            call_id
            for call_id in memory.runtime_verified_call_ids
            if call_id not in committed_set
        ),
    )


def _verify_successful_functional_retry_checkpoint(
    expected: FunctionalRetryGraphCheckpoint,
    *,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: StepIntentExecutionDiagnostic | None,
    goal_verification_report: AnswerGoalVerificationReport | None,
    attempt: int,
    functional_catalog: FunctionalCapabilityCatalog,
    planner_state_context: PlannerStateContext,
) -> None:
    """Verify committed versions on a retry that completed successfully."""

    accepted_step_ids = {
        item.step_id
        for item in (
            diagnostic.accepted_prefix if diagnostic is not None else ()
        )
    }
    runtime_verified_call_ids = tuple(
        item.call_id
        for item in reconciliation.execution_entries
        if item.call_id in accepted_step_ids
    )
    runtime_results = (
        tuple(diagnostic.runtime_results)
        if diagnostic is not None
        else ()
    )
    provenance = (
        tuple(diagnostic.state_write_provenance)
        if diagnostic is not None
        else ()
    )
    call_memory = build_functional_call_memory(
        reconciliation,
        catalog=functional_catalog,
        runtime_verified_call_ids=runtime_verified_call_ids,
        runtime_results=runtime_results,
        provenance=provenance,
        goal_report=goal_verification_report,
        active_issues=(),
        attempt=attempt,
        allow_goal_commit=True,
    )
    actual = build_functional_retry_graph_checkpoint(
        context=planner_state_context,
        reconciliation=reconciliation,
        call_memory=call_memory,
        provenance=provenance,
    )
    verify_restored_runtime_checkpoint(expected, actual)


def _runtime_provenance_repair_roots(
    issues: tuple[PlannerRetryIssue, ...],
    *,
    diagnostic: StepIntentExecutionDiagnostic | None,
) -> tuple[str, ...]:
    """Trace unresolved output state to its earliest call-level producer.

    Goal verification naturally reports the terminal answer writer. When that
    writer merely preserves an already-open state, freezing the upstream writer
    makes retry ineffective. Provenance gives us a deterministic reverse edge;
    follow it only while the same unresolved symbols are still present.
    """

    if diagnostic is None:
        return ()
    writes_by_step: dict[str, list[Any]] = {}
    writes_by_slot: dict[str, list[Any]] = {}
    for write in diagnostic.state_write_provenance:
        writes_by_step.setdefault(write.step_id, []).append(write)
        if write.state_slot_id is not None:
            writes_by_slot.setdefault(write.state_slot_id, []).append(write)
    roots: list[str] = []
    for issue in issues:
        details = issue.details if isinstance(issue.details, dict) else {}
        symbols = {
            str(item)
            for key in ("unresolved_symbols", "free_symbol_names")
            for item in details.get(key, ())
            if isinstance(item, str) and item
        }
        if not symbols or issue.step_id is None:
            continue
        frontier = {issue.step_id}
        visited: set[str] = set()
        terminal: set[str] = set()
        while frontier:
            step_id = frontier.pop()
            if step_id in visited:
                continue
            visited.add(step_id)
            sources: set[str] = set()
            for write in writes_by_step.get(step_id, ()):
                if not symbols.intersection(write.free_symbol_names):
                    continue
                if write.source_step_id is not None:
                    sources.add(write.source_step_id)
                for slot_id in write.source_state_slot_ids:
                    for source in writes_by_slot.get(slot_id, ()):
                        if (
                            source.step_id != step_id
                            and symbols.intersection(source.free_symbol_names)
                        ):
                            sources.add(source.step_id)
            if sources:
                frontier.update(sources - visited)
            else:
                terminal.add(step_id)
        roots.extend(sorted(terminal))
    return unique_ordered(roots)


def _retry_state_with_candidate_format(
    retry_state: PlannerRetryState | None,
    candidate_format: PlannerOutputFormat,
) -> PlannerRetryState | None:
    """Keep Context projection on the candidate IR that owns the replay.

    FunctionalPlan temporarily projects through StepIntent, but its inner
    replay must not let linear StepIntent prefix semantics recover graph-level
    issues before the Functional stable graph is computed.
    """
    if retry_state is None or retry_state.candidate_format == candidate_format:
        return retry_state
    return replace(retry_state, candidate_format=candidate_format)


def _enrich_functional_retry_issues(
    issues: tuple[PlannerRetryIssue, ...],
    *,
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[PlannerRetryIssue, ...]:
    """Project runtime failures back to typed Functional call arguments."""
    calls = {call.call_id: call for call in plan.calls}
    call_scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    call_order = {call.call_id: index for index, call in enumerate(plan.calls)}
    step_to_call = {
        item.call_id: item.canonical_call_id
        for item in reconciliation.execution_entries
    }
    result: list[PlannerRetryIssue] = []
    placements_by_call = {
        placement.canonical_call_id: placement
        for placement in reconciliation.call_placements
    }
    for issue in issues:
        issue_call_id = step_to_call.get(
            issue.step_id or "",
            issue.step_id or "",
        )
        call = calls.get(issue_call_id)
        capability = (
            catalog.get(call.capability_id) if call is not None else None
        )
        details = dict(issue.details or {})
        argument_name = details.get("arg")
        unresolved_point_ref = details.get("unresolved_point_ref")
        reconciled_call = next(
            (
                item
                for item in reconciliation.calls
                if call is not None and item.call_id == call.call_id
            ),
            None,
        )
        error_code = details.get("error_code") or issue.code
        if (
            error_code == "function.transition_dependency_missing"
            and call is not None
        ):
            previous_step_id = (
                details.get("previous_writer_call_id")
                or _diagnostic_field(issue.message, "previous_step")
            )
            previous_call_id = step_to_call.get(
                previous_step_id or "",
                previous_step_id,
            )
            repair_call_ids = unique_ordered(
                call_id
                for call_id in (previous_call_id, call.call_id)
                if isinstance(call_id, str) and call_id in calls
            )
            details.update(
                {
                    "previous_writer_call_id": previous_call_id,
                    "current_writer_call_id": call.call_id,
                    "repair_call_ids": list(repair_call_ids),
                }
            )
            result.append(
                replace(
                    issue,
                    step_id=call.call_id,
                    repair_target="functional_call",
                    message=(
                        f"call {call.call_id} writes a new state of the same "
                        f"mathematical object as {previous_call_id}, but its "
                        "inputs do not prove a state transition"
                    ),
                    details=details,
                )
            )
            continue
        if (
            error_code == "function.transition_previous_write_mismatch"
            and call is not None
        ):
            expected_step_id = details.get("expected_previous_step_id")
            actual_step_id = details.get("actual_previous_step_id")
            expected_call_id = step_to_call.get(
                expected_step_id,
                expected_step_id,
            )
            actual_call_id = step_to_call.get(
                actual_step_id,
                actual_step_id,
            )
            expression_values = (
                reconciled_call.resolved_args.get("expression", ())
                if reconciled_call is not None
                else ()
            )
            state_value_type = (
                expression_values[0].runtime_type
                if len(expression_values) == 1
                else None
            )
            repair_call_ids = unique_ordered(
                call_id
                for call_id in (actual_call_id, call.call_id)
                if isinstance(call_id, str) and call_id in calls
            )
            context_call_ids = unique_ordered(
                call_id
                for call_id in (expected_call_id,)
                if isinstance(call_id, str) and call_id in calls
            )
            details.update(
                {
                    "expected_previous_call_id": expected_call_id,
                    "actual_previous_call_id": actual_call_id,
                    "consumer_call_id": call.call_id,
                    "state_value_type": state_value_type,
                    "repair_call_ids": list(repair_call_ids),
                    "context_call_ids": list(context_call_ids),
                }
            )
            result.append(
                replace(
                    issue,
                    step_id=call.call_id,
                    repair_target="functional_call",
                    message=(
                        f"call {call.call_id} reads a state version produced by "
                        f"{actual_call_id}, but its transition must continue "
                        f"from {expected_call_id}"
                    ),
                    details=details,
                )
            )
            continue
        if (
            error_code == "function.substitution_symbol_mismatch"
            and call is not None
        ):
            free_symbol_names = tuple(
                item
                for item in details.get("free_symbol_names", ())
                if isinstance(item, str)
            )
            compatible_refs = unique_ordered(
                f"{prior.call_id}.{allocation.return_name}"
                for prior in reconciliation.calls
                if call_order.get(prior.call_id, -1)
                < call_order.get(call.call_id, -1)
                for allocation in prior.returns
                if allocation.runtime_type == "ParameterValue"
                and allocation.object_ref is not None
                and allocation.object_ref.rsplit(":", 1)[-1]
                in set(free_symbol_names)
            )
            current_parameter_producers = unique_ordered(
                value.source_call_id
                for value in (
                    reconciled_call.resolved_args.get(
                        "parameter_value",
                        (),
                    )
                    if reconciled_call is not None
                    else ()
                )
                if value.source_call_id is not None
            )
            details.update(
                {
                    "compatible_refs": list(compatible_refs),
                    "repair_call_ids": list(
                        unique_ordered(
                            (*current_parameter_producers, call.call_id)
                        )
                    ),
                }
            )
            result.append(
                replace(
                    issue,
                    step_id=call.call_id,
                    repair_target="functional_call",
                    message=(
                        f"call {call.call_id} cannot substitute parameter "
                        f"{details.get('parameter_name')}: the input expression "
                        "has a different free-Symbol identity"
                    ),
                    details=details,
                )
            )
            continue
        if (
            argument_name is None
            and isinstance(unresolved_point_ref, str)
            and reconciled_call is not None
        ):
            point_args = [
                name
                for name, values in reconciled_call.resolved_args.items()
                if any(
                    (
                        value.runtime_type == "Point"
                        and value.object_ref is not None
                        and value.object_ref.rsplit(":", 1)[-1]
                        == unresolved_point_ref
                    )
                    or any(
                        object_ref.rsplit(":", 1)[-1]
                        == unresolved_point_ref
                        for object_ref in value.dependency_object_refs
                    )
                    for value in values
                )
            ]
            if len(point_args) == 1:
                argument_name = point_args[0]
        argument = next(
            (
                item
                for item in (capability.args if capability is not None else ())
                if item.name == argument_name
            ),
            None,
        )
        if call is None or argument is None:
            result.append(issue)
            continue
        accepted_types = (
            ("Point",)
            if details.get("error_code") == "function.arg_state_unavailable"
            else argument.accepted_item_types or (argument.runtime_type,)
        )
        accepted_semantic_roles = tuple(
            details.get("accepted_semantic_roles", ())
            or argument.accepted_semantic_roles
        )
        requires_materialized_state = bool(
            details.get("state_requirement") == "materialized_state"
            or argument.requires_materialized_state
        )
        missing_symbol_handles = {
            item
            for item in details.pop("missing_symbol_handles", ())
            if isinstance(item, str)
        }
        required_object_refs = set(missing_symbol_handles)
        required_object_ref = details.get("object_ref")
        if isinstance(required_object_ref, str):
            required_object_refs.add(required_object_ref)
        if (
            isinstance(unresolved_point_ref, str)
            and reconciled_call is not None
            and isinstance(argument_name, str)
        ):
            required_object_refs.update(
                object_ref
                for value in reconciled_call.resolved_args.get(
                    argument_name,
                    (),
                )
                for object_ref in (
                    *((value.object_ref,) if value.object_ref is not None else ()),
                    *value.dependency_object_refs,
                )
                if object_ref.rsplit(":", 1)[-1]
                == unresolved_point_ref
            )
        required_symbol_sources = [
            {
                "from_call": source.get("from_call"),
                "return": source.get("return"),
                "value_type": source.get("value_type", "Symbol"),
            }
            for source in details.get("required_symbol_sources", ())
            if isinstance(source, dict)
            and isinstance(source.get("from_call"), str)
            and isinstance(source.get("return"), str)
        ]
        required_symbol_sources.extend(
            {
                "from_call": prior.call_id,
                "return": allocation.return_name,
                "value_type": allocation.runtime_type,
            }
            for prior in reconciliation.calls
            if call_order.get(prior.call_id, -1) < call_order[call.call_id]
            for allocation in prior.returns
            if allocation.runtime_type == "Symbol"
            and allocation.object_ref in missing_symbol_handles
        )
        required_symbol_sources = list(
            {
                (item["from_call"], item["return"]): item
                for item in required_symbol_sources
            }.values()
        )
        allocations_by_source = {
            (prior.call_id, allocation.return_name): allocation
            for prior in reconciliation.calls
            for allocation in prior.returns
        }
        required_object_refs.update(
            allocation.object_ref
            for source in required_symbol_sources
            for allocation in (
                allocations_by_source.get(
                    (source["from_call"], source["return"])
                ),
            )
            if allocation is not None and allocation.object_ref is not None
        )
        details.update(
            {
                "arg": argument.name,
                "semantic_role": argument.semantic_role or argument.name,
                "accepted_item_types": list(accepted_types),
                "accepted_condition_kinds": list(
                    argument.accepted_condition_kinds
                ),
                "compatible_refs": list(
                    semantic_index.available_refs(
                        scope_id=call_scopes[call.call_id],
                        accepted_types=accepted_types,
                        accepted_condition_kinds=(
                            argument.accepted_condition_kinds
                        ),
                        accepted_semantic_roles=accepted_semantic_roles,
                        requires_materialized_state=(
                            requires_materialized_state
                        ),
                    )
                ),
            }
        )
        if accepted_semantic_roles:
            details["accepted_semantic_roles"] = list(
                accepted_semantic_roles
            )
        if requires_materialized_state:
            details["state_requirement"] = "materialized_state"
        if required_symbol_sources:
            details["required_symbol_sources"] = required_symbol_sources
        current_bindings = _functional_current_arg_bindings(
            call,
            argument_name=argument.name,
            reconciliation=reconciliation,
            required_object_refs=required_object_refs,
        )
        if reconciled_call is not None:
            resolved_current_values = reconciled_call.resolved_args.get(
                argument.name,
                (),
            )
            for item, value in zip(current_bindings, resolved_current_values):
                item.setdefault("value_type", value.runtime_type)
                if required_object_refs:
                    item["identity_matches_required"] = (
                        value.object_ref in required_object_refs
                    )
        if current_bindings and "current_bindings" not in details:
            details["current_bindings"] = current_bindings
        compatible_results = [
            {
                "from_call": prior.call_id,
                "return": allocation.return_name,
                "value_type": allocation.runtime_type,
            }
            for prior in reconciliation.calls
            if call_order.get(prior.call_id, -1) < call_order[call.call_id]
            for allocation in prior.returns
            if visible_from_valid_scope(
                allocation.valid_scope,
                scope_id=call_scopes[call.call_id],
                registry=semantic_index.handle_registry,
            )
            if any(
                runtime_type_compatible(expected, allocation.runtime_type)
                for expected in accepted_types
            )
            if not accepted_semantic_roles
            or allocation.return_name in accepted_semantic_roles
            if not required_object_refs
            or allocation.object_ref in required_object_refs
        ]
        declared_compatible_results = _declared_compatible_call_results(
            plan=plan,
            catalog=catalog,
            consumer_call_id=call.call_id,
            consumer_scope_id=call_scopes[call.call_id],
            accepted_types=accepted_types,
            accepted_semantic_roles=accepted_semantic_roles,
            call_order=call_order,
            call_scopes=call_scopes,
            placements_by_call=placements_by_call,
            handle_registry=semantic_index.handle_registry,
            required_object_refs=required_object_refs,
        )
        compatible_results = list(
            {
                (item["from_call"], item["return"]): item
                for item in (
                    *compatible_results,
                    *declared_compatible_results,
                )
            }.values()
        )
        if compatible_results:
            details["compatible_call_results"] = compatible_results
        later_compatible_results = [
            {
                "from_call": later.call_id,
                "return": allocation.return_name,
                "value_type": allocation.runtime_type,
            }
            for later in reconciliation.calls
            if call_order.get(later.call_id, -1) > call_order[call.call_id]
            for allocation in later.returns
            if any(
                runtime_type_compatible(expected, allocation.runtime_type)
                for expected in accepted_types
            )
            if not accepted_semantic_roles
            or allocation.return_name in accepted_semantic_roles
            if not required_object_refs
            or allocation.object_ref in required_object_refs
        ]
        if later_compatible_results:
            details["later_compatible_call_results"] = later_compatible_results
        if details.get("error_code") == "function.arg_state_unavailable":
            details["state_requirement"] = "computed Point"
        if not details["compatible_refs"] and not compatible_results:
            producers = [
                candidate.capability_id
                for candidate in catalog.items.values()
                if candidate.capability_id != call.capability_id
                and any(
                    runtime_type_compatible(expected, returned.runtime_type)
                    for returned in candidate.returns
                    for expected in accepted_types
                )
                and (
                    not accepted_semantic_roles
                    or any(
                        returned.semantic_role in accepted_semantic_roles
                        for returned in candidate.returns
                    )
                )
            ]
            producers = list(dict.fromkeys(producers))
            if len(producers) == 1:
                details["producer_candidate"] = producers[0]
        message = issue.message
        if issue.code == "function.unresolved_symbol_inputs":
            required = ", ".join(
                f"{item['from_call']}.{item['return']}"
                for item in required_symbol_sources
            ) or "an unresolved Symbol state"
            message = (
                f"call {call.call_id} requires a ParameterValue whose Symbol "
                f"identity matches {required}; the current binding does not "
                "cover that Symbol"
            )
        elif issue.code == "functional.arg_identity_mismatch":
            required = ", ".join(
                f"{item['from_call']}.{item['return']}"
                for item in required_symbol_sources
            ) or "the missing Symbol identity"
            message = (
                f"call {call.call_id} cannot run with its current bindings: "
                f"{argument.semantic_role or argument.name} must provide a "
                f"ParameterValue matching {required}. Reusing the unchanged "
                "capability and bindings will fail; add a prior producer for "
                "that state or replace this call with a capability that can "
                "produce the same external destination from resolved states."
            )
        elif details.get("error_code") == "function.arg_applicability":
            message = (
                f"call {call.call_id} cannot use its current "
                f"{argument.semantic_role or argument.name}: this capability "
                "requires a Point state with exactly one unresolved Symbol"
            )
        elif details.get("error_code") == "function.arg_state_unavailable":
            message = (
                f"call {call.call_id} requires an already computed Point state "
                f"for {argument.semantic_role or argument.name}; "
                f"{unresolved_point_ref} is currently only an object reference. "
                "Move its producer earlier or bind this arg to that prior call result."
            )
            issue = replace(issue, code="functional.arg_state_unavailable")
        result.append(
            replace(
                issue,
                repair_target="functional_call",
                message=message,
                details=details,
            )
        )
    return tuple(result)


def _declared_compatible_call_results(
    *,
    plan: FunctionalPlan,
    catalog: FunctionalCapabilityCatalog,
    consumer_call_id: str,
    consumer_scope_id: str,
    accepted_types: tuple[str, ...],
    accepted_semantic_roles: tuple[str, ...],
    call_order: dict[str, int],
    call_scopes: dict[str, str],
    placements_by_call: dict[str, Any],
    handle_registry: CanonicalHandleRegistry,
    required_object_refs: set[str],
) -> list[dict[str, str]]:
    """Offer prior declared returns even when an optional return was not allocated.

    A CallResultRef in the repaired plan is itself enough to request an
    optional return. ``internal_only`` forbids destination bindings and
    expectations, but does not forbid a downstream CallResultRef. Restrict
    candidates to prior visible calls whose declared runtime type and semantic
    role satisfy the consumer contract.
    """

    # A declaration alone cannot prove a required MathObject identity. In that
    # case only an allocated return with typed object provenance is eligible.
    if required_object_refs:
        return []

    accepted_roles = {
        canonical_straightening_endpoint_name(role) or role
        for role in accepted_semantic_roles
    }
    result: list[dict[str, str]] = []
    for prior in plan.calls:
        if call_order.get(prior.call_id, -1) >= call_order[consumer_call_id]:
            continue
        capability = catalog.get(prior.capability_id)
        if capability is None:
            continue
        placement = placements_by_call.get(prior.call_id)
        for returned in capability.returns:
            if not any(
                runtime_type_compatible(expected, returned.runtime_type)
                for expected in accepted_types
            ):
                continue
            return_roles = {
                returned.name,
                returned.semantic_role,
                returned.equivalent_to,
                *returned.provides_semantic_roles,
            }
            canonical_roles = {
                canonical_straightening_endpoint_name(role) or role
                for role in return_roles
                if role
            }
            if accepted_roles and not accepted_roles.intersection(
                canonical_roles
            ):
                continue
            valid_scope = (
                placement.return_scopes.get(
                    returned.name,
                    placement.execution_scope_id,
                )
                if placement is not None
                else call_scopes.get(prior.call_id, consumer_scope_id)
            )
            if not visible_from_valid_scope(
                valid_scope,
                scope_id=consumer_scope_id,
                registry=handle_registry,
            ):
                continue
            result.append(
                {
                    "from_call": prior.call_id,
                    "return": returned.name,
                    "value_type": returned.runtime_type,
                }
            )
    return result


def _functional_current_arg_bindings(
    call: Any,
    *,
    argument_name: str,
    reconciliation: FunctionalPlanReconciliationResult,
    required_object_refs: set[str],
) -> list[dict[str, Any]]:
    allocations = {
        (prior.call_id, allocation.return_name): allocation
        for prior in reconciliation.calls
        for allocation in prior.returns
    }
    result: list[dict[str, Any]] = []
    for ref in call.args.get(argument_name, ()):
        if isinstance(ref, CallResultRef):
            allocation = allocations.get((ref.from_call, ref.return_name))
            item: dict[str, Any] = {
                "from_call": ref.from_call,
                "return": ref.return_name,
            }
            if allocation is not None:
                item["value_type"] = allocation.runtime_type
                if required_object_refs:
                    item["identity_matches_required"] = (
                        allocation.object_ref in required_object_refs
                    )
        else:
            item = {
                "ref": ref.ref,
                "kind": ref.kind,
            }
        result.append(item)
    return result


def _root_repair_call_ids(
    reconciliation: FunctionalPlanReconciliationResult,
) -> tuple[str, ...]:
    structured = _repair_call_ids_from_functional_issues(
        reconciliation.issues
    )
    if structured:
        return structured
    return tuple(
        report.call_id
        for report in reconciliation.call_reports
        if report.status == "invalid"
    )


def _repair_call_ids_from_functional_issues(
    issues: tuple[FunctionalPlanIssue, ...],
) -> tuple[str, ...]:
    result: list[str] = []
    for issue in issues:
        details = issue.details if isinstance(issue.details, dict) else {}
        structured = details.get("repair_call_ids")
        if isinstance(structured, (list, tuple)) and structured:
            result.extend(
                item for item in structured if isinstance(item, str) and item
            )
        if not structured and issue.call_id is not None:
            result.append(issue.call_id)
    return tuple(dict.fromkeys(result))


def _unique_retry_issues(
    issues: tuple[PlannerRetryIssue, ...],
) -> tuple[PlannerRetryIssue, ...]:
    result: dict[tuple[Any, ...], PlannerRetryIssue] = {}
    for issue in issues:
        key = (issue.layer, issue.code, issue.step_id, issue.scope_id, issue.message)
        result.setdefault(key, issue)
    return tuple(result.values())


def _functional_dependency_graph_with_projected_versions(
    dependency_graph: dict[str, tuple[str, ...]],
    *,
    projected_state_writes: tuple[ProjectedStateWrite, ...],
    projected_state_dependencies: tuple[ProjectedStateDependency, ...],
) -> dict[str, tuple[str, ...]]:
    """Compatibility wrapper around the shared typed dependency graph."""

    return expand_functional_dependency_graph(
        dependency_graph,
        projected_state_writes=projected_state_writes,
        projected_state_dependencies=projected_state_dependencies,
    )


def _functional_topological_call_ids(
    call_ids: tuple[str, ...],
    dependency_graph: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    original_position = {
        call_id: index for index, call_id in enumerate(call_ids)
    }
    pending = set(call_ids)
    ordered: list[str] = []
    while pending:
        ready = min(
            (
                call_id
                for call_id in pending
                if not (set(dependency_graph.get(call_id, ())) & pending)
            ),
            key=original_position.__getitem__,
            default=None,
        )
        if ready is None:
            ordered.extend(
                sorted(pending, key=original_position.__getitem__)
            )
            break
        ordered.append(ready)
        pending.remove(ready)
    return tuple(ordered)


def _functional_dependency_closure(
    call_id: str,
    dependency_graph: dict[str, tuple[str, ...]],
) -> set[str]:
    result: set[str] = set()
    pending = [call_id]
    while pending:
        current = pending.pop()
        if current in result:
            continue
        result.add(current)
        pending.extend(dependency_graph.get(current, ()))
    return result


def _functional_dependent_closure(
    root_call_ids: set[str],
    dependency_graph: dict[str, tuple[str, ...]],
) -> set[str]:
    """Return failure roots and every call transitively blocked by them."""
    reverse: dict[str, set[str]] = {}
    for call_id, dependencies in dependency_graph.items():
        for dependency in dependencies:
            reverse.setdefault(dependency, set()).add(call_id)
    result = set(root_call_ids)
    pending = list(root_call_ids)
    while pending:
        current = pending.pop()
        for dependent in reverse.get(current, ()):
            if dependent in result:
                continue
            result.add(dependent)
            pending.append(dependent)
    return result


def _ordered_functional_repair_cone(
    root_call_ids: tuple[str, ...],
    *,
    reconciliation: FunctionalPlanReconciliationResult,
) -> tuple[str, ...]:
    """Expand repair roots to every dependent call in canonical plan order."""
    if not root_call_ids:
        return ()
    root_set = set(root_call_ids)
    known_call_ids = {call.call_id for call in reconciliation.plan.calls}
    repair_cone = _functional_dependent_closure(
        root_set & known_call_ids,
        reconciliation.dependency_graph,
    )
    ordered = [
        call.call_id
        for call in reconciliation.plan.calls
        if call.call_id in repair_cone
    ]
    ordered.extend(
        call_id for call_id in root_call_ids if call_id not in known_call_ids
    )
    return tuple(dict.fromkeys(ordered))


def _draft_for_step_ids(
    draft: StepIntentDraft,
    step_ids: set[str],
) -> StepIntentDraft:
    return StepIntentDraft(
        scopes=tuple(
            StepIntentScope(
                scope.scope_id,
                scope.label,
                tuple(step for step in scope.steps if step.step_id in step_ids),
            )
            for scope in draft.scopes
            if any(step.step_id in step_ids for step in scope.steps)
        )
    )


__all__ = [
    "PlannerRetryReplayResult",
    "PlannerRetryReplayService",
    "repair_attempt_payload_from_replay",
    "transactional_repair_attempt_payload_from_replay",
]


def _with_planner_state_context(
    replay: PlannerRetryReplayResult,
    *,
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
    problem_payload: dict[str, Any] | None,
) -> PlannerRetryReplayResult:
    context = _planner_state_context_from_replay(
        replay,
        inputs=inputs,
        handle_registry=handle_registry,
        problem_payload=problem_payload,
    )
    projected_retry_state = PlannerRetryStateProjector.from_context(context)
    return replace(
        replay,
        planner_state_context=context,
        retry_state=projected_retry_state or replay.retry_state,
    )


def _append_normalization_actions(
    report: StepIntentNormalizationReport,
    actions: tuple[StepIntentNormalizationAction, ...],
) -> StepIntentNormalizationReport:
    if not actions:
        return report
    return StepIntentNormalizationReport(
        actions=(*report.actions, *actions),
        warnings=report.warnings,
    )


def _planner_state_context_from_replay(
    replay: PlannerRetryReplayResult,
    *,
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
    problem_payload: dict[str, Any] | None,
) -> PlannerStateContext:
    context_problem_payload, context_warnings = _problem_payload_for_context(
        inputs,
        problem_payload,
    )
    return PlannerStateContextBuilder.from_replay_result(
        replay,
        inputs=inputs,
        problem_payload=context_problem_payload,
        handle_registry=handle_registry,
        context_warnings=context_warnings,
        parent_context_id=_parent_context_id_from_attempts(inputs.previous_errors),
    )


def _initial_planner_state_context(
    *,
    inputs: PlannerInputs,
    handle_registry: CanonicalHandleRegistry,
    problem_payload: dict[str, Any] | None,
    attempt: int,
    previous_attempts: list[Any],
) -> PlannerStateContext:
    context_problem_payload, _context_warnings = _problem_payload_for_context(
        inputs,
        problem_payload,
    )
    context = initial_planner_state_context(
        inputs,
        problem_payload=context_problem_payload,
        handle_registry=handle_registry,
        attempt=attempt,
        parent_context_id=_parent_context_id_from_attempts(previous_attempts),
    )
    checkpoint = latest_functional_retry_graph_checkpoint(previous_attempts)
    if checkpoint is None:
        legacy_retry_state = next(
            (
                parsed_retry_state
                for attempt_payload in reversed(previous_attempts)
                if isinstance(attempt_payload, dict)
                and (
                    parsed_retry_state := retry_state_from_attempt(
                        attempt_payload
                    )
                )
                is not None
            ),
            None,
        )
        has_legacy_committed_calls = (
            isinstance(legacy_retry_state, dict)
            and legacy_retry_state.get("candidate_format")
            == "functional_plan"
            and bool(
                legacy_retry_state.get("committed_candidate_calls")
                or legacy_retry_state.get("stable_candidate_calls")
            )
        )
        if not has_legacy_committed_calls:
            return context
        return replace(
            context,
            state=replace(
                context.state,
                context_events=(
                    *context.state.context_events,
                    {
                        "event": "legacy_retry_checkpoint_missing",
                        "ok": True,
                        "detail_count": 1,
                        "detail": (
                            "legacy committed calls were downgraded "
                            "to provisional memory"
                        ),
                    },
                ),
            ),
        )
    return replace(
        context,
        state=replace(
            context.state,
            retry_memory=replace(
                context.state.retry_memory,
                functional_retry_graph_checkpoint=checkpoint.to_payload(),
            ),
        ),
    )


def _problem_payload_for_context(
    inputs: PlannerInputs,
    problem_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    if problem_payload is not None:
        return problem_payload, ()
    if inputs.problem is not None:
        return problem_to_llm_payload(inputs.problem), ()
    return (
        {"problem_id": inputs.problem_id, "scopes": []},
        (
            {
                "layer": "planner_state_context",
                "code": "incomplete_problem_payload",
                "message": (
                    "PlannerStateContext was built without problem_payload or "
                    "PlannerInputs.problem; problem_ir is a minimal fallback."
                ),
            },
        ),
    )


def _parent_context_id_from_attempts(
    previous_attempts: list[Any],
) -> str | None:
    for item in reversed(previous_attempts):
        if not isinstance(item, dict):
            continue
        # Prefer the direct context reference: it is written by the replay
        # layer when the snapshot is created. Retry-state source_context_id is
        # only a compatibility projection and may be absent on older attempts.
        ref = item.get("planner_state_context_ref")
        if isinstance(ref, dict):
            context_id = ref.get("context_id")
            if isinstance(context_id, str) and context_id:
                return context_id
        for key in ("context_derived_retry_state", "planner_retry_state"):
            state = item.get(key)
            if not isinstance(state, dict):
                continue
            context_id = state.get("source_context_id")
            if isinstance(context_id, str) and context_id:
                return context_id
    return None
