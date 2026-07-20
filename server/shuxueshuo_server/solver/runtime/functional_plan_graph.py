"""Shared graph primitives for FunctionalPlan elaboration and placement."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCapability,
    FunctionalCall,
    FunctionalPlan,
    SemanticRef,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)


def wire_inputs_are_stable(
    call: FunctionalCall,
    capability: FunctionalCapability,
) -> bool:
    """Return whether wire arguments alone identify a shareable computation."""
    if capability.dependency_policy == "context_closure":
        return False
    return all(
        isinstance(ref, CallResultRef)
        or (isinstance(ref, SemanticRef) and ref.kind == "fact")
        for values in call.args.values()
        for ref in values
    )


def functional_call_dependencies(
    plan: FunctionalPlan,
) -> dict[str, tuple[str, ...]]:
    """Return declared prior-call dependencies without resolving semantics."""
    known_call_ids = {call.call_id for call in plan.calls}
    return {
        call.call_id: tuple(
            dict.fromkeys(
                value.from_call
                for values in call.args.values()
                for value in values
                if isinstance(value, CallResultRef)
                and value.from_call in known_call_ids
            )
        )
        for call in plan.calls
    }


def topological_scoped_calls(
    plan: FunctionalPlan,
) -> tuple[tuple[tuple[str, str, FunctionalCall], ...], tuple[str, ...]]:
    """Return calls in stable dependency order plus any cyclic call ids.

    Functional wire scopes are presentation ownership, not execution order. A
    model may therefore place a consumer before its producer in the serialized
    scope list. Stable Kahn ordering makes that representation deterministic;
    only an actual cycle remains an LLM-facing graph error.
    """
    scoped_calls = tuple(
        (scope.scope_id, scope.label, call)
        for scope in plan.scopes
        for call in scope.calls
    )
    original_position = {
        call.call_id: index for index, (_, _, call) in enumerate(scoped_calls)
    }
    dependencies = functional_call_dependencies(plan)
    pending = {call.call_id for _, _, call in scoped_calls}
    ordered_ids: list[str] = []
    while pending:
        ready = min(
            (
                call_id
                for call_id in pending
                if not (set(dependencies.get(call_id, ())) & pending)
            ),
            key=original_position.__getitem__,
            default=None,
        )
        if not ready:
            break
        ordered_ids.append(ready)
        pending.remove(ready)
    cyclic_ids = tuple(sorted(pending, key=original_position.__getitem__))
    ordered_ids.extend(cyclic_ids)
    by_id = {call.call_id: item for item in scoped_calls for call in (item[2],)}
    return tuple(by_id[call_id] for call_id in ordered_ids), cyclic_ids


def topologically_order_plan(
    plan: FunctionalPlan,
) -> tuple[FunctionalPlan, tuple[str, ...], tuple[str, ...]]:
    """Stably reorder wire calls where the existing scope shape permits it."""
    ordered, cyclic_ids = topological_scoped_calls(plan)
    rank = {call.call_id: index for index, (_, _, call) in enumerate(ordered)}
    original_rank = {
        call.call_id: index for index, call in enumerate(plan.calls)
    }
    moved = tuple(
        call_id
        for call_id, index in rank.items()
        if index != original_rank[call_id]
    )
    scopes = tuple(
        replace(
            scope,
            calls=tuple(sorted(scope.calls, key=lambda call: rank[call.call_id])),
        )
        for scope in plan.scopes
    )
    scopes = tuple(
        sorted(
            scopes,
            key=lambda scope: min(
                (rank[call.call_id] for call in scope.calls),
                default=len(rank),
            ),
        )
    )
    return replace(plan, scopes=scopes), moved, cyclic_ids


def least_common_scope(
    scopes: Sequence[str],
    registry: CanonicalHandleRegistry,
) -> str:
    """Return the nearest scope visible to every supplied scope."""
    if not scopes:
        return "problem"
    chains = [registry.ancestor_scopes(scope) for scope in scopes]
    return next(
        scope for scope in chains[0] if all(scope in chain for chain in chains[1:])
    )


def canonical_call_id(call_id: str, aliases: Mapping[str, str]) -> str:
    """Resolve a possibly chained call alias without looping on malformed data."""
    seen: set[str] = set()
    while call_id in aliases and call_id not in seen:
        seen.add(call_id)
        call_id = aliases[call_id]
    return call_id


def canonical_call_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    return {
        alias: canonical_call_id(canonical, aliases)
        for alias, canonical in aliases.items()
    }


def rewrite_call_result_aliases(
    call: FunctionalCall,
    aliases: Mapping[str, str],
) -> FunctionalCall:
    """Rewrite every prior-call reference to its canonical call id."""
    if not aliases:
        return call
    return replace(
        call,
        args={
            name: tuple(
                replace(
                    value,
                    from_call=canonical_call_id(value.from_call, aliases),
                )
                if isinstance(value, CallResultRef)
                else value
                for value in values
            )
            for name, values in call.args.items()
        },
    )


def rewrite_call_aliases(
    plan: FunctionalPlan,
    aliases: Mapping[str, str],
    *,
    drop_alias_calls: bool = True,
) -> FunctionalPlan:
    """Canonicalize call references and optionally remove alias call nodes."""
    if not aliases:
        return plan
    return replace(
        plan,
        scopes=tuple(
            replace(
                scope,
                calls=tuple(
                    rewrite_call_result_aliases(call, aliases)
                    for call in scope.calls
                    if not drop_alias_calls or call.call_id not in aliases
                ),
            )
            for scope in plan.scopes
        ),
    )


__all__ = [
    "canonical_call_aliases",
    "canonical_call_id",
    "functional_call_dependencies",
    "least_common_scope",
    "rewrite_call_aliases",
    "rewrite_call_result_aliases",
    "topological_scoped_calls",
    "topologically_order_plan",
    "wire_inputs_are_stable",
]
