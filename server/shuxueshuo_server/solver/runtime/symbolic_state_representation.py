"""Deterministic symbolic views over one immutable runtime state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import sympy as sp


class SymbolicStateRepresentationError(ValueError):
    """Raised when a requested symbolic basis cannot be proven unique."""


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
            "function.state_representation_unresolved: "
            f"requested={_symbol_names(requested_set)}, "
            f"current={_symbol_names(current)}"
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
            "function.state_representation_unresolved: "
            f"requested={_symbol_names(requested_set)}, "
            f"current={_symbol_names(current)}"
        )
    if len(valid) != 1:
        raise SymbolicStateRepresentationError(
            "function.state_representation_ambiguous: "
            f"requested={_symbol_names(requested_set)}, "
            f"branch_count={len(valid)}"
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


def _normalized_relations(
    relations: Iterable[sp.Equality],
) -> list[sp.Equality]:
    result: list[sp.Equality] = []
    for relation in relations:
        if relation is sp.S.true:
            continue
        if relation is sp.S.false:
            raise SymbolicStateRepresentationError(
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
    "SymbolicStateRepresentationError",
    "SymbolicStateRepresentationProof",
    "project_symbolic_state_representation",
]
