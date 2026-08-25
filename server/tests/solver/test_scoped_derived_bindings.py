from __future__ import annotations

import pytest

from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanAuthorityAdapter,
    ScopedFunctionalPlanError,
    ScopedFunctionalPlanValidator,
)

from _problem_planning_support import planning_binding_fixture
from _scoped_functional_plan_support import load_v3_fixture_payload


pytestmark = pytest.mark.solver_contract


def _scope(root, scope_ref):
    if root["scope_ref"] == scope_ref:
        return root
    for child in root.get("children", []):
        try:
            return _scope(child, scope_ref)
        except KeyError:
            pass
    raise KeyError(scope_ref)


def _authority(tmp_path, payload):
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


def test_default_derived_binding_has_stable_scope_local_identity(tmp_path) -> None:
    authority = _authority(
        tmp_path,
        load_v3_fixture_payload("tj-2026-heping-ermo-25"),
    )
    step = next(
        item
        for item in authority.scoped_plan.steps
        if item.step_id == "derive_locus_G_ii"
    )
    binding = step.return_bindings["line"]
    lowered = next(
        item
        for item in authority.lowered_plan.calls
        if item.call_id == step.step_id
    )

    assert binding.kind == "derived"
    assert binding.naming_origin == "default"
    assert binding.ref == "derive_locus_G_ii.line"
    assert lowered.return_bindings["line"].from_step == step.step_id


def test_derived_name_cannot_shadow_visible_problem_entity(tmp_path) -> None:
    payload = load_v3_fixture_payload("tj-2026-heping-ermo-25")
    scope = _scope(payload["root_scope"], "ii")
    producer = next(
        item
        for item in scope["goals"][0]["steps"]
        if item["step_id"] == "derive_locus_G_ii"
    )
    producer["return_bindings"] = {
        "line": {"kind": "derived", "ref": "A"}
    }

    with pytest.raises(ScopedFunctionalPlanError, match="conflicts"):
        _authority(tmp_path, payload)


def test_derived_forward_reference_is_rejected_before_runtime(tmp_path) -> None:
    payload = load_v3_fixture_payload("tj-2026-heping-ermo-25")
    steps = _scope(payload["root_scope"], "ii")["goals"][0]["steps"]
    producer_index = next(
        index
        for index, item in enumerate(steps)
        if item["step_id"] == "derive_locus_G_ii"
    )
    producer = steps.pop(producer_index)
    consumer_index = next(
        index
        for index, item in enumerate(steps)
        if item["step_id"] == "derive_path_minimum_ii"
    )
    steps[consumer_index]["args"]["moving_locus"] = (
        "derive_locus_G_ii.line"
    )
    steps.insert(consumer_index + 1, producer)

    with pytest.raises(ScopedFunctionalPlanError, match="used before"):
        _authority(tmp_path, payload)
