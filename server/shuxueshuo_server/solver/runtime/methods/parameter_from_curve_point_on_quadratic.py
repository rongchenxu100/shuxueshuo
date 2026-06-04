"""parameter_from_curve_point_on_quadratic 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class ParameterFromCurvePointOnQuadraticMethod:
    """由含参抛物线和含参曲线点反求参数。

    这个 method 处理的是一个很小、很常见的动作：当前问已经得到只含一个参数的
    抛物线，且某个点坐标也由同一个参数表达。把该点代入抛物线即可解出参数，
    再把参数代回点和抛物线。

    典型例子是河西第（Ⅱ）问：已知当前问抛物线
    ``y=2*x**2-b*x-b-2``，几何候选已经筛成 ``D=(b+1,1)``，代入曲线得到
    ``b=-1+sqrt(2)``，从而得到 ``D=(sqrt(2),1)`` 和最终抛物线。
    """

    method_id = "parameter_from_curve_point_on_quadratic"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        quadratic = inputs["quadratic"]
        x = inputs["x"]
        point: Point = inputs["point"]
        parameter = inputs["parameter"]
        constraint = inputs.get("parameter_constraint")

        equation = sp.Eq(quadratic.subs(x, point[0]), point[1])
        solutions = kernel.solve_equations([equation], [parameter])
        valid_values = [
            sp.simplify(solution[parameter])
            for solution in solutions
            if parameter in solution and _value_satisfies_constraint(solution[parameter], constraint)
        ]
        if len(valid_values) != 1:
            raise ValueError(
                f"曲线点条件不能唯一确定参数 {parameter.name}: {len(valid_values)} valid values"
            )
        parameter_value = valid_values[0]
        substitution = {parameter: parameter_value}
        resolved_point = _subs_point(point, substitution)
        parabola = sp.expand(quadratic.subs(substitution))

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "parameter_value": TypedValue("ParameterValue", parameter_value, source=self.method_id),
                "point": TypedValue("Point", resolved_point, source=self.method_id),
                "parabola": TypedValue("Parabola", parabola, source=self.method_id),
            },
            checks=[
                _check(
                    "parameter_constraint_satisfied",
                    _value_satisfies_constraint(parameter_value, constraint),
                    f"{parameter.name} 满足题设参数约束",
                ),
                _check(
                    "resolved_point_on_parabola",
                    sp.simplify(parabola.subs(x, resolved_point[0]) - resolved_point[1]) == 0,
                    "代入参数后的点在抛物线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由曲线点反求参数",
                    f"确定参数 {parameter.name} 并代回点坐标",
                    "把含参点坐标代入当前问含参抛物线，结合参数约束选出唯一参数值。",
                    f"{parameter.name}={kernel.sstr(parameter_value)}",
                    f"点({_fmt_point(resolved_point, kernel)})，y={kernel.sstr(parabola)}",
                )
            ],
        )


def _value_satisfies_constraint(
    value: sp.Expr,
    constraint: dict[str, sp.Expr | str] | None,
) -> bool:
    """校验当前轻量 Constraint 结构；首版主要支持 ``>``。"""
    if constraint is None:
        return True
    if str(constraint.get("operator", "")) != ">":
        return True
    try:
        return bool(sp.simplify(value - sp.sympify(constraint["value"])) > 0)
    except TypeError:
        return False


SPEC = MethodSpecSource(
    method_cls=ParameterFromCurvePointOnQuadraticMethod,
    title="由曲线点反求参数并代回抛物线",
    summary=(
        "输入: 含一个参数的抛物线、由同一参数表示的曲线点和参数约束；"
        "输出: 参数值、代回后的点坐标和抛物线。"
    ),
    solves=("derive_parameter_from_curve_point_on_quadratic",),
    inputs={
        "quadratic": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "point": {"type": "Point", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {"type": "Constraint", "required": False},
    },
    outputs={
        "parameter_value": "ParameterValue",
        "point": "Point",
        "parabola": "Parabola",
    },
    preconditions=(
        "quadratic 与 point 必须只共享同一个待求参数",
        "点代入抛物线后，在参数约束下必须唯一确定参数值",
    ),
    postconditions=(
        "输出 point 是代入参数后的坐标",
        "输出 parabola 是代入参数后的当前问抛物线",
    ),
)
