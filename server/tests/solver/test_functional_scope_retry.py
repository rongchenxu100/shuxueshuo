from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionCheckpointError,
    FunctionalGoalExecutionGoal,
    FunctionalGoalExecutionScope,
    FunctionalGoalExecutionStep,
    ScopedFunctionalGoalExecutionService,
    _public_runtime_result_value,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalBindingContextError,
)
from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FUNCTIONAL_ANNOTATED_PLAN_CONTRACT,
    FunctionalAnnotatedPlanProjector,
    FunctionalScopeRepairCompiler,
    FunctionalScopeRetryAuthority,
    FunctionalScopeRetryAuthorityProjector,
    FunctionalScopeRetryError,
    ScopedFunctionalScopeRetryService,
    _final_contract_retry_feedback,
    _retry_parent_state_rewrite_issue,
    build_scope_retry_restore_seed,
    functional_annotated_plan_schema,
    functional_scope_repair_schema,
    functional_scope_repair_schema_for_authority,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
    functional_plan_content_from_plan,
    functional_plan_content_schema,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    rebase_restored_call_seed,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlan,
    ScopedFunctionalPlanError,
    ScopedFunctionalScope,
    ScopedFunctionalPlanValidator,
    ScopedFunctionalStep,
    ScopedStepResultRef,
    _StepLocation,
    _audit_explicit_dependency,
    scoped_functional_plan_id,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
)

from _functional_scope_retry_support import (
    FAILED_STEP_ID,
    iter_scopes,
    scope_retry_fixture,
    step,
)


ROOT = Path(__file__).resolve().parents[3]


goal_retry_fixture = scope_retry_fixture


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


def _parent_with_descendant_consumer(*, parent_args, parent_targets):
    producer = ScopedFunctionalStep(
        step_id="build_parabola",
        capability_id="quadratic_from_constraints",
        args=parent_args,
        output_targets=parent_targets,
        return_expectations={},
    )
    consumer = ScopedFunctionalStep(
        step_id="read_parabola",
        capability_id="quadratic_vertex_point",
        args={"parabola": ("parabola",)},
        output_targets={},
        return_expectations={},
    )
    return ScopedFunctionalPlan(
        root_scope=ScopedFunctionalScope(
            scope_ref="root",
            steps=(producer,),
            children=(ScopedFunctionalScope(scope_ref="child", steps=(consumer,)),),
        )
    )


def test_parent_state_guard_allows_shared_producer_argument_repair() -> None:
    base = _parent_with_descendant_consumer(
        parent_args={"constraints": ("old",)},
        parent_targets={"parabola": "parabola"},
    )
    candidate = _parent_with_descendant_consumer(
        parent_args={"constraints": ("repaired",)},
        parent_targets={"parabola": "parabola"},
    )

    assert (
        _retry_parent_state_rewrite_issue(
            base_plan=base,
            candidate=candidate,
            editable_scope_refs=("root",),
        )
        is None
    )


def test_parent_state_guard_rejects_changed_output_identity() -> None:
    base = _parent_with_descendant_consumer(
        parent_args={"constraints": ("old",)},
        parent_targets={"parabola": "parabola"},
    )
    candidate = _parent_with_descendant_consumer(
        parent_args={"constraints": ("old",)},
        parent_targets={"coordinate": "parabola"},
    )

    issue = _retry_parent_state_rewrite_issue(
        base_plan=base,
        candidate=candidate,
        editable_scope_refs=("root",),
    )

    assert issue is not None
    assert issue["code"] == "functional.retry_parent_state_rewrite"


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
    scopes = {
        item.scope_ref: item
        for item in _walk_annotated(annotated.root_scope)
    }
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


def test_path_transformation_runtime_projection_fails_at_atomic_boundary() -> None:
    value = {
        "construction": "right_isosceles_triangle",
        "moving_point_name": "N",
        "auxiliary_point_name": "Q",
        "moving_point_ref": "point:problem:N@state-1",
        "auxiliary_point_ref": "point:problem:Q@state-2",
        "fixed_endpoint_refs": (
            "point:problem:A@state-1",
            "point:problem:B@state-1",
        ),
        "transformed_path": "sqrt(2)*(MN+QN)",
    }

    with pytest.raises(FunctionalGoalExecutionCheckpointError) as captured:
        _public_runtime_result_value(
            value,
            runtime_type="PathTransformation",
            forbidden_values=frozenset(
                {"point:problem:N@state-1", "point:problem:Q@state-2"}
            ),
        )

    assert captured.value.code == (
        "functional.retry_runtime_output_projection_invalid"
    )


@pytest.mark.parametrize(
    "synthetic_path",
    (
        "point:ii:G#quadratic-square-reflection",
        "point:ii:N#coupled-segment-reflection",
        "point:iii:Q#weighted-axis-triangle",
    ),
)
def test_synthetic_path_ref_projection_fails_at_atomic_boundary(
    synthetic_path: str,
) -> None:
    with pytest.raises(FunctionalGoalExecutionCheckpointError) as captured:
        _public_runtime_result_value(
            {"point_ref": synthetic_path},
            runtime_type="Point",
            forbidden_values=frozenset(),
        )

    assert captured.value.code == (
        "functional.retry_runtime_output_projection_invalid"
    )


def test_runtime_reference_pair_is_snapshotted_as_refs_not_as_point(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    runtime_context = ContextBuilder().build(fixture.problem)

    projected = runtime_context.to_answer_value(
        {
            "type": "reference_pair",
            "fixed_endpoint_refs": (
                "point:problem:A@state-1",
                "point:problem:B@state-1",
            ),
        }
    )

    assert projected["fixed_endpoint_refs"] == [
        "point:problem:A@state-1",
        "point:problem:B@state-1",
    ]


def test_parameter_outside_free_symbol_basis_is_scope_repairable(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = deepcopy(fixture.correct_payload)
    step(payload, "solve_parameter_from_minimum_ii")["args"]["parameter"] = "b"

    executed = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=executed.canonical_plan,
        execution=executed,
    )
    annotated, _ = FunctionalAnnotatedPlanProjector().project(
        plan=executed.canonical_plan,
        execution=executed,
        editable_scope_refs=authority.editable_scope_refs,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )
    prompt = json.dumps(annotated.to_prompt_payload(), ensure_ascii=False)

    assert "ii" in authority.editable_scope_refs
    assert "functional.parameter_outside_free_symbol_basis" in prompt
    assert '"free_symbol_names": ["a"]' in prompt
    assert '"selected_parameter_names": ["b"]' in prompt
    assert "planner_configuration_error" not in prompt


def test_restore_rebase_drops_call_absent_from_next_authority(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    checkpoint = fixture.execution.checkpoint
    reconciliation = fixture.execution.replay.functional_reconciliation
    assert checkpoint is not None
    assert reconciliation is not None
    seed = checkpoint.restore_state.runtime_seed
    assert seed is not None and seed.call_ids
    missing_call_id = seed.call_ids[0]
    selected = checkpoint.restore_state.seed_for_calls(
        frozenset({missing_call_id})
    )
    next_reconciliation = replace(
        reconciliation,
        calls=tuple(
            item for item in reconciliation.calls if item.call_id != missing_call_id
        ),
    )

    rebased = rebase_restored_call_seed(selected, next_reconciliation)

    assert rebased is not None
    assert rebased.call_ids == ()


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


def test_missing_producer_diagnostic_opens_required_ancestor_scope(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    checkpoint = fixture.execution.checkpoint
    assert checkpoint is not None
    root_scope = _replace_execution_step(
        checkpoint.root_scope,
        FAILED_STEP_ID,
        lambda item: replace(
            item,
            typed_issue={
                "schema_version": "functional-prompt-diagnostic/v1",
                "code": "functional.coupled_segment_path_state_unavailable",
                "category": "input",
                "stage": "reconciliation_binding",
                "retryability": "planner_repairable",
                "message": "Materialize the constructed Point in its owner Scope.",
                "repair_action": "materialize_constructed_point_before_macro",
                "step_id": FAILED_STEP_ID,
                "scope_id": "ii",
                "subjects": ({"ref": "F"},),
                "expected": {"required_scope_ref": "problem"},
                "observed": {"existing_producers": ()},
                "repair_call_ids": (),
            },
        ),
    )
    execution = replace(
        fixture.execution,
        checkpoint=replace(checkpoint, root_scope=root_scope),
    )

    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=execution,
    )

    assert authority.editable_scope_refs == ("problem",)


def test_root_issue_expected_required_scope_opens_ancestor_scope(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(fixture.correct_payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    assert execution.checkpoint is not None
    issue = {
        "schema_version": "functional-prompt-diagnostic/v1",
        "code": "functional.coupled_segment_path_state_unavailable",
        "category": "input",
        "stage": "reconciliation_binding",
        "retryability": "planner_repairable",
        "message": "Materialize the constructed Point in its owner Scope.",
        "step_id": FAILED_STEP_ID,
        "scope_id": "ii",
        "expected": {"required_scope_ref": "problem"},
        "observed": {"existing_producers": []},
    }
    failed = replace(
        execution,
        checkpoint=replace(
            execution.checkpoint,
            root_issues=(issue,),
            all_required_goals_verified=False,
            transaction_ok=False,
        ),
    )

    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=execution.canonical_plan,
        execution=failed,
    )

    assert authority.editable_scope_refs == ("problem",)


def test_scope_authority_opens_scope_for_unbound_goal_root_diagnostic(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    execution = ScopedFunctionalGoalExecutionService().execute_raw_json(
        json.dumps(fixture.correct_payload, ensure_ascii=False),
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
    )
    assert execution.checkpoint is not None
    issue = {
        "code": "functional.required_goal_unbound",
        "stage": "reconciliation_binding",
        "retryability": "planner_repairable",
        "scope_id": "ii",
        "message": "required answer E has no compatible producer",
        "expected": {"expected_object_refs": ["E"]},
        "observed": {"observed_object_ref": "G"},
        "details": {
            "answer_handle": "answer:ii.E",
            "candidate_producer_call_ids": [],
        },
    }
    checkpoint = replace(
        execution.checkpoint,
        root_issues=(issue,),
        all_required_goals_verified=False,
        transaction_ok=False,
    )
    failed = replace(execution, checkpoint=checkpoint)

    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=execution.canonical_plan,
        execution=failed,
    )
    annotated, _ = FunctionalAnnotatedPlanProjector().project(
        plan=execution.canonical_plan,
        execution=failed,
        editable_scope_refs=authority.editable_scope_refs,
        planning_context=fixture.planning_context,
        binding_catalog=fixture.binding_catalog,
    )
    scopes = {item.scope_ref: item for item in _walk_annotated(annotated.root_scope)}

    assert authority.editable_scope_refs == ("ii",)
    assert scopes["ii"].retry_editable is True
    assert scopes["ii"].diagnostics[0]["code"] == (
        "functional.required_goal_unbound"
    )
    assert scopes["ii"].diagnostics[0]["expected"] == {
        "expected_object_refs": ("E",)
    }
    assert scopes["ii"].diagnostics[0]["observed"] == {
        "observed_object_ref": "G"
    }
    assert not scopes["problem"].diagnostics


def test_final_contract_goal_failure_is_forwarded_to_next_repair_prompt() -> None:
    feedback = _final_contract_retry_feedback(
        (
            {
                "code": "functional.required_goal_unbound",
                "path": "$.goal_plans.iii.b",
                "message": (
                    "required answer answer:iii.b has no reachable producer"
                ),
                "details": {"answer_handle": "answer:iii.b"},
                "stage": "validation",
                "retryability": "planner_repairable",
            },
            {
                "code": "functional.final_plan_contract_drift",
                "path": "$",
                "message": "canonical Plan changed while round-tripping",
                "stage": "validation",
            },
        )
    )

    assert feedback == {
        "code": "functional.required_goal_unbound",
        "path": "$.goal_plans.iii.b",
        "message": "required answer answer:iii.b has no reachable producer",
        "details": {
            "answer_handle": "answer:iii.b",
            "diagnostics": [
                {
                    "code": "functional.required_goal_unbound",
                    "path": "$.goal_plans.iii.b",
                    "message": (
                        "required answer answer:iii.b has no reachable producer"
                    ),
                    "details": {"answer_handle": "answer:iii.b"},
                    "stage": "validation",
                    "retryability": "planner_repairable",
                },
                {
                    "code": "functional.final_plan_contract_drift",
                    "path": "$",
                    "message": "canonical Plan changed while round-tripping",
                    "stage": "validation",
                },
            ],
        },
        "stage": "validation",
        "suggestion": (
            "Add the complete executable producer chain for the required "
            "answer in this Scope, then point answer_from to the final "
            "producer return."
        ),
    }


def test_scope_authority_opens_cross_scope_exact_result_consumer(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    payload = deepcopy(fixture.failed_payload)
    scope_ii = next(
        item
        for item in iter_scopes(payload["root_scope"])
        if item["scope_ref"] == "ii"
    )
    scope_ii["children"] = [
        {
            "scope_ref": "ii_child",
            "steps": [
                {
                    "step_id": "consume_exact_result_in_child",
                    "capability_id": "test_consumer",
                    "args": {
                        "value": {
                            "step_id": FAILED_STEP_ID,
                            "return": "minimum_expression",
                        }
                    },
                }
            ],
        }
    ]
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and plan is not None
    execution = replace(fixture.execution, canonical_plan=plan)

    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=plan,
        execution=execution,
    )

    assert authority.editable_scope_refs == ("ii", "ii_child")


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


def test_structural_repair_parser_allows_refs_before_merged_plan_normalization(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    schema = functional_scope_repair_schema_for_authority(
        authority,
    )
    payload = _scope_repair_payload(fixture.failed_plan, "ii")
    goal = payload["scope_replacements"]["ii"]["goals"]["ii.a"]
    goal["steps"][0] = {
        "step_id": "intersection_probe",
        "capability_id": "line_intersection_point",
        "args": {
            "line1_p1": "A",
            "line1_p2": "K",
            "line2_p1": "E",
            "line2_p2": "G",
        },
    }

    assert not tuple(Draft202012Validator(schema).iter_errors(payload))

    goal["steps"][0]["args"]["line1_p1"] = {
        "step_id": "produce_a",
        "return": "point",
    }
    assert not tuple(Draft202012Validator(schema).iter_errors(payload))


def test_scope_repair_parser_discards_dsml_trailer_like_content(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    payload = _scope_repair_payload(fixture.failed_plan, "ii")

    repair = FunctionalScopeRepairCompiler().parse_json(
        json.dumps(payload, ensure_ascii=False)
        + "</｜｜DSML｜｜ parameter>\n</｜｜DSML｜｜ invoke>",
        authority=authority,
        capability_catalog=fixture.capability_catalog,
    )

    assert repair.scope_replacements["ii"].goals["ii.a"].answer_from
    assert [item.code for item in repair.normalizations] == [
        "functional.trailing_non_json_discarded"
    ]


def test_scope_repair_normalizes_optional_empty_capability_args(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    payload = _scope_repair_payload(fixture.failed_plan, "ii")
    goal = payload["scope_replacements"]["ii"]["goals"]["ii.a"]
    goal["steps"][0] = {
        "step_id": "closed_parabola",
        "capability_id": "quadratic_from_constraints",
        "args": {
            "curve_points": ["A"],
            "free_parameters": [],
        },
    }

    repair = FunctionalScopeRepairCompiler().parse_json(
        json.dumps(payload),
        authority=authority,
        capability_catalog=fixture.capability_catalog,
    )
    normalized = repair.scope_replacements["ii"].goals["ii.a"].steps[0]

    assert "free_parameters" not in normalized["args"]
    assert [item.code for item in repair.normalizations] == [
        "functional.empty_optional_capability_arg_omitted"
    ]


def test_repair_and_content_share_capability_parameter_contract(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    catalog = fixture.capability_catalog
    content_schema = functional_plan_content_schema(
        frame, capability_catalog=catalog,
    )
    repair_schema = functional_scope_repair_schema_for_authority(
        authority, capability_catalog=catalog, authority_frame=frame,
        for_prompt=True,
    )
    Draft202012Validator.check_schema(repair_schema)

    def step_validator(schema, name):
        return Draft202012Validator({
            "$defs": schema["$defs"], "$ref": f"#/$defs/{name}",
        })

    content_validator = step_validator(content_schema, "step")
    repair_validator = step_validator(repair_schema, "repair_step")
    result_ref = {"step_id": "produce_parabola", "return": "parabola"}
    cases = [
        ("quadratic_x_axis_intercept_point", {"parabola": "parabola"}, True),
        # The recorded failure: named Function inputs cannot author an exact ref.
        ("quadratic_x_axis_intercept_point", {"parabola": result_ref}, False),
        ("quadratic_x_axis_intercept_point", {"parabola": ["parabola"]}, False),
        ("quadratic_x_axis_intercept_point", {}, False),
        ("quadratic_x_axis_intercept_point", {
            "parabola": "parabola", "invented_arg": "A",
        }, False),
        ("quadratic_from_constraints", {"curve_points": ["A", "D"]}, True),
        ("line_intersection_point", {
            "line1_p1": {"step_id": "produce_point", "return": "point"},
            "line1_p2": "K", "line2_p1": "E", "line2_p2": "G",
        }, True),
        ("parameter_from_expression_value", {
            "expression": {"step_id": "reduce_path", "return": "minimum_expression"},
            "minimum_value": "minimum_value", "parameter": "a",
        }, True),
        ("unknown_capability", {"parabola": "parabola"}, False),
    ]
    for capability_id, args, accepted in cases:
        candidate = {"step_id": "probe", "capability_id": capability_id, "args": args}
        assert content_validator.is_valid(candidate) is accepted, candidate
        assert repair_validator.is_valid(candidate) is accepted, candidate

    # Equal parameter/target contracts do not erase protocol-specific fields.
    with_expectation = {
        "step_id": "probe", "capability_id": "quadratic_from_constraints",
        "args": {"curve_points": ["A", "D"]},
        "return_expectations": {"parabola": "closed_state"},
    }
    assert content_validator.is_valid(with_expectation)
    assert not repair_validator.is_valid(with_expectation)


def test_shared_schema_does_not_normalize_an_invisible_named_producer(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert plan is not None and report.ok
    sibling_producer = next(
        item
        for scope in iter_scopes(fixture.correct_payload["root_scope"])
        if scope["scope_ref"] not in {"problem", "ii"}
        for item in [
            *scope.get("steps", []),
            *(item for goal in scope.get("goals", []) for item in goal.get("steps", [])),
        ]
        if item["capability_id"] == "quadratic_from_constraints"
    )
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    content = functional_plan_content_from_plan(plan, frame=frame).to_payload()
    consumer = next(
        item for item in content["goal_plans"]["ii.a"]["steps"]
        if item["step_id"] == "derive_x_intercept_B_ii"
    )
    consumer["args"]["parabola"] = {
        "step_id": sibling_producer["step_id"], "return": "parabola",
    }
    result = FunctionalPlanContentCompiler().compile_payload(
        content, frame=frame, capability_catalog=fixture.capability_catalog,
    )
    assert not result.report.ok
    assert any(
        issue.code == "functional.plan_content_schema_invalid"
        for issue in result.report.issues
    )


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


def test_cross_goal_step_ref_allows_only_exact_visible_public_answer() -> None:
    producer_step = ScopedFunctionalStep(
        step_id="produce_answer",
        capability_id="producer",
        args={},
        output_targets={},
        return_expectations={},
    )
    consumer_step = ScopedFunctionalStep(
        step_id="consume_answer",
        capability_id="consumer",
        args={},
        output_targets={},
        return_expectations={},
    )
    producer = _StepLocation(producer_step, "ii", "ii.a", 0)
    consumer = _StepLocation(consumer_step, "ii", "ii.b", 1)
    answers = {"ii.a": ("produce_answer", "answer")}
    parents = {"problem": None, "ii": "problem", "iii": "problem"}

    _audit_explicit_dependency(
        producer,
        consumer,
        ref=ScopedStepResultRef("produce_answer", "answer"),
        published_answer_sources=answers,
        scope_parents=parents,
    )

    with pytest.raises(ScopedFunctionalPlanError):
        _audit_explicit_dependency(
            producer,
            consumer,
            ref=ScopedStepResultRef("produce_answer", "internal_witness"),
            published_answer_sources=answers,
            scope_parents=parents,
        )

    sibling_consumer = _StepLocation(consumer_step, "iii", "iii.a", 1)
    with pytest.raises(ScopedFunctionalPlanError) as failure:
        _audit_explicit_dependency(
            producer,
            sibling_consumer,
            ref=ScopedStepResultRef("produce_answer", "answer"),
            published_answer_sources=answers,
            scope_parents=parents,
            path="$.steps['consume_answer'].args['value'][0]",
        )
    assert failure.value.path.endswith(".args['value'][0]")
    assert failure.value.issues[0].details["producer"]["goal_ref"] == "ii.a"
    assert failure.value.issues[0].details["consumer"]["goal_ref"] == "iii.a"
    assert "authorized_scope_refs" not in failure.value.issues[0].details



def test_restore_seed_excludes_open_scope_calls_and_dependency_descendants(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    restored = build_scope_retry_restore_seed(
        authority,
        fixture.execution,
        next_plan=fixture.failed_plan,
    )
    ii_scope = fixture.failed_plan.root_scope.children[1]
    open_call_ids = {
        step.step_id
        for step in (
            *ii_scope.steps,
            *(step for goal in ii_scope.goals for step in goal.steps),
        )
    }

    assert not set(restored.call_ids).intersection(open_call_ids)
    assert set(restored.call_ids) <= {
        item.call_id
        for item in fixture.execution.checkpoint.restore_state.runtime_seed.call_results
    }


def test_scope_repair_auto_rebinds_one_unique_answer_successor(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(
        plan=fixture.failed_plan,
        execution=fixture.execution,
    )
    payload = _scope_repair_payload(fixture.failed_plan, "ii")
    goal_body = payload["scope_replacements"]["ii"]["goals"]["ii.a"]
    old_answer_id = goal_body["answer_from"]["step_id"]
    producer = next(
        step for step in goal_body["steps"] if step["step_id"] == old_answer_id
    )
    producer["step_id"] = "repaired_answer_producer"

    application = FunctionalScopeRepairCompiler().apply_json(
        json.dumps(payload),
        base_plan=fixture.failed_plan,
        authority=authority,
    )
    repaired_goal = application.plan.root_scope.children[1].goals[0]

    assert repaired_goal.answer_from.step_id == "repaired_answer_producer"


def test_scope_repair_prompt_has_one_annotated_plan_and_one_replacement_map(
    tmp_path,
) -> None:
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
    payload = StrategyPayloadBuilder(
        scoped_functional_few_shot_examples=[]
    ).build_scope_repair(
        fixture.inputs,
        annotated_plan=annotated,
        retry_authority=authority,
        problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    prompt = StrategyPromptRenderer().render_scope_repair(payload)
    combined = f"{prompt.system}\n{prompt.user}"

    assert payload["planner_protocol"] == "functional-scope-repair/v1"
    assert set(payload) == {
        "planner_protocol",
        "problem_id",
        "family_id",
        "problem_planning_context",
        "annotated_previous_plan",
        "functional_capability_catalog",
        "output_json_schema",
    }
    assert "## Annotated Previous Plan" in prompt.user
    assert "整块替换" in prompt.system
    assert "Macro 始终是一个原子" in prompt.system
    common = StrategyPromptRenderer().env.get_template(
        "strategy-functional-reference-rules.jinja"
    ).render().strip()
    assert prompt.system.count(common) == 1
    pass1 = StrategyPayloadBuilder(scoped_functional_few_shot_examples=[]).build_scoped(
        fixture.inputs, problem_payload=fixture.problem_payload,
        planner_state_context=fixture.planner_state_context,
        problem_planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
    )
    assert StrategyPromptRenderer().render_scoped(pass1).system.count(common) == 1
    assert "跨Goal不改变引用形式规则" in common
    assert "开放Scope和受影响后继均重新执行" in prompt.system
    definitions = payload["output_json_schema"]["$defs"]
    assert "repair_step_base" in definitions
    # The repair instruction must not exclude an authored field admitted by
    # the schema; doing so caused the live planner to second-guess math inputs.
    assert "parameters" in definitions["repair_step_base"]["properties"]
    authored_fields = next(
        line for line in prompt.system.splitlines() if "纯 authored body" in line
    )
    assert "`parameters`" in authored_fields
    public_ids = {
        item["capability_id"]
        for item in payload["functional_capability_catalog"]["capabilities"]
    }
    def capability_ids(value):
        if isinstance(value, dict):
            capability = value.get("capability_id", {})
            if isinstance(capability, dict) and "const" in capability:
                yield capability["const"]
            for child in value.values():
                yield from capability_ids(child)
        elif isinstance(value, list):
            for child in value:
                yield from capability_ids(child)

    assert set(capability_ids(definitions)) == public_ids
    assert len(json.dumps(payload["output_json_schema"], ensure_ascii=False)) < 12_000
    assert prompt.user.count('"title":"Functional Scope Repair v1"') == 1
    for removed in (
        "goal_retry_context",
        "goal_replacements",
        "scope_step_replacements",
        "answer_binding_replacements",
        "base_plan_id",
        "base_retry_context_id",
        "published_goal_ref",
    ):
        assert removed not in combined


@pytest.mark.parametrize("connection_failure", [False, True])
def test_scope_retry_service_switches_from_pass1_to_vnext_and_accepts_repair(
    tmp_path, connection_failure,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    correct_plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert correct_plan is not None and report.ok
    pass1 = functional_plan_content_from_plan(
        fixture.failed_plan,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(
            fixture.planning_context
        ),
    ).to_payload()
    repair = _scope_repair_payload(correct_plan, "ii")
    repaired_steps = repair["scope_replacements"]["ii"]["goals"][
        "ii.a"
    ]["steps"]
    next(
        item
        for item in repaired_steps
        if item["step_id"] == "derive_x_intercept_B_ii"
    )["args"]["parabola"] = {
        "step_id": "derive_parametric_parabola_ii",
        "return": "parabola",
    }
    next(
        item
        for item in repaired_steps
        if item["step_id"] == "derive_parametric_parabola_ii"
    )["output_targets"] = False

    class Client:
        provider_name = "recorded-test"

        def __init__(self):
            self.responses = [
                json.dumps(pass1, ensure_ascii=False),
                json.dumps(repair, ensure_ascii=False),
            ]
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            if connection_failure and len(self.requests) == 2:
                raise ConnectionError("connection interrupted during repair")
            return self.responses.pop(0)

    client = Client()
    result = ScopedFunctionalScopeRetryService(
        client,
        payload_builder=StrategyPayloadBuilder(
            scoped_functional_few_shot_examples=[]
        ),
        prompt_renderer=StrategyPromptRenderer(),
    ).run(
        inputs=fixture.inputs,
        planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog,
        handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload,
        max_attempts=3 if connection_failure else 2,
    )

    assert result.status == "accepted"
    assert [item.planner_protocol for item in result.attempts] == [
        "functional-plan-content/v2",
        "functional-scope-repair/v1",
    ] + (["functional-scope-repair/v1"] if connection_failure else [])
    if connection_failure:
        assert result.attempts[1].raw_response is None
        assert result.attempts[1].scope_authority == result.attempts[2].scope_authority
        assert result.attempts[1].payload == result.attempts[2].payload
    assert any(
        item.code == "functional.named_entity_result_ref_normalized"
        for item in result.attempts[-1].content_normalizations
    )
    assert any(
        item.code == "functional.false_output_targets_omitted"
        for item in result.attempts[-1].content_normalizations
    )
    repaired_plan = result.attempts[-1].merged_plan
    assert repaired_plan is not None
    repaired_intercept = next(
        item
        for item in repaired_plan.steps
        if item.step_id == "derive_x_intercept_B_ii"
    )
    assert repaired_intercept.args["parabola"] == ("parabola",)
    assert set(result.attempts[1].payload) == {
        "planner_protocol",
        "problem_id",
        "family_id",
        "problem_planning_context",
        "annotated_previous_plan",
        "functional_capability_catalog",
        "output_json_schema",
    }
    assert all(
        "functional-goal-repair/v4" not in json.dumps(request, ensure_ascii=False)
        for request in client.requests
    )


def test_production_retry_tree_contains_no_retired_v4_contract() -> None:
    retired_module = (
        ROOT
        / "server/shuxueshuo_server/solver/runtime/functional_goal_retry.py"
    )
    assert not retired_module.exists()
    production_files = [
        ROOT
        / "server/shuxueshuo_server/solver/runtime/functional_scope_retry.py",
        ROOT / "server/shuxueshuo_server/solver/runtime/strategy_payload.py",
        ROOT
        / "server/shuxueshuo_server/solver/runtime/strategy_runtime_planner.py",
        ROOT
        / "server/shuxueshuo_server/solver/runtime/scoped_functional_plan.py",
        ROOT
        / "server/shuxueshuo_server/solver/runtime/functional_plan_models.py",
        ROOT
        / "internal/llm-prompts/strategy-functional-scope-repair-system.jinja",
        ROOT
        / "internal/llm-prompts/strategy-functional-scope-repair-user.jinja",
        ROOT / "internal/schemas/functional-annotated-plan.schema.json",
        ROOT / "internal/schemas/functional-scope-repair.schema.json",
    ]
    combined = "\n".join(path.read_text() for path in production_files)
    for retired in (
        "functional-goal-repair/v4",
        "planner-goal-retry-context/v4",
        "goal_replacements",
        "scope_step_replacements",
        "answer_binding_replacements",
        "editable_step_ids",
        "frozen_step_ids",
        "base_retry_context_id",
        "published_goal_ref",
        "ScopedPublishedGoalResultRef",
    ):
        assert retired not in combined


@pytest.mark.parametrize('failure_mode', ['recover', 'exhaust', 'nonretryable'])
def test_provider_failure_preserves_attempt_history(tmp_path, failure_mode):
    import httpx
    from openai import APIConnectionError, APITimeoutError, AuthenticationError
    from shuxueshuo_server.solver.runtime.orchestrator import _write_scoped_debug_attempts
    from types import SimpleNamespace

    fixture = goal_retry_fixture(tmp_path)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert plan is not None and report.ok
    valid = functional_plan_content_from_plan(
        plan, frame=FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context)
    ).to_payload()
    invalid = deepcopy(valid)
    first_goal = next(iter(invalid['goal_plans'].values()))
    first_goal.pop('answer_from')
    request = httpx.Request('POST', 'https://example.test/completions')

    class Client:
        # Deliberately stale metadata must never appear on a failed call.
        last_usage = {'total_tokens': 123}
        last_response_model = 'previous-model'
        last_provider_attempts = ({'usage': {'total_tokens': 123}},)

        def __init__(self):
            self.requests = []

        def complete(self, payload):
            self.requests.append(payload)
            index = len(self.requests)
            if index == 1:
                return json.dumps(invalid)
            if failure_mode == 'nonretryable':
                raise AuthenticationError('invalid credentials', response=httpx.Response(401, request=request), body=None)
            if index == 2:
                raise APIConnectionError(request=request)
            if failure_mode == 'exhaust':
                raise APITimeoutError(request=request)
            return json.dumps(valid)

    client = Client()
    result = ScopedFunctionalScopeRetryService(
        client, payload_builder=StrategyPayloadBuilder(scoped_functional_few_shot_examples=[]),
    ).run(
        inputs=fixture.inputs, planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog, handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem),
        planner_state_context=fixture.planner_state_context, problem_payload=fixture.problem_payload,
        max_attempts=3,
    )
    assert len(result.attempts) == (2 if failure_mode == 'nonretryable' else 3)
    assert result.status == ('accepted' if failure_mode == 'recover' else 'blocked')
    assert result.attempts[0].content_validation_report.issues
    failed_call = result.attempts[1]
    assert failed_call.raw_response is None
    assert failed_call.error.retryable is (failure_mode != 'nonretryable')
    assert failed_call.llm_metadata['usage'] is None
    assert failed_call.llm_metadata['response_model'] is None
    assert failed_call.llm_metadata['provider_attempts'] is None
    if failure_mode != 'nonretryable':
        assert result.attempts[1].payload['authoring_feedback'] == result.attempts[2].payload['authoring_feedback']
        assert result.attempts[1].payload['authoring_feedback']
    debug_dir = tmp_path / 'provider-debug'
    _write_scoped_debug_attempts(debug_dir, SimpleNamespace(), result)
    assert (debug_dir / 'attempt-1.raw-response.txt').exists()
    assert (debug_dir / 'attempt-1.validation-report.json').exists()
    assert (debug_dir / 'attempt-2.scope-retry-error.json').exists()
    assert (debug_dir / 'attempt-2.prompt.user.md').exists()
    assert not (debug_dir / 'attempt-2.raw-response.txt').exists()
    if failure_mode == 'exhaust':
        assert (debug_dir / 'attempt-3.scope-retry-error.json').exists()
        assert not (debug_dir / 'attempt-3.raw-response.txt').exists()


def _goal_local_parabola_payload(fixture):
    payload = deepcopy(fixture.correct_payload)
    scopes = {s['scope_ref']: s for s in iter_scopes(payload['root_scope'])}
    producer = next(s for s in scopes['i']['steps'] if s['capability_id'] == 'quadratic_from_constraints')
    scopes['i']['steps'].remove(producer)
    if not scopes['i']['steps']:
        scopes['i'].pop('steps')
    scopes['i_1']['goals'][0]['steps'] = [producer]
    return payload


def _placement_case(fixture):
    payload = _goal_local_parabola_payload(fixture)
    base, report = ScopedFunctionalPlanValidator().validate_payload_with_report(payload)
    assert report.ok and base is not None
    candidate_payload = deepcopy(payload)
    step(candidate_payload, 'derive_x_intercept_B_i')['args']['parabola'] = {
        'step_id': 'derive_parabola_i', 'return': 'parabola',
    }
    candidate, report = ScopedFunctionalPlanValidator().validate_payload_with_report(candidate_payload)
    assert report.ok and candidate is not None
    authority = FunctionalScopeRetryAuthority(base, scoped_functional_plan_id(base), 'test-checkpoint', ('i_1', 'i_2'))
    return authority, candidate


def test_candidate_placement_opens_common_scope_without_adopting_candidate(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    authority, candidate = _placement_case(fixture)
    expanded, issues = FunctionalScopeRetryAuthorityProjector().expand_for_candidate_placement(
        authority=authority, candidate=candidate,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context),
        capability_catalog=fixture.capability_catalog,
    )
    assert expanded.editable_scope_refs == ('i', 'i_1', 'i_2')
    assert expanded.base_plan is authority.base_plan
    assert expanded.base_plan_hash == authority.base_plan_hash
    assert expanded.checkpoint_id == authority.checkpoint_id
    assert expanded.authority_id != authority.authority_id
    assert issues[0]['expected'] == {'producer_scope_ref': 'i', 'producer_owner': 'scope_steps'}
    assert issues[0]['consumer_step_ids'] == ['derive_x_intercept_B_i']


@pytest.mark.parametrize('local_context', ['fact', 'entity'])
def test_placement_does_not_lift_local_conditions_or_entities(tmp_path, local_context):
    fixture = goal_retry_fixture(tmp_path)
    authority, candidate = _placement_case(fixture)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context)
    if local_context == 'fact':
        frame = replace(frame, source_facts={**frame.source_facts, 'i_1': ({'kind': 'symbol_value', 'ref': 'local_coefficient'},)})
    else:
        frame = replace(frame, source_ref_domain_types={**frame.source_ref_domain_types, 'i_1': {'local_point': 'Point'}})
    expanded, issues = FunctionalScopeRetryAuthorityProjector().expand_for_candidate_placement(
        authority=authority, candidate=candidate, frame=frame, capability_catalog=fixture.capability_catalog,
    )
    assert expanded is authority
    assert not issues


def test_placement_does_not_infer_shared_state_from_source_name(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    authority, _ = _placement_case(fixture)
    expanded, issues = FunctionalScopeRetryAuthorityProjector().expand_for_candidate_placement(
        authority=authority, candidate=authority.base_plan,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context),
        capability_catalog=fixture.capability_catalog,
    )
    assert expanded is authority
    assert not issues


def test_candidate_cannot_rewrite_closed_scope_to_obtain_permission(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    authority, _ = _placement_case(fixture)
    candidate, report = ScopedFunctionalPlanValidator().validate_payload_with_report(fixture.correct_payload)
    assert report.ok and candidate is not None
    with pytest.raises(FunctionalScopeRetryError) as caught:
        FunctionalScopeRetryAuthorityProjector().expand_for_candidate_placement(
            authority=authority, candidate=candidate,
            frame=FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context),
            capability_catalog=fixture.capability_catalog,
        )
    assert caught.value.code == 'functional.scope_retry_boundary_violation'
    assert not caught.value.retryable


def test_scope_retry_reopens_parent_after_candidate_failure_and_reexecutes_it(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context)
    initial = _goal_local_parabola_payload(fixture)
    scopes = {s['scope_ref']: s for s in iter_scopes(initial['root_scope'])}
    translated = next(s for s in scopes['problem']['steps'] if s['step_id'] == 'derive_translated_D_i')
    scopes['problem']['steps'].remove(translated)
    scopes['i']['steps'] = [translated]
    step(initial, 'derive_parabola_i')['args']['curve_points'] = ['D']
    initial_plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(initial)
    assert report.ok and initial_plan is not None
    initial_content = functional_plan_content_from_plan(initial_plan, frame=frame).to_payload()

    correct = deepcopy(fixture.correct_payload)
    correct_scopes = {s['scope_ref']: s for s in iter_scopes(correct['root_scope'])}
    correct_scopes['problem']['steps'] = [s for s in correct_scopes['problem']['steps'] if s['step_id'] != 'derive_translated_D_i']
    correct_scopes['i']['steps'].insert(0, deepcopy(translated))
    local_d = deepcopy(translated)
    local_d['step_id'] = 'derive_translated_D_ii'
    correct_scopes['ii']['goals'][0]['steps'].insert(0, local_d)
    correct_plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(correct)
    assert report.ok and correct_plan is not None

    class Client:
        def __init__(self):
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                return json.dumps(initial_content)
            annotated = request['planner_payload']['annotated_previous_plan']
            def walk(scope):
                yield scope
                for child in scope['children']:
                    yield from walk(child)
            open_scopes = [s['scope_ref'] for s in walk(annotated['root_scope']) if s['retry_editable']]
            if len(self.requests) == 2:
                assert 'i' not in open_scopes
                replacements = {}
                def pure(s):
                    return {k: deepcopy(v) for k, v in s.items() if k not in {'execution', 'return_expectations'}}
                for scope in walk(annotated['root_scope']):
                    if scope['scope_ref'] not in open_scopes:
                        continue
                    replacements[scope['scope_ref']] = {
                        'scope_steps': [pure(s) for s in scope['scope_steps']],
                        'goals': {g: {'steps': [pure(s) for s in b['steps']], 'answer_from': b['answer_from']} for g, b in scope['goals'].items()},
                    }
                curve = replacements['i_1']['goals']['i_1.parabola']['steps'][0]
                curve['args']['curve_points'] = ['A', 'D']
                b = next(s for s in replacements['i_2']['goals']['i_2.E']['steps'] if s['step_id'] == 'derive_x_intercept_B_i')
                b['args']['parabola'] = {'step_id': 'derive_parabola_i', 'return': 'parabola'}
                return json.dumps({'schema_version': 'functional-scope-repair/v1', 'scope_replacements': replacements})
            assert 'i' in open_scopes
            assert 'problem' not in open_scopes
            error = annotated['previous_response_error']
            assert error['code'] == 'functional.shared_producer_scope_required'
            assert error['details']['placement_issues'][0]['expected']['producer_scope_ref'] == 'i'
            placement = error['details']['placement_issues'][0]
            assert placement['producer']['goal_ref'] == 'i_1.parabola'
            assert placement['consumers'][0]['scope_ref'] == 'i_2'
            assert 'i' in error['details']['authorized_scope_refs']
            leaf = next(item for item in error['details']['diagnostics'] if item['details'].get('step_id') == 'derive_x_intercept_B_i')
            assert leaf['path'].endswith("['args']['parabola']")
            assert leaf['details']['expected']['reference_form'] == 'SourceRef'
            assert leaf['details']['observed']['reference_form'] == 'StepResultRef'
            assert leaf['details']['producer']['scope_ref'] == 'i_1'
            assert leaf['details']['consumer']['scope_ref'] == 'i_2'

            # Failed candidate did not overwrite A1's execution tree.
            old_curve = next(s for scope in walk(annotated['root_scope']) for body in scope['goals'].values() for s in body['steps'] if s['step_id'] == 'derive_parabola_i')
            assert old_curve['args']['curve_points'] == 'D'
            return json.dumps(_scope_repair_payload(correct_plan, *open_scopes))

    from shuxueshuo_server.solver.runtime.functional_attempt_evidence import write_scoped_attempt_evidence
    incremental = tmp_path / 'incremental-evidence'
    phases = []
    def observe(attempt):
        phases.append((attempt.semantic_attempt, attempt.evidence_phase))
        write_scoped_attempt_evidence(incremental, attempt)
    client = Client()
    result = ScopedFunctionalScopeRetryService(
        client, payload_builder=StrategyPayloadBuilder(scoped_functional_few_shot_examples=[]),
    ).run(
        inputs=fixture.inputs, planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog, handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem), planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload, max_attempts=3, attempt_observer=observe,
    )
    assert len(result.attempts) == 3
    second, third = result.attempts[1:]
    assert second.error.code == 'functional.shared_producer_scope_required'
    assert second.execution is None
    assert third.scope_authority == second.result_scope_authority
    assert third.scope_authority.base_plan_hash == second.scope_authority.base_plan_hash
    assert third.scope_authority.checkpoint_id == second.scope_authority.checkpoint_id
    assert result.status == 'accepted', [(a.error, a.execution) for a in result.attempts]
    assert 'derive_translated_D_i' not in third.restored_call_ids
    assert third.execution.checkpoint is not None
    def execution_scopes(scope):
        yield scope
        for child in scope.children:
            yield from execution_scopes(child)
    d = next(s for scope in execution_scopes(third.execution.checkpoint.root_scope) for s in scope.scope_steps if s.step_id == 'derive_translated_D_i')
    assert d.status == 'runtime_verified'
    from types import SimpleNamespace
    from shuxueshuo_server.solver.runtime.orchestrator import _write_scoped_debug_attempts
    debug = tmp_path / 'placement-debug'
    _write_scoped_debug_attempts(debug, SimpleNamespace(), result)
    old_authority = json.loads((debug / 'attempt-2.scope-retry-authority.json').read_text())
    new_authority = json.loads((debug / 'attempt-2.scope-retry-result-authority.json').read_text())
    assert 'i' not in old_authority['editable_scope_refs']
    assert 'i' in new_authority['editable_scope_refs']
    assert old_authority['base_plan_hash'] == new_authority['base_plan_hash']
    assert old_authority['checkpoint_id'] == new_authority['checkpoint_id']
    full = json.loads((debug / 'attempt-2.validation-diagnostic-evidence.json').read_text())
    prompt_error = json.loads((debug / 'attempt-2.scope-retry-error.json').read_text())
    report = json.loads((debug / 'attempt-2.validation-report.json').read_text())
    evidence = full['details']['diagnostics'][0]
    assert evidence['details']['diagnostic_id'] == prompt_error['details']['diagnostics'][0]['details']['diagnostic_id']
    assert evidence['details']['diagnostic_id'] == report['issues'][0]['details']['diagnostic_id']
    assert 'schema_path' in evidence['details']
    assert 'schema_path' not in prompt_error['details']['diagnostics'][0]['details']



    from shuxueshuo_server.solver.runtime.functional_goal_execution import FunctionalGoalExecutionCheckpoint
    from hashlib import sha256
    assert (2, 'compiled') not in phases
    assert (1, 'completed') in phases and (3, 'completed') in phases
    rejected = json.loads((debug / 'attempt-2.evidence-index.json').read_text())
    assert rejected['artifacts']['candidate-plan']['status'] == 'saved'
    assert rejected['artifacts']['canonical-plan']['status'] == 'not_available'
    assert rejected['artifacts']['transaction']['status'] == 'not_available'
    candidate = json.loads((debug / 'attempt-2.candidate-plan.json').read_text())
    base = json.loads((debug / 'attempt-2.base-plan.json').read_text())
    assert step(candidate, 'derive_parabola_i')['args']['curve_points'] == ['A', 'D']
    assert step(base, 'derive_parabola_i')['args']['curve_points'] == 'D'
    first_checkpoint = json.loads((debug / 'attempt-1.checkpoint.json').read_text())
    restored = FunctionalGoalExecutionCheckpoint.from_payload(first_checkpoint)
    assert restored.checkpoint_id == old_authority['checkpoint_id']
    assert restored.restore_state.runtime_seed is None
    assert restored.authority_payload() == first_checkpoint
    third_reuse = json.loads((debug / 'attempt-3.reuse.json').read_text())
    assert 'derive_translated_D_i' not in third_reuse['actual_restored_call_ids']
    assert 'derive_translated_D_i' in third_reuse['executed_call_ids']
    assert third_reuse['base_checkpoint_id'] == first_checkpoint['checkpoint_id']
    assert 'root_issues' in json.loads((debug / 'attempt-1.transaction.json').read_text())
    for index in (1, 2, 3):
        manifest = json.loads((incremental / f'attempt-{index}.evidence-index.json').read_text())
        assert manifest['phase'] == 'completed'
        for item in manifest['artifacts'].values():
            if item['status'] == 'saved':
                assert sha256((incremental / item['file']).read_bytes()).hexdigest() == item['sha256']


def test_placement_requires_producer_inputs_visible_at_destination(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    authority, candidate = _placement_case(fixture)
    payload = candidate.to_payload()
    # E is owned by sibling i_2; naming it does not make it available at i.
    step(payload, 'derive_parabola_i')['args']['curve_points'] = ['E']
    invalid, report = ScopedFunctionalPlanValidator().validate_payload_with_report(payload)
    assert report.ok and invalid is not None
    expanded, issues = FunctionalScopeRetryAuthorityProjector().expand_for_candidate_placement(
        authority=authority, candidate=invalid,
        frame=FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context),
        capability_catalog=fixture.capability_catalog,
    )
    assert expanded is authority
    assert not issues


def test_audit_survives_execution_crash_with_received_and_compiled_evidence(tmp_path):
    from types import SimpleNamespace
    from shuxueshuo_server.solver.runtime.functional_attempt_evidence import write_scoped_attempt_evidence

    fixture = goal_retry_fixture(tmp_path)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(fixture.correct_payload)
    assert report.ok
    frame = FunctionalPlanAuthorityFrame.from_planning_context(fixture.planning_context)
    payload = functional_plan_content_from_plan(plan, frame=frame).to_payload()
    # An allowed normalization must be distinguishable from authored bytes.
    first = next(iter(payload['scope_steps'].values()))[0]
    first['return_expectations'] = {}
    raw = json.dumps(payload)
    debug = tmp_path / 'crash-evidence'
    phases = []
    def observe(attempt):
        phases.append(attempt.evidence_phase)
        write_scoped_attempt_evidence(debug, attempt)
    def crash(*args, **kwargs):
        index = json.loads((debug / 'attempt-1.evidence-index.json').read_text())
        assert index['phase'] == 'compiled'
        assert index['artifacts']['compiled-plan']['status'] == 'saved'
        raise RuntimeError('unexpected execution failure')
    with pytest.raises(RuntimeError, match='unexpected execution failure'):
        ScopedFunctionalScopeRetryService(SimpleNamespace(complete=lambda request: raw),
            execution_service=SimpleNamespace(execute_raw_json=crash)).run(
            inputs=fixture.inputs, planning_context=fixture.planning_context,
            problem_binding_catalog=fixture.binding_catalog, handle_registry=fixture.handle_registry,
            runtime_context=ContextBuilder().build(fixture.problem), planner_state_context=fixture.planner_state_context,
            problem_payload=fixture.problem_payload, max_attempts=1, attempt_observer=observe)
    assert phases == ['requested', 'received', 'compiled', 'execution_failed']
    assert json.loads((debug / 'attempt-1.raw-response.json').read_text())['text'] == raw
    normalized = json.loads((debug / 'attempt-1.normalized-response.json').read_text())
    assert 'return_expectations' not in next(iter(normalized['scope_steps'].values()))[0]
    assert json.loads((debug / 'attempt-1.normalizations.json').read_text())['content']
    index = json.loads((debug / 'attempt-1.evidence-index.json').read_text())
    assert index['artifacts']['canonical-plan']['status'] == 'not_available'
    assert index['artifacts']['checkpoint']['status'] == 'not_available'
    assert index['phase'] == 'execution_failed'
    assert json.loads((debug / 'attempt-1.blockers.json').read_text())['first_reported']['code'] == 'functional.execution_unexpected_failure'


def test_retryable_binding_failure_reissues_full_plan_without_checkpoint(tmp_path):
    """A latest-state dependency failure must trigger a second planner call."""

    fixture = goal_retry_fixture(tmp_path)
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        fixture.correct_payload
    )
    assert report.ok and plan is not None
    frame = FunctionalPlanAuthorityFrame.from_planning_context(
        fixture.planning_context
    )
    raw_plan = json.dumps(
        functional_plan_content_from_plan(plan, frame=frame).to_payload(),
        ensure_ascii=False,
    )

    class Client:
        provider_name = "recorded-test"

        def __init__(self):
            self.requests = []

        def complete(self, request):
            self.requests.append(request)
            return raw_plan

    class ExecutionService:
        def __init__(self):
            self.calls = 0
            self.delegate = ScopedFunctionalGoalExecutionService()

        def execute_raw_json(self, raw_response, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise FunctionalBindingContextError(
                    "planner.method_input_view_authority_missing",
                    "angle_sum_step.x_axis_point requires latest state B",
                    # The low-level binding service keeps this false; the
                    # planner boundary upgrades candidate dependency errors
                    # into semantic retry feedback.
                    retryable=False,
                    step_id="angle_sum_step",
                    arg_name="x_axis_point",
                    expected={"source": "latest_state", "ref": "B"},
                    observed={"available": ()},
                    repair_action="materialize_required_input_before_consuming",
                )
            return self.delegate.execute_raw_json(raw_response, **kwargs)

    client = Client()
    execution_service = ExecutionService()
    result = ScopedFunctionalScopeRetryService(
        client,
        payload_builder=StrategyPayloadBuilder(
            scoped_functional_few_shot_examples=[]
        ),
        execution_service=execution_service,
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
    assert execution_service.calls == 2
    assert len(client.requests) == 2
    assert [
        request["planner_protocol"] for request in client.requests
    ] == [
        "functional-plan-content/v2",
        "functional-plan-content/v2",
    ]
    assert result.attempts[0].error is not None
    assert result.attempts[0].error.code == (
        "planner.method_input_view_authority_missing"
    )
    assert result.attempts[0].error.retryable is True
    feedback = client.requests[1]["planner_payload"]["authoring_feedback"]
    assert feedback[0]["code"] == "planner.method_input_view_authority_missing"
    assert feedback[0]["details"]["repair_action"] == (
        "materialize_required_input_before_consuming"
    )


def test_transport_failure_keeps_proven_current_provider_evidence(tmp_path):
    from shuxueshuo_server.solver.runtime.functional_attempt_evidence import write_scoped_attempt_evidence
    fixture = goal_retry_fixture(tmp_path)
    class Client:
        last_invocation_id = 0
        def complete(self, payload):
            self.last_invocation_id += 1
            self.last_provider_reasoning = [{'provider_attempt': 1, 'reasoning_content': 'partial reasoning'}]
            self.last_provider_attempts = [{'provider_attempt': 1, 'visible_content': False}]
            self.last_provider_requests = [{'provider_attempt': 1}, {'provider_attempt': 2}]
            self.last_provider_responses = [{'provider_attempt': 1, 'text': ''}]
            self.last_usage = {'total_tokens': 30}
            raise ConnectionError('provider retry disconnected')
    debug = tmp_path / 'provider-failure'
    result = ScopedFunctionalScopeRetryService(Client()).run(
        inputs=fixture.inputs, planning_context=fixture.planning_context,
        problem_binding_catalog=fixture.binding_catalog, handle_registry=fixture.handle_registry,
        runtime_context=ContextBuilder().build(fixture.problem), planner_state_context=fixture.planner_state_context,
        problem_payload=fixture.problem_payload, max_attempts=1,
        attempt_observer=lambda attempt: write_scoped_attempt_evidence(debug, attempt))
    attempt = result.attempts[0]
    assert attempt.raw_response is None
    assert attempt.llm_metadata['usage'] == {'total_tokens': 30}
    assert attempt.llm_metadata['provider_attempts'][0]['provider_attempt'] == 1
    reasoning = json.loads((debug / 'attempt-1.provider-reasoning.json').read_text())
    assert reasoning['status'] == 'provided'
    assert reasoning['attempts'][0]['reasoning_content'] == 'partial reasoning'
    assert 'partial reasoning' not in (debug / 'attempt-1.request.json').read_text()
    assert len(json.loads((debug / 'attempt-1.provider-requests.json').read_text())) == 2


def test_invalid_repair_preserves_normalized_envelope_and_records(tmp_path):
    fixture = goal_retry_fixture(tmp_path)
    authority = FunctionalScopeRetryAuthorityProjector().project(plan=fixture.failed_plan, execution=fixture.execution)
    payload = _scope_repair_payload(fixture.failed_plan, *authority.editable_scope_refs)
    body = next(iter(payload['scope_replacements']['ii']['goals'].values()))
    body['steps'][0]['return_expectations'] = {}
    body['steps'][0].pop('args')
    with pytest.raises(FunctionalScopeRetryError) as raised:
        FunctionalScopeRepairCompiler().parse_json(json.dumps(payload), authority=authority)
    assert raised.value.normalized_response is not None
    normalized = next(iter(raised.value.normalized_response['scope_replacements']['ii']['goals'].values()))
    assert 'return_expectations' not in normalized['steps'][0]
    assert raised.value.content_normalizations
