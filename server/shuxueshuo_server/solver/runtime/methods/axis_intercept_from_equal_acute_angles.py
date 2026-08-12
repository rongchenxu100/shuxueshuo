"""axis_intercept_from_equal_acute_angles 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec

from ._common import *
from ._spec import MethodSpecSource


class AxisInterceptFromEqualAcuteAnglesMethod:
    """由两个锐角相等推出正切比相等，并求竖直轴截点。"""

    method_id = "axis_intercept_from_equal_acute_angles"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        angle_equality = dict(inputs["angle_equality"])
        x_axis_point: Point = inputs["x_axis_point"]
        y_axis_point: Point = inputs["y_axis_point"]
        reference_x_axis_point: Point = inputs["reference_x_axis_point"]
        origin: Point = inputs["origin"]
        target: PointRef = inputs["target"]

        if sp.simplify(x_axis_point[1] - origin[1]) != 0:
            raise ValueError("x_axis_point must lie on the horizontal axis through origin")
        if sp.simplify(y_axis_point[0] - origin[0]) != 0:
            raise ValueError("y_axis_point must lie on the vertical axis through origin")
        if sp.simplify(reference_x_axis_point[1] - origin[1]) != 0:
            raise ValueError("reference_x_axis_point must lie on the horizontal axis through origin")

        ob = kernel.distance(origin, x_axis_point)
        ao = kernel.distance(origin, reference_x_axis_point)
        co = kernel.distance(origin, y_axis_point)
        if sp.simplify(ob) == 0:
            raise ValueError(
                "angle_role_degenerate: x_axis_point must differ from origin"
            )
        if sp.simplify(ao) == 0:
            raise ValueError(
                "angle_role_degenerate: reference_x_axis_point must differ "
                "from origin"
            )
        if sp.simplify(co) == 0:
            raise ValueError(
                "angle_role_degenerate: y_axis_point must differ from origin"
            )
        if _same_point(x_axis_point, reference_x_axis_point):
            raise ValueError(
                "angle_role_degenerate: x_axis_point and "
                "reference_x_axis_point must be distinct"
            )

        vertical_direction = sp.simplify((y_axis_point[1] - origin[1]) / co)
        of_length = sp.simplify(ob * ao / co)
        point = (
            sp.simplify(origin[0]),
            sp.simplify(origin[1] + vertical_direction * of_length),
        )
        left_angle = str(angle_equality.get("left_angle", "target angle"))
        right_angle = str(angle_equality.get("right_angle", "reference angle"))

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "target_on_y_axis",
                    sp.simplify(point[0] - origin[0]) == 0,
                    f"{target.name} 在 y 轴上",
                ),
                _check(
                    "tangent_ratio_transferred",
                    sp.simplify(kernel.distance(origin, point) * co - ob * ao) == 0,
                    "由等角得到 OF/OB = AO/CO",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由等角求轴上截点",
                    f"确定 {target.name} 的坐标",
                    f"已知 ∠{left_angle}=∠{right_angle}，两个直角三角形正切相等。",
                    f"OF/OB=AO/CO，{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _same_point(first: Point, second: Point) -> bool:
    return all(
        sp.simplify(left - right) == 0
        for left, right in zip(first, second, strict=True)
    )


SPEC = MethodSpecSource(
    method_cls=AxisInterceptFromEqualAcuteAnglesMethod,
    title="由等锐角求轴上截点",
    summary=(
        "消费前序 AngleEquality，通过两个非退化直角三角形的正切比相等，"
        "求目标直线与竖直轴的辅助交点。只需提供等角事实；目标水平轴点、参考"
        "水平轴点、竖直轴点和原点由代码从等角两边的点顺序恢复。"
        "这些点可以携带符号坐标，输出也可以是待后续约束闭合的参数化 Point。"
        "本能力只计算轴截点，不证明该点在抛物线上，也不返回直线与抛物线的"
        "另一个交点；若最终目标是曲线点，还必须继续使用直线与抛物线交点能力。"
    ),
    do_not_use_when=(
        "只有原始角和条件、尚未得到 AngleEquality 时，不能直接使用本能力。",
        "等角两边不能形成两个非退化直角三角形，或目标不是竖直轴截点。",
        "最终答案是抛物线上的曲线点时，不要把本能力的辅助轴截点直接绑定为该答案。",
        "不要手工交换目标水平轴点、参考水平轴点、竖直轴点和原点；这些机械角色由 AngleEquality 决定。",
    ),
    solves=("derive_axis_intercept_from_equal_acute_angles",),
    inputs={
        "angle_equality": {"type": "AngleEquality", "required": True},
        "x_axis_point": {"type": "Point", "required": True},
        "y_axis_point": {"type": "Point", "required": True},
        "reference_x_axis_point": {"type": "Point", "required": True},
        "origin": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=(
        "angle_equality 表示目标直角三角形锐角等于参考直角三角形锐角",
        "x_axis_point 与 reference_x_axis_point 在以 origin 为原点的水平轴上",
        "y_axis_point 在以 origin 为原点的竖直轴上",
    ),
    postconditions=("输出点在 y 轴上，且满足 OF/OB=AO/CO",),
    explanation=MethodExplanationSpec(
        role_schema={
            "angle_equality": "已推出的等锐角关系。",
            "reference_right_triangle": "参考直角三角形。",
            "target_intercept": "目标直线与坐标轴的交点。",
        },
        student_goal_template="由等锐角得到正切比相等，求出目标直线在坐标轴上的截点。",
        student_title_template="由等角关系求辅助点坐标",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "angle_equality": "用于保留当前讲解中的等角关系与对应角边。",
            "target_intercept": "目标线与竖直轴的交点。",
            "reference_right_triangle": "由参考水平轴点、原点、竖直轴点组成的直角三角形。",
            "target_right_triangle": "由目标水平轴点、原点、目标截点组成的直角三角形。",
        },
        scene_templates=(
            {
                "component": "EqualAcuteAngleInterceptMarker",
                "style_intent": "tangent_ratio_from_equal_acute_angles",
                "show_angles": False,
                "show_right_angles": False,
            },
        ),
        role_binder_id="axis_intercept_from_equal_acute_angles",
    ),
)
