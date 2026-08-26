"""Canonical compatibility rules for typed Condition kinds."""

from __future__ import annotations

from collections.abc import Iterable


_CONDITION_KIND_GROUPS = (
    frozenset(
        ("length_squared", "segment_length_relation", "segment_relation")
    ),
    frozenset(("point_on_segment", "segment_membership")),
    frozenset(("dynamic_constraint", "symbol_constraint")),
)


def compatible_condition_kinds(condition_kind: str) -> tuple[str, ...]:
    """Return the stable public/runtime aliases for one Condition kind."""

    for group in _CONDITION_KIND_GROUPS:
        if condition_kind in group:
            return tuple(sorted(group))
    return (condition_kind,)


def expand_condition_kinds(condition_kinds: Iterable[str]) -> tuple[str, ...]:
    """Expand declared kinds without changing their deterministic order."""

    result: list[str] = []
    for condition_kind in condition_kinds:
        for compatible in compatible_condition_kinds(condition_kind):
            if compatible not in result:
                result.append(compatible)
    return tuple(result)


def condition_kind_matches(
    actual: str | None,
    accepted: Iterable[str],
) -> bool:
    """Whether one runtime kind satisfies the declared public kind set."""

    if actual is None:
        return False
    return actual in expand_condition_kinds(accepted)


__all__ = [
    "compatible_condition_kinds",
    "condition_kind_matches",
    "expand_condition_kinds",
]
