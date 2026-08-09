from __future__ import annotations

from copy import deepcopy

import pytest

from shuxueshuo_server.solver.extraction.context import (
    CONTEXT_SCHEMA_VERSION,
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
)

from _problem_extraction_f2_support import make_fixture


def test_context_v2_root_round_trip_is_deterministic() -> None:
    fixture = make_fixture()
    context = fixture.context
    payload = context.to_payload()

    assert context.manifest.schema_version == CONTEXT_SCHEMA_VERSION
    assert ProblemExtractionContext.from_payload(payload).to_payload() == payload
    assert "decisions" not in payload
    assert set(payload["state"]) == {"artifacts", "evidence", "issues"}


def test_context_hash_tampering_fails_loud() -> None:
    payload = deepcopy(make_fixture().context.to_payload())
    payload["quality"]["tampered"] = True

    with pytest.raises(ProblemExtractionContextError) as error:
        ProblemExtractionContext.from_payload(payload)
    assert error.value.code == "extraction.context_hash_mismatch"


def test_context_v1_payload_is_intentionally_not_supported() -> None:
    payload = deepcopy(make_fixture().context.to_payload())
    payload["manifest"]["schema_version"] = "problem-extraction-context/v1"

    with pytest.raises(ProblemExtractionContextError) as error:
        ProblemExtractionContext.from_payload(payload)
    assert error.value.code == "extraction.context_hash_mismatch"


def test_attempt_budget_and_identity_are_authoritative() -> None:
    context = make_fixture().context
    attempt = ExtractionAttemptRecord(
        attempt_id="attempt-1",
        base_context_id=context.manifest.context_id,
        provider="recorded",
        route="multimodal",
        input_artifact_refs=(),
        output_artifact_refs=(),
        result="succeeded",
        usage={},
        latency_ms=1,
    )
    ledger = ExtractionAttemptLedger.for_context(context).append(context, attempt)
    assert ledger.append(context, attempt) == ledger

    drifted = ExtractionAttemptRecord(
        **{**attempt.__dict__, "latency_ms": 2}
    )
    with pytest.raises(ProblemExtractionContextError):
        ledger.append(context, drifted)


def test_child_requires_the_complete_real_parent_chain() -> None:
    root = make_fixture().context
    child = ProblemExtractionContextBuilder.trusted_child(
        root,
        state=root.state,
        attempt_ledger=ExtractionAttemptLedger.for_context(root),
        event="trusted_test_child",
        producer="test",
        producer_version="v2",
    )

    with pytest.raises(ProblemExtractionContextError):
        ProblemExtractionContext.from_payload(child.to_payload())
    assert ProblemExtractionContext.from_payload(
        child.to_payload(),
        ancestor_contexts=(root,),
    ).to_payload() == child.to_payload()
