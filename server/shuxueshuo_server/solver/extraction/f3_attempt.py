"""One F3 semantic attempt without applying candidates to Context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.multimodal_candidates import (
    F3ContractIssue,
    F3ContractValidationReport,
    ProblemExtractionCandidatePatch,
    parse_candidate_patch,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    ExtractionArtifactReader,
    MultimodalEvidencePack,
    MultimodalEvidencePackBuilder,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MULTIMODAL_PROVIDER_NAME,
    MultimodalProviderError,
    MultimodalProviderRequest,
    MultimodalProviderResponse,
    build_multimodal_provider_request,
)
from shuxueshuo_server.solver.extraction.observations import SourceObservation
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    stable_hash,
)


class MultimodalProvider(Protocol):
    model: str

    def complete(
        self,
        request: MultimodalProviderRequest,
    ) -> MultimodalProviderResponse: ...


@dataclass(frozen=True)
class F3ExtractionAttemptResult:
    context: ProblemExtractionContext
    evidence_pack: MultimodalEvidencePack
    request: MultimodalProviderRequest
    provider_response: MultimodalProviderResponse | None
    candidate_patch: ProblemExtractionCandidatePatch | None
    validation_report: F3ContractValidationReport
    attempt: ExtractionAttemptRecord
    attempt_ledger: ExtractionAttemptLedger
    structured_error: Mapping[str, Any] | None
    input_artifacts: tuple[ExtractionArtifactRef, ...]
    output_artifacts: tuple[ExtractionArtifactRef, ...]

    @property
    def ok(self) -> bool:
        return (
            self.attempt.result == "succeeded"
            and self.candidate_patch is not None
            and self.validation_report.ok
        )

    def summary_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "attempt_id": self.attempt.attempt_id,
            "attempt_result": self.attempt.result,
            "base_context_id": self.context.manifest.context_id,
            "evidence_pack_id": self.evidence_pack.evidence_pack_id,
            "candidate_patch_id": (
                self.candidate_patch.patch_id
                if self.candidate_patch is not None
                else None
            ),
            "candidate_counts": {
                candidate_type: sum(
                    item.candidate_type == candidate_type
                    for item in (self.candidate_patch.candidates if self.candidate_patch else ())
                )
                for candidate_type in ("scope", "entity", "fact", "goal")
            },
            "validation": self.validation_report.to_payload(),
            "structured_error": dict(self.structured_error) if self.structured_error else None,
        }


class F3ExtractionAttemptService:
    def __init__(
        self,
        *,
        input_artifact_reader: ExtractionArtifactReader,
        output_artifact_store: ExtractionArtifactStore,
        provider: MultimodalProvider,
        evidence_pack_builder: MultimodalEvidencePackBuilder | None = None,
    ) -> None:
        self.input_artifact_reader = input_artifact_reader
        self.output_artifact_store = output_artifact_store
        self.provider = provider
        self.evidence_pack_builder = (
            evidence_pack_builder or MultimodalEvidencePackBuilder()
        )

    def execute(
        self,
        context: ProblemExtractionContext,
        *,
        attempt_ledger: ExtractionAttemptLedger,
        observation: SourceObservation | None = None,
    ) -> F3ExtractionAttemptResult:
        ledger = attempt_ledger
        self._preflight_attempt_budget(context, ledger)
        attempt_index = context.retry.attempts_used + len(ledger.attempts) + 1
        before = context.to_payload()
        pack = self.evidence_pack_builder.build(
            context,
            artifact_reader=self.input_artifact_reader,
            observation=observation,
        )
        request = build_multimodal_provider_request(
            pack,
            artifact_reader=self.input_artifact_reader,
        )
        input_artifacts = self._store_inputs(context, request)
        attempt_id = _attempt_id(
            context,
            pack,
            attempt_index,
            self.provider.model,
        )
        response: MultimodalProviderResponse | None = None
        patch: ProblemExtractionCandidatePatch | None = None
        error_payload: Mapping[str, Any] | None = None
        output_artifacts: list[ExtractionArtifactRef] = []
        try:
            response = self.provider.complete(request)
        except MultimodalProviderError as exc:
            report = F3ContractValidationReport(
                (F3ContractIssue(exc.code, "$provider", exc.message),)
            )
            error_payload = {
                "code": exc.code,
                "path": "$provider",
                "message": exc.message,
                "provider_attempts": [
                    item.to_payload() for item in exc.provider_attempts
                ],
            }
            result = exc.result
            usage = {
                "request_model": self.provider.model,
                "provider_attempts": [
                    item.to_payload() for item in exc.provider_attempts
                ],
            }
            latency_ms = sum(item.latency_ms for item in exc.provider_attempts)
        else:
            raw_response_ref = self.output_artifact_store.put_bytes(
                kind="multimodal_raw_response",
                content=response.text.encode("utf-8"),
                media_type="text/plain",
                suffix=".txt",
            )
            provider_response_ref = self.output_artifact_store.put_json(
                kind="multimodal_provider_response",
                payload=dict(response.raw_payload),
            )
            output_artifacts.extend((raw_response_ref, provider_response_ref))
            if response.finish_reason == "length":
                report = F3ContractValidationReport(
                    (
                        F3ContractIssue(
                            "extraction.multimodal_provider_output_truncated",
                            "$provider.finish_reason",
                            "provider exhausted the configured output token budget",
                        ),
                    )
                )
            else:
                patch, report = parse_candidate_patch(response.text, pack)
            if patch is not None:
                output_artifacts.append(
                    self.output_artifact_store.put_json(
                        kind="multimodal_candidate_patch",
                        payload={
                            "patch_id": patch.patch_id,
                            "candidate_patch": patch.to_payload(),
                        },
                    )
                )
            if report.ok:
                result = "succeeded"
            elif report.issues[0].code == "extraction.multimodal_response_invalid_json":
                result = "invalid_json"
            else:
                result = "failed"
            if not report.ok:
                first = report.issues[0]
                error_payload = first.to_payload()
            usage = response.metadata_payload()
            latency_ms = response.latency_ms
        validation_ref = self.output_artifact_store.put_json(
            kind="multimodal_contract_validation",
            payload=report.to_payload(),
        )
        output_artifacts.append(validation_ref)
        if error_payload is not None:
            output_artifacts.append(
                self.output_artifact_store.put_json(
                    kind="multimodal_structured_error",
                    payload=dict(error_payload),
                )
            )
        attempt = ExtractionAttemptRecord(
            attempt_id=attempt_id,
            base_context_id=context.manifest.context_id,
            provider=MULTIMODAL_PROVIDER_NAME,
            route="multimodal",
            input_artifact_refs=_unique_artifacts(input_artifacts),
            output_artifact_refs=_unique_artifacts(output_artifacts),
            result=result,  # type: ignore[arg-type]
            usage=usage,
            latency_ms=latency_ms,
        )
        next_ledger = ledger.append(context, attempt)
        if context.to_payload() != before:
            raise RuntimeError("F3 attempt mutated ProblemExtractionContext")
        return F3ExtractionAttemptResult(
            context=context,
            evidence_pack=pack,
            request=request,
            provider_response=response,
            candidate_patch=patch,
            validation_report=report,
            attempt=attempt,
            attempt_ledger=next_ledger,
            structured_error=error_payload,
            input_artifacts=_unique_artifacts(input_artifacts),
            output_artifacts=_unique_artifacts(output_artifacts),
        )

    def _store_inputs(
        self,
        context: ProblemExtractionContext,
        request: MultimodalProviderRequest,
    ) -> tuple[ExtractionArtifactRef, ...]:
        pack_ref = self.output_artifact_store.put_json(
            kind="multimodal_evidence_pack",
            payload=request.evidence_pack.to_payload(),
        )
        region_ref = self.output_artifact_store.put_json(
            kind="multimodal_region_index",
            payload=[
                item.to_payload() for item in request.evidence_pack.region_index
            ],
        )
        request_ref = self.output_artifact_store.put_json(
            kind="multimodal_provider_request_redacted",
            payload=request.redacted_payload(),
        )
        source_observation_id = context.quality.get(
            "source_observation_artifact_id"
        )
        source_observation = next(
            (
                item
                for item in context.state.artifacts
                if item.artifact_id == source_observation_id
            ),
            None,
        )
        if source_observation is None:
            raise ProblemExtractionContextError(
                "extraction.multimodal_evidence_pack_invalid",
                "$.quality.source_observation_artifact_id",
                "SourceObservation artifact is missing",
            )
        return (
            *(item.artifact for item in request.evidence_pack.images),
            source_observation,
            pack_ref,
            region_ref,
            request_ref,
        )

    @staticmethod
    def _preflight_attempt_budget(
        context: ProblemExtractionContext,
        ledger: ExtractionAttemptLedger,
    ) -> None:
        if ledger.base_context_id != context.manifest.context_id:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.base_context_id",
                "ledger does not belong to the supplied Context",
            )
        next_usage = context.retry.attempts_used + len(ledger.attempts) + 1
        if next_usage > context.retry.attempt_budget:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.retry.attempt_budget",
                "semantic attempt budget is exhausted",
            )


def _attempt_id(
    context: ProblemExtractionContext,
    pack: MultimodalEvidencePack,
    attempt_index: int,
    model: str,
) -> str:
    authority = {
        "base_context_id": context.manifest.context_id,
        "evidence_pack_id": pack.evidence_pack_id,
        "attempt_index": attempt_index,
        "provider": MULTIMODAL_PROVIDER_NAME,
        "model": model,
    }
    return f"attempt-f3:{stable_hash(authority)}"


def _unique_artifacts(
    artifacts: Any,
) -> tuple[ExtractionArtifactRef, ...]:
    result: dict[str, ExtractionArtifactRef] = {}
    for item in artifacts:
        result[item.artifact_id] = item
    return tuple(sorted(result.values(), key=lambda item: item.artifact_id))
