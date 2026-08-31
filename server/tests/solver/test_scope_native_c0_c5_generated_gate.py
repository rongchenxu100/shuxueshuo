from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from support.scope_native_c0_c5_adapters import (
    SCOPE_NATIVE_PROTOCOL_PROBES,
    compare_adapter_suite,
    run_dead_writer_liveness_adapter,
    run_production_adapters,
    run_scope_native_protocol_adapter,
)
from support.scope_native_c0_c5_generator import (
    dead_writer_liveness_scenarios,
    dimension_coverage,
    generated_scenarios,
    reduce_scenario,
    replay_scenario,
)
from support.scope_native_c0_c5_oracle import (
    ScopeNativeReferenceModel,
)
from support.generated_gate_profiles import (
    FULL_SHARD_COUNT,
    assert_complete_partition,
    coverage_first_sample,
    select_shard,
)


def _requested_scenarios(scenarios):
    requested_scenario_id = os.environ.get("SCOPE_NATIVE_SCENARIO_ID")
    if requested_scenario_id:
        requested = tuple(
            item
            for item in scenarios
            if item.scenario_id == requested_scenario_id
        )
        assert requested, requested_scenario_id
        return requested
    return None


@pytest.mark.generated_gate
def test_scope_native_c0_c5_generated_gate_quick() -> None:
    all_scenarios = generated_scenarios()
    scenarios = _requested_scenarios(all_scenarios)
    if scenarios is None:
        scenarios = coverage_first_sample(
            all_scenarios,
            512,
            scenario_id=lambda item: item.scenario_id,
            dimensions=lambda item: dict(item.dimensions),
            pinned=lambda item: (
                dict(item.dimensions).get("generator")
                == "authority_regression"
            ),
        )
        assert len(scenarios) == 512
        _assert_c0_dimension_values(dimension_coverage(scenarios))
    _run_c0_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
@pytest.mark.parametrize("shard_index", range(FULL_SHARD_COUNT))
def test_scope_native_c0_c5_generated_gate_full(shard_index: int) -> None:
    if os.environ.get("SCOPE_NATIVE_SCENARIO_ID"):
        pytest.skip("single-scenario replay is handled by the quick gate")
    scenarios = select_shard(
        generated_scenarios(),
        shard_index,
        scenario_id=lambda item: item.scenario_id,
    )
    assert scenarios
    _run_c0_scenarios(scenarios)


@pytest.mark.generated_gate
@pytest.mark.solver_full
def test_scope_native_c0_c5_generated_gate_full_metadata() -> None:
    scenarios = generated_scenarios()
    assert len(scenarios) >= 10_000
    assert_complete_partition(
        scenarios,
        scenario_id=lambda item: item.scenario_id,
    )
    coverage = dimension_coverage(scenarios)
    _assert_c0_dimension_values(coverage)
    assert all(
        coverage["topology"][topology] >= 1_000
        for topology in ("root", "parent_child", "siblings", "branched")
    )
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
        for topology in ("root", "parent_child", "siblings", "branched")
        for read_mode in (
            "none",
            "exact",
            "latest",
            "identity_only",
            "call_result",
        )
    }
    parent_child = tuple(
        scenario
        for scenario in scenarios
        if dict(scenario.dimensions).get("generator") == "bounded"
        and dict(scenario.dimensions).get("topology") == "parent_child"
    )
    assert sum(
        {call.declared_scope_id for call in scenario.calls}
        >= {"problem", "ii"}
        for scenario in parent_child
    ) >= 1_800
    assert sum(
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
    ) >= 200
    assert coverage["runtime_failure"]["producer"] >= 250
    assert sum(coverage["closure_checkpoint"].values()) == 36

    model = ScopeNativeReferenceModel()
    dependent_blocking_count = 0
    blocking_with_b3_issue_count = 0
    for scenario in scenarios:
        expected = model.evaluate(scenario)
        if expected.blocked_call_ids:
            dependent_blocking_count += 1
            if expected.b3_issue_categories:
                blocking_with_b3_issue_count += 1
    assert dependent_blocking_count >= 60
    assert blocking_with_b3_issue_count >= 15


def _assert_c0_dimension_values(coverage) -> None:
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
    assert set(coverage["read_mode"]) == {
        "none",
        "exact",
        "latest",
        "identity_only",
        "call_result",
    }
    assert set(coverage["dependency_kind"]) == {
        "call_result",
        "condition",
        "hidden_semantic_role",
        "state_version",
    }
    assert set(coverage["state_restore"]) == {
        "none",
        "locked_restore",
        "discard_provisional",
        "version_drift",
    }
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


def _run_c0_scenarios(scenarios) -> None:
    model = ScopeNativeReferenceModel()
    started = time.monotonic()
    for scenario in scenarios:
        expected = model.evaluate(scenario)
        actual = run_production_adapters(scenario)
        mismatches = compare_adapter_suite(expected, actual)
        assert not mismatches, _failure_report(
            scenario,
            expected,
            actual,
            mismatches,
        )
    elapsed = time.monotonic() - started
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


@pytest.mark.solver_contract
def test_authenticated_scope_native_protocol_probes() -> None:
    cases = (
        "tj-2026-nankai-yimo-25",
        "tj-2026-heping-ermo-25",
        "tj-2026-xiqing-yimo-25",
        "tj-2026-hexi-yimo-25",
        "tj-2026-heping-yimo-25",
    )
    expected_issues = {
        "baseline": (),
        "empty_optional_maps": (),
        "missing_goal": ("functional.plan_content_schema_invalid",),
        "unknown_scope": ("functional.plan_content_schema_invalid",),
        "duplicate_step_owner": ("functional.step_id_duplicate",),
        "invalid_answer_source": (
            "functional.goal_answer_source_unresolved",
            "functional.answer_producer_invalid",
        ),
        "revision_drift": ("planner.problem_revision_drift",),
        "source_binding_drift": ("planner.problem_source_binding_drift",),
    }
    for case_id in cases:
        for probe in SCOPE_NATIVE_PROTOCOL_PROBES:
            outcome = run_scope_native_protocol_adapter(case_id, probe)
            assert outcome.issue_codes == expected_issues[probe]
            assert len(outcome.planning_context_id) > 20
            assert len(outcome.binding_signature) == 64
            if probe in {
                "baseline",
                "empty_optional_maps",
            }:
                assert outcome.checkpoint_id is not None
                assert outcome.all_required_goals_verified
                assert outcome.transaction_ok
            elif probe == "invalid_answer_source":
                # A parseable Plan remains executable as a Draft so Goal-level
                # repair can reuse verified work. It must not be promoted.
                assert outcome.checkpoint_id is not None
                assert not outcome.all_required_goals_verified
                assert outcome.transaction_ok
            else:
                assert outcome.checkpoint_id is None
                assert not outcome.all_required_goals_verified
                assert not outcome.transaction_ok
    normalized = run_scope_native_protocol_adapter(
        cases[0], "empty_optional_maps"
    )
    assert normalized.normalization_codes == (
        "functional.empty_optional_step_map_omitted",
        "functional.empty_optional_step_map_omitted",
    )
    draft = run_scope_native_protocol_adapter(
        cases[0], "invalid_answer_source"
    )
    assert draft.normalization_codes == ()
    assert draft.checkpoint_id is not None


def test_internal_candidate_result_is_not_normalized_to_named_entity() -> None:
    outcome = run_scope_native_protocol_adapter(
        "tj-2026-hexi-yimo-25",
        "baseline",
    )

    assert "functional.named_entity_result_ref_normalized" not in (
        outcome.normalization_codes
    )
    assert outcome.issue_codes == ()
    assert outcome.all_required_goals_verified
    assert outcome.transaction_ok


def test_dead_writer_liveness_generated_gate() -> None:
    model = ScopeNativeReferenceModel()
    for scenario in dead_writer_liveness_scenarios():
        expected = model.evaluate(scenario)
        actual = run_dead_writer_liveness_adapter(scenario)
        assert expected.canonical_order == ("answer",)
        assert actual.values == {
            "kept": ("answer",),
            "dropped": ("provisional",),
        }


def test_superseded_gate_contracts_have_no_source_references() -> None:
    repository = Path(__file__).resolve().parents[3]
    forbidden = (
        "cross_" + "scope_version",
        "cross-" + "scope-version",
        "c0.5/" + "v10",
        "committed_" + "restore",
        "provisional_" + "replacement",
        "functional_" + "binding_generator",
    )
    violations: list[str] = []
    for root in (
        repository / "docs",
        repository / "server" / "shuxueshuo_server",
        repository / "server" / "tests" / "solver",
    ):
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".md", ".json"}:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    violations.append(f"{path.relative_to(repository)}:{token}")
    assert not violations, violations


def _failure_report(scenario, expected, actual, mismatches) -> str:
    first = mismatches[0] if mismatches else None
    model = ScopeNativeReferenceModel()

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
            "cd server && SCOPE_NATIVE_SCENARIO_ID="
            f"{scenario.scenario_id} uv run pytest "
            "tests/solver/test_scope_native_c0_c5_generated_gate.py "
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
