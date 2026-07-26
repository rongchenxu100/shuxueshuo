"""Context-closure resolver for structured construction conditions."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.runtime.condition_roles import (
    ConditionRoleResolutionError,
    ConditionRoleResolver,
)
from shuxueshuo_server.solver.runtime.context_closure import (
    ContextClosureResolverSpec,
)
from shuxueshuo_server.solver.runtime.functional_context_values import (
    latest_point_state_for_object,
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
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.utils import unique_ordered


ContextClosureResolution = tuple[
    dict[str, tuple[ResolvedFunctionalValue, ...]],
    tuple[FunctionalDeterministicRepair, ...],
    tuple[FunctionalPlanIssue, ...],
    bool,
]


def resolve_condition_role_args(
    capability: FunctionalCapability,
    call: FunctionalCall,
    resolved_args: Mapping[str, tuple[ResolvedFunctionalValue, ...]],
    resolver: ContextClosureResolverSpec,
    *,
    call_id: str,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> ContextClosureResolution:
    """Expand a structured Condition into complete internal macro inputs."""

    conditions = tuple(
        value
        for values in resolved_args.values()
        for value in values
        if value.runtime_type == "Condition"
        and value.object_roles
        and ConditionRoleResolver.supports(
            handle_registry.fact_types.get(value.handle, "")
        )
    )
    if not conditions:
        return {}, (), (), False
    if len(conditions) != 1:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    "functional.condition_role_ambiguous",
                    "multiple structured Conditions require role expansion",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={"conditions": [item.handle for item in conditions]},
                ),
            ),
            False,
        )
    condition = conditions[0]
    target_hints = _condition_target_hints(
        call,
        scope_id=scope_id,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
        explicit_values=resolved_args.get(
            resolver.arg_name(
                "target",
                capability.context_arg_bindings,
            ),
            (),
        ),
    )
    endpoints = dict(condition.object_roles).get("endpoint", ())
    target_hints = unique_ordered(
        (
            *target_hints,
            *(
                endpoint
                for endpoint in endpoints
                if _condition_views_for_subject(
                    semantic_index,
                    condition_kind="orientation_constraint",
                    subject=endpoint,
                    scope_id=scope_id,
                )
            ),
        )
    )
    materialized_points = unique_ordered(
        (
            *(
                value.object_ref
                for value in produced.values()
                if value.runtime_type == "Point"
                and value.object_ref is not None
                and visible_from_valid_scope(
                    value.valid_scope,
                    scope_id=scope_id,
                    registry=handle_registry,
                )
            ),
            *(
                view.object_ref
                for view in semantic_index.compatible_views(
                    scope_id=scope_id,
                    accepted_types=("Point",),
                )
                if view.state_slot_id is not None
                and view.object_ref is not None
            ),
        )
    )
    try:
        roles = ConditionRoleResolver.resolve_constructed_point_roles(
            condition.object_roles,
            target_hints=target_hints,
            materialized_points=materialized_points,
        )
    except ConditionRoleResolutionError as exc:
        return (
            {},
            (),
            (
                _issue(
                    "functional_elaboration",
                    f"functional.{exc.code}",
                    str(exc),
                    call_id=call_id,
                    scope_id=scope_id,
                    details=exc.details,
                ),
            ),
            False,
        )

    additions: dict[str, tuple[ResolvedFunctionalValue, ...]] = {}
    issues: list[FunctionalPlanIssue] = []
    anchor = latest_point_state_for_object(
        roles.anchor,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    reference = latest_point_state_for_object(
        roles.reference,
        scope_id=scope_id,
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=handle_registry,
    )
    for role_name, object_ref, value in (
        ("anchor", roles.anchor, anchor),
        ("reference", roles.reference, reference),
    ):
        if not _resolver_role_is_used(capability, resolver, role_name):
            continue
        if value is None:
            issues.append(
                _issue(
                    "functional_elaboration",
                    "functional.condition_role_state_unavailable",
                    f"condition role {role_name} requires a computed Point state",
                    call_id=call_id,
                    scope_id=scope_id,
                    details={
                        "role": role_name,
                        "object_ref": object_ref,
                        "accepted_item_types": ["Point"],
                    },
                )
            )
        else:
            additions[
                resolver.arg_name(role_name, capability.context_arg_bindings)
            ] = (value,)
    if _resolver_role_is_used(capability, resolver, "target"):
        additions[
            resolver.arg_name("target", capability.context_arg_bindings)
        ] = (
            ResolvedFunctionalValue(
                handle=roles.target,
                runtime_type="PointRef",
                valid_scope=handle_registry.handle_valid_scopes.get(
                    roles.target,
                    scope_id,
                ),
                object_ref=roles.target,
                dependency_object_refs=(roles.target,),
            ),
        )

    if _resolver_role_is_used(capability, resolver, "orientation"):
        orientation = _unique_condition_value(
            _condition_views_for_subject(
                semantic_index,
                condition_kind="orientation_constraint",
                subject=roles.target,
                scope_id=scope_id,
            ),
            role="orientation",
            call_id=call_id,
            scope_id=scope_id,
            issues=issues,
        )
        if orientation is not None:
            additions[
                resolver.arg_name(
                    "orientation",
                    capability.context_arg_bindings,
                )
            ] = (orientation,)

    symbol_refs = unique_ordered(
        dependency
        for value in (reference,)
        if value is not None
        for dependency in value.free_symbol_refs
        if dependency.startswith("symbol:")
    )
    needs_parameter = _resolver_role_is_used(
        capability,
        resolver,
        "parameter",
    )
    parameter = None
    if needs_parameter and len(symbol_refs) != 1:
        issues.append(
            _issue(
                "functional_elaboration",
                (
                    "functional.condition_parameter_unresolved"
                    if not symbol_refs
                    else "functional.condition_parameter_ambiguous"
                ),
                "condition selection requires one parameter Symbol",
                call_id=call_id,
                scope_id=scope_id,
                details={"symbol_candidates": list(symbol_refs)},
            )
        )
    elif needs_parameter:
        parameter_handle = symbol_refs[0]
        parameter = ResolvedFunctionalValue(
            handle=parameter_handle,
            runtime_type="Symbol",
            valid_scope=handle_registry.handle_valid_scopes.get(
                parameter_handle,
                scope_id,
            ),
            object_ref=parameter_handle,
            dependency_object_refs=(parameter_handle,),
            free_symbol_refs=(parameter_handle,),
        )
        additions[
            resolver.arg_name("parameter", capability.context_arg_bindings)
        ] = (parameter,)

    if parameter is not None and _resolver_role_is_used(
        capability,
        resolver,
        "parameter_constraint",
    ):
        parameter_constraint = _unique_condition_value(
            _condition_views_for_subject(
                semantic_index,
                condition_kind="symbol_constraint",
                subject=parameter.object_ref or parameter.handle,
                scope_id=scope_id,
            ),
            role="parameter_constraint",
            call_id=call_id,
            scope_id=scope_id,
            issues=issues,
        )
        if parameter_constraint is not None:
            additions[
                resolver.arg_name(
                    "parameter_constraint",
                    capability.context_arg_bindings,
                )
            ] = (parameter_constraint,)

    if issues:
        return additions, (), tuple(issues), False
    return (
        additions,
        (
            FunctionalDeterministicRepair(
                call_id,
                "expand_condition_object_roles",
                condition.handle,
                ",".join(
                    (
                        f"anchor={roles.anchor}",
                        f"reference={roles.reference}",
                        f"target={roles.target}",
                    )
                ),
            ),
        ),
        (),
        True,
    )


def _resolver_role_is_used(
    capability: FunctionalCapability,
    resolver: ContextClosureResolverSpec,
    semantic_role: str,
) -> bool:
    return resolver.arg_name_or_none(
        semantic_role,
        capability.context_arg_bindings,
    ) is not None


def _condition_target_hints(
    call: FunctionalCall,
    *,
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    explicit_values: tuple[ResolvedFunctionalValue, ...] = (),
) -> tuple[str, ...]:
    result: list[str] = [
        value.object_ref
        for value in explicit_values
        if value.object_ref is not None
    ]
    for binding in call.return_bindings.values():
        result.extend(
            semantic_index.object_refs_for(binding, scope_id=scope_id)
        )
        if binding.kind == "answer":
            target = handle_registry.answer_target_handles.get(
                f"answer:{binding.ref}"
            )
            if target is not None:
                result.append(target)
    return unique_ordered(result)


def _condition_views_for_subject(
    semantic_index: FunctionalSemanticIndex,
    *,
    condition_kind: str,
    subject: str,
    scope_id: str,
) -> tuple[Any, ...]:
    return tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Condition",),
            accepted_condition_kinds=(condition_kind,),
        )
        if semantic_index.handle_registry.fact_payloads.get(
            view.handle,
            {},
        ).get("subject")
        == subject
    )


def _unique_condition_value(
    candidates: Sequence[Any],
    *,
    role: str,
    call_id: str,
    scope_id: str,
    issues: list[FunctionalPlanIssue],
) -> ResolvedFunctionalValue | None:
    unique = {item.handle: item for item in candidates}
    if len(unique) != 1:
        issues.append(
            _issue(
                "functional_elaboration",
                (
                    "functional.condition_role_condition_missing"
                    if not unique
                    else "functional.condition_role_condition_ambiguous"
                ),
                f"condition role {role} requires one matching Condition",
                call_id=call_id,
                scope_id=scope_id,
                details={
                    "role": role,
                    "condition_candidates": sorted(unique),
                },
            )
        )
        return None
    item = next(iter(unique.values()))
    return ResolvedFunctionalValue(
        handle=item.handle,
        runtime_type="Condition",
        valid_scope=item.valid_scope,
        condition_id=item.condition_id,
        object_roles=item.object_roles,
        dependency_object_refs=item.dependency_object_refs,
        free_symbol_refs=item.free_symbol_refs,
        source_state_slot_ids=item.source_state_slot_ids,
        provides_semantic_roles=item.provides_semantic_roles,
        lineage=item.lineage,
    )


__all__ = ["ContextClosureResolution", "resolve_condition_role_args"]
