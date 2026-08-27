from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from shuxueshuo_server.solver.contracts import CheckResult, PointRef
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT,
    FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT,
    FunctionalDiagnosticAuthority,
    FunctionalDiagnosticSubject,
    FunctionalPromptDiagnostic,
    FunctionalPromptDiagnosticProjector,
    StatelessMethodError,
    diagnostic_authority_from_issue,
    functional_diagnostic_authority_schema,
    functional_prompt_diagnostic_schema,
    method_check_failed,
    method_input_invalid,
    method_input_missing,
    method_input_state_unavailable,
    method_result_ambiguous,
    method_result_empty,
    normalize_macro_diagnostic_authority,
    unexpected_method_error,
)
from shuxueshuo_server.solver.runtime.macro_specs import MacroSpecRegistry
from shuxueshuo_server.solver.runtime.methods import PointOnParabolaAtXMethod
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    _checkpoint_identity_payload,
    _reconciliation_issue_payload,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    FunctionalPlanIssue,
)
from shuxueshuo_server.solver.runtime.functional_scope_retry import (
    FunctionalScopeRetryAuthorityProjector,
    FunctionalScopeRetryError,
)

from _functional_scope_retry_support import scope_retry_fixture as goal_retry_fixture
from _problem_planning_support import planning_binding_fixture


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "internal" / "schemas"
METHOD_ROOT = (
    Path(__file__).resolve().parents[2]
    / "shuxueshuo_server"
    / "solver"
    / "runtime"
    / "methods"
)
RAW_METHOD_ERROR_NAMES = frozenset(
    {"ValueError", "TypeError", "RuntimeError", "AssertionError"}
)


def test_diagnostic_schemas_match_snapshots_and_round_trip() -> None:
    authority_schema = functional_diagnostic_authority_schema()
    prompt_schema = functional_prompt_diagnostic_schema()
    assert json.loads(
        (SCHEMA_ROOT / "functional-diagnostic-authority.schema.json").read_text(
            encoding="utf-8"
        )
    ) == authority_schema
    assert json.loads(
        (SCHEMA_ROOT / "functional-prompt-diagnostic.schema.json").read_text(
            encoding="utf-8"
        )
    ) == prompt_schema

    authority = method_input_missing(
        "missing fixed point",
        arg_name="fixed_point",
        role="fixed_endpoint",
        internal_ref="point:problem:M",
        expected={"type": "Point", "state": "materialized"},
        observed={"state": "missing"},
        repair_action="provide_visible_point_producer",
    ).authority
    restored = FunctionalDiagnosticAuthority.from_payload(authority.to_payload())
    assert restored.to_payload() == authority.to_payload()
    assert restored.schema_version == FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT

    prompt = FunctionalPromptDiagnostic(
        code="functional.method_input_missing",
        category="input",
        stage="method",
        retryability="planner_repairable",
        subjects=(),
        expected={"type": "Point", "state": "materialized"},
        observed={"state": "missing"},
        repair_action="provide_visible_point_producer",
        message="Add a visible Point producer.",
    )
    prompt_restored = FunctionalPromptDiagnostic.from_payload(prompt.to_payload())
    assert prompt_restored.to_payload() == prompt.to_payload()
    assert prompt_restored.schema_version == FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT


def test_nested_immutable_diagnostic_payload_is_json_safe_and_stable() -> None:
    authority = FunctionalDiagnosticAuthority(
        code="functional.method_input_state_unavailable",
        category="input",
        stage="constraint_analyzer",
        retryability="planner_repairable",
        expected=MappingProxyType(
            {
                "allowed_free_parameter_bases": (
                    MappingProxyType({"symbols": ("b",)}),
                    MappingProxyType({"symbols": ("c",)}),
                )
            }
        ),
        observed=MappingProxyType({"declared": frozenset()}),
        repair_action="align_symbolic_state_basis",
        authority_details=MappingProxyType(
            {"nested": MappingProxyType({"candidate_count": 2})}
        ),
    )

    payload = authority.to_payload()
    restored = FunctionalDiagnosticAuthority.from_payload(payload)

    json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert restored.to_payload() == payload
    assert stable_hash(restored.to_payload()) == stable_hash(payload)


def test_missing_m_projects_role_and_materialized_point_requirement(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    binding = next(
        item
        for item in fixture.binding_catalog.bindings.values()
        if item.usage == "input" and item.semantic_ref.ref == "M"
    )
    internal_ref = next(
        source.math_object_id.value
        for source in binding.typed_sources
        if source.math_object_id is not None
    )
    authority = method_input_missing(
        "fixed endpoint is not materialized",
        arg_name="fixed_point",
        role="fixed_endpoint",
        internal_ref=internal_ref,
        expected={"type": "Point", "state": "materialized"},
        observed={"state": "missing"},
        repair_action="provide_visible_point_producer",
    ).authority

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.retryability == "planner_repairable"
    assert prompt.subjects[0].to_payload() == {
        "ref": "M",
        "role": "fixed_endpoint",
        "arg_name": "fixed_point",
        "expected_type": "Point",
        "expected_state": "materialized",
        "observed_state": "missing",
    }
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert internal_ref not in wire
    assert "<internal-identity-omitted>" not in wire


def test_stale_derived_point_diagnostic_projects_both_entity_roles(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
    ) = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    object_ids = {}
    for binding in binding_catalog.bindings.values():
        if binding.usage != "input" or binding.semantic_ref.ref not in {"B", "C"}:
            continue
        for source in binding.typed_sources:
            if source.math_object_id is not None:
                object_ids[str(binding.semantic_ref.ref)] = (
                    source.math_object_id.value
                )
    authority = method_result_empty(
        "reference triangle is not isosceles",
        subjects=(
            FunctionalDiagnosticSubject(
                role="horizontal_axis_point",
                arg_name="x_axis_point",
                internal_ref=object_ids["B"],
                expected_type="Point",
                observed_state="open_state",
            ),
            FunctionalDiagnosticSubject(
                role="vertical_axis_point",
                arg_name="y_axis_point",
                internal_ref=object_ids["C"],
                expected_type="Point",
                observed_state="closed_state",
            ),
        ),
        observed={"horizontal_free_symbols": ["a"]},
        repair_action="refresh_derived_input_states",
    ).authority

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        binding_catalog,
        planning_context,
    )

    assert [item.ref for item in prompt.subjects] == ["B", "C"]
    assert prompt.repair_action == "refresh_derived_input_states"
    assert "Recompute or close" in prompt.message
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert object_ids["B"] not in wire
    assert object_ids["C"] not in wire


def test_return_role_issue_projects_exact_public_repair_contract(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = diagnostic_authority_from_issue(
        {
            "code": "functional.step_contract_invalid",
            "message": "return role does not match the capability",
            "details": {
                "capability_id": "quadratic_axis_x_intercept_point",
                "observed_role": "point",
                "expected_roles": ["axis_point"],
                "repair_action": "repair_return_role",
                "retryability": "planner_repairable",
            },
        },
        stage="reconciliation",
        step_id="derive_axis_point_M_ii",
    )

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.capability_id == "quadratic_axis_x_intercept_point"
    prompt_payload = prompt.to_payload()
    assert prompt_payload["observed"] == {"observed_role": "point"}
    assert prompt_payload["expected"] == {
        "expected_roles": ["axis_point"]
    }
    assert prompt.repair_action == "repair_return_role"
    assert "expected_roles" in prompt.message


def test_context_path_identity_projects_to_same_scope_source_ref(tmp_path) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
    ) = planning_binding_fixture(
        tmp_path,
        case="tj-2026-xiqing-yimo-25",
    )
    authority = method_input_state_unavailable(
        "declared Method input view is unavailable in the current scope",
        method_id="parameter_from_segment_length",
        capability_id="parameter_from_segment_length",
        scope_id="ii_1",
        step_id="solve_b_1",
        arg_name="p2",
        role="p2",
        internal_ref="$question.ii.points.D",
        expected={
            "domain_type": "Point",
            "runtime_type": "Point",
            "view": "latest_state",
        },
        observed={"error": "TypeError"},
        repair_action="provide_visible_entity_state",
    ).authority

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        binding_catalog,
        planning_context,
    )

    assert prompt.code == "functional.method_input_state_unavailable"
    assert prompt.retryability == "planner_repairable"
    assert prompt.subjects[0].ref == "D"
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert "$question.ii.points.D" not in wire
    assert "planner.method_contract_invalid" not in wire


def test_exact_call_result_identity_projects_to_step_result_ref(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = diagnostic_authority_from_issue(
        {
            "code": "functional.method_input_state_unavailable",
            "message": "exact anonymous result is unavailable",
            "details": {
                "source_call_id": "ii_straighten",
                "source_return_name": "path_minimum_expression",
                "arg_name": "minimum_expression",
                "expected_type": "MinimumExpression",
            },
        },
        stage="transaction",
    )
    call_result_id = "ii_straighten.path_minimum_expression"

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
        exact_result_refs={
            call_result_id: {
                "step_id": "ii_straighten",
                "return": "path_minimum_expression",
            }
        },
    )

    assert prompt.subjects[0].to_payload()["ref"] == {
        "step_id": "ii_straighten",
        "return": "path_minimum_expression",
    }
    restored = FunctionalPromptDiagnostic.from_payload(prompt.to_payload())
    assert restored.to_payload() == prompt.to_payload()
    assert call_result_id not in json.dumps(
        prompt.to_payload(),
        ensure_ascii=False,
    )


def test_xiqing_missing_target_x_projects_c_and_applicable_capability_action(
    tmp_path,
) -> None:
    (
        _bundle,
        planning_context,
        _problem,
        _inputs,
        _problem_payload,
        _registry,
        _planner_context,
        binding_catalog,
    ) = planning_binding_fixture(
        tmp_path,
        case="tj-2026-xiqing-yimo-25",
    )
    kernel = SympyKernel()
    x, b = kernel.symbols(["x", "b"]).values()

    with pytest.raises(StatelessMethodError) as error:
        PointOnParabolaAtXMethod().run(
            {
                "parabola": -x**2 + b * x + b + 1,
                "x": x,
                "target": PointRef(
                    "C",
                    "$question.ii.points.C",
                    definition={"definition": "y_axis_intercept", "of": "parabola"},
                ),
            },
            kernel,
        )

    prompt = FunctionalPromptDiagnosticProjector().project(
        error.value.authority,
        binding_catalog,
        planning_context,
    )

    assert prompt.code == "functional.method_precondition_failed"
    assert prompt.retryability == "planner_repairable"
    assert prompt.subjects[0].ref == "C"
    assert prompt.observed["construction"] == "y_axis_intercept"
    assert (
        prompt.repair_action
        == "choose_applicable_point_construction_capability"
    )


def test_macro_missing_public_arg_projects_only_the_public_contract(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    family = next(
        family
        for family in DEFAULT_FAMILY_REGISTRY.families
        if any(
            recipe.recipe_id == "broken_path_straightening_minimum_expression"
            for recipe in family.step_recipes
        )
    )
    macro = MacroSpecRegistry.from_family_spec(
        family,
        fixture.inputs.method_specs,
    ).require("broken_path_straightening_minimum_expression")
    inner = method_input_missing(
        "distance evaluation requires a substitution pair",
        method_id="distance_between_points",
        capability_id=macro.macro_id,
        step_id="derive_closed_minimum",
        observed={
            "missing_inputs": ["parameter", "parameter_value"],
            "provided_inputs": ["p1", "p2"],
        },
        repair_action="provide_required_input",
    ).authority

    authority = normalize_macro_diagnostic_authority(
        inner,
        macro_spec=macro,
        provided_arg_names=("path_transformation",),
    )
    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.code == "functional.macro_input_missing"
    assert prompt.retryability == "planner_repairable"
    assert prompt.method_id is None
    assert prompt.expected == {"required_args": ("parameter_value",)}
    assert prompt.subjects[0].arg_name == "parameter_value"
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert "distance_between_points" not in wire
    assert '"arg_name": "parameter"' not in wire


def test_supplied_macro_arg_that_fails_lowering_is_configuration_drift(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    family = next(
        family
        for family in DEFAULT_FAMILY_REGISTRY.families
        if any(
            recipe.recipe_id == "broken_path_straightening_minimum_expression"
            for recipe in family.step_recipes
        )
    )
    macro = MacroSpecRegistry.from_family_spec(
        family,
        fixture.inputs.method_specs,
    ).require("broken_path_straightening_minimum_expression")
    inner = method_input_missing(
        "distance evaluation requires a substitution pair",
        method_id="distance_between_points",
        capability_id=macro.macro_id,
        step_id="derive_closed_minimum",
        observed={
            "missing_inputs": ["parameter", "parameter_value"],
            "provided_inputs": ["p1", "p2"],
        },
        repair_action="provide_required_input",
    ).authority

    authority = normalize_macro_diagnostic_authority(
        inner,
        macro_spec=macro,
        provided_arg_names=("path_transformation", "parameter_value"),
    )

    assert authority.code == "planner.macro_contract_invalid"
    assert authority.retryability == "configuration"
    assert authority.method_id is None
    assert authority.subjects == ()


def test_macro_method_failure_keeps_public_object_role_not_hidden_arg(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    family = next(
        family
        for family in DEFAULT_FAMILY_REGISTRY.families
        if any(
            recipe.recipe_id == "broken_path_straightening_minimum_expression"
            for recipe in family.step_recipes
        )
    )
    macro = MacroSpecRegistry.from_family_spec(
        family,
        fixture.inputs.method_specs,
    ).require("broken_path_straightening_minimum_expression")
    binding = next(
        item
        for item in fixture.binding_catalog.bindings.values()
        if item.usage == "input" and item.semantic_ref.ref == "M"
    )
    internal_ref = next(
        source.math_object_id.value
        for source in binding.typed_sources
        if source.math_object_id is not None
    )
    inner = method_input_invalid(
        "fixed endpoint violates the geometric precondition",
        method_id="broken_path_straightening_candidates",
        capability_id=macro.macro_id,
        step_id="derive_minimum",
        arg_name="fixed_point_1",
        role="fixed_endpoint",
        internal_ref=internal_ref,
        expected={"type": "Point", "state": "materialized"},
        observed={"state": "invalid"},
        repair_action="repair_input_binding",
    ).authority

    authority = normalize_macro_diagnostic_authority(
        inner,
        macro_spec=macro,
        provided_arg_names=("path_transformation",),
    )
    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.method_id is None
    assert prompt.subjects[0].ref == "M"
    assert prompt.subjects[0].role == "fixed_endpoint"
    assert prompt.subjects[0].arg_name is None
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert "broken_path_straightening_candidates" not in wire
    assert "fixed_point_1" not in wire


def test_identity_projection_prefers_problem_input_over_answer_aliases(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    binding = next(
        item
        for item in fixture.binding_catalog.bindings.values()
        if item.usage == "input" and item.semantic_ref.ref == "E"
    )
    internal_ref = next(
        source.math_object_id.value
        for source in binding.typed_sources
        if source.math_object_id is not None
    )
    authority = method_input_missing(
        "point state is unavailable",
        role="curve_point",
        internal_ref=internal_ref,
        expected={"type": "Point", "state": "materialized"},
        observed={"expected_object_ref": internal_ref},
    ).authority

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.subjects[0].ref == "E"
    assert prompt.observed["expected_object_ref"] == "E"
    assert prompt.code == "functional.method_input_missing"


def test_object_diagnostic_prefers_exact_entity_runtime_node_over_fact(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path / "heping-ermo",
        case="tj-2026-heping-ermo-25",
    )
    planning_context = fixture[1]
    catalog = fixture[7]
    entity = next(
        item
        for item in catalog.bindings.values()
        if item.usage == "input" and item.semantic_ref.ref == "A"
    )
    coordinate = next(
        item
        for item in catalog.bindings.values()
        if item.usage == "input"
        and item.semantic_ref.ref == "point_coordinate_a"
    )
    assert entity.runtime_node_id != coordinate.runtime_node_id
    assert {
        source.math_object_id.value
        for binding in (entity, coordinate)
        for source in binding.typed_sources
        if source.math_object_id is not None
    } == {"point:problem:A"}
    authority = method_input_missing(
        "point state must be repaired",
        role="target_point",
        internal_ref=entity.runtime_node_id,
        expected={"type": "Point", "state": "materialized"},
        observed={"expected_object_ref": entity.runtime_node_id},
    ).authority

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        catalog,
        planning_context,
    )

    assert prompt.retryability == "planner_repairable"
    assert prompt.subjects[0].ref == "A"
    assert prompt.observed["expected_object_ref"] == "A"


def test_unmapped_repairable_identity_fails_closed_as_configuration(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = method_input_missing(
        "point state is unavailable",
        role="fixed_endpoint",
        internal_ref="point:foreign:PHANTOM",
        expected={"type": "Point", "state": "materialized"},
    ).authority

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.code == "planner.method_contract_invalid"
    assert prompt.retryability == "configuration"
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert "point:foreign:PHANTOM" not in wire
    assert "<internal-identity-omitted>" not in wire


@pytest.mark.parametrize(
    "stage",
    ("resolver", "compiler", "method", "runtime_check"),
)
def test_all_diagnostic_stages_use_the_same_prompt_projector(
    tmp_path,
    stage: str,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = diagnostic_authority_from_issue(
        {
            "code": "functional.method_result_ambiguous",
            "message": "two candidates remain",
            "details": {
                "candidate_count": 2,
                "expected_candidate_count": 1,
            },
        },
        stage=stage,
        method_id="demo_method",
        step_id="demo_step",
    )

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )

    assert prompt.schema_version == FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT
    assert prompt.stage == stage
    assert prompt.observed["candidate_count"] == 2


def test_named_entity_wire_issue_uses_unified_prompt_diagnostic(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    authority = diagnostic_authority_from_issue(
        {
            "code": "functional.named_entity_requires_source_ref",
            "message": "named output must be consumed through its Entity ref",
            "details": {
                "arg_name": "parabola",
                "expected_ref": "parabola",
                "named_entity_refs": ["parabola"],
                "producer": {
                    "step_id": "derive_parabola_i",
                    "return": "parabola",
                },
                "target": "parabola",
                "repair_action": "use_named_entity_source_ref",
            },
        },
        stage="authoring_schema",
        capability_id="quadratic_x_axis_intercept_point",
        scope_id="i_2",
        step_id="derive_x_intercept_B_i",
    )

    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture.binding_catalog,
        fixture.planning_context,
    )
    payload = prompt.to_payload()

    assert payload["code"] == "functional.named_entity_requires_source_ref"
    assert payload["retryability"] == "planner_repairable"
    assert payload["repair_action"] == "use_named_entity_source_ref"
    assert payload["subjects"] == [
        {"arg_name": "parabola", "ref": "parabola"}
    ]
    assert payload["expected"] == {"expected_ref": "parabola"}


def test_reconciliation_type_mismatch_projects_ref_arg_and_types(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    issue = FunctionalPlanIssue(
        layer="functional_reconciliation",
        code="functional.arg_type_mismatch",
        message=(
            "semantic value_type cannot satisfy argument: "
            "point_on_curve_parabola_a"
        ),
        call_id="derive_parabola",
        scope_id="i",
        details={
            "arg_name": "curve_points",
            "semantic_ref": "point_on_curve_parabola_a",
            "accepted_item_types": ["Point"],
            "actual_type": "point_on_curve",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture.binding_catalog,
        planning_context=fixture.planning_context,
    )

    assert payload["category"] == "input"
    assert payload["subjects"] == [
        {
            "ref": "point_on_curve_parabola_a",
            "arg_name": "curve_points",
            "expected_type": "Point",
            "observed_type": "point_on_curve",
        }
    ]
    assert payload["expected"] == {"accepted_types": ["Point"]}
    assert payload["observed"] == {"type": "point_on_curve"}
    assert payload["repair_action"] == "repair_input_binding"


def test_condition_parameter_ambiguity_projects_all_symbol_candidates(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )

    def internal_ref(ref: str) -> str:
        binding = next(
            item
            for item in fixture[7].bindings.values()
            if item.usage == "input" and item.semantic_ref.ref == ref
        )
        return next(
            source.math_object_id.value
            for source in binding.typed_sources
            if source.math_object_id is not None
        )

    issue = FunctionalPlanIssue(
        layer="functional_elaboration",
        code="functional.condition_parameter_ambiguous",
        message="condition selection requires one parameter Symbol",
        call_id="ii_construct_N",
        scope_id="ii",
        details={
            "role": "parameter",
            "expected_candidate_count": 1,
            "expected_type": "Symbol",
            "expected_state": "unique_visible_parameter",
            "candidate_count": 2,
            "symbol_candidates": [internal_ref("a"), internal_ref("m")],
            "repair_action": "supply_disambiguating_constraint",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture[7],
        planning_context=fixture[1],
    )

    assert {item["ref"] for item in payload["subjects"]} == {"a", "m"}
    assert all(
        item["role"] == "parameter_candidate"
        and item["expected_type"] == "Symbol"
        and item["expected_state"] == "candidate"
        for item in payload["subjects"]
    )
    assert payload["expected"] == {
        "expected_candidate_count": 1,
        "expected_state": "unique_visible_parameter",
        "expected_type": "Symbol",
    }
    assert payload["observed"] == {
        "candidate_count": 2,
        "symbol_candidates": ["a", "m"],
    }


def test_condition_target_ambiguity_preserves_endpoint_context(tmp_path) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )

    def internal_ref(ref: str) -> str:
        binding = next(
            item
            for item in fixture[7].bindings.values()
            if item.usage == "input" and item.semantic_ref.ref == ref
        )
        return next(
            source.math_object_id.value
            for source in binding.typed_sources
            if source.math_object_id is not None
        )

    m_ref = internal_ref("M")
    n_ref = internal_ref("N")
    issue = FunctionalPlanIssue(
        layer="functional_elaboration",
        code="functional.condition_target_ambiguous",
        message="the constructed endpoint cannot be determined uniquely",
        call_id="ii_construct_N",
        scope_id="ii",
        details={
            "role": "constructed_target",
            "expected_candidate_count": 1,
            "expected_type": "Point",
            "candidate_count": 2,
            "endpoints": [m_ref, n_ref],
            "materialized_points": [],
            "target_candidates": [m_ref, n_ref],
            "repair_action": "supply_disambiguating_constraint",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture[7],
        planning_context=fixture[1],
    )

    assert {item["ref"] for item in payload["subjects"]} == {"M", "N"}
    assert payload["expected"] == {
        "expected_candidate_count": 1,
        "expected_type": "Point",
    }
    assert payload["observed"] == {
        "candidate_count": 2,
        "endpoints": ["M", "N"],
        "materialized_points": [],
        "target_candidates": ["M", "N"],
    }


def test_output_target_selector_mismatch_projects_required_fact(tmp_path) -> None:
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )
    issue = FunctionalPlanIssue(
        layer="functional_authority",
        code="functional.output_target_selector_mismatch",
        message="output target is not authorized by the source-fact selector",
        call_id="redundant_build_M",
        scope_id="ii",
        details={
            "capability_id": "point_on_parabola_at_x",
            "semantic_ref": "M",
            "role": "point",
            "expected_type": "Point",
            "expected_state": "source_fact_authorized",
            "observed_role": "point",
            "observed_target": "M",
            "expected_targets": [],
            "required_fact_kind": "point_on_curve",
            "required_fields": {"construction": "curve_at_x"},
            "repair_options": [
                "use the existing visible object state without reconstructing it",
                "choose a capability whose source-fact selector matches this target",
            ],
            "repair_action": "choose_applicable_point_construction_capability",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture[7],
        planning_context=fixture[1],
    )

    assert payload["subjects"] == [
        {
            "ref": "M",
            "role": "point",
            "expected_type": "Point",
            "expected_state": "source_fact_authorized",
        }
    ]
    assert payload["expected"] == {
        "expected_state": "source_fact_authorized",
        "expected_targets": [],
        "expected_type": "Point",
        "required_fact_kind": "point_on_curve",
        "required_fields": {"construction": "curve_at_x"},
        "repair_options": [
            "use the existing visible object state without reconstructing it",
            "choose a capability whose source-fact selector matches this target",
        ],
    }
    assert payload["observed"] == {
        "observed_role": "point",
        "observed_target": "M",
    }
    assert payload["repair_action"] == (
        "choose_applicable_point_construction_capability"
    )
    assert "existing complete Point state" in payload["message"]


def test_distinct_argument_diagnostic_preserves_both_public_bindings(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    issue = FunctionalPlanIssue(
        layer="functional_reconciliation",
        code="functional.arg_distinctness_violation",
        message="target and preserved free parameter use the same Symbol",
        call_id="derive_parametric_parabola_ii",
        scope_id="ii",
        details={
            "subjects": [
                {
                    "role": "free_parameters",
                    "arg_name": "free_parameters",
                    "internal_ref": "symbol:problem:a",
                    "expected_type": "Symbol",
                    "expected_state": "distinct_math_entity",
                    "observed_state": "same_math_entity",
                },
                {
                    "role": "target_parameter",
                    "arg_name": "target_parameter",
                    "internal_ref": "symbol:problem:a",
                    "expected_type": "Symbol",
                    "expected_state": "distinct_math_entity",
                    "observed_state": "same_math_entity",
                },
            ],
            "arg_group": ["free_parameters", "target_parameter"],
            "duplicate_args": [["free_parameters", "target_parameter"]],
            "current_bindings": [
                {
                    "arg": "free_parameters",
                    "object_ref": "symbol:problem:a",
                    "state_slot_id": "state-slot:internal-a",
                },
                {
                    "arg": "target_parameter",
                    "object_ref": "symbol:problem:a",
                    "state_slot_id": "state-slot:internal-a",
                },
            ],
            "expected_relation": "pairwise_distinct_math_entities",
            "repair_options": [
                "omit target_parameter when parameter_value is unused",
                "preserve a different free-parameter basis",
            ],
            "observed_duplicate_args": [
                ["free_parameters", "target_parameter"]
            ],
            "repair_action": "separate_target_and_free_parameters",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture.binding_catalog,
        planning_context=fixture.planning_context,
    )

    assert [item["arg_name"] for item in payload["subjects"]] == [
        "free_parameters",
        "target_parameter",
    ]
    assert {item["ref"] for item in payload["subjects"]} == {"a"}
    assert payload["expected"]["expected_relation"] == (
        "pairwise_distinct_math_entities"
    )
    assert payload["expected"]["repair_options"] == [
        "omit target_parameter when parameter_value is unused",
        "preserve a different free-parameter basis",
    ]
    assert payload["observed"]["observed_duplicate_args"] == [
        ["free_parameters", "target_parameter"]
    ]
    assert "state_slot" not in json.dumps(
        {
            key: value
            for key, value in payload.items()
            if key != "_diagnostic_authority"
        },
        sort_keys=True,
    )
    assert payload["repair_action"] == "separate_target_and_free_parameters"


def test_state_unavailable_diagnostic_preserves_producer_scope_context(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    issue = FunctionalPlanIssue(
        layer="functional_reconciliation",
        code="functional.arg_state_unavailable",
        message="D has no state visible from scope ii",
        call_id="reduce_path_ii",
        scope_id="ii",
        details={
            "arg": "ray_point",
            "object_ref": "point:problem:D",
            "required_producer_scope": "ii",
            "existing_producer_scopes": ["i"],
            "existing_producers": [
                {"step_id": "calc_D_i", "scope_ref": "i"}
            ],
            "state_requirement": "materialized_state",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture.binding_catalog,
        planning_context=fixture.planning_context,
    )

    assert payload["subjects"][0]["ref"] == "D"
    assert payload["expected"]["required_producer_scope"] == "ii"
    assert payload["observed"]["existing_producer_scopes"] == ["i"]
    assert payload["observed"]["existing_producers"] == [
        {"step_id": "calc_D_i", "scope_ref": "i"}
    ]


def test_scope_visibility_diagnostic_projects_goal_and_scope_authority(
    tmp_path,
) -> None:
    fixture = planning_binding_fixture(
        tmp_path / "heping-ermo",
        case="tj-2026-heping-ermo-25",
    )
    issue = FunctionalPlanIssue(
        layer="functional_reconciliation",
        code="functional.call_scope_not_visible_for_goal",
        message="call execution scope is outside its GoalView authority",
        call_id="i_build_parabola",
        scope_id="i",
        details={
            "goal_unit_ids": ["goal:problem/ii:point_coordinate:E"],
            "observed_goal_refs": ["ii.E"],
            "observed_goal_scope_ids": ["ii"],
            "actual_execution_scope": "i",
            "expected_visible_scope_ids": ["problem", "ii"],
            "repair_action": "align_call_with_goal_scope",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture[7],
        planning_context=fixture[1],
    )
    authority = payload.pop("_diagnostic_authority")

    assert payload["retryability"] == "planner_repairable"
    assert payload["repair_action"] == "align_call_with_goal_scope"
    assert payload["expected"] == {
        "expected_visible_scope_ids": ["problem", "ii"]
    }
    assert payload["observed"] == {
        "actual_execution_scope": "i",
        "observed_goal_refs": ["ii.E"],
        "observed_goal_scope_ids": ["ii"],
    }
    assert "goal:problem/ii" not in json.dumps(
        payload,
        ensure_ascii=False,
    )
    assert authority["authority_details"]["goal_unit_ids"] == [
        "goal:problem/ii:point_coordinate:E"
    ]


def test_return_form_mismatch_preserves_runtime_closure_details(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    issue = FunctionalPlanIssue(
        layer="trial_execution",
        code="functional.return_form_mismatch",
        message="return point expected closed_state but retains ['c']",
        call_id="recover_E_ii",
        scope_id="ii",
        details={
            "return": "point",
            "expected_form": "closed_state",
            "observed_form": "symbolic_state",
            "observed_free_symbol_names": ["c"],
            "repair_action": "provide_visible_state_producer",
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture.binding_catalog,
        planning_context=fixture.planning_context,
    )
    payload.pop("_diagnostic_authority")

    assert payload["expected"] == {"expected_form": "closed_state"}
    assert payload["observed"] == {
        "observed_form": "symbolic_state",
        "observed_free_symbol_names": ["c"],
    }
    assert payload["repair_action"] == "provide_visible_state_producer"


def test_return_complexity_exceeded_explains_two_unknown_parameter_repair(
    tmp_path,
) -> None:
    fixture = goal_retry_fixture(tmp_path)
    issue = FunctionalPlanIssue(
        layer="trial_execution",
        code="functional.return_complexity_exceeded",
        message=(
            "return quadratic_state must contain at most 1 independent unknown "
            "parameter, but the current inputs leave 2: ['b', 'c']"
        ),
        call_id="derive_parametric_parabola_ii",
        scope_id="ii",
        details={
            "return": "quadratic_state",
            "expected_max_independent_free_parameters": 1,
            "observed_independent_free_parameter_count": 2,
            "observed_free_symbol_names": ["b", "c"],
            "retryability": "planner_repairable",
            "repair_action": (
                "reduce_symbolic_state_to_expected_parameter_count"
            ),
        },
    )

    payload = _reconciliation_issue_payload(
        issue,
        binding_catalog=fixture.binding_catalog,
        planning_context=fixture.planning_context,
    )
    payload.pop("_diagnostic_authority")

    assert payload["category"] == "result"
    assert payload["retryability"] == "planner_repairable"
    assert payload["expected"] == {
        "expected_max_independent_free_parameters": 1
    }
    assert payload["observed"] == {
        "observed_free_symbol_names": ["b", "c"],
        "observed_independent_free_parameter_count": 2,
    }
    assert payload["repair_action"] == (
        "reduce_symbolic_state_to_expected_parameter_count"
    )
    assert "current inputs and visible constraints" in payload["message"]
    assert "Do not merely delete a name from free_parameters" in payload["message"]


def test_method_check_failure_preserves_structured_check_details() -> None:
    error = method_check_failed(
        (
            CheckResult(
                name="point_on_locus",
                status="failed",
                detail="point misses locus",
                code="functional.point_not_on_locus",
                retryability="planner_repairable",
                expected={"state": "on_locus"},
                observed={"state": "off_locus"},
                subjects=({"role": "moving_point"},),
                repair_action="choose_matching_dynamic_point",
            ),
        ),
        method_id="demo_method",
    )

    authority = error.authority
    assert authority.code == "functional.method_check_failed"
    assert authority.retryability == "planner_repairable"
    assert authority.observed["failed_checks"][0]["code"] == (
        "functional.point_not_on_locus"
    )


def test_unknown_method_exception_is_nonretryable_configuration() -> None:
    error = unexpected_method_error(
        RuntimeError("unexpected implementation failure"),
        method_id="unmigrated_method",
        scope_id="i",
        step_id="bad_step",
    )

    assert error.authority.code == "planner.method_contract_invalid"
    assert error.authority.retryability == "configuration"
    assert error.authority.repair_action == "fix_runtime_contract"


def test_configuration_diagnostic_prevents_goal_repair_attempt(tmp_path) -> None:
    fixture = goal_retry_fixture(tmp_path)
    checkpoint = fixture.execution.checkpoint
    assert checkpoint is not None
    prompt = FunctionalPromptDiagnostic(
        code="planner.method_contract_invalid",
        category="configuration",
        stage="method",
        retryability="configuration",
        subjects=(),
        expected={},
        observed={"exception_type": "RuntimeError"},
        repair_action="fix_runtime_contract",
        message="Do not repair the Plan.",
    )
    drifted = replace(
        checkpoint,
        root_issues=(prompt.to_payload(),),
        checkpoint_id="pending",
    )
    drifted = replace(
        drifted,
        checkpoint_id=stable_hash(_checkpoint_identity_payload(drifted)),
    )
    execution = replace(fixture.execution, checkpoint=drifted)

    with pytest.raises(FunctionalScopeRetryError) as error:
        FunctionalScopeRetryAuthorityProjector().project(
            plan=fixture.failed_plan,
            execution=execution,
        )

    assert error.value.retryable is False
    assert error.value.code == "planner.method_contract_invalid"


def test_all_methods_do_not_raise_raw_execution_errors() -> None:
    violations: list[str] = []
    for path in sorted(METHOD_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or node.exc is None:
                continue
            call = node.exc
            if not isinstance(call, ast.Call):
                continue
            function = call.func
            if (
                isinstance(function, ast.Name)
                and function.id in RAW_METHOD_ERROR_NAMES
            ):
                violations.append(f"{path.name}:{node.lineno}:{function.id}")
    assert violations == []


def test_ambiguity_diagnostic_preserves_candidate_count() -> None:
    authority = method_result_ambiguous(
        "angle candidates are ambiguous",
        role="angle_candidate",
        expected={"candidate_count": 1},
        observed={"candidate_count": 3, "missing_constraint": "quadrant"},
    ).authority

    assert authority.code == "functional.method_result_ambiguous"
    assert authority.observed["candidate_count"] == 3
    assert authority.observed["missing_constraint"] == "quadrant"
