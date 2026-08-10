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
    functional_problem_binding_context_schema,
    problem_planning_binding_catalog_schema,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
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

from _problem_planning_support import (
    CASES,
    SCOPE_NATIVE_FIXTURES,
    planning_binding_fixture,
    scope_native_reconciliation_fixture,
)


ROOT = Path(__file__).resolve().parents[3]


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
        issue.code == "planner.problem_scope_visibility_drift"
        and issue.call_id == "derive_parametric_parabola_ii"
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
