from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

import pytest
import sympy as sp

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionScope,
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.macro_preparation import (
    MacroPreparationService,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


pytestmark = pytest.mark.solver_contract


CASE = "tj-2026-nankai-yimo-25"
EXPLICIT_PLAN_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "explicit_function_plans"
    / "nankai_coupled_segment.json"
)
PATH_STEP_IDS = (
    "llm_prove_EG_eq_DG",
    "llm_reflect_D",
    "llm_construct_G",
    "llm_rewrite_path",
    "llm_compute_minimum",
    "llm_verify_attainment",
    "llm_publish_minimum",
)


def _scope(payload: Mapping[str, Any], scope_ref: str) -> dict[str, Any]:
    if payload.get("scope_ref") == scope_ref:
        return payload  # type: ignore[return-value]
    for child in payload.get("children", ()):
        if isinstance(child, dict):
            match = _scope(child, scope_ref)
            if match:
                return match
    return {}


def _rewrite_step_result(
    value: Any,
    *,
    replaced_step_id: str,
    replaced_return: str,
    replacement: Mapping[str, str],
) -> Any:
    if isinstance(value, list):
        return [
            _rewrite_step_result(
                item,
                replaced_step_id=replaced_step_id,
                replaced_return=replaced_return,
                replacement=replacement,
            )
            for item in value
        ]
    if isinstance(value, Mapping):
        if (
            value.get("step_id") == replaced_step_id
            and value.get("return") == replaced_return
            and "capability_id" not in value
        ):
            return dict(replacement)
        return {
            str(key): _rewrite_step_result(
                child,
                replaced_step_id=replaced_step_id,
                replaced_return=replaced_return,
                replacement=replacement,
            )
            for key, child in value.items()
        }
    return value


def _explicit_function_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    fragment = json.loads(EXPLICIT_PLAN_FIXTURE.read_text(encoding="utf-8"))
    assert fragment["case_id"] == CASE
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
    retained[first_position:first_position] = deepcopy(fragment["steps"])
    ii_scope["steps"] = retained

    ii_2_scope = _scope(payload["root_scope"], "ii_2")
    replacement = fragment["child_goal_replacements"]["ii_2.G"]
    goal = next(item for item in ii_2_scope["goals"] if item["goal_ref"] == "ii_2.G")
    goal["steps"] = deepcopy(replacement["steps"])
    goal["answer_from"] = deepcopy(replacement["answer_from"])

    export = fragment["exports"]["minimum_expression"]
    payload = _rewrite_step_result(
        payload,
        replaced_step_id="ii_derive_path_model",
        replaced_return="path_minimum_expression",
        replacement=export,
    )
    return payload, fragment


def _execute(fixture, payload):
    return ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )


def _goals(scope: FunctionalGoalExecutionScope):
    yield from scope.goals
    for child in scope.children:
        yield from _goals(child)


def _call(result, step_id: str):
    attempt = result.replay.transactional_attempt_result
    assert attempt is not None
    return next(
        call
        for call in attempt.execution_report.call_results
        if call.call_id == step_id
    )


def _runtime_value(result, step_id: str, return_name: str) -> Any:
    call = _call(result, step_id)
    matches = tuple(
        item
        for item in call.runtime_results
        if item.output_key == return_name
        or item.output_key.rsplit(".", 1)[-1] == return_name
    )
    assert len(matches) == 1
    return matches[0].value


def test_nankai_coupled_path_is_solved_by_explicit_function_steps(
    tmp_path,
    monkeypatch,
) -> None:
    payload, fragment = _explicit_function_payload()

    def forbidden_prepare(*_args, **_kwargs):
        raise AssertionError("the explicit path Function chain must not search a Macro")

    monkeypatch.setattr(MacroPreparationService, "prepare", forbidden_prepare)
    fixture = planning_binding_fixture(tmp_path / CASE, case=CASE)
    result = _execute(fixture, payload)

    assert result.checkpoint is not None
    assert result.checkpoint.transaction_ok
    assert result.checkpoint.all_required_goals_verified
    goals = tuple(_goals(result.checkpoint.root_scope))
    assert len(goals) == 6
    assert {goal.status for goal in goals} == {"provisionally_solved"}

    by_id = {step.step_id: step for step in result.canonical_plan.steps}
    assert tuple(by_id[step_id].capability_id for step_id in PATH_STEP_IDS) == tuple(
        step["capability_id"] for step in fragment["steps"]
    )
    assert not {
        "two_moving_points_path_reduction",
        "broken_path_straightening_minimum_expression",
    }.intersection(step.capability_id for step in result.canonical_plan.steps)
    assert "PathTransformation" not in json.dumps(
        result.canonical_plan.to_payload(),
        ensure_ascii=False,
    )

    reflected = tuple(
        sp.sympify(value)
        for value in _runtime_value(result, "llm_reflect_D", "reflected_point")
    )
    m = next(iter(set().union(*(value.free_symbols for value in reflected))))
    assert tuple(
        sp.simplify(value - expected)
        for value, expected in zip(
            reflected,
            (m + 1, 2 - m),
            strict=True,
        )
    ) == (0, 0)
    intersection = tuple(
        sp.sympify(value)
        for value in _runtime_value(result, "llm_construct_G", "intersection")
    )
    assert tuple(
        sp.simplify(value - expected)
        for value, expected in zip(
            intersection,
            ((m + 4) / 3, (3 - 2 * m) / 3),
            strict=True,
        )
    ) == (0, 0)
    minimum = sp.sympify(
        _runtime_value(result, "llm_publish_minimum", "minimum_expression")
    )
    assert sp.simplify(minimum - sp.sqrt(5 * m**2 - 10 * m + 10) / 2) == 0
    assert tuple(
        sp.simplify(value)
        for value in _runtime_value(result, "llm_evaluate_G", "evaluated_point")
    ) == (sp.Integer(4), sp.Rational(-13, 3))

    published_kinds = {
        condition.kind
        for step_id in ("llm_prove_EG_eq_DG", "llm_verify_attainment")
        for condition in _call(result, step_id).published_conditions
    }
    assert published_kinds == {"distance_equality", "path_minimum_attained"}
    attainment_condition = _call(
        result, "llm_verify_attainment"
    ).published_conditions[0]
    assert dict(attainment_condition.result_roles)["candidate"] == (
        "llm_compute_minimum.distance",
    )
    assert set(dict(attainment_condition.attested_value_signatures)) == {
        "objective",
        "candidate",
    }

    reconciliation = result.replay.functional_reconciliation
    assert reconciliation is not None
    binding_context = reconciliation.functional_problem_binding_context
    assert binding_context is not None
    for step_id in (*PATH_STEP_IDS, "llm_evaluate_G"):
        assert binding_context.call_binding(step_id).input_bindings
        assert step_id in result.checkpoint.restore_state.source_read_signatures
