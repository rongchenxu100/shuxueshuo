"""Strategy Planner 的 Runtime GenericPlanner 实现。

StrategyPlanner 不直接计算答案。它只负责把 recorded 或真实 LLM 产出的
FunctionalPlan 编译成 ``PlannerOutput``，后续仍由 Orchestrator 执行 method、
校验 checks 并收集 QuestionGoal。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalog,
    ProblemPlanningBindingCatalogBuilder,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityError,
)
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    ScopedFunctionalGoalRetryRunResult,
    ScopedFunctionalGoalRetryService,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.functional_few_shots import (
    FunctionalFewShotSelectionMode,
    default_scope_native_functional_plan_fixture_dir,
    load_functional_plan_fixture,
)
from shuxueshuo_server.solver.runtime.functional_repair_feedback import (
    CapabilityRepairFeedbackProviderError,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.llm_clients import (
    LLMPlannerClient,
    LLMProviderResponseError,
)
from shuxueshuo_server.solver.runtime.models import PlannerOutput
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
    latest_functional_retry_graph_checkpoint,
    validate_checkpoint_manifest,
)
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.session import (
    PlannerExecutionError,
    StructuredSolveError,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StrategyDraftValidationError,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
    repair_attempt_payload_from_replay,
    transactional_repair_attempt_payload_from_replay,
)
from shuxueshuo_server.solver.runtime.planner_failure_classification import (
    is_planner_configuration_failure_code,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)


StrategyPlannerMode = Literal["recorded", "deepseek"]


@dataclass(frozen=True)
class StrategyPlannerArtifacts:
    """StrategyPlanner 最近一次规划的中间产物。

    测试和 debug 可以读取这些字段确认 recorded/deepseek 都经过了同一套后半段
    编译链路，而不是直接 mock PlannerOutput。
    """

    payload: dict[str, Any] | None = None
    prompt: StrategyPrompt | None = None
    raw_response: str | None = None
    planner_inputs: PlannerInputs | None = None
    validation_report: object | None = None
    retry_replay_result: PlannerRetryReplayResult | None = None
    output: PlannerOutput | None = None
    problem_authority: VerifiedPlannerProblemAuthority | None = None
    problem_binding_catalog: ProblemPlanningBindingCatalog | None = None
    initial_planner_state_context: PlannerStateContext | None = None
    scoped_retry_result: ScopedFunctionalGoalRetryRunResult | None = None
    verified_execution: object | None = None


class StrategyPlanner:
    """把 recorded/deepseek FunctionalPlan 编译成 PlannerOutput。"""

    def __init__(
        self,
        context: RuntimeContext,
        *,
        problem_authority: VerifiedPlannerProblemAuthority,
        mode: StrategyPlannerMode = "recorded",
        client: LLMPlannerClient | None = None,
        payload_builder: StrategyPayloadBuilder | None = None,
        prompt_renderer: StrategyPromptRenderer | None = None,
        functional_plan_fixture_dir: Path | str | None = None,
        scoped_functional_plan_fixture_dir: Path | str | None = None,
    ) -> None:
        if problem_authority is None:
            raise ProblemBundleAuthorityError(
                "planner.problem_bundle_required",
                "$.problem_authority",
                "Strategy planning requires VerifiedSolverProblemBundle authority",
            )
        self.context = context
        self.problem_authority = problem_authority
        self.mode = mode
        self.client = client
        self.payload_builder = payload_builder or StrategyPayloadBuilder()
        self.prompt_renderer = prompt_renderer or StrategyPromptRenderer()
        self.functional_plan_fixture_dir = (
            Path(functional_plan_fixture_dir)
            if functional_plan_fixture_dir is not None
            else default_scope_native_functional_plan_fixture_dir()
        )
        self.scoped_functional_plan_fixture_dir = (
            Path(scoped_functional_plan_fixture_dir)
            if scoped_functional_plan_fixture_dir is not None
            else (
                repo_root(Path(__file__))
                / "internal"
                / "functional-plan-v2-fixtures"
            )
        )
        self.artifacts = StrategyPlannerArtifacts()

    @property
    def last_payload(self) -> dict[str, Any] | None:
        """兼容 Orchestrator debug 的最近一次 prompt payload。"""
        return self.artifacts.payload

    @property
    def last_prompt(self) -> StrategyPrompt | None:
        """兼容 Orchestrator debug 的最近一次 prompt。"""
        return self.artifacts.prompt

    @property
    def last_raw_response(self) -> str | None:
        """兼容 Orchestrator debug 的最近一次 raw LLM/recorded 输出。"""
        return self.artifacts.raw_response

    @property
    def last_validation_report(self) -> object | None:
        """最近一次 FunctionalPlan validation report。"""
        return self.artifacts.validation_report

    @property
    def last_output(self) -> PlannerOutput | None:
        """兼容 Orchestrator debug 的最近一次 PlannerOutput。"""
        return self.artifacts.output

    def plan(self, inputs: PlannerInputs) -> PlannerOutput:
        """Legacy v1 debug entry; production uses :meth:`run_scoped`."""
        (
            problem_payload,
            handle_registry,
            planner_state_context,
            retry_checkpoint,
            problem_binding_catalog,
        ) = self._prepare_problem_authority(inputs)
        payload = self.payload_builder.build(
            inputs,
            problem_payload=problem_payload,
            planner_state_context=planner_state_context,
            problem_planning_context=self.problem_authority.planning_context,
            problem_binding_catalog=problem_binding_catalog,
        )
        prompt = self.prompt_renderer.render(payload)
        if self.mode == "recorded":
            raw_response = json.dumps(
                load_functional_plan_fixture(
                    inputs.problem_id,
                    fixture_dir=self.functional_plan_fixture_dir,
                ),
                ensure_ascii=False,
            )
            replay_result = self._replay_functional_raw_json(
                raw_response,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
                planner_state_context=planner_state_context,
                retry_checkpoint=retry_checkpoint,
                problem_binding_catalog=problem_binding_catalog,
            )
        elif self.mode == "deepseek":
            raw_response, replay_result = (
                self._deepseek_functional_replay(
                    inputs,
                    payload=payload,
                    prompt=prompt,
                    problem_payload=problem_payload,
                    handle_registry=handle_registry,
                    planner_state_context=planner_state_context,
                    retry_checkpoint=retry_checkpoint,
                    problem_binding_catalog=problem_binding_catalog,
                )
            )
        else:
            raise StrategyDraftValidationError(f"unknown strategy planner mode: {self.mode}")
        validation_report = replay_result.functional_validation_report
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            planner_inputs=inputs,
            validation_report=validation_report,
            retry_replay_result=replay_result,
            problem_authority=self.problem_authority,
            problem_binding_catalog=problem_binding_catalog,
            initial_planner_state_context=planner_state_context,
        )
        output = replay_result.output
        goal_issue = _goal_verification_issue(replay_result)
        if goal_issue is not None:
            self._capture(
                payload=payload,
                prompt=prompt,
                raw_response=raw_response,
                planner_inputs=inputs,
                validation_report=validation_report,
                retry_replay_result=replay_result,
                output=output,
                problem_binding_catalog=problem_binding_catalog,
                initial_planner_state_context=planner_state_context,
            )
            raise _functional_planner_execution_error(
                replay_result,
                primary_issue=goal_issue,
            )
        if output is None:
            self._capture(
                payload=payload,
                prompt=prompt,
                raw_response=raw_response,
                planner_inputs=inputs,
                validation_report=validation_report,
                retry_replay_result=replay_result,
                output=None,
                problem_binding_catalog=problem_binding_catalog,
                initial_planner_state_context=planner_state_context,
            )
            blocker = replay_result.diagnostic.first_blocker if replay_result.diagnostic else None
            raise _functional_planner_execution_error(
                replay_result,
                blocker=blocker,
            )
        self._capture(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            planner_inputs=inputs,
            validation_report=validation_report,
            retry_replay_result=replay_result,
            output=output,
            problem_binding_catalog=problem_binding_catalog,
            initial_planner_state_context=planner_state_context,
        )
        return output

    def run_scoped(
        self,
        inputs: PlannerInputs,
        *,
        max_attempts: int = 3,
    ) -> ScopedFunctionalGoalRetryRunResult:
        """Run the production content/v2 -> Goal retry -> checkpoint v3 path."""

        (
            problem_payload,
            handle_registry,
            planner_state_context,
            problem_binding_catalog,
        ) = self._prepare_scope_native_problem_authority(inputs)
        if self.mode == "recorded":
            client: LLMPlannerClient = _RecordedScopedFunctionalClient(
                self._recorded_scoped_content(inputs)
            )
        elif self.mode == "deepseek":
            if self.client is None:
                raise StrategyDraftValidationError(
                    "deepseek strategy planner requires client"
                )
            client = self.client
        else:
            raise StrategyDraftValidationError(
                f"unknown strategy planner mode: {self.mode}"
            )

        run_result = ScopedFunctionalGoalRetryService(
            client,
            payload_builder=self.payload_builder,
            prompt_renderer=self.prompt_renderer,
        ).run(
            inputs=inputs,
            planning_context=self.problem_authority.planning_context,
            problem_binding_catalog=problem_binding_catalog,
            handle_registry=handle_registry,
            runtime_context=self.context,
            planner_state_context=planner_state_context,
            problem_payload=problem_payload,
            max_attempts=max_attempts,
        )
        representative = run_result.attempts[-1] if run_result.attempts else None
        replay = (
            run_result.final_execution.replay
            if run_result.final_execution is not None
            else None
        )
        self.artifacts = StrategyPlannerArtifacts(
            payload=(
                dict(representative.payload)
                if representative is not None
                else None
            ),
            prompt=(representative.prompt if representative is not None else None),
            raw_response=(
                representative.raw_response
                if representative is not None
                else None
            ),
            planner_inputs=inputs,
            validation_report=(
                representative.content_validation_report
                if representative is not None
                else None
            ),
            retry_replay_result=replay,
            output=(replay.output if replay is not None else None),
            problem_authority=self.problem_authority,
            problem_binding_catalog=problem_binding_catalog,
            initial_planner_state_context=planner_state_context,
            scoped_retry_result=run_result,
            verified_execution=run_result.verified_execution,
        )
        return run_result

    def _recorded_scoped_content(self, inputs: PlannerInputs) -> str:
        path = (
            self.scoped_functional_plan_fixture_dir
            / f"{inputs.problem_id}.functional-plan.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
            payload
        )
        if plan is None or not report.ok:
            first = report.first_issue
            raise StrategyDraftValidationError(
                "planner.recorded_scoped_fixture_invalid: "
                + (
                    f"{first.code}: {first.message}"
                    if first is not None
                    else str(path)
                )
            )
        content = functional_plan_content_from_plan(
            plan,
            frame=FunctionalPlanAuthorityFrame.from_planning_context(
                self.problem_authority.planning_context
            ),
        )
        return json.dumps(content.to_payload(), ensure_ascii=False)

    def repair_attempt_payload(
        self,
        *,
        attempt: int,
        errors: list[str],
    ) -> dict[str, Any] | None:
        """生成下一轮 previous_attempts 可携带的 repair context。"""
        replay = self.artifacts.retry_replay_result
        if (
            replay is not None
            and replay.state_observation_authority == "transactional"
            and replay.transactional_attempt_result is not None
            and errors
            and self.artifacts.planner_inputs is not None
        ):
            problem_payload = problem_to_llm_payload(
                self.problem_authority.bundle.build_solver_problem()
            )
            handle_registry = CanonicalHandleRegistry.from_problem_payload(
                problem_payload
            )
            return self._with_functional_few_shot_selection(
                transactional_repair_attempt_payload_from_replay(
                    replay,
                    attempt=attempt,
                    errors=tuple(errors),
                    inputs=self.artifacts.planner_inputs,
                    handle_registry=handle_registry,
                    problem_payload=problem_payload,
                )
            )
        if (
            replay is not None
            and replay.retry_state is not None
        ):
            return self._with_functional_few_shot_selection(
                repair_attempt_payload_from_replay(replay)
            )
        if _goal_verification_issue(self.artifacts.retry_replay_result) is not None:
            return self._with_functional_few_shot_selection(
                repair_attempt_payload_from_replay(
                    self.artifacts.retry_replay_result
                )
            )
        return None

    def _with_functional_few_shot_selection(
        self,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Carry the internal selection across retries without prompting it."""
        if payload is None:
            return payload
        planner_payload = self.artifacts.payload
        selection = (
            planner_payload.get("functional_few_shot_selection")
            if isinstance(planner_payload, dict)
            else None
        )
        if isinstance(selection, dict):
            payload["functional_few_shot_selection"] = dict(selection)
        return payload

    def _replay_functional_raw_json(
        self,
        raw_response: str,
        *,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
        problem_payload: dict[str, Any],
        planner_state_context: PlannerStateContext,
        retry_checkpoint: FunctionalRetryGraphCheckpoint | None,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
    ) -> PlannerRetryReplayResult:
        return PlannerRetryReplayService(
            functional_transaction_mode="context_authoritative",
            functional_symbolic_closure_mode="authoritative",
        ).replay_functional_raw_json(
            raw_response,
            inputs=inputs,
            handle_registry=handle_registry,
            context=self.context,
            attempt=len(inputs.previous_errors),
            errors=(),
            problem_payload=problem_payload,
            planner_state_context=planner_state_context,
            retry_checkpoint=retry_checkpoint,
            problem_binding_catalog=problem_binding_catalog,
        )

    def _deepseek_functional_replay(
        self,
        inputs: PlannerInputs,
        *,
        payload: dict[str, Any],
        prompt: StrategyPrompt,
        problem_payload: dict[str, Any],
        handle_registry: CanonicalHandleRegistry,
        planner_state_context: PlannerStateContext,
        retry_checkpoint: FunctionalRetryGraphCheckpoint | None,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
    ) -> tuple[str, PlannerRetryReplayResult]:
        """Call the strict FunctionalPlan protocol and replay its projection."""
        if self.client is None:
            raise StrategyDraftValidationError("deepseek strategy planner requires client")
        try:
            raw_response = self.client.complete(
                {
                    "messages": prompt.messages,
                    "family_id": inputs.family_spec.family_id,
                    "problem_id": inputs.problem_id,
                    "planner_protocol": "functional_plan/v1",
                    "planner_attempt": len(inputs.previous_errors) + 1,
                    "planner_payload": payload,
                }
            )
        except LLMProviderResponseError as exc:
            self.artifacts = StrategyPlannerArtifacts(
                payload=payload,
                prompt=prompt,
                raw_response="",
                planner_inputs=inputs,
            )
            raise PlannerExecutionError(
                StructuredSolveError(
                    stage="provider",
                    code=exc.code,
                    message=str(exc),
                    retryable=False,
                    details={
                        "provider_attempts": list(
                            getattr(
                                self.client,
                                "last_provider_attempts",
                                (),
                            )
                        )
                    },
                ),
            ) from exc
        # Capture the complete LLM boundary before deterministic replay. A
        # projection invariant may fail before replay can return a report, but
        # the prompt, payload, and raw FunctionalPlan must still be debuggable.
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            planner_inputs=inputs,
        )
        try:
            replay = self._replay_functional_raw_json(
                raw_response,
                inputs=inputs,
                handle_registry=handle_registry,
                problem_payload=problem_payload,
                planner_state_context=planner_state_context,
                retry_checkpoint=retry_checkpoint,
                problem_binding_catalog=problem_binding_catalog,
            )
        except StrategyDraftValidationError as exc:
            raise _functional_draft_validation_error(exc) from exc
        except CapabilityRepairFeedbackProviderError as exc:
            raise PlannerExecutionError(
                StructuredSolveError(
                    stage="planner",
                    code=exc.code,
                    message=str(exc),
                    retryable=False,
                    details={
                        "exception_type": exc.__class__.__name__,
                    },
                ),
                root_issues=(
                    {
                        "layer": "planner",
                        "code": exc.code,
                        "message": str(exc),
                        "preserve_policy": "none",
                    },
                ),
            ) from exc
        return raw_response, replay

    def _prepare_problem_authority(
        self,
        inputs: PlannerInputs,
    ) -> tuple[
        dict[str, Any],
        CanonicalHandleRegistry,
        PlannerStateContext,
        FunctionalRetryGraphCheckpoint | None,
        ProblemPlanningBindingCatalog,
    ]:
        """Pin one Bundle, PlanningContext and initial typed state snapshot."""
        bundle = self.problem_authority.bundle
        planning_context = self.problem_authority.planning_context
        if inputs.problem_id != planning_context.problem_id:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.problem_id",
                "Planner inputs do not belong to the authenticated problem",
            )
        if inputs.family_spec.family_id != planning_context.family_id:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.family_id",
                "Planner family differs from the authenticated problem",
            )
        problem_payload = problem_to_llm_payload(bundle.build_solver_problem())
        if problem_to_llm_payload(self.context.problem) != problem_payload:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.runtime_context.problem",
                "RuntimeContext was not built from the authenticated bundle",
            )
        handle_registry = CanonicalHandleRegistry.from_problem_payload(
            problem_payload
        )
        # Every attempt starts from the immutable source snapshot. Dynamic
        # committed state is restored exclusively from checkpoint v2.
        planner_state_context = initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
        )
        retry_checkpoint = latest_functional_retry_graph_checkpoint(
            inputs.previous_errors
        )
        if retry_checkpoint is not None:
            validate_checkpoint_manifest(
                retry_checkpoint,
                context=planner_state_context,
            )
        problem_binding_catalog = ProblemPlanningBindingCatalogBuilder().build(
            bundle,
            planning_context,
            planner_state_context,
            handle_registry,
            expected_token=bundle.authority_token,
        )
        return (
            problem_payload,
            handle_registry,
            planner_state_context,
            retry_checkpoint,
            problem_binding_catalog,
        )

    def _prepare_scope_native_problem_authority(
        self,
        inputs: PlannerInputs,
    ) -> tuple[
        dict[str, Any],
        CanonicalHandleRegistry,
        PlannerStateContext,
        ProblemPlanningBindingCatalog,
    ]:
        """Pin the immutable authority used by the production v2 service.

        Goal retry owns its checkpoint lifecycle internally.  In particular,
        this entry never reads the legacy call-level checkpoint carried by
        ``PlannerInputs.previous_errors``.
        """

        bundle = self.problem_authority.bundle
        planning_context = self.problem_authority.planning_context
        if inputs.problem_id != planning_context.problem_id:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.problem_id",
                "Planner inputs do not belong to the authenticated problem",
            )
        if inputs.family_spec.family_id != planning_context.family_id:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.family_id",
                "Planner family differs from the authenticated problem",
            )
        problem_payload = problem_to_llm_payload(bundle.build_solver_problem())
        if problem_to_llm_payload(self.context.problem) != problem_payload:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.runtime_context.problem",
                "RuntimeContext was not built from the authenticated bundle",
            )
        handle_registry = CanonicalHandleRegistry.from_problem_payload(
            problem_payload
        )
        planner_state_context = initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
        )
        problem_binding_catalog = ProblemPlanningBindingCatalogBuilder().build(
            bundle,
            planning_context,
            planner_state_context,
            handle_registry,
            expected_token=bundle.authority_token,
        )
        return (
            problem_payload,
            handle_registry,
            planner_state_context,
            problem_binding_catalog,
        )

    def _capture(
        self,
        *,
        payload: dict[str, Any] | None,
        prompt: StrategyPrompt | None,
        raw_response: str,
        planner_inputs: PlannerInputs,
        validation_report: object | None,
        retry_replay_result: PlannerRetryReplayResult | None,
        output: PlannerOutput | None,
        problem_binding_catalog: ProblemPlanningBindingCatalog,
        initial_planner_state_context: PlannerStateContext,
    ) -> None:
        """保存最近一次规划产物，供 Orchestrator debug 或测试读取。"""
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            planner_inputs=planner_inputs,
            validation_report=validation_report,
            retry_replay_result=retry_replay_result,
            output=output,
            problem_authority=self.problem_authority,
            problem_binding_catalog=problem_binding_catalog,
            initial_planner_state_context=initial_planner_state_context,
        )


def strategy_planner_provider(
    *,
    mode: StrategyPlannerMode = "recorded",
    client: LLMPlannerClient | None = None,
    functional_plan_fixture_dir: Path | str | None = None,
    scoped_functional_plan_fixture_dir: Path | str | None = None,
    allow_same_problem_few_shot: bool = True,
    functional_few_shot_mode: FunctionalFewShotSelectionMode | None = None,
) -> "Callable[..., StrategyPlanner]":
    """构造 Orchestrator 可用的单一 Strategy provider。"""
    from collections.abc import Callable

    def provider(
        context: RuntimeContext,
        *,
        problem_authority: VerifiedPlannerProblemAuthority | None = None,
    ) -> StrategyPlanner:
        if problem_authority is None:
            raise ProblemBundleAuthorityError(
                "planner.problem_bundle_required",
                "$.problem_authority",
                "Strategy planning requires VerifiedSolverProblemBundle authority",
            )
        payload_builder = StrategyPayloadBuilder(
            allow_same_problem_few_shot=allow_same_problem_few_shot,
            functional_few_shot_mode=functional_few_shot_mode,
        )
        return StrategyPlanner(
            context,
            problem_authority=problem_authority,
            mode=mode,
            client=client,
            payload_builder=payload_builder,
            functional_plan_fixture_dir=functional_plan_fixture_dir,
            scoped_functional_plan_fixture_dir=(
                scoped_functional_plan_fixture_dir
            ),
        )

    return provider


class _RecordedScopedFunctionalClient:
    """Deterministic content/v2 provider for local and offline production tests."""

    provider_name = "recorded"
    model = "recorded-functional-plan-content-v2"
    last_usage: dict[str, int] | None = None
    last_response_model = model
    last_provider_attempts: tuple[object, ...] = ()

    def __init__(self, raw_content: str) -> None:
        self.raw_content = raw_content
        self.requests: list[Mapping[str, Any]] = []

    def complete(self, payload: Mapping[str, Any]) -> str:
        self.requests.append(payload)
        protocol = str(payload.get("planner_protocol", ""))
        if protocol != "functional-plan-content/v2":
            raise StrategyDraftValidationError(
                "planner.recorded_scoped_fixture_requires_repair: "
                "recorded content/v2 fixture did not pass in one semantic attempt",
            )
        return self.raw_content


def _goal_verification_issue(
    replay_result: PlannerRetryReplayResult | None,
) -> Any | None:
    if replay_result is None or replay_result.retry_state is None:
        return None
    for issue in replay_result.retry_state.issues:
        if issue.layer == "goal_verification":
            return issue
    return None


def _planner_failure_message(
    replay_result: PlannerRetryReplayResult,
) -> str:
    retry_state = replay_result.retry_state
    if retry_state is not None:
        for issue in retry_state.issues:
            if issue.layer in {
                "functional_validation",
                "functional_elaboration",
                "functional_reconciliation",
            }:
                location = f" call={issue.step_id}" if issue.step_id else ""
                return (
                    "strategy_functional_plan_failed: "
                    f"{issue.code}{location}: {issue.message}"
                )
            if issue.layer == "candidate_resolution":
                location = f" step={issue.step_id}" if issue.step_id else ""
                return (
                    "strategy_candidate_resolution_failed: "
                    f"{issue.code}{location}: {issue.message}"
                )
    return (
        "strategy_candidate_resolution_failed: "
        + json.dumps(
            replay_result.diagnostic.candidate_errors
            if replay_result.diagnostic is not None
            else (),
            ensure_ascii=False,
        )
    )


def _functional_planner_execution_error(
    replay_result: PlannerRetryReplayResult,
    *,
    primary_issue: PlannerRetryIssue | None = None,
    blocker: Any | None = None,
) -> PlannerExecutionError:
    """Preserve Functional retry diagnostics across the GenericPlanner boundary."""
    issues = _deduplicated_retry_issues(replay_result)
    root_payloads = tuple(issue.to_payload() for issue in issues)
    if primary_issue is not None:
        primary = StructuredSolveError(
            stage=primary_issue.layer,
            code=primary_issue.code,
            message=primary_issue.message or _planner_failure_message(replay_result),
            retryable=not _has_configuration_failure(
                issues,
                primary_code=primary_issue.code,
            ),
            step_id=primary_issue.step_id,
            details={
                "scope_id": primary_issue.scope_id,
                "repair_target": primary_issue.repair_target,
            },
        )
    elif blocker is not None:
        blocker_code = str(blocker.code)
        planner_repairable = blocker_code.startswith(
            ("functional.", "function.", "macro.")
        )
        primary = StructuredSolveError(
            stage=str(blocker.stage),
            code=blocker_code,
            message=str(blocker.message),
            retryable=(bool(blocker.retryable) or planner_repairable)
            and not _has_configuration_failure(issues),
            step_id=blocker.step_id,
            method_id=blocker.capability_id,
            details=dict(blocker.details or {}),
        )
    elif issues:
        issue = issues[0]
        primary = StructuredSolveError(
            stage=issue.layer,
            code=issue.code,
            message=issue.message or _planner_failure_message(replay_result),
            retryable=not _has_configuration_failure(issues),
            step_id=issue.step_id,
            details={
                "scope_id": issue.scope_id,
                "repair_target": issue.repair_target,
            },
        )
    else:
        primary = StructuredSolveError(
            stage="planner",
            code="unclassified_planner_failure",
            message=_planner_failure_message(replay_result),
            retryable=True,
        )
    return PlannerExecutionError(
        primary,
        root_issues=root_payloads,
    )


def _functional_draft_validation_error(
    exc: StrategyDraftValidationError,
) -> PlannerExecutionError:
    """Type deterministic projection failures that escape replay reports."""
    message = str(exc)
    raw_code, separator, _detail = message.partition(":")
    code = raw_code.strip() if separator else "functional_projection_failed"
    if not code or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_."
        for character in code
    ):
        code = "functional_projection_failed"
    if code == "planner_configuration_error":
        stage = "planner"
        retryable = False
    elif code.startswith(
        (
            "state_transition_",
            "duplicate_state_slot_writer",
            "duplicate_point_coordinate_fact",
        )
    ):
        stage = "normalization"
        retryable = True
    elif code.startswith(("functional.", "function.", "macro.")):
        stage = "functional_reconciliation"
        retryable = True
    else:
        stage = "validation"
        retryable = True
    root_issue = {
        "layer": stage,
        "code": code,
        "message": message,
        "preserve_policy": "none",
    }
    return PlannerExecutionError(
        StructuredSolveError(
            stage=stage,
            code=code,
            message=message,
            retryable=retryable,
            details={"exception_type": exc.__class__.__name__},
        ),
        root_issues=(root_issue,),
    )


def _deduplicated_retry_issues(
    replay_result: PlannerRetryReplayResult,
) -> tuple[PlannerRetryIssue, ...]:
    retry_state = replay_result.retry_state
    if retry_state is None:
        return ()
    result: list[PlannerRetryIssue] = []
    seen: set[tuple[str, str, str | None]] = set()
    for issue in retry_state.issues:
        key = (issue.layer, issue.code, issue.step_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(issue)
    return tuple(result)


def _has_configuration_failure(
    issues: tuple[PlannerRetryIssue, ...],
    *,
    primary_code: str | None = None,
) -> bool:
    return is_planner_configuration_failure_code(primary_code) or any(
        is_planner_configuration_failure_code(issue.code) for issue in issues
    )


__all__ = [
    "StrategyPlanner",
    "StrategyPlannerArtifacts",
    "StrategyPlannerMode",
    "strategy_planner_provider",
]
