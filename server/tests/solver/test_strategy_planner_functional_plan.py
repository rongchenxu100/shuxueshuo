from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import re

import pytest

from shuxueshuo_server.solver.explanation.builder import ExplanationBuilder
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.explanation.presentation import (
    StudentNarrativePlacementProjector,
)
from shuxueshuo_server.solver.runtime import strategy_replay as strategy_replay_module
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
    FunctionalReturnAllocation,
    FunctionalScope,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    _projected_creates,
)
from shuxueshuo_server.solver.runtime.functional_result_forms import (
    verify_functional_result_forms,
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
from shuxueshuo_server.solver.runtime.recipe_compiler import RecipeTrialExecutor
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
from shuxueshuo_server.solver.runtime.models import (
    MethodInvocation,
    StepGoal,
    StepPlan,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    PlannerRetryState,
    ProducedFact,
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
from shuxueshuo_server.solver.state_semantics import derived_role_object_ref


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
    evaluate_point = next(
        item
        for item in capabilities
        if item["capability_id"] == "evaluate_point_at_parameter"
    )
    assert any("不改变对象身份" in item for item in evaluate_point["do_not_use_when"])
    assert any("含参坐标状态" in item.get("desc", "") for item in evaluate_point["args"])
    assert "同一 Point" in evaluate_point["returns"][0]["desc"]


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


def test_fixed_form_return_expectation_is_dropped_deterministically() -> None:
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

    assert result.ok, [item.to_payload() for item in result.issues]
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
    assert effective.return_expectations == {
        "path_minimum_expression": "open_expression"
    }
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

    heping_ermo = load_problem_ir(HEPING_ERMO_FIXTURE)
    heping_inputs = build_strategy_probe_inputs(heping_ermo)
    square_reduction = FunctionalCapabilityCatalog.from_family_spec(
        heping_inputs.family_spec,
        heping_inputs.method_specs,
    ).get("square_path_dimension_reduction")
    assert square_reduction is not None
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
        if item.code == "functional.arg_role_mismatch"
    ]
    assert {item.details["arg"] for item in role_issues if item.details} == {
        "minimum_point_1",
        "minimum_point_2",
    }


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
    assert any(
        item["action"] == "promote_return_scope_for_atomic_call"
        for item in result.elaboration["deterministic_repairs"]
    )


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

    for call_id in (
        "ii_derive_path_model",
        "ii_select_straightening",
    ):
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


def test_elaborator_drops_supplied_auto_arg_and_remains_idempotent() -> None:
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
    assert "parameter" not in first.plan.calls[0].args
    assert any(
        item.action == "drop_supplied_auto_arg"
        and item.from_value == "parameter"
        for item in first.deterministic_repairs
    )

    second = FunctionalPlanElaborator().elaborate(first.plan, catalog=catalog)
    assert second.plan.to_payload() == first.plan.to_payload()
    assert second.deterministic_repairs == ()


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


def test_reconciler_keeps_post_transition_call_and_drops_stale_calculation() -> None:
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
    assert "stale_parameterized_parabola" not in call_ids
    assert "final_numeric_parabola" in call_ids
    final_call = next(
        item for item in result.calls if item.call_id == "final_numeric_parabola"
    )
    assert {
        value.source_call_id
        for value in final_call.resolved_args["curve_points"]
    } == {"evaluate_M", "evaluate_N"}
    assert set(result.dependency_graph["final_numeric_parabola"]) >= {
        "evaluate_M",
        "evaluate_N",
    }
    assert final_call.resolved_args["quadratic"][0].source_call_id is None
    assert final_call.resolved_args["quadratic"][0].handle == (
        "function:problem:parabola"
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
    assert any(
        item["action"] == "drop_superseded_unobserved_object_binding"
        and item["call_id"] == "stale_parameterized_parabola"
        for item in repairs
    )
    assert any(
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
        "from_call": "ii_select_straightening",
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
        "from_call": "ii_select_straightening",
        "return": "straightening_auxiliary_point",
    }
    call["args"]["line1_p2"] = {
        "from_call": "ii_select_straightening",
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
                                "available_parameter_states": [
                                    "fact:ii_1:m_value"
                                ],
                                "identity_message": (
                                    "point:ii:G differs from "
                                    "role:path_minimum_point_2@ii_2"
                                ),
                            },
                        }
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
    assert issue.details == {
        "error_code": "macro.arg_missing",
        "arg": "moving_locus",
        "semantic_role": "moving_locus",
        "accepted_item_types": ["Line"],
        "accepted_condition_kinds": [],
        "compatible_refs": [],
        "producer_candidate": "parameterized_point_locus_line",
    }
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
    solve_call = next(
        item for item in reconciliation.calls if item.call_id == "solve_parameter"
    )
    parameter = solve_call.resolved_args["parameter"]
    assert len(parameter) == 1
    assert parameter[0].object_ref == "symbol:problem:c"


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
