from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ExtractionRetryState,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.observation_context import f2_semantic_config
from shuxueshuo_server.solver.extraction.observation_pipeline import (
    F2ObservationAssemblyResult,
    F2ObservationPipeline,
)
from shuxueshuo_server.solver.extraction.observations import (
    PaddleProviderRecord,
    ProviderManifest,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    ProblemSourceFingerprintService,
    SelectionRegion,
    SourceAssetInput,
    SourceSelection,
)


@dataclass(frozen=True)
class F2Fixture:
    page_bytes: bytes
    source: object
    selection: SourceSelection
    dependency: ExtractionDependencyManifest
    context: ProblemExtractionContext
    providers: tuple[ProviderManifest, ...]
    layout_record: PaddleProviderRecord
    text_record: PaddleProviderRecord
    formula_record: PaddleProviderRecord


def provider(component: str, model: str) -> ProviderManifest:
    return ProviderManifest.create(
        provider="test_provider",
        component=component,  # type: ignore[arg-type]
        model_name=model,
        model_revision="sha256:test",
        software_versions={"test": "1"},
        config={"device": "cpu"},
    )


def make_fixture(*, colored_ink: bool = False) -> F2Fixture:
    image = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 30), "24. neighbor", fill="black")
    draw.text((20, 320), "25. y=x^2+1", fill="black")
    draw.text((20, 380), "(1) find y", fill="black")
    if colored_ink:
        draw.line((20, 322, 48, 330), fill=(220, 20, 20), width=3)
        draw.text((250, 440), "work", fill=(20, 70, 220))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    page_bytes = buffer.getvalue()
    source = ProblemSourceFingerprintService().fingerprint(
        (
            SourceAssetInput(
                page_id="page_1",
                media_type="image/png",
                content_bytes=page_bytes,
                locator="memory://page_1",
            ),
        )
    )
    selection = SourceSelection.create(
        source,
        mode="user_confirmed",
        revision=0,
        regions=(
            SelectionRegion(
                region_id="question_25",
                page_id="page_1",
                polygon=((0.02, 0.50), (0.98, 0.50), (0.98, 0.98), (0.02, 0.98)),
            ),
        ),
    )
    layout_provider = provider("layout", "layout-test")
    text_provider = provider("text_ocr", "ocr-test")
    formula_provider = provider("formula_ocr", "formula-test")
    ink_provider = ConservativeInkOriginAnalyzer().provider
    providers = (layout_provider, text_provider, formula_provider, ink_provider)
    dependency = ExtractionDependencyManifest.create(
        source,
        selection,
        semantic_config=f2_semantic_config([item.to_payload() for item in providers]),
    )
    context = ProblemExtractionContextBuilder.initial(
        source=source,
        selection=selection,
        dependency=dependency,
        retry=ExtractionRetryState(attempt_budget=8),
        quality={"problem_id": "synthetic-f2"},
    )
    layout_record = PaddleProviderRecord.create(
        component="layout",
        provider=layout_provider,
        source_revision_hash=source.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            {"label": "text", "confidence": 0.98, "polygon": [[15, 20], [350, 20], [350, 80], [15, 80]]},
            {"label": "text", "confidence": 0.99, "polygon": [[15, 300], [380, 300], [380, 430], [15, 430]]},
        ),
    )
    text_record = PaddleProviderRecord.create(
        component="text_ocr",
        provider=text_provider,
        source_revision_hash=source.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            {"text": "24. neighbor", "confidence": 0.96, "polygon": [[20, 30], [180, 30], [180, 55], [20, 55]]},
            {"text": "25. y=x^2+1", "confidence": 0.97, "polygon": [[20, 320], [220, 320], [220, 350], [20, 350]]},
            {"text": "(1) find y", "confidence": 0.95, "polygon": [[20, 380], [180, 380], [180, 410], [20, 410]]},
        ),
    )
    formula_record = PaddleProviderRecord.create(
        component="formula_ocr",
        provider=formula_provider,
        source_revision_hash=source.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(),
    )
    return F2Fixture(
        page_bytes,
        source,
        selection,
        dependency,
        context,
        providers,
        layout_record,
        text_record,
        formula_record,
    )


def assemble_fixture(
    tmp_path: Path,
    *,
    colored_ink: bool = False,
    include_formula: bool = True,
) -> tuple[F2Fixture, F2ObservationAssemblyResult, ExtractionArtifactStore]:
    fixture = make_fixture(colored_ink=colored_ink)
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    pipeline = F2ObservationPipeline(artifact_store=store)
    formula_records = (fixture.formula_record,) if include_formula else ()
    result = pipeline.assemble(
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency=fixture.dependency,
        page_bytes={"page_1": fixture.page_bytes},
        layout_records=(fixture.layout_record,),
        text_records=(fixture.text_record,),
        formula_records=formula_records,
    )
    return fixture, result, store


def successful_ledger(
    context: ProblemExtractionContext,
    artifacts: tuple,
) -> ExtractionAttemptLedger:
    provider_output = tuple(
        item for item in artifacts if item.kind.startswith("provider_")
    )
    provider_attempt = ExtractionAttemptRecord(
        attempt_id="attempt_f2_provider",
        base_context_id=context.manifest.context_id,
        provider="recorded_f2",
        route="pending",
        input_artifact_refs=tuple(
            item
            for item in artifacts
            if item.kind
            in {"canonical_source_page", "selection_crop", "formula_crop"}
        ),
        output_artifact_refs=provider_output,
        result="succeeded",
        usage={"model_calls": 3},
        latency_ms=10,
    )
    ledger = ExtractionAttemptLedger(context.manifest.context_id).append(
        context,
        provider_attempt,
    )
    masks = tuple(item for item in artifacts if item.kind == "handwriting_mask")
    if not masks:
        return ledger
    ink_attempt = ExtractionAttemptRecord(
        attempt_id="attempt_f2_ink_origin",
        base_context_id=context.manifest.context_id,
        provider="local_cv",
        route="pending",
        input_artifact_refs=tuple(
            item
            for item in artifacts
            if item.kind in {"canonical_source_page", "provider_text_ocr"}
        ),
        output_artifact_refs=masks,
        result="succeeded",
        usage={"page_count": len(masks)},
        latency_ms=0,
    )
    return ledger.append(context, ink_attempt)
