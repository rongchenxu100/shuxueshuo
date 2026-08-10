from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    FunctionalProblemBindingContext,
)
from shuxueshuo_server.solver.runtime import (
    functional_transaction_execution as transaction_module,
)
from shuxueshuo_server.solver.runtime import (
    planner_state_context as planner_state_context_module,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContextBuilder,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryCheckpointError,
    FunctionalRetryGraphCheckpoint,
    build_functional_retry_graph_checkpoint,
    functional_retry_graph_checkpoint_schema,
    verify_restored_runtime_checkpoint,
)
from shuxueshuo_server.solver.runtime.functional_call_memory import (
    build_functional_call_memory,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalTransactionalInterpreter,
)
from shuxueshuo_server.solver.runtime.problem_source_provenance import (
    problem_call_source_provenance_schema,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayService,
    transactional_repair_attempt_payload_from_replay,
)

from _problem_planning_support import (
    CASES,
    scope_native_reconciliation_fixture,
)


ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("case", CASES)
def test_five_case_runtime_writes_and_results_share_call_source_authority(
    tmp_path,
    case,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        _catalog,
        plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path / case, case=case)
    sidecar = reconciliation.functional_problem_binding_context
    assert isinstance(sidecar, FunctionalProblemBindingContext)

    attempt = FunctionalTransactionalInterpreter(
        symbolic_closure_mode="authoritative"
    ).execute_attempt(
        raw_plan=plan,
        reconciliation=reconciliation,
        runtime_context=ContextBuilder().build(problem),
        parent_context=planner_context,
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )

    assert attempt.compiled_output is not None, attempt.root_issues
    observed_calls: set[str] = set()
    for call_result in attempt.execution_report.call_results:
        if call_result.status != "verified":
            continue
        expected = sidecar.source_provenance_for_call(call_result.call_id)
        observed_calls.add(call_result.call_id)
        assert call_result.state_writes or call_result.runtime_results
        assert all(
            write.problem_source_provenance == expected
            for write in call_result.state_writes
        )
        assert all(
            result.problem_source_provenance == expected
            for result in call_result.runtime_results
        )
        assert all(
            "problem_source_provenance" not in result.to_payload()
            and result.authority_payload()["problem_source_provenance"]
            == expected.to_payload()
            for result in call_result.runtime_results
        )
        expected_direct_sources = {
            source_unit_id
            for binding in sidecar.inputs_for_call(call_result.call_id)
            if binding.source_kind == "problem_source"
            for source_unit_id in binding.source_unit_ids
        }
        assert set(expected.input_source_unit_ids) == expected_direct_sources

    assert observed_calls
    assert any(
        write.identity_policy == "value_only"
        for write in attempt.diagnostic.state_write_provenance
    )
    answer_aliases = tuple(
        write
        for write in attempt.diagnostic.state_write_provenance
        if write.produced_handle.startswith("answer:")
    )
    assert answer_aliases
    assert all(
        write.problem_source_provenance
        == sidecar.source_provenance_for_call(write.step_id)
        for write in answer_aliases
    )
    call_result_consumers = tuple(
        call_id
        for call_id in observed_calls
        if any(
            binding.source_kind == "call_result"
            for binding in sidecar.inputs_for_call(call_id)
        )
    )
    assert call_result_consumers


@pytest.mark.parametrize("case", CASES)
def test_five_case_retry_checkpoint_records_problem_authority(
    tmp_path,
    case,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        catalog,
        plan,
        validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path / case, case=case)

    checkpoint, sidecar, replay = _recorded_checkpoint(
        plan=plan,
        inputs=inputs,
        registry=registry,
        problem=problem,
        problem_payload=problem_payload,
        planner_context=planner_context,
        validation=validation,
        catalog=catalog,
    )
    checkpoint = FunctionalRetryGraphCheckpoint.from_payload(
        checkpoint.to_payload()
    )
    assert checkpoint.problem_authority is not None
    assert checkpoint.problem_authority.problem_revision_id == (
        sidecar.problem_revision_id
    )
    assert {
        item.canonical_call_id for item in checkpoint.problem_call_authorities
    } == set(sidecar.call_goal_bindings)
    assert all(
        item.problem_source_provenance is not None
        for item in (
            *checkpoint.committed_calls,
            *checkpoint.verified_versions,
            *checkpoint.verified_results,
        )
    )
    context_snapshot = PlannerStateContextBuilder.from_replay_result(
        replay,
        inputs=inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    persisted_writes = tuple(
        item
        for item in context_snapshot.state.state_write_provenance
        if item.get("selected_version_id") is not None
    )
    assert persisted_writes
    assert all(
        item.get("problem_source_provenance") is not None
        for item in persisted_writes
    )
    assert all(
        history.problem_source_provenance is not None
        for slot in context_snapshot.state.state_slots
        for history in slot.write_history
        if history.version_id is not None and history.version_id.ordinal > 0
    )


def test_missing_compiled_problem_provenance_rolls_back_before_method(
    tmp_path,
    monkeypatch,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        _catalog,
        plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASES[0])
    original = transaction_module._stamp_compiled_problem_source_provenance

    def omit_first_write(compiled, provenance):
        stamped = original(compiled, provenance)
        returns = list(stamped.public_returns)
        first = next(
            index
            for index, returned in enumerate(returns)
            if returned.expected_write is not None
        )
        returns[first] = replace(
            returns[first],
            expected_write=replace(
                returns[first].expected_write,
                problem_source_provenance=None,
            ),
        )
        return replace(stamped, public_returns=tuple(returns))

    monkeypatch.setattr(
        transaction_module,
        "_stamp_compiled_problem_source_provenance",
        omit_first_write,
    )
    attempt = FunctionalTransactionalInterpreter(
        symbolic_closure_mode="authoritative"
    ).execute_attempt(
        raw_plan=plan,
        reconciliation=reconciliation,
        runtime_context=ContextBuilder().build(problem),
        parent_context=planner_context,
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )

    assert attempt.compiled_output is None
    assert not attempt.state_writes
    assert not attempt.execution_report.committed_versions
    assert any(
        issue.code == "planner.runtime_problem_provenance_missing"
        for issue in attempt.root_issues
    )


def test_planner_context_hydrates_problem_source_provenance_fail_closed(
    tmp_path,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        _catalog,
        plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASES[0])
    attempt = FunctionalTransactionalInterpreter(
        symbolic_closure_mode="authoritative"
    ).execute_attempt(
        raw_plan=plan,
        reconciliation=reconciliation,
        runtime_context=ContextBuilder().build(problem),
        parent_context=planner_context,
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )
    write = next(
        item
        for item in attempt.state_writes
        if item.selected_version_id is not None
    )
    state = PlannerStateContextBuilder._initial_mutable_state(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
        attempt=1,
        parent_context_id=None,
    )

    planner_state_context_module._apply_state_write_provenance(
        state,
        write.to_payload(),
        require_typed_authority=True,
    )
    hydrated = next(
        history
        for slot in state.state_slots.values()
        for history in slot.write_history
        if history.version_id == write.selected_version_id
    )
    assert hydrated.problem_source_provenance == (
        write.problem_source_provenance
    )

    drifted = write.to_payload()
    drifted["problem_source_provenance"] = {
        **drifted["problem_source_provenance"],
        "canonical_call_id": "call:wrong",
    }
    with pytest.raises(
        ValueError,
        match="planner.runtime_problem_provenance_drift",
    ):
        planner_state_context_module._apply_state_write_provenance(
            state,
            drifted,
            require_typed_authority=True,
        )


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    (
        (
            "problem_revision_id",
            "problem-revision:mutated",
            "planner.retry_problem_revision_drift",
        ),
        (
            "goal_unit_ids",
            ("goal:mutated",),
            "planner.retry_problem_source_binding_drift",
        ),
        (
            "input_source_unit_ids",
            ("unit:mutated",),
            "planner.retry_problem_source_binding_drift",
        ),
        (
            "call_binding_signature",
            "f" * 64,
            "planner.retry_problem_source_binding_drift",
        ),
    ),
)
def test_retry_checkpoint_problem_authority_mutations_fail_loud(
    tmp_path,
    field,
    value,
    expected_code,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        catalog,
        plan,
        validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASES[0])
    checkpoint, _sidecar, _replay = _recorded_checkpoint(
        plan=plan,
        inputs=inputs,
        registry=registry,
        problem=problem,
        problem_payload=problem_payload,
        planner_context=planner_context,
        validation=validation,
        catalog=catalog,
    )
    authority = checkpoint.problem_call_authorities[0]
    drifted = replace(
        checkpoint,
        problem_call_authorities=(
            replace(authority, **{field: value}),
            *checkpoint.problem_call_authorities[1:],
        ),
    )

    with pytest.raises(FunctionalRetryCheckpointError) as exc_info:
        verify_restored_runtime_checkpoint(checkpoint, drifted)

    assert exc_info.value.code == expected_code


def test_answer_check_revocation_keeps_provisional_problem_provenance(
    tmp_path,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        catalog,
        plan,
        validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path, case=CASES[0])
    _checkpoint_value, _sidecar, replay = _recorded_checkpoint(
        plan=plan,
        inputs=inputs,
        registry=registry,
        problem=problem,
        problem_payload=problem_payload,
        planner_context=planner_context,
        validation=validation,
        catalog=catalog,
    )

    payload = transactional_repair_attempt_payload_from_replay(
        replay,
        attempt=2,
        errors=("answer_mismatch: synthetic",),
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )

    assert payload is not None
    checkpoint = FunctionalRetryGraphCheckpoint.from_payload(
        payload["functional_retry_graph_checkpoint"]
    )
    assert checkpoint.problem_authority is not None
    assert not checkpoint.committed_calls
    provisional = (
        *checkpoint.verified_versions,
        *checkpoint.verified_results,
    )
    assert provisional
    assert {item.status for item in provisional} == {
        "runtime_verified"
    }
    assert all(
        item.problem_source_provenance is not None for item in provisional
    )


def _recorded_checkpoint(
    *,
    plan,
    inputs,
    registry,
    problem,
    problem_payload,
    planner_context,
    validation,
    catalog,
):
    replay = PlannerRetryReplayService(
        functional_transaction_mode="context_authoritative",
        functional_symbolic_closure_mode="authoritative",
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        validation_report=validation,
        problem_binding_catalog=catalog,
    )

    attempt_result = replay.transactional_attempt_result
    assert attempt_result is not None
    diagnostic = attempt_result.diagnostic
    verified_call_ids = tuple(
        item.call_id
        for item in attempt_result.execution_report.call_states
        if item.status == "verified"
    )
    call_memory = build_functional_call_memory(
        replay.functional_reconciliation,
        catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
        runtime_verified_call_ids=verified_call_ids,
        runtime_results=diagnostic.runtime_results,
        provenance=diagnostic.state_write_provenance,
        goal_report=attempt_result.goal_report,
        active_issues=(),
        attempt=1,
    )
    checkpoint = build_functional_retry_graph_checkpoint(
        context=planner_context,
        reconciliation=replay.functional_reconciliation,
        call_memory=call_memory,
        provenance=diagnostic.state_write_provenance,
    )
    sidecar = replay.functional_reconciliation.functional_problem_binding_context
    assert sidecar is not None
    return checkpoint, sidecar, replay


def test_problem_provenance_and_checkpoint_schema_snapshots() -> None:
    provenance_schema = problem_call_source_provenance_schema()
    checkpoint_schema = functional_retry_graph_checkpoint_schema()
    checked_provenance = json.loads(
        (
            ROOT
            / "internal/schemas/problem-call-source-provenance.schema.json"
        ).read_text(encoding="utf-8")
    )
    checked_checkpoint = json.loads(
        (
            ROOT
            / "internal/schemas/functional-retry-graph-checkpoint.schema.json"
        ).read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(provenance_schema)
    Draft202012Validator.check_schema(checkpoint_schema)
    assert checked_provenance == provenance_schema
    assert checked_checkpoint == checkpoint_schema
