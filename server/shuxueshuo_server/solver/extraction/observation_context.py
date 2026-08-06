"""Trusted attachment of F2 observations to immutable extraction Context."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ExtractionAttemptLedger,
    ExtractionEvidenceRecord,
    ExtractionIssue,
    ExtractionState,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.observations import (
    FormulaObservation,
    InkOriginObservation,
    SourceObservation,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    thaw_json,
)


class ObservationContextTransitionService:
    def attach(
        self,
        context: ProblemExtractionContext,
        observation: SourceObservation,
        *,
        artifacts: Sequence[ExtractionArtifactRef],
        attempt_ledger: ExtractionAttemptLedger,
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
    ) -> ProblemExtractionContext:
        current_hash = context.quality.get("source_observation_hash")
        if current_hash is not None:
            if str(current_hash) == observation.observation_hash:
                return context
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.quality.source_observation_hash",
                "a different observation is already attached",
            )
        if context.state.candidates:
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.state.candidates",
                "F2 observation must be attached before semantic candidates exist",
            )
        observation.validate(
            context.source,
            context.selection,
            context.dependency.dependency_hash,
        )
        if not attempt_ledger.attempts:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.attempts",
                "observation attachment requires provider attempts",
            )
        failed = [item.attempt_id for item in attempt_ledger.attempts if item.result != "succeeded"]
        if failed:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.attempts",
                f"failed provider attempts cannot produce an observation child: {failed}",
            )
        provider_ids = tuple(sorted(item.provider_id for item in observation.providers))
        expected_provider_ids = context.dependency.semantic_config.get("f2_provider_ids")
        if expected_provider_ids is not None and tuple(expected_provider_ids) != provider_ids:
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.dependency.semantic_config.f2_provider_ids",
                "observation providers differ from dependency authority",
            )

        artifact_by_id = {item.artifact_id: item for item in artifacts}
        if len(artifact_by_id) != len(tuple(artifacts)):
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.artifacts",
                "duplicate artifact id",
            )
        observation.validate_artifact_closure(set(artifact_by_id))
        observation_artifacts = [
            item for item in artifacts if item.kind == "source_observation"
        ]
        if len(observation_artifacts) != 1:
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.artifacts",
                "exactly one source_observation artifact is required",
            )
        page_artifact_ids = {page.source_artifact_id for page in observation.pages}
        if page_artifact_ids - set(artifact_by_id):
            raise ProblemExtractionContextError(
                "extraction.evidence_ref_unresolved",
                "$.pages.source_artifact_id",
                "canonical page artifact is missing",
            )
        output_artifact_ids = {
            artifact.artifact_id
            for attempt in attempt_ledger.attempts
            for artifact in attempt.output_artifact_refs
        }
        if output_artifact_ids - set(artifact_by_id):
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.output_artifact_refs",
                "provider output artifact is not attached to Context",
            )
        input_artifact_ids = {
            artifact.artifact_id
            for attempt in attempt_ledger.attempts
            for artifact in attempt.input_artifact_refs
        }
        if input_artifact_ids - set(artifact_by_id):
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.input_artifact_refs",
                "attempt input artifact is not attached to Context",
            )
        required_input_ids = {
            item.artifact_id
            for item in artifacts
            if item.kind
            in {"canonical_source_page", "selection_crop", "formula_crop"}
        }
        if required_input_ids - input_artifact_ids:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.input_artifact_refs",
                "source and crop artifacts are not traced to attempt inputs",
            )
        provider_artifact_ids = {
            item.artifact_id
            for item in artifacts
            if item.kind.startswith("provider_")
        }
        if provider_artifact_ids - output_artifact_ids:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.output_artifact_refs",
                "provider records are not traced to attempt outputs",
            )
        mask_artifact_ids = {
            item.mask_artifact_id
            for item in observation.ink_origins
            if item.mask_artifact_id is not None
        }
        if mask_artifact_ids - output_artifact_ids:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.output_artifact_refs",
                "handwriting masks are not traced to an attempt output",
            )
        formula_crop_ids = {
            item.crop_artifact_id
            for item in observation.formulas
            if item.crop_artifact_id is not None
        }
        if formula_crop_ids - input_artifact_ids:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.input_artifact_refs",
                "formula crops are not traced to a provider attempt input",
            )

        evidence = tuple(
            ExtractionEvidenceRecord(
                evidence_id=item.observation_id,
                artifact_id=item.source_artifact_id,
                page_id=item.page_id,
                payload={
                    "kind": _observation_kind(item.observation_id),
                    "polygon": [[x, y] for x, y in item.polygon],
                    "confidence": item.confidence,
                    "origin": item.origin,
                    "source_observation_artifact_id": observation_artifacts[0].artifact_id,
                    "derived_artifact_ids": list(_derived_artifact_ids(item)),
                },
            )
            for item in observation.spatial_observations
        )
        evidence_ids = {item.evidence_id for item in evidence}
        issues = tuple(
            ExtractionIssue(
                issue_id=item.issue_id,
                code=item.code,
                blocking=item.blocking,
                retryable=item.retryable,
                evidence_ids=tuple(
                    evidence_id
                    for evidence_id in item.observation_ids
                    if evidence_id in evidence_ids
                ),
            )
            for item in observation.issues
        )
        next_state = ExtractionState(
            artifacts=tuple(sorted(artifacts, key=lambda item: item.artifact_id)),
            evidence=evidence,
            scope_candidates=(),
            entity_candidates=(),
            fact_candidates=(),
            goal_candidates=(),
            issues=issues,
        )
        quality = dict(thaw_json(context.quality))
        quality.update(
            {
                "source_observation_hash": observation.observation_hash,
                "source_observation_artifact_id": observation_artifacts[0].artifact_id,
                "selected_observation_count": len(observation.selected_observation_ids),
                "layout_block_count": len(observation.layout_blocks),
                "text_span_count": len(observation.text_spans),
                "formula_count": len(observation.formulas),
                "ink_origin_count": len(observation.ink_origins),
                "observation_issue_count": len(observation.issues),
            }
        )
        return ProblemExtractionContextBuilder.trusted_child(
            context,
            state=next_state,
            attempt_ledger=attempt_ledger,
            event="source_observation_attached",
            event_payload={"observation_hash": observation.observation_hash},
            quality=quality,
            ancestor_contexts=ancestor_contexts,
            producer="f2_source_observation",
            producer_version="v1",
        )


def _derived_artifact_ids(
    observation: object,
) -> tuple[str, ...]:
    if isinstance(observation, FormulaObservation):
        return (
            (observation.crop_artifact_id,)
            if observation.crop_artifact_id is not None
            else ()
        )
    if isinstance(observation, InkOriginObservation):
        return (
            (observation.mask_artifact_id,)
            if observation.mask_artifact_id is not None
            else ()
        )
    return ()


def f2_semantic_config(
    provider_payloads: Sequence[Mapping[str, Any]],
    *,
    pdf_dpi: int = 200,
) -> dict[str, Any]:
    provider_ids = tuple(sorted(str(item["provider_id"]) for item in provider_payloads))
    return {
        "track": "F2",
        "observation_schema": "source-observation/v1",
        "provider_contract": "paddle-provider-record/v1",
        "f2_provider_ids": list(provider_ids),
        "pdf_dpi": pdf_dpi,
        "coordinates": "source-relative-6dp",
        "text_ocr_scope": "confirmed_selection_crop",
    }


def _observation_kind(observation_id: str) -> str:
    parts = observation_id.split(":", 3)
    return parts[1] if len(parts) >= 3 else "unknown"
