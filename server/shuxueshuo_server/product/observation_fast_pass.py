"""Deterministic observation adapter used by the production fast-pass mode.

The observation stage is intentionally still materialized and audited.  This
adapter supplies empty provider records backed by the normalized image, so the
later extraction stage can decide whether image-only evidence is sufficient.
It never invents OCR text or semantic facts.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ExtractionRetryState,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.multimodal_evidence import _selection_canvas
from shuxueshuo_server.solver.extraction.observation_context import (
    ObservationContextTransitionService,
    f2_semantic_config,
)
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import (
    PaddleProviderRecord,
    ProviderManifest,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    EXTRACTION_CONTRACT_VERSION,
    ExtractionDependencyManifest,
    ProblemSourceFingerprintService,
    SelectionRegion,
    SourceAssetInput,
    SourceSelection,
)


def _provider_manifests() -> tuple[ProviderManifest, ...]:
    common = {
        "provider": "fast-pass",
        "model_name": "none",
        "model_revision": "fast-pass/v1",
        "software_versions": {"adapter": "fast-pass/v1"},
        "config": {"ocr_status": "skipped_fast_pass"},
    }
    return (
        ProviderManifest.create(component="layout", **common),
        ProviderManifest.create(component="text_ocr", **common),
        ConservativeInkOriginAnalyzer().provider,
    )


def _source(x: Any, content: bytes):
    source = ProblemSourceFingerprintService().fingerprint(
        (
            SourceAssetInput(
                page_id="page-1",
                media_type="image/png",
                content_bytes=content,
                locator=f"product://{x.build['id']}/normalized.png",
            ),
        )
    )
    selection = SourceSelection.create(
        source,
        mode="user_confirmed",
        revision=0,
        regions=(
            SelectionRegion(
                region_id="whole-image",
                page_id="page-1",
                polygon=((0, 0), (1, 0), (1, 1), (0, 1)),
                reason="用户上传完整单题截图",
            ),
        ),
    )
    manifests = _provider_manifests()
    dependency = ExtractionDependencyManifest.create(
        source,
        selection,
        extraction_contract_version=EXTRACTION_CONTRACT_VERSION,
        semantic_config=f2_semantic_config([item.to_payload() for item in manifests]),
    )
    return source, selection, dependency, manifests


def run(x: Any, phase: str) -> None:
    """Write the source or observation artifacts for ``StageRunner``."""

    content = x.bytes("source", "规范化图片")
    source, selection, dependency, manifests = _source(x, content)
    if phase == "source":
        initial = ProblemExtractionContextBuilder.initial(
            source=source,
            selection=selection,
            dependency=dependency,
            producer="source_ingestion",
            producer_version="fast-pass/v1",
            retry=ExtractionRetryState(attempt_budget=8),
            quality={
                "problem_id": str(x.build["problem_id"]),
                "source": "upload",
                "observation_mode": "fast-pass",
                "ocr_status": "skipped_fast_pass",
            },
        )
        x.add("Source / selection / initial Context", initial)
        x.add(
            "Observation mode",
            {
                "mode": "fast-pass",
                "ocr_status": "skipped_fast_pass",
                "source_revision_hash": source.source_revision_hash,
            },
            role="validation",
        )
        return

    initial = ProblemExtractionContext.from_payload(
        x.read("source", "Source / selection / initial Context")
    )
    if initial.dependency.dependency_hash != dependency.dependency_hash:
        raise ValueError("observation.fast_pass_dependency_drift")
    with Image.open(BytesIO(content)) as image:
        width, height = image.size
    records = tuple(
        PaddleProviderRecord.create(
            component=manifest.component,
            provider=manifest,
            source_revision_hash=source.source_revision_hash,
            page_id="page-1",
            width=width,
            height=height,
            items=(),
        )
        for manifest in manifests[:2]
    )
    artifact_store = ExtractionArtifactStore(x.work / "extraction-artifacts")
    selection_crop = artifact_store.put_bytes(
        kind="selection_crop",
        content=_selection_canvas(initial, "page-1", content),
        media_type="image/png",
        suffix=".png",
    )
    assembly = F2ObservationPipeline(artifact_store=artifact_store).assemble(
        source=source,
        selection=selection,
        dependency=dependency,
        page_bytes={"page-1": content},
        layout_records=(records[0],),
        text_records=(records[1],),
        extra_artifacts=(selection_crop,),
    )
    provider_outputs = tuple(
        item for item in assembly.artifacts if item.kind.startswith("provider_")
    )
    input_artifacts = tuple(
        item
        for item in assembly.artifacts
        if item.kind in {"canonical_source_page", "selection_crop"}
    )
    ledger = ExtractionAttemptLedger.for_context(initial).append(
        initial,
        ExtractionAttemptRecord(
            attempt_id="attempt:fast-pass:provider",
            base_context_id=initial.manifest.context_id,
            provider="fast-pass",
            route="pending",
            input_artifact_refs=input_artifacts,
            output_artifact_refs=provider_outputs,
            result="succeeded",
            usage={"ocr_status": "skipped_fast_pass"},
            latency_ms=0,
        ),
    )
    masks = tuple(item for item in assembly.artifacts if item.kind == "handwriting_mask")
    if masks:
        ledger = ledger.append(
            initial,
            ExtractionAttemptRecord(
                attempt_id="attempt:fast-pass:ink",
                base_context_id=initial.manifest.context_id,
                provider="local_cv",
                route="pending",
                input_artifact_refs=tuple(
                    item
                    for item in assembly.artifacts
                    if item.kind in {"canonical_source_page", "provider_text_ocr"}
                ),
                output_artifact_refs=masks,
                result="succeeded",
                usage={"ocr_status": "skipped_fast_pass"},
                latency_ms=0,
            ),
        )
    context = ObservationContextTransitionService().attach(
        initial,
        assembly.observation,
        artifacts=assembly.artifacts,
        attempt_ledger=ledger,
    )
    x.add("SourceObservation", assembly.observation)
    x.add("Observation Context", context)
    x.add(
        "观察校验",
        {
            "ok": True,
            "mode": "fast-pass",
            "ocr_status": "skipped_fast_pass",
            "issues": [item.to_payload() for item in assembly.observation.issues],
        },
        role="validation",
    )