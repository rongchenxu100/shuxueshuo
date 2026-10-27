"""A retained user photograph reaches M6 through the authenticated photo API."""

import json
import time
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image
from shuxueshuo_server.search import dev_api
from tests.search.function_domain_recording import RECORDING, revalidate_recording
from tests.search.support import authenticated_client
from tests.search.test_function_domain_api import forbidden, seed_photo_recording

Q04_RECORDING = RECORDING.parent / "q04-recorded-20261027"
Q04_RETRY_RECORDING = RECORDING.parent / "q04-retry-recorded-20261027"
REPO = Path(__file__).resolve().parents[3]


def test_q04_retained_photo_keeps_the_printed_input_range_and_parameter_goal():
    manifest = json.loads((Q04_RECORDING / "recording.json").read_text())
    source_file = REPO / manifest["source"]
    source = json.loads(source_file.read_text())
    page = source_file.parent / source["page"]["file"]
    crop = source_file.parent / source["question"]["file"]
    assert sha256(page.read_bytes()).hexdigest() == source["page"]["sha256"]
    assert sha256(crop.read_bytes()).hexdigest() == source["question"]["sha256"]
    assert crop.read_bytes() == (Q04_RECORDING / "question.png").read_bytes()
    with Image.open(page) as full, Image.open(crop) as question:
        assert list(full.size) == source["page"]["size"]
        assert full.crop(source["question"]["crop_xyxy"]).tobytes() == question.tobytes()

    result = revalidate_recording(Q04_RECORDING, problem_id="function-concepts-q04")
    candidate = result["candidate"]
    assert [value.replace(" ", "") for value in candidate["root"]["definitions"]] == [
        "f(x)=sqrt(m*x^2+4*m*x+3)",
    ]
    assert candidate["root"]["goals"] == [
        {"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "m"},
    ]
    assert "y=" in candidate["original_text"]
    assert "$x$ 的取值范围" in candidate["original_text"]
    assert "定义域" not in candidate["original_text"], "keep the photographed wording, not a rewritten fixture"
    assert "3/4" not in candidate["original_text"], "the handwritten answer is outside the crop"
    assert manifest["historical_semantic_calls"] == manifest["historical_network_attempts"] == 5
    assert [attempt["status"] for attempt in manifest["attempts"]] == [
        "workflow.oscillation", "reviewed_candidate",
    ]


def test_q04_unchanged_failed_photo_is_reviewed_with_shared_rules_and_no_handwritten_answer():
    manifest = json.loads((Q04_RETRY_RECORDING / "recording.json").read_text())
    failed = RECORDING.parent / "q04-failed-20261027"
    assert (Q04_RETRY_RECORDING / "question.png").read_bytes() == (failed / "question.png").read_bytes()
    assert manifest["source_image_sha256"] == "4b88a2553d6afecfe67e530e725e0cbdde6d466657e86b68e11111c2b42b90be"
    assert manifest["historical_semantic_calls"] == manifest["historical_network_attempts"] == 2
    result = revalidate_recording(Q04_RETRY_RECORDING, problem_id="function-concepts-q04")
    public = result["public_candidate"]
    assert public["root"]["definitions"] == ["f(x)=sqrt(m*x^2+4*m*x+3)"]
    assert public["root"]["goals"] == [
        {"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "m"},
    ]
    assert not public["root"].get("facts"), "domain conditions belong to the solver"
    assert public["original_text"].startswith("4.")
    statement = public["public_content"]["scopes"][0]["statement"]
    assert not statement.startswith("4.")
    assert "y=" in public["original_text"] and "y=" in statement
    assert "3/4" not in json.dumps(public, ensure_ascii=False)
    assert "frac" not in json.dumps(public, ensure_ascii=False), "ignore handwritten fraction"
    ledger = json.loads((Q04_RETRY_RECORDING / "workflow/ledger.json").read_text())
    shared = "internal/llm-prompts/graph-stage-one-source-rules.md"
    assert shared in ledger["identity"]["binding"]["files"]


@pytest.mark.parametrize("recording", [Q04_RECORDING, Q04_RETRY_RECORDING], ids=["printed-crop", "unchanged-retry"])
def test_q04_photo_api_solves_parameter_range_and_reopens_without_reexecution(tmp_path, monkeypatch, recording):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    root = tmp_path / "private-search"
    _session, directory = seed_photo_recording(root, recording=recording,
                                               problem_id="function-concepts-q04")
    base = f"/api/search/problems/{directory.name}"
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal = first.json()["lesson"]["goals"][0]
        assert goal["primary"] == "type-function-domain"
        assert "diagnostics" not in goal["d1"], goal["d1"]
        reading = goal["walk"]["bundle"]["intro"][0]
        assert reading["question"] == "题目已知定义域，实际要求确定什么？"
        assert {option["label"] for option in reading["interaction"]["options"]} == {
            "使定义域恰为题给集合的参数 $m$ 的取值范围", "自变量 $x$ 的取值范围",
        }
        assert "y=" in goal["d1"]["givens"][0]["quote"][0]["text"]
        started = client.post(base + "/lesson/start")
        assert started.status_code == 200, started.text
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            response = client.get(base)
            assert response.status_code == 200, response.text
            lesson = response.json()["lesson"]
            if lesson.get("execution_status") in {"completed", "partial", "failed", "error", "input_error"}:
                break
            time.sleep(0.05)
        assert lesson["execution_status"] == "completed", lesson
        stream = lesson["stream"]
        response = client.get(stream["snapshot_url"])
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert snapshot["goals"]["/root/goals/0"]["status"] == "solved"
        (handoff,) = snapshot["handoffs"]
        assert handoff["available"] is True
        assert handoff["answer"]["kind"] == "match_domain"
        assert handoff["answer"]["set"]["expression"] == "Interval(0, 3/4)"
        assert all(row["status"] != "pending" for row in snapshot["interaction_states"])
        parts = [part for chunk in snapshot["interactions"] for part in chunk["parts"]]
        (borrow,) = [part for part in parts if part["interaction"]["type"] == "plane"]
        assert borrow["expected_answer"] == {"cell": ["real", "free"], "method": "discriminant"}
        assert any(part["title"] == "回到定义域求参" for part in parts)
        assert len(parts) == 11, "retain the parameter-zero branch and the parent-method return"
        events = client.get(stream["events_url"]).json()
        assert events["events"] and events["last_seq"] == snapshot["last_seq"]
        monkeypatch.setattr("shuxueshuo_server.search.stage_three.runner.run_sample", forbidden)
        assert client.post(base + "/lesson/start").json()["stream"] == stream
        assert client.get(stream["snapshot_url"]).json() == snapshot
        assert client.get(base).json()["lesson"]["stream"] == stream
    print(f"Q04 verified photo Stage3: {directory / 'stage-two-1/stage-three'}")
