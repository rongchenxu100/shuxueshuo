"""Shared metadata helpers for broken-path straightening outputs."""

from __future__ import annotations

from collections.abc import Iterable

STRAIGHTENED_ENDPOINT_1 = "straightened_endpoint_1"
STRAIGHTENED_ENDPOINT_2 = "straightened_endpoint_2"

# Legacy StepIntent semantic names remain readable during the FunctionalPlan
# migration. New capability contracts and FunctionalPlan payloads use the
# geometrically precise ``straightened_endpoint_*`` roles above.
STRAIGHTENING_ENDPOINT_POINT_1 = "path_minimum_point_1"
STRAIGHTENING_ENDPOINT_POINT_2 = "path_minimum_point_2"
STRAIGHTENING_ENDPOINT_NAMES: tuple[str, str] = (
    STRAIGHTENED_ENDPOINT_1,
    STRAIGHTENED_ENDPOINT_2,
)
_STRAIGHTENING_ENDPOINT_ALIASES = {
    STRAIGHTENED_ENDPOINT_1: STRAIGHTENED_ENDPOINT_1,
    STRAIGHTENED_ENDPOINT_2: STRAIGHTENED_ENDPOINT_2,
    "straightening_endpoint_1": STRAIGHTENED_ENDPOINT_1,
    "straightening_endpoint_2": STRAIGHTENED_ENDPOINT_2,
    STRAIGHTENING_ENDPOINT_POINT_1: STRAIGHTENED_ENDPOINT_1,
    STRAIGHTENING_ENDPOINT_POINT_2: STRAIGHTENED_ENDPOINT_2,
}


def collect_straightening_endpoint_handles(
    candidates: Iterable[tuple[str, str]],
) -> tuple[str, str] | None:
    """Collect unique straightened-segment endpoints by canonical role."""
    by_name: dict[str, list[str]] = {name: [] for name in STRAIGHTENING_ENDPOINT_NAMES}
    for semantic_name, handle in candidates:
        canonical_name = canonical_straightening_endpoint_name(semantic_name)
        if canonical_name is None:
            continue
        by_name[canonical_name].append(handle)
    point_1 = _unique_ordered(by_name[STRAIGHTENED_ENDPOINT_1])
    point_2 = _unique_ordered(by_name[STRAIGHTENED_ENDPOINT_2])
    if len(point_1) == 1 and len(point_2) == 1:
        return point_1[0], point_2[0]
    return None


def is_straightening_endpoint_name(semantic_name: str) -> bool:
    """Return whether a semantic name denotes a straightening endpoint."""
    return canonical_straightening_endpoint_name(semantic_name) is not None


def canonical_straightening_endpoint_name(
    semantic_name: str,
) -> str | None:
    """Map legacy and current endpoint roles to the public canonical role."""
    return _STRAIGHTENING_ENDPOINT_ALIASES.get(semantic_name)


def straightening_endpoint_position(semantic_name: str) -> int | None:
    """Return the one-based endpoint position for a supported semantic role."""
    canonical = canonical_straightening_endpoint_name(semantic_name)
    if canonical == STRAIGHTENED_ENDPOINT_1:
        return 1
    if canonical == STRAIGHTENED_ENDPOINT_2:
        return 2
    return None


def _unique_ordered(items: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
