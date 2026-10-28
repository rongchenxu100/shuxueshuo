"""Replay every retained Q19 extraction/review/repair call with zero model I/O."""

import json
import secrets
import shutil
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.support import session_for

RECORDING = Path(__file__).parent / "fixtures/function-equality/q19-browser-recorded-20261028"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def forbidden(*args, **kwargs):
    raise AssertionError("recorded Q19 replay must not call a model")


def request_content(request):
    """Extract semantic inputs without binding replay to historic prompt wording."""
    parts = request["messages"][1]["content"]
    payload = json.loads(parts[0]["text"])
    return {key: value for key, value in payload.items()
            if key not in ("response_schema", "math_expression_catalog")}


def image_hashes(request):
    return [part["image"]["sha256"] for message in request["messages"]
            if isinstance(message["content"], list)
            for part in message["content"] if "image" in part]


class RecordedWorkflowProvider:
    """No SDK/client/fallback; each workflow request must match its recorded turn."""

    def __init__(self, recording, ledger, image_hash):
        self.recording, self.ledger, self.image_hash = Path(recording), ledger, image_hash
        self.position = 0

    def prepare_request(self, request):
        return replace(request, timeout=300, max_tokens=16384, stream=False,
                       thinking_mode="enabled", reasoning_effort="low")

    def complete(self, request):
        assert self.position < len(self.ledger["calls"]), "workflow requested an unrecorded call"
        call = self.ledger["calls"][self.position]
        expected = read(self.recording / "workflow" / call["directory"] / "request.json")
        actual = request.redacted_payload()
        assert image_hashes(actual) == image_hashes(expected) == [self.image_hash]
        assert request_content(actual) == request_content(expected), call["directory"]
        response = read(self.recording / "workflow" / call["response_file"])
        assert request.contract_version == response["metadata"]["response_format"]
        self.position += 1
        metadata = {**deepcopy(response["metadata"]), "provider": "recorded-deepseek",
                    "replay": True, "file_api_calls": 0,
                    "recorded_elapsed_seconds": response["elapsed_seconds"],
                    "recorded_network_attempts": response["network_attempts"]}
        return SimpleNamespace(text=response["text"], finish_reason=response["finish_reason"],
                               raw_payload=deepcopy(response["raw_payload"]),
                               provider_attempts=tuple({} for _ in range(response["network_attempts"])),
                               metadata_payload=lambda: metadata)


def replay_recording(output, recording=RECORDING):
    """Check provenance, then rerun the real workflow against immutable responses."""
    recording, output = Path(recording), Path(output)
    manifest = read(recording / "recording.json")
    for name, digest in manifest["files"].items():
        assert sha256((recording / name).read_bytes()).hexdigest() == digest
    ledger = read(recording / "workflow/ledger.json")
    png = (recording / "question.png").read_bytes()
    image_hash = sha256(png).hexdigest()
    assert ledger["identity"]["binding"]["images"] == [image_hash]
    calls = ledger["calls"]
    assert [call["stage"] for call in calls] == manifest["call_stages"]
    assert calls[0]["stage"] == "extract" and calls[-1]["stage"] == "review"
    assert all(call["status"] == "completed" for call in calls)
    assert len(calls) == manifest["historical_semantic_calls"]
    assert sum(call["network_attempts"] for call in calls) == manifest["historical_network_attempts"]
    for call in calls:
        name = "workflow/" + call["response_file"]
        response = read(recording / name)
        assert sha256(response["text"].encode()).hexdigest() == manifest["response_text_sha256"][name]
        assert response["metadata"]["provider"] == "deepseek"
        assert response["raw_payload"]["usage"]["total_tokens"] > 0
        assert 1 <= response["network_attempts"] == call["network_attempts"] <= 2
        request = read(recording / "workflow" / call["directory"] / "request.json")
        assert image_hashes(request) == [image_hash]
        payload = request_content(request)
        for field in ("candidate", "base_candidate"):
            if field in payload:
                current = payload[field]
                assert (revision(current) if current is not None else None) == call["base_revision"]
    provider = RecordedWorkflowProvider(recording, ledger, image_hash)
    result = run_question_image(png, output, provider,
                                problem_id=ledger["identity"]["binding"]["problem_id"])
    assert provider.position == len(calls), "workflow skipped retained repair/review evidence"
    assert result["status"] == "reviewed_candidate" and result["source_reviewed"] and result["features_ok"], result
    historical = read(recording / "result.json")
    assert result["public_candidate"] == historical["public_candidate"] == read(recording / "workflow/candidate.json")
    assert result["candidate"] == historical["candidate"]
    assert result["reviewed_candidate_revision"] == revision(result["public_candidate"])
    assert result["question_sha256"] == image_hash and result["sent_image_sha256"] == [image_hash]
    replayed = read(output / "workflow/ledger.json")
    assert [(call["stage"], call["base_revision"]) for call in replayed["calls"]] == [
        (call["stage"], call["base_revision"]) for call in calls]
    review = read(output / "workflow/latest-review.json")
    assert review == read(recording / "workflow/latest-review.json")
    assert review["status"] == "confirmed" and review["findings"] == []
    return result


def seed_photo_recording(root, recording=RECORDING):
    """Use a fresh offline replay, then enter the same owned search API as upload."""
    root = Path(root)
    result = replay_recording(root / "recording-replay", recording)
    session = session_for(root)
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root / "submissions" / search_id
    directory.mkdir(parents=True)
    save(directory / dev_api.RESULT_FILE, result)
    with Image.open(recording / "question.png") as image:
        size = list(image.size)
    save(directory / "crop.json", {"page_id": page_id, "box": [0, 0, 1, 1],
                                   "crop_size": size, "bytes": (recording / "question.png").stat().st_size})
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
