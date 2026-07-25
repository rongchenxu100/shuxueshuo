"""Deterministic target-Symbol closure for bounded algebraic calls."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import sympy as sp

from shuxueshuo_server.solver.math_kernel import SympyKernel


TargetClosureStatus = Literal[
    "unique",
    "identity_unresolved",
    "underdetermined",
    "ambiguous",
    "inconsistent",
]


@dataclass(frozen=True)
class TargetSymbolClosureResult:
    """Result of solving one bounded equation set for a requested Symbol."""

    status: TargetClosureStatus
    target: sp.Symbol
    target_value: sp.Expr | None = None
    substitutions: tuple[tuple[sp.Symbol, sp.Expr], ...] = ()
    residual_symbols: tuple[sp.Symbol, ...] = ()
    branch_count: int = 0

    @property
    def substitution(self) -> dict[sp.Symbol, sp.Expr]:
        return dict(self.substitutions)


def solve_target_symbol_closure(
    equations: Sequence[Any],
    *,
    target: sp.Symbol,
    kernel: SympyKernel,
    target_expression: sp.Expr | None = None,
    accept_target: Callable[[sp.Expr], bool] | None = None,
    preserve_symbols: Sequence[sp.Symbol] = (),
) -> TargetSymbolClosureResult:
    """Solve only the equation-local symbols needed to determine ``target``.

    ``target_expression`` is a deterministic representation map, such as the
    current quadratic coefficient corresponding to the requested coefficient
    Symbol. It lets a call solve an internal residual Symbol and then map that
    value back to the requested identity without searching unrelated state or
    inventing another capability chain.
    """

    normalized, inconsistent = _normalize_equations(equations)
    residual_symbols = _ordered_symbols(
        symbol
        for equation in normalized
        for symbol in (equation.lhs - equation.rhs).free_symbols
    )
    if inconsistent:
        return TargetSymbolClosureResult(
            "inconsistent",
            target,
            residual_symbols=residual_symbols,
        )

    preserved = set(preserve_symbols)
    if target in preserved:
        return TargetSymbolClosureResult(
            "underdetermined",
            target,
            residual_symbols=residual_symbols,
        )
    if target in residual_symbols:
        # Solve the bounded system before deciding whether the requested
        # Symbol is underdetermined. Auxiliary unknowns may be jointly
        # determined, or may remain free while the target itself is unique.
        solve_symbols = tuple(
            symbol for symbol in residual_symbols if symbol not in preserved
        )
    else:
        if target_expression is None:
            return TargetSymbolClosureResult(
                "identity_unresolved",
                target,
                residual_symbols=residual_symbols,
            )
        expression_dependencies = set(target_expression.free_symbols)
        if not expression_dependencies.issubset(set(residual_symbols)):
            return TargetSymbolClosureResult(
                "underdetermined",
                target,
                residual_symbols=_ordered_symbols(
                    (*residual_symbols, *expression_dependencies)
                ),
            )
        solve_symbols = tuple(
            symbol for symbol in residual_symbols if symbol not in preserved
        )

    if not solve_symbols:
        if target_expression is None or target_expression.free_symbols:
            return TargetSymbolClosureResult(
                "underdetermined",
                target,
                residual_symbols=residual_symbols,
            )
        return TargetSymbolClosureResult(
            "unique",
            target,
            target_value=sp.simplify(target_expression),
            branch_count=1,
        )

    branches = kernel.solve_equations(list(normalized), list(solve_symbols))
    if not branches:
        return TargetSymbolClosureResult(
            "inconsistent",
            target,
            residual_symbols=residual_symbols,
            branch_count=0,
        )

    resolved: list[tuple[sp.Expr, dict[sp.Symbol, sp.Expr]]] = []
    for branch in branches:
        substitution = {
            symbol: sp.simplify(branch[symbol])
            for symbol in solve_symbols
            if symbol in branch
        }
        if target in substitution:
            target_value = substitution[target]
        elif target_expression is not None:
            target_value = sp.simplify(target_expression.subs(substitution))
        else:
            continue
        if not target_value.free_symbols.issubset(preserved):
            continue
        if accept_target is not None and not accept_target(target_value):
            continue
        resolved.append((target_value, substitution))

    if not resolved:
        return TargetSymbolClosureResult(
            "underdetermined",
            target,
            residual_symbols=residual_symbols,
            branch_count=len(branches),
        )
    target_groups = _group_by_target_value(resolved)
    if len(target_groups) != 1:
        return TargetSymbolClosureResult(
            "ambiguous",
            target,
            residual_symbols=residual_symbols,
            branch_count=len(target_groups),
        )

    target_value, substitutions = target_groups[0]
    substitution = _common_substitution(substitutions, solve_symbols)
    return TargetSymbolClosureResult(
        "unique",
        target,
        target_value=target_value,
        substitutions=tuple(substitution.items()),
        residual_symbols=residual_symbols,
        branch_count=1,
    )


def _group_by_target_value(
    resolved: Sequence[tuple[sp.Expr, dict[sp.Symbol, sp.Expr]]],
) -> list[tuple[sp.Expr, list[dict[sp.Symbol, sp.Expr]]]]:
    """Group solver branches by the value that matters to the caller."""
    groups: list[tuple[sp.Expr, list[dict[sp.Symbol, sp.Expr]]]] = []
    for target_value, substitution in resolved:
        for known_value, substitutions in groups:
            if sp.simplify(target_value - known_value) == 0:
                substitutions.append(substitution)
                break
        else:
            groups.append((target_value, [substitution]))
    return groups


def _common_substitution(
    substitutions: Sequence[dict[sp.Symbol, sp.Expr]],
    solve_symbols: Sequence[sp.Symbol],
) -> dict[sp.Symbol, sp.Expr]:
    """Keep only assignments shared by every branch of one target value."""
    if not substitutions:
        return {}
    common: dict[sp.Symbol, sp.Expr] = {}
    for symbol in solve_symbols:
        values = [item.get(symbol) for item in substitutions]
        if any(value is None for value in values):
            continue
        first = values[0]
        if first is None:
            continue
        if all(
            value is not None and sp.simplify(value - first) == 0
            for value in values[1:]
        ):
            common[symbol] = first
    return common


def _normalize_equations(
    equations: Sequence[Any],
) -> tuple[tuple[sp.Equality, ...], bool]:
    normalized: list[sp.Equality] = []
    for equation in equations:
        if equation is sp.S.true or equation is True:
            continue
        if equation is sp.S.false or equation is False:
            return tuple(normalized), True
        simplified = sp.simplify(equation.lhs - equation.rhs)
        if simplified == 0:
            continue
        if simplified.is_number and simplified != 0:
            return tuple(normalized), True
        normalized.append(sp.Eq(simplified, 0))
    return tuple(normalized), False


def _ordered_symbols(symbols: Iterable[sp.Symbol]) -> tuple[sp.Symbol, ...]:
    return tuple(sorted(set(symbols), key=lambda symbol: symbol.name))
