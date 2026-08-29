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
from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FUNCTIONAL_ANNOTATED_PLAN_CONTRACT,
    FunctionalAnnotatedPlanProjector,
    FunctionalScopeRepairCompiler,
    FunctionalScopeRetryAuthorityProjector,
    FunctionalScopeRetryError,
    ScopedFunctionalScopeRetryService,
    build_scope_retry_restore_seed,
    functional_annotated_plan_schema,
    functional_scope_repair_schema,
    functional_scope_repair_schema_for_authority,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    rebase_restored_call_seed,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanError,
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


def test_repair_schema_allows_named_or_anonymous_point_inputs(tmp_path) -> None:
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
    with pytest.raises(ScopedFunctionalPlanError):
        _audit_explicit_dependency(
            producer,
            sibling_consumer,
            ref=ScopedStepResultRef("produce_answer", "answer"),
            published_answer_sources=answers,
            scope_parents=parents,
        )


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
    assert "repair_step_base" not in payload["output_json_schema"]["$defs"]
    assert len(json.dumps(payload["output_json_schema"])) < 10_000
    # R0 captured a 68,481-character v4 prompt for the same repair class.
    assert len(combined) < 68_481
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


def test_scope_retry_service_switches_from_pass1_to_vnext_and_accepts_repair(
    tmp_path,
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
        max_attempts=2,
    )

    assert result.status == "accepted"
    assert [item.planner_protocol for item in result.attempts] == [
        "functional-plan-content/v2",
        "functional-scope-repair/v1",
    ]
    assert any(
        item.code == "functional.named_entity_result_ref_normalized"
        for item in result.attempts[1].content_normalizations
    )
    repaired_plan = result.attempts[1].merged_plan
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
