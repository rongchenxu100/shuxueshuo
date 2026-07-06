"""Small shared helpers for solver modules."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar


T = TypeVar("T")


def unique_ordered(values: Iterable[T]) -> tuple[T, ...]:
    """Return first-seen unique values while preserving stable order."""
    seen: set[T] = set()
    result: list[T] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


__all__ = ["unique_ordered"]
