from __future__ import annotations

from dataclasses import asdict, replace
import json
import os

import pytest

from support.scope_native_c0_c5_generator import (
    goal_retry_dimension_coverage,
    goal_retry_scenarios,
    replay_goal_retry_scenario,
)
from support.scope_native_c0_c5_oracle import (
    ScopeNativeRetryReferenceModel,
)
from support.scope_native_goal_retry_adapters import (
    run_scope_native_goal_retry_adapter,
)
from support.generated_gate_profiles import (
    FULL_SHARD_COUNT,
    QUICK_SHARD_COUNT,
    assert_complete_partition,
    coverage_first_sample,
    select_shard,
)


def _requested_scenarios(scenarios):
    requested = os.environ.get("SCOPE_NATIVE_RETRY_SCENARIO_ID")
    if requested:
        selected = tuple(
            item for item in scenarios if item.scenario_id == requested
        )
        assert selected, requested
        return selected
    return None


@pytest.mark.generated_gate
@pytest.mark.parametrize("quick_shard_index", range(QUICK_SHARD_COUNT))
def test_scope_native_goal_retry_generated_gate_quick(
    quick_shard_index: int,
) -> None:
    all_scenarios = goal_retry_scenarios()
    scenarios = _requested_scenarios(all_scenarios)
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
            _assert_retry_dimension_values(
                goal_retry_dimension_coverage(quick_scenarios)
            )
        scenarios = select_shard(
            quick_scenarios,
            quick_shard_index,
            scenario_id=lambda item: item.scenario_id,
            shard_count=QUICK_SHARD_COUNT,
        )
        assert scenarios
    _run_retry_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
@pytest.mark.parametrize("shard_index", range(FULL_SHARD_COUNT))
def test_scope_native_goal_retry_generated_gate_full(shard_index: int) -> None:
    if os.environ.get("SCOPE_NATIVE_RETRY_SCENARIO_ID"):
        pytest.skip("single-scenario replay is handled by the quick gate")
    scenarios = select_shard(
        goal_retry_scenarios(),
        shard_index,
        scenario_id=lambda item: item.scenario_id,
    )
    assert scenarios
    _run_retry_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
def test_scope_native_goal_retry_generated_gate_full_metadata() -> None:
    scenarios = goal_retry_scenarios()
    assert len(scenarios) == 512
    assert_complete_partition(
        scenarios,
        scenario_id=lambda item: item.scenario_id,
    )
    _assert_retry_dimension_values(goal_retry_dimension_coverage(scenarios))


def _assert_retry_dimension_values(coverage) -> None:
    assert set(coverage["fixture_profile"]) == {
        "failed_goal",
        "published_goal",
    }
    assert set(coverage["repair_mode"]) == {
        "valid",
        "stale_plan",
        "stale_context",
        "missing_editable_goal",
        "foreign_goal",
        "foreign_scope",
        "invalid_answer",
        "no_progress",
    }
    assert set(coverage["reverse_mapping_order"]) == {"False", "True"}
    assert set(coverage["retry_round"]) == {"1", "2"}
    assert set(coverage["variant"]) == {str(index) for index in range(8)}


def _run_retry_scenarios(scenarios) -> None:
    oracle = ScopeNativeRetryReferenceModel()
    for scenario in scenarios:
        expected = oracle.evaluate(scenario)
        actual = run_scope_native_goal_retry_adapter(scenario)
        mismatches = _mismatches(expected, actual)
        assert not mismatches, _failure_report(
            scenario,
            expected=expected,
            actual=actual,
            mismatches=mismatches,
        )
        if scenario.repair_mode in {"valid", "no_progress"}:
            assert actual.restored_call_count > 0


def test_scope_native_goal_retry_scenario_id_is_stably_replayable() -> None:
    scenarios = goal_retry_scenarios()
    for scenario in (scenarios[0], scenarios[255], scenarios[-1]):
        assert replay_goal_retry_scenario(scenario.scenario_id) == scenario


def _mismatches(expected, actual) -> dict[str, tuple[object, object]]:
    result: dict[str, tuple[object, object]] = {}
    for field_name in (
        "accepted",
        "error_code",
        "no_progress",
        "solved_goal_reexecution_count",
        "failed_transaction_ghost_write_count",
    ):
        expected_value = getattr(expected, field_name)
        actual_value = getattr(actual, field_name)
        if expected_value != actual_value:
            result[field_name] = (expected_value, actual_value)
    return result


def _failure_report(scenario, *, expected, actual, mismatches) -> str:
    minimal = _minimize_failure(scenario)
    return json.dumps(
        {
            "scenario_id": scenario.scenario_id,
            "dimensions": scenario.to_payload(),
            "minimal_scenario_id": minimal.scenario_id,
            "minimal_dimensions": minimal.to_payload(),
            "expected": asdict(expected),
            "actual": asdict(actual),
            "mismatches": mismatches,
            "replay_command": (
                "cd server && SCOPE_NATIVE_RETRY_SCENARIO_ID="
                f"{scenario.scenario_id} uv run pytest "
                "tests/solver/test_scope_native_goal_retry_generated_gate.py -q"
            ),
        },
        ensure_ascii=False,
        default=str,
        indent=2,
    )


def _minimize_failure(scenario):
    oracle = ScopeNativeRetryReferenceModel()
    current = scenario
    for field_name, value in (
        ("variant", 0),
        ("retry_round", 1),
        ("reverse_mapping_order", False),
    ):
        candidate = replace(current, scenario_id="", **{field_name: value})
        expected = oracle.evaluate(candidate)
        actual = run_scope_native_goal_retry_adapter(candidate)
        if _mismatches(expected, actual):
            current = candidate
    return current
