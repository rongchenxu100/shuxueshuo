"""Cold path from one pending extraction Context to the verified Solver."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Sequence

from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    ProblemDomainExtractionRunResult,
    ProblemDomainExtractionService,
)
from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    VerifiedSolverProblemBundle,
    VerifiedSolverProblemBundleLoader,
)
from shuxueshuo_server.solver.result_models import SolverResult
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


VerifiedSolver = Callable[
    [VerifiedSolverProblemBundle, SolverRuntimeConfig],
    SolverResult,
]


@dataclass(frozen=True)
class ProblemColdPathRunResult:
    extraction: ProblemDomainExtractionRunResult
    bundle: VerifiedSolverProblemBundle | None = None
    problem_authority: VerifiedPlannerProblemAuthority | None = None
    solver_result: SolverResult | None = None
    extraction_usage: dict[str, float] | None = None
    planner_usage: dict[str, int] | None = None
    extraction_latency_ms: int = 0
    planner_latency_ms: int = 0

    @property
    def accepted(self) -> bool:
        return self.extraction.accepted

    @property
    def solved(self) -> bool:
        return self.solver_result is not None and self.solver_result.ok

    def to_payload(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "solved": self.solved,
            "extraction_attempt_count": len(self.extraction.attempts),
            "extraction_context_id": self.extraction.final_context.manifest.context_id,
            "bundle_authority_token": (
                self.bundle.authority_token.to_payload()
                if self.bundle is not None
                else None
            ),
            "planning_context_id": (
                self.problem_authority.planning_context.planning_context_id
                if self.problem_authority is not None
                else None
            ),
            "solver_result": (
                self.solver_result.to_dict()
                if self.solver_result is not None
                else None
            ),
            "extraction_usage": dict(self.extraction_usage or {}),
            "planner_usage": dict(self.planner_usage or {}),
            "extraction_latency_ms": self.extraction_latency_ms,
            "planner_latency_ms": self.planner_latency_ms,
        }


class ProblemColdPathService:
    """Run extraction once, then solve only an authenticated accepted Bundle."""

    def __init__(
        self,
        extraction_service: ProblemDomainExtractionService,
        *,
        bundle_loader: VerifiedSolverProblemBundleLoader | None = None,
        solver: VerifiedSolver | None = None,
    ) -> None:
        self.extraction_service = extraction_service
        self.bundle_loader = bundle_loader or VerifiedSolverProblemBundleLoader()
        self.solver = solver or _solve_verified

    def run(
        self,
        f2_context: ProblemExtractionContext,
        extraction_attempt_ledger: ExtractionAttemptLedger,
        ancestor_contexts: Sequence[ProblemExtractionContext],
        *,
        extraction_max_attempts: int = 3,
        solver_runtime_config: SolverRuntimeConfig,
    ) -> ProblemColdPathRunResult:
        extraction_started = time.perf_counter()
        extraction = self.extraction_service.run(
            f2_context,
            attempt_ledger=extraction_attempt_ledger,
            max_attempts=extraction_max_attempts,
            ancestor_contexts=ancestor_contexts,
        )
        extraction_latency_ms = int(
            (time.perf_counter() - extraction_started) * 1000
        )
        extraction_usage = _extraction_usage(extraction)
        if not extraction.accepted:
            return ProblemColdPathRunResult(
                extraction=extraction,
                extraction_usage=extraction_usage,
                extraction_latency_ms=extraction_latency_ms,
            )

        bundle = self.bundle_loader.load(
            extraction.final_context,
            self.extraction_service.output_artifact_store,
            ancestor_contexts=(*ancestor_contexts, f2_context),
        )
        authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
        planner_started = time.perf_counter()
        solver_result = self.solver(bundle, solver_runtime_config)
        planner_latency_ms = int((time.perf_counter() - planner_started) * 1000)
        return ProblemColdPathRunResult(
            extraction=extraction,
            bundle=bundle,
            problem_authority=authority,
            solver_result=solver_result,
            extraction_usage=extraction_usage,
            planner_usage=_planner_usage(solver_result),
            extraction_latency_ms=extraction_latency_ms,
            planner_latency_ms=planner_latency_ms,
        )


def _solve_verified(
    bundle: VerifiedSolverProblemBundle,
    runtime_config: SolverRuntimeConfig,
) -> SolverResult:
    # Keep the public Solver import lazy so extraction model imports do not
    # create a family/runtime initialization cycle.
    from shuxueshuo_server.solver.engine import solve_problem

    return solve_problem(bundle, runtime_config=runtime_config)


def _extraction_usage(
    result: ProblemDomainExtractionRunResult,
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for attempt in result.attempts:
        response = attempt.provider_response
        if response is None or response.usage is None:
            continue
        for key, value in response.usage.items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0.0) + float(value)
    return totals


def _planner_usage(result: SolverResult) -> dict[str, int]:
    run_log = result.run_log
    if not isinstance(run_log, dict):
        return {}
    raw = run_log.get("total_usage")
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): int(value)
        for key, value in raw.items()
        if isinstance(value, int)
    }


__all__ = ["ProblemColdPathRunResult", "ProblemColdPathService"]
