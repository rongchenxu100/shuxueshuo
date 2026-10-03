"""Exercise the real OTP/cookie boundary, with no dependency overrides or paid calls."""

import runpy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo.api import create_app
from shuxueshuo_server.tutor_demo.limits import CallBudget
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Sessions


class Tutor:
    def __init__(self):
        self.calls = []

    async def respond(self, **kwargs):
        self.calls.append(kwargs)
        return Proposal(reply="先想一想固定的是和还是积？", intent="question", evidence=[], actions=[])


def login(client, auth, phone):
    sent = client.post("/api/auth/sms/send", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    cid = sent.json()["challenge_id"]
    response = client.post("/api/auth/sms/verify", json={
        "phone": phone, "challenge_id": cid, "code": auth.sms.messages[cid][1],
    })
    assert response.status_code == 200, response.text
    return response.json()["user"]


@pytest.fixture(params=["standalone", "main"])
def tutor_app(auth, tmp_path, request, monkeypatch):
    tutor = Tutor()
    budget = CallBudget(tmp_path / "usage.sqlite3")
    if request.param == "standalone":
        app = create_app(tutor, budget, auth=auth)
    else:
        from shuxueshuo_server.auth import api as auth_api
        from shuxueshuo_server.product import api as product_api
        from shuxueshuo_server.tutor_demo import api as tutor_api

        install = auth_api.install_auth
        router = tutor_api.create_router
        monkeypatch.setenv("REVIEW_BACKEND", "product")
        monkeypatch.setattr(auth_api, "install_auth", lambda app: install(app, auth=auth))
        monkeypatch.setattr(tutor_api, "create_router", lambda: router(tutor, budget))
        monkeypatch.setattr(product_api, "load_application", lambda: SimpleNamespace(db=auth.db, close=lambda: None))
        app = runpy.run_module("shuxueshuo_server.main")["app"]
    return app, tutor


def client_for(app):
    return TestClient(app, base_url="https://testserver", headers={"Origin": "https://testserver"})


def start(client):
    response = client.post("/api/tutor-demo/sessions", json={"lesson_id": "q01"})
    assert response.status_code == 201, response.text
    assert "owner_user_id" not in response.text
    return response.json()


def event(view, kind="help"):
    return {"event_id": "ask-1", "revision": view["revision"], "kind": kind,
            "text": "固定的是和吗？" if kind == "text" else ""}


def test_anonymous_and_disabled_entries_fail_closed(tutor_app):
    app, tutor = tutor_app
    for instance, status in [(app, 401)]:
        with client_for(instance) as client:
            assert client.post("/api/tutor-demo/sessions", json={"lesson_id": "q01"}).status_code == status
            assert client.get("/api/tutor-demo/sessions/unknown").status_code == status
            for kind in ["help", "text", "ui"]:
                result = client.post("/api/tutor-demo/sessions/unknown/events",
                                     json=event({"revision": 0}, kind), headers={"X-User-Id": "forged"})
                assert result.status_code == status
                assert result.headers["cache-control"] == "no-store"
    assert not tutor.calls


def test_disabled_standalone_preserves_static_practice():
    with client_for(create_app(Tutor())) as client:
        assert client.get("/1/q01/").status_code == 200
        assert client.get("/assets/auth/site-auth.js").status_code == 200
        assert client.post("/api/tutor-demo/sessions", json={"lesson_id": "q01"}).status_code == 503
        assert client.get("/api/tutor-demo/sessions/unknown").status_code == 503
        assert client.post("/api/tutor-demo/sessions/unknown/events", json=event({"revision": 0})).status_code == 503


@pytest.mark.parametrize("kind", ["help", "text"])
def test_ownership_csrf_and_idempotent_dialogue(tutor_app, auth, phone, kind):
    app, tutor = tutor_app
    with client_for(app) as alice, client_for(app) as bob:
        login(alice, auth, phone)
        login(bob, auth, "138" + phone[3:])
        view = start(alice)
        url = f"/api/tutor-demo/sessions/{view['session_id']}"
        payload = event(view, kind)
        assert bob.get(url).status_code == 404
        assert bob.post(url + "/events", json=payload).status_code == 404
        assert alice.post(url + "/events", json=payload, headers={"Origin": "https://evil.example"}).status_code == 403
        assert alice.post("/api/tutor-demo/sessions", json={"lesson_id": "q01", "user_id": "forged"}).status_code == 422
        assert not tutor.calls
        response = alice.post(url + "/events", json=payload)
        assert response.status_code == 200, response.text
        assert len(tutor.calls) == 1
        assert alice.post(url + "/events", json=payload).json() == response.json()
        assert len(tutor.calls) == 1
        assert alice.get(url).json() == response.json()
        assert response.headers["cache-control"] == "no-store"


def test_logout_expiry_and_same_account_reauthentication(tutor_app, auth, phone):
    app, tutor = tutor_app
    with client_for(app) as client:
        user = login(client, auth, phone)
        view = start(client)
        url = f"/api/tutor-demo/sessions/{view['session_id']}"
        token = client.cookies.get("__Host-sss_session")
        assert client.post("/api/auth/logout").status_code == 204
        assert client.get(url, headers={"Cookie": f"__Host-sss_session={token}"}).status_code == 401
        assert client.post(url + "/events", json=event(view)).status_code == 401
        auth.test_time[0] += timedelta(seconds=61)
        assert login(client, auth, phone) == user
        assert client.get(url).status_code == 200
        auth.test_time[0] += timedelta(seconds=auth.config.session_seconds + 1)
        assert client.post(url + "/events", json=event(view)).status_code == 401
        assert not tutor.calls
        assert login(client, auth, phone) == user
        assert client.post(url + "/events", json=event(view)).status_code == 200
        assert len(tutor.calls) == 1


def test_one_account_cannot_fill_the_global_session_cap():
    sessions = Sessions()
    other = sessions.create("q01", owner_user_id="bob")
    mine = [sessions.create("q01", owner_user_id="alice") for _ in range(12)]
    owned = [s for s in sessions.items.values() if s.owner_user_id == "alice"]
    assert len(owned) == 8 and mine[-1] in owned and mine[0] not in owned
    assert sessions.get(other.id, owner_user_id="bob") is other
