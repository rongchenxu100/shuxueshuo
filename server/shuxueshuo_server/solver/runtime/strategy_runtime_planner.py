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
    normalized_draft: StepIntentDraft | None = None
    normalization_report: object | None = None
    resolution_report: object | None = None
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
    def last_draft(self) -> StepIntentDraft | None:
        """兼容 Orchestrator debug 的最近一次 draft；优先返回 normalize 后版本。"""
        return self.artifacts.normalized_draft or self.artifacts.draft

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
            payload, prompt, raw_response, draft = self._deepseek_draft(
                inputs,
                problem_payload=problem_payload,
                handle_registry=handle_registry,
            )
        else:
            raise StrategyDraftValidationError(f"unknown strategy planner mode: {self.mode}")

        # 先记录 raw draft，保证 normalize / resolver 失败时 Orchestrator 仍能写 debug。
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
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
            raise StrategyDraftValidationError(
                "strategy_candidate_resolution_failed: "
                + json.dumps(resolution_report.errors, ensure_ascii=False)
            )
        output = RecipeTrialExecutor().compile(
            normalized,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=self.context,
            question_goals=inputs.question_goals,
        )
        self._capture(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            normalized_draft=normalized,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            output=output,
        )
        return output

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
    ) -> tuple[dict[str, Any], StrategyPrompt, str, StepIntentDraft]:
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
        draft = StepIntentValidator().validate_json(
            raw_response,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )
        return payload, prompt, raw_response, draft

    def _capture(
        self,
        *,
        payload: dict[str, Any] | None,
        prompt: StrategyPrompt | None,
        raw_response: str,
        draft: StepIntentDraft,
        normalized_draft: StepIntentDraft,
        normalization_report: object,
        resolution_report: object,
        output: PlannerOutput,
    ) -> None:
        """保存最近一次规划产物，供 Orchestrator debug 或测试读取。"""
        self.artifacts = StrategyPlannerArtifacts(
            payload=payload,
            prompt=prompt,
            raw_response=raw_response,
            draft=draft,
            normalized_draft=normalized_draft,
            normalization_report=normalization_report,
            resolution_report=resolution_report,
            output=output,
        )


def strategy_planner_provider(
    *,
    mode: StrategyPlannerMode = "recorded",
    client: LLMPlannerClient | None = None,
    recorded_fixture_dir: Path | str | None = None,
) -> "Callable[[RuntimeContext], StrategyPlanner]":
    """构造 Orchestrator 可用的单一 Strategy provider。"""
    from collections.abc import Callable

    def provider(context: RuntimeContext) -> StrategyPlanner:
        return StrategyPlanner(
            context,
            mode=mode,
            client=client,
            recorded_fixture_dir=recorded_fixture_dir,
        )

    return provider


def _default_recorded_fixture_dir() -> Path:
    """返回 recorded StepIntent fixture 默认目录。"""
    return repo_root(Path(__file__)) / "internal" / "solver-fixtures"


__all__ = [
    "StrategyPlanner",
    "StrategyPlannerArtifacts",
    "StrategyPlannerMode",
    "strategy_planner_provider",
]
