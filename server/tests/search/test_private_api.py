"""Authenticated search boundaries with a real isolated PostgreSQL database."""

import secrets
import time
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from shuxueshuo_server.auth.api import cookie_name, install_auth
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthService
from shuxueshuo_server.auth.sms import MockSms
from shuxueshuo_server.graph_lesson.stage_three.checkpoint import identity_from_seed
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from tests.search.test_identity import public_candidate, reviewed_result
from tests.search.test_repository import repository as repository_fixture
from tests.search.test_repository import submission


@pytest.fixture
def repository(tmp_path):
    yield from repository_fixture.__wrapped__(tmp_path)


@pytest.fixture
def private_app(repository, monkeypatch):
    repository.admission.set_generation_enabled(True)
    config = AuthConfig(mode="mock", environment="test", origin="https://testserver", session_seconds=90 * 86400,
                        secret=secrets.token_urlsafe(48))
    auth = AuthService(repository.db, config, MockSms(), clock=repository.clock)
    app = FastAPI()
    app.state.search_repository = repository
    install_auth(app, auth=auth)
    app.include_router(dev_api.create_search_router(repository.root))
    monkeypatch.setattr(dev_api.OcrClient, "observe", lambda *_args, **_kwargs: {
        "width": 100, "height": 100, "lines": [], "layout": [], "latency_ms": {"detect": 0},
    })
    return app, auth


def login(client, auth):
    phone = "139" + "".join(str(secrets.randbelow(10)) for _ in range(8))
    challenge = auth.send(phone, phone)
    code = auth.sms.messages[str(challenge["challenge_id"])][1]
    user, token = auth.verify(phone, challenge["challenge_id"], code, phone)
    client.cookies.set(cookie_name(auth.config), token)
    client.headers["Origin"] = auth.config.origin
    client.headers["X-Search-User"] = user["id"]
    return user, token


def upload(client):
    content = BytesIO()
    Image.new("RGB", (100, 100), "white").save(content, format="PNG")
    response = client.post("/api/search/pages", content=content.getvalue())
    assert response.status_code == 200, response.text
    return response.json()


def recorded_pipeline(monkeypatch, *, entered=None, release=None, verified=True):
    calls = []
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    def provider_factory(_name, *, file_cache_dir):
        # Containers mount the code tree read-only; the cache must live under the data root.
        assert file_cache_dir.name == "deepseek-files-cache"
        assert not file_cache_dir.is_relative_to(Path(dev_api.__file__).resolve().parents[3])
        return lambda: object()

    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory",
                        provider_factory)
    monkeypatch.setattr("shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory", lambda: object())

    def recognize(png, directory, _provider, *, problem_id, original_png=None, read_graph_details=False):
        calls.append(problem_id)
        if entered:
            entered.set()
            assert release.wait(10)
        result = reviewed_result(public_candidate())
        result.update(question_sha256=sha256(png).hexdigest(), sent_image_sha256=[sha256(png).hexdigest()],
                      review_findings=[], features=[], elapsed_seconds=0)
        save(directory / dev_api.RESULT_FILE, result)
        return result

    def classify(directory, *_args, **_kwargs):
        save(directory / "stage-two-1/stage-two-result.json", {"status": "resolved", "goals": [{"status": "resolved"}]})

    def finish(directory, **_kwargs):
        output = directory / "stage-three"
        seed = {"run_id": secrets.token_hex(16), "lesson_version": "offline-boundary-fixture",
                "stage_one": {"sha256": "a" * 64}, "stage_two": {"sha256": "c" * 64}}
        identity = {**identity_from_seed(seed), "revisions": {"fixture": "b" * 64}}
        save(output / "run.json", seed)
        save(output / "frozen.json", {"implementation": identity["revisions"]})
        EventStore(output, identity, create=True)
        save(directory / "stage-three/stage-three-result.json", {
            "status": "completed", "goals": [{"status": "solved", "routes": [{"status": "verified" if verified else "failed"}]}],
        })

    monkeypatch.setattr(dev_api, "run_question_image", recognize)
    monkeypatch.setattr(dev_api, "run_stage_two", classify)
    monkeypatch.setattr(dev_api.stage_three, "run_stage_three", finish)
    monkeypatch.setattr(dev_api, "present_lesson", lambda *_args, **_kwargs: {"status": "resolved", "goals": []})
    return calls


@pytest.mark.parametrize('change,expected', [('delete', 404), ('expire', 410), ('disable', 410)])
@pytest.mark.parametrize('endpoint', ['snapshot_url', 'events_url', 'websocket_url'])
@pytest.mark.parametrize('phase', ['open_store', 'read_run'])
def test_execution_snapshot_lifecycle_race_is_not_a_server_error(private_app, repository, monkeypatch, change, expected, endpoint, phase):
    recorded_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        search_id = client.post('/api/search/problems', json={
            'page_id': page['page_id'], 'box': [0, 0, 1, 1], 'client_request_id': 'snapshot-race',
        }).json()['search_id']
        row = wait_ready(repository, user, search_id)
        stream = client.get(f'/api/search/problems/{search_id}').json()['lesson']['stream']
        original = getattr(dev_api.stage_three, phase)
        changed = False

        def raced(output):
            nonlocal changed
            if changed:
                return original(output)
            changed = True
            if change == 'delete':
                repository.delete(user, search_id)
            elif change == 'expire':
                repository.test_time[0] = row['expires_at']
            else:
                repository.disable(row['problem_id'])
            return original(output)

        monkeypatch.setattr(dev_api.stage_three, phase, raced)
        if endpoint == 'websocket_url':
            from starlette.websockets import WebSocketDisconnect
            with pytest.raises(WebSocketDisconnect) as closed, client.websocket_connect(stream[endpoint]) as socket:
                socket.receive_json()
                socket.receive_json()
            assert closed.value.code == (4404 if expected == 404 else 4410)
        else:
            response = client.get(stream[endpoint])
            assert response.status_code == expected, response.text
            assert response.headers['cache-control'] == 'no-store'


def wait_ready(repo, user, search_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        row = repo.submission(user, search_id)
        if row["lesson_status"] == "ready":
            return row
        if row["recognition_status"] in {"failed", "needs_confirmation"} or row["lesson_status"] == "failed":
            pytest.fail(str(row))
        time.sleep(0.02)
    pytest.fail("search did not finish")


def test_all_http_routes_require_cookie_and_all_writes_require_origin(private_app):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        routes = [route for route in app.routes if isinstance(route, dev_api.SearchRoute)]
        assert len(routes) >= 14
        for route in routes:
            path = route.path.replace("{page_id}", "a" * 12).replace("{search_id}", "b" * 12).replace("{run_id}", "c" * 32)
            for method in route.methods:
                result = client.request(method, path, json={"page_id": "a" * 12, "box": [0, 0, 1, 1], "degrees": 90})
                assert result.status_code == 401, (method, path, result.text)
                assert result.headers["cache-control"] == "no-store"
        login(client, auth)
        client.headers["Origin"] = "https://other.example"
        for route in routes:
            path = route.path.replace("{page_id}", "a" * 12).replace("{search_id}", "b" * 12).replace("{run_id}", "c" * 32)
            for method in route.methods & {"POST", "PUT", "PATCH", "DELETE"}:
                result = client.request(method, path, json={"page_id": "a" * 12, "box": [0, 0, 1, 1], "degrees": 90})
                assert result.status_code == 403, (method, path, result.text)


def test_upload_model_submission_history_delete_and_expiry(private_app, repository, monkeypatch):
    calls = recorded_pipeline(monkeypatch)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        body = {"page_id": page["page_id"], "box": [0, 0, 1, 1], "client_request_id": "first-click"}
        first = client.post("/api/search/problems", json=body).json()["search_id"]
        assert client.post("/api/search/problems", json=body).json()["search_id"] == first
        wait_ready(repository, user, first)
        body["client_request_id"] = "second-click"
        second = client.post("/api/search/problems", json=body).json()["search_id"]
        wait_ready(repository, user, second)
        assert len(calls) == 2
        history = client.get("/api/search/problems").json()
        assert history["user_id"] == user["id"] and len(history["items"]) == 1
        assert history["items"][0]["lesson_available"]
        detail = client.get(f"/api/search/problems/{first}").json()
        assert detail["user_id"] == user["id"] and detail["problem_id"]
        assert "path" not in detail and "storage_key" not in detail
        repository.test_time[0] += timedelta(hours=24)
        assert client.get(page["image_url"]).status_code == 410
        assert client.get(f"/api/search/problems/{first}/image").status_code == 200
        repository.test_time[0] += timedelta(days=29)
        expired = client.get(f"/api/search/problems/{first}").json()
        assert expired["outcome"] == "expired" and expired["statement"] and expired["lesson"] is None
        assert client.get(f"/api/search/problems/{first}/image").status_code == 410
        deleted = client.delete(f"/api/search/problems/{first}").json()
        assert set(deleted["deleted_search_ids"]) == {first, second}
        assert client.get(f"/api/search/problems/{first}").status_code == 404
        assert client.get("/api/search/problems").json()["items"] == []


def test_cross_account_expected_user_and_legacy_directory_are_rejected(private_app, repository):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        first, _token = login(client, auth)
        page = upload(client)
        row, _ = submission(repository, first, page["page_id"])
        second, _token = login(client, auth)
        assert first != second
        for suffix in ("", "/image", "/figures", "/figures/original", "/lesson/" + "c" * 32 + "/snapshot"):
            assert client.get(f"/api/search/problems/{row['id']}{suffix}").status_code == 404
        assert client.get(page["image_url"]).status_code == 404
        assert client.delete(f"/api/search/problems/{row['id']}").status_code == 404
        client.headers["X-Search-User"] = first["id"]
        assert client.get("/api/search/problems").status_code == 409
        client.headers["X-Search-User"] = second["id"]
        legacy = repository.root / ("d" * 12) / "problems" / ("e" * 12)
        legacy.mkdir(parents=True)
        (legacy / "question.png").write_bytes(b"old private bytes")
        assert client.get("/api/search/problems/" + "e" * 12 + "/image").status_code == 404
        assert legacy.exists()


def test_private_figures_keep_high_fidelity_and_obey_lifecycle(private_app, repository):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner, _ = login(client, auth)
        row, _ = submission(repository, owner)
        repository.associate(row['id'], build_identity(reviewed_result(public_candidate())))
        save(row['path'] / 'crop.json', {'box': [0, 0, 1, 1]})
        original = row['path'] / 'original.png'
        Image.new('RGB', (240, 80), '#1258ab').save(original)
        base = f"/api/search/problems/{row['id']}"
        manifest = client.get(base + '/figures')
        assert manifest.status_code == 200
        assert manifest.headers['cache-control'] == 'no-store'
        assert client.get(base).json()['figures'] == manifest.json()
        url = manifest.json()['figures'][0]['image_url']
        image = client.get(url)
        assert image.content == original.read_bytes()
        assert image.headers['cache-control'] == 'no-store'
        assert client.get(base + '/image').content == (row['path'] / 'question.png').read_bytes()
        assert client.get(base + '/figures/unknown').status_code == 404
        assert client.get(base + '/figures/original?version=' + '0' * 64).status_code == 409
        repository.test_time[0] = row['expires_at']
        assert client.get(base + '/figures').status_code == 410
        assert client.get(url).status_code == 410
        repository.delete(owner, row['id'])
        assert client.get(base + '/figures').status_code == 404
        assert client.get(url).status_code == 404


def test_every_owned_http_and_websocket_route_rejects_other_account(private_app, repository):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner, _token = login(client, auth)
        page = upload(client)
        row, _ = submission(repository, owner, page["page_id"])
        login(client, auth)
        routes = [route for route in app.routes if isinstance(route, dev_api.SearchRoute)]
        for route in routes:
            if not ({"page_id", "search_id"} & set(route.param_convertors)):
                continue
            path = route.path.replace("{page_id}", page["page_id"]).replace("{search_id}", row["id"]).replace("{run_id}", "c" * 32)
            for method in route.methods:
                response = client.request(method, path, json={"degrees": 90})
                assert response.status_code == 404, (method, path, response.text)
                assert response.headers["cache-control"] == "no-store"
        assert client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]}).status_code == 404
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            f"/api/search/problems/{row['id']}/lesson/" + "c" * 32 + "/ws"
        ):
            pytest.fail("another account's socket accepted")
        assert repository.submission(owner, row["id"])["recognition_status"] == "queued"


@pytest.mark.parametrize("target", ["missing", "foreign"])
def test_unowned_http_identifiers_never_create_lock_files(private_app, repository, target):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner, _token = login(client, auth)
        page = upload(client)
        row, _ = submission(repository, owner, page["page_id"])
        login(client, auth)
        original = set(repository.storage.path("locks").iterdir())
        routes = [route for route in app.routes if isinstance(route, dev_api.SearchRoute)]
        for route in routes:
            if not ({"page_id", "search_id"} & set(route.param_convertors)):
                continue
            page_id = page["page_id"] if target == "foreign" else secrets.token_hex(6)
            search_id = row["id"] if target == "foreign" else secrets.token_hex(6)
            path = route.path.replace("{page_id}", page_id).replace("{search_id}", search_id).replace("{run_id}", "c" * 32)
            for method in route.methods:
                response = client.request(method, path, json={"degrees": 90})
                assert response.status_code == 404, (method, path, response.text)
                assert set(repository.storage.path("locks").iterdir()) == original, (method, path)


@pytest.mark.parametrize("suffix", ["", "/image", "/lesson/" + "c" * 32 + "/snapshot", "/lesson/" + "c" * 32 + "/events"])
def test_private_reads_recheck_deletion_after_acquiring_read_lock(private_app, repository, monkeypatch, suffix):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        owner, _token = login(client, auth)
        row, _ = submission(repository, owner)
        original_lock = repository.storage.read_lock

        def delete_before_lock(search_id, **kwargs):
            repository.delete(owner, search_id)
            return original_lock(search_id, **kwargs)

        monkeypatch.setattr(repository.storage, "read_lock", delete_before_lock)
        response = client.get(f"/api/search/problems/{row['id']}{suffix}")
        assert response.status_code == 404
        assert response.json() == {"detail": "search.not_found"}


def test_upload_uses_streamed_twenty_mib_limit_not_login_limit(private_app):
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        login(client, auth)
        content = BytesIO()
        Image.new("RGB", (100, 100), "white").save(content, format="PNG")
        body = content.getvalue() + b"\0" * 8192
        assert client.post("/api/search/pages", content=iter([body[:4096], body[4096:]])).status_code == 200
        response = client.post("/api/search/pages", content=iter([b"\0" * (1024 * 1024)] * 21))
        assert response.status_code == 413
        assert response.headers["cache-control"] == "no-store"


def test_ocr_failure_never_echoes_private_worker_paths(private_app, repository, monkeypatch):
    def failed_observe(*_args, **_kwargs):
        raise dev_api.OcrWorkerError(f"Unreadable private image at {repository.root}/pages/private-owner/source.png")

    monkeypatch.setattr(dev_api.OcrClient, "observe", failed_observe)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        login(client, auth)
        content = BytesIO()
        Image.new("RGB", (100, 100), "white").save(content, format="PNG")
        response = client.post("/api/search/pages", content=content.getvalue())
        assert response.status_code == 503
        assert response.json() == {"detail": "ocr.unavailable"}
        assert str(repository.root) not in response.text


def test_completed_without_verified_course_remains_public_but_unsupported(private_app, repository, monkeypatch):
    recorded_pipeline(monkeypatch, verified=False)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        result = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]}).json()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            row = repository.submission(user, result["search_id"])
            if row["lesson_status"] == "unsupported":
                break
            time.sleep(0.02)
        assert row["lesson_status"] == "unsupported"
        assert row["problem_id"] and row["recognition_status"] == "reviewed"
        history = client.get("/api/search/problems").json()["items"]
        assert len(history) == 1 and not history[0]["lesson_available"]


def test_deleting_running_recognition_never_republishes(private_app, repository, monkeypatch):
    entered, release = Event(), Event()
    recorded_pipeline(monkeypatch, entered=entered, release=release)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        started = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]}).json()
        assert entered.wait(5)
        assert client.delete(f"/api/search/problems/{started['search_id']}").status_code == 200
        assert client.get(page["image_url"]).status_code == 200
        release.set()
    repository.cleanup()
    assert repository.history(user)["items"] == []
    assert not repository.storage.path(repository.storage.submission_key(started["search_id"])).exists()


def test_orphan_cleanup_cannot_remove_an_inflight_crop_before_registration(private_app, repository, monkeypatch):
    calls = recorded_pipeline(monkeypatch)
    cleaned = []
    original_save = dev_api.save

    def save_during_cleanup(path, payload):
        if path.name == "crop.json":
            repository.test_time[0] += timedelta(hours=2)
            cleaned.append(repository.cleanup_orphans())
        original_save(path, payload)

    monkeypatch.setattr(dev_api, "save", save_during_cleanup)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        response = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]})
        assert response.status_code == 200, response.text
        row = wait_ready(repository, user, response.json()["search_id"])
        assert (row["path"] / "original.png").is_file()
        assert (row["path"] / "question.png").is_file()
    assert cleaned == [0]
    assert calls == [row["id"]]


@pytest.mark.parametrize("revocation", ["delete", "expire", "disable"])
def test_revoked_stage_two_does_not_start_another_teaching_phase(private_app, repository, monkeypatch, revocation):
    entered, release = Event(), Event()
    recorded_pipeline(monkeypatch)
    classify = dev_api.run_stage_two
    following_phases = []

    def paused_classify(*args, **kwargs):
        classify(*args, **kwargs)
        entered.set()
        assert release.wait(10)

    monkeypatch.setattr(dev_api, "run_stage_two", paused_classify)
    monkeypatch.setattr(dev_api.stage_three, "run_stage_three", lambda *args, **kwargs: following_phases.append(args))
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        started = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]}).json()
        try:
            assert entered.wait(5)
            row = repository.submission(user, started["search_id"])
            if revocation == "delete":
                assert client.delete(f"/api/search/problems/{row['id']}").status_code == 200
            elif revocation == "expire":
                repository.test_time[0] += timedelta(days=30)
            else:
                repository.disable(row["problem_id"])
        finally:
            release.set()
    assert following_phases == []
    repository.cleanup()
    history = repository.history(user)["items"]
    if revocation == "delete":
        assert history == []
    else:
        assert history[0]["latest_status"] == {"expire": "expired", "disable": "disabled"}[revocation]
    if revocation != "disable":
        assert not row["path"].exists()


@pytest.mark.parametrize("revocation", ["logout", "delete", "expire", "disable"])
def test_websocket_handshake_and_revocation(private_app, repository, monkeypatch, revocation):
    app, auth = private_app
    monkeypatch.setattr(dev_api.stage_three, "find_run", lambda directory, _run_id: directory)
    monkeypatch.setattr(dev_api.stage_three, "stream_descriptor", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dev_api.stage_three, "event_page", lambda *_args: {"events": [], "last_seq": 0})
    with TestClient(app, base_url=auth.config.origin) as client:
        url = "/api/search/problems/" + "a" * 12 + "/lesson/" + "b" * 32 + "/ws"
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(url, headers={"Origin": auth.config.origin}):
            pytest.fail("anonymous socket accepted")
        user, token = login(client, auth)
        row, _ = submission(repository, user)
        problem = repository.associate(row["id"], build_identity(reviewed_result(public_candidate())))
        url = f"/api/search/problems/{row['id']}/lesson/" + "b" * 32 + "/ws"
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(url, headers={"Origin": "https://other.example"}):
            pytest.fail("foreign origin accepted")
        with client.websocket_connect(url) as socket:
            assert socket.receive_json()["events"] == []
            if revocation == "logout":
                auth.logout(token)
            elif revocation == "delete":
                repository.delete(user, row["id"])
            elif revocation == "expire":
                repository.test_time[0] += timedelta(days=30)
            else:
                repository.disable(problem["id"])
            expected = {"logout": "search.login_required", "delete": "search.not_found",
                        "expire": "search.expired", "disable": "problem.disabled"}
            assert socket.receive_json()["error"] == expected[revocation]
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()


def test_idle_websocket_checks_authority_periodically_not_on_every_poll(private_app, repository, monkeypatch):
    app, auth = private_app
    clock = [10.0]
    reads = []
    checks = []
    ownership_checks = []
    idle = Event()
    refreshed = Event()
    original_current_user = auth.current_user
    original_submission = repository.submission

    def current_user(token):
        checks.append(clock[0])
        if clock[0] == 13.0:
            refreshed.set()
        return original_current_user(token)

    def checked_submission(*args, **kwargs):
        ownership_checks.append(clock[0])
        return original_submission(*args, **kwargs)

    def events(_directory, after):
        reads.append(after)
        if len(reads) >= 3:
            idle.set()
        return {"events": [], "last_seq": after}

    monkeypatch.setattr(dev_api, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(dev_api.stage_three, "find_run", lambda directory, _run_id: directory)
    monkeypatch.setattr(dev_api.stage_three, "stream_descriptor", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dev_api.stage_three, "event_page", events)
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        row, _ = submission(repository, user)
        monkeypatch.setattr(auth, "current_user", current_user)
        monkeypatch.setattr(repository, "submission", checked_submission)
        with client.websocket_connect(f"/api/search/problems/{row['id']}/lesson/" + "b" * 32 + "/ws") as socket:
            assert socket.receive_json()["events"] == []
            initial = len(checks)
            initial_ownership = len(ownership_checks)
            assert idle.wait(5)
            assert len(checks) == initial
            assert len(ownership_checks) == initial_ownership
            clock[0] = 13.0
            assert refreshed.wait(5)
            assert len(checks) == initial + 1


@pytest.mark.parametrize("revocation", ["logout", "delete", "expire", "disable"])
def test_websocket_rechecks_before_new_events_even_inside_idle_check_interval(private_app, repository, monkeypatch, revocation):
    app, auth = private_app
    published = Event()
    monkeypatch.setattr(dev_api, "monotonic", lambda: 10.0, raising=False)
    monkeypatch.setattr(dev_api.stage_three, "find_run", lambda directory, _run_id: directory)
    monkeypatch.setattr(dev_api.stage_three, "stream_descriptor", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(dev_api.stage_three, "event_page", lambda *_args: {
        "events": [{"seq": 1, "private": "not to be delivered"}] if published.is_set() else [], "last_seq": 1,
    })
    with TestClient(app, base_url=auth.config.origin) as client:
        user, token = login(client, auth)
        row, _ = submission(repository, user)
        problem = repository.associate(row["id"], build_identity(reviewed_result(public_candidate())))
        with client.websocket_connect(f"/api/search/problems/{row['id']}/lesson/" + "b" * 32 + "/ws") as socket:
            assert socket.receive_json()["events"] == []
            if revocation == "logout":
                auth.logout(token)
            elif revocation == "delete":
                repository.delete(user, row["id"])
            elif revocation == "expire":
                repository.test_time[0] += timedelta(days=30)
            else:
                repository.disable(problem["id"])
            published.set()
            response = socket.receive_json()
            assert "error" in response and "events" not in response
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()


def test_websocket_cached_location_cannot_recreate_cleaned_artifacts(private_app, repository, monkeypatch):
    recorded_pipeline(monkeypatch)
    monkeypatch.setattr(dev_api, "monotonic", lambda: 10.0)
    app, auth = private_app
    with TestClient(app, base_url=auth.config.origin) as client:
        user, _token = login(client, auth)
        page = upload(client)
        started = client.post("/api/search/problems", json={"page_id": page["page_id"], "box": [0, 0, 1, 1]}).json()
        row = wait_ready(repository, user, started["search_id"])
        stream = client.get(f"/api/search/problems/{row['id']}").json()['lesson']['stream']
        with client.websocket_connect(stream['websocket_url']) as socket:
            assert socket.receive_json()["events"] == []
            repository.delete(user, row["id"])
            deadline = time.monotonic() + 5
            while row["path"].exists() and time.monotonic() < deadline:
                repository.cleanup()
                time.sleep(0.02)
            assert not row["path"].exists()
            assert socket.receive_json() == {"error": "search.not_found"}
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
        assert not row["path"].exists()
