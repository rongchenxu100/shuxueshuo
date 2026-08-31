from __future__ import annotations

from dataclasses import replace
import json
from typing import Any

import pytest

from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.functional_logical_graph import (
    LogicalFunctionalGraphBuilder,
)
from shuxueshuo_server.solver.runtime.functional_plan import (
    FunctionalPlanReconciler,
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import (
    problem_to_llm_payload,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)

from _problem_planning_support import cached_planning_binding_fixture


def _logical_graph_case(case_id: str = "nankai"):
    case = FUNCTIONAL_BATCH_CASES[case_id]
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        context,
        problem_binding_catalog,
    ) = cached_planning_binding_fixture(case.problem_id)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=problem_binding_catalog,
    )
    assert reconciliation.ok
    return plan, reconciliation, registry


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixture_builds_typed_logical_graph(case_id: str) -> None:
    plan, reconciliation, registry = _logical_graph_case(case_id)

    result = LogicalFunctionalGraphBuilder().build(
        plan,
        reconciliation,
        handle_registry=registry,
    )

    assert result.issues == ()
    graph = result.graph
    assert set(graph.canonical_order) == {
        call.call_id for call in reconciliation.plan.calls
    }
    order = {
        call_id: index
        for index, call_id in enumerate(graph.canonical_order)
    }
    assert all(
        order[edge.producer_call_id] < order[edge.consumer_call_id]
        for edge in graph.dependencies
    )
    assert graph.answer_bindings
    assert all(
        binding.math_object_id is not None
        for binding in graph.answer_bindings
    )

    forbidden_keys = {
        "runtime_path",
        "state_slot_id",
        "canonical_handle",
        "strategy",
        "reason",
    }
    assert not (_payload_keys(graph.to_payload()) & forbidden_keys)


def test_wire_order_does_not_control_logical_execution_order() -> None:
    plan, reconciliation, registry = _logical_graph_case()
    reversed_plan = replace(
        plan,
        scopes=tuple(
            replace(scope, calls=tuple(reversed(scope.calls)))
            for scope in plan.scopes
        ),
    )

    graph = LogicalFunctionalGraphBuilder().build(
        reversed_plan,
        reconciliation,
        handle_registry=registry,
    ).graph
    order = {
        call_id: index
        for index, call_id in enumerate(graph.canonical_order)
    }

    assert all(
        order[edge.producer_call_id] < order[edge.consumer_call_id]
        for edge in graph.dependencies
    )


def test_alias_and_eliminated_calls_are_not_execution_nodes() -> None:
    plan, reconciliation, registry = _logical_graph_case()
    owner = plan.scopes[0].calls[0]
    alias_id = f"{owner.call_id}_alias"
    dead_id = f"{owner.call_id}_dead"
    augmented = replace(
        plan,
        scopes=(
            replace(
                plan.scopes[0],
                calls=(
                    *plan.scopes[0].calls,
                    replace(owner, call_id=alias_id),
                    replace(owner, call_id=dead_id),
                ),
            ),
            *plan.scopes[1:],
        ),
    )
    aliased_reconciliation = replace(
        reconciliation,
        call_aliases={alias_id: owner.call_id},
    )

    graph = LogicalFunctionalGraphBuilder().build(
        augmented,
        aliased_reconciliation,
        handle_registry=registry,
    ).graph

    assert alias_id in graph.alias_call_ids
    assert dead_id in graph.eliminated_call_ids
    assert alias_id not in graph.canonical_order
    assert dead_id not in graph.canonical_order


def test_answer_binding_requires_typed_allocation_math_object() -> None:
    plan, reconciliation, registry = _logical_graph_case()
    answer_allocation = next(
        returned
        for call in reconciliation.calls
        for returned in call.returns
        if returned.bound_ref is not None
        and returned.bound_ref.kind == "answer"
    )
    calls = tuple(
        replace(
            call,
            returns=tuple(
                replace(returned, math_object_id=None)
                if (
                    call.call_id == answer_allocation.call_id
                    and returned.return_name
                    == answer_allocation.return_name
                )
                else returned
                for returned in call.returns
            ),
        )
        for call in reconciliation.calls
    )

    result = LogicalFunctionalGraphBuilder().build(
        plan,
        replace(reconciliation, calls=calls),
        handle_registry=registry,
    )

    assert "answer_math_object_identity_missing" in {
        item.code for item in result.issues
    }
    assert not any(
        item.answer_handle == answer_allocation.bound_ref.ref
        for item in result.graph.answer_bindings
    )


def test_dependency_kind_must_have_typed_evidence() -> None:
    plan, reconciliation, registry = _logical_graph_case()
    call_ids = tuple(call.call_id for call in reconciliation.plan.calls)
    existing = {
        (producer, consumer)
        for consumer, producers in reconciliation.dependency_graph.items()
        for producer in producers
    }
    producer, consumer = next(
        (producer, consumer)
        for producer in call_ids
        for consumer in call_ids
        if call_ids.index(producer) < call_ids.index(consumer)
        and (producer, consumer) not in existing
    )
    dependency_graph = dict(reconciliation.dependency_graph)
    dependency_graph[consumer] = (
        *dependency_graph.get(consumer, ()),
        producer,
    )

    result = LogicalFunctionalGraphBuilder().build(
        plan,
        replace(
            reconciliation,
            dependency_graph=dependency_graph,
        ),
        handle_registry=registry,
    )

    assert "dependency_kind_unresolved" in {
        item.code for item in result.issues
    }
    assert any(
        item.producer_call_id == producer
        and item.consumer_call_id == consumer
        and item.kind == "unknown"
        for item in result.graph.dependencies
    )


def _payload_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested
            for item in value.values()
            for nested in _payload_keys(item)
        }
    if isinstance(value, (list, tuple)):
        return {
            nested
            for item in value
            for nested in _payload_keys(item)
        }
    return set()
