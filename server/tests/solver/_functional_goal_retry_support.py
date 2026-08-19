from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionResult,
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRetryAuthority,
    FunctionalGoalRetryProjector,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanValidator,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


CASE = "tj-2026-heping-yimo-25"
FAILED_STEP_ID = "reduce_equal_length_ray_path_ii"
FAILED_GOAL_REF = "ii.a"


@dataclass(frozen=True)
class GoalRetryFixture:
    authority_fixture: tuple[Any, ...]
    correct_payload: dict[str, Any]
    failed_payload: dict[str, Any]
    failed_plan: ScopedFunctionalPlan
    execution: ScopedFunctionalGoalExecutionResult
    retry_authority: FunctionalGoalRetryAuthority

    @property
    def planning_context(self):
        return self.authority_fixture[1]

    @property
    def problem(self):
        return self.authority_fixture[2]

    @property
    def inputs(self):
        return self.authority_fixture[3]

    @property
    def problem_payload(self):
        return self.authority_fixture[4]

    @property
    def handle_registry(self):
        return self.authority_fixture[5]

    @property
    def planner_state_context(self):
        return self.authority_fixture[6]

    @property
    def binding_catalog(self):
        return self.authority_fixture[7]

    @property
    def capability_catalog(self):
        return FunctionalCapabilityCatalog.from_family_spec(
            self.inputs.family_spec,
            self.inputs.method_specs,
        )


def goal_retry_fixture(tmp_path: Path) -> GoalRetryFixture:
    authority_fixture = planning_binding_fixture(tmp_path / CASE, case=CASE)
    correct = load_v2_fixture_payload(CASE)
    failed = deepcopy(correct)
    step(failed, FAILED_STEP_ID)["args"]["point_on_ray"] = "not_a_real_ref"
    failed_plan, validation = (
        ScopedFunctionalPlanValidator().validate_payload_with_report(failed)
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    retry_authority = FunctionalGoalRetryProjector().project(
        plan=failed_plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )
    return GoalRetryFixture(
        authority_fixture=authority_fixture,
        correct_payload=correct,
        failed_payload=failed,
        failed_plan=failed_plan,
        execution=execution,
        retry_authority=retry_authority,
    )


def downstream_path_witness_retry_fixture(tmp_path: Path) -> GoalRetryFixture:
    """Keep the path Macro verified while its parameter consumer is invalid."""

    authority_fixture = planning_binding_fixture(tmp_path / CASE, case=CASE)
    correct = load_v2_fixture_payload(CASE)
    failed = deepcopy(correct)
    step(failed, "solve_parameter_from_minimum_ii")["args"][
        "minimum_value"
    ] = "not_a_real_ref"
    failed_plan, validation = (
        ScopedFunctionalPlanValidator().validate_payload_with_report(failed)
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    retry_authority = FunctionalGoalRetryProjector().project(
        plan=failed_plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )
    return GoalRetryFixture(
        authority_fixture=authority_fixture,
        correct_payload=correct,
        failed_payload=failed,
        failed_plan=failed_plan,
        execution=execution,
        retry_authority=retry_authority,
    )


def published_goal_retry_fixture(tmp_path: Path) -> GoalRetryFixture:
    """Fail i_2 after i_1 has published the shared parent-scope parabola."""

    authority_fixture = planning_binding_fixture(tmp_path / CASE, case=CASE)
    correct = load_v2_fixture_payload(CASE)
    failed = deepcopy(correct)
    step(failed, "derive_curve_intersection_E_i")["args"]["parabola"] = (
        "not_a_real_ref"
    )
    failed_plan, validation = (
        ScopedFunctionalPlanValidator().validate_payload_with_report(failed)
    )
    assert validation.ok and failed_plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(failed, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    retry_authority = FunctionalGoalRetryProjector().project(
        plan=failed_plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )
    assert retry_authority.editable_goal_refs == ("i_2.E",)
    assert "i_1.parabola" in retry_authority.solved_goal_refs
    return GoalRetryFixture(
        authority_fixture=authority_fixture,
        correct_payload=correct,
        failed_payload=failed,
        failed_plan=failed_plan,
        execution=execution,
        retry_authority=retry_authority,
    )


def repair_payload(
    fixture: GoalRetryFixture,
    *,
    goal_ref: str = FAILED_GOAL_REF,
    goal_payload: dict[str, Any] | None = None,
    base_plan_id: str | None = None,
    base_retry_context_id: str | None = None,
) -> dict[str, Any]:
    goal_payload = goal_payload or goal(
        fixture.correct_payload,
        FAILED_GOAL_REF,
    )
    return {
        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
        "base_plan_id": base_plan_id or fixture.retry_authority.base_plan_id,
        "base_retry_context_id": (
            base_retry_context_id
            or fixture.retry_authority.retry_context_id
        ),
        "goal_replacements": {
            goal_ref: {
                "steps": deepcopy(goal_payload["steps"]),
                "answer_from": deepcopy(goal_payload["answer_from"]),
            }
        },
        "scope_step_replacements": {},
    }


def goal(payload: dict[str, Any], goal_ref: str) -> dict[str, Any]:
    for scope in iter_scopes(payload["root_scope"]):
        for candidate in scope.get("goals", []):
            if candidate["goal_ref"] == goal_ref:
                return candidate
    raise KeyError(goal_ref)


def step(payload: dict[str, Any], step_id: str) -> dict[str, Any]:
    for scope in iter_scopes(payload["root_scope"]):
        for candidate in scope.get("steps", []):
            if candidate["step_id"] == step_id:
                return candidate
        for candidate_goal in scope.get("goals", []):
            for candidate in candidate_goal.get("steps", []):
                if candidate["step_id"] == step_id:
                    return candidate
    raise KeyError(step_id)


def iter_scopes(scope: dict[str, Any]):
    yield scope
    for child in scope.get("children", []):
        yield from iter_scopes(child)
