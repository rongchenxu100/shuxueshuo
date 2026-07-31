from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import PointRef, TypedValue
from shuxueshuo_server.solver.explanation.builder import ExplanationBuilder
from shuxueshuo_server.solver.family.models import (
    RecipeExecutionSpec,
    StateIdentityConstraintSpec,
)
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.explanation.presentation import (
    StudentNarrativePlacementProjector,
)
from shuxueshuo_server.solver.runtime import strategy_replay as strategy_replay_module
from shuxueshuo_server.solver.runtime import strategy_payload as strategy_payload_module
from shuxueshuo_server.solver.runtime import (
    functional_plan_reconciliation as functional_reconciliation_module,
)
from shuxueshuo_server.solver.runtime import (
    functional_call_placement as functional_call_placement_module,
)
from shuxueshuo_server.solver.runtime import (
    functional_plan_elaboration as functional_elaboration_module,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.canonical_draft_finalizer import (
    CanonicalDraftFinalizer,
)
from shuxueshuo_server.solver.runtime.binding_index import (
    CanonicalRuntimeBindingIndex,
    RuntimeHandleBinding,
)
from shuxueshuo_server.solver.runtime.binding_rules import (
    DEFAULT_BINDING_SELECTORS,
    MethodBindingRuleRegistry,
)
from shuxueshuo_server.solver.runtime.answer_goal_verifier import (
    AnswerGoalVerificationItem,
    AnswerGoalVerificationReport,
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
    FunctionalSemanticView,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCall,
    FunctionalCallReconciliation,
    FunctionalCallReport,
    FunctionalPlan,
    FunctionalPlanReconciliationResult,
    FunctionalResultFormEvent,
    FunctionalReturnAllocation,
    FunctionalScope,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_plan_liveness import (
    FunctionalCallLivenessAnalyzer,
)
from shuxueshuo_server.solver.runtime.functional_call_memory import (
    FunctionalCallMemory,
    FunctionalCallMemoryEntry,
    FunctionalResultSnapshot,
    attach_actual_result_refs,
)
from shuxueshuo_server.solver.runtime.functional_retry_versions import (
    FunctionalRetryGraphCheckpoint,
)
from shuxueshuo_server.solver.runtime.functional_context_values import (
    latest_point_state_for_object,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    _infer_symbolic_target_args_from_consumers,
    _projected_creates,
    _values_share_lineage_source_call,
)
from shuxueshuo_server.solver.runtime.functional_result_forms import (
    canonicalize_verified_result_forms,
    verify_functional_input_closures,
    verify_functional_result_forms,
)
from shuxueshuo_server.solver.runtime.functional_state_refinement import (
    refine_functional_object_states,
)
from shuxueshuo_server.solver.runtime.functional_state_allocation import (
    project_sibling_symbol_dependencies,
    rebase_live_state_versions,
)
from shuxueshuo_server.solver.runtime.entity_state_resolver import (
    EntityStateResolver,
)
from shuxueshuo_server.solver.runtime.functional_symbol_flow import (
    infer_unique_target_symbol_ref,
    return_free_symbol_refs,
)
from shuxueshuo_server.solver.runtime.functional_reconciliation_validators import (
    functional_reconciliation_issues,
)
from shuxueshuo_server.solver.runtime.function_specs import (
    FunctionSpecRegistry,
    _analyze_quadratic_coefficient_inputs,
)
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContextBuilder,
    StateSlot,
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.session import PlannerExecutionError
from shuxueshuo_server.solver.runtime.recipe_compiler import (
    RecipeTrialExecutor,
    _RecipePlanCompiler,
    _point_value_path_for_step,
    _promote_outputs_for_step,
    _projected_midpoint_state_is_stale,
    _validate_student_single_degree_of_freedom,
    _projected_recipe_method_arg_bindings,
    _target_path_for_produced,
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
from shuxueshuo_server.solver.runtime.state_identity import (
    ArgVersionBinding,
    ComputationKey,
    LogicalStateKey,
    MathObjectId,
    MathObjectRegistry,
    StateIdentityFactory,
    StateSlotId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.state_identity_constraints import (
    StateIdentityConstraintValidator,
)
from shuxueshuo_server.solver.runtime.state_finalization import (
    StateFinalizationService,
    project_functional_state_dependencies,
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
    ProjectedStateDependency,
    ProjectedStateWrite,
    SemanticRef,
    StateWriteProvenance,
    StepIntentRuntimeResult,
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
HEPING_FUNCTIONAL_PLAN = (
    REPO_ROOT
    / "internal"
    / "functional-plan-fixtures"
    / "tj-2026-heping-yimo-25.functional-plan.json"
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


def _reconcile_heping_ermo_payload(
    payload: dict[str, Any],
) -> FunctionalPlanReconciliationResult:
    inputs, _, registry, context = _heping_ermo_case()
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    return FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )


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


def test_answer_binding_rejects_preserved_identity_from_another_object() -> None:
    _, payload, _, _ = _heping_ermo_case()
    calls = {
        call["call_id"]: call
        for scope in payload["scopes"]
        for call in scope["calls"]
    }
    candidate_call = calls["solve_axis_point_candidates_i"]
    candidate_call["args"]["target_point"] = {
        "from_call": "derive_square_vertex_G_i",
        "return": "point",
    }
    candidate_call["args"]["curve_point"] = {
        "from_call": "derive_square_vertex_G_i",
        "return": "point",
    }

    result = _reconcile_heping_ermo_payload(payload)

    issue = next(
        item
        for item in result.issues
        if item.code
        == "functional.return_answer_object_identity_mismatch"
        and item.call_id == "solve_axis_point_candidates_i"
    )
    assert issue.details["expected_object_ref"] == "point:i_2:E"
    assert issue.details["actual_object_ref"] == "point:i_2:G"
    assert issue.details["identity_arg"] == "target_point"


def test_unknown_call_local_line_binding_is_dropped() -> None:
    _, payload, _, _ = _heping_ermo_case()
    locus_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_locus_G_ii"
    )
    locus_call["return_bindings"] = {
        "line": {"kind": "line", "ref": "display_locus"}
    }

    result = _reconcile_heping_ermo_payload(payload)

    assert not [
        item
        for item in result.issues
        if item.call_id == "derive_locus_G_ii"
        and item.code == "functional.return_binding_unknown"
    ]
    effective_call = next(
        call
        for call in result.plan.calls
        if call.call_id == "derive_locus_G_ii"
    )
    assert effective_call.return_bindings == {}
    assert {
        "call_id": "derive_locus_G_ii",
        "action": "drop_unknown_call_local_return_binding",
        "from": "line:display_locus",
        "to": "line",
    } in result.elaboration["deterministic_repairs"]


@pytest.mark.parametrize(
    ("problem_fixture", "plan_fixture"),
    (
        (NANKAI_FIXTURE, NANKAI_FUNCTIONAL_PLAN),
        (HEPING_ERMO_FIXTURE, HEPING_ERMO_FUNCTIONAL_PLAN),
        (XIQING_FIXTURE, XIQING_FUNCTIONAL_PLAN),
        (HEXI_FIXTURE, HEXI_FUNCTIONAL_PLAN),
        (HEPING_FIXTURE, HEPING_FUNCTIONAL_PLAN),
    ),
)
def test_authored_functional_fixtures_have_zero_typed_identity_drift(
    problem_fixture: Path,
    plan_fixture: Path,
) -> None:
    problem = load_problem_ir(problem_fixture)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(plan_fixture.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.identity_mismatches == ()
    assert result.state_identity_decisions
    assert result.placement_mismatches == ()
    assert result.state_placement_decisions
    assert result.state_finalization_mismatches == ()
    assert result.state_finalization_decisions
    assert {
        item["canonical_call_id"]
        for item in result.state_placement_decisions
    } == {call.call_id for call in result.plan.calls}
    repeated = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert repeated.plan.to_payload() == result.plan.to_payload()
    assert repeated.call_aliases == result.call_aliases
    assert repeated.state_placement_decisions == (
        result.state_placement_decisions
    )
    assert repeated.state_finalization_decisions == (
        result.state_finalization_decisions
    )
    assert all(
        allocation.logical_state_key is not None
        and allocation.typed_slot_id is not None
        and allocation.selected_version_id is not None
        for call in result.calls
        for allocation in call.returns
        if allocation.object_ref is not None
        and allocation.allocation_action != "reuse"
    )


def test_reconciliation_finalizer_receives_exact_state_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    captured_dependencies: list[ProjectedStateDependency] = []
    captured_step_scopes: dict[str, str] = {}
    original = StateFinalizationService.finalize_logical_graph

    def capture_dependencies(
        service: StateFinalizationService,
        writes: Any,
        **kwargs: Any,
    ) -> Any:
        captured_dependencies.extend(kwargs.get("dependencies", ()))
        captured_step_scopes.update(kwargs.get("step_scopes", {}))
        return original(service, writes, **kwargs)

    monkeypatch.setattr(
        StateFinalizationService,
        "finalize_logical_graph",
        capture_dependencies,
    )

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok
    assert captured_dependencies
    assert any(
        dependency.state_version_id is not None
        for dependency in captured_dependencies
    )
    expected_execution_scopes = {
        placement.canonical_call_id: placement.execution_scope_id
        for placement in result.call_placements
    }
    assert captured_step_scopes == expected_execution_scopes
    assert any(
        placement.declared_scope_id != placement.execution_scope_id
        for placement in result.call_placements
    )
    exact_dependency_edges = [
        (dependency.step_id, dependency.source_step_id)
        for dependency in captured_dependencies
        if dependency.source_step_id is not None
        and dependency.step_id in result.dependency_graph
        and dependency.source_step_id in result.dependency_graph
    ]
    assert exact_dependency_edges
    assert all(
        source_step_id in result.dependency_graph[consumer_step_id]
        for consumer_step_id, source_step_id in exact_dependency_edges
    )


def test_probe_dependency_graph_includes_inferred_version_producer() -> None:
    object_id = MathObjectId("point:problem:D", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        1,
    )
    transition_version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        2,
    )
    derived_version_id = StateVersionId(
        StateSlotId(logical_key, "problem"),
        3,
    )
    graph = (
        strategy_replay_module
        ._functional_dependency_graph_with_projected_versions(
            {
                "producer": (),
                "consumer": (),
                "transition": (),
                "derived": (),
            },
            projected_state_writes=(
                SimpleNamespace(
                    step_id="producer",
                    selected_version_id=version_id,
                    allocation_action="create",
                    previous_version_id=None,
                    source_version_ids=(),
                ),
                SimpleNamespace(
                    step_id="transition",
                    selected_version_id=transition_version_id,
                    allocation_action="transition",
                    previous_version_id=version_id,
                    source_version_ids=(),
                ),
                SimpleNamespace(
                    step_id="derived",
                    selected_version_id=derived_version_id,
                    allocation_action="create",
                    previous_version_id=None,
                    source_version_ids=(transition_version_id,),
                ),
            ),
            projected_state_dependencies=(
                ProjectedStateDependency(
                    step_id="consumer",
                    state_slot_id="point:problem:D.coordinate@problem:Point",
                    produced_handle="point:problem:D",
                    state_version_id=version_id,
                ),
            ),
        )
    )

    assert graph["consumer"] == ("producer",)
    assert graph["transition"] == ("producer",)
    assert graph["derived"] == ("transition",)
    assert strategy_replay_module._functional_dependency_closure(
        "consumer",
        graph,
    ) == {"producer", "consumer"}
    assert strategy_replay_module._functional_dependent_closure(
        {"producer"},
        graph,
    ) == {"producer", "consumer", "transition", "derived"}
    assert strategy_replay_module._ordered_functional_repair_cone(
        ("producer",),
        reconciliation=SimpleNamespace(
            plan=SimpleNamespace(
                calls=tuple(
                    SimpleNamespace(call_id=call_id)
                    for call_id in (
                        "producer",
                        "consumer",
                        "transition",
                        "derived",
                    )
                )
            ),
            dependency_graph=graph,
        ),
    ) == ("producer", "consumer", "transition", "derived")
    assert strategy_replay_module._functional_topological_call_ids(
        ("consumer", "derived", "transition", "producer"),
        graph,
    ) == ("producer", "consumer", "transition", "derived")


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


def test_functional_wire_drops_redundant_call_result_fields() -> None:
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["args"]["coefficient_relation"] = {
        "from_call": "derive_relation",
        "return": "condition",
        "type": "Condition",
    }

    plan, report = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=_base_inputs().question_goals,
    )

    assert report.ok and plan is not None
    assert plan.calls[0].args["coefficient_relation"] == (
        CallResultRef("derive_relation", "condition"),
    )
    assert report.deterministic_repairs == (
        {
            "call_id": "derive_axis_point",
            "action": "drop_redundant_call_result_fields",
            "fields": ["type"],
            "from": "presentational_metadata",
            "to": "omitted",
        },
    )


def test_functional_wire_drops_null_return_expectations_deterministically() -> None:
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["return_expectations"] = {
        "axis_point": None,
    }

    plan, report = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=_base_inputs().question_goals,
    )

    assert report.ok and plan is not None
    assert plan.calls[0].return_expectations == {}
    assert report.deterministic_repairs == (
        {
            "call_id": "derive_axis_point",
            "action": "drop_null_return_expectation",
            "return": "axis_point",
            "from": "null",
            "to": "omitted",
        },
    )


def test_functional_wire_drops_internal_binding_metadata_expectation() -> None:
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["return_expectations"] = {
        "parameter": "internal_only",
    }

    plan, report = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=_registry(),
        question_goals=_base_inputs().question_goals,
    )

    assert report.ok and plan is not None
    assert plan.calls[0].return_expectations == {}
    assert report.deterministic_repairs == (
        {
            "call_id": "derive_axis_point",
            "action": "drop_return_binding_metadata_expectation",
            "return": "parameter",
            "from": "internal_only",
            "to": "omitted",
        },
    )


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
                    "return": "straightened_endpoint_1",
                },
                "endpoint_2": {
                    "from_call": "ii_derive_path_model",
                    "return": "straightened_endpoint_2",
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
    assert replay.diagnostic is not None
    assert replay.diagnostic.runtime_results, replay.diagnostic
    distance_result = next(
        item
        for item in replay.diagnostic.runtime_results
        if item.step_id == "distance_of_selected_endpoints"
    )
    assert distance_result.output_key == "distance_between_points.distance"
    assert distance_result.runtime_type == "MinimumExpression"
    assert distance_result.value is not None
    assert "$" not in json.dumps(
        distance_result.to_payload(),
        ensure_ascii=False,
    )
    captured_types = {
        item.runtime_type for item in replay.diagnostic.runtime_results
    }
    assert {
        "Point",
        "Parabola",
        "ParameterValue",
        "PathTransformation",
    } <= captured_types
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


def test_straightened_distance_recipe_emits_base_and_evaluated_returns() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii_1")
    solve_index = next(
        index
        for index, call in enumerate(scope["calls"])
        if call["call_id"] == "ii_1_solve_m"
    )
    scope["calls"] = [
        call
        for call in scope["calls"]
        if call["call_id"] != "ii_1_evaluate_minimum"
    ]
    scope["calls"].insert(
        solve_index + 1,
        {
            "call_id": "evaluate_selected_endpoint_distance",
            "capability_id": "path_minimum_by_straightened_distance",
            "args": {
                "endpoint_1": {
                    "from_call": "ii_derive_path_model",
                    "return": "straightened_endpoint_1",
                },
                "endpoint_2": {
                    "from_call": "ii_derive_path_model",
                    "return": "straightened_endpoint_2",
                },
                "parameter_value": {
                    "from_call": "ii_1_solve_m",
                    "return": "parameter_value",
                },
            },
            "return_bindings": {
                "evaluated_path_minimum_expression": {
                    "kind": "answer",
                    "ref": "ii_1.minimum_value",
                }
            },
            "return_expectations": {
                "path_minimum_expression": "open_expression",
                "evaluated_path_minimum_expression": "closed_value",
            },
            "strategy": "Measure the endpoints before and after substitution.",
            "reason": "Both states are declared Macro returns.",
        },
    )
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
        if step_plan.step_id == "evaluate_selected_endpoint_distance"
        for invocation in step_plan.invocations
    )
    assert set(invocation.outputs) == {"distance", "evaluated_distance"}
    step_plan = next(
        item
        for item in replay.output.step_plans
        if item.step_id == "evaluate_selected_endpoint_distance"
    )
    assert invocation.outputs["distance"] in step_plan.promote_outputs
    assert "$subquestion.ii_1.outputs.min_value" in (
        step_plan.promote_outputs.values()
    )


def test_direct_distance_keeps_projected_base_return_for_closed_points() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii_1")
    scope["calls"] = [
        call
        for call in scope["calls"]
        if call["call_id"] != "ii_1_evaluate_minimum"
    ]
    scope["calls"].extend(
        [
            {
                "call_id": "evaluate_first_endpoint",
                "capability_id": "evaluate_point_at_parameter",
                "args": {
                    "point": {
                        "from_call": "ii_derive_path_model",
                        "return": "straightened_endpoint_1",
                    },
                    "parameter_value": {
                        "from_call": "ii_1_solve_m",
                        "return": "parameter_value",
                    },
                },
                "return_bindings": {},
                "strategy": "close the first endpoint",
                "reason": "prepare a numerical distance",
            },
            {
                "call_id": "evaluate_second_endpoint",
                "capability_id": "evaluate_point_at_parameter",
                "args": {
                    "point": {
                        "from_call": "ii_derive_path_model",
                        "return": "straightened_endpoint_2",
                    },
                    "parameter_value": {
                        "from_call": "ii_1_solve_m",
                        "return": "parameter_value",
                    },
                },
                "return_bindings": {},
                "strategy": "close the second endpoint",
                "reason": "prepare a numerical distance",
            },
            {
                "call_id": "measure_closed_endpoints",
                "capability_id": "distance_between_points",
                "args": {
                    "p1": {
                        "from_call": "evaluate_first_endpoint",
                        "return": "evaluated_point",
                    },
                    "p2": {
                        "from_call": "evaluate_second_endpoint",
                        "return": "evaluated_point",
                    },
                },
                "return_bindings": {
                    "distance": {
                        "kind": "answer",
                        "ref": "ii_1.minimum_value",
                    }
                },
                "return_expectations": {"distance": "closed_value"},
                "strategy": "measure the closed endpoints",
                "reason": "their distance is the required minimum",
            },
        ]
    )
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
        if step_plan.step_id == "measure_closed_endpoints"
        for invocation in step_plan.invocations
    )
    assert set(invocation.outputs) == {"distance"}
    assert "parameter_value" not in invocation.inputs
    assert not any(
        item["action"] == "auto_fill_optional_arg"
        and item["call_id"] == "measure_closed_endpoints"
        and "parameter_value" in item["after"]
        for item in replay.functional_reconciliation.elaboration[
            "deterministic_repairs"
        ]
    )


def test_macro_parabola_return_inherits_internal_closure_exclusions() -> None:
    inputs, registry, _context_value, payload = _hexi_case()
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "select_curve_candidate_ii"
    )
    call["return_bindings"]["solved_parabola"] = {
        "ref": "parabola",
        "kind": "function",
    }
    call["return_expectations"] = {
        "selected_curve_point": "closed_state",
        "solved_parabola": "closed_state",
    }
    problem = load_problem_ir(HEXI_FIXTURE)
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
        problem_payload=problem_to_llm_payload(problem),
        validation_report=validation,
    )

    assert replay.output is not None, replay.errors
    write = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.step_id == "select_curve_candidate_ii"
        and item.runtime_type == "Parabola"
    )
    assert write.closure_ignored_symbol_names == ("x",)
    event = next(
        item
        for item in replay.functional_reconciliation.result_form_events
        if item.call_id == "select_curve_candidate_ii"
        and item.return_name == "solved_parabola"
    )
    assert event.status == "matched"
    assert event.actual_form == "closed_state"


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
                    "return": "straightened_endpoint_1",
                },
                "endpoint_2": {
                    "from_call": "ii_derive_path_model",
                    "return": "straightened_endpoint_2",
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


def test_internal_point_list_binding_is_dropped_before_reconciliation() -> None:
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

    assert result.ok, [item.to_payload() for item in result.issues]
    effective = next(
        item
        for item in result.plan.calls
        if item.call_id == "derive_right_angle_candidates_ii"
    )
    assert effective.return_bindings == {}
    report = next(
        item
        for item in result.call_reports
        if item.call_id == "derive_right_angle_candidates_ii"
    )
    assert report.status == "valid"
    assert {
        "call_id": "derive_right_angle_candidates_ii",
        "action": "drop_internal_only_return_binding",
        "from": "candidates:point:D",
        "to": "derive_right_angle_candidates_ii.candidates",
    } in result.elaboration["deterministic_repairs"]


def test_context_role_conflict_is_typed_retry_issue() -> None:
    inputs, registry, context, payload = _hexi_case()
    candidate_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_right_angle_candidates_ii"
    )
    candidate_call["args"]["target"] = {"ref": "A", "kind": "point"}
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
        if item.code == "functional.context_resolver_conflict"
    )
    assert issue.call_id == "derive_right_angle_candidates_ii"
    assert issue.details == {
        "arg": "target",
        "wire_object_refs": ["point:problem:A"],
        "resolved_object_refs": ["point:ii:D"],
    }


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


def test_multiple_explicit_free_parameters_follow_unique_downstream_constraint() -> None:
    inputs, registry, context, payload = _hexi_case()
    producer = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_ii"
    )
    producer["args"]["free_parameters"] = [
        {"kind": "symbol", "ref": "b"},
        {"kind": "symbol", "ref": "c"},
    ]
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
        and item["from"] == "b,c"
        and item["to"] == "b"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_curve_candidate_recipe_does_not_steal_omitted_symbol_constraint() -> None:
    inputs, registry, _context, payload = _hexi_case()
    select_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "select_curve_candidate_ii"
    )
    select_call["args"].pop("symbol_constraint")
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
        context=ContextBuilder().build(load_problem_ir(HEXI_FIXTURE)),
        attempt=1,
        problem_payload=problem_to_llm_payload(load_problem_ir(HEXI_FIXTURE)),
        validation_report=validation,
    )

    assert replay.output is None
    assert replay.diagnostic is not None
    blocker = next(
        item
        for item in replay.diagnostic.blockers
        if item.step_id == "select_curve_candidate_ii"
    )
    assert blocker.code == "functional.candidate_selection_constraint_required"
    assert blocker.details is not None
    assert blocker.details["arg"] == "symbol_constraint"


def test_free_parameter_suppresses_same_symbol_value_auto_fill() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = replace(build_strategy_probe_inputs(problem), question_goals=[])
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "keep_parameter_open",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": {
                                "kind": "point",
                                "ref": "A",
                            },
                            "free_parameters": {
                                "kind": "symbol",
                                "ref": "a",
                            },
                        },
                        "return_bindings": {},
                        "return_expectations": {
                            "parabola": "open_state",
                        },
                        "strategy": "retain one independent coefficient",
                        "reason": "solve it from a later condition",
                    }
                ],
            }
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    context = replace(
        context,
        state=replace(
            context.state,
            state_slots=(
                *context.state.state_slots,
                StateSlot(
                    slot_id="symbol:problem:a.value@problem:ParameterValue",
                    object_ref="symbol:problem:a",
                    state_kind="value",
                    scope_id="problem",
                    runtime_type="ParameterValue",
                    canonical_handle="fact:problem:a_value",
                    aliases=("a",),
                    valid_scope="problem",
                    status="materialized",
                ),
            ),
        ),
    )
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    call = result.calls[0]
    assert "parameter_value" not in call.resolved_args
    assert "fact:problem:a_value" not in result.projected_draft.steps[0].reads
    assert any(
        item["action"] == "suppress_value_for_preserved_symbol"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_free_parameter_basis_follows_transitive_symbol_consumer() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)
    inputs, registry, context, payload = _hexi_case()
    producer = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_parametric_parabola_iii"
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

    assert result.ok, [item.to_payload() for item in result.issues]
    repaired = next(
        call
        for call in result.plan.calls
        if call.call_id == "derive_parametric_parabola_iii"
    )
    assert repaired.args["free_parameters"] == (
        SemanticRef(ref="b", kind="symbol"),
    )
    assert any(
        item["action"]
        == "align_free_parameter_basis_with_downstream_constraint"
        and item["call_id"] == producer["call_id"]
        for item in result.elaboration["deterministic_repairs"]
    )

    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=registry,
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_to_llm_payload(problem),
        validation_report=validation,
    )
    assert replay.output is not None, replay.errors
    assert replay.diagnostic is not None and replay.diagnostic.ok


def test_explicit_condition_target_removes_identity_ambiguity_not_missing_state() -> None:
    inputs, registry, context, payload = _hexi_case()
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii")
    scope["calls"] = [
        call
        for call in scope["calls"]
        if call["call_id"] != "derive_y_intercept_ii"
    ]
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

    issue_codes = {item.code for item in result.issues}
    assert "functional.condition.target_ambiguous" not in issue_codes
    assert "functional.condition_role_state_unavailable" in issue_codes


def test_point_binding_uses_latest_projected_version_by_graph_order() -> None:
    problem = _problem()
    registry = _registry()
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=(),
    )
    initial_handle = "fact:ii:N_coordinate"
    closed_handle = "fact:ii_2:N_closed_coordinate"
    initial_slot = "point:ii:N.coordinate@ii"
    closed_slot = "point:ii:N.coordinate@ii_2"
    writes = (
        ProjectedStateWrite(
            step_id="derive_N",
            produced_handle=initial_handle,
            state_slot_id=initial_slot,
            write_mode="create",
            runtime_type="Point",
            object_ref="point:ii:N",
        ),
        ProjectedStateWrite(
            step_id="close_N",
            produced_handle=closed_handle,
            state_slot_id=closed_slot,
            write_mode="transition",
            runtime_type="Point",
            object_ref="point:ii:N",
            source_state_slot_ids=(initial_slot,),
        ),
        ProjectedStateWrite(
            step_id="consume_N",
            produced_handle="fact:ii_2:distance",
            state_slot_id="functional:ii_2:distance",
            write_mode="value",
            runtime_type="Distance",
        ),
    )
    index.register_projected_state_writes(writes)
    index.register(
        initial_handle,
        "$question.ii.outputs.N_coordinate",
        "Point",
        source="test",
    )
    index.register(
        closed_handle,
        "$subquestion.ii_2.outputs.N_closed_coordinate",
        "Point",
        source="test",
    )
    step = StepIntent(
        step_id="consume_N",
        scope_id="ii_2",
        recipe_hint="distance_between_points",
        goal_type="derive_distance",
        target="fact:ii_2:distance",
        strategy="read the latest point state",
        # The older state intentionally appears last. Graph order remains
        # authoritative over incidental reads ordering.
        reads=(closed_handle, initial_handle, "point:ii:N"),
        produces=(
            ProducedFact(
                "fact:ii_2:distance",
                "ii_2",
                output_type="Distance",
            ),
        ),
    )

    assert _point_value_path_for_step("point:ii:N", step, index) == (
        "$subquestion.ii_2.outputs.N_closed_coordinate"
    )


def test_midpoint_state_becomes_stale_when_endpoint_version_advances() -> None:
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(_problem()),
        handle_registry=_registry(),
        question_goals=(),
    )
    initial_n_slot = "point:ii:N.coordinate@ii"
    writes = (
        ProjectedStateWrite(
            step_id="derive_N",
            produced_handle="fact:ii:N_coordinate",
            state_slot_id=initial_n_slot,
            write_mode="create",
            runtime_type="Point",
            object_ref="point:ii:N",
        ),
        ProjectedStateWrite(
            step_id="derive_F",
            produced_handle="fact:ii:F_coordinate",
            state_slot_id="point:ii:F.coordinate@ii",
            write_mode="create",
            runtime_type="Point",
            object_ref="point:ii:F",
            source_state_slot_ids=(initial_n_slot,),
        ),
        ProjectedStateWrite(
            step_id="close_N",
            produced_handle="fact:ii_2:N_closed_coordinate",
            state_slot_id="point:ii:N.coordinate@ii_2",
            write_mode="transition",
            runtime_type="Point",
            object_ref="point:ii:N",
            source_state_slot_ids=(initial_n_slot,),
        ),
        ProjectedStateWrite(
            step_id="consume_F",
            produced_handle="fact:ii_2:minimum",
            state_slot_id="functional:ii_2:minimum",
            write_mode="value",
            runtime_type="MinimumExpression",
        ),
    )
    index.register_projected_state_writes(writes)
    step = StepIntent(
        step_id="consume_F",
        scope_id="ii_2",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum",
        target="fact:ii_2:minimum",
        strategy="recompute derived states from the latest endpoint",
        reads=(
            "fact:ii_2:N_closed_coordinate",
            "fact:ii:N_coordinate",
            "point:ii:F",
        ),
        produces=(
            ProducedFact(
                "fact:ii_2:minimum",
                "ii_2",
                output_type="MinimumExpression",
            ),
        ),
    )

    assert _projected_midpoint_state_is_stale(
        "point:ii:F",
        step,
        index,
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
    assert (
        parameter_return.state_slot_id
        == "symbol:problem:b.value@ii:ParameterValue"
    )
    assert parameter_return.free_symbol_refs == ("symbol:problem:c",)
    parabola_return = next(
        item for item in refined.returns if item.return_name == "parabola"
    )
    assert parabola_return.free_symbol_refs == ("symbol:problem:c",)
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
    assert {
        item.binding_authority for item in sidecar
    } <= {"wire"}
    assert not {
        item.arg_name
        for item in sidecar
        if item.step_id == "derive_parametric_parabola_ii"
    } & {"quadratic", "x", "all_coefficients"}
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
    assert len(parabola_write.lineage.symbol_closures) == 1
    closure = parabola_write.lineage.symbol_closures[0]
    assert closure.target_object_ref == "symbol:problem:b"
    assert closure.dependency_object_refs == ("symbol:problem:c",)
    assert closure.expression == "1 - c"
    assert parameter_write.state_slot_id in closure.source_state_slot_ids
    assert parameter_write.produced_handle in closure.source_handles
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


def test_downstream_symbol_constraint_writes_single_free_basis_to_plan() -> None:
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
    assert normalized.args["free_parameters"] == (
        SemanticRef(ref="c", kind="symbol"),
    )
    assert binding_event.arg_repairs[0].source_handles == (
        "symbol:problem:c",
    )
    assert replay.functional_reconciliation is not None
    assert any(
        item["action"]
        == "align_free_parameter_basis_with_downstream_constraint"
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
) -> tuple[dict, ...]:
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
        {
            "call_id": f"{prefix}_derive_midpoint",
            "capability_id": "midpoint_point",
            "args": {
                "midpoint_definition": {
                    "ref": "F_midpoint_of_DN",
                    "kind": "fact",
                }
            },
            "return_bindings": {
                "midpoint": {
                    "ref": "F",
                    "kind": "point",
                }
            },
            "strategy": "derive the transformed fixed endpoint",
            "reason": "materialize the exact endpoint state used by path reduction",
        },
    )


def _path_reduction_setup_calls(
    call_id: str = "reduce_path",
) -> tuple[dict, ...]:
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
        "straightened_endpoint_1",
        "straightened_endpoint_2",
        "path_minimum_expression",
        "evaluated_path_minimum_expression",
    } == {item.name for item in path_macro.returns}
    auxiliary = next(
        item
        for item in path_macro.returns
        if item.name == "straightening_auxiliary_point"
    )
    assert auxiliary.equivalent_to == "straightened_endpoint_1"
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
    assert "一次放入 known_coefficients" in quadratic.use_when
    assert any(
        "不要逐个调用 evaluate_expression_at_parameter" in item
        for item in quadratic.do_not_use_when
    )
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
    evaluate_expression = catalog.get("evaluate_expression_at_parameter")
    assert evaluate_expression is not None
    evaluate_prompt = evaluate_expression.to_prompt_payload()
    assert "输入类型决定唯一 return" in evaluate_prompt["use_when"]
    assert any(
        "Function 模板" in item
        and "quadratic_from_constraints" in item
        for item in evaluate_prompt["do_not_use_when"]
    )
    assert any(
        "不会同时产生" in item or "同时产生" in item
        for item in evaluate_prompt["do_not_use_when"]
    )
    evaluate_args = {
        item["name"]: item for item in evaluate_prompt["args"]
    }
    assert "Function 模板不是已经得到的 Parabola" in (
        evaluate_args["expression"]["desc"]
    )
    evaluate_returns = {
        item["name"]: item for item in evaluate_prompt["returns"]
    }
    assert "仅当输入是 Expression" in (
        evaluate_returns["evaluated_expression"]["desc"]
    )
    assert "仅当输入已经是 Parabola" in (
        evaluate_returns["evaluated_parabola"]["desc"]
    )
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
        "straightened_endpoint_1" in item
        and "Point 答案" in item
        for item in straightening["do_not_use_when"]
    )
    assert any(
        "evaluated_path_minimum_expression" in item
        and "内部拉直端点" in item
        for item in straightening["do_not_use_when"]
    )
    assert "路径等价变换" in straightening_args["path_transformation"]["desc"]
    straightening_returns = {
        item["name"]: item for item in straightening["returns"]
    }
    for role in ("straightened_endpoint_1", "straightened_endpoint_2"):
        assert straightening_returns[role]["binding"] == "internal_only"
        assert "不是原路径动点、极值点或答案点" in (
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
    point_at_x = next(
        item
        for item in capabilities
        if item["capability_id"] == "point_on_parabola_at_x"
    )
    assert "结构化 definition.x" in point_at_x["use_when"]
    assert "strategy/reason" in point_at_x["use_when"]
    assert "return" in point_at_x["use_when"]
    assert any(
        "多个有坐标的候选点" in item
        for item in point_at_x["do_not_use_when"]
    )
    assert any(
        "仅知道点在抛物线上" in item
        and "strategy/reason" in item
        for item in point_at_x["do_not_use_when"]
    )
    assert "必须已经在题面结构化定义中直接给出" in (
        point_at_x["returns"][0]["desc"]
    )
    assert "同一个 Point 对象" in point_at_x["returns"][0]["desc"]
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
    assert "分别绑定 V3、V4" in square_vertex["returns"][0]["desc"]
    assert square_vertex["returns"][0]["binding"] == (
        "explicit_answer_or_existing_object"
    )
    assert any(
        "return_bindings.point" in item
        for item in square_vertex["do_not_use_when"]
    )
    assert "return_bindings.point" in square_vertex["use_when"]
    assert "顶点顺序" in square_vertex["use_when"]


def test_square_vertex_requires_explicit_return_identity() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    square_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["capability_id"] == "square_adjacent_vertex_from_side"
    )
    square_call["return_bindings"] = {}
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
        if item.call_id == square_call["call_id"]
        and item.code == "functional.return_identity_unresolved"
    )
    assert issue.details is not None
    assert issue.details["binding_requirement"] == (
        "explicit_answer_or_existing_object"
    )
    assert "CallResultRef" in issue.details["repair_guidance"]
    assert square_call["call_id"] not in {
        call.call_id for call in result.calls
    }


def test_compiler_owned_point_target_is_not_projected_as_state_read() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
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
    assert result.ok
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    dependencies = (
        strategy_replay_module._functional_projected_state_dependencies(
            result,
            catalog=catalog,
        )
    )
    square_call_ids = {
        call.call_id
        for call in result.calls
        if call.capability_id == "square_adjacent_vertex_from_side"
    }

    assert square_call_ids
    assert not any(
        dependency.step_id in square_call_ids
        and dependency.arg_name == "target"
        for dependency in dependencies
    )
    projected_by_id = {
        step.step_id: step for step in result.projected_draft.steps
    }
    for call in result.calls:
        if call.call_id not in square_call_ids:
            continue
        for allocation in call.returns:
            if (
                allocation.write_mode == "create"
                and allocation.object_ref is not None
            ):
                assert (
                    allocation.object_ref
                    not in projected_by_id[call.call_id].reads
                )


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


def test_reconciler_merges_same_object_binding_for_single_return_capability() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["return_bindings"]["point"] = {
        "ref": "D",
        "kind": "point",
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
        item
        for item in result.plan.calls
        if item.call_id == "derive_axis_point"
    )
    assert set(effective_call.return_bindings) == {"axis_point"}
    assert effective_call.return_bindings["axis_point"].kind == "answer"
    assert {
        "call_id": "derive_axis_point",
        "action": "merge_unique_return_projection_binding",
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
    assert effective_call.return_expectations == {
        "axis_point": "closed_state"
    }
    assert {
        "call_id": "derive_axis_point",
        "action": "normalize_answer_result_form",
        "from": "axis_point=closed_value",
        "to": "closed_state",
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
    assert effective.return_expectations["straightened_endpoint_1"] == "open_state"
    assert effective.return_expectations["straightened_endpoint_2"] == "open_state"
    assert {
        "call_id": "ii_derive_path_model",
        "action": "drop_intermediate_open_expression_answer_binding",
        "from": "ii_1.minimum_value",
        "to": "ii_1_evaluate_minimum.evaluated_minimum_expression",
    } in result.elaboration["deterministic_repairs"]


def test_straightening_endpoint_return_aliases_are_normalized_with_consumers() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    source = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_derive_path_model"
    )
    source["return_expectations"]["straightening_endpoint_1"] = "open_state"
    ii_1_scope = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "ii_1"
    )
    ii_1_scope["calls"].append(
        {
            "call_id": "ii_evaluate_endpoint_alias",
            "capability_id": "evaluate_point_at_parameter",
            "args": {
                "point": {
                    "from_call": "ii_derive_path_model",
                    "return": "straightening_endpoint_1",
                },
                "parameter_value": {
                    "from_call": "ii_1_solve_m",
                    "return": "parameter_value",
                },
            },
            "return_bindings": {},
            "strategy": "evaluate one straightened endpoint",
            "reason": "exercise the shared return-role vocabulary",
        }
    )
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None

    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    normalized, repairs = (
        functional_reconciliation_module
        ._normalize_declared_return_role_aliases(
            plan,
            catalog=catalog,
        )
    )
    effective_source = next(
        call
        for call in normalized.calls
        if call.call_id == "ii_derive_path_model"
    )
    effective_consumer = next(
        call
        for call in normalized.calls
        if call.call_id == "ii_evaluate_endpoint_alias"
    )

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    assert "straightening_endpoint_1" not in (
        effective_source.return_expectations
    )
    assert (
        effective_consumer.args["point"][0].return_name
        == "straightened_endpoint_1"
    )
    assert any(
        item.action == "normalize_declared_return_role_alias"
        for item in repairs
    )


def test_open_expression_answer_binding_is_normalized_for_runtime_verification() -> None:
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

    assert "functional.return_expectation_answer_conflict" not in {
        item.code for item in result.issues
    }
    effective = next(
        item for item in result.plan.calls if item.call_id == "ii_derive_path_model"
    )
    assert effective.return_expectations["path_minimum_expression"] == (
        "closed_value"
    )
    assert {
        "call_id": "ii_derive_path_model",
        "action": "normalize_answer_result_form",
        "from": "path_minimum_expression=open_expression",
        "to": "closed_value",
    } in result.elaboration["deterministic_repairs"]


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


def test_elaborator_renames_unknown_arg_to_unique_compatible_required_arg() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_x_intercept_A_i"
    )
    call["args"]["parabola"] = call["args"].pop("quadratic")
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )

    first = FunctionalPlanElaborator().elaborate(
        plan,
        catalog=catalog,
        semantic_index=FunctionalSemanticIndex.from_context(
            context,
            handle_registry=registry,
        ),
    )

    assert first.ok
    elaborated = next(
        item
        for item in first.plan.calls
        if item.call_id == "derive_x_intercept_A_i"
    )
    assert "parabola" not in elaborated.args
    assert elaborated.args["quadratic"] == (
        CallResultRef("derive_parabola_i", "parabola"),
    )
    assert any(
        item.call_id == elaborated.call_id
        and item.action == "rename_unique_type_compatible_required_arg"
        and item.from_value == "parabola"
        and item.to_value == "quadratic"
        for item in first.deterministic_repairs
    )

    second = FunctionalPlanElaborator().elaborate(
        first.plan,
        catalog=catalog,
        semantic_index=FunctionalSemanticIndex.from_context(
            context,
            handle_registry=registry,
        ),
    )
    assert second.plan.to_payload() == first.plan.to_payload()
    assert second.deterministic_repairs == ()


def test_elaborator_does_not_guess_between_compatible_required_args() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope(
                "ii_1",
                "ii_1",
                (
                    FunctionalCall(
                        call_id="ambiguous_distance",
                        capability_id="distance_between_points",
                        args={
                            "endpoint": (
                                SemanticRef(ref="M", kind="point"),
                            )
                        },
                        return_bindings={},
                        strategy="compute a distance",
                        reason="exercise ambiguous representation repair",
                    ),
                ),
            ),
        ),
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

    assert result.plan.calls[0].args == plan.calls[0].args
    assert not any(
        item.action == "rename_unique_type_compatible_required_arg"
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


def test_closed_internal_return_expectation_blocks_open_runtime_state() -> None:
    """A closed expectation cannot hide a still-open internal state."""
    inputs, _payload, _registry, _context_value = _heping_ermo_case()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    call = FunctionalCall(
        call_id="straighten_path",
        capability_id="broken_path_straightening_minimum_expression",
        args={},
        return_bindings={},
        strategy="derive internal endpoints",
        reason="exercise advisory internal result forms",
        return_expectations={"straightened_endpoint_2": "closed_state"},
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (call,)),),
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="straightened_endpoint_2",
        handle="fact:part:internal_endpoint",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:endpoint.coordinate@part",
        object_ref="point:part:endpoint",
        identity_policy="derived_role",
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
                output_key="straightened_endpoint_2",
                runtime_type="Point",
                object_ref=allocation.object_ref,
                identity_policy="derived_role",
                identity_role="straightened_endpoint_2",
                write_mode="create",
                free_symbol_names=("c",),
            ),
        ),
    )

    events, issues = verify_functional_result_forms(
        plan,
        reconciliation,
        diagnostic,
        catalog=catalog,
    )
    canonical = canonicalize_verified_result_forms(plan, events)

    assert [item.code for item in issues] == [
        "functional.return_form_mismatch"
    ]
    assert events[0].status == "mismatch"
    assert canonical.calls[0].return_expectations == {
        "straightened_endpoint_2": "closed_state"
    }


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
        "lineage": state_semantic_lineage(
            semantic_roles=("axis_x_intercept",),
        ),
    }
    open_allocation = FunctionalReturnAllocation(
        call_id=open_call.call_id,
        handle="fact:part:target_symbolic_coordinate",
        free_symbol_refs=("symbol:part:parameter",),
        **shared,
    )
    closed_shared = {
        **shared,
        "source_state_slot_ids": ("function:part:curve.expression@part",),
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
    assert "point:part:target.coordinate@part" in refined.source_state_slot_ids


def test_return_symbol_flow_uses_current_states_over_relation_history() -> None:
    symbol_ref = "symbol:part:t"
    relation = ResolvedFunctionalValue(
        handle="fact:part:midpoint_definition",
        runtime_type="Condition",
        valid_scope="part",
        condition_id="condition:midpoint@part",
        object_roles=(
            ("midpoint", ("point:part:midpoint",)),
            ("endpoint", ("point:part:left", "point:part:right")),
        ),
        free_symbol_refs=(symbol_ref,),
    )
    left = ResolvedFunctionalValue(
        handle="fact:part:left_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:left.coordinate@part",
        object_ref="point:part:left",
    )
    right = ResolvedFunctionalValue(
        handle="fact:part:right_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:right.coordinate@part",
        object_ref="point:part:right",
    )

    assert return_free_symbol_refs(
        "Point",
        {
            "midpoint_definition": (relation,),
            "p1": (left,),
            "p2": (right,),
        },
        object_ref="point:part:midpoint",
    ) == ()

    open_right = replace(right, free_symbol_refs=(symbol_ref,))
    assert return_free_symbol_refs(
        "Point",
        {
            "midpoint_definition": (relation,),
            "p1": (left,),
            "p2": (open_right,),
        },
        object_ref="point:part:midpoint",
    ) == (symbol_ref,)

    equation = replace(relation, object_roles=())
    assert return_free_symbol_refs(
        "Parabola",
        {"coefficient_relation": (equation,)},
        object_ref="function:part:curve",
    ) == (symbol_ref,)


def test_return_symbol_flow_can_ignore_scalar_only_parameter_inputs() -> None:
    symbol_ref = "symbol:part:m"
    endpoint = ResolvedFunctionalValue(
        handle="fact:part:straightened_endpoint",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:endpoint.coordinate@part",
        object_ref="point:part:endpoint",
        free_symbol_refs=(symbol_ref,),
    )
    parameter_value = ResolvedFunctionalValue(
        handle="fact:part:m_value",
        runtime_type="ParameterValue",
        valid_scope="part",
        state_slot_id="symbol:part:m.value@part",
        object_ref=symbol_ref,
    )

    assert return_free_symbol_refs(
        "Point",
        {
            "path_transformation": (endpoint,),
            "parameter_value": (parameter_value,),
        },
        object_ref="point:part:endpoint",
        ignored_input_args=("parameter_value",),
    ) == (symbol_ref,)


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
            resolved_args={
                "quadratic": (
                    ResolvedFunctionalValue(
                        handle="fact:part:initial_curve",
                        runtime_type="Parabola",
                        valid_scope="part",
                        state_slot_id=slot_id,
                        source_call_id="initial_state",
                        return_name="parabola",
                        object_ref="function:part:curve",
                    ),
                ),
            },
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


def test_object_state_refinement_reuses_immutable_symbol_identity() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability_id = "quadratic_axis_parameterized_point"
    calls = tuple(
        FunctionalCall(
            call_id=call_id,
            capability_id=capability_id,
            args={},
            return_bindings={},
            strategy="publish the same internal parameter identity",
            reason="synthetic immutable identity reuse",
        )
        for call_id in ("parameterize_open", "parameterize_closed")
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", calls),),
    )
    slot_id = "symbol:part:axis_parameter.parameter@part"
    common = {
        "return_name": "parameter",
        "runtime_type": "Symbol",
        "valid_scope": "part",
        "state_slot_id": slot_id,
        "object_ref": "symbol:part:axis_parameter",
        "identity_policy": "derived_role",
        "write_mode": "value",
        "free_symbol_refs": ("symbol:part:axis_parameter",),
        "dependency_object_refs": ("point:part:target",),
        "lineage": state_semantic_lineage(
            semantic_roles=("axis_parameter",),
        ),
    }
    reconciled = tuple(
        FunctionalCallReconciliation(
            call_id=call.call_id,
            scope_id="part",
            capability_id=capability_id,
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    handle=f"fact:part:{call.call_id}_axis_parameter",
                    source_state_slot_ids=(
                        f"function:part:curve_{index}.expression@part",
                    ),
                    **common,
                ),
            ),
        )
        for index, call in enumerate(calls)
    )

    result = refine_functional_object_states(
        plan,
        reconciled=reconciled,
        catalog=catalog,
    )

    refined = result.calls[1].returns[0]
    assert refined.write_mode == "transition"
    assert refined.transition_kind == "direct"
    assert refined.previous_write_step_id == "parameterize_open"
    assert slot_id in refined.source_state_slot_ids


def test_object_state_refinement_does_not_close_a_new_companion_symbol() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability_id = "quadratic_axis_parameterized_point"
    calls = tuple(
        FunctionalCall(
            call_id=call_id,
            capability_id=capability_id,
            args={},
            return_bindings={},
            strategy="parameterize the same object again",
            reason="synthetic companion-symbol guard",
        )
        for call_id in ("parameterize_open", "parameterize_again")
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", calls),),
    )
    point_slot = "point:part:target.coordinate@part"
    symbol_slot = "symbol:part:axis_parameter.parameter@part"
    reconciled = tuple(
        FunctionalCallReconciliation(
            call_id=call.call_id,
            scope_id="part",
            capability_id=capability_id,
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="point",
                    handle=f"fact:part:{call.call_id}_coordinate",
                    runtime_type="Point",
                    valid_scope="part",
                    state_slot_id=point_slot,
                    object_ref="point:part:target",
                    identity_policy="target_object",
                    write_mode="create",
                    free_symbol_refs=(
                        ("symbol:part:t",) if index == 0 else ()
                    ),
                    source_state_slot_ids=(
                        f"function:part:curve_{index}.expression@part",
                    ),
                    dependency_object_refs=("function:part:curve",),
                    lineage=state_semantic_lineage(
                        semantic_roles=("axis_point",),
                    ),
                ),
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="parameter",
                    handle=f"fact:part:{call.call_id}_axis_parameter",
                    runtime_type="Symbol",
                    valid_scope="part",
                    state_slot_id=symbol_slot,
                    object_ref="symbol:part:axis_parameter",
                    identity_policy="derived_role",
                    write_mode="value",
                    free_symbol_refs=("symbol:part:axis_parameter",),
                    dependency_object_refs=("point:part:target",),
                    lineage=state_semantic_lineage(
                        semantic_roles=("axis_parameter",),
                    ),
                ),
            ),
        )
        for index, call in enumerate(calls)
    )

    result = refine_functional_object_states(
        plan,
        reconciled=reconciled,
        catalog=catalog,
    )

    point_write = result.calls[1].returns[0]
    assert point_write.write_mode == "create"
    assert point_write.transition_kind is None


def test_parameterized_object_inherits_declared_sibling_symbol_dependency() -> None:
    inputs = build_strategy_probe_inputs(load_problem_ir(HEPING_ERMO_FIXTURE))
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["quadratic_axis_parameterized_point"]
    point = FunctionalReturnAllocation(
        call_id="parameterize_target",
        return_name="point",
        handle="fact:part:target_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        object_ref="point:part:target",
        identity_policy="target_object",
        write_mode="create",
        free_symbol_refs=("symbol:problem:c",),
    )
    parameter = FunctionalReturnAllocation(
        call_id="parameterize_target",
        return_name="parameter",
        handle="fact:part:target_axis_parameter",
        runtime_type="Symbol",
        valid_scope="part",
        state_slot_id="symbol:part:target_axis_parameter.parameter@part",
        object_ref="symbol:part:target_axis_parameter",
        identity_policy="derived_role",
        write_mode="value",
    )

    projected = project_sibling_symbol_dependencies(
        capability.returns,
        (point, parameter),
        capability_id=capability.capability_id,
    )

    projected_point = projected[0]
    assert projected_point.free_symbol_refs == (
        "symbol:problem:c",
        "symbol:part:target_axis_parameter",
    )
    assert projected_point.dependency_object_refs == (
        "symbol:part:target_axis_parameter",
    )
    assert projected_point.source_state_slot_ids == (
        "symbol:part:target_axis_parameter.parameter@part",
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


def test_object_state_refinement_keeps_unsubstituted_companion_symbol_open() -> None:
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
        strategy="substitute one of two independent parameters",
        reason="synthetic partial-closure guard",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("part", "part", (call,)),),
    )
    substituted_symbol = "symbol:part:u"
    companion_symbol = "symbol:part:v"
    source_point = ResolvedFunctionalValue(
        handle="fact:part:target_open_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        source_call_id="derive_target",
        return_name="point",
        object_ref="point:part:target",
        free_symbol_refs=(substituted_symbol, companion_symbol),
    )
    parameter_value = ResolvedFunctionalValue(
        handle="fact:part:u_value",
        runtime_type="ParameterValue",
        valid_scope="part",
        state_slot_id=f"{substituted_symbol}.value@part",
        source_call_id="solve_u",
        return_name="parameter_value",
        object_ref=substituted_symbol,
    )
    allocation = FunctionalReturnAllocation(
        call_id=call.call_id,
        return_name="evaluated_point",
        handle="fact:part:target_partially_evaluated_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part",
        object_ref="point:part:target",
        identity_policy="preserve_input_object",
        write_mode="transition",
        free_symbol_refs=(companion_symbol,),
        source_state_slot_ids=(
            "point:part:target.coordinate@part",
            f"{substituted_symbol}.value@part",
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
        "evaluated_point": "open_state"
    }
    assert any(
        repair.action == "infer_object_result_form"
        and repair.to_value == "open_state"
        for repair in result.repairs
    )


def test_liveness_rebases_transition_to_latest_surviving_version() -> None:
    object_id = MathObjectId("point:part:target", "point", "part")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "part")
    version_1 = StateVersionId(slot_id, 1)
    removed_version_2 = StateVersionId(slot_id, 2)
    version_3 = StateVersionId(slot_id, 3)
    create = FunctionalReturnAllocation(
        call_id="create_target",
        return_name="point",
        handle="fact:part:target_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part:Point",
        object_ref=object_id.value,
        identity_policy="target_object",
        write_mode="create",
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        selected_version_id=version_1,
    )
    transition = FunctionalReturnAllocation(
        call_id="close_target",
        return_name="evaluated_point",
        handle="fact:part:target_closed_coordinate",
        runtime_type="Point",
        valid_scope="part",
        state_slot_id="point:part:target.coordinate@part:Point",
        object_ref=object_id.value,
        identity_policy="preserve_input_object",
        write_mode="transition",
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        selected_version_id=version_3,
        previous_version_id=removed_version_2,
        previous_write_step_id="removed_refinement",
        source_version_ids=(removed_version_2,),
        computation_key=ComputationKey(
            "evaluate_point_at_parameter",
            (
                ArgVersionBinding(
                    arg_name="point",
                    item_index=0,
                    version_id=removed_version_2,
                ),
            ),
        ),
    )
    calls = (
        FunctionalCallReconciliation(
            call_id="create_target",
            scope_id="part",
            capability_id="construct_point",
            resolved_args={},
            returns=(create,),
        ),
        FunctionalCallReconciliation(
            call_id="close_target",
            scope_id="part",
            capability_id="evaluate_point_at_parameter",
            resolved_args={},
            returns=(transition,),
        ),
    )

    rebased_calls, rebases = rebase_live_state_versions(calls)

    updated = rebased_calls[1].returns[0]
    assert updated.previous_version_id == version_1
    assert updated.previous_write_step_id == "create_target"
    assert updated.source_version_ids == (version_1,)
    assert updated.computation_key is not None
    assert updated.computation_key.arg_bindings[0].version_id == version_1
    assert rebases[0].removed_previous_version_id == removed_version_2
    assert rebases[0].selected_previous_version_id == version_1


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


def test_return_consumer_scope_exports_child_result_without_hoisting_call() -> None:
    producer = FunctionalCall(
        call_id="produce_child_result",
        capability_id="synthetic_producer",
        args={},
        return_bindings={},
        strategy="derive a reusable result from child-only inputs",
        reason="exercise per-return publication",
    )
    consumer = FunctionalCall(
        call_id="consume_in_sibling",
        capability_id="synthetic_consumer",
        args={
            "value": (
                CallResultRef(
                    from_call=producer.call_id,
                    return_name="result",
                ),
            )
        },
        return_bindings={},
        strategy="consume the result in a sibling scope",
        reason="exercise cross-question reuse",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope("ii_1", "ii_1", (producer,)),
            FunctionalScope("ii_2", "ii_2", (consumer,)),
        )
    )
    produced = ResolvedFunctionalValue(
        handle="fact:ii_1:result",
        runtime_type="Expression",
        valid_scope="ii_1",
        source_call_id=producer.call_id,
        return_name="result",
    )
    reconciled = {
        producer.call_id: FunctionalCallReconciliation(
            call_id=producer.call_id,
            scope_id="ii_1",
            capability_id=producer.capability_id,
            resolved_args={},
            returns=(),
        ),
        consumer.call_id: FunctionalCallReconciliation(
            call_id=consumer.call_id,
            scope_id="ii_2",
            capability_id=consumer.capability_id,
            resolved_args={"value": (produced,)},
            returns=(),
        ),
    }

    scopes = functional_call_placement_module._return_consumer_scopes(
        plan,
        reconciled=reconciled,
        aliases={},
        execution_scopes={
            producer.call_id: "ii_1",
            consumer.call_id: "ii_2",
        },
    )

    assert scopes == {(producer.call_id, "result"): ("ii_2",)}


def test_fixed_branch_scope_forces_hoisted_consumer_back_to_visible_scope() -> None:
    producer = FunctionalCall(
        call_id="build_branch_state",
        capability_id="synthetic_producer",
        args={},
        return_bindings={},
        strategy="build a branch-private state",
        reason="exercise fixed placement",
    )
    consumer = FunctionalCall(
        call_id="consume_branch_state",
        capability_id="synthetic_consumer",
        args={},
        return_bindings={},
        strategy="consume the branch-private state",
        reason="exercise visibility fallback",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("ii", "ii", (producer, consumer)),),
    )
    produced = ResolvedFunctionalValue(
        handle="fact:ii:branch_state",
        runtime_type="Parabola",
        valid_scope="ii",
        source_call_id=producer.call_id,
        return_name="parabola",
    )
    reconciled = {
        producer.call_id: FunctionalCallReconciliation(
            call_id=producer.call_id,
            scope_id="ii",
            capability_id=producer.capability_id,
            resolved_args={},
            returns=(),
        ),
        consumer.call_id: FunctionalCallReconciliation(
            call_id=consumer.call_id,
            scope_id="ii",
            capability_id=consumer.capability_id,
            resolved_args={"parabola": (produced,)},
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
            producer.call_id: "ii",
            consumer.call_id: "problem",
        },
        declared_scopes={
            producer.call_id: "ii",
            consumer.call_id: "ii",
        },
        aliases={},
        registry=_registry(),
        fixed_scopes={producer.call_id: "ii"},
    )

    assert scopes == {
        producer.call_id: "ii",
        consumer.call_id: "ii",
    }


def test_branch_private_scope_pins_first_create_and_later_isolated_writer() -> None:
    object_id = MathObjectId("function:problem:curve", "function", "problem")
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    left_slot = StateSlotId(logical_key, "ii_1")
    right_slot = StateSlotId(logical_key, "i")
    reconciled = {
        "build_left": SimpleNamespace(
            returns=(
                SimpleNamespace(
                    logical_state_key=logical_key,
                    typed_slot_id=left_slot,
                    allocation_action="create",
                    selected_version_id=StateVersionId(left_slot, 1),
                ),
            )
        ),
        "build_right": SimpleNamespace(
            returns=(
                SimpleNamespace(
                    logical_state_key=logical_key,
                    typed_slot_id=right_slot,
                    allocation_action="isolated",
                    selected_version_id=StateVersionId(right_slot, 1),
                ),
            )
        ),
    }

    assert (
        functional_call_placement_module
        ._branch_private_state_storage_scopes(
                reconciled,
                consumer_scopes={"build_left": ("ii_2",)},
                registry=_registry(),
            )
        == {"build_left": "ii", "build_right": "i"}
    )


def test_isolated_branch_scope_does_not_widen_for_parent_consumer() -> None:
    object_id = MathObjectId("function:problem:curve", "function", "problem")
    logical_key = LogicalStateKey(object_id, "expression", "Parabola")
    closed_slot = StateSlotId(logical_key, "i")
    open_slot = StateSlotId(logical_key, "ii")
    reconciled = {
        "closed_branch": SimpleNamespace(
            returns=(
                SimpleNamespace(
                    logical_state_key=logical_key,
                    typed_slot_id=closed_slot,
                    allocation_action="create",
                    selected_version_id=StateVersionId(closed_slot, 1),
                ),
            )
        ),
        "open_branch": SimpleNamespace(
            returns=(
                SimpleNamespace(
                    logical_state_key=logical_key,
                    typed_slot_id=open_slot,
                    allocation_action="isolated",
                    selected_version_id=StateVersionId(open_slot, 1),
                ),
            )
        ),
    }

    scopes = (
        functional_call_placement_module
        ._branch_private_state_storage_scopes(
            reconciled,
            consumer_scopes={
                "closed_branch": ("i",),
                "open_branch": ("problem",),
            },
            registry=_registry(),
        )
    )

    assert scopes == {
        "closed_branch": "i",
        "open_branch": "ii",
    }


def test_target_object_origin_moves_parent_declared_call_to_child_scope() -> None:
    target = MathObjectId("point:ii:target", "point", "ii")
    reconciliation = FunctionalCallReconciliation(
        call_id="materialize_target",
        scope_id="problem",
        capability_id="synthetic_target",
        resolved_args={},
        returns=(
            FunctionalReturnAllocation(
                call_id="materialize_target",
                return_name="point",
                handle="point:ii:target",
                runtime_type="Point",
                valid_scope="problem",
                state_slot_id="compat:target",
                object_ref=target.value,
                identity_policy="target_object",
                write_mode="create",
                math_object_id=target,
            ),
        ),
    )

    target_scopes = (
        functional_call_placement_module._state_target_object_scopes(
            reconciliation,
            base_identity_index=None,
        )
    )
    execution_scope = functional_call_placement_module._call_execution_scope(
        declared_scopes=("problem",),
        destination_scopes=(),
        answer_scopes=(),
        answer_target_scopes=(),
        state_target_scopes=target_scopes,
        registry=_registry(),
    )

    assert target_scopes == ("ii",)
    assert execution_scope == "ii"


def test_pinned_return_scope_restores_semantic_state_dependency_before_retry() -> None:
    point_d = MathObjectId("point:problem:D", "point", "problem")
    point_c = MathObjectId("point:problem:C", "point", "problem")
    key_d = LogicalStateKey(point_d, "coordinate", "Point")
    key_c = LogicalStateKey(point_c, "coordinate", "Point")
    slot_d = StateSlotId(key_d, "problem")
    slot_c = StateSlotId(key_c, "ii")
    version_d = StateVersionId(slot_d, 1)
    version_c = StateVersionId(slot_c, 1)
    consumer = FunctionalCall(
        call_id="consume_D",
        capability_id="consume_point",
        args={},
        return_bindings={},
        strategy="consume a materialized point",
        reason="exercise retry ordering",
    )
    producer = FunctionalCall(
        call_id="produce_D",
        capability_id="produce_point",
        args={},
        return_bindings={},
        strategy="produce the point",
        reason="exercise retry ordering",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope("i", "i", (consumer,)),
            FunctionalScope("ii", "ii", (producer,)),
        )
    )
    reconciled = {
        "consume_D": FunctionalCallReconciliation(
            call_id="consume_D",
            scope_id="i",
            capability_id="consume_point",
            resolved_args={
                "point": (
                    ResolvedFunctionalValue(
                        handle="point:problem:D",
                        runtime_type="Point",
                        valid_scope="i",
                        object_ref=point_d.value,
                        math_object_id=point_d,
                    ),
                )
            },
            returns=(),
        ),
        "produce_D": FunctionalCallReconciliation(
            call_id="produce_D",
            scope_id="ii",
            capability_id="produce_point",
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id="produce_D",
                    return_name="point",
                    handle="fact:ii:D_coordinate",
                    runtime_type="Point",
                    valid_scope="ii",
                    state_slot_id="compat:D",
                    object_ref=point_d.value,
                    identity_policy="target_object",
                    write_mode="create",
                    math_object_id=point_d,
                    logical_state_key=key_d,
                    typed_slot_id=slot_d,
                    selected_version_id=version_d,
                    source_version_ids=(version_c,),
                    allocation_action="create",
                ),
            ),
        ),
    }

    dependencies = (
        functional_call_placement_module
        ._semantic_object_return_dependencies(
            plan,
            reconciled=reconciled,
            dependency_graph={},
            handle_registry=_registry(),
            pinned_return_scopes={
                "produce_D": {"point": "problem"},
            },
        )
    )

    assert dependencies == {"consume_D": (("produce_D", "point"),)}


def test_committed_scope_pin_overrides_new_branch_private_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["return_bindings"] = {
        "axis_point": {"ref": "D", "kind": "point"}
    }
    plan, report = _validate(payload, inputs)
    assert report.ok and plan is not None

    monkeypatch.setattr(
        functional_call_placement_module,
        "_branch_private_state_storage_scopes",
        lambda *_args, **_kwargs: {"derive_axis_point": "i"},
    )
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=(),
        pinned_canonical_call_ids=("derive_axis_point",),
        pinned_execution_scopes={"derive_axis_point": "problem"},
        pinned_return_scopes={
            "derive_axis_point": {"axis_point": "problem"}
        },
    )

    assert result.ok, [item.to_payload() for item in result.issues]
    placement = next(
        item
        for item in result.call_placements
        if item.canonical_call_id == "derive_axis_point"
    )
    assert placement.execution_scope_id == "problem"
    assert placement.return_scopes["axis_point"] == "problem"


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
        ("transformed_fixed_endpoint", "transformed_fixed_endpoint"),
        ("moving_locus_endpoint_1", "moving_locus_endpoint_1"),
        ("moving_locus_endpoint_2", "moving_locus_endpoint_2"),
    }
    assert "context_arg_bindings" not in right_angle.to_prompt_payload()


def test_derived_role_identity_is_call_scoped() -> None:
    first = derived_role_object_ref(
        call_id="derive_first_path",
        semantic_role="straightened_endpoint_1",
        scope_id="ii_2",
        runtime_type="Point",
    )
    second = derived_role_object_ref(
        call_id="derive_second_path",
        semantic_role="straightened_endpoint_1",
        scope_id="ii_2",
        runtime_type="Point",
    )

    assert first == "point:ii_2:derive_first_path_straightened_endpoint_1"
    assert second == "point:ii_2:derive_second_path_straightened_endpoint_1"
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
        "parameter_value",
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
    prompt_reduction = reduction.to_prompt_payload()
    assert "每个固定端点都必须已有可读取的 Point 坐标状态" in (
        prompt_reduction["use_when"]
    )
    assert any(
        "仅有定义、构造或中点关系" in item
        for item in prompt_reduction["do_not_use_when"]
    )
    guidance_payload = json.dumps(prompt_reduction, ensure_ascii=False)
    assert "点 F" not in guidance_payload
    assert "F 点" not in guidance_payload
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
    square_prompt = square_reduction.to_prompt_payload()
    assert "原目标路径恰好由三段组成" in square_prompt["use_when"]
    assert "输出不携带动点轨迹" in square_prompt["use_when"]
    assert any(
        "原路径只有两段" in item
        for item in square_prompt["do_not_use_when"]
    )
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

    heping_problem = load_problem_ir(HEPING_FIXTURE)
    heping_catalog = FunctionalCapabilityCatalog.from_family_spec(
        build_strategy_probe_inputs(heping_problem).family_spec,
        build_strategy_probe_inputs(heping_problem).method_specs,
    )
    angle_sum = heping_catalog.get("angle_sum_equal_angle_candidates")
    assert angle_sum is not None
    assert [item.name for item in angle_sum.args] == ["condition"]
    assert {item.name for item in angle_sum.auto_args} == {
        "x_axis_point",
        "y_axis_point",
        "reference_x_axis_point",
        "origin",
        "target",
    }
    assert "只需提供结构化角和条件" in angle_sum.use_when
    angle_intercept = heping_catalog.get(
        "axis_intercept_from_equal_acute_angles"
    )
    assert angle_intercept is not None
    assert [item.name for item in angle_intercept.args] == [
        "angle_equality"
    ]
    assert {item.name for item in angle_intercept.auto_args} == {
        "x_axis_point",
        "y_axis_point",
        "reference_x_axis_point",
        "origin",
        "target",
    }
    assert "只需提供等角事实" in angle_intercept.use_when
    ray_reduction = heping_catalog.get("equal_length_ray_path_reduction")
    assert ray_reduction is not None
    ray_prompt = ray_reduction.to_prompt_payload()
    assert "一个动点在线段上、另一个动点在射线上" in (
        ray_prompt["use_when"]
    )
    assert "返回 MinimumExpression" in ray_prompt["use_when"]
    assert "PathTransformation" in ray_prompt["use_when"]
    assert any(
        "三段正方形路径或带权距离" in item
        for item in ray_prompt["do_not_use_when"]
    )

    hexi_problem = load_problem_ir(HEXI_FIXTURE)
    hexi_inputs = build_strategy_probe_inputs(hexi_problem)
    hexi_catalog = FunctionalCapabilityCatalog.from_family_spec(
        hexi_inputs.family_spec,
        hexi_inputs.method_specs,
    )
    weighted_reduction = hexi_catalog.get("weighted_axis_path_triangle_transform")
    assert weighted_reduction is not None
    weighted_prompt = weighted_reduction.to_prompt_payload()
    assert "距离和中有一项带大于 1 的权重" in (
        weighted_prompt["use_when"]
    )
    assert "输出辅助点、等价的 PathTransformation 和辅助点轨迹" in (
        weighted_prompt["use_when"]
    )
    assert any(
        "原距离和没有权重" in item
        for item in weighted_prompt["do_not_use_when"]
    )
    weighted_args = {
        item["name"]: item for item in weighted_prompt["args"]
    }
    assert "不表示本能力会求最小值" in weighted_prompt["use_when"]
    assert "数值最小值不由本能力计算" in (
        weighted_args["minimum_value"]["desc"]
    )
    assert "不带权线段的固定端点" in weighted_args["fixed_point"]["desc"]
    assert "共享的 x 轴动点" in weighted_args["moving_point"]["desc"]
    weighted_returns = {
        item["name"]: item for item in weighted_prompt["returns"]
    }
    assert "不是最小值表达式" in (
        weighted_returns["path_transformation"]["desc"]
    )
    assert "不是原动点、极值点或 Point 答案" in (
        weighted_returns["auxiliary_point"]["desc"]
    )
    assert any(
        "直接得到最小值表达式" in item
        for item in weighted_prompt["do_not_use_when"]
    )
    candidate_solve = hexi_catalog.get("curve_candidate_parameter_solve")
    assert candidate_solve is not None
    candidate_prompt = candidate_solve.to_prompt_payload()
    candidate_args = {
        item["name"]: item for item in candidate_prompt["args"]
    }
    assert "前序几何构造调用实际产出的候选点列表" in (
        candidate_args["candidates"]["desc"]
    )
    assert "不是 candidates 的替代输入" in (
        candidate_args["target_point"]["desc"]
    )
    assert any(
        "结构化声明横坐标" in item
        for item in candidate_prompt["do_not_use_when"]
    )
    assert any(
        "materialized PointList" in item
        for item in candidate_prompt["do_not_use_when"]
    )
    assert any(
        "不要假定默认旋转方向" in item
        for item in candidate_prompt["do_not_use_when"]
    )
    assert "条件性必需输入" in candidate_args["symbol_constraint"]["desc"]
    right_angle_select = hexi_catalog.get(
        "right_angle_equal_length_construct_and_select"
    )
    assert right_angle_select is not None
    right_angle_prompt = right_angle_select.to_prompt_payload()
    assert "直接唯一选择旋转分支" in right_angle_prompt["use_when"]
    assert any(
        "曲线归属和参数正负条件" in item
        for item in right_angle_prompt["do_not_use_when"]
    )


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


def test_context_semantic_index_does_not_invent_condition_for_value_fact() -> None:
    _problem, _inputs, _payload, registry, context, _plan = _xiqing_case()
    index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )

    point, _ = index.resolve(
        SemanticRef("M_coordinate_expr", "fact"),
        scope_id="ii_2",
        accepted_types=("Point",),
    )
    condition, _ = index.resolve(
        SemanticRef("M_coordinate_expr", "fact"),
        scope_id="ii_2",
        accepted_types=("Condition",),
    )
    range_condition, _ = index.resolve(
        SemanticRef("m_gt_0", "fact"),
        scope_id="ii_2",
        accepted_types=("Constraint",),
        accepted_condition_kinds=("symbol_constraint",),
    )

    assert point is not None and point.object_ref == "point:ii_2:M"
    assert condition is None
    assert range_condition is not None
    assert range_condition.runtime_type == "Condition"


def test_weighted_minimum_catalog_requires_symbol_range_constraint() -> None:
    _problem, inputs, _payload, _registry, _context, _plan = _xiqing_case()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.get("linked_broken_path_minimum_expression")
    assert capability is not None
    assert "parameter" not in {item.name for item in capability.args}
    assert "dynamic_parameter" not in {
        item.name for item in capability.args
    }
    assert {
        item.name: item.binding_authority
        for item in capability.auto_args
        if item.name in {"parameter", "dynamic_parameter"}
    } == {
        "parameter": "compiler",
        "dynamic_parameter": "compiler",
    }
    dynamic_constraint = next(
        item for item in capability.args
        if item.name == "dynamic_constraint"
    )

    assert dynamic_constraint.accepted_condition_kinds == (
        "symbol_constraint",
    )
    assert "不是点坐标" in dynamic_constraint.description
    segment_solver = catalog.get("parameter_from_segment_length")
    assert segment_solver is not None
    parameter = next(
        item for item in segment_solver.args if item.name == "parameter"
    )
    assert parameter.llm_mode == "optional"
    assert parameter.deterministic_resolver == "unique_parameter_symbol"


def test_weighted_minimum_internal_outputs_are_not_allocated() -> None:
    _problem, inputs, _problem_payload, registry, context, payload = (
        _xiqing_case()
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
    linked = next(
        item
        for item in result.calls
        if item.capability_id == "linked_broken_path_minimum_expression"
    )
    assert tuple(item.return_name for item in linked.returns) == (
        "minimum_expression",
    )


def test_compiler_owned_primary_parameter_rejects_wire_sidecar_override() -> None:
    """An explicit dynamic symbol must not replace the family primary symbol."""

    hexi_problem = load_problem_ir(HEXI_FIXTURE)
    hexi_inputs = build_strategy_probe_inputs(hexi_problem)
    compiler = object.__new__(_RecipePlanCompiler)
    compiler.function_specs = FunctionSpecRegistry.from_family_spec(
        hexi_inputs.family_spec,
        hexi_inputs.method_specs,
    )
    compiler.binding_rules = MethodBindingRuleRegistry.from_family_spec(
        hexi_inputs.family_spec
    )
    compiler.projected_function_arg_bindings = (
        ProjectedFunctionArgBinding(
            step_id="synthetic_weighted_minimum",
            arg_name="parameter",
            source_handle="symbol:problem:v",
            runtime_type="Symbol",
            object_ref="symbol:problem:v",
            binding_authority="wire",
        ),
    )
    step = StepIntent(
        scope_id="iii",
        step_id="synthetic_weighted_minimum",
        recipe_hint="linked_broken_path_minimum_expression",
        goal_type="derive_minimum_expression",
        target="fact:iii:minimum_expression",
        reads=("symbol:problem:u", "symbol:problem:v"),
        strategy="derive the weighted minimum expression",
    )
    spec = hexi_inputs.method_specs.require(
        "linked_broken_path_minimum_expression"
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="declared_authority=compiler",
    ):
        compiler._projected_exact_function_inputs(step, spec)


def test_quadratic_constraint_adapter_accepts_three_curve_points() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8")
    )
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_parabola_i"
    )
    call["args"]["curve_points"].append(
        {"kind": "point", "ref": "A"}
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
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is not None, replay.errors
    invocation = next(
        invocation
        for step in replay.output.step_plans
        if step.step_id == "derive_parabola_i"
        for invocation in step.invocations
        if invocation.method_id == "quadratic_from_constraints"
    )
    assert "p3" not in invocation.inputs
    assert len(invocation.inputs["curve_points"]) == 3


def test_quadratic_constraint_analyzer_materializes_each_aggregate_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shuxueshuo_server.solver.runtime.methods import (
        quadratic_from_constraints as quadratic_method_module,
    )

    captured: dict[str, Any] = {}

    def analyze(
        runtime_inputs: dict[str, Any],
        **_kwargs: Any,
    ) -> Any:
        captured.update(runtime_inputs)
        return SimpleNamespace(status="determined")

    monkeypatch.setattr(
        quadratic_method_module,
        "analyze_quadratic_constraints",
        analyze,
    )

    class _Context:
        def read_path(
            self,
            path: str,
            *,
            from_scope_id: str,
            expected_type: str | None = None,
        ) -> TypedValue:
            assert from_scope_id == "branch"
            if path == "$problem.symbol_lists.quadratic_coefficients":
                return TypedValue("SymbolList", ())
            if expected_type == "Point":
                coordinate = (sp.Integer(1), sp.Integer(2))
                return TypedValue("Point", coordinate)
            return TypedValue(
                "PointRef",
                PointRef(path, path, scope_id="branch"),
            )

    result = _analyze_quadratic_coefficient_inputs(
        {"curve_points": ("$point.one", "$point.two")},
        StepIntent(
            step_id="build_curve",
            scope_id="branch",
            recipe_hint="quadratic_from_constraints",
            goal_type="derive_curve",
            target="",
            strategy="materialize aggregate points",
        ),
        SimpleNamespace(
            context=_Context(),
            bindings={},
        ),
    )

    assert result.inputs == {
        "curve_points": ("$point.one", "$point.two")
    }
    assert captured["curve_points"] == [
        (sp.Integer(1), sp.Integer(2)),
        (sp.Integer(1), sp.Integer(2)),
    ]


def test_mechanical_auto_arg_with_state_version_projects_exact_dependency() -> None:
    object_id = MathObjectId("point:problem:target", "point", "problem")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "branch")
    version_id = StateVersionId(slot_id, 1)
    call = FunctionalCall(
        call_id="consume_target",
        capability_id="synthetic_consumer",
        args={},
        return_bindings={},
        strategy="consume a mechanical target role",
        reason="verify exact dependency projection",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope(
                scope_id="branch",
                label="branch",
                calls=(call,),
            ),
        )
    )
    reconciliation = SimpleNamespace(
        call_id=call.call_id,
        capability_id=call.capability_id,
        resolved_args={
            "target": (
                ResolvedFunctionalValue(
                    handle="fact:branch:target_coordinate",
                    runtime_type="Point",
                    valid_scope="branch",
                    state_slot_id="point:problem:target.coordinate@branch",
                    object_ref=object_id.value,
                    source_call_id="produce_target",
                    return_name="point",
                    math_object_id=object_id,
                    logical_state_key=logical_key,
                    typed_slot_id=slot_id,
                    state_version_id=version_id,
                ),
            )
        },
        returns=(),
    )
    capability = SimpleNamespace(
        args=(),
        auto_args=(
            SimpleNamespace(
                name="target",
                binding_authority="compiler",
                selector="point_output_ref",
            ),
        ),
    )

    dependencies = project_functional_state_dependencies(
        plan,
        (reconciliation,),
        catalog=SimpleNamespace(
            get=lambda capability_id: (
                capability
                if capability_id == "synthetic_consumer"
                else None
            )
        ),
    )

    assert len(dependencies) == 1
    assert dependencies[0].arg_name == "target"
    assert dependencies[0].state_version_id == version_id
    assert dependencies[0].source_step_id == "produce_target"


def test_path_transformation_consumer_uses_exact_projected_producer() -> None:
    compiler = object.__new__(_RecipePlanCompiler)
    object_id = MathObjectId(
        "path_transformation:branch:selected",
        "path_transformation",
        "branch",
    )
    logical_key = LogicalStateKey(
        object_id,
        "transformation",
        "PathTransformation",
    )
    version_id = StateVersionId(
        StateSlotId(logical_key, "branch"),
        1,
    )
    compiler.projected_state_dependencies = (
        ProjectedStateDependency(
            step_id="consume_transform",
            state_slot_id="functional:branch:selected_transform",
            produced_handle="fact:branch:selected_transform",
            runtime_type="PathTransformation",
            arg_name="path_transformation",
            source="wire",
            source_step_id="produce_selected_transform",
            source_return_name="path_transformation",
            state_version_id=version_id,
        ),
    )
    compiler.index = SimpleNamespace(
        runtime_path_for_state_version=lambda selected, **_kwargs: (
            f"$version[{selected.ordinal}]"
        ),
        bindings={},
    )
    step = StepIntent(
        step_id="consume_transform",
        scope_id="branch",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum_expression",
        target="",
        strategy="consume the selected transformation",
    )

    handle, path = compiler._path_transformation_input(step)

    assert handle == "fact:branch:selected_transform"
    assert path == "$version[1]"


def test_functional_path_transformation_missing_dependency_fails_closed() -> None:
    compiler = object.__new__(_RecipePlanCompiler)
    compiler.projected_state_dependencies = ()
    fallback_reasons: list[str] = []

    def reject_fallback(**kwargs: str) -> None:
        fallback_reasons.append(kwargs["reason"])
        raise StrategyDraftValidationError(
            "planner.runtime_state_binding_drift"
        )

    compiler.index = SimpleNamespace(
        functional_consumer_identity_mode="authoritative",
        record_legacy_runtime_identity_fallback=reject_fallback,
        bindings={},
    )
    step = StepIntent(
        step_id="consume_transform",
        scope_id="branch",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum_expression",
        target="",
        strategy="consume a typed transformation",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        compiler._path_transformation_input(step)

    assert fallback_reasons == [
        "path_transformation_dependency_missing"
    ]


def test_path_transformation_consumer_accepts_exact_wire_sidecar() -> None:
    compiler = object.__new__(_RecipePlanCompiler)
    object_id = MathObjectId(
        "path_transformation:branch:selected",
        "path_transformation",
        "branch",
    )
    logical_key = LogicalStateKey(
        object_id,
        "transformation",
        "PathTransformation",
    )
    version_id = StateVersionId(
        StateSlotId(logical_key, "branch"),
        1,
    )
    compiler.projected_state_dependencies = ()
    compiler.projected_function_arg_bindings = (
        ProjectedFunctionArgBinding(
            step_id="consume_transform",
            arg_name="path_transformation",
            source_handle="fact:branch:selected_transform",
            runtime_type="PathTransformation",
            math_object_id=object_id,
            state_version_id=version_id,
            source_call_id="produce_selected_transform",
            source_return_name="path_transformation",
        ),
    )
    compiler.index = SimpleNamespace(
        functional_consumer_identity_mode="authoritative",
        runtime_path_for_state_version=lambda selected, **_kwargs: (
            "$version[1]"
            if selected == version_id
            else pytest.fail("wrong transformation version")
        ),
        record_legacy_runtime_identity_fallback=lambda **_kwargs: pytest.fail(
            "exact wire sidecar must not fall back"
        ),
    )
    step = StepIntent(
        step_id="consume_transform",
        scope_id="branch",
        recipe_hint="broken_path_straightening_minimum_expression",
        goal_type="derive_minimum_expression",
        target="",
        strategy="consume the selected transformation",
    )

    handle, path = compiler._path_transformation_input(step)

    assert handle == "fact:branch:selected_transform"
    assert path == "$version[1]"


def test_typed_merge_rejects_distinct_exact_arg_producers() -> None:
    left = {
        "point": (
            ResolvedFunctionalValue(
                handle="fact:branch:left",
                runtime_type="Point",
                valid_scope="branch",
                source_call_id="produce_left",
            ),
        )
    }
    right = {
        "point": (
            ResolvedFunctionalValue(
                handle="fact:branch:right",
                runtime_type="Point",
                valid_scope="branch",
                source_call_id="produce_right",
            ),
        )
    }

    assert not (
        functional_call_placement_module
        ._resolved_arg_producers_compatible(
            left,
            right,
            aliases={},
        )
    )


def test_hidden_mechanical_selector_alias_is_pruned_before_auto_resolution() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_parabola_i"
    )
    call["args"]["parabola"] = {"kind": "function", "ref": "parabola"}
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

    assert replay.output is not None, replay.errors
    assert replay.functional_reconciliation is not None
    effective_call = next(
        item
        for item in replay.functional_reconciliation.effective_plan.calls
        if item.call_id == "derive_parabola_i"
    )
    assert "parabola" not in effective_call.args
    assert "quadratic" not in effective_call.args
    repairs = replay.functional_reconciliation.elaboration[
        "deterministic_repairs"
    ]
    assert any(
        item["action"] == "drop_unknown_capability_arg"
        and item["from"] == "parabola=provided"
        and item["to"] == "parabola=omitted"
        for item in repairs
    )


def test_recomputed_translated_ray_endpoint_keeps_original_point_definition() -> None:
    """A scoped coordinate version must still target the canonical PointRef."""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii")
    reduction_index = next(
        index
        for index, call in enumerate(scope["calls"])
        if call["call_id"] == "reduce_equal_length_ray_path_ii"
    )
    scope["calls"][reduction_index:reduction_index] = [
        {
            "call_id": "recompute_C_ii",
            "capability_id": "quadratic_y_axis_intercept_point",
            "args": {
                "quadratic": {
                    "from_call": "derive_parametric_parabola_ii",
                    "return": "parabola",
                }
            },
            "return_bindings": {
                "point": {"ref": "C", "kind": "point"},
            },
            "strategy": "recompute a shared intercept state",
            "reason": "exercise a newer scoped state version",
        },
        {
            "call_id": "recompute_D_ii",
            "capability_id": "translated_point",
            "args": {
                "source": {
                    "from_call": "recompute_C_ii",
                    "return": "point",
                }
            },
            "return_bindings": {
                "point": {"ref": "D", "kind": "point"},
            },
            "strategy": "recompute the translated ray endpoint",
            "reason": "the target keeps its original translation definition",
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
        replay.diagnostic.blockers if replay.diagnostic is not None else None,
        replay.retry_state.issues if replay.retry_state is not None else None,
    )
    assert replay.diagnostic is not None and replay.diagnostic.ok


def test_angle_role_args_are_pruned_and_rebound_from_structured_facts() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    angle_call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_equal_angle_i"
    )
    angle_call["args"].update(
        {
            "x_axis_point": {"kind": "point", "ref": "A"},
            "y_axis_point": {"kind": "point", "ref": "B"},
            "reference_x_axis_point": {"kind": "point", "ref": "C"},
            "origin": {"kind": "point", "ref": "B"},
        }
    )
    intercept_call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_axis_intercept_F_i"
    )
    intercept_call["args"].update(
        {
            "x_axis_point": {"kind": "point", "ref": "A"},
            "y_axis_point": {"kind": "point", "ref": "B"},
            "reference_x_axis_point": {"kind": "point", "ref": "C"},
            "origin": {"kind": "point", "ref": "B"},
        }
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
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_payload,
        validation_report=validation,
    )

    assert replay.output is not None, replay.errors
    assert replay.functional_reconciliation is not None
    repairs = replay.functional_reconciliation.elaboration[
        "deterministic_repairs"
    ]
    dropped = {
        (item["call_id"], item["from"])
        for item in repairs
        if item["action"] == "drop_unknown_capability_arg"
    }
    for call_id in ("derive_equal_angle_i", "derive_axis_intercept_F_i"):
        assert {
            (call_id, f"{name}=provided")
            for name in (
                "x_axis_point",
                "y_axis_point",
                "reference_x_axis_point",
                "origin",
            )
        } <= dropped


def test_x_axis_intercept_infers_known_point_from_target_definition() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_x_intercept_B_i"
    )
    call["args"].pop("known_point")
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

    assert replay.output is not None, replay.errors
    invocation = next(
        invocation
        for step in replay.output.step_plans
        if step.step_id == "derive_x_intercept_B_i"
        for invocation in step.invocations
        if invocation.method_id == "quadratic_x_axis_intercept_point"
    )
    assert invocation.inputs["known_point"] == "$problem.points.A"


def test_answer_bound_object_return_keeps_canonical_state_alias() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
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

    assert replay.output is not None, replay.errors
    assert replay.functional_reconciliation is not None
    allocation = next(
        output
        for call in replay.functional_reconciliation.calls
        if call.call_id == "derive_parabola_i"
        for output in call.returns
        if output.return_name == "parabola"
    )
    assert allocation.handle == "answer:i_1_parabola"
    assert allocation.state_handle is not None
    assert allocation.state_handle.startswith("fact:")
    assert replay.effective_draft is not None
    producer = next(
        step
        for step in replay.effective_draft.steps
        if step.step_id == "derive_parabola_i"
    )
    consumer = next(
        step
        for step in replay.effective_draft.steps
        if step.step_id == "derive_x_intercept_B_i"
    )
    assert {item.handle for item in producer.produces} >= {
        allocation.handle,
        allocation.state_handle,
    }
    assert allocation.state_handle in consumer.reads
    assert allocation.handle not in consumer.reads


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


def test_reconciler_reprojects_sibling_point_semantic_read_to_exact_version() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
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
                "label": "producer branch",
                "calls": [
                    {
                        "call_id": "build_curve",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": [
                                {"ref": "A", "kind": "point"},
                            ],
                            "free_parameters": [
                                {"ref": "a", "kind": "symbol"},
                            ],
                        },
                        "return_bindings": {},
                        "strategy": "materialize a curve",
                        "reason": "provide the intercept input",
                    },
                    {
                        "call_id": "produce_B",
                        "capability_id": "quadratic_x_axis_intercept_point",
                        "args": {
                            "quadratic": {
                                "from_call": "build_curve",
                                "return": "parabola",
                            },
                            "known_point": {
                                "ref": "A",
                                "kind": "point",
                            },
                        },
                        "return_bindings": {
                            "point": {"ref": "B", "kind": "point"},
                        },
                        "strategy": "materialize the shared point",
                        "reason": "the sibling reads this MathObject",
                    },
                ],
            },
            {
                "scope_id": "i_2",
                "label": "consumer branch",
                "calls": [
                    {
                        "call_id": "consume_B",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {"ref": "B", "kind": "point"},
                            "p2": {"ref": "A", "kind": "point"},
                        },
                        "return_bindings": {},
                        "strategy": "consume the shared point state",
                        "reason": "exercise final semantic arg reprojection",
                    },
                ],
            },
        ],
    }
    payload["scopes"] = list(reversed(payload["scopes"]))
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
    calls = {item.call_id: item for item in result.calls}
    produced = calls["produce_B"].returns[0]
    consumed = calls["consume_B"].resolved_args["p1"][0]
    assert produced.valid_scope == "i"
    assert consumed.source_call_id == "produce_B"
    assert consumed.state_version_id == produced.selected_version_id
    assert result.dependency_graph["consume_B"] == ("produce_B",)


def test_semantic_object_reads_prefer_branch_local_planned_producer() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
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
                "label": "first branch",
                "calls": [
                    {
                        "call_id": "first_intercept",
                        "capability_id": "quadratic_y_axis_intercept_point",
                        "args": {
                            "quadratic": {
                                "ref": "parabola",
                                "kind": "function",
                            }
                        },
                        "return_bindings": {
                            "point": {"ref": "C", "kind": "point"}
                        },
                        "strategy": "derive a branch-local intercept",
                        "reason": "provide the local source point",
                    },
                    {
                        "call_id": "first_translation",
                        "capability_id": "translated_point",
                        "args": {
                            "source": {"ref": "C", "kind": "point"}
                        },
                        "return_bindings": {
                            "point": {"ref": "D", "kind": "point"}
                        },
                        "strategy": "translate the local source point",
                        "reason": "exercise semantic state selection",
                    },
                ],
            },
            {
                "scope_id": "ii",
                "label": "second branch",
                "calls": [
                    {
                        "call_id": "build_branch_curve",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_point": {
                                "ref": "A",
                                "kind": "point",
                            },
                            "free_parameters": {
                                "ref": "a",
                                "kind": "symbol",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "materialize a branch-local curve",
                        "reason": "use a distinct input state",
                    },
                    {
                        "call_id": "second_intercept",
                        "capability_id": "quadratic_y_axis_intercept_point",
                        "args": {
                            "quadratic": {
                                "from_call": "build_branch_curve",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {
                            "point": {"ref": "C", "kind": "point"}
                        },
                        "strategy": "derive the same object in this branch",
                        "reason": "keep the sibling state isolated",
                    },
                    {
                        "call_id": "second_translation",
                        "capability_id": "translated_point",
                        "args": {
                            "source": {"ref": "C", "kind": "point"}
                        },
                        "return_bindings": {
                            "point": {"ref": "D", "kind": "point"}
                        },
                        "strategy": "translate the second local source",
                        "reason": "read the latest state in this branch",
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

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.state_finalization_mismatches == ()
    calls = {item.call_id: item for item in result.calls}
    assert calls["first_translation"].resolved_args["source"][
        0
    ].source_call_id == "first_intercept"
    assert calls["second_translation"].resolved_args["source"][
        0
    ].source_call_id == "second_intercept"
    assert calls["first_intercept"].returns[0].valid_scope != "problem"
    assert calls["second_intercept"].returns[0].valid_scope == "ii"


def test_typed_placement_keeps_sibling_parabola_version_isolated() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
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
                "label": "closed branch",
                "calls": [
                    {
                        "call_id": "translate_d",
                        "capability_id": "translated_point",
                        "args": {
                            "source": {"ref": "C", "kind": "point"},
                        },
                        "return_bindings": {
                            "point": {"ref": "D", "kind": "point"},
                        },
                        "strategy": "materialize the translated point",
                        "reason": "provide the second curve constraint",
                    },
                    {
                        "call_id": "closed_curve",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": [
                                {"ref": "A", "kind": "point"},
                                {"from_call": "translate_d", "return": "point"},
                            ],
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            },
                        },
                        "return_expectations": {
                            "parabola": "closed_state",
                        },
                        "strategy": "determine the closed sibling state",
                        "reason": "exercise the first function version",
                    },
                ],
            },
            {
                "scope_id": "ii",
                "label": "open branch",
                "calls": [
                    {
                        "call_id": "open_curve",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_points": [
                                {"ref": "A", "kind": "point"},
                            ],
                            "free_parameters": [
                                {"ref": "a", "kind": "symbol"},
                            ],
                        },
                        "return_bindings": {
                            "parabola": {
                                "ref": "parabola",
                                "kind": "function",
                            },
                        },
                        "return_expectations": {
                            "parabola": "open_state",
                        },
                        "strategy": "derive an independent open sibling state",
                        "reason": "the closed branch constraint is not visible here",
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

    assert result.ok, [item.to_payload() for item in result.issues]
    open_call = next(item for item in result.calls if item.call_id == "open_curve")
    open_return = next(
        item for item in open_call.returns if item.return_name == "parabola"
    )
    placement = next(
        item
        for item in result.call_placements
        if item.canonical_call_id == "open_curve"
    )
    assert open_return.allocation_action == "isolated"
    assert open_return.typed_slot_id is not None
    assert open_return.typed_slot_id.storage_scope_id == "ii"
    assert open_return.valid_scope == "ii"
    assert placement.execution_scope_id == "ii"
    assert placement.return_scopes["parabola"] == "ii"


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
        "straightened_endpoint_1",
    )
    assert args["minimum_point_2"].accepted_semantic_roles == (
        "straightened_endpoint_2",
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
                        "return": f"straightened_endpoint_{number}",
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
        assert (
            f"straightened_endpoint_{number}"
            in allocation.lineage.semantic_roles
        )
        assert allocation.lineage.object_roles
        assert "derive_path_minimum_ii" in allocation.lineage.source_call_ids

    evaluated = tuple(
        ResolvedFunctionalValue(
            handle=allocation.handle,
            runtime_type="Point",
            valid_scope=allocation.valid_scope,
            source_call_id=f"evaluate_path_endpoint_{number}_ii",
            lineage=allocation.lineage,
        )
        for number, allocation in (
            (number, allocations[
                (f"evaluate_path_endpoint_{number}_ii", "evaluated_point")
            ])
            for number in (1, 2)
        )
    )
    assert _values_share_lineage_source_call(evaluated)


def test_role_mismatch_feedback_lists_unallocated_declared_returns() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(
        HEPING_ERMO_FUNCTIONAL_PLAN.read_text(encoding="utf-8")
    )
    minimum_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_minimum_point_G_ii"
    )
    minimum_call["args"]["minimum_point_1"] = {
        "from_call": "evaluate_point_A_ii",
        "return": "evaluated_point",
    }
    minimum_call["args"]["minimum_point_2"] = {
        "from_call": "derive_axis_point_M_ii",
        "return": "axis_point",
    }

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

    assert replay.retry_state is not None
    issues = [
        issue
        for issue in replay.retry_state.issues
        if issue.code == "functional.state_role_mismatch"
    ]
    assert {issue.details["arg"] for issue in issues if issue.details} == {
        "minimum_point_1",
        "minimum_point_2",
    }
    candidates_by_arg = {
        issue.details["arg"]: {
            (item["from_call"], item["return"])
            for item in issue.details["compatible_call_results"]
        }
        for issue in issues
        if issue.details is not None
    }
    assert (
        "derive_path_minimum_ii",
        "straightened_endpoint_1",
    ) in candidates_by_arg["minimum_point_1"]
    assert (
        "derive_path_minimum_ii",
        "straightened_endpoint_2",
    ) in candidates_by_arg["minimum_point_2"]


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
    assert result.ok
    call = next(
        item
        for item in result.calls
        if item.call_id == "derive_path_minimum_ii"
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.get(call.capability_id)
    assert capability is not None
    wrong_locus = replace(
        call.resolved_args["moving_locus"][0],
        source_call_id="derive_locus_G_ii",
        lineage=state_semantic_lineage(
            object_roles=(
                StateObjectRoleBinding(
                    role="subject",
                    object_refs=("point:ii:E",),
                    object_ids=(
                        MathObjectId("point:ii:E", "point", "ii"),
                    ),
                ),
            ),
        ),
    )
    resolved_args = {
        **call.resolved_args,
        "moving_locus": (wrong_locus,),
    }
    issues = StateIdentityConstraintValidator().validate(
        capability.identity_constraints,
        call_id=call.call_id,
        scope_id=call.scope_id,
        resolved_args=resolved_args,
        returns=call.returns,
    )
    issue = next(
        item for item in issues
        if item.code == "functional.object_identity_mismatch"
    )
    assert issue.details["actual_object_refs"] == ["point:ii:E"]
    assert issue.details["expected_object_refs"] == ["point:ii:G"]
    assert "derive_locus_G_ii" in issue.details["repair_call_ids"]
    assert "derive_path_minimum_ii" in issue.details["repair_call_ids"]
    repair_roots = strategy_replay_module._root_repair_call_ids(
        replace(result, issues=issues)
    )
    assert "derive_locus_G_ii" in repair_roots
    assert "derive_path_minimum_ii" in repair_roots
    assert "derive_minimum_point_G_ii" not in repair_roots


def test_identity_constraint_compares_unordered_math_object_sets() -> None:
    first = MathObjectId("point:part:first", "point", "part")
    second = MathObjectId("point:part:second", "point", "part")
    unrelated = MathObjectId("point:part:unrelated", "point", "part")
    condition = ResolvedFunctionalValue(
        handle="fact:part:segment_length",
        runtime_type="Condition",
        valid_scope="part",
        condition_id="condition:segment_length@part",
        lineage=state_semantic_lineage(
            object_roles=(
                StateObjectRoleBinding(
                    role="endpoint",
                    object_refs=(first.value, second.value),
                    object_ids=(first, second),
                ),
            ),
        ),
    )
    constraints = (
        StateIdentityConstraintSpec(
            left="args:p1,p2.object_ref",
            right="arg:condition.object_role:endpoint",
            relation="same_object_set",
        ),
    )
    valid_args = {
        "p1": (
            ResolvedFunctionalValue(
                handle=second.value,
                runtime_type="Point",
                valid_scope="part",
                object_ref=second.value,
                math_object_id=second,
            ),
        ),
        "p2": (
            ResolvedFunctionalValue(
                handle=first.value,
                runtime_type="Point",
                valid_scope="part",
                object_ref=first.value,
                math_object_id=first,
            ),
        ),
        "condition": (condition,),
    }

    validator = StateIdentityConstraintValidator()
    assert not validator.validate(
        constraints,
        call_id="solve_parameter",
        scope_id="part",
        resolved_args=valid_args,
        returns=(),
    )

    issues = validator.validate(
        constraints,
        call_id="solve_parameter",
        scope_id="part",
        resolved_args={
            **valid_args,
            "p1": (
                replace(
                    valid_args["p1"][0],
                    handle=unrelated.value,
                    object_ref=unrelated.value,
                    math_object_id=unrelated,
                ),
            ),
        },
        returns=(),
    )
    assert [item.code for item in issues] == [
        "functional.object_identity_mismatch"
    ]
    assert issues[0].details["relation"] == "same_object_set"


def test_segment_length_condition_rejects_points_from_another_segment() -> None:
    inputs = _base_inputs()
    payload = json.loads(
        NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8")
    )
    solve_parameter = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_1_solve_m"
    )
    solve_parameter["args"]["p1"] = {
        "from_call": "i_derive_D",
        "return": "axis_point",
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
        if item.call_id == "ii_1_solve_m"
        and item.code == "functional.object_identity_mismatch"
    )
    assert issue.details["relation"] == "same_object_set"
    assert set(issue.details["actual_object_refs"]) != set(
        issue.details["expected_object_refs"]
    )


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
def test_reconciler_drops_external_binding_from_internal_derived_role(
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
                            "straightened_endpoint_2": {
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

    effective = next(
        item
        for item in result.plan.calls
        if item.call_id == "derive_path_endpoint"
    )
    assert effective.return_bindings == {}
    assert any(
        item["action"] == "drop_internal_only_return_binding"
        and item["call_id"] == "derive_path_endpoint"
        for item in result.elaboration["deterministic_repairs"]
    )


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
    ) == 2


def test_reconciler_does_not_treat_object_ref_as_materialized_target_state() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "i_2")
    calls = scope["calls"]
    square_call_index = next(
        index
        for index, call in enumerate(calls)
        if call["call_id"] == "derive_square_vertex_G_i"
    )
    square_call = calls[square_call_index]
    derive_other_vertex = json.loads(json.dumps(square_call))
    derive_other_vertex["call_id"] = "derive_other_square_vertex_i"
    derive_other_vertex["return_bindings"] = {
        "point": {"ref": "i_2.K", "kind": "point"}
    }
    derive_other_vertex["strategy"] = "先求同一结构中另一个已知角色的坐标。"
    derive_other_vertex["reason"] = "使剩余目标对象可由结构化角色唯一确定。"
    calls.insert(square_call_index, derive_other_vertex)

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

    assert result.ok
    resolved = next(
        item
        for item in result.calls
        if item.call_id == "derive_square_vertex_G_i"
    )
    assert tuple(item.object_ref for item in resolved.returns) == (
        "point:i_2:G",
    )


def test_explicit_return_identity_is_not_replaced_by_structured_role() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_square_vertex_G_i"
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

    issue = next(
        item
        for item in result.issues
        if item.call_id == "derive_square_vertex_G_i"
        and item.code == "functional.return_identity_unresolved"
    )
    assert issue.details is not None
    assert issue.details["binding_requirement"] == (
        "explicit_answer_or_existing_object"
    )


def test_reconciler_reuses_open_state_for_incomplete_parameter_transition() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    scope = next(item for item in payload["scopes"] if item["scope_id"] == "ii")
    square_index = next(
        index
        for index, call in enumerate(scope["calls"])
        if call["call_id"] == "derive_square_vertex_G_ii"
    )
    scope["calls"].insert(
        square_index,
        {
            "call_id": "redundant_materialize_A",
            "capability_id": "evaluate_point_at_parameter",
            "args": {
                "point": {
                    "ref": "ii.A",
                    "kind": "point",
                }
            },
            "return_bindings": {
                "evaluated_point": {
                    "ref": "ii.A",
                    "kind": "point",
                }
            },
            "return_expectations": {
                "evaluated_point": "open_state",
            },
            "strategy": "repeat the existing open point state",
            "reason": "exercise incomplete transition normalization",
        },
    )
    square_call = next(
        call
        for call in scope["calls"]
        if call["call_id"] == "derive_square_vertex_G_ii"
    )
    square_call["args"]["side_start"] = {
        "from_call": "redundant_materialize_A",
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

    assert result.ok, [item.to_payload() for item in result.issues]
    assert "redundant_materialize_A" not in {
        call.call_id for call in result.plan.calls
    }
    canonical_square = next(
        call
        for call in result.plan.calls
        if call.call_id == "derive_square_vertex_G_ii"
    )
    assert canonical_square.args["side_start"] == (
        SemanticRef(ref="ii.A", kind="point"),
    )
    assert any(
        item["action"] == "reuse_open_state_for_incomplete_transition"
        and item["call_id"] == "redundant_materialize_A"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_keeps_incomplete_transition_when_closed_state_is_required() -> None:
    inputs, _payload, registry, context = _heping_ermo_case()
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "close_A_without_parameter",
                        "capability_id": "evaluate_point_at_parameter",
                        "args": {
                            "point": {
                                "ref": "ii.A",
                                "kind": "point",
                            }
                        },
                        "return_bindings": {},
                        "return_expectations": {
                            "evaluated_point": "closed_state",
                        },
                        "strategy": "request a closed point state",
                        "reason": "exercise the no-op repair boundary",
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

    assert any(
        item.call_id == "close_A_without_parameter"
        and item.code == "functional.arg_missing"
        for item in result.issues
    )
    assert all(
        item["action"] != "reuse_open_state_for_incomplete_transition"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_explicit_return_identity_is_not_inferred_from_downstream_usage() -> None:
    inputs, payload, registry, context = _heping_ermo_case()
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "derive_square_vertex_G_ii"
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

    issue = next(
        item
        for item in result.issues
        if item.call_id == "derive_square_vertex_G_ii"
        and item.code == "functional.return_identity_unresolved"
    )
    assert issue.details is not None
    assert issue.details["binding_requirement"] == (
        "explicit_answer_or_existing_object"
    )


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
    allocation = next(
        returned
        for resolved in result.calls
        if resolved.call_id == "derive_x_intercept_A_i"
        for returned in resolved.returns
        if returned.return_name == "point"
    )
    assert allocation.object_ref == "point:problem:A"
    assert allocation.valid_scope == "i"


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
        "fact:problem:i_derive_D_axis_point",
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
        "transformed_fixed_endpoint",
        "moving_locus_endpoint_1",
        "moving_locus_endpoint_2",
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
    allocation = next(
        item
        for item in reduction.returns
        if item.return_name == "path_transformation"
    )
    roles = {item.role: item for item in allocation.lineage.object_roles}
    assert roles["fixed_endpoint_1"].object_refs == ("point:problem:D",)
    assert roles["fixed_endpoint_2"].object_refs == ("point:ii:F",)
    assert roles["fixed_endpoint_2"].source_state_slot_ids == (
        "point:ii:F.coordinate@ii:Point",
    )
    assert roles["fixed_endpoint_2"].source_handles == (
        "fact:ii:F_coordinate",
    )
    assert roles["moving_locus"].object_refs == ("segment:ii:MN",)
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    dependencies = (
        strategy_replay_module._functional_projected_state_dependencies(
            result,
            catalog=catalog,
        )
    )
    f_dependency = next(
        item
        for item in dependencies
        if item.step_id == "ii_reduce_path"
        and item.arg_name == "transformed_fixed_endpoint"
    )
    assert f_dependency.produced_handle == "fact:ii:F_coordinate"
    assert f_dependency.state_slot_id == "point:ii:F.coordinate@ii:Point"
    assert f_dependency.source_step_id == "ii_compute_F"
    assert f_dependency.source_return_name == "midpoint"

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
    assert all(
        binding.state_version_id is not None
        for binding in bindings
        if binding.state_slot_id is not None
        and binding.object_ref is not None
    )
    assert all(
        binding.math_object_id is not None
        for binding in bindings
        if binding.object_ref is not None
    )
    assert reconciliation.typed_identity_completeness["complete"] is True
    assert reconciliation.legacy_identity_fallback_count == 0


def test_path_transformation_producers_publish_distinct_role_profiles() -> None:
    weighted_inputs, weighted_registry, weighted_context, weighted_payload = (
        _hexi_case()
    )
    weighted_plan, weighted_validation = (
        FunctionalPlanValidator().validate_payload_with_report(
            weighted_payload,
            handle_registry=weighted_registry,
            question_goals=weighted_inputs.question_goals,
        )
    )
    assert weighted_validation.ok and weighted_plan is not None
    weighted = FunctionalPlanReconciler().reconcile(
        weighted_plan,
        planner_state_context=weighted_context,
        family_spec=weighted_inputs.family_spec,
        method_specs=weighted_inputs.method_specs,
        handle_registry=weighted_registry,
        question_goals=weighted_inputs.question_goals,
    )
    weighted_call = next(
        item
        for item in weighted.calls
        if item.call_id == "transform_weighted_path_iii"
    )
    weighted_return = next(
        item
        for item in weighted_call.returns
        if item.runtime_type == "PathTransformation"
    )
    weighted_auxiliary = next(
        item
        for item in weighted_call.returns
        if item.return_name == "auxiliary_point"
    )
    assert {
        item.role for item in weighted_return.lineage.object_roles
    } == {
        "moving_object",
        "fixed_endpoint_1",
        "auxiliary_object",
    }
    weighted_auxiliary_role = next(
        item
        for item in weighted_return.lineage.object_roles
        if item.role == "auxiliary_object"
    )
    assert weighted_auxiliary_role.object_ids == (
        weighted_auxiliary.math_object_id,
    )
    assert weighted_auxiliary_role.source_version_ids == (
        weighted_auxiliary.selected_version_id,
    )

    square_inputs, square_payload, square_registry, square_context = (
        _heping_ermo_case()
    )
    square_plan, square_validation = (
        FunctionalPlanValidator().validate_payload_with_report(
            square_payload,
            handle_registry=square_registry,
            question_goals=square_inputs.question_goals,
        )
    )
    assert square_validation.ok and square_plan is not None
    square = FunctionalPlanReconciler().reconcile(
        square_plan,
        planner_state_context=square_context,
        family_spec=square_inputs.family_spec,
        method_specs=square_inputs.method_specs,
        handle_registry=square_registry,
        question_goals=square_inputs.question_goals,
    )
    square_call = next(
        item
        for item in square.calls
        if item.call_id == "reduce_square_path_ii"
    )
    square_return = next(
        item
        for item in square_call.returns
        if item.runtime_type == "PathTransformation"
    )
    square_roles = {
        item.role: item for item in square_return.lineage.object_roles
    }
    assert set(square_roles) == {
        "moving_object",
        "fixed_endpoint_1",
        "fixed_endpoint_2",
    }
    assert "moving_locus" not in square_roles
    assert square_roles["fixed_endpoint_1"].state_requirement == "materialized"
    assert square_roles["fixed_endpoint_2"].state_requirement == "materialized"


def test_path_transformation_source_roles_follow_final_placed_versions() -> None:
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
    assert reconciliation.ok

    reductions = tuple(
        item
        for item in reconciliation.calls
        if item.capability_id == "two_moving_points_path_reduction"
    )
    assert reductions
    for reduction in reductions:
        transformation = next(
            item
            for item in reduction.returns
            if item.runtime_type == "PathTransformation"
        )
        fixed_endpoint = next(
            item
            for item in transformation.lineage.object_roles
            if item.role == "fixed_endpoint_2"
        )
        source = reduction.resolved_args["transformed_fixed_endpoint"]
        assert fixed_endpoint.object_ids == tuple(
            item.math_object_id for item in source
        )
        assert fixed_endpoint.source_version_ids == tuple(
            item.state_version_id for item in source
        )


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
            known_state_versions=(
                strategy_replay_module._functional_known_state_versions(
                    _context(inputs),
                    handle_registry=_registry(),
                )
            ),
            functional_consumer_identity_mode="authoritative",
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


def test_typed_destination_configuration_error_skips_capability_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert reconciliation.ok
    assert reconciliation.projected_draft is not None
    finalization_calls = 0

    def reject_destination(*_args: object, **_kwargs: object) -> None:
        nonlocal finalization_calls
        finalization_calls += 1
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.contract_runtime_destination_drift: synthetic"
        )

    monkeypatch.setattr(
        CanonicalDraftFinalizer,
        "finalize_compiled_state_writes",
        reject_destination,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.contract_runtime_destination_drift",
    ):
        RecipeTrialExecutor().diagnose(
            reconciliation.projected_draft,
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
            projected_state_dependencies=(
                strategy_replay_module
                ._functional_projected_state_dependencies(
                    reconciliation,
                    catalog=FunctionalCapabilityCatalog.from_family_spec(
                        inputs.family_spec,
                        inputs.method_specs,
                    ),
                )
            ),
            known_state_versions=(
                strategy_replay_module._functional_known_state_versions(
                    _context(inputs),
                    handle_registry=_registry(),
                )
            ),
        )

    assert finalization_calls == 1


def test_replay_draft_propagates_typed_finalizer_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _base_inputs()

    def reject_logical_projection(
        *_args: object,
        **_kwargs: object,
    ) -> None:
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.state_finalization_drift: synthetic"
        )

    monkeypatch.setattr(
        CanonicalDraftFinalizer,
        "finalize",
        reject_logical_projection,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_finalization_drift",
    ):
        PlannerRetryReplayService().replay_draft(
            StepIntentDraft(scopes=()),
            inputs=inputs,
            handle_registry=_registry(),
            context=ContextBuilder().build(_problem()),
            attempt=1,
            merge_previous_prefix=False,
            problem_payload=_problem_payload(),
            candidate_format="functional_plan",
        )


def test_single_dynamic_known_coefficient_lowers_to_parameter_pair() -> None:
    """One selected coefficient value must reach the runtime method exactly."""

    class FakeIndex:
        functional_consumer_identity_mode = "authoritative"

        def path_for(self, handle: str, *, expected_type: str) -> str:
            return f"{expected_type}:{handle}"

        def runtime_path_for_object_identity(
            self,
            object_id: MathObjectId,
            *,
            expected_type: str,
            **_kwargs,
        ) -> str:
            return f"{expected_type}:{object_id.value}"

        def runtime_path_for_state_version(
            self,
            _version_id: StateVersionId,
            **_kwargs,
        ) -> str:
            return "ParameterValue:fact:part:solved_parameter"

    compiler = object.__new__(_RecipePlanCompiler)
    compiler.index = FakeIndex()
    inputs = _heping_ermo_case()[0]
    spec = inputs.method_specs.require(
        "quadratic_from_constraints"
    )
    function = FunctionSpecRegistry.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).get("quadratic_from_constraints")
    assert function is not None and function.adapter is not None
    lowering = function.adapter.scalar_aggregate_lowerings[0]
    symbol_id = MathObjectId(
        "symbol:problem:c",
        "symbol",
        "problem",
    )
    parameter_logical_key = LogicalStateKey(
        symbol_id,
        "parameter",
        "ParameterValue",
    )
    item = ProjectedFunctionArgBinding(
        step_id="refine_quadratic",
        arg_name="known_coefficients",
        source_handle="fact:part:solved_parameter",
        runtime_type="ParameterValue",
        object_ref="symbol:problem:c",
        math_object_id=symbol_id,
        state_version_id=StateVersionId(
            StateSlotId(parameter_logical_key, "problem"),
            1,
        ),
    )
    result: dict[str, str] = {}
    selected: dict[str, ProjectedFunctionArgBinding] = {}

    lowered = compiler._lower_single_parameter_value_aggregate(
        spec,
        lowering=lowering,
        expected_type="Coefficients",
        items=[item],
        result=result,
        selected_items=selected,
        consumer_scope_id="part",
    )

    assert lowered is True
    assert result == {
        "parameter": "Symbol:symbol:problem:c",
        "parameter_value": (
            "ParameterValue:fact:part:solved_parameter"
        ),
    }
    assert selected == {"parameter_value": item}


def test_functional_mechanism_method_uses_latest_explicit_point_versions() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs, payload, registry, _context = _heping_ermo_case()
    recover_call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "recover_target_point_E_ii"
    )
    recover_call["args"]["side_start"], recover_call["args"]["side_end"] = (
        recover_call["args"]["side_end"],
        recover_call["args"]["side_start"],
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
        context=ContextBuilder().build(problem),
        attempt=1,
        problem_payload=problem_to_llm_payload(problem),
        validation_report=validation,
    )

    assert replay.output is not None, (
        replay.errors,
        replay.diagnostic.to_payload() if replay.diagnostic is not None else None,
    )
    assert replay.diagnostic is not None and replay.diagnostic.ok
    recovery = next(
        invocation
        for step in replay.output.step_plans
        if step.step_id == "recover_target_point_E_ii"
        for invocation in step.invocations
        if invocation.method_id == "square_adjacent_vertex_from_side"
    )
    assert recovery.inputs["side_start"] == "$question.ii.outputs.G_point"
    assert recovery.inputs["side_end"] == (
        "$question.ii.outputs.A_evaluated_point"
    )
    assert recovery.inputs["side_start_ref"] == "$question.ii.points.G"
    assert recovery.inputs["side_end_ref"] == "$question.ii.object_refs.A"
    answer_write = next(
        item
        for item in replay.diagnostic.state_write_provenance
        if item.step_id == "recover_target_point_E_ii"
        and item.produced_handle == "answer:ii.E"
    )
    assert answer_write.free_symbol_names == ()


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
    path_return = next(
        item
        for item in result.calls
        if item.call_id == original_id
    ).returns[0]
    assert path_return.selected_version_id is not None
    assert path_return.logical_state_key is not None
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
    evidence_issue = next(
        issue
        for issue in result.issues
        if issue.code == "functional.evidence_closure_unproven"
    )
    assert evidence_issue.call_id == "derive_intersection"
    assert evidence_issue.details["answer"] == "ii_2.intersection"


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
        "$question.ii.object_refs.A"
    )
    declaration = index.declarations["$question.ii.object_refs.A"]
    index.context.apply_declaration(declaration)
    object_ref = index.context.read_path(
        declaration.path,
        from_scope_id="ii",
        expected_type="PointRef",
    )
    assert object_ref.locked
    assert object_ref.value.name == "A"
    with pytest.raises(
        StrategyDraftValidationError,
        match="duplicate_point_coordinate_fact",
    ):
        index.point_ref_path_for("point:ii:A")


def test_typed_object_identity_projects_materialized_point_to_point_ref() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=(),
        functional_consumer_identity_mode="authoritative",
    )
    point_handle = "point:ii:A"
    object_id = MathObjectRegistry.from_sources(registry).resolve(
        point_handle
    )
    assert object_id is not None
    index.bindings[point_handle] = RuntimeHandleBinding(
        point_handle,
        "$question.ii.facts.A_coordinate",
        "Point",
        "materialized_state",
    )

    selected = index.runtime_path_for_object_identity(
        object_id,
        expected_type="PointRef",
        consumer_scope_id="ii",
        consumer="construct_A.point_ref",
    )

    assert selected == "$question.ii.object_refs.A"
    assert index.runtime_consumer_decisions[-1]["reason_code"] == (
        "typed_object_identity_point_ref_projection"
    )


def test_point_output_selector_uses_projected_transition_target() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=(),
    )
    index.register_projected_state_writes(
        (
            ProjectedStateWrite(
                step_id="refine_A",
                produced_handle="fact:ii:A_refined_coordinate",
                state_slot_id="point:ii:A.coordinate@ii",
                write_mode="transition",
                runtime_type="Point",
                object_ref="point:ii:A",
                transition_kind="dependency_refinement",
                previous_write_step_id="derive_A",
            ),
        )
    )
    step = StepIntent(
        step_id="refine_A",
        scope_id="ii",
        recipe_hint="synthetic_point_refinement",
        goal_type="derive_point",
        target="point:ii:A",
        strategy="refine the same point from a closed source state",
        produces=(
            ProducedFact(
                "fact:ii:A_refined_coordinate",
                "ii",
                output_type="Point",
            ),
        ),
    )

    selected = DEFAULT_BINDING_SELECTORS["point_output_ref"](step, index, {})

    assert selected == index.path_for(
        "point:ii:A",
        expected_type="PointRef|Point",
    )


def test_point_output_selector_prefers_typed_object_over_legacy_fact_name() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    index.register_projected_state_writes(
        (
            ProjectedStateWrite(
                step_id="derive_axis_point",
                produced_handle="fact:problem:d_coordinate_axis_point",
                state_slot_id="point:problem:D.coordinate@problem:Point",
                write_mode="create",
                runtime_type="Point",
                object_ref="point:problem:D",
                return_name="axis_point",
            ),
        )
    )
    step = StepIntent(
        step_id="derive_axis_point",
        scope_id="problem",
        recipe_hint="quadratic_axis_from_relation",
        goal_type="derive_axis_point",
        target="answer:i.axis_point",
        strategy="derive the axis point",
        produces=(
            ProducedFact(
                "fact:problem:d_coordinate_axis_point",
                "problem",
                output_type="Point",
            ),
            ProducedFact(
                "answer:i.axis_point",
                "problem",
                output_type="Point",
            ),
        ),
    )

    selected = DEFAULT_BINDING_SELECTORS["point_output_ref"](step, index, {})

    assert selected == index.point_ref_path_for("point:problem:D")


def test_projected_point_transition_uses_writable_state_destination() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=registry,
        question_goals=(),
    )
    produced = ProducedFact(
        "fact:ii:A_refined_coordinate",
        "ii",
        output_type="Point",
    )
    step = StepIntent(
        step_id="refine_A",
        scope_id="ii",
        recipe_hint="synthetic_point_refinement",
        goal_type="derive_point",
        target="point:ii:A",
        strategy="write a refined state without replacing the object declaration",
        produces=(produced,),
    )
    write = ProjectedStateWrite(
        step_id=step.step_id,
        produced_handle=produced.handle,
        state_slot_id="point:ii:A.coordinate@ii",
        write_mode="transition",
        runtime_type="Point",
        object_ref="point:ii:A",
        transition_kind="dependency_refinement",
        previous_write_step_id="derive_A",
    )

    promote = _promote_outputs_for_step(
        step,
        "synthetic_point_refinement",
        {"point": "$step.refine_A.outputs.point"},
        {"point": "Point"},
        index,
        MethodBindingRuleRegistry(),
        projected_state_writes=(write,),
    )

    assert promote == {
        "$step.refine_A.outputs.point": (
            "$question.ii.outputs.A_refined_coordinate"
        )
    }


def test_typed_parameter_destinations_use_symbol_identity() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
    index = CanonicalRuntimeBindingIndex.from_context(
        ContextBuilder().build(problem),
        handle_registry=_registry(),
        question_goals=(),
    )
    writes: list[ProjectedStateWrite] = []
    steps: list[tuple[StepIntent, ProducedFact, str]] = []
    for symbol, suffix in (("m", "length_parameter"), ("a", "curve_parameter")):
        step_id = f"phase_{suffix}"
        produced = ProducedFact(
            f"fact:ii_1:{step_id}_parameter_value",
            "ii_1",
            output_type="ParameterValue",
        )
        object_id = MathObjectId(
            f"symbol:problem:{symbol}",
            "symbol",
            "problem",
        )
        logical_key = LogicalStateKey(
            object_id,
            "value",
            "ParameterValue",
        )
        writes.append(
            ProjectedStateWrite(
                step_id=step_id,
                produced_handle=produced.handle,
                state_slot_id=(
                    f"symbol:problem:{symbol}.value@ii_1:ParameterValue"
                ),
                write_mode="create",
                runtime_type="ParameterValue",
                object_ref=object_id.value,
                return_name="parameter_value",
                math_object_id=object_id,
                logical_state_key=logical_key,
                typed_slot_id=StateSlotId(logical_key, "ii_1"),
            )
        )
        steps.append(
            (
                StepIntent(
                    step_id=step_id,
                    scope_id="ii_1",
                    recipe_hint="synthetic_parameter_solver",
                    goal_type="derive_parameter",
                    target=object_id.value,
                    strategy="derive one parameter value",
                    produces=(produced,),
                ),
                produced,
                symbol,
            )
        )
    index.register_projected_state_writes(tuple(writes))

    destinations = {
        symbol: _target_path_for_produced(
            produced,
            "ParameterValue",
            index,
            step,
        )
        for step, produced, symbol in steps
    }

    assert destinations == {
        "m": "$subquestion.ii_1.outputs.m",
        "a": "$subquestion.ii_1.outputs.a",
    }


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
                        *_path_reduction_setup_calls(),
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


def test_call_placement_identity_distinguishes_state_write_versions() -> None:
    object_id = MathObjectId("point:problem:B", "point", "problem")
    slot_id = StateSlotId(
        LogicalStateKey(object_id, "coordinate", "Point"),
        "problem",
    )
    open_key = ComputationKey(
        "consume_point",
        (
            ArgVersionBinding(
                "point",
                0,
                version_id=StateVersionId(slot_id, 1),
            ),
        ),
    )
    closed_key = ComputationKey(
        "consume_point",
        (
            ArgVersionBinding(
                "point",
                0,
                version_id=StateVersionId(slot_id, 2),
            ),
        ),
    )
    assert open_key != closed_key


def test_typed_call_merge_unions_disjoint_return_bindings() -> None:
    line_binding = SemanticRef(ref="guide", kind="line")
    point_binding = SemanticRef(ref="target", kind="point")
    previous_call = FunctionalCall(
        call_id="first",
        capability_id="multi_return",
        args={},
        return_bindings={"line": line_binding},
        strategy="first projection",
        reason="bind the line result",
    )
    duplicate_call = FunctionalCall(
        call_id="second",
        capability_id="multi_return",
        args={},
        return_bindings={"point": point_binding},
        strategy="second projection",
        reason="bind the point result",
    )

    merged = functional_call_placement_module._merged_return_bindings(
        previous_call,
        duplicate_call,
        transferred={},
    )

    assert merged == {
        "line": line_binding,
        "point": point_binding,
    }
    previous = FunctionalCallReconciliation(
        call_id="first",
        scope_id="ii",
        capability_id="multi_return",
        resolved_args={},
        returns=(
            FunctionalReturnAllocation(
                call_id="first",
                return_name="line",
                handle="fact:ii:first_line",
                runtime_type="Line",
                valid_scope="ii",
                state_slot_id="line:ii:guide.equation@ii:Line",
                object_ref="line:ii:guide",
                identity_policy="derived_role",
                write_mode="create",
                bound_ref=line_binding,
            ),
            FunctionalReturnAllocation(
                call_id="first",
                return_name="point",
                handle="fact:ii:first_point",
                runtime_type="Point",
                valid_scope="ii",
                state_slot_id="functional:ii:first:point",
                object_ref=None,
                identity_policy="derived_role",
                write_mode="create",
            ),
        ),
    )
    duplicate = replace(
        previous,
        call_id="second",
        returns=(
            replace(previous.returns[0], call_id="second"),
            replace(
                previous.returns[1],
                call_id="second",
                handle="fact:ii:second_point",
                state_slot_id="point:ii:target.coordinate@ii:Point",
                object_ref="point:ii:target",
                bound_ref=point_binding,
            ),
        ),
    )

    transferred = (
        functional_call_placement_module._transfer_return_allocations(
            previous,
            duplicate,
            transferred_bindings={"point": point_binding},
        )
    )

    assert transferred.returns[0].bound_ref == line_binding
    assert transferred.returns[1].bound_ref == point_binding
    assert transferred.returns[1].call_id == "first"


def test_typed_effect_key_uses_only_materialized_returns() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["quadratic_from_constraints"]
    parabola = FunctionalReturnAllocation(
        call_id="build_curve",
        return_name="parabola",
        handle="fact:ii:parabola_expression",
        runtime_type="Parabola",
        valid_scope="ii",
        state_slot_id="function:problem:parabola.expression@ii:Parabola",
        object_ref="function:problem:parabola",
        identity_policy="preserve_input_object",
        write_mode="transition",
        logical_state_key=LogicalStateKey(
            MathObjectId(
                "function:problem:parabola",
                "function",
                "problem",
            ),
            "expression",
            "Parabola",
        ),
    )

    merge_effect = (
        functional_call_placement_module._state_effect_key_for_returns(
            (parabola,),
            capability=capability,
        )
    )
    finalize_effect = (
        functional_call_placement_module._state_effect_key_for_returns(
            (parabola,),
            capability=capability,
            logical_keys={"parabola": parabola.logical_state_key},
        )
    )

    assert merge_effect == finalize_effect
    assert merge_effect is not None
    assert [item.return_name for item in merge_effect.returns] == [
        "parabola"
    ]


def test_final_derived_identity_uses_final_computation_key() -> None:
    objects = MathObjectRegistry()
    factory = StateIdentityFactory(objects)
    final_key = ComputationKey(
        "synthetic_path_reduction",
        (
            ArgVersionBinding(
                "condition",
                0,
                condition_id="condition:path",
            ),
        ),
    )
    provisional_refs = (
        "path_transformation:problem:derived_provisional_a",
        "path_transformation:problem:derived_provisional_b",
    )
    allocations = tuple(
        FunctionalReturnAllocation(
            call_id="reduce_path",
            return_name="path_transformation",
            handle=f"fact:ii:path_transformation_{index}",
            runtime_type="PathTransformation",
            valid_scope="ii",
            state_slot_id=f"{object_ref}.transformation@ii",
            object_ref=object_ref,
            identity_policy="derived_role",
            write_mode="create",
            logical_state_key=LogicalStateKey(
                factory.object_id(object_ref),
                "transformation",
                "PathTransformation",
            ),
        )
        for index, object_ref in enumerate(provisional_refs)
    )
    return_spec = SimpleNamespace(
        name="path_transformation",
        runtime_type="PathTransformation",
        semantic_role="path_transformation",
        equivalent_to=None,
        identity_policy="derived_role",
        identity_arg=None,
    )

    finalized_refs = {
        functional_call_placement_module._finalized_return_object_ref(
            allocation,
            return_spec=return_spec,
            computation_key=final_key,
            identity_factory=factory,
        )
        for allocation in allocations
    }

    assert len(finalized_refs) == 1
    assert finalized_refs.isdisjoint(provisional_refs)


def _typed_quadratic_duplicate_graph(
    *,
    first_bindings: dict[str, SemanticRef] | None = None,
    second_bindings: dict[str, SemanticRef] | None = None,
    third_bindings: dict[str, SemanticRef] | None = None,
    first_expectations: dict[str, str] | None = None,
    second_expectations: dict[str, str] | None = None,
    pinned_call_ids: frozenset[str] = frozenset(),
    first_scope: str = "ii",
    second_scope: str = "ii",
    pinned_return_scopes: dict[str, dict[str, str]] | None = None,
):
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["quadratic_from_constraints"]
    first_call = FunctionalCall(
        call_id="build_curve_first",
        capability_id=capability.capability_id,
        args={},
        return_bindings=first_bindings or {},
        strategy="build the curve",
        reason="first projection",
        return_expectations=first_expectations or {},
    )
    second_call = FunctionalCall(
        call_id="build_curve_second",
        capability_id=capability.capability_id,
        args={},
        return_bindings=second_bindings or {},
        strategy="build the same curve",
        reason="second projection",
        return_expectations=second_expectations or {},
    )
    third_call = (
        FunctionalCall(
            call_id="build_curve_third",
            capability_id=capability.capability_id,
            args={},
            return_bindings=third_bindings,
            strategy="build the same curve",
            reason="third projection",
        )
        if third_bindings is not None
        else None
    )
    computation_key = ComputationKey(capability.capability_id)
    parabola_key = LogicalStateKey(
        MathObjectId(
            "function:problem:parabola",
            "function",
            "problem",
        ),
        "expression",
        "Parabola",
    )
    parameter_key = LogicalStateKey(
        MathObjectId("symbol:problem:a", "symbol", "problem"),
        "value",
        "ParameterValue",
    )

    scopes_by_call = {
        "build_curve_first": first_scope,
        "build_curve_second": second_scope,
        "build_curve_third": second_scope,
    }

    def reconciled(call: FunctionalCall) -> FunctionalCallReconciliation:
        scope_id = scopes_by_call[call.call_id]
        return FunctionalCallReconciliation(
            call_id=call.call_id,
            scope_id=scope_id,
            capability_id=call.capability_id,
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="parabola",
                    handle=f"fact:ii:{call.call_id}_parabola",
                    runtime_type="Parabola",
                    valid_scope=scope_id,
                    state_slot_id=(
                        "function:problem:parabola.expression@ii:Parabola"
                    ),
                    object_ref="function:problem:parabola",
                    identity_policy="preserve_input_object",
                    write_mode="transition",
                    bound_ref=call.return_bindings.get("parabola"),
                    logical_state_key=parabola_key,
                    computation_key=computation_key,
                ),
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="parameter_value",
                    handle=f"fact:ii:{call.call_id}_parameter",
                    runtime_type="ParameterValue",
                    valid_scope=scope_id,
                    state_slot_id=(
                        "symbol:problem:a.value@ii:ParameterValue"
                    ),
                    object_ref="symbol:problem:a",
                    identity_policy="preserve_input_object",
                    write_mode="transition",
                    bound_ref=call.return_bindings.get("parameter_value"),
                    logical_state_key=parameter_key,
                    computation_key=computation_key,
                ),
            ),
        )

    calls = tuple(
        item
        for item in (first_call, second_call, third_call)
        if item is not None
    )
    plan = FunctionalPlan(
        scopes=tuple(
            FunctionalScope(
                scope_id,
                scope_id,
                tuple(
                    call
                    for call in calls
                    if scopes_by_call[call.call_id] == scope_id
                ),
            )
            for scope_id in dict.fromkeys(scopes_by_call[call.call_id] for call in calls)
        )
    )
    reconciled_by_id = {call.call_id: reconciled(call) for call in calls}
    result = functional_call_placement_module._canonicalize_typed_calls(
        plan,
        source_scopes={
            call.call_id: scopes_by_call[call.call_id] for call in calls
        },
        reconciled_by_id=reconciled_by_id,
        catalog=catalog,
        aliases={},
        groups={call.call_id: (call.call_id,) for call in calls},
        handle_registry=_registry(),
        pinned_canonical_call_ids=pinned_call_ids,
        pinned_return_scopes=pinned_return_scopes,
    )
    return plan, result


def test_typed_canonicalization_transfers_cross_return_object_bindings() -> None:
    parabola_binding = SemanticRef(ref="parabola", kind="function")
    parameter_binding = SemanticRef(ref="a", kind="symbol")
    plan, result = _typed_quadratic_duplicate_graph(
        first_bindings={"parabola": parabola_binding},
        second_bindings={"parameter_value": parameter_binding},
    )
    (
        aliases,
        _groups,
        reconciled,
        _keys,
        _repairs,
        issues,
        transferred_bindings,
        _expectations,
    ) = result

    assert issues == ()
    assert aliases == {"build_curve_second": "build_curve_first"}
    assert transferred_bindings["build_curve_first"] == {
        "parabola": parabola_binding,
        "parameter_value": parameter_binding,
    }
    canonical = (
        functional_call_placement_module._apply_transferred_return_bindings(
            plan,
            transferred_bindings,
        ).calls[0]
    )
    assert canonical.return_bindings == transferred_bindings[
        "build_curve_first"
    ]
    allocations = {
        item.return_name: item
        for item in reconciled["build_curve_first"].returns
    }
    assert allocations["parabola"].bound_ref == parabola_binding
    assert allocations["parameter_value"].bound_ref == parameter_binding


def test_typed_canonicalization_merges_compatible_expectations() -> None:
    _plan, result = _typed_quadratic_duplicate_graph(
        first_expectations={"parabola": "open_state"},
        second_expectations={"parabola": "open_state"},
    )
    aliases, _, _, _, _, issues, _, expectations = result

    assert aliases == {"build_curve_second": "build_curve_first"}
    assert issues == ()
    assert expectations["build_curve_first"] == {
        "parabola": "open_state"
    }


def test_typed_canonicalization_keeps_each_pinned_call_canonical() -> None:
    _plan, result = _typed_quadratic_duplicate_graph(
        pinned_call_ids=frozenset(
            {"build_curve_first", "build_curve_second"}
        ),
    )
    aliases, groups, _, _, repairs, issues, _, _ = result

    assert aliases == {}
    assert groups == {
        "build_curve_first": ("build_curve_first",),
        "build_curve_second": ("build_curve_second",),
    }
    assert repairs == ()
    assert issues == ()


def test_typed_canonicalization_does_not_alias_sibling_into_private_pin() -> None:
    _plan, result = _typed_quadratic_duplicate_graph(
        pinned_call_ids=frozenset({"build_curve_first"}),
        first_scope="ii_2",
        second_scope="ii_1",
        pinned_return_scopes={
            "build_curve_first": {
                "parabola": "ii_2",
                "parameter_value": "ii_2",
            }
        },
    )
    aliases, groups, _, _, _, issues, _, _ = result

    assert aliases == {}
    assert issues == ()
    assert groups == {
        "build_curve_first": ("build_curve_first",),
        "build_curve_second": ("build_curve_second",),
    }


def test_effective_wire_basis_filters_stale_typed_resolved_values() -> None:
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
    )

    def resolved_symbol(name: str) -> ResolvedFunctionalValue:
        view, _ = semantic_index.resolve(
            SemanticRef(ref=name, kind="symbol"),
            scope_id="i",
            accepted_types=("Symbol",),
        )
        assert view is not None
        return ResolvedFunctionalValue(
            handle=view.handle,
            runtime_type=view.runtime_type,
            valid_scope=view.valid_scope,
            object_ref=view.object_ref,
            math_object_id=view.math_object_id,
            state_version_id=view.state_version_id,
            source_version_ids=view.source_version_ids,
        )

    call = FunctionalCall(
        call_id="build_curve",
        capability_id="quadratic_from_constraints",
        args={
            "free_parameters": (
                SemanticRef(ref="b", kind="symbol"),
            )
        },
        return_bindings={},
        strategy="keep one free parameter",
        reason="exercise effective-wire synchronization",
    )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("i", "i", (call,)),),
    )
    reconciled = FunctionalCallReconciliation(
        call_id=call.call_id,
        scope_id="i",
        capability_id=call.capability_id,
        resolved_args={
            "free_parameters": (
                resolved_symbol("a"),
                resolved_symbol("b"),
            )
        },
        returns=(),
    )

    updated, repairs, issues = (
        functional_reconciliation_module._synchronize_wire_resolved_args(
            plan,
            reconciled=(reconciled,),
            catalog=catalog,
            semantic_index=semantic_index,
        )
    )

    assert issues == ()
    assert [
        value.object_ref
        for value in updated[0].resolved_args["free_parameters"]
    ] == ["symbol:problem:b"]
    assert [item.action for item in repairs] == [
        "synchronize_typed_wire_arg"
    ]


def test_effective_wire_basis_replaces_same_arity_stale_identity() -> None:
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
    )

    def resolved_symbol(name: str) -> ResolvedFunctionalValue:
        view, _ = semantic_index.resolve(
            SemanticRef(ref=name, kind="symbol"),
            scope_id="i",
            accepted_types=("Symbol",),
        )
        assert view is not None
        return ResolvedFunctionalValue(
            handle=view.handle,
            runtime_type=view.runtime_type,
            valid_scope=view.valid_scope,
            object_ref=view.object_ref,
            math_object_id=view.math_object_id,
        )

    call = FunctionalCall(
        call_id="build_curve",
        capability_id="quadratic_from_constraints",
        args={
            "free_parameters": (
                SemanticRef(ref="b", kind="symbol"),
            )
        },
        return_bindings={},
        strategy="keep b",
        reason="same arity identity replacement",
    )
    reconciled = FunctionalCallReconciliation(
        call_id=call.call_id,
        scope_id="i",
        capability_id=call.capability_id,
        resolved_args={
            "free_parameters": (resolved_symbol("a"),)
        },
        returns=(),
    )

    updated, repairs, issues = (
        functional_reconciliation_module._synchronize_wire_resolved_args(
            FunctionalPlan(
                scopes=(FunctionalScope("i", "i", (call,)),),
            ),
            reconciled=(reconciled,),
            catalog=catalog,
            semantic_index=semantic_index,
        )
    )

    assert issues == ()
    assert updated[0].resolved_args["free_parameters"][0].object_ref == (
        "symbol:problem:b"
    )
    assert [item.action for item in repairs] == [
        "synchronize_typed_wire_arg"
    ]


@pytest.mark.parametrize("typed_field", ("state_version", "math_object"))
def test_semantic_wire_match_does_not_fall_back_from_partial_typed_identity(
    typed_field: str,
) -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(
        object_id,
        "coordinate",
        "Point",
    )
    slot_id = StateSlotId(logical_key, "problem")
    version_id = StateVersionId(slot_id, 1)
    view = FunctionalSemanticView(
        ref="P",
        kind="point",
        handle="fact:problem:P_coordinate",
        runtime_type="Point",
        valid_scope="problem",
        object_ref=object_id.value,
        math_object_id=(
            object_id if typed_field == "math_object" else None
        ),
        logical_state_key=(
            logical_key if typed_field == "state_version" else None
        ),
        typed_slot_id=(
            slot_id if typed_field == "state_version" else None
        ),
        state_version_id=(
            version_id if typed_field == "state_version" else None
        ),
    )
    value = ResolvedFunctionalValue(
        handle="fact:problem:P_legacy",
        runtime_type="Point",
        valid_scope="problem",
        object_ref=object_id.value,
    )
    spec = SimpleNamespace(
        runtime_type="Point",
        accepted_item_types=(),
        accepted_condition_kinds=(),
    )
    semantic_index = SimpleNamespace(
        resolve=lambda *_args, **_kwargs: (view, None),
    )

    assert not functional_reconciliation_module._resolved_value_matches_wire_ref(
        value,
        SemanticRef("P", "point"),
        spec=spec,
        scope_id="ii",
        semantic_index=semantic_index,
        produced={},
    )


def test_effective_wire_call_result_replaces_stale_state_version() -> None:
    object_id = MathObjectId(
        "point:problem:P",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(
        object_id,
        "coordinate",
        "Point",
    )
    slot_id = StateSlotId(logical_key, "problem")
    stale_version = StateVersionId(slot_id, 1)
    current_version = StateVersionId(slot_id, 2)
    stale = ResolvedFunctionalValue(
        handle="fact:problem:P_v1",
        runtime_type="Point",
        valid_scope="problem",
        object_ref=object_id.value,
        source_call_id="produce_P",
        return_name="point",
        math_object_id=object_id,
        logical_state_key=logical_key,
        typed_slot_id=slot_id,
        state_version_id=stale_version,
    )
    current = replace(
        stale,
        handle="fact:problem:P_v2",
        state_version_id=current_version,
    )
    call = FunctionalCall(
        call_id="consume_P",
        capability_id="synthetic_consumer",
        args={
            "point": (
                CallResultRef("produce_P", "point"),
            )
        },
        return_bindings={},
        strategy="consume the current point version",
        reason="exercise call-result version synchronization",
    )
    reconciled = FunctionalCallReconciliation(
        call_id=call.call_id,
        scope_id="ii",
        capability_id=call.capability_id,
        resolved_args={"point": (stale,)},
        returns=(),
    )
    arg_spec = SimpleNamespace(
        name="point",
        binding_authority="wire",
        runtime_type="Point",
        accepted_item_types=(),
        accepted_condition_kinds=(),
    )
    catalog = SimpleNamespace(
        get=lambda capability_id: (
            SimpleNamespace(args=(arg_spec,))
            if capability_id == "synthetic_consumer"
            else None
        )
    )

    updated, repairs, issues = (
        functional_reconciliation_module._synchronize_wire_resolved_args(
            FunctionalPlan(
                scopes=(FunctionalScope("ii", "ii", (call,)),),
            ),
            reconciled=(reconciled,),
            catalog=catalog,
            semantic_index=SimpleNamespace(),
            produced={("produce_P", "point"): current},
        )
    )

    assert issues == ()
    assert updated[0].resolved_args["point"] == (current,)
    assert [item.action for item in repairs] == [
        "synchronize_typed_wire_arg"
    ]


def test_typed_canonicalization_safely_aliases_exact_copy_to_pinned_owner() -> None:
    _plan, result = _typed_quadratic_duplicate_graph(
        pinned_call_ids=frozenset({"build_curve_first"}),
    )
    aliases, groups, _, _, _, issues, transferred, expectations = result

    assert aliases == {"build_curve_second": "build_curve_first"}
    assert groups == {
        "build_curve_first": (
            "build_curve_first",
            "build_curve_second",
        )
    }
    assert transferred == {}
    assert expectations["build_curve_first"] == {}
    assert issues == ()


def test_typed_canonicalization_does_not_mutate_pinned_owner_bindings() -> None:
    parabola_binding = SemanticRef(ref="parabola", kind="function")
    parameter_binding = SemanticRef(ref="a", kind="symbol")
    _plan, result = _typed_quadratic_duplicate_graph(
        first_bindings={"parabola": parabola_binding},
        second_bindings={"parameter_value": parameter_binding},
        pinned_call_ids=frozenset({"build_curve_first"}),
    )
    aliases, groups, reconciled, _, _, _, transferred, _ = result

    assert aliases == {}
    assert groups == {
        "build_curve_first": ("build_curve_first",),
        "build_curve_second": ("build_curve_second",),
    }
    assert transferred == {}
    allocations = {
        item.return_name: item
        for item in reconciled["build_curve_first"].returns
    }
    assert allocations["parabola"].bound_ref == parabola_binding
    assert allocations["parameter_value"].bound_ref is None


def test_typed_canonicalization_blocks_conflicting_expectations_after_merge() -> None:
    _plan, result = _typed_quadratic_duplicate_graph(
        first_expectations={"parabola": "open_state"},
        second_expectations={"parabola": "closed_state"},
    )
    aliases, _, _, _, repairs, issues, _, expectations = result

    assert aliases == {"build_curve_second": "build_curve_first"}
    assert expectations == {}
    assert [item.code for item in issues] == [
        "functional.return_expectation_conflict"
    ]
    assert any(
        item.action == "merge_typed_call_with_expectation_conflict"
        for item in repairs
    )


def test_typed_canonicalization_starts_new_binding_cluster_after_conflict() -> None:
    answer_a = SemanticRef(ref="answer:a", kind="answer")
    answer_b = SemanticRef(ref="answer:b", kind="answer")
    _plan, result = _typed_quadratic_duplicate_graph(
        first_bindings={"parabola": answer_a},
        second_bindings={"parabola": answer_b},
        third_bindings={"parabola": answer_b},
    )
    aliases, groups, _, _, repairs, issues, _, _ = result

    assert aliases == {"build_curve_third": "build_curve_second"}
    assert groups["build_curve_first"] == ("build_curve_first",)
    assert groups["build_curve_second"] == (
        "build_curve_second",
        "build_curve_third",
    )
    assert [item.code for item in issues] == [
        "functional.return_binding_conflict"
    ]
    assert issues[0].call_id == "build_curve_second"
    assert issues[0].details == {
        "conflicting_calls": [
            {
                "call_id": "build_curve_first",
                "returns": [
                    {
                        "return_name": "parabola",
                        "existing": answer_a.to_payload(),
                        "incoming": answer_b.to_payload(),
                    }
                ],
            }
        ]
    }
    assert any(
        item.action == "merge_typed_equivalent_call"
        and item.call_id == "build_curve_third"
        for item in repairs
    )


def test_typed_canonicalization_ignores_optional_binding_value_type() -> None:
    untyped = SemanticRef(ref="target", kind="point")
    typed = SemanticRef(ref="target", kind="point", value_type="Point")
    _plan, result = _typed_quadratic_duplicate_graph(
        first_bindings={"parabola": untyped},
        second_bindings={"parabola": typed},
    )
    aliases, _, _, _, _, issues, _, _ = result

    assert issues == ()
    assert aliases == {"build_curve_second": "build_curve_first"}


def test_typed_canonicalization_rewrites_aliased_input_versions() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["quadratic_from_constraints"]
    logical_key = LogicalStateKey(
        MathObjectId(
            "function:problem:parabola",
            "function",
            "problem",
        ),
        "expression",
        "Parabola",
    )
    source_versions = (
        StateVersionId(StateSlotId(logical_key, "ii_1"), 1),
        StateVersionId(StateSlotId(logical_key, "ii_2"), 1),
    )
    result_versions = (
        StateVersionId(StateSlotId(logical_key, "ii_1"), 2),
        StateVersionId(StateSlotId(logical_key, "ii_2"), 2),
    )
    calls = tuple(
        FunctionalCall(
            call_id=call_id,
            capability_id=capability.capability_id,
            args={},
            return_bindings={},
            strategy="compute one pure state",
            reason="exercise typed canonicalization",
        )
        for call_id in (
            "source_first",
            "source_second",
            "consumer_first",
            "consumer_second",
        )
    )

    def allocation(
        call_id: str,
        *,
        computation_key: ComputationKey,
        version_id: StateVersionId,
    ) -> FunctionalReturnAllocation:
        return FunctionalReturnAllocation(
            call_id=call_id,
            return_name="parabola",
            handle=f"fact:ii:{call_id}_parabola",
            runtime_type="Parabola",
            valid_scope="ii",
            state_slot_id=(
                "function:problem:parabola.expression@ii:Parabola"
            ),
            object_ref="function:problem:parabola",
            identity_policy="preserve_input_object",
            write_mode="transition",
            logical_state_key=logical_key,
            selected_version_id=version_id,
            computation_key=computation_key,
        )

    source_key = ComputationKey(capability.capability_id)
    reconciled = {
        "source_first": FunctionalCallReconciliation(
            call_id="source_first",
            scope_id="ii",
            capability_id=capability.capability_id,
            resolved_args={},
            returns=(
                allocation(
                    "source_first",
                    computation_key=source_key,
                    version_id=source_versions[0],
                ),
            ),
        ),
        "source_second": FunctionalCallReconciliation(
            call_id="source_second",
            scope_id="ii",
            capability_id=capability.capability_id,
            resolved_args={},
            returns=(
                allocation(
                    "source_second",
                    computation_key=source_key,
                    version_id=source_versions[1],
                ),
            ),
        ),
    }
    for index, call_id in enumerate(("consumer_first", "consumer_second")):
        source_call_id = ("source_first", "source_second")[index]
        computation_key = ComputationKey(
            capability.capability_id,
                (
                    ArgVersionBinding(
                        "parabola",
                        0,
                        version_id=source_versions[index],
                    ),
                ),
        )
        reconciled[call_id] = FunctionalCallReconciliation(
            call_id=call_id,
            scope_id="ii",
            capability_id=capability.capability_id,
            resolved_args={
                "parabola": (
                    ResolvedFunctionalValue(
                        handle=f"fact:ii:{source_call_id}_parabola",
                        runtime_type="Parabola",
                        valid_scope="ii",
                        source_call_id=source_call_id,
                        state_version_id=source_versions[index],
                    ),
                )
            },
            returns=(
                allocation(
                    call_id,
                    computation_key=computation_key,
                    version_id=result_versions[index],
                ),
            ),
        )
    plan = FunctionalPlan(
        scopes=(FunctionalScope("ii", "ii", calls),)
    )

    result = functional_call_placement_module._canonicalize_typed_calls(
        plan,
        source_scopes={call.call_id: "ii" for call in calls},
        reconciled_by_id=reconciled,
        catalog=catalog,
        aliases={},
        groups={call.call_id: (call.call_id,) for call in calls},
        handle_registry=_registry(),
    )
    aliases, _, _, _, _, issues, _, _ = result

    assert issues == ()
    assert aliases == {
        "source_second": "source_first",
        "consumer_second": "consumer_first",
    }


def test_future_target_identity_flows_across_pure_computation_trees() -> None:
    _problem, inputs, _payload, registry, context, _fixture = _xiqing_case()
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "first branch",
                "calls": [
                    {
                        "call_id": "build_curve_first",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_point": {"kind": "point", "ref": "A"},
                            "free_parameters": {
                                "kind": "symbol",
                                "ref": "b",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "build an open curve",
                        "reason": "feed a target-object computation",
                    },
                    {
                        "call_id": "derive_target_first",
                        "capability_id": "point_on_parabola_at_x",
                        "args": {
                            "parabola": {
                                "from_call": "build_curve_first",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "compute the target point",
                        "reason": "the sibling binds its identity",
                    },
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "second branch",
                "calls": [
                    {
                        "call_id": "build_curve_second",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "curve_point": {"kind": "point", "ref": "A"},
                            "free_parameters": {
                                "kind": "symbol",
                                "ref": "b",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "build the same open curve",
                        "reason": "exercise recursive computation identity",
                    },
                    {
                        "call_id": "derive_target_second",
                        "capability_id": "point_on_parabola_at_x",
                        "args": {
                            "parabola": {
                                "from_call": "build_curve_second",
                                "return": "parabola",
                            }
                        },
                        "return_bindings": {
                            "point": {"kind": "point", "ref": "D"}
                        },
                        "strategy": "compute the bound target point",
                        "reason": "provide unique object identity evidence",
                    },
                ],
            },
        ],
    }
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    prepared = functional_reconciliation_module._NormalizeElaborateScopeStage().run(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert prepared.future_return_object_hints[
        ("derive_target_first", "point")
    ] == ("point:ii:D",)


def test_structured_return_roles_identify_blocked_point_producers() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
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
                "label": "first branch",
                "calls": [
                    {
                        "call_id": "derive_B",
                        "capability_id": "quadratic_x_axis_intercept_point",
                        "args": {
                            "quadratic": {
                                "ref": "parabola",
                                "kind": "function",
                            },
                            "known_point": {
                                "ref": "A",
                                "kind": "point",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "derive the other intercept",
                        "reason": "provide its materialized state",
                    },
                    {
                        "call_id": "derive_D",
                        "capability_id": "translated_point",
                        "args": {
                            "source": {
                                "ref": "C",
                                "kind": "point",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "translate the source point",
                        "reason": "provide the translated state",
                    },
                ],
            },
            {
                "scope_id": "i_2",
                "label": "second branch",
                "calls": [
                    {
                        "call_id": "derive_angle_relation",
                        "capability_id": "angle_sum_equal_angle_candidates",
                        "args": {
                            "condition": {
                                "ref": "angle_sum_CBE_ACO_45",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {},
                        "strategy": "derive one angle relation",
                        "reason": "consume the intercept state",
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

    prepared = functional_reconciliation_module._NormalizeElaborateScopeStage().run(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    assert prepared.future_return_object_hints[("derive_B", "point")] == (
        "point:problem:B",
    )
    assert prepared.future_return_object_hints[("derive_D", "point")] == (
        "point:problem:D",
    )
    assert "derive_B" in prepared.dependency_graph["derive_angle_relation"]


def _typed_cross_scope_point_duplicate_graph(
    *,
    source_origin_scope: str,
) -> tuple[FunctionalPlan, tuple[Any, ...]]:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(
        problem_to_llm_payload(problem)
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["quadratic_x_axis_intercept_point"]
    returned = capability.returns[0]
    source_object = MathObjectId(
        "function:problem:parabola",
        "function",
        source_origin_scope,
    )
    source_key = LogicalStateKey(
        source_object,
        "expression",
        "Parabola",
    )
    source_version = StateVersionId(
        StateSlotId(source_key, "i_1"),
        1,
    )
    target_object = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    target_key = LogicalStateKey(
        target_object,
        returned.state_kind,
        returned.runtime_type,
    )
    computation_key = ComputationKey(
        capability.capability_id,
        (
            ArgVersionBinding(
                "quadratic",
                0,
                version_id=source_version,
            ),
        ),
    )
    calls = tuple(
        FunctionalCall(
            call_id,
            capability.capability_id,
            {},
            {
                "point": SemanticRef(
                    "B",
                    "point",
                )
            },
            "derive the same point state",
            "exercise cross-scope typed sharing",
        )
        for call_id in ("derive_B_first", "derive_B_second")
    )

    def reconciliation(
        call: FunctionalCall,
        scope_id: str,
        ordinal: int,
    ) -> FunctionalCallReconciliation:
        return FunctionalCallReconciliation(
            call_id=call.call_id,
            scope_id=scope_id,
            capability_id=call.capability_id,
            resolved_args={
                "quadratic": (
                    ResolvedFunctionalValue(
                        handle="fact:i_1:curve",
                        runtime_type="Parabola",
                        valid_scope="i_1",
                        state_slot_id=(
                            "function:problem:parabola.expression@i_1:Parabola"
                        ),
                        source_call_id="build_curve",
                        return_name="parabola",
                        object_ref=source_object.value,
                        math_object_id=source_object,
                        logical_state_key=source_key,
                        typed_slot_id=source_version.slot_id,
                        state_version_id=source_version,
                    ),
                )
            },
            returns=(
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="point",
                    handle=f"fact:{scope_id}:{call.call_id}_point",
                    runtime_type=returned.runtime_type,
                    valid_scope=scope_id,
                    state_slot_id=(
                        f"point:problem:B.{returned.state_kind}"
                        f"@{scope_id}:{returned.runtime_type}"
                    ),
                    object_ref=target_object.value,
                    identity_policy=returned.identity_policy,
                    write_mode=returned.write_mode,
                    bound_ref=call.return_bindings["point"],
                    math_object_id=target_object,
                    logical_state_key=target_key,
                    typed_slot_id=StateSlotId(target_key, scope_id),
                    selected_version_id=StateVersionId(
                        StateSlotId(target_key, scope_id),
                        ordinal,
                    ),
                    computation_key=computation_key,
                ),
            ),
        )

    reconciled = {
        calls[0].call_id: reconciliation(calls[0], "i_1", 1),
        calls[1].call_id: reconciliation(calls[1], "i_2", 1),
    }
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope("i_1", "first", (calls[0],)),
            FunctionalScope("i_2", "second", (calls[1],)),
        )
    )
    result = functional_call_placement_module._canonicalize_typed_calls(
        plan,
        source_scopes={
            "build_curve": "i_1",
            "derive_B_first": "i_1",
            "derive_B_second": "i_2",
        },
        reconciled_by_id=reconciled,
        catalog=catalog,
        aliases={},
        groups={
            "derive_B_first": ("derive_B_first",),
            "derive_B_second": ("derive_B_second",),
        },
        handle_registry=registry,
    )
    return plan, result


def test_typed_canonicalization_merges_global_state_before_scope_placement() -> None:
    _plan, result = _typed_cross_scope_point_duplicate_graph(
        source_origin_scope="problem",
    )
    aliases, _groups, _calls, _keys, repairs, issues, _bindings, _forms = result

    assert issues == ()
    assert aliases == {"derive_B_second": "derive_B_first"}
    assert any(
        item.action == "merge_typed_equivalent_call"
        and item.call_id == "derive_B_second"
        for item in repairs
    )


def test_typed_canonicalization_keeps_sibling_private_state_separate() -> None:
    _plan, result = _typed_cross_scope_point_duplicate_graph(
        source_origin_scope="i_1",
    )
    aliases, groups, _calls, _keys, repairs, issues, _bindings, _forms = result

    assert issues == ()
    assert aliases == {}
    assert groups == {
        "derive_B_first": ("derive_B_first",),
        "derive_B_second": ("derive_B_second",),
    }
    assert repairs == ()


def test_path_context_can_defer_unique_planned_point_visibility() -> None:
    _problem, _inputs, _payload, registry, context, _fixture = _xiqing_case()
    semantic_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )
    target_object_id = MathObjectId("point:ii:D", "point", "ii")
    target_logical_key = LogicalStateKey(
        target_object_id,
        "coordinate",
        "Point",
    )
    target_slot_id = StateSlotId(target_logical_key, "ii")
    planned = ResolvedFunctionalValue(
        handle="fact:ii_1:target_coordinate",
        runtime_type="Point",
        valid_scope="ii_1",
        object_ref="point:ii:D",
        source_call_id="derive_target",
        math_object_id=target_object_id,
        logical_state_key=target_logical_key,
        typed_slot_id=target_slot_id,
        state_version_id=StateVersionId(target_slot_id, 1),
    )
    produced = {("derive_target", "point"): planned}

    assert latest_point_state_for_object(
        "point:ii:D",
        scope_id="ii_2",
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=registry,
    ) is None
    assert latest_point_state_for_object(
        "point:ii:D",
        scope_id="ii_2",
        produced=produced,
        semantic_index=semantic_index,
        handle_registry=registry,
        allow_unique_planned_producer=True,
    ) is planned


def test_path_context_prefers_visible_state_over_sibling_planned_state() -> None:
    problem = load_problem_ir(NANKAI_FIXTURE)
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
    planned = ResolvedFunctionalValue(
        handle="fact:ii_1:evaluated_M",
        runtime_type="Point",
        valid_scope="ii_1",
        object_ref="point:ii:M",
        source_call_id="evaluate_M",
    )

    selected = latest_point_state_for_object(
        "point:ii:M",
        scope_id="ii_2",
        produced={("evaluate_M", "evaluated_point"): planned},
        semantic_index=semantic_index,
        handle_registry=registry,
        allow_unique_planned_producer=True,
    )

    assert selected is not None
    assert selected is not planned
    assert selected.valid_scope == "ii"


def test_elaboration_defers_hidden_method_inputs_to_typed_placement() -> None:
    inputs = _base_inputs()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["midpoint_point"]
    call = FunctionalCall(
        "midpoint",
        "midpoint_point",
        {
            "midpoint_definition": (
                SemanticRef("F_midpoint_of_DN", "fact"),
            )
        },
        {},
        "derive the midpoint",
        "use its coordinate",
    )

    assert not functional_elaboration_module._wire_inputs_are_version_stable(
        call,
        capability,
    )


def test_typed_placement_merges_sibling_state_producers_after_resolution() -> None:
    inputs = replace(_base_inputs(), question_goals=[])

    def construct_target(call_id: str) -> dict[str, Any]:
        return {
            "call_id": call_id,
            "capability_id": "right_angle_equal_length_construct_and_select",
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
            "strategy": "construct the condition target",
            "reason": "provide the endpoint state",
        }

    def derive_midpoint(call_id: str) -> dict[str, Any]:
        return {
            "call_id": call_id,
            "capability_id": "midpoint_point",
            "args": {
                "midpoint_definition": {
                    "ref": "F_midpoint_of_DN",
                    "kind": "fact",
                }
            },
            "return_bindings": {
                "midpoint": {
                    "ref": "F",
                    "kind": "point",
                }
            },
            "strategy": "derive the midpoint",
            "reason": "consume the local endpoint state",
        }

    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii",
                "label": "ii",
                "calls": [
                    {
                        "call_id": "derive_axis_point",
                        "capability_id": "quadratic_axis_from_relation",
                        "args": {
                            "coefficient_relation": {
                                "ref": "coefficient_relation",
                                "kind": "fact",
                            }
                        },
                        "return_bindings": {
                            "axis_point": {
                                "ref": "D",
                                "kind": "point",
                            }
                        },
                        "strategy": "derive the fixed endpoint",
                        "reason": "provide the parent-scope state",
                    }
                ],
            },
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    construct_target("derive_target_1"),
                    derive_midpoint("derive_midpoint_1"),
                ],
            },
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    construct_target("derive_target_2"),
                    derive_midpoint("derive_midpoint_2"),
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

    assert result.ok, [item.to_payload() for item in result.issues]
    assert result.call_aliases == {
        "derive_target_2": "derive_target_1",
        "derive_midpoint_2": "derive_midpoint_1",
    }
    placements = {
        item.canonical_call_id: item
        for item in result.call_placements
    }
    assert placements["derive_target_1"].execution_scope_id == "ii"
    assert placements["derive_midpoint_1"].execution_scope_id == "ii"


def test_equal_length_ray_point_allocates_referenced_call_local_object() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i_2",
                "label": "i_2",
                "calls": [
                    {
                        "call_id": "construct_auxiliary",
                        "capability_id": "equal_length_ray_point",
                        "args": {
                            "anchor": {"kind": "point", "ref": "A"},
                            "reference_point": {
                                "kind": "point",
                                "ref": "O",
                            },
                            "ray_point": {"kind": "point", "ref": "O"},
                        },
                        "return_bindings": {},
                        "strategy": "construct a local auxiliary point",
                        "reason": "use it in the next call",
                    },
                    {
                        "call_id": "consume_auxiliary",
                        "capability_id": "distance_between_points",
                        "args": {
                            "p1": {
                                "from_call": "construct_auxiliary",
                                "return": "point",
                            },
                            "p2": {"kind": "point", "ref": "A"},
                        },
                        "return_bindings": {},
                        "strategy": "consume the local point",
                        "reason": "prove that the call result remains usable",
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
        planner_state_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
        ),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )

    assert result.ok
    producer = next(
        item for item in result.calls if item.call_id == "construct_auxiliary"
    )
    produced_point = next(
        item for item in producer.returns if item.return_name == "point"
    )
    assert produced_point.object_ref == (
        "point:i_2:construct_auxiliary_point"
    )
    assert any(
        repair["action"] == "allocate_planned_target_object"
        and repair["call_id"] == "construct_auxiliary"
        for repair in result.elaboration["deterministic_repairs"]
    )


def test_relation_call_inherits_explicit_downstream_answer_object_identity() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = json.loads(HEPING_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    i_2 = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "i_2"
    )
    derive_b = i_2["calls"][0]
    i_2["calls"] = [
        derive_b,
        {
            "call_id": "derive_angle_relation",
            "capability_id": "angle_sum_equal_angle_candidates",
            "args": {
                "condition": {
                    "kind": "fact",
                    "ref": "angle_sum_CBE_ACO_45",
                }
            },
            "return_bindings": {},
            "strategy": "derive the reusable angle relation",
            "reason": "feed the axis-intercept call",
        },
        {
            "call_id": "derive_answer_point",
            "capability_id": "axis_intercept_from_equal_acute_angles",
            "args": {
                "angle_equality": {
                    "from_call": "derive_angle_relation",
                    "return": "angle_equality",
                }
            },
            "return_bindings": {
                "point": {
                    "kind": "answer",
                    "ref": "i_2_E",
                }
            },
            "return_expectations": {"point": "closed_state"},
            "strategy": "derive the requested axis point",
            "reason": "bind the point answer",
        },
    ]
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=initial_planner_state_context(
            inputs,
            problem_payload=problem_payload,
            handle_registry=registry,
        ),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )

    assert not any(
        issue.code == "functional.auto_arg_identity_unresolved"
        for issue in result.issues
    ), [issue.to_payload() for issue in result.issues]
    relation = next(
        call for call in result.calls if call.call_id == "derive_angle_relation"
    )
    answer_call = next(
        call for call in result.calls if call.call_id == "derive_answer_point"
    )
    expected_object_ref = registry.answer_target_handles["answer:i_2_E"]
    assert relation.resolved_args["target"][0].object_ref == expected_object_ref
    assert answer_call.returns[0].object_ref == expected_object_ref
    assert result.projected_draft is not None
    relation_step = next(
        step
        for step in result.projected_draft.steps
        if step.step_id == "derive_angle_relation"
    )
    assert relation_step.target == expected_object_ref


def test_entity_state_resolver_prefers_exact_projected_read_version() -> None:
    old_path = "$problem.points.B"
    closed_path = "$subquestion.i_2.facts.B_coordinate"
    write = ProjectedStateWrite(
        step_id="compute_B_closed",
        produced_handle="fact:i_2:B_coordinate",
        state_slot_id="point:problem:B.coordinate@i_2",
        write_mode="create",
        runtime_type="Point",
        object_ref="point:problem:B",
    )
    fills: list[tuple[str, str]] = []
    index = SimpleNamespace(
        bindings={
            "point:problem:B": RuntimeHandleBinding(
                "point:problem:B",
                old_path,
                "Point",
                "old_state",
            ),
            "fact:i_2:B_coordinate": RuntimeHandleBinding(
                "fact:i_2:B_coordinate",
                closed_path,
                "Point",
                "compute_B_closed",
            ),
        },
        context=SimpleNamespace(is_visible=lambda _consumer, _producer: True),
        latest_projected_state_write_in_handles=(
            lambda object_ref, handles, before_step_id=None: (
                write
                if object_ref == "point:problem:B"
                and "fact:i_2:B_coordinate" in handles
                else None
            )
        ),
        record_applied_fill=lambda **kwargs: fills.append(
            (kwargs["resolved_handle"], kwargs["reason"])
        ),
    )
    step = StepIntent(
        step_id="consume_B",
        scope_id="i_2",
        recipe_hint="axis_intercept_from_equal_acute_angles",
        goal_type="derive_axis_intercept",
        target="",
        strategy="consume the exact closed B state",
        reads=("fact:i_2:B_coordinate",),
    )

    resolved = EntityStateResolver().resolve(
        "point:problem:B",
        "Point",
        step,
        index,
    )

    assert resolved == closed_path
    assert fills == [
        ("fact:i_2:B_coordinate", "exact_projected_state_version")
    ]


def test_compiler_binds_resolver_arg_to_exact_state_write_version() -> None:
    object_id = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    version_id = StateVersionId(slot_id, 1)
    compiler = object.__new__(_RecipePlanCompiler)
    compiler.projected_state_dependencies = (
        ProjectedStateDependency(
            step_id="derive_angle_relation",
            state_slot_id="point:problem:B.coordinate@problem",
            produced_handle="fact:i_2:B_evaluated_coordinate",
            runtime_type="Point",
            object_ref="point:problem:B",
            arg_name="x_axis_point",
            source="resolver",
            state_version_id=version_id,
        ),
    )
    compiler.index = SimpleNamespace(
        runtime_path_for_state_version=lambda resolved_version_id, **_: (
            f"$version[{resolved_version_id.ordinal}]"
        )
    )
    step = StepIntent(
        step_id="derive_angle_relation",
        scope_id="i_2",
        recipe_hint="angle_sum_equal_angle_candidates",
        goal_type="derive_angle_relation",
        target="",
        strategy="use the latest evaluated coordinate",
    )
    spec = SimpleNamespace(
        method_id="angle_sum_equal_angle_candidates",
        inputs={"x_axis_point": SimpleNamespace(type="Point")},
    )

    exact = compiler._projected_exact_state_dependency_inputs(
        step,
        spec,
        existing={},
    )

    assert exact == {
        "x_axis_point": "$version[1]"
    }


def test_compiler_binds_wire_arg_to_exact_state_write_version() -> None:
    object_id = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    version_id = StateVersionId(slot_id, 2)
    compiler = object.__new__(_RecipePlanCompiler)
    compiler.projected_function_arg_bindings = (
        ProjectedFunctionArgBinding(
            step_id="consume_B",
            arg_name="point",
            source_handle="fact:i_2:B_coordinate",
            runtime_type="Point",
            object_ref=object_id.value,
            math_object_id=object_id,
            state_version_id=version_id,
        ),
    )
    compiler.function_specs = SimpleNamespace(
        get=lambda _method_id: SimpleNamespace(adapter=None)
    )
    compiler.binding_rules = SimpleNamespace(rules={})
    compiler.index = SimpleNamespace(
        runtime_path_for_state_version=lambda selected, **_: (
            "$question.i_2.facts.B_closed"
            if selected == version_id
            else pytest.fail("wrong version selected")
        ),
        path_for=lambda *_args, **_kwargs: pytest.fail(
            "wire state binding must not use source_handle lookup"
        ),
    )
    step = StepIntent(
        step_id="consume_B",
        scope_id="i_2",
        recipe_hint="synthetic_consumer",
        goal_type="derive_value",
        target="",
        strategy="consume exact B version",
    )
    spec = SimpleNamespace(
        method_id="synthetic_consumer",
        inputs={"point": SimpleNamespace(type="Point")},
    )

    exact = compiler._projected_exact_function_inputs(step, spec)

    assert exact == {
        "point": "$question.i_2.facts.B_closed"
    }


def test_compiler_rejects_object_call_result_without_state_version() -> None:
    object_id = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    compiler = object.__new__(_RecipePlanCompiler)
    fallbacks: list[str] = []

    def reject_fallback(**kwargs: str) -> None:
        fallbacks.append(kwargs["reason"])
        raise StrategyDraftValidationError(
            "planner.runtime_state_binding_drift"
        )

    compiler.index = SimpleNamespace(
        record_legacy_runtime_identity_fallback=reject_fallback,
        path_for=lambda *_args, **_kwargs: pytest.fail(
            "materialized call result must not use source_handle"
        ),
    )
    binding = ProjectedFunctionArgBinding(
        step_id="consume_B",
        arg_name="point",
        source_handle="fact:i_2:B_coordinate",
        runtime_type="Point",
        object_ref=object_id.value,
        math_object_id=object_id,
        source_call_id="compute_B",
        source_return_name="point",
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.runtime_state_binding_drift",
    ):
        compiler._projected_input_path(
            binding,
            expected_type="Point",
            consumer_scope_id="i_2",
        )

    assert fallbacks == [
        "materialized_projected_arg_missing_state_version"
    ]


@pytest.mark.parametrize(
    ("binding", "resolver_name", "expected_args"),
    (
        (
            ProjectedFunctionArgBinding(
                step_id="consume_condition",
                arg_name="condition",
                source_handle="fact:ii:condition",
                runtime_type="Condition",
                condition_id="condition:ii:constraint",
            ),
            "runtime_path_for_condition_identity",
            ("condition:ii:constraint",),
        ),
        (
            ProjectedFunctionArgBinding(
                step_id="consume_expression",
                arg_name="expression",
                source_handle="value:expression",
                runtime_type="Expression",
                source_call_id="produce_expression",
                source_return_name="expression",
            ),
            "runtime_path_for_call_result_identity",
            ("produce_expression", "expression"),
        ),
    ),
)
def test_compiler_projects_non_state_typed_identity_without_path_fallback(
    binding: ProjectedFunctionArgBinding,
    resolver_name: str,
    expected_args: tuple[str, ...],
) -> None:
    calls: list[tuple[str, tuple[str, ...], dict[str, str]]] = []

    def resolve(*args: str, **kwargs: str) -> str:
        calls.append((resolver_name, args, kwargs))
        return "$question.ii.facts.typed_value"

    compiler = object.__new__(_RecipePlanCompiler)
    compiler.index = SimpleNamespace(
        runtime_path_for_condition_identity=(
            resolve
            if resolver_name == "runtime_path_for_condition_identity"
            else pytest.fail
        ),
        runtime_path_for_call_result_identity=(
            resolve
            if resolver_name == "runtime_path_for_call_result_identity"
            else pytest.fail
        ),
        path_for=lambda *_args, **_kwargs: pytest.fail(
            "typed condition/call-result must not use path_for"
        ),
    )

    path = compiler._projected_input_path(
        binding,
        expected_type=binding.runtime_type or "Expression",
        consumer_scope_id="ii",
    )

    assert path == "$question.ii.facts.typed_value"
    assert calls == [
        (
            resolver_name,
            expected_args,
            {
                "source_handle": binding.source_handle,
                "expected_type": binding.runtime_type,
                "consumer_scope_id": "ii",
                "consumer": f"{binding.step_id}.{binding.arg_name}",
            },
        )
    ]


def test_function_return_identity_uses_projected_math_object() -> None:
    object_id = MathObjectId(
        "point:ii:K",
        "point",
        "ii",
    )
    compiler = object.__new__(_RecipePlanCompiler)
    compiler.function_specs = SimpleNamespace(
        get=lambda _method_id: SimpleNamespace(
            returns=(
                SimpleNamespace(
                    name="point",
                    runtime_type="Point",
                    identity_arg="target",
                ),
            ),
            adapter=None,
        )
    )
    compiler.projected_state_writes = (
        ProjectedStateWrite(
            step_id="construct_K",
            produced_handle="fact:ii:K_coordinate",
            state_slot_id="point:ii:K.coordinate@ii:Point",
            write_mode="create",
            runtime_type="Point",
            object_ref=object_id.value,
            return_name="point",
            math_object_id=object_id,
        ),
    )
    compiler.index = SimpleNamespace(
        runtime_path_for_return_object_identity=lambda selected, **_: (
            "$question.ii.object_refs.K"
            if selected == object_id
            else pytest.fail("wrong return MathObjectId")
        ),
        point_identity_path_for=lambda _handle: pytest.fail(
            "return identity must not be recovered from a point handle"
        ),
    )
    step = StepIntent(
        step_id="construct_K",
        scope_id="ii",
        recipe_hint="synthetic_point_construct",
        goal_type="derive_point",
        target="point:ii:K",
        strategy="construct K",
    )
    spec = SimpleNamespace(
        method_id="synthetic_point_construct",
        inputs={"target": SimpleNamespace(type="PointRef")},
    )

    result = compiler._projected_function_return_identity_inputs(
        step,
        spec,
        existing={},
    )

    assert result == {"target": "$question.ii.object_refs.K"}


def test_compiler_rejects_resolver_arg_state_version_drift() -> None:
    object_id = MathObjectId(
        "point:problem:target",
        "point",
        "problem",
    )
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "problem")
    expected_version = StateVersionId(slot_id, 2)
    stale_version = StateVersionId(slot_id, 1)
    handle = "fact:problem:target_coordinate"
    compiler = object.__new__(_RecipePlanCompiler)
    compiler.projected_state_dependencies = (
        ProjectedStateDependency(
            step_id="consume_target",
            state_slot_id="point:problem:target.coordinate@problem",
            produced_handle=handle,
            runtime_type="Point",
            object_ref=object_id.value,
            arg_name="point",
            source="resolver",
            source_step_id="close_target",
            source_return_name="point",
            state_version_id=expected_version,
        ),
    )
    compiler.projected_state_writes = (
        ProjectedStateWrite(
            step_id="close_target",
            produced_handle=handle,
            state_slot_id="point:problem:target.coordinate@problem",
            write_mode="transition",
            runtime_type="Point",
            object_ref=object_id.value,
            return_name="point",
            math_object_id=object_id,
            logical_state_key=logical_key,
            typed_slot_id=slot_id,
            selected_version_id=stale_version,
            allocation_action="transition",
        ),
    )
    compiler.index = SimpleNamespace(
        path_for=lambda value, *, expected_type: (
            f"$exact[{value}:{expected_type}]"
        )
    )
    step = StepIntent(
        step_id="consume_target",
        scope_id="ii",
        recipe_hint="synthetic_consumer",
        goal_type="consume_point",
        target="",
        strategy="consume the selected state version",
    )
    spec = SimpleNamespace(
        method_id="synthetic_consumer",
        inputs={"point": SimpleNamespace(type="Point")},
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.contract_runtime_input_version_drift",
    ):
        compiler._projected_exact_state_dependency_inputs(
            step,
            spec,
            existing={},
        )


def test_angle_sum_auto_arg_selects_latest_point_state_version() -> None:
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
    condition = ResolvedFunctionalValue(
        handle="fact:i_2:angle_sum_CBE_ACO_45",
        runtime_type="Condition",
        valid_scope="i_2",
        condition_id="condition:angle_sum_CBE_ACO_45@i_2",
    )
    point_object_id = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    point_logical_key = LogicalStateKey(
        point_object_id,
        "coordinate",
        "Point",
    )
    point_slot_id = StateSlotId(point_logical_key, "problem")
    open_point = ResolvedFunctionalValue(
        handle="fact:problem:B_parameterized_coordinate",
        runtime_type="Point",
        valid_scope="problem",
        state_slot_id="point:problem:B.coordinate@problem",
        source_call_id="derive_B_open",
        return_name="point",
        object_ref="point:problem:B",
        free_symbol_refs=("symbol:problem:a",),
        math_object_id=point_object_id,
        logical_state_key=point_logical_key,
        typed_slot_id=point_slot_id,
        state_version_id=StateVersionId(point_slot_id, 1),
    )
    closed_point = replace(
        open_point,
        handle="fact:i_2:B_evaluated_coordinate",
        source_call_id="evaluate_B_closed",
        return_name="evaluated_point",
        free_symbol_refs=(),
        state_version_id=StateVersionId(point_slot_id, 2),
    )

    value, repair, issue = (
        functional_reconciliation_module._resolve_angle_sum_auto_arg(
            SimpleNamespace(
                name="x_axis_point",
                selector="angle_sum:x_axis_point",
            ),
            resolved_args={"condition": (condition,)},
            produced={
                ("derive_B_open", "point"): open_point,
                ("evaluate_B_closed", "evaluated_point"): closed_point,
            },
            semantic_index=semantic_index,
            handle_registry=registry,
            call_id="derive_angle_relation",
            scope_id="i_2",
        )
    )

    assert issue is None
    assert repair is not None
    assert value is not None
    assert value.handle == "fact:i_2:B_evaluated_coordinate"


def test_angle_sum_auto_arg_defers_declared_closed_producer_to_runtime() -> None:
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
    condition = ResolvedFunctionalValue(
        handle="fact:i_2:angle_sum_CBE_ACO_45",
        runtime_type="Condition",
        valid_scope="i_2",
        condition_id="condition:angle_sum_CBE_ACO_45@i_2",
    )
    point_object_id = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    point_logical_key = LogicalStateKey(
        point_object_id,
        "coordinate",
        "Point",
    )
    point_slot_id = StateSlotId(point_logical_key, "problem")
    planned_point = ResolvedFunctionalValue(
        handle="fact:i:B_coordinate",
        runtime_type="Point",
        valid_scope="i",
        state_slot_id="point:problem:B.coordinate@i",
        source_call_id="derive_B_closed",
        return_name="point",
        object_ref="point:problem:B",
        free_symbol_refs=("symbol:problem:a",),
        math_object_id=point_object_id,
        logical_state_key=point_logical_key,
        typed_slot_id=point_slot_id,
        state_version_id=StateVersionId(point_slot_id, 1),
    )

    value, repair, issue = (
        functional_reconciliation_module._resolve_angle_sum_auto_arg(
            SimpleNamespace(
                name="x_axis_point",
                selector="angle_sum:x_axis_point",
            ),
            resolved_args={"condition": (condition,)},
            produced={("derive_B_closed", "point"): planned_point},
            semantic_index=semantic_index,
            handle_registry=registry,
            call_id="derive_angle_relation",
            scope_id="i_2",
            planned_return_expectations={
                ("derive_B_closed", "point"): "closed_state"
            },
        )
    )

    assert issue is None
    assert value == planned_point
    assert repair is not None
    assert repair.action == "defer_closed_state_check_to_runtime"


def test_angle_sum_open_state_issue_repairs_producer_and_consumer() -> None:
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
    condition = ResolvedFunctionalValue(
        handle="fact:i_2:angle_sum_CBE_ACO_45",
        runtime_type="Condition",
        valid_scope="i_2",
        condition_id="condition:angle_sum_CBE_ACO_45@i_2",
    )
    point_object_id = MathObjectId(
        "point:problem:B",
        "point",
        "problem",
    )
    point_logical_key = LogicalStateKey(
        point_object_id,
        "coordinate",
        "Point",
    )
    point_slot_id = StateSlotId(point_logical_key, "problem")
    open_point = ResolvedFunctionalValue(
        handle="fact:problem:B_parameterized_coordinate",
        runtime_type="Point",
        valid_scope="problem",
        state_slot_id="point:problem:B.coordinate@problem",
        source_call_id="derive_B_open",
        return_name="point",
        object_ref="point:problem:B",
        free_symbol_refs=("symbol:problem:a",),
        math_object_id=point_object_id,
        logical_state_key=point_logical_key,
        typed_slot_id=point_slot_id,
        state_version_id=StateVersionId(point_slot_id, 1),
    )

    value, repair, issue = (
        functional_reconciliation_module._resolve_angle_sum_auto_arg(
            SimpleNamespace(
                name="x_axis_point",
                selector="angle_sum:x_axis_point",
            ),
            resolved_args={"condition": (condition,)},
            produced={("derive_B_open", "point"): open_point},
            semantic_index=semantic_index,
            handle_registry=registry,
            call_id="derive_angle_relation",
            scope_id="i_2",
            planned_return_expectations={},
        )
    )

    assert value is None
    assert repair is None
    assert issue is not None
    assert issue.code == "functional.arg_state_open"
    assert issue.details["producer_call_id"] == "derive_B_open"
    assert issue.details["repair_call_ids"] == [
        "derive_B_open",
        "derive_angle_relation",
    ]


def test_closed_state_requirement_does_not_accept_open_context_state() -> None:
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
    open_index = FunctionalSemanticIndex(
        (
            *semantic_index.views,
            FunctionalSemanticView(
                ref="C",
                kind="point",
                handle="fact:problem:C_parameterized_coordinate",
                runtime_type="Point",
                valid_scope="problem",
                object_ref="point:problem:C",
                state_slot_id="point:problem:C.coordinate@problem",
                free_symbol_refs=("symbol:problem:a",),
            ),
        ),
        handle_registry=registry,
        entity_payloads=semantic_index.entity_payloads,
        fact_payloads=semantic_index.fact_payloads,
    )

    assert functional_reconciliation_module._context_has_materialized_object_state(
        open_index,
        object_ref="point:problem:C",
        scope_id="i_2",
    )
    assert not (
        functional_reconciliation_module._context_has_materialized_object_state(
            open_index,
            object_ref="point:problem:C",
            scope_id="i_2",
            requires_closed_state=True,
        )
    )


def test_hidden_closed_state_dependency_prefers_planned_closed_producer() -> None:
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    base_index = FunctionalSemanticIndex.from_context(
        context,
        handle_registry=registry,
    )
    semantic_index = FunctionalSemanticIndex(
        (
            *base_index.views,
            FunctionalSemanticView(
                ref="B",
                kind="point",
                handle="fact:problem:B_parameterized_coordinate",
                runtime_type="Point",
                valid_scope="problem",
                object_ref="point:problem:B",
                state_slot_id="point:problem:B.coordinate@problem",
                free_symbol_refs=("symbol:problem:a",),
            ),
        ),
        handle_registry=registry,
        entity_payloads=base_index.entity_payloads,
        fact_payloads=base_index.fact_payloads,
    )
    producer = FunctionalCall(
        call_id="derive_B_closed",
        capability_id="synthetic_point_producer",
        args={},
        return_bindings={},
        return_expectations={"point": "closed_state"},
        strategy="produce a closed point state",
        reason="satisfy a downstream state requirement",
    )
    consumer = FunctionalCall(
        call_id="derive_angle_relation",
        capability_id="synthetic_angle_consumer",
        args={
            "condition": (
                SemanticRef("angle_sum_CBE_ACO_45", "fact"),
            )
        },
        return_bindings={},
        strategy="consume structured angle roles",
        reason="exercise hidden state dependencies",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope("i_1", "i_1", (producer,)),
            FunctionalScope("i_2", "i_2", (consumer,)),
        )
    )
    capabilities = {
        "synthetic_point_producer": SimpleNamespace(
            args=(),
            auto_args=(),
            context_resolvers=(),
        ),
        "synthetic_angle_consumer": SimpleNamespace(
            args=(),
            auto_args=(
                SimpleNamespace(
                    name="x_axis_point",
                    selector="angle_sum:x_axis_point",
                ),
            ),
            context_resolvers=(),
        ),
    }

    graph = (
        functional_reconciliation_module._with_hidden_condition_object_dependencies(
            plan,
            dependency_graph={
                "derive_B_closed": (),
                "derive_angle_relation": (),
            },
            catalog=SimpleNamespace(get=capabilities.get),
            semantic_index=semantic_index,
            future_return_object_hints={
                ("derive_B_closed", "point"): ("point:problem:B",)
            },
        )
    )

    assert graph["derive_angle_relation"] == ("derive_B_closed",)


def test_explicit_symbol_values_do_not_depend_on_future_symbol_writes() -> None:
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
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
    build_curve = FunctionalCall(
        call_id="build_curve",
        capability_id="quadratic_from_constraints",
        args={
            "known_coefficients": (
                SemanticRef("b_value", "fact"),
                SemanticRef("c_value", "fact"),
            ),
        },
        return_bindings={},
        strategy="materialize the fully known function",
        reason="exercise call-time semantic authority",
    )
    later_b = FunctionalCall(
        call_id="later_b",
        capability_id="synthetic_parameter_producer",
        args={},
        return_bindings={},
        strategy="produce another b state",
        reason="must not become a backward dependency",
    )
    later_c = replace(later_b, call_id="later_c")
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope("i_1", "i_1", (build_curve,)),
            FunctionalScope("ii", "ii", (later_b, later_c)),
        )
    )

    graph = (
        functional_reconciliation_module
        ._with_hidden_condition_object_dependencies(
            plan,
            dependency_graph={
                "build_curve": (),
                "later_b": (),
                "later_c": (),
            },
            catalog=catalog,
            semantic_index=semantic_index,
            future_return_object_hints={
                ("later_b", "parameter_value"): ("symbol:problem:b",),
                ("later_c", "parameter_value"): ("symbol:problem:c",),
            },
        )
    )

    assert graph["build_curve"] == ()


def test_reconciler_prunes_unknown_arg_and_collects_remaining_contract_errors() -> None:
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
        "functional.arg_cardinality",
    }
    assert not any(item.code == "functional.arg_unknown" for item in result.issues)
    effective = next(
        call for call in result.plan.calls if call.call_id == "bad_midpoint"
    )
    assert "invented" not in effective.args
    assert any(
        item["call_id"] == "bad_midpoint"
        and item["action"] == "drop_unknown_capability_arg"
        for item in result.elaboration["deterministic_repairs"]
    )


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
                "merge_typed_equivalent_call",
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
        item["action"] == "merge_typed_equivalent_call"
        and item["call_id"] == "derive_axis_point_for_object"
        for item in result.elaboration["deterministic_repairs"]
    )


@pytest.mark.parametrize(
    ("second_scope", "expect_conflict"),
    (("i", True), ("i_2", False)),
)
def test_finalizer_distinguishes_overlapping_and_sibling_object_states(
    second_scope: str,
    expect_conflict: bool,
) -> None:
    inputs, _fixture, registry, context = _heping_ermo_case()
    inputs = replace(inputs, question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i_1",
                "label": "first question",
                "calls": [
                    {
                        "call_id": "derive_existing_a",
                        "capability_id": "quadratic_x_axis_intercept_point",
                        "args": {
                            "quadratic": {
                                "ref": "parabola",
                                "kind": "function",
                            },
                        },
                        "return_bindings": {
                            "point": {
                                "ref": "problem.A",
                                "kind": "point",
                            },
                        },
                        "strategy": "derive the existing point coordinate",
                        "reason": "materialize the shared object state",
                    },
                ],
            },
            {
                "scope_id": second_scope,
                "label": "second state branch",
                "calls": [
                    {
                        "call_id": "materialize_parabola",
                        "capability_id": "quadratic_from_constraints",
                        "args": {
                            "known_coefficients": [
                                {"ref": "b_value", "kind": "fact"},
                                {"ref": "c_value", "kind": "fact"},
                            ],
                        },
                        "return_bindings": {},
                        "strategy": "materialize the same function",
                        "reason": "exercise a distinct input path",
                    },
                    {
                        "call_id": "derive_existing_a_again",
                        "capability_id": "quadratic_x_axis_intercept_point",
                        "args": {
                            "quadratic": {
                                "from_call": "materialize_parabola",
                                "return": "parabola",
                            },
                        },
                        "return_bindings": {
                            "point": {
                                "ref": "problem.A",
                                "kind": "point",
                            },
                        },
                        "strategy": "derive the same coordinate again",
                        "reason": "rewrite the point in an overlapping scope",
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

    if expect_conflict:
        with pytest.raises(
            StrategyDraftValidationError,
            match="state.logical_duplicate_writer",
        ):
            FunctionalPlanReconciler().reconcile(
                plan,
                planner_state_context=context,
                family_spec=inputs.family_spec,
                method_specs=inputs.method_specs,
                handle_registry=registry,
                question_goals=(),
            )
        return

    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=(),
    )
    assert result.ok
    point_writes = [
        allocation
        for call in result.calls
        for allocation in call.returns
        if allocation.object_ref == "point:problem:A"
    ]
    assert {
        allocation.typed_slot_id.storage_scope_id
        for allocation in point_writes
        if allocation.typed_slot_id is not None
    } == {"i_1", "i_2"}


def test_final_typed_allocation_orders_wire_consumer_after_producer() -> None:
    producer = FunctionalCall(
        call_id="produce_state",
        capability_id="produce",
        args={},
        return_bindings={},
        strategy="produce one state",
        reason="supply a typed version",
    )
    consumer = FunctionalCall(
        call_id="consume_state",
        capability_id="consume",
        args={
            "state": (
                CallResultRef("produce_state", "state"),
            )
        },
        return_bindings={},
        strategy="consume that state",
        reason="exercise dependency ordering",
    )

    ordered = functional_call_placement_module._topological_calls(
        (consumer, producer),
        dependency_graph={
            "consume_state": ("produce_state",),
            "produce_state": (),
        },
    )

    assert [call.call_id for call in ordered] == [
        "produce_state",
        "consume_state",
    ]


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
    assert {item.handle for item in projected[0].produces} == {
        "fact:problem:derive_axis_point_globally_axis_point",
        "answer:i.axis_point",
    }
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


def test_post_placement_invisible_call_result_is_retryable_plan_issue() -> None:
    producer = FunctionalCallReconciliation(
        call_id="produce_child_state",
        scope_id="ii_1",
        capability_id="synthetic_producer",
        resolved_args={},
        returns=(),
    )
    consumer = FunctionalCallReconciliation(
        call_id="consume_from_sibling",
        scope_id="ii_2",
        capability_id="synthetic_consumer",
        resolved_args={
            "state": (
                ResolvedFunctionalValue(
                    handle="fact:ii_1:child_state",
                    runtime_type="Expression",
                    valid_scope="ii_1",
                    state_slot_id="functional:ii_1:child_state",
                    source_call_id="produce_child_state",
                    return_name="expression",
                ),
            )
        },
        returns=(),
    )

    issues = functional_call_placement_module._post_placement_scope_issues(
        (producer, consumer),
        registry=_registry(),
    )

    assert len(issues) == 1
    assert issues[0].code == "functional.arg_scope_invisible"
    assert issues[0].call_id == "consume_from_sibling"
    assert issues[0].details["repair_call_ids"] == [
        "produce_child_state",
        "consume_from_sibling",
    ]
    mismatches = (
        {
            "call_id": "consume_from_sibling",
            "arg": "state",
            "reason_code": "input_version_not_visible",
            "message": "typed input is not visible",
        },
        {
            "call_id": "other_call",
            "return": "point",
            "reason_code": "return_scope_drift",
            "message": "return scope changed",
        },
    )

    filtered = (
        functional_call_placement_module
        ._suppress_repairable_scope_mismatches(
            mismatches,
            scope_issues=issues,
        )
    )

    assert filtered == (mismatches[1],)


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
        (
            "fact:ii_1:evaluate_parabola_evaluated_parabola",
            "Parabola",
        ),
        ("answer:ii_1.parabola", "Parabola"),
    ]


def test_call_result_reports_inactive_polymorphic_return_variant() -> None:
    producer = ResolvedFunctionalValue(
        handle="fact:i:evaluate_expression",
        runtime_type="Expression",
        valid_scope="i",
        source_call_id="evaluate_expression",
        return_name="evaluated_expression",
    )

    value, issues = functional_reconciliation_module._resolve_functional_ref(
        CallResultRef("evaluate_expression", "evaluated_parabola"),
        arg_name="parabola",
        call_id="derive_vertex",
        scope_id="i",
        accepted_types=("Parabola",),
        accepted_condition_kinds=(),
        aggregation="none",
        semantic_index=FunctionalSemanticIndex(
            (),
            handle_registry=_registry(),
        ),
        produced={
            ("evaluate_expression", "evaluated_parabola"): producer,
        },
        handle_registry=_registry(),
        known_call_ids={"evaluate_expression", "derive_vertex"},
        processed_call_ids={"evaluate_expression"},
        deterministic_repairs=[],
        input_closure_policy="any",
    )

    assert value is None
    assert [item.code for item in issues] == [
        "functional.return_variant_mismatch"
    ]
    assert issues[0].details == {
        "arg": "parabola",
        "accepted_item_types": ["Parabola"],
        "actual_type": "Expression",
        "requested_return": "evaluated_parabola",
        "active_return": "evaluated_expression",
    }


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


def test_elaborator_merges_calls_after_dropping_internal_return_binding() -> None:
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
                            "straightened_endpoint_2": {
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

    assert len(result.plan.calls) == 2
    assert result.plan.calls[1].call_id == "derive_minimum"
    assert result.plan.calls[1].return_bindings == {}
    assert result.call_aliases == {"bind_minimum_point": "derive_minimum"}
    assert any(
        item.action == "drop_internal_only_return_binding"
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


def test_liveness_drops_unconsumed_pure_object_binding() -> None:
    inputs = _base_inputs()
    first_object_binding = FunctionalCall(
        call_id="first_object_state",
        capability_id="quadratic_y_axis_intercept_point",
        args={},
        return_bindings={
            "point": SemanticRef(ref="M", kind="point"),
        },
        strategy="derive the first object state",
        reason="the first writer remains observable",
    )
    duplicate_object_binding = FunctionalCall(
        call_id="duplicate_object_state",
        capability_id="quadratic_y_axis_intercept_point",
        args={},
        return_bindings={
            "point": SemanticRef(ref="M", kind="point"),
        },
        strategy="repeat the same unconsumed object state",
        reason="exercise duplicate object-state liveness",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope(
                scope_id="i",
                label="i",
                calls=(first_object_binding, duplicate_object_binding),
            ),
        )
    )
    reports = tuple(
        FunctionalCallReport(
            call.call_id,
            "i",
            call.capability_id,
            "valid",
        )
        for call in plan.calls
    )
    state_slot_id = "point:problem:M.coordinate@i:Point"
    reconciled = tuple(
        FunctionalCallReconciliation(
            call_id=call.call_id,
            scope_id="i",
            capability_id=call.capability_id,
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id=call.call_id,
                    return_name="point",
                    handle=f"fact:i:{call.call_id}_point",
                    runtime_type="Point",
                    valid_scope="i",
                    state_slot_id=state_slot_id,
                    object_ref="point:problem:M",
                    identity_policy="target_object",
                    write_mode="create",
                ),
            ),
        )
        for call in plan.calls
    )

    result = FunctionalCallLivenessAnalyzer().analyze(
        plan,
        reconciled=reconciled,
        call_reports=reports,
        dependency_graph={
            "first_object_state": (),
            "duplicate_object_state": (),
        },
        catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )

    assert [call.call_id for call in result.plan.calls] == [
        "first_object_state"
    ]
    assert result.dropped_call_ids == ("duplicate_object_state",)


def test_liveness_drops_writer_kept_only_by_unproven_predecessor_edge() -> None:
    inputs = _base_inputs()
    object_id = MathObjectId("point:part:target", "point", "part")
    logical_key = LogicalStateKey(object_id, "coordinate", "Point")
    slot_id = StateSlotId(logical_key, "part")
    provisional_version = StateVersionId(slot_id, 1)
    answer_version = StateVersionId(slot_id, 2)
    provisional = FunctionalCall(
        call_id="provisional_writer",
        capability_id="evaluate_point_at_parameter",
        args={},
        return_bindings={
            "evaluated_point": SemanticRef(
                ref="part.target",
                kind="point",
            ),
        },
        strategy="derive a provisional state",
        reason="exercise pre-liveness allocation",
    )
    answer = FunctionalCall(
        call_id="answer_writer",
        capability_id="evaluate_point_at_parameter",
        args={},
        return_bindings={
            "evaluated_point": SemanticRef(
                ref="part.target",
                kind="answer",
            ),
        },
        strategy="derive the answer state independently",
        reason="the provisional predecessor is not an input",
    )
    plan = FunctionalPlan(
        scopes=(
            FunctionalScope(
                scope_id="part",
                label="part",
                calls=(provisional, answer),
            ),
        )
    )
    reconciled = (
        FunctionalCallReconciliation(
            call_id=provisional.call_id,
            scope_id="part",
            capability_id=provisional.capability_id,
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id=provisional.call_id,
                    return_name="evaluated_point",
                    handle="fact:part:provisional",
                    runtime_type="Point",
                    valid_scope="part",
                    state_slot_id="compatibility-only",
                    object_ref=object_id.value,
                    identity_policy="preserve_input_object",
                    write_mode="transition",
                    math_object_id=object_id,
                    logical_state_key=logical_key,
                    typed_slot_id=slot_id,
                    selected_version_id=provisional_version,
                ),
            ),
        ),
        FunctionalCallReconciliation(
            call_id=answer.call_id,
            scope_id="part",
            capability_id=answer.capability_id,
            resolved_args={},
            returns=(
                FunctionalReturnAllocation(
                    call_id=answer.call_id,
                    return_name="evaluated_point",
                    handle="answer:part.target",
                    runtime_type="Point",
                    valid_scope="part",
                    state_slot_id="compatibility-only",
                    object_ref=object_id.value,
                    identity_policy="preserve_input_object",
                    write_mode="transition",
                    math_object_id=object_id,
                    logical_state_key=logical_key,
                    typed_slot_id=slot_id,
                    selected_version_id=answer_version,
                    previous_version_id=provisional_version,
                ),
            ),
        ),
    )
    reports = tuple(
        FunctionalCallReport(
            call.call_id,
            "part",
            call.capability_id,
            "valid",
        )
        for call in plan.calls
    )

    result = FunctionalCallLivenessAnalyzer().analyze(
        plan,
        reconciled=reconciled,
        call_reports=reports,
        dependency_graph={
            provisional.call_id: (),
            answer.call_id: (provisional.call_id,),
        },
        catalog=FunctionalCapabilityCatalog.from_family_spec(
            inputs.family_spec,
            inputs.method_specs,
        ),
    )

    assert [call.call_id for call in result.plan.calls] == [
        "answer_writer"
    ]
    assert result.dropped_call_ids == ("provisional_writer",)


def test_reconciler_rewrites_consumed_pure_write_to_existing_object_state() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    common_scope = next(
        item for item in payload["scopes"] if item["scope_id"] == "ii"
    )
    parabola_index = next(
        index
        for index, call in enumerate(common_scope["calls"])
        if call["call_id"] == "ii_derive_parabola"
    )
    common_scope["calls"].insert(
        parabola_index + 1,
        {
            "call_id": "recompute_existing_M",
            "capability_id": "point_on_parabola_at_x",
            "args": {
                "parabola": {
                    "from_call": "ii_derive_parabola",
                    "return": "parabola",
                }
            },
            "return_bindings": {
                "point": {
                    "ref": "M",
                    "kind": "point",
                }
            },
            "strategy": "recompute an already materialized point",
            "reason": "exercise initial StateSlot liveness",
        },
    )
    solve_m = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_1_solve_m"
    )
    solve_m["args"]["p1"] = {
        "from_call": "recompute_existing_M",
        "return": "point",
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
    assert "recompute_existing_M" not in {
        call.call_id for call in result.plan.calls
    }
    assert result.projected_draft is not None
    assert "recompute_existing_M" not in {
        step.step_id for step in result.projected_draft.steps
    }
    rewritten_solve_m = next(
        call for call in result.plan.calls if call.call_id == "ii_1_solve_m"
    )
    assert rewritten_solve_m.args["p1"] == (
        SemanticRef(ref="M", kind="point"),
    )
    assert any(
        item["action"]
        == "rewrite_redundant_pure_function_call_to_existing_state"
        and item["call_id"] == "recompute_existing_M"
        for item in result.elaboration["deterministic_repairs"]
    )


def test_reconciler_keeps_transition_of_existing_object_state() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    first_subquestion = next(
        item for item in payload["scopes"] if item["scope_id"] == "ii_1"
    )
    solve_index = next(
        index
        for index, call in enumerate(first_subquestion["calls"])
        if call["call_id"] == "ii_1_solve_m"
    )
    first_subquestion["calls"].insert(
        solve_index + 1,
        {
            "call_id": "specialize_existing_M",
            "capability_id": "evaluate_point_at_parameter",
            "args": {
                "point": {
                    "ref": "M",
                    "kind": "point",
                },
                "parameter_value": {
                    "from_call": "ii_1_solve_m",
                    "return": "parameter_value",
                },
            },
            "return_bindings": {
                "evaluated_point": {
                    "ref": "M",
                    "kind": "point",
                }
            },
            "strategy": "specialize the existing point state",
            "reason": "a transition must not be treated as a duplicate create",
        },
    )
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
    assert "specialize_existing_M" in {
        call.call_id for call in result.plan.calls
    }
    assert not any(
        item["action"] == "drop_dead_pure_function_call"
        and item["call_id"] == "specialize_existing_M"
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
    assert invocation.inputs["curve_points"] == (
        "$subquestion.ii_1.outputs.M_evaluated_point",
        "$subquestion.ii_1.outputs.N_evaluated_point",
    )
    assert "p1" not in invocation.inputs
    assert "p2" not in invocation.inputs


def test_elaborator_defers_cross_scope_call_merge_to_typed_placement() -> None:
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
        "construct_duplicate_point",
        "derive_child_midpoint",
    ]
    midpoint_ref = result.plan.calls[2].args["p2"][0]
    assert midpoint_ref.from_call == "construct_duplicate_point"
    assert not result.call_aliases


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
                            "target_parameter": {
                                "ref": "a",
                                "kind": "symbol",
                            },
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
    target_parameters = calls["solve_numeric_parabola"].resolved_args[
        "target_parameter"
    ]
    assert len(parameter_values) == 1
    assert parameter_values[0].object_ref == "symbol:problem:m"
    assert parameter_values[0].source_call_id == "solve_parameter"
    assert len(target_parameters) == 1
    assert target_parameters[0].object_ref == "symbol:problem:a"
    assert result.dependency_graph["solve_numeric_parabola"] == (
        "solve_parameter",
    )
    assert any(
        item["action"] == "auto_fill_optional_arg"
        for item in (result.elaboration or {})["deterministic_repairs"]
    )


def test_optional_parameter_value_requires_exact_unresolved_symbol_identity() -> None:
    inputs, _payload, registry, context = _heping_ermo_case()
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
    capability = catalog.items["square_adjacent_vertex_from_side"]
    c_ref = "symbol:problem:c"
    b_ref = "symbol:problem:b"
    point = ResolvedFunctionalValue(
        handle="fact:ii:open_point",
        runtime_type="Point",
        valid_scope="ii",
        state_slot_id="point:ii:E.coordinate@ii",
        object_ref="point:ii:E",
        free_symbol_refs=(c_ref,),
    )
    b_value = ResolvedFunctionalValue(
        handle="fact:ii:b_value",
        runtime_type="ParameterValue",
        valid_scope="ii",
        state_slot_id="symbol:problem:b.value@ii",
        source_call_id="derive_b",
        return_name="parameter_value",
        object_ref=b_ref,
        dependency_object_refs=(b_ref, c_ref),
    )

    additions, repairs = (
        functional_reconciliation_module._resolve_deterministic_optional_args(
            capability,
            {
                "side_start": (point,),
                "side_end": (point,),
            },
            call_id="construct_square_vertex",
            scope_id="ii",
            produced={("derive_b", "parameter_value"): b_value},
            semantic_index=FunctionalSemanticIndex.from_context(
                context,
                handle_registry=registry,
            ),
            handle_registry=registry,
        )
    )

    assert "parameter_value" not in additions
    assert not any(
        item.action == "auto_fill_optional_arg"
        and "parameter_value" in item.after
        for item in repairs
    )


def test_symbolic_target_is_inferred_from_exact_downstream_substitution() -> None:
    inputs = _base_inputs()
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_1",
                "label": "ii_1",
                "calls": [
                    {
                        "call_id": "derive_parameterized_curve",
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
                        "return_bindings": {},
                        "strategy": "derive a parameterized curve",
                        "reason": "publish the solved coefficient state",
                    },
                    {
                        "call_id": "consume_solved_coefficient",
                        "capability_id": "evaluate_expression_at_parameter",
                        "args": {
                            "expression": {
                                "from_call": "derive_parameterized_curve",
                                "return": "parabola",
                            },
                            "parameter": {
                                "ref": "a",
                                "kind": "symbol",
                            },
                            "parameter_value": {
                                "from_call": "derive_parameterized_curve",
                                "return": "parameter_value",
                            },
                        },
                        "return_bindings": {},
                        "strategy": "consume the solved coefficient",
                        "reason": "exercise typed target identity inference",
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

    inferred, repairs = _infer_symbolic_target_args_from_consumers(
        plan,
        catalog=catalog,
    )

    producer = next(
        call
        for call in inferred.calls
        if call.call_id == "derive_parameterized_curve"
    )
    assert producer.args["target_parameter"] == (
        SemanticRef(ref="a", kind="symbol"),
    )
    assert any(
        item.action == "infer_symbolic_target_from_consumer"
        and item.call_id == "derive_parameterized_curve"
        for item in repairs
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
    assert "solve_parameter" in result.dependency_graph["evaluate_point"]
    pending = ["evaluate_point"]
    ancestors: set[str] = set()
    while pending:
        current = pending.pop()
        for dependency in result.dependency_graph.get(current, ()):
            if dependency not in ancestors:
                ancestors.add(dependency)
                pending.append(dependency)
    assert {
        "reduce_path_derive_axis",
        "reduce_path_construct_target",
        "reduce_path_derive_midpoint",
    } <= ancestors


def test_reconciler_drops_unknown_compiler_owned_arg_without_identity_check() -> None:
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
                            "parameter": {"ref": "m", "kind": "symbol"},
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
    effective = next(
        call for call in result.plan.calls if call.call_id == "evaluate_point"
    )
    assert "parameter" not in effective.args
    assert any(
        item["call_id"] == "evaluate_point"
        and item["action"] == "drop_unknown_capability_arg"
        for item in result.elaboration["deterministic_repairs"]
    )

    mismatched_payload = json.loads(json.dumps(payload))
    mismatched_payload["scopes"][0]["calls"][-1]["args"]["parameter"] = {
        "ref": "a",
        "kind": "symbol",
    }
    mismatched_plan, mismatched_report = _validate(
        mismatched_payload,
        inputs,
    )
    assert mismatched_report.ok and mismatched_plan is not None
    mismatched = FunctionalPlanReconciler().reconcile(
        mismatched_plan,
        planner_state_context=_context(inputs),
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=_registry(),
        question_goals=inputs.question_goals,
    )
    assert mismatched.ok, [item.to_payload() for item in mismatched.issues]
    mismatched_effective = next(
        call
        for call in mismatched.plan.calls
        if call.call_id == "evaluate_point"
    )
    assert "parameter" not in mismatched_effective.args
    assert any(
        item["call_id"] == "evaluate_point"
        and item["action"] == "drop_unknown_capability_arg"
        for item in mismatched.elaboration["deterministic_repairs"]
    )


def test_reconciler_drops_unknown_arg_but_still_requires_declared_args() -> None:
    inputs = replace(_base_inputs(), question_goals=[])
    payload = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "ii_2",
                "label": "ii_2",
                "calls": [
                    {
                        "call_id": "missing_midpoint_definition",
                        "capability_id": "midpoint_point",
                        "args": {
                            "invented": {"ref": "A", "kind": "point"},
                        },
                        "return_bindings": {},
                        "strategy": "try to construct a midpoint",
                        "reason": "exercise contract pruning",
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

    assert any(
        item.call_id == "missing_midpoint_definition"
        and item.code == "functional.arg_missing"
        and item.details.get("arg") == "midpoint_definition"
        for item in result.issues
    )
    assert not any(item.code == "functional.arg_unknown" for item in result.issues)
    assert any(
        item["call_id"] == "missing_midpoint_definition"
        and item["action"] == "drop_unknown_capability_arg"
        for item in result.elaboration["deterministic_repairs"]
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


def test_answer_binding_rejects_another_preserved_input_identity() -> None:
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

    assert not result.ok
    issue = next(
        item
        for item in result.issues
        if item.code
        == "functional.return_answer_object_identity_mismatch"
    )
    assert issue.details["answer_handle"] == "answer:i.axis_point"
    assert issue.details["actual_object_ref"] == "point:problem:C"
    assert issue.details["expected_object_ref"] == "point:problem:D"


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
        "fact:i:solve_parabola_parabola",
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


def test_legacy_functional_retry_prefix_is_provisional_without_checkpoint() -> None:
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
    assert merged["scopes"][0]["calls"][0]["strategy"] == "changed"

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
                    "committed_candidate_calls": [
                        {"scope_id": "i", "call": stable_call.to_payload()}
                    ],
                    "call_memory": [
                        {
                            "call_id": "i_derive_D",
                            "capability_id": stable_call.capability_id,
                            "scope_id": "i",
                            "execution_status": "runtime_verified",
                            "commit_status": "goal_committed",
                            "repair_required": False,
                            "source_attempt": 1,
                            "results": [
                                {
                                    "return": "axis_point",
                                    "type": "Point",
                                    "semantic_ref": "D",
                                    "value": ["1", "4"],
                                    "actual_form": "closed_state",
                                }
                            ],
                            "committed_goals": ["answer:i.D"],
                        }
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
    assert replay.retry_state.preserve_policy == "none"
    assert replay.retry_state.stable_candidate_calls == ()
    repair_cone = strategy_replay_module._functional_dependent_closure(
        {"ii_1_solve_m"},
        replay.functional_reconciliation.dependency_graph,
    )
    assert repair_cone <= set(replay.retry_state.repair_call_ids)
    assert replay.retry_state.issues[0].code == (
        "duplicate_point_coordinate_fact"
    )
    assert replay.retry_state.issues[0].step_id == "ii_1_solve_m"
    committed_memory = next(
        item
        for item in replay.retry_state.call_memory
        if item["call_id"] == "i_derive_D"
    )
    assert committed_memory["execution_status"] == "validated"
    assert committed_memory["commit_status"] == "provisional"
    assert committed_memory["repair_required"] is True
    assert committed_memory.get("results", []) == []
    assert "i_derive_D" in replay.retry_state.validated_call_ids
    assert "StepIntent" not in replay.retry_state.repair_instruction
    assert replay.planner_state_context is not None
    assert (
        replay.planner_state_context.state.retry_memory.candidate_format
        == "functional_plan"
    )
    assert (
        replay.planner_state_context.state.retry_memory
        .stable_candidate_calls
        == ()
    )


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
    original_replay_draft = PlannerRetryReplayService.replay_draft
    validation_calls = 0
    replay_sidecar_steps: list[tuple[set[str], set[str], set[str]]] = []

    def reject_full_projection_once(
        validator: StepIntentValidator,
        *args: object,
        **kwargs: object,
    ):
        nonlocal validation_calls
        validation_calls += 1
        if validation_calls == 1:
            return None, projection_validation
        candidate_payload = json.loads(str(args[0]))
        candidate_step_ids = {
            step["step_id"]
            for scope in candidate_payload["scopes"]
            for step in scope["steps"]
        }
        assert {
            item.step_id
            for item in kwargs.get("projected_state_writes", ())
        } <= candidate_step_ids
        return original_validate(validator, *args, **kwargs)

    def capture_replay_draft(
        service: PlannerRetryReplayService,
        draft: StepIntentDraft,
        *args: object,
        **kwargs: object,
    ) -> PlannerRetryReplayResult:
        draft_step_ids = {step.step_id for step in draft.steps}
        write_step_ids = {
            item.step_id
            for item in kwargs.get("projected_state_writes", ())
        }
        dependency_step_ids = {
            item.step_id
            for item in kwargs.get("projected_state_dependencies", ())
        }
        replay_sidecar_steps.append(
            (draft_step_ids, write_step_ids, dependency_step_ids)
        )
        return original_replay_draft(service, draft, *args, **kwargs)

    monkeypatch.setattr(
        strategy_replay_module.StepIntentValidator,
        "validate_json_with_report",
        reject_full_projection_once,
    )
    monkeypatch.setattr(
        PlannerRetryReplayService,
        "replay_draft",
        capture_replay_draft,
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
    assert replay.retry_state.preserve_policy == "none"
    stable_ids = {
        item["call"]["call_id"]
        for item in replay.retry_state.stable_candidate_calls
    }
    assert not stable_ids
    assert blocker_id not in stable_ids
    runtime_verified_ids = {
        item["call_id"]
        for item in replay.retry_state.runtime_verified_calls
    }
    assert "i_derive_D" in runtime_verified_ids
    assert replay.functional_reconciliation is not None
    dependents = {
        call_id
        for call_id, dependencies in (
            replay.functional_reconciliation.dependency_graph.items()
        )
        if blocker_id in dependencies
    }
    assert dependents
    assert dependents.isdisjoint(runtime_verified_ids)
    repair_cone = strategy_replay_module._functional_dependent_closure(
        {blocker_id},
        replay.functional_reconciliation.dependency_graph,
    )
    assert set(replay.retry_state.repair_call_ids) == repair_cone
    issue = next(
        item
        for item in replay.retry_state.issues
        if item.code == "functional.state_transition_dependency_missing"
    )
    assert issue.details is not None
    assert dependents <= set(issue.details["blocked_call_ids"])
    verification = replay.retry_state.replay_reports[
        "functional_reconciliation"
    ]["independent_graph_verification"]
    assert "i_derive_D" in verification["verified_call_ids"]
    assert replay_sidecar_steps
    assert all(
        write_step_ids <= draft_step_ids
        and dependency_step_ids <= draft_step_ids
        for (
            draft_step_ids,
            write_step_ids,
            dependency_step_ids,
        ) in replay_sidecar_steps
    )


def test_projection_probe_propagates_typed_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    plan, functional_validation = _validate(payload, inputs)
    assert functional_validation.ok and plan is not None
    projection_validation = StepIntentValidationReport(
        ok=False,
        errors=(
            "duplicate_state_writer: previous_step=i_derive_D, "
            "current_step=ii_reduce_path",
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

    def reject_probe(
        *_args: object,
        **_kwargs: object,
    ) -> PlannerRetryReplayResult:
        raise StrategyDraftValidationError(
            "planner_configuration_error: "
            "planner.state_finalization_drift: probe synthetic"
        )

    monkeypatch.setattr(
        strategy_replay_module.StepIntentValidator,
        "validate_json_with_report",
        reject_full_projection_once,
    )
    monkeypatch.setattr(
        PlannerRetryReplayService,
        "replay_draft",
        reject_probe,
    )

    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.state_finalization_drift",
    ):
        PlannerRetryReplayService().replay_functional_plan(
            plan,
            inputs=inputs,
            handle_registry=_registry(),
            context=ContextBuilder().build(_problem()),
            attempt=1,
            problem_payload=_problem_payload(),
            validation_report=functional_validation,
        )


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
def test_legacy_functional_retry_does_not_restore_without_checkpoint() -> None:
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

    assert merged["scopes"][0]["calls"] == []


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


def test_functional_replay_accepts_commuted_line_intersection_groups() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_2_derive_G"
    )
    line1 = (call["args"]["line1_p1"], call["args"]["line1_p2"])
    line2 = (call["args"]["line2_p1"], call["args"]["line2_p2"])
    call["args"]["line1_p1"], call["args"]["line1_p2"] = line2
    call["args"]["line2_p1"], call["args"]["line2_p2"] = line1
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
    assert replay.diagnostic is not None
    assert replay.diagnostic.ok
    assert replay.goal_verification_issues == ()
    assert replay.goal_verification_report is not None
    assert all(
        goal.status == "passed"
        for goal in replay.goal_verification_report.goals
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
        "return": "straightened_endpoint_1",
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


def test_evidence_preflight_preserves_completed_goal_subgraphs() -> None:
    inputs = _base_inputs()
    payload = json.loads(NANKAI_FUNCTIONAL_PLAN.read_text(encoding="utf-8"))
    call = next(
        call
        for scope in payload["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_2_derive_G"
    )
    call["args"]["line1_p2"] = {
        "from_call": "i_derive_D",
        "return": "axis_point",
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
    assert replay.diagnostic is not None
    assert replay.diagnostic.runtime_results
    assert replay.retry_state is not None
    issue = next(
        item
        for item in replay.retry_state.issues
        if item.code == "functional.evidence_closure_unproven"
    )
    assert issue.step_id == "ii_2_derive_G"
    assert issue.details is not None
    assert (
        "ii_derive_path_model.straightened_endpoint_2"
        in issue.details["compatible_refs"]
    )
    committed_call_ids = {
        item["call"]["call_id"]
        for item in replay.retry_state.committed_candidate_calls
    }
    assert {"i_derive_parabola", "i_derive_D"} <= committed_call_ids
    assert {
        "ii_1_solve_m",
        "ii_1_specialize_parabola",
        "ii_1_evaluate_minimum",
    } <= committed_call_ids
    assert "ii_2_derive_G" in replay.retry_state.repair_call_ids
    assert "ii_derive_path_model" not in replay.retry_state.repair_call_ids
    assert "ii_derive_path_model" in issue.details["locked_context_call_ids"]
    checkpoint = replay.retry_state.functional_retry_graph_checkpoint
    assert checkpoint is not None
    assert replay.planner_state_context is not None
    assert (
        replay.planner_state_context.state.retry_memory
        .functional_retry_graph_checkpoint
        == checkpoint
    )
    checkpoint_call_ids = {
        item["canonical_call_id"]
        for item in checkpoint["committed_calls"]
    }
    assert committed_call_ids == checkpoint_call_ids
    assert checkpoint["verified_versions"]
    assert all(
        item["version_id"]["ordinal"] >= 1
        and item["canonical_producer_call_id"] in {
            call.call_id for call in replay.functional_reconciliation.calls
        }
        for item in checkpoint["verified_versions"]
    )
    committed_versions = {
        json.dumps(item["version_id"], sort_keys=True)
        for item in checkpoint["verified_versions"]
        if item["status"] == "goal_committed"
    }
    persisted_versions = {
        json.dumps(write.version_id.to_payload(), sort_keys=True): write
        for slot in replay.planner_state_context.state.state_slots
        for write in slot.write_history
        if write.version_id is not None
    }
    assert committed_versions <= set(persisted_versions)
    assert all(
        persisted_versions[version].canonical_producer_call_id
        and persisted_versions[version].state_effect_key is not None
        for version in committed_versions
    )
    for record in checkpoint["verified_versions"]:
        if (
            record["status"] != "goal_committed"
            or record["previous_version_id"] is None
        ):
            continue
        persisted = persisted_versions[
            json.dumps(record["version_id"], sort_keys=True)
        ]
        assert persisted.previous_version_id is not None
        assert (
            persisted.previous_version_id.to_payload()
            == record["previous_version_id"]
        )

    candidate = json.loads(
        json.dumps(replay.functional_reconciliation.plan.to_payload())
    )
    for scope in candidate["scopes"]:
        scope["calls"] = [
            call
            for call in scope["calls"]
            if call["call_id"] != "i_derive_D"
        ]
    restored = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(candidate),
            previous_attempts=[
                {
                    "functional_retry_graph_checkpoint": checkpoint,
                    "context_derived_retry_state": (
                        replay.retry_state.to_payload()
                    ),
                }
            ],
        )
    )
    assert any(
        call["call_id"] == "i_derive_D"
        for scope in restored["scopes"]
        for call in scope["calls"]
    )
    modified_committed = json.loads(
        json.dumps(replay.functional_reconciliation.plan.to_payload())
    )
    modified_call = next(
        call
        for scope in modified_committed["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "i_derive_D"
    )
    modified_call["return_expectations"] = {
        "axis_point": "open_state",
    }
    restored_modified = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(modified_committed),
            previous_attempts=[
                {
                    "functional_retry_graph_checkpoint": checkpoint,
                    "context_derived_retry_state": (
                        replay.retry_state.to_payload()
                    ),
                }
            ],
        )
    )
    restored_call = next(
        call
        for scope in restored_modified["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "i_derive_D"
    )
    checkpoint_call = next(
        item["call_payload"]
        for item in checkpoint["committed_calls"]
        if item["canonical_call_id"] == "i_derive_D"
    )
    assert restored_call == checkpoint_call
    attempt_payload = repair_attempt_payload_from_replay(replay)
    assert attempt_payload is not None
    retry_inputs = replace(
        inputs,
        previous_errors=[attempt_payload],
    )
    prompt_payload = StrategyPayloadBuilder().build(
        retry_inputs,
        problem_payload=_problem_payload(),
        planner_state_context=_context(retry_inputs),
        output_format="functional_plan",
    )
    prompt_retry_state = prompt_payload["previous_attempt_state"][
        "latest_retry_state"
    ]
    assert set(prompt_retry_state["locked_call_ids"]) == committed_call_ids
    assert "functional_retry_graph_checkpoint" not in prompt_retry_state
    assert "state_version_id" not in json.dumps(
        prompt_retry_state,
        ensure_ascii=False,
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        _context(retry_inputs),
        handle_registry=_registry(),
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        retry_inputs.family_spec,
        retry_inputs.method_specs,
    ).contextualized(semantic_index)
    projection_retry = strategy_replay_module._functional_projection_retry_state(
        attempt=2,
        reconciliation=replay.functional_reconciliation,
        validation_report=StepIntentValidationReport(
            ok=False,
            errors=("synthetic projection failure",),
        ),
        previous_attempts=[attempt_payload],
        functional_catalog=catalog,
    )
    projection_locked_ids = {
        item["call"]["call_id"]
        for item in projection_retry.committed_candidate_calls
    }
    assert projection_locked_ids == committed_call_ids
    assert (
        projection_retry.functional_retry_graph_checkpoint
        == checkpoint
    )
    projection_prompt_state = (
        strategy_payload_module._functional_previous_attempt_state(
            [
                {
                    "context_derived_retry_state": (
                        projection_retry.to_payload()
                    )
                }
            ]
        )["latest_retry_state"]
    )
    assert set(projection_prompt_state["locked_call_ids"]) == (
        projection_locked_ids
    )
    retried = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps(candidate),
        inputs=retry_inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
    )
    assert retried.retry_state is not None
    assert retried.retry_state.functional_retry_graph_checkpoint is not None
    renamed_candidate = json.loads(json.dumps(candidate))
    renamed_call = json.loads(
        json.dumps(
            next(
                item["call_payload"]
                for item in checkpoint["committed_calls"]
                if item["canonical_call_id"] == "i_derive_D"
            )
        )
    )
    renamed_call["call_id"] = "renamed_i_derive_D"
    next(
        scope
        for scope in renamed_candidate["scopes"]
        if scope["scope_id"] == "i"
    )["calls"].append(renamed_call)
    renamed_retry = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps(renamed_candidate),
        inputs=retry_inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
    )
    assert renamed_retry.functional_reconciliation is not None
    pinned_placement = next(
        item
        for item in renamed_retry.functional_reconciliation.call_placements
        if item.canonical_call_id == "i_derive_D"
    )
    assert "renamed_i_derive_D" in pinned_placement.alias_call_ids
    assert "renamed_i_derive_D" not in {
        call.call_id
        for call in renamed_retry.functional_reconciliation.plan.calls
    }
    successful_candidate = json.loads(json.dumps(candidate))
    successful_call = next(
        call
        for scope in successful_candidate["scopes"]
        for call in scope["calls"]
        if call["call_id"] == "ii_2_derive_G"
    )
    successful_call["args"]["line1_p2"] = {
        "from_call": "ii_derive_path_model",
        "return": "straightened_endpoint_2",
    }
    successful_retry = PlannerRetryReplayService().replay_functional_raw_json(
        json.dumps(successful_candidate),
        inputs=retry_inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
    )
    assert successful_retry.output is not None
    assert successful_retry.retry_state is None
    assert successful_retry.planner_state_context is not None
    successful_versions = [
        write
        for slot in successful_retry.planner_state_context.state.state_slots
        for write in slot.write_history
        if write.canonical_producer_call_id == "i_derive_D"
        and write.version_id is not None
    ]
    assert successful_versions
    incomplete_versions = [
        write.to_payload()
        for write in successful_versions
        if write.state_effect_key is None
        or write.valid_scope_id is None
    ]
    assert not incomplete_versions, incomplete_versions

    drifted_attempt = json.loads(json.dumps(attempt_payload))
    drifted_checkpoint = drifted_attempt[
        "functional_retry_graph_checkpoint"
    ]
    committed_version = next(
        item
        for item in drifted_checkpoint["verified_versions"]
        if item["status"] == "goal_committed"
    )
    committed_version["version_id"]["ordinal"] += 100
    drifted_attempt["context_derived_retry_state"][
        "functional_retry_graph_checkpoint"
    ] = drifted_checkpoint
    drifted_inputs = replace(
        inputs,
        previous_errors=[drifted_attempt],
    )
    with pytest.raises(
        StrategyDraftValidationError,
        match="planner.retry_version_checkpoint_invalid",
    ):
        PlannerRetryReplayService().replay_functional_raw_json(
            json.dumps(candidate),
            inputs=drifted_inputs,
            handle_registry=_registry(),
            context=ContextBuilder().build(_problem()),
            attempt=2,
            problem_payload=_problem_payload(),
        )


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
    verified_call_ids = {
        call.call_id for call in reconciliation.plan.calls
    } - {blocker_id, *direct_dependents}

    projected = strategy_replay_module._functional_runtime_retry_state(
        retry_state,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids=verified_call_ids,
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
    assert projected.preserve_policy == "none"
    runtime_verified_ids = {
        item["call_id"] for item in projected.runtime_verified_calls
    }
    assert blocker_id not in runtime_verified_ids
    assert direct_dependents.isdisjoint(runtime_verified_ids)
    assert runtime_verified_ids


def test_functional_retry_does_not_commit_without_typed_checkpoint() -> None:
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
    producer_call_id = "i_derive_D"
    producer_step_id = next(
        item.step_ids[0]
        for item in reconciliation.projection_map
        if item.call_id == producer_call_id
    )
    blocker_id = "ii_reduce_path"
    issue = PlannerRetryIssue(
        layer="trial_execution",
        code="synthetic_runtime_blocker",
        step_id=blocker_id,
        scope_id="ii",
        message="the second question remains incomplete",
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
    unexecuted = {blocker_id}
    changed = True
    while changed:
        changed = False
        for call_id, dependencies in reconciliation.dependency_graph.items():
            if call_id in unexecuted or not unexecuted.intersection(dependencies):
                continue
            unexecuted.add(call_id)
            changed = True
    projected = strategy_replay_module._functional_runtime_retry_state(
        retry_state,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={
            call.call_id for call in reconciliation.plan.calls
        } - unexecuted,
        goal_verification_report=AnswerGoalVerificationReport(
            (
                AnswerGoalVerificationItem(
                    "answer:i.D",
                    "passed",
                    producer_step_id=producer_step_id,
                ),
            )
        ),
        attempt=1,
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )

    assert projected is not None
    committed_ids = {
        item["call"]["call_id"]
        for item in projected.committed_candidate_calls
    }
    assert committed_ids == set()
    assert projected.functional_retry_graph_checkpoint is None
    assert projected.stable_candidate_calls == (
        projected.committed_candidate_calls
    )
    assert projected.preserve_policy == "none"
    runtime_verified_ids = {
        item["call_id"] for item in projected.runtime_verified_calls
    }
    assert blocker_id not in runtime_verified_ids
    assert runtime_verified_ids.isdisjoint(committed_ids)
    assert all(
        item["commit_status"] == "goal_committed"
        and item["execution_status"] == "runtime_verified"
        and item["repair_required"] is False
        for item in projected.call_memory
        if item["call_id"] in committed_ids
    )

    answer_check_retry = replace(
        retry_state,
        issues=(
            PlannerRetryIssue(
                layer="answer_check",
                code="answer_mismatch",
                step_id=producer_call_id,
                scope_id="i",
                message="external answer verification rejected this goal",
            ),
        ),
    )
    revoked = strategy_replay_module._functional_runtime_retry_state(
        answer_check_retry,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={
            call.call_id for call in reconciliation.plan.calls
        },
        goal_verification_report=AnswerGoalVerificationReport(
            (
                AnswerGoalVerificationItem(
                    "answer:i.D",
                    "passed",
                    producer_step_id=producer_step_id,
                ),
            )
        ),
        attempt=1,
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )
    assert revoked is not None
    assert revoked.committed_candidate_calls == ()
    assert revoked.preserve_policy == "none"
    revoked_result = next(
        item
        for item in revoked.runtime_verified_calls
        if item["call_id"] == producer_call_id
    )
    assert revoked_result["execution_status"] == "runtime_verified"
    assert revoked_result["commit_status"] == "provisional"
    assert revoked_result["repair_required"] is True


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
    upstream_call = next(
        item
        for item in reconciliation.calls
        if item.call_id == upstream_root
    )
    upstream_return = upstream_call.returns[0]
    produced_handle = (
        upstream_return.state_handle or upstream_return.handle
    )

    projected = strategy_replay_module._functional_runtime_retry_state(
        retry_state,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={call.call_id for call in reconciliation.plan.calls},
        verified_runtime_results=(
            StepIntentRuntimeResult(
                step_id=upstream_root,
                scope_id="ii",
                capability_id=upstream_call.capability_id,
                produced_handle=produced_handle,
                output_key=upstream_return.return_name,
                runtime_type=upstream_return.runtime_type,
                value_omitted_reason="structured_state_projected_from_lineage",
            ),
        ),
        verified_state_write_provenance=(
            StateWriteProvenance(
                step_id=upstream_root,
                scope_id="ii",
                capability_id=upstream_call.capability_id,
                produced_handle=produced_handle,
                output_key=upstream_return.return_name,
                runtime_type=upstream_return.runtime_type,
                identity_policy=upstream_return.identity_policy,
                identity_role=upstream_return.return_name,
                object_ref=upstream_return.object_ref,
                state_slot_id=upstream_return.state_slot_id,
            ),
        ),
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )

    assert projected is not None
    stable_ids = {
        item["call"]["call_id"] for item in projected.stable_candidate_calls
    }
    assert upstream_root not in stable_ids
    assert failing_consumer not in stable_ids
    assert upstream_root in projected.repair_call_ids
    assert failing_consumer in projected.repair_call_ids
    dependent_closure = strategy_replay_module._functional_dependent_closure(
        {upstream_root, failing_consumer},
        reconciliation.dependency_graph,
    )
    assert set(projected.repair_call_ids) == dependent_closure
    upstream_memory = next(
        item
        for item in projected.runtime_verified_calls
        if item["call_id"] == upstream_root
    )
    assert upstream_memory["execution_status"] == "runtime_verified"
    assert upstream_memory["commit_status"] == "provisional"
    assert upstream_memory["repair_required"] is True
    consumer_issue = next(
        item for item in projected.issues if item.step_id == failing_consumer
    )
    assert consumer_issue.details is not None
    assert consumer_issue.details["actual_result_refs"] == [
        f"{upstream_root}.{upstream_return.return_name}"
    ]

    input_failure = replace(
        retry_state,
        issues=(replace(issue, details=None),),
        repair_call_ids=(failing_consumer,),
    )
    input_projected = strategy_replay_module._functional_runtime_retry_state(
        input_failure,
        plan=reconciliation.plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={call.call_id for call in reconciliation.plan.calls},
        verified_runtime_results=(
            StepIntentRuntimeResult(
                step_id=upstream_root,
                scope_id="ii",
                capability_id=upstream_call.capability_id,
                produced_handle=produced_handle,
                output_key=upstream_return.return_name,
                runtime_type=upstream_return.runtime_type,
                value_omitted_reason="structured_state_projected_from_lineage",
            ),
        ),
        verified_state_write_provenance=(
            StateWriteProvenance(
                step_id=upstream_root,
                scope_id="ii",
                capability_id=upstream_call.capability_id,
                produced_handle=produced_handle,
                output_key=upstream_return.return_name,
                runtime_type=upstream_return.runtime_type,
                identity_policy=upstream_return.identity_policy,
                identity_role=upstream_return.return_name,
                object_ref=upstream_return.object_ref,
                state_slot_id=upstream_return.state_slot_id,
            ),
        ),
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )
    assert input_projected is not None
    nearest_issue = next(
        item
        for item in input_projected.issues
        if item.step_id == failing_consumer
    )
    assert nearest_issue.details is not None
    assert nearest_issue.details["actual_result_refs"] == [
        f"{upstream_root}.{upstream_return.return_name}"
    ]


def test_transition_trial_issue_includes_provisional_previous_writer() -> None:
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
    previous_writer = "i_derive_D"
    current_writer = "ii_1_solve_m"
    issue = PlannerRetryIssue(
        layer="trial_execution",
        code="function.transition_dependency_missing",
        step_id=current_writer,
        scope_id="ii_1",
        message=(
            "function.transition_dependency_missing: "
            f"step={current_writer}, object_ref=point:problem:D, "
            f"previous_step={previous_writer}"
        ),
    )
    semantic_index = FunctionalSemanticIndex.from_context(
        planner_context,
        handle_registry=_registry(),
    )
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    ).contextualized(semantic_index)

    enriched = strategy_replay_module._enrich_functional_retry_issues(
        (issue,),
        plan=plan,
        reconciliation=reconciliation,
        catalog=catalog,
        semantic_index=semantic_index,
    )

    assert len(enriched) == 1
    assert enriched[0].details is not None
    assert enriched[0].details["previous_writer_call_id"] == previous_writer
    assert enriched[0].details["current_writer_call_id"] == current_writer
    assert enriched[0].details["repair_call_ids"] == [
        previous_writer,
        current_writer,
    ]


def test_legacy_functional_retry_does_not_rewrite_renamed_call() -> None:
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
        "renamed_axis_point",
        "consume_axis_point",
    ]
    assert calls[1]["args"]["point"]["from_call"] == "renamed_axis_point"


def test_legacy_functional_retry_drops_stale_untyped_graph() -> None:
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
    assert "construct_G_i2" not in calls


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


def test_functional_wire_preparation_drops_matching_call_scope_only() -> None:
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    call["scope_id"] = "i"
    conflicting = json.loads(json.dumps(call))
    conflicting["call_id"] = "conflicting_scope"
    conflicting["scope_id"] = "ii"
    payload["scopes"][0]["calls"].append(conflicting)

    prepared = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(payload),
            previous_attempts=[],
        )
    )

    assert "scope_id" not in prepared["scopes"][0]["calls"][0]
    assert prepared["scopes"][0]["calls"][1]["scope_id"] == "ii"


def test_functional_wire_validation_drops_matching_scope_call_id_only() -> None:
    payload = _axis_plan_payload()
    payload["scopes"][0]["call_id"] = "i"

    plan, report = _validate(payload, _inputs_for_goal(0))

    assert report.ok and plan is not None
    assert "call_id" not in plan.to_payload()["scopes"][0]
    assert report.deterministic_repairs == (
        {
            "scope_id": "i",
            "action": "drop_redundant_scope_call_id",
            "from": "i",
            "to": "omitted",
        },
    )

    conflicting = _axis_plan_payload()
    conflicting["scopes"][0]["call_id"] = "ii"

    rejected, rejected_report = _validate(
        conflicting,
        _inputs_for_goal(0),
    )

    assert rejected is None
    assert not rejected_report.ok
    assert rejected_report.deterministic_repairs == ()
    assert {
        issue.code for issue in rejected_report.issues
    } == {"functional.fields_extra"}


def test_functional_wire_preparation_groups_unambiguous_flat_scoped_calls() -> None:
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    flattened = {
        "format": "functional_plan/v1",
        "scopes": [
            {
                "scope_id": "i",
                **call,
            }
        ],
    }

    prepared = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(flattened),
            previous_attempts=[],
        )
    )

    assert prepared == payload
    plan, report = _validate(prepared, _inputs_for_goal(0))
    assert report.ok and plan is not None


def test_functional_wire_preparation_leaves_mixed_scope_shape_for_validation() -> None:
    payload = _axis_plan_payload()
    call = payload["scopes"][0]["calls"][0]
    mixed = {
        "format": "functional_plan/v1",
        "scopes": [
            payload["scopes"][0],
            {
                "scope_id": "i",
                **call,
            },
        ],
    }

    prepared = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(mixed),
            previous_attempts=[],
        )
    )

    assert prepared == mixed
    plan, report = _validate(prepared, _inputs_for_goal(0))
    assert plan is None
    assert not report.ok


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


def test_functional_wire_failure_inherits_previous_verified_graph() -> None:
    inputs = _inputs_for_goal(0)
    baseline = _axis_plan_payload(strategy="verified")
    stable_call = baseline["scopes"][0]["calls"][0]
    inputs = replace(
        inputs,
        previous_errors=[
            {
                "context_derived_retry_state": {
                    "candidate_format": "functional_plan",
                    "preserve_policy": "preserve_graph",
                    "baseline_candidate": baseline,
                    "stable_candidate_calls": [
                        {"scope_id": "i", "call": stable_call}
                    ],
                    "committed_candidate_calls": [
                        {"scope_id": "i", "call": stable_call}
                    ],
                    "runtime_verified_calls": [
                        {
                            "call_id": "derive_curve",
                            "capability_id": "quadratic_from_constraints",
                            "scope_id": "i",
                            "execution_status": "runtime_verified",
                            "commit_status": "provisional",
                            "repair_required": False,
                            "source_attempt": 1,
                        }
                    ],
                    "validated_call_ids": ["derive_candidate"],
                    "call_memory": [
                        {
                            "call_id": "derive_axis_point",
                            "capability_id": stable_call["capability_id"],
                            "scope_id": "i",
                            "execution_status": "runtime_verified",
                            "commit_status": "goal_committed",
                            "repair_required": False,
                            "source_attempt": 1,
                            "committed_goals": ["answer:i.D"],
                        }
                    ],
                }
            }
        ],
    )

    replay = PlannerRetryReplayService().replay_functional_raw_json(
        '{"format":"functional_plan/v1","scopes":[',
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
    )

    assert replay.output is None
    assert replay.retry_state is not None
    assert replay.retry_state.candidate_format == "functional_plan"
    assert replay.retry_state.baseline_candidate == baseline
    assert replay.retry_state.preserve_policy == "none"
    assert replay.retry_state.stable_candidate_calls == ()
    assert replay.retry_state.committed_candidate_calls == ()
    assert replay.retry_state.runtime_verified_calls[0]["call_id"] == (
        "derive_curve"
    )
    assert replay.retry_state.validated_call_ids == ("derive_candidate",)
    assert replay.retry_state.call_memory[0]["commit_status"] == "provisional"
    assert replay.planner_state_context is not None
    memory = replay.planner_state_context.state.retry_memory
    assert memory.baseline_candidate == baseline
    assert memory.stable_candidate_calls == ()
    assert memory.committed_candidate_calls == ()
    assert memory.runtime_verified_calls[0]["call_id"] == "derive_curve"
    assert memory.validated_call_ids == ("derive_candidate",)
    assert memory.call_memory[0]["commit_status"] == "provisional"


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
    with pytest.raises(PlannerExecutionError) as raised:
        planner.plan(inputs)
    assert raised.value.primary.stage == "functional_validation"
    assert raised.value.primary.code == "functional.scopes"
    assert raised.value.candidate_format == "functional_plan"

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


def test_functional_configuration_failure_crosses_typed_planner_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def complete(self, payload: dict) -> str:
            return '{"format":"functional_plan/v1","scopes":[]}'

    def fail_replay(*args: Any, **kwargs: Any) -> PlannerRetryReplayResult:
        raise StrategyDraftValidationError(
            "planner_configuration_error: synthetic Macro projection drift"
        )

    monkeypatch.setattr(
        PlannerRetryReplayService,
        "replay_functional_raw_json",
        fail_replay,
    )
    planner = StrategyPlanner(
        ContextBuilder().build(_problem()),
        mode="deepseek",
        client=Client(),
        payload_builder=StrategyPayloadBuilder(
            functional_few_shot_mode="strict_test"
        ),
        output_format="functional_plan",
    )

    with pytest.raises(PlannerExecutionError) as raised:
        planner.plan(_inputs_for_goal(0))

    assert raised.value.primary.stage == "planner"
    assert raised.value.primary.code == "planner_configuration_error"
    assert raised.value.primary.retryable is False
    assert raised.value.candidate_format == "functional_plan"


def test_functional_projection_failure_crosses_typed_planner_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def complete(self, payload: dict) -> str:
            return '{"format":"functional_plan/v1","scopes":[]}'

    def fail_replay(*args: Any, **kwargs: Any) -> PlannerRetryReplayResult:
        raise StrategyDraftValidationError(
            "state_transition_not_dependency_refinement: "
            "slot=function:part:curve.expression@part"
        )

    monkeypatch.setattr(
        PlannerRetryReplayService,
        "replay_functional_raw_json",
        fail_replay,
    )
    planner = StrategyPlanner(
        ContextBuilder().build(_problem()),
        mode="deepseek",
        client=Client(),
        payload_builder=StrategyPayloadBuilder(
            functional_few_shot_mode="strict_test"
        ),
        output_format="functional_plan",
    )

    with pytest.raises(PlannerExecutionError) as raised:
        planner.plan(_inputs_for_goal(0))

    assert raised.value.primary.stage == "normalization"
    assert (
        raised.value.primary.code
        == "state_transition_not_dependency_refinement"
    )
    assert raised.value.primary.retryable is True
    assert raised.value.root_issues == (
        {
            "layer": "normalization",
            "code": "state_transition_not_dependency_refinement",
            "message": (
                "state_transition_not_dependency_refinement: "
                "slot=function:part:curve.expression@part"
            ),
            "preserve_policy": "none",
        },
    )
    assert raised.value.candidate_format == "functional_plan"


def test_functional_prompt_retry_state_never_exposes_step_intent_baseline() -> None:
    inputs = _inputs_for_goal(0)
    stable_call = _axis_plan_payload()["scopes"][0]["calls"][0]
    retry_state = {
        "candidate_format": "functional_plan",
        "baseline_candidate": _axis_plan_payload(),
        "baseline_draft": {"scopes": [{"steps": []}]},
        "stable_candidate_prefix": [],
        "stable_candidate_calls": [
            {"scope_id": "i", "call": stable_call}
        ],
        "committed_candidate_calls": [
            {"scope_id": "i", "call": stable_call}
        ],
        "runtime_verified_calls": [
            {
                "call_id": "derive_curve",
                "capability_id": "quadratic_from_constraints",
                "scope_id": "ii",
                "execution_status": "runtime_verified",
                "commit_status": "provisional",
                "repair_required": True,
                "source_attempt": 1,
                "results": [
                    {
                        "return": "parabola",
                        "type": "Parabola",
                        "semantic_ref": "parabola",
                        "actual_form": "open_state",
                        "free_parameters": ["c"],
                        "value": "-x**2 + (-c - 2)*x + c",
                    }
                ],
            }
        ],
        "call_memory": [
            {
                "call_id": "derive_axis_point",
                "execution_status": "runtime_verified",
                "commit_status": "goal_committed",
                "repair_required": False,
                "results": [
                    {
                        "return": "axis_point",
                        "type": "Point",
                        "semantic_ref": "axis_point",
                        "actual_form": "closed_state",
                        "free_parameters": [],
                        "value": ["1", "0"],
                    }
                ],
            }
        ],
        "validated_call_ids": ["derive_candidates"],
        "stable_prefix": [{"step_id": "legacy"}],
        "preserve_policy": "preserve_graph",
        "issues": [
            {
                "layer": "goal_verification",
                "code": "functional.free_basis_mismatch",
                "step_id": "derive_curve",
                "message": "the provisional curve preserves the wrong symbol",
                "details": {
                    "actual_result_refs": ["derive_curve.parabola"],
                    "expected_free_parameter": "b",
                    "context_call_ids": ["derive_axis_point"],
                },
            }
        ],
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
    assert "stable_candidate_calls" not in latest
    assert latest["locked_call_ids"] == []
    assert latest["locked_context_call_ids"] == []
    assert latest["locked_context_results"] == []
    assert latest["runtime_verified"][0]["call_id"] == "derive_curve"
    assert latest["runtime_verified"][0]["repair_required"] is True
    assert latest["runtime_verified"][0]["results"][0] == {
        "return": "parabola",
        "type": "Parabola",
        "ref": "parabola",
        "value": "-x**2 + (-c - 2)*x + c",
        "form": "open_state",
        "free": ["c"],
    }
    assert latest["runtime_verified"][1]["call_id"] == "derive_axis_point"
    assert latest["runtime_verified"][1]["results"][0]["value"] == ["1", "0"]
    assert "capability_id" not in latest["runtime_verified"][0]
    assert "scope_id" not in latest["runtime_verified"][0]
    assert "source_attempt" not in latest["runtime_verified"][0]
    assert latest["validated_call_ids"] == ["derive_candidates"]
    assert "repair_suffix_start" not in latest
    assert all("step_id" not in item for item in latest["issues"])
    assert latest["issues"][0]["call_id"] == "derive_curve"
    assert latest["issues"][0]["details"]["actual_result_refs"] == [
        "derive_curve.parabola"
    ]
    encoded_latest = json.dumps(latest, ensure_ascii=False)
    assert encoded_latest.count("-x**2 + (-c - 2)*x + c") == 1
    prompt = StrategyPromptRenderer().render(payload)
    assert "stable_candidate_calls" not in prompt.system
    assert "stable_candidate_calls" not in prompt.user
    assert "locked_call_ids" in prompt.system
    assert '"locked_call_ids"' in prompt.user
    assert '"runtime_verified"' in prompt.user
    assert '"free": [' in prompt.user
    assert "可以修改、替换或删除" in prompt.user
    assert "任何不在 `locked_call_ids` 中的调用" in prompt.user
    assert "只修复 `repair_call_ids`" not in prompt.system
    assert "StateSlot" not in json.dumps(latest, ensure_ascii=False)
    assert "runtime path" not in json.dumps(latest, ensure_ascii=False)


def test_repair_issue_references_nearest_locked_runtime_result() -> None:
    memory = FunctionalCallMemory(
        entries=(
            FunctionalCallMemoryEntry(
                call_id="locked_curve",
                capability_id="quadratic_from_constraints",
                scope_id="i",
                execution_status="runtime_verified",
                commit_status="goal_committed",
                result_snapshots=(
                    FunctionalResultSnapshot(
                        return_name="parabola",
                        value_type="Parabola",
                        semantic_ref="curve",
                        value="u*x**2 + (u - 3)*x - 3",
                        actual_form="open_state",
                        free_parameters=("u",),
                    ),
                ),
            ),
        ),
    )
    issue = PlannerRetryIssue(
        layer="goal_verification",
        code="functional.evidence_closure_unproven",
        step_id="answer_call",
    )

    (projected,) = attach_actual_result_refs(
        (issue,),
        memory=memory,
        dependency_graph={
            "answer_call": ("intermediate_call",),
            "intermediate_call": ("locked_curve",),
            "locked_curve": (),
        },
    )

    assert projected.details == {
        "locked_result_refs": ["locked_curve.parabola"],
        "locked_context_call_ids": ["locked_curve"],
    }


def test_scope_invisible_issue_does_not_offer_locked_result_as_usable() -> None:
    memory = FunctionalCallMemory(
        entries=(
            FunctionalCallMemoryEntry(
                call_id="locked_local_point",
                capability_id="quadratic_vertex_point",
                scope_id="i_1",
                execution_status="runtime_verified",
                commit_status="goal_committed",
                result_snapshots=(
                    FunctionalResultSnapshot(
                        return_name="point",
                        value_type="Point",
                        semantic_ref="local_point",
                        value=["1", "2"],
                        actual_form="closed_state",
                    ),
                ),
            ),
        ),
    )
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.arg_scope_invisible",
        step_id="sibling_consumer",
        details={
            "source_call_id": "locked_local_point",
            "producer_valid_scope": "i_1",
            "consumer_execution_scope": "i_2",
        },
    )

    (projected,) = attach_actual_result_refs(
        (issue,),
        memory=memory,
        dependency_graph={
            "sibling_consumer": ("locked_local_point",),
            "locked_local_point": (),
        },
    )

    assert projected.details == issue.details


def test_functional_prompt_reads_locked_context_from_result_refs() -> None:
    issues = [
        {
            "details": {
                "locked_result_refs": ["locked_curve.parabola"],
            }
        }
    ]

    call_ids = strategy_payload_module._functional_locked_context_call_ids(
        issues,
        locked_call_ids=["locked_curve", "unrelated_locked_call"],
    )

    assert call_ids == ["locked_curve"]


def test_locked_context_result_budget_prefers_ticket_result_refs() -> None:
    call_ids = [f"locked_{index}" for index in range(1, 6)]
    memory = [
        {
            "call_id": call_id,
            "execution_status": "runtime_verified",
            "commit_status": "goal_committed",
            "results": [
                {
                    "return": "point",
                    "type": "Point",
                    "value": [str(index), "0"],
                }
            ],
        }
        for index, call_id in enumerate(call_ids, start=1)
    ]
    issues = [
        {
            "details": {
                "locked_result_refs": ["locked_5.point"],
                "locked_context_call_ids": call_ids,
            }
        }
    ]

    compact = strategy_payload_module._compact_functional_locked_results(
        memory,
        call_ids=call_ids,
        issues=issues,
    )

    projected_ids = [item["call_id"] for item in compact]
    assert len(projected_ids) == 4
    assert "locked_5" in projected_ids
    assert "locked_4" not in projected_ids


def test_functional_prompt_compacts_large_and_structured_runtime_results() -> None:
    large_value = "x" * 900
    compact = strategy_payload_module._compact_functional_runtime_verified(
        [
            {
                "call_id": "derive_large_expression",
                "execution_status": "runtime_verified",
                "commit_status": "provisional",
                "repair_required": True,
                "results": [
                    {
                        "return": "expression",
                        "type": "Expression",
                        "semantic_ref": "minimum_expression",
                        "value": large_value,
                        "semantic_roles": ["path_minimum_expression"],
                        "object_roles": {"subject": ["moving_point"]},
                    }
                ],
            },
            {
                "call_id": "reduce_path",
                "execution_status": "runtime_verified",
                "commit_status": "provisional",
                "repair_required": False,
                "results": [
                    {
                        "return": "path_transformation",
                        "type": "PathTransformation",
                        "semantic_ref": "reduced_path",
                        "object_roles": {
                            "moving_object": ["G"],
                            "fixed_endpoint_1": ["D"],
                            "fixed_endpoint_2": ["F"],
                        },
                    }
                ],
            },
        ],
        issues=[],
    )

    expression = compact[0]["results"][0]
    assert "value" not in expression
    assert expression["value_omitted_reason"] == (
        "value_too_large_for_prompt"
    )
    assert "roles" not in expression
    assert "identity" not in expression
    transformation = compact[1]["results"][0]
    assert transformation["structure"]["moving_object"] == ["G"]
    assert transformation["structure"]["moving_locus_available"] is False


def test_verified_closed_form_is_memory_not_hard_retry_overlay() -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
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
    open_payload = json.loads(json.dumps(payload))
    open_payload["scopes"][0]["calls"][0]["return_expectations"] = {
        "axis_point": "open_state"
    }
    open_plan, open_validation = _validate(open_payload, inputs)
    assert open_validation.ok and open_plan is not None
    verified_plan = canonicalize_verified_result_forms(
        open_plan,
        (
            FunctionalResultFormEvent(
                call_id="derive_axis_point",
                scope_id="i",
                return_name="axis_point",
                expected_form="open_state",
                actual_form="closed_state",
                status="result_form_closed",
            ),
        ),
    )
    retry_state = PlannerRetryState(
        attempt=1,
        baseline_draft=None,
        issues=(
            PlannerRetryIssue(
                layer="functional_reconciliation",
                code="synthetic.retry",
                message="exercise verified result-form retry projection",
            ),
        ),
        candidate_format="functional_plan",
        baseline_candidate=open_plan.to_payload(),
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
        plan=verified_plan,
        reconciliation=reconciliation,
        diagnostic=None,
        verified_call_ids={"derive_axis_point"},
        functional_catalog=catalog,
        semantic_index=semantic_index,
    )

    assert projected is not None
    baseline = projected.baseline_candidate
    assert baseline is not None
    baseline_call = baseline["scopes"][0]["calls"][0]
    assert baseline_call["return_expectations"] == {
        "axis_point": "closed_state"
    }
    assert projected.stable_candidate_calls == ()
    assert projected.preserve_policy == "none"
    assert [
        item["call_id"] for item in projected.runtime_verified_calls
    ] == ["derive_axis_point"]

    retry_candidate = json.loads(json.dumps(baseline))
    retry_candidate["scopes"][0]["calls"][0]["return_expectations"] = {
        "axis_point": "open_state"
    }
    merged = json.loads(
        prepare_functional_plan_raw_response(
            json.dumps(retry_candidate),
            previous_attempts=[
                {
                    "context_derived_retry_state": projected.to_payload()
                }
            ],
        )
    )
    assert merged["scopes"][0]["calls"][0]["return_expectations"] == {
        "axis_point": "open_state"
    }


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
                                    "role:straightened_endpoint_2@ii_2"
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
    assert "role:straightened_endpoint_2@ii_2" not in serialized
    assert "_axis_param_E" not in serialized
    assert "点 E 的未定坐标参数" in serialized
    assert "ii_1.minimum_value" in serialized
    assert "m_value" in serialized
    assert "straightened_endpoint_2" in serialized


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


def test_partial_reconciliation_defers_checkpoint_version_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _inputs_for_goal(0)
    payload = _axis_plan_payload()
    payload["scopes"][0]["calls"][0]["args"] = {}
    plan, validation = _validate(payload, inputs)
    assert validation.ok and plan is not None
    checkpoint = FunctionalRetryGraphCheckpoint(
        source_context_id="prior-context",
        problem_id=inputs.problem_id,
        family_id=inputs.family_spec.family_id,
        family_spec_hash="family",
        capability_pack_hash="catalog",
    )

    verification_modes: list[bool] = []

    def record_partial_verification(*_args, **kwargs) -> None:
        verification_modes.append(kwargs["verify_reconciled_graph"])

    monkeypatch.setattr(
        strategy_replay_module,
        "verify_restored_checkpoint",
        record_partial_verification,
    )
    replay = PlannerRetryReplayService().replay_functional_plan(
        plan,
        inputs=inputs,
        handle_registry=_registry(),
        context=ContextBuilder().build(_problem()),
        attempt=2,
        problem_payload=_problem_payload(),
        validation_report=validation,
        retry_checkpoint=checkpoint,
    )

    assert replay.retry_state is not None
    assert any(
        issue.code == "functional.arg_missing"
        for issue in replay.retry_state.issues
    )
    assert verification_modes == [False]


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
        if item.step_id == "reduce_path"
    )
    assert issue.repair_target == "functional_call"
    assert issue.code == "functional.path_transformation_state_unavailable"
    assert "Point state" in issue.message
    assert issue.details["state_requirement"].startswith(
        "materialized Point state"
    )
    assert "structured endpoint" in issue.details["repair_guidance"]
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
    straighten_report = next(
        item
        for item in reconciliation.call_reports
        if item.call_id == "straighten_path"
    )
    assert straighten_report.status == "blocked_by_dependency"
    assert straighten_report.blocked_by == ("reduce_path",)


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
    assert reconciliation["state_identity_decisions"]
    assert reconciliation["identity_mismatches"] == []
    assert reconciliation["state_placement_decisions"]
    assert reconciliation["placement_mismatches"] == []
    assert context_payload["state"]["state_identity_decisions"] == (
        reconciliation["state_identity_decisions"]
    )
    assert context_payload["state"]["identity_mismatches"] == []
    assert context_payload["state"]["state_placement_decisions"] == (
        reconciliation["state_placement_decisions"]
    )
    assert context_payload["state"]["placement_mismatches"] == []
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
