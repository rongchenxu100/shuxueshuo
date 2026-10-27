"""Published domain courses record actual native answers through student APIs."""

import json
import os
from uuid import uuid4

import pytest
from test_auth import login

from shuxueshuo_server.learning.content import ROOT, load_content, publish
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine


@pytest.mark.parametrize("problem_id", [
    "function-concepts-q15", "function-concepts-q01", "function-concepts-q22",
])
def test_published_domain_course_records_each_step_and_restores(client, auth, phone, problem_id):
    settings = Settings.load("local", os.environ["PRODUCT_TEST_DATA_DIR"], os.environ["PRODUCT_TEST_INSTANCE"])
    publisher = engine(settings.url("migration"))
    try:
        publish(publisher, load_content())
    finally:
        publisher.dispose()
    login(client, auth, phone)
    bundle = json.loads((ROOT / f"site/data/graph-walk/{problem_id}.json").read_text())
    replay = json.loads((ROOT / f"site/data/graph-walk/{problem_id}.replay.json").read_text())
    mark = f"/api/learning/marks/{problem_id}"
    assert client.get(mark).json()["practiced"] is False
    assert client.post(mark + "/complete", json={}).status_code == 409
    response = client.post("/api/learning/practice", json={
        "id": str(uuid4()), "problem_id": problem_id, "route_id": next(iter(bundle["routes"])),
        "content_version": client.get("/api/learning/content").json()["content_version"],
    })
    assert response.status_code == 200, response.text
    attempt = response.json()
    base = f"/api/learning/practice/{attempt['id']}"
    last = replay["actions"][-1]
    premature = client.post(base + "/answers", json={
        "id": str(uuid4()), "step_id": last["decision"], "answer": {"value": last["answer"]},
    })
    assert premature.status_code == 409
    for action in replay["actions"]:
        payload = {"id": str(uuid4()), "step_id": action["decision"], "answer": {"value": action["answer"]}}
        response = client.post(base + "/answers", json=payload)
        assert response.status_code == 200, response.text
        attempt = response.json()
        # A response retry cannot add another attempt event or change the answer.
        assert client.post(base + "/answers", json=payload).json() == attempt
    assert attempt["status"] == "completed"
    assert len(attempt["steps"]) == len(replay["actions"])
    assert all(step["passed"] for step in attempt["steps"])
    restored = client.get(base)
    assert restored.status_code == 200
    assert restored.json()["steps"] == attempt["steps"]
    assert client.get(mark).json()["practiced"] is True
