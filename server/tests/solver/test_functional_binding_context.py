from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.contracts import (
    ConditionSourceSpec,
    ExactCallResultSourceSpec,
    FreeSymbolBasisDerivationSpec,
    LatestStateSourceSpec,
    MethodInputBindingSpec,
    ProducerLinkedSourceSpec,
)
from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalArgSourceIdentity,
    FunctionalBindingContextBuilder,
    FunctionalBindingContextError,
    _binding_signature,
    _typed_input_selected_source,
    audit_compiled_functional_arg_consumption,
    audit_functional_arg_binding_projection,
    build_functional_runtime_arg_bindings_from_context,
)
from shuxueshuo_server.solver.runtime.condition_binding_authority import (
    ConditionBindingAuthorityIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan import (
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalCallReconciliation,
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.runtime.functional_transaction_execution import (
    build_functional_runtime_arg_bindings,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    _functional_runtime_arg_bindings,
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
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
)
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    FunctionArgBindingRepair,
    ProjectedFunctionArgBinding,
)

from _problem_planning_support import cached_planning_binding_fixture


def _reconcile(case_id: str, payload: dict | None = None):
    case = FUNCTIONAL_BATCH_CASES[case_id]
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        problem_binding_catalog,
    ) = cached_planning_binding_fixture(case.problem_id)
    payload = payload or json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
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
    result = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=problem_binding_catalog,
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
            binding.binding_authority != "compiler"
            or binding.input_binding is not None
        )
        and (
            binding.runtime_input_targets
            or binding.consumption_mode == "resolver_evidence"
        )
        for binding in result.functional_binding_context.bindings
    )


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_catalog_backed_latest_state_bindings_are_finalized_exact(
    case_id: str,
) -> None:
    result, _catalog = _reconcile(case_id)
    context = result.functional_binding_context
    assert context is not None
    latest_state_bindings = tuple(
        binding
        for binding in context.bindings
        if binding.input_binding is not None
        and isinstance(
            binding.input_binding.source,
            LatestStateSourceSpec,
        )
    )

    assert latest_state_bindings
    assert all(
        binding.selection_policy == "exact"
        for binding in latest_state_bindings
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
    assert compiler is not None
    assert compiler.binding_authority == "compiler"
    assert compiler.consumption_mode == "typed_binding"
    assert compiler.source.kind == "condition"
    assert isinstance(compiler.input_binding.source, ConditionSourceSpec)

    projected = build_functional_runtime_arg_bindings(result, catalog=catalog)
    projected_keys = {(item.step_id, item.arg_name) for item in projected}
    assert ("ii_1_solve_m", "length_squared") in projected_keys
    projected_parameter = next(
        item
        for item in projected
        if (item.step_id, item.arg_name)
        == ("ii_1_solve_m", "parameter")
    )
    assert projected_parameter.binding_authority == "resolver"
    assert ("ii_1_solve_m", "constraint") in projected_keys
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


def test_runtime_binding_manifest_is_projected_from_the_ledger() -> None:
    result, catalog = _reconcile("nankai")

    transactional = build_functional_runtime_arg_bindings(result, catalog=catalog)
    manifest = _functional_runtime_arg_bindings(result, catalog=catalog)

    assert manifest == transactional
    assert {item.binding_authority for item in manifest} == {
        "wire",
        "resolver",
        "compiler",
    }
    assert all(item.semantic_role for item in manifest)
    empty_target_keys = {
        (item.step_id, item.arg_name, item.item_index)
        for item in manifest
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
    projected = build_functional_runtime_arg_bindings(result, catalog=catalog)
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
                    outputs={},
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

    point_identity = replace(
        binding,
        selection_policy="identity_only",
    )
    identity_view = SimpleNamespace(
        invocations=(
            SimpleNamespace(
                invocation_id="invoke",
                method_id="method",
                inputs={"value": "$question.ii.object_refs.N"},
                outputs={},
            ),
        )
    )
    identity_audit = audit_compiled_functional_arg_consumption(
        (point_identity,),
        (identity_view,),
        expected_runtime_paths={
            point_identity.key: "$question.ii.points.N"
        },
    )
    assert not identity_audit.mismatches

    foreign_identity = SimpleNamespace(
        invocations=(
            SimpleNamespace(
                invocation_id="invoke",
                method_id="method",
                inputs={"value": "$question.ii.object_refs.M"},
                outputs={},
            ),
        )
    )
    foreign_audit = audit_compiled_functional_arg_consumption(
        (point_identity,),
        (foreign_identity,),
        expected_runtime_paths={
            point_identity.key: "$question.ii.points.N"
        },
    )
    assert foreign_audit.mismatches[0]["details"] == [
        "runtime_source_path_drift"
    ]

def test_post_compile_binding_audit_accepts_deterministic_basis_repair() -> None:
    result, _catalog = _reconcile("nankai")
    context = result.functional_binding_context
    assert context is not None
    source = context.binding_for("ii_1_solve_m", "free_parameters", 0)
    if source is None:
        source = next(
            item
            for item in context.bindings
            if item.binding_authority == "wire"
        )
    binding = replace(
        source,
        key=replace(source.key, arg_name="free_parameters", item_index=0),
        source=FunctionalArgSourceIdentity(
            kind="math_object",
            math_object_id=MathObjectId(
                "symbol:problem:b",
                "symbol",
                "problem",
            ),
        ),
        runtime_input_targets=("free_parameters",),
    )
    plan = SimpleNamespace(
        invocations=(
            SimpleNamespace(
                invocation_id="quadratic",
                method_id="quadratic_from_constraints",
                inputs={"free_parameter": "$problem.symbols.b"},
                outputs={},
            ),
        ),
    )

    audit = audit_compiled_functional_arg_consumption(
        (binding,),
        (plan,),
        expected_runtime_paths={binding.key: "$problem.symbols.b"},
        arg_repairs=(
            FunctionArgBindingRepair(
                arg_name="free_parameters",
                source_handles=("symbol:problem:b",),
                reason="normalize_constraint_free_parameter_basis",
            ),
        ),
    )

    assert not audit.mismatches
    assert audit.decisions[0]["deterministic_arg_repair"] == {
        "arg_name": "free_parameters",
        "source_handles": ["symbol:problem:b"],
        "reason": "normalize_constraint_free_parameter_basis",
    }

    forged = audit_compiled_functional_arg_consumption(
        (binding,),
        (plan,),
        expected_runtime_paths={binding.key: "$problem.symbols.b"},
        arg_repairs=(
            FunctionArgBindingRepair(
                arg_name="free_parameters",
                source_handles=("symbol:problem:c",),
                reason="normalize_constraint_free_parameter_basis",
            ),
        ),
    )
    assert "runtime_target_not_consumed" in forged.mismatches[0]["details"]


def test_return_binding_rejects_sibling_private_object() -> None:
    case = FUNCTIONAL_BATCH_CASES["heping-ermo"]
    payload = json.loads(case.functional_fixture_path.read_text(encoding="utf-8"))
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_square_vertex_G_i"
    )
    call["return_bindings"]["point"] = {
        "kind": "point",
        "ref": "ii.G",
    }

    result, _catalog = _reconcile("heping-ermo", payload)

    issue = next(
        item
        for item in result.issues
        if item.call_id == "derive_square_vertex_G_i"
        and item.code == "functional.semantic_ref_not_visible_for_goal"
    )
    assert "ii.G" in issue.message


def test_optional_condition_uses_derived_parameter_value_authority() -> None:
    result, _catalog = _reconcile("heping-ermo")
    context = result.functional_binding_context
    assert context is not None

    bindings = tuple(
        item
        for item in context.bindings
        if item.key.arg_name == "parameter_constraint"
        and item.binding_authority == "compiler"
    )

    assert len(bindings) == 1
    assert bindings[0].key.call_id == "recover_target_point_E_ii"
    assert {
        (item.source.kind, item.source.condition_id)
        for item in bindings
    } == {
        ("condition", "condition:symbol_constraint_6098472a86b7@problem")
    }
    assert all(item.consumption_mode == "typed_binding" for item in bindings)


def test_curve_points_use_declared_scalar_lowering_targets() -> None:
    result, _catalog = _reconcile("nankai")
    context = result.functional_binding_context
    assert context is not None

    bindings = tuple(
        item
        for item in context.for_call("ii_derive_parabola")
        if item.key.arg_name == "curve_points"
    )

    assert [item.runtime_input_targets for item in bindings] == [
        ("curve_points",),
        ("curve_points",),
    ]

    case = FUNCTIONAL_BATCH_CASES["heping"]
    payload = json.loads(
        case.functional_fixture_path.read_text(encoding="utf-8")
    )
    call = next(
        item
        for scope in payload["scopes"]
        for item in scope["calls"]
        if item["call_id"] == "derive_parabola_i"
    )
    call["args"]["curve_points"] = call["args"]["curve_points"][:1]
    singleton, _catalog = _reconcile("heping", payload)
    singleton_context = singleton.functional_binding_context
    assert singleton_context is not None
    singleton_binding = singleton_context.binding_for(
        "derive_parabola_i",
        "curve_points",
        0,
    )
    assert singleton_binding is not None
    assert singleton_binding.runtime_input_targets == ("curve_point",)


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
    point_state = context.binding_for(
        "ii_1_solve_m",
        "p1",
        0,
    )
    assert semantic is not None and semantic.selection_policy == "exact"
    assert call_result is not None and call_result.selection_policy == "exact"
    assert call_result.source.kind == "call_result"
    assert call_result.source.source_call_id == "ii_path_minimum"
    assert call_result.source.source_return_name == "minimum_expression"
    assert call_result.input_binding is not None
    assert call_result.input_binding.source is not None
    assert call_result.input_binding.source.kind == "exact_call_result"
    assert point_state is not None and point_state.source.kind == "state_version"
    assert point_state.input_binding is not None
    assert point_state.input_binding.source is not None
    assert point_state.input_binding.source.kind == "public_arg"


def test_exact_result_binding_requires_one_declared_producer_return() -> None:
    binding = MethodInputBindingSpec(
        input_name="expression",
        source=ExactCallResultSourceSpec("expression"),
    )
    base = {
        "arg_name": "expression",
        "binding": binding,
        "runtime_input": "expression",
        "required": True,
        "capability": SimpleNamespace(returns=(), source=SimpleNamespace()),
        "calls_by_id": {},
        "object_registry": None,
        "handle_registry": None,
        "method_specs": None,
    }

    with pytest.raises(FunctionalBindingContextError) as missing:
        _typed_input_selected_source(
            **base,
            call=SimpleNamespace(call_id="consumer", resolved_args={}),
        )
    assert missing.value.code == "planner.method_input_view_authority_missing"

    with pytest.raises(FunctionalBindingContextError) as ambiguous:
        _typed_input_selected_source(
            **base,
            call=SimpleNamespace(
                call_id="consumer",
                resolved_args={
                    "expression": (
                        ResolvedFunctionalValue(
                            "first",
                            "MinimumExpression",
                            "problem",
                            source_call_id="first",
                            return_name="minimum_expression",
                        ),
                        ResolvedFunctionalValue(
                            "second",
                            "MinimumExpression",
                            "problem",
                            source_call_id="second",
                            return_name="minimum_expression",
                        ),
                    ),
                },
            ),
        )
    assert ambiguous.value.code == "planner.method_input_view_authority_drift"


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


def test_typed_sources_survive_payload_round_trip() -> None:
    result, _catalog = _reconcile("xiqing")
    context = result.functional_binding_context
    assert context is not None
    selected_bindings = tuple(
        binding
        for binding in context.bindings
        if binding.binding_authority == "compiler"
        and binding.input_binding is not None
    )
    assert selected_bindings
    for binding in selected_bindings:
        assert FunctionalArgSourceIdentity.from_payload(
            binding.source.to_payload()
        ) == binding.source

    projected = build_functional_runtime_arg_bindings_from_context(
        result.calls,
        context,
    )
    restored = tuple(
        ProjectedFunctionArgBinding.from_payload(item.to_payload())
        for item in projected
    )
    audit = audit_functional_arg_binding_projection(context, restored)

    assert audit.mismatches == ()
    restored_by_key = {
        (item.step_id, item.arg_name, item.item_index): item
        for item in restored
    }
    for binding in selected_bindings:
        item = restored_by_key[
            (
                binding.key.call_id,
                binding.key.arg_name,
                binding.key.item_index,
            )
        ]
        selected = binding.source
        if selected.math_object_id is not None:
            assert item.math_object_id == selected.math_object_id
        if selected.state_version_id is not None:
            assert item.state_version_id == selected.state_version_id
        if selected.condition_id is not None:
            assert item.condition_id == selected.condition_id
        if selected.source_call_id is not None:
            assert item.source_call_id == selected.source_call_id
            assert item.source_return_name == selected.source_return_name

    selected_by_key = {
        (binding.key.call_id, binding.key.arg_name): (
            binding.source.math_object_id.value
            if binding.source.math_object_id is not None
            else None
        )
        for binding in selected_bindings
    }
    assert not any(
        call_id in {
            "transform_weighted_path_ii",
            "derive_weighted_minimum_ii",
        }
        and arg_name in {"dynamic_parameter", "parameter"}
        for call_id, arg_name in selected_by_key
    )


def test_atomic_weighted_hidden_symbol_ignores_sibling_candidate() -> None:
    result, catalog = _reconcile("xiqing")
    case = FUNCTIONAL_BATCH_CASES["xiqing"]
    *_, registry, planner_context, problem_binding_catalog = (
        cached_planning_binding_fixture(case.problem_id)
    )
    sibling = "symbol:ii_1:q"
    expanded_registry = replace(
        registry,
        entity_handles=registry.entity_handles | {sibling},
        handle_valid_scopes={
            **registry.handle_valid_scopes,
            sibling: "ii_1",
        },
        entity_payloads={
            **registry.entity_payloads,
            sibling: {
                "handle": sibling,
                "entity_type": "symbol",
                "name": "q",
                "scope_id": "ii_1",
                "role": "dynamic_parameter",
            },
        },
    )

    object_registry = MathObjectRegistry.from_sources(expanded_registry)
    condition_index = ConditionBindingAuthorityIndex.from_context(
        planner_context,
        object_registry=object_registry,
        problem_binding_catalog=problem_binding_catalog,
    )
    rebuilt = FunctionalBindingContextBuilder().build(
        result.plan,
        result.calls,
        catalog=catalog,
        object_registry=object_registry,
        handle_registry=expanded_registry,
        method_specs=MethodSpecRegistry.load_from_code(),
        condition_authority_index=condition_index,
    )
    dynamic = rebuilt.binding_for(
        "derive_weighted_minimum_ii",
        "dynamic_parameter",
        0,
    )
    assert dynamic is not None
    assert dynamic.input_binding is None
    assert dynamic.consumption_mode == "resolver_evidence"
    assert dynamic.source.math_object_id == MathObjectId(
        "symbol:ii_2:m",
        "symbol",
        "ii_2",
    )


def test_atomic_weighted_hidden_symbol_is_not_a_public_binding() -> None:
    result, catalog = _reconcile("xiqing")
    case = FUNCTIONAL_BATCH_CASES["xiqing"]
    *_, registry, planner_context, problem_binding_catalog = (
        cached_planning_binding_fixture(case.problem_id)
    )
    visible = "symbol:problem:q"
    expanded_registry = replace(
        registry,
        entity_handles=registry.entity_handles | {visible},
        handle_valid_scopes={
            **registry.handle_valid_scopes,
            visible: "problem",
        },
        entity_payloads={
            **registry.entity_payloads,
            visible: {
                "handle": visible,
                "entity_type": "symbol",
                "name": "q",
                "scope_id": "problem",
                "role": "dynamic_parameter",
            },
        },
    )

    object_registry = MathObjectRegistry.from_sources(expanded_registry)
    condition_index = ConditionBindingAuthorityIndex.from_context(
        planner_context,
        object_registry=object_registry,
        problem_binding_catalog=problem_binding_catalog,
    )
    rebuilt = FunctionalBindingContextBuilder().build(
        result.plan,
        result.calls,
        catalog=catalog,
        object_registry=object_registry,
        handle_registry=expanded_registry,
        method_specs=MethodSpecRegistry.load_from_code(),
        condition_authority_index=condition_index,
    )
    dynamic = rebuilt.binding_for(
        "derive_weighted_minimum_ii",
        "dynamic_parameter",
        0,
    )

    assert dynamic is not None
    assert dynamic.input_binding is None
    assert dynamic.consumption_mode == "resolver_evidence"
    assert dynamic.source.math_object_id == MathObjectId(
        "symbol:ii_2:m",
        "symbol",
        "ii_2",
    )


def _symbol_projection_fixture(
    *,
    resolved_args: dict[str, tuple[ResolvedFunctionalValue, ...]],
    producer_args: dict[str, tuple[ResolvedFunctionalValue, ...]] | None = None,
):
    registry = MathObjectRegistry()
    for ref in ("symbol:problem:b", "symbol:problem:c"):
        assert registry.register_handle(ref) is not None
    consumer = FunctionalCallReconciliation(
        call_id="consumer",
        scope_id="problem",
        capability_id="capability",
        resolved_args=resolved_args,
        returns=(),
    )
    producer = FunctionalCallReconciliation(
        call_id="producer",
        scope_id="problem",
        capability_id="producer_capability",
        resolved_args=producer_args or {},
        returns=(),
    )
    input_spec = SimpleNamespace(
        view=SimpleNamespace(mode="identity", object_kind="symbol")
    )
    method_specs = SimpleNamespace(
        require=lambda _method_id: SimpleNamespace(
            inputs={"parameter": input_spec}
        )
    )
    capability = SimpleNamespace(
        source=SimpleNamespace(method_id="method"),
        returns=(),
        auto_args=(),
    )
    return registry, consumer, producer, method_specs, capability


def test_producer_arg_evidence_follows_the_declared_source_arg_producer() -> None:
    b = MathObjectId("symbol:problem:b", "symbol", "problem")
    c = MathObjectId("symbol:problem:c", "symbol", "problem")
    registry, consumer, producer, method_specs, capability = (
        _symbol_projection_fixture(
            resolved_args={
                "parameter_value": (
                    ResolvedFunctionalValue(
                        handle="parameter_value",
                        runtime_type="ParameterValue",
                        valid_scope="problem",
                        source_call_id="producer",
                        return_name="parameter_value",
                        object_ref="symbol:problem:b",
                        math_object_id=b,
                        free_symbol_refs=("symbol:problem:b",),
                    ),
                ),
                "unrelated_result": (
                    ResolvedFunctionalValue(
                        handle="unrelated_result",
                        runtime_type="Point",
                        valid_scope="problem",
                        source_call_id="unrelated_producer",
                        return_name="point",
                    ),
                ),
            },
            producer_args={
                "parameter": (
                    ResolvedFunctionalValue(
                        handle="symbol:problem:b",
                        runtime_type="Symbol",
                        valid_scope="problem",
                        object_ref="symbol:problem:b",
                        math_object_id=b,
                    ),
                ),
            },
        )
    )
    unrelated_producer = FunctionalCallReconciliation(
        call_id="unrelated_producer",
        scope_id="problem",
        capability_id="unrelated_capability",
        resolved_args={
            "parameter": (
                ResolvedFunctionalValue(
                    handle="symbol:problem:c",
                    runtime_type="Symbol",
                    valid_scope="problem",
                    object_ref="symbol:problem:c",
                    math_object_id=c,
                ),
            ),
        },
        returns=(),
    )

    selected = _typed_input_selected_source(
        arg_name="parameter",
        binding=MethodInputBindingSpec(
            input_name="parameter",
            source=ProducerLinkedSourceSpec("parameter_value", "parameter"),
        ),
        runtime_input="parameter",
        required=True,
        capability=capability,
        call=consumer,
        calls_by_id={
            "producer": producer,
            "unrelated_producer": unrelated_producer,
        },
        object_registry=registry,
        handle_registry=None,
        method_specs=method_specs,
    )

    assert selected == FunctionalArgSourceIdentity(
        kind="math_object",
        math_object_id=b,
    )


def test_compiler_projection_requires_all_declared_evidence_to_agree() -> None:
    b = MathObjectId("symbol:problem:b", "symbol", "problem")
    c = MathObjectId("symbol:problem:c", "symbol", "problem")
    registry, consumer, producer, method_specs, capability = (
        _symbol_projection_fixture(
            resolved_args={
                "parameter_value": (
                    ResolvedFunctionalValue(
                        handle="parameter_value",
                        runtime_type="ParameterValue",
                        valid_scope="problem",
                        source_call_id="producer",
                        return_name="parameter_value",
                        object_ref="symbol:problem:b",
                        math_object_id=b,
                        free_symbol_refs=("symbol:problem:c",),
                    ),
                ),
            },
            producer_args={
                "parameter": (
                    ResolvedFunctionalValue(
                        handle="symbol:problem:c",
                        runtime_type="Symbol",
                        valid_scope="problem",
                        object_ref="symbol:problem:c",
                        math_object_id=c,
                    ),
                ),
            },
        )
    )

    with pytest.raises(
        FunctionalBindingContextError,
        match="arg:parameter_value.*producer_arg:parameter",
    ):
        _typed_input_selected_source(
            arg_name="parameter",
            binding=MethodInputBindingSpec(
                input_name="parameter",
                source=ProducerLinkedSourceSpec(
                    "parameter_value",
                    "parameter",
                ),
            ),
            runtime_input="parameter",
            required=True,
            capability=capability,
            call=consumer,
            calls_by_id={"producer": producer},
            object_registry=registry,
            handle_registry=None,
            method_specs=method_specs,
        )


def test_free_symbol_projection_never_uses_max_coverage_as_winner() -> None:
    registry, consumer, producer, method_specs, capability = (
        _symbol_projection_fixture(
            resolved_args={
                "left": (
                    ResolvedFunctionalValue(
                        handle="left",
                        runtime_type="Expression",
                        valid_scope="problem",
                        free_symbol_refs=("symbol:problem:b",),
                    ),
                ),
                "right": (
                    ResolvedFunctionalValue(
                        handle="right",
                        runtime_type="Expression",
                        valid_scope="problem",
                        free_symbol_refs=("symbol:problem:b",),
                    ),
                ),
                "minority": (
                    ResolvedFunctionalValue(
                        handle="minority",
                        runtime_type="Expression",
                        valid_scope="problem",
                        free_symbol_refs=("symbol:problem:c",),
                    ),
                ),
            }
        )
    )

    with pytest.raises(
        FunctionalBindingContextError,
        match="ambiguous_channels=.*free_symbol_basis",
    ):
        _typed_input_selected_source(
            arg_name="parameter",
            binding=MethodInputBindingSpec(
                input_name="parameter",
                derivation=FreeSymbolBasisDerivationSpec(
                    ("left", "right", "minority")
                ),
            ),
            runtime_input="parameter",
            required=True,
            capability=capability,
            call=consumer,
            calls_by_id={"producer": producer},
            object_registry=registry,
            handle_registry=None,
            method_specs=method_specs,
        )


def test_ambiguous_unconsumed_optional_source_fails_loud() -> None:
    registry, consumer, producer, method_specs, capability = (
        _symbol_projection_fixture(
            resolved_args={
                "left": (
                    ResolvedFunctionalValue(
                        handle="left",
                        runtime_type="Expression",
                        valid_scope="problem",
                        free_symbol_refs=(
                            "symbol:problem:b",
                            "symbol:problem:c",
                        ),
                    ),
                ),
            }
        )
    )

    with pytest.raises(
        FunctionalBindingContextError,
        match="ambiguous_channels=.*free_symbol_basis",
    ):
        _typed_input_selected_source(
            arg_name="parameter",
            binding=MethodInputBindingSpec(
                input_name="parameter",
                required=False,
                derivation=FreeSymbolBasisDerivationSpec(("left",)),
            ),
            runtime_input="parameter",
            required=False,
            capability=capability,
            call=consumer,
            calls_by_id={"producer": producer},
            object_registry=registry,
            handle_registry=None,
            method_specs=method_specs,
        )


def test_optional_zero_evidence_is_audited_without_a_binding() -> None:
    result, _catalog = _reconcile("heping-ermo")
    context = result.functional_binding_context
    assert context is not None

    omission = next(
        item
        for item in context.typed_input_omissions
        if item.call_id == "derive_x_intercept_A_i"
        and item.input_name == "known_point"
    )
    assert omission.reason == "optional_no_evidence"
    assert context.binding_for(
        "derive_x_intercept_A_i",
        "known_point",
        0,
    ) is None
    assert context.binding_signature == _binding_signature(
        context.bindings,
        relation_bindings=context.relation_bindings,
    )
