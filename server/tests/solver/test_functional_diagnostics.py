from __future__ import annotations

import ast
from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.contracts import CheckResult, PointRef
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FUNCTIONAL_DIAGNOSTIC_AUTHORITY_CONTRACT,
    FUNCTIONAL_PROMPT_DIAGNOSTIC_CONTRACT,
    FunctionalDiagnosticAuthority,
    FunctionalPromptDiagnostic,
    FunctionalPromptDiagnosticProjector,
    StatelessMethodError,
    diagnostic_authority_from_issue,
    functional_diagnostic_authority_schema,
    functional_prompt_diagnostic_schema,
    method_check_failed,
    method_input_invalid,
    method_input_missing,
    method_result_ambiguous,
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
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    FunctionalGoalRetryError,
    FunctionalGoalRetryProjector,
)

from _functional_goal_retry_support import goal_retry_fixture
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

    with pytest.raises(FunctionalGoalRetryError) as error:
        FunctionalGoalRetryProjector().project(
            plan=fixture.failed_plan,
            execution=execution,
            planning_context=fixture.planning_context,
            binding_catalog=fixture.binding_catalog,
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
