"""quadratic_coefficients_from_curve_points 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class QuadraticCoefficientsFromCurvePointsMethod:
    """由点在抛物线上和额外方程求二次函数通式。"""

    method_id = "quadratic_coefficients_from_curve_points"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        quadratic = inputs["quadratic"]
        x = inputs["x"]
        points = [inputs["p1"], inputs["p2"]]
        relation = inputs["coefficient_relation"]
        unknowns = inputs["unknowns"]
        parameter = inputs.get("parameter")
        parameter_value = inputs.get("parameter_value")
        if parameter is not None and parameter_value is not None:
            substitutions = {parameter: parameter_value}
            points = [_subs_point(point, substitutions) for point in points]
        solution = solve_coefficients_from_curve_points(
            kernel,
            quadratic,
            x,
            points,
            [relation],
            unknowns,
        )
        parabola = sp.factor(quadratic.subs(solution))
        checks = [
            _check(
                "coefficients_match_relation",
                sp.simplify(relation.lhs.subs(solution) - relation.rhs.subs(solution)) == 0,
                "通式系数满足题设关系",
            )
        ]
        for index, point in enumerate(points):
            checks.append(
                _check(
                    f"curve_point_{index}_on_parabola",
                    kernel.point_on_curve(point, parabola, x),
                    "代入点满足通式抛物线",
                )
            )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "coefficients": TypedValue("Coefficients", solution, source=self.method_id),
                "parabola": TypedValue("Parabola", parabola, source=self.method_id),
            },
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "由点在抛物线上求抛物线",
                    "确定当前小问的二次函数系数",
                    _curve_points_reason(parameter, parameter_value, kernel),
                    ", ".join(f"{symbol.name}={kernel.sstr(value)}" for symbol, value in solution.items()),
                    f"y={kernel.sstr(parabola)}",
                )
            ],
        )


SPEC = MethodSpecSource(
    method_cls=QuadraticCoefficientsFromCurvePointsMethod,
    title='由点在抛物线上求通式',
    solves=('derive_quadratic_coefficients',),
    inputs={
    "quadratic": {
        "type": "Expression",
        "required": True
    },
    "x": {
        "type": "Symbol",
        "required": True
    },
    "p1": {
        "type": "Point",
        "required": True
    },
    "p2": {
        "type": "Point",
        "required": True
    },
    "coefficient_relation": {
        "type": "Equation",
        "required": True
    },
    "unknowns": {
        "type": "SymbolList",
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
    "coefficients": "Coefficients",
    "parabola": "Parabola"
},
    preconditions=(),
    postconditions=(),
    trace_template=(),
)
