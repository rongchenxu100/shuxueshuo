"""quadratic_y_axis_intercept_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.math_ops import y_axis_intercept

from ._common import *
from ._spec import MethodSpecSource


class QuadraticYAxisInterceptPointMethod:
    """由二次函数解析式求与 y 轴的交点。

    该 method 只把 ``x=0`` 代入当前抛物线表达式，因此允许抛物线仍含一个或多个
    未定系数；输出点坐标会保留这些符号参数，例如
    ``y=2*x**2-b*x-b-2`` 会得到 ``(0, -b-2)``。这类含参交点常用于后续把
    几何构造点代回曲线，再筛选或求参数。
    """

    method_id = "quadratic_y_axis_intercept_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        quadratic = inputs["quadratic"]
        x = inputs["x"]
        target: PointRef = inputs["target"]
        point = y_axis_intercept(quadratic, x)
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "y_axis_x_is_zero",
                    sp.simplify(point[0]) == 0,
                    "y 轴交点的横坐标为 0",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "求 y 轴交点",
                    f"确定 {target.name} 的坐标",
                    "抛物线与 y 轴交点满足 x=0，代入解析式即可。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=QuadraticYAxisInterceptPointMethod,
    title="求二次函数与 y 轴交点",
    summary="输入: 抛物线表达式，可含未定系数；输出: x=0 时的 y 轴交点，坐标可保留参数。",
    solves=("derive_quadratic_y_axis_intercept_point",),
    inputs={
        "quadratic": {"type": "Expression", "required": True},
        "x": {"type": "Symbol", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=("quadratic 是关于 x 的函数表达式，可以含未定系数",),
    postconditions=("输出点横坐标为 0 且在曲线上；若输入含参数，输出坐标保留参数表达式",),
)
