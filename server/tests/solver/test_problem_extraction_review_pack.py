from __future__ import annotations

import json
from dataclasses import replace

import pytest

from shuxueshuo_server.solver.extraction.observation_context import ObservationContextTransitionService
from shuxueshuo_server.solver.extraction.observations import FormulaObservation
from shuxueshuo_server.solver.extraction.review import (
    ObservationReviewCase,
    render_observation_review_pack,
)
from _problem_extraction_f2_support import (
    assemble_fixture,
    successful_ledger,
)


def _review_case(tmp_path):
    fixture, result, _ = assemble_fixture(tmp_path, colored_ink=True)
    child = ObservationContextTransitionService().attach(
        fixture.context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=successful_ledger(fixture.context, result.artifacts),
    )
    return ObservationReviewCase(
        problem_id="synthetic-f2",
        observation=result.observation,
        context=child,
        page_images={"page_1": fixture.page_bytes},
    )


def test_static_review_pack_contains_all_layers(tmp_path) -> None:
    case = _review_case(tmp_path)
    paths = render_observation_review_pack((case,), tmp_path / "review")
    names = {path.relative_to(tmp_path / "review").as_posix() for path in paths}
    assert "index.html" in names
    assert "synthetic-f2/review.html" in names
    assert "synthetic-f2/source-observation.json" in names
    assert "synthetic-f2/review-summary.json" in names
    assert {
        "synthetic-f2/overlays/page_1-layout.png",
        "synthetic-f2/overlays/page_1-selection_ocr.png",
        "synthetic-f2/overlays/page_1-formula.png",
        "synthetic-f2/overlays/page_1-ink.png",
    }.issubset(names)
    review_html = (tmp_path / "review/synthetic-f2/review.html").read_text()
    assert "人工签核清单" in review_html
    assert 'href="#region"' in review_html
    assert 'href="#ocr"' in review_html
    assert 'href="#formula"' in review_html
    assert 'href="#ink"' in review_html
    assert "Formula crops" in review_html
    assert "精确 ink mask" in review_html
    assert review_html.index('id="region"') < review_html.index('id="ocr"')
    assert review_html.index('id="ocr"') < review_html.index('id="formula"')


def test_review_summary_excludes_semantic_authority(tmp_path) -> None:
    case = _review_case(tmp_path)
    render_observation_review_pack((case,), tmp_path / "review")
    payload = json.loads((tmp_path / "review/synthetic-f2/review-summary.json").read_text())
    assert payload["review_boundaries"]["excluded"] == [
        "route",
        "scope",
        "entity",
        "fact",
        "goal",
        "ProblemIR",
    ]
    serialized = json.dumps(payload)
    assert '"facts"' not in serialized
    assert '"question_goals"' not in serialized
    assert [item["id"] for item in payload["human_review_checklist"]] == [
        "region",
        "ocr",
        "formula",
        "ink",
        "issues",
    ]


def test_review_render_is_deterministic_and_does_not_mutate_context(tmp_path) -> None:
    case = _review_case(tmp_path)
    before = case.context.to_payload()
    first = render_observation_review_pack((case,), tmp_path / "first")
    second = render_observation_review_pack((case,), tmp_path / "second")
    first_payload = (tmp_path / "first/synthetic-f2/review-summary.json").read_bytes()
    second_payload = (tmp_path / "second/synthetic-f2/review-summary.json").read_bytes()
    assert first_payload == second_payload
    assert len(first) == len(second)
    assert case.context.to_payload() == before


def test_review_pack_rejects_missing_formula_crop(tmp_path) -> None:
    case = _review_case(tmp_path)
    source = next(item for item in case.observation.text_spans if "x^2" in item.text)
    formula = FormulaObservation(
        observation_id="observation:formula:missing-crop",
        page_id=source.page_id,
        polygon=source.polygon,
        confidence=0.5,
        origin="printed",
        source_artifact_id=source.source_artifact_id,
        provider_id=source.provider_id,
        reading_order=source.reading_order,
        latex="y=x^2+1",
        status="recognized",
        source_observation_ids=(source.observation_id,),
        formula_request_id="formula-request:" + "a" * 64,
        source_text_hint="y=x^2+1",
        crop_artifact_id="artifact:missing",
    )
    broken = replace(
        case,
        observation=replace(case.observation, formulas=(formula,)),
    )

    with pytest.raises(RuntimeError, match="formula crop artifact is unavailable"):
        render_observation_review_pack((broken,), tmp_path / "review")
