"""V1.5 规则 StepPlanner 测试。

Planner 只负责把 PlanningSignal 映射成 MethodInvocation 的 ContextPath，不直接计算坐标。
"""

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner import RuleBasedStepPlannerV15


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"


def _plan_for_target(fixture: str, target: str):
    context = ContextBuilder().build(load_problem_ir(fixture))
    specs = MethodSpecRegistry.load_from_code()
    inventory = ContextInventoryBuilder().build(context, specs)
    signal = next(
        item for item in inventory.planning_signals
        if item.signal_type == "constructible_right_angle_equal_length_point"
        and item.roles["target"] == target
    )
    return context, RuleBasedStepPlannerV15(specs).plan(context, signal)


def test_plans_nankai_right_angle_invocation_without_hardcoded_method() -> None:
    _context, plan = _plan_for_target(NANKAI_FIXTURE, "N")

    assert plan is not None
    candidate_invocation = plan.invocations[0]
    selector_invocation = plan.invocations[1]
    assert candidate_invocation.method_id == "right_angle_equal_length_candidates"
    assert candidate_invocation.inputs["anchor"] == "$problem.points.D"
    assert candidate_invocation.inputs["reference"] == "$question.ii.points.M"
    assert candidate_invocation.inputs["target"] == "$question.ii.points.N"
    assert selector_invocation.method_id == "select_point_by_quadrant_constraint"
    assert selector_invocation.inputs["quadrant"] == "$question.ii.constraints.N_quadrant"
    assert selector_invocation.inputs["parameter"] == "$problem.symbols.m"
    assert selector_invocation.inputs["parameter_constraint"] == "$problem.constraints.m"


def test_returns_none_for_hexi_without_explicit_selector_condition() -> None:
    _context, plan = _plan_for_target(HEXI_FIXTURE, "D")

    assert plan is None


def test_returns_none_when_no_matching_method_spec() -> None:
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    signal = ContextInventoryBuilder().build(context, specs).signals_by_type(
        "constructible_right_angle_equal_length_point"
    )[0]
    empty_specs = MethodSpecRegistry({})

    assert RuleBasedStepPlannerV15(empty_specs).plan(context, signal) is None
