"""Authenticated problem authority consumed by the Strategy Planner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContext,
    ProblemPlanningContextProjector,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityError,
    VerifiedSolverProblemBundle,
)


@dataclass(frozen=True)
class VerifiedPlannerProblemAuthority:
    """One immutable Bundle and its deterministic Planner-facing projection."""

    bundle: VerifiedSolverProblemBundle
    planning_context: ProblemPlanningContext

    def __post_init__(self) -> None:
        if self.planning_context.bundle_authority_token != self.bundle.authority_token:
            raise ProblemBundleAuthorityError(
                "planner.problem_revision_drift",
                "$.planning_context.bundle_authority_token",
                "Planner context was not derived from the supplied problem bundle",
            )
        if self.planning_context.problem_id != self.bundle.verified_problem.graph.problem_id:
            raise ProblemBundleAuthorityError(
                "planner.problem_bundle_invalid",
                "$.planning_context.problem_id",
                "Planner context and problem bundle use different problem ids",
            )
        if self.planning_context.family_id != self.bundle.verified_problem.family_id:
            raise ProblemBundleAuthorityError(
                "planner.problem_bundle_invalid",
                "$.planning_context.family_id",
                "Planner context and problem bundle use different families",
            )

    @classmethod
    def from_bundle(
        cls,
        bundle: VerifiedSolverProblemBundle,
    ) -> "VerifiedPlannerProblemAuthority":
        return cls(
            bundle=bundle,
            planning_context=ProblemPlanningContextProjector().project(
                bundle,
                expected_token=bundle.authority_token,
            ),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "bundle": self.bundle.authority_payload(),
            "planning_context": self.planning_context.authority_payload(),
        }
