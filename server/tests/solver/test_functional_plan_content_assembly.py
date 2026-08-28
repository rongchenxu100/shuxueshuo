from __future__ import annotations

from copy import deepcopy

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
    ScopedStepResultRef,
    scoped_functional_plan_authority_payload,
)

from _functional_scope_retry_support import scope_retry_fixture as goal_retry_fixture
from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


def test_content_round_trip_rebuilds_identical_canonical_plan(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and expected is not None
    content = functional_plan_content_from_plan(expected, frame=frame)

    compiled = FunctionalPlanContentCompiler().compile_payload(
        content.to_payload(),
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert compiled.report.ok
    assert compiled.plan is not None
    assert scoped_functional_plan_authority_payload(compiled.plan) == (
        scoped_functional_plan_authority_payload(expected)
    )


def test_content_map_reordering_does_not_change_plan_identity(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and expected is not None
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    reordered = deepcopy(payload)
    reordered["goal_plans"] = dict(
        reversed(tuple(reordered["goal_plans"].items()))
    )
    if "scope_steps" in reordered:
        reordered["scope_steps"] = dict(
            reversed(tuple(reordered["scope_steps"].items()))
        )

    first = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    second = FunctionalPlanContentCompiler().compile_payload(
        reordered,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert first.plan is not None and second.plan is not None
    assert stable_hash(scoped_functional_plan_authority_payload(first.plan)) == (
        stable_hash(scoped_functional_plan_authority_payload(second.plan))
    )


def test_exact_scope_goal_step_copy_is_deduplicated_before_assembly(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and expected is not None
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    goal_ref = "i_2.E"
    owner_scope = frame.goal_owners[goal_ref]
    duplicated = deepcopy(payload["goal_plans"][goal_ref]["steps"][0])
    payload.setdefault("scope_steps", {}).setdefault(owner_scope, []).append(
        duplicated
    )

    compiled = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert compiled.report.ok and compiled.plan is not None
    assert compiled.content is not None
    assert any(
        step["step_id"] == duplicated["step_id"]
        for step in compiled.content.scope_steps[owner_scope]
    )
    assert all(
        step["step_id"] != duplicated["step_id"]
        for step in compiled.content.goal_plans[goal_ref]["steps"]
    )
    assert [
        item.code
        for item in compiled.normalizations
        if item.code == "functional.cross_container_step_duplicate_removed"
    ] == ["functional.cross_container_step_duplicate_removed"]


def test_conflicting_scope_goal_step_copy_fails_with_ownership_details(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and expected is not None
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    goal_ref = "i_2.E"
    owner_scope = frame.goal_owners[goal_ref]
    conflicting = deepcopy(payload["goal_plans"][goal_ref]["steps"][0])
    conflicting["intent"] = "a different authored definition"
    payload.setdefault("scope_steps", {}).setdefault(owner_scope, []).append(
        conflicting
    )

    compiled = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert compiled.plan is None
    assert compiled.report.issues[0].code == "functional.step_id_conflict"
    assert compiled.report.issues[0].details == {
        "step_id": conflicting["step_id"],
        "owners": [f"scope:{owner_scope}", f"goal:{goal_ref}"],
        "paths": [
            f"$.scope_steps.{owner_scope}[0]",
            f"$.goal_plans.{goal_ref}.steps[0]",
        ],
    }


def test_frame_uses_problem_scope_as_root(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )

    assert frame.to_prompt_payload()["root_scope"]["scope_ref"] == "problem"
    assert "root" not in frame.scope_refs
    assert fixture.inputs.problem_id not in frame.scope_refs


def test_same_step_id_with_changed_capability_rederives_return_name(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        load_v2_fixture_payload(case)
    )
    assert report.ok and expected is not None
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture[1])
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    step = next(
        item
        for item in payload["goal_plans"]["ii_1.parabola"]["steps"]
        if item["step_id"] == "ii_1_specialize_parabola"
    )
    step["capability_id"] = "quadratic_from_constraints"
    step["args"] = {}
    step["return_expectations"] = {"parabola": "closed_state"}

    compiled = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            fixture[3].family_spec,
            fixture[3].method_specs,
        ),
    )

    assert compiled.report.ok and compiled.plan is not None
    selected = next(
        item
        for item in compiled.answer_bindings
        if item.goal_ref == "ii_1.parabola"
    )
    assert selected.step_id == "ii_1_specialize_parabola"
    assert selected.return_name == "parabola"
    normalization = next(
        item
        for item in compiled.normalizations
        if item.code == "functional.return_role_normalized"
    )
    assert normalization.path == (
        "$.goal_plans.ii_1.parabola.answer_from.return"
    )


def test_content_assembly_keeps_named_macro_consumer_for_identity_reconciliation(
    tmp_path,
) -> None:
    case = "tj-2026-heping-ermo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        load_v2_fixture_payload(case)
    )
    assert report.ok and expected is not None
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture[1])
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    step = next(
        item
        for item in payload["goal_plans"]["ii.E"]["steps"]
        if item["step_id"] == "derive_path_minimum_ii"
    )
    step.pop("output_targets", None)
    consumer = next(
        item
        for item in payload["goal_plans"]["ii.E"]["steps"]
        if item["step_id"] == "evaluate_minimum_point_G_ii"
    )

    compiled = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            fixture[3].family_spec,
            fixture[3].method_specs,
        ),
    )

    assert compiled.report.ok and compiled.plan is not None
    compiled_consumer = next(
        item
        for item in compiled.plan.steps
        if item.step_id == "evaluate_minimum_point_G_ii"
    )
    assert compiled_consumer.args["point"] == (
        ScopedStepResultRef(
            step_id="derive_path_minimum_ii",
            return_name="attainment_point",
        ),
    )
    compiled_macro = next(
        item
        for item in compiled.plan.steps
        if item.step_id == "derive_path_minimum_ii"
    )
    assert "attainment_point" not in compiled_macro.output_targets


def test_invalid_answer_step_keeps_draft_and_ignores_inactive_returns(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        load_v2_fixture_payload(case)
    )
    assert report.ok and expected is not None
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture[1])
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    minimum_goal = payload["goal_plans"]["ii_1.min_value"]
    parabola_evaluation = deepcopy(
        payload["goal_plans"]["ii_1.parabola"]["steps"][-1]
    )
    parabola_evaluation["step_id"] = "ii_1_unrelated_parabola_evaluation"
    minimum_goal["steps"].append(parabola_evaluation)
    minimum_goal["answer_from"] = {
        "step_id": "missing_answer_producer",
        "return": "evaluated_minimum_expression",
    }

    compiled = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            fixture[3].family_spec,
            fixture[3].method_specs,
        ),
    )

    assert not compiled.report.ok and compiled.plan is not None
    assert compiled.answer_binding_error is not None
    assert compiled.answer_binding_error.goal_ref == "ii_1.min_value"
    assert {
        item.runtime_type for item in compiled.answer_binding_error.candidates
    } == {"MinimumExpression"}
    assert all(
        item.return_name != "evaluated_parabola"
        for item in compiled.answer_binding_error.candidates
    )


def test_authored_answer_from_disambiguates_multiple_valid_returns(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and expected is not None
    payload = functional_plan_content_from_plan(expected, frame=frame).to_payload()
    duplicate = deepcopy(payload["goal_plans"]["ii.a"]["steps"][-1])
    duplicate["step_id"] = "solve_parameter_duplicate_ii"
    payload["goal_plans"]["ii.a"]["steps"].append(duplicate)
    payload["goal_plans"]["ii.a"]["answer_from"] = {
        "step_id": "solve_parameter_duplicate_ii",
        "return": "parameter_value",
    }

    compiled = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert compiled.report.ok and compiled.plan is not None
    selected = next(
        item for item in compiled.answer_bindings if item.goal_ref == "ii.a"
    )
    assert selected.step_id == "solve_parameter_duplicate_ii"
    assert selected.match_basis.startswith("authored_answer_from:")


def test_zero_and_multiple_answer_candidates_return_structured_details(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    expected, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and expected is not None
    base = functional_plan_content_from_plan(expected, frame=frame).to_payload()

    missing = deepcopy(base)
    missing["goal_plans"]["ii.a"]["steps"] = []
    missing_result = FunctionalPlanContentCompiler().compile_payload(
        missing,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    assert missing_result.plan is not None
    assert missing_result.answer_binding_error is not None
    assert missing_result.answer_binding_error.to_feedback_payload()["details"] == {
        "goal_ref": "ii.a",
        "target_ref": "a",
        "answer_type": "ParameterValue",
        "candidate_count": 0,
        "candidates": [],
        "authored_answer_from": base["goal_plans"]["ii.a"]["answer_from"],
    }

    ambiguous = deepcopy(base)
    final_step = deepcopy(ambiguous["goal_plans"]["ii.a"]["steps"][-1])
    final_step["step_id"] = "solve_parameter_duplicate_ii"
    ambiguous["goal_plans"]["ii.a"]["steps"].append(final_step)
    ambiguous["goal_plans"]["ii.a"]["answer_from"] = {
        "step_id": "missing_answer_producer",
        "return": "parameter_value",
    }
    ambiguous_result = FunctionalPlanContentCompiler().compile_payload(
        ambiguous,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    assert ambiguous_result.plan is not None
    assert ambiguous_result.answer_binding_error is not None
    details = ambiguous_result.answer_binding_error.to_feedback_payload()["details"]
    candidate_step_ids = {item["step_id"] for item in details["candidates"]}
    assert details["candidate_count"] == len(details["candidates"])
    assert {
        "solve_parameter_from_minimum_ii",
        "solve_parameter_duplicate_ii",
    } <= candidate_step_ids
    assert details["authored_answer_from"] == {
        "step_id": "missing_answer_producer",
        "return": "parameter_value",
    }
