from __future__ import annotations

from dataclasses import asdict, replace
import json
import os

import pytest
import sympy as sp

from shuxueshuo_server.solver.contracts import SymbolicClosureSpec
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.runtime.state_identity import MathObjectId
from shuxueshuo_server.solver.runtime.symbolic_closure_execution import (
    execute_symbolic_closure,
)
from support.scope_native_c0_c5_generator import (
    c5_retry_dimension_coverage,
    c5_retry_scenarios,
    replay_c5_retry_scenario,
)
from support.scope_native_c0_c5_oracle import ScopeNativeC5ReferenceModel
from support.scope_native_goal_retry_adapters import (
    run_scope_native_c5_retry_adapter,
)
from support.generated_gate_profiles import (
    FULL_SHARD_COUNT,
    QUICK_SHARD_COUNT,
    assert_complete_partition,
    coverage_first_sample,
    select_shard,
)


def _base_spec() -> SymbolicClosureSpec:
    return SymbolicClosureSpec(
        target_arg="target_parameter",
        equation_builder="quadratic_constraints",
        known_substitutions=(("parameter", "parameter_value"),),
        known_mapping_args=("known_coefficients",),
        representation_mapper="polynomial_coefficient_template",
        preserved_symbol_args=("free_parameter", "free_parameters"),
        output_validator="quadratic_closure_outputs",
    )


SYMBOLIC_SCENARIOS = (
    "direct",
    "mapped",
    "mapped_open",
    "known_coefficient",
    "known_parameter",
    "ambiguous",
    "inconsistent",
    "underdetermined",
    "filter_accept",
    "filter_reject",
)


def _symbolic_indices() -> tuple[int, ...]:
    return tuple(range(2048))


def _symbolic_scenario_id(index: int) -> str:
    return f"symbolic-closure:{index:04d}"


def _symbolic_dimensions(index: int) -> dict[str, object]:
    return {
        "scenario": SYMBOLIC_SCENARIOS[index % len(SYMBOLIC_SCENARIOS)],
        "offset": index % 11 + 1,
    }


@pytest.mark.generated_gate
@pytest.mark.parametrize("quick_shard_index", range(QUICK_SHARD_COUNT))
def test_generated_production_quadratic_symbolic_closure_gate_quick(
    quick_shard_index: int,
) -> None:
    if os.environ.get("SCOPE_NATIVE_C5_SCENARIO_ID"):
        pytest.skip("C5 single-scenario replay bypasses the closure matrix")
    quick_indices = coverage_first_sample(
        _symbolic_indices(),
        256,
        scenario_id=_symbolic_scenario_id,
        dimensions=_symbolic_dimensions,
    )
    assert len(quick_indices) == 256
    if quick_shard_index == 0:
        assert {
            _symbolic_dimensions(index)["scenario"] for index in quick_indices
        } == set(SYMBOLIC_SCENARIOS)
        assert {
            _symbolic_dimensions(index)["offset"] for index in quick_indices
        } == set(range(1, 12))
    indices = select_shard(
        quick_indices,
        quick_shard_index,
        scenario_id=_symbolic_scenario_id,
        shard_count=QUICK_SHARD_COUNT,
    )
    assert indices
    _run_symbolic_closure_indices(indices)


@pytest.mark.generated_gate
@pytest.mark.solver_full
@pytest.mark.parametrize("shard_index", range(FULL_SHARD_COUNT))
def test_generated_production_quadratic_symbolic_closure_gate_full(
    shard_index: int,
) -> None:
    if os.environ.get("SCOPE_NATIVE_C5_SCENARIO_ID"):
        pytest.skip("C5 single-scenario replay bypasses the closure matrix")
    indices = select_shard(
        _symbolic_indices(),
        shard_index,
        scenario_id=_symbolic_scenario_id,
    )
    assert indices
    _run_symbolic_closure_indices(indices)


@pytest.mark.generated_gate
@pytest.mark.solver_full
def test_generated_symbolic_closure_full_metadata() -> None:
    indices = _symbolic_indices()
    assert len(indices) == 2_048
    assert_complete_partition(indices, scenario_id=_symbolic_scenario_id)


def _run_symbolic_closure_indices(indices) -> None:
    kernel = SympyKernel()
    symbols = kernel.symbols(["x", "a", "b", "c"])
    x, a, b, c = (
        symbols[name] for name in ("x", "a", "b", "c")
    )
    identities = {
        symbol: MathObjectId(symbol.name, "symbol", "problem")
        for symbol in symbols.values()
    }
    for scenario_index in indices:
        scenario = SYMBOLIC_SCENARIOS[
            scenario_index % len(SYMBOLIC_SCENARIOS)
        ]
        offset = sp.Integer(scenario_index % 11 + 1)
        spec = _base_spec()
        args = {
            "quadratic": a * x**2 + b,
            "quadratic_template": a * x**2 + b,
            "x": x,
            "all_coefficients": [a, b],
            "known_coefficients": {a: 1},
            "target_parameter": b,
        }
        expected = "unique"

        if scenario == "direct":
            args["curve_point"] = (1, offset)
        elif scenario == "mapped":
            args.update(
                {
                    "quadratic": a * x**2 + (1 - c) * x + c,
                    "quadratic_template": a * x**2 + b * x + c,
                    "all_coefficients": [a, b, c],
                    "extra_equation": sp.Eq(c, offset),
                }
            )
        elif scenario == "mapped_open":
            args.update(
                {
                    "quadratic": a * x**2 + (1 - c) * x + c,
                    "quadratic_template": a * x**2 + b * x + c,
                    "all_coefficients": [a, b, c],
                    "free_parameter": c,
                }
            )
        elif scenario == "known_coefficient":
            args["known_coefficients"][b] = offset
        elif scenario == "known_parameter":
            args["parameter"] = b
            args["parameter_value"] = offset
        elif scenario == "ambiguous":
            args["extra_equation"] = sp.Eq(b**2, 1)
            expected = "ambiguous"
        elif scenario == "inconsistent":
            args["extra_equation"] = sp.S.false
            expected = "inconsistent"
        elif scenario == "underdetermined":
            expected = "identity_unresolved"
        else:
            candidate = offset if scenario == "filter_accept" else -offset
            args["extra_equation"] = sp.Eq(b, candidate)
            args["value_constraint"] = {
                "operator": ">",
                "value": sp.Integer(0),
            }
            spec = replace(
                spec,
                constraint_filter="parameter_value_constraint",
                constraint_args=("value_constraint",),
            )
            if scenario == "filter_reject":
                expected = "underdetermined"

        result = execute_symbolic_closure(
            spec,
            args=args,
            target_object_id=identities[b],
            runtime_symbol_bindings=identities,
            kernel=kernel,
        )

        assert result.status == expected, (
            scenario_index,
            scenario,
            result,
        )
        assert result.target_object_id == identities[b]
        assert result.validation_context_attached
        if expected == "unique":
            assert result.target_value is not None
            assert b in result.substitution
        if scenario == "mapped_open":
            assert sp.simplify(result.target_value - (1 - c)) == 0
            assert result.residual_symbols == (c,)


def _requested_c5_scenarios(scenarios):
    requested = os.environ.get("SCOPE_NATIVE_C5_SCENARIO_ID")
    if requested:
        selected = tuple(
            item for item in scenarios if item.scenario_id == requested
        )
        assert selected, requested
        return selected
    return None


@pytest.mark.generated_gate
@pytest.mark.parametrize("quick_shard_index", range(QUICK_SHARD_COUNT))
def test_scope_native_execution_to_closure_retry_generated_gate_quick(
    quick_shard_index: int,
) -> None:
    all_scenarios = c5_retry_scenarios()
    scenarios = _requested_c5_scenarios(all_scenarios)
    if scenarios is not None:
        if quick_shard_index:
            pytest.skip("single-scenario replay runs in quick shard zero")
    else:
        quick_scenarios = coverage_first_sample(
            all_scenarios,
            64,
            scenario_id=lambda item: item.scenario_id,
            dimensions=lambda item: item.to_payload(),
        )
        assert len(quick_scenarios) == 64
        if quick_shard_index == 0:
            _assert_c5_dimension_values(
                c5_retry_dimension_coverage(quick_scenarios)
            )
        scenarios = select_shard(
            quick_scenarios,
            quick_shard_index,
            scenario_id=lambda item: item.scenario_id,
            shard_count=QUICK_SHARD_COUNT,
        )
        assert scenarios
    _run_c5_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
@pytest.mark.parametrize("shard_index", range(FULL_SHARD_COUNT))
def test_scope_native_execution_to_closure_retry_generated_gate_full(
    shard_index: int,
) -> None:
    if os.environ.get("SCOPE_NATIVE_C5_SCENARIO_ID"):
        pytest.skip("single-scenario replay is handled by the quick gate")
    scenarios = select_shard(
        c5_retry_scenarios(),
        shard_index,
        scenario_id=lambda item: item.scenario_id,
    )
    assert scenarios
    _run_c5_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
def test_scope_native_closure_retry_full_metadata() -> None:
    scenarios = c5_retry_scenarios()
    assert len(scenarios) == 256
    assert_complete_partition(
        scenarios,
        scenario_id=lambda item: item.scenario_id,
    )
    _assert_c5_dimension_values(c5_retry_dimension_coverage(scenarios))


def _assert_c5_dimension_values(coverage) -> None:
    assert set(coverage["closure_failure"]) == {
        "identity_unresolved",
        "underdetermined",
        "ambiguous",
        "inconsistent",
    }
    assert set(coverage["expose_residual_symbol"]) == {"False", "True"}
    assert set(coverage["expose_equation_sources"]) == {"False", "True"}
    assert set(coverage["repair_mode"]) == {"valid", "stale_plan"}
    assert set(coverage["reverse_mapping_order"]) == {"False", "True"}
    assert set(coverage["variant"]) == {"0", "1", "2", "3"}


def _run_c5_scenarios(scenarios) -> None:
    oracle = ScopeNativeC5ReferenceModel()
    for scenario in scenarios:
        expected = oracle.evaluate(scenario)
        actual = run_scope_native_c5_retry_adapter(scenario)
        assert asdict(actual) == asdict(expected), _c5_failure_report(
            scenario,
            expected=expected,
            actual=actual,
        )


def test_scope_native_c5_scenario_id_is_stably_replayable() -> None:
    scenarios = c5_retry_scenarios()
    for scenario in (scenarios[0], scenarios[127], scenarios[-1]):
        assert replay_c5_retry_scenario(scenario.scenario_id) == scenario


def _c5_failure_report(scenario, *, expected, actual) -> str:
    return json.dumps(
        {
            "scenario_id": scenario.scenario_id,
            "dimensions": scenario.to_payload(),
            "expected": asdict(expected),
            "actual": asdict(actual),
            "replay_command": (
                "cd server && SCOPE_NATIVE_C5_SCENARIO_ID="
                f"{scenario.scenario_id} uv run pytest "
                "tests/solver/test_symbolic_closure_generated_gate.py -q"
            ),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )
