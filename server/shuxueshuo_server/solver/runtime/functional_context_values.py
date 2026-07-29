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
from shuxueshuo_server.solver.utils import unique_ordered


def resolved_value_object_refs(
    values: tuple[ResolvedFunctionalValue, ...],
) -> tuple[str, ...]:
    return unique_ordered(
        item.object_ref
        for item in values
        if item.object_ref is not None
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


def latest_point_state_for_object(
    object_ref: str,
    *,
    scope_id: str,
    produced: Mapping[tuple[str, str], ResolvedFunctionalValue],
    semantic_index: FunctionalSemanticIndex,
    handle_registry: CanonicalHandleRegistry,
    allow_unique_planned_producer: bool = False,
) -> ResolvedFunctionalValue | None:
    dynamic = tuple(
        value
        for value in produced.values()
        if value.runtime_type == "Point"
        and value.object_ref == object_ref
        and visible_from_valid_scope(
            value.valid_scope,
            scope_id=scope_id,
            registry=handle_registry,
        )
    )
    if dynamic:
        return dynamic[-1]
    views = tuple(
        view
        for view in semantic_index.compatible_views(
            scope_id=scope_id,
            accepted_types=("Point",),
        )
        if view.object_ref == object_ref and view.state_slot_id is not None
    )
    if views:
        view = views[-1]
        return ResolvedFunctionalValue(
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
        )
    if allow_unique_planned_producer:
        planned = tuple(
            value
            for value in produced.values()
            if value.runtime_type == "Point"
            and value.object_ref == object_ref
            and value.source_call_id is not None
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


__all__ = [
    "condition_value_by_handle",
    "latest_point_state_for_object",
    "resolved_value_object_refs",
]
