from __future__ import annotations

from pathlib import Path

from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner_public_types import (
    planner_output_value_type,
)
from shuxueshuo_server.solver.runtime.strategy_planner import (
    build_strategy_probe_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-heping-ermo-25",
)


def test_every_llm_catalog_uses_one_canonical_return_type_projection() -> None:
    observed_goal_return_types: set[str] = set()
    goal_types: set[str] = set()

    for case in CASES:
        problem = load_problem_ir(
            str(REPO_ROOT / "internal" / "solver-fixtures" / f"{case}.json")
        )
        inputs = build_strategy_probe_inputs(problem)
        goal_types.update(goal.value_type for goal in inputs.question_goals)

    methods = MethodSpecRegistry.load_from_code()
    for family in DEFAULT_FAMILY_REGISTRY.families:
        functions = FunctionSpecRegistry.from_family_spec(
            family,
            methods,
        )
        for spec in functions.specs.values():
            prompt_returns = {
                item["name"]: item for item in spec.to_prompt_payload()["returns"]
            }
            for returned in spec.returns:
                public_type = prompt_returns[returned.name]["type"]
                assert public_type == planner_output_value_type(
                    returned.runtime_type
                )
                if returned.runtime_type in goal_types:
                    assert public_type == returned.runtime_type
                    observed_goal_return_types.add(public_type)

        macros = MacroSpecRegistry.from_family_spec(
            family,
            methods,
        )
        for spec in macros.specs.values():
            prompt_returns = {
                item["name"]: item for item in spec.to_prompt_payload()["returns"]
            }
            for returned in spec.returns:
                public_type = prompt_returns[returned.name]["type"]
                assert public_type == planner_output_value_type(
                    returned.runtime_type
                )
                if returned.runtime_type in goal_types:
                    assert public_type == returned.runtime_type
                    observed_goal_return_types.add(public_type)

        catalog = FunctionalCapabilityCatalog.from_family_spec(
            family,
            methods,
        )
        for capability in catalog.items.values():
            prompt_returns = {
                item["name"]: item
                for item in capability.to_prompt_payload()["returns"]
            }
            for returned in capability.returns:
                public_type = prompt_returns[returned.name]["type"]
                assert public_type == planner_output_value_type(
                    returned.runtime_type
                )
                if returned.runtime_type in goal_types:
                    assert public_type == returned.runtime_type
                    observed_goal_return_types.add(public_type)

            for arg in capability.to_prompt_payload()["args"]:
                role = arg.get("role", "")
                chunks = role.split(" ")
                assert not (
                    len(chunks) == 2 and chunks[0] == chunks[1]
                ), capability.capability_id

    assert observed_goal_return_types >= {
        "Point",
        "PointList",
        "Parabola",
        "ParameterValue",
        "MinimumExpression",
    }


def test_public_return_projection_does_not_use_input_entity_aliases() -> None:
    assert planner_output_value_type("Parabola") == "Parabola"
    assert planner_output_value_type("ParameterValue") == "ParameterValue"
    assert planner_output_value_type("PointList") == "PointList"
    assert planner_output_value_type("Expression") == "Expression"
