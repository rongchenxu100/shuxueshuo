from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from shuxueshuo_server.solver.contracts import (
    CanonicalSymbolDerivationSpec,
    CoefficientExtractionDerivationSpec,
    ConditionSourceSpec,
    EntityIdentitySourceSpec,
    ExactCallResultSourceSpec,
    ExactParameterSubstitutionSourceSpec,
    FreeSymbolBasisDerivationSpec,
    LatestStateSourceSpec,
    MacroPreparedRoleSourceSpec,
    MethodInputBindingContractError,
    MethodInputBindingSpec,
    MethodInputSpec,
    MethodInputViewMode,
    MethodInputViewSpec,
    OrdinalZeroTemplateDerivationSpec,
    PreviousOutputIdentityDerivationSpec,
    ProducerLinkedSourceSpec,
    PublicArgSourceSpec,
    SourceObjectIdentityDerivationSpec,
    validate_method_input_binding_view,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.family.models import RecipeInputDerivationSpec
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionAdapterRegistry,
    FunctionAdapterSpec,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "internal/schemas/method-input-binding.schema.json"
FAMILY_BINDING_FILES = (
    "shuxueshuo_server/solver/family/capability_packs.py",
    "shuxueshuo_server/solver/family/common_binding_rules.py",
    "shuxueshuo_server/solver/family/quadratic_equal_length_ray_path_minimum.py",
    "shuxueshuo_server/solver/family/quadratic_path_minimum.py",
    "shuxueshuo_server/solver/family/quadratic_square_reflection_path_minimum.py",
    "shuxueshuo_server/solver/family/quadratic_weighted_path_minimum.py",
)


SOURCE_VARIANTS = (
    PublicArgSourceSpec("point"),
    EntityIdentitySourceSpec(arg_name="point"),
    EntityIdentitySourceSpec(semantic_roles=("moving_point", "endpoint")),
    LatestStateSourceSpec("quadratic"),
    ConditionSourceSpec(arg_name="point_on_curve"),
    ConditionSourceSpec(
        condition_kinds=("point_on_curve",),
        related_args=("point", "quadratic"),
    ),
    ExactCallResultSourceSpec("candidate_set"),
    ExactCallResultSourceSpec(
        "minimum_point",
        ("straightened_endpoint_1",),
    ),
    ExactParameterSubstitutionSourceSpec(
        ("quadratic", "point"),
        "parameter",
    ),
    ProducerLinkedSourceSpec("parameter_value", "parameter"),
    MacroPreparedRoleSourceSpec("moving_point"),
)

DERIVATION_VARIANTS = (
    CanonicalSymbolDerivationSpec("x"),
    CoefficientExtractionDerivationSpec("quadratic"),
    OrdinalZeroTemplateDerivationSpec("quadratic"),
    PreviousOutputIdentityDerivationSpec("point"),
    SourceObjectIdentityDerivationSpec("parameter_value"),
    FreeSymbolBasisDerivationSpec(("expression", "constraint")),
)

MIGRATED_QUADRATIC_BINDINGS = {
    ("evaluate_expression_at_parameter", "parameter", "free_symbol_basis"),
    ("line_parabola_second_intersection_point", "parabola", "public_arg"),
    ("line_parabola_second_intersection_point", "x", "canonical_symbol"),
    (
        "linked_broken_path_minimum_expression",
        "parameter",
        "free_symbol_basis",
    ),
    (
        "parameter_from_curve_point_on_quadratic",
        "known_parameter",
        "source_object_identity",
    ),
    (
        "parameter_from_curve_point_on_quadratic",
        "parameter",
        "free_symbol_basis",
    ),
    (
        "parameter_from_curve_point_on_quadratic",
        "quadratic",
        "public_arg",
    ),
    (
        "parameter_from_curve_point_on_quadratic",
        "x",
        "canonical_symbol",
    ),
    ("parameter_from_expression_value", "parameter", "free_symbol_basis"),
    ("parameter_from_minimum_value", "parameter", "free_symbol_basis"),
    ("parameter_from_segment_length", "parameter", "free_symbol_basis"),
    ("point_candidates_from_curve_point_condition", "parabola", "public_arg"),
    (
        "point_candidates_from_curve_point_condition",
        "x",
        "canonical_symbol",
    ),
    ("point_on_parabola_at_x", "parabola", "public_arg"),
    ("point_on_parabola_at_x", "x", "canonical_symbol"),
    ("quadratic_axis_parameterized_point", "parabola", "public_arg"),
    ("quadratic_axis_parameterized_point", "x", "canonical_symbol"),
    ("quadratic_axis_x_intercept_point", "parabola", "public_arg"),
    ("quadratic_axis_x_intercept_point", "x", "canonical_symbol"),
    (
        "quadratic_from_constraints",
        "all_coefficients",
        "coefficient_extraction",
    ),
    ("quadratic_from_constraints", "quadratic", "latest_state"),
    ("quadratic_from_constraints", "x", "canonical_symbol"),
    ("quadratic_vertex_point", "parabola", "public_arg"),
    ("quadratic_vertex_point", "x", "canonical_symbol"),
    ("quadratic_x_axis_intercept_point", "quadratic", "public_arg"),
    ("quadratic_x_axis_intercept_point", "x", "canonical_symbol"),
    ("quadratic_y_axis_intercept_point", "quadratic", "latest_state"),
    ("quadratic_y_axis_intercept_point", "x", "canonical_symbol"),
}

C1_MIGRATED_BINDINGS = {
    ("distance_between_points", "p1", "public_arg"),
    ("distance_between_points", "p2", "public_arg"),
    ("evaluate_expression_at_parameter", "expression", "exact_call_result"),
    ("evaluate_point_at_parameter", "point", "public_arg"),
    ("line_intersection_point", "line1_p1", "public_arg"),
    ("line_intersection_point", "line1_p2", "public_arg"),
    ("line_intersection_point", "line2_p1", "public_arg"),
    ("line_intersection_point", "line2_p2", "public_arg"),
    ("line_locus_minimum_point", "moving_locus", "exact_call_result"),
    ("line_parabola_second_intersection_point", "known_point", "public_arg"),
    ("line_parabola_second_intersection_point", "line_p1", "public_arg"),
    ("line_parabola_second_intersection_point", "line_p2", "public_arg"),
    (
        "linked_broken_path_minimum_expression",
        "auxiliary_locus",
        "exact_call_result",
    ),
    (
        "linked_broken_path_minimum_expression",
        "auxiliary_point",
        "public_arg",
    ),
    ("linked_broken_path_minimum_expression", "curve_point", "public_arg"),
    ("linked_broken_path_minimum_expression", "fixed_point", "public_arg"),
    ("linked_broken_path_minimum_expression", "moving_point", "public_arg"),
    (
        "linked_broken_path_minimum_expression",
        "path_transformation",
        "exact_call_result",
    ),
    ("parameter_from_curve_point_on_quadratic", "point", "public_arg"),
    ("parameter_from_expression_value", "expression", "exact_call_result"),
    (
        "parameter_from_minimum_value",
        "minimum_expression",
        "exact_call_result",
    ),
    ("parameter_from_segment_length", "p1", "public_arg"),
    ("parameter_from_segment_length", "p2", "public_arg"),
    ("parameter_from_segment_length", "reference_p1", "public_arg"),
    ("parameter_from_segment_length", "reference_p2", "public_arg"),
    ("parameterized_point_locus_line", "point", "public_arg"),
    (
        "point_candidates_from_curve_point_condition",
        "curve_point",
        "public_arg",
    ),
    (
        "point_candidates_from_curve_point_condition",
        "target_point",
        "public_arg",
    ),
    ("square_adjacent_vertex_from_side", "side_end", "public_arg"),
    ("square_adjacent_vertex_from_side", "side_start", "public_arg"),
    ("translated_point", "source", "public_arg"),
}

C2_MIGRATED_BINDINGS = {
    ("angle_sum_equal_angle_candidates", "condition", "condition"),
    ("angle_sum_equal_angle_candidates", "origin", "latest_state"),
    (
        "angle_sum_equal_angle_candidates",
        "reference_x_axis_point",
        "latest_state",
    ),
    ("angle_sum_equal_angle_candidates", "x_axis_point", "latest_state"),
    ("angle_sum_equal_angle_candidates", "y_axis_point", "latest_state"),
    (
        "axis_intercept_from_equal_acute_angles",
        "angle_equality",
        "exact_call_result",
    ),
    (
        "axis_intercept_from_equal_acute_angles",
        "origin",
        "producer_linked",
    ),
    (
        "axis_intercept_from_equal_acute_angles",
        "reference_x_axis_point",
        "producer_linked",
    ),
    (
        "axis_intercept_from_equal_acute_angles",
        "x_axis_point",
        "producer_linked",
    ),
    (
        "axis_intercept_from_equal_acute_angles",
        "y_axis_point",
        "producer_linked",
    ),
    (
        "linked_broken_path_minimum_expression",
        "dynamic_constraint",
        "condition",
    ),
    (
        "linked_broken_path_minimum_expression",
        "dynamic_parameter",
        "free_symbol_basis",
    ),
    (
        "linked_broken_path_minimum_expression",
        "parameter_constraint",
        "condition",
    ),
    ("midpoint_point", "p1", "entity_identity"),
    ("midpoint_point", "p2", "entity_identity"),
    (
        "parameter_from_curve_point_on_quadratic",
        "parameter_constraint",
        "condition",
    ),
    ("parameter_from_expression_value", "condition", "condition"),
    ("parameter_from_expression_value", "constraint", "condition"),
    ("parameter_from_minimum_value", "condition", "condition"),
    ("parameter_from_minimum_value", "constraint", "condition"),
    ("parameter_from_segment_length", "condition", "condition"),
    ("parameter_from_segment_length", "constraint", "condition"),
    ("quadratic_axis_from_relation", "a", "canonical_symbol"),
    ("quadratic_axis_from_relation", "b", "canonical_symbol"),
    (
        "quadratic_axis_from_relation",
        "coefficient_relation",
        "condition",
    ),
    ("quadratic_from_constraints", "coefficient_relation", "condition"),
    ("right_angle_equal_length_candidates", "anchor", "latest_state"),
    ("right_angle_equal_length_candidates", "reference", "latest_state"),
    ("square_adjacent_vertex_from_side", "parameter_constraint", "condition"),
    (
        "square_adjacent_vertex_from_side",
        "side_end_ref",
        "source_object_identity",
    ),
    (
        "square_adjacent_vertex_from_side",
        "side_start_ref",
        "source_object_identity",
    ),
    ("square_adjacent_vertex_from_side", "square_condition", "condition"),
    (
        "square_path_dimension_reduction",
        "fixed_endpoint_1_ref",
        "entity_identity",
    ),
    (
        "square_path_dimension_reduction",
        "fixed_endpoint_2_ref",
        "entity_identity",
    ),
    (
        "square_path_dimension_reduction",
        "midpoint_condition",
        "condition",
    ),
    (
        "square_path_dimension_reduction",
        "path_condition",
        "condition",
    ),
    (
        "square_path_dimension_reduction",
        "square_center_condition",
        "condition",
    ),
    (
        "square_path_dimension_reduction",
        "square_condition",
        "condition",
    ),
    ("two_moving_points_path_reduction", "binding_relation", "condition"),
    (
        "two_moving_points_path_reduction",
        "first_moving_membership",
        "condition",
    ),
    (
        "two_moving_points_path_reduction",
        "first_segment_start",
        "latest_state",
    ),
    ("two_moving_points_path_reduction", "joint_point", "latest_state"),
    ("two_moving_points_path_reduction", "original_path", "condition"),
    (
        "two_moving_points_path_reduction",
        "second_moving_membership",
        "condition",
    ),
    (
        "two_moving_points_path_reduction",
        "second_segment_end",
        "latest_state",
    ),
    ("weighted_axis_path_triangle_transform", "condition", "condition"),
    (
        "weighted_axis_path_triangle_transform",
        "dynamic_parameter",
        "free_symbol_basis",
    ),
    ("weighted_axis_path_triangle_transform", "fixed_point", "public_arg"),
    (
        "weighted_axis_path_triangle_transform",
        "linked_fixed_endpoint_ref",
        "entity_identity",
    ),
    ("weighted_axis_path_triangle_transform", "moving_point", "public_arg"),
    (
        "weighted_axis_path_triangle_transform",
        "moving_point_ref",
        "source_object_identity",
    ),
}

C3_MIGRATED_BINDINGS = {
    ("angle_sum_equal_angle_candidates", "target", "entity_identity"),
    (
        "axis_intercept_from_equal_acute_angles",
        "target",
        "previous_output_identity",
    ),
    ("equal_length_ray_point", "anchor", "macro_prepared_role"),
    ("equal_length_ray_point", "ray_point", "macro_prepared_role"),
    (
        "equal_length_ray_point",
        "reference_point",
        "macro_prepared_role",
    ),
    ("equal_length_ray_point", "target", "previous_output_identity"),
    ("line_intersection_point", "target", "previous_output_identity"),
    ("line_intersection_point", "parameter", "source_object_identity"),
    ("line_locus_minimum_point", "minimum_point_1", "exact_call_result"),
    ("line_locus_minimum_point", "minimum_point_2", "exact_call_result"),
    ("line_locus_minimum_point", "parameter", "source_object_identity"),
    (
        "line_locus_minimum_point",
        "target",
        "previous_output_identity",
    ),
    (
        "line_parabola_second_intersection_point",
        "target",
        "previous_output_identity",
    ),
    ("midpoint_point", "target", "previous_output_identity"),
    ("point_on_parabola_at_x", "target", "previous_output_identity"),
    ("quadratic_axis_from_relation", "target", "previous_output_identity"),
    (
        "quadratic_axis_parameterized_point",
        "target",
        "previous_output_identity",
    ),
    (
        "quadratic_axis_x_intercept_point",
        "target",
        "previous_output_identity",
    ),
    ("quadratic_vertex_point", "target", "previous_output_identity"),
    ("quadratic_x_axis_intercept_point", "known_point", "public_arg"),
    (
        "quadratic_x_axis_intercept_point",
        "target",
        "previous_output_identity",
    ),
    ("quadratic_x_axis_intercept_point", "target_state", "latest_state"),
    (
        "quadratic_y_axis_intercept_point",
        "target",
        "previous_output_identity",
    ),
    ("right_angle_equal_length_candidates", "target", "public_arg"),
    ("distance_between_points", "parameter", "source_object_identity"),
    ("evaluate_point_at_parameter", "parameter", "source_object_identity"),
    (
        "square_adjacent_vertex_from_side",
        "parameter",
        "source_object_identity",
    ),
    (
        "square_adjacent_vertex_from_side",
        "target",
        "previous_output_identity",
    ),
    ("translated_point", "target", "previous_output_identity"),
    (
        "weighted_axis_path_triangle_transform",
        "auxiliary_point_ref",
        "previous_output_identity",
    ),
}

D_MIGRATED_BINDINGS = {
    (
        "quadratic_from_constraints",
        "parameter_value",
        "public_arg",
    ),
    (
        "quadratic_from_constraints",
        "parameter",
        "source_object_identity",
    ),
    (
        "parameter_from_curve_point_on_quadratic",
        "known_parameter_value",
        "exact_parameter_substitution",
    ),
}

F4_3C_RETIRED_PUBLIC_METHODS = {
    "quadratic_axis_x_intercept_point",
    "square_path_dimension_reduction",
    "parameterized_point_locus_line",
    "line_locus_minimum_point",
}


def _schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.mark.parametrize("source", SOURCE_VARIANTS)
def test_typed_source_variants_round_trip_and_match_schema(source) -> None:
    binding = MethodInputBindingSpec(input_name="value", source=source)
    payload = binding.to_payload()

    assert MethodInputBindingSpec.from_payload(payload) == binding
    assert not tuple(_schema_validator().iter_errors(payload))


@pytest.mark.parametrize("derivation", DERIVATION_VARIANTS)
def test_typed_derivation_variants_round_trip_and_match_schema(
    derivation,
) -> None:
    binding = MethodInputBindingSpec(
        input_name="derived_value",
        required=False,
        derivation=derivation,
    )
    payload = binding.to_payload()

    assert MethodInputBindingSpec.from_payload(payload) == binding
    assert not tuple(_schema_validator().iter_errors(payload))


def test_strict_binding_has_no_selector_or_legacy_authority_fields() -> None:
    field_names = {item.name for item in fields(MethodInputBindingSpec)}
    payload = MethodInputBindingSpec(
        input_name="point",
        source=EntityIdentitySourceSpec(arg_name="point"),
    ).to_payload()

    assert field_names.isdisjoint(
        {"selector", "functional_authority", "functional_resolver"}
    )
    assert set(payload).isdisjoint(
        {"selector", "functional_authority", "functional_resolver"}
    )


@pytest.mark.parametrize(
    "factory",
    (
        lambda: MethodInputBindingSpec(input_name="value"),
        lambda: MethodInputBindingSpec(
            input_name="value",
            source=PublicArgSourceSpec("value"),
            derivation=CanonicalSymbolDerivationSpec("x"),
        ),
        lambda: MethodInputBindingSpec(
            input_name=" ",
            source=PublicArgSourceSpec("value"),
        ),
        lambda: MethodInputBindingSpec(
            input_name="value",
            required="yes",  # type: ignore[arg-type]
            source=PublicArgSourceSpec("value"),
        ),
        lambda: MethodInputBindingSpec(
            input_name="value",
            source=object(),  # type: ignore[arg-type]
        ),
        lambda: EntityIdentitySourceSpec(semantic_roles=("point", "point")),
        lambda: ExactCallResultSourceSpec(
            "minimum_point",
            ("straightened_endpoint", "straightened_endpoint"),
        ),
        lambda: ConditionSourceSpec(
            condition_kinds=("point_on_curve",),
            related_args=(),
        ),
        lambda: FreeSymbolBasisDerivationSpec(("a", "a")),
    ),
)
def test_typed_contract_rejects_invalid_direct_declarations(factory) -> None:
    with pytest.raises(MethodInputBindingContractError) as error:
        factory()

    assert error.value.code == "planner.method_input_binding_contract_invalid"


@pytest.mark.parametrize(
    "payload",
    (
        {
            "schema_version": "method-input-binding/v1",
            "input_name": "value",
            "required": True,
            "source": {"kind": "unknown", "arg_name": "value"},
        },
        {
            "schema_version": "method-input-binding/v1",
            "input_name": 1,
            "required": True,
            "source": {"kind": "public_arg", "arg_name": "value"},
        },
        {
            "schema_version": "method-input-binding/v1",
            "input_name": "value",
            "required": True,
            "source": {"kind": "public_arg", "arg_name": "value"},
            "selector": "read_type:Point",
        },
    ),
)
def test_python_codec_and_json_schema_reject_the_same_invalid_payloads(
    payload,
) -> None:
    with pytest.raises(MethodInputBindingContractError):
        MethodInputBindingSpec.from_payload(payload)

    assert tuple(_schema_validator().iter_errors(payload))


@pytest.mark.parametrize(
    ("source", "required_view"),
    (
        (EntityIdentitySourceSpec(arg_name="point"), "identity"),
        (LatestStateSourceSpec("point"), "latest_state"),
        (ConditionSourceSpec(arg_name="point_on_curve"), "immutable_value"),
        (ExactCallResultSourceSpec("candidate"), "exact_result"),
    ),
)
def test_source_contract_rejects_an_incompatible_method_view(
    source,
    required_view: MethodInputViewMode,
) -> None:
    binding = MethodInputBindingSpec(input_name="value", source=source)
    compatible = MethodInputSpec(
        name="value",
        domain_type="Point",
        runtime_type="Point",
        view=MethodInputViewSpec(
            mode=required_view,
            domain_type="Point",
        ),
    )
    incompatible = MethodInputSpec(
        name="value",
        domain_type="Point",
        runtime_type="Point",
        view=MethodInputViewSpec(
            mode=("exact_result" if required_view != "exact_result" else "identity"),
            domain_type="Point",
        ),
    )

    validate_method_input_binding_view(binding, compatible)
    with pytest.raises(MethodInputBindingContractError):
        validate_method_input_binding_view(binding, incompatible)


def test_typed_binding_without_lowerer_fails_without_selection_fallback() -> None:
    adapter = FunctionAdapterSpec(
        adapter_id="typed_not_migrated",
        input_bindings=(
            MethodInputBindingSpec(
                input_name="point",
                source=PublicArgSourceSpec("point"),
            ),
        ),
    )
    registry = FunctionAdapterRegistry(adapters={"typed_not_migrated": adapter})
    with pytest.raises(StatelessMethodError) as error:
        registry.bind(
            "typed_not_migrated",
            SimpleNamespace(step_id="typed_step"),
            SimpleNamespace(problem_binding_authority=False),
        )

    assert error.value.code == "planner.method_input_binding_lowerer_missing"
    assert error.value.retryability == "configuration"
    assert not hasattr(registry, "_select")
    assert not hasattr(registry, "_expand")


def test_recipe_derivation_wraps_shared_contract_without_payload_drift() -> None:
    derivation = RecipeInputDerivationSpec(
        target="distance_between_points.parameter",
        derivation=SourceObjectIdentityDerivationSpec("parameter_value"),
    )

    assert derivation.to_payload() == {
        "source_arg": "parameter_value",
        "target": "distance_between_points.parameter",
        "kind": "source_object_identity",
    }


def test_all_production_bindings_use_the_strict_contract() -> None:
    assert all(
        isinstance(binding, MethodInputBindingSpec)
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )


def test_migrated_inputs_use_the_strict_binding_contract() -> None:
    actual = {
        (
            rule.method_id,
            binding.input_name,
            (binding.source or binding.derivation).kind,
        )
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
        if isinstance(binding, MethodInputBindingSpec)
    }

    expected = (
        MIGRATED_QUADRATIC_BINDINGS
        | C1_MIGRATED_BINDINGS
        | C2_MIGRATED_BINDINGS
        | C3_MIGRATED_BINDINGS
        | D_MIGRATED_BINDINGS
    )
    expected = {
        item for item in expected if item[0] not in F4_3C_RETIRED_PUBLIC_METHODS
    }
    assert actual == expected
    assert all(
        not hasattr(rule, "expansion_selectors")
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
    )


def test_legacy_source_declaration_count_is_zero() -> None:
    sources = [
        (REPO_ROOT / "server" / relative).read_text(encoding="utf-8")
        for relative in FAMILY_BINDING_FILES
    ]

    assert all("LegacySelectorInputBindingSpec" not in source for source in sources)
    assert all("LegacyExpansionSelectorSpec" not in source for source in sources)


def test_c1_retires_all_production_read_type_selectors() -> None:
    assert all(
        "read_type:" not in binding.to_payload().__repr__()
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )


def test_c2_retires_fact_and_immutable_value_selectors() -> None:
    assert all(
        isinstance(binding, MethodInputBindingSpec)
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )


def test_c3_retires_output_transition_and_geometry_selectors() -> None:
    assert len(C3_MIGRATED_BINDINGS) == 30


def test_new_schema_excludes_legacy_selector_payload() -> None:
    legacy = {
        "input_name": "point",
        "selector": "read_type:Point",
        "required": True,
    }

    assert tuple(_schema_validator().iter_errors(legacy))
