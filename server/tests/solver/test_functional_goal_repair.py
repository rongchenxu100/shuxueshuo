from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRepairService,
    FunctionalGoalRetryError,
    FunctionalGoalRetryProjector,
    functional_goal_repair_schema_for_authority,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedPublishedGoalResultRef,
    ScopedFunctionalPlanAuthorityAdapter,
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
from _scoped_functional_plan_support import load_v3_fixture_payload


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


def test_repair_accepts_then_canonicalizes_empty_free_parameters(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    step = next(
        item
        for item in payload["goal_replacements"][FAILED_GOAL_REF]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    step["args"]["free_parameters"] = []

    schema = functional_goal_repair_schema_for_authority(
        fixture.retry_authority,
        capability_catalog=fixture.capability_catalog,
        authority_frame=FunctionalPlanAuthorityFrame.from_planning_context(
            fixture.planning_context
        ),
    )
    quadratic = next(
        item["allOf"][1]["properties"]
        for item in schema["$defs"]["repair_step"]["oneOf"]
        if item["allOf"][1]["properties"]["capability_id"].get("const")
        == "quadratic_from_constraints"
    )
    assert quadratic["args"]["properties"]["free_parameters"]["oneOf"][1][
        "minItems"
    ] == 0

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


def test_repair_omits_optional_empty_maps_before_schema_validation(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    step = payload["goal_replacements"][FAILED_GOAL_REF]["steps"][0]
    step["return_bindings"] = {}
    step["return_expectations"] = {}
    payload["answer_binding_replacements"] = {}

    repair = FunctionalGoalRepairService().parse_json(
        json.dumps(payload, ensure_ascii=False),
        capability_catalog=fixture.capability_catalog,
    )

    normalized_step = repair.goal_replacements[0].steps[0]
    assert "return_bindings" not in normalized_step
    assert "return_expectations" not in normalized_step
    assert repair.answer_binding_replacements == ()
    assert [item.code for item in repair.normalizations] == [
        "functional.empty_optional_step_map_omitted",
        "functional.empty_optional_step_map_omitted",
        "functional.empty_optional_repair_map_omitted",
    ]
    assert [item.path for item in repair.normalizations] == [
        "$.goal_replacements.ii.a.steps[0].return_bindings",
        "$.goal_replacements.ii.a.steps[0].return_expectations",
        "$.answer_binding_replacements",
    ]


def test_repair_canonicalizes_interchangeable_line_endpoint_sources(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    payload["goal_replacements"][FAILED_GOAL_REF]["steps"].insert(
        0,
        {
            "step_id": "derive_axis_point_for_interchange_test",
            "capability_id": "line_parabola_second_intersection_point",
            "args": {
                "parabola": "parabola",
                "line_p1": {
                    "step_id": "anonymous_axis_point",
                    "return": "point",
                },
                "line_p2": "B",
                "known_point": "B",
            },
        },
    )

    repair = FunctionalGoalRepairService().parse_json(
        json.dumps(payload, ensure_ascii=False),
        capability_catalog=fixture.capability_catalog,
    )

    step = repair.goal_replacements[0].steps[0]
    assert step["args"]["line_p1"] == "B"
    assert step["args"]["line_p2"] == {
        "step_id": "anonymous_axis_point",
        "return": "point",
    }
    assert "functional.interchangeable_args_permuted" in {
        item.code for item in repair.normalizations
    }


def test_repair_keeps_required_empty_values_strict(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = repair_payload(fixture)
    payload["goal_replacements"][FAILED_GOAL_REF]["answer_from"] = {}

    with pytest.raises(FunctionalGoalRetryError) as error:
        FunctionalGoalRepairService().parse_json(
            json.dumps(payload, ensure_ascii=False),
            capability_catalog=fixture.capability_catalog,
        )

    assert error.value.code == "functional.goal_repair_schema_invalid"
    assert error.value.path.endswith(".answer_from")


def test_answer_source_changes_when_goal_producer_step_is_replaced(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
    replacement["steps"][-1]["step_id"] = "solve_parameter_replanned_ii"
    replacement["answer_from"]["step_id"] = "solve_parameter_replanned_ii"

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


def test_missing_answer_step_requires_goal_replacement_to_name_new_producer(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
    previous_step_id = replacement["answer_from"]["step_id"]
    replacement["steps"][-1]["step_id"] = "solve_parameter_replanned_ii"
    assert replacement["answer_from"]["step_id"] == previous_step_id
    with pytest.raises(FunctionalGoalRetryError) as caught:
        FunctionalGoalRepairService().apply_json(
            json.dumps(
                repair_payload(fixture, goal_payload=replacement),
                ensure_ascii=False,
            ),
            base_plan=fixture.failed_plan,
            authority=fixture.retry_authority,
            capability_catalog=fixture.capability_catalog,
        )

    assert caught.value.code == "functional.goal_repair_answer_source_invalid"
    assert caught.value.retryable
    assert caught.value.details["goal_ref"] == FAILED_GOAL_REF
    assert caught.value.details["authored_answer_from"] == {
        "step_id": previous_step_id,
        "return": "parameter_value",
    }
    assert caught.value.details["candidate_count"] >= 1
    assert any(
        item["step_id"] == "solve_parameter_replanned_ii"
        for item in caught.value.details["candidates"]
    )


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
        (
            lambda payload: payload.update(
                answer_binding_replacements={
                    "i_1.parabola": {
                        "answer_from": {
                            "step_id": "derive_parabola_i",
                            "return": "parabola",
                        }
                    }
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

    authority = ScopedFunctionalPlanAuthorityAdapter().lower(
        application.plan,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
        capability_catalog=fixture.capability_catalog,
    )
    canonical_bindings = scoped_published_goal_bindings(authority.scoped_plan)
    assert {item.semantic_ref for item in canonical_bindings} == {"parabola"}
    assert all(
        item.producer_step_id == "derive_parabola_i"
        and item.return_name == "parabola"
        for item in canonical_bindings
    )
    canonical_payload = authority.scoped_plan.to_payload()
    canonical_goal = goal(canonical_payload, "i_2.E")
    canonical_consumers = [
        item
        for item in canonical_goal["steps"]
        if item["step_id"]
        in {"derive_x_intercept_B_i", "derive_curve_intersection_E_i"}
    ]
    assert all(item["args"]["parabola"] == "parabola" for item in canonical_consumers)
    assert sum(
        item.action == "canonicalize_published_goal_entity_ref"
        for item in authority.normalizations
    ) == 2
    final_contract = FunctionalPlanContentCompiler().validate_final_plan(
        authority.scoped_plan,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(
            fixture.planning_context
        ),
        capability_catalog=fixture.capability_catalog,
    )
    assert final_contract.ok

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(application.plan.to_payload(), ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        published_goal_bindings=bindings,
    )
    assert execution.authority is not None
    published_goal_id = next(
        item.goal_unit_id
        for item in fixture.planning_context.goal_views
        if item.answer_ref.ref == "i_1.parabola"
    )
    downstream_goal_id = next(
        item.goal_unit_id
        for item in fixture.planning_context.goal_views
        if item.answer_ref.ref == "i_2.E"
    )
    producer = execution.authority.step_authorities["derive_parabola_i"]
    # Publication makes the solved answer visible to the downstream Goal, but
    # it must not rewrite the producer's semantic ownership or placement.
    assert producer.consumer_goal_unit_ids == (published_goal_id,)
    assert producer.semantic_owner_scope_id == "i"
    assert producer.execution_scope_id == "i"
    assert not any(
        item.action == "promote_shared_goal_step_to_scope"
        and item.step_id == "derive_parabola_i"
        for item in execution.authority.normalizations
    )

    reconciliation = execution.replay.functional_reconciliation
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    call_goal_bindings = dict(sidecar.call_goal_bindings)
    call_goal_bindings["derive_parabola_i"] = tuple(
        sorted((published_goal_id, downstream_goal_id))
    )
    publication_reconciliation = replace(
        reconciliation,
        functional_problem_binding_context=replace(
            sidecar,
            call_goal_bindings=call_goal_bindings,
        ),
    )

    publication_authority, publication_report = (
        execution.authority.finalize_reconciliation(
            publication_reconciliation
        )
    )

    assert publication_report.ok
    assert publication_authority is not None
    publication_producer = publication_authority.step_authorities[
        "derive_parabola_i"
    ]
    assert publication_producer.consumer_goal_unit_ids == (
        published_goal_id,
    )
    assert publication_producer.semantic_owner_scope_id == "i"
    assert publication_producer.execution_scope_id == "i"
    assert not any(
        item.action == "promote_shared_goal_step_to_scope"
        and item.step_id == "derive_parabola_i"
        for item in publication_authority.normalizations
    )


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
    correct = load_v3_fixture_payload(case)
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
    correct = load_v3_fixture_payload(case)
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
    checkpoint = execution.checkpoint
    assert checkpoint is not None
    checkpoint_steps = {}

    def collect_steps(scope):
        checkpoint_steps.update(
            (item.step_id, item) for item in scope.scope_steps
        )
        for goal_execution in scope.goals:
            checkpoint_steps.update(
                (item.step_id, item) for item in goal_execution.steps
            )
        for child in scope.children:
            collect_steps(child)

    collect_steps(checkpoint.root_scope)
    sibling_consumer = checkpoint_steps["derive_x_intercept_B_i"]
    assert sibling_consumer.status == "authority_invalid"
    assert sibling_consumer.typed_issue is not None
    assert sibling_consumer.typed_issue["code"] == (
        "functional.arg_state_underdetermined"
    )
    assert "derive_parabola_i" not in sibling_consumer.typed_issue.get(
        "repair_call_ids",
        (),
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
