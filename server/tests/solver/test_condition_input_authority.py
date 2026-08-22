from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.condition_binding_authority import (
    ConditionBindingAuthority,
    ConditionBindingAuthorityError,
    ConditionBindingAuthorityIndex,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CallResultReadSource,
    ConditionReadSource,
    MethodInputReadAuthority,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    MathObjectRegistry,
)

from _problem_planning_support import cached_planning_binding_fixture
from test_functional_transaction_execution import _replay


def _condition_index(case: str) -> ConditionBindingAuthorityIndex:
    (
        _bundle,
        _planning_context,
        _problem,
        _inputs,
        _problem_payload,
        handle_registry,
        planner_context,
        binding_catalog,
    ) = cached_planning_binding_fixture(case)
    object_registry = MathObjectRegistry.from_sources(
        handle_registry,
        math_objects=planner_context.state.math_objects,
    )
    return ConditionBindingAuthorityIndex.from_context(
        planner_context,
        object_registry=object_registry,
        problem_binding_catalog=binding_catalog,
    )


def _object_id(
    index: ConditionBindingAuthorityIndex,
    ref: str,
) -> MathObjectId:
    result = index.object_id_for_ref(ref)
    assert result is not None, ref
    return result


def test_explicit_problem_fact_has_one_exact_source_condition_authority() -> None:
    index = _condition_index("tj-2026-nankai-yimo-25")
    authority = next(
        item
        for item in index.authorities
        if item.source_ref == "coefficient_relation_a_b"
    )

    assert index.require(authority.condition_id) is authority
    assert authority.condition_kind == "coefficient_relation"
    assert authority.owner_scope_id == "problem"
    assert authority.runtime_handle == "fact:problem:equation_43b253c6c618"
    assert authority.source_unit_ids


def test_related_condition_resolution_is_lexical_and_role_typed() -> None:
    index = _condition_index("tj-2026-nankai-yimo-25")
    midpoint = index.resolve_relation(
        condition_kinds=("midpoint_definition",),
        related_object_ids=(
            _object_id(index, "D"),
            _object_id(index, "N"),
        ),
        scope_id="ii",
    )

    assert midpoint.source_ref == "midpoint_definition_d_n_f"
    assert dict(midpoint.object_role_refs)["midpoint"] == ("point:ii:F",)
    assert dict(midpoint.object_role_refs)["p1"] == ("point:problem:D",)
    assert dict(midpoint.object_role_refs)["p2"] == ("point:ii:N",)


def test_condition_alias_and_parameter_symbol_identity_are_canonical() -> None:
    index = _condition_index("tj-2026-nankai-yimo-25")
    length = index.resolve_relation(
        condition_kinds=("segment_length_relation",),
        related_object_ids=(
            _object_id(index, "M"),
            _object_id(index, "N"),
        ),
        scope_id="ii_1",
    )
    parameter_constraint = index.resolve_relation(
        condition_kinds=("dynamic_constraint",),
        related_object_ids=(_object_id(index, "m"),),
        scope_id="ii_2",
    )

    assert length.condition_kind == "length_squared"
    assert length.source_ref == "length_squared_mn"
    assert parameter_constraint.condition_kind == "symbol_constraint"
    assert parameter_constraint.source_ref == "symbol_constraint_m"


def test_sibling_or_descendant_condition_is_not_visible() -> None:
    index = _condition_index("tj-2026-nankai-yimo-25")

    with pytest.raises(ConditionBindingAuthorityError) as error:
        index.resolve_relation(
            condition_kinds=("symbol_constraint",),
            related_object_ids=(_object_id(index, "m"),),
            scope_id="problem",
        )

    assert error.value.code == "functional.method_input_condition_not_visible"
    assert error.value.details["candidate_owner_scopes"] == ["ii"]


def test_multiple_visible_conditions_are_never_selected_by_order() -> None:
    index = _condition_index("tj-2026-nankai-yimo-25")

    with pytest.raises(ConditionBindingAuthorityError) as error:
        index.resolve_relation(
            condition_kinds=("point_on_curve",),
            related_object_ids=(_object_id(index, "parabola"),),
            scope_id="ii",
        )

    assert error.value.code == "functional.method_input_condition_ambiguous"
    assert set(error.value.details["candidate_refs"]) == {
        "C",
        "point_on_curve_parabola_m",
        "point_on_curve_parabola_n",
    }


@pytest.mark.parametrize(
    ("case", "condition_kind", "source_ref", "required_roles"),
    (
        (
            "tj-2026-heping-yimo-25",
            "angle_sum",
            "angle_sum",
            {"origin", "reference_x_axis_point", "x_axis_point", "y_axis_point"},
        ),
        (
            "tj-2026-nankai-yimo-25",
            "right_angle_equal_length",
            "right_angle_equal_length_m_d_n_dm_dn",
            {"anchor", "endpoint"},
        ),
        (
            "tj-2026-heping-ermo-25",
            "square",
            "square_ae_a_e_k_g",
            {"vertex", "vertex_1", "vertex_2", "vertex_3", "vertex_4"},
        ),
    ),
)
def test_structured_geometry_conditions_preserve_canonical_roles(
    case: str,
    condition_kind: str,
    source_ref: str,
    required_roles: set[str],
) -> None:
    authority = next(
        item
        for item in _condition_index(case).authorities
        if item.condition_kind == condition_kind and item.source_ref == source_ref
    )

    assert required_roles.issubset(dict(authority.object_roles))


def test_recorded_fact_and_role_inputs_use_typed_read_authority() -> None:
    replay = _replay("nankai", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item for item in report.compiled_calls if item.call_id == "ii_reduce_path"
    )
    invocation = next(
        invocation
        for plan in compiled.plans
        for invocation in plan.invocations
        if invocation.method_id == "two_moving_points_path_reduction"
    )

    assert {
        name: authorities[0].source.condition_id
        for name, authorities in invocation.input_read_authorities.items()
        if isinstance(authorities[0].source, ConditionReadSource)
    } == {
        "original_path": "condition:minimum_target_0cdb0e4b1c87@ii",
        "binding_relation": "condition:length_relation_70154fb39055@ii",
        "first_moving_membership": (
            "condition:point_on_segment_5d1a87767221@ii"
        ),
        "second_moving_membership": (
            "condition:point_on_segment_132a8609a697@ii"
        ),
    }
    assert all(
        authority.source.kind != "compiler_selector"
        for authorities in invocation.input_read_authorities.values()
        for authority in authorities
    )


def test_produced_condition_and_linked_roles_keep_exact_producer_authority() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "derive_axis_intercept_F_i"
    )
    invocation = next(
        invocation
        for plan in compiled.plans
        for invocation in plan.invocations
        if invocation.method_id == "axis_intercept_from_equal_acute_angles"
    )
    equality_source = invocation.input_read_authorities["angle_equality"][0].source

    assert isinstance(equality_source, CallResultReadSource)
    assert equality_source.call_id == "derive_equal_angle_i"
    assert equality_source.return_name == "angle_equality"
    assert {
        name for name in invocation.input_read_authorities if name != "target"
    } == {
        "angle_equality",
        "origin",
        "reference_x_axis_point",
        "x_axis_point",
        "y_axis_point",
    }


def test_condition_read_authority_round_trip_pins_exact_condition_without_scan() -> None:
    replay = _replay("nankai", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    authority = next(
        authority
        for compiled in report.compiled_calls
        for plan in compiled.plans
        for invocation in plan.invocations
        for authorities in invocation.input_read_authorities.values()
        for authority in authorities
        if isinstance(authority.source, ConditionReadSource)
    )

    restored = MethodInputReadAuthority.from_payload(
        authority.authority_payload()
    )

    assert restored == authority
    assert restored.source.condition_id == authority.source.condition_id
    assert restored.authority_signature == authority.authority_signature


def test_condition_index_rejects_duplicate_condition_authority() -> None:
    first = ConditionBindingAuthority(
        condition_id="condition:test@problem",
        source_ref="fact_a",
        condition_kind="square",
        owner_scope_id="problem",
        valid_scope_id="problem",
        object_roles=(),
        object_role_refs=(),
        runtime_type="Condition",
        runtime_handle="$problem.conditions.fact_a",
    )
    second = ConditionBindingAuthority(
        condition_id=first.condition_id,
        source_ref="fact_b",
        condition_kind=first.condition_kind,
        owner_scope_id=first.owner_scope_id,
        valid_scope_id=first.valid_scope_id,
        object_roles=(),
        object_role_refs=(),
        runtime_type=first.runtime_type,
        runtime_handle="$problem.conditions.fact_b",
    )

    with pytest.raises(ConditionBindingAuthorityError) as error:
        ConditionBindingAuthorityIndex(
            (first, second),
            scope_parent_ids={"problem": None},
            object_ids_by_ref={},
        )

    assert error.value.code == "planner.method_input_view_authority_drift"
