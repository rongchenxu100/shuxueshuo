from __future__ import annotations

from dataclasses import replace

import pytest

from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.observation_context import (
    ObservationContextTransitionService,
)
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import (
    PaddleObservationAdapter,
    PaddleProviderRecord,
    select_formula_crop_requests,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    ProblemExtractionContextError,
)
from _problem_extraction_f2_support import (
    assemble_fixture,
    make_fixture,
    successful_ledger,
)


def test_successful_observation_attach_is_atomic_and_round_trips(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    ledger = successful_ledger(fixture.context, result.artifacts)
    assert {item.provider for item in ledger.attempts} == {"recorded_f2", "local_cv"}
    child = ObservationContextTransitionService().attach(
        fixture.context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=ledger,
    )
    assert child.manifest.parent_context_id == fixture.context.manifest.context_id
    assert child.events[-1].event == "source_observation_attached"
    assert child.quality["source_observation_hash"] == result.observation.observation_hash
    assert set(child.state.to_payload()) == {"artifacts", "evidence", "issues"}
    restored = ProblemExtractionContext.from_payload(
        child.to_payload(),
        ancestor_contexts=(fixture.context,),
    )
    assert restored.to_payload() == child.to_payload()


def test_failed_provider_attempt_does_not_create_child(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    attempt = ExtractionAttemptRecord(
        attempt_id="attempt_failed",
        base_context_id=fixture.context.manifest.context_id,
        provider="paddle_ocr",
        route="pending",
        input_artifact_refs=(),
        output_artifact_refs=(),
        result="failed",
        usage={},
        latency_ms=1,
    )
    ledger = ExtractionAttemptLedger(fixture.context.manifest.context_id).append(fixture.context, attempt)
    before = fixture.context.to_payload()
    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=result.artifacts,
            attempt_ledger=ledger,
        )
    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert fixture.context.to_payload() == before


def test_provider_manifest_drift_fails_closed(tmp_path) -> None:
    fixture = make_fixture()
    semantic_config = dict(fixture.dependency.semantic_config)
    semantic_config["f2_provider_ids"] = ["provider:unexpected"]
    dependency = ExtractionDependencyManifest.create(
        fixture.source,  # type: ignore[arg-type]
        fixture.selection,
        semantic_config=semantic_config,
    )
    context = ProblemExtractionContextBuilder.initial(
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency=dependency,
        retry=fixture.context.retry,
        quality={"problem_id": "synthetic-f2-provider-drift"},
    )
    store = ExtractionArtifactStore(tmp_path / "provider-drift")
    result = F2ObservationPipeline(artifact_store=store).assemble(
        source=fixture.source,  # type: ignore[arg-type]
        selection=fixture.selection,
        dependency=dependency,
        page_bytes={"page_1": fixture.page_bytes},
        layout_records=(fixture.layout_record,),
        text_records=(fixture.text_record,),
        formula_records=(fixture.formula_record,),
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            context,
            result.observation,
            artifacts=result.artifacts,
            attempt_ledger=successful_ledger(context, result.artifacts),
        )

    assert error.value.code == "extraction.observation_invalid"
    assert error.value.path == "$.dependency.semantic_config.f2_provider_ids"


def test_repeated_attach_is_idempotent_but_drift_fails(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    ledger = successful_ledger(fixture.context, result.artifacts)
    service = ObservationContextTransitionService()
    child = service.attach(fixture.context, result.observation, artifacts=result.artifacts, attempt_ledger=ledger)
    assert service.attach(child, result.observation, artifacts=result.artifacts, attempt_ledger=ledger) is child
    drifted = replace(result.observation, observation_hash="0" * 64)
    with pytest.raises(ProblemExtractionContextError) as error:
        service.attach(child, drifted, artifacts=result.artifacts, attempt_ledger=ledger)
    assert error.value.code == "extraction.observation_invalid"


def test_missing_provider_output_artifact_fails_closed(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    ledger = successful_ledger(fixture.context, result.artifacts)
    provider_artifact = next(item for item in result.artifacts if item.kind.startswith("provider_"))
    artifacts = tuple(item for item in result.artifacts if item != provider_artifact)
    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=artifacts,
            attempt_ledger=ledger,
        )
    assert error.value.code == "extraction.attempt_ledger_mismatch"


def test_untraced_provider_output_artifact_fails_closed(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    ledger = successful_ledger(fixture.context, result.artifacts)
    provider_attempt = next(
        item for item in ledger.attempts if item.provider == "recorded_f2"
    )
    untraced = provider_attempt.output_artifact_refs[0]
    broken = replace(
        ledger,
        attempts=tuple(
            replace(
                attempt,
                output_artifact_refs=tuple(
                    item
                    for item in attempt.output_artifact_refs
                    if item != untraced
                ),
            )
            if attempt is provider_attempt
            else attempt
            for attempt in ledger.attempts
        ),
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=result.artifacts,
            attempt_ledger=broken,
        )

    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert error.value.path == "$.attempt_ledger.output_artifact_refs"


def test_missing_handwriting_mask_artifact_fails_closed(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path, colored_ink=True)
    assert result.observation.ink_origins
    attached = ObservationContextTransitionService().attach(
        fixture.context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=successful_ledger(fixture.context, result.artifacts),
    )
    evidence_by_id = {item.evidence_id: item for item in attached.state.evidence}
    for ink in result.observation.ink_origins:
        assert evidence_by_id[ink.observation_id].payload["derived_artifact_ids"] == (
            ink.mask_artifact_id,
        )
    artifacts = tuple(
        item
        for item in result.artifacts
        if item.kind != "handwriting_mask"
    )
    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=artifacts,
            attempt_ledger=successful_ledger(fixture.context, result.artifacts),
        )
    assert error.value.code == "extraction.evidence_ref_unresolved"
    assert error.value.path == "$.ink_origins.mask_artifact_id"


def test_untraced_handwriting_mask_fails_closed(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path, colored_ink=True)
    ledger = successful_ledger(fixture.context, result.artifacts)
    without_ink_attempt = replace(
        ledger,
        attempts=tuple(item for item in ledger.attempts if item.provider != "local_cv"),
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=result.artifacts,
            attempt_ledger=without_ink_attempt,
        )

    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert error.value.path == "$.attempt_ledger.output_artifact_refs"


def test_missing_formula_crop_artifact_fails_closed(tmp_path) -> None:
    fixture = make_fixture()
    store = ExtractionArtifactStore(tmp_path / "formula-artifacts")
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
            {
                "latex": "y=x^2+1",
                "confidence": 0.9,
                "polygon": [
                    [round(x * 400, 6), round(y * 600, 6)]
                    for x, y in request.polygon
                ],
                "source_observation_ids": list(request.source_observation_ids),
                "formula_request_id": request.request_id,
                "source_text_hint": request.source_text_hint,
                "crop_artifact_id": crop.artifact_id,
            },
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
    attached = ObservationContextTransitionService().attach(
        fixture.context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=successful_ledger(fixture.context, result.artifacts),
    )
    formula = result.observation.formulas[0]
    evidence_by_id = {item.evidence_id: item for item in attached.state.evidence}
    assert evidence_by_id[formula.observation_id].payload[
        "derived_artifact_ids"
    ] == (crop.artifact_id,)
    artifacts = tuple(item for item in result.artifacts if item != crop)
    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=artifacts,
            attempt_ledger=successful_ledger(fixture.context, result.artifacts),
        )
    assert error.value.code == "extraction.formula_observation_unresolved"
    assert error.value.path == "$.formulas.crop_artifact_id"

    ledger = successful_ledger(fixture.context, result.artifacts)
    without_formula_crop_input = replace(
        ledger,
        attempts=tuple(
            replace(
                attempt,
                input_artifact_refs=tuple(
                    item
                    for item in attempt.input_artifact_refs
                    if item.kind != "formula_crop"
                ),
            )
            if attempt.provider == "recorded_f2"
            else attempt
            for attempt in ledger.attempts
        ),
    )
    with pytest.raises(ProblemExtractionContextError) as error:
        ObservationContextTransitionService().attach(
            fixture.context,
            result.observation,
            artifacts=result.artifacts,
            attempt_ledger=without_formula_crop_input,
        )
    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert error.value.path == "$.attempt_ledger.input_artifact_refs"


def test_observation_attachment_does_not_create_semantic_state(tmp_path) -> None:
    fixture, result, _ = assemble_fixture(tmp_path)
    child = ObservationContextTransitionService().attach(
        fixture.context,
        result.observation,
        artifacts=result.artifacts,
        attempt_ledger=successful_ledger(fixture.context, result.artifacts),
    )
    assert set(child.state.to_payload()) == {"artifacts", "evidence", "issues"}
