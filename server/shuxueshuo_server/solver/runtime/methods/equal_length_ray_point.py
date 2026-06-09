"""equal_length_ray_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class EqualLengthRayPointMethod:
    """在一条射线上构造点，使它到端点的距离等于另一条已知线段。"""

    method_id = "equal_length_ray_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        anchor: Point = inputs["anchor"]
        reference_point: Point = inputs["reference_point"]
        ray_point: Point = inputs["ray_point"]
        target: PointRef = inputs["target"]

        direction = (
            sp.simplify(ray_point[0] - anchor[0]),
            sp.simplify(ray_point[1] - anchor[1]),
        )
        direction_length = kernel.distance(anchor, ray_point)
        if sp.simplify(direction_length) == 0:
            raise ValueError("ray direction requires two distinct points")
        reference_length = kernel.distance(anchor, reference_point)
        unit_scale = sp.simplify(reference_length / direction_length)
        point = (
            sp.simplify(anchor[0] + direction[0] * unit_scale),
            sp.simplify(anchor[1] + direction[1] * unit_scale),
        )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=[
                _check(
                    "equal_lengths",
                    sp.simplify(
                        kernel.distance_squared(anchor, point)
                        - kernel.distance_squared(anchor, reference_point)
                    ) == 0,
                    f"{target.name} 到 anchor 的距离等于参考线段长度",
                ),
                _check(
                    "point_on_ray_line",
                    sp.simplify(
                        (point[0] - anchor[0]) * direction[1]
                        - (point[1] - anchor[1]) * direction[0]
                    ) == 0,
                    f"{target.name} 在指定射线所在直线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "在射线上作等长点",
                    f"确定 {target.name} 的坐标",
                    "沿指定射线取点，使该点到端点的距离等于参考线段长度。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=EqualLengthRayPointMethod,
    title="射线上等长构造点",
    summary=(
        "输入: 射线端点、射线方向点、参考线段另一端和目标 PointRef；"
        "输出: 射线上满足 anchor-target = anchor-reference 的点。"
    ),
    solves=("derive_equal_length_point_on_ray",),
    inputs={
        "anchor": {"type": "Point", "required": True},
        "reference_point": {"type": "Point", "required": True},
        "ray_point": {"type": "Point", "required": True},
        "target": {"type": "PointRef", "required": True},
    },
    outputs={"point": "Point"},
    preconditions=("anchor 与 ray_point 必须确定一条非零射线方向",),
    postconditions=("输出点在指定射线所在直线上，且到 anchor 的距离等于 anchor-reference",),
)
