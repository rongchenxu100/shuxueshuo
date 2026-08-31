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
from shuxueshuo_server.solver.runtime.symbolic_state_representation import (
    SymbolicStateRepresentationProof,
    project_symbolic_state_representation,
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
    coefficient_template: sp.Expr | None = None
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
    representation_proof: SymbolicStateRepresentationProof | None = None


@dataclass(frozen=True)
class QuadraticConstraintSystem:
    expression: sp.Expr
    substitutions: dict[sp.Symbol, sp.Expr]
    curve_points: tuple[Point, ...]
    equations: tuple[sp.Equality, ...]
    contradictory: bool = False


def build_quadratic_constraint_system(
    request: QuadraticConstraintSolveRequest,
) -> QuadraticConstraintSystem:
    """Build the normalized equation system shared by runtime consumers."""

    parameter_substitutions = dict(request.parameter_substitutions)
    known_coefficients = _substitute_mapping_values(
        request.known_coefficients,
        parameter_substitutions,
    )
    explicit_conflict = _substitution_mappings_conflict(
        known_coefficients,
        parameter_substitutions,
    )
    materialized_coefficients = _substitute_mapping_values(
        _materialized_coefficient_substitutions(request),
        parameter_substitutions,
    )
    explicit_coefficients = _resolve_substitution_values({
        **known_coefficients,
        **parameter_substitutions,
    })
    resolved_materialized_coefficients = _substitute_mapping_values(
        materialized_coefficients,
        explicit_coefficients,
    )
    materialized_consistency = tuple(
        sp.Eq(materialized_value, explicit_coefficients[symbol])
        for symbol, materialized_value in resolved_materialized_coefficients.items()
        if symbol in explicit_coefficients
        and sp.simplify(
            materialized_value - explicit_coefficients[symbol]
        )
        != 0
    )
    substitutions = _resolve_substitution_values({
        **materialized_coefficients,
        **known_coefficients,
        **parameter_substitutions,
    })
    expression = sp.expand(request.base_expression.subs(substitutions))
    points = tuple(
        (
            sp.simplify(
                sp.sympify(point[0]).subs(substitutions)
            ),
            sp.simplify(
                sp.sympify(point[1]).subs(substitutions)
            ),
        )
        for point in request.curve_points
    )
    equations = [
        _substitute_equation(equation, substitutions)
        for equation in (
            *request.equations,
            *materialized_consistency,
        )
    ]
    equations.extend(
        sp.Eq(expression.subs(request.independent_symbol, point[0]), point[1])
        for point in points
    )
    normalized, contradictory = _normalize_equations(equations)
    return QuadraticConstraintSystem(
        expression=expression,
        substitutions=substitutions,
        curve_points=points,
        equations=tuple(normalized),
        contradictory=contradictory or explicit_conflict,
    )


def solve_quadratic_constraint_system(
    request: QuadraticConstraintSolveRequest,
    *,
    kernel: SympyKernel,
) -> QuadraticConstraintSolveResult:
    """Solve or refine a quadratic while preserving an explicit free basis."""
    system = build_quadratic_constraint_system(request)
    substitutions = system.substitutions
    expression = system.expression
    normalized = list(system.equations)
    if system.contradictory:
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

    representation_proof = (
        project_symbolic_state_representation(
            expression,
            requested_symbols=preserve,
            representable_symbols=tuple(
                dict.fromkeys((*request.coefficient_symbols, *preserve))
            ),
            relations=(
                *(
                    sp.Eq(symbol, value)
                    for symbol, value in substitutions.items()
                ),
                *normalized,
            ),
            excluded_symbols=(request.independent_symbol,),
        )
        if request.target_symbol is None
        else None
    )
    if representation_proof is not None:
        projection = representation_proof.substitution_map
        expression = representation_proof.projected_expression
        substitutions = _project_substitution_mapping(
            substitutions,
            projection,
        )
        normalized, contradictory = _normalize_equations(
            [_substitute_equation(equation, projection) for equation in normalized]
        )
        if contradictory:
            return QuadraticConstraintSolveResult(
                "inconsistent",
                equations=tuple(normalized),
                representation_proof=representation_proof,
            )

    # A target supplied by known coefficients or a ParameterValue is already
    # closed.  Continue solving the remaining coefficient system instead of
    # asking target closure to recover a Symbol that substitutions removed
    # from every equation.
    if (
        request.target_symbol is not None
        and request.target_symbol not in substitutions
    ):
        target_expression = request.target_expression
        if target_expression is None:
            target_expression = quadratic_target_expression(
                request,
                system=system,
            )
        targeted = _solve_target(
            request,
            expression=expression,
            equations=normalized,
            substitutions=substitutions,
            target_expression=target_expression,
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
                representation_proof=representation_proof,
            )
        branches = sp.solve(normalized, unknowns, dict=True)
        if not branches:
            return QuadraticConstraintSolveResult(
                "inconsistent",
                equations=tuple(normalized),
                representation_proof=representation_proof,
            )
        if len(branches) != 1:
            return QuadraticConstraintSolveResult(
                "ambiguous",
                branch_count=len(branches),
                equations=tuple(normalized),
                representation_proof=representation_proof,
            )
        branch = branches[0]
        if any(symbol not in branch for symbol in unknowns):
            unresolved = tuple(symbol for symbol in unknowns if symbol not in branch)
            partial_substitutions = _resolve_substitution_values(
                {**substitutions, **branch}
            )
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
                representation_proof=representation_proof,
            )
        substitutions = _resolve_substitution_values(
            {
                **substitutions,
                **{
                    symbol: sp.simplify(value)
                    for symbol, value in branch.items()
                },
            }
        )
    elif any(sp.simplify(item.lhs - item.rhs) != 0 for item in normalized):
        return QuadraticConstraintSolveResult(
            "inconsistent",
            equations=tuple(normalized),
        )

    substitutions = _resolve_substitution_values(substitutions)
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
    target_dependencies = (
        set(sp.sympify(target_value).free_symbols)
        if target_value is not None
        else set()
    )
    unexpected_target_dependencies = target_dependencies - set(preserve)
    if unexpected_target_dependencies:
        free = tuple(
            sorted(
                set(free) | unexpected_target_dependencies,
                key=lambda item: item.name,
            )
        )
        status = "underdetermined"
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
        representation_proof=representation_proof,
    )


def _project_substitution_mapping(
    substitutions: dict[sp.Symbol, sp.Expr],
    projection: dict[sp.Symbol, sp.Expr],
) -> dict[sp.Symbol, sp.Expr]:
    result: dict[sp.Symbol, sp.Expr] = {}
    for symbol, value in substitutions.items():
        projected = sp.simplify(sp.sympify(value).subs(projection))
        if projected != symbol:
            result[symbol] = projected
    for symbol, value in projection.items():
        projected = sp.simplify(value)
        if projected != symbol:
            result[symbol] = projected
    return _resolve_substitution_values(result)


def _resolve_substitution_values(
    substitutions: dict[sp.Symbol, sp.Expr],
) -> dict[sp.Symbol, sp.Expr]:
    result = dict(substitutions)
    for _ in range(len(result) + 1):
        changed = False
        for symbol, value in tuple(result.items()):
            others = {
                key: item
                for key, item in result.items()
                if key != symbol
            }
            resolved = sp.simplify(sp.sympify(value).subs(others))
            if resolved != value:
                result[symbol] = resolved
                changed = True
        if not changed:
            break
    return result


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
    if request.coefficient_template is not None:
        # An explicit template is the coefficient-role authority even when
        # the current expression still matches it exactly. Falling through to
        # conventional a/b/c positions would misread sparse templates such as
        # ``a*x**2 + b``, where ``b`` is the constant coefficient.
        return _coefficient_substitutions_from_template(request)
    try:
        polynomial = sp.Poly(
            sp.expand(request.base_expression),
            request.independent_symbol,
        )
    except (sp.PolynomialError, TypeError, ValueError):
        return {}
    if polynomial.degree() > 2:
        return {}
    conventional_monomials = {
        "a": request.independent_symbol**2,
        "b": request.independent_symbol,
        "c": sp.Integer(1),
    }
    if all(
        symbol.name in conventional_monomials
        for symbol in request.coefficient_symbols
    ):
        values = tuple(
            polynomial.coeff_monomial(conventional_monomials[symbol.name])
            for symbol in request.coefficient_symbols
        )
    elif len(request.coefficient_symbols) == 3:
        values = (
            polynomial.coeff_monomial(request.independent_symbol**2),
            polynomial.coeff_monomial(request.independent_symbol),
            polynomial.coeff_monomial(1),
        )
    else:
        return {}
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


def _coefficient_substitutions_from_template(
    request: QuadraticConstraintSolveRequest,
) -> dict[sp.Symbol, sp.Expr]:
    """Recover eliminated coefficients from the immutable function template.

    The current state may already encode a relation such as one coefficient
    expressed through another. Compare it with the original polynomial and
    solve only for coefficient Symbols absent from the current expression.
    This works for partial coefficient vectors and does not rely on names or a
    fixed ``(a, b, c)`` layout.
    """

    template = request.coefficient_template
    if template is None:
        return {}
    current_symbols = set(
        sp.sympify(request.base_expression).free_symbols
    )
    eliminated = tuple(
        symbol
        for symbol in request.coefficient_symbols
        if symbol not in current_symbols
    )
    if not eliminated:
        return {}
    try:
        difference = sp.Poly(
            sp.expand(
                template - request.base_expression
            ),
            request.independent_symbol,
        )
    except (sp.PolynomialError, TypeError, ValueError):
        return {}
    equations = tuple(
        sp.Eq(coefficient, 0)
        for coefficient in difference.all_coeffs()
        if sp.simplify(coefficient) != 0
    )
    if not equations:
        return {}
    branches = sp.solve(equations, eliminated, dict=True)
    if len(branches) != 1:
        return {}
    branch = branches[0]
    if any(symbol not in branch for symbol in eliminated):
        return {}
    return {
        symbol: sp.simplify(branch[symbol])
        for symbol in eliminated
        if symbol not in sp.sympify(branch[symbol]).free_symbols
    }


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


def _substitution_mappings_conflict(
    left: dict[sp.Symbol, sp.Expr],
    right: dict[sp.Symbol, sp.Expr],
) -> bool:
    return any(
        symbol in right
        and sp.simplify(
            sp.sympify(value) - sp.sympify(right[symbol])
        )
        != 0
        for symbol, value in left.items()
    )


def _solve_target(
    request: QuadraticConstraintSolveRequest,
    *,
    expression: sp.Expr,
    equations: list[sp.Equality],
    substitutions: dict[sp.Symbol, sp.Expr],
    target_expression: sp.Expr | None,
    kernel: SympyKernel,
) -> QuadraticConstraintSolveResult | None:
    target = request.target_symbol
    if target is None or not equations:
        return None
    closure = solve_target_symbol_closure(
        equations,
        target=target,
        target_expression=target_expression,
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


def quadratic_target_expression(
    request: QuadraticConstraintSolveRequest,
    *,
    system: QuadraticConstraintSystem | None = None,
) -> sp.Expr | None:
    """Project a target coefficient through the current quadratic state."""

    target = request.target_symbol
    if target is None:
        return None
    system = system or build_quadratic_constraint_system(request)
    template = request.coefficient_template
    parameter_substitutions = dict(request.parameter_substitutions)
    explicit_substitutions = {
        **_substitute_mapping_values(
            request.known_coefficients,
            parameter_substitutions,
        ),
        **parameter_substitutions,
    }
    return quadratic_coefficient_expression(
        system.expression,
        independent_symbol=request.independent_symbol,
        target_symbol=target,
        template_expression=(
            sp.sympify(template).subs(explicit_substitutions)
            if template is not None
            else None
        ),
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


def quadratic_coefficient_expression(
    current_expression: sp.Expr,
    *,
    independent_symbol: sp.Symbol,
    target_symbol: sp.Symbol,
    template_expression: sp.Expr | None,
) -> sp.Expr | None:
    """Map one template coefficient identity into the current polynomial.

    A refined polynomial may no longer contain the original coefficient
    Symbol. The template preserves that identity, while the current
    expression contains its actual representation in the selected free basis.
    """
    if (
        template_expression is None
        or target_symbol not in template_expression.free_symbols
    ):
        return None
    try:
        current = sp.Poly(
            sp.expand(current_expression),
            independent_symbol,
        )
        template = sp.Poly(
            sp.expand(template_expression),
            independent_symbol,
        )
    except (sp.PolynomialError, TypeError, ValueError):
        return None
    candidates: list[sp.Expr] = []
    for power in range(max(current.degree(), template.degree()), -1, -1):
        template_coefficient = template.coeff_monomial(
            independent_symbol**power
        )
        if target_symbol not in template_coefficient.free_symbols:
            continue
        current_coefficient = current.coeff_monomial(
            independent_symbol**power
        )
        solutions = sp.solve(
            sp.Eq(template_coefficient, current_coefficient),
            target_symbol,
            dict=True,
        )
        candidates.extend(
            sp.simplify(solution[target_symbol])
            for solution in solutions
            if target_symbol in solution
            and target_symbol not in solution[target_symbol].free_symbols
        )
    unique: list[sp.Expr] = []
    for candidate in candidates:
        if not any(sp.simplify(candidate - item) == 0 for item in unique):
            unique.append(candidate)
    return unique[0] if len(unique) == 1 else None


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
