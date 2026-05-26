"""Phase 2 通用 Planner 接口测试。

当前 solver 主链路仍然直接使用南开 deterministic planner；这些测试只证明新的
PlannerInputs / GenericPlanner 形状可以承接现有 planner 输出。
"""

from __future__ import annotations

from shuxueshuo_server.solver.family import (
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner import (
    GenericPlanner,
    Nankai25DeterministicPlannerAdapter,
    PlannerInputs,
)
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)
from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
    Hexi25WeightedPathPlannerV15,
)
from shuxueshuo_server.solver.runtime.models import PlannerOutput, StepPlan


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"


def _planner_inputs(context) -> PlannerInputs:
    """把当前 RuntimeContext 压成新 Planner 接口需要的输入包。"""
    specs = MethodSpecRegistry.load_from_code()
    inventory = ContextInventoryBuilder().build(context, specs)
    return PlannerInputs(
        problem_id=context.problem.problem_id,
        family_spec=QUADRATIC_PATH_MINIMUM_FAMILY,
        question_goals=extract_question_goals(context.problem),
        context_inventory=inventory,
        method_specs=specs,
    )


def _method_ids(plans: list[StepPlan]) -> list[str]:
    """抽取 StepPlan 中的 method 顺序，避免测试关心 invocation 细节。"""
    return [
        invocation.method_id
        for plan in plans
        for invocation in plan.invocations
    ]


def test_planner_inputs_carries_family_question_goals_inventory_and_specs() -> None:
    """PlannerInputs 应承载题型、作答目标、上下文摘要和 method spec。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))

    inputs = _planner_inputs(context)

    assert inputs.problem_id == "tj-2026-nankai-yimo-25"
    assert inputs.family_spec is QUADRATIC_PATH_MINIMUM_FAMILY
    assert inputs.question_goals
    assert not hasattr(inputs, "planner_goals")
    assert inputs.context_inventory.planning_signals
    assert inputs.context_inventory.find_path("$problem.points.D") is not None
    assert (
        inputs.method_specs.require("right_angle_equal_length_candidates").method_id
        == "right_angle_equal_length_candidates"
    )
    assert inputs.previous_errors == []


def test_nankai_adapter_satisfies_generic_planner_interface_and_preserves_steps() -> None:
    """adapter 应满足 GenericPlanner，并保持当前 deterministic planner 的步骤顺序。"""
    adapter_context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    direct_context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    inputs = _planner_inputs(adapter_context)

    adapter = Nankai25DeterministicPlannerAdapter(adapter_context)
    adapter_output = adapter.plan(inputs)
    direct_output = QuadraticPathMinimumPlannerV15().plan(direct_context)

    assert isinstance(adapter, GenericPlanner)
    assert isinstance(adapter_output, PlannerOutput)
    assert _method_ids(adapter_output.step_plans) == _method_ids(direct_output.step_plans)
    assert adapter_output.context_declarations == direct_output.context_declarations


def test_nankai_adapter_does_not_call_answer_paths() -> None:
    """adapter 只返回 StepPlan，不读取当前南开 planner 的 answer_paths。"""

    class RaisingAnswerPathsPlanner(QuadraticPathMinimumPlannerV15):
        """若 adapter 错误访问 answer_paths，测试会立刻失败。"""

        def answer_paths(self):
            raise AssertionError("adapter should not read answer_paths")

    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    inputs = _planner_inputs(context)
    adapter = Nankai25DeterministicPlannerAdapter(
        context,
        delegate=RaisingAnswerPathsPlanner(),
    )

    output = adapter.plan(inputs)

    assert output.step_plans


def test_deterministic_planners_return_declarations_without_mutating_context() -> None:
    """内置 deterministic planner 只能声明占位，不能直接写 RuntimeContext。"""
    nankai_context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    nankai_output = QuadraticPathMinimumPlannerV15().plan(nankai_context)

    assert "G" not in nankai_context.get_scope("ii").container("points")
    assert "D_prime" not in nankai_context.get_scope("ii").container("points")
    assert {item.path for item in nankai_output.context_declarations} == {
        "$question.ii.points.G",
        "$question.ii.points.D_prime",
    }

    hexi_context = ContextBuilder().build(load_problem_ir(HEXI_FIXTURE))
    hexi_inputs = PlannerInputs(
        problem_id=hexi_context.problem.problem_id,
        family_spec=QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        question_goals=extract_question_goals(hexi_context.problem),
        context_inventory=ContextInventoryBuilder().build(
            hexi_context,
            MethodSpecRegistry.load_from_code(),
        ),
        method_specs=MethodSpecRegistry.load_from_code(),
    )
    hexi_output = Hexi25WeightedPathPlannerV15(hexi_context).plan(hexi_inputs)

    assert "Q" not in hexi_context.get_scope("iii").container("points")
    assert [item.path for item in hexi_output.context_declarations] == [
        "$question.iii.points.Q"
    ]
