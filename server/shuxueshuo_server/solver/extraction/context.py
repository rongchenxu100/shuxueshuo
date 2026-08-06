"""Immutable ProblemExtractionContext and deterministic state transitions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    FrozenJson,
    ProblemExtractionContextError,
    ProblemSourceFingerprint,
    SourceSelection,
    freeze_json,
    stable_hash,
    thaw_json,
)


CONTEXT_SCHEMA_VERSION = "problem-extraction-context/v1"
CandidateType = Literal["scope", "entity", "fact", "goal"]
CandidateStatus = Literal["proposed", "accepted", "rejected", "ambiguous"]
AttemptResult = Literal[
    "succeeded",
    "timeout",
    "rate_limited",
    "empty_response",
    "invalid_json",
    "failed",
]
ExtractionRoute = Literal[
    "pending",
    "multimodal",
]
_CANDIDATE_TYPES = frozenset({"scope", "entity", "fact", "goal"})
_CANDIDATE_STATUSES = frozenset(
    {"proposed", "accepted", "rejected", "ambiguous"}
)
_ATTEMPT_RESULTS = frozenset(
    {"succeeded", "timeout", "rate_limited", "empty_response", "invalid_json", "failed"}
)
_ROUTES = frozenset(
    {
        "pending",
        "multimodal",
    }
)


@dataclass(frozen=True)
class ExtractionArtifactRef:
    artifact_id: str
    kind: str
    sha256: str
    media_type: str | None = None
    byte_size: int | None = None
    locator: str | None = None

    def validate(self, path: str) -> None:
        if not self.artifact_id or not self.kind:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                path,
                "artifact id and kind are required",
            )
        _validate_sha(self.sha256, f"{path}.sha256")
        if self.byte_size is not None and self.byte_size < 0:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                f"{path}.byte_size",
                "byte size must be non-negative",
            )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "sha256": self.sha256,
            "media_type": self.media_type,
            "byte_size": self.byte_size,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self.authority_payload(), "locator": self.locator}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionArtifactRef:
        return cls(
            artifact_id=str(payload["artifact_id"]),
            kind=str(payload["kind"]),
            sha256=str(payload["sha256"]),
            media_type=(
                str(payload["media_type"])
                if payload.get("media_type") is not None
                else None
            ),
            byte_size=(
                int(payload["byte_size"])
                if payload.get("byte_size") is not None
                else None
            ),
            locator=(
                str(payload["locator"])
                if payload.get("locator") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ExtractionEvidenceRecord:
    evidence_id: str
    artifact_id: str
    page_id: str
    payload: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "artifact_id": self.artifact_id,
            "page_id": self.page_id,
            "payload": thaw_json(self.payload),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionEvidenceRecord:
        return cls(
            evidence_id=str(payload["evidence_id"]),
            artifact_id=str(payload["artifact_id"]),
            page_id=str(payload["page_id"]),
            payload=_mapping(payload.get("payload", {}), "$.state.evidence.payload"),
        )


@dataclass(frozen=True)
class ExtractionCandidateRecord:
    candidate_id: str
    candidate_type: CandidateType
    status: CandidateStatus
    evidence_refs: tuple[str, ...]
    locked: bool
    payload: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "status": self.status,
            "evidence_refs": list(self.evidence_refs),
            "locked": self.locked,
            "payload": thaw_json(self.payload),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionCandidateRecord:
        return cls(
            candidate_id=str(payload["candidate_id"]),
            candidate_type=str(payload["candidate_type"]),  # type: ignore[arg-type]
            status=str(payload["status"]),  # type: ignore[arg-type]
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", ())),
            locked=bool(payload["locked"]),
            payload=_mapping(payload.get("payload", {}), "$.state.candidate.payload"),
        )


@dataclass(frozen=True)
class ExtractionIssue:
    issue_id: str
    code: str
    blocking: bool
    retryable: bool
    candidate_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    authorized_revision_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(self.candidate_ids))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(
            self,
            "authorized_revision_candidate_ids",
            tuple(self.authorized_revision_candidate_ids),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "code": self.code,
            "blocking": self.blocking,
            "retryable": self.retryable,
            "candidate_ids": list(self.candidate_ids),
            "evidence_ids": list(self.evidence_ids),
            "authorized_revision_candidate_ids": list(
                self.authorized_revision_candidate_ids
            ),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionIssue:
        return cls(
            issue_id=str(payload["issue_id"]),
            code=str(payload["code"]),
            blocking=bool(payload["blocking"]),
            retryable=bool(payload["retryable"]),
            candidate_ids=tuple(str(item) for item in payload.get("candidate_ids", ())),
            evidence_ids=tuple(str(item) for item in payload.get("evidence_ids", ())),
            authorized_revision_candidate_ids=tuple(
                str(item)
                for item in payload.get("authorized_revision_candidate_ids", ())
            ),
        )


@dataclass(frozen=True)
class ExtractionDecision:
    decision_id: str
    action: str
    candidate_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    payload: Mapping[str, FrozenJson] = field(
        default_factory=lambda: freeze_json({})  # type: ignore[arg-type,return-value]
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_ids", tuple(self.candidate_ids))
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "action": self.action,
            "candidate_ids": list(self.candidate_ids),
            "evidence_ids": list(self.evidence_ids),
            "payload": thaw_json(self.payload),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionDecision:
        return cls(
            decision_id=str(payload["decision_id"]),
            action=str(payload["action"]),
            candidate_ids=tuple(str(item) for item in payload.get("candidate_ids", ())),
            evidence_ids=tuple(str(item) for item in payload.get("evidence_ids", ())),
            payload=_mapping(payload.get("payload", {}), "$.decisions.payload"),
        )


@dataclass(frozen=True)
class ExtractionEvent:
    sequence: int
    event: str
    payload: Mapping[str, FrozenJson] = field(
        default_factory=lambda: freeze_json({})  # type: ignore[arg-type,return-value]
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "event": self.event,
            "payload": thaw_json(self.payload),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionEvent:
        return cls(
            sequence=int(payload["sequence"]),
            event=str(payload["event"]),
            payload=_mapping(payload.get("payload", {}), "$.events.payload"),
        )


@dataclass(frozen=True)
class ExtractionAttemptRef:
    attempt_id: str
    attempt_hash: str
    authority: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "authority", freeze_json(self.authority))

    def to_payload(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_hash": self.attempt_hash,
            "authority": thaw_json(self.authority),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionAttemptRef:
        return cls(
            attempt_id=str(payload["attempt_id"]),
            attempt_hash=str(payload["attempt_hash"]),
            authority=_mapping(
                payload["authority"],
                "$.attempt_refs.authority",
            ),
        )

    def validate(self, path: str) -> None:
        record = ExtractionAttemptRecord.from_authority_payload(self.authority)
        record.validate(record.base_context_id)
        if record.attempt_id != self.attempt_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                f"{path}.attempt_id",
                "attempt ref identity differs from its authority payload",
            )
        expected_hash = stable_hash(record.authority_payload())
        if self.attempt_hash != expected_hash:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                f"{path}.attempt_hash",
                f"expected {expected_hash}, got {self.attempt_hash}",
            )

    @property
    def base_context_id(self) -> str:
        return str(self.authority["base_context_id"])


@dataclass(frozen=True)
class ExtractionRetryState:
    status: Literal["pending", "ready", "blocked", "complete"] = "pending"
    work_item_ids: tuple[str, ...] = ()
    attempt_budget: int = 0
    attempts_used: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "work_item_ids", tuple(self.work_item_ids))

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "work_item_ids": list(self.work_item_ids),
            "attempt_budget": self.attempt_budget,
            "attempts_used": self.attempts_used,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionRetryState:
        return cls(
            status=str(payload.get("status", "pending")),  # type: ignore[arg-type]
            work_item_ids=tuple(
                str(item) for item in payload.get("work_item_ids", ())
            ),
            attempt_budget=int(payload.get("attempt_budget", 0)),
            attempts_used=int(payload.get("attempts_used", 0)),
        )


@dataclass(frozen=True)
class ExtractionProjection:
    status: Literal["pending"] = "pending"
    problem_ir_ref: None = None

    def to_payload(self) -> dict[str, Any]:
        return {"status": self.status, "problem_ir_ref": self.problem_ir_ref}


@dataclass(frozen=True)
class ExtractionState:
    artifacts: tuple[ExtractionArtifactRef, ...] = ()
    evidence: tuple[ExtractionEvidenceRecord, ...] = ()
    scope_candidates: tuple[ExtractionCandidateRecord, ...] = ()
    entity_candidates: tuple[ExtractionCandidateRecord, ...] = ()
    fact_candidates: tuple[ExtractionCandidateRecord, ...] = ()
    goal_candidates: tuple[ExtractionCandidateRecord, ...] = ()
    issues: tuple[ExtractionIssue, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "artifacts",
            "evidence",
            "scope_candidates",
            "entity_candidates",
            "fact_candidates",
            "goal_candidates",
            "issues",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))

    @property
    def candidates(self) -> tuple[ExtractionCandidateRecord, ...]:
        return (
            self.scope_candidates
            + self.entity_candidates
            + self.fact_candidates
            + self.goal_candidates
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_payload() for item in self.artifacts],
            "evidence": [item.to_payload() for item in self.evidence],
            "scope_candidates": [item.to_payload() for item in self.scope_candidates],
            "entity_candidates": [item.to_payload() for item in self.entity_candidates],
            "fact_candidates": [item.to_payload() for item in self.fact_candidates],
            "goal_candidates": [item.to_payload() for item in self.goal_candidates],
            "issues": [item.to_payload() for item in self.issues],
        }

    def authority_payload(self) -> dict[str, Any]:
        payload = self.to_payload()
        payload["artifacts"] = [
            item.authority_payload() for item in self.artifacts
        ]
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionState:
        return cls(
            artifacts=tuple(
                ExtractionArtifactRef.from_payload(item)
                for item in _mapping_sequence(payload.get("artifacts", ()), "$.state.artifacts")
            ),
            evidence=tuple(
                ExtractionEvidenceRecord.from_payload(item)
                for item in _mapping_sequence(payload.get("evidence", ()), "$.state.evidence")
            ),
            scope_candidates=_candidate_records(payload, "scope"),
            entity_candidates=_candidate_records(payload, "entity"),
            fact_candidates=_candidate_records(payload, "fact"),
            goal_candidates=_candidate_records(payload, "goal"),
            issues=tuple(
                ExtractionIssue.from_payload(item)
                for item in _mapping_sequence(payload.get("issues", ()), "$.state.issues")
            ),
        )


@dataclass(frozen=True)
class ExtractionContextManifest:
    context_id: str
    schema_version: str
    parent_context_id: str | None
    ancestor_context_ids: tuple[str, ...]
    dependency_hash: str
    state_hash: str
    producer: str
    producer_version: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "ancestor_context_ids",
            tuple(self.ancestor_context_ids),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "schema_version": self.schema_version,
            "parent_context_id": self.parent_context_id,
            "ancestor_context_ids": list(self.ancestor_context_ids),
            "dependency_hash": self.dependency_hash,
            "state_hash": self.state_hash,
            "producer": self.producer,
            "producer_version": self.producer_version,
        }


@dataclass(frozen=True)
class ProblemExtractionContext:
    manifest: ExtractionContextManifest
    source: ProblemSourceFingerprint
    selection: SourceSelection
    dependency: ExtractionDependencyManifest
    state: ExtractionState
    decisions: tuple[ExtractionDecision, ...]
    events: tuple[ExtractionEvent, ...]
    attempt_refs: tuple[ExtractionAttemptRef, ...]
    retry: ExtractionRetryState
    projection: ExtractionProjection
    quality: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "decisions", tuple(self.decisions))
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "attempt_refs", tuple(self.attempt_refs))
        object.__setattr__(self, "quality", freeze_json(self.quality))

    def to_payload(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_payload(),
            "source": self.source.to_payload(),
            "selection": self.selection.to_payload(),
            "dependency": self.dependency.to_payload(),
            "state": self.state.to_payload(),
            "decisions": [item.to_payload() for item in self.decisions],
            "events": [item.to_payload() for item in self.events],
            "attempt_refs": [item.to_payload() for item in self.attempt_refs],
            "retry": self.retry.to_payload(),
            "projection": self.projection.to_payload(),
            "quality": thaw_json(self.quality),
        }

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
    ) -> ProblemExtractionContext:
        _validate_context_schema(payload)
        try:
            source = ProblemSourceFingerprint.from_payload(
                _mapping(payload["source"], "$.source")
            )
            selection = SourceSelection.from_payload(
                _mapping(payload["selection"], "$.selection"),
                source,
            )
            dependency = ExtractionDependencyManifest.from_payload(
                _mapping(payload["dependency"], "$.dependency"),
                source,
                selection,
            )
            manifest_payload = _mapping(payload["manifest"], "$.manifest")
            context = cls(
                manifest=ExtractionContextManifest(
                    context_id=str(manifest_payload["context_id"]),
                    schema_version=str(manifest_payload["schema_version"]),
                    parent_context_id=(
                        str(manifest_payload["parent_context_id"])
                        if manifest_payload.get("parent_context_id") is not None
                        else None
                    ),
                    ancestor_context_ids=tuple(
                        str(item)
                        for item in manifest_payload["ancestor_context_ids"]
                    ),
                    dependency_hash=str(manifest_payload["dependency_hash"]),
                    state_hash=str(manifest_payload["state_hash"]),
                    producer=str(manifest_payload["producer"]),
                    producer_version=str(manifest_payload["producer_version"]),
                ),
                source=source,
                selection=selection,
                dependency=dependency,
                state=ExtractionState.from_payload(_mapping(payload["state"], "$.state")),
                decisions=tuple(
                    ExtractionDecision.from_payload(item)
                    for item in _mapping_sequence(payload["decisions"], "$.decisions")
                ),
                events=tuple(
                    ExtractionEvent.from_payload(item)
                    for item in _mapping_sequence(payload["events"], "$.events")
                ),
                attempt_refs=tuple(
                    ExtractionAttemptRef.from_payload(item)
                    for item in _mapping_sequence(payload["attempt_refs"], "$.attempt_refs")
                ),
                retry=ExtractionRetryState.from_payload(
                    _mapping(payload["retry"], "$.retry")
                ),
                projection=ExtractionProjection(
                    status=str(
                        _mapping(payload["projection"], "$.projection")["status"]
                    ),  # type: ignore[arg-type]
                    problem_ir_ref=_mapping(payload["projection"], "$.projection").get(
                        "problem_ir_ref"
                    ),  # type: ignore[arg-type]
                ),
                quality=_mapping(payload["quality"], "$.quality"),
            )
        except ProblemExtractionContextError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("extraction.context_hash_mismatch", "$", str(exc)) from exc
        validate_problem_extraction_context(
            context,
            ancestor_contexts=ancestor_contexts,
        )
        return context


class ProblemExtractionContextBuilder:
    @classmethod
    def initial(
        cls,
        *,
        source: ProblemSourceFingerprint,
        selection: SourceSelection,
        dependency: ExtractionDependencyManifest,
        state: ExtractionState | None = None,
        producer: str = "source_ingestion",
        producer_version: str = "v1",
        retry: ExtractionRetryState | None = None,
        quality: Mapping[str, Any] | None = None,
    ) -> ProblemExtractionContext:
        return _assemble_context(
            source=source,
            selection=selection,
            dependency=dependency,
            state=state or ExtractionState(),
            parent_context=None,
            ancestor_contexts=(),
            producer=producer,
            producer_version=producer_version,
            decisions=(),
            events=(ExtractionEvent(0, "context_initialized"),),
            attempt_refs=(),
            retry=retry or ExtractionRetryState(),
            quality=quality or {},
        )

    @classmethod
    def trusted_child(
        cls,
        context: ProblemExtractionContext,
        *,
        state: ExtractionState,
        attempt_ledger: ExtractionAttemptLedger,
        event: str,
        event_payload: Mapping[str, Any] | None = None,
        quality: Mapping[str, Any] | None = None,
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
        producer: str,
        producer_version: str,
    ) -> ProblemExtractionContext:
        """Create a child at a trusted non-semantic authority boundary."""

        validate_problem_extraction_context(
            context,
            ancestor_contexts=ancestor_contexts,
        )
        if attempt_ledger.base_context_id != context.manifest.context_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.base_context_id",
                "ledger does not belong to trusted child base",
            )
        attempt_refs = _merged_attempt_refs(context, attempt_ledger)
        return _assemble_context(
            source=context.source,
            selection=context.selection,
            dependency=context.dependency,
            state=state,
            parent_context=context,
            ancestor_contexts=ancestor_contexts,
            producer=producer,
            producer_version=producer_version,
            decisions=context.decisions,
            events=context.events
            + (
                ExtractionEvent(
                    sequence=len(context.events),
                    event=event,
                    payload=event_payload or {},
                ),
            ),
            attempt_refs=attempt_refs,
            retry=replace(context.retry, attempts_used=len(attempt_refs)),
            quality=quality if quality is not None else context.quality,
        )


@dataclass(frozen=True)
class ExtractionAttemptRecord:
    attempt_id: str
    base_context_id: str
    provider: str
    route: ExtractionRoute
    input_artifact_refs: tuple[ExtractionArtifactRef, ...]
    output_artifact_refs: tuple[ExtractionArtifactRef, ...]
    result: AttemptResult
    usage: Mapping[str, FrozenJson]
    latency_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "input_artifact_refs",
            tuple(self.input_artifact_refs),
        )
        object.__setattr__(
            self,
            "output_artifact_refs",
            tuple(self.output_artifact_refs),
        )
        object.__setattr__(self, "usage", freeze_json(self.usage))

    @property
    def attempt_hash(self) -> str:
        return stable_hash(self.authority_payload())

    def authority_payload(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "base_context_id": self.base_context_id,
            "provider": self.provider,
            "route": self.route,
            "input_artifact_refs": [
                item.authority_payload() for item in self.input_artifact_refs
            ],
            "output_artifact_refs": [
                item.authority_payload() for item in self.output_artifact_refs
            ],
            "result": self.result,
            "usage": thaw_json(self.usage),
            "latency_ms": self.latency_ms,
        }

    def to_ref(self) -> ExtractionAttemptRef:
        return ExtractionAttemptRef(
            self.attempt_id,
            self.attempt_hash,
            self.authority_payload(),
        )

    @classmethod
    def from_authority_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> ExtractionAttemptRecord:
        try:
            return cls(
                attempt_id=str(payload["attempt_id"]),
                base_context_id=str(payload["base_context_id"]),
                provider=str(payload["provider"]),
                route=str(payload["route"]),  # type: ignore[arg-type]
                input_artifact_refs=tuple(
                    ExtractionArtifactRef.from_payload(item)
                    for item in _mapping_sequence(
                        payload["input_artifact_refs"],
                        "$.attempt_refs.authority.input_artifact_refs",
                    )
                ),
                output_artifact_refs=tuple(
                    ExtractionArtifactRef.from_payload(item)
                    for item in _mapping_sequence(
                        payload["output_artifact_refs"],
                        "$.attempt_refs.authority.output_artifact_refs",
                    )
                ),
                result=str(payload["result"]),  # type: ignore[arg-type]
                usage=_mapping(
                    payload["usage"],
                    "$.attempt_refs.authority.usage",
                ),
                latency_ms=int(payload["latency_ms"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_refs.authority",
                str(exc),
            ) from exc

    def validate(self, base_context_id: str) -> None:
        if self.base_context_id != base_context_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt.base_context_id",
                f"expected {base_context_id}, got {self.base_context_id}",
            )
        if not self.attempt_id or not self.provider:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt",
                "attempt id and provider are required",
            )
        if self.route not in _ROUTES or self.result not in _ATTEMPT_RESULTS:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt",
                "invalid route or result",
            )
        if self.latency_ms < 0:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt.latency_ms",
                "latency must be non-negative",
            )
        refs = self.input_artifact_refs + self.output_artifact_refs
        _validate_unique(
            (item.artifact_id for item in refs),
            "extraction.attempt_ledger_mismatch",
            "$.attempt.artifact_refs",
        )
        for index, artifact in enumerate(refs):
            artifact.validate(f"$.attempt.artifact_refs[{index}]")


@dataclass(frozen=True)
class ExtractionAttemptLedger:
    base_context_id: str
    attempts: tuple[ExtractionAttemptRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))

    @classmethod
    def for_context(
        cls,
        context: ProblemExtractionContext,
    ) -> ExtractionAttemptLedger:
        return cls(base_context_id=context.manifest.context_id)

    def append(
        self,
        context: ProblemExtractionContext,
        attempt: ExtractionAttemptRecord,
    ) -> ExtractionAttemptLedger:
        if self.base_context_id != context.manifest.context_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.base_context_id",
                "ledger does not belong to the supplied Context",
            )
        _validate_unique(
            (item.attempt_id for item in self.attempts),
            "extraction.attempt_ledger_mismatch",
            "$.attempt_ledger.attempts",
        )
        for existing_attempt in self.attempts:
            existing_attempt.validate(self.base_context_id)
        attempt.validate(self.base_context_id)
        existing = {item.attempt_id: item for item in self.attempts}
        prior = existing.get(attempt.attempt_id)
        if prior is not None:
            if prior.attempt_hash == attempt.attempt_hash:
                return self
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt.attempt_id",
                "attempt id was reused with different content",
            )
        _validate_attempt_budget(
            context.retry,
            context.retry.attempts_used + len(self.attempts) + 1,
            "$.attempt_ledger.attempts",
        )
        return replace(self, attempts=self.attempts + (attempt,))


@dataclass(frozen=True)
class ExtractionCandidateChange:
    action: Literal["upsert", "remove"]
    candidate_id: str
    candidate: ExtractionCandidateRecord | None = None


@dataclass(frozen=True)
class ExtractionStatePatch:
    patch_id: str
    base_context_id: str
    candidate_changes: tuple[ExtractionCandidateChange, ...] = ()
    issue_resolutions: tuple[str, ...] = ()
    decisions: tuple[ExtractionDecision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_changes",
            tuple(self.candidate_changes),
        )
        object.__setattr__(self, "issue_resolutions", tuple(self.issue_resolutions))
        object.__setattr__(self, "decisions", tuple(self.decisions))


class ProblemExtractionContextTransitionService:
    def apply_patch(
        self,
        context: ProblemExtractionContext,
        patch: ExtractionStatePatch,
        *,
        attempt_ledger: ExtractionAttemptLedger,
        ancestor_contexts: Sequence[ProblemExtractionContext] = (),
        producer: str = "semantic_patch",
        producer_version: str = "v1",
    ) -> ProblemExtractionContext:
        validate_problem_extraction_context(
            context,
            ancestor_contexts=ancestor_contexts,
        )
        if patch.base_context_id != context.manifest.context_id:
            raise _error(
                "extraction.patch_base_mismatch",
                "$.patch.base_context_id",
                f"expected {context.manifest.context_id}, got {patch.base_context_id}",
            )
        if attempt_ledger.base_context_id != context.manifest.context_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.base_context_id",
                "ledger does not belong to patch base",
            )
        if not patch.patch_id:
            raise _error(
                "extraction.patch_base_mismatch",
                "$.patch.patch_id",
                "patch id is required",
            )

        issues_by_id = {item.issue_id: item for item in context.state.issues}
        unknown_resolutions = set(patch.issue_resolutions) - set(issues_by_id)
        if unknown_resolutions:
            raise _error(
                "extraction.patch_base_mismatch",
                "$.patch.issue_resolutions",
                f"unknown issues: {sorted(unknown_resolutions)}",
            )
        authorized = {
            candidate_id
            for issue_id in patch.issue_resolutions
            for candidate_id in issues_by_id[
                issue_id
            ].authorized_revision_candidate_ids
            if issues_by_id[issue_id].blocking
        }
        effective_change_ids: set[str] = set()
        candidates = {item.candidate_id: item for item in context.state.candidates}
        for change in patch.candidate_changes:
            existing = candidates.get(change.candidate_id)
            if existing is not None and existing.status == "accepted" and existing.locked:
                if change.candidate_id not in authorized:
                    raise _error(
                        "extraction.locked_candidate_mutation",
                        f"$.patch.candidate_changes.{change.candidate_id}",
                        "locked accepted candidate lacks explicit issue authorization",
                    )
            if change.action == "remove":
                if change.candidate is not None:
                    raise _error(
                        "extraction.patch_base_mismatch",
                        "$.patch.candidate_changes",
                        "remove change cannot carry a candidate",
                    )
                if existing is not None:
                    effective_change_ids.add(change.candidate_id)
                candidates.pop(change.candidate_id, None)
            elif change.action == "upsert":
                if (
                    change.candidate is None
                    or change.candidate.candidate_id != change.candidate_id
                ):
                    raise _error(
                        "extraction.patch_base_mismatch",
                        "$.patch.candidate_changes",
                        "upsert candidate identity mismatch",
                    )
                if change.candidate.locked and (
                    existing is None or not existing.locked
                ):
                    raise _error(
                        "extraction.locked_candidate_mutation",
                        f"$.patch.candidate_changes.{change.candidate_id}",
                        "ordinary semantic patches cannot establish a new lock",
                    )
                if (
                    existing is not None
                    and existing.candidate_type != change.candidate.candidate_type
                ):
                    raise _error(
                        "extraction.patch_base_mismatch",
                        "$.patch.candidate_changes",
                        "candidate type cannot change",
                    )
                if existing != change.candidate:
                    effective_change_ids.add(change.candidate_id)
                candidates[change.candidate_id] = change.candidate
            else:
                raise _error(
                    "extraction.patch_base_mismatch",
                    "$.patch.candidate_changes",
                    f"unknown action {change.action!r}",
                )

        dismissed_issue_ids = _false_positive_dismissal_ids(
            patch,
            issues_by_id,
        )
        for issue_id in patch.issue_resolutions:
            issue = issues_by_id[issue_id]
            authorized_ids = set(issue.authorized_revision_candidate_ids)
            if (
                authorized_ids
                and not authorized_ids.intersection(effective_change_ids)
                and issue_id not in dismissed_issue_ids
            ):
                raise _error(
                    "extraction.patch_base_mismatch",
                    f"$.patch.issue_resolutions.{issue_id}",
                    (
                        "authorized issue resolution requires an effective candidate "
                        "revision or dismiss_issue_false_positive decision"
                    ),
                )

        next_state = _state_with_candidates(
            context.state,
            tuple(candidates.values()),
            issues=tuple(
                item
                for item in context.state.issues
                if item.issue_id not in patch.issue_resolutions
            ),
        )
        next_decisions = context.decisions + patch.decisions
        next_events = context.events + (
            ExtractionEvent(
                sequence=len(context.events),
                event="semantic_patch_applied",
                payload={"patch_id": patch.patch_id},
            ),
        )
        attempt_refs = _merged_attempt_refs(context, attempt_ledger)
        return _assemble_context(
            source=context.source,
            selection=context.selection,
            dependency=context.dependency,
            state=next_state,
            parent_context=context,
            ancestor_contexts=ancestor_contexts,
            producer=producer,
            producer_version=producer_version,
            decisions=next_decisions,
            events=next_events,
            attempt_refs=attempt_refs,
            retry=replace(
                context.retry,
                attempts_used=len(attempt_refs),
            ),
            quality=context.quality,
        )


def _validate_history_prefix(
    current: Sequence[Any],
    parent: Sequence[Any],
    path: str,
    *,
    code: str = "extraction.context_lineage_unresolved",
) -> None:
    if len(current) < len(parent) or tuple(current[: len(parent)]) != tuple(parent):
        raise _error(
            code,
            path,
            "child audit history must preserve the complete parent prefix",
        )


def _validate_context_self_authority(
    context: ProblemExtractionContext,
) -> None:
    """Validate hash-backed Context facts without resolving its parent object."""

    if context.manifest.schema_version != CONTEXT_SCHEMA_VERSION:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.manifest.schema_version",
            f"unsupported schema {context.manifest.schema_version!r}",
        )
    context.source.validate()
    context.selection.validate(context.source)
    context.dependency.validate(context.source, context.selection)
    if context.manifest.dependency_hash != context.dependency.dependency_hash:
        raise _error(
            "extraction.dependency_hash_mismatch",
            "$.manifest.dependency_hash",
            "manifest and dependency hashes differ",
        )
    if context.manifest.parent_context_id == context.manifest.context_id:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.manifest.parent_context_id",
            "Context cannot be its own parent",
        )
    ancestors = context.manifest.ancestor_context_ids
    _validate_unique(
        ancestors,
        "extraction.context_hash_mismatch",
        "$.manifest.ancestor_context_ids",
    )
    if context.manifest.parent_context_id is None:
        if ancestors:
            raise _error(
                "extraction.context_hash_mismatch",
                "$.manifest.ancestor_context_ids",
                "initial Context cannot declare ancestors",
            )
    elif not ancestors or ancestors[-1] != context.manifest.parent_context_id:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.manifest.ancestor_context_ids",
            "ancestor lineage must end at parent_context_id",
        )
    if context.manifest.context_id in ancestors:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.manifest.ancestor_context_ids",
            "Context cannot be its own ancestor",
        )
    _validate_state(context.state, context.source)
    expected_state_hash = stable_hash(context.state.authority_payload())
    if context.manifest.state_hash != expected_state_hash:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.manifest.state_hash",
            f"expected {expected_state_hash}, got {context.manifest.state_hash}",
        )
    _validate_unique(
        (item.decision_id for item in context.decisions),
        "extraction.context_hash_mismatch",
        "$.decisions",
    )
    if tuple(item.sequence for item in context.events) != tuple(
        range(len(context.events))
    ):
        raise _error(
            "extraction.context_hash_mismatch",
            "$.events",
            "event sequence must be contiguous and zero-based",
        )
    _validate_unique(
        (item.attempt_id for item in context.attempt_refs),
        "extraction.attempt_ledger_mismatch",
        "$.attempt_refs",
    )
    ancestor_positions = {
        context_id: index for index, context_id in enumerate(ancestors)
    }
    prior_base_position = -1
    for index, item in enumerate(context.attempt_refs):
        item.validate(f"$.attempt_refs[{index}]")
        base_position = ancestor_positions.get(item.base_context_id)
        if base_position is None or base_position < prior_base_position:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                f"$.attempt_refs[{index}].authority.base_context_id",
                "attempt base is absent from or out of order in Context lineage",
            )
        prior_base_position = base_position
    if context.retry.attempt_budget < 0 or context.retry.attempts_used < 0:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.retry",
            "retry counters must be non-negative",
        )
    if context.retry.attempts_used != len(context.attempt_refs):
        raise _error(
            "extraction.attempt_ledger_mismatch",
            "$.retry.attempts_used",
            "attempt count does not match persisted refs",
        )
    _validate_attempt_budget(
        context.retry,
        context.retry.attempts_used,
        "$.retry.attempts_used",
    )
    if (
        context.projection.status != "pending"
        or context.projection.problem_ir_ref is not None
    ):
        raise _error(
            "extraction.context_hash_mismatch",
            "$.projection",
            "F1 only permits a pending ProblemIR projection",
        )
    expected_context_id = _context_id(
        manifest=context.manifest,
        selection=context.selection,
        decisions=context.decisions,
        events=context.events,
        attempt_refs=context.attempt_refs,
        retry=context.retry,
        projection=context.projection,
        quality=context.quality,
    )
    if context.manifest.context_id != expected_context_id:
        raise _error(
            "extraction.context_hash_mismatch",
            "$.manifest.context_id",
            f"expected {expected_context_id}, got {context.manifest.context_id}",
        )


def _validate_context_parent_link(
    context: ProblemExtractionContext,
    parent_context: ProblemExtractionContext | None,
) -> None:
    if context.manifest.parent_context_id is None:
        if parent_context is not None:
            raise _error(
                "extraction.context_lineage_unresolved",
                "$.manifest.parent_context_id",
                "initial Context cannot be hydrated with a parent Context",
            )
        return
    if parent_context is None:
        raise _error(
            "extraction.context_lineage_unresolved",
            "$.manifest.parent_context_id",
            "child Context hydration requires its immediate parent Context",
        )
    if context.manifest.parent_context_id != parent_context.manifest.context_id:
        raise _error(
            "extraction.context_lineage_unresolved",
            "$.manifest.parent_context_id",
            "supplied parent Context does not match parent_context_id",
        )
    expected_ancestors = (
        parent_context.manifest.ancestor_context_ids
        + (parent_context.manifest.context_id,)
    )
    if context.manifest.ancestor_context_ids != expected_ancestors:
        raise _error(
            "extraction.context_lineage_unresolved",
            "$.manifest.ancestor_context_ids",
            "ancestor lineage is not the exact parent lineage extension",
        )


def _validate_problem_extraction_context_pair(
    context: ProblemExtractionContext,
    *,
    parent_context: ProblemExtractionContext | None = None,
) -> None:
    _validate_context_parent_link(context, parent_context)
    _validate_context_self_authority(context)
    if parent_context is not None:
        if (
            context.source != parent_context.source
            or context.selection != parent_context.selection
            or context.dependency != parent_context.dependency
        ):
            raise _error(
                "extraction.context_lineage_unresolved",
                "$.manifest.parent_context_id",
                "child Context changed immutable source dependencies",
            )
    historical_decision_count = 0
    historical_attempt_count = 0
    candidate_ids = {item.candidate_id for item in context.state.candidates}
    evidence_ids = {item.evidence_id for item in context.state.evidence}
    if parent_context is not None:
        _validate_history_prefix(
            context.decisions,
            parent_context.decisions,
            "$.decisions",
        )
        _validate_history_prefix(
            context.events,
            parent_context.events,
            "$.events",
        )
        _validate_history_prefix(
            context.attempt_refs,
            parent_context.attempt_refs,
            "$.attempt_refs",
            code="extraction.attempt_ledger_mismatch",
        )
        historical_decision_count = len(parent_context.decisions)
        historical_attempt_count = len(parent_context.attempt_refs)
        candidate_ids.update(
            item.candidate_id for item in parent_context.state.candidates
        )
        evidence_ids.update(
            item.evidence_id for item in parent_context.state.evidence
        )
    for decision in context.decisions[historical_decision_count:]:
        if set(decision.candidate_ids) - candidate_ids:
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.decisions.{decision.decision_id}.candidate_ids",
                "decision references unknown candidates",
            )
        if set(decision.evidence_ids) - evidence_ids:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.decisions.{decision.decision_id}.evidence_ids",
                "decision references unknown evidence",
            )
    for index, item in enumerate(
        context.attempt_refs[historical_attempt_count:],
        start=historical_attempt_count,
    ):
        if (
            parent_context is None
            or item.base_context_id != parent_context.manifest.context_id
        ):
            raise _error(
                "extraction.attempt_ledger_mismatch",
                f"$.attempt_refs[{index}].authority.base_context_id",
                "new attempt ref must belong to the immediate parent Context",
            )
    if parent_context is None and context.attempt_refs:
        raise _error(
            "extraction.attempt_ledger_mismatch",
            "$.attempt_refs",
            "initial Context cannot persist attempt refs",
        )


def validate_problem_extraction_context(
    context: ProblemExtractionContext,
    *,
    ancestor_contexts: Sequence[ProblemExtractionContext] = (),
) -> None:
    lineage = tuple(ancestor_contexts)
    actual_ancestor_ids = tuple(
        item.manifest.context_id for item in lineage
    )
    if actual_ancestor_ids != context.manifest.ancestor_context_ids:
        raise _error(
            "extraction.context_lineage_unresolved",
            "$.manifest.ancestor_context_ids",
            "Context validation requires the complete root-to-parent lineage",
        )
    parent_context: ProblemExtractionContext | None = None
    for item in lineage + (context,):
        _validate_problem_extraction_context_pair(
            item,
            parent_context=parent_context,
        )
        parent_context = item


def _assemble_context(
    *,
    source: ProblemSourceFingerprint,
    selection: SourceSelection,
    dependency: ExtractionDependencyManifest,
    state: ExtractionState,
    parent_context: ProblemExtractionContext | None,
    ancestor_contexts: Sequence[ProblemExtractionContext],
    producer: str,
    producer_version: str,
    decisions: tuple[ExtractionDecision, ...],
    events: tuple[ExtractionEvent, ...],
    attempt_refs: tuple[ExtractionAttemptRef, ...],
    retry: ExtractionRetryState,
    quality: Mapping[str, Any],
) -> ProblemExtractionContext:
    parent_context_id = (
        parent_context.manifest.context_id
        if parent_context is not None
        else None
    )
    ancestor_context_ids = (
        parent_context.manifest.ancestor_context_ids
        + (parent_context.manifest.context_id,)
        if parent_context is not None
        else ()
    )
    state_hash = stable_hash(state.authority_payload())
    provisional_manifest = ExtractionContextManifest(
        context_id="",
        schema_version=CONTEXT_SCHEMA_VERSION,
        parent_context_id=parent_context_id,
        ancestor_context_ids=ancestor_context_ids,
        dependency_hash=dependency.dependency_hash,
        state_hash=state_hash,
        producer=producer,
        producer_version=producer_version,
    )
    projection = ExtractionProjection()
    frozen_quality = freeze_json(quality)
    if not isinstance(frozen_quality, Mapping):
        raise _error(
            "extraction.context_hash_mismatch",
            "$.quality",
            "quality must be an object",
        )
    manifest = replace(
        provisional_manifest,
        context_id=_context_id(
            manifest=provisional_manifest,
            selection=selection,
            decisions=decisions,
            events=events,
            attempt_refs=attempt_refs,
            retry=retry,
            projection=projection,
            quality=frozen_quality,
        ),
    )
    context = ProblemExtractionContext(
        manifest=manifest,
        source=source,
        selection=selection,
        dependency=dependency,
        state=state,
        decisions=decisions,
        events=events,
        attempt_refs=attempt_refs,
        retry=retry,
        projection=projection,
        quality=frozen_quality,
    )
    validate_problem_extraction_context(
        context,
        ancestor_contexts=(
            tuple(ancestor_contexts) + (parent_context,)
            if parent_context is not None
            else ()
        ),
    )
    return context


def _context_id(
    *,
    manifest: ExtractionContextManifest,
    selection: SourceSelection,
    decisions: Sequence[ExtractionDecision],
    events: Sequence[ExtractionEvent],
    attempt_refs: Sequence[ExtractionAttemptRef],
    retry: ExtractionRetryState,
    projection: ExtractionProjection,
    quality: Mapping[str, Any],
) -> str:
    digest = stable_hash(
        {
            "schema_version": manifest.schema_version,
            "parent_context_id": manifest.parent_context_id,
            "ancestor_context_ids": list(manifest.ancestor_context_ids),
            "dependency_hash": manifest.dependency_hash,
            "state_hash": manifest.state_hash,
            "selection_audit_hash": stable_hash(selection.to_payload()),
            "producer": manifest.producer,
            "producer_version": manifest.producer_version,
            "decisions": [item.to_payload() for item in decisions],
            "events": [item.to_payload() for item in events],
            "attempt_refs": [item.to_payload() for item in attempt_refs],
            "retry": retry.to_payload(),
            "projection": projection.to_payload(),
            "quality": thaw_json(quality),
        }
    )
    return f"extraction-context:{digest}"


def _validate_state(state: ExtractionState, source: ProblemSourceFingerprint) -> None:
    page_ids = {page.page_id for page in source.pages}
    artifact_ids = tuple(item.artifact_id for item in state.artifacts)
    _validate_unique(
        artifact_ids,
        "extraction.context_hash_mismatch",
        "$.state.artifacts",
    )
    for index, artifact in enumerate(state.artifacts):
        artifact.validate(f"$.state.artifacts[{index}]")
    evidence_ids = tuple(item.evidence_id for item in state.evidence)
    _validate_unique(
        evidence_ids,
        "extraction.context_hash_mismatch",
        "$.state.evidence",
    )
    artifact_id_set = set(artifact_ids)
    for evidence in state.evidence:
        if evidence.artifact_id not in artifact_id_set:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.evidence.{evidence.evidence_id}.artifact_id",
                evidence.artifact_id,
            )
        if evidence.page_id not in page_ids:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.evidence.{evidence.evidence_id}.page_id",
                evidence.page_id,
            )
    candidates = state.candidates
    _validate_unique(
        (item.candidate_id for item in candidates),
        "extraction.candidate_duplicate",
        "$.state.candidates",
    )
    evidence_id_set = set(evidence_ids)
    for candidate in candidates:
        if candidate.candidate_type not in _CANDIDATE_TYPES:
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.state.candidates.{candidate.candidate_id}.candidate_type",
                str(candidate.candidate_type),
            )
        if candidate.status not in _CANDIDATE_STATUSES:
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.state.candidates.{candidate.candidate_id}.status",
                str(candidate.status),
            )
        if candidate.status == "accepted" and not candidate.locked:
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.state.candidates.{candidate.candidate_id}.locked",
                "accepted candidates must be locked",
            )
        if not candidate.evidence_refs or len(set(candidate.evidence_refs)) != len(
            candidate.evidence_refs
        ):
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.candidates.{candidate.candidate_id}.evidence_refs",
                "candidate evidence refs must be non-empty and unique",
            )
        unresolved = set(candidate.evidence_refs) - evidence_id_set
        if unresolved:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.candidates.{candidate.candidate_id}.evidence_refs",
                str(sorted(unresolved)),
            )
    expected_collections = {
        "scope": state.scope_candidates,
        "entity": state.entity_candidates,
        "fact": state.fact_candidates,
        "goal": state.goal_candidates,
    }
    for expected_type, items in expected_collections.items():
        if any(item.candidate_type != expected_type for item in items):
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.state.{expected_type}_candidates",
                "candidate stored in the wrong collection",
            )
    candidate_ids = {item.candidate_id for item in candidates}
    _validate_unique(
        (item.issue_id for item in state.issues),
        "extraction.context_hash_mismatch",
        "$.state.issues",
    )
    for issue in state.issues:
        if set(issue.candidate_ids) - candidate_ids:
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.state.issues.{issue.issue_id}.candidate_ids",
                "issue references unknown candidates",
            )
        if set(issue.evidence_ids) - evidence_id_set:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.issues.{issue.issue_id}.evidence_ids",
                "issue references unknown evidence",
            )
        if set(issue.authorized_revision_candidate_ids) - set(issue.candidate_ids):
            raise _error(
                "extraction.context_hash_mismatch",
                f"$.state.issues.{issue.issue_id}.authorized_revision_candidate_ids",
                "revision authorization must be a subset of issue candidates",
            )


def _state_with_candidates(
    state: ExtractionState,
    candidates: Sequence[ExtractionCandidateRecord],
    *,
    issues: tuple[ExtractionIssue, ...],
) -> ExtractionState:
    ordered = sorted(candidates, key=lambda item: item.candidate_id)
    return replace(
        state,
        scope_candidates=tuple(item for item in ordered if item.candidate_type == "scope"),
        entity_candidates=tuple(item for item in ordered if item.candidate_type == "entity"),
        fact_candidates=tuple(item for item in ordered if item.candidate_type == "fact"),
        goal_candidates=tuple(item for item in ordered if item.candidate_type == "goal"),
        issues=issues,
    )


def _merged_attempt_refs(
    context: ProblemExtractionContext,
    attempt_ledger: ExtractionAttemptLedger,
) -> tuple[ExtractionAttemptRef, ...]:
    _validate_unique(
        (item.attempt_id for item in attempt_ledger.attempts),
        "extraction.attempt_ledger_mismatch",
        "$.attempt_ledger.attempts",
    )
    for attempt in attempt_ledger.attempts:
        attempt.validate(context.manifest.context_id)
    new_refs = tuple(item.to_ref() for item in attempt_ledger.attempts)
    combined = context.attempt_refs + new_refs
    _validate_unique(
        (item.attempt_id for item in combined),
        "extraction.attempt_ledger_mismatch",
        "$.attempt_refs",
    )
    _validate_attempt_budget(
        context.retry,
        len(combined),
        "$.attempt_ledger.attempts",
    )
    return combined


def _false_positive_dismissal_ids(
    patch: ExtractionStatePatch,
    issues_by_id: Mapping[str, ExtractionIssue],
) -> frozenset[str]:
    dismissed: set[str] = set()
    resolution_ids = set(patch.issue_resolutions)
    for decision in patch.decisions:
        if decision.action != "dismiss_issue_false_positive":
            continue
        issue_id = decision.payload.get("issue_id")
        if not isinstance(issue_id, str) or issue_id not in issues_by_id:
            raise _error(
                "extraction.patch_base_mismatch",
                f"$.patch.decisions.{decision.decision_id}.payload.issue_id",
                "false-positive dismissal must reference an existing issue",
            )
        if issue_id not in resolution_ids or issue_id in dismissed:
            raise _error(
                "extraction.patch_base_mismatch",
                f"$.patch.decisions.{decision.decision_id}",
                "false-positive dismissal must uniquely resolve its issue",
            )
        issue = issues_by_id[issue_id]
        if set(issue.authorized_revision_candidate_ids) - set(
            decision.candidate_ids
        ):
            raise _error(
                "extraction.patch_base_mismatch",
                f"$.patch.decisions.{decision.decision_id}.candidate_ids",
                "dismissal must identify every candidate authorized for revision",
            )
        if set(issue.evidence_ids) - set(decision.evidence_ids):
            raise _error(
                "extraction.patch_base_mismatch",
                f"$.patch.decisions.{decision.decision_id}.evidence_ids",
                "dismissal must preserve the issue evidence references",
            )
        dismissed.add(issue_id)
    return frozenset(dismissed)


def _validate_attempt_budget(
    retry: ExtractionRetryState,
    attempts_used: int,
    path: str,
) -> None:
    if attempts_used > retry.attempt_budget:
        raise _error(
            "extraction.attempt_ledger_mismatch",
            path,
            (
                f"attempt budget exceeded: {attempts_used} used, "
                f"budget is {retry.attempt_budget}"
            ),
        )


def _candidate_records(
    payload: Mapping[str, Any],
    candidate_type: str,
) -> tuple[ExtractionCandidateRecord, ...]:
    key = f"{candidate_type}_candidates"
    return tuple(
        ExtractionCandidateRecord.from_payload(item)
        for item in _mapping_sequence(payload.get(key, ()), f"$.state.{key}")
    )


def _validate_context_schema(payload: Mapping[str, Any]) -> None:
    errors = sorted(
        _context_schema_validator().iter_errors(payload),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    location = "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}"
        for item in error.absolute_path
    )
    raise _error(
        "extraction.context_hash_mismatch",
        location,
        error.message,
    )


@lru_cache(maxsize=1)
def _context_schema_validator() -> Draft202012Validator:
    schema_path = (
        Path(__file__).resolve().parents[4]
        / "internal"
        / "schemas"
        / "problem-extraction-context.schema.json"
    )
    import json

    payload = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(payload)
    return Draft202012Validator(payload)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("extraction.context_hash_mismatch", path, "expected an object")
    return value


def _mapping_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _error("extraction.context_hash_mismatch", path, "expected an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise _error(
            "extraction.context_hash_mismatch",
            path,
            "array items must be objects",
        )
    return tuple(value)  # type: ignore[return-value]


def _validate_unique(
    values: Sequence[str] | Any,
    code: str,
    path: str,
) -> None:
    materialized = tuple(values)
    if any(not item for item in materialized):
        raise _error(code, path, "identities must be non-empty")
    if len(materialized) != len(set(materialized)):
        raise _error(code, path, "duplicate identity")


def _validate_sha(value: str, path: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise _error("extraction.attempt_ledger_mismatch", path, "invalid SHA-256")


def _error(code: str, path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(code, path, message)
