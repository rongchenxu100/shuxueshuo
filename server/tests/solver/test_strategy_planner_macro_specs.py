from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.macro_specs import (
    MacroAdapterSpec,
    MacroAdapterRegistry,
    MacroReturnSpec,
    MacroSpec,
    MacroSpecRegistry,
    assert_no_macro_adapter_failures,
    macro_catalog_payload,
)
from shuxueshuo_server.solver.family.models import (
    CONDITION_OBJECT_ROLES_RESOLVER,
    PATH_REDUCTION_ROLES_RESOLVER,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    ProducedFact,
    RecipeTrialExecutor,
    StepIntent,
    StepIntentValidator,
    StrategyDraftValidationError,
    build_strategy_probe_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[3]

RECORDED_FIXTURES = (
    (
        REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json",
        REPO_ROOT
        / "internal/solver-fixtures/tj-2026-nankai-yimo-25.executable-step-intents.json",
    ),
    (
        REPO_ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.json",
        REPO_ROOT
        / "internal/solver-fixtures/tj-2026-hexi-yimo-25.executable-step-intents.json",
    ),
    (
        REPO_ROOT / "internal/solver-fixtures/tj-2026-xiqing-yimo-25.json",
        REPO_ROOT
        / "internal/solver-fixtures/tj-2026-xiqing-yimo-25.executable-step-intents.json",
    ),
    (
        REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-yimo-25.json",
        REPO_ROOT
        / "internal/solver-fixtures/tj-2026-heping-yimo-25.executable-step-intents.json",
    ),
    (
        REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.json",
        REPO_ROOT
        / "internal/solver-fixtures/tj-2026-heping-ermo-25.executable-step-intents.json",
    ),
)


def test_macro_context_closure_resolvers_come_from_contracts() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    assert registry.require(
        "right_angle_equal_length_construct_and_select"
    ).context_resolvers == (CONDITION_OBJECT_ROLES_RESOLVER,)
    assert registry.require(
        "two_moving_points_path_reduction"
    ).context_resolvers == (PATH_REDUCTION_ROLES_RESOLVER,)


def test_macro_spec_registry_derives_executable_recipes_from_contracts() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)

    registry = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    executable_recipe_ids = {
        recipe.recipe_id
        for recipe in inputs.family_spec.step_recipes
        if recipe.execution is not None or len(recipe.method_ids) == 1
    }
    assert executable_recipe_ids
    assert executable_recipe_ids <= set(registry.specs)
    for recipe_id in executable_recipe_ids:
        spec = registry.require(recipe_id)
        assert spec.macro_id == recipe_id
        assert spec.recipe_id == recipe_id
        assert spec.returns
        assert spec.internal_calls
        json.dumps(spec.to_payload(), ensure_ascii=False, sort_keys=True)


def test_path_minimum_goal_evidence_is_projected_from_recipe_outputs() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    tags = {
        tag
        for spec in registry.specs.values()
        for item in spec.returns
        for tag in item.goal_evidence_tags
    }

    assert tags >= {"path_minimum_witness", "path_minimum_expression"}


def test_macro_scalar_result_forms_are_projected_from_internal_functions() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    macro = registry.require("broken_path_straightening_minimum_expression")
    returns = {item.name: item for item in macro.returns}
    assert returns["path_minimum_expression"].scalar_result_form is not None
    assert returns[
        "path_minimum_expression"
    ].scalar_result_form.possible_forms == (
        "open_expression",
        "closed_value",
    )
    assert returns["path_minimum_point_1"].scalar_result_form is None


def test_shareable_macro_purity_is_derived_from_internal_functions() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    assert registry.require("right_angle_equal_length_construct_and_select").is_pure
    assert registry.require("two_moving_points_path_reduction").is_pure


def test_macro_catalog_prompt_payload_hides_runtime_wiring_details() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)

    catalog = macro_catalog_payload(inputs.family_spec, inputs.method_specs)

    assert catalog["item_count"] > 0
    encoded = json.dumps(catalog, ensure_ascii=False)
    assert "runtime_path" not in encoded
    assert "ContextPath" not in encoded
    assert "intermediate_wiring" not in encoded
    assert "output_aliases" not in encoded
    assert "execution_strategy" not in encoded


def test_migrated_macro_specs_have_no_required_contract_return_mismatch() -> None:
    for fixture, _steps_path in RECORDED_FIXTURES:
        problem = load_problem_ir(str(fixture))
        inputs = build_strategy_probe_inputs(problem)
        registry = MacroSpecRegistry.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )

        for spec in registry.specs.values():
            required_mismatches = [
                note for note in spec.notes
                if note.startswith("macro_contract_mismatch:required:")
            ]
            assert required_mismatches == []


def test_macro_adapter_reports_typed_return_failure() -> None:
    registry = MacroAdapterRegistry(
        MacroSpecRegistry(
            {
                "broken_macro": MacroSpec(
                    macro_id="broken_macro",
                    recipe_id="broken_macro",
                    goal_types=("derive_minimum_value",),
                    args=(),
                    returns=(
                        MacroReturnSpec(
                            name="minimum_expression",
                            kind="slot_write",
                            runtime_type="MinimumExpression",
                        ),
                    ),
                    internal_calls=(),
                    adapter=MacroAdapterSpec(
                        adapter_id="broken_macro",
                        execution_strategy="single_method",
                    ),
                )
            }
        )
    )
    step = StepIntent(
        step_id="bad_macro_return",
        scope_id="ii",
        goal_type="derive_minimum_value",
        target="fact:ii:bad_point",
        recipe_hint="broken_macro",
        strategy="intentionally invalid macro return",
        reads=("point:problem:A",),
        produces=(
            ProducedFact(
                handle="fact:ii:bad_point",
                valid_scope="ii",
                output_type="Point",
            ),
        ),
    )

    with pytest.raises(StrategyDraftValidationError, match="macro.return_unresolved"):
        registry.validate("broken_macro", step)


def test_macro_rejects_point_output_without_declared_identity_role() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    handles = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    registry = MacroAdapterRegistry(
        MacroSpecRegistry.from_family_spec(inputs.family_spec, inputs.method_specs),
        handle_registry=handles,
    )
    step = StepIntent(
        step_id="derive_path_state",
        scope_id="ii_1",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        recipe_hint="broken_path_straightening_minimum_expression",
        strategy="derive a path minimum and an unrelated point",
        reads=("fact:ii:path_minimum_target",),
        produces=(
            ProducedFact(
                "fact:ii:path_minimum_expression",
                "ii",
                output_type="MinimumExpression",
            ),
            ProducedFact(
                "fact:ii:unrelated_target_coordinate",
                "ii",
                output_type="Point",
            ),
        ),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="macro.return_(unresolved|ambiguous)",
    ):
        registry.validate(
            "broken_path_straightening_minimum_expression",
            step,
        )


def test_macro_exact_return_metadata_disambiguates_prefixed_roles() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    handles = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    registry = MacroAdapterRegistry(
        MacroSpecRegistry.from_family_spec(inputs.family_spec, inputs.method_specs),
        handle_registry=handles,
    )
    step = StepIntent(
        step_id="derive_and_evaluate_path_state",
        scope_id="ii_1",
        goal_type="derive_path_minimum_expression",
        target="fact:ii_1:evaluated_path_minimum_expression",
        recipe_hint="broken_path_straightening_minimum_expression",
        strategy="derive both declared minimum-expression views",
        reads=(
            "point:ii:E",
            "point:ii:F",
            "fact:ii:path_minimum_target",
        ),
        produces=(
            ProducedFact(
                "fact:ii_1:path_minimum_expression",
                "ii_1",
                description=(
                    "broken_path_straightening_minimum_expression "
                    "return path_minimum_expression"
                ),
                output_type="MinimumExpression",
            ),
            ProducedFact(
                "fact:ii_1:evaluated_path_minimum_expression",
                "ii_1",
                description=(
                    "broken_path_straightening_minimum_expression "
                    "return evaluated_path_minimum_expression"
                ),
                output_type="MinimumExpression",
            ),
        ),
    )

    registry.validate(
        "broken_path_straightening_minimum_expression",
        step,
    )


def test_recorded_fixtures_compile_recipe_steps_without_macro_failures() -> None:
    for fixture, steps_path in RECORDED_FIXTURES:
        problem = load_problem_ir(str(fixture))
        inputs = build_strategy_probe_inputs(problem)
        problem_payload = problem_to_llm_payload(problem)
        handle_registry = CanonicalHandleRegistry.from_problem_payload(
            problem_payload
        )
        raw = steps_path.read_text(encoding="utf-8")
        draft = StepIntentValidator().validate_json(
            raw,
            question_goals=inputs.question_goals,
            handle_registry=handle_registry,
            family_spec=inputs.family_spec,
        )

        _output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
            draft,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handle_registry,
            context=ContextBuilder().build(problem),
            question_goals=inputs.question_goals,
        )

        assert diagnostic.ok, diagnostic.to_payload()
        recipe_steps = {
            step.step_id
            for step in draft.steps
            if step.recipe_hint
            and any(
                recipe.recipe_id == step.recipe_hint
                for recipe in inputs.family_spec.step_recipes
            )
        }
        if recipe_steps:
            assert diagnostic.macro_binding_events
        assert_no_macro_adapter_failures(diagnostic.macro_binding_events)
