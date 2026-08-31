"""Shared typed Context value lookups used during Functional reconciliation."""

from __future__ import annotations

from typing import Mapping

from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.handle_alias_index import (
    visible_from_valid_scope,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
    RuntimeStateVersionBinding,
)
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.utils import unique_ordered


def resolved_value_object_refs(
    values: tuple[ResolvedFunctionalValue, ...],
) -> tuple[str, ...]:
    return unique_ordered(
        item.object_ref
        for item in values
        if item.object_ref is not None
    )


def resolved_value_object_ids(
    values: tuple[ResolvedFunctionalValue, ...],
) -> tuple[MathObjectId, ...]:
    return tuple(
        dict.fromkeys(
            item.math_object_id
            for item in values
            if item.math_object_id is not None
        )
    )


def condition_value_by_handle(
    handle: str,
    *,
    semantic_index: FunctionalSemanticIndex,
    scope_id: str,
) -> ResolvedFunctionalValue | None:
    candidates = tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Condition",),
        )
        if view.handle == handle
    )
    if len(candidates) != 1:
        return None
    item = candidates[0]
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


def object_identity_value(
    object_ref: str,
    *,
    domain_runtime_types: tuple[str, ...],
    scope_id: str,
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
) -> ResolvedFunctionalValue | None:
    """Return one visible MathObject identity without selecting a state version."""

    views = tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=domain_runtime_types,
        )
        if view.object_ref == object_ref
        and visible_from_valid_scope(
            view.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    object_ids = tuple(
        dict.fromkeys(
            view.math_object_id
            for view in views
            if view.math_object_id is not None
        )
    )
    if len(object_ids) != 1:
        return None
    object_id = object_ids[0]
    matching = tuple(view for view in views if view.math_object_id == object_id)
    if not matching:
        return None
    selected = min(
        matching,
        key=lambda view: (
            view.state_version_id is not None,
            view.state_slot_id is not None,
            view.handle,
        ),
    )
    return ResolvedFunctionalValue(
        handle=selected.handle,
        runtime_type=(
            "PointRef"
            if "Point" in domain_runtime_types
            or "PointRef" in domain_runtime_types
            else selected.runtime_type
        ),
        valid_scope=selected.valid_scope,
        object_ref=selected.object_ref,
        dependency_object_refs=selected.dependency_object_refs,
        free_symbol_refs=(),
        provides_semantic_roles=selected.provides_semantic_roles,
        lineage=selected.lineage,
        math_object_id=selected.math_object_id,
    )


def latest_point_state_for_object(
    object_ref: str,
    *,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    allow_unique_planned_producer: bool = False,
    allow_invisible_planned_producer: bool = False,
) -> ResolvedFunctionalValue | None:
    object_ids = tuple(
        dict.fromkeys(
            item.math_object_id
            for item in (
                *tuple(produced.values()),
                *tuple(
                    semantic_index.compatible_views(
                        scope_id=scope_id,
                        accepted_types=("Point",),
                    )
                ),
            )
            if item.object_ref == object_ref
            and item.math_object_id is not None
        )
    )
    if len(object_ids) != 1:
        if object_ids:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"object_ref={object_ref}, typed_candidates={len(object_ids)}"
            )
        return None
    object_id = object_ids[0]
    dynamic = tuple(
        value
        for value in produced.values()
        if value.runtime_type == "Point"
        and value.math_object_id == object_id
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    views = tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Point",),
        )
        if view.math_object_id == object_id
        and view.state_version_id is not None
    )
    typed_candidates: dict[object, ResolvedFunctionalValue] = {}
    for value in dynamic:
        if value.state_version_id is None:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_version_unresolved: "
                f"object_ref={object_ref}, handle={value.handle}"
            )
        typed_candidates[value.state_version_id] = value
    for view in views:
        assert view.state_version_id is not None
        typed_candidates.setdefault(
            view.state_version_id,
            ResolvedFunctionalValue(
                handle=view.handle,
                runtime_type=view.runtime_type,
                valid_scope=view.valid_scope,
                state_slot_id=view.state_slot_id,
                object_ref=view.object_ref,
                dependency_object_refs=view.dependency_object_refs,
                free_symbol_refs=view.free_symbol_refs,
                source_state_slot_ids=view.source_state_slot_ids,
                provides_semantic_roles=view.provides_semantic_roles,
                lineage=view.lineage,
                math_object_id=view.math_object_id,
                logical_state_key=view.logical_state_key,
                typed_slot_id=view.typed_slot_id,
                state_version_id=view.state_version_id,
                source_version_ids=view.source_version_ids,
            ),
        )
    if typed_candidates:
        read_index = FunctionalStateReadIndex(
            handle_registry=handle_registry,
            mode="authoritative",
        )
        for value in typed_candidates.values():
            logical_state_key = (
                value.logical_state_key
                or (
                    value.state_version_id.slot_id.logical_key
                    if value.state_version_id is not None
                    else None
                )
            )
            if (
                value.state_version_id is None
                or logical_state_key is None
                or value.math_object_id is None
            ):
                raise ValueError(
                    "planner_configuration_error: "
                    "planner.runtime_state_version_unresolved: "
                    f"object_ref={object_ref}, handle={value.handle}"
                )
            read_index.register(
                RuntimeStateVersionBinding(
                    version_id=value.state_version_id,
                    logical_state_key=logical_state_key,
                    math_object_id=value.math_object_id,
                    runtime_type=value.runtime_type or "Point",
                    valid_scope_id=value.valid_scope,
                    canonical_producer_call_id=value.source_call_id,
                    runtime_path=None,
                    produced_handle=value.handle,
                    lineage=value.lineage,
                    source_version_ids=value.source_version_ids,
                    free_symbol_refs=value.free_symbol_refs,
                )
            )
        logical_keys = {
            value.logical_state_key
            for value in typed_candidates.values()
            if value.logical_state_key is not None
        }
        if len(logical_keys) != 1:
            raise ValueError(
                "planner_configuration_error: "
                "planner.runtime_state_binding_drift: "
                f"object_ref={object_ref}, logical_state_count={len(logical_keys)}"
            )
        selected = read_index.latest_visible(
            next(iter(logical_keys)),
            consumer_scope_id=scope_id,
        )
        if selected is None:
            return None
        return typed_candidates[selected.version_id]
    if allow_unique_planned_producer:
        planned = tuple(
            value
            for value in produced.values()
            if value.runtime_type == "Point"
            and value.math_object_id == object_id
            and value.source_call_id is not None
            and (
                allow_invisible_planned_producer
                or visible_from_valid_scope(
                    value.valid_scope,
                    scope_id=scope_id,
                    registry=handle_registry,
                )
            )
        )
        producer_ids = unique_ordered(
            value.source_call_id
            for value in planned
            if value.source_call_id is not None
        )
        if len(producer_ids) == 1:
            producer_values = tuple(
                value
                for value in planned
                if value.source_call_id == producer_ids[0]
            )
            if len(producer_values) == 1:
                return producer_values[0]
    return None


def state_producer_locations_for_object(
    object_ref: str,
    *,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
) -> tuple[tuple[str, str], ...]:
    """Return known planned/runtime producer locations for diagnostics."""

    return tuple(
        sorted(
            {
                (value.source_call_id, value.valid_scope)
                for value in produced.values()
                if value.object_ref == object_ref
                and value.source_call_id is not None
                and (
                    value.state_version_id is not None
                    or value.runtime_type not in {"PointRef", "Symbol"}
                )
            }
        )
    )


__all__ = [
    "condition_value_by_handle",
    "latest_point_state_for_object",
    "object_identity_value",
    "resolved_value_object_ids",
    "resolved_value_object_refs",
    "state_producer_locations_for_object",
]
