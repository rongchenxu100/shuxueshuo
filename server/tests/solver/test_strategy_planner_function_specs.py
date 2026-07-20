from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import MethodInputSpec, MethodSpec
from shuxueshuo_server.solver.family.models import (
    CapabilityContractSpec,
    StateSlotPattern,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.answer_goal_verifier import AnswerGoalVerifier
from shuxueshuo_server.solver.runtime.function_specs import (
    GENERIC_FUNCTION_ADAPTERS,
    GENERIC_FUNCTION_BINDING_RULES,
    GENERIC_FUNCTION_METHOD_IDS,
    FunctionSpecRegistry,
    assert_no_function_adapter_failures,
    function_spec_from_method,
    function_catalog_payload,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods.quadratic_from_constraints import (
    analyze_quadratic_constraints,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.recipe_compiler import _preserved_object_ref
from shuxueshuo_server.solver.runtime.strategy_planner import (
    CanonicalHandleRegistry,
    MethodBindingRuleRegistry,
    ProducedFact,
    RecipeTrialExecutor,
    StepIntent,
    StepIntentValidator,
    StrategyDraftValidationError,
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.state_dependency_graph import (
    drop_dead_pure_function_steps,
)
from shuxueshuo_server.solver.runtime.strategy_repair_guidance import (
    RepairGuidanceResolver,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    StepIntentDraft,
    StepIntentScope,
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


def test_function_spec_registry_models_non_adapter_point_identity() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[4][0]))
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


def test_recorded_point_answers_have_verified_function_or_macro_identity() -> None:
    for problem_path, step_intents_path in RECORDED_FIXTURES:
        problem = load_problem_ir(str(problem_path))
        inputs = build_strategy_probe_inputs(problem)
        problem_payload = problem_to_llm_payload(problem)
        handles = CanonicalHandleRegistry.from_problem_payload(problem_payload)
        draft = StepIntentValidator().validate_json(
            step_intents_path.read_text(encoding="utf-8"),
            question_goals=inputs.question_goals,
            handle_registry=handles,
            family_spec=inputs.family_spec,
        )
        _output, diagnostic, effective = RecipeTrialExecutor().diagnose(
            draft,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=handles,
            context=ContextBuilder().build(problem),
            question_goals=inputs.question_goals,
        )

        assert diagnostic.ok, diagnostic.to_payload()
        issues = AnswerGoalVerifier().verify(
            effective,
            problem_payload=problem_payload,
            handle_registry=handles,
            diagnostic=diagnostic,
            family_spec=inputs.family_spec,
        )
        assert issues == (), [item.to_payload() for item in issues]


def test_quadratic_constraint_analyzer_declarations_are_consistent() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
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

    invalid = analyze_quadratic_constraints(
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

    assert invalid.status == "determined"
    assert invalid.free_parameters == ()
    assert valid.status == "single_free"
    assert valid.free_parameters == (b,)


def test_curve_point_parameter_function_declares_state_transitions() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    function = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).require("parameter_from_curve_point_on_quadratic")
    returns = {item.output_key: item for item in function.returns}

    assert returns["parameter_value"].write_mode == "value"
    assert returns["point"].write_mode == "transition"
    assert returns["parabola"].write_mode == "transition"


def test_expression_evaluation_preserves_same_parabola_as_transition() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
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
    step = StepIntent(
        scope_id="ii_1",
        step_id="specialize_curve",
        recipe_hint="evaluate_expression_at_parameter",
        goal_type="derive_parabola",
        target="answer:ii_1.parabola",
        strategy="substitute one known parameter",
        reads=("point:ii:M",),
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
    problem = load_problem_ir(str(RECORDED_FIXTURES[-1][0]))
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
    problem = load_problem_ir(str(RECORDED_FIXTURES[-1][0]))
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


def test_state_dependency_graph_drops_only_unreachable_pure_function_step() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    unused = StepIntent(
        step_id="derive_unused_curve",
        scope_id="ii_1",
        recipe_hint="quadratic_from_constraints",
        goal_type="derive_parabola",
        target="fact:ii:unused_curve",
        strategy="derive an unused intermediate curve",
        reads=("function:problem:parabola",),
        produces=(
            ProducedFact(
                "fact:ii:unused_curve",
                "ii",
                output_type="Parabola",
            ),
        ),
    )
    terminal = StepIntent(
        step_id="produce_terminal_state",
        scope_id="ii_1",
        recipe_hint=None,
        goal_type="derive_parameter",
        target="answer:ii_1.parabola",
        strategy="produce the externally observable state",
        reads=("function:problem:parabola",),
        produces=(
            ProducedFact(
                "answer:ii_1.parabola",
                "ii_1",
                output_type="Parabola",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="subquestion",
                steps=(unused, terminal),
            ),
        ),
    )

    pruned, actions = drop_dead_pure_function_steps(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
    )

    assert [step.step_id for step in pruned.steps] == ["produce_terminal_state"]
    assert [action.action for action in actions] == [
        "drop_dead_pure_function_step"
    ]


def test_state_dependency_graph_keeps_explicitly_non_pure_function_step() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[0][0]))
    inputs = build_strategy_probe_inputs(problem)
    method_id = "quadratic_from_constraints"
    method_specs = MethodSpecRegistry(
        {
            **inputs.method_specs.specs,
            method_id: replace(
                inputs.method_specs.require(method_id),
                is_pure=False,
            ),
        }
    )
    side_effecting = StepIntent(
        step_id="record_external_state",
        scope_id="ii_1",
        recipe_hint=method_id,
        goal_type="derive_parabola",
        target="fact:ii:external_state",
        strategy="record state with an explicitly non-pure function",
        reads=("function:problem:parabola",),
        produces=(
            ProducedFact(
                "fact:ii:external_state",
                "ii",
                output_type="Parabola",
            ),
        ),
    )
    terminal = replace(
        side_effecting,
        step_id="produce_terminal_state",
        recipe_hint=None,
        target="answer:ii_1.parabola",
        produces=(
            ProducedFact(
                "answer:ii_1.parabola",
                "ii_1",
                output_type="Parabola",
            ),
        ),
    )
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                scope_id="ii_1",
                label="subquestion",
                steps=(side_effecting, terminal),
            ),
        ),
    )

    pruned, actions = drop_dead_pure_function_steps(
        draft,
        family_spec=inputs.family_spec,
        method_specs=method_specs,
    )

    assert pruned == draft
    assert actions == ()


def test_generic_function_method_ids_are_derived_from_binding_rules() -> None:
    assert GENERIC_FUNCTION_METHOD_IDS == tuple(
        rule.method_id for rule in GENERIC_FUNCTION_BINDING_RULES
    )


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


def test_migrated_function_specs_have_no_required_contract_return_mismatch() -> None:
    for problem_path, _step_intents_path in RECORDED_FIXTURES:
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
    step = StepIntent(
        step_id="compute_distance",
        scope_id="problem",
        goal_type="derive_minimum_value",
        target="fact:problem:distance",
        strategy="compute a distance",
        reason="exercise migrated function adapter failure",
        recipe_hint="distance_between_points",
        reads=(),
        creates=(),
        produces=(
            ProducedFact(
                "fact:problem:distance",
                "problem",
                output_type="MinimumExpression",
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


def test_recorded_fixtures_compile_generic_methods_without_function_failures() -> None:
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
        assert_no_function_adapter_failures(diagnostic.function_binding_events)


def test_function_adapter_does_not_bind_unread_visible_expression() -> None:
    """A globally visible state cannot satisfy a Function slot_read implicitly."""
    problem_path, step_intents_path = RECORDED_FIXTURES[4]
    problem = load_problem_ir(str(problem_path))
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    draft = StepIntentValidator().validate_json(
        step_intents_path.read_text(encoding="utf-8"),
        question_goals=inputs.question_goals,
        handle_registry=handle_registry,
        family_spec=inputs.family_spec,
    )
    draft = StepIntentDraft(
        scopes=tuple(
            replace(
                scope,
                steps=tuple(
                    replace(
                        step,
                        reads=tuple(
                            handle
                            for handle in step.reads
                            if "path_minimum_expression" not in handle
                        ),
                    )
                    if step.step_id == "derive_parameter_c"
                    else step
                    for step in scope.steps
                ),
            )
            for scope in draft.scopes
        )
    )

    _output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=handle_registry,
        context=ContextBuilder().build(problem),
        question_goals=inputs.question_goals,
    )

    assert not diagnostic.ok
    assert diagnostic.first_blocker is not None
    assert diagnostic.first_blocker.step_id == "derive_parameter_c"
    assert diagnostic.first_blocker.code == "function.arg_not_read"


def test_repair_guidance_only_returns_unique_applicable_contract_candidate() -> None:
    problem = load_problem_ir(str(RECORDED_FIXTURES[4][0]))
    inputs = build_strategy_probe_inputs(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    point_handle = "fact:ii:moving_coordinate"
    producer = StepIntent(
        step_id="produce_moving_point",
        scope_id="ii",
        recipe_hint=None,
        goal_type="derive_point",
        target=point_handle,
        strategy="produce a moving point",
        produces=(ProducedFact(point_handle, "ii", output_type="Point"),),
    )
    repair = StepIntent(
        step_id="repair_missing_state",
        scope_id="ii",
        recipe_hint=None,
        goal_type="derive_state",
        target="fact:ii:missing_state",
        strategy="repair one missing state",
        reads=(point_handle,),
        produces=(
            ProducedFact("fact:ii:missing_state", "ii", output_type="Line"),
        ),
    )
    draft = StepIntentDraft(
        scopes=(StepIntentScope("ii", "question", (producer, repair)),)
    )
    resolver = RepairGuidanceResolver(
        inputs.family_spec,
        inputs.method_specs,
        registry,
    )

    line = resolver.resolve(
        missing_runtime_type="Line",
        step=repair,
        draft=draft,
    )
    point = resolver.resolve(
        missing_runtime_type="Point",
        step=repair,
        draft=draft,
    )

    assert line is not None
    assert line.capability_id == "parameterized_point_locus_line"
    assert point is None


def _diagnostic_payload(value: Any) -> dict[str, Any]:
    return value.to_payload() if hasattr(value, "to_payload") else dict(value)
