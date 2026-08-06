from __future__ import annotations

from dataclasses import replace
import inspect

import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionRetryState,
)
from shuxueshuo_server.solver.extraction.f3_attempt import (
    F3ExtractionAttemptService,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalProviderError,
    ProviderSubAttempt,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
)
from shuxueshuo_server.solver.runtime.config import DEFAULT_DOUBAO_MODEL

from _problem_extraction_f3_support import (
    RecordedMultimodalProvider,
    make_f3_fixture,
    valid_candidate_json,
)


class FakeProvider(RecordedMultimodalProvider):
    def __init__(self, text: str = "", error: Exception | None = None):
        super().__init__(text, model=DEFAULT_DOUBAO_MODEL)
        self.error = error

    def complete(self, request):
        if self.error is not None:
            self.calls += 1
            raise self.error
        return super().complete(request)


def service(tmp_path, store, provider):
    return F3ExtractionAttemptService(
        input_artifact_reader=store,
        output_artifact_store=ExtractionArtifactStore(tmp_path / "f3-artifacts"),
        provider=provider,
    )


def execute(service, context, *, observation):
    return service.execute(
        context,
        observation=observation,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )


def test_successful_attempt_records_patch_without_mutating_context(tmp_path) -> None:
    _, result, context, store, pack = make_f3_fixture(tmp_path)
    provider = FakeProvider(valid_candidate_json(pack))
    before = context.to_payload()

    attempt = execute(
        service(tmp_path, store, provider),
        context,
        observation=result.observation,
    )

    assert attempt.ok
    assert attempt.context is context
    assert context.to_payload() == before
    assert attempt.attempt.route == "multimodal"
    assert attempt.attempt.result == "succeeded"
    assert attempt.candidate_patch is not None
    assert {item.kind for item in attempt.input_artifacts} >= {
        "selection_crop",
        "source_observation",
        "multimodal_evidence_pack",
        "multimodal_region_index",
    }
    assert {item.kind for item in attempt.output_artifacts} >= {
        "multimodal_raw_response",
        "multimodal_provider_response",
        "multimodal_candidate_patch",
        "multimodal_contract_validation",
    }
    assert len(attempt.attempt_ledger.attempts) == 1


def test_bad_json_is_a_failed_attempt_not_a_context_child(tmp_path) -> None:
    _, result, context, store, _ = make_f3_fixture(tmp_path)
    provider = FakeProvider("not-json")

    attempt = execute(
        service(tmp_path, store, provider),
        context,
        observation=result.observation,
    )

    assert not attempt.ok
    assert attempt.context is context
    assert attempt.attempt.result == "invalid_json"
    assert attempt.candidate_patch is None
    assert attempt.structured_error["code"] == "extraction.multimodal_response_invalid_json"


def test_length_finish_reason_is_reported_as_typed_truncation(tmp_path) -> None:
    _, result, context, store, pack = make_f3_fixture(tmp_path)
    provider = FakeProvider(valid_candidate_json(pack))
    original_complete = provider.complete

    def truncated(request):
        return replace(original_complete(request), finish_reason="length")

    provider.complete = truncated

    attempt = execute(
        service(tmp_path, store, provider),
        context,
        observation=result.observation,
    )

    assert not attempt.ok
    assert attempt.candidate_patch is None
    assert attempt.validation_report.issues[0].code == (
        "extraction.multimodal_provider_output_truncated"
    )


def test_provider_failure_is_audited_without_semantic_patch(tmp_path) -> None:
    _, result, context, store, _ = make_f3_fixture(tmp_path)
    subattempt = ProviderSubAttempt(
        provider_attempt=1,
        status="error",
        response_model=None,
        usage=None,
        finish_reason=None,
        visible_content=False,
        latency_ms=3,
        error_code="extraction.multimodal_provider_timeout",
        error_message="timeout",
    )
    provider = FakeProvider(
        error=MultimodalProviderError(
            "extraction.multimodal_provider_timeout",
            "timeout",
            result="timeout",
            provider_attempts=(subattempt,),
        )
    )

    attempt = execute(
        service(tmp_path, store, provider),
        context,
        observation=result.observation,
    )

    assert not attempt.ok
    assert attempt.attempt.result == "timeout"
    assert attempt.candidate_patch is None
    assert attempt.structured_error["code"] == "extraction.multimodal_provider_timeout"


def test_attempt_budget_is_checked_before_provider_call(tmp_path) -> None:
    _, result, context, store, _ = make_f3_fixture(tmp_path)
    provider = FakeProvider("{}")
    exhausted = replace(
        context,
        retry=ExtractionRetryState(
            status=context.retry.status,
            work_item_ids=context.retry.work_item_ids,
            attempt_budget=context.retry.attempts_used,
            attempts_used=context.retry.attempts_used,
        ),
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        service(tmp_path, store, provider).execute(
            exhausted,
            observation=result.observation,
            attempt_ledger=ExtractionAttemptLedger.for_context(exhausted),
        )

    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert provider.calls == 0


def test_attempt_service_requires_cumulative_ledger_from_caller() -> None:
    parameter = inspect.signature(
        F3ExtractionAttemptService.execute
    ).parameters["attempt_ledger"]

    assert parameter.default is inspect.Parameter.empty


def test_second_attempt_must_carry_cumulative_ledger_and_respects_budget(
    tmp_path,
) -> None:
    _, result, context, store, pack = make_f3_fixture(tmp_path)
    provider = FakeProvider(valid_candidate_json(pack))
    one_remaining = replace(
        context,
        retry=ExtractionRetryState(
            status=context.retry.status,
            work_item_ids=context.retry.work_item_ids,
            attempt_budget=context.retry.attempts_used + 1,
            attempts_used=context.retry.attempts_used,
        ),
    )
    ledger = ExtractionAttemptLedger.for_context(one_remaining)
    first = service(tmp_path, store, provider).execute(
        one_remaining,
        observation=result.observation,
        attempt_ledger=ledger,
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        service(tmp_path, store, provider).execute(
            one_remaining,
            observation=result.observation,
            attempt_ledger=first.attempt_ledger,
        )

    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert provider.calls == 1
