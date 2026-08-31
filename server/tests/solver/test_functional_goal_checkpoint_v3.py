from __future__ import annotations

from copy import deepcopy
import json

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FUNCTIONAL_EXECUTION_RESTORE_STATE_CONTRACT,
    FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT,
    FunctionalGoalExecutionCheckpoint,
    FunctionalGoalExecutionCheckpointError,
    ScopedFunctionalGoalExecutionService,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


def _execute(tmp_path, case="tj-2026-heping-yimo-25"):
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    result = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(load_v2_fixture_payload(case), ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )
    assert result.checkpoint is not None
    return result.checkpoint


def test_goal_checkpoint_v3_round_trip_preserves_typed_restore_authority(tmp_path) -> None:
    checkpoint = _execute(tmp_path)
    payload = checkpoint.authority_payload()
    restored = FunctionalGoalExecutionCheckpoint.from_payload(payload)

    assert checkpoint.schema_version == FUNCTIONAL_GOAL_EXECUTION_CHECKPOINT_CONTRACT
    assert restored.authority_payload() == payload
    assert restored.restore_state.schema_version == (
        FUNCTIONAL_EXECUTION_RESTORE_STATE_CONTRACT
    )
    assert restored.restore_state.state_versions
    assert restored.restore_state.call_results
    assert restored.restore_state.compiled_calls
    assert restored.restore_state.finalized_call_bindings
    assert restored.restore_state.source_read_signatures
    assert restored.restore_state.runtime_write_signatures
    assert restored.restore_state.publication_signatures
    assert restored.restore_state.macro_preparations
    assert any(
        call.get("method_output_writes")
        for call in restored.restore_state.compiled_calls
    )
    for call in restored.restore_state.compiled_calls:
        for authority in call.get("method_output_writes", ()):
            assert authority["schema_version"] == (
                "method-output-write-authority/v1"
            )
            assert authority["authority_signature"]


def test_goal_checkpoint_prompt_does_not_expose_private_restore_state(tmp_path) -> None:
    checkpoint = _execute(tmp_path)
    prompt_payload = checkpoint.to_prompt_payload()
    encoded = json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)

    assert "restore_state" not in prompt_payload
    assert "StateVersionId" not in encoded
    assert "runtime_path" not in encoded
    assert "macro_preparations" not in encoded


def test_deserialized_checkpoint_cannot_restore_without_in_process_typed_seed(
    tmp_path,
) -> None:
    checkpoint = _execute(tmp_path)
    restored = FunctionalGoalExecutionCheckpoint.from_payload(
        checkpoint.authority_payload()
    )
    call_id = restored.restore_state.compiled_calls[0]["call_id"]

    with pytest.raises(FunctionalGoalExecutionCheckpointError) as error:
        restored.restore_state.seed_for_calls(frozenset((call_id,)))

    assert error.value.code == "functional.goal_retry_typed_checkpoint_missing"


def test_goal_checkpoint_v2_is_rejected_without_hydration(tmp_path) -> None:
    payload = _execute(tmp_path).authority_payload()
    payload["schema_version"] = "functional-goal-execution-checkpoint/v2"

    with pytest.raises(FunctionalGoalExecutionCheckpointError) as error:
        FunctionalGoalExecutionCheckpoint.from_payload(payload)

    assert error.value.code == "planner.goal_checkpoint_version_unsupported"


def test_restore_namespace_signature_drift_fails_loud(tmp_path) -> None:
    payload = deepcopy(_execute(tmp_path).authority_payload())
    payload["restore_state"]["state_versions"][0]["typed_value"][
        "source"
    ] = "tampered"

    with pytest.raises(FunctionalGoalExecutionCheckpointError) as error:
        FunctionalGoalExecutionCheckpoint.from_payload(payload)

    assert error.value.path == "$.restore_state.restore_signature"


def test_method_output_authority_drift_fails_checkpoint_restore(tmp_path) -> None:
    payload = deepcopy(_execute(tmp_path).authority_payload())
    compiled_call = next(
        item
        for item in payload["restore_state"]["compiled_calls"]
        if item.get("method_output_writes")
    )
    compiled_call["method_output_writes"][0]["valid_scope"] = "sibling"

    with pytest.raises(FunctionalGoalExecutionCheckpointError) as error:
        FunctionalGoalExecutionCheckpoint.from_payload(payload)

    assert error.value.path == "$.restore_state.restore_signature"


def test_in_process_checkpoint_filters_exact_calls_without_reselecting_state(
    tmp_path,
) -> None:
    checkpoint = _execute(tmp_path)
    seed = checkpoint.restore_state.runtime_seed
    assert seed is not None and len(seed.call_ids) > 1
    selected_call = seed.call_ids[0]

    filtered = checkpoint.restore_state.seed_for_calls(
        frozenset((selected_call,))
    )

    assert filtered.call_ids == (selected_call,)
    assert set(filtered.source_read_authorities) == {selected_call}
    assert set(filtered.runtime_write_authorities) == {selected_call}
    assert set(filtered.publication_authorities) == {selected_call}
