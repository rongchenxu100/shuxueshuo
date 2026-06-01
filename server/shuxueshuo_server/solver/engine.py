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
        family_registry=runtime_config.build_family_registry(),
        planner_providers=runtime_config.build_planner_providers(),
        max_attempts=runtime_config.max_llm_attempts
        if runtime_config.planner_mode == "llm"
        else 1,
        debug_dir=runtime_config.llm_debug_dir,
    ).solve(problem_ir)
