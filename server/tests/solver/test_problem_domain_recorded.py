from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalProviderRequest,
    MultimodalProviderResponse,
    ProviderSubAttempt,
)
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    ProblemDomainExtractionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)

from _problem_extraction_f3_support import make_f3_fixture


ROOT = Path(__file__).resolve().parents[3]
EXPECTED_IDENTITIES = {
    "tj-2026-heping-ermo-25": (
        "problem-revision:9dfcc08df320f779fde2706c12f04dcdf64d3503879ef11d3f06d9de431e5698",
        "a7dd9eb1f06eec5385909a38c7c387ec44932153514293b25cce6a433db54aa7",
    ),
    "tj-2026-heping-yimo-25": (
        "problem-revision:a699f5bb0dad4e50f431bd62aed9d40bdb8030cf9f9403fed2e58e9d4fcc83ee",
        "450953bbd7797da4ff2ae05006cf8faa14037364cbbb773e5d7d968eddddba58",
    ),
    "tj-2026-hexi-yimo-25": (
        "problem-revision:7da2c35c8b6523b8f7ddeabd1d93e1724f10a111b63ddefa29c9cd5e783340b4",
        "6bd16268033943d569e536ce4e04b1cd7a2321c528d1c475e509cbf04d80eb25",
    ),
    "tj-2026-nankai-yimo-25": (
        "problem-revision:4aad5615f12b11f6f861f7502e715b211b80ab6188efb1fbbb8f386197d8bdec",
        "8d66378678912def5acb4dd6e4a4ecf98ab166b89ed7d39f2fda6db999f73265",
    ),
    "tj-2026-xiqing-yimo-25": (
        "problem-revision:23569dc0db8acf3ca5d8c831bf80487ab0e9262e40ec35953f1f45469ae454d6",
        "b0b934b687c5c55cf2a394e7b6d4fa708f11d42a11bc1c57bfbb9605bf944bf1",
    ),
}


class _SourceIndependentValidator(ProblemDomainValidator):
    def validate(self, draft, *, evidence_pack=None, expected_problem_id=None):
        return super().validate(draft, expected_problem_id=expected_problem_id)


@dataclass
class _RecordedProvider:
    response_text: str
    model: str = "recorded-problem-domain"
    provider_name: str = "recorded"
    supports_images: bool = True
    response_format_mode: str = "json_schema"

    def complete(self, request: MultimodalProviderRequest) -> MultimodalProviderResponse:
        return MultimodalProviderResponse(
            text=self.response_text,
            raw_payload={"model": self.model, "content": self.response_text},
            request_model=self.model,
            response_model=self.model,
            usage={"total_tokens": 1},
            finish_reason="stop",
            provider_attempts=(
                ProviderSubAttempt(
                    provider_attempt=1,
                    status="completed",
                    response_model=self.model,
                    usage={"total_tokens": 1},
                    finish_reason="stop",
                    visible_content=True,
                    latency_ms=1,
                ),
            ),
            latency_ms=1,
            thinking_mode=request.thinking_mode,
            reasoning_effort=request.reasoning_effort,
            contract_version=request.contract_version,
        )


@pytest.mark.parametrize("case", tuple(EXPECTED_IDENTITIES))
def test_five_authored_domain_payloads_replay_without_hash_drift(case: str) -> None:
    payload = json.loads(
        (ROOT / "internal/problem-domain-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )
    first = ProblemDraft.create(payload)
    second = ProblemDraft.create(
        json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    )
    validation = ProblemDomainValidator().validate(first)

    assert (first.revision_id, first.semantic_hash) == EXPECTED_IDENTITIES[case]
    assert second.to_payload() == first.to_payload()
    assert validation.report.ok, validation.report.to_payload()
    assert validation.projection is not None


@pytest.mark.parametrize("case", tuple(EXPECTED_IDENTITIES))
def test_five_authored_raw_responses_replay_through_extraction_service(
    case: str,
    tmp_path: Path,
) -> None:
    payload = json.loads(
        (ROOT / "internal/problem-domain-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )
    payload["problem_id"] = "synthetic-f2"
    response_text = json.dumps(payload, ensure_ascii=False)

    def execute(root: Path):
        fixture, _, context, store, _ = make_f3_fixture(root)
        result = ProblemDomainExtractionService(
            input_artifact_reader=store,
            output_artifact_store=store,
            provider=_RecordedProvider(response_text),
            validator=_SourceIndependentValidator(),
        ).run(
            context,
            attempt_ledger=ExtractionAttemptLedger.for_context(context),
            ancestor_contexts=(fixture.context,),
        )
        assert result.accepted
        assert result.verified_problem is not None
        assert result.solver_projection is not None
        assert len(result.attempts) == 1
        assert result.attempts[0].request.contract_version == "problem-domain/v1"
        assert [item.role for item in result.attempts[0].request.images] == ["primary"]
        return result

    first = execute(tmp_path / "first")
    second = execute(tmp_path / "second")

    assert first.verified_problem.to_payload() == second.verified_problem.to_payload()
    assert first.solver_projection.to_payload() == second.solver_projection.to_payload()
    assert first.final_context.manifest.context_id == second.final_context.manifest.context_id


@pytest.mark.parametrize("case", tuple(EXPECTED_IDENTITIES))
def test_domain_wire_is_at_most_75_percent_of_flat_solver_fixture(case: str) -> None:
    domain = json.loads(
        (ROOT / "internal/problem-domain-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )
    solver = json.loads(
        (ROOT / "internal/solver-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )["input"]
    domain_bytes = len(
        json.dumps(domain, ensure_ascii=False, separators=(",", ":")).encode()
    )
    solver_bytes = len(
        json.dumps(solver, ensure_ascii=False, separators=(",", ":")).encode()
    )

    assert domain_bytes <= solver_bytes * 0.75
