"""Files reuse and real provider-message assembly, without paid inference."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_deepseek_vision import request_fixture, response
from test_math_notation_workflow import OK, candidate, finding, setup

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.review_contract import (
    review_family_context,
    review_schema,
)
from shuxueshuo_server.problem_understanding.workflow import frozen_files, run_workflow
from shuxueshuo_server.problem_understanding.workflow_ledger import (
    Budget,
    Ledger,
    WorkflowStop,
)
from shuxueshuo_server.solver.extraction.deepseek_files import save_json
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider,
    MultimodalProviderError,
    problem_domain_family_catalog,
)


class Server:
    def __init__(self, *outputs, upload_error=None, mutate_upload=lambda x: x):
        self.outputs = list(outputs)
        self.uploads, self.calls, self.inits = [], [], []
        self.upload_error, self.mutate_upload = upload_error, mutate_upload

    def factory(self, **kwargs):
        self.inits.append(kwargs)
        return SimpleNamespace(
            files=SimpleNamespace(create=self.upload),
            chat=SimpleNamespace(completions=SimpleNamespace(create=self.complete)),
        )

    def upload(self, **kwargs):
        self.uploads.append(kwargs)
        if self.upload_error:
            raise self.upload_error
        return self.mutate_upload(
            {
                "id": f"file-api-{len(self.uploads)}",
                "bytes": len(kwargs["file"][1]),
                "purpose": "user_data",
                "expires_at": int(time.time()) + 86400,
            }
        )

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        value = self.outputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return response(value if isinstance(value, str) else json.dumps(value))


def provider(tmp_path, server, **kwargs):
    return DeepSeekMultimodalExtractionProvider(
        api_key=kwargs.pop("api_key", "test-secret"),
        base_url=kwargs.pop("base_url", "https://api.deepseek.com"),
        file_cache_dir=tmp_path / "cache",
        client_factory=server.factory,
        sleeper=lambda _: None,
        **kwargs,
    )


def file_parts(call):
    return [p for p in call["messages"][1]["content"] if p["type"] == "file"]


def test_prepare_is_pure_and_unresolved_file_requests_cannot_be_sent(tmp_path):
    _, request = request_fixture(tmp_path)
    server = Server()
    model = provider(tmp_path, server)
    prepared = model.prepare_request(request)
    assert prepared.image_transport == "files"
    assert not server.uploads and not (tmp_path / "cache").exists()
    assert revision(prepared.redacted_payload()) == revision(
        model.prepare_request(prepared).redacted_payload()
    )
    assert revision(
        replace(prepared, transport_audit_directory="elsewhere").redacted_payload()
    ) == revision(prepared.redacted_payload())
    with pytest.raises(ValueError, match="unresolved"):
        prepared.provider_messages()
    assert "test-secret" not in json.dumps(prepared.redacted_payload())


def test_extract_review_repair_reuses_upload_and_sends_full_review_schema(tmp_path):
    registry = list(problem_domain_family_catalog())
    request = setup(tmp_path, registry)
    original, fixed = candidate(["t>0"]), candidate(["t>0", "t>1"])
    server = Server(original, finding(), fixed, OK)
    model = provider(tmp_path, server)
    result = run_workflow(
        request, model, tmp_path / "run", registry, problem_id="synthetic"
    )
    assert result["source_reviewed"] is True
    assert len(server.uploads) == 1 and len(server.calls) == 4
    assert all(
        file_parts(call) == [{"type": "file", "file_id": "file-api-1"}]
        for call in server.calls
    )
    assert all("data:image/" not in json.dumps(call) for call in server.calls)
    assert server.uploads[0]["file"][1] == request.images[0].content
    assert server.uploads[0]["purpose"] == "user_data"
    assert server.uploads[0]["expires_after"] == {
        "anchor": "created_at",
        "seconds": 86400,
    }
    for call in (server.calls[1], server.calls[3]):
        payload = json.loads(call["messages"][1]["content"][0]["text"])
        for key, value in review_family_context(registry).items():
            assert payload[key] == value
        assert "path_minimum_target" not in json.dumps(call, ensure_ascii=False)
        assert "source_conditions/source_conflicts" in call["messages"][0]["content"]
        assert payload["response_schema"] == review_schema()
        assert payload["response_schema"]["properties"]["status"]["enum"] == [
            "confirmed",
            "correction_required",
            "uncertain",
        ]
        assert payload["response_schema"][
            "allOf"
        ]  # Status/findings cross-field constraints.
        assert "完整的复核 JSON Schema" in call["messages"][0]["content"]
        assert (
            not {"gold", "answers", "acceptance_policy", "reasoning_content"}
            & payload.keys()
        )
    for call in (server.calls[0], server.calls[2]):
        payload = json.loads(call["messages"][1]["content"][0]["text"])
        assert payload["registered_families"] == registry
        assert "family_review_scope" not in payload
    payloads = [
        json.loads(p.read_text())
        for p in sorted(
            (tmp_path / "run/calls").glob("*/provider-attempts/01-request.json")
        )
    ]
    assert len(payloads) == 4
    for audit in payloads:
        image = next(p for p in audit["messages"][1]["content"] if p["type"] == "file")
        assert image["file_id"] == "file-api-1"
        assert image["image"]["sha256"] == request.images[0].artifact.sha256
    ledger = json.loads((tmp_path / "run/ledger.json").read_text())
    assert [e["file_api_calls"] for e in ledger["calls"]] == [1, 0, 0, 0]
    assert sum(e["network_attempts"] for e in ledger["calls"]) == 4
    # A completed run restores responses without resolving or uploading files again.
    restored = provider(tmp_path, Server())
    replay = run_workflow(
        request, restored, tmp_path / "run", registry, problem_id="synthetic"
    )
    assert replay["source_reviewed"] is True
    assert not restored.last_file_operations
    assert "solver/extraction/deepseek_files.py" in frozen_files()["implementation"]


@pytest.mark.parametrize("scope_change", ["none", "key", "endpoint", "image"])
def test_cache_reuse_survives_new_provider_and_isolates_identity(
    tmp_path, scope_change
):
    _, request = request_fixture(tmp_path)
    server = Server({}, {})
    first = provider(tmp_path, server)
    first.complete(request)
    options = (
        {"api_key": "other-secret"}
        if scope_change == "key"
        else (
            {"base_url": "https://separate.example"}
            if scope_change == "endpoint"
            else {}
        )
    )
    if scope_change == "image":
        # Trailing PNG bytes change source identity without changing decoded pixels.
        from hashlib import sha256

        image = request.images[0]
        content = image.content + b"changed"
        image = replace(
            image,
            content=content,
            artifact=replace(image.artifact, sha256=sha256(content).hexdigest()),
        )
        request = replace(
            request,
            images=(image,),
            evidence_pack=replace(
                request.evidence_pack,
                images=(
                    replace(request.evidence_pack.images[0], artifact=image.artifact),
                ),
            ),
        )
    provider(tmp_path, server, **options).complete(request)
    assert len(server.uploads) == (1 if scope_change == "none" else 2)
    assert all(i["max_retries"] == 0 for i in server.inits)
    for cached in (tmp_path / "cache").rglob("*.json"):
        assert "secret" not in cached.read_text()


def test_expiry_refresh_and_stale_invalidation_preserve_new_file(tmp_path):
    _, request = request_fixture(tmp_path)
    server = Server({}, {}, {})
    model = provider(tmp_path, server)
    model.complete(request)
    path = next((tmp_path / "cache").rglob("*.json"))
    cached = json.loads(path.read_text())
    save_json(path, {**cached, "expires_at": time.time() + 60})
    model.complete(request)
    model._file_cache.invalidate(cached["sha256"], cached["file_id"], [])
    model.complete(request)
    assert len(server.uploads) == 2
    assert file_parts(server.calls[-1])[0]["file_id"] == "file-api-2"


def test_concurrent_providers_upload_once(tmp_path):
    _, request = request_fixture(tmp_path)
    server = Server({}, {}, {})
    models = [provider(tmp_path, server) for _ in range(3)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda m: m.complete(request), models))
    assert len(server.uploads) == 1 and len(results) == 3
    assert all(file_parts(call)[0]["file_id"] == "file-api-1" for call in server.calls)


@pytest.mark.parametrize(
    "failure", ["upload", "bad_id", "bad_size", "bad_purpose", "bad_expiry"]
)
def test_upload_failures_are_audited_and_never_infer_or_retry(tmp_path, failure):
    _, request = request_fixture(tmp_path)
    edits = {
        "bad_id": {"id": "invalid"},
        "bad_size": {"bytes": 0},
        "bad_purpose": {"purpose": "other"},
        "bad_expiry": {"expires_at": None},
    }
    server = Server(
        upload_error=TimeoutError("contains test-secret")
        if failure == "upload"
        else None,
        mutate_upload=lambda value: {**value, **edits.get(failure, {})},
    )
    model = provider(tmp_path, server)
    with Ledger(tmp_path / "run", {"test": True}, Budget()) as ledger:
        with pytest.raises(WorkflowStop, match="provider_failed"):
            ledger.complete("extract", request, None, model)
        assert ledger.counts()["network_attempts"] == 0
        assert ledger.counts()["file_api_calls"] == 1
    assert not server.calls and len(server.uploads) == 1
    assert not list((tmp_path / "cache").rglob("*.json"))
    events = json.loads(
        (tmp_path / "run/calls/01-extract/file-operations.json").read_text()
    )
    assert events[0]["status"] == "failed"
    assert "test-secret" not in json.dumps(events)
    with (
        Ledger(tmp_path / "run", {"test": True}, Budget()) as ledger,
        pytest.raises(WorkflowStop),
    ):
        ledger.complete("extract", request, None, model)
    assert (
        len(server.uploads) == 1
    )  # Failure recovery cannot silently re-upload/rebill.


@pytest.mark.parametrize(
    "code,expected_attempts,expected_uploads",
    [
        ("file_not_found", 2, 2),
        ("file_expired", 2, 2),
        ("model_not_found", 1, 1),
        ("invalid_request", 1, 1),
        ("timeout", 2, 1),
    ],
)
def test_only_explicit_file_failures_refresh_within_two_attempt_budget(
    tmp_path, code, expected_attempts, expected_uploads
):
    _, request = request_fixture(tmp_path)
    error = (
        TimeoutError("timeout") if code == "timeout" else Exception("transport failed")
    )
    if code != "timeout":
        error.status_code = 404
        error.body = {"error": {"code": code, "message": code}}
    server = Server(error, {})
    model = provider(tmp_path, server)
    if expected_attempts == 1:
        with pytest.raises(MultimodalProviderError):
            model.complete(request)
    else:
        model.complete(request)
    assert len(server.calls) == expected_attempts
    assert len(server.uploads) == expected_uploads
    assert len(model.last_provider_attempts) == expected_attempts


def test_repeated_expired_response_stops_after_two_chat_attempts(tmp_path):
    _, request = request_fixture(tmp_path)
    error = Exception("expired")
    error.status_code = 400
    error.body = {"error": {"code": "file_expired"}}
    server = Server(error, error)
    with pytest.raises(MultimodalProviderError):
        provider(tmp_path, server).complete(request)
    assert len(server.uploads) == len(server.calls) == 2


def test_invalid_local_hash_rejected_before_file_api(tmp_path):
    _, request = request_fixture(tmp_path)
    request = replace(request, images=(replace(request.images[0], content=b"wrong"),))
    server = Server()
    with pytest.raises(MultimodalProviderError, match="hash"):
        provider(tmp_path, server).complete(request)
    assert not server.calls and not server.uploads


def test_real_sdk_serializes_file_upload_and_chat_reference(tmp_path):
    import httpx
    from openai import OpenAI

    _, request = request_fixture(tmp_path)
    requests = []

    def receive(req):
        requests.append(req)
        if req.url.path == "/files":
            assert req.headers["content-type"].startswith("multipart/form-data;")
            assert request.images[0].content in req.content
            assert b'name="expires_after[anchor]"' in req.content
            assert b'name="expires_after[seconds]"' in req.content
            return httpx.Response(
                200,
                json={
                    "id": "file-api-sdk",
                    "object": "file",
                    "filename": "image.png",
                    "bytes": len(request.images[0].content),
                    "purpose": "user_data",
                    "created_at": int(time.time()),
                    "expires_at": int(time.time()) + 86400,
                },
            )
        assert req.url.path == "/chat/completions"
        data = json.loads(req.content)
        assert file_parts(data) == [{"type": "file", "file_id": "file-api-sdk"}]
        assert "base64" not in req.content.decode()
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "{}"},
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(receive)) as client:
        model = DeepSeekMultimodalExtractionProvider(
            api_key="test-secret",
            base_url="https://api.deepseek.com",
            file_cache_dir=tmp_path / "cache",
            client_factory=lambda **opts: OpenAI(**opts, http_client=client),
        )
        assert model.complete(request).text == "{}"
    assert len(requests) == 2


def test_multipage_file_refs_preserve_input_order(tmp_path):
    from _problem_extraction_f3_support import make_multi_page_f3_fixture

    from shuxueshuo_server.solver.extraction.multimodal_provider import (
        build_multimodal_provider_request,
    )

    _, _, store, pack = make_multi_page_f3_fixture(tmp_path)
    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="multipage",
        response_format_mode="json_object",
    )
    server = Server({})
    result = provider(tmp_path, server).complete(request)
    bindings = result.metadata_payload()["image_files"]
    assert [b["sha256"] for b in bindings] == [
        i.artifact.sha256 for i in request.images
    ]
    assert [p["file_id"] for p in file_parts(server.calls[0])] == [
        b["file_id"] for b in bindings
    ]


@pytest.mark.parametrize("mode", [None, "files", "base64"])
def test_live_math_factory_selects_transport_without_network(
    tmp_path, monkeypatch, mode
):
    from shuxueshuo_server.problem_understanding import batch_smoke

    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *_: None)
    monkeypatch.setattr(batch_smoke, "REPO", tmp_path)
    model = batch_smoke.live_provider_factory(image_transport=mode)()
    if mode == "base64":
        assert model.file_cache_dir is None and model._file_cache is None
    else:
        assert (
            model.file_cache_dir
            == tmp_path / "internal/solver-runs/.deepseek-files-cache"
        )
        assert not model.file_cache_dir.exists()


def test_doubao_rejects_files_mode_before_calling_any_provider():
    from shuxueshuo_server.problem_understanding.batch_smoke import (
        live_provider_factory,
    )

    with pytest.raises(ValueError, match="base64 image transport only"):
        live_provider_factory("doubao", image_transport="files")
