"""Immutable domain model for multimodal problem extraction.

The LLM authors ``problem-domain/v1``.  Runtime identifiers, validation state,
retry ownership, and Solver-compatible handles are deliberately absent from
that wire contract and are assigned by this module after parsing.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from functools import lru_cache
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping, Sequence
import unicodedata

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.source_identity import (
    FrozenJson,
    freeze_json,
    stable_hash,
    thaw_json,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY


PROBLEM_DOMAIN_CONTRACT = "problem-domain/v1"
PROBLEM_REPAIR_CONTRACT = "problem-repair/v1"
PROBLEM_DRAFT_CONTRACT = "problem-draft/v1"
VERIFIED_PROBLEM_CONTRACT = "verified-problem/v1"
PROBLEM_DOMAIN_PROVIDER_MAX_SCOPE_DEPTH = 4
PROBLEM_DOMAIN_MAX_TEXT_LENGTH = 2_048
PROBLEM_DOMAIN_MAX_EXPRESSION_LENGTH = 1_024
PROBLEM_DOMAIN_MAX_SOURCE_LINES_PER_SCOPE = 12
PROBLEM_DOMAIN_MAX_ENTITIES_PER_SCOPE = 32
PROBLEM_DOMAIN_MAX_FACTS_PER_SCOPE = 48
PROBLEM_DOMAIN_MAX_GOALS_PER_SCOPE = 12
PROBLEM_DOMAIN_MAX_CHILDREN_PER_SCOPE = 8
PROBLEM_DOMAIN_MAX_VALUE_TERMS = 16
PROBLEM_REPAIR_MAX_OPERATIONS = 32

UnitStatus = Literal["verified", "invalid", "dependent"]
UnitKind = Literal["family", "scope", "entity", "fact", "goal"]
RepairCollection = Literal["scope", "entity", "fact", "goal"]

_LOCAL_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"
_EXPRESSION_PATTERN = r"^[^\x00-\x1f\x7f]+$"
_PROMOTION_TOKEN = object()


class ProblemDomainError(ValueError):
    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class ProblemSource:
    question_number: str
    score: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "question_number": self.question_number,
            "score": self.score,
        }


@dataclass(frozen=True)
class ProblemEntity:
    unit_id: str
    local_id: str
    kind: str
    label: str
    attributes: Mapping[str, FrozenJson] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_json(self.attributes))

    def wire_payload(self) -> dict[str, Any]:
        return {
            "id": self.local_id,
            "kind": self.kind,
            "label": self.label,
            **thaw_json(self.attributes),
        }

    @property
    def semantic_signature(self) -> str:
        return stable_hash(self.wire_payload())


@dataclass(frozen=True)
class ProblemFact:
    unit_id: str
    kind: str
    attributes: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_json(self.attributes))

    def wire_payload(self) -> dict[str, Any]:
        return {"kind": self.kind, **thaw_json(self.attributes)}

    @property
    def semantic_signature(self) -> str:
        return stable_hash(self.wire_payload())


@dataclass(frozen=True)
class ProblemGoal:
    unit_id: str
    kind: str
    answer_key: str
    attributes: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", freeze_json(self.attributes))

    def wire_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "answer_key": self.answer_key,
            **thaw_json(self.attributes),
        }

    @property
    def semantic_signature(self) -> str:
        return stable_hash(self.wire_payload())


@dataclass(frozen=True)
class ProblemScope:
    unit_id: str
    local_id: str
    label: str
    source_text: tuple[str, ...]
    entities: tuple[ProblemEntity, ...]
    facts: tuple[ProblemFact, ...]
    goals: tuple[ProblemGoal, ...]
    children: tuple["ProblemScope", ...]
    path: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_text", tuple(self.source_text))
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(self, "goals", tuple(self.goals))
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "path", tuple(self.path))

    @property
    def path_id(self) -> str:
        return "/".join(self.path)

    def wire_payload(self) -> dict[str, Any]:
        return {
            "id": self.local_id,
            "label": self.label,
            "source_text": list(self.source_text),
            "entities": [item.wire_payload() for item in self.entities],
            "facts": [item.wire_payload() for item in self.facts],
            "goals": [item.wire_payload() for item in self.goals],
            "children": [item.wire_payload() for item in self.children],
        }

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "id": self.local_id,
            "label": self.label,
            "source_text": list(self.source_text),
            "entities": sorted(
                (item.wire_payload() for item in self.entities),
                key=_stable_json,
            ),
            "facts": sorted(
                (item.wire_payload() for item in self.facts),
                key=_stable_json,
            ),
            "goals": sorted(
                (item.wire_payload() for item in self.goals),
                key=_stable_json,
            ),
            # Child order is source order and therefore semantic.
            "children": [item.semantic_payload() for item in self.children],
        }

    def iter_scopes(self) -> Iterable["ProblemScope"]:
        yield self
        for child in self.children:
            yield from child.iter_scopes()


@dataclass(frozen=True)
class ProblemGraph:
    problem_id: str
    family_id: str
    source: ProblemSource
    root_scope: ProblemScope

    def wire_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROBLEM_DOMAIN_CONTRACT,
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "source": self.source.to_payload(),
            "root": self.root_scope.wire_payload(),
        }

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "source": self.source.to_payload(),
            "root": self.root_scope.semantic_payload(),
        }

    @property
    def semantic_hash(self) -> str:
        return stable_hash(_graph_semantic_equivalence_payload(self))

    @property
    def original_text_lines(self) -> tuple[str, ...]:
        return tuple(
            line
            for scope in self.root_scope.iter_scopes()
            for line in scope.source_text
        )

    @property
    def scope_by_path(self) -> dict[str, ProblemScope]:
        return {scope.path_id: scope for scope in self.root_scope.iter_scopes()}


@dataclass(frozen=True)
class ProblemUnitRecord:
    unit_id: str
    unit_kind: UnitKind
    scope_path: str
    semantic_signature: str
    local_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "unit_kind": self.unit_kind,
            "scope_path": self.scope_path,
            "semantic_signature": self.semantic_signature,
            "local_id": self.local_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProblemUnitRecord":
        return cls(
            unit_id=str(payload["unit_id"]),
            unit_kind=str(payload["unit_kind"]),  # type: ignore[arg-type]
            scope_path=str(payload["scope_path"]),
            semantic_signature=str(payload["semantic_signature"]),
            local_id=(
                str(payload["local_id"])
                if payload.get("local_id") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ProblemValidationIssue:
    code: str
    unit_ids: tuple[str, ...]
    dependency_unit_ids: tuple[str, ...]
    message: str
    repair_action: str
    region_refs: tuple[str, ...] = ()
    retryable: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_ids", tuple(self.unit_ids))
        object.__setattr__(self, "dependency_unit_ids", tuple(self.dependency_unit_ids))
        object.__setattr__(self, "region_refs", tuple(self.region_refs))

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "unit_ids": list(self.unit_ids),
            "dependency_unit_ids": list(self.dependency_unit_ids),
            "message": self.message,
            "repair_action": self.repair_action,
            "region_refs": list(self.region_refs),
            "retryable": self.retryable,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProblemValidationIssue":
        return cls(
            code=str(payload["code"]),
            unit_ids=tuple(str(item) for item in payload.get("unit_ids", ())),
            dependency_unit_ids=tuple(
                str(item) for item in payload.get("dependency_unit_ids", ())
            ),
            message=str(payload["message"]),
            repair_action=str(payload["repair_action"]),
            region_refs=tuple(str(item) for item in payload.get("region_refs", ())),
            retryable=bool(payload.get("retryable", True)),
        )


@dataclass(frozen=True)
class ProblemVerificationStamp:
    unit_id: str
    semantic_signature: str
    validator_ids: tuple[str, ...]
    dependency_signatures: tuple[str, ...]
    status: UnitStatus

    def to_payload(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "semantic_signature": self.semantic_signature,
            "validator_ids": list(self.validator_ids),
            "dependency_signatures": list(self.dependency_signatures),
            "status": self.status,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProblemVerificationStamp":
        return cls(
            unit_id=str(payload["unit_id"]),
            semantic_signature=str(payload["semantic_signature"]),
            validator_ids=tuple(str(item) for item in payload.get("validator_ids", ())),
            dependency_signatures=tuple(
                str(item) for item in payload.get("dependency_signatures", ())
            ),
            status=str(payload["status"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ProblemValidationReport:
    issues: tuple[ProblemValidationIssue, ...] = ()
    validator_ids: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def first_issue(self) -> ProblemValidationIssue | None:
        return self.issues[0] if self.issues else None

    @property
    def issue_signature(self) -> str:
        return stable_hash([item.to_payload() for item in self.issues])

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "validator_ids": list(self.validator_ids),
            "issue_signature": self.issue_signature,
            "issues": [item.to_payload() for item in self.issues],
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProblemValidationReport":
        return cls(
            issues=tuple(
                ProblemValidationIssue.from_payload(item)
                for item in payload.get("issues", ())
            ),
            validator_ids=tuple(str(item) for item in payload.get("validator_ids", ())),
        )


@dataclass(frozen=True)
class ProblemDraft:
    graph: ProblemGraph
    revision_id: str
    parent_revision_id: str | None
    unit_registry: Mapping[str, ProblemUnitRecord]
    validation_report: ProblemValidationReport
    verification_stamps: Mapping[str, ProblemVerificationStamp]
    repairable_unit_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unit_registry",
            MappingProxyType(dict(self.unit_registry)),
        )
        object.__setattr__(
            self,
            "verification_stamps",
            MappingProxyType(dict(self.verification_stamps)),
        )
        object.__setattr__(self, "repairable_unit_ids", tuple(self.repairable_unit_ids))

    @classmethod
    def create(
        cls,
        payload: Mapping[str, Any] | str,
        *,
        parent_revision_id: str | None = None,
    ) -> "ProblemDraft":
        raw = _load_json_object(payload, "extraction.problem_domain_invalid_json")
        _validate_schema(raw, _domain_validator(), "extraction.problem_domain_schema_invalid")
        graph = _parse_graph(raw)
        return cls.from_graph(graph, parent_revision_id=parent_revision_id)

    @classmethod
    def from_graph(
        cls,
        graph: ProblemGraph,
        *,
        parent_revision_id: str | None = None,
        validation_report: ProblemValidationReport | None = None,
        verification_stamps: Mapping[str, ProblemVerificationStamp] | None = None,
        repairable_unit_ids: Sequence[str] = (),
    ) -> "ProblemDraft":
        registry = _unit_registry(graph)
        revision_id = "problem-revision:" + stable_hash(
            {
                "parent_revision_id": parent_revision_id,
                "semantic": graph.semantic_payload(),
            }
        )
        return cls(
            graph=graph,
            revision_id=revision_id,
            parent_revision_id=parent_revision_id,
            unit_registry=registry,
            validation_report=validation_report or ProblemValidationReport(),
            verification_stamps=verification_stamps or {},
            repairable_unit_ids=tuple(sorted(set(repairable_unit_ids))),
        )

    @property
    def semantic_hash(self) -> str:
        return self.graph.semantic_hash

    @property
    def frozen_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                unit_id
                for unit_id, stamp in self.verification_stamps.items()
                if stamp.status == "verified"
            )
        )

    def with_validation(
        self,
        report: ProblemValidationReport,
        stamps: Mapping[str, ProblemVerificationStamp],
        repairable_unit_ids: Sequence[str],
    ) -> "ProblemDraft":
        return replace(
            self,
            validation_report=report,
            verification_stamps=dict(stamps),
            repairable_unit_ids=tuple(sorted(set(repairable_unit_ids))),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROBLEM_DRAFT_CONTRACT,
            "graph": self.graph.wire_payload(),
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "semantic_hash": self.semantic_hash,
            "unit_registry": [
                self.unit_registry[key].to_payload()
                for key in sorted(self.unit_registry)
            ],
            "validation_report": self.validation_report.to_payload(),
            "verification_stamps": [
                self.verification_stamps[key].to_payload()
                for key in sorted(self.verification_stamps)
            ],
            "repairable_unit_ids": list(self.repairable_unit_ids),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ProblemDraft":
        if payload.get("schema_version") != PROBLEM_DRAFT_CONTRACT:
            raise ProblemDomainError(
                "extraction.problem_domain_schema_invalid",
                "$.schema_version",
                "unsupported ProblemDraft schema",
            )
        graph_payload = payload.get("graph")
        if not isinstance(graph_payload, Mapping):
            raise ProblemDomainError(
                "extraction.problem_domain_schema_invalid", "$.graph", "graph is required"
            )
        serialized_records = tuple(
            ProblemUnitRecord.from_payload(item)
            for item in _mapping_sequence(
                payload.get("unit_registry", ()), "$.unit_registry"
            )
        )
        if not serialized_records or len({item.unit_id for item in serialized_records}) != len(
            serialized_records
        ):
            raise ProblemDomainError(
                "extraction.problem_revision_drift",
                "$.unit_registry",
                "ProblemDraft unit registry is missing or contains duplicate ids",
            )
        parent_revision_id = (
            str(payload["parent_revision_id"])
            if payload.get("parent_revision_id") is not None
            else None
        )
        graph = _parse_graph(graph_payload, unit_records=serialized_records)
        draft = cls.from_graph(
            graph,
            parent_revision_id=parent_revision_id,
        )
        if draft.revision_id != payload.get("revision_id") or draft.semantic_hash != payload.get(
            "semantic_hash"
        ):
            raise ProblemDomainError(
                "extraction.problem_revision_drift",
                "$.revision_id",
                "ProblemDraft identity does not match its graph",
            )
        restored_records = tuple(
            draft.unit_registry[key].to_payload() for key in sorted(draft.unit_registry)
        )
        supplied_records = tuple(
            item.to_payload() for item in sorted(serialized_records, key=lambda item: item.unit_id)
        )
        if restored_records != supplied_records:
            raise ProblemDomainError(
                "extraction.problem_revision_drift",
                "$.unit_registry",
                "ProblemDraft unit registry does not match its graph",
            )
        report = ProblemValidationReport.from_payload(
            _mapping(payload.get("validation_report", {}), "$.validation_report")
        )
        stamps = {
            str(item["unit_id"]): ProblemVerificationStamp.from_payload(item)
            for item in _mapping_sequence(
                payload.get("verification_stamps", ()), "$.verification_stamps"
            )
        }
        restored = draft.with_validation(
            report,
            stamps,
            tuple(str(item) for item in payload.get("repairable_unit_ids", ())),
        )
        _validate_stamps(restored)
        return restored


@dataclass(frozen=True)
class VerifiedProblem:
    graph: ProblemGraph
    revision_id: str
    parent_revision_id: str | None
    semantic_hash: str
    family_id: str
    verification_proof: Mapping[str, FrozenJson]
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _PROMOTION_TOKEN:
            raise TypeError("VerifiedProblem can only be created by promotion")
        object.__setattr__(self, "verification_proof", freeze_json(self.verification_proof))

    @classmethod
    def _create(
        cls,
        draft: ProblemDraft,
        *,
        proof: Mapping[str, Any],
        token: object,
    ) -> "VerifiedProblem":
        if token is not _PROMOTION_TOKEN:
            raise TypeError("VerifiedProblem can only be created by promotion")
        return cls(
            graph=draft.graph,
            revision_id=draft.revision_id,
            parent_revision_id=draft.parent_revision_id,
            semantic_hash=draft.semantic_hash,
            family_id=draft.graph.family_id,
            verification_proof=proof,
            _authority=token,
        )

    def fork_draft(self) -> ProblemDraft:
        return ProblemDraft.from_graph(
            self.graph,
            parent_revision_id=self.revision_id,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": VERIFIED_PROBLEM_CONTRACT,
            "graph": self.graph.wire_payload(),
            "revision_id": self.revision_id,
            "parent_revision_id": self.parent_revision_id,
            "semantic_hash": self.semantic_hash,
            "family_id": self.family_id,
            "unit_registry": [
                item.to_payload()
                for item in sorted(
                    _unit_registry(self.graph).values(), key=lambda item: item.unit_id
                )
            ],
            "verification_proof": thaw_json(self.verification_proof),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "VerifiedProblem":
        """Hydrate an internally authenticated VerifiedProblem artifact.

        This verifies graph, identity, registry, and proof self-consistency. The
        caller remains responsible for authenticating the artifact hash against
        its accepted ProblemExtractionContext before calling this method.
        """

        if payload.get("schema_version") != VERIFIED_PROBLEM_CONTRACT:
            raise ProblemDomainError(
                "extraction.problem_domain_schema_invalid",
                "$.schema_version",
                "unsupported VerifiedProblem schema",
            )
        graph_payload = _mapping(payload.get("graph"), "$.graph")
        records = tuple(
            ProblemUnitRecord.from_payload(item)
            for item in _mapping_sequence(
                payload.get("unit_registry", ()), "$.unit_registry"
            )
        )
        graph = _parse_graph(graph_payload, unit_records=records)
        proof = _mapping(payload.get("verification_proof"), "$.verification_proof")
        report = ProblemValidationReport.from_payload(
            _mapping(proof.get("validation_report"), "$.verification_proof.validation_report")
        )
        stamps = {
            str(item["unit_id"]): ProblemVerificationStamp.from_payload(item)
            for item in _mapping_sequence(
                proof.get("verification_stamps", ()),
                "$.verification_proof.verification_stamps",
            )
        }
        draft = ProblemDraft.from_graph(
            graph,
            parent_revision_id=(
                str(payload["parent_revision_id"])
                if payload.get("parent_revision_id") is not None
                else None
            ),
            validation_report=report,
            verification_stamps=stamps,
        )
        supplied_records = tuple(
            item.to_payload() for item in sorted(records, key=lambda item: item.unit_id)
        )
        actual_records = tuple(
            draft.unit_registry[key].to_payload() for key in sorted(draft.unit_registry)
        )
        if (
            draft.revision_id != payload.get("revision_id")
            or draft.semantic_hash != payload.get("semantic_hash")
            or draft.graph.family_id != payload.get("family_id")
            or supplied_records != actual_records
        ):
            raise ProblemDomainError(
                "extraction.problem_revision_drift",
                "$",
                "VerifiedProblem identity does not match its graph",
            )
        return ProblemPromotionService().promote(draft)


class ProblemPromotionService:
    def promote(self, draft: ProblemDraft) -> VerifiedProblem:
        _validate_stamps(draft)
        if not draft.validation_report.ok:
            raise ProblemDomainError(
                "extraction.problem_promotion_invalid",
                "$.validation_report",
                "a Draft with blocking issues cannot be promoted",
            )
        missing = sorted(set(draft.unit_registry) - set(draft.frozen_unit_ids))
        if missing:
            raise ProblemDomainError(
                "extraction.problem_promotion_invalid",
                "$.verification_stamps",
                f"all units must be verified before promotion; first missing {missing[0]!r}",
            )
        proof = {
            "validation_report": draft.validation_report.to_payload(),
            "verification_stamps": [
                draft.verification_stamps[key].to_payload()
                for key in sorted(draft.verification_stamps)
            ],
        }
        return VerifiedProblem._create(draft, proof=proof, token=_PROMOTION_TOKEN)


@dataclass(frozen=True)
class ProblemReplacement:
    unit_id: str
    value: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", freeze_json(self.value))


@dataclass(frozen=True)
class ProblemAddition:
    scope_path: str
    collection: RepairCollection
    value: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", freeze_json(self.value))


@dataclass(frozen=True)
class ProblemRepairPatch:
    base_revision_id: str
    replacements: tuple[ProblemReplacement, ...]
    additions: tuple[ProblemAddition, ...]
    removals: tuple[str, ...]
    patch_id: str

    @classmethod
    def create(cls, payload: Mapping[str, Any] | str) -> "ProblemRepairPatch":
        raw = _load_json_object(payload, "extraction.problem_repair_invalid_json")
        _validate_schema(raw, _repair_validator(), "extraction.problem_repair_schema_invalid")
        identity = stable_hash(raw)
        return cls(
            base_revision_id=str(raw["base_revision_id"]),
            replacements=tuple(
                ProblemReplacement(str(item["unit_id"]), item["value"])
                for item in raw["replacements"]
            ),
            additions=tuple(
                ProblemAddition(
                    str(item["scope_path"]),
                    str(item["collection"]),  # type: ignore[arg-type]
                    item["value"],
                )
                for item in raw["additions"]
            ),
            removals=tuple(str(item) for item in raw["removals"]),
            patch_id=f"problem-patch:{identity}",
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROBLEM_REPAIR_CONTRACT,
            "base_revision_id": self.base_revision_id,
            "replacements": [
                {"unit_id": item.unit_id, "value": thaw_json(item.value)}
                for item in self.replacements
            ],
            "additions": [
                {
                    "scope_path": item.scope_path,
                    "collection": item.collection,
                    "value": thaw_json(item.value),
                }
                for item in self.additions
            ],
            "removals": list(self.removals),
        }


class ProblemRepairService:
    """Apply one authorized repair atomically and preserve stable unit identity."""

    def apply(self, draft: ProblemDraft, patch: ProblemRepairPatch) -> ProblemDraft:
        if patch.base_revision_id != draft.revision_id:
            raise ProblemDomainError(
                "extraction.problem_patch_base_mismatch",
                "$.base_revision_id",
                "repair patch does not target the current Draft revision",
            )
        replacement_ids = [item.unit_id for item in patch.replacements]
        changed_ids = (*replacement_ids, *patch.removals)
        if len(set(changed_ids)) != len(changed_ids):
            raise ProblemDomainError(
                "extraction.problem_repair_schema_invalid",
                "$",
                "a unit may be changed at most once per patch",
            )
        repairable = set(draft.repairable_unit_ids)
        removable = {
            unit_id
            for issue in draft.validation_report.issues
            for unit_id in issue.unit_ids
            if unit_id in draft.unit_registry
        }
        for unit_id in changed_ids:
            if unit_id not in draft.unit_registry:
                raise ProblemDomainError(
                    "extraction.problem_repair_unit_unresolved",
                    "$.replacements",
                    f"unknown unit {unit_id!r}",
                )
            if unit_id in draft.frozen_unit_ids and unit_id not in repairable:
                raise ProblemDomainError(
                    "extraction.problem_frozen_unit_mutation",
                    "$.replacements",
                    f"verified unit {unit_id!r} is outside the repair cone",
                )
            if unit_id not in repairable:
                raise ProblemDomainError(
                    "extraction.problem_repair_unauthorized",
                    "$.replacements",
                    f"unit {unit_id!r} is not authorized by a blocking issue",
                )
        for unit_id in patch.removals:
            if unit_id not in removable:
                raise ProblemDomainError(
                    "extraction.problem_repair_unauthorized",
                    "$.removals",
                    f"removal of {unit_id!r} was not directly authorized by a blocking issue",
                )

        graph = draft.graph
        for item in patch.replacements:
            graph = _replace_graph_unit(graph, item.unit_id, thaw_json(item.value))
        for unit_id in patch.removals:
            graph = _remove_graph_unit(graph, unit_id)
        for operation_index, item in enumerate(patch.additions):
            if not _scope_addition_authorized(draft, item.scope_path):
                raise ProblemDomainError(
                    "extraction.problem_repair_unauthorized",
                    "$.additions",
                    f"scope {item.scope_path!r} is outside the repair cone",
                )
            graph = _add_graph_unit(
                graph,
                item,
                unit_id=(
                    f"{item.collection}:added:"
                    + stable_hash(
                        {
                            "parent_revision_id": draft.revision_id,
                            "patch_id": patch.patch_id,
                            "operation_index": operation_index,
                        }
                    )
                ),
            )
        previous_registry = draft.unit_registry
        next_registry = _unit_registry(graph)
        implicit_changes = {
            unit_id
            for unit_id in set(previous_registry).intersection(next_registry)
            if previous_registry[unit_id].semantic_signature
            != next_registry[unit_id].semantic_signature
        } | (set(previous_registry) - set(next_registry))
        unauthorized_implicit = sorted(implicit_changes - set(changed_ids))
        if unauthorized_implicit:
            raise ProblemDomainError(
                "extraction.problem_frozen_unit_mutation",
                "$.replacements",
                "repair changed an untargeted unit; first drifted unit "
                f"{unauthorized_implicit[0]!r}",
            )
        if graph.semantic_hash == draft.graph.semantic_hash:
            raise ProblemDomainError(
                "extraction.problem_retry_no_progress",
                "$",
                "repair patch did not change problem semantics",
            )
        next_draft = ProblemDraft.from_graph(
            graph,
            parent_revision_id=draft.revision_id,
        )
        # Reuse stamps only for unchanged units with unchanged dependency authority.
        reusable = {
            unit_id: stamp
            for unit_id, stamp in draft.verification_stamps.items()
            if unit_id in next_draft.unit_registry
            and unit_id in draft.unit_registry
            and next_draft.unit_registry[unit_id].semantic_signature
            == draft.unit_registry[unit_id].semantic_signature
        }
        return replace(next_draft, verification_stamps=reusable)


def problem_domain_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "problem_domain_v1",
            "strict": True,
            "schema": problem_domain_provider_schema(),
        },
    }


def problem_repair_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "problem_repair_v1",
            "strict": True,
            "schema": problem_repair_provider_schema(),
        },
    }


@lru_cache(maxsize=1)
def problem_domain_schema() -> dict[str, Any]:
    family_ids = sorted(family.family_id for family in DEFAULT_FAMILY_REGISTRY.families)
    defs: dict[str, Any] = {
        "ref": _id_schema(),
        "expression": {
            "type": "string",
            "minLength": 1,
            "maxLength": PROBLEM_DOMAIN_MAX_EXPRESSION_LENGTH,
            "pattern": _EXPRESSION_PATTERN,
        },
        "segment_term": _object_schema(
            {"start": _id_schema(), "end": _id_schema()},
            ("start", "end"),
        ),
        "ray_term": _object_schema(
            {"origin": _id_schema(), "through": _id_schema()},
            ("origin", "through"),
        ),
        "angle_term": _object_schema(
            {
                "start": _id_schema(),
                "vertex": _id_schema(),
                "end": _id_schema(),
            },
            ("start", "vertex", "end"),
        ),
        "axis_placement": _object_schema(
            {
                "point": _id_schema(),
                "relation": {
                    "type": "string",
                    "enum": [
                        "above_x_axis",
                        "below_x_axis",
                        "left_of_y_axis",
                        "right_of_y_axis",
                    ],
                },
            },
            ("point", "relation"),
        ),
        "scaled_length_term": _object_schema(
            {
                "scale": {"$ref": "#/$defs/expression"},
                "segment": {"$ref": "#/$defs/segment_term"},
            },
            ("scale", "segment"),
        ),
        "length_sum": _object_schema(
            {
                "terms": _array_schema(
                    {"$ref": "#/$defs/scaled_length_term"},
                    min_items=1,
                    max_items=PROBLEM_DOMAIN_MAX_VALUE_TERMS,
                )
            },
            ("terms",),
        ),
        "entity": {"oneOf": _entity_schemas()},
        "fact": {"oneOf": _fact_schemas()},
        "goal": {"oneOf": _goal_schemas()},
        "scope": {},
    }
    defs["scope"] = _object_schema(
        {
            "id": _id_schema(),
            "label": _text_schema(),
            "source_text": _array_schema(
                _text_schema(),
                min_items=1,
                max_items=PROBLEM_DOMAIN_MAX_SOURCE_LINES_PER_SCOPE,
            ),
            "entities": _array_schema(
                {"$ref": "#/$defs/entity"},
                max_items=PROBLEM_DOMAIN_MAX_ENTITIES_PER_SCOPE,
            ),
            "facts": _array_schema(
                {"$ref": "#/$defs/fact"},
                max_items=PROBLEM_DOMAIN_MAX_FACTS_PER_SCOPE,
            ),
            "goals": _array_schema(
                {"$ref": "#/$defs/goal"},
                max_items=PROBLEM_DOMAIN_MAX_GOALS_PER_SCOPE,
            ),
            "children": _array_schema(
                {"$ref": "#/$defs/scope"},
                max_items=PROBLEM_DOMAIN_MAX_CHILDREN_PER_SCOPE,
            ),
        },
        ("id", "label", "source_text", "entities", "facts", "goals", "children"),
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "problem_id", "family_id", "source", "root"],
        "properties": {
            "schema_version": {"const": PROBLEM_DOMAIN_CONTRACT},
            "problem_id": _text_schema(),
            "family_id": {"type": "string", "enum": family_ids},
            "source": _object_schema(
                {
                    "question_number": _text_schema(),
                    "score": {
                        "type": ["string", "null"],
                        "maxLength": PROBLEM_DOMAIN_MAX_TEXT_LENGTH,
                    },
                },
                ("question_number", "score"),
            ),
            "root": {"$ref": "#/$defs/scope"},
        },
        "$defs": defs,
    }


@lru_cache(maxsize=1)
def problem_domain_provider_schema() -> dict[str, Any]:
    """Return the provider schema with Scope recursion expanded to four levels."""

    return _finite_scope_provider_schema(problem_domain_schema())


@lru_cache(maxsize=1)
def problem_repair_schema() -> dict[str, Any]:
    family_ids = sorted(family.family_id for family in DEFAULT_FAMILY_REGISTRY.families)
    domain_defs = {
        **problem_domain_schema()["$defs"],
        "family_selection": _object_schema(
            {"family_id": {"type": "string", "enum": family_ids}},
            ("family_id",),
        ),
        "scope_replacement": _object_schema(
            {
                "id": _id_schema(),
                "label": _text_schema(),
                "source_text": _array_schema(
                    _text_schema(),
                    min_items=1,
                    max_items=PROBLEM_DOMAIN_MAX_SOURCE_LINES_PER_SCOPE,
                ),
            },
            ("id", "label", "source_text"),
        ),
    }
    replacement_value = {
        "oneOf": [
            {"$ref": "#/$defs/family_selection"},
            {"$ref": "#/$defs/entity"},
            {"$ref": "#/$defs/fact"},
            {"$ref": "#/$defs/goal"},
            {"$ref": "#/$defs/scope_replacement"},
        ]
    }
    addition_value = {
        "oneOf": [
            {"$ref": "#/$defs/entity"},
            {"$ref": "#/$defs/fact"},
            {"$ref": "#/$defs/goal"},
            {"$ref": "#/$defs/scope"},
        ]
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "base_revision_id",
            "replacements",
            "additions",
            "removals",
        ],
        "properties": {
            "schema_version": {"const": PROBLEM_REPAIR_CONTRACT},
            "base_revision_id": {
                "type": "string",
                "pattern": r"^problem-revision:[a-f0-9]{64}$",
            },
            "replacements": _array_schema(
                _object_schema(
                    {"unit_id": _text_schema(), "value": replacement_value},
                    ("unit_id", "value"),
                ),
                max_items=PROBLEM_REPAIR_MAX_OPERATIONS,
            ),
            "additions": _array_schema(
                _object_schema(
                    {
                        "scope_path": _text_schema(),
                        "collection": {
                            "type": "string",
                            "enum": ["scope", "entity", "fact", "goal"],
                        },
                        "value": addition_value,
                    },
                    ("scope_path", "collection", "value"),
                ),
                max_items=PROBLEM_REPAIR_MAX_OPERATIONS,
            ),
            "removals": _array_schema(
                _text_schema(), max_items=PROBLEM_REPAIR_MAX_OPERATIONS
            ),
        },
        "$defs": domain_defs,
    }


@lru_cache(maxsize=1)
def problem_repair_provider_schema() -> dict[str, Any]:
    """Return the repair provider schema without recursive Scope references."""

    return _finite_scope_provider_schema(problem_repair_schema())


def _finite_scope_provider_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(dict(schema))
    definitions = result.get("$defs")
    if not isinstance(definitions, dict):
        raise ValueError("problem schema is missing $defs")
    recursive_scope = definitions.pop("scope", None)
    if not isinstance(recursive_scope, Mapping):
        raise ValueError("problem schema is missing the recursive scope definition")
    properties = recursive_scope.get("properties")
    required = recursive_scope.get("required")
    if not isinstance(properties, Mapping) or not isinstance(required, list):
        raise ValueError("problem scope schema is malformed")
    scope_properties = {
        key: deepcopy(value)
        for key, value in properties.items()
        if key != "children"
    }
    for level in range(PROBLEM_DOMAIN_PROVIDER_MAX_SCOPE_DEPTH):
        if level + 1 < PROBLEM_DOMAIN_PROVIDER_MAX_SCOPE_DEPTH:
            children = _array_schema(
                {"$ref": f"#/$defs/scope_level_{level + 1}"},
                max_items=PROBLEM_DOMAIN_MAX_CHILDREN_PER_SCOPE,
            )
        else:
            # The fourth level remains a normal Scope, but it must be a leaf.
            # Avoid a recursive $ref even behind maxItems=0 because provider
            # constrained decoders may still expand that reference.
            children = _array_schema(
                _object_schema({}, ()),
                max_items=0,
            )
        definitions[f"scope_level_{level}"] = _object_schema(
            {**deepcopy(scope_properties), "children": children},
            tuple(str(item) for item in required),
        )
    _replace_schema_ref(
        result,
        old="#/$defs/scope",
        new="#/$defs/scope_level_0",
    )
    return result


def _replace_schema_ref(value: Any, *, old: str, new: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref" and child == old:
                value[key] = new
            else:
                _replace_schema_ref(child, old=old, new=new)
    elif isinstance(value, list):
        for child in value:
            _replace_schema_ref(child, old=old, new=new)


def _entity_schemas() -> list[dict[str, Any]]:
    base = {"id": _id_schema(), "kind": _text_schema(), "label": _text_schema()}
    variants: list[tuple[str, Mapping[str, Any], Sequence[str]]] = [
        (
            "symbol",
            {
                "role": {
                    "type": "string",
                    "enum": [
                        "function_variable",
                        "quadratic_coefficient",
                        "primary_parameter",
                        "dynamic_parameter",
                        "parameter",
                        "constant",
                    ],
                }
            },
            ("role",),
        ),
        ("point", {"role": _text_schema()}, ()),
        ("quadratic_function", {}, ()),
        (
            "named_line",
            {
                "points": {
                    **_array_schema(
                        _id_schema(),
                        min_items=2,
                        max_items=PROBLEM_DOMAIN_MAX_VALUE_TERMS,
                    ),
                    "description": "Only for a source explicitly named as a line (直线), never for a length segment.",
                }
            },
            ("points",),
        ),
        (
            "named_ray",
            {
                "origin": {
                    **_id_schema(),
                    "description": "Origin point local id of an explicitly printed ray (射线).",
                },
                "through": {
                    **_id_schema(),
                    "description": "Second point local id defining that explicitly printed ray.",
                },
            },
            ("origin", "through"),
        ),
        (
            "polygon",
            {
                "vertices": _array_schema(
                    _id_schema(),
                    min_items=3,
                    max_items=PROBLEM_DOMAIN_MAX_VALUE_TERMS,
                )
            },
            ("vertices",),
        ),
        (
            "scalar_expression",
            {"expression": {"$ref": "#/$defs/expression"}},
            ("expression",),
        ),
    ]
    return [
        _object_schema(
            {**base, "kind": {"const": kind}, **extra},
            ("id", "kind", "label", *required),
        )
        for kind, extra, required in variants
    ]


def _fact_schemas() -> list[dict[str, Any]]:
    ref = _id_schema()
    expr = {"$ref": "#/$defs/expression"}
    segment = {"$ref": "#/$defs/segment_term"}
    angle = {"$ref": "#/$defs/angle_term"}
    scaled = {"$ref": "#/$defs/scaled_length_term"}
    length_sum = {"$ref": "#/$defs/length_sum"}
    variants: list[tuple[str, Mapping[str, Any], Sequence[str]]] = [
        ("function_expression", {"function": ref, "variable": ref, "expression": expr}, ("function", "variable", "expression")),
        ("point_construction", {"point": ref, "construction": {"const": "origin"}}, ("point", "construction")),
        ("point_construction", {"point": ref, "construction": {"const": "vertex"}, "owner": ref}, ("point", "construction", "owner")),
        ("point_construction", {"point": ref, "construction": {"const": "x_axis_intercept"}, "owner": ref, "exclude_point": ref, "side": _text_schema()}, ("point", "construction", "owner")),
        ("point_construction", {"point": ref, "construction": {"const": "y_axis_intercept"}, "owner": ref}, ("point", "construction", "owner")),
        ("point_construction", {"point": ref, "construction": {"const": "axis_x_intercept"}, "owner": ref}, ("point", "construction", "owner")),
        ("point_construction", {"point": ref, "construction": {"const": "translated_point"}, "owner": ref, "vector": _array_schema(expr, min_items=2, max_items=2)}, ("point", "construction", "owner", "vector")),
        ("point_construction", {"point": ref, "construction": {"const": "curve_at_x"}, "owner": ref, "x_expression": expr}, ("point", "construction", "owner", "x_expression")),
        (
            "equation",
            {
                "expression": expr,
                "symbols": _array_schema(
                    ref,
                    min_items=1,
                    max_items=PROBLEM_DOMAIN_MAX_VALUE_TERMS,
                ),
            },
            ("expression", "symbols"),
        ),
        (
            "symbol_constraint",
            {
                "symbol": ref,
                "operator": {
                    "type": "string",
                    "enum": ["=", "!=", ">", ">=", "<", "<="],
                    "description": "Put the comparison token in this operator field; never use '>' or '<' as a JSON property name.",
                },
                "value": expr,
            },
            ("symbol", "operator", "value"),
        ),
        ("symbol_value", {"symbol": ref, "value": expr}, ("symbol", "value")),
        ("point_coordinate", {"point": ref, "value": _array_schema(expr, min_items=2, max_items=2)}, ("point", "value")),
        ("point_on_curve", {"point": ref, "curve": ref}, ("point", "curve")),
        ("point_on_curve_with_x", {"point": ref, "curve": ref, "x_symbol": ref, "x_range": _array_schema(expr, min_items=2, max_items=2)}, ("point", "curve", "x_symbol", "x_range")),
        ("point_on_axis", {"point": ref, "axis": {"type": "string", "enum": ["x", "y", "symmetry"]}, "curve": ref}, ("point", "axis")),
        ("point_on_segment", {"point": ref, "segment": segment}, ("point", "segment")),
        ("point_on_ray", {"point": ref, "ray": {"oneOf": [ref, {"$ref": "#/$defs/ray_term"}]}}, ("point", "ray")),
        ("quadrant_membership", {"point": ref, "quadrant": _text_schema()}, ("point", "quadrant")),
        ("midpoint", {"point": ref, "segment": segment}, ("point", "segment")),
        ("right_angle", {"angle": angle}, ("angle",)),
        (
            "angle_sum",
            {
                "angles": _array_schema(
                    angle,
                    min_items=2,
                    max_items=PROBLEM_DOMAIN_MAX_VALUE_TERMS,
                ),
                "value": expr,
            },
            ("angles", "value"),
        ),
        ("equal_length", {"left": segment, "right": segment}, ("left", "right")),
        ("length_value", {"segment": segment, "value": expr, "power": {"type": "integer", "enum": [1, 2]}}, ("segment", "value", "power")),
        ("length_relation", {"left": scaled, "right": scaled}, ("left", "right")),
        (
            "square",
            {
                "polygon": ref,
                "side": segment,
                "orientation": {"$ref": "#/$defs/axis_placement"},
            },
            ("polygon", "side", "orientation"),
        ),
        ("square_center", {"point": ref, "square": ref}, ("point", "square")),
        ("minimum_target", {"expression": length_sum}, ("expression",)),
        ("minimum_value_given", {"expression": length_sum, "value": expr}, ("expression", "value")),
    ]
    return [
        _object_schema(
            {"kind": {"const": kind}, **extra},
            ("kind", *required),
        )
        for kind, extra, required in variants
    ]


def _goal_schemas() -> list[dict[str, Any]]:
    ref = _id_schema()
    length_sum = {"$ref": "#/$defs/length_sum"}
    variants: list[tuple[str, Mapping[str, Any], Sequence[str]]] = [
        ("point_coordinate", {"target": ref}, ("target",)),
        ("quadratic_equation", {"target": ref}, ("target",)),
        ("parameter_value", {"target": ref}, ("target",)),
        ("minimum_value", {"expression": length_sum}, ("expression",)),
    ]
    return [
        _object_schema(
            {
                "kind": {"const": kind},
                "answer_key": _id_schema(),
                **extra,
            },
            ("kind", "answer_key", *required),
        )
        for kind, extra, required in variants
    ]


def _parse_graph(
    payload: Mapping[str, Any],
    *,
    unit_records: Sequence[ProblemUnitRecord] = (),
) -> ProblemGraph:
    overrides = _unit_id_overrides(unit_records)
    root_payload = _mapping(payload["root"], "$.root")
    root = _parse_scope(root_payload, path=(), unit_overrides=overrides)
    source_payload = _mapping(payload["source"], "$.source")
    return ProblemGraph(
        problem_id=str(payload["problem_id"]),
        family_id=str(payload["family_id"]),
        source=ProblemSource(
            question_number=str(source_payload["question_number"]),
            score=(str(source_payload["score"]) if source_payload.get("score") is not None else None),
        ),
        root_scope=root,
    )


def _parse_scope(
    payload: Mapping[str, Any],
    *,
    path: tuple[str, ...],
    forced_unit_id: str | None = None,
    unit_overrides: Mapping[tuple[str, str, str], str] | None = None,
) -> ProblemScope:
    local_id = str(payload["id"])
    scope_path = (*path, local_id)
    path_id = "/".join(scope_path)
    overrides = unit_overrides or {}
    unit_id = forced_unit_id or overrides.get(
        ("scope", path_id, local_id), f"scope:{path_id}"
    )
    entities = tuple(
        _parse_entity(
            _mapping(item, "$.entities"),
            scope_path,
            forced_unit_id=overrides.get(
                ("entity", path_id, str(_mapping(item, "$.entities")["id"]))
            ),
        )
        for item in _mapping_sequence(payload.get("entities", ()), "$.entities")
    )
    seen_fact_signatures: set[str] = set()
    facts: list[ProblemFact] = []
    for raw in _mapping_sequence(payload.get("facts", ()), "$.facts"):
        raw_mapping = _mapping(raw, "$.facts")
        signature = stable_hash(raw_mapping)
        # Exact wire duplicates represent the same source unit and are collapsed
        # before identity allocation. Non-identical repeated definitions remain
        # separate so the domain validator can report conflicts or redundancy.
        if signature in seen_fact_signatures:
            continue
        seen_fact_signatures.add(signature)
        facts.append(
            _parse_fact(
                raw_mapping,
                scope_path,
                forced_unit_id=overrides.get(("fact", path_id, signature)),
            )
        )
    goals = tuple(
        _parse_goal(
            _mapping(item, "$.goals"),
            scope_path,
            forced_unit_id=overrides.get(
                ("goal", path_id, stable_hash(_mapping(item, "$.goals")))
            ),
        )
        for item in _mapping_sequence(payload.get("goals", ()), "$.goals")
    )
    children = tuple(
        _parse_scope(
            _mapping(item, "$.children"),
            path=scope_path,
            unit_overrides=overrides,
        )
        for item in _mapping_sequence(payload.get("children", ()), "$.children")
    )
    return ProblemScope(
        unit_id=unit_id,
        local_id=local_id,
        label=str(payload["label"]),
        source_text=tuple(str(item) for item in payload["source_text"]),
        entities=entities,
        facts=tuple(facts),
        goals=goals,
        children=children,
        path=scope_path,
    )


def _unit_id_overrides(
    records: Sequence[ProblemUnitRecord],
) -> dict[tuple[str, str, str], str]:
    result: dict[tuple[str, str, str], str] = {}
    for record in records:
        if record.unit_kind == "family":
            continue
        if record.unit_kind in {"scope", "entity"}:
            identity = record.local_id
        else:
            identity = record.semantic_signature
        if not identity:
            raise ProblemDomainError(
                "extraction.problem_revision_drift",
                "$.unit_registry",
                f"{record.unit_kind} record {record.unit_id!r} lacks identity",
            )
        key = (record.unit_kind, record.scope_path, identity)
        if key in result:
            raise ProblemDomainError(
                "extraction.problem_revision_drift",
                "$.unit_registry",
                f"duplicate unit identity for {record.unit_id!r}",
            )
        result[key] = record.unit_id
    return result


def _parse_entity(
    payload: Mapping[str, Any],
    scope_path: tuple[str, ...],
    *,
    forced_unit_id: str | None = None,
) -> ProblemEntity:
    local_id = str(payload["id"])
    path_id = "/".join(scope_path)
    return ProblemEntity(
        unit_id=forced_unit_id or f"entity:{path_id}:{local_id}",
        local_id=local_id,
        kind=str(payload["kind"]),
        label=str(payload["label"]),
        attributes={
            key: value
            for key, value in payload.items()
            if key not in {"id", "kind", "label"}
        },
    )


def _parse_fact(
    payload: Mapping[str, Any],
    scope_path: tuple[str, ...],
    *,
    forced_unit_id: str | None = None,
) -> ProblemFact:
    path_id = "/".join(scope_path)
    semantic = {key: value for key, value in payload.items() if key != "kind"}
    return ProblemFact(
        unit_id=forced_unit_id or f"fact:{path_id}:{stable_hash(payload)}",
        kind=str(payload["kind"]),
        attributes=semantic,
    )


def _parse_goal(
    payload: Mapping[str, Any],
    scope_path: tuple[str, ...],
    *,
    forced_unit_id: str | None = None,
) -> ProblemGoal:
    path_id = "/".join(scope_path)
    return ProblemGoal(
        unit_id=forced_unit_id or f"goal:{path_id}:{stable_hash(payload)}",
        kind=str(payload["kind"]),
        answer_key=str(payload["answer_key"]),
        attributes={
            key: value
            for key, value in payload.items()
            if key not in {"kind", "answer_key"}
        },
    )


def _unit_registry(graph: ProblemGraph) -> dict[str, ProblemUnitRecord]:
    result: dict[str, ProblemUnitRecord] = {
        "family": ProblemUnitRecord(
            unit_id="family",
            unit_kind="family",
            scope_path=graph.root_scope.path_id,
            semantic_signature=stable_hash({"family_id": graph.family_id}),
            local_id=graph.family_id,
        )
    }
    for scope in graph.root_scope.iter_scopes():
        records: Iterable[tuple[UnitKind, Any]] = (
            ("scope", scope),
            *(("entity", item) for item in scope.entities),
            *(("fact", item) for item in scope.facts),
            *(("goal", item) for item in scope.goals),
        )
        for unit_kind, item in records:
            if item.unit_id in result:
                raise ProblemDomainError(
                    "extraction.problem_unit_duplicate",
                    "$.root",
                    f"duplicate unit id {item.unit_id!r}",
                )
            if unit_kind == "scope":
                signature = stable_hash(
                    {
                        "id": scope.local_id,
                        "label": scope.label,
                        "source_text": list(scope.source_text),
                        "child_ids": [child.local_id for child in scope.children],
                    }
                )
                local_id = scope.local_id
            else:
                signature = item.semantic_signature
                local_id = getattr(item, "local_id", None)
            result[item.unit_id] = ProblemUnitRecord(
                unit_id=item.unit_id,
                unit_kind=unit_kind,
                scope_path=scope.path_id,
                semantic_signature=signature,
                local_id=local_id,
            )
    return result


def _replace_graph_unit(
    graph: ProblemGraph,
    unit_id: str,
    value: Mapping[str, Any],
) -> ProblemGraph:
    record = _unit_registry(graph)[unit_id]
    if record.unit_kind == "family":
        family_id = value.get("family_id")
        if not isinstance(family_id, str) or set(value) != {"family_id"}:
            raise ProblemDomainError(
                "extraction.problem_repair_kind_drift",
                "$.replacements",
                "family replacement must contain only family_id",
            )
        return replace(graph, family_id=family_id)
    _validate_repair_unit_value(value, record.unit_kind, "$.replacements.value")
    if record.unit_kind == "scope":
        local_id = str(value["id"])
        if local_id != record.local_id:
            raise ProblemDomainError(
                "extraction.problem_repair_scope_drift", "$.replacements", "scope id cannot change"
            )
        existing = graph.scope_by_path[record.scope_path]
        replacement = replace(
            existing,
            label=str(value["label"]),
            source_text=tuple(str(item) for item in value["source_text"]),
        )
        return replace(
            graph,
            root_scope=_map_scope(graph.root_scope, unit_id, replacement),
        )
    scope = graph.scope_by_path[record.scope_path]
    if record.unit_kind == "entity":
        parsed: Any = _parse_entity(value, scope.path, forced_unit_id=unit_id)
    elif record.unit_kind == "fact":
        parsed = _parse_fact(value, scope.path, forced_unit_id=unit_id)
    else:
        parsed = _parse_goal(value, scope.path, forced_unit_id=unit_id)
    if record.unit_kind != _unit_kind_of(parsed):
        raise ProblemDomainError(
            "extraction.problem_repair_kind_drift", "$.replacements", "unit kind cannot change"
        )
    return replace(graph, root_scope=_replace_in_scope(graph.root_scope, unit_id, parsed))


def _remove_graph_unit(graph: ProblemGraph, unit_id: str) -> ProblemGraph:
    record = _unit_registry(graph)[unit_id]
    if record.unit_kind in {"family", "scope"}:
        raise ProblemDomainError(
            "extraction.problem_repair_kind_drift",
            "$.removals",
            "family and scope removal must use an authorized scope addition/restructure",
        )
    return replace(graph, root_scope=_remove_from_scope(graph.root_scope, unit_id))


def _add_graph_unit(
    graph: ProblemGraph,
    addition: ProblemAddition,
    *,
    unit_id: str,
) -> ProblemGraph:
    scope = graph.scope_by_path.get(addition.scope_path)
    if scope is None:
        raise ProblemDomainError(
            "extraction.problem_repair_scope_unresolved",
            "$.additions.scope_path",
            f"unknown scope {addition.scope_path!r}",
        )
    value = thaw_json(addition.value)
    _validate_repair_unit_value(
        value,
        addition.collection,
        "$.additions.value",
        addition=True,
    )
    if addition.collection == "scope":
        parsed: Any = _parse_scope(value, path=scope.path, forced_unit_id=unit_id)
    elif addition.collection == "entity":
        parsed = _parse_entity(value, scope.path, forced_unit_id=unit_id)
    elif addition.collection == "fact":
        parsed = _parse_fact(value, scope.path, forced_unit_id=unit_id)
    else:
        parsed = _parse_goal(value, scope.path, forced_unit_id=unit_id)
    return replace(
        graph,
        root_scope=_append_to_scope(graph.root_scope, addition.scope_path, addition.collection, parsed),
    )


def _map_scope(scope: ProblemScope, unit_id: str, replacement_scope: ProblemScope) -> ProblemScope:
    if scope.unit_id == unit_id:
        return replacement_scope
    return replace(
        scope,
        children=tuple(_map_scope(child, unit_id, replacement_scope) for child in scope.children),
    )


def _replace_in_scope(scope: ProblemScope, unit_id: str, replacement_unit: Any) -> ProblemScope:
    def mapped(items: Sequence[Any]) -> tuple[Any, ...]:
        return tuple(replacement_unit if item.unit_id == unit_id else item for item in items)

    return replace(
        scope,
        entities=mapped(scope.entities),
        facts=mapped(scope.facts),
        goals=mapped(scope.goals),
        children=tuple(_replace_in_scope(child, unit_id, replacement_unit) for child in scope.children),
    )


def _remove_from_scope(scope: ProblemScope, unit_id: str) -> ProblemScope:
    return replace(
        scope,
        entities=tuple(item for item in scope.entities if item.unit_id != unit_id),
        facts=tuple(item for item in scope.facts if item.unit_id != unit_id),
        goals=tuple(item for item in scope.goals if item.unit_id != unit_id),
        children=tuple(_remove_from_scope(child, unit_id) for child in scope.children),
    )


def _append_to_scope(
    scope: ProblemScope,
    scope_path: str,
    collection: RepairCollection,
    value: Any,
) -> ProblemScope:
    if scope.path_id == scope_path:
        if collection == "scope":
            return replace(scope, children=(*scope.children, value))
        if collection == "entity":
            return replace(scope, entities=(*scope.entities, value))
        if collection == "fact":
            return replace(scope, facts=(*scope.facts, value))
        return replace(scope, goals=(*scope.goals, value))
    return replace(
        scope,
        children=tuple(
            _append_to_scope(child, scope_path, collection, value)
            for child in scope.children
        ),
    )


def _scope_addition_authorized(draft: ProblemDraft, scope_path: str) -> bool:
    if f"scope:{scope_path}" in draft.repairable_unit_ids:
        return True
    return any(
        draft.unit_registry.get(unit_id, ProblemUnitRecord("", "scope", "", "")).scope_path
        == scope_path
        for unit_id in draft.repairable_unit_ids
    )


@lru_cache(maxsize=8)
def _repair_unit_validator(
    unit_kind: str,
    *,
    addition: bool,
) -> Draft202012Validator:
    if unit_kind not in {"scope", "entity", "fact", "goal"}:
        raise ValueError(f"unsupported repair unit kind {unit_kind!r}")
    schema = problem_repair_schema()
    definition = (
        "scope_replacement"
        if unit_kind == "scope" and not addition
        else unit_kind
    )
    return Draft202012Validator(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$ref": f"#/$defs/{definition}",
            "$defs": schema["$defs"],
        }
    )


def _validate_repair_unit_value(
    value: Mapping[str, Any],
    unit_kind: str,
    path: str,
    *,
    addition: bool = False,
) -> None:
    errors = tuple(
        sorted(
            _repair_unit_validator(unit_kind, addition=addition).iter_errors(value),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
    )
    if errors:
        first = errors[0]
        suffix = "".join(f"[{part!r}]" for part in first.absolute_path)
        raise ProblemDomainError(
            "extraction.problem_repair_kind_drift",
            path + suffix,
            f"replacement must remain a {unit_kind}: {first.message}",
        )


def _unit_kind_of(value: Any) -> UnitKind:
    if isinstance(value, ProblemEntity):
        return "entity"
    if isinstance(value, ProblemFact):
        return "fact"
    if isinstance(value, ProblemGoal):
        return "goal"
    if isinstance(value, ProblemScope):
        return "scope"
    raise TypeError(type(value))


def _validate_stamps(draft: ProblemDraft) -> None:
    for unit_id, stamp in draft.verification_stamps.items():
        record = draft.unit_registry.get(unit_id)
        if record is None or record.semantic_signature != stamp.semantic_signature:
            raise ProblemDomainError(
                "extraction.problem_verification_drift",
                "$.verification_stamps",
                f"verification stamp drifted for {unit_id!r}",
            )


def _load_json_object(
    payload: Mapping[str, Any] | str,
    error_code: str,
) -> Mapping[str, Any]:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ProblemDomainError(error_code, "$", str(exc)) from exc
    else:
        parsed = payload
    if not isinstance(parsed, Mapping):
        raise ProblemDomainError(error_code, "$", "payload must be a JSON object")
    return parsed


def _validate_schema(
    payload: Mapping[str, Any],
    validator: Draft202012Validator,
    code: str,
) -> None:
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if not errors:
        return
    first = _specific_union_error(errors[0])
    path = "$" + "".join(
        f"[{item}]" if isinstance(item, int) else f".{item}"
        for item in first.absolute_path
    )
    raise ProblemDomainError(code, path, first.message)


def _specific_union_error(error: Any) -> Any:
    """Prefer the matching discriminated-union branch over a generic oneOf error."""

    if error.validator != "oneOf" or not error.context:
        return error
    branches: dict[int, list[Any]] = {}
    for child in error.context:
        schema_path = tuple(child.schema_path)
        if not schema_path or not isinstance(schema_path[0], int):
            continue
        branches.setdefault(schema_path[0], []).append(child)
    viable = [
        branch
        for branch in branches.values()
        if not any(child.validator == "const" for child in branch)
    ]
    if not viable:
        return error
    priority = {
        "required": 0,
        "additionalProperties": 1,
        "type": 2,
        "enum": 3,
        "pattern": 4,
    }
    branch = min(
        viable,
        key=lambda items: (
            len(items),
            min(priority.get(item.validator, 10) for item in items),
        ),
    )
    return min(
        branch,
        key=lambda item: (
            priority.get(item.validator, 10),
            len(tuple(item.absolute_path)),
            item.message,
        ),
    )


@lru_cache(maxsize=1)
def _domain_validator() -> Draft202012Validator:
    return Draft202012Validator(problem_domain_schema())


@lru_cache(maxsize=1)
def _repair_validator() -> Draft202012Validator:
    return Draft202012Validator(problem_repair_schema())


def _object_schema(
    properties: Mapping[str, Any], required: Sequence[str]
) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": dict(properties),
    }


def _array_schema(
    items: Mapping[str, Any],
    *,
    min_items: int = 0,
    max_items: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": dict(items)}
    if min_items:
        result["minItems"] = min_items
    if max_items is not None:
        result["maxItems"] = max_items
    return result


def _text_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "minLength": 1,
        "maxLength": PROBLEM_DOMAIN_MAX_TEXT_LENGTH,
        "pattern": _EXPRESSION_PATTERN,
    }


def _id_schema() -> dict[str, Any]:
    return {
        "type": "string",
        "maxLength": 96,
        "pattern": _LOCAL_ID_PATTERN,
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _graph_semantic_equivalence_payload(graph: ProblemGraph) -> dict[str, Any]:
    """Resolve model-local ids before computing cross-revision semantics.

    ``revision_id`` continues to hash ``ProblemGraph.semantic_payload`` and is
    therefore the exact patch base. ``semantic_hash`` uses this representation so
    a consistent rename of local ids does not masquerade as a mathematical change.
    """

    structural_scope_ids: dict[str, str] = {}

    def index_scopes(scope: ProblemScope, position: tuple[int, ...]) -> None:
        structural_scope_ids[scope.path_id] = "root" + "".join(
            f"/{item}" for item in position
        )
        for index, child in enumerate(scope.children):
            index_scopes(child, (*position, index))

    index_scopes(graph.root_scope, ())
    scope_by_path = graph.scope_by_path

    def ancestor_paths(scope_path: str) -> tuple[str, ...]:
        parts = scope_path.split("/")
        return tuple("/".join(parts[:index]) for index in range(len(parts), 0, -1))

    def resolve(scope_path: str, local_id: str) -> ProblemEntity | None:
        for path in ancestor_paths(scope_path):
            for entity in scope_by_path[path].entities:
                if entity.local_id == local_id:
                    return entity
        return None

    entity_scope_by_unit = {
        entity.unit_id: scope.path_id
        for scope in graph.root_scope.iter_scopes()
        for entity in scope.entities
    }

    def resolved_entity_ref(entity: ProblemEntity) -> str:
        owner_path = entity_scope_by_unit[entity.unit_id]
        return (
            f"entity:{entity.kind}:{structural_scope_ids[owner_path]}:"
            f"{semantic_entity_label(entity)}"
        )

    def entity_ref(scope_path: str, local_id: str) -> str:
        entity = resolve(scope_path, local_id)
        if entity is None:
            return local_id
        return resolved_entity_ref(entity)

    def semantic_entity_label(entity: ProblemEntity) -> str:
        if entity.kind == "quadratic_function":
            return "quadratic_function"
        if entity.kind == "symbol":
            return _semantic_text(entity.label)
        if entity.kind == "scalar_expression":
            return "scalar_expression"
        source_names = re.findall(
            r"[A-Za-z]+(?:_[A-Za-z0-9]+)?",
            unicodedata.normalize("NFKC", entity.label),
        )
        if source_names:
            return source_names[-1]
        return _semantic_text(entity.label)

    def semantic_entity_attributes(
        scope_path: str,
        entity: ProblemEntity,
    ) -> Mapping[str, Any]:
        attributes = thaw_json(entity.attributes)
        if entity.kind == "point":
            return {}
        if entity.kind == "symbol":
            role = str(attributes.get("role", ""))
            if role in {"quadratic_coefficient", "primary_parameter", "parameter"}:
                role = "coefficient_or_parameter"
            return {"role": role}
        return canonical_value(scope_path, attributes)

    def expression(scope_path: str, value: str) -> str:
        result = str(value)
        visible: dict[str, ProblemEntity] = {}
        for path in reversed(ancestor_paths(scope_path)):
            for entity in scope_by_path[path].entities:
                visible[entity.local_id] = entity
        for local_id, entity in sorted(
            visible.items(), key=lambda pair: (-len(pair[0]), pair[0])
        ):
            result = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(local_id)}(?![A-Za-z0-9_])",
                str(entity.label),
                result,
            )
        return re.sub(r"\s+", "", result)

    def symbol_ref(scope_path: str, source_name: str) -> str | None:
        direct = resolve(scope_path, source_name)
        if direct is not None and direct.kind == "symbol":
            return resolved_entity_ref(direct)
        normalized = _semantic_text(source_name)
        for path in ancestor_paths(scope_path):
            matches = [
                entity
                for entity in scope_by_path[path].entities
                if entity.kind == "symbol"
                and _semantic_text(entity.label) == normalized
            ]
            if len(matches) == 1:
                return resolved_entity_ref(matches[0])
            if len(matches) > 1:
                return None
        return None

    reference_fields = {
        "point",
        "function",
        "variable",
        "symbol",
        "curve",
        "ray",
        "x_symbol",
        "polygon",
        "square",
        "owner",
        "exclude_point",
        "target",
        "origin",
        "through",
        "start",
        "vertex",
        "end",
    }
    reference_arrays = {"symbols", "vertices", "points"}
    expression_fields = {"expression", "value", "scale", "x_expression", "vector", "x_range"}

    def canonical_value(scope_path: str, value: Any, field_name: str = "") -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): canonical_value(scope_path, child, str(key))
                for key, child in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [canonical_value(scope_path, item, field_name) for item in value]
        if isinstance(value, str):
            if field_name in reference_fields or field_name in reference_arrays:
                return entity_ref(scope_path, value)
            if field_name in expression_fields:
                return expression(scope_path, value)
            if field_name in {"orientation", "quadrant"}:
                return _semantic_orientation(value)
        return value

    def scope_payload(scope: ProblemScope) -> dict[str, Any]:
        scope_path = scope.path_id
        coordinate_by_point = {
            entity_ref(scope_path, str(fact.attributes["point"])): tuple(
                expression(scope_path, str(item))
                for item in fact.attributes["value"]
            )
            for fact in scope.facts
            if fact.kind == "point_coordinate"
        }
        bounds_by_symbol: dict[str, dict[str, str]] = {}
        for fact in scope.facts:
            if fact.kind != "symbol_constraint":
                continue
            source_name = str(fact.attributes["symbol"])
            reference = symbol_ref(scope_path, source_name)
            operator = str(fact.attributes["operator"])
            if reference is None or operator not in {">", ">=", "<", "<="}:
                continue
            side = "lower" if operator in {">", ">="} else "upper"
            bounds_by_symbol.setdefault(reference, {})[side] = expression(
                scope_path,
                str(fact.attributes["value"]),
            )

        def fact_attributes(fact: ProblemFact) -> Mapping[str, Any]:
            attributes = thaw_json(fact.attributes)
            if (
                fact.kind == "point_construction"
                and attributes.get("construction") == "x_axis_intercept"
                and attributes.get("exclude_point") is not None
            ):
                # ``exclude_point`` already selects the other root. A model may
                # repeat the implied side, but that adds no mathematical meaning.
                attributes.pop("side", None)
            return canonical_value(scope_path, attributes)

        def fact_payload(fact: ProblemFact) -> dict[str, Any]:
            raw_attributes = thaw_json(fact.attributes)
            attributes = fact_attributes(fact)
            kind = fact.kind
            if (
                kind == "point_construction"
                and attributes.get("construction") == "curve_at_x"
                and coordinate_by_point.get(str(attributes.get("point")), (None,))[0]
                == attributes.get("x_expression")
            ):
                # A full coordinate plus curve_at_x is the same source claim as
                # that coordinate plus point_on_curve. Keep exact wire identity
                # in revision_id, but avoid semantic drift between those forms.
                kind = "point_on_curve"
                attributes = {
                    "point": attributes["point"],
                    "curve": attributes["owner"],
                }
            elif (
                kind == "point_construction"
                and attributes.get("construction") == "curve_at_x"
            ):
                x_symbol = symbol_ref(
                    scope_path,
                    str(raw_attributes.get("x_expression", "")),
                )
                bounds = bounds_by_symbol.get(str(x_symbol), {})
                if x_symbol is not None and set(bounds) == {"lower", "upper"}:
                    kind = "point_on_curve_with_x"
                    attributes = {
                        "point": attributes["point"],
                        "curve": attributes["owner"],
                        "x_symbol": x_symbol,
                        "x_range": [bounds["lower"], bounds["upper"]],
                    }
            elif (
                kind == "point_construction"
                and attributes.get("construction") == "x_axis_intercept"
                and coordinate_by_point.get(str(attributes.get("point")), (None, None))[1]
                == "0"
            ):
                kind = "point_on_curve"
                attributes = {
                    "point": attributes["point"],
                    "curve": attributes["owner"],
                }
            return {"kind": kind, "attributes": attributes}

        entities = [
            {
                "kind": entity.kind,
                "label": semantic_entity_label(entity),
                "attributes": semantic_entity_attributes(scope_path, entity),
            }
            for entity in scope.entities
        ]
        facts = [fact_payload(fact) for fact in scope.facts]
        goals = [
            {
                "kind": goal.kind,
                "attributes": canonical_value(
                    scope_path,
                    thaw_json(goal.attributes),
                ),
            }
            for goal in scope.goals
        ]
        source_text: list[str] = []
        for item in scope.source_text:
            normalized = _semantic_source_text(item)
            if scope is graph.root_scope:
                normalized = _strip_repeated_source_header(
                    normalized,
                    graph.source,
                )
            if normalized:
                source_text.append(normalized)
        return {
            # Line boundaries are OCR/layout mechanics. Exact line segmentation
            # remains in revision_id, while semantic identity preserves only the
            # ordered normalized text within this scope.
            "source_text": "".join(source_text),
            "entities": sorted(entities, key=_stable_json),
            "facts": sorted(facts, key=_stable_json),
            "goals": sorted(goals, key=_stable_json),
            "children": [scope_payload(child) for child in scope.children],
        }

    return {
        "problem_id": graph.problem_id,
        "family_id": graph.family_id,
        "source": {
            "question_number": _source_numeric_identity(graph.source.question_number),
            "score": _source_numeric_identity(graph.source.score),
        },
        "root": scope_payload(graph.root_scope),
    }


def _semantic_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).translate(
        str.maketrans(
            {
                "，": ",",
                "。": ".",
                "；": ";",
                "：": ":",
                "（": "(",
                "）": ")",
                "＋": "+",
                "－": "-",
                "−": "-",
                "＝": "=",
                "＞": ">",
                "＜": "<",
            }
        )
    )
    return re.sub(r"\s+", "", normalized.strip()).replace("^", "")


def _semantic_source_text(value: str) -> str:
    """Normalize transcription mechanics while preserving mathematical tokens."""

    normalized = _semantic_text(value).replace(r"\cdot", "")
    return re.sub(r"[,.;:()（）【】\[\]，。；：、*·]", "", normalized)


def _semantic_orientation(value: str) -> str:
    normalized = _semantic_text(value).casefold()
    if "x轴下方" in normalized or "below_x_axis" in normalized:
        return "below_x_axis"
    if "x轴上方" in normalized or "above_x_axis" in normalized:
        return "above_x_axis"
    if "第四象限" in normalized or normalized in {
        "4",
        "fourth",
        "iv",
        "quadrant4",
        "quadrant_4",
    }:
        return "quadrant_4"
    return normalized


def _source_numeric_identity(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.findall(r"\d+(?:\.\d+)?", unicodedata.normalize("NFKC", value))
    return digits[0] if digits else _semantic_text(value)


def _strip_repeated_source_header(value: str, source: ProblemSource) -> str:
    number = _source_numeric_identity(source.question_number)
    score = _source_numeric_identity(source.score)
    if number is None:
        return value
    prefixes = {number}
    if score is not None:
        prefixes.update(
            {
                f"{number}本小题{score}",
                f"{number}本小题{score}分",
                f"{number}本题{score}",
                f"{number}本题{score}分",
            }
        )
    for prefix in sorted(prefixes, key=len, reverse=True):
        if value.startswith(prefix):
            return value[len(prefix) :]
    return value


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProblemDomainError(
            "extraction.problem_domain_schema_invalid", path, "expected an object"
        )
    return value


def _mapping_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ProblemDomainError(
            "extraction.problem_domain_schema_invalid", path, "expected an array"
        )
    return tuple(_mapping(item, f"{path}[{index}]") for index, item in enumerate(value))


__all__ = [
    "PROBLEM_DOMAIN_CONTRACT",
    "PROBLEM_DRAFT_CONTRACT",
    "PROBLEM_REPAIR_CONTRACT",
    "VERIFIED_PROBLEM_CONTRACT",
    "ProblemAddition",
    "ProblemDomainError",
    "ProblemDraft",
    "ProblemEntity",
    "ProblemFact",
    "ProblemGoal",
    "ProblemGraph",
    "ProblemPromotionService",
    "ProblemRepairPatch",
    "ProblemRepairService",
    "ProblemReplacement",
    "ProblemScope",
    "ProblemSource",
    "ProblemUnitRecord",
    "ProblemValidationIssue",
    "ProblemValidationReport",
    "ProblemVerificationStamp",
    "VerifiedProblem",
    "problem_domain_response_format",
    "problem_domain_schema",
    "problem_repair_response_format",
    "problem_repair_schema",
]
