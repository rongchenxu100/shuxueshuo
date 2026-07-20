"""line_intersection_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class LineIntersectionPointMethod:
    """求两条直线交点，可先代入参数值。"""

    method_id = "line_intersection_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        p1: Point = inputs["line1_p1"]
        p2: Point = inputs["line1_p2"]
        p3: Point = inputs["line2_p1"]
        p4: Point = inputs["line2_p2"]
        target: PointRef = inputs["target"]
        if "parameter" in inputs and "parameter_value" in inputs:
            substitutions = {inputs["parameter"]: inputs["parameter_value"]}
            p1, p2, p3, p4 = (
                _subs_point(point, substitutions)
                for point in (p1, p2, p3, p4)
            )
        point = kernel.line_intersection((p1, p2), (p3, p4))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"intersection": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check("intersection_on_line1", point_collinear(point, p1, p2), f"{target.name} 在第一条直线上"),
                _check("intersection_on_line2", point_collinear(point, p3, p4), f"{target.name} 在第二条直线上"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    f"求交点 {target.name}",
                    "确定最短位置对应点",
                    "最短时目标点同时位于两条约束直线上。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=LineIntersectionPointMethod,
    title='求两直线交点',
    summary='输入: 两条直线；输出: 交点坐标。',
    solves=('derive_line_intersection_point',),
    inputs={
    "line1_p1": {
        "type": "Point",
        "required": True
    },
    "line1_p2": {
        "type": "Point",
        "required": True
    },
    "line2_p1": {
        "type": "Point",
        "required": True
    },
    "line2_p2": {
        "type": "Point",
        "required": True
    },
    "target": {
        "type": "PointRef",
        "required": True
    },
    "parameter": {
        "type": "Symbol",
        "required": False
    },
    "parameter_value": {
        "type": "ParameterValue",
        "required": False
    }
},
    outputs={
    "intersection": "Point"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
    distinct_arg_groups=(
        ("line1_p1", "line1_p2"),
        ("line2_p1", "line2_p2"),
    ),
)
