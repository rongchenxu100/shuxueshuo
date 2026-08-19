"""quadratic_from_constraints 无状态 method。

本文件同时保存该 method 的实现与 SPEC；生成的 MethodSpec JSON 只是
从这里派生出的资产，不作为事实源。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Literal, Mapping

from shuxueshuo_server.solver.contracts import (
    MethodExplanationSpec,
    MethodInputRelationSpec,
    MethodOutputActivationSpec,
    ScalarResultFormSpec,
    SymbolicClosureSpec,
)
from shuxueshuo_server.solver.runtime.quadratic_constraint_solver import (
    QuadraticConstraintSolveRequest,
    QuadraticConstraintSolveResult,
    solve_quadratic_constraint_system,
)
from shuxueshuo_server.solver.runtime.symbolic_state_representation import (
    SymbolicStateRepresentationError,
)

from ._common import *
from ._spec import MethodSpecSource, declare_input_views


QuadraticConstraintStatus = Literal[
    "determined",
    "single_free",
    "underdetermined",
    "ambiguous",
    "inconsistent",
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
        coefficient_template=inputs.get("quadratic_template"),
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
    if result.status == "inconsistent":
        return QuadraticConstraintAnalysis("inconsistent", branch_count=0)
    if result.status == "ambiguous":
        return QuadraticConstraintAnalysis(
            "ambiguous",
            branch_count=result.branch_count,
        )
    analyzer_free = tuple(
        symbol
        for symbol in result.free_symbols
        if symbol in set(coefficients) or symbol in set(preferred_free_parameters)
    )
    if not analyzer_free:
        return QuadraticConstraintAnalysis("determined", branch_count=1)
    return QuadraticConstraintAnalysis(
        "single_free" if len(analyzer_free) == 1 else "underdetermined",
        free_parameters=analyzer_free,
        branch_count=result.branch_count,
    )


def equivalent_quadratic_free_parameter_bases(
    inputs: dict[str, Any],
) -> tuple[tuple[sp.Symbol, ...], ...]:
    """Enumerate every exact free-symbol basis accepted by the same constraints.

    The solver's elimination order may represent a one-dimensional state using
    ``b`` or ``c``.  That order is an implementation choice, not mathematical
    evidence that one symbol is the unique valid basis.  Candidate bases are
    therefore verified by rerunning the shared solver with each finite basis.
    """

    x = inputs["x"]
    known = set(dict(inputs.get("known_coefficients", {})))
    substitutions = set(_parameter_substitution(inputs))
    candidates = tuple(
        sorted(
            (
                _input_free_symbols(inputs)
                - {x}
                - known
                - substitutions
            ),
            key=lambda symbol: symbol.name,
        )
    )
    for dimension in range(1, len(candidates) + 1):
        bases: list[tuple[sp.Symbol, ...]] = []
        for basis in combinations(candidates, dimension):
            try:
                analysis = analyze_quadratic_constraints(
                    inputs,
                    preferred_free_parameters=tuple(basis),
                )
            except SymbolicStateRepresentationError:
                continue
            if (
                analysis.status in {"single_free", "underdetermined"}
                and set(analysis.free_parameters) == set(basis)
            ):
                bases.append(tuple(basis))
        if bases:
            return tuple(bases)
    return ()


def _input_free_symbols(value: Any) -> set[sp.Symbol]:
    if isinstance(value, Mapping):
        return {
            symbol
            for key, item in value.items()
            for symbol in (
                *_input_free_symbols(key),
                *_input_free_symbols(item),
            )
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return {
            symbol for item in value for symbol in _input_free_symbols(item)
        }
    try:
        return set(sp.sympify(value).free_symbols)
    except (TypeError, ValueError, AttributeError):
        return set()


class QuadraticFromConstraintsMethod:
    """由二次函数约束求当前问需要的最简抛物线。

    这个 method 合并了此前三类近似方法：

    - 只由已知系数和系数关系补齐抛物线；
    - 由点在抛物线上和系数关系求通式；
    - 由已知系数和一个曲线点求含参抛物线；
    - 只代入部分已知系数，得到仍含自由系数的当前问抛物线。

    ``free_parameter/free_parameters`` 是 typed Symbol authority，而不是可由编译器
    改名的表达式变量。当前状态若采用等价的另一组系数表示，shared solver 只有在
    能证明唯一换基时才投影到指定 Symbol；不能证明时直接失败，不会偷换参数身份。

    Functional 编译可以把任意数量的 Point ContextPath 聚合为 ``curve_points``。
    ``curve_point/p1/p2`` 仅保留给历史 binding rule 兼容路径，method
    内部会把两种输入统一组装成约束方程。
    ``free_parameter/free_parameters`` 表示本步骤结果的一组完整独立参数基底。
    开放状态必须显式声明非空基底；闭合状态可传 ``[]`` 或省略。若约束证明
    ``b`` 与 ``c`` 是同一一维状态的等价表示，任一单元素基底都可接受；Method
    不按下游Goal偏好猜测或收窄基底。
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
                coefficient_template=inputs.get("quadratic_template"),
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
            raise StatelessMethodError(
                "planner.method_contract_invalid",
                "quadratic solver reported success without a parabola result",
                category="configuration",
                retryability="configuration",
                arg_name="quadratic",
                role="quadratic_state",
                expected={"type": "Parabola", "state": "materialized"},
                observed={"type": "None", "solver_status": result.status},
                repair_action="fix_runtime_contract",
            )
        values = {
            **known,
            **{
                symbol: value
                for symbol, value in result.coefficient_substitution.items()
                if symbol in coefficients
            },
        }
        if target_parameter is not None and result.target_value is not None:
            values[target_parameter] = sp.simplify(result.target_value)
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
        raise method_result_inconsistent(
            "function.constraints_inconsistent: quadratic constraints conflict",
            arg_name="quadratic",
            role="quadratic_constraint_system",
            expected={"state": "consistent"},
            observed={"state": "inconsistent", "branch_count": result.branch_count},
            retryability="planner_repairable",
            repair_action="revise_quadratic_constraints",
        )
    if result.status == "ambiguous":
        raise method_result_ambiguous(
            "function.constraints_ambiguous: "
            f"branch_count={result.branch_count}; "
            "二次函数约束不能唯一确定缺失系数",
            arg_name="quadratic",
            role="quadratic_constraint_system",
            expected={"state": "unique_solution"},
            observed={"state": "ambiguous", "candidate_count": result.branch_count},
            repair_action="provide_additional_quadratic_constraint",
        )
    if target_parameter is not None and result.target_value is not None:
        unexpected_target_dependencies = (
            set(sp.sympify(result.target_value).free_symbols)
            - explicit_free_symbols
        )
        if unexpected_target_dependencies:
            names = ", ".join(
                sorted(
                    symbol.name
                    for symbol in unexpected_target_dependencies
                )
            )
            raise method_input_state_unavailable(
                "function.constraints_underdetermined: "
                f"target={target_parameter.name}, "
                f"undeclared_dependencies={names}; "
                "target parameter depends on undeclared free symbols",
                arg_name="target_parameter",
                role="coefficient_target",
                internal_ref=target_parameter,
                expected={"type": "Symbol", "state": "dependencies_declared"},
                observed={
                    "state": "undeclared_dependencies",
                    "symbols": names,
                },
                repair_action="declare_visible_free_parameters",
            )
    if target_parameter is not None and result.target_value is None:
        equation_symbols = {
            symbol
            for equation in result.equations
            for symbol in sp.expand(equation.lhs - equation.rhs).free_symbols
        }
        if target_parameter not in equation_symbols:
            names = ", ".join(
                sorted(symbol.name for symbol in equation_symbols)
            ) or "<none>"
            raise method_input_missing(
                "function.target_parameter_not_constrained: "
                f"target={target_parameter.name}, constraint_symbols={names}; "
                "the supplied curve points and equations do not constrain the target parameter",
                arg_name="target_parameter",
                role="coefficient_target",
                internal_ref=target_parameter,
                expected={"type": "Symbol", "state": "constrained"},
                observed={"state": "unconstrained", "constraint_symbols": names},
                repair_action="provide_additional_quadratic_constraint",
            )
    actual_free_symbols = set(result.free_symbols)
    if explicit_free_symbols and actual_free_symbols != explicit_free_symbols:
        actual = ",".join(
            sorted(symbol.name for symbol in actual_free_symbols)
        ) or "none"
        declared = ",".join(
            sorted(symbol.name for symbol in explicit_free_symbols)
        ) or "none"
        raise method_input_state_unavailable(
            "function.state_representation_mismatch: "
            f"declared={declared}, actual={actual}",
            arg_name="free_parameters",
            role="free_coefficient_state",
            expected={"type": "SymbolList", "state": "declared", "symbols": declared},
            observed={"type": "SymbolList", "state": "derived", "symbols": actual},
            repair_action="align_free_parameter_state",
        )
    unresolved = (
        set(result.free_symbols) & coefficient_symbols
    ) - explicit_free_symbols
    if unresolved:
        names = ", ".join(sorted(symbol.name for symbol in unresolved))
        raise method_input_missing(
            "function.constraints_underdetermined: "
            f"residual_symbols={names}; 约束不足以确定系数: {names}",
            arg_name="quadratic",
            role="quadratic_constraint_system",
            expected={"state": "closed_or_explicitly_parameterized"},
            observed={"state": "underdetermined", "residual_symbols": names},
            repair_action="provide_additional_quadratic_constraint",
        )
    if target_parameter is not None and result.target_value is None:
        names = ", ".join(symbol.name for symbol in result.free_symbols) or "<none>"
        raise method_result_empty(
            "function.constraints_underdetermined: "
            f"target={target_parameter.name}, residual_symbols={names}; "
            "target parameter was not solved from the supplied quadratic constraints",
            arg_name="target_parameter",
            role="coefficient_target",
            internal_ref=target_parameter,
            expected={"type": "ParameterValue", "state": "materialized"},
            observed={"state": "unsolved", "residual_symbols": names},
            repair_action="provide_additional_quadratic_constraint",
        )


def _parameter_substitution(inputs: dict[str, Any]) -> dict[sp.Symbol, sp.Expr]:
    """Validate and normalize one explicitly authored parameter substitution."""
    return _optional_parameter_substitution(
        inputs,
        inputs.get("quadratic"),
        inputs.get("quadratic_template"),
        inputs.get("known_coefficients"),
        inputs.get("coefficient_relation"),
        inputs.get("extra_equation"),
        inputs.get("curve_point"),
        inputs.get("curve_points"),
        inputs.get("p1"),
        inputs.get("p2"),
        allow_closed_noop=True,
    )


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
        "根据当前scope中由编译器注入的唯一题面二次函数身份与可见状态，联立本步骤"
        "新增的已知系数、系数关系、曲线点、等式或参数值，输出最简系数与抛物线。"
        "Plan只填写catalog公开的约束参数；quadratic、parabola、x和all_coefficients"
        "均由编译器确定，不得自行放入args。指定target_parameter时还可输出该系数"
        "关于free_parameters的开放或闭合状态。使用原则：多个已知系数应一次放入 "
        "known_coefficients；单个运行参数代入才使用parameter_value；"
        "free_parameters必须给出应用本步骤当前scope约束后的一组完整独立参数"
        "基底：开放状态必填非空，闭合状态可填[]或省略。"
    ),
    do_not_use_when=(
        "当前目标所需的同一抛物线状态已经由前序调用完整确定，无需用相同约束重复求解。",
        (
            "不能根据下游Goal希望求哪个参数来选择或缩减free_parameters；它必须是"
            "当前scope约束后完整的独立基底。runtime可证明等价的基底均合法。"
        ),
        (
            "要求 closed_state 时，不能遗漏当前抛物线仍含自由符号对应的 "
            "parameter_value；代码只会在 Symbol 身份唯一时确定性补全。"
        ),
        "不要把参数范围或不等式放入 extra_equation；它只接受用于求系数的等式。",
        "不要把同一个 Symbol 同时声明为 free_parameters 和 target_parameter。",
        (
            "题面 Function 模板已有多个已知系数时，不要逐个调用 "
            "evaluate_expression_at_parameter；使用 known_coefficients 一次建立"
            "当前 Parabola 状态。"
        ),
        (
            "目标只是把已求出的参数值代回同一题面抛物线时，继续使用该Function的"
            "SourceRef；编译器会读取当前scope最近可见的Parabola状态和参数值。不要"
            "用StepResultRef指定具名Function的普通状态，也不要再次建立抛物线。"
        ),
        (
            "不要添加quadratic、parabola、x或all_coefficients参数；这些内部输入由"
            "编译器从当前scope的题面权威中注入，且不属于公开args。"
        ),
        (
            "新增曲线点或方程代入后成为恒等式，或只约束其他符号，却仍指定一个"
            "未出现在这些约束中的 target_parameter；该能力不能凭目标名称反求系数。"
        ),
    ),
    description=(
        "由编译器选择当前scope的题面二次函数身份与可见状态，Plan只提交当前scope"
        "新增的已知系数、曲线点、系数关系和额外方程，求该scope约束下的最简抛物线。"
        "应用本步骤当前scope约束后，free_parameters必须给出仍未确定状态的一组"
        "完整独立参数基底；开放状态必须非空，闭合状态允许[]或省略。runtime可证明"
        "等价的基底均可使用，但不能根据下游Goal提前收窄。兄弟scope使用不同局部"
        "条件时，应在各自scope分别生成状态。"
    ),
    solves=("derive_quadratic_from_constraints",),
    inputs={
        "quadratic": {"type": "Expression", "required": True},
        "quadratic_template": {
            "type": "Expression",
            "required": False,
            "functional_exposed": False,
        },
        "x": {"type": "Symbol", "required": True},
        "all_coefficients": {"type": "SymbolList", "required": True},
        "known_coefficients": {
            "type": "Coefficients",
            "required": False,
            "description": (
                "当前scope可见的零个或多个 symbol_value Fact；每个Fact提供一个"
                "已知二次函数系数值。"
            ),
        },
        "coefficient_relation": {"type": "Equation", "required": False},
        "extra_equation": {"type": "Equation", "required": False},
        "curve_point": {"type": "Point", "required": False},
        "curve_points": {
            "type": "PointList",
            "required": False,
            "object_kind": "point",
            "state_kind": "coordinate",
        },
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
        "free_parameters": {
            "type": "SymbolList",
            "required": False,
            "allows_empty_collection": True,
            "role": (
                "应用本步骤当前scope可见约束后仍未确定的一组完整独立参数基底。"
                "开放状态必须填写非空基底；闭合状态可填写[]或省略。代码接受"
                "runtime证明等价的基底，但不得按下游Goal目标人为收窄"
            ),
        },
        "parameter": {"type": "Symbol", "required": False},
        "parameter_value": {"type": "ParameterValue", "required": False},
        "target_parameter": {
            "type": "Symbol",
            "required": False,
            "role": (
                "本轮希望明确求出的二次函数系数；只有提供它，"
                "parameter_value return 才具有确定的 Symbol 身份"
            ),
        },
    },
    input_views=declare_input_views(
        identity=("x", "free_parameter", "parameter", "target_parameter"),
        latest_state=(
            "quadratic",
            "curve_point",
            "curve_points",
            "p1",
            "p2",
            "parameter_value",
        ),
        immutable_value=(
            "quadratic_template",
            "all_coefficients",
            "known_coefficients",
            "coefficient_relation",
            "extra_equation",
            "free_parameters",
        ),
    ),
    input_relations=(
        MethodInputRelationSpec(
            relation_kind="point_on_curve",
            point_arg="curve_point",
            curve_arg="quadratic",
            cardinality="one",
            accepted_condition_kinds=(
                "point_on_curve",
                "point_on_curve_with_x_coordinate",
            ),
        ),
        MethodInputRelationSpec(
            relation_kind="point_on_curve",
            point_arg="curve_points",
            curve_arg="quadratic",
            cardinality="for_each",
            accepted_condition_kinds=(
                "point_on_curve",
                "point_on_curve_with_x_coordinate",
            ),
        ),
    ),
    outputs={
        "coefficients": "Coefficients",
        "parabola": "Parabola",
        "parameter_value": "ParameterValue",
    },
    output_activation={
        "parameter_value": MethodOutputActivationSpec(
            kind="requires_inputs",
            required_inputs=("target_parameter",),
        ),
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
        (
            "开放状态的free_parameter/free_parameters必须给出应用当前scope可见"
            "约束后的完整独立基底；闭合状态允许[]或省略"
        ),
        (
            "局部条件属于子scope或兄弟scope时，状态producer必须位于对应局部scope，"
            "不能仅因共享同一抛物线身份而提升到祖先"
        ),
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
    symbolic_closure=SymbolicClosureSpec(
        target_arg="target_parameter",
        equation_builder="quadratic_constraints",
        representation_mapper="polynomial_coefficient_template",
        known_substitutions=(("parameter", "parameter_value"),),
        known_mapping_args=("known_coefficients",),
        preserved_symbol_args=("free_parameter", "free_parameters"),
        substitution_outputs=(
            "coefficients",
            "parabola",
            "parameter_value",
        ),
        output_validator="quadratic_closure_outputs",
    ),
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
