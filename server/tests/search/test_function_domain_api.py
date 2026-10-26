"""Photo-backed extraction replay reaches the actual authenticated search API."""

import secrets
import shutil
import time

import pytest
from PIL import Image

from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two
from tests.search.function_domain_recording import RECORDING, revalidate_recording
from tests.search.support import authenticated_client, session_for


def seed_photo_recording(root, *, recording=RECORDING, problem_id="function-concepts-q15"):
    session = session_for(root)
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root / "submissions" / search_id
    directory.mkdir(parents=True)
    result = revalidate_recording(recording, problem_id=problem_id)
    save(directory / dev_api.RESULT_FILE, result)
    with Image.open(recording / "question.png") as image:
        size = list(image.size)
    save(directory / "crop.json", {
        "page_id": page_id, "box": [0, 0, 1, 1],
        "crop_size": size, "bytes": (recording / "question.png").stat().st_size,
    })
    for name in ("question.png", "original.png"):
        shutil.copyfile(recording / "question.png", directory / name)
    page = root / "pages" / page_id
    page.mkdir(parents=True)
    shutil.copyfile(recording / "question.png", page / "page.png")
    session.repository.register_page(session.user, page_id, {})
    session.repository.create_submission(session.user, search_id, page_id, [0, 0, 1, 1])
    assert session.repository.associate(search_id, build_identity(result))
    run_stage_two(directory, result, provider=forbidden, unsupported_root=root / "unsupported")
    session.repository.set_state(search_id, recognition_state="reviewed", lesson_state="not_started")
    return session, directory


def forbidden(*args, **kwargs):
    raise AssertionError("recorded API replay must not call a model")


@pytest.mark.parametrize("problem_id,recording", [
    ("function-concepts-q15", RECORDING),
    ("function-concepts-q01", RECORDING.parent / "q01-recorded-20261026"),
])
def test_photo_domain_starts_verified_lesson_and_reopens_without_reexecution(tmp_path, monkeypatch, problem_id, recording):
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)
    root = tmp_path / "private-search"
    _session, directory = seed_photo_recording(root, recording=recording, problem_id=problem_id)
    base = f"/api/search/problems/{directory.name}"
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal = first.json()["lesson"]["goals"][0]
        assert goal["primary"] == "type-function-domain"
        reading = goal["walk"]["bundle"]["intro"][0]
        assert reading["question"] == "题目要求“定义域”，也就是要确定什么？"
        assert reading["interaction"]["type"] == "choice"
        assert {option["label"] for option in reading["interaction"]["options"]} == {
            "自变量 $x$ 的取值范围", "函数值 $f(x)$ 的取值范围",
        }
        action = goal["walk"]["replay"]["actions"][0]
        assert isinstance(action["answer"], str)
        assert action["answer"] in reading["expected_answer"]["one_of"]
        assert "使原解析式有意义" in action["reason"]
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
        assert lesson["goals"][0]["walk"]["bundle"]["intro"][0] == reading
        stream = lesson["stream"]
        snapshot = client.get(stream["snapshot_url"]).json()
        assert snapshot["goals"]["/root/goals/0"]["status"] == "solved"
        assert len(snapshot["handoffs"]) == 1
        assert snapshot["math_steps"] and snapshot["interactions"]
        assert all(row["status"] != "pending" for row in snapshot["interaction_states"])
        events = client.get(stream["events_url"]).json()
        assert events["events"] and events["last_seq"] == snapshot["last_seq"]
        monkeypatch.setattr("shuxueshuo_server.search.stage_three.runner.run_sample", forbidden)
        assert client.post(base + "/lesson/start").json()["stream"] == stream
        assert client.get(stream["snapshot_url"]).json() == snapshot
        assert client.get(base).json()["lesson"]["stream"] == stream
