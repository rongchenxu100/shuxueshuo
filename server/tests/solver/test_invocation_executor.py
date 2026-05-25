"""V1.5 InvocationExecutor 集成测试。

这组测试证明“候选生成”和“条件筛选”拆分后，南开可以完整执行到 N，
候选生成 method 仍可在河西上下文中复用。
"""

import inspect

import sympy as sp

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import (
    RightAngleEqualLengthCandidatesMethod,
    SelectPointByQuadrantConstraintMethod,
)
from shuxueshuo_server.solver.runtime.planner import RuleBasedStepPlannerV15


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"


def _execute_first_right_angle_goal(fixture: str, target: str):
    context = ContextBuilder().build(load_problem_ir(fixture))
    specs = MethodSpecRegistry.load_from_code()
    signal = next(
        item for item in ContextInventoryBuilder().build(context, specs).planning_signals
        if item.signal_type == "constructible_right_angle_equal_length_point"
        and item.roles["target"] == target
    )
    plan = RuleBasedStepPlannerV15(specs).plan(context, signal)
    assert plan is not None
    result = InvocationExecutor(specs).execute_step(context, plan)
    return context, result, plan


def test_nankai_executes_right_angle_method_for_n() -> None:
    context, result, plan = _execute_first_right_angle_goal(NANKAI_FIXTURE, "N")
    m = context.symbols["m"]

    point = context.read_path("$question.ii.points.N", from_scope_id="ii", expected_type="Point").value

    assert [invocation.method_id for invocation in plan.invocations] == [
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    ]
    assert sp.simplify(point[0] - 2) == 0
    assert sp.simplify(point[1] - (1 - m)) == 0
    assert result.checks
    assert all(check.ok for check in result.checks)


def test_hexi_can_reuse_right_angle_candidate_generation_for_d() -> None:
    context = ContextBuilder().build(load_problem_ir(HEXI_FIXTURE))
    c = context.symbols["c"]
    anchor = context.read_path("$problem.points.A", from_scope_id="ii", expected_type="Point").value
    reference = context.read_path("$question.ii.points.C", from_scope_id="ii", expected_type="Point").value

    result = RightAngleEqualLengthCandidatesMethod().run(
        {
            "anchor": anchor,
            "reference": reference,
            "target": context.read_path(
                "$question.ii.points.D",
                from_scope_id="ii",
                expected_type="PointRef",
            ).value,
        },
        context.kernel,
    )

    assert (c - 1, sp.Integer(-1)) in result.outputs["candidates"].value
    assert all(check.ok for check in result.checks)


def test_stateless_methods_do_not_accept_solve_context() -> None:
    candidate_signature = inspect.signature(RightAngleEqualLengthCandidatesMethod().run)
    selector_signature = inspect.signature(SelectPointByQuadrantConstraintMethod().run)

    assert list(candidate_signature.parameters) == ["inputs", "kernel"]
    assert list(selector_signature.parameters) == ["inputs", "kernel"]
