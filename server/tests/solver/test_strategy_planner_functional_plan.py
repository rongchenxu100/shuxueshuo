from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import TypedValue
from shuxueshuo_server.solver.explanation.builder import ExplanationBuilder
from shuxueshuo_server.solver.family.models import RecipeExecutionSpec
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.explanation.presentation import (
    StudentNarrativePlacementProjector,
)
from shuxueshuo_server.solver.runtime import strategy_replay as strategy_replay_module
from shuxueshuo_server.solver.runtime import (
    functional_plan_reconciliation as functional_reconciliation_module,
)
from shuxueshuo_server.solver.runtime import (
    functional_call_placement as functional_call_placement_module,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.canonical_draft_finalizer import (
    CanonicalDraftFinalizer,
)
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan import (
    FUNCTIONAL_PLAN_JSON_SCHEMA,
    FunctionalCapabilityCatalog,
    FunctionalPlanReconciler,
    FunctionalPlanValidator,
    prepare_functional_plan_raw_response,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalPlanElaborator,
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalResultFormEvent,
    FunctionalReturnAllocation,
    FunctionalScope,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    _projected_creates,
)
from shuxueshuo_server.solver.runtime.functional_result_forms import (
    canonicalize_verified_result_forms,
    verify_functional_input_closures,
    verify_functional_result_forms,
)
from shuxueshuo_server.solver.runtime.functional_state_refinement import (
    refine_functional_object_states,
)
from shuxueshuo_server.solver.runtime.functional_symbol_flow import (
    infer_unique_target_symbol_ref,
)
from shuxueshuo_server.solver.runtime.functional_reconciliation_validators import (
    functional_reconciliation_issues,
)
from shuxueshuo_server.solver.runtime.function_specs import FunctionSpecRegistry
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContextBuilder,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    RecipeTrialExecutor,
    _validate_student_single_degree_of_freedom,
    _projected_recipe_method_arg_bindings,
    _validate_runtime_lineage_payload,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
    PlannerRetryReplayService,
    repair_attempt_payload_from_replay,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import StrategyPlanner
from shuxueshuo_server.solver.runtime.scalar_result_closure import (
    ScalarResultClosureRegistry,
    close_scalar_plan_output,
)
from shuxueshuo_server.solver.runtime.student_symbolic_complexity import (
    analyze_student_symbolic_complexity,
)
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    PlannerRetryState,
    ProducedFact,
    ProjectedFunctionArgBinding,
    ProjectedStateWrite,
    SemanticRef,
    StateWriteProvenance,
    StepIntent,
    StepIntentDraft,
    StepIntentExecutionDiagnostic,
    StepIntentScope,
    StepIntentValidationReport,
    StrategyDraftValidationError,
)
from shuxueshuo_server.solver.runtime.strategy_validator import StepIntentValidator
from shuxueshuo_server.solver.state_semantics import (
    StateObjectRoleBinding,
    derived_role_object_ref,
    state_semantic_lineage,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
NANKAI_FIXTURE = (
    REPO_ROOT / "internal" / "solver-fixtures" / "tj-2026-nankai-yimo-25.json"
)
HEPING_FIXTURE = (
    REPO_ROOT / "internal" / "solver-fixtures" / "tj-2026-heping-yimo-25.json"
)
HEPING_ERMO_FIXTURE = (
    REPO_ROOT / "internal" / "solver-fixtures" / "tj-2026-heping-ermo-25.json"
)
HEPING_ERMO_FUNCTIONAL_PLAN = (
    REPO_ROOT
    / "internal"
    / "functional-plan-fixtures"
    / "tj-2026-heping-ermo-25.functional-plan.json"
)
XIQING_FIXTURE = (
    REPO_ROOT / "internal" / "solver-fixtures" / "tj-2026-xiqing-yimo-25.json"
)
XIQING_FUNCTIONAL_PLAN = (
    REPO_ROOT
    / "internal"
    / "functional-plan-fixtures"
    / "tj-2026-xiqing-yimo-25.functional-plan.json"
)
HEXI_FIXTURE = (
    REPO_ROOT / "internal" / "solver-fixtures" / "tj-2026-hexi-yimo-25.json"
)
HEXI_FUNCTIONAL_PLAN = (
    REPO_ROOT
    / "internal"
    / "functional-plan-fixtures"
    / "tj-2026-hexi-yimo-25.functional-plan.json"
)
CANONICAL_REF_RE = re.compile(
    r"\b(?:point|line|segment|ray|function|symbol|angle|circle|polygon|fact|answer):"
)
NANKAI_FUNCTIONAL_PLAN = (
    REPO_ROOT
    / "internal"
    / "functional-plan-fixtures"
    / "tj-2026-nankai-yimo-25.functional-plan.json"
)


def _problem():
    return load_problem_ir(NANKAI_FIXTURE)


def _base_inputs():
    return build_strategy_probe_inputs(_problem())


def _inputs_for_goal(goal_index: int):
    inputs = _base_inputs()
    return replace(inputs, question_goals=[inputs.question_goals[goal_index]])


def test_projected_creates_derive_entity_kind_from_object_identity() -> None:
    allocation = FunctionalReturnAllocation(
        call_id="construct_line",
        return_name="locus",
        handle="fact:part:constructed_locus",
        runtime_type="Line",
        valid_scope="part",
        state_slot_id="line:part:locus.locus@part",
        object_ref="line:part:locus",
        identity_policy="derived_role",
        write_mode="create",
    )
    target = ResolvedFunctionalValue(
        handle="ray:part:target_ray",
        runtime_type="RayRef",
        valid_scope="part",
        object_ref="ray:part:target_ray",
    )

    creates = _projected_creates(
        (allocation,),
        resolved_args={"target": (target,)},
        known_handles=set(),
        capability_id="synthetic_object_construction",
    )

    assert [(item.handle, item.entity_type) for item in creates] == [
        ("ray:part:target_ray", "ray"),
        ("line:part:locus", "line"),
    ]


def _problem_payload() -> dict:
    return problem_to_llm_payload(_problem())


def _registry() -> CanonicalHandleRegistry:
    return CanonicalHandleRegistry.from_problem_payload(_problem_payload())


def _context(inputs):
    return initial_planner_state_context(
        inputs,
        problem_payload=_problem_payload(),
        handle_registry=_registry(),
    )


def _heping_ermo_case():
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(
        HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8")
    )
    return inputs, payload, registry, context


def _xiqing_case():
    problem = load_problem_ir(XIQING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(XIQING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    return problem, inputs, problem_payload, registry, context, payload


def _hexi_case():
    problem = load_problem_ir(HEXI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEXI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    return inputs, registry, context, payload


def test_functional_wire_fills_empty_explanation_field_deterministically() -> None:
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "part",
                "calls": [
                    {
                        "call_id": "evaluate_state",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {},
                        "return_bindings": {},
                        "strategy": "",
                        "reason": "Substitute the verified parameter value.",
                    }
                ],
            }
        ],
    }

    plan, report = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=_base_inputs().question_goals,
    )

    assert report.ok and plan is not None
    assert plan.calls[0].strategy == plan.calls[0].reason
    assert report.deterministic_repairs == (
        {
            "call_id": "evaluate_state",
            "action": "fill_missing_call_text",
            "from": "strategy=empty",
            "to": "strategy=reason",
        },
    )


def test_functional_wire_drops_null_arguments_deterministically() -> None:
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "part",
                "calls": [
                    {
                        "call_id": "derive_curve",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "known_point": None,
                            "known_coefficients": [
                                None,
                                {"ref": "coefficient_relation", "kind": "fact"},
                            ],
                        },
                        "return_bindings": {},
                        "strategy": "determine the curve",
                        "reason": "exercise null wire normalization",
                    }
                ],
            }
        ],
    }

    plan, report = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=_base_inputs().question_goals,
    )

    assert report.ok and plan is not None
    assert "known_point" not in plan.calls[0].args
    assert len(plan.calls[0].args["known_coefficients"]) == 1
    assert [item["action"] for item in report.deterministic_repairs] == [
        "drop_null_functional_arg",
        "drop_null_functional_arg",
    ]


def test_functional_wire_normalizes_unique_generic_entity_kind() -> None:
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "consume_point",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {"point": {"ref": "M", "kind": "entity"}},
                        "return_bindings": {},
                        "strategy": "consume the existing point state",
                        "reason": "exercise exact entity-kind normalization",
                    }
                ],
            }
        ],
    }

    plan, report = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=_base_inputs().question_goals,
    )

    assert report.ok and plan is not None
    point_ref = plan.calls[0].args["point"][0]
    assert isinstance(point_ref, SemanticRef)
    assert point_ref.kind == "point"
    assert {
        "call_id": "consume_point",
        "action": "normalize_unique_entity_kind",
        "from": "entity:M",
        "to": "point:M",
    } in report.deterministic_repairs


def test_target_symbol_inference_uses_state_dependency_asymmetry() -> None:
    coefficient = "symbol:problem:coefficient"
    contextual = "symbol:problem:context"
    args = {
        "curve": (
            ResolvedFunctionalValue(
                handle="fact:part:curve_state",
                runtime_type="Parabola",
                valid_scope="part",
                free_symbol_refs=(coefficient, contextual),
            ),
        ),
        "point": (
            ResolvedFunctionalValue(
                handle="fact:part:point_state",
                runtime_type="Point",
                valid_scope="part",
                free_symbol_refs=(contextual,),
            ),
        ),
    }

    assert infer_unique_target_symbol_ref(
        args,
        (coefficient, contextual),
    ) == coefficient


def test_recipe_input_aliases_preserve_macro_argument_identity() -> None:
    execution = RecipeExecutionSpec(
        recipe_id="synthetic_distance_macro",
        method_sequence=("distance_between_points",),
        input_aliases=(
            ("first_endpoint", "distance_between_points.p1"),
            ("second_endpoint", "distance_between_points.p2"),
        ),
    )
    bindings = (
        ProjectedFunctionArgBinding(
            step_id="distance_call",
            arg_name="first_endpoint",
            source_handle="fact:part:first_state",
            runtime_type="Point",
        ),
        ProjectedFunctionArgBinding(
            step_id="distance_call",
            arg_name="second_endpoint",
            source_handle="fact:part:second_state",
            runtime_type="Point",
        ),
    )

    projected = _projected_recipe_method_arg_bindings(
        execution,
        step_id="distance_call",
        method_id="distance_between_points",
        projected_bindings=bindings,
    )

    assert projected["p1"].source_handle == "fact:part:first_state"
    assert projected["p2"].source_handle == "fact:part:second_state"


def test_straightened_distance_recipe_compiles_reconciled_endpoints() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii_2")
    solve_index = next(
        index
        for index, call in enumerate(scope["calls"])
        if call["call_id"] == "ii_2_solve_m"
    )
    scope["calls"].insert(
        solve_index,
        {
            "call_id": "distance_of_selected_endpoints",
            "capability_id": "path_minimum_by_straightened_distance",
            "args": {
                "endpoint_1": {
                    "from_call": "ii_derive_path_model",
                    "return": "path_minimum_point_1",
                },
                "endpoint_2": {
                    "from_call": "ii_derive_path_model",
                    "return": "path_minimum_point_2",
                },
            },
            "return_bindings": {},
            "return_expectations": {
                "path_minimum_expression": "open_expression"
            },
            "strategy": "Measure the selected straightening endpoints.",
            "reason": "The selected endpoints define the reduced path length.",
        },
    )
    solve_call = next(
        call for call in scope["calls"] if call["call_id"] == "ii_2_solve_m"
    )
    solve_call["args"]["minimum_expression"] = {
        "from_call": "distance_of_selected_endpoints",
        "return": "path_minimum_expression",
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
        validation_report=validation,
    )

    assert replay.output is not None, replay.errors
    invocation = next(
        invocation
        for step_plan in replay.output.step_plans
        if step_plan.step_id == "distance_of_selected_endpoints"
        for invocation in step_plan.invocations
        if invocation.method_id == "distance_between_points"
    )
    assert "ii_derive_path_model" in invocation.inputs["p1"]
    assert "ii_derive_path_model" in invocation.inputs["p2"]
    assert invocation.inputs["p1"] != "$problem.points.D"
    assert invocation.inputs["p2"] != "$question.ii.points.M"


def test_direct_distance_aliases_preserve_path_minimum_lineage() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii_2")
    solve_index = next(
        index
        for index, call in enumerate(scope["calls"])
        if call["call_id"] == "ii_2_solve_m"
    )
    scope["calls"].insert(
        solve_index,
        {
            "call_id": "distance_of_selected_endpoints",
            "capability_id": "distance_between_points",
            "args": {
                "endpoint_1": {
                    "from_call": "ii_derive_path_model",
                    "return": "path_minimum_point_1",
                },
                "endpoint_2": {
                    "from_call": "ii_derive_path_model",
                    "return": "path_minimum_point_2",
                },
            },
            "return_bindings": {},
            "return_expectations": {"distance": "open_expression"},
            "strategy": "Measure the two proven straightening endpoints.",
            "reason": "Their distance is the reduced path minimum.",
        },
    )
    solve_call = next(
        call for call in scope["calls"] if call["call_id"] == "ii_2_solve_m"
    )
    solve_call["args"]["minimum_expression"] = {
        "from_call": "distance_of_selected_endpoints",
        "return": "distance",
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    call = next(
        item
        for item in result.calls
        if item.call_id == "distance_of_selected_endpoints"
    )
    assert set(call.resolved_args) >= {"p1", "p2"}
    assert "path_minimum_expression" in call.returns[0].lineage.semantic_roles
    assert "path_minimum_expression" in call.returns[0].lineage.evidence_tags
    assert any(
        item["action"] == "normalize_arg_role"
        and item["call_id"] == "distance_of_selected_endpoints"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_point_list_return_cannot_bind_singular_point_object() -> None:
    inputs, registry, context, payload = _hexi_case()
    candidate_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_right_angle_candidates_ii"
    )
    candidate_call["return_bindings"] = {
        "candidates": {"ref": "D", "kind": "point"}
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert "functional.return_cardinality_mismatch" in {
        item.code for item in result.issues
    }
    report = next(
        item
        for item in result.call_reports
        if item.call_id == "derive_right_angle_candidates_ii"
    )
    assert report.status == "invalid"


def test_free_parameter_basis_follows_unique_downstream_symbol_constraint() -> None:
    inputs, registry, context, payload = _hexi_case()
    producer = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    producer["args"].pop("free_parameters")
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    repaired = next(
        call
        for call in result.plan.calls
        if call.call_id == "derive_parametric_parabola_ii"
    )
    assert repaired.args["free_parameters"] == (
        SemanticRef(ref="b", kind="symbol"),
    )
    assert any(
        item["action"]
        == "align_free_parameter_basis_with_downstream_constraint"
        and item["call_id"] == "derive_parametric_parabola_ii"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_unified_quadratic_constraint_call_publishes_open_target_symbol() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8")
    )
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    call["args"]["target_parameter"] = {"kind": "symbol", "ref": "b"}
    call["return_bindings"]["parameter_value"] = {
        "kind": "symbol",
        "ref": "b",
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=handle_registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
        ),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=handle_registry,
        question_goals=inputs.question_goals,
    )

    assert reconciliation.ok, [item.to_payload() for item in reconciliation.issues]
    refined = next(
        call
        for call in reconciliation.calls
        if call.call_id == "derive_parametric_parabola_ii"
    )
    assert refined.resolved_args["target_parameter"][0].object_ref == (
        "symbol:problem:b"
    )
    parameter_return = next(
        item for item in refined.returns if item.return_name == "parameter_value"
    )
    assert parameter_return.object_ref == "symbol:problem:b"
    assert parameter_return.state_slot_id == "symbol:problem:b.value@ii"
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    sidecar = strategy_replay_module._functional_projected_arg_bindings(
        reconciliation,
        catalog=catalog,
    )
    matching_sidecar = [
        item
        for item in sidecar
        if item.step_id == "derive_parametric_parabola_ii"
        and item.arg_name in {"free_parameters", "target_parameter"}
    ]
    assert {(item.arg_name, item.source_handle) for item in matching_sidecar} == {
        ("free_parameters", "symbol:problem:c"),
        ("target_parameter", "symbol:problem:b"),
    }
    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=handle_registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )
    assert replay.output is not None, replay.errors
    parameter_write = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.step_id == "derive_parametric_parabola_ii"
        and item.output_key == "parameter_value"
    )
    assert parameter_write.object_ref == "symbol:problem:b"
    assert parameter_write.free_symbol_names == ("c",)
    parabola_write = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.step_id == "derive_parametric_parabola_ii"
        and item.output_key == "parabola"
    )
    assert parabola_write.closure_ignored_symbol_names == ("x",)
    assert parabola_write.free_symbol_names == ("c",)
    assert replay.planner_state_context is not None
    parameter_slot = next(
        item
        for item in replay.planner_state_context.state.state_slots
        if item.object_ref == "symbol:problem:b"
        and item.runtime_type == "ParameterValue"
        and item.produced_by == "derive_parametric_parabola_ii"
    )
    assert parameter_slot.free_symbol_refs == ("symbol:problem:c",)
    assert parameter_slot.source_state_slot_ids


def test_problem_symbol_value_has_scalar_and_aggregate_runtime_views() -> None:
    problem, inputs, _payload, registry, _context, _plan = _xiqing_case()
    runtime_context = ContextBuilder().build(problem)
    index = CanonicalRuntimeBindingIndex.from_context(
        runtime_context,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    scalar_path = index.path_for(
        "fact:i:b_value",
        expected_type="ParameterValue",
    )
    scalar = runtime_context.read_path(
        scalar_path,
        from_scope_id="i",
        expected_type="ParameterValue",
    )
    aggregate = runtime_context.read_path(
        "$question.i.coefficients.known",
        from_scope_id="i",
        expected_type="Coefficients",
    )

    assert scalar.value == 4
    assert next(
        value for symbol, value in aggregate.value.items() if str(symbol) == "b"
    ) == 4


def test_functional_replay_accepts_scalar_symbol_value_for_parabola_evaluation() -> None:
    problem, inputs, problem_payload, registry, _context, payload = _xiqing_case()
    first_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "i"
    )
    first_scope["calls"] = [
        {
            "call_id": "build_open_parabola_i",
            "capability_id": "quadratic_from_constraints",
            "args": {
                "curve_point": {"kind": "point", "ref": "A"},
                "free_parameters": {"kind": "symbol", "ref": "b"},
            },
            "return_bindings": {},
            "return_expectations": {"parabola": "open_state"},
            "strategy": "建立保留一个系数的抛物线状态",
            "reason": "后续代入题面给出的系数值",
        },
        {
            "call_id": "evaluate_parabola_i",
            "capability_id": "evaluate_expression_at_parameter",
            "args": {
                "expression": {
                    "from_call": "build_open_parabola_i",
                    "return": "parabola",
                },
                "parameter_value": {"kind": "fact", "ref": "b_value"},
            },
            "return_bindings": {},
            "return_expectations": {"evaluated_parabola": "closed_state"},
            "strategy": "代入已知系数",
            "reason": "得到闭合抛物线",
        },
        {
            "call_id": "derive_vertex_i",
            "capability_id": "quadratic_vertex_point",
            "args": {
                "parabola": {
                    "from_call": "evaluate_parabola_i",
                    "return": "evaluated_parabola",
                }
            },
            "return_bindings": {
                "point": {"kind": "answer", "ref": "i_P"}
            },
            "strategy": "求顶点",
            "reason": "回答第一问",
        },
    ]
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is not None, (
        replay.errors,
        replay.diagnostic.to_payload() if replay.diagnostic is not None else None,
    )
    assert replay.diagnostic is not None and replay.diagnostic.ok
    evaluation = next(
        invocation
        for step in replay.output.step_plans
        if step.step_id == "evaluate_parabola_i"
        for invocation in step.invocations
        if invocation.method_id == "evaluate_expression_at_parameter"
    )
    assert "parameter_values.b" in evaluation.inputs["parameter_value"]


def test_explicit_target_parameter_is_not_reinferred_as_free_parameter() -> None:
    problem, inputs, problem_payload, registry, context, payload = _xiqing_case()
    scope = next(
        item for item in payload["scopes"] if item["scope_id"] == "i"
    )
    solve = next(
        call
        for call in scope["calls"]
        if call["call_id"] == "derive_parabola_i"
    )
    solve["args"]["target_parameter"] = {"kind": "symbol", "ref": "b"}
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert reconciliation.ok, [item.to_payload() for item in reconciliation.issues]
    semantic_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)
    sidecar = strategy_replay_module._functional_projected_arg_bindings(
        reconciliation,
        catalog=catalog,
    )
    selected = {
        item.arg_name: item.source_handle
        for item in sidecar
        if item.step_id == "derive_parabola_i"
    }
    assert selected["curve_point"] == "fact:problem:A_coordinate_value"
    assert selected["target_parameter"] == "symbol:problem:b"

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is not None, (
        replay.errors,
        replay.diagnostic.to_payload() if replay.diagnostic is not None else None,
    )
    invocation = next(
        invocation
        for step in replay.output.step_plans
        if step.step_id == "derive_parabola_i"
        for invocation in step.invocations
        if invocation.method_id == "quadratic_from_constraints"
    )
    assert "target_parameter" in invocation.inputs
    assert "free_parameter" not in invocation.inputs
    assert "free_parameters" not in invocation.inputs


def test_constraint_analyzer_writes_normalized_free_basis_back_to_plan() -> None:
    inputs, payload, registry, _context_value = _heping_ermo_case()
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    call["args"]["free_parameters"] = [
        {"kind": "symbol", "ref": "b"},
        {"kind": "symbol", "ref": "c"},
    ]
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(load_problem_ir(HEPING_ERMO_FIXTURE)),
        attempt=1,
        problem_payload=problem_to_llm_payload(
            load_problem_ir(HEPING_ERMO_FIXTURE)
        ),
        validation_report=validation,
    )

    assert replay.output is not None, replay.errors
    assert replay.functional_plan is not None
    normalized = next(
        item
        for item in replay.functional_plan.calls
        if item.call_id == "derive_parametric_parabola_ii"
    )
    binding_event = next(
        item
        for item in replay.diagnostic.function_binding_events
        if item.step_id == "derive_parametric_parabola_ii"
    )
    assert binding_event.arg_repairs, binding_event
    assert "free_parameters" not in normalized.args
    assert binding_event.arg_repairs[0].source_handles == ()
    assert replay.functional_reconciliation is not None
    assert any(
        item["action"] == "normalize_constraint_free_parameter_basis"
        and item["call_id"] == "derive_parametric_parabola_ii"
        for item in replay.functional_reconciliation.elaboration[
            "deterministic_repairs"
        ]
    )


def test_unified_quadratic_constraint_rejects_target_in_free_basis() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    handle_registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8")
    )
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    call["args"]["free_parameters"] = {"kind": "symbol", "ref": "b"}
    call["args"]["target_parameter"] = {"kind": "symbol", "ref": "b"}
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=handle_registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=handle_registry,
        ),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=handle_registry,
        question_goals=inputs.question_goals,
    )

    assert not reconciliation.ok
    assert any(
        item.code == "functional.arg_distinctness_violation"
        and item.call_id == "derive_parametric_parabola_ii"
        for item in reconciliation.issues
    )


def _axis_plan_payload(*, strategy: str = "use the coefficient relation") -> dict:
    return {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "derive_axis_point",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                                "value_type": "coefficient_relation",
                            }
                        },
                        "return_bindings": {
                            "axis_point": {
                                "ref": "i.axis_point",
                                "kind": "answer",
                                "value_type": "Point",
                            }
                        },
                        "strategy": strategy,
                        "reason": "determine the symmetry-axis point",
                    }
                ],
            }
        ],
    }


def _path_reduction_call(call_id: str = "reduce_path") -> dict:
    return {
        "call_id": call_id,
        "capability_id": "two_moving_points_path_reduction",
        "args": {
            "path_minimum_target": {
                "ref": "path_minimum_target",
                "kind": "fact",
            }
        },
        "return_bindings": {},
        "strategy": "reduce the path to a single moving-point state",
        "reason": "produce the path transformation consumed downstream",
    }


def _path_transformation_ref(call_id: str = "reduce_path") -> dict:
    return {
        "from_call": call_id,
        "return": "path_transformation",
    }


def _path_reduction_prerequisite_calls(
    prefix: str = "path_setup",
) -> tuple[dict, dict]:
    return (
        {
            "call_id": f"{prefix}_derive_axis",
            "capability_id": "quadratic_axis_from_relation",
            "args": {
                "coefficient_relation": {
                    "ref": "coefficient_relation",
                    "kind": "fact",
                }
            },
            "return_bindings": {},
            "strategy": "derive the fixed axis point",
            "reason": "materialize a fixed point required by path reduction",
        },
        {
            "call_id": f"{prefix}_construct_target",
            "capability_id": "right_angle_equal_length_construct_and_select",
            "args": {
                "right_angle_equal_length": {
                    "ref": "right_angle_equal_length_MDN",
                    "kind": "fact",
                }
            },
            "return_bindings": {},
            "strategy": "construct the second track endpoint",
            "reason": "materialize the point state required by path reduction",
        },
    )


def _path_reduction_setup_calls(
    call_id: str = "reduce_path",
) -> tuple[dict, dict, dict]:
    return (
        *_path_reduction_prerequisite_calls(call_id),
        _path_reduction_call(call_id),
    )


def _validate(payload: dict, inputs):
    return FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )


def test_functional_schema_and_catalog_are_prompt_safe() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    assert json.loads(json.dumps(FUNCTIONAL_PLAN_JSON_SCHEMA))
    assert FUNCTIONAL_PLAN_JSON_SCHEMA["description"] == (
        "用 capability 调用图表示的完整数学解法。"
    )
    schema_call = FUNCTIONAL_PLAN_JSON_SCHEMA["properties"]["scopes"][
        "items"
    ]["properties"]["calls"]["items"]
    assert "goal_type" not in schema_call["properties"]
    assert "goal_type" not in schema_call["required"]
    assert "capability catalog" in schema_call["properties"]["args"][
        "description"
    ]
    assert "普通中间结果" in schema_call["properties"]["return_bindings"][
        "description"
    ]
    assert "return_expectations" in schema_call["properties"]
    assert "return_expectations" not in schema_call["required"]
    assert catalog.get("quadratic_axis_from_relation") is not None
    prompt_payload = catalog.to_prompt_payload()
    capabilities = prompt_payload["capabilities"]
    assert capabilities
    assert all(
        {"capability_id", "title", "use_when", "args", "returns"}
        <= set(item)
        <= {
            "capability_id",
            "title",
            "use_when",
            "do_not_use_when",
            "args",
            "returns",
            "input_requirements",
        }
        for item in capabilities
    )
    assert all(item["use_when"].strip() for item in capabilities)
    assert all("description" not in item for item in capabilities)
    for item in capabilities:
        guidance = item.get("do_not_use_when", [])
        assert all(value.strip() for value in guidance)
        assert len(guidance) == len(set(guidance))
    path_macro = catalog.get("broken_path_straightening_minimum_expression")
    assert path_macro is not None
    assert catalog.get("broken_path_straightening_and_select") is None
    assert {
        "straightened_scheme",
        "straightening_auxiliary_point",
        "path_minimum_point_1",
        "path_minimum_point_2",
        "path_minimum_expression",
        "evaluated_path_minimum_expression",
    } == {item.name for item in path_macro.returns}
    auxiliary = next(
        item
        for item in path_macro.returns
        if item.name == "straightening_auxiliary_point"
    )
    assert auxiliary.equivalent_to == "path_minimum_point_1"
    path_result = next(
        item for item in path_macro.returns
        if item.name == "path_minimum_expression"
    )
    assert path_result.possible_forms == (
        "open_expression",
        "closed_value",
    )
    prompt_result = next(
        item
        for item in path_macro.to_prompt_payload()["returns"]
        if item["name"] == "path_minimum_expression"
    )
    assert prompt_result["possible_forms"] == [
        "open_expression",
        "closed_value",
    ]
    assert "自由参数" in prompt_result["desc"]
    quadratic = catalog.get("quadratic_from_constraints")
    assert quadratic is not None
    quadratic_prompt = quadratic.to_prompt_payload()
    quadratic_args = {
        item["name"]: item for item in quadratic_prompt["args"]
    }
    assert "多个系数统一放在这里" in quadratic_args[
        "known_coefficients"
    ]["desc"]
    assert "单个需要代入" in quadratic_args["parameter_value"]["desc"]
    assert "不等式" in quadratic_args["extra_equation"]["desc"]
    assert "有意保留" in quadratic_args["free_parameters"]["desc"]
    assert any(
        "free_parameters、target_parameter" in item["requirement"]
        and "彼此不同" in item["requirement"]
        for item in quadratic_prompt["input_requirements"]
    )
    parabola_result = next(
        item for item in quadratic.returns if item.name == "parabola"
    )
    assert parabola_result.possible_forms == ("open_state", "closed_state")
    assert "未确定系数或参数" in parabola_result.result_form_description
    axis = next(
        item
        for item in capabilities
        if item["capability_id"] == "quadratic_axis_from_relation"
    )
    assert axis["title"] == "由系数关系求对称轴交点"
    assert "对称轴与 x 轴交点" in axis["use_when"]
    assert "do_not_use_when" not in axis
    assert axis["args"] == [
        {
            "name": "coefficient_relation",
            "accepts": ["Equation"],
            "required": True,
            "cardinality": "one",
        }
    ]
    assert axis["returns"] == [
        {
            "name": "axis_point",
            "type": "Point",
            "binding": "answer_or_existing_object",
            "desc": (
                "坐标仍含未确定符号时为 open_state；不存在自由符号时为 "
                "closed_state。重复写入同一对象时，代码会验证它是否为状态收敛。"
            ),
            "possible_forms": ["open_state", "closed_state"],
        }
    ]
    text = json.dumps(prompt_payload)
    prompt_text = json.dumps(prompt_payload, ensure_ascii=False)
    assert "南开" not in prompt_text
    assert "和平" not in prompt_text
    for internal_field in (
        "runtime_path",
        "binding_selector",
        "goal_type",
        "kind",
        "llm_mode",
        "state_kind",
        "identity_policy",
        "identity_arg",
        "write_mode",
    ):
        assert internal_field not in text
    assert not CANONICAL_REF_RE.search(text)
    prompt_returns = [
        result
        for capability in capabilities
        for result in capability["returns"]
    ]
    assert {result["binding"] for result in prompt_returns} >= {
        "internal_only",
        "answer_or_existing_object",
    }
    straightening = next(
        item
        for item in capabilities
        if item["capability_id"]
        == "broken_path_straightening_minimum_expression"
    )
    straightening_args = {item["name"]: item for item in straightening["args"]}
    assert any(
        "原路径动点或极值点坐标" in item
        for item in straightening["do_not_use_when"]
    )
    assert "路径等价变换" in straightening_args["path_transformation"]["desc"]
    straightening_returns = {
        item["name"]: item for item in straightening["returns"]
    }
    for role in ("path_minimum_point_1", "path_minimum_point_2"):
        assert straightening_returns[role]["binding"] == "internal_only"
        assert "不是原路径上的动点、极值点或答案点" in (
            straightening_returns[role]["desc"]
        )
    assert "最小值表达式" in (
        straightening_returns["path_minimum_expression"]["desc"]
    )
    assert "不能从可见的任意 Line 自动选择" in (
        straightening_args["moving_locus"]["desc"]
    )
    x_intercept = next(
        item
        for item in capabilities
        if item["capability_id"] == "quadratic_x_axis_intercept_point"
    )
    x_intercept_args = {item["name"]: item for item in x_intercept["args"]}
    assert "不能填写当前正在求解的目标点" in (
        x_intercept_args["known_point"]["desc"]
    )
    assert any(
        "目标交点" in item and "known_point" in item
        for item in x_intercept["do_not_use_when"]
    )
    evaluate_point = next(
        item
        for item in capabilities
        if item["capability_id"] == "evaluate_point_at_parameter"
    )
    assert any("不改变对象身份" in item for item in evaluate_point["do_not_use_when"])
    assert any("含参坐标状态" in item.get("desc", "") for item in evaluate_point["args"])
    assert "同一 Point" in evaluate_point["returns"][0]["desc"]


def test_heping_ermo_functional_catalog_explains_stateful_geometry_args() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    capabilities = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).to_prompt_payload()["capabilities"]
    by_id = {item["capability_id"]: item for item in capabilities}

    line_minimum = by_id["line_locus_minimum_point"]
    line_args = {item["name"]: item for item in line_minimum["args"]}
    assert "不能用 Point" in line_args["moving_locus"]["desc"]
    assert "第一个内部端点" in line_args["minimum_point_1"]["desc"]
    assert "第二个内部端点" in line_args["minimum_point_2"]["desc"]
    assert "另一个几何点" in line_minimum["returns"][0]["desc"]
    assert any(
        "本能力只返回路径动点自身" in item
        for item in line_minimum["do_not_use_when"]
    )

    square_vertex = by_id["square_adjacent_vertex_from_side"]
    square_args = {item["name"]: item for item in square_vertex["args"]}
    assert "已经求出坐标" in square_args["side_start"]["desc"]
    assert "不能只填写尚未计算坐标" in square_args["side_end"]["desc"]


def test_functional_return_expectation_rejects_unknown_return() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["return_expectations"] = {
        "missing_return": "closed_value"
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    assert plan.to_payload()["scopes"][0]["calls"][0][
        "return_expectations"
    ] == {"missing_return": "closed_value"}

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert "functional.return_expectation_unknown" in {
        item.code for item in result.issues
    }


def test_reconciler_normalizes_unknown_binding_for_single_return_capability() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["return_bindings"] = {
        "point": call["return_bindings"].pop("axis_point")
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    effective_call = next(
        call for call in result.plan.calls if call.call_id == "derive_axis_point"
    )
    assert set(effective_call.return_bindings) == {"axis_point"}
    assert {
        "call_id": "derive_axis_point",
        "action": "normalize_unique_return_role",
        "from": "point",
        "to": "axis_point",
    } in result.elaboration["deterministic_repairs"]


def test_wrong_result_form_domain_is_dropped_deterministically() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["return_expectations"] = {
        "axis_point": "closed_value"
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert not any(
        item.code == "functional.return_binding_unknown"
        and item.call_id in expected
        for item in result.issues
    ), [item.to_payload() for item in result.issues]
    effective_call = next(
        call for call in result.plan.calls if call.call_id == "derive_axis_point"
    )
    assert effective_call.return_expectations == {}
    assert {
        "call_id": "derive_axis_point",
        "action": "drop_fixed_form_return_expectation",
        "from": "axis_point:closed_value",
        "to": "fixed_result_form",
    } in result.elaboration["deterministic_repairs"]


def test_functional_return_expectation_rejects_invalid_enum() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["return_expectations"] = {
        "axis_point": "symbolic"
    }
    plan, validation = _validate(payload, inputs)
    assert plan is None
    assert "functional.return_expectation_value" in {
        item.code for item in validation.issues
    }


def test_consumed_open_expression_answer_binding_is_dropped_for_closed_producer() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_derive_path_model"
    )
    call["return_bindings"] = {
        "path_minimum_expression": {
            "kind": "answer",
            "ref": "ii_1.minimum_value",
        }
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert result.ok, [item.to_payload() for item in result.issues]
    effective = next(
        item for item in result.plan.calls if item.call_id == "ii_derive_path_model"
    )
    assert "path_minimum_expression" not in effective.return_bindings
    assert effective.return_expectations["path_minimum_expression"] == (
        "open_expression"
    )
    assert effective.return_expectations["path_minimum_point_1"] == "open_state"
    assert effective.return_expectations["path_minimum_point_2"] == "open_state"
    assert {
        "call_id": "ii_derive_path_model",
        "action": "drop_intermediate_open_expression_answer_binding",
        "from": "ii_1.minimum_value",
        "to": "ii_1_evaluate_minimum.evaluated_minimum_expression",
    } in result.elaboration["deterministic_repairs"]


def test_open_expression_answer_binding_without_closed_producer_still_fails() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    source = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_derive_path_model"
    )
    source["return_bindings"] = {
        "path_minimum_expression": {
            "kind": "answer",
            "ref": "ii_1.minimum_value",
        }
    }
    terminal = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_1_evaluate_minimum"
    )
    terminal["return_bindings"] = {}
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert "functional.return_expectation_answer_conflict" in {
        item.code for item in result.issues
    }


def test_consumed_open_point_answer_binding_becomes_existing_object_state() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    calls = {
        call["call_id"]: call
        for scope in payload["scopes"]
        for call in scope["calls"]
    }
    parameterized = calls["parameterize_axis_point_E_ii"]
    parameterized["return_bindings"] = {
        "point": {"kind": "answer", "ref": "ii.E"}
    }
    parameterized["return_expectations"] = {"point": "open_state"}
    final = calls["recover_target_point_E_ii"]
    final["return_expectations"] = {"point": "closed_state"}
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    effective = next(
        call
        for call in result.plan.calls
        if call.call_id == "parameterize_axis_point_E_ii"
    )
    assert effective.return_bindings["point"].ref == "ii.E"
    assert effective.return_bindings["point"].kind == "point"
    assert any(
        item["action"] == "demote_intermediate_open_state_answer_binding"
        and item["call_id"] == "parameterize_axis_point_E_ii"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_closed_result_expectation_blocks_runtime_when_symbols_remain() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_derive_path_model"
    )
    call["return_expectations"] = {
        "path_minimum_expression": "closed_value"
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
        validation_report=validation,
    )

    assert replay.output is None
    assert replay.retry_state is not None
    issue = next(
        item
        for item in replay.retry_state.issues
        if item.code == "functional.return_form_mismatch"
    )
    assert issue.step_id == "ii_derive_path_model"
    assert issue.details is not None
    assert issue.details["actual_form"] == "open_expression"
    assert issue.details["free_symbol_names"]


def test_closed_scalar_projection_reads_unique_prior_parameter_value() -> None:
    inputs = _inputs_for_goal(3)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    *_path_reduction_prerequisite_calls(),
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_segment_length",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {"ref": "N", "kind": "point"},
                            "length_squared": {
                                "ref": "MN_length_squared_eq_10",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "determine the remaining parameter",
                        "reason": "provide a value state for scalar closure",
                    },
                    _path_reduction_call(),
                    {
                        "call_id": "derive_closed_minimum",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                        },
                        "return_bindings": {
                            "path_minimum_expression": {
                                "ref": "ii_1.minimum_value",
                                "kind": "answer",
                            }
                        },
                        "strategy": "derive the closed path minimum",
                        "reason": "consume the uniquely available parameter value",
                    },
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    effective_call = next(
        call
        for call in result.plan.calls
        if call.call_id == "derive_closed_minimum"
    )
    assert effective_call.return_expectations == {
        "path_minimum_expression": "closed_value"
    }
    assert any(
        item["action"] == "infer_closed_answer_result_form"
        and item["call_id"] == "derive_closed_minimum"
        for item in result.elaboration["deterministic_repairs"]
    )
    assert result.projected_draft is not None
    solve = next(
        item for item in result.calls if item.call_id == "solve_parameter"
    )
    parameter_handle = next(
        item.handle
        for item in solve.returns
        if item.runtime_type == "ParameterValue"
    )
    closed_step = next(
        step
        for step in result.projected_draft.steps
        if step.step_id == "derive_closed_minimum"
    )
    assert parameter_handle in closed_step.reads


def test_scalar_closure_function_is_discovered_from_typed_function_signature() -> None:
    inputs = _base_inputs()
    functions = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    registry = ScalarResultClosureRegistry(functions)

    closure = registry.require("MinimumExpression")

    assert closure.runtime_type == "MinimumExpression"
    assert closure.value_input == "expression"
    assert closure.symbol_input == "parameter"
    assert closure.parameter_value_input == "parameter_value"
    assert closure.output_name == "evaluated_minimum_expression"


def test_scalar_closure_appends_read_closed_substitution_before_promotion() -> None:
    inputs = _base_inputs()
    registry = ScalarResultClosureRegistry(
        FunctionSpecRegistry.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        )
    )
    source = "$step.derive_value.temp.minimum_expression"
    target = "$question.ii_1.answers.minimum_value"
    plan = StepPlan(
        step_id="derive_value",
        goal=StepGoal(
            goal_id="derive_minimum_value:derive_value",
            type="derive_minimum_value",
            target_path=target,
            scope_id="ii_1",
        ),
        scope="ii_1",
        invocations=[
            MethodInvocation(
                invocation_id="derive_value.producer",
                method_id="distance_between_points",
                scope="derive_value",
                inputs={
                    "p1": "$question.ii.points.P",
                    "p2": "$question.ii.points.Q",
                },
                outputs={"distance": source},
            )
        ],
        expected_outputs=[target],
        promote_outputs={source: target},
    )

    closed = close_scalar_plan_output(
        plan,
        target_path=target,
        runtime_type="MinimumExpression",
        parameter_pairs=(("$problem.symbols.t", "$question.ii_1.outputs.t_value"),),
        registry=registry,
        return_name="minimum_expression",
    )

    assert [item.method_id for item in closed.invocations] == [
        "distance_between_points",
        "evaluate_expression_at_parameter",
    ]
    closure_invocation = closed.invocations[-1]
    assert closure_invocation.inputs == {
        "expression": source,
        "parameter": "$problem.symbols.t",
        "parameter_value": "$question.ii_1.outputs.t_value",
    }
    assert list(closed.promote_outputs.values()) == [target]
    assert source not in closed.promote_outputs


def test_redundant_incompatible_optional_arg_is_dropped_by_contract_role() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "ii_derive_path_model"
    )
    call["args"]["moving_locus"] = {"kind": "segment", "ref": "MN"}
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    result = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=catalog,
        semantic_index=FunctionalSemanticIndex.from_context(
            _context(inputs),
            handle_registry=_registry(),
        ),
    )

    elaborated = next(
        item for item in result.plan.calls if item.call_id == "ii_derive_path_model"
    )
    assert result.ok
    assert "moving_locus" not in elaborated.args
    assert any(
        item.call_id == elaborated.call_id
        and item.action == "drop_redundant_incompatible_optional_arg"
        for item in result.deterministic_repairs
    )


def test_context_closure_calls_wait_for_resolved_state_versions_before_merge() -> None:
    inputs = _base_inputs()

    def reduction(call_id: str) -> FunctionalCall:
        return FunctionalCall(
            call_id=call_id,
            capability_id="two_moving_points_path_reduction",
            args={
                "path_minimum_target": (
                    SemanticRef(ref="path_minimum_target", kind="fact"),
                )
            },
            return_bindings={},
            strategy="reduce the linked path",
            reason="derive a reusable path transformation",
        )

    plan = FunctionalPlan(
        scopes=(
            FunctionalScope("ii_1", "ii_1", (reduction("reduce_first"),)),
            FunctionalScope("ii_2", "ii_2", (reduction("reduce_second"),)),
        )
    )
    result = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
        semantic_index=FunctionalSemanticIndex.from_context(
            _context(inputs),
            handle_registry=_registry(),
        ),
    )

    assert result.ok
    assert [item.call_id for item in result.plan.calls] == [
        "reduce_first",
        "reduce_second",
    ]
    assert result.call_aliases == {}


@pytest.mark.parametrize(
    ("expectation", "free_symbols", "expected_status", "issue_count"),
    (
        ("closed_value", ("m",), "mismatch", 1),
        ("open_expression", (), "result_form_closed", 0),
        ("closed_value", (), "matched", 0),
    ),
)
def test_runtime_verifies_functional_scalar_result_form_from_free_symbols(
    expectation: str,
    free_symbols: tuple[str, ...],
    expected_status: str,
    issue_count: int,
) -> None:
    call = FunctionalCall(
        call_id="compute_scalar",
        capability_id="distance_between_points",
        args={},
        return_bindings={},
        strategy="compute an exact scalar",
        reason="exercise result form verification",
        return_expectations={
            "distance": expectation,  # type: ignore[dict-item]
        },
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("i", "i", (call,)),),
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="distance",
        handle="fact:i:distance",
        runtime_type="MinimumExpression",
        valid_scope="i",
        state_slot_id="distance.expression@i:MinimumExpression",
        object_ref=None,
        identity_policy="value_only",
        write_mode="value",
    )
    reconciliation = FunctionalPlanReconciliationResult(
        plan=plan,
        calls=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="i",
                capability_id=call.capability_id,
                resolved_args={},
                returns=(allocation,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id=call.call_id,
                scope_id="i",
                capability_id=call.capability_id,
                produced_handle=allocation.handle,
                output_key="distance",
                runtime_type="MinimumExpression",
                identity_policy="value_only",
                identity_role="distance",
                free_symbol_names=free_symbols,
            ),
        ),
    )

    events, issues = verify_functional_result_forms(
        plan,
        reconciliation,
        diagnostic,
    )
    assert len(events) == 1
    assert events[0].status == expected_status
    assert len(issues) == issue_count
    if issues:
        assert issues[0].code == "functional.return_form_mismatch"


def test_runtime_closed_form_updates_canonical_functional_plan() -> None:
    call = FunctionalCall(
        call_id="evaluate_object",
        capability_id="evaluate_point_at_parameter",
        args={},
        return_bindings={},
        strategy="evaluate the remaining parameter",
        reason="exercise canonical runtime form write-back",
        return_expectations={"point": "open_state"},
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (call,)),),
    )
    event = FunctionalResultFormEvent(
        call_id=call.call_id,
        scope_id="part",
        return_name="point",
        expected_form="open_state",
        actual_form="closed_state",
        status="result_form_closed",
    )

    canonical = canonicalize_verified_result_forms(plan, (event,))

    assert canonical.calls[0].return_expectations == {
        "point": "closed_state"
    }


def test_function_template_materialization_uses_independent_free_basis() -> None:
    inputs, _payload, registry, context = _heping_ermo_case()
    semantic_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )
    ref = SemanticRef(ref="parabola", kind="function")

    closed = semantic_index.materialize_function_state(
        ref,
        scope_id="i_1",
        target_runtime_type="Parabola",
        closure_policy="closed_or_single_free",
    )
    underdetermined = semantic_index.materialize_function_state(
        ref,
        scope_id="ii",
        target_runtime_type="Parabola",
        closure_policy="closed_or_single_free",
    )
    c_only = FunctionalSemanticIndex(
        semantic_index.views,
        handle_registry=registry,
        entity_payloads=semantic_index.entity_payloads,
        fact_payloads={
            handle: payload
            for handle, payload in semantic_index.fact_payloads.items()
            if handle == "fact:i:c_value"
        },
    ).materialize_function_state(
        ref,
        scope_id="i_1",
        target_runtime_type="Parabola",
        closure_policy="closed_or_single_free",
    )

    assert closed.status == "determined"
    assert closed.free_symbol_refs == ()
    assert set(closed.supporting_handles) >= {
        "fact:i:b_value",
        "fact:i:c_value",
    }
    assert c_only.status == "single_free"
    assert c_only.free_symbol_refs == ("symbol:problem:b",)
    assert underdetermined.status == "underdetermined"
    assert set(underdetermined.free_symbol_refs) == {
        "symbol:problem:b",
        "symbol:problem:c",
    }


def test_functional_replay_materializes_closed_function_template_for_consumers() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    inputs = replace(
        inputs,
        question_goals=tuple(
            goal for goal in inputs.question_goals if goal.question_id == "i_1"
        ),
    )
    payload["scopes"] = [payload["scopes"][0]]
    for scope in payload["scopes"]:
        scope["calls"] = [
            call
            for call in scope["calls"]
            if call["call_id"] != "derive_parabola_i"
        ]
        for call in scope["calls"]:
            call["args"] = _replace_call_result_with_semantic_ref(
                call["args"],
                from_call="derive_parabola_i",
                replacement={"kind": "function", "ref": "parabola"},
            )
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(load_problem_ir(HEPING_ERMO_FIXTURE)),
        attempt=1,
        problem_payload=problem_to_llm_payload(
            load_problem_ir(HEPING_ERMO_FIXTURE)
        ),
        validation_report=validation,
        planner_state_context=context,
    )

    assert replay.output is not None, replay.errors
    assert replay.functional_reconciliation is not None
    repairs = replay.functional_reconciliation.elaboration[
        "deterministic_repairs"
    ]
    assert any(
        item["action"] == "materialize_function_state"
        for item in repairs
    )


def _replace_call_result_with_semantic_ref(
    value: Any,
    *,
    from_call: str,
    replacement: dict[str, str],
) -> Any:
    if isinstance(value, list):
        return [
            _replace_call_result_with_semantic_ref(
                item,
                from_call=from_call,
                replacement=replacement,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    if value.get("from_call") == from_call:
        return dict(replacement)
    return {
        key: _replace_call_result_with_semantic_ref(
            item,
            from_call=from_call,
            replacement=replacement,
        )
        for key, item in value.items()
    }


def test_functional_catalog_exposes_input_and_output_parameter_budgets() -> None:
    inputs, _payload, _registry_value, _context_value = _heping_ermo_case()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    vertex = catalog.get("quadratic_vertex_point")
    y_intercept = catalog.get("quadratic_y_axis_intercept_point")
    assert vertex is not None and y_intercept is not None

    vertex_arg = next(item for item in vertex.args if item.name == "parabola")
    y_arg = next(item for item in y_intercept.args if item.name == "quadratic")
    y_return = next(item for item in y_intercept.returns if item.name == "point")

    assert vertex_arg.input_closure_policy == "closed_or_single_free"
    assert y_arg.input_closure_policy == "any"
    assert y_return.max_independent_free_parameters == 1
    payload = y_intercept.to_prompt_payload()
    assert payload["returns"][0]["max_independent_free_parameters"] == 1


def test_runtime_enforces_declared_output_parameter_budget_without_expectation() -> None:
    inputs, _payload, _registry_value, _context_value = _heping_ermo_case()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    call = FunctionalCall(
        call_id="derive_intercept",
        capability_id="quadratic_y_axis_intercept_point",
        args={},
        return_bindings={},
        strategy="project the y-axis intercept",
        reason="exercise output parameter budget",
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="point",
        handle="fact:part:intercept",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:C.coordinate@part",
        object_ref="point:part:C",
        identity_policy="target_object",
        write_mode="create",
    )
    reconciliation = FunctionalPlanReconciliationResult(
        plan=FunctionalPlan(
            scopes=(FunctionalScope("part", "part", (call,)),),
        ),
        calls=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="part",
                capability_id=call.capability_id,
                resolved_args={},
                returns=(allocation,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id=call.call_id,
                scope_id="part",
                capability_id=call.capability_id,
                produced_handle=allocation.handle,
                output_key="point",
                runtime_type="Point",
                identity_policy="target_object",
                identity_role="y_axis_intercept",
                free_symbol_names=("p", "q"),
            ),
        ),
    )

    events, issues = verify_functional_result_forms(
        reconciliation.plan,
        reconciliation,
        diagnostic,
        catalog=catalog,
    )

    assert events == ()
    assert [item.code for item in issues] == [
        "functional.return_state_underdetermined"
    ]


def test_runtime_enforces_prior_call_input_closure_after_constraint_analysis() -> None:
    inputs, _payload, _registry_value, _context_value = _heping_ermo_case()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    call = FunctionalCall(
        call_id="derive_vertex",
        capability_id="quadratic_vertex_point",
        args={},
        return_bindings={},
        strategy="read a parameterized curve",
        reason="exercise authoritative input closure",
    )
    source_handle = "fact:part:parametric_parabola"
    reconciliation = FunctionalPlanReconciliationResult(
        plan=FunctionalPlan(
            scopes=(FunctionalScope("part", "part", (call,)),),
        ),
        calls=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="part",
                capability_id=call.capability_id,
                resolved_args={
                    "parabola": (
                        ResolvedFunctionalValue(
                            handle=source_handle,
                            runtime_type="Parabola",
                            valid_scope="part",
                            source_call_id="build_curve",
                            return_name="parabola",
                        ),
                    ),
                },
                returns=(),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id="build_curve",
                scope_id="part",
                capability_id="quadratic_from_constraints",
                produced_handle=source_handle,
                output_key="parabola",
                runtime_type="Parabola",
                identity_policy="target_object",
                identity_role="parabola",
                free_symbol_names=("x", "p", "q"),
                closure_ignored_symbol_names=("x",),
            ),
        ),
    )

    issues = verify_functional_input_closures(
        reconciliation,
        catalog=catalog,
        diagnostic=diagnostic,
    )

    assert [item.code for item in issues] == [
        "functional.arg_state_underdetermined"
    ]
    assert issues[0].details["free_symbol_names"] == ["p", "q"]


def test_object_state_refinement_infers_forms_and_transition() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability_id = "quadratic_axis_x_intercept_point"
    capability = catalog.get(capability_id)
    assert capability is not None
    axis_return = next(item for item in capability.returns if item.name == "axis_point")
    assert axis_return.possible_forms == ("open_state", "closed_state")

    open_call = FunctionalCall(
        call_id="derive_symbolic_state",
        capability_id=capability_id,
        args={},
        return_bindings={},
        strategy="derive an object state containing a free parameter",
        reason="exercise generic object closure",
    )
    closed_call = replace(
        open_call,
        call_id="derive_refined_state",
        strategy="derive the same object after closing the parameter",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (open_call, closed_call)),),
    )
    shared = {
        "return_name": "axis_point",
        "runtime_type": "Point",
        "valid_scope": "part",
        "state_slot_id": "point:part:target.coordinate@part",
        "object_ref": "point:part:target",
        "identity_policy": "target_object",
        "write_mode": "create",
        "source_state_slot_ids": ("function:part:curve.expression@part",),
        "dependency_object_refs": ("function:part:curve",),
    }
    open_allocation = FunctionalReturnAllocation(
        call_id=open_call.call_id,
        handle="fact:part:target_symbolic_coordinate",
        free_symbol_refs=("symbol:part:parameter",),
        **shared,
    )
    closed_shared = {
        **shared,
        "source_state_slot_ids": (
            "function:part:curve.expression@part",
            "point:part:target.coordinate@part",
        ),
    }
    closed_allocation = FunctionalReturnAllocation(
        call_id=closed_call.call_id,
        handle="fact:part:target_closed_coordinate",
        free_symbol_refs=(),
        **closed_shared,
    )
    reconciled = (
        FunctionalCallReconciliation(
            call_id=open_call.call_id,
            scope_id="part",
            capability_id=capability_id,
            resolved_args={},
            returns=(open_allocation,),
        ),
        FunctionalCallReconciliation(
            call_id=closed_call.call_id,
            scope_id="part",
            capability_id=capability_id,
            resolved_args={},
            returns=(closed_allocation,),
        ),
    )

    result = refine_functional_object_states(
        plan,
        reconciled=reconciled,
        catalog=catalog,
    )

    calls = {call.call_id: call for call in result.plan.calls}
    assert calls[open_call.call_id].return_expectations == {
        "axis_point": "open_state"
    }
    assert calls[closed_call.call_id].return_expectations == {}
    refined = result.calls[1].returns[0]
    assert refined.write_mode == "transition"
    assert refined.transition_kind == "dependency_refinement"
    assert refined.previous_write_step_id == open_call.call_id


def test_object_state_refinement_accepts_direct_constraint_transition() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    calls = (
        FunctionalCall(
            call_id="initial_state",
            capability_id="quadratic_from_constraints",
            args={},
            return_bindings={},
            strategy="establish a symbolic object state",
            reason="synthetic state transition",
        ),
        FunctionalCall(
            call_id="append_constraint",
            capability_id="quadratic_from_constraints",
            args={},
            return_bindings={},
            strategy="append a constraint to the same object state",
            reason="synthetic state transition",
        ),
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", calls),),
    )
    slot_id = "function:part:curve.expression@part"
    common = {
        "return_name": "parabola",
        "runtime_type": "Parabola",
        "valid_scope": "part",
        "state_slot_id": slot_id,
        "object_ref": "function:part:curve",
        "identity_policy": "preserve_input_object",
        "write_mode": "value",
        "free_symbol_refs": ("symbol:part:t",),
        "dependency_object_refs": ("function:part:curve",),
    }
    reconciled = (
        FunctionalCallReconciliation(
            call_id="initial_state",
            scope_id="part",
            capability_id="quadratic_from_constraints",
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id="initial_state",
                    handle="fact:part:initial_curve",
                    source_state_slot_ids=("function:part:curve.template@part",),
                    **common,
                ),
            ),
        ),
        FunctionalCallReconciliation(
            call_id="append_constraint",
            scope_id="part",
            capability_id="quadratic_from_constraints",
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id="append_constraint",
                    handle="fact:part:refined_curve",
                    source_state_slot_ids=(
                        slot_id,
                        "point:part:evidence.coordinate@part",
                    ),
                    **common,
                ),
            ),
        ),
    )

    result = refine_functional_object_states(
        plan,
        reconciled=reconciled,
        catalog=catalog,
    )

    refined = result.calls[1].returns[0]
    assert refined.write_mode == "transition"
    assert refined.transition_kind == "direct"
    assert refined.previous_write_step_id == "initial_state"
    assert any(
        repair.action == "promote_state_write_to_direct_transition"
        for repair in result.repairs
    )


def test_object_state_refinement_infers_closed_state_from_symbol_identity() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    call = FunctionalCall(
        call_id="evaluate_target",
        capability_id="evaluate_point_at_parameter",
        args={},
        return_bindings={},
        strategy="substitute the matching parameter value",
        reason="synthetic identity-safe closure",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (call,)),),
    )
    symbol_ref = "symbol:part:t"
    source_point = ResolvedFunctionalValue(
        handle="fact:part:target_open_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        source_call_id="derive_target",
        return_name="point",
        object_ref="point:part:target",
        free_symbol_refs=(symbol_ref,),
    )
    parameter_value = ResolvedFunctionalValue(
        handle="fact:part:t_value",
        runtime_type="ParameterValue",
        valid_scope="part",
        state_slot_id=f"{symbol_ref}.value@part",
        source_call_id="solve_t",
        return_name="parameter_value",
        object_ref=symbol_ref,
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="evaluated_point",
        handle="fact:part:target_closed_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        object_ref="point:part:target",
        identity_policy="preserve_input_object",
        write_mode="transition",
        free_symbol_refs=(),
        source_state_slot_ids=(
            "point:part:target.coordinate@part",
            f"{symbol_ref}.value@part",
        ),
    )

    result = refine_functional_object_states(
        plan,
        reconciled=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="part",
                capability_id=call.capability_id,
                resolved_args={
                    "point": (source_point,),
                    "parameter_value": (parameter_value,),
                },
                returns=(allocation,),
            ),
        ),
        catalog=catalog,
    )

    assert result.plan.calls[0].return_expectations == {
        "evaluated_point": "closed_state"
    }
    assert any(
        repair.action == "infer_object_result_form"
        and repair.to_value == "closed_state"
        for repair in result.repairs
    )


def test_object_state_refinement_rejects_stale_transition_branch() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    call_ids = ("initial_state", "latest_state", "stale_branch")
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope(
                "part",
                "part",
                tuple(
                    FunctionalCall(
                        call_id=call_id,
                        capability_id="quadratic_from_constraints",
                        args={},
                        return_bindings={},
                        strategy="update one curve state",
                        reason="synthetic versioned transition",
                    )
                    for call_id in call_ids
                ),
            ),
        ),
    )
    slot_id = "function:part:curve.expression@part"

    def allocation(call_id: str, *, write_mode: str = "value"):
        return FunctionalReturnAllocation(
            call_id=call_id,
            return_name="parabola",
            handle=f"fact:part:{call_id}",
            runtime_type="Parabola",
            valid_scope="part",
            state_slot_id=slot_id,
            object_ref="function:part:curve",
            identity_policy="preserve_input_object",
            write_mode=write_mode,
            source_state_slot_ids=(slot_id,),
            dependency_object_refs=("function:part:curve",),
        )

    source = ResolvedFunctionalValue(
        handle="fact:part:initial_state",
        runtime_type="Parabola",
        valid_scope="part",
        state_slot_id=slot_id,
        source_call_id="initial_state",
        return_name="parabola",
        object_ref="function:part:curve",
    )
    reconciled = (
        FunctionalCallReconciliation(
            call_id="initial_state",
            scope_id="part",
            capability_id="quadratic_from_constraints",
            resolved_args={},
            returns=(allocation("initial_state"),),
        ),
        FunctionalCallReconciliation(
            call_id="latest_state",
            scope_id="part",
            capability_id="quadratic_from_constraints",
            resolved_args={"quadratic": (source,)},
            returns=(allocation("latest_state"),),
        ),
        FunctionalCallReconciliation(
            call_id="stale_branch",
            scope_id="part",
            capability_id="quadratic_from_constraints",
            resolved_args={"quadratic": (source,)},
            returns=(allocation("stale_branch", write_mode="transition"),),
        ),
    )

    result = refine_functional_object_states(
        plan,
        reconciled=reconciled,
        catalog=catalog,
    )

    assert [issue.code for issue in result.issues] == [
        "functional.stale_state_transition"
    ]
    assert result.issues[0].details == {
        "state_slot_id": slot_id,
        "source_call_id": "initial_state",
        "latest_call_id": "latest_state",
        "repair_call_ids": ["stale_branch"],
    }


def test_execution_scope_closure_hoists_visible_dependency_producer() -> None:
    producer = FunctionalCall(
        call_id="derive_parameter_state",
        capability_id="parameter_from_expression_value",
        args={},
        return_bindings={},
        strategy="derive a reusable parameter state",
        reason="synthetic placement",
    )
    consumer = FunctionalCall(
        call_id="consume_parameter_state",
        capability_id="evaluate_expression_at_parameter",
        args={},
        return_bindings={},
        strategy="consume the state in a shared calculation",
        reason="synthetic placement",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("ii_1", "ii_1", (producer, consumer)),),
    )
    source = ResolvedFunctionalValue(
        handle="fact:ii:shared_expression",
        runtime_type="Expression",
        valid_scope="ii",
        state_slot_id="expression:ii:shared.value@ii",
    )
    produced_value = ResolvedFunctionalValue(
        handle="fact:ii_1:parameter_value",
        runtime_type="ParameterValue",
        valid_scope="ii_1",
        state_slot_id="symbol:problem:t.value@ii_1",
        source_call_id=producer.call_id,
        return_name="parameter_value",
        object_ref="symbol:problem:t",
    )
    reconciled = {
        producer.call_id: FunctionalCallReconciliation(
            call_id=producer.call_id,
            scope_id="ii_1",
            capability_id=producer.capability_id,
            resolved_args={"expression": (source,)},
            returns=(),
        ),
        consumer.call_id: FunctionalCallReconciliation(
            call_id=consumer.call_id,
            scope_id="ii_1",
            capability_id=consumer.capability_id,
            resolved_args={"parameter_value": (produced_value,)},
            returns=(),
        ),
    }

    scopes = functional_call_placement_module._close_execution_scope_dependencies(
        plan,
        reconciled=reconciled,
        dependency_graph={
            producer.call_id: (),
            consumer.call_id: (producer.call_id,),
        },
        requested_scopes={
            producer.call_id: "ii_1",
            consumer.call_id: "ii",
        },
        declared_scopes={
            producer.call_id: "ii_1",
            consumer.call_id: "ii_1",
        },
        aliases={},
        registry=_registry(),
    )

    assert scopes == {
        producer.call_id: "ii",
        consumer.call_id: "ii",
    }


def test_object_form_is_not_closed_when_capability_creates_companion_symbol() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability_id = "quadratic_axis_parameterized_point"
    assert catalog.get(capability_id) is not None
    call = FunctionalCall(
        call_id="parameterize_object",
        capability_id=capability_id,
        args={},
        return_bindings={},
        strategy="introduce an internal coordinate parameter",
        reason="exercise conservative closure inference",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (call,)),),
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="point",
        handle="fact:part:parameterized_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        object_ref="point:part:target",
        identity_policy="target_object",
        write_mode="create",
        source_state_slot_ids=("function:part:curve.expression@part",),
    )

    result = refine_functional_object_states(
        plan,
        reconciled=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="part",
                capability_id=capability_id,
                resolved_args={},
                returns=(allocation,),
            ),
        ),
        catalog=catalog,
    )

    assert result.plan.calls[0].return_expectations == {}


@pytest.mark.parametrize(
    (
        "expectation",
        "free_symbols",
        "ignored_symbols",
        "expected_status",
        "issue_count",
    ),
    (
        ("closed_state", ("p",), (), "mismatch", 1),
        ("open_state", (), (), "result_form_closed", 0),
        ("closed_state", (), (), "matched", 0),
        ("closed_state", ("x",), ("x",), "matched", 0),
    ),
)
def test_runtime_verifies_object_result_form_from_free_symbols(
    expectation: str,
    free_symbols: tuple[str, ...],
    ignored_symbols: tuple[str, ...],
    expected_status: str,
    issue_count: int,
) -> None:
    call = FunctionalCall(
        call_id="derive_object_state",
        capability_id="quadratic_axis_x_intercept_point",
        args={},
        return_bindings={},
        strategy="derive the current coordinate state",
        reason="exercise object result form verification",
        return_expectations={"axis_point": expectation},  # type: ignore[dict-item]
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (call,)),),
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="axis_point",
        handle="fact:part:target_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        object_ref="point:part:target",
        identity_policy="target_object",
        write_mode="create",
    )
    reconciliation = FunctionalPlanReconciliationResult(
        plan=plan,
        calls=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="part",
                capability_id=call.capability_id,
                resolved_args={},
                returns=(allocation,),
            ),
        ),
    )
    diagnostic = StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=(
            StateWriteProvenance(
                step_id=call.call_id,
                scope_id="part",
                capability_id=call.capability_id,
                produced_handle=allocation.handle,
                output_key="axis_point",
                runtime_type="Point",
                identity_policy="target_object",
                identity_role="axis_point",
                free_symbol_names=free_symbols,
                closure_ignored_symbol_names=ignored_symbols,
            ),
        ),
    )

    events, issues = verify_functional_result_forms(
        plan,
        reconciliation,
        diagnostic,
    )
    assert events[0].actual_form in {"open_state", "closed_state"}
    assert events[0].status == expected_status
    assert len(issues) == issue_count


def test_result_form_verification_records_missing_runtime_provenance() -> None:
    call = FunctionalCall(
        call_id="compute_scalar",
        capability_id="distance_between_points",
        args={},
        return_bindings={},
        strategy="compute a scalar",
        reason="exercise provenance drift diagnostics",
        return_expectations={"distance": "closed_value"},
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("i", "i", (call,)),),
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="distance",
        handle="fact:i:distance",
        runtime_type="MinimumExpression",
        valid_scope="i",
        state_slot_id="distance.expression@i:MinimumExpression",
        object_ref=None,
        identity_policy="value_only",
        write_mode="value",
    )
    reconciliation = FunctionalPlanReconciliationResult(
        plan=plan,
        calls=(
            FunctionalCallReconciliation(
                call_id=call.call_id,
                scope_id="i",
                capability_id=call.capability_id,
                resolved_args={},
                returns=(allocation,),
            ),
        ),
    )

    events, issues = verify_functional_result_forms(
        plan,
        reconciliation,
        StepIntentExecutionDiagnostic(ok=True),
    )

    assert issues == ()
    assert len(events) == 1
    assert events[0].status == "provenance_missing"
    assert events[0].actual_form is None


def test_functional_catalog_rejects_invalid_usage_guidance() -> None:
    inputs = _base_inputs()
    recipe = next(
        item
        for item in inputs.family_spec.step_recipes
        if item.recipe_id == "right_angle_equal_length_construct_and_select"
    )

    blank_description = replace(recipe, description="  ")
    blank_description_family = replace(
        inputs.family_spec,
        step_recipes=tuple(
            blank_description if item.recipe_id == recipe.recipe_id else item
            for item in inputs.family_spec.step_recipes
        ),
    )
    with pytest.raises(
        ValueError,
        match="functional capability has empty use_when",
    ):
        FunctionalCapabilityCatalog.from_family_spec(
            blank_description_family,
            inputs.method_specs,
        )

    blank_counterexample = replace(recipe, do_not_use_when=("",))
    blank_counterexample_family = replace(
        inputs.family_spec,
        step_recipes=tuple(
            blank_counterexample if item.recipe_id == recipe.recipe_id else item
            for item in inputs.family_spec.step_recipes
        ),
    )
    with pytest.raises(
        ValueError,
        match="functional capability has empty do_not_use_when item",
    ):
        FunctionalCapabilityCatalog.from_family_spec(
            blank_counterexample_family,
            inputs.method_specs,
        )


def test_functional_catalog_deduplicates_usage_counterexamples() -> None:
    inputs = _base_inputs()
    recipe = next(
        item
        for item in inputs.family_spec.step_recipes
        if item.recipe_id == "right_angle_equal_length_construct_and_select"
    )
    guidance = "只有单个几何条件，无法确定完整对象角色。"
    overridden = replace(
        recipe,
        do_not_use_when=(guidance, guidance),
    )
    family = replace(
        inputs.family_spec,
        step_recipes=tuple(
            overridden if item.recipe_id == recipe.recipe_id else item
            for item in inputs.family_spec.step_recipes
        ),
    )

    capability = FunctionalCapabilityCatalog.from_family_spec(
        family,
        inputs.method_specs,
    ).to_prompt_payload()["capabilities"]
    item = next(
        value
        for value in capability
        if value["capability_id"] == recipe.recipe_id
    )

    assert item["do_not_use_when"] == [guidance]


def test_context_closure_arg_bindings_are_projected_from_declarations() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    right_angle = catalog.get("right_angle_equal_length_construct_and_select")
    assert right_angle is not None
    assert {
        (item.semantic_role, item.arg_name)
        for item in right_angle.context_arg_bindings
    } == {
        ("anchor", "anchor"),
        ("reference", "reference"),
        ("target", "target"),
        ("orientation", "quadrant"),
        ("parameter", "parameter"),
        ("parameter_constraint", "parameter_constraint"),
    }

    path_reduction = catalog.get("two_moving_points_path_reduction")
    assert path_reduction is not None
    assert {
        (item.semantic_role, item.arg_name)
        for item in path_reduction.context_arg_bindings
    } == {
        ("first_membership", "first_moving_membership"),
        ("second_membership", "second_moving_membership"),
        ("binding_relation", "binding_relation"),
        ("first_segment_start", "first_segment_start"),
        ("joint_point", "joint_point"),
        ("second_segment_end", "second_segment_end"),
    }
    assert "context_arg_bindings" not in right_angle.to_prompt_payload()


def test_derived_role_identity_is_call_scoped() -> None:
    first = derived_role_object_ref(
        call_id="derive_first_path",
        semantic_role="path_minimum_point_1",
        scope_id="ii_2",
        runtime_type="Point",
    )
    second = derived_role_object_ref(
        call_id="derive_second_path",
        semantic_role="path_minimum_point_1",
        scope_id="ii_2",
        runtime_type="Point",
    )

    assert first == "point:ii_2:derive_first_path_path_minimum_point_1"
    assert second == "point:ii_2:derive_second_path_path_minimum_point_1"
    assert first != second


def test_functional_catalog_lowers_containers_and_hides_auto_args() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    quadratic = catalog.get("quadratic_from_constraints")
    assert quadratic is not None
    args = {item.name: item for item in quadratic.args}

    assert args["known_coefficients"].accepted_item_types == ("ParameterValue",)
    assert args["known_coefficients"].cardinality == "many"
    assert args["known_coefficients"].aggregation == "coefficients_by_symbol"
    assert args["curve_points"].accepted_item_types == ("Point",)
    assert args["curve_points"].aggregation == "point_list"
    assert {item.name for item in quadratic.auto_args} >= {
        "quadratic",
        "x",
        "all_coefficients",
    }
    prompt_args = {
        item["name"] for item in quadratic.to_prompt_payload()["args"]
    }
    assert not prompt_args & {"quadratic", "x", "all_coefficients"}

    parameter_solver = catalog.get("parameter_from_expression_value")
    assert parameter_solver is not None
    parameter_arg = next(
        item for item in parameter_solver.args if item.name == "parameter"
    )
    assert parameter_arg.llm_mode == "optional"
    assert parameter_arg.accepted_item_types == ("Symbol",)
    assert parameter_arg.deterministic_resolver == "unique_parameter_symbol"
    assert "parameter" not in {
        item.name for item in parameter_solver.auto_args
    }

    path = catalog.get("path_minimum_by_straightened_distance")
    assert path is not None
    assert [item.semantic_role for item in path.args] == [
        "endpoint_1",
        "endpoint_2",
        "parameter_value",
    ]

    straightening = catalog.get(
        "broken_path_straightening_minimum_expression"
    )
    assert straightening is not None
    assert [item.semantic_role for item in straightening.args] == [
        "path_transformation",
        "moving_locus",
    ]
    moving_locus = next(
        item for item in straightening.args if item.semantic_role == "moving_locus"
    )
    assert moving_locus.accepted_item_types == ("Line",)
    assert moving_locus.cardinality == "optional"
    assert [
        item.to_prompt_payload()
        for item in straightening.input_closure_requirements
    ] == [
        {
            "role": "moving_locus",
            "requirement": (
                "路径变换必须包含对应运动轨迹，或显式提供该轨迹。"
            ),
        },
    ]
    prompt_straightening = straightening.to_prompt_payload()
    assert prompt_straightening["input_requirements"] == [
        {
            "role": "moving_locus",
            "requirement": (
                "路径变换必须包含对应运动轨迹，或显式提供该轨迹。"
            ),
        },
        {
            "requirement": (
                "显式轨迹所属动点必须与 PathTransformation "
                "声明的 moving object 相同。"
            ),
        },
    ]

    reduction = catalog.get("two_moving_points_path_reduction")
    assert reduction is not None
    transformation = next(
        item
        for item in reduction.returns
        if item.name == "path_transformation"
    )
    assert transformation.provides_semantic_roles == ("moving_locus",)
    assert transformation.to_prompt_payload()["provides"] == [
        "moving_locus"
    ]
    assert "可据此省略 moving_locus" in (
        transformation.to_prompt_payload()["desc"]
    )

    heping_ermo = load_problem_ir(HEPING_ERMO_FIXTURE)
    heping_inputs = build_strategy_probe_inputs(heping_ermo)
    square_reduction = FunctionalCapabilityCatalog.from_family_spec(
        heping_inputs.family_spec,
        heping_inputs.method_specs,
    ).get("square_path_dimension_reduction")
    assert square_reduction is not None
    square_transformation = next(
        item
        for item in square_reduction.returns
        if item.name == "path_transformation"
    )
    assert square_transformation.provides_semantic_roles == ()
    assert "provides" not in square_transformation.to_prompt_payload()
    assert "必须显式提供属于同一动点的 Line" in (
        square_transformation.to_prompt_payload()["desc"]
    )
    axis_parameterized = FunctionalCapabilityCatalog.from_family_spec(
        heping_inputs.family_spec,
        heping_inputs.method_specs,
    ).get("quadratic_axis_parameterized_point")
    assert axis_parameterized is not None
    axis_returns = {
        item.name: item.to_prompt_payload()
        for item in axis_parameterized.returns
    }
    assert "默认不等于抛物线系数" in axis_returns["point"]["desc"]
    assert "只有同身份 ParameterValue 才能代入" in (
        axis_returns["parameter"]["desc"]
    )
    assert any(
        "不同 Symbol identity 的参数值不能互相代入" in item
        for item in axis_parameterized.do_not_use_when
    )
    assert {
        item.semantic_role: item.accepted_condition_kinds
        for item in square_reduction.args
    } == {
        "path_minimum_target": ("path_minimum_target",),
        "square": ("square",),
        "midpoint_definition": ("midpoint_definition",),
        "square_center": ("square_center",),
    }

    midpoint = catalog.get("midpoint_point")
    assert midpoint is not None
    assert [item.name for item in midpoint.args] == ["midpoint_definition"]
    assert midpoint.args[0].accepted_condition_kinds == (
        "midpoint_definition",
    )
    assert {item.name for item in midpoint.auto_args} == {"p1", "p2", "target"}


def test_context_semantic_index_selects_object_state_and_condition_views() -> None:
    inputs = _base_inputs()
    index = FunctionalSemanticIndex.from_context(
        _context(inputs),
        handle_registry=_registry(),
    )

    parameter_value, _ = index.resolve(
        SemanticRef("a", "symbol"),
        scope_id="i",
        accepted_types=("ParameterValue",),
    )
    assert parameter_value is not None
    assert parameter_value.handle == "fact:i:a_value"
    assert parameter_value.object_ref == "symbol:problem:a"

    point_state, _ = index.resolve(
        SemanticRef("M", "point"),
        scope_id="ii",
        accepted_types=("Point",),
    )
    assert point_state is not None
    assert point_state.object_ref == "point:ii:M"
    assert "symbol:problem:m" in point_state.dependency_object_refs

    equation, _ = index.resolve(
        SemanticRef("coefficient_relation", "fact"),
        scope_id="i",
        accepted_types=("Equation",),
    )
    condition, _ = index.resolve(
        SemanticRef("coefficient_relation", "fact"),
        scope_id="i",
        accepted_types=("Condition",),
        accepted_condition_kinds=("coefficient_relation",),
    )
    assert equation is not None and equation.runtime_type == "Equation"
    assert condition is not None and condition.runtime_type == "Condition"

    function_object, _ = index.resolve(
        SemanticRef("parabola", "function"),
        scope_id="ii",
        accepted_types=("Function",),
    )
    assert function_object is not None
    assert function_object.object_ref == "function:problem:parabola"
    parabola_state, _ = index.resolve(
        SemanticRef("parabola", "function"),
        scope_id="ii",
        accepted_types=("Parabola",),
    )
    assert parabola_state is None


def test_reconciler_selects_latest_prior_call_state_for_object_ref() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "i_1",
                "calls": [
                    {
                        "call_id": "derive_shared_function_state",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "known_coefficients": [
                                {"ref": "b_value", "kind": "fact"},
                                {"ref": "c_value", "kind": "fact"},
                            ]
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "strategy": "derive a state for the shared function object",
                        "reason": "the next sibling scope consumes this state",
                    }
                ],
            },
            {
                "scope_id": "i_2",
                "label": "i_2",
                "calls": [
                    {
                        "call_id": "consume_shared_function_state",
                        "capability_id": "quadratic_axis_parameterized_point",
                        "args": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "return_bindings": {
                            "point": {"ref": "i_2.E", "kind": "point"}
                        },
                        "strategy": "read the latest compatible function state",
                        "reason": "the LLM names the object rather than a runtime state",
                    }
                ],
            },
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=(),
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    producer = next(
        item for item in result.calls if item.call_id == "derive_shared_function_state"
    )
    parabola_return = next(
        item for item in producer.returns if item.return_name == "parabola"
    )
    assert parabola_return.object_ref == "function:problem:parabola"
    assert parabola_return.valid_scope == "i"
    consumer = next(
        item for item in result.calls if item.call_id == "consume_shared_function_state"
    )
    selected = consumer.resolved_args["parabola"][0]
    assert selected.runtime_type == "Parabola"
    assert selected.source_call_id == "derive_shared_function_state"
    consumer_returns = {item.return_name: item for item in consumer.returns}
    point_object_ref = consumer_returns["point"].object_ref
    assert point_object_ref is not None
    assert consumer_returns["parameter"].object_ref == (
        f"symbol:{consumer_returns['parameter'].valid_scope}:"
        f"{point_object_ref.rsplit(':', 1)[-1]}_axis_parameter"
    )
    assert result.dependency_graph[consumer.call_id] == (
        "derive_shared_function_state",
    )
    actions = {
        item["action"] for item in result.elaboration["deterministic_repairs"]
    }
    assert "promote_return_scope_for_object_consumers" in actions
    assert "select_latest_object_state" in actions


def test_reconciler_rejects_parameter_value_for_wrong_companion_symbol() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    method_id = "evaluate_point_at_parameter"
    inputs = replace(
        inputs,
        method_specs=MethodSpecRegistry(
            {
                **inputs.method_specs.specs,
                method_id: replace(
                    inputs.method_specs.require(method_id),
                    plan_transformer=None,
                ),
            }
        ),
    )
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "i_1",
                "calls": [
                    {
                        "call_id": "derive_function",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "known_coefficients": [
                                {"ref": "b_value", "kind": "fact"},
                                {"ref": "c_value", "kind": "fact"},
                            ]
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "strategy": "derive the function state",
                        "reason": "prepare a parameterized point",
                    }
                ],
            },
            {
                "scope_id": "i_2",
                "label": "i_2",
                "calls": [
                    {
                        "call_id": "parameterize_point",
                        "capability_id": "quadratic_axis_parameterized_point",
                        "args": {
                            "parabola": {
                                "from_call": "derive_function",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {
                            "point": {"ref": "i_2.E", "kind": "point"}
                        },
                        "strategy": "parameterize E",
                        "reason": "create its internal Symbol companion",
                    },
                    {
                        "call_id": "evaluate_with_wrong_symbol",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {
                            "point": {
                                "from_call": "parameterize_point",
                                "return": "point",
                            },
                            "parameter_value": {
                                "ref": "c",
                                "kind": "symbol",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "use an unrelated parameter value",
                        "reason": "exercise Symbol identity validation",
                    },
                ],
            },
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=(),
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    issue = next(
        item
        for item in result.issues
        if item.call_id == "evaluate_with_wrong_symbol"
    )
    assert issue.code == "functional.arg_identity_mismatch"
    assert issue.details is not None
    assert issue.details["required_symbol_sources"] == [
        {
            "from_call": "parameterize_point",
            "return": "parameter",
            "value_type": "Symbol",
        }
    ]
    assert issue.details["current_bindings"][0][
        "identity_matches_required"
    ] is False
    assert issue.details["unchanged_binding_rejected"] is True
    assert {item["action"] for item in issue.details["repair_options"]} == {
        "add_missing_state_producer",
        "replace_capability",
    }

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=0,
        problem_payload=problem_payload,
        validation_report=validation,
    )
    assert replay.retry_state is not None
    ticket = next(
        item
        for item in replay.retry_state.issues
        if item.code == "functional.arg_identity_mismatch"
    )
    assert ticket.details is not None
    assert ticket.details["unchanged_binding_rejected"] is True
    assert ticket.details["current_bindings"][0][
        "identity_matches_required"
    ] is False
    assert "compatible_call_results" not in ticket.details
    assert "replace this call" in ticket.message
    assert "unchanged_binding_rejected" in replay.retry_state.repair_instruction


def test_companion_validator_checks_parameterized_context_point_without_producer() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    capability = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).get("evaluate_point_at_parameter")
    assert capability is not None

    issues = functional_reconciliation_issues(
        capability,
        {
            "point": (
                ResolvedFunctionalValue(
                    handle="fact:ii:M_coordinate_expr",
                    runtime_type="Point",
                    valid_scope="ii",
                    state_slot_id="point:M.coordinate@ii:Point",
                    object_ref="point:ii:M",
                    free_symbol_refs=("symbol:problem:m",),
                ),
            ),
            "parameter_value": (
                ResolvedFunctionalValue(
                    handle="fact:i:c_value",
                    runtime_type="ParameterValue",
                    valid_scope="i",
                    object_ref="symbol:problem:c",
                ),
            ),
        },
        produced={},
        call_id="evaluate_initial_point",
        scope_id="ii",
    )

    assert len(issues) == 1
    assert issues[0].code == "functional.arg_identity_mismatch"
    assert issues[0].details is not None
    assert issues[0].details["required_symbol_sources"] == [
        {
            "source": "point_free_symbol_state",
            "input_arg": "point",
            "semantic_ref": "m",
            "value_type": "Symbol",
        }
    ]


def test_companion_validator_allows_one_identity_safe_partial_substitution() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    capability = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).get("evaluate_point_at_parameter")
    assert capability is not None

    issues = functional_reconciliation_issues(
        capability,
        {
            "point": (
                ResolvedFunctionalValue(
                    handle="fact:ii:E_coordinate_expr",
                    runtime_type="Point",
                    valid_scope="ii",
                    state_slot_id="point:ii:E.coordinate@ii",
                    object_ref="point:ii:E",
                    free_symbol_refs=(
                        "symbol:problem:c",
                        "symbol:problem:t",
                    ),
                ),
            ),
            "parameter_value": (
                ResolvedFunctionalValue(
                    handle="fact:ii:c_value",
                    runtime_type="ParameterValue",
                    valid_scope="ii",
                    object_ref="symbol:problem:c",
                ),
            ),
        },
        produced={},
        call_id="partially_evaluate_E",
        scope_id="ii",
    )

    assert issues == ()


def test_student_parameter_solver_checks_actual_runtime_expression() -> None:
    c, t = sp.symbols("c t")
    expression_path = "$step.solve_c.temp.expression"
    parameter_path = "$problem.symbols.c"
    plan = StepPlan(
        step_id="solve_c",
        goal=StepGoal("solve_c", "derive_parameter", "$step.solve_c.temp.value", "ii"),
        scope="ii",
        invocations=[
            MethodInvocation(
                invocation_id="solve_c.parameter_from_expression_value",
                method_id="parameter_from_expression_value",
                scope="ii",
                inputs={
                    "expression": expression_path,
                    "parameter": parameter_path,
                },
                outputs={"parameter_value": "$step.solve_c.temp.value"},
            )
        ],
    )
    step = StepIntent(
        scope_id="ii",
        step_id="solve_c",
        recipe_hint="parameter_from_expression_value",
        goal_type="derive_parameter",
        target="fact:ii:c_value",
        strategy="reduce to one unknown and solve",
    )

    def binding_index(expression: sp.Expr) -> object:
        values = {
            expression_path: TypedValue("MinimumExpression", expression),
            parameter_path: TypedValue("Symbol", c),
        }
        context = SimpleNamespace(
            read_path=lambda path, **_kwargs: values[path],
        )
        return SimpleNamespace(context=context)

    with pytest.raises(
        StrategyDraftValidationError,
        match="function.student_symbolic_complexity_exceeded.*symbols=c\\|t",
    ):
        _validate_student_single_degree_of_freedom(
            plan,
            step,
            binding_index(c + t),  # type: ignore[arg-type]
        )

    assert (
        _validate_student_single_degree_of_freedom(
            plan,
            step,
            binding_index(2 * c + 1),  # type: ignore[arg-type]
        )
        is plan
    )


def test_student_parameter_solver_aggregates_all_invocations() -> None:
    c, t = sp.symbols("c t")
    expression_c = "$step.solve_c.temp.expression_c"
    expression_t = "$step.solve_c.temp.expression_t"
    parameter_path = "$problem.symbols.c"
    plan = StepPlan(
        step_id="solve_c",
        goal=StepGoal("solve_c", "derive_parameter", "$step.solve_c.temp.value", "ii"),
        scope="ii",
        invocations=[
            MethodInvocation(
                invocation_id="solve_c.first",
                method_id="parameter_from_expression_value",
                scope="ii",
                inputs={"expression": expression_c, "parameter": parameter_path},
                outputs={"parameter_value": "$step.solve_c.temp.first"},
            ),
            MethodInvocation(
                invocation_id="solve_c.second",
                method_id="parameter_from_expression_value",
                scope="ii",
                inputs={"expression": expression_t, "parameter": parameter_path},
                outputs={"parameter_value": "$step.solve_c.temp.second"},
            ),
        ],
    )
    step = StepIntent(
        scope_id="ii",
        step_id="solve_c",
        recipe_hint="parameter_from_expression_value",
        goal_type="derive_parameter",
        target="fact:ii:c_value",
        strategy="solve a student-readable parameter equation",
    )
    values = {
        expression_c: TypedValue("MinimumExpression", c),
        expression_t: TypedValue("MinimumExpression", t),
        parameter_path: TypedValue("Symbol", c),
    }
    index = SimpleNamespace(
        context=SimpleNamespace(
            read_path=lambda path, **_kwargs: values[path],
        )
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="function.student_symbolic_complexity_exceeded.*symbols=c\\|t",
    ):
        _validate_student_single_degree_of_freedom(
            plan,
            step,
            index,  # type: ignore[arg-type]
            "all_invocations",
        )


def test_student_symbolic_complexity_recognizes_identity_safe_reduction() -> None:
    analysis = analyze_student_symbolic_complexity(
        ("symbol:problem:c", "symbol:problem:t"),
        target_symbol_ref="symbol:problem:c",
        resolved_symbol_refs=("symbol:problem:t",),
    )

    assert analysis.status == "reducible_multi_symbol"
    assert analysis.student_ready
    assert analysis.residual_symbol_refs == ("symbol:problem:c",)


def test_contextual_catalog_only_exposes_constructible_capabilities() -> None:
    inputs = _base_inputs()
    context = _context(inputs)
    semantic_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=_registry(),
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)

    assert catalog.get("quadratic_vertex_point") is not None
    assert catalog.get("translated_point") is None
    assert all(
        not arg.required
        or semantic_index.has_compatible_view(
            accepted_types=arg.accepted_item_types or (arg.runtime_type,),
            accepted_condition_kinds=arg.accepted_condition_kinds,
        )
        or any(
            result.runtime_type in (arg.accepted_item_types or (arg.runtime_type,))
            for producer in catalog.items.values()
            for result in producer.returns
        )
        for capability in catalog.items.values()
        for arg in capability.args
    )


def test_contextual_catalog_keeps_selector_with_declared_target_metadata() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )

    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)

    assert catalog.get("translated_point") is not None


def test_selector_state_roles_reject_type_compatible_wrong_points() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.get("line_locus_minimum_point")
    assert capability is not None
    args = {item.name: item for item in capability.args}
    assert args["minimum_point_1"].accepted_semantic_roles == (
        "path_minimum_point_1",
    )
    assert args["minimum_point_2"].accepted_semantic_roles == (
        "path_minimum_point_2",
    )
    assert capability.identity_constraints
    prompt_payload = capability.to_prompt_payload()
    assert any(
        "同一对象" in requirement["requirement"]
        for requirement in prompt_payload["input_requirements"]
    )

    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "locate_minimum_point",
                        "capability_id": "line_locus_minimum_point",
                        "args": {
                            "moving_locus": {
                                "ref": "ii.A",
                                "kind": "point",
                            },
                            "minimum_point_1": {
                                "ref": "ii.A",
                                "kind": "point",
                            },
                            "minimum_point_2": {
                                "ref": "M",
                                "kind": "point",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "try ordinary endpoints",
                        "reason": "exercise semantic role validation",
                    }
                ],
            }
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=(),
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    role_issues = [
        item
        for item in result.issues
        if item.code == "functional.state_role_mismatch"
    ]
    assert {item.details["arg"] for item in role_issues if item.details} == {
        "minimum_point_1",
        "minimum_point_2",
    }


def test_evaluated_path_endpoints_preserve_semantic_lineage() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii")
    calls = scope["calls"]
    minimum_index = next(
        index
        for index, call in enumerate(calls)
        if call["call_id"] == "derive_minimum_point_G_ii"
    )
    evaluated_calls = [
        {
            "call_id": f"evaluate_path_endpoint_{number}_ii",
            "capability_id": "evaluate_point_at_parameter",
            "args": {
                "point": {
                    "from_call": "derive_path_minimum_ii",
                    "return": f"path_minimum_point_{number}",
                },
                "parameter_value": {
                    "from_call": "solve_parameter_c_ii",
                    "return": "parameter_value",
                },
            },
            "return_bindings": {},
            "strategy": "代入已确定参数并保留端点对象身份。",
            "reason": "验证状态转移后的语义 lineage。",
        }
        for number in (1, 2)
    ]
    calls[minimum_index:minimum_index] = evaluated_calls
    minimum_call = next(
        call for call in calls if call["call_id"] == "derive_minimum_point_G_ii"
    )
    for number in (1, 2):
        minimum_call["args"][f"minimum_point_{number}"] = {
            "from_call": f"evaluate_path_endpoint_{number}_ii",
            "return": "evaluated_point",
        }

    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert not [
        issue
        for issue in result.issues
        if issue.code
        in {"functional.state_role_mismatch", "functional.object_identity_mismatch"}
    ]
    allocations = {
        (item.call_id, item.return_name): item
        for call in result.calls
        for item in call.returns
    }
    for number in (1, 2):
        allocation = allocations[
            (f"evaluate_path_endpoint_{number}_ii", "evaluated_point")
        ]
        assert f"path_minimum_point_{number}" in allocation.lineage.semantic_roles
        assert allocation.lineage.object_roles


def test_path_locus_identity_mismatch_repairs_wrong_locus_subgraph() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    calls = [call for scope in payload["scopes"] for call in scope["calls"]]
    locus_call = next(call for call in calls if call["call_id"] == "derive_locus_G_ii")
    locus_call["args"]["point"] = {
        "from_call": "parameterize_axis_point_E_ii",
        "return": "point",
    }

    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    issue = next(
        item
        for item in result.issues
        if item.code == "functional.object_identity_mismatch"
        and item.call_id == "derive_path_minimum_ii"
    )
    assert issue.details["actual_object_refs"] == ["point:ii:E"]
    assert issue.details["expected_object_refs"] == ["point:ii:G"]
    assert "derive_locus_G_ii" in issue.details["repair_call_ids"]
    assert "derive_path_minimum_ii" in issue.details["repair_call_ids"]
    repair_roots = strategy_replay_module._root_repair_call_ids(result)
    assert "derive_locus_G_ii" in repair_roots
    assert "derive_path_minimum_ii" in repair_roots
    assert "derive_minimum_point_G_ii" not in repair_roots


def test_path_locus_identity_requirement_is_prompt_visible_and_optional() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.get("broken_path_straightening_minimum_expression")
    assert capability is not None
    constraint = next(
        item
        for item in capability.identity_constraints
        if item.left == "arg:moving_locus.object_role:subject"
    )
    assert constraint.applicability == "when_all_present"
    assert any(
        "moving object" in item["requirement"]
        for item in capability.to_prompt_payload()["input_requirements"]
    )

    plan, validation = _validate(
        json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8")),
        inputs,
    )
    assert validation.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert not [
        item
        for item in result.issues
        if item.code == "functional.identity_constraint_unresolved"
        and item.call_id == "ii_derive_path_model"
    ]


def test_runtime_path_transformation_identity_drift_is_configuration_error() -> None:
    provenance = StateWriteProvenance(
        step_id="reduce_path",
        scope_id="ii",
        capability_id="synthetic_path_reduction",
        produced_handle="fact:ii:path_transformation",
        output_key="path_transformation",
        runtime_type="PathTransformation",
        identity_policy="value_only",
        identity_role="path_transformation",
        lineage=state_semantic_lineage(
            object_roles=(
                StateObjectRoleBinding(
                    role="moving_object",
                    object_refs=("point:ii:P",),
                ),
            ),
        ),
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.contract_runtime_identity_drift",
    ):
        _validate_runtime_lineage_payload(
            provenance,
            {"moving_point_ref": "point:ii:Q"},
        )


def test_selector_requires_materialized_point_state() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )
    contextual_catalog = catalog.contextualized(semantic_index)
    assert contextual_catalog.get("line_intersection_point") is None
    capability = catalog.get("square_adjacent_vertex_from_side")
    assert capability is not None
    args = {item.name: item for item in capability.args}
    assert args["side_start"].requires_materialized_state is True
    assert args["side_end"].requires_materialized_state is True

    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "derive_square_vertex",
                        "capability_id": "square_adjacent_vertex_from_side",
                        "args": {
                            "side_start": {
                                "ref": "ii.A",
                                "kind": "point",
                            },
                            "side_end": {
                                "ref": "ii.E",
                                "kind": "point",
                            },
                            "square": {
                                "ref": "square_AEKG",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "point": {
                                "ref": "ii.G",
                                "kind": "point",
                            }
                        },
                        "strategy": "derive G from side AE",
                        "reason": "exercise materialized state selection",
                    }
                ],
            }
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=(),
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    state_issues = [
        item
        for item in result.issues
        if item.code == "functional.arg_state_unavailable"
    ]
    assert [item.details["arg"] for item in state_issues if item.details] == [
        "side_end"
    ]
    assert state_issues[0].details["state_requirement"] == (
        "materialized_state"
    )


def test_hidden_midpoint_endpoint_requires_materialized_state() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "derive_midpoint",
                        "capability_id": "midpoint_point",
                        "args": {
                            "midpoint_definition": {
                                "ref": "F_midpoint_of_AE",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "midpoint": {
                                "ref": "F",
                                "kind": "point",
                            }
                        },
                        "strategy": "derive F",
                        "reason": "exercise hidden endpoint resolution",
                    }
                ],
            }
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=(),
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    issue = next(
        item
        for item in result.issues
        if item.code == "functional.arg_state_unavailable"
    )
    assert issue.details is not None
    assert issue.details["arg"] == "midpoint_definition"
    assert issue.details["hidden_arg"] == "p2"
    assert issue.details["required_ref"] == "ii.E"
    assert issue.details["state_requirement"] == "materialized_state"
    assert any(
        item["action"] == "resolve_condition_endpoint_state"
        and item["to"] == "p1=ii.A"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_hidden_condition_object_state_is_blocked_by_failed_producer() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "invalid_curve",
                        "capability_id": "not_an_executable_capability",
                        "args": {},
                        "return_bindings": {},
                        "strategy": "produce an invalid prerequisite",
                        "reason": "exercise dependency classification",
                    },
                    {
                        "call_id": "produce_E",
                        "capability_id": "quadratic_axis_parameterized_point",
                        "args": {
                            "quadratic": {
                                "from_call": "invalid_curve",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {
                            "point": {"ref": "ii.E", "kind": "point"}
                        },
                        "strategy": "materialize E",
                        "reason": "exercise future object identity",
                    },
                    {
                        "call_id": "derive_midpoint",
                        "capability_id": "midpoint_point",
                        "args": {
                            "midpoint_definition": {
                                "ref": "F_midpoint_of_AE",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "midpoint": {"ref": "F", "kind": "point"}
                        },
                        "strategy": "derive F",
                        "reason": "consume the hidden E endpoint",
                    },
                ],
            }
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=(),
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    reports = {item.call_id: item for item in result.call_reports}
    assert reports["invalid_curve"].status == "invalid"
    assert reports["produce_E"].status == "blocked_by_dependency"
    assert reports["derive_midpoint"].status == "blocked_by_dependency"
    assert reports["derive_midpoint"].blocked_by == ("produce_E",)
    assert not any(
        item.call_id == "derive_midpoint"
        and item.code == "functional.arg_state_unavailable"
        for item in result.issues
    )


def test_functional_payload_is_isolated_from_step_intent_payload() -> None:
    inputs = _base_inputs()
    builder = StrategyPayloadBuilder()
    functional = builder.build(
        inputs,
        problem_payload=_problem_payload(),
        output_format="functional_plan",
    )
    legacy = builder.build(inputs, problem_payload=_problem_payload())

    assert set(functional) == {
        "planner_output_format",
        "problem_id",
        "family_id",
        "problem_ir",
        "strategy_principles",
        "functional_capability_catalog",
        "few_shot_examples",
        "functional_few_shot_selection",
        "previous_attempt_state",
        "output_json_schema",
    }
    assert "method_catalog" not in functional
    assert "recipe_catalog" not in functional
    assert "naming_conventions" not in functional
    assert "semantic_read_catalog" not in functional
    assert "family_principles" not in functional
    assert functional["strategy_principles"]
    assert not {
        "display",
        "pattern",
        "problem_id",
        "problem_type",
        "purpose",
        "title",
    } & set(functional["problem_ir"])
    assert functional["problem_ir"]["original_text"]
    assert functional["problem_ir"]["facts"]
    assert functional["problem_ir"]["question_goals"]
    assert "planner_output_format" not in legacy
    assert not CANONICAL_REF_RE.search(json.dumps(functional, ensure_ascii=False))
    prompt = StrategyPromptRenderer().render(functional)
    assert "FunctionalPlan" in prompt.system
    assert "Semantic Read Catalog" not in prompt.user
    assert "ProblemIR 中的 `semantic_ref`" in prompt.system
    assert "完成题目" in prompt.system
    assert "先按 `use_when`" in prompt.system
    assert "do_not_use_when" in prompt.system
    assert "title/use_when" in prompt.user
    assert "title/description" not in prompt.user
    assert "后续不同 scope" in prompt.system
    assert "同一对象状态" in prompt.system
    assert "后续任何 scope" in prompt.user
    assert "不要另建“读取/复制/再次求解”call" in prompt.user
    assert "common_goal_types" not in prompt.user
    assert '"family_id"' not in prompt.user
    for internal_term in (
        "StepIntent",
        "StateSlot",
        "canonical handle",
        "runtime path",
        "creates/produces",
    ):
        assert internal_term not in prompt.system
        assert internal_term not in prompt.user


def test_validator_collects_duplicate_call_and_canonical_ref_errors() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    duplicate = json.loads(json.dumps(payload["scopes"][0]["calls"][0]))
    duplicate["goal_type"] = "legacy_goal_type"
    duplicate["args"]["coefficient_relation"]["ref"] = (
        "fact:problem:coefficient_relation"
    )
    payload["scopes"][0]["calls"].append(duplicate)

    plan, report = _validate(payload, inputs)

    assert plan is None
    assert {item.code for item in report.issues} >= {
        "functional.duplicate_call_id",
        "functional.canonical_ref_forbidden",
        "functional.fields_extra",
    }


def test_validator_allows_parent_scope_calls_without_direct_answer_binding() -> None:
    inputs = _base_inputs()
    payload = _axis_plan_payload()
    payload["scopes"].append(
        {
            "scope_id": "ii",
            "label": "shared parent scope",
            "calls": [
                {
                    "call_id": "derive_shared_axis_point",
                    "capability_id": "quadratic_axis_from_relation",
                    "args": {
                        "coefficient_relation": {
                            "ref": "coefficient_relation",
                            "kind": "fact",
                        }
                    },
                    "return_bindings": {},
                    "strategy": "derive shared state for descendant scopes",
                    "reason": "the parent scope need not own an answer",
                }
            ],
        }
    )

    plan, report = _validate(payload, inputs)

    assert report.ok
    assert plan is not None


def test_root_execution_scope_keeps_answer_in_student_question() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    payload["scopes"][0]["scope_id"] = "problem"

    plan, report = _validate(payload, inputs)

    assert report.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert result.ok
    assert result.projected_draft is not None
    assert result.projected_draft.scopes[0].scope_id == "problem"
    assert result.projected_draft.steps[0].scope_id == "problem"

    narrative = StudentNarrativePlacementProjector().project(
        effective_steps=tuple(
            step.to_payload(include_scope_id=True)
            for step in result.projected_draft.steps
        ),
        problem=_problem_payload(),
        functional_reconciliation=result,
        raw_functional_plan=plan,
    )
    assert narrative.placements[0].execution_scope_id == "problem"
    assert narrative.placements[0].presentation_scope_id == "i"
    assert narrative.placements[0].placement_reason == "answer_scope_anchor"


def test_reconciler_projects_short_refs_to_canonical_step_intent() -> None:
    inputs = _inputs_for_goal(0)
    plan, validation = _validate(_axis_plan_payload(), inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok
    assert result.projected_draft is not None
    step = result.projected_draft.steps[0]
    assert step.reads == ("fact:problem:coefficient_relation",)
    assert step.target == "answer:i.axis_point"
    assert step.goal_type == "derive_axis_point"
    assert step.creates == ()
    assert step.produces[0].output_type == "Point"
    assert result.projection_map[0].call_id == "derive_axis_point"
    finalized_once, _ = CanonicalDraftFinalizer().finalize(
        result.projected_draft,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
    )
    finalized_twice, _ = CanonicalDraftFinalizer().finalize(
        finalized_once,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
    )
    assert finalized_twice.to_payload() == finalized_once.to_payload()


def test_projector_uses_point_state_and_object_views_for_reads() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    axis_call = _axis_plan_payload()["scopes"][0]["calls"][0]
    axis_call["return_bindings"] = {
        "axis_point": {"ref": "D", "kind": "point"}
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    axis_call,
                    {
                        "call_id": "measure_from_axis_point",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {
                                "from_call": "derive_axis_point",
                                "return": "axis_point",
                            },
                            "p2": {
                                "from_call": "derive_axis_point",
                                "return": "axis_point",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "measure from the derived point",
                        "reason": "exercise the internal object view",
                    },
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.projected_draft is not None
    reads = result.projected_draft.steps[1].reads
    assert "point:problem:D" in reads
    axis_output = next(
        item for item in result.calls if item.call_id == "derive_axis_point"
    ).returns[0]
    assert axis_output.handle in reads


def test_projector_promotes_shared_call_execution_to_consumer_lca() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "derive_shared_point",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive a point shared by sibling scopes",
                        "reason": "exercise graph scope projection",
                    },
                    {
                        "call_id": "consume_shared_point_left",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {
                                "from_call": "derive_shared_point",
                                "return": "axis_point",
                            },
                            "p2": {"ref": "M", "kind": "point"},
                        },
                        "return_bindings": {},
                        "strategy": "consume the shared point in the left scope",
                        "reason": "create the first sibling dependency",
                    },
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    {
                        "call_id": "consume_shared_point",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {
                                "from_call": "derive_shared_point",
                                "return": "axis_point",
                            },
                            "p2": {"ref": "M", "kind": "point"},
                        },
                        "return_bindings": {},
                        "strategy": "consume the shared point",
                        "reason": "force a sibling-scope dependency",
                    }
                ],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.projected_draft is not None
    shared = next(
        step
        for step in result.projected_draft.steps
        if step.step_id == "derive_shared_point"
    )
    assert shared.scope_id == "ii"
    assert {item.valid_scope for item in shared.produces} == {"ii"}
    validated = StepIntentValidator().validate_json(
        json.dumps(result.projected_draft.to_payload()),
        question_goals=_base_inputs().question_goals,
        handle_registry=_registry(),
        partial_candidate=True,
        allow_shared_derivation_scopes=True,
    )
    assert any(scope.scope_id == "ii" for scope in validated.scopes)


def test_projector_promotes_all_returns_to_atomic_call_scope() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "derive_shared_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive one shared quadratic state",
                        "reason": "exercise atomic multi-return projection",
                    }
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    {
                        "call_id": "consume_shared_parabola",
                        "capability_id": "quadratic_vertex_point",
                        "args": {
                            "parabola": {
                                "from_call": "derive_shared_parabola",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {
                            "point": {"ref": "N", "kind": "point"}
                        },
                        "strategy": "consume the shared quadratic",
                        "reason": "force sibling visibility",
                    }
                ],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=(),
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.projected_draft is not None
    producer = next(
        step
        for step in result.projected_draft.steps
        if step.step_id == "derive_shared_parabola"
    )
    assert producer.scope_id == "ii"
    assert len(producer.produces) > 1
    assert {item.valid_scope for item in producer.produces} == {"ii"}
    repair_actions = {
        item["action"]
        for item in result.elaboration["deterministic_repairs"]
    }
    assert "place_call_at_shared_scope" in repair_actions


@pytest.mark.parametrize(
    ("binding_kind", "binding_ref"),
    (
        ("point", "G"),
        ("answer", "ii_2.intersection"),
    ),
)
def test_reconciler_rejects_derived_role_bound_as_external_identity(
    binding_kind: str,
    binding_ref: str,
) -> None:
    inputs = _inputs_for_goal(5)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    *_path_reduction_setup_calls(),
                    {
                        "call_id": "derive_path_endpoint",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                        },
                        "return_bindings": {
                            "path_minimum_point_2": {
                                "ref": binding_ref,
                                "kind": binding_kind,
                            }
                        },
                        "strategy": "derive an internal endpoint role",
                        "reason": "exercise return identity policy",
                    }
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    issue = next(
        item
        for item in result.issues
        if item.code == "functional.return_identity_mismatch"
    )
    assert issue.call_id == "derive_path_endpoint"
    assert issue.details == {
        "return": "path_minimum_point_2",
        "semantic_role": "path_minimum_point_2",
        "identity_policy": "derived_role",
        "bound_ref": binding_ref,
    }


def test_reconciler_infers_unique_target_objects_from_structured_problem_ir() -> None:
    inputs = _base_inputs()
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "derive_axis",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive the axis point",
                        "reason": "the relation determines the axis",
                    },
                    {
                        "call_id": "construct_unknown_point",
                        "capability_id": "right_angle_equal_length_construct_and_select",
                        "args": {
                            "right_angle_equal_length": {
                                "ref": "right_angle_equal_length_MDN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "construct the point selected by the condition",
                        "reason": "the relation has one unresolved point identity",
                    },
                    {
                        "call_id": "derive_midpoint",
                        "capability_id": "midpoint_point",
                        "args": {
                            "midpoint_definition": {
                                "ref": "F_midpoint_of_DN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive the midpoint",
                        "reason": "use the two resolved endpoints",
                    },
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=(),
    )

    assert result.ok
    object_refs = {
        call.call_id: tuple(item.object_ref for item in call.returns)
        for call in result.calls
    }
    assert object_refs == {
        "derive_axis": ("point:problem:D",),
        "construct_unknown_point": ("point:ii:N",),
        "derive_midpoint": ("point:ii:F",),
    }
    repairs = result.elaboration["deterministic_repairs"]
    assert [item["action"] for item in repairs].count(
        "auto_bind_target_object"
    ) == 3


def test_reconciler_propagates_unique_downstream_object_identity() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii_2")
    derive_point = next(
        item for item in scope["calls"] if item["call_id"] == "ii_2_derive_G"
    )
    derive_point["args"].pop("parameter_value")
    derive_point["return_bindings"] = {}
    scope["calls"].append(
        {
            "call_id": "ii_2_evaluate_G",
            "capability_id": "evaluate_point_at_parameter",
            "args": {
                "point": {
                    "from_call": "ii_2_derive_G",
                    "return": "intersection",
                },
                "parameter_value": {
                    "from_call": "ii_2_solve_m",
                    "return": "parameter_value",
                },
            },
            "return_bindings": {
                "evaluated_point": {
                    "kind": "answer",
                    "ref": "ii_2.intersection",
                }
            },
            "strategy": "substitute the solved parameter into the point",
            "reason": "finish the coordinate state of the same target point",
        }
    )
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    canonical = next(
        item for item in result.plan.calls if item.call_id == "ii_2_derive_G"
    )
    assert canonical.return_bindings["intersection"] == SemanticRef(
        ref="G",
        kind="point",
        value_type="Point",
    )
    assert any(
        item["action"] == "propagate_downstream_object_identity"
        and item["call_id"] == "ii_2_derive_G"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_promotes_unique_value_return_to_required_answer() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "i_derive_parabola"
    )
    call["return_bindings"] = {
        "parabola": {"kind": "function", "ref": "parabola"}
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok
    rebound = next(
        call for call in result.plan.calls if call.call_id == "i_derive_parabola"
    )
    assert rebound.return_bindings["parabola"] == SemanticRef(
        ref="i.parabola",
        kind="answer",
        value_type="Parabola",
    )
    assert any(
        item["action"] == "bind_unique_required_answer"
        and item["call_id"] == "i_derive_parabola"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_promotes_existing_point_binding_to_target_answer() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_x_intercept_A_i"
    )
    call["return_bindings"] = {
        "point": {"kind": "point", "ref": "problem.A"}
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    rebound = next(
        item
        for item in result.plan.calls
        if item.call_id == "derive_x_intercept_A_i"
    )
    assert rebound.return_bindings["point"] == SemanticRef(
        ref="i_1.A",
        kind="answer",
        value_type="Point",
    )
    assert any(
        item["action"] == "bind_resolved_object_state_to_required_answer"
        and item["call_id"] == "derive_x_intercept_A_i"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_normalizes_exact_question_goal_ref_with_object_kind() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    expected = {
        "derive_vertex_P_i": "i_1.P",
        "derive_x_intercept_A_i": "i_1.A",
    }
    for scope in payload["scopes"]:
        for call in scope["calls"]:
            answer_ref = expected.get(call["call_id"])
            if answer_ref is not None:
                call["return_bindings"] = {
                    "point": {"kind": "point", "ref": answer_ref}
                }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert not any(
        item.code == "functional.return_binding_unknown"
        and item.call_id in expected
        for item in result.issues
    ), [item.to_payload() for item in result.issues]
    by_id = {call.call_id: call for call in result.plan.calls}
    for call_id, answer_ref in expected.items():
        assert by_id[call_id].return_bindings["point"] == SemanticRef(
            ref=answer_ref,
            kind="answer",
            value_type="Point",
        )
    repairs = result.elaboration["deterministic_repairs"]
    assert set(expected).issubset({
        item["call_id"]
        for item in repairs
        if item["action"] == "normalize_question_goal_binding_kind"
    })


def test_reconciler_binds_terminal_object_state_to_required_answer() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "recover_target_point_E_ii"
    )
    call["capability_id"] = "evaluate_point_at_parameter"
    call["args"] = {
        "point": {
            "from_call": "parameterize_axis_point_E_ii",
            "return": "point",
        },
        "parameter_value": {
            "from_call": "solve_parameter_c_ii",
            "return": "parameter_value",
        },
    }
    call["return_bindings"] = {}
    call.pop("return_expectations", None)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    answer_calls = [
        item
        for item in result.plan.calls
        if any(
            binding.kind == "answer" and binding.ref == "ii.E"
            for binding in item.return_bindings.values()
        )
    ]
    assert len(answer_calls) == 1
    allocation = next(
        item
        for resolved in result.calls
        for item in resolved.returns
        if item.handle == "answer:ii.E"
    )
    assert allocation.handle == "answer:ii.E"
    answer_repairs = [
        item
        for item in result.elaboration["deterministic_repairs"]
        if "answer" in item["action"]
    ]
    assert any(
        item["action"] == "bind_resolved_object_state_to_required_answer"
        for item in answer_repairs
    ), answer_repairs


def test_answer_target_object_scope_constrains_runtime_placement() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    first_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "i_1"
    )
    shared_calls = [
        call
        for call in first_scope["calls"]
        if call["call_id"] in {"derive_parabola_i", "derive_vertex_P_i"}
    ]
    first_scope["calls"] = [
        call
        for call in first_scope["calls"]
        if call["call_id"] not in {"derive_parabola_i", "derive_vertex_P_i"}
    ]
    payload["scopes"].insert(
        0,
        {"scope_id": "i", "label": "shared i", "calls": shared_calls},
    )
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    placement = next(
        item
        for item in result.call_placements
        if item.canonical_call_id == "derive_vertex_P_i"
    )
    assert placement.declared_scope_id == "i"
    assert placement.execution_scope_id == "i_1"
    assert placement.return_scopes["point"] == "i_1"
    assert result.projected_draft is not None
    projected = next(
        step
        for step in result.projected_draft.steps
        if step.step_id == "derive_vertex_P_i"
    )
    assert projected.scope_id == "i_1"


def test_identity_constraint_infers_unique_target_object_return() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_minimum_point_G_ii"
    )
    call["return_bindings"] = {}
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    effective = next(
        item
        for item in result.plan.calls
        if item.call_id == "derive_minimum_point_G_ii"
    )
    assert effective.return_bindings["point"] == SemanticRef(
        ref="ii.G",
        kind="point",
        value_type="Point",
    )
    assert any(
        item["action"] == "infer_return_identity_from_contract"
        and item["call_id"] == "derive_minimum_point_G_ii"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_required_goal_unbound_identifies_object_producer_for_graph_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    payload = json.loads(HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_x_intercept_A_i"
    )
    call["return_bindings"] = {
        "point": {"kind": "point", "ref": "problem.A"}
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    def skip_answer_binding(
        _plan: FunctionalPlan,
        **kwargs: Any,
    ) -> tuple[
        dict[str, FunctionalCall],
        list[FunctionalCallReconciliation],
        tuple[object, ...],
    ]:
        return (
            dict(kwargs["effective_calls"]),
            list(kwargs["reconciled"]),
            (),
        )

    monkeypatch.setattr(
        functional_reconciliation_module,
        "_bind_unique_resolved_object_answers",
        skip_answer_binding,
    )
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    issue = next(
        item
        for item in result.issues
        if item.code == "functional.required_goal_unbound"
        and item.details["answer_handle"] == "answer:i_1.A"
    )
    assert issue.call_id == "derive_x_intercept_A_i"
    assert issue.details["candidate_producer_call_ids"] == [
        "derive_x_intercept_A_i"
    ]
    assert issue.details["repair_call_ids"] == ["derive_x_intercept_A_i"]
    assert "derive_x_intercept_A_i" in strategy_replay_module._root_repair_call_ids(
        result
    )


def test_reconciler_drops_unknown_answer_binding_from_consumed_intermediate() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_derive_path_model"
    )
    call["return_bindings"] = {
        "path_minimum_expression": {
            "kind": "answer",
            "ref": "ii_2.temporary_expression",
            "value_type": "MinimumExpression",
        }
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok
    rebound = next(
        call
        for call in result.plan.calls
        if call.call_id == "ii_derive_path_model"
    )
    assert rebound.return_bindings == {}
    assert any(
        item["action"] == "drop_unknown_intermediate_answer_binding"
        and item["call_id"] == "ii_derive_path_model"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_right_angle_macro_projection_is_structured_and_read_closed() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok
    call = next(
        item for item in result.calls if item.call_id == "ii_construct_N"
    )
    assert call.reads_closed
    assert set(call.resolved_args) == {
        "right_angle_equal_length",
        "anchor",
        "reference",
        "target",
        "quadrant",
        "parameter",
        "parameter_constraint",
    }
    step = next(
        item
        for item in result.projected_draft.steps
        if item.step_id == "ii_construct_N"
    )
    assert step.reads == (
        "fact:ii:right_angle_equal_length_MDN",
        "answer:i.axis_point",
        "point:problem:D",
        "fact:ii:M_coordinate_expr",
        "point:ii:M",
        "point:ii:N",
        "fact:ii:N_fourth_quadrant",
        "symbol:problem:m",
        "fact:problem:m_gt_2",
    )
    assert not any(
        token in handle
        for handle in step.reads
        for token in ("segment_E", "segment_G", "F_", "N_on_parabola")
    )


def test_path_reduction_projects_one_structured_state_for_downstream_macros() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok
    reduction = next(
        item for item in result.calls if item.call_id == "ii_reduce_path"
    )
    assert reduction.reads_closed
    assert set(reduction.resolved_args) == {
        "path_minimum_target",
        "first_moving_membership",
        "second_moving_membership",
        "binding_relation",
        "first_segment_start",
        "joint_point",
        "second_segment_end",
    }
    reduction_step = next(
        item
        for item in result.projected_draft.steps
        if item.step_id == "ii_reduce_path"
    )
    assert reduction_step.scope_id == "ii"
    transformation = reduction_step.produces[0]
    assert transformation.output_type == "PathTransformation"
    assert transformation.valid_scope == "ii"

    for call_id in ("ii_derive_path_model",):
        call = next(item for item in result.calls if item.call_id == call_id)
        step = next(
            item
            for item in result.projected_draft.steps
            if item.step_id == call_id
        )
        assert call.reads_closed
        assert tuple(call.resolved_args) == ("path_transformation",)
        assert step.reads == (transformation.handle,)


def test_functional_projected_arg_sidecar_only_exports_wire_selected_args() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert reconciliation.ok, [
        item.to_payload() for item in reconciliation.issues
    ]
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    bindings = strategy_replay_module._functional_projected_arg_bindings(
        reconciliation,
        catalog=catalog,
    )
    names_by_call: dict[str, set[str]] = {}
    for binding in bindings:
        names_by_call.setdefault(binding.step_id, set()).add(binding.arg_name)

    assert names_by_call["ii_construct_N"] == {"right_angle_equal_length"}
    assert "parameter_value" in names_by_call["ii_2_derive_G"]
    assert "parameter" not in names_by_call["ii_2_derive_G"]


def test_functional_compile_uses_named_sidecar_after_flat_reads_are_reordered() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_2_derive_G"
    )
    call["args"]["line2_p1"], call["args"]["line2_p2"] = (
        call["args"]["line2_p2"],
        call["args"]["line2_p1"],
    )
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert reconciliation.ok, [
        item.to_payload() for item in reconciliation.issues
    ]
    assert reconciliation.projected_draft is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    sidecar = strategy_replay_module._functional_projected_arg_bindings(
        reconciliation,
        catalog=catalog,
    )
    exact = {
        item.arg_name: item
        for item in sidecar
        if item.step_id == "ii_2_derive_G"
    }
    first = exact["line2_p1"].source_handle
    second = exact["line2_p2"].source_handle
    steps = []
    for step in reconciliation.projected_draft.steps:
        if step.step_id != "ii_2_derive_G":
            steps.append(step)
            continue
        reordered_reads = (
            second,
            first,
            *(handle for handle in step.reads if handle not in {first, second}),
        )
        steps.append(replace(step, reads=reordered_reads))
    steps_by_id = {step.step_id: step for step in steps}
    draft = replace(
        reconciliation.projected_draft,
        scopes=tuple(
            replace(
                scope,
                steps=tuple(steps_by_id[step.step_id] for step in scope.steps),
            )
            for scope in reconciliation.projected_draft.scopes
        ),
    )

    output, diagnostic, _effective = RecipeTrialExecutor().diagnose(
        draft,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        question_goals=inputs.question_goals,
        allow_shared_derivation_scopes=True,
        preserve_call_graph=True,
        projected_state_writes=(
            strategy_replay_module._functional_projected_state_writes(
                reconciliation
            )
        ),
        projected_function_arg_bindings=sidecar,
    )
    assert output is not None, diagnostic.to_payload()
    invocation = next(
        invocation
        for step_plan in output.step_plans
        for invocation in step_plan.invocations
        if invocation.method_id == "line_intersection_point"
    )
    assert invocation.inputs["line2_p1"] == "$question.ii.points.N"
    assert invocation.inputs["line2_p2"] == "$question.ii.points.M"


def test_nankai_student_narrative_uses_question_scopes_not_execution_scopes() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert result.ok, [item.to_payload() for item in result.issues]

    narrative = StudentNarrativePlacementProjector().project(
        effective_steps=tuple(
            step.to_payload(include_scope_id=True)
            for step in result.projected_draft.steps
        ),
        problem=_problem_payload(),
        functional_reconciliation=result,
        raw_functional_plan=plan,
    )
    placements = {item.step_id: item for item in narrative.placements}

    assert placements["i_derive_D"].presentation_scope_id == "i"
    assert placements["ii_reduce_path"].presentation_scope_id == "ii"
    assert placements["ii_derive_path_model"].presentation_scope_id == "ii"
    assert placements["ii_1_evaluate_minimum"].presentation_scope_id == "ii_1"
    assert placements["ii_2_derive_G"].presentation_scope_id == "ii_2"
    assert all(
        item.presentation_scope_id != "problem" for item in narrative.placements
    )
    assert list(
        dict.fromkeys(item.presentation_scope_id for item in narrative.placements)
    ) == ["i", "ii", "ii_1", "ii_2"]
    assert any(
        item.source_step_id == "i_derive_D"
        and item.target_step_id == "ii_construct_N"
        and item.source_scope_id == "i"
        and item.target_scope_id == "ii"
        for item in narrative.references
    )

    shadow_context = PlannerStateContextBuilder.from_replay_result(
        PlannerRetryReplayResult(
            attempt=1,
            effective_draft=result.projected_draft,
            functional_plan=plan,
            functional_reconciliation=result,
        ),
        inputs=inputs,
        problem_payload=_problem_payload(),
        handle_registry=_registry(),
    )
    assert shadow_context.state.student_step_placements == tuple(
        item.to_payload() for item in narrative.placements
    )
    assert shadow_context.state.student_scope_references == tuple(
        item.to_payload() for item in narrative.references
    )

    lesson = ExplanationBuilder().build_lesson(
        ExplanationSnapshot(
            problem_id=inputs.problem_id,
            family_id=inputs.family_spec.family_id,
            problem=_problem_payload(),
            effective_steps=tuple(
                step.to_payload(include_scope_id=True)
                for step in result.projected_draft.steps
            ),
            teaching_trace=(),
            fact_index={},
            student_step_placements=narrative.placements,
            student_scope_references=narrative.references,
        )
    )
    assert [section.scope_id for section in lesson.sections] == [
        "i",
        "ii",
        "ii_1",
        "ii_2",
    ]
    assert any(
        item == ("由", "第（Ⅰ）问已得点 D，继续计算")
        for step in lesson.steps
        for item in step.derive
    )


def test_student_narrative_keeps_legacy_step_intent_scope_identity() -> None:
    narrative = StudentNarrativePlacementProjector().project(
        effective_steps=(
            {
                "step_id": "legacy_step",
                "scope_id": "ii_1",
                "reads": [],
                "creates": [],
                "produces": [],
            },
        ),
        problem=_problem_payload(),
    )

    assert narrative.references == ()
    assert narrative.placements[0].execution_scope_id == "ii_1"
    assert narrative.placements[0].presentation_scope_id == "ii_1"
    assert narrative.placements[0].placement_reason == "legacy_step_intent"


def test_nankai_duplicate_sibling_path_reduction_is_placed_and_shared() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scopes = {item["scope_id"]: item for item in payload["scopes"]}
    original_id = "ii_reduce_path"
    duplicate_id = "ii_2_path_reduction_duplicate"
    original = next(
        call for call in scopes["ii"]["calls"] if call["call_id"] == original_id
    )
    duplicate = json.loads(json.dumps(original))
    duplicate["call_id"] = duplicate_id
    duplicate["strategy"] = "repeat the shared path reduction in the second question"
    duplicate["reason"] = "exercise deterministic sibling sharing"

    def rewrite_call_result_refs(value: object) -> None:
        if isinstance(value, dict):
            if value.get("from_call") == original_id:
                value["from_call"] = duplicate_id
            for child in value.values():
                rewrite_call_result_refs(child)
        elif isinstance(value, list):
            for child in value:
                rewrite_call_result_refs(child)

    for call in scopes["ii_2"]["calls"]:
        rewrite_call_result_refs(call)
    scopes["ii_2"]["calls"].insert(0, duplicate)

    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.call_aliases[duplicate_id] == original_id
    assert duplicate_id not in {call.call_id for call in result.plan.calls}
    assert duplicate_id not in json.dumps(
        result.to_payload()["effective_plan"],
        sort_keys=True,
    )
    placement = next(
        item for item in result.call_placements if item.canonical_call_id == original_id
    )
    assert placement.alias_call_ids == (duplicate_id,)
    assert placement.declared_scope_id == "ii"
    assert placement.execution_scope_id == "ii"
    assert placement.return_scopes == {"path_transformation": "ii"}
    assert f'"from_call": "{duplicate_id}"' not in json.dumps(
        result.plan.to_payload(),
        sort_keys=True,
    )
    step = next(
        item for item in result.projected_draft.steps if item.step_id == original_id
    )
    assert step.scope_id == "ii"
    assert step.produces[0].valid_scope == "ii"
    projection = next(
        item for item in result.projection_map if item.call_id == original_id
    )
    assert duplicate_id not in {item.call_id for item in result.projection_map}
    assert projection.alias_call_ids == (duplicate_id,)
    assert projection.declared_scope_id == "ii"
    assert projection.execution_scope_id == "ii"

    shadow_context = PlannerStateContextBuilder.from_replay_result(
        PlannerRetryReplayResult(
            attempt=1,
            functional_plan=plan,
            functional_reconciliation=result,
        ),
        inputs=inputs,
        problem_payload=_problem_payload(),
        handle_registry=_registry(),
    )
    timeline_call = next(
        item
        for item in shadow_context.state.functional_call_timeline
        if item["call_id"] == original_id
    )
    assert timeline_call["placement"]["alias_call_ids"] == [duplicate_id]
    assert timeline_call["placement"]["execution_scope_id"] == "ii"
    assert duplicate_id in json.dumps(
        shadow_context.state.raw_functional_plan_snapshot,
        sort_keys=True,
    )
    assert duplicate_id not in json.dumps(
        shadow_context.state.functional_plan_snapshot,
        sort_keys=True,
    )

    runtime_replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        errors=("synthetic retry request",),
        problem_payload=_problem_payload(),
        validation_report=validation,
    )
    assert runtime_replay.output is not None
    assert runtime_replay.effective_draft is not None
    assert runtime_replay.functional_reconciliation is not None
    result_forms = {
        (item.call_id, item.return_name): item
        for item in runtime_replay.functional_reconciliation.result_form_events
    }
    assert result_forms[
        ("ii_derive_path_model", "path_minimum_expression")
    ].actual_form == "open_expression"
    assert result_forms[
        ("ii_1_evaluate_minimum", "evaluated_minimum_expression")
    ].actual_form == "closed_value"
    effective_step_ids = [
        step.step_id for step in runtime_replay.effective_draft.steps
    ]
    assert len(effective_step_ids) == len(set(effective_step_ids))
    assert duplicate_id not in effective_step_ids
    assert duplicate_id not in {
        step.step_id for step in runtime_replay.output.step_plans
    }
    assert runtime_replay.retry_state is not None
    assert duplicate_id not in json.dumps(
        runtime_replay.retry_state.baseline_candidate,
        sort_keys=True,
    )

    replayed = FunctionalPlanReconciler().reconcile(
        result.plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert replayed.ok, [item.to_payload() for item in replayed.issues]
    assert replayed.projected_draft.to_payload() == (
        result.projected_draft.to_payload()
    )


def test_sibling_path_reduction_preserves_published_input_scope_when_hoisted() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scopes = {item["scope_id"]: item for item in payload["scopes"]}
    shared_calls = scopes["ii"]["calls"]
    reduction = next(
        call for call in shared_calls if call["call_id"] == "ii_reduce_path"
    )
    path_model = next(
        call
        for call in shared_calls
        if call["call_id"] == "ii_derive_path_model"
    )
    shared_calls.remove(reduction)
    shared_calls.remove(path_model)

    first_id = "reduce_path_ii1"
    duplicate_id = "reduce_path_ii2"
    first_model_id = "path_model_ii1"
    duplicate_model_id = "path_model_ii2"
    first_reduction = json.loads(json.dumps(reduction))
    first_reduction["call_id"] = first_id
    duplicate_reduction = json.loads(json.dumps(reduction))
    duplicate_reduction["call_id"] = duplicate_id
    first_model = json.loads(json.dumps(path_model))
    first_model["call_id"] = first_model_id
    first_model["args"]["path_transformation"]["from_call"] = first_id
    duplicate_model = json.loads(json.dumps(path_model))
    duplicate_model["call_id"] = duplicate_model_id
    duplicate_model["args"]["path_transformation"]["from_call"] = duplicate_id

    def rewrite_call_refs(value: object, replacements: dict[str, str]) -> None:
        if isinstance(value, dict):
            source = value.get("from_call")
            if isinstance(source, str) and source in replacements:
                value["from_call"] = replacements[source]
            for child in value.values():
                rewrite_call_refs(child, replacements)
        elif isinstance(value, list):
            for child in value:
                rewrite_call_refs(child, replacements)

    rewrite_call_refs(
        scopes["ii_1"]["calls"],
        {"ii_derive_path_model": first_model_id},
    )
    rewrite_call_refs(
        scopes["ii_2"]["calls"],
        {
            "ii_reduce_path": duplicate_id,
            "ii_derive_path_model": duplicate_model_id,
        },
    )
    scopes["ii_1"]["calls"][0:0] = [first_reduction, first_model]
    scopes["ii_2"]["calls"][0:0] = [duplicate_reduction, duplicate_model]

    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.call_aliases[duplicate_id] == first_id
    placement = next(
        item for item in result.call_placements if item.canonical_call_id == first_id
    )
    assert placement.declared_scope_id == "ii_1"
    assert placement.execution_scope_id == "ii"
    assert placement.return_scopes == {"path_transformation": "ii"}
    projected = next(
        step for step in result.projected_draft.steps if step.step_id == first_id
    )
    assert projected.scope_id == "ii"
    assert projected.produces[0].valid_scope == "ii"


def test_nankai_redundant_existing_object_write_reuses_answer_producer() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scopes = {item["scope_id"]: item for item in payload["scopes"]}
    duplicate_ids = ("ii_1_derive_D_again", "ii_2_derive_D_again")
    for scope_id, duplicate_id in zip(("ii_1", "ii_2"), duplicate_ids):
        scopes[scope_id]["calls"].insert(0, {
            "call_id": duplicate_id,
            "capability_id": "quadratic_axis_from_relation",
            "args": {
                "coefficient_relation": {
                    "ref": "coefficient_relation",
                    "kind": "fact",
                }
            },
            "return_bindings": {
                "axis_point": {"ref": "D", "kind": "point"}
            },
            "strategy": "derive the already-computed axis point again",
            "reason": "exercise deterministic existing-state reuse",
        })
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert all(
        result.call_aliases[duplicate_id] == "i_derive_D"
        for duplicate_id in duplicate_ids
    )
    assert not set(duplicate_ids) & {call.call_id for call in result.plan.calls}
    assert not set(duplicate_ids) & {
        step.step_id for step in result.projected_draft.steps
    }
    owner = next(
        item
        for item in result.call_placements
        if item.canonical_call_id == "i_derive_D"
    )
    assert set(owner.alias_call_ids) == set(duplicate_ids)
    assert owner.execution_scope_id == "problem"
    assert owner.return_scopes == {"axis_point": "problem"}
    for duplicate_id in duplicate_ids:
        assert any(
            item["action"].startswith("merge_")
            and item["call_id"] == duplicate_id
            for item in result.elaboration["deterministic_repairs"]
        )

    narrative = StudentNarrativePlacementProjector().project(
        effective_steps=tuple(
            step.to_payload(include_scope_id=True)
            for step in result.projected_draft.steps
        ),
        problem=_problem_payload(),
        functional_reconciliation=result,
        raw_functional_plan=plan,
    )
    narrative_steps = {item.step_id: item for item in narrative.placements}
    assert not set(duplicate_ids) & set(narrative_steps)
    assert narrative_steps["i_derive_D"].execution_scope_id == "problem"
    assert narrative_steps["i_derive_D"].presentation_scope_id == "i"


def test_midpoint_condition_reconciles_target_identity_before_runtime() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    registry = _registry()
    context = _context(inputs)

    def reconcile(return_bindings: dict) -> object:
        payload = {
            "format": "functional_plan/v1",
            "scopes": [
                {
                    "scope_id": "ii",
                    "label": "ii",
                    "calls": [
                        {
                            "call_id": "derive_axis",
                            "capability_id": "quadratic_axis_from_relation",
                            "args": {
                                "coefficient_relation": {
                                    "ref": "coefficient_relation",
                                    "kind": "fact",
                                }
                            },
                            "return_bindings": {},
                            "strategy": "derive the axis point",
                            "reason": "materialize the first midpoint endpoint",
                        },
                        {
                            "call_id": "construct_unknown_point",
                            "capability_id": (
                                "right_angle_equal_length_construct_and_select"
                            ),
                            "args": {
                                "right_angle_equal_length": {
                                    "ref": "right_angle_equal_length_MDN",
                                    "kind": "fact",
                                }
                            },
                            "return_bindings": {},
                            "strategy": "construct the second endpoint",
                            "reason": "materialize the second midpoint endpoint",
                        },
                        {
                            "call_id": "derive_midpoint",
                            "capability_id": "midpoint_point",
                            "args": {
                                "midpoint_definition": {
                                    "ref": "F_midpoint_of_DN",
                                    "kind": "fact",
                                }
                            },
                            "return_bindings": return_bindings,
                            "strategy": "derive the structurally defined midpoint",
                            "reason": "the condition determines endpoint and target roles",
                        }
                    ],
                }
            ],
        }
        plan, report = _validate(payload, inputs)
        assert report.ok and plan is not None
        return FunctionalPlanReconciler().reconcile(
            plan,
            planner_state_context=context,
            family_spec=inputs.family_spec,
            method_specs=inputs.method_specs,
            handle_registry=registry,
            question_goals=(),
        )

    valid = reconcile({})
    assert valid.ok
    assert valid.calls[-1].returns[0].object_ref == "point:ii:F"

    mismatched = reconcile(
        {"midpoint": {"ref": "D", "kind": "point"}}
    )
    identity_issues = [
        item
        for item in mismatched.issues
        if item.code == "functional.return_identity_mismatch"
    ]
    assert identity_issues, [
        (item.code, item.details) for item in mismatched.issues
    ]
    mismatch = identity_issues[0]
    assert mismatch.details == {
        "return": "midpoint",
        "bound_ref": "D",
        "inferred_ref": "F",
        "semantic_role": "midpoint",
    }


def test_explicit_intersection_answer_is_not_overridden_by_unrelated_object_relation() -> None:
    """Input endpoints alone do not turn their structurally related midpoint into the target."""
    inputs = _inputs_for_goal(5)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    {
                        "call_id": "derive_intersection",
                        "capability_id": "line_intersection_point",
                        "args": {
                            "line1_p1": {"ref": "M", "kind": "point"},
                            "line1_p2": {"ref": "N", "kind": "point"},
                            "line2_p1": {"ref": "D", "kind": "point"},
                            "line2_p2": {"ref": "F", "kind": "point"},
                        },
                        "return_bindings": {
                            "intersection": {
                                "ref": "ii_2.intersection",
                                "kind": "answer",
                            }
                        },
                        "strategy": "intersect two explicitly defined lines",
                        "reason": "the output identity is declared by the answer binding",
                    }
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert not [
        issue
        for issue in result.issues
        if issue.code == "functional.return_identity_mismatch"
    ]
    intersection = result.calls[0].returns[0]
    assert intersection.handle == "answer:ii_2.intersection"
    assert intersection.object_ref == "point:ii:G"


def test_explicit_answer_producer_takes_priority_over_object_to_answer_promotion() -> None:
    """An earlier reusable object write must not steal a later explicit answer binding."""
    inputs = _inputs_for_goal(0)
    axis_call = {
        "capability_id": "quadratic_axis_from_relation",
        "args": {
            "coefficient_relation": {
                "ref": "coefficient_relation",
                "kind": "fact",
            }
        },
        "strategy": "derive the shared axis point",
        "reason": "the coefficient relation determines its coordinate",
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "problem",
                "label": "problem",
                "calls": [
                    {
                        **axis_call,
                        "call_id": "derive_shared_axis_point",
                        "return_bindings": {
                            "axis_point": {"ref": "D", "kind": "point"}
                        },
                    }
                ],
            },
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        **axis_call,
                        "call_id": "bind_axis_answer",
                        "return_bindings": {
                            "axis_point": {
                                "ref": "i.axis_point",
                                "kind": "answer",
                            }
                        },
                    }
                ],
            },
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert not [
        issue
        for issue in result.issues
        if issue.code == "functional.answer_duplicate"
    ]
    answer_returns = [
        item
        for call in result.calls
        for item in call.returns
        if item.handle == "answer:i.axis_point"
    ]
    assert len(answer_returns) == 1


def test_point_identity_path_preserves_coordinate_and_object_roles() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=(),
    )

    assert index.point_identity_path_for("point:ii:A") == (
        "$question.ii.points.A"
    )
    with pytest.raises(
        StrategyDraftValidationError,
        match="duplicate_point_coordinate_fact",
    ):
        index.point_ref_path_for("point:ii:A")


@pytest.mark.parametrize(
    ("first_expectation", "second_expectation", "expect_conflict"),
    (
        ("open_expression", None, False),
        ("open_expression", "closed_value", True),
    ),
)
def test_reconciler_merges_compatible_result_expectations_only(
    first_expectation: str,
    second_expectation: str | None,
    expect_conflict: bool,
) -> None:
    inputs = _base_inputs()
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "derive_axis",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive the axis point",
                        "reason": "provide the known point state",
                    },
                    {
                        "call_id": "construct_point",
                        "capability_id": (
                            "right_angle_equal_length_construct_and_select"
                        ),
                        "args": {
                            "right_angle_equal_length": {
                                "ref": "right_angle_equal_length_MDN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "construct the selected point",
                        "reason": "provide its current coordinate state",
                    },
                    _path_reduction_call(),
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    {
                        "call_id": "derive_minimum_from_object_ref",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                            },
                            "return_bindings": {},
                            "return_expectations": {
                                "path_minimum_expression": first_expectation,
                            },
                            "strategy": "derive the minimum state",
                        "reason": "use the current object views",
                    },
                    {
                        "call_id": "derive_minimum_from_call_ref",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                            },
                            "return_bindings": {},
                            **(
                                {
                                    "return_expectations": {
                                        "path_minimum_expression": second_expectation,
                                    }
                                }
                                if second_expectation is not None
                                else {}
                            ),
                            "strategy": "repeat the same state transform",
                        "reason": "exercise resolved-state deduplication",
                    },
                ],
            },
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=(),
    )

    if expect_conflict:
        assert "functional.return_expectation_conflict" in {
            item.code for item in result.issues
        }
        assert "derive_minimum_from_call_ref" not in {
            call.call_id for call in result.plan.calls
        }
        assert result.partial_projected_draft is not None
        assert [
            step.step_id for step in result.partial_projected_draft.steps
        ].count("derive_minimum_from_object_ref") == 1
        assert any(
            item["action"] == "isolate_conflicting_equivalent_call"
            for item in result.elaboration["deterministic_repairs"]
        )
        return
    assert result.ok
    assert [call.call_id for call in result.plan.calls].count(
        "derive_minimum_from_object_ref"
    ) == 1
    assert "derive_minimum_from_call_ref" not in {
        call.call_id for call in result.plan.calls
    }
    canonical = next(
        call
        for call in result.plan.calls
        if call.call_id == "derive_minimum_from_object_ref"
    )
    assert canonical.return_expectations == {
        "path_minimum_expression": "open_expression"
    }
    assert any(
        item["action"] == "merge_equivalent_capability_call"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_collects_all_call_contract_errors() -> None:
    inputs = _inputs_for_goal(0)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "bad_midpoint",
                        "capability_id": "midpoint_point",
                        "args": {
                            "midpoint_definition": [
                                {
                                    "ref": "F_midpoint_of_DN",
                                    "kind": "fact",
                                },
                                {
                                    "ref": "F_midpoint_of_DN",
                                    "kind": "fact",
                                },
                            ],
                            "invented": {"ref": "A", "kind": "point"},
                        },
                        "return_bindings": {
                            "midpoint": {"ref": "i.axis_point", "kind": "answer"}
                        },
                        "strategy": "bad call for validation",
                        "reason": "exercise all contract checks",
                    }
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert {item.code for item in result.issues} >= {
        "functional.arg_unknown",
        "functional.arg_cardinality",
    }


def test_reconciler_reuses_pure_object_state_across_sibling_scopes() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    first = _axis_plan_payload()["scopes"][0]["calls"][0]
    first["return_bindings"] = {
        "axis_point": {"ref": "D", "kind": "point"}
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [first],
            },
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "derive_axis_point_again",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": first["args"],
                        "return_bindings": {
                            "axis_point": {"ref": "D", "kind": "point"}
                        },
                        "strategy": "repeat the same pure derivation",
                        "reason": "reuse D in another question scope",
                    },
                    {
                        "call_id": "consume_shared_d",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {"ref": "D", "kind": "point"},
                            "p2": {"ref": "D", "kind": "point"},
                        },
                        "return_bindings": {},
                        "strategy": "consume the shared problem object",
                        "reason": "make the cross-scope value visibility explicit",
                    },
                ],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.calls[0].returns[0].valid_scope == "problem"
    assert [call.call_id for call in result.plan.calls] == [
        "derive_axis_point",
        "consume_shared_d",
    ]
    assert result.call_aliases == {
        "derive_axis_point_again": "derive_axis_point"
    }
    placement = result.call_placements[0]
    assert placement.alias_call_ids == ("derive_axis_point_again",)
    assert placement.execution_scope_id == "problem"
    assert any(
        item["action"] in {
            "merge_equivalent_object_call",
            "merge_resolved_equivalent_call",
        }
        and item["call_id"] == "derive_axis_point_again"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_reuses_answer_producer_for_same_object_state_write() -> None:
    inputs = _inputs_for_goal(0)
    answer_call = _axis_plan_payload()["scopes"][0]["calls"][0]
    object_call = json.loads(json.dumps(answer_call))
    object_call["call_id"] = "derive_axis_point_for_object"
    object_call["return_bindings"] = {
        "axis_point": {"ref": "D", "kind": "point"}
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {"scope_id": "i", "label": "i", "calls": [answer_call]},
            {"scope_id": "ii", "label": "ii", "calls": [object_call]},
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.call_aliases == {
        "derive_axis_point_for_object": "derive_axis_point"
    }
    assert [call.call_id for call in result.plan.calls] == ["derive_axis_point"]
    assert any(
        item["action"] == "merge_redundant_existing_state_call"
        and item["call_id"] == "derive_axis_point_for_object"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_transfers_later_answer_to_earliest_object_producer() -> None:
    inputs = _inputs_for_goal(0)
    answer_call = _axis_plan_payload()["scopes"][0]["calls"][0]
    global_call = json.loads(json.dumps(answer_call))
    global_call["call_id"] = "derive_axis_point_globally"
    global_call["return_bindings"] = {
        "axis_point": {"ref": "D", "kind": "point"}
    }
    sibling_call = json.loads(json.dumps(global_call))
    sibling_call["call_id"] = "derive_axis_point_again_in_ii"
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "problem",
                "label": "shared preparation",
                "calls": [global_call],
            },
            {"scope_id": "i", "label": "i", "calls": [answer_call]},
            {"scope_id": "ii", "label": "ii", "calls": [sibling_call]},
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.call_aliases == {
        "derive_axis_point": "derive_axis_point_globally",
        "derive_axis_point_again_in_ii": "derive_axis_point_globally",
    }
    assert [call.call_id for call in result.plan.calls] == [
        "derive_axis_point_globally"
    ]
    owner = result.plan.calls[0]
    assert owner.return_bindings == {
        "axis_point": SemanticRef(
            ref="i.axis_point",
            kind="answer",
            value_type="Point",
        )
    }
    projected = result.projected_draft.steps
    assert len(projected) == 1
    assert projected[0].step_id == "derive_axis_point_globally"
    assert projected[0].target == "answer:i.axis_point"
    assert projected[0].produces[0].handle == "answer:i.axis_point"
    allocation = result.calls[0].returns[0]
    assert allocation.object_ref == "point:problem:D"
    assert allocation.valid_scope == "problem"
    assert any(
        item["action"] == "reuse_existing_state_for_answer"
        and item["call_id"] == "derive_axis_point"
        and item["to"] == "derive_axis_point_globally"
        for item in result.elaboration["deterministic_repairs"]
    )

    replayed = FunctionalPlanReconciler().reconcile(
        result.plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert replayed.ok, [item.to_payload() for item in replayed.issues]
    assert replayed.plan.to_payload() == result.plan.to_payload()
    assert replayed.projected_draft.to_payload() == result.projected_draft.to_payload()

    runtime_replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        errors=("synthetic retry request",),
        problem_payload=_problem_payload(),
        validation_report=report,
    )
    assert runtime_replay.output is not None
    assert runtime_replay.effective_draft is not None
    assert [step.step_id for step in runtime_replay.effective_draft.steps] == [
        "derive_axis_point_globally"
    ]
    assert runtime_replay.retry_state is not None
    baseline = runtime_replay.retry_state.baseline_candidate
    assert baseline is not None
    baseline_text = json.dumps(baseline, sort_keys=True)
    assert "derive_axis_point" not in baseline_text.replace(
        "derive_axis_point_globally",
        "",
    )
    assert "derive_axis_point_again_in_ii" not in baseline_text
    assert '"ref": "i.axis_point"' in baseline_text


def test_reconciler_reports_value_type_and_scope_errors_without_guessing() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["args"]["coefficient_relation"]["value_type"] = "Point"
    call["return_bindings"]["axis_point"]["value_type"] = "Parabola"
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    codes = {item.code for item in result.issues}
    assert "functional.arg_type_mismatch" in codes
    assert "functional.return_type_mismatch" in codes

    call["args"]["coefficient_relation"] = {
        "ref": "path_minimum_target",
        "kind": "fact",
    }
    call["return_bindings"]["axis_point"].pop("value_type")
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    invisible = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert "functional.arg_scope_invisible" in {
        item.code for item in invisible.issues
    }


def test_macro_call_projects_required_return_and_omits_unused_optional_returns() -> None:
    inputs = _inputs_for_goal(3)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    *_path_reduction_setup_calls(),
                    {
                        "call_id": "derive_path_minimum",
                        "capability_id": "broken_path_straightening_minimum_expression",
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                        },
                        "return_bindings": {
                            "path_minimum_expression": {
                                "ref": "ii_1.minimum_value",
                                "kind": "answer",
                            }
                        },
                        "strategy": "straighten the path and derive its minimum",
                        "reason": "satisfy the minimum-expression goal",
                    }
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.projected_draft is not None
    step = next(
        item
        for item in result.projected_draft.steps
        if item.step_id == "derive_path_minimum"
    )
    assert step.recipe_hint == "broken_path_straightening_minimum_expression"
    assert [item.handle for item in step.produces] == [
        "answer:ii_1.minimum_value"
    ]


def test_reconciler_selects_polymorphic_return_from_resolved_input_type() -> None:
    inputs = _inputs_for_goal(3)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    *_path_reduction_prerequisite_calls(),
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_segment_length",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {"ref": "N", "kind": "point"},
                            "length_squared": {
                                "ref": "MN_length_squared_eq_10",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parameter_value": {
                                "ref": "m",
                                "kind": "symbol",
                            }
                        },
                        "strategy": "solve the parameter",
                        "reason": "provide the parameter value state",
                    },
                    _path_reduction_call(),
                    {
                        "call_id": "derive_minimum_expression",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                        },
                        "return_bindings": {},
                        "strategy": "derive the symbolic minimum",
                        "reason": "provide a MinimumExpression state",
                    },
                    {
                        "call_id": "evaluate_minimum_expression",
                        "capability_id": "evaluate_expression_at_parameter",
                        "args": {
                            "expression": {
                                "from_call": "derive_minimum_expression",
                                "return": "path_minimum_expression",
                            },
                            "parameter_value": {
                                "from_call": "solve_parameter",
                                "return": "parameter_value",
                            },
                        },
                        "return_bindings": {
                            "evaluated_minimum_expression": {
                                "ref": "ii_1.minimum_value",
                                "kind": "answer",
                            }
                        },
                        "strategy": "evaluate the minimum expression",
                        "reason": "preserve the MinimumExpression view",
                    },
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.projected_draft is not None
    step = next(
        item
        for item in result.projected_draft.steps
        if item.step_id == "evaluate_minimum_expression"
    )
    assert [(item.handle, item.output_type) for item in step.produces] == [
        ("answer:ii_1.minimum_value", "MinimumExpression")
    ]
    finalized, _report = CanonicalDraftFinalizer().finalize(
        result.projected_draft,
        family_spec=inputs.family_spec,
        question_goals=inputs.question_goals,
        handle_registry=_registry(),
        allow_shared_derivation_scopes=True,
    )
    assert finalized.to_payload() == result.projected_draft.to_payload()


def test_reconciler_rewrites_polymorphic_parabola_return_and_binds_answer() -> None:
    inputs = _inputs_for_goal(2)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "derive_parametric_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": [
                                {"ref": "M", "kind": "point"},
                                {"ref": "N", "kind": "point"},
                            ],
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "derive the parameterized parabola",
                        "reason": "provide the state to specialize",
                    },
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_segment_length",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {"ref": "N", "kind": "point"},
                            "length_squared": {
                                "ref": "MN_length_squared_eq_10",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parameter_value": {"ref": "m", "kind": "symbol"}
                        },
                        "strategy": "solve the parameter",
                        "reason": "provide the value used for substitution",
                    },
                    {
                        "call_id": "evaluate_parabola",
                        "capability_id": "evaluate_expression_at_parameter",
                        "args": {
                            "expression": {
                                "from_call": "derive_parametric_parabola",
                                "return": "parabola",
                            },
                            "parameter_value": {
                                "from_call": "solve_parameter",
                                "return": "parameter_value",
                            },
                        },
                        "return_bindings": {
                            "evaluated_expression": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "strategy": "substitute the solved parameter",
                        "reason": "obtain the current question parabola",
                    },
                ],
            }
        ],
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, {
        "issues": [item.to_payload() for item in result.issues],
        "plan": result.plan.to_payload(),
        "elaboration": result.elaboration,
    }
    evaluated_call = next(
        call for call in result.plan.calls if call.call_id == "evaluate_parabola"
    )
    assert set(evaluated_call.return_bindings) == {"evaluated_parabola"}
    binding = evaluated_call.return_bindings["evaluated_parabola"]
    assert (binding.kind, binding.ref) == ("answer", "ii_1.parabola")
    assert any(
        item["action"] == "select_runtime_return_variant"
        for item in result.elaboration["deterministic_repairs"]
    )
    assert result.projected_draft is not None
    step = next(
        item
        for item in result.projected_draft.steps
        if item.step_id == "evaluate_parabola"
    )
    assert [(item.handle, item.output_type) for item in step.produces] == [
        ("answer:ii_1.parabola", "Parabola")
    ]


def test_elaborator_reclassifies_semantic_evidence_and_is_idempotent() -> None:
    inputs = _inputs_for_goal(1)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "solve_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "extra_equation": {
                                "ref": "a_value",
                                "kind": "fact",
                            },
                            "known_coefficients": {
                                "ref": "c_value",
                                "kind": "fact",
                            },
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "i.parabola",
                                "kind": "answer",
                            }
                        },
                        "strategy": "solve from the supplied evidence",
                        "reason": "derive the requested parabola",
                    }
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        _context(inputs),
        handle_registry=_registry(),
    )

    first = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=catalog,
        semantic_index=semantic_index,
    )
    call = first.plan.calls[0]
    assert {item.ref for item in call.args["known_coefficients"]} == {
        "a_value",
        "c_value",
    }
    assert "extra_equation" not in call.args
    assert first.aggregations == {
        "solve_parabola": {"known_coefficients": "coefficients_by_symbol"}
    }
    assert any(
        item.action == "reclassify_semantic_arg"
        for item in first.deterministic_repairs
    )

    second = FunctionalPlanElaborator().elaborate(
        first.plan,
        catalog=catalog,
        semantic_index=semantic_index,
    )
    assert second.plan.to_payload() == first.plan.to_payload()
    assert second.deterministic_repairs == ()


def test_elaborator_preserves_supplied_auto_arg_and_remains_idempotent() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_minimum_value",
                        "args": {
                            "minimum_expression": {
                                "ref": "path_minimum_expression",
                                "kind": "fact",
                            },
                            "minimum_value": {
                                "ref": "path_minimum_value_given",
                                "kind": "fact",
                            },
                            "parameter": {"ref": "m", "kind": "symbol"},
                        },
                        "return_bindings": {},
                        "strategy": "solve the parameter",
                        "reason": "use the minimum condition",
                    }
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    first = FunctionalPlanElaborator().elaborate(plan, catalog=catalog)
    assert "parameter" in first.plan.calls[0].args
    assert first.deterministic_repairs == ()

    second = FunctionalPlanElaborator().elaborate(first.plan, catalog=catalog)
    assert second.plan.to_payload() == first.plan.to_payload()
    assert second.deterministic_repairs == ()


def test_context_auto_override_must_match_unique_resolved_state() -> None:
    capability = SimpleNamespace(
        capability_id="synthetic_capability",
        auto_args=(
            SimpleNamespace(name="object_state", selector="function:curve"),
        ),
    )
    supplied = ResolvedFunctionalValue(
        handle="fact:part:curve_state_alias",
        runtime_type="Parabola",
        valid_scope="part",
        state_slot_id="function:part:curve.expression@part",
        object_ref="function:part:curve",
    )
    expected = replace(supplied, handle="fact:part:curve_state")

    additions, repairs, issues = (
        functional_reconciliation_module._reconcile_supplied_context_auto_args(
            capability,
            resolved_args={"object_state": (supplied,)},
            resolved_auto_args={"object_state": (expected,)},
            resolver_repairs=(),
            resolver_issues=(),
            supplied_names={"object_state"},
            call_id="consume_curve",
            scope_id="part",
        )
    )

    assert additions == {}
    assert issues == ()
    assert repairs[0].action == "absorb_equivalent_auto_arg_override"

    _, _, mismatch_issues = (
        functional_reconciliation_module._reconcile_supplied_context_auto_args(
            capability,
            resolved_args={"object_state": (supplied,)},
            resolved_auto_args={
                "object_state": (
                    replace(
                        expected,
                        state_slot_id=(
                            "function:part:curve.expression@other_version"
                        ),
                    ),
                )
            },
            resolver_repairs=(),
            resolver_issues=(),
            supplied_names={"object_state"},
            call_id="consume_curve",
            scope_id="part",
        )
    )
    assert [issue.code for issue in mismatch_issues] == [
        "functional.auto_arg_override_mismatch"
    ]


def test_elaborator_does_not_merge_calls_with_different_return_bindings() -> None:
    inputs = _inputs_for_goal(5)
    shared_args = {
        "path_transformation": _path_transformation_ref(),
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    _path_reduction_call(),
                    {
                        "call_id": "derive_minimum",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": shared_args,
                        "return_bindings": {},
                        "strategy": "derive the minimum expression",
                        "reason": "produce the required value state",
                    },
                    {
                        "call_id": "bind_minimum_point",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": shared_args,
                        "return_bindings": {
                            "path_minimum_point_2": {
                                "ref": "ii_2.intersection",
                                "kind": "answer",
                            }
                        },
                        "strategy": "bind the minimizing point",
                        "reason": "reuse the same state transformation",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    result = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=catalog,
        semantic_index=FunctionalSemanticIndex.from_context(
            _context(inputs),
            handle_registry=_registry(),
        ),
    )

    assert len(result.plan.calls) == 3
    assert result.plan.calls[1].call_id == "derive_minimum"
    assert result.plan.calls[1].return_bindings == {}
    assert result.plan.calls[2].call_id == "bind_minimum_point"
    assert result.plan.calls[2].return_bindings == {
        "path_minimum_point_2": SemanticRef(
            "ii_2.intersection",
            "answer",
        )
    }
    assert not any(
        item.action == "merge_equivalent_capability_call"
        and item.call_id == "bind_minimum_point"
        for item in result.deterministic_repairs
    )


def test_elaborator_defers_mutable_object_ref_deduplication() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    args = {
        "p1": {"ref": "M", "kind": "point"},
        "p2": {"ref": "M", "kind": "point"},
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "distance_before_transition",
                        "capability_id": "distance_between_points",
                        "args": args,
                        "return_bindings": {},
                        "strategy": "read the current point state",
                        "reason": "establish the pre-transition calculation",
                    },
                    {
                        "call_id": "distance_after_transition",
                        "capability_id": "distance_between_points",
                        "args": args,
                        "return_bindings": {},
                        "strategy": "read the later point state",
                        "reason": "the same object ref may select a newer state",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    result = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=catalog,
        semantic_index=FunctionalSemanticIndex.from_context(
            _context(inputs),
            handle_registry=_registry(),
        ),
    )

    assert [call.call_id for call in result.plan.calls] == [
        "distance_before_transition",
        "distance_after_transition",
    ]
    assert not any(
        item.action == "merge_equivalent_capability_call"
        for item in result.deterministic_repairs
    )


def test_reconciler_drops_unconsumed_pure_function_call() -> None:
    inputs = _inputs_for_goal(0)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "unused_distance",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {"ref": "M", "kind": "point"},
                        },
                        "return_bindings": {},
                        "strategy": "compute an unrelated distance",
                        "reason": "exercise deterministic dead-call removal",
                    }
                ],
            },
            {
                "scope_id": "i",
                "label": "i",
                "calls": [_axis_plan_payload()["scopes"][0]["calls"][0]],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert [call.call_id for call in result.plan.calls] == [
        "derive_axis_point"
    ]
    assert result.projected_draft is not None
    assert [step.step_id for step in result.projected_draft.steps] == [
        "derive_axis_point"
    ]
    assert any(
        item["action"] == "drop_dead_pure_function_call"
        and item["call_id"] == "unused_distance"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_refines_latest_parabola_after_point_transitions() -> None:
    inputs = _inputs_for_goal(2)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "derive_D",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "axis_point": {"ref": "D", "kind": "point"}
                        },
                        "strategy": "derive the fixed anchor",
                        "reason": "materialize D for the construction",
                    }
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "construct_N",
                        "capability_id": (
                            "right_angle_equal_length_construct_and_select"
                        ),
                        "args": {
                            "right_angle_equal_length": {
                                "ref": "right_angle_equal_length_MDN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "selected_target_point": {
                                "ref": "N",
                                "kind": "point",
                            }
                        },
                        "strategy": "construct the parameterized point N",
                        "reason": "provide the initial N coordinate state",
                    },
                    {
                        "call_id": "stale_parameterized_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": [
                                {"ref": "M", "kind": "point"},
                                {"ref": "N", "kind": "point"},
                            ],
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "strategy": "derive a parameterized parabola",
                        "reason": "this intermediate state is not consumed",
                    },
                    {
                        "call_id": "solve_m",
                        "capability_id": "parameter_from_segment_length",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {"ref": "N", "kind": "point"},
                            "length_squared": {
                                "ref": "MN_length_squared_eq_10",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "solve the parameter from the segment length",
                        "reason": "produce the numerical parameter value",
                    },
                    {
                        "call_id": "evaluate_M",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {
                            "point": {"ref": "M", "kind": "point"},
                            "parameter_value": {
                                "from_call": "solve_m",
                                "return": "parameter_value",
                            },
                        },
                        "return_bindings": {
                            "evaluated_point": {"ref": "M", "kind": "point"}
                        },
                        "strategy": "evaluate M at the solved parameter",
                        "reason": "advance M to its numerical coordinate state",
                    },
                    {
                        "call_id": "evaluate_N",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {
                            "point": {"ref": "N", "kind": "point"},
                            "parameter_value": {
                                "from_call": "solve_m",
                                "return": "parameter_value",
                            },
                        },
                        "return_bindings": {
                            "evaluated_point": {"ref": "N", "kind": "point"}
                        },
                        "strategy": "evaluate N at the solved parameter",
                        "reason": "advance N to its numerical coordinate state",
                    },
                    {
                        "call_id": "final_numeric_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": [
                                {"ref": "M", "kind": "point"},
                                {"ref": "N", "kind": "point"},
                            ],
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "strategy": "derive the parabola from numerical points",
                        "reason": "bind the required final parabola",
                    },
                ],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    call_ids = [call.call_id for call in result.plan.calls]
    assert "stale_parameterized_parabola" in call_ids
    assert "final_numeric_parabola" in call_ids
    final_call = next(
        item for item in result.calls if item.call_id == "final_numeric_parabola"
    )
    assert {
        value.source_call_id
        for value in final_call.resolved_args["curve_points"]
    } == {"evaluate_M", "evaluate_N"}
    assert set(result.dependency_graph["final_numeric_parabola"]) >= {
        "stale_parameterized_parabola",
        "evaluate_M",
        "evaluate_N",
    }
    assert final_call.resolved_args["quadratic"][0].source_call_id == (
        "stale_parameterized_parabola"
    )
    assert final_call.resolved_args["quadratic"][0].handle == (
        "fact:ii_1:stale_parameterized_parabola_parabola"
    )
    repairs = result.elaboration["deterministic_repairs"]
    assert not any(
        item["action"] in {
            "merge_equivalent_capability_call",
            "merge_resolved_equivalent_call",
        }
        and item["call_id"] == "final_numeric_parabola"
        for item in repairs
    )
    assert not any(
        item["action"] == "drop_dead_pure_function_call"
        and item["call_id"] == "stale_parameterized_parabola"
        for item in repairs
    )
    final_plan_call = next(
        item for item in result.plan.calls if item.call_id == "final_numeric_parabola"
    )
    assert final_plan_call.return_bindings["parabola"] == SemanticRef(
        ref="ii_1.parabola",
        kind="answer",
        value_type="Parabola",
    )

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
        validation_report=report,
    )
    assert replay.output is not None, replay.errors
    invocation = next(
        invocation
        for step_plan in replay.output.step_plans
        if step_plan.step_id == "final_numeric_parabola"
        for invocation in step_plan.invocations
        if invocation.method_id == "quadratic_from_constraints"
    )
    assert invocation.inputs["p1"].endswith("M_evaluated_point")
    assert invocation.inputs["p2"].endswith("N_evaluated_point")


def test_elaborator_reuses_unbound_equivalent_call_from_ancestor_scope() -> None:
    inputs = _base_inputs()
    condition_arg = {
        "right_angle_equal_length": {
            "ref": "right_angle_equal_length_MDN",
            "kind": "fact",
        }
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "construct_shared_point",
                        "capability_id": (
                            "right_angle_equal_length_construct_and_select"
                        ),
                        "args": condition_arg,
                        "return_bindings": {},
                        "strategy": "construct the shared point",
                        "reason": "the condition belongs to the parent scope",
                    }
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "construct_duplicate_point",
                        "capability_id": (
                            "right_angle_equal_length_construct_and_select"
                        ),
                        "args": condition_arg,
                        "return_bindings": {},
                        "strategy": "repeat the same construction",
                        "reason": "exercise ancestor-call reuse",
                    },
                    {
                        "call_id": "derive_child_midpoint",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {"ref": "D", "kind": "point"},
                            "p2": {
                                "from_call": "construct_duplicate_point",
                                "return": "selected_target_point",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "derive the child midpoint",
                        "reason": "consume the shared construction",
                    },
                ],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    result = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=catalog,
        semantic_index=FunctionalSemanticIndex.from_context(
            _context(inputs),
            handle_registry=_registry(),
        ),
    )

    assert [call.call_id for call in result.plan.calls] == [
        "construct_shared_point",
        "derive_child_midpoint",
    ]
    midpoint_ref = result.plan.calls[1].args["p2"][0]
    assert midpoint_ref.from_call == "construct_shared_point"
    assert any(
        item.action == "merge_ancestor_equivalent_call"
        and item.call_id == "construct_duplicate_point"
        for item in result.deterministic_repairs
    )


def test_reconciler_auto_fills_unique_related_parameter_state() -> None:
    inputs = _inputs_for_goal(2)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_segment_length",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {"ref": "N", "kind": "point"},
                            "length_squared": {
                                "ref": "MN_length_squared_eq_10",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "solve the unique geometric parameter",
                        "reason": "produce its ParameterValue state",
                    },
                    {
                        "call_id": "solve_numeric_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            },
                            "curve_points": [
                                {"ref": "M", "kind": "point"},
                                {"ref": "N", "kind": "point"},
                            ],
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "ii_1.parabola",
                                "kind": "answer",
                            }
                        },
                        "strategy": "solve the numerical parabola",
                        "reason": "reuse the related solved parameter",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    calls = {item.call_id: item for item in result.calls}
    parameter_values = calls["solve_numeric_parabola"].resolved_args[
        "parameter_value"
    ]
    assert len(parameter_values) == 1
    assert parameter_values[0].object_ref == "symbol:problem:m"
    assert parameter_values[0].source_call_id == "solve_parameter"
    assert result.dependency_graph["solve_numeric_parabola"] == (
        "solve_parameter",
    )
    assert any(
        item["action"] == "auto_fill_optional_arg"
        for item in (result.elaboration or {})["deterministic_repairs"]
    )


def test_parameter_identity_uses_free_symbols_not_transitive_lineage() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "problem",
                "label": "problem",
                "calls": [
                    {
                        "call_id": "derive_D",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "axis_point": {"ref": "D", "kind": "point"}
                        },
                        "strategy": "derive the fixed axis point",
                        "reason": "provide the construction anchor",
                    }
                ],
            },
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "construct_N",
                        "capability_id": (
                            "right_angle_equal_length_construct_and_select"
                        ),
                        "args": {
                            "right_angle_equal_length": {
                                "ref": "right_angle_equal_length_MDN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "selected_target_point": {
                                "ref": "N",
                                "kind": "point",
                            }
                        },
                        "strategy": "construct N from the geometric relation",
                        "reason": "provide the parameterized endpoint",
                    }
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "solve_m",
                        "capability_id": "parameter_from_segment_length",
                        "args": {
                            "p1": {"ref": "M", "kind": "point"},
                            "p2": {
                                "from_call": "construct_N",
                                "return": "selected_target_point",
                            },
                            "length_squared": {
                                "ref": "MN_length_squared_eq_10",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "solve the segment parameter",
                        "reason": "derive its numerical value",
                    }
                ],
            },
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=(),
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    calls = {item.call_id: item for item in result.calls}
    d_point = calls["derive_D"].returns[0]
    n_point = calls["construct_N"].returns[0]
    assert {"symbol:problem:a", "symbol:problem:b"} <= set(
        d_point.dependency_object_refs
    )
    assert d_point.free_symbol_refs == ()
    assert {"symbol:problem:a", "symbol:problem:b"} <= set(
        n_point.dependency_object_refs
    )
    assert n_point.free_symbol_refs == ("symbol:problem:m",)
    parameter = calls["solve_m"].resolved_args["parameter"]
    assert [item.object_ref for item in parameter] == ["symbol:problem:m"]
    assert calls["solve_m"].returns[0].free_symbol_refs == ()


def test_reconciler_infers_parameter_identity_from_future_consumer() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    *_path_reduction_setup_calls(),
                    {
                        "call_id": "derive_minimum_expression",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                        },
                        "return_bindings": {},
                        "strategy": "derive the path minimum expression",
                        "reason": "produce the expression consumed next",
                    },
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_minimum_value",
                        "args": {
                            "minimum_expression": {
                                "from_call": "derive_minimum_expression",
                                "return": "path_minimum_expression",
                            },
                            "minimum_value": {
                                "ref": "path_minimum_value_given",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "solve the parameter",
                        "reason": "produce the value used by the point",
                    },
                    {
                        "call_id": "evaluate_point",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {
                            "point": {"ref": "M", "kind": "point"},
                            "parameter_value": {
                                "from_call": "solve_parameter",
                                "return": "parameter_value",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "evaluate the point",
                        "reason": "consume the solved parameter value",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    calls = {item.call_id: item for item in result.calls}
    parameter_value = calls["solve_parameter"].returns[0]
    assert parameter_value.object_ref == "symbol:problem:m"
    assert calls["evaluate_point"].resolved_args["parameter_value"][
        0
    ].object_ref == "symbol:problem:m"
    assert result.dependency_graph["evaluate_point"] == (
        "solve_parameter",
    )


def test_reconciler_infers_hidden_parameter_from_return_object_binding() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    *_path_reduction_setup_calls(),
                    {
                        "call_id": "derive_minimum_expression",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": _path_transformation_ref(),
                        },
                        "return_bindings": {},
                        "strategy": "derive the minimum expression",
                        "reason": "provide the expression consumed next",
                    },
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_minimum_value",
                        "args": {
                            "minimum_expression": {
                                "from_call": "derive_minimum_expression",
                                "return": "path_minimum_expression",
                            },
                            "minimum_value": {
                                "ref": "path_minimum_value_given",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parameter_value": {"ref": "m", "kind": "symbol"}
                        },
                        "strategy": "solve the parameter",
                        "reason": "bind the resulting value to its symbol",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    solve = next(item for item in result.calls if item.call_id == "solve_parameter")
    assert solve.resolved_args["parameter"][0].object_ref == "symbol:problem:m"
    assert solve.returns[0].object_ref == "symbol:problem:m"


def test_answer_binding_does_not_overwrite_preserved_input_identity() -> None:
    inputs = _inputs_for_goal(0)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "evaluate_other_point",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {
                            "point": {"ref": "C", "kind": "point"},
                            "parameter_value": {
                                "ref": "a_value",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "evaluated_point": {
                                "ref": "i.axis_point",
                                "kind": "answer",
                            }
                        },
                        "strategy": "evaluate a different point",
                        "reason": "exercise preserve-input provenance",
                    }
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok
    output = result.calls[0].returns[0]
    assert output.handle == "answer:i.axis_point"
    assert output.object_ref == "point:problem:C"


def test_projector_reads_point_call_result_through_object_view() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "derive_axis",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive D",
                        "reason": "produce a point state view",
                    },
                    {
                        "call_id": "measure_from_c",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {
                                "from_call": "derive_axis",
                                "return": "axis_point",
                            },
                            "p2": {
                                "from_call": "derive_axis",
                                "return": "axis_point",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "measure from evaluated C",
                        "reason": "consume the latest Point state",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.projected_draft is not None
    reads = result.projected_draft.steps[1].reads
    assert "point:problem:D" in reads


def test_partial_reconciliation_keeps_independent_calls_and_blocks_dependents() -> None:
    inputs = _inputs_for_goal(0)
    axis_call = _axis_plan_payload()["scopes"][0]["calls"][0]
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "invalid_source",
                        "capability_id": "not_in_catalog",
                        "args": {},
                        "return_bindings": {},
                        "strategy": "try an unavailable capability",
                        "reason": "exercise root-cause reporting",
                    },
                    {
                        "call_id": "blocked_vertex",
                        "capability_id": "quadratic_vertex_point",
                        "args": {
                            "parabola": {
                                "from_call": "invalid_source",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "consume the failed source",
                        "reason": "exercise dependency blocking",
                    },
                    axis_call,
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    reports = {item.call_id: item for item in result.call_reports}
    assert reports["invalid_source"].status == "invalid"
    assert "blocked_vertex" not in reports
    assert reports["derive_axis_point"].status == "valid"
    assert result.partial_projected_draft is not None
    assert [
        step.step_id for step in result.partial_projected_draft.steps
    ] == ["derive_axis_point"]
    assert {item.call_id for item in result.issues} == {"invalid_source"}
    assert any(
        item["action"] == "drop_dead_invalid_call"
        and item["call_id"] == "blocked_vertex"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_topologically_repairs_prior_call_forward_reference() -> None:
    inputs = _base_inputs()
    goals = [inputs.question_goals[0], inputs.question_goals[1]]
    inputs = replace(inputs, question_goals=goals)
    quadratic_call = {
        "call_id": "solve_parabola",
        "capability_id": "quadratic_from_constraints",
        "args": {
            "coefficient_relation": {
                "ref": "coefficient_relation",
                "kind": "fact",
            }
        },
        "return_bindings": {
            "parabola": {"ref": "i.parabola", "kind": "answer"}
        },
        "strategy": "solve the quadratic constraints",
        "reason": "produce the parabola state",
    }
    vertex_call = {
        "call_id": "derive_vertex",
        "capability_id": "quadratic_vertex_point",
        "args": {
            "parabola": {"from_call": "solve_parabola", "return": "parabola"}
        },
        "return_bindings": {
            "point": {"ref": "i.axis_point", "kind": "answer"}
        },
        "strategy": "derive the vertex",
        "reason": "use the solved parabola",
    }
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [quadratic_call, vertex_call],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None
    reconciled = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=goals,
    )
    assert reconciled.ok, [item.to_payload() for item in reconciled.issues]
    assert reconciled.projected_draft is not None
    assert reconciled.projected_draft.steps[1].reads == (
        "answer:i.parabola",
    )

    payload["scopes"][0]["calls"] = [vertex_call, quadratic_call]
    forward_plan, report = _validate(payload, inputs)
    assert report.ok and forward_plan is not None
    forward = FunctionalPlanReconciler().reconcile(
        forward_plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=goals,
    )
    assert forward.ok, [item.to_payload() for item in forward.issues]
    assert forward.projected_draft is not None
    assert [step.step_id for step in forward.projected_draft.steps] == [
        "solve_parabola",
        "derive_vertex",
    ]
    assert any(
        item["action"] == "reorder_call_by_dependency"
        for item in (forward.elaboration or {}).get("deterministic_repairs", ())
    )

    vertex_call["args"]["parabola"] = {
        "from_call": "i.solve_parabola",
        "return": "parabola",
    }
    payload["scopes"][0]["calls"] = [quadratic_call, vertex_call]
    unknown_plan, report = _validate(payload, inputs)
    assert report.ok and unknown_plan is not None
    unknown = FunctionalPlanReconciler().reconcile(
        unknown_plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=goals,
    )
    assert "functional.call_unknown" in {item.code for item in unknown.issues}


def test_functional_retry_prefix_is_call_level_and_none_is_authoritative() -> None:
    candidate = _axis_plan_payload(strategy="changed")
    stable_call = _axis_plan_payload(strategy="stable")["scopes"][0]["calls"][0]
    retry_state = {
        "candidate_format": "functional_plan",
        "preserve_policy": "preserve_prefix",
        "baseline_candidate": _axis_plan_payload(strategy="stable"),
        "stable_candidate_prefix": [{"scope_id": "i", "call": stable_call}],
    }
    attempts = [{"context_derived_retry_state": retry_state}]

    merged = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(candidate),
            previous_attempts=attempts,
        )
    )
    assert merged["scopes"][0]["calls"][0]["strategy"] == "stable"

    retry_state["preserve_policy"] = "none"
    unmerged = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(candidate),
            previous_attempts=attempts,
        )
    )
    assert unmerged["scopes"][0]["calls"][0]["strategy"] == "changed"


def test_projection_validation_failure_keeps_functional_retry_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, functional_validation = _validate(payload, inputs)
    assert functional_validation.ok and plan is not None
    stable_call = next(
        call for call in plan.calls if call.call_id == "i_derive_D"
    )
    inputs = replace(
        inputs,
        previous_errors=[
            {
                "context_derived_retry_state": {
                    "candidate_format": "functional_plan",
                    "preserve_policy": "preserve_graph",
                    "baseline_candidate": plan.to_payload(),
                    "stable_candidate_calls": [
                        {"scope_id": "i", "call": stable_call.to_payload()}
                    ],
                }
            }
        ],
    )
    projection_validation = StepIntentValidationReport(
        ok=False,
        errors=(
            "duplicate_point_coordinate_fact: previous_step=i_derive_D, "
            "current_step=ii_1_solve_m",
        ),
    )

    def reject_projection(*_args: object, **_kwargs: object):
        return None, projection_validation

    monkeypatch.setattr(
        strategy_replay_module.StepIntentValidator,
        "validate_json_with_report",
        reject_projection,
    )

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
        validation_report=functional_validation,
    )

    assert replay.retry_state is not None
    assert replay.retry_state.candidate_format == "functional_plan"
    assert replay.retry_state.baseline_candidate == (
        replay.functional_reconciliation.plan.to_payload()
    )
    assert replay.retry_state.preserve_policy == "preserve_graph"
    assert [
        item["call"]["call_id"]
        for item in replay.retry_state.stable_candidate_calls
    ] == ["i_derive_D"]
    assert replay.retry_state.repair_call_ids == ("ii_1_solve_m",)
    assert replay.retry_state.issues[0].code == "functional.projection_invalid"
    assert replay.retry_state.issues[0].step_id == "ii_1_solve_m"
    assert "StepIntent" not in replay.retry_state.repair_instruction
    assert replay.planner_state_context is not None
    assert (
        replay.planner_state_context.state.retry_memory.candidate_format
        == "functional_plan"
    )
    assert [
        item["call"]["call_id"]
        for item in replay.planner_state_context.state.retry_memory.stable_candidate_calls
    ] == ["i_derive_D"]


def test_projection_failure_verifies_independent_current_call_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, functional_validation = _validate(payload, inputs)
    assert functional_validation.ok and plan is not None
    blocker_id = "ii_reduce_path"
    projection_validation = StepIntentValidationReport(
        ok=False,
        errors=(
            "duplicate_state_writer: previous_step=i_derive_D, "
            f"current_step={blocker_id}",
        ),
    )
    original_validate = StepIntentValidator.validate_json_with_report
    validation_calls = 0

    def reject_full_projection_once(
        validator: StepIntentValidator,
        *args: object,
        **kwargs: object,
    ):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            return None, projection_validation
        return original_validate(validator, *args, **kwargs)

    monkeypatch.setattr(
        strategy_replay_module.StepIntentValidator,
        "validate_json_with_report",
        reject_full_projection_once,
    )

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
        validation_report=functional_validation,
    )

    assert replay.retry_state is not None
    assert replay.retry_state.preserve_policy == "preserve_graph"
    stable_ids = {
        item["call"]["call_id"]
        for item in replay.retry_state.stable_candidate_calls
    }
    assert "i_derive_D" in stable_ids
    assert blocker_id not in stable_ids
    assert replay.functional_reconciliation is not None
    dependents = {
        call_id
        for call_id, dependencies in (
            replay.functional_reconciliation.dependency_graph.items()
        )
        if blocker_id in dependencies
    }
    assert dependents
    assert dependents.isdisjoint(stable_ids)
    assert replay.retry_state.repair_call_ids == (blocker_id,)
    issue = next(
        item
        for item in replay.retry_state.issues
        if item.code == "functional.projection_invalid"
    )
    assert issue.details is not None
    assert dependents <= set(issue.details["blocked_call_ids"])
    verification = replay.retry_state.replay_reports[
        "functional_reconciliation"
    ]["independent_graph_verification"]
    assert "i_derive_D" in verification["verified_call_ids"]


def test_projected_parabola_transition_allows_same_state_slot_update() -> None:
    first_handle = "fact:ii_1:parabola_after_parameter"
    second_handle = "fact:ii_1:parabola_after_constraint"
    slot_id = "function:problem:parabola.expression@ii_1"
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                "ii_1",
                "ii_1",
                (
                    StepIntent(
                        scope_id="ii_1",
                        step_id="specialize_parabola",
                        recipe_hint="evaluate_expression_at_parameter",
                        goal_type="evaluate_expression_at_parameter",
                        target="function:problem:parabola",
                        strategy="specialize the current curve",
                        reads=("fact:problem:coefficient_relation",),
                        creates=(),
                        produces=(
                            ProducedFact(
                                first_handle,
                                "ii_1",
                                "parameter-specialized parabola",
                                output_type="Parabola",
                            ),
                        ),
                        reason="produce the first local curve state",
                    ),
                    StepIntent(
                        scope_id="ii_1",
                        step_id="close_parabola_parameter",
                        recipe_hint="parameter_from_curve_point_on_quadratic",
                        goal_type="derive_parameter",
                        target="function:problem:parabola",
                        strategy="close one parameter and update the curve",
                        reads=(first_handle,),
                        creates=(),
                        produces=(
                            ProducedFact(
                                second_handle,
                                "ii_1",
                                "constraint-closed parabola",
                                output_type="Parabola",
                            ),
                        ),
                        reason="transition the same curve state",
                    ),
                ),
            ),
        )
    )
    state_writes = (
        ProjectedStateWrite(
            step_id="specialize_parabola",
            produced_handle=first_handle,
            state_slot_id=slot_id,
            write_mode="value",
            source_state_slot_ids=(
                "function:problem:parabola.expression@ii",
            ),
        ),
        ProjectedStateWrite(
            step_id="close_parabola_parameter",
            produced_handle=second_handle,
            state_slot_id=slot_id,
            write_mode="transition",
            source_state_slot_ids=(slot_id,),
        ),
    )

    validated, report = StepIntentValidator().validate_json_with_report(
        json.dumps(draft.to_payload()),
        handle_registry=_registry(),
        partial_candidate=True,
        allow_shared_derivation_scopes=True,
        allow_internal_output_types=True,
        projected_state_writes=state_writes,
    )

    assert validated is not None
    assert report.ok


def test_projected_duplicate_parabola_without_transition_is_rejected() -> None:
    first_handle = "fact:ii_1:parabola_initial_state"
    second_handle = "fact:ii_1:parabola_duplicate_state"
    slot_id = "function:problem:parabola.expression@ii_1"
    draft = StepIntentDraft(
        scopes=(
            StepIntentScope(
                "ii_1",
                "ii_1",
                (
                    StepIntent(
                        "ii_1",
                        "first_curve_write",
                        "quadratic_from_constraints",
                        "derive_parabola",
                        "function:problem:parabola",
                        "derive the curve",
                        ("fact:problem:coefficient_relation",),
                        (),
                        (
                            ProducedFact(
                                first_handle,
                                "ii_1",
                                "initial parabola state",
                                output_type="Parabola",
                            ),
                        ),
                        "first writer",
                    ),
                    StepIntent(
                        "ii_1",
                        "duplicate_curve_write",
                        "quadratic_from_constraints",
                        "derive_parabola",
                        "function:problem:parabola",
                        "derive the curve again",
                        (first_handle,),
                        (),
                        (
                            ProducedFact(
                                second_handle,
                                "ii_1",
                                "duplicate parabola state",
                                output_type="Parabola",
                            ),
                        ),
                        "ordinary duplicate writer",
                    ),
                ),
            ),
        )
    )
    state_writes = (
        ProjectedStateWrite(
            "first_curve_write",
            first_handle,
            slot_id,
            "value",
        ),
        ProjectedStateWrite(
            "duplicate_curve_write",
            second_handle,
            slot_id,
            "value",
            (slot_id,),
        ),
    )

    validated, report = StepIntentValidator().validate_json_with_report(
        json.dumps(draft.to_payload()),
        handle_registry=_registry(),
        partial_candidate=True,
        allow_shared_derivation_scopes=True,
        allow_internal_output_types=True,
        projected_state_writes=state_writes,
    )

    assert validated is None
    assert "duplicate_point_coordinate_fact" in report.errors[0]
def test_functional_retry_preserve_graph_restores_omitted_stable_call() -> None:
    baseline = _axis_plan_payload(strategy="verified")
    stable_call = baseline["scopes"][0]["calls"][0]
    candidate = {
        "format": "functional_plan/v1",
        "scopes": [{"scope_id": "i", "label": "i", "calls": []}],
    }
    attempts = [
        {
            "context_derived_retry_state": {
                "candidate_format": "functional_plan",
                "preserve_policy": "preserve_graph",
                "baseline_candidate": baseline,
                "stable_candidate_calls": [
                    {"scope_id": "i", "call": stable_call}
                ],
            }
        }
    ]

    merged = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(candidate),
            previous_attempts=attempts,
        )
    )

    assert merged["scopes"][0]["calls"] == [stable_call]


def test_functional_replay_preserves_named_line_intersection_arguments() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
        validation_report=validation,
    )

    assert replay.output is not None, (
        replay.retry_state.to_payload() if replay.retry_state is not None else None
    )
    invocation = next(
        invocation
        for step in replay.output.step_plans
        for invocation in step.invocations
        if invocation.method_id == "line_intersection_point"
    )
    assert invocation.inputs["line1_p1"] != invocation.inputs["line1_p2"]
    assert invocation.inputs["line2_p1"] != invocation.inputs["line2_p2"]
    assert {
        invocation.inputs["line1_p1"],
        invocation.inputs["line1_p2"],
    }.isdisjoint(
        {
            invocation.inputs["line2_p1"],
            invocation.inputs["line2_p2"],
        }
    )


def test_functional_replay_registers_equivalent_macro_return_alias() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_2_derive_G"
    )
    call["args"]["line1_p1"] = {
        "from_call": "ii_derive_path_model",
        "return": "straightening_auxiliary_point",
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
        validation_report=validation,
    )

    assert replay.output is not None, (
        replay.retry_state.to_payload() if replay.retry_state is not None else None
    )
    invocation = next(
        invocation
        for step in replay.output.step_plans
        for invocation in step.invocations
        if invocation.method_id == "line_intersection_point"
    )
    assert invocation.inputs["line1_p1"] != invocation.inputs["line1_p2"]


def test_reconciler_rejects_equivalent_returns_as_distinct_line_endpoints() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_2_derive_G"
    )
    call["args"]["line1_p1"] = {
        "from_call": "ii_derive_path_model",
        "return": "straightening_auxiliary_point",
    }
    call["args"]["line1_p2"] = {
        "from_call": "ii_derive_path_model",
        "return": "path_minimum_point_1",
    }
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    issue = next(
        item
        for item in result.issues
        if item.code == "functional.arg_distinctness_violation"
    )
    assert issue.call_id == "ii_2_derive_G"
    assert issue.details is not None
    assert issue.details["duplicate_args"] == [["line1_p1", "line1_p2"]]
    assert issue.details["unchanged_binding_rejected"] is True


def test_functional_retry_stable_graph_excludes_runtime_blocker_and_dependents() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    planner_context = _context(inputs)
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert reconciliation.ok, [
        item.to_payload() for item in reconciliation.issues
    ]
    blocker_id = "ii_reduce_path"
    direct_dependents = {
        call_id
        for call_id, dependencies in reconciliation.dependency_graph.items()
        if blocker_id in dependencies
    }
    assert direct_dependents
    issue = PlannerRetryIssue(
        layer="trial_execution",
        code="synthetic_runtime_blocker",
        step_id=blocker_id,
        scope_id="ii",
        message="the full graph rejected this call",
    )
    retry_state = PlannerRetryState(
        attempt=1,
        baseline_draft=None,
        issues=(issue,),
        candidate_format="functional_plan",
        baseline_candidate=reconciliation.plan.to_payload(),
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        planner_context,
        handle_registry=_registry(),
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)

    projected = strategy_replay_module._functional_runtime_retry_state(
        retry_state,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={call.call_id for call in reconciliation.plan.calls},
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )

    assert projected is not None
    stable_ids = {
        item["call"]["call_id"] for item in projected.stable_candidate_calls
    }
    assert blocker_id not in stable_ids
    assert direct_dependents.isdisjoint(stable_ids)
    assert blocker_id in projected.repair_call_ids
    assert projected.preserve_policy == "preserve_graph"


def test_functional_retry_does_not_freeze_structured_upstream_repair_root() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    planner_context = _context(inputs)
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert reconciliation.ok
    upstream_root = "ii_reduce_path"
    failing_consumer = next(
        call_id
        for call_id, dependencies in reconciliation.dependency_graph.items()
        if upstream_root in dependencies
    )
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.object_identity_mismatch",
        step_id=failing_consumer,
        scope_id="ii",
        message="consumer exposed an upstream identity error",
        details={"repair_call_ids": [upstream_root, failing_consumer]},
    )
    retry_state = PlannerRetryState(
        attempt=1,
        baseline_draft=None,
        issues=(issue,),
        candidate_format="functional_plan",
        baseline_candidate=reconciliation.plan.to_payload(),
        repair_call_ids=(upstream_root, failing_consumer),
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        planner_context,
        handle_registry=_registry(),
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)

    projected = strategy_replay_module._functional_runtime_retry_state(
        retry_state,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={call.call_id for call in reconciliation.plan.calls},
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )

    assert projected is not None
    stable_ids = {
        item["call"]["call_id"] for item in projected.stable_candidate_calls
    }
    assert upstream_root not in stable_ids
    assert failing_consumer not in stable_ids
    assert projected.repair_call_ids == (upstream_root, failing_consumer)


def test_functional_retry_preserve_graph_reconciles_renamed_stable_call() -> None:
    baseline = _axis_plan_payload(strategy="verified")
    stable_call = baseline["scopes"][0]["calls"][0]
    renamed = json.loads(json.dumps(stable_call))
    renamed["call_id"] = "renamed_axis_point"
    renamed["strategy"] = "model rewrote the verified call"
    consumer = {
        "call_id": "consume_axis_point",
        "capability_id": "evaluate_point_at_parameter",
        "args": {
            "point": {
                "from_call": "renamed_axis_point",
                "return": "axis_point",
            }
        },
        "return_bindings": {},
        "strategy": "consume the prior result",
        "reason": "exercise graph edge rewriting",
    }
    candidate = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [renamed, consumer],
            }
        ],
    }
    attempts = [
        {
            "context_derived_retry_state": {
                "candidate_format": "functional_plan",
                "preserve_policy": "preserve_graph",
                "baseline_candidate": baseline,
                "stable_candidate_calls": [
                    {"scope_id": "i", "call": stable_call}
                ],
            }
        }
    ]

    merged = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(candidate),
            previous_attempts=attempts,
        )
    )

    calls = merged["scopes"][0]["calls"]
    assert [item["call_id"] for item in calls] == [
        "derive_axis_point",
        "consume_axis_point",
    ]
    assert calls[0] == stable_call
    assert calls[1]["args"]["point"]["from_call"] == "derive_axis_point"


def test_functional_retry_replaces_stale_stable_object_producer() -> None:
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(load_problem_ir(HEPING_ERMO_FIXTURE))
    )
    stable_producer = {
        "call_id": "get_A_i2",
        "capability_id": "quadratic_x_axis_intercept_point",
        "args": {
            "quadratic": {
                "from_call": "old_curve",
                "return": "parabola",
            }
        },
        "return_bindings": {
            "point": {"ref": "problem.A", "kind": "point"}
        },
        "strategy": "derive A from the old curve state",
        "reason": "old stable producer",
    }
    stable_consumer = {
        "call_id": "construct_G_i2",
        "capability_id": "square_adjacent_vertex_from_side",
        "args": {
            "side_start": {
                "from_call": "get_A_i2",
                "return": "point",
            }
        },
        "return_bindings": {},
        "strategy": "consume A",
        "reason": "stable dependent call",
    }
    baseline = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "i_2",
                "calls": [stable_producer, stable_consumer],
            }
        ],
    }
    repaired_producer = {
        "call_id": "a_point_from_parabola",
        "capability_id": "quadratic_x_axis_intercept_point",
        "args": {
            "quadratic": {
                "from_call": "repaired_curve",
                "return": "parabola",
            }
        },
        "return_bindings": {
            "point": {"ref": "i_1.A", "kind": "answer"}
        },
        "strategy": "derive A from the repaired curve state",
        "reason": "current repair producer",
    }
    candidate = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "i_1",
                "calls": [repaired_producer],
            }
        ],
    }
    attempts = [
        {
            "context_derived_retry_state": {
                "candidate_format": "functional_plan",
                "preserve_policy": "preserve_graph",
                "baseline_candidate": baseline,
                "stable_candidate_calls": [
                    {"scope_id": "i_2", "call": stable_producer},
                    {"scope_id": "i_2", "call": stable_consumer},
                ],
            }
        }
    ]

    merged = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(candidate),
            previous_attempts=attempts,
            handle_registry=registry,
            shareable_capability_ids={
                "quadratic_x_axis_intercept_point"
            },
        )
    )

    calls = {
        call["call_id"]: call
        for scope in merged["scopes"]
        for call in scope["calls"]
    }
    assert "get_A_i2" not in calls
    assert "a_point_from_parabola" in calls
    assert calls["construct_G_i2"]["args"]["side_start"]["from_call"] == (
        "a_point_from_parabola"
    )


def test_functional_wire_preparation_repairs_fence_and_empty_return_binding() -> None:
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["return_bindings"]["unused_optional_return"] = {}
    prepared = prepare_functional_plan_raw_response(
        "```json\n" + json.dumps(payload) + "\n```",
        previous_attempts=[],
    )

    repaired = json.loads(prepared)
    assert repaired["scopes"][0]["calls"][0]["return_bindings"] == {
        "axis_point": {
            "ref": "i.axis_point",
            "kind": "answer",
            "value_type": "Point",
        }
    }


def test_functional_wire_preparation_drops_only_redundant_ref_scope() -> None:
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["args"]["coefficient_relation"]["scope"] = "i"
    call["return_bindings"]["axis_point"]["scope"] = "i"
    call["args"]["untrusted_scope"] = {
        "ref": "A",
        "kind": "point",
        "scope": "ii",
    }

    prepared = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(payload),
            previous_attempts=[],
        )
    )
    repaired_call = prepared["scopes"][0]["calls"][0]

    assert "scope" not in repaired_call["args"]["coefficient_relation"]
    assert "scope" not in repaired_call["return_bindings"]["axis_point"]
    assert repaired_call["args"]["untrusted_scope"]["scope"] == "ii"


def test_functional_projection_may_use_internal_symbol_output_type() -> None:
    payload = {
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "steps": [
                        {
                            "step_id": "derive_internal_symbol",
                            "recipe_hint": None,
                            "goal_type": "derive_internal_symbol",
                            "target": "fact:i:internal_symbol",
                        "strategy": "project an internal symbol state",
                        "reads": [],
                        "creates": [],
                        "produces": [
                            {
                                "handle": "fact:i:internal_symbol",
                                "valid_scope": "i",
                                "description": "internal companion state",
                                "output_type": "Symbol",
                            }
                        ],
                        "reason": "the functional bridge owns this state",
                    }
                ],
            }
        ]
    }
    validator = StepIntentValidator()

    external, external_report = validator.validate_json_with_report(
        json.dumps(payload)
    )
    internal, internal_report = validator.validate_json_with_report(
        json.dumps(payload),
        allow_internal_output_types=True,
    )

    assert external is None
    assert "output_type unsupported: Symbol" in external_report.errors[0]
    assert internal is not None
    assert internal_report.ok


def test_functional_wire_preparation_does_not_extract_json_from_prose() -> None:
    raw = 'Here is the plan: {"format": "functional_plan/v1"}'

    assert prepare_functional_plan_raw_response(raw, previous_attempts=[]) == raw


def test_functional_validation_failure_still_creates_context_retry_memory() -> None:
    inputs = _inputs_for_goal(0)
    replay = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps({"scopes": []}),
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
    )

    assert replay.output is None
    assert replay.retry_state is not None
    assert replay.retry_state.candidate_format == "functional_plan"
    assert replay.retry_state.issues[0].layer == "functional_validation"
    assert replay.planner_state_context is not None
    assert replay.planner_state_context.state.candidate_format == "functional_plan"


def test_functional_context_versions_link_across_retry_attempts() -> None:
    inputs = _inputs_for_goal(0)
    first = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps({"scopes": []}),
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=1,
        problem_payload=_problem_payload(),
    )
    attempt_payload = repair_attempt_payload_from_replay(first)
    assert attempt_payload is not None
    second_inputs = replace(inputs, previous_errors=[attempt_payload])
    second = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps({"format": "functional_plan/v1", "scopes": []}),
        inputs=second_inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
    )

    assert first.planner_state_context is not None
    assert second.planner_state_context is not None
    assert second.planner_state_context.manifest.parent_context_id == (
        first.planner_state_context.manifest.context_id
    )


def test_functional_retry_keeps_the_first_attempt_few_shot_selection() -> None:
    inputs = _inputs_for_goal(0)

    class InvalidClient:
        def complete(self, payload: dict) -> str:
            return json.dumps(
                {"format": "functional_plan/v1", "scopes": []}
            )

    planner = StrategyPlanner(
        ContextBuilder().build(_problem()),
        mode="deepseek",
        client=InvalidClient(),
        payload_builder=StrategyPayloadBuilder(
            functional_few_shot_mode="strict_test"
        ),
        output_format="functional_plan",
    )
    with pytest.raises(StrategyDraftValidationError):
        planner.plan(inputs)

    first_payload = planner.artifacts.payload
    assert first_payload is not None
    first_selection = first_payload["functional_few_shot_selection"]
    repair = planner.repair_attempt_payload(attempt=1, errors=["invalid plan"])
    assert repair is not None
    assert repair["functional_few_shot_selection"] == first_selection

    retry_payload = StrategyPayloadBuilder(
        functional_few_shot_mode="strict_test"
    ).build(
        replace(inputs, previous_errors=[repair]),
        problem_payload=_problem_payload(),
        output_format="functional_plan",
    )
    assert retry_payload["functional_few_shot_selection"] == first_selection
    assert retry_payload["few_shot_examples"] == first_payload["few_shot_examples"]
    prompt = StrategyPromptRenderer().render(retry_payload).user
    assert first_selection["example_id"] not in prompt
    assert first_selection["source_problem_id"] not in prompt
    assert first_selection["selection_tier"] not in prompt


def test_functional_prompt_retry_state_never_exposes_step_intent_baseline() -> None:
    inputs = _inputs_for_goal(0)
    retry_state = {
        "candidate_format": "functional_plan",
        "baseline_candidate": _axis_plan_payload(),
        "baseline_draft": {"scopes": [{"steps": []}]},
        "stable_candidate_prefix": [],
        "stable_prefix": [{"step_id": "legacy"}],
        "preserve_policy": "none",
        "issues": [],
    }
    inputs = replace(
        inputs,
        previous_errors=[{"context_derived_retry_state": retry_state}],
    )
    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_problem_payload(),
        output_format="functional_plan",
    )
    latest = payload["previous_attempt_state"]["latest_retry_state"]

    assert latest["baseline_candidate"] == _axis_plan_payload()
    assert "baseline_draft" not in latest
    assert "stable_prefix" not in latest
    assert "stable_candidate_prefix" not in latest
    assert all("step_id" not in item for item in latest["issues"])


def test_functional_prompt_projects_retry_handles_to_semantic_refs() -> None:
    inputs = replace(
        _inputs_for_goal(0),
        previous_errors=[
            {
                "context_derived_retry_state": {
                    "candidate_format": "functional_plan",
                    "preserve_policy": "none",
                    "issues": [
                        {
                            "layer": "goal_verification",
                            "code": "answer_unresolved_symbol_state",
                            "step_id": "evaluate_answer",
                            "scope_id": "ii_1",
                            "related_handles": [
                                "answer:ii_1.minimum_value",
                                "symbol:problem:m",
                                "fact:ii_1:m_value",
                            ],
                            "details": {
                                "unresolved_symbols": ["_axis_param_E"],
                                "unresolved_symbol_states": [
                                    {
                                        "runtime_symbol": "_axis_param_E",
                                        "semantic_role": "axis_parameter",
                                        "description": "点 E 的未定坐标参数",
                                        "object_ref": (
                                            "symbol:ii:E_axis_parameter"
                                        ),
                                        "source_object_ref": "point:ii:E",
                                    }
                                ],
                                "available_parameter_states": [
                                    "fact:ii_1:m_value"
                                ],
                                "identity_message": (
                                    "point:ii:G differs from "
                                    "role:path_minimum_point_2@ii_2"
                                ),
                            },
                        },
                        {
                            "layer": "goal_verification",
                            "code": "functional.return_form_mismatch",
                            "step_id": "evaluate_answer",
                            "scope_id": "ii_1",
                            "details": {
                                "free_symbol_names": ["_axis_param_E"]
                            },
                        },
                    ],
                }
            }
        ],
    )

    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_problem_payload(),
        output_format="functional_plan",
    )
    latest = payload["previous_attempt_state"]["latest_retry_state"]
    serialized = json.dumps(latest, ensure_ascii=False)

    assert "answer:ii_1.minimum_value" not in serialized
    assert "symbol:problem:m" not in serialized
    assert "fact:ii_1:m_value" not in serialized
    assert "point:ii:G" not in serialized
    assert "role:path_minimum_point_2@ii_2" not in serialized
    assert "_axis_param_E" not in serialized
    assert "点 E 的未定坐标参数" in serialized
    assert "ii_1.minimum_value" in serialized
    assert "m_value" in serialized
    assert "path_minimum_point_2" in serialized


def test_fake_llm_functional_plan_compiles_through_existing_runtime() -> None:
    inputs = _inputs_for_goal(0)

    class FakeClient:
        request: dict | None = None

        def complete(self, payload: dict) -> str:
            self.request = payload
            return json.dumps(_axis_plan_payload())

    client = FakeClient()
    planner = StrategyPlanner(
        ContextBuilder().build(_problem()),
        mode="deepseek",
        client=client,
        output_format="functional_plan",
    )

    output = planner.plan(inputs)

    invocation = output.step_plans[0].invocations[0]
    assert invocation.method_id == "quadratic_axis_from_relation"
    assert invocation.inputs == {
        "coefficient_relation": "$problem.equations.coefficient_relation",
        "a": "$problem.symbols.a",
        "b": "$problem.symbols.b",
        "target": "$problem.points.D",
    }
    assert client.request is not None
    assert client.request["planner_output_format"] == "functional_plan"
    raw_candidate = planner.last_raw_response or ""
    assert not CANONICAL_REF_RE.search(raw_candidate)
    assert "creates" not in raw_candidate and "produces" not in raw_candidate


def test_functional_projection_output_types_remain_authoritative_in_replay() -> None:
    inputs = _inputs_for_goal(1)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                "label": "i",
                "calls": [
                    {
                        "call_id": "derive_parabola_i",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "known_coefficients": [
                                {"ref": "a_value", "kind": "fact"},
                                {"ref": "c_value", "kind": "fact"},
                            ],
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "i.parabola",
                                "kind": "answer",
                            }
                        },
                        "strategy": "derive the parabola",
                        "reason": "exercise multi-return type provenance",
                    }
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=0,
        problem_payload=_problem_payload(),
        validation_report=report,
    )

    assert replay.normalized_draft is not None
    produced_types = {
        item.handle: item.output_type
        for item in replay.normalized_draft.steps[0].produces
    }
    assert produced_types[
        "fact:i:derive_parabola_i_coefficients"
    ] == "Coefficients"
    assert produced_types["answer:i.parabola"] == "Parabola"


def test_functional_replay_preserves_reconciled_call_graph_topology(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Functional projection must not re-enter StepIntent topology repair."""
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    def reject_legacy_normalizer(*_args, **_kwargs):
        raise AssertionError("legacy topology normalizer must not run")

    monkeypatch.setattr(
        strategy_replay_module.StepIntentNormalizer,
        "normalize",
        reject_legacy_normalizer,
    )
    monkeypatch.setattr(
        strategy_replay_module,
        "drop_dead_pure_function_steps",
        reject_legacy_normalizer,
    )

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=0,
        problem_payload=_problem_payload(),
        validation_report=report,
    )

    assert replay.normalized_draft is not None
    assert [step.step_id for step in replay.normalized_draft.steps] == [
        "derive_axis_point"
    ]
    assert replay.normalization_report is not None
    assert "functional_call_graph_topology_preserved" in (
        replay.normalization_report.warnings
    )


def test_functional_runtime_unavailable_point_becomes_call_level_work_order() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "derive_axis",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive the known endpoint",
                        "reason": "the coefficient relation determines D",
                    },
                    {
                        "call_id": "derive_midpoint",
                        "capability_id": "midpoint_point",
                        "args": {
                            "midpoint_definition": {
                                "ref": "F_midpoint_of_DN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive the midpoint",
                        "reason": "exercise a point object before its state exists",
                    },
                    {
                        "call_id": "construct_unknown_point",
                        "capability_id": (
                            "right_angle_equal_length_construct_and_select"
                        ),
                        "args": {
                            "right_angle_equal_length": {
                                "ref": "right_angle_equal_length_MDN",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "construct the missing endpoint",
                        "reason": "this producer deliberately appears too late",
                    },
                ],
            }
        ],
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=0,
        problem_payload=_problem_payload(),
        validation_report=report,
    )

    assert replay.retry_state is not None
    issue = next(
        item
        for item in replay.retry_state.issues
        if item.code == "functional.arg_state_unavailable"
    )
    assert issue.step_id == "derive_midpoint"
    assert issue.repair_target == "functional_call"
    assert issue.details is not None
    assert issue.details["arg"] == "midpoint_definition"
    assert issue.details["accepted_item_types"] == ["Point"]
    assert issue.details["state_requirement"] == "computed Point"
    assert any(
        item["from_call"] == "construct_unknown_point"
        and item["value_type"] == "Point"
        for item in issue.details["later_compatible_call_results"]
    )


def test_dead_invalid_pure_call_does_not_block_submittable_output() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"].append(
        {
            "call_id": "invalid_extra_call",
            "capability_id": "quadratic_x_axis_intercept_point",
            "args": {},
            "return_bindings": {},
            "strategy": "attempt an unsupported extra call",
            "reason": "exercise partial reconciliation",
        }
    )
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=0,
        problem_payload=_problem_payload(),
        validation_report=report,
    )

    assert replay.functional_reconciliation is not None
    assert replay.functional_reconciliation.partial_projected_draft is not None
    assert replay.functional_reconciliation.issues == ()
    assert replay.output is not None
    assert "invalid_extra_call" not in {
        call.call_id for call in replay.functional_reconciliation.plan.calls
    }
    assert any(
        item["action"] == "drop_dead_invalid_call"
        and item["call_id"] == "invalid_extra_call"
        for item in replay.functional_reconciliation.elaboration[
            "deterministic_repairs"
        ]
    )
    pruned_issue_record = next(
        item
        for item in replay.functional_reconciliation.elaboration[
            "deterministic_repairs"
        ]
        if item["action"] == "record_pruned_call_issues"
        and item["call_id"] == "invalid_extra_call"
    )
    assert pruned_issue_record["from"] == "quadratic_x_axis_intercept_point"
    assert "functional." in pruned_issue_record["to"]
    assert replay.retry_state is None


def test_runtime_macro_arg_failure_becomes_typed_functional_work_order() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    handles = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "reduce_path",
                        "capability_id": "square_path_dimension_reduction",
                        "args": {
                            "path_minimum_target": {
                                "ref": "path_minimum_target",
                                "kind": "fact",
                            },
                            "square": {
                                "ref": "square_AEKG",
                                "kind": "fact",
                            },
                            "midpoint_condition": {
                                "ref": "F_midpoint_of_AE",
                                "kind": "fact",
                            },
                            "square_center_condition": {
                                "ref": "H_square_diagonal_intersection",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "reduce the path dimension",
                        "reason": "produce the path transformation",
                    },
                    {
                        "call_id": "straighten_path",
                        "capability_id": (
                            "broken_path_straightening_minimum_expression"
                        ),
                        "args": {
                            "path_transformation": {
                                "from_call": "reduce_path",
                                "return": "path_transformation",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "straighten the path",
                        "reason": "derive a minimum expression",
                    },
                    {
                        "call_id": "solve_parameter",
                        "capability_id": "parameter_from_expression_value",
                        "args": {
                            "expression": {
                                "from_call": "straighten_path",
                                "return": "path_minimum_expression",
                            },
                            "minimum_value": {
                                "ref": "path_minimum_value_given",
                                "kind": "fact",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "solve the remaining parameter",
                        "reason": "exercise inherited Symbol provenance",
                    },
                ],
            }
        ],
    }

    replay = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps(payload),
        inputs=inputs,
        handle_registry=handles,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
    )

    assert replay.retry_state is not None
    issue = next(
        item
        for item in replay.retry_state.issues
        if item.step_id == "straighten_path"
    )
    assert issue.repair_target == "functional_call"
    assert issue.code == "functional.arg_dependency_missing"
    assert issue.details is not None
    assert issue.details["arg"] == "moving_locus"
    assert issue.details["semantic_role"] == "moving_locus"
    assert issue.details["provider_arg_roles"] == ["path_transformation"]
    assert issue.details["accepted_item_types"] == ["Line"]
    assert issue.details["linked_candidates"] == []
    assert issue.details["automatic_selection"] == (
        "only_provenance_linked_unique_candidate"
    )
    assert issue.details["producer_candidate"] == (
        "parameterized_point_locus_line"
    )
    assert not any(
        item.code in {
            "functional.auto_arg_unresolved",
            "functional.auto_arg_ambiguous",
        }
        and item.step_id == "solve_parameter"
        for item in replay.retry_state.issues
    )
    reconciliation = replay.functional_reconciliation
    assert reconciliation is not None
    solve_report = next(
        item
        for item in reconciliation.call_reports
        if item.call_id == "solve_parameter"
    )
    assert solve_report.status == "blocked_by_dependency"
    assert solve_report.blocked_by == ("straighten_path",)


def test_functional_debug_artifacts_reuse_projected_step_intents(tmp_path: Path) -> None:
    inputs = _inputs_for_goal(0)
    plan, report = _validate(_axis_plan_payload(), inputs)
    assert plan is not None
    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=0,
        problem_payload=_problem_payload(),
        validation_report=report,
    )
    payload = StrategyPayloadBuilder().build(
        inputs,
        problem_payload=_problem_payload(),
        output_format="functional_plan",
    )
    prompt = StrategyPromptRenderer().render(payload)

    write_strategy_debug_artifacts(
        tmp_path,
        payload=payload,
        prompt=prompt,
        raw_response=json.dumps(_axis_plan_payload()),
        draft=replay.raw_draft,
        report=replay.functional_validation_report,
        normalization_report=replay.normalization_report,
        resolution_report=replay.resolution_report,
        execution_diagnostic=replay.diagnostic,
        effective_draft=replay.effective_draft,
        planner_retry_state=replay.retry_state,
        planner_state_context=replay.planner_state_context,
        functional_plan=replay.functional_plan,
        functional_reconciliation=replay.functional_reconciliation,
    )

    assert json.loads((tmp_path / "functional-plan.json").read_text())["format"] == (
        "functional_plan/v1"
    )
    reconciliation = json.loads(
        (tmp_path / "functional-reconciliation-report.json").read_text()
    )
    assert reconciliation["ok"] is True
    assert reconciliation["effective_plan"] == (
        replay.functional_reconciliation.effective_plan.to_payload()
    )
    context_payload = json.loads(
        (tmp_path / "planner-state-context.json").read_text()
    )
    assert context_payload["state"]["raw_functional_plan_snapshot"] == (
        replay.functional_plan.to_payload()
    )
    assert context_payload["state"]["functional_plan_snapshot"] == (
        replay.functional_reconciliation.effective_plan.to_payload()
    )
    assert reconciliation["student_step_placements"] == context_payload["state"][
        "student_step_placements"
    ]
    assert reconciliation["student_scope_references"] == context_payload["state"][
        "student_scope_references"
    ]
    assert (tmp_path / "effective-step-intents.json").exists()
    selection = json.loads(
        (tmp_path / "payload.functional_few_shot_selection.json").read_text()
    )
    assert selection == payload["functional_few_shot_selection"]
    assert not (tmp_path / "payload.semantic_read_catalog.json").exists()
    assert not (tmp_path / "semantic-read-catalog.json").exists()
    assert (tmp_path / "context-semantic-read-catalog.json").exists()


def test_recorded_mode_rejects_functional_protocol() -> None:
    planner = StrategyPlanner(
        ContextBuilder().build(_problem()),
        mode="recorded",
        output_format="functional_plan",
    )
    with pytest.raises(Exception, match="recorded mode only supports step_intent"):
        planner.plan(_inputs_for_goal(0))
