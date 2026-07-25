"""select_curve_point_candidate_and_solve_coefficients 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class SelectCurvePointCandidateAndSolveCoefficientsMethod:
    """从几何候选点中选择能落在抛物线上的点，并同步求系数。

    典型场景是：几何关系先给出目标点的多个候选坐标；再用已知点、目标点都在
    当前抛物线上以及参数范围，筛掉不符合题设的候选，并同步得到系数与抛物线。
    如果上一步已经把已知点条件吸收到含参抛物线中，本 method 也可以只把目标点
    代回当前抛物线，再通过 ``coefficient_dependencies`` 补齐其他系数。
    """

    method_id = "select_curve_point_candidate_and_solve_coefficients"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        candidates = list(inputs["candidates"])
        target: PointRef = inputs["target"]
        quadratic = inputs["quadratic"]
        x = inputs["x"]
        curve_point: Point | None = inputs.get("curve_point")
        known = dict(inputs.get("known_coefficients", {}))
        coefficient_dependencies = dict(inputs.get("coefficient_dependencies", {}))
        primary_symbol = inputs["primary_symbol"]
        secondary_symbol = inputs["secondary_symbol"]
        primary_constraint = inputs["primary_constraint"]
        if coefficient_dependencies:
            # 当前抛物线已包含部分约束时，通常只需要解主参数 b；
            # 其他系数（如 c=-b-2）由 coefficient_dependencies 代回得到。
            unknowns = [primary_symbol]
        else:
            unknowns = [symbol for symbol in inputs["unknowns"] if symbol not in known]

        valid: list[tuple[Point, dict[sp.Symbol, sp.Expr], sp.Expr]] = []
        base_equation = (
            sp.Eq(quadratic.subs(known).subs(x, curve_point[0]), curve_point[1])
            if curve_point is not None
            else None
        )
        for candidate in candidates:
            candidate_equation = sp.Eq(quadratic.subs(known).subs(x, candidate[0]), candidate[1])
            equations = [candidate_equation]
            if base_equation is not None:
                equations.insert(0, base_equation)
            for solution in kernel.solve_equations(equations, unknowns):
                values = _merge_coefficient_values(known, coefficient_dependencies, solution)
                if not _value_satisfies_constraint(values.get(primary_symbol), primary_constraint):
                    continue
                point = _subs_point(candidate, values)
                parabola = sp.expand(quadratic.subs(values))
                if sp.simplify(parabola.subs(x, point[0]) - point[1]) == 0:
                    valid.append((point, values, parabola))

        if len(valid) != 1:
            raise ValueError(f"候选点不能唯一确定 {target.name}: {len(valid)} valid candidates")
        point, values, parabola = valid[0]
        primary_value = sp.simplify(values[primary_symbol])
        secondary_value = sp.simplify(values[secondary_symbol])
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={
                "point": TypedValue("Point", point, source=self.method_id),
                "coefficients": TypedValue("Coefficients", values, source=self.method_id),
                "primary_value": TypedValue("ParameterValue", primary_value, source=self.method_id),
                "secondary_value": TypedValue("ParameterValue", secondary_value, source=self.method_id),
                "parabola": TypedValue("Parabola", parabola, source=self.method_id),
            },
            checks=[
                _check("unique_curve_candidate", True, "只有一个候选点满足曲线与系数约束"),
                _check(
                    "primary_constraint_satisfied",
                    _value_satisfies_constraint(primary_value, primary_constraint),
                    f"{primary_symbol.name} 满足题设约束",
                ),
                _check(
                    "selected_point_on_parabola",
                    sp.simplify(parabola.subs(x, point[0]) - point[1]) == 0,
                    f"{target.name} 在求得的抛物线上",
                ),
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    f"代入 {target.name} 候选并求系数",
                    f"确定 {target.name} 及抛物线系数",
                    _reason_text(target.name, curve_point is not None),
                    (
                        f"{primary_symbol.name}={kernel.sstr(primary_value)}, "
                        f"{secondary_symbol.name}={kernel.sstr(secondary_value)}"
                    ),
                    f"{target.name}({_fmt_point(point, kernel)})，y={kernel.sstr(parabola)}",
                )
            ],
        )


def _value_satisfies_constraint(value: sp.Expr | None, constraint: dict[str, sp.Expr | str]) -> bool:
    """校验 ``>`` 形式的单个参数约束。"""
    if value is None:
        return False
    if str(constraint.get("operator", "")) != ">":
        return True
    return bool(sp.simplify(value - sp.sympify(constraint["value"])) > 0)


def _merge_coefficient_values(
    known: dict[sp.Symbol, sp.Expr],
    dependencies: dict[sp.Symbol, sp.Expr],
    solution: dict[sp.Symbol, sp.Expr],
) -> dict[sp.Symbol, sp.Expr]:
    """合并已知系数、依赖系数和本次解出的参数值。

    例如前序步骤得到 ``a=2, c=-b-2``，本步骤由候选点解出一个 ``b`` 值后，
    需要同步代回得到对应的 ``c``。
    """
    values: dict[sp.Symbol, sp.Expr] = {}
    for symbol, value in {**known, **dependencies}.items():
        values[symbol] = sp.simplify(sp.sympify(value).subs(solution))
    values.update({symbol: sp.simplify(value) for symbol, value in solution.items()})
    return values


def _reason_text(target_name: str, has_curve_point: bool) -> str:
    """根据是否还需要额外曲线点，生成更贴近学生推导的说明。"""
    if has_curve_point:
        return f"直角等长给出两个候选点；逐个把候选 {target_name} 与已知曲线点代入当前问抛物线，再用参数约束筛选。"
    return f"直角等长给出两个候选点；已知曲线点条件已在上一步代入，所以这里只需逐个把候选 {target_name} 代入当前问抛物线，再用参数约束筛选。"


SPEC = MethodSpecSource(
    method_cls=SelectCurvePointCandidateAndSolveCoefficientsMethod,
    title="候选点筛选并求系数",
    summary="输入: 候选点、抛物线约束和参数约束；输出: 被选中的曲线点、系数和抛物线。",
    solves=("select_curve_point_candidate_and_solve_coefficients",),
    inputs={
        "candidates": {"type": "PointList", "required": True},
        "target": {"type": "PointRef", "required": True},
        "quadratic": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "curve_point": {"type": "Point", "required": False},
        "known_coefficients": {"type": "Coefficients", "required": False},
        "coefficient_dependencies": {"type": "Coefficients", "required": False},
        "unknowns": {"type": "SymbolList", "required": False},
        "primary_symbol": {"type": "Symbol", "required": True},
        "secondary_symbol": {"type": "Symbol", "required": True},
        "primary_constraint": {"type": "Constraint", "required": True},
    },
    outputs={
        "point": "Point",
        "coefficients": "Coefficients",
        "primary_value": "ParameterValue",
        "secondary_value": "ParameterValue",
        "parabola": "Parabola",
    },
    preconditions=("candidates 来自已验证的几何构造", "primary_constraint 是单参数约束"),
    postconditions=("唯一候选点满足抛物线与参数约束",),
)
