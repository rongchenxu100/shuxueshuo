"""Controlled LLM Planner 的测试/开发 fake provider。

本模块承载体积较大的黄金题 fake draft，避免 ``controlled_llm_planner`` 核心模块
同时混入测试样板和生产编译逻辑。D2 增加河西 controlled draft 时，也应该继续放在
这里，而不是塞回核心 planner。
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any

from shuxueshuo_server.solver.family import (
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.runtime.controlled_llm_planner import (
    AbstractPlanValidationError,
    ControlledLLMPlanner,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient


class FakeControlledLLMPlannerClient:
    """测试用完整 controlled draft Fake LLM。

    这个 fake 不硬编码 ``c_0/c_1``，而是读取当前请求 payload 中的 ``slot_options``，
    按 ContextPath 动态查找 candidate id。这样 SlotBinder 排序变动时，fake 仍然
    测的是“完整 draft 协议”，而不是某个偶然的候选编号。
    """

    def __init__(self, response: str | None = None) -> None:
        self.response = response
        self.payloads: list[dict[str, Any]] = []

    def complete(self, payload: dict[str, Any]) -> str:
        """按 ``family_id + problem_id`` 返回完整 PlannerDraft JSON。"""
        self.payloads.append(payload)
        if self.response is not None:
            return self.response
        family_id = str(payload.get("family_id", ""))
        planner_payload = payload.get("planner_payload")
        if not isinstance(planner_payload, dict):
            raise AbstractPlanValidationError("controlled fake requires planner_payload")
        if family_id == QUADRATIC_PATH_MINIMUM_FAMILY.family_id:
            problem_id = str(payload.get("problem_id", ""))
            if problem_id not in {
                "tj-2026-nankai-yimo-25",
                "tj-2026-nankai-yimo-25-alt-labels",
            }:
                raise AbstractPlanValidationError(
                    f"fake controlled planner has no draft for problem_id={problem_id}"
                )
            return json.dumps(
                _quadratic_path_controlled_draft(planner_payload),
                ensure_ascii=False,
            )
        if family_id == QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id:
            problem_id = str(payload.get("problem_id", ""))
            if problem_id != "tj-2026-hexi-yimo-25":
                raise AbstractPlanValidationError(
                    f"fake controlled planner has no draft for problem_id={problem_id}"
                )
            return json.dumps(
                _hexi25_controlled_draft(planner_payload),
                ensure_ascii=False,
            )
        raise AbstractPlanValidationError(
            f"fake controlled planner has no draft for family_id={family_id}"
        )


def controlled_llm_planner_provider(
    client: LLMPlannerClient,
) -> Callable[[Any], ControlledLLMPlanner]:
    """创建 RuntimeOrchestrator 可注入的 controlled planner provider。"""

    def provider(_context: Any) -> ControlledLLMPlanner:
        return ControlledLLMPlanner(client)

    return provider


def _quadratic_path_controlled_draft(planner_payload: dict[str, Any]) -> dict[str, Any]:
    """生成二次函数路径最值 family 的 payload-driven controlled draft。

    这个 fake 仍是“南开同构题”的黄金样板，但不再写死 D/M/N/F/G 或 i/ii/ii_1/ii_2。
    它只从 payload 暴露的 QuestionGoal、PlanningSignal、relation_graph 和 visible path
    中解析角色，然后用受控 binding 生成完整 draft。
    """

    roles = _resolve_quadratic_path_roles(planner_payload)

    def candidate(method_id: str, input_name: str, path: str) -> str:
        return _candidate_id_from_payload(planner_payload, method_id, input_name, path)

    return {
        "context_declarations": [
            {
                "path": roles["result_path"],
                "type": "PointRef",
                "name": roles["result_name"],
                "definition_intent": "line_intersection",
                "scope_id": roles["main_scope"],
            },
            {
                "path": roles["auxiliary_path"],
                "type": "PointRef",
                "name": roles["auxiliary_name"],
                "definition_intent": "straightening_auxiliary_point",
                "scope_id": roles["main_scope"],
            },
        ],
        "steps": [
            _draft_step(
                "derive_axis_point",
                "problem",
                "derive_axis_point",
                roles["axis_path"],
                "quadratic_axis_from_relation",
                {
                    "coefficient_relation": candidate(
                        "quadratic_axis_from_relation",
                        "coefficient_relation",
                        "$problem.equations.coefficient_relation",
                    ),
                    "a": candidate("quadratic_axis_from_relation", "a", "$problem.symbols.a"),
                    "b": candidate("quadratic_axis_from_relation", "b", "$problem.symbols.b"),
                    "target": candidate(
                        "quadratic_axis_from_relation",
                        "target",
                        roles["axis_path"],
                    ),
                },
                {"axis_point": roles["axis_path"]},
                reason="由系数关系先求对称轴与 x 轴交点。",
            ),
            _draft_step(
                "derive_part_i_parabola",
                roles["part_i_scope"],
                "derive_part_i_parabola",
                roles["part_i_parabola_path"],
                "quadratic_from_constraints",
                {
                    "quadratic": candidate(
                        "quadratic_from_constraints",
                        "quadratic",
                        "$problem.expressions.quadratic",
                    ),
                    "x": candidate("quadratic_from_constraints", "x", "$problem.symbols.x"),
                    "coefficient_relation": candidate(
                        "quadratic_from_constraints",
                        "coefficient_relation",
                        "$problem.equations.coefficient_relation",
                    ),
                    "known_coefficients": candidate(
                        "quadratic_from_constraints",
                        "known_coefficients",
                        f"$question.{roles['part_i_scope']}.coefficients.known",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                },
                {"parabola": roles["part_i_parabola_path"]},
                reason="代入第一问已知系数和系数关系求抛物线。",
            ),
            _draft_step(
                "derive_constructed_point_candidates",
                roles["main_scope"],
                "derive_point_candidates",
                f"$question.{roles['main_scope']}.outputs.constructed_point_candidates",
                "right_angle_equal_length_candidates",
                {
                    "anchor": candidate(
                        "right_angle_equal_length_candidates",
                        "anchor",
                        roles["axis_path"],
                    ),
                    "reference": candidate(
                        "right_angle_equal_length_candidates",
                        "reference",
                        roles["reference_path"],
                    ),
                    "target": candidate(
                        "right_angle_equal_length_candidates",
                        "target",
                        roles["target_path"],
                    ),
                },
                {
                    "candidates": (
                        f"$question.{roles['main_scope']}.outputs.constructed_point_candidates"
                    )
                },
                reason="由直角等长关系构造未知点的两个候选点。",
            ),
            _draft_step(
                "select_constructed_point",
                roles["main_scope"],
                "derive_point_coordinate",
                roles["target_path"],
                "select_point_by_quadrant_constraint",
                {
                    "candidates": "@step.derive_constructed_point_candidates.candidates",
                    "target": candidate(
                        "select_point_by_quadrant_constraint",
                        "target",
                        roles["target_path"],
                    ),
                    "quadrant": candidate(
                        "select_point_by_quadrant_constraint",
                        "quadrant",
                        roles["orientation_path"],
                    ),
                    "parameter": candidate(
                        "select_point_by_quadrant_constraint",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_constraint": candidate(
                        "select_point_by_quadrant_constraint",
                        "parameter_constraint",
                        "$problem.constraints.m",
                    ),
                },
                {"selected_point": roles["target_path"]},
                depends_on=["derive_constructed_point_candidates"],
                reason="结合方位约束和参数范围筛选正确的构造点。",
            ),
            _draft_step(
                "derive_q1_parameter",
                roles["q1_scope"],
                "derive_q1_parameter",
                f"$subquestion.{roles['q1_scope']}.outputs.m",
                "parameter_from_segment_length",
                {
                    "p1": candidate(
                        "parameter_from_segment_length",
                        "p1",
                        roles["reference_path"],
                    ),
                    "p2": "@step.select_constructed_point.selected_point",
                    "parameter": candidate(
                        "parameter_from_segment_length",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "condition": candidate(
                        "parameter_from_segment_length",
                        "condition",
                        roles["q1_length_condition_path"],
                    ),
                    "constraint": candidate(
                        "parameter_from_segment_length",
                        "constraint",
                        "$problem.constraints.m",
                    ),
                },
                {"parameter_value": f"$subquestion.{roles['q1_scope']}.outputs.m"},
                depends_on=["select_constructed_point"],
                reason="由第一小问的长度条件求参数。",
            ),
            _draft_step(
                "derive_q1_parabola",
                roles["q1_scope"],
                "derive_q1_parabola",
                roles["q1_parabola_path"],
                "quadratic_from_constraints",
                {
                    "quadratic": candidate(
                        "quadratic_from_constraints",
                        "quadratic",
                        "$problem.expressions.quadratic",
                    ),
                    "x": candidate("quadratic_from_constraints", "x", "$problem.symbols.x"),
                    "p1": candidate(
                        "quadratic_from_constraints",
                        "p1",
                        roles["reference_path"],
                    ),
                    "p2": "@step.select_constructed_point.selected_point",
                    "coefficient_relation": candidate(
                        "quadratic_from_constraints",
                        "coefficient_relation",
                        "$problem.equations.coefficient_relation",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                    "parameter": candidate(
                        "quadratic_from_constraints",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_value": "@step.derive_q1_parameter.parameter_value",
                },
                {
                    "coefficients": f"$subquestion.{roles['q1_scope']}.outputs.coefficients",
                    "parabola": roles["q1_parabola_path"],
                },
                depends_on=["select_constructed_point", "derive_q1_parameter"],
                reason="代入曲线上两点和参数值，得到第一小问抛物线。",
            ),
            _draft_step(
                "derive_midpoint",
                roles["main_scope"],
                "derive_midpoint_coordinate",
                roles["midpoint_path"],
                "midpoint_point",
                {
                    "p1": "@step.derive_axis_point.axis_point",
                    "p2": "@step.select_constructed_point.selected_point",
                    "target": candidate("midpoint_point", "target", roles["midpoint_path"]),
                },
                {"midpoint": roles["midpoint_path"]},
                depends_on=["derive_axis_point", "select_constructed_point"],
                reason="由两端点求中点。",
            ),
            _draft_step(
                "reduce_path",
                roles["main_scope"],
                "reduce_two_moving_point_path",
                f"$question.{roles['main_scope']}.outputs.path_transformation",
                "two_moving_points_path_reduction",
                {
                    "original_path": candidate(
                        "two_moving_points_path_reduction",
                        "original_path",
                        "$problem.conditions.path_minimum",
                    ),
                    "first_moving_membership": candidate(
                        "two_moving_points_path_reduction",
                        "first_moving_membership",
                        roles["first_membership_path"],
                    ),
                    "second_moving_membership": candidate(
                        "two_moving_points_path_reduction",
                        "second_moving_membership",
                        roles["second_membership_path"],
                    ),
                    "binding_relation": candidate(
                        "two_moving_points_path_reduction",
                        "binding_relation",
                        roles["binding_relation_path"],
                    ),
                    "first_segment_start": "@step.derive_axis_point.axis_point",
                    "joint_point": candidate(
                        "two_moving_points_path_reduction",
                        "joint_point",
                        roles["reference_path"],
                    ),
                    "second_segment_end": "@step.select_constructed_point.selected_point",
                },
                {
                    "path_transformation": (
                        f"$question.{roles['main_scope']}.outputs.path_transformation"
                    )
                },
                depends_on=["derive_axis_point", "select_constructed_point"],
                reason="把两动点路径转化成单动点路径。",
            ),
            _draft_step(
                "derive_straightening_candidates",
                roles["main_scope"],
                "derive_broken_path_straightening_candidates",
                f"$question.{roles['main_scope']}.outputs.straightening_candidates",
                "broken_path_straightening_candidates",
                {
                    "path_transformation": "@step.reduce_path.path_transformation",
                    "moving_point_membership": candidate(
                        "broken_path_straightening_candidates",
                        "moving_point_membership",
                        roles["second_membership_path"],
                    ),
                    "fixed_point_1": "@step.derive_axis_point.axis_point",
                    "fixed_point_2": "@step.derive_midpoint.midpoint",
                    "line_point_1": candidate(
                        "broken_path_straightening_candidates",
                        "line_point_1",
                        roles["reference_path"],
                    ),
                    "line_point_2": "@step.select_constructed_point.selected_point",
                },
                {
                    "candidates": (
                        f"$question.{roles['main_scope']}.outputs.straightening_candidates"
                    )
                },
                depends_on=[
                    "reduce_path",
                    "derive_axis_point",
                    "select_constructed_point",
                    "derive_midpoint",
                ],
                reason="构造折线路径拉直候选。",
            ),
            _draft_step(
                "select_straightening_candidate",
                roles["main_scope"],
                "select_broken_path_straightening_candidate",
                roles["auxiliary_path"],
                "select_straightening_candidate",
                {
                    "candidates": "@step.derive_straightening_candidates.candidates",
                    "target": f"@declaration.{roles['main_scope']}.{roles['auxiliary_name']}",
                },
                {
                    "selected_candidate": (
                        f"$question.{roles['main_scope']}.outputs.straightening_candidate"
                    ),
                    "auxiliary_point": roles["auxiliary_path"],
                },
                depends_on=["derive_straightening_candidates"],
                reason="选择便于计算的拉直辅助点。",
            ),
            _draft_step(
                "derive_minimum_expression",
                roles["q1_scope"],
                "derive_minimum_expression",
                f"$question.{roles['main_scope']}.outputs.minimum_expression",
                "distance_between_points",
                {
                    "p1": "@step.select_straightening_candidate.auxiliary_point",
                    "p2": "@step.derive_midpoint.midpoint",
                    "parameter": candidate(
                        "distance_between_points",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_value": "@step.derive_q1_parameter.parameter_value",
                },
                {
                    "distance": f"$question.{roles['main_scope']}.outputs.minimum_expression",
                    "evaluated_distance": roles["q1_minimum_path"],
                },
                depends_on=[
                    "select_straightening_candidate",
                    "derive_midpoint",
                    "derive_q1_parameter",
                ],
                reason="用拉直后的线段长度表示路径最小值。",
            ),
            _draft_step(
                "derive_q2_parameter",
                roles["q2_scope"],
                "derive_q2_parameter",
                f"$subquestion.{roles['q2_scope']}.outputs.m",
                "parameter_from_minimum_value",
                {
                    "minimum_expression": "@step.derive_minimum_expression.distance",
                    "condition": candidate(
                        "parameter_from_minimum_value",
                        "condition",
                        roles["q2_minimum_condition_path"],
                    ),
                    "parameter": candidate(
                        "parameter_from_minimum_value",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "constraint": candidate(
                        "parameter_from_minimum_value",
                        "constraint",
                        "$problem.constraints.m",
                    ),
                },
                {"parameter_value": f"$subquestion.{roles['q2_scope']}.outputs.m"},
                depends_on=["derive_minimum_expression"],
                reason="由第二小问的最小值条件反求参数。",
            ),
            _draft_step(
                "derive_q2_parabola",
                roles["q2_scope"],
                "derive_q2_parabola",
                roles["q2_parabola_path"],
                "quadratic_from_constraints",
                {
                    "quadratic": candidate(
                        "quadratic_from_constraints",
                        "quadratic",
                        "$problem.expressions.quadratic",
                    ),
                    "x": candidate("quadratic_from_constraints", "x", "$problem.symbols.x"),
                    "p1": candidate(
                        "quadratic_from_constraints",
                        "p1",
                        roles["reference_path"],
                    ),
                    "p2": "@step.select_constructed_point.selected_point",
                    "coefficient_relation": candidate(
                        "quadratic_from_constraints",
                        "coefficient_relation",
                        "$problem.equations.coefficient_relation",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                    "parameter": candidate(
                        "quadratic_from_constraints",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_value": "@step.derive_q2_parameter.parameter_value",
                },
                {
                    "coefficients": f"$subquestion.{roles['q2_scope']}.outputs.coefficients",
                    "parabola": roles["q2_parabola_path"],
                },
                depends_on=["select_constructed_point", "derive_q2_parameter"],
                reason="代入第二小问参数得到抛物线。",
            ),
            _draft_step(
                "derive_intersection",
                roles["q2_scope"],
                "derive_q2_intersection",
                roles["result_path"],
                "line_intersection_point",
                {
                    "line1_p1": candidate(
                        "line_intersection_point",
                        "line1_p1",
                        roles["reference_path"],
                    ),
                    "line1_p2": "@step.select_constructed_point.selected_point",
                    "line2_p1": "@step.select_straightening_candidate.auxiliary_point",
                    "line2_p2": "@step.derive_midpoint.midpoint",
                    "target": f"@declaration.{roles['main_scope']}.{roles['result_name']}",
                    "parameter": candidate(
                        "line_intersection_point",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_value": "@step.derive_q2_parameter.parameter_value",
                },
                {"intersection": roles["result_path"]},
                depends_on=[
                    "select_constructed_point",
                    "select_straightening_candidate",
                    "derive_midpoint",
                    "derive_q2_parameter",
                ],
                reason="求曲线动点连线与拉直线段的交点。",
            ),
        ],
    }


def _hexi25_controlled_draft(planner_payload: dict[str, Any]) -> dict[str, Any]:
    """生成河西 25 weighted family 的完整 controlled draft。"""

    def candidate(method_id: str, input_name: str, path: str) -> str:
        return _candidate_id_from_payload(planner_payload, method_id, input_name, path)

    return {
        "context_declarations": [
            {
                "path": "$question.iii.points.Q",
                "type": "PointRef",
                "name": "Q",
                "definition_intent": "weighted_path_auxiliary_point",
                "scope_id": "iii",
            }
        ],
        "steps": [
            _draft_step(
                "hexi_i_parabola",
                "i",
                "derive_i_parabola",
                "$question.i.outputs.parabola",
                "quadratic_from_constraints",
                {
                    "quadratic": candidate(
                        "quadratic_from_constraints",
                        "quadratic",
                        "$problem.expressions.quadratic",
                    ),
                    "x": candidate("quadratic_from_constraints", "x", "$problem.symbols.x"),
                    "known_coefficients": candidate(
                        "quadratic_from_constraints",
                        "known_coefficients",
                        "$question.i.coefficients.known",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                },
                {
                    "coefficients": "$question.i.outputs.coefficients",
                    "parabola": "$question.i.outputs.parabola",
                },
                reason="代入第一问已知系数求抛物线。",
            ),
            _draft_step(
                "hexi_i_vertex",
                "i",
                "derive_i_vertex",
                "$question.i.points.P",
                "quadratic_vertex_point",
                {
                    "parabola": "@step.hexi_i_parabola.parabola",
                    "x": candidate("quadratic_vertex_point", "x", "$problem.symbols.x"),
                    "target": candidate(
                        "quadratic_vertex_point",
                        "target",
                        "$question.i.points.P",
                    ),
                },
                {"point": "$question.i.points.P"},
                depends_on=["hexi_i_parabola"],
                reason="由抛物线求顶点 P。",
            ),
            _draft_step(
                "hexi_ii_parametric_parabola",
                "ii",
                "derive_ii_parametric_parabola",
                "$question.ii.outputs.parametric_parabola",
                "quadratic_from_constraints",
                {
                    "quadratic": candidate(
                        "quadratic_from_constraints",
                        "quadratic",
                        "$problem.expressions.quadratic",
                    ),
                    "x": candidate("quadratic_from_constraints", "x", "$problem.symbols.x"),
                    "known_coefficients": candidate(
                        "quadratic_from_constraints",
                        "known_coefficients",
                        "$question.ii.coefficients.known",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                    "curve_point": candidate(
                        "quadratic_from_constraints",
                        "curve_point",
                        "$problem.points.A",
                    ),
                    "free_parameter": candidate(
                        "quadratic_from_constraints",
                        "free_parameter",
                        "$problem.symbols.b",
                    ),
                },
                {
                    "coefficients": "$question.ii.outputs.parametric_coefficients",
                    "parabola": "$question.ii.outputs.parametric_parabola",
                },
                reason="先代入 a 和 A 点，得到只含 b 的当前问抛物线。",
            ),
            _draft_step(
                "hexi_ii_C",
                "ii",
                "derive_ii_y_axis_intercept",
                "$question.ii.points.C",
                "quadratic_y_axis_intercept_point",
                {
                    "quadratic": "@step.hexi_ii_parametric_parabola.parabola",
                    "x": candidate(
                        "quadratic_y_axis_intercept_point",
                        "x",
                        "$problem.symbols.x",
                    ),
                    "target": candidate(
                        "quadratic_y_axis_intercept_point",
                        "target",
                        "$question.ii.points.C",
                    ),
                },
                {"point": "$question.ii.points.C"},
                depends_on=["hexi_ii_parametric_parabola"],
                reason="由当前问抛物线求 y 轴交点 C。",
            ),
            _draft_step(
                "hexi_ii_D_candidates",
                "ii",
                "derive_ii_D_candidates",
                "$question.ii.outputs.D_candidates",
                "right_angle_equal_length_candidates",
                {
                    "anchor": candidate(
                        "right_angle_equal_length_candidates",
                        "anchor",
                        "$problem.points.A",
                    ),
                    "reference": "@step.hexi_ii_C.point",
                    "target": candidate(
                        "right_angle_equal_length_candidates",
                        "target",
                        "$question.ii.points.D",
                    ),
                },
                {"candidates": "$question.ii.outputs.D_candidates"},
                depends_on=["hexi_ii_C"],
                reason="由直角等长条件列出 D 的候选点。",
            ),
            _draft_step(
                "hexi_ii_filter_D_candidates",
                "ii",
                "filter_ii_D_candidates",
                "$question.ii.outputs.filtered_D_candidates",
                "filter_point_candidates_by_quadratic_curve",
                {
                    "candidates": "@step.hexi_ii_D_candidates.candidates",
                    "target": candidate(
                        "filter_point_candidates_by_quadratic_curve",
                        "target",
                        "$question.ii.points.D",
                    ),
                    "parabola": "@step.hexi_ii_parametric_parabola.parabola",
                    "x": candidate(
                        "filter_point_candidates_by_quadratic_curve",
                        "x",
                        "$problem.symbols.x",
                    ),
                    "parameter": candidate(
                        "filter_point_candidates_by_quadratic_curve",
                        "parameter",
                        "$problem.symbols.b",
                    ),
                    "parameter_constraint": candidate(
                        "filter_point_candidates_by_quadratic_curve",
                        "parameter_constraint",
                        "$problem.constraints.b",
                    ),
                },
                {
                    "filtered_candidates": "$question.ii.outputs.filtered_D_candidates",
                    "rejected_candidates": "$question.ii.outputs.rejected_D_candidates",
                },
                depends_on=["hexi_ii_D_candidates", "hexi_ii_parametric_parabola"],
                reason="把候选 D 代入当前问抛物线，先排除不可能分支。",
            ),
            _draft_step(
                "hexi_ii_D",
                "ii",
                "derive_ii_D_and_coefficients",
                "$question.ii.points.D",
                "select_curve_point_candidate_and_solve_coefficients",
                {
                    "candidates": "@step.hexi_ii_filter_D_candidates.filtered_candidates",
                    "target": candidate(
                        "select_curve_point_candidate_and_solve_coefficients",
                        "target",
                        "$question.ii.points.D",
                    ),
                    "quadratic": "@step.hexi_ii_parametric_parabola.parabola",
                    "x": candidate(
                        "select_curve_point_candidate_and_solve_coefficients",
                        "x",
                        "$problem.symbols.x",
                    ),
                    "coefficient_dependencies": (
                        "@step.hexi_ii_parametric_parabola.coefficients"
                    ),
                    "primary_symbol": candidate(
                        "select_curve_point_candidate_and_solve_coefficients",
                        "primary_symbol",
                        "$problem.symbols.b",
                    ),
                    "secondary_symbol": candidate(
                        "select_curve_point_candidate_and_solve_coefficients",
                        "secondary_symbol",
                        "$problem.symbols.c",
                    ),
                    "primary_constraint": candidate(
                        "select_curve_point_candidate_and_solve_coefficients",
                        "primary_constraint",
                        "$problem.constraints.b",
                    ),
                },
                {
                    "point": "$question.ii.points.D",
                    "coefficients": "$question.ii.outputs.coefficients",
                    "primary_value": "$question.ii.outputs.b",
                    "secondary_value": "$question.ii.outputs.c",
                    "parabola": "$question.ii.outputs.parabola",
                },
                depends_on=[
                    "hexi_ii_filter_D_candidates",
                    "hexi_ii_parametric_parabola",
                ],
                reason="用曲线条件和参数约束筛选唯一 D，并求 b、c。",
            ),
            _draft_step(
                "hexi_iii_parametric_parabola",
                "iii",
                "derive_iii_parametric_parabola",
                "$question.iii.outputs.parametric_parabola",
                "quadratic_from_constraints",
                {
                    "quadratic": candidate(
                        "quadratic_from_constraints",
                        "quadratic",
                        "$problem.expressions.quadratic",
                    ),
                    "x": candidate("quadratic_from_constraints", "x", "$problem.symbols.x"),
                    "known_coefficients": candidate(
                        "quadratic_from_constraints",
                        "known_coefficients",
                        "$question.iii.coefficients.known",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                    "curve_point": candidate(
                        "quadratic_from_constraints",
                        "curve_point",
                        "$problem.points.A",
                    ),
                    "free_parameter": candidate(
                        "quadratic_from_constraints",
                        "free_parameter",
                        "$problem.symbols.b",
                    ),
                },
                {
                    "coefficients": "$question.iii.outputs.coefficients",
                    "parabola": "$question.iii.outputs.parametric_parabola",
                },
                reason="第 III 问先化简出含 b 的抛物线。",
            ),
            _draft_step(
                "hexi_iii_M",
                "iii",
                "derive_iii_M",
                "$question.iii.points.M",
                "point_on_parabola_at_x",
                {
                    "parabola": "@step.hexi_iii_parametric_parabola.parabola",
                    "x": candidate("point_on_parabola_at_x", "x", "$problem.symbols.x"),
                    "target": candidate(
                        "point_on_parabola_at_x",
                        "target",
                        "$question.iii.points.M",
                    ),
                },
                {"point": "$question.iii.points.M"},
                depends_on=["hexi_iii_parametric_parabola"],
                reason="由横坐标把 M 代入当前抛物线。",
            ),
            _draft_step(
                "hexi_iii_triangle_transform",
                "iii",
                "derive_weighted_path_transform",
                "$question.iii.outputs.path_transformation",
                "weighted_axis_path_triangle_transform",
                {
                    "condition": candidate(
                        "weighted_axis_path_triangle_transform",
                        "condition",
                        "$question.iii.conditions.minimum_value",
                    ),
                    "fixed_point": candidate(
                        "weighted_axis_path_triangle_transform",
                        "fixed_point",
                        "$problem.points.A",
                    ),
                    "moving_point": candidate(
                        "weighted_axis_path_triangle_transform",
                        "moving_point",
                        "$question.iii.points.N",
                    ),
                    "dynamic_parameter": candidate(
                        "weighted_axis_path_triangle_transform",
                        "dynamic_parameter",
                        "$problem.symbols.n",
                    ),
                    "auxiliary_point_ref": "@declaration.iii.Q",
                },
                {
                    "auxiliary_point": "$question.iii.points.Q",
                    "path_transformation": "$question.iii.outputs.path_transformation",
                    "auxiliary_locus": "$question.iii.outputs.auxiliary_locus",
                },
                reason="构造辅助直角三角形，把加权路径转成等倍率折线路径。",
            ),
            _draft_step(
                "hexi_iii_weighted_minimum",
                "iii",
                "derive_iii_weighted_minimum",
                "$question.iii.outputs.b",
                "linked_broken_path_geometric_minimum",
                {
                    "condition": candidate(
                        "linked_broken_path_geometric_minimum",
                        "condition",
                        "$question.iii.conditions.minimum_value",
                    ),
                    "path_transformation": (
                        "@step.hexi_iii_triangle_transform.path_transformation"
                    ),
                    "auxiliary_locus": "@step.hexi_iii_triangle_transform.auxiliary_locus",
                    "fixed_point": candidate(
                        "linked_broken_path_geometric_minimum",
                        "fixed_point",
                        "$problem.points.A",
                    ),
                    "curve_point": "@step.hexi_iii_M.point",
                    "moving_point": candidate(
                        "linked_broken_path_geometric_minimum",
                        "moving_point",
                        "$question.iii.points.N",
                    ),
                    "auxiliary_point": "@step.hexi_iii_triangle_transform.auxiliary_point",
                    "parameter": candidate(
                        "linked_broken_path_geometric_minimum",
                        "parameter",
                        "$problem.symbols.b",
                    ),
                    "dynamic_parameter": candidate(
                        "linked_broken_path_geometric_minimum",
                        "dynamic_parameter",
                        "$problem.symbols.n",
                    ),
                    "parameter_constraint": candidate(
                        "linked_broken_path_geometric_minimum",
                        "parameter_constraint",
                        "$problem.constraints.b",
                    ),
                    "dynamic_constraint": candidate(
                        "linked_broken_path_geometric_minimum",
                        "dynamic_constraint",
                        "$problem.constraints.n",
                    ),
                },
                {
                    "parameter_value": "$question.iii.outputs.b",
                    "dynamic_parameter_value": "$question.iii.outputs.n",
                    "minimum_value": "$question.iii.outputs.min_value",
                    "dynamic_point": "$question.iii.outputs.N",
                },
                depends_on=[
                    "hexi_iii_M",
                    "hexi_iii_triangle_transform",
                ],
                reason="用辅助点轨迹的最短距离反求 b 和动点 N。",
            ),
        ],
    }


def _resolve_quadratic_path_roles(planner_payload: dict[str, Any]) -> dict[str, str]:
    """从 payload 中解析南开同构题的核心角色和 ContextPath。"""
    constructible = _single_signal(
        planner_payload,
        "constructible_right_angle_equal_length_point",
    )
    orientation = _single_signal(planner_payload, "orientation_constraint")
    main_scope = str(constructible["scope_id"])
    relation_roles = dict(constructible.get("roles", {}))
    axis_name = _required_role(relation_roles, "anchor")
    reference_name = _required_role(relation_roles, "reference")
    target_name = _required_role(relation_roles, "target")
    axis_path = _point_path(planner_payload, axis_name)
    target_path = str(constructible["path"])
    q1_scope = _question_with_goal_type(planner_payload, "MinimumExpression")
    result_goal = _result_point_goal(planner_payload, exclude_path=axis_path)
    q2_scope = str(result_goal["question_id"])
    result_path = str(result_goal["target_path"])
    first_moving_name, second_moving_name = _moving_point_names(
        planner_payload,
        axis_name=axis_name,
        target_name=target_name,
    )
    part_i_scope = _question_for_answer_key(planner_payload, axis_name)
    auxiliary_name = f"{axis_name}_prime"
    return {
        "main_scope": main_scope,
        "axis_path": axis_path,
        "reference_path": _point_path(planner_payload, reference_name, scope_id=main_scope),
        "target_path": target_path,
        "midpoint_path": _midpoint_path(
            planner_payload,
            main_scope,
            axis_name,
            target_name,
        ),
        "orientation_path": str(orientation["path"]),
        "part_i_scope": part_i_scope,
        "part_i_parabola_path": _goal_path(planner_payload, part_i_scope, "Parabola"),
        "q1_scope": q1_scope,
        "q1_parabola_path": _goal_path(planner_payload, q1_scope, "Parabola"),
        "q1_minimum_path": _goal_path(planner_payload, q1_scope, "MinimumExpression"),
        "q1_length_condition_path": _condition_path(
            planner_payload,
            key="length_squared",
            scope_id=q1_scope,
        ),
        "q2_scope": q2_scope,
        "q2_parabola_path": _goal_path(planner_payload, q2_scope, "Parabola"),
        "q2_minimum_condition_path": _condition_path(
            planner_payload,
            key="minimum_value",
            scope_id=q2_scope,
        ),
        "first_membership_path": _condition_path(
            planner_payload,
            key=f"segment_membership_{first_moving_name}",
        ),
        "second_membership_path": _condition_path(
            planner_payload,
            key=f"segment_membership_{second_moving_name}",
        ),
        "binding_relation_path": _condition_path_prefix(
            planner_payload,
            "segment_relation_",
        ),
        "result_path": result_path,
        "result_name": _path_key(result_path),
        "auxiliary_path": f"$question.{main_scope}.points.{auxiliary_name}",
        "auxiliary_name": auxiliary_name,
    }


def _single_signal(planner_payload: dict[str, Any], signal_type: str) -> dict[str, Any]:
    """读取唯一的 planning signal。"""
    matches = [
        signal for signal in planner_payload.get("planning_signals", [])
        if isinstance(signal, dict) and signal.get("signal_type") == signal_type
    ]
    if len(matches) != 1:
        raise AbstractPlanValidationError(
            f"expected exactly one planning signal {signal_type}, got {len(matches)}"
        )
    return matches[0]


def _required_role(roles: dict[str, Any], key: str) -> str:
    """读取 relation role，缺失时给出 fake draft 诊断。"""
    value = str(roles.get(key, ""))
    if not value:
        raise AbstractPlanValidationError(f"missing planning role: {key}")
    return value


def _question_for_answer_key(planner_payload: dict[str, Any], answer_key: str) -> str:
    """按最终答案 key 查找所属 question。"""
    for goal in planner_payload.get("question_goals", []):
        if isinstance(goal, dict) and goal.get("answer_key") == answer_key:
            return str(goal["question_id"])
    raise AbstractPlanValidationError(f"question goal not found for answer_key={answer_key}")


def _question_with_goal_type(planner_payload: dict[str, Any], value_type: str) -> str:
    """查找拥有某类答案目标的 question。"""
    for goal in planner_payload.get("question_goals", []):
        if isinstance(goal, dict) and goal.get("value_type") == value_type:
            return str(goal["question_id"])
    raise AbstractPlanValidationError(f"question goal not found for value_type={value_type}")


def _goal_path(planner_payload: dict[str, Any], question_id: str, value_type: str) -> str:
    """查找某 question 下某类型答案的 target_path。"""
    for goal in planner_payload.get("question_goals", []):
        if (
            isinstance(goal, dict)
            and goal.get("question_id") == question_id
            and goal.get("value_type") == value_type
        ):
            return str(goal["target_path"])
    raise AbstractPlanValidationError(
        f"question goal path not found for {question_id}.{value_type}"
    )


def _result_point_goal(
    planner_payload: dict[str, Any],
    *,
    exclude_path: str,
) -> dict[str, Any]:
    """查找第二小问要求输出的交点答案。"""
    for goal in planner_payload.get("question_goals", []):
        if (
            isinstance(goal, dict)
            and goal.get("value_type") == "Point"
            and goal.get("target_path") != exclude_path
        ):
            return goal
    raise AbstractPlanValidationError("result point question goal not found")


def _point_path(
    planner_payload: dict[str, Any],
    name: str,
    *,
    scope_id: str | None = None,
) -> str:
    """按点名和可选 scope 查找 visible point path。"""
    matches = [
        path for path in planner_payload.get("visible_paths", [])
        if (
            isinstance(path, dict)
            and path.get("container") == "points"
            and path.get("key") == name
            and (scope_id is None or path.get("scope_id") == scope_id)
        )
    ]
    if len(matches) != 1:
        raise AbstractPlanValidationError(
            f"point path not uniquely resolved for name={name}, scope={scope_id}: {len(matches)}"
        )
    return str(matches[0]["path"])


def _midpoint_path(
    planner_payload: dict[str, Any],
    scope_id: str,
    axis_name: str,
    target_name: str,
) -> str:
    """查找 midpoint PointRef。"""
    expected = {axis_name, target_name}
    matches = []
    for path in planner_payload.get("visible_paths", []):
        if not isinstance(path, dict):
            continue
        definition = path.get("definition", {})
        if not isinstance(definition, dict):
            definition = {}
        dependencies = _definition_point_tokens(definition.get("of"))
        if (
            path.get("container") == "points"
            and path.get("scope_id") == scope_id
            and path.get("type") == "PointRef"
            and definition.get("definition") == "midpoint"
            and expected.issubset(set(dependencies))
        ):
            matches.append(path)
    if len(matches) != 1:
        raise AbstractPlanValidationError(
            f"midpoint path not uniquely resolved for {sorted(expected)}: {len(matches)}"
        )
    return str(matches[0]["path"])


def _condition_path(
    planner_payload: dict[str, Any],
    *,
    key: str,
    scope_id: str | None = None,
) -> str:
    """按 condition key 查找 visible condition/constraint path。"""
    matches = [
        path for path in planner_payload.get("visible_paths", [])
        if (
            isinstance(path, dict)
            and path.get("container") in {"conditions", "constraints"}
            and path.get("key") == key
            and (scope_id is None or path.get("scope_id") == scope_id)
        )
    ]
    if len(matches) != 1:
        raise AbstractPlanValidationError(
            f"condition path not uniquely resolved for key={key}, scope={scope_id}: {len(matches)}"
        )
    return str(matches[0]["path"])


def _condition_path_prefix(planner_payload: dict[str, Any], prefix: str) -> str:
    """按 condition key 前缀查找唯一 path。"""
    matches = [
        path for path in planner_payload.get("visible_paths", [])
        if (
            isinstance(path, dict)
            and path.get("container") == "conditions"
            and str(path.get("key", "")).startswith(prefix)
        )
    ]
    if len(matches) != 1:
        raise AbstractPlanValidationError(
            f"condition path not uniquely resolved for prefix={prefix}: {len(matches)}"
        )
    return str(matches[0]["path"])


def _moving_point_names(
    planner_payload: dict[str, Any],
    *,
    axis_name: str,
    target_name: str,
) -> tuple[str, str]:
    """从 segment_relation 推断两个动点名。"""
    relations = [
        relation for relation in planner_payload.get("relation_graph", [])
        if isinstance(relation, dict) and relation.get("relation_type") == "segment_relation"
    ]
    if len(relations) != 1:
        raise AbstractPlanValidationError(
            f"expected exactly one segment_relation, got {len(relations)}"
        )
    roles = dict(relations[0].get("roles", {}))
    first = _single_token_except(_extract_point_tokens(str(roles.get("left", ""))), axis_name)
    second = _single_token_except(
        _extract_point_tokens(str(roles.get("right", ""))),
        target_name,
    )
    return first, second


def _single_token_except(tokens: list[str], excluded: str) -> str:
    """从 token 列表中取唯一一个非 excluded 点名。"""
    candidates = [token for token in tokens if token != excluded]
    if len(candidates) != 1:
        raise AbstractPlanValidationError(
            f"cannot resolve moving point from tokens={tokens}, excluded={excluded}"
        )
    return candidates[0]


def _extract_point_tokens(text: str) -> list[str]:
    """从线段表达式中提取点名 token。

    当前 fixture 仍以单大写字母为主；这里放宽到 ``D_prime``、``P1`` 这类常见点名，
    但不处理中文点名。中文点名后续应由 ProblemIR 解析阶段提供结构化 participants。
    """
    return re.findall(r"[A-Z](?:_[A-Za-z0-9]+|[0-9]+|[a-z]+)?", text)


def _definition_point_tokens(value: Any) -> list[str]:
    """从 PointRef.definition 的结构化依赖字段中读取点名。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _path_key(path: str) -> str:
    """返回 ContextPath 最后的 key。"""
    return path.rsplit(".", 1)[-1]


def _draft_step(
    step_id: str,
    scope_id: str,
    goal_type: str,
    target_path: str,
    method_id: str,
    bindings: dict[str, str],
    promote_to: dict[str, str],
    *,
    depends_on: list[str] | None = None,
    reason: str,
) -> dict[str, Any]:
    """生成符合真实 draft schema 的 step 对象。"""
    return {
        "step_id": step_id,
        "scope_id": scope_id,
        "step_goal": {
            "type": goal_type,
            "target_path": target_path,
        },
        "method_id": method_id,
        "bindings": bindings,
        "promote_to": promote_to,
        "depends_on": depends_on or [],
        "reason": reason,
    }


def _candidate_id_from_payload(
    planner_payload: dict[str, Any],
    method_id: str,
    input_name: str,
    path: str,
) -> str:
    """从 payload.slot_options 中按 ContextPath 查找 candidate id。"""
    for option in planner_payload.get("slot_options", []):
        if not isinstance(option, dict):
            continue
        if option.get("method_id") != method_id or option.get("input_name") != input_name:
            continue
        for candidate in option.get("candidates", []):
            if isinstance(candidate, dict) and candidate.get("path") == path:
                return str(candidate["candidate_id"])
    raise AbstractPlanValidationError(
        f"candidate not found for {method_id}.{input_name}: {path}"
    )
