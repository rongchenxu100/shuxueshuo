from __future__ import annotations

import json

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan_replay import (
    ScopedFunctionalPlanAuthoringService,
    ScopedFunctionalPlanReplayService,
)

from _problem_planning_support import CASES, planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


class _RecordedClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[dict[str, object]] = []

    def complete(self, payload: dict[str, object]) -> str:
        self.requests.append(payload)
        return self.response


@pytest.mark.parametrize("case", CASES)
def test_v2_recorded_plan_reconciles_compiles_and_executes(
    tmp_path,
    case,
) -> None:
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path / case, case=case)
    result = ScopedFunctionalPlanReplayService().replay_raw_json(
        json.dumps(load_v3_fixture_payload(case), ensure_ascii=False),
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )
    authority = result.authority
    replay = result.replay
    reconciliation = replay.functional_reconciliation
    assert result.validation_report.ok
    assert reconciliation is not None
    assert reconciliation.ok, reconciliation.to_payload()
    sidecar = reconciliation.functional_problem_binding_context
    assert sidecar is not None
    assert {
        key: value.consumer_goal_unit_ids
        for key, value in authority.step_authorities.items()
    } == dict(sidecar.call_goal_bindings)

    attempt = replay.transactional_attempt_result

    assert attempt is not None
    assert attempt.compiled_output is not None, [
        (issue.code, issue.message) for issue in attempt.root_issues
    ]
    assert not attempt.root_issues
    assert all(goal.status == "passed" for goal in attempt.goal_report.goals)
    assert attempt.execution_report.functional_compile_count > 0


def test_explicit_live_authoring_boundary_uses_content_prompt_and_replay(
    tmp_path,
) -> None:
    case = CASES[-1]
    (
        _bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = planning_binding_fixture(tmp_path / case, case=case)
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        load_v3_fixture_payload(case)
    )
    assert validation.ok and plan is not None
    raw_response = json.dumps(
        functional_plan_content_from_plan(
            plan,
            frame=FunctionalPlanAuthorityFrame.from_planning_context(
                planning_context
            ),
        ).to_payload(),
        ensure_ascii=False,
    )
    client = _RecordedClient(raw_response)

    result = ScopedFunctionalPlanAuthoringService(client).author_and_replay(
        inputs=inputs,
        planning_context=planning_context,
        problem_binding_catalog=binding_catalog,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        planner_state_context=planner_context,
        problem_payload=problem_payload,
    )

    assert result.payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
    assert result.raw_response == raw_response
    assert len(client.requests) == 1
    assert client.requests[0]["planner_protocol"] == (
        FUNCTIONAL_PLAN_CONTENT_CONTRACT
    )
    assert client.requests[0]["messages"] == result.prompt.messages
    assert result.replay_result.validation_report.ok
    assert result.replay_result.replay.transactional_attempt_result is not None
