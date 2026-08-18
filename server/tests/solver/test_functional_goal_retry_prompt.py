from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    functional_goal_repair_schema,
    functional_goal_repair_schema_for_authority,
    planner_goal_retry_context_schema,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    functional_plan_prompt_payload,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)

from _functional_goal_retry_support import (
    FAILED_GOAL_REF,
    goal,
    goal_retry_fixture,
)


ROOT = Path(__file__).resolve().parents[3]


def test_pass1_and_retry_use_independent_templates_and_schemas(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    builder = StrategyPayloadBuilder(scoped_functional_few_shot_examples=[])
    retry_payload = builder.build_goal_repair(
        fixture.inputs,
        previous_plan=fixture.failed_plan,
        retry_authority=fixture.retry_authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    pass1_payload = builder.build_scoped(
        fixture.inputs,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    renderer = StrategyPromptRenderer()
    retry_prompt = renderer.render_goal_repair(retry_payload)
    pass1_prompt = renderer.render_scoped(pass1_payload)

    assert retry_payload["planner_protocol"] == FUNCTIONAL_GOAL_REPAIR_CONTRACT
    assert retry_payload["output_json_schema"] == (
        functional_goal_repair_schema_for_authority(
            fixture.retry_authority
        )
    )
    assert retry_payload["goal_retry_context"]["base_retry_context_id"] == (
        fixture.retry_authority.retry_context_id
    )
    assert "few_shot_examples" not in retry_payload
    assert "functional_few_shot_selection" not in retry_payload
    assert FUNCTIONAL_GOAL_REPAIR_CONTRACT in retry_prompt.system
    assert FUNCTIONAL_GOAL_REPAIR_CONTRACT not in pass1_prompt.system
    assert pass1_payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
    assert "输出完整的 `functional_plan/v2`" not in retry_prompt.system
    assert "same_compiler_selected_object" in retry_prompt.system
    assert "same_compiler_selected_object" in pass1_prompt.system
    assert "共享题面数学实体不等于共享当前数学状态" in retry_prompt.system
    assert "兄弟scope不得直接读取彼此的step" in retry_prompt.system
    assert "题面中有名的Entity始终使用Planner Problem View的SourceRef" in (
        retry_prompt.system
    )
    assert "代码不会根据兄弟使用关系自动发明或移动数学步骤" in (
        retry_prompt.system
    )
    assert "互斥的step所有权容器" in retry_prompt.system
    assert "同一个step完整对象只能在其中一个replacement出现一次" in (
        retry_prompt.system
    )
    assert "不能根据下游Goal希望求哪个参数" in retry_prompt.system
    assert retry_prompt.system != pass1_prompt.system
    authority_bound_fragment = (
        f'"base_retry_context_id":{{"const":"'
        f"{fixture.retry_authority.retry_context_id}" f'"}}'
    )
    assert authority_bound_fragment not in retry_prompt.system
    assert authority_bound_fragment in retry_prompt.user
    assert "## Output JSON Schema" in retry_prompt.user
    combined = f"{retry_prompt.system}\n{retry_prompt.user}"
    for forbidden in (
        "PointRef",
        "StateVersion",
        "MathObjectId",
        "semantic_ref_role",
        "runtime_path",
    ):
        assert forbidden not in combined


def test_retry_schema_is_bound_to_exact_authority(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    schema = functional_goal_repair_schema_for_authority(
        fixture.retry_authority
    )

    assert schema["properties"]["base_plan_id"] == {
        "const": fixture.retry_authority.base_plan_id
    }
    assert schema["properties"]["base_retry_context_id"] == {
        "const": fixture.retry_authority.retry_context_id
    }
    goals = schema["properties"]["goal_replacements"]
    scopes = schema["properties"]["scope_step_replacements"]
    assert goals["required"] == [FAILED_GOAL_REF]
    assert set(goals["properties"]) == {FAILED_GOAL_REF}
    assert goals["additionalProperties"] is False
    assert scopes["required"] == []
    assert scopes["properties"] == {}
    assert scopes["additionalProperties"] is False
    assert "mutually exclusive" in goals["description"]
    assert "Never repeat" in scopes["description"]
    assert "exactly one" in schema["$defs"]["repair_step"]["properties"][
        "step_id"
    ]["description"]


def test_retry_schema_rejects_prior_step_id_from_another_owner(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    schema = functional_goal_repair_schema_for_authority(
        fixture.retry_authority
    )
    replacement = json.loads(
        json.dumps(
            {
                "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                "base_plan_id": fixture.retry_authority.base_plan_id,
                "base_retry_context_id": fixture.retry_authority.retry_context_id,
                "goal_replacements": {
                    FAILED_GOAL_REF: {
                        "steps": [
                            {
                                **fixture.correct_payload["root_scope"][
                                    "children"
                                ][1]["goals"][0]["steps"][0],
                                "step_id": "derive_parabola_i",
                            }
                        ],
                        "answer_from": deepcopy(
                            goal(
                                fixture.correct_payload,
                                FAILED_GOAL_REF,
                            )["answer_from"]
                        ),
                    }
                },
                "scope_step_replacements": {},
            }
        )
    )

    errors = tuple(Draft202012Validator(schema).iter_errors(replacement))
    assert errors
    assert any("derive_parabola_i" in error.message for error in errors)


def test_retry_user_sections_are_ordered_and_previous_plan_occurs_once(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_goal_repair(
        fixture.inputs,
        previous_plan=fixture.failed_plan,
        retry_authority=fixture.retry_authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    prompt = StrategyPromptRenderer().render_goal_repair(payload)
    headings = (
        "## Problem Planning Context",
        "## Strategy Principles",
        "## Functional Capability Catalog",
        "## Output JSON Schema",
        "## Previous Canonical Plan",
        "## Goal Execution And Repair Authority",
    )

    assert [prompt.user.index(item) for item in headings] == sorted(
        prompt.user.index(item) for item in headings
    )
    assert prompt.user.count("## Previous Canonical Plan") == 1
    previous_section = prompt.user.split(
        "## Previous Canonical Plan\n\n",
        1,
    )[1].split(
        "\n\n## Goal Execution And Repair Authority",
        1,
    )[0]
    assert json.loads(previous_section) == functional_plan_prompt_payload(
        fixture.failed_plan
    )
    assert "answer_from" in previous_section
    assert "steps + answer_from" in prompt.system
    assert "显式选择一个满足该权威的可见return" in prompt.system
    assert prompt.user.count(
        '"format":"functional_plan/v2"'
    ) == 1
    assert "few-shot" not in prompt.user.lower()
    assert fixture.retry_authority.retry_context_id in prompt.user
    assert '"authored_step"' not in json.dumps(
        payload["goal_retry_context"],
        ensure_ascii=False,
    )


def test_retry_prompt_builds_stable_cache_prefix_before_dynamic_tail(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_goal_repair(
        fixture.inputs,
        previous_plan=fixture.failed_plan,
        retry_authority=fixture.retry_authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    changed = json.loads(json.dumps(payload))
    changed["output_json_schema"]["title"] = "different repair attempt"
    changed["previous_plan"]["format"] = "different-plan-tail"
    changed["goal_retry_context"]["base_retry_context_id"] = "different-tail"

    renderer = StrategyPromptRenderer()
    original_prompt = renderer.render_goal_repair(payload)
    changed_prompt = renderer.render_goal_repair(changed)
    marker = "## Output JSON Schema"
    original_prefix = original_prompt.user.split(marker, 1)[0]
    changed_prefix = changed_prompt.user.split(marker, 1)[0]

    assert original_prompt.system == changed_prompt.system
    assert original_prefix == changed_prefix
    assert "## Functional Capability Catalog" in original_prefix
    assert "## Previous Canonical Plan" not in original_prefix
    assert fixture.retry_authority.retry_context_id not in (
        f"{original_prompt.system}\n{original_prefix}"
    )


def test_retry_prompt_hides_internal_problem_authority(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_goal_repair(
        fixture.inputs,
        previous_plan=fixture.failed_plan,
        retry_authority=fixture.retry_authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    prompt = StrategyPromptRenderer().render_goal_repair(payload)
    combined = f"{prompt.system}\n{prompt.user}"

    for forbidden in (
        fixture.planning_context.planning_context_id,
        fixture.planning_context.problem_revision_id,
        fixture.planning_context.problem_semantic_hash,
        "source_unit_ids",
        "runtime_node_id",
        "state_version_id",
        "math_object_id",
    ):
        assert forbidden not in combined


def test_retry_schemas_match_checked_in_snapshots() -> None:
    schema_root = ROOT / "internal" / "schemas"
    assert json.loads(
        (schema_root / "functional-goal-repair.schema.json").read_text(
            encoding="utf-8"
        )
    ) == functional_goal_repair_schema()
    assert json.loads(
        (schema_root / "planner-goal-retry-context.schema.json").read_text(
            encoding="utf-8"
        )
    ) == planner_goal_retry_context_schema()


def test_retry_catalog_exposes_second_intersection_geometry_contract(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_goal_repair(
        fixture.inputs,
        previous_plan=fixture.failed_plan,
        retry_authority=fixture.retry_authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    capability = next(
        item
        for item in payload["functional_capability_catalog"]["capabilities"]
        if item["capability_id"]
        == "line_parabola_second_intersection_point"
    )
    args = {item["name"]: item for item in capability["args"]}

    assert "横坐标不同" in args["line_p1"]["role"]
    assert "禁止传入不在目标直线上的点" in args["known_point"]["role"]
    assert any(
        "known_point 不同时位于目标直线和抛物线上" in item
        for item in capability["do_not_use_when"]
    )


def test_retry_catalog_hides_compiler_injected_quadratic_identity(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_goal_repair(
        fixture.inputs,
        previous_plan=fixture.failed_plan,
        retry_authority=fixture.retry_authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    capability = next(
        item
        for item in payload["functional_capability_catalog"]["capabilities"]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    arg_names = {item["name"] for item in capability["args"]}
    parabola_return = next(
        item for item in capability["returns"] if item["name"] == "parabola"
    )

    assert {"quadratic", "parabola", "x", "all_coefficients"}.isdisjoint(
        arg_names
    )
    assert parabola_return["binding"] == "same_compiler_selected_object"
    assert "不得自行放入args" in capability["use_when"]
    assert any(
        "不属于公开args" in item
        for item in capability["do_not_use_when"]
    )
