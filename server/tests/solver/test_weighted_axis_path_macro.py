from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from _problem_planning_support import cached_planning_binding_fixture
from _scoped_functional_plan_support import load_v2_fixture_payload
from test_functional_goal_execution import _checkpoint_steps, _execute

from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    PathMinimumWitness,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.weighted_axis_path_roles import (
    WeightedAxisPathRoleError,
    build_weighted_axis_path_role_candidates,
)


MACRO_ID = "weighted_axis_path_minimum"
KERNEL_ID = "weighted_axis_path_minimum_kernel"
HEXI = "tj-2026-hexi-yimo-25"
XIQING = "tj-2026-xiqing-yimo-25"


@pytest.mark.parametrize("case", (HEXI, XIQING))
def test_weighted_macro_public_contract_is_one_input_one_output(case) -> None:
    fixture = cached_planning_binding_fixture(case)
    catalog = FunctionalCapabilityCatalog.from_family_spec(
        fixture[3].family_spec,
        fixture[3].method_specs,
    )
    capability = catalog.get(MACRO_ID)

    assert capability is not None
    assert [item.name for item in capability.args] == [
        "path_minimum_target"
    ]
    assert [item.name for item in capability.returns] == [
        "minimum_expression"
    ]
    assert catalog.get("weighted_axis_path_triangle_transform") is None
    assert catalog.get("linked_broken_path_minimum_expression") is None


@pytest.mark.parametrize(
    ("case", "scope_id", "expected"),
    (
        (
            HEXI,
            "iii",
            {
                "curve_point": "point:iii:M",
                "moving_point": "point:iii:N",
                "fixed_point": "point:iii:A",
                "parameter": "symbol:problem:b",
                "dynamic_parameter": "symbol:iii:n",
                "weight_expression": "sqrt(2)",
                "geometry_profile_id": "sqrt2_right_isosceles",
            },
        ),
        (
            XIQING,
            "ii_2",
            {
                "curve_point": "point:ii:D",
                "moving_point": "point:ii_2:M",
                "fixed_point": "point:problem:A",
                "parameter": "symbol:problem:b",
                "dynamic_parameter": "symbol:ii_2:m",
                "weight_expression": "2",
                "geometry_profile_id": "weight2_30_60",
            },
        ),
    ),
)
def test_weighted_roles_come_from_typed_path_structure(
    case,
    scope_id,
    expected,
) -> None:
    registry = cached_planning_binding_fixture(case)[5]
    path_targets = tuple(
        handle
        for handle, fact_type in registry.fact_types.items()
        if fact_type == "path_minimum_target"
        and registry.handle_valid_scopes.get(handle) == scope_id
    )

    assert len(path_targets) == 1
    candidates = build_weighted_axis_path_role_candidates(
        path_minimum_target=path_targets[0],
        scope_id=scope_id,
        registry=registry,
    )

    assert len(candidates) == 1
    payload = candidates[0].to_payload()
    assert {key: payload[key] for key in expected} == expected


@pytest.mark.parametrize(
    ("case", "step_id", "expected_expression", "moving_point"),
    (
        (
            HEXI,
            "derive_weighted_minimum_iii",
            (
                "Piecewise((3*b/2 + 9/4, b > 1/2), "
                "(sqrt(40*b**2 + 56*b + 26)/4 + 1, True))"
            ),
            "point:iii:N",
        ),
        (
            XIQING,
            "derive_weighted_minimum_ii",
            "b + sqrt(3)*b + 3 + 3*sqrt(3)",
            "point:ii_2:M",
        ),
    ),
)
def test_weighted_macro_executes_as_one_public_kernel(
    tmp_path,
    case,
    step_id,
    expected_expression,
    moving_point,
) -> None:
    result, _fixture = _execute(
        tmp_path,
        case,
        load_v2_fixture_payload(case),
    )
    checkpoint = result.checkpoint
    assert checkpoint is not None
    macro_step = _checkpoint_steps(checkpoint)[step_id]

    assert macro_step.status == "runtime_verified"
    assert [dict(item) for item in macro_step.actual_outputs] == [
        {
            "return": "minimum_expression",
            "runtime_type": "MinimumExpression",
            "value": expected_expression,
        }
    ]
    witnesses = [
        item
        for item in macro_step.evidence
        if isinstance(item, PathMinimumWitness)
    ]
    assert len(witnesses) == 1
    witness = witnesses[0]
    assert witness.macro_id == MACRO_ID
    assert tuple(witness.minimizing_points) == (moving_point,)

    report = result.replay.transactional_attempt_result.execution_report
    call_result = next(
        item for item in report.call_results if item.call_id == step_id
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
    assert "#weighted-axis-triangle" not in public_projection
    assert "PointRef" not in public_projection
    assert "PathTransformation" not in public_projection


def test_unregistered_weight_fails_during_structural_role_resolution() -> None:
    fixture = cached_planning_binding_fixture(XIQING)
    registry = fixture[5]
    path_target = next(
        handle
        for handle, fact_type in registry.fact_types.items()
        if fact_type == "path_minimum_target"
        and registry.handle_valid_scopes.get(handle) == "ii_2"
    )
    fact_payloads = dict(registry.fact_payloads)
    target_payload = deepcopy(fact_payloads[path_target])
    target_payload["terms"][0]["scale"] = "3"
    fact_payloads[path_target] = target_payload
    unsupported = replace(registry, fact_payloads=fact_payloads)

    with pytest.raises(WeightedAxisPathRoleError) as error:
        build_weighted_axis_path_role_candidates(
            path_minimum_target=path_target,
            scope_id="ii_2",
            registry=unsupported,
        )

    assert error.value.code == "weight_unsupported"


def test_missing_curve_endpoint_state_is_one_macro_diagnostic(tmp_path) -> None:
    payload = deepcopy(load_v2_fixture_payload(HEXI))

    def remove_step(scope) -> None:
        for goal in scope.get("goals", ()):  # pragma: no branch - tiny fixture
            goal["steps"] = [
                item
                for item in goal.get("steps", ())
                if item["step_id"] != "derive_curve_point_iii"
            ]
        for child in scope.get("children", ()):
            remove_step(child)

    remove_step(payload["root_scope"])
    result, _fixture = _execute(tmp_path, HEXI, payload)

    assert result.checkpoint is not None
    failed = _checkpoint_steps(result.checkpoint)[
        "derive_weighted_minimum_iii"
    ]
    assert failed.status == "authority_invalid"
    assert failed.typed_issue is not None
    assert failed.typed_issue["code"] == (
        "functional.weighted_axis_path.state_unavailable"
    )
    assert failed.typed_issue["subjects"] == [
        {"ref": "M", "role": "curve_point"}
    ]
    assert failed.typed_issue["expected"]["required_scope_ref"] == "iii"
