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
    "least_common_scope",
    "rewrite_call_aliases",
    "rewrite_call_result_aliases",
    "wire_inputs_are_stable",
]
