"""Revalidate the retained photo responses, without claiming a fresh model call."""

import json
from hashlib import sha256
from pathlib import Path

from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search.extraction import SearchStageOneContract
from shuxueshuo_server.search.identity import (
    EXTRACTION_CONTRACT,
    mathematical_candidate,
)

RECORDING = Path(__file__).parent / "fixtures/function-domain/recorded-20261026"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def revalidate_recording(recording=RECORDING, *, problem_id="function-concepts-q15"):
    recording = Path(recording)
    manifest = read(recording / "recording.json")
    for name, digest in manifest["files"].items():
        assert sha256((recording / name).read_bytes()).hexdigest() == digest
    ledger = read(recording / "workflow/ledger.json")
    image_hash = sha256((recording / "question.png").read_bytes()).hexdigest()
    assert ledger["identity"]["binding"]["images"] == [image_hash]
    assert [call["stage"] for call in ledger["calls"]] == ["extract", "review"]
    responses = []
    for call in ledger["calls"]:
        response = read(recording / "workflow" / call["response_file"])
        assert response["metadata"]["provider"] == "deepseek"
        assert response["finish_reason"] == "stop"
        assert response["raw_payload"]["usage"]["total_tokens"] > 0
        assert response["network_attempts"] == call["network_attempts"] == 1
        request = read(recording / "workflow" / call["directory"] / "request.json")
        images = [part["image"] for message in request["messages"]
                  if isinstance(message["content"], list)
                  for part in message["content"] if "image" in part]
        assert [image["sha256"] for image in images] == [image_hash]
        responses.append(response)
    extracted, reviewed = responses
    public = json.loads(extracted["text"])
    contract = SearchStageOneContract()
    validation = contract.parse(extracted["text"], problem_id=problem_id,
                                source_hash=image_hash, registry=[], store=None)
    assert validation["contract_valid"], validation
    review = contract.validate_review(reviewed["text"], public)
    assert review == {"status": "confirmed", "findings": []}
    assert ledger["calls"][1]["base_revision"] == revision(public)
    candidate = mathematical_candidate(public)
    features = candidate_features(candidate)
    assert features["ok"], features
    return {"status": "reviewed_candidate", "source_reviewed": True,
            "output_contract": EXTRACTION_CONTRACT,
            "public_candidate": public, "candidate": candidate,
            "reviewed_candidate_revision": revision(public),
            "features": features["features"], "features_ok": True,
            "question_sha256": image_hash, "sent_image_sha256": [image_hash]}
