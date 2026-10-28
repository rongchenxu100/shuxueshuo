"""Retained original Q20 photograph reaches the authenticated shared lesson."""

import json
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import (
    present_lesson,
    public_problem_text,
    stage_one_result,
)
from shuxueshuo_server.search.question_image import question_png
from tests.search.function_domain_recording import revalidate_recording
from tests.search.support import authenticated_client
from tests.search.test_function_domain_api import forbidden, seed_photo_recording

RECORDING = Path(__file__).parent / "fixtures/function-equality/q20-recorded-20261028"
RECORDINGS = [RECORDING, *(RECORDING.parent / name for name in (
    "q20-browser-recorded-20261028", "q20-browser-reviewfix-20261028",
))]
REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda value: value.name)
def test_q20_photo_keeps_all_options_local_and_preserves_original_operations(recording):
    manifest = json.loads((recording / "recording.json").read_text())
    source_file = REPO / manifest["source"]
    source = json.loads(source_file.read_text())
    page_path = source_file.parent / source["page"]["file"]
    assert sha256(page_path.read_bytes()).hexdigest() == source["page"]["sha256"]
    if "upload_source" in manifest:
        upload = REPO / manifest["upload_source"]
        assert sha256(upload.read_bytes()).hexdigest() == manifest["upload_source_sha256"] == source["crop"]["sha256"]
        crop = recording / manifest["product_crop_source"]["file"]
        assert sha256(crop.read_bytes()).hexdigest() == manifest["product_crop_source"]["sha256"]
        with Image.open(upload) as page, Image.open(crop) as original_crop:
            assert manifest["product_crop"]["box"] == [0, 0, 1, 1]
            assert list(page.size) == list(original_crop.size) == manifest["product_crop"]["page_size"]
            assert question_png(original_crop) == (recording / "question.png").read_bytes()
    else:
        with Image.open(page_path) as page:
            assert question_png(page.crop(source["crop"]["xyxy"])) == (recording / "question.png").read_bytes()
    result = revalidate_recording(recording, problem_id="function-concepts-q20")
    root = result["candidate"]["root"]
    assert root.get("definitions", []) == root.get("facts", []) == root.get("children", []) == []
    goal, = root["goals"]
    assert (goal["kind"], goal["select_relation"], goal["selection_mode"]) == ("compare_functions", "equal", "multiple")
    assert [option["label"] for option in goal["options"]] == list("ABCD")
    expressions = [[function["definition"] for function in option["functions"]] for option in goal["options"]]
    assert expressions == [["f(x)=x", "g(x)=(sqrt(x))^2"], ["f(x)=x^2", "g(x)=(x+1)^2"],
                           ["f(x)=sqrt(x^2)", "g(x)=abs(x)"], ["f(x)=3*x^2-2*x+3", "g(t)=3*t^2-2*t+3"]]
    assert not any(word in result["candidate"]["original_text"] for word in ("解析", "答案", "CD"))
    assert manifest["historical_semantic_calls"] == manifest["historical_network_attempts"] == 2


@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda value: value.name)
def test_q20_photo_api_solves_four_scoped_comparisons_and_exact_multiple_handoff(tmp_path, monkeypatch, recording):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    root = tmp_path / "private-search"
    _, directory = seed_photo_recording(root, recording=recording, problem_id="function-concepts-q20")
    base = f"/api/search/problems/{directory.name}"
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal, = first.json()["lesson"]["goals"]
        assert goal["primary"] == "type-function-equality", goal
        assert goal["walk"] and goal["walk"]["bundle"]["intro"]
        display = goal["walk"]["bundle"]["problem"]["text"]
        assert "【变式】" not in display
        assert all(f"{label}. " in display for label in "ABCD")
        assert client.post(base + "/lesson/start").status_code == 200
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            lesson = client.get(base).json()["lesson"]
            if lesson.get("execution_status") in {"completed", "partial", "failed", "error", "input_error"}:
                break
            time.sleep(0.05)
        assert lesson["execution_status"] == "completed", lesson
        stream = lesson["stream"]
        snapshot = client.get(stream["snapshot_url"]).json()
        assert snapshot["goals"]["/root/goals/0"]["status"] == "solved"
        handoff, = snapshot["handoffs"]
        assert handoff["available"] is True
        original = handoff["original_choice"]
        assert original["selection_mode"] == "multiple"
        assert original["correct_labels"] == ["C", "D"]
        assert [row["verdict"] for row in original["option_verdicts"]] == ["different", "different", "equal", "equal"]
        parts = [part for chunk in snapshot["interactions"] for part in chunk["parts"]]
        verdicts = [part for part in parts if part.get("option_context", {}).get("phase") == "verdict"]
        assert len(verdicts) == 4
        assert [part["option_context"]["label"] for part in verdicts] == list("ABCD")
        assert all(part["interaction"]["type"] == "choice" and not part.get("case_path") for part in verdicts)
        assert all(row["status"] == "interactive" for row in snapshot["interaction_states"])
        monkeypatch.setattr("shuxueshuo_server.search.stage_three.runner.run_sample", forbidden)
        assert client.post(base + "/lesson/start").json()["stream"] == stream
        assert client.get(stream["snapshot_url"]).json() == snapshot
    print(f"Q20 verified photo Stage3: {directory / 'stage-two-1/stage-three'}")


def test_q20_reviewed_public_projection_preserves_source_offsets_and_complete_options(tmp_path):
    result = revalidate_recording(RECORDINGS[-1], problem_id="function-concepts-q20")
    original = deepcopy(result)
    text = result["candidate"]["original_text"]
    assert text.startswith("【变式】")
    envelope = stage_one_result(result, "q20-public-text")
    display = envelope["public_statement"]
    assert display == public_problem_text(result) == build_identity(result)["statement"]
    assert "【变式】" not in display
    public = result["public_candidate"]["public_content"]["scopes"][0]
    assert display.startswith(public["statement"])
    assert all(f"{option['label']}. {option['text']}" in display for option in public["choices"][0]["options"])
    stage_two = run_result(envelope, tmp_path / "stage-two", admission="student_upload")
    assert stage_two["status"] == "completed"
    args = (stage_two, result["features"], text, "q20-public-text")
    source_lesson = present_lesson(*args, candidate=result["candidate"])
    displayed = present_lesson(*args, candidate=result["candidate"], display_text=display)
    assert displayed["goals"][0]["d1"] == source_lesson["goals"][0]["d1"]
    assert displayed["goals"][0]["walk"]["bundle"]["problem"]["text"] == display
    assert result == original
