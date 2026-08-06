from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.f2_smoke import (
    _load_provider_runs,
    _validate_selection_scoped_text_runs,
    _write_provider_records,
    evaluate_f2_acceptance,
)
from shuxueshuo_server.solver.extraction.paddle_worker import PaddleProviderRun
from shuxueshuo_server.solver.extraction.observations import FormulaObservation
from shuxueshuo_server.solver.extraction.gold_corpus import (
    Evidence,
    GoldAnnotation,
    GoldCorpusCase,
    SourceManifest,
)
from _problem_extraction_f2_support import assemble_fixture, make_fixture


def _acceptance_case(tmp_path: Path) -> tuple[GoldCorpusCase, object]:
    _, result, _ = assemble_fixture(tmp_path)
    spans = tuple(
        item
        for item in result.observation.text_spans
        if item.observation_id in result.observation.selected_observation_ids
    )
    evidence = tuple(
        Evidence(
            evidence_id=f"evidence:line:{index}",
            page_id=span.page_id,
            kind="text_formula" if "x^2" in span.text else "text",
            origin="printed",
            purpose="problem_source",
            polygon=span.polygon,
            transcript=span.text,
        )
        for index, span in enumerate(spans)
    )
    annotation = GoldAnnotation(
        schema_version="problem-extraction-gold/v1",
        problem_id="synthetic-f2",
        question_label="25",
        selection_source="test",
        selection_regions=(),
        excluded_subjects=(),
        excluded_regions=(),
        evidence=evidence,
        semantic_evidence={
            "original_text_lines": {
                str(index): (item.evidence_id,)
                for index, item in enumerate(evidence)
            }
        },
        coverage={},
        path=tmp_path / "gold-annotation.json",
    )
    manifest = SourceManifest(
        schema_version="problem-extraction-source/v1",
        problem_id="synthetic-f2",
        problem_fixture="unused.json",
        pages=(),
        path=tmp_path / "source-manifest.json",
    )
    return GoldCorpusCase(manifest, annotation), result.observation


def test_smoke_acceptance_passes_complete_recorded_observation(tmp_path) -> None:
    case, observation = _acceptance_case(tmp_path)

    metrics, failures = evaluate_f2_acceptance(case, observation, True)

    assert failures == []
    assert metrics["normalized_ocr_cer"] == 0
    assert metrics["formula_observed_or_typed_issue"] is True
    assert metrics["deterministic_recorded_replay"] is True


def test_smoke_acceptance_rejects_missing_line_formula_and_replay(tmp_path) -> None:
    case, observation = _acceptance_case(tmp_path)
    selected_spans = tuple(
        item
        for item in observation.text_spans
        if item.observation_id in observation.selected_observation_ids
    )
    broken = replace(
        observation,
        text_spans=tuple(
            item for item in observation.text_spans if item is not selected_spans[-1]
        ),
        formulas=(),
        issues=tuple(
            item
            for item in observation.issues
            if item.code != "extraction.formula_observation_unresolved"
        ),
    )

    _, failures = evaluate_f2_acceptance(case, broken, False)

    assert "original_text_line_missing" in failures
    assert "gold_printed_evidence_uncovered" in failures
    assert "formula_observation_missing_without_issue" in failures
    assert "recorded_replay_drift" in failures


def test_smoke_acceptance_rejects_unresolved_formula_without_typed_issue(
    tmp_path,
) -> None:
    case, observation = _acceptance_case(tmp_path)
    source = next(item for item in observation.text_spans if "x^2" in item.text)
    unresolved = FormulaObservation(
        observation_id="observation:formula:untracked",
        page_id=source.page_id,
        polygon=source.polygon,
        confidence=0.5,
        origin="printed",
        source_artifact_id=source.source_artifact_id,
        provider_id=source.provider_id,
        reading_order=source.reading_order,
        latex="y=x^2",
        status="unresolved",
        source_observation_ids=(source.observation_id,),
        formula_request_id="formula-request:" + "a" * 64,
        source_text_hint="y=x^2+1",
        crop_artifact_id="artifact:test",
    )
    broken = replace(
        observation,
        formulas=(unresolved,),
        issues=tuple(
            item
            for item in observation.issues
            if item.code != "extraction.formula_observation_unresolved"
        ),
    )

    metrics, failures = evaluate_f2_acceptance(case, broken, True)

    assert metrics["unresolved_formula_without_typed_issue"] == [
        unresolved.observation_id
    ]
    assert "unresolved_formula_missing_typed_issue" in failures


def test_confirmed_selection_ocr_rejects_outside_text() -> None:
    fixture = make_fixture()
    run = PaddleProviderRun(fixture.text_record, ())

    with pytest.raises(RuntimeError, match="outside the confirmed selection"):
        _validate_selection_scoped_text_runs(fixture.context, (run,))  # type: ignore[arg-type]


def test_provider_record_replay_preserves_raw_vendor_payloads(tmp_path) -> None:
    fixture = make_fixture()
    run = PaddleProviderRun(
        fixture.text_record,
        ({"vendor_result": {"rec_text": "25. y=x^2+1", "score": 0.97}},),
    )

    _write_provider_records("synthetic-f2", tmp_path, (run,))
    restored = _load_provider_runs(tmp_path, "synthetic-f2")

    assert len(restored) == 1
    assert restored[0].record.to_payload() == run.record.to_payload()
    assert restored[0].raw_payloads == run.raw_payloads
