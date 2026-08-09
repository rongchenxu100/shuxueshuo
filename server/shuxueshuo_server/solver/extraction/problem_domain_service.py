"""Multimodal Problem domain extraction with immutable local repair."""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
import json
from typing import Any, Mapping, Protocol, Sequence

from PIL import Image

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.attempt_ledger_store import (
    ExtractionAttemptLedgerStore,
)
from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    ExtractionArtifactReader,
    MultimodalEvidencePack,
    MultimodalEvidencePackBuilder,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalProviderError,
    MultimodalProviderImage,
    MultimodalProviderRequest,
    MultimodalProviderResponse,
    build_multimodal_provider_request,
)
from shuxueshuo_server.solver.extraction.observations import SourceObservation
from shuxueshuo_server.solver.extraction.problem_domain import (
    PROBLEM_DOMAIN_CONTRACT,
    ProblemDomainError,
    ProblemDraft,
    ProblemPromotionService,
    ProblemRepairPatch,
    ProblemRepairService,
    ProblemValidationIssue,
    ProblemValidationReport,
    VerifiedProblem,
)
from shuxueshuo_server.solver.extraction.problem_domain_canonicalization import (
    ProblemDomainCanonicalizer,
)
from shuxueshuo_server.solver.extraction.problem_domain_context import (
    ProblemDomainContextTransitionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    SolverProblemProjection,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    stable_hash,
)


PROBLEM_DOMAIN_PRIMARY_IMAGE_MAX_EDGE = 1600


class ProblemDomainMultimodalProvider(Protocol):
    provider_name: str
    supports_images: bool
    response_format_mode: str
    model: str

    def complete(
        self, request: MultimodalProviderRequest
    ) -> MultimodalProviderResponse: ...


@dataclass(frozen=True)
class ProblemDomainExtractionAttemptResult:
    attempt_number: int
    request: MultimodalProviderRequest
    provider_response: MultimodalProviderResponse | None
    patch: ProblemRepairPatch | None
    resulting_draft: ProblemDraft | None
    report: ProblemValidationReport
    projection: SolverProblemProjection | None
    attempt_record: ExtractionAttemptRecord
    input_artifacts: tuple[ExtractionArtifactRef, ...]
    output_artifacts: tuple[ExtractionArtifactRef, ...]
    validation_artifact: ExtractionArtifactRef
    structured_error: Mapping[str, Any] | None

    @property
    def ok(self) -> bool:
        return (
            self.resulting_draft is not None
            and self.report.ok
            and self.projection is not None
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "attempt_number": self.attempt_number,
            "attempt_id": self.attempt_record.attempt_id,
            "contract_version": self.request.contract_version,
            "result": self.attempt_record.result,
            "patch_id": self.patch.patch_id if self.patch is not None else None,
            "resulting_revision_id": (
                self.resulting_draft.revision_id
                if self.resulting_draft is not None
                else None
            ),
            "validation": self.report.to_payload(),
            "structured_error": (
                dict(self.structured_error) if self.structured_error else None
            ),
        }


@dataclass(frozen=True)
class ProblemDomainExtractionRunResult:
    base_context: ProblemExtractionContext
    final_context: ProblemExtractionContext
    evidence_pack: MultimodalEvidencePack
    attempts: tuple[ProblemDomainExtractionAttemptResult, ...]
    attempt_ledger: ExtractionAttemptLedger
    verified_problem: VerifiedProblem | None = None
    solver_projection: SolverProblemProjection | None = None
    blocked_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.final_context.projection.status == "accepted"

    @property
    def blocked(self) -> bool:
        return self.final_context.projection.status == "blocked"


class ProblemDomainExtractionService:
    def __init__(
        self,
        *,
        input_artifact_reader: ExtractionArtifactReader,
        output_artifact_store: ExtractionArtifactStore,
        provider: ProblemDomainMultimodalProvider,
        validator: ProblemDomainValidator | None = None,
        evidence_pack_builder: MultimodalEvidencePackBuilder | None = None,
        attempt_ledger_store: ExtractionAttemptLedgerStore | None = None,
        repair_service: ProblemRepairService | None = None,
        canonicalizer: ProblemDomainCanonicalizer | None = None,
        promotion_service: ProblemPromotionService | None = None,
        context_transition: ProblemDomainContextTransitionService | None = None,
    ) -> None:
        self.input_artifact_reader = input_artifact_reader
        self.output_artifact_store = output_artifact_store
        self.provider = provider
        self.validator = validator or ProblemDomainValidator()
        self.evidence_pack_builder = evidence_pack_builder or MultimodalEvidencePackBuilder()
        self.attempt_ledger_store = attempt_ledger_store or ExtractionAttemptLedgerStore(
            output_artifact_store.root / "_authority" / "attempt-ledgers"
        )
        self.repair_service = repair_service or ProblemRepairService()
        self.canonicalizer = canonicalizer or ProblemDomainCanonicalizer()
        self.promotion_service = promotion_service or ProblemPromotionService()
        self.context_transition = context_transition or ProblemDomainContextTransitionService()

    def run(
        self,
        context: ProblemExtractionContext,
        *,
        attempt_ledger: ExtractionAttemptLedger,
        max_attempts: int = 3,
        observation: SourceObservation | None = None,
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
    ) -> ProblemDomainExtractionRunResult:
        if context.projection.status != "pending":
            raise ProblemExtractionContextError(
                "extraction.problem_context_build_failed",
                "$.projection.status",
                "Problem domain extraction requires a pending Context",
            )
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._require_ledger(context, attempt_ledger)
        pack = self.evidence_pack_builder.build(
            context,
            artifact_reader=self.input_artifact_reader,
            observation=observation,
        )
        expected_problem_id = _expected_problem_id(context)
        remaining = (
            context.retry.attempt_budget
            - context.retry.attempts_used
            - len(attempt_ledger.attempts)
        )
        attempts: list[ProblemDomainExtractionAttemptResult] = []
        ledger = attempt_ledger
        current_draft: ProblemDraft | None = None
        prompt_issues: tuple[ProblemValidationIssue, ...] = ()
        previous_signature: tuple[str | None, str] | None = None
        blocked_reason = "extraction.problem_retry_exhausted"

        for semantic_attempt in range(1, min(max_attempts, max(0, remaining)) + 1):
            zooms = self._retry_zooms(context, pack, prompt_issues)
            result, ledger = self._execute_once(
                context,
                pack=pack,
                expected_problem_id=expected_problem_id,
                attempt_ledger=ledger,
                current_draft=current_draft,
                validation_issues=prompt_issues,
                zoom_images=zooms,
                semantic_attempt_number=semantic_attempt,
            )
            attempts.append(result)
            if result.resulting_draft is not None:
                current_draft = result.resulting_draft
            if result.ok and current_draft is not None and result.projection is not None:
                verified = self.promotion_service.promote(current_draft)
                final_context = self._accepted_context(
                    context,
                    verified=verified,
                    projection=result.projection,
                    attempts=attempts,
                    ledger=ledger,
                    validation_artifact=result.validation_artifact,
                    ancestor_contexts=ancestor_contexts,
                )
                return ProblemDomainExtractionRunResult(
                    context,
                    final_context,
                    pack,
                    tuple(attempts),
                    ledger,
                    verified_problem=verified,
                    solver_projection=result.projection,
                )

            prompt_issues = _merge_issues(
                (
                    current_draft.validation_report.issues
                    if current_draft is not None
                    else ()
                ),
                result.report.issues,
            )
            # Transport and wire failures have not produced a semantic candidate,
            # so repeating their issue code is not evidence that the model is stuck
            # on the same mathematical repair.  No-progress applies only after a
            # schema-valid Draft or patch was materialized.
            semantic_candidate = bool(
                current_draft is not None
                and (
                    result.patch is not None
                    or (
                        result.request.contract_version == PROBLEM_DOMAIN_CONTRACT
                        and result.resulting_draft is not None
                    )
                )
            )
            if semantic_candidate:
                signature = (
                    current_draft.semantic_hash,
                    stable_hash([item.to_payload() for item in prompt_issues]),
                )
                if previous_signature == signature:
                    blocked_reason = "extraction.problem_retry_no_progress"
                    break
                previous_signature = signature

        final_context = self._blocked_context(
            context,
            draft=current_draft,
            prompt_issues=prompt_issues,
            attempts=attempts,
            ledger=ledger,
            reason=blocked_reason,
            ancestor_contexts=ancestor_contexts,
        )
        return ProblemDomainExtractionRunResult(
            context,
            final_context,
            pack,
            tuple(attempts),
            ledger,
            blocked_reason=blocked_reason,
        )

    def _execute_once(
        self,
        context: ProblemExtractionContext,
        *,
        pack: MultimodalEvidencePack,
        expected_problem_id: str,
        attempt_ledger: ExtractionAttemptLedger,
        current_draft: ProblemDraft | None,
        validation_issues: Sequence[ProblemValidationIssue],
        zoom_images: Sequence[MultimodalProviderImage],
        semantic_attempt_number: int,
    ) -> tuple[ProblemDomainExtractionAttemptResult, ExtractionAttemptLedger]:
        with self.attempt_ledger_store.transaction(context, attempt_ledger) as transaction:
            ledger = transaction.ledger
            if ledger is None:
                raise RuntimeError("attempt ledger authority is unavailable")
            request = build_multimodal_provider_request(
                pack,
                artifact_reader=self.input_artifact_reader,
                expected_problem_id=expected_problem_id,
                current_draft=current_draft,
                validation_issues=validation_issues,
                zoom_images=(zoom_images if self.provider.supports_images else ()),
                semantic_attempt_number=semantic_attempt_number,
                include_images=self.provider.supports_images,
                response_format_mode=self.provider.response_format_mode,  # type: ignore[arg-type]
            )
            request = self._prepare_transport_images(request)
            input_artifacts = self._store_inputs(context, request)
            response: MultimodalProviderResponse | None = None
            patch: ProblemRepairPatch | None = None
            resulting_draft: ProblemDraft | None = current_draft
            projection: SolverProblemProjection | None = None
            output_artifacts: list[ExtractionArtifactRef] = []
            structured_error: Mapping[str, Any] | None = None
            try:
                response = self.provider.complete(request)
            except MultimodalProviderError as exc:
                report = _error_report(exc.code, exc.message, current_draft)
                attempt_result = exc.result
                usage: Mapping[str, Any] = {
                    "request_model": self.provider.model,
                    "provider_attempts": [
                        item.to_payload() for item in exc.provider_attempts
                    ],
                }
                latency_ms = sum(item.latency_ms for item in exc.provider_attempts)
            else:
                output_artifacts.extend(
                    (
                        self.output_artifact_store.put_bytes(
                            kind="problem_domain_raw_response",
                            content=response.text.encode("utf-8"),
                            media_type="text/plain",
                            suffix=".txt",
                        ),
                        self.output_artifact_store.put_json(
                            kind="problem_domain_provider_response",
                            payload=dict(response.raw_payload),
                        ),
                    )
                )
                raw_object = _raw_object(response.text)
                if raw_object is not None:
                    output_artifacts.append(
                        self.output_artifact_store.put_json(
                            kind=(
                                "problem_repair_payload"
                                if current_draft is not None
                                else "problem_domain_payload"
                            ),
                            payload=raw_object,
                        )
                    )
                if response.finish_reason == "length":
                    report = _error_report(
                        "extraction.problem_domain_schema_invalid",
                        "provider output was truncated",
                        current_draft,
                    )
                else:
                    try:
                        if current_draft is None:
                            resulting_draft = ProblemDraft.create(response.text)
                        else:
                            patch = ProblemRepairPatch.create(response.text)
                            resulting_draft = self.repair_service.apply(
                                current_draft, patch
                            )
                        canonicalization = self.canonicalizer.canonicalize(
                            resulting_draft
                        )
                        resulting_draft = canonicalization.draft
                        if canonicalization.actions:
                            output_artifacts.append(
                                self.output_artifact_store.put_json(
                                    kind="problem_domain_canonicalization",
                                    payload={
                                        "actions": [
                                            item.to_payload()
                                            for item in canonicalization.actions
                                        ]
                                    },
                                )
                            )
                    except ProblemDomainError as exc:
                        report = _error_report(exc.code, exc.message, current_draft)
                    else:
                        validation = self.validator.validate(
                            resulting_draft,
                            evidence_pack=pack,
                            expected_problem_id=expected_problem_id,
                        )
                        resulting_draft = validation.draft
                        report = validation.report
                        projection = validation.projection
                        output_artifacts.append(
                            self.output_artifact_store.put_json(
                                kind="problem_draft",
                                payload=resulting_draft.to_payload(),
                            )
                        )
                attempt_result = (
                    "succeeded"
                    if resulting_draft is not None and report.ok and projection is not None
                    else "invalid_json"
                    if report.issues
                    and report.issues[0].code
                    in {
                        "extraction.problem_domain_invalid_json",
                        "extraction.problem_repair_invalid_json",
                    }
                    else "failed"
                )
                usage = response.metadata_payload()
                latency_ms = response.latency_ms

            validation_artifact = self.output_artifact_store.put_json(
                kind="problem_validation_report",
                payload=report.to_payload(),
            )
            output_artifacts.append(validation_artifact)
            if report.issues:
                structured_error = report.issues[0].to_payload()
                output_artifacts.append(
                    self.output_artifact_store.put_json(
                        kind="problem_domain_structured_error",
                        payload=structured_error,
                    )
                )
            authority_attempt_number = (
                context.retry.attempts_used + len(ledger.attempts) + 1
            )
            attempt_record = ExtractionAttemptRecord(
                attempt_id=_attempt_id(
                    context.manifest.context_id,
                    pack.evidence_pack_id,
                    authority_attempt_number,
                    self.provider.model,
                ),
                base_context_id=context.manifest.context_id,
                provider=self.provider.provider_name,
                route=(
                    "multimodal"
                    if self.provider.supports_images
                    else "text_baseline"
                ),
                input_artifact_refs=_unique_artifacts(input_artifacts),
                output_artifact_refs=_unique_artifacts(output_artifacts),
                result=attempt_result,  # type: ignore[arg-type]
                usage=usage,
                latency_ms=latency_ms,
            )
            next_ledger = ledger.append(context, attempt_record)
            transaction.commit(next_ledger)
            return (
                ProblemDomainExtractionAttemptResult(
                    attempt_number=semantic_attempt_number,
                    request=request,
                    provider_response=response,
                    patch=patch,
                    resulting_draft=resulting_draft,
                    report=report,
                    projection=projection,
                    attempt_record=attempt_record,
                    input_artifacts=_unique_artifacts(input_artifacts),
                    output_artifacts=_unique_artifacts(output_artifacts),
                    validation_artifact=validation_artifact,
                    structured_error=structured_error,
                ),
                next_ledger,
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
        request_ref = self.output_artifact_store.put_json(
            kind="problem_domain_provider_request_redacted",
            payload=request.redacted_payload(),
        )
        observation_id = context.quality.get("source_observation_artifact_id")
        observation = next(
            (
                item
                for item in context.state.artifacts
                if item.artifact_id == observation_id
            ),
            None,
        )
        if observation is None:
            raise ProblemExtractionContextError(
                "extraction.multimodal_evidence_pack_invalid",
                "$.quality.source_observation_artifact_id",
                "SourceObservation artifact is missing",
            )
        return _unique_artifacts(
            (
                *(item.artifact for item in request.evidence_pack.images),
                *(item.artifact for item in request.images),
                observation,
                pack_ref,
                request_ref,
            )
        )

    def _prepare_transport_images(
        self,
        request: MultimodalProviderRequest,
    ) -> MultimodalProviderRequest:
        images: list[MultimodalProviderImage] = []
        for item in request.images:
            if (
                item.role != "primary"
                or max(item.width, item.height)
                <= PROBLEM_DOMAIN_PRIMARY_IMAGE_MAX_EDGE
            ):
                images.append(item)
                continue
            with Image.open(BytesIO(item.content)) as source:
                image = source.convert("RGB")
            image.thumbnail(
                (
                    PROBLEM_DOMAIN_PRIMARY_IMAGE_MAX_EDGE,
                    PROBLEM_DOMAIN_PRIMARY_IMAGE_MAX_EDGE,
                ),
                Image.Resampling.LANCZOS,
            )
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            content = buffer.getvalue()
            artifact = self.output_artifact_store.put_bytes(
                kind="problem_domain_primary_image",
                content=content,
                media_type="image/png",
                suffix=".png",
            )
            images.append(
                MultimodalProviderImage(
                    image_id=f"primary:{item.page_id}:{artifact.sha256}",
                    page_id=item.page_id,
                    role="primary",
                    artifact=artifact,
                    content=content,
                    width=image.width,
                    height=image.height,
                )
            )
        return replace(request, images=tuple(images))

    def _retry_zooms(
        self,
        context: ProblemExtractionContext,
        pack: MultimodalEvidencePack,
        issues: Sequence[ProblemValidationIssue],
    ) -> tuple[MultimodalProviderImage, ...]:
        region_ids = {region for issue in issues for region in issue.region_refs}
        by_id = pack.region_by_id
        result: list[MultimodalProviderImage] = []
        for region_id in sorted(region_ids):
            region = by_id.get(region_id)
            if region is None:
                continue
            source_ref = next(
                (
                    artifact
                    for artifact in context.state.artifacts
                    if artifact.artifact_id == region.source_artifact_id
                ),
                None,
            )
            if source_ref is None:
                continue
            with Image.open(
                BytesIO(self.input_artifact_reader.read_bytes(source_ref))
            ) as source:
                with source.convert("RGB") as image:
                    left = max(
                        0,
                        int(min(x for x, _ in region.polygon) * image.width) - 24,
                    )
                    top = max(
                        0,
                        int(min(y for _, y in region.polygon) * image.height) - 24,
                    )
                    right = min(
                        image.width,
                        int(max(x for x, _ in region.polygon) * image.width) + 24,
                    )
                    bottom = min(
                        image.height,
                        int(max(y for _, y in region.polygon) * image.height) + 24,
                    )
                    if right <= left or bottom <= top:
                        continue
                    with image.crop((left, top, right, bottom)) as crop:
                        buffer = BytesIO()
                        crop.save(buffer, format="PNG")
                        crop_width = crop.width
                        crop_height = crop.height
            artifact = self.output_artifact_store.put_bytes(
                kind="problem_domain_retry_zoom",
                content=buffer.getvalue(),
                media_type="image/png",
                suffix=".png",
            )
            result.append(
                MultimodalProviderImage(
                    image_id=f"zoom:{region_id}",
                    page_id=region.page_id,
                    role="zoom",
                    artifact=artifact,
                    content=buffer.getvalue(),
                    width=crop_width,
                    height=crop_height,
                )
            )
        return tuple(result)

    def _accepted_context(
        self,
        context: ProblemExtractionContext,
        *,
        verified: VerifiedProblem,
        projection: SolverProblemProjection,
        attempts: Sequence[ProblemDomainExtractionAttemptResult],
        ledger: ExtractionAttemptLedger,
        validation_artifact: ExtractionArtifactRef,
        ancestor_contexts: Sequence[ProblemExtractionContext],
    ) -> ProblemExtractionContext:
        verified_artifact = self.output_artifact_store.put_json(
            kind="verified_problem", payload=verified.to_payload()
        )
        solver_artifact = self.output_artifact_store.put_json(
            kind="solver_problem_ir", payload=projection.to_payload()
        )
        return self.context_transition.accepted(
            context,
            verified_problem=verified,
            solver_projection=projection,
            verified_artifact=verified_artifact,
            solver_problem_ir_artifact=solver_artifact,
            validation_artifact=validation_artifact,
            attempt_ledger=ledger,
            artifacts=_attempt_artifacts(attempts),
            ancestor_contexts=ancestor_contexts,
        )

    def _blocked_context(
        self,
        context: ProblemExtractionContext,
        *,
        draft: ProblemDraft | None,
        prompt_issues: Sequence[ProblemValidationIssue],
        attempts: Sequence[ProblemDomainExtractionAttemptResult],
        ledger: ExtractionAttemptLedger,
        reason: str,
        ancestor_contexts: Sequence[ProblemExtractionContext],
    ) -> ProblemExtractionContext:
        terminal_report = ProblemValidationReport(
            issues=_merge_issues(
                prompt_issues,
                (
                    ProblemValidationIssue(
                        code=reason,
                        unit_ids=(
                            (draft.graph.root_scope.unit_id,)
                            if draft is not None
                            else ()
                        ),
                        dependency_unit_ids=(),
                        message=(
                            "semantic retry made no progress"
                            if reason == "extraction.problem_retry_no_progress"
                            else "semantic attempt budget is exhausted"
                        ),
                        repair_action="inspect the last Draft and blocking root issues",
                        retryable=False,
                    ),
                ),
            ),
            validator_ids=(
                draft.validation_report.validator_ids if draft is not None else ()
            ),
        )
        validation_artifact = self.output_artifact_store.put_json(
            kind="problem_validation_report", payload=terminal_report.to_payload()
        )
        artifacts = (*_attempt_artifacts(attempts), validation_artifact)
        if draft is None:
            return self.context_transition.blocked_without_draft(
                context,
                issue_codes=tuple(item.code for item in terminal_report.issues),
                validation_artifact=validation_artifact,
                attempt_ledger=ledger,
                artifacts=artifacts,
                ancestor_contexts=ancestor_contexts,
            )
        terminal_draft = draft.with_validation(
            terminal_report,
            draft.verification_stamps,
            draft.repairable_unit_ids,
        )
        draft_artifact = self.output_artifact_store.put_json(
            kind="problem_draft", payload=terminal_draft.to_payload()
        )
        return self.context_transition.blocked(
            context,
            draft=terminal_draft,
            draft_artifact=draft_artifact,
            validation_artifact=validation_artifact,
            attempt_ledger=ledger,
            artifacts=artifacts,
            ancestor_contexts=ancestor_contexts,
        )

    @staticmethod
    def _require_ledger(
        context: ProblemExtractionContext,
        ledger: ExtractionAttemptLedger,
    ) -> None:
        if ledger.base_context_id != context.manifest.context_id:
            raise ProblemExtractionContextError(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.base_context_id",
                "ledger does not belong to the supplied Context",
            )


def _error_report(
    code: str,
    message: str,
    draft: ProblemDraft | None,
) -> ProblemValidationReport:
    return ProblemValidationReport(
        issues=(
            ProblemValidationIssue(
                code=code,
                unit_ids=(
                    (draft.graph.root_scope.unit_id,) if draft is not None else ()
                ),
                dependency_unit_ids=(),
                message=message,
                repair_action=(
                    "return one problem-repair/v1 patch for the current Draft"
                    if draft is not None
                    else "return one complete problem-domain/v1 object"
                ),
            ),
        ),
        validator_ids=("wire/v1",),
    )


def _merge_issues(
    *groups: Sequence[ProblemValidationIssue],
) -> tuple[ProblemValidationIssue, ...]:
    by_signature: dict[str, ProblemValidationIssue] = {}
    for item in (issue for group in groups for issue in group):
        by_signature.setdefault(stable_hash(item.to_payload()), item)
    return tuple(
        sorted(
            by_signature.values(),
            key=lambda item: (item.code, item.unit_ids, item.message),
        )
    )


def _raw_object(raw: str) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _expected_problem_id(context: ProblemExtractionContext) -> str:
    value = context.quality.get("problem_id")
    if value is not None and str(value).strip():
        return str(value)
    return "extracted-" + context.selection.selection_id.removeprefix("selection:")[:20]


def _attempt_id(
    context_id: str,
    evidence_pack_id: str,
    attempt_number: int,
    model: str,
) -> str:
    return "attempt-problem-domain:" + stable_hash(
        {
            "base_context_id": context_id,
            "evidence_pack_id": evidence_pack_id,
            "attempt_number": attempt_number,
            "model": model,
        }
    )


def _unique_artifacts(
    artifacts: Sequence[ExtractionArtifactRef],
) -> tuple[ExtractionArtifactRef, ...]:
    return tuple(
        sorted(
            {item.artifact_id: item for item in artifacts}.values(),
            key=lambda item: item.artifact_id,
        )
    )


def _attempt_artifacts(
    attempts: Sequence[ProblemDomainExtractionAttemptResult],
) -> tuple[ExtractionArtifactRef, ...]:
    return _unique_artifacts(
        tuple(
            artifact
            for attempt in attempts
            for artifact in (*attempt.input_artifacts, *attempt.output_artifacts)
        )
    )


__all__ = [
    "ProblemDomainExtractionAttemptResult",
    "ProblemDomainExtractionRunResult",
    "ProblemDomainExtractionService",
]
