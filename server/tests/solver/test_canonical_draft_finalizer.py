from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.canonical_draft_finalizer import (
    CanonicalDraftFinalizer,
    _close_projected_state_reads,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
    ProjectedStateDependency,
    ProjectedStateWrite,
    StepIntent,
    StepIntentDraft,
    StepIntentScope,
    StrategyDraftValidationError,
    StateWriteProvenance,
)
from shuxueshuo_server.solver.runtime.strategy_normalizer import StepIntentNormalizer
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    StepIntentValidator,
    build_strategy_probe_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PROBLEM = REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
RECORDED = (
    REPO_ROOT
    / "internal/solver-fixtures/tj-2026-nankai-yimo-25.executable-step-intents.json"
)


def test_canonical_draft_finalizer_is_idempotent() -> None:
    problem = load_problem_ir(str(PROBLEM))
    inputs = build_strategy_probe_inputs(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    draft = StepIntentValidator().validate_json(
        RECORDED.read_text(encoding="utf-8"),
        question_goals=inputs.question_goals,
        handle_registry=registry,
        family_spec=inputs.family_spec,
    )
    normalized, _report = StepIntentNormalizer().normalize(
        draft,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    first, _first_report = CanonicalDraftFinalizer().finalize(
        normalized,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )
    second, second_report = CanonicalDraftFinalizer().finalize(
        first,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=registry,
    )

    assert second.to_payload() == first.to_payload()
    assert second_report.changed is False
    assert second_report.issues == ()


def test_canonical_draft_finalizer_rejects_duplicate_single_writer() -> None:
    problem = load_problem_ir(str(PROBLEM))
    inputs = build_strategy_probe_inputs(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    steps = tuple(
        StepIntent(
            step_id=f"producer_{index}",
            scope_id="ii_1",
            recipe_hint="quadratic_from_constraints",
            goal_type="derive_parabola",
            target="fact:ii:shared_curve",
            strategy="derive shared state",
            reads=("function:problem:parabola",),
            produces=(
                ProducedFact(
                    "fact:ii:shared_curve",
                    "ii",
                    output_type="Parabola",
                ),
            ),
        )
        for index in (1, 2)
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="subquestion",
                steps=steps,
            ),
        ),
    )

    with pytest.raises(StrategyDraftValidationError, match="duplicate_produced_handle"):
        CanonicalDraftFinalizer().finalize(
            draft,
            family_spec=inputs.family_spec,
            question_goals=(),
            handle_registry=registry,
        )


def test_finalizer_accepts_ordered_transition_and_rejects_second_create() -> None:
    first = StateWriteProvenance(
        step_id="create_state",
        scope_id="question",
        capability_id="create_point",
        produced_handle="fact:question:moving_coordinate",
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        object_ref="point:question:moving",
        state_slot_id="point:question:moving.coordinate@question:Point",
        write_mode="create",
    )
    transition = StateWriteProvenance(
        step_id="advance_state",
        scope_id="question",
        capability_id="advance_point",
        produced_handle="fact:question:optimal_coordinate",
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        object_ref="point:question:moving",
        state_slot_id=first.state_slot_id,
        write_mode="transition",
        previous_write_step_id=first.step_id,
    )

    finalizer = CanonicalDraftFinalizer()
    finalizer.validate_state_write_provenance((first, transition))

    second_create = replace(
        transition,
        write_mode="create",
        previous_write_step_id=None,
    )
    with pytest.raises(
        StrategyDraftValidationError,
        match="duplicate_state_slot_writer",
    ):
        finalizer.validate_state_write_provenance((first, second_create))


def test_finalizer_accepts_typed_transition_from_ancestor_storage_scope() -> None:
    object_id = MathObjectId(
        "function:problem:parabola",
        "function",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    parent_version = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    child_version = StateVersionId(
        StateSlotId(logical_key, "i"),
        1,
    )
    parent = StateWriteProvenance(
        step_id="build_parent_curve",
        scope_id="problem",
        capability_id="quadratic_from_constraints",
        produced_handle="fact:problem:parabola_expression",
        output_key="parabola",
        runtime_type="Parabola",
        identity_policy="preserve_input_object",
        identity_role="parabola",
        object_ref=object_id.value,
        state_slot_id="function:problem:parabola.expression@problem:Parabola",
        write_mode="create",
        selected_version_id=parent_version,
    )
    child = replace(
        parent,
        step_id="refine_child_curve",
        scope_id="i",
        produced_handle="fact:i:parabola_expression",
        state_slot_id="function:problem:parabola.expression@i:Parabola",
        write_mode="transition",
        previous_write_step_id=parent.step_id,
        selected_version_id=child_version,
        previous_version_id=parent_version,
    )

    CanonicalDraftFinalizer().validate_state_write_provenance((parent, child))


def test_finalizer_rejects_authoritative_transition_without_previous_version() -> None:
    transition = StateWriteProvenance(
        step_id="refine_curve",
        scope_id="i",
        capability_id="quadratic_from_constraints",
        produced_handle="fact:i:parabola_expression",
        output_key="parabola",
        runtime_type="Parabola",
        identity_policy="preserve_input_object",
        identity_role="parabola",
        object_ref="function:problem:parabola",
        state_slot_id="function:problem:parabola.expression@i:Parabola",
        write_mode="transition",
        previous_write_step_id="build_curve",
        allocation_action="transition",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_projection_drift",
    ):
        CanonicalDraftFinalizer().validate_state_write_provenance((transition,))


def test_finalizer_dependency_refinement_requires_nonexpanding_symbols() -> None:
    first = StateWriteProvenance(
        step_id="derive_open_state",
        scope_id="question",
        capability_id="derive_state",
        produced_handle="fact:question:open_coordinate",
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        object_ref="point:question:target",
        state_slot_id="point:question:target.coordinate@question:Point",
        write_mode="create",
        free_symbol_names=("p",),
    )
    refined = replace(
        first,
        step_id="derive_closed_state",
        produced_handle="fact:question:closed_coordinate",
        write_mode="transition",
        previous_write_step_id=first.step_id,
        transition_kind="dependency_refinement",
        free_symbol_names=(),
    )

    finalizer = CanonicalDraftFinalizer()
    finalizer.validate_state_write_provenance((first, refined))

    unchanged_degree = replace(refined, free_symbol_names=("p",))
    finalizer.validate_state_write_provenance((first, unchanged_degree))

    not_refined = replace(refined, free_symbol_names=("p", "q"))
    with pytest.raises(
        StrategyDraftValidationError,
        match="state_transition_not_dependency_refinement",
    ):
        finalizer.validate_state_write_provenance((first, not_refined))


def test_projected_point_state_dependency_closes_downstream_reads() -> None:
    problem = load_problem_ir(str(PROBLEM))
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    point_state = ProducedFact(
        "fact:ii_2:closed_moving_point",
        "ii_2",
        output_type="Point",
    )
    transformation = ProducedFact(
        "fact:ii_2:reduced_path",
        "ii_2",
        output_type="PathTransformation",
    )
    minimum = ProducedFact(
        "fact:ii_2:minimum_expression",
        "ii_2",
        output_type="MinimumExpression",
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_2",
                label="subquestion",
                steps=(
                    StepIntent(
                        step_id="close_point",
                        scope_id="ii_2",
                        recipe_hint="evaluate_point_at_parameter",
                        goal_type="derive_point",
                        target="point:ii:M",
                        strategy="close the point state",
                        reads=("point:ii:M",),
                        produces=(point_state,),
                    ),
                    StepIntent(
                        step_id="reduce_path",
                        scope_id="ii_2",
                        recipe_hint="two_moving_points_path_reduction",
                        goal_type="reduce_path",
                        target=transformation.handle,
                        strategy="derive the path transformation",
                        reads=(point_state.handle,),
                        produces=(transformation,),
                    ),
                    StepIntent(
                        step_id="consume_path",
                        scope_id="ii_2",
                        recipe_hint=(
                            "broken_path_straightening_minimum_expression"
                        ),
                        goal_type="derive_minimum",
                        target=minimum.handle,
                        strategy="consume the transformed path",
                        reads=(transformation.handle,),
                        produces=(minimum,),
                    ),
                ),
            ),
        ),
    )
    point_slot = "point:ii:M.coordinate@ii_2"
    writes = (
        ProjectedStateWrite(
            step_id="close_point",
            produced_handle=point_state.handle,
            state_slot_id=point_slot,
            write_mode="transition",
            runtime_type="Point",
            object_ref="point:ii:M",
        ),
        ProjectedStateWrite(
            step_id="reduce_path",
            produced_handle=transformation.handle,
            state_slot_id="functional:ii_2:reduced_path",
            write_mode="value",
            runtime_type="PathTransformation",
            source_state_slot_ids=(point_slot,),
        ),
    )
    dependencies = (
        ProjectedStateDependency(
            step_id="consume_path",
            state_slot_id="functional:ii_2:reduced_path",
            produced_handle=transformation.handle,
            runtime_type="PathTransformation",
            object_ref=None,
            source="wire",
        ),
    )

    closed = _close_projected_state_reads(
        draft,
        projected_state_writes=writes,
        projected_state_dependencies=dependencies,
        handle_registry=registry,
    )
    consumer = next(
        step for step in closed.steps if step.step_id == "consume_path"
    )

    assert point_state.handle in consumer.reads
    assert _close_projected_state_reads(
        closed,
        projected_state_writes=writes,
        projected_state_dependencies=dependencies,
        handle_registry=registry,
    ).to_payload() == closed.to_payload()


@pytest.mark.parametrize(
    ("runtime_type", "object_ref", "state_kind"),
    (
        ("Point", "point:ii:M", "coordinate"),
        ("Parabola", "function:problem:parabola", "expression"),
        ("ParameterValue", "symbol:problem:m", "value"),
    ),
)
def test_projected_dependency_closure_is_runtime_type_agnostic(
    runtime_type: str,
    object_ref: str,
    state_kind: str,
) -> None:
    problem = load_problem_ir(str(PROBLEM))
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    handle = f"fact:ii_1:typed_{state_kind}"
    produced = ProducedFact(
        handle,
        "ii_1",
        output_type=runtime_type,
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                "ii_1",
                "第（Ⅱ）①问",
                (
                    StepIntent(
                        step_id="produce_typed_state",
                        scope_id="ii_1",
                        recipe_hint="synthetic_producer",
                        goal_type="derive_state",
                        target=handle,
                        strategy="produce a typed state",
                        produces=(produced,),
                    ),
                    StepIntent(
                        step_id="consume_typed_state",
                        scope_id="ii_1",
                        recipe_hint="synthetic_consumer",
                        goal_type="consume_state",
                        target="fact:ii_1:consumer",
                        strategy="consume the exact state",
                    ),
                ),
            ),
        )
    )
    slot_id = f"{object_ref}.{state_kind}@ii_1:{runtime_type}"
    dependencies = (
        ProjectedStateDependency(
            step_id="consume_typed_state",
            state_slot_id=slot_id,
            produced_handle=handle,
            runtime_type=runtime_type,
            object_ref=object_ref,
            source="resolver",
        ),
    )
    writes = (
        ProjectedStateWrite(
            step_id="produce_typed_state",
            produced_handle=handle,
            state_slot_id=slot_id,
            write_mode="value",
            runtime_type=runtime_type,
            object_ref=object_ref,
        ),
    )

    closed = _close_projected_state_reads(
        draft,
        projected_state_writes=writes,
        projected_state_dependencies=dependencies,
        handle_registry=registry,
    )

    consumer = next(
        item
        for item in closed.steps
        if item.step_id == "consume_typed_state"
    )
    assert consumer.reads == (handle,)


def test_functional_state_scope_remains_authoritative_for_cross_scope_reads() -> None:
    problem = load_problem_ir(str(PROBLEM))
    inputs = build_strategy_probe_inputs(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    local_input = ProducedFact(
        "fact:i:local_parameter",
        "i",
        output_type="ParameterValue",
    )
    shared_state = ProducedFact(
        "fact:problem:shared_coordinate",
        "problem",
        output_type="Point",
    )
    consumer_output = ProducedFact(
        "fact:ii_1:consumer_value",
        "ii_1",
        output_type="Expression",
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                "i",
                "first question",
                (
                    StepIntent(
                        step_id="derive_local_parameter",
                        scope_id="i",
                        recipe_hint="synthetic_parameter",
                        goal_type="derive_parameter",
                        target=local_input.handle,
                        strategy="derive a local input",
                        produces=(local_input,),
                    ),
                    StepIntent(
                        step_id="publish_shared_point",
                        scope_id="i",
                        recipe_hint="synthetic_point",
                        goal_type="derive_point",
                        target=shared_state.handle,
                        strategy="publish the object state",
                        reads=(local_input.handle,),
                        produces=(shared_state,),
                    ),
                ),
            ),
            StepIntentScope(
                "ii_1",
                "sibling question",
                (
                    StepIntent(
                        step_id="consume_shared_point",
                        scope_id="ii_1",
                        recipe_hint="synthetic_consumer",
                        goal_type="consume_point",
                        target=consumer_output.handle,
                        strategy="reuse the published object state",
                        produces=(consumer_output,),
                    ),
                ),
            ),
        )
    )
    slot_id = "point:problem:shared.coordinate@problem"
    writes = (
        ProjectedStateWrite(
            step_id="publish_shared_point",
            produced_handle=shared_state.handle,
            state_slot_id=slot_id,
            write_mode="create",
            runtime_type="Point",
            object_ref="point:problem:shared",
        ),
    )
    dependencies = (
        ProjectedStateDependency(
            step_id="consume_shared_point",
            state_slot_id=slot_id,
            produced_handle="fact:ii_1:stale_shared_coordinate",
            runtime_type="Point",
            object_ref="point:problem:shared",
            source="wire",
            source_step_id="publish_shared_point",
            source_return_name=None,
        ),
    )

    finalized, _report = CanonicalDraftFinalizer().finalize(
        draft,
        family_spec=inputs.family_spec,
        question_goals=(),
        handle_registry=registry,
        projected_state_writes=writes,
        projected_state_dependencies=dependencies,
    )

    producer = next(
        item for item in finalized.steps
        if item.step_id == "publish_shared_point"
    )
    consumer = next(
        item for item in finalized.steps
        if item.step_id == "consume_shared_point"
    )
    assert producer.produces[0] == shared_state
    assert shared_state.handle in consumer.reads
    assert "fact:ii_1:stale_shared_coordinate" not in consumer.reads
