"""Conservative local ink-origin and printed-overlap analysis."""

from __future__ import annotations

from dataclasses import dataclass, replace
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageOps

from shuxueshuo_server.solver.extraction.observations import (
    InkOriginObservation,
    ObservationIssue,
    OcclusionObservation,
    Polygon,
    ProviderManifest,
    TextSpanObservation,
    bbox_polygon,
    make_observation_issue,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash

_MINIMUM_SEED_PIXELS = 20
_MINIMUM_SEED_RATIO = 0.06
_MINIMUM_NEUTRAL_SEED_PIXELS = 16
_MINIMUM_NEUTRAL_SEED_RATIO = 0.08


@dataclass(frozen=True)
class InkAnalysisResult:
    provider: ProviderManifest
    text_spans: tuple[TextSpanObservation, ...]
    ink_origins: tuple[InkOriginObservation, ...]
    occlusions: tuple[OcclusionObservation, ...]
    issues: tuple[ObservationIssue, ...]
    mask_png: bytes

    def bind_mask_artifact(self, artifact_id: str) -> InkAnalysisResult:
        return replace(
            self,
            ink_origins=tuple(
                replace(item, mask_artifact_id=artifact_id)
                for item in self.ink_origins
            ),
        )


class ConservativeInkOriginAnalyzer:
    """Find conservative chromatic and neutral-stroke ink candidates."""

    def __init__(self, *, max_dimension: int = 960) -> None:
        self.max_dimension = max_dimension
        self.provider = ProviderManifest.create(
            provider="local_cv",
            component="ink_origin",
            model_name="conservative_local_ink",
            model_revision="v2",
            software_versions={"Pillow": Image.__version__},
            config={
                "max_dimension": max_dimension,
                "candidate_minimum_chroma": 48,
                "seed_minimum_chroma": 70,
                "seed_minimum_relative_saturation": 0.45,
                "minimum_seed_pixels": _MINIMUM_SEED_PIXELS,
                "minimum_seed_ratio": _MINIMUM_SEED_RATIO,
                "neutral_dark_maximum": 150,
                "neutral_maximum_chroma": 35,
                "neutral_minimum_seed_pixels": _MINIMUM_NEUTRAL_SEED_PIXELS,
                "neutral_minimum_seed_ratio": _MINIMUM_NEUTRAL_SEED_RATIO,
                "neutral_authority": "unknown_or_mixed_only",
                "min_tile_pixels": 4,
            },
        )

    def analyze(
        self,
        *,
        page_id: str,
        image_bytes: bytes,
        source_artifact_id: str,
        text_spans: Sequence[TextSpanObservation],
    ) -> InkAnalysisResult:
        source = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGB")
        scale = min(1.0, self.max_dimension / max(source.size))
        size = (
            max(1, round(source.width * scale)),
            max(1, round(source.height * scale)),
        )
        image = source.resize(size, Image.Resampling.BILINEAR)
        mask = Image.new("L", image.size, 0)
        mask_pixels = mask.load()
        image_pixels = image.load()
        printed_region = Image.new("L", image.size, 0)
        printed_draw = ImageDraw.Draw(printed_region)
        for span in text_spans:
            if span.page_id != page_id:
                continue
            printed_draw.polygon(
                [
                    (round(x * image.width), round(y * image.height))
                    for x, y in span.polygon
                ],
                fill=255,
            )
        printed_pixels = printed_region.load()
        tile_size = max(8, min(image.size) // 64)
        occupied: dict[tuple[int, int], int] = {}
        seeded: dict[tuple[int, int], int] = {}
        chromatic_by_tile: dict[tuple[int, int], list[tuple[int, int]]] = {}
        neutral_by_tile: dict[tuple[int, int], list[tuple[int, int]]] = {}
        neutral_seeded: dict[tuple[int, int], int] = {}
        for y in range(image.height):
            for x in range(image.width):
                red, green, blue = image_pixels[x, y]
                maximum = max(red, green, blue)
                minimum = min(red, green, blue)
                chroma = maximum - minimum
                if chroma >= 48 and 30 <= maximum <= 248:
                    tile = (x // tile_size, y // tile_size)
                    occupied[tile] = occupied.get(tile, 0) + 1
                    chromatic_by_tile.setdefault(tile, []).append((x, y))
                    if (
                        chroma >= 70
                        and maximum <= 235
                        and chroma / maximum >= 0.45
                    ):
                        seeded[tile] = seeded.get(tile, 0) + 1
                if maximum <= 150 and chroma < 35:
                    tile = (x // tile_size, y // tile_size)
                    neutral_by_tile.setdefault(tile, []).append((x, y))
                    if printed_pixels[x, y] == 0:
                        neutral_seeded[tile] = neutral_seeded.get(tile, 0) + 1

        active = {
            tile
            for tile, count in occupied.items()
            if count >= max(4, int(tile_size * tile_size * 0.008))
        }
        chromatic_components = tuple(
            component
            for component in _connected_tiles(active)
            if _component_has_chromatic_seed(component, occupied, seeded)
        )
        neutral_active = {
            tile
            for tile, pixels in neutral_by_tile.items()
            if len(pixels) >= max(4, int(tile_size * tile_size * 0.035))
        }
        neutral_components = tuple(
            component
            for component in _connected_tiles(neutral_active)
            if _component_has_neutral_seed(
                component,
                neutral_by_tile,
                neutral_seeded,
            )
            and _component_is_neutral_stroke(
                component,
                neutral_by_tile,
                tile_size,
            )
            and _component_crosses_printed_span(
                component,
                neutral_by_tile,
                tile_size,
                image,
                text_spans,
                page_id,
            )
        )
        component_entries = tuple(
            (component, chromatic_by_tile, "chromatic")
            for component in chromatic_components
        ) + tuple(
            (component, neutral_by_tile, "neutral")
            for component in neutral_components
        )
        candidate_by_tile: dict[tuple[int, int], list[tuple[int, int]]] = {}
        active = set()
        for component, pixels_by_tile, _ in component_entries:
            active.update(component)
            for tile in component:
                candidate_by_tile.setdefault(tile, []).extend(
                    pixels_by_tile.get(tile, ())
                )
        for tile in active:
            for x, y in candidate_by_tile.get(tile, ()):
                mask_pixels[x, y] = 255
        span_origins = {}
        for span in text_spans:
            candidate_pixels, neutral_pixels = _span_ink_profile(
                span.polygon,
                active,
                candidate_by_tile,
                tile_size,
                image,
            )
            overlap_ratio = candidate_pixels / max(
                1,
                candidate_pixels + neutral_pixels,
            )
            if span.origin == "printed":
                span_origins[span.observation_id] = (
                    "mixed"
                    if candidate_pixels >= 4 and overlap_ratio >= 0.08
                    else "printed"
                )
            elif candidate_pixels >= 12 and candidate_pixels > neutral_pixels:
                span_origins[span.observation_id] = "handwritten"
            elif candidate_pixels >= 4 and overlap_ratio >= 0.08:
                span_origins[span.observation_id] = "mixed"
            else:
                span_origins[span.observation_id] = span.origin
        ink_items: list[InkOriginObservation] = []
        occlusions: list[OcclusionObservation] = []
        issues: list[ObservationIssue] = []
        updated_spans = {item.observation_id: item for item in text_spans}

        for component, pixels_by_tile, detection_kind in component_entries:
            pixel_count = sum(len(pixels_by_tile.get(tile, ())) for tile in component)
            if pixel_count < 12:
                continue
            left = min(tile[0] for tile in component) * tile_size / image.width
            top = min(tile[1] for tile in component) * tile_size / image.height
            right = min(
                1.0,
                (max(tile[0] for tile in component) + 1) * tile_size / image.width,
            )
            bottom = min(
                1.0,
                (max(tile[1] for tile in component) + 1) * tile_size / image.height,
            )
            polygon = bbox_polygon((left, top, right, bottom))
            overlap_profiles = {
                span.observation_id: _span_ink_profile(
                    span.polygon,
                    component,
                    pixels_by_tile,
                    tile_size,
                    image,
                )
                for span in text_spans
                if span.page_id == page_id
            }
            overlaps = tuple(
                sorted(
                    span_id
                    for span_id, (candidate_pixels, _) in overlap_profiles.items()
                    if candidate_pixels > 0
                )
            )
            density = min(1.0, pixel_count / max(1, len(component) * tile_size * tile_size))
            confidence = round(
                min(
                    0.99,
                    (0.68 if detection_kind == "chromatic" else 0.55) + density,
                ),
                6,
            )
            has_printed_pixels = any(
                span_origins[span_id] == "mixed"
                for span_id in overlaps
            )
            origin = (
                "mixed"
                if has_printed_pixels
                else "handwritten"
                if detection_kind == "chromatic" and confidence >= 0.72
                else "unknown"
            )
            authority = {
                "page_id": page_id,
                "polygon": [[x, y] for x, y in polygon],
                "origin": origin,
                "overlaps": overlaps,
                "provider": self.provider.provider_id,
                "detection_kind": detection_kind,
            }
            ink_id = f"observation:ink_origin:{stable_hash(authority)}"
            ink_items.append(
                InkOriginObservation(
                    observation_id=ink_id,
                    page_id=page_id,
                    polygon=polygon,
                    confidence=confidence,
                    origin=origin,
                    source_artifact_id=source_artifact_id,
                    provider_id=self.provider.provider_id,
                    reading_order=0,
                    mask_artifact_id=None,
                    overlap_observation_ids=overlaps,
                    signals={
                        "detection_kind": detection_kind,
                        "chromatic_pixel_count": (
                            pixel_count if detection_kind == "chromatic" else 0
                        ),
                        "neutral_pixel_count": (
                            pixel_count if detection_kind == "neutral" else 0
                        ),
                        "tile_count": len(component),
                        "density": round(density, 6),
                    },
                )
            )
            for span_id in overlaps:
                span = updated_spans[span_id]
                candidate_pixels, neutral_pixels = overlap_profiles[span_id]
                ratio = round(
                    candidate_pixels / max(1, candidate_pixels + neutral_pixels),
                    6,
                )
                span_origin = span_origins[span_id]
                severity = (
                    "unrecoverable"
                    if ratio >= 0.25
                    else "ambiguous"
                    if ratio >= 0.08
                    else "recoverable"
                )
                updated_spans[span_id] = replace(span, origin=span_origin)
                if span_origin != "mixed":
                    continue
                local_polygon = _span_component_polygon(
                    span.polygon,
                    component,
                    pixels_by_tile,
                    tile_size,
                    image,
                )
                if local_polygon is None:
                    continue
                occlusion_authority = {
                    "ink": ink_id,
                    "target": span_id,
                    "severity": severity,
                    "ratio": ratio,
                }
                occlusion_id = f"observation:occlusion:{stable_hash(occlusion_authority)}"
                occlusions.append(
                    OcclusionObservation(
                        observation_id=occlusion_id,
                        page_id=page_id,
                        polygon=local_polygon,
                        confidence=confidence,
                        origin="mixed",
                        source_artifact_id=source_artifact_id,
                        provider_id=self.provider.provider_id,
                        reading_order=span.reading_order,
                        target_observation_ids=(span_id,),
                        severity=severity,
                        overlap_ratio=ratio,
                    )
                )
                code = (
                    "extraction.printed_content_unrecoverable"
                    if severity == "unrecoverable"
                    else "extraction.source_occluded"
                )
                issues.append(
                    make_observation_issue(
                        code,
                        blocking=severity != "recoverable",
                        retryable=False,
                        observation_ids=(span_id, ink_id, occlusion_id),
                        details={"severity": severity, "overlap_ratio": ratio},
                    )
                )

        buffer = BytesIO()
        mask.save(buffer, format="PNG", optimize=False)
        ordered_ink = tuple(
            replace(item, reading_order=index)
            for index, item in enumerate(
                sorted(
                    ink_items,
                    key=lambda item: (item.page_id, item.polygon, item.observation_id),
                )
            )
        )
        return InkAnalysisResult(
            provider=self.provider,
            text_spans=tuple(
                sorted(
                    updated_spans.values(),
                    key=lambda item: (item.page_id, item.reading_order, item.observation_id),
                )
            ),
            ink_origins=ordered_ink,
            occlusions=tuple(
                sorted(
                    occlusions,
                    key=lambda item: (item.page_id, item.reading_order, item.observation_id),
                )
            ),
            issues=tuple(sorted(issues, key=lambda item: item.issue_id)),
            mask_png=buffer.getvalue(),
        )


def _connected_tiles(active: set[tuple[int, int]]) -> tuple[set[tuple[int, int]], ...]:
    remaining = set(active)
    components = []
    while remaining:
        root = remaining.pop()
        component = {root}
        frontier = [root]
        while frontier:
            x, y = frontier.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (x + dx, y + dy)
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        component.add(neighbor)
                        frontier.append(neighbor)
        components.append(component)
    return tuple(components)


def _component_has_chromatic_seed(
    component: set[tuple[int, int]],
    occupied: dict[tuple[int, int], int],
    seeded: dict[tuple[int, int], int],
) -> bool:
    candidate_pixels = sum(occupied.get(tile, 0) for tile in component)
    seed_pixels = sum(seeded.get(tile, 0) for tile in component)
    return (
        seed_pixels >= _MINIMUM_SEED_PIXELS
        and seed_pixels / max(1, candidate_pixels) >= _MINIMUM_SEED_RATIO
    )


def _component_has_neutral_seed(
    component: set[tuple[int, int]],
    pixels_by_tile: dict[tuple[int, int], list[tuple[int, int]]],
    seeded: dict[tuple[int, int], int],
) -> bool:
    candidate_pixels = sum(len(pixels_by_tile.get(tile, ())) for tile in component)
    seed_pixels = sum(seeded.get(tile, 0) for tile in component)
    return (
        seed_pixels >= _MINIMUM_NEUTRAL_SEED_PIXELS
        and seed_pixels / max(1, candidate_pixels) >= _MINIMUM_NEUTRAL_SEED_RATIO
    )


def _component_is_neutral_stroke(
    component: set[tuple[int, int]],
    pixels_by_tile: dict[tuple[int, int], list[tuple[int, int]]],
    tile_size: int,
) -> bool:
    if not component:
        return False
    pixel_count = sum(len(pixels_by_tile.get(tile, ())) for tile in component)
    width = max(tile[0] for tile in component) - min(tile[0] for tile in component) + 1
    height = max(tile[1] for tile in component) - min(tile[1] for tile in component) + 1
    density = pixel_count / max(1, len(component) * tile_size * tile_size)
    return pixel_count >= 20 and max(width, height) >= 3 and density <= 0.55


def _component_crosses_printed_span(
    component: set[tuple[int, int]],
    pixels_by_tile: dict[tuple[int, int], list[tuple[int, int]]],
    tile_size: int,
    image: Image.Image,
    text_spans: Sequence[TextSpanObservation],
    page_id: str,
) -> bool:
    return any(
        _span_ink_profile(
            span.polygon,
            component,
            pixels_by_tile,
            tile_size,
            image,
        )[0]
        >= 8
        for span in text_spans
        if span.page_id == page_id and span.origin == "printed"
    )


def _span_ink_profile(
    polygon: Polygon,
    component: set[tuple[int, int]],
    chromatic_by_tile: dict[tuple[int, int], list[tuple[int, int]]],
    tile_size: int,
    image: Image.Image,
) -> tuple[int, int]:
    left, top, right, bottom = _pixel_bbox(polygon, image.size)
    chromatic_pixels = sum(
        sum(left <= x < right and top <= y < bottom for x, y in chromatic_by_tile.get(tile, ()))
        for tile in component
        if _tile_intersects_bbox(tile, tile_size, (left, top, right, bottom))
    )
    neutral_pixels = 0
    pixels = image.load()
    for y in range(top, bottom):
        for x in range(left, right):
            red, green, blue = pixels[x, y]
            if max(red, green, blue) <= 150 and max(red, green, blue) - min(red, green, blue) < 35:
                neutral_pixels += 1
    return chromatic_pixels, neutral_pixels


def _span_component_polygon(
    polygon: Polygon,
    component: set[tuple[int, int]],
    pixels_by_tile: dict[tuple[int, int], list[tuple[int, int]]],
    tile_size: int,
    image: Image.Image,
) -> Polygon | None:
    left, top, right, bottom = _pixel_bbox(polygon, image.size)
    pixels = [
        (x, y)
        for tile in component
        if _tile_intersects_bbox(tile, tile_size, (left, top, right, bottom))
        for x, y in pixels_by_tile.get(tile, ())
        if left <= x < right and top <= y < bottom
    ]
    if not pixels:
        return None
    local_left = min(x for x, _ in pixels) / image.width
    local_top = min(y for _, y in pixels) / image.height
    local_right = (max(x for x, _ in pixels) + 1) / image.width
    local_bottom = (max(y for _, y in pixels) + 1) / image.height
    return bbox_polygon((local_left, local_top, local_right, local_bottom))


def _pixel_bbox(
    polygon: Polygon,
    size: tuple[int, int],
) -> tuple[int, int, int, int]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    left = max(0, int(min(xs) * size[0]))
    top = max(0, int(min(ys) * size[1]))
    right = min(size[0], max(left + 1, int(max(xs) * size[0] + 0.999)))
    bottom = min(size[1], max(top + 1, int(max(ys) * size[1] + 0.999)))
    return left, top, right, bottom


def _tile_intersects_bbox(
    tile: tuple[int, int],
    tile_size: int,
    bbox: tuple[int, int, int, int],
) -> bool:
    left, top, right, bottom = bbox
    tile_left = tile[0] * tile_size
    tile_top = tile[1] * tile_size
    return (
        min(tile_left + tile_size, right) > max(tile_left, left)
        and min(tile_top + tile_size, bottom) > max(tile_top, top)
    )
