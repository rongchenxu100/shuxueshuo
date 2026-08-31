"""南开 25 的 V1.5 固定 StepPlan 生成器。

这不是通用智能 planner，而是第一道完整黄金用例的显式编排器。它负责把题意中
的点、条件和 planner hints 映射成一组有序 MethodInvocation；method 本身仍然
只接收 ContextPath 解析后的 typed inputs。
"""

from __future__ import annotations

from typing import Any

from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime._planner_helpers import (
    question_point_declaration as _point_declaration,
    single_invocation_step as _single_invocation_step,
)
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    PlannerOutput,
    StepGoal,
    StepPlan,
)


class QuadraticPathMinimumPlannerV15:
    """为 canonical 南开 25 生成完整 V1.5 计划。"""

    def plan(self, context: RuntimeContext) -> PlannerOutput:
        """生成南开 25 的声明式 planner 输出。

        G 不是题设已知坐标，而是原子路径 Macro 返回的取等状态。内部反射点和
        拉直候选只存在于 kernel 内，不再成为 StepPlan 或 RuntimeContext 中的
        公开对象。Phase B 起 planner 只返回声明，不再直接写
        RuntimeContext；Orchestrator 会统一校验并 apply。
        """
        _ = context
        return PlannerOutput(
            context_declarations=[
                _point_declaration("ii", "G", "line_intersection"),
            ],
            step_plans=[
                self._derive_axis_point(),
                self._derive_part_i_parabola(),
                self._derive_right_angle_point(),
                self._derive_q1_parameter(),
                self._derive_q1_parabola(),
                self._derive_midpoint(),
                self._derive_atomic_path_minimum(),
                self._evaluate_q1_minimum(),
                self._derive_q2_parameter(),
                self._derive_q2_parabola(),
                self._evaluate_q2_attainment_point(),
            ],
        )

    def _derive_axis_point(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_D",
            parent_scope="problem",
            method_id="quadratic_axis_from_relation",
            inputs={
                "coefficient_relation": "$problem.equations.coefficient_relation",
                "a": "$problem.symbols.a",
                "b": "$problem.symbols.b",
                "target": "$problem.points.D",
            },
            outputs={"axis_point": "$step.derive_D.temp.axis_point"},
            promote={"$step.derive_D.temp.axis_point": "$problem.points.D"},
            goal_type="derive_axis_point",
            target_path="$problem.points.D",
        )

    def _derive_part_i_parabola(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_part_i_parabola",
            parent_scope="i",
            method_id="quadratic_from_constraints",
            inputs={
                "quadratic": "$problem.expressions.quadratic",
                "x": "$problem.symbols.x",
                "coefficient_relation": "$problem.equations.coefficient_relation",
                "known_coefficients": "$question.i.coefficients.known",
                "all_coefficients": "$problem.symbol_lists.quadratic_coefficients",
            },
            outputs={
                "coefficients": "$step.derive_part_i_parabola.temp.coefficients",
                "parabola": "$step.derive_part_i_parabola.temp.parabola",
            },
            promote={"$step.derive_part_i_parabola.temp.parabola": "$question.i.outputs.parabola"},
            goal_type="derive_part_i_parabola",
            target_path="$question.i.outputs.parabola",
        )

    def _derive_right_angle_point(self) -> StepPlan:
        goal = StepGoal(
            goal_id="derive_point_coordinate:derive_N",
            type="derive_point_coordinate",
            target_path="$question.ii.points.N",
            scope_id="ii",
            metadata={},
        )
        return StepPlan(
            step_id="derive_N",
            goal=goal,
            scope="ii",
            invocations=[
                MethodInvocation(
                    invocation_id="derive_N.right_angle_equal_length_candidates",
                    method_id="right_angle_equal_length_candidates",
                    scope="derive_N",
                    inputs={
                        "anchor": "$problem.points.D",
                        "reference": "$question.ii.points.M",
                        "target": "$question.ii.points.N",
                    },
                    outputs={"candidates": "$step.derive_N.temp.candidates"},
                ),
                MethodInvocation(
                    invocation_id="derive_N.select_point_by_quadrant_constraint",
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
                ),
            ],
            expected_outputs=["$question.ii.points.N"],
            promote_outputs={"$step.derive_N.temp.selected_point": "$question.ii.points.N"},
        )

    def _derive_midpoint(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_F",
            parent_scope="ii",
            method_id="midpoint_point",
            inputs={
                "p1": "$problem.points.D",
                "p2": "$question.ii.points.N",
                "target": "$question.ii.points.F",
            },
            outputs={"midpoint": "$step.derive_F.temp.midpoint"},
            promote={"$step.derive_F.temp.midpoint": "$question.ii.points.F"},
            goal_type="derive_midpoint_coordinate",
            target_path="$question.ii.points.F",
        )

    def _derive_q1_parameter(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_q1_m",
            parent_scope="ii_1",
            method_id="parameter_from_segment_length",
            inputs={
                "p1": "$question.ii.points.M",
                "p2": "$question.ii.points.N",
                "parameter": "$problem.symbols.m",
                "condition": "$subquestion.ii_1.conditions.length_squared",
                "constraint": "$problem.constraints.m",
            },
            outputs={"parameter_value": "$step.derive_q1_m.temp.parameter_value"},
            promote={"$step.derive_q1_m.temp.parameter_value": "$subquestion.ii_1.outputs.m"},
            goal_type="derive_q1_parameter",
            target_path="$subquestion.ii_1.outputs.m",
        )

    def _derive_q1_parabola(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_q1_parabola",
            parent_scope="ii_1",
            method_id="quadratic_from_constraints",
            inputs={
                "quadratic": "$problem.expressions.quadratic",
                "x": "$problem.symbols.x",
                "p1": "$question.ii.points.M",
                "p2": "$question.ii.points.N",
                "coefficient_relation": "$problem.equations.coefficient_relation",
                "all_coefficients": "$problem.symbol_lists.quadratic_coefficients",
                "parameter": "$problem.symbols.m",
                "parameter_value": "$subquestion.ii_1.outputs.m",
            },
            outputs={
                "coefficients": "$step.derive_q1_parabola.temp.coefficients",
                "parabola": "$step.derive_q1_parabola.temp.parabola",
            },
            promote={
                "$step.derive_q1_parabola.temp.coefficients": "$subquestion.ii_1.outputs.coefficients",
                "$step.derive_q1_parabola.temp.parabola": "$subquestion.ii_1.outputs.parabola",
            },
            goal_type="derive_q1_parabola",
            target_path="$subquestion.ii_1.outputs.parabola",
        )

    def _derive_atomic_path_minimum(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_path_minimum",
            parent_scope="ii",
            method_id=(
                "coupled_segment_endpoint_replacement_path_minimum_kernel"
            ),
            inputs={
                "path_condition": "$problem.conditions.path_minimum",
                "first_membership": "$problem.conditions.segment_membership_E",
                "second_membership": "$problem.conditions.segment_membership_G",
                "segment_binding_relation": "$problem.conditions.segment_relation_DE_NG",
                "first_segment_start": "$problem.points.D",
                "joint_point": "$question.ii.points.M",
                "second_segment_end": "$question.ii.points.N",
                "transformed_fixed_endpoint": "$question.ii.points.F",
                "moving_point": "$question.ii.points.G",
            },
            outputs={
                "minimum_expression": (
                    "$step.derive_path_minimum.temp.minimum_expression"
                ),
                "attainment_point": (
                    "$step.derive_path_minimum.temp.attainment_point"
                ),
            },
            promote={
                "$step.derive_path_minimum.temp.minimum_expression": (
                    "$question.ii.outputs.minimum_expression"
                ),
                "$step.derive_path_minimum.temp.attainment_point": (
                    "$question.ii.points.G"
                ),
            },
            goal_type="derive_coupled_segment_path_minimum",
            target_path="$question.ii.outputs.minimum_expression",
        )

    def _evaluate_q1_minimum(self) -> StepPlan:
        return _single_invocation_step(
            step_id="evaluate_q1_minimum",
            parent_scope="ii_1",
            method_id="evaluate_expression_at_parameter",
            inputs={
                "expression": "$question.ii.outputs.minimum_expression",
                "parameter": "$problem.symbols.m",
                "parameter_value": "$subquestion.ii_1.outputs.m",
            },
            outputs={
                "evaluated_minimum_expression": (
                    "$step.evaluate_q1_minimum.temp.minimum_value"
                ),
            },
            promote={
                "$step.evaluate_q1_minimum.temp.minimum_value": (
                    "$subquestion.ii_1.outputs.min_value"
                ),
            },
            goal_type="evaluate_path_minimum",
            target_path="$subquestion.ii_1.outputs.min_value",
        )

    def _derive_q2_parameter(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_q2_m",
            parent_scope="ii_2",
            method_id="parameter_from_minimum_value",
            inputs={
                "minimum_expression": "$question.ii.outputs.minimum_expression",
                "condition": "$subquestion.ii_2.conditions.minimum_value",
                "parameter": "$problem.symbols.m",
                "constraint": "$problem.constraints.m",
            },
            outputs={"parameter_value": "$step.derive_q2_m.temp.parameter_value"},
            promote={"$step.derive_q2_m.temp.parameter_value": "$subquestion.ii_2.outputs.m"},
            goal_type="derive_q2_parameter",
            target_path="$subquestion.ii_2.outputs.m",
        )

    def _derive_q2_parabola(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_q2_parabola",
            parent_scope="ii_2",
            method_id="quadratic_from_constraints",
            inputs={
                "quadratic": "$problem.expressions.quadratic",
                "x": "$problem.symbols.x",
                "p1": "$question.ii.points.M",
                "p2": "$question.ii.points.N",
                "coefficient_relation": "$problem.equations.coefficient_relation",
                "all_coefficients": "$problem.symbol_lists.quadratic_coefficients",
                "parameter": "$problem.symbols.m",
                "parameter_value": "$subquestion.ii_2.outputs.m",
            },
            outputs={
                "coefficients": "$step.derive_q2_parabola.temp.coefficients",
                "parabola": "$step.derive_q2_parabola.temp.parabola",
            },
            promote={
                "$step.derive_q2_parabola.temp.coefficients": "$subquestion.ii_2.outputs.coefficients",
                "$step.derive_q2_parabola.temp.parabola": "$subquestion.ii_2.outputs.parabola",
            },
            goal_type="derive_q2_parabola",
            target_path="$subquestion.ii_2.outputs.parabola",
        )

    def _evaluate_q2_attainment_point(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_G",
            parent_scope="ii_2",
            method_id="evaluate_point_at_parameter",
            inputs={
                "point": "$question.ii.points.G",
                "parameter": "$problem.symbols.m",
                "parameter_value": "$subquestion.ii_2.outputs.m",
            },
            outputs={"evaluated_point": "$step.derive_G.temp.evaluated_point"},
            promote={
                "$step.derive_G.temp.evaluated_point": "$question.ii.points.G"
            },
            goal_type="evaluate_q2_attainment_point",
            target_path="$question.ii.points.G",
        )
