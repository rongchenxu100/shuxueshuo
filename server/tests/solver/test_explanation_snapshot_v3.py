from __future__ import annotations

import json
import re

import pytest

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
    iter_teaching_sources,
    teaching_source_owners,
)
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import CASE_ID
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


@pytest.fixture(scope="module")
def snapshot_and_execution():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture(CASE_ID)
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    artifacts = orchestrator.last_success_artifacts
    assert artifacts is not None
    execution = artifacts.verified_functional_execution
    assert execution is not None
    return ExplanationSnapshotBuilder().build(artifacts), execution


def _execution_steps(scope):
    yield from scope.scope_steps
    for goal in scope.goals:
        yield from goal.steps
    for child in scope.children:
        yield from _execution_steps(child)


_PRIVATE_AXIS_PARAMETER = re.compile(
    r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+"
)


def _student_safe_runtime_value(value):
    if isinstance(value, dict):
        return {
            str(key): _student_safe_runtime_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_student_safe_runtime_value(item) for item in value]
    if isinstance(value, str):
        return _PRIVATE_AXIS_PARAMETER.sub("t", value)
    return value


def test_snapshot_v3_is_recursive_and_has_no_retired_wire(snapshot_and_execution) -> None:
    snapshot, execution = snapshot_and_execution
    payload = snapshot.to_payload()
    text = json.dumps(payload, ensure_ascii=False)

    assert snapshot.schema_version == "explanation-snapshot/v3"
    assert snapshot.canonical_plan_hash == execution.plan_id
    assert len(tuple(iter_teaching_sources(snapshot.root_scope))) == 12
    for retired in (
        '"scope_steps"',
        '"cross_scope_references"',
        '"teaching_trace"',
        '"return_expectations"',
        '"evidence_refs"',
    ):
        assert retired not in text
    assert explanation_snapshot_from_payload(payload).to_payload() == payload


def test_snapshot_v3_projects_every_materialized_output_without_loss(
    snapshot_and_execution,
) -> None:
    snapshot, execution = snapshot_and_execution
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    for runtime in _execution_steps(execution.root_scope):
        source = sources[runtime.step_id]
        assert set(source.outputs) == {
            str(item["return"]) for item in runtime.actual_outputs
        }
        for item in runtime.actual_outputs:
            projected = source.outputs[str(item["return"])]
            assert projected["runtime_type"] == item["runtime_type"]
            assert projected["value"] == _student_safe_runtime_value(item["value"])
            assert projected["display"]


def test_snapshot_v3_inputs_have_exact_refs_values_and_displays(
    snapshot_and_execution,
) -> None:
    snapshot, _execution = snapshot_and_execution
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    for source in sources.values():
        for values in source.inputs.values():
            assert values
            for item in values:
                assert item["ref"]["kind"] in {"source", "step_result"}
                assert item["runtime_type"]
                assert "value" in item
                assert item["display"]

    path_parabola = sources["derive_path_minimum_ii"].inputs["parabola"][0]
    assert path_parabola["ref"] == {"kind": "source", "ref": "parabola"}
    assert path_parabola["resolved_from"] == {
        "kind": "step_result",
        "step_id": "derive_parametric_parabola_ii",
        "return": "parabola",
    }
    square_side = sources["derive_square_vertex_G_i"].inputs
    assert square_side["side_start"][0]["resolved_from"]["step_id"] == (
        "derive_x_intercept_A_i"
    )
    assert square_side["side_end"][0]["resolved_from"]["step_id"] == (
        "parameterize_axis_point_E_i"
    )


def test_snapshot_v3_problem_source_values_hide_binding_identity(
    snapshot_and_execution,
) -> None:
    snapshot, _execution = snapshot_and_execution
    sources = tuple(iter_teaching_sources(snapshot.root_scope))
    input_payload = {
        source.source_step_id: source.inputs
        for source in sources
    }
    text = json.dumps(input_payload, ensure_ascii=False)
    for forbidden in (
        '"handle"',
        '"math_object_id"',
        '"runtime_node_id"',
        '"scope_id"',
        '"valid_scope"',
        "point:problem:",
        "segment:problem:",
        "function:problem:",
        "symbol:problem:",
    ):
        assert forbidden not in text

    path_target = next(
        source
        for source in sources
        if source.source_step_id == "derive_path_minimum_ii"
    ).inputs["path_minimum_target"][0]["value"]
    assert path_target["path"] == "HF+FM+MG"
    assert path_target["terms"] == [["H", "F"], ["F", "M"], ["M", "G"]]


def test_snapshot_v3_owner_tree_matches_verified_plan(snapshot_and_execution) -> None:
    snapshot, execution = snapshot_and_execution
    snapshot_owners = teaching_source_owners(snapshot.root_scope)

    expected: dict[str, tuple[str, str | None]] = {}

    def visit(scope) -> None:
        for step in scope.scope_steps:
            expected[step.step_id] = (scope.scope_ref, None)
        for goal in scope.goals:
            for step in goal.steps:
                expected[step.step_id] = (scope.scope_ref, goal.goal_ref)
        for child in scope.children:
            visit(child)

    visit(execution.root_scope)
    assert snapshot_owners == expected


def test_snapshot_v3_parser_rejects_retired_or_extra_fields(
    snapshot_and_execution,
) -> None:
    snapshot, _execution = snapshot_and_execution
    payload = snapshot.to_payload()
    payload["cross_scope_references"] = []
    with pytest.raises(ValueError, match="v3 contract"):
        explanation_snapshot_from_payload(payload)


def test_snapshot_v3_contains_no_private_macro_identity(snapshot_and_execution) -> None:
    snapshot, _execution = snapshot_and_execution
    text = json.dumps(snapshot.to_payload(), ensure_ascii=False)
    for forbidden in (
        "#quadratic-square-reflection",
        "PathTransformation",
        "StateVersion",
        "checkpoint_id",
        "provenance_signature",
        "_axis_param_",
    ):
        assert forbidden not in text


def test_snapshot_v3_exposes_x_intercept_selection_authority(
    snapshot_and_execution,
) -> None:
    snapshot, _execution = snapshot_and_execution
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_x_intercept_A_i"
    )
    assert source.outputs["point"]["display"] == "A(-3,0)"
    assert {
        (item["check_id"], item["passed"])
        for item in source.checks
    } >= {
        ("x_axis_y_is_zero", True),
        ("point_on_parabola", True),
        ("left_x_axis_intercept", True),
    }
