from __future__ import annotations

import json

import pytest

from _problem_planning_support import cached_planning_binding_fixture

from shuxueshuo_server.solver.explanation import ExplanationSnapshotBuilder
from shuxueshuo_server.solver.explanation.evidence_projectors import (
    SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT,
    TeachingEvidenceProjectionError,
    default_teaching_evidence_projector_registry,
)
from shuxueshuo_server.solver.explanation.models import iter_teaching_sources
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import CASE_ID
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    SymbolicClosureExecutionEvidence,
    functional_execution_evidence_from_payload,
)
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


@pytest.fixture(scope="module")
def snapshot():
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=config.max_llm_attempts,
    )
    bundle, *_ = cached_planning_binding_fixture(CASE_ID)
    result = orchestrator.solve_verified(bundle)
    assert result.status == "ok", result.errors
    return ExplanationSnapshotBuilder().build(orchestrator.last_success_artifacts)


def test_path_minimum_projector_exposes_complete_public_proof(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "derive_path_minimum_ii"
    )
    source_evidence = snapshot.evidence_for_step(source.source_step_id)
    assert len(source_evidence) == 1
    evidence = source_evidence[0]

    assert evidence["schema_version"] == "path-minimum-prompt-witness/v1"
    assert evidence["original_objective"] == "HF+FM+MG"
    assert evidence["reduced_objective"] == "AG+MG"
    assert len(source.calculations) == 5
    assert {item["calculation_id"] for item in source.calculations} == {
        "path_equivalence",
        "path_construction_1",
        "path_construction_2",
        "path_minimum",
        "path_attainment",
    }
    assert all(item["passed"] for item in source.checks)


def test_symbolic_closure_is_public_evidence_not_transaction_state(snapshot) -> None:
    source = next(
        item
        for item in iter_teaching_sources(snapshot.root_scope)
        if item.source_step_id == "solve_parameter_c_ii"
    )
    source_evidence = snapshot.evidence_for_step(source.source_step_id)
    assert len(source_evidence) == 1
    evidence = source_evidence[0]
    text = json.dumps(evidence, ensure_ascii=False)

    assert evidence["schema_version"] == (
        SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT
    )
    assert evidence["target"] == "c"
    assert evidence["target_value"] == "5"
    assert evidence["branch_count"] == 1
    assert [item["calculation_id"] for item in source.calculations] == [
        "symbolic_equations",
        "symbolic_substitutions",
        "symbolic_solution",
    ]
    for forbidden in (
        "StateVersion",
        "checkpoint",
        "MathObjectId",
        "transaction",
        "provenance_signature",
    ):
        assert forbidden not in text


def test_symbolic_execution_evidence_round_trips_strictly() -> None:
    evidence = SymbolicClosureExecutionEvidence(
        step_id="solve_parameter",
        target="a",
        target_value="3/4",
        equations=("Eq(4*a, 3)",),
        equation_sources=("expression", "condition"),
        substitutions=(("a", "3/4"),),
        branch_count=1,
        residual_symbols=(),
        affected_returns=("parameter_value",),
        constraint_summary="题设范围筛选出唯一解",
    )
    hydrated = functional_execution_evidence_from_payload(evidence.to_payload())
    assert hydrated == evidence


def test_evidence_registry_uses_exact_type_and_unknown_evidence_fails_loud() -> None:
    registry = default_teaching_evidence_projector_registry()
    with pytest.raises(
        TeachingEvidenceProjectionError,
        match="evidence_projector_missing",
    ):
        registry.project(object(), planning_context=None)  # type: ignore[arg-type]
