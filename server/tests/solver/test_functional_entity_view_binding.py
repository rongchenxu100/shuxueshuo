from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Iterator

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanError,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan_replay import (
    ScopedFunctionalPlanReplayService,
)

from _problem_planning_support import CASES, planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


def _scopes(scope: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield scope
    for child in scope.get("children", ()):
        yield from _scopes(child)


def _steps(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for scope in _scopes(payload["root_scope"]):
        yield from scope.get("steps", ())
        for goal in scope.get("goals", ()):
            yield from goal.get("steps", ())


def _step_result_refs(value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        if set(value) == {"step_id", "return"}:
            yield str(value["step_id"]), str(value["return"])
            return
        for child in value.values():
            yield from _step_result_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _step_result_refs(child)


@pytest.mark.parametrize("case", CASES)
def test_named_entity_outputs_are_read_by_entity_ref_not_step_result(case) -> None:
    payload = load_v2_fixture_payload(case)
    steps = {step["step_id"]: step for step in _steps(payload)}

    observed = 0
    for step in steps.values():
        for producer_id, return_name in _step_result_refs(step.get("args", {})):
            observed += 1
            producer = steps[producer_id]
            assert return_name not in producer.get("output_targets", {}), (
                case,
                step["step_id"],
                producer_id,
                return_name,
            )
    assert observed > 0


def test_named_entity_source_ref_builds_latest_visible_producer_dependency(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path, case=case)
    result = ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(load_v2_fixture_payload(case), ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )

    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None and reconciliation.ok
    assert "ii_derive_parabola" in reconciliation.dependency_graph[
        "ii_1_specialize_parabola"
    ]
    assert "ii_1_solve_m" in reconciliation.dependency_graph[
        "ii_1_specialize_parabola"
    ]


def test_hidden_entity_state_can_depend_on_later_same_scope_producer(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = deepcopy(load_v2_fixture_payload(case))
    scope = next(
        item for item in _scopes(payload["root_scope"])
        if item["scope_ref"] == "ii"
    )
    steps = list(scope["steps"])
    midpoint_index = next(
        index
        for index, step in enumerate(steps)
        if step["step_id"] == "ii_compute_F"
    )
    midpoint = steps.pop(midpoint_index)
    parabola_index = next(
        index
        for index, step in enumerate(steps)
        if step["step_id"] == "ii_derive_parabola"
    )
    parabola = steps.pop(parabola_index)
    producer_index = next(
        index
        for index, step in enumerate(steps)
        if step["step_id"] == "ii_construct_N"
    )
    steps.insert(producer_index, midpoint)
    steps.insert(producer_index + 1, parabola)
    scope["steps"] = steps
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path, case=case)

    result = ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )

    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None and reconciliation.ok
    assert "ii_construct_N" in reconciliation.dependency_graph[
        "ii_compute_F"
    ]
    assert "ii_construct_N" in reconciliation.dependency_graph[
        "ii_derive_parabola"
    ]
    reports = {
        item.call_id: item
        for item in result.replay.transactional_execution_report.call_results
    }
    assert reports["ii_construct_N"].status == "verified"
    assert reports["ii_compute_F"].status == "verified"


def test_runtime_search_macro_never_reads_sibling_planned_point(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = deepcopy(load_v2_fixture_payload(case))
    scope_ii = next(
        item for item in _scopes(payload["root_scope"])
        if item["scope_ref"] == "ii"
    )
    goal = scope_ii["goals"][0]
    sibling_sensitive_steps = {
        "derive_parametric_parabola_ii",
        "derive_x_intercept_B_ii",
    }
    goal["steps"] = [
        step
        for step in goal["steps"]
        if step["step_id"] not in sibling_sensitive_steps
    ]
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path, case=case)

    with pytest.raises(ScopedFunctionalPlanError) as error:
        ScopedFunctionalPlanReplayService().replay_raw_json(
            json.dumps(payload, ensure_ascii=False),
            inputs=inputs,
            planning_context=planning_context,
            problem_binding_catalog=binding_catalog,
            handle_registry=registry,
            context=ContextBuilder().build(problem),
            planner_state_context=planner_context,
            problem_payload=problem_payload,
        )

    assert error.value.code == (
        "functional.equal_length_ray_point_state_unavailable"
    )
    issue_payload = [item.to_payload() for item in error.value.issues]
    assert not any(
        item["code"] == "functional.call_scope_not_visible_for_goal"
        for item in issue_payload
    )
    assert all(
        "derive_x_intercept_B_i"
        not in item.get("details", {}).get("repair_call_ids", ())
        for item in issue_payload
    )


def test_named_step_result_normalization_retains_exact_producer_edge(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = deepcopy(load_v2_fixture_payload(case))
    consumer = next(
        step
        for step in _steps(payload)
        if step["step_id"] == "derive_x_intercept_B_i"
    )
    consumer["args"]["parabola"] = {
        "step_id": "derive_parabola_i",
        "return": "parabola",
    }
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path, case=case)

    result = ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )

    canonical_consumer = next(
        step
        for step in _steps(result.authority.scoped_plan.to_payload())
        if step["step_id"] == "derive_x_intercept_B_i"
    )
    assert canonical_consumer["args"]["parabola"] == "parabola"
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None and reconciliation.ok
    assert "derive_parabola_i" in reconciliation.dependency_graph[
        "derive_x_intercept_B_i"
    ]


@pytest.mark.parametrize("case", CASES)
def test_recorded_runtime_search_reports_cover_declared_macro_roles(
    tmp_path,
    case,
) -> None:
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path, case=case)
    result = ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(load_v2_fixture_payload(case), ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )
    macro_specs = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    reports = tuple(
        item.macro_search_report
        for item in result.replay.transactional_execution_report.call_results
        if item.macro_search_report is not None
    )
    for report in reports:
        spec = macro_specs.require(report.macro_id)
        assert spec.search is not None
        assert tuple(
            item.role for item in report.role_resolutions
        ) == spec.search.searchable_roles
        assert all(
            item.chosen_ref.startswith(
                ("point:", "fact:", "symbol:", "function:")
            )
            for item in report.role_resolutions
        )
        assert all("#" not in item.chosen_ref for item in report.role_resolutions)
        assert all(
            item.call_count is not None and item.call_count > 0
            for item in report.evaluations
            if item.passed
        )


def test_named_entity_step_result_ref_is_normalized_before_runtime(tmp_path) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = deepcopy(load_v2_fixture_payload(case))
    target = next(
        step
        for step in _steps(payload)
        if step["step_id"] == "ii_1_specialize_parabola"
    )
    target["args"]["expression"] = {
        "step_id": "ii_derive_parabola",
        "return": "coefficients",
    }
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path, case=case)

    result = ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )

    canonical_target = next(
        step
        for step in _steps(result.authority.scoped_plan.to_payload())
        if step["step_id"] == "ii_1_specialize_parabola"
    )
    assert canonical_target["args"]["expression"] == "parabola"
    assert any(
        item.action == "canonicalize_unique_return_role"
        and item.from_ref == "coefficients"
        and item.to_ref == "parabola"
        for item in result.authority.normalizations
    )
    assert any(
        item.action == "canonicalize_named_entity_result_ref"
        and item.from_ref == "ii_derive_parabola.parabola"
        and item.to_ref == "parabola"
        for item in result.authority.normalizations
    )
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None and reconciliation.ok
    assert "ii_derive_parabola" in reconciliation.dependency_graph[
        "ii_1_specialize_parabola"
    ]


def test_atomic_path_macro_does_not_expose_internal_path_result() -> None:
    payload = load_v2_fixture_payload("tj-2026-nankai-yimo-25")
    target = next(
        step
        for step in _steps(payload)
        if step["step_id"] == "ii_path_minimum"
    )

    assert set(target["args"]) == {
        "path_minimum_target",
        "segment_binding_relation",
    }
    assert "PathTransformation" not in json.dumps(target, ensure_ascii=False)
    assert "path_witness" not in json.dumps(target, ensure_ascii=False)
