"""Recorded/live replay boundary for code-framed FunctionalPlan authoring."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalRestoredCallSeed,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanAuthority,
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanValidationReport,
    ScopedFunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.strategy_models import StrategyPrompt
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
)


@dataclass(frozen=True)
class ScopedFunctionalPlanReplayResult:
    validation_report: ScopedFunctionalPlanValidationReport
    authority: ScopedFunctionalPlanAuthority
    replay: PlannerRetryReplayResult


@dataclass(frozen=True)
class ScopedFunctionalPlanAuthoringResult:
    payload: dict[str, Any]
    prompt: StrategyPrompt
    raw_response: str
    replay_result: ScopedFunctionalPlanReplayResult


class ScopedFunctionalPlanReplayService:
    """Parse v2, prove authoring authority, then reuse the typed v1 runtime."""

    def replay_raw_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        planning_context: ProblemPlanningContext,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        planner_state_context: PlannerStateContext,
        problem_payload: dict[str, Any],
        attempt: int = 0,
        restored_seed: FunctionalRestoredCallSeed | None = None,
    ) -> ScopedFunctionalPlanReplayResult:
        scoped, validation = (
            ScopedFunctionalPlanValidator().validate_json_with_report(
                raw_response
            )
        )
        if scoped is None:
            first = validation.issues[0]
            raise ScopedFunctionalPlanError(
                first.code,
                first.path,
                first.message,
            )
        authority = ScopedFunctionalPlanAuthorityAdapter().lower(
            scoped,
            planning_context=planning_context,
            binding_catalog=problem_binding_catalog,
            capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
                inputs.family_spec,
                inputs.method_specs,
            ),
        )
        replay_service = PlannerRetryReplayService(
            functional_transaction_mode="context_authoritative",
            functional_symbolic_closure_mode="authoritative",
            legacy_call_level_checkpoint_mode=False,
        )
        prepared = replay_service.reconcile_functional_plan(
            authority.lowered_plan,
            inputs=inputs,
            handle_registry=handle_registry,
            context=context,
            attempt=attempt,
            problem_payload=problem_payload,
            planner_state_context=planner_state_context,
            problem_binding_catalog=problem_binding_catalog,
            preserve_scoped_step_identity=True,
            scoped_call_goal_bindings={
                step_id: item.consumer_goal_unit_ids
                for step_id, item in authority.step_authorities.items()
            },
            scoped_semantic_owner_scopes={
                step_id: item.semantic_owner_scope_id
                for step_id, item in authority.step_authorities.items()
            },
            canonical_plan_id=authority.plan_id,
        )
        reconciliation = prepared.functional_reconciliation
        if reconciliation is None:
            raise ScopedFunctionalPlanError(
                "functional.step_scope_authority_drift",
                "$.reconciliation",
                "v2 replay did not produce reconciliation authority",
            )
        finalized, finalization_report = authority.finalize_reconciliation(
            reconciliation
        )
        if finalized is None:
            first = finalization_report.first_issue
            assert first is not None
            raise ScopedFunctionalPlanError(
                first.code,
                first.path,
                first.message,
                issues=finalization_report.issues,
                normalizations=finalization_report.normalizations,
            )
        replay = replay_service.execute_reconciled_functional_plan(
            prepared,
            raw_plan=finalized.lowered_plan,
            parent_context=planner_state_context,
            inputs=inputs,
            handle_registry=handle_registry,
            problem_payload=problem_payload,
            runtime_context=context,
            finalized_authority=finalized,
            restored_seed=restored_seed,
        )
        return ScopedFunctionalPlanReplayResult(
            validation_report=validation,
            authority=finalized,
            replay=replay,
        )

    def replay_content_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        planning_context: ProblemPlanningContext,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        planner_state_context: PlannerStateContext,
        problem_payload: dict[str, Any],
        attempt: int = 0,
        restored_seed: FunctionalRestoredCallSeed | None = None,
    ) -> ScopedFunctionalPlanReplayResult:
        """Compile provider-authored content into the code-owned Plan tree."""

        compilation = FunctionalPlanContentCompiler().compile_json(
            raw_response,
            frame=FunctionalPlanAuthorityFrame.from_planning_context(
                planning_context
            ),
            capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
                inputs.family_spec,
                inputs.method_specs,
            ),
        )
        if compilation.plan is None:
            first = compilation.report.issues[0]
            raise ScopedFunctionalPlanError(
                first.code,
                first.path,
                first.message,
            )
        result = self.replay_raw_json(
            json.dumps(compilation.plan.to_payload(), ensure_ascii=False),
            inputs=inputs,
            planning_context=planning_context,
            problem_binding_catalog=problem_binding_catalog,
            handle_registry=handle_registry,
            context=context,
            planner_state_context=planner_state_context,
            problem_payload=problem_payload,
            attempt=attempt,
            restored_seed=restored_seed,
        )
        return ScopedFunctionalPlanReplayResult(
            validation_report=compilation.report,
            authority=result.authority,
            replay=result.replay,
        )


class ScopedFunctionalPlanAuthoringService:
    """Explicit provider boundary for code-framed FunctionalPlan content."""

    def __init__(
        self,
        client: LLMPlannerClient,
        *,
        payload_builder: StrategyPayloadBuilder | None = None,
        prompt_renderer: StrategyPromptRenderer | None = None,
        replay_service: ScopedFunctionalPlanReplayService | None = None,
    ) -> None:
        self.client = client
        self.payload_builder = payload_builder or StrategyPayloadBuilder()
        self.prompt_renderer = prompt_renderer or StrategyPromptRenderer()
        self.replay_service = replay_service or ScopedFunctionalPlanReplayService()

    def author_and_replay(
        self,
        *,
        inputs: PlannerInputs,
        planning_context: ProblemPlanningContext,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
        handle_registry: CanonicalHandleRegistry,
        context: Any,
        planner_state_context: PlannerStateContext,
        problem_payload: dict[str, Any],
    ) -> ScopedFunctionalPlanAuthoringResult:
        """Call one provider attempt, assemble its content, then replay."""

        payload = self.payload_builder.build_scoped(
            inputs,
            problem_payload=problem_payload,
            planner_state_context=planner_state_context,
            problem_planning_context=planning_context,
            problem_binding_catalog=problem_binding_catalog,
        )
        prompt = self.prompt_renderer.render_scoped(payload)
        raw_response = self.client.complete(
            {
                "messages": prompt.messages,
                "family_id": inputs.family_spec.family_id,
                "problem_id": inputs.problem_id,
                "planner_protocol": FUNCTIONAL_PLAN_CONTENT_CONTRACT,
                "planner_attempt": 1,
                "planner_payload": payload,
            }
        )
        replay_result = self.replay_service.replay_content_json(
            raw_response,
            inputs=inputs,
            planning_context=planning_context,
            problem_binding_catalog=problem_binding_catalog,
            handle_registry=handle_registry,
            context=context,
            planner_state_context=planner_state_context,
            problem_payload=problem_payload,
        )
        return ScopedFunctionalPlanAuthoringResult(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            replay_result=replay_result,
        )
