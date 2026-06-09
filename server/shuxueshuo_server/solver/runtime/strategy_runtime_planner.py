"""Strategy Planner 的 Runtime GenericPlanner 实现。

StrategyPlanner 不直接计算答案。它只负责把 recorded 或真实 LLM 产出的
StepIntentDraft 编译成 ``PlannerOutput``，后续仍由 Orchestrator 执行 method、
校验 checks 并收集 QuestionGoal。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient
from shuxueshuo_server.solver.runtime.models import PlannerOutput
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.projection import RuntimeProjection
from shuxueshuo_server.solver.runtime.recipe_compiler import RecipeTrialExecutor
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntentExecutionDiagnostic,
    StepIntentRepairAttempt,
    StepIntentScope,
    StepIntentSkippedStep,
    StepIntentDraft,
    StrategyDraftValidationError,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)
from shuxueshuo_server.solver.runtime.strategy_resolver import StepIntentCandidateResolver
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator


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
    draft: StepIntentDraft | None = None
    validation_report: object | None = None
    effective_draft: StepIntentDraft | None = None
    normalized_draft: StepIntentDraft | None = None
    normalization_report: object | None = None
    resolution_report: object | None = None
    execution_diagnostic: StepIntentExecutionDiagnostic | None = None
    output: PlannerOutput | None = None


class StrategyPlanner:
    """把 recorded/deepseek StepIntent 编译成 PlannerOutput 的 GenericPlanner。

    ``mode="recorded"`` 用固定 ``*.executable-step-intents.json`` 作为 LLM 输出
    的投影，覆盖除真实模型调用外的完整执行链路。``mode="deepseek"`` 则渲染
    prompt 并通过 ``LLMPlannerClient`` 获取 raw JSON。
    """

    def __init__(
        self,
        context: RuntimeContext,
        *,
        mode: StrategyPlannerMode = "recorded",
        client: LLMPlannerClient | None = None,
        projection: RuntimeProjection | None = None,
        payload_builder: StrategyPayloadBuilder | None = None,
        prompt_renderer: StrategyPromptRenderer | None = None,
        recorded_fixture_dir: Path | str | None = None,
    ) -> None:
        self.context = context
        self.mode = mode
        self.client = client
        self.projection = projection or RuntimeProjection(context.problem)
        self.payload_builder = payload_builder or StrategyPayloadBuilder()
        self.prompt_renderer = prompt_renderer or StrategyPromptRenderer()
        self.recorded_fixture_dir = Path(recorded_fixture_dir) if recorded_fixture_dir else _default_recorded_fixture_dir()
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
        """最近一次 StepIntent validation report。"""
        return self.artifacts.validation_report

    @property
    def last_draft(self) -> StepIntentDraft | None:
        """兼容 Orchestrator debug 的最近一次 draft；优先返回 normalize 后版本。"""
        return self.artifacts.effective_draft or self.artifacts.normalized_draft or self.artifacts.draft

    @property
    def last_raw_draft(self) -> StepIntentDraft | None:
        """最近一次 LLM/recorded 原始 StepIntentDraft。"""
        return self.artifacts.draft

    @property
    def last_effective_draft(self) -> StepIntentDraft | None:
        """最近一次用于执行诊断的 effective StepIntentDraft。"""
        return self.artifacts.effective_draft or self.artifacts.normalized_draft

    @property
    def last_output(self) -> PlannerOutput | None:
        """兼容 Orchestrator debug 的最近一次 PlannerOutput。"""
        return self.artifacts.output

    @property
    def last_normalization_report(self) -> object | None:
        """兼容测试/debug 的最近一次 normalization report。"""
        return self.artifacts.normalization_report

    @property
    def last_resolution_report(self) -> object | None:
        """兼容测试/debug 的最近一次 candidate resolution report。"""
        return self.artifacts.resolution_report

    @property
    def last_execution_diagnostic(self) -> StepIntentExecutionDiagnostic | None:
        """最近一次 execution diagnostic。"""
        return self.artifacts.execution_diagnostic

    def plan(self, inputs: PlannerInputs) -> PlannerOutput:
        """生成 PlannerOutput，但不执行 method、不收集答案。"""
        problem_payload = self.projection.to_llm_problem_payload()
        handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
        if self.mode == "recorded":
            draft = self._recorded_draft(inputs, handle_registry)
            raw_response = json.dumps(draft.to_payload(), ensure_ascii=False)
            payload: dict[str, Any] | None = None
            prompt: StrategyPrompt | None = None
        elif self.mode == "deepseek":
            payload, prompt, raw_response, draft, validation_report = self._deepseek_draft(
                inputs,
                problem_payload=problem_payload,
                handle_registry=handle_registry,
            )
        else:
            raise StrategyDraftValidationError(f"unknown strategy planner mode: {self.mode}")
        if self.mode == "recorded":
            validation_report = None

        # 先记录 raw draft，保证 normalize / resolver 失败时 Orchestrator 仍能写 debug。
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            validation_report=validation_report,
        )
        raw_draft = draft
        draft = _merge_previous_accepted_prefix(
            draft,
            previous_attempts=inputs.previous_errors,
            handle_registry=handle_registry,
            inputs=inputs,
        )
        normalized, normalization_report = StepIntentNormalizer().normalize(
            draft,
            family_spec=inputs.family_spec,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
        )
        resolution_report = StepIntentCandidateResolver().resolve(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
        )
        if not resolution_report.ok:
            diagnostic = StepIntentExecutionDiagnostic(
                ok=False,
                candidate_errors=tuple(resolution_report.errors),
                skipped_steps=tuple(
                    StepIntentSkippedStep(
                        step_id=step.step_id,
                        scope_id=step.scope_id,
                        reason="candidate_resolution_failed",
                    )
                    for step in normalized.steps
                ),
            )
            self._capture(
                payload=payload,
                prompt=prompt,
                raw_response=raw_response,
                draft=raw_draft,
                validation_report=validation_report,
                effective_draft=normalized,
                normalized_draft=normalized,
                normalization_report=normalization_report,
                resolution_report=resolution_report,
                execution_diagnostic=diagnostic,
                output=None,
            )
            raise StrategyDraftValidationError(
                "strategy_candidate_resolution_failed: "
                + json.dumps(resolution_report.errors, ensure_ascii=False)
            )
        output, execution_diagnostic, effective_draft = RecipeTrialExecutor().diagnose(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=self.context,
            question_goals=inputs.question_goals,
        )
        if output is None:
            self._capture(
                payload=payload,
                prompt=prompt,
                raw_response=raw_response,
                draft=raw_draft,
                validation_report=validation_report,
                effective_draft=effective_draft,
                normalized_draft=normalized,
                normalization_report=normalization_report,
                resolution_report=resolution_report,
                execution_diagnostic=execution_diagnostic,
                output=None,
            )
            blocker = execution_diagnostic.first_blocker
            if blocker is not None:
                raise StrategyDraftValidationError(
                    f"recipe_trial_step_failed: step={blocker.step_id}, "
                    f"errors={list(blocker.capability_errors)}"
                )
            raise StrategyDraftValidationError(
                "strategy_candidate_resolution_failed: "
                + json.dumps(execution_diagnostic.candidate_errors, ensure_ascii=False)
            )
        self._capture(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=raw_draft,
            validation_report=validation_report,
            effective_draft=effective_draft,
            normalized_draft=normalized,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            execution_diagnostic=execution_diagnostic,
            output=output,
        )
        return output

    def repair_attempt_payload(
        self,
        *,
        attempt: int,
        errors: list[str],
    ) -> dict[str, Any] | None:
        """生成下一轮 previous_attempts 可携带的 repair context。"""
        effective = self.last_effective_draft
        diagnostic = self.last_execution_diagnostic
        if not errors and (diagnostic is None or diagnostic.ok):
            return None
        if effective is None and diagnostic is None and not errors:
            return None
        repair = StepIntentRepairAttempt(
            attempt=attempt,
            effective_draft=effective.to_payload() if effective is not None else None,
            diagnostic=diagnostic,
            repair_instruction=_repair_instruction(diagnostic),
            errors=tuple(errors),
        )
        return repair.to_payload()

    def _recorded_draft(
        self,
        inputs: PlannerInputs,
        handle_registry: CanonicalHandleRegistry,
    ) -> StepIntentDraft:
        """从 recorded executable StepIntent fixture 读取 draft。"""
        path = self.recorded_fixture_dir / f"{inputs.problem_id}.executable-step-intents.json"
        if not path.exists():
            raise StrategyDraftValidationError(
                f"recorded_step_intents_not_found: {path}"
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        return StepIntentValidator().validate(
            payload,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )

    def _deepseek_draft(
        self,
        inputs: PlannerInputs,
        *,
        problem_payload: dict[str, Any],
        handle_registry: CanonicalHandleRegistry,
    ) -> tuple[dict[str, Any], StrategyPrompt, str, StepIntentDraft, object]:
        """调用 DeepSeek client 并解析 raw JSON。"""
        if self.client is None:
            raise StrategyDraftValidationError("deepseek strategy planner requires client")
        payload = self.payload_builder.build(inputs, problem_payload=problem_payload)
        prompt = self.prompt_renderer.render(payload)
        raw_response = self.client.complete(
            {
                "messages": prompt.messages,
                "family_id": inputs.family_spec.family_id,
                "problem_id": inputs.problem_id,
                "planner_payload": payload,
            }
        )
        draft, validation_report = StepIntentValidator().validate_json_with_report(
            raw_response,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            validation_report=validation_report,
        )
        if draft is None:
            raise StrategyDraftValidationError(
                "strategy_validation_failed: "
                + json.dumps(validation_report.errors, ensure_ascii=False)
            )
        return payload, prompt, raw_response, draft, validation_report

    def _capture(
        self,
        *,
        payload: dict[str, Any] | None,
        prompt: StrategyPrompt | None,
        raw_response: str,
        draft: StepIntentDraft,
        validation_report: object | None,
        effective_draft: StepIntentDraft | None,
        normalized_draft: StepIntentDraft,
        normalization_report: object,
        resolution_report: object,
        execution_diagnostic: StepIntentExecutionDiagnostic | None,
        output: PlannerOutput | None,
    ) -> None:
        """保存最近一次规划产物，供 Orchestrator debug 或测试读取。"""
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            validation_report=validation_report,
            effective_draft=effective_draft,
            normalized_draft=normalized_draft,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            execution_diagnostic=execution_diagnostic,
            output=output,
        )


def strategy_planner_provider(
    *,
    mode: StrategyPlannerMode = "recorded",
    client: LLMPlannerClient | None = None,
    recorded_fixture_dir: Path | str | None = None,
    allow_same_problem_few_shot: bool = True,
) -> "Callable[[RuntimeContext], StrategyPlanner]":
    """构造 Orchestrator 可用的单一 Strategy provider。"""
    from collections.abc import Callable

    def provider(context: RuntimeContext) -> StrategyPlanner:
        payload_builder = StrategyPayloadBuilder(
            allow_same_problem_few_shot=allow_same_problem_few_shot
        )
        return StrategyPlanner(
            context,
            mode=mode,
            client=client,
            payload_builder=payload_builder,
            recorded_fixture_dir=recorded_fixture_dir,
        )

    return provider


def _default_recorded_fixture_dir() -> Path:
    """返回 recorded StepIntent fixture 默认目录。"""
    return repo_root(Path(__file__)) / "internal" / "solver-fixtures"


def _merge_previous_accepted_prefix(
    draft: StepIntentDraft,
    *,
    previous_attempts: list[object],
    handle_registry: CanonicalHandleRegistry,
    inputs: PlannerInputs,
) -> StepIntentDraft:
    """把上一轮已 dry-run 通过的前缀覆盖回当前完整 draft。

    LLM 下一轮仍输出完整 JSON；这里仅保留系统已验证的 prefix，避免模型修复后续
    blocker 时改坏前序步骤。若上一轮 payload 缺少 effective_draft 或 diagnostic，
    保持当前 draft 不变。
    """
    previous = _last_previous_attempt(previous_attempts)
    if previous is None:
        return draft
    effective_payload = previous.get("effective_draft")
    diagnostic = previous.get("diagnostic")
    if not isinstance(effective_payload, dict) or not isinstance(diagnostic, dict):
        return draft
    accepted_items = diagnostic.get("accepted_prefix")
    if not isinstance(accepted_items, list) or not accepted_items:
        return draft
    accepted_ids = {
        str(item.get("step_id"))
        for item in accepted_items
        if isinstance(item, dict) and item.get("step_id")
    }
    if not accepted_ids:
        return draft
    try:
        previous_draft = StepIntentValidator().validate(
            effective_payload,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
    except Exception:
        return draft

    previous_scopes = {scope.scope_id: scope for scope in previous_draft.scopes}
    current_scopes = {scope.scope_id: scope for scope in draft.scopes}
    merged_scopes: list[StepIntentScope] = []
    emitted_scope_ids: set[str] = set()
    for current_scope in draft.scopes:
        previous_scope = previous_scopes.get(current_scope.scope_id)
        if previous_scope is None:
            merged_scopes.append(current_scope)
            emitted_scope_ids.add(current_scope.scope_id)
            continue
        frozen_prefix = []
        for step in previous_scope.steps:
            if step.step_id not in accepted_ids:
                break
            frozen_prefix.append(step)
        if not frozen_prefix:
            merged_scopes.append(current_scope)
            emitted_scope_ids.add(current_scope.scope_id)
            continue
        frozen_ids = {step.step_id for step in frozen_prefix}
        merged_steps = [
            *frozen_prefix,
            *(step for step in current_scope.steps if step.step_id not in frozen_ids),
        ]
        merged_scopes.append(
            StepIntentScope(
                scope_id=current_scope.scope_id,
                label=current_scope.label,
                steps=tuple(merged_steps),
            )
        )
        emitted_scope_ids.add(current_scope.scope_id)

    for previous_scope in previous_draft.scopes:
        if previous_scope.scope_id in emitted_scope_ids:
            continue
        frozen_steps = tuple(
            step for step in previous_scope.steps if step.step_id in accepted_ids
        )
        if frozen_steps:
            merged_scopes.append(
                StepIntentScope(
                    scope_id=previous_scope.scope_id,
                    label=previous_scope.label,
                    steps=frozen_steps,
                )
            )
    return StepIntentDraft(scopes=tuple(merged_scopes))


def _last_previous_attempt(previous_attempts: list[object]) -> dict[str, Any] | None:
    """返回最后一个包含可执行前缀信息的 rich repair context payload。"""
    for item in reversed(previous_attempts):
        if (
            isinstance(item, dict)
            and isinstance(item.get("effective_draft"), dict)
            and isinstance(item.get("diagnostic"), dict)
        ):
            return item
    return None


def _repair_instruction(diagnostic: StepIntentExecutionDiagnostic | None) -> str:
    """生成下一轮 prompt 中的 repair 指令。"""
    if diagnostic is None:
        return (
            "请根据 errors 修复并重新输出完整 StepIntent JSON。不要输出 patch，"
            "也不要引入 RuntimePath 或 expected answer。"
        )
    blocker = diagnostic.first_blocker
    accepted = [item.step_id for item in diagnostic.accepted_prefix]
    parts = [
        "请重新输出完整 StepIntent JSON；系统会保留 accepted_prefix 中已经通过 "
        "compile + dry-run 的步骤语义，不需要重写这些步骤。",
        "代码已能完成 applied_fills 中列出的补位，不要为了这些补位新增 utility step。",
    ]
    if accepted:
        parts.append("accepted_prefix=" + ",".join(accepted))
    if blocker is not None:
        parts.append(
            f"请从 blocker step `{blocker.step_id}` 开始修复后续步骤；"
            f"错误码是 `{blocker.code}`。"
        )
    return " ".join(parts)


__all__ = [
    "StrategyPlanner",
    "StrategyPlannerArtifacts",
    "StrategyPlannerMode",
    "strategy_planner_provider",
]
