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
    FreeSymbolBasisDerivationSpec,
    LatestStateSourceSpec,
    LegacyExpansionSelectorSpec,
    LegacySelectorInputBindingSpec,
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
from shuxueshuo_server.solver.family.models import (
    MethodBindingRuleSpec,
    RecipeInputDerivationSpec,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionAdapterRegistry,
    FunctionAdapterSpec,
    function_adapter_from_binding_rule,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "internal/schemas/method-input-binding.schema.json"
BASELINE_PATH = (
    Path(__file__).parent / "fixtures/legacy_method_input_selectors.json"
)
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


def test_typed_binding_reaching_legacy_lowerer_fails_before_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FunctionAdapterSpec(
        adapter_id="typed_not_migrated",
        input_bindings=(
            MethodInputBindingSpec(
                input_name="point",
                source=PublicArgSourceSpec("point"),
            ),
        ),
    )
    registry = FunctionAdapterRegistry(
        selectors={},
        expansion_selectors={},
        adapters={"typed_not_migrated": adapter},
    )
    selector_calls: list[str] = []

    def forbidden_selector(*_args, **_kwargs):
        selector_calls.append("called")
        return "$problem.points.A"

    monkeypatch.setattr(registry, "_select", forbidden_selector)
    with pytest.raises(StatelessMethodError) as error:
        registry.bind(
            "typed_not_migrated",
            SimpleNamespace(step_id="typed_step"),
            SimpleNamespace(problem_binding_authority=False),
        )

    assert error.value.code == "planner.method_input_binding_lowerer_missing"
    assert error.value.retryability == "configuration"
    assert selector_calls == []


def test_legacy_binding_payload_and_adapter_projection_are_unchanged() -> None:
    binding = LegacySelectorInputBindingSpec(
        input_name="point",
        selector="read_type:Point",
        required=False,
        functional_authority="compiler",
        functional_resolver="unique_visible_point",
    )
    expected = {
        "input_name": "point",
        "selector": "read_type:Point",
        "required": False,
        "functional_authority": "compiler",
        "functional_resolver": "unique_visible_point",
    }
    rule = MethodBindingRuleSpec(
        method_id="legacy_method",
        input_bindings=(binding,),
    )
    adapter = function_adapter_from_binding_rule(rule)

    assert binding.to_payload() == expected
    assert adapter.input_bindings[0] is binding
    assert adapter.to_payload()["input_bindings"] == [expected]


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


def test_remaining_production_selectors_are_explicit_legacy_and_match_baseline() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    actual = sorted(
        {
            (rule.method_id, binding.input_name, binding.selector)
            for family in DEFAULT_FAMILY_REGISTRY.families
            for rule in family.method_binding_rules
            for binding in rule.input_bindings
            if isinstance(binding, LegacySelectorInputBindingSpec)
        }
    )

    assert baseline["schema_version"] == "legacy-method-input-selectors/v1"
    assert [list(item) for item in actual] == baseline["bindings"]
    assert all(
        isinstance(
            binding,
            (LegacySelectorInputBindingSpec, MethodInputBindingSpec),
        )
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )


def test_common_quadratic_inputs_use_the_strict_binding_contract() -> None:
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

    assert actual == MIGRATED_QUADRATIC_BINDINGS
    assert all(
        isinstance(selector, LegacyExpansionSelectorSpec)
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for selector in rule.expansion_selectors
    )
    assert all(
        prep.expansion_selectors is None
        or all(
            isinstance(selector, LegacyExpansionSelectorSpec)
            for selector in prep.expansion_selectors
        )
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for prep in rule.prep_invocations
    )


def test_legacy_source_declaration_count_is_frozen() -> None:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    sources = [
        (REPO_ROOT / "server" / relative).read_text(encoding="utf-8")
        for relative in FAMILY_BINDING_FILES
    ]

    assert sum(
        source.count("LegacySelectorInputBindingSpec(") for source in sources
    ) == baseline["source_declaration_count"] == 114


def test_new_schema_excludes_legacy_selector_payload() -> None:
    legacy = LegacySelectorInputBindingSpec("point", "read_type:Point")

    assert tuple(_schema_validator().iter_errors(legacy.to_payload()))
