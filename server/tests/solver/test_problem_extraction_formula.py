from __future__ import annotations

from dataclasses import replace

import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import (
    FormulaObservation,
    PaddleObservationAdapter,
    PaddleProviderRecord,
    ProblemExtractionContextError,
    SourceObservation,
    formula_math_fragments,
    formula_recognition_failure_reason,
    normalize_formula_text,
    select_formula_crop_requests,
    unresolved_formula_source_ids,
)
from _problem_extraction_f2_support import assemble_fixture, make_fixture


def _fixture_formula_request(fixture):
    adapter = PaddleObservationAdapter()
    layout = adapter.layout(
        fixture.layout_record,
        source_artifact_id="artifact:placeholder",
    )
    spans = adapter.text(
        fixture.text_record,
        source_artifact_id="artifact:placeholder",
        layout_blocks=layout,
    )
    request = select_formula_crop_requests(layout, spans)[0]
    return request, spans


def _provider_formula_item(request, latex: str, *, crop_artifact_id=None):
    item = {
        "latex": latex,
        "confidence": 0.9,
        "polygon": [
            [round(x * 400, 6), round(y * 600, 6)]
            for x, y in request.polygon
        ],
        "source_observation_ids": list(request.source_observation_ids),
        "formula_request_id": request.request_id,
        "source_text_hint": request.source_text_hint,
    }
    if crop_artifact_id is not None:
        item["crop_artifact_id"] = crop_artifact_id
    return item


def test_math_text_produces_formula_crop_request() -> None:
    fixture = make_fixture()
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
    requests = select_formula_crop_requests(layout, spans)
    assert len(requests) == 1
    assert requests[0].source_text_hint == "y=x^2+1"
    assert any("y=x^2+1" in item.text for item in spans if item.observation_id in requests[0].source_observation_ids)


def test_prose_math_line_is_split_into_tight_formula_requests() -> None:
    fixture = make_fixture()
    _, spans = _fixture_formula_request(fixture)
    source = next(item for item in spans if "x^2" in item.text)
    source = replace(
        source,
        text="②抛物线上的点E的横坐标为m,且-1<m<0,若∠CBE+∠ACO=45°,求点E的坐标",
        polygon=((0.1, 0.2), (0.9, 0.2), (0.9, 0.25), (0.1, 0.25)),
    )

    requests = select_formula_crop_requests((), (source,))

    assert [item.source_text_hint for item in requests] == [
        "-1<m<0",
        "∠CBE+∠ACO=45°",
    ]
    assert requests[0].source_text_range == (16, 22)
    assert requests[1].source_text_range == (24, 37)
    source_width = max(x for x, _ in source.polygon) - min(x for x, _ in source.polygon)
    request_widths = [
        max(x for x, _ in item.polygon) - min(x for x, _ in item.polygon)
        for item in requests
    ]
    assert all(width < source_width * 0.4 for width in request_widths)
    assert max(x for x, _ in requests[0].polygon) < min(
        x for x, _ in requests[1].polygon
    )


def test_plain_text_does_not_call_formula_selection() -> None:
    fixture = make_fixture()
    adapter = PaddleObservationAdapter()
    spans = tuple(
        item
        for item in adapter.text(fixture.text_record, source_artifact_id="artifact:page")
        if item.text == "24. neighbor"
    )
    assert select_formula_crop_requests((), spans) == ()


def test_unknown_math_text_does_not_trigger_formula_crop() -> None:
    fixture = make_fixture()
    spans = PaddleObservationAdapter().text(
        fixture.text_record,
        source_artifact_id="artifact:page",
    )
    assert any("x^2" in item.text and item.origin == "unknown" for item in spans)
    assert select_formula_crop_requests((), spans) == ()


def test_handwritten_math_is_retained_as_unresolved_observation() -> None:
    fixture = make_fixture()
    spans = PaddleObservationAdapter().text(
        fixture.text_record,
        source_artifact_id="artifact:page",
    )
    handwritten = tuple(
        replace(item, origin="handwritten") if "x^2" in item.text else item
        for item in spans
    )
    source_id = next(item.observation_id for item in handwritten if "x^2" in item.text)

    assert select_formula_crop_requests((), handwritten) == ()
    assert unresolved_formula_source_ids((), handwritten) == (source_id,)


def test_handwritten_or_mixed_math_does_not_trigger_formula_crop(tmp_path) -> None:
    _, result, _ = assemble_fixture(
        tmp_path,
        colored_ink=True,
        include_formula=False,
    )
    math_spans = [
        item
        for item in result.observation.text_spans
        if "x^2" in item.text
    ]
    assert math_spans
    assert any(item.origin == "mixed" for item in math_spans)
    assert result.formula_requests == ()
    assert any(
        item.code == "extraction.formula_observation_unresolved"
        and item.details["reason"] == "formula_candidate_origin_not_printed"
        for item in result.observation.issues
    )


def test_formula_result_for_handwritten_request_is_rejected(tmp_path) -> None:
    fixture = make_fixture(colored_ink=True)
    request, _ = _fixture_formula_request(fixture)
    record = PaddleProviderRecord.create(
        component="formula_ocr",
        provider=fixture.formula_record.provider,
        source_revision_hash=fixture.formula_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            _provider_formula_item(request, "y=x^2+1"),
        ),
    )
    with pytest.raises(ProblemExtractionContextError) as error:
        F2ObservationPipeline(
            artifact_store=ExtractionArtifactStore(tmp_path / "artifacts")
        ).assemble(
            source=fixture.source,  # type: ignore[arg-type]
            selection=fixture.selection,
            dependency=fixture.dependency,
            page_bytes={"page_1": fixture.page_bytes},
            layout_records=(fixture.layout_record,),
            text_records=(fixture.text_record,),
            formula_records=(record,),
        )
    assert error.value.code == "extraction.formula_observation_unresolved"


def test_formula_adapter_normalizes_latex_and_links_source() -> None:
    fixture = make_fixture()
    adapter = PaddleObservationAdapter()
    request, _ = _fixture_formula_request(fixture)
    record = PaddleProviderRecord.create(
        component="formula_ocr",
        provider=fixture.formula_record.provider,
        source_revision_hash=fixture.formula_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            _provider_formula_item(request, " y = x ^ 2 + 1 "),
        ),
    )
    formulas = adapter.formulas(record, source_artifact_id="artifact:page")
    assert formulas[0].latex == "y = x ^ 2 + 1"
    assert formulas[0].source_observation_ids == request.source_observation_ids
    assert formulas[0].formula_request_id == request.request_id
    assert formulas[0].source_text_hint == "y=x^2+1"


def test_missing_formula_record_becomes_typed_issue(tmp_path) -> None:
    _, result, _ = assemble_fixture(tmp_path, include_formula=False)
    assert result.observation.formulas == ()
    assert "extraction.formula_observation_unresolved" in {
        item.code for item in result.observation.issues
    }


def test_pipeline_accepts_formula_crop_artifact(tmp_path) -> None:
    fixture = make_fixture()
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    request, _ = _fixture_formula_request(fixture)
    crop = store.put_bytes(kind="formula_crop", content=b"png", media_type="image/png", suffix=".png")
    record = PaddleProviderRecord.create(
        component="formula_ocr",
        provider=fixture.formula_record.provider,
        source_revision_hash=fixture.formula_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            _provider_formula_item(
                request,
                "y=x^2+1",
                crop_artifact_id=crop.artifact_id,
            ),
        ),
    )
    result = F2ObservationPipeline(artifact_store=store).assemble(
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency=fixture.dependency,
        page_bytes={"page_1": fixture.page_bytes},
        layout_records=(fixture.layout_record,),
        text_records=(fixture.text_record,),
        formula_records=(record,),
        extra_artifacts=(crop,),
    )
    assert result.observation.formulas[0].crop_artifact_id == crop.artifact_id
    assert not any(item.code == "extraction.formula_observation_unresolved" for item in result.observation.issues)


def test_pipeline_rejects_stale_formula_request_for_same_source(tmp_path) -> None:
    fixture = make_fixture()
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    request, _ = _fixture_formula_request(fixture)
    crop = store.put_bytes(
        kind="formula_crop",
        content=b"png",
        media_type="image/png",
        suffix=".png",
    )
    item = _provider_formula_item(
        request,
        "y=x^2+1",
        crop_artifact_id=crop.artifact_id,
    )
    item["formula_request_id"] = "formula-request:" + "f" * 64
    record = PaddleProviderRecord.create(
        component="formula_ocr",
        provider=fixture.formula_record.provider,
        source_revision_hash=fixture.formula_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(item,),
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        F2ObservationPipeline(artifact_store=store).assemble(
            source=fixture.source,  # type: ignore[arg-type]
            selection=fixture.selection,
            dependency=fixture.dependency,
            page_bytes={"page_1": fixture.page_bytes},
            layout_records=(fixture.layout_record,),
            text_records=(fixture.text_record,),
            formula_records=(record,),
            extra_artifacts=(crop,),
        )

    assert error.value.code == "extraction.formula_observation_unresolved"
    assert error.value.path == "$.formulas.formula_request_id"


def test_formula_normalization_does_not_apply_symbolic_rewrite() -> None:
    assert normalize_formula_text(" -c + 1 ") == "-c + 1"
    assert normalize_formula_text("1-c") == "1-c"


@pytest.mark.parametrize(
    ("source", "recognized", "reason"),
    (
        (
            "已知抛物线y=-x2+bx+c(b,c为常数,c>1)的顶点为P",
            "y=-x^{2}+bx+c(b,c 为常数,c>1) 的顶点为 P",
            "formula_output_contains_prose",
        ),
        (
            "当HF+FM+MG取得最小值为3√5时,求点E的坐标",
            "HF+FM+MG",
            "formula_output_incomplete",
        ),
        (
            "若∠CBE+∠ACO=45°,求点E的坐标",
            "\\angle CBE+" + "\\angle B^2=" * 80,
            "formula_output_excessive_expansion",
        ),
    ),
)
def test_formula_quality_gate_rejects_prose_incomplete_and_repeated_outputs(
    source: str,
    recognized: str,
    reason: str,
) -> None:
    assert formula_recognition_failure_reason((source,), recognized) == reason


def test_formula_quality_gate_accepts_complete_printed_math() -> None:
    assert (
        formula_recognition_failure_reason(
            ("(I)若b=-2,c=3.",),
            "b=-2,\\quad c=3.",
        )
        is None
    )
    assert formula_recognition_failure_reason(("a>0",), "\\because a>0") is None


def test_formula_quality_gate_rejects_extra_neighboring_characters() -> None:
    assert (
        formula_recognition_failure_reason(
            ("y=ax2+bx-3",),
            "y=a x^{2}+b x-3(a",
        )
        == "formula_output_contains_unexpected_content"
    )


def test_source_observation_rejects_recognized_nonprinted_formula(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    source = next(item for item in result.observation.text_spans if "x^2" in item.text)
    formula = FormulaObservation(
        observation_id="observation:formula:mixed-recognized",
        page_id=source.page_id,
        polygon=source.polygon,
        confidence=0.9,
        origin="mixed",
        source_artifact_id=source.source_artifact_id,
        provider_id=fixture.formula_record.provider.provider_id,
        reading_order=source.reading_order,
        latex="y=x^2+1",
        status="recognized",
        source_observation_ids=(source.observation_id,),
        formula_request_id="formula-request:" + "a" * 64,
        source_text_hint="y=x^2+1",
        crop_artifact_id="artifact:test",
    )
    observation = result.observation

    with pytest.raises(ProblemExtractionContextError) as error:
        SourceObservation.create(
            source=fixture.source,  # type: ignore[arg-type]
            selection=fixture.selection,
            dependency_hash=fixture.dependency.dependency_hash,
            providers=observation.providers,
            pages=observation.pages,
            layout_blocks=observation.layout_blocks,
            text_spans=observation.text_spans,
            formulas=(formula,),
            ink_origins=observation.ink_origins,
            occlusions=observation.occlusions,
            proposals=observation.proposals,
            selected_observation_ids=observation.selected_observation_ids,
            issues=observation.issues,
        )

    assert error.value.code == "extraction.formula_observation_unresolved"


def test_formula_fragment_coverage_preserves_leading_numeric_value() -> None:
    assert formula_math_fragments(
        "当HF+FM+MG取得最小值为3√5时,求点E的坐标"
    ) == ("HF+FM+MG", "3√5")
    assert formula_math_fragments("与x轴相交于点A(-1,0)和点B") == ("A(-1,0)",)


def test_pipeline_downgrades_incomplete_formula_to_typed_unresolved(tmp_path) -> None:
    fixture = make_fixture()
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    request, _ = _fixture_formula_request(fixture)
    crop = store.put_bytes(
        kind="formula_crop",
        content=b"png",
        media_type="image/png",
        suffix=".png",
    )
    record = PaddleProviderRecord.create(
        component="formula_ocr",
        provider=fixture.formula_record.provider,
        source_revision_hash=fixture.formula_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            _provider_formula_item(
                request,
                "y=x^2",
                crop_artifact_id=crop.artifact_id,
            ),
        ),
    )

    result = F2ObservationPipeline(artifact_store=store).assemble(
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency=fixture.dependency,
        page_bytes={"page_1": fixture.page_bytes},
        layout_records=(fixture.layout_record,),
        text_records=(fixture.text_record,),
        formula_records=(record,),
        extra_artifacts=(crop,),
    )

    assert result.observation.formulas[0].status == "unresolved"
    assert result.observation.formulas[0].latex == "y=x^2"
    assert any(
        item.code == "extraction.formula_observation_unresolved"
        and item.details["reason"] == "formula_output_incomplete"
        for item in result.observation.issues
    )
