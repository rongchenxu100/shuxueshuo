from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
    _localizable_reconciliation_issue,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRetryError,
    FunctionalGoalRetryProjector,
    ScopedFunctionalGoalRetryService,
    _repair_affected_goal_unit_ids,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalRestoredCallBindingError,
)
from shuxueshuo_server.solver.runtime import functional_goal_retry as retry_module
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)

from _functional_goal_retry_support import (
    FAILED_GOAL_REF,
    goal,
    goal_retry_fixture,
    iter_scopes,
    published_goal_retry_fixture,
)
from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


def _content_json(fixture, plan_payload) -> str:
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        plan_payload
    )
    assert report.ok and plan is not None
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    content = functional_plan_content_from_plan(plan, frame=frame)
    return json.dumps(content.to_payload(), ensure_ascii=False)


class _RepairingClient:
    def __init__(self, fixture) -> None:
        self.fixture = fixture
        self.requests = []

    def complete(self, payload):
        self.requests.append(payload)
        if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
            return _content_json(self.fixture, self.fixture.failed_payload)
        retry = payload["planner_payload"]
        correct_goal = goal(self.fixture.correct_payload, FAILED_GOAL_REF)
        return json.dumps(
            {
                "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                "base_plan_id": retry["goal_retry_context"]["base_plan_id"],
                "base_retry_context_id": (
                    self.fixture.retry_authority.retry_context_id
                ),
                "goal_replacements": {
                    FAILED_GOAL_REF: {
                        "steps": deepcopy(correct_goal["steps"]),
                        "answer_from": deepcopy(correct_goal["answer_from"]),
                    }
                },
                "scope_step_replacements": {},
            },
            ensure_ascii=False,
        )


def test_goal_repair_restores_solved_calls_without_reexecution(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    client = _RepairingClient(fixture)
    service = ScopedFunctionalGoalRetryService(client)

    result = service.run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert [item.planner_protocol for item in result.attempts] == [
        FUNCTIONAL_PLAN_CONTENT_CONTRACT,
        FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    ]
    assert result.attempts[0].retry_authority is None
    assert result.attempts[0].result_retry_authority is not None
    assert result.attempts[1].retry_authority is (
        result.attempts[0].result_retry_authority
    )
    assert result.final_execution is not None
    report = (
        result.final_execution.replay.transactional_attempt_result.execution_report
    )
    restored = set(report.restored_call_ids)
    assert {
        "derive_y_intercept_C_i",
        "derive_translated_D_i",
        "derive_parabola_i",
        "derive_x_intercept_B_i",
        "derive_equal_angle_i",
        "derive_axis_intercept_F_i",
        "derive_curve_intersection_E_i",
    } <= restored
    assert "derive_parametric_parabola_ii" not in restored
    assert "derive_x_intercept_B_ii" not in restored
    assert result.solved_goal_restore_count == len(restored)
    assert result.final_execution.checkpoint.all_required_goals_verified


def test_scope_repair_can_add_local_object_states_without_invalidating_restored_parent_call(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    failed = deepcopy(fixture.correct_payload)
    scopes = {
        item["scope_ref"]: item
        for item in iter_scopes(failed["root_scope"])
    }
    for scope_ref, failed_step_id, arg_name in (
        ("i_2", "derive_equal_angle_i", "condition"),
        ("ii", "reduce_equal_length_ray_path_ii", "point_on_ray"),
    ):
        scope = scopes[scope_ref]
        owned_goal = scope["goals"][0]
        scope["steps"] = owned_goal.pop("steps")
        next(
            item
            for item in scope["steps"]
            if item["step_id"] == failed_step_id
        )["args"][arg_name] = "not_a_real_ref"

    correct = deepcopy(fixture.correct_payload)
    correct_scopes = {
        item["scope_ref"]: item
        for item in iter_scopes(correct["root_scope"])
    }
    replacement_steps = {}
    for scope_ref in ("i_2", "ii"):
        replacement_steps[scope_ref] = deepcopy(
            correct_scopes[scope_ref]["goals"][0]["steps"]
        )
    ii_steps = replacement_steps["ii"]
    ii_steps[1:1] = [
        {
            "step_id": "derive_y_intercept_C_ii_local",
            "capability_id": "quadratic_y_axis_intercept_point",
            "args": {
                "quadratic": {
                    "step_id": "derive_parametric_parabola_ii",
                    "return": "parabola",
                }
            },
            "output_targets": {"point": "C"},
        },
        {
            "step_id": "derive_translated_D_ii_local",
            "capability_id": "translated_point",
            "args": {
                "source": {
                    "step_id": "derive_y_intercept_C_ii_local",
                    "return": "point",
                }
            },
            "output_targets": {"point": "D"},
        },
    ]

    class ScopeRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return _content_json(fixture, failed)
            retry = payload["planner_payload"]["goal_retry_context"]
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry["base_plan_id"],
                    "base_retry_context_id": retry[
                        "base_retry_context_id"
                    ],
                    "goal_replacements": {},
                    "scope_step_replacements": {
                        scope_ref: {
                            "steps": replacement_steps[scope_ref],
                        }
                        for scope_ref in ("i_2", "ii")
                    },
                },
                ensure_ascii=False,
            )

    result = ScopedFunctionalGoalRetryService(ScopeRepairClient()).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=2,
    )

    assert result.status == "accepted"
    assert result.final_execution is not None
    restored = set(
        result.final_execution.replay.transactional_attempt_result
        .execution_report.restored_call_ids
    )
    assert "derive_y_intercept_C_i" in restored
    assert "derive_y_intercept_C_ii_local" not in restored


def test_blocked_goal_in_editable_scope_allows_consumer_dag_refinement(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = fixture.retry_authority
    blocked = replace(
        authority.goal_authorities[FAILED_GOAL_REF],
        status="blocked",
        editable=False,
    )
    updated = replace(
        authority,
        goal_authorities={
            **authority.goal_authorities,
            FAILED_GOAL_REF: blocked,
        },
        editable_scope_refs=("ii",),
    )

    affected = _repair_affected_goal_unit_ids(updated)

    assert blocked.goal_unit_id in affected
    assert all(
        item.goal_unit_id not in affected
        for item in updated.goal_authorities.values()
        if item.status == "solved"
    )


def test_typed_duplicate_goal_producers_reuse_visible_ancestor_steps(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = load_v2_fixture_payload(case)
    scopes = {
        item["scope_ref"]: item
        for item in iter_scopes(payload["root_scope"])
    }
    root_steps = payload["root_scope"].pop("steps")
    scope_i_steps = scopes["i"]["steps"]
    scopes["i"]["steps"] = root_steps
    scopes["i_1"]["goals"][0]["steps"] = scope_i_steps
    goal_i2 = scopes["i_2"]["goals"][0]

    local_c = deepcopy(root_steps[0])
    local_c["step_id"] = "retry_local_C"
    local_d = deepcopy(root_steps[1])
    local_d["step_id"] = "retry_local_D"
    local_d["args"]["source"]["step_id"] = "retry_local_C"
    local_parabola = deepcopy(scope_i_steps[0])
    local_parabola["step_id"] = "retry_local_parabola"
    local_parabola["args"]["curve_points"][1]["step_id"] = "retry_local_D"

    def replace_parent_parabola(value):
        if isinstance(value, list):
            return [replace_parent_parabola(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {
            key: replace_parent_parabola(item) for key, item in value.items()
        }
        if (
            result.get("step_id") == "derive_parabola_i"
            and "return" in result
        ):
            result["step_id"] = "retry_local_parabola"
        return result

    goal_i2["steps"] = [
        local_c,
        local_d,
        local_parabola,
        *replace_parent_parabola(goal_i2["steps"]),
    ]

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
    )

    assert execution.canonical_plan is not None
    canonical_step_ids = {
        step.step_id for step in execution.canonical_plan.steps
    }
    assert not {"retry_local_C", "retry_local_D"}.intersection(
        canonical_step_ids
    )
    assert "retry_local_parabola" in canonical_step_ids
    assert execution.checkpoint is not None
    assert execution.checkpoint.all_required_goals_verified


def test_restore_source_survives_an_intermediate_nontransaction_round(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)

    class ThreeRoundClient(_RepairingClient):
        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return _content_json(fixture, fixture.failed_payload)
            replacement = deepcopy(goal(fixture.correct_payload, FAILED_GOAL_REF))
            if len(self.requests) == 2:
                replacement_step = next(
                    item
                    for item in replacement["steps"]
                    if item["step_id"] == "reduce_equal_length_ray_path_ii"
                )
                replacement_step["args"]["point_on_ray"] = (
                    "another_invalid_ref"
                )
            retry = payload["planner_payload"]["goal_retry_context"]
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry["base_plan_id"],
                    "base_retry_context_id": retry[
                        "base_retry_context_id"
                    ],
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": replacement["steps"],
                            "answer_from": replacement["answer_from"],
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    class DropSecondTransaction:
        def __init__(self) -> None:
            self.delegate = ScopedFunctionalGoalExecutionService()
            self.calls = 0

        def execute_raw_json(self, *args, **kwargs):
            self.calls += 1
            result = self.delegate.execute_raw_json(*args, **kwargs)
            return replace(result, replay=None) if self.calls == 2 else result

    result = ScopedFunctionalGoalRetryService(
        ThreeRoundClient(fixture),
        execution_service=DropSecondTransaction(),
    ).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert len(result.attempts) == 3
    third_authority = result.attempts[2].retry_authority
    assert third_authority is not None
    assert third_authority.solved_goal_refs == (
        fixture.retry_authority.solved_goal_refs
    )
    report = (
        result.final_execution.replay.transactional_attempt_result.execution_report
    )
    assert set(third_authority.goal_authorities["i_1.parabola"].closure_step_ids) <= set(
        report.restored_call_ids
    )


def test_restore_binding_drift_is_retained_as_a_nonretryable_attempt(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)

    class DriftOnRepairExecution:
        def __init__(self) -> None:
            self.delegate = ScopedFunctionalGoalExecutionService()
            self.calls = 0

        def execute_raw_json(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise FunctionalRestoredCallBindingError(
                    "derive_y_intercept_C_i",
                    "typed binding changed for restored call derive_y_intercept_C_i",
                    details={
                        "first_difference": {
                            "path": "$.call.scope_id",
                            "expected": "problem",
                            "actual": "i",
                        }
                    },
                )
            return self.delegate.execute_raw_json(*args, **kwargs)

    result = ScopedFunctionalGoalRetryService(
        _RepairingClient(fixture),
        execution_service=DriftOnRepairExecution(),
    ).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "blocked"
    assert len(result.attempts) == 2
    error = result.attempts[-1].error
    assert error is not None
    assert error.code == "planner.retry_problem_source_binding_drift"
    assert error.retryable is False
    assert error.details["first_difference"]["path"] == "$.call.scope_id"


def test_transport_payload_switches_protocol_and_keeps_full_problem_view(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    client = _RepairingClient(fixture)
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert len(client.requests) == 2
    assert all(
        request["planner_payload"]["problem_planning_context"]
        == fixture.planning_context.to_prompt_payload()
        for request in client.requests
    )
    retry_payload = client.requests[1]["planner_payload"]
    assert "previous_plan" in retry_payload
    assert "goal_retry_context" in retry_payload
    assert "few_shot_examples" not in retry_payload


def test_unknown_scope_content_key_retries_with_authority_feedback(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    valid_content = json.loads(_content_json(fixture, fixture.correct_payload))
    malformed = deepcopy(valid_content)
    malformed.setdefault("scope_steps", {})["invented_scope"] = deepcopy(
        next(iter(valid_content["scope_steps"].values()))
    )

    class FullPlanRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            assert payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
            if len(self.requests) == 1:
                return json.dumps(malformed, ensure_ascii=False)
            feedback = payload["planner_payload"]["authoring_feedback"]
            assert feedback[0]["code"] == (
                "functional.plan_content_schema_invalid"
            )
            return json.dumps(valid_content, ensure_ascii=False)

    client = FullPlanRepairClient()
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert [item.planner_protocol for item in result.attempts] == [
        FUNCTIONAL_PLAN_CONTENT_CONTRACT,
        FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    ]
    assert result.attempts[0].retry_authority is None
    assert result.attempts[1].retry_authority is None


def test_schema_failure_retries_with_feedback_and_normalized_candidate(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    valid_content = json.loads(_content_json(fixture, fixture.correct_payload))
    malformed = deepcopy(valid_content)
    malformed["unexpected"] = True

    class SchemaRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            assert payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
            if len(self.requests) == 1:
                return json.dumps(malformed, ensure_ascii=False)
            planner_payload = payload["planner_payload"]
            feedback = planner_payload["authoring_feedback"]
            assert feedback and feedback[0]["code"] == (
                "functional.plan_content_schema_invalid"
            )
            candidate = planner_payload["previous_invalid_content"]
            assert candidate["unexpected"] is True
            assert "Previous Invalid Content Candidate" in payload[
                "messages"
            ][1]["content"]
            return json.dumps(valid_content, ensure_ascii=False)

    client = SchemaRepairClient()
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert [item.planner_protocol for item in result.attempts] == [
        FUNCTIONAL_PLAN_CONTENT_CONTRACT,
        FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    ]
    assert result.attempts[0].plan is None


def test_empty_scope_collections_do_not_consume_a_retry(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = json.loads(_content_json(fixture, fixture.correct_payload))
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    empty_scope = next(
        scope_ref
        for scope_ref in frame.scope_refs
        if scope_ref not in payload.get("scope_steps", {})
    )
    payload.setdefault("scope_steps", {})[empty_scope] = []

    class EmptyCollectionClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            return json.dumps(payload, ensure_ascii=False)

    client = EmptyCollectionClient()
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert len(client.requests) == 1
    assert len(result.attempts) == 1
    assert result.attempts[0].plan_content is not None
    assert empty_scope not in result.attempts[0].plan_content.scope_steps


def test_repeated_repair_blocks_without_a_third_execution(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)

    class RepeatingClient(_RepairingClient):
        def complete(self, payload):
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                self.requests.append(payload)
                return _content_json(fixture, fixture.failed_payload)
            self.requests.append(payload)
            failed_goal = goal(fixture.failed_payload, FAILED_GOAL_REF)
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": fixture.retry_authority.base_plan_id,
                    "base_retry_context_id": fixture.retry_authority.retry_context_id,
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": deepcopy(failed_goal["steps"]),
                            "answer_from": deepcopy(
                                failed_goal["answer_from"]
                            ),
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = RepeatingClient(fixture)
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "blocked"
    assert result.no_progress is True
    assert len(client.requests) == 2


def test_same_plan_with_changed_issue_is_not_no_progress(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    signatures = iter(("issue-a", "issue-b", "issue-b"))
    monkeypatch.setattr(
        retry_module,
        "_retry_issue_signature",
        lambda _authority: next(signatures),
    )

    class RepeatingClient(_RepairingClient):
        def complete(self, payload):
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                self.requests.append(payload)
                return _content_json(fixture, fixture.failed_payload)
            self.requests.append(payload)
            failed_goal = goal(fixture.failed_payload, FAILED_GOAL_REF)
            retry = payload["planner_payload"]["goal_retry_context"]
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry["base_plan_id"],
                    "base_retry_context_id": retry["base_retry_context_id"],
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": deepcopy(failed_goal["steps"]),
                            "answer_from": deepcopy(
                                failed_goal["answer_from"]
                            ),
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = RepeatingClient(fixture)
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "blocked"
    assert result.no_progress is True
    assert len(client.requests) == 3


def test_repair_protocol_error_is_returned_to_the_next_retry_prompt(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)

    class BoundaryThenRepairClient(_RepairingClient):
        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return _content_json(fixture, fixture.failed_payload)
            retry = payload["planner_payload"]
            if len(self.requests) == 2:
                return json.dumps(
                    {
                        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                        "base_plan_id": retry["goal_retry_context"][
                            "base_plan_id"
                        ],
                        "base_retry_context_id": retry[
                            "goal_retry_context"
                        ]["base_retry_context_id"],
                        "goal_replacements": {},
                        "scope_step_replacements": {
                            "i": {
                                "steps": [
                                    deepcopy(
                                        goal(
                                            fixture.correct_payload,
                                            FAILED_GOAL_REF,
                                        )["steps"][0]
                                    )
                                ],
                            }
                        },
                    },
                    ensure_ascii=False,
                )
            issue = retry["goal_retry_context"]["previous_repair_issue"]
            assert issue["code"] == "functional.goal_repair_boundary_violation"
            assert "expected" in issue["message"]
            correct_goal = goal(fixture.correct_payload, FAILED_GOAL_REF)
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry["goal_retry_context"][
                        "base_plan_id"
                    ],
                    "base_retry_context_id": retry["goal_retry_context"][
                        "base_retry_context_id"
                    ],
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": deepcopy(correct_goal["steps"]),
                            "answer_from": deepcopy(
                                correct_goal["answer_from"]
                            ),
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = BoundaryThenRepairClient(fixture)
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert len(result.attempts) == 3


def test_ambiguous_answer_candidates_are_returned_to_next_repair_prompt(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)

    class AmbiguousThenRepairClient(_RepairingClient):
        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return _content_json(fixture, fixture.failed_payload)
            retry = payload["planner_payload"]["goal_retry_context"]
            correct_goal = goal(fixture.correct_payload, FAILED_GOAL_REF)
            if len(self.requests) == 2:
                steps = deepcopy(correct_goal["steps"])
                duplicate = deepcopy(steps[-1])
                duplicate["step_id"] = "solve_parameter_duplicate_ii"
                steps.append(duplicate)
                answer_from = {
                    "step_id": "missing_answer_producer",
                    "return": "parameter_value",
                }
            else:
                issue = retry["previous_repair_issue"]
                assert issue["code"] == (
                    "functional.goal_repair_answer_source_invalid"
                )
                assert issue["details"]["candidate_count"] == 2
                assert {
                    item["step_id"] for item in issue["details"]["candidates"]
                } == {
                    "solve_parameter_from_minimum_ii",
                    "solve_parameter_duplicate_ii",
                }
                steps = deepcopy(correct_goal["steps"])
                answer_from = deepcopy(correct_goal["answer_from"])
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry["base_plan_id"],
                    "base_retry_context_id": retry["base_retry_context_id"],
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": steps,
                            "answer_from": answer_from,
                        },
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = AmbiguousThenRepairClient(fixture)
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert len(result.attempts) == 3
    assert result.attempts[1].error is not None
    assert result.attempts[1].error.details["candidate_count"] == 2
    assert result.attempts[1].error is not None
    assert result.attempts[2].error is None


def test_nonretryable_projection_failure_records_one_semantic_attempt(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    client = _RepairingClient(fixture)

    def fail_projection(*args, **kwargs):
        raise FunctionalGoalRetryError(
            "functional.goal_retry_publication_missing",
            "$.published_goal_results",
            "typed answer alias is missing",
            retryable=False,
        )

    monkeypatch.setattr(
        FunctionalGoalRetryProjector,
        "project",
        fail_projection,
    )
    result = ScopedFunctionalGoalRetryService(client).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "blocked"
    assert len(client.requests) == 1
    assert len(result.attempts) == 1
    assert result.attempts[0].error is not None
    assert (
        result.attempts[0].error.code
        == "functional.goal_retry_publication_missing"
    )


@pytest.mark.parametrize(
    "code",
    (
        "functional.arg_state_unavailable",
        "functional.arg_dependency_missing",
        "functional.condition_role_state_unavailable",
        "functional.equal_length_ray_point_state_unavailable",
        "functional.path_transformation_state_unavailable",
        "functional.path_reduction_point_state_unavailable",
        "functional.square_path_point_state_unavailable",
        "functional.state_transition_dependency_unproven",
    ),
)
def test_call_local_state_issue_opens_its_goal_repair_boundary(code) -> None:
    issue = SimpleNamespace(code=code, call_id="failed_step", details={})
    assert _localizable_reconciliation_issue(issue)


def test_unowned_state_issue_remains_a_root_authority_failure() -> None:
    issue = SimpleNamespace(
        code="functional.arg_state_unavailable",
        call_id=None,
        details={},
    )
    assert not _localizable_reconciliation_issue(issue)


@pytest.mark.parametrize(
    "retryability",
    ("configuration", "problem_semantics"),
)
def test_owned_nonrepairable_diagnostic_remains_a_root_failure(
    retryability: str,
) -> None:
    issue = SimpleNamespace(
        code="functional.synthetic_owned_failure",
        call_id="failed_step",
        details={"retryability": retryability},
    )
    assert not _localizable_reconciliation_issue(issue)


def test_published_goal_answer_feeds_repaired_goal_without_goal_contamination(
    tmp_path,
) -> None:
    fixture = published_goal_retry_fixture(tmp_path)

    class PublishingClient(_RepairingClient):
        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return _content_json(fixture, fixture.failed_payload)
            replacement = deepcopy(goal(fixture.correct_payload, "i_2.E"))
            for item in replacement["steps"]:
                if item["step_id"] in {
                    "derive_x_intercept_B_i",
                    "derive_curve_intersection_E_i",
                }:
                    item["args"]["parabola"] = {
                        "published_goal_ref": "i_1.parabola"
                    }
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": payload["planner_payload"][
                        "goal_retry_context"
                    ]["base_plan_id"],
                    "base_retry_context_id": (
                        fixture.retry_authority.retry_context_id
                    ),
                    "goal_replacements": {
                        "i_2.E": {
                            "steps": replacement["steps"],
                            "answer_from": replacement["answer_from"],
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    result = ScopedFunctionalGoalRetryService(PublishingClient(fixture)).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3,
    )

    assert result.status == "accepted"
    assert result.final_execution is not None
    assert result.final_execution.authority is not None
    i_1_goal_id = next(
        item.goal_unit_id
        for item in fixture.planning_context.goal_views
        if item.answer_ref.ref == "i_1.parabola"
    )
    producer = result.final_execution.authority.step_authorities[
        "derive_parabola_i"
    ]
    assert producer.consumer_goal_unit_ids == (i_1_goal_id,)
    report = (
        result.final_execution.replay.transactional_attempt_result.execution_report
    )
    assert "derive_parabola_i" in report.restored_call_ids
    assert "derive_curve_intersection_E_i" not in report.restored_call_ids
    reconciliation = result.final_execution.replay.functional_reconciliation
    parabola_placement = next(
        item
        for item in reconciliation.call_placements
        if item.canonical_call_id == "derive_parabola_i"
    )
    assert parabola_placement.execution_scope_id == "i"
