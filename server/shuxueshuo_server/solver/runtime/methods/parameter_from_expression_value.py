"""parameter_from_expression_value 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ParameterFromExpressionValueMethod:
    """由表达式等于题设给定值反求参数。

    这是 ``parameter_from_minimum_value`` 的泛化命名版：method 不关心表达式的
    来源是否为“最小值”，只关心它已经是一个可求值的表达式，并且题设给出它应
    等于某个目标值。首版输入类型仍复用 runtime 里已有的 ``MinimumExpression``，
    避免过早扩大类型系统；后续若普通 ``Expression`` 也需要同样能力，再放宽
    MethodSpec 输入类型。
    """

    method_id = "parameter_from_expression_value"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = inputs["expression"]
        condition = inputs["condition"]
        parameter = inputs["parameter"]
        constraint = inputs.get("constraint")

        target = kernel.expr(condition["value"])
        lower_bound = (
            constraint["value"]
            if isinstance(constraint, dict) and constraint.get("operator") == ">"
            else None
        )
        candidates = kernel.solve_values(sp.Eq(expression, target), parameter)
        value = pick_by_lower_bound(candidates, lower_bound)

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"parameter_value": TypedValue("ParameterValue", value, source=self.method_id)},
            checks=[
                _check("parameter_domain", satisfies_lower_bound(value, lower_bound), "参数满足定义域"),
                _check(
                    "expression_value_matches",
                    sp.simplify(expression.subs(parameter, value) - target) == 0,
                    "表达式取值匹配题设",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由表达式取值反求参数",
                    f"求 {parameter.name} 的值",
                    "题目给出某个表达式的取值，代入表达式解方程。",
                    f"{parameter.name}={kernel.sstr(value)}",
                    f"{parameter.name}={kernel.sstr(value)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=ParameterFromExpressionValueMethod,
    title="由表达式取值反求参数",
    summary="输入: 已推导表达式与给定值条件；输出: 参数值。使用原则: 当几何或代数步骤已经给出含参数表达式，而题设给出该表达式的取值时使用。",
    solves=("derive_parameter_from_expression_value",),
    inputs={
        "expression": {"type": "MinimumExpression", "required": True},
        "condition": {"type": "Condition", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "constraint": {"type": "Constraint", "required": False},
    },
    outputs={"parameter_value": "ParameterValue"},
    preconditions=("expression 已由前序 method 推导得到",),
    postconditions=("输出参数值满足表达式取值条件",),
)
