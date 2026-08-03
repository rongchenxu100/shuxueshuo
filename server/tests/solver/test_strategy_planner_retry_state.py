"""Functional retry payload regression tests."""

from shuxueshuo_server.solver.runtime.strategy_replay import (
    transactional_repair_attempt_payload_from_replay,
)
from shuxueshuo_server.solver.deepseek_functional_batch import FUNCTIONAL_BATCH_CASES
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.handle_registry import CanonicalHandleRegistry
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_payload import build_strategy_probe_inputs

from test_functional_transaction_execution import _replay


def test_functional_retry_payload_uses_functional_repair_contract() -> None:
    replay = _replay("nankai", mode="context_authoritative")

    payload = _answer_check_retry_payload(replay)

    assert payload is not None
    assert payload["planner_protocol"] == "functional_plan/v1"
    assert "StepIntent" not in payload["repair_instruction"]
    assert "FunctionalPlan" in payload["repair_instruction"]


def test_successful_transactional_retry_keeps_typed_checkpoint() -> None:
    replay = _replay("nankai", mode="context_authoritative")

    payload = _answer_check_retry_payload(replay)
    checkpoint = payload["functional_retry_graph_checkpoint"]
    assert checkpoint["verified_versions"]
    assert checkpoint["committed_calls"] == []


def test_retry_result_serialization_has_no_legacy_draft_snapshots() -> None:
    replay = _replay("nankai", mode="context_authoritative")

    payload = replay.to_payload()
    assert "raw_draft" not in payload
    assert "normalized_draft" not in payload
    assert "effective_draft" not in payload


def _answer_check_retry_payload(replay):
    case = FUNCTIONAL_BATCH_CASES["nankai"]
    problem = load_problem_ir(case.problem_fixture_path)
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    payload = transactional_repair_attempt_payload_from_replay(
        replay,
        attempt=2,
        errors=("answer_mismatch: synthetic",),
        inputs=inputs,
        handle_registry=registry,
        problem_payload=problem_payload,
    )
    assert payload is not None
    return payload
