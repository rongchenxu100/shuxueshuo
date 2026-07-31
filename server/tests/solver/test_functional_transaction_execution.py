from __future__ import annotations

import inspect
import json
from dataclasses import replace

import pytest

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
    FunctionalTransactionBehaviorDelta,
    FunctionalTransactionalInterpreter,
    _compare_with_legacy,
)
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_transaction_shadow import (
    FunctionalCallExecutionState,
    WorkingPlannerState,
    build_working_state,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
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
)
from shuxueshuo_server.solver.runtime.state_identity import (
    IndexedStateVersion,
    ScopeVisibilityResolver,
    StateIdentityIndex,
    StateVersionId,
)


def _replay(case_id: str, *, mode: str):
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
    ).replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_transaction_execution_has_zero_mismatch(
    case_id: str,
) -> None:
    replay = _replay(case_id, mode="execution_shadow")

    assert replay.output is not None
    assert replay.transactional_shadow_report is not None
    report = replay.transactional_execution_report
    assert report is not None
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
