from __future__ import annotations

import json
import os
import time

from support.cross_scope_version_adapters import (
    compare_adapter_suite,
    run_dead_writer_liveness_adapter,
    run_production_adapters,
)
from support.cross_scope_version_generator import (
    dead_writer_liveness_scenarios,
    dimension_coverage,
    generated_scenarios,
    reduce_scenario,
    replay_scenario,
)
from support.cross_scope_version_oracle import (
    ReferenceScopeVersionModel,
)


def test_cross_scope_version_generated_gate() -> None:
    scenarios = generated_scenarios()
    requested_scenario_id = os.environ.get("CROSS_SCOPE_SCENARIO_ID")
    if requested_scenario_id:
        scenarios = tuple(
            item
            for item in scenarios
            if item.scenario_id == requested_scenario_id
        )
        assert scenarios, requested_scenario_id
    else:
        assert len(scenarios) >= 10_000
    coverage = dimension_coverage(scenarios)
    if requested_scenario_id is None:
        assert set(coverage["generator"]) == {
            "authority_regression",
            "bounded",
            "expanded",
            "handoff",
        }
        assert set(coverage["topology"]) == {
            "root",
            "parent_child",
            "siblings",
            "branched",
        }
        assert all(
            coverage["topology"][topology] >= 1_000
            for topology in (
                "root",
                "parent_child",
                "siblings",
                "branched",
            )
        )
        assert set(coverage["read_mode"]) == {
            "none",
            "exact",
            "latest",
            "identity_only",
            "call_result",
        }
        assert all(
            coverage["read_mode"][read_mode] >= 1_000
            for read_mode in (
                "none",
                "exact",
                "latest",
                "identity_only",
                "call_result",
            )
        )
        bounded_pairs = {
            (dimensions["topology"], dimensions["read_mode"])
            for scenario in scenarios
            if (dimensions := dict(scenario.dimensions)).get("generator")
            == "bounded"
        }
        assert bounded_pairs == {
            (topology, read_mode)
            for topology in (
                "root",
                "parent_child",
                "siblings",
                "branched",
            )
            for read_mode in (
                "none",
                "exact",
                "latest",
                "identity_only",
                "call_result",
            )
        }
        assert set(coverage["dependency_kind"]) == {
            "call_result",
            "condition",
            "hidden_semantic_role",
            "state_version",
        }
        assert set(coverage["retry"]) == {
            "none",
            "committed_restore",
            "provisional_replacement",
            "version_drift",
        }
        parent_child = tuple(
            scenario
            for scenario in scenarios
            if dict(scenario.dimensions).get("generator") == "bounded"
            and dict(scenario.dimensions).get("topology")
            == "parent_child"
        )
        both_levels = sum(
            {
                call.declared_scope_id for call in scenario.calls
            }
            >= {"problem", "ii"}
            for scenario in parent_child
        )
        assert both_levels >= 1_800
        cross_scope_edges = sum(
            any(
                next(
                    call.declared_scope_id
                    for call in scenario.calls
                    if call.call_id == edge.producer_call_id
                )
                != next(
                    call.declared_scope_id
                    for call in scenario.calls
                    if call.call_id == edge.consumer_call_id
                )
                for edge in scenario.dependency_edges
            )
            for scenario in parent_child
        )
        assert cross_scope_edges >= 200
        assert coverage["runtime_failure"]["producer"] >= 250
        assert set(coverage["producer_capability"]) == {
            "parameter_from_curve_point_on_quadratic",
            "parameter_from_expression_value",
            "parameter_from_minimum_value",
            "parameter_from_segment_length",
        }
        assert set(coverage["closure_checkpoint"]) == {
            "none",
            "none_second",
            "equivalent_target_value",
            "target_value",
            "branch_count",
            "equation_source",
            "residual_symbol",
            "status",
            "missing",
        }
        assert sum(coverage["closure_checkpoint"].values()) == 36

    model = ReferenceScopeVersionModel()
    started = time.monotonic()
    dependent_blocking_count = 0
    blocking_with_b3_issue_count = 0
    for scenario in scenarios:
        expected = model.evaluate(scenario)
        if expected.blocked_call_ids:
            dependent_blocking_count += 1
            if expected.b3_issue_categories:
                blocking_with_b3_issue_count += 1
        actual = run_production_adapters(scenario)
        mismatches = compare_adapter_suite(expected, actual)
        assert not mismatches, _failure_report(
            scenario,
            expected,
            actual,
            mismatches,
        )
    if requested_scenario_id is None:
        assert dependent_blocking_count >= 60
        assert blocking_with_b3_issue_count >= 15
    elapsed = time.monotonic() - started
    # The limit is deliberately generous on shared CI; coverage must not be
    # reduced to make this pass.
    assert elapsed < 60, {
        "elapsed_seconds": elapsed,
        "scenario_count": len(scenarios),
    }


def test_generated_scenario_id_is_stably_replayable() -> None:
    scenarios = generated_scenarios(
        bounded_count=32,
        expanded_count=8,
    )
    for scenario in (scenarios[0], scenarios[-1]):
        replayed = replay_scenario(
            scenario.scenario_id,
            bounded_count=32,
            expanded_count=8,
        )
        assert replayed == scenario


def test_dead_writer_liveness_generated_gate() -> None:
    model = ReferenceScopeVersionModel()
    for scenario in dead_writer_liveness_scenarios():
        expected = model.evaluate(scenario)
        actual = run_dead_writer_liveness_adapter(scenario)
        assert expected.canonical_order == ("answer",)
        assert actual.values == {
            "kept": ("answer",),
            "dropped": ("provisional",),
        }


def _failure_report(scenario, expected, actual, mismatches) -> str:
    first = mismatches[0] if mismatches else None
    model = ReferenceScopeVersionModel()

    def still_fails(candidate) -> bool:
        try:
            return bool(
                compare_adapter_suite(
                    model.evaluate(candidate),
                    run_production_adapters(candidate),
                )
            )
        except Exception:
            return True

    minimal = reduce_scenario(scenario, still_fails)
    payload = {
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "dimensions": dict(scenario.dimensions),
        "scope_tree": [
            (item.scope_id, item.parent_scope_id)
            for item in minimal.scopes
        ],
        "calls": [
            {
                "id": item.call_id,
                "scope": item.declared_scope_id,
                "inputs": item.input_version_ids,
                "state_reads": [
                    {
                        "mode": read.mode,
                        "state_key": read.state_key.token,
                    }
                    for read in item.state_reads
                ],
                "write": item.requested_write_mode,
            }
            for item in minimal.calls
        ],
        "version_edges": [
            {
                "producer": item.producer_call_id,
                "consumer": item.consumer_call_id,
                "kind": item.kind,
            }
            for item in minimal.dependency_edges
        ],
        "first_mismatching_authority": (
            first.authority if first is not None else None
        ),
        "expected": _json_safe(
            first.expected if first is not None else expected
        ),
        "actual": _json_safe(
            first.actual if first is not None else actual
        ),
        "replay_command": (
            "cd server && CROSS_SCOPE_SCENARIO_ID="
            f"{scenario.scenario_id} uv run pytest "
            "tests/solver/test_cross_scope_version_generated_gate.py "
            "-q"
        ),
        "pid": os.getpid(),
    }
    return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


def _json_safe(value):
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return value
