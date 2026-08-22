from __future__ import annotations

from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.contracts import (
    ExactCallResultSourceSpec,
    MacroPreparedRoleSourceSpec,
    MethodInputBindingSpec,
    PreviousOutputIdentityDerivationSpec,
)
from shuxueshuo_server.solver.runtime.equal_length_ray_path_search import (
    _prepared_runtime_arg_value,
)
from shuxueshuo_server.solver.runtime.debug_equal_length_ray_roles import (
    DebugEqualLengthRayRoleProvider,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.macro_preparation import (
    default_macro_implementation_registry,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    InvocationResultReadSource,
    StateVersionReadSource,
)

from test_functional_transaction_execution import _replay


pytestmark = pytest.mark.solver_contract


def _implementation():
    return default_macro_implementation_registry()._items[
        "equal_length_ray_path_reduction"
    ]


def test_registry_owns_every_equal_length_internal_method_input() -> None:
    bindings = {
        item.target: item.binding
        for item in _implementation().method_input_bindings
    }

    assert set(bindings) == {
        "equal_length_ray_point.anchor",
        "equal_length_ray_point.reference_point",
        "equal_length_ray_point.ray_point",
        "equal_length_ray_point.target",
        "distance_between_points.p1",
        "distance_between_points.p2",
    }
    assert {
        bindings[name].source.role
        for name in (
            "equal_length_ray_point.anchor",
            "equal_length_ray_point.reference_point",
            "equal_length_ray_point.ray_point",
            "distance_between_points.p1",
        )
        if isinstance(bindings[name].source, MacroPreparedRoleSourceSpec)
    } == {"anchor", "reference_point", "ray_point", "fixed_point"}
    assert isinstance(
        bindings["equal_length_ray_point.target"].derivation,
        PreviousOutputIdentityDerivationSpec,
    )
    assert isinstance(
        bindings["distance_between_points.p2"].source,
        ExactCallResultSourceSpec,
    )


def test_equal_length_role_provider_is_debug_only_and_families_are_strict() -> None:
    assert DebugEqualLengthRayRoleProvider.__module__.endswith(
        ".debug_equal_length_ray_roles"
    )
    assert all(
        isinstance(binding, MethodInputBindingSpec)
        for family in DEFAULT_FAMILY_REGISTRY.families
        for rule in family.method_binding_rules
        for binding in rule.input_bindings
    )


def test_macro_winner_is_the_only_f5c_role_authority() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    binding = compiled.problem_call_binding
    assert binding is not None

    assert dict(binding.authored_roles) == {}
    assert dict(binding.chosen_roles) == {
        "anchor": "point:problem:C",
        "fixed_point": "point:problem:O",
        "ray_point": "point:problem:D",
        "reference_point": "point:problem:B",
    }
    assert binding.macro_preparation_signature
    assert binding.macro_search_signature
    assert compiled.problem_source_provenance is not None
    assert (
        compiled.problem_source_provenance.macro_search_signature
        == binding.macro_search_signature
    )


def test_macro_clean_replay_uses_canonical_paths_and_exact_internal_result() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    invocations = {
        item.method_id: item
        for plan in compiled.replay_plans
        for item in plan.invocations
    }

    for input_name in ("anchor", "reference_point", "ray_point"):
        source = invocations["equal_length_ray_point"].input_read_authorities[
            input_name
        ][0].source
        assert isinstance(source, StateVersionReadSource)
        assert "__functional_transaction_" not in source.runtime_path
    p2 = invocations["distance_between_points"].input_read_authorities["p2"][
        0
    ].source
    assert isinstance(p2, InvocationResultReadSource)
    assert p2.invocation_id.endswith(".equal_length_ray_point")
    assert p2.return_name == "point"


def test_witness_reads_the_registry_owned_state_pin() -> None:
    replay = _replay("heping", mode="context_authoritative")
    report = replay.transactional_execution_report
    assert report is not None
    compiled = next(
        item
        for item in report.compiled_calls
        if item.call_id == "reduce_equal_length_ray_path_ii"
    )
    invocation = compiled.plans[0].invocations[0]
    source = invocation.input_read_authorities["anchor"][0].source
    value = report.runtime_version_values[source.state_version_id]
    declaration = next(
        item
        for item in _implementation().method_input_bindings
        if item.target == "equal_length_ray_point.anchor"
    )
    prepared = SimpleNamespace(
        macro_method_inputs=(
            SimpleNamespace(declaration=declaration, source=source),
        ),
        state_reads=(
            SimpleNamespace(
                selected_version_id=source.state_version_id,
                runtime_value=value,
                arg_name="$macro.equal_length_ray_point.anchor",
            ),
        ),
        arg_bindings=(),
    )

    assert _prepared_runtime_arg_value(prepared, "anchor") == value
