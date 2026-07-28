from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalCommittedCallCheckpoint,
    FunctionalRetryCheckpointError,
    FunctionalRetryGraphCheckpoint,
    FunctionalRetryResultRecord,
    FunctionalRetryVersionRecord,
    build_functional_retry_graph_checkpoint,
    expand_retry_dependency_graph_with_versions,
    restore_committed_calls,
    validate_checkpoint_manifest,
    verify_restored_checkpoint,
    verify_restored_runtime_checkpoint,
)
from shuxueshuo_server.solver.runtime.planner_retry_projection import (
    _typed_committed_candidate_calls,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    _functional_previous_attempt_state,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    _checkpoint_committed_candidate_calls,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    ArgVersionBinding,
    ComputationKey,
    FunctionalCallIdentityKey,
    LogicalReturnEffect,
    LogicalStateKey,
    MathObjectId,
    RuntimeDestinationKey,
    StateEffectKey,
    StateSlotId,
    StateVersionId,
)


def _checkpoint() -> FunctionalRetryGraphCheckpoint:
    object_id = MathObjectId("point:problem:P", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    source_version = StateVersionId(slot_id, 0)
    version_id = StateVersionId(slot_id, 1)
    computation_key = ComputationKey(
        "construct_point",
        (
            ArgVersionBinding(
                "source",
                0,
                version_id=source_version,
            ),
        ),
    )
    state_effect_key = StateEffectKey(
        (
            LogicalReturnEffect(
                "point",
                logical_key,
                "target_object",
                "create",
            ),
        )
    )
    return FunctionalRetryGraphCheckpoint(
        source_context_id="context-1",
        problem_id="problem-1",
        family_id="family-1",
        family_spec_hash="family-hash",
        capability_pack_hash="pack-hash",
        committed_calls=(
            FunctionalCommittedCallCheckpoint(
                canonical_call_id="make_point",
                declared_scope_id="i",
                call_payload={
                    "call_id": "make_point",
                    "capability_id": "construct_point",
                    "args": {},
                    "return_bindings": {
                        "point": {"kind": "point", "ref": "P"}
                    },
                    "strategy": "construct",
                    "reason": "needed",
                },
                identity_key=FunctionalCallIdentityKey(
                    computation_key,
                    state_effect_key,
                ),
                output_version_ids=(version_id,),
                committed_goal_handles=("answer:i.P",),
                execution_scope_id="problem",
                return_scope_ids=(("point", "problem"),),
            ),
        ),
        verified_versions=(
            FunctionalRetryVersionRecord(
                return_name="point",
                version_id=version_id,
                logical_state_key=logical_key,
                canonical_producer_call_id="make_point",
                computation_key=computation_key,
                state_effect_key=state_effect_key,
                previous_version_id=source_version,
                source_version_ids=(source_version,),
                valid_scope_id="problem",
                result_form="closed_state",
                free_symbol_refs=(),
                runtime_destination=RuntimeDestinationKey(
                    object_id,
                    "coordinate",
                    "Point",
                    "$question.objects.P",
                ),
                status="goal_committed",
            ),
        ),
    )


def _checkpoint_builder_inputs(
    *,
    canonical_producer_call_id: str = "make_point",
) -> tuple[dict[str, object], FunctionalRetryVersionRecord]:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    verified = checkpoint.verified_versions[0]
    call = SimpleNamespace(
        call_id="make_point",
        to_payload=lambda: dict(committed.call_payload),
    )
    allocation = SimpleNamespace(
        return_name="point",
        canonical_producer_call_id=canonical_producer_call_id,
        valid_scope="problem",
        free_symbol_refs=(),
        selected_version_id=verified.version_id,
    )
    reconciliation = SimpleNamespace(
        plan=SimpleNamespace(
            calls=(call,),
            scopes=(
                SimpleNamespace(scope_id="i", calls=(call,)),
            ),
        ),
        calls=(
            SimpleNamespace(
                call_id="make_point",
                returns=(allocation,),
            ),
        ),
        projection_map=(
            SimpleNamespace(
                call_id="make_point",
                step_ids=("make_point_step",),
            ),
        ),
        state_placement_decisions=(
            {
                "canonical_call_id": "make_point",
                "identity_key": committed.identity_key.to_payload(),
            },
        ),
        call_placements=(
            SimpleNamespace(
                canonical_call_id="make_point",
                execution_scope_id="problem",
                return_scopes={"point": "problem"},
            ),
        ),
    )
    call_memory = SimpleNamespace(
        committed_call_ids=("make_point",),
        runtime_verified_call_ids=(),
        entries=(
            SimpleNamespace(
                call_id="make_point",
                committed_goal_handles=("answer:i.P",),
                result_snapshots=(
                    SimpleNamespace(
                        return_name="point",
                        actual_form="closed_state",
                    ),
                ),
            ),
        ),
    )
    provenance = (
        SimpleNamespace(
            step_id="make_point_step",
            return_name="point",
            selected_version_id=verified.version_id,
            logical_state_key=verified.logical_state_key,
            computation_key=verified.computation_key,
            previous_version_id=verified.previous_version_id,
            source_version_ids=verified.source_version_ids,
            runtime_destination_key=verified.runtime_destination,
        ),
    )
    context = SimpleNamespace(
        manifest=SimpleNamespace(
            context_id="context-2",
            problem_id=checkpoint.problem_id,
            family_id=checkpoint.family_id,
            family_spec_hash=checkpoint.family_spec_hash,
            capability_pack_hash=checkpoint.capability_pack_hash,
        )
    )
    return {
        "context": context,
        "reconciliation": reconciliation,
        "call_memory": call_memory,
        "provenance": provenance,
    }, verified


def test_retry_checkpoint_round_trip_and_exact_scope_restore() -> None:
    checkpoint = _checkpoint()
    assert FunctionalRetryGraphCheckpoint.from_payload(
        checkpoint.to_payload()
    ) == checkpoint
    candidate = {
        "schema_version": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "II",
                "calls": [
                    {
                        "call_id": "make_point",
                        "capability_id": "wrong",
                        "args": {},
                        "return_bindings": {},
                        "strategy": "wrong",
                        "reason": "wrong",
                    }
                ],
            },
            {"scope_id": "i", "label": "I", "calls": []},
        ],
    }

    restored = restore_committed_calls(candidate, checkpoint)
    restored_again = restore_committed_calls(restored, checkpoint)

    assert restored_again == restored
    assert restored["scopes"][0]["calls"] == []
    assert restored["scopes"][1]["calls"] == [
        checkpoint.committed_calls[0].call_payload
    ]
    assert checkpoint.pinned_execution_scopes == {
        "make_point": "problem"
    }
    assert checkpoint.pinned_return_scopes == {
        "make_point": {"point": "problem"}
    }


def test_typed_checkpoint_backfills_locked_call_projection() -> None:
    checkpoint = _checkpoint()

    committed = _typed_committed_candidate_calls(
        checkpoint.to_payload(),
        (),
    )
    prompt_state = _functional_previous_attempt_state(
        [
            {
                "context_derived_retry_state": {
                    "attempt": 1,
                    "candidate_format": "functional_plan",
                    "baseline_candidate": {
                        "schema_version": "functional_plan/v1",
                        "scopes": [],
                    },
                    "functional_retry_graph_checkpoint": (
                        checkpoint.to_payload()
                    ),
                    "issues": [
                        {
                            "layer": "goal_verification",
                            "code": "synthetic_failure",
                            "message": "repair another branch",
                        }
                    ],
                }
            }
        ]
    )

    assert committed == (
        {
            "scope_id": "i",
            "call": checkpoint.committed_calls[0].call_payload,
        },
    )
    assert prompt_state["latest_retry_state"]["locked_call_ids"] == [
        "make_point"
    ]


def test_typed_checkpoint_projection_prefers_checkpoint_payload() -> None:
    checkpoint = _checkpoint()
    stale_candidate = {
        "scope_id": "ii",
        "call": {
            **checkpoint.committed_calls[0].call_payload,
            "capability_id": "stale_capability",
        },
    }

    committed = _typed_committed_candidate_calls(
        checkpoint.to_payload(),
        (stale_candidate,),
    )

    assert committed == (
        {
            "scope_id": "i",
            "call": checkpoint.committed_calls[0].call_payload,
        },
    )


def test_committed_materialized_return_requires_typed_provenance() -> None:
    inputs, _verified = _checkpoint_builder_inputs()
    inputs["provenance"] = ()

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match=(
            "planner.retry_version_checkpoint_invalid.*"
            "no typed version checkpoint"
        ),
    ):
        build_functional_retry_graph_checkpoint(**inputs)


def test_committed_call_local_return_uses_typed_result_anchor() -> None:
    inputs, verified = _checkpoint_builder_inputs()
    reconciliation = inputs["reconciliation"]
    call_memory = inputs["call_memory"]
    identity_key = _checkpoint().committed_calls[0].identity_key
    value_call = SimpleNamespace(
        call_id="make_point",
        returns=(
            SimpleNamespace(
                return_name="angle_equality",
                canonical_producer_call_id="make_point",
                valid_scope="i",
                free_symbol_refs=(),
                selected_version_id=None,
                computation_key=verified.computation_key,
                runtime_type="AngleEquality",
            ),
        ),
    )
    reconciliation.calls = (value_call,)
    call_memory.entries = (
        SimpleNamespace(
            call_id="make_point",
            committed_goal_handles=("answer:i.P",),
            result_snapshots=(
                SimpleNamespace(
                    return_name="angle_equality",
                    actual_form=None,
                    value_type="AngleEquality",
                    value_omitted_reason=None,
                ),
            ),
        ),
    )
    inputs["provenance"] = ()

    result = build_functional_retry_graph_checkpoint(**inputs)

    assert result.verified_versions == ()
    assert result.verified_results == (
        FunctionalRetryResultRecord(
            return_name="angle_equality",
            result_id="make_point.angle_equality",
            canonical_producer_call_id="make_point",
            computation_key=verified.computation_key,
            state_effect_key=identity_key.state_effect_key,
            valid_scope_id="i",
            value_type="AngleEquality",
            result_form=None,
            free_symbol_refs=(),
            status="goal_committed",
        ),
    )
    assert result.committed_calls[0].output_version_ids == ()
    assert result.committed_calls[0].output_result_ids == (
        "make_point.angle_equality",
    )

    verify_restored_checkpoint(
        result,
        reconciliation=SimpleNamespace(
            calls=(value_call,),
            state_placement_decisions=(
                {
                    "canonical_call_id": "make_point",
                    "identity_key": identity_key.to_payload(),
                },
            ),
            call_aliases={},
        ),
        handle_registry=SimpleNamespace(
            ancestor_scopes=lambda _scope_id: ("problem",),
        ),
    )


def test_checkpoint_ignores_allocated_return_without_runtime_write() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    verified = checkpoint.verified_versions[0]
    ghost_object = MathObjectId(
        "point:i:unused_output",
        "point",
        "i",
    )
    ghost_logical = LogicalStateKey(
        ghost_object,
        "coordinate",
        "Point",
    )
    ghost_version = StateVersionId(
        StateSlotId(ghost_logical, "i"),
        1,
    )
    call = SimpleNamespace(
        call_id="make_point",
        to_payload=lambda: dict(committed.call_payload),
    )
    allocation = SimpleNamespace(
        return_name="point",
        canonical_producer_call_id="make_point",
        valid_scope="problem",
        free_symbol_refs=(),
        selected_version_id=verified.version_id,
    )
    ghost_allocation = SimpleNamespace(
        return_name="unused_point",
        canonical_producer_call_id="make_point",
        valid_scope="i",
        free_symbol_refs=(),
        selected_version_id=ghost_version,
    )
    reconciliation = SimpleNamespace(
        plan=SimpleNamespace(
            calls=(call,),
            scopes=(
                SimpleNamespace(scope_id="i", calls=(call,)),
            ),
        ),
        calls=(
            SimpleNamespace(
                call_id="make_point",
                returns=(allocation, ghost_allocation),
            ),
        ),
        projection_map=(
            SimpleNamespace(
                call_id="make_point",
                step_ids=("make_point_step",),
            ),
        ),
        state_placement_decisions=(
            {
                "canonical_call_id": "make_point",
                "identity_key": committed.identity_key.to_payload(),
            },
        ),
        call_placements=(
            SimpleNamespace(
                canonical_call_id="make_point",
                execution_scope_id="problem",
                return_scopes={
                    "point": "problem",
                    "unused_point": "i",
                },
            ),
        ),
    )
    memory_entry = SimpleNamespace(
        call_id="make_point",
        committed_goal_handles=("answer:i.P",),
        result_snapshots=(
            SimpleNamespace(
                return_name="point",
                actual_form="closed_state",
            ),
        ),
    )
    call_memory = SimpleNamespace(
        committed_call_ids=("make_point",),
        runtime_verified_call_ids=(),
        entries=(memory_entry,),
    )
    provenance = (
        SimpleNamespace(
            step_id="make_point_step",
            return_name="point",
            selected_version_id=verified.version_id,
            logical_state_key=verified.logical_state_key,
            computation_key=verified.computation_key,
            previous_version_id=verified.previous_version_id,
            source_version_ids=verified.source_version_ids,
            runtime_destination_key=verified.runtime_destination,
        ),
    )
    context = SimpleNamespace(
        manifest=SimpleNamespace(
            context_id="context-2",
            problem_id=checkpoint.problem_id,
            family_id=checkpoint.family_id,
            family_spec_hash=checkpoint.family_spec_hash,
            capability_pack_hash=checkpoint.capability_pack_hash,
        )
    )

    result = build_functional_retry_graph_checkpoint(
        context=context,
        reconciliation=reconciliation,
        call_memory=call_memory,
        provenance=provenance,
    )

    assert result.committed_calls[0].output_version_ids == (
        verified.version_id,
    )
    assert tuple(
        item.return_name for item in result.verified_versions
    ) == ("point",)


@pytest.mark.parametrize(
    "missing",
    ("call_payload", "identity_key", "call_memory"),
)
def test_committed_checkpoint_metadata_is_fail_closed(
    missing: str,
) -> None:
    inputs, _verified = _checkpoint_builder_inputs()
    reconciliation = inputs["reconciliation"]
    call_memory = inputs["call_memory"]
    if missing == "call_payload":
        reconciliation.plan.scopes = (
            SimpleNamespace(scope_id="i", calls=()),
        )
    elif missing == "identity_key":
        reconciliation.state_placement_decisions = ()
    else:
        call_memory.entries = ()

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match=(
            "planner.retry_version_checkpoint_invalid.*"
            f"{missing}"
        ),
    ):
        build_functional_retry_graph_checkpoint(**inputs)


def test_unanchored_committed_dependency_fails_entire_goal_checkpoint() -> None:
    inputs, _verified = _checkpoint_builder_inputs()
    reconciliation = inputs["reconciliation"]
    call_memory = inputs["call_memory"]
    committed = _checkpoint().committed_calls[0]
    unanchored_call = SimpleNamespace(
        call_id="prepare_value",
        to_payload=lambda: {
            "call_id": "prepare_value",
            "capability_id": "prepare_value",
            "args": {},
            "return_bindings": {},
            "strategy": "prepare",
            "reason": "goal dependency",
        },
    )
    reconciliation.plan.calls = (
        *reconciliation.plan.calls,
        unanchored_call,
    )
    reconciliation.plan.scopes = (
        SimpleNamespace(
            scope_id="i",
            calls=(
                *reconciliation.plan.scopes[0].calls,
                unanchored_call,
            ),
        ),
    )
    reconciliation.calls = (
        *reconciliation.calls,
        SimpleNamespace(call_id="prepare_value", returns=()),
    )
    reconciliation.projection_map = (
        *reconciliation.projection_map,
        SimpleNamespace(
            call_id="prepare_value",
            step_ids=("prepare_value_step",),
        ),
    )
    reconciliation.state_placement_decisions = (
        *reconciliation.state_placement_decisions,
        {
            "canonical_call_id": "prepare_value",
            "identity_key": committed.identity_key.to_payload(),
        },
    )
    reconciliation.call_placements = (
        *reconciliation.call_placements,
        SimpleNamespace(
            canonical_call_id="prepare_value",
            execution_scope_id="i",
            return_scopes={},
        ),
    )
    call_memory.committed_call_ids = (
        *call_memory.committed_call_ids,
        "prepare_value",
    )
    call_memory.entries = (
        *call_memory.entries,
        SimpleNamespace(
            call_id="prepare_value",
            committed_goal_handles=("answer:i.P",),
            result_snapshots=(),
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match=(
            "planner.retry_version_checkpoint_invalid.*"
            "prepare_value.*no typed output version anchor"
        ),
    ):
        build_functional_retry_graph_checkpoint(**inputs)


def test_same_attempt_locked_projection_uses_checkpoint_only() -> None:
    checkpoint = _checkpoint()

    committed = _checkpoint_committed_candidate_calls(checkpoint)

    assert committed == (
        {
            "scope_id": "i",
            "call": checkpoint.committed_calls[0].call_payload,
        },
    )


def test_committed_reuse_anchors_canonical_producer_version() -> None:
    inputs, verified = _checkpoint_builder_inputs(
        canonical_producer_call_id="existing_producer",
    )

    result = build_functional_retry_graph_checkpoint(**inputs)

    assert result.committed_calls[0].output_version_ids == (
        verified.version_id,
    )
    assert result.verified_versions[0].canonical_producer_call_id == (
        "existing_producer"
    )


def test_retry_checkpoint_reuse_keeps_wire_object_bindings_strict() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    expected = checkpoint.verified_versions[0]
    expected_source = MathObjectId(
        "point:problem:A",
        "point",
        "problem",
    )
    drifted_source = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    expected_key = ComputationKey(
        expected.computation_key.capability_id,
        (
            ArgVersionBinding(
                "source_object",
                0,
                object_id=expected_source,
            ),
        ),
    )
    drifted_key = ComputationKey(
        expected.computation_key.capability_id,
        (
            ArgVersionBinding(
                "source_object",
                0,
                object_id=drifted_source,
            ),
        ),
    )
    checkpoint = replace(
        checkpoint,
        committed_calls=(
            replace(
                committed,
                canonical_call_id="reuse_point",
                call_payload={
                    **committed.call_payload,
                    "call_id": "reuse_point",
                    "args": {
                        "source_object": {
                            "kind": "point",
                            "ref": "A",
                        }
                    },
                },
                identity_key=FunctionalCallIdentityKey(
                    expected_key,
                    committed.identity_key.state_effect_key,
                ),
            ),
        ),
        verified_versions=(
            replace(
                expected,
                canonical_producer_call_id="existing_producer",
                computation_key=expected_key,
            ),
        ),
    )
    allocation = SimpleNamespace(
        return_name=expected.return_name,
        selected_version_id=expected.version_id,
        logical_state_key=expected.logical_state_key,
        computation_key=drifted_key,
        previous_version_id=expected.previous_version_id,
        source_version_ids=expected.source_version_ids,
        valid_scope=expected.valid_scope_id,
        canonical_producer_call_id="existing_producer",
    )
    reconciliation = SimpleNamespace(
        calls=(
            SimpleNamespace(
                call_id="reuse_point",
                returns=(allocation,),
            ),
        ),
        call_aliases={},
        state_placement_decisions=(
            {
                "canonical_call_id": "reuse_point",
                "identity_key": FunctionalCallIdentityKey(
                    expected_key,
                    committed.identity_key.state_effect_key,
                ).to_payload(),
            },
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_state_version_drift",
    ):
        verify_restored_checkpoint(
            checkpoint,
            reconciliation=reconciliation,
            handle_registry=SimpleNamespace(
                ancestor_scopes=lambda _scope_id: ("problem",),
            ),
        )


def test_retry_checkpoint_manifest_mismatch_is_configuration_error() -> None:
    checkpoint = _checkpoint()
    context = SimpleNamespace(
        manifest=SimpleNamespace(
            problem_id="different-problem",
            family_id=checkpoint.family_id,
            family_spec_hash=checkpoint.family_spec_hash,
            capability_pack_hash=checkpoint.capability_pack_hash,
        )
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_context_incompatible",
    ):
        validate_checkpoint_manifest(checkpoint, context=context)


def test_retry_checkpoint_ignores_transitive_provenance_versions() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    expected = checkpoint.verified_versions[0]
    incidental_object = MathObjectId(
        "point:problem:Q",
        "point",
        "problem",
    )
    incidental_version = StateVersionId(
        StateSlotId(
            LogicalStateKey(
                incidental_object,
                "coordinate",
                "Point",
            ),
            "problem",
        ),
        1,
    )
    checkpoint = replace(
        checkpoint,
        verified_versions=(
            replace(
                expected,
                source_version_ids=(
                    *expected.source_version_ids,
                    incidental_version,
                ),
            ),
        ),
    )
    allocation = SimpleNamespace(
        return_name=expected.return_name,
        selected_version_id=expected.version_id,
        logical_state_key=expected.logical_state_key,
        computation_key=expected.computation_key,
        previous_version_id=expected.previous_version_id,
        source_version_ids=expected.source_version_ids,
        valid_scope=expected.valid_scope_id,
    )
    reconciliation = SimpleNamespace(
        calls=(
            SimpleNamespace(
                call_id=committed.canonical_call_id,
                returns=(allocation,),
            ),
        ),
        state_placement_decisions=(
            {
                "canonical_call_id": committed.canonical_call_id,
                "identity_key": committed.identity_key.to_payload(),
            },
        ),
    )

    verify_restored_checkpoint(
        checkpoint,
        reconciliation=reconciliation,
        handle_registry=SimpleNamespace(
            ancestor_scopes=lambda _scope_id: ("problem",),
        ),
    )


def test_retry_checkpoint_rejects_direct_transition_predecessor_drift() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    expected = checkpoint.verified_versions[0]
    wrong_previous = StateVersionId(
        expected.previous_version_id.slot_id,
        expected.previous_version_id.ordinal + 4,
    )
    allocation = SimpleNamespace(
        return_name=expected.return_name,
        selected_version_id=expected.version_id,
        logical_state_key=expected.logical_state_key,
        computation_key=expected.computation_key,
        previous_version_id=wrong_previous,
        source_version_ids=(),
        valid_scope=expected.valid_scope_id,
    )
    reconciliation = SimpleNamespace(
        calls=(
            SimpleNamespace(
                call_id=committed.canonical_call_id,
                returns=(allocation,),
            ),
        ),
        state_placement_decisions=(
            {
                "canonical_call_id": committed.canonical_call_id,
                "identity_key": committed.identity_key.to_payload(),
            },
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_transition_chain_drift",
    ):
        verify_restored_checkpoint(
            checkpoint,
            reconciliation=reconciliation,
            handle_registry=SimpleNamespace(
                ancestor_scopes=lambda _scope_id: ("problem",),
            ),
        )


def test_retry_checkpoint_rejects_missing_committed_allocation() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    reconciliation = SimpleNamespace(
        calls=(
            SimpleNamespace(
                call_id=committed.canonical_call_id,
                returns=(),
            ),
        ),
        state_placement_decisions=(
            {
                "canonical_call_id": committed.canonical_call_id,
                "identity_key": committed.identity_key.to_payload(),
            },
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_state_version_drift.*missing committed return",
    ):
        verify_restored_checkpoint(
            checkpoint,
            reconciliation=reconciliation,
            handle_registry=SimpleNamespace(
                ancestor_scopes=lambda _scope_id: ("problem",),
            ),
        )


def test_retry_checkpoint_follows_canonical_alias_for_pinned_call() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    expected = checkpoint.verified_versions[0]
    owner = SimpleNamespace(
        call_id="canonical_owner",
        returns=(
            SimpleNamespace(
                return_name=expected.return_name,
                selected_version_id=expected.version_id,
                logical_state_key=expected.logical_state_key,
                computation_key=expected.computation_key,
                previous_version_id=expected.previous_version_id,
                source_version_ids=expected.source_version_ids,
                valid_scope=expected.valid_scope_id,
                canonical_producer_call_id="canonical_owner",
            ),
        ),
    )
    reconciliation = SimpleNamespace(
        calls=(owner,),
        call_aliases={"make_point": "canonical_owner"},
        state_placement_decisions=(
            {
                "canonical_call_id": "canonical_owner",
                "identity_key": committed.identity_key.to_payload(),
            },
        ),
    )

    verify_restored_checkpoint(
        checkpoint,
        reconciliation=reconciliation,
        handle_registry=SimpleNamespace(
            ancestor_scopes=lambda _scope_id: ("problem",),
        ),
    )


def test_retry_checkpoint_recomputes_resolver_object_metadata() -> None:
    checkpoint = _checkpoint()
    committed = checkpoint.committed_calls[0]
    expected = checkpoint.verified_versions[0]
    resolver_symbol = MathObjectId(
        "symbol:problem:m",
        "symbol",
        "problem",
    )
    checkpoint_key = replace(
        expected.computation_key,
        arg_bindings=(
            *expected.computation_key.arg_bindings,
            ArgVersionBinding(
                "free_parameters",
                0,
                object_id=resolver_symbol,
            ),
        ),
    )
    checkpoint = replace(
        checkpoint,
        committed_calls=(
            replace(
                committed,
                identity_key=replace(
                    committed.identity_key,
                    computation_key=checkpoint_key,
                ),
            ),
        ),
        verified_versions=(
            replace(expected, computation_key=checkpoint_key),
        ),
    )
    allocation = SimpleNamespace(
        return_name=expected.return_name,
        selected_version_id=expected.version_id,
        logical_state_key=expected.logical_state_key,
        computation_key=expected.computation_key,
        previous_version_id=expected.previous_version_id,
        source_version_ids=expected.source_version_ids,
        valid_scope=expected.valid_scope_id,
        canonical_producer_call_id="make_point",
    )
    reconciliation = SimpleNamespace(
        calls=(
            SimpleNamespace(
                call_id="make_point",
                returns=(allocation,),
            ),
        ),
        call_aliases={},
        state_placement_decisions=(
            {
                "canonical_call_id": "make_point",
                "identity_key": FunctionalCallIdentityKey(
                    expected.computation_key,
                    committed.identity_key.state_effect_key,
                ).to_payload(),
            },
        ),
    )

    verify_restored_checkpoint(
        checkpoint,
        reconciliation=reconciliation,
        handle_registry=SimpleNamespace(
            ancestor_scopes=lambda _scope_id: ("problem",),
        ),
    )


def test_answer_check_runtime_verifies_revoked_committed_version() -> None:
    expected = _checkpoint()
    actual = replace(
        expected,
        committed_calls=(),
        verified_versions=(
            replace(
                expected.verified_versions[0],
                status="runtime_verified",
            ),
        ),
    )

    verify_restored_runtime_checkpoint(expected, actual)

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_state_version_drift",
    ):
        verify_restored_runtime_checkpoint(
            expected,
            replace(
                actual,
                verified_versions=(
                    replace(
                        actual.verified_versions[0],
                        result_form="open_state",
                    ),
                ),
            ),
        )


def test_retry_dependency_graph_uses_version_edges() -> None:
    checkpoint = _checkpoint()
    version_id = checkpoint.verified_versions[0].version_id
    reconciliation = SimpleNamespace(
        dependency_graph={"producer": (), "consumer": ()},
        calls=(
            SimpleNamespace(
                call_id="producer",
                returns=(
                    SimpleNamespace(
                        selected_version_id=version_id,
                        canonical_producer_call_id="producer",
                        source_version_ids=(),
                        previous_version_id=None,
                    ),
                ),
            ),
            SimpleNamespace(
                call_id="consumer",
                returns=(
                    SimpleNamespace(
                        selected_version_id=None,
                        canonical_producer_call_id=None,
                        source_version_ids=(version_id,),
                        previous_version_id=None,
                    ),
                ),
            ),
        ),
    )

    graph = expand_retry_dependency_graph_with_versions(reconciliation)

    assert graph["consumer"] == ("producer",)
