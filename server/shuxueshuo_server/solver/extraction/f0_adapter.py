"""Adapt authored F0 gold cases into deterministic F1 Context seeds."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from shuxueshuo_server.solver.extraction.context import (
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.gold_corpus import GoldCorpusCase
from shuxueshuo_server.solver.extraction.source_identity import (
    EXTRACTION_CONTRACT_VERSION,
    ExtractionDependencyManifest,
    ProblemExtractionContextError,
    ProblemSourceFingerprint,
    ProblemSourceFingerprintService,
    SelectionRegion,
    SourceAssetInput,
    SourceSelection,
)


@dataclass(frozen=True)
class F0ExtractionContextSeed:
    problem_id: str
    source: ProblemSourceFingerprint
    selection: SourceSelection
    dependency: ExtractionDependencyManifest
    context: ProblemExtractionContext

    def fingerprint_payload(self) -> dict[str, str]:
        return {
            "source_id": self.source.source_id,
            "source_revision_hash": self.source.source_revision_hash,
            "selection_id": self.selection.selection_id,
            "dependency_hash": self.dependency.dependency_hash,
            "context_id": self.context.manifest.context_id,
        }


def build_f0_extraction_context_seed(
    case: GoldCorpusCase,
    *,
    semantic_config: Mapping[str, Any] | None = None,
) -> F0ExtractionContextSeed:
    repo_root = Path(__file__).resolve().parents[4]
    assets: list[SourceAssetInput] = []
    for page in case.manifest.pages:
        asset_path = _trusted_repo_path(repo_root, page.asset_path)
        try:
            content = asset_path.read_bytes()
        except OSError as exc:
            raise ProblemExtractionContextError(
                "extraction.source_invalid",
                f"$.source.pages.{page.page_id}",
                str(exc),
            ) from exc
        digest = sha256(content).hexdigest()
        if digest != page.sha256:
            raise ProblemExtractionContextError(
                "extraction.source_fingerprint_mismatch",
                f"$.source.pages.{page.page_id}.sha256",
                f"expected {page.sha256}, got {digest}",
            )
        assets.append(
            SourceAssetInput(
                page_id=page.page_id,
                media_type=page.media_type,
                content_bytes=content,
                locator=page.asset_path,
            )
        )
    source = ProblemSourceFingerprintService().fingerprint(tuple(assets))
    selection = SourceSelection.create(
        source,
        mode="authored_gold",
        revision=0,
        regions=tuple(
            SelectionRegion(
                region_id=region.region_id,
                page_id=region.page_id,
                polygon=region.polygon,
                reason=region.reason,
            )
            for region in case.annotation.selection_regions
        ),
    )
    dependency = ExtractionDependencyManifest.create(
        source,
        selection,
        extraction_contract_version=EXTRACTION_CONTRACT_VERSION,
        semantic_config=semantic_config or {"f0_adapter": "v1"},
    )
    context = ProblemExtractionContextBuilder.initial(
        source=source,
        selection=selection,
        dependency=dependency,
        producer="f0_gold_adapter",
        producer_version="v1",
        quality={"problem_id": case.problem_id, "source": "authored_gold"},
    )
    return F0ExtractionContextSeed(
        problem_id=case.problem_id,
        source=source,
        selection=selection,
        dependency=dependency,
        context=context,
    )


def _trusted_repo_path(repo_root: Path, value: str) -> Path:
    candidate = (repo_root / value).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ProblemExtractionContextError(
            "extraction.source_invalid",
            "$.source.asset_path",
            f"path escapes repository root: {value}",
        ) from exc
    return candidate
