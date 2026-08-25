from __future__ import annotations

from dataclasses import replace
import inspect
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.engine import solve_problem
from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.problem_cold_path import (
    ProblemColdPathService,
)
from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityError,
)
from shuxueshuo_server.solver.result_models import SolverResult
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.strategy_payload import StrategyPayloadBuilder
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    StrategyPlanner,
    strategy_planner_provider,
)

from _problem_planning_support import (
    CASES,
    accepted_bundle_fixture,
    planning_binding_fixture,
)


@pytest.mark.parametrize("case", CASES)
def test_verified_bundle_is_the_default_recorded_strategy_entry(
    tmp_path,
    case: str,
) -> None:
    bundle, planning_context, *_ = planning_binding_fixture(
        tmp_path / case,
        case=case,
    )
    config = SolverRuntimeConfig(planner_mode="strategy", llm_provider="recorded")
    orchestrator = RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        planner_providers=config.build_planner_providers(),
        default_planner_provider=config.build_default_planner_provider(),
    )

    result = orchestrator.solve_verified(bundle)

    assert result.ok, result.errors
    success = orchestrator.last_success_artifacts
    assert success is not None
    assert success.problem_authority is not None
    assert success.problem_authority.bundle.authority_token == bundle.authority_token
    assert (
        success.problem_authority.planning_context.planning_context_id
        == planning_context.planning_context_id
    )
    assert success.problem_binding_catalog is not None
    assert success.planner_state_context is not None
    artifacts = success.planner.artifacts
    assert artifacts.problem_authority == success.problem_authority
    assert artifacts.problem_binding_catalog == success.problem_binding_catalog
    payload = artifacts.payload
    assert payload is not None
    assert "problem_ir" not in payload
    prompt_context = payload["problem_planning_context"]
    assert prompt_context["schema_version"] == "planner-problem-view/v2"
    assert prompt_context["root_scope"]["id"] == "problem"


def test_public_strategy_entry_rejects_bare_problem_ir(tmp_path) -> None:
    _bundle, _planning_context, problem, *_ = planning_binding_fixture(tmp_path)
    with pytest.raises(ProblemBundleAuthorityError) as caught:
        solve_problem(problem)

    assert caught.value.code == "planner.problem_bundle_required"
    assert caught.value.retryable is False


def test_strategy_planner_requires_problem_bundle_authority(tmp_path) -> None:
    _bundle, _planning_context, problem, *_ = planning_binding_fixture(tmp_path)

    with pytest.raises(ProblemBundleAuthorityError) as caught:
        StrategyPlanner(
            ContextBuilder().build(problem),
            problem_authority=None,  # type: ignore[arg-type]
        )

    assert caught.value.code == "planner.problem_bundle_required"


def test_public_verified_entry_never_calls_legacy_v1_planner(
    monkeypatch,
    tmp_path,
) -> None:
    """The public Bundle API must terminate in Goal checkpoint v3."""

    bundle, *_ = planning_binding_fixture(
        tmp_path,
        case="tj-2026-nankai-yimo-25",
    )
    monkeypatch.setattr(
        StrategyPlanner,
        "plan",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy functional_plan/v1 planner must not run")
        ),
    )
    orchestrator = RuntimeOrchestrator()

    result = orchestrator.solve_verified(bundle)

    assert result.ok, result.errors
    success = orchestrator.last_success_artifacts
    assert success is not None
    artifacts = success.planner.artifacts
    assert artifacts.scoped_retry_result is not None
    assert artifacts.scoped_retry_result.status == "accepted"
    checkpoint = artifacts.scoped_retry_result.final_execution.checkpoint
    assert checkpoint.schema_version == "functional-goal-execution-checkpoint/v4"
    assert checkpoint.all_required_goals_verified
    assert success.verified_functional_execution is not None


def test_strategy_provider_requires_problem_bundle_authority(tmp_path) -> None:
    _bundle, _planning_context, problem, *_ = planning_binding_fixture(tmp_path)

    with pytest.raises(ProblemBundleAuthorityError) as caught:
        strategy_planner_provider()(ContextBuilder().build(problem))

    assert caught.value.code == "planner.problem_bundle_required"


def test_low_level_problem_ir_entry_rejects_default_strategy(tmp_path) -> None:
    _bundle, _planning_context, problem, *_ = planning_binding_fixture(tmp_path)

    result = RuntimeOrchestrator().solve(problem)

    assert result.status == "failed"
    assert any("planner.problem_bundle_required" in error for error in result.errors)


def test_verified_planner_authority_rejects_token_drift(tmp_path) -> None:
    bundle, planning_context, *_ = planning_binding_fixture(tmp_path)
    drifted = replace(
        planning_context,
        bundle_authority_token=replace(
            planning_context.bundle_authority_token,
            bundle_id="verified-solver-problem-bundle:" + "0" * 64,
        ),
    )

    with pytest.raises(ProblemBundleAuthorityError) as caught:
        VerifiedPlannerProblemAuthority(bundle=bundle, planning_context=drifted)

    assert caught.value.code == "planner.problem_revision_drift"


def test_cold_path_loads_accepted_bundle_before_solver(tmp_path) -> None:
    root, parent, accepted, store, *_ = accepted_bundle_fixture(tmp_path)
    extraction = SimpleNamespace(
        accepted=True,
        final_context=accepted,
        attempts=(),
    )
    extraction_service = _FakeExtractionService(extraction, store)
    calls: list[str] = []

    def solve(bundle, config):
        calls.append(bundle.authority_token.bundle_id)
        assert config.planner_mode == "strategy"
        return SolverResult(
            problem_id=bundle.verified_problem.graph.problem_id,
            status="ok",
            solver_family=bundle.verified_problem.family_id,
        )

    result = ProblemColdPathService(
        extraction_service,
        solver=solve,
    ).run(
        parent,
        ExtractionAttemptLedger.for_context(parent),
        (root,),
        solver_runtime_config=SolverRuntimeConfig(),
    )

    assert result.accepted
    assert result.solved
    assert result.bundle is not None
    assert result.problem_authority is not None
    assert calls == [result.bundle.authority_token.bundle_id]
    assert extraction_service.run_count == 1


def test_cold_path_does_not_call_planner_when_extraction_blocks(tmp_path) -> None:
    root, parent, _accepted, store, *_ = accepted_bundle_fixture(tmp_path)
    blocked = replace(
        parent,
        projection=replace(parent.projection, status="blocked"),
    )
    extraction = SimpleNamespace(
        accepted=False,
        final_context=blocked,
        attempts=(),
    )
    extraction_service = _FakeExtractionService(extraction, store)
    solver_calls = 0

    def solve(_bundle, _config):
        nonlocal solver_calls
        solver_calls += 1
        raise AssertionError("blocked extraction must not call the Solver")

    result = ProblemColdPathService(
        extraction_service,
        solver=solve,
    ).run(
        parent,
        ExtractionAttemptLedger.for_context(parent),
        (root,),
        solver_runtime_config=SolverRuntimeConfig(),
    )

    assert result.accepted is False
    assert result.bundle is None
    assert result.solver_result is None
    assert extraction_service.run_count == 1
    assert solver_calls == 0


def test_strategy_prompt_builder_has_no_flat_problem_fallback() -> None:
    source = inspect.getsource(StrategyPayloadBuilder.build)
    planner_source = inspect.getsource(StrategyPlanner)

    assert "semantic_read_catalog(" not in source
    assert '"problem_ir"' not in source
    assert "problem_binding_catalog" in planner_source
    assert "problem_authority" in planner_source


class _FakeExtractionService:
    def __init__(self, result, output_artifact_store) -> None:
        self.result = result
        self.output_artifact_store = output_artifact_store
        self.run_count = 0

    def run(self, *_args, **_kwargs):
        self.run_count += 1
        return self.result
