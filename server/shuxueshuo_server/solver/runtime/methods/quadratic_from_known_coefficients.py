"""quadratic_from_known_coefficients 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class QuadraticFromKnownCoefficientsMethod:
    """代入已知系数，并用系数关系补齐缺失系数。"""

    method_id = "quadratic_from_known_coefficients"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        quadratic = inputs["quadratic"]
        relation = inputs["coefficient_relation"]
        known = inputs["known_coefficients"]
        all_coefficients = inputs["all_coefficients"]
        values = solve_missing_coefficients(kernel, relation, known, all_coefficients)
        parabola = substitute_known_coefficients(kernel, quadratic, values)
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "coefficients": TypedValue("Coefficients", values, source=self.method_id),
                "parabola": TypedValue("Parabola", sp.expand(parabola), source=self.method_id),
            },
            checks=[
                _check(
                    "known_coefficients_match_relation",
                    sp.simplify(relation.lhs.subs(values) - relation.rhs.subs(values)) == 0,
                    "补齐后的系数满足题设关系",
                )
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "代入已知系数求抛物线",
                    "写出当前问的抛物线解析式",
                    "已知系数直接代入，缺失系数由题设关系确定。",
                    ", ".join(f"{symbol.name}={kernel.sstr(value)}" for symbol, value in values.items()),
                    f"y={kernel.sstr(parabola)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=QuadraticFromKnownCoefficientsMethod,
    title='代入已知系数求抛物线',
    solves=('derive_quadratic_from_known_coefficients',),
    inputs={
    "quadratic": {
        "type": "Expression",
        "required": True
    },
    "coefficient_relation": {
        "type": "Equation",
        "required": True
    },
    "known_coefficients": {
        "type": "Coefficients",
        "required": True
    },
    "all_coefficients": {
        "type": "SymbolList",
        "required": True
    }
},
    outputs={
    "coefficients": "Coefficients",
    "parabola": "Parabola"
},
    preconditions=('known_coefficients 与 coefficient_relation 必须能唯一确定 all_coefficients 中的所有系数', 'coefficient_relation 不能与 known_coefficients 矛盾', '若存在多个候选系数解或仍有未定系数，本 method 不适用'),
    postconditions=(),
    trace_template=(),
)
