"""Immutable authority envelope for image-to-ProblemIR extraction."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
import re
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


CONTEXT_SCHEMA_VERSION = "problem-extraction-context/v3"
SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND = "solver_problem_projection"
AttemptResult = Literal[
    "succeeded",
    "timeout",
    "rate_limited",
    "empty_response",
    "invalid_json",
    "failed",
]
ExtractionRoute = Literal["pending", "multimodal", "text_baseline"]
ProjectionStatus = Literal["pending", "accepted", "blocked"]
_ATTEMPT_RESULTS = frozenset(
    {"succeeded", "timeout", "rate_limited", "empty_response", "invalid_json", "failed"}
)
_ROUTES = frozenset({"pending", "multimodal", "text_baseline"})
_PROJECTION_STATUSES = frozenset({"pending", "accepted", "blocked"})


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
        expected_artifact_id = f"artifact:{self.kind}:{self.sha256}"
        if self.artifact_id != expected_artifact_id:
            raise _error(
                "extraction.context_hash_mismatch",
                f"{path}.artifact_id",
                "artifact id does not match kind and content hash",
            )
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
class ExtractionIssue:
    issue_id: str
    code: str
    blocking: bool
    retryable: bool
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "code": self.code,
            "blocking": self.blocking,
            "retryable": self.retryable,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionIssue:
        return cls(
            issue_id=str(payload["issue_id"]),
            code=str(payload["code"]),
            blocking=bool(payload["blocking"]),
            retryable=bool(payload["retryable"]),
            evidence_ids=tuple(str(item) for item in payload.get("evidence_ids", ())),
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
            work_item_ids=tuple(str(item) for item in payload.get("work_item_ids", ())),
            attempt_budget=int(payload.get("attempt_budget", 0)),
            attempts_used=int(payload.get("attempts_used", 0)),
        )


@dataclass(frozen=True)
class ExtractionProjection:
    status: ProjectionStatus = "pending"
    problem_draft_artifact_id: str | None = None
    verified_problem_artifact_id: str | None = None
    solver_problem_ir_artifact_id: str | None = None
    problem_revision_id: str | None = None
    problem_semantic_hash: str | None = None
    family_id: str | None = None
    validation_artifact_id: str | None = None

    @property
    def solver_problem_projection_artifact_id(self) -> str | None:
        """Semantic alias for the legacy Context v3 wire field.

        ``solver_problem_ir_artifact_id`` stores a
        ``solver-problem-projection/v1`` envelope, not a bare ProblemIR payload.
        New consumers must use this alias and the bundle loader.
        """

        return self.solver_problem_ir_artifact_id

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "problem_draft_artifact_id": self.problem_draft_artifact_id,
            "verified_problem_artifact_id": self.verified_problem_artifact_id,
            "solver_problem_ir_artifact_id": self.solver_problem_ir_artifact_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "family_id": self.family_id,
            "validation_artifact_id": self.validation_artifact_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> ExtractionProjection:
        return cls(
            status=str(payload["status"]),  # type: ignore[arg-type]
            problem_draft_artifact_id=_optional_string(payload.get("problem_draft_artifact_id")),
            verified_problem_artifact_id=_optional_string(payload.get("verified_problem_artifact_id")),
            solver_problem_ir_artifact_id=_optional_string(payload.get("solver_problem_ir_artifact_id")),
            problem_revision_id=_optional_string(payload.get("problem_revision_id")),
            problem_semantic_hash=_optional_string(payload.get("problem_semantic_hash")),
            family_id=_optional_string(payload.get("family_id")),
            validation_artifact_id=_optional_string(payload.get("validation_artifact_id")),
        )


@dataclass(frozen=True)
class ExtractionState:
    artifacts: tuple[ExtractionArtifactRef, ...] = ()
    evidence: tuple[ExtractionEvidenceRecord, ...] = ()
    issues: tuple[ExtractionIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "issues", tuple(self.issues))

    def to_payload(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_payload() for item in self.artifacts],
            "evidence": [item.to_payload() for item in self.evidence],
            "issues": [item.to_payload() for item in self.issues],
        }

    def authority_payload(self) -> dict[str, Any]:
        return {
            "artifacts": [item.authority_payload() for item in self.artifacts],
            "evidence": [item.to_payload() for item in self.evidence],
            "issues": [item.to_payload() for item in self.issues],
        }

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
            issues=tuple(
                ExtractionIssue.from_payload(item)
                for item in _mapping_sequence(payload.get("issues", ()), "$.state.issues")
            ),
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
        object.__setattr__(self, "input_artifact_refs", tuple(self.input_artifact_refs))
        object.__setattr__(self, "output_artifact_refs", tuple(self.output_artifact_refs))
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
            "input_artifact_refs": [item.authority_payload() for item in self.input_artifact_refs],
            "output_artifact_refs": [item.authority_payload() for item in self.output_artifact_refs],
            "result": self.result,
            "usage": thaw_json(self.usage),
            "latency_ms": self.latency_ms,
        }

    def to_ref(self) -> ExtractionAttemptRef:
        return ExtractionAttemptRef(
            attempt_id=self.attempt_id,
            attempt_hash=self.attempt_hash,
            authority=self.authority_payload(),
        )

    @classmethod
    def from_authority_payload(cls, payload: Mapping[str, Any]) -> ExtractionAttemptRecord:
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
                        "$.attempt.input_artifact_refs",
                    )
                ),
                output_artifact_refs=tuple(
                    ExtractionArtifactRef.from_payload(item)
                    for item in _mapping_sequence(
                        payload["output_artifact_refs"],
                        "$.attempt.output_artifact_refs",
                    )
                ),
                result=str(payload["result"]),  # type: ignore[arg-type]
                usage=_mapping(payload["usage"], "$.attempt.usage"),
                latency_ms=int(payload["latency_ms"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("extraction.attempt_ledger_mismatch", "$.attempt", str(exc)) from exc

    def validate(self, base_context_id: str) -> None:
        if self.base_context_id != base_context_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt.base_context_id",
                f"expected {base_context_id}, got {self.base_context_id}",
            )
        if not self.attempt_id or not self.provider:
            raise _error("extraction.attempt_ledger_mismatch", "$.attempt", "attempt id and provider are required")
        if self.route not in _ROUTES or self.result not in _ATTEMPT_RESULTS:
            raise _error("extraction.attempt_ledger_mismatch", "$.attempt", "invalid route or result")
        if self.latency_ms < 0:
            raise _error("extraction.attempt_ledger_mismatch", "$.attempt.latency_ms", "latency must be non-negative")
        refs = self.input_artifact_refs + self.output_artifact_refs
        _validate_unique((item.artifact_id for item in refs), "$.attempt.artifact_refs")
        for index, artifact in enumerate(refs):
            artifact.validate(f"$.attempt.artifact_refs[{index}]")


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
            authority=_mapping(payload["authority"], "$.attempt_refs.authority"),
        )

    @property
    def base_context_id(self) -> str:
        return str(self.authority["base_context_id"])

    def validate(self, path: str) -> None:
        record = ExtractionAttemptRecord.from_authority_payload(self.authority)
        record.validate(record.base_context_id)
        if record.attempt_id != self.attempt_id or record.attempt_hash != self.attempt_hash:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                path,
                "attempt ref differs from its authority payload",
            )


@dataclass(frozen=True)
class ExtractionAttemptLedger:
    base_context_id: str
    attempts: tuple[ExtractionAttemptRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempts", tuple(self.attempts))

    @classmethod
    def for_context(cls, context: ProblemExtractionContext) -> ExtractionAttemptLedger:
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
        for existing in self.attempts:
            existing.validate(self.base_context_id)
        attempt.validate(self.base_context_id)
        prior = next((item for item in self.attempts if item.attempt_id == attempt.attempt_id), None)
        if prior is not None:
            if prior.attempt_hash == attempt.attempt_hash:
                return self
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt.attempt_id",
                "attempt id was reused with different content",
            )
        used = context.retry.attempts_used + len(self.attempts) + 1
        if used > context.retry.attempt_budget:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.retry.attempt_budget",
                f"attempt budget exhausted ({used}>{context.retry.attempt_budget})",
            )
        return replace(self, attempts=(*self.attempts, attempt))


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
        object.__setattr__(self, "ancestor_context_ids", tuple(self.ancestor_context_ids))

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
    events: tuple[ExtractionEvent, ...]
    attempt_refs: tuple[ExtractionAttemptRef, ...]
    retry: ExtractionRetryState
    projection: ExtractionProjection
    quality: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
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
            source = ProblemSourceFingerprint.from_payload(_mapping(payload["source"], "$.source"))
            selection = SourceSelection.from_payload(_mapping(payload["selection"], "$.selection"), source)
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
                    parent_context_id=_optional_string(manifest_payload.get("parent_context_id")),
                    ancestor_context_ids=tuple(str(item) for item in manifest_payload["ancestor_context_ids"]),
                    dependency_hash=str(manifest_payload["dependency_hash"]),
                    state_hash=str(manifest_payload["state_hash"]),
                    producer=str(manifest_payload["producer"]),
                    producer_version=str(manifest_payload["producer_version"]),
                ),
                source=source,
                selection=selection,
                dependency=dependency,
                state=ExtractionState.from_payload(_mapping(payload["state"], "$.state")),
                events=tuple(
                    ExtractionEvent.from_payload(item)
                    for item in _mapping_sequence(payload["events"], "$.events")
                ),
                attempt_refs=tuple(
                    ExtractionAttemptRef.from_payload(item)
                    for item in _mapping_sequence(payload["attempt_refs"], "$.attempt_refs")
                ),
                retry=ExtractionRetryState.from_payload(_mapping(payload["retry"], "$.retry")),
                projection=ExtractionProjection.from_payload(_mapping(payload["projection"], "$.projection")),
                quality=_mapping(payload["quality"], "$.quality"),
            )
        except ProblemExtractionContextError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("extraction.context_hash_mismatch", "$", str(exc)) from exc
        validate_problem_extraction_context(context, ancestor_contexts=ancestor_contexts)
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
        producer_version: str = "v3",
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
            events=(ExtractionEvent(0, "context_initialized"),),
            attempt_refs=(),
            retry=retry or ExtractionRetryState(),
            projection=ExtractionProjection(),
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
        projection: ExtractionProjection | None = None,
        retry: ExtractionRetryState | None = None,
    ) -> ProblemExtractionContext:
        validate_problem_extraction_context(context, ancestor_contexts=ancestor_contexts)
        if attempt_ledger.base_context_id != context.manifest.context_id:
            raise _error(
                "extraction.attempt_ledger_mismatch",
                "$.attempt_ledger.base_context_id",
                "ledger does not belong to trusted child base",
            )
        attempt_refs = _merge_attempt_refs(context.attempt_refs, attempt_ledger)
        next_retry = retry or replace(context.retry, attempts_used=len(attempt_refs))
        return _assemble_context(
            source=context.source,
            selection=context.selection,
            dependency=context.dependency,
            state=state,
            parent_context=context,
            ancestor_contexts=ancestor_contexts,
            producer=producer,
            producer_version=producer_version,
            events=(*context.events, ExtractionEvent(len(context.events), event, event_payload or {})),
            attempt_refs=attempt_refs,
            retry=next_retry,
            projection=projection or context.projection,
            quality=quality if quality is not None else context.quality,
        )


def validate_problem_extraction_context(
    context: ProblemExtractionContext,
    *,
    ancestor_contexts: Sequence[ProblemExtractionContext] = (),
) -> None:
    context.source.validate()
    context.selection.validate(context.source)
    context.dependency.validate(context.source, context.selection)
    if context.manifest.schema_version != CONTEXT_SCHEMA_VERSION:
        raise _error("extraction.context_hash_mismatch", "$.manifest.schema_version", "unsupported Context schema")
    if context.manifest.dependency_hash != context.dependency.dependency_hash:
        raise _error("extraction.dependency_hash_mismatch", "$.manifest.dependency_hash", "manifest dependency hash drifted")
    _validate_state(context.state, context.source)
    expected_state_hash = stable_hash(context.state.authority_payload())
    if context.manifest.state_hash != expected_state_hash:
        raise _error("extraction.context_hash_mismatch", "$.manifest.state_hash", "state hash drifted")
    _validate_lineage(context, ancestor_contexts)
    _validate_events(context.events)
    _validate_attempt_refs(context)
    _validate_retry(context.retry, len(context.attempt_refs))
    _validate_projection(context.projection, context.state)
    expected_id = _context_id(
        manifest=replace(context.manifest, context_id=""),
        selection=context.selection,
        events=context.events,
        attempt_refs=context.attempt_refs,
        retry=context.retry,
        projection=context.projection,
        quality=context.quality,
    )
    if context.manifest.context_id != expected_id:
        raise _error("extraction.context_hash_mismatch", "$.manifest.context_id", "Context identity drifted")


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
    events: tuple[ExtractionEvent, ...],
    attempt_refs: tuple[ExtractionAttemptRef, ...],
    retry: ExtractionRetryState,
    projection: ExtractionProjection,
    quality: Mapping[str, Any],
) -> ProblemExtractionContext:
    ancestors = (
        (*parent_context.manifest.ancestor_context_ids, parent_context.manifest.context_id)
        if parent_context is not None
        else ()
    )
    manifest = ExtractionContextManifest(
        context_id="",
        schema_version=CONTEXT_SCHEMA_VERSION,
        parent_context_id=(parent_context.manifest.context_id if parent_context is not None else None),
        ancestor_context_ids=ancestors,
        dependency_hash=dependency.dependency_hash,
        state_hash=stable_hash(state.authority_payload()),
        producer=producer,
        producer_version=producer_version,
    )
    frozen_quality = freeze_json(quality)
    if not isinstance(frozen_quality, Mapping):
        raise _error("extraction.context_hash_mismatch", "$.quality", "quality must be an object")
    manifest = replace(
        manifest,
        context_id=_context_id(
            manifest=manifest,
            selection=selection,
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
        events=events,
        attempt_refs=attempt_refs,
        retry=retry,
        projection=projection,
        quality=frozen_quality,
    )
    supplied_ancestors = tuple(ancestor_contexts) + ((parent_context,) if parent_context is not None else ())
    validate_problem_extraction_context(context, ancestor_contexts=supplied_ancestors)
    return context


def _context_id(
    *,
    manifest: ExtractionContextManifest,
    selection: SourceSelection,
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
            "events": [item.to_payload() for item in events],
            "attempt_refs": [item.to_payload() for item in attempt_refs],
            "retry": retry.to_payload(),
            "projection": projection.to_payload(),
            "quality": thaw_json(quality),
        }
    )
    return f"extraction-context:{digest}"


def _validate_state(state: ExtractionState, source: ProblemSourceFingerprint) -> None:
    artifact_ids = [item.artifact_id for item in state.artifacts]
    evidence_ids = [item.evidence_id for item in state.evidence]
    _validate_unique(artifact_ids, "$.state.artifacts")
    _validate_unique(evidence_ids, "$.state.evidence")
    artifact_set = set(artifact_ids)
    page_ids = {item.page_id for item in source.pages}
    for index, artifact in enumerate(state.artifacts):
        artifact.validate(f"$.state.artifacts[{index}]")
    for index, evidence in enumerate(state.evidence):
        if evidence.artifact_id not in artifact_set or evidence.page_id not in page_ids:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.evidence[{index}]",
                "evidence references an unknown artifact or page",
            )
    for index, issue in enumerate(state.issues):
        missing = sorted(set(issue.evidence_ids) - set(evidence_ids))
        if missing:
            raise _error(
                "extraction.evidence_ref_unresolved",
                f"$.state.issues[{index}].evidence_ids",
                f"unknown evidence {missing[0]!r}",
            )


def _validate_lineage(
    context: ProblemExtractionContext,
    ancestor_contexts: Sequence[ProblemExtractionContext],
) -> None:
    expected_ids = tuple(item.manifest.context_id for item in ancestor_contexts)
    if context.manifest.parent_context_id is None:
        if context.manifest.ancestor_context_ids or expected_ids:
            raise _error("extraction.context_lineage_unresolved", "$.manifest", "root Context cannot have ancestors")
        return
    if expected_ids != context.manifest.ancestor_context_ids:
        raise _error(
            "extraction.context_lineage_unresolved",
            "$.manifest.ancestor_context_ids",
            "the complete ordered ancestor chain is required",
        )
    if not expected_ids or expected_ids[-1] != context.manifest.parent_context_id:
        raise _error("extraction.context_lineage_unresolved", "$.manifest.parent_context_id", "immediate parent is unresolved")
    parent = ancestor_contexts[-1]
    validate_problem_extraction_context(parent, ancestor_contexts=ancestor_contexts[:-1])
    if (
        parent.source.source_id != context.source.source_id
        or parent.selection.selection_id != context.selection.selection_id
        or parent.dependency.dependency_hash != context.dependency.dependency_hash
    ):
        raise _error("extraction.context_lineage_unresolved", "$.manifest.parent_context_id", "parent authority differs")
    if context.events[: len(parent.events)] != parent.events:
        raise _error("extraction.context_lineage_unresolved", "$.events", "event history is not a parent prefix")
    if context.attempt_refs[: len(parent.attempt_refs)] != parent.attempt_refs:
        raise _error("extraction.context_lineage_unresolved", "$.attempt_refs", "attempt history is not a parent prefix")


def _validate_events(events: Sequence[ExtractionEvent]) -> None:
    if not events or tuple(item.sequence for item in events) != tuple(range(len(events))):
        raise _error("extraction.context_hash_mismatch", "$.events", "event sequence must be contiguous")
    if any(not item.event for item in events):
        raise _error("extraction.context_hash_mismatch", "$.events", "event names are required")


def _validate_attempt_refs(context: ProblemExtractionContext) -> None:
    _validate_unique((item.attempt_id for item in context.attempt_refs), "$.attempt_refs")
    valid_bases = set(context.manifest.ancestor_context_ids) | {context.manifest.context_id}
    for index, item in enumerate(context.attempt_refs):
        item.validate(f"$.attempt_refs[{index}]")
        if item.base_context_id not in valid_bases:
            raise _error(
                "extraction.context_lineage_unresolved",
                f"$.attempt_refs[{index}].authority.base_context_id",
                "attempt base is outside the Context lineage",
            )


def _validate_retry(retry: ExtractionRetryState, attempt_count: int) -> None:
    if retry.attempt_budget < 0 or retry.attempts_used < 0:
        raise _error("extraction.attempt_ledger_mismatch", "$.retry", "attempt counters must be non-negative")
    if retry.attempts_used != attempt_count or retry.attempts_used > retry.attempt_budget:
        raise _error("extraction.attempt_ledger_mismatch", "$.retry.attempts_used", "attempt counter differs from committed refs or exceeds budget")


def _validate_projection(projection: ExtractionProjection, state: ExtractionState) -> None:
    if projection.status not in _PROJECTION_STATUSES:
        raise _error("extraction.context_hash_mismatch", "$.projection.status", "invalid projection status")
    artifact_ids = {item.artifact_id for item in state.artifacts}
    artifact_kind_by_id = {item.artifact_id: item.kind for item in state.artifacts}
    authority_values = (
        projection.problem_draft_artifact_id,
        projection.verified_problem_artifact_id,
        projection.solver_problem_projection_artifact_id,
        projection.problem_revision_id,
        projection.problem_semantic_hash,
        projection.family_id,
        projection.validation_artifact_id,
    )
    if projection.status == "pending":
        if any(value is not None for value in authority_values):
            raise _error("extraction.context_hash_mismatch", "$.projection", "pending projection cannot carry result authority")
        return
    if projection.validation_artifact_id not in artifact_ids:
        raise _error("extraction.context_hash_mismatch", "$.projection.validation_artifact_id", "validation artifact is missing")
    if artifact_kind_by_id.get(projection.validation_artifact_id) != "problem_validation_report":
        raise _error("extraction.context_hash_mismatch", "$.projection.validation_artifact_id", "validation artifact has the wrong kind")
    if projection.problem_revision_id is not None and not re.fullmatch(
        r"problem-revision:[a-f0-9]{64}", projection.problem_revision_id
    ):
        raise _error("extraction.context_hash_mismatch", "$.projection.problem_revision_id", "problem revision id is invalid")
    if projection.status == "accepted":
        required = (
            projection.verified_problem_artifact_id,
            projection.solver_problem_projection_artifact_id,
            projection.problem_revision_id,
            projection.problem_semantic_hash,
            projection.family_id,
        )
        if (
            any(value is None for value in required)
            or projection.problem_draft_artifact_id is not None
            or projection.verified_problem_artifact_id not in artifact_ids
            or projection.solver_problem_projection_artifact_id not in artifact_ids
        ):
            raise _error("extraction.context_hash_mismatch", "$.projection", "accepted projection authority is incomplete")
        if artifact_kind_by_id.get(projection.verified_problem_artifact_id) != "verified_problem":
            raise _error("extraction.context_hash_mismatch", "$.projection.verified_problem_artifact_id", "verified problem artifact has the wrong kind")
        if (
            artifact_kind_by_id.get(
                projection.solver_problem_projection_artifact_id
            )
            != SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND
        ):
            raise _error(
                "extraction.context_hash_mismatch",
                "$.projection.solver_problem_ir_artifact_id",
                "Solver projection envelope artifact has the wrong kind",
            )
        _validate_sha(str(projection.problem_semantic_hash), "$.projection.problem_semantic_hash")
        return
    if (
        (projection.problem_draft_artifact_id is None)
        != (projection.problem_revision_id is None)
        or any(
            value is not None
            for value in (
                projection.verified_problem_artifact_id,
                projection.solver_problem_projection_artifact_id,
                projection.problem_semantic_hash,
                projection.family_id,
            )
        )
    ):
        raise _error("extraction.context_hash_mismatch", "$.projection", "blocked projection authority is incomplete or carries accepted state")
    if projection.problem_draft_artifact_id is not None and (
        projection.problem_draft_artifact_id not in artifact_ids
        or artifact_kind_by_id.get(projection.problem_draft_artifact_id) != "problem_draft"
    ):
        raise _error("extraction.context_hash_mismatch", "$.projection.problem_draft_artifact_id", "blocked Draft artifact is missing or has the wrong kind")


def _merge_attempt_refs(
    prior: Sequence[ExtractionAttemptRef],
    ledger: ExtractionAttemptLedger,
) -> tuple[ExtractionAttemptRef, ...]:
    result = list(prior)
    by_id = {item.attempt_id: item for item in result}
    for attempt in ledger.attempts:
        attempt.validate(ledger.base_context_id)
        ref = attempt.to_ref()
        existing = by_id.get(ref.attempt_id)
        if existing is not None:
            if existing.attempt_hash != ref.attempt_hash:
                raise _error("extraction.attempt_ledger_mismatch", "$.attempt_refs", "attempt id hash drifted")
            continue
        by_id[ref.attempt_id] = ref
        result.append(ref)
    return tuple(result)


def _validate_context_schema(payload: Mapping[str, Any]) -> None:
    errors = sorted(_context_schema_validator().iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        raise _error("extraction.context_hash_mismatch", _json_path(first.path), first.message)


@lru_cache(maxsize=1)
def _context_schema_validator() -> Draft202012Validator:
    path = Path(__file__).resolve().parents[4] / "internal/schemas/problem-extraction-context.schema.json"
    schema = __import__("json").loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("extraction.context_hash_mismatch", path, "expected an object")
    return value


def _mapping_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _error("extraction.context_hash_mismatch", path, "expected an array")
    result = tuple(value)
    if not all(isinstance(item, Mapping) for item in result):
        raise _error("extraction.context_hash_mismatch", path, "array items must be objects")
    return result  # type: ignore[return-value]


def _validate_unique(values: Sequence[str] | Any, path: str) -> None:
    items = tuple(values)
    if any(not item for item in items) or len(items) != len(set(items)):
        raise _error("extraction.context_hash_mismatch", path, "identities must be unique and non-empty")


def _validate_sha(value: str, path: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise _error("extraction.context_hash_mismatch", path, "expected lowercase SHA-256")


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _json_path(parts: Sequence[object]) -> str:
    return "$" + "".join(f"[{part!r}]" for part in parts)


def _error(code: str, path: str, message: str) -> ProblemExtractionContextError:
    return ProblemExtractionContextError(code, path, message)


__all__ = [
    "CONTEXT_SCHEMA_VERSION",
    "ExtractionArtifactRef",
    "ExtractionAttemptLedger",
    "ExtractionAttemptRecord",
    "ExtractionAttemptRef",
    "ExtractionContextManifest",
    "ExtractionEvent",
    "ExtractionEvidenceRecord",
    "ExtractionIssue",
    "ExtractionProjection",
    "ExtractionRetryState",
    "ExtractionState",
    "ProblemExtractionContext",
    "ProblemExtractionContextBuilder",
    "validate_problem_extraction_context",
]
