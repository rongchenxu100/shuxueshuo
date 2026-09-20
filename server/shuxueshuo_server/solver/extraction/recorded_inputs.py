"""Matching repository images and recorded Paddle outputs for offline/live acceptance.

Only observation responses are replayed; the adapter, evidence and validators are real.
"""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext, ExtractionAttemptLedger, ExtractionRetryState, ProblemExtractionContextBuilder
from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
from shuxueshuo_server.solver.extraction.multimodal_evidence import MultimodalEvidencePackBuilder
from shuxueshuo_server.solver.extraction.observation_context import ObservationContextTransitionService, f2_semantic_config
from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline
from shuxueshuo_server.solver.extraction.observations import PaddleProviderRecord
from shuxueshuo_server.solver.extraction.source_identity import ExtractionDependencyManifest, ProblemSourceFingerprintService, SourceAssetInput, SourceSelection, SelectionRegion


from shuxueshuo_server.solver.extraction.context import ExtractionAttemptRecord
from shuxueshuo_server.solver.extraction.observations import ProviderManifest

def recorded_gold_input(tmp_path, case):
    repo = Path(__file__).resolve().parents[4]
    FIXTURE = repo / 'server/tests/solver/fixtures/source_review/heping-layout-miss'
    manifest = json.loads((repo / 'internal/source-images' / case / 'source-manifest.json').read_text())
    image_path = repo / manifest['pages'][0]['asset_path']
    content = image_path.read_bytes()
    if sha256(content).hexdigest() != manifest["pages"][0]["sha256"]:
        raise ValueError("recorded source image hash mismatch")
    page_id = 'page_1'
    source = ProblemSourceFingerprintService().fingerprint((SourceAssetInput(
        page_id=page_id, media_type='image/jpeg' if image_path.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png', content_bytes=content, locator='fixture://source.png'),))
    selection = SourceSelection.create(source, mode='user_confirmed', revision=0,
        regions=(SelectionRegion('question', page_id, ((0, 0), (1, 0), (1, 1), (0, 1))),))
    records = []
    manifests = []
    for name, component in [('layout', 'layout'), ('text', 'text_ocr')]:
        raw = json.loads((FIXTURE.parent / 'gold-observations' / (case + '.json')).read_text())[component]
        raw = {k: v for k, v in raw.items() if k != 'page_id'}
        manifest = ProviderManifest.create(provider='recorded_paddle', component=component, model_name='recorded-' + name, model_revision='fixture/v1', software_versions={'replay': '1'}, config={})
        manifests.append(manifest)
        records.append(PaddleProviderRecord.create(component=component, provider=manifest,
            source_revision_hash=source.source_revision_hash, page_id=page_id, **raw))
    manifests.append(ConservativeInkOriginAnalyzer().provider)
    dependency = ExtractionDependencyManifest.create(source, selection,
        semantic_config=f2_semantic_config([p.to_payload() for p in manifests]))
    initial = ProblemExtractionContextBuilder.initial(source=source, selection=selection, dependency=dependency,
        retry=ExtractionRetryState(attempt_budget=8), quality={'problem_id': case})
    store = ExtractionArtifactStore(tmp_path / 'artifacts')
    from shuxueshuo_server.solver.extraction.multimodal_evidence import _selection_canvas
    crop_bytes = _selection_canvas(initial, page_id, content)
    crop = store.put_bytes(kind='selection_crop', content=crop_bytes, media_type='image/png', suffix='.png')
    assembly = F2ObservationPipeline(artifact_store=store).assemble(source=source, selection=selection,
        dependency=dependency, page_bytes={page_id: content}, layout_records=(records[0],), text_records=(records[1],),
        extra_artifacts=(crop,))
    context = ObservationContextTransitionService().attach(initial, assembly.observation,
        artifacts=assembly.artifacts, attempt_ledger=_recorded_ledger(initial, assembly.artifacts))
    pack = MultimodalEvidencePackBuilder().build(context, artifact_reader=store, observation=assembly.observation)
    return initial, context, store, pack


def _recorded_ledger(
    context: ProblemExtractionContext,
    artifacts: tuple,
) -> ExtractionAttemptLedger:
    provider_output = tuple(
        item for item in artifacts if item.kind.startswith("provider_")
    )
    provider_attempt = ExtractionAttemptRecord(
        attempt_id="attempt_f2_provider",
        base_context_id=context.manifest.context_id,
        provider="recorded_f2",
        route="pending",
        input_artifact_refs=tuple(
            item
            for item in artifacts
            if item.kind
            in {"canonical_source_page", "selection_crop", "formula_crop"}
        ),
        output_artifact_refs=provider_output,
        result="succeeded",
        usage={"recorded_provider_outputs": len(provider_output)},
        latency_ms=0,
    )
    ledger = ExtractionAttemptLedger(context.manifest.context_id).append(
        context,
        provider_attempt,
    )
    masks = tuple(item for item in artifacts if item.kind == "handwriting_mask")
    if not masks:
        return ledger
    ink_attempt = ExtractionAttemptRecord(
        attempt_id="attempt_f2_ink_origin",
        base_context_id=context.manifest.context_id,
        provider="local_cv",
        route="pending",
        input_artifact_refs=tuple(
            item
            for item in artifacts
            if item.kind in {"canonical_source_page", "provider_text_ocr"}
        ),
        output_artifact_refs=masks,
        result="succeeded",
        usage={"page_count": len(masks)},
        latency_ms=0,
    )
    return ledger.append(context, ink_attempt)
