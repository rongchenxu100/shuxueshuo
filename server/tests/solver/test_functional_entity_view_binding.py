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


def test_runtime_search_macro_preserves_and_corrects_wrong_entity_hint(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = deepcopy(load_v2_fixture_payload(case))
    reduce_path = next(
        step
        for step in _steps(payload)
        if step["step_id"] == "ii_reduce_path"
    )
    reduce_path["args"]["moving_point"] = "E"
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
    reconciled_call = next(
        item for item in reconciliation.calls if item.call_id == "ii_reduce_path"
    )
    assert dict(reconciled_call.authored_macro_roles) == {
        "moving_point": "point:ii:E"
    }
    assert tuple(
        value.object_ref
        for value in reconciled_call.resolved_args["moving_point"]
    ) == ("point:ii:G",)

    execution = result.replay.transactional_execution_report
    assert execution is not None
    call_result = next(
        item for item in execution.call_results if item.call_id == "ii_reduce_path"
    )
    assert call_result.status == "verified"
    assert call_result.macro_search_report is not None
    role = call_result.macro_search_report.role_resolutions[0]
    assert (role.role, role.authored_ref, role.chosen_ref, role.corrected) == (
        "moving_point",
        "point:ii:E",
        "point:ii:G",
        True,
    )


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
        assert all(item.chosen_ref.startswith("point:") for item in report.role_resolutions)


def test_named_entity_step_result_ref_is_rejected_before_runtime(tmp_path) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = deepcopy(load_v2_fixture_payload(case))
    target = next(
        step
        for step in _steps(payload)
        if step["step_id"] == "ii_1_specialize_parabola"
    )
    target["args"]["expression"] = {
        "step_id": "ii_derive_parabola",
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

    with pytest.raises(ScopedFunctionalPlanError) as exc_info:
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

    assert exc_info.value.code == "functional.named_entity_requires_source_ref"


def test_anonymous_path_witness_remains_an_exact_step_result() -> None:
    payload = load_v2_fixture_payload("tj-2026-nankai-yimo-25")
    target = next(
        step
        for step in _steps(payload)
        if step["step_id"] == "ii_derive_path_model"
    )

    assert target["args"]["path_transformation"] == {
        "step_id": "ii_reduce_path",
        "return": "path_transformation",
    }
