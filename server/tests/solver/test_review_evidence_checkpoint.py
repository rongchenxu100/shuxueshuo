import json

from _problem_planning_support import cached_planning_binding_fixture
from shuxueshuo_server.review.replay import evidence_checkpoint, restore_evidence
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.explanation.snapshot import ExplanationSnapshotBuilder


def test_evidence_checkpoint_rebuilds_identical_snapshot_without_execution():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(), max_attempts=config.max_llm_attempts)
    bundle, *_ = cached_planning_binding_fixture("tj-2026-heping-yimo-25")
    result = orchestrator.solve_verified(bundle)
    assert result.ok, result.errors
    original = orchestrator.last_success_artifacts
    checkpoint = json.loads(json.dumps(evidence_checkpoint(original)))
    restored = restore_evidence(bundle, original.verified_functional_execution.to_payload(), checkpoint, config)
    assert ExplanationSnapshotBuilder().build(restored).to_payload() == ExplanationSnapshotBuilder().build(original).to_payload()
