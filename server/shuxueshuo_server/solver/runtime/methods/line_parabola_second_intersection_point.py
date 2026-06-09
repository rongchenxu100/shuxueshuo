"""line_parabola_second_intersection_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


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
            raise ValueError("vertical line is not supported for line-parabola second intersection")
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
        if len(candidates) != 1:
            raise ValueError(
                f"line/parabola second intersection cannot uniquely determine {target.name}: "
                f"{[kernel.sstr(point[0]) for point in candidates]}"
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
    locals_ = {
        symbol.name: symbol
        for point in candidates
        for value in point
        for symbol in sp.sympify(value).free_symbols
    }
    lower = kernel.expr(str(raw[0]), locals_)
    upper = kernel.expr(str(raw[1]), locals_)
    return [
        point for point in candidates
        if sp.simplify(point[0] - lower) > 0 and sp.simplify(point[0] - upper) < 0
    ]


SPEC = MethodSpecSource(
    method_cls=LineParabolaSecondIntersectionPointMethod,
    title="求直线与抛物线的另一交点",
    summary=(
        "输入: 抛物线、确定直线的两点、已知交点和目标 PointRef；"
        "输出: 直线与抛物线的另一个交点。可用 target.x_range 选择符合题设范围的点。"
    ),
    solves=(
        "derive_line_parabola_second_intersection",
        "derive_curve_intersection_point",
    ),
    inputs={
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "line_p1": {"type": "Point", "required": True},
        "line_p2": {"type": "Point", "required": True},
        "known_point": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=("line_p1 与 line_p2 不能形成竖直线", "已知交点必须在直线和抛物线上"),
    postconditions=("输出点在直线和抛物线上，且不同于 known_point",),
)
