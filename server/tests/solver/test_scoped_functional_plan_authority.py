from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningSourceUnit,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    FunctionalStepScopeAuthority,
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanValidator,
    audit_scoped_functional_structure,
    audit_scoped_functional_structure_prompt_payload,
    normalize_unique_scoped_goal_refs,
)

from _problem_planning_support import CASES, scope_native_reconciliation_fixture
from _scoped_functional_plan_support import (
    load_v2_fixture_payload,
    migrate_v1_fixture_payload,
)


@pytest.mark.parametrize("case", CASES)
def test_v2_authority_lowers_five_scope_native_plans(tmp_path, case) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
        _v1_plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path / case, case=case)
    payload = load_v2_fixture_payload(case)
    scoped, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and scoped is not None, report.to_payload()

    authority = ScopedFunctionalPlanAuthorityAdapter().lower(
        scoped,
        planning_context=planning_context,
        binding_catalog=binding_catalog,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )

    assert set(authority.step_authorities) == {
        step.step_id for step in scoped.steps
    }
    assert all(
        item.authored_goal_ref is None or item.authored_goal_unit_id is not None
        for item in authority.step_authorities.values()
    )
    authoring_scopes = {
        step_id: (item.plan_scope_id, item.semantic_owner_scope_id)
        for step_id, item in authority.step_authorities.items()
    }
    v2_reconciliation = FunctionalPlanReconciler().reconcile(
        authority.lowered_plan,
        planner_state_context=_planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=binding_catalog,
        pinned_canonical_call_ids=tuple(authority.step_authorities),
        authored_call_goal_bindings={
            step_id: item.consumer_goal_unit_ids
            for step_id, item in authority.step_authorities.items()
        },
        require_explicit_step_results=True,
    )
    assert v2_reconciliation.ok, v2_reconciliation.to_payload()
    finalized, finalization_report = authority.finalize_reconciliation(
        v2_reconciliation
    )
    assert finalization_report.ok
    assert finalized is not None
    placements = {
        item.canonical_call_id: item.execution_scope_id
        for item in v2_reconciliation.call_placements
    }
    assert all(
        item.execution_scope_id
        for item in finalized.step_authorities.values()
    )
    for step_id, item in finalized.step_authorities.items():
        assert (
            item.plan_scope_id,
            item.semantic_owner_scope_id,
        ) == authoring_scopes[step_id]
        assert item.execution_scope_id == placements[step_id]
        assert FunctionalStepScopeAuthority.from_payload(
            item.to_payload()
        ) == item

    refinalized, repeated_report = finalized.finalize_reconciliation(
        v2_reconciliation
    )
    assert repeated_report.ok
    assert refinalized is not None
    assert refinalized.authority_payload() == finalized.authority_payload()


def test_finalize_preserves_distinct_plan_semantic_and_execution_scopes(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    authority, fixture = _lower_payload(
        tmp_path,
        case,
        load_v2_fixture_payload(case),
    )
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        binding_catalog,
        *_rest,
    ) = fixture
    step_id = "ii_1_solve_m"
    source = authority.step_authorities[step_id]
    divergent = replace(
        source,
        plan_scope_id="problem",
        semantic_owner_scope_id="ii",
        binding_signature=stable_hash(
            {
                "fixture": "distinct_scope_authority",
                "step_id": step_id,
                "plan_scope_id": "problem",
                "semantic_owner_scope_id": "ii",
            }
        ),
    )
    authority = replace(
        authority,
        step_authorities={
            **authority.step_authorities,
            step_id: divergent,
        },
    )
    reconciliation = FunctionalPlanReconciler().reconcile(
        authority.lowered_plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=binding_catalog,
        pinned_canonical_call_ids=tuple(authority.step_authorities),
        authored_call_goal_bindings={
            item_id: item.consumer_goal_unit_ids
            for item_id, item in authority.step_authorities.items()
        },
        require_explicit_step_results=True,
    )
    placement = next(
        item
        for item in reconciliation.call_placements
        if item.canonical_call_id == step_id
    )
    assert placement.execution_scope_id == "ii_1"

    finalized, report = authority.finalize_reconciliation(reconciliation)

    assert report.ok
    assert finalized is not None
    item = finalized.step_authorities[step_id]
    assert (
        item.plan_scope_id,
        item.semantic_owner_scope_id,
        item.execution_scope_id,
    ) == ("problem", "ii", "ii_1")
    assert item.binding_signature == stable_hash(
        {
            "authoring_binding_signature": divergent.binding_signature,
            "canonical_call_id": step_id,
            "plan_scope_id": "problem",
            "semantic_owner_scope_id": "ii",
            "consumer_goal_unit_ids": list(item.consumer_goal_unit_ids),
            "execution_scope_id": "ii_1",
        }
    )


def test_single_return_role_is_safely_canonicalized(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    goal = _find_scope(payload["root_scope"], "ii")["goals"][0]
    assert goal["answer_from"] == {
        "step_id": "recover_target_point_E_ii",
        "return": "adjacent_vertex",
    }
    goal["answer_from"]["return"] = "point"

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    canonical_goal = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii",
    )["goals"][0]
    assert canonical_goal["answer_from"]["return"] == "adjacent_vertex"
    assert any(
        item.action == "canonicalize_unique_return_role"
        and item.step_id == "recover_target_point_E_ii"
        and item.from_ref == "point"
        and item.to_ref == "adjacent_vertex"
        for item in authority.normalizations
    )


def test_wrong_typed_macro_return_normalizes_to_unique_compatible_return(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    steps = _find_scope(payload["root_scope"], "ii")["goals"][0]["steps"]
    solve = next(item for item in steps if item["step_id"] == "solve_parameter_c_ii")
    # The Point return is incompatible with the MinimumExpression consumer.
    # Because the Macro return identity is code-owned and there is exactly one
    # type-compatible public return, canonicalization repairs the role.
    solve["args"]["expression"]["return"] = "attainment_point"

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    assert any(
        item.action == "canonicalize_unique_return_role"
        and item.step_id == "solve_parameter_c_ii"
        and item.from_ref == "attainment_point"
        and item.to_ref == "minimum_expression"
        for item in authority.normalizations
    )


def test_quadratic_square_macro_accepts_declared_open_return_forms(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    steps = _find_scope(payload["root_scope"], "ii")["goals"][0]["steps"]
    macro = next(
        item for item in steps if item["step_id"] == "derive_path_minimum_ii"
    )
    macro["return_expectations"] = {
        "minimum_expression": "open_expression",
        "attainment_point": "open_state",
    }

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    lowered = next(
        step
        for step in authority.scoped_plan.steps
        if step.step_id == "derive_path_minimum_ii"
    )
    assert lowered.return_expectations == macro["return_expectations"]


def test_goal_moved_to_parent_scope_fails_loud(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
        v1_plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    payload = migrate_v1_fixture_payload(
        v1_plan,
        planning_context,
        dict(sidecar.call_goal_bindings),
    )
    root = payload["root_scope"]
    scope_i = next(item for item in root["children"] if item["scope_ref"] == "i")
    scope_i_1 = next(
        item for item in scope_i["children"] if item["scope_ref"] == "i_1"
    )
    scope_i["goals"] = scope_i_1.pop("goals")
    scoped, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and scoped is not None

    with pytest.raises(ScopedFunctionalPlanError, match="functional.goal_tree_drift"):
        ScopedFunctionalPlanAuthorityAdapter().lower(
            scoped,
            planning_context=planning_context,
            binding_catalog=binding_catalog,
            capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
                inputs.family_spec,
                inputs.method_specs,
            ),
        )


@pytest.mark.parametrize(
    "case",
    ("tj-2026-hexi-yimo-25", "tj-2026-heping-yimo-25"),
)
def test_single_goal_scope_refs_are_canonicalized_deterministically(
    tmp_path,
    case,
) -> None:
    payload = load_v2_fixture_payload(case)
    raw_payload = deepcopy(payload)

    def replace_goal_refs(scope):
        goals = scope.get("goals", [])
        if len(goals) == 1:
            goals[0]["goal_ref"] = scope["scope_ref"]
        for child in scope.get("children", []):
            replace_goal_refs(child)

    replace_goal_refs(payload["root_scope"])
    scoped, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and scoped is not None
    fixture = scope_native_reconciliation_fixture(tmp_path / "fixture", case=case)
    planning_context = fixture[1]

    normalized, records = normalize_unique_scoped_goal_refs(
        scoped,
        planning_context,
    )
    normalized_again, second_records = normalize_unique_scoped_goal_refs(
        normalized,
        planning_context,
    )

    assert normalized.to_payload() == raw_payload
    assert normalized_again == normalized
    assert second_records == ()
    assert len(records) == 3
    assert {item.action for item in records} == {
        "canonicalize_unique_goal_ref"
    }
    assert {item.reason for item in records} == {
        "single_goal_owner_authority"
    }
    assert scoped.to_payload() == payload

    first, _ = _lower_payload(tmp_path / "first", case, payload)
    second, _ = _lower_payload(tmp_path / "second", case, payload)
    assert first.plan_id == second.plan_id
    assert first.plan_semantic_hash == second.plan_semantic_hash
    assert [item.to_payload() for item in first.normalizations[:3]] == [
        item.to_payload() for item in records
    ]


def test_multi_goal_scope_ref_is_never_guessed(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    scope_i_1 = _find_scope(payload["root_scope"], "i_1")
    scope_i_1["goals"][0]["goal_ref"] = "i_1"

    with pytest.raises(ScopedFunctionalPlanError, match="functional.goal_tree_drift"):
        _lower_payload(tmp_path, case, payload)


def test_structure_audit_is_independent_from_step_authority(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    fixture = scope_native_reconciliation_fixture(tmp_path, case=case)
    planning_context = fixture[1]
    payload = load_v2_fixture_payload(case)
    scope_i = _find_scope(payload["root_scope"], "i")
    scope_i["steps"][1]["args"] = {"unexpected_role": "A"}
    scoped, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and scoped is not None

    report = audit_scoped_functional_structure(scoped, planning_context)
    prompt_report = audit_scoped_functional_structure_prompt_payload(
        scoped,
        planning_context.to_prompt_payload(),
    )
    assert report.ok
    assert prompt_report.to_payload() == report.to_payload()
    with pytest.raises(
        ScopedFunctionalPlanError,
        match="functional.step_contract_invalid",
    ):
        _lower_payload(tmp_path / "step-authority", case, payload)


def test_unique_required_arg_type_match_is_recorded(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    step = _find_scope(payload["root_scope"], "i_2")["goals"][0]["steps"][0]
    step["args"]["curve_input"] = step["args"].pop("parabola")

    with pytest.raises(ScopedFunctionalPlanError) as captured:
        _lower_payload(tmp_path, case, payload)
    assert captured.value.code == "functional.step_contract_invalid"
    assert "unknown capability args: ['curve_input']" in captured.value.message


def test_goal_answer_refs_are_canonicalized_to_exact_target_object_refs(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    original = deepcopy(payload)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    steps = scope_ii["goals"][0]["steps"]
    candidates = next(
        item
        for item in steps
        if item["capability_id"] == "right_angle_equal_length_candidates"
    )
    selector = next(
        item
        for item in steps
        if item["capability_id"] == "curve_candidate_parameter_solve"
    )
    candidates["args"]["target"] = "ii.D"
    selector["args"]["target_point"] = "ii.D"
    original = deepcopy(payload)

    authority, _ = _lower_payload(tmp_path / "first", case, payload)
    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii",
    )
    canonical_steps = canonical_scope["goals"][0]["steps"]
    canonical_candidates = next(
        item
        for item in canonical_steps
        if item["capability_id"] == "right_angle_equal_length_candidates"
    )
    canonical_selector = next(
        item
        for item in canonical_steps
        if item["capability_id"] == "curve_candidate_parameter_solve"
    )

    assert canonical_candidates["args"]["target"] == "D"
    assert canonical_selector["args"]["target_point"] == "D"
    assert payload == original
    assert [
        item.to_payload()
        for item in authority.normalizations
        if item.action == "canonicalize_goal_target_input_ref"
    ] == [
        {
            "action": "canonicalize_goal_target_input_ref",
            "reason": "exact_math_object_identity",
            "step_id": "derive_right_angle_candidates_ii",
            "capability_id": "right_angle_equal_length_candidates",
            "arg_name": "target",
            "from_ref": "ii.D",
            "to_ref": "D",
            "goal_ref": "ii.D",
        },
        {
            "action": "canonicalize_goal_target_input_ref",
            "reason": "exact_math_object_identity",
            "step_id": "select_curve_candidate_ii",
            "capability_id": "curve_candidate_parameter_solve",
            "arg_name": "target_point",
            "from_ref": "ii.D",
            "to_ref": "D",
            "goal_ref": "ii.D",
        },
    ]

    replayed, _ = _lower_payload(
        tmp_path / "second",
        case,
        authority.scoped_plan.to_payload(),
    )
    assert replayed.plan_id == authority.plan_id
    assert replayed.plan_semantic_hash == authority.plan_semantic_hash
    assert not any(
        item.action == "canonicalize_goal_target_input_ref"
        for item in replayed.normalizations
    )


def test_unique_residual_symbol_constraint_enters_f5c_binding_sidecar(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    selector = next(
        item
        for item in scope_ii["goals"][0]["steps"]
        if item["capability_id"] == "curve_candidate_parameter_solve"
    )
    selector["args"].pop("symbol_constraint")
    authority, fixture = _lower_payload(tmp_path, case, payload)
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        binding_catalog,
        *_rest,
    ) = fixture

    reconciliation = FunctionalPlanReconciler().reconcile(
        authority.lowered_plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=binding_catalog,
        pinned_canonical_call_ids=tuple(authority.step_authorities),
        authored_call_goal_bindings={
            step_id: item.consumer_goal_unit_ids
            for step_id, item in authority.step_authorities.items()
        },
        require_explicit_step_results=True,
    )

    assert reconciliation.ok, reconciliation.to_payload()
    context = reconciliation.functional_problem_binding_context
    assert context is not None
    binding = context.input_binding_for(
        "select_curve_candidate_ii",
        "symbol_constraint",
        0,
    )
    assert binding is not None
    assert binding.source_kind == "problem_source"
    assert binding.semantic_ref is not None
    assert binding.semantic_ref.ref == "symbol_constraint_b"
    assert binding.typed_source is not None
    assert binding.typed_source.kind == "condition"
    assert binding.typed_source.condition_id == (
        "condition:symbol_constraint_f11ebacac514@problem"
    )


def test_goal_answer_ref_is_canonicalized_for_same_object_latest_state_arg(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    step = next(
        item
        for item in scope_ii["goals"][0]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    step["args"]["curve_point"] = "ii.D"

    authority, _ = _lower_payload(tmp_path, case, payload)
    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii",
    )
    canonical_step = next(
        item
        for item in canonical_scope["goals"][0]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    assert canonical_step["args"]["curve_point"] == "D"
    assert [
        item.to_payload()
        for item in authority.normalizations
        if item.action == "canonicalize_goal_target_input_ref"
        and item.step_id == step["step_id"]
    ] == [
        {
            "action": "canonicalize_goal_target_input_ref",
            "reason": "exact_math_object_identity",
            "step_id": step["step_id"],
            "capability_id": "quadratic_from_constraints",
            "arg_name": "curve_point",
            "from_ref": "ii.D",
            "to_ref": "D",
            "goal_ref": "ii.D",
        }
    ]


def test_fixed_form_return_expectation_is_dropped_without_semantic_drift(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    baseline_payload = load_v2_fixture_payload(case)
    baseline, _ = _lower_payload(
        tmp_path / "baseline",
        case,
        baseline_payload,
    )
    payload = load_v2_fixture_payload(case)
    original = deepcopy(payload)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    step = scope_ii["goals"][0]["steps"][-1]
    assert step["capability_id"] == "parameter_from_expression_value"
    step["return_expectations"] = {"parameter_value": "closed_value"}
    original = deepcopy(payload)

    authority, _ = _lower_payload(tmp_path / "normalized", case, payload)

    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii",
    )
    canonical_step = canonical_scope["goals"][0]["steps"][-1]
    assert "return_expectations" not in canonical_step
    assert payload == original
    assert authority.plan_id == baseline.plan_id
    assert authority.plan_semantic_hash == baseline.plan_semantic_hash
    assert [
        item.to_payload()
        for item in authority.normalizations
        if item.action == "drop_fixed_form_return_expectation"
    ] == [
        {
            "action": "drop_fixed_form_return_expectation",
            "reason": "return_expectation_policy_omit",
            "step_id": "solve_parameter_from_minimum_ii",
            "capability_id": "parameter_from_expression_value",
            "return_name": "parameter_value",
            "from_form": "closed_value",
        }
    ]
    replayed, _ = _lower_payload(
        tmp_path / "replayed",
        case,
        authority.scoped_plan.to_payload(),
    )
    assert replayed.plan_id == authority.plan_id
    assert replayed.plan_semantic_hash == authority.plan_semantic_hash
    assert not any(
        item.action == "drop_fixed_form_return_expectation"
        for item in replayed.normalizations
    )


def test_selectable_expectation_is_preserved_and_invalid_form_fails(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    reduction = scope_ii["goals"][0]["steps"][-2]
    assert reduction["return_expectations"] == {
        "minimum_expression": "open_expression"
    }

    authority, _ = _lower_payload(tmp_path / "valid", case, payload)
    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii",
    )
    assert canonical_scope["goals"][0]["steps"][-2][
        "return_expectations"
    ] == {"minimum_expression": "open_expression"}

    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    scope_ii["goals"][0]["steps"][-2]["return_expectations"] = {
        "minimum_expression": "closed_state"
    }
    with pytest.raises(
        ScopedFunctionalPlanError,
        match="return expectation is not declared by the capability",
    ):
        _lower_payload(tmp_path / "invalid", case, payload)


def test_unknown_return_expectation_role_is_not_silently_dropped(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    scope_ii["goals"][0]["steps"][-1]["return_expectations"] = {
        "parameter_result": "closed_value"
    }

    with pytest.raises(
        ScopedFunctionalPlanError,
        match="return expectation is not declared by the capability",
    ):
        _lower_payload(tmp_path, case, payload)


def test_mixed_expectations_only_drop_omit_return(tmp_path) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii_2 = _find_scope(payload["root_scope"], "ii_2")
    transform = scope_ii_2["goals"][0]["steps"][0]
    assert transform["capability_id"] == "weighted_axis_path_triangle_transform"
    transform["return_expectations"] = {
        "auxiliary_point": "open_state",
        "auxiliary_locus": "open_state",
    }

    authority, _ = _lower_payload(tmp_path, case, payload)

    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii_2",
    )
    canonical_transform = canonical_scope["goals"][0]["steps"][0]
    assert canonical_transform["return_expectations"] == {
        "auxiliary_point": "open_state"
    }
    assert [
        item.to_payload()
        for item in authority.normalizations
        if item.action == "drop_fixed_form_return_expectation"
    ] == [
        {
            "action": "drop_fixed_form_return_expectation",
            "reason": "return_expectation_policy_omit",
            "step_id": "transform_weighted_path_ii",
            "capability_id": "weighted_axis_path_triangle_transform",
            "return_name": "auxiliary_locus",
            "from_form": "open_state",
        }
    ]

def test_goal_answer_ref_is_not_repaired_across_goals_or_from_scope_step(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    steps = scope_ii["goals"][0]["steps"]
    candidate_index = next(
        index
        for index, item in enumerate(steps)
        if item["capability_id"] == "right_angle_equal_length_candidates"
    )
    steps[candidate_index]["args"]["target"] = "i.P"
    with pytest.raises(ScopedFunctionalPlanError) as cross_goal:
        _lower_payload(tmp_path / "cross-goal", case, payload)
    assert cross_goal.value.code == "functional.answer_ref_used_as_input"
    assert "belongs to another Goal" in cross_goal.value.message

    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    goal_steps = scope_ii["goals"][0]["steps"]
    candidate_index = next(
        index
        for index, item in enumerate(goal_steps)
        if item["capability_id"] == "right_angle_equal_length_candidates"
    )
    candidate_step = goal_steps.pop(candidate_index)
    candidate_step["args"]["target"] = "ii.D"
    scope_ii["steps"] = [candidate_step]
    with pytest.raises(ScopedFunctionalPlanError) as shared_scope:
        _lower_payload(tmp_path / "scope-step", case, payload)
    assert shared_scope.value.code == "functional.answer_ref_used_as_input"
    assert not any(
        item.action == "canonicalize_goal_target_input_ref"
        for item in shared_scope.value.normalizations
    )


@pytest.mark.parametrize("candidate_refs", [(), ("D", "D_alias")])
def test_goal_answer_ref_requires_one_proven_target_input(
    tmp_path,
    monkeypatch,
    candidate_refs,
) -> None:
    import shuxueshuo_server.solver.runtime.scoped_functional_plan as scoped_module

    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    step = next(
        item
        for item in scope_ii["goals"][0]["steps"]
        if item["capability_id"] == "right_angle_equal_length_candidates"
    )
    step["args"]["target"] = "ii.D"
    monkeypatch.setattr(
        scoped_module,
        "_goal_target_input_ref_candidates",
        lambda *args, **kwargs: candidate_refs,
    )

    with pytest.raises(ScopedFunctionalPlanError) as captured:
        _lower_payload(tmp_path, case, payload)

    assert captured.value.code == "functional.answer_ref_used_as_input"
    assert "not exactly one visible" in captured.value.message


def test_unknown_args_drop_only_after_declared_contract_is_complete(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    step = _find_scope(payload["root_scope"], "i_2")["goals"][0]["steps"][0]
    step["args"]["mystery_point"] = step["args"].pop("known_point")
    step["args"]["unused_hint"] = "A"

    authority, _ = _lower_payload(tmp_path / "optional", case, payload)

    canonical_step = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "i_2",
    )["goals"][0]["steps"][0]
    assert set(canonical_step["args"]) == {"parabola"}
    assert {
        item.arg_name
        for item in authority.normalizations
        if item.action == "drop_unknown_capability_arg"
        and item.step_id == canonical_step["step_id"]
    } == {"mystery_point", "unused_hint"}

    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    step = _find_scope(payload["root_scope"], "i_2")["goals"][0]["steps"][1]
    step["args"]["first_point"] = step["args"].pop("side_start")
    step["args"]["second_point"] = step["args"].pop("side_end")
    with pytest.raises(ScopedFunctionalPlanError, match="unknown capability args"):
        _lower_payload(tmp_path / "ambiguous", case, payload)


def test_answer_from_drops_only_the_same_redundant_output_target(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    step = _find_scope(payload["root_scope"], "i")["steps"][1]
    step["output_targets"] = {"point": "A"}

    authority, _ = _lower_payload(tmp_path / "same-target", case, payload)

    canonical_step = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "i",
    )["steps"][1]
    assert "output_targets" not in canonical_step
    assert [
        item.to_payload()
        for item in authority.normalizations
        if item.action == "drop_redundant_answer_output_target"
    ] == [
        {
            "action": "drop_redundant_answer_output_target",
            "step_id": "derive_x_intercept_A_i",
            "capability_id": "quadratic_x_axis_intercept_point",
            "reason": "answer_from_precedence",
            "return_name": "point",
            "target_ref": "A",
        }
    ]

    payload = load_v2_fixture_payload(case)
    _find_scope(payload["root_scope"], "i")["steps"][1][
        "output_targets"
    ] = {"point": "P"}
    with pytest.raises(
        ScopedFunctionalPlanError,
        match="answer return must not also declare output_targets",
    ):
        _lower_payload(tmp_path / "different-target", case, payload)


def test_unique_source_fact_target_is_inferred_and_recorded(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    step = _find_scope(payload["root_scope"], "i_2")["goals"][0]["steps"][0]
    step.pop("output_targets")

    authority, fixture = _lower_payload(tmp_path, case, payload)

    canonical_step = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "i_2",
    )["goals"][0]["steps"][0]
    assert canonical_step["output_targets"] == {"point": "E"}
    assert any(
        item.to_payload()
        == {
            "action": "infer_unique_output_target",
            "step_id": "parameterize_axis_point_E_i",
            "capability_id": "quadratic_axis_parameterized_point",
            "reason": "capability_selector_source_authority",
            "return_name": "point",
            "target_ref": "E",
        }
        for item in authority.normalizations
    )
    inputs = fixture[3]
    reconciliation = FunctionalPlanReconciler().reconcile(
        authority.lowered_plan,
        planner_state_context=fixture[6],
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=fixture[5],
        question_goals=inputs.question_goals,
        problem_binding_catalog=fixture[7],
    )
    assert reconciliation.ok, reconciliation.to_payload()


def test_curve_at_x_target_is_inferred_before_liveness(tmp_path) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    step = next(
        item
        for item in scope_ii["steps"]
        if item["capability_id"] == "point_on_parabola_at_x"
    )
    step.pop("output_targets")

    authority, fixture = _lower_payload(tmp_path, case, payload)

    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "ii",
    )
    canonical_step = next(
        item
        for item in canonical_scope["steps"]
        if item["capability_id"] == "point_on_parabola_at_x"
    )
    assert canonical_step["output_targets"] == {"point": "D"}
    assert any(
        item.action == "infer_unique_output_target"
        and item.step_id == canonical_step["step_id"]
        and item.target_ref == "D"
        for item in authority.normalizations
    )
    inputs = fixture[3]
    reconciliation = FunctionalPlanReconciler().reconcile(
        authority.lowered_plan,
        planner_state_context=fixture[6],
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=fixture[5],
        question_goals=inputs.question_goals,
        problem_binding_catalog=fixture[7],
    )
    assert reconciliation.ok, reconciliation.to_payload()


def test_source_fact_target_selector_refuses_multiple_objects(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    step = _find_scope(payload["root_scope"], "i_2")["goals"][0]["steps"][0]
    step.pop("output_targets")
    fixture = scope_native_reconciliation_fixture(tmp_path, case=case)
    context = fixture[1]
    root = next(scope for scope in context.scopes if scope.scope_id == "problem")
    ambiguous_context = replace(
        context,
        scopes=tuple(
            replace(
                scope,
                facts=(
                    *scope.facts,
                    ProblemPlanningSourceUnit(
                        "fact:test:second_axis_point",
                        {
                            "kind": "point_on_axis",
                            "axis": "symmetry",
                            "curve": "parabola",
                            "point": "K",
                            "ref": "axis_membership_parabola_k",
                        },
                    ),
                ),
            )
            if scope is root
            else scope
            for scope in context.scopes
        ),
    )
    scoped, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and scoped is not None
    inputs = fixture[3]

    with pytest.raises(
        ScopedFunctionalPlanError,
        match="has no unique target from its declared source-fact selector",
    ):
        ScopedFunctionalPlanAuthorityAdapter().lower(
            scoped,
            planning_context=ambiguous_context,
            binding_catalog=fixture[7],
            capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
                inputs.family_spec,
                inputs.method_specs,
            ),
        )


def test_scope_tree_does_not_lift_branch_step_from_source_ref_read(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    scope_i = _find_scope(payload["root_scope"], "i")
    scope_i_1 = _find_scope(payload["root_scope"], "i_1")
    scope_i_2 = _find_scope(payload["root_scope"], "i_2")
    get_a = scope_i["steps"].pop(1)
    scope_i_1["steps"] = [get_a]
    square_step = scope_i_2["goals"][0]["steps"][1]
    square_step["args"]["side_start"] = "A"

    authority, fixture = _lower_payload(tmp_path, case, payload)

    step_authority = authority.step_authorities["derive_x_intercept_A_i"]
    assert step_authority.plan_scope_id == "i_1"
    assert step_authority.semantic_owner_scope_id == "i_1"
    assert next(
        scope.scope_id
        for scope in authority.lowered_plan.scopes
        if any(call.call_id == "derive_x_intercept_A_i" for call in scope.calls)
    ) == "i_1"
    square_call = next(
        call
        for call in authority.lowered_plan.calls
        if call.call_id == "derive_square_vertex_G_i"
    )
    assert square_call.args["side_start"][0].to_payload() == {
        "ref": "A",
        "kind": "point",
    }


def test_scope_step_cannot_be_authored_above_its_output_authority(tmp_path) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v2_fixture_payload(case)
    root = payload["root_scope"]
    scope_ii = _find_scope(root, "ii")
    establish_parabola, derive_d = scope_ii["steps"][:2]
    scope_ii["steps"] = scope_ii["steps"][2:]
    root["steps"] = [establish_parabola, derive_d]

    with pytest.raises(
        ScopedFunctionalPlanError,
        match="functional.output_target_invalid",
    ):
        _lower_payload(tmp_path, case, payload)


def test_output_target_selector_rejects_type_compatible_wrong_fact_role(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    scope_ii["steps"].insert(
        0,
        {
            "step_id": "redundant_build_M",
            "capability_id": "point_on_parabola_at_x",
            "args": {"parabola": "parabola"},
            "output_targets": {"point": "M"},
        },
    )
    fixture = scope_native_reconciliation_fixture(tmp_path, case=case)
    scoped, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and scoped is not None
    inputs = fixture[3]

    authority, report = ScopedFunctionalPlanAuthorityAdapter().analyze(
        scoped,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )

    assert authority is None
    issue = next(
        item
        for item in report.issues
        if item.code == "functional.output_target_selector_mismatch"
    )
    assert issue.details == {
        "capability_id": "point_on_parabola_at_x",
        "semantic_ref": "M",
        "role": "point",
        "expected_type": "Point",
        "expected_state": "source_fact_authorized",
        "observed_role": "point",
        "observed_target": "M",
        "expected_targets": [],
        "required_fact_kind": "point_on_curve",
        "required_fields": {"construction": "curve_at_x"},
        "repair_options": [
            "use the existing visible object state without reconstructing it",
            "choose a capability whose source-fact selector matches this target",
        ],
        "retryability": "planner_repairable",
        "repair_action": "choose_applicable_point_construction_capability",
    }


def test_scope_visibility_feedback_distinguishes_identity_from_local_state(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    payload = load_v2_fixture_payload(case)
    root = payload["root_scope"]
    scope_iii = _find_scope(root, "iii")
    goal_iii = scope_iii["goals"][0]
    local_state_step = goal_iii["steps"].pop(0)
    root["steps"] = [local_state_step]

    fixture = scope_native_reconciliation_fixture(tmp_path, case=case)
    scoped, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and scoped is not None
    inputs = fixture[3]

    authority, report = ScopedFunctionalPlanAuthorityAdapter().analyze(
        scoped,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )

    assert authority is None
    issue = next(
        item
        for item in report.issues
        if item.code == "functional.step_scope_visibility_drift"
    )
    assert "step scope 'problem'" in issue.message
    assert "candidate owner scopes" in issue.message
    assert "'iii'" in issue.message
    assert "shared MathObject identity does not share scope-local state" in (
        issue.message
    )


def test_authority_analysis_aggregates_independent_root_issues(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    scope_i = _find_scope(payload["root_scope"], "i")
    scope_i["steps"][1]["args"] = {"mystery": "A"}
    scope_i_2 = _find_scope(payload["root_scope"], "i_2")
    scope_i_2["goals"][0]["steps"][1].pop("output_targets")
    scope_ii = _find_scope(payload["root_scope"], "ii")
    scope_ii["goals"][0]["steps"][0]["args"]["curve_point"] = (
        "point_on_curve_parabola_g"
    )
    fixture = scope_native_reconciliation_fixture(tmp_path, case=case)
    scoped, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and scoped is not None
    inputs = fixture[3]

    authority, report = ScopedFunctionalPlanAuthorityAdapter().analyze(
        scoped,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )

    assert authority is None
    assert list(dict.fromkeys(item.code for item in report.issues)) == [
        "functional.step_contract_invalid",
        "functional.output_target_invalid",
        "functional.step_scope_visibility_drift",
    ]
    contract_issues = tuple(
        item
        for item in report.issues
        if item.code == "functional.step_contract_invalid"
    )
    assert len(contract_issues) == 2
    assert {
        tuple(item.details[key])
        for item in contract_issues
        for key in (
            "observed_unknown_args",
            "observed_missing_required_args",
        )
        if item.details[key]
    } == {("mystery",), ("parabola",)}
    assert [item.path for item in contract_issues] == sorted(
        item.path for item in contract_issues
    )


def test_structure_audit_classifies_scope_and_goal_drift(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    planning_context = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
    )[1]

    def report(payload):
        scoped, validation = (
            ScopedFunctionalPlanValidator().validate_payload_with_report(payload)
        )
        assert validation.ok and scoped is not None
        return audit_scoped_functional_structure(scoped, planning_context)

    missing_scope = load_v2_fixture_payload(case)
    _find_scope(missing_scope["root_scope"], "i")["children"].pop()
    missing_scope_report = report(missing_scope)
    assert missing_scope_report.missing_scope_refs == ("i_2",)
    assert missing_scope_report.to_payload()["first_issue"] == {
        "code": "functional.scope_tree_drift",
        "path": "$.scopes['i_2']",
        "message": "scope is missing from the Plan",
    }

    unexpected_scope = load_v2_fixture_payload(case)
    unexpected_scope["root_scope"]["children"].append(
        {"scope_ref": "unexpected_scope"}
    )
    assert report(unexpected_scope).unexpected_scope_refs == ("unexpected_scope",)

    duplicate_scope = load_v2_fixture_payload(case)
    duplicate_scope["root_scope"]["children"].append(
        deepcopy(_find_scope(duplicate_scope["root_scope"], "i_1"))
    )
    assert report(duplicate_scope).duplicate_scope_refs == ("i_1",)

    moved_scope = load_v2_fixture_payload(case)
    parent_i = _find_scope(moved_scope["root_scope"], "i")
    child_i_1 = parent_i["children"].pop(0)
    moved_scope["root_scope"]["children"].append(child_i_1)
    assert report(moved_scope).moved_scope_refs == ("i_1",)

    missing_goal = load_v2_fixture_payload(case)
    _find_scope(missing_goal["root_scope"], "i_1")["goals"].pop()
    assert report(missing_goal).missing_goal_refs == ("i_1.P",)

    unexpected_goal = load_v2_fixture_payload(case)
    goal = _find_scope(unexpected_goal["root_scope"], "i_1")["goals"][0]
    goal["goal_ref"] = "i_1.unexpected"
    unexpected_report = report(unexpected_goal)
    assert unexpected_report.missing_goal_refs == ("i_1.A",)
    assert unexpected_report.unexpected_goal_refs == ("i_1.unexpected",)

    duplicate_goal = load_v2_fixture_payload(case)
    goals = _find_scope(duplicate_goal["root_scope"], "i_1")["goals"]
    goals.append(deepcopy(goals[0]))
    assert report(duplicate_goal).duplicate_goal_refs == ("i_1.A",)

    moved_goal = load_v2_fixture_payload(case)
    source_goals = _find_scope(moved_goal["root_scope"], "i_1")["goals"]
    moved = source_goals.pop(0)
    _find_scope(moved_goal["root_scope"], "i_2")["goals"].append(moved)
    assert report(moved_goal).moved_goal_refs == ("i_1.A",)


def test_intent_does_not_change_semantic_hash(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
        _v1_plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path)
    payload = load_v2_fixture_payload("tj-2026-nankai-yimo-25")
    scoped, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and scoped is not None
    adapter = ScopedFunctionalPlanAuthorityAdapter()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    first = adapter.lower(
        scoped,
        planning_context=planning_context,
        binding_catalog=binding_catalog,
        capability_catalog=catalog,
    )
    first_step_id = scoped.steps[0].step_id
    changed = replace(
        scoped,
        root_scope=_replace_step_intent(
            scoped.root_scope,
            first_step_id,
            "different debug prose",
        ),
    )
    second = adapter.lower(
        changed,
        planning_context=planning_context,
        binding_catalog=binding_catalog,
        capability_catalog=catalog,
    )

    assert first.plan_id != second.plan_id
    assert first.plan_semantic_hash == second.plan_semantic_hash


def test_missing_scope_and_duplicate_goal_fail_loud(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    missing_scope = deepcopy(payload)
    missing_scope["root_scope"]["children"].pop()

    with pytest.raises(ScopedFunctionalPlanError, match="functional.scope_tree_drift"):
        _lower_payload(tmp_path / "missing", case, missing_scope)

    duplicate_goal = deepcopy(payload)
    scope_i_1 = _find_scope(duplicate_goal["root_scope"], "i_1")
    scope_i_1["goals"].append(deepcopy(scope_i_1["goals"][0]))
    with pytest.raises(ScopedFunctionalPlanError, match="functional.goal_tree_drift"):
        _lower_payload(tmp_path / "duplicate", case, duplicate_goal)


def test_forward_reference_fails_loud(tmp_path) -> None:
    case = "tj-2026-xiqing-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    scope_ii["steps"][0]["args"]["curve_point"] = {
        "step_id": "derive_curve_point_D_ii",
        "return": "point",
    }
    with pytest.raises(ScopedFunctionalPlanError) as captured:
        _lower_payload(tmp_path / "forward", case, payload)
    assert captured.value.code == "functional.named_entity_requires_source_ref"


def test_answer_selected_named_output_is_normalized_to_source_ref(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_i_2 = _find_scope(payload["root_scope"], "i_2")
    target = next(
        item
        for item in scope_i_2["goals"][0]["steps"]
        if item["step_id"] == "derive_x_intercept_B_i"
    )
    target["args"]["parabola"] = {
        "step_id": "derive_parabola_i",
        "return": "parabola",
    }

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"], "i_2"
    )
    canonical_target = next(
        item
        for item in canonical_scope["goals"][0]["steps"]
        if item["step_id"] == "derive_x_intercept_B_i"
    )
    assert canonical_target["args"]["parabola"] == "parabola"
    assert any(
        item.action == "canonicalize_named_entity_result_ref"
        and item.from_ref == "derive_parabola_i.parabola"
        and item.to_ref == "parabola"
        for item in authority.normalizations
    )


def test_unknown_targets_on_anonymous_returns_are_removed(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_i = _find_scope(payload["root_scope"], "i")
    steps = [
        step
        for goal_plan in scope_i["children"]
        for goal in goal_plan.get("goals", [])
        for step in goal.get("steps", [])
    ]
    angle = next(
        item
        for item in steps
        if item["step_id"] == "derive_equal_angle_i"
    )
    axis = next(
        item
        for item in steps
        if item["step_id"] == "derive_axis_intercept_F_i"
    )
    angle["output_targets"] = {
        "angle_equality": "invented_angle_equality"
    }
    axis["output_targets"] = {"point": "invented_axis_point"}

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    canonical_scope = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "i",
    )
    canonical_steps = [
        step
        for child in canonical_scope["children"]
        for goal in child.get("goals", [])
        for step in goal.get("steps", [])
    ]
    assert "output_targets" not in next(
        item
        for item in canonical_steps
        if item["step_id"] == "derive_equal_angle_i"
    )
    assert "output_targets" not in next(
        item
        for item in canonical_steps
        if item["step_id"] == "derive_axis_intercept_F_i"
    )
    records = [
        item
        for item in authority.normalizations
        if item.action == "drop_unknown_anonymous_output_target"
    ]
    assert {(item.step_id, item.target_ref) for item in records} == {
        ("derive_equal_angle_i", "invented_angle_equality"),
        ("derive_axis_intercept_F_i", "invented_axis_point"),
    }


def test_return_expectation_role_uses_public_macro_contract(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    steps = _find_scope(payload["root_scope"], "ii")["goals"][0]["steps"]
    macro = next(
        item for item in steps if item["step_id"] == "derive_path_minimum_ii"
    )
    macro["return_expectations"] = {"attainment_point": "closed_value"}

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    canonical = next(
        item
        for item in _find_scope(
            authority.scoped_plan.to_payload()["root_scope"], "ii"
        )["goals"][0]["steps"]
        if item["step_id"] == "derive_path_minimum_ii"
    )
    assert canonical["return_expectations"] == {
        "minimum_expression": "closed_value"
    }
    assert any(
        item.action == "canonicalize_unique_return_role"
        and item.step_id == "derive_path_minimum_ii"
        and item.from_ref == "attainment_point"
        and item.to_ref == "minimum_expression"
        for item in authority.normalizations
    )


def test_scope_local_producer_is_not_promoted_across_sibling_goals(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    scope_i = _find_scope(payload["root_scope"], "i")
    scope_i_1 = _find_scope(payload["root_scope"], "i_1")
    shared = next(
        item
        for item in scope_i["steps"]
        if item["step_id"] == "derive_parabola_i"
    )
    scope_i["steps"].remove(shared)
    scope_i_1["goals"][0]["steps"] = [shared]

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    canonical_i = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "i",
    )
    canonical_i_1 = _find_scope(
        authority.scoped_plan.to_payload()["root_scope"],
        "i_1",
    )
    assert "steps" not in canonical_i
    assert [
        item["step_id"] for item in canonical_i_1["goals"][0]["steps"]
    ] == ["derive_parabola_i"]
    assert not any(
        item.action == "promote_shared_step_to_scope"
        for item in authority.normalizations
    )


def test_goal_authored_shared_producer_is_promoted_to_typed_lca(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    canonical_payload = load_v2_fixture_payload(case)
    authority, fixture = _lower_payload(
        tmp_path / "canonical",
        case,
        canonical_payload,
    )
    goal_owned_payload = deepcopy(canonical_payload)
    scope_i = _find_scope(goal_owned_payload["root_scope"], "i")
    scope_i_1 = _find_scope(goal_owned_payload["root_scope"], "i_1")
    shared = next(
        item
        for item in scope_i["steps"]
        if item["step_id"] == "derive_parabola_i"
    )
    scope_i["steps"].remove(shared)
    scope_i_1["goals"][0]["steps"] = [shared]

    goal_owned_authority, _ = _lower_payload(
        tmp_path / "goal-owned",
        case,
        goal_owned_payload,
    )
    authority = replace(
        goal_owned_authority,
        # Reconciliation has already produced a complete typed consumer DAG.
        # Finalization must use that authority to normalize the authored tree;
        # authored Goal visibility is not reinterpreted here.
        lowered_plan=authority.lowered_plan,
    )
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        binding_catalog,
        *_rest,
    ) = fixture
    reconciliation = FunctionalPlanReconciler().reconcile(
        authority.lowered_plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=binding_catalog,
        pinned_canonical_call_ids=tuple(authority.step_authorities),
        authored_call_goal_bindings={
            step_id: item.consumer_goal_unit_ids
            for step_id, item in authority.step_authorities.items()
        },
        require_explicit_step_results=True,
    )
    assert reconciliation.ok, [item.to_payload() for item in reconciliation.issues]

    finalized, report = authority.finalize_reconciliation(reconciliation)

    assert report.ok, report.to_payload()
    assert finalized is not None
    canonical_i = _find_scope(
        finalized.scoped_plan.to_payload()["root_scope"],
        "i",
    )
    canonical_i_1 = _find_scope(
        finalized.scoped_plan.to_payload()["root_scope"],
        "i_1",
    )
    assert "derive_parabola_i" in {
        item["step_id"] for item in canonical_i["steps"]
    }
    assert "derive_parabola_i" not in {
        item["step_id"]
        for item in canonical_i_1["goals"][0].get("steps", [])
    }
    step_authority = finalized.step_authorities["derive_parabola_i"]
    assert step_authority.authored_goal_ref is None
    assert step_authority.authored_goal_unit_id is None
    assert step_authority.semantic_owner_scope_id == "i"
    assert step_authority.execution_scope_id == "i"
    assert any(
        item.action == "promote_shared_goal_step_to_scope"
        and item.step_id == "derive_parabola_i"
        and item.scope_ref == "i"
        for item in finalized.normalizations
    )


def test_answer_and_output_authority_fail_loud(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    scope_i_1 = _find_scope(payload["root_scope"], "i_1")
    scope_i_1["goals"][1]["answer_from"] = {
        "step_id": "derive_x_intercept_A_i",
        "return": "point",
    }
    with pytest.raises(
        ScopedFunctionalPlanError,
        match="one return role cannot bind multiple Goal answers",
    ):
        _lower_payload(tmp_path / "duplicate-answer", case, payload)

    payload = load_v2_fixture_payload(case)
    scope_i = _find_scope(payload["root_scope"], "i")
    scope_i["steps"][1]["output_targets"] = {"point": "minimum_value"}
    with pytest.raises(
        ScopedFunctionalPlanError,
        match="output target is outside the step scope",
    ) as output_error:
        _lower_payload(tmp_path / "output-scope", case, payload)
    issue = next(
        item
        for item in output_error.value.issues
        if item.code == "functional.output_target_invalid"
        and item.details.get("observed_target") == "minimum_value"
    )
    assert issue.details["observed_role"] == "point"
    assert issue.details["expected_targets"]
    assert "minimum_value" not in issue.details["expected_targets"]
    assert issue.details["retryability"] == "planner_repairable"


def test_source_ref_keeps_entity_wire_and_pins_latest_visible_producer(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    root_steps = payload["root_scope"]["steps"]
    duplicate = deepcopy(root_steps[0])
    duplicate["step_id"] = "derive_y_intercept_C_again"
    root_steps.insert(1, duplicate)
    root_steps[2]["args"]["source"] = "C"

    authority, _fixture = _lower_payload(tmp_path, case, payload)
    translated = next(
        call
        for call in authority.lowered_plan.calls
        if call.call_id == "derive_translated_D_i"
    )
    assert translated.args["source"][0].to_payload() == {
        "kind": "point",
        "ref": "C",
    }
    pin = authority.lowered_plan.typed_input_source_pins[
        ("derive_translated_D_i", "source", 0)
    ]
    assert pin.semantic_ref == "C"
    assert pin.producer_call_id == "derive_y_intercept_C_again"
    assert not any(
        item.action == "canonicalize_latest_dynamic_source_ref"
        for item in authority.normalizations
    )


def test_source_ref_pins_implicit_preserve_input_object_return(tmp_path) -> None:
    case = "tj-2026-heping-ermo-25"
    payload = load_v2_fixture_payload(case)
    scope_ii = _find_scope(payload["root_scope"], "ii")
    goal = scope_ii["goals"][0]
    steps = {item["step_id"]: item for item in goal["steps"]}
    steps["evaluate_point_A_ii"].pop("output_targets")
    steps["recover_target_point_E_ii"]["args"]["side_start"] = "A"

    authority, _fixture = _lower_payload(tmp_path, case, payload)

    recovered = next(
        call
        for call in authority.lowered_plan.calls
        if call.call_id == "recover_target_point_E_ii"
    )
    assert recovered.args["side_start"][0].to_payload() == {
        "kind": "point",
        "ref": "A",
    }
    pin = authority.lowered_plan.typed_input_source_pins[
        ("recover_target_point_E_ii", "side_start", 0)
    ]
    assert pin.semantic_ref == "A"
    assert pin.producer_call_id == "evaluate_point_A_ii"
    assert not any(
        item.action == "canonicalize_latest_dynamic_source_ref"
        for item in authority.normalizations
    )


def test_terminal_dead_pure_goal_step_is_available_for_pruning(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = load_v2_fixture_payload(case)
    goal = _find_scope(payload["root_scope"], "i_2")["goals"][0]
    goal["steps"].append(
        {
            "step_id": "dead_vertex",
            "capability_id": "quadratic_vertex_point",
            "args": {
                "parabola": "parabola"
            },
        }
    )
    authority, _fixture = _lower_payload(tmp_path, case, payload)
    dead = authority.step_authorities["dead_vertex"]
    assert dead.authored_goal_ref == "i_2.E"
    assert dead.authored_goal_unit_id is not None
    assert dead.consumer_goal_unit_ids == ()


def _call_semantics(plan) -> dict:
    result = {}
    capability_by_call = {
        call.call_id: call.capability_id for call in plan.calls
    }
    for call in plan.calls:
        payload = call.to_payload()
        payload.pop("strategy")
        payload.pop("reason")
        if call.capability_id == "quadratic_x_axis_intercept_point":
            args = payload["args"]
            if "quadratic" in args:
                args["parabola"] = args.pop("quadratic")
        if call.capability_id == "square_adjacent_vertex_from_side":
            bindings = payload["return_bindings"]
            if "point" in bindings:
                bindings["adjacent_vertex"] = bindings.pop("point")
        _normalize_public_step_results(payload, capability_by_call)
        result[call.call_id] = _without_derived_value_types(payload)
    return result


def _normalize_public_step_results(value, capability_by_call):
    if isinstance(value, dict):
        producer = value.get("from_call")
        if (
            producer is not None
            and capability_by_call.get(producer)
            == "square_adjacent_vertex_from_side"
            and value.get("return") == "point"
        ):
            value["return"] = "adjacent_vertex"
        for item in value.values():
            _normalize_public_step_results(item, capability_by_call)
    elif isinstance(value, list):
        for item in value:
            _normalize_public_step_results(item, capability_by_call)


def _without_derived_value_types(value):
    if isinstance(value, dict):
        return {
            key: _without_derived_value_types(item)
            for key, item in value.items()
            if key != "value_type"
        }
    if isinstance(value, list):
        return [_without_derived_value_types(item) for item in value]
    return value


def _replace_step_intent(scope, step_id, intent):
    steps = tuple(
        replace(step, intent=intent) if step.step_id == step_id else step
        for step in scope.steps
    )
    goals = tuple(
        replace(
            goal,
            steps=tuple(
                replace(step, intent=intent)
                if step.step_id == step_id
                else step
                for step in goal.steps
            ),
        )
        for goal in scope.goals
    )
    return replace(
        scope,
        steps=steps,
        goals=goals,
        children=tuple(
            _replace_step_intent(child, step_id, intent)
            for child in scope.children
        ),
    )


def _lower_payload(tmp_path, case, payload):
    fixture = scope_native_reconciliation_fixture(tmp_path, case=case)
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
        *_rest,
    ) = fixture
    scoped, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and scoped is not None, report.to_payload()
    authority = ScopedFunctionalPlanAuthorityAdapter().lower(
        scoped,
        planning_context=planning_context,
        binding_catalog=binding_catalog,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )
    return authority, fixture


def _find_scope(scope, scope_ref):
    if scope["scope_ref"] == scope_ref:
        return scope
    for child in scope.get("children", []):
        found = _find_scope(child, scope_ref)
        if found is not None:
            return found
    return None
