"""LLM step decomposition planner 的受控切片。

Phase 5 只让 LLM 做“步骤拆解”，不让它直接生成 MethodInvocation、ContextPath
参数映射或答案。本模块先用 ``FakeLLMPlannerClient`` 跑通协议层：

1. PlannerInputs 被压成受控 payload；
2. LLM client 返回 JSON steps；
3. AbstractStepPlanValidator 校验 JSON 结构和南开已知步骤序列；
4. AbstractStepPlanCompiler 复用当前 deterministic planner 生成真正 StepPlan。

真实 LLM API、invocation mapping 和 repair loop 都不在本阶段实现。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import StepPlan
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)


class LLMPlannerError(ValueError):
    """LLM step decomposition 失败时抛出的结构化错误。"""


class LLMPlannerClient(Protocol):
    """LLM Planner client 协议。

    首版只要求同步返回 JSON 字符串。真实 provider 后续可以在此协议外层处理模型名、
    token、重试和 tracing，但输出仍必须是可校验 JSON。
    """

    def complete(self, payload: dict[str, Any]) -> str:
        """根据受控 payload 返回 JSON 字符串。"""
        ...


@dataclass(frozen=True)
class AbstractStepPlan:
    """LLM 允许输出的抽象步骤。

    这里刻意不包含 ``inputs``、``outputs`` 或 method 参数映射。LLM 只能表达“这
    一步要解决什么”，真正可执行的 MethodInvocation 仍由 deterministic compiler
    或后续受控 InvocationResolver 生成。
    """

    step_id: str
    goal_type: str
    target_path: str
    scope_id: str
    method_intent: str


@dataclass
class PlannerAttempt:
    """一次 LLM 调用记录。"""

    payload: dict[str, Any]
    raw_response: str
    parsed_steps: list[AbstractStepPlan] = field(default_factory=list)
    error: str | None = None


@dataclass
class PlannerMemory:
    """Planner 内部工作记忆。

    该对象只记录 LLM 规划过程，不能直接写 RuntimeContext。只有 Planner 产出的
    StepPlan 通过 PlanValidator 后，才能影响后续执行。
    """

    attempts: list[PlannerAttempt] = field(default_factory=list)

    def add_attempt(self, attempt: PlannerAttempt) -> None:
        """记录一次 LLM planning attempt。"""
        self.attempts.append(attempt)


class FakeLLMPlannerClient:
    """测试用假 LLM client。

    默认返回 canonical 南开 25 的抽象步骤；测试也可以传入自定义 response，用来
    覆盖非法 JSON、重复 step、未知 intent 等失败路径。
    """

    def __init__(self, response: str | None = None) -> None:
        self.response = response
        self.payloads: list[dict[str, Any]] = []

    def complete(self, payload: dict[str, Any]) -> str:
        """保存 payload 并返回预设 JSON。"""
        self.payloads.append(payload)
        if self.response is not None:
            return self.response
        return json.dumps(
            {"steps": [step.__dict__ for step in nankai25_abstract_steps()]},
            ensure_ascii=False,
        )


class AbstractStepPlanCompiler:
    """把抽象步骤编译成当前可执行的 StepPlan。

    首版只支持 canonical 南开 25：LLM 输出必须与当前 deterministic planner 的
    step_id / goal_type / target_path / scope / method_intent 序列一致。编译时复用
    ``QuadraticPathMinimumPlannerV15`` 生成 MethodInvocation，确保 LLM 不接触参数映射。
    """

    def __init__(
        self,
        context: RuntimeContext,
        delegate: QuadraticPathMinimumPlannerV15 | None = None,
    ) -> None:
        self.context = context
        self.delegate = delegate or QuadraticPathMinimumPlannerV15()

    def compile(self, abstract_steps: list[AbstractStepPlan]) -> list[StepPlan]:
        """校验抽象步骤并返回 deterministic StepPlan。"""
        plans = self.delegate.plan(self.context)
        expected = _abstract_steps_from_plans(plans)
        if abstract_steps != expected:
            raise LLMPlannerError(
                "step decomposition validation failed: abstract steps do not match "
                "canonical nankai25 decomposition"
            )
        return plans


class LLMStepDecompositionPlanner:
    """只负责 step decomposition 的 LLM Planner。

    ``plan`` 会调用 LLM client 获取抽象步骤，然后交给 compiler 生成真实 StepPlan。
    所有错误都会写入 PlannerMemory，方便后续 repair loop 或离线分析。
    """

    def __init__(
        self,
        context: RuntimeContext,
        client: LLMPlannerClient,
        memory: PlannerMemory | None = None,
        compiler: AbstractStepPlanCompiler | None = None,
    ) -> None:
        self.context = context
        self.client = client
        self.memory = memory or PlannerMemory()
        self.compiler = compiler or AbstractStepPlanCompiler(context)

    def plan(self, inputs: PlannerInputs) -> list[StepPlan]:
        """调用 fake/LLM client 做抽象步骤拆解，再编译成 StepPlan。"""
        payload = _planner_payload(inputs)
        raw_response = self.client.complete(payload)
        attempt = PlannerAttempt(payload=payload, raw_response=raw_response)
        try:
            parsed_steps = parse_abstract_steps(raw_response)
            validate_abstract_steps(parsed_steps, inputs, self.compiler)
            attempt.parsed_steps = parsed_steps
            plans = self.compiler.compile(parsed_steps)
        except Exception as exc:
            attempt.error = str(exc)
            self.memory.add_attempt(attempt)
            raise
        self.memory.add_attempt(attempt)
        return plans


def llm_step_decomposition_planner_provider(
    client: LLMPlannerClient,
    *,
    memory: PlannerMemory | None = None,
) -> Any:
    """创建 Orchestrator 可注入的 planner provider。"""

    def provider(context: RuntimeContext) -> LLMStepDecompositionPlanner:
        return LLMStepDecompositionPlanner(context, client, memory=memory)

    return provider


def parse_abstract_steps(raw_response: str) -> list[AbstractStepPlan]:
    """解析 LLM JSON，并拒绝 schema 之外的字段。"""
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise LLMPlannerError(f"step decomposition validation failed: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LLMPlannerError("step decomposition validation failed: response must be object")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise LLMPlannerError("step decomposition validation failed: steps must be list")
    steps: list[AbstractStepPlan] = []
    allowed_keys = {"step_id", "goal_type", "target_path", "scope_id", "method_intent"}
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise LLMPlannerError(f"step decomposition validation failed: step {index} must be object")
        extra_keys = set(raw_step) - allowed_keys
        if extra_keys:
            # 这会拦住 answer / inputs / coordinates 这类越界输出。
            raise LLMPlannerError(
                f"step decomposition validation failed: unknown step fields {sorted(extra_keys)}"
            )
        missing = allowed_keys - set(raw_step)
        if missing:
            raise LLMPlannerError(
                f"step decomposition validation failed: missing step fields {sorted(missing)}"
            )
        values = {key: raw_step[key] for key in allowed_keys}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise LLMPlannerError(
                f"step decomposition validation failed: step {index} fields must be non-empty strings"
            )
        if not str(raw_step["target_path"]).startswith("$"):
            raise LLMPlannerError(
                f"step decomposition validation failed: target_path must be ContextPath"
            )
        steps.append(
            AbstractStepPlan(
                step_id=str(raw_step["step_id"]),
                goal_type=str(raw_step["goal_type"]),
                target_path=str(raw_step["target_path"]),
                scope_id=str(raw_step["scope_id"]),
                method_intent=str(raw_step["method_intent"]),
            )
        )
    return steps


def validate_abstract_steps(
    steps: list[AbstractStepPlan],
    inputs: PlannerInputs,
    compiler: AbstractStepPlanCompiler,
) -> None:
    """校验抽象步骤是否处在受控规划空间内。"""
    seen_step_ids: set[str] = set()
    scope_ids = {path.scope_id for path in inputs.context_inventory.visible_paths}
    known_targets = {path.path for path in inputs.context_inventory.visible_paths}
    known_targets.update(goal.target_path for goal in inputs.question_goals)
    known_targets.update(signal.path for signal in inputs.context_inventory.planning_signals)
    expected_steps = compiler.delegate.plan(compiler.context)
    expected_abstract = _abstract_steps_from_plans(expected_steps)
    allowed_targets = known_targets | {step.target_path for step in expected_abstract}
    allowed_intents = {step.method_intent for step in expected_abstract}
    for step in steps:
        if step.step_id in seen_step_ids:
            raise LLMPlannerError(
                f"step decomposition validation failed: duplicate step_id {step.step_id}"
            )
        seen_step_ids.add(step.step_id)
        if step.scope_id not in scope_ids:
            raise LLMPlannerError(
                f"step decomposition validation failed: unknown scope_id {step.scope_id}"
            )
        if step.target_path not in allowed_targets:
            raise LLMPlannerError(
                f"step decomposition validation failed: unknown target_path {step.target_path}"
            )
        if step.method_intent not in allowed_intents:
            raise LLMPlannerError(
                f"step decomposition validation failed: unknown method_intent {step.method_intent}"
            )


def nankai25_abstract_steps() -> list[AbstractStepPlan]:
    """返回 canonical 南开 25 的抽象步骤，用于 Fake client 和测试。"""
    # 这里不需要 RuntimeContext，因为该列表只描述当前 deterministic plan 的稳定
    # step skeleton；真正编译仍会用当前 context 调用 planner 生成 MethodInvocation。
    return [
        AbstractStepPlan("derive_D", "derive_axis_point", "$problem.points.D", "problem", "derive_axis_point"),
        AbstractStepPlan("derive_part_i_parabola", "derive_part_i_parabola", "$question.i.outputs.parabola", "i", "derive_part_i_parabola"),
        AbstractStepPlan("derive_N", "derive_point_coordinate", "$question.ii.points.N", "ii", "derive_point_coordinate"),
        AbstractStepPlan("derive_q1_m", "derive_q1_parameter", "$subquestion.ii_1.outputs.m", "ii_1", "derive_q1_parameter"),
        AbstractStepPlan("derive_q1_parabola", "derive_q1_parabola", "$subquestion.ii_1.outputs.parabola", "ii_1", "derive_q1_parabola"),
        AbstractStepPlan("derive_F", "derive_midpoint_coordinate", "$question.ii.points.F", "ii", "derive_midpoint_coordinate"),
        AbstractStepPlan("reduce_path", "reduce_two_moving_point_path", "$question.ii.outputs.path_transformation", "ii", "reduce_two_moving_point_path"),
        AbstractStepPlan("derive_straightening_candidates", "derive_broken_path_straightening_candidates", "$question.ii.outputs.straightening_candidates", "ii", "derive_broken_path_straightening_candidates"),
        AbstractStepPlan("select_straightening_candidate", "select_broken_path_straightening_candidate", "$question.ii.points.D_prime", "ii", "select_broken_path_straightening_candidate"),
        AbstractStepPlan("derive_minimum_expression", "derive_minimum_expression", "$question.ii.outputs.minimum_expression", "ii_1", "derive_minimum_expression"),
        AbstractStepPlan("derive_q2_m", "derive_q2_parameter", "$subquestion.ii_2.outputs.m", "ii_2", "derive_q2_parameter"),
        AbstractStepPlan("derive_q2_parabola", "derive_q2_parabola", "$subquestion.ii_2.outputs.parabola", "ii_2", "derive_q2_parabola"),
        AbstractStepPlan("derive_G", "derive_q2_intersection", "$question.ii.points.G", "ii_2", "derive_q2_intersection"),
    ]


def _abstract_steps_from_plans(plans: list[StepPlan]) -> list[AbstractStepPlan]:
    """把 deterministic StepPlan 压成 LLM 可输出的抽象步骤。"""
    return [
        AbstractStepPlan(
            step_id=plan.step_id,
            goal_type=plan.goal.type,
            target_path=plan.goal.target_path,
            scope_id=plan.scope,
            method_intent=plan.goal.type,
        )
        for plan in plans
    ]


def _planner_payload(inputs: PlannerInputs) -> dict[str, Any]:
    """构造给 LLM 的受控 payload，避免把完整 fixture 直接暴露给 planner。"""
    return {
        "problem_id": inputs.problem_id,
        "family_id": inputs.family_spec.family_id,
        "strategy_principles": list(inputs.family_spec.strategy_principles),
        "question_goals": [
            {
                "goal_id": goal.id,
                "answer_key": goal.answer_key,
                "target_path": goal.target_path,
                "scope_id": goal.question_id,
                "value_type": goal.value_type,
            }
            for goal in inputs.question_goals
        ],
        "planning_signals": [
            {
                "signal_type": signal.signal_type,
                "path": signal.path,
                "scope_id": signal.scope_id,
                "source_ref": signal.source_ref,
                "participants": list(signal.participants),
                "roles": dict(signal.roles),
                "reason": signal.reason,
            }
            for signal in inputs.context_inventory.planning_signals
        ],
        "visible_paths": [
            {
                "path": path.path,
                "type": path.type,
                "scope_id": path.scope_id,
                "readable_from": list(path.readable_from),
            }
            for path in inputs.context_inventory.visible_paths
        ],
        "method_candidates": [
            {
                "method_id": method.method_id,
                "solves": list(method.solves),
                "required_inputs": list(method.required_inputs),
            }
            for method in inputs.context_inventory.method_candidates
        ],
        "output_schema": {
            "steps": [
                "step_id",
                "goal_type",
                "target_path",
                "scope_id",
                "method_intent",
            ]
        },
    }
