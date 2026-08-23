from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from shuxueshuo_server.solver.runtime.method_output_write_authority import (
    CallResultOutputDestinationAuthority,
    MethodOutputWriteAuthority,
    StateOutputDestinationAuthority,
)
from shuxueshuo_server.solver.runtime.method_specs import (
    MethodSpecRegistry,
    parse_method_spec,
)
from shuxueshuo_server.solver.runtime.methods import method_spec_payloads

from test_functional_transaction_execution import _replay


pytestmark = pytest.mark.solver_contract


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = REPO_ROOT / "internal/schemas"
EXPECTED_COMPANIONS = {
    ("quadratic_from_constraints", "coefficients"),
    ("quadratic_axis_parameterized_point", "parameter"),
    ("weighted_axis_path_triangle_transform", "auxiliary_point"),
    ("weighted_axis_path_triangle_transform", "auxiliary_locus"),
}


@pytest.fixture(scope="module")
def recorded_companion_calls():
    result = []
    for case_id in ("heping", "heping-ermo", "hexi", "nankai", "xiqing"):
        replay = _replay(case_id, mode="context_authoritative")
        assert replay.output is not None
        report = replay.transactional_execution_report
        assert report is not None
        result.extend(
            call
            for call in report.compiled_calls
            if call.output_write_authorities
        )
    return tuple(result)


def test_method_companion_output_contract_and_schema_round_trip() -> None:
    registry = MethodSpecRegistry.load_from_code()
    actual = {
        (spec.method_id, companion.output_name)
        for spec in registry.specs.values()
        for companion in spec.companion_outputs
    }
    assert actual == EXPECTED_COMPANIONS

    schema = json.loads(
        (SCHEMA_ROOT / "method-companion-output.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validator = Draft202012Validator(schema)
    for spec in registry.specs.values():
        for companion in spec.companion_outputs:
            validator.validate(companion.to_payload())

    payload = next(
        item
        for item in method_spec_payloads()
        if item["method_id"] == "quadratic_from_constraints"
    )
    retired = json.loads(json.dumps(payload))
    retired["companion_outputs"][0]["target_selector"] = "scope_output:x"
    with pytest.raises(
        ValueError,
        match="planner.method_output_binding_contract_invalid",
    ):
        parse_method_spec(retired)


def test_all_companion_outputs_receive_exact_write_authority(
    recorded_companion_calls,
) -> None:
    actual = {
        (authority.method_id, authority.output_name)
        for call in recorded_companion_calls
        for authority in call.output_write_authorities
    }
    assert actual == EXPECTED_COMPANIONS

    for call in recorded_companion_calls:
        allocations = {
            item.return_name: item.allocation
            for item in call.public_returns
        }
        for authority in call.output_write_authorities:
            allocation = allocations[authority.function_return_name]
            authority.verify(
                allocation=allocation,
                runtime_path=authority.runtime_path,
            )
            aliases = {item.handle for item in authority.registration_aliases}
            allowed = {
                allocation.handle,
                allocation.state_handle,
                (
                    f"runtime:{allocation.call_id}:{allocation.return_name}"
                    if allocation.allocation_action == "call_local_value"
                    else None
                ),
            }
            assert aliases <= {item for item in allowed if item}

            invocation = next(
                invocation
                for plan in call.plans
                for invocation in plan.invocations
                if invocation.invocation_id == authority.invocation_id
            )
            plan = next(
                plan
                for plan in call.plans
                if invocation in plan.invocations
            )
            assert (
                plan.promote_outputs[
                    invocation.outputs[authority.output_name]
                ]
                == authority.runtime_path
            )


def test_companion_destination_kind_matches_runtime_semantics(
    recorded_companion_calls,
) -> None:
    authorities = tuple(
        authority
        for call in recorded_companion_calls
        for authority in call.output_write_authorities
    )
    assert all(
        isinstance(authority.destination, CallResultOutputDestinationAuthority)
        for authority in authorities
        if authority.output_name in {"coefficients", "auxiliary_locus"}
    )
    assert all(
        isinstance(authority.destination, StateOutputDestinationAuthority)
        for authority in authorities
        if authority.output_name in {"parameter", "auxiliary_point"}
    )
    for authority in authorities:
        if isinstance(authority.destination, StateOutputDestinationAuthority):
            assert authority.destination.selected_version_id
            assert authority.destination.runtime_path == authority.runtime_path


def test_output_authority_schema_round_trip_and_drift_detection(
    recorded_companion_calls,
) -> None:
    authority = recorded_companion_calls[0].output_write_authorities[0]
    payload = authority.authority_payload()
    schema = json.loads(
        (SCHEMA_ROOT / "method-output-write-authority.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(payload)
    assert MethodOutputWriteAuthority.from_payload(payload) == authority

    tampered = dict(payload)
    tampered["valid_scope"] = "sibling"
    with pytest.raises(ValueError, match="signature drift"):
        MethodOutputWriteAuthority.from_payload(tampered)

    allocation = recorded_companion_calls[0].public_returns[0].allocation
    with pytest.raises(
        ValueError,
        match="planner.method_output_write_authority_drift",
    ):
        authority.verify(
            allocation=replace(allocation, runtime_type="Line"),
            runtime_path=authority.runtime_path,
        )


def test_standalone_equal_length_role_provider_is_absent() -> None:
    runtime_root = (
        REPO_ROOT / "server/shuxueshuo_server/solver/runtime"
    )
    assert not (runtime_root / "debug_equal_length_ray_roles.py").exists()
    direct_builder_users = tuple(
        path.name
        for path in runtime_root.glob("*.py")
        if path.name != "equal_length_ray_roles.py"
        and "build_equal_length_ray_role_candidates"
        in path.read_text(encoding="utf-8")
    )
    assert direct_builder_users == ("macro_preparation.py",)
