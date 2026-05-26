"""LLM step decomposition planner 受控切片测试。"""

from __future__ import annotations

import json

import pytest

from shuxueshuo_server.solver.family import (
    DEFAULT_FAMILY_REGISTRY,
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.fixtures import load_expected_answers, load_problem_ir
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.llm_step_planner import (
    FakeLLMPlannerClient,
    LLMPlannerError,
    LLMStepDecompositionPlanner,
    PlannerMemory,
    hexi25_abstract_steps,
    llm_step_decomposition_planner_provider,
    nankai25_abstract_steps,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"
HEXI_EXPECTED = "tests/solver/expected/tj-2026-hexi-yimo-25.expected.json"


def _planner_inputs(context) -> PlannerInputs:
    """构造 LLM planner 测试所需的通用 PlannerInputs。"""
    specs = MethodSpecRegistry.load_from_code()
    inventory = ContextInventoryBuilder().build(context, specs)
    family = DEFAULT_FAMILY_REGISTRY.match(context.problem)
    assert family is not None
    return PlannerInputs(
        problem_id=context.problem.problem_id,
        family_spec=family,
        question_goals=extract_question_goals(context.problem),
        context_inventory=inventory,
        method_specs=specs,
    )


def _method_ids(plans) -> list[str]:
    """抽取 StepPlan 中展开后的 method 顺序。"""
    return [
        invocation.method_id
        for plan in plans
        for invocation in plan.invocations
    ]


def _response_with_steps(steps) -> str:
    """把 AbstractStepPlan 列表转成 fake LLM JSON response。"""
    return json.dumps(
        {"steps": [step.__dict__ for step in steps]},
        ensure_ascii=False,
    )


def test_fake_llm_decomposition_compiles_to_deterministic_method_order() -> None:
    """Fake LLM 输出抽象步骤后，应编译成当前 deterministic planner 的同一方法顺序。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    direct_context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    memory = PlannerMemory()
    planner = LLMStepDecompositionPlanner(
        context,
        FakeLLMPlannerClient(),
        memory=memory,
    )

    plans = planner.plan(_planner_inputs(context))
    direct_plans = QuadraticPathMinimumPlannerV15().plan(direct_context)

    assert _method_ids(plans) == _method_ids(direct_plans)
    assert len(memory.attempts) == 1
    assert memory.attempts[0].parsed_steps == nankai25_abstract_steps()
    assert memory.attempts[0].error is None


def test_fake_llm_decomposition_supports_hexi_weighted_family() -> None:
    """Fake LLM 应按 family_id 返回河西 weighted 的抽象步骤并完成编译。"""
    context = ContextBuilder().build(load_problem_ir(HEXI_FIXTURE))
    memory = PlannerMemory()
    planner = LLMStepDecompositionPlanner(
        context,
        FakeLLMPlannerClient(),
        memory=memory,
    )

    plans = planner.plan(_planner_inputs(context))

    assert [plan.step_id for plan in plans] == [
        step.step_id for step in hexi25_abstract_steps()
    ]
    assert memory.attempts[0].parsed_steps == hexi25_abstract_steps()
    assert memory.attempts[0].payload["family_id"] == (
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id
    )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        ("not json", "invalid JSON"),
        (
            _response_with_steps(
                [
                    nankai25_abstract_steps()[0],
                    nankai25_abstract_steps()[0],
                ]
            ),
            "duplicate step_id",
        ),
        (
            _response_with_steps(
                [
                    *nankai25_abstract_steps()[:-1],
                    type(nankai25_abstract_steps()[-1])(
                        step_id="derive_G",
                        goal_type="derive_q2_intersection",
                        target_path="$question.ii.points.G",
                        scope_id="ii_2",
                        method_intent="free_solve_answer",
                    ),
                ]
            ),
            "unknown method_intent",
        ),
        (
            json.dumps(
                {
                    "steps": [
                        {
                            **nankai25_abstract_steps()[0].__dict__,
                            "answer": ["1", "0"],
                        }
                    ]
                }
            ),
            "unknown step fields",
        ),
    ],
)
def test_llm_step_decomposition_rejects_invalid_outputs(
    response: str,
    message: str,
) -> None:
    """非法 JSON、重复步骤、未知意图和裸答案字段都不能进入 executor。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    memory = PlannerMemory()
    planner = LLMStepDecompositionPlanner(
        context,
        FakeLLMPlannerClient(response=response),
        memory=memory,
    )

    with pytest.raises(LLMPlannerError, match=message):
        planner.plan(_planner_inputs(context))

    assert len(memory.attempts) == 1
    assert memory.attempts[0].raw_response == response
    assert memory.attempts[0].error is not None


def test_orchestrator_can_run_with_injected_llm_step_planner_provider() -> None:
    """通过 provider 注入 LLM planner slice 后，南开端到端结果保持一致。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    expected = load_expected_answers(EXPECTED)
    client = FakeLLMPlannerClient()
    memory = PlannerMemory()

    result = RuntimeOrchestrator(
        planner_providers={
            QUADRATIC_PATH_MINIMUM_FAMILY.family_id:
                llm_step_decomposition_planner_provider(client, memory=memory)
        },
    ).solve(problem)

    assert result.status == "ok"
    assert result.answers == expected
    assert all(check.ok for check in result.checks)
    assert client.payloads
    payload = client.payloads[0]
    assert "planner_goals" not in payload
    assert payload["question_goals"]
    assert payload["planning_signals"]
    assert len(memory.attempts) == 1
    assert memory.attempts[0].error is None


def test_orchestrator_can_run_hexi_with_injected_llm_step_planner_provider() -> None:
    """Phase A 中 --planner llm 语义要求河西 weighted family 也能走 LLM provider。"""
    problem = load_problem_ir(HEXI_FIXTURE)
    expected = load_expected_answers(HEXI_EXPECTED)
    client = FakeLLMPlannerClient()
    memory = PlannerMemory()

    result = RuntimeOrchestrator(
        planner_providers={
            QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id:
                llm_step_decomposition_planner_provider(client, memory=memory)
        },
    ).solve(problem)

    assert result.status == "ok"
    assert result.answers == expected
    assert all(check.ok for check in result.checks)
    assert client.payloads[0]["family_id"] == (
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id
    )
    assert memory.attempts[0].parsed_steps == hexi25_abstract_steps()


def test_orchestrator_returns_failed_when_llm_decomposition_is_invalid() -> None:
    """LLM 抽象步骤非法时，Orchestrator 返回 failed，且不会产生执行 trace。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    client = FakeLLMPlannerClient(response="not json")
    memory = PlannerMemory()

    result = RuntimeOrchestrator(
        planner_providers={
            QUADRATIC_PATH_MINIMUM_FAMILY.family_id:
                llm_step_decomposition_planner_provider(client, memory=memory)
        },
    ).solve(problem)

    assert result.status == "failed"
    assert result.methods_used == []
    assert result.trace is None
    assert "step decomposition validation failed" in result.errors[0]
    assert memory.attempts[0].error is not None
