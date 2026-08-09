"""Durable compare-and-swap authority for extraction attempt ledgers."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Mapping

from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    stable_hash,
)


ATTEMPT_LEDGER_STORE_SCHEMA_VERSION = "extraction-attempt-ledger-store/v1"


class ExtractionAttemptLedgerStore:
    """Persist one authoritative ledger with short optimistic CAS locks."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def transaction(
        self,
        context: ProblemExtractionContext,
        expected: ExtractionAttemptLedger,
    ) -> ExtractionAttemptLedgerTransaction:
        return ExtractionAttemptLedgerTransaction(self, context, expected)

    def load(
        self,
        context: ProblemExtractionContext,
    ) -> ExtractionAttemptLedger:
        lock_path = self._lock_path(context.manifest.context_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                return self._load_unlocked(context)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(
        self,
        context: ProblemExtractionContext,
    ) -> ExtractionAttemptLedger:
        path = self._ledger_path(context.manifest.context_id)
        if not path.exists():
            return ExtractionAttemptLedger.for_context(context)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _ledger_error("$.attempt_ledger_store", str(exc)) from exc
        if not isinstance(payload, Mapping):
            raise _ledger_error("$.attempt_ledger_store", "ledger payload must be an object")
        if payload.get("schema_version") != ATTEMPT_LEDGER_STORE_SCHEMA_VERSION:
            raise _ledger_error(
                "$.attempt_ledger_store.schema_version",
                "unsupported attempt ledger store schema",
            )
        if payload.get("base_context_id") != context.manifest.context_id:
            raise _ledger_error(
                "$.attempt_ledger_store.base_context_id",
                "persisted ledger belongs to another Context",
            )
        attempt_payloads = payload.get("attempts")
        if not isinstance(attempt_payloads, list):
            raise _ledger_error(
                "$.attempt_ledger_store.attempts",
                "attempts must be an array",
            )
        attempts = tuple(
            ExtractionAttemptRecord.from_authority_payload(item)
            for item in attempt_payloads
            if isinstance(item, Mapping)
        )
        if len(attempts) != len(attempt_payloads):
            raise _ledger_error(
                "$.attempt_ledger_store.attempts",
                "every attempt must be an object",
            )
        ledger = ExtractionAttemptLedger(
            base_context_id=context.manifest.context_id,
            attempts=attempts,
        )
        _validate_ledger(context, ledger)
        expected_hash = stable_hash(_ledger_authority_payload(ledger))
        if payload.get("ledger_hash") != expected_hash:
            raise _ledger_error(
                "$.attempt_ledger_store.ledger_hash",
                "persisted attempt ledger hash drifted",
            )
        return ledger

    def _write_unlocked(
        self,
        context: ProblemExtractionContext,
        ledger: ExtractionAttemptLedger,
    ) -> None:
        _validate_ledger(context, ledger)
        authority = _ledger_authority_payload(ledger)
        payload = {
            "schema_version": ATTEMPT_LEDGER_STORE_SCHEMA_VERSION,
            **authority,
            "ledger_hash": stable_hash(authority),
        }
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        target = self._ledger_path(context.manifest.context_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.replace(temporary, target)

    def _ledger_path(self, base_context_id: str) -> Path:
        digest = stable_hash({"base_context_id": base_context_id})
        return self.root / digest[:2] / f"{digest}.json"

    def _lock_path(self, base_context_id: str) -> Path:
        digest = stable_hash({"base_context_id": base_context_id})
        return self.root / "locks" / f"{digest}.lock"


@dataclass
class ExtractionAttemptLedgerTransaction:
    store: ExtractionAttemptLedgerStore
    context: ProblemExtractionContext
    expected: ExtractionAttemptLedger
    ledger: ExtractionAttemptLedger | None = None
    _handle: IO[bytes] | None = None
    _committed: bool = False

    def __enter__(self) -> ExtractionAttemptLedgerTransaction:
        self._acquire()
        try:
            authoritative = self.store._load_unlocked(self.context)
            _require_same_ledger(self.expected, authoritative)
            self.ledger = authoritative
        finally:
            self._release()
        return self

    def commit(self, updated: ExtractionAttemptLedger) -> None:
        if self.ledger is None:
            raise RuntimeError("attempt ledger transaction is not active")
        if self._committed:
            raise RuntimeError("attempt ledger transaction was already committed")
        self._acquire()
        try:
            authoritative = self.store._load_unlocked(self.context)
            _require_same_ledger(self.ledger, authoritative)
            _require_ledger_extension(authoritative, updated)
            self.store._write_unlocked(self.context, updated)
            self._committed = True
        finally:
            self._release()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._release()

    def _acquire(self) -> None:
        if self._handle is not None:
            raise RuntimeError("attempt ledger lock is already held")
        lock_path = self.store._lock_path(self.context.manifest.context_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = lock_path.open("a+b")
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)

    def _release(self) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def _ledger_authority_payload(ledger: ExtractionAttemptLedger) -> dict[str, object]:
    return {
        "base_context_id": ledger.base_context_id,
        "attempts": [item.authority_payload() for item in ledger.attempts],
    }


def _validate_ledger(
    context: ProblemExtractionContext,
    ledger: ExtractionAttemptLedger,
) -> None:
    if ledger.base_context_id != context.manifest.context_id:
        raise _ledger_error(
            "$.attempt_ledger.base_context_id",
            "ledger does not belong to the supplied Context",
        )
    attempt_ids = [item.attempt_id for item in ledger.attempts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise _ledger_error(
            "$.attempt_ledger.attempts",
            "attempt ids must be unique",
        )
    for attempt in ledger.attempts:
        attempt.validate(context.manifest.context_id)


def _require_same_ledger(
    expected: ExtractionAttemptLedger,
    authoritative: ExtractionAttemptLedger,
) -> None:
    if (
        expected.base_context_id != authoritative.base_context_id
        or tuple(item.attempt_hash for item in expected.attempts)
        != tuple(item.attempt_hash for item in authoritative.attempts)
    ):
        raise _ledger_error(
            "$.attempt_ledger.attempts",
            "supplied attempt ledger is stale or was reset",
        )


def _require_ledger_extension(
    previous: ExtractionAttemptLedger,
    updated: ExtractionAttemptLedger,
) -> None:
    prior_hashes = tuple(item.attempt_hash for item in previous.attempts)
    updated_hashes = tuple(item.attempt_hash for item in updated.attempts)
    if (
        previous.base_context_id != updated.base_context_id
        or updated_hashes[: len(prior_hashes)] != prior_hashes
        or len(updated_hashes) != len(prior_hashes) + 1
    ):
        raise _ledger_error(
            "$.attempt_ledger.attempts",
            "transaction must append exactly one attempt",
        )


def _ledger_error(path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(
        "extraction.attempt_ledger_mismatch",
        path,
        message,
    )
