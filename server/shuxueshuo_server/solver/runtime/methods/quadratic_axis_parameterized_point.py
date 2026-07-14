"""quadratic_axis_parameterized_point 无状态 method。

由二次函数对称轴构造轴上的参数化点，例如 ``E=(axis_x, t)``。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec, MethodVisualSpec
from shuxueshuo_server.solver.math_ops import vertex_of_quadratic

from ._common import *
from ._spec import MethodSpecSource


class QuadraticAxisParameterizedPointMethod:
    """由抛物线对称轴构造目标点的参数化坐标。"""

    method_id = "quadratic_axis_parameterized_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        x = inputs["x"]
        target: PointRef = inputs["target"]

        axis_x = sp.simplify(vertex_of_quadratic(parabola, x)[0])
        parameter = sp.Symbol(_axis_parameter_name(target), real=True)
        point: Point = (axis_x, parameter)

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "point": TypedValue("Point", point, source=self.method_id),
                "parameter": TypedValue("Symbol", parameter, source=self.method_id),
            },
            checks=[
                _check(
                    "axis_x_derivative_zero",
                    sp.simplify(sp.diff(parabola, x).subs(x, axis_x)) == 0,
                    "参数化点横坐标位于抛物线对称轴上",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "构造对称轴上的参数化点",
                    f"表示 {target.name} 的坐标",
                    "点在抛物线对称轴上时，横坐标等于对称轴横坐标，纵坐标先设为参数。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _axis_parameter_name(target: PointRef) -> str:
    """为目标点构造稳定的内部参数名。"""
    safe = "".join(char if char.isalnum() or char == "_" else "_" for char in target.name)
    return f"_axis_param_{safe or 'point'}"


SPEC = MethodSpecSource(
    method_cls=QuadraticAxisParameterizedPointMethod,
    title="构造对称轴参数化点",
    summary=(
        "Given 已解抛物线和目标 PointRef, derive 该点在抛物线对称轴上的参数化坐标。"
        "适用于后续再由几何或曲线条件求参数的步骤。"
    ),
    solves=("parameterize_point_on_quadratic_axis",),
    inputs={
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point", "parameter": "Symbol"},
    preconditions=("parabola 必须是关于 x 的二次函数", "target 是题设中位于该对称轴上的点"),
    postconditions=("输出点的横坐标等于抛物线对称轴横坐标，纵坐标为待定参数",),
    explanation=MethodExplanationSpec(
        role_schema={
            "target": "对称轴上的目标点。",
            "axis_equation": "当前抛物线的对称轴方程。",
            "parameterized_point": "目标点的参数化坐标。",
        },
        student_goal_template="把对称轴上的点设成一个参数点。",
        student_title_template="设对称轴上的参数点",
        derive_templates=(
            "∵{target} 在对称轴 {axis_equation} 上",
            "∴设 {parameterized_point}",
        ),
        box_templates=("{parameterized_point}",),
        role_binder_id="quadratic_axis_parameterized_point",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "axis": "当前抛物线对称轴。",
            "parameterized_point": "对称轴上的参数化点。",
        },
        scene_templates=(
            {
                "component": "AxisParameterizedPointMarker",
                "axis_color": "#64748b",
                "point_color": "#dc2626",
                "persistence": "carry_forward",
            },
        ),
        role_binder_id="generic_visual",
    ),
)
