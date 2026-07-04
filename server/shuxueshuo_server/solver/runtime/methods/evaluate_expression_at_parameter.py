"""evaluate_expression_at_parameter 无状态 method。

本 method 只处理“表达式代入参数值”这一层通用代数动作。抛物线、系数等
结构化对象仍由更具体的 method 负责，避免一个 method 承担多态类型分发。
路径最小值表达式可以走同一套代入逻辑，但输出仍保留 MinimumExpression 视图。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class EvaluateExpressionAtParameterMethod:
    """把表达式中的参数替换为已求出的参数值。"""

    method_id = "evaluate_expression_at_parameter"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        expression = sp.sympify(inputs["expression"])
        parameter = inputs["parameter"]
        parameter_value = sp.sympify(inputs["parameter_value"])
        evaluated = sp.simplify(expression.subs(parameter, parameter_value))
        expression_type = inputs.get("__input_types__", {}).get("expression", "Expression")
        output_name = (
            "evaluated_minimum_expression"
            if expression_type == "MinimumExpression"
            else "evaluated_expression"
        )
        output_type = "MinimumExpression" if expression_type == "MinimumExpression" else "Expression"
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                output_name: TypedValue(
                    output_type,
                    evaluated,
                    source=self.method_id,
                ),
            },
            checks=[
                _check(
                    "expression_parameter_substituted",
                    parameter not in evaluated.free_symbols,
                    "参数已代入表达式",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "代入参数化简表达式",
                    "求表达式在参数取值下的结果",
                    "前序步骤已经确定参数值，因此直接代入并化简。",
                    f"{parameter.name}={kernel.sstr(parameter_value)}",
                    kernel.sstr(evaluated),
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=EvaluateExpressionAtParameterMethod,
    title="代入参数化简表达式",
    summary=(
        "输入: 表达式或最小值表达式、参数符号和参数值；输出: 代入参数后的同类型表达式。"
    ),
    solves=("evaluate_expression_at_parameter",),
    inputs={
        "expression": {"type": "Expression|MinimumExpression", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_value": {"type": "ParameterValue", "required": True},
    },
    outputs={
        "evaluated_expression": "Expression",
        "evaluated_minimum_expression": "MinimumExpression",
    },
    preconditions=("expression 可以包含 parameter",),
    postconditions=("输出表达式不再含 parameter，且保持输入表达式的 runtime 语义类型",),
)
