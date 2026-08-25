from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.runtime.scoped_functional_few_shots import (
    load_scoped_functional_few_shot,
    validate_scoped_functional_few_shot_asset,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    SCOPED_FUNCTIONAL_PLAN_CONTRACT,
    scoped_functional_plan_schema,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    functional_plan_content_schema,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
    _validate_function_facade_coverage,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpec
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)

from _problem_planning_support import scope_native_reconciliation_fixture


FEW_SHOT_DIR = (
    Path(__file__).resolve().parents[3]
    / "internal"
    / "functional-few-shots-v3"
)

PROMPT_CASES = (
    "tj-2026-heping-ermo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-nankai-yimo-25",
    "tj-2026-xiqing-yimo-25",
)

INTERNAL_VIEW_TERMS = (
    "PointRef",
    "StateVersion",
    "MathObjectId",
    "semantic_ref_role",
    "runtime_path",
)


def test_v2_payload_and_prompt_use_scope_native_authority_only(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        problem_payload,
        _registry,
        planner_context,
        binding_catalog,
        _plan,
        _validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_scoped(
        inputs,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        problem_planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
    )
    prompt = StrategyPromptRenderer().render_scoped(payload)

    frame = FunctionalPlanAuthorityFrame.from_planning_context(planning_context)
    full_catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    prompt_catalog = FunctionalCapabilityCatalog(
        {
            item["capability_id"]: full_catalog.items[item["capability_id"]]
            for item in payload["functional_capability_catalog"]["capabilities"]
        }
    )
    assert payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
    assert payload["output_json_schema"] == functional_plan_content_schema(
        frame,
        capability_catalog=prompt_catalog,
    )
    assert "previous_attempt_state" not in payload
    assert payload["authoring_feedback"] == []
    assert payload["problem_planning_context"] == (
        planning_context.to_prompt_payload()
    )
    assert FUNCTIONAL_PLAN_CONTENT_CONTRACT in prompt.system
    assert payload["plan_authority_frame"] == frame.to_prompt_payload()
    assert payload["plan_authority_frame"]["goal_answers"] == {
        goal_ref: {
            "target_ref": requirement.target_ref,
            "answer_type": requirement.answer_type,
        }
        for goal_ref, requirement in sorted(frame.goal_answers.items())
    }
    assert "Scope树与Goal归属完全由Plan Authority Frame拥有" in prompt.system
    assert "planner-problem-view/v2" in prompt.user
    assert "输出不得包含`root_scope`" in prompt.system
    assert "重复的`goal_ref`" in prompt.system
    assert "`goal_ref`不是step输入" in prompt.system
    assert "每个Goal必须输出`answer_from={step_id, return}`" in prompt.system
    assert "public return `type`必须与该Goal的`answer_type`逐字一致" in prompt.system
    assert "合法指针用于消歧" in prompt.system
    assert "共享题面数学实体不等于共享当前数学状态" in prompt.system
    assert "兄弟scope使用不同局部条件" in prompt.system
    assert "互斥的step所有权容器" in prompt.system
    assert "每个step完整对象只能出现一次" in prompt.system
    assert "只为该Goal答案服务的局部推导" in prompt.system
    assert "Entity始终使用字符串SourceRef" in prompt.system
    assert "free_parameters" in prompt.system
    assert "不能根据下游Goal希望求哪个参数" in prompt.system
    assert "只在该scope及其子孙scope可见" in prompt.user
    assert "对当前step的写入scope可见" in prompt.user
    assert "不会把子scope中的`D∈parabola` Fact提升到根scope" in prompt.user
    assert "Full-plan Validation Feedback" in prompt.user
    assert "Authority-bound Output JSON Schema" in prompt.user

    quadratic = next(
        item
        for item in payload["functional_capability_catalog"]["capabilities"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    assert "应用本步骤当前scope约束后" in quadratic["use_when"]
    assert any(
        "不能根据下游Goal希望求哪个参数" in item
        for item in quadratic["do_not_use_when"]
    )

    prompt_problem = payload["problem_planning_context"]
    serialized_problem = json.dumps(prompt_problem, ensure_ascii=False)
    assert '"goal_ref"' in serialized_problem
    assert '"target_ref"' in serialized_problem
    assert '"target"' not in serialized_problem
    assert '"answer_ref"' not in serialized_problem
    assert "copy" in (
        scoped_functional_plan_schema()["$defs"]["goal"]["properties"][
            "goal_ref"
        ]["description"]
    ).lower()

    combined = f"{prompt.system}\n{prompt.user}"
    for forbidden in (
        *INTERNAL_VIEW_TERMS,
        "execution_scope_id",
        "shared_steps",
        "source_unit_ids",
        "runtime_node_id",
        planning_context.planning_context_id,
        planning_context.problem_revision_id,
        planning_context.problem_semantic_hash,
    ):
        assert forbidden not in combined


@pytest.mark.parametrize("case", PROMPT_CASES)
def test_all_five_v2_prompts_hide_internal_input_views(tmp_path, case) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        problem_payload,
        _registry,
        planner_context,
        binding_catalog,
        _plan,
        _validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path / case, case=case)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_scoped(
        inputs,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        problem_planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
    )
    prompt = StrategyPromptRenderer().render_scoped(payload)
    combined = f"{prompt.system}\n{prompt.user}"

    assert all(term not in combined for term in INTERNAL_VIEW_TERMS), case


def test_v2_prompt_renders_only_v2_mechanism_plan(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        problem_payload,
        _registry,
        planner_context,
        binding_catalog,
        _plan,
        _validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(tmp_path)
    example = {
        "annotation": {
            "purpose": "演示单步答案。",
            "use_when": "能力可直接回答目标。",
            "key_idea": "让 Goal 指向 producer return。",
            "do_not_use_when": ["仍需中间推导。"],
        },
        "plan": {
            "format": SCOPED_FUNCTIONAL_PLAN_CONTRACT,
            "root_scope": {
                "scope_ref": "example",
                "goals": [
                    {
                        "goal_ref": "example.answer",
                        "steps": [
                            {
                                "step_id": "solve_answer",
                                "capability_id": "example_capability",
                                "args": {},
                            }
                        ],
                        "answer_from": {
                            "step_id": "solve_answer",
                            "return": "answer",
                        },
                    }
                ],
            },
        },
    }
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[example]
    ).build_scoped(
        inputs,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        problem_planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
    )
    prompt = StrategyPromptRenderer().render_scoped(payload)

    assert '"format":"functional-plan-content/v3"' in prompt.user
    assert '"step_id":"solve_answer"' in prompt.user
    assert '"goal_plans":{"example.answer"' in prompt.user
    assert '"root_scope":{"scope_ref":"example"' not in prompt.user
    assert "functional_plan/v1" not in prompt.user


def test_all_v3_mechanism_assets_are_strict_and_loadable() -> None:
    paths = sorted(FEW_SHOT_DIR.glob("*.functional-few-shot.json"))
    assert len(paths) == 7

    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_scoped_functional_few_shot_asset(payload)
        loaded = load_scoped_functional_few_shot(
            payload["example_id"],
            directory=FEW_SHOT_DIR,
        )
        expected = {
            "annotation": payload["annotation"],
            "plan": payload["plan"],
        }
        if "problem_goal" in payload:
            expected["problem_goal"] = payload["problem_goal"]
        assert loaded == expected

    square = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in paths
        if "square" in path.name
    )
    goals = square["plan"]["root_scope"]["goals"]
    assert {item["goal_ref"] for item in goals} == {
        "example.answer",
        "example.target_point",
    }
    curve = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in paths
        if "curve-candidate" in path.name
    )
    assert curve["problem_goal"] == {
        "goal_ref": "example.answer",
        "kind": "point_coordinate",
        "target_ref": "target_point",
        "answer_type": "Point",
    }


def test_v3_mechanism_assets_do_not_consume_named_outputs_by_step_result() -> None:
    for path in sorted(FEW_SHOT_DIR.glob("*.functional-few-shot.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scopes = [payload["plan"]["root_scope"]]
        steps: list[dict] = []
        while scopes:
            scope = scopes.pop()
            steps.extend(scope.get("steps", []))
            for goal_payload in scope.get("goals", []):
                steps.extend(goal_payload.get("steps", []))
            scopes.extend(scope.get("children", []))

        named_returns = {
            (step["step_id"], return_name): target_ref
            for step in steps
            for return_name, binding in step.get(
                "return_bindings",
                {},
            ).items()
            for target_ref in (binding["ref"],)
        }
        violations: list[tuple[str, str, str, str]] = []
        for consumer in steps:
            pending = list(consumer.get("args", {}).values())
            while pending:
                value = pending.pop()
                if isinstance(value, list):
                    pending.extend(value)
                    continue
                if not isinstance(value, dict):
                    continue
                if set(value) == {"step_id", "return"}:
                    target_ref = named_returns.get(
                        (value["step_id"], value["return"])
                    )
                    if target_ref is not None:
                        violations.append(
                            (
                                consumer["step_id"],
                                value["step_id"],
                                value["return"],
                                target_ref,
                            )
                        )
                    continue
                pending.extend(value.values())

        assert not violations, f"{path.name}: {violations}"


def test_v3_catalog_uses_public_facade_names_with_typed_return_binding_wire(
    tmp_path,
) -> None:
    fixture = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    inputs = fixture[3]
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    intercept = catalog.get("quadratic_x_axis_intercept_point")
    axis_point = catalog.get("quadratic_axis_parameterized_point")
    square = catalog.get("square_adjacent_vertex_from_side")
    assert intercept is not None and axis_point is not None and square is not None
    assert {item.name for item in intercept.args} >= {"parabola"}
    assert "quadratic" not in {item.name for item in intercept.args}
    assert intercept.source.adapter is not None
    assert dict(intercept.source.adapter.functional_input_names) == {
        "quadratic": "parabola"
    }
    assert [item.name for item in square.returns] == ["adjacent_vertex"]
    assert square.source.adapter is not None
    assert dict(square.source.adapter.functional_output_names) == {
        "point": "adjacent_vertex"
    }
    point_return = next(
        item for item in axis_point.returns if item.name == "point"
    )
    assert point_return.output_target_selector is not None
    assert point_return.to_prompt_payload()["target_selection"] == {
        "policy": "unique_visible_fact_target",
        "fact_kind": "axis_membership",
        "target_field": "point",
        "related_arg": "parabola",
        "related_field": "curve",
        "required_fields": {"axis": "symmetry"},
        "description": point_return.output_target_selector.description,
    }
    prompt_catalog = catalog.to_prompt_payload()
    assert '"scope_binding"' in json.dumps(
        prompt_catalog,
        ensure_ascii=False,
    )

    method = inputs.method_specs.require(
        "quadratic_x_axis_intercept_point"
    )
    assert isinstance(intercept.source, FunctionSpec)
    with pytest.raises(
        ValueError,
        match="functional.capability_contract_invalid.*missing_inputs",
    ):
        _validate_function_facade_coverage(
            intercept.source,
            method_spec=method,
            public_args=tuple(
                item
                for item in intercept.args
                if item.runtime_input != "quadratic"
            ),
            auto_args=intercept.auto_args,
            returns=intercept.returns,
        )


def test_scoped_builder_selects_v2_example_without_v1_plan_projection(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        problem_payload,
        _registry,
        planner_context,
        binding_catalog,
        _plan,
        _validation,
        _reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-xiqing-yimo-25",
    )
    payload = StrategyPayloadBuilder().build_scoped(
        inputs,
        problem_payload=problem_payload,
        planner_state_context=planner_context,
        problem_planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
    )

    assert len(payload["few_shot_examples"]) == 1
    assert (
        payload["few_shot_examples"][0]["plan"]["format"]
        == SCOPED_FUNCTIONAL_PLAN_CONTRACT
    )
    assert payload["functional_few_shot_selection"]["mode"] == (
        "v3_capability_subset"
    )


def test_v2_catalog_marks_problem_object_identity_args(tmp_path) -> None:
    fixture = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-hexi-yimo-25",
    )
    inputs = fixture[3]
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    candidates = catalog.get("right_angle_equal_length_candidates")
    selector = catalog.get("curve_candidate_parameter_solve")
    assert candidates is not None and selector is not None
    candidate_target = next(
        item for item in candidates.args if item.name == "target"
    )
    selector_target = next(
        item for item in selector.args if item.name == "target_point"
    )
    for item in (candidate_target, selector_target):
        prompt_arg = item.to_prompt_payload()
        assert prompt_arg["domain_type"] == "Point"
        assert "semantic_ref_role" not in prompt_arg
        assert prompt_arg["role"]
        assert "PointRef" not in prompt_arg["role"]
        assert "target_ref" not in prompt_arg["role"]
        assert "goal_ref" not in prompt_arg["role"]

    value_arg = next(item for item in selector.args if item.name == "parabola")
    value_prompt = value_arg.to_prompt_payload()
    assert value_prompt["domain_type"] == "QuadraticFunction"
    assert "semantic_ref_role" not in value_prompt


def test_v2_catalog_declares_return_expectation_policy_per_return(tmp_path) -> None:
    fixture = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    inputs = fixture[3]
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    quadratic = catalog.get("quadratic_from_constraints")
    parameter_solver = catalog.get("parameter_from_expression_value")
    assert quadratic is not None and parameter_solver is not None
    open_parameter = next(
        item for item in quadratic.returns if item.name == "parameter_value"
    )
    fixed_parameter = next(
        item
        for item in parameter_solver.returns
        if item.name == "parameter_value"
    )

    assert open_parameter.runtime_type == fixed_parameter.runtime_type
    assert open_parameter.return_expectation_policy == "selectable"
    assert open_parameter.to_prompt_payload()["possible_forms"] == [
        "open_state",
        "closed_state",
    ]
    assert fixed_parameter.return_expectation_policy == "omit"
    assert fixed_parameter.to_prompt_payload() == {
        "name": "parameter_value",
        "type": "ParameterValue",
        "binding": "same_object_as:parameter",
        "scope_binding": {"mode": "existing_only"},
    }

    schema = functional_plan_content_schema(
        FunctionalPlanAuthorityFrame.from_planning_context(fixture[1])
    )
    point_list_goal = schema["properties"]["goal_plans"]["properties"][
        "i_2.E"
    ]
    assert "targets 'E'" in point_list_goal["description"]
    assert "canonical type 'PointList'" in point_list_goal["description"]
    assert "must be 'PointList'" in point_list_goal["properties"][
        "answer_from"
    ]["description"]

    for capability in catalog.to_prompt_payload()["capabilities"]:
        for returned in capability["returns"]:
            if returned.get("possible_forms"):
                assert returned["return_expectation_policy"] == "selectable"
            else:
                assert "return_expectation_policy" not in returned
