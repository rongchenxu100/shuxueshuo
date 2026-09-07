from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    ANNOTATED_TEACHING_PLAN_CONTRACT,
    AnnotatedTeachingPlanProjector,
    AnnotatedTeachingProjectionError,
    TeachingMaterialProjector,
    annotated_teaching_plan_schema,
    build_projection_audit,
    find_forbidden_llm_tokens,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_from_payload,
    iter_teaching_scopes,
    iter_teaching_sources,
)
from shuxueshuo_server.solver.explanation.teaching_specs import (
    TeachingSpecBindingError,
)


ROOT = Path(__file__).resolve().parents[3]
B1_SNAPSHOT = (
    ROOT
    / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
    "heping_ermo_b1/snapshot.json"
)


@pytest.fixture(scope="module")
def snapshot():
    return explanation_snapshot_from_payload(
        json.loads(B1_SNAPSHOT.read_text(encoding="utf-8"))
    )


@pytest.fixture(scope="module")
def projection(snapshot):
    return AnnotatedTeachingPlanProjector().project(snapshot)


def _plan_steps(root_scope):
    result = []

    def visit(scope):
        result.extend(scope.steps)
        for goal in scope.goals:
            result.extend(goal.steps)
        for child in scope.children:
            visit(child)

    visit(root_scope)
    return tuple(result)


def _plan_goals(root_scope):
    result = []

    def visit(scope):
        result.extend(scope.goals)
        for child in scope.children:
            visit(child)

    visit(root_scope)
    return tuple(result)


def test_annotated_plan_is_strict_recursive_projection(snapshot, projection) -> None:
    plan = projection.plan
    payload = plan.to_payload()

    assert plan.schema_version == ANNOTATED_TEACHING_PLAN_CONTRACT
    assert payload["problem"].keys() == {"original_text", "scope_labels"}
    assert len(tuple(iter_teaching_scopes(snapshot.root_scope))) == 5
    assert len(tuple(_plan_goals(plan.root_scope))) == 4
    assert len(tuple(_plan_steps(plan.root_scope))) == 12
    assert sum(
        len(step.teaching_materials) for step in _plan_steps(plan.root_scope)
    ) == 13
    assert projection.diagnostics == ()
    assert projection.authority["diagnostics"] == []

    # The checked-in public Schema must accept the complete projection.
    from jsonschema import Draft202012Validator

    assert not list(
        Draft202012Validator(annotated_teaching_plan_schema()).iter_errors(
            payload
        )
    )
    assert annotated_teaching_plan_schema() == json.loads(
        (
            ROOT
            / "internal/schemas/"
            "functional-annotated-teaching-plan.schema.json"
        ).read_text(encoding="utf-8")
    )


def test_inputs_use_one_exact_ref_and_preserve_all_verified_values(
    snapshot,
    projection,
) -> None:
    sources = {
        item.source_step_id: item
        for item in iter_teaching_sources(snapshot.root_scope)
    }
    steps = {item.step_id: item for item in _plan_steps(projection.plan.root_scope)}

    for step_id, source in sources.items():
        projected = steps[step_id]
        assert set(projected.inputs) == set(source.inputs)
        for arg_name, input_items in source.inputs.items():
            assert isinstance(projected.inputs[arg_name], tuple)
            assert len(projected.inputs[arg_name]) == len(input_items)
            for original, observed in zip(
                input_items,
                projected.inputs[arg_name],
                strict=True,
            ):
                assert "ref" not in observed
                assert "resolved_from" not in observed
                assert observed["type"] == original["runtime_type"]
                assert observed["value"] == original["value"]
                assert observed["display"] == original["display"]

        assert {
            name: {
                "type": value["runtime_type"],
                "value": value["value"],
                "display": value["display"],
            }
            for name, value in source.outputs.items()
        } == projected.outputs


def test_calculations_and_materials_are_student_safe(projection) -> None:
    payload = projection.plan.to_payload()
    serialized = json.dumps(payload, ensure_ascii=False)

    for forbidden_field in (
        "calculation_id",
        "check_id",
        "checks",
        "fact_id",
        "evidence_ref",
        "unit_key",
        "variant_key",
        "resolved_from",
        "output_targets",
        "return_expectations",
    ):
        assert f'"{forbidden_field}"' not in serialized
    assert find_forbidden_llm_tokens(payload) == []

    for step in _plan_steps(projection.plan.root_scope):
        assert step.teaching_materials
        assert all(
            set(material.to_payload())
            == {"title", "nav_title", "goal", "derive", "conclusions"}
            for material in step.teaching_materials
        )
        for calculation in step.calculations:
            assert set(calculation) == {"kind", "value", "display"}
            assert calculation["display"]

    assert "symbolic closure" not in serialized
    assert "一阶导数" not in serialized
    parameter_step = next(
        item
        for item in _plan_steps(projection.plan.root_scope)
        if item.step_id == "solve_parameter_c_ii"
    )
    equation = next(
        item
        for item in parameter_step.calculations
        if item["kind"] == "equation_system"
    )
    assert equation["display"] == ["√5|c+1|/2＝3√5"]

    macro = next(
        item
        for item in _plan_steps(projection.plan.root_scope)
        if item.step_id == "derive_path_minimum_ii"
    )
    assert len(macro.teaching_materials) == 2
    macro_text = json.dumps(
        [item.to_payload() for item in macro.teaching_materials],
        ensure_ascii=False,
    )
    for expected in ("HF+FM+MG＝AG+MG", "G 的轨迹", "A′", "AG=A′G"):
        assert expected in macro_text


def test_verified_answers_match_each_goal_answer_from(projection) -> None:
    steps = {item.step_id: item for item in _plan_steps(projection.plan.root_scope)}
    goals = {item.goal_ref: item for item in _plan_goals(projection.plan.root_scope)}

    assert set(projection.plan.answers) == {"i_1.A", "i_1.P", "i_2.E", "ii.E"}
    for goal_ref, goal in goals.items():
        producer = steps[goal.answer_from["step_id"]]
        output = producer.outputs[goal.answer_from["return"]]
        assert projection.plan.answers[goal_ref] == output
        assert goal.required_answer["runtime_type"] == output["type"]


def test_leaf_scopes_omit_empty_children_from_llm_wire(projection) -> None:
    root = projection.plan.to_payload()["root_scope"]
    assert root["children"]

    def visit(scope):
        children = scope.get("children", ())
        if not children:
            assert "children" not in scope
        for child in children:
            visit(child)

    visit(root)


def test_teaching_step_refs_are_local_ordered_and_cover_each_container(
    projection,
) -> None:
    root = projection.plan.to_payload()["root_scope"]

    def assert_container(steps):
        refs = [
            material["step_ref"]
            for step in steps
            for material in step["materials"]
        ]
        assert refs == [f"s{index}" for index in range(1, len(refs) + 1)]

    def visit(scope):
        assert_container(scope.get("steps", []))
        for steps in scope.get("goals", {}).values():
            assert_container(steps)
        for child in scope.get("children", []):
            visit(child)

    visit(root)


def test_dynamic_output_schema_uses_fixed_scope_and_goal_owners(projection) -> None:
    schema = lesson_scope_content_schema(projection.plan)
    assert schema["required"] == ["i", "i_1", "i_2", "ii"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["i"]["properties"]["steps"]["maxItems"] == 2
    i_1_goals = schema["properties"]["i_1"]["properties"]["goals"]
    assert i_1_goals["required"] == ["i_1.P"]
    assert "i_1.A" not in i_1_goals["properties"]
    assert (
        schema["properties"]["ii"]["properties"]["goals"]["properties"]
        ["ii.E"]["maxItems"]
        == 7
    )
    lesson_step = schema["$defs"]["lesson_step"]
    assert lesson_step["required"] == [
        "source_steps",
        "title",
        "nav_title",
        "goal",
        "derive",
    ]


def test_final_prompt_is_compact_shared_and_contains_exact_plan_once(projection) -> None:
    schema = lesson_scope_content_schema(projection.plan)
    prompt = render_annotated_teaching_prompt(
        projection.plan,
        authority=projection.authority,
        output_schema=schema,
    )
    audit = build_projection_audit(
        projection,
        prompt=prompt,
        output_schema=schema,
    )

    assert prompt.user.count("## 全题型共享示例") == 1
    assert "s1 需要理解的新思考是根据周长建立方程并求参数" in prompt.user
    assert "s2、s3 只是把刚得到的参数代入两个已有对象" in prompt.user
    assert "如果后续材料需要新的几何构造、证明或分支选择" in prompt.user
    assert '"source_steps":["s1","s2","s3"]' in prompt.user
    assert "U(4,8)" in prompt.user
    assert "l：y＝4x＋1" in prompt.user
    assert "中学数学讲解编排器" in prompt.system
    assert "学生步骤的边界应对应一次需要理解的新数学思考" in prompt.system
    assert "而不是一次代码调用" in prompt.system
    assert "是否需要转换思路" in prompt.system
    assert "新的解题策略、定理、几何构造、证明、候选分支判断" in prompt.system
    assert "不需要新的选择或理由" in prompt.system
    assert "存在依赖”本身都不是合并理由" in prompt.system
    assert "而不是压缩数学内容" in prompt.system
    assert "让学生清楚每一步为什么成立、得到什么以及如何衔接下一步" in prompt.system
    assert "只能使用当前 materials 的 derive、calculations 和 conclusions 中已经明确给出的计算" in prompt.system
    assert "不得自行新增代入、化简、方程、坐标计算或数值运算" in prompt.system
    assert "你不需要返回 conclusions 或 box" in prompt.system
    assert "root_scope 仅按真实父子关系递归展示上下文" in prompt.system
    assert "只按同名 scope_ref/goal_ref 填写正文，不要重建 children" in prompt.system
    assert "child Scope 或 sibling Scope 的结果绝不能提前写回" in prompt.system
    assert "初中数学讲解编排器" not in prompt.system
    assert "tj-2026-heping-ermo-25" not in prompt.user
    assert "expected_answers" not in prompt.user
    assert audit["status"] == "ready_for_human_review"
    assert audit["prompt_chars"]["total"] < 54_707
    assert audit["shared_few_shot"] == {
        "count": 1,
        "same_problem": False,
        "mechanism": "student_cognitive_action_boundary",
    }
    assert audit["llm_invoked"] is False
    assert audit["prompt_chars"]["total"] < 14_000
    assert audit["independent_step_refs"] == {
        "goal:i_2.E": ["s1", "s2", "s3"],
        "goal:ii.E": ["s2", "s3", "s7"],
    }
    assert "## 必须独立的教学材料" in prompt.user
    assert "- Goal i_2.E：s1、s2、s3" in prompt.user
    assert "- Goal ii.E：s2、s3、s7" in prompt.user
    assert "requires_independent_lesson_step" not in prompt.user
    assert "AtomicPathMinimumMarker" not in prompt.user
    assert "local_interaction" not in prompt.user
    assert "square_axis_motion" not in prompt.user
    assert "constraint_carriers" not in prompt.user
    assert "show_fixed_endpoint" not in prompt.user
    assert "show_axis_context" not in prompt.user
    plan_json = prompt.user.split("## Annotated Teaching Plan\n\n", 1)[1]
    assert json.loads(plan_json) == projection.plan.to_payload()


def test_projection_fails_loud_on_answer_or_private_identity_mismatch(snapshot) -> None:
    answers = copy.deepcopy(snapshot.answers)
    answers["i_1"]["A"] = ["999", "0"]
    with pytest.raises(
        AnnotatedTeachingProjectionError,
        match="teaching_answer_value_mismatch",
    ):
        AnnotatedTeachingPlanProjector().project(
            replace(snapshot, answers=answers)
        )

    problem = copy.deepcopy(snapshot.problem)
    problem["original_text"] = [
        *problem["original_text"],
        "PathTransformation is a private runtime identity",
    ]
    with pytest.raises(
        AnnotatedTeachingProjectionError,
        match="teaching_private_identity_leak",
    ):
        AnnotatedTeachingPlanProjector().project(
            replace(snapshot, problem=problem)
        )


def test_projection_fails_loud_on_goal_owner_mismatch(snapshot) -> None:
    problem = copy.deepcopy(snapshot.problem)
    goal = next(
        item
        for item in problem["question_goals"]
        if item["handle"] == "answer:i_1.A"
    )
    goal["scope_id"] = "ii"

    with pytest.raises(
        AnnotatedTeachingProjectionError,
        match="teaching_goal_owner_mismatch",
    ):
        AnnotatedTeachingPlanProjector().project(
            replace(snapshot, problem=problem)
        )


class _AlwaysBrokenBinder:
    def generic_spec_payload(self, _source):
        return {"kind": "function"}

    def bind_source_selection(self, *_args, **_kwargs):
        raise TeachingSpecBindingError(
            "teaching_spec_placeholder_unresolved: broken test template"
        )


def test_incomplete_spec_falls_back_to_one_complete_generic_material(snapshot) -> None:
    source = next(iter(iter_teaching_sources(snapshot.root_scope)))
    projector = TeachingMaterialProjector(binder=_AlwaysBrokenBinder())
    result = projector.project(
        source,
        snapshot=snapshot,
        calculations=(),
        checks=(),
    )

    assert len(result.materials) == 1
    assert result.materials[0].suggested_derive
    assert result.materials[0].suggested_box
    assert [item.code for item in result.diagnostics] == [
        "teaching_spec_placeholder_unresolved"
    ]
    assert result.diagnostics[0].fallback == "complete_generic_material"
