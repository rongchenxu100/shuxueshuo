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
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FunctionalDiagnosticSubject,
    StatelessMethodError,
    method_check_failed,
    method_input_invalid,
    method_input_missing,
    method_input_state_unavailable,
    method_precondition_failed,
    method_result_ambiguous,
    method_result_empty,
    method_result_inconsistent,
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
    "FunctionalDiagnosticSubject",
    "StatelessMethodError",
    "method_check_failed",
    "method_input_invalid",
    "method_input_missing",
    "method_input_state_unavailable",
    "method_precondition_failed",
    "method_result_ambiguous",
    "method_result_empty",
    "method_result_inconsistent",
    "StatelessMethod",
    "StatelessMethodRegistry",
    "_check",
    "_step",
    "_free_symbols_in",
    "_canonicalize_runtime_constraint",
    "_require_canonical_runtime_expression",
    "_require_substitution_symbol",
    "_require_unique_symbolic_closure",
    "_optional_parameter_substitution",
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


def _check(
    name: str,
    passed: bool,
    detail: str,
    **diagnostic: Any,
) -> CheckResult:
    """创建 CheckResult。"""
    return CheckResult(
        name=name,
        status="passed" if bool(passed) else "failed",
        detail=detail,
        **diagnostic,
    )


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


def _free_symbols_in(value: Any) -> set[sp.Symbol]:
    """Collect symbolic dependencies from nested stateless-method values."""

    if isinstance(value, dict):
        result: set[sp.Symbol] = set()
        for item in value.values():
            result.update(_free_symbols_in(item))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        result: set[sp.Symbol] = set()
        for item in value:
            result.update(_free_symbols_in(item))
        return result
    try:
        expression = sp.sympify(value)
    except (TypeError, ValueError, sp.SympifyError):
        return set()
    return set(getattr(expression, "free_symbols", set()))


def _require_canonical_runtime_expression(
    value: Any,
    kernel: SympyKernel,
    *,
    arg_name: str,
    role: str,
) -> sp.Expr:
    """Reject source-authored symbolic strings at the Method boundary.

    Problem-origin expressions must be parsed once by ``RuntimeContext`` with
    its canonical Symbol identities.  Constant strings remain accepted for
    direct Method fixtures and literal metadata; a string with free symbols is
    evidence that compiler/runtime canonicalization was skipped.
    """

    try:
        expression = kernel.expr(
            value.replace("^", "**") if isinstance(value, str) else value,
            {"inf": sp.oo, "oo": sp.oo},
        )
    except (TypeError, ValueError, sp.SympifyError) as exc:
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            f"{arg_name} is not a valid canonical runtime expression",
            category="configuration",
            retryability="configuration",
            arg_name=arg_name,
            role=role,
            expected={"state": "canonical_sympy_expression"},
            observed={"type": type(value).__name__, "value": repr(value)},
            repair_action="fix_runtime_contract",
        ) from exc

    if isinstance(value, str) and expression.free_symbols:
        raise StatelessMethodError(
            "planner.method_contract_invalid",
            f"{arg_name} reached Method as an unbound symbolic string",
            category="configuration",
            retryability="configuration",
            arg_name=arg_name,
            role=role,
            expected={"state": "canonical_sympy_expression"},
            observed={
                "type": "str",
                "free_symbols": sorted(
                    symbol.name for symbol in expression.free_symbols
                ),
            },
            repair_action="fix_runtime_contract",
        )
    return expression


def _canonicalize_runtime_constraint(
    value: dict[str, Any] | None,
    kernel: SympyKernel,
    *,
    arg_name: str,
    role: str = "parameter_constraint",
) -> dict[str, Any] | None:
    """Canonicalize the scalar bound carried by a runtime Constraint."""

    if value is None:
        return None
    result = dict(value)
    if result.get("value") is not None:
        result["value"] = _require_canonical_runtime_expression(
            result["value"],
            kernel,
            arg_name=arg_name,
            role=role,
        )
    return result


def _require_substitution_symbol(
    value: Any,
    parameter: sp.Symbol,
) -> None:
    """Require a substitution to target an actual dependency identity."""

    if not isinstance(parameter, sp.Symbol):
        raise method_input_invalid(
            "substitution parameter must be a Symbol",
            arg_name="parameter",
            role="substitution_parameter",
            expected={"type": "Symbol"},
            observed={"type": type(parameter).__name__},
        )
    free_symbols = _free_symbols_in(value)
    if parameter in free_symbols:
        return
    names = "|".join(sorted(symbol.name for symbol in free_symbols)) or "none"
    raise method_precondition_failed(
        "function.substitution_symbol_mismatch: "
        f"parameter={parameter.name}, free_symbols={names}; "
        "substitution parameter is not a dependency of the input value",
        arg_name="parameter",
        role="substitution_parameter",
        internal_ref=parameter.name,
        expected={"dependency": parameter.name},
        observed={"free_symbols": names},
        repair_action="repair_input_binding",
    )


def _require_unique_symbolic_closure(
    result: Any,
    *,
    arg_name: str,
    role: str,
) -> Any:
    """Translate expected symbolic-closure outcomes at the Method boundary."""

    if result.status == "unique" and result.target_value is not None:
        from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
            require_unique_symbolic_closure,
        )

        return require_unique_symbolic_closure(result)

    target_name = result.target.name if result.target is not None else None
    observed = {
        "status": result.status,
        "branch_count": result.branch_count,
        "residual_symbols": [
            symbol.name for symbol in result.residual_symbols
        ],
    }
    from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
        closure_failure_code,
    )

    residual_text = ",".join(observed["residual_symbols"]) or "<none>"
    message = (
        f"{closure_failure_code(result.status)}: "
        f"target={target_name or '<unresolved>'}, "
        f"residual_symbols={residual_text}, "
        f"branch_count={result.branch_count}"
    )
    shared = {
        "arg_name": arg_name,
        "role": role,
        "internal_ref": target_name,
        "expected": {"status": "unique", "branch_count": 1},
        "observed": observed,
    }
    if result.status == "ambiguous":
        raise method_result_ambiguous(
            message,
            repair_action="supply_disambiguating_constraint",
            **shared,
        )
    if result.status == "inconsistent":
        raise method_result_inconsistent(
            message,
            retryability="planner_repairable",
            repair_action="revise_symbolic_constraints",
            **shared,
        )
    if result.status == "identity_unresolved":
        raise method_input_state_unavailable(
            message,
            repair_action="repair_target_binding",
            **shared,
        )
    if result.status in {"underdetermined", "not_applicable"}:
        raise method_result_empty(
            message,
            repair_action="provide_additional_constraint",
            **shared,
        )
    raise StatelessMethodError(
        "planner.method_contract_invalid",
        f"unsupported symbolic closure status: {result.status}",
        category="configuration",
        retryability="configuration",
        expected={"status_contract": "known_symbolic_closure_status"},
        observed=observed,
        repair_action="fix_runtime_contract",
    )


def _optional_parameter_substitution(
    inputs: dict[str, Any],
    *values: Any,
    allow_parameter_without_value: bool = False,
    allow_closed_noop: bool = False,
    closed_noop_ignored_symbols: Iterable[sp.Symbol] = (),
) -> dict[sp.Symbol, sp.Expr]:
    """Build an optional, identity-checked parameter substitution."""

    parameter_present = "parameter" in inputs and inputs.get("parameter") is not None
    value_present = (
        "parameter_value" in inputs
        and inputs.get("parameter_value") is not None
    )
    if value_present and not parameter_present:
        raise method_input_missing(
            "function.substitution_pair_incomplete: parameter_value requires "
            "its matching parameter Symbol",
            arg_name="parameter",
            role="substitution_parameter",
            expected={"paired_arg": "parameter_value"},
        )
    if parameter_present and not value_present:
        if allow_parameter_without_value:
            return {}
        raise method_input_missing(
            "function.substitution_pair_incomplete: parameter requires its "
            "matching parameter_value",
            arg_name="parameter_value",
            role="substitution_value",
            expected={"paired_arg": "parameter"},
        )
    if not parameter_present:
        return {}
    parameter = inputs["parameter"]
    free_symbols = _free_symbols_in(values)
    unresolved_symbols = free_symbols - set(closed_noop_ignored_symbols)
    if allow_closed_noop and parameter not in unresolved_symbols:
        return {}
    _require_substitution_symbol(values, parameter)
    return {parameter: sp.sympify(inputs["parameter_value"])}


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
        raise method_input_invalid(
            "scaled segment does not contain exactly two endpoint labels",
            arg_name="scaled_segment",
            role="path_segment",
            expected={"endpoint_count": 2},
            observed={"value": raw, "parsed_segment": segment},
        )
    coefficient_text = raw.replace(segment, "", 1).strip().rstrip("*").strip()
    coefficient = (
        _require_canonical_runtime_expression(
            coefficient_text,
            kernel,
            arg_name="scaled_segment",
            role="path_scale",
        )
        if coefficient_text
        else sp.Integer(1)
    )
    return sp.simplify(coefficient), segment


def _other_segment_endpoint(segment: str, endpoint: str) -> str:
    """给定线段名和一个端点名，返回另一个端点名。"""
    if endpoint not in segment or len(segment) != 2:
        raise method_precondition_failed(
            "segment does not contain the required endpoint",
            arg_name="segment",
            role="path_segment",
            internal_ref=endpoint,
            expected={"contains_endpoint": endpoint, "endpoint_count": 2},
            observed={"segment": segment},
        )
    return segment[1] if segment[0] == endpoint else segment[0]


def _canonical_reference_name(value: Any) -> str:
    """Return the local display name carried by a canonical runtime ref."""

    text = str(value)
    return text.rsplit(":", 1)[-1] if ":" in text else text


def _canonical_segment_name(value: Any) -> str:
    """Normalize a Segment ref or endpoint pair to its two-point name."""

    if isinstance(value, (list, tuple)) and len(value) == 2:
        return "".join(_canonical_reference_name(item) for item in value)
    return _canonical_reference_name(value)


def _validate_moving_point_memberships(
    first_segment: list[str],
    second_segment: list[str],
    fixed_name: str,
    second_fixed_name: str,
) -> None:
    """校验两个动点所在边与绑定关系的端点一致。"""
    if fixed_name not in first_segment:
        raise method_precondition_failed(
            "fixed endpoint is not on the first moving segment",
            role="fixed_endpoint_1",
            internal_ref=fixed_name,
            expected={"membership": list(first_segment)},
            observed={"endpoint": fixed_name},
        )
    if second_fixed_name not in second_segment:
        raise method_precondition_failed(
            "fixed endpoint is not on the second moving segment",
            role="fixed_endpoint_2",
            internal_ref=second_fixed_name,
            expected={"membership": list(second_segment)},
            observed={"endpoint": second_fixed_name},
        )
    if not (set(first_segment) & set(second_segment)):
        raise method_precondition_failed(
            "the two moving-point segments do not share an endpoint",
            role="moving_path",
            expected={"shared_endpoint_count": 1},
            observed={
                "first_segment": list(first_segment),
                "second_segment": list(second_segment),
            },
        )


def _replace_segment_in_path(path: str, source: str, target: str) -> str:
    """在路径表达式中替换线段名，同时兼容反向线段。"""
    if source in path:
        return path.replace(source, target, 1)
    reversed_source = source[::-1]
    if reversed_source in path:
        return path.replace(reversed_source, target[::-1], 1)
    raise method_precondition_failed(
        "path does not contain the segment selected for replacement",
        arg_name="path",
        role="path_expression",
        expected={"contains_segment": source},
        observed={"path": path},
    )


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
        raise method_precondition_failed(
            "segments must share exactly one endpoint",
            role="adjacent_segments",
            expected={"shared_endpoint_count": 1},
            observed={
                "segments": [segment1, segment2],
                "shared_endpoint_count": len(common),
            },
        )
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
    normalized = quadrant.strip().lower()
    if normalized in ("第一象限", "1", "i", "first"):
        return (True, True)
    if normalized in ("第二象限", "2", "ii", "second"):
        return (False, True)
    if normalized in ("第三象限", "3", "iii", "third"):
        return (False, False)
    if normalized in ("第四象限", "4", "iv", "fourth"):
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
