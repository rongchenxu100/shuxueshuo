"""Typed Symbol identity at the Functional runtime observation boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import sympy as sp

from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
)
from shuxueshuo_server.solver.utils import unique_ordered


def symbol_ids_from_refs(
    refs: Sequence[str],
    *,
    registry: MathObjectRegistry,
) -> tuple[MathObjectId, ...]:
    """Resolve static Symbol refs without preserving strings as authority."""

    result: list[MathObjectId] = []
    for ref in refs:
        object_id = registry.resolve(ref) or registry.register_handle(ref)
        if object_id is None or object_id.kind != "symbol":
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"symbol_ref={ref}"
            )
        result.append(object_id)
    return tuple(unique_ordered(result))


def runtime_free_symbol_ids(
    value: Any,
    *,
    context: RuntimeContext,
    registry: MathObjectRegistry,
    declared_runtime_symbols: Mapping[sp.Symbol, MathObjectId] | None = None,
) -> tuple[MathObjectId, ...]:
    """Resolve actual SymPy Symbols through RuntimeContext object identity."""

    return _runtime_symbol_ids(
        runtime_free_symbols(value),
        context=context,
        registry=registry,
        declared_runtime_symbols=declared_runtime_symbols or {},
    )


def runtime_symbol_ids_from_names(
    names: Sequence[str],
    *,
    context: RuntimeContext,
    registry: MathObjectRegistry,
) -> tuple[MathObjectId, ...]:
    """Resolve compatibility symbol names at the runtime boundary only."""

    symbols: list[sp.Symbol] = []
    for name in names:
        symbol = context.symbols.get(name)
        if symbol is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={name}"
            )
        symbols.append(symbol)
    return _runtime_symbol_ids(
        symbols,
        context=context,
        registry=registry,
        declared_runtime_symbols={},
    )


def _runtime_symbol_ids(
    symbols: Sequence[sp.Symbol],
    *,
    context: RuntimeContext,
    registry: MathObjectRegistry,
    declared_runtime_symbols: Mapping[sp.Symbol, MathObjectId],
) -> tuple[MathObjectId, ...]:
    result: list[MathObjectId] = []
    for symbol in symbols:
        declared = declared_runtime_symbols.get(symbol)
        if declared is not None:
            if declared.kind != "symbol":
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_symbol_identity_unresolved: "
                    f"runtime_symbol={symbol}, declared_kind={declared.kind}"
                )
            result.append(declared)
            continue
        names = tuple(
            name
            for name, candidate in context.symbols.items()
            if candidate is symbol
        )
        if not names:
            names = tuple(
                name
                for name, candidate in context.symbols.items()
                if candidate == symbol
            )
        if len(names) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={symbol}, candidates={list(names)}"
            )
        object_id = registry.resolve(names[0])
        if object_id is None or object_id.kind != "symbol":
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_symbol_identity_unresolved: "
                f"runtime_symbol={symbol}"
            )
        result.append(object_id)
    return tuple(unique_ordered(result))


def runtime_free_symbols(value: Any) -> tuple[sp.Symbol, ...]:
    symbols: set[sp.Symbol] = {
        item
        for item in getattr(value, "free_symbols", set())
        if isinstance(item, sp.Symbol)
    }
    if isinstance(value, Mapping):
        for item in value.values():
            symbols.update(runtime_free_symbols(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            symbols.update(runtime_free_symbols(item))
    return tuple(sorted(symbols, key=lambda item: item.sort_key()))


__all__ = [
    "runtime_free_symbol_ids",
    "runtime_free_symbols",
    "runtime_symbol_ids_from_names",
    "symbol_ids_from_refs",
]
