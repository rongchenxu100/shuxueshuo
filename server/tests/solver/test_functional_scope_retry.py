from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionGoal,
    FunctionalGoalExecutionScope,
    FunctionalGoalExecutionStep,
)
from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FUNCTIONAL_ANNOTATED_PLAN_CONTRACT,
    FunctionalAnnotatedPlanProjector,
    FunctionalScopeRepairCompiler,
    FunctionalScopeRetryAuthorityProjector,
    FunctionalScopeRetryError,
    functional_annotated_plan_schema,
    functional_scope_repair_schema,
    functional_scope_repair_schema_for_authority,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    scoped_functional_plan_id,
)

from _functional_goal_retry_support import (
    FAILED_STEP_ID,
    goal_retry_fixture,
    iter_scopes,
)


ROOT = Path(__file__).resolve().parents[3]


def _canonical_shape(scope):
    return {
        "scope_ref": scope.scope_ref,
        "scope_steps": [item.step_id for item in scope.steps],
        "goals": {
            goal.goal_ref: [item.step_id for item in goal.steps]
            for goal in scope.goals
        },
        "children": [_canonical_shape(item) for item in scope.children],
    }


def _annotated_shape(scope):
    return {
        "scope_ref": scope.scope_ref,
        "scope_steps": [item.step_id for item in scope.scope_steps],
        "goals": {
            goal_ref: [item.step_id for item in goal.steps]
            for goal_ref, goal in scope.goals.items()
        },
        "children": [_annotated_shape(item) for item in scope.children],
    }


def _walk_annotated(scope):
    yield scope
    for child in scope.children:
        yield from _walk_annotated(child)


def _replace_execution_step(scope, step_id, transform):
    def replace_step(step: FunctionalGoalExecutionStep):
        return transform(step) if step.step_id == step_id else step

    return FunctionalGoalExecutionScope(
        scope_ref=scope.scope_ref,
        scope_steps=tuple(replace_step(item) for item in scope.scope_steps),
        goals=tuple(
            FunctionalGoalExecutionGoal(
                goal_ref=goal.goal_ref,
                status=goal.status,
                steps=tuple(replace_step(item) for item in goal.steps),
            )
            for goal in scope.goals
        ),
        children=tuple(
            _replace_execution_step(child, step_id, transform)
            for child in scope.children
        ),
    )


def _scope_repair_payload(plan, *scope_refs):
    canonical = plan.to_payload()
    by_ref = {
        scope["scope_ref"]: scope
        for scope in iter_scopes(canonical["root_scope"])
    }

    def pure_step(step):
        value = deepcopy(step)
        value.pop("return_expectations", None)
        value.pop("execution", None)
        return value

    replacements = {}
    for scope_ref in scope_refs:
        scope = by_ref[scope_ref]
        replacements[scope_ref] = {
            "scope_steps": [pure_step(item) for item in scope.get("steps", ())],
            "goals": {
                goal["goal_ref"]: {
                    "steps": [pure_step(item) for item in goal.get("steps", ())],
                    "answer_from": deepcopy(goal["answer_from"]),
                }
                for goal in scope.get("goals", ())
            },
        }
    return {
        "schema_version": "functional-scope-repair/v1",
        "scope_replacements": replacements,
    }


def test_annotated_plan_is_canonical_tree_with_three_state_execution(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    before_hash = scoped_functional_plan_id(fixture.failed_plan)

    annotated, authority = FunctionalAnnotatedPlanProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
        editable_scope_refs=("ii",),
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )
    payload = annotated.to_prompt_payload()

    assert payload["schema_version"] == FUNCTIONAL_ANNOTATED_PLAN_CONTRACT
    assert _annotated_shape(annotated.root_scope) == _canonical_shape(
        authority.base_plan.root_scope
    )
    assert scoped_functional_plan_id(fixture.failed_plan) == before_hash
    assert not tuple(
        Draft202012Validator(functional_annotated_plan_schema()).iter_errors(
            payload
        )
    )
    scopes = {item.scope_ref: item for item in _walk_annotated(annotated.root_scope)}
    assert {key: value.retry_editable for key, value in scopes.items()} == {
        "problem": False,
        "i": False,
        "i_1": False,
        "i_2": False,
        "ii": True,
    }
    all_steps = [
        step
        for scope in scopes.values()
        for step in (
            *scope.scope_steps,
            *(step for goal in scope.goals.values() for step in goal.steps),
        )
    ]
    assert all(
        item.execution.status in {"succeeded", "failed", "not_run"}
        for item in all_steps
    )
    failed = next(item for item in all_steps if item.step_id == FAILED_STEP_ID)
    assert failed.execution.status == "failed"
    assert failed.execution.error is not None
    assert failed.execution.error["stage"] == "validation"
    blocked = next(
        item
        for item in all_steps
        if item.step_id == "solve_parameter_from_minimum_ii"
    )
    assert blocked.execution.status == "not_run"
    assert blocked.execution.blocked_by == (FAILED_STEP_ID,)


def test_annotated_plan_schema_snapshot_matches_runtime_schema() -> None:
    checked_in = json.loads(
        (ROOT / "internal/schemas/functional-annotated-plan.schema.json").read_text()
    )
    assert checked_in == functional_annotated_plan_schema()


def test_scope_repair_schema_snapshot_matches_runtime_schema() -> None:
    checked_in = json.loads(
        (ROOT / "internal/schemas/functional-scope-repair.schema.json").read_text()
    )
    assert checked_in == functional_scope_repair_schema()


def test_annotated_plan_projects_all_materialized_outputs_and_goal_answers(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    annotated, _ = FunctionalAnnotatedPlanProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
        editable_scope_refs=("ii",),
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )
    scopes = {item.scope_ref: item for item in _walk_annotated(annotated.root_scope)}
    derive_parabola = next(
        item
        for item in scopes["i"].scope_steps
        if item.step_id == "derive_parabola_i"
    )
    assert set(derive_parabola.execution.outputs) == {"coefficients", "parabola"}
    assert derive_parabola.execution.outputs["parabola"] == {
        "runtime_type": "Parabola",
        "value": "x**2 - 2*x - 3",
    }
    point_goal = scopes["i_2"].goals["i_2.E"]
    assert point_goal.execution == {
        "status": "succeeded",
        "answer": {"runtime_type": "Point", "value": ("-2/3", "-11/9")},
    }
    assert point_goal.required_answer == {
        "target_ref": "E",
        "answer_type": "Point",
    }
    prompt_text = json.dumps(annotated.to_prompt_payload(), ensure_ascii=False)
    for forbidden in (
        "StateVersion",
        "CallResult",
        "checkpoint_id",
        "transaction_ok",
        "<internal-identity-omitted>",
    ):
        assert forbidden not in prompt_text


@pytest.mark.parametrize(
    "bad_output",
    [
        {
            "return": "minimum_expression",
            "runtime_type": "Expression",
            "value_omitted_reason": "transport_limit",
        },
        {
            "return": "minimum_expression",
            "runtime_type": "Expression",
            "value": {"state_version": "private"},
        },
    ],
)
def test_runtime_output_projection_fails_loud_on_omission_or_internal_identity(
    tmp_path,
    bad_output,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    checkpoint = fixture.execution.checkpoint
    assert checkpoint is not None
    verified_step_id = "derive_parabola_i"
    root_scope = _replace_execution_step(
        checkpoint.root_scope,
        verified_step_id,
        lambda item: replace(item, actual_outputs=(bad_output,)),
    )
    execution = replace(
        fixture.execution,
        checkpoint=replace(checkpoint, root_scope=root_scope),
    )

    with pytest.raises(FunctionalScopeRetryError) as captured:
        FunctionalAnnotatedPlanProjector().project(
            plan=fixture.failed_plan,
            execution=execution,
            editable_scope_refs=("ii",),
            planning_context=fixture.planning_context,
            binding_catalog=fixture.binding_catalog,
        )

    assert captured.value.code == (
        "functional.retry_runtime_output_projection_invalid"
    )
    assert captured.value.retryable is False


def test_scope_authority_opens_owner_scope_without_step_permissions(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    annotated, _ = FunctionalAnnotatedPlanProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
        editable_scope_refs=authority.editable_scope_refs,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )

    assert authority.editable_scope_refs == ("ii",)
    payload = annotated.to_prompt_payload()
    text = json.dumps(payload, ensure_ascii=False)
    assert '"retry_editable": true' in text
    for removed in (
        "repair_permission",
        "editable_step_ids",
        "frozen_step_ids",
        "promoted_step_ids",
    ):
        assert removed not in text


def test_scope_repair_schema_requires_exact_scopes_and_direct_goals(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    schema = functional_scope_repair_schema_for_authority(authority)
    valid = _scope_repair_payload(fixture.failed_plan, "ii")

    assert not tuple(Draft202012Validator(schema).iter_errors(valid))
    assert schema["properties"]["scope_replacements"]["required"] == ["ii"]
    goals = schema["properties"]["scope_replacements"]["properties"]["ii"][
        "properties"
    ]["goals"]
    assert goals["required"] == ["ii.a"]
    assert goals["additionalProperties"] is False

    missing_goal = deepcopy(valid)
    missing_goal["scope_replacements"]["ii"]["goals"] = {}
    assert tuple(Draft202012Validator(schema).iter_errors(missing_goal))

    extra_scope = deepcopy(valid)
    extra_scope["scope_replacements"]["i"] = {
        "scope_steps": [],
        "goals": {},
    }
    assert tuple(Draft202012Validator(schema).iter_errors(extra_scope))

    annotated_step = deepcopy(valid)
    annotated_step["scope_replacements"]["ii"]["goals"]["ii.a"]["steps"][0][
        "execution"
    ] = {"status": "not_run"}
    assert tuple(Draft202012Validator(schema).iter_errors(annotated_step))


def test_scope_repair_applies_complete_scope_atomically_and_preserves_children(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    payload = _scope_repair_payload(fixture.failed_plan, "ii")
    application = FunctionalScopeRepairCompiler().apply_json(
        json.dumps(payload, ensure_ascii=False),
        base_plan=fixture.failed_plan,
        authority=authority,
    )

    assert application.validation_report.ok
    assert application.plan.root_scope.children[0] == (
        fixture.failed_plan.root_scope.children[0]
    )
    assert application.plan.root_scope.children[1].scope_ref == "ii"
    assert all(
        not step.return_expectations
        for step in application.plan.root_scope.children[1].goals[0].steps
    )

    stale_base = replace(
        fixture.failed_plan,
        root_scope=replace(fixture.failed_plan.root_scope, children=()),
    )
    with pytest.raises(FunctionalScopeRetryError) as captured:
        FunctionalScopeRepairCompiler().apply_json(
            json.dumps(payload),
            base_plan=stale_base,
            authority=authority,
        )
    assert captured.value.code == "functional.scope_repair_stale_plan"
