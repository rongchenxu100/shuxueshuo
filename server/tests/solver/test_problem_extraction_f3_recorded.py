from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.f3_attempt import (
    F3ExtractionAttemptService,
)
from shuxueshuo_server.solver.extraction.f3_smoke import (
    F3SmokeSampleResult,
    _batch_summary,
    _coarse_gold_coverage_for_patch,
    _coverage_refs,
)
from shuxueshuo_server.solver.extraction.gold_corpus import load_gold_corpus
from shuxueshuo_server.solver.extraction.multimodal_candidates import (
    parse_candidate_patch,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
)
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL

from _problem_extraction_f3_support import (
    RecordedMultimodalProvider,
    make_f3_fixture,
    valid_candidate_payload,
)


RECORDS_PATH = (
    Path(__file__).parent
    / "fixtures/problem_extraction/f3-recorded-response-cases.json"
)
RECORDS = json.loads(RECORDS_PATH.read_text(encoding="utf-8"))["cases"]
LIVE_RECORDS_ROOT = RECORDS_PATH.parent / "f3-recorded"


@pytest.mark.parametrize("record", RECORDS, ids=lambda item: item["problem_id"])
def test_five_case_recorded_response_replay_is_deterministic(
    tmp_path,
    record,
) -> None:
    _, observation, context, input_store, pack = make_f3_fixture(tmp_path)
    payload = valid_candidate_payload(pack)
    payload["classification"].update(
        {
            "pattern": record["pattern"],
            "problem_type": record["problem_type"],
        }
    )
    payload["transcription_lines"][0]["text"] = record["transcription"]
    response = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    before = context.to_payload()

    first = _execute_recorded(
        tmp_path / "first",
        context,
        observation.observation,
        input_store,
        response,
    )
    second = _execute_recorded(
        tmp_path / "second",
        context,
        observation.observation,
        input_store,
        response,
    )

    assert first.ok and second.ok
    assert context.to_payload() == before
    assert first.candidate_patch == second.candidate_patch
    assert first.validation_report == second.validation_report
    assert first.attempt.authority_payload() == second.attempt.authority_payload()
    assert [item.authority_payload() for item in first.output_artifacts] == [
        item.authority_payload() for item in second.output_artifacts
    ]
    assert first.summary_payload()["candidate_counts"] == {
        "scope": 1,
        "entity": 1,
        "fact": 1,
        "goal": 1,
    }


def test_batch_summary_reports_real_image_and_coverage_metrics() -> None:
    results = tuple(
        F3SmokeSampleResult(
            problem_id=record["problem_id"],
            sample_index=1,
            ok=True,
            attempt_result="succeeded",
            candidate_counts={"scope": 1, "entity": 1, "fact": 1, "goal": 1},
            coarse_coverage={"ratio": 1.0},
            usage={"total_tokens": 10},
            latency_ms=2,
            full_question_image_input=True,
            crop_only_request_count=0,
            handwritten_only_evidence_candidate_count=0,
            model_contract_clean=True,
            normalized_review_region_count=0,
            failures=(),
            sample_dir=f"batch/{record['problem_id']}/sample-01",
        )
        for record in RECORDS
    )
    config = {
        "batch_id": "recorded",
        "provider": "doubao",
        "model": DEFAULT_DOUBAO_MODEL,
        "thinking_mode": "disabled",
        "response_format": "json_object",
    }

    summary = _batch_summary(config, results)

    assert summary["ok"] is True
    assert summary["sample_count"] == 5
    assert summary["full_question_image_input_rate"] == 1.0
    assert summary["crop_only_request_count"] == 0
    assert summary["coarse_gold_evidence_coverage_rate"] == 1.0
    assert summary["coverage_is_semantic_validation"] is False
    assert summary["model_contract_clean_rate"] == 1.0
    assert summary["normalized_review_region_count"] == 0
    assert summary["usage"]["total_tokens"] == 50


@pytest.mark.parametrize("record", RECORDS, ids=lambda item: item["problem_id"])
def test_live_five_case_candidate_patches_replay_against_gold(record) -> None:
    problem_id = record["problem_id"]
    pack_payload = json.loads(
        (LIVE_RECORDS_ROOT / f"{problem_id}.evidence-pack.json").read_text(
            encoding="utf-8"
        )
    )
    raw_response = (LIVE_RECORDS_ROOT / f"{problem_id}.response.json").read_text(
        encoding="utf-8"
    )
    pack = MultimodalEvidencePack.from_payload(pack_payload)

    first, first_report = parse_candidate_patch(raw_response, pack)
    second, second_report = parse_candidate_patch(raw_response, pack)

    assert pack.to_payload() == pack_payload
    assert first_report.ok and second_report.ok
    assert first is not None and second is not None
    assert first.patch_id == second.patch_id
    assert first.to_payload() == second.to_payload()
    assert {item.candidate_type for item in first.candidates} == {
        "scope",
        "entity",
        "fact",
        "goal",
    }
    assert not any(
        candidate.evidence_refs
        and all(pack.evidence_by_id[ref].origin == "handwritten" for ref in candidate.evidence_refs)
        for candidate in first.candidates
    )
    case = next(
        item for item in load_gold_corpus().cases if item.problem_id == problem_id
    )
    coverage = _coarse_gold_coverage_for_patch(case, pack, first)
    assert coverage["ratio"] == 1.0, coverage


def test_live_raw_response_shape_runs_through_full_attempt_service(tmp_path) -> None:
    """Replay a real provider payload through request, provider, and parser layers."""

    _, observation, context, input_store, pack = make_f3_fixture(tmp_path)
    raw = json.loads(
        (LIVE_RECORDS_ROOT / "tj-2026-hexi-yimo-25.response.json").read_text(
            encoding="utf-8"
        )
    )
    printed = next(item for item in pack.region_index if item.origin == "printed")
    evidence_aliases, region_aliases = pack.prompt_reference_aliases()
    rebound = _rebind_recorded_response(
        raw,
        base_context_id=pack.base_context_id,
        evidence_pack_id=pack.evidence_pack_id,
        evidence_ref=evidence_aliases[printed.evidence_id],
        region_ref=region_aliases[printed.region_id],
    )

    result = _execute_recorded(
        tmp_path / "full-recorded",
        context,
        observation.observation,
        input_store,
        json.dumps(rebound, ensure_ascii=False),
    )

    assert result.ok
    assert result.candidate_patch is not None
    assert len(result.candidate_patch.candidates) == len(raw["candidates"])
    assert result.candidate_patch.classification.pattern == raw["classification"][
        "pattern"
    ]
    assert result.provider_response is not None
    assert result.validation_report.ok


def test_printed_subregion_can_cover_broad_mixed_gold_region() -> None:
    candidate = SimpleNamespace(
        evidence_refs=("printed_subregion",),
        review_region_refs=(),
    )

    assert _coverage_refs(candidate, (), "mixed") == ("printed_subregion",)


def _execute_recorded(
    output_root,
    context,
    observation,
    input_store,
    response,
):
    return F3ExtractionAttemptService(
        input_artifact_reader=input_store,
        output_artifact_store=ExtractionArtifactStore(output_root / "artifacts"),
        provider=RecordedMultimodalProvider(
            response,
            model=DEFAULT_DOUBAO_MODEL,
        ),
    ).execute(
        context,
        observation=observation,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )


def _rebind_recorded_response(
    payload,
    *,
    base_context_id,
    evidence_pack_id,
    evidence_ref,
    region_ref,
):
    result = json.loads(json.dumps(payload))
    result["base_context_id"] = base_context_id
    result["evidence_pack_id"] = evidence_pack_id

    def rebind(value):
        if isinstance(value, dict):
            rebound = {}
            for key, item in value.items():
                if key == "evidence_refs" and isinstance(item, list):
                    rebound[key] = [evidence_ref] if item else []
                elif key == "review_region_refs" and isinstance(item, list):
                    rebound[key] = [region_ref] if item else []
                else:
                    rebound[key] = rebind(item)
            return rebound
        if isinstance(value, list):
            return [rebind(item) for item in value]
        return value

    return rebind(result)
