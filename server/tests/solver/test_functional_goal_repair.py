from __future__ import annotations

from copy import deepcopy
import json

import pytest

from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRepairService,
    FunctionalGoalRetryError,
    FunctionalGoalRetryProjector,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedPublishedGoalResultRef,
    ScopedFunctionalPlanValidator,
    scoped_functional_plan_authority_payload,
    scoped_published_goal_bindings,
)

from _functional_goal_retry_support import (
    FAILED_GOAL_REF,
    goal,
    goal_retry_fixture,
    published_goal_retry_fixture,
    repair_payload,
)
from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


def test_failed_goal_is_replaced_with_code_derived_answer_source(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    application = FunctionalGoalRepairService().apply_json(
        json.dumps(repair_payload(fixture), ensure_ascii=False),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )

    actual = goal(application.plan.to_payload(), FAILED_GOAL_REF)
    expected = goal(fixture.correct_payload, FAILED_GOAL_REF)
    assert actual == expected
    assert application.plan_hash != fixture.retry_authority.base_plan_hash


def test_repair_omits_empty_optional_many_capability_arg(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    step = next(
        item
        for item in payload["goal_replacements"][FAILED_GOAL_REF]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    step["args"]["free_parameters"] = []

    application = FunctionalGoalRepairService().apply_json(
        json.dumps(payload, ensure_ascii=False),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )

    repaired_step = next(
        item
        for item in goal(
            application.plan.to_payload(),
            FAILED_GOAL_REF,
        )["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    assert "free_parameters" not in repaired_step["args"]
    assert [item.code for item in application.normalizations] == [
        "functional.empty_optional_capability_arg_omitted"
    ]
    assert application.normalizations[0].path == (
        "$.goal_replacements.ii.a.steps[0].args.free_parameters"
    )


def test_answer_source_changes_when_goal_producer_step_is_replaced(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
    replacement["steps"][-1]["step_id"] = "solve_parameter_replanned_ii"

    application = FunctionalGoalRepairService().apply_json(
        json.dumps(
            repair_payload(fixture, goal_payload=replacement),
            ensure_ascii=False,
        ),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )

    repaired = goal(application.plan.to_payload(), FAILED_GOAL_REF)
    assert repaired["answer_from"] == {
        "step_id": "solve_parameter_replanned_ii",
        "return": "parameter_value",
    }


def test_repair_authored_answer_from_disambiguates_valid_producers(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
    duplicate = deepcopy(replacement["steps"][-1])
    duplicate["step_id"] = "solve_parameter_alternative_ii"
    replacement["steps"].append(duplicate)
    replacement["answer_from"] = {
        "step_id": "solve_parameter_alternative_ii",
        "return": "parameter_value",
    }

    application = FunctionalGoalRepairService().apply_json(
        json.dumps(
            repair_payload(fixture, goal_payload=replacement),
            ensure_ascii=False,
        ),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )

    repaired = goal(application.plan.to_payload(), FAILED_GOAL_REF)
    assert repaired["answer_from"] == replacement["answer_from"]
    selected = next(
        item
        for item in application.answer_rebindings
        if item.goal_ref == FAILED_GOAL_REF
    )
    assert selected.selected_step_id == "solve_parameter_alternative_ii"
    assert selected.match_basis.startswith("authored_answer_from:")


def test_missing_answer_step_rebinds_by_goal_target_and_typed_return(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
    previous_step_id = replacement["answer_from"]["step_id"]
    replacement["steps"][-1]["step_id"] = "solve_parameter_replanned_ii"
    assert replacement["answer_from"]["step_id"] == previous_step_id
    application = FunctionalGoalRepairService().apply_json(
        json.dumps(
            repair_payload(fixture, goal_payload=replacement),
            ensure_ascii=False,
        ),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )

    repaired = goal(application.plan.to_payload(), FAILED_GOAL_REF)
    assert repaired["answer_from"] == {
        "step_id": "solve_parameter_replanned_ii",
        "return": "parameter_value",
    }
    assert [item.to_payload() for item in application.answer_rebindings] == [
        {
            "goal_ref": FAILED_GOAL_REF,
            "previous_step_id": previous_step_id,
            "previous_return_name": "parameter_value",
            "selected_step_id": "solve_parameter_replanned_ii",
            "selected_return_name": "parameter_value",
            "answer_target_ref": "a",
            "answer_type": "ParameterValue",
            "match_basis": (
                "fallback_from_invalid_authored:"
                "target_identity_goal_terminal"
            ),
        }
    ]


@pytest.mark.parametrize(
    ("payload_update", "code"),
    [
        (
            lambda payload: payload.update(base_plan_id="plan:stale"),
            "functional.goal_repair_stale_plan",
        ),
        (
            lambda payload: payload.update(
                base_retry_context_id="retry-context:stale"
            ),
            "functional.goal_repair_authority_drift",
        ),
        (
            lambda payload: payload["goal_replacements"].update(
                {
                    "i_1.parabola": payload["goal_replacements"].pop(
                        FAILED_GOAL_REF
                    )
                }
            ),
            "functional.goal_repair_boundary_violation",
        ),
    ],
)
def test_stale_or_solved_goal_replacement_fails_loud(
    tmp_path,
    payload_update,
    code,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    payload_update(payload)

    with pytest.raises(FunctionalGoalRetryError) as error:
        FunctionalGoalRepairService().apply_json(
            json.dumps(payload, ensure_ascii=False),
            base_plan=fixture.failed_plan,
            authority=fixture.retry_authority,
            capability_catalog=fixture.capability_catalog,
        )

    assert error.value.code == code


def test_invalid_replacement_is_atomic_and_same_plan_application_is_valid(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    original = fixture.failed_plan.to_payload()
    invalid = repair_payload(fixture)
    invalid["goal_replacements"][FAILED_GOAL_REF]["steps"] = []

    with pytest.raises(FunctionalGoalRetryError):
        FunctionalGoalRepairService().apply_json(
            json.dumps(invalid, ensure_ascii=False),
            base_plan=fixture.failed_plan,
            authority=fixture.retry_authority,
            capability_catalog=fixture.capability_catalog,
        )
    assert fixture.failed_plan.to_payload() == original

    repeated = repair_payload(
        fixture,
        goal_payload=goal(fixture.failed_payload, FAILED_GOAL_REF),
    )
    application = FunctionalGoalRepairService().apply_json(
        json.dumps(repeated, ensure_ascii=False),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )
    assert application.plan.to_payload() == fixture.failed_plan.to_payload()


def test_repair_schema_rejects_full_plan_and_json_patch(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    service = FunctionalGoalRepairService()

    for payload, expected_code in (
        (fixture.correct_payload, "functional.goal_repair_schema_invalid"),
        (
            [{"op": "replace", "path": "/root_scope", "value": {}}],
            "functional.goal_repair_invalid_json",
        ),
    ):
        with pytest.raises(FunctionalGoalRetryError) as error:
            service.parse_json(json.dumps(payload, ensure_ascii=False))
        assert error.value.code == expected_code


def test_replacement_step_ids_cannot_collide_with_retained_plan(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    payload["goal_replacements"][FAILED_GOAL_REF]["steps"][0]["step_id"] = (
        "derive_parabola_i"
    )

    with pytest.raises(FunctionalGoalRetryError) as error:
        FunctionalGoalRepairService().apply_json(
            json.dumps(payload, ensure_ascii=False),
            base_plan=fixture.failed_plan,
            authority=fixture.retry_authority,
            capability_catalog=fixture.capability_catalog,
        )

    assert error.value.code == "functional.goal_repair_step_owner_drift"
    assert "derive_parabola_i" in error.value.message


def test_published_goal_ref_resolves_only_to_solved_final_answer(tmp_path) -> None:
    fixture = published_goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, "i_2.E"))
    for item in replacement["steps"]:
        if item["step_id"] in {
            "derive_x_intercept_B_i",
            "derive_curve_intersection_E_i",
        }:
            item["args"]["parabola"] = {
                "published_goal_ref": "i_1.parabola"
            }
    application = FunctionalGoalRepairService().apply_json(
        json.dumps(
            repair_payload(
                fixture,
                goal_ref="i_2.E",
                goal_payload=replacement,
            ),
            ensure_ascii=False,
        ),
        base_plan=fixture.failed_plan,
        authority=fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
    )

    bindings = scoped_published_goal_bindings(application.plan)
    assert len(bindings) == 2
    assert {item.published_goal_ref for item in bindings} == {"i_1.parabola"}
    assert all(
        isinstance(value, ScopedPublishedGoalResultRef)
        for step in application.plan.steps
        for values in step.args.values()
        for value in values
        if getattr(value, "published_goal_ref", None) is not None
    )
    authority_payload = scoped_functional_plan_authority_payload(
        application.plan
    )
    assert json.dumps(authority_payload).count("published_goal_ref") == 2
    # The normal v2 execution/checkpoint wire remains a standard StepResultRef.
    assert "published_goal_ref" not in json.dumps(application.plan.to_payload())


def test_unpublished_or_intermediate_goal_result_is_rejected(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
    replacement["steps"][0]["args"]["curve_point"] = {
        "published_goal_ref": FAILED_GOAL_REF
    }

    with pytest.raises(FunctionalGoalRetryError) as error:
        FunctionalGoalRepairService().apply_json(
            json.dumps(
                repair_payload(fixture, goal_payload=replacement),
                ensure_ascii=False,
            ),
            base_plan=fixture.failed_plan,
            authority=fixture.retry_authority,
            capability_catalog=fixture.capability_catalog,
        )
    assert error.value.code == "functional.published_goal_result_unavailable"


def test_failed_scope_and_all_consumer_goals_are_replaced_atomically(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    correct = load_v2_fixture_payload(case)
    failed = deepcopy(correct)
    failed_scope = _scope(failed["root_scope"], "i")
    failed_scope["steps"][0]["args"]["curve_points"] = ["not_a_real_ref"]
    failed_plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        failed
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=failed_plan,
        execution=execution,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
    )
    correct_scope = _scope(correct["root_scope"], "i")
    replacement_payload = {
        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
        "base_plan_id": authority.base_plan_id,
        "base_retry_context_id": authority.retry_context_id,
        "goal_replacements": {
            goal_ref: {
                "steps": deepcopy(goal(correct, goal_ref).get("steps", [])),
                "answer_from": deepcopy(
                    goal(correct, goal_ref)["answer_from"]
                ),
            }
            for goal_ref in authority.editable_goal_refs
        },
        "scope_step_replacements": {
            "i": {
                "steps": deepcopy(correct_scope["steps"]),
            }
        },
    }

    application = FunctionalGoalRepairService().apply_json(
        json.dumps(replacement_payload, ensure_ascii=False),
        base_plan=authority.base_plan,
        authority=authority,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            fixture[3].family_spec,
            fixture[3].method_specs,
        ),
    )

    repaired_scope = _scope(application.plan.to_payload()["root_scope"], "i")
    assert repaired_scope == correct_scope


def test_cross_sibling_producer_is_not_semantically_promoted_by_code(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    correct = load_v2_fixture_payload(case)
    failed = deepcopy(correct)
    scope_i = _scope(failed["root_scope"], "i")
    scope_i_1 = _scope(failed["root_scope"], "i_1")
    misplaced = scope_i.pop("steps")[0]
    misplaced["args"] = {
        "curve_points": "point_coordinate_a",
        "free_parameters": "b",
        "target_parameter": "a",
    }
    misplaced["return_expectations"] = {"parabola": "closed_state"}
    scope_i_1["steps"] = [misplaced]
    failed_plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        failed
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=failed_plan,
        execution=execution,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
    )
    assert authority.editable_goal_refs == ("i_1.parabola", "i_2.E")
    assert authority.goal_authorities["i_1.parabola"].status == "failed"
    assert authority.goal_authorities["i_2.E"].status == "failed"
    assert authority.editable_scope_refs == ("i_1",)
    assert authority.repair_step_owners["derive_parabola_i"] == "scope:i_1"
    retry_scope_i_1 = _scope(
        authority.retry_context.to_prompt_payload()["root_scope"],
        "i_1",
    )
    assert "promoted_step_ids" not in retry_scope_i_1
    canonical_i = _scope(authority.base_plan.to_payload()["root_scope"], "i")
    canonical_i_1 = _scope(authority.base_plan.to_payload()["root_scope"], "i_1")
    assert "steps" not in canonical_i
    assert [item["step_id"] for item in canonical_i_1["steps"]] == [
        misplaced["step_id"]
    ]


def _scope(scope_payload, scope_ref):
    if scope_payload["scope_ref"] == scope_ref:
        return scope_payload
    for child in scope_payload.get("children", []):
        found = _scope(child, scope_ref)
        if found is not None:
            return found
    return None
