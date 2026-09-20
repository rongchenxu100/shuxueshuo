import json
from copy import deepcopy

import pytest
from _math_runtime_binding_support import CASES, ROOT, binding, replay
from jsonschema import Draft202012Validator
from test_method_math_arguments import resolver_for

from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.solver.extraction.source_identity import thaw_json
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.method_math_prompt import (
    MathStrategyPayloadBuilder,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)


@pytest.mark.parametrize("case", CASES)
def test_math_prompt_retains_catalog_frame_and_schema_constraints(case, tmp_path):
    bound = binding(case)
    resolver = resolver_for(bound)
    builder = StrategyPayloadBuilder()
    kwargs = {
        "problem_payload": thaw_json(bound.bundle.canonical_solver_input),
        "problem_planning_context": bound.planning_context,
        "problem_binding_catalog": bound.binding_catalog,
        "planner_state_context": bound.planner_state_context,
    }
    old = builder.build_scoped(bound.inputs, **kwargs)
    new = MathStrategyPayloadBuilder(builder, resolver).build_scoped(
        bound.inputs, **kwargs
    )
    assert old["plan_authority_frame"] == new["plan_authority_frame"]
    assert (
        old["planner_protocol"]
        == new["planner_protocol"]
        == "functional-plan-content/v2"
    )
    assert old["strategy_principles"] == new["strategy_principles"]
    assert old["functional_few_shot_selection"] == new["functional_few_shot_selection"]
    for before, after in zip(
        old["functional_capability_catalog"]["capabilities"],
        new["functional_capability_catalog"]["capabilities"],
    ):
        before_names = [item["name"] for item in before["args"]]
        after_names = [item["name"] for item in after["args"]]
        if "right_angle_equal_length" in before_names:
            assert after_names == [
                *before_names[: before_names.index("right_angle_equal_length")],
                "angle",
                "equal_length",
                *before_names[before_names.index("right_angle_equal_length") + 1 :],
            ]
        else:
            assert after_names == before_names
        for argument in after["args"]:
            contract = argument["math_argument"]
            assert contract["encoding"] == "math-expression/v1"
            assert contract["preferred_examples"]
            assert set(argument) == {"name", "math_argument"}
    r = replay(case, bound, tmp_path)
    assert r.status == "accepted"
    frame = FunctionalPlanAuthorityFrame.from_planning_context(bound.planning_context)
    content = functional_plan_content_from_plan(r.final_plan, frame=frame).to_payload()
    math, _ = resolver.transform(content, encode=True)
    assert not list(Draft202012Validator(new["output_json_schema"]).iter_errors(math))
    # JSON field and cardinality gates have not been weakened for expressions.
    bad = deepcopy(math)
    bad["unexpected_scope_override"] = []
    assert list(Draft202012Validator(new["output_json_schema"]).iter_errors(bad))
    prompt = StrategyPromptRenderer().render_scoped(new)
    assert "functional-plan-content/v2" in prompt.system
    assert "数学表达式" in prompt.system and "Plan Authority Frame" in prompt.user
    assert "路径目标用`min(sqrt(2)*MN+AN)`" not in prompt.system
    assert "path_minimum_target` 直接写要最小化的路径表达式" in prompt.system
    assert "functional-scope-repair/v1" not in prompt.system


def test_math_few_shots_change_only_call_arguments_and_targets():
    def mask(scope):
        for step in scope.get("steps", []) + [
            s for g in scope.get("goals", []) for s in g.get("steps", [])
        ]:
            for field in ("args", "output_targets"):
                if field not in step:
                    continue

                def argument(value):
                    if isinstance(value, str):
                        return "<source-spelling>"
                    if isinstance(value, list):
                        return [argument(v) for v in value]
                    return value

                step[field] = {k: argument(v) for k, v in step[field].items()}
        for child in scope.get("children", []):
            mask(child)

    original_dir = ROOT / "internal/functional-few-shots-v2"
    math_dir = ROOT / "internal/functional-few-shots-v2-math"
    assert {p.name for p in original_dir.glob("*.json")} == {
        p.name for p in math_dir.glob("*.json")
    }
    for path in original_dir.glob("*.json"):
        old = json.loads(path.read_text())
        new = json.loads((math_dir / path.name).read_text())

        def check(value):
            if isinstance(value, dict):
                for field in ("args", "output_targets"):
                    for argument in value.get(field, {}).values():
                        for text in (
                            argument if isinstance(argument, list) else [argument]
                        ):
                            if isinstance(text, str):
                                assert parse(text)
                for v in value.values():
                    check(v)
            elif isinstance(value, list):
                for v in value:
                    check(v)

        check(new)
        mask(old["plan"]["root_scope"])
        mask(new["plan"]["root_scope"])
        assert new["plan"] == old["plan"]


def test_math_catalog_exposes_path_objective_as_expression():
    bound = binding("tj-2026-nankai-yimo-25")
    resolver = resolver_for(bound)
    builder = StrategyPayloadBuilder()
    kwargs = {
        "problem_payload": thaw_json(bound.bundle.canonical_solver_input),
        "problem_planning_context": bound.planning_context,
        "problem_binding_catalog": bound.binding_catalog,
        "planner_state_context": bound.planner_state_context,
    }
    payload = MathStrategyPayloadBuilder(builder, resolver).build_scoped(
        bound.inputs, **kwargs
    )
    coupled = next(
        item
        for item in payload["functional_capability_catalog"]["capabilities"]
        if item["capability_id"]
        == "coupled_segment_endpoint_replacement_path_minimum"
    )
    target = next(
        item for item in coupled["args"] if item["name"] == "path_minimum_target"
    )["math_argument"]
    assert target["domain_type"] == "Expression"
    assert target["form"] == "path_sum"
    assert target["preferred_examples"] == ["EG+FG"]
    assert "min(EG+FG)" in target["invalid_examples"]

    weighted_bound = binding("tj-2026-hexi-yimo-25")
    weighted_resolver = resolver_for(weighted_bound)
    weighted_payload = MathStrategyPayloadBuilder(builder, weighted_resolver).build_scoped(
        weighted_bound.inputs,
        problem_payload=thaw_json(weighted_bound.bundle.canonical_solver_input),
        problem_planning_context=weighted_bound.planning_context,
        problem_binding_catalog=weighted_bound.binding_catalog,
        planner_state_context=weighted_bound.planner_state_context,
    )
    weighted = next(
        item
        for item in weighted_payload["functional_capability_catalog"]["capabilities"]
        if item["capability_id"] == "weighted_axis_path_minimum"
    )
    weighted_target = next(
        item
        for item in weighted["args"]
        if item["name"] == "path_minimum_target"
    )["math_argument"]
    assert weighted_target["domain_type"] == "Expression"
    assert weighted_target["preferred_examples"] == ["sqrt(2)*MN+AN"]
