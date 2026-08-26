from __future__ import annotations

import json
from pathlib import Path

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import (
    MethodInputSpec,
    MethodInputViewSpec,
    PointRef,
    TypedValue,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.method_input_views import (
    MethodInputViewResolver,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    EntityIdentityReadSource,
    MethodInputReadAuthority,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import method_spec_payloads


REPO_ROOT = Path(__file__).resolve().parents[3]
NANKAI_FIXTURE = (
    REPO_ROOT / "internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
)


def _input(
    *,
    name: str,
    domain_type: str,
    runtime_type: str,
    mode: str,
    object_kind: str | None = None,
    state_kind: str | None = None,
) -> MethodInputSpec:
    return MethodInputSpec(
        name=name,
        domain_type=domain_type,
        runtime_type=runtime_type,
        view=MethodInputViewSpec(
            mode=mode,
            domain_type=domain_type,
            object_kind=object_kind,
            state_kind=state_kind,
        ),
    )


def test_all_method_inputs_declare_one_explicit_view() -> None:
    registry = MethodSpecRegistry.load_from_code()

    assert len(registry.specs) == 48
    assert "certify_minimum_expression" in registry.specs
    inputs = tuple(
        item
        for spec in registry.specs.values()
        for item in spec.inputs.values()
    )
    assert len(inputs) == 257
    assert {item.view.mode for item in inputs} == {
        "identity",
        "latest_state",
        "immutable_value",
        "exact_result",
    }
    assert all(item.domain_type == item.view.domain_type for item in inputs)
    assert all(item.runtime_type for item in inputs)

    intersection = registry.specs["line_intersection_point"]
    assert all(
        intersection.inputs[name].allows_anonymous_result
        for name in ("line1_p1", "line1_p2", "line2_p1", "line2_p2")
    )
    line_parabola = registry.specs[
        "line_parabola_second_intersection_point"
    ]
    assert all(
        line_parabola.inputs[name].allows_anonymous_result
        for name in ("line_p1", "line_p2")
    )


def test_interchangeable_method_inputs_have_symmetric_executable_contracts() -> None:
    registry = MethodSpecRegistry.load_from_code()
    expected = {
        "distance_between_points": (("p1", "p2"),),
        "line_intersection_point": (
            ("line1_p1", "line1_p2"),
            ("line2_p1", "line2_p2"),
        ),
        "line_locus_minimum_point": (
            ("minimum_point_1", "minimum_point_2"),
        ),
        "line_parabola_second_intersection_point": (
            ("line_p1", "line_p2"),
        ),
        "midpoint_point": (("p1", "p2"),),
        "parameter_from_segment_length": (
            ("p1", "p2"),
            ("reference_p1", "reference_p2"),
        ),
        "reflect_point_across_line": (("line_p1", "line_p2"),),
        "square_opposite_point": (("adjacent1", "adjacent2"),),
    }

    assert {
        method_id: spec.interchangeable_arg_groups
        for method_id, spec in registry.specs.items()
        if spec.interchangeable_arg_groups
    } == expected
    for spec in registry.specs.values():
        for group in spec.interchangeable_arg_groups:
            signatures = {
                (
                    spec.inputs[name].domain_type,
                    spec.inputs[name].runtime_type,
                    spec.inputs[name].view,
                    spec.inputs[name].required,
                    spec.inputs[name].functional_exposed,
                    spec.inputs[name].allows_anonymous_result,
                    spec.inputs[name].allows_empty_collection,
                )
                for name in group
            }
            assert len(signatures) == 1, (spec.method_id, group)


def test_generated_method_specs_preserve_view_contracts() -> None:
    generated = {
        item["method_id"]: item
        for item in method_spec_payloads()
    }
    snapshots = {
        payload["method_id"]: payload
        for path in (REPO_ROOT / "internal/method-specs").glob("*.json")
        for payload in (json.loads(path.read_text(encoding="utf-8")),)
    }

    assert snapshots == generated
    assert all(
        set(input_payload) >= {"domain_type", "runtime_type", "view"}
        for method in generated.values()
        for input_payload in method["inputs"].values()
    )


def test_same_point_entity_resolves_identity_or_latest_state_by_contract() -> None:
    context = ContextBuilder().build(load_problem_ir(str(NANKAI_FIXTURE)))
    resolver = MethodInputViewResolver()

    identity = resolver.resolve(
        context,
        method_id="synthetic_identity",
        invocation_id="identity",
        scope_id="i",
        input_name="point",
        input_spec=_input(
            name="point",
            domain_type="Point",
            runtime_type="PointRef",
            mode="identity",
            object_kind="point",
        ),
        raw_path="$problem.points.D",
    )
    latest = resolver.resolve(
        context,
        method_id="synthetic_latest",
        invocation_id="latest",
        scope_id="i",
        input_name="point",
        input_spec=_input(
            name="point",
            domain_type="Point",
            runtime_type="Point",
            mode="latest_state",
            object_kind="point",
            state_kind="coordinate",
        ),
        raw_path="$problem.points.D",
    )

    assert isinstance(identity.value, PointRef)
    assert identity.value.name == "D"
    assert latest.typed_value.type == "Point"
    assert latest.value == (sp.Integer(1), sp.Integer(0))


def test_hidden_point_ref_identity_recovers_entity_from_point_state() -> None:
    context = ContextBuilder().build(load_problem_ir(str(NANKAI_FIXTURE)))
    runtime_path = "$question.i.outputs.synthetic_D_coordinate"
    context.write_path(
        runtime_path,
        TypedValue("Point", (sp.Integer(1), sp.Integer(0))),
        from_scope_id="i",
    )
    input_spec = _input(
        name="target_ref",
        domain_type="PointRef",
        runtime_type="PointRef",
        mode="identity",
        object_kind="point",
    )

    identity = MethodInputViewResolver().resolve(
        context,
        method_id="synthetic_hidden_identity",
        invocation_id="hidden_identity",
        scope_id="i",
        input_name="target_ref",
        input_spec=input_spec,
        raw_path=runtime_path,
        authority=MethodInputReadAuthority(
            method_id="synthetic_hidden_identity",
            invocation_id="hidden_identity",
            input_name="target_ref",
            item_index=0,
            view_mode="identity",
            domain_type="PointRef",
            runtime_type="PointRef",
            scope_id="i",
            source=EntityIdentityReadSource(
                "point:problem:D",
                runtime_path,
            ),
        ),
        require_authority=True,
    )

    assert identity.typed_value.type == "Point"
    assert isinstance(identity.value, PointRef)
    assert identity.value.name == "D"


def test_point_coordinate_fact_is_the_latest_point_state_without_reconstruction() -> None:
    context = ContextBuilder().build(load_problem_ir(str(NANKAI_FIXTURE)))
    resolver = MethodInputViewResolver()
    m = context.symbols["m"]

    latest = resolver.resolve(
        context,
        method_id="synthetic_latest",
        invocation_id="latest_M",
        scope_id="ii",
        input_name="point",
        input_spec=_input(
            name="point",
            domain_type="Point",
            runtime_type="Point",
            mode="latest_state",
            object_kind="point",
            state_kind="coordinate",
        ),
        raw_path="$question.ii.points.M",
    )

    assert latest.typed_value.type == "Point"
    assert latest.value == (m, sp.Integer(1))


def test_symbol_entity_resolves_identity_or_known_value_by_contract() -> None:
    context = ContextBuilder().build(load_problem_ir(str(NANKAI_FIXTURE)))
    resolver = MethodInputViewResolver()

    identity = resolver.resolve(
        context,
        method_id="symbol_identity",
        invocation_id="symbol_identity",
        scope_id="i",
        input_name="parameter",
        input_spec=_input(
            name="parameter",
            domain_type="Symbol",
            runtime_type="Symbol",
            mode="identity",
            object_kind="symbol",
        ),
        raw_path="$problem.symbols.a",
    )
    latest = resolver.resolve(
        context,
        method_id="symbol_latest",
        invocation_id="symbol_latest",
        scope_id="i",
        input_name="parameter",
        input_spec=_input(
            name="parameter",
            domain_type="Symbol",
            runtime_type="ParameterValue",
            mode="latest_state",
            object_kind="symbol",
            state_kind="value",
        ),
        raw_path="$question.i.parameter_values.a",
    )

    assert identity.typed_value.type == "Symbol"
    assert identity.value == context.symbols["a"]
    assert latest.typed_value.type == "ParameterValue"
    assert latest.value == 2


def test_exact_result_reads_only_the_explicit_result_path() -> None:
    context = ContextBuilder().build(load_problem_ir(str(NANKAI_FIXTURE)))
    context.ensure_step_scope("producer", "ii")
    context.write_path(
        "$step.producer.outputs.path_witness",
        TypedValue(
            "PathTransformation",
            {"type": "test_witness"},
            source="test",
        ),
        from_scope_id="producer",
    )

    resolved = MethodInputViewResolver().resolve(
        context,
        method_id="consume_witness",
        invocation_id="consume_witness",
        scope_id="producer",
        input_name="path_witness",
        input_spec=_input(
            name="path_witness",
            domain_type="PathWitness",
            runtime_type="PathTransformation",
            mode="exact_result",
        ),
        raw_path="$step.producer.outputs.path_witness",
    )

    assert resolved.selected_path == "$step.producer.outputs.path_witness"
    assert resolved.value == {"type": "test_witness"}


def test_view_resolution_rejects_sibling_state() -> None:
    context = ContextBuilder().build(load_problem_ir(str(NANKAI_FIXTURE)))
    context.write_path(
        "$subquestion.ii_2.points.private",
        TypedValue("Point", (sp.Integer(2), sp.Integer(3)), source="test"),
        from_scope_id="ii_2",
    )

    with pytest.raises(Exception) as exc_info:
        MethodInputViewResolver().resolve(
            context,
            method_id="sibling_read",
            invocation_id="sibling_read",
            scope_id="ii_1",
            input_name="point",
            input_spec=_input(
                name="point",
                domain_type="Point",
                runtime_type="Point",
                mode="latest_state",
            ),
            raw_path="$subquestion.ii_2.points.private",
        )

    assert getattr(exc_info.value, "code", None) == (
        "functional.method_input_state_unavailable"
    )
