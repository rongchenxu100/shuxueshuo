from io import BytesIO
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from shuxueshuo_server.review.api import router
from shuxueshuo_server.review.store import ReviewStore, STAGES, normalize_image, MAX_BYTES
from shuxueshuo_server.review.worker import execute
from shuxueshuo_server.review.pipeline import AuditedClient


def image_bytes():
    out = BytesIO()
    Image.new("RGB", (40, 30), "white").save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def service(tmp_path):
    store = ReviewStore(tmp_path)
    app = FastAPI()
    app.state.review_store = store
    app.include_router(router)
    return store, TestClient(app)


def create(client):
    response = client.post("/api/review/runs", files={"image": ("problem.png", image_bytes(), "image/png")})
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def test_upload_persistent_identity_and_rerun(service):
    store, client = service
    run_id = create(client)
    doc = ReviewStore(store.root).get(run_id)
    assert doc["status"] == "queued"
    assert len(doc["stages"]) == 9
    original = doc["artifacts"][0]
    assert client.get(original["url"]).content == image_bytes()
    second = client.post(f"/api/review/runs/{run_id}/rerun").json()["run_id"]
    new = store.get(second)
    assert new["parent_run_id"] == run_id
    assert new["artifacts"][0]["sha256"] == original["sha256"]
    assert new["artifacts"][0]["id"] != original["id"]
    assert client.get(f"/api/review/runs/{second}/artifacts/{original['id']}").status_code == 404


@pytest.mark.parametrize("media,body", [("image/svg+xml", b"<svg/>"), ("image/jpeg", image_bytes()),
    ("image/png", b"broken"), ("image/png", b"x" * (MAX_BYTES + 1))])
def test_invalid_upload(service, media, body):
    store, client = service
    response = client.post("/api/review/runs", files={"image": ("image", body, media)})
    assert response.status_code in {413, 422}
    assert not store.list()


def test_image_pixel_limit(monkeypatch):
    monkeypatch.setattr("shuxueshuo_server.review.store.MAX_PIXELS", 100)
    with pytest.raises(ValueError, match="像素"):
        normalize_image(image_bytes(), "image/png")


@pytest.mark.parametrize("failed_stage", [s[0] for s in STAGES])
def test_stage_failures_preserve_evidence_and_block_downstream(service, failed_stage):
    store, client = service
    run_id = create(client)
    assert store.claim() == run_id
    def pipeline(store, run_id):
        for key, _ in STAGES:
            store.stage(run_id, key, "running")
            store.add(run_id, key, "input", "实际输入", {"stage": key})
            if key == failed_stage:
                raise ValueError("example failure")
            store.stage(run_id, key, "succeeded")
    execute(store, run_id, pipeline)
    doc = store.get(run_id)
    assert doc["status"] == "failed" and doc["page_url"] is None
    position = [s[0] for s in STAGES].index(failed_stage)
    assert all(s["status"] == "succeeded" for s in doc["stages"][:position])
    assert doc["stages"][position]["status"] == "failed"
    assert all(s["status"] == "blocked" for s in doc["stages"][position + 1:])
    assert any(a["stage"] == failed_stage for a in doc["artifacts"])
    assert client.get(f"/api/review/runs/{run_id}/page/lesson.html").status_code == 404


def test_events_resume_and_worker_restart(service):
    store, client = service
    run_id = create(client)
    store.claim()
    store.stage(run_id, "source", "running")
    cursor = store.events(run_id)[-1]["seq"]
    store.interrupt_unfinished()
    assert store.get(run_id)["status"] == "interrupted"
    assert store.claim() is None
    result = client.get(f"/api/review/runs/{run_id}/events", headers={"Last-Event-ID": str(cursor)})
    assert "interrupted" in result.text and "event: done" in result.text
    ids = [int(line[4:]) for line in result.text.splitlines() if line.startswith("id: ")]
    assert ids and min(ids) > cursor
    assert client.get(f"/api/review/runs/{run_id}/events?after=no").status_code == 422


def test_success_requires_all_stages_and_sandboxed_page(service):
    store, client = service
    run_id = create(client)
    store.claim()
    with pytest.raises(ValueError, match="incomplete"):
        store.finish(run_id)
    for key, _ in STAGES:
        store.stage(run_id, key, "running")
        store.stage(run_id, key, "succeeded")
    with pytest.raises(ValueError, match="missing compiled"):
        store.finish(run_id)
    ref = store.add(run_id, "page", "output", "lesson.html", b"<html>ok</html>", "text/html", page_path="lesson.html")
    store.finish(run_id)
    result = client.get(store.get(run_id)["page_url"])
    assert result.status_code == 200
    assert "sandbox allow-scripts" in result.headers["content-security-policy"]
    assert "allow-same-origin" not in result.headers["content-security-policy"]
    assert client.get(ref["url"]).headers["content-type"].startswith("text/plain")


def test_redaction_integrity_and_origin(service):
    store, client = service
    run_id = create(client)
    store.secrets = ("this-is-a-test-secret",)
    ref = store.add(run_id, "solver", "input", "payload", {"api_key": "secret", "text": "this-is-a-test-secret", "authorization": "Bearer foo"})
    body = client.get(ref["url"]).text
    assert "this-is-a-test-secret" not in body and '"secret"' not in body
    assert client.get(ref["url"], headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.get(ref["url"], headers={"Host": "evil.example"}).status_code == 403
    assert client.get(f"/api/review/runs/{run_id}/artifacts/..%2F..%2F.env").status_code == 404
    path = store.root / run_id / "artifacts" / ref["id"]
    path.write_bytes(b"tampered")
    assert client.get(ref["url"]).status_code == 409


def test_client_failure_does_not_fabricate_raw_response(service):
    store, client = service
    run_id = create(client)
    class FailingClient:
        provider_name = "test"
        model = "test-model"
        def complete(self, request):
            raise RuntimeError("provider unavailable")
    audit = AuditedClient(FailingClient(), store, run_id, "lesson")
    with pytest.raises(RuntimeError):
        audit.complete({"messages": [{"role": "user", "content": "input"}]})
    refs = [a for a in store.get(run_id)["artifacts"] if a["stage"] == "lesson"]
    assert [a["role"] for a in refs] == ["input", "call"]
    _, raw = store.read(run_id, refs[-1]["id"])
    assert json.loads(raw)["usage"] is None
    assert json.loads(raw)["visible_response"] is False


def test_no_fixture_or_review_harness_in_production_adapters():
    root = Path(__file__).resolve().parents[1] / "shuxueshuo_server/review"
    for name in ("pipeline.py", "ocr.py"):
        text = (root / name).read_text()
        assert "import GoldCorpusCase" not in text
        assert "import build_f0_extraction_context_seed" not in text
        assert "import build_recursive_lesson_review" not in text
        assert "tests/solver/" not in text


def test_handoff_failure_is_visible_and_terminal_artifacts_are_immutable(service):
    store, client = service
    run_id = create(client)
    store.claim()
    store.stage(run_id, "source", "running")
    store.stage(run_id, "source", "succeeded")
    store.finish(run_id, error="context handoff failed")
    doc = store.get(run_id)
    assert doc["error"] == "context handoff failed"
    assert doc["stages"][1]["status"] == "failed"
    with pytest.raises(ValueError, match="terminal"):
        store.add(run_id, "source", "output", "late", {})


def test_missing_config_fails_before_ocr_or_any_provider(service, monkeypatch):
    from types import SimpleNamespace
    from shuxueshuo_server.review.pipeline import generate
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    store, client = service
    run_id = create(client)
    store.claim()
    monkeypatch.setattr(SolverRuntimeConfig, "from_sources", lambda **kwargs: SimpleNamespace(deepseek_api_key=None, doubao_api_key=None))
    execute(store, run_id, generate)
    doc = store.get(run_id)
    assert "configuration.missing" in doc["error"]
    assert doc["stages"][0]["status"] == "failed"
    assert not any(a["role"] == "raw" for a in doc["artifacts"])


def test_uploaded_image_observation_roundtrip_keeps_whole_crop_authority(service, monkeypatch):
    from shuxueshuo_server.review.ocr import run
    from shuxueshuo_server.solver.extraction import paddle_worker
    from shuxueshuo_server.solver.extraction.observations import PaddleProviderRecord, ProviderManifest
    from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
    class LocalTestWorker:
        def manifests(self):
            return tuple(ProviderManifest.create(provider="test", component=c, model_name=c,
                model_revision="test-v1", software_versions={"test": "1"}, config={})
                for c in ("layout", "text_ocr", "formula_ocr"))
        def record(self, component, source_revision_hash, page_id, **kwargs):
            provider = next(p for p in self.manifests() if p.component == component)
            items = ({"text": "Find the vertex", "confidence": .99,
                      "polygon": [[1, 1], [38, 1], [38, 28], [1, 28]]},) if component == "text_ocr" else ()
            record = PaddleProviderRecord.create(component=component, provider=provider,
                source_revision_hash=source_revision_hash, page_id=page_id,
                width=40, height=30, items=items, latency_ms=1)
            return paddle_worker.PaddleProviderRun(record, ({"test": True},))
        def layout(self, **kwargs): return self.record("layout", **kwargs)
        def text(self, **kwargs): return self.record("text_ocr", **kwargs)
        def formulas(self, **kwargs): return self.record("formula_ocr", **kwargs)
    monkeypatch.setattr(paddle_worker, "PaddleF2ProviderWorker", LocalTestWorker)
    store, client = service
    run_id = create(client)
    store.claim()
    run(store, run_id)
    saved = json.loads((store.root / run_id / "work/contexts.json").read_text())
    initial = ProblemExtractionContext.from_payload(saved["initial"])
    child = ProblemExtractionContext.from_payload(saved["observation"], ancestor_contexts=(initial,))
    crop = next(a for a in child.state.artifacts if a.kind == "selection_crop")
    assert ExtractionArtifactStore(store.root / run_id / "extraction-artifacts").read_bytes(crop) == normalize_image(image_bytes(), "image/png")
    assert child.manifest.parent_context_id == initial.manifest.context_id
    assert initial.selection.regions[0].polygon == ((0., 0.), (1., 0.), (1., 1.), (0., 1.))


def test_debug_journal_publishes_versions_not_half_written_json(tmp_path):
    from shuxueshuo_server.review.pipeline import DebugJournal
    recorded = []
    journal = DebugJournal(tmp_path, lambda name, doc: recorded.append((name, doc)))
    path = tmp_path / "attempt-1.json"
    path.write_text('{"partial":')
    journal.scan()
    assert recorded == []
    path.write_text('{"status":"running"}')
    journal.scan()
    journal.scan()
    path.write_text('{"status":"verified"}')
    journal.scan()
    assert [doc["status"] for _, doc in recorded] == ["running", "verified"]


def test_registered_dependencies_form_one_run_closure(service):
    store, client = service
    run_id = create(client)
    first = store.get(run_id)["artifacts"][0]
    with pytest.raises(ValueError, match="dependencies"):
        store.add(run_id, "page", "output", "foreign", {}, dependencies=["unknown"])
    ref = store.add(run_id, "source", "validation", "bytes log", b'Bearer sensitive-token', "text/plain")
    assert b'sensitive-token' not in store.read(run_id, ref["id"])[1]
    assert first["id"] in ref["dependencies"]
    assert ref["id"] in store.get(run_id)["stages"][0]["validation_refs"]


def test_page_inspection_ignores_source_comments_and_rejects_external_scripts():
    from shuxueshuo_server.review.pipeline import inspect_page
    inspect_page(b'<script>/* example <script src="x"><\\/script> */</script><style>/* <link rel="stylesheet"> */</style>')
    with pytest.raises(ValueError, match="external_dependency"):
        inspect_page(b'<script src="https://evil.example"></script>')


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    from shuxueshuo_server.review import pipeline
    root = tmp_path / 'source'
    style = root / 'internal/config/style-presets.json'
    style.parent.mkdir(parents=True)
    style.write_text('{}')
    for name in ['internal/llm-prompts/shared/rules.jinja', 'internal/schemas/nested/plan.json']:
        path = root / name
        path.parent.mkdir(parents=True)
        path.write_text('original')
    monkeypatch.setattr(pipeline, 'REPO', root)
    return root


@pytest.mark.parametrize('name', ['internal/llm-prompts/shared/rules.jinja', 'internal/schemas/nested/plan.json'])
@pytest.mark.parametrize('operation', ['edit', 'add', 'delete', 'rename'])
def test_source_version_tracks_prompt_and_schema_tree_changes(source_tree, name, operation):
    from shuxueshuo_server.review.pipeline import source_version
    path = source_tree / name
    before = source_version()
    assert source_version() == before
    if operation == 'edit':
        path.write_text('modified')
    elif operation == 'add':
        path.with_name('new-' + path.name).write_text('original')
    elif operation == 'delete':
        path.unlink()
    else:
        path.rename(path.with_name('renamed-' + path.name))
    assert source_version() != before


def test_source_version_ignores_review_artifacts_and_timestamps(source_tree):
    from shuxueshuo_server.review.pipeline import source_version
    import os
    before = source_version()
    os.utime(source_tree / 'internal/llm-prompts/shared/rules.jinja', (1, 1))
    artifact = source_tree / 'internal/review-runs/run/artifact.json'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('new output')
    assert source_version() == before


def seed_visual_parent(store, client):
    run_id = create(client)
    store.claim()
    for key, _ in STAGES[:7]:
        store.stage(run_id, key, "running")
        if key in {"evidence", "lesson"}:
            filename, name = ("snapshot.json", "ExplanationSnapshot") if key == "evidence" else ("lesson.json", "LessonIR（实际采用）")
            source = Path(__file__).parent / "solver/fixtures/anonymous_point_visual" / filename
            store.add(run_id, key, "output", name, json.loads(source.read_text()))
        from shuxueshuo_server.review import dependencies as deps
        from shuxueshuo_server.review.replay import find
        for inputs in deps.INPUTS.values():
            for owner, name in inputs:
                if owner == key and not find(store.get(run_id), owner, name):
                    store.add(run_id, owner, "output", name, {"graph": {"problem_id": run_id}, "semantic_hash": "fixture"})
        store.stage(run_id, key, "succeeded")
        with store.edit(run_id) as doc:
            next(s for s in doc["stages"] if s["id"] == key)["manifest"] = deps.manifest(doc, key, deps.probe())
    store.stage(run_id, "visual", "running")
    store.finish(run_id, error="old visual failure")
    return run_id


@pytest.mark.parametrize('name', ['internal/llm-prompts/shared/rules.jinja', 'internal/schemas/nested/plan.json'])
def test_prompt_or_schema_change_during_build_blocks_page_registration(service, source_tree, monkeypatch, name):
    from types import SimpleNamespace
    from shuxueshuo_server.review import pipeline

    from shuxueshuo_server.review import dependencies as deps
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    monkeypatch.setattr(deps, "probe", lambda: deps.collect(source_tree, SolverRuntimeConfig()))
    store, client = service
    parent = seed_visual_parent(store, client)
    child = store.rerun(parent, from_stage='visual')['id']
    assert store.claim() == child
    def compile_with_source_change(*args, **kwargs):
        # No providers: the visual inputs are verified recordings. Simulate a
        # prompt/schema edit while the page compiler is running.
        (source_tree / name).write_text('changed during compilation')
        return SimpleNamespace(returncode=0, stdout='', stderr='')
    monkeypatch.setattr(pipeline.subprocess, 'run', compile_with_source_change)
    execute(store, child, pipeline.generate)
    doc = store.get(child)
    assert doc['status'] == 'failed'
    assert 'build.source_changed' in doc['error']
    assert not any(a['stage'] == 'page' and a['role'] == 'output' for a in doc['artifacts'])
    assert not any(a['name'] == '页面资源与版本一致性' for a in doc['artifacts'])


def test_stage_rerun_compiles_real_recording_without_any_provider(service, monkeypatch):
    from shuxueshuo_server.review.pipeline import generate
    store, client = service
    parent = seed_visual_parent(store, client)
    frozen = store.get(parent)
    def forbidden(*args, **kwargs):
        raise AssertionError("stage replay must not call a provider")
    monkeypatch.setattr(AuditedClient, "complete", forbidden)
    option = client.get(f"/api/review/runs/{parent}").json()["rerun_options"]
    assert option["visual"]["available"]
    assert not option["page"]["available"]
    assert not option["evidence"]["available"]
    response = client.post(f"/api/review/runs/{parent}/rerun?from_stage=visual")
    assert response.status_code == 202, response.text
    child = response.json()["run_id"]
    assert store.claim() == child
    execute(store, child, generate)
    generated = store.get(child)
    assert generated["status"] == "succeeded", generated.get("error")
    assert store.get(parent) == frozen
    assert all(s.get("reused_from_run_id") == parent for s in generated["stages"][:7])
    assert not any(a["role"] in {"call", "raw"} and not a.get("reused_from") for a in generated["artifacts"])
    ids = {a["id"] for a in generated["artifacts"]}
    assert all(set(a["dependencies"]) <= ids for a in generated["artifacts"])
    page_run = client.post(f"/api/review/runs/{child}/rerun?from_stage=page").json()["run_id"]
    assert store.claim() == page_run
    execute(store, page_run, generate)
    assert store.get(page_run)["status"] == "succeeded", store.get(page_run).get("error")
    assert all(a.get("reused_from") for a in store.get(page_run)["artifacts"] if a["stage"] == "visual")


def test_stage_rerun_rejects_missing_inputs_and_tampered_artifacts(service):
    store, client = service
    parent = seed_visual_parent(store, client)
    assert client.post(f"/api/review/runs/{parent}/rerun?from_stage=page").status_code == 409
    assert client.post(f"/api/review/runs/{parent}/rerun?from_stage=unknown").status_code == 409
    ref = next(a for a in store.get(parent)["artifacts"] if a["stage"] == "lesson")
    (store.root / parent / "artifacts" / ref["id"]).write_text("corrupt")
    assert client.post(f"/api/review/runs/{parent}/rerun?from_stage=visual").status_code == 409
    assert not any(r["status"] == "queued" for r in store.list())


def test_extraction_checkpoint_restores_content_without_historical_locator(tmp_path):
    from shuxueshuo_server.review.replay import archive_bytes, extraction_store, restore_archive, ARCHIVE
    from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
    store = ReviewStore(tmp_path / "review")
    run = store.create(image_bytes(), "image/png", "p.png")["id"]
    old = ExtractionArtifactStore(tmp_path / "old")
    ref = old.put_bytes(kind="crop", content=b"image-evidence", media_type="image/png", suffix=".png")
    journal = old.root / "_authority/attempt-ledgers"
    journal.mkdir(parents=True)
    (journal / "process.lock").touch()
    (journal / "journal.json").write_text('{"attempt": 3}')
    store.add(run, "observation", "output", ARCHIVE, archive_bytes(old.root), "application/zip")
    restore_archive(store, run, "observation")
    assert not (store.root / run / "extraction-artifacts/_authority").exists()
    Path(ref.locator).unlink()
    assert extraction_store(store.root / run / "extraction-artifacts").read_bytes(ref) == b"image-evidence"


@pytest.mark.parametrize('kind,role', [
    ('raw-response', 'raw'), ('functional-plan', 'raw'), ('provider-reasoning', 'raw'),
    ('request', 'input'), ('base-plan', 'input'), ('provider-requests', 'input'),
    ('normalized-response', 'output'), ('candidate-plan', 'output'), ('canonical-plan', 'output'),
    ('checkpoint', 'validation'), ('transaction', 'validation'), ('evidence-index', 'validation'),
])
def test_solver_journal_preserves_artifact_roles(kind, role):
    from shuxueshuo_server.review.pipeline import solver_debug_role
    assert solver_debug_role(f'attempt-2.{kind}.json') == role
