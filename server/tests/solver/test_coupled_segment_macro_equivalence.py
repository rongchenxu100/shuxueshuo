from __future__ import annotations

from copy import deepcopy
import json

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationService,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload
from test_coupled_segment_explicit_function_plan import (
    CASE,
    PATH_STEP_IDS,
    _execute,
    _explicit_function_payload,
    _rewrite_step_result,
    _scope,
)
from test_macro_explicit_plan_equivalence import (
    _alpha_normalized_conditions,
    _alpha_normalized_f5c_graph,
    _alpha_normalized_runtime_authority,
    _export_value,
    _fragment_from_result,
)


pytestmark = pytest.mark.solver_contract


MACRO_ID = "coupled_segment_endpoint_replacement_path_minimum"


def _macro_payload() -> dict:
    _authored, fragment = _explicit_function_payload()
    payload = deepcopy(load_v3_fixture_payload(CASE))
    ii_scope = _scope(payload["root_scope"], "ii")
    replaced = set(fragment["replaces_step_ids"])
    original_steps = list(ii_scope["steps"])
    first_position = min(
        index
        for index, step in enumerate(original_steps)
        if step["step_id"] in replaced
    )
    retained = [step for step in original_steps if step["step_id"] not in replaced]
    retained[first_position:first_position] = [
        {
            "step_id": "macro_coupled_path",
            "capability_id": MACRO_ID,
            "args": {
                "path_minimum_target": "path_minimum_target_e_g_f",
                "point_on_segment": [
                    "point_on_segment_e_dm",
                    "point_on_segment_g_mn",
                ],
                "segment_length_relation": "segment_length_relation_de_ng",
            },
            "return_expectations": {
                "minimum_expression": "open_expression",
            },
            "intent": "用耦合线段端点替换并反射拉直求路径最小值。",
        }
    ]
    ii_scope["steps"] = retained

    replacement = fragment["child_goal_replacements"]["ii_2.G"]
    ii_2_scope = _scope(payload["root_scope"], "ii_2")
    goal = next(
        item for item in ii_2_scope["goals"] if item["goal_ref"] == "ii_2.G"
    )
    goal["steps"] = deepcopy(replacement["steps"])
    goal["answer_from"] = deepcopy(replacement["answer_from"])

    return _rewrite_step_result(
        payload,
        replaced_step_id="ii_derive_path_model",
        replaced_return="path_minimum_expression",
        replacement={
            "step_id": "macro_coupled_path",
            "return": "minimum_expression",
        },
    )


def test_coupled_segment_macro_matches_independent_c1_function_plan(
    tmp_path,
    monkeypatch,
) -> None:
    macro_fixture = planning_binding_fixture(tmp_path / "macro", case=CASE)
    macro = _execute(macro_fixture, _macro_payload())
    assert macro.checkpoint is not None
    assert macro.checkpoint.all_required_goals_verified
    expansion = next(
        item for item in macro.macro_expansions if item.macro_id == MACRO_ID
    )
    assert len(expansion.generated_step_ids) == 7
    assert not {
        "two_moving_points_path_reduction",
        "broken_path_straightening_minimum_expression",
    }.intersection(
        step.capability_id
        for step in macro.canonical_plan.steps
        if step.step_id in expansion.generated_step_ids
    )

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("the independent C1 Function Plan must not search a Macro")

    monkeypatch.setattr(MacroPreparationService, "prepare", forbidden_prepare)
    authored_fixture = planning_binding_fixture(tmp_path / "authored", case=CASE)
    authored_payload, authored_fragment = _explicit_function_payload()
    authored = _execute(authored_fixture, authored_payload)
    assert authored.checkpoint is not None
    assert authored.checkpoint.all_required_goals_verified
    assert authored.macro_expansions == ()

    macro_ids = tuple(expansion.generated_step_ids)
    authored_ids = PATH_STEP_IDS
    macro_graph = _fragment_from_result(
        macro,
        macro_ids,
        {
            name: {"step_id": value[0], "return": value[1]}
            for name, value in expansion.export_map.items()
        },
    )
    authored_graph = _fragment_from_result(
        authored,
        authored_ids,
        authored_fragment["exports"],
    )

    assert macro_graph.alpha_normalized_payload() == (
        authored_graph.alpha_normalized_payload()
    )
    assert _alpha_normalized_f5c_graph(macro, macro_ids) == (
        _alpha_normalized_f5c_graph(authored, authored_ids)
    )
    assert _alpha_normalized_conditions(macro, macro_ids) == (
        _alpha_normalized_conditions(authored, authored_ids)
    )
    assert _alpha_normalized_runtime_authority(macro, macro_ids) == (
        _alpha_normalized_runtime_authority(authored, authored_ids)
    )
    macro_export = {
        "step_id": expansion.export_map["minimum_expression"][0],
        "return": expansion.export_map["minimum_expression"][1],
    }
    assert _export_value(macro, macro_export) == _export_value(
        authored,
        authored_fragment["exports"]["minimum_expression"],
    )


def test_coupled_segment_macro_checkpoint_restores_materialized_functions(
    tmp_path,
    monkeypatch,
) -> None:
    first_fixture = planning_binding_fixture(tmp_path / "first", case=CASE)
    first = _execute(first_fixture, _macro_payload())
    assert first.checkpoint is not None
    seed = first.checkpoint.restore_state.runtime_seed
    assert seed is not None
    expansion = next(
        item for item in first.macro_expansions if item.macro_id == MACRO_ID
    )

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("restored ordinary Functions must not search the Macro")

    monkeypatch.setattr(MacroPreparationService, "prepare", forbidden_prepare)
    restore_fixture = planning_binding_fixture(tmp_path / "restore", case=CASE)
    restored = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(first.canonical_plan.to_payload(), ensure_ascii=False),
        inputs=restore_fixture[3],
        planning_context=restore_fixture[1],
        problem_binding_catalog=restore_fixture[7],
        handle_registry=restore_fixture[5],
        context=ContextBuilder().build(restore_fixture[2]),
        planner_state_context=restore_fixture[6],
        problem_payload=restore_fixture[4],
        restored_seed=seed,
        macro_expansions=first.macro_expansions,
    )

    assert restored.checkpoint is not None
    assert restored.checkpoint.all_required_goals_verified
    transaction = restored.replay.transactional_attempt_result
    assert transaction is not None
    assert set(expansion.generated_step_ids) <= set(
        transaction.execution_report.restored_call_ids
    )
