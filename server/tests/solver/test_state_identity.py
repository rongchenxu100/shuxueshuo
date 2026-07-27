from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_state_allocation import (
    functional_computation_key,
    functional_source_version_ids,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    _previous_state_write,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    AmbiguousMathObjectReferenceError,
    ArgVersionBinding,
    ComputationKey,
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
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProjectedStateWrite,
    StateWriteProvenance,
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


def test_legacy_slot_projection_is_typed_and_accepts_old_alias() -> None:
    factory, _visibility, index = _identity()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    slot_id = factory.slot_id(logical_key, storage_scope_id="ii")
    canonical = factory.legacy_slot_id(slot_id)
    old_alias = factory.legacy_slot_alias(slot_id)
    initial = IndexedStateVersion(
        StateVersionId(slot_id, 0),
        valid_scope_id="ii",
        producer_call_id=None,
        produced_handle="fact:ii:D_coordinate",
    )
    index.register(initial, legacy_slot_id=old_alias)

    assert canonical.endswith("@ii:Point")
    assert index.latest_for_legacy_slot(
        canonical,
        consumer_scope_id="ii_1",
    ) == initial
    assert index.latest_for_legacy_slot(
        old_alias,
        consumer_scope_id="ii_1",
    ) == initial


def test_context_to_inflight_lookup_uses_latest_typed_version() -> None:
    factory, _visibility, index = _identity()
    service = StateAllocationService()
    logical_key = factory.logical_key(
        object_ref="point:problem:D",
        state_kind="coordinate",
        runtime_type="Point",
    )
    assert logical_key is not None
    slot_id = factory.slot_id(logical_key, storage_scope_id="ii")
    canonical_slot = factory.legacy_slot_id(slot_id)
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


def test_typed_identity_payloads_round_trip() -> None:
    object_id = MathObjectId("point:problem:D", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    version_id = StateVersionId(slot_id, 3)

    assert MathObjectId.from_payload(object_id.to_payload()) == object_id
    assert LogicalStateKey.from_payload(logical_key.to_payload()) == logical_key
    assert StateSlotId.from_payload(slot_id.to_payload()) == slot_id
    assert StateVersionId.from_payload(version_id.to_payload()) == version_id
