"""distance_between_points 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import MethodExplanationSpec

from ._common import *
from ._spec import MethodSpecSource


class DistanceBetweenPointsMethod:
    """计算两点距离，并可选代入参数值得到具体距离。"""

    method_id = "distance_between_points"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        p1: Point = inputs["p1"]
        p2: Point = inputs["p2"]
        distance = sp.simplify(kernel.distance(p1, p2))
        outputs = {"distance": TypedValue("MinimumExpression", distance, source=self.method_id)}
        checks = [_check("distance_is_nonzero", distance != 0, "距离表达式非零")]
        conclusion = f"最小值表达式为 {kernel.sstr(distance)}"
        if "parameter" in inputs and "parameter_value" in inputs:
            value = sp.simplify(distance.subs(inputs["parameter"], inputs["parameter_value"]))
            outputs["evaluated_distance"] = TypedValue("MinimumExpression", value, source=self.method_id)
            checks.append(_check("evaluated_distance_positive", value > 0, "代入后的最小值为正"))
            conclusion = f"最小值表达式为 {kernel.sstr(distance)}，代入后为 {kernel.sstr(value)}"
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs=outputs,
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "计算路径最小值表达式",
                    "把折线路径转为最短线段距离",
                    "路径转化后，折线最短值等于两个固定端点之间的距离。",
                    f"d={kernel.sstr(distance)}",
                    conclusion,
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=DistanceBetweenPointsMethod,
    title='计算两点距离',
    summary='输入: 两点及可选参数值；输出: 两点距离或代入参数后的距离。',
    solves=('derive_distance_between_points',),
    inputs={
    "p1": {
        "type": "Point",
        "required": True
    },
    "p2": {
        "type": "Point",
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
    "distance": "MinimumExpression",
    "evaluated_distance": "MinimumExpression"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
    explanation=MethodExplanationSpec(
        role_schema={
            "p1": "第一个点或线段端点。",
            "p2": "第二个点或线段端点。",
            "distance": "两点距离表达式。",
        },
        student_goal_template="计算 {p1} 与 {p2} 的距离，作为当前路径最值表达式。",
        derive_templates=(
            "由距离公式，{p1}{p2} = {distance}。",
            "化简得到当前需要的距离或最小值表达式。",
        ),
        box_templates=("{p1}{p2} = {distance}",),
        role_binder_id="distance_between_points",
    ),
)
