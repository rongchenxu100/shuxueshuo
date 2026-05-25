"""coefficient_at_parameter 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class CoefficientAtParameterMethod:
    """在参数取值确定后，求某个依赖系数的具体值。"""

    method_id = "coefficient_at_parameter"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        coefficients = inputs["coefficients"]
        coefficient = inputs["coefficient"]
        parameter = inputs["parameter"]
        parameter_value = inputs["parameter_value"]
        if coefficient == parameter:
            value = parameter_value
        elif coefficient in coefficients:
            value = coefficients[coefficient]
        else:
            raise ValueError(f"coefficient {coefficient.name} not found")
        value = sp.simplify(sp.sympify(value).subs(parameter, parameter_value))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"coefficient_value": TypedValue("ParameterValue", value, source=self.method_id)},
            checks=[
                _check(
                    "coefficient_parameter_substituted",
                    parameter not in value.free_symbols,
                    "参数已代入系数表达式",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "代入参数求系数",
                    f"求 {coefficient.name} 的值",
                    "先前步骤得到系数关于参数的表达式，参数确定后直接代入。",
                    f"{parameter.name}={kernel.sstr(parameter_value)}",
                    f"{coefficient.name}={kernel.sstr(value)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=CoefficientAtParameterMethod,
    title="代入参数求系数",
    solves=("derive_coefficient_at_parameter",),
    inputs={
        "coefficients": {"type": "Coefficients", "required": True},
        "coefficient": {"type": "Symbol", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_value": {"type": "ParameterValue", "required": True},
    },
    outputs={"coefficient_value": "ParameterValue"},
    preconditions=("coefficients 中包含目标 coefficient 或 coefficient 本身就是 parameter",),
    postconditions=("输出系数值不再含 parameter",),
)
