"""midpoint_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class MidpointPointMethod:
    """求两点中点。"""

    method_id = "midpoint_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        p1: Point = inputs["p1"]
        p2: Point = inputs["p2"]
        target: PointRef = inputs["target"]
        point = (sp.simplify((p1[0] + p2[0]) / 2), sp.simplify((p1[1] + p2[1]) / 2))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"midpoint": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "midpoint_average",
                    True,
                    f"{target.name} 的坐标为端点坐标平均值",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    f"求中点 {target.name}",
                    "由两端点坐标确定中点",
                    "中点坐标等于两端点横纵坐标的平均值。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=MidpointPointMethod,
    title='求中点坐标',
    solves=('derive_midpoint_coordinate',),
    inputs={
    "p1": {
        "type": "Point",
        "required": True
    },
    "p2": {
        "type": "Point",
        "required": True
    },
    "target": {
        "type": "PointRef",
        "required": True
    }
},
    outputs={
    "midpoint": "Point"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
)
