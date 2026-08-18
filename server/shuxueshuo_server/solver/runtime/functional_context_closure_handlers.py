"""Executable registry for Functional Context-closure resolvers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Mapping

from shuxueshuo_server.solver.family.models import CapabilityContextResolver
from shuxueshuo_server.solver.runtime.context_closure import (
    CONDITION_OBJECT_ROLES_RESOLVER,
    EQUAL_LENGTH_RAY_PATH_ROLES_RESOLVER,
    PATH_REDUCTION_ROLES_RESOLVER,
    SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER,
    WEIGHTED_PATH_TRANSFORMATION_ROLES_RESOLVER,
    context_closure_resolver,
    context_closure_resolver_ids,
)
from shuxueshuo_server.solver.runtime.functional_condition_context_resolvers import (
    ContextClosureResolution,
    resolve_condition_role_args,
)
from shuxueshuo_server.solver.runtime.functional_context_values import (
    resolved_value_object_refs,
)
from shuxueshuo_server.solver.runtime.functional_path_context_resolvers import (
    resolve_equal_length_ray_path_args,
    resolve_path_reduction_args,
    resolve_square_path_transformation_args,
    resolve_weighted_path_transformation_args,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalDeterministicRepair,
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCapability,
    FunctionalPlanIssue,
    ResolvedFunctionalValue,
    _issue,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)


ContextClosureHandler = Callable[..., ContextClosureResolution]

_CONTEXT_CLOSURE_HANDLERS: Mapping[
    CapabilityContextResolver,
    ContextClosureHandler,
] = {
    CONDITION_OBJECT_ROLES_RESOLVER: resolve_condition_role_args,
    EQUAL_LENGTH_RAY_PATH_ROLES_RESOLVER: resolve_equal_length_ray_path_args,
    PATH_REDUCTION_ROLES_RESOLVER: resolve_path_reduction_args,
    SQUARE_PATH_TRANSFORMATION_ROLES_RESOLVER: (
        resolve_square_path_transformation_args
    ),
    WEIGHTED_PATH_TRANSFORMATION_ROLES_RESOLVER: (
        resolve_weighted_path_transformation_args
    ),
}


def context_closure_handler_ids() -> frozenset[CapabilityContextResolver]:
    return frozenset(_CONTEXT_CLOSURE_HANDLERS)


def validate_context_closure_handler_registry() -> None:
    """Fail during module loading when spec and executable registries drift."""

    declared = context_closure_resolver_ids()
    executable = context_closure_handler_ids()
    if declared == executable:
        return
    missing = sorted(declared - executable)
    extra = sorted(executable - declared)
    raise RuntimeError(
        "planner_configuration_error: context closure handler registry "
        f"mismatch; missing={missing}, extra={extra}"
    )


def resolve_context_closure_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    bool,
]:
    """Run the complete executable registry declared by the capability."""

    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    repairs: list[FunctionalDeterministicRepair] = []
    issues: list[FunctionalPlanIssue] = []
    reads_closed = False
    for resolver_id in capability.context_resolvers:
        resolver = context_closure_resolver(resolver_id)
        handler = _CONTEXT_CLOSURE_HANDLERS[resolver_id]
        resolved, current_repairs, current_issues, closed = handler(
            capability,
            call,
            {**resolved_args, **additions},
            resolver,
            call_id=call_id,
            scope_id=scope_id,
            produced=produced,
            semantic_index=semantic_index,
            handle_registry=handle_registry,
        )
        for arg_name, values in resolved.items():
            previous = additions.get(arg_name) or resolved_args.get(arg_name)
            if (
                previous is not None
                and previous != values
                and not _same_context_object_values(previous, values)
            ):
                if _is_runtime_search_role(capability, arg_name):
                    additions[arg_name] = values
                    continue
                issues.append(
                    _issue(
                        "functional_reconciliation",
                        "functional.context_resolver_conflict",
                        (
                            "wire argument conflicts with the object role "
                            f"resolved from structured Context: {arg_name}"
                        ),
                        call_id=call_id,
                        scope_id=scope_id,
                        details={
                            "arg": arg_name,
                            "wire_object_refs": list(
                                resolved_value_object_refs(previous)
                            ),
                            "resolved_object_refs": list(
                                resolved_value_object_refs(values)
                            ),
                        },
                    )
                )
                continue
            additions[arg_name] = values
        repairs.extend(current_repairs)
        issues.extend(current_issues)
        reads_closed = reads_closed or closed
    return additions, tuple(repairs), tuple(issues), reads_closed


def _is_runtime_search_role(
    capability: FunctionalCapability,
    arg_name: str,
) -> bool:
    source = capability.source
    search = getattr(source, "search", None)
    return (
        capability.kind == "macro"
        and getattr(source, "execution_mode", None) == "runtime_search"
        and search is not None
        and arg_name in search.searchable_roles
    )


def _same_context_object_values(
    first: tuple[ResolvedFunctionalValue, ...],
    second: tuple[ResolvedFunctionalValue, ...],
) -> bool:
    return (
        len(first) == len(second) == 1
        and first[0].object_ref is not None
        and first[0].object_ref == second[0].object_ref
    )


validate_context_closure_handler_registry()


__all__ = [
    "context_closure_handler_ids",
    "resolve_context_closure_args",
    "validate_context_closure_handler_registry",
]
