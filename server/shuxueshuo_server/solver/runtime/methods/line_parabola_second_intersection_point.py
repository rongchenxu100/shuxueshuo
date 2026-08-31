"""line_parabola_second_intersection_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec

from ._common import *
from ._spec import MethodSpecSource, canonical_symbol_input, declare_input_views


class LineParabolaSecondIntersectionPointMethod:
    """由直线两点和已知交点，求直线与抛物线的另一个交点。"""

    method_id = "line_parabola_second_intersection_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        x = inputs["x"]
        line_p1: Point = inputs["line_p1"]
        line_p2: Point = inputs["line_p2"]
        known_point: Point = inputs["known_point"]
        target: PointRef = inputs["target"]

        if sp.simplify(line_p1[0] - line_p2[0]) == 0:
            raise method_precondition_failed(
                "line-parabola second-intersection requires a nonvertical line",
                subjects=(
                    FunctionalDiagnosticSubject(
                        role="line_point_1",
                        arg_name="line_p1",
                        expected_type="Point",
                    ),
                    FunctionalDiagnosticSubject(
                        role="line_point_2",
                        arg_name="line_p2",
                        expected_type="Point",
                    ),
                ),
                expected={"line_state": "nonvertical"},
                observed={
                    "line_state": "vertical",
                    "x_coordinate": kernel.sstr(line_p1[0]),
                },
                repair_action="choose_applicable_intersection_capability",
            )
        slope = sp.simplify((line_p2[1] - line_p1[1]) / (line_p2[0] - line_p1[0]))
        line_expr = sp.simplify(line_p1[1] + slope * (x - line_p1[0]))
        roots = [
            sp.simplify(root)
            for root in kernel.solve_values(sp.Eq(parabola, line_expr), x)
        ]
        candidates: list[Point] = [
            (root, sp.simplify(line_expr.subs(x, root)))
            for root in roots
            if sp.simplify(root - known_point[0]) != 0
        ]
        candidates = _filter_by_x_range(candidates, target, kernel)
        candidate_x_values = [kernel.sstr(point[0]) for point in candidates]
        if not candidates:
            raise method_result_empty(
                f"line/parabola second intersection cannot determine {target.name}",
                role="target_second_intersection",
                internal_ref=target.name,
                expected={"candidate_count": 1, "runtime_type": "Point"},
                observed={"candidate_count": 0, "candidate_x_values": []},
                repair_action="repair_intersection_inputs",
            )
        if len(candidates) > 1:
            raise method_result_ambiguous(
                f"line/parabola second intersection cannot uniquely determine {target.name}",
                role="target_second_intersection",
                internal_ref=target.name,
                expected={"candidate_count": 1, "runtime_type": "Point"},
                observed={
                    "candidate_count": len(candidates),
                    "candidate_x_values": candidate_x_values,
                },
                repair_action="supply_disambiguating_constraint",
            )
        point = candidates[0]
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "point_on_parabola",
                    sp.simplify(parabola.subs(x, point[0]) - point[1]) == 0,
                    "交点满足抛物线",
                ),
                _check(
                    "point_on_line",
                    sp.simplify(point[1] - line_expr.subs(x, point[0])) == 0,
                    "交点在目标直线上",
                ),
                _check(
                    "different_from_known_point",
                    sp.simplify(point[0] - known_point[0]) != 0,
                    "取到的是不同于已知交点的另一交点",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "联立直线与抛物线求另一交点",
                    f"确定 {target.name} 的坐标",
                    "直线由两点确定，联立抛物线后排除已知交点。",
                    f"line: y={kernel.sstr(line_expr)}",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _filter_by_x_range(
    candidates: list[Point],
    target: PointRef,
    kernel: SympyKernel,
) -> list[Point]:
    """按 target.definition.x_range 做可选筛选。"""
    raw = target.definition.get("x_range")
    if not (isinstance(raw, list) and len(raw) == 2):
        return candidates
    lower = _require_canonical_runtime_expression(
        raw[0],
        kernel,
        arg_name="target",
        role="x_range_lower_bound",
    )
    upper = _require_canonical_runtime_expression(
        raw[1],
        kernel,
        arg_name="target",
        role="x_range_upper_bound",
    )
    selected: list[Point] = []
    unresolved: list[Point] = []
    for point in candidates:
        above_lower = sp.simplify(point[0] - lower)
        below_upper = sp.simplify(point[0] - upper)
        if is_definitely_positive(
            above_lower
        ) and is_definitely_negative(below_upper):
            selected.append(point)
            continue
        if is_definitely_nonpositive(
            above_lower
        ) or is_definitely_nonnegative(below_upper):
            continue
        unresolved.append(point)
    if not selected and unresolved:
        raise method_result_ambiguous(
            "line/parabola intersection x-range membership is symbolic",
            role="target_second_intersection",
            internal_ref=target.name,
            expected={
                "candidate_count": 1,
                "x_range": [kernel.sstr(lower), kernel.sstr(upper)],
            },
            observed={
                "candidate_count": len(unresolved),
                "candidates": [
                    [kernel.sstr(value) for value in point]
                    for point in unresolved
                ],
                "state": "range_membership_unresolved",
            },
            repair_action="supply_disambiguating_constraint",
        )
    return selected


SPEC = MethodSpecSource(
    method_cls=LineParabolaSecondIntersectionPointMethod,
    title="求直线与抛物线的另一交点",
    summary=(
        "输入: 抛物线、确定直线的两点、已知交点和目标 PointRef；"
        "输出: 直线与抛物线的另一个交点。line_p1/line_p2 顺序可交换，"
        "且任一端点都可来自匿名步骤结果。可用 target.x_range 选择符合题设范围的点。"
    ),
    solves=(
        "derive_line_parabola_second_intersection",
        "derive_curve_intersection_point",
    ),
    inputs={
        "parabola": {
            "type": "Parabola",
            "required": True,
            "symbolic_basis_role": "state_anchor",
        },
        "x": canonical_symbol_input("x"),
        "line_p1": {
            "type": "Point",
            "required": True,
            "allows_anonymous_result": True,
            "symbolic_basis_role": "align_to_anchor",
            "role": (
                "确定目标直线的第一个点；必须与 line_p2 的横坐标不同。"
                "若该点也是抛物线已知交点，通常同时把它传给 known_point。"
            ),
        },
        "line_p2": {
            "type": "Point",
            "required": True,
            "allows_anonymous_result": True,
            "symbolic_basis_role": "align_to_anchor",
            "role": (
                "确定目标直线的第二个点；必须与 line_p1 的横坐标不同，"
                "从而得到非竖直直线。"
            ),
        },
        "known_point": {
            "type": "Point",
            "required": True,
            "symbolic_basis_role": "align_to_anchor",
            "role": (
                "目标直线与抛物线共有、并需要从联立结果中排除的已知交点；"
                "通常直接复用 line_p1 或 line_p2，禁止传入不在目标直线上的点。"
            ),
        },
        "target": {
            "type": "PointRef",
            "required": True,
            "symbolic_basis_role": "align_to_anchor",
        },
    },
    input_views=declare_input_views(
        identity=("x", "target"),
        latest_state=("parabola", "line_p1", "line_p2", "known_point"),
    ),
    outputs={"point": "Point"},
    do_not_use_when=(
        "line_p1 与 line_p2 横坐标相同或两点重合，无法确定本方法支持的非竖直直线。",
        "known_point 不同时位于目标直线和抛物线上；不要仅因它在抛物线上就把它作为排除点。",
    ),
    preconditions=("line_p1 与 line_p2 不能形成竖直线", "已知交点必须在直线和抛物线上"),
    postconditions=("输出点在直线和抛物线上，且不同于 known_point",),
    distinct_arg_groups=(("line_p1", "line_p2"),),
    interchangeable_arg_groups=(("line_p1", "line_p2"),),
    explanation=MethodExplanationSpec(
        role_schema={
            "line_points": "确定目标直线的两个已知点。",
            "line_expression": "由两个已知点确定的目标直线表达式。",
            "parabola": "待联立的抛物线解析式。",
            "known_point": "需要排除的已知交点。",
            "target_point": "最终求出的另一交点。",
        },
        student_goal_template="先由两个已知点确定目标直线，再联立抛物线求另一交点。",
        student_title_template="联立直线与抛物线求交点",
        derive_templates=(
            "由 {line_points} 可确定目标直线，得到 {line_expression}。",
            "联立 {line_expression} 与 {parabola}，排除已知交点 {known_point}，得到 {target_point}。",
        ),
        box_templates=("{line_expression}", "{target_point}"),
        role_binder_id="line_parabola_second_intersection_point",
    ),
)
