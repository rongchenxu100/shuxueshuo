"""Project verified runtime evidence into student-safe teaching facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, TypeVar

from shuxueshuo_server.solver.runtime.functional_execution_authority import (
    FunctionalExecutionEvidence,
    PathMinimumPromptWitnessProjector,
    PathMinimumWitness,
    SymbolicClosureExecutionEvidence,
)


SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT = (
    "symbolic-closure-teaching-evidence/v1"
)


class TeachingEvidenceProjectionError(ValueError):
    """One verified evidence value has no complete public teaching projection."""


@dataclass(frozen=True)
class ProjectedTeachingEvidence:
    evidence_ref: str
    payload: Mapping[str, Any]
    calculations: tuple[Mapping[str, Any], ...] = ()
    checks: tuple[Mapping[str, Any], ...] = ()


EvidenceT = TypeVar("EvidenceT", bound=FunctionalExecutionEvidence)


class TeachingEvidenceProjector(Protocol[EvidenceT]):
    def project(
        self,
        evidence: EvidenceT,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence: ...


class PathMinimumTeachingEvidenceProjector:
    """Expose the verified equivalence, locus, reflection and attainment proof."""

    def project(
        self,
        evidence: PathMinimumWitness,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        if planning_context is None:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_planning_context_missing: "
                f"step={evidence.step_id}"
            )
        payload = PathMinimumPromptWitnessProjector().project(
            evidence,
            planning_context,
        ).to_payload()
        calculations: list[dict[str, Any]] = [
            {
                "calculation_id": "path_equivalence",
                "kind": "equivalence_chain",
                "statements": list(payload["equivalence_proof"]),
                "result": (
                    f'{payload["original_objective"]}='
                    f'{payload["reduced_objective"]}'
                ),
            }
        ]
        for index, construction in enumerate(payload.get("constructions", ())):
            if not isinstance(construction, Mapping):
                continue
            kind = str(construction.get("kind") or f"construction_{index + 1}")
            calculations.append(
                {
                    "calculation_id": f"path_construction_{index + 1}",
                    "kind": kind,
                    "facts": dict(construction),
                }
            )
        calculations.extend(
            (
                {
                    "calculation_id": "path_minimum",
                    "kind": "minimum",
                    "strategy": payload["minimum_strategy"],
                    "expression": payload["minimum_expression"],
                },
                {
                    "calculation_id": "path_attainment",
                    "kind": "attainment",
                    "points": dict(payload["minimizing_points"]),
                },
            )
        )
        checks: list[dict[str, Any]] = []
        for attainment_index, attainment in enumerate(
            payload.get("attainment_checks", ())
        ):
            if not isinstance(attainment, Mapping):
                continue
            for check_index, check in enumerate(attainment.get("checks", ())):
                if not isinstance(check, Mapping):
                    continue
                checks.append(
                    {
                        "check_id": (
                            f"path_attainment_{attainment_index + 1}_"
                            f"{check_index + 1}"
                        ),
                        "kind": str(check.get("check") or "attainment"),
                        "passed": bool(check.get("passed")),
                        **(
                            {"parameter": str(check["parameter"])}
                            if check.get("parameter") is not None
                            else {}
                        ),
                    }
                )
        return ProjectedTeachingEvidence(
            evidence_ref=f"path-minimum:{evidence.witness_id}",
            payload=payload,
            calculations=tuple(calculations),
            checks=tuple(checks),
        )


class SymbolicClosureTeachingEvidenceProjector:
    """Expose only the public algebra used to select the verified solution."""

    def project(
        self,
        evidence: SymbolicClosureExecutionEvidence,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        del planning_context
        payload = {
            "schema_version": SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT,
            "step_id": evidence.step_id,
            "target": evidence.target,
            "target_value": evidence.target_value,
            "equations": list(evidence.equations),
            "equation_sources": list(evidence.equation_sources),
            "substitutions": [
                {"symbol": symbol, "value": value}
                for symbol, value in evidence.substitutions
            ],
            "branch_count": evidence.branch_count,
            "residual_symbols": list(evidence.residual_symbols),
            "affected_returns": list(evidence.affected_returns),
            "constraint_summary": evidence.constraint_summary,
        }
        calculations: list[dict[str, Any]] = [
            {
                "calculation_id": "symbolic_equations",
                "kind": "equation_system",
                "equations": list(evidence.equations),
                "sources": list(evidence.equation_sources),
            }
        ]
        if evidence.substitutions:
            calculations.append(
                {
                    "calculation_id": "symbolic_substitutions",
                    "kind": "substitution",
                    "values": [
                        {"symbol": symbol, "value": value}
                        for symbol, value in evidence.substitutions
                    ],
                }
            )
        calculations.append(
            {
                "calculation_id": "symbolic_solution",
                "kind": "solution",
                "target": evidence.target,
                "value": evidence.target_value,
            }
        )
        checks = (
            {
                "check_id": "symbolic_unique_branch",
                "kind": "unique_solution_branch",
                "passed": evidence.branch_count == 1
                and not evidence.residual_symbols,
                "branch_count": evidence.branch_count,
                "residual_symbols": list(evidence.residual_symbols),
            },
            *(
                (
                    {
                        "check_id": "symbolic_constraint_filter",
                        "kind": "constraint_filter",
                        "passed": True,
                        "summary": evidence.constraint_summary,
                    },
                )
                if evidence.constraint_summary
                else ()
            ),
        )
        return ProjectedTeachingEvidence(
            evidence_ref=f"symbolic-closure:{evidence.evidence_id}",
            payload=payload,
            calculations=tuple(calculations),
            checks=tuple(checks),
        )


class TeachingEvidenceProjectorRegistry:
    """Exact-type registry; unknown verified evidence fails loudly."""

    def __init__(self) -> None:
        self._projectors: dict[type[Any], TeachingEvidenceProjector[Any]] = {}

    def register(
        self,
        evidence_type: type[EvidenceT],
        projector: TeachingEvidenceProjector[EvidenceT],
    ) -> None:
        if evidence_type in self._projectors:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_evidence_projector_duplicate: "
                f"{evidence_type.__name__}"
            )
        self._projectors[evidence_type] = projector

    def project(
        self,
        evidence: FunctionalExecutionEvidence,
        *,
        planning_context: Any | None,
    ) -> ProjectedTeachingEvidence:
        projector = self._projectors.get(type(evidence))
        if projector is None:
            raise TeachingEvidenceProjectionError(
                "teaching_projection_evidence_projector_missing: "
                f"evidence={type(evidence).__name__}"
            )
        return projector.project(
            evidence,
            planning_context=planning_context,
        )


def default_teaching_evidence_projector_registry(
) -> TeachingEvidenceProjectorRegistry:
    registry = TeachingEvidenceProjectorRegistry()
    registry.register(PathMinimumWitness, PathMinimumTeachingEvidenceProjector())
    registry.register(
        SymbolicClosureExecutionEvidence,
        SymbolicClosureTeachingEvidenceProjector(),
    )
    return registry


__all__ = [
    "PathMinimumTeachingEvidenceProjector",
    "ProjectedTeachingEvidence",
    "SYMBOLIC_CLOSURE_TEACHING_EVIDENCE_CONTRACT",
    "SymbolicClosureTeachingEvidenceProjector",
    "TeachingEvidenceProjectionError",
    "TeachingEvidenceProjector",
    "TeachingEvidenceProjectorRegistry",
    "default_teaching_evidence_projector_registry",
]
