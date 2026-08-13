from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionCheckpoint,
    FunctionalGoalExecutionCheckpointError,
    ScopedFunctionalGoalExecutionService,
    functional_goal_execution_checkpoint_schema,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanAuthority,
    ScopedFunctionalPlanAuthorityReport,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanIssue,
)

from _problem_planning_support import CASES, planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "schemas"
    / "functional-goal-execution-checkpoint.schema.json"
)


def test_checkpoint_python_schema_matches_checked_in_snapshot() -> None:
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == (
        functional_goal_execution_checkpoint_schema()
    )


def test_invalid_json_has_no_scope_shaped_checkpoint(tmp_path) -> None:
    case = CASES[0]
    fixture = planning_binding_fixture(tmp_path / case, case=case)

    result = ScopedFunctionalGoalExecutionService().execute_raw_json(
        "{not-json",
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )

    assert result.checkpoint is None
    assert not result.validation_report.ok


def test_nonretryable_problem_authority_drift_fails_loud(tmp_path) -> None:
    case = CASES[0]
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    drifted_catalog = replace(
        fixture[7],
        planning_context_id="planning-context:foreign",
    )

    with pytest.raises(ScopedFunctionalPlanError) as error:
        ScopedFunctionalGoalExecutionService().execute_raw_json(
            json.dumps(load_v2_fixture_payload(case), ensure_ascii=False),
            inputs=fixture[3],
            planning_context=fixture[1],
            problem_binding_catalog=drifted_catalog,
            handle_registry=fixture[5],
            context=ContextBuilder().build(fixture[2]),
            planner_state_context=fixture[6],
            problem_payload=fixture[4],
        )

    assert error.value.retryable is False
    assert error.value.code == "planner.problem_revision_drift"


def test_placement_finalization_failure_still_creates_checkpoint(
    tmp_path,
    monkeypatch,
) -> None:
    issue = ScopedFunctionalPlanIssue(
        "functional.step_scope_authority_drift",
        "$.steps['forced']",
        "forced placement failure",
    )

    def fail_finalize(self, reconciliation):
        return None, ScopedFunctionalPlanAuthorityReport(issues=(issue,))

    monkeypatch.setattr(
        ScopedFunctionalPlanAuthority,
        "finalize_reconciliation",
        fail_finalize,
    )
    result, _fixture = _execute(
        tmp_path,
        CASES[0],
        load_v2_fixture_payload(CASES[0]),
    )

    assert result.checkpoint is not None
    assert result.checkpoint.blocked_stage == "placement_finalize"
    assert result.checkpoint.transaction_attempted is False
    assert result.checkpoint.transaction_ok is False
    assert result.checkpoint.all_required_goals_verified is False
    assert result.checkpoint.root_issues == (
        {
            "stage": "placement_finalize",
            "code": "functional.step_scope_authority_drift",
            "path": "$.steps['forced']",
            "message": "forced placement failure",
        },
    )


def test_bad_step_blocks_only_its_suffix_and_executes_independent_goals(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    step = _step(payload, "reduce_equal_length_ray_path_ii")
    step["args"]["point_on_ray"] = "not_a_real_ref"

    result, fixture = _execute(tmp_path, case, payload)
    checkpoint = result.checkpoint
    assert checkpoint is not None
    steps = _checkpoint_steps(checkpoint)

    assert steps["reduce_equal_length_ray_path_ii"].status == (
        "authority_invalid"
    )
    assert steps["solve_parameter_from_minimum_ii"].status == (
        "blocked_by_dependency"
    )
    assert steps["solve_parameter_from_minimum_ii"].blocked_by == (
        "reduce_equal_length_ray_path_ii",
    )
    assert steps["derive_curve_intersection_E_i"].status == (
        "runtime_verified"
    )
    assert steps["derive_parametric_parabola_ii"].status == (
        "runtime_verified"
    )
    metrics = checkpoint.to_prompt_payload()["metrics"]
    assert metrics["authority_invalid_step_count"] == 1
    assert metrics["blocked_by_dependency_step_count"] == 1
    assert metrics["provisional_executed_step_count"] >= 2
    assert metrics["transaction_attempted"] is True
    assert metrics["transaction_ok"] is True
    assert metrics["blocked_stage"] == "authoring_authority"

    sidecar = result.replay.functional_reconciliation.functional_problem_binding_context
    assert sidecar is not None
    checkpoint.verify_authority(
        planning_context=fixture[1],
        binding_catalog=fixture[7],
        authority=result.authority,
        binding_context=sidecar,
    )


def test_checkpoint_round_trip_hash_and_current_authority_are_fail_closed(
    tmp_path,
) -> None:
    result, fixture = _execute(
        tmp_path,
        CASES[-1],
        load_v2_fixture_payload(CASES[-1]),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    payload = checkpoint.authority_payload()
    assert FunctionalGoalExecutionCheckpoint.from_payload(payload) == checkpoint

    tampered = deepcopy(payload)
    tampered["problem_revision_id"] = "problem-revision:foreign"
    with pytest.raises(FunctionalGoalExecutionCheckpointError):
        FunctionalGoalExecutionCheckpoint.from_payload(tampered)

    stale = deepcopy(payload)
    stale["problem_revision_id"] = "problem-revision:foreign"
    stale["checkpoint_id"] = stable_hash(
        {key: value for key, value in stale.items() if key != "checkpoint_id"}
    )
    restored = FunctionalGoalExecutionCheckpoint.from_payload(stale)
    with pytest.raises(
        FunctionalGoalExecutionCheckpointError,
        match="problem_revision_id",
    ):
        restored.verify_authority(
            planning_context=fixture[1],
            binding_catalog=fixture[7],
        )


def test_checkpoint_prompt_payload_hides_problem_authority(tmp_path) -> None:
    result, fixture = _execute(
        tmp_path,
        CASES[0],
        load_v2_fixture_payload(CASES[0]),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    prompt_text = json.dumps(
        checkpoint.to_prompt_payload(),
        ensure_ascii=False,
        sort_keys=True,
    )
    assert fixture[1].planning_context_id not in prompt_text
    assert fixture[1].problem_revision_id not in prompt_text
    assert fixture[1].problem_semantic_hash not in prompt_text
    assert "source_unit_id" not in prompt_text
    assert "runtime_node_id" not in prompt_text
    assert "state_version" not in prompt_text
    assert "math_object" not in prompt_text


def test_checkpoint_resolved_inputs_include_actual_step_result(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    result, _fixture = _execute(
        tmp_path,
        case,
        load_v2_fixture_payload(case),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    translated = _checkpoint_steps(checkpoint)["derive_translated_D_i"]
    source = next(
        item for item in translated.resolved_inputs if item["arg"] == "source"
    )
    assert source["source"] == {
        "step_id": "derive_y_intercept_C_i",
        "return": "point",
    }
    assert source["resolution"] == "step_result"
    assert source["runtime_type"] == "Point"
    assert "value" in source or "value_omitted_reason" in source


def test_unique_fact_placeholder_refs_are_safely_canonicalized(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    step = _step(payload, "reduce_equal_length_ray_path_ii")
    for arg_name in (
        "path_minimum_target",
        "point_on_segment",
        "point_on_ray",
    ):
        step["args"][arg_name] = arg_name

    result, _fixture = _execute(tmp_path, case, payload)
    assert result.authority_report.ok
    assert result.authority is not None
    records = tuple(
        item
        for item in result.authority.normalizations
        if item.action == "canonicalize_unique_fact_ref"
    )
    assert {
        (item.from_ref, item.to_ref, item.fact_type)
        for item in records
    } == {
        (
            "path_minimum_target",
            "path_minimum_target_o_m_b_n",
            "path_minimum_target",
        ),
        ("point_on_segment", "point_on_segment_m_bc", "point_on_segment"),
        ("point_on_ray", "point_on_ray_n_cd", "point_on_ray"),
    }


def test_known_wrong_fact_ref_is_not_rewritten_by_type(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    _step(payload, "reduce_equal_length_ray_path_ii")["args"][
        "point_on_ray"
    ] = "point_on_segment_m_bc"

    result, _fixture = _execute(tmp_path, case, payload)
    assert not result.authority_report.ok
    assert not any(
        item.action == "canonicalize_unique_fact_ref"
        and item.arg_name == "point_on_ray"
        for item in result.authority_report.normalizations
    )


def test_source_ref_cannot_read_a_step_produced_latest_state(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    _step(payload, "derive_translated_D_i")["args"]["source"] = "C"

    result, _fixture = _execute(tmp_path, case, payload)
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None
    assert reconciliation.ok
    assert result.authority_report.ok
    assert result.authoring_authority is not None
    assert result.checkpoint is not None
    steps = _checkpoint_steps(result.checkpoint)
    assert steps["derive_translated_D_i"].status == "authority_invalid"
    assert steps["derive_translated_D_i"].typed_issue == {
        "stage": "reconciliation_binding",
        "code": "functional.dynamic_source_ref_requires_step_result",
        "message": (
            "a FunctionalPlan v2 SourceRef resolved to a dynamic call result; "
            "use an explicit StepResultRef"
        ),
        "arg_name": "source",
        "item_index": 0,
        "source_ref": "C",
        "required_step_result": {
            "step_id": "derive_y_intercept_C_i",
            "return": "point",
        },
    }
    assert steps["derive_parabola_i"].status == "blocked_by_dependency"
    assert steps["derive_parametric_parabola_ii"].status == "runtime_verified"
    assert result.checkpoint.transaction_attempted is True
    assert result.checkpoint.all_required_goals_verified is False
    assert result.checkpoint.blocked_stage == "reconciliation_binding"


def test_projected_sibling_return_is_allocated_after_consumer_isolated(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    _step(payload, "derive_weighted_minimum_iii")["args"][
        "curve_point"
    ] = "M"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    steps = _checkpoint_steps(checkpoint)
    assert steps["derive_weighted_minimum_iii"].status == "authority_invalid"
    assert steps["derive_weighted_minimum_iii"].typed_issue["code"] == (
        "functional.dynamic_source_ref_requires_step_result"
    )
    assert steps["transform_weighted_path_iii"].status == "pruned_dead"
    assert checkpoint.transaction_attempted is True
    assert checkpoint.all_required_goals_verified is False


def test_dead_pure_step_stays_in_authored_plan_but_not_effective_plan(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    goal = _scope(payload["root_scope"], "i_2")["goals"][0]
    goal.setdefault("steps", []).append(
        {
            "step_id": "dead_vertex",
            "capability_id": "quadratic_vertex_point",
            "args": {
                "parabola": {
                    "step_id": "derive_parabola_i",
                    "return": "parabola",
                }
            },
        }
    )

    result, _fixture = _execute(tmp_path, case, payload)
    assert result.authority is not None
    assert result.authority.pruned_step_ids == ("dead_vertex",)
    assert "dead_vertex" in {
        item.step_id for item in result.authority.scoped_plan.steps
    }
    assert "dead_vertex" not in {
        item.call_id for item in result.authority.lowered_plan.calls
    }
    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert _checkpoint_steps(checkpoint)["dead_vertex"].status == "pruned_dead"
    assert all(
        item.call_id != "dead_vertex"
        for item in result.replay.transactional_attempt_result.execution_report.call_results
    )


@pytest.mark.parametrize("case", CASES)
def test_v2_step_ids_remain_canonical_without_call_aliases(
    tmp_path,
    case,
) -> None:
    result, _fixture = _execute(
        tmp_path,
        case,
        load_v2_fixture_payload(case),
    )
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None and reconciliation.ok
    assert reconciliation.call_aliases == {}
    assert result.authority is not None
    assert all(
        item.step_id == item.canonical_call_id
        for item in result.authority.step_authorities.values()
    )


def _execute(tmp_path, case, payload):
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    result = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )
    return result, fixture


def _checkpoint_steps(checkpoint):
    result = {}

    def visit(scope):
        result.update((item.step_id, item) for item in scope.scope_steps)
        for goal in scope.goals:
            result.update((item.step_id, item) for item in goal.steps)
        for child in scope.children:
            visit(child)

    visit(checkpoint.root_scope)
    return result


def _step(payload, step_id):
    for scope in _iter_scope_payloads(payload["root_scope"]):
        for step in scope.get("steps", []):
            if step["step_id"] == step_id:
                return step
        for goal in scope.get("goals", []):
            for step in goal.get("steps", []):
                if step["step_id"] == step_id:
                    return step
    raise KeyError(step_id)


def _scope(scope, scope_ref):
    if scope["scope_ref"] == scope_ref:
        return scope
    for child in scope.get("children", []):
        result = _scope(child, scope_ref)
        if result is not None:
            return result
    return None


def _iter_scope_payloads(scope):
    yield scope
    for child in scope.get("children", []):
        yield from _iter_scope_payloads(child)
