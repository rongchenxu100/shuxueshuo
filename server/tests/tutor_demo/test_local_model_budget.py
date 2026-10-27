"""Only the local development entry point opts out of model call quotas."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.search.admission import SearchLimits
from shuxueshuo_server.tutor_demo.api import create_router, require_tutor_user
from tools import run_site

from .test_generated_explanation import Generator, initial
from .test_tutor_demo import Tutor


def test_local_entry_serves_both_model_routes_even_when_configured_quotas_are_zero(monkeypatch, tmp_path):
    for name in ("TUTOR_SESSION_CALL_LIMIT", "TUTOR_USER_DAILY_CALL_LIMIT", "TUTOR_DAILY_CALL_LIMIT"):
        monkeypatch.setenv(name, "0")
    tutor = Tutor()
    explanation = Generator(initial(), {"outcome": "feedback", "reply": "可以先换元。"})
    monkeypatch.setattr(run_site, "create_router", lambda *, budget, enable_explanation: create_router(
        tutor=tutor, explanation_interpreter=explanation, budget=budget, enable_explanation=enable_explanation))
    app = run_site.create_local_app(SimpleNamespace(mode="local", root=tmp_path), AuthConfig(environment="development"))
    app.dependency_overrides[require_tutor_user] = lambda: {"id": "local-test-user"}
    # No lifespan/database: these requests must not touch the production ledger.
    client = TestClient(app)
    base = "/api/tutor-demo"
    session = client.post(f"{base}/sessions", json={"lesson_id": "q01"}).json()
    response = client.post(f"{base}/sessions/{session['session_id']}/events", json={
        "event_id": "ask", "revision": session["revision"], "kind": "text", "text": "怎么做？"})
    assert response.status_code == 200 and len(tutor.calls) == 1
    assert "X-Tutor-Calls-Remaining" not in response.headers
    session = client.post(f"{base}/explanation/sessions", json={"problem_id": "q12"}).json()
    url = f"{base}/explanation/sessions/{session['session_id']}"
    response = client.post(f"{url}/candidates")
    assert response.status_code == 200
    response = client.post(f"{url}/events", json={
        "event_id": "hint", "revision": response.json()["revision"], "kind": "help"})
    assert response.status_code == 200 and len(explanation.calls) == 2


def test_local_entry_installs_search_without_daily_llm_quotas(monkeypatch, tmp_path):
    seen = {}

    def capture(app, *, settings=None, admission_config=None):
        seen["admission_config"] = admission_config

    monkeypatch.setattr(run_site, "install_search", capture)
    monkeypatch.setattr(run_site, "install_auth", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_site, "create_router", lambda **_kwargs: __import__("fastapi").APIRouter())
    run_site.create_local_app(SimpleNamespace(mode="local", root=tmp_path), AuthConfig(environment="development"))
    assert seen["admission_config"] == SearchLimits.local_development()
    assert seen["admission_config"].generation_account_daily is None


@pytest.mark.parametrize("mode, environment", [
    ("server", "production"), ("server", "development"), ("local", "production"),
])
def test_unlimited_entry_requires_local_development(mode, environment):
    with pytest.raises(ValueError, match="local development"):
        run_site.create_local_app(SimpleNamespace(mode=mode), AuthConfig(environment=environment))
