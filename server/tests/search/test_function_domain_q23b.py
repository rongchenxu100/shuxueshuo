"""The independent second question keeps its real source and interval goal."""

import json
import time
from hashlib import sha256
from pathlib import Path

from PIL import Image

from shuxueshuo_server.search import dev_api
from tests.search.function_domain_recording import RECORDING, revalidate_recording
from tests.search.support import authenticated_client
from tests.search.test_function_domain_api import forbidden, seed_photo_recording

Q23B_RECORDING = RECORDING.parent / "q23b-recorded-20261027"
REPO = Path(__file__).resolve().parents[3]


def test_q23b_two_source_crops_keep_only_shared_stem_and_second_question():
    manifest = json.loads((Q23B_RECORDING / "recording.json").read_text())
    assert manifest["source_kind"] == "user_photograph_shared_stem_and_second_question_crops_composite"
    source_file = REPO / manifest["source"]
    source = json.loads(source_file.read_text())
    page = source_file.parent / source["page"]["file"]
    question = source_file.parent / source["question"]["file"]
    assert sha256(page.read_bytes()).hexdigest() == source["page"]["sha256"]
    assert sha256(question.read_bytes()).hexdigest() == source["question"]["sha256"]
    assert question.read_bytes() == (Q23B_RECORDING / "question.png").read_bytes()
    assert len(source["parts"]) == 2
    rebuilt = Image.new("RGB", tuple(source["question"]["size"]),
                        tuple(source["question"]["background_rgb"]))
    with Image.open(page) as full, Image.open(question) as composed:
        assert list(full.size) == source["page"]["size"]
        for part in source["parts"]:
            path = source_file.parent / part["file"]
            assert sha256(path.read_bytes()).hexdigest() == part["sha256"]
            with Image.open(path) as crop:
                assert full.crop(part["crop_xyxy"]).tobytes() == crop.tobytes()
                rebuilt.paste(crop, tuple(part["paste_xy"]))
        assert rebuilt.tobytes() == composed.tobytes(), "the independent image contains only original pixels and padding"

    result = revalidate_recording(Q23B_RECORDING, problem_id="function-concepts-q23b")
    candidate = result["candidate"]
    assert candidate["root"]["definitions"] == ["f(x)=sqrt(x^2-3*x-m)/sqrt(x-1)"]
    assert candidate["root"].get("facts", []) == []
    assert candidate["root"].get("children", []) == []
    assert candidate["root"]["goals"] == [
        {"kind": "match_domain", "object": "f", "domain": "(1,∞)", "symbol": "m"},
    ]
    assert r"\frac{\sqrt{x^2-3x-m}}{\sqrt{x-1}}" in candidate["original_text"]
    assert r"$(1,+\infty)$" in candidate["original_text"]
    assert "10" not in candidate["original_text"], "part (1) must not become a parameter constraint"
    assert "9" not in candidate["original_text"], "the source solution is outside both crops"
    assert manifest["historical_semantic_calls"] == manifest["historical_network_attempts"] == 2
    assert [attempt["status"] for attempt in manifest["attempts"]] == ["reviewed_candidate"]


def test_q23b_photo_api_solves_exact_interval_domain_and_reopens_without_reexecution(tmp_path, monkeypatch):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    root = tmp_path / "private-search"
    _session, directory = seed_photo_recording(root, recording=Q23B_RECORDING,
                                               problem_id="function-concepts-q23b")
    base = f"/api/search/problems/{directory.name}"
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        (goal,) = first.json()["lesson"]["goals"]
        assert goal["primary"] == "type-function-domain"
        assert "diagnostics" not in goal["d1"], goal["d1"]
        assert "全体实数" not in goal["d1"]["summary"]
        assert "集合外" in goal["d1"]["summary"]
        assert "10" not in "".join(span["text"] for given in goal["d1"]["givens"]
                                  for span in given["quote"])
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
        assert set(snapshot["goals"]) == {"/root/goals/0"}
        assert snapshot["goals"]["/root/goals/0"]["status"] == "solved"
        (handoff,) = snapshot["handoffs"]
        assert handoff["available"] is True
        assert handoff["answer"]["kind"] == "match_domain"
        assert handoff["answer"]["set"]["expression"] == "Interval(-oo, -9/4)"
        assert all(row["status"] != "pending" for row in snapshot["interaction_states"])
        parts = [part for chunk in snapshot["interactions"] for part in chunk["parts"]]
        (conditions,) = [part for part in parts if part["title"] == "列出根号与分母的条件"]
        assert conditions["interaction"]["type"] == "checklist"
        assert len(conditions["interaction"]["slots"]) == 3
        assert conditions["expected_answer"] == {"terms": ["s1o1", "s2o1", "s3o1"]}
        originals = [next(option["label"] for option in slot["options"]
                          if option["value"] == f"s{index}o1")
                     for index, slot in enumerate(conditions["interaction"]["slots"], 1)]
        assert r"\geq" in originals[0] and "m" in originals[0]
        assert r"\geq" in originals[1] and "m" not in originals[1]
        assert r"\neq" in originals[2] and r"\sqrt" in originals[2]
        (reduction,) = [part for part in parts if part["title"] == "合并有意义的条件"]
        assert reduction["expected_answer"] == {"one_of": ["o1"]}
        assert "$x - 1$" in reduction["question"]
        assert next(option["label"] for option in reduction["interaction"]["options"]
                    if option["value"] == "o1") == "$u>0$"
        (universal,) = [part for part in parts if part["title"] == "转化为恒成立问题"]
        assert universal["expected_answer"] == {"one_of": ["o1"]}
        assert "域外原式" in universal["question"] and "分母" in universal["question"]
        assert r"\geq" in universal["question"], "the numerator may be zero at the vertex"
        (borrow,) = [part for part in parts if part["interaction"]["type"] == "plane"]
        assert borrow["expected_answer"] == {"cell": ["interval", "free"], "method": "separation"}
        assert r"\infty" in borrow["question"] and "1" in borrow["question"]
        (returned,) = [part for part in parts if part["title"] == "回到定义域求参"]
        original_goal = next(option["label"] for option in returned["interaction"]["options"]
                             if option["value"] in returned["expected_answer"]["one_of"])
        assert "D_{f}" in original_goal and r"\infty" in original_goal
        assert r"\mathbb{R}" not in original_goal
        events = client.get(stream["events_url"]).json()
        assert events["events"] and events["last_seq"] == snapshot["last_seq"]
        monkeypatch.setattr("shuxueshuo_server.search.stage_three.runner.run_sample", forbidden)
        assert client.post(base + "/lesson/start").json()["stream"] == stream
        assert client.get(stream["snapshot_url"]).json() == snapshot
        assert client.get(base).json()["lesson"]["stream"] == stream
    print(f"Q23b verified photo Stage3: {directory / 'stage-two-1/stage-three'}")
