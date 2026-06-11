"""quadratic_x_axis_intercept_point 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from ._common import *
from ._spec import MethodSpecSource


class QuadraticXAxisInterceptPointMethod:
    """由二次函数解析式求与 x 轴的交点。

    该 method 用于“已知抛物线与 x 轴的一个交点，求另一个交点”这类常见场景。
    输入抛物线可以含一个参数，输出点坐标也会保留该参数表达式，例如
    ``y=-x**2+b*x+b+1`` 且已知 ``A(-1,0)`` 时，另一个交点为 ``(b+1,0)``。
    若目标 PointRef 声明了 ``side=left/right``，则在两个交点中选对应的
    左侧或右侧交点。
    """

    method_id = "quadratic_x_axis_intercept_point"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        quadratic = inputs["quadratic"]
        x = inputs["x"]
        target: PointRef = inputs["target"]
        known_point: Point | None = inputs.get("known_point")

        roots = [sp.simplify(root) for root in kernel.solve_values(sp.Eq(quadratic, 0), x)]
        candidates: list[Point] = [(root, sp.Integer(0)) for root in roots]
        if known_point is not None:
            candidates = [
                point
                for point in candidates
                if sp.simplify(point[0] - known_point[0]) != 0
            ]
        if len(candidates) > 1:
            side = _target_intercept_side(target)
            if side is not None:
                candidates = _pick_side_intercept(candidates, side)
        if len(candidates) != 1:
            raise ValueError(
                f"x_axis_intercept cannot uniquely determine {target.name}: "
                f"{[kernel.sstr(point[0]) for point in candidates]}"
            )
        point = candidates[0]
        checks = [
            _check("x_axis_y_is_zero", sp.simplify(point[1]) == 0, "x 轴交点的纵坐标为 0"),
            _check(
                "point_on_parabola",
                sp.simplify(quadratic.subs(x, point[0]) - point[1]) == 0,
                "点坐标满足抛物线解析式",
            ),
        ]
        if known_point is not None:
            checks.append(
                _check(
                    "different_from_known_intercept",
                    sp.simplify(point[0] - known_point[0]) != 0,
                    "求得的是不同于已知交点的另一个 x 轴交点",
                )
            )
        side = _target_intercept_side(target)
        if side is not None and len(roots) > 1:
            other_xs = [root for root in roots if sp.simplify(root - point[0]) != 0]
            if other_xs:
                comparisons = [sp.simplify(point[0] - other_x) for other_x in other_xs]
                if side == "left":
                    passed = all(_is_negative(value) for value in comparisons)
                    detail = "目标点声明为左侧 x 轴交点"
                else:
                    passed = all(_is_positive(value) for value in comparisons)
                    detail = "目标点声明为右侧 x 轴交点"
                checks.append(_check(f"{side}_x_axis_intercept", passed, detail))
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs={"point": TypedValue("Point", point, source=self.method_id)},
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "求 x 轴交点",
                    f"确定 {target.name} 的坐标",
                    "抛物线与 x 轴交点满足 y=0，解一元二次方程；若已知一个交点，则取另一个交点。",
                    f"{target.name}=({_fmt_point(point, kernel)})",
                    f"{target.name}({_fmt_point(point, kernel)})",
                )
            ],
        )


def _target_intercept_side(target: PointRef) -> str | None:
    side = target.definition.get("side")
    if isinstance(side, str):
        normalized = side.strip().lower()
        if normalized in {"left", "right"}:
            return normalized
    return None


def _pick_side_intercept(candidates: list[Point], side: str) -> list[Point]:
    selected: list[Point] = []
    for candidate in candidates:
        comparisons = [
            sp.simplify(candidate[0] - other[0])
            for other in candidates
            if other is not candidate
        ]
        if side == "left" and comparisons and all(_is_negative(value) for value in comparisons):
            selected.append(candidate)
        if side == "right" and comparisons and all(_is_positive(value) for value in comparisons):
            selected.append(candidate)
    return selected


def _is_negative(value: sp.Expr) -> bool:
    simplified = sp.simplify(value)
    if simplified.is_negative is not None:
        return bool(simplified.is_negative)
    try:
        return bool(sp.N(simplified) < 0)
    except TypeError:
        return False


def _is_positive(value: sp.Expr) -> bool:
    simplified = sp.simplify(value)
    if simplified.is_positive is not None:
        return bool(simplified.is_positive)
    try:
        return bool(sp.N(simplified) > 0)
    except TypeError:
        return False


SPEC = MethodSpecSource(
    method_cls=QuadraticXAxisInterceptPointMethod,
    title="求二次函数与 x 轴交点",
    summary="输入: 抛物线表达式、变量和目标 PointRef，可带已知交点或目标左右侧声明；输出: x 轴交点，坐标可保留参数。",
    solves=("derive_quadratic_x_axis_intercept_point",),
    inputs={
        "quadratic": {"type": "Parabola", "required": True},
        "x": {"type": "Symbol", "required": True},
        "target": {"type": "PointRef", "required": True},
        "known_point": {"type": "Point", "required": False},
    },
    outputs={"point": "Point"},
    preconditions=("quadratic 是关于 x 的函数表达式，可以含未定系数",),
    postconditions=("输出点纵坐标为 0 且在曲线上；若给定 known_point，则输出另一个 x 轴交点；若目标 PointRef 声明 side=left/right，则输出对应左右交点",),
)
