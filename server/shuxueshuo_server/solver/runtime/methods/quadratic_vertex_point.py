"""quadratic_vertex_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.math_ops import vertex_of_quadratic

from ._common import *
from ._spec import MethodSpecSource


class QuadraticVertexPointMethod:
    """由二次函数解析式求顶点坐标。"""

    method_id = "quadratic_vertex_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        x = inputs["x"]
        target: PointRef = inputs["target"]
        point = vertex_of_quadratic(parabola, x)
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "vertex_x_derivative_zero",
                    sp.simplify(sp.diff(parabola, x).subs(x, point[0])) == 0,
                    "顶点横坐标使一阶导数为 0",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求二次函数顶点",
                    f"确定 {target.name} 的坐标",
                    "二次函数顶点横坐标为 -B/(2A)，纵坐标代回解析式。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=QuadraticVertexPointMethod,
    title="求二次函数顶点",
    solves=("derive_quadratic_vertex_point",),
    inputs={
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=("parabola 必须是关于 x 的二次函数",),
    postconditions=("输出点是该二次函数顶点",),
)
