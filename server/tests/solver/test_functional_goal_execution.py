from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionCheckpoint,
    FunctionalGoalExecutionCheckpointError,
    ScopedFunctionalGoalExecutionService,
    _provisional_state_payload,
    _reconciliation_dependency_blocks,
    functional_goal_execution_checkpoint_schema,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    _semantic_object_consumer_scopes,
    _unique_answer_for_object_binding,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalPlan,
    FunctionalScope,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanAuthority,
    ScopedFunctionalPlanAuthorityReport,
    ScopedFunctionalPlanError,
    ScopedFunctionalScope,
    ScopedFunctionalStep,
    ScopedFunctionalPlanIssue,
    ScopedReturnBinding,
    scoped_functional_plan_id,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef

from _problem_planning_support import CASES, planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


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


def test_provisional_payload_recursively_normalizes_immutable_diagnostics() -> None:
    issue = SimpleNamespace(
        to_payload=lambda: MappingProxyType(
            {
                "code": "functional.method_input_state_unavailable",
                "expected": MappingProxyType(
                    {"allowed_bases": (("b",), ("c",))}
                ),
                "observed": MappingProxyType({"declared": frozenset()}),
                "authority_details": MappingProxyType(
                    {"nested": MappingProxyType({"count": 2})}
                ),
            }
        )
    )
    call_result = SimpleNamespace(
        call_id="derive_parabola",
        status="failed",
        runtime_results=(),
        root_issues=(issue,),
    )
    transaction = SimpleNamespace(
        execution_report=SimpleNamespace(
            call_states=(),
            call_results=(call_result,),
        )
    )

    payload = _provisional_state_payload(transaction)

    json.dumps(payload, ensure_ascii=False, sort_keys=True)
    root_issue = payload["call_results"][0]["root_issues"][0]
    assert root_issue["expected"]["allowed_bases"] == [["b"], ["c"]]
    assert root_issue["observed"]["declared"] == []


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
            json.dumps(load_v3_fixture_payload(case), ensure_ascii=False),
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


def test_inferred_parent_point_target_survives_liveness_and_executes(tmp_path) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v3_fixture_payload(case)
    derive_d = _step(payload, "derive_curve_point_D_ii")
    derive_d.pop("return_bindings")

    result, _fixture = _execute(tmp_path, case, payload)

    assert result.checkpoint is not None
    checkpoint_step = _checkpoint_steps(result.checkpoint)["derive_curve_point_D_ii"]
    assert checkpoint_step.status == "runtime_verified"
    assert result.checkpoint.all_required_goals_verified


def test_same_point_identity_can_have_scope_local_sibling_producers(tmp_path) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = load_v3_fixture_payload(case)
    scope_ii = _scope(payload["root_scope"], "ii")
    shared_steps = scope_ii.pop("steps")

    def rewrite_step_ids(value, replacements):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "step_id" and item in replacements:
                    value[key] = replacements[item]
                else:
                    rewrite_step_ids(item, replacements)
        elif isinstance(value, list):
            for item in value:
                rewrite_step_ids(item, replacements)

    expected_steps = []
    for scope_id in ("ii_1", "ii_2"):
        replacements = {
            item["step_id"]: f"{scope_id}_{item['step_id']}"
            for item in shared_steps
        }
        local_steps = deepcopy(shared_steps)
        rewrite_step_ids(local_steps, replacements)
        scope = _scope(payload["root_scope"], scope_id)
        rewrite_step_ids(scope, replacements)
        scope["steps"] = [*local_steps, *scope.get("steps", [])]
        expected_steps.append(replacements["ii_construct_N"])

    result, _fixture = _execute(tmp_path, case, payload)

    assert result.checkpoint is not None
    steps = _checkpoint_steps(result.checkpoint)
    assert all(steps[step_id].status == "runtime_verified" for step_id in expected_steps)
    assert result.checkpoint.all_required_goals_verified


def test_reconciliation_dependency_blocks_never_include_sibling_producer() -> None:
    sibling_writer = ScopedFunctionalStep(
        step_id="sibling_writer",
        capability_id="synthetic_point_producer",
        args={},
        return_bindings={
            "point": ScopedReturnBinding(kind="existing", ref="D")
        },
        return_expectations={"point": "closed_state"},
    )
    ancestor_writer = replace(sibling_writer, step_id="ancestor_writer")
    consumer = ScopedFunctionalStep(
        step_id="consumer",
        capability_id="synthetic_point_consumer",
        args={},
        return_bindings={},
        return_expectations={},
    )
    issue = SimpleNamespace(
        call_id=consumer.step_id,
        scope_id="ii",
        details={"object_ref": "point:D"},
    )
    point_source = SimpleNamespace(
        math_object_id=SimpleNamespace(value="point:D")
    )
    catalog = SimpleNamespace(
        scope_parent_ids={"problem": None, "i": "problem", "ii": "problem"},
        resolve_input_binding=lambda **_kwargs: SimpleNamespace(
            typed_sources=(point_source,)
        ),
    )

    sibling_only = ScopedFunctionalPlan(
        root_scope=ScopedFunctionalScope(
            scope_ref="problem",
            children=(
                ScopedFunctionalScope(scope_ref="i", steps=(sibling_writer,)),
                ScopedFunctionalScope(scope_ref="ii", steps=(consumer,)),
            ),
        )
    )
    assert _reconciliation_dependency_blocks(
        sibling_only,
        (issue,),
        binding_catalog=catalog,
        invalid_step_ids={sibling_writer.step_id},
        blocked_by={},
    ) == {}

    ancestor_and_sibling = ScopedFunctionalPlan(
        root_scope=replace(
            sibling_only.root_scope,
            steps=(ancestor_writer,),
        )
    )
    assert _reconciliation_dependency_blocks(
        ancestor_and_sibling,
        (issue,),
        binding_catalog=catalog,
        invalid_step_ids={sibling_writer.step_id, ancestor_writer.step_id},
        blocked_by={},
    ) == {consumer.step_id: (ancestor_writer.step_id,)}


def test_semantic_object_consumers_never_select_sibling_producer() -> None:
    object_ref = "point:problem:D"
    sibling_writer = FunctionalCall(
        call_id="sibling_writer",
        capability_id="point_producer",
        args={},
        return_bindings={},
        strategy="produce D in sibling i",
        reason="scope visibility regression",
    )
    ancestor_writer = replace(sibling_writer, call_id="ancestor_writer")
    consumer = FunctionalCall(
        call_id="consumer",
        capability_id="point_consumer",
        args={"point": (SemanticRef("D", "point", "Point"),)},
        return_bindings={},
        strategy="consume D in sibling ii",
        reason="scope visibility regression",
    )
    producer_capability = SimpleNamespace(
        returns=(SimpleNamespace(name="point"),),
        auto_args=(),
    )
    consumer_capability = SimpleNamespace(returns=(), auto_args=())
    catalog = SimpleNamespace(
        get=lambda capability_id: (
            producer_capability
            if capability_id == "point_producer"
            else consumer_capability
        )
    )
    registry = SimpleNamespace(
        ancestor_scopes=lambda scope_id: {
            "problem": ("problem",),
            "i": ("problem", "i"),
            "ii": ("problem", "ii"),
        }[scope_id]
    )
    semantic_index = SimpleNamespace(
        handle_registry=registry,
        object_refs_for=lambda ref, **_kwargs: (
            (object_ref,) if ref.ref == "D" else ()
        ),
        resolve=lambda *_args, **_kwargs: (None, ()),
    )

    def consumers(plan, hints):
        return _semantic_object_consumer_scopes(
            plan,
            semantic_index=semantic_index,
            catalog=catalog,
            future_return_object_hints=hints,
        )

    sibling_only = FunctionalPlan(
        scopes=(
            FunctionalScope("problem", "problem", ()),
            FunctionalScope("i", "i", (sibling_writer,)),
            FunctionalScope("ii", "ii", (consumer,)),
        ),
        typed_dependency_graph={"sibling_writer": (), "consumer": ()},
    )
    assert consumers(
        sibling_only,
        {("sibling_writer", "point"): (object_ref,)},
    ) == {}

    ancestor_and_sibling = FunctionalPlan(
        scopes=(
            FunctionalScope("problem", "problem", (ancestor_writer,)),
            FunctionalScope("i", "i", (sibling_writer,)),
            FunctionalScope("ii", "ii", (consumer,)),
        ),
        typed_dependency_graph={
            "ancestor_writer": (),
            "sibling_writer": (),
            "consumer": (),
        },
    )
    assert consumers(
        ancestor_and_sibling,
        {
            ("ancestor_writer", "point"): (object_ref,),
            ("sibling_writer", "point"): (object_ref,),
        },
    ) == {
        ("ancestor_writer", object_ref): (("consumer", "ii"),),
    }


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
        load_v3_fixture_payload(CASES[0]),
    )

    assert result.checkpoint is not None
    assert result.checkpoint.blocked_stage == "placement_finalize"
    assert result.checkpoint.transaction_attempted is False
    assert result.checkpoint.transaction_ok is False
    assert result.checkpoint.all_required_goals_verified is False
    assert len(result.checkpoint.root_issues) == 1
    prompt_issue = result.checkpoint.root_issues[0]
    assert prompt_issue["schema_version"] == "functional-prompt-diagnostic/v1"
    assert prompt_issue["stage"] == "placement_finalize"
    assert prompt_issue["code"] == "functional.step_scope_authority_drift"
    assert prompt_issue["retryability"] == "planner_repairable"
    authority = result.checkpoint.diagnostic_authorities[0]
    assert authority["original_message"] == "forced placement failure"
    assert authority["authority_details"]["path"] == "$.steps['forced']"


def test_bad_step_blocks_only_its_suffix_and_executes_independent_goals(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v3_fixture_payload(case)
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
        goal_authority=result.authoring_authority,
        dependency_graph=result.replay.functional_reconciliation.dependency_graph,
        binding_context=sidecar,
    )
    assert result.canonical_plan is not None
    assert checkpoint.plan_id == scoped_functional_plan_id(
        result.canonical_plan
    )
    assert checkpoint.execution_graph_signature != checkpoint.plan_id


def test_checkpoint_round_trip_hash_and_current_authority_are_fail_closed(
    tmp_path,
) -> None:
    result, fixture = _execute(
        tmp_path,
        CASES[-1],
        load_v3_fixture_payload(CASES[-1]),
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
        load_v3_fixture_payload(CASES[0]),
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
        load_v3_fixture_payload(case),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    translated = _checkpoint_steps(checkpoint)["derive_translated_D_i"]
    source = next(
        item for item in translated.resolved_inputs if item["arg"] == "source"
    )
    assert source["source"] == "C"
    assert source["resolution"] == "source_snapshot"
    _assert_named_entity_pin(
        result.authority,
        consumer_call_id="derive_translated_D_i",
        arg_name="source",
        semantic_ref="C",
        producer_call_id="derive_y_intercept_C_i",
        return_name="point",
    )


@pytest.mark.parametrize("case", CASES)
def test_state_writers_keep_v2_semantic_owner_scope(tmp_path, case) -> None:
    result, _fixture = _execute(
        tmp_path,
        case,
        load_v3_fixture_payload(case),
    )
    assert result.authority is not None
    assert result.replay is not None
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None
    calls = {item.call_id: item for item in reconciliation.calls}

    state_writer_count = 0
    for step_id, step_authority in result.authority.step_authorities.items():
        call = calls.get(step_id)
        if call is None or not any(
            allocation.logical_state_key is not None
            and allocation.typed_slot_id is not None
            for allocation in call.returns
        ):
            continue
        state_writer_count += 1
        assert call.scope_id == step_authority.semantic_owner_scope_id
        assert (
            step_authority.execution_scope_id
            == step_authority.semantic_owner_scope_id
        )

    assert state_writer_count > 0


def test_checkpoint_uses_public_return_roles_for_facade_runtime_outputs(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    result, _fixture = _execute(
        tmp_path,
        case,
        load_v3_fixture_payload(case),
    )

    checkpoint = result.checkpoint
    assert checkpoint is not None
    steps = _checkpoint_steps(checkpoint)
    adjacent = steps["derive_square_vertex_G_ii"]
    assert [item["return"] for item in adjacent.actual_outputs] == [
        "adjacent_vertex"
    ]
    minimum = steps["derive_path_minimum_ii"]
    assert {
        item["return"] for item in minimum.actual_outputs
    } >= {
        "straightened_endpoint_1",
        "straightened_endpoint_2",
        "path_minimum_expression",
    }
    consumer = steps["derive_minimum_point_G_ii"]
    endpoint_inputs = tuple(
        item
        for item in consumer.resolved_inputs
        if item["arg"] in {"minimum_point_1", "minimum_point_2"}
    )
    assert len(endpoint_inputs) == 2
    assert all(item["resolution"] == "step_result" for item in endpoint_inputs)


def test_stable_object_ref_uses_source_snapshot_before_any_visible_write(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    result, _fixture = _execute(
        tmp_path,
        case,
        load_v3_fixture_payload(case),
    )

    checkpoint = result.checkpoint
    assert checkpoint is not None
    intercept = _checkpoint_steps(checkpoint)["derive_y_intercept_C_i"]
    source = next(
        item for item in intercept.resolved_inputs if item["arg"] == "quadratic"
    )
    assert source["source"] == "parabola"
    assert source["resolution"] == "source_snapshot"
    point = next(
        item for item in intercept.actual_outputs if item["return"] == "point"
    )
    assert point["value"] == ["0", "-3"]


def test_unique_fact_placeholder_refs_are_safely_canonicalized(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v3_fixture_payload(case)
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
    payload = load_v3_fixture_payload(case)
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


def test_complete_call_drops_unknown_capability_arg_before_execution(
    tmp_path,
) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v3_fixture_payload(case)
    step = _step(payload, "derive_curve_point_D_ii")
    step["args"]["point"] = "D"

    result, _fixture = _execute(tmp_path, case, payload)

    assert result.authority_report.ok, result.authority_report.to_payload()
    assert result.checkpoint is not None
    assert result.checkpoint.all_required_goals_verified is True
    assert result.canonical_plan is not None
    assert set(
        _step(
            result.canonical_plan.to_payload(),
            "derive_curve_point_D_ii",
        )["args"]
    ) == {"parabola"}
    assert any(
        item.action == "drop_unknown_capability_arg"
        and item.step_id == "derive_curve_point_D_ii"
        and item.capability_id == "point_on_parabola_at_x"
        and item.arg_name == "point"
        and item.reason == "declared_call_contract_complete"
        for item in result.authority_report.normalizations
    )


def test_unknown_arg_is_not_dropped_when_required_arg_is_missing(
    tmp_path,
) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v3_fixture_payload(case)
    step = _step(payload, "derive_curve_point_D_ii")
    step["args"] = {"point": "D"}

    result, _fixture = _execute(tmp_path, case, payload)

    assert not result.authority_report.ok
    assert not any(
        item.action == "drop_unknown_capability_arg"
        and item.step_id == "derive_curve_point_D_ii"
        for item in result.authority_report.normalizations
    )
    assert result.checkpoint is not None
    failed = _checkpoint_steps(result.checkpoint)["derive_curve_point_D_ii"]
    assert failed.status == "authority_invalid"
    assert failed.typed_issue is not None
    assert failed.typed_issue["step_id"] == "derive_curve_point_D_ii"
    assert failed.typed_issue["capability_id"] == "point_on_parabola_at_x"
    assert failed.typed_issue["repair_action"] == (
        "repair_capability_arguments"
    )
    assert failed.typed_issue["subjects"] == [
        {"arg_name": "parabola"}
    ]
    assert failed.typed_issue["expected"] == {
        "expected_allowed_args": ["parabola"],
        "expected_required_args": ["parabola"],
    }
    assert failed.typed_issue["observed"] == {
        "observed_args": ["point"],
        "observed_invalid_cardinality_args": [],
        "observed_missing_required_args": ["parabola"],
        "observed_unknown_args": ["point"],
    }
    authority = next(
        item
        for item in result.checkpoint.diagnostic_authorities
        if item.get("step_id") == "derive_curve_point_D_ii"
    )
    assert authority["authority_details"]["observed_unknown_args"] == [
        "point"
    ]
    assert authority["authority_details"][
        "observed_missing_required_args"
    ] == ["parabola"]


def test_unique_visible_dynamic_source_ref_becomes_exact_step_result(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v3_fixture_payload(case)
    _step(payload, "derive_translated_D_i")["args"]["source"] = "C"

    result, _fixture = _execute(tmp_path, case, payload)
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None
    assert reconciliation.ok
    assert result.authority_report.ok
    assert result.authoring_authority is not None
    assert result.checkpoint is not None
    assert result.checkpoint.all_required_goals_verified is True
    canonical = result.canonical_plan
    assert canonical is not None
    assert _step(canonical.to_payload(), "derive_translated_D_i")["args"][
        "source"
    ] == "C"
    _assert_named_entity_pin(
        result.authority,
        consumer_call_id="derive_translated_D_i",
        arg_name="source",
        semantic_ref="C",
        producer_call_id="derive_y_intercept_C_i",
        return_name="point",
    )


def test_answer_target_source_ref_uses_prior_scope_owned_answer_result(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    _step(payload, "derive_square_vertex_G_i")["args"]["side_start"] = "A"

    result, _fixture = _execute(tmp_path, case, payload)

    assert result.authority_report.ok
    assert result.checkpoint is not None
    assert result.checkpoint.all_required_goals_verified is True
    canonical = result.canonical_plan
    assert canonical is not None
    assert _step(canonical.to_payload(), "derive_square_vertex_G_i")["args"][
        "side_start"
    ] == "A"
    _assert_named_entity_pin(
        result.authority,
        consumer_call_id="derive_square_vertex_G_i",
        arg_name="side_start",
        semantic_ref="A",
        producer_call_id="derive_x_intercept_A_i",
        return_name="point",
    )


def test_latest_parameter_state_closes_transitive_point_without_llm_wiring(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    goal = _scope(payload["root_scope"], "ii")["goals"][0]
    goal["steps"] = [
        step
        for step in goal["steps"]
        if step["step_id"] != "evaluate_point_A_ii"
    ]
    solve_c = next(
        step
        for step in goal["steps"]
        if step["step_id"] == "solve_parameter_c_ii"
    )
    goal["steps"] = [
        step for step in goal["steps"] if step is not solve_c
    ]
    goal["steps"].append(solve_c)
    recover = _step(payload, "recover_target_point_E_ii")
    recover["args"]["side_start"] = "A"
    recover["args"].pop("parameter_value", None)
    derive_g = _step(payload, "derive_minimum_point_G_ii")
    derive_g["args"].pop("parameter_value", None)

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    report = result.replay.transactional_attempt_result.execution_report
    runtime_order = [item.call_id for item in report.call_states]
    assert runtime_order.index("solve_parameter_c_ii") < runtime_order.index(
        "derive_minimum_point_G_ii"
    )
    assert runtime_order.index("solve_parameter_c_ii") < runtime_order.index(
        "recover_target_point_E_ii"
    )
    solved_c = report.runtime_result_values[
        ("solve_parameter_c_ii", "parameter_value")
    ]
    recovered_e = report.runtime_result_values[
        ("recover_target_point_E_ii", "point")
    ]
    assert sp.simplify(solved_c.value - 5) == 0
    assert tuple(sp.simplify(item) for item in recovered_e.value) == (
        sp.Integer(-2),
        sp.Rational(3, 2),
    )
    c_versions = {
        item.version_id
        for item in report.committed_versions
        if (
            item.version_id.slot_id.logical_key.runtime_type
            == "ParameterValue"
            and item.version_id.slot_id.logical_key.object_id.value
            == "symbol:problem:c"
        )
    }
    recover_write = next(
        write
        for call_result in report.call_results
        if call_result.call_id == "recover_target_point_E_ii"
        for write in call_result.state_writes
        if write.return_name == "adjacent_vertex"
    )
    assert c_versions
    assert c_versions <= set(recover_write.source_version_ids)
    derive_g_write = next(
        write
        for call_result in report.call_results
        if call_result.call_id == "derive_minimum_point_G_ii"
        for write in call_result.state_writes
        if write.return_name == "point"
    )
    assert c_versions <= set(derive_g_write.source_version_ids)


def test_identity_contract_drives_named_entity_latest_state_dependency(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    derive_g = _step(payload, "derive_minimum_point_G_ii")
    derive_g.pop("return_bindings")

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    authority = result.authority
    assert authority is not None
    lowered_g = next(
        call
        for call in authority.lowered_plan.calls
        if call.call_id == "derive_minimum_point_G_ii"
    )
    assert lowered_g.return_bindings["point"].ref == "G"
    _assert_named_entity_pin(
        authority,
        consumer_call_id="recover_target_point_E_ii",
        arg_name="side_end",
        semantic_ref="G",
        producer_call_id="derive_minimum_point_G_ii",
        return_name="point",
    )
    reconciliation = result.replay.functional_reconciliation
    assert "derive_minimum_point_G_ii" in reconciliation.dependency_graph[
        "recover_target_point_E_ii"
    ]
    runtime_values = (
        result.replay.transactional_attempt_result.execution_report
        .runtime_result_values
    )
    recovered_e = runtime_values[
        ("recover_target_point_E_ii", "point")
    ]
    assert tuple(sp.simplify(item) for item in recovered_e.value) == (
        sp.Integer(-2),
        sp.Rational(3, 2),
    )


def test_existing_object_answer_promotion_never_crosses_sibling_scope(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path / "heping-ermo",
        case="tj-2026-heping-ermo-25",
    )
    semantic_items = fixture[7].semantic_read_items()
    entity_e = next(
        item
        for item in semantic_items
        if item.kind == "point" and item.ref == "E"
    )

    assert _unique_answer_for_object_binding(
        entity_e,
        return_type="Point",
        scope_id="i_2",
        question_goals=fixture[3].question_goals,
        semantic_items=semantic_items,
        handle_registry=fixture[5],
    ) is None
    answer = _unique_answer_for_object_binding(
        entity_e,
        return_type="Point",
        scope_id="ii",
        question_goals=fixture[3].question_goals,
        semantic_items=semantic_items,
        handle_registry=fixture[5],
    )
    assert answer is not None
    assert answer.ref == "ii.E"


def test_duplicate_a_writer_is_removed_only_after_runtime_equivalence(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    goal = _scope(payload["root_scope"], "ii")["goals"][0]
    source = deepcopy(_step(payload, "evaluate_point_A_ii"))
    source["step_id"] = "evaluate_point_A_ii_duplicate"
    source_index = next(
        index
        for index, step in enumerate(goal["steps"])
        if step["step_id"] == "evaluate_point_A_ii"
    )
    goal["steps"].insert(source_index + 1, source)
    _step(payload, "recover_target_point_E_ii")["args"]["side_start"] = "A"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    aliases = {
        item.duplicate_call_id: item.canonical_call_id
        for item in result.runtime_equivalent_aliases
    }
    assert aliases["evaluate_point_A_ii_duplicate"] == "evaluate_point_A_ii"
    report = result.replay.transactional_attempt_result.execution_report
    assert not any(
        item.producer_call_id == "evaluate_point_A_ii_duplicate"
        for item in report.committed_versions
    )


def test_runtime_equivalent_version_alias_is_canonical_for_later_writer(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    goal = _scope(payload["root_scope"], "ii")["goals"][0]
    source = deepcopy(_step(payload, "evaluate_point_A_ii"))
    first_duplicate = deepcopy(source)
    first_duplicate["step_id"] = "evaluate_point_A_ii_duplicate_1"
    second_duplicate = deepcopy(source)
    second_duplicate["step_id"] = "evaluate_point_A_ii_duplicate_2"
    source_index = next(
        index
        for index, step in enumerate(goal["steps"])
        if step["step_id"] == "evaluate_point_A_ii"
    )
    goal["steps"][source_index + 1 : source_index + 1] = [
        first_duplicate,
        second_duplicate,
    ]
    _step(payload, "recover_target_point_E_ii")["args"]["side_start"] = "A"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    report = result.replay.transactional_attempt_result.execution_report
    assert not any(
        mismatch.code == "planner.contract_runtime_destination_drift"
        for mismatch in report.compatibility_mismatches
    )
    assert {
        item.duplicate_call_id for item in result.runtime_equivalent_aliases
    } >= {
        "evaluate_point_A_ii_duplicate_1",
        "evaluate_point_A_ii_duplicate_2",
    }


def test_recomputed_source_a_is_reused_only_after_runtime_equivalence(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    ii_goal = _scope(payload["root_scope"], "ii")["goals"][0]
    evaluate = _step(payload, "evaluate_point_A_ii")
    evaluate["capability_id"] = "quadratic_x_axis_intercept_point"
    evaluate["args"] = {"parabola": "parabola"}
    evaluate["return_bindings"] = {
        "point": {"kind": "existing", "ref": "A"}
    }
    _step(payload, "recover_target_point_E_ii")["args"]["side_start"] = "A"
    evaluate_index = next(
        index
        for index, step in enumerate(ii_goal["steps"])
        if step["step_id"] == "evaluate_point_A_ii"
    )
    evaluate = ii_goal["steps"].pop(evaluate_index)
    path_reduction_index = next(
        index
        for index, step in enumerate(ii_goal["steps"])
        if step["step_id"] == "reduce_square_path_ii"
    )
    ii_goal["steps"].insert(path_reduction_index, evaluate)

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    assert result.canonical_plan is not None
    assert "evaluate_point_A_ii" not in {
        item.step_id for item in result.canonical_plan.steps
    }
    assert any(
        item.duplicate_call_id == "evaluate_point_A_ii"
        and item.canonical_call_id == "evaluate_point_A_ii"
        for item in result.runtime_equivalent_aliases
    )
    report = result.replay.transactional_attempt_result.execution_report
    assert not any(
        item.call_id == "evaluate_point_A_ii"
        for item in report.call_results
    )
    path_minimum = next(
        item
        for item in report.call_results
        if item.call_id == "derive_path_minimum_ii"
    )
    assert path_minimum.status == "verified"
    assert not any(
        item.producer_call_id == "evaluate_point_A_ii"
        and item.version_id.slot_id.logical_key.object_id.value
        == "point:problem:A"
        for item in report.committed_versions
    )


def test_scope_owned_recomputed_source_state_is_removed_before_checkpoint(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    ii_scope = _scope(payload["root_scope"], "ii")
    ii_goal = ii_scope["goals"][0]
    establish = _step(payload, "derive_parametric_parabola_ii")
    evaluate = _step(payload, "evaluate_point_A_ii")
    evaluate["step_id"] = "derive_A_ii"
    evaluate["capability_id"] = "quadratic_x_axis_intercept_point"
    evaluate["args"] = {"parabola": "parabola"}
    evaluate["return_bindings"] = {
        "point": {"kind": "existing", "ref": "A"}
    }
    _step(payload, "recover_target_point_E_ii")["args"]["side_start"] = "A"
    ii_goal["steps"] = [
        item
        for item in ii_goal["steps"]
        if item["step_id"]
        not in {
            "derive_parametric_parabola_ii",
            "evaluate_point_A_ii",
            "derive_A_ii",
        }
    ]
    ii_scope["steps"] = [establish, evaluate]

    result, _fixture = _execute(tmp_path, case, payload)

    assert result.checkpoint is not None
    assert result.checkpoint.all_required_goals_verified is True
    assert result.canonical_plan is not None
    canonical_step_ids = {
        item.step_id for item in result.canonical_plan.steps
    }
    assert "derive_parametric_parabola_ii" in canonical_step_ids
    assert "derive_A_ii" not in canonical_step_ids
    assert "derive_A_ii" not in _checkpoint_steps(
        result.checkpoint
    )
    assert any(
        item.duplicate_call_id == "derive_A_ii"
        and item.canonical_call_id == "derive_A_ii"
        for item in result.runtime_equivalent_aliases
    )
    report = result.replay.transactional_attempt_result.execution_report
    assert not any(
        item.producer_call_id == "derive_A_ii"
        for item in report.committed_versions
    )


def test_conflicting_duplicate_a_writer_fails_without_ghost_version(
    tmp_path,
    monkeypatch,
) -> None:
    from shuxueshuo_server.solver.contracts import TypedValue
    from shuxueshuo_server.solver.runtime.methods.evaluate_point_at_parameter import (
        EvaluatePointAtParameterMethod,
    )

    original_run = EvaluatePointAtParameterMethod.run
    evaluations = 0

    def divergent_second_evaluation(self, inputs, kernel):
        nonlocal evaluations
        result = original_run(self, inputs, kernel)
        evaluations += 1
        if evaluations != 2:
            return result
        point = result.outputs["evaluated_point"]
        return replace(
            result,
            outputs={
                **result.outputs,
                "evaluated_point": TypedValue(
                    "Point",
                    (point.value[0] + 1, point.value[1]),
                    source="test_conflicting_a_writer",
                ),
            },
        )

    monkeypatch.setattr(
        EvaluatePointAtParameterMethod,
        "run",
        divergent_second_evaluation,
    )
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    goal = _scope(payload["root_scope"], "ii")["goals"][0]
    source = deepcopy(_step(payload, "evaluate_point_A_ii"))
    source["step_id"] = "evaluate_point_A_ii_duplicate"
    source_index = next(
        index
        for index, step in enumerate(goal["steps"])
        if step["step_id"] == "evaluate_point_A_ii"
    )
    goal["steps"].insert(source_index + 1, source)
    _step(payload, "recover_target_point_E_ii")["args"]["side_start"] = "A"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.blocked_stage == "runtime"
    transaction = result.replay.transactional_attempt_result
    assert {
        item.code for item in transaction.root_issues
    } >= {"planner.runtime_state_equivalence_conflict"}
    assert result.replay.retry_state is not None
    assert result.replay.retry_state.functional_retry_graph_checkpoint is None
    assert result.replay.planner_state_context is not None
    retry_memory = result.replay.planner_state_context.state.retry_memory
    assert retry_memory.functional_retry_graph_checkpoint is None
    assert not any(
        item.producer_call_id == "evaluate_point_A_ii_duplicate"
        for item in transaction.execution_report.committed_versions
    )


def test_closed_point_role_reuse_is_runtime_checked_before_transition_commit(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v3_fixture_payload(case)
    auxiliary = _step(payload, "derive_axis_intercept_F_i")
    auxiliary["return_bindings"] = {
        "point": {"kind": "existing", "ref": "E"}
    }
    final = _step(payload, "derive_curve_intersection_E_i")
    final["args"]["line_p1"] = "E"
    final["args"]["line_p2"] = "B"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.blocked_stage == "runtime"
    transaction = result.replay.transactional_attempt_result
    assert {
        item.code for item in transaction.root_issues
    } >= {"planner.runtime_state_equivalence_conflict"}
    assert not {
        "planner.method_input_view_authority_missing",
        "planner.method_input_view_authority_drift",
    } & {item.code for item in transaction.root_issues}
    assert not any(
        item.producer_call_id == "derive_curve_intersection_E_i"
        for item in transaction.execution_report.committed_versions
    )


def test_identity_mismatch_checkpoint_exposes_public_expected_and_actual_refs(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v3_fixture_payload(case)
    _step(payload, "derive_locus_G_ii")["args"]["point"] = "E"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    failed = _checkpoint_steps(checkpoint)["derive_path_minimum_ii"]
    assert failed.status == "authority_invalid"
    assert failed.typed_issue is not None
    issue = failed.typed_issue
    assert issue["step_id"] == "derive_path_minimum_ii"
    assert issue["observed"]["actual_object_refs"] == ["E"]
    assert issue["expected"]["expected_object_refs"] == ["G"]
    assert issue["expected"]["relation"] == "same_object"
    assert issue["expected"]["requirement"]
    assert issue["repair_call_ids"]
    # The invalid step is rejected before execution; independent valid prefixes
    # still use the normal provisional transaction.
    assert checkpoint.transaction_attempted is True
    assert checkpoint.blocked_stage == "reconciliation_binding"
    assert "derive_path_minimum_ii" not in {
        str(item.get("call_id") or "")
        for item in checkpoint.restore_state.call_results
    }
    prompt = json.dumps(checkpoint.to_prompt_payload(), ensure_ascii=False)
    assert "point:problem:E" not in prompt
    assert "point:problem:G" not in prompt


def test_unique_prior_same_object_result_is_canonicalized_in_goal_scope(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v3_fixture_payload(case)
    _step(payload, "derive_weighted_minimum_iii")["args"][
        "curve_point"
    ] = "M"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    _assert_named_entity_pin(
        result.authority,
        consumer_call_id="derive_weighted_minimum_iii",
        arg_name="curve_point",
        semantic_ref="M",
        producer_call_id="derive_curve_point_iii",
        return_name="point",
    )


def test_visible_same_object_result_is_rewritten_only_after_runtime_equivalence(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v3_fixture_payload(case)
    goal = _scope(payload["root_scope"], "iii")["goals"][0]
    producer = deepcopy(_step(payload, "derive_curve_point_iii"))
    producer["step_id"] = "derive_curve_point_iii_alternate"
    consumer_index = next(
        index
        for index, item in enumerate(goal["steps"])
        if item["step_id"] == "derive_weighted_minimum_iii"
    )
    goal["steps"].insert(consumer_index, producer)
    _step(payload, "derive_weighted_minimum_iii")["args"][
        "curve_point"
    ] = "M"

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.all_required_goals_verified is True
    aliases = {
        item.duplicate_call_id: item.canonical_call_id
        for item in result.runtime_equivalent_aliases
    }
    assert aliases["derive_curve_point_iii_alternate"] == (
        "derive_curve_point_iii"
    )
    canonical = result.canonical_plan
    assert canonical is not None
    assert "derive_curve_point_iii_alternate" not in {
        item.step_id for item in canonical.steps
    }
    assert _step(canonical.to_payload(), "derive_weighted_minimum_iii")["args"][
        "curve_point"
    ] == "M"


def test_materialized_macro_dependencies_normalize_equivalent_local_writers(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = _duplicate_descendant_point_plan_payload()

    result, _fixture = _execute(tmp_path, case, payload)

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.blocked_stage is None
    assert checkpoint.all_required_goals_verified is True
    aliases = {
        item.duplicate_call_id: item.canonical_call_id
        for item in result.runtime_equivalent_aliases
    }
    assert aliases == {
        "locate_C": "derive_y_intercept_C_i",
        "locate_D": "derive_translated_D_i",
    }
    canonical = result.canonical_plan
    assert canonical is not None
    assert {"locate_C", "locate_D"}.isdisjoint(
        item.step_id for item in canonical.steps
    )
    checkpoint_steps = _checkpoint_steps(checkpoint)
    assert {"locate_C", "locate_D"}.isdisjoint(checkpoint_steps)
    assert checkpoint.macro_expansions
    assert all(
        origin.generated_step_id in checkpoint_steps
        for origin in checkpoint.macro_expansions[0].generated_step_origins
    )
    final_report = result.replay.transactional_attempt_result.execution_report
    assert final_report.runtime_equivalent_aliases == ()
    assert {"locate_C", "locate_D"}.isdisjoint(
        item.call_id for item in final_report.call_results
    )
    assert not any(
        write.step_id in {"locate_C", "locate_D"}
        for call_result in final_report.call_results
        for write in call_result.state_writes
    )


def test_materialized_macro_reuses_verified_prefix_before_local_writer_failure(
    tmp_path,
    monkeypatch,
) -> None:
    from shuxueshuo_server.solver.contracts import TypedValue
    from shuxueshuo_server.solver.runtime.methods.quadratic_y_axis_intercept_point import (
        QuadraticYAxisInterceptPointMethod,
    )

    original_run = QuadraticYAxisInterceptPointMethod.run
    intercept_calls = 0

    def divergent_second_intercept(self, inputs, kernel):
        nonlocal intercept_calls
        result = original_run(self, inputs, kernel)
        if inputs["target"].name != "C":
            return result
        intercept_calls += 1
        if intercept_calls != 2:
            return result
        point = result.outputs["point"]
        return replace(
            result,
            outputs={
                **result.outputs,
                "point": TypedValue(
                    "Point",
                    (point.value[0], point.value[1] + 1),
                    source="test_divergent_runtime_probe",
                ),
            },
        )

    monkeypatch.setattr(
        QuadraticYAxisInterceptPointMethod,
        "run",
        divergent_second_intercept,
    )
    case = "tj-2026-heping-yimo-25"
    result, _fixture = _execute(
        tmp_path,
        case,
        _duplicate_descendant_point_plan_payload(),
    )

    checkpoint = result.checkpoint
    assert checkpoint is not None
    assert checkpoint.blocked_stage == "runtime"
    assert checkpoint.all_required_goals_verified is False
    assert result.runtime_equivalent_aliases == ()
    canonical = result.canonical_plan
    assert canonical is not None
    assert "locate_C" in {item.step_id for item in canonical.steps}
    # The ancestor producer ran before Macro materialization and is restored;
    # only the distinct local writer executes in the clean ordinary Plan.
    assert intercept_calls == 2
    checkpoint_steps = _checkpoint_steps(checkpoint)
    assert checkpoint_steps["locate_C"].status == "runtime_failed"
    assert any(
        item.status == "blocked_by_dependency"
        for step_id, item in checkpoint_steps.items()
        if step_id in checkpoint.macro_expansions[0].generated_step_ids
    )
    report = result.replay.transactional_attempt_result.execution_report
    assert sum(
        item.call_id == "derive_y_intercept_C_i"
        for item in report.call_results
    ) == 1
    assert next(
        item for item in report.call_results if item.call_id == "locate_C"
    ).status == "failed"


def test_dead_pure_step_stays_in_authored_plan_but_not_effective_plan(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v3_fixture_payload(case)
    goal = _scope(payload["root_scope"], "i_2")["goals"][0]
    goal.setdefault("steps", []).append(
        {
            "step_id": "dead_vertex",
            "capability_id": "quadratic_vertex_point",
            "args": {"parabola": "parabola"},
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
        load_v3_fixture_payload(case),
    )
    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None and reconciliation.ok
    assert reconciliation.call_aliases == {}
    assert result.authority is not None
    assert all(
        item.step_id == item.canonical_call_id
        for item in result.authority.step_authorities.values()
    )


def _duplicate_descendant_point_plan_payload():
    payload = load_v3_fixture_payload("tj-2026-heping-yimo-25")
    goal = _scope(payload["root_scope"], "ii")["goals"][0]
    goal["steps"] = [
        {
            "step_id": "locate_C",
            "capability_id": "quadratic_y_axis_intercept_point",
            "args": {"quadratic": "parabola"},
            "return_bindings": {
                "point": {"kind": "existing", "ref": "C"}
            },
            "return_expectations": {"point": "closed_state"},
        },
        {
            "step_id": "locate_D",
            "capability_id": "translated_point",
            "args": {"source": "C"},
            "return_bindings": {
                "point": {"kind": "existing", "ref": "D"}
            },
            "return_expectations": {"point": "closed_state"},
        },
        *goal["steps"],
    ]
    return payload


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


def _assert_named_entity_pin(
    authority,
    *,
    consumer_call_id,
    arg_name,
    semantic_ref,
    producer_call_id,
    return_name,
):
    lowered = next(
        item
        for item in authority.lowered_plan.calls
        if item.call_id == consumer_call_id
    )
    assert lowered.args[arg_name][0].ref == semantic_ref
    pin = authority.lowered_plan.typed_input_source_pins[
        (consumer_call_id, arg_name, 0)
    ]
    assert pin.semantic_ref == semantic_ref
    assert pin.producer_call_id == producer_call_id
    assert pin.return_name == return_name


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
