"""Deterministic source, selection, and dependency identity for extraction."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from hashlib import sha256
from io import BytesIO
import json
import math
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from PIL import Image, ImageOps, UnidentifiedImageError


SOURCE_NORMALIZATION_PROFILE = "raster-rgba-exif/v1"
EXTRACTION_CONTRACT_VERSION = "problem-extraction/v1"
_ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png"})
_ALLOWED_SELECTION_MODES = frozenset(
    {"authored_gold", "auto_confirmed", "user_confirmed", "user_adjusted"}
)
_JSON_SCALAR = str | int | float | bool | None
FrozenJson = _JSON_SCALAR | tuple["FrozenJson", ...] | Mapping[str, "FrozenJson"]


class ProblemExtractionContextError(ValueError):
    """A typed fail-closed error at an extraction authority boundary."""

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class SourceAssetInput:
    page_id: str
    media_type: str
    content_bytes: bytes
    locator: str | None = None


@dataclass(frozen=True)
class SourcePageFingerprint:
    page_id: str
    media_type: str
    raw_sha256: str
    canonical_sha256: str
    width: int
    height: int
    locator: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "media_type": self.media_type,
            "raw_sha256": self.raw_sha256,
            "canonical_sha256": self.canonical_sha256,
            "width": self.width,
            "height": self.height,
            "locator": self.locator,
        }


@dataclass(frozen=True)
class ProblemSourceFingerprint:
    source_id: str
    source_revision_hash: str
    normalization_profile: str
    pages: tuple[SourcePageFingerprint, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", tuple(self.pages))

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_revision_hash": self.source_revision_hash,
            "normalization_profile": self.normalization_profile,
            "pages": [page.to_payload() for page in self.pages],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ProblemSourceFingerprint:
        try:
            pages = tuple(
                SourcePageFingerprint(
                    page_id=str(item["page_id"]),
                    media_type=str(item["media_type"]),
                    raw_sha256=str(item["raw_sha256"]),
                    canonical_sha256=str(item["canonical_sha256"]),
                    width=int(item["width"]),
                    height=int(item["height"]),
                    locator=(
                        str(item["locator"])
                        if item.get("locator") is not None
                        else None
                    ),
                )
                for item in _mapping_sequence(payload.get("pages"), "$.source.pages")
            )
            result = cls(
                source_id=str(payload["source_id"]),
                source_revision_hash=str(payload["source_revision_hash"]),
                normalization_profile=str(payload["normalization_profile"]),
                pages=pages,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("extraction.source_invalid", "$.source", str(exc)) from exc
        result.validate()
        return result

    def validate(self) -> None:
        if self.normalization_profile != SOURCE_NORMALIZATION_PROFILE:
            raise _error(
                "extraction.source_invalid",
                "$.source.normalization_profile",
                f"unsupported profile {self.normalization_profile!r}",
            )
        _validate_unique_nonempty(
            (page.page_id for page in self.pages),
            code="extraction.source_invalid",
            path="$.source.pages",
            label="page id",
        )
        if not self.pages:
            raise _error(
                "extraction.source_invalid",
                "$.source.pages",
                "at least one page is required",
            )
        for index, page in enumerate(self.pages):
            path = f"$.source.pages[{index}]"
            if page.media_type not in _ALLOWED_MEDIA_TYPES:
                raise _error(
                    "extraction.source_invalid",
                    f"{path}.media_type",
                    page.media_type,
                )
            if page.width <= 0 or page.height <= 0:
                raise _error(
                    "extraction.source_invalid",
                    path,
                    "page dimensions must be positive",
                )
            _validate_sha(page.raw_sha256, f"{path}.raw_sha256")
            _validate_sha(page.canonical_sha256, f"{path}.canonical_sha256")
        expected_source_id = _source_id(self.normalization_profile, self.pages)
        expected_revision = _source_revision_hash(expected_source_id, self.pages)
        if self.source_id != expected_source_id:
            raise _error(
                "extraction.source_fingerprint_mismatch",
                "$.source.source_id",
                f"expected {expected_source_id}, got {self.source_id}",
            )
        if self.source_revision_hash != expected_revision:
            raise _error(
                "extraction.source_fingerprint_mismatch",
                "$.source.source_revision_hash",
                f"expected {expected_revision}, got {self.source_revision_hash}",
            )


class ProblemSourceFingerprintService:
    """Fingerprint ordered, already-paginated raster source assets."""

    def fingerprint(
        self,
        assets: Sequence[SourceAssetInput],
        *,
        normalization_profile: str = SOURCE_NORMALIZATION_PROFILE,
    ) -> ProblemSourceFingerprint:
        if normalization_profile != SOURCE_NORMALIZATION_PROFILE:
            raise _error(
                "extraction.source_invalid",
                "$.normalization_profile",
                f"unsupported profile {normalization_profile!r}",
            )
        _validate_unique_nonempty(
            (asset.page_id for asset in assets),
            code="extraction.source_invalid",
            path="$.pages",
            label="page id",
        )
        if not assets:
            raise _error(
                "extraction.source_invalid",
                "$.pages",
                "at least one page is required",
            )
        pages = tuple(self._page(asset, index) for index, asset in enumerate(assets))
        source_id = _source_id(normalization_profile, pages)
        result = ProblemSourceFingerprint(
            source_id=source_id,
            source_revision_hash=_source_revision_hash(source_id, pages),
            normalization_profile=normalization_profile,
            pages=pages,
        )
        result.validate()
        return result

    @staticmethod
    def _page(asset: SourceAssetInput, index: int) -> SourcePageFingerprint:
        path = f"$.pages[{index}]"
        if not asset.page_id.strip():
            raise _error("extraction.source_invalid", f"{path}.page_id", "empty")
        if asset.media_type not in _ALLOWED_MEDIA_TYPES:
            raise _error(
                "extraction.source_invalid",
                f"{path}.media_type",
                f"unsupported media type {asset.media_type!r}",
            )
        if not isinstance(asset.content_bytes, bytes) or not asset.content_bytes:
            raise _error(
                "extraction.source_invalid",
                f"{path}.content_bytes",
                "source bytes are required",
            )
        try:
            with Image.open(BytesIO(asset.content_bytes)) as image:
                if getattr(image, "n_frames", 1) != 1:
                    raise _error(
                        "extraction.source_invalid",
                        path,
                        "animated or multi-frame images are unsupported",
                    )
                actual_media_type = {
                    "JPEG": "image/jpeg",
                    "PNG": "image/png",
                }.get(image.format)
                if actual_media_type != asset.media_type:
                    raise _error(
                        "extraction.source_invalid",
                        f"{path}.media_type",
                        f"declared {asset.media_type}, decoded {actual_media_type}",
                    )
                normalized = ImageOps.exif_transpose(image).convert("RGBA")
                width, height = normalized.size
                canonical_sha = _sha256_parts(
                    b"raster-rgba\0",
                    str(width).encode("ascii"),
                    b"x",
                    str(height).encode("ascii"),
                    b"\0",
                    normalized.tobytes(),
                )
        except ProblemExtractionContextError:
            raise
        except (OSError, UnidentifiedImageError) as exc:
            raise _error(
                "extraction.source_invalid",
                f"{path}.content_bytes",
                f"image cannot be decoded: {exc}",
            ) from exc
        return SourcePageFingerprint(
            page_id=asset.page_id.strip(),
            media_type=asset.media_type,
            raw_sha256=sha256(asset.content_bytes).hexdigest(),
            canonical_sha256=canonical_sha,
            width=width,
            height=height,
            locator=asset.locator,
        )


@dataclass(frozen=True)
class SelectionRegion:
    region_id: str
    page_id: str
    polygon: tuple[tuple[float, float], ...]
    reason: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "page_id": self.page_id,
            "polygon": [[x, y] for x, y in self.polygon],
            "reason": self.reason,
        }


SelectionMode = Literal[
    "authored_gold", "auto_confirmed", "user_confirmed", "user_adjusted"
]


@dataclass(frozen=True)
class SourceSelection:
    source_id: str
    mode: SelectionMode
    revision: int
    parent_selection_id: str | None
    regions: tuple[SelectionRegion, ...]
    included_block_ids: tuple[str, ...]
    selection_id: str
    selection_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "regions", tuple(self.regions))
        object.__setattr__(
            self,
            "included_block_ids",
            tuple(self.included_block_ids),
        )

    @classmethod
    def create(
        cls,
        source: ProblemSourceFingerprint,
        *,
        mode: SelectionMode,
        revision: int,
        regions: Sequence[SelectionRegion],
        included_block_ids: Sequence[str] = (),
        parent_selection_id: str | None = None,
    ) -> SourceSelection:
        normalized_regions = _normalize_regions(source, regions)
        normalized_blocks = tuple(sorted(set(included_block_ids)))
        if any(not item.strip() for item in normalized_blocks):
            raise _error(
                "extraction.selection_invalid",
                "$.selection.included_block_ids",
                "block ids must be non-empty",
            )
        identity_payload = _selection_identity_payload(
            source.source_id,
            normalized_regions,
            normalized_blocks,
        )
        selection_hash = stable_hash(identity_payload)
        result = cls(
            source_id=source.source_id,
            mode=mode,
            revision=revision,
            parent_selection_id=parent_selection_id,
            regions=normalized_regions,
            included_block_ids=normalized_blocks,
            selection_id=f"selection:{selection_hash}",
            selection_hash=selection_hash,
        )
        result.validate(source)
        return result

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        source: ProblemSourceFingerprint,
    ) -> SourceSelection:
        try:
            regions = tuple(
                SelectionRegion(
                    region_id=str(item["region_id"]),
                    page_id=str(item["page_id"]),
                    polygon=tuple(
                        (float(point[0]), float(point[1]))
                        for point in item["polygon"]
                    ),
                    reason=str(item.get("reason", "")),
                )
                for item in _mapping_sequence(
                    payload.get("regions"), "$.selection.regions"
                )
            )
            result = cls(
                source_id=str(payload["source_id"]),
                mode=str(payload["mode"]),  # type: ignore[arg-type]
                revision=int(payload["revision"]),
                parent_selection_id=(
                    str(payload["parent_selection_id"])
                    if payload.get("parent_selection_id") is not None
                    else None
                ),
                regions=regions,
                included_block_ids=tuple(
                    str(item) for item in payload.get("included_block_ids", ())
                ),
                selection_id=str(payload["selection_id"]),
                selection_hash=str(payload["selection_hash"]),
            )
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise _error(
                "extraction.selection_invalid", "$.selection", str(exc)
            ) from exc
        result.validate(source)
        return result

    def validate(self, source: ProblemSourceFingerprint) -> None:
        if self.source_id != source.source_id:
            raise _error(
                "extraction.selection_source_mismatch",
                "$.selection.source_id",
                f"expected {source.source_id}, got {self.source_id}",
            )
        if self.mode not in _ALLOWED_SELECTION_MODES:
            raise _error(
                "extraction.selection_invalid",
                "$.selection.mode",
                str(self.mode),
            )
        if self.revision < 0:
            raise _error(
                "extraction.selection_invalid",
                "$.selection.revision",
                "revision must be non-negative",
            )
        normalized_regions = _normalize_regions(source, self.regions)
        normalized_blocks = tuple(sorted(set(self.included_block_ids)))
        if self.regions != normalized_regions or self.included_block_ids != normalized_blocks:
            raise _error(
                "extraction.selection_invalid",
                "$.selection",
                "selection payload is not canonically ordered",
            )
        expected_hash = stable_hash(
            _selection_identity_payload(
                self.source_id,
                self.regions,
                self.included_block_ids,
            )
        )
        if self.selection_hash != expected_hash or self.selection_id != (
            f"selection:{expected_hash}"
        ):
            raise _error(
                "extraction.selection_invalid",
                "$.selection.selection_hash",
                "selection fingerprint does not match its regions",
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "mode": self.mode,
            "revision": self.revision,
            "parent_selection_id": self.parent_selection_id,
            "regions": [region.to_payload() for region in self.regions],
            "included_block_ids": list(self.included_block_ids),
            "selection_id": self.selection_id,
            "selection_hash": self.selection_hash,
        }


@dataclass(frozen=True)
class ExtractionDependencyManifest:
    source_id: str
    source_revision_hash: str
    selection_id: str
    extraction_contract_version: str
    normalization_profile_version: str
    semantic_config: Mapping[str, FrozenJson]
    semantic_config_hash: str
    upstream_context_ids: tuple[str, ...]
    dependency_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_config", freeze_json(self.semantic_config))
        object.__setattr__(
            self,
            "upstream_context_ids",
            tuple(self.upstream_context_ids),
        )

    @classmethod
    def create(
        cls,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
        *,
        extraction_contract_version: str = EXTRACTION_CONTRACT_VERSION,
        semantic_config: Mapping[str, Any] | None = None,
        upstream_context_ids: Sequence[str] = (),
    ) -> ExtractionDependencyManifest:
        selection.validate(source)
        if extraction_contract_version != EXTRACTION_CONTRACT_VERSION:
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.extraction_contract_version",
                f"unsupported contract {extraction_contract_version!r}",
            )
        frozen_config = freeze_json(semantic_config or {})
        if not isinstance(frozen_config, Mapping):
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.semantic_config",
                "semantic config must be an object",
            )
        upstream = tuple(sorted(set(upstream_context_ids)))
        if any(not item for item in upstream):
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.upstream_context_ids",
                "context ids must be non-empty",
            )
        config_hash = stable_hash(frozen_config)
        identity = _dependency_identity_payload(
            source=source,
            selection=selection,
            contract=extraction_contract_version,
            semantic_config_hash=config_hash,
            upstream_context_ids=upstream,
        )
        return cls(
            source_id=source.source_id,
            source_revision_hash=source.source_revision_hash,
            selection_id=selection.selection_id,
            extraction_contract_version=extraction_contract_version,
            normalization_profile_version=source.normalization_profile,
            semantic_config=frozen_config,
            semantic_config_hash=config_hash,
            upstream_context_ids=upstream,
            dependency_hash=stable_hash(identity),
        )

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
    ) -> ExtractionDependencyManifest:
        try:
            result = cls(
                source_id=str(payload["source_id"]),
                source_revision_hash=str(payload["source_revision_hash"]),
                selection_id=str(payload["selection_id"]),
                extraction_contract_version=str(
                    payload["extraction_contract_version"]
                ),
                normalization_profile_version=str(
                    payload["normalization_profile_version"]
                ),
                semantic_config=payload.get("semantic_config", {}),
                semantic_config_hash=str(payload["semantic_config_hash"]),
                upstream_context_ids=tuple(
                    str(item) for item in payload.get("upstream_context_ids", ())
                ),
                dependency_hash=str(payload["dependency_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error(
                "extraction.dependency_hash_mismatch", "$.dependency", str(exc)
            ) from exc
        result.validate(source, selection)
        return result

    def validate(
        self,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
    ) -> None:
        if self.extraction_contract_version != EXTRACTION_CONTRACT_VERSION:
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.extraction_contract_version",
                f"unsupported contract {self.extraction_contract_version!r}",
            )
        expected_pairs = {
            "source_id": source.source_id,
            "source_revision_hash": source.source_revision_hash,
            "selection_id": selection.selection_id,
            "normalization_profile_version": source.normalization_profile,
        }
        for name, expected in expected_pairs.items():
            if getattr(self, name) != expected:
                raise _error(
                    "extraction.dependency_hash_mismatch",
                    f"$.dependency.{name}",
                    f"expected {expected}, got {getattr(self, name)}",
                )
        expected_config_hash = stable_hash(self.semantic_config)
        if self.semantic_config_hash != expected_config_hash:
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.semantic_config_hash",
                "semantic config hash does not match config",
            )
        if self.upstream_context_ids != tuple(
            sorted(set(self.upstream_context_ids))
        ) or any(not item for item in self.upstream_context_ids):
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.upstream_context_ids",
                "upstream Context ids must be non-empty, unique, and sorted",
            )
        expected_hash = stable_hash(
            _dependency_identity_payload(
                source=source,
                selection=selection,
                contract=self.extraction_contract_version,
                semantic_config_hash=self.semantic_config_hash,
                upstream_context_ids=self.upstream_context_ids,
            )
        )
        if self.dependency_hash != expected_hash:
            raise _error(
                "extraction.dependency_hash_mismatch",
                "$.dependency.dependency_hash",
                f"expected {expected_hash}, got {self.dependency_hash}",
            )

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_revision_hash": self.source_revision_hash,
            "selection_id": self.selection_id,
            "extraction_contract_version": self.extraction_contract_version,
            "normalization_profile_version": self.normalization_profile_version,
            "semantic_config": thaw_json(self.semantic_config),
            "semantic_config_hash": self.semantic_config_hash,
            "upstream_context_ids": list(self.upstream_context_ids),
            "dependency_hash": self.dependency_hash,
        }


def stable_hash(value: Any) -> str:
    return sha256(
        json.dumps(
            thaw_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def freeze_json(value: Any) -> FrozenJson:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): freeze_json(child)
                for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise _error(
            "extraction.context_hash_mismatch",
            "$",
            "non-finite JSON numbers are unsupported",
        )
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise _error(
        "extraction.context_hash_mismatch",
        "$",
        f"unsupported JSON value {type(value).__name__}",
    )


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _source_id(
    profile: str,
    pages: Sequence[SourcePageFingerprint],
) -> str:
    digest = stable_hash(
        {
            "normalization_profile": profile,
            "pages": [
                {
                    "canonical_sha256": page.canonical_sha256,
                    "width": page.width,
                    "height": page.height,
                }
                for page in pages
            ],
        }
    )
    return f"source:{digest}"


def _source_revision_hash(
    source_id: str,
    pages: Sequence[SourcePageFingerprint],
) -> str:
    return stable_hash(
        {
            "source_id": source_id,
            "raw_pages": [
                {
                    "page_id": page.page_id,
                    "raw_sha256": page.raw_sha256,
                }
                for page in pages
            ],
        }
    )


def _normalize_regions(
    source: ProblemSourceFingerprint,
    regions: Sequence[SelectionRegion],
) -> tuple[SelectionRegion, ...]:
    page_ids = {page.page_id for page in source.pages}
    seen: set[str] = set()
    normalized: list[SelectionRegion] = []
    for region in regions:
        if not region.region_id.strip() or region.region_id in seen:
            raise _error(
                "extraction.selection_invalid",
                "$.selection.regions",
                f"duplicate or empty region id {region.region_id!r}",
            )
        seen.add(region.region_id)
        if region.page_id not in page_ids:
            raise _error(
                "extraction.selection_invalid",
                f"$.selection.regions.{region.region_id}.page_id",
                f"unknown page {region.page_id!r}",
            )
        polygon = tuple(
            (_quantized_coordinate(x), _quantized_coordinate(y))
            for x, y in region.polygon
        )
        if len(polygon) < 3 or abs(_polygon_area(polygon)) <= 1e-12:
            raise _error(
                "extraction.selection_invalid",
                f"$.selection.regions.{region.region_id}.polygon",
                "polygon must have non-zero area and at least three points",
            )
        normalized.append(
            SelectionRegion(
                region_id=region.region_id.strip(),
                page_id=region.page_id,
                polygon=polygon,
                reason=region.reason,
            )
        )
    if not normalized:
        raise _error(
            "extraction.selection_invalid",
            "$.selection.regions",
            "at least one region is required",
        )
    return tuple(sorted(normalized, key=lambda item: item.region_id))


def _selection_identity_payload(
    source_id: str,
    regions: Sequence[SelectionRegion],
    included_block_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "regions": [
            {
                "region_id": region.region_id,
                "page_id": region.page_id,
                "polygon": [[x, y] for x, y in region.polygon],
            }
            for region in regions
        ],
        "included_block_ids": list(included_block_ids),
    }


def _dependency_identity_payload(
    *,
    source: ProblemSourceFingerprint,
    selection: SourceSelection,
    contract: str,
    semantic_config_hash: str,
    upstream_context_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "source_revision_hash": source.source_revision_hash,
        "selection_id": selection.selection_id,
        "extraction_contract_version": contract,
        "normalization_profile_version": source.normalization_profile,
        "semantic_config_hash": semantic_config_hash,
        "upstream_context_ids": list(upstream_context_ids),
    }


def _quantized_coordinate(value: float) -> float:
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _error(
            "extraction.selection_invalid",
            "$.selection.regions.polygon",
            f"invalid coordinate {value!r}",
        ) from exc
    if not decimal_value.is_finite() or not 0 <= decimal_value <= 1:
        raise _error(
            "extraction.selection_invalid",
            "$.selection.regions.polygon",
            f"coordinate out of range: {value!r}",
        )
    return float(decimal_value.quantize(Decimal("0.000001"), ROUND_HALF_EVEN))


def _polygon_area(polygon: Sequence[tuple[float, float]]) -> float:
    return sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1])
    ) / 2


def _sha256_parts(*parts: bytes) -> str:
    digest = sha256()
    for part in parts:
        digest.update(part)
    return digest.hexdigest()


def _validate_sha(value: str, path: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise _error("extraction.source_invalid", path, "invalid SHA-256")


def _validate_unique_nonempty(
    values: Sequence[str] | Any,
    *,
    code: str,
    path: str,
    label: str,
) -> None:
    materialized = tuple(values)
    if any(not value.strip() for value in materialized):
        raise _error(code, path, f"{label} must be non-empty")
    if len(set(materialized)) != len(materialized):
        raise _error(code, path, f"duplicate {label}")


def _mapping_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _error("extraction.source_invalid", path, "expected an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise _error("extraction.source_invalid", path, "array items must be objects")
    return tuple(value)  # type: ignore[return-value]


def _error(code: str, path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(code, path, message)
