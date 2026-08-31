from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionResult,
    ScopedFunctionalGoalExecutionService,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanValidator,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


CASE = "tj-2026-heping-yimo-25"
FAILED_STEP_ID = "reduce_equal_length_ray_path_ii"


@dataclass(frozen=True)
class ScopeRetryFixture:
    authority_fixture: tuple[Any, ...]
    correct_payload: dict[str, Any]
    failed_payload: dict[str, Any]
    failed_plan: ScopedFunctionalPlan
    execution: ScopedFunctionalGoalExecutionResult

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


def scope_retry_fixture(tmp_path: Path) -> ScopeRetryFixture:
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
    return ScopeRetryFixture(
        authority_fixture=authority_fixture,
        correct_payload=correct,
        failed_payload=failed,
        failed_plan=failed_plan,
        execution=execution,
    )


def step(payload: dict[str, Any], step_id: str) -> dict[str, Any]:
    for scope in iter_scopes(payload["root_scope"]):
        for candidate in scope.get("steps", []):
            if candidate["step_id"] == step_id:
                return candidate
        for goal in scope.get("goals", []):
            for candidate in goal.get("steps", []):
                if candidate["step_id"] == step_id:
                    return candidate
    raise KeyError(step_id)


def iter_scopes(scope: dict[str, Any]):
    yield scope
    for child in scope.get("children", []):
        yield from iter_scopes(child)
