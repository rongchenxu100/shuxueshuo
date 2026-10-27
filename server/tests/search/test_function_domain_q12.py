"""The retained Q12 photograph reaches strict domain-parameter solving."""

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

Q12_RECORDING = RECORDING.parent / "q12-recorded-20261027"
Q12_SPACED_RECORDING = RECORDING.parent / "q12-spaced-recorded-20261027"
REPO = Path(__file__).resolve().parents[3]


def test_q12_retained_photo_preserves_reciprocal_root_and_parameter_goal():
    manifest = json.loads((Q12_RECORDING / "recording.json").read_text())
    source_file = REPO / manifest["source"]
    source = json.loads(source_file.read_text())
    page = source_file.parent / source["page"]["file"]
    crop = source_file.parent / source["question"]["file"]
    assert page.read_bytes() == (REPO / source["retained_source"]).read_bytes()
    assert sha256(page.read_bytes()).hexdigest() == source["page"]["sha256"]
    assert sha256(crop.read_bytes()).hexdigest() == source["question"]["sha256"]
    assert crop.read_bytes() == (Q12_RECORDING / "question.png").read_bytes()
    with Image.open(page) as full, Image.open(crop) as question:
        assert list(full.size) == source["page"]["size"]
        assert full.crop(source["question"]["crop_xyxy"]).tobytes() == question.tobytes()

    result = revalidate_recording(Q12_RECORDING, problem_id="function-concepts-q12")
    candidate = result["candidate"]
    assert [value.replace(" ", "") for value in candidate["root"]["definitions"]] == [
        "f(x)=1/sqrt(m*x^2-6*m*x+m+8)",
    ]
    assert candidate["root"]["facts"] == []
    assert candidate["root"]["goals"] == [
        {"kind": "match_domain", "object": "f", "domain": "ℝ", "symbol": "m"},
    ]
    assert r"\frac{1}{\sqrt{mx^2-6mx+m+8}}" in candidate["original_text"]
    assert "定义域" in candidate["original_text"]
    assert "[0" not in candidate["original_text"], "the handwritten answer is outside the crop"
    assert manifest["historical_semantic_calls"] == manifest["historical_network_attempts"] == 2
    assert [attempt["status"] for attempt in manifest["attempts"]] == ["reviewed_candidate"]


def test_q12_real_spaced_transcription_retains_the_original_failure_evidence():
    manifest = json.loads((Q12_SPACED_RECORDING / "recording.json").read_text())
    assert manifest["source_image_sha256"] == sha256((Q12_SPACED_RECORDING / "question.png").read_bytes()).hexdigest()
    assert manifest["historical_semantic_calls"] == manifest["historical_network_attempts"] == 2
    previous = manifest["previous_stage_two"]
    assert previous["primary"] == "type-function-domain"
    assert any(item["code"] == "d1.function_definition_not_uniquely_located" for item in previous["d1_diagnostics"])
    result = revalidate_recording(Q12_SPACED_RECORDING, problem_id="function-concepts-q12")
    assert r"\sqrt{m x^2-6mx+m+8}" in result["candidate"]["original_text"]
    assert result["candidate"]["root"]["definitions"] == ["f(x)=1/sqrt(m*x^2-6*m*x+m+8)"]


@pytest.mark.parametrize("recording", [Q12_RECORDING, Q12_SPACED_RECORDING], ids=["compact", "spaced-original"])
def test_q12_photo_api_solves_strict_parameter_range_and_reopens_without_reexecution(tmp_path, monkeypatch, recording):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    root = tmp_path / "private-search"
    _session, directory = seed_photo_recording(root, recording=recording,
                                               problem_id="function-concepts-q12")
    base = f"/api/search/problems/{directory.name}"
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal = first.json()["lesson"]["goals"][0]
        assert goal["primary"] == "type-function-domain"
        assert "diagnostics" not in goal["d1"], goal["d1"]
        if recording == Q12_SPACED_RECORDING:
            (given,) = goal["d1"]["givens"]
            assert r"\sqrt{m x^2-6mx+m+8}" in given["quote"][0]["text"]
            candidate = json.loads((directory / "result.json").read_text())["candidate"]
            quote = given["quote"][0]
            assert candidate["original_text"][quote["start"]:quote["end"]].strip("$") == quote["text"].strip("$")
        reading = goal["walk"]["bundle"]["intro"][0]
        assert reading["question"] == "题目已知定义域，实际要求确定什么？"
        assert {option["label"] for option in reading["interaction"]["options"]} == {
            "使定义域恰为题给集合的参数 $m$ 的取值范围", "自变量 $x$ 的取值范围",
        }
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
        assert handoff["answer"]["set"]["expression"] == "Interval.Ropen(0, 1)"
        assert all(row["status"] != "pending" for row in snapshot["interaction_states"])
        parts = [part for chunk in snapshot["interactions"] for part in chunk["parts"]]
        (conditions,) = [part for part in parts if part["title"] == "列出根号与分母的条件"]
        assert conditions["interaction"]["type"] == "checklist"
        assert len(conditions["interaction"]["slots"]) == 2
        assert conditions["expected_answer"] == {"terms": ["s1o1", "s2o1"]}
        slots = conditions["interaction"]["slots"]
        originals = [next(option["label"] for option in slot["options"]
                          if option["value"] == f"s{index}o1")
                     for index, slot in enumerate(slots, 1)]
        assert r"\geq" in originals[0] and r"\sqrt" not in originals[0]
        assert r"\neq" in originals[1] and r"\sqrt" in originals[1]
        (reduction,) = [part for part in parts if part["title"] == "合并有意义的条件"]
        assert reduction["expected_answer"] == {"one_of": ["o1"]}
        assert next(option["label"] for option in reduction["interaction"]["options"]
                    if option["value"] == "o1") == "$u>0$"
        (borrow,) = [part for part in parts if part["interaction"]["type"] == "plane"]
        assert borrow["expected_answer"] == {"cell": ["real", "free"], "method": "discriminant"}
        assert ">" in borrow["question"] and r"\geq" not in borrow["question"]
        assert any(part["title"] == "回到定义域求参" for part in parts)
        events = client.get(stream["events_url"]).json()
        assert events["events"] and events["last_seq"] == snapshot["last_seq"]
        monkeypatch.setattr("shuxueshuo_server.search.stage_three.runner.run_sample", forbidden)
        assert client.post(base + "/lesson/start").json()["stream"] == stream
        assert client.get(stream["snapshot_url"]).json() == snapshot
        assert client.get(base).json()["lesson"]["stream"] == stream
    print(f"Q12 verified photo Stage3: {directory / 'stage-two-1/stage-three'}")
