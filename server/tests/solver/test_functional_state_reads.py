from __future__ import annotations

from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    RuntimeHandleBinding,
)
from shuxueshuo_server.solver.runtime.entity_state_resolver import (
    EntityStateResolver,
)
from shuxueshuo_server.solver.runtime.functional_context_values import (
    latest_point_state_for_object,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_state_reads import (
    FunctionalStateReadIndex,
    RuntimeStateVersionBinding,
)
from shuxueshuo_server.solver.runtime.path_transformation_state import (
    ResolvedPathTransformationRole,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    _midpoint_target_identity_path,
    _required_path_role_point_input,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntent,
    StrategyDraftValidationError,
)


class _Registry:
    entity_handles = {
        "point:problem:P",
        "point:ii_1:Q",
    }
    answer_target_handles: dict[str, str] = {}
    _parents = {
        "problem": None,
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


def _version(
    *,
    object_id: MathObjectId,
    storage_scope: str,
    valid_scope: str,
    ordinal: int,
    runtime_path: str | None,
) -> RuntimeStateVersionBinding:
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    return RuntimeStateVersionBinding(
        version_id=StateVersionId(
            StateSlotId(logical_key, storage_scope),
            ordinal,
        ),
        logical_state_key=logical_key,
        math_object_id=object_id,
        runtime_type="Point",
        valid_scope_id=valid_scope,
        canonical_producer_call_id=f"producer_{ordinal}",
        runtime_path=runtime_path,
        produced_handle=f"fact:{valid_scope}:P_v{ordinal}",
    )


def test_exact_and_latest_visible_versions_do_not_alias() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    open_state = _version(
        object_id=object_id,
        storage_scope="problem",
        valid_scope="problem",
        ordinal=1,
        runtime_path="$problem.facts.P_open",
    )
    closed_state = _version(
        object_id=object_id,
        storage_scope="problem",
        valid_scope="problem",
        ordinal=2,
        runtime_path="$problem.facts.P_closed",
    )
    index.register(open_state)
    index.register(closed_state)

    assert index.require_version(
        open_state.version_id,
        consumer_scope_id="ii_1",
    ) is open_state
    assert index.latest_visible(
        open_state.logical_state_key,
        consumer_scope_id="ii_1",
    ) is closed_state


def test_latest_visible_uses_scope_specificity_before_slot_ordinal() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    parent = _version(
        object_id=object_id,
        storage_scope="problem",
        valid_scope="problem",
        ordinal=99,
        runtime_path="$problem.facts.P_parent",
    )
    branch = _version(
        object_id=object_id,
        storage_scope="ii",
        valid_scope="ii",
        ordinal=1,
        runtime_path="$question.ii.facts.P_branch",
    )
    index.register(parent)
    index.register(branch)

    assert index.latest_visible(
        parent.logical_state_key,
        consumer_scope_id="ii_1",
    ) is branch


def test_latest_point_state_uses_typed_scope_specificity() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    parent_version = StateVersionId(
        StateSlotId(logical_key, "problem"),
        99,
    )
    branch_version = StateVersionId(
        StateSlotId(logical_key, "ii"),
        1,
    )
    parent = ResolvedFunctionalValue(
        handle="fact:problem:P_parent",
        runtime_type="Point",
        valid_scope="problem",
        object_ref=object_id.value,
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=parent_version.slot_id,
        state_version_id=parent_version,
    )
    branch = ResolvedFunctionalValue(
        handle="fact:ii:P_branch",
        runtime_type="Point",
        valid_scope="ii",
        object_ref=object_id.value,
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=branch_version.slot_id,
        state_version_id=branch_version,
    )

    selected = latest_point_state_for_object(
        object_id.value,
        scope_id="ii_1",
        produced={
            ("parent", "point"): parent,
            ("branch", "point"): branch,
        },
        semantic_index=SimpleNamespace(
            compatible_views=lambda **_kwargs: ()
        ),
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )

    assert selected is branch


def test_latest_visible_rejects_incomparable_same_scope_slots() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    first = _version(
        object_id=object_id,
        storage_scope="problem",
        valid_scope="ii",
        ordinal=2,
        runtime_path="$question.ii.facts.P_first",
    )
    second = _version(
        object_id=object_id,
        storage_scope="ii",
        valid_scope="ii",
        ordinal=1,
        runtime_path="$question.ii.facts.P_second",
    )
    index.register(first)
    index.register(second)

    with pytest.raises(
        StrategyDraftValidationError,
        match="ambiguous_latest_visible",
    ):
        index.latest_visible(
            first.logical_state_key,
            consumer_scope_id="ii_1",
        )


def test_sibling_private_version_is_not_visible() -> None:
    object_id = MathObjectId("point:ii_1:Q", "point", "ii_1")
    binding = _version(
        object_id=object_id,
        storage_scope="ii_1",
        valid_scope="ii_1",
        ordinal=1,
        runtime_path="$subquestion.ii_1.facts.Q",
    )
    index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    index.register(binding)

    assert (
        index.latest_visible(
            binding.logical_state_key,
            consumer_scope_id="ii_2",
        )
        is None
    )
    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_visibility_drift",
    ):
        index.require_version(
            binding.version_id,
            consumer_scope_id="ii_2",
        )


def test_runtime_path_cannot_identify_two_logical_states() -> None:
    index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    first = _version(
        object_id=MathObjectId(
            "point:problem:P",
            "point",
            "problem",
        ),
        storage_scope="problem",
        valid_scope="problem",
        ordinal=1,
        runtime_path="$problem.facts.shared",
    )
    second = _version(
        object_id=MathObjectId(
            "point:ii_1:Q",
            "point",
            "ii_1",
        ),
        storage_scope="ii_1",
        valid_scope="ii_1",
        ordinal=1,
        runtime_path="$problem.facts.shared",
    )
    index.register(first)

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        index.register(second)


def test_runtime_path_is_required_only_at_physical_binding_boundary() -> None:
    binding = _version(
        object_id=MathObjectId(
            "point:problem:P",
            "point",
            "problem",
        ),
        storage_scope="problem",
        valid_scope="problem",
        ordinal=1,
        runtime_path=None,
    )
    index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    index.register(binding)

    assert index.require_version(
        binding.version_id,
        consumer_scope_id="ii",
    ) is binding
    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        index.runtime_path_for_version(
            binding.version_id,
            consumer_scope_id="ii",
        )


def test_initial_materialized_entity_becomes_typed_ordinal_zero_state() -> None:
    index = FunctionalStateReadIndex.from_sources(
        handle_registry=_Registry(),  # type: ignore[arg-type]
        runtime_bindings={
            "point:problem:P": RuntimeHandleBinding(
                "point:problem:P",
                "$problem.points.P",
                "Point",
                "entity",
            )
        },
    )
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(
        object_id,
        "coordinate",
        "Point",
    )

    selected = index.latest_visible(
        logical_key,
        consumer_scope_id="ii_1",
    )

    assert selected is not None
    assert selected.version_id.ordinal == 0
    assert selected.runtime_path == "$problem.points.P"


def test_entity_identity_read_ignores_stale_direct_handle_binding() -> None:
    calls: list[tuple[MathObjectId, str]] = []
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    index = SimpleNamespace(
        functional_consumer_identity_mode="authoritative",
        handle_registry=_Registry(),
        bindings={
            "point:problem:P": RuntimeHandleBinding(
                "point:problem:P",
                "$problem.entities.stale_P",
                "PointRef",
                "legacy",
            )
        },
        projected_state_write_for_handle=lambda _handle: None,
        runtime_path_for_object_identity=lambda selected, **kwargs: (
            calls.append((selected, kwargs["expected_type"]))
            or "$problem.entities.typed_P"
        ),
        record_legacy_runtime_identity_fallback=lambda **_kwargs: pytest.fail(
            "typed identity read must not fall back to the direct handle"
        ),
    )
    step = StepIntent(
        step_id="consume_P",
        scope_id="ii_1",
        recipe_hint="",
        goal_type="",
        target="",
        strategy="",
    )

    path = EntityStateResolver().resolve(
        "point:problem:P",
        "PointRef",
        step,
        index,
    )

    assert path == "$problem.entities.typed_P"
    assert calls == [(object_id, "PointRef")]


def test_entity_state_resolver_uses_scope_specific_latest_version() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    read_index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
    )
    parent = _version(
        object_id=object_id,
        storage_scope="problem",
        valid_scope="problem",
        ordinal=99,
        runtime_path="$problem.facts.P_parent",
    )
    branch = _version(
        object_id=object_id,
        storage_scope="ii",
        valid_scope="ii",
        ordinal=1,
        runtime_path="$question.ii.facts.P_branch",
    )
    read_index.register(parent)
    read_index.register(branch)
    fills: list[str] = []
    index = SimpleNamespace(
        functional_consumer_identity_mode="authoritative",
        bindings={},
        projected_state_write_for_handle=lambda _handle: None,
        handle_registry=_Registry(),
        functional_state_read_index=lambda: read_index,
        capture_functional_read_audit=lambda _read_index: None,
        record_applied_fill=lambda **kwargs: fills.append(
            kwargs["resolved_handle"]
        ),
    )
    step = StepIntent(
        step_id="consume_P",
        scope_id="ii_1",
        recipe_hint="",
        goal_type="",
        target="",
        strategy="",
    )

    selected = EntityStateResolver().resolve(
        object_id.value,
        "Point",
        step,
        index,
    )

    assert selected == "$question.ii.facts.P_branch"
    assert fills == [branch.produced_handle]


def test_legacy_runtime_identity_fallback_is_counted_and_authoritative_fails() -> None:
    shadow = object.__new__(CanonicalRuntimeBindingIndex)
    shadow.functional_consumer_identity_mode = "shadow"
    shadow.legacy_runtime_identity_fallback_count = 0
    shadow.runtime_consumer_mismatches = []

    shadow.record_legacy_runtime_identity_fallback(
        consumer="consume_P",
        handle="point:problem:P",
        reason="missing_typed_identity",
    )

    assert shadow.legacy_runtime_identity_fallback_count == 1
    assert shadow.runtime_consumer_mismatches == [
        {
            "code": "legacy_runtime_identity_fallback",
            "consumer": "consume_P",
            "handle": "point:problem:P",
            "reason": "missing_typed_identity",
        }
    ]

    authoritative = object.__new__(CanonicalRuntimeBindingIndex)
    authoritative.functional_consumer_identity_mode = "authoritative"
    authoritative.legacy_runtime_identity_fallback_count = 0
    authoritative.runtime_consumer_mismatches = []
    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        authoritative.record_legacy_runtime_identity_fallback(
            consumer="consume_P",
            handle="point:problem:P",
            reason="missing_typed_identity",
        )
    assert authoritative.legacy_runtime_identity_fallback_count == 1


def test_condition_identity_uses_typed_physical_binding() -> None:
    index = object.__new__(CanonicalRuntimeBindingIndex)
    index.bindings = {
        "fact:ii:condition": RuntimeHandleBinding(
            "fact:ii:condition",
            "$question.ii.facts.condition",
            "Condition",
            "fact",
        )
    }
    index.handle_registry = _Registry()
    index.runtime_consumer_decisions = []

    path = index.runtime_path_for_condition_identity(
        "condition:ii:constraint",
        source_handle="fact:ii:condition",
        expected_type="Condition",
        consumer_scope_id="ii_1",
        consumer="consume.condition",
    )

    assert path == "$question.ii.facts.condition"
    assert index.runtime_consumer_decisions[0]["action"] == (
        "typed_condition_binding"
    )


def test_call_result_identity_validates_its_physical_producer() -> None:
    index = object.__new__(CanonicalRuntimeBindingIndex)
    index.bindings = {
        "value:expression": RuntimeHandleBinding(
            "value:expression",
            "$step.produce_expression.temp.expression",
            "Expression",
            "step:produce_expression",
        )
    }
    index.handle_registry = _Registry()
    index.runtime_consumer_decisions = []

    assert index.runtime_path_for_call_result_identity(
        "produce_expression",
        "expression",
        source_handle="value:expression",
        expected_type="Expression",
        consumer_scope_id="ii_1",
        consumer="consume.expression",
    ) == "$step.produce_expression.temp.expression"

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        index.runtime_path_for_call_result_identity(
            "another_producer",
            "expression",
            source_handle="value:expression",
            expected_type="Expression",
            consumer_scope_id="ii_1",
            consumer="consume.stale_expression",
        )


def test_midpoint_target_missing_typed_identity_fails_before_legacy_path() -> None:
    fallback_reasons: list[str] = []

    def reject_fallback(**kwargs: str) -> None:
        fallback_reasons.append(kwargs["reason"])
        raise StrategyDraftValidationError(
            "planner.runtime_state_binding_drift"
        )

    index = SimpleNamespace(
        functional_consumer_identity_mode="authoritative",
        projected_state_write_for_handle=lambda _handle: None,
        handle_registry=SimpleNamespace(
            entity_handles=frozenset(),
            answer_target_handles={},
        ),
        record_legacy_runtime_identity_fallback=reject_fallback,
        point_identity_path_for=lambda _handle: pytest.fail(
            "authoritative midpoint target must not use a legacy handle"
        ),
    )
    step = StepIntent(
        step_id="derive_midpoint",
        scope_id="ii",
        recipe_hint="midpoint_point",
        goal_type="derive_midpoint",
        target="",
        strategy="",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        _midpoint_target_identity_path(
            "point:ii:missing",
            step=step,
            index=index,
        )

    assert fallback_reasons == ["midpoint_target_math_object_unresolved"]


def test_shadow_read_index_incomplete_identity_counts_fallback_once() -> None:
    read_index = FunctionalStateReadIndex(
        handle_registry=_Registry(),  # type: ignore[arg-type]
        mode="shadow",
    )
    read_index._incomplete(
        "planner.state_identity_incomplete",
        "synthetic missing version",
    )
    read_index._incomplete(
        "planner.state_identity_incomplete",
        "synthetic missing version",
    )
    binding_index = object.__new__(CanonicalRuntimeBindingIndex)
    binding_index.functional_consumer_identity_mode = "shadow"
    binding_index.legacy_runtime_identity_fallback_count = 0
    binding_index.runtime_consumer_decisions = []
    binding_index.runtime_consumer_mismatches = []

    binding_index.capture_functional_read_audit(read_index)
    binding_index.capture_functional_read_audit(read_index)

    assert read_index.legacy_identity_fallback_count == 1
    assert binding_index.legacy_runtime_identity_fallback_count == 1


def test_path_role_consumer_keeps_exact_version_runtime_path() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(
        object_id,
        "coordinate",
        "Point",
    )
    version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    role = ResolvedPathTransformationRole(
        role="fixed_endpoint_1",
        object_ref=object_id.value,
        state_handle="fact:problem:P_rebound",
        source_state_slot_ids=(),
        source_handles=(),
        state_requirement="materialized",
        object_id=object_id,
        state_version_id=version_id,
        runtime_path="$problem.facts.P_v1",
    )
    index = SimpleNamespace(
        functional_consumer_identity_mode="authoritative",
        runtime_path_for_state_version=lambda selected, **_kwargs: (
            "$problem.facts.P_v1"
            if selected == version_id
            else pytest.fail("unexpected version")
        ),
        path_for=lambda *_args, **_kwargs: pytest.fail(
            "role state_handle must not be rebound through path_for"
        ),
    )
    step = StepIntent(
        step_id="consume_path",
        scope_id="ii",
        recipe_hint="",
        goal_type="",
        target="",
        strategy="",
    )

    path, preparation = _required_path_role_point_input(
        role,
        step=step,
        index=index,
    )

    assert path == "$problem.facts.P_v1"
    assert preparation == ((), {})


def test_latest_point_state_uses_version_ordinal_not_insertion_order() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(
        object_id,
        "coordinate",
        "Point",
    )
    slot_id = StateSlotId(logical_key, "problem")
    closed = ResolvedFunctionalValue(
        handle="fact:problem:P_closed",
        runtime_type="Point",
        valid_scope="problem",
        object_ref=object_id.value,
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        state_version_id=StateVersionId(slot_id, 2),
    )
    open_state = ResolvedFunctionalValue(
        handle="fact:problem:P_open",
        runtime_type="Point",
        valid_scope="problem",
        object_ref=object_id.value,
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        state_version_id=StateVersionId(slot_id, 1),
    )
    semantic_index = SimpleNamespace(
        compatible_views=lambda **_kwargs: ()
    )

    selected = latest_point_state_for_object(
        object_id.value,
        scope_id="ii_1",
        produced={
            ("closed", "point"): closed,
            ("open", "point"): open_state,
        },
        semantic_index=semantic_index,
        handle_registry=_Registry(),
    )

    assert selected is closed
