from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context_closure import (
    context_closure_resolver_ids,
)
from shuxueshuo_server.solver.runtime.functional_context_closure_handlers import (
    context_closure_handler_ids,
    validate_context_closure_handler_registry,
)
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
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.functional_direct_compiler import (
    FunctionalCapabilityCompileCall,
    FunctionalReturnOutput,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    StrategyDraftValidationError,
    build_strategy_probe_inputs,
)


REPO_ROOT = Path(__file__).resolve().parents[3]

FUNCTIONAL_FIXTURES = (
    REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-xiqing-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.json",
)


def _call(
    *,
    step_id: str,
    scope_id: str,
    capability_id: str,
    goal_type: str,
    target: str,
    inputs: tuple[str, ...],
    returns: tuple[FunctionalReturnOutput, ...],
) -> FunctionalCapabilityCompileCall:
    return FunctionalCapabilityCompileCall(
        step_id=step_id,
        scope_id=scope_id,
        capability_id=capability_id,
        goal_type=goal_type,
        target_handle=target,
        input_handles=inputs,
        created_entities=(),
        return_outputs=returns,
    )


def test_macro_context_closure_resolvers_come_from_contracts() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
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


def test_context_closure_specs_and_handlers_are_complete() -> None:
    validate_context_closure_handler_registry()

    assert context_closure_handler_ids() == context_closure_resolver_ids()


def test_macro_spec_registry_derives_executable_recipes_from_contracts() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
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
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
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

    assert tags >= {
        "verified_path_minimum_subplan",
        "path_minimum_expression",
    }


def test_macro_result_forms_are_projected_from_internal_functions() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
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
    assert returns["straightened_endpoint_1"].scalar_result_form is not None
    assert returns[
        "straightened_endpoint_1"
    ].scalar_result_form.possible_forms == (
        "open_state",
        "closed_state",
    )
    assert returns[
        "straightened_endpoint_1"
    ].scalar_result_form.ignored_symbol_input_args == ("parameter_value",)
    assert returns[
        "straightened_endpoint_2"
    ].scalar_result_form.ignored_symbol_input_args == ("parameter_value",)


def test_shareable_macro_purity_is_derived_from_internal_functions() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = MacroSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    assert registry.require("right_angle_equal_length_construct_and_select").is_pure
    assert registry.require("two_moving_points_path_reduction").is_pure
    assert not registry.require(
        "broken_path_straightening_minimum_expression"
    ).is_pure


def test_macro_catalog_prompt_payload_hides_runtime_wiring_details() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)

    catalog = macro_catalog_payload(inputs.family_spec, inputs.method_specs)

    assert catalog["item_count"] > 0
    macro_ids = {item["macro_id"] for item in catalog["items"]}
    assert "broken_path_straightening_minimum_expression" in macro_ids
    assert "broken_path_straightening_and_select" not in macro_ids
    encoded = json.dumps(catalog, ensure_ascii=False)
    assert "runtime_path" not in encoded
    assert "ContextPath" not in encoded
    assert "intermediate_wiring" not in encoded
    assert "output_aliases" not in encoded
    assert "execution_strategy" not in encoded


def test_migrated_macro_specs_have_no_required_contract_return_mismatch() -> None:
    for fixture in FUNCTIONAL_FIXTURES:
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


def test_every_registered_macro_has_an_audited_lowering_contract() -> None:
    method_specs = MethodSpecRegistry.load_from_code()
    macros = {}

    for family in DEFAULT_FAMILY_REGISTRY.families:
        registry = MacroSpecRegistry.from_family_spec(family, method_specs)
        for macro_id, spec in registry.specs.items():
            macros.setdefault(macro_id, []).append(spec.to_payload())

    assert set(macros) == {
        "broken_path_straightening_minimum_expression",
        "curve_candidate_parameter_solve",
        "equal_length_ray_path_reduction",
        "right_angle_equal_length_construct_and_select",
        "two_moving_points_path_reduction",
    }

    for macro_id in ("broken_path_straightening_minimum_expression",):
        for payload in macros[macro_id]:
            adapter = payload["adapter"]
            assert [
                "parameter_value",
                "distance_between_points.parameter_value",
            ] in adapter["input_aliases"]
            assert {
                "kind": "source_object_identity",
                "source_arg": "parameter_value",
                "target": "distance_between_points.parameter",
            } in adapter["input_derivations"]

    for payload in macros["equal_length_ray_path_reduction"]:
        equal_length_returns = {
            item["semantic_role"]
            for item in payload["adapter"]["output_aliases"]
        }
        assert equal_length_returns == {"minimum_expression"}
        assert payload["internal_calls"] == []
        assert payload["adapter"]["execution_strategy"] == (
            "functional_plan_fragment"
        )
        assert payload["adapter"]["input_aliases"] == []
        assert payload["adapter"]["input_derivations"] == []
        assert payload["adapter"]["strategy_input_targets"] == []
        assert payload["adapter"]["intermediate_wiring"] == []


def test_every_path_transformation_uses_planner_declared_moving_point() -> None:
    """A Function/Macro may validate a strategy role, never invent it."""

    method_specs = MethodSpecRegistry.load_from_code()
    producers = []
    for family in DEFAULT_FAMILY_REGISTRY.families:
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            family,
            method_specs,
        )
        for capability in catalog.items.values():
            for returned in capability.returns:
                if returned.runtime_type != "PathTransformation":
                    continue
                moving = tuple(
                    item
                    for item in returned.object_role_projections
                    if item.role == "moving_object"
                )
                assert len(moving) == 1
                assert moving[0].source_arg == "moving_point"
                assert moving[0].source_object_role is None
                arg = next(
                    item
                    for item in capability.args
                    if item.name == "moving_point"
                )
                assert arg.binding_authority == "wire"
                producers.append(capability.capability_id)

    assert set(producers) >= {
        "square_path_dimension_reduction",
        "two_moving_points_path_reduction",
        "weighted_axis_path_triangle_transform",
    }


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
                    execution_mode="direct",
                )
            }
        )
    )
    step = _call(
        step_id="bad_macro_return",
        scope_id="ii",
        goal_type="derive_minimum_value",
        target="fact:ii:bad_point",
        capability_id="broken_macro",
        inputs=("point:problem:A",),
        returns=(
            FunctionalReturnOutput(
                handle="fact:ii:bad_point",
                valid_scope="ii",
                description="invalid macro return",
                output_type="Point",
            ),
        ),
    )

    with pytest.raises(StrategyDraftValidationError, match="macro.return_unresolved"):
        registry.validate("broken_macro", step)


def test_macro_rejects_point_output_without_declared_identity_role() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)
    handles = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    registry = MacroAdapterRegistry(
        MacroSpecRegistry.from_family_spec(inputs.family_spec, inputs.method_specs),
        handle_registry=handles,
    )
    step = _call(
        step_id="derive_path_state",
        scope_id="ii_1",
        goal_type="derive_path_minimum_expression",
        target="fact:ii:path_minimum_expression",
        capability_id="broken_path_straightening_minimum_expression",
        inputs=("fact:ii:path_minimum_target",),
        returns=(
            FunctionalReturnOutput(
                "fact:ii:path_minimum_expression",
                "ii",
                description="path minimum",
                output_type="MinimumExpression",
            ),
            FunctionalReturnOutput(
                "fact:ii:unrelated_target_coordinate",
                "ii",
                description="unrelated target",
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
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)
    handles = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    registry = MacroAdapterRegistry(
        MacroSpecRegistry.from_family_spec(inputs.family_spec, inputs.method_specs),
        handle_registry=handles,
    )
    step = _call(
        step_id="derive_and_evaluate_path_state",
        scope_id="ii_1",
        goal_type="derive_path_minimum_expression",
        target="fact:ii_1:evaluated_path_minimum_expression",
        capability_id="broken_path_straightening_minimum_expression",
        inputs=(
            "point:ii:E",
            "point:ii:F",
            "fact:ii:path_minimum_target",
        ),
        returns=(
            FunctionalReturnOutput(
                "fact:ii_1:path_minimum_expression",
                "ii_1",
                description=(
                    "broken_path_straightening_minimum_expression "
                    "return path_minimum_expression"
                ),
                output_type="MinimumExpression",
            ),
            FunctionalReturnOutput(
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
