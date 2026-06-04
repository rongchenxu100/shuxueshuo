"""parameter_from_segment_length 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ParameterFromSegmentLengthMethod:
    """由两点距离平方条件求参数。"""

    method_id = "parameter_from_segment_length"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        p1: Point = inputs["p1"]
        p2: Point = inputs["p2"]
        parameter = inputs["parameter"]
        condition = inputs["condition"]
        constraint = inputs.get("constraint")
        target = kernel.expr(condition["value"])
        lower_bound = constraint["value"] if isinstance(constraint, dict) and constraint.get("operator") == ">" else None
        length_sq = kernel.distance_squared(p1, p2)
        candidates = kernel.solve_values(sp.Eq(length_sq, target), parameter)
        value = pick_by_lower_bound(candidates, lower_bound)
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"parameter_value": TypedValue("ParameterValue", value, source=self.method_id)},
            checks=[
                _check("parameter_domain", satisfies_lower_bound(value, lower_bound), "参数满足定义域"),
                _check("length_condition_matches", sp.simplify(length_sq.subs(parameter, value) - target) == 0, "距离条件成立"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由长度条件求参数",
                    f"求 {parameter.name} 的值",
                    "两点距离平方等于题设值，解一元方程并按定义域筛选。",
                    f"{parameter.name}={kernel.sstr(value)}",
                    f"{parameter.name}={kernel.sstr(value)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=ParameterFromSegmentLengthMethod,
    title='由线段长度求参数',
    summary='输入: 两点和线段长度条件；输出: 满足条件的参数值。',
    solves=('derive_parameter_from_segment_length',),
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
        "required": True
    },
    "condition": {
        "type": "Condition",
        "required": True
    },
    "constraint": {
        "type": "Constraint",
        "required": False
    }
},
    outputs={
    "parameter_value": "ParameterValue"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
)
