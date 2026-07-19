"""parameter_from_curve_point_on_quadratic 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from shuxueshuo_server.solver.runtime.symbolic_target_closure import (
    TargetSymbolClosureResult,
    solve_target_symbol_closure,
)

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
        known_parameter = inputs.get("known_parameter")
        known_parameter_value = inputs.get("known_parameter_value")
        quadratic_template = inputs.get("quadratic_template")

        if (known_parameter is None) != (known_parameter_value is None):
            raise ValueError(
                "function.arg_missing: known_parameter and "
                "known_parameter_value must be provided together"
            )

        known_substitution = (
            {known_parameter: known_parameter_value}
            if known_parameter is not None
            else {}
        )
        specialized_quadratic = sp.expand(quadratic.subs(known_substitution))
        specialized_point = _subs_point(point, known_substitution)
        residual = sp.simplify(
            specialized_quadratic.subs(x, specialized_point[0])
            - specialized_point[1]
        )
        closure = solve_target_symbol_closure(
            [sp.Eq(residual, 0)],
            target=parameter,
            target_expression=_quadratic_coefficient_expression(
                specialized_quadratic,
                x=x,
                target=parameter,
                quadratic_template=quadratic_template,
            ),
            kernel=kernel,
            accept_target=lambda value: _value_satisfies_constraint(
                value,
                constraint,
            ),
        )
        parameter_value, substitution = _resolved_target_value(
            closure,
            constraint=constraint,
        )
        resolved_point = _subs_point(specialized_point, substitution)
        parabola = sp.expand(specialized_quadratic.subs(substitution))

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
                    (
                        "把含参点坐标代入当前问含参抛物线；若方程先确定等价的"
                        "内部系数，则沿当前系数表达式闭包到目标参数。"
                    ),
                    f"{parameter.name}={kernel.sstr(parameter_value)}",
                    f"点({_fmt_point(resolved_point, kernel)})，y={kernel.sstr(parabola)}",
                )
            ],
        )


def _quadratic_coefficient_expression(
    quadratic: sp.Expr,
    *,
    x: sp.Symbol,
    target: sp.Symbol,
    quadratic_template: sp.Expr | None,
) -> sp.Expr | None:
    """Return the current expression for a requested quadratic coefficient."""
    if quadratic_template is None or target not in quadratic_template.free_symbols:
        return None
    current = sp.Poly(sp.expand(quadratic), x)
    template = sp.Poly(sp.expand(quadratic_template), x)
    candidates: list[sp.Expr] = []
    for power in range(max(current.degree(), template.degree()), -1, -1):
        template_coefficient = template.coeff_monomial(x**power)
        if target not in template_coefficient.free_symbols:
            continue
        current_coefficient = current.coeff_monomial(x**power)
        solutions = sp.solve(
            sp.Eq(template_coefficient, current_coefficient),
            target,
            dict=True,
        )
        candidates.extend(
            sp.simplify(solution[target])
            for solution in solutions
            if target in solution and target not in solution[target].free_symbols
        )
    unique = []
    for candidate in candidates:
        if not any(sp.simplify(candidate - item) == 0 for item in unique):
            unique.append(candidate)
    return unique[0] if len(unique) == 1 else None


def _resolved_target_value(
    closure: TargetSymbolClosureResult,
    *,
    constraint: dict[str, sp.Expr | str] | None,
) -> tuple[sp.Expr, dict[sp.Symbol, sp.Expr]]:
    residual_names = ", ".join(
        symbol.name for symbol in closure.residual_symbols
    ) or "<none>"
    if closure.status == "identity_unresolved":
        raise ValueError(
            "function.parameter_identity_mismatch: "
            f"target={closure.target.name}, residual_symbols={residual_names}; "
            "the bounded call has no deterministic mapping to the target Symbol"
        )
    if closure.status == "underdetermined":
        raise ValueError(
            "function.constraints_underdetermined: "
            f"target={closure.target.name}, residual_symbols={residual_names}"
        )
    if closure.status == "ambiguous":
        raise ValueError(
            "function.constraints_ambiguous: "
            f"target={closure.target.name}, branch_count={closure.branch_count}"
        )
    if closure.status == "inconsistent" or closure.target_value is None:
        raise ValueError(
            "function.constraints_inconsistent: curve-point equation has no solution"
        )
    if not _value_satisfies_constraint(closure.target_value, constraint):
        raise ValueError(
            "function.constraints_inconsistent: target value violates its constraint"
        )
    substitution = closure.substitution
    substitution[closure.target] = closure.target_value
    return closure.target_value, substitution


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
        "已有当前抛物线和曲线上一点；先代入已知参数值，再用曲线点方程唯一"
        "确定目标参数。若方程直接确定另一二次函数系数，代码会沿当前系数"
        "表达式闭包到目标参数，并更新点和抛物线。"
    ),
    do_not_use_when=(
        "代入当前已知参数值后仍有两个及以上未确定参数，且无法由当前二次函数系数表达式唯一闭包到目标参数。",
        "需要先推导曲线表达式或点坐标，而不是利用已有曲线点条件反求参数。",
    ),
    solves=("derive_parameter_from_curve_point_on_quadratic",),
    inputs={
        "quadratic": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "point": {"type": "Point", "required": True},
        "parameter": {"type": "Symbol", "required": True},
        "parameter_constraint": {"type": "Constraint", "required": False},
        "known_parameter": {"type": "Symbol", "required": False},
        "known_parameter_value": {"type": "ParameterValue", "required": False},
        "quadratic_template": {"type": "Expression", "required": False},
    },
    outputs={
        "parameter_value": "ParameterValue",
        "point": "Point",
        "parabola": "Parabola",
    },
    preconditions=(
        "应用已知参数值后，曲线点方程必须直接唯一确定目标参数，或唯一确定可映射到目标参数的二次函数系数",
        "点代入抛物线后，在参数约束下必须唯一确定参数值",
    ),
    postconditions=(
        "输出 point 是代入参数后的坐标",
        "输出 parabola 是代入参数后的当前问抛物线",
    ),
)
