"""Canonical grammar helpers for runtime type declarations."""

from __future__ import annotations


def split_runtime_types(runtime_type: str) -> tuple[str, ...]:
    """Split one runtime union into non-empty, normalized members."""
    return tuple(part.strip() for part in runtime_type.split("|") if part.strip())


def runtime_type_union_is_well_formed(runtime_type: str) -> bool:
    """Return whether every declared union member is present and non-empty."""
    raw_members = runtime_type.split("|")
    return bool(raw_members) and all(member.strip() for member in raw_members)


__all__ = [
    "runtime_type_union_is_well_formed",
    "split_runtime_types",
]
