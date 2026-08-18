from __future__ import annotations

from copy import deepcopy

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
    functional_plan_content_from_plan,
    functional_plan_content_schema,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)

from _functional_goal_retry_support import goal_retry_fixture


def _content_fixture(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and plan is not None
    content = functional_plan_content_from_plan(plan, frame=frame)
    return fixture, frame, content, plan


def test_dynamic_schema_owns_exact_scope_and_goal_keys(tmp_path) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    schema = functional_plan_content_schema(frame)

    assert schema["properties"]["format"] == {
        "const": FUNCTIONAL_PLAN_CONTENT_CONTRACT
    }
    assert set(schema["properties"]["scope_steps"]["properties"]) == {
        item.scope_id for item in fixture.planning_context.scopes
    }
    assert set(schema["properties"]["goal_plans"]["required"]) == {
        item.answer_ref.ref for item in fixture.planning_context.goal_views
    }
    assert not tuple(
        Draft202012Validator(schema).iter_errors(content.to_payload())
    )
    assert set(schema["$defs"]) == {
        "source_ref",
        "step_result_ref",
        "functional_ref",
        "step",
        "answer_from",
    }
    assert all(
        item["required"] == ["answer_from"]
        and "answer_from" in item["properties"]
        for item in schema["properties"]["goal_plans"]["properties"].values()
    )
    assert "mutually exclusive" in schema["properties"]["goal_plans"][
        "description"
    ]
    assert "must not be copied" in schema["properties"]["scope_steps"][
        "description"
    ]
    assert "exactly one ownership container" in schema["$defs"]["step"][
        "properties"
    ]["step_id"]["description"]


def test_every_pass1_goal_requires_answer_from(tmp_path) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    goal_ref = frame.goal_refs[0]
    payload["goal_plans"][goal_ref].pop("answer_from")

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.plan is None
    assert result.report.issues[0].code == (
        "functional.plan_content_schema_invalid"
    )


def test_unknown_or_missing_authority_key_fails_schema(tmp_path) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    compiler = FunctionalPlanContentCompiler()

    unknown = deepcopy(content.to_payload())
    unknown.setdefault("scope_steps", {})["invented"] = [
        deepcopy(next(iter(unknown["scope_steps"].values()))[0])
    ]
    result = compiler.compile_payload(
        unknown,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    assert result.plan is None
    assert result.report.issues
    assert result.report.issues[0].code == "functional.plan_content_schema_invalid"

    missing = deepcopy(content.to_payload())
    missing["goal_plans"].pop(next(iter(frame.goal_refs)))
    result = compiler.compile_payload(
        missing,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    assert result.plan is None
    assert result.report.issues
    assert result.report.issues[0].code == "functional.plan_content_schema_invalid"


def test_empty_optional_step_arrays_are_removed(tmp_path) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    payload.setdefault("scope_steps", {})[frame.scope_refs[0]] = []
    first_goal = frame.goal_refs[0]
    payload["goal_plans"][first_goal]["steps"] = []

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.report.ok
    assert result.content is not None
    assert frame.scope_refs[0] not in result.content.scope_steps
    assert "steps" not in result.content.goal_plans[first_goal]


def test_empty_optional_step_maps_are_omitted_before_schema_validation(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    scope_ref, steps = next(iter(payload["scope_steps"].items()))
    steps[0]["output_targets"] = {}
    steps[0]["return_expectations"] = {}

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.report.ok
    assert result.content is not None
    normalized = result.content.scope_steps[scope_ref][0]
    assert "output_targets" not in normalized
    assert "return_expectations" not in normalized
    assert [item.code for item in result.normalizations] == [
        "functional.empty_optional_step_map_omitted",
        "functional.empty_optional_step_map_omitted",
    ]
    assert [item.path for item in result.normalizations] == [
        f"$.scope_steps.{scope_ref}[0].output_targets",
        f"$.scope_steps.{scope_ref}[0].return_expectations",
    ]


def test_empty_optional_many_capability_arg_is_omitted_before_schema(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    step = next(
        item
        for item in payload["goal_plans"]["ii.a"]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    step["args"]["free_parameters"] = []

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.report.ok
    assert result.content is not None
    normalized_step = next(
        item
        for item in result.content.goal_plans["ii.a"]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    assert "free_parameters" not in normalized_step["args"]
    assert [item.to_payload() for item in result.normalizations] == [
        {
            "code": "functional.empty_optional_capability_arg_omitted",
            "path": (
                "$.goal_plans.ii.a.steps[0].args.free_parameters"
            ),
            "message": (
                "omitted empty optional many-valued capability argument "
                "quadratic_from_constraints.free_parameters"
            ),
        }
    ]


def test_empty_scalar_or_unknown_capability_arg_remains_schema_error(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    compiler = FunctionalPlanContentCompiler()

    scalar = deepcopy(content.to_payload())
    scalar_step = next(
        item
        for item in scalar["goal_plans"]["ii.a"]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    scalar_step["args"]["curve_point"] = []
    result = compiler.compile_payload(
        scalar,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    assert result.plan is None
    assert result.report.issues[0].code == (
        "functional.plan_content_schema_invalid"
    )

    unknown = deepcopy(content.to_payload())
    unknown_step = next(
        item
        for item in unknown["goal_plans"]["ii.a"]["steps"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    unknown_step["args"]["invented"] = []
    result = compiler.compile_payload(
        unknown,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )
    assert result.plan is None
    assert result.report.issues[0].code == (
        "functional.plan_content_schema_invalid"
    )


def test_required_empty_args_is_not_removed_by_content_normalization(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    _scope_ref, steps = next(iter(payload["scope_steps"].items()))
    steps[0]["args"] = {}

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.content is not None
    assert result.content.to_payload()["scope_steps"][_scope_ref][0][
        "args"
    ] == {}
