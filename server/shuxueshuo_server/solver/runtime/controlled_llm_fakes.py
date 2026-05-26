"""Controlled LLM Planner 的测试/开发 fake provider。

本模块承载体积较大的黄金题 fake draft，避免 ``controlled_llm_planner`` 核心模块
同时混入测试样板和生产编译逻辑。D2 增加河西 controlled draft 时，也应该继续放在
这里，而不是塞回核心 planner。
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from shuxueshuo_server.solver.family import QUADRATIC_PATH_MINIMUM_FAMILY
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
        """返回 canonical 南开 25 的完整 PlannerDraft JSON。"""
        self.payloads.append(payload)
        if self.response is not None:
            return self.response
        family_id = str(payload.get("family_id", ""))
        if family_id != QUADRATIC_PATH_MINIMUM_FAMILY.family_id:
            raise AbstractPlanValidationError(
                f"fake controlled planner has no draft for family_id={family_id}"
            )
        planner_payload = payload.get("planner_payload")
        if not isinstance(planner_payload, dict):
            raise AbstractPlanValidationError("controlled fake requires planner_payload")
        return json.dumps(
            _nankai25_controlled_draft(planner_payload),
            ensure_ascii=False,
        )


def controlled_llm_planner_provider(
    client: LLMPlannerClient,
) -> Callable[[Any], ControlledLLMPlanner]:
    """创建 RuntimeOrchestrator 可注入的 controlled planner provider。"""

    def provider(_context: Any) -> ControlledLLMPlanner:
        return ControlledLLMPlanner(client)

    return provider


def _nankai25_controlled_draft(planner_payload: dict[str, Any]) -> dict[str, Any]:
    """生成 canonical 南开 25 的完整 controlled draft。

    这是 D1 的 Fake LLM 黄金样板：它仍然是固定南开题的计划，但每个输入槽位都走
    ``candidate_id``、``@step`` 或 ``@declaration``，不会把裸 ContextPath 塞进
    bindings。
    """

    def candidate(method_id: str, input_name: str, path: str) -> str:
        return _candidate_id_from_payload(planner_payload, method_id, input_name, path)

    return {
        "context_declarations": [
            {
                "path": "$question.ii.points.G",
                "type": "PointRef",
                "name": "G",
                "definition_intent": "line_intersection",
                "scope_id": "ii",
            },
            {
                "path": "$question.ii.points.D_prime",
                "type": "PointRef",
                "name": "D_prime",
                "definition_intent": "straightening_auxiliary_point",
                "scope_id": "ii",
            },
        ],
        "steps": [
            _draft_step(
                "derive_D",
                "problem",
                "derive_axis_point",
                "$problem.points.D",
                "quadratic_axis_from_relation",
                {
                    "coefficient_relation": candidate(
                        "quadratic_axis_from_relation",
                        "coefficient_relation",
                        "$problem.equations.coefficient_relation",
                    ),
                    "a": candidate(
                        "quadratic_axis_from_relation",
                        "a",
                        "$problem.symbols.a",
                    ),
                    "b": candidate(
                        "quadratic_axis_from_relation",
                        "b",
                        "$problem.symbols.b",
                    ),
                    "target": candidate(
                        "quadratic_axis_from_relation",
                        "target",
                        "$problem.points.D",
                    ),
                },
                {"axis_point": "$problem.points.D"},
                reason="由系数关系先求对称轴与 x 轴交点。",
            ),
            _draft_step(
                "derive_part_i_parabola",
                "i",
                "derive_part_i_parabola",
                "$question.i.outputs.parabola",
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
                        "$question.i.coefficients.known",
                    ),
                    "all_coefficients": candidate(
                        "quadratic_from_constraints",
                        "all_coefficients",
                        "$problem.symbol_lists.quadratic_coefficients",
                    ),
                },
                {"parabola": "$question.i.outputs.parabola"},
                reason="代入第一问已知系数和系数关系求抛物线。",
            ),
            _draft_step(
                "derive_N_candidates",
                "ii",
                "derive_point_candidates",
                "$question.ii.outputs.N_candidates",
                "right_angle_equal_length_candidates",
                {
                    "anchor": candidate(
                        "right_angle_equal_length_candidates",
                        "anchor",
                        "$problem.points.D",
                    ),
                    "reference": candidate(
                        "right_angle_equal_length_candidates",
                        "reference",
                        "$question.ii.points.M",
                    ),
                    "target": candidate(
                        "right_angle_equal_length_candidates",
                        "target",
                        "$question.ii.points.N",
                    ),
                },
                {"candidates": "$question.ii.outputs.N_candidates"},
                reason="由直角等长关系构造 N 的两个候选点。",
            ),
            _draft_step(
                "derive_N",
                "ii",
                "derive_point_coordinate",
                "$question.ii.points.N",
                "select_point_by_quadrant_constraint",
                {
                    "candidates": "@step.derive_N_candidates.candidates",
                    "target": candidate(
                        "select_point_by_quadrant_constraint",
                        "target",
                        "$question.ii.points.N",
                    ),
                    "quadrant": candidate(
                        "select_point_by_quadrant_constraint",
                        "quadrant",
                        "$question.ii.constraints.N_quadrant",
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
                {"selected_point": "$question.ii.points.N"},
                depends_on=["derive_N_candidates"],
                reason="结合第四象限和 m>2 筛选正确的 N。",
            ),
            _draft_step(
                "derive_q1_m",
                "ii_1",
                "derive_q1_parameter",
                "$subquestion.ii_1.outputs.m",
                "parameter_from_segment_length",
                {
                    "p1": candidate(
                        "parameter_from_segment_length",
                        "p1",
                        "$question.ii.points.M",
                    ),
                    "p2": "@step.derive_N.selected_point",
                    "parameter": candidate(
                        "parameter_from_segment_length",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "condition": candidate(
                        "parameter_from_segment_length",
                        "condition",
                        "$subquestion.ii_1.conditions.length_squared",
                    ),
                    "constraint": candidate(
                        "parameter_from_segment_length",
                        "constraint",
                        "$problem.constraints.m",
                    ),
                },
                {"parameter_value": "$subquestion.ii_1.outputs.m"},
                depends_on=["derive_N"],
                reason="由 MN 的长度条件求第一小问参数。",
            ),
            _draft_step(
                "derive_q1_parabola",
                "ii_1",
                "derive_q1_parabola",
                "$subquestion.ii_1.outputs.parabola",
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
                        "$question.ii.points.M",
                    ),
                    "p2": "@step.derive_N.selected_point",
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
                    "parameter_value": "@step.derive_q1_m.parameter_value",
                },
                {
                    "coefficients": "$subquestion.ii_1.outputs.coefficients",
                    "parabola": "$subquestion.ii_1.outputs.parabola",
                },
                depends_on=["derive_N", "derive_q1_m"],
                reason="代入 M、N 和参数值，得到第一小问抛物线。",
            ),
            _draft_step(
                "derive_F",
                "ii",
                "derive_midpoint_coordinate",
                "$question.ii.points.F",
                "midpoint_point",
                {
                    "p1": "@step.derive_D.axis_point",
                    "p2": "@step.derive_N.selected_point",
                    "target": candidate("midpoint_point", "target", "$question.ii.points.F"),
                },
                {"midpoint": "$question.ii.points.F"},
                depends_on=["derive_D", "derive_N"],
                reason="由 D、N 求中点 F。",
            ),
            _draft_step(
                "reduce_path",
                "ii",
                "reduce_two_moving_point_path",
                "$question.ii.outputs.path_transformation",
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
                        "$problem.conditions.segment_membership_E",
                    ),
                    "second_moving_membership": candidate(
                        "two_moving_points_path_reduction",
                        "second_moving_membership",
                        "$problem.conditions.segment_membership_G",
                    ),
                    "binding_relation": candidate(
                        "two_moving_points_path_reduction",
                        "binding_relation",
                        "$problem.conditions.segment_relation_DE_NG",
                    ),
                    "first_segment_start": "@step.derive_D.axis_point",
                    "joint_point": candidate(
                        "two_moving_points_path_reduction",
                        "joint_point",
                        "$question.ii.points.M",
                    ),
                    "second_segment_end": "@step.derive_N.selected_point",
                },
                {"path_transformation": "$question.ii.outputs.path_transformation"},
                depends_on=["derive_D", "derive_N"],
                reason="把两动点路径转化成单动点路径。",
            ),
            _draft_step(
                "derive_straightening_candidates",
                "ii",
                "derive_broken_path_straightening_candidates",
                "$question.ii.outputs.straightening_candidates",
                "broken_path_straightening_candidates",
                {
                    "path_transformation": "@step.reduce_path.path_transformation",
                    "moving_point_membership": candidate(
                        "broken_path_straightening_candidates",
                        "moving_point_membership",
                        "$problem.conditions.segment_membership_G",
                    ),
                    "fixed_point_1": "@step.derive_D.axis_point",
                    "fixed_point_2": "@step.derive_F.midpoint",
                    "line_point_1": candidate(
                        "broken_path_straightening_candidates",
                        "line_point_1",
                        "$question.ii.points.M",
                    ),
                    "line_point_2": "@step.derive_N.selected_point",
                },
                {"candidates": "$question.ii.outputs.straightening_candidates"},
                depends_on=["reduce_path", "derive_D", "derive_N", "derive_F"],
                reason="构造折线路径拉直候选。",
            ),
            _draft_step(
                "select_straightening_candidate",
                "ii",
                "select_broken_path_straightening_candidate",
                "$question.ii.points.D_prime",
                "select_straightening_candidate",
                {
                    "candidates": "@step.derive_straightening_candidates.candidates",
                    "target": "@declaration.ii.D_prime",
                },
                {
                    "selected_candidate": "$question.ii.outputs.straightening_candidate",
                    "auxiliary_point": "$question.ii.points.D_prime",
                },
                depends_on=["derive_straightening_candidates"],
                reason="选择便于计算的拉直辅助点。",
            ),
            _draft_step(
                "derive_minimum_expression",
                "ii_1",
                "derive_minimum_expression",
                "$question.ii.outputs.minimum_expression",
                "distance_between_points",
                {
                    "p1": "@step.select_straightening_candidate.auxiliary_point",
                    "p2": "@step.derive_F.midpoint",
                    "parameter": candidate(
                        "distance_between_points",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_value": "@step.derive_q1_m.parameter_value",
                },
                {
                    "distance": "$question.ii.outputs.minimum_expression",
                    "evaluated_distance": "$subquestion.ii_1.outputs.min_value",
                },
                depends_on=[
                    "select_straightening_candidate",
                    "derive_F",
                    "derive_q1_m",
                ],
                reason="用拉直后的线段长度表示路径最小值。",
            ),
            _draft_step(
                "derive_q2_m",
                "ii_2",
                "derive_q2_parameter",
                "$subquestion.ii_2.outputs.m",
                "parameter_from_minimum_value",
                {
                    "minimum_expression": "@step.derive_minimum_expression.distance",
                    "condition": candidate(
                        "parameter_from_minimum_value",
                        "condition",
                        "$subquestion.ii_2.conditions.minimum_value",
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
                {"parameter_value": "$subquestion.ii_2.outputs.m"},
                depends_on=["derive_minimum_expression"],
                reason="由第二小问的最小值条件反求 m。",
            ),
            _draft_step(
                "derive_q2_parabola",
                "ii_2",
                "derive_q2_parabola",
                "$subquestion.ii_2.outputs.parabola",
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
                        "$question.ii.points.M",
                    ),
                    "p2": "@step.derive_N.selected_point",
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
                    "parameter_value": "@step.derive_q2_m.parameter_value",
                },
                {
                    "coefficients": "$subquestion.ii_2.outputs.coefficients",
                    "parabola": "$subquestion.ii_2.outputs.parabola",
                },
                depends_on=["derive_N", "derive_q2_m"],
                reason="代入第二小问参数得到抛物线。",
            ),
            _draft_step(
                "derive_G",
                "ii_2",
                "derive_q2_intersection",
                "$question.ii.points.G",
                "line_intersection_point",
                {
                    "line1_p1": candidate(
                        "line_intersection_point",
                        "line1_p1",
                        "$question.ii.points.M",
                    ),
                    "line1_p2": "@step.derive_N.selected_point",
                    "line2_p1": "@step.select_straightening_candidate.auxiliary_point",
                    "line2_p2": "@step.derive_F.midpoint",
                    "target": "@declaration.ii.G",
                    "parameter": candidate(
                        "line_intersection_point",
                        "parameter",
                        "$problem.symbols.m",
                    ),
                    "parameter_value": "@step.derive_q2_m.parameter_value",
                },
                {"intersection": "$question.ii.points.G"},
                depends_on=[
                    "derive_N",
                    "select_straightening_candidate",
                    "derive_F",
                    "derive_q2_m",
                ],
                reason="求 MN 与拉直线段的交点 G。",
            ),
        ],
    }


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
