from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.auth.api import install_auth
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthError, AuthService
from shuxueshuo_server.auth.sms import SmsUnavailable
from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.db import transaction


def login(client, auth, phone):
    sent = client.post("/api/auth/sms/send", json={"phone": phone})
    assert sent.status_code == 200, sent.text
    challenge_id = sent.json()["challenge_id"]
    _, code = auth.sms.messages[challenge_id]
    response = client.post(
        "/api/auth/sms/verify",
        json={"phone": phone, "challenge_id": challenge_id, "code": code},
    )
    assert response.status_code == 200, response.text
    return response


def test_login_cookie_logout_and_replay(client, auth, phone):
    assert client.get("/api/auth/me").json() == {"enabled": True, "user": None}
    assert client.get("/protected").status_code == 401
    response = login(client, auth, phone)
    assert phone not in response.text
    header = response.headers["set-cookie"]
    for flag in ["HttpOnly", "Secure", "SameSite=lax", "Path=/"]:
        assert flag in header
    user = client.get("/api/auth/me").json()["user"]
    assert client.get("/protected").json() == user
    token = client.cookies.get("__Host-sss_session")
    restarted = AuthService(auth.db, auth.config, auth.sms, clock=auth.clock)
    assert restarted.current_user(token) == user
    assert client.post("/api/auth/logout").status_code == 204
    assert restarted.current_user(token) is None
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/protected").status_code == 401
    assert client.get("/api/auth/me").headers["cache-control"] == "no-store"


def test_account_switch_revokes_old_session(client, auth, phone):
    first = login(client, auth, phone).json()["user"]
    old = client.cookies.get("__Host-sss_session")
    second = login(client, auth, "138" + phone[3:]).json()["user"]
    assert first["id"] != second["id"]
    assert auth.current_user(old) is None
    with transaction(auth.db) as c:
        assert (
            c.scalar(
                select(func.count())
                .select_from(m.workspace_members)
                .where(
                    m.workspace_members.c.user_id.in_(
                        [UUID(first["id"]), UUID(second["id"])]
                    )
                )
            )
            == 0
        )
        with pytest.raises(DBAPIError):
            c.execute(
                m.users.insert().values(key="forbidden", display_name="forbidden")
            )


def test_same_phone_across_devices_and_logout_scope(app, client, auth, phone):
    first = login(client, auth, phone).json()["user"]
    auth.test_time[0] += timedelta(seconds=61)
    with TestClient(
        app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    ) as other:
        assert login(other, auth, phone).json()["user"] == first
        client.post("/api/auth/logout")
        assert other.get("/protected").status_code == 200


def test_wrong_codes_committed_and_attempts_exhausted(client, auth, phone):
    sent = client.post("/api/auth/sms/send", json={"phone": phone}).json()
    cid = sent["challenge_id"]
    code = auth.sms.messages[cid][1]
    wrong = "000000" if code != "000000" else "111111"
    body = {"phone": phone, "challenge_id": cid, "code": wrong}
    for _ in range(5):
        assert client.post("/api/auth/sms/verify", json=body).status_code == 400
    body["code"] = code
    assert client.post("/api/auth/sms/verify", json=body).status_code == 400
    with transaction(auth.db) as c:
        assert (
            c.scalar(
                select(m.student_sms_challenges.c.attempts).where(
                    m.student_sms_challenges.c.id == UUID(cid)
                )
            )
            == 5
        )


def test_expiry_and_consumed_code(auth, phone):
    sent = auth.send(phone, "local")
    cid = UUID(sent["challenge_id"])
    code = auth.sms.messages[str(cid)][1]
    auth.test_time[0] += timedelta(seconds=301)
    with pytest.raises(AuthError):
        auth.verify(phone, cid, code, "local")
    sent = auth.send(phone, "local")
    cid = UUID(sent["challenge_id"])
    code = auth.sms.messages[str(cid)][1]
    _user, token = auth.verify(phone, cid, code, "local")
    with pytest.raises(AuthError):
        auth.verify(phone, cid, code, "local")
    auth.test_time[0] += timedelta(seconds=auth.config.session_seconds + 1)
    assert auth.current_user(token) is None


def test_concurrent_code_consumption_and_registration(auth, phone):
    sent = auth.send(phone, "one")
    cid = UUID(sent["challenge_id"])
    code = auth.sms.messages[str(cid)][1]

    def verify(_):
        try:
            return auth.verify(phone, cid, code, "one")
        except AuthError:
            return None

    with ThreadPoolExecutor(4) as pool:
        assert len([x for x in pool.map(verify, range(4)) if x]) == 1
    # Two separately issued valid codes still converge on one phone identity.
    challenges = []
    for _ in range(2):
        auth.test_time[0] += timedelta(seconds=61)
        cid = UUID(auth.send(phone, "one")["challenge_id"])
        challenges.append((cid, auth.sms.messages[str(cid)][1]))
    with ThreadPoolExecutor(2) as pool:
        users = list(
            pool.map(lambda pair: auth.verify(phone, *pair, "one")[0], challenges)
        )
    assert users[0]["id"] == users[1]["id"]


def test_send_cooldown_and_failed_provider_consumes_budget(auth, phone):
    auth.sms.send = lambda *args: (_ for _ in ()).throw(SmsUnavailable())
    with pytest.raises(AuthError) as error:
        auth.send(phone, "one")
    assert error.value.status == 503
    with pytest.raises(AuthError) as error:
        auth.send(phone, "one")
    assert error.value.status == 429
    auth.test_time[0] += timedelta(seconds=61)
    auth.config = replace(auth.config, daily_limit=1)
    with pytest.raises(AuthError) as error:
        auth.send("138" + phone[3:], "two")
    assert error.value.status == 429


def test_csrf_validation_and_no_input_echo(client, auth, phone):
    for origin in [
        "https://evil.example",
        "https://testserver.evil.example",
        "null",
        "",
    ]:
        response = client.post(
            "/api/auth/sms/send", json={"phone": phone}, headers={"origin": origin}
        )
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"
    bad = client.post(
        "/api/auth/sms/verify",
        json={"phone": phone, "code": "SECRET", "challenge_id": str(uuid4())},
    )
    assert bad.status_code == 422
    assert "SECRET" not in bad.text and phone not in bad.text
    assert client.post("/api/auth/sms/send", content="x" * 4097).status_code == 413
    login(client, auth, phone)
    assert (
        client.post(
            "/api/auth/logout", headers={"origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/protected").status_code == 200


def test_phone_mismatch_and_verify_ip_limit(auth, phone):
    cid = UUID(auth.send(phone, "local")["challenge_id"])
    code = auth.sms.messages[str(cid)][1]
    with pytest.raises(AuthError):
        auth.verify("138" + phone[3:], cid, code, "local")
    for _ in range(29):
        with pytest.raises(AuthError):
            auth.verify(phone, uuid4(), "123456", "local")
    with pytest.raises(AuthError) as error:
        auth.verify(phone, cid, code, "local")
    assert error.value.status == 429


def test_mock_rejects_remote_clients(app):
    with TestClient(
        app, base_url="https://testserver", client=("203.0.113.8", 1234)
    ) as client:
        assert client.get("/api/auth/me").status_code == 403


def test_config_refuses_production_mock_and_insecure_cookie(config):
    with pytest.raises(ValueError):
        replace(config, environment="production")
    with pytest.raises(ValueError):
        replace(config, origin="https://public.example")
    with pytest.raises(ValueError):
        replace(config, secret="short")
    with pytest.raises(ValueError):
        replace(config, mode="aliyun_sms", environment="production", secure=False)


def test_disabled_service():
    app = FastAPI()
    install_auth(app, config=AuthConfig())
    with TestClient(app) as client:
        assert client.get("/api/auth/me").json() == {"enabled": False, "user": None}
        assert (
            client.post("/api/auth/sms/send", json={"phone": "13900000000"}).status_code
            == 503
        )
