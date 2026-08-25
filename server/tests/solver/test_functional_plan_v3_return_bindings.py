from __future__ import annotations

from copy import deepcopy

import pytest

from shuxueshuo_server.solver.contracts import FunctionalReturnNamingSpec
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    SCOPED_FUNCTIONAL_PLAN_CONTRACT,
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanValidator,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


pytestmark = pytest.mark.solver_contract


def _scopes(root):
    yield root
    for child in root.get("children", []):
        yield from _scopes(child)


def _steps(payload):
    for scope in _scopes(payload["root_scope"]):
        yield from scope.get("steps", [])
        for goal in scope.get("goals", []):
            yield from goal.get("steps", [])


def _lower(tmp_path, payload):
    fixture = planning_binding_fixture(
        tmp_path,
        case="tj-2026-heping-ermo-25",
    )
    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )
    assert report.ok and plan is not None, report.to_payload()
    return ScopedFunctionalPlanAuthorityAdapter().lower(
        plan,
        planning_context=fixture[1],
        binding_catalog=fixture[7],
        capability_catalog=FunctionalCapabilityCatalog.from_family_spec(
            fixture[3].family_spec,
            fixture[3].method_specs,
        ),
    )


def test_return_naming_contract_owns_deterministic_default_ref() -> None:
    naming = FunctionalReturnNamingSpec(
        mode="optional_default",
        default_name="point",
    )

    assert naming.default_ref("construct_G") == "construct_G.point"
    assert FunctionalReturnNamingSpec.from_payload(
        naming.to_payload()
    ) == naming
    with pytest.raises(ValueError, match="requires default_name"):
        FunctionalReturnNamingSpec(mode="optional_default")
    with pytest.raises(ValueError, match="must not declare default_name"):
        FunctionalReturnNamingSpec(mode="anonymous", default_name="value")


def test_explicit_derived_binding_is_visible_to_later_steps_in_same_pass(
    tmp_path,
) -> None:
    payload = load_v3_fixture_payload("tj-2026-heping-ermo-25")
    producer = next(
        item for item in _steps(payload) if item["step_id"] == "derive_locus_G_ii"
    )
    producer["return_bindings"] = {
        "line": {"kind": "derived", "ref": "G_line"}
    }
    for consumer in _steps(payload):
        if consumer["step_id"] in {
            "derive_path_minimum_ii",
            "derive_minimum_point_G_ii",
        }:
            consumer["args"]["moving_locus"] = "G_line"

    authority = _lower(tmp_path, payload)
    canonical = authority.scoped_plan.to_payload()
    canonical_producer = next(
        item
        for item in _steps(canonical)
        if item["step_id"] == "derive_locus_G_ii"
    )
    lowered_consumer = next(
        item
        for item in authority.lowered_plan.calls
        if item.call_id == "derive_path_minimum_ii"
    )

    assert canonical_producer["return_bindings"] == {
        "line": {"kind": "derived", "ref": "G_line"}
    }
    assert lowered_consumer.args["moving_locus"][0].from_call == (
        "derive_locus_G_ii"
    )


def test_answer_return_does_not_materialize_a_second_derived_name(tmp_path) -> None:
    payload = load_v3_fixture_payload("tj-2026-heping-ermo-25")
    authority = _lower(tmp_path, payload)
    canonical = authority.scoped_plan.to_payload()
    answer_producer = next(
        item for item in _steps(canonical) if item["step_id"] == "derive_vertex_P_i"
    )

    assert canonical["format"] == SCOPED_FUNCTIONAL_PLAN_CONTRACT
    assert "return_bindings" not in answer_producer


def test_v2_output_target_field_is_rejected_by_v3_wire() -> None:
    payload = deepcopy(
        load_v3_fixture_payload("tj-2026-heping-ermo-25")
    )
    step = next(iter(_steps(payload)))
    step["output_targets"] = {"parabola": "parabola"}

    plan, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
        payload
    )

    assert plan is None
    assert any(
        "output_targets" in str(issue.to_payload()) for issue in report.issues
    )
