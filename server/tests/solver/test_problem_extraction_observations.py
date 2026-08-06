from __future__ import annotations

import ast
from dataclasses import replace
from io import BytesIO
import inspect
import sys

from PIL import Image
import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.gold_corpus import load_gold_corpus
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import (
    PaddleObservationAdapter,
    PaddleProviderRecord,
    ProblemExtractionContextError,
    ProblemRegionProposer,
    SourceObservation,
    TextSpanObservation,
    selected_observation_ids,
)
from shuxueshuo_server.solver.extraction.pdf_ingestion import PdfSourceRasterizer
from _problem_extraction_f2_support import (
    assemble_fixture,
    make_fixture,
)


def test_source_observation_round_trip_and_hash_are_stable(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    payload = result.observation.to_payload()
    restored = SourceObservation.from_payload(
        payload,
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency_hash=fixture.dependency.dependency_hash,
    )
    assert restored.to_payload() == payload
    assert restored.observation_hash == result.observation.observation_hash


def test_pipeline_rejects_debug_artifacts_from_authoritative_bundle(tmp_path) -> None:
    fixture = make_fixture()
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    raw = store.put_json(
        kind="provider_raw_text_ocr",
        payload={"vendor": "debug-only"},
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        F2ObservationPipeline(artifact_store=store).assemble(
            source=fixture.source,  # type: ignore[arg-type]
            selection=fixture.selection,
            dependency=fixture.dependency,
            page_bytes={"page_1": fixture.page_bytes},
            layout_records=(fixture.layout_record,),
            text_records=(fixture.text_record,),
            extra_artifacts=(raw,),
        )

    assert error.value.code == "extraction.observation_invalid"
    assert error.value.path == "$.extra_artifacts"


def test_gold_original_text_lines_have_physical_source_transcripts() -> None:
    for case in load_gold_corpus().cases:
        evidence_by_id = {
            evidence.evidence_id: evidence
            for evidence in case.annotation.evidence
        }
        line_evidence = case.annotation.semantic_evidence["original_text_lines"]
        assert line_evidence
        assert all(
            evidence_by_id[evidence_id].transcript
            for evidence_ids in line_evidence.values()
            for evidence_id in evidence_ids
        )


def test_f2_authoritative_producers_do_not_emit_semantic_candidate_fields() -> None:
    forbidden = {
        "scopes",
        "entities",
        "facts",
        "question_goals",
        "scope_candidates",
        "entity_candidates",
        "fact_candidates",
        "goal_candidates",
    }
    for producer in (
        PaddleObservationAdapter,
        ProblemRegionProposer,
        F2ObservationPipeline,
        ConservativeInkOriginAnalyzer,
    ):
        tree = ast.parse(inspect.getsource(producer))
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert literals.isdisjoint(forbidden), producer.__name__


def test_provider_item_order_does_not_change_canonical_observations() -> None:
    fixture = make_fixture()
    reversed_record = PaddleProviderRecord.create(
        component="text_ocr",
        provider=fixture.text_record.provider,
        source_revision_hash=fixture.text_record.source_revision_hash,
        page_id=fixture.text_record.page_id,
        width=fixture.text_record.width,
        height=fixture.text_record.height,
        items=tuple(reversed(fixture.text_record.items)),
    )
    adapter = PaddleObservationAdapter()
    source_artifact = "artifact:canonical:deadbeef"
    expected = adapter.text(fixture.text_record, source_artifact_id=source_artifact)
    actual = adapter.text(reversed_record, source_artifact_id=source_artifact)
    assert [item.to_payload() for item in actual] == [item.to_payload() for item in expected]


def test_selection_rejects_observations_that_only_graze_its_boundary() -> None:
    fixture = make_fixture()
    shared = {
        "page_id": "page_1",
        "confidence": 0.9,
        "origin": "printed",
        "source_artifact_id": "artifact:page",
        "provider_id": "provider:test",
        "reading_order": 0,
        "block_id": None,
    }
    centered = TextSpanObservation(
        observation_id="observation:centered",
        polygon=((0.10, 0.60), (0.30, 0.60), (0.30, 0.65), (0.10, 0.65)),
        text="inside",
        **shared,  # type: ignore[arg-type]
    )
    grazing = TextSpanObservation(
        observation_id="observation:grazing",
        polygon=((0.979, 0.60), (0.999, 0.60), (0.999, 0.65), (0.979, 0.65)),
        text="outside",
        **shared,  # type: ignore[arg-type]
    )

    assert selected_observation_ids(
        fixture.selection,
        (grazing, centered),
    ) == ("observation:centered",)


def test_reading_order_clusters_fraction_tokens_on_their_text_line() -> None:
    fixture = make_fixture()
    record = PaddleProviderRecord.create(
        component="text_ocr",
        provider=fixture.text_record.provider,
        source_revision_hash=fixture.text_record.source_revision_hash,
        page_id="page_1",
        width=400,
        height=600,
        items=(
            {"text": "2", "confidence": 0.9, "polygon": [[202, 219], [214, 219], [214, 231], [202, 231]]},
            {"text": "M(b+", "confidence": 0.9, "polygon": [[20, 210], [200, 210], [200, 230], [20, 230]]},
            {"text": ", y)", "confidence": 0.9, "polygon": [[216, 210], [270, 210], [270, 230], [216, 230]]},
            {"text": "1", "confidence": 0.9, "polygon": [[202, 202], [214, 202], [214, 214], [202, 214]]},
        ),
    )
    spans = PaddleObservationAdapter().text(record, source_artifact_id="artifact:page")
    assert [item.text for item in spans] == ["M(b+", "1", "2", ", y)"]


def test_provider_record_rejects_semantic_fields_and_nonfinite_confidence() -> None:
    fixture = make_fixture()
    with pytest.raises(ProblemExtractionContextError) as semantic:
        PaddleProviderRecord.create(
            component="text_ocr",
            provider=fixture.text_record.provider,
            source_revision_hash=fixture.text_record.source_revision_hash,
            page_id="page_1",
            width=400,
            height=600,
            items=({"text": "x", "confidence": 0.9, "polygon": [[1, 1], [2, 1], [2, 2], [1, 2]], "facts": []},),
        )
    assert semantic.value.code == "extraction.provider_record_invalid"
    with pytest.raises(ProblemExtractionContextError):
        PaddleProviderRecord.create(
            component="text_ocr",
            provider=fixture.text_record.provider,
            source_revision_hash=fixture.text_record.source_revision_hash,
            page_id="page_1",
            width=400,
            height=600,
            items=({"text": "x", "confidence": float("nan"), "polygon": [[1, 1], [2, 1], [2, 2], [1, 2]]},),
        )


def test_observation_hash_tampering_fails(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    payload = result.observation.to_payload()
    payload["observation_hash"] = "0" * 64
    with pytest.raises(ProblemExtractionContextError) as error:
        SourceObservation.from_payload(
            payload,
            source=fixture.source,  # type: ignore[arg-type]
            selection=fixture.selection,
            dependency_hash=fixture.dependency.dependency_hash,
        )
    assert error.value.code == "extraction.observation_invalid"


def test_default_observation_pipeline_never_imports_paddle(tmp_path) -> None:
    before = {name for name in sys.modules if name == "paddle" or name.startswith("paddle.")}
    assemble_fixture(tmp_path)
    after = {name for name in sys.modules if name == "paddle" or name.startswith("paddle.")}
    assert after == before


def test_two_page_pdf_rasterizes_in_stable_order(tmp_path) -> None:
    first = Image.new("RGB", (40, 30), "white")
    second = Image.new("RGB", (40, 30), "black")
    buffer = BytesIO()
    first.save(buffer, format="PDF", save_all=True, append_images=[second])
    store = ExtractionArtifactStore(tmp_path / "artifacts")
    result = PdfSourceRasterizer(dpi=72).rasterize(buffer.getvalue(), artifact_store=store)
    assert [item.page_id for item in result.pages] == ["page_1", "page_2"]
    assert all(item.media_type == "image/png" for item in result.pages)
    again = PdfSourceRasterizer(dpi=72).rasterize(buffer.getvalue(), artifact_store=store)
    assert [item.artifact_id for item in again.page_artifacts] == [item.artifact_id for item in result.page_artifacts]


def test_source_or_selection_drift_is_rejected(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    drifted = replace(result.observation, selection_id="selection:" + "0" * 64)
    with pytest.raises(ProblemExtractionContextError):
        drifted.validate(
            fixture.source,  # type: ignore[arg-type]
            fixture.selection,
            fixture.dependency.dependency_hash,
        )
