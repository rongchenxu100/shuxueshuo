from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalExecutionRestoreState,
    FunctionalGoalExecutionGoal,
    FunctionalGoalExecutionScope,
    FunctionalGoalExecutionStep,
    ScopedFunctionalGoalExecutionService,
    _build_checkpoint,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FunctionalGoalRetryProjector,
    _iter_execution_scopes,
    _retry_scope_prompt,
    _scope_authority,
    _scope_step_authority,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)

from _functional_goal_retry_support import (
    FAILED_GOAL_REF,
    FAILED_STEP_ID,
    goal_retry_fixture,
    published_goal_retry_fixture,
    step,
)
from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload


def test_strict_goal_authority_freezes_only_fully_verified_goals(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = fixture.retry_authority

    assert {
        key: (item.status, item.editable)
        for key, item in authority.goal_authorities.items()
    } == {
        "i_1.parabola": ("solved", False),
        "i_2.E": ("solved", False),
        FAILED_GOAL_REF: ("failed", True),
    }
    for goal_ref in ("i_1.parabola", "i_2.E"):
        assert all(authority.goal_authorities[goal_ref].checks.values())
    assert authority.goal_authorities[FAILED_GOAL_REF].checks[
        "typed_checkpoint_restorable"
    ] is False
    assert authority.editable_goal_refs == (FAILED_GOAL_REF,)


def test_mixed_scope_projects_editable_and_frozen_step_ids(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    root = fixture.retry_authority.base_plan.root_scope
    frozen_step, editable_step = root.steps[:2]
    solved = next(
        item
        for item in fixture.retry_authority.goal_authorities.values()
        if item.status == "solved"
    )
    failed = fixture.retry_authority.goal_authorities[FAILED_GOAL_REF]

    editable, frozen = _scope_step_authority(
        fixture.retry_authority.base_plan,
        goal_authorities={
            solved.goal_ref: replace(
                solved,
                closure_step_ids=(frozen_step.step_id,),
            ),
            failed.goal_ref: replace(
                failed,
                closure_step_ids=(editable_step.step_id,),
            ),
        },
        editable_scope_refs=(root.scope_ref,),
        frozen_scope_refs=(),
        failed_scope_step_ids=frozenset({editable_step.step_id}),
    )

    assert editable == {root.scope_ref: (editable_step.step_id,)}
    assert frozen == {root.scope_ref: (frozen_step.step_id,)}

    checkpoint = fixture.execution.checkpoint
    assert checkpoint is not None
    statuses = {
        scope.scope_ref: "context"
        for scope in _iter_execution_scopes(checkpoint.root_scope)
    }
    statuses[root.scope_ref] = "editable"
    prompt_scope = _retry_scope_prompt(
        checkpoint.root_scope,
        planning_context=fixture.planning_context,
        goal_authorities=fixture.retry_authority.goal_authorities,
        scope_statuses=statuses,
        step_promotions={},
        editable_scope_step_ids=editable,
        frozen_scope_step_ids=frozen,
    )
    assert prompt_scope["editable_step_ids"] == [editable_step.step_id]
    assert prompt_scope["frozen_step_ids"] == [frozen_step.step_id]


def test_goal_closure_keeps_implicit_materialized_state_dependencies(
    tmp_path,
) -> None:
    fixture = published_goal_retry_fixture(tmp_path)
    closure = set(
        fixture.retry_authority.goal_authorities["ii.a"].closure_step_ids
    )

    assert {
        "derive_y_intercept_C_i",
        "derive_translated_D_i",
        "derive_parametric_parabola_ii",
        "derive_x_intercept_B_ii",
        "reduce_equal_length_ray_path_ii",
        "solve_parameter_from_minimum_ii",
    } <= closure


def test_retry_context_keeps_failed_goal_prefix_results_but_does_not_freeze_them(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = fixture.retry_authority.retry_context.to_prompt_payload()
    failed = _prompt_goal(payload["root_scope"], FAILED_GOAL_REF)
    statuses = {item["step_id"]: item["status"] for item in failed["steps"]}

    assert statuses["derive_parametric_parabola_ii"] == "runtime_verified"
    assert statuses["derive_x_intercept_B_ii"] == "runtime_verified"
    assert statuses["reduce_equal_length_ray_path_ii"] == "authority_invalid"
    assert statuses["solve_parameter_from_minimum_ii"] == (
        "blocked_by_dependency"
    )
    assert failed["editable"] is True
    assert failed["required_answer"] == {
        "target_ref": "a",
        "answer_type": "ParameterValue",
    }
    assert failed["issues"]
    assert all("authored_step" not in item for item in failed["steps"])
    assert not any(
        step_id in fixture.retry_authority.frozen_scope_refs
        for step_id in statuses
    )


def test_checkpoint_sanitizes_internal_identity_in_typed_issue(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    internal_id = next(iter(fixture.binding_catalog.bindings.values())).runtime_node_id
    checkpoint = _build_checkpoint(
        fixture.failed_plan,
        canonical_plan=fixture.failed_plan,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
        report=fixture.execution.authority_report,
        authority=None,
        replay=None,
        blocked_by={},
        step_issues={
            FAILED_STEP_ID: {
                "stage": "reconciliation_binding",
                "code": "functional.arg_state_unavailable",
                "message": f"computed state is unavailable: {internal_id}",
            }
        },
        root_issues=(),
        blocked_stage="reconciliation_binding",
    )

    prompt = json.dumps(checkpoint.to_prompt_payload(), ensure_ascii=False)
    assert internal_id not in prompt
    assert "<internal-identity-omitted>" not in prompt
    authority = repr(checkpoint.diagnostic_authorities)
    assert internal_id in authority


def test_only_solved_goal_final_answers_are_published(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    publications = fixture.retry_authority.published_goal_results

    assert {item.goal_ref for item in publications} == {
        "i_1.parabola",
        "i_2.E",
    }
    assert {
        (item.producer_step_id, item.return_name) for item in publications
    } == {
        ("derive_parabola_i", "parabola"),
        ("derive_curve_intersection_E_i", "point"),
    }
    assert all(item.value is not None for item in publications)


def test_namespaced_runtime_output_uses_public_return_in_execution_tree(
    tmp_path,
) -> None:
    case = "tj-2026-nankai-yimo-25"
    authority_fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = load_v2_fixture_payload(case)
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    checkpoint = execution.checkpoint
    assert checkpoint is not None and checkpoint.all_required_goals_verified
    output = next(
        item
        for step_item in _execution_steps(checkpoint.root_scope)
        if step_item.step_id == "ii_1_evaluate_minimum"
        for item in step_item.actual_outputs
    )
    assert output["return"] == "evaluated_minimum_expression"


def test_namespaced_runtime_output_is_published_by_typed_answer_alias(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    replay = fixture.execution.replay
    assert replay is not None
    transaction = replay.transactional_attempt_result
    assert transaction is not None
    report = transaction.execution_report
    call_results = tuple(
        replace(
            result,
            runtime_results=tuple(
                replace(
                    output,
                    output_key=f"quadratic_from_constraints.{output.output_key}",
                )
                if output.produced_handle == "answer:i_1.parabola"
                else output
                for output in result.runtime_results
            ),
        )
        for result in report.call_results
    )
    execution = replace(
        fixture.execution,
        replay=replace(
            replay,
            transactional_attempt_result=replace(
                transaction,
                execution_report=replace(report, call_results=call_results),
            ),
        ),
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=fixture.failed_plan,
        execution=execution,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )
    publication = next(
        item
        for item in authority.published_goal_results
        if item.goal_ref == "i_1.parabola"
    )
    assert publication.return_name == "parabola"
    assert publication.value is not None


def test_named_state_return_is_published_without_answer_handle_alias(
    tmp_path,
) -> None:
    case = "tj-2026-hexi-yimo-25"
    authority_fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = deepcopy(load_v2_fixture_payload(case))
    step(payload, "transform_weighted_path_iii")["args"]["moving_point"] = (
        "not_a_real_ref"
    )
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )

    publication = next(
        item
        for item in authority.published_goal_results
        if item.goal_ref == "ii.D"
    )
    assert publication.return_name == "selected_curve_point"
    assert publication.runtime_type == "Point"
    assert publication.value == ["sqrt(2)", "1"]
    assert authority.editable_goal_refs == ("iii.b",)


def test_retry_authority_preserves_authored_scope_tree_without_promotion(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    authority_fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = deepcopy(load_v2_fixture_payload(case))
    scope_i = next(
        item
        for item in payload["root_scope"]["children"]
        if item["scope_ref"] == "i"
    )
    promoted = scope_i.pop("steps")[0]
    promoted["args"] = {
        "curve_points": "point_coordinate_a",
        "free_parameters": "b",
        "target_parameter": "a",
    }
    promoted["return_expectations"] = {"parabola": "closed_state"}
    scope_i_1 = next(
        item
        for item in scope_i["children"]
        if item["scope_ref"] == "i_1"
    )
    scope_i_1["goals"][0]["steps"] = [promoted]
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )

    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )
    canonical = authority.base_plan.to_payload()["root_scope"]
    canonical_i = next(
        item for item in canonical["children"] if item["scope_ref"] == "i"
    )
    assert "steps" not in canonical_i
    canonical_i_1 = next(
        item
        for item in canonical_i["children"]
        if item["scope_ref"] == "i_1"
    )
    assert [
        item["step_id"] for item in canonical_i_1["goals"][0]["steps"]
    ] == [promoted["step_id"]]


def test_missing_typed_checkpoint_means_no_goal_is_frozen(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    checkpoint = replace(
        fixture.execution.checkpoint,
        restore_state=FunctionalExecutionRestoreState.empty(),
    )
    execution = replace(fixture.execution, checkpoint=checkpoint)

    authority = FunctionalGoalRetryProjector().project(
        plan=fixture.failed_plan,
        execution=execution,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )

    assert authority.solved_goal_refs == ()
    assert authority.published_goal_results == ()
    assert FAILED_GOAL_REF in authority.editable_goal_refs


def test_unchanged_solved_goals_survive_an_intermediate_nontransaction_round(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    execution = replace(fixture.execution, replay=None)

    authority = FunctionalGoalRetryProjector().project(
        plan=fixture.retry_authority.base_plan,
        execution=execution,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
        previous_authority=fixture.retry_authority,
    )

    assert authority.solved_goal_refs == fixture.retry_authority.solved_goal_refs
    assert authority.published_goal_results == (
        fixture.retry_authority.published_goal_results
    )
    assert authority.typed_checkpoint_hash == (
        fixture.retry_authority.typed_checkpoint_hash
    )
    assert FAILED_GOAL_REF in authority.editable_goal_refs


def test_solved_goal_inheritance_ignores_intent_only_drift(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = fixture.retry_authority.base_plan.to_payload()
    solved_step_id = fixture.retry_authority.goal_authorities[
        "i_1.parabola"
    ].closure_step_ids[0]
    solved_step = step(payload, solved_step_id)
    solved_step.pop("intent", None)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and plan is not None

    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=replace(fixture.execution, canonical_plan=plan, replay=None),
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
        previous_authority=fixture.retry_authority,
    )

    assert "i_1.parabola" in authority.solved_goal_refs


def test_missing_condition_role_state_is_localized_to_its_goal(tmp_path) -> None:
    case = "tj-2026-hexi-yimo-25"
    authority_fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = deepcopy(load_v2_fixture_payload(case))
    goal_payload = _wire_goal(payload["root_scope"], "ii.D")
    goal_payload["steps"] = [
        item
        for item in goal_payload["steps"]
        if item["step_id"] != "derive_y_intercept_ii"
    ]
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )

    goal_authority = authority.goal_authorities["ii.D"]
    assert goal_authority.status == "failed"
    assert goal_authority.editable is True
    assert any(
        item["code"] == "functional.condition_role_state_unavailable"
        for item in goal_authority.issues
    )
    assert authority.retry_context.to_prompt_payload()[
        "base_retry_context_id"
    ] == authority.retry_context_id


def test_failed_scope_opens_its_answer_goal_not_blocked_consumers(tmp_path) -> None:
    case = "tj-2026-heping-yimo-25"
    authority_fixture = planning_binding_fixture(tmp_path / case, case=case)
    payload = deepcopy(load_v2_fixture_payload(case))
    scope_i = next(
        item
        for item in payload["root_scope"]["children"]
        if item["scope_ref"] == "i"
    )
    scope_i["steps"][0]["args"]["curve_points"] = ["not_a_real_ref"]
    plan, validation = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert validation.ok and plan is not None

    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=authority_fixture[3],
        planning_context=authority_fixture[1],
        problem_binding_catalog=authority_fixture[7],
        handle_registry=authority_fixture[5],
        context=ContextBuilder().build(authority_fixture[2]),
        planner_state_context=authority_fixture[6],
        problem_payload=authority_fixture[4],
    )
    authority = FunctionalGoalRetryProjector().project(
        plan=plan,
        execution=execution,
        planning_context=authority_fixture[1],
        binding_catalog=authority_fixture[7],
    )

    assert authority.editable_scope_refs == ("i",)
    assert authority.editable_goal_refs == ("i_1.parabola",)
    assert authority.goal_authorities["i_1.parabola"].status == "failed"
    assert authority.goal_authorities["i_2.E"].status == "blocked"
    assert authority.goal_authorities["ii.a"].status == "solved"
    goal_ids = {
        item.answer_ref.ref: item.goal_unit_id
        for item in authority_fixture[1].goal_views
    }
    assert set(execution.checkpoint.goal_unit_ids[scope_i["steps"][0]["step_id"]]) == {
        goal_ids["i_1.parabola"],
        goal_ids["i_2.E"],
    }


def test_dead_failed_scope_branch_does_not_reopen_a_solved_goal_scope(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    solved = next(
        item
        for item in fixture.retry_authority.goal_authorities.values()
        if item.status == "solved"
    )
    verified = FunctionalGoalExecutionStep(
        step_id="goal_closure_step",
        status="runtime_verified",
        authored_step={},
    )
    dead_failure = FunctionalGoalExecutionStep(
        step_id="dead_diagnostic_step",
        status="runtime_failed",
        authored_step={},
    )
    root = FunctionalGoalExecutionScope(
        scope_ref="problem",
        children=(
            FunctionalGoalExecutionScope(
                scope_ref="solved_scope",
                scope_steps=(verified, dead_failure),
                goals=(
                    FunctionalGoalExecutionGoal(
                        goal_ref=solved.goal_ref,
                        status="provisionally_solved",
                        steps=(),
                    ),
                ),
            ),
        ),
    )
    checkpoint = replace(
        fixture.execution.checkpoint,
        goal_unit_ids={
            "goal_closure_step": (solved.goal_unit_id,),
            "dead_diagnostic_step": (),
        },
    )

    editable, frozen, statuses = _scope_authority(
        root,
        goal_authorities={solved.goal_ref: solved},
        checkpoint=checkpoint,
    )

    assert editable == ()
    assert frozen == ("solved_scope",)
    assert statuses["solved_scope"] == "frozen"


def _prompt_goal(scope, goal_ref):
    for item in scope.get("goals", []):
        if item["goal_ref"] == goal_ref:
            return item
    for child in scope.get("children", []):
        found = _prompt_goal(child, goal_ref)
        if found is not None:
            return found
    return None


def _wire_goal(scope, goal_ref):
    for item in scope.get("goals", []):
        if item["goal_ref"] == goal_ref:
            return item
    for child in scope.get("children", []):
        found = _wire_goal(child, goal_ref)
        if found is not None:
            return found
    return None


def _execution_steps(scope):
    yield from scope.scope_steps
    for goal_item in scope.goals:
        yield from goal_item.steps
    for child in scope.children:
        yield from _execution_steps(child)
