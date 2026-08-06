from __future__ import annotations

import json

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.f3_attempt import F3ExtractionAttemptService
from shuxueshuo_server.solver.extraction.f3_debug import F3AttemptDebugWriter
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL

from _problem_extraction_f3_support import (
    RecordedMultimodalProvider,
    make_f3_fixture,
    valid_candidate_json,
)


EXPECTED_FILES = {
    "attempt-1.prompt.json",
    "attempt-1.prompt.system.md",
    "attempt-1.prompt.user.md",
    "attempt-1.payload.evidence-pack.json",
    "attempt-1.payload.region-index.json",
    "attempt-1.input-manifest.json",
    "attempt-1.input.page-01.png",
    "attempt-1.input-overlay.page-01.png",
    "attempt-1.provider-request.redacted.json",
    "attempt-1.provider-response.json",
    "attempt-1.raw-response.txt",
    "attempt-1.candidate-patch.json",
    "attempt-1.contract-validation.json",
    "attempt-1.llm-metadata.json",
    "attempt-1.attempt-ledger.json",
    "attempt-1.context-before.json",
    "attempt-1.structured-error.json",
    "attempt-1.provider-attempt-1.json",
    "review.html",
}


def execute(tmp_path, text=None):
    _, observation_result, context, store, pack = make_f3_fixture(tmp_path)
    response_text = valid_candidate_json(pack) if text is None else text
    result = F3ExtractionAttemptService(
        input_artifact_reader=store,
        output_artifact_store=ExtractionArtifactStore(tmp_path / "f3-artifacts"),
        provider=RecordedMultimodalProvider(
            response_text,
            model=DEFAULT_DOUBAO_MODEL,
        ),
    ).execute(
        context,
        observation=observation_result.observation,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )
    debug_dir = tmp_path / "debug"
    F3AttemptDebugWriter().write(
        result,
        debug_dir,
        attempt_index=1,
        input_artifact_reader=store,
    )
    return result, pack, debug_dir


def test_debug_attempt_contains_planner_style_trace_and_visual_review(tmp_path) -> None:
    _, pack, debug_dir = execute(tmp_path)

    assert EXPECTED_FILES <= {item.name for item in debug_dir.iterdir()}
    metadata = json.loads((debug_dir / "attempt-1.llm-metadata.json").read_text())
    validation = json.loads((debug_dir / "attempt-1.contract-validation.json").read_text())
    review = (debug_dir / "review.html").read_text()

    assert metadata["thinking_mode"] == "disabled"
    assert metadata["image_count"] == 1
    assert validation["ok"] is True
    assert "Provider 原始响应" in review
    assert "Candidate → evidence" in review
    assert pack.evidence_pack_id


def test_debug_request_never_writes_key_or_base64_image(tmp_path) -> None:
    _, _, debug_dir = execute(tmp_path, "not-json")

    textual = "\n".join(
        path.read_text(encoding="utf-8")
        for path in debug_dir.iterdir()
        if path.suffix in {".json", ".md", ".txt", ".html"}
    ).lower()

    assert "test-key" not in textual
    assert "data:image/" not in textual
    assert ";base64," not in textual
    assert "extraction.multimodal_response_invalid_json" in textual


def test_bad_response_keeps_first_contract_error_and_no_candidate_patch(tmp_path) -> None:
    result, _, debug_dir = execute(tmp_path, "not-json")
    patch = json.loads((debug_dir / "attempt-1.candidate-patch.json").read_text())
    error = json.loads((debug_dir / "attempt-1.structured-error.json").read_text())

    assert not result.ok
    assert patch is None
    assert error["code"] == "extraction.multimodal_response_invalid_json"
