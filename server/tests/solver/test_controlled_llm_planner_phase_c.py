"""Phase C 受控 LLM Planner 组件测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.context_inventory import ContextInventoryBuilder
from shuxueshuo_server.solver.runtime.controlled_llm_planner import (
    AbstractPlanValidationError,
    AbstractPlanValidator,
    ControlledLLMPlanner,
    FewShotExampleLoader,
    PlanCompiler,
    PlanningPayloadBuilder,
    PlanningPromptRenderer,
    SlotBinder,
    parse_planner_draft,
    summarize_slot_options,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import PlannerOutput
from shuxueshuo_server.solver.runtime.planner import PlannerInputs
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"


class _DraftClient:
    """测试用 LLM client，直接返回预设 draft JSON。"""

    def __init__(self, response: str) -> None:
        self.response = response
        self.payloads: list[dict[str, Any]] = []

    def complete(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        return self.response


class _CountingSlotBinder(SlotBinder):
    """统计 build 调用次数，防止 ControlledLLMPlanner 重复枚举候选。"""

    def __init__(self) -> None:
        self.build_calls = 0

    def build(self, *, method_specs, context_inventory):
        self.build_calls += 1
        return super().build(
            method_specs=method_specs,
            context_inventory=context_inventory,
        )


class _CountingValidator(AbstractPlanValidator):
    """统计 validate 调用次数，确保 ControlledLLMPlanner 不重复校验 draft。"""

    def __init__(self) -> None:
        self.validate_calls = 0

    def validate(self, draft, inputs, slot_options) -> None:
        self.validate_calls += 1
        super().validate(draft, inputs, slot_options)


def _planner_inputs(fixture: str = NANKAI_FIXTURE) -> PlannerInputs:
    """构造 Phase C 测试使用的 PlannerInputs。"""
    problem = load_problem_ir(fixture)
    context = ContextBuilder().build(problem)
    specs = MethodSpecRegistry.load_from_code()
    family = DEFAULT_FAMILY_REGISTRY.match(problem)
    assert family is not None
    return PlannerInputs(
        problem_id=problem.problem_id,
        family_spec=family,
        question_goals=extract_question_goals(problem),
        context_inventory=ContextInventoryBuilder().build(context, specs),
        method_specs=specs,
    )


def _candidate_id(
    slot_options,
    *,
    method_id: str,
    input_name: str,
    path: str,
) -> str:
    """按 path 反查某个 slot candidate id。"""
    for option in slot_options:
        if option.method_id != method_id or option.input_name != input_name:
            continue
        for candidate in option.candidates:
            if candidate.path == path:
                return candidate.candidate_id
    raise AssertionError(f"candidate not found for {method_id}.{input_name}: {path}")


def _axis_draft(inputs: PlannerInputs) -> dict[str, Any]:
    """构造一条合法的“求对称轴交点” controlled draft。"""
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    method_id = "quadratic_axis_from_relation"
    return {
        "context_declarations": [],
        "steps": [
            {
                "step_id": "derive_D",
                "scope_id": "problem",
                "step_goal": {
                    "type": "derive_axis_point",
                    "target_path": "$problem.points.D",
                    "value_type": "Point",
                    "description": "由系数关系求对称轴与 x 轴交点",
                },
                "method_id": method_id,
                "bindings": {
                    "coefficient_relation": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="coefficient_relation",
                        path="$problem.equations.coefficient_relation",
                    ),
                    "a": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="a",
                        path="$problem.symbols.a",
                    ),
                    "b": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="b",
                        path="$problem.symbols.b",
                    ),
                    "target": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="target",
                        path="$problem.points.D",
                    ),
                },
                "promote_to": {"axis_point": "$problem.points.D"},
                "depends_on": [],
                "reason": "题设给出 2a+b=0，可先求对称轴上的点。",
            }
        ],
    }


def test_payload_builder_contains_controlled_context_without_expected_answers() -> None:
    """payload 应包含 planner 所需索引，但不能夹带测试期望答案。"""
    inputs = _planner_inputs()

    payload = PlanningPayloadBuilder().build(inputs)
    payload_text = json.dumps(payload, ensure_ascii=False)

    assert payload["family_spec"]["family_id"] == inputs.family_spec.family_id
    assert payload["question_goals"]
    assert payload["planning_signals"]
    assert payload["relation_graph"]
    assert payload["visible_paths"]
    assert payload["method_candidates"]
    assert payload["slot_options"]
    assert payload["output_json_schema"]["required"] == ["context_declarations", "steps"]
    assert payload["few_shot_examples"]
    assert "expected_answers" not in payload_text
    assert "expected_answer" not in payload_text


def test_prompt_renderer_injects_schema_binding_rules_and_few_shots() -> None:
    """Jinja prompt 应显式告诉模型 schema、候选绑定规则和禁止事项。"""
    payload = PlanningPayloadBuilder().build(_planner_inputs())

    prompt = PlanningPromptRenderer().render(payload)

    assert '"context_declarations"' in prompt.system
    assert '"definition_intent"' in prompt.system
    assert "candidate_id" in prompt.system
    assert "禁止写 ContextPath" in prompt.system
    assert "few-shot" in prompt.user
    assert "few-shot 是语义模板" in prompt.user
    assert "不能照抄这些字段名" in prompt.user
    assert "step_goal.target_path" in prompt.user
    assert "QuadraticPathMinimumSolver" in prompt.user


def test_few_shot_loader_only_uses_same_family_and_limit() -> None:
    """few-shot 示例按 family_id 过滤，且不暴露 expected answer 字段。"""
    path_inputs = _planner_inputs(NANKAI_FIXTURE)
    weighted_inputs = _planner_inputs(HEXI_FIXTURE)
    loader = FewShotExampleLoader(limit=3)

    path_examples = loader.load_for_family(path_inputs.family_spec.family_id)
    weighted_examples = loader.load_for_family(weighted_inputs.family_spec.family_id)

    assert path_examples
    assert weighted_examples
    assert all(item["family_id"] == path_inputs.family_spec.family_id for item in path_examples)
    assert all(item["family_id"] == weighted_inputs.family_spec.family_id for item in weighted_examples)
    assert len(path_examples) <= 3
    assert "expected_answer" not in json.dumps(path_examples, ensure_ascii=False).lower()
    assert path_examples[0]["draft_steps"]
    assert any(
        "bindings" in step and step["bindings"]
        for step in path_examples[0]["draft_steps"]
    )
    assert any(
        "promote_to" in step
        for step in path_examples[0]["draft_steps"]
    )


def test_slot_binder_generates_stable_candidates_and_allows_pointref_for_point() -> None:
    """candidate id 多次构建应稳定；Point 输入允许绑定可解析的 PointRef。"""
    inputs = _planner_inputs()
    binder = SlotBinder()

    first = binder.build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    second = binder.build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )

    assert summarize_slot_options(first) == summarize_slot_options(second)
    midpoint_p1 = next(
        option for option in first
        if option.method_id == "midpoint_point" and option.input_name == "p1"
    )
    assert any(candidate.path == "$problem.points.D" for candidate in midpoint_p1.candidates)


def test_validator_rejects_invalid_json_duplicate_step_and_raw_contextpath_binding() -> None:
    """非法 JSON、重复 step_id、裸 ContextPath binding 都会在编译前失败。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    validator = AbstractPlanValidator()
    valid = _axis_draft(inputs)

    with pytest.raises(AbstractPlanValidationError, match="invalid JSON"):
        validator.validate_json("not json", inputs, slot_options)

    duplicate = {
        "context_declarations": [],
        "steps": [valid["steps"][0], valid["steps"][0]],
    }
    with pytest.raises(AbstractPlanValidationError, match="duplicate step_id"):
        validator.validate_json(json.dumps(duplicate), inputs, slot_options)

    raw_path = json.loads(json.dumps(valid))
    raw_path["steps"][0]["bindings"]["a"] = "$problem.symbols.a"
    with pytest.raises(AbstractPlanValidationError, match="raw ContextPath"):
        validator.validate_json(json.dumps(raw_path), inputs, slot_options)


def test_validator_rejects_unknown_method_unknown_candidate_missing_input_and_dependency_error() -> None:
    """method、candidate、必填输入和 depends_on 都必须在受控空间内。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    validator = AbstractPlanValidator()
    valid = _axis_draft(inputs)

    unknown_method = json.loads(json.dumps(valid))
    unknown_method["steps"][0]["method_id"] = "free_solve_answer"
    with pytest.raises(AbstractPlanValidationError, match="unknown method_id"):
        validator.validate_json(json.dumps(unknown_method), inputs, slot_options)

    unknown_candidate = json.loads(json.dumps(valid))
    unknown_candidate["steps"][0]["bindings"]["a"] = "c_9999"
    with pytest.raises(AbstractPlanValidationError, match="unknown candidate id"):
        validator.validate_json(json.dumps(unknown_candidate), inputs, slot_options)

    missing_input = json.loads(json.dumps(valid))
    del missing_input["steps"][0]["bindings"]["target"]
    with pytest.raises(AbstractPlanValidationError, match="missing required input target"):
        validator.validate_json(json.dumps(missing_input), inputs, slot_options)

    bad_dep = json.loads(json.dumps(valid))
    bad_dep["steps"][0]["depends_on"] = ["later_step"]
    with pytest.raises(AbstractPlanValidationError, match="depends_on"):
        validator.validate_json(json.dumps(bad_dep), inputs, slot_options)

    self_dep = json.loads(json.dumps(valid))
    self_dep["steps"][0]["depends_on"] = ["derive_D"]
    with pytest.raises(AbstractPlanValidationError, match="cannot reference itself"):
        validator.validate_json(json.dumps(self_dep), inputs, slot_options)


def test_empty_steps_draft_is_valid_and_compiles_to_empty_plan() -> None:
    """允许 LLM 返回只有 declarations、暂无 steps 的合法 draft。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    raw = {
        "context_declarations": [
            {
                "path": "$question.ii.points.G",
                "type": "PointRef",
                "name": "G",
                "definition_intent": "line_intersection",
                "scope_id": "ii",
            }
        ],
        "steps": [],
    }
    draft = AbstractPlanValidator().validate_json(
        json.dumps(raw, ensure_ascii=False),
        inputs,
        slot_options,
    )

    output = PlanCompiler().compile(draft, inputs, slot_options)

    assert output.context_declarations[0].path == "$question.ii.points.G"
    assert output.step_plans == []


def test_validator_rejects_declaration_unknown_scope() -> None:
    """declaration 不能声明到不存在的 scope。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    raw = _axis_draft(inputs)
    raw["context_declarations"] = [
        {
            "path": "$question.ii_99.points.G",
            "type": "PointRef",
            "name": "G",
            "definition_intent": "line_intersection",
            "scope_id": "ii_99",
        }
    ]

    with pytest.raises(AbstractPlanValidationError, match="unknown declaration scope_id"):
        AbstractPlanValidator().validate_json(
            json.dumps(raw, ensure_ascii=False),
            inputs,
            slot_options,
        )


def test_validator_rejects_unknown_promote_point_target() -> None:
    """promote_to 指向未声明、不可见的点路径时，应在 abstract 层提前失败。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    invalid_target = _axis_draft(inputs)
    invalid_target["steps"][0]["promote_to"]["axis_point"] = "$question.ii.points.Z"

    with pytest.raises(AbstractPlanValidationError, match="unknown promote_to target_path"):
        AbstractPlanValidator().validate_json(
            json.dumps(invalid_target),
            inputs,
            slot_options,
        )


def test_validator_rejects_unknown_promote_output_key() -> None:
    """promote_to 的 key 必须来自 method spec outputs。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    invalid_output = _axis_draft(inputs)
    invalid_output["steps"][0]["promote_to"] = {
        "not_a_method_output": "$problem.points.D"
    }

    with pytest.raises(AbstractPlanValidationError, match="unknown promote output"):
        AbstractPlanValidator().validate_json(
            json.dumps(invalid_output),
            inputs,
            slot_options,
        )


def test_validator_rejects_invisible_sibling_scope_candidate_and_invalid_declaration() -> None:
    """跨 sibling scope 的候选不可绑定；declaration 不能夹带答案字段。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    method_id = "parameter_from_segment_length"
    invalid_scope_draft = {
        "context_declarations": [],
        "steps": [
            {
                "step_id": "bad_segment_length",
                "scope_id": "ii_2",
                "step_goal": {
                    "type": "derive_parameter",
                    "target_path": "$subquestion.ii_2.outputs.m",
                },
                "method_id": method_id,
                "bindings": {
                    "p1": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="p1",
                        path="$problem.points.D",
                    ),
                    "p2": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="p2",
                        path="$question.ii.points.M",
                    ),
                    "parameter": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="parameter",
                        path="$problem.symbols.m",
                    ),
                    "condition": _candidate_id(
                        slot_options,
                        method_id=method_id,
                        input_name="condition",
                        path="$subquestion.ii_1.conditions.length_squared",
                    ),
                },
                "promote_to": {"parameter_value": "$subquestion.ii_2.outputs.m"},
                "depends_on": [],
                "reason": "故意跨 sibling scope 引用 ii_1 条件。",
            }
        ],
    }

    with pytest.raises(AbstractPlanValidationError, match="not visible"):
        AbstractPlanValidator().validate_json(
            json.dumps(invalid_scope_draft),
            inputs,
            slot_options,
        )

    invalid_declaration = json.loads(json.dumps(_axis_draft(inputs)))
    invalid_declaration["context_declarations"] = [
        {
            "path": "$question.ii.points.G",
            "type": "PointRef",
            "name": "G",
            "definition_intent": "line_intersection",
            "scope_id": "ii",
            "answer": ["4", "-13/3"],
        }
    ]
    with pytest.raises(AbstractPlanValidationError, match="unknown field"):
        AbstractPlanValidator().validate_json(
            json.dumps(invalid_declaration),
            inputs,
            slot_options,
        )


def test_plan_compiler_generates_temp_outputs_promote_outputs_and_declarations() -> None:
    """compiler 自动生成 step temp output，并把 definition_intent 转为 ContextDeclaration。"""
    inputs = _planner_inputs()
    slot_options = SlotBinder().build(
        method_specs=inputs.method_specs,
        context_inventory=inputs.context_inventory,
    )
    raw = _axis_draft(inputs)
    raw["context_declarations"] = [
        {
            "path": "$question.ii.points.G",
            "type": "PointRef",
            "name": "G",
            "definition_intent": "line_intersection",
            "scope_id": "ii",
        }
    ]
    draft = parse_planner_draft(json.dumps(raw, ensure_ascii=False))

    output = PlanCompiler().compile(draft, inputs, slot_options)

    assert isinstance(output, PlannerOutput)
    assert output.context_declarations[0].definition == {"definition": "line_intersection"}
    plan = output.step_plans[0]
    invocation = plan.invocations[0]
    assert invocation.outputs == {"axis_point": "$step.derive_D.temp.axis_point"}
    assert plan.promote_outputs == {
        "$step.derive_D.temp.axis_point": "$problem.points.D"
    }
    assert invocation.inputs["a"] == "$problem.symbols.a"
    assert plan.goal.metadata["reason"]


def test_controlled_llm_planner_builds_prompt_and_compiles_fake_draft() -> None:
    """ControlledLLMPlanner 可完成 payload -> prompt -> fake LLM -> PlannerOutput 闭环。"""
    inputs = _planner_inputs()
    response = json.dumps(_axis_draft(inputs), ensure_ascii=False)
    client = _DraftClient(response)
    planner = ControlledLLMPlanner(client)

    output = planner.plan(inputs)

    assert output.step_plans[0].step_id == "derive_D"
    assert output.step_plans[0].invocations[0].method_id == "quadratic_axis_from_relation"
    assert client.payloads
    assert client.payloads[0]["messages"][0]["role"] == "system"
    assert "context_declarations" in client.payloads[0]["messages"][0]["content"]
    assert planner.last_payload is not None
    assert planner.last_prompt is not None


def test_controlled_llm_planner_reuses_payload_slot_options() -> None:
    """payload 与 compile 使用同一次 SlotBinder 结果，避免重复构建候选。"""
    inputs = _planner_inputs()
    response = json.dumps(_axis_draft(inputs), ensure_ascii=False)
    binder = _CountingSlotBinder()
    planner = ControlledLLMPlanner(_DraftClient(response), slot_binder=binder)

    planner.plan(inputs)

    assert binder.build_calls == 1


def test_controlled_llm_planner_validates_only_inside_compiler() -> None:
    """ControlledLLMPlanner 只 parse JSON，语义 validate 由 PlanCompiler 执行一次。"""
    inputs = _planner_inputs()
    response = json.dumps(_axis_draft(inputs), ensure_ascii=False)
    validator = _CountingValidator()
    planner = ControlledLLMPlanner(
        _DraftClient(response),
        compiler=PlanCompiler(validator=validator),
    )

    planner.plan(inputs)

    assert validator.validate_calls == 1
