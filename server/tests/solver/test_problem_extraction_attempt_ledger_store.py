from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Barrier

import pytest

from shuxueshuo_server.solver.extraction.attempt_ledger_store import (
    ExtractionAttemptLedgerStore,
)
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ExtractionRetryState,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
)

from _problem_extraction_f3_support import make_f3_fixture


def test_concurrent_compare_and_swap_allows_exactly_one_append(tmp_path) -> None:
    context = _context_with_budget(tmp_path, attempts=3)
    store = ExtractionAttemptLedgerStore(tmp_path / "ledger-store")
    expected = ExtractionAttemptLedger.for_context(context)
    barrier = Barrier(2)

    def append(attempt_index: int):
        barrier.wait()
        try:
            with store.transaction(context, expected) as transaction:
                assert transaction.ledger is not None
                updated = transaction.ledger.append(
                    context,
                    _attempt(context, attempt_index),
                )
                transaction.commit(updated)
            return "committed"
        except ProblemExtractionContextError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(append, (1, 2)))

    assert sorted(outcomes) == [
        "committed",
        "extraction.attempt_ledger_mismatch",
    ]
    assert len(store.load(context).attempts) == 1


@pytest.mark.parametrize("corruption", ("invalid_json", "hash_drift"))
def test_corrupt_or_hash_drifted_ledger_fails_loud(
    tmp_path,
    corruption,
) -> None:
    context = _context_with_budget(tmp_path, attempts=2)
    store = ExtractionAttemptLedgerStore(tmp_path / "ledger-store")
    committed = _append_one(
        store,
        context,
        ExtractionAttemptLedger.for_context(context),
        attempt_index=1,
    )
    ledger_path = next(store.root.rglob("*.json"))
    if corruption == "invalid_json":
        ledger_path.write_text("{", encoding="utf-8")
    else:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        payload["ledger_hash"] = "0" * 64
        ledger_path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    with pytest.raises(ProblemExtractionContextError) as error:
        store.load(context)

    assert committed.attempts
    assert error.value.code == "extraction.attempt_ledger_mismatch"


def test_stale_transaction_failure_releases_lock_for_current_ledger(
    tmp_path,
) -> None:
    context = _context_with_budget(tmp_path, attempts=2)
    store = ExtractionAttemptLedgerStore(tmp_path / "ledger-store")
    empty = ExtractionAttemptLedger.for_context(context)
    first = _append_one(store, context, empty, attempt_index=1)

    with pytest.raises(ProblemExtractionContextError):
        with store.transaction(context, empty):
            raise AssertionError("stale transaction must fail before entering")

    second = _append_one(store, context, first, attempt_index=2)

    assert len(second.attempts) == 2
    assert [item.attempt_hash for item in store.load(context).attempts] == [
        item.attempt_hash for item in second.attempts
    ]


def test_persisted_ledger_resumes_after_store_recreation(tmp_path) -> None:
    context = _context_with_budget(tmp_path, attempts=2)
    root = tmp_path / "ledger-store"
    first_store = ExtractionAttemptLedgerStore(root)
    first = _append_one(
        first_store,
        context,
        ExtractionAttemptLedger.for_context(context),
        attempt_index=1,
    )

    resumed_store = ExtractionAttemptLedgerStore(root)
    restored = resumed_store.load(context)
    second = _append_one(
        resumed_store,
        context,
        restored,
        attempt_index=2,
    )

    assert restored == first
    assert len(second.attempts) == 2
    assert resumed_store.load(context) == second


def _context_with_budget(tmp_path, *, attempts: int):
    _, _, context, _, _ = make_f3_fixture(tmp_path)
    return replace(
        context,
        retry=ExtractionRetryState(
            status=context.retry.status,
            work_item_ids=context.retry.work_item_ids,
            attempt_budget=context.retry.attempts_used + attempts,
            attempts_used=context.retry.attempts_used,
        ),
    )


def _attempt(context, attempt_index: int) -> ExtractionAttemptRecord:
    return ExtractionAttemptRecord(
        attempt_id=f"attempt-store-{attempt_index}",
        base_context_id=context.manifest.context_id,
        provider="recorded",
        route="multimodal",
        input_artifact_refs=(),
        output_artifact_refs=(),
        result="succeeded",
        usage={"attempt_index": attempt_index},
        latency_ms=attempt_index,
    )


def _append_one(
    store,
    context,
    expected,
    *,
    attempt_index,
):
    with store.transaction(context, expected) as transaction:
        assert transaction.ledger is not None
        updated = transaction.ledger.append(
            context,
            _attempt(context, attempt_index),
        )
        transaction.commit(updated)
    return updated
