"""Shared structured-object dependency extraction for planner Context layers."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.state_semantics import is_object_handle

_TEXT_FIELDS = frozenset(
    {"description", "title", "label", "strategy", "reason"}
)


def structured_object_refs(value: Any) -> list[str]:
    """Collect canonical object handles from structured payload fields."""
    if isinstance(value, str):
        return [value] if is_object_handle(value) else []
    if isinstance(value, list):
        return [
            item
            for child in value
            for item in structured_object_refs(child)
        ]
    if isinstance(value, dict):
        return [
            item
            for key, child in value.items()
            if key not in _TEXT_FIELDS
            for item in structured_object_refs(child)
        ]
    return []


def expand_object_dependencies(
    object_refs: Sequence[str],
    dependencies_by_object: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return a stable breadth-first transitive object dependency closure."""
    result: list[str] = []
    pending = list(object_refs)
    seen: set[str] = set()
    while pending:
        object_ref = pending.pop(0)
        if object_ref in seen:
            continue
        seen.add(object_ref)
        result.append(object_ref)
        pending.extend(dependencies_by_object.get(object_ref, ()))
    return result


__all__ = ["expand_object_dependencies", "structured_object_refs"]
