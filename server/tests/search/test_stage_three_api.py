"""Recorded Q01 reaches real product streams without image extraction or live LLM calls."""

import json
import secrets
import shutil
import threading
import time
from copy import deepcopy

import pytest

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_two.runner import replay_run
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api, stage_three
from tests.search.support import (
    authenticated_client,
    execution_scope,
    execution_store,
    session_for,
)
from tests.search.test_lesson import search_result
from tests.solver.test_graph_stage_three_recorded import Q01_SELECTION

TARGET = "/root/goals/0"


def forbidden(*args, **kwargs):
    raise AssertionError("read-only search views must not start extraction, solving or a live LLM")


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    monkeypatch.delenv("RUN_LLM_INTEGRATION", raising=False)
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory", forbidden)
    monkeypatch.setattr(dev_api, "run_question_image", forbidden)


def seed(tmp_path, *, refresh_features=False):
    """Register a recorded private lesson; it does not claim a public identity review."""
    root = tmp_path / "search"
    session = session_for(root)
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root / "submissions" / search_id
    directory.mkdir(parents=True)
    value = {**search_result("q01"), "question_sha256": "recorded", "sent_image_sha256": ["recorded"]}
    save(directory / dev_api.RESULT_FILE, value)
    save(directory / "crop.json", {"page_id": page_id})
    result = replay_run(Q01_SELECTION, directory / "stage-two-1", refresh_features=refresh_features)
    assert result["replay_comparison"]["ok"] and result["llm"]["new_network_attempts"] == 0
    shutil.copyfile(directory / "stage-two-1/source.png", directory / "question.png")
    shutil.copyfile(directory / "question.png", directory / "original.png")
    page = root / "pages" / page_id
    page.mkdir()
    shutil.copyfile(directory / "question.png", page / "page.png")
    session.repository.register_page(session.user, page_id, {})
    session.repository.create_submission(session.user, search_id, page_id, [0, 0, 1, 1])
    session.repository.set_state(search_id, recognition_state="reviewed", lesson_state="not_started")
    return root, directory


def client_for(root, *, hooks=None):
    client = authenticated_client(root, hooks=hooks)
    client.search_id = session_for(root).search_id
    return client


def status(client):
    response = client.get(f"/api/search/problems/{client.search_id}")
    assert response.status_code == 200, response.text
    return response.json()["lesson"]


def wait_done(client):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = status(client)
        if value.get("execution_status") in ("completed", "partial", "failed", "error", "input_error"):
            assert value["execution_status"] == "completed", value
            return value
        time.sleep(0.025)
    pytest.fail("stage-three search execution did not complete")


def start(client):
    response = client.post(f"/api/search/problems/{client.search_id}/lesson/start")
    assert response.status_code == 200, response.text
    return wait_done(client)


def test_open_upgrades_teaching_without_ocr_and_preserves_historical_run(tmp_path, monkeypatch):
    root, directory = seed(tmp_path, refresh_features=True)
    with client_for(root) as client:
        old = start(client)
        old_id = old['stream']['run_id']
        old_snapshot = client.get(old['stream']['snapshot_url']).json()
        monkeypatch.setattr(stage_three, 'teaching_revision', lambda: 'new-shared-flow')
        # A GET continues to show the captured version without starting work.
        assert status(client)['stream']['run_id'] == old_id
        assert len(stage_three.attempts(directory)) == 1
        response = client.post(f'/api/search/problems/{client.search_id}/lesson/current')
        assert response.status_code == 200 and response.json()['updating'] is True
        new = wait_done(client)
        assert new['stream']['run_id'] != old_id
        assert client.get(old['stream']['snapshot_url']).json() == old_snapshot
        attempt = stage_three.latest_attempt(directory)
        assert stage_three.read(attempt/stage_three.RESULT)['llm']['new_network_attempts'] == 0
        assert not stage_three.needs_teaching_update(attempt)
        response = client.post(f'/api/search/problems/{client.search_id}/lesson/current')
        assert response.status_code == 200 and response.json()['updating'] is False
        assert len(stage_three.attempts(directory)) == 2


def test_status_pins_material_and_stream_to_one_attempt_during_concurrent_retry(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)
    first_run_id, second_run_id = secrets.token_hex(16), secrets.token_hex(16)

    def stream(attempt, run_id):
        output = attempt / "stage-three"
        frozen = {"implementation": {"recording": "b" * 64}}
        seed = {"run_id": run_id, "lesson_version": "lesson-" + run_id,
                "stage_one": {"sha256": "c" * 64}, "stage_two": {"sha256": "d" * 64}}
        save(output / "run.json", seed)
        save(output / "frozen.json", frozen)
        with execution_scope(root):
            EventStore(output, {"run_id": run_id, "lesson_version": seed["lesson_version"],
                                "input_sha256": revision({"stage_one": "c" * 64, "stage_two": "d" * 64}),
                                "revisions": frozen["implementation"]}, create=True)

    stream(directory / "stage-two-1", first_run_id)
    present = dev_api.present_lesson
    published = False

    def publish_retry_between_material_read_and_stream_read(stage_two, *args, **kwargs):
        nonlocal published
        rendered = present(stage_two, *args, **kwargs)
        if not published:
            published = True
            second = deepcopy(stage_two)
            second["goals"][0]["primary"] = "type-amgm-quantified"
            for option in second["goals"][0]["d2"]["options"]:
                if option["role"] in {"primary", "alternative"}:
                    option["role"] = "primary" if option["type_id"] == "type-amgm-quantified" else "alternative"
            attempt = directory / "stage-two-2"
            save(attempt / stage_three.RESULT, second)
            stream(attempt, second_run_id)
        return rendered

    monkeypatch.setattr(dev_api, "present_lesson", publish_retry_between_material_read_and_stream_read)
    with client_for(root) as client:
        first = status(client)
        assert first["goals"][0]["primary"] == "type-quantified-quadratic"
        assert first["stream"]["run_id"] == first_run_id
        second = status(client)
        assert second["goals"][0]["primary"] == "type-amgm-quantified"
        assert second["stream"]["run_id"] == second_run_id
        assert client.get(first["stream"]["snapshot_url"]).json()["run_id"] == first_run_id
        assert client.get(second["stream"]["snapshot_url"]).json()["run_id"] == second_run_id


@pytest.mark.parametrize("operation", ["start", "resume"])
def test_start_and_resume_recheck_attempt_after_acquiring_problem_lease(tmp_path, monkeypatch, operation):
    root, directory = seed(tmp_path)
    run_id = secrets.token_hex(16)
    if operation == "resume":
        # The run identity is already durable, but no route has been submitted.
        output = directory / "stage-two-1/stage-three"
        save(output / "run.json", {"run_id": run_id, "lesson_version": "existing-lesson"})
        save(output / "frozen.json", {"implementation": stage_three.fingerprint()})
        with execution_scope(root):
            EventStore(output, {'run_id': run_id, 'lesson_version': 'existing-lesson', 'input_sha256': 'a' * 64,
                                'revisions': {'fixture': 'b' * 64}}, create=True)
    original_acquire = stage_three.acquire_problem

    def retry_finishes_before_lease_acquisition(problem):
        second = problem / "stage-two-2"
        second.mkdir()
        shutil.copyfile(problem / "stage-two-1" / stage_three.RESULT, second / stage_three.RESULT)
        return original_acquire(problem)

    monkeypatch.setattr(stage_three, "acquire_problem", retry_finishes_before_lease_acquisition)
    monkeypatch.setattr(stage_three, "run_stage_three", forbidden)
    monkeypatch.setattr(stage_three, "resume_stage_three", forbidden)
    suffix = "start" if operation == "start" else run_id + "/resume"
    with client_for(root) as client:
        response = client.post(f"/api/search/problems/{directory.name}/lesson/{suffix}")
        assert response.status_code == 409
        assert response.json() == {"detail": "lesson.stale_run"}
        assert not (directory / "stage-two-2/stage-three").exists()
        # A rejected stale request must release its acquired lease immediately.
        stage_three.release_problem(original_acquire(directory))


def test_real_recorded_two_routes_stream_while_running_and_refresh_never_recomputes(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)
    reached, release = threading.Event(), threading.Event()

    def before_verification(state, _store):
        if state["route_id"] == "discriminant":
            reached.set()
            assert release.wait(8), "test did not release the first route"

    with client_for(root, hooks={"before_verification": before_verification}) as client:
        try:
            response = client.post(f"/api/search/problems/{directory.name}/lesson/start")
            assert response.status_code == 200
            assert reached.wait(8)
            current = status(client)
            assert current["status"] == "completed" and current["execution_status"] == "running"
            assert current["goals"][0]["d1"]["rows"] and current["goals"][0]["d2"]
            stream = current["stream"]
            snapshot = client.get(stream["snapshot_url"]).json()
            assert snapshot["math_steps"] and not snapshot["handoffs"] and not snapshot["goals"]
            assert snapshot["contract"] == "graph-stage-three-snapshot/v2"
            assert "revisions" not in snapshot and len(snapshot["revisions_ref"]) == 64
            assert snapshot["trajectories"]
            assert all("driver_state" not in row and "frames" not in row for row in snapshot["checkpoints"])
            assert all(card["contract"] == "graph-math-step/v2" and "revisions" not in card
                       for card in snapshot["math_steps"])
            first_page = client.get(stream["events_url"], params={"after_seq": 0}).json()
            with client.websocket_connect(stream["websocket_url"] + "?after=0") as socket:
                assert socket.receive_json() == first_page
            assert client.post(stream["snapshot_url"].removesuffix("/snapshot") + "/resume").status_code == 409
            # The lock is persistent, so another router instance cannot start
            # a concurrent resume just because its in-memory queue is empty.
            with client_for(root) as other:
                assert status(other)["execution_status"] == "running"
                assert other.post(stream["snapshot_url"].removesuffix("/snapshot") + "/resume").status_code == 409
        finally:
            release.set()
        completed = wait_done(client)
        snapshot = client.get(completed["stream"]["snapshot_url"]).json()
        assert {row["route_id"] for row in snapshot["checkpoints"] if row["status"] == "verified"} == {
            "discriminant", "extremum",
        }
        assert len(snapshot["handoffs"]) == 2 and snapshot["goals"][TARGET]["status"] == "solved"
        marker = (snapshot["last_seq"], [step["math_step_sha256"] for step in snapshot["math_steps"]])
        monkeypatch.setattr(runner, "run_sample", forbidden)
        monkeypatch.setattr(dev_api, "run_stage_two", forbidden)
        for _ in range(2):
            assert status(client)["stream"] == completed["stream"]
            assert client.get(completed["stream"]["snapshot_url"]).json() == snapshot
        assert client.post(f"/api/search/problems/{directory.name}/lesson/start").json()["stream"] == completed["stream"]
        resume_url = completed["stream"]["snapshot_url"].removesuffix("/snapshot") + "/resume"
        assert client.post(resume_url).json()["status"] == "completed"
        stable = execution_store(root, directory / "stage-two-1/stage-three").snapshot()
        assert (stable["last_seq"], [step["math_step_sha256"] for step in stable["math_steps"]]) == marker


def test_http_ws_cursor_expiry_and_snapshot_recovery_share_authoritative_store(tmp_path):
    root, directory = seed(tmp_path)
    with client_for(root) as client:
        lesson = start(client)
        stream = lesson["stream"]
        all_events = client.get(stream["events_url"]).json()["events"]
        middle = all_events[len(all_events) // 2]["seq"]
        expected = client.get(stream["events_url"], params={"after_seq": middle}).json()
        with client.websocket_connect(stream["websocket_url"] + f"?after={middle}") as socket:
            assert socket.receive_json() == expected
        durable = execution_store(root, directory / "stage-two-1/stage-three")
        before = durable.snapshot()
        durable.prune_events(middle)
        expired = client.get(stream["events_url"], params={"after_seq": 0})
        assert expired.status_code == 409
        assert expired.json() == {"error": "events.cursor_expired", "cursor_expired": True, "minimum_seq": middle + 1}
        with client.websocket_connect(stream["websocket_url"] + "?after=0") as socket:
            assert socket.receive_json() == expired.json()
        after = client.get(stream["snapshot_url"]).json()
        for key in ("math_steps", "handoffs", "goals", "selection_chunks"):
            assert after[key] == before[key]
        assert after["last_seq"] == before["last_seq"]
        assert client.get(stream["events_url"], params={"after_seq": after["last_seq"] + 1}).status_code == 400
        assert client.get(stream["events_url"], params={"after_seq": -1}).status_code == 400


def test_explicit_retry_automatically_runs_stage_three_and_isolates_old_run(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)
    calls = []

    def recorded_stage_two(output, _result, **_kwargs):
        attempt = output / f"stage-two-{len(stage_three.attempts(output)) + 1}"
        calls.append(str(attempt))
        return replay_run(Q01_SELECTION, attempt)

    monkeypatch.setattr(dev_api, "run_stage_two", recorded_stage_two)
    monkeypatch.setattr("shuxueshuo_server.graph_lesson.stage_two.selection.live_provider_factory", lambda: forbidden)
    with client_for(root) as client:
        first = start(client)["stream"]
        old_snapshot = client.get(first["snapshot_url"]).json()
        assert client.post(f"/api/search/problems/{directory.name}/lesson").status_code == 200
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = status(client)
            if (current.get("stream") or {}).get("run_id") not in (None, first["run_id"]):
                break
            time.sleep(0.025)
        second = wait_done(client)["stream"]
        assert second["run_id"] != first["run_id"] and second["lesson_version"] != first["lesson_version"]
        assert calls == [str(directory / "stage-two-2")]
        assert client.get(first["snapshot_url"]).json() == old_snapshot
        assert client.post(first["snapshot_url"].removesuffix("/snapshot") + "/resume").json() == {
            "detail": "lesson.stale_run",
        }
        old = client.get(first["events_url"]).json()
        new = client.get(second["events_url"]).json()
        assert all(event["run_id"] == first["run_id"] for event in old["events"])
        assert all(event["run_id"] == second["run_id"] for event in new["events"])
        assert client.get(first["snapshot_url"].replace(directory.name, "c" * 12)).status_code == 404


def test_explicit_resume_continues_same_partial_run_and_rejects_changed_revision(tmp_path, monkeypatch):
    root, directory = seed(tmp_path)

    class Interrupted(BaseException):
        pass

    def interrupt(_state, _store):
        raise Interrupted()

    with execution_scope(root), pytest.raises(Interrupted):
        stage_three.run_stage_three(directory / "stage-two-1", hooks={"before_verification": interrupt})
    with client_for(root) as client:
        partial = status(client)
        assert partial["execution_status"] == "interrupted"
        stream = partial["stream"]
        prefix = client.get(stream["events_url"]).json()["events"]
        resume_url = stream["snapshot_url"].removesuffix("/snapshot") + "/resume"
        original = stage_three.fingerprint
        monkeypatch.setattr(stage_three, "fingerprint", lambda: {"changed.py": "different"})
        assert client.post(resume_url).json() == {"detail": "checkpoint.revisions_changed"}
        # Stored history remains readable even when this implementation cannot resume it.
        assert client.get(stream["events_url"]).json()["events"] == prefix
        monkeypatch.setattr(stage_three, "fingerprint", original)
        assert client.post(resume_url).status_code == 200
        completed = wait_done(client)
        assert completed["stream"] == stream
        after = client.get(stream["events_url"]).json()["events"]
        assert after[:len(prefix)] == prefix
        assert len({event["event_id"] for event in after}) == len(after)
        assert len(list(directory.glob("stage-two-*/stage-three"))) == 1
        assert not any(json.loads((directory / "stage-two-1/stage-three/stage-three-result.json").read_text())["llm"].values())
