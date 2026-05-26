"""Solver entrypoint."""

from __future__ import annotations

from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.result_models import SolverResult
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


def solve_problem(
    problem_ir: ProblemIR,
    runtime_config: SolverRuntimeConfig | None = None,
) -> SolverResult:
    """使用通用 RuntimeOrchestrator 求解结构化题目。"""
    if runtime_config is None:
        return RuntimeOrchestrator().solve(problem_ir)
    return RuntimeOrchestrator(
        planner_providers=runtime_config.build_planner_providers(),
    ).solve(problem_ir)
