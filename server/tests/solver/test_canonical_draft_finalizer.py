from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.canonical_draft_finalizer import (
    CanonicalDraftFinalizer,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_models import (
    ProducedFact,
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


def test_finalizer_dependency_refinement_requires_runtime_symbol_reduction() -> None:
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

    not_refined = replace(refined, free_symbol_names=("p",))
    with pytest.raises(
        StrategyDraftValidationError,
        match="state_transition_not_dependency_refinement",
    ):
        finalizer.validate_state_write_provenance((first, not_refined))
