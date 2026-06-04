"""point_on_parabola_at_x 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class PointOnParabolaAtXMethod:
    """由目标点定义中的横坐标，在抛物线上求点坐标。"""

    method_id = "point_on_parabola_at_x"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        x = inputs["x"]
        target: PointRef = inputs["target"]
        raw_x = target.definition.get("x") or target.definition.get("x_coordinate")
        if raw_x is None:
            raise ValueError("point_on_parabola_at_x requires target.definition.x")
        locals_ = {symbol.name: symbol for symbol in parabola.free_symbols | {x}}
        x_value = kernel.expr(raw_x, locals_)
        point = (sp.simplify(x_value), sp.simplify(parabola.subs(x, x_value)))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "point_on_parabola",
                    sp.simplify(parabola.subs(x, point[0]) - point[1]) == 0,
                    "点坐标满足抛物线解析式",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由横坐标求曲线上点",
                    f"确定 {target.name} 的坐标",
                    "点在抛物线上，已知横坐标时把横坐标代入解析式。",
                    f"x_{target.name}={kernel.sstr(x_value)}",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=PointOnParabolaAtXMethod,
    title="由横坐标求抛物线上点",
    summary="输入: 抛物线和横坐标；输出: 曲线上的点。",
    solves=("derive_point_on_parabola_at_x",),
    inputs={
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=("target.definition.x 或 target.definition.x_coordinate 必须存在",),
    postconditions=("输出点在给定抛物线上",),
)
