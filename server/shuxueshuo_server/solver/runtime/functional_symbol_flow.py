"""Type-driven free-Symbol propagation for pre-runtime Functional state."""

from __future__ import annotations

from typing import Mapping

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.utils import unique_ordered

def return_free_symbol_refs(
    runtime_type: str,
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    object_ref: str | None,
) -> tuple[str, ...]:
    """Estimate unresolved symbols in a return before runtime execution.

    Provenance lineage is deliberately excluded. A Condition contributes only
    the free symbols of the current object states it structurally references;
    merely mentioning a Symbol subject does not make that Symbol free. Runtime
    provenance later replaces this estimate with the symbols observed in the
    actual typed value.
    """
    if runtime_type == "ParameterValue":
        return ()
    if runtime_type == "Symbol":
        return (object_ref,) if object_ref and object_ref.startswith("symbol:") else ()

    inherited = unique_ordered(
        symbol_ref
        for values in args.values()
        for value in values
        for symbol_ref in (
            *value.free_symbol_refs,
            *(
                (value.object_ref,)
                if value.runtime_type == "Symbol"
                and value.object_ref is not None
                else ()
            ),
        )
    )
    solved = {
        value.object_ref
        for values in args.values()
        for value in values
        if value.runtime_type == "ParameterValue" and value.object_ref is not None
    }
    return tuple(item for item in inherited if item not in solved)


__all__ = ["return_free_symbol_refs"]
