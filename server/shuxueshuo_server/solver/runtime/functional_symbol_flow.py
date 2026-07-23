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


def align_free_parameter_basis_with_consumers(
    plan: FunctionalPlan,
    *,
    catalog: FunctionalCapabilityCatalog,
    semantic_index: FunctionalSemanticIndex,
) -> tuple[FunctionalPlan, tuple[FunctionalDeterministicRepair, ...]]:
    """Align an explicit free-symbol basis with unique downstream constraints.

    The rule is graph- and contract-driven: a producer must expose a public
    SymbolList basis argument, and every direct consumer constraint must name
    the same structured Symbol identity. Ambiguous or absent evidence leaves
    the plan unchanged for normal retry handling.
    """
    scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    replacements = {}
    repairs: list[FunctionalDeterministicRepair] = []
    for producer in plan.calls:
        capability = catalog.get(producer.capability_id)
        if capability is None:
            continue
        basis_args = tuple(
            arg
            for arg in capability.args
            if arg.aggregation == "symbol_list"
            and (arg.semantic_role or arg.name) == "free_parameters"
        )
        if len(basis_args) != 1 or "target_parameter" in producer.args:
            continue
        constrained_symbols: list[str] = []
        for consumer in plan.calls:
            if not any(
                isinstance(ref, CallResultRef)
                and ref.from_call == producer.call_id
                for values in consumer.args.values()
                for ref in values
            ):
                continue
            consumer_capability = catalog.get(consumer.capability_id)
            if consumer_capability is None:
                continue
            for arg in consumer_capability.args:
                if "symbol_constraint" not in arg.accepted_condition_kinds:
                    continue
                for ref in consumer.args.get(arg.name, ()):
                    if not isinstance(ref, SemanticRef):
                        continue
                    view, _ = semantic_index.resolve(
                        ref,
                        scope_id=scopes[consumer.call_id],
                        accepted_types=("Condition",),
                        accepted_condition_kinds=("symbol_constraint",),
                    )
                    if view is None:
                        continue
                    symbol_dependencies = unique_ordered(
                        (
                            *view.free_symbol_refs,
                            *(
                                item
                                for item in view.dependency_object_refs
                                if item.startswith("symbol:")
                            ),
                        )
                    )
                    if len(symbol_dependencies) == 1:
                        constrained_symbols.append(symbol_dependencies[0])
        symbols = unique_ordered(constrained_symbols)
        if len(symbols) != 1:
            continue
        symbol_ref = _semantic_symbol_ref(
            symbols[0],
            scope_id=scopes[producer.call_id],
            semantic_index=semantic_index,
        )
        if symbol_ref is None:
            continue
        arg_name = basis_args[0].name
        previous = producer.args.get(arg_name, ())
        replacement = (symbol_ref,)
        if previous == replacement:
            continue
        replacements[producer.call_id] = replace(
            producer,
            args={**producer.args, arg_name: replacement},
        )
        repairs.append(
            FunctionalDeterministicRepair(
                producer.call_id,
                "align_free_parameter_basis_with_downstream_constraint",
                ",".join(item.to_payload().get("ref", "") for item in previous)
                or "unspecified",
                symbol_ref.ref,
            )
        )
    if not replacements:
        return plan, ()
    return replace(
        plan,
        scopes=tuple(
            replace(
                scope,
                calls=tuple(
                    replacements.get(call.call_id, call)
                    for call in scope.calls
                ),
            )
            for scope in plan.scopes
        ),
    ), tuple(repairs)


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
    "align_free_parameter_basis_with_consumers",
    "infer_unique_target_symbol_ref",
    "return_free_symbol_refs",
]
