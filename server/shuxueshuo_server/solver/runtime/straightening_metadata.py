"""Shared metadata helpers for broken-path straightening outputs."""

from __future__ import annotations

from collections.abc import Iterable

STRAIGHTENING_ENDPOINT_POINT_1 = "path_minimum_point_1"
STRAIGHTENING_ENDPOINT_POINT_2 = "path_minimum_point_2"
STRAIGHTENING_ENDPOINT_NAMES: tuple[str, str] = (
    STRAIGHTENING_ENDPOINT_POINT_1,
    STRAIGHTENING_ENDPOINT_POINT_2,
)


def collect_straightening_endpoint_handles(
    candidates: Iterable[tuple[str, str]],
) -> tuple[str, str] | None:
    """Collect unique path-minimum endpoint handles by semantic endpoint name."""
    by_name: dict[str, list[str]] = {name: [] for name in STRAIGHTENING_ENDPOINT_NAMES}
    for semantic_name, handle in candidates:
        if semantic_name not in by_name:
            continue
        by_name[semantic_name].append(handle)
    point_1 = _unique_ordered(by_name[STRAIGHTENING_ENDPOINT_POINT_1])
    point_2 = _unique_ordered(by_name[STRAIGHTENING_ENDPOINT_POINT_2])
    if len(point_1) == 1 and len(point_2) == 1:
        return point_1[0], point_2[0]
    return None


def is_straightening_endpoint_name(semantic_name: str) -> bool:
    """Return whether a semantic name denotes a straightening endpoint."""
    return semantic_name in STRAIGHTENING_ENDPOINT_NAMES


def _unique_ordered(items: list[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return tuple(result)
