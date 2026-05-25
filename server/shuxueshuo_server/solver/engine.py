"""Solver entrypoint."""

from __future__ import annotations

from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.result_models import SolverResult
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


def solve_problem(problem_ir: ProblemIR) -> SolverResult:
    """使用通用 RuntimeOrchestrator 求解结构化题目。"""
    return RuntimeOrchestrator().solve(problem_ir)
