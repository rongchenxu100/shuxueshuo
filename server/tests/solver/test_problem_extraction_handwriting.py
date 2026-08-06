from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw

from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.observations import (
    PaddleObservationAdapter,
    polygon_bbox,
    select_formula_crop_requests,
)
from _problem_extraction_f2_support import assemble_fixture, make_fixture


def test_clean_printed_page_has_no_handwriting_observation(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path, colored_ink=False)
    assert result.observation.ink_origins == ()
    assert all(item.origin in {"printed", "unknown"} for item in result.observation.text_spans)


def test_muted_scan_color_fringe_is_not_handwriting() -> None:
    fixture = make_fixture()
    image = Image.new("RGB", (400, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 318, 222, 352), outline=(180, 140, 110), width=3)
    draw.text((20, 320), "25. y=x^2+1", fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    spans = PaddleObservationAdapter().text(
        fixture.text_record,
        source_artifact_id="artifact:page",
    )
    result = ConservativeInkOriginAnalyzer().analyze(
        page_id="page_1",
        image_bytes=buffer.getvalue(),
        source_artifact_id="artifact:page",
        text_spans=spans,
    )
    assert result.ink_origins == ()
    assert result.occlusions == ()


def test_colored_student_ink_is_never_promoted_to_printed(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path, colored_ink=True)
    assert result.observation.ink_origins
    assert all(item.origin in {"handwritten", "mixed", "unknown"} for item in result.observation.ink_origins)
    assert any(item.origin == "handwritten" for item in result.observation.ink_origins)


def test_neutral_student_stroke_crossing_printed_math_becomes_mixed() -> None:
    fixture = make_fixture()
    image = Image.open(BytesIO(fixture.page_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.line((5, 308, 95, 365), fill=(45, 45, 45), width=4)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    adapter = PaddleObservationAdapter()
    layout = adapter.layout(
        fixture.layout_record,
        source_artifact_id="artifact:page",
    )
    spans = adapter.text(
        fixture.text_record,
        source_artifact_id="artifact:page",
        layout_blocks=layout,
    )

    result = ConservativeInkOriginAnalyzer().analyze(
        page_id="page_1",
        image_bytes=buffer.getvalue(),
        source_artifact_id="artifact:page",
        text_spans=spans,
    )

    assert any(
        item.signals["detection_kind"] == "neutral"
        and item.origin in {"mixed", "unknown"}
        for item in result.ink_origins
    )
    assert any(
        "x^2" in item.text and item.origin == "mixed"
        for item in result.text_spans
    )
    requests = select_formula_crop_requests(
        layout,
        result.text_spans,
        ink_origins=result.ink_origins,
    )
    math_span_ids = {
        item.observation_id for item in result.text_spans if "x^2" in item.text
    }
    assert not any(
        math_span_ids.intersection(item.source_observation_ids)
        for item in requests
    )


def test_overlap_with_printed_text_becomes_mixed_and_occlusion(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path, colored_ink=True)
    assert any(item.origin == "mixed" for item in result.observation.ink_origins)
    assert result.observation.occlusions
    assert any(item.origin == "mixed" for item in result.observation.text_spans)
    assert {
        "extraction.source_occluded",
        "extraction.printed_content_unrecoverable",
    } & {item.code for item in result.observation.issues}


def test_recoverable_colored_contact_does_not_downgrade_printed_span() -> None:
    fixture = make_fixture()
    image = Image.open(BytesIO(fixture.page_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.line((218, 349, 365, 520), fill=(210, 25, 40), width=2)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    adapter = PaddleObservationAdapter()
    layout = adapter.layout(
        fixture.layout_record,
        source_artifact_id="artifact:page",
    )
    spans = adapter.text(
        fixture.text_record,
        source_artifact_id="artifact:page",
        layout_blocks=layout,
    )
    math_span = next(item for item in spans if "x^2" in item.text)

    result = ConservativeInkOriginAnalyzer().analyze(
        page_id="page_1",
        image_bytes=buffer.getvalue(),
        source_artifact_id="artifact:page",
        text_spans=spans,
    )

    updated = next(
        item for item in result.text_spans if item.observation_id == math_span.observation_id
    )
    assert result.ink_origins
    assert updated.origin == "printed"
    assert not any(
        math_span.observation_id in item.target_observation_ids
        for item in result.occlusions
    )


def test_occlusion_polygon_is_tight_to_its_target_span() -> None:
    fixture = make_fixture()
    image = Image.open(BytesIO(fixture.page_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.line((30, 325, 370, 535), fill=(210, 25, 40), width=5)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    adapter = PaddleObservationAdapter()
    layout = adapter.layout(
        fixture.layout_record,
        source_artifact_id="artifact:page",
    )
    spans = adapter.text(
        fixture.text_record,
        source_artifact_id="artifact:page",
        layout_blocks=layout,
    )
    math_span = next(item for item in spans if "x^2" in item.text)

    result = ConservativeInkOriginAnalyzer().analyze(
        page_id="page_1",
        image_bytes=buffer.getvalue(),
        source_artifact_id="artifact:page",
        text_spans=spans,
    )

    occlusion = next(
        item
        for item in result.occlusions
        if math_span.observation_id in item.target_observation_ids
    )
    left, top, right, bottom = polygon_bbox(occlusion.polygon)
    span_left, span_top, span_right, span_bottom = polygon_bbox(math_span.polygon)
    assert span_left <= left < right <= span_right
    assert span_top <= top < bottom <= span_bottom
    assert any(
        _bbox_area(item.polygon) > _bbox_area(occlusion.polygon) * 4
        for item in result.ink_origins
        if math_span.observation_id in item.overlap_observation_ids
    )


def test_low_confidence_ocr_remains_unknown() -> None:
    fixture = make_fixture()
    low = fixture.text_record.create(
        component="text_ocr",
        provider=fixture.text_record.provider,
        source_revision_hash=fixture.text_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=({"text": "maybe", "confidence": 0.2, "polygon": [[20, 320], [100, 320], [100, 350], [20, 350]]},),
    )
    result = PaddleObservationAdapter().text(low, source_artifact_id="artifact:page")
    assert result[0].origin == "unknown"


def test_ink_analysis_is_deterministic() -> None:
    fixture = make_fixture(colored_ink=True)
    spans = PaddleObservationAdapter().text(fixture.text_record, source_artifact_id="artifact:page")
    analyzer = ConservativeInkOriginAnalyzer()
    first = analyzer.analyze(page_id="page_1", image_bytes=fixture.page_bytes, source_artifact_id="artifact:page", text_spans=spans)
    second = analyzer.analyze(page_id="page_1", image_bytes=fixture.page_bytes, source_artifact_id="artifact:page", text_spans=spans)
    assert [item.to_payload() for item in first.ink_origins] == [item.to_payload() for item in second.ink_origins]
    assert first.mask_png == second.mask_png


def _bbox_area(polygon) -> float:
    left, top, right, bottom = polygon_bbox(polygon)
    return (right - left) * (bottom - top)
