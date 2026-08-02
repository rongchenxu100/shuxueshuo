from __future__ import annotations

import inspect
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan import (
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalCallPreparationService,
    FunctionalRuntimeWriteCommitter,
    SymbolicClosureProvenanceError,
    FunctionalTransactionBehaviorDelta,
    FunctionalTransactionalInterpreter,
    PreparedFunctionalArgBinding,
    PreparedFunctionalCall,
    _compare_with_legacy,
    _closure_failure_details,
    _prepared_runtime_arg_object_ids,
    _validate_symbolic_closure_write_set,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalArgBinding,
    FunctionalArgBindingKey,
    FunctionalArgSourceIdentity,
    FunctionalBindingContextBuilder,
)
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    latest_functional_retry_graph_checkpoint,
)
from shuxueshuo_server.solver.runtime.result_builder import ResultBuilder
from shuxueshuo_server.solver.runtime.functional_transaction_shadow import (
    FunctionalCallExecutionState,
    FunctionalTransactionShadowMismatch,
    WorkingPlannerState,
    build_working_state,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
)
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
    QuadraticFromConstraintsMethod,
)
from shuxueshuo_server.solver.runtime.models import Point, TypedValue
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import (
    problem_to_llm_payload,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayService,
    transactional_repair_attempt_payload_from_replay,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    LogicalStateKey,
    MathObjectId,
    MathObjectRegistry,
    ScopeVisibilityResolver,
    StateAllocationService,
    StateIdentityIndex,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationService,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    execute_symbolic_closure,
)


def _replay(
    case_id: str,
    *,
    mode: str,
    symbolic_closure_mode: str = "disabled",
    compile_mode: str = "direct_authoritative",
):
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
    return PlannerRetryReplayService(
        functional_transaction_mode=mode,
        functional_symbolic_closure_mode=symbolic_closure_mode,
        functional_compile_mode=compile_mode,
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )


def _active_symbolic_closure_plan():
    case = FUNCTIONAL_BATCH_CASES["heping-ermo"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    target_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    target_call["args"]["target_parameter"] = {
        "kind": "symbol",
        "ref": "b",
    }
    target_call["return_bindings"]["parameter_value"] = {
        "kind": "symbol",
        "ref": "b",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    return problem, inputs, problem_payload, registry, plan, validation


def _active_singleton_mapping_closure_plan():
    case = FUNCTIONAL_BATCH_CASES["hexi"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    target_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    target_call["args"]["target_parameter"] = {
        "kind": "symbol",
        "ref": "c",
    }
    target_call["return_bindings"]["parameter_value"] = {
        "kind": "symbol",
        "ref": "c",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    return problem, inputs, problem_payload, registry, plan, validation


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_transaction_execution_has_zero_mismatch(
    case_id: str,
) -> None:
    replay = _replay(case_id, mode="execution_shadow")

    assert replay.output is not None
    assert replay.transactional_shadow_report is not None
    report = replay.transactional_execution_report
    assert report is not None, (
        [
            item.to_payload()
            for item in (replay.functional_reconciliation.issues or ())
        ]
        if replay.functional_reconciliation is not None
        else replay.errors
    )
    assert report.ok, report.to_payload()
    assert not report.compatibility_mismatches
    assert not report.behavior_deltas
    assert all(
        item.status == "verified"
        for item in report.call_states
        if item.call_id in report.graph.canonical_order
    )
    assert replay.planner_state_context is not None
    assert (
        replay.planner_state_context.state.functional_transaction_execution
        == report.to_payload()
    )

    events = report.events
    for call_id in report.graph.canonical_order:
        call_events = [
            (index, event.event)
            for index, event in enumerate(events)
            if event.call_id == call_id
        ]
        ready = next(index for index, event in call_events if event == "became_ready")
        running = next(index for index, event in call_events if event == "running")
        verified = next(index for index, event in call_events if event == "verified")
        committed = [
            index
            for index, event in call_events
            if event == "state_version_committed"
        ]
        assert ready < running < verified
        assert all(verified < index for index in committed)


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_executes_declared_symbolic_closures(
    case_id: str,
) -> None:
    replay = _replay(
        case_id,
        mode="context_authoritative",
        symbolic_closure_mode="authoritative",
    )

    assert replay.output is not None, (
        [
            (
                item.call_id,
                item.status,
                [
                    (issue.code, issue.message)
                    for issue in item.root_issues
                ],
            )
            for item in replay.transactional_execution_report.call_results
            if item.status != "verified"
        ]
        if replay.transactional_execution_report is not None
        else replay.errors
    )
    report = replay.transactional_execution_report
    assert report is not None
    assert report.symbolic_closure_execution_count > 0
    assert (
        sum(report.symbolic_closure_execution_by_capability.values())
        == report.symbolic_closure_execution_count
    )
    assert report.symbolic_closure_drift_count == 0
    assert report.symbolic_closure_drift_by_capability == {}
    assert report.ok, report.to_payload()


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_context_shadow_has_transactional_parity(
    case_id: str,
) -> None:
    replay = _replay(case_id, mode="context_shadow")

    attempt = replay.transactional_attempt_result
    assert attempt is not None
    assert attempt.execution_report.ok, attempt.to_payload()
    binding_consumption = attempt.execution_report.to_payload()[
        "binding_consumption_decisions"
    ]
    assert binding_consumption
    assert all(item["matches"] for item in binding_consumption)
    assert attempt.compiled_output is not None
    assert not attempt.root_issues
    assert all(
        item.status == "passed"
        for item in attempt.goal_report.goals
    )
    assert replay.state_observation_authority == "legacy"
    assert replay.output is not None


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_context_authoritative_goal_output_replays_in_fresh_context(
    case_id: str,
) -> None:
    replay = _replay(case_id, mode="context_authoritative")
    attempt = replay.transactional_attempt_result
    assert attempt is not None and attempt.compiled_output is not None
    case = FUNCTIONAL_BATCH_CASES[case_id]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    context = ContextBuilder().build(problem)
    output = attempt.compiled_output

    DeclarationValidator().validate_declarations(
        context,
        output.context_declarations,
    )
    context.apply_declarations(output.context_declarations)
    execution = InvocationExecutor(
        inputs.method_specs,
        methods=default_stateless_registry(),
        kernel=context.kernel,
    ).execute_plan(context, output.step_plans)

    assert all(item.ok for item in execution.checks), [
        item.to_payload() for item in execution.checks if not item.ok
    ]
    answers = ResultBuilder().build(
        context,
        execution,
        list(inputs.question_goals),
    )
    assert all(
        goal.answer_key in answers.get(goal.question_id, {})
        for goal in inputs.question_goals
        if goal.required
    )


def test_goal_closure_keeps_hidden_equal_length_ray_state_producers() -> None:
    replay = _replay("heping", mode="context_authoritative")
    attempt = replay.transactional_attempt_result

    assert attempt is not None and attempt.compiled_output is not None
    assert "derive_parametric_parabola_ii" in attempt.goal_reachable_call_ids
    assert "derive_x_intercept_B_ii" in attempt.goal_reachable_call_ids
    assert "reduce_equal_length_ray_path_ii" in attempt.goal_reachable_call_ids


def test_sibling_question_states_do_not_publish_through_object_origin() -> None:
    replay = _replay("heping", mode="context_authoritative")
    reconciliation = replay.functional_reconciliation
    assert reconciliation is not None
    calls = {item.call_id: item for item in reconciliation.calls}

    i2_point = calls["derive_x_intercept_B_i"].returns[0]
    ii_point = calls["derive_x_intercept_B_ii"].returns[0]
    assert i2_point.valid_scope == "i_2"
    assert ii_point.valid_scope == "ii"
    assert i2_point.typed_slot_id is not None
    assert ii_point.typed_slot_id is not None
    assert i2_point.typed_slot_id.storage_scope_id == "i_2"
    assert ii_point.typed_slot_id.storage_scope_id == "ii"
    assert i2_point.selected_version_id != ii_point.selected_version_id


def test_context_authoritative_uses_transactional_output_and_context() -> None:
    replay = _replay("nankai", mode="context_authoritative")

    attempt = replay.transactional_attempt_result
    assert attempt is not None and attempt.compiled_output is not None
    assert replay.output == attempt.compiled_output
    assert replay.diagnostic == attempt.diagnostic
    assert replay.goal_verification_report == attempt.goal_report
    assert replay.state_observation_authority == "transactional"
    assert replay.functional_reconciliation is not None
    assert replay.functional_reconciliation.projected_draft is None
    assert attempt.execution_report.functional_compile_count > 0
    assert replay.retry_state is None
    assert replay.planner_state_context is not None
    assert any(
        item.event == "state_observation_authority_selected"
        for item in replay.planner_state_context.state.context_events
    )


def test_context_authoritative_mismatch_produces_retry_instead_of_dead_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_execute = FunctionalTransactionalInterpreter.execute

    def execute_with_mismatch(self, **kwargs):
        report = original_execute(self, **kwargs)
        return replace(
            report,
            compatibility_mismatches=(
                *report.compatibility_mismatches,
                FunctionalTransactionShadowMismatch(
                    "synthetic_transactional_drift",
                    "i_derive_parabola",
                    "expected",
                    "actual",
                ),
            ),
        )

    monkeypatch.setattr(
        FunctionalTransactionalInterpreter,
        "execute",
        execute_with_mismatch,
    )

    replay = _replay("nankai", mode="context_authoritative")

    assert replay.state_observation_authority == "transactional"
    assert replay.output is None
    assert replay.transactional_attempt_result is not None
    assert replay.transactional_attempt_result.root_issues
    assert replay.retry_state is not None
    assert any(
        item.code == "planner.transactional_authority_mismatch"
        for item in replay.retry_state.issues
    )


def test_context_authoritative_attempt_exception_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_attempt(self, **kwargs):
        raise RuntimeError("synthetic transactional entry failure")

    monkeypatch.setattr(
        FunctionalTransactionalInterpreter,
        "execute_attempt",
        fail_attempt,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.transactional_attempt_failed",
    ):
        _replay("nankai", mode="context_authoritative")


def test_context_authoritative_partial_legacy_probe_stays_provisional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_allocate = StateAllocationService.allocate

    def conflict_last_call(self, request, index):
        decision = original_allocate(self, request, index)
        if request.call_id != "ii_2_derive_G":
            return decision
        return replace(
            decision,
            action="conflict",
            selected_slot_id=None,
            selected_version_id=None,
            canonical_producer_call_id=None,
            reason_code="synthetic_partial_graph_failure",
            conflict_code="state.logical_duplicate_writer",
        )

    monkeypatch.setattr(
        StateAllocationService,
        "allocate",
        conflict_last_call,
    )

    replay = _replay(
        "nankai",
        mode="context_authoritative",
        compile_mode="projected",
    )

    assert replay.transactional_attempt_result is None
    assert replay.retry_state is not None
    checkpoint = latest_functional_retry_graph_checkpoint(
        [
            {
                "functional_retry_graph_checkpoint": (
                    replay.retry_state.functional_retry_graph_checkpoint
                )
            }
        ]
    )
    assert checkpoint is not None
    assert checkpoint.committed_calls == ()
    assert checkpoint.verified_versions
    assert {
        item.status for item in checkpoint.verified_versions
    } == {"runtime_verified"}
    assert replay.retry_state.runtime_verified_calls
    assert all(
        item["commit_status"] == "provisional"
        for item in replay.retry_state.call_memory
        if item["execution_status"] == "runtime_verified"
    )


def test_context_authoritative_does_not_gate_on_legacy_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_compare = _compare_with_legacy

    def fail_if_compared(*args, **kwargs):
        raise AssertionError("legacy comparator is not authoritative")

    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.functional_transaction_execution."
        "_compare_with_legacy",
        fail_if_compared,
    )
    replay = _replay("nankai", mode="context_authoritative")
    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.functional_transaction_execution."
        "_compare_with_legacy",
        original_compare,
    )

    assert replay.output is not None
    assert replay.state_observation_authority == "transactional"


def test_context_shadow_compares_goal_output_context_and_retry_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_attempt = FunctionalTransactionalInterpreter.execute_attempt

    def attempt_with_output_drift(self, **kwargs):
        attempt = original_attempt(self, **kwargs)
        assert attempt.compiled_output is not None
        output = replace(
            attempt.compiled_output,
            step_plans=attempt.compiled_output.step_plans[:-1],
        )
        return replace(attempt, compiled_output=output)

    monkeypatch.setattr(
        FunctionalTransactionalInterpreter,
        "execute_attempt",
        attempt_with_output_drift,
    )

    replay = _replay("nankai", mode="context_shadow")

    assert replay.output is not None
    assert replay.state_observation_authority == "legacy"
    assert replay.transactional_attempt_result is not None
    assert any(
        item.code == "transactional_goal_output_drift"
        for item in (
            replay.transactional_attempt_result.execution_report
            .compatibility_mismatches
        )
    )


def test_context_shadow_keeps_legacy_checkpoint_prevalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authoritative = _replay("nankai", mode="context_authoritative")
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    previous = transactional_repair_attempt_payload_from_replay(
        authoritative,
        attempt=2,
        errors=("answer_mismatch: synthetic",),
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )
    assert previous is not None
    checkpoint = latest_functional_retry_graph_checkpoint([previous])
    assert checkpoint is not None
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    observed = []

    def observe_checkpoint(expected, **kwargs):
        observed.append(expected)

    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.strategy_replay."
        "_verify_successful_functional_retry_checkpoint",
        observe_checkpoint,
    )
    PlannerRetryReplayService(
        functional_transaction_mode="context_shadow",
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
        retry_checkpoint=checkpoint,
    )

    assert len(observed) == 1


def test_transactional_answer_check_revokes_commits_but_keeps_versions() -> None:
    replay = _replay("nankai", mode="context_authoritative")
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)

    payload = transactional_repair_attempt_payload_from_replay(
        replay,
        attempt=2,
        errors=(
            "answer_mismatch: synthetic; actual=1; expected=2",
        ),
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )

    assert payload is not None
    retry = payload["planner_retry_state"]
    assert retry["preserve_policy"] == "none"
    assert retry["committed_candidate_calls"] == []
    assert any(
        item["layer"] == "answer_check"
        and item["code"] == "answer_mismatch"
        for item in retry["issues"]
    )
    checkpoint = payload["functional_retry_graph_checkpoint"]
    assert checkpoint["committed_calls"] == []
    assert checkpoint["verified_versions"]
    assert {
        item["status"] for item in checkpoint["verified_versions"]
    } == {"runtime_verified"}


def test_exact_transaction_attempt_does_not_require_legacy_output() -> None:
    legacy = _replay("nankai", mode="legacy")
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)

    attempt = FunctionalTransactionalInterpreter().execute_attempt(
        raw_plan=legacy.functional_reconciliation.plan,
        reconciliation=legacy.functional_reconciliation,
        legacy_output=None,
        legacy_diagnostic=None,
        runtime_context=ContextBuilder().build(problem),
        parent_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
            attempt=1,
        ),
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
        compare_legacy=False,
    )

    assert attempt.compiled_output is not None
    assert not attempt.root_issues
    assert all(
        item.status == "passed" for item in attempt.goal_report.goals
    )


def test_context_authoritative_commits_runtime_symbolic_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finalized_closure_writes: list[tuple[object, ...]] = []
    original_finalize = StateFinalizationService.finalize_compiled_graph

    def capture_finalized_provenance(self, *args, **kwargs):
        provenance = tuple(args[1] if len(args) > 1 else ())
        target_writes = tuple(
            write
            for write in provenance
            if write.step_id == "derive_parametric_parabola_ii"
            and write.return_name
            in {"coefficients", "parabola", "parameter_value"}
        )
        if target_writes:
            finalized_closure_writes.append(target_writes)
        return original_finalize(self, *args, **kwargs)

    monkeypatch.setattr(
        StateFinalizationService,
        "finalize_compiled_graph",
        capture_finalized_provenance,
    )
    case = FUNCTIONAL_BATCH_CASES["heping-ermo"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    target_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    target_call["args"]["target_parameter"] = {
        "kind": "symbol",
        "ref": "b",
    }
    target_call["return_bindings"]["parameter_value"] = {
        "kind": "symbol",
        "ref": "b",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

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
        validation_report=validation,
    )

    assert replay.output is not None, (
        [
            (
                item.call_id,
                item.status,
                [
                    (issue.code, issue.message)
                    for issue in item.root_issues
                ],
            )
            for item in replay.transactional_execution_report.call_results
            if item.status != "verified"
        ]
        if replay.transactional_execution_report is not None
        else replay.errors
    )
    report = replay.transactional_execution_report
    assert report is not None
    assert report.symbolic_closure_execution_count >= 1
    assert report.symbolic_closure_drift_count == 0
    call_result = next(
        item
        for item in report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )
    assert call_result.status == "verified"
    assert call_result.symbolic_closure is not None
    assert call_result.symbolic_closure.status == "unique"
    assert finalized_closure_writes
    assert any(
        all(
            write.symbolic_closure_provenance is not None
            for write in writes
        )
        for writes in finalized_closure_writes
    )
    assert all(
        write.symbolic_closure_provenance is not None
        for write in call_result.state_writes
        if write.return_name
        in {"coefficients", "parabola", "parameter_value"}
    )
    assert replay.planner_state_context is not None
    closure_by_version = replay.planner_state_context.closure_by_version
    closure_writes = tuple(
        write
        for write in call_result.state_writes
        if write.symbolic_closure_provenance is not None
        and write.selected_version_id is not None
    )
    assert closure_writes
    assert all(
        closure_by_version[write.selected_version_id]
        == write.symbolic_closure_provenance
        for write in closure_writes
    )


def test_non_unique_symbolic_closure_rolls_back_entire_call() -> None:
    case = FUNCTIONAL_BATCH_CASES["heping-ermo"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    target_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    target_call["args"]["target_parameter"] = {
        "kind": "symbol",
        "ref": "b",
    }
    target_call["args"].pop("curve_point")
    target_call["return_bindings"]["parameter_value"] = {
        "kind": "symbol",
        "ref": "b",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

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
        validation_report=validation,
    )

    report = replay.transactional_execution_report
    assert report is not None, (
        [
            item.to_payload()
            for item in replay.functional_reconciliation.issues
        ]
        if replay.functional_reconciliation is not None
        else replay.errors
    )
    call_result = next(
        item
        for item in report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )
    assert call_result.status == "failed"
    assert call_result.symbolic_closure is not None
    assert call_result.symbolic_closure.status == "identity_unresolved"
    assert call_result.state_writes == ()
    assert call_result.committed_versions == ()
    assert call_result.root_issues[0].code == (
        "function.symbolic_closure_identity_unresolved"
    )


def test_symbolic_closure_write_set_requires_every_allocated_companion() -> None:
    provenance = SimpleNamespace(
        status="unique",
        target_object_id=None,
        residual_symbol_ids=(),
        semantic_signature=lambda: ("unique", "b", "1-c"),
    )
    closure_result = SimpleNamespace(
        provenance=provenance,
        affected_returns=("parameter_value", "parabola"),
    )
    writes = (
        SimpleNamespace(
            return_name="parameter_value",
            runtime_type="Expression",
            math_object_id=None,
            free_symbol_ids=(),
            symbolic_closure_provenance=provenance,
        ),
    )
    compiled = SimpleNamespace(
        public_returns=(
            SimpleNamespace(
                return_name="parameter_value",
                expected_write=object(),
            ),
            SimpleNamespace(
                return_name="parabola",
                expected_write=object(),
            ),
        )
    )

    with pytest.raises(SymbolicClosureProvenanceError) as exc_info:
        _validate_symbolic_closure_write_set(
            writes,
            closure_result=closure_result,
            compiled=compiled,
        )

    assert exc_info.value.code == "planner.symbolic_closure_provenance_missing"
    assert "parabola" in str(exc_info.value)


def test_symbolic_closure_write_set_allows_unallocated_optional_return() -> None:
    provenance = SimpleNamespace(
        status="unique",
        target_object_id=None,
        residual_symbol_ids=(),
        semantic_signature=lambda: ("unique", "b", "1-c"),
    )

    _validate_symbolic_closure_write_set(
        (),
        closure_result=SimpleNamespace(
            provenance=provenance,
            affected_returns=("optional_parabola",),
        ),
        compiled=SimpleNamespace(public_returns=()),
    )


def test_symbolic_closure_repair_cone_excludes_sibling_consumers() -> None:
    calls = (
        SimpleNamespace(
            call_id="source",
            dependency_call_ids=(),
            consumer_call_ids=("closure", "unrelated"),
        ),
        SimpleNamespace(
            call_id="closure",
            dependency_call_ids=("source",),
            consumer_call_ids=("answer",),
        ),
        SimpleNamespace(
            call_id="answer",
            dependency_call_ids=("closure",),
            consumer_call_ids=(),
        ),
        SimpleNamespace(
            call_id="unrelated",
            dependency_call_ids=("source",),
            consumer_call_ids=(),
        ),
    )
    result = SimpleNamespace(
        status="underdetermined",
        branch_count=0,
        target_object_id=None,
        residual_symbol_ids=(),
        provenance=None,
        validation_build=SimpleNamespace(
            equation_sources=("curve_point",),
        ),
    )

    details = _closure_failure_details(
        result,
        call_id="closure",
        graph=SimpleNamespace(calls=calls),
    )

    assert set(details["repair_call_ids"]) == {
        "source",
        "closure",
        "answer",
    }
    assert details["equation_sources"] == ["curve_point"]


def test_authoritative_closure_rejects_wrong_method_companion_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run = QuadraticFromConstraintsMethod.run

    def wrong_companion_outputs(self, inputs, kernel):
        result = original_run(self, inputs, kernel)
        target = inputs.get("target_parameter")
        if target is None:
            return result
        outputs = dict(result.outputs)
        coefficients = dict(outputs["coefficients"].value)
        coefficients[sp.Symbol("_wrong_companion")] = sp.Integer(99)
        outputs["coefficients"] = TypedValue(
            "Coefficients",
            coefficients,
            source=result.method_id,
        )
        return replace(result, outputs=outputs)

    monkeypatch.setattr(
        QuadraticFromConstraintsMethod,
        "run",
        wrong_companion_outputs,
    )

    case = FUNCTIONAL_BATCH_CASES["heping-ermo"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    target_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    target_call["args"]["target_parameter"] = {
        "kind": "symbol",
        "ref": "b",
    }
    target_call["return_bindings"]["parameter_value"] = {
        "kind": "symbol",
        "ref": "b",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

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
        validation_report=validation,
    )

    report = replay.transactional_execution_report
    assert report is not None
    call_result = next(
        item
        for item in report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )
    assert call_result.status == "failed"
    assert call_result.state_writes == ()
    assert call_result.committed_versions == ()
    assert call_result.root_issues[0].code == (
        "planner.contract_runtime_symbol_drift"
    ), call_result.root_issues

    monkeypatch.setattr(
        QuadraticFromConstraintsMethod,
        "run",
        original_run,
    )
    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.functional_transaction_execution."
        "_symbolic_values_equivalent",
        lambda _left, _right: False,
    )
    shadow = PlannerRetryReplayService(
        functional_transaction_mode="execution_shadow",
        functional_symbolic_closure_mode="shadow",
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )
    shadow_report = shadow.transactional_execution_report
    assert shadow_report is not None
    assert shadow_report.symbolic_closure_execution_count >= 1
    assert shadow_report.symbolic_closure_drift_count >= 1
    shadow_call = next(
        item
        for item in shadow_report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )
    assert shadow_call.status == "verified"
    assert shadow_call.symbolic_closure is not None
    assert shadow_call.symbolic_closure.status == "unique"
    assert all(
        write.symbolic_closure_provenance is None
        for write in shadow_call.state_writes
    )


def test_commit_payload_issue_does_not_stamp_closure_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_commit = FunctionalRuntimeWriteCommitter.commit_payload

    def commit_with_issue(self, compiled, **kwargs):
        payload = original_commit(self, compiled, **kwargs)
        if compiled.call_id != "derive_parametric_parabola_ii":
            return payload
        return (
            *payload[:-1],
            (
                PlannerRetryIssue(
                    layer="trial_execution",
                    code="synthetic.commit_issue",
                    step_id=compiled.call_id,
                    message="synthetic commit failure",
                ),
            ),
        )

    monkeypatch.setattr(
        FunctionalRuntimeWriteCommitter,
        "commit_payload",
        commit_with_issue,
    )
    (
        problem,
        inputs,
        problem_payload,
        registry,
        plan,
        validation,
    ) = _active_symbolic_closure_plan()

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
        validation_report=validation,
    )

    report = replay.transactional_execution_report
    assert report is not None
    call_result = next(
        item
        for item in report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )
    assert call_result.status == "failed"
    assert call_result.state_writes
    assert call_result.committed_versions == ()
    assert all(
        write.symbolic_closure_provenance is None
        for write in call_result.state_writes
    )


def test_singleton_mapping_keeps_public_arg_symbol_identity() -> None:
    object_id = MathObjectId("a", "symbol", "problem")
    logical_key = LogicalStateKey(
        object_id,
        "value",
        "ParameterValue",
    )
    version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    logical_binding = FunctionalArgBinding(
        key=FunctionalArgBindingKey(
            "build_curve",
            "known_coefficients",
            0,
        ),
        capability_id="quadratic_from_constraints",
        semantic_role="known_coefficients",
        binding_authority="wire",
        cardinality="many",
        runtime_type="ParameterValue",
        source=FunctionalArgSourceIdentity(
            kind="state_version",
            state_version_id=version_id,
        ),
        selection_policy="exact",
        consumption_mode="runtime_input",
        runtime_input_targets=("parameter", "parameter_value"),
    )
    prepared = PreparedFunctionalCall(
        call_id="build_curve",
        capability_id="quadratic_from_constraints",
        step_ids=("build_curve",),
        dependency_call_ids=(),
        reconciliation=None,  # type: ignore[arg-type]
        arg_bindings=(
            PreparedFunctionalArgBinding(
                logical_binding,
                selected_state_version_id=version_id,
            ),
        ),
    )

    identities = _prepared_runtime_arg_object_ids(
        prepared,
        runtime_args={
            "known_coefficients": {sp.Symbol("a"): sp.Integer(2)},
            "parameter": sp.Symbol("a"),
            "parameter_value": sp.Integer(2),
        },
    )

    assert identities["known_coefficients"] == (object_id,)
    assert identities["parameter"] == (object_id,)
    assert identities["parameter_value"] == (object_id,)


def test_hexi_singleton_known_mapping_reaches_closure_with_typed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, tuple[MathObjectId, ...]]] = []

    def capture_identity(*args, **kwargs):
        runtime_args = kwargs.get("args", {})
        if (
            kwargs.get("target_binding") == "target_parameter"
            and isinstance(runtime_args.get("known_coefficients"), dict)
            and len(runtime_args["known_coefficients"]) == 1
        ):
            observed.append(dict(kwargs.get("arg_object_ids", {})))
        return execute_symbolic_closure(*args, **kwargs)

    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.functional_transaction_execution."
        "execute_symbolic_closure",
        capture_identity,
    )
    (
        problem,
        inputs,
        problem_payload,
        registry,
        plan,
        validation,
    ) = _active_singleton_mapping_closure_plan()

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
        validation_report=validation,
    )

    report = replay.transactional_execution_report
    assert report is not None
    call_result = next(
        item
        for item in report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )
    assert call_result.status == "verified", call_result.root_issues
    assert observed
    assert observed[0]["known_coefficients"] == (
        MathObjectId("symbol:problem:a", "symbol", "problem"),
    )


def test_partial_goal_failure_keeps_independent_goal_branch_verified() -> None:
    legacy = _replay("nankai", mode="legacy")
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    failed_call_id = "ii_1_evaluate_minimum"

    class FailingExecutor:
        def __init__(self, context):
            self.delegate = InvocationExecutor(
                inputs.method_specs,
                methods=default_stateless_registry(),
                kernel=context.kernel,
            )

        def execute_plan(self, context, plans):
            if any(
                item.step_id == failed_call_id for item in plans
            ):
                raise RuntimeError("synthetic goal-branch failure")
            return self.delegate.execute_plan(context, plans)

    attempt = FunctionalTransactionalInterpreter(
        executor_factory=lambda _inputs, context: FailingExecutor(context),
    ).execute_attempt(
        raw_plan=legacy.functional_reconciliation.plan,
        reconciliation=legacy.functional_reconciliation,
        legacy_output=None,
        legacy_diagnostic=None,
        runtime_context=ContextBuilder().build(problem),
        parent_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
            attempt=1,
        ),
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
        compare_legacy=False,
    )
    goals = {
        item.goal_handle: item.status
        for item in attempt.goal_report.goals
    }

    assert attempt.compiled_output is None
    assert failed_call_id in attempt.failed_call_ids
    assert goals["answer:ii_1.minimum_value"] == "not_executed"
    assert goals["answer:ii_2.intersection"] == "passed"
    assert "ii_2_derive_G" in attempt.verified_call_ids
    assert "ii_2_derive_G" in attempt.goal_reachable_call_ids
    assert failed_call_id not in attempt.goal_reachable_call_ids
    assert len(attempt.root_issues) == 1
    assert attempt.root_issues[0].step_id == failed_call_id


def test_runtime_context_fork_discards_branch_writes() -> None:
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    context = ContextBuilder().build(problem)
    branch = context.fork()
    point_path = "$problem.points.transaction_probe"

    branch.write_path(
        point_path,
        TypedValue("Point", Point((1, 2)), source="test"),
        from_scope_id="problem",
    )

    assert branch.read_path(point_path).value == Point((1, 2))
    with pytest.raises(KeyError):
        context.read_path(point_path)
    assert branch.symbols is context.symbols


def test_execution_shadow_keeps_legacy_authority_unchanged() -> None:
    legacy = _replay("nankai", mode="legacy")
    execution = _replay("nankai", mode="execution_shadow")

    assert legacy.transactional_execution_report is None
    assert legacy.transactional_shadow_report is None
    legacy_payload = legacy.to_payload()
    execution_payload = execution.to_payload()
    for payload in (legacy_payload, execution_payload):
        payload.pop("transactional_shadow_report", None)
        payload.pop("transactional_execution_report", None)
        context = payload.get("planner_state_context")
        if isinstance(context, dict):
            state = context.get("state")
            if isinstance(state, dict):
                state.pop("functional_transaction_shadow", None)
                state.pop("functional_transaction_execution", None)

    assert execution_payload == legacy_payload
    assert "functional_transaction_execution" not in json.dumps(
        (
            legacy.retry_state.to_payload()
            if legacy.retry_state is not None
            else {}
        )
    )


def test_transaction_failure_rolls_back_and_blocks_only_dependents() -> None:
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    legacy = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )
    normal = _replay("nankai", mode="execution_shadow")
    graph = normal.transactional_execution_report.graph
    root, descendants, independent = _failure_partition(graph)
    projection = {
        item.call_id: item.step_ids
        for item in legacy.functional_reconciliation.projection_map
    }
    fail_step_ids = frozenset(projection[root])
    leak_observed = [False]

    class FailingExecutor:
        def __init__(self, context):
            self.delegate = InvocationExecutor(
                inputs.method_specs,
                methods=default_stateless_registry(),
                kernel=context.kernel,
            )

        def execute_plan(self, context, plans):
            probe = "$problem.points.transaction_failed_probe"
            try:
                context.read_path(probe)
            except KeyError:
                pass
            else:
                leak_observed[0] = True
            if any(item.step_id in fail_step_ids for item in plans):
                from shuxueshuo_server.solver.runtime.models import (
                    Point as RuntimePoint,
                )

                context.write_path(
                    probe,
                    TypedValue(
                        "Point",
                        RuntimePoint((9, 9)),
                        source="test",
                    ),
                    from_scope_id="problem",
                )
                raise RuntimeError("synthetic transactional root failure")
            return self.delegate.execute_plan(context, plans)

    report = FunctionalTransactionalInterpreter(
        executor_factory=lambda _inputs, context: FailingExecutor(context),
    ).execute(
        raw_plan=plan,
        reconciliation=legacy.functional_reconciliation,
        legacy_output=legacy.output,
        legacy_diagnostic=legacy.diagnostic,
        runtime_context=ContextBuilder().build(problem),
        parent_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
            attempt=1,
        ),
        inputs=inputs,
        handle_registry=registry,
        goal_verification_report=legacy.goal_verification_report,
    )
    statuses = {item.call_id: item.status for item in report.call_states}

    assert statuses[root] == "failed"
    assert all(
        statuses[call_id] == "blocked_by_dependency"
        for call_id in descendants
    )
    assert any(statuses[call_id] == "verified" for call_id in independent)
    assert not leak_observed[0]


def test_form_or_closure_gap_is_a_hard_compatibility_mismatch() -> None:
    case = FUNCTIONAL_BATCH_CASES["hexi"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    legacy = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )
    target = next(
        item
        for item in legacy.diagnostic.state_write_provenance
        if item.free_symbol_names
    )
    diagnostic = replace(
        legacy.diagnostic,
        state_write_provenance=tuple(
            replace(item, result_form=None, free_symbol_names=())
            if item is target
            else item
            for item in legacy.diagnostic.state_write_provenance
        ),
    )

    report = FunctionalTransactionalInterpreter().execute(
        raw_plan=plan,
        reconciliation=legacy.functional_reconciliation,
        legacy_output=legacy.output,
        legacy_diagnostic=diagnostic,
        runtime_context=ContextBuilder().build(problem),
        parent_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
            attempt=1,
        ),
        inputs=inputs,
        handle_registry=registry,
        goal_verification_report=legacy.goal_verification_report,
    )

    assert not report.ok
    assert any(
        item.code == "transactional_runtime_write_drift"
        and item.call_id == target.step_id
        for item in report.compatibility_mismatches
    )
    assert not report.behavior_deltas


def test_unknown_behavior_delta_cannot_pass_the_compatibility_gate() -> None:
    report = _replay(
        "nankai",
        mode="execution_shadow",
    ).transactional_execution_report
    assert report is not None and report.ok

    report = replace(
        report,
        behavior_deltas=(
            FunctionalTransactionBehaviorDelta(
                "unexpected_state_delta",
                "call",
                "must not be silently accepted",
            ),
        ),
    )

    assert not report.ok


def test_rejected_legacy_output_is_not_executed_by_shadow() -> None:
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    target = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_construct_N"
    )
    target["return_expectations"] = {
        "selected_target_point": "closed_state",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    replay = PlannerRetryReplayService(
        functional_transaction_mode="execution_shadow",
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is None
    report = replay.transactional_execution_report
    assert report is not None and not report.ok
    assert not report.call_results
    assert (
        report.compatibility_mismatches[0].code
        == "transactional_execution_shadow_failed"
    )
    retry_payload = (
        replay.retry_state.to_payload()
        if replay.retry_state is not None
        else {}
    )
    assert "transactional_execution_report" not in json.dumps(retry_payload)


def test_execution_shadow_finalize_has_no_stale_output_fallback() -> None:
    parameters = inspect.signature(
        PlannerRetryReplayService._finalize_functional_replay
    ).parameters

    assert "transactional_output" not in parameters


def test_independent_branch_write_is_not_reclassified_as_hard_mismatch() -> None:
    replay = _replay("nankai", mode="execution_shadow")
    report = replay.transactional_execution_report
    assert report is not None and report.ok
    target = next(
        item
        for item in reversed(report.call_results)
        if item.status == "verified" and item.state_writes
    )
    projection = next(
        item
        for item in replay.functional_reconciliation.projection_map
        if item.call_id == target.call_id
    )
    target_steps = frozenset(projection.step_ids)
    diagnostic = replace(
        replay.diagnostic,
        accepted_prefix=tuple(
            item
            for item in replay.diagnostic.accepted_prefix
            if item.step_id not in target_steps
        ),
        state_write_provenance=tuple(
            item
            for item in replay.diagnostic.state_write_provenance
            if item.step_id not in target_steps
        ),
    )
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    working = build_working_state(
        report.graph,
        parent_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
            attempt=1,
        ),
        handle_registry=registry,
    )
    working.call_states = {
        item.call_id: item for item in report.call_states
    }

    mismatches, deltas = _compare_with_legacy(
        report.graph,
        working=working,
        reconciliation=replay.functional_reconciliation,
        diagnostic=diagnostic,
        call_results=report.call_results,
    )

    assert not mismatches
    assert deltas == (
        FunctionalTransactionBehaviorDelta(
            "transactional_independent_branch_verified",
            target.call_id,
            "legacy prefix replay did not verify this call",
        ),
    )


def test_context_auto_args_refresh_at_final_effective_call_position() -> None:
    case = FUNCTIONAL_BATCH_CASES["heping-ermo"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    ii_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "ii"
    )
    ii_scope["calls"].append(
        {
            "call_id": "test_F_midpoint",
            "capability_id": "midpoint_point",
            "args": {
                "midpoint_definition": {
                    "kind": "fact",
                    "ref": "F_midpoint_of_AE",
                },
            },
            "return_bindings": {
                "midpoint": {"kind": "point", "ref": "F"},
            },
            "return_expectations": {"midpoint": "closed_state"},
            "strategy": "derive the midpoint after endpoint transitions",
            "reason": "exercise final-position Context resolution",
        }
    )
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert plan is not None and validation.ok

    replay = PlannerRetryReplayService(
        functional_transaction_mode="execution_shadow",
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is not None
    report = replay.transactional_execution_report
    assert report is not None and report.ok, report.to_payload()
    assert not report.behavior_deltas
    reconciled = next(
        item
        for item in replay.functional_reconciliation.calls
        if item.call_id == "test_F_midpoint"
    )
    assert reconciled.resolved_args["p1"][0].state_version_id.ordinal == 1
    assert reconciled.resolved_args["p2"][0].state_version_id.ordinal == 2


def test_call_time_semantic_read_selects_latest_working_version() -> None:
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    legacy = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )
    graph = LogicalFunctionalGraphBuilder().build(
        plan,
        legacy.functional_reconciliation,
        handle_registry=registry,
    ).graph
    working = build_working_state(
        graph,
        parent_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
            attempt=1,
        ),
        handle_registry=registry,
    )
    call = next(
        item
        for item in legacy.functional_reconciliation.calls
        if item.call_id == "i_derive_parabola"
    )
    coefficient_values = call.resolved_args["known_coefficients"]
    for value in coefficient_values:
        assert value.state_version_id is not None
        working.runtime_version_values[value.state_version_id] = TypedValue(
            "ParameterValue",
            1,
            source="test",
        )
    original_id = coefficient_values[0].state_version_id
    assert original_id is not None
    original = working.identity_index.version(original_id)
    assert original is not None
    latest_id = StateVersionId(original_id.slot_id, original_id.ordinal + 1)
    latest = replace(
        original,
        version_id=latest_id,
        producer_call_id="synthetic_latest_M",
        previous_version_id=original_id,
        source_version_ids=(original_id,),
    )
    working.identity_index.register(latest)
    working.runtime_version_values[original_id] = TypedValue(
        "ParameterValue",
        1,
        source="test",
    )
    working.runtime_version_values[latest_id] = TypedValue(
        "ParameterValue",
        9,
        source="test",
    )

    prepared = FunctionalCallPreparationService().prepare(
        call_id=call.call_id,
        graph=graph,
        reconciliation=legacy.functional_reconciliation,
        working=working,
        runtime_context=ContextBuilder().build(problem),
        inputs=inputs,
        handle_registry=registry,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )
    selected = next(
        item
        for item in prepared.state_reads
        if item.arg_name == "known_coefficients"
        and item.item_index == 0
    )

    assert selected.selection == "latest"
    assert selected.original_version_id == original_id
    assert selected.selected_version_id == latest_id
    assert selected.runtime_value.value == 9

    hidden_call = replace(
        call,
        resolved_args={
            **call.resolved_args,
            "hidden_coefficients": (coefficient_values[0],),
        },
    )
    hidden_reconciliation = replace(
        legacy.functional_reconciliation,
        calls=tuple(
            hidden_call if item.call_id == call.call_id else item
            for item in legacy.functional_reconciliation.calls
        ),
    )
    resolver_catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    resolver_capability = resolver_catalog.get(call.capability_id)
    assert resolver_capability is not None
    source_arg = next(
        item
        for item in resolver_capability.args
        if item.name == "known_coefficients"
    )
    resolver_catalog = FunctionalCapabilityCatalog(
        {
            **resolver_catalog.items,
            call.capability_id: replace(
                resolver_capability,
                args=(
                    *resolver_capability.args,
                    replace(
                        source_arg,
                        name="hidden_coefficients",
                        binding_authority="resolver",
                    ),
                ),
            ),
        }
    )
    hidden_reconciliation = replace(
        hidden_reconciliation,
        functional_binding_context=(
            FunctionalBindingContextBuilder().build(
                hidden_reconciliation.plan,
                hidden_reconciliation.calls,
                catalog=resolver_catalog,
                object_registry=MathObjectRegistry.from_sources(registry),
            )
        ),
    )
    hidden_prepared = FunctionalCallPreparationService().prepare(
        call_id=call.call_id,
        graph=graph,
        reconciliation=hidden_reconciliation,
        working=working,
        runtime_context=ContextBuilder().build(problem),
        inputs=inputs,
        handle_registry=registry,
        capability_catalog=resolver_catalog,
    )
    hidden_selected = next(
        item
        for item in hidden_prepared.state_reads
        if item.arg_name == "hidden_coefficients"
    )

    assert hidden_selected.selection == "latest"
    assert hidden_selected.selected_version_id == latest_id


def test_verified_commit_is_atomic_when_version_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(payload)
    visibility = ScopeVisibilityResolver(registry)
    index = StateIdentityIndex(visibility)
    first = next(
        item
        for item in _replay(
            "nankai",
            mode="execution_shadow",
        ).transactional_execution_report.committed_versions
    )
    second = replace(
        first,
        version_id=StateVersionId(
            first.version_id.slot_id,
            first.version_id.ordinal + 1,
        ),
        previous_version_id=first.version_id,
    )
    state = WorkingPlannerState(
        parent_context_id="test",
        identity_index=index,
        call_states={
            "call": FunctionalCallExecutionState(
                call_id="call",
                status="running",
                dependency_call_ids=(),
            )
        },
    )
    original_register = StateIdentityIndex.register
    count = 0

    def fail_second(self, version, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("synthetic second-version failure")
        return original_register(self, version, **kwargs)

    monkeypatch.setattr(StateIdentityIndex, "register", fail_second)
    values = {
        first.version_id: TypedValue("Point", Point((1, 1))),
        second.version_id: TypedValue("Point", Point((2, 2))),
    }

    with pytest.raises(RuntimeError, match="second-version"):
        state.commit_verified_transaction(
            "call",
            (first, second),
            values,
        )

    assert state.call_states["call"].status == "running"
    assert not state.committed_versions
    assert not state.runtime_version_values
    assert not state.events


def _failure_partition(graph):
    order = list(graph.canonical_order)
    consumers = {
        call_id: {
            edge.consumer_call_id
            for edge in graph.dependencies
            if edge.producer_call_id == call_id
        }
        for call_id in order
    }
    for root in order:
        descendants = set()
        pending = list(consumers[root])
        while pending:
            call_id = pending.pop()
            if call_id in descendants:
                continue
            descendants.add(call_id)
            pending.extend(consumers.get(call_id, ()))
        root_index = order.index(root)
        independent = {
            call_id
            for call_id in order[root_index + 1 :]
            if call_id not in descendants
        }
        if descendants and independent:
            return root, descendants, independent
    raise AssertionError("fixture has no root with dependent and independent branches")
