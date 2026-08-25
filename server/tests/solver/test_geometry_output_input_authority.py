from __future__ import annotations

import pytest

from shuxueshuo_server.solver.contracts import (
    ExactCallResultSourceSpec,
    LatestStateSourceSpec,
    MethodInputBindingSpec,
    PreviousOutputIdentityDerivationSpec,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CallResultReadSource,
    EntityIdentityReadSource,
)

from test_functional_transaction_execution import _replay


pytestmark = pytest.mark.solver_contract


_OUTPUT_IDENTITIES = {
    ("axis_intercept_from_equal_acute_angles", "target"): "point",
    ("line_intersection_point", "target"): "intersection",
    ("line_locus_minimum_point", "target"): "point",
    ("line_parabola_second_intersection_point", "target"): "point",
    ("midpoint_point", "target"): "midpoint",
    ("point_on_parabola_at_x", "target"): "point",
    ("quadratic_axis_from_relation", "target"): "axis_point",
    ("quadratic_axis_parameterized_point", "target"): "point",
    ("quadratic_axis_x_intercept_point", "target"): "axis_point",
    ("quadratic_vertex_point", "target"): "point",
    ("quadratic_x_axis_intercept_point", "target"): "point",
    ("quadratic_y_axis_intercept_point", "target"): "point",
    ("square_adjacent_vertex_from_side", "target"): "adjacent_vertex",
    ("translated_point", "target"): "point",
    (
        "weighted_axis_path_triangle_transform",
        "auxiliary_point_ref",
    ): "auxiliary_point",
}


def _binding(method_id: str, input_name: str) -> MethodInputBindingSpec:
    matches = {
        binding
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        if rule.method_id == method_id
        for binding in rule.input_bindings
        if binding.input_name == input_name
        and isinstance(binding, MethodInputBindingSpec)
    }
    assert len(matches) == 1
    return next(iter(matches))


def test_every_geometry_output_identity_names_a_real_return_role() -> None:
    observed = {}
    for key in _OUTPUT_IDENTITIES:
        binding = _binding(*key)
        assert isinstance(
            binding.derivation,
            PreviousOutputIdentityDerivationSpec,
        )
        observed[key] = binding.derivation.output_name

    assert observed == _OUTPUT_IDENTITIES


def test_point_transition_state_is_separate_from_output_identity() -> None:
    identity = _binding("quadratic_x_axis_intercept_point", "target")
    state = _binding("quadratic_x_axis_intercept_point", "target_state")

    assert isinstance(
        identity.derivation,
        PreviousOutputIdentityDerivationSpec,
    )
    assert isinstance(state.source, LatestStateSourceSpec)
    assert state.source.entity_arg == "target"
    assert not state.required


def test_relation_and_point_producer_share_one_allocated_identity() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    identities = []
    for call_id in ("derive_equal_angle_i", "derive_axis_intercept_F_i"):
        compiled = next(item for item in report.compiled_calls if item.call_id == call_id)
        invocation = compiled.replay_plans[0].invocations[0]
        authority = invocation.input_read_authorities["target"][0]
        assert isinstance(authority.source, EntityIdentityReadSource)
        identities.append(authority.source.entity_handle)

    assert identities == [
        "point:i_2:derive_axis_intercept_F_i_point",
        "point:i_2:derive_axis_intercept_F_i_point",
    ]


def test_anonymous_straightening_endpoints_keep_two_exact_result_slots() -> None:
    first = _binding("line_locus_minimum_point", "minimum_point_1")
    second = _binding("line_locus_minimum_point", "minimum_point_2")
    assert isinstance(first.source, ExactCallResultSourceSpec)
    assert isinstance(second.source, ExactCallResultSourceSpec)

    replay = _replay("heping-ermo", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "derive_minimum_point_G_ii"
    )
    invocation = compiled.replay_plans[0].invocations[0]
    sources = tuple(
        invocation.input_read_authorities[name][0].source
        for name in ("minimum_point_1", "minimum_point_2")
    )

    assert all(isinstance(item, CallResultReadSource) for item in sources)
    assert {item.call_id for item in sources} == {"derive_path_minimum_ii"}
    assert [item.return_name for item in sources] == [
        "straightened_endpoint_1",
        "straightened_endpoint_2",
    ]
    assert sources[0].runtime_path != sources[1].runtime_path


def test_c3_geometry_inputs_never_lower_through_compiler_selector() -> None:
    c3_inputs = set(_OUTPUT_IDENTITIES) | {
        ("angle_sum_equal_angle_candidates", "target"),
        ("line_locus_minimum_point", "minimum_point_1"),
        ("line_locus_minimum_point", "minimum_point_2"),
        ("quadratic_x_axis_intercept_point", "known_point"),
        ("quadratic_x_axis_intercept_point", "target_state"),
        ("right_angle_equal_length_candidates", "target"),
        ("square_adjacent_vertex_from_side", "parameter"),
    }
    checked = 0
    for case_id in ("heping", "heping-ermo", "hexi", "nankai", "xiqing"):
        replay = _replay(case_id, mode="context_authoritative")
        report = replay.transactional_execution_report
        assert report is not None
        for compiled in report.compiled_calls:
            for plan in compiled.replay_plans:
                for invocation in plan.invocations:
                    for input_name, authorities in (
                        invocation.input_read_authorities.items()
                    ):
                        if (invocation.method_id, input_name) not in c3_inputs:
                            continue
                        checked += len(authorities)
                        assert all(
                            authority.source.kind != "compiler_selector"
                            for authority in authorities
                        )

    assert checked >= 30
