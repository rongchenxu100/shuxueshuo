"""Shared extraction and propagation helpers for unresolved Symbol identity."""

from __future__ import annotations

from typing import Any, Mapping

import sympy as sp

from shuxueshuo_server.solver.state_semantics import is_object_handle
from shuxueshuo_server.solver.utils import unique_ordered


def symbol_handles_by_name(
    entity_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    """Index declared Symbol objects by their expression-level names."""
    return {
        str(payload.get("name") or handle.rsplit(":", 1)[-1]): handle
        for handle, payload in entity_payloads.items()
        if payload.get("entity_type") == "symbol"
    }


def structured_free_symbol_refs(
    payload: Mapping[str, Any],
    *,
    symbol_handles: Mapping[str, str],
) -> tuple[str, ...]:
    """Extract free Symbol object refs from structured value-bearing fields."""
    values = [
        payload[key]
        for key in ("coordinate", "coordinates", "value")
        if key in payload
    ]
    local_symbols = {name: sp.Symbol(name) for name in symbol_handles}
    refs: list[str] = []
    for value in _scalar_values(values):
        if not isinstance(value, str) or is_object_handle(value):
            continue
        try:
            expression = sp.sympify(value, locals=local_symbols)
        except (TypeError, ValueError, SyntaxError):
            continue
        refs.extend(
            symbol_handles[symbol.name]
            for symbol in expression.free_symbols
            if symbol.name in symbol_handles
        )
    return unique_ordered(refs)


def symbol_refs_from_names(
    names: tuple[str, ...],
    *,
    entity_payloads: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Map runtime free-symbol names back to canonical Symbol object refs."""
    by_name = symbol_handles_by_name(entity_payloads)
    return unique_ordered(by_name[name] for name in names if name in by_name)


def _scalar_values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _scalar_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _scalar_values(child)]
    return [value]


__all__ = [
    "structured_free_symbol_refs",
    "symbol_handles_by_name",
    "symbol_refs_from_names",
]
