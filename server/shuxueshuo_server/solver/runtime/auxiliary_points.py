"""Shared auxiliary point naming helpers."""

from __future__ import annotations

from collections.abc import Iterable

AUXILIARY_POINT_PREFIX = "Aux"
AUXILIARY_POINT_SEARCH_LIMIT = 20


def fresh_auxiliary_point_handle(
    scope_id: str,
    used_handles: Iterable[str],
    *,
    prefix: str = AUXILIARY_POINT_PREFIX,
    limit: int = AUXILIARY_POINT_SEARCH_LIMIT,
) -> str | None:
    """Return the first available auxiliary point handle in ``scope_id``."""
    used = set(used_handles)
    for suffix in ("", *[str(number) for number in range(1, limit)]):
        handle = f"point:{scope_id}:{prefix}{suffix}"
        if handle not in used:
            return handle
    return None
