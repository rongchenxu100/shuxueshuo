"""南开 25 的 V1.5 固定 StepPlan 生成器。

这不是通用智能 planner，而是第一道完整黄金用例的显式编排器。它负责把题意中
的点、条件和 planner hints 映射成一组有序 MethodInvocation；method 本身仍然
只接收 ContextPath 解析后的 typed inputs。
"""

from __future__ import annotations

from typing import Any

from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime._planner_helpers import (
    single_invocation_step as _single_invocation_step,
)
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    PointRef,
    StepGoal,
    StepPlan,
    TypedValue,
)


class QuadraticPathMinimumPlannerV15:
    """为 canonical 南开 25 生成完整 V1.5 计划。"""

    def plan(self, context: RuntimeContext) -> list[StepPlan]:
        # G 和 D_prime 都不是题设已知点：G 是最终交点答案，D_prime 是“将军饮马”
        # 拉直过程中选择出来的辅助点。Phase 6 起 fixture 不再注入这类 planner
        # hints，所以 deterministic slice 在规划阶段显式创建可写 PointRef 占位。
        self._ensure_result_point(context, "ii", "G")
        self._ensure_straightening_auxiliary_point(context, "ii", "D_prime")
        return [
            self._derive_axis_point(),
            self._derive_part_i_parabola(),
            self._derive_right_angle_point(),
            self._derive_q1_parameter(),
            self._derive_q1_parabola(),
            self._derive_midpoint(),
            self._derive_path_reduction(),
            self._derive_straightening_candidates(),
            self._select_straightening_candidate(),
            self._derive_minimum_expression(),
            self._derive_q2_parameter(),
            self._derive_q2_parabola(),
            self._derive_q2_intersection(),
        ]

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

    def _derive_straightening_candidates(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_straightening_candidates",
            parent_scope="ii",
            method_id="broken_path_straightening_candidates",
            inputs={
                "path_transformation": "$question.ii.outputs.path_transformation",
                "moving_point_membership": "$problem.conditions.segment_membership_G",
                "fixed_point_1": "$problem.points.D",
                "fixed_point_2": "$question.ii.points.F",
                "line_point_1": "$question.ii.points.M",
                "line_point_2": "$question.ii.points.N",
            },
            outputs={"candidates": "$step.derive_straightening_candidates.temp.candidates"},
            promote={
                "$step.derive_straightening_candidates.temp.candidates": "$question.ii.outputs.straightening_candidates"
            },
            goal_type="derive_broken_path_straightening_candidates",
            target_path="$question.ii.outputs.straightening_candidates",
        )

    def _select_straightening_candidate(self) -> StepPlan:
        return _single_invocation_step(
            step_id="select_straightening_candidate",
            parent_scope="ii",
            method_id="select_straightening_candidate",
            inputs={
                "candidates": "$question.ii.outputs.straightening_candidates",
                "target": "$question.ii.points.D_prime",
            },
            outputs={
                "selected_candidate": "$step.select_straightening_candidate.temp.selected_candidate",
                "auxiliary_point": "$step.select_straightening_candidate.temp.auxiliary_point",
            },
            promote={
                "$step.select_straightening_candidate.temp.selected_candidate": "$question.ii.outputs.straightening_candidate",
                "$step.select_straightening_candidate.temp.auxiliary_point": "$question.ii.points.D_prime",
            },
            goal_type="select_broken_path_straightening_candidate",
            target_path="$question.ii.points.D_prime",
        )

    def _derive_path_reduction(self) -> StepPlan:
        return _single_invocation_step(
            step_id="reduce_path",
            parent_scope="ii",
            method_id="two_moving_points_path_reduction",
            inputs={
                "original_path": "$problem.conditions.path_minimum",
                "first_moving_membership": "$problem.conditions.segment_membership_E",
                "second_moving_membership": "$problem.conditions.segment_membership_G",
                "binding_relation": "$problem.conditions.segment_relation_DE_NG",
                "first_segment_start": "$problem.points.D",
                "joint_point": "$question.ii.points.M",
                "second_segment_end": "$question.ii.points.N",
            },
            outputs={"path_transformation": "$step.reduce_path.temp.path_transformation"},
            promote={
                "$step.reduce_path.temp.path_transformation": "$question.ii.outputs.path_transformation"
            },
            goal_type="reduce_two_moving_point_path",
            target_path="$question.ii.outputs.path_transformation",
        )

    def _derive_minimum_expression(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_minimum_expression",
            parent_scope="ii_1",
            method_id="distance_between_points",
            inputs={
                "p1": "$question.ii.points.D_prime",
                "p2": "$question.ii.points.F",
                "parameter": "$problem.symbols.m",
                "parameter_value": "$subquestion.ii_1.outputs.m",
            },
            outputs={
                "distance": "$step.derive_minimum_expression.temp.distance",
                "evaluated_distance": "$step.derive_minimum_expression.temp.evaluated_distance",
            },
            promote={
                "$step.derive_minimum_expression.temp.distance": "$question.ii.outputs.minimum_expression",
                "$step.derive_minimum_expression.temp.evaluated_distance": "$subquestion.ii_1.outputs.min_value",
            },
            goal_type="derive_minimum_expression",
            target_path="$question.ii.outputs.minimum_expression",
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

    def _derive_q2_intersection(self) -> StepPlan:
        return _single_invocation_step(
            step_id="derive_G",
            parent_scope="ii_2",
            method_id="line_intersection_point",
            inputs={
                "line1_p1": "$question.ii.points.M",
                "line1_p2": "$question.ii.points.N",
                "line2_p1": "$question.ii.points.D_prime",
                "line2_p2": "$question.ii.points.F",
                "target": "$question.ii.points.G",
                "parameter": "$problem.symbols.m",
                "parameter_value": "$subquestion.ii_2.outputs.m",
            },
            outputs={"intersection": "$step.derive_G.temp.intersection"},
            promote={"$step.derive_G.temp.intersection": "$question.ii.points.G"},
            goal_type="derive_q2_intersection",
            target_path="$question.ii.points.G",
        )

    def _ensure_result_point(self, context: RuntimeContext, scope_id: str, name: str) -> None:
        scope = context.get_scope(scope_id)
        if name in scope.container("points"):
            return
        path = f"$question.{scope_id}.points.{name}"
        scope.container("points")[name] = TypedValue(
            "PointRef",
            PointRef(name=name, path=path, definition={"definition": "line_intersection"}, scope_id=scope_id),
            locked=False,
            source="planner",
        )

    def _ensure_straightening_auxiliary_point(
        self,
        context: RuntimeContext,
        scope_id: str,
        name: str,
    ) -> None:
        """创建折线拉直辅助点占位。

        这里只声明“planner 预计会产生一个辅助点”，不把反射来源、镜像线或坐标写进
        fixture。真正的候选生成与选择仍由
        ``broken_path_straightening_candidates`` 和
        ``select_straightening_candidate`` 计算、验算并写回。
        """
        scope = context.get_scope(scope_id)
        if name in scope.container("points"):
            return
        path = f"$question.{scope_id}.points.{name}"
        scope.container("points")[name] = TypedValue(
            "PointRef",
            PointRef(
                name=name,
                path=path,
                definition={"definition": "straightening_auxiliary_point"},
                scope_id=scope_id,
            ),
            locked=False,
            source="planner",
        )
