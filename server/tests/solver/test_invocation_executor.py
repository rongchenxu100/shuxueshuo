"""V1.5 InvocationExecutor 集成测试。

这组测试证明“候选生成”和“条件筛选”拆分后，南开可以完整执行到 N，
候选生成 method 仍可在河西上下文中复用。
"""

import inspect

import pytest
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
from shuxueshuo_server.solver.runtime.models import MethodInvocation, StepGoal, StepPlan, TypedValue
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


def test_executor_recovers_point_ref_from_computed_point_output_path() -> None:
    """PointRef|Point target 若来自 outputs/fact path，也应恢复学生可见点名。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    outputs = context.get_scope("ii").container("outputs")
    outputs["G_locus_line"] = TypedValue(
        "Line",
        {
            "kind": "line",
            "start_point": (sp.Integer(0), sp.Integer(0)),
            "direction": (sp.Integer(1), sp.Integer(0)),
        },
        source="test",
    )
    outputs["path_minimum_point_1"] = TypedValue(
        "Point",
        (sp.Integer(2), sp.Integer(-1)),
        source="test",
    )
    outputs["path_minimum_point_2"] = TypedValue(
        "Point",
        (sp.Integer(2), sp.Integer(1)),
        source="test",
    )
    outputs["G_coordinate"] = TypedValue(
        "Point",
        (sp.Integer(0), sp.Integer(0)),
        source="test",
    )
    invocation = MethodInvocation(
        invocation_id="derive_minimum_G_point.line_locus_minimum_point",
        method_id="line_locus_minimum_point",
        scope="ii",
        inputs={
            "moving_locus": "$question.ii.outputs.G_locus_line",
            "minimum_point_1": "$question.ii.outputs.path_minimum_point_1",
            "minimum_point_2": "$question.ii.outputs.path_minimum_point_2",
            "target": "$question.ii.outputs.G_coordinate",
        },
        outputs={"point": "$question.ii.outputs.optimal_G_coordinate"},
    )

    result = InvocationExecutor(specs).execute_invocation(context, invocation)

    assert result.outputs["point"].value == (sp.Integer(2), sp.Integer(0))
    assert result.trace_fragments[0].goal == "确定 G 的坐标"
    assert "moving_point" not in result.trace_fragments[0].goal
    written = context.read_path(
        "$question.ii.outputs.optimal_G_coordinate",
        from_scope_id="ii",
        expected_type="Point",
    )
    assert written.value == (sp.Integer(2), sp.Integer(0))


def test_promote_outputs_can_update_unlocked_existing_point_state() -> None:
    """promote 可把同一对象从参数化 Point 更新为已代入 Point。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    step_id = "manual_promote_g"
    context.ensure_step_scope(step_id, "ii")
    m = context.symbols["m"]
    context.get_scope("ii").container("points")["G"] = TypedValue(
        "Point",
        (m, m),
        locked=False,
        source="test",
    )
    context.write_path(
        "$step.manual_promote_g.temp.point",
        TypedValue("Point", (sp.Integer(2), sp.Integer(3)), source="test"),
        from_scope_id=step_id,
    )

    InvocationExecutor(specs).execute_step(
        context,
        StepPlan(
            step_id=step_id,
            goal=StepGoal(
                goal_id="test:update_g",
                type="derive_extremal_point",
                target_path="$question.ii.points.G",
                scope_id="ii",
            ),
            scope="ii",
            promote_outputs={
                "$step.manual_promote_g.temp.point": "$question.ii.points.G"
            },
        ),
    )

    point = context.read_path(
        "$question.ii.points.G",
        from_scope_id="ii",
        expected_type="Point",
    ).value
    assert point == (sp.Integer(2), sp.Integer(3))


def test_promote_outputs_still_reject_locked_existing_point() -> None:
    """promote 不能覆盖 locked 题设值。"""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    step_id = "manual_promote_d"
    context.ensure_step_scope(step_id, "ii")
    context.write_path(
        "$step.manual_promote_d.temp.point",
        TypedValue("Point", (sp.Integer(9), sp.Integer(9)), source="test"),
        from_scope_id=step_id,
    )

    with pytest.raises(PermissionError, match="promote target is not writable"):
        InvocationExecutor(specs).execute_step(
            context,
            StepPlan(
                step_id=step_id,
                goal=StepGoal(
                    goal_id="test:update_m",
                    type="derive_point",
                    target_path="$question.ii.points.M",
                    scope_id="ii",
                ),
                scope="ii",
                promote_outputs={
                    "$step.manual_promote_d.temp.point": "$question.ii.points.M"
                },
            ),
        )
