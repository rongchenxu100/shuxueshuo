"""Deterministic PDF-to-raster ingestion for F2."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionArtifactRef
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    SourceAssetInput,
)


@dataclass(frozen=True)
class PdfRasterizationResult:
    source_pdf: ExtractionArtifactRef
    page_artifacts: tuple[ExtractionArtifactRef, ...]
    pages: tuple[SourceAssetInput, ...]
    dpi: int


class PdfSourceRasterizer:
    def __init__(self, *, dpi: int = 200, max_pages: int = 20) -> None:
        if dpi <= 0 or max_pages <= 0:
            raise ValueError("dpi and max_pages must be positive")
        self.dpi = dpi
        self.max_pages = max_pages

    def rasterize(
        self,
        content: bytes,
        *,
        artifact_store: ExtractionArtifactStore,
    ) -> PdfRasterizationResult:
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover - installation boundary
            raise ProblemExtractionContextError(
                "extraction.source_invalid",
                "$.source.pdf",
                "pypdfium2 is required for PDF ingestion",
            ) from exc
        source_ref = artifact_store.put_bytes(
            kind="source_pdf",
            content=content,
            media_type="application/pdf",
            suffix=".pdf",
        )
        try:
            document = pdfium.PdfDocument(content)
        except Exception as exc:
            raise ProblemExtractionContextError(
                "extraction.source_invalid",
                "$.source.pdf",
                f"PDF cannot be decoded: {exc}",
            ) from exc
        if len(document) == 0 or len(document) > self.max_pages:
            raise ProblemExtractionContextError(
                "extraction.source_invalid",
                "$.source.pdf.pages",
                f"PDF page count must be in [1,{self.max_pages}]",
            )
        page_refs = []
        page_inputs = []
        scale = self.dpi / 72
        for index in range(len(document)):
            page = document[index]
            image = page.render(scale=scale).to_pil().convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            buffer = BytesIO()
            background.convert("RGB").save(buffer, format="PNG", optimize=False)
            page_bytes = buffer.getvalue()
            page_ref = artifact_store.put_bytes(
                kind="canonical_pdf_page",
                content=page_bytes,
                media_type="image/png",
                suffix=".png",
            )
            page_refs.append(page_ref)
            page_inputs.append(
                SourceAssetInput(
                    page_id=f"page_{index + 1}",
                    media_type="image/png",
                    content_bytes=page_bytes,
                    locator=page_ref.locator,
                )
            )
        return PdfRasterizationResult(
            source_pdf=source_ref,
            page_artifacts=tuple(page_refs),
            pages=tuple(page_inputs),
            dpi=self.dpi,
        )
