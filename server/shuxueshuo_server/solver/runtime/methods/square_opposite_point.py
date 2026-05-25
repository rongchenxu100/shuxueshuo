"""square_opposite_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class SquareOppositePointMethod:
    """由平行四边形/正方形对顶点关系构造辅助点。"""

    method_id = "square_opposite_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        vertex: Point = inputs["vertex"]
        adjacent1: Point = inputs["adjacent1"]
        adjacent2: Point = inputs["adjacent2"]
        target: PointRef = inputs["target"]
        point = (
            sp.simplify(adjacent1[0] + adjacent2[0] - vertex[0]),
            sp.simplify(adjacent1[1] + adjacent2[1] - vertex[1]),
        )
        t = sp.Symbol("t", real=True)
        moving_point = (
            sp.simplify(adjacent2[0] + t * (adjacent1[0] - adjacent2[0])),
            sp.simplify(adjacent2[1] + t * (adjacent1[1] - adjacent2[1])),
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check("square_opposite_constructed", True, f"已构造辅助点 {target.name}"),
                _check(
                    "opposite_point_preserves_distance_to_moving_line",
                    sp.simplify(
                        kernel.distance_squared(vertex, moving_point)
                        - kernel.distance_squared(point, moving_point)
                    ) == 0,
                    f"{target.name} 到动点所在直线的距离关系成立",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    f"构造辅助点 {target.name}",
                    "继续把单动点折线路径转化为两点距离",
                    "构造等腰直角四边形的对顶点，使动点到两个固定点的折线可以转化为一条线段。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})，因 G 在 MN 上，有 DG={target.name}G",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=SquareOppositePointMethod,
    title='构造对顶辅助点',
    solves=('derive_square_opposite_point',),
    inputs={
    "vertex": {
        "type": "Point",
        "required": True
    },
    "adjacent1": {
        "type": "Point",
        "required": True
    },
    "adjacent2": {
        "type": "Point",
        "required": True
    },
    "target": {
        "type": "PointRef",
        "required": True
    }
},
    outputs={
    "point": "Point"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
)
