from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXTRACTION = ROOT / "shuxueshuo_server/solver/extraction"


def test_retired_problem_ir_authoring_chain_is_physically_absent() -> None:
    retired_files = (
        "problem_ir_authoring.py",
        "problem_ir_extraction.py",
        "problem_ir_service.py",
        "problem_ir_debug.py",
        "problem_ir_smoke.py",
    )

    assert all(not (EXTRACTION / name).exists() for name in retired_files)


def test_production_extraction_has_no_retired_authoring_or_full_retry_symbols() -> None:
    retired_symbols = (
        "ProblemIRAuthoringCandidate",
        "ProblemIRAuthoringCompiler",
        "ProblemSemanticModel",
        "ExtractedProblemIRValidator",
        "ProblemIRExtractionService",
        "problem-ir-authoring/v2",
        "solver-llm-problem-ir",
    )
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in EXTRACTION.glob("*.py")
        if path.name != "problem_ir_runtime_preflight.py"
    )

    for symbol in retired_symbols:
        assert symbol not in source


def test_domain_smoke_cannot_call_planner_or_full_solver() -> None:
    source = (EXTRACTION / "problem_domain_smoke.py").read_text(encoding="utf-8")

    assert "solve_problem" not in source
    assert "StrategyPlanner" not in source
    assert "--skip-solver" not in source
    assert '"planner_call_count": 0' in source
    assert '"solver_call_count": 0' in source
