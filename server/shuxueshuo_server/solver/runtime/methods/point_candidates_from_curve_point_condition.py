"""point_candidates_from_curve_point_condition 无状态 method。

由参数化目标点、同参数曲线点和曲线条件，求目标点候选列表。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class PointCandidatesFromCurvePointConditionMethod:
    """把同参数曲线点代入二次函数，反求目标点候选。"""

    method_id = "point_candidates_from_curve_point_condition"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        target_point: Point = inputs["target_point"]
        curve_point: Point = inputs["curve_point"]
        parabola = inputs["parabola"]
        x = inputs["x"]

        parameter = _unique_point_parameter(target_point, curve_point, parabola, x)
        equation = sp.Eq(parabola.subs(x, curve_point[0]), curve_point[1])
        roots = [sp.simplify(root) for root in kernel.solve_values(equation, parameter)]
        candidates = _unique_points(
            [
                (sp.simplify(target_point[0].subs(parameter, root)), sp.simplify(target_point[1].subs(parameter, root)))
                for root in roots
            ],
            kernel,
        )
        if not candidates:
            raise ValueError("curve point condition has no target point candidates")

        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"candidates": TypedValue("PointList", candidates, source=self.method_id)},
            checks=[
                _check("candidate_count_positive", bool(candidates), "至少得到一个目标点候选"),
                *[
                    _check(
                        f"curve_point_{index}_on_curve",
                        kernel.point_on_curve(_subs_point(curve_point, {parameter: root}), parabola, x),
                        "同参数曲线点在抛物线上",
                    )
                    for index, root in enumerate(roots, start=1)
                ],
            ],
            trace_fragments=[
                _step(
                    self.method_id,
                    "由曲线点条件求目标候选",
                    "求目标点候选列表",
                    "目标点和曲线点含同一个参数；把曲线点代入抛物线求参数，再回代目标点。",
                    f"{parameter.name}=" + " 或 ".join(kernel.sstr(root) for root in roots),
                    _fmt_point_candidates("P", candidates, kernel),
                )
            ],
        )


def _unique_point_parameter(
    target_point: Point,
    curve_point: Point,
    parabola: sp.Expr,
    x: sp.Symbol,
) -> sp.Symbol:
    """从两个点表达式中找出唯一非曲线参数。"""
    point_symbols = set().union(*(coord.free_symbols for coord in (*target_point, *curve_point)))
    curve_symbols = set(parabola.free_symbols) | {x}
    candidates = sorted(point_symbols - curve_symbols, key=lambda symbol: symbol.name)
    if len(candidates) != 1:
        raise ValueError("curve point condition requires exactly one point parameter")
    return candidates[0]


def _unique_points(points: list[Point], kernel: SympyKernel) -> list[Point]:
    """按格式化结果去重点候选，并保持稳定顺序。"""
    result: list[Point] = []
    seen: set[tuple[str, str]] = set()
    for point in points:
        key = (kernel.sstr(point[0]), kernel.sstr(point[1]))
        if key in seen:
            continue
        seen.add(key)
        result.append(point)
    result.sort(key=lambda point: (kernel.sstr(point[0]), kernel.sstr(point[1])))
    return result


SPEC = MethodSpecSource(
    method_cls=PointCandidatesFromCurvePointConditionMethod,
    title="由曲线点条件求目标点候选",
    summary=(
        "Given 目标点 P(t)、同参数曲线点 Q(t) 和已解抛物线, derive 使 Q(t) 在曲线上的 P 候选列表。"
        "适用于几何构造先得到两个同参数点，再用其中一个点落曲线来反求目标点的场景。"
    ),
    solves=("derive_point_candidates_from_curve_point_condition",),
    inputs={
        "target_point": {"type": "Point", "required": True},
        "curve_point": {"type": "Point", "required": True},
        "parabola": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
    },
    outputs={"candidates": "PointList"},
    preconditions=("target_point 与 curve_point 只共享一个待定参数", "parabola 已代入当前问已知条件"),
    postconditions=("输出每个目标点候选对应的 curve_point 都在抛物线上",),
)
