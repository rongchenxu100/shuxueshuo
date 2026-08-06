"""Canonical F2 source observations and Paddle provider adapters."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.source_identity import (
    FrozenJson,
    ProblemExtractionContextError,
    ProblemSourceFingerprint,
    SourceSelection,
    freeze_json,
    stable_hash,
    thaw_json,
)


SOURCE_OBSERVATION_SCHEMA_VERSION = "source-observation/v1"
PADDLE_PROVIDER_RECORD_SCHEMA_VERSION = "paddle-provider-record/v1"
ObservationOrigin = Literal["printed", "handwritten", "mixed", "unknown"]
ObservationComponent = Literal["layout", "text_ocr", "formula_ocr", "ink_origin"]
Polygon = tuple[tuple[float, float], ...]

_QUESTION_LABEL = re.compile(
    r"^\s*(?:(?P<bare>\d{1,3})\s*[).．、]|[（(]\s*(?P<wrapped>\d{2,3})\s*[）)])\s*"
)
_MATH_TEXT = re.compile(
    r"(?:[=<>≤≥√∑∫^_]|[A-Za-z]\s*[+\-*/]|\d\s*[+\-*/]\s*[A-Za-z])"
)
_CJK_TEXT = re.compile(r"[\u3400-\u9fff]")
_MATH_FRAGMENT_RUN = re.compile(
    r"[A-Za-z0-9√∠°+\-*/=<>≤≥^_.,，:：;；()（）{}\[\]\\\s]+"
)
_MATH_FRAGMENT_OPERATOR = re.compile(
    r"(?:[=<>≤≥√∠^]|-\d|[A-Za-z0-9)]\s*[+\-*/]\s*[A-Za-z0-9(])"
)
_POINT_COORDINATE_FRAGMENT = re.compile(
    r"[A-Z][A-Za-z0-9'′]*\(\s*[^(),]+\s*,\s*[^(),]+\s*\)"
)
_LATEX_COMMAND = re.compile(r"\\[A-Za-z]+")
_SEMANTIC_KEYS = frozenset(
    {
        "scope",
        "scopes",
        "entity",
        "entities",
        "fact",
        "facts",
        "goal",
        "goals",
        "question_goals",
        "problem_ir",
    }
)


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    provider: str
    component: ObservationComponent
    model_name: str
    model_revision: str
    software_versions: Mapping[str, FrozenJson]
    config: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "software_versions", freeze_json(self.software_versions))
        object.__setattr__(self, "config", freeze_json(self.config))

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        component: ObservationComponent,
        model_name: str,
        model_revision: str,
        software_versions: Mapping[str, Any],
        config: Mapping[str, Any] | None = None,
    ) -> ProviderManifest:
        authority = {
            "provider": provider,
            "component": component,
            "model_name": model_name,
            "model_revision": model_revision,
            "software_versions": dict(software_versions),
            "config": dict(config or {}),
        }
        return cls(
            provider_id=f"provider:{stable_hash(authority)}",
            provider=provider,
            component=component,
            model_name=model_name,
            model_revision=model_revision,
            software_versions=software_versions,
            config=config or {},
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "provider": self.provider,
            "component": self.component,
            "model_name": self.model_name,
            "model_revision": self.model_revision,
            "software_versions": thaw_json(self.software_versions),
            "config": thaw_json(self.config),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ProviderManifest:
        result = cls(
            provider_id=str(payload["provider_id"]),
            provider=str(payload["provider"]),
            component=str(payload["component"]),  # type: ignore[arg-type]
            model_name=str(payload["model_name"]),
            model_revision=str(payload["model_revision"]),
            software_versions=_mapping(payload.get("software_versions", {})),
            config=_mapping(payload.get("config", {})),
        )
        expected = cls.create(
            provider=result.provider,
            component=result.component,
            model_name=result.model_name,
            model_revision=result.model_revision,
            software_versions=thaw_json(result.software_versions),
            config=thaw_json(result.config),
        )
        if result.provider_id != expected.provider_id:
            raise _observation_error(
                "extraction.provider_record_invalid",
                "$.provider.provider_id",
                "provider identity does not match its authority fields",
            )
        return result


@dataclass(frozen=True)
class PageObservation:
    page_id: str
    width: int
    height: int
    orientation_degrees: Literal[0]
    source_artifact_id: str
    layout_block_ids: tuple[str, ...]
    reading_order: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "width": self.width,
            "height": self.height,
            "orientation_degrees": self.orientation_degrees,
            "source_artifact_id": self.source_artifact_id,
            "layout_block_ids": list(self.layout_block_ids),
            "reading_order": list(self.reading_order),
        }


@dataclass(frozen=True)
class SpatialObservation:
    observation_id: str
    page_id: str
    polygon: Polygon
    confidence: float
    origin: ObservationOrigin
    source_artifact_id: str
    provider_id: str
    reading_order: int

    def spatial_payload(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "page_id": self.page_id,
            "polygon": _polygon_payload(self.polygon),
            "confidence": self.confidence,
            "origin": self.origin,
            "source_artifact_id": self.source_artifact_id,
            "provider_id": self.provider_id,
            "reading_order": self.reading_order,
        }


@dataclass(frozen=True)
class LayoutBlock(SpatialObservation):
    kind: str
    provider_label: str

    def to_payload(self) -> dict[str, Any]:
        return {**self.spatial_payload(), "kind": self.kind, "provider_label": self.provider_label}


@dataclass(frozen=True)
class TextSpanObservation(SpatialObservation):
    text: str
    block_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {**self.spatial_payload(), "text": self.text, "block_id": self.block_id}


@dataclass(frozen=True)
class FormulaObservation(SpatialObservation):
    latex: str | None
    status: Literal["recognized", "unresolved"]
    source_observation_ids: tuple[str, ...]
    formula_request_id: str
    source_text_hint: str | None
    crop_artifact_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.spatial_payload(),
            "latex": self.latex,
            "status": self.status,
            "source_observation_ids": list(self.source_observation_ids),
            "formula_request_id": self.formula_request_id,
            "source_text_hint": self.source_text_hint,
            "crop_artifact_id": self.crop_artifact_id,
        }


@dataclass(frozen=True)
class InkOriginObservation(SpatialObservation):
    mask_artifact_id: str | None
    overlap_observation_ids: tuple[str, ...]
    signals: Mapping[str, FrozenJson] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", freeze_json(self.signals))

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.spatial_payload(),
            "mask_artifact_id": self.mask_artifact_id,
            "overlap_observation_ids": list(self.overlap_observation_ids),
            "signals": thaw_json(self.signals),
        }


@dataclass(frozen=True)
class OcclusionObservation(SpatialObservation):
    target_observation_ids: tuple[str, ...]
    severity: Literal["recoverable", "ambiguous", "unrecoverable"]
    overlap_ratio: float

    def to_payload(self) -> dict[str, Any]:
        return {
            **self.spatial_payload(),
            "target_observation_ids": list(self.target_observation_ids),
            "severity": self.severity,
            "overlap_ratio": self.overlap_ratio,
        }


@dataclass(frozen=True)
class ProblemRegionProposal:
    proposal_id: str
    question_label: str
    page_ids: tuple[str, ...]
    polygons: tuple[Polygon, ...]
    included_block_ids: tuple[str, ...]
    confidence: float
    reason_codes: tuple[str, ...]
    requires_confirmation: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "question_label": self.question_label,
            "page_ids": list(self.page_ids),
            "polygons": [_polygon_payload(item) for item in self.polygons],
            "included_block_ids": list(self.included_block_ids),
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class ObservationIssue:
    issue_id: str
    code: str
    blocking: bool
    retryable: bool
    observation_ids: tuple[str, ...] = ()
    details: Mapping[str, FrozenJson] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_json(self.details))

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "code": self.code,
            "blocking": self.blocking,
            "retryable": self.retryable,
            "observation_ids": list(self.observation_ids),
            "details": thaw_json(self.details),
        }


@dataclass(frozen=True)
class SourceObservation:
    schema_version: str
    source_id: str
    source_revision_hash: str
    selection_id: str
    dependency_hash: str
    providers: tuple[ProviderManifest, ...]
    pages: tuple[PageObservation, ...]
    layout_blocks: tuple[LayoutBlock, ...]
    text_spans: tuple[TextSpanObservation, ...]
    formulas: tuple[FormulaObservation, ...]
    ink_origins: tuple[InkOriginObservation, ...]
    occlusions: tuple[OcclusionObservation, ...]
    proposals: tuple[ProblemRegionProposal, ...]
    selected_observation_ids: tuple[str, ...]
    issues: tuple[ObservationIssue, ...]
    observation_hash: str

    @classmethod
    def create(
        cls,
        *,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
        dependency_hash: str,
        providers: Sequence[ProviderManifest],
        pages: Sequence[PageObservation],
        layout_blocks: Sequence[LayoutBlock] = (),
        text_spans: Sequence[TextSpanObservation] = (),
        formulas: Sequence[FormulaObservation] = (),
        ink_origins: Sequence[InkOriginObservation] = (),
        occlusions: Sequence[OcclusionObservation] = (),
        proposals: Sequence[ProblemRegionProposal] = (),
        selected_observation_ids: Sequence[str] = (),
        issues: Sequence[ObservationIssue] = (),
    ) -> SourceObservation:
        provider_items = tuple(sorted(providers, key=lambda item: item.provider_id))
        page_items = tuple(sorted(pages, key=lambda item: item.page_id))
        block_items = _sort_spatial(layout_blocks)
        text_items = _sort_spatial(text_spans)
        formula_items = _sort_spatial(formulas)
        ink_items = _sort_spatial(ink_origins)
        occlusion_items = _sort_spatial(occlusions)
        proposal_items = tuple(sorted(proposals, key=lambda item: item.proposal_id))
        selected = tuple(sorted(set(selected_observation_ids)))
        issue_items = tuple(sorted(issues, key=lambda item: item.issue_id))
        provisional = cls(
            schema_version=SOURCE_OBSERVATION_SCHEMA_VERSION,
            source_id=source.source_id,
            source_revision_hash=source.source_revision_hash,
            selection_id=selection.selection_id,
            dependency_hash=dependency_hash,
            providers=provider_items,
            pages=page_items,
            layout_blocks=block_items,
            text_spans=text_items,
            formulas=formula_items,
            ink_origins=ink_items,
            occlusions=occlusion_items,
            proposals=proposal_items,
            selected_observation_ids=selected,
            issues=issue_items,
            observation_hash="",
        )
        result = replace(
            provisional,
            observation_hash=stable_hash(provisional._authority_payload()),
        )
        result.validate(source, selection, dependency_hash)
        return result

    @property
    def spatial_observations(self) -> tuple[SpatialObservation, ...]:
        return (
            self.layout_blocks
            + self.text_spans
            + self.formulas
            + self.ink_origins
            + self.occlusions
        )

    def _authority_payload(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload.pop("observation_hash", None)
        return payload

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_revision_hash": self.source_revision_hash,
            "selection_id": self.selection_id,
            "dependency_hash": self.dependency_hash,
            "providers": [item.to_payload() for item in self.providers],
            "pages": [item.to_payload() for item in self.pages],
            "layout_blocks": [item.to_payload() for item in self.layout_blocks],
            "text_spans": [item.to_payload() for item in self.text_spans],
            "formulas": [item.to_payload() for item in self.formulas],
            "ink_origins": [item.to_payload() for item in self.ink_origins],
            "occlusions": [item.to_payload() for item in self.occlusions],
            "proposals": [item.to_payload() for item in self.proposals],
            "selected_observation_ids": list(self.selected_observation_ids),
            "issues": [item.to_payload() for item in self.issues],
            "observation_hash": self.observation_hash,
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
        dependency_hash: str,
    ) -> SourceObservation:
        errors = sorted(_observation_schema_validator().iter_errors(payload), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            raise _observation_error(
                "extraction.observation_invalid",
                "$" + "".join(f"[{part!r}]" for part in first.path),
                first.message,
            )
        result = cls(
            schema_version=str(payload["schema_version"]),
            source_id=str(payload["source_id"]),
            source_revision_hash=str(payload["source_revision_hash"]),
            selection_id=str(payload["selection_id"]),
            dependency_hash=str(payload["dependency_hash"]),
            providers=tuple(ProviderManifest.from_payload(item) for item in payload["providers"]),
            pages=tuple(_page_from_payload(item) for item in payload["pages"]),
            layout_blocks=tuple(_layout_from_payload(item) for item in payload["layout_blocks"]),
            text_spans=tuple(_text_from_payload(item) for item in payload["text_spans"]),
            formulas=tuple(_formula_from_payload(item) for item in payload["formulas"]),
            ink_origins=tuple(_ink_from_payload(item) for item in payload["ink_origins"]),
            occlusions=tuple(_occlusion_from_payload(item) for item in payload["occlusions"]),
            proposals=tuple(_proposal_from_payload(item) for item in payload["proposals"]),
            selected_observation_ids=tuple(str(item) for item in payload["selected_observation_ids"]),
            issues=tuple(_issue_from_payload(item) for item in payload["issues"]),
            observation_hash=str(payload["observation_hash"]),
        )
        result.validate(source, selection, dependency_hash)
        return result

    def validate(
        self,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
        dependency_hash: str,
    ) -> None:
        if self.schema_version != SOURCE_OBSERVATION_SCHEMA_VERSION:
            raise _observation_error("extraction.observation_invalid", "$.schema_version", self.schema_version)
        expected_identity = (
            source.source_id,
            source.source_revision_hash,
            selection.selection_id,
            dependency_hash,
        )
        actual_identity = (
            self.source_id,
            self.source_revision_hash,
            self.selection_id,
            self.dependency_hash,
        )
        if actual_identity != expected_identity:
            raise _observation_error(
                "extraction.observation_invalid",
                "$",
                "observation source, selection, or dependency identity drifted",
            )
        provider_ids = {item.provider_id for item in self.providers}
        page_ids = {item.page_id for item in self.pages}
        source_page_ids = {item.page_id for item in source.pages}
        if page_ids != source_page_ids:
            raise _observation_error("extraction.observation_invalid", "$.pages", "page set differs from source")
        observation_ids = [item.observation_id for item in self.spatial_observations]
        if len(observation_ids) != len(set(observation_ids)):
            raise _observation_error("extraction.observation_invalid", "$.observations", "duplicate observation id")
        observations = {item.observation_id: item for item in self.spatial_observations}
        for item in self.spatial_observations:
            _validate_polygon(item.polygon, f"$.observations.{item.observation_id}.polygon")
            _validate_confidence(item.confidence, f"$.observations.{item.observation_id}.confidence")
            if item.page_id not in page_ids or item.provider_id not in provider_ids:
                raise _observation_error(
                    "extraction.observation_invalid",
                    f"$.observations.{item.observation_id}",
                    "observation references an unknown page or provider",
                )
        if set(self.selected_observation_ids) - set(observations):
            raise _observation_error(
                "extraction.observation_invalid",
                "$.selected_observation_ids",
                "selected observation id is unresolved",
            )
        for page in self.pages:
            unresolved = set(page.layout_block_ids + page.reading_order) - set(observations)
            if unresolved:
                raise _observation_error("extraction.observation_invalid", "$.pages", f"unresolved page observations: {sorted(unresolved)}")
        for formula in self.formulas:
            if set(formula.source_observation_ids) - set(observations):
                raise _observation_error("extraction.observation_invalid", "$.formulas", "formula source is unresolved")
            if not re.fullmatch(r"formula-request:[a-f0-9]{64}", formula.formula_request_id):
                raise _observation_error(
                    "extraction.formula_observation_unresolved",
                    "$.formulas.formula_request_id",
                    "formula request identity is missing or invalid",
                )
            if formula.status == "recognized" and not formula.latex:
                raise _observation_error("extraction.formula_observation_unresolved", "$.formulas", "recognized formula has no LaTeX")
            if formula.status == "recognized" and formula.origin != "printed":
                raise _observation_error(
                    "extraction.formula_observation_unresolved",
                    "$.formulas",
                    "only printed formula observations may be recognized",
                )
            if formula.status == "recognized":
                source_texts = (
                    (formula.source_text_hint,)
                    if formula.source_text_hint is not None
                    else tuple(
                        source.text
                        for source_id in formula.source_observation_ids
                        if isinstance((source := observations[source_id]), TextSpanObservation)
                    )
                )
                reason = formula_recognition_failure_reason(
                    source_texts,
                    formula.latex or "",
                )
                if reason is not None:
                    raise _observation_error(
                        "extraction.formula_observation_unresolved",
                        "$.formulas",
                        f"recognized formula failed source fidelity audit: {reason}",
                    )
        formula_request_ids = [item.formula_request_id for item in self.formulas]
        if len(formula_request_ids) != len(set(formula_request_ids)):
            raise _observation_error(
                "extraction.formula_observation_unresolved",
                "$.formulas.formula_request_id",
                "formula request identity may appear at most once",
            )
        for ink in self.ink_origins:
            if set(ink.overlap_observation_ids) - set(observations):
                raise _observation_error("extraction.observation_invalid", "$.ink_origins", "ink overlap is unresolved")
        for occlusion in self.occlusions:
            if set(occlusion.target_observation_ids) - set(observations):
                raise _observation_error("extraction.observation_invalid", "$.occlusions", "occlusion target is unresolved")
        layout_ids = {item.observation_id for item in self.layout_blocks}
        for proposal in self.proposals:
            if len(proposal.page_ids) != len(proposal.polygons):
                raise _observation_error(
                    "extraction.problem_region_incomplete",
                    "$.proposals",
                    "proposal pages and polygons must have the same cardinality",
                )
            if set(proposal.page_ids) - page_ids:
                raise _observation_error(
                    "extraction.problem_region_incomplete",
                    "$.proposals.page_ids",
                    "proposal references an unknown page",
                )
            if set(proposal.included_block_ids) - layout_ids:
                raise _observation_error(
                    "extraction.selection_block_unresolved",
                    "$.proposals.included_block_ids",
                    "proposal references an unknown layout block",
                )
            for polygon in proposal.polygons:
                _validate_polygon(polygon, "$.proposals.polygons")
            _validate_confidence(proposal.confidence, "$.proposals.confidence")
        if self.observation_hash != stable_hash(self._authority_payload()):
            raise _observation_error("extraction.observation_invalid", "$.observation_hash", "observation hash mismatch")

    def validate_artifact_closure(self, artifact_ids: Sequence[str] | set[str]) -> None:
        available = set(artifact_ids)
        source_artifact_ids = {
            item.source_artifact_id
            for item in self.spatial_observations
        } | {page.source_artifact_id for page in self.pages}
        missing_sources = source_artifact_ids - available
        if missing_sources:
            raise _observation_error(
                "extraction.evidence_ref_unresolved",
                "$.observations.source_artifact_id",
                f"source artifacts are missing: {sorted(missing_sources)}",
            )
        missing_crops = {
            formula.crop_artifact_id
            for formula in self.formulas
            if formula.crop_artifact_id is None or formula.crop_artifact_id not in available
        }
        if missing_crops:
            raise _observation_error(
                "extraction.formula_observation_unresolved",
                "$.formulas.crop_artifact_id",
                f"formula crops are missing: {sorted(str(item) for item in missing_crops)}",
            )
        missing_masks = {
            ink.mask_artifact_id
            for ink in self.ink_origins
            if ink.mask_artifact_id is None or ink.mask_artifact_id not in available
        }
        if missing_masks:
            raise _observation_error(
                "extraction.evidence_ref_unresolved",
                "$.ink_origins.mask_artifact_id",
                f"handwriting masks are missing: {sorted(str(item) for item in missing_masks)}",
            )


@dataclass(frozen=True)
class PaddleProviderRecord:
    schema_version: str
    component: ObservationComponent
    provider: ProviderManifest
    source_revision_hash: str
    page_id: str
    width: int
    height: int
    items: tuple[Mapping[str, FrozenJson], ...]
    latency_ms: int
    record_hash: str

    @classmethod
    def create(
        cls,
        *,
        component: ObservationComponent,
        provider: ProviderManifest,
        source_revision_hash: str,
        page_id: str,
        width: int,
        height: int,
        items: Sequence[Mapping[str, Any]],
        latency_ms: int = 0,
    ) -> PaddleProviderRecord:
        frozen_items = tuple(freeze_json(item) for item in items)
        if not all(isinstance(item, Mapping) for item in frozen_items):
            raise _observation_error("extraction.provider_record_invalid", "$.items", "provider items must be objects")
        provisional = cls(
            schema_version=PADDLE_PROVIDER_RECORD_SCHEMA_VERSION,
            component=component,
            provider=provider,
            source_revision_hash=source_revision_hash,
            page_id=page_id,
            width=width,
            height=height,
            items=frozen_items,  # type: ignore[arg-type]
            latency_ms=latency_ms,
            record_hash="",
        )
        result = replace(provisional, record_hash=stable_hash(provisional._authority_payload()))
        result.validate()
        return result

    def _authority_payload(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload.pop("record_hash", None)
        return payload

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "component": self.component,
            "provider": self.provider.to_payload(),
            "source_revision_hash": self.source_revision_hash,
            "page_id": self.page_id,
            "width": self.width,
            "height": self.height,
            "items": [thaw_json(item) for item in self.items],
            "latency_ms": self.latency_ms,
            "record_hash": self.record_hash,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> PaddleProviderRecord:
        errors = sorted(_provider_schema_validator().iter_errors(payload), key=lambda item: list(item.path))
        if errors:
            first = errors[0]
            raise _observation_error("extraction.provider_record_invalid", "$", first.message)
        result = cls(
            schema_version=str(payload["schema_version"]),
            component=str(payload["component"]),  # type: ignore[arg-type]
            provider=ProviderManifest.from_payload(_mapping(payload["provider"])),
            source_revision_hash=str(payload["source_revision_hash"]),
            page_id=str(payload["page_id"]),
            width=int(payload["width"]),
            height=int(payload["height"]),
            items=tuple(freeze_json(_mapping(item)) for item in payload["items"]),  # type: ignore[arg-type]
            latency_ms=int(payload["latency_ms"]),
            record_hash=str(payload["record_hash"]),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if self.schema_version != PADDLE_PROVIDER_RECORD_SCHEMA_VERSION:
            raise _observation_error("extraction.provider_record_invalid", "$.schema_version", self.schema_version)
        if self.component != self.provider.component:
            raise _observation_error("extraction.provider_record_invalid", "$.component", "provider component drift")
        if self.width <= 0 or self.height <= 0 or self.latency_ms < 0:
            raise _observation_error("extraction.provider_record_invalid", "$", "invalid dimensions or latency")
        for index, item in enumerate(self.items):
            _reject_semantic_keys(item, f"$.items[{index}]")
            polygon = _pixel_polygon(item.get("polygon"), self.width, self.height)
            _validate_polygon(polygon, f"$.items[{index}].polygon")
            _validate_confidence(float(item.get("confidence", 0.0)), f"$.items[{index}].confidence")
        if self.record_hash != stable_hash(self._authority_payload()):
            raise _observation_error("extraction.provider_record_invalid", "$.record_hash", "record hash mismatch")


class PaddleObservationAdapter:
    """Normalize Paddle records without importing Paddle or NumPy."""

    _LAYOUT_KIND = {
        "formula": "formula",
        "formula_number": "formula",
        "image": "figure",
        "header_image": "figure",
        "footer_image": "figure",
        "chart": "figure",
        "table": "table",
        "header": "header",
        "footer": "footer",
        "seal": "watermark",
        "number": "number",
    }

    def layout(
        self,
        record: PaddleProviderRecord,
        *,
        source_artifact_id: str,
    ) -> tuple[LayoutBlock, ...]:
        self._require_component(record, "layout")
        provisional: list[LayoutBlock] = []
        for item in record.items:
            label = str(item.get("label", "unknown"))
            polygon = _pixel_polygon(item.get("polygon"), record.width, record.height)
            kind = self._LAYOUT_KIND.get(label, "text")
            provisional.append(
                LayoutBlock(
                    observation_id=_observation_id(
                        "layout",
                        record.page_id,
                        polygon,
                        {"kind": kind, "provider_label": label, "provider": record.provider.provider_id},
                    ),
                    page_id=record.page_id,
                    polygon=polygon,
                    confidence=_confidence(item.get("confidence")),
                    origin="printed" if kind not in {"figure", "watermark"} else "unknown",
                    source_artifact_id=source_artifact_id,
                    provider_id=record.provider.provider_id,
                    reading_order=0,
                    kind=kind,
                    provider_label=label,
                )
            )
        return tuple(replace(item, reading_order=index) for index, item in enumerate(_sort_spatial(provisional)))

    def text(
        self,
        record: PaddleProviderRecord,
        *,
        source_artifact_id: str,
        layout_blocks: Sequence[LayoutBlock] = (),
    ) -> tuple[TextSpanObservation, ...]:
        self._require_component(record, "text_ocr")
        provisional: list[TextSpanObservation] = []
        for item in record.items:
            polygon = _pixel_polygon(item.get("polygon"), record.width, record.height)
            text = normalize_observed_text(str(item.get("text", "")))
            block_id = _best_containing_block(polygon, layout_blocks)
            origin: ObservationOrigin = "printed" if block_id is not None else "unknown"
            confidence = _confidence(item.get("confidence"))
            if confidence < 0.65:
                origin = "unknown"
            provisional.append(
                TextSpanObservation(
                    observation_id=_observation_id(
                        "text",
                        record.page_id,
                        polygon,
                        {"text": text, "provider": record.provider.provider_id},
                    ),
                    page_id=record.page_id,
                    polygon=polygon,
                    confidence=confidence,
                    origin=origin,
                    source_artifact_id=source_artifact_id,
                    provider_id=record.provider.provider_id,
                    reading_order=0,
                    text=text,
                    block_id=block_id,
                )
            )
        return tuple(replace(item, reading_order=index) for index, item in enumerate(_sort_spatial(provisional)))

    def formulas(
        self,
        record: PaddleProviderRecord,
        *,
        source_artifact_id: str,
    ) -> tuple[FormulaObservation, ...]:
        self._require_component(record, "formula_ocr")
        provisional: list[FormulaObservation] = []
        for item in record.items:
            polygon = _pixel_polygon(item.get("polygon"), record.width, record.height)
            latex = normalize_formula_text(str(item.get("latex", ""))) or None
            source_ids = tuple(sorted(str(value) for value in item.get("source_observation_ids", ())))
            status: Literal["recognized", "unresolved"] = "recognized" if latex else "unresolved"
            provisional.append(
                FormulaObservation(
                    observation_id=_observation_id(
                        "formula",
                        record.page_id,
                        polygon,
                        {
                            "latex": latex,
                            "sources": source_ids,
                            "formula_request_id": item.get("formula_request_id"),
                            "provider": record.provider.provider_id,
                        },
                    ),
                    page_id=record.page_id,
                    polygon=polygon,
                    confidence=_confidence(item.get("confidence")),
                    origin="printed",
                    source_artifact_id=source_artifact_id,
                    provider_id=record.provider.provider_id,
                    reading_order=0,
                    latex=latex,
                    status=status,
                    source_observation_ids=source_ids,
                    formula_request_id=_required_formula_request_id(item),
                    source_text_hint=(
                        normalize_observed_text(str(item["source_text_hint"]))
                        if item.get("source_text_hint")
                        else None
                    ),
                    crop_artifact_id=(str(item["crop_artifact_id"]) if item.get("crop_artifact_id") else None),
                )
            )
        return tuple(replace(item, reading_order=index) for index, item in enumerate(_sort_spatial(provisional)))

    @staticmethod
    def _require_component(record: PaddleProviderRecord, component: ObservationComponent) -> None:
        record.validate()
        if record.component != component:
            raise _observation_error(
                "extraction.provider_record_invalid",
                "$.component",
                f"expected {component}, got {record.component}",
            )


@dataclass(frozen=True)
class FormulaCropRequest:
    request_id: str
    page_id: str
    polygon: Polygon
    source_observation_ids: tuple[str, ...]
    source_text_hint: str | None
    source_text_range: tuple[int, int] | None


@dataclass(frozen=True)
class _FormulaTextFragment:
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class _FormulaCropCandidate:
    page_id: str
    polygon: Polygon
    source_observation_ids: tuple[str, ...]
    source_text_hint: str | None
    source_text_range: tuple[int, int] | None


def select_formula_crop_requests(
    layout_blocks: Sequence[LayoutBlock],
    text_spans: Sequence[TextSpanObservation],
    *,
    ink_origins: Sequence[InkOriginObservation] = (),
) -> tuple[FormulaCropRequest, ...]:
    candidates: list[_FormulaCropCandidate] = []
    for span in text_spans:
        if span.origin != "printed":
            continue
        for fragment in _formula_text_fragments(span.text):
            candidates.append(
                _FormulaCropCandidate(
                    page_id=span.page_id,
                    polygon=_formula_fragment_polygon(
                        span.polygon,
                        span.text,
                        fragment.start,
                        fragment.end,
                    ),
                    source_observation_ids=(span.observation_id,),
                    source_text_hint=fragment.text,
                    source_text_range=(fragment.start, fragment.end),
                )
            )
    for block in layout_blocks:
        if (
            block.kind == "formula"
            and block.origin == "printed"
            and not any(
                ink.page_id == block.page_id
                and ink.origin in {"handwritten", "mixed"}
                and bbox_iou(ink.polygon, block.polygon) > 0
                for ink in ink_origins
            )
        ):
            if any(
                candidate.page_id == block.page_id
                and bbox_overlap_ratio(candidate.polygon, block.polygon) >= 0.8
                for candidate in candidates
            ):
                continue
            candidates.append(
                _FormulaCropCandidate(
                    page_id=block.page_id,
                    polygon=block.polygon,
                    source_observation_ids=(block.observation_id,),
                    source_text_hint=None,
                    source_text_range=None,
                )
            )
    deduplicated: list[_FormulaCropCandidate] = []
    for candidate in _sort_formula_candidates(candidates):
        existing = next(
            (
                item
                for item in deduplicated
                if item.page_id == candidate.page_id
                and item.source_text_hint == candidate.source_text_hint
                and bbox_iou(item.polygon, candidate.polygon) >= 0.8
            ),
            None,
        )
        if existing is None:
            deduplicated.append(candidate)
    result = []
    for candidate in deduplicated:
        sources = tuple(sorted(candidate.source_observation_ids))
        request_id = f"formula-request:{stable_hash({'page_id': candidate.page_id, 'polygon': _polygon_payload(candidate.polygon), 'sources': sources, 'source_text_hint': candidate.source_text_hint, 'source_text_range': candidate.source_text_range})}"
        result.append(
            FormulaCropRequest(
                request_id=request_id,
                page_id=candidate.page_id,
                polygon=candidate.polygon,
                source_observation_ids=sources,
                source_text_hint=candidate.source_text_hint,
                source_text_range=candidate.source_text_range,
            )
        )
    return tuple(result)


def unresolved_formula_source_ids(
    layout_blocks: Sequence[LayoutBlock],
    text_spans: Sequence[TextSpanObservation],
    *,
    ink_origins: Sequence[InkOriginObservation] = (),
) -> tuple[str, ...]:
    """Return selected math candidates that are unsafe for formula OCR."""

    unresolved = {
        span.observation_id
        for span in text_spans
        if span.origin in {"handwritten", "mixed", "unknown"}
        and _MATH_TEXT.search(span.text)
    }
    unresolved.update(
        block.observation_id
        for block in layout_blocks
        if block.kind == "formula"
        and any(
            ink.page_id == block.page_id
            and ink.origin in {"handwritten", "mixed"}
            and bbox_iou(ink.polygon, block.polygon) > 0
            for ink in ink_origins
        )
    )
    return tuple(sorted(unresolved))


class ProblemRegionProposer:
    """Propose question regions from canonical layout and OCR observations."""

    def propose(
        self,
        *,
        pages: Sequence[PageObservation],
        layout_blocks: Sequence[LayoutBlock],
        text_spans: Sequence[TextSpanObservation],
    ) -> tuple[tuple[ProblemRegionProposal, ...], tuple[ObservationIssue, ...]]:
        page_order = {item.page_id: index for index, item in enumerate(pages)}
        page_items: dict[str, list[SpatialObservation]] = {}
        for item in tuple(layout_blocks) + tuple(text_spans):
            page_items.setdefault(item.page_id, []).append(item)
        single_column_by_page = {
            page_id: any(
                polygon_bbox(item.polygon)[0] < 0.42
                and polygon_bbox(item.polygon)[2] > 0.52
                for item in items
            )
            for page_id, items in page_items.items()
        }
        markers = []
        for span in text_spans:
            match = _QUESTION_LABEL.match(span.text)
            if match:
                column = _spatial_column(
                    span.polygon,
                    single_column=single_column_by_page.get(span.page_id, True),
                )
                markers.append(
                    (span, match.group("bare") or match.group("wrapped"), column)
                )
        markers.sort(
            key=lambda item: (
                page_order[item[0].page_id],
                item[2],
                item[0].reading_order,
                item[0].observation_id,
            )
        )
        proposals: list[ProblemRegionProposal] = []
        issues: list[ObservationIssue] = []
        ordered_page_ids = tuple(
            item.page_id
            for item in sorted(pages, key=lambda item: page_order[item.page_id])
        )
        for index, (marker, label, marker_column) in enumerate(markers):
            next_marker = next(
                (
                    item[0]
                    for item in markers[index + 1 :]
                    if item[0].page_id == marker.page_id
                    and item[2] == marker_column
                ),
                None,
            )
            top = polygon_bbox(marker.polygon)[1]
            bottom = polygon_bbox(next_marker.polygon)[1] if next_marker is not None else 1.0
            excluded_layout_ids = {
                block.observation_id
                for block in layout_blocks
                if block.kind in {"header", "footer", "watermark"}
            }
            selected_blocks = tuple(
                block
                for block in layout_blocks
                if block.page_id == marker.page_id
                and _spatial_column(
                    block.polygon,
                    single_column=single_column_by_page.get(block.page_id, True),
                )
                == marker_column
                and top <= _center(block.polygon)[1] < bottom
                and block.kind not in {"header", "footer", "watermark"}
            )
            selected_spans = tuple(
                span
                for span in text_spans
                if span.page_id == marker.page_id
                and span.block_id not in excluded_layout_ids
                and _spatial_column(
                    span.polygon,
                    single_column=single_column_by_page.get(span.page_id, True),
                )
                == marker_column
                and top <= _center(span.polygon)[1] < bottom
            )
            spatial = selected_blocks + selected_spans
            if not spatial:
                continue
            proposal_page_ids = [marker.page_id]
            proposal_polygons = [
                bbox_polygon(_union_bbox(item.polygon for item in spatial))
            ]
            included_ids = {item.observation_id for item in selected_blocks}
            cross_page = False
            marker_page_index = page_order.get(marker.page_id)
            reaches_page_bottom = max(
                polygon_bbox(item.polygon)[3] for item in spatial
            ) >= 0.8
            if (
                next_marker is None
                and reaches_page_bottom
                and marker_page_index is not None
                and marker_page_index + 1 < len(ordered_page_ids)
            ):
                continuation_page_id = ordered_page_ids[marker_page_index + 1]
                continuation_marker = next(
                    (
                        item[0]
                        for item in markers
                        if item[0].page_id == continuation_page_id
                        and item[2] == marker_column
                    ),
                    None,
                )
                continuation_bottom = (
                    polygon_bbox(continuation_marker.polygon)[1]
                    if continuation_marker is not None
                    else 1.0
                )
                continuation_blocks = tuple(
                    block
                    for block in layout_blocks
                    if block.page_id == continuation_page_id
                    and block.kind not in {"header", "footer", "watermark"}
                    and _spatial_column(
                        block.polygon,
                        single_column=single_column_by_page.get(
                            continuation_page_id,
                            True,
                        ),
                    )
                    == marker_column
                    and _center(block.polygon)[1] < continuation_bottom
                )
                continuation_block_ids = {
                    block.observation_id for block in continuation_blocks
                }
                continuation_spans = tuple(
                    span
                    for span in text_spans
                    if span.page_id == continuation_page_id
                    and span.block_id not in excluded_layout_ids
                    and _spatial_column(
                        span.polygon,
                        single_column=single_column_by_page.get(
                            continuation_page_id,
                            True,
                        ),
                    )
                    == marker_column
                    and _center(span.polygon)[1] < continuation_bottom
                )
                continuation_spatial = continuation_blocks + continuation_spans
                if continuation_spatial:
                    proposal_page_ids.append(continuation_page_id)
                    proposal_polygons.append(
                        bbox_polygon(
                            _union_bbox(
                                item.polygon for item in continuation_spatial
                            )
                        )
                    )
                    included_ids.update(continuation_block_ids)
                    cross_page = True
            included = tuple(sorted(included_ids))
            authority = {
                "label": label,
                "page_ids": proposal_page_ids,
                "polygons": [
                    _polygon_payload(polygon) for polygon in proposal_polygons
                ],
                "included": included,
            }
            reasons = ["question_number", "reading_order_boundary"]
            if any(item.kind in {"figure", "formula"} for item in selected_blocks):
                reasons.append("adjacent_visual_block")
            if cross_page:
                reasons.append("cross_page_continuation")
            proposal = ProblemRegionProposal(
                proposal_id=f"problem-region:{stable_hash(authority)}",
                question_label=label,
                page_ids=tuple(proposal_page_ids),
                polygons=tuple(proposal_polygons),
                included_block_ids=included,
                confidence=round(min(marker.confidence, 0.99), 6),
                reason_codes=tuple(reasons),
                requires_confirmation=(
                    next_marker is None
                    or marker.origin != "printed"
                    or cross_page
                ),
            )
            proposals.append(proposal)
        labels = [item.question_label for item in proposals]
        duplicates = sorted({item for item in labels if labels.count(item) > 1})
        if duplicates:
            issues.append(
                make_observation_issue(
                    "extraction.problem_region_ambiguous",
                    blocking=True,
                    retryable=False,
                    details={"duplicate_question_labels": duplicates},
                )
            )
        if not proposals:
            issues.append(
                make_observation_issue(
                    "extraction.problem_region_incomplete",
                    blocking=True,
                    retryable=False,
                    details={"reason": "no_question_label_detected"},
                )
            )
        return tuple(sorted(proposals, key=lambda item: item.proposal_id)), tuple(issues)


def selected_observation_ids(
    selection: SourceSelection,
    observations: Sequence[SpatialObservation],
) -> tuple[str, ...]:
    selected = []
    for item in observations:
        regions = [region for region in selection.regions if region.page_id == item.page_id]
        if any(
            _point_in_polygon(_center(item.polygon), region.polygon)
            or bbox_overlap_ratio(item.polygon, region.polygon) >= 0.5
            for region in regions
        ):
            selected.append(item.observation_id)
    return tuple(sorted(selected))


def make_observation_issue(
    code: str,
    *,
    blocking: bool,
    retryable: bool,
    observation_ids: Sequence[str] = (),
    details: Mapping[str, Any] | None = None,
) -> ObservationIssue:
    observations = tuple(sorted(set(observation_ids)))
    payload = {"code": code, "observations": observations, "details": dict(details or {})}
    return ObservationIssue(
        issue_id=f"observation-issue:{stable_hash(payload)}",
        code=code,
        blocking=blocking,
        retryable=retryable,
        observation_ids=observations,
        details=details or {},
    )


def normalize_observed_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.replace("\u00a0", " ").split())


def normalize_formula_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    return re.sub(r"\s+", " ", normalized)


def formula_math_fragments(value: str) -> tuple[str, ...]:
    """Extract lexical math fragments without assigning mathematical semantics."""

    fragments: list[str] = []
    for fragment in _formula_text_fragments(value):
        compact = _compact_formula_math(fragment.text)
        if compact and compact not in fragments:
            fragments.append(compact)
    return tuple(fragments)


def _formula_text_fragments(value: str) -> tuple[_FormulaTextFragment, ...]:
    normalized = unicodedata.normalize("NFKC", value)
    fragments: list[_FormulaTextFragment] = []
    for match in _MATH_FRAGMENT_RUN.finditer(normalized):
        start, end = _trim_fragment_range(normalized, match.start(), match.end())
        if start >= end:
            continue
        leading = re.match(
            r"(?:\(?\d{1,3}\)?[.)．、])+",
            normalized[start:end],
        )
        if leading is not None:
            start += leading.end()
            start, end = _trim_fragment_range(normalized, start, end)
        candidate = normalized[start:end]
        is_coordinate = _POINT_COORDINATE_FRAGMENT.fullmatch(candidate) is not None
        if not is_coordinate:
            while start < end and normalized[start] in "(（":
                start += 1
            while end > start and normalized[end - 1] in ")）":
                end -= 1
            start, end = _trim_fragment_range(normalized, start, end)
        if start >= end:
            continue
        part_ranges = ((start, end),)
        opening = normalized.find("(", start, end)
        if opening >= 0 and not is_coordinate:
            suffix_end = end - 1 if normalized[end - 1] == ")" else end
            part_ranges = ((start, opening), (opening + 1, suffix_end))
        for part_start, part_end in part_ranges:
            part_start, part_end = _trim_fragment_range(
                normalized,
                part_start,
                part_end,
            )
            if part_start >= part_end:
                continue
            part = normalized[part_start:part_end]
            if _MATH_FRAGMENT_OPERATOR.search(part) is None:
                continue
            compact = _compact_formula_math(part)
            if not compact:
                continue
            fragments.append(
                _FormulaTextFragment(
                    text=part,
                    start=part_start,
                    end=part_end,
                )
            )
    return tuple(fragments)


def _trim_fragment_range(value: str, start: int, end: int) -> tuple[int, int]:
    trim_chars = " \t\r\n.,，:：;；"
    while start < end and value[start] in trim_chars:
        start += 1
    while end > start and value[end - 1] in trim_chars:
        end -= 1
    return start, end


def _formula_fragment_polygon(
    polygon: Polygon,
    source_text: str,
    start: int,
    end: int,
) -> Polygon:
    normalized = unicodedata.normalize("NFKC", source_text)
    weights = tuple(_display_character_weight(character) for character in normalized)
    total = sum(weights)
    if total <= 0 or not 0 <= start < end <= len(weights):
        return polygon
    fragment_weight = sum(weights[start:end])
    padding = min(1.25, max(0.45, fragment_weight * 0.04))
    start_weight = max(0.0, sum(weights[:start]) - padding)
    end_weight = min(total, sum(weights[:end]) + padding)
    left, top, right, bottom = polygon_bbox(polygon)
    width = right - left
    height = bottom - top
    return bbox_polygon(
        (
            left + width * start_weight / total,
            max(0.0, top - height * 0.08),
            left + width * end_weight / total,
            min(1.0, bottom + height * 0.08),
        )
    )


def _display_character_weight(character: str) -> float:
    if character.isspace():
        return 0.45
    if unicodedata.east_asian_width(character) in {"W", "F", "A"}:
        return 1.0
    if character in "√∠≤≥°":
        return 0.9
    if character in ",.，。:：;；()（）[]{}":
        return 0.42
    return 0.58


def formula_recognition_failure_reason(
    source_texts: Sequence[str],
    latex: str,
) -> str | None:
    """Return why Formula OCR cannot be treated as faithful printed math."""

    normalized = normalize_formula_text(latex)
    if not normalized:
        return "formula_output_empty"
    fragments = tuple(
        fragment
        for source_text in source_texts
        for fragment in formula_math_fragments(source_text)
    )
    output_compact = _compact_formula_math(normalized)
    source_size = sum(len(fragment) for fragment in fragments)
    if len(output_compact) > max(160, source_size * 6):
        return "formula_output_excessive_expansion"
    if _CJK_TEXT.search(normalized):
        return "formula_output_contains_prose"
    commands = _LATEX_COMMAND.findall(normalized)
    if commands and len(commands) >= 24:
        most_common = max(commands.count(command) for command in set(commands))
        if most_common >= 12 and most_common / len(commands) >= 0.4:
            return "formula_output_repetitive"
    if len(fragments) == 1 and output_compact != fragments[0]:
        if fragments[0] not in output_compact:
            return "formula_output_incomplete"
        return "formula_output_contains_unexpected_content"
    if fragments and any(fragment not in output_compact for fragment in fragments):
        return "formula_output_incomplete"
    return None


def _compact_formula_math(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    replacements = {
        "\\because": "",
        "\\therefore": "",
        "\\geq": ">=",
        "\\ge": ">=",
        "\\leq": "<=",
        "\\le": "<=",
        "\\angle": "∠",
        "\\circ": "°",
        "\\times": "*",
        "\\cdot": "*",
        "×": "*",
        "÷": "/",
        "²": "2",
        "³": "3",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"\\sqrt\s*\{([^{}]+)\}", r"√\1", normalized)
    normalized = re.sub(r"\\(?:left|right|quad|qquad|,|;|!| )", "", normalized)
    normalized = re.sub(r"\^\{([^{}]+)\}", r"\1", normalized)
    normalized = re.sub(r"\^([A-Za-z0-9])", r"\1", normalized)
    normalized = normalized.replace("{", "").replace("}", "")
    return re.sub(r"[^A-Za-z0-9√∠°+\-*/=<>≤≥(),.]", "", normalized).strip(".,")


def bbox_polygon(bbox: tuple[float, float, float, float]) -> Polygon:
    left, top, right, bottom = bbox
    return _canonical_polygon(((left, top), (right, top), (right, bottom), (left, bottom)))


def polygon_bbox(polygon: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    return (
        min(point[0] for point in polygon),
        min(point[1] for point in polygon),
        max(point[0] for point in polygon),
        max(point[1] for point in polygon),
    )


def bbox_iou(left: Polygon, right: Polygon) -> float:
    l1, t1, r1, b1 = polygon_bbox(left)
    l2, t2, r2, b2 = polygon_bbox(right)
    intersection = max(0.0, min(r1, r2) - max(l1, l2)) * max(0.0, min(b1, b2) - max(t1, t2))
    area_left = max(0.0, r1 - l1) * max(0.0, b1 - t1)
    area_right = max(0.0, r2 - l2) * max(0.0, b2 - t2)
    union = area_left + area_right - intersection
    return intersection / union if union else 0.0


def bbox_overlap_ratio(subject: Polygon, container: Polygon) -> float:
    l1, t1, r1, b1 = polygon_bbox(subject)
    l2, t2, r2, b2 = polygon_bbox(container)
    intersection = max(0.0, min(r1, r2) - max(l1, l2)) * max(0.0, min(b1, b2) - max(t1, t2))
    area = max(0.0, r1 - l1) * max(0.0, b1 - t1)
    return intersection / area if area else 0.0


def _observation_id(kind: str, page_id: str, polygon: Polygon, content: Mapping[str, Any]) -> str:
    return f"observation:{kind}:{stable_hash({'page_id': page_id, 'polygon': _polygon_payload(polygon), 'content': dict(content)})}"


def _pixel_polygon(value: Any, width: int, height: int) -> Polygon:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _observation_error("extraction.provider_record_invalid", "$.items.polygon", "polygon must be an array")
    points: list[tuple[float, float]] = []
    for point in value:
        if not isinstance(point, Sequence) or len(point) != 2:
            raise _observation_error("extraction.provider_record_invalid", "$.items.polygon", "point must contain x and y")
        points.append((round(float(point[0]) / width, 6), round(float(point[1]) / height, 6)))
    return _canonical_polygon(points)


def _canonical_polygon(points: Sequence[tuple[float, float]]) -> Polygon:
    normalized = tuple((round(float(x), 6), round(float(y), 6)) for x, y in points)
    if len(normalized) > 1 and normalized[0] == normalized[-1]:
        normalized = normalized[:-1]
    _validate_polygon(normalized, "$.polygon")
    variants = []
    for sequence in (normalized, tuple(reversed(normalized))):
        for index in range(len(sequence)):
            variants.append(sequence[index:] + sequence[:index])
    return min(variants)


def _validate_polygon(polygon: Sequence[tuple[float, float]], path: str) -> None:
    if len(polygon) < 3:
        raise _observation_error("extraction.observation_invalid", path, "polygon needs at least three points")
    if any(not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1 for x, y in polygon):
        raise _observation_error("extraction.geometry_transform_mismatch", path, "polygon coordinates must be finite and normalized")
    area = abs(sum(polygon[index][0] * polygon[(index + 1) % len(polygon)][1] - polygon[(index + 1) % len(polygon)][0] * polygon[index][1] for index in range(len(polygon))) / 2)
    if area <= 1e-12:
        raise _observation_error("extraction.geometry_transform_mismatch", path, "polygon area must be positive")


def _validate_confidence(value: float, path: str) -> None:
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise _observation_error("extraction.observation_invalid", path, "confidence must be in [0,1]")


def _confidence(value: Any) -> float:
    result = round(float(value), 6)
    _validate_confidence(result, "$.confidence")
    return result


def _sort_spatial(items: Sequence[Any]) -> tuple[Any, ...]:
    grouped: dict[tuple[str, int], list[Any]] = {}
    page_items: dict[str, list[Any]] = {}
    for item in items:
        page_items.setdefault(item.page_id, []).append(item)
    for page_id, values in page_items.items():
        single_column = any(
            polygon_bbox(item.polygon)[0] < 0.42
            and polygon_bbox(item.polygon)[2] > 0.52
            for item in values
        )
        for item in values:
            grouped.setdefault(
                (page_id, _spatial_column(item.polygon, single_column=single_column)),
                [],
            ).append(item)
    ordered = []
    for key in sorted(grouped):
        lines: list[list[Any]] = []
        for item in sorted(
            grouped[key],
            key=lambda value: (
                _vertical_center(value.polygon),
                polygon_bbox(value.polygon)[0],
                value.observation_id,
            ),
        ):
            candidate = min(
                (line for line in lines if _same_reading_line(item.polygon, line)),
                key=lambda line: abs(_vertical_center(item.polygon) - _line_center(line)),
                default=None,
            )
            if candidate is None:
                lines.append([item])
            else:
                candidate.append(item)
        for line in sorted(
            lines,
            key=lambda values: min(_vertical_center(item.polygon) for item in values),
        ):
            ordered.extend(
                sorted(
                    line,
                    key=lambda value: (
                        round(polygon_bbox(value.polygon)[0], 6),
                        round(_vertical_center(value.polygon), 6),
                        value.observation_id,
                    ),
                )
            )
    return tuple(ordered)


def _spatial_key(polygon: Polygon) -> tuple[int, float, float, float]:
    left, top, right, bottom = polygon_bbox(polygon)
    width = right - left
    column = 0 if width >= 0.65 else (1 if (left + right) / 2 >= 0.5 else 0)
    return (column, round(top, 6), round(left, 6), round(bottom, 6))


def _spatial_column(polygon: Polygon, *, single_column: bool) -> int:
    if single_column:
        return 0
    left, _, right, _ = polygon_bbox(polygon)
    return 0 if right - left >= 0.65 or (left + right) / 2 < 0.5 else 1


def _vertical_center(polygon: Polygon) -> float:
    _, top, _, bottom = polygon_bbox(polygon)
    return (top + bottom) / 2


def _line_center(line: Sequence[Any]) -> float:
    centers = sorted(_vertical_center(item.polygon) for item in line)
    middle = len(centers) // 2
    return (
        centers[middle]
        if len(centers) % 2
        else (centers[middle - 1] + centers[middle]) / 2
    )


def _same_reading_line(polygon: Polygon, line: Sequence[Any]) -> bool:
    _, top, _, bottom = polygon_bbox(polygon)
    center = (top + bottom) / 2
    item_height = max(1e-9, bottom - top)
    line_heights = [
        max(1e-9, polygon_bbox(item.polygon)[3] - polygon_bbox(item.polygon)[1])
        for item in line
    ]
    ordered_heights = sorted(line_heights)
    height_middle = len(ordered_heights) // 2
    line_height = (
        ordered_heights[height_middle]
        if len(ordered_heights) % 2
        else (ordered_heights[height_middle - 1] + ordered_heights[height_middle]) / 2
    )
    comparable_height = max(item_height, line_height) / min(item_height, line_height) <= 2.0
    return comparable_height and (
        abs(center - _line_center(line)) <= max(item_height, line_height) * 0.75
    )


def _sort_formula_candidates(
    items: Sequence[_FormulaCropCandidate],
) -> tuple[_FormulaCropCandidate, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.page_id,
                *_spatial_key(item.polygon),
                item.source_observation_ids,
                item.source_text_range or (-1, -1),
            ),
        )
    )


def _required_formula_request_id(item: Mapping[str, Any]) -> str:
    value = item.get("formula_request_id")
    if not isinstance(value, str) or re.fullmatch(
        r"formula-request:[a-f0-9]{64}", value
    ) is None:
        raise _observation_error(
            "extraction.provider_record_invalid",
            "$.items.formula_request_id",
            "formula provider item must identify its exact crop request",
        )
    return value


def _best_containing_block(polygon: Polygon, blocks: Sequence[LayoutBlock]) -> str | None:
    candidates = [
        (bbox_overlap_ratio(polygon, block.polygon), block.observation_id)
        for block in blocks
        if block.page_id and block.kind not in {"figure", "watermark"}
    ]
    if not candidates:
        return None
    ratio, block_id = max(candidates)
    return block_id if ratio >= 0.5 else None


def _center(polygon: Polygon) -> tuple[float, float]:
    left, top, right, bottom = polygon_bbox(polygon)
    return ((left + right) / 2, (top + bottom) / 2)


def _point_in_polygon(point: tuple[float, float], polygon: Polygon) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y):
            crossing = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x <= crossing:
                inside = not inside
    return inside


def _union_bbox(polygons: Sequence[Polygon] | Any) -> tuple[float, float, float, float]:
    boxes = [polygon_bbox(item) for item in polygons]
    return (min(item[0] for item in boxes), min(item[1] for item in boxes), max(item[2] for item in boxes), max(item[3] for item in boxes))


def _polygon_payload(polygon: Polygon) -> list[list[float]]:
    return [[x, y] for x, y in polygon]


def _reject_semantic_keys(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        forbidden = _SEMANTIC_KEYS.intersection(str(key) for key in value)
        if forbidden:
            raise _observation_error("extraction.provider_record_invalid", path, f"semantic fields are forbidden: {sorted(forbidden)}")
        for key, item in value.items():
            _reject_semantic_keys(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _reject_semantic_keys(item, f"{path}[{index}]")


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("expected object")
    return value


def _polygon_from_payload(value: Any) -> Polygon:
    return _canonical_polygon(tuple((float(point[0]), float(point[1])) for point in value))


def _spatial_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "observation_id": str(payload["observation_id"]),
        "page_id": str(payload["page_id"]),
        "polygon": _polygon_from_payload(payload["polygon"]),
        "confidence": float(payload["confidence"]),
        "origin": str(payload["origin"]),
        "source_artifact_id": str(payload["source_artifact_id"]),
        "provider_id": str(payload["provider_id"]),
        "reading_order": int(payload["reading_order"]),
    }


def _page_from_payload(payload: Mapping[str, Any]) -> PageObservation:
    return PageObservation(str(payload["page_id"]), int(payload["width"]), int(payload["height"]), 0, str(payload["source_artifact_id"]), tuple(str(item) for item in payload["layout_block_ids"]), tuple(str(item) for item in payload["reading_order"]))


def _layout_from_payload(payload: Mapping[str, Any]) -> LayoutBlock:
    return LayoutBlock(**_spatial_kwargs(payload), kind=str(payload["kind"]), provider_label=str(payload["provider_label"]))


def _text_from_payload(payload: Mapping[str, Any]) -> TextSpanObservation:
    return TextSpanObservation(**_spatial_kwargs(payload), text=str(payload["text"]), block_id=(str(payload["block_id"]) if payload.get("block_id") is not None else None))


def _formula_from_payload(payload: Mapping[str, Any]) -> FormulaObservation:
    return FormulaObservation(
        **_spatial_kwargs(payload),
        latex=(str(payload["latex"]) if payload.get("latex") is not None else None),
        status=str(payload["status"]),
        source_observation_ids=tuple(
            str(item) for item in payload["source_observation_ids"]
        ),
        formula_request_id=str(payload["formula_request_id"]),
        source_text_hint=(
            str(payload["source_text_hint"])
            if payload.get("source_text_hint") is not None
            else None
        ),
        crop_artifact_id=(
            str(payload["crop_artifact_id"])
            if payload.get("crop_artifact_id") is not None
            else None
        ),
    )


def _ink_from_payload(payload: Mapping[str, Any]) -> InkOriginObservation:
    return InkOriginObservation(**_spatial_kwargs(payload), mask_artifact_id=(str(payload["mask_artifact_id"]) if payload.get("mask_artifact_id") is not None else None), overlap_observation_ids=tuple(str(item) for item in payload["overlap_observation_ids"]), signals=_mapping(payload["signals"]))


def _occlusion_from_payload(payload: Mapping[str, Any]) -> OcclusionObservation:
    return OcclusionObservation(**_spatial_kwargs(payload), target_observation_ids=tuple(str(item) for item in payload["target_observation_ids"]), severity=str(payload["severity"]), overlap_ratio=float(payload["overlap_ratio"]))


def _proposal_from_payload(payload: Mapping[str, Any]) -> ProblemRegionProposal:
    return ProblemRegionProposal(str(payload["proposal_id"]), str(payload["question_label"]), tuple(str(item) for item in payload["page_ids"]), tuple(_polygon_from_payload(item) for item in payload["polygons"]), tuple(str(item) for item in payload["included_block_ids"]), float(payload["confidence"]), tuple(str(item) for item in payload["reason_codes"]), bool(payload["requires_confirmation"]))


def _issue_from_payload(payload: Mapping[str, Any]) -> ObservationIssue:
    return ObservationIssue(str(payload["issue_id"]), str(payload["code"]), bool(payload["blocking"]), bool(payload["retryable"]), tuple(str(item) for item in payload["observation_ids"]), _mapping(payload["details"]))


@lru_cache(maxsize=1)
def _observation_schema_validator() -> Draft202012Validator:
    schema = json.loads((_repo_root() / "internal/schemas/source-observation.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@lru_cache(maxsize=1)
def _provider_schema_validator() -> Draft202012Validator:
    schema = json.loads((_repo_root() / "internal/schemas/paddle-provider-record.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _observation_error(code: str, path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(code, path, message)
