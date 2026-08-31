"""河西 25 的 weighted path deterministic planner。

这仍然是第二道黄金用例的固定模板，不是通用智能 planner。它的价值是验证同一套
RuntimeOrchestrator、QuestionGoal、ResultBuilder 和 stateless method 可以承接
另一个 SolverFamily。
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime._planner_helpers import (
    single_invocation_step as _single_invocation_step,
)
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    PlannerOutput,
    StepGoal,
    StepPlan,
)


class Hexi25WeightedPathPlannerV15:
    """为河西 25 生成完整 V1.5 StepPlan。"""

    def __init__(self, context: RuntimeContext | None = None) -> None:
        # 当前河西 planner 仍是 deterministic template；context 只保留为旧 provider
        # 构造参数，不再在 plan() 中直接写入占位点。
        self.context = context

    def plan(self, inputs) -> PlannerOutput:
        """生成河西 25 三问的固定执行计划。

        ``inputs`` 由 RuntimeOrchestrator 传入，当前模板只用它满足 GenericPlanner
        接口；所有数学信息仍通过 ContextPath 绑定，让 executor 负责读取和校验。
        """
        _ = inputs
        return PlannerOutput(
            context_declarations=[],
            step_plans=[
                self._derive_part_i_parabola(),
                self._derive_part_i_vertex(),
                self._derive_part_ii_parametric_parabola(),
                self._derive_part_ii_y_axis_intercept(),
                self._derive_part_ii_d_and_coefficients(),
                self._derive_part_iii_parametric_parabola(),
                self._derive_part_iii_m(),
                self._derive_part_iii_weighted_minimum(),
            ],
        )

    def _derive_part_i_parabola(self) -> StepPlan:
        return _single_invocation_step(
            step_id="hexi_i_parabola",
            parent_scope="i",
            method_id="quadratic_from_constraints",
            inputs={
                "quadratic": "$problem.expressions.quadratic",
                "x": "$problem.symbols.x",
                "known_coefficients": "$question.i.coefficients.known",
                "all_coefficients": "$problem.symbol_lists.quadratic_coefficients",
            },
            outputs={
                "coefficients": "$step.hexi_i_parabola.temp.coefficients",
                "parabola": "$step.hexi_i_parabola.temp.parabola",
            },
            promote={
                "$step.hexi_i_parabola.temp.coefficients": "$question.i.outputs.coefficients",
                "$step.hexi_i_parabola.temp.parabola": "$question.i.outputs.parabola",
            },
            goal_type="derive_i_parabola",
            target_path="$question.i.outputs.parabola",
        )

    def _derive_part_i_vertex(self) -> StepPlan:
        return _single_invocation_step(
            step_id="hexi_i_vertex",
            parent_scope="i",
            method_id="quadratic_vertex_point",
            inputs={
                "parabola": "$question.i.outputs.parabola",
                "x": "$problem.symbols.x",
                "target": "$question.i.points.P",
            },
            outputs={"point": "$step.hexi_i_vertex.temp.point"},
            promote={"$step.hexi_i_vertex.temp.point": "$question.i.points.P"},
            goal_type="derive_i_vertex",
            target_path="$question.i.points.P",
        )

    def _derive_part_ii_parametric_parabola(self) -> StepPlan:
        return _single_invocation_step(
            step_id="hexi_ii_parametric_parabola",
            parent_scope="ii",
            method_id="quadratic_from_constraints",
            inputs={
                "quadratic": "$problem.expressions.quadratic",
                "x": "$problem.symbols.x",
                "known_coefficients": "$question.ii.coefficients.known",
                "all_coefficients": "$problem.symbol_lists.quadratic_coefficients",
                "curve_point": "$problem.points.A",
                # 第（Ⅱ）问第一步同时代入 a=2 和 A(-1,0)，所以可先推出 c=-b-2，
                # 得到只含 b 的当前问抛物线，再用于求 C 和 D。
                "free_parameter": "$problem.symbols.b",
            },
            outputs={
                "coefficients": "$step.hexi_ii_parametric_parabola.temp.coefficients",
                "parabola": "$step.hexi_ii_parametric_parabola.temp.parabola",
            },
            promote={
                "$step.hexi_ii_parametric_parabola.temp.coefficients": "$question.ii.outputs.parametric_coefficients",
                "$step.hexi_ii_parametric_parabola.temp.parabola": "$question.ii.outputs.parametric_parabola",
            },
            goal_type="derive_ii_parametric_parabola",
            target_path="$question.ii.outputs.parametric_parabola",
        )

    def _derive_part_ii_y_axis_intercept(self) -> StepPlan:
        return _single_invocation_step(
            step_id="hexi_ii_C",
            parent_scope="ii",
            method_id="quadratic_y_axis_intercept_point",
            inputs={
                "quadratic": "$question.ii.outputs.parametric_parabola",
                "x": "$problem.symbols.x",
                "target": "$question.ii.points.C",
            },
            outputs={"point": "$step.hexi_ii_C.temp.point"},
            promote={"$step.hexi_ii_C.temp.point": "$question.ii.points.C"},
            goal_type="derive_ii_y_axis_intercept",
            target_path="$question.ii.points.C",
        )

    def _derive_part_ii_d_and_coefficients(self) -> StepPlan:
        step_id = "hexi_ii_D"
        candidates_path = f"$step.{step_id}.temp.candidates"
        filtered_candidates_path = f"$step.{step_id}.temp.filtered_candidates"
        selected_candidate_path = f"$step.{step_id}.temp.selected_candidate"
        return StepPlan(
            step_id=step_id,
            goal=StepGoal(
                goal_id="derive_ii_D_and_coefficients",
                type="parameter_from_curve_point_on_quadratic",
                target_path="$question.ii.points.D",
                scope_id="ii",
                metadata={},
            ),
            scope="ii",
            invocations=[
                MethodInvocation(
                    invocation_id=f"{step_id}.right_angle_equal_length_candidates",
                    method_id="right_angle_equal_length_candidates",
                    scope=step_id,
                    inputs={
                        "anchor": "$problem.points.A",
                        "reference": "$question.ii.points.C",
                        "target": "$question.ii.points.D",
                    },
                    outputs={"candidates": candidates_path},
                ),
                MethodInvocation(
                    invocation_id=f"{step_id}.filter_point_candidates_by_quadratic_curve",
                    method_id="filter_point_candidates_by_quadratic_curve",
                    scope=step_id,
                    inputs={
                        "candidates": candidates_path,
                        "target": "$question.ii.points.D",
                        "parabola": "$question.ii.outputs.parametric_parabola",
                        "x": "$problem.symbols.x",
                        "parameter": "$problem.symbols.b",
                        "parameter_constraint": "$problem.constraints.b",
                    },
                    outputs={
                        "filtered_candidates": filtered_candidates_path,
                        "rejected_candidates": f"$step.{step_id}.temp.rejected_candidates",
                        "selected_candidate": selected_candidate_path,
                    },
                ),
                MethodInvocation(
                    invocation_id=f"{step_id}.parameter_from_curve_point_on_quadratic",
                    method_id="parameter_from_curve_point_on_quadratic",
                    scope=step_id,
                    inputs={
                        "quadratic": "$question.ii.outputs.parametric_parabola",
                        "x": "$problem.symbols.x",
                        "point": selected_candidate_path,
                        "parameter": "$problem.symbols.b",
                        "parameter_constraint": "$problem.constraints.b",
                    },
                    outputs={
                        "point": f"$step.{step_id}.temp.point",
                        "parameter_value": f"$step.{step_id}.temp.b",
                        "parabola": f"$step.{step_id}.temp.parabola",
                    },
                ),
            ],
            expected_outputs=[
                "$question.ii.points.D",
                "$question.ii.outputs.b",
                "$question.ii.outputs.parabola",
            ],
            promote_outputs={
                f"$step.{step_id}.temp.point": "$question.ii.points.D",
                f"$step.{step_id}.temp.b": "$question.ii.outputs.b",
                f"$step.{step_id}.temp.parabola": "$question.ii.outputs.parabola",
            },
        )

    def _derive_part_iii_parametric_parabola(self) -> StepPlan:
        return _single_invocation_step(
            step_id="hexi_iii_parametric_parabola",
            parent_scope="iii",
            method_id="quadratic_from_constraints",
            inputs={
                "quadratic": "$problem.expressions.quadratic",
                "x": "$problem.symbols.x",
                "known_coefficients": "$question.iii.coefficients.known",
                "all_coefficients": "$problem.symbol_lists.quadratic_coefficients",
                "curve_point": "$problem.points.A",
                "free_parameter": "$problem.symbols.b",
            },
            outputs={
                "coefficients": "$step.hexi_iii_parametric_parabola.temp.coefficients",
                "parabola": "$step.hexi_iii_parametric_parabola.temp.parabola",
            },
            promote={
                "$step.hexi_iii_parametric_parabola.temp.coefficients": "$question.iii.outputs.coefficients",
                "$step.hexi_iii_parametric_parabola.temp.parabola": "$question.iii.outputs.parametric_parabola",
            },
            goal_type="derive_iii_parametric_parabola",
            target_path="$question.iii.outputs.parametric_parabola",
        )

    def _derive_part_iii_m(self) -> StepPlan:
        return _single_invocation_step(
            step_id="hexi_iii_M",
            parent_scope="iii",
            method_id="point_on_parabola_at_x",
            inputs={
                "parabola": "$question.iii.outputs.parametric_parabola",
                "x": "$problem.symbols.x",
                "target": "$question.iii.points.M",
            },
            outputs={"point": "$step.hexi_iii_M.temp.point"},
            promote={"$step.hexi_iii_M.temp.point": "$question.iii.points.M"},
            goal_type="derive_iii_M",
            target_path="$question.iii.points.M",
        )

    def _derive_part_iii_weighted_minimum(self) -> StepPlan:
        step_id = "hexi_iii_weighted_minimum"
        minimum_path = f"$step.{step_id}.temp.minimum_expression"
        parameter_path = f"$step.{step_id}.temp.b"
        # 辅助三角形、内部 PointRef、路径变换和定义域取等验证均由原子
        # kernel 完成；确定性 planner 与 LLM planner 共享同一公开边界。
        return StepPlan(
            step_id=step_id,
            goal=StepGoal(
                goal_id=f"derive_iii_weighted_minimum:{step_id}",
                type="derive_iii_weighted_minimum",
                target_path="$question.iii.outputs.b",
                scope_id="iii",
                metadata={},
            ),
            scope="iii",
            invocations=[
                MethodInvocation(
                    invocation_id=f"{step_id}.weighted_axis_path_minimum_kernel",
                    method_id="weighted_axis_path_minimum_kernel",
                    scope=step_id,
                    inputs={
                        "path_condition": "$question.iii.conditions.minimum_value",
                        "fixed_point": "$problem.points.A",
                        "curve_point": "$question.iii.points.M",
                        "moving_point": "$question.iii.points.N",
                        "moving_point_ref": "$question.iii.points.N",
                        "parameter": "$problem.symbols.b",
                        "dynamic_parameter": "$problem.symbols.n",
                        "parameter_constraint": "$problem.constraints.b",
                        "dynamic_constraint": "$problem.constraints.n",
                    },
                    outputs={"minimum_expression": minimum_path},
                ),
                MethodInvocation(
                    invocation_id=f"{step_id}.parameter_from_expression_value",
                    method_id="parameter_from_expression_value",
                    scope=step_id,
                    inputs={
                        "expression": minimum_path,
                        "condition": "$question.iii.conditions.minimum_value",
                        "parameter": "$problem.symbols.b",
                        "constraint": "$problem.constraints.b",
                    },
                    outputs={"parameter_value": parameter_path},
                ),
            ],
            expected_outputs=["$question.iii.outputs.b"],
            promote_outputs={
                parameter_path: "$question.iii.outputs.b",
            },
        )
