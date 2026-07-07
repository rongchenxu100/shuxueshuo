from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shuxueshuo_server.solver.contracts import MethodInputSpec, MethodSpec
from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    StateSlotPattern,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.function_specs import (
    GENERIC_FUNCTION_ADAPTERS,
    GENERIC_FUNCTION_BINDING_RULES,
    GENERIC_FUNCTION_METHOD_IDS,
    FunctionSpecRegistry,
    assert_no_function_adapter_fallbacks,
    function_spec_from_method,
    function_catalog_payload,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    RecipeTrialExecutor,
    StepIntentValidator,
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


def test_function_spec_registry_derives_generic_methods_from_contracts() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)

    registry = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    generic_methods = [
        method_id
        for method_id in GENERIC_FUNCTION_METHOD_IDS
        if method_id in inputs.family_spec.method_ids
    ]
    assert generic_methods
    for method_id in generic_methods:
        spec = registry.require(method_id)
        assert spec.function_id == method_id
        assert spec.method_id == method_id
        assert spec.adapter is not None
        assert spec.returns
        assert spec.source in {
            "explicit_contract",
            "projected_contract",
            "method_spec",
        }
        json.dumps(spec.to_payload(), ensure_ascii=False, sort_keys=True)


def test_function_catalog_prompt_payload_hides_runtime_binding_details() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)

    catalog = function_catalog_payload(inputs.family_spec, inputs.method_specs)

    assert catalog["item_count"] > 0
    encoded = json.dumps(catalog, ensure_ascii=False)
    assert "selector" not in encoded
    assert "runtime_path" not in encoded
    assert "ContextPath" not in encoded
    assert "method_input" not in encoded


def test_function_arg_kind_is_runtime_type_driven_not_method_input_name() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    quadratic = registry.require("quadratic_from_constraints")
    kinds = {arg.name: arg.kind for arg in quadratic.args}

    assert kinds["quadratic"] == "slot_read"
    assert kinds["x"] == "symbol"
    assert kinds["all_coefficients"] == "slot_read"

    parameter_solver = registry.require("parameter_from_expression_value")
    parameter_kinds = {arg.name: arg.kind for arg in parameter_solver.args}
    assert parameter_kinds["parameter"] == "symbol"
    assert parameter_kinds["constraint"] == "condition_read"


def test_function_spec_notes_contract_return_mismatch() -> None:
    spec = function_spec_from_method(
        MethodSpec(
            method_id="synthetic_method",
            title="Synthetic",
            solves=("derive_synthetic",),
            inputs={
                "value": MethodInputSpec("value", "Expression"),
            },
            outputs={"expression": "Expression"},
        ),
        contract=CapabilityContractSpec(
            capability_id="synthetic_method",
            kind="method",
            slot_writes=(
                StateSlotPattern("expression", "Expression"),
                StateSlotPattern("coordinate", "Point", required=False),
            ),
        ),
        adapter=None,
    )

    assert "contract_slot_write_missing:optional:Point" in spec.notes
    assert not any(note.endswith(":Expression") for note in spec.notes)


def test_generic_function_adapters_are_projected_from_common_binding_rules() -> None:
    """Generic adapter selector truth lives in common binding rules."""
    assert set(GENERIC_FUNCTION_ADAPTERS) == set(GENERIC_FUNCTION_METHOD_IDS)
    assert {rule.method_id for rule in GENERIC_FUNCTION_BINDING_RULES} == set(
        GENERIC_FUNCTION_METHOD_IDS
    )
    for rule in GENERIC_FUNCTION_BINDING_RULES:
        adapter = GENERIC_FUNCTION_ADAPTERS[rule.method_id]
        assert adapter.adapter_id == rule.method_id
        assert [
            (item.input_name, item.selector, item.required)
            for item in adapter.input_bindings
        ] == [
            (item.input_name, item.selector, item.required)
            for item in rule.input_bindings
        ]
        assert adapter.expansion_selectors == rule.expansion_selectors


def test_recorded_fixtures_compile_generic_methods_without_function_fallbacks() -> None:
    for problem_path, step_intents_path in RECORDED_FIXTURES:
        problem = load_problem_ir(str(problem_path))
        inputs = build_strategy_probe_inputs(problem)
        problem_payload = problem_to_llm_payload(problem)
        handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
        raw = step_intents_path.read_text(encoding="utf-8")
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

        assert diagnostic.ok, _diagnostic_payload(diagnostic)
        assert diagnostic.function_binding_events
        assert_no_function_adapter_fallbacks(diagnostic.function_binding_events)


def _diagnostic_payload(value: Any) -> dict[str, Any]:
    return value.to_payload() if hasattr(value, "to_payload") else dict(value)
