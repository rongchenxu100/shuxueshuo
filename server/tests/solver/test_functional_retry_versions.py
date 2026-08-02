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
    preserve_committed_retry_checkpoint,
    restore_committed_calls,
    validate_checkpoint_manifest,
    verify_restored_checkpoint,
    verify_restored_runtime_checkpoint,
)
from shuxueshuo_server.solver.runtime.functional_call_memory import (
    FunctionalCallMemory,
    FunctionalCallMemoryEntry,
    FunctionalResultSnapshot,
    _compact_symbolic_closure_result,
)
from shuxueshuo_server.solver.runtime.planner_retry_projection import (
    _typed_committed_candidate_calls,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    _compact_functional_runtime_verified,
    _functional_previous_attempt_state,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    _checkpoint_committed_candidate_calls,
    _with_checkpoint_commit_status,
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
from shuxueshuo_server.solver.runtime.strategy_models import (
    SymbolicClosureProvenance,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    SymbolicClosureExecutionResult,
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
                binding_signature="binding-v1",
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
                free_symbol_ids=(),
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


def _closure_provenance(
    *,
    target_value: str = "1-c",
) -> SymbolicClosureProvenance:
    target = MathObjectId("symbol:problem:b", "symbol", "problem")
    residual = MathObjectId("symbol:problem:c", "symbol", "problem")
    return SymbolicClosureProvenance(
        status="unique",
        target_object_id=target,
        target_value=target_value,
        substitutions=((target, target_value),),
        residual_symbol_ids=(residual,),
        branch_count=1,
        equation_builder="quadratic_constraints",
        target_binding="target_parameter",
        equation_sources=("curve_points",),
        preserved_symbol_ids=(residual,),
        affected_returns=("point",),
    )


def _binding_context(signature: str = "binding-v1") -> SimpleNamespace:
    return SimpleNamespace(
        signature_for_call=lambda _call_id: signature,
    )


def test_retry_checkpoint_round_trips_symbolic_closure_provenance() -> None:
    checkpoint = _checkpoint()
    record = replace(
        checkpoint.verified_versions[0],
        symbolic_closure_provenance=_closure_provenance(),
    )
    checkpoint = replace(checkpoint, verified_versions=(record,))

    restored = FunctionalRetryGraphCheckpoint.from_payload(
        checkpoint.to_payload()
    )

    assert (
        restored.verified_versions[0].symbolic_closure_provenance
        == _closure_provenance()
    )


def test_runtime_checkpoint_rejects_symbolic_closure_drift() -> None:
    checkpoint = _checkpoint()
    expected_record = replace(
        checkpoint.verified_versions[0],
        symbolic_closure_provenance=_closure_provenance(),
    )
    expected = replace(checkpoint, verified_versions=(expected_record,))
    actual_record = replace(
        expected_record,
        symbolic_closure_provenance=_closure_provenance(target_value="2-c"),
        status="runtime_verified",
    )
    actual = replace(expected, verified_versions=(actual_record,))

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_symbolic_closure_drift",
    ):
        verify_restored_runtime_checkpoint(expected, actual)


def test_runtime_checkpoint_accepts_equivalent_symbolic_closure_forms() -> None:
    expected_record = replace(
        _checkpoint().verified_versions[0],
        symbolic_closure_provenance=_closure_provenance(
            target_value="1-c",
        ),
    )
    actual_record = replace(
        expected_record,
        status="runtime_verified",
        symbolic_closure_provenance=_closure_provenance(
            target_value="-c+1",
        ),
    )
    expected = replace(
        _checkpoint(),
        verified_versions=(expected_record,),
    )
    actual = replace(
        expected,
        committed_calls=(),
        verified_versions=(actual_record,),
    )

    verify_restored_runtime_checkpoint(expected, actual)


def test_runtime_checkpoint_does_not_cancel_domain_sensitive_quotient() -> None:
    expected_record = replace(
        _checkpoint().verified_versions[0],
        symbolic_closure_provenance=_closure_provenance(
            target_value="x/x",
        ),
    )
    actual_record = replace(
        expected_record,
        status="runtime_verified",
        symbolic_closure_provenance=_closure_provenance(
            target_value="1",
        ),
    )
    expected = replace(
        _checkpoint(),
        verified_versions=(expected_record,),
    )
    actual = replace(
        expected,
        committed_calls=(),
        verified_versions=(actual_record,),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_symbolic_closure_drift",
    ):
        verify_restored_runtime_checkpoint(expected, actual)


def test_shadow_closure_result_projects_read_only_retry_summary() -> None:
    result = SymbolicClosureExecutionResult(
        status="unique",
        provenance=_closure_provenance(),
    )

    assert _compact_symbolic_closure_result(result) == {
        "status": "unique",
        "branches": 1,
        "target": "b",
        "value": "1-c",
        "remaining_free": ["c"],
        "equation_sources": ["curve_points"],
    }


def test_prompt_closure_summary_is_compact_and_hides_typed_identity() -> None:
    projected = _compact_functional_runtime_verified(
        [
            {
                "call_id": "solve_b",
                "execution_status": "runtime_verified",
                "results": [
                    {
                        "return": "parameter_value",
                        "type": "ParameterValue",
                        "value": "b=1-c",
                        "state_version_id": {"ordinal": 1},
                        "symbolic_closure": {
                            "target": "b",
                            "status": "unique",
                            "value": "1-c",
                            "branches": 1,
                            "remaining_free": ["c"],
                            "equation_sources": ["curve_point"],
                            "internal_builder": "quadratic_constraints",
                        },
                    }
                ],
            }
        ],
        issues=[],
    )

    serialized = str(projected)
    closure = projected[0]["closure"]
    assert closure == {
        "target": "b",
        "status": "unique",
        "branches": 1,
        "remaining_free": ["c"],
        "equation_sources": ["curve_point"],
    }
    assert "state_version_id" not in serialized
    assert "internal_builder" not in serialized
    assert "closure" not in projected[0]["results"][0]


@pytest.mark.parametrize("closure_value", ("c", "1"))
def test_prompt_closure_summary_does_not_use_substring_deduplication(
    closure_value: str,
) -> None:
    projected = _compact_functional_runtime_verified(
        [
            {
                "call_id": "solve_b",
                "execution_status": "runtime_verified",
                "results": [
                    {
                        "return": "parameter_value",
                        "type": "ParameterValue",
                        "value": "b=1-c",
                        "symbolic_closure": {
                            "target": "b",
                            "status": "unique",
                            "value": closure_value,
                            "branches": 1,
                        },
                    }
                ],
            }
        ],
        issues=[],
    )

    assert projected[0]["closure"]["value"] == closure_value


@pytest.mark.parametrize("parameter_value", ("a<=3", "a>=3", "a==3"))
def test_prompt_closure_summary_does_not_parse_relations_as_assignments(
    parameter_value: str,
) -> None:
    projected = _compact_functional_runtime_verified(
        [
            {
                "call_id": "solve_a",
                "execution_status": "runtime_verified",
                "results": [
                    {
                        "return": "parameter_value",
                        "type": "ParameterValue",
                        "value": parameter_value,
                        "symbolic_closure": {
                            "target": "a",
                            "status": "unique",
                            "value": "3",
                            "branches": 1,
                        },
                    }
                ],
            }
        ],
        issues=[],
    )

    assert projected[0]["closure"]["value"] == "3"


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
        handle="answer:i.P",
        state_handle=None,
        bound_ref=SimpleNamespace(kind="answer", ref="i.P"),
        source_version_ids=(),
        previous_version_id=None,
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
                resolved_args={},
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
        functional_binding_context=SimpleNamespace(
            signature_for_call=lambda _call_id: "binding-v1",
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
                        free_parameters=(),
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


def test_retry_checkpoint_round_trip_drops_scope_emptied_by_restore() -> None:
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
            {"scope_id": "ii_2", "label": "II-2", "calls": []},
        ],
    }

    restored = restore_committed_calls(candidate, checkpoint)
    restored_again = restore_committed_calls(restored, checkpoint)

    assert restored_again == restored
    scopes = {item["scope_id"]: item for item in restored["scopes"]}
    assert "ii" not in scopes
    assert scopes["i"]["calls"] == [
        checkpoint.committed_calls[0].call_payload
    ]
    # Empty scopes unrelated to checkpoint restoration remain available to
    # strict wire validation.
    assert scopes["ii_2"]["calls"] == []
    assert checkpoint.pinned_execution_scopes == {
        "make_point": "problem"
    }
    assert checkpoint.pinned_return_scopes == {
        "make_point": {"point": "problem"}
    }


def test_checkpoint_validation_requires_binding_signature_in_partial_mode() -> None:
    checkpoint = _checkpoint()
    invalid = replace(
        checkpoint,
        committed_calls=(
            replace(checkpoint.committed_calls[0], binding_signature=None),
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_binding_checkpoint_invalid",
    ):
        verify_restored_checkpoint(
            invalid,
            reconciliation=SimpleNamespace(),
            handle_registry=SimpleNamespace(),
            verify_reconciled_graph=False,
        )


def test_legacy_checkpoint_without_binding_signature_downgrades_at_load_boundary() -> None:
    payload = _checkpoint().to_payload()
    payload["committed_calls"][0].pop("binding_signature")

    migrated = FunctionalRetryGraphCheckpoint.from_payload(payload)

    assert migrated.committed_calls == ()
    assert {item.status for item in migrated.verified_versions} == {
        "runtime_verified"
    }
    assert migrated.compatibility_events == (
        "legacy_binding_signature_missing_downgraded",
    )


def test_runtime_checkpoint_requires_binding_signature_on_both_sides() -> None:
    checkpoint = _checkpoint()
    missing_expected = replace(
        checkpoint,
        committed_calls=(
            replace(checkpoint.committed_calls[0], binding_signature=None),
        ),
    )
    missing_actual = replace(
        checkpoint,
        committed_calls=(
            replace(checkpoint.committed_calls[0], binding_signature=None),
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_binding_checkpoint_invalid",
    ):
        verify_restored_runtime_checkpoint(missing_expected, checkpoint)
    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_binding_checkpoint_invalid",
    ):
        verify_restored_runtime_checkpoint(checkpoint, missing_actual)


def test_partial_observation_preserves_only_prior_committed_checkpoint() -> None:
    committed = _checkpoint()
    committed_version = committed.verified_versions[0]
    provisional_version_id = StateVersionId(
        committed_version.version_id.slot_id,
        committed_version.version_id.ordinal + 1,
    )
    observed = replace(
        committed,
        source_context_id="context-2",
        committed_calls=(),
        verified_versions=(
            replace(committed_version, status="runtime_verified"),
            replace(
                committed_version,
                version_id=provisional_version_id,
                status="runtime_verified",
            ),
        ),
    )

    merged = preserve_committed_retry_checkpoint(committed, observed)

    assert merged.committed_calls == committed.committed_calls
    assert merged.verified_versions == (
        committed_version,
        replace(
            committed_version,
            version_id=provisional_version_id,
            status="runtime_verified",
        ),
    )


def test_preserved_commit_projects_relevant_result_as_locked_context() -> None:
    checkpoint = _checkpoint()
    memory = FunctionalCallMemory(
        entries=(
            FunctionalCallMemoryEntry(
                call_id="make_point",
                capability_id="construct_point",
                scope_id="i",
                execution_status="runtime_verified",
                result_snapshots=(
                    FunctionalResultSnapshot(
                        return_name="point",
                        value_type="Point",
                        semantic_ref="P",
                        value={"x": 1, "y": 2},
                        actual_form="closed_state",
                    ),
                ),
            ),
        ),
        runtime_verified_call_ids=("make_point",),
    )
    projected = _with_checkpoint_commit_status(
        memory,
        checkpoint=checkpoint,
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
                    "call_memory": projected.to_payload(),
                    "runtime_verified_calls": [],
                    "issues": [
                        {
                            "layer": "functional_reconciliation",
                            "code": "synthetic_failure",
                            "message": "repair another call",
                            "details": {
                                "locked_result_refs": ["make_point.point"]
                            },
                        }
                    ],
                }
            }
        ]
    )["latest_retry_state"]

    assert projected.entries[0].commit_status == "goal_committed"
    assert prompt_state["runtime_verified"] == []
    assert prompt_state["locked_context_results"] == [
        {
            "call_id": "make_point",
            "results": [
                {
                    "return": "point",
                    "type": "Point",
                    "ref": "P",
                    "value": {"x": 1, "y": 2},
                    "form": "closed_state",
                }
            ],
        }
    ]


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
    base_identity_key = _checkpoint().committed_calls[0].identity_key
    identity_key = FunctionalCallIdentityKey(
        base_identity_key.computation_key,
        StateEffectKey(
            (
                LogicalReturnEffect(
                    "angle_equality",
                    None,
                    "value_only",
                    "value",
                ),
            )
        ),
    )
    reconciliation.state_placement_decisions = (
        {
            "canonical_call_id": "make_point",
            "identity_key": identity_key.to_payload(),
        },
    )
    value_call = SimpleNamespace(
        call_id="make_point",
        returns=(
            SimpleNamespace(
                return_name="angle_equality",
                canonical_producer_call_id="make_point",
                valid_scope="i",
                free_symbol_refs=("symbol:ii:static_parameter",),
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
                    free_parameters=("_axis_param_E",),
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
            free_symbol_refs=("_axis_param_E",),
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
                functional_binding_context=SimpleNamespace(
                    signature_for_call=lambda _call_id: "binding-v1",
                ),
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
        functional_binding_context=SimpleNamespace(
            signature_for_call=lambda _call_id: "binding-v1",
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


def test_checkpoint_does_not_lock_unused_optional_return() -> None:
    inputs, verified = _checkpoint_builder_inputs()
    reconciliation = inputs["reconciliation"]
    call_memory = inputs["call_memory"]
    committed = _checkpoint().committed_calls[0]
    optional_object = MathObjectId(
        "symbol:problem:unused",
        "symbol",
        "problem",
    )
    optional_key = LogicalStateKey(
        optional_object,
        "value",
        "ParameterValue",
    )
    optional_version = StateVersionId(
        StateSlotId(optional_key, "problem"),
        1,
    )
    main_allocation = reconciliation.calls[0].returns[0]
    optional_allocation = SimpleNamespace(
        return_name="optional_parameter",
        canonical_producer_call_id="make_point",
        valid_scope="problem",
        free_symbol_refs=(),
        selected_version_id=optional_version,
        handle="fact:i:optional_parameter",
        state_handle=None,
        bound_ref=None,
        source_version_ids=(),
        previous_version_id=None,
    )
    reconciliation.calls = (
        SimpleNamespace(
            call_id="make_point",
            returns=(main_allocation, optional_allocation),
            resolved_args={},
        ),
    )
    expanded_effect = StateEffectKey(
        (
            *committed.identity_key.state_effect_key.returns,
            LogicalReturnEffect(
                "optional_parameter",
                optional_key,
                "preserve_input_object",
                "create",
            ),
        )
    )
    reconciliation.state_placement_decisions = (
        {
            "canonical_call_id": "make_point",
            "identity_key": FunctionalCallIdentityKey(
                committed.identity_key.computation_key,
                expanded_effect,
            ).to_payload(),
        },
    )
    call_memory.entries = (
        SimpleNamespace(
            call_id=call_memory.entries[0].call_id,
            committed_goal_handles=(
                call_memory.entries[0].committed_goal_handles
            ),
            result_snapshots=(
                *call_memory.entries[0].result_snapshots,
                SimpleNamespace(
                    return_name="optional_parameter",
                    actual_form="closed_state",
                    free_parameters=(),
                    value_omitted_reason=None,
                ),
            ),
        ),
    )
    inputs["provenance"] = (
        *inputs["provenance"],
        SimpleNamespace(
            step_id="make_point_step",
            return_name="optional_parameter",
            selected_version_id=optional_version,
            logical_state_key=optional_key,
            computation_key=verified.computation_key,
            previous_version_id=None,
            source_version_ids=(),
            runtime_destination_key=RuntimeDestinationKey(
                optional_object,
                "value",
                "ParameterValue",
                "$question.symbols.unused",
            ),
        ),
    )

    result = build_functional_retry_graph_checkpoint(**inputs)

    assert result.committed_calls[0].output_version_ids == (
        verified.version_id,
    )
    assert tuple(
        effect.return_name
        for effect in result.committed_calls[0]
        .identity_key.state_effect_key.returns
    ) == ("point",)
    optional_record = next(
        item
        for item in result.verified_versions
        if item.return_name == "optional_parameter"
    )
    assert optional_record.status == "runtime_verified"


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
        functional_binding_context=_binding_context(),
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
        functional_binding_context=_binding_context(),
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
        functional_binding_context=_binding_context(),
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
        functional_binding_context=_binding_context(),
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
        functional_binding_context=_binding_context(),
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
        functional_binding_context=_binding_context(),
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


def test_runtime_checkpoint_compares_free_symbols_by_math_object_identity() -> None:
    checkpoint = _checkpoint()
    symbol_id = MathObjectId(
        "symbol:problem:a",
        "symbol",
        "problem",
    )
    expected_record = replace(
        checkpoint.verified_versions[0],
        free_symbol_refs=("a",),
        free_symbol_ids=(symbol_id,),
    )
    expected = replace(
        checkpoint,
        verified_versions=(expected_record,),
    )
    observed = replace(
        expected,
        committed_calls=(),
        verified_versions=(
            replace(
                expected_record,
                free_symbol_refs=("symbol:problem:a",),
                status="runtime_verified",
            ),
        ),
    )

    verify_restored_runtime_checkpoint(expected, observed)

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_state_version_drift",
    ):
        verify_restored_runtime_checkpoint(
            expected,
            replace(
                observed,
                verified_versions=(
                    replace(
                        observed.verified_versions[0],
                        free_symbol_ids=(
                            MathObjectId(
                                "symbol:problem:b",
                                "symbol",
                                "problem",
                            ),
                        ),
                    ),
                ),
            ),
        )


def test_runtime_checkpoint_rejects_untyped_free_symbol_identity() -> None:
    checkpoint = _checkpoint()
    checkpoint = replace(
        checkpoint,
        verified_versions=(
            replace(
                checkpoint.verified_versions[0],
                free_symbol_refs=("a",),
                free_symbol_ids=(),
            ),
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_version_checkpoint_invalid",
    ):
        verify_restored_runtime_checkpoint(checkpoint, checkpoint)


def test_partial_runtime_checkpoint_allows_unobserved_committed_return() -> None:
    expected = _checkpoint()
    partial = replace(
        expected,
        committed_calls=(),
        verified_versions=(),
        verified_results=(),
    )

    verify_restored_runtime_checkpoint(
        expected,
        partial,
        require_complete_evidence=False,
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_state_version_drift",
    ):
        verify_restored_runtime_checkpoint(expected, partial)


def test_partial_runtime_checkpoint_rejects_observed_version_drift() -> None:
    expected = _checkpoint()
    observed = replace(
        expected,
        committed_calls=(),
        verified_versions=(
            replace(
                expected.verified_versions[0],
                result_form="open_state",
                status="runtime_verified",
            ),
        ),
    )

    with pytest.raises(
        FunctionalRetryCheckpointError,
        match="planner.retry_state_version_drift",
    ):
        verify_restored_runtime_checkpoint(
            expected,
            observed,
            require_complete_evidence=False,
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
