from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.runtime.functional_subplan import (
    MacroSearchSelection,
    SingleFragmentSelection,
    VerifiedSubplanExecution,
)
from shuxueshuo_server.solver.runtime.functional_goal_execution import (
    FunctionalGoalExecutionCheckpoint,
    VerifiedFunctionalPlanExecution,
    functional_goal_execution_checkpoint_schema,
    verified_functional_plan_execution_schema,
)
from shuxueshuo_server.solver.runtime.functional_goal_retry import (
    planner_goal_retry_context_schema,
)

from _scoped_functional_plan_support import load_v3_fixture_payload
from test_functional_goal_execution import _execute


ROOT = Path(__file__).resolve().parents[3]
SCHEMAS = ROOT / "internal" / "schemas"


def _execution_evidence(root_scope):
    scopes = [root_scope]
    while scopes:
        scope = scopes.pop()
        scopes.extend(scope.children)
        for step in (
            *scope.scope_steps,
            *(item for goal in scope.goals for item in goal.steps),
        ):
            yield from step.evidence


def _execution_steps(root_scope):
    scopes = [root_scope]
    while scopes:
        scope = scopes.pop()
        scopes.extend(scope.children)
        yield from scope.scope_steps
        for goal in scope.goals:
            yield from goal.steps


def test_verified_execution_uses_one_generic_macro_subplan(tmp_path) -> None:
    result, _fixture = _execute(
        tmp_path,
        "tj-2026-heping-yimo-25",
        load_v3_fixture_payload("tj-2026-heping-yimo-25"),
    )
    verified = result.verified_execution
    checkpoint = result.checkpoint

    assert verified is not None and checkpoint is not None
    assert verified.root_scope is checkpoint.root_scope
    assert verified.plan_id == checkpoint.plan_id
    assert verified.checkpoint_id == checkpoint.checkpoint_id
    restored = VerifiedFunctionalPlanExecution.from_payload(
        verified.to_payload()
    )
    assert restored.execution_id == verified.execution_id
    assert restored.execution_signature == verified.execution_signature

    subplans = tuple(
        item
        for item in _execution_evidence(verified.root_scope)
        if isinstance(item, VerifiedSubplanExecution)
    )
    macro_subplans = tuple(
        item
        for item in subplans
        if isinstance(item.selection, MacroSearchSelection)
    )
    assert len(macro_subplans) == 1
    subplan = macro_subplans[0]
    assert VerifiedSubplanExecution.from_payload(
        subplan.to_payload()
    ).execution_signature == subplan.execution_signature
    assert subplan.witness.standard_results["minimum_expression"] == (
        "3*sqrt(2*a**2 + 1)/Abs(a)"
    )
    assert {
        item.check_code for item in subplan.clean_execution.verification
    } >= {"distance_equality", "path_minimum_attained"}

    mutated = verified.to_payload()
    mutated["problem_semantic_hash"] = "drift"
    with pytest.raises(ValueError, match="hash drift"):
        VerifiedFunctionalPlanExecution.from_payload(mutated)


def test_non_path_macro_uses_same_verified_execution_envelope(tmp_path) -> None:
    result, _fixture = _execute(
        tmp_path,
        "tj-2026-nankai-yimo-25",
        load_v3_fixture_payload("tj-2026-nankai-yimo-25"),
    )
    verified = result.verified_execution

    assert verified is not None
    evidence = tuple(_execution_evidence(verified.root_scope))
    assert evidence
    assert all(isinstance(item, VerifiedSubplanExecution) for item in evidence)
    assert any(
        isinstance(item.selection, SingleFragmentSelection)
        for item in evidence
    )
    assert any(step.actual_outputs for step in _execution_steps(verified.root_scope))
    assert VerifiedFunctionalPlanExecution.from_payload(
        verified.to_payload()
    ).execution_id == verified.execution_id


def test_incomplete_checkpoint_cannot_be_promoted(tmp_path) -> None:
    result, _fixture = _execute(
        tmp_path,
        "tj-2026-heping-yimo-25",
        load_v3_fixture_payload("tj-2026-heping-yimo-25"),
    )
    assert result.checkpoint is not None and result.canonical_plan is not None
    incomplete = replace(result.checkpoint, transaction_ok=False)

    with pytest.raises(ValueError, match="incomplete checkpoint"):
        VerifiedFunctionalPlanExecution.from_checkpoint(
            canonical_plan=result.canonical_plan,
            checkpoint=incomplete,
        )


@pytest.mark.parametrize(
    ("filename", "runtime_schema"),
    (
        (
            "functional-goal-execution-checkpoint.schema.json",
            functional_goal_execution_checkpoint_schema,
        ),
        (
            "planner-goal-retry-context.schema.json",
            planner_goal_retry_context_schema,
        ),
        (
            "verified-functional-plan-execution.schema.json",
            verified_functional_plan_execution_schema,
        ),
    ),
)
def test_execution_authority_schema_snapshots_match_runtime(
    filename,
    runtime_schema,
) -> None:
    assert json.loads((SCHEMAS / filename).read_text(encoding="utf-8")) == (
        runtime_schema()
    )


def test_checkpoint_v1_is_rejected(tmp_path) -> None:
    result, _fixture = _execute(
        tmp_path,
        "tj-2026-heping-yimo-25",
        load_v3_fixture_payload("tj-2026-heping-yimo-25"),
    )
    assert result.checkpoint is not None
    legacy = result.checkpoint.authority_payload()
    legacy["schema_version"] = "functional-goal-execution-checkpoint/v1"

    with pytest.raises(ValueError):
        FunctionalGoalExecutionCheckpoint.from_payload(legacy)
