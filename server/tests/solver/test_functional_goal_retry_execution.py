from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingError,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    ScopedFunctionalGoalExecutionService,
    _localizable_reconciliation_issue,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    FunctionalGoalRepairService,
    FunctionalGoalRetryError,
    FunctionalGoalRetryProjector,
    ScopedFunctionalGoalRetryService,
    functional_goal_repair_schema_for_authority,
    _merge_scope_step_replacement,
    _repair_affected_goal_unit_ids,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FUNCTIONAL_PLAN_CONTENT_CONTRACT,
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    FunctionalRestoredCallBindingError,
    rebase_restored_call_seed,
)
from shuxueshuo_server.solver.runtime import functional_goal_retry as retry_module
from shuxueshuo_server.solver.runtime import (
    functional_transaction_execution as transaction_module,
)
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
    previous_calls = {
        item.call_id: item
        for item in fixture.execution.replay.functional_reconciliation.calls
    }

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
    final_calls = {
        item.call_id: item
        for item in result.final_execution.replay.functional_reconciliation.calls
    }
    for call_id in restored:
        assert final_calls[call_id] == previous_calls[call_id]
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


def test_mixed_scope_repair_retains_frozen_producer_and_replaces_editable_step(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    root = fixture.retry_authority.base_plan.root_scope
    assert len(root.steps) >= 2
    frozen_step, editable_step = root.steps[:2]
    authority = replace(
        fixture.retry_authority,
        goal_authorities={
            key: replace(item, editable=False)
            for key, item in fixture.retry_authority.goal_authorities.items()
        },
        editable_scope_refs=(root.scope_ref,),
        frozen_scope_refs=(),
        editable_scope_step_ids={
            root.scope_ref: (editable_step.step_id,),
        },
        frozen_scope_step_ids={
            root.scope_ref: (frozen_step.step_id,),
        },
    )
    replacement = editable_step.to_payload()
    replacement["intent"] = "重新计算可编辑的scope步骤。"
    repair_payload = {
        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
        "base_plan_id": authority.base_plan_id,
        "base_retry_context_id": authority.retry_context_id,
        "goal_replacements": {},
        "scope_step_replacements": {
            root.scope_ref: {"steps": [replacement]},
        },
    }

    application = FunctionalGoalRepairService().apply_json(
        json.dumps(repair_payload, ensure_ascii=False),
        base_plan=authority.base_plan,
        authority=authority,
        capability_catalog=fixture.capability_catalog,
    )

    repaired_steps = application.plan.root_scope.steps
    assert repaired_steps[0].to_payload() == frozen_step.to_payload()
    assert repaired_steps[1].step_id == editable_step.step_id
    assert repaired_steps[1].intent == "重新计算可编辑的scope步骤。"

    illegal = deepcopy(repair_payload)
    illegal["scope_step_replacements"][root.scope_ref]["steps"].insert(
        0,
        frozen_step.to_payload(),
    )
    with pytest.raises(
        FunctionalGoalRetryError,
        match="functional.goal_repair_step_id_conflict",
    ):
        FunctionalGoalRepairService().apply_json(
            json.dumps(illegal, ensure_ascii=False),
            base_plan=authority.base_plan,
            authority=authority,
            capability_catalog=fixture.capability_catalog,
        )


def test_mixed_scope_merge_interleaves_frozen_dependency_between_replacements(
) -> None:
    def prior(step_id: str) -> SimpleNamespace:
        payload = {
            "step_id": step_id,
            "capability_id": "test_capability",
            "args": {},
            "intent": step_id,
        }
        return SimpleNamespace(
            step_id=step_id,
            to_payload=lambda payload=payload: deepcopy(payload),
        )

    merged = _merge_scope_step_replacement(
        (prior("A"), prior("B"), prior("C")),
        editable_step_ids=("A", "C"),
        replacement_steps=(
            {
                "step_id": "A_prime",
                "capability_id": "test_capability",
                "args": {},
                "intent": "replacement before frozen producer",
            },
            {
                "step_id": "C_prime",
                "capability_id": "test_capability",
                "args": {
                    "value": {"step_id": "B", "return": "result"},
                },
                "intent": "replacement consuming frozen producer",
            },
        ),
    )

    assert [step["step_id"] for step in merged] == [
        "A_prime",
        "B",
        "C_prime",
    ]


def test_mixed_scope_merge_preserves_frozen_slot_for_hidden_dependency() -> None:
    """Renamed replacements inherit old editable slots without a wire edge."""

    def prior(step_id: str) -> SimpleNamespace:
        payload = {
            "step_id": step_id,
            "capability_id": "test_capability",
            "args": {},
        }
        return SimpleNamespace(
            step_id=step_id,
            to_payload=lambda payload=payload: deepcopy(payload),
        )

    merged = _merge_scope_step_replacement(
        (prior("A"), prior("B"), prior("C")),
        editable_step_ids=("A", "C"),
        replacement_steps=(
            {
                "step_id": "A_prime",
                "capability_id": "test_capability",
                "args": {},
            },
            {
                "step_id": "C_prime",
                "capability_id": "test_capability",
                "args": {"named_entity": "B_result"},
            },
        ),
    )

    assert [step["step_id"] for step in merged] == [
        "A_prime",
        "B",
        "C_prime",
    ]


def test_mixed_scope_merge_projects_added_step_around_frozen_barrier() -> None:
    """Cardinality changes must not let a frozen producer drift to the end."""

    def prior(step_id: str) -> SimpleNamespace:
        payload = {
            "step_id": step_id,
            "capability_id": "test_capability",
            "args": {},
        }
        return SimpleNamespace(
            step_id=step_id,
            to_payload=lambda payload=payload: deepcopy(payload),
        )

    merged = _merge_scope_step_replacement(
        (prior("A"), prior("B"), prior("C")),
        editable_step_ids=("A", "C"),
        replacement_steps=(
            {
                "step_id": "A_prime",
                "capability_id": "test_capability",
                "args": {},
            },
            {
                "step_id": "D",
                "capability_id": "test_capability",
                "args": {"named_entity": "B_result"},
            },
            {
                "step_id": "C_prime",
                "capability_id": "test_capability",
                "args": {
                    "value": {"step_id": "B", "return": "result"},
                },
            },
        ),
    )

    assert [step["step_id"] for step in merged] == [
        "A_prime",
        "B",
        "D",
        "C_prime",
    ]


def test_mixed_scope_merge_rejects_ambiguous_single_step_across_barrier() -> None:
    def prior(step_id: str) -> SimpleNamespace:
        payload = {
            "step_id": step_id,
            "capability_id": "test_capability",
            "args": {},
        }
        return SimpleNamespace(
            step_id=step_id,
            to_payload=lambda payload=payload: deepcopy(payload),
        )

    with pytest.raises(FunctionalGoalRetryError) as error:
        _merge_scope_step_replacement(
            (prior("A"), prior("B"), prior("C")),
            editable_step_ids=("A", "C"),
            replacement_steps=(
                {
                    "step_id": "combined",
                    "capability_id": "test_capability",
                    "args": {},
                },
            ),
        )

    assert error.value.code == "functional.goal_repair_step_order_invalid"
    assert error.value.details["frozen_barrier_step_ids"] == ["B"]


def test_failed_scope_owned_answer_producer_opens_goal_answer_repair(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = deepcopy(fixture.correct_payload)
    scope_ii = next(
        item
        for item in iter_scopes(payload["root_scope"])
        if item["scope_ref"] == "ii"
    )
    goal_ii = next(
        item for item in scope_ii["goals"] if item["goal_ref"] == FAILED_GOAL_REF
    )
    scope_ii["steps"] = goal_ii.pop("steps")
    old_answer = deepcopy(goal_ii["answer_from"])
    failed_answer_step = next(
        item
        for item in scope_ii["steps"]
        if item["step_id"] == old_answer["step_id"]
    )
    failed_answer_step["args"]["minimum_value"] = "not_a_real_ref"

    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=execution,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )

    goal_authority = authority.goal_authorities[FAILED_GOAL_REF]
    assert goal_authority.status == "failed"
    assert goal_authority.editable is True
    assert FAILED_GOAL_REF in authority.editable_goal_refs
    assert "ii" in authority.editable_scope_refs
    response_schema = functional_goal_repair_schema_for_authority(authority)
    goal_schema = response_schema["properties"]["goal_replacements"]
    assert goal_schema["required"] == [FAILED_GOAL_REF]
    assert FAILED_GOAL_REF in goal_schema["properties"]

    corrected_scope_steps = deepcopy(scope_ii["steps"])
    replacement_answer_step_id = "solve_parameter_from_minimum_ii_retry"
    corrected_answer_step = next(
        item
        for item in corrected_scope_steps
        if item["step_id"] == old_answer["step_id"]
    )
    corrected_answer_step["step_id"] = replacement_answer_step_id
    corrected_answer_step["args"]["minimum_value"] = "minimum_value"
    repair_payload = {
        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
        "base_plan_id": authority.base_plan_id,
        "base_retry_context_id": authority.retry_context_id,
        "goal_replacements": {
            FAILED_GOAL_REF: {
                "steps": [],
                "answer_from": {
                    "step_id": replacement_answer_step_id,
                    "return": old_answer["return"],
                },
            }
        },
        "scope_step_replacements": {
            "ii": {"steps": corrected_scope_steps},
        },
    }
    application = FunctionalGoalRepairService().apply_json(
        json.dumps(repair_payload, ensure_ascii=False),
        base_plan=authority.base_plan,
        authority=authority,
        capability_catalog=fixture.capability_catalog,
    )

    repaired_payload = application.plan.to_payload()
    repaired_goal = goal(repaired_payload, FAILED_GOAL_REF)
    assert repaired_goal["answer_from"]["step_id"] == replacement_answer_step_id
    assert repaired_goal["answer_from"]["return"] == old_answer["return"]
    repaired_execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(repaired_payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    assert repaired_execution.checkpoint is not None
    assert repaired_execution.checkpoint.all_required_goals_verified is True


def test_blocked_scope_owned_answer_producer_allows_answer_only_rebinding(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = deepcopy(fixture.failed_payload)
    scope_ii = next(
        item
        for item in iter_scopes(payload["root_scope"])
        if item["scope_ref"] == "ii"
    )
    goal_ii = next(
        item for item in scope_ii["goals"] if item["goal_ref"] == FAILED_GOAL_REF
    )
    scope_ii["steps"] = goal_ii.pop("steps")

    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=execution,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )

    goal_authority = authority.goal_authorities[FAILED_GOAL_REF]
    assert goal_authority.status == "blocked"
    assert goal_authority.editable is False
    assert FAILED_GOAL_REF not in authority.editable_goal_refs
    assert "ii" in authority.editable_scope_refs
    assert FAILED_GOAL_REF in authority.editable_answer_goal_refs
    response_schema = functional_goal_repair_schema_for_authority(authority)
    goal_schema = response_schema["properties"]["goal_replacements"]
    assert goal_schema["required"] == []
    assert goal_schema["properties"] == {}
    answer_schema = response_schema["properties"][
        "answer_binding_replacements"
    ]
    assert set(answer_schema["properties"]) == {FAILED_GOAL_REF}

    correct_goal = goal(fixture.correct_payload, FAILED_GOAL_REF)
    editable_step_ids = set(authority.editable_scope_step_ids["ii"])
    replacement_steps = [
        deepcopy(item)
        for item in correct_goal["steps"]
        if item["step_id"] in editable_step_ids
    ]
    previous_answer_step = correct_goal["answer_from"]["step_id"]
    replacement_answer_step = f"{previous_answer_step}_retry"
    next(
        item
        for item in replacement_steps
        if item["step_id"] == previous_answer_step
    )["step_id"] = replacement_answer_step
    repair_payload = {
        "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
        "base_plan_id": authority.base_plan_id,
        "base_retry_context_id": authority.retry_context_id,
        "goal_replacements": {},
        "scope_step_replacements": {
            "ii": {"steps": replacement_steps},
        },
        "answer_binding_replacements": {
            FAILED_GOAL_REF: {
                "answer_from": {
                    "step_id": replacement_answer_step,
                    "return": correct_goal["answer_from"]["return"],
                }
            }
        },
    }
    application = FunctionalGoalRepairService().apply_json(
        json.dumps(repair_payload, ensure_ascii=False),
        base_plan=authority.base_plan,
        authority=authority,
        capability_catalog=fixture.capability_catalog,
    )
    repaired_goal = goal(application.plan.to_payload(), FAILED_GOAL_REF)
    assert "steps" not in repaired_goal
    assert repaired_goal["answer_from"] == {
        "step_id": replacement_answer_step,
        "return": correct_goal["answer_from"]["return"],
    }
    repaired_execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(application.plan.to_payload(), ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    assert repaired_execution.checkpoint is not None
    assert repaired_execution.checkpoint.all_required_goals_verified is True


def test_restore_authority_separates_publication_from_reads_and_writes(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = fixture.retry_authority
    seed = retry_module._restored_seed(
        authority,
        fixture.execution,
        next_plan=authority.base_plan,
    )
    assert seed.conditions
    assert set(seed.typed_value_index.conditions) == set(
        seed.conditions
    )
    for condition_id, value in seed.conditions.items():
        assert seed.typed_value_index.condition_value(condition_id) is value
    assert seed.call_result_records
    for key, record in seed.call_result_records.items():
        assert (record.call_id, record.return_name) == key
        assert record.runtime_type == record.runtime_value.type
        assert record.scope_id
        assert record.problem_source_provenance is not None
        assert record.prompt_ref == {
            "step_id": record.call_id,
            "return": record.return_name,
        }
    reconciliation = fixture.execution.replay.functional_reconciliation
    assert reconciliation is not None
    binding_context = reconciliation.functional_problem_binding_context
    assert binding_context is not None
    call_id = "derive_y_intercept_C_i"
    current_goals = binding_context.call_goal_bindings[call_id]
    added_goal = next(
        item
        for item in seed.mutable_publication_goal_unit_ids
        if item not in current_goals
    )
    expanded_binding_context = replace(
        binding_context,
        call_goal_bindings={
            **binding_context.call_goal_bindings,
            call_id: (*current_goals, added_goal),
        },
    )
    expanded_reconciliation = replace(
        reconciliation,
        functional_problem_binding_context=expanded_binding_context,
    )

    rebased = rebase_restored_call_seed(seed, expanded_reconciliation)
    assert rebased is not None
    assert call_id in rebased.call_ids

    with pytest.raises(FunctionalRestoredCallBindingError) as source_exc:
        rebase_restored_call_seed(
            replace(
                seed,
                source_read_authorities={
                    **seed.source_read_authorities,
                    call_id: "0" * 64,
                },
            ),
            reconciliation,
        )
    assert source_exc.value.code == (
        "planner.retry_problem_source_binding_drift"
    )

    with pytest.raises(FunctionalRestoredCallBindingError) as write_exc:
        rebase_restored_call_seed(
            replace(
                seed,
                runtime_write_authorities={
                    **seed.runtime_write_authorities,
                    call_id: "0" * 64,
                },
            ),
            reconciliation,
        )
    assert write_exc.value.code == "planner.contract_runtime_destination_drift"

    condition_id = next(iter(seed.conditions))
    condition_value = seed.conditions[condition_id]
    drifted_seed = replace(
        seed,
        conditions={
            **seed.conditions,
            condition_id: replace(
                condition_value,
                kind=f"{condition_value.kind}:drift",
            ),
        },
    )
    with pytest.raises(ValueError, match="changed"):
        transaction_module._restored_conditions(
            drifted_seed,
            parent_context=fixture.planner_state_context,
        )


def test_restored_shared_producer_republishes_all_authored_anonymous_returns(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    correct = load_v2_fixture_payload(case)
    failed = deepcopy(correct)
    failed_scopes = {
        item["scope_ref"]: item
        for item in iter_scopes(failed["root_scope"])
    }
    failed_scopes["ii_2"]["steps"][0]["args"]["minimum_value"] = (
        "not_a_real_ref"
    )
    correct_scopes = {
        item["scope_ref"]: item
        for item in iter_scopes(correct["root_scope"])
    }

    class NankaiAnonymousResultRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                frame = FunctionalPlanAuthorityFrame.from_planning_context(
                    fixture[1]
                )
                plan, report = (
                    ScopedFunctionalPlanValidator()
                    .validate_payload_with_report(failed)
                )
                assert report.ok and plan is not None
                content = functional_plan_content_from_plan(plan, frame=frame)
                return json.dumps(content.to_payload(), ensure_ascii=False)
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
                        "ii_2": {
                            "steps": deepcopy(correct_scopes["ii_2"]["steps"]),
                        }
                    },
                },
                ensure_ascii=False,
            )

    result = ScopedFunctionalGoalRetryService(
        NankaiAnonymousResultRepairClient()
    ).run(
        inputs=fixture[3],
        planning_context=fixture[1],
        problem_binding_catalog=fixture[7],
        handle_registry=fixture[5],
        runtime_context=ContextBuilder().build(fixture[2]),
        planner_state_context=fixture[6],
        problem_payload=fixture[4],
        max_attempts=2,
    )

    assert result.status == "accepted"
    assert result.final_execution is not None
    first_reconciliation = (
        result.attempts[0].execution.replay.functional_reconciliation
    )
    assert first_reconciliation is not None
    shared_call = next(
        item
        for item in first_reconciliation.calls
        if item.call_id == "ii_derive_path_model"
    )
    assert {
        "straightened_endpoint_1",
        "straightened_endpoint_2",
        "path_minimum_expression",
    } <= {item.return_name for item in shared_call.returns}
    final_report = (
        result.final_execution.replay.transactional_attempt_result
        .execution_report
    )
    assert "ii_derive_path_model" in final_report.restored_call_ids
    final_states = {
        item.call_id: item.status for item in final_report.call_states
    }
    assert final_states["ii_2_solve_m"] == "verified"
    assert final_states["ii_2_derive_G"] == "verified"


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
    local_parabola = deepcopy(scope_i_steps[0])
    local_parabola["step_id"] = "retry_local_parabola"

    goal_i2["steps"] = [
        local_c,
        local_d,
        local_parabola,
        *goal_i2["steps"],
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
    assert not execution.checkpoint.all_required_goals_verified
    assert {
        item["code"] for item in execution.checkpoint.root_issues
    } == set()
    strict_scope_issues = tuple(
        step.typed_issue
        for scope in retry_module._iter_execution_scopes(
            execution.checkpoint.root_scope
        )
        for step in (
            *scope.scope_steps,
            *(item for goal_item in scope.goals for item in goal_item.steps),
        )
        if step.typed_issue is not None
    )
    assert any(
        issue.get("code")
        == "functional.equal_length_ray_point_state_unavailable"
        and issue.get("subjects", [{}])[0].get("ref") == "D"
        for issue in strict_scope_issues
    )
    assert all(
        "derive_translated_D_i" not in issue.get("repair_call_ids", ())
        for issue in strict_scope_issues
    )


def test_named_parabola_uses_latest_state_and_runtime_closes_duplicate_point(
    tmp_path,
) -> None:
    """D-only closure and B=(3/a,0)->(3,0) are one state sequence."""

    case = "tj-2026-heping-yimo-25"
    fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = load_v2_fixture_payload(case)
    scopes = {
        item["scope_ref"]: item
        for item in iter_scopes(payload["root_scope"])
    }
    root_steps = payload["root_scope"]["steps"]
    root_steps.insert(
        0,
        {
            "step_id": "problem_state_parabola",
            "capability_id": "quadratic_from_constraints",
            "args": {
                "curve_point": "A",
                "free_parameters": "a",
            },
            "return_expectations": {"parabola": "open_state"},
            "intent": "建立具名抛物线的开放参数状态。",
        },
    )
    root_steps.append(
        {
            "step_id": "problem_open_x_intercept_B",
            "capability_id": "quadratic_x_axis_intercept_point",
            "args": {
                "parabola": "parabola",
                "known_point": "A",
            },
            "output_targets": {"point": "B"},
            "return_expectations": {"point": "open_state"},
            "intent": "在开放状态中求另一个横轴交点。",
        }
    )
    scopes["i"]["steps"][0]["args"] = {"curve_point": "D"}
    ii_steps = scopes["ii"]["goals"][0]["steps"]
    scopes["ii"]["goals"][0]["steps"] = [
        item
        for item in ii_steps
        if item["step_id"] != "derive_x_intercept_B_ii"
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

    assert execution.checkpoint is not None
    assert execution.checkpoint.all_required_goals_verified
    attempt = execution.replay.transactional_attempt_result
    assert not any(
        item.code == "planner.runtime_state_equivalence_conflict"
        for item in attempt.root_issues
    )
    values = attempt.execution_report.runtime_result_values
    parabola = values[("derive_parabola_i", "parabola")].value
    x = next(item for item in parabola.free_symbols if item.name == "x")
    assert sp.simplify(
        parabola - (x**2 - 2 * x - 3)
    ) == 0
    assert values[("derive_x_intercept_B_i", "point")].value == (
        sp.Integer(3),
        sp.Integer(0),
    )


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


def test_parseable_plan_with_invalid_answer_source_uses_goal_repair(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    content = json.loads(_content_json(fixture, fixture.correct_payload))
    content["goal_plans"][FAILED_GOAL_REF]["answer_from"] = {
        "step_id": "missing_answer_producer",
        "return": "parameter_value",
    }

    class GoalAnswerRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return json.dumps(content, ensure_ascii=False)
            assert payload["planner_protocol"] == FUNCTIONAL_GOAL_REPAIR_CONTRACT
            retry_context = payload["planner_payload"]["goal_retry_context"]
            replacement = goal(fixture.correct_payload, FAILED_GOAL_REF)
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry_context["base_plan_id"],
                    "base_retry_context_id": retry_context[
                        "base_retry_context_id"
                    ],
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": deepcopy(replacement["steps"]),
                            "answer_from": deepcopy(replacement["answer_from"]),
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = GoalAnswerRepairClient()
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
        FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    ]
    first = result.attempts[0]
    assert first.plan is not None
    assert first.result_retry_authority is not None
    assert first.result_retry_authority.editable_goal_refs == (
        FAILED_GOAL_REF,
    )


def test_parseable_capability_schema_error_uses_goal_repair(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    content = json.loads(_content_json(fixture, fixture.correct_payload))
    failed_goal_ref = "i_2.E"
    target = next(
        item
        for item in content["goal_plans"][failed_goal_ref]["steps"]
        if item["step_id"] == "derive_x_intercept_B_i"
    )
    target["args"]["known_point"] = {
        "step_id": "derive_equal_angle_i",
        "return": "angle_equality",
    }

    class GoalAuthoringRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return json.dumps(content, ensure_ascii=False)
            assert payload["planner_protocol"] == FUNCTIONAL_GOAL_REPAIR_CONTRACT
            retry_context = payload["planner_payload"]["goal_retry_context"]
            replacement = goal(fixture.correct_payload, failed_goal_ref)
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry_context["base_plan_id"],
                    "base_retry_context_id": retry_context[
                        "base_retry_context_id"
                    ],
                    "goal_replacements": {
                        failed_goal_ref: {
                            "steps": deepcopy(replacement["steps"]),
                            "answer_from": deepcopy(replacement["answer_from"]),
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = GoalAuthoringRepairClient()
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
        FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    ]
    first = result.attempts[0]
    assert first.plan is not None
    assert first.content_validation_report is not None
    assert first.content_validation_report.issues[0].code == (
        "functional.plan_content_schema_invalid"
    )
    assert first.result_retry_authority is not None
    assert first.result_retry_authority.editable_goal_refs == (failed_goal_ref,)
    assert first.result_retry_authority.goal_authorities[
        failed_goal_ref
    ].status == "failed"
    assert first.result_retry_authority is not None
    assert first.result_retry_authority.editable_goal_refs == (failed_goal_ref,)


def test_pass1_draft_does_not_veto_a_valid_current_final_plan(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    content = json.loads(_content_json(fixture, fixture.correct_payload))
    reduction = next(
        item
        for item in content["goal_plans"][FAILED_GOAL_REF]["steps"]
        if item["capability_id"] == "equal_length_ray_path_reduction"
    )
    reduction["return_expectations"] = {"point": "closed_state"}
    correct_execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(fixture.correct_payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )

    class CanonicalizingExecution:
        def execute_raw_json(self, *args, **kwargs):
            return correct_execution

    class DraftClient:
        def complete(self, payload):
            assert payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
            return json.dumps(content, ensure_ascii=False)

    result = ScopedFunctionalGoalRetryService(
        DraftClient(),
        execution_service=CanonicalizingExecution(),
    ).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=1,
    )

    assert result.status == "accepted"
    assert len(result.attempts) == 1
    attempt = result.attempts[0]
    assert attempt.content_validation_report is not None
    assert not attempt.content_validation_report.ok
    assert attempt.final_plan_contract_validation is not None
    assert attempt.final_plan_contract_validation.ok
    assert (
        attempt.final_plan_contract_validation.final_plan_id
        == attempt.final_plan_contract_validation.round_trip_plan_id
    )


def test_runtime_passed_final_contract_issue_opens_only_owning_goal(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    content = json.loads(_content_json(fixture, fixture.correct_payload))
    reduction = next(
        item
        for item in content["goal_plans"][FAILED_GOAL_REF]["steps"]
        if item["capability_id"] == "equal_length_ray_path_reduction"
    )
    reduction["return_expectations"] = {"point": "closed_state"}
    correct_execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(fixture.correct_payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )

    class ContractDraftExecution:
        def __init__(self) -> None:
            self.calls = 0

        def execute_raw_json(self, raw_plan, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                authored, report = (
                    ScopedFunctionalPlanValidator().validate_payload_with_report(
                        json.loads(raw_plan)
                    )
                )
                assert report.ok and authored is not None
                return replace(correct_execution, canonical_plan=authored)
            return correct_execution

    class ContractRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            if payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT:
                return json.dumps(content, ensure_ascii=False)
            retry_context = payload["planner_payload"]["goal_retry_context"]
            replacement = goal(fixture.correct_payload, FAILED_GOAL_REF)
            return json.dumps(
                {
                    "schema_version": FUNCTIONAL_GOAL_REPAIR_CONTRACT,
                    "base_plan_id": retry_context["base_plan_id"],
                    "base_retry_context_id": retry_context[
                        "base_retry_context_id"
                    ],
                    "goal_replacements": {
                        FAILED_GOAL_REF: {
                            "steps": deepcopy(replacement["steps"]),
                            "answer_from": deepcopy(replacement["answer_from"]),
                        }
                    },
                    "scope_step_replacements": {},
                },
                ensure_ascii=False,
            )

    client = ContractRepairClient()
    result = ScopedFunctionalGoalRetryService(
        client,
        execution_service=ContractDraftExecution(),
    ).run(
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
    assert [item.planner_protocol for item in result.attempts] == [
        FUNCTIONAL_PLAN_CONTENT_CONTRACT,
        FUNCTIONAL_GOAL_REPAIR_CONTRACT,
    ]
    first = result.attempts[0]
    assert first.execution is not None
    assert first.execution.checkpoint is not None
    assert first.execution.checkpoint.all_required_goals_verified
    assert first.final_plan_contract_validation is not None
    assert not first.final_plan_contract_validation.ok
    assert first.result_retry_authority is not None
    assert first.result_retry_authority.editable_goal_refs == (FAILED_GOAL_REF,)
    issue = first.result_retry_authority.goal_authorities[
        FAILED_GOAL_REF
    ].issues[0]
    assert issue["stage"] == "authoring_contract"
    assert issue["repair_action"] == "replace_goal"


def test_problem_binding_error_is_nonretryable_and_classified(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)

    class BindingFailureExecution:
        def execute_raw_json(self, *args, **kwargs):
            raise ProblemPlanningBindingError(
                "planner.problem_source_binding_drift",
                "$.calls['solve_c'].returns['parameter_value']",
                "B1 return target differs from Problem authority",
                details={"stage": "C3"},
            )

    client = _RepairingClient(fixture)
    result = ScopedFunctionalGoalRetryService(
        client,
        execution_service=BindingFailureExecution(),
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
    assert len(client.requests) == 1
    assert len(result.attempts) == 1
    error = result.attempts[0].error
    assert error is not None
    assert error.code == "planner.problem_source_binding_drift"
    assert error.retryable is False
    assert error.details == {"stage": "C3"}


def test_conflicting_cross_container_step_retries_as_full_plan(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    valid_content = json.loads(_content_json(fixture, fixture.correct_payload))
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    goal_ref = "i_2.E"
    owner_scope = frame.goal_owners[goal_ref]
    conflicting = deepcopy(valid_content["goal_plans"][goal_ref]["steps"][0])
    conflicting["intent"] = "conflicting duplicate definition"
    malformed = deepcopy(valid_content)
    malformed.setdefault("scope_steps", {}).setdefault(owner_scope, []).append(
        conflicting
    )

    class OwnershipRepairClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            assert payload["planner_protocol"] == FUNCTIONAL_PLAN_CONTENT_CONTRACT
            if len(self.requests) == 1:
                return json.dumps(malformed, ensure_ascii=False)
            planner_payload = payload["planner_payload"]
            feedback = planner_payload["authoring_feedback"]
            assert feedback[0]["code"] == "functional.step_id_conflict"
            assert feedback[0]["details"]["owners"] == [
                f"scope:{owner_scope}",
                f"goal:{goal_ref}",
            ]
            assert planner_payload["previous_invalid_content"] == malformed
            return json.dumps(valid_content, ensure_ascii=False)

    client = OwnershipRepairClient()
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
    assert result.attempts[0].error is not None
    assert result.attempts[0].error.code == "functional.step_id_conflict"
    assert result.attempts[0].plan is None


def test_exact_cross_container_step_copy_is_normalized_without_retry(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = json.loads(_content_json(fixture, fixture.correct_payload))
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    goal_ref = "i_2.E"
    owner_scope = frame.goal_owners[goal_ref]
    payload.setdefault("scope_steps", {}).setdefault(owner_scope, []).append(
        deepcopy(payload["goal_plans"][goal_ref]["steps"][0])
    )

    class DuplicateClient:
        def __init__(self) -> None:
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            return json.dumps(payload, ensure_ascii=False)

    client = DuplicateClient()
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
    assert any(
        item.code == "functional.cross_container_step_duplicate_removed"
        for item in result.attempts[0].content_normalizations
    )


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
                candidate_ids = {
                    item["step_id"] for item in issue["details"]["candidates"]
                }
                assert issue["details"]["candidate_count"] == len(candidate_ids)
                assert {
                    "solve_parameter_from_minimum_ii",
                    "solve_parameter_duplicate_ii",
                } <= candidate_ids
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
    assert result.attempts[1].error.details["candidate_count"] >= 2
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


def test_named_goal_result_feeds_repaired_goal_through_source_ref(
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
                    item["args"]["parabola"] = "parabola"
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
    i_2_goal_id = next(
        item.goal_unit_id
        for item in fixture.planning_context.goal_views
        if item.answer_ref.ref == "i_2.E"
    )
    producer = result.final_execution.authority.step_authorities[
        "derive_parabola_i"
    ]
    assert producer.consumer_goal_unit_ids == tuple(sorted((i_1_goal_id, i_2_goal_id)))
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
