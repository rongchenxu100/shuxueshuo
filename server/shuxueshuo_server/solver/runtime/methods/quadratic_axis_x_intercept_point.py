"""quadratic_axis_x_intercept_point 无状态 method。

由已解二次函数求对称轴与 x 轴交点。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec
from shuxueshuo_server.solver.math_ops import vertex_of_quadratic

from ._common import *
from ._spec import MethodSpecSource


class QuadraticAxisXInterceptPointMethod:
    """由抛物线解析式求对称轴与 x 轴交点。"""

    method_id = "quadratic_axis_x_intercept_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        x = inputs["x"]
        target: PointRef = inputs["target"]

        axis_x = sp.simplify(vertex_of_quadratic(parabola, x)[0])
        point: Point = (axis_x, sp.Integer(0))

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"axis_point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check("axis_point_y_is_zero", point[1] == 0, f"{target.name} 在 x 轴上"),
                _check(
                    "axis_x_derivative_zero",
                    sp.simplify(sp.diff(parabola, x).subs(x, axis_x)) == 0,
                    "横坐标位于抛物线对称轴上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求对称轴与 x 轴交点",
                    f"确定 {target.name} 的坐标",
                    "二次函数对称轴为 x=-b/(2a)，与 x 轴交点纵坐标为 0。",
                    f"x={kernel.sstr(axis_x)}",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=QuadraticAxisXInterceptPointMethod,
    title="由抛物线求对称轴与 x 轴交点",
    summary=(
        "Given 已解二次函数表达式和目标 PointRef, derive 对称轴与 x 轴交点坐标。"
        "适用于题面点定义为 axis_x_intercept，但当前问需要含参或定值坐标的场景。"
    ),
    solves=("derive_axis_x_intercept_point",),
    inputs={
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"axis_point": "Point"},
    preconditions=("parabola 必须是关于 x 的二次函数",),
    postconditions=("输出点位于 x 轴，横坐标为抛物线对称轴横坐标",),
    explanation=MethodExplanationSpec(
        role_schema={
            "axis_equation": "当前抛物线的对称轴方程。",
            "axis_point": "对称轴与 x 轴的交点。",
            "target_label": "对称轴与 x 轴交点的学生可见点名。",
        },
        student_goal_template="求抛物线对称轴与 x 轴的交点。",
        student_title_template="求对称轴与X轴交点{target_label}",
        student_nav_title_template="求对称轴交点{target_label}",
        derive_templates=(
            "∵对称轴为 {axis_equation}",
            "∴{axis_point}",
        ),
        box_templates=("{axis_point}",),
        role_binder_id="quadratic_axis_x_intercept_point",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "axis": "当前抛物线对称轴。",
            "axis_point": "对称轴与 x 轴的交点。",
        },
        scene_templates=(
            {
                "component": "QuadraticAxisXInterceptMarker",
                "axis_color": "#64748b",
                "point_color": "#b45309",
                "persistence": "carry_forward",
            },
        ),
        role_binder_id="generic_visual",
    ),
)
