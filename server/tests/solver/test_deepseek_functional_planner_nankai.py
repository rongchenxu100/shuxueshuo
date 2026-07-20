"""Real DeepSeek FunctionalPlan opt-in for the Nankai solver fixture.

Run explicitly:

    cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_FUNCTIONAL_PLANNER=1 \
      uv run pytest tests/solver/test_deepseek_functional_planner_nankai.py -q -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest
import sympy as sp

from shuxueshuo_server.solver import load_expected_answers
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.strategy_payload import (
    write_strategy_debug_artifacts,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)


RUN_FUNCTIONAL = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_FUNCTIONAL_PLANNER") == "1"
)
MAX_ATTEMPTS = int(os.getenv("DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS", "3"))
REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = REPO_ROOT / "internal" / "solver-fixtures" / "tj-2026-nankai-yimo-25.json"
EXPECTED = Path("tests/solver/expected/tj-2026-nankai-yimo-25.expected.json")
DEFAULT_DEBUG_DIR = (
    REPO_ROOT
    / "internal"
    / "solver-runs"
    / "strategy-planner-deepseek-functional-nankai"
)
DEBUG_DIR = Path(
    os.getenv("DEEPSEEK_FUNCTIONAL_PLANNER_DEBUG_DIR", str(DEFAULT_DEBUG_DIR))
).expanduser().resolve()
SAMPLE_ID = os.getenv("DEEPSEEK_FUNCTIONAL_PLANNER_SAMPLE_ID", "single")


@pytest.mark.skipif(
    not RUN_FUNCTIONAL,
    reason="set RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_FUNCTIONAL_PLANNER=1",
)
def test_deepseek_functional_plan_solves_nankai_without_protocol_fallback() -> None:
    _reset_debug_dir(DEBUG_DIR)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
    )
    if not config.deepseek_api_key:
        pytest.skip("DEEPSEEK_API_KEY is not configured")
    client = config.build_llm_client()
    problem = load_problem_ir(FIXTURE)
    expected = load_expected_answers(EXPECTED)
    orchestrator = RuntimeOrchestrator(
        planner_providers={},
        default_planner_provider=strategy_planner_provider(
            mode="deepseek",
            client=client,
            functional_few_shot_mode="strict_test",
            output_format="functional_plan",
        ),
        max_attempts=MAX_ATTEMPTS,
        debug_dir=DEBUG_DIR,
    )

    result = orchestrator.solve(problem)
    _write_sample_result(
        DEBUG_DIR,
        sample_id=SAMPLE_ID,
        result=result,
        attempt_count=(
            len(orchestrator.last_session.attempts)
            if orchestrator.last_session is not None
            else 0
        ),
    )

    assert result.status == "ok", result.errors
    assert all(check.ok for check in result.checks)
    assert result.answers["i"]["D"] == expected["i"]["D"]
    assert sp.simplify(
        sp.sympify(result.answers["i"]["parabola"])
        - sp.sympify(expected["i"]["parabola"])
    ) == 0
    assert result.answers["ii_1"]["min_value"] == expected["ii_1"]["min_value"]
    assert result.answers["ii_2"]["G"] == expected["ii_2"]["G"]

    success = orchestrator.last_success_artifacts
    assert success is not None
    planner = success.planner
    artifacts = planner.artifacts
    replay = artifacts.retry_replay_result
    assert replay is not None and replay.functional_plan is not None
    assert artifacts.candidate_format == "functional_plan"
    assert artifacts.raw_response is not None
    assert '"format":"step_intent"' not in artifacts.raw_response.replace(" ", "")
    write_strategy_debug_artifacts(
        DEBUG_DIR,
        payload=artifacts.payload or {},
        prompt=artifacts.prompt,
        raw_response=artifacts.raw_response,
        draft=replay.raw_draft,
        report=replay.functional_validation_report,
        normalization_report=replay.normalization_report,
        resolution_report=replay.resolution_report,
        execution_diagnostic=replay.diagnostic,
        effective_draft=replay.effective_draft,
        planner_retry_state=replay.retry_state,
        planner_state_context=replay.planner_state_context,
        functional_plan=replay.functional_plan,
        functional_reconciliation=replay.functional_reconciliation,
        llm_metadata={
            "provider": "deepseek",
            "response_model": getattr(client, "last_response_model", None),
            "usage": getattr(client, "last_usage", None),
            "attempts": len(orchestrator.last_session.attempts),
        },
    )
    assert (DEBUG_DIR / "functional-plan.json").exists()
    assert (DEBUG_DIR / "functional-reconciliation-report.json").exists()


def _reset_debug_dir(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if path == DEFAULT_DEBUG_DIR and child.name == "batches":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _write_sample_result(
    path: Path,
    *,
    sample_id: str,
    result: object,
    attempt_count: int,
) -> None:
    payload = {
        "sample_id": sample_id,
        "status": getattr(result, "status", None),
        "attempt_count": attempt_count,
        "answers": getattr(result, "answers", {}),
        "errors": getattr(result, "errors", []),
        "checks": [
            {"ok": getattr(check, "ok", False), "message": str(check)}
            for check in getattr(result, "checks", [])
        ],
    }
    path.mkdir(parents=True, exist_ok=True)
    (path / "sample-result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
