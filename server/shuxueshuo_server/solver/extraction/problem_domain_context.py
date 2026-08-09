"""Trusted Context v3 transitions for validated problem-domain state."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Sequence

from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ExtractionAttemptLedger,
    ExtractionIssue,
    ExtractionProjection,
    ExtractionRetryState,
    ExtractionState,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    VerifiedProblem,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    SolverProblemProjection,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    stable_hash,
)


class ProblemDomainContextTransitionService:
    """Commit either one blocked Draft or one accepted VerifiedProblem atomically."""

    def blocked(
        self,
        context: ProblemExtractionContext,
        *,
        draft: ProblemDraft,
        draft_artifact: ExtractionArtifactRef,
        validation_artifact: ExtractionArtifactRef,
        attempt_ledger: ExtractionAttemptLedger,
        artifacts: Sequence[ExtractionArtifactRef] = (),
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
    ) -> ProblemExtractionContext:
        _require_artifact(draft_artifact, "problem_draft")
        _require_artifact(validation_artifact, "problem_validation_report")
        if draft.validation_report.ok:
            raise _context_error(
                "$.projection",
                "blocked Context requires a Draft with blocking validation issues",
            )
        next_state = replace(
            context.state,
            artifacts=_merge_artifacts(
                context.state.artifacts,
                (*artifacts, draft_artifact, validation_artifact),
            ),
            issues=_merge_domain_issues(context.state.issues, draft),
        )
        return ProblemExtractionContextBuilder.trusted_child(
            context,
            state=next_state,
            attempt_ledger=attempt_ledger,
            event="problem_domain_blocked",
            event_payload={
                "problem_revision_id": draft.revision_id,
                "issue_signature": draft.validation_report.issue_signature,
            },
            ancestor_contexts=ancestor_contexts,
            producer="problem_domain_extraction",
            producer_version="v1",
            projection=ExtractionProjection(
                status="blocked",
                problem_draft_artifact_id=draft_artifact.artifact_id,
                problem_revision_id=draft.revision_id,
                validation_artifact_id=validation_artifact.artifact_id,
            ),
            retry=ExtractionRetryState(
                status="blocked",
                work_item_ids=tuple(
                    sorted({item.code for item in draft.validation_report.issues})
                ),
                attempt_budget=context.retry.attempt_budget,
                attempts_used=context.retry.attempts_used + len(attempt_ledger.attempts),
            ),
        )

    def blocked_without_draft(
        self,
        context: ProblemExtractionContext,
        *,
        issue_codes: Sequence[str],
        validation_artifact: ExtractionArtifactRef,
        attempt_ledger: ExtractionAttemptLedger,
        artifacts: Sequence[ExtractionArtifactRef] = (),
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
    ) -> ProblemExtractionContext:
        """Persist a terminal wire failure when no schema-valid Draft exists."""

        _require_artifact(validation_artifact, "problem_validation_report")
        next_state = replace(
            context.state,
            artifacts=_merge_artifacts(
                context.state.artifacts,
                (*artifacts, validation_artifact),
            ),
            issues=tuple(
                (
                    *context.state.issues,
                    *(
                        ExtractionIssue(
                            issue_id="problem-domain-issue:" + stable_hash({"code": code}),
                            code=code,
                            blocking=True,
                            retryable=False,
                        )
                        for code in sorted(set(issue_codes))
                    ),
                )
            ),
        )
        return ProblemExtractionContextBuilder.trusted_child(
            context,
            state=next_state,
            attempt_ledger=attempt_ledger,
            event="problem_domain_wire_blocked",
            event_payload={"issue_codes": sorted(set(issue_codes))},
            ancestor_contexts=ancestor_contexts,
            producer="problem_domain_extraction",
            producer_version="v1",
            projection=ExtractionProjection(
                status="blocked",
                validation_artifact_id=validation_artifact.artifact_id,
            ),
            retry=ExtractionRetryState(
                status="blocked",
                work_item_ids=tuple(sorted(set(issue_codes))),
                attempt_budget=context.retry.attempt_budget,
                attempts_used=context.retry.attempts_used + len(attempt_ledger.attempts),
            ),
        )

    def accepted(
        self,
        context: ProblemExtractionContext,
        *,
        verified_problem: VerifiedProblem,
        solver_projection: SolverProblemProjection,
        verified_artifact: ExtractionArtifactRef,
        solver_problem_ir_artifact: ExtractionArtifactRef,
        validation_artifact: ExtractionArtifactRef,
        attempt_ledger: ExtractionAttemptLedger,
        artifacts: Sequence[ExtractionArtifactRef] = (),
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
    ) -> ProblemExtractionContext:
        _require_artifact(verified_artifact, "verified_problem")
        _require_artifact(solver_problem_ir_artifact, "solver_problem_ir")
        _require_artifact(validation_artifact, "problem_validation_report")
        if (
            solver_projection.manifest.problem_revision_id
            != verified_problem.revision_id
            or solver_projection.manifest.problem_semantic_hash
            != verified_problem.semantic_hash
        ):
            raise _context_error(
                "$.projection",
                "Solver projection does not belong to the VerifiedProblem",
            )
        next_state = replace(
            context.state,
            artifacts=_merge_artifacts(
                context.state.artifacts,
                (
                    *artifacts,
                    verified_artifact,
                    solver_problem_ir_artifact,
                    validation_artifact,
                ),
            ),
        )
        return ProblemExtractionContextBuilder.trusted_child(
            context,
            state=next_state,
            attempt_ledger=attempt_ledger,
            event="problem_domain_accepted",
            event_payload={
                "problem_revision_id": verified_problem.revision_id,
                "problem_semantic_hash": verified_problem.semantic_hash,
                "family_id": verified_problem.family_id,
            },
            ancestor_contexts=ancestor_contexts,
            producer="problem_domain_extraction",
            producer_version="v1",
            projection=ExtractionProjection(
                status="accepted",
                verified_problem_artifact_id=verified_artifact.artifact_id,
                solver_problem_ir_artifact_id=solver_problem_ir_artifact.artifact_id,
                problem_revision_id=verified_problem.revision_id,
                problem_semantic_hash=verified_problem.semantic_hash,
                family_id=verified_problem.family_id,
                validation_artifact_id=validation_artifact.artifact_id,
            ),
            retry=ExtractionRetryState(
                status="complete",
                work_item_ids=(),
                attempt_budget=context.retry.attempt_budget,
                attempts_used=context.retry.attempts_used + len(attempt_ledger.attempts),
            ),
        )


def _merge_artifacts(
    prior: Sequence[ExtractionArtifactRef],
    added: Iterable[ExtractionArtifactRef],
) -> tuple[ExtractionArtifactRef, ...]:
    result = list(prior)
    by_id = {item.artifact_id: item for item in prior}
    for artifact in added:
        existing = by_id.get(artifact.artifact_id)
        if existing is not None:
            if existing.authority_payload() != artifact.authority_payload():
                raise _context_error(
                    "$.state.artifacts",
                    f"artifact authority drifted for {artifact.artifact_id!r}",
                )
            continue
        by_id[artifact.artifact_id] = artifact
        result.append(artifact)
    return tuple(result)


def _merge_domain_issues(
    prior: Sequence[ExtractionIssue],
    draft: ProblemDraft,
) -> tuple[ExtractionIssue, ...]:
    domain_codes = {item.code for item in draft.validation_report.issues}
    retained = [
        item for item in prior if not item.issue_id.startswith("problem-domain-issue:")
    ]
    retained.extend(
        ExtractionIssue(
            issue_id=(
                "problem-domain-issue:"
                + stable_hash(
                    {
                        "revision_id": draft.revision_id,
                        "code": code,
                    }
                )
            ),
            code=code,
            blocking=True,
            retryable=any(
                item.retryable
                for item in draft.validation_report.issues
                if item.code == code
            ),
        )
        for code in sorted(domain_codes)
    )
    return tuple(retained)


def _require_artifact(artifact: ExtractionArtifactRef, kind: str) -> None:
    if artifact.kind != kind:
        raise _context_error(
            "$.state.artifacts",
            f"expected {kind!r} artifact, got {artifact.kind!r}",
        )


def _context_error(path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(
        "extraction.context_hash_mismatch",
        path,
        message,
    )


__all__ = ["ProblemDomainContextTransitionService"]
