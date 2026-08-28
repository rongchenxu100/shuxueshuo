from __future__ import annotations

from copy import deepcopy
import json

from _problem_planning_support import cached_planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload
from test_functional_goal_execution import _checkpoint_steps, _execute

from shuxueshuo_server.solver.runtime.coupled_segment_path_roles import (
    build_coupled_segment_path_role_candidates,
)
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)


CASE = "tj-2026-nankai-yimo-25"
MACRO_ID = "coupled_segment_endpoint_replacement_path_minimum"
KERNEL_ID = "coupled_segment_endpoint_replacement_path_minimum_kernel"


def test_coupled_macro_public_contract_is_atomic() -> None:
    fixture = cached_planning_binding_fixture(CASE)
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    )
    capability = catalog.get(MACRO_ID)

    assert capability is not None
    assert [item.name for item in capability.args] == [
        "path_minimum_target",
        "segment_binding_relation",
    ]
    assert capability.args[1].accepted_condition_kinds == (
        "segment_relation",
        "segment_length_relation",
    )
    assert [item.name for item in capability.returns] == [
        "minimum_expression",
        "attainment_point",
    ]
    attainment = capability.returns[1]
    assert attainment.identity_arg == "moving_point"
    assert attainment.reference_mode == "exact_result"
    assert catalog.get("two_moving_points_path_reduction") is None
    assert catalog.get("broken_path_straightening_minimum_expression") is None


def test_coupled_role_search_uses_only_the_selected_public_facts() -> None:
    fixture = cached_planning_binding_fixture(CASE)
    registry = fixture[5]
    candidates = build_coupled_segment_path_role_candidates(
        path_minimum_target="fact:ii:minimum_target_0cdb0e4b1c87",
        segment_binding_relation="fact:ii:length_relation_70154fb39055",
        scope_id="ii",
        registry=registry,
    )

    assert len(candidates) == 1
    roles = candidates[0]
    assert roles.first_moving_point == "point:ii:E"
    assert roles.moving_point == "point:ii:G"
    assert roles.first_segment_start == "point:problem:D"
    assert roles.joint_point == "point:ii:M"
    assert roles.second_segment_end == "point:ii:N"
    assert roles.transformed_fixed_endpoint == "point:ii:F"
    assert build_coupled_segment_path_role_candidates(
        path_minimum_target="fact:ii:minimum_target_0cdb0e4b1c87",
        segment_binding_relation="fact:ii:midpoint_b9b70ef36bb8",
        scope_id="ii",
        registry=registry,
    ) == ()


def test_nankai_coupled_macro_executes_as_one_public_kernel(tmp_path) -> None:
    result, _fixture = _execute(
        tmp_path,
        CASE,
        load_v2_fixture_payload(CASE),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    macro_step = _checkpoint_steps(checkpoint)["ii_path_minimum"]

    assert macro_step.status == "runtime_verified"
    outputs = {
        item["return"]: item["value"] for item in macro_step.actual_outputs
    }
    assert outputs == {
        "minimum_expression": "sqrt(5*m**2 - 10*m + 10)/2",
        "attainment_point": ["m/3 + 4/3", "1 - 2*m/3"],
    }
    witnesses = [
        item for item in macro_step.evidence if isinstance(item, PathMinimumWitness)
    ]
    assert len(witnesses) == 1
    witness = witnesses[0]
    assert witness.macro_id == MACRO_ID
    assert witness.original_objective == "EG+FG"
    assert witness.reduced_objective == "DG+FG"
    assert witness.minimizing_points == {
        "point:ii:G": ("m/3 + 4/3", "1 - 2*m/3")
    }

    report = result.replay.transactional_attempt_result.execution_report
    call_result = next(
        item for item in report.call_results if item.call_id == "ii_path_minimum"
    )
    assert len(call_result.step_results) == 1
    assert call_result.step_results[0].methods_used == [KERNEL_ID]

    public_projection = json.dumps(
        {
            "outputs": [dict(item) for item in macro_step.actual_outputs],
            "evidence": [item.to_payload() for item in witnesses],
        },
        ensure_ascii=False,
    )
    assert "#coupled-segment-reflection" not in public_projection
    assert "PointRef" not in public_projection


def test_missing_constructed_endpoint_requests_its_owner_scope(tmp_path) -> None:
    payload = deepcopy(load_v2_fixture_payload(CASE))
    scope_ii = next(
        scope
        for scope in payload["root_scope"]["children"]
        if scope["scope_ref"] == "ii"
    )
    scope_ii["steps"] = [
        item for item in scope_ii["steps"] if item["step_id"] != "ii_compute_F"
    ]

    result, _fixture = _execute(tmp_path, CASE, payload)

    assert result.checkpoint is not None
    failed = _checkpoint_steps(result.checkpoint)["ii_path_minimum"]
    assert failed.status == "authority_invalid"
    assert failed.typed_issue is not None
    assert failed.typed_issue["code"] == (
        "functional.coupled_segment_path_state_unavailable"
    )
    assert failed.typed_issue["repair_action"] == (
        "materialize_constructed_point_before_macro"
    )
    assert failed.typed_issue["expected"]["required_scope_ref"] == "ii"
