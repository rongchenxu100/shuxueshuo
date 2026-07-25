"""Deterministic replay pipeline for planner retry state generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from typing import Any, Literal

from shuxueshuo_server.solver.runtime.answer_goal_verifier import AnswerGoalVerifier
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
    ProjectedStateWrite,
    PlannerRetryState,
    PlannerRetryIssue,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationReport,
    StepIntentNormalizationAction,
    StepIntentRepairAttempt,
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
from shuxueshuo_server.solver.runtime.strategy_retry_state import build_planner_retry_state
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator
from shuxueshuo_server.solver.utils import unique_ordered


@dataclass(frozen=True)
class PlannerRetryReplayResult:
    """一次 deterministic replay 的完整产物。"""

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
    retry_state: PlannerRetryState | None = None
    output: Any | None = None
    planner_state_context: PlannerStateContext | None = None
    functional_plan: FunctionalPlan | None = None
    functional_validation_report: FunctionalPlanValidationReport | None = None
    functional_reconciliation: FunctionalPlanReconciliationResult | None = None

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
        }


@dataclass(frozen=True)
class _FunctionalProjectionRecovery:
    """Verified remainder of a Functional graph after bridge validation fails."""

    issues: tuple[FunctionalPlanIssue, ...]
    verified_call_ids: frozenset[str] = frozenset()
    blocked_call_ids: tuple[str, ...] = ()
    validation_reports: tuple[dict[str, Any], ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "verified_call_ids": sorted(self.verified_call_ids),
            "blocked_call_ids": list(self.blocked_call_ids),
            "validation_reports": [dict(item) for item in self.validation_reports],
        }

class PlannerRetryReplayService:
    """统一执行 StepIntent deterministic replay 并生成 retry state。"""

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
            retry_state = _functional_retry_state(
                attempt=attempt,
                issues=report.issues,
                baseline_candidate=report.partially_parsed_payload,
                errors=errors,
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
    ) -> PlannerRetryReplayResult:
        """Reconcile FunctionalPlan, then reuse the canonical StepIntent replay."""
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
        )
        authoritative_output_types = {
            output.handle: output.runtime_type
            for call in reconciliation.calls
            for output in call.returns
        }
        projected_state_writes = _functional_projected_state_writes(
            reconciliation
        )
        projected_function_arg_bindings = (
            _functional_projected_arg_bindings(
                reconciliation,
                catalog=functional_catalog,
            )
        )
        projected_candidate = (
            reconciliation.projected_draft
            if reconciliation.ok
            else reconciliation.partial_projected_draft
        )
        has_partial_steps = bool(
            projected_candidate is not None and projected_candidate.steps
        )
        if projected_candidate is None or not has_partial_steps:
            retry_state = _functional_retry_state(
                attempt=attempt,
                issues=reconciliation.issues,
                baseline_candidate=reconciliation.plan.to_payload(),
                errors=errors,
                replay_report=reconciliation.to_payload(),
                repair_call_ids=_root_repair_call_ids(reconciliation),
            )
            replay = PlannerRetryReplayResult(
                attempt=attempt,
                errors=errors or tuple(issue.message for issue in reconciliation.issues),
                retry_state=retry_state,
                functional_plan=plan,
                functional_validation_report=validation_report,
                functional_reconciliation=reconciliation,
            )
            return _with_planner_state_context(
                replay,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
            )
        projected_draft, step_validation = StepIntentValidator().validate_json_with_report(
            json.dumps(projected_candidate.to_payload(), ensure_ascii=False),
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
            planner_state_context=planner_state_context,
            partial_candidate=not reconciliation.ok,
            allow_shared_derivation_scopes=True,
            allow_internal_output_types=True,
            projected_state_writes=projected_state_writes,
        )
        if projected_draft is None:
            projection_errors = tuple(step_validation.errors) or (
                "FunctionalPlan projection produced invalid canonical StepIntent",
            )
            replay_errors = errors or tuple(
                "planner_configuration_error: FunctionalPlan projection produced "
                f"invalid StepIntent: {message}"
                for message in projection_errors
            )
            recovery = self._recover_functional_projection_graph(
                reconciliation,
                projected_candidate=projected_candidate,
                validation_report=step_validation,
                inputs=inputs,
                handle_registry=handle_registry,
                context=context,
                attempt=attempt,
                problem_payload=problem_payload,
                planner_state_context=planner_state_context,
                authoritative_output_types=authoritative_output_types,
                projected_state_writes=projected_state_writes,
                projected_function_arg_bindings=projected_function_arg_bindings,
            )
            retry_state = _functional_projection_retry_state(
                attempt=attempt,
                reconciliation=reconciliation,
                validation_report=step_validation,
                previous_attempts=inputs.previous_errors,
                recovery=recovery,
            )
            replay = PlannerRetryReplayResult(
                attempt=attempt,
                errors=replay_errors,
                raw_draft=projected_candidate,
                validation_report=step_validation,
                retry_state=retry_state,
                functional_plan=plan,
                functional_validation_report=validation_report,
                functional_reconciliation=reconciliation,
            )
            return _with_planner_state_context(
                replay,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
            )
        base = self.replay_draft(
            projected_draft,
            inputs=inputs,
            handle_registry=handle_registry,
            context=context,
            attempt=attempt,
            errors=errors,
            validation_report=step_validation,
            merge_previous_prefix=False,
            problem_payload=problem_payload,
            partial_candidate=not reconciliation.ok,
            authoritative_output_types=authoritative_output_types,
            allow_shared_derivation_scopes=True,
            candidate_format="functional_plan",
            projected_state_writes=projected_state_writes,
            projected_function_arg_bindings=projected_function_arg_bindings,
        )
        reconciliation = _apply_function_arg_binding_repairs(
            reconciliation,
            diagnostic=base.diagnostic,
        )
        result_form_events, result_form_issues = verify_functional_result_forms(
            reconciliation.plan,
            reconciliation,
            base.diagnostic,
            catalog=functional_catalog,
        )
        if result_form_events:
            reconciliation = replace(
                reconciliation,
                plan=canonicalize_verified_result_forms(
                    reconciliation.plan,
                    result_form_events,
                ),
                result_form_events=result_form_events,
            )
        input_closure_issues = verify_functional_input_closures(
            reconciliation,
            catalog=functional_catalog,
            diagnostic=base.diagnostic,
        )
        runtime_form_issues = (
            *result_form_issues,
            *input_closure_issues,
        )
        if runtime_form_issues:
            goal_verification_issues = (
                *base.goal_verification_issues,
                *runtime_form_issues,
            )
            result_form_retry = build_planner_retry_state(
                attempt=attempt,
                errors=errors,
                effective_draft=base.effective_draft,
                normalized_draft=base.normalized_draft,
                validation_report=base.validation_report,
                normalization_report=base.normalization_report,
                resolution_report=base.resolution_report,
                diagnostic=base.diagnostic,
                handle_registry=handle_registry,
                goal_verification_issues=goal_verification_issues,
                guidance_resolver=RepairGuidanceResolver(
                    inputs.family_spec,
                    inputs.method_specs,
                    handle_registry,
                ),
            )
            base = replace(
                base,
                goal_verification_issues=goal_verification_issues,
                retry_state=_retry_state_with_candidate_format(
                    result_form_retry,
                    "functional_plan",
                ),
                output=None,
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
        needs_retry = functional_retry is not None or base.retry_state is not None
        verified_call_ids = (
            self._verify_functional_call_graph(
                reconciliation,
                projected_draft=base.raw_draft,
                inputs=inputs,
                handle_registry=handle_registry,
                context=context,
                attempt=attempt,
                problem_payload=problem_payload,
                authoritative_output_types=authoritative_output_types,
                projected_state_writes=projected_state_writes,
                projected_function_arg_bindings=(
                    projected_function_arg_bindings
                ),
            )
            if needs_retry
            else set()
        )
        retry_state = _functional_runtime_retry_state(
            functional_retry or base.retry_state,
            runtime_retry_state=(
                base.retry_state if functional_retry is not None else None
            ),
            plan=reconciliation.plan,
            reconciliation=reconciliation,
            diagnostic=base.diagnostic,
            verified_call_ids=verified_call_ids,
            functional_catalog=functional_catalog.contextualized(
                FunctionalSemanticIndex.from_context(
                    planner_state_context,
                    handle_registry=handle_registry,
                )
            ),
            semantic_index=FunctionalSemanticIndex.from_context(
                planner_state_context,
                handle_registry=handle_registry,
            ),
        )
        enriched = replace(
            base,
            retry_state=retry_state,
            functional_plan=reconciliation.plan,
            functional_validation_report=validation_report,
            functional_reconciliation=reconciliation,
            planner_state_context=None,
            # A partial projection exists only to diagnose independent calls
            # and compute the stable graph. It is never a complete planner
            # candidate, even when its executable subset happens to run.
            output=(None if reconciliation.issues else base.output),
        )
        return _with_planner_state_context(
            enriched,
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
        )

    def _verify_functional_call_graph(
        self,
        reconciliation: FunctionalPlanReconciliationResult,
        *,
        projected_draft: StepIntentDraft | None,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        problem_payload: dict[str, Any] | None,
        authoritative_output_types: dict[str, str],
        projected_state_writes: tuple[ProjectedStateWrite, ...],
        projected_function_arg_bindings: tuple[
            ProjectedFunctionArgBinding, ...
        ],
    ) -> set[str]:
        if projected_draft is None:
            return set()
        valid_calls = {
            item.call_id
            for item in reconciliation.call_reports
            if item.status == "valid"
        }
        projection = {
            item.call_id: item.step_ids
            for item in reconciliation.projection_map
        }
        stable: set[str] = set()
        for call in reconciliation.plan.calls:
            if call.call_id not in valid_calls:
                continue
            dependencies = set(
                reconciliation.dependency_graph.get(call.call_id, ())
            )
            if not dependencies <= stable:
                continue
            closure = _functional_dependency_closure(
                call.call_id,
                reconciliation.dependency_graph,
            )
            step_ids = {
                step_id
                for call_id in closure
                for step_id in projection.get(call_id, ())
            }
            probe_draft = _draft_for_step_ids(projected_draft, step_ids)
            if not probe_draft.steps:
                continue
            try:
                probe = self.replay_draft(
                    probe_draft,
                    inputs=inputs,
                    handle_registry=handle_registry,
                    context=context,
                    attempt=attempt,
                    merge_previous_prefix=False,
                    problem_payload=problem_payload,
                    partial_candidate=True,
                    authoritative_output_types=authoritative_output_types,
                    allow_shared_derivation_scopes=True,
                    candidate_format="functional_plan",
                    projected_state_writes=projected_state_writes,
                    projected_function_arg_bindings=(
                        projected_function_arg_bindings
                    ),
                )
            except StrategyDraftValidationError:
                continue
            accepted = {
                item.step_id
                for item in (
                    probe.diagnostic.accepted_prefix
                    if probe.diagnostic is not None
                    else ()
                )
            }
            current_steps = set(projection.get(call.call_id, ()))
            if current_steps and current_steps <= accepted:
                stable.add(call.call_id)
        return stable

    def _recover_functional_projection_graph(
        self,
        reconciliation: FunctionalPlanReconciliationResult,
        *,
        projected_candidate: StepIntentDraft,
        validation_report: StepIntentValidationReport,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        attempt: int,
        problem_payload: dict[str, Any] | None,
        planner_state_context: PlannerStateContext,
        authoritative_output_types: dict[str, str],
        projected_state_writes: tuple[ProjectedStateWrite, ...],
        projected_function_arg_bindings: tuple[
            ProjectedFunctionArgBinding, ...
        ],
    ) -> _FunctionalProjectionRecovery:
        """Verify the dependency-closed graph outside projection failures."""
        issues = list(
            _functional_projection_issues(reconciliation, validation_report)
        )
        failure_roots = {
            issue.call_id for issue in issues if issue.call_id is not None
        }
        reports: list[dict[str, Any]] = []
        verified: set[str] = set()
        blocked: set[str] = set()
        seen_root_sets: set[frozenset[str]] = set()

        while failure_roots:
            root_key = frozenset(failure_roots)
            if root_key in seen_root_sets:
                break
            seen_root_sets.add(root_key)
            blocked = _functional_dependent_closure(
                failure_roots,
                reconciliation.dependency_graph,
            )
            candidate_call_ids = {
                report.call_id
                for report in reconciliation.call_reports
                if report.status == "valid" and report.call_id not in blocked
            }
            candidate_step_ids = {
                step_id
                for item in reconciliation.projection_map
                if item.call_id in candidate_call_ids
                for step_id in item.step_ids
            }
            candidate = _draft_for_step_ids(
                projected_candidate,
                candidate_step_ids,
            )
            if not candidate.steps:
                break
            partial_draft, partial_validation = (
                StepIntentValidator().validate_json_with_report(
                    json.dumps(candidate.to_payload(), ensure_ascii=False),
                    question_goals=inputs.question_goals,
                    handle_registry=handle_registry,
                    family_spec=inputs.family_spec,
                    planner_state_context=planner_state_context,
                    partial_candidate=True,
                    allow_shared_derivation_scopes=True,
                    allow_internal_output_types=True,
                    projected_state_writes=projected_state_writes,
                )
            )
            reports.append(
                {
                    "excluded_root_call_ids": sorted(failure_roots),
                    "blocked_call_ids": sorted(blocked),
                    "validation": partial_validation.to_payload(),
                }
            )
            if partial_draft is not None:
                verified = self._verify_functional_call_graph(
                    reconciliation,
                    projected_draft=partial_draft,
                    inputs=inputs,
                    handle_registry=handle_registry,
                    context=context,
                    attempt=attempt,
                    problem_payload=problem_payload,
                    authoritative_output_types=authoritative_output_types,
                    projected_state_writes=projected_state_writes,
                    projected_function_arg_bindings=(
                        projected_function_arg_bindings
                    ),
                )
                break

            discovered = _functional_projection_issues(
                reconciliation,
                partial_validation,
            )
            new_roots = {
                issue.call_id
                for issue in discovered
                if issue.call_id is not None
            }
            issues.extend(discovered)
            if not new_roots - failure_roots:
                break
            failure_roots.update(new_roots)

        blocked_dependents = tuple(sorted(blocked - failure_roots))
        return _FunctionalProjectionRecovery(
            issues=_enrich_projection_issues_with_blocked_calls(
                tuple(issues),
                blocked_dependents,
            ),
            verified_call_ids=frozenset(verified),
            blocked_call_ids=blocked_dependents,
            validation_reports=tuple(reports),
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
        projected_function_arg_bindings: tuple[
            ProjectedFunctionArgBinding, ...
        ] = (),
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
            )
        except Exception as exc:
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
            projected_function_arg_bindings=projected_function_arg_bindings,
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
        goal_verification_issues = (
            ()
            if partial_candidate
            else AnswerGoalVerifier().verify(
                effective_draft,
                problem_payload=context_problem_payload,
                handle_registry=handle_registry,
                diagnostic=diagnostic,
                family_spec=inputs.family_spec,
            )
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


def _functional_projected_state_writes(
    reconciliation: FunctionalPlanReconciliationResult,
) -> tuple[ProjectedStateWrite, ...]:
    """Project typed Function/Macro returns into StepIntent validation sidecars."""
    calls_by_id = {
        call.call_id: call for call in reconciliation.effective_plan.calls
    }
    result: list[ProjectedStateWrite] = []
    for call in reconciliation.calls:
        functional_call = calls_by_id.get(call.call_id)
        for output in call.returns:
            mode: Literal["create", "transition", "value"]
            if output.write_mode == "create":
                mode = "create"
            elif output.write_mode == "transition":
                mode = "transition"
            elif output.write_mode == "value":
                mode = "value"
            else:
                raise StrategyDraftValidationError(
                    "planner_configuration_error: invalid functional return "
                    f"write mode: call={call.call_id}, return={output.return_name}, "
                    f"write_mode={output.write_mode}"
                )
            result.append(
                ProjectedStateWrite(
                    step_id=call.call_id,
                    produced_handle=output.handle,
                    state_slot_id=output.state_slot_id,
                    write_mode=mode,
                    source_state_slot_ids=output.source_state_slot_ids,
                    dependency_object_refs=output.dependency_object_refs,
                    return_name=output.return_name,
                    expected_result_form=(
                        functional_call.return_expectations.get(
                            output.return_name
                        )
                        if functional_call is not None
                        else None
                    ),
                    transition_kind=output.transition_kind,
                    previous_write_step_id=output.previous_write_step_id,
                    lineage=output.lineage,
                )
            )
    return tuple(result)


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


def _functional_projected_arg_bindings(
    reconciliation: FunctionalPlanReconciliationResult,
    *,
    catalog: FunctionalCapabilityCatalog,
) -> tuple[ProjectedFunctionArgBinding, ...]:
    """Preserve LLM-selected public args and explicit auto-arg overrides.

    Reconciliation also contains auto, mechanical and context-closure args.
    Those remain owned by their declared compiler primitives and must not leak
    into this exact-binding sidecar. Optional public args are retained when the
    wire plan explicitly supplied them.
    """
    calls_by_id = {call.call_id: call for call in reconciliation.plan.calls}
    selected_args_by_call: dict[str, frozenset[str]] = {}
    for call in reconciliation.calls:
        wire_call = calls_by_id.get(call.call_id)
        capability = catalog.get(call.capability_id)
        if wire_call is None or capability is None:
            selected_args_by_call[call.call_id] = frozenset()
            continue
        public_args = {
            arg.name
            for arg in capability.args
            if arg.llm_mode in {"explicit", "optional"}
        }
        explicit_auto_overrides = {
            arg.name
            for arg in capability.auto_args
            if arg.name in wire_call.args
        }
        selected_args_by_call[call.call_id] = frozenset(
            (public_args | explicit_auto_overrides) & set(wire_call.args)
        )
    return tuple(
        ProjectedFunctionArgBinding(
            step_id=call.call_id,
            arg_name=arg_name,
            source_handle=value.handle,
            runtime_type=value.runtime_type,
            state_slot_id=value.state_slot_id,
            object_ref=value.object_ref,
        )
        for call in reconciliation.calls
        for arg_name, values in call.resolved_args.items()
        if arg_name in selected_args_by_call.get(call.call_id, ())
        for value in values
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
    repair_instruction = (
        retry_state.repair_instruction
        if retry_state is not None
        else "请根据 errors 修复并重新输出完整 StepIntent JSON。不要输出 patch。"
    )
    payload = StepIntentRepairAttempt(
        attempt=replay.attempt,
        effective_draft=effective.to_payload() if effective is not None else None,
        diagnostic=diagnostic,
        repair_summary=repair_summary,
        planner_retry_state=retry_state,
        repair_instruction=repair_instruction,
        errors=replay.errors,
    ).to_payload()
    if replay.planner_state_context is not None:
        context = replay.planner_state_context
        payload["planner_state_context_ref"] = {
            "context_id": context.manifest.context_id,
            "parent_context_id": context.manifest.parent_context_id,
            "schema_version": context.manifest.schema_version,
        }
        payload["context_retry_memory"] = context.state.retry_memory.to_payload()
        if retry_state is not None:
            payload["context_derived_retry_state"] = retry_state.to_payload()
    return payload


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


def _functional_projection_issues(
    reconciliation: FunctionalPlanReconciliationResult,
    validation_report: StepIntentValidationReport,
) -> tuple[FunctionalPlanIssue, ...]:
    step_to_call = {
        step_id: item.call_id
        for item in reconciliation.projection_map
        for step_id in item.step_ids
    }
    call_scopes = {
        call.call_id: scope.scope_id
        for scope in reconciliation.plan.scopes
        for call in scope.calls
    }
    issues: list[FunctionalPlanIssue] = list(reconciliation.issues)
    for message in validation_report.errors:
        matched = sorted(
            (
                (position, call_id, step_id)
                for step_id, call_id in step_to_call.items()
                if (position := message.rfind(step_id)) >= 0
            ),
            key=lambda item: item[0],
        )
        call_id = matched[-1][1] if matched else None
        issues.append(
            FunctionalPlanIssue(
                layer="functional_reconciliation",
                code="functional.projection_invalid",
                message=message,
                call_id=call_id,
                scope_id=call_scopes.get(call_id) if call_id is not None else None,
                details={
                    "projected_step_id": matched[-1][2] if matched else None,
                    "validation_error": message,
                },
            )
        )
    if not issues:
        issues.append(
            FunctionalPlanIssue(
                layer="functional_reconciliation",
                code="functional.projection_invalid",
                message="FunctionalPlan projection produced invalid canonical StepIntent",
            )
        )
    result: dict[tuple[Any, ...], FunctionalPlanIssue] = {}
    for issue in issues:
        key = (
            issue.layer,
            issue.code,
            issue.call_id,
            issue.scope_id,
            issue.message,
        )
        result.setdefault(key, issue)
    return tuple(result.values())


def _enrich_projection_issues_with_blocked_calls(
    issues: tuple[FunctionalPlanIssue, ...],
    blocked_call_ids: tuple[str, ...],
) -> tuple[FunctionalPlanIssue, ...]:
    unique: dict[tuple[Any, ...], FunctionalPlanIssue] = {}
    for issue in issues:
        key = (
            issue.layer,
            issue.code,
            issue.call_id,
            issue.scope_id,
            issue.message,
        )
        unique.setdefault(key, issue)
    issues = tuple(unique.values())
    if not blocked_call_ids:
        return issues
    return tuple(
        replace(
            issue,
            details={
                **dict(issue.details or {}),
                "blocked_call_ids": list(blocked_call_ids),
            },
        )
        if issue.call_id is not None
        else issue
        for issue in issues
    )


def _functional_projection_retry_state(
    *,
    attempt: int,
    reconciliation: FunctionalPlanReconciliationResult,
    validation_report: StepIntentValidationReport,
    previous_attempts: list[Any],
    recovery: _FunctionalProjectionRecovery | None = None,
) -> PlannerRetryState:
    """Keep Functional graph memory when its StepIntent bridge is invalid."""
    issues = (
        recovery.issues
        if recovery is not None
        else _functional_projection_issues(reconciliation, validation_report)
    )
    repair_call_ids = _repair_call_ids_from_functional_issues(issues)
    previous = latest_functional_retry_state(previous_attempts)
    previous_stable = (
        previous.get("stable_candidate_calls", ())
        if isinstance(previous, dict)
        else ()
    )
    current_calls = {
        call.call_id: (scope.scope_id, call)
        for scope in reconciliation.plan.scopes
        for call in scope.calls
    }
    previous_stable_by_id = {
        call_id: call
        for entry in previous_stable
        if isinstance(entry, dict)
        for call in (entry.get("call"),)
        if isinstance(call, dict)
        for call_id in (call.get("call_id"),)
        if isinstance(call_id, str)
    }
    eligible_call_ids = set(
        recovery.verified_call_ids if recovery is not None else ()
    )
    eligible_call_ids.update(
        call_id
        for call_id, previous_call in previous_stable_by_id.items()
        if call_id in current_calls
        and current_calls[call_id][1].to_payload() == previous_call
    )
    eligible_call_ids.difference_update(repair_call_ids)
    stable_call_ids: set[str] = set()
    for call in reconciliation.plan.calls:
        if call.call_id not in eligible_call_ids:
            continue
        dependencies = set(
            reconciliation.dependency_graph.get(call.call_id, ())
        )
        if dependencies <= stable_call_ids:
            stable_call_ids.add(call.call_id)
    stable_candidate_calls = tuple(
        {
            "scope_id": current_calls[call.call_id][0],
            "call": call.to_payload(),
        }
        for call in reconciliation.plan.calls
        if call.call_id in stable_call_ids
    )
    replay_report: dict[str, Any] = {
        "reconciliation": reconciliation.to_payload(),
        "projection_validation": validation_report.to_payload(),
    }
    if recovery is not None:
        replay_report["independent_graph_verification"] = recovery.to_payload()
    retry_state = _functional_retry_state(
        attempt=attempt,
        issues=issues,
        baseline_candidate=reconciliation.plan.to_payload(),
        errors=(),
        replay_report=replay_report,
        repair_call_ids=repair_call_ids,
    )
    return replace(
        retry_state,
        stable_candidate_prefix=stable_candidate_calls,
        stable_candidate_calls=stable_candidate_calls,
        preserve_policy=("preserve_graph" if stable_candidate_calls else "none"),
        repair_instruction=functional_repair_instruction(
            stable_candidate_calls=stable_candidate_calls,
            repair_call_ids=repair_call_ids,
            issue_count=len(issues),
        ),
    )


def _functional_runtime_retry_state(
    retry_state: PlannerRetryState | None,
    *,
    runtime_retry_state: PlannerRetryState | None = None,
    plan: FunctionalPlan,
    reconciliation: FunctionalPlanReconciliationResult,
    diagnostic: StepIntentExecutionDiagnostic | None,
    verified_call_ids: set[str] | None = None,
    functional_catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> PlannerRetryState | None:
    if retry_state is None and runtime_retry_state is None:
        return None
    retry_state = retry_state or runtime_retry_state
    assert retry_state is not None
    accepted_step_ids = {
        item.step_id
        for item in (diagnostic.accepted_prefix if diagnostic is not None else ())
    }
    projected_verified = (
        verified_call_ids
        if verified_call_ids is not None
        else {
            item.call_id
            for item in reconciliation.projection_map
            if item.step_ids and set(item.step_ids) <= accepted_step_ids
        }
    )
    runtime_issues = (
        runtime_retry_state.issues
        if runtime_retry_state is not None
        else retry_state.issues
    )
    runtime_invalid_call_ids = {
        issue.step_id
        for issue in runtime_issues
        if issue.step_id is not None
    }
    provenance_repair_roots = _runtime_provenance_repair_roots(
        runtime_issues,
        diagnostic=diagnostic,
    )
    # Reconciliation can identify an earlier invalid producer than the call
    # carrying the visible error (for example, a locus with the wrong object
    # identity). Never freeze that structured repair root merely because its
    # isolated runtime trial succeeded.
    runtime_invalid_call_ids.update(retry_state.repair_call_ids)
    runtime_invalid_call_ids.update(provenance_repair_roots)
    runtime_invalid_call_ids.update(
        blocker.step_id
        for blocker in (
            diagnostic.blockers if diagnostic is not None else ()
        )
    )
    stable_call_ids: set[str] = set()
    for call in plan.calls:
        if (
            call.call_id not in projected_verified
            or call.call_id in runtime_invalid_call_ids
        ):
            continue
        dependencies = set(reconciliation.dependency_graph.get(call.call_id, ()))
        if dependencies <= stable_call_ids:
            stable_call_ids.add(call.call_id)
    stable_candidate_calls = tuple(
        {"scope_id": scope.scope_id, "call": call.to_payload()}
        for scope in plan.scopes
        for call in scope.calls
        if call.call_id in stable_call_ids
    )
    actionable_runtime_issues = tuple(
        issue
        for issue in runtime_issues
        if issue.step_id not in stable_call_ids
        or issue.step_id in runtime_invalid_call_ids
    )
    issues = _unique_retry_issues(
        (*retry_state.issues, *actionable_runtime_issues)
    )
    issues = _enrich_functional_retry_issues(
        issues,
        plan=plan,
        reconciliation=reconciliation,
        catalog=functional_catalog,
        semantic_index=semantic_index,
    )
    repair_call_ids = tuple(
        dict.fromkeys(
            (
                *retry_state.repair_call_ids,
                *provenance_repair_roots,
                *(
                    issue.step_id
                    for issue in actionable_runtime_issues
                    if issue.step_id is not None
                ),
            )
        )
    )
    repair_call_ids = tuple(
        call_id
        for call_id in repair_call_ids
        if call_id not in stable_call_ids or call_id in runtime_invalid_call_ids
    )
    repair_suffix_start = dict(retry_state.repair_suffix_start or {})
    if repair_suffix_start.get("step_id") is not None:
        repair_suffix_start["call_id"] = repair_suffix_start["step_id"]
    return replace(
        retry_state,
        candidate_format="functional_plan",
        baseline_candidate=plan.to_payload(),
        stable_candidate_prefix=stable_candidate_calls,
        stable_candidate_calls=stable_candidate_calls,
        repair_call_ids=repair_call_ids,
        issues=issues,
        preserve_policy=("preserve_graph" if stable_candidate_calls else "none"),
        repair_suffix_start=repair_suffix_start or None,
        repair_instruction=functional_repair_instruction(
            stable_candidate_calls=stable_candidate_calls,
            repair_call_ids=repair_call_ids,
            issue_count=len(issues),
        ),
    )


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
    result: list[PlannerRetryIssue] = []
    for issue in issues:
        call = calls.get(issue.step_id or "")
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
    return initial_planner_state_context(
        inputs,
        problem_payload=context_problem_payload,
        handle_registry=handle_registry,
        attempt=attempt,
        parent_context_id=_parent_context_id_from_attempts(previous_attempts),
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
