from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
    functional_plan_content_from_plan,
    functional_plan_content_schema,
    normalize_interchangeable_capability_args,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
    referenced_functional_step_returns,
    unconsumed_duplicate_identity_arg_omissions,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)

from _functional_scope_retry_support import scope_retry_fixture as goal_retry_fixture
from _problem_planning_support import planning_binding_fixture


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


def _content_step(payload: dict, step_id: str) -> dict:
    for steps in payload.get("scope_steps", {}).values():
        for item in steps:
            if item["step_id"] == step_id:
                return item
    for goal_plan in payload["goal_plans"].values():
        for item in goal_plan.get("steps", []):
            if item["step_id"] == step_id:
                return item
    raise AssertionError(f"missing content step {step_id!r}")


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


def test_dynamic_schema_binds_output_and_expectation_roles_per_capability(
    tmp_path,
) -> None:
    fixture, frame, _content, _plan = _content_fixture(tmp_path)
    schema = functional_plan_content_schema(
        frame,
        capability_catalog=fixture.capability_catalog,
    )
    variants = schema["$defs"]["step"]["oneOf"]
    by_capability = {
        item["allOf"][1]["properties"]["capability_id"]["const"]: item[
            "allOf"
        ][1]["properties"]
        for item in variants
    }

    assert set(by_capability) == set(fixture.capability_catalog.items)
    for capability_id, capability in fixture.capability_catalog.items.items():
        properties = by_capability[capability_id]
        output_schema = properties["output_targets"]
        expectation_schema = properties["return_expectations"]
        assert expectation_schema["additionalProperties"] is False
        public_return_names = {
            item.name
            for item in capability.returns
            if item.binding_mode != "internal_only"
        }
        if output_schema is False:
            target_names = set()
        else:
            assert output_schema["additionalProperties"] is False
            target_names = set(output_schema["properties"])
            assert all(
                item["enum"]
                for item in output_schema["properties"].values()
            )
            assert all(
                set(item["enum"])
                <= {
                    ref
                    for values in frame.source_ref_domain_types.values()
                    for ref in values
                }
                for item in output_schema["properties"].values()
            )
        assert target_names <= public_return_names
        assert set(expectation_schema["properties"]) == {
            item.name
            for item in capability.returns
            if item.possible_forms
            and item.return_expectation_policy != "omit"
        }
        for returned in capability.returns:
            if (
                returned.possible_forms
                and returned.return_expectation_policy != "omit"
            ):
                assert expectation_schema["properties"][returned.name][
                    "enum"
                ] == list(returned.possible_forms)

    quadratic_targets = by_capability["quadratic_from_constraints"][
        "output_targets"
    ]
    assert "coefficients" not in quadratic_targets["properties"]
    assert any(
        properties["output_targets"] is False
        for properties in by_capability.values()
    )


def test_output_target_schema_honors_structural_fact_selector(tmp_path) -> None:
    nankai = planning_binding_fixture(
        tmp_path / "nankai",
        case="tj-2026-nankai-yimo-25",
    )
    nankai_frame = FunctionalPlanAuthorityFrame.from_planning_context(
        nankai[1]
    )
    nankai_catalog = FunctionalCapabilityCatalog.from_family_spec(
        nankai[3].family_spec,
        nankai[3].method_specs,
    )
    nankai_schema = functional_plan_content_schema(
        nankai_frame,
        capability_catalog=nankai_catalog,
    )
    nankai_point_at_x = next(
        item["allOf"][1]["properties"]
        for item in nankai_schema["$defs"]["step"]["oneOf"]
        if item["allOf"][1]["properties"]["capability_id"].get("const")
        == "point_on_parabola_at_x"
    )

    # M has a complete point_coordinate Fact, not a curve_at_x construction.
    # It is already a Point state and must not be offered as this Method's
    # output target merely because both values have runtime type Point.
    assert nankai_point_at_x["output_targets"] is False

    hexi = planning_binding_fixture(
        tmp_path / "hexi",
        case="tj-2026-hexi-yimo-25",
    )
    hexi_frame = FunctionalPlanAuthorityFrame.from_planning_context(hexi[1])
    hexi_catalog = FunctionalCapabilityCatalog.from_family_spec(
        hexi[3].family_spec,
        hexi[3].method_specs,
    )
    hexi_schema = functional_plan_content_schema(
        hexi_frame,
        capability_catalog=hexi_catalog,
    )
    hexi_point_at_x = next(
        item["allOf"][1]["properties"]
        for item in hexi_schema["$defs"]["step"]["oneOf"]
        if item["allOf"][1]["properties"]["capability_id"].get("const")
        == "point_on_parabola_at_x"
    )
    assert hexi_point_at_x["output_targets"]["properties"]["point"][
        "enum"
    ] == ["M"]


def test_distinct_symbol_roles_are_schema_checked_after_safe_normalization(
    tmp_path,
) -> None:
    fixture, frame, content, _plan = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    step = _content_step(payload, "derive_parametric_parabola_ii")
    step["args"]["target_parameter"] = "a"
    step["return_expectations"] = {
        **step.get("return_expectations", {}),
        "parameter_value": "closed_state",
    }
    schema = functional_plan_content_schema(
        frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert tuple(Draft202012Validator(schema).iter_errors(payload))

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.report.ok
    assert result.plan is not None
    canonical = next(
        item
        for item in result.plan.steps
        if item.step_id == "derive_parametric_parabola_ii"
    )
    assert "target_parameter" not in canonical.args
    assert "parameter_value" not in canonical.return_expectations
    assert {
        item.code for item in result.normalizations
    } >= {
        "functional.unconsumed_duplicate_identity_arg_omitted",
        "functional.inactive_return_expectation_omitted",
    }


def test_consumed_duplicate_identity_arg_is_left_for_typed_reconciliation(
    tmp_path,
) -> None:
    fixture, frame, content, _plan = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    step = _content_step(payload, "derive_parametric_parabola_ii")
    step["args"]["target_parameter"] = "a"
    payload["goal_plans"]["ii.a"]["answer_from"] = {
        "step_id": "derive_parametric_parabola_ii",
        "return": "parameter_value",
    }

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.draft_only
    assert result.plan is not None
    assert {
        item.code for item in result.report.issues
    } == {"functional.plan_content_schema_invalid"}
    assert "functional.arg_distinctness_violation" not in {
        item.code for item in result.report.issues
    }
    assert "functional.unconsumed_duplicate_identity_arg_omitted" not in {
        item.code for item in result.normalizations
    }


def test_identity_arg_omission_is_name_agnostic_and_consumer_aware(
    tmp_path,
) -> None:
    fixture, _frame, _content, _plan = _content_fixture(tmp_path)
    capability = fixture.capability_catalog.get("quadratic_from_constraints")
    assert capability is not None
    renamed = replace(
        capability,
        args=tuple(
            replace(item, name="chosen_symbol")
            if item.name == "target_parameter"
            else item
            for item in capability.args
        ),
        returns=tuple(
            replace(item, identity_arg="chosen_symbol")
            if item.identity_arg == "target_parameter"
            else item
            for item in capability.returns
        ),
        distinct_arg_groups=tuple(
            tuple(
                "chosen_symbol" if name == "target_parameter" else name
                for name in group
            )
            for group in capability.distinct_arg_groups
        ),
    )
    args = {"chosen_symbol": "a", "free_parameters": ["a"]}

    omissions = unconsumed_duplicate_identity_arg_omissions(
        step_id="derive",
        capability=renamed,
        args=args,
        output_targets={},
        consumed_returns=frozenset(),
    )
    assert [(item.arg_name, item.return_names) for item in omissions] == [
        ("chosen_symbol", ("parameter_value",))
    ]

    consumer_payload = {
        "answer_from": {"step_id": "derive", "return": "parameter_value"},
        "nested": [
            {"args": {"value": {"step_id": "other", "return": "point"}}}
        ],
    }
    consumers = referenced_functional_step_returns(consumer_payload)
    assert consumers == frozenset(
        {("derive", "parameter_value"), ("other", "point")}
    )
    assert not unconsumed_duplicate_identity_arg_omissions(
        step_id="derive",
        capability=renamed,
        args=args,
        output_targets={},
        consumed_returns=consumers,
    )
    assert not unconsumed_duplicate_identity_arg_omissions(
        step_id="derive",
        capability=renamed,
        args=args,
        output_targets={"parameter_value": "a"},
        consumed_returns=frozenset(),
    )


def test_line_intersection_schema_allows_anonymous_points_on_both_lines(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path / "nankai",
        case="tj-2026-nankai-yimo-25",
    )
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture[1])
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    )
    schema = functional_plan_content_schema(
        frame,
        capability_catalog=catalog,
    )
    variant = next(
        item["allOf"][1]["properties"]
        for item in schema["$defs"]["step"]["oneOf"]
        if item["allOf"][1]["properties"]["capability_id"].get("const")
        == "line_intersection_point"
    )

    for name in ("line1_p1", "line1_p2", "line2_p1", "line2_p2"):
        assert variant["args"]["properties"][name]["oneOf"] == [
            {"$ref": "#/$defs/source_ref"},
            {"$ref": "#/$defs/step_result_ref"},
        ]


def test_line_parabola_schema_and_canonicalizer_treat_line_endpoints_symmetrically(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path / "heping",
        case="tj-2026-heping-yimo-25",
    )
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture[1])
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    )
    schema = functional_plan_content_schema(
        frame,
        capability_catalog=catalog,
    )
    variant = next(
        item["allOf"][1]["properties"]
        for item in schema["$defs"]["step"]["oneOf"]
        if item["allOf"][1]["properties"]["capability_id"].get("const")
        == "line_parabola_second_intersection_point"
    )
    expected_ref_schema = [
        {"$ref": "#/$defs/source_ref"},
        {"$ref": "#/$defs/step_result_ref"},
    ]
    assert variant["args"]["properties"]["line_p1"]["oneOf"] == (
        expected_ref_schema
    )
    assert variant["args"]["properties"]["line_p2"]["oneOf"] == (
        expected_ref_schema
    )

    payload = {
        "capability_id": "line_parabola_second_intersection_point",
        "args": {
            "parabola": "parabola",
            "line_p1": {"step_id": "derive_axis_point", "return": "point"},
            "line_p2": "B",
            "known_point": "B",
        },
    }
    normalized, records = normalize_interchangeable_capability_args(
        payload,
        capability_catalog=catalog,
    )

    assert normalized["args"]["line_p1"] == "B"
    assert normalized["args"]["line_p2"] == {
        "step_id": "derive_axis_point",
        "return": "point",
    }
    assert [item.code for item in records] == [
        "functional.interchangeable_args_permuted"
    ]
    capability = catalog.get("line_parabola_second_intersection_point")
    assert capability is not None
    assert capability.interchangeable_arg_groups == (("line_p1", "line_p2"),)
    assert any(
        "交换它们不改变数学结果" in item["requirement"]
        for item in capability.to_prompt_payload()["input_requirements"]
    )


def test_final_canonical_plan_contract_round_trip_preserves_identity(
    tmp_path,
) -> None:
    fixture, frame, _, plan = _content_fixture(tmp_path)

    result = FunctionalPlanContentCompiler().validate_final_plan(
        plan,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.ok
    assert result.report.ok
    assert result.final_plan_id == result.round_trip_plan_id
    assert result.content is not None
    assert result.to_payload()["schema_version"] == (
        "functional-final-plan-contract-validation/v1"
    )


def test_missing_final_plan_fails_final_contract(tmp_path) -> None:
    fixture, frame, _, _ = _content_fixture(tmp_path)

    result = FunctionalPlanContentCompiler().validate_final_plan(
        None,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert not result.ok
    assert result.final_plan_id is None
    assert result.report.issues[0].code == "functional.final_plan_missing"


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


def test_capability_bound_schema_normalizes_named_entity_step_result(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    valid = content.to_payload()
    schema = functional_plan_content_schema(
        frame,
        capability_catalog=fixture.capability_catalog,
    )

    # Anonymous expression results remain valid StepResultRefs.
    expression = _content_step(
        valid,
        "solve_parameter_from_minimum_ii",
    )["args"]["expression"]
    assert expression == {
        "step_id": "reduce_equal_length_ray_path_ii",
        "return": "minimum_expression",
    }
    assert not tuple(Draft202012Validator(schema).iter_errors(valid))

    invalid = deepcopy(valid)
    _content_step(invalid, "derive_x_intercept_B_i")["args"][
        "parabola"
    ] = {
        "step_id": "derive_parabola_i",
        "return": "parabola",
    }
    result = FunctionalPlanContentCompiler().compile_payload(
        invalid,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.report.ok and result.plan is not None
    assert result.content is not None
    assert _content_step(
        result.content.to_payload(), "derive_x_intercept_B_i"
    )["args"]["parabola"] == "parabola"
    assert [item.code for item in result.normalizations] == [
        "functional.named_entity_result_ref_normalized"
    ]


def test_content_compiler_normalizes_unique_public_return_role(tmp_path) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    expression = _content_step(
        payload, "solve_parameter_from_minimum_ii"
    )["args"]["expression"]
    expression["return"] = "point"

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.report.ok and result.content is not None
    assert _content_step(
        result.content.to_payload(), "solve_parameter_from_minimum_ii"
    )["args"]["expression"] == {
        "step_id": "reduce_equal_length_ray_path_ii",
        "return": "minimum_expression",
    }
    assert any(
        item.code == "functional.return_role_normalized"
        for item in result.normalizations
    )


def test_content_return_role_error_keeps_precise_public_diagnostic(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    payload = deepcopy(content.to_payload())
    reduction = _content_step(payload, "reduce_equal_length_ray_path_ii")
    reduction["return_expectations"] = {"point": "closed_state"}

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.draft_only
    issue = result.report.issues[0]
    assert issue.code == "functional.step_contract_invalid"
    assert issue.details["capability_id"] == "equal_length_ray_path_reduction"
    assert issue.details["observed_role"] == "point"
    assert issue.details["observed_form"] == "closed_state"
    assert issue.details["expected_roles"] == ["minimum_expression"]
    assert issue.details["repair_action"] == "repair_return_role"


def test_exact_selector_normalizes_named_result_with_same_type_decoy(
    tmp_path,
) -> None:
    fixture, frame, content, _ = _content_fixture(tmp_path)
    source_types = {
        scope_id: dict(values)
        for scope_id, values in frame.source_ref_domain_types.items()
    }
    source_types["problem"]["second_parabola"] = "QuadraticFunction"
    frame = replace(frame, source_ref_domain_types=source_types)
    payload = deepcopy(content.to_payload())
    _content_step(payload, "derive_x_intercept_B_i")["args"][
        "parabola"
    ] = {
        "step_id": "derive_parabola_i",
        "return": "parabola",
    }

    result = FunctionalPlanContentCompiler().compile_payload(
        payload,
        frame=frame,
        capability_catalog=fixture.capability_catalog,
    )

    assert result.plan is not None
    assert result.content is not None
    assert result.draft_only is False
    assert result.report.ok
    assert _content_step(
        result.content.to_payload(), "derive_x_intercept_B_i"
    )["args"]["parabola"] == "parabola"
    assert [item.code for item in result.normalizations] == [
        "functional.named_entity_result_ref_normalized"
    ]


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


def test_free_parameters_empty_array_is_wire_valid_then_canonicalized(
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

    schema = functional_plan_content_schema(
        frame,
        capability_catalog=fixture.capability_catalog,
    )
    quadratic = next(
        item["allOf"][1]["properties"]
        for item in schema["$defs"]["step"]["oneOf"]
        if item["allOf"][1]["properties"]["capability_id"].get("const")
        == "quadratic_from_constraints"
    )
    free_parameters_schema = quadratic["args"]["properties"][
        "free_parameters"
    ]
    assert free_parameters_schema["oneOf"][1]["minItems"] == 0
    assert not tuple(Draft202012Validator(schema).iter_errors(payload))

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


def test_empty_scalar_remains_error_but_surplus_unknown_arg_is_omitted(
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
    assert result.plan is not None
    assert result.report.ok
    assert any(
        item.code == "functional.unknown_capability_arg_omitted"
        and item.path.endswith(".args.invented")
        for item in result.normalizations
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
