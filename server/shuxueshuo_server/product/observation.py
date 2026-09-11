"""Isolated Paddle adapter. Only execution-local files and an output journal; no product/Review database."""
from io import BytesIO
import json
from pathlib import Path
import sys
import time
from PIL import Image


class ObservationJournal:
    def __init__(self, directory, identity, phase):
        self.directory = Path(directory)
        self.root = self.directory.parent
        self.identity, self.phase, self.records = identity, phase, []

    def get(self, identity):
        return {'artifacts': [{'name': '规范化图片', 'id': 'normalized.png'}]}

    def read(self, identity, artifact_id):
        return None, (self.directory / artifact_id).read_bytes()

    def add(self, identity, stage, role, name, value, media='application/json'):
        if stage != self.phase: return
        path = self.directory / f'ocr-{self.phase}-{len(self.records)}.bin'
        content = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        path.write_bytes(content)
        self.records.append({'stage': stage, 'role': role, 'name': name, 'path': path.name, 'media_type': media})
        (self.directory / f'{self.phase}-journal.json').write_text(json.dumps(self.records, ensure_ascii=False))

    def stage(self, *args): pass


def run(store, run_id, phase):
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
    from shuxueshuo_server.solver.extraction.context import (
        ExtractionAttemptLedger, ExtractionAttemptRecord, ExtractionRetryState,
        ProblemExtractionContextBuilder,
    )
    from shuxueshuo_server.solver.extraction.source_identity import (
        EXTRACTION_CONTRACT_VERSION, ExtractionDependencyManifest,
        ProblemSourceFingerprintService, SelectionRegion, SourceAssetInput, SourceSelection,
    )
    from shuxueshuo_server.solver.extraction.observation_context import ObservationContextTransitionService, f2_semantic_config
    from shuxueshuo_server.solver.extraction.observation_pipeline import F2ObservationPipeline, crop_formula_request
    from shuxueshuo_server.solver.extraction.handwriting import ConservativeInkOriginAnalyzer
    from shuxueshuo_server.solver.extraction.paddle_worker import PaddleF2ProviderWorker, FormulaWorkerInput

    image_ref = next(a for a in store.get(run_id)["artifacts"] if a["name"] == "规范化图片")
    _, content = store.read(run_id, image_ref["id"])
    artifacts = ExtractionArtifactStore(store.root / run_id / "extraction-artifacts")
    worker = PaddleF2ProviderWorker()
    ink = ConservativeInkOriginAnalyzer()
    manifests = worker.manifests() + (ink.provider,)
    source = ProblemSourceFingerprintService().fingerprint((SourceAssetInput(
        page_id="page-1", media_type="image/png", content_bytes=content,
        locator=str(store.directory / image_ref["id"])),))
    with Image.open(BytesIO(content)) as im:
        w, h = im.size
    selection = SourceSelection.create(source, mode="user_confirmed", revision=0,
        regions=(SelectionRegion(region_id="whole-image", page_id="page-1",
            polygon=((0, 0), (1, 0), (1, 1), (0, 1)), reason="用户上传完整单题截图"),))
    config = f2_semantic_config([m.to_payload() for m in manifests])
    dependency = ExtractionDependencyManifest.create(source, selection,
        extraction_contract_version=EXTRACTION_CONTRACT_VERSION, semantic_config=config)
    initial = ProblemExtractionContextBuilder.initial(source=source, selection=selection,
        dependency=dependency, producer="review_image_upload", producer_version="v1",
        retry=ExtractionRetryState(attempt_budget=8), quality={"problem_id": store.identity, "source": "upload"})
    if phase == 'source':
        store.add(run_id, "source", "output", "Source / selection / initial Context", initial.to_payload())
    store.stage(run_id, "source", "succeeded", f"完整单题截图 · {w} × {h}")
    store.stage(run_id, "observation", "running", "正在运行本地 Paddle")
    store.add(run_id, "observation", "input", "OCR 配置与来源", {"source": source.to_payload(), "config": config})
    if phase == 'source': return
    from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
    initial = ProblemExtractionContext.from_payload(json.loads((store.directory / 'initial.json').read_text()))
    source, selection, dependency = initial.source, initial.selection, initial.dependency
    pipeline = F2ObservationPipeline(artifact_store=artifacts, ink_analyzer=ink)
    selection_crop = artifacts.put_bytes(kind="selection_crop", content=content,
                                        media_type="image/png", suffix=".png")
    runs = []
    def call(name, fn):
        started = time.time()
        result = fn()
        runs.append(result)
        store.add(run_id, "observation", "call", name, {
            "provider": "paddle_local_cpu", "duration_seconds": time.time() - started,
            "usage": None, "record": result.record.to_payload(), "raw_payloads": result.raw_payloads})
        return result.record
    layout = call("版面识别", lambda: worker.layout(source_revision_hash=source.source_revision_hash,
        page_id="page-1", image_bytes=content))
    text = call("文字识别", lambda: worker.text(source_revision_hash=source.source_revision_hash,
        page_id="page-1", image_bytes=content))
    common = dict(source=source, selection=selection, dependency=dependency,
                  page_bytes={"page-1": content}, layout_records=(layout,), text_records=(text,))
    assembled = pipeline.assemble(**common, extra_artifacts=(selection_crop,))
    crop_refs, formula_inputs = [], []
    for request in assembled.formula_requests:
        crop = crop_formula_request(request, assembled.canonical_pages[0], artifact_store=artifacts)
        crop_refs.append(crop)
        formula_inputs.append(FormulaWorkerInput(request=request, crop_bytes=artifacts.read_bytes(crop),
                                                crop_artifact_id=crop.artifact_id))
    formulas = call("公式识别", lambda: worker.formulas(source_revision_hash=source.source_revision_hash,
        page_id="page-1", page_width=w, page_height=h, inputs=formula_inputs))
    final = pipeline.assemble(**common, formula_records=(formulas,), extra_artifacts=(selection_crop, *crop_refs))
    inputs = tuple(a for a in final.artifacts if a.kind in {"canonical_source_page", "selection_crop", "formula_crop"})
    outputs = tuple(a for a in final.artifacts if a.kind.startswith("provider_"))
    ledger = ExtractionAttemptLedger.for_context(initial).append(initial, ExtractionAttemptRecord(
        attempt_id=f"attempt:paddle:{run_id}", base_context_id=initial.manifest.context_id,
        provider="paddle_local_cpu", route="pending", input_artifact_refs=inputs,
        output_artifact_refs=outputs, result="succeeded",
        latency_ms=sum(r.record.latency_ms for r in runs), usage={"provider_record_count": len(outputs)}))
    masks = tuple(a for a in final.artifacts if a.kind == "handwriting_mask")
    if masks:
        ledger = ledger.append(initial, ExtractionAttemptRecord(attempt_id=f"attempt:ink:{run_id}",
            base_context_id=initial.manifest.context_id, provider="local_cv", route="pending",
            input_artifact_refs=tuple(a for a in final.artifacts if a.kind in {"canonical_source_page", "provider_text_ocr"}),
            output_artifact_refs=masks, result="succeeded", latency_ms=0, usage={"page_count": len(masks)}))
    context = ObservationContextTransitionService().attach(initial, final.observation,
        artifacts=final.artifacts, attempt_ledger=ledger)
    store.add(run_id, "observation", "output", "SourceObservation", final.observation.to_payload())
    store.add(run_id, "observation", "output", "Observation Context", context.to_payload())
    store.add(run_id, "observation", "validation", "观察校验", {"ok": True, "issues": [i.to_payload() for i in final.observation.issues]})
    for ref in final.artifacts:
        if ref.media_type.startswith("image/"):
            store.add(run_id, "observation", "output", ref.kind, artifacts.read_bytes(ref), ref.media_type)
    work = store.root / run_id / "work"
    work.mkdir(exist_ok=True)
    (work / "contexts.json").write_text(json.dumps({"initial": initial.to_payload(), "observation": context.to_payload()}))
    store.stage(run_id, "observation", "succeeded", "版面、文字、公式与观察 Context 已生成")


if __name__ == '__main__':
    directory, identity, phase = sys.argv[1:]
    journal = ObservationJournal(directory, identity, phase)
    run(journal, Path(directory).name, phase)
