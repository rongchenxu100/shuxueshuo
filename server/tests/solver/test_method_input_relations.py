from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FunctionalDiagnosticAuthority,
    FunctionalPromptDiagnostic,
    FunctionalPromptDiagnosticProjector,
    diagnostic_authority_from_issue,
)
from shuxueshuo_server.solver.runtime.functional_plan_elaboration import (
    FunctionalSemanticIndex,
)
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    ResolvedFunctionalValue,
)
from shuxueshuo_server.solver.runtime.method_input_relations import (
    resolve_method_input_relations,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId

from _problem_planning_support import (
    SCOPE_NATIVE_FIXTURES,
    scope_native_reconciliation_fixture,
)


METHOD_RELATIONS = {
    "quadratic_from_constraints": (
        ("curve_point", "quadratic", "one"),
        ("curve_points", "quadratic", "for_each"),
    ),
    "parameter_from_curve_point_on_quadratic": (
        ("point", "quadratic", "one"),
    ),
    "point_candidates_from_curve_point_condition": (
        ("curve_point", "parabola", "one"),
    ),
}


@pytest.fixture
def heping_yimo_relation_fixture(tmp_path):
    (
        _bundle,
        planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        binding_catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    call = next(
        item
        for item in reconciliation.calls
        if item.call_id == "derive_parabola_i"
    )
    semantic_index = FunctionalSemanticIndex.from_semantic_items(
        planner_context,
        binding_catalog.semantic_read_items(),
        handle_registry=registry,
    )
    return {
        "planning_context": planning_context,
        "inputs": inputs,
        "planner_context": planner_context,
        "binding_catalog": binding_catalog,
        "reconciliation": reconciliation,
        "call": call,
        "semantic_index": semantic_index,
    }


def test_three_methods_declare_exact_point_on_curve_relations() -> None:
    registry = MethodSpecRegistry.load_from_code()

    for method_id, expected in METHOD_RELATIONS.items():
        spec = registry.require(method_id)
        assert tuple(
            (
                relation.point_arg,
                relation.curve_arg,
                relation.cardinality,
            )
            for relation in spec.input_relations
        ) == expected
        assert all(
            relation.relation_kind == "point_on_curve"
            and relation.accepted_condition_kinds
            == (
                "point_on_curve",
                "point_on_curve_with_x_coordinate",
            )
            for relation in spec.input_relations
        )


@pytest.mark.parametrize(
    ("method_id", "point_arg", "curve_arg"),
    (
        ("quadratic_from_constraints", "curve_point", "quadratic"),
        (
            "parameter_from_curve_point_on_quadratic",
            "point",
            "quadratic",
        ),
        (
            "point_candidates_from_curve_point_condition",
            "curve_point",
            "parabola",
        ),
    ),
)
def test_three_methods_resolve_the_same_exact_visible_condition(
    heping_yimo_relation_fixture,
    method_id: str,
    point_arg: str,
    curve_arg: str,
) -> None:
    fixture = heping_yimo_relation_fixture
    call = fixture["call"]
    point = call.resolved_args["curve_points"][0]
    curve = call.resolved_args["quadratic"][0]
    spec = fixture["inputs"].method_specs.require(method_id)

    resolution = resolve_method_input_relations(
        spec,
        {point_arg: (point,), curve_arg: (curve,)},
        call_id=f"exercise_{method_id}",
        capability_id=method_id,
        scope_id="i_1",
        semantic_index=fixture["semantic_index"],
    )

    assert resolution.issues == ()
    assert len(resolution.bindings) == 1
    binding = resolution.bindings[0]
    assert binding.point_object_ref == "point:problem:A"
    assert binding.curve_object_ref == "function:problem:parabola"
    assert binding.condition_kind == "point_on_curve"
    assert binding.condition_id.startswith("condition:point_on_curve_")


def test_debug_semantic_index_recovers_folded_entity_relation(
    tmp_path,
) -> None:
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        _binding_catalog,
        _plan,
        _validation,
        reconciliation,
    ) = scope_native_reconciliation_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    call = next(
        item
        for item in reconciliation.calls
        if item.call_id == "derive_parametric_parabola_ii"
    )
    debug_index = FunctionalSemanticIndex.from_context(
        planner_context,
        handle_registry=registry,
    )
    spec = inputs.method_specs.require(
        "quadratic_from_constraints"
    )

    resolution = resolve_method_input_relations(
        spec,
        {
            "curve_point": call.resolved_args["curve_point"],
            "quadratic": call.resolved_args["quadratic"],
        },
        call_id="debug_folded_relation",
        capability_id=spec.method_id,
        scope_id="i_1",
        semantic_index=debug_index,
    )

    assert resolution.issues == ()
    assert len(resolution.bindings) == 1
    assert resolution.bindings[0].condition_ref == "A"
    assert resolution.bindings[0].owner_scope_id == "problem"


def test_relation_binding_is_pinned_in_c3_and_problem_sidecar(
    heping_yimo_relation_fixture,
) -> None:
    fixture = heping_yimo_relation_fixture
    call = fixture["call"]
    c3 = fixture["reconciliation"].functional_binding_context
    sidecar = fixture["reconciliation"].functional_problem_binding_context

    assert c3 is not None
    assert sidecar is not None
    assert {item.point_item_index for item in call.relation_bindings} == {0, 1}
    assert {item.owner_scope_id for item in call.relation_bindings} == {
        "problem",
        "i",
    }
    assert c3.relations_for_call(call.call_id) == call.relation_bindings
    problem_relations = sidecar.relations_for_call(call.call_id)
    assert len(problem_relations) == 2
    assert {item.condition_id for item in problem_relations} == {
        item.condition_id for item in call.relation_bindings
    }
    assert all(item.source_unit_ids for item in problem_relations)
    assert sidecar.source_provenance_for_call(call.call_id).input_source_unit_ids


def test_x_coordinate_curve_relation_resolves_its_exact_condition(
    heping_yimo_relation_fixture,
) -> None:
    fixture = heping_yimo_relation_fixture
    semantic_index = fixture["semantic_index"]
    point_view = next(
        item
        for item in semantic_index.views
        if item.ref == "E" and item.runtime_type == "Point"
    )
    curve_view = next(
        item
        for item in semantic_index.views
        if item.ref == "parabola" and item.runtime_type == "Function"
    )
    point = ResolvedFunctionalValue(
        handle=point_view.handle,
        runtime_type=point_view.runtime_type,
        valid_scope=point_view.valid_scope,
        object_ref=point_view.object_ref,
        math_object_id=point_view.math_object_id,
    )
    curve = ResolvedFunctionalValue(
        handle=curve_view.handle,
        runtime_type=curve_view.runtime_type,
        valid_scope=curve_view.valid_scope,
        object_ref=curve_view.object_ref,
        math_object_id=curve_view.math_object_id,
    )
    spec = fixture["inputs"].method_specs.require(
        "point_candidates_from_curve_point_condition"
    )

    resolution = resolve_method_input_relations(
        spec,
        {"curve_point": (point,), "parabola": (curve,)},
        call_id="solve_e_candidates",
        capability_id=spec.method_id,
        scope_id="i_2",
        semantic_index=semantic_index,
    )

    assert resolution.issues == ()
    assert len(resolution.bindings) == 1
    relation = resolution.bindings[0]
    assert relation.condition_kind == "point_on_curve_with_x_coordinate"
    assert relation.condition_ref == "point_on_curve_with_x_coordinate_parabola_e_m"
    assert relation.owner_scope_id == "i_2"


def test_child_relation_cannot_be_consumed_from_root_and_projects_item_index(
    heping_yimo_relation_fixture,
) -> None:
    fixture = heping_yimo_relation_fixture
    call = fixture["call"]
    spec = fixture["inputs"].method_specs.require(
        "quadratic_from_constraints"
    )

    resolution = resolve_method_input_relations(
        spec,
        call.resolved_args,
        call_id=call.call_id,
        capability_id=call.capability_id,
        scope_id="problem",
        semantic_index=fixture["semantic_index"],
    )

    assert len(resolution.issues) == 1
    issue = resolution.issues[0]
    assert issue.code == "functional.method_relation_not_visible"
    assert issue.details["arg_name"] == "curve_points"
    assert issue.details["item_index"] == 1
    assert issue.details["observed_relation"] == {
        "relation_owner_scopes": ["i"]
    }

    authority = diagnostic_authority_from_issue(
        {
            "code": issue.code,
            "message": issue.message,
            "details": issue.details,
        },
        stage="reconciliation",
    )
    authority = FunctionalDiagnosticAuthority.from_payload(
        authority.to_payload()
    )
    prompt = FunctionalPromptDiagnosticProjector().project(
        authority,
        fixture["binding_catalog"],
        fixture["planning_context"],
    )
    prompt = FunctionalPromptDiagnostic.from_payload(prompt.to_payload())
    subjects = [item.to_payload() for item in prompt.subjects]
    assert subjects == [
        {
            "ref": "D",
            "role": "curve_point",
            "arg_name": "curve_points",
            "item_index": 1,
            "expected_type": "Point",
            "expected_state": "related_by_visible_condition",
            "observed_type": "Point",
        },
        {
            "ref": "parabola",
            "role": "curve",
            "arg_name": "quadratic",
            "item_index": 1,
            "expected_type": "QuadraticFunction",
            "expected_state": "same_condition_object",
            "observed_type": "Function",
        },
    ]
    assert prompt.repair_action == "place_step_in_relation_scope"
    wire = json.dumps(prompt.to_payload(), ensure_ascii=False)
    assert "point:problem:D" not in wire
    assert "function:problem:parabola" not in wire
    assert "condition:" not in wire


def test_sibling_private_relation_is_reported_missing_without_scope_leak(
    tmp_path,
) -> None:
    case = "tj-2026-heping-yimo-25"
    payload = json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    payload = deepcopy(payload)
    scope_ii = next(
        scope for scope in payload["scopes"] if scope["scope_id"] == "ii"
    )
    call = next(
        item
        for item in scope_ii["calls"]
        if item["call_id"] == "derive_parametric_parabola_ii"
    )
    call["args"]["curve_point"] = {"ref": "D", "kind": "point"}

    *_, reconciliation = scope_native_reconciliation_fixture(
        tmp_path,
        case=case,
        plan_payload=payload,
    )

    issue = next(
        item
        for item in reconciliation.issues
        if item.call_id == "derive_parametric_parabola_ii"
        and item.code == "functional.method_relation_missing"
    )
    assert issue.details["arg_name"] == "curve_point"
    assert issue.details["item_index"] == 0
    assert issue.details["observed_relation"] == {}
    assert "relation_owner_scopes" not in json.dumps(
        issue.to_payload(), ensure_ascii=False
    )
    assert all(
        item.call_id != "derive_parametric_parabola_ii"
        for item in reconciliation.calls
    )


def test_relation_matching_never_uses_curve_or_point_value_similarity(
    heping_yimo_relation_fixture,
) -> None:
    fixture = heping_yimo_relation_fixture
    call = fixture["call"]
    spec = fixture["inputs"].method_specs.require(
        "quadratic_from_constraints"
    )
    point = call.resolved_args["curve_points"][1]
    curve = call.resolved_args["quadratic"][0]

    wrong_curve = replace(
        curve,
        object_ref="function:problem:other",
        math_object_id=MathObjectId(
            value="function:problem:other",
            kind="function",
            origin_scope_id="problem",
        ),
    )
    mismatch = resolve_method_input_relations(
        spec,
        {"curve_point": (point,), "quadratic": (wrong_curve,)},
        call_id="wrong_curve",
        capability_id=spec.method_id,
        scope_id="i_1",
        semantic_index=fixture["semantic_index"],
    )
    assert [item.code for item in mismatch.issues] == [
        "functional.method_relation_argument_mismatch"
    ]

    same_runtime_path_new_identity = replace(
        point,
        object_ref="point:problem:D_copy",
        math_object_id=MathObjectId(
            value="point:problem:D_copy",
            kind="point",
            origin_scope_id="problem",
        ),
    )
    missing = resolve_method_input_relations(
        spec,
        {
            "curve_point": (same_runtime_path_new_identity,),
            "quadratic": (curve,),
        },
        call_id="same_value_different_identity",
        capability_id=spec.method_id,
        scope_id="i_1",
        semantic_index=fixture["semantic_index"],
    )
    assert [item.code for item in missing.issues] == [
        "functional.method_relation_missing"
    ]
