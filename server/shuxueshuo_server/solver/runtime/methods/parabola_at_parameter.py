"""parabola_at_parameter 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ParabolaAtParameterMethod:
    """把含参抛物线代入参数值。"""

    method_id = "parabola_at_parameter"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        parabola = inputs["parabola"]
        parameter = inputs["parameter"]
        value = inputs["parameter_value"]
        result = sp.expand(parabola.subs(parameter, value))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"parabola": TypedValue("Parabola", result, source=self.method_id)},
            checks=[
                _check("parameter_substituted", parameter not in result.free_symbols, "参数已代入抛物线"),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "代入参数得到抛物线",
                    "写出当前小问解析式",
                    "将已求参数值代入含参通式。",
                    f"y={kernel.sstr(result)}",
                    f"y={kernel.sstr(result)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=ParabolaAtParameterMethod,
    title='代入参数得到抛物线',
    solves=('derive_parabola_at_parameter',),
    inputs={
    "parabola": {
        "type": "Parabola",
        "required": True
    },
    "parameter": {
        "type": "Symbol",
        "required": True
    },
    "parameter_value": {
        "type": "ParameterValue",
        "required": True
    }
},
    outputs={
    "parabola": "Parabola"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
)
