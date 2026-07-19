"""evaluate_expression_at_parameter 无状态 method。

本 method 处理“向符号表达式状态代入参数值”这一层通用代数动作，并按输入
runtime type 保留 Expression、MinimumExpression 或 Parabola 的状态语义。
"""

from __future__ import annotations

from shuxueshuo_server.solver.contracts import ScalarResultFormSpec

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
        output_by_input_type = {
            "Expression": ("evaluated_expression", "Expression"),
            "MinimumExpression": (
                "evaluated_minimum_expression",
                "MinimumExpression",
            ),
            "Parabola": ("evaluated_parabola", "Parabola"),
        }
        output_name, output_type = output_by_input_type.get(
            expression_type,
            ("evaluated_expression", "Expression"),
        )
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
        "输入: 表达式、最小值表达式或抛物线状态，以及参数符号和参数值；"
        "输出: 代入参数后的同类型状态。代入一个参数不保证其他自由参数也已闭合；"
        "最终结果形态由剩余自由符号决定。"
    ),
    solves=("evaluate_expression_at_parameter",),
    inputs={
        "expression": {
            "type": "Expression|MinimumExpression|Parabola",
            "required": True,
        },
        "parameter": {"type": "Symbol", "required": True},
        "parameter_value": {"type": "ParameterValue", "required": True},
    },
    outputs={
        "evaluated_expression": "Expression",
        "evaluated_minimum_expression": "MinimumExpression",
        "evaluated_parabola": "Parabola",
    },
    scalar_result_forms={
        "evaluated_expression": ScalarResultFormSpec(
            possible_forms=("open_expression", "closed_value"),
            description=(
                "代入后仍含未确定参数时为 open_expression；不存在自由参数时为 "
                "closed_value。"
            ),
        ),
        "evaluated_minimum_expression": ScalarResultFormSpec(
            possible_forms=("open_expression", "closed_value"),
            description=(
                "代入后仍含未确定参数时为 open_expression；不存在自由参数时为 "
                "closed_value，可直接作为数值答案。"
            ),
        ),
    },
    preconditions=("expression 可以包含 parameter",),
    postconditions=("输出表达式不再含 parameter，且保持输入表达式的 runtime 语义类型",),
)
