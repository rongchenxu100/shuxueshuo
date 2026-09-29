import json
from dataclasses import replace
from pathlib import Path

import pytest

from _problem_planning_support import cached_scope_native_payload_args
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    _basic_inequality_strategy_reference,
    build_strategy_probe_inputs,
)


ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "internal/llm-prompts/basic-inequality-strategy.json"


def test_basic_inequality_strategy_reference_has_one_overview_and_six_methods():
    payload = json.loads(REFERENCE.read_text(encoding="utf-8"))

    assert payload["family_id"] == "basic_inequality"
    assert isinstance(payload["strategy_overview"], str)
    assert len(payload["methods"]) == 6
    assert [item["name"] for item in payload["methods"]] == [
        "直接应用基本不等式",
        "找对称结构",
        "配齐次式",
        "多次应用基本不等式",
        "换元法",
        "条件消元法",
    ]
    assert "strategy_principles" not in payload
    assert all("capability_id" not in item for item in payload["methods"])


def test_basic_inequality_reference_is_loaded_outside_runtime_method_catalog():
    payload = _basic_inequality_strategy_reference()

    assert payload is not None
    assert payload["family_id"] == "basic_inequality"
    assert all("method_id" not in item for item in payload["methods"])


@pytest.mark.parametrize("protocol", ["functional", "scoped", "repair"])
def test_basic_inequality_prompt_renders_overview_and_planning_methods(protocol):
    reference = _basic_inequality_strategy_reference()
    assert reference is not None
    assert '同一角色的多个完整关系用逗号分隔' in reference['method_application_rules']['principle']
    examples = json.dumps(reference['method_boundary_examples'], ensure_ascii=False)
    assert '∵' in examples and '∴' in examples
    assert '因为 ' not in examples and '所以 ' not in examples
    payload = {
        "problem_planning_context": {},
        "strategy_overview": reference["strategy_overview"],
        "planning_methods": reference["methods"],
        "method_application_rules": reference["method_application_rules"],
        "method_boundary_examples": reference["method_boundary_examples"],
        "functional_capability_catalog": {},
        "few_shot_examples": [],
        "previous_attempt_state": {},
        "output_json_schema": {},
        "plan_authority_frame": {},
        "authoring_feedback": [],
        "planner_protocol": "functional-scope-repair/v1",
        "annotated_previous_plan": {},
    }

    renderer = StrategyPromptRenderer()
    render = {
        "functional": renderer.render,
        "scoped": renderer.render_scoped,
        "repair": renderer.render_scope_repair,
    }[protocol]
    prompt = render(payload)

    assert "## Strategy Overview" in prompt.user
    assert "## LLM Planning Methods" in prompt.user
    assert "## Strategy Principles" not in prompt.user
    for method in reference["methods"]:
        assert method["name"] in prompt.user
    assert "六种思路的名称不是 capability_id" in prompt.user
    assert "可以在该字段说明采用的思路" in prompt.user
    assert "## Method Application Boundaries" in prompt.user
    assert "separate_amgm_and_square_nonnegativity" in prompt.user
    assert "previous_bound" in prompt.user
    assert reference['method_application_rules']['principle'] in prompt.user
    assert '表达式对象与极值目标事实' in prompt.user
    assert '这是教学偏好，不是合法路线的准入条件' in prompt.user
    assert 'Method Application Boundaries' not in prompt.system


def test_planning_reference_preserves_executable_catalog_and_output_contract():
    # Reuse an executable geometry bundle to isolate prompt projection. This
    # does not register or pretend to solve a basic inequality problem.
    problem = load_problem_ir("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json")
    inputs = build_strategy_probe_inputs(problem)
    builder = StrategyPayloadBuilder(functional_few_shot_examples=[])
    kwargs = cached_scope_native_payload_args(problem.problem_id)
    original = builder.build(inputs, **kwargs)
    basic_inputs = replace(
        inputs,
        family_spec=replace(inputs.family_spec, family_id="basic_inequality"),
    )
    result = builder.build(basic_inputs, **kwargs)

    assert "strategy_overview" not in original
    assert "planning_methods" not in original
    assert "strategy_principles" not in result
    assert (
        result["strategy_overview"]
        == _basic_inequality_strategy_reference()["strategy_overview"]
    )
    assert len(result["planning_methods"]) == 6
    for key in ('method_application_rules', 'method_boundary_examples'):
        assert key not in original
        assert result[key] == _basic_inequality_strategy_reference()[key]
    assert 'separate_amgm_and_square_nonnegativity' in StrategyPromptRenderer().render(result).user
    for key in ("functional_capability_catalog", "output_json_schema", "problem_planning_context"):
        assert result[key] == original[key]
    assert all(family.family_id != "basic_inequality" for family in DEFAULT_FAMILY_REGISTRY.families)


def test_boundary_example_is_mathematically_verified_and_rejected_when_mixed():
    from shuxueshuo_server.solver.math_kernel.inequality_bound_v2 import verify, public
    from shuxueshuo_server.solver.math_kernel.quadratic_bound import verify_quadratic
    from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
    from shuxueshuo_server.solver.math_kernel.proof_algebra import ProofFailure
    example = _basic_inequality_strategy_reference()['method_boundary_examples'][0]
    target = {'type': 'extremum_target', 'goal_kind': 'find_minimum', 'scope_id': 'problem',
              'scalar_symbols': ['x', 'z'], 'target_math': 'x+4/x+(z-2)^2',
              'source_conditions': [{'handle': 'positive_x', 'source_path': '/facts/0', 'math': 'x>0'}]}
    with pytest.raises(ProofFailure) as caught:
        verify(target, **example['incorrect_call']['parameters'])
    assert caught.value.code == 'amgm_remainder_changed'
    first, second = example['corrected_calls']
    bound = public(verify(target, **first['parameters']))
    assert second['args']['previous_bound']['step_id'] == first['step_id']
    final = public(verify_quadratic(target, previous_bound=bound, **second['parameters']))
    assert str(replay_bound(target, final)['bound']) == '4'
