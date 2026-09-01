from __future__ import annotations

import pytest

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingScope,
    canonical_plan_hash_for_teaching_scope,
    explanation_snapshot_from_payload,
)


def _snapshot() -> ExplanationSnapshot:
    root_scope = TeachingScope(scope_ref="problem")
    return ExplanationSnapshot(
        problem_id="symbolic-closure-boundary",
        family_id="quadratic_function_composite",
        problem_revision="problem-revision:test",
        problem_semantic_hash="problem-semantics:test",
        canonical_plan_hash=canonical_plan_hash_for_teaching_scope(root_scope),
        verified_execution_hash="verified-execution:test",
        problem={},
        root_scope=root_scope,
    )


def test_snapshot_v2_does_not_project_transactional_symbolic_closure() -> None:
    snapshot = _snapshot()

    assert snapshot.symbolic_closures == ()
    assert "symbolic_closures" not in snapshot.to_payload()


def test_snapshot_v2_rejects_legacy_symbolic_closure_payload() -> None:
    payload = _snapshot().to_payload()
    payload["symbolic_closures"] = []

    with pytest.raises(ValueError, match="fields do not match v2 contract"):
        explanation_snapshot_from_payload(payload)
