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
        if expression.free_symbols and parameter not in expression.free_symbols:
            free_symbols = "|".join(
                sorted(symbol.name for symbol in expression.free_symbols)
            )
            raise ValueError(
                "function.substitution_symbol_mismatch: "
                f"parameter={parameter.name}, "
                f"free_symbols={free_symbols or 'none'}"
            )
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
        "对已经得到的 Expression、MinimumExpression 或 Parabola 状态代入一个"
        "同身份参数值，并输出同类型状态。输入类型决定唯一 return：Expression "
        "输出 evaluated_expression，MinimumExpression 输出 "
        "evaluated_minimum_expression，Parabola 输出 evaluated_parabola。"
        "代入一个参数不保证其他自由参数也已闭合；最终结果形态由剩余自由符号决定。"
    ),
    do_not_use_when=(
        (
            "只有 ProblemIR 中的 Function 模板、尚未得到同一函数对象的 Parabola "
            "状态；建立抛物线应使用 quadratic_from_constraints。"
        ),
        (
            "需要依次代入多个已知二次函数系数；应把这些系数值一次放入 "
            "quadratic_from_constraints.known_coefficients。"
        ),
        (
            "不要假定 evaluated_expression、evaluated_minimum_expression 和 "
            "evaluated_parabola 会同时产生；实际 return 只由输入状态类型决定。"
        ),
        (
            "表达式不含待代入 Symbol，或 ParameterValue 属于另一个 Symbol；"
            "例如表达式只含参数 u 时，不能用参数 v 的值关闭该表达式。"
        ),
        (
            "试图通过代入无关参数改变或关闭函数状态；应先选择实际出现在该状态"
            "自由符号集合中的参数。"
        ),
    ),
    repair_feedback_provider_id="expression_state_transition",
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
