from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.contracts import (
    ExactParameterSubstitutionSourceSpec,
    MethodInputBindingSpec,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime import binding_rules
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionAdapterRegistry,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    _exact_parameter_substitution_sources,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    functional_capability_catalog_payload,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCallReconciliation,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SOLVER_ROOT = REPO_ROOT / "server/shuxueshuo_server/solver"
SCHEMA_ROOT = REPO_ROOT / "internal/schemas"

RETIRED_INPUT_SELECTOR_SYMBOLS = (
    "LegacySelectorInputBindingSpec",
    "LegacyExpansionSelectorSpec",
    "DEFAULT_BINDING_SELECTORS",
    "DEFAULT_EXPANSION_SELECTORS",
    "CompilerSelectorReadSource",
    "compiler_selector",
    "binding_selector_semantics",
    "_parameter_symbol_from_reads_selector",
)


def _binding_rules(method_id: str):
    return tuple(
        rule
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        if rule.method_id == method_id
    )


def _parameter_version(name: str, ordinal: int = 1) -> StateVersionId:
    object_id = MathObjectId(f"symbol:problem:{name}", "symbol", "problem")
    return StateVersionId(
        StateSlotId(
            LogicalStateKey(object_id, "value", "ParameterValue"),
            "problem",
        ),
        ordinal,
    )


def _substitution_call(*versions: StateVersionId) -> FunctionalCallReconciliation:
    return FunctionalCallReconciliation(
        call_id="solve_parameter",
        scope_id="problem",
        capability_id="parameter_from_curve_point_on_quadratic",
        resolved_args={
            "quadratic": (
                ResolvedFunctionalValue(
                    handle="parabola",
                    runtime_type="Parabola",
                    valid_scope="problem",
                    source_version_ids=versions,
                ),
            ),
        },
        returns=(),
    )


def test_production_input_selector_runtime_is_physically_retired() -> None:
    sources = {
        path: path.read_text(encoding="utf-8")
        for path in SOLVER_ROOT.rglob("*.py")
    }

    for symbol in RETIRED_INPUT_SELECTOR_SYMBOLS:
        offenders = [
            str(path.relative_to(REPO_ROOT))
            for path, source in sources.items()
            if symbol in source
        ]
        assert offenders == [], f"{symbol} remains in {offenders}"

    assert not hasattr(FunctionAdapterRegistry, "_select")
    assert not hasattr(FunctionAdapterRegistry, "_expand")
    assert not hasattr(binding_rules, "_known_parameter_substitution_pair")


def test_companion_output_selector_debt_is_fixed_and_output_only() -> None:
    actual = {
        (
            rule.method_id,
            companion.output_name,
            companion.target_selector,
            companion.registration_selector,
        )
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for companion in rule.companion_outputs
    }

    # This output-registration compatibility boundary may only shrink until
    # F4.3 replaces it with a typed companion-output contract.
    assert actual == {
        (
            "quadratic_axis_parameterized_point",
            "parameter",
            "axis_parameter_symbol",
            "axis_parameter_symbol",
        ),
        (
            "quadratic_from_constraints",
            "coefficients",
            "answer_scope_output:coefficients",
            "runtime_step_output:coefficients",
        ),
        (
            "weighted_axis_path_triangle_transform",
            "auxiliary_locus",
            "scope_output:auxiliary_locus",
            "runtime_step_output:auxiliary_locus",
        ),
        (
            "weighted_axis_path_triangle_transform",
            "auxiliary_point",
            "weighted_path_auxiliary_point",
            "weighted_path_auxiliary_point",
        ),
    }


def test_every_production_method_input_binding_is_strict() -> None:
    declarations = tuple(
        binding
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )

    assert declarations
    assert all(isinstance(item, MethodInputBindingSpec) for item in declarations)
    assert all(
        not hasattr(rule, "expansion_selectors")
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
    )


def test_last_optional_bindings_are_declarative() -> None:
    quadratic_rules = _binding_rules("quadratic_from_constraints")
    assert quadratic_rules
    free_parameter_lowerings = []
    for rule in quadratic_rules:
        assert all(
            item.input_name != "free_parameter" for item in rule.input_bindings
        )
        free_parameter_lowerings.extend(
            item
            for item in rule.aggregate_input_bindings
            if item.source_input == "free_parameters"
        )
    assert free_parameter_lowerings
    assert all(
        item.singleton_input == "free_parameter"
        for item in free_parameter_lowerings
    )

    parameter_rules = _binding_rules(
        "parameter_from_curve_point_on_quadratic"
    )
    assert parameter_rules
    for rule in parameter_rules:
        binding = next(
            item
            for item in rule.input_bindings
            if item.input_name == "known_parameter_value"
        )
        assert binding.required is False
        assert binding.source == ExactParameterSubstitutionSourceSpec(
            source_inputs=("quadratic", "point"),
            target_input="parameter",
        )


def test_exact_parameter_substitution_uses_only_exact_declared_lineage() -> None:
    target = _parameter_version("b")
    known = _parameter_version("c")
    other = _parameter_version("m")

    assert _exact_parameter_substitution_sources(
        ("quadratic", "point"),
        target_ids=frozenset({target.slot_id.logical_key.object_id}),
        call=_substitution_call(),
        scope_id="problem",
        handle_registry=None,
    ) == []

    selected = _exact_parameter_substitution_sources(
        ("quadratic", "point"),
        target_ids=frozenset({target.slot_id.logical_key.object_id}),
        call=_substitution_call(target, known),
        scope_id="problem",
        handle_registry=None,
    )
    assert [item.state_version_id for item in selected] == [known]

    ambiguous = _exact_parameter_substitution_sources(
        ("quadratic", "point"),
        target_ids=frozenset({target.slot_id.logical_key.object_id}),
        call=_substitution_call(known, other),
        scope_id="problem",
        handle_registry=None,
    )
    assert {item.state_version_id for item in ambiguous} == {known, other}


def test_prompt_catalog_has_no_input_selector_metadata() -> None:
    method_specs = MethodSpecRegistry.load_from_code()
    payloads = (
        functional_capability_catalog_payload(family, method_specs)
        for family in DEFAULT_FAMILY_REGISTRY.families
    )

    assert all("selector" not in json.dumps(payload) for payload in payloads)


def test_binding_schemas_reject_retired_selector_payloads() -> None:
    for schema_name in (
        "method-input-binding.schema.json",
        "problem-planning-binding-catalog.schema.json",
        "functional-problem-binding-context.schema.json",
    ):
        schema = json.loads((SCHEMA_ROOT / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert "compiler_selector" not in json.dumps(schema)

    method_schema = json.loads(
        (SCHEMA_ROOT / "method-input-binding.schema.json").read_text(
            encoding="utf-8"
        )
    )
    retired_payload = {
        "input_name": "point",
        "required": True,
        "selector": "read_type:Point",
    }
    assert tuple(
        Draft202012Validator(method_schema).iter_errors(retired_payload)
    )


def test_equal_length_role_provider_is_debug_only() -> None:
    production_sources = tuple(
        path.read_text(encoding="utf-8")
        for path in SOLVER_ROOT.rglob("*.py")
        if path.name != "debug_equal_length_ray_roles.py"
    )

    assert all(
        "debug_equal_length_ray_roles" not in source
        for source in production_sources
    )
