"""line_locus_minimum_point 无状态 method。

由最短线段和动点轨迹直线求最短状态下的动点坐标。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource


class LineLocusMinimumPointMethod:
    """求最短线段与动点轨迹直线的交点。"""

    method_id = "line_locus_minimum_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        moving_locus = inputs["moving_locus"]
        minimum_point_1: Point = inputs["minimum_point_1"]
        minimum_point_2: Point = inputs["minimum_point_2"]
        target: PointRef = inputs["target"]
        parameter = inputs.get("parameter")
        parameter_value = inputs.get("parameter_value")

        line_p1, line_p2 = _line_points(moving_locus)
        if parameter is not None and parameter_value is not None:
            substitutions = {parameter: parameter_value}
            line_p1, line_p2, minimum_point_1, minimum_point_2 = (
                _subs_point(point, substitutions)
                for point in (line_p1, line_p2, minimum_point_1, minimum_point_2)
            )
        point = kernel.line_intersection(
            (minimum_point_1, minimum_point_2),
            (line_p1, line_p2),
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "minimum_point_on_minimum_segment",
                    point_collinear(point, minimum_point_1, minimum_point_2),
                    f"{target.name} 在最短线段上",
                ),
                _check(
                    "minimum_point_on_locus",
                    point_collinear(point, line_p1, line_p2),
                    f"{target.name} 在动点轨迹直线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求最短状态动点",
                    f"确定 {target.name} 的坐标",
                    "最短状态下，动点是拉直后的最短线段与原动点轨迹直线的交点。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _line_points(line: dict[str, Any]) -> tuple[Point, Point]:
    """从 Line payload 读取一条直线上的两个点。"""
    start = _line_point(line, "start_point")
    direction = _line_point(line, "direction")
    end = (
        sp.simplify(start[0] + direction[0]),
        sp.simplify(start[1] + direction[1]),
    )
    return start, end


def _line_point(line: dict[str, Any], key: str) -> Point:
    """读取 Line payload 中的二维点或方向。"""
    raw = line.get(key)
    if isinstance(raw, list) and len(raw) == 2:
        raw = tuple(raw)
    if not isinstance(raw, tuple) or len(raw) != 2:
        raise ValueError(f"moving_locus requires 2D {key}")
    return (sp.simplify(raw[0]), sp.simplify(raw[1]))


SPEC = MethodSpecSource(
    method_cls=LineLocusMinimumPointMethod,
    title="由最短线段和轨迹求动点",
    summary="Given 动点轨迹直线和拉直后的最短线段两端点, derive 最短状态下的动点坐标。",
    solves=("derive_line_locus_minimum_point",),
    inputs={
        "moving_locus": {"type": "Line", "required": True},
        "minimum_point_1": {"type": "Point", "required": True},
        "minimum_point_2": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
        "parameter": {"type": "Symbol", "required": False},
        "parameter_value": {"type": "ParameterValue", "required": False},
    },
    outputs={"point": "Point"},
    preconditions=("最短线段与 moving_locus 不平行",),
    postconditions=("输出点同时位于最短线段和 moving_locus 上",),
    explanation=MethodExplanationSpec(
        role_schema={
            "parameter_assignment": "已求出的参数值（若有）。",
            "locus_line": "动点的轨迹直线。",
            "minimum_segment_line": "拉直后最短线段所在直线。",
            "line_intersection_equation": "由两条直线联立得到交点横纵坐标的关键等式。",
            "target_point": "最短状态下动点坐标。",
        },
        student_goal_template="把最短线段所在直线与动点轨迹直线相交，求最短状态下的动点。",
        student_title_template="由最短线段和轨迹求动点",
        student_nav_title_template="求最短状态动点",
        derive_templates=(
            "{parameter_assignment}",
            "∵动点在轨迹直线 {locus_line} 上",
            "∵最短时动点也在直线 {minimum_segment_line} 上",
            "∴{line_intersection_equation}",
            "∴{target_point}",
        ),
        box_templates=("{target_point}",),
        role_binder_id="line_locus_minimum_point",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "locus_line": "动点轨迹直线。",
            "minimum_segment_line": "拉直后的最短线段。",
            "target_point": "两线交点。",
        },
        role_binder_id="line_locus_minimum_point",
        scene_templates=(
            {
                "component": "LineLocusMinimumPointMarker",
                "persistence": "carry_forward",
                "locus_color": "#0f766e",
                "minimum_line_color": "#b45309",
                "target_color": "#b45309",
                "show_locus_label": False,
            },
        ),
    ),
)
