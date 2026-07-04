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
from shuxueshuo_server.solver.runtime.strategy_models import (
    ExecutablePlanResolutionReport,
    StepIntentExecutionDiagnostic,
    StepIntentNormalizationReport,
    StepIntentDraft,
    StepIntentValidationReport,
    StrategyDraftValidationError,
    StrategyPrompt,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)
from shuxueshuo_server.solver.runtime.strategy_draft_merge import (
    merge_previous_accepted_prefix,
    prepare_step_intent_raw_response,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
    repair_attempt_payload_from_replay,
)
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
    retry_replay_result: PlannerRetryReplayResult | None = None
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
        replay_result = PlannerRetryReplayService().replay_draft(
            draft,
            inputs=inputs,
            handle_registry=handle_registry,
            context=self.context,
            attempt=0,
            errors=(),
            validation_report=validation_report,
        )
        output = replay_result.output
        if output is None:
            self._capture(
                payload=payload,
                prompt=prompt,
                raw_response=raw_response,
                draft=draft,
                validation_report=validation_report,
                effective_draft=replay_result.effective_draft,
                normalized_draft=replay_result.normalized_draft,
                normalization_report=replay_result.normalization_report,
                resolution_report=replay_result.resolution_report,
                execution_diagnostic=replay_result.diagnostic,
                retry_replay_result=replay_result,
                output=None,
            )
            blocker = replay_result.diagnostic.first_blocker if replay_result.diagnostic else None
            if blocker is not None:
                raise StrategyDraftValidationError(
                    f"recipe_trial_step_failed: step={blocker.step_id}, "
                    f"errors={list(blocker.capability_errors)}"
                )
            raise StrategyDraftValidationError(
                "strategy_candidate_resolution_failed: "
                + json.dumps(
                    replay_result.diagnostic.candidate_errors
                    if replay_result.diagnostic is not None
                    else (),
                    ensure_ascii=False,
                )
            )
        self._capture(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            validation_report=validation_report,
            effective_draft=replay_result.effective_draft,
            normalized_draft=replay_result.normalized_draft,
            normalization_report=replay_result.normalization_report,
            resolution_report=replay_result.resolution_report,
            execution_diagnostic=replay_result.diagnostic,
            retry_replay_result=replay_result,
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
        replay_result = PlannerRetryReplayService().replay_from_artifacts(
            attempt=attempt,
            errors=tuple(errors),
            raw_draft=self.artifacts.draft,
            effective_draft=effective,
            normalized_draft=self.artifacts.normalized_draft,
            normalization_report=(
                self.artifacts.normalization_report
                if isinstance(self.artifacts.normalization_report, StepIntentNormalizationReport)
                else None
            ),
            validation_report=(
                self.artifacts.validation_report
                if isinstance(self.artifacts.validation_report, StepIntentValidationReport)
                else None
            ),
            resolution_report=(
                self.artifacts.resolution_report
                if isinstance(self.artifacts.resolution_report, ExecutablePlanResolutionReport)
                else None
            ),
            diagnostic=diagnostic,
            output=self.artifacts.output,
        )
        return repair_attempt_payload_from_replay(replay_result)

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
        prepared_raw_response = prepare_step_intent_raw_response(
            raw_response,
            previous_attempts=inputs.previous_errors,
        )
        draft, validation_report = StepIntentValidator().validate_json_with_report(
            prepared_raw_response,
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
        retry_replay_result: PlannerRetryReplayResult | None,
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
            retry_replay_result=retry_replay_result,
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
    """兼容旧私有入口；实现已移到 retry replay 层。"""
    return merge_previous_accepted_prefix(
        draft,
        previous_attempts=previous_attempts,
        handle_registry=handle_registry,
        inputs=inputs,
    )


def _last_previous_attempt(previous_attempts: list[object]) -> dict[str, Any] | None:
    """返回最后一个包含可执行前缀信息的 rich repair context payload。"""
    for item in reversed(previous_attempts):
        if (
            isinstance(item, dict)
            and (
                isinstance(item.get("planner_retry_state"), dict)
                or (
                    isinstance(item.get("effective_draft"), dict)
                    and isinstance(item.get("diagnostic"), dict)
                )
            )
        ):
            return item
    return None


def _repair_instruction(
    diagnostic: StepIntentExecutionDiagnostic | None,
    repair_summary: dict[str, Any] | None = None,
) -> str:
    """生成下一轮 prompt 中的 repair 指令。"""
    if repair_summary is not None:
        return _repair_instruction_from_summary(repair_summary)
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
    if diagnostic.planner_insights:
        latest = diagnostic.planner_insights[-1]
        parts.append(
            "请优先根据最新 planner_insight 继续规划后续步骤："
            + json.dumps(latest.to_payload(), ensure_ascii=False)
        )
    if diagnostic.preflight_issues:
        code_fillable = [
            issue.to_payload()
            for issue in diagnostic.preflight_issues
            if issue.category == "code_fillable"
        ]
        downstream = [
            issue.to_payload()
            for issue in diagnostic.preflight_issues
            if issue.category != "code_fillable"
        ]
        if code_fillable:
            parts.append(
                "preflight 检测到这些输入代码可以临时补位；不要为它们新增 utility step："
                + json.dumps(code_fillable, ensure_ascii=False)
            )
        if downstream:
            parts.append(
                "preflight 检测到后续同源潜在问题；修复 blocker 时请一并调整这些 steps："
                + json.dumps(downstream, ensure_ascii=False)
            )
    if blocker is not None:
        parts.append(
            f"请从 blocker step `{blocker.step_id}` 开始修复后续步骤；"
            f"错误码是 `{blocker.code}`。"
        )
    return " ".join(parts)


def _repair_instruction_from_summary(summary: dict[str, Any]) -> str:
    """根据 LLM-facing repair_summary 生成短指令。"""
    parts = [
        "请优先阅读 repair_summary，再参考 effective_draft/diagnostic；重新输出完整 StepIntent JSON。",
    ]
    frozen = summary.get("frozen_prefix")
    if isinstance(frozen, list) and frozen:
        ids = [
            str(item.get("step_id"))
            for item in frozen
            if isinstance(item, dict) and item.get("step_id")
        ]
        if ids:
            parts.append("系统会保留 frozen_prefix，不要重写这些步骤：" + ",".join(ids))
    current = summary.get("current_blocker")
    if isinstance(current, dict) and current.get("step_id"):
        parts.append(
            f"请从 blocker step `{current.get('step_id')}` 开始修复后续步骤；"
            f"错误码是 `{current.get('code')}`。"
        )
    next_actions = summary.get("next_actions")
    if isinstance(next_actions, list) and next_actions:
        parts.append(
            "下一轮请执行这些修复动作："
            + json.dumps(next_actions, ensure_ascii=False)
        )
    do_not = summary.get("do_not")
    if isinstance(do_not, list) and do_not:
        parts.append(
            "必须避免："
            + json.dumps(do_not, ensure_ascii=False)
        )
    return " ".join(parts)


__all__ = [
    "StrategyPlanner",
    "StrategyPlannerArtifacts",
    "StrategyPlannerMode",
    "strategy_planner_provider",
]
