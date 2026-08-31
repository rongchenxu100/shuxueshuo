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
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
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


def test_executor_reads_point_identity_from_canonical_entity_path() -> None:
    """Identity-view inputs come from the canonical entity, not a Point value."""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    invocation = MethodInvocation(
        invocation_id="derive_D.quadratic_axis_from_relation",
        method_id="quadratic_axis_from_relation",
        scope="ii",
        inputs={
            "coefficient_relation": "$problem.equations.coefficient_relation",
            "a": "$problem.symbols.a",
            "b": "$problem.symbols.b",
            "target": "$problem.points.D",
        },
        outputs={"axis_point": "$question.ii.outputs.axis_point"},
    )

    result = InvocationExecutor(specs).execute_invocation(context, invocation)

    assert result.outputs["axis_point"].value == (sp.Integer(1), sp.Integer(0))
    assert result.trace_fragments[0].title == "由系数关系确定 D"
    written = context.read_path(
        "$question.ii.outputs.axis_point",
        from_scope_id="ii",
        expected_type="Point",
    )
    assert written.value == (sp.Integer(1), sp.Integer(0))


def test_executor_keeps_point_identity_separate_from_existing_point_state() -> None:
    """An identity-view target never relies on a coordinate state's path/name."""
    context = ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    x = context.symbols["x"]
    outputs = context.get_scope("ii").container("outputs")
    outputs["closed_parabola"] = TypedValue(
        "Parabola",
        x * (x - 2),
        source="test",
    )
    outputs["known_intercept"] = TypedValue(
        "Point",
        (sp.Integer(0), sp.Integer(0)),
        source="test",
    )
    invocation = MethodInvocation(
        invocation_id="close_existing_B.quadratic_x_axis_intercept_point",
        method_id="quadratic_x_axis_intercept_point",
        scope="ii",
        inputs={
            "quadratic": "$question.ii.outputs.closed_parabola",
            "x": "$problem.symbols.x",
            "target": "$question.ii.points.G",
            "known_point": "$question.ii.outputs.known_intercept",
        },
        outputs={"point": "$question.ii.outputs.closed_B_coordinate"},
    )

    result = InvocationExecutor(specs).execute_invocation(context, invocation)

    assert result.outputs["point"].value == (
        sp.Integer(2),
        sp.Integer(0),
    )
    assert result.trace_fragments[0].goal == "确定 G 的坐标"


def test_executor_projects_structured_point_to_active_function_basis() -> None:
    """A Method sees an equivalent local view without mutating Problem state."""

    context = ContextBuilder().build(load_problem_ir(HEXI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    x = context.symbols["x"]
    b = context.symbols["b"]
    c = context.symbols["c"]
    original = context.read_path(
        "$question.iii.points.M",
        from_scope_id="iii",
        expected_type="PointRef",
    ).value
    context.get_scope("iii").container("outputs")["c_basis_parabola"] = TypedValue(
        "Parabola",
        x**2 + (c + 1) * x + c,
        source="test",
    )
    invocation = MethodInvocation(
        invocation_id="derive_M.point_on_parabola_at_x",
        method_id="point_on_parabola_at_x",
        scope="iii",
        inputs={
            "parabola": "$question.iii.outputs.c_basis_parabola",
            "x": "$problem.symbols.x",
            "target": "$question.iii.points.M",
        },
        outputs={"point": "$question.iii.outputs.M_coordinate"},
    )

    resolved = InvocationExecutor(specs).resolve_inputs(context, invocation)
    projected = resolved["target"]
    assert projected.definition["x"] == -c - sp.Rational(1, 2)

    result = InvocationExecutor(specs).execute_invocation(context, invocation)

    assert result.outputs["point"].value == (
        -c - sp.Rational(1, 2),
        c / 2 - sp.Rational(1, 4),
    )
    assert original.definition["x"] == b + sp.Rational(1, 2)
    assert context.read_path(
        "$question.iii.points.M",
        from_scope_id="iii",
        expected_type="PointRef",
    ).value is original


def test_executor_reports_missing_conditional_method_output() -> None:
    context = ContextBuilder().build(load_problem_ir(HEXI_FIXTURE))
    specs = MethodSpecRegistry.load_from_code()
    x = context.symbols["x"]
    b = context.symbols["b"]
    outputs = context.get_scope("ii").container("outputs")
    outputs["ambiguous_candidates"] = TypedValue(
        "PointList",
        [(sp.Integer(0), sp.Integer(1)), (sp.Integer(1), sp.Integer(2))],
        source="test",
    )
    outputs["parametric_parabola"] = TypedValue(
        "Parabola",
        x**2 + b,
        source="test",
    )
    outputs["positive_parameter"] = TypedValue(
        "Constraint",
        {"operator": ">", "value": sp.Integer(0)},
        source="test",
    )
    invocation = MethodInvocation(
        invocation_id="filter_candidates.filter",
        method_id="filter_point_candidates_by_quadratic_curve",
        scope="ii",
        inputs={
            "candidates": "$question.ii.outputs.ambiguous_candidates",
            "target": "$question.ii.points.D",
            "parabola": "$question.ii.outputs.parametric_parabola",
            "x": "$problem.symbols.x",
            "parameter": "$problem.symbols.b",
            "parameter_constraint": "$question.ii.outputs.positive_parameter",
        },
        outputs={
            "selected_candidate": "$question.ii.outputs.selected_candidate"
        },
    )

    with pytest.raises(StatelessMethodError) as exc_info:
        InvocationExecutor(specs).execute_invocation(context, invocation)

    error = exc_info.value
    assert error.code == "functional.method_result_ambiguous"
    assert error.authority.expected["outputs"] == ("selected_candidate",)
    assert error.authority.observed["missing_outputs"] == (
        "selected_candidate",
    )
    assert (
        "candidate_selection_ambiguous"
        in error.authority.observed["failed_checks"]
    )
    assert (
        error.authority.repair_action
        == "supply_disambiguating_constraint"
    )


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
