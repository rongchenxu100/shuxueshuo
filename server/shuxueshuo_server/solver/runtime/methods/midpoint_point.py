"""midpoint_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodVisualSpec, TeachingUnitSpec

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


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
    summary='输入: 两端点和中点定义；输出: 中点坐标。',
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
    input_views=declare_input_views(
        identity=("target",),
        latest_state=("p1", "p2"),
    ),
    outputs={
    "midpoint": "Point"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
    interchangeable_arg_groups=(("p1", "p2"),),
    teaching_unit=TeachingUnitSpec(
        unit_key="midpoint_point/compute_midpoint",
        title_template="求线段中点",
        nav_title_template="求中点",
        goal_template="分别取两端点横、纵坐标的平均值，求出中点坐标。",
        derive_templates=(
            ("∵", "线段两端点为 {p1}、{p2}"),
            ("计算", "中点横、纵坐标分别取平均"),
            ("∴", "中点为 {midpoint}"),
        ),
        box_templates=("{midpoint}",),
        role_schema={
            "p1": "线段第一个端点。",
            "p2": "线段第二个端点。",
            "midpoint": "计算所得中点。",
        },
        role_binder_id="midpoint_point",
    ),
    visual=MethodVisualSpec(
        role_schema={
            "p1": "线段第一个端点。",
            "p2": "线段第二个端点。",
            "midpoint": "中点。",
        },
        scene_templates=(
            {
                "component": "MidpointMarker",
                "endpoint_roles": ["p1", "p2"],
                "output_role": "midpoint",
                "persistence": "carry_forward",
            },
        ),
        role_binder_id="generic_visual",
    ),
)
