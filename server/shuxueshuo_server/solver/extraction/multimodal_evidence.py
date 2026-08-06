"""Source-grounded evidence packs for the F3 multimodal extractor."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from jsonschema import Draft202012Validator
from PIL import Image, ImageDraw, ImageOps

from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.observations import (
    FormulaObservation,
    InkOriginObservation,
    LayoutBlock,
    OcclusionObservation,
    SourceObservation,
    SpatialObservation,
    TextSpanObservation,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    stable_hash,
)


EVIDENCE_PACK_SCHEMA_VERSION = "multimodal-evidence-pack/v1"
_PRINTED_TEXT_CONFIDENCE = 0.8
_VISUAL_REVIEW_GRID_ROWS = 4
_VISUAL_REVIEW_GRID_COLUMNS = 4
_VISUAL_REVIEW_KIND_PREFIX = "visual_review_tile:"


class ExtractionArtifactReader(Protocol):
    def read_bytes(self, artifact: ExtractionArtifactRef) -> bytes: ...


@dataclass(frozen=True)
class MultimodalImageInput:
    image_id: str
    page_id: str
    role: Literal["primary"]
    artifact: ExtractionArtifactRef
    width: int
    height: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "page_id": self.page_id,
            "role": self.role,
            "artifact": self.artifact.authority_payload(),
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ObservationRegionIndexEntry:
    region_id: str
    evidence_id: str
    page_id: str
    polygon: tuple[tuple[float, float], ...]
    kind: str
    origin: str
    confidence: float
    reading_order: int
    source_artifact_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "evidence_id": self.evidence_id,
            "page_id": self.page_id,
            "polygon": [[x, y] for x, y in self.polygon],
            "kind": self.kind,
            "origin": self.origin,
            "confidence": self.confidence,
            "reading_order": self.reading_order,
            "source_artifact_id": self.source_artifact_id,
        }


@dataclass(frozen=True)
class PrintedTextEvidence:
    observation_id: str
    page_id: str
    reading_order: int
    confidence: float
    text: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "page_id": self.page_id,
            "reading_order": self.reading_order,
            "confidence": self.confidence,
            "text": self.text,
        }


@dataclass(frozen=True)
class RecognizedFormulaEvidence:
    observation_id: str
    page_id: str
    reading_order: int
    confidence: float
    latex: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "page_id": self.page_id,
            "reading_order": self.reading_order,
            "confidence": self.confidence,
            "latex": self.latex,
        }


@dataclass(frozen=True)
class UnresolvedObservationWorkItem:
    work_item_id: str
    code: str
    region_refs: tuple[str, ...]
    hint: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "code": self.code,
            "region_refs": list(self.region_refs),
            "hint": self.hint,
        }


@dataclass(frozen=True)
class MultimodalEvidencePack:
    schema_version: str
    evidence_pack_id: str
    base_context_id: str
    source_id: str
    source_revision_hash: str
    selection_id: str
    observation_hash: str
    images: tuple[MultimodalImageInput, ...]
    printed_text: tuple[PrintedTextEvidence, ...]
    recognized_formulas: tuple[RecognizedFormulaEvidence, ...]
    unresolved_items: tuple[UnresolvedObservationWorkItem, ...]
    region_index: tuple[ObservationRegionIndexEntry, ...]

    def authority_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "base_context_id": self.base_context_id,
            "source_id": self.source_id,
            "source_revision_hash": self.source_revision_hash,
            "selection_id": self.selection_id,
            "observation_hash": self.observation_hash,
            "images": [item.to_payload() for item in self.images],
            "printed_text": [item.to_payload() for item in self.printed_text],
            "recognized_formulas": [
                item.to_payload() for item in self.recognized_formulas
            ],
            "unresolved_items": [
                item.to_payload() for item in self.unresolved_items
            ],
            "region_index": [item.to_payload() for item in self.region_index],
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.authority_payload(),
            "evidence_pack_id": self.evidence_pack_id,
        }

    def prompt_payload(self) -> dict[str, Any]:
        """Compact provider input; image bytes are sent as separate message parts."""

        evidence_aliases, region_aliases = self.prompt_reference_aliases()
        prompt_regions = tuple(
            item
            for item in self.region_index
            if item.origin != "handwritten"
            and not (item.kind == "ink" and item.origin == "unknown")
        )
        prompt_region_ids = {item.region_id for item in prompt_regions}
        prompt_unresolved = []
        for item in self.unresolved_items:
            visible_refs = tuple(
                ref for ref in item.region_refs if ref in prompt_region_ids
            )
            if not visible_refs:
                continue
            prompt_unresolved.append(
                {
                    "work_item_id": f"u{len(prompt_unresolved) + 1:03d}",
                    "code": item.code,
                    "region_refs": [region_aliases[ref] for ref in visible_refs],
                    "hint": item.hint,
                }
            )

        return {
            "schema_version": self.schema_version,
            "evidence_pack_id": self.evidence_pack_id,
            "base_context_id": self.base_context_id,
            "images": [
                {
                    "image_id": item.image_id,
                    "page_id": item.page_id,
                    "role": item.role,
                    "sha256": item.artifact.sha256,
                    "width": item.width,
                    "height": item.height,
                }
                for item in self.images
            ],
            "printed_text": [
                {
                    "evidence_id": evidence_aliases[item.observation_id],
                    "page_id": item.page_id,
                    "reading_order": item.reading_order,
                    "confidence": item.confidence,
                    "text": item.text,
                }
                for item in self.printed_text
            ],
            "recognized_formulas": [
                {
                    "evidence_id": evidence_aliases[item.observation_id],
                    "page_id": item.page_id,
                    "reading_order": item.reading_order,
                    "confidence": item.confidence,
                    "latex": item.latex,
                }
                for item in self.recognized_formulas
            ],
            "origin_summary": _origin_summary(self.region_index),
            "unresolved_items": prompt_unresolved,
            "region_index": [
                {
                    **item.to_payload(),
                    "region_id": region_aliases[item.region_id],
                    "evidence_id": evidence_aliases[item.evidence_id],
                }
                for item in prompt_regions
            ],
        }

    def prompt_reference_aliases(self) -> tuple[dict[str, str], dict[str, str]]:
        evidence_aliases = {
            item.evidence_id: f"e{index:03d}"
            for index, item in enumerate(self.region_index, start=1)
        }
        region_aliases = {
            item.region_id: f"r{index:03d}"
            for index, item in enumerate(self.region_index, start=1)
        }
        return evidence_aliases, region_aliases

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> MultimodalEvidencePack:
        _validate_evidence_pack_payload(payload)
        images = tuple(
            MultimodalImageInput(
                image_id=str(item["image_id"]),
                page_id=str(item["page_id"]),
                role="primary",
                artifact=ExtractionArtifactRef.from_payload(item["artifact"]),
                width=int(item["width"]),
                height=int(item["height"]),
            )
            for item in payload["images"]
        )
        result = cls(
            schema_version=str(payload["schema_version"]),
            evidence_pack_id=str(payload["evidence_pack_id"]),
            base_context_id=str(payload["base_context_id"]),
            source_id=str(payload["source_id"]),
            source_revision_hash=str(payload["source_revision_hash"]),
            selection_id=str(payload["selection_id"]),
            observation_hash=str(payload["observation_hash"]),
            images=images,
            printed_text=tuple(
                PrintedTextEvidence(
                    observation_id=str(item["observation_id"]),
                    page_id=str(item["page_id"]),
                    reading_order=int(item["reading_order"]),
                    confidence=float(item["confidence"]),
                    text=str(item["text"]),
                )
                for item in payload["printed_text"]
            ),
            recognized_formulas=tuple(
                RecognizedFormulaEvidence(
                    observation_id=str(item["observation_id"]),
                    page_id=str(item["page_id"]),
                    reading_order=int(item["reading_order"]),
                    confidence=float(item["confidence"]),
                    latex=str(item["latex"]),
                )
                for item in payload["recognized_formulas"]
            ),
            unresolved_items=tuple(
                UnresolvedObservationWorkItem(
                    work_item_id=str(item["work_item_id"]),
                    code=str(item["code"]),
                    region_refs=tuple(str(ref) for ref in item["region_refs"]),
                    hint=(str(item["hint"]) if item.get("hint") is not None else None),
                )
                for item in payload["unresolved_items"]
            ),
            region_index=tuple(
                ObservationRegionIndexEntry(
                    region_id=str(item["region_id"]),
                    evidence_id=str(item["evidence_id"]),
                    page_id=str(item["page_id"]),
                    polygon=tuple(
                        (float(point[0]), float(point[1]))
                        for point in item["polygon"]
                    ),
                    kind=str(item["kind"]),
                    origin=str(item["origin"]),
                    confidence=float(item["confidence"]),
                    reading_order=int(item["reading_order"]),
                    source_artifact_id=str(item["source_artifact_id"]),
                )
                for item in payload["region_index"]
            ),
        )
        result.validate()
        return result

    @property
    def region_by_id(self) -> dict[str, ObservationRegionIndexEntry]:
        return {item.region_id: item for item in self.region_index}

    @property
    def evidence_by_id(self) -> dict[str, ObservationRegionIndexEntry]:
        return {item.evidence_id: item for item in self.region_index}

    def validate(self) -> None:
        _validate_evidence_pack_payload(self.to_payload())
        expected = f"evidence-pack:{stable_hash(self.authority_payload())}"
        if self.evidence_pack_id != expected:
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.evidence_pack_id",
                f"expected {expected}, got {self.evidence_pack_id}",
            )
        page_ids = [item.page_id for item in self.images]
        if len(page_ids) != len(set(page_ids)):
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.images",
                "one primary image per page is required",
            )
        region_ids = [item.region_id for item in self.region_index]
        evidence_ids = [item.evidence_id for item in self.region_index]
        if len(region_ids) != len(set(region_ids)) or len(evidence_ids) != len(
            set(evidence_ids)
        ):
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.region_index",
                "region and evidence identities must be unique",
            )
        image_pages = set(page_ids)
        evidence_by_id = self.evidence_by_id
        for index, item in enumerate(self.region_index):
            if item.page_id not in image_pages:
                raise _error(
                    "extraction.multimodal_evidence_pack_invalid",
                    f"$.region_index[{index}].page_id",
                    "region page is not represented by a primary image",
                )
            if _polygon_area(item.polygon) <= 0:
                raise _error(
                    "extraction.multimodal_evidence_pack_invalid",
                    f"$.region_index[{index}].polygon",
                    "region polygon must have positive area",
                )
            grid_position = _visual_review_grid_position(item.kind)
            if (
                item.kind.startswith(_VISUAL_REVIEW_KIND_PREFIX)
                and grid_position is None
            ):
                raise _error(
                    "extraction.multimodal_evidence_pack_invalid",
                    f"$.region_index[{index}].kind",
                    "visual review tile grid position is invalid",
                )
            if grid_position is not None:
                row, column = grid_position
                expected_id = _visual_review_tile_id(
                    self.selection_id,
                    item.page_id,
                    item.polygon,
                    row=row,
                    column=column,
                )
                if (
                    item.region_id != expected_id
                    or item.evidence_id != expected_id
                    or item.origin != "unknown"
                    or item.confidence != 0.0
                ):
                    raise _error(
                        "extraction.multimodal_evidence_pack_invalid",
                        f"$.region_index[{index}]",
                        "visual review tile identity or authority drifted",
                    )
        _validate_prompt_evidence_records(
            self.printed_text,
            evidence_by_id,
            expected_kind="text",
            path="$.printed_text",
        )
        _validate_prompt_evidence_records(
            self.recognized_formulas,
            evidence_by_id,
            expected_kind="formula",
            path="$.recognized_formulas",
        )
        available = set(region_ids)
        for item in self.unresolved_items:
            if set(item.region_refs) - available:
                raise _error(
                    "extraction.evidence_ref_unresolved",
                    "$.unresolved_items.region_refs",
                    "unresolved item references an unknown region",
                )


class MultimodalEvidencePackBuilder:
    def build(
        self,
        context: ProblemExtractionContext,
        *,
        artifact_reader: ExtractionArtifactReader,
        observation: SourceObservation | None = None,
    ) -> MultimodalEvidencePack:
        observation = observation or self._load_observation(
            context,
            artifact_reader,
        )
        observation.validate(
            context.source,
            context.selection,
            context.dependency.dependency_hash,
        )
        if observation.observation_hash != context.quality.get(
            "source_observation_hash"
        ):
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.quality.source_observation_hash",
                "Context and SourceObservation identities differ",
            )
        artifact_by_id = {
            item.artifact_id: item for item in context.state.artifacts
        }
        observation.validate_artifact_closure(set(artifact_by_id))
        images = self._primary_images(
            context,
            observation,
            artifact_by_id,
            artifact_reader,
        )
        selected_ids = set(observation.selected_observation_ids)
        selected = tuple(
            item
            for item in observation.spatial_observations
            if item.observation_id in selected_ids
        )
        if not selected:
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.selected_observation_ids",
                "the selected question has no observations",
            )
        observed_regions = tuple(
            ObservationRegionIndexEntry(
                region_id=item.observation_id,
                evidence_id=item.observation_id,
                page_id=item.page_id,
                polygon=tuple(item.polygon),
                kind=_observation_kind(item),
                origin=_prompt_origin(item),
                confidence=item.confidence,
                reading_order=item.reading_order,
                source_artifact_id=item.source_artifact_id,
            )
            for item in sorted(
                selected,
                key=lambda item: (item.page_id, item.reading_order, item.observation_id),
            )
        )
        regions = observed_regions + _visual_review_tiles(
            context,
            observation,
            reading_order_start=(
                max((item.reading_order for item in observed_regions), default=-1)
                + 1
            ),
        )
        printed_text = tuple(
            PrintedTextEvidence(
                item.observation_id,
                item.page_id,
                item.reading_order,
                item.confidence,
                item.text,
            )
            for item in selected
            if isinstance(item, TextSpanObservation)
            and item.origin == "printed"
            and item.confidence >= _PRINTED_TEXT_CONFIDENCE
            and item.text.strip()
        )
        formulas = tuple(
            RecognizedFormulaEvidence(
                item.observation_id,
                item.page_id,
                item.reading_order,
                item.confidence,
                item.latex or "",
            )
            for item in selected
            if isinstance(item, FormulaObservation)
            and item.status == "recognized"
            and item.origin == "printed"
            and bool(item.latex)
        )
        unresolved = _unresolved_items(observation, selected)
        provisional = MultimodalEvidencePack(
            schema_version=EVIDENCE_PACK_SCHEMA_VERSION,
            evidence_pack_id="",
            base_context_id=context.manifest.context_id,
            source_id=context.source.source_id,
            source_revision_hash=context.source.source_revision_hash,
            selection_id=context.selection.selection_id,
            observation_hash=observation.observation_hash,
            images=images,
            printed_text=tuple(
                sorted(
                    printed_text,
                    key=lambda item: (
                        item.page_id,
                        item.reading_order,
                        item.observation_id,
                    ),
                )
            ),
            recognized_formulas=tuple(
                sorted(
                    formulas,
                    key=lambda item: (
                        item.page_id,
                        item.reading_order,
                        item.observation_id,
                    ),
                )
            ),
            unresolved_items=unresolved,
            region_index=regions,
        )
        result = replace(
            provisional,
            evidence_pack_id=f"evidence-pack:{stable_hash(provisional.authority_payload())}",
        )
        result.validate()
        return result

    def _load_observation(
        self,
        context: ProblemExtractionContext,
        reader: ExtractionArtifactReader,
    ) -> SourceObservation:
        artifact_id = context.quality.get("source_observation_artifact_id")
        matches = [
            item
            for item in context.state.artifacts
            if item.artifact_id == artifact_id and item.kind == "source_observation"
        ]
        if len(matches) != 1:
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.quality.source_observation_artifact_id",
                "exactly one SourceObservation artifact is required",
            )
        try:
            payload = json.loads(reader.read_bytes(matches[0]))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.state.artifacts.source_observation",
                str(exc),
            ) from exc
        return SourceObservation.from_payload(
            payload,
            source=context.source,
            selection=context.selection,
            dependency_hash=context.dependency.dependency_hash,
        )

    def _primary_images(
        self,
        context: ProblemExtractionContext,
        observation: SourceObservation,
        artifact_by_id: Mapping[str, ExtractionArtifactRef],
        reader: ExtractionArtifactReader,
    ) -> tuple[MultimodalImageInput, ...]:
        crop_by_sha = {
            item.sha256: item
            for item in context.state.artifacts
            if item.kind == "selection_crop"
        }
        page_by_id = {item.page_id: item for item in observation.pages}
        selected_page_ids = tuple(
            page.page_id
            for page in context.source.pages
            if any(
                region.page_id == page.page_id
                for region in context.selection.regions
            )
        )
        images: list[MultimodalImageInput] = []
        for page_id in selected_page_ids:
            page = page_by_id.get(page_id)
            if page is None or page.source_artifact_id not in artifact_by_id:
                raise _error(
                    "extraction.multimodal_full_image_missing",
                    "$.images",
                    f"canonical source page is missing for {page_id}",
                )
            source_bytes = reader.read_bytes(artifact_by_id[page.source_artifact_id])
            expected_bytes = _selection_canvas(context, page_id, source_bytes)
            expected_sha = sha256(expected_bytes).hexdigest()
            crop = crop_by_sha.get(expected_sha)
            if crop is None:
                raise _error(
                    "extraction.multimodal_full_image_missing",
                    "$.state.artifacts",
                    f"selection crop is missing or drifted for {page_id}",
                )
            actual = reader.read_bytes(crop)
            if actual != expected_bytes:
                raise _error(
                    "extraction.multimodal_full_image_missing",
                    "$.state.artifacts.selection_crop",
                    f"selection crop bytes drifted for {page_id}",
                )
            with Image.open(BytesIO(actual)) as image:
                width, height = image.size
            images.append(
                MultimodalImageInput(
                    image_id=f"primary:{page_id}:{crop.sha256}",
                    page_id=page_id,
                    role="primary",
                    artifact=crop,
                    width=width,
                    height=height,
                )
            )
        if not images:
            raise _error(
                "extraction.multimodal_full_image_missing",
                "$.images",
                "at least one complete selection image is required",
            )
        return tuple(images)


def _selection_canvas(
    context: ProblemExtractionContext,
    page_id: str,
    content: bytes,
) -> bytes:
    image = ImageOps.exif_transpose(Image.open(BytesIO(content))).convert("RGB")
    regions = tuple(
        item for item in context.selection.regions if item.page_id == page_id
    )
    if not regions:
        raise _error(
            "extraction.multimodal_full_image_missing",
            "$.selection.regions",
            f"selection has no region for {page_id}",
        )
    left = max(0, int(min(x for item in regions for x, _ in item.polygon) * image.width))
    top = max(0, int(min(y for item in regions for _, y in item.polygon) * image.height))
    right = min(
        image.width,
        max(
            left + 1,
            round(max(x for item in regions for x, _ in item.polygon) * image.width),
        ),
    )
    bottom = min(
        image.height,
        max(
            top + 1,
            round(max(y for item in regions for _, y in item.polygon) * image.height),
        ),
    )
    crop = image.crop((left, top, right, bottom))
    mask = Image.new("L", crop.size, 0)
    draw = ImageDraw.Draw(mask)
    for region in regions:
        draw.polygon(
            [
                (
                    round(x * image.width - left),
                    round(y * image.height - top),
                )
                for x, y in region.polygon
            ],
            fill=255,
        )
    crop.paste(
        Image.new("RGB", crop.size, "white"),
        mask=mask.point(lambda value: 255 - value),
    )
    buffer = BytesIO()
    crop.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()


def _unresolved_items(
    observation: SourceObservation,
    selected: Sequence[SpatialObservation],
) -> tuple[UnresolvedObservationWorkItem, ...]:
    selected_by_id = {item.observation_id: item for item in selected}
    unresolved: dict[str, UnresolvedObservationWorkItem] = {}
    for item in selected:
        code: str | None = None
        hint: str | None = None
        if (
            _prompt_origin(item) == "unknown"
            and item.origin == "printed"
            and item.confidence < _PRINTED_TEXT_CONFIDENCE
        ):
            code = "extraction.observation_confidence_low"
            if isinstance(item, TextSpanObservation):
                hint = _short_hint(item.text)
        elif isinstance(item, FormulaObservation) and item.status == "unresolved":
            code = "extraction.formula_observation_unresolved"
            hint = _short_hint(item.source_text_hint)
        elif item.origin in {"handwritten", "mixed", "unknown"}:
            code = "extraction.observation_origin_unresolved"
            if isinstance(item, TextSpanObservation) and item.origin != "handwritten":
                hint = _short_hint(item.text)
        elif isinstance(item, OcclusionObservation):
            code = "extraction.source_occluded"
        if code is not None:
            payload = {
                "code": code,
                "regions": [item.observation_id],
                "hint": hint,
            }
            work = UnresolvedObservationWorkItem(
                work_item_id=f"unresolved:{stable_hash(payload)}",
                code=code,
                region_refs=(item.observation_id,),
                hint=hint,
            )
            unresolved[work.work_item_id] = work
    for issue in observation.issues:
        region_refs = tuple(
            sorted(
                item
                for item in issue.observation_ids
                if item in selected_by_id
            )
        )
        if not region_refs:
            continue
        payload = {"code": issue.code, "regions": region_refs, "hint": None}
        work = UnresolvedObservationWorkItem(
            work_item_id=f"unresolved:{stable_hash(payload)}",
            code=issue.code,
            region_refs=region_refs,
        )
        unresolved[work.work_item_id] = work
    return tuple(sorted(unresolved.values(), key=lambda item: item.work_item_id))


def _short_hint(value: str | None) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    return compact[:120] or None


def _origin_summary(
    regions: Sequence[ObservationRegionIndexEntry],
) -> list[dict[str, Any]]:
    by_page: dict[str, dict[str, int]] = {}
    for item in regions:
        counts = by_page.setdefault(item.page_id, {})
        counts[item.origin] = counts.get(item.origin, 0) + 1
    return [
        {
            "page_id": page_id,
            "counts": {
                origin: counts[origin]
                for origin in ("printed", "handwritten", "mixed", "unknown")
                if counts.get(origin, 0)
            },
        }
        for page_id, counts in sorted(by_page.items())
    ]


def _validate_prompt_evidence_records(
    records: Sequence[PrintedTextEvidence | RecognizedFormulaEvidence],
    evidence_by_id: Mapping[str, ObservationRegionIndexEntry],
    *,
    expected_kind: str,
    path: str,
) -> None:
    record_ids = [item.observation_id for item in records]
    if len(record_ids) != len(set(record_ids)):
        raise _error(
            "extraction.multimodal_evidence_pack_invalid",
            path,
            "prompt evidence observation ids must be unique",
        )
    for index, item in enumerate(records):
        region = evidence_by_id.get(item.observation_id)
        if region is None:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"{path}[{index}].observation_id",
                "prompt evidence is absent from the region index",
            )
        if (
            region.kind != expected_kind
            or region.origin != "printed"
            or region.page_id != item.page_id
            or region.reading_order != item.reading_order
            or region.confidence != item.confidence
        ):
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                f"{path}[{index}]",
                "prompt evidence metadata differs from its authoritative region",
            )


def _polygon_area(polygon: Sequence[tuple[float, float]]) -> float:
    return abs(
        sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(
                polygon,
                (*polygon[1:], polygon[0]),
            )
        )
    ) / 2


def _validate_evidence_pack_payload(payload: Mapping[str, Any]) -> None:
    errors = sorted(
        _evidence_pack_schema_validator().iter_errors(payload),
        key=lambda item: list(item.path),
    )
    if errors:
        first = errors[0]
        raise _error(
            "extraction.multimodal_evidence_pack_invalid",
            _json_path(first.path),
            first.message,
        )


def _observation_kind(item: SpatialObservation) -> str:
    if isinstance(item, TextSpanObservation):
        return "text"
    if isinstance(item, FormulaObservation):
        return "formula"
    if isinstance(item, InkOriginObservation):
        return "ink"
    if isinstance(item, OcclusionObservation):
        return "occlusion"
    if isinstance(item, LayoutBlock):
        return f"layout:{item.kind}"
    return "observation"


def _prompt_origin(item: SpatialObservation) -> str:
    # FormulaRecognition currently supplies a status-bearing confidence scale
    # that is not calibrated to PP-OCR text confidence. Keep recognized formula
    # authority status-driven; demote low-confidence printed text/layout evidence.
    if (
        item.origin == "printed"
        and not isinstance(item, FormulaObservation)
        and item.confidence < _PRINTED_TEXT_CONFIDENCE
    ):
        return "unknown"
    return item.origin


def _visual_review_tiles(
    context: ProblemExtractionContext,
    observation: SourceObservation,
    *,
    reading_order_start: int,
) -> tuple[ObservationRegionIndexEntry, ...]:
    page_artifact_ids = {
        item.page_id: item.source_artifact_id for item in observation.pages
    }
    tiles: list[ObservationRegionIndexEntry] = []
    for page in context.source.pages:
        regions = tuple(
            item
            for item in context.selection.regions
            if item.page_id == page.page_id
        )
        if not regions:
            continue
        left = min(x for item in regions for x, _ in item.polygon)
        top = min(y for item in regions for _, y in item.polygon)
        right = max(x for item in regions for x, _ in item.polygon)
        bottom = max(y for item in regions for _, y in item.polygon)
        width = (right - left) / _VISUAL_REVIEW_GRID_COLUMNS
        height = (bottom - top) / _VISUAL_REVIEW_GRID_ROWS
        source_artifact_id = page_artifact_ids.get(page.page_id)
        if source_artifact_id is None:
            raise _error(
                "extraction.multimodal_evidence_pack_invalid",
                "$.pages.source_artifact_id",
                f"canonical source artifact is missing for {page.page_id}",
            )
        for row in range(_VISUAL_REVIEW_GRID_ROWS):
            for column in range(_VISUAL_REVIEW_GRID_COLUMNS):
                x0 = _coordinate(left + column * width)
                y0 = _coordinate(top + row * height)
                x1 = _coordinate(left + (column + 1) * width)
                y1 = _coordinate(top + (row + 1) * height)
                polygon = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                tile_id = _visual_review_tile_id(
                    context.selection.selection_id,
                    page.page_id,
                    polygon,
                    row=row,
                    column=column,
                )
                tiles.append(
                    ObservationRegionIndexEntry(
                        region_id=tile_id,
                        evidence_id=tile_id,
                        page_id=page.page_id,
                        polygon=polygon,
                        kind=(
                            f"{_VISUAL_REVIEW_KIND_PREFIX}"
                            f"r{row + 1}c{column + 1}"
                        ),
                        origin="unknown",
                        confidence=0.0,
                        reading_order=reading_order_start + len(tiles),
                        source_artifact_id=source_artifact_id,
                    )
                )
    return tuple(tiles)


def _visual_review_tile_id(
    selection_id: str,
    page_id: str,
    polygon: Sequence[tuple[float, float]],
    *,
    row: int,
    column: int,
) -> str:
    return "visual-review:" + stable_hash(
        {
            "selection_id": selection_id,
            "page_id": page_id,
            "polygon": [[x, y] for x, y in polygon],
            "row": row,
            "column": column,
            "grid": [
                _VISUAL_REVIEW_GRID_ROWS,
                _VISUAL_REVIEW_GRID_COLUMNS,
            ],
        }
    )


def _visual_review_grid_position(kind: str) -> tuple[int, int] | None:
    if not kind.startswith(_VISUAL_REVIEW_KIND_PREFIX):
        return None
    suffix = kind.removeprefix(_VISUAL_REVIEW_KIND_PREFIX)
    if len(suffix) != 4 or suffix[0] != "r" or suffix[2] != "c":
        return None
    try:
        row = int(suffix[1]) - 1
        column = int(suffix[3]) - 1
    except ValueError:
        return None
    if not (
        0 <= row < _VISUAL_REVIEW_GRID_ROWS
        and 0 <= column < _VISUAL_REVIEW_GRID_COLUMNS
    ):
        return None
    return row, column


def _coordinate(value: float) -> float:
    return round(value, 6)


@lru_cache(maxsize=1)
def _evidence_pack_schema_validator() -> Draft202012Validator:
    path = _repo_root() / "internal/schemas/multimodal-evidence-pack.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _json_path(parts: Sequence[object]) -> str:
    return "$" + "".join(f"[{part!r}]" for part in parts)


def _error(code: str, path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(code, path, message)
