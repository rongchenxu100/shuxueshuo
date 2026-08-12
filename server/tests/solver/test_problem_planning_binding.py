from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
)
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalogBuilder,
    ProblemPlanningBindingError,
    build_functional_problem_binding_context,
    functional_problem_binding_context_schema,
    problem_planning_binding_catalog_schema,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    parameter_substitution_pairs_from_reads,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalTransactionalInterpreter,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayService,
)
from shuxueshuo_server.solver.runtime.state_identity import StateVersionId
from shuxueshuo_server.solver.runtime.strategy_models import (
    FunctionalCompileStep,
    ProjectedStateDependency,
    ProjectedStateWrite,
)

from _problem_planning_support import (
    CASES,
    SCOPE_NATIVE_FIXTURES,
    planning_binding_fixture,
    scope_native_reconciliation_fixture,
)


ROOT = Path(__file__).resolve().parents[3]


def _xiqing_parameter_evaluation_payload(*, parameter_ref: str = "b") -> dict:
    case = "tj-2026-xiqing-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    first_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "i"
    )
    first_scope["calls"] = [
        {
            "call_id": "build_open_parabola_i",
            "capability_id": "quadratic_from_constraints",
            "args": {
                "curve_point": {"kind": "point", "ref": "A"},
                "free_parameters": {"kind": "symbol", "ref": "b"},
            },
            "return_bindings": {},
            "strategy": "建立保留参数 b 的抛物线。",
            "reason": "先保留题面动态参数。",
        },
        {
            "call_id": "evaluate_parabola_i",
            "capability_id": "evaluate_expression_at_parameter",
            "args": {
                "expression": {
                    "from_call": "build_open_parabola_i",
                    "return": "parabola",
                },
                "parameter": {"kind": "symbol", "ref": parameter_ref},
                "parameter_value": {
                    "kind": "fact",
                    "ref": "symbol_value_b",
                },
            },
            "return_bindings": {},
            "strategy": "代入本问给定的参数值。",
            "reason": "闭合抛物线状态。",
        },
        {
            "call_id": "derive_vertex_i",
            "capability_id": "quadratic_vertex_point",
            "args": {
                "parabola": {
                    "from_call": "evaluate_parabola_i",
                    "return": "evaluated_parabola",
                }
            },
            "return_bindings": {
                "point": {"kind": "answer", "ref": "i.vertex"}
            },
            "strategy": "求闭合抛物线的顶点。",
            "reason": "回答第一问。",
        },
    ]
    return payload


@pytest.mark.parametrize("case", CASES)
def test_five_planning_contexts_bind_every_authority_to_typed_context(
    tmp_path,
    case,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        catalog,
    ) = planning_binding_fixture(tmp_path / case, case=case)

    assert set(catalog.bindings) == set(planning_context.ref_authorities)
    assert catalog.planner_state_context_id == (
        planner_context.manifest.context_id
    )
    assert catalog.binding_signature
    assert all(binding.typed_sources for binding in catalog.bindings.values())
    assert all(
        source.math_object_id is not None
        for binding in catalog.bindings.values()
        if binding.usage == "answer"
        for source in binding.typed_sources
    )


def test_binding_wire_schema_snapshots_validate_five_cases(tmp_path) -> None:
    catalog_schema = problem_planning_binding_catalog_schema()
    sidecar_schema = functional_problem_binding_context_schema()
    checked_catalog_schema = json.loads(
        (
            ROOT
            / "internal/schemas/problem-planning-binding-catalog.schema.json"
        ).read_text(encoding="utf-8")
    )
    checked_sidecar_schema = json.loads(
        (
            ROOT
            / "internal/schemas/functional-problem-binding-context.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(catalog_schema)
    Draft202012Validator.check_schema(sidecar_schema)
    assert checked_catalog_schema == catalog_schema
    assert checked_sidecar_schema == sidecar_schema

    catalog_validator = Draft202012Validator(catalog_schema)
    sidecar_validator = Draft202012Validator(sidecar_schema)
    for case in CASES:
        *_, catalog, _plan, _validation, reconciliation = (
            scope_native_reconciliation_fixture(
                tmp_path / case,
                case=case,
            )
        )
        sidecar = reconciliation.functional_problem_binding_context
        assert sidecar is not None
        assert list(
            catalog_validator.iter_errors(catalog.authority_payload())
        ) == []
        assert list(sidecar_validator.iter_errors(sidecar.to_payload())) == []


def test_scope_local_symbol_values_share_object_but_not_state_version(
    tmp_path,
) -> None:
    *_, catalog = planning_binding_fixture(
        tmp_path,
        case="tj-2026-hexi-yimo-25",
    )
    values = [
        catalog.bindings[ref].typed_sources[0]
        for ref in (
            "i.symbol_value_a",
            "ii.symbol_value_a",
            "iii.symbol_value_a",
        )
    ]

    assert len({item.math_object_id for item in values}) == 1
    assert len({item.state_version_id for item in values}) == 3
    assert {
        item.state_version_id.slot_id.storage_scope_id
        for item in values
        if item.state_version_id is not None
    } == {"i", "ii", "iii"}


def test_same_scope_symbol_values_do_not_overwrite_each_other(tmp_path) -> None:
    *_, planner_context, catalog = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )
    state_handles = {
        slot.canonical_handle for slot in planner_context.state.state_slots
    }

    assert catalog.bindings["symbol_value_a"].runtime_node_id in state_handles
    assert catalog.bindings["symbol_value_c"].runtime_node_id in state_handles
    assert (
        catalog.bindings["symbol_value_a"].typed_sources[0].math_object_id
        != catalog.bindings["symbol_value_c"].typed_sources[0].math_object_id
    )


def test_bundle_revision_drift_fails_loud(tmp_path) -> None:
    (
        bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        registry,
        planner_context,
        _catalog,
    ) = planning_binding_fixture(tmp_path)
    drifted = replace(
        planner_context,
        manifest=replace(
            planner_context.manifest,
            problem_id="different-problem",
        ),
    )

    with pytest.raises(
        ProblemPlanningBindingError,
        match="planner.problem_source_binding_drift",
    ):
        ProblemPlanningBindingCatalogBuilder().build(
            bundle,
            planning_context,
            drifted,
            registry,
        )


def test_catalog_builder_does_not_use_global_semantic_catalog(
    tmp_path,
    monkeypatch,
) -> None:
    (
        bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        registry,
        planner_context,
        _catalog,
    ) = planning_binding_fixture(tmp_path)

    monkeypatch.setattr(
        PlannerStateContext,
        "semantic_read_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("global semantic catalog must not be used")
        ),
    )

    rebuilt = ProblemPlanningBindingCatalogBuilder().build(
        bundle,
        planning_context,
        planner_context,
        registry,
    )

    assert rebuilt.binding_signature


@pytest.mark.parametrize("case", CASES)
def test_scope_native_recorded_plan_reconciles_compiles_and_executes(
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
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path / case, case=case)

    assert validation.ok
    assert reconciliation.ok, reconciliation.to_payload()
    assert reconciliation.functional_problem_binding_context is not None
    assert set(
        reconciliation.functional_problem_binding_context.call_goal_bindings
    ) == {call.call_id for call in reconciliation.calls}
    assert all(
        goal_ids
        for goal_ids in reconciliation.functional_problem_binding_context
        .call_goal_bindings.values()
    )
    assert catalog.binding_signature

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

    assert attempt.compiled_output is not None, [
        (issue.code, issue.message) for issue in attempt.root_issues
    ]
    assert not attempt.root_issues
    assert all(goal.status == "passed" for goal in attempt.goal_report.goals)
    assert attempt.execution_report.functional_compile_count > 0


def test_recorded_replay_explicitly_consumes_problem_binding_catalog(
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
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )

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

    assert replay.output is not None, replay.errors
    assert replay.functional_reconciliation is not None
    assert replay.functional_reconciliation.functional_problem_binding_context
    assert replay.transactional_attempt_result is not None
    assert not replay.transactional_attempt_result.root_issues


def test_state_fact_binds_exact_source_snapshot_and_sidecar_provenance(
    tmp_path,
) -> None:
    (
        _bundle,
        _planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        planner_context,
        catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    coordinate = catalog.bindings["point_coordinate_a"].typed_sources[0]
    sidecar = reconciliation.functional_problem_binding_context.input_binding_for(
        "derive_parametric_parabola_ii",
        "curve_point",
        0,
    )

    assert coordinate.state_version_id is not None
    assert coordinate.state_version_id.ordinal == 0
    assert coordinate.state_version_id.slot_id.storage_scope_id == "ii"
    assert sidecar is not None
    assert sidecar.selection_policy == "exact"
    assert sidecar.typed_source.state_version_id == coordinate.state_version_id
    assert "entity:problem:A" in sidecar.source_unit_ids
    coordinate_slot = next(
        slot
        for slot in planner_context.state.state_slots
        if slot.latest_version_id == coordinate.state_version_id
    )
    assert coordinate_slot.runtime_path == "$question.ii.points.A"


def test_parameter_value_compiles_from_exact_problem_source_identity(
    tmp_path,
) -> None:
    case = "tj-2026-xiqing-yimo-25"
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
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=_xiqing_parameter_evaluation_payload(),
    )

    assert reconciliation.ok, reconciliation.to_payload()
    dependency = next(
        item
        for item in reconciliation.state_dependencies
        if item.step_id == "evaluate_parabola_i"
        and item.arg_name == "parameter_value"
    )
    assert dependency.state_version_id is not None
    assert dependency.state_version_id.ordinal == 0
    assert dependency.object_ref == "symbol:problem:b"

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

    assert attempt.compiled_output is not None, [
        (issue.code, issue.message) for issue in attempt.root_issues
    ]
    invocation = next(
        invocation
        for step in attempt.compiled_output.step_plans
        if step.step_id == "evaluate_parabola_i"
        for invocation in step.invocations
        if invocation.method_id == "evaluate_expression_at_parameter"
    )
    assert invocation.inputs["parameter"].endswith(".symbols.b")
    assert "parameter_values.b" in invocation.inputs["parameter_value"]


def test_parameter_value_rejects_an_explicit_different_symbol(tmp_path) -> None:
    case = "tj-2026-xiqing-yimo-25"
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
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=_xiqing_parameter_evaluation_payload(parameter_ref="c"),
    )

    assert reconciliation.ok, reconciliation.to_payload()
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
    assert any(
        "function.parameter_value_object_mismatch" in issue.message
        for issue in attempt.root_issues
    )


def test_call_result_parameter_value_keeps_its_symbol_object_identity(
    tmp_path,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        _problem_payload,
        registry,
        _planner_context,
        catalog,
    ) = planning_binding_fixture(
        tmp_path,
        case="tj-2026-xiqing-yimo-25",
    )
    object_id = catalog.bindings["b"].typed_sources[0].math_object_id
    assert object_id is not None
    dynamic_handle = "fact:i:dynamic_b_value"
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=inputs.question_goals,
        functional_consumer_identity_mode="authoritative",
        problem_binding_authority=True,
    )
    index.register(
        dynamic_handle,
        "$step.solve_b.parameter_value",
        "ParameterValue",
        source="step:solve_b",
    )
    index.register_projected_state_writes(
        (
            ProjectedStateWrite(
                step_id="solve_b",
                produced_handle=dynamic_handle,
                state_slot_id="symbol:problem:b.value@i:ParameterValue",
                write_mode="value",
                runtime_type="ParameterValue",
                object_ref=object_id.value,
                return_name="parameter_value",
                math_object_id=object_id,
            ),
        ),
        dependencies=(
            ProjectedStateDependency(
                step_id="consume_b",
                state_slot_id="symbol:problem:b.value@i:ParameterValue",
                produced_handle=dynamic_handle,
                runtime_type="ParameterValue",
                object_ref=object_id.value,
                arg_name="parameter_value",
                source="wire",
                source_step_id="solve_b",
                source_return_name="parameter_value",
            ),
        ),
    )
    step = FunctionalCompileStep(
        scope_id="i",
        step_id="consume_b",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="",
        target="",
        strategy="",
        reads=(dynamic_handle,),
    )

    pairs = parameter_substitution_pairs_from_reads(step, index)

    assert pairs == (
        (
            index.bindings[object_id.value].path,
            "$step.solve_b.parameter_value",
        ),
    )


def test_parameter_value_from_sibling_scope_is_not_visible(tmp_path) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    first_call = next(
        call
        for scope in payload["scopes"]
        if scope["scope_id"] == "i"
        for call in scope["calls"]
    )
    first_call["args"]["known_coefficients"] = {
        "kind": "fact",
        "ref": "ii.symbol_value_a",
    }

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.semantic_ref_not_visible_for_goal"
        and issue.call_id == first_call["call_id"]
        for issue in reconciliation.issues
    )


def test_catalog_rebuild_rejects_evolved_source_state(tmp_path) -> None:
    (
        bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        registry,
        planner_context,
        catalog,
    ) = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    source = catalog.bindings["point_coordinate_a"].typed_sources[0]
    assert source.state_version_id is not None
    slot = next(
        item
        for item in planner_context.state.state_slots
        if item.typed_slot_id == source.state_version_id.slot_id
    )
    evolved_slot = replace(
        slot,
        latest_version_id=StateVersionId(slot.typed_slot_id, 1),
    )
    evolved_context = replace(
        planner_context,
        state=replace(
            planner_context.state,
            state_slots=tuple(
                evolved_slot if item.slot_id == slot.slot_id else item
                for item in planner_context.state.state_slots
            ),
        ),
    )

    with pytest.raises(
        ProblemPlanningBindingError,
        match="planner.problem_source_binding_drift",
    ):
        ProblemPlanningBindingCatalogBuilder().build(
            bundle,
            planning_context,
            evolved_context,
            registry,
        )


def test_answer_authority_cannot_be_used_as_call_input(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_parametric_parabola_ii"
    )
    call["args"]["curve_point"] = {"ref": "ii.E", "kind": "answer"}

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.semantic_ref_not_visible_for_goal"
        and issue.call_id == "derive_parametric_parabola_ii"
        for issue in reconciliation.issues
    )


def test_goal_answer_name_used_as_identity_input_recovers_source_target(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    calls = {
        call["call_id"]: call
        for scope in payload["scopes"]
        for call in scope["calls"]
    }
    calls["derive_right_angle_candidates_ii"]["args"]["target"] = {
        "ref": "ii.D",
        "kind": "point",
    }
    calls["select_curve_candidate_ii"]["args"]["target_point"] = {
        "ref": "ii.D",
        "kind": "point",
    }

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert reconciliation.ok, reconciliation.to_payload()
    effective_calls = {
        call.call_id: call
        for scope in reconciliation.plan.scopes
        for call in scope.calls
    }
    assert effective_calls["derive_right_angle_candidates_ii"].args[
        "target"
    ][0].ref == "D"
    assert effective_calls["select_curve_candidate_ii"].args[
        "target_point"
    ][0].ref == "D"
    assert reconciliation.elaboration is not None
    assert {
        repair["call_id"]
        for repair in reconciliation.elaboration["deterministic_repairs"]
        if repair["action"] == "replace_answer_ref_with_goal_target"
    } == {
        "derive_right_angle_candidates_ii",
        "select_curve_candidate_ii",
    }
    assert "derive_y_intercept_ii" in reconciliation.dependency_graph[
        "derive_right_angle_candidates_ii"
    ]


def test_goal_answer_target_recovery_does_not_cross_scope(tmp_path) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_right_angle_candidates_ii"
    )
    call["args"]["target"] = {"ref": "i.P", "kind": "point"}

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.semantic_ref_not_visible_for_goal"
        and issue.call_id == "derive_right_angle_candidates_ii"
        for issue in reconciliation.issues
    )


def test_square_path_hidden_endpoint_uses_consumer_scope_producer(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    sibling_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "i_1"
    )
    sibling_scope["calls"].append(
        {
            "call_id": "derive_axis_point_M_i",
            "capability_id": "quadratic_axis_x_intercept_point",
            "args": {
                "parabola": {
                    "from_call": "derive_parabola_i",
                    "return": "parabola",
                }
            },
            "return_bindings": {
                "axis_point": {"ref": "M", "kind": "point"}
            },
            "strategy": "构造当前分支的轴点。",
            "reason": "制造同对象的 sibling producer 以验证作用域选择。",
        }
    )

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    dependencies = reconciliation.dependency_graph["reduce_square_path_ii"]
    assert "derive_axis_point_M_ii" in dependencies
    assert "derive_axis_point_M_i" not in dependencies


def test_hidden_sibling_dependency_does_not_propagate_foreign_goal_authority(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    ii_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "ii"
    )
    ii_scope["calls"] = [
        call
        for call in ii_scope["calls"]
        if call["call_id"] != "derive_axis_point_M_ii"
    ]
    sibling_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "i_1"
    )
    sibling_scope["calls"].append(
        {
            "call_id": "derive_axis_point_M_i",
            "capability_id": "quadratic_axis_x_intercept_point",
            "args": {
                "parabola": {
                    "from_call": "derive_parabola_i",
                    "return": "parabola",
                }
            },
            "return_bindings": {
                "axis_point": {"ref": "M", "kind": "point"}
            },
            "strategy": "构造 sibling 分支的轴点。",
            "reason": "验证隐式状态依赖不能跨 sibling。",
        }
    )

    fixture = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )
    registry = fixture[5]
    reconciliation = fixture[-1]

    assert "i_1" not in registry.ancestor_scopes("ii")
    assert "derive_axis_point_M_i" in reconciliation.dependency_graph.get(
        "reduce_square_path_ii",
        (),
    )
    assert not any(
        issue.code == "functional.call_scope_not_visible_for_goal"
        and issue.call_id == "derive_axis_point_M_i"
        for issue in reconciliation.issues
    )


def test_square_path_hidden_endpoint_keeps_goal_authority_when_upstream_invalid(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    parabola_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    parabola_call["args"]["free_parameters"] = {
        "ref": "b",
        "kind": "symbol",
    }
    parabola_call["args"]["target_parameter"] = {
        "ref": "b",
        "kind": "symbol",
    }

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.arg_distinctness_violation"
        and issue.call_id == "derive_parametric_parabola_ii"
        for issue in reconciliation.issues
    )
    unexpected_goal_issues = [
        issue
        for issue in reconciliation.issues
        if issue.code == "functional.call_goal_unresolved"
        and issue.call_id in {"derive_axis_point_M_ii", "reduce_square_path_ii"}
    ]
    assert not unexpected_goal_issues, [
        (issue.code, issue.call_id, issue.details)
        for issue in unexpected_goal_issues
    ]


def test_dynamic_point_semantic_ref_binds_unique_prior_same_object_state(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    calls = {
        item["call_id"]: item
        for scope in payload["scopes"]
        for item in scope["calls"]
    }
    calls["ii_derive_parabola"]["args"]["curve_points"][1] = {
        "kind": "point",
        "ref": "N",
    }
    calls["ii_1_solve_m"]["args"]["p2"] = {
        "kind": "point",
        "ref": "N",
    }
    calls["ii_2_derive_G"]["args"]["line2_p2"] = {
        "kind": "point",
        "ref": "N",
    }

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
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert reconciliation.ok, [item.to_payload() for item in reconciliation.issues]
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    expected_keys = {
        ("ii_derive_parabola", "curve_points", 1),
        ("ii_1_solve_m", "p2", 0),
        ("ii_2_derive_G", "line2_p2", 0),
    }
    bindings = {
        (item.call_id, item.arg_name, item.item_index): item
        for item in sidecar.input_bindings
        if (item.call_id, item.arg_name, item.item_index) in expected_keys
    }
    assert set(bindings) == expected_keys
    for item in bindings.values():
        assert item.source_kind == "call_result"
        assert item.semantic_ref is not None
        assert item.semantic_ref.to_payload() == {"kind": "point", "ref": "N"}
        assert item.runtime_node_id is not None
        assert item.source_unit_ids == ()
        assert item.typed_source is not None
        assert item.typed_source.source_call_id == "ii_construct_N"
        assert item.typed_source.source_return_name == "selected_target_point"

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
    assert attempt.compiled_output is not None, [
        (issue.code, issue.message) for issue in attempt.root_issues
    ]
    assert not attempt.root_issues


def test_dynamic_point_semantic_ref_rejects_different_object_result(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    consumer = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "ii_1_solve_m"
    )
    consumer["args"]["p2"] = {"kind": "point", "ref": "N"}
    (
        _bundle,
        _planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        _planner_context,
        catalog,
        plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )
    binding_context = reconciliation.functional_binding_context
    target = binding_context.binding_for("ii_1_solve_m", "p2", 0)
    assert target is not None and target.source.kind == "call_result"
    drifted_target = replace(
        target,
        source=replace(
            target.source,
            source_call_id="ii_compute_F",
            source_return_name="midpoint",
        ),
    )
    drifted_context = replace(
        binding_context,
        bindings=tuple(
            drifted_target if item is target else item
            for item in binding_context.bindings
        ),
    )
    goal_bindings = catalog.bind_plan(
        plan,
        require_goal_reachable=True,
        additional_dependencies=reconciliation.dependency_graph,
    )

    with pytest.raises(
        ProblemPlanningBindingError,
        match="planner.problem_source_binding_drift",
    ):
        build_functional_problem_binding_context(
            catalog,
            plan,
            reconciliation.calls,
            drifted_context,
            goal_bindings=goal_bindings,
        )


def test_answer_authority_rejects_multiple_goal_source_units(tmp_path) -> None:
    (
        bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        registry,
        planner_context,
        _catalog,
    ) = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    first_goal, second_goal = planning_context.goal_views[:2]
    authority = planning_context.answer_authority_for_goal(
        first_goal.goal_unit_id
    )
    authorities = dict(planning_context.ref_authorities)
    authorities[authority.semantic_ref.ref] = replace(
        authority,
        source_unit_ids=(
            first_goal.goal_unit_id,
            second_goal.goal_unit_id,
        ),
    )
    drifted_context = replace(
        planning_context,
        ref_authorities=authorities,
    )

    with pytest.raises(
        ProblemPlanningBindingError,
        match="planner.problem_source_binding_drift",
    ):
        ProblemPlanningBindingCatalogBuilder().build(
            bundle,
            drifted_context,
            planner_context,
            registry,
        )


def test_same_type_membership_facts_keep_distinct_condition_identity(
    tmp_path,
) -> None:
    *_, catalog = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )
    e_membership = catalog.bindings["point_on_segment_e_dm"]
    g_membership = catalog.bindings["point_on_segment_g_mn"]

    assert e_membership.runtime_node_id != g_membership.runtime_node_id
    assert e_membership.typed_sources[0].condition_id != (
        g_membership.typed_sources[0].condition_id
    )


def test_sibling_private_ref_is_rejected_before_compile(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_square_vertex_G_i"
    )
    call["args"]["side_start"] = {"ref": "F", "kind": "point"}

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.semantic_ref_not_visible_for_goal"
        and issue.call_id == "derive_square_vertex_G_i"
        for issue in reconciliation.issues
    )


def test_cross_scope_answer_swap_is_rejected_before_compile(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    calls = {
        call["call_id"]: call
        for scope in payload["scopes"]
        for call in scope["calls"]
    }
    calls["derive_vertex_P_i"]["return_bindings"]["point"] = {
        "ref": "ii.E",
        "kind": "answer",
    }
    calls["recover_target_point_E_ii"]["return_bindings"]["point"] = {
        "ref": "i_1.P",
        "kind": "answer",
    }

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.call_scope_not_visible_for_goal"
        and issue.call_id == "derive_parametric_parabola_ii"
        for issue in reconciliation.issues
    )


def test_scope_local_bare_answer_refs_are_qualified_without_retry(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    calls = {
        call["call_id"]: call
        for scope in payload["scopes"]
        for call in scope["calls"]
    }
    calls["solve_axis_point_candidates_i"]["return_bindings"][
        "candidates"
    ] = {"ref": "E", "kind": "answer", "value_type": "PointList"}
    calls["recover_target_point_E_ii"]["return_bindings"]["point"] = {
        "ref": "E",
        "kind": "answer",
        "value_type": "Point",
    }

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert reconciliation.ok, reconciliation.to_payload()
    effective_calls = {
        call.call_id: call
        for scope in reconciliation.plan.scopes
        for call in scope.calls
    }
    assert effective_calls["solve_axis_point_candidates_i"].return_bindings[
        "candidates"
    ].ref == "i_2.E"
    assert effective_calls["recover_target_point_E_ii"].return_bindings[
        "point"
    ].ref == "ii.E"
    assert reconciliation.elaboration is not None
    assert {
        repair["call_id"]
        for repair in reconciliation.elaboration["deterministic_repairs"]
        if repair["action"] == "qualify_scope_local_answer_binding"
    } == {"solve_axis_point_candidates_i", "recover_target_point_E_ii"}


def test_scope_local_answer_qualification_does_not_cross_scope(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "solve_axis_point_candidates_i"
    )
    call["return_bindings"]["candidates"] = {
        "ref": "P",
        "kind": "answer",
        "value_type": "PointList",
    }

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert not reconciliation.ok
    assert any(
        issue.code == "functional.answer_ref_goal_mismatch"
        and issue.call_id == "solve_axis_point_candidates_i"
        for issue in reconciliation.issues
    )


def test_expected_bundle_token_drift_fails_loud(tmp_path) -> None:
    (
        bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        registry,
        planner_context,
        _catalog,
    ) = planning_binding_fixture(tmp_path)
    expected = replace(
        bundle.authority_token,
        problem_revision_id="problem-revision:stale",
    )

    with pytest.raises(
        ProblemPlanningBindingError,
        match="planner.problem_revision_drift",
    ):
        ProblemPlanningBindingCatalogBuilder().build(
            bundle,
            planning_context,
            planner_context,
            registry,
            expected_token=expected,
        )


def test_preparation_rejects_problem_sidecar_state_version_drift(
    tmp_path,
) -> None:
    (
        _bundle,
        _planning_context,
        problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        _catalog,
        plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    sidecar = reconciliation.functional_problem_binding_context
    target = sidecar.input_binding_for(
        "derive_parametric_parabola_ii",
        "curve_point",
        0,
    )
    assert target is not None and target.typed_source.state_version_id is not None
    drifted_source = replace(
        target.typed_source,
        state_version_id=replace(
            target.typed_source.state_version_id,
            ordinal=target.typed_source.state_version_id.ordinal + 1,
        ),
    )
    drifted_target = replace(target, typed_source=drifted_source)
    drifted_sidecar = replace(
        sidecar,
        input_bindings=tuple(
            drifted_target if item is target else item
            for item in sidecar.input_bindings
        ),
    )
    drifted_reconciliation = replace(
        reconciliation,
        functional_problem_binding_context=drifted_sidecar,
    )

    report = FunctionalTransactionalInterpreter().execute(
        raw_plan=plan,
        reconciliation=drifted_reconciliation,
        runtime_context=ContextBuilder().build(problem),
        parent_context=planner_context,
        inputs=inputs,
        handle_registry=registry,
    )
    failed = next(
        item
        for item in report.call_results
        if item.call_id == "derive_parametric_parabola_ii"
    )

    assert failed.status == "failed"
    assert failed.root_issues[0].code == "planner.transactional_configuration_error"
    assert "planner.problem_source_binding_drift" in failed.root_issues[0].message


def test_f5c_binding_path_does_not_reproject_or_call_global_catalog(
    tmp_path,
    monkeypatch,
) -> None:
    (
        bundle,
        planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        _catalog,
    ) = planning_binding_fixture(tmp_path)
    payload = deepcopy(
        json.loads(
            (
                SCOPE_NATIVE_FIXTURES
                / "tj-2026-nankai-yimo-25.functional-plan.json"
            ).read_text(encoding="utf-8")
        )
    )
    monkeypatch.setattr(
        PlannerStateContext,
        "semantic_read_catalog",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("global semantic catalog must not be used")
        ),
    )
    monkeypatch.setattr(
        ProblemDomainProjector,
        "project_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("domain projector must not be called")
        ),
    )
    catalog = ProblemPlanningBindingCatalogBuilder().build(
        bundle,
        planning_context,
        planner_context,
        registry,
    )

    from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
        FunctionalPlanReconciler,
    )
    from shuxueshuo_server.solver.runtime.functional_plan_validation import (
        FunctionalPlanValidator,
    )

    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=catalog,
    )

    assert reconciliation.ok


def test_unique_goal_visible_condition_role_binds_to_exact_ref(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    reduction = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["capability_id"] == "equal_length_ray_path_reduction"
    )
    exact_ref = reduction["args"]["path_minimum_target"]["ref"]
    reduction["args"]["path_minimum_target"]["ref"] = (
        "path_minimum_target"
    )

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    assert reconciliation.ok, reconciliation.to_payload()
    effective = next(
        call
        for call in reconciliation.effective_plan.calls
        if call.capability_id == "equal_length_ray_path_reduction"
    )
    assert effective.args["path_minimum_target"][0].ref == exact_ref
    assert any(
        item["action"] == "bind_unique_condition_role"
        for item in reconciliation.elaboration["deterministic_repairs"]
    )
