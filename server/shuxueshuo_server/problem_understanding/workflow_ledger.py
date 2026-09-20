"""Crash-safe at-most-once call reservations for the isolated workflow."""

import fcntl
import json
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter

from .identity import revision


class WorkflowStop(ValueError):
    pass


@dataclass(frozen=True)
class Budget:
    content: int = 3
    review: int = 3
    semantic: int = 6
    network: int = 12

    def __post_init__(self):
        for key, ceiling in (
            ("content", 3),
            ("review", 3),
            ("semantic", 6),
            ("network", 12),
        ):
            if not 1 <= getattr(self, key) <= ceiling:
                raise ValueError("workflow.invalid_budget")


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(
            json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()
        )
        f.flush()
        os.fsync(f.fileno())
        temp = f.name
    os.replace(temp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


class Ledger:
    def __init__(self, directory, binding, budget):
        self.directory, self.binding, self.budget = Path(directory), binding, budget
        self.position, self.entries = 0, []

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory / "workflow.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.lock.close()
            raise WorkflowStop("workflow.concurrent_run") from exc
        try:
            self.path = self.directory / "ledger.json"
            identity = {"binding": self.binding, "budget": asdict(self.budget)}
            if self.path.exists():
                data = json.loads(self.path.read_text())
                if data["identity"] != identity:
                    raise WorkflowStop("workflow.stale_binding")
                self.entries = data["calls"]
            else:
                self.flush()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def flush(self):
        save(
            self.path,
            {
                "identity": {"binding": self.binding, "budget": asdict(self.budget)},
                "calls": self.entries,
            },
        )

    def counts(self):
        return {
            "semantic_calls": len(self.entries),
            "content_calls": sum(e["stage"] != "review" for e in self.entries),
            "review_calls": sum(e["stage"] == "review" for e in self.entries),
            "network_attempts": sum(e.get("network_attempts", 0) for e in self.entries),
            "network_reserved": sum(e.get("network_attempts", 2) for e in self.entries),
            "file_api_calls": sum(e.get("file_api_calls", 0) for e in self.entries),
        }

    def complete(self, stage, request, base_revision, provider):
        prepared = provider.prepare_request(request)
        key = {
            "stage": stage,
            "request_hash": revision(prepared.redacted_payload()),
            "base_revision": base_revision,
        }
        position = self.position
        self.position += 1
        if position < len(self.entries):
            entry = self.entries[position]
            if any(entry[k] != v for k, v in key.items()):
                raise WorkflowStop("workflow.stale_response")
            if entry["status"] == "reserved":
                raise WorkflowStop("workflow.outcome_unknown")
            if entry["status"] == "failed":
                raise WorkflowStop(entry["error_code"])
            response = json.loads((self.directory / entry["response_file"]).read_text())
            if revision(response) != entry["response_hash"]:
                raise WorkflowStop("workflow.response_hash_mismatch")
            return response
        counts = self.counts()
        group = "review" if stage == "review" else "content"
        if (
            counts["semantic_calls"] >= self.budget.semantic
            or counts[group + "_calls"] >= getattr(self.budget, group)
            or counts["network_reserved"] + 2 > self.budget.network
        ):
            raise WorkflowStop("workflow.budget_exhausted")
        directory = self.directory / "calls" / f"{position + 1:02d}-{stage}"
        directory.mkdir(parents=True, exist_ok=True)
        save(directory / "request.json", prepared.redacted_payload())
        entry = {
            **key,
            "status": "reserved",
            "number": position + 1,
            "directory": str(directory.relative_to(self.directory)),
        }
        self.entries.append(entry)
        self.flush()  # Reservation is durable before any provider I/O.
        started = perf_counter()
        try:
            response = provider.complete(
                replace(prepared, transport_audit_directory=str(directory))
            )
            attempts = [
                a.to_payload() if hasattr(a, "to_payload") else a
                for a in response.provider_attempts
            ]
            if not 1 <= len(attempts) <= 2:
                raise WorkflowStop("workflow.provider_network_budget")
            saved = {
                "text": response.text,
                "finish_reason": response.finish_reason,
                "metadata": response.metadata_payload(),
                "raw_payload": dict(response.raw_payload),
                "network_attempts": len(attempts),
                "elapsed_seconds": round(perf_counter() - started, 3),
            }
            save(directory / "response.json", saved)
            entry.update(
                status="completed",
                response_file=str(
                    (directory / "response.json").relative_to(self.directory)
                ),
                response_hash=revision(saved),
                network_attempts=len(attempts),
                elapsed_seconds=saved["elapsed_seconds"],
                usage=saved["metadata"].get("usage"),
                file_api_calls=saved["metadata"].get("file_api_calls", 0),
            )
            self.flush()
            return saved
        except Exception as exc:
            # Failure text/SDK objects may contain authenticated URLs; record codes only.
            attempts = getattr(provider, "last_provider_attempts", ())
            entry.update(
                status="failed",
                error_code="workflow.provider_failed",
                error_type=type(exc).__name__,
                elapsed_seconds=round(perf_counter() - started, 3),
                network_attempts=(
                    min(2, len(attempts))
                    if attempts
                    else 0
                    if getattr(provider, "last_completion_started", None) is False
                    else 2
                ),
                file_api_calls=sum(
                    e["api_calls"]
                    for e in getattr(provider, "last_file_operations", ())
                ),
            )
            self.flush()
            raise WorkflowStop(entry["error_code"]) from exc
