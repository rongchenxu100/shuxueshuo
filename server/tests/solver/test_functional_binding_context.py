from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalArgSourceIdentity,
    FunctionalBindingContextError,
    audit_compiled_functional_arg_consumption,
    audit_functional_arg_binding_projection,
)
from shuxueshuo_server.solver.runtime.functional_plan import (
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    project_functional_arg_bindings,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    _functional_projected_arg_bindings,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)


def _reconcile(case_id: str):
    case = FUNCTIONAL_BATCH_CASES[case_id]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        json.loads(case.functional_fixture_path.read_text(encoding="utf-8")),
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        inputs.family_spec,
        inputs.method_specs,
    )
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
    return result, catalog


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_authored_fixtures_have_complete_binding_context(case_id: str) -> None:
    result, _catalog = _reconcile(case_id)

    assert result.functional_binding_context is not None
    assert result.functional_binding_context.binding_signature
    assert result.functional_binding_mismatches == ()
    assert result.legacy_binding_role_fallback_count == 0
    assert result.functional_binding_decisions
    assert all(
        item["matches"] for item in result.functional_binding_decisions
    )
    assert all(
        binding.semantic_role
        and binding.source.kind
        and (
            binding.runtime_input_targets
            or binding.consumption_mode == "resolver_evidence"
        )
        for binding in result.functional_binding_context.bindings
    )


def test_wire_resolver_and_compiler_authorities_are_orthogonal() -> None:
    result, catalog = _reconcile("nankai")
    context = result.functional_binding_context
    assert context is not None

    parameter = context.binding_for("ii_1_solve_m", "parameter", 0)
    minimum = context.binding_for("ii_1_solve_m", "length_squared", 0)
    compiler = context.binding_for("ii_1_solve_m", "constraint", 0)
    assert parameter is not None and parameter.binding_authority == "resolver"
    assert parameter.selection_policy == "identity_only"
    assert minimum is not None and minimum.binding_authority == "wire"
    assert compiler is not None and compiler.binding_authority == "compiler"
    assert compiler.source.kind == "compiler_selector"

    projected = project_functional_arg_bindings(result, catalog=catalog)
    projected_keys = {(item.step_id, item.arg_name) for item in projected}
    assert ("ii_1_solve_m", "length_squared") in projected_keys
    projected_parameter = next(
        item
        for item in projected
        if (item.step_id, item.arg_name)
        == ("ii_1_solve_m", "parameter")
    )
    assert projected_parameter.binding_authority == "resolver"
    assert ("ii_1_solve_m", "constraint") not in projected_keys
    assert all(item.semantic_role for item in projected)
    empty_target_keys = {
        (item.step_id, item.arg_name, item.item_index)
        for item in projected
        if not item.runtime_input_targets
    }
    assert empty_target_keys == {
        (
            binding.key.call_id,
            binding.key.arg_name,
            binding.key.item_index,
        )
        for binding in context.bindings
        if binding.binding_authority != "compiler"
        and binding.consumption_mode == "resolver_evidence"
    }


def test_legacy_and_transactional_functional_projection_share_the_ledger() -> None:
    result, catalog = _reconcile("nankai")

    transactional = project_functional_arg_bindings(result, catalog=catalog)
    legacy = _functional_projected_arg_bindings(result, catalog=catalog)

    assert legacy == transactional
    assert {item.binding_authority for item in legacy} == {"wire", "resolver"}
    assert all(item.semantic_role for item in legacy)
    empty_target_keys = {
        (item.step_id, item.arg_name, item.item_index)
        for item in legacy
        if not item.runtime_input_targets
    }
    assert empty_target_keys == {
        (
            binding.key.call_id,
            binding.key.arg_name,
            binding.key.item_index,
        )
        for binding in result.functional_binding_context.bindings
        if binding.binding_authority != "compiler"
        and binding.consumption_mode == "resolver_evidence"
    }


def test_binding_projection_audit_reports_real_mismatch_and_fallback() -> None:
    result, catalog = _reconcile("nankai")
    context = result.functional_binding_context
    assert context is not None
    projected = project_functional_arg_bindings(result, catalog=catalog)
    first = projected[0]
    damaged = (
        replace(
            first,
            semantic_role=None,
            runtime_input_targets=(),
        ),
        *projected[1:],
    )

    audit = audit_functional_arg_binding_projection(context, damaged)

    assert audit.legacy_fallback_count == 1
    assert audit.mismatches
    assert audit.mismatches[0]["call_id"] == first.step_id
    assert "legacy_role_fallback_required" in audit.mismatches[0]["details"]


def test_post_compile_binding_audit_checks_actual_target_and_source_path() -> None:
    result, _catalog = _reconcile("nankai")
    context = result.functional_binding_context
    assert context is not None
    source = context.binding_for("ii_1_solve_m", "length_squared", 0)
    assert source is not None
    binding = replace(
        source,
        runtime_input_targets=("method.value",),
    )
    plan = SimpleNamespace(
        invocations=(
            SimpleNamespace(
                invocation_id="invoke",
                method_id="method",
                inputs={"value": "$runtime.actual"},
            ),
        ),
    )

    matching = audit_compiled_functional_arg_consumption(
        (binding,),
        (plan,),
        expected_runtime_paths={binding.key: "$runtime.actual"},
    )
    assert not matching.mismatches

    wrong_path = audit_compiled_functional_arg_consumption(
        (binding,),
        (plan,),
        expected_runtime_paths={binding.key: "$runtime.stale"},
    )
    assert wrong_path.mismatches[0]["details"] == [
        "runtime_source_path_drift"
    ]

    missing_target = audit_compiled_functional_arg_consumption(
        (replace(binding, runtime_input_targets=("method.missing",)),),
        (plan,),
        expected_runtime_paths={binding.key: "$runtime.actual"},
    )
    assert "runtime_target_not_consumed" in missing_target.mismatches[0][
        "details"
    ]


def test_semantic_latest_and_call_result_exact_are_part_of_binding() -> None:
    result, _catalog = _reconcile("nankai")
    context = result.functional_binding_context
    assert context is not None

    semantic = context.binding_for(
        "i_derive_parabola",
        "known_coefficients",
        0,
    )
    call_result = context.binding_for(
        "ii_1_evaluate_minimum",
        "expression",
        0,
    )
    assert semantic is not None and semantic.selection_policy == "latest"
    assert call_result is not None and call_result.selection_policy == "exact"
    assert call_result.source.kind == "call_result"


def test_source_identity_requires_exactly_one_typed_category() -> None:
    with pytest.raises(
        FunctionalBindingContextError,
        match="planner.functional_binding_context_incomplete",
    ):
        FunctionalArgSourceIdentity(
            kind="math_object",
            math_object_id=MathObjectId("symbol:problem:u", "symbol", "problem"),
            condition_id="condition:u_positive",
        )
