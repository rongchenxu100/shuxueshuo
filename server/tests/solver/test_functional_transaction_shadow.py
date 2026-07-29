from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

import pytest

from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan import (
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.functional_transaction_shadow import (
    FunctionalTransactionShadowObserver,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.projection import (
    problem_to_llm_payload,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntentExecutionBlocker,
    StepIntentSkippedStep,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayService,
)


def _replay(case_id: str, *, mode: str):
    (
        problem,
        inputs,
        problem_payload,
        registry,
        plan,
        validation,
    ) = _case_runtime(case_id)
    return PlannerRetryReplayService(
        functional_transaction_mode=mode,
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )


def _case_runtime(case_id: str):
    case = FUNCTIONAL_BATCH_CASES[case_id]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    return (
        problem,
        inputs,
        problem_payload,
        registry,
        plan,
        validation,
    )


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_transaction_shadow_has_zero_mismatch(
    case_id: str,
) -> None:
    replay = _replay(case_id, mode="shadow")

    assert replay.output is not None
    assert replay.transactional_shadow_report is not None
    assert replay.transactional_shadow_report.ok
    assert replay.transactional_shadow_report.mismatches == ()
    assert replay.planner_state_context is not None
    assert (
        replay.planner_state_context.state.functional_transaction_shadow
        == replay.transactional_shadow_report.to_payload()
    )

    states = {
        item.call_id: item.status
        for item in replay.transactional_shadow_report.call_states
    }
    assert all(
        states[call_id] == "verified"
        for call_id in replay.transactional_shadow_report.graph.canonical_order
    )
    committed_events = {
        event.call_id
        for event in replay.transactional_shadow_report.events
        if event.event == "state_version_committed"
    }
    assert committed_events
    assert committed_events <= set(
        replay.transactional_shadow_report.graph.canonical_order
    )
    events = replay.transactional_shadow_report.events
    for call_id in replay.transactional_shadow_report.graph.canonical_order:
        call_events = [
            (index, event.event)
            for index, event in enumerate(events)
            if event.call_id == call_id
        ]
        ready_index = next(
            index for index, event in call_events if event == "became_ready"
        )
        verified_index = next(
            index for index, event in call_events if event == "verified"
        )
        committed_indexes = [
            index
            for index, event in call_events
            if event == "state_version_committed"
        ]
        assert ready_index < verified_index
        assert all(verified_index < index for index in committed_indexes)
    event_index = {
        (event.call_id, event.event): index
        for index, event in enumerate(events)
    }
    for edge in replay.transactional_shadow_report.graph.dependencies:
        producer_commits = [
            index
            for index, event in enumerate(events)
            if event.call_id == edge.producer_call_id
            and event.event == "state_version_committed"
        ]
        if producer_commits:
            assert max(producer_commits) < event_index[
                (edge.consumer_call_id, "became_ready")
            ]


def test_legacy_and_shadow_modes_keep_authoritative_replay_identical() -> None:
    legacy = _replay("nankai", mode="legacy")
    shadow = _replay("nankai", mode="shadow")

    legacy_payload = legacy.to_payload()
    shadow_payload = shadow.to_payload()
    _remove_shadow_fields(legacy_payload)
    _remove_shadow_fields(shadow_payload)

    assert shadow_payload == legacy_payload
    assert legacy.transactional_shadow_report is None
    assert shadow.transactional_shadow_report is not None


def test_shadow_timeline_is_deterministic() -> None:
    first = _replay("heping-ermo", mode="shadow")
    second = _replay("heping-ermo", mode="shadow")

    assert (
        first.transactional_shadow_report.to_payload()
        == second.transactional_shadow_report.to_payload()
    )


def test_runtime_failure_blocks_only_version_dependents() -> None:
    replay = _replay("nankai", mode="shadow")
    graph = replay.transactional_shadow_report.graph
    root = next(
        call_id
        for call_id in graph.canonical_order
        if any(
            edge.producer_call_id == call_id
            for edge in graph.dependencies
        )
    )
    blocked = _descendants(graph, root)
    projection = {
        item.call_id: item.step_ids
        for item in replay.functional_reconciliation.projection_map
    }
    blocked_step_ids = {
        step_id
        for call_id in blocked
        for step_id in projection.get(call_id, ())
    }
    root_step_id = projection[root][0]
    independent_step_ids = {
        step_id
        for call_id in graph.canonical_order
        if call_id != root and call_id not in blocked
        for step_id in projection.get(call_id, ())
    }
    diagnostic = replace(
        replay.diagnostic,
        ok=False,
        accepted_prefix=tuple(
            item
            for item in replay.diagnostic.accepted_prefix
            if item.step_id in independent_step_ids
        ),
        blockers=(
            StepIntentExecutionBlocker(
                step_id=root_step_id,
                scope_id="problem",
                stage="trial_execution",
                code="synthetic_failure",
                message="synthetic root failure",
            ),
        ),
        skipped_steps=tuple(
            StepIntentSkippedStep(
                step_id=step_id,
                scope_id="problem",
                reason="blocked by synthetic dependency",
            )
            for step_id in sorted(blocked_step_ids)
        ),
        state_write_provenance=tuple(
            item
            for item in replay.diagnostic.state_write_provenance
            if item.step_id in independent_step_ids
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("nankai")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=None,
        parent_context=parent_context,
        handle_registry=registry,
    )

    states = {item.call_id: item for item in report.call_states}
    assert report.ok, report.to_payload()
    assert states[root].status == "failed"
    assert states[root].return_version_ids == ()
    assert all(
        states[call_id].status == "blocked_by_dependency"
        for call_id in blocked
    )
    assert all(
        states[call_id].return_version_ids == ()
        for call_id in blocked
    )
    assert any(
        states[call_id].status == "verified"
        for call_id in graph.canonical_order
        if call_id != root and call_id not in blocked
    )


def test_missing_runtime_provenance_is_reported_without_mutating_replay() -> None:
    replay = _replay("xiqing", mode="shadow")
    removed = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.selected_version_id is not None
    )
    diagnostic = replace(
        replay.diagnostic,
        state_write_provenance=tuple(
            item
            for item in replay.diagnostic.state_write_provenance
            if item is not removed
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("xiqing")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        retry_state=replay.retry_state,
        goal_verification_report=replay.goal_verification_report,
        parent_context=parent_context,
        handle_registry=registry,
    )

    assert not report.ok
    assert "verified_return_missing_runtime_write" in {
        item.code for item in report.mismatches
    }


def test_runtime_provenance_step_must_map_to_functional_call() -> None:
    replay = _replay("xiqing", mode="shadow")
    original = replay.diagnostic.state_write_provenance[0]
    diagnostic = replace(
        replay.diagnostic,
        state_write_provenance=(
            replace(original, step_id="unmapped_runtime_step"),
            *replay.diagnostic.state_write_provenance[1:],
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("xiqing")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=replay.goal_verification_report,
        parent_context=parent_context,
        handle_registry=registry,
    )

    assert "runtime_write_step_unmapped" in {
        item.code for item in report.mismatches
    }


def test_passed_answer_requires_its_typed_version_commit() -> None:
    replay = _replay("xiqing", mode="shadow")
    allocation = next(
        returned
        for call in replay.functional_reconciliation.calls
        for returned in call.returns
        if returned.bound_ref is not None
        and returned.bound_ref.kind == "answer"
        and returned.selected_version_id is not None
    )
    projection = next(
        item
        for item in replay.functional_reconciliation.projection_map
        if item.call_id == allocation.call_id
    )
    diagnostic = replace(
        replay.diagnostic,
        state_write_provenance=tuple(
            item
            for item in replay.diagnostic.state_write_provenance
            if not (
                item.step_id in projection.step_ids
                and item.return_name == allocation.return_name
            )
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("xiqing")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=replay.goal_verification_report,
        parent_context=parent_context,
        handle_registry=registry,
    )

    assert "passed_answer_version_not_committed" in {
        item.code for item in report.mismatches
    }


def test_verified_producer_does_not_make_uncommitted_source_available() -> None:
    replay = _replay("xiqing", mode="shadow")
    write = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.selected_version_id is not None
        and item.return_name is not None
    )
    ghost_version = replace(write.selected_version_id, ordinal=999)
    step_to_call = {
        step_id: item.call_id
        for item in replay.functional_reconciliation.projection_map
        for step_id in item.step_ids
    }
    call_id = step_to_call[write.step_id]
    calls = tuple(
        replace(
            call,
            returns=tuple(
                replace(returned, source_version_ids=(ghost_version,))
                if (
                    call.call_id == call_id
                    and returned.return_name == write.return_name
                )
                else returned
                for returned in call.returns
            ),
        )
        for call in replay.functional_reconciliation.calls
    )
    diagnostic = replace(
        replay.diagnostic,
        state_write_provenance=tuple(
            replace(item, source_version_ids=(ghost_version,))
            if item is write
            else item
            for item in replay.diagnostic.state_write_provenance
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("xiqing")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replace(
            replay.functional_reconciliation,
            calls=calls,
        ),
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=None,
        parent_context=parent_context,
        handle_registry=registry,
    )

    assert "state_version_source_unavailable" in {
        item.code for item in report.mismatches
    }


def test_observed_consumer_cannot_verify_before_dependencies_are_ready() -> None:
    replay = _replay("nankai", mode="shadow")
    graph = replay.transactional_shadow_report.graph
    edge = next(
        item
        for item in graph.dependencies
        if item.producer_call_id != item.consumer_call_id
    )
    projection = {
        item.call_id: item.step_ids
        for item in replay.functional_reconciliation.projection_map
    }
    producer_steps = set(projection[edge.producer_call_id])
    diagnostic = replace(
        replay.diagnostic,
        accepted_prefix=tuple(
            item
            for item in replay.diagnostic.accepted_prefix
            if item.step_id not in producer_steps
        ),
        state_write_provenance=tuple(
            item
            for item in replay.diagnostic.state_write_provenance
            if item.step_id not in producer_steps
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("nankai")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=None,
        parent_context=parent_context,
        handle_registry=registry,
    )

    states = {item.call_id: item for item in report.call_states}
    assert "dependency_accepted_before_verified" in {
        item.code for item in report.mismatches
    }
    assert states[edge.consumer_call_id].status != "verified"
    assert not any(
        event.call_id == edge.consumer_call_id
        and event.event == "state_version_committed"
        for event in report.events
    )


@pytest.mark.parametrize(
    "field_name",
    ("math_object_id", "typed_slot_id", "computation_key", "valid_scope_id"),
)
def test_incomplete_typed_runtime_write_is_not_committed(
    field_name: str,
) -> None:
    replay = _replay("xiqing", mode="shadow")
    original = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.selected_version_id is not None
        and item.math_object_id is not None
        and item.typed_slot_id is not None
        and item.computation_key is not None
        and item.valid_scope_id is not None
    )
    diagnostic = replace(
        replay.diagnostic,
        state_write_provenance=tuple(
            replace(item, **{field_name: None})
            if item is original
            else item
            for item in replay.diagnostic.state_write_provenance
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("xiqing")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=None,
        parent_context=parent_context,
        handle_registry=registry,
    )

    assert "state_write_identity_incomplete" in {
        item.code for item in report.mismatches
    }
    assert not any(
        event.event == "state_version_committed"
        and event.version_id == original.selected_version_id
        for event in report.events
    )


@pytest.mark.parametrize(
    "field_name",
    ("math_object_id", "typed_slot_id", "computation_key"),
)
def test_missing_typed_identity_on_both_sides_blocks_dependents(
    field_name: str,
) -> None:
    replay = _replay("xiqing", mode="shadow")
    graph = replay.transactional_shadow_report.graph
    producer_call_id = next(
        call_id
        for call_id in graph.canonical_order
        if any(
            edge.producer_call_id == call_id
            for edge in graph.dependencies
        )
    )
    allocation = next(
        returned
        for call in replay.functional_reconciliation.calls
        for returned in call.returns
        if call.call_id == producer_call_id
        and returned.selected_version_id is not None
    )
    projection = next(
        item
        for item in replay.functional_reconciliation.projection_map
        if item.call_id == producer_call_id
    )
    runtime_write = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.step_id in projection.step_ids
        and item.return_name == allocation.return_name
    )
    calls = tuple(
        replace(
            call,
            returns=tuple(
                replace(returned, **{field_name: None})
                if (
                    call.call_id == producer_call_id
                    and returned.return_name == allocation.return_name
                )
                else returned
                for returned in call.returns
            ),
        )
        for call in replay.functional_reconciliation.calls
    )
    diagnostic = replace(
        replay.diagnostic,
        state_write_provenance=tuple(
            replace(item, **{field_name: None})
            if item is runtime_write
            else item
            for item in replay.diagnostic.state_write_provenance
        ),
    )
    (
        _problem,
        inputs,
        problem_payload,
        registry,
        plan,
        _validation,
    ) = _case_runtime("xiqing")
    parent_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )

    report = FunctionalTransactionShadowObserver().observe(
        raw_plan=plan,
        reconciliation=replace(
            replay.functional_reconciliation,
            calls=calls,
        ),
        diagnostic=diagnostic,
        retry_state=None,
        goal_verification_report=None,
        parent_context=parent_context,
        handle_registry=registry,
    )

    states = {item.call_id: item.status for item in report.call_states}
    consumers = {
        edge.consumer_call_id
        for edge in graph.dependencies
        if edge.producer_call_id == producer_call_id
    }
    assert "state_write_identity_incomplete" in {
        item.code for item in report.mismatches
    }
    assert states[producer_call_id] == "failed"
    assert all(
        states[call_id] == "blocked_by_dependency"
        for call_id in consumers
    )
    assert not any(
        event.call_id in consumers
        and event.event in {"became_ready", "verified"}
        for event in report.events
    )


def test_partial_reconciliation_still_emits_shadow_report() -> None:
    (
        problem,
        inputs,
        problem_payload,
        registry,
        plan,
        validation,
    ) = _case_runtime("nankai")
    first_scope = plan.scopes[0]
    partial_plan = replace(
        plan,
        scopes=(
            replace(
                first_scope,
                calls=(
                    replace(first_scope.calls[0], args={}),
                    *first_scope.calls[1:],
                ),
            ),
            *plan.scopes[1:],
        ),
    )

    replay = PlannerRetryReplayService(
        functional_transaction_mode="shadow",
    ).replay_functional_plan(
        partial_plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is None
    assert replay.retry_state is not None
    assert replay.transactional_shadow_report is not None
    assert replay.transactional_shadow_report.graph.calls
    assert replay.planner_state_context is not None
    assert (
        replay.planner_state_context.state.functional_transaction_shadow
        == replay.transactional_shadow_report.to_payload()
    )


def _remove_shadow_fields(value: Any) -> None:
    if isinstance(value, dict):
        value.pop("transactional_shadow_report", None)
        value.pop("functional_transaction_shadow", None)
        for item in value.values():
            _remove_shadow_fields(item)
    elif isinstance(value, list):
        for item in value:
            _remove_shadow_fields(item)


def _descendants(graph, call_id: str) -> set[str]:
    result: set[str] = set()
    frontier = [call_id]
    while frontier:
        producer = frontier.pop()
        for edge in graph.dependencies:
            if (
                edge.producer_call_id == producer
                and edge.consumer_call_id not in result
            ):
                result.add(edge.consumer_call_id)
                frontier.append(edge.consumer_call_id)
    return result
