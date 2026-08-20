from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.solver.contracts import (
    MethodInputSpec,
    MethodInputViewSpec,
    PointRef,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.executor import InvocationExecutor
from shuxueshuo_server.solver.runtime.functional_diagnostics import (
    FunctionalDiagnosticSubject,
    method_result_empty,
)
from shuxueshuo_server.solver.runtime.method_input_read_authority import (
    CallResultReadSource,
    CompilerSelectorReadSource,
    ConditionReadSource,
    EntityIdentityReadSource,
    MethodInputReadAuthority,
    StateVersionReadSource,
)
from shuxueshuo_server.solver.runtime.method_input_views import (
    MethodInputViewResolver,
    debug_method_input_read_authority,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.models import MethodInvocation
from shuxueshuo_server.solver.runtime.state_identity import (
    LogicalStateKey,
    MathObjectId,
    StateSlotId,
    StateVersionId,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "internal/solver-fixtures"


def _version(*, ordinal: int = 1) -> StateVersionId:
    return StateVersionId(
        StateSlotId(
            LogicalStateKey(
                MathObjectId("point:i:D", "point", "i"),
                "coordinate",
                "Point",
            ),
            "i",
        ),
        ordinal,
    )


def _input(*, mode: str, domain_type: str, runtime_type: str) -> MethodInputSpec:
    return MethodInputSpec(
        name="value",
        domain_type=domain_type,
        runtime_type=runtime_type,
        view=MethodInputViewSpec(mode=mode, domain_type=domain_type),
    )


def _authority(*, mode="latest_state", source=None) -> MethodInputReadAuthority:
    return MethodInputReadAuthority(
        method_id="test_method",
        invocation_id="test_invocation",
        input_name="value",
        item_index=0,
        view_mode=mode,
        domain_type="Point",
        runtime_type="Point" if mode == "latest_state" else "PointRef",
        scope_id="i",
        source=source
        or StateVersionReadSource(_version(), "$question.i.points.D"),
    )


def _context(case: str = "tj-2026-nankai-yimo-25"):
    return ContextBuilder().build(load_problem_ir(str(FIXTURE_ROOT / f"{case}.json")))


def test_read_authority_round_trip_and_hash_drift() -> None:
    authority = _authority()

    assert MethodInputReadAuthority.from_payload(
        authority.authority_payload()
    ) == authority

    drifted = deepcopy(authority.authority_payload())
    drifted["source"]["state_version_id"]["ordinal"] = 2
    with pytest.raises(ValueError, match="signature drift"):
        MethodInputReadAuthority.from_payload(drifted)


def test_method_diagnostic_subject_uses_pinned_read_entity_identity() -> None:
    authority = MethodInputReadAuthority(
        method_id="angle_sum_equal_angle_candidates",
        invocation_id="angle_candidates",
        input_name="x_axis_point",
        item_index=0,
        view_mode="latest_state",
        domain_type="Point",
        runtime_type="Point",
        scope_id="i_2",
        source=StateVersionReadSource(
            StateVersionId(
                StateSlotId(
                    LogicalStateKey(
                        MathObjectId("point:problem:B", "point", "problem"),
                        "coordinate",
                        "Point",
                    ),
                    "problem",
                ),
                1,
            ),
            "$question.i_2.points.B",
        ),
    )
    error = method_result_empty(
        "reference triangle is not isosceles",
        subjects=(
            FunctionalDiagnosticSubject(
                role="horizontal_axis_point",
                arg_name="x_axis_point",
                expected_type="Point",
                observed_state="open_state",
            ),
        ),
        observed={"free_symbols": ["a"]},
        repair_action="refresh_derived_input_states",
    ).with_input_read_authorities({"x_axis_point": (authority,)})

    assert error.authority.subjects[0].internal_ref == "point:problem:B"
    assert error.authority.repair_action == "refresh_derived_input_states"


@pytest.mark.parametrize(
    ("mode", "source"),
    [
        ("identity", StateVersionReadSource(_version(), "$question.i.points.D")),
        (
            "latest_state",
            CallResultReadSource("producer", "point", "$step.producer.outputs.point"),
        ),
        (
            "exact_result",
            ConditionReadSource("condition:D", "$question.i.conditions.D"),
        ),
    ],
)
def test_read_authority_rejects_source_kind_incompatible_with_view(mode, source) -> None:
    runtime_type = {
        "identity": "PointRef",
        "latest_state": "Point",
        "exact_result": "Point",
    }[mode]
    with pytest.raises(ValueError, match="authority_drift"):
        MethodInputReadAuthority(
            method_id="test_method",
            invocation_id="test_invocation",
            input_name="value",
            item_index=0,
            view_mode=mode,
            domain_type="Point",
            runtime_type=runtime_type,
            scope_id="i",
            source=source,
        )


@pytest.mark.parametrize("mode", ["latest_state", "exact_result"])
def test_production_resolver_rejects_debug_compiler_selector(mode) -> None:
    runtime_type = "Point"
    input_spec = _input(
        mode=mode,
        domain_type="Point",
        runtime_type=runtime_type,
    )
    authority = MethodInputReadAuthority(
        method_id="test_method",
        invocation_id="test_invocation",
        input_name="value",
        item_index=0,
        view_mode=mode,
        domain_type="Point",
        runtime_type=runtime_type,
        scope_id="i",
        source=CompilerSelectorReadSource(
            "debug:value",
            "$question.i.points.D",
        ),
    )

    with pytest.raises(Exception) as error:
        MethodInputViewResolver().resolve(
            _context(),
            method_id="test_method",
            invocation_id="test_invocation",
            scope_id="i",
            input_name="value",
            input_spec=input_spec,
            raw_path="$question.i.points.D",
            authority=authority,
            require_authority=True,
        )

    assert getattr(error.value, "code", None) == (
        "planner.method_input_view_authority_drift"
    )


def test_point_identity_is_pure_and_does_not_capture_coordinate_state() -> None:
    authority = MethodInputReadAuthority(
        method_id="test_method",
        invocation_id="test_invocation",
        input_name="value",
        item_index=0,
        view_mode="identity",
        domain_type="Point",
        runtime_type="PointRef",
        scope_id="i",
        source=EntityIdentityReadSource(
            "point:problem:D",
            "$problem.points.D",
        ),
    )

    resolved = MethodInputViewResolver().resolve(
        _context(),
        method_id="test_method",
        invocation_id="test_invocation",
        scope_id="i",
        input_name="value",
        input_spec=_input(
            mode="identity",
            domain_type="Point",
            runtime_type="PointRef",
        ),
        raw_path="$problem.points.D",
        authority=authority,
        require_authority=True,
    )

    assert isinstance(resolved.value, PointRef)
    assert resolved.value.name == "D"
    assert "existing_coordinate" not in resolved.value.definition
    assert "coordinate" not in resolved.value.definition


def test_debug_identity_authority_never_uses_runtime_path_as_entity_handle() -> None:
    authority = debug_method_input_read_authority(
        _context(),
        method_id="test_method",
        invocation_id="test_invocation",
        scope_id="i",
        input_name="value",
        item_index=0,
        input_spec=_input(
            mode="identity",
            domain_type="Point",
            runtime_type="PointRef",
        ),
        raw_path="$problem.points.D",
    )

    assert isinstance(authority.source, EntityIdentityReadSource)
    assert authority.source.entity_handle == "point:problem:D"
    assert not authority.source.entity_handle.startswith("$")


def test_aggregate_inputs_are_resolved_item_by_item_through_authority() -> None:
    context = _context()
    paths = (
        "$problem.symbols.a",
        "$problem.symbols.b",
        "$problem.symbols.c",
    )
    authorities = tuple(
        MethodInputReadAuthority(
            method_id="quadratic_from_constraints",
            invocation_id="aggregate",
            input_name="all_coefficients",
            item_index=index,
            view_mode="immutable_value",
            domain_type="SymbolList",
            runtime_type="Symbol",
            scope_id="problem",
            source=EntityIdentityReadSource(
                f"symbol:problem:{name}",
                path,
            ),
        )
        for index, (name, path) in enumerate(zip(("a", "b", "c"), paths))
    )
    invocation = MethodInvocation(
        invocation_id="aggregate",
        method_id="quadratic_from_constraints",
        scope="problem",
        inputs={"all_coefficients": paths},
        input_read_authorities={"all_coefficients": authorities},
    )

    resolved = InvocationExecutor(
        MethodSpecRegistry.load_from_code(),
        require_input_read_authority=True,
    ).resolve_inputs(context, invocation)

    assert [str(item) for item in resolved["all_coefficients"]] == [
        "a",
        "b",
        "c",
    ]


def test_production_resolver_requires_authority() -> None:
    with pytest.raises(Exception) as error:
        MethodInputViewResolver().resolve(
            _context(),
            method_id="test_method",
            invocation_id="test_invocation",
            scope_id="i",
            input_name="value",
            input_spec=_input(
                mode="latest_state",
                domain_type="Point",
                runtime_type="Point",
            ),
            raw_path="$question.i.points.D",
            require_authority=True,
        )

    assert getattr(error.value, "code", None) == (
        "planner.method_input_view_authority_missing"
    )
