"""无状态 method 共享基础设施与 method 层辅助函数。

这个模块不包含任何具体题型 method。纯数学操作来自 ``math_ops``；这里只保留
无状态 method 的协议、注册表、trace/check 构造和少量路径文本处理。
"""

from __future__ import annotations

from typing import Any, Protocol

import sympy as sp

from shuxueshuo_server.solver.math_ops import (
    dot_from_origin,
    parametric_point_on_line,
    pick_by_lower_bound,
    point_collinear,
    point_complexity_score,
    reflect_point_across_line,
    rotated_equal_length_candidates,
    satisfies_lower_bound,
    solve_coefficients_from_curve_points,
    solve_missing_coefficients,
    subs_point,
    substitute_known_coefficients,
)
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.contracts import (
    CheckResult,
    DerivationStep,
    Point,
    PointRef,
    StatelessMethodResult,
    TypedValue,
)

__all__ = [
    "Any",
    "sp",
    "dot_from_origin",
    "parametric_point_on_line",
    "pick_by_lower_bound",
    "point_collinear",
    "point_complexity_score",
    "reflect_point_across_line",
    "rotated_equal_length_candidates",
    "satisfies_lower_bound",
    "solve_coefficients_from_curve_points",
    "solve_missing_coefficients",
    "subs_point",
    "substitute_known_coefficients",
    "SympyKernel",
    "CheckResult",
    "DerivationStep",
    "Point",
    "PointRef",
    "StatelessMethodResult",
    "TypedValue",
    "StatelessMethod",
    "StatelessMethodRegistry",
    "_check",
    "_step",
    "_subs_point",
    "_fmt_point",
    "_fmt_point_candidates",
    "_curve_points_reason",
    "_parse_scaled_segment",
    "_other_segment_endpoint",
    "_validate_moving_point_memberships",
    "_replace_segment_in_path",
    "_parse_path_segments",
    "_common_endpoint",
    "_generic_point_on_line",
    "_reflect_point_across_line",
    "_point_complexity",
    "_straightening_candidate",
    "_point_matches_quadrant_under_lower_bound",
]

_subs_point = subs_point
_generic_point_on_line = parametric_point_on_line
_reflect_point_across_line = reflect_point_across_line
_point_complexity = point_complexity_score


class StatelessMethod(Protocol):
    """无状态 method 的最小协议。

    method 只接收 executor 解析后的 typed inputs，并返回 typed outputs、checks
    与 trace fragments；它不能读写 RuntimeContext 或 fixture。
    """

    method_id: str

    def run(
        self,
        inputs: dict[str, Any],
        kernel: SympyKernel,
    ) -> StatelessMethodResult:
        ...


class StatelessMethodRegistry:
    """无状态 method 实例注册表。"""

    def __init__(self, methods: dict[str, StatelessMethod]) -> None:
        self.methods = methods

    def require(self, method_id: str) -> StatelessMethod:
        """按 method_id 获取实际可执行的 method 实例。"""
        try:
            return self.methods[method_id]
        except KeyError as exc:
            raise KeyError(f"stateless method not found: {method_id}") from exc


def _check(name: str, passed: bool, detail: str) -> CheckResult:
    """创建 CheckResult。"""
    return CheckResult(name=name, status="passed" if bool(passed) else "failed", detail=detail)


def _step(
    method_id: str,
    title: str,
    goal: str,
    reason: str,
    calculation: str,
    conclusion: str,
) -> DerivationStep:
    """创建 DerivationStep。"""
    return DerivationStep(
        title=title,
        goal=goal,
        reason=reason,
        calculation=calculation,
        conclusion=conclusion,
        method_id=method_id,
    )


def _fmt_point(point: Point, kernel: SympyKernel) -> str:
    """把 SymPy 点坐标格式化成 trace 里可读的字符串。"""
    return f"{kernel.sstr(point[0])}, {kernel.sstr(point[1])}"


def _fmt_point_candidates(name: str, candidates: list[Point], kernel: SympyKernel) -> str:
    """把候选点列表格式化为 ``N1=(...), N2=(...)``。"""
    return ", ".join(
        f"{name}{index}=({_fmt_point(point, kernel)})"
        for index, point in enumerate(candidates, start=1)
    )


def _curve_points_reason(
    parameter: sp.Symbol | None,
    parameter_value: sp.Expr | None,
    kernel: SympyKernel,
) -> str:
    """生成“点在曲线上求系数”步骤的解释文本。"""
    if parameter is None or parameter_value is None:
        return "把点坐标代入抛物线，并联立系数关系。"
    return (
        f"先代入 {parameter.name}={kernel.sstr(parameter_value)}，"
        "再把点坐标代入抛物线，并联立系数关系。"
    )


def _extract_segment_name(raw: str) -> str:
    """从 ``sqrt(2)*NG`` 这类表达式中取出线段名 ``NG``。"""
    letters = "".join(char for char in raw if char.isupper())
    return letters[-2:] if len(letters) >= 2 else letters


def _parse_scaled_segment(raw: str, kernel: SympyKernel) -> tuple[sp.Expr, str]:
    """解析 ``sqrt(2)*NG`` 为 ``(sqrt(2), "NG")``。"""
    segment = _extract_segment_name(raw)
    if len(segment) != 2:
        raise ValueError(f"cannot parse segment name from {raw!r}")
    coefficient_text = raw.replace(segment, "", 1).strip().rstrip("*").strip()
    coefficient = kernel.expr(coefficient_text) if coefficient_text else sp.Integer(1)
    return sp.simplify(coefficient), segment


def _other_segment_endpoint(segment: str, endpoint: str) -> str:
    """给定线段名和一个端点名，返回另一个端点名。"""
    if endpoint not in segment or len(segment) != 2:
        raise ValueError(f"segment {segment!r} does not contain endpoint {endpoint!r}")
    return segment[1] if segment[0] == endpoint else segment[0]


def _validate_moving_point_memberships(
    first_segment: list[str],
    second_segment: list[str],
    fixed_name: str,
    second_fixed_name: str,
) -> None:
    """校验两个动点所在边与绑定关系的端点一致。"""
    if fixed_name not in first_segment:
        raise ValueError(f"fixed endpoint {fixed_name!r} is not on first moving segment")
    if second_fixed_name not in second_segment:
        raise ValueError(f"fixed endpoint {second_fixed_name!r} is not on second moving segment")
    if not (set(first_segment) & set(second_segment)):
        raise ValueError("two moving point segments must share one endpoint")


def _replace_segment_in_path(path: str, source: str, target: str) -> str:
    """在路径表达式中替换线段名，同时兼容反向线段。"""
    if source in path:
        return path.replace(source, target, 1)
    reversed_source = source[::-1]
    if reversed_source in path:
        return path.replace(reversed_source, target[::-1], 1)
    raise ValueError(f"path {path!r} does not contain segment {source!r}")


def _parse_path_segments(path: str) -> list[str]:
    """把 ``DG+FG`` 这类路径表达式拆成线段名列表。"""
    return [
        segment.strip()
        for segment in path.replace("＋", "+").split("+")
        if segment.strip()
    ]


def _common_endpoint(segment1: str, segment2: str) -> str:
    """返回两条线段共有的端点名。"""
    common = sorted(set(segment1) & set(segment2))
    if len(common) != 1:
        raise ValueError(f"segments must share exactly one endpoint: {segment1}, {segment2}")
    return common[0]


def _reflected_point_name(source_name: str) -> str:
    """把点名转成辅助反射点名。"""
    return f"{source_name}_prime"


def _straightening_candidate(
    *,
    kernel: SympyKernel,
    transformed_path: str,
    moving_point_name: str,
    moving_line_name: str,
    source_name: str,
    source_point: Point,
    other_name: str,
    other_point: Point,
    line_point_1: Point,
    line_point_2: Point,
) -> dict[str, Any]:
    """构造一个“反射某个固定端点”的折线拉直候选。"""
    reflected_point = _reflect_point_across_line(source_point, line_point_1, line_point_2)
    reflected_name = _reflected_point_name(source_name)
    source_segment = f"{source_name}{moving_point_name}"
    reflected_segment = f"{reflected_name}{moving_point_name}"
    straightened_path = _replace_segment_in_path(
        transformed_path,
        source_segment,
        reflected_segment,
    )
    minimum_segment = f"{reflected_name}{other_name}"
    return {
        "id": f"reflect_{source_name}",
        "reflect_source": source_name,
        "reflected_point_name": reflected_name,
        "reflected_point": reflected_point,
        "source_point": source_point,
        "moving_point": moving_point_name,
        "moving_line": moving_line_name,
        "other_fixed_point": other_name,
        "transformed_path": transformed_path,
        "straightened_path": straightened_path,
        "segment_equality": f"{source_segment}={reflected_segment}",
        "minimum_segment": minimum_segment,
        "minimum_endpoints": (reflected_point, other_point),
        "complexity_score": _point_complexity(reflected_point, kernel),
    }


def _point_matches_quadrant_under_lower_bound(
    point: Point,
    quadrant: str,
    parameter: sp.Symbol,
    lower_bound: sp.Expr,
) -> bool:
    """判断点在 ``parameter > lower_bound`` 下是否恒属于指定象限。

    当前实现覆盖本阶段需要的线性含参坐标。它不是随便取样，而是检查坐标在
    下界右侧的符号是否不会改变；无法证明时返回 False，让 method 暴露为不适用。
    """
    sign_requirements = _quadrant_sign_requirements(quadrant)
    if sign_requirements is None:
        return False
    x_positive, y_positive = sign_requirements
    return (
        _expr_positive_under_lower_bound(point[0], parameter, lower_bound)
        if x_positive
        else _expr_negative_under_lower_bound(point[0], parameter, lower_bound)
    ) and (
        _expr_positive_under_lower_bound(point[1], parameter, lower_bound)
        if y_positive
        else _expr_negative_under_lower_bound(point[1], parameter, lower_bound)
    )


def _quadrant_sign_requirements(quadrant: str) -> tuple[bool, bool] | None:
    """返回象限对应的 x/y 正负要求。"""
    if quadrant in ("第一象限", "1", "I"):
        return (True, True)
    if quadrant in ("第二象限", "2", "II"):
        return (False, True)
    if quadrant in ("第三象限", "3", "III"):
        return (False, False)
    if quadrant in ("第四象限", "4", "IV"):
        return (True, False)
    return None


def _expr_positive_under_lower_bound(
    expression: sp.Expr,
    parameter: sp.Symbol,
    lower_bound: sp.Expr,
) -> bool:
    """证明 expression 在 parameter > lower_bound 下恒正。"""
    expression = sp.simplify(expression)
    if not expression.has(parameter):
        return _is_positive(expression)
    slope = _linear_slope(expression, parameter)
    if slope is None:
        return False
    value_at_bound = sp.simplify(expression.subs(parameter, lower_bound))
    if _is_positive(slope) and _is_nonnegative(value_at_bound):
        return True
    if _is_zero(slope) and _is_positive(value_at_bound):
        return True
    return False


def _expr_negative_under_lower_bound(
    expression: sp.Expr,
    parameter: sp.Symbol,
    lower_bound: sp.Expr,
) -> bool:
    """证明 expression 在 parameter > lower_bound 下恒负。"""
    expression = sp.simplify(expression)
    if not expression.has(parameter):
        return _is_negative(expression)
    slope = _linear_slope(expression, parameter)
    if slope is None:
        return False
    value_at_bound = sp.simplify(expression.subs(parameter, lower_bound))
    if _is_negative(slope) and _is_nonpositive(value_at_bound):
        return True
    if _is_zero(slope) and _is_negative(value_at_bound):
        return True
    return False


def _linear_slope(expression: sp.Expr, parameter: sp.Symbol) -> sp.Expr | None:
    """返回一次表达式的斜率；非一次表达式返回 None。"""
    try:
        poly = sp.Poly(expression, parameter)
    except sp.PolynomialError:
        return None
    if poly.degree() > 1:
        return None
    return sp.simplify(poly.coeff_monomial(parameter))


def _is_positive(value: sp.Expr) -> bool:
    value = sp.simplify(value)
    return value.is_positive is True or (value.is_number and bool(sp.N(value) > 0))


def _is_negative(value: sp.Expr) -> bool:
    value = sp.simplify(value)
    return value.is_negative is True or (value.is_number and bool(sp.N(value) < 0))


def _is_nonnegative(value: sp.Expr) -> bool:
    value = sp.simplify(value)
    return value.is_nonnegative is True or (value.is_number and bool(sp.N(value) >= 0))


def _is_nonpositive(value: sp.Expr) -> bool:
    value = sp.simplify(value)
    return value.is_nonpositive is True or (value.is_number and bool(sp.N(value) <= 0))


def _is_zero(value: sp.Expr) -> bool:
    return sp.simplify(value) == 0
