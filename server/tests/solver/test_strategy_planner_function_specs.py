from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import (
    MethodInputSpec,
    MethodInputViewSpec,
    MethodSpec,
)
from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    StateSlotPattern,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.function_specs import (
    GENERIC_FUNCTION_ADAPTERS,
    GENERIC_FUNCTION_BINDING_RULES,
    GENERIC_FUNCTION_METHOD_IDS,
    FunctionSpec,
    FunctionSpecRegistry,
    _analyze_quadratic_coefficient_inputs,
    function_spec_from_method,
    function_catalog_payload,
)
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    StatelessMethodError,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
    analyze_quadratic_constraints,
)
from shuxueshuo_server.solver.runtime.symbolic_state_representation import (
    SymbolicStateRepresentationError,
)
from shuxueshuo_server.solver.runtime.recipe_compiler import _preserved_object_ref
from shuxueshuo_server.solver.runtime.strategy_planner import (
    MethodBindingRuleRegistry,
    StrategyDraftValidationError,
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.functional_direct_compiler import (
    FunctionalCapabilityCompileCall,
    FunctionalReturnOutput,
)


REPO_ROOT = Path(__file__).resolve().parents[3]

FUNCTIONAL_FIXTURES = (
    REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-hexi-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-xiqing-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-yimo-25.json",
    REPO_ROOT / "internal/solver-fixtures/tj-2026-heping-ermo-25.json",
)


def test_function_spec_registry_derives_generic_methods_from_contracts() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
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


def test_function_spec_registry_models_non_adapter_point_identity() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[4]))
    inputs = build_strategy_probe_inputs(problem)
    registry = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    square = registry.require("square_adjacent_vertex_from_side")
    assert square.adapter is None
    assert square.returns[0].identity_policy == "target_object"
    assert square.returns[0].identity_arg == "target"

    candidates = registry.require("point_candidates_from_curve_point_condition")
    assert candidates.adapter is None

    axis_parameterized = registry.require("quadratic_axis_parameterized_point")
    returns = {item.output_key: item for item in axis_parameterized.returns}
    assert returns["point"].write_mode == "create"
    assert returns["parameter"].runtime_type == "Symbol"
    assert returns["parameter"].identity_policy == "derived_role"

    locus_minimum = registry.require("line_locus_minimum_point")
    assert locus_minimum.returns[0].write_mode == "transition"
    assert candidates.returns[0].runtime_type == "PointList"
    assert candidates.returns[0].identity_policy == "preserve_input_object"
    assert candidates.returns[0].identity_arg == "target_point"


def test_optional_parameter_value_requires_explicit_wire_authority() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[4]))
    inputs = build_strategy_probe_inputs(problem)
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    for capability_id in (
        "square_adjacent_vertex_from_side",
        "distance_between_points",
    ):
        capability = catalog.items[capability_id]
        parameter_value = next(
            item for item in capability.args if item.name == "parameter_value"
        )
        assert parameter_value.required is False
        assert parameter_value.binding_authority == "wire"
        assert parameter_value.deterministic_resolver is None


def test_quadratic_constraint_analyzer_declarations_are_consistent() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    function = registry.require("quadratic_from_constraints")
    contract = next(
        item
        for item in inputs.family_spec.capability_contracts
        if item.capability_id == "quadratic_from_constraints"
    )
    assert inputs.method_specs.require(
        "quadratic_from_constraints"
    ).constraint_analyzer == "quadratic_coefficients"
    assert contract.constraint_analyzer == "quadratic_coefficients"
    assert function.adapter is not None
    assert function.adapter.constraint_analyzer == "quadratic_coefficients"


def _run_quadratic_input_analyzer(runtime_inputs: dict[str, object]):
    class _Context:
        def read_path(self, path, **_kwargs):
            return SimpleNamespace(value=runtime_inputs[path])

    return _analyze_quadratic_coefficient_inputs(
        {name: name for name in runtime_inputs},
        SimpleNamespace(scope_id="ii", step_id="derive_parabola_ii"),
        SimpleNamespace(context=_Context()),
    )


@pytest.mark.parametrize("authored_empty", [False, True])
def test_open_quadratic_state_requires_nonempty_free_parameter_basis(
    authored_empty: bool,
) -> None:
    x, b, c = sp.symbols("x b c")
    runtime_inputs: dict[str, object] = {
        "quadratic": x**2 - b * x + c,
        "x": x,
        "all_coefficients": (b, c),
        "coefficient_relation": sp.Eq(b + c, -1),
    }
    if authored_empty:
        runtime_inputs["free_parameters"] = []

    with pytest.raises(StatelessMethodError) as captured:
        _run_quadratic_input_analyzer(runtime_inputs)

    diagnostic = captured.value.authority.to_payload()
    assert diagnostic["code"] == "functional.method_input_state_unavailable"
    assert diagnostic["retryability"] == "planner_repairable"
    assert diagnostic["repair_action"] == (
        "provide_or_align_symbolic_state_basis"
    )
    assert diagnostic["expected"] == {
        "allowed_free_parameter_bases": [["b"], ["c"]],
        "basis_cardinality": 1,
    }
    assert diagnostic["observed"] == {"declared_free_parameters": []}
    assert "requires an explicit non-empty" in diagnostic["original_message"]


@pytest.mark.parametrize("authored_empty", [False, True])
def test_closed_quadratic_state_accepts_omitted_or_empty_free_parameters(
    authored_empty: bool,
) -> None:
    x, b, c = sp.symbols("x b c")
    runtime_inputs: dict[str, object] = {
        "quadratic": x**2 - b * x + c,
        "x": x,
        "all_coefficients": (b, c),
        "known_coefficients": {b: 2, c: 3},
    }
    if authored_empty:
        runtime_inputs["free_parameters"] = []

    result = _run_quadratic_input_analyzer(runtime_inputs)

    assert result.inputs == {name: name for name in runtime_inputs}


@pytest.mark.parametrize("basis_name", ["b", "c"])
def test_open_quadratic_state_accepts_runtime_equivalent_authored_basis(
    basis_name: str,
) -> None:
    x, b, c = sp.symbols("x b c")
    symbols = {"b": b, "c": c}
    runtime_inputs: dict[str, object] = {
        "quadratic": x**2 - b * x + c,
        "x": x,
        "all_coefficients": (b, c),
        "coefficient_relation": sp.Eq(b + c, -1),
        "free_parameters": [symbols[basis_name]],
    }

    result = _run_quadratic_input_analyzer(runtime_inputs)

    assert result.inputs == {name: name for name in runtime_inputs}


def test_open_quadratic_state_rejects_dependent_or_overspecified_basis() -> None:
    x, b, c = sp.symbols("x b c")
    runtime_inputs: dict[str, object] = {
        "quadratic": x**2 - b * x + c,
        "x": x,
        "all_coefficients": (b, c),
        "coefficient_relation": sp.Eq(b + c, -1),
        "free_parameters": [b, c],
    }

    with pytest.raises(StatelessMethodError) as captured:
        _run_quadratic_input_analyzer(runtime_inputs)

    diagnostic = captured.value.authority.to_payload()
    assert diagnostic["code"] == "functional.method_input_state_unavailable"
    assert diagnostic["expected"]["allowed_free_parameter_bases"] == [
        ["b"],
        ["c"],
    ]
    assert diagnostic["observed"]["declared_free_parameters"] == ["b", "c"]


def test_closed_quadratic_state_rejects_nonempty_free_parameter_basis() -> None:
    x, b, c = sp.symbols("x b c")
    runtime_inputs: dict[str, object] = {
        "quadratic": x**2 - b * x + c,
        "x": x,
        "all_coefficients": (b, c),
        "known_coefficients": {b: 2, c: 3},
        "free_parameters": [b],
    }

    with pytest.raises(StatelessMethodError) as captured:
        _run_quadratic_input_analyzer(runtime_inputs)

    diagnostic = captured.value.authority.to_payload()
    assert diagnostic["code"] == "functional.method_input_invalid"
    assert diagnostic["expected"] == {"free_parameters": []}
    assert diagnostic["observed"] == {"declared_free_parameters": ["b"]}
    assert diagnostic["repair_action"] == "remove_redundant_free_parameters"


def test_quadratic_constraint_analyzer_preserves_only_valid_parameterization_basis() -> None:
    x, a, b, c, m = sp.symbols("x a b c m")
    base = {
        "quadratic": a * x**2 + b * x + c,
        "x": x,
        "all_coefficients": (a, b, c),
        "coefficient_relation": sp.Eq(2 * a + b, 0),
        "p1": (m, 1),
        "p2": (2, 1 - m),
    }

    with pytest.raises(
        SymbolicStateRepresentationError,
        match="function.state_representation_unresolved",
    ):
        analyze_quadratic_constraints(
            base,
            preferred_free_parameters=(a,),
        )
    valid = analyze_quadratic_constraints(
        {
            "quadratic": a * x**2 + b * x + c,
            "x": x,
            "all_coefficients": (a, b, c),
            "known_coefficients": {a: 2},
            "p1": (-1, 0),
        },
        preferred_free_parameters=(b,),
    )

    assert valid.status == "single_free"
    assert valid.free_parameters == (b,)


def test_curve_point_parameter_function_declares_state_transitions() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)
    function = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).require("parameter_from_curve_point_on_quadratic")
    returns = {item.output_key: item for item in function.returns}

    assert returns["parameter_value"].write_mode == "value"
    assert returns["point"].write_mode == "transition"
    assert returns["parabola"].write_mode == "transition"


def test_functional_catalog_hides_legacy_curve_parameter_primitive() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[4]))
    inputs = build_strategy_probe_inputs(problem)
    functions = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    assert functions.require("parameter_from_curve_point_on_quadratic")
    assert "parameter_from_curve_point_on_quadratic" not in catalog.items
    unified = catalog.items["quadratic_from_constraints"]
    assert {item.name for item in unified.args} >= {
        "known_coefficients",
        "coefficient_relation",
        "extra_equation",
        "curve_point",
        "curve_points",
        "parameter_value",
        "free_parameters",
        "target_parameter",
    }
    assert {item.name for item in unified.args}.isdisjoint(
        {"p1", "p2", "p3"}
    )
    free_parameters = next(
        item for item in unified.args if item.name == "free_parameters"
    )
    assert free_parameters.allows_empty_collection
    assert "开放状态必须填写非空基底" in free_parameters.description
    assert "闭合状态可填写[]或省略" in free_parameters.description
    parameter_return = next(
        item for item in unified.returns if item.name == "parameter_value"
    )
    assert not parameter_return.required
    assert parameter_return.identity_arg == "target_parameter"
    assert parameter_return.possible_forms == ("open_state", "closed_state")
    assert isinstance(unified.source, FunctionSpec)
    assert unified.source.symbolic_closure is not None
    assert unified.source.symbolic_closure.target_arg == "target_parameter"
    assert unified.source.symbolic_closure.substitution_outputs == (
        "coefficients",
        "parabola",
        "parameter_value",
    )


def test_expression_evaluation_preserves_same_parabola_as_transition() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)
    function = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).require("evaluate_expression_at_parameter")
    result = next(
        item
        for item in function.returns
        if item.output_key == "evaluated_parabola"
    )

    assert result.identity_policy == "preserve_input_object"
    assert result.identity_arg == "expression"
    assert result.write_mode == "transition"


def test_preserved_state_identity_filters_objects_by_runtime_type() -> None:
    path = "$problem.functions.parabola"
    index = SimpleNamespace(
        bindings={
            "point:ii:M": SimpleNamespace(path=path),
            "function:problem:parabola": SimpleNamespace(path=path),
        }
    )
    step = FunctionalCapabilityCompileCall(
        scope_id="ii_1",
        step_id="specialize_curve",
        capability_id="evaluate_expression_at_parameter",
        goal_type="derive_parabola",
        target_handle="answer:ii_1.parabola",
        input_handles=("point:ii:M",),
        created_entities=(),
        return_outputs=(),
    )

    object_ref = _preserved_object_ref(
        runtime_type="Parabola",
        input_path=path,
        source_handle="fact:ii:parametric_parabola",
        source=None,
        produced_handle="answer:ii_1.parabola",
        step=step,
        index=index,
    )

    assert object_ref == "function:problem:parabola"


def test_functional_capability_projects_runtime_behavior_metadata() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[-1]))
    inputs = build_strategy_probe_inputs(problem)
    capability = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).get("evaluate_point_at_parameter")

    assert capability is not None
    assert capability.is_pure
    assert capability.dependency_policy == "explicit_args"
    assert capability.reconciliation_validators == (
        "companion_symbol_coverage",
    )


def test_unknown_functional_reconciliation_validator_fails_preflight() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[-1]))
    inputs = build_strategy_probe_inputs(problem)
    method_id = "evaluate_point_at_parameter"
    method_specs = MethodSpecRegistry(
        {
            **inputs.method_specs.specs,
            method_id: replace(
                inputs.method_specs.require(method_id),
                reconciliation_validators=("missing_validator",),
            ),
        }
    )

    with pytest.raises(
        ValueError,
        match="functional reconciliation validator missing: missing_validator",
    ):
        FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            method_specs,
        )


def test_generic_function_method_ids_are_derived_from_binding_rules() -> None:
    assert GENERIC_FUNCTION_METHOD_IDS == tuple(
        rule.method_id for rule in GENERIC_FUNCTION_BINDING_RULES
    )


def test_function_catalog_prompt_payload_hides_runtime_binding_details() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
    inputs = build_strategy_probe_inputs(problem)

    catalog = function_catalog_payload(inputs.family_spec, inputs.method_specs)

    assert catalog["item_count"] > 0
    encoded = json.dumps(catalog, ensure_ascii=False)
    assert "selector" not in encoded
    assert "runtime_path" not in encoded
    assert "ContextPath" not in encoded
    assert "method_input" not in encoded


def test_function_arg_kind_is_runtime_type_driven_not_method_input_name() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[0]))
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


def test_internal_method_outputs_are_not_functional_returns() -> None:
    problem = load_problem_ir(str(FUNCTIONAL_FIXTURES[2]))
    inputs = build_strategy_probe_inputs(problem)
    method = inputs.method_specs.require(
        "linked_broken_path_minimum_expression"
    )
    functions = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    assert set(method.outputs) == {
        "minimum_expression",
        "dynamic_parameter_expression",
        "dynamic_point_expression",
    }
    assert method.internal_outputs == (
        "dynamic_parameter_expression",
        "dynamic_point_expression",
    )
    assert tuple(
        item.name
        for item in functions.require(
            "linked_broken_path_minimum_expression"
        ).returns
    ) == ("minimum_expression",)
    capability = catalog.get("linked_broken_path_minimum_expression")
    assert capability is not None
    assert tuple(item.name for item in capability.returns) == (
        "minimum_expression",
    )


def test_internal_method_output_cannot_be_a_contract_state_write() -> None:
    method = MethodSpec(
        method_id="synthetic_internal_output",
        title="Synthetic",
        solves=("derive_synthetic",),
        inputs={},
        outputs={
            "public_expression": "Expression",
            "runtime_witness": "Point",
        },
        internal_outputs=("runtime_witness",),
    )
    contract = CapabilityContractSpec(
        capability_id=method.method_id,
        kind="method",
        slot_writes=(
            StateSlotPattern(
                "coordinate",
                "Point",
                output_key="runtime_witness",
            ),
        ),
    )

    with pytest.raises(
        ValueError,
        match="internal method outputs cannot be Functional state writes",
    ):
        function_spec_from_method(
            method,
            contract=contract,
            adapter=None,
        )


def test_function_spec_notes_contract_return_mismatch() -> None:
    spec = function_spec_from_method(
        MethodSpec(
            method_id="synthetic_method",
            title="Synthetic",
            solves=("derive_synthetic",),
            inputs={
                "value": MethodInputSpec(
                    name="value",
                    domain_type="Expression",
                    runtime_type="Expression",
                    view=MethodInputViewSpec(
                        mode="immutable_value",
                        domain_type="Expression",
                    ),
                ),
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


def test_migrated_function_specs_have_no_required_contract_return_mismatch() -> None:
    for problem_path in FUNCTIONAL_FIXTURES:
        problem = load_problem_ir(str(problem_path))
        inputs = build_strategy_probe_inputs(problem)
        registry = FunctionSpecRegistry.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
        notes = [
            f"{spec.function_id}:{note}"
            for spec in registry.specs.values()
            for note in spec.notes
            if note.startswith("contract_slot_write_missing:required:")
        ]
        assert notes == []


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


def test_migrated_function_adapter_failure_does_not_fallback_to_legacy_rule() -> None:
    distance_rule = next(
        rule for rule in GENERIC_FUNCTION_BINDING_RULES
        if rule.method_id == "distance_between_points"
    )

    def failing_selector(_step, _index, _local_outputs):
        raise StrategyDraftValidationError("forced_missing_distance_endpoint")

    registry = MethodBindingRuleRegistry(
        rules=(distance_rule,),
        selectors={
            "distance:p1": failing_selector,
            "distance:p2": lambda _step, _index, _local_outputs: "$fake.p2",
        },
        expansion_selectors={
            "distance_parameter_value_if_read": (
                lambda _step, _index, _local_outputs: {}
            ),
        },
    )
    step = FunctionalCapabilityCompileCall(
        scope_id="problem",
        step_id="compute_distance",
        capability_id="distance_between_points",
        goal_type="derive_minimum_value",
        target_handle="fact:problem:distance",
        input_handles=(),
        created_entities=(),
        return_outputs=(
            FunctionalReturnOutput(
                "fact:problem:distance",
                "problem",
                "distance",
                "MinimumExpression",
            ),
        ),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="function.arg_missing: method=distance_between_points, arg=p1",
    ):
        registry.bind("distance_between_points", step, object())

    assert [event.status for event in registry.function_binding_events] == ["failure"]
    assert registry.function_binding_events[0].errors


def _diagnostic_payload(value: Any) -> dict[str, Any]:
    return value.to_payload() if hasattr(value, "to_payload") else dict(value)
