from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionRetryState,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.handwriting import (
    ConservativeInkOriginAnalyzer,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
    MultimodalEvidencePackBuilder,
    _selection_canvas,
)
from shuxueshuo_server.solver.extraction.observation_context import (
    ObservationContextTransitionService,
)
from shuxueshuo_server.solver.extraction.observation_pipeline import (
    F2ObservationPipeline,
)
from shuxueshuo_server.solver.extraction.observations import PaddleProviderRecord
from shuxueshuo_server.solver.extraction.observation_context import (
    f2_semantic_config,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    ProblemSourceFingerprintService,
    SelectionRegion,
    SourceAssetInput,
    SourceSelection,
)

from _problem_extraction_f2_support import (
    make_fixture,
    provider,
    successful_ledger,
)


def make_f3_fixture(
    tmp_path: Path,
    *,
    colored_ink: bool = False,
    printed_text_confidence: float | None = None,
    printed_text_override: str | None = None,
):
    fixture = make_fixture(colored_ink=colored_ink)
    text_record = fixture.text_record
    if printed_text_confidence is not None or printed_text_override is not None:
        items = [dict(item) for item in text_record.items]
        if printed_text_confidence is not None:
            items[1]["confidence"] = printed_text_confidence
        if printed_text_override is not None:
            items[1]["text"] = printed_text_override
        text_record = PaddleProviderRecord.create(
            component="text_ocr",
            provider=text_record.provider,
            source_revision_hash=text_record.source_revision_hash,
            page_id=text_record.page_id,
            width=text_record.width,
            height=text_record.height,
            items=items,
        )
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    crop_bytes = _selection_canvas(
        fixture.context,
        "page_1",
        fixture.page_bytes,
    )
    selection_crop = store.put_bytes(
        kind="selection_crop",
        content=crop_bytes,
        media_type="image/png",
        suffix=".png",
    )
    result = F2ObservationPipeline(artifact_store=store).assemble(
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency=fixture.dependency,
        page_bytes={"page_1": fixture.page_bytes},
        layout_records=(fixture.layout_record,),
        text_records=(text_record,),
        formula_records=(fixture.formula_record,),
        extra_artifacts=(selection_crop,),
    )
    context = ObservationContextTransitionService().attach(
        fixture.context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=successful_ledger(fixture.context, result.artifacts),
    )
    pack = MultimodalEvidencePackBuilder().build(
        context,
        artifact_reader=store,
        observation=result.observation,
    )
    return fixture, result, context, store, pack


def make_multi_page_f3_fixture(tmp_path: Path):
    page_bytes = {
        "page_1": _page_png(("24. neighbor", "25. y=x^2+1"), y=(30, 330)),
        "page_2": _page_png(("continued: point A", "(1) find y"), y=(40, 120)),
    }
    source = ProblemSourceFingerprintService().fingerprint(
        tuple(
            SourceAssetInput(
                page_id=page_id,
                media_type="image/png",
                content_bytes=content,
                locator=f"memory://{page_id}",
            )
            for page_id, content in page_bytes.items()
        )
    )
    selection = SourceSelection.create(
        source,
        mode="user_confirmed",
        revision=0,
        regions=(
            SelectionRegion(
                "question_25_page_1",
                "page_1",
                ((0.02, 0.5), (0.98, 0.5), (0.98, 0.98), (0.02, 0.98)),
            ),
            SelectionRegion(
                "question_25_page_2",
                "page_2",
                ((0.02, 0.02), (0.98, 0.02), (0.98, 0.5), (0.02, 0.5)),
            ),
        ),
    )
    layout_provider = provider("layout", "layout-test")
    text_provider = provider("text_ocr", "ocr-test")
    formula_provider = provider("formula_ocr", "formula-test")
    providers = (
        layout_provider,
        text_provider,
        formula_provider,
        ConservativeInkOriginAnalyzer().provider,
    )
    dependency = ExtractionDependencyManifest.create(
        source,
        selection,
        semantic_config=f2_semantic_config(
            [item.to_payload() for item in providers]
        ),
    )
    context = ProblemExtractionContextBuilder.initial(
        source=source,
        selection=selection,
        dependency=dependency,
        retry=ExtractionRetryState(attempt_budget=8),
        quality={"problem_id": "synthetic-f3-multi-page"},
    )
    layout_records = tuple(
        PaddleProviderRecord.create(
            component="layout",
            provider=layout_provider,
            source_revision_hash=source.source_revision_hash,
            page_id=page_id,
            width=400,
            height=600,
            items=(
                {
                    "label": "text",
                    "confidence": 0.99,
                    "polygon": (
                        [[15, 300], [380, 300], [380, 430], [15, 430]]
                        if page_id == "page_1"
                        else [[15, 20], [380, 20], [380, 180], [15, 180]]
                    ),
                },
            ),
        )
        for page_id in page_bytes
    )
    text_records = (
        PaddleProviderRecord.create(
            component="text_ocr",
            provider=text_provider,
            source_revision_hash=source.source_revision_hash,
            page_id="page_1",
            width=400,
            height=600,
            items=(
                {
                    "text": "25. y=x^2+1",
                    "confidence": 0.97,
                    "polygon": [[20, 330], [220, 330], [220, 360], [20, 360]],
                },
            ),
        ),
        PaddleProviderRecord.create(
            component="text_ocr",
            provider=text_provider,
            source_revision_hash=source.source_revision_hash,
            page_id="page_2",
            width=400,
            height=600,
            items=(
                {
                    "text": "continued: point A",
                    "confidence": 0.96,
                    "polygon": [[20, 40], [250, 40], [250, 70], [20, 70]],
                },
                {
                    "text": "(1) find y",
                    "confidence": 0.95,
                    "polygon": [[20, 120], [180, 120], [180, 150], [20, 150]],
                },
            ),
        ),
    )
    formula_records = tuple(
        PaddleProviderRecord.create(
            component="formula_ocr",
            provider=formula_provider,
            source_revision_hash=source.source_revision_hash,
            page_id=page_id,
            width=400,
            height=600,
            items=(),
        )
        for page_id in page_bytes
    )
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    crops = tuple(
        store.put_bytes(
            kind="selection_crop",
            content=_selection_canvas(context, page_id, content),
            media_type="image/png",
            suffix=".png",
        )
        for page_id, content in page_bytes.items()
    )
    result = F2ObservationPipeline(artifact_store=store).assemble(
        source=source,
        selection=selection,
        dependency=dependency,
        page_bytes=page_bytes,
        layout_records=layout_records,
        text_records=text_records,
        formula_records=formula_records,
        extra_artifacts=crops,
    )
    child = ObservationContextTransitionService().attach(
        context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=successful_ledger(context, result.artifacts),
    )
    pack = MultimodalEvidencePackBuilder().build(
        child,
        artifact_reader=store,
        observation=result.observation,
    )
    return result, child, store, pack


def _page_png(lines: tuple[str, ...], *, y: tuple[int, ...]) -> bytes:
    image = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(image)
    for text, top in zip(lines, y):
        draw.text((20, top), text, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
