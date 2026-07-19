"""Declarative registry for capability Context-closure argument expansion."""

from __future__ import annotations

from dataclasses import dataclass

from shuxueshuo_server.solver.family.models import (
    CapabilityContextResolver,
    CONDITION_OBJECT_ROLES_RESOLVER,
    PATH_REDUCTION_ROLES_RESOLVER,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalContextArgBinding,
)


@dataclass(frozen=True)
class ContextClosureResolverSpec:
    """Identify one Context closure algorithm.

    Role-to-argument bindings are projected from binding selectors into each
    FunctionalCapability; this registry intentionally stores no method input
    names.
    """

    resolver_id: CapabilityContextResolver

    def arg_name(
        self,
        semantic_role: str,
        bindings: tuple[FunctionalContextArgBinding, ...],
    ) -> str:
        result = self.arg_name_or_none(semantic_role, bindings)
        if result is None:
            raise ValueError(
                "planner_configuration_error: context resolver role missing: "
                f"{self.resolver_id}.{semantic_role}"
            )
        return result

    def arg_name_or_none(
        self,
        semantic_role: str,
        bindings: tuple[FunctionalContextArgBinding, ...],
    ) -> str | None:
        matches = tuple(
            binding.arg_name
            for binding in bindings
            if binding.resolver_id == self.resolver_id
            and binding.semantic_role == semantic_role
        )
        if len(matches) > 1:
            raise ValueError(
                "planner_configuration_error: context resolver role ambiguous: "
                f"{self.resolver_id}.{semantic_role}"
            )
        return matches[0] if matches else None


_CONTEXT_CLOSURE_RESOLVERS = {
    CONDITION_OBJECT_ROLES_RESOLVER: ContextClosureResolverSpec(
        resolver_id=CONDITION_OBJECT_ROLES_RESOLVER,
    ),
    PATH_REDUCTION_ROLES_RESOLVER: ContextClosureResolverSpec(
        resolver_id=PATH_REDUCTION_ROLES_RESOLVER,
    ),
}

_MIDPOINT_ENDPOINT_POSITIONS = {"p1": 0, "p2": 1}


def context_closure_resolver(
    resolver_id: CapabilityContextResolver,
) -> ContextClosureResolverSpec:
    try:
        return _CONTEXT_CLOSURE_RESOLVERS[resolver_id]
    except KeyError as exc:
        raise ValueError(
            "planner_configuration_error: unknown context resolver: "
            f"{resolver_id}"
        ) from exc


def validate_context_closure_resolvers(
    resolver_ids: tuple[CapabilityContextResolver, ...],
) -> None:
    for resolver_id in resolver_ids:
        context_closure_resolver(resolver_id)


def midpoint_endpoint_position(selector: str) -> int | None:
    """Project a generic ``midpoint:<role>`` selector to endpoint position."""
    if not selector.startswith("midpoint:"):
        return None
    role = selector.split(":", 1)[1]
    return _MIDPOINT_ENDPOINT_POSITIONS.get(role)


__all__ = [
    "CONDITION_OBJECT_ROLES_RESOLVER",
    "PATH_REDUCTION_ROLES_RESOLVER",
    "ContextClosureResolverSpec",
    "context_closure_resolver",
    "midpoint_endpoint_position",
    "validate_context_closure_resolvers",
]
