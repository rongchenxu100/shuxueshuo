"""Deterministic symbolic views over one immutable runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import sympy as sp
from sympy.core.relational import Relational

from shuxueshuo_server.solver.contracts import PointRef


class SymbolicStateRepresentationError(ValueError):
    """Structured failure to prove one requested symbolic basis."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        requested_symbols: Iterable[sp.Symbol] = (),
        current_symbols: Iterable[sp.Symbol] = (),
        branch_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.requested_symbols = tuple(
            sorted(set(requested_symbols), key=lambda item: item.name)
        )
        self.current_symbols = tuple(
            sorted(set(current_symbols), key=lambda item: item.name)
        )
        self.branch_count = branch_count


@dataclass(frozen=True)
class SymbolicStateRepresentationProof:
    """Proof that two expressions represent the same state in different bases."""

    source_expression: sp.Expr
    projected_expression: sp.Expr
    requested_symbols: tuple[sp.Symbol, ...]
    eliminated_symbols: tuple[sp.Symbol, ...]
    substitutions: tuple[tuple[sp.Symbol, sp.Expr], ...]
    relation_equations: tuple[sp.Equality, ...]

    @property
    def substitution_map(self) -> dict[sp.Symbol, sp.Expr]:
        return dict(self.substitutions)


@dataclass(frozen=True)
class SymbolicInputView:
    """One ephemeral Method input plus the proofs used to align its basis."""

    value: Any
    proofs: tuple[SymbolicStateRepresentationProof, ...] = ()


def project_symbolic_state_representation(
    expression: sp.Expr,
    *,
    requested_symbols: Iterable[sp.Symbol],
    representable_symbols: Iterable[sp.Symbol],
    relations: Iterable[sp.Equality],
    excluded_symbols: Iterable[sp.Symbol] = (),
) -> SymbolicStateRepresentationProof | None:
    """Project ``expression`` to an explicitly requested equivalent basis.

    The function never chooses a preferred variable. The caller supplies the
    typed Symbol identities to preserve, and the projection succeeds only
    when the supplied relations prove one unique representation.
    """

    source = sp.expand(sp.sympify(expression))
    requested = tuple(dict.fromkeys(requested_symbols))
    if not requested:
        return None
    representable = set(representable_symbols)
    excluded = set(excluded_symbols)
    requested_set = set(requested)
    current = (set(source.free_symbols) & representable) - excluded
    equations = tuple(_normalized_relations(relations))
    if current == requested_set:
        return None

    eliminated = tuple(
        sorted(current - requested_set, key=lambda item: item.name)
    )
    if not eliminated:
        raise SymbolicStateRepresentationError(
            "function.state_representation_unresolved",
            "function.state_representation_unresolved: "
            f"requested={_symbol_names(requested_set)}, "
            f"current={_symbol_names(current)}",
            requested_symbols=requested_set,
            current_symbols=current,
            branch_count=0,
        )

    projection_equations = tuple(
        relation
        for relation in equations
        if set((relation.lhs - relation.rhs).free_symbols) & set(eliminated)
    )
    branches = sp.solve(projection_equations, eliminated, dict=True)
    valid: list[tuple[dict[sp.Symbol, sp.Expr], sp.Expr]] = []
    for raw_branch in branches:
        if any(symbol not in raw_branch for symbol in eliminated):
            continue
        branch = {
            symbol: sp.simplify(raw_branch[symbol])
            for symbol in eliminated
        }
        if any(
            set(value.free_symbols) & set(eliminated)
            for value in branch.values()
        ):
            continue
        projected = sp.expand(source.subs(branch))
        projected_basis = (
            set(projected.free_symbols) & representable
        ) - excluded
        if projected_basis != requested_set:
            continue
        if not _branch_satisfies_relations(branch, projection_equations):
            continue
        valid.append((branch, projected))

    if not valid:
        raise SymbolicStateRepresentationError(
            "function.state_representation_unresolved",
            "function.state_representation_unresolved: "
            f"requested={_symbol_names(requested_set)}, "
            f"current={_symbol_names(current)}",
            requested_symbols=requested_set,
            current_symbols=current,
            branch_count=0,
        )
    if len(valid) != 1:
        raise SymbolicStateRepresentationError(
            "function.state_representation_ambiguous",
            "function.state_representation_ambiguous: "
            f"requested={_symbol_names(requested_set)}, "
            f"branch_count={len(valid)}",
            requested_symbols=requested_set,
            current_symbols=current,
            branch_count=len(valid),
        )

    branch, projected = valid[0]
    return SymbolicStateRepresentationProof(
        source_expression=source,
        projected_expression=projected,
        requested_symbols=requested,
        eliminated_symbols=eliminated,
        substitutions=tuple(
            sorted(branch.items(), key=lambda item: item[0].name)
        ),
        relation_equations=equations,
    )


def polynomial_state_relations(
    source_expression: sp.Expr,
    runtime_expression: sp.Expr,
    *,
    independent_symbol: sp.Symbol,
) -> tuple[sp.Equality, ...]:
    """Derive coefficient relations between two states of one polynomial.

    The caller is responsible for proving that both expressions belong to the
    same MathObject. This helper only performs deterministic algebra and never
    chooses a preferred coefficient basis.
    """

    residual = sp.together(
        sp.sympify(source_expression) - sp.sympify(runtime_expression)
    )
    numerator, denominator = sp.fraction(residual)
    if independent_symbol in denominator.free_symbols:
        raise SymbolicStateRepresentationError(
            "function.state_representation_unresolved",
            "function.state_representation_unresolved: runtime state is not "
            "polynomial in the independent symbol",
        )
    try:
        polynomial = sp.Poly(sp.expand(numerator), independent_symbol)
    except sp.PolynomialError as exc:
        raise SymbolicStateRepresentationError(
            "function.state_representation_unresolved",
            "function.state_representation_unresolved: runtime state is not "
            "a compatible polynomial",
        ) from exc
    return tuple(
        sp.Eq(coefficient, 0, evaluate=False)
        for coefficient in polynomial.all_coeffs()
        if sp.simplify(coefficient) != 0
    )


def project_symbolic_input_view(
    value: Any,
    *,
    allowed_symbols: Iterable[sp.Symbol],
    representable_symbols: Iterable[sp.Symbol],
    relations: Iterable[sp.Equality],
    excluded_symbols: Iterable[sp.Symbol] = (),
) -> SymbolicInputView:
    """Project expression leaves of one Method input to an allowed basis.

    Unlike ``project_symbolic_state_representation``, an individual input does
    not have to mention every symbol retained by the state. It only has to
    eliminate symbols outside the state's active basis. Containers and
    PointRef definitions are rebuilt; the source authority is never mutated.
    """

    allowed = tuple(dict.fromkeys(allowed_symbols))
    representable = tuple(dict.fromkeys(representable_symbols))
    equations = tuple(relations)
    excluded = tuple(dict.fromkeys(excluded_symbols))
    proofs: list[SymbolicStateRepresentationProof] = []

    def visit(item: Any) -> Any:
        if isinstance(item, PointRef):
            return PointRef(
                name=item.name,
                path=item.path,
                definition=visit(item.definition),
                scope_id=item.scope_id,
            )
        if isinstance(item, Mapping):
            return {key: visit(child) for key, child in item.items()}
        if isinstance(item, tuple):
            return tuple(visit(child) for child in item)
        if isinstance(item, list):
            return [visit(child) for child in item]
        if isinstance(item, Relational):
            return item.func(visit(item.lhs), visit(item.rhs), evaluate=False)
        if isinstance(item, sp.Basic):
            proof = _project_expression_to_allowed_basis(
                item,
                allowed_symbols=allowed,
                representable_symbols=representable,
                relations=equations,
                excluded_symbols=excluded,
            )
            if proof is None:
                return item
            proofs.append(proof)
            return proof.projected_expression
        return item

    return SymbolicInputView(visit(value), tuple(proofs))


def _project_expression_to_allowed_basis(
    expression: sp.Expr,
    *,
    allowed_symbols: tuple[sp.Symbol, ...],
    representable_symbols: tuple[sp.Symbol, ...],
    relations: tuple[sp.Equality, ...],
    excluded_symbols: tuple[sp.Symbol, ...],
) -> SymbolicStateRepresentationProof | None:
    source = sp.expand(sp.sympify(expression))
    allowed = set(allowed_symbols)
    representable = set(representable_symbols)
    excluded = set(excluded_symbols)
    current = (set(source.free_symbols) & representable) - excluded
    eliminated = tuple(sorted(current - allowed, key=lambda item: item.name))
    if not eliminated:
        return None

    projection_equations = tuple(
        relation
        for relation in _normalized_relations(relations)
        if set((relation.lhs - relation.rhs).free_symbols) & set(eliminated)
    )
    branches = sp.solve(projection_equations, eliminated, dict=True)
    valid: dict[str, tuple[dict[sp.Symbol, sp.Expr], sp.Expr]] = {}
    for raw_branch in branches:
        if any(symbol not in raw_branch for symbol in eliminated):
            continue
        branch = {
            symbol: sp.simplify(raw_branch[symbol])
            for symbol in eliminated
        }
        if any(
            set(candidate.free_symbols) & set(eliminated)
            for candidate in branch.values()
        ):
            continue
        projected = sp.simplify(source.subs(branch))
        projected_basis = (
            set(projected.free_symbols) & representable
        ) - excluded
        if not projected_basis.issubset(allowed):
            continue
        if not _branch_satisfies_relations(branch, projection_equations):
            continue
        valid.setdefault(sp.srepr(projected), (branch, projected))

    if not valid:
        raise SymbolicStateRepresentationError(
            "function.state_representation_unresolved",
            "function.state_representation_unresolved: "
            f"allowed={_symbol_names(allowed)}, "
            f"current={_symbol_names(current)}",
            requested_symbols=allowed,
            current_symbols=current,
            branch_count=0,
        )
    if len(valid) != 1:
        raise SymbolicStateRepresentationError(
            "function.state_representation_ambiguous",
            "function.state_representation_ambiguous: "
            f"allowed={_symbol_names(allowed)}, "
            f"branch_count={len(valid)}",
            requested_symbols=allowed,
            current_symbols=current,
            branch_count=len(valid),
        )
    branch, projected = next(iter(valid.values()))
    return SymbolicStateRepresentationProof(
        source_expression=source,
        projected_expression=projected,
        requested_symbols=tuple(sorted(allowed, key=lambda item: item.name)),
        eliminated_symbols=eliminated,
        substitutions=tuple(
            sorted(branch.items(), key=lambda item: item[0].name)
        ),
        relation_equations=tuple(_normalized_relations(relations)),
    )


def _normalized_relations(
    relations: Iterable[sp.Equality],
) -> list[sp.Equality]:
    result: list[sp.Equality] = []
    for relation in relations:
        if relation is sp.S.true:
            continue
        if relation is sp.S.false:
            raise SymbolicStateRepresentationError(
                "function.state_representation_inconsistent",
                "function.state_representation_inconsistent: false relation"
            )
        residual = sp.simplify(relation.lhs - relation.rhs)
        if residual == 0:
            continue
        result.append(sp.Eq(residual, 0))
    return result


def _branch_satisfies_relations(
    branch: dict[sp.Symbol, sp.Expr],
    relations: tuple[sp.Equality, ...],
) -> bool:
    return all(
        sp.simplify((relation.lhs - relation.rhs).subs(branch)) == 0
        for relation in relations
    )


def _symbol_names(symbols: Iterable[sp.Symbol]) -> str:
    names = sorted(symbol.name for symbol in symbols)
    return ",".join(names) or "none"


__all__ = [
    "SymbolicInputView",
    "SymbolicStateRepresentationError",
    "SymbolicStateRepresentationProof",
    "polynomial_state_relations",
    "project_symbolic_input_view",
    "project_symbolic_state_representation",
]
