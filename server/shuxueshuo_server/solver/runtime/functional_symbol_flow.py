"""Type-driven free-Symbol propagation for pre-runtime Functional state."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalSemanticIndex,
)

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalPlan,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef
from shuxueshuo_server.solver.utils import unique_ordered


def infer_unique_target_symbol_ref(
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    candidates: tuple[str, ...],
) -> str | None:
    """Infer a solve target from structural Symbol dependency asymmetry.

    A Symbol that occurs in exactly one independently resolved input state,
    while every other candidate is shared by another state, is the only safe
    target. This distinguishes a coefficient to solve from a contextual
    parameter already carried by both a curve and a point without relying on
    method ids or symbol names.
    """
    candidate_set = set(candidates)
    symbol_sets = [
        {
            symbol
            for symbol in (
                *value.free_symbol_refs,
                *(
                    (value.object_ref,)
                    if value.runtime_type == "Symbol"
                    and value.object_ref is not None
                    else ()
                ),
            )
            if symbol in candidate_set
        }
        for values in args.values()
        for value in values
    ]
    unique_to_one_state = {
        symbol
        for index, symbols in enumerate(symbol_sets)
        for symbol in symbols - set().union(
            *(other for other_index, other in enumerate(symbol_sets) if other_index != index)
        )
    }
    return next(iter(unique_to_one_state)) if len(unique_to_one_state) == 1 else None

def return_free_symbol_refs(
    runtime_type: str,
    args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    object_ref: str | None,
    ignored_input_args: tuple[str, ...] = (),
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

    effective_args = {
        name: values
        for name, values in args.items()
        if name not in ignored_input_args
    }
    state_object_refs = {
        value.object_ref
        for values in effective_args.values()
        for value in values
        if value.runtime_type not in {"Condition", "Constraint"}
        and value.object_ref is not None
    }
    inherited = unique_ordered(
        symbol_ref
        for values in effective_args.values()
        for value in values
        if not _condition_symbols_are_covered(
            value,
            output_object_ref=object_ref,
            state_object_refs=state_object_refs,
        )
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
        for values in effective_args.values()
        for value in values
        if value.runtime_type == "ParameterValue" and value.object_ref is not None
    }
    return tuple(item for item in inherited if item not in solved)


def _condition_symbols_are_covered(
    value: ResolvedFunctionalValue,
    *,
    output_object_ref: str | None,
    state_object_refs: set[str],
) -> bool:
    """Return whether newer object states cover a Condition's old symbols."""
    if value.runtime_type not in {"Condition", "Constraint"}:
        return False
    role_object_refs = {
        object_ref
        for _role, object_refs in value.object_roles
        for object_ref in object_refs
        if object_ref != output_object_ref
    }
    return bool(role_object_refs) and role_object_refs <= state_object_refs


def _call_result_is_referenced(
    plan: FunctionalPlan,
    *,
    call_id: str,
    return_name: str,
) -> bool:
    return any(
        isinstance(ref, CallResultRef)
        and ref.from_call == call_id
        and ref.return_name == return_name
        for call in plan.calls
        for values in call.args.values()
        for ref in values
    )


def _transitive_call_dependencies(
    plan: FunctionalPlan,
) -> dict[str, tuple[str, ...]]:
    """Return prior-call dependencies, including reads of bound object refs."""
    calls = plan.calls
    call_positions = {
        call.call_id: index for index, call in enumerate(calls)
    }
    bound_producers: dict[tuple[str, str], str] = {}
    dependencies: dict[str, tuple[str, ...]] = {}
    for call in calls:
        direct: list[str] = []
        for values in call.args.values():
            for ref in values:
                if isinstance(ref, CallResultRef):
                    if call_positions.get(ref.from_call, len(calls)) < call_positions[
                        call.call_id
                    ]:
                        direct.append(ref.from_call)
                    continue
                if isinstance(ref, SemanticRef):
                    producer = bound_producers.get((ref.kind, ref.ref))
                    if producer is not None:
                        direct.append(producer)
        dependencies[call.call_id] = unique_ordered(
            (
                *direct,
                *(
                    dependency
                    for direct_call_id in direct
                    for dependency in dependencies.get(direct_call_id, ())
                ),
            )
        )
        for binding in call.return_bindings.values():
            bound_producers[(binding.kind, binding.ref)] = call.call_id
    return dependencies


def _semantic_symbol_ref(
    object_ref: str,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
) -> SemanticRef | None:
    candidates = tuple(
        view
        for view in semantic_index.views
        if view.runtime_type == "Symbol"
        and view.object_ref == object_ref
        and view.kind == "symbol"
        and view.valid_scope
        in semantic_index.handle_registry.ancestor_scopes(scope_id)
    )
    refs = unique_ordered(view.ref for view in candidates)
    return SemanticRef(ref=refs[0], kind="symbol") if len(refs) == 1 else None


__all__ = [
    "infer_unique_target_symbol_ref",
    "return_free_symbol_refs",
]
