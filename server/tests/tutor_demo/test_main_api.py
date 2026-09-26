"""Exercise the deployed entry point without a database or external model."""

import runpy

from fastapi.testclient import TestClient

from shuxueshuo_server.product import api as product_api
from shuxueshuo_server.tutor_demo import api as tutor_api
from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable


def test_main_hosts_tutor_api_and_preserves_lifecycles(monkeypatch):
    lifecycle = []

    class Product:
        def close(self):
            lifecycle.append("product.closed")

    def load_product():
        lifecycle.append("product.started")
        return Product()

    class Tutor:
        unavailable = False

        async def respond(self, **data):
            if self.unavailable:
                raise TutorUnavailable("provider failure")
            return Proposal(
                reply="先看题目中固定的是和还是积。",
                intent="question",
                evidence=[],
                actions=[],
            )

        async def close(self):
            lifecycle.append("tutor.closed")

    tutor = Tutor()
    monkeypatch.setenv("REVIEW_BACKEND", "product")
    monkeypatch.setattr(product_api, "load_application", load_product)
    monkeypatch.setattr(tutor_api, "DeepSeekTutor", lambda: tutor)
    app = runpy.run_module("shuxueshuo_server.main")["app"]

    with TestClient(app) as client:
        assert lifecycle == ["product.started"]
        assert client.get("/api/health").json() == {"status": "ok"}
        assert "/api/product/v1/health" in client.get("/openapi.json").json()["paths"]
        response = client.post("/api/tutor-demo/sessions", json={"lesson_id": "q01"})
        assert response.status_code == 201
        view = response.json()
        url = f"/api/tutor-demo/sessions/{view['session_id']}"
        assert client.get(url).json() == view
        response = client.post(
            url + "/events",
            json={"event_id": "help-1", "revision": 0, "kind": "help"},
        )
        assert response.status_code == 200
        after = response.json()
        assert after["revision"] == 1
        assert after["messages"][-1]["text"] == "先看题目中固定的是和还是积。"

        tutor.unavailable = True
        response = client.post(
            url + "/events",
            json={"event_id": "help-2", "revision": 1, "kind": "help"},
        )
        assert response.status_code == 503
        assert "provider failure" not in response.text
        assert client.get(url).json() == after
        assert client.get("/api/tutor-demo/sessions/missing").status_code == 404

    assert lifecycle.count("tutor.closed") == 1
    assert lifecycle.count("product.closed") == 1
