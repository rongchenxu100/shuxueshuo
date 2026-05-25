"""V1.5 PlanValidator 测试。

Validator 是 planner 输出和真实执行之间的安全门：它负责拦截缺输入、错类型、
跨 sibling 引用、裸值输入和非法写回。
"""

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.executor import PlanValidator
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import StepGoal, MethodInvocation, StepPlan


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


@pytest.fixture()
def context():
    return ContextBuilder().build(load_problem_ir(NANKAI_FIXTURE))


@pytest.fixture()
def validator() -> PlanValidator:
    return PlanValidator(MethodSpecRegistry.load_from_code())


def _valid_plan(context) -> StepPlan:
    context.ensure_step_scope("derive_N", "ii")
    goal = StepGoal(
        goal_id="derive_point_coordinate:ii:N",
        type="derive_point_coordinate",
        target_path="$question.ii.points.N",
        scope_id="ii",
    )
    candidate_invocation = MethodInvocation(
        invocation_id="derive_N.candidates",
        method_id="right_angle_equal_length_candidates",
        scope="derive_N",
        inputs={
            "anchor": "$problem.points.D",
            "reference": "$question.ii.points.M",
            "target": "$question.ii.points.N",
        },
        outputs={"candidates": "$step.derive_N.temp.candidates"},
    )
    selector_invocation = MethodInvocation(
        invocation_id="derive_N.select",
        method_id="select_point_by_quadrant_constraint",
        scope="derive_N",
        inputs={
            "candidates": "$step.derive_N.temp.candidates",
            "target": "$question.ii.points.N",
            "quadrant": "$question.ii.constraints.N_quadrant",
            "parameter": "$problem.symbols.m",
            "parameter_constraint": "$problem.constraints.m",
        },
        outputs={"selected_point": "$step.derive_N.temp.selected_point"},
    )
    return StepPlan(
        step_id="derive_N",
        goal=goal,
        scope="ii",
        invocations=[candidate_invocation, selector_invocation],
        expected_outputs=["$question.ii.points.N"],
        promote_outputs={"$step.derive_N.temp.selected_point": "$question.ii.points.N"},
    )


def test_valid_invocation_passes(context, validator: PlanValidator) -> None:
    validator.validate_step(context, _valid_plan(context))


def test_missing_required_input_fails(context, validator: PlanValidator) -> None:
    plan = _valid_plan(context)
    del plan.invocations[0].inputs["anchor"]

    with pytest.raises(ValueError, match="missing required input"):
        validator.validate_step(context, plan)


def test_wrong_input_type_fails(context, validator: PlanValidator) -> None:
    plan = _valid_plan(context)
    plan.invocations[0].inputs["anchor"] = "$question.ii.conditions.length_squared"

    with pytest.raises((TypeError, KeyError)):
        validator.validate_step(context, plan)


def test_sibling_scope_reference_fails(context, validator: PlanValidator) -> None:
    context.ensure_step_scope("derive_N_from_q2", "ii_2")
    plan = _valid_plan(context)
    plan.step_id = "derive_N_from_q2"
    plan.scope = "ii_2"
    plan.invocations[0].scope = "derive_N_from_q2"
    plan.invocations[1].scope = "derive_N_from_q2"
    plan.invocations[0].outputs = {"candidates": "$step.derive_N_from_q2.temp.candidates"}
    plan.invocations[1].inputs["candidates"] = "$step.derive_N_from_q2.temp.candidates"
    plan.invocations[1].outputs = {"selected_point": "$step.derive_N_from_q2.temp.selected_point"}
    plan.promote_outputs = {
        "$step.derive_N_from_q2.temp.selected_point": "$subquestion.ii_1.outputs.N"
    }

    with pytest.raises(PermissionError):
        validator.validate_step(context, plan)


def test_naked_input_value_fails(context, validator: PlanValidator) -> None:
    plan = _valid_plan(context)
    plan.invocations[0].inputs["anchor"] = ["1", "0"]  # type: ignore[assignment]

    with pytest.raises(ValueError, match="ContextPath"):
        validator.validate_step(context, plan)


def test_output_over_locked_fact_fails(context, validator: PlanValidator) -> None:
    plan = _valid_plan(context)
    plan.invocations[1].outputs = {"selected_point": "$question.ii.points.M"}

    with pytest.raises(PermissionError):
        validator.validate_step(context, plan)
