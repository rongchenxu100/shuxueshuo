from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import inspect
import textwrap

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalReturnAllocation,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.family.models import (
    StateObjectRoleProjectionSpec,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    _materialize_functional_return,
)
from shuxueshuo_server.solver.runtime.functional_state_allocation import (
    functional_computation_key,
    functional_source_version_ids,
)
from shuxueshuo_server.solver.runtime.functional_call_placement import (
    _canonical_dependency_graph,
    _project_placed_calls,
    _reproject_final_return_object_roles,
)
from shuxueshuo_server.solver.runtime.entity_state_resolver import (
    EntityStateResolver,
)
from shuxueshuo_server.solver.runtime.functional_debug_aliases import (
    functional_state_slot_debug_alias,
)
from shuxueshuo_server.solver.runtime.legacy_context_migration import (
    LegacyContextIdentityMigrator,
)
from shuxueshuo_server.solver.runtime.functional_typed_identity import (
    FunctionalTypedIdentityValidator,
    _legacy_sources_are_fully_typed,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    MathObject,
    StateSlot,
    StateWriteVersion,
    _attach_typed_initial_identity,
)
from shuxueshuo_server.solver.runtime.path_transformation_state import (
    PathTransformationStateResolver,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    _required_path_role_point_input,
    _previous_state_write,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    AmbiguousMathObjectReferenceError,
    ArgVersionBinding,
    ComputationKey,
    FunctionalCallIdentityKey,
    IndexedStateVersion,
    LogicalReturnEffect,
    LogicalStateKey,
    MathObjectId,
    MathObjectRegistry,
    RuntimeDestinationKey,
    ScopeVisibilityResolver,
    StateAllocationRequest,
    StateAllocationService,
    StateEffectKey,
    StateIdentityFactory,
    StateIdentityIndex,
    StateSlotId,
    StateVersionId,
    StateVersionPlacementRewrite,
    TypedCallPlacementDecision,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationService,
    build_functional_state_dependencies,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateWrite,
    StateWriteProvenance,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    state_semantic_lineage,
    state_semantic_lineage_from_payload,
)


class _Registry:
    entity_handles = {
        "point:problem:D",
        "point:ii_1:P",
        "point:ii_2:P",
        "function:problem:f",
    }
    answer_target_handles = {
        "answer:i.D": "point:problem:D",
    }

    _parents = {
        "problem": None,
        "i": "problem",
        "ii": "problem",
        "ii_1": "ii",
        "ii_2": "ii",
    }

    def ancestor_scopes(self, scope_id: str) -> tuple[str, ...]:
        result: list[str] = []
        current: str | None = scope_id
        while current is not None:
            result.append(current)
            current = self._parents[current]
        return tuple(result)


@dataclass(frozen=True)
class _Object:
    object_id: str
    kind: str
    scope_id: str
    canonical_handle: str | None
    semantic_refs: tuple[str, ...]
    math_object_id: MathObjectId | None = None


def _identity() -> tuple[
    StateIdentityFactory,
    ScopeVisibilityResolver,
    StateIdentityIndex,
]:
    registry = _Registry()
    objects = MathObjectRegistry.from_sources(
        registry,
        math_objects=(
            _Object(
                "point:D@problem",
                "point",
                "problem",
                "point:problem:D",
                ("D",),
            ),
        ),
    )
    factory = StateIdentityFactory(objects)
    visibility = ScopeVisibilityResolver(registry)
    return factory, visibility, StateIdentityIndex(visibility)


def _request(
    *,
    computation_key: ComputationKey,
    write_mode: str = "create",
    storage_scope: str = "ii",
    source_versions: tuple[StateVersionId, ...] = (),
    free_symbols: tuple[str, ...] = (),
) -> StateAllocationRequest:
    object_id = MathObjectId("point:problem:D", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    return StateAllocationRequest(
        call_id=f"call_{len(computation_key.arg_bindings)}_{storage_scope}",
        capability_id=computation_key.capability_id,
        return_name="point",
        object_id=object_id,
        state_kind="coordinate",
        runtime_type="Point",
        storage_scope_id=storage_scope,
        valid_scope_id=storage_scope,
        requested_write_mode=write_mode,
        identity_policy="target_object",
        is_shareable=True,
        computation_key=computation_key,
        state_effect_key=StateEffectKey(
            (
                LogicalReturnEffect(
                    "point",
                    logical_key,
                    "target_object",
                    write_mode,
                ),
            )
        ),
        source_version_ids=source_versions,
        free_symbol_refs=free_symbols,
        free_symbol_ids=tuple(
            MathObjectId(f"symbol:problem:{item}", "symbol", "problem")
            for item in free_symbols
        ),
        runtime_destination=RuntimeDestinationKey(
            object_id,
            "coordinate",
            "Point",
        ),
    )


def test_registry_unifies_answer_canonical_handle_and_semantic_ref() -> None:
    factory, _visibility, _index = _identity()

    canonical = factory.object_id("point:problem:D")
    assert canonical is not None
    assert factory.object_id("answer:i.D") == canonical
    assert factory.object_id("D") == canonical


def test_registry_reports_ambiguous_semantic_ref() -> None:
    registry = _Registry()
    objects = MathObjectRegistry.from_sources(
        registry,
        math_objects=(
            _Object(
                "point:P@ii_1",
                "point",
                "ii_1",
                "point:ii_1:P",
                ("P",),
            ),
            _Object(
                "point:P@ii_2",
                "point",
                "ii_2",
                "point:ii_2:P",
                ("P",),
            ),
        ),
    )

    with pytest.raises(
        AmbiguousMathObjectReferenceError,
        match="planner.math_object_identity_ambiguous",
    ):
        objects.resolve("P")


def test_context_closed_write_does_not_inherit_slot_free_symbols() -> None:
    factory, visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    typed_slot = factory.slot_id(
        logical_key,
        storage_scope_id="problem",
    )
    state_slot = StateSlot(
        slot_id="point:problem:D.coordinate@problem:Point",
        object_ref="point:problem:D",
        state_kind="coordinate",
        scope_id="problem",
        runtime_type="Point",
        canonical_handle="point:problem:D",
        valid_scope="problem",
        free_symbol_refs=("symbol:problem:m",),
        logical_state_key=logical_key,
        typed_slot_id=typed_slot,
        write_history=(
            StateWriteVersion(
                step_id="close_D",
                produced_handle="point:problem:D",
                capability_id="evaluate_point_at_parameter",
                write_mode="transition",
                free_symbol_refs=(),
            ),
        ),
    )

    index = StateIdentityIndex.from_context(
        state_slots=(state_slot,),
        factory=factory,
        visibility=visibility,
    )

    assert index.versions_for(logical_key)[0].free_symbol_refs == ()


def test_logical_state_key_separates_runtime_container_types() -> None:
    factory, _visibility, _index = _identity()

    point = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    point_list = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="PointList",
    )

    assert point != point_list


def test_legacy_slot_projection_does_not_drive_typed_index_lookup() -> None:
    factory, _visibility, index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    slot_id = factory.slot_id(logical_key, storage_scope_id="ii")
    canonical = functional_state_slot_debug_alias(slot_id)
    old_alias = factory.legacy_slot_alias(slot_id)
    initial = IndexedStateVersion(
        StateVersionId(slot_id, 0),
        valid_scope_id="ii",
        producer_call_id=None,
        produced_handle="fact:ii:D_coordinate",
    )
    index.register(initial, legacy_slot_id=old_alias)

    assert canonical.endswith("@ii:Point")
    assert old_alias.endswith("@ii")
    assert index.latest_visible(
        logical_key,
        consumer_scope_id="ii_1",
    ) == initial


def test_context_to_inflight_binding_uses_explicit_typed_version() -> None:
    factory, _visibility, index = _identity()
    service = StateAllocationService()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    slot_id = factory.slot_id(logical_key, storage_scope_id="ii")
    canonical_slot = functional_state_slot_debug_alias(slot_id)
    initial = IndexedStateVersion(
        StateVersionId(slot_id, 0),
        valid_scope_id="ii",
        producer_call_id=None,
        produced_handle="fact:ii:D_initial_coordinate",
    )
    index.register(initial, legacy_slot_id=canonical_slot)

    request = _request(
        computation_key=ComputationKey(
            "refine_point",
            (
                ArgVersionBinding(
                    "point",
                    0,
                    version_id=initial.version_id,
                ),
            ),
        ),
        write_mode="transition",
        source_versions=(initial.version_id,),
    )
    decision = service.allocate(request, index)
    assert decision.action == "transition"
    refined = service.indexed_version(
        request,
        decision,
        produced_handle="fact:ii:D_refined_coordinate",
    )
    assert refined is not None
    index.register(refined)

    resolved = ResolvedFunctionalValue(
        handle="fact:ii:D_refined_coordinate",
        runtime_type="Point",
        valid_scope="ii",
        state_slot_id=canonical_slot,
        object_ref="point:problem:D",
        math_object_id=logical_key.object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        state_version_id=refined.version_id,
    )
    source_versions = functional_source_version_ids(
        {"point": (resolved,)},
        scope_id="ii_1",
        identity_index=index,
    )
    computation_key = functional_computation_key(
        FunctionalCall(
            call_id="consume_refined_point",
            capability_id="consume_point",
            args={},
            return_bindings={},
            strategy="consume the latest state",
            reason="exercise version lookup",
        ),
        resolved_args={"point": (resolved,)},
        scope_id="ii_1",
        identity_factory=factory,
        identity_index=index,
    )

    assert source_versions == (refined.version_id,)
    assert computation_key.arg_bindings[0].version_id == refined.version_id


def test_source_versions_use_materialized_version_not_transitive_lineage() -> None:
    factory, _visibility, index = _identity()
    point_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert point_key is not None
    point_version = StateVersionId(
        factory.slot_id(point_key, storage_scope_id="ii"),
        0,
    )
    path_key = LogicalStateKey(
        MathObjectId(
            "path:ii:transformation",
            "path_transformation",
            "ii",
        ),
        "transformation",
        "PathTransformation",
    )
    path_version = StateVersionId(StateSlotId(path_key, "ii"), 1)
    resolved = ResolvedFunctionalValue(
        handle="fact:ii:path_transformation",
        runtime_type="PathTransformation",
        valid_scope="ii",
        state_version_id=path_version,
        source_version_ids=(point_version,),
    )

    assert functional_source_version_ids(
        {"path_transformation": (resolved,)},
        scope_id="ii",
        identity_index=index,
    ) == (path_version,)


def test_declared_transition_ignores_unrelated_input_versions() -> None:
    factory, _visibility, index = _identity()
    service = StateAllocationService()
    point_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    function_key = factory.logical_key(
        object_ref="function:problem:f",
        state_kind="expression",
        runtime_type="Parabola",
    )
    assert point_key is not None
    assert function_key is not None
    point_version = IndexedStateVersion(
        StateVersionId(
            factory.slot_id(point_key, storage_scope_id="ii"),
            0,
        ),
        valid_scope_id="ii",
        producer_call_id="parameterize_target",
        produced_handle=None,
    )
    unrelated_version = IndexedStateVersion(
        StateVersionId(
            factory.slot_id(function_key, storage_scope_id="ii"),
            1,
        ),
        valid_scope_id="ii",
        producer_call_id="build_curve",
        produced_handle=None,
    )
    index.register(point_version)
    index.register(unrelated_version)
    request = _request(
        computation_key=ComputationKey("recover_target", ()),
        write_mode="transition",
        source_versions=(unrelated_version.version_id,),
    )

    decision = service.allocate(request, index)

    assert decision.action == "transition"
    assert decision.previous_version_id == point_version.version_id
    assert decision.reason_code == "declared_visible_state_transition"


def test_authoritative_value_rejects_legacy_slot_without_version() -> None:
    factory, _visibility, _index = _identity()
    value = ResolvedFunctionalValue(
        handle="fact:ii:D_refined_coordinate",
        runtime_type="Point",
        valid_scope="ii",
        state_slot_id="point:problem:D.coordinate@ii:Point",
        object_ref="point:problem:D",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_identity_incomplete",
    ):
        FunctionalTypedIdentityValidator().validate_resolved_args(
            {"point": (value,)},
            call_id="consume_refined_point",
            identity_factory=factory,
        )


def test_authoritative_value_rejects_partially_typed_legacy_sources() -> None:
    factory, _visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    version_id = StateVersionId(
        factory.slot_id(logical_key, storage_scope_id="ii"),
        1,
    )
    partial = ResolvedFunctionalValue(
        handle="fact:ii:path_transformation",
        runtime_type="PathTransformation",
        valid_scope="ii",
        object_ref="point:problem:D",
        source_state_slot_ids=("legacy-slot-1", "legacy-slot-2"),
        source_version_ids=(version_id,),
        lineage=state_semantic_lineage(
            source_call_ids=("unrelated_materialized_producer",),
        ),
    )
    same_call_materialized = ResolvedFunctionalValue(
        handle="fact:ii:D_coordinate",
        runtime_type="Point",
        valid_scope="ii",
        state_slot_id="legacy-slot-2",
        object_ref="point:problem:D",
        math_object_id=logical_key.object_id,
        logical_state_key=logical_key,
        typed_slot_id=version_id.slot_id,
        state_version_id=version_id,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_dependency_version_unresolved",
    ):
        FunctionalTypedIdentityValidator().validate_resolved_args(
            {"path": (partial,), "point": (same_call_materialized,)},
            call_id="consume_path",
            identity_factory=factory,
        )


def test_call_result_cannot_cover_legacy_state_dependency() -> None:
    factory, _visibility, _index = _identity()
    value = ResolvedFunctionalValue(
        handle="functional:ii:derive_path:transformation",
        runtime_type="PathTransformation",
        valid_scope="ii",
        object_ref="point:problem:D",
        source_state_slot_ids=(
            "point:problem:D.coordinate@ii:Point",
        ),
        lineage=state_semantic_lineage(
            source_call_result_ids=("derive_point.point",),
        ),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_dependency_version_unresolved",
    ):
        FunctionalTypedIdentityValidator().validate_resolved_args(
            {"path": (value,)},
            call_id="consume_path",
            identity_factory=factory,
        )


def test_equal_count_wrong_version_does_not_cover_legacy_source() -> None:
    factory, _visibility, _index = _identity()
    function_key = factory.logical_key(
        object_ref="function:problem:f",
        state_kind="expression",
        runtime_type="Parabola",
    )
    assert function_key is not None
    wrong_version = StateVersionId(
        factory.slot_id(function_key, storage_scope_id="ii"),
        1,
    )

    assert not _legacy_sources_are_fully_typed(
        ("point:problem:D.coordinate@ii:Point",),
        (wrong_version,),
    )


def test_context_identity_hydration_rejects_missing_lineage_slot() -> None:
    slot = StateSlot(
        slot_id="point:D.coordinate@problem:Point",
        object_ref="point:problem:D",
        state_kind="coordinate",
        scope_id="problem",
        runtime_type="Point",
        lineage=state_semantic_lineage(
            source_state_slot_ids=(
                "missing.coordinate@problem:Point",
            ),
        ),
    )
    math_object = MathObject(
        object_id="point:D@problem",
        kind="point",
        scope_id="problem",
        canonical_handle="point:problem:D",
        semantic_refs=("D",),
        source="problem",
    )

    with pytest.raises(
        ValueError,
        match="planner.context_identity_migration_failed",
    ):
        _attach_typed_initial_identity(
            [math_object],
            {slot.slot_id: slot},
            handle_registry=_Registry(),
        )


def test_authoritative_value_rejects_multiple_identity_categories() -> None:
    factory, _visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    version_id = StateVersionId(
        factory.slot_id(logical_key, storage_scope_id="ii"),
        1,
    )
    state_and_condition = ResolvedFunctionalValue(
        handle="fact:ii:D_coordinate",
        runtime_type="Point",
        valid_scope="ii",
        object_ref="point:problem:D",
        condition_id="condition:D",
        math_object_id=logical_key.object_id,
        logical_state_key=logical_key,
        typed_slot_id=version_id.slot_id,
        state_version_id=version_id,
    )
    with pytest.raises(
        StrategyDraftValidationError,
        match="exactly one typed identity category",
    ):
        FunctionalTypedIdentityValidator().validate_resolved_args(
            {"value": (state_and_condition,)},
            call_id="consume_value",
            identity_factory=factory,
        )


def test_identity_category_ignores_provenance_metadata() -> None:
    factory, _visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    value = ResolvedFunctionalValue(
        handle="functional:ii:derive_D:point",
        runtime_type="Point",
        valid_scope="ii",
        source_call_id="derive_D",
        return_name="point",
        object_ref="point:problem:D",
        math_object_id=logical_key.object_id,
    )

    _, completeness = (
        FunctionalTypedIdentityValidator().validate_resolved_args(
            {"point": (value,)},
            call_id="consume_D",
            identity_factory=factory,
        )
    )

    assert completeness.identity_only_values == 1
    assert completeness.call_result_values == 0


def test_materialized_identity_allows_producer_provenance() -> None:
    factory, _visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    version_id = StateVersionId(
        factory.slot_id(logical_key, storage_scope_id="ii"),
        1,
    )
    value = ResolvedFunctionalValue(
        handle="fact:ii:D_coordinate",
        runtime_type="Point",
        valid_scope="ii",
        state_slot_id="point:problem:D.coordinate@ii:Point",
        source_call_id="derive_D",
        return_name="point",
        object_ref="point:problem:D",
        math_object_id=logical_key.object_id,
        logical_state_key=logical_key,
        typed_slot_id=version_id.slot_id,
        state_version_id=version_id,
    )

    _, completeness = (
        FunctionalTypedIdentityValidator().validate_resolved_args(
            {"point": (value,)},
            call_id="consume_D",
            identity_factory=factory,
        )
    )

    assert completeness.materialized_values == 1
    assert completeness.call_result_values == 0


def test_typed_lineage_round_trip_preserves_role_versions() -> None:
    factory, _visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    version_id = StateVersionId(
        factory.slot_id(logical_key, storage_scope_id="ii"),
        1,
    )
    lineage = state_semantic_lineage(
        object_roles=(
            StateObjectRoleBinding(
                role="fixed_endpoint",
                object_refs=("point:problem:D",),
                source_state_slot_ids=("legacy-slot",),
                object_ids=(logical_key.object_id,),
                source_version_ids=(version_id,),
                state_requirement="materialized",
            ),
        ),
        source_state_slot_ids=("legacy-slot",),
        source_version_ids=(version_id,),
        source_call_result_ids=("derive_value.expression",),
    )

    restored = state_semantic_lineage_from_payload(lineage.to_payload())

    assert restored.source_version_ids == (version_id,)
    assert restored.source_call_result_ids == (
        "derive_value.expression",
    )
    assert restored.object_roles[0].object_ids == (logical_key.object_id,)
    assert restored.object_roles[0].source_version_ids == (version_id,)


def test_legacy_lineage_migration_counts_complete_fallback() -> None:
    factory, _visibility, _index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    version_id = StateVersionId(
        factory.slot_id(logical_key, storage_scope_id="ii"),
        0,
    )
    adapter = LegacyContextIdentityMigrator()
    lineage = state_semantic_lineage(
        object_roles=(
            StateObjectRoleBinding(
                role="subject",
                object_refs=("point:problem:D",),
                source_state_slot_ids=("legacy-slot",),
                state_requirement="materialized",
            ),
        ),
        source_state_slot_ids=("legacy-slot",),
    )

    migrated = adapter.migrate_lineage(
        lineage,
        object_ids_by_ref={"point:problem:D": logical_key.object_id},
        versions_by_legacy_slot={"legacy-slot": version_id},
    )

    assert adapter.identity_fallback_count > 0
    assert migrated.source_version_ids == (version_id,)
    assert migrated.object_roles[0].object_ids == (logical_key.object_id,)
    assert migrated.object_roles[0].source_version_ids == (version_id,)


def test_legacy_lineage_migration_rejects_partial_source_mapping() -> None:
    adapter = LegacyContextIdentityMigrator()
    lineage = state_semantic_lineage(
        source_state_slot_ids=("legacy-slot-1", "legacy-slot-2"),
    )

    with pytest.raises(
        ValueError,
        match="planner.context_identity_migration_failed",
    ):
        adapter.migrate_lineage(
            lineage,
            object_ids_by_ref={},
            versions_by_legacy_slot={
                "legacy-slot-1": StateVersionId(
                    StateSlotId(
                        LogicalStateKey(
                            MathObjectId(
                                "point:problem:D",
                                "point",
                                "problem",
                            ),
                            "coordinate",
                            "Point",
                        ),
                        "ii",
                    ),
                    0,
                ),
            },
        )


def test_functional_authority_has_no_legacy_identity_lookup() -> None:
    functions = (
        functional_computation_key,
        functional_source_version_ids,
        _canonical_dependency_graph,
        build_functional_state_dependencies,
        _materialize_functional_return,
    )
    forbidden_calls = {
        "latest_for_legacy_slot",
        "legacy_slot_id",
    }
    for function in functions:
        tree = ast.parse(inspect.getsource(function))
        called_attributes = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert not called_attributes.intersection(forbidden_calls), (
            function.__name__,
            called_attributes,
        )
    materialize_tree = ast.parse(
        inspect.getsource(_materialize_functional_return)
    )
    assert not any(
        isinstance(node, ast.JoinedStr)
        for node in ast.walk(materialize_tree)
    )
    placement_projection_tree = ast.parse(
        textwrap.dedent(inspect.getsource(_project_placed_calls))
    )
    assert not any(
        isinstance(node, ast.JoinedStr)
        and {
            child.id
            for child in ast.walk(node)
            if isinstance(child, ast.Name)
        }.intersection(
            {"object_ref", "state_kind", "runtime_type", "valid_scope"}
        )
        for node in ast.walk(placement_projection_tree)
    )
    coverage_tree = ast.parse(
        textwrap.dedent(
            inspect.getsource(_legacy_sources_are_fully_typed)
        )
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "len"
        for node in ast.walk(coverage_tree)
    )
    context_hydration_tree = ast.parse(
        textwrap.dedent(
            inspect.getsource(_attach_typed_initial_identity)
        )
    )
    assert any(
        isinstance(node, ast.Attribute)
        and node.attr == "migrate_lineage"
        for node in ast.walk(context_hydration_tree)
    )
    complete_value_tree = ast.parse(
        textwrap.dedent(
            inspect.getsource(
                FunctionalTypedIdentityValidator._complete_value
            )
        )
    )
    assert not any(
        isinstance(node, ast.Name) and node.id == "slot_versions"
        for node in ast.walk(complete_value_tree)
    )


def test_functional_runtime_consumers_do_not_call_legacy_state_selectors() -> None:
    typed_consumers = (
        EntityStateResolver._resolve_typed,
        PathTransformationStateResolver._resolve_typed_role,
        _required_path_role_point_input,
    )
    forbidden_calls = {
        "_legacy_explicit_state",
        "_state_handle",
        "latest_projected_state_write_in_handles",
        "latest_for_legacy_slot",
        "startswith",
    }
    for function in typed_consumers:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        assert not called.intersection(forbidden_calls), (
            function.__qualname__,
            called,
        )
    path_role_tree = ast.parse(
        textwrap.dedent(
            inspect.getsource(_required_path_role_point_input)
        )
    )
    assert any(
        isinstance(node, ast.Attribute)
        and node.attr == "runtime_path_for_state_version"
        for node in ast.walk(path_role_tree)
    )
    assert not any(
        isinstance(node, ast.Attribute)
        and node.attr == "path_for"
        for node in ast.walk(path_role_tree)
    )


def test_final_return_role_reprojection_fails_when_source_disappears() -> None:
    allocation = FunctionalReturnAllocation(
        call_id="build_path",
        return_name="path_transformation",
        handle="fact:ii:path",
        runtime_type="PathTransformation",
        valid_scope="ii",
        state_slot_id="call:build_path.path_transformation",
        object_ref=None,
        identity_policy="derived_role",
        write_mode="value",
        state_handle="fact:ii:path",
    )
    spec = type(
        "_ReturnSpec",
        (),
        {
            "object_role_projections": (
                StateObjectRoleProjectionSpec(
                    role="fixed_endpoint_1",
                    source_return="missing_endpoint",
                ),
            )
        },
    )()

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_identity_incomplete",
    ):
        _reproject_final_return_object_roles(
            (allocation,),
            specs={"path_transformation": spec},
            resolved_args={},
        )


def test_legacy_context_migration_rejects_ambiguous_object_ref() -> None:
    factory, visibility, _index = _identity()
    slot = StateSlot(
        slot_id="legacy:P.coordinate@ii",
        object_ref="P",
        state_kind="coordinate",
        scope_id="ii",
        runtime_type="Point",
    )

    with pytest.raises(
        ValueError,
        match="planner.context_identity_migration_failed",
    ):
        StateIdentityIndex.from_context(
            state_slots=(slot,),
            factory=factory,
            visibility=visibility,
        )


def test_scope_visibility_allows_ancestors_but_not_siblings() -> None:
    _factory, visibility, _index = _identity()

    assert visibility.is_visible("ii", consumer_scope_id="ii_1")
    assert not visibility.is_visible("ii_1", consumer_scope_id="ii_2")
    assert visibility.least_common_scope(("ii_1", "ii_2")) == "ii"


def test_allocation_reuses_only_identical_input_versions() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    first_key = ComputationKey("derive_point")
    first_request = _request(computation_key=first_key)
    first = service.allocate(first_request, index)
    assert first.action == "create"
    indexed = service.indexed_version(
        first_request,
        first,
        produced_handle="fact:ii:D_coordinate",
    )
    assert indexed is not None
    index.register(indexed, legacy_slot_id="point:problem:D.coordinate@ii")

    same = service.allocate(first_request, index)
    assert same.action == "reuse"
    assert same.selected_version_id == first.selected_version_id

    other_input = StateVersionId(
        StateSlotId(
            LogicalStateKey(
                MathObjectId("function:problem:f", "function", "problem"),
                "expression",
                "Parabola",
            ),
            "ii",
        ),
        1,
    )
    different_key = ComputationKey(
        "derive_point",
        (
            ArgVersionBinding(
                "quadratic",
                0,
                version_id=other_input,
            ),
        ),
    )
    different = service.allocate(
        _request(
            computation_key=different_key,
            write_mode="transition",
            source_versions=(first.selected_version_id,),
        ),
        index,
    )
    assert different.action == "transition"
    assert different.selected_version_id != first.selected_version_id


def test_allocation_isolates_child_state_when_freedom_increases() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    closed_request = _request(
        computation_key=ComputationKey("derive_point"),
        storage_scope="ii",
    )
    closed = service.allocate(closed_request, index)
    indexed = service.indexed_version(
        closed_request,
        closed,
        produced_handle="fact:ii:D_coordinate",
    )
    assert indexed is not None
    index.register(indexed)

    open_child = service.allocate(
        _request(
            computation_key=ComputationKey("derive_parametric_point"),
            storage_scope="ii_1",
            free_symbols=("symbol:problem:t",),
        ),
        index,
    )

    assert open_child.action == "isolated"
    assert open_child.previous_version_id is None


def test_allocation_isolates_independent_closed_child_object_state() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    open_parent_request = replace(
        _request(
            computation_key=ComputationKey("derive_open_curve"),
            storage_scope="ii",
            free_symbols=("symbol:problem:a",),
        ),
        identity_policy="preserve_input_object",
    )
    open_parent = service.allocate(open_parent_request, index)
    indexed = service.indexed_version(
        open_parent_request,
        open_parent,
        produced_handle="fact:ii:open_curve",
    )
    assert indexed is not None
    index.register(indexed)

    closed_child = service.allocate(
        replace(
            _request(
                computation_key=ComputationKey("derive_closed_curve"),
                storage_scope="ii_1",
            ),
            identity_policy="preserve_input_object",
        ),
        index,
    )

    assert closed_child.action == "isolated"
    assert closed_child.previous_version_id is None
    assert closed_child.reason_code == "independent_object_state_in_child_scope"


def test_allocation_accepts_recomputation_from_descendant_input_versions() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    curve_key = LogicalStateKey(
        MathObjectId("function:problem:f", "function", "problem"),
        "expression",
        "Parabola",
    )
    open_curve = StateVersionId(StateSlotId(curve_key, "problem"), 1)
    closed_curve = StateVersionId(StateSlotId(curve_key, "i"), 1)
    index.register(
        IndexedStateVersion(
            open_curve,
            valid_scope_id="problem",
            producer_call_id="build_open_curve",
            produced_handle="fact:problem:open_curve",
        )
    )
    index.register(
        IndexedStateVersion(
            closed_curve,
            valid_scope_id="i",
            producer_call_id="close_curve",
            produced_handle="fact:i:closed_curve",
            source_version_ids=(open_curve,),
        )
    )
    open_request = _request(
        computation_key=ComputationKey(
            "derive_intercept",
            (
                ArgVersionBinding(
                    "quadratic",
                    0,
                    version_id=open_curve,
                ),
            ),
        ),
        storage_scope="problem",
        free_symbols=("symbol:problem:a",),
    )
    open_point = service.allocate(open_request, index)
    indexed_open_point = service.indexed_version(
        open_request,
        open_point,
        produced_handle="fact:problem:D_open_coordinate",
    )
    assert indexed_open_point is not None
    index.register(indexed_open_point)

    closed_request = _request(
        computation_key=ComputationKey(
            "derive_intercept",
            (
                ArgVersionBinding(
                    "quadratic",
                    0,
                    version_id=closed_curve,
                ),
            ),
        ),
        storage_scope="i",
    )
    closed_point = service.allocate(closed_request, index)

    assert closed_point.action == "transition"
    assert closed_point.previous_version_id == open_point.selected_version_id
    assert closed_point.previous_producer_call_id == open_request.call_id
    assert closed_point.transition_kind == "dependency_refinement"
    assert closed_point.reason_code == "recomputed_from_descendant_inputs"


def test_allocation_does_not_refine_state_from_cross_slot_descendant() -> None:
    factory, _visibility, index = _identity()
    service = StateAllocationService()
    point_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert point_key is not None
    point_version = StateVersionId(StateSlotId(point_key, "ii"), 0)
    index.register(
        IndexedStateVersion(
            point_version,
            valid_scope_id="ii",
            producer_call_id=None,
            produced_handle="fact:ii:D_coordinate",
        )
    )
    path_key = LogicalStateKey(
        MathObjectId(
            "path:ii:transformation",
            "path_transformation",
            "ii",
        ),
        "transformation",
        "PathTransformation",
    )
    path_version = StateVersionId(StateSlotId(path_key, "ii"), 1)
    index.register(
        IndexedStateVersion(
            path_version,
            valid_scope_id="ii",
            producer_call_id="build_path",
            produced_handle="fact:ii:path_transformation",
            source_version_ids=(point_version,),
        )
    )

    indirect = service.allocate(
        _request(
            computation_key=ComputationKey("derive_point_from_path"),
            source_versions=(path_version,),
        ),
        index,
    )
    direct = service.allocate(
        _request(
            computation_key=ComputationKey("derive_point_from_path"),
            source_versions=(path_version, point_version),
        ),
        index,
    )

    assert indirect.action == "conflict"
    assert indirect.reason_code != "dependency_refines_visible_state"
    assert direct.action == "transition"
    assert direct.previous_version_id == point_version
    assert direct.reason_code == "dependency_refines_visible_state"


def test_allocation_refines_exact_child_version_when_publishing_to_parent() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    logical_key = LogicalStateKey(
        MathObjectId("point:problem:D", "point", "problem"),
        "coordinate",
        "Point",
    )
    child_version = StateVersionId(
        StateSlotId(logical_key, "ii_1"),
        1,
    )
    index.register(
        IndexedStateVersion(
            child_version,
            valid_scope_id="ii_1",
            producer_call_id="build_open_point",
            produced_handle="fact:ii_1:D_coordinate",
            free_symbol_refs=("symbol:problem:t",),
        )
    )

    decision = service.allocate(
        _request(
            computation_key=ComputationKey("close_point"),
            storage_scope="ii",
            source_versions=(child_version,),
        ),
        index,
    )

    assert decision.action == "transition"
    assert decision.previous_version_id == child_version
    assert decision.reason_code == "explicit_dependency_refines_state"


def test_allocation_rejects_recomputation_from_unrelated_input_version() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    curve_key = LogicalStateKey(
        MathObjectId("function:problem:f", "function", "problem"),
        "expression",
        "Parabola",
    )
    first_curve = StateVersionId(StateSlotId(curve_key, "problem"), 1)
    unrelated_curve = StateVersionId(StateSlotId(curve_key, "i"), 1)
    for version, scope, producer in (
        (first_curve, "problem", "build_first_curve"),
        (unrelated_curve, "i", "build_unrelated_curve"),
    ):
        index.register(
            IndexedStateVersion(
                version,
                valid_scope_id=scope,
                producer_call_id=producer,
                produced_handle=f"fact:{scope}:curve",
            )
        )
    open_request = _request(
        computation_key=ComputationKey(
            "derive_intercept",
            (
                ArgVersionBinding(
                    "quadratic",
                    0,
                    version_id=first_curve,
                ),
            ),
        ),
        storage_scope="problem",
        free_symbols=("symbol:problem:a",),
    )
    open_point = service.allocate(open_request, index)
    indexed_open_point = service.indexed_version(
        open_request,
        open_point,
        produced_handle="fact:problem:D_open_coordinate",
    )
    assert indexed_open_point is not None
    index.register(indexed_open_point)

    conflict = service.allocate(
        _request(
            computation_key=ComputationKey(
                "derive_intercept",
                (
                    ArgVersionBinding(
                        "quadratic",
                        0,
                        version_id=unrelated_curve,
                    ),
                ),
            ),
            storage_scope="i",
        ),
        index,
    )

    assert conflict.action == "conflict"
    assert conflict.conflict_code == "state.transition_dependency_unproven"
    assert conflict.previous_producer_call_id == open_request.call_id


def test_unrelated_creates_for_visible_logical_state_conflict() -> None:
    _factory, _visibility, index = _identity()
    service = StateAllocationService()
    first_request = _request(computation_key=ComputationKey("first"))
    first = service.allocate(first_request, index)
    indexed = service.indexed_version(
        first_request,
        first,
        produced_handle="fact:ii:D_coordinate",
    )
    assert indexed is not None
    index.register(indexed)

    unrelated = _request(computation_key=ComputationKey("second"))
    unrelated = replace(
        unrelated,
        identity_policy="derived_role",
        state_effect_key=StateEffectKey(
            (
                LogicalReturnEffect(
                    "point",
                    unrelated.state_effect_key.returns[0].logical_key,
                    "derived_role",
                    "create",
                ),
            )
        ),
    )
    conflict = service.allocate(unrelated, index)

    assert conflict.action == "conflict"
    assert conflict.conflict_code == "state.logical_duplicate_writer"


def test_value_only_return_remains_call_local() -> None:
    _factory, _visibility, index = _identity()
    request = replace(
        _request(computation_key=ComputationKey("distance")),
        object_id=None,
        state_kind="expression",
        runtime_type="Expression",
        requested_write_mode="value",
        identity_policy="value_only",
        runtime_destination=None,
    )

    decision = StateAllocationService().allocate(request, index)

    assert decision.action == "call_local_value"
    assert decision.selected_version_id is None


def test_compiler_resolves_typed_transition_predecessor_across_scopes() -> None:
    object_id = MathObjectId(
        "function:problem:parabola",
        "function",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    parent_version = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    parent_write = StateWriteProvenance(
        step_id="build_parent_curve",
        scope_id="problem",
        capability_id="quadratic_from_constraints",
        produced_handle="fact:problem:parabola_expression",
        output_key="parabola",
        runtime_type="Parabola",
        identity_policy="preserve_input_object",
        identity_role="parabola",
        object_ref=object_id.value,
        selected_version_id=parent_version,
    )
    projected_child = ProjectedStateWrite(
        step_id="refine_child_curve",
        produced_handle="fact:i:parabola_expression",
        state_slot_id="function:problem:parabola.expression@i",
        write_mode="transition",
        runtime_type="Parabola",
        object_ref=object_id.value,
        previous_version_id=parent_version,
    )

    selected = _previous_state_write(
        (parent_write,),
        projected_write=projected_child,
        object_ref=object_id.value,
        runtime_type="Parabola",
        scope_id="i",
    )

    assert selected == parent_write


def test_logical_finalizer_keeps_sibling_isolated_state_versions_independent() -> None:
    registry = _Registry()
    object_id = MathObjectId(
        "function:problem:f",
        "function",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    first_slot = StateSlotId(logical_key, "ii_1")
    second_slot = StateSlotId(logical_key, "ii_2")
    writes = (
        ProjectedStateWrite(
            step_id="build_closed_branch",
            produced_handle="answer:ii_1.curve",
            state_slot_id="function:problem:f.expression@ii_1",
            write_mode="create",
            runtime_type="Parabola",
            object_ref=object_id.value,
            return_name="parabola",
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=first_slot,
            selected_version_id=StateVersionId(first_slot, 1),
            allocation_action="create",
        ),
        ProjectedStateWrite(
            step_id="build_open_branch",
            produced_handle="function:problem:f",
            state_slot_id="function:problem:f.expression@ii_2",
            write_mode="create",
            runtime_type="Parabola",
            object_ref=object_id.value,
            return_name="parabola",
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=second_slot,
            selected_version_id=StateVersionId(second_slot, 1),
            allocation_action="isolated",
        ),
    )

    result = StateFinalizationService().finalize_logical_graph(
        writes,
        step_scopes={
            "build_closed_branch": "ii_1",
            "build_open_branch": "ii_2",
        },
        handle_registry=registry,
    )

    assert result.ok
    assert {item.logical_writer_status for item in result.decisions} == {
        "valid"
    }


def test_logical_finalizer_defers_ancestor_isolated_destination_check() -> None:
    registry = _Registry()
    object_id = MathObjectId(
        "function:problem:f",
        "function",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    parent_slot = StateSlotId(logical_key, "problem")
    child_slot = StateSlotId(logical_key, "ii")
    writes = (
        ProjectedStateWrite(
            step_id="build_template",
            produced_handle="fact:problem:f_expression",
            state_slot_id="function:problem:f.expression@problem",
            write_mode="create",
            runtime_type="Parabola",
            object_ref=object_id.value,
            return_name="parabola",
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=parent_slot,
            selected_version_id=StateVersionId(parent_slot, 1),
            allocation_action="create",
        ),
        ProjectedStateWrite(
            step_id="build_child_specialization",
            produced_handle="fact:ii:f_expression",
            state_slot_id="function:problem:f.expression@ii",
            write_mode="create",
            runtime_type="Parabola",
            object_ref=object_id.value,
            return_name="parabola",
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=child_slot,
            selected_version_id=StateVersionId(child_slot, 1),
            allocation_action="isolated",
        ),
    )

    result = StateFinalizationService().finalize_logical_graph(
        writes,
        step_scopes={
            "build_template": "problem",
            "build_child_specialization": "ii",
        },
        handle_registry=registry,
    )

    assert result.ok


def test_logical_finalizer_rejects_isolated_writes_in_same_typed_slot() -> None:
    registry = _Registry()
    object_id = MathObjectId(
        "function:problem:f",
        "function",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    slot = StateSlotId(logical_key, "ii")
    writes = tuple(
        ProjectedStateWrite(
            step_id=step_id,
            produced_handle=f"fact:ii:{step_id}",
            state_slot_id="function:problem:f.expression@ii",
            write_mode="create",
            runtime_type="Parabola",
            object_ref=object_id.value,
            return_name="parabola",
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=slot,
            selected_version_id=StateVersionId(slot, ordinal),
            allocation_action="isolated",
        )
        for ordinal, step_id in enumerate(
            ("build_first", "build_second"),
            start=1,
        )
    )

    result = StateFinalizationService().finalize_logical_graph(
        writes,
        step_scopes={"build_first": "ii", "build_second": "ii"},
        handle_registry=registry,
        mode="shadow",
    )

    assert not result.ok
    assert {
        item.code for item in result.mismatches
    } == {"state.logical_duplicate_writer"}


def test_typed_identity_payloads_round_trip() -> None:
    object_id = MathObjectId("point:problem:D", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    version_id = StateVersionId(slot_id, 3)

    assert MathObjectId.from_payload(object_id.to_payload()) == object_id
    assert LogicalStateKey.from_payload(logical_key.to_payload()) == logical_key
    assert StateSlotId.from_payload(slot_id.to_payload()) == slot_id
    assert StateVersionId.from_payload(version_id.to_payload()) == version_id


def test_typed_placement_payloads_round_trip() -> None:
    object_id = MathObjectId("point:problem:D", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    source_version = StateVersionId(slot_id, 1)
    target_version = StateVersionId(slot_id, 2)
    identity_key = FunctionalCallIdentityKey(
        ComputationKey(
            "derive_point",
            (
                ArgVersionBinding(
                    "source",
                    0,
                    version_id=source_version,
                ),
            ),
        ),
        StateEffectKey(
            (
                LogicalReturnEffect(
                    "point",
                    logical_key,
                    "target_object",
                    "transition",
                ),
            )
        ),
    )
    decision = TypedCallPlacementDecision(
        canonical_call_id="derive_point_i",
        alias_call_ids=("derive_point_ii",),
        identity_key=identity_key,
        declared_scope_ids=("i", "ii"),
        execution_scope_id="problem",
        return_scope_ids={"point": "problem"},
        version_rewrites=(
            StateVersionPlacementRewrite(
                source_version,
                target_version,
            ),
        ),
    )

    assert FunctionalCallIdentityKey.from_payload(
        identity_key.to_payload()
    ) == identity_key
    assert TypedCallPlacementDecision.from_payload(
        decision.to_payload()
    ) == decision
