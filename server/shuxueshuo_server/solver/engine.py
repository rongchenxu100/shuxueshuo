"""Solver entrypoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.result_models import SolverResult
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator

if TYPE_CHECKING:
    from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
        VerifiedSolverProblemBundle,
    )


def solve_problem(
    problem: "VerifiedSolverProblemBundle",
    runtime_config: SolverRuntimeConfig | None = None,
) -> SolverResult:
    """从authenticated problem Bundle运行生产Strategy Solver。"""
    from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
        ProblemBundleAuthorityError,
        VerifiedSolverProblemBundle,
    )

    if not isinstance(problem, VerifiedSolverProblemBundle):
        raise ProblemBundleAuthorityError(
            "planner.problem_bundle_required",
            "$",
            "solve_problem requires VerifiedSolverProblemBundle; use "
            "solve_problem_ir_debug for deterministic ProblemIR tests",
        )
    if runtime_config is None:
        return RuntimeOrchestrator().solve_verified(problem)
    if runtime_config.planner_mode != "strategy":
        raise ProblemBundleAuthorityError(
            "planner.problem_bundle_required",
            "$.runtime_config.planner_mode",
            "verified bundle entry requires the Strategy planner",
        )
    return RuntimeOrchestrator(
        family_registry=runtime_config.build_family_registry(),
        planner_providers=runtime_config.build_planner_providers(),
        default_planner_provider=runtime_config.build_default_planner_provider(),
        max_attempts=runtime_config.max_llm_attempts
        if runtime_config.planner_mode == "strategy"
        and runtime_config.llm_provider == "deepseek"
        else 1,
        debug_dir=runtime_config.llm_debug_dir,
    ).solve_verified(problem)


def solve_problem_ir_debug(
    problem_ir: ProblemIR,
    runtime_config: SolverRuntimeConfig | None = None,
) -> SolverResult:
    """显式运行不带extraction authority的deterministic/debug入口。"""
    config = runtime_config or SolverRuntimeConfig(planner_mode="deterministic")
    if config.planner_mode != "deterministic":
        from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
            ProblemBundleAuthorityError,
        )

        raise ProblemBundleAuthorityError(
            "planner.problem_bundle_required",
            "$.runtime_config.planner_mode",
            "Strategy planning cannot consume a bare ProblemIR",
        )
    return RuntimeOrchestrator(
        family_registry=config.build_family_registry(),
        planner_providers=config.build_planner_providers(),
        default_planner_provider=config.build_default_planner_provider(),
        max_attempts=1,
        debug_dir=config.llm_debug_dir,
    ).solve(problem_ir)
