"""Teaching-facing symbolic complexity over typed Symbol identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping

from shuxueshuo_server.solver.utils import unique_ordered


StudentSymbolicComplexityStatus = Literal[
    "closed",
    "single_degree_of_freedom",
    "reducible_multi_symbol",
    "irreducible_multi_symbol",
]


@dataclass(frozen=True)
class StudentSymbolicComplexity:
    """Classify unresolved Symbol identities after known substitutions."""

    status: StudentSymbolicComplexityStatus
    original_symbol_refs: tuple[str, ...]
    residual_symbol_refs: tuple[str, ...]
    resolved_symbol_refs: tuple[str, ...] = ()
    target_symbol_ref: str | None = None

    @property
    def student_ready(self) -> bool:
        return self.status != "irreducible_multi_symbol"


def analyze_student_symbolic_complexity(
    free_symbol_refs: Iterable[str],
    *,
    target_symbol_ref: str | None,
    resolved_symbol_refs: Iterable[str] = (),
) -> StudentSymbolicComplexity:
    """Measure student-facing degrees of freedom without parsing prose.

    A matching ``ParameterValue`` closes only its own Symbol identity. This
    deliberately permits a Point or expression to advance one Symbol at a
    time while requiring parameter-solving calls to consume a state with at
    most one unresolved identity.
    """
    original = unique_ordered(free_symbol_refs)
    resolved = unique_ordered(resolved_symbol_refs)
    resolved_set = set(resolved)
    residual = tuple(item for item in original if item not in resolved_set)
    if not residual:
        status: StudentSymbolicComplexityStatus = "closed"
    elif len(residual) == 1:
        status = (
            "reducible_multi_symbol"
            if len(original) > 1
            else "single_degree_of_freedom"
        )
    else:
        status = "irreducible_multi_symbol"
    return StudentSymbolicComplexity(
        status=status,
        original_symbol_refs=original,
        residual_symbol_refs=residual,
        resolved_symbol_refs=resolved,
        target_symbol_ref=target_symbol_ref,
    )


def runtime_free_symbol_names(value: Any) -> tuple[str, ...]:
    """Extract free Symbol names from a runtime scalar or structured value."""
    symbols: set[Any] = set(getattr(value, "free_symbols", set()))
    if isinstance(value, Mapping):
        for item in value.values():
            symbols.update(runtime_free_symbol_names(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            symbols.update(runtime_free_symbol_names(item))
    return tuple(sorted({str(item) for item in symbols}))


__all__ = [
    "StudentSymbolicComplexity",
    "StudentSymbolicComplexityStatus",
    "analyze_student_symbolic_complexity",
    "runtime_free_symbol_names",
]
