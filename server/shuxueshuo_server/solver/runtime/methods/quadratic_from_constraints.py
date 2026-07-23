"""quadratic_from_constraints 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
    ScalarResultFormSpec,
)
from shuxueshuo_server.solver.runtime.quadratic_constraint_solver import (
    QuadraticConstraintSolveRequest,
    QuadraticConstraintSolveResult,
    solve_quadratic_constraint_system,
)

from ._common import *
from ._spec import MethodSpecSource


QuadraticConstraintStatus = Literal[
    "determined",
    "single_free",
    "underdetermined",
    "ambiguous",
]


@dataclass(frozen=True)
class QuadraticConstraintAnalysis:
    """Deterministic coefficient-solution shape shared by adapter and runtime."""

    status: QuadraticConstraintStatus
    free_parameters: tuple[sp.Symbol, ...] = ()
    branch_count: int = 0


def analyze_quadratic_constraints(
    inputs: dict[str, Any],
    *,
    preferred_free_parameters: tuple[sp.Symbol, ...] = (),
) -> QuadraticConstraintAnalysis:
    """Project the shared solver result into adapter applicability metadata."""
    quadratic = inputs["quadratic"]
    x = inputs["x"]
    coefficients = tuple(inputs["all_coefficients"])
    known = dict(inputs.get("known_coefficients", {}))
    substitution = _parameter_substitution(inputs)
    request = QuadraticConstraintSolveRequest(
        base_expression=quadratic,
        independent_symbol=x,
        coefficient_symbols=coefficients,
        known_coefficients=known,
        curve_points=tuple(_collect_curve_points(inputs, substitution)),
        equations=tuple(
            _collect_extra_equations(inputs, known, substitution)
        ),
        parameter_substitutions=substitution,
        preserve_symbols=preferred_free_parameters,
    )
    result = solve_quadratic_constraint_system(
        request,
        kernel=SympyKernel(),
    )
    active_preferred = preferred_free_parameters
    if preferred_free_parameters and not _preserved_basis_is_valid(
        result,
        preferred=preferred_free_parameters,
        coefficient_symbols=coefficients,
    ):
        result = solve_quadratic_constraint_system(
            replace(request, preserve_symbols=()),
            kernel=SympyKernel(),
        )
        active_preferred = ()
    if result.status == "inconsistent":
        return QuadraticConstraintAnalysis("ambiguous", branch_count=0)
    if result.status == "ambiguous":
        return QuadraticConstraintAnalysis(
            "ambiguous",
            branch_count=result.branch_count,
        )
    analyzer_free = tuple(
        symbol
        for symbol in result.free_symbols
        if symbol in set(coefficients) or symbol in set(active_preferred)
    )
    if not analyzer_free:
        return QuadraticConstraintAnalysis("determined", branch_count=1)
    return QuadraticConstraintAnalysis(
        "single_free" if len(analyzer_free) == 1 else "underdetermined",
        free_parameters=analyzer_free,
        branch_count=result.branch_count,
    )


def _preserved_basis_is_valid(
    result: QuadraticConstraintSolveResult,
    *,
    preferred: tuple[sp.Symbol, ...],
    coefficient_symbols: tuple[sp.Symbol, ...],
) -> bool:
    if result.status in {"ambiguous", "inconsistent"}:
        return False
    free = set(result.free_symbols)
    preferred_set = set(preferred)
    if not preferred_set.issubset(free):
        return False
    return not ((free & set(coefficient_symbols)) - preferred_set)


class QuadraticFromConstraintsMethod:
    """由二次函数约束求当前问需要的最简抛物线。

    这个 method 合并了此前三类近似方法：

    - 只由已知系数和系数关系补齐抛物线；
    - 由点在抛物线上和系数关系求通式；
    - 由已知系数和一个曲线点求含参抛物线；
    - 只代入部分已知系数，得到仍含自由系数的当前问抛物线。

    作为“化简函数表达式”的 method，它的使用原则是：只有当代入约束后能明显降低
    当前问表达式复杂度时才值得单独调用。理想化简结果是二次函数系数 ``a,b,c``
    只剩一个未知参数，或已经完全确定；如果化简后仍有多个等价自由参数，Planner
    应结合后续题面条件选择最有用的参数方向，而不是随意缓存一组含参系数。
    例如 ``b``、``c`` 都能作为自由参数时，优先保留后续长度、最值、曲线点或答案
    目标会直接求解/引用的那个参数；无法从上下文唯一判断时，应推迟到更多约束出现。

    V1.5 的 MethodInvocation 只能传 ContextPath，暂时不能直接构造“任意长度 facts
    列表”，所以输入仍保留 ``curve_point/p1/p2`` 这几个固定槽位；method 内部会把
    它们统一组装成约束方程。``free_parameter/free_parameters`` 表示本步骤允许保留
    的自由系数，例如先把 ``a=2`` 代入，保留 ``b,c``，供后续曲线点和联立方程
    继续约束。后续有 ContextValue 构造器后，可以收敛成真正的
    ``curve_points`` / ``extra_equations`` / ``free_symbols`` 列表输入。
    """

    method_id = "quadratic_from_constraints"

    def run(self, inputs: dict[str, Any], kernel: SympyKernel) -> StatelessMethodResult:
        quadratic = inputs["quadratic"]
        x = inputs["x"]
        coefficients = list(inputs["all_coefficients"])
        known = dict(inputs.get("known_coefficients", {}))
        free_symbols = _collect_free_symbols(inputs)
        substitution = _parameter_substitution(inputs)

        points = _collect_curve_points(inputs, substitution)
        equations = _collect_extra_equations(inputs, known, substitution)
        target_parameter = inputs.get("target_parameter")
        result = solve_quadratic_constraint_system(
            QuadraticConstraintSolveRequest(
                base_expression=quadratic,
                independent_symbol=x,
                coefficient_symbols=tuple(coefficients),
                known_coefficients=known,
                curve_points=tuple(points),
                equations=tuple(equations),
                parameter_substitutions=substitution,
                preserve_symbols=tuple(
                    sorted(free_symbols, key=lambda symbol: symbol.name)
                ),
                target_symbol=target_parameter,
            ),
            kernel=kernel,
        )
        _raise_constraint_failure(
            result,
            explicit_free_symbols=free_symbols,
            coefficient_symbols=set(coefficients),
            target_parameter=target_parameter,
        )
        if result.parabola is None:
            raise ValueError(
                "function.constraints_inconsistent: quadratic state was not produced"
            )
        values = {
            **known,
            **{
                symbol: value
                for symbol, value in result.coefficient_substitution.items()
                if symbol in coefficients
            },
        }
        parabola = result.parabola
        checks = _build_checks(
            kernel,
            parabola,
            x,
            points,
            list(result.equations),
            values,
            known,
        )
        calculation = ", ".join(
            f"{symbol.name}={kernel.sstr(value)}"
            for symbol, value in values.items()
        )
        outputs = {
            "coefficients": TypedValue("Coefficients", values, source=self.method_id),
            "parabola": TypedValue("Parabola", parabola, source=self.method_id),
        }
        if target_parameter is not None and result.target_value is not None:
            outputs["parameter_value"] = TypedValue(
                "ParameterValue",
                result.target_value,
                source=self.method_id,
            )
        return StatelessMethodResult(
            method_id=self.method_id,
            outputs=outputs,
            checks=checks,
            trace_fragments=[
                _step(
                    self.method_id,
                    "由约束求抛物线",
                    "确定当前问的二次函数系数",
                    _reason_text(points, equations, known),
                    calculation,
                    f"y={kernel.sstr(parabola)}",
                )
            ],
        )


def _raise_constraint_failure(
    result: QuadraticConstraintSolveResult,
    *,
    explicit_free_symbols: set[sp.Symbol],
    coefficient_symbols: set[sp.Symbol],
    target_parameter: sp.Symbol | None,
) -> None:
    if result.status == "inconsistent":
        raise ValueError(
            "function.constraints_inconsistent: quadratic constraints conflict"
        )
    if result.status == "ambiguous":
        raise ValueError(
            "function.constraints_ambiguous: "
            f"branch_count={result.branch_count}; 二次函数约束不能唯一确定缺失系数"
        )
    unresolved = (
        set(result.free_symbols) & coefficient_symbols
    ) - explicit_free_symbols
    if unresolved:
        names = ", ".join(sorted(symbol.name for symbol in unresolved))
        raise ValueError(
            "function.constraints_underdetermined: "
            f"residual_symbols={names}; 约束不足以确定系数: {names}"
        )
    if target_parameter is not None and result.target_value is None:
        names = ", ".join(symbol.name for symbol in result.free_symbols) or "<none>"
        raise ValueError(
            "function.constraints_underdetermined: "
            f"target={target_parameter.name}, residual_symbols={names}"
        )


def _parameter_substitution(inputs: dict[str, Any]) -> dict[sp.Symbol, sp.Expr]:
    """把可选参数值整理成统一 substitutions。"""
    parameter = inputs.get("parameter")
    parameter_value = inputs.get("parameter_value")
    if parameter is None or parameter_value is None:
        return {}
    return {parameter: parameter_value}


def _collect_free_symbols(inputs: dict[str, Any]) -> set[sp.Symbol]:
    """收集本步骤允许保留的自由系数。

    单个 ``free_parameter`` 用于“求出关于 b 的含参抛物线”这类旧场景；
    ``free_parameters`` 则用于“先代入 a=2，保留 b、c”这类多自由系数场景。
    """
    free_symbols: set[sp.Symbol] = set()
    free_parameter = inputs.get("free_parameter")
    if free_parameter is not None:
        free_symbols.add(free_parameter)
    free_parameters = inputs.get("free_parameters")
    if free_parameters is not None:
        free_symbols.update(free_parameters)
    return free_symbols


def _collect_curve_points(
    inputs: dict[str, Any],
    substitution: dict[sp.Symbol, sp.Expr],
) -> list[Point]:
    """收集可选曲线点，并统一代入已知参数。"""
    points: list[Point] = []
    if "curve_points" in inputs:
        points.extend(inputs["curve_points"])
    for name in ("curve_point", "p1", "p2"):
        if name in inputs:
            points.append(inputs[name])
    if substitution:
        return [_subs_point(point, substitution) for point in points]
    return points


def _collect_extra_equations(
    inputs: dict[str, Any],
    known: dict[sp.Symbol, sp.Expr],
    substitution: dict[sp.Symbol, sp.Expr],
) -> list[Any]:
    """收集可选额外方程，例如系数关系。"""
    equations: list[sp.Equality] = []
    relation = inputs.get("coefficient_relation")
    if relation is not None:
        equations.append(relation)
    extra_equation = inputs.get("extra_equation")
    if extra_equation is not None:
        equations.append(extra_equation)
    return [
        sp.Eq(
            sp.simplify(equation.lhs.subs(known).subs(substitution)),
            sp.simplify(equation.rhs.subs(known).subs(substitution)),
        )
        for equation in equations
    ]


def _normalize_constraint_equations(
    equations: list[Any],
) -> tuple[list[sp.Equality], bool]:
    """Remove tautologies and surface contradictions before solve/check.

    SymPy eagerly reduces ``Eq(expr, expr)`` to ``BooleanTrue`` and impossible
    equalities to ``BooleanFalse``. Neither value has ``lhs``/``rhs`` and they
    are not runtime equations; treating them here keeps analyzer and execution
    on the same deterministic constraint set.
    """

    normalized: list[sp.Equality] = []
    for equation in equations:
        if equation is sp.S.true:
            continue
        if equation is sp.S.false:
            return normalized, True
        normalized.append(equation)
    return normalized, False


def _build_checks(
    kernel: SympyKernel,
    parabola: sp.Expr,
    x: sp.Symbol,
    points: list[Point],
    equations: list[sp.Equality],
    values: dict[sp.Symbol, sp.Expr],
    known: dict[sp.Symbol, sp.Expr],
) -> list[CheckResult]:
    """为统一约束求解结果生成验算 checks。"""
    checks = [
        _check(
            "known_coefficients_preserved",
            all(
                symbol in values
                and sp.simplify(values[symbol] - value) == 0
                for symbol, value in known.items()
            ),
            "已知系数被保留",
        )
    ]
    for index, equation in enumerate(equations):
        checks.append(
            _check(
                f"extra_equation_{index}_satisfied",
                sp.simplify(equation.lhs.subs(values) - equation.rhs.subs(values)) == 0,
                "额外方程约束成立",
            )
        )
    for index, point in enumerate(points):
        checks.append(
            _check(
                f"curve_point_{index}_on_parabola",
                kernel.point_on_curve(point, parabola, x),
                "曲线点满足求得的抛物线",
            )
        )
    return checks


def _reason_text(
    points: list[Point],
    equations: list[sp.Equality],
    known: dict[sp.Symbol, sp.Expr],
) -> str:
    """根据输入约束生成 trace 的理由文本。"""
    pieces = []
    if known:
        pieces.append("代入已知系数")
    if points:
        pieces.append("把曲线点代入抛物线")
    if equations:
        pieces.append("联立额外系数方程")
    return "；".join(pieces) + "。" if pieces else "直接整理二次函数约束。"


SPEC = MethodSpecSource(
    method_cls=QuadraticFromConstraintsMethod,
    title="由二次函数约束求抛物线",
    summary=(
        "从题面函数模板建立抛物线，或在当前同一抛物线状态上追加已知系数、"
        "系数关系、曲线点和参数值；输出当前约束下最简的系数与抛物线。指定 "
        "target_parameter 时还可输出该系数关于 free_parameters 的开放或闭合状态。"
        "使用原则：建立曲线和继续追加约束都使用这一能力；多个已知系数使用 "
        "known_coefficients，单个运行参数代入才使用 parameter_value。"
    ),
    do_not_use_when=(
        "当前目标所需的同一抛物线状态已经由前序调用完整确定，无需用相同约束重复求解。",
        "现有约束仍有多个自由参数，且无法唯一选择一个会被后续条件或答案目标消费的参数。",
        "不要把参数范围或不等式放入 extra_equation；它只接受用于求系数的等式。",
        "不要把同一个 Symbol 同时声明为 free_parameters 和 target_parameter。",
    ),
    description=(
        "由题面模板建立，或继续化简当前同一对象的抛物线状态。通过已知系数、"
        "曲线点、系数关系和额外方程求当前问需要的最简抛物线。"
        "它适合在代入后能把 a,b,c 完全确定，或至少化简到只剩一个上下文有用的"
        "未知参数时使用；若 b、c 等多个参数都可作为自由参数，应结合后续长度、"
        "最值、曲线点或答案目标选择保留哪个参数，无法判断时应等待更多约束。"
    ),
    solves=("derive_quadratic_from_constraints",),
    inputs={
        "quadratic": {"type": "Expression", "required": True},
        "x": {"type": "Symbol", "required": True},
        "all_coefficients": {"type": "SymbolList", "required": True},
        "known_coefficients": {"type": "Coefficients", "required": False},
        "coefficient_relation": {"type": "Equation", "required": False},
        "extra_equation": {"type": "Equation", "required": False},
        "curve_point": {"type": "Point", "required": False},
        "curve_points": {"type": "PointList", "required": False},
        "p1": {
            "type": "Point",
            "required": False,
            "functional_exposed": False,
        },
        "p2": {
            "type": "Point",
            "required": False,
            "functional_exposed": False,
        },
        "free_parameter": {"type": "Symbol", "required": False},
        "free_parameters": {"type": "SymbolList", "required": False},
        "parameter": {"type": "Symbol", "required": False},
        "parameter_value": {"type": "ParameterValue", "required": False},
        "target_parameter": {
            "type": "Symbol",
            "required": False,
            "role": "本轮希望明确求出的二次函数系数",
        },
    },
    outputs={
        "coefficients": "Coefficients",
        "parabola": "Parabola",
        "parameter_value": "ParameterValue",
    },
    scalar_result_forms={
        "parameter_value": ScalarResultFormSpec(
            possible_forms=("open_state", "closed_state"),
            description=(
                "目标系数仍依赖明确保留的参数时为 open_state；不存在自由符号时为 "
                "closed_state。"
            ),
        ),
    },
    preconditions=(
        "输入约束必须能唯一确定除 free_parameter/free_parameters 外的缺失系数",
        "若作为独立化简步骤，化简后应完全确定系数，或只保留一个由后续条件/目标明确需要的自由参数",
        "当多个自由参数都可表达同一函数时，应由 Planner 结合后续条件选择参数；不能唯一判断时不要提前缓存含参系数",
    ),
    postconditions=(
        "输出抛物线满足已知系数、曲线点和额外方程约束",
        "输出 coefficients/parabola 表示当前问已知约束下的最简函数表达式",
    ),
    distinct_arg_groups=(
        ("free_parameter", "target_parameter"),
        ("free_parameters", "target_parameter"),
    ),
    constraint_analyzer="quadratic_coefficients",
    explanation=MethodExplanationSpec(
        role_schema={
            "constraints": "用于确定当前问二次函数的系数约束。",
            "result_parabola": "由约束得到的当前问抛物线解析式。",
            "parabola_title_action": "标题动词；完全确定时为求，含后续参数时为化简。",
            "completed_square_suffix": "配方形式补充说明；没有配方形式时为空。",
        },
        student_goal_template="代入当前问给出的约束，确定二次函数解析式。",
        student_title_template="{parabola_title_action}函数解析式",
        student_nav_title_template="{parabola_title_action}解析式",
        derive_templates=(
            "∵{constraints}",
            "∴y＝{result_parabola}{completed_square_suffix}",
        ),
        box_templates=("y＝{result_parabola}",),
        role_binder_id="quadratic_from_constraints",
    ),
)
