from __future__ import annotations

from dataclasses import replace
import json

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FunctionalGoalRetryProjector,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalScope,
    scoped_functional_plan_id,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


pytestmark = pytest.mark.solver_contract


def _execute(fixture, plan_payload, *, macro_expansions=()):
    return ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(plan_payload, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
        macro_expansions=macro_expansions,
    )


def _replace_step(plan: ScopedFunctionalPlan, step_id: str, transform):
    def visit(scope: ScopedFunctionalScope) -> ScopedFunctionalScope:
        return replace(
            scope,
            steps=tuple(
                transform(step) if step.step_id == step_id else step
                for step in scope.steps
            ),
            goals=tuple(
                replace(
                    goal,
                    steps=tuple(
                        transform(step) if step.step_id == step_id else step
                        for step in goal.steps
                    ),
                )
                for goal in scope.goals
            ),
            children=tuple(visit(child) for child in scope.children),
        )

    return replace(plan, root_scope=visit(plan.root_scope))


def _checkpoint_steps(root):
    result = []

    def visit(scope) -> None:
        result.extend(scope.scope_steps)
        for goal in scope.goals:
            result.extend(goal.steps)
        for child in scope.children:
            visit(child)

    visit(root)
    return {step.step_id: step for step in result}


def test_failed_generated_function_uses_the_ordinary_step_repair_cone(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    successful = _execute(fixture, load_v3_fixture_payload(case))
    assert successful.checkpoint is not None
    expansion = successful.macro_expansions[0]
    failing_step = next(
        step
        for step in successful.canonical_plan.steps
        if step.capability_id == "verify_distance_equality"
        and step.step_id in expansion.generated_step_ids
    )

    def make_false(step):
        args = dict(step.args)
        args["first_end"] = ("A",)
        return replace(step, args=args)

    failing_plan = _replace_step(
        successful.canonical_plan,
        failing_step.step_id,
        make_false,
    )
    failing_expansion = replace(
        expansion,
        materialized_plan_id=scoped_functional_plan_id(failing_plan),
    )
    failed = _execute(
        fixture,
        failing_plan.to_payload(),
        macro_expansions=(failing_expansion,),
    )

    assert failed.checkpoint is not None
    assert failed.macro_expansions == ()
    by_id = _checkpoint_steps(failed.checkpoint.root_scope)
    assert by_id[failing_step.step_id].status == "runtime_failed"
    downstream = {
        step_id
        for step_id in expansion.generated_step_ids
        if by_id[step_id].status == "blocked_by_dependency"
    }
    assert downstream
    assert any(
        by_id[step_id].status == "runtime_verified"
        for step_id in expansion.generated_step_ids
    )

    retry = FunctionalGoalRetryProjector().project(
        plan=failing_plan,
        execution=failed,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
    )
    assert "ii.a" in retry.editable_goal_refs
    failed_goal = retry.goal_authorities["ii.a"]
    assert failed_goal.editable
    assert failing_step.step_id in failed_goal.closure_step_ids
    assert retry.repair_step_owners[failing_step.step_id] == "goal:ii.a"
    assert all(
        step_id not in retry.editable_scope_step_ids.get("problem", ())
        for step_id in expansion.generated_step_ids
    )
