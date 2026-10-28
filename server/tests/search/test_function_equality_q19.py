"""The retained Q19 photograph reaches M8 and its two-level multiple-choice flow."""

import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from PIL import Image

from shuxueshuo_server.graph_lesson.stage_one import contracts
from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import public_problem_text
from shuxueshuo_server.search.question_image import question_png
from tests.search.function_equality_recording import (
    RECORDING,
    forbidden,
    read,
    replay_recording,
    seed_photo_recording,
)
from tests.search.support import authenticated_client

REPO = Path(__file__).resolve().parents[3]


def test_q19_photo_replays_every_actual_model_turn_and_keeps_original_scoped_functions(tmp_path, monkeypatch):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    manifest = read(RECORDING / "recording.json")
    source_file = REPO / manifest["source"]
    source = read(source_file)
    page = source_file.parent / source["page"]["file"]
    upload = REPO / manifest["upload_source"]
    assert sha256(page.read_bytes()).hexdigest() == source["page"]["sha256"]
    assert sha256(upload.read_bytes()).hexdigest() == manifest["upload_source_sha256"] == source["crop"]["sha256"]
    original = RECORDING / manifest["product_crop_source"]["file"]
    assert sha256(original.read_bytes()).hexdigest() == manifest["product_crop_source"]["sha256"]
    with Image.open(upload) as uploaded, Image.open(original) as cropped:
        assert manifest["product_crop"]["box"] == [0, 0, 1, 1]
        assert list(uploaded.size) == list(cropped.size) == manifest["product_crop"]["page_size"]
        assert question_png(cropped) == (RECORDING / "question.png").read_bytes()
    result = replay_recording(tmp_path / "replay")
    candidate = result["candidate"]
    root = candidate["root"]
    assert not any(root.get(key) for key in ("definitions", "facts", "children"))
    goal, = root["goals"]
    assert (goal["mode"], goal["select_relation"], goal["selection_mode"]) == ("shared_baseline", "equal", "multiple")
    assert goal["shared_functions"] == [{"id": "base", "definition": "f(x)=2*x^2+1"}]
    assert [option["label"] for option in goal["options"]] == list("ABCD")
    assert [option["functions"][0]["definition"] for option in goal["options"]] == [
        "f(x)=x^2+abs(x^2+1)", "f(x)=sqrt((2*x^2+1)^2)",
        "f(x)=abs(2*x^2+1)", "f(x)=((2*x^2+1)*(x+1))/(x+1)",
    ]
    assert not any("domain" in function for option in goal["options"] for function in option["functions"])
    report = NotationValidator().validate_root(root, contracts.schema()["$defs"])
    assert report.ok
    options = report.semantic["goals"][0]["options"]
    assert len({option["left"]["function_ref"] for option in options}) == 1
    assert len({option["right"]["function_ref"] for option in options}) == 4
    assert all(option["left"]["function_ref"] != option["right"]["function_ref"] for option in options)
    assert not any(word in candidate["original_text"] for word in ("解析", "答案", "ABC"))
    recorded_lesson = read(RECORDING / "lesson-verification.json")
    assert (recorded_lesson["status"], recorded_lesson["goal_status"]) == ("completed", "solved")
    assert recorded_lesson["answer"]["correct_labels"] == ["A", "B", "C"]


def test_q19_photo_api_solves_shared_baseline_and_unlocks_exact_multiple_handoff(tmp_path, monkeypatch):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    root = tmp_path / "private-search"
    _, directory = seed_photo_recording(root)
    base = f"/api/search/problems/{directory.name}"
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal, = first.json()["lesson"]["goals"]
        assert goal["primary"] == "type-function-equality", goal
        assert goal["walk"] and goal["walk"]["bundle"]["intro"]
        display = goal["walk"]["bundle"]["problem"]["text"]
        assert "【例5】" not in display
        assert all(f"{label}. " in display for label in "ABCD")
        assert client.post(base + "/lesson/start").status_code == 200
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = client.get(base)
            assert response.status_code == 200, response.text
            lesson = response.json()["lesson"]
            if lesson.get("execution_status") in {"completed", "partial", "failed", "error", "input_error"}:
                break
            time.sleep(0.05)
        assert lesson["execution_status"] == "completed", lesson
        stream = lesson["stream"]
        snapshot_response = client.get(stream["snapshot_url"])
        assert snapshot_response.status_code == 200, snapshot_response.text
        snapshot = snapshot_response.json()
        assert snapshot["goals"]["/root/goals/0"]["status"] == "solved"
        handoff, = snapshot["handoffs"]
        assert handoff["available"] is True
        original = handoff["original_choice"]
        assert original["selection_mode"] == "multiple"
        assert original["correct_labels"] == ["A", "B", "C"]
        assert [row["verdict"] for row in original["option_verdicts"]] == ["equal", "equal", "equal", "different"]
        parts = [part for chunk in snapshot["interactions"] for part in chunk["parts"]]
        verdicts = [part for part in parts if part.get("option_context", {}).get("phase") == "verdict"]
        assert [part["option_context"]["label"] for part in verdicts] == list("ABCD")
        assert all(part["interaction"]["type"] == "choice" and not part.get("case_path") for part in verdicts)
        assert all(row["status"] == "interactive" for row in snapshot["interaction_states"])
        events = client.get(stream["events_url"]).json()
        assert events["events"] and events["last_seq"] == snapshot["last_seq"]
        monkeypatch.setattr("shuxueshuo_server.search.stage_three.runner.run_sample", forbidden)
        assert client.post(base + "/lesson/start").json()["stream"] == stream
        assert client.get(stream["snapshot_url"]).json() == snapshot
        assert client.get(base).json()["lesson"]["stream"] == stream


def test_q19_reviewed_public_text_preserves_y_and_options_without_publishing_internal_aliases(tmp_path):
    result = replay_recording(tmp_path / "replay")
    before = deepcopy(result)
    display = public_problem_text(result)
    assert display == build_identity(result)["statement"]
    assert "【例5】" not in display
    assert "f(" not in display and "g(" not in display
    assert display.count("y=") == 5
    public = result["public_candidate"]["public_content"]["scopes"][0]
    assert display.startswith(" ".join(public["statement"].split()))
    assert all(f"{option['label']}. {option['text']}" in display for option in public["choices"][0]["options"])
    assert "sqrt" in display and "frac" in display
    assert result == before
