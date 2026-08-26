from dataclasses import fields, replace
import json

import pytest

from shuxueshuo_server.solver.family import (
    CapabilityContractSpec,
    CapabilityPackRegistry,
    CapabilityPackSpec,
    DEFAULT_CAPABILITY_PACK_REGISTRY,
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
    FamilyRegistry,
    QUADRATIC_PATH_MINIMUM_FAMILY,
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    MethodBindingRuleSpec,
    RecipeExecutionSpec,
    SolverFamilySpec,
    StateSlotPattern,
    StepRecipeSpec,
    expand_family_spec,
)
from shuxueshuo_server.solver.family import (
    quadratic_equal_length_ray_path_minimum as equal_length_ray_family_module,
    quadratic_path_minimum as path_family_module,
    quadratic_square_reflection_path_minimum as square_family_module,
    quadratic_weighted_path_minimum as weighted_family_module,
)
from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    ConditionSourceSpec,
    MethodInputBindingSpec,
    MethodSpec,
    PreviousOutputIdentityDerivationSpec,
    PublicArgSourceSpec,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.binding_rules import MethodBindingRuleRegistry
from shuxueshuo_server.solver.runtime.capability_contracts import (
    contract_is_prompt_executable,
    effective_contract_by_id,
    project_method_contract,
)
from shuxueshuo_server.solver.runtime.strategy_planner import (
    StrategyPayloadBuilder,
    build_strategy_probe_inputs,
)

from _problem_planning_support import cached_scope_native_payload_args


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
ALT_LABEL_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
HEPING_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-yimo-25.json"
HEPING_ERMO_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-ermo-25.json"


def test_quadratic_path_family_supports_canonical_nankai_fixture() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)

    assert QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)
    assert QUADRATIC_PATH_MINIMUM_FAMILY.family_id == "QuadraticPathMinimumSolver"


def test_quadratic_path_family_supports_alt_label_fixture_structurally() -> None:
    problem = load_problem_ir(ALT_LABEL_FIXTURE)

    assert QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)


def test_family_support_is_independent_of_problem_id() -> None:
    problem = load_problem_ir(ALT_LABEL_FIXTURE)

    assert QUADRATIC_PATH_MINIMUM_FAMILY.match.matches(problem)
    assert QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)


def test_quadratic_path_family_rejects_other_real_25_fixture() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)

    assert not QUADRATIC_PATH_MINIMUM_FAMILY.supports(problem)


def test_quadratic_weighted_path_family_supports_hexi_fixture() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)

    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.supports(problem)
    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id == "QuadraticWeightedPathMinimumSolver"


def test_quadratic_weighted_path_family_uses_structural_match_without_problem_gate() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)

    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.match.matches(problem)
    assert QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.supports(problem)


def test_equal_length_ray_family_supports_heping_fixture() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)

    assert QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY.supports(problem)
    assert (
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY.family_id
        == "QuadraticEqualLengthRayPathMinimumSolver"
    )


def test_square_reflection_family_supports_heping_ermo_fixture() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)

    assert QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY.supports(problem)
    assert (
        QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY.family_id
        == "QuadraticSquareReflectionPathMinimumSolver"
    )


def test_family_spec_keeps_planner_and_answer_shape_out_of_spec() -> None:
    field_names = {field.name for field in fields(QUADRATIC_PATH_MINIMUM_FAMILY)}

    assert "answer_schema" not in field_names
    assert "planner_id" not in field_names
    assert "method_capability_hints" not in field_names
    assert "result_collection_policy" not in field_names
    assert not hasattr(QUADRATIC_PATH_MINIMUM_FAMILY, "answer_schema")
    assert not hasattr(QUADRATIC_PATH_MINIMUM_FAMILY, "planner_id")


def test_family_spec_contains_only_family_level_context() -> None:
    spec = QUADRATIC_PATH_MINIMUM_FAMILY

    assert "derive_parabola" in spec.common_goal_types
    assert "derive_parameter" in spec.common_goal_types
    assert spec.strategy_principles
    assert "quadratic_from_constraints" in spec.method_ids
    recipe_ids = {recipe.recipe_id for recipe in spec.step_recipes}
    assert "right_angle_equal_length_construct_and_select" in recipe_ids
    assert "coupled_segment_endpoint_replacement_path_minimum" in recipe_ids
    assert "two_moving_points_path_reduction" not in recipe_ids
    assert any(recipe.priority == "preferred" for recipe in spec.step_recipes)
    assert spec.method_binding_rules


def test_path_family_recipes_include_execution_specs() -> None:
    """Recipe 执行序列应跟随 FamilySpec，而不是只存在 runtime default 表里。"""
    recipes = {
        recipe.recipe_id: recipe
        for recipe in QUADRATIC_PATH_MINIMUM_FAMILY.step_recipes
    }

    right_angle = recipes["right_angle_equal_length_construct_and_select"]
    assert right_angle.execution is not None
    assert right_angle.execution.method_sequence == (
        "right_angle_equal_length_candidates",
        "select_point_by_quadrant_constraint",
    )
    assert right_angle.execution.execution_strategy == "right_angle_construct_select"
    assert right_angle.do_not_use_when
    assert any("单个条件" in item for item in right_angle.do_not_use_when)

    assert "coupled_segment_endpoint_replacement_path_minimum" in recipes
    assert "broken_path_straightening_minimum_expression" not in recipes
    assert "broken_path_minimum_core" not in (
        QUADRATIC_PATH_MINIMUM_FAMILY.base_packs
    )
    assert "broken_path_straightening_candidates" not in (
        QUADRATIC_PATH_MINIMUM_FAMILY.method_ids
    )
    assert not any(
        "先把两动点路径降为单动点路径" in principle
        for principle in QUADRATIC_PATH_MINIMUM_FAMILY.strategy_principles
    )
    assert any(
        "耦合线段端点替换Macro" in principle
        for principle in QUADRATIC_PATH_MINIMUM_FAMILY.strategy_principles
    )


def test_path_family_binding_rules_are_declared_in_spec() -> None:
    """南开相关 method 的 slot 绑定规则应由 FamilySpec 提供。"""
    rules = {
        rule.method_id: rule
        for rule in QUADRATIC_PATH_MINIMUM_FAMILY.method_binding_rules
    }

    assert "quadratic_axis_from_relation" in rules
    assert "two_moving_points_path_reduction" not in rules
    axis_bindings = {
        binding.input_name: binding
        for binding in rules["quadratic_axis_from_relation"].input_bindings
    }
    assert isinstance(axis_bindings["target"], MethodInputBindingSpec)
    assert axis_bindings["target"].derivation == (
        PreviousOutputIdentityDerivationSpec("axis_point")
    )
    relation = axis_bindings["coefficient_relation"]
    assert isinstance(relation, MethodInputBindingSpec)
    assert relation.source == ConditionSourceSpec(
        arg_name="coefficient_relation"
    )
    assert axis_bindings["a"].derivation == CanonicalSymbolDerivationSpec("a")
    assert axis_bindings["b"].derivation == CanonicalSymbolDerivationSpec("b")


def test_family_registry_matches_supported_problem_only() -> None:
    registry = FamilyRegistry((
        QUADRATIC_PATH_MINIMUM_FAMILY,
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
    ))

    supported = load_problem_ir(NANKAI_FIXTURE)
    hexi = load_problem_ir(HEXI_FIXTURE)
    alt_labels = load_problem_ir(ALT_LABEL_FIXTURE)
    unsupported = replace(
        supported,
        problem_id="unsupported-family",
        problem_type="unsupported_problem_type",
    )

    assert registry.match(supported) is QUADRATIC_PATH_MINIMUM_FAMILY
    assert registry.match(hexi) is QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
    assert registry.match(alt_labels) is QUADRATIC_PATH_MINIMUM_FAMILY
    assert registry.match(unsupported) is None


def test_family_registry_rejects_ambiguous_structural_match() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    duplicate = replace(
        QUADRATIC_PATH_MINIMUM_FAMILY,
        family_id="DuplicateQuadraticPathMinimumSolver",
    )
    registry = FamilyRegistry((QUADRATIC_PATH_MINIMUM_FAMILY, duplicate))

    with pytest.raises(ValueError, match="ambiguous solver family match"):
        registry.match(problem)


def test_capability_pack_registry_rejects_unknown_pack() -> None:
    registry = CapabilityPackRegistry(())

    with pytest.raises(ValueError, match="unknown capability pack: missing_pack"):
        registry.require("missing_pack")


def test_capability_pack_expansion_deduplicates_methods_and_overrides_recipes() -> None:
    base_recipe = StepRecipeSpec(
        recipe_id="shared_recipe",
        goal_type="derive_base",
        title="base recipe",
        description="base recipe",
        method_ids=("method_a",),
        execution=RecipeExecutionSpec(
            recipe_id="shared_recipe",
            method_sequence=("method_a",),
            execution_mode="direct",
        ),
        do_not_use_when=("base misuse",),
    )
    local_recipe = StepRecipeSpec(
        recipe_id="shared_recipe",
        goal_type="derive_local",
        title="local recipe",
        description="local recipe",
        method_ids=("method_local",),
        execution=RecipeExecutionSpec(
            recipe_id="shared_recipe",
            method_sequence=("method_local",),
            execution_mode="direct",
        ),
        do_not_use_when=("local misuse",),
    )
    mechanism_recipe = StepRecipeSpec(
        recipe_id="mechanism_recipe",
        goal_type="derive_mechanism",
        title="mechanism recipe",
        description="mechanism recipe",
        method_ids=("method_c",),
        execution=RecipeExecutionSpec(
            recipe_id="mechanism_recipe",
            method_sequence=("method_c",),
            execution_mode="direct",
        ),
    )
    registry = CapabilityPackRegistry((
        CapabilityPackSpec(
            pack_id="base_pack",
            kind="base",
            method_ids=("method_a", "method_b"),
            step_recipes=(base_recipe,),
            strategy_notes=("base note", "shared note"),
        ),
        CapabilityPackSpec(
            pack_id="mechanism_pack",
            kind="mechanism",
            method_ids=("method_b", "method_c"),
            step_recipes=(mechanism_recipe,),
            strategy_notes=("mechanism note", "shared note"),
        ),
    ))
    family = SolverFamilySpec(
        family_id="SyntheticFamily",
        match=QUADRATIC_PATH_MINIMUM_FAMILY.match,
        base_packs=("base_pack",),
        mechanism_packs=("mechanism_pack",),
        strategy_principles=("family note", "shared note"),
        method_ids=("method_c", "method_local"),
        step_recipes=(local_recipe,),
    )

    expanded = expand_family_spec(family, registry)

    assert expanded.method_ids == (
        "method_a",
        "method_b",
        "method_c",
        "method_local",
    )
    assert [recipe.recipe_id for recipe in expanded.step_recipes] == [
        "shared_recipe",
        "mechanism_recipe",
    ]
    assert expanded.step_recipes[0].title == "local recipe"
    assert expanded.step_recipes[0].do_not_use_when == ("local misuse",)
    assert expanded.strategy_principles == (
        "base note",
        "shared note",
        "mechanism note",
        "family note",
    )


def test_capability_pack_expansion_merges_binding_rules_and_family_override() -> None:
    pack_rule = MethodBindingRuleSpec(
        method_id="method_a",
        input_bindings=(
            MethodInputBindingSpec(
                input_name="value",
                source=PublicArgSourceSpec("pack_value"),
            ),
        ),
    )
    family_rule = MethodBindingRuleSpec(
        method_id="method_a",
        input_bindings=(
            MethodInputBindingSpec(
                input_name="value",
                source=PublicArgSourceSpec("family_value"),
            ),
        ),
    )
    registry = CapabilityPackRegistry((
        CapabilityPackSpec(
            pack_id="base_pack",
            kind="base",
            method_ids=("method_a",),
            method_binding_rules=(pack_rule,),
        ),
    ))
    family = SolverFamilySpec(
        family_id="SyntheticFamily",
        match=QUADRATIC_PATH_MINIMUM_FAMILY.match,
        base_packs=("base_pack",),
        method_binding_rules=(family_rule,),
    )

    expanded = expand_family_spec(family, registry)
    rule = next(
        rule
        for rule in expanded.method_binding_rules
        if rule.method_id == "method_a"
    )

    assert rule == family_rule


def test_capability_pack_expansion_rejects_conflicting_pack_binding_rules() -> None:
    registry = CapabilityPackRegistry((
        CapabilityPackSpec(
            pack_id="base_pack",
            kind="base",
            method_binding_rules=(
                MethodBindingRuleSpec(
                    method_id="method_a",
                    input_bindings=(
                        MethodInputBindingSpec(
                            input_name="value",
                            source=PublicArgSourceSpec("base_value"),
                        ),
                    ),
                ),
            ),
        ),
        CapabilityPackSpec(
            pack_id="mechanism_pack",
            kind="mechanism",
            method_binding_rules=(
                MethodBindingRuleSpec(
                    method_id="method_a",
                    input_bindings=(
                        MethodInputBindingSpec(
                            input_name="value",
                            source=PublicArgSourceSpec("mechanism_value"),
                        ),
                    ),
                ),
            ),
        ),
    ))
    family = SolverFamilySpec(
        family_id="SyntheticFamily",
        match=QUADRATIC_PATH_MINIMUM_FAMILY.match,
        base_packs=("base_pack",),
        mechanism_packs=("mechanism_pack",),
    )

    with pytest.raises(
        ValueError,
        match="conflicting capability pack binding rule: method_a",
    ):
        expand_family_spec(family, registry)


def test_capability_pack_expansion_allows_identical_pack_binding_rules() -> None:
    rule = MethodBindingRuleSpec(
        method_id="method_a",
        input_bindings=(
            MethodInputBindingSpec(
                input_name="value",
                source=PublicArgSourceSpec("value"),
            ),
        ),
    )
    registry = CapabilityPackRegistry((
        CapabilityPackSpec(
            pack_id="base_pack",
            kind="base",
            method_binding_rules=(rule,),
        ),
        CapabilityPackSpec(
            pack_id="mechanism_pack",
            kind="mechanism",
            method_binding_rules=(rule,),
        ),
    ))
    family = SolverFamilySpec(
        family_id="SyntheticFamily",
        match=QUADRATIC_PATH_MINIMUM_FAMILY.match,
        base_packs=("base_pack",),
        mechanism_packs=("mechanism_pack",),
    )

    expanded = expand_family_spec(family, registry)

    assert expanded.method_binding_rules == (rule,)


def test_capability_pack_contracts_merge_and_are_json_serializable() -> None:
    pack_contract = CapabilityContractSpec(
        capability_id="method_a",
        capability_kind="function",
        slot_writes=(StateSlotPattern("expression", "Expression"),),
    )
    family_contract = CapabilityContractSpec(
        capability_id="method_a",
        capability_kind="function",
        execution_status="catalog_only",
        slot_writes=(StateSlotPattern("expression", "Expression"),),
    )
    registry = CapabilityPackRegistry((
        CapabilityPackSpec(
            pack_id="base_pack",
            kind="base",
            contracts=(pack_contract,),
        ),
    ))
    family = SolverFamilySpec(
        family_id="SyntheticFamily",
        match=QUADRATIC_PATH_MINIMUM_FAMILY.match,
        base_packs=("base_pack",),
        capability_contracts=(family_contract,),
    )

    expanded = expand_family_spec(family, registry)

    assert expanded.capability_contracts == (family_contract,)
    json.dumps([contract.to_payload() for contract in expanded.capability_contracts])


def test_projected_method_contract_without_outputs_stays_prompt_executable() -> None:
    """A migration projection must not silently hide a registered no-output method."""
    contract = project_method_contract(
        MethodSpec(
            method_id="diagnostic_method",
            title="diagnostic method",
            solves=("diagnose_state",),
            inputs={},
            outputs={},
        )
    )

    assert contract.is_complete
    assert contract.source == "projected"
    assert contract.to_payload()["source"] == "projected"
    assert contract_is_prompt_executable(contract)
    assert "projected_no_outputs_declared" in contract.notes


def test_raw_family_binding_rules_do_not_duplicate_pack_rules() -> None:
    """Family-local binding rules should be real overrides, not pack copies."""
    raw_families = (
        path_family_module._QUADRATIC_PATH_MINIMUM_FAMILY,
        weighted_family_module._QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        equal_length_ray_family_module._QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
        square_family_module._QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    )
    duplicates: list[str] = []
    for family in raw_families:
        pack_rules: dict[str, MethodBindingRuleSpec] = {}
        for pack_id in (*family.base_packs, *family.mechanism_packs):
            pack = DEFAULT_CAPABILITY_PACK_REGISTRY.require(pack_id)
            for rule in pack.method_binding_rules:
                pack_rules[rule.method_id] = rule
        for rule in family.method_binding_rules:
            if pack_rules.get(rule.method_id) == rule:
                duplicates.append(f"{family.family_id}:{rule.method_id}")

    assert duplicates == []


def test_real_families_declare_packs_and_keep_legacy_family_ids() -> None:
    families = (
        QUADRATIC_PATH_MINIMUM_FAMILY,
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
        QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
    )

    for family in families:
        assert family.base_packs
        for pack_id in (*family.base_packs, *family.mechanism_packs):
            DEFAULT_CAPABILITY_PACK_REGISTRY.require(pack_id)

    assert QUADRATIC_PATH_MINIMUM_FAMILY.family_id == "QuadraticPathMinimumSolver"


def test_expanded_family_catalogs_keep_pack_and_local_capabilities() -> None:
    expected = {
        QUADRATIC_PATH_MINIMUM_FAMILY.family_id: (
            QUADRATIC_PATH_MINIMUM_FAMILY,
            {
                "quadratic_from_constraints",
                "quadratic_vertex_point",
                "right_angle_equal_length_candidates",
            },
            {
                "right_angle_equal_length_construct_and_select",
                "coupled_segment_endpoint_replacement_path_minimum",
            },
        ),
        QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id: (
            QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY,
            {
                "quadratic_axis_from_relation",
                "filter_point_candidates_by_quadratic_curve",
                "linked_broken_path_minimum_expression",
            },
            {
                "right_angle_equal_length_construct_and_select",
                "curve_candidate_parameter_solve",
            },
        ),
        QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY.family_id: (
            QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
            {
                "quadratic_vertex_point",
                "angle_sum_equal_angle_candidates",
                "construct_point_on_ray_at_reference_distance",
            },
            {"equal_length_ray_path_reduction"},
        ),
        QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY.family_id: (
            QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
            {
                "square_path_dimension_reduction",
                "line_locus_minimum_point",
            },
            {
                "broken_path_straightening_minimum_expression",
            },
        ),
    }

    for family, method_ids, recipe_ids in expected.values():
        assert method_ids.issubset(set(family.method_ids))
        assert recipe_ids.issubset(
            {recipe.recipe_id for recipe in family.step_recipes}
        )


def test_pack_bound_methods_enter_functional_capability_catalog() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    payload = StrategyPayloadBuilder().build(
        inputs,
        **cached_scope_native_payload_args(problem.problem_id),
    )
    capability_ids = {
        capability["capability_id"]
        for capability in payload["functional_capability_catalog"]["capabilities"]
    }
    rules = MethodBindingRuleRegistry.from_family_spec(QUADRATIC_PATH_MINIMUM_FAMILY)

    assert "quadratic_vertex_point" in QUADRATIC_PATH_MINIMUM_FAMILY.method_ids
    assert rules.rule_for("quadratic_vertex_point") is not None
    assert "quadratic_vertex_point" in capability_ids
    assert "quadratic_from_constraints" in capability_ids


def test_functional_catalog_only_exposes_executable_contracts_for_real_families() -> None:
    for fixture in (
        NANKAI_FIXTURE,
        HEXI_FIXTURE,
        HEPING_FIXTURE,
        HEPING_ERMO_FIXTURE,
    ):
        problem = load_problem_ir(fixture)
        inputs = build_strategy_probe_inputs(problem)
        payload = StrategyPayloadBuilder().build(
            inputs,
            **cached_scope_native_payload_args(problem.problem_id),
        )
        capability_ids = {
            capability["capability_id"]
            for capability in payload["functional_capability_catalog"]["capabilities"]
        }
        contracts = effective_contract_by_id(inputs.family_spec, inputs.method_specs)

        assert capability_ids
        assert all(
            contract_is_prompt_executable(contracts.get(capability_id))
            for capability_id in capability_ids
        )


def test_single_method_recipes_have_runtime_binding_rules_for_real_families() -> None:
    """A visible single-method recipe must compile in every expanded family."""
    for fixture in (
        NANKAI_FIXTURE,
        HEXI_FIXTURE,
        HEPING_FIXTURE,
        HEPING_ERMO_FIXTURE,
    ):
        inputs = build_strategy_probe_inputs(load_problem_ir(fixture))
        binding_rule_ids = {
            rule.method_id for rule in inputs.family_spec.method_binding_rules
        }
        missing = {
            method_id
            for recipe in inputs.family_spec.step_recipes
            if recipe.execution is not None
            and recipe.execution.execution_strategy == "single_method"
            for method_id in recipe.execution.method_sequence
            if method_id not in binding_rule_ids
        }

        assert not missing, (inputs.family_spec.family_id, sorted(missing))


def test_polynomial_templates_are_hidden_from_family_compiler_bindings() -> None:
    """Only MethodInputReadAuthority may inject coefficient identity."""

    for fixture in (
        NANKAI_FIXTURE,
        HEXI_FIXTURE,
        HEPING_FIXTURE,
        HEPING_ERMO_FIXTURE,
    ):
        inputs = build_strategy_probe_inputs(load_problem_ir(fixture))
        for rule in inputs.family_spec.method_binding_rules:
            method = inputs.method_specs.require(rule.method_id)
            closure = method.symbolic_closure
            if (
                closure is None
                or closure.representation_mapper
                != "polynomial_coefficient_template"
            ):
                continue
            bindings = {item.input_name for item in rule.input_bindings}
            assert "quadratic_template" not in bindings, (
                inputs.family_spec.family_id,
                rule.method_id,
            )
            template = method.inputs["quadratic_template"]
            assert template.required is False
            assert template.functional_exposed is False


def test_functional_catalog_hides_catalog_only_contracts() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    catalog_only_override = CapabilityContractSpec(
        capability_id="quadratic_from_constraints",
        capability_kind="function",
        execution_status="catalog_only",
        slot_writes=(StateSlotPattern("expression", "Parabola"),),
    )
    family = replace(
        inputs.family_spec,
        capability_contracts=(
            *inputs.family_spec.capability_contracts,
            catalog_only_override,
        ),
    )
    payload = StrategyPayloadBuilder().build(
        replace(inputs, family_spec=family),
        **cached_scope_native_payload_args(problem.problem_id),
    )
    capability_ids = {
        capability["capability_id"]
        for capability in payload["functional_capability_catalog"]["capabilities"]
    }

    assert "quadratic_from_constraints" not in capability_ids
