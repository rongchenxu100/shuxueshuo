"""Shared deterministic solver for refining quadratic-function state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import sympy as sp

from shuxueshuo_server.solver.contracts import Point
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.symbolic_target_closure import (
    solve_target_symbol_closure,
)


QuadraticConstraintStatus = Literal[
    "determined",
    "single_free",
    "underdetermined",
    "ambiguous",
    "inconsistent",
]


@dataclass(frozen=True)
class QuadraticConstraintSolveRequest:
    """One quadratic constraint system, independent of planner representation."""

    base_expression: sp.Expr
    independent_symbol: sp.Symbol
    coefficient_symbols: tuple[sp.Symbol, ...]
    known_coefficients: dict[sp.Symbol, sp.Expr] = field(default_factory=dict)
    curve_points: tuple[Point, ...] = ()
    equations: tuple[sp.Equality, ...] = ()
    parameter_substitutions: dict[sp.Symbol, sp.Expr] = field(default_factory=dict)
    preserve_symbols: tuple[sp.Symbol, ...] = ()
    target_symbol: sp.Symbol | None = None
    target_expression: sp.Expr | None = None
    parameter_constraint: dict[str, sp.Expr | str] | None = None


@dataclass(frozen=True)
class QuadraticConstraintSolveResult:
    status: QuadraticConstraintStatus
    coefficient_substitution: dict[sp.Symbol, sp.Expr] = field(default_factory=dict)
    parabola: sp.Expr | None = None
    free_symbols: tuple[sp.Symbol, ...] = ()
    target_value: sp.Expr | None = None
    dependency_symbols: tuple[sp.Symbol, ...] = ()
    branch_count: int = 0
    equations: tuple[sp.Equality, ...] = ()


def solve_quadratic_constraint_system(
    request: QuadraticConstraintSolveRequest,
    *,
    kernel: SympyKernel,
) -> QuadraticConstraintSolveResult:
    """Solve or refine a quadratic while preserving an explicit free basis."""
    substitutions = {
        **_substitute_mapping_values(
            _materialized_coefficient_substitutions(request),
            request.parameter_substitutions,
        ),
        **_substitute_mapping_values(
            request.known_coefficients,
            request.parameter_substitutions,
        ),
        **request.parameter_substitutions,
    }
    expression = sp.expand(request.base_expression.subs(substitutions))
    points = tuple(
        (
            sp.simplify(sp.sympify(point[0]).subs(request.parameter_substitutions)),
            sp.simplify(sp.sympify(point[1]).subs(request.parameter_substitutions)),
        )
        for point in request.curve_points
    )
    equations = [
        _substitute_equation(equation, substitutions)
        for equation in request.equations
    ]
    equations.extend(
        sp.Eq(expression.subs(request.independent_symbol, point[0]), point[1])
        for point in points
    )
    normalized, contradictory = _normalize_equations(equations)
    if contradictory:
        return QuadraticConstraintSolveResult(
            "inconsistent",
            equations=tuple(normalized),
        )

    preserve = tuple(dict.fromkeys(request.preserve_symbols))
    if request.target_symbol is not None and request.target_symbol in preserve:
        return QuadraticConstraintSolveResult(
            "underdetermined",
            free_symbols=preserve,
            equations=tuple(normalized),
        )

    # A target supplied by known coefficients or a ParameterValue is already
    # closed.  Continue solving the remaining coefficient system instead of
    # asking target closure to recover a Symbol that substitutions removed
    # from every equation.
    if (
        request.target_symbol is not None
        and request.target_symbol not in substitutions
    ):
        targeted = _solve_target(
            request,
            expression=expression,
            equations=normalized,
            substitutions=substitutions,
            kernel=kernel,
        )
        if targeted is not None:
            return targeted

    unknowns = tuple(
        symbol
        for symbol in request.coefficient_symbols
        if symbol not in substitutions and symbol not in preserve
    )
    if unknowns:
        if not normalized:
            free_symbols = tuple(dict.fromkeys((*unknowns, *preserve)))
            return QuadraticConstraintSolveResult(
                "single_free" if len(free_symbols) == 1 else "underdetermined",
                coefficient_substitution=dict(substitutions),
                parabola=expression,
                free_symbols=free_symbols,
                equations=tuple(normalized),
            )
        branches = sp.solve(normalized, unknowns, dict=True)
        if not branches:
            return QuadraticConstraintSolveResult(
                "inconsistent",
                equations=tuple(normalized),
            )
        if len(branches) != 1:
            return QuadraticConstraintSolveResult(
                "ambiguous",
                branch_count=len(branches),
                equations=tuple(normalized),
            )
        branch = branches[0]
        if any(symbol not in branch for symbol in unknowns):
            unresolved = tuple(symbol for symbol in unknowns if symbol not in branch)
            partial_substitutions = {**substitutions, **branch}
            free_symbols = tuple(
                dict.fromkeys((*unresolved, *preserve))
            )
            return QuadraticConstraintSolveResult(
                "single_free" if len(free_symbols) == 1 else "underdetermined",
                coefficient_substitution=partial_substitutions,
                parabola=sp.expand(
                    request.base_expression.subs(partial_substitutions)
                ),
                free_symbols=free_symbols,
                dependency_symbols=_dependency_symbols(
                    request.base_expression.subs(partial_substitutions),
                    partial_substitutions.values(),
                    independent_symbol=request.independent_symbol,
                ),
                branch_count=1,
                equations=tuple(normalized),
            )
        substitutions.update(
            {symbol: sp.simplify(value) for symbol, value in branch.items()}
        )
    elif any(sp.simplify(item.lhs - item.rhs) != 0 for item in normalized):
        return QuadraticConstraintSolveResult(
            "inconsistent",
            equations=tuple(normalized),
        )

    parabola = sp.expand(request.base_expression.subs(substitutions))
    free = tuple(
        sorted(
            parabola.free_symbols - {request.independent_symbol},
            key=lambda item: item.name,
        )
    )
    status: QuadraticConstraintStatus = (
        "determined"
        if not free
        else "single_free" if len(free) == 1 else "underdetermined"
    )
    target_value = (
        substitutions.get(request.target_symbol)
        if request.target_symbol is not None
        else None
    )
    dependencies = _dependency_symbols(
        parabola,
        substitutions.values(),
        independent_symbol=request.independent_symbol,
    )
    return QuadraticConstraintSolveResult(
        status,
        coefficient_substitution=dict(substitutions),
        parabola=parabola,
        free_symbols=free,
        target_value=target_value,
        dependency_symbols=dependencies,
        branch_count=1,
        equations=tuple(normalized),
    )


def _materialized_coefficient_substitutions(
    request: QuadraticConstraintSolveRequest,
) -> dict[sp.Symbol, sp.Expr]:
    """Recover coefficient state already encoded in the current parabola.

    A refined ``Parabola`` no longer has to contain the original coefficient
    symbols.  Treating those absent symbols as fresh unknowns makes a later
    constraint call forget the current state and solve the template again.
    For the conventional ``(a, b, c)`` coefficient vector, project the current
    polynomial back onto ``x**2, x, 1`` and retain only genuinely materialized
    values.  Explicit known coefficients and parameter substitutions are
    applied afterwards and remain authoritative.
    """
    if len(request.coefficient_symbols) != 3:
        return {}
    try:
        polynomial = sp.Poly(
            sp.expand(request.base_expression),
            request.independent_symbol,
        )
    except (sp.PolynomialError, TypeError, ValueError):
        return {}
    if polynomial.degree() > 2:
        return {}
    values = (
        polynomial.coeff_monomial(request.independent_symbol**2),
        polynomial.coeff_monomial(request.independent_symbol),
        polynomial.coeff_monomial(1),
    )
    result: dict[sp.Symbol, sp.Expr] = {}
    for symbol, value in zip(request.coefficient_symbols, values, strict=True):
        value = sp.simplify(value)
        if value == symbol:
            continue
        # A partially materialized coefficient may depend on another declared
        # coefficient (for example a=-b/2).  That relation is still useful and
        # leaves the dependency symbol available to the shared solver.
        if symbol in value.free_symbols:
            continue
        result[symbol] = value
    return result


def _substitute_mapping_values(
    values: dict[sp.Symbol, sp.Expr],
    substitutions: dict[sp.Symbol, sp.Expr],
) -> dict[sp.Symbol, sp.Expr]:
    if not substitutions:
        return dict(values)
    return {
        symbol: sp.simplify(sp.sympify(value).subs(substitutions))
        for symbol, value in values.items()
    }


def _solve_target(
    request: QuadraticConstraintSolveRequest,
    *,
    expression: sp.Expr,
    equations: list[sp.Equality],
    substitutions: dict[sp.Symbol, sp.Expr],
    kernel: SympyKernel,
) -> QuadraticConstraintSolveResult | None:
    target = request.target_symbol
    if target is None or not equations:
        return None
    closure = solve_target_symbol_closure(
        equations,
        target=target,
        target_expression=request.target_expression,
        kernel=kernel,
        accept_target=lambda value: value_satisfies_constraint(
            value,
            request.parameter_constraint,
        ),
        preserve_symbols=request.preserve_symbols,
    )
    status_map: dict[str, QuadraticConstraintStatus] = {
        "underdetermined": "underdetermined",
        "identity_unresolved": "underdetermined",
        "ambiguous": "ambiguous",
        "inconsistent": "inconsistent",
    }
    if closure.status != "unique" or closure.target_value is None:
        return QuadraticConstraintSolveResult(
            status_map.get(closure.status, "inconsistent"),
            coefficient_substitution=dict(substitutions),
            parabola=expression,
            free_symbols=closure.residual_symbols,
            dependency_symbols=closure.residual_symbols,
            branch_count=closure.branch_count,
            equations=tuple(equations),
        )
    solved = {
        **substitutions,
        **closure.substitution,
        target: sp.simplify(closure.target_value),
    }
    parabola = sp.expand(request.base_expression.subs(solved))
    free = tuple(
        sorted(
            parabola.free_symbols - {request.independent_symbol},
            key=lambda item: item.name,
        )
    )
    status: QuadraticConstraintStatus = (
        "determined"
        if not free
        else "single_free" if len(free) == 1 else "underdetermined"
    )
    return QuadraticConstraintSolveResult(
        status,
        coefficient_substitution=solved,
        parabola=parabola,
        free_symbols=free,
        target_value=sp.simplify(closure.target_value),
        dependency_symbols=_dependency_symbols(
            parabola,
            solved.values(),
            independent_symbol=request.independent_symbol,
        ),
        branch_count=closure.branch_count,
        equations=tuple(equations),
    )


def value_satisfies_constraint(
    value: sp.Expr,
    constraint: dict[str, sp.Expr | str] | None,
) -> bool:
    if constraint is None:
        return True
    operator = str(constraint.get("operator", ""))
    if operator != ">":
        return True
    try:
        return bool(sp.simplify(value - sp.sympify(constraint["value"])) > 0)
    except TypeError:
        return False


def _substitute_equation(
    equation: sp.Equality,
    substitutions: dict[sp.Symbol, sp.Expr],
) -> sp.Equality | Any:
    if equation in {sp.S.true, sp.S.false}:
        return equation
    return sp.Eq(
        sp.simplify(equation.lhs.subs(substitutions)),
        sp.simplify(equation.rhs.subs(substitutions)),
    )


def _normalize_equations(
    equations: list[Any],
) -> tuple[list[sp.Equality], bool]:
    result: list[sp.Equality] = []
    for equation in equations:
        if equation is sp.S.true:
            continue
        if equation is sp.S.false:
            return result, True
        residual = sp.simplify(equation.lhs - equation.rhs)
        if residual == 0:
            continue
        if residual.free_symbols:
            result.append(sp.Eq(residual, 0))
            continue
        return result, True
    return result, False


def _dependency_symbols(
    parabola: sp.Expr,
    values: Any,
    *,
    independent_symbol: sp.Symbol,
) -> tuple[sp.Symbol, ...]:
    symbols = set(parabola.free_symbols)
    for value in values:
        if isinstance(value, sp.Expr):
            symbols.update(value.free_symbols)
    symbols.discard(independent_symbol)
    return tuple(sorted(symbols, key=lambda item: item.name))


__all__ = [
    "QuadraticConstraintSolveRequest",
    "QuadraticConstraintSolveResult",
    "QuadraticConstraintStatus",
    "solve_quadratic_constraint_system",
    "value_satisfies_constraint",
]
