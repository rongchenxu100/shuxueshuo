"""Deterministic F2 assembly from provider records to SourceObservation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from io import BytesIO
from typing import Mapping, Sequence

from PIL import Image, ImageOps

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.observations import (
    FormulaCropRequest,
    ObservationIssue,
    PaddleObservationAdapter,
    PaddleProviderRecord,
    PageObservation,
    ProblemRegionProposer,
    SourceObservation,
    bbox_overlap_ratio,
    formula_math_fragments,
    formula_recognition_failure_reason,
    make_observation_issue,
    select_formula_crop_requests,
    selected_observation_ids,
    unresolved_formula_source_ids,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    ProblemExtractionContextError,
    ProblemSourceFingerprint,
    SourceSelection,
)


_ALLOWED_EXTRA_ARTIFACT_KINDS = frozenset({"selection_crop", "formula_crop"})


@dataclass(frozen=True)
class CanonicalPageArtifact:
    page_id: str
    artifact: ExtractionArtifactRef
    content: bytes
    width: int
    height: int


@dataclass(frozen=True)
class F2ObservationAssemblyResult:
    observation: SourceObservation
    artifacts: tuple[ExtractionArtifactRef, ...]
    canonical_pages: tuple[CanonicalPageArtifact, ...]
    formula_requests: tuple[FormulaCropRequest, ...]


class F2ObservationPipeline:
    def __init__(
        self,
        *,
        artifact_store: ExtractionArtifactStore,
        adapter: PaddleObservationAdapter | None = None,
        region_proposer: ProblemRegionProposer | None = None,
        ink_analyzer: ConservativeInkOriginAnalyzer | None = None,
    ) -> None:
        self.artifact_store = artifact_store
        self.adapter = adapter or PaddleObservationAdapter()
        self.region_proposer = region_proposer or ProblemRegionProposer()
        self.ink_analyzer = ink_analyzer or ConservativeInkOriginAnalyzer()

    def assemble(
        self,
        *,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
        dependency: ExtractionDependencyManifest,
        page_bytes: Mapping[str, bytes],
        layout_records: Sequence[PaddleProviderRecord],
        text_records: Sequence[PaddleProviderRecord],
        formula_records: Sequence[PaddleProviderRecord] = (),
        extra_artifacts: Sequence[ExtractionArtifactRef] = (),
    ) -> F2ObservationAssemblyResult:
        source.validate()
        selection.validate(source)
        dependency.validate(source, selection)
        unexpected_artifacts = sorted(
            {
                item.kind
                for item in extra_artifacts
                if item.kind not in _ALLOWED_EXTRA_ARTIFACT_KINDS
            }
        )
        if unexpected_artifacts:
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.extra_artifacts",
                f"artifact kinds are not authorized for observation state: {unexpected_artifacts}",
            )
        canonical_pages = tuple(
            self._canonical_page(page, page_bytes.get(page.page_id))
            for page in source.pages
        )
        page_by_id = {item.page_id: item for item in canonical_pages}
        layout_by_page = _records_by_page(layout_records, "layout", source)
        text_by_page = _records_by_page(text_records, "text_ocr", source)
        formula_by_page = _records_by_page(
            formula_records,
            "formula_ocr",
            source,
            require_all_pages=False,
        )

        layout_blocks = []
        text_spans = []
        provider_manifests = {}
        record_artifacts = []
        for record in tuple(layout_records) + tuple(text_records) + tuple(formula_records):
            provider_manifests[record.provider.provider_id] = record.provider
            record_artifacts.append(
                self.artifact_store.put_json(
                    kind=f"provider_{record.component}",
                    payload=record.to_payload(),
                )
            )
        for page in canonical_pages:
            layout = self.adapter.layout(
                layout_by_page[page.page_id],
                source_artifact_id=page.artifact.artifact_id,
            )
            layout_blocks.extend(layout)
            text_spans.extend(
                self.adapter.text(
                    text_by_page[page.page_id],
                    source_artifact_id=page.artifact.artifact_id,
                    layout_blocks=layout,
                )
            )

        issues: list[ObservationIssue] = []
        ink_items = []
        occlusions = []
        mask_artifacts = []
        text_by_id = {item.observation_id: item for item in text_spans}
        for page in canonical_pages:
            page_spans = tuple(
                item for item in text_by_id.values() if item.page_id == page.page_id
            )
            ink_result = self.ink_analyzer.analyze(
                page_id=page.page_id,
                image_bytes=page.content,
                source_artifact_id=page.artifact.artifact_id,
                text_spans=page_spans,
            )
            mask_ref = self.artifact_store.put_bytes(
                kind="handwriting_mask",
                content=ink_result.mask_png,
                media_type="image/png",
                suffix=".png",
            )
            mask_artifacts.append(mask_ref)
            bound = ink_result.bind_mask_artifact(mask_ref.artifact_id)
            provider_manifests[bound.provider.provider_id] = bound.provider
            for span in bound.text_spans:
                text_by_id[span.observation_id] = span
            ink_items.extend(bound.ink_origins)
            occlusions.extend(bound.occlusions)
            issues.extend(bound.issues)
        text_spans = list(text_by_id.values())

        formula_source_ids = set(
            selected_observation_ids(
                selection,
                tuple(layout_blocks) + tuple(text_spans),
            )
        )
        formula_requests = tuple(
            request
            for request in select_formula_crop_requests(
                layout_blocks,
                text_spans,
                ink_origins=ink_items,
            )
            if formula_source_ids.intersection(request.source_observation_ids)
        )
        unsafe_formula_source_ids = tuple(
            source_id
            for source_id in unresolved_formula_source_ids(
                layout_blocks,
                text_spans,
                ink_origins=ink_items,
            )
            if source_id in formula_source_ids
        )
        if unsafe_formula_source_ids:
            issues.append(
                make_observation_issue(
                    "extraction.formula_observation_unresolved",
                    blocking=False,
                    retryable=False,
                    observation_ids=unsafe_formula_source_ids,
                    details={
                        "reason": "formula_candidate_origin_not_printed",
                        "candidate_count": len(unsafe_formula_source_ids),
                    },
                )
            )
        formula_request_by_id = {
            request.request_id: request for request in formula_requests
        }
        formulas = []
        observed_formula_request_ids: set[str] = set()
        for page_id, record in formula_by_page.items():
            page = page_by_id[page_id]
            page_formulas = self.adapter.formulas(
                record,
                source_artifact_id=page.artifact.artifact_id,
            )
            for item in page_formulas:
                request = formula_request_by_id.get(item.formula_request_id)
                if request is None:
                    raise ProblemExtractionContextError(
                        "extraction.formula_observation_unresolved",
                        "$.formulas.formula_request_id",
                        "formula result does not correspond to an eligible crop request",
                    )
                if (
                    item.page_id != request.page_id
                    or item.source_observation_ids != request.source_observation_ids
                    or item.source_text_hint != request.source_text_hint
                    or item.polygon != request.polygon
                ):
                    raise ProblemExtractionContextError(
                        "extraction.formula_observation_unresolved",
                        "$.formulas",
                        "formula result drifted from its exact crop request",
                    )
                if item.formula_request_id in observed_formula_request_ids:
                    raise ProblemExtractionContextError(
                        "extraction.formula_observation_unresolved",
                        "$.formulas.formula_request_id",
                        "formula crop request produced more than one result",
                    )
                formulas.append(item)
                observed_formula_request_ids.add(item.formula_request_id)
                if item.status == "unresolved":
                    issues.append(
                        make_observation_issue(
                            "extraction.formula_observation_unresolved",
                            blocking=False,
                            retryable=True,
                            observation_ids=item.source_observation_ids,
                            details={
                                "formula_observation_id": item.observation_id,
                                "formula_request_id": item.formula_request_id,
                            },
                        )
                    )
        for request in formula_requests:
            if request.request_id not in observed_formula_request_ids:
                issues.append(
                    make_observation_issue(
                        "extraction.formula_observation_unresolved",
                        blocking=False,
                        retryable=True,
                        observation_ids=request.source_observation_ids,
                        details={"formula_request_id": request.request_id},
                    )
                )

        audited_formulas = []
        for formula in formulas:
            origin = _formula_origin(formula, text_by_id, ink_items)
            source_texts = (
                (formula.source_text_hint,)
                if formula.source_text_hint is not None
                else tuple(
                    text_by_id[source_id].text
                    for source_id in formula.source_observation_ids
                    if source_id in text_by_id
                )
            )
            reason = None
            if formula.status == "recognized" and origin != "printed":
                reason = "formula_origin_not_printed"
            elif formula.status == "recognized":
                reason = formula_recognition_failure_reason(
                    source_texts,
                    formula.latex or "",
                )
            audited = replace(
                formula,
                origin=origin,
                status="unresolved" if reason is not None else formula.status,
            )
            audited_formulas.append(audited)
            if reason is not None:
                issues.append(
                    make_observation_issue(
                        "extraction.formula_observation_unresolved",
                        blocking=False,
                        retryable=True,
                        observation_ids=formula.source_observation_ids,
                        details={
                            "formula_observation_id": formula.observation_id,
                            "formula_request_id": formula.formula_request_id,
                            "reason": reason,
                            "expected_math_fragments": [
                                fragment
                                for source_text in source_texts
                                for fragment in formula_math_fragments(source_text)
                            ],
                        },
                    )
                )
        formulas = audited_formulas

        provisional_pages = tuple(
            PageObservation(
                page_id=page.page_id,
                width=page.width,
                height=page.height,
                orientation_degrees=0,
                source_artifact_id=page.artifact.artifact_id,
                layout_block_ids=tuple(
                    item.observation_id
                    for item in layout_blocks
                    if item.page_id == page.page_id
                ),
                reading_order=tuple(
                    item.observation_id
                    for item in sorted(
                        (
                            tuple(item for item in layout_blocks if item.page_id == page.page_id)
                            + tuple(item for item in text_spans if item.page_id == page.page_id)
                            + tuple(item for item in formulas if item.page_id == page.page_id)
                        ),
                        key=lambda item: (item.reading_order, item.observation_id),
                    )
                ),
            )
            for page in canonical_pages
        )
        proposals, proposal_issues = self.region_proposer.propose(
            pages=provisional_pages,
            layout_blocks=layout_blocks,
            text_spans=text_spans,
        )
        issues.extend(proposal_issues)
        spatial = tuple(layout_blocks) + tuple(text_spans) + tuple(formulas) + tuple(ink_items) + tuple(occlusions)
        selected_ids = selected_observation_ids(selection, spatial)
        observation = SourceObservation.create(
            source=source,
            selection=selection,
            dependency_hash=dependency.dependency_hash,
            providers=tuple(provider_manifests.values()),
            pages=provisional_pages,
            layout_blocks=layout_blocks,
            text_spans=text_spans,
            formulas=formulas,
            ink_origins=ink_items,
            occlusions=occlusions,
            proposals=proposals,
            selected_observation_ids=selected_ids,
            issues=issues,
        )
        observation_ref = self.artifact_store.put_json(
            kind="source_observation",
            payload=observation.to_payload(),
        )
        artifacts = _unique_artifacts(
            tuple(page.artifact for page in canonical_pages)
            + tuple(record_artifacts)
            + tuple(mask_artifacts)
            + tuple(extra_artifacts)
            + (observation_ref,)
        )
        observation.validate_artifact_closure(
            {item.artifact_id for item in artifacts}
        )
        return F2ObservationAssemblyResult(
            observation=observation,
            artifacts=artifacts,
            canonical_pages=canonical_pages,
            formula_requests=formula_requests,
        )

    def _canonical_page(self, page: object, content: bytes | None) -> CanonicalPageArtifact:
        if content is None:
            raise ProblemExtractionContextError(
                "extraction.source_invalid",
                "$.source.pages",
                "source page bytes are missing",
            )
        page_id = str(getattr(page, "page_id"))
        try:
            image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGBA")
        except Exception as exc:
            raise ProblemExtractionContextError(
                "extraction.source_invalid",
                f"$.source.pages.{page_id}",
                str(exc),
            ) from exc
        if image.size != (int(getattr(page, "width")), int(getattr(page, "height"))):
            raise ProblemExtractionContextError(
                "extraction.geometry_transform_mismatch",
                f"$.source.pages.{page_id}",
                "canonical dimensions differ from source fingerprint",
            )
        canonical_sha = _canonical_rgba_sha(image)
        if canonical_sha != str(getattr(page, "canonical_sha256")):
            raise ProblemExtractionContextError(
                "extraction.source_fingerprint_mismatch",
                f"$.source.pages.{page_id}.canonical_sha256",
                "canonical pixels differ from source fingerprint",
            )
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=False)
        png = buffer.getvalue()
        artifact = self.artifact_store.put_bytes(
            kind="canonical_source_page",
            content=png,
            media_type="image/png",
            suffix=".png",
        )
        return CanonicalPageArtifact(page_id, artifact, png, image.width, image.height)


def crop_formula_request(
    request: FormulaCropRequest,
    page: CanonicalPageArtifact,
    *,
    artifact_store: ExtractionArtifactStore,
) -> ExtractionArtifactRef:
    if request.page_id != page.page_id:
        raise ProblemExtractionContextError(
            "extraction.geometry_transform_mismatch",
            "$.formula_request.page_id",
            "formula request belongs to another page",
        )
    image = Image.open(BytesIO(page.content)).convert("RGB")
    xs = [point[0] for point in request.polygon]
    ys = [point[1] for point in request.polygon]
    left = max(0, int(min(xs) * image.width))
    top = max(0, int(min(ys) * image.height))
    right = min(image.width, max(left + 1, int(max(xs) * image.width + 0.999)))
    bottom = min(image.height, max(top + 1, int(max(ys) * image.height + 0.999)))
    crop = image.crop((left, top, right, bottom))
    buffer = BytesIO()
    crop.save(buffer, format="PNG", optimize=False)
    return artifact_store.put_bytes(
        kind="formula_crop",
        content=buffer.getvalue(),
        media_type="image/png",
        suffix=".png",
    )


def _records_by_page(
    records: Sequence[PaddleProviderRecord],
    component: str,
    source: ProblemSourceFingerprint,
    *,
    require_all_pages: bool = True,
) -> dict[str, PaddleProviderRecord]:
    result = {}
    source_pages = {item.page_id: item for item in source.pages}
    for record in records:
        record.validate()
        if record.component != component:
            raise ProblemExtractionContextError(
                "extraction.provider_record_invalid",
                "$.component",
                f"expected {component}, got {record.component}",
            )
        page = source_pages.get(record.page_id)
        if page is None or record.source_revision_hash != source.source_revision_hash:
            raise ProblemExtractionContextError(
                "extraction.provider_record_invalid",
                "$.source_revision_hash",
                "provider record belongs to another source",
            )
        if (record.width, record.height) != (page.width, page.height):
            raise ProblemExtractionContextError(
                "extraction.geometry_transform_mismatch",
                "$.provider_record",
                "provider dimensions differ from canonical page",
            )
        if record.page_id in result:
            raise ProblemExtractionContextError(
                "extraction.provider_record_invalid",
                "$.page_id",
                "duplicate provider record for page",
            )
        result[record.page_id] = record
    missing = set(source_pages) - set(result)
    if require_all_pages and missing:
        raise ProblemExtractionContextError(
            "extraction.provider_record_invalid",
            "$.records",
            f"missing {component} records for {sorted(missing)}",
        )
    return result


def _formula_origin(formula: object, text_by_id: Mapping[str, object], ink_items: Sequence[object]) -> str:
    source_origins = {
        str(getattr(text_by_id[source_id], "origin"))
        for source_id in getattr(formula, "source_observation_ids")
        if source_id in text_by_id
    }
    if "mixed" in source_origins or "handwritten" in source_origins:
        return "mixed"
    if source_origins and source_origins == {"printed"}:
        return "printed"
    overlaps_ink = any(
        getattr(ink, "page_id") == getattr(formula, "page_id")
        and bbox_overlap_ratio(getattr(formula, "polygon"), getattr(ink, "polygon"))
        >= 0.08
        for ink in ink_items
    )
    if overlaps_ink:
        return "mixed"
    return "unknown"


def _canonical_rgba_sha(image: Image.Image) -> str:
    digest = sha256()
    for part in (
        b"raster-rgba\0",
        str(image.width).encode("ascii"),
        b"x",
        str(image.height).encode("ascii"),
        b"\0",
        image.tobytes(),
    ):
        digest.update(part)
    return digest.hexdigest()


def _unique_artifacts(items: Sequence[ExtractionArtifactRef]) -> tuple[ExtractionArtifactRef, ...]:
    result = {}
    for item in items:
        prior = result.get(item.artifact_id)
        if prior is not None and prior.authority_payload() != item.authority_payload():
            raise ProblemExtractionContextError(
                "extraction.observation_invalid",
                "$.artifacts",
                "artifact id was reused with different authority",
            )
        result[item.artifact_id] = item
    return tuple(sorted(result.values(), key=lambda item: item.artifact_id))
