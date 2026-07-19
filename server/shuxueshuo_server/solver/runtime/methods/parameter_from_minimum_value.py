"""parameter_from_minimum_value 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ParameterFromMinimumValueMethod:
    """由最小值表达式和目标值反求参数。"""

    method_id = "parameter_from_minimum_value"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = inputs["minimum_expression"]
        condition = inputs["condition"]
        parameter = inputs["parameter"]
        constraint = inputs.get("constraint")
        target = kernel.expr(condition["value"])
        lower_bound = constraint["value"] if isinstance(constraint, dict) and constraint.get("operator") == ">" else None
        candidates = kernel.solve_values(sp.Eq(expression, target), parameter)
        value = pick_by_lower_bound(candidates, lower_bound)
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"parameter_value": TypedValue("ParameterValue", value, source=self.method_id)},
            checks=[
                _check("minimum_parameter_domain", satisfies_lower_bound(value, lower_bound), "参数满足定义域"),
                _check("minimum_value_matches", sp.simplify(expression.subs(parameter, value) - target) == 0, "最小值匹配题设"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由最小值反求参数",
                    f"求 {parameter.name} 的值",
                    "题目给出最小值，代入最小值表达式解方程。",
                    f"{parameter.name}={kernel.sstr(value)}",
                    f"{parameter.name}={kernel.sstr(value)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=ParameterFromMinimumValueMethod,
    title='由最小值反求参数',
    summary='输入: 最小值表达式与给定最小值条件；输出: 参数值。',
    do_not_use_when=(
        "输入表达式不具有最小值语义，或题面给出的只是普通表达式取值条件。",
        "尚未得到可代入的最小值表达式。",
    ),
    solves=('derive_parameter_from_minimum_value',),
    inputs={
    "minimum_expression": {
        "type": "MinimumExpression",
        "required": True
    },
    "condition": {
        "type": "Condition",
        "required": True
    },
    "parameter": {
        "type": "Symbol",
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
