"""Wire-only candidate patches returned by the F3 multimodal extractor."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    FrozenJson,
    freeze_json,
    stable_hash,
    thaw_json,
)


CANDIDATE_PATCH_SCHEMA_VERSION = "problem-extraction-candidate-patch/v1"
_CANDIDATE_TYPES = frozenset({"scope", "entity", "fact", "goal"})
_FORBIDDEN_KEYS = frozenset(
    {
        "answer",
        "answers",
        "expected_answer",
        "expected_answers",
        "solution",
        "solution_steps",
        "capability",
        "capability_id",
        "functional_plan",
        "problem_ir",
        "polygon",
        "bbox",
        "runtime_path",
        "state_version_id",
        "math_object_id",
    }
)


@dataclass(frozen=True)
class F3ContractIssue:
    code: str
    path: str
    message: str

    def to_payload(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class F3ContractNormalization:
    code: str
    path: str
    added_review_region_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "added_review_region_refs": list(self.added_review_region_refs),
        }


@dataclass(frozen=True)
class F3ContractValidationReport:
    issues: tuple[F3ContractIssue, ...] = ()
    normalizations: tuple[F3ContractNormalization, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def normalized_review_region_count(self) -> int:
        return sum(
            len(item.added_review_region_refs) for item in self.normalizations
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [item.to_payload() for item in self.issues],
            "first_issue": self.issues[0].to_payload() if self.issues else None,
            "normalizations": [
                item.to_payload() for item in self.normalizations
            ],
            "normalized_review_region_count": (
                self.normalized_review_region_count
            ),
        }


@dataclass(frozen=True)
class CandidateClassification:
    pattern: str | None
    problem_type: str | None
    confidence: float
    evidence_refs: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "problem_type": self.problem_type,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class CandidateTranscriptionLine:
    line_id: str
    text: str
    reading_order: int
    evidence_refs: tuple[str, ...]
    review_region_refs: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "text": self.text,
            "reading_order": self.reading_order,
            "evidence_refs": list(self.evidence_refs),
            "review_region_refs": list(self.review_region_refs),
        }


@dataclass(frozen=True)
class MultimodalCandidate:
    candidate_id: str
    candidate_type: str
    confidence: float
    evidence_refs: tuple[str, ...]
    review_region_refs: tuple[str, ...]
    payload: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", freeze_json(self.payload))

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "review_region_refs": list(self.review_region_refs),
            "payload": thaw_json(self.payload),
        }


@dataclass(frozen=True)
class CandidateAmbiguity:
    ambiguity_id: str
    code: str
    candidate_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    review_region_refs: tuple[str, ...]
    message: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "ambiguity_id": self.ambiguity_id,
            "code": self.code,
            "candidate_ids": list(self.candidate_ids),
            "evidence_refs": list(self.evidence_refs),
            "review_region_refs": list(self.review_region_refs),
            "message": self.message,
        }


@dataclass(frozen=True)
class ProblemExtractionCandidatePatch:
    base_context_id: str
    evidence_pack_id: str
    classification: CandidateClassification
    transcription_lines: tuple[CandidateTranscriptionLine, ...]
    candidates: tuple[MultimodalCandidate, ...]
    ambiguities: tuple[CandidateAmbiguity, ...]
    review_region_refs: tuple[str, ...]

    @property
    def schema_version(self) -> str:
        return CANDIDATE_PATCH_SCHEMA_VERSION

    @property
    def patch_id(self) -> str:
        return f"candidate-patch:{stable_hash(self.to_payload())}"

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "base_context_id": self.base_context_id,
            "evidence_pack_id": self.evidence_pack_id,
            "classification": self.classification.to_payload(),
            "transcription_lines": [
                item.to_payload() for item in self.transcription_lines
            ],
            "candidates": [item.to_payload() for item in self.candidates],
            "ambiguities": [item.to_payload() for item in self.ambiguities],
            "review_region_refs": list(self.review_region_refs),
        }


def parse_candidate_patch(
    raw_response: str,
    evidence_pack: MultimodalEvidencePack,
) -> tuple[ProblemExtractionCandidatePatch | None, F3ContractValidationReport]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return None, _report(
            "extraction.multimodal_response_invalid_json",
            "$",
            str(exc),
        )
    if not isinstance(payload, Mapping):
        return None, _report(
            "extraction.multimodal_response_invalid",
            "$",
            "response must be a JSON object",
        )
    payload = _with_wire_defaults(payload)
    payload = _expand_prompt_references(payload, evidence_pack)
    payload, normalizations = _project_required_review_regions(
        payload,
        evidence_pack,
    )
    schema_errors = sorted(
        _candidate_patch_schema_validator().iter_errors(payload),
        key=lambda item: list(item.path),
    )
    if schema_errors:
        first = schema_errors[0]
        return None, _report(
            "extraction.multimodal_response_invalid",
            _json_path(first.path),
            first.message,
            normalizations=normalizations,
        )
    forbidden = _find_forbidden_key(payload)
    if forbidden is not None:
        return None, _report(
            "extraction.multimodal_forbidden_output",
            forbidden,
            "candidate patch contains solver, answer, typed identity, or free geometry data",
            normalizations=normalizations,
        )
    if payload["base_context_id"] != evidence_pack.base_context_id:
        return None, _report(
            "extraction.multimodal_response_identity_drift",
            "$.base_context_id",
            "response does not belong to the supplied Context",
            normalizations=normalizations,
        )
    if payload["evidence_pack_id"] != evidence_pack.evidence_pack_id:
        return None, _report(
            "extraction.multimodal_response_identity_drift",
            "$.evidence_pack_id",
            "response does not belong to the supplied evidence pack",
            normalizations=normalizations,
        )

    patch = _patch_from_payload(payload)
    issue = _validate_patch_authority(patch, evidence_pack)
    if issue is not None:
        return None, F3ContractValidationReport(
            issues=(issue,),
            normalizations=normalizations,
        )
    return patch, F3ContractValidationReport(normalizations=normalizations)


def _patch_from_payload(payload: Mapping[str, Any]) -> ProblemExtractionCandidatePatch:
    classification = payload["classification"]
    return ProblemExtractionCandidatePatch(
        base_context_id=str(payload["base_context_id"]),
        evidence_pack_id=str(payload["evidence_pack_id"]),
        classification=CandidateClassification(
            pattern=_optional_string(classification.get("pattern")),
            problem_type=_optional_string(classification.get("problem_type")),
            confidence=float(classification["confidence"]),
            evidence_refs=tuple(str(item) for item in classification["evidence_refs"]),
        ),
        transcription_lines=tuple(
            CandidateTranscriptionLine(
                line_id=str(item["line_id"]),
                text=str(item["text"]),
                reading_order=int(item["reading_order"]),
                evidence_refs=tuple(str(ref) for ref in item["evidence_refs"]),
                review_region_refs=tuple(
                    str(ref) for ref in item["review_region_refs"]
                ),
            )
            for item in payload["transcription_lines"]
        ),
        candidates=tuple(
            MultimodalCandidate(
                candidate_id=str(item["candidate_id"]),
                candidate_type=str(item["candidate_type"]),
                confidence=float(item["confidence"]),
                evidence_refs=tuple(str(ref) for ref in item["evidence_refs"]),
                review_region_refs=tuple(
                    str(ref) for ref in item["review_region_refs"]
                ),
                payload=item["payload"],
            )
            for item in payload["candidates"]
        ),
        ambiguities=tuple(
            CandidateAmbiguity(
                ambiguity_id=str(item["ambiguity_id"]),
                code=str(item["code"]),
                candidate_ids=tuple(str(ref) for ref in item["candidate_ids"]),
                evidence_refs=tuple(str(ref) for ref in item["evidence_refs"]),
                review_region_refs=tuple(
                    str(ref) for ref in item["review_region_refs"]
                ),
                message=str(item["message"]),
            )
            for item in payload["ambiguities"]
        ),
        review_region_refs=tuple(
            str(item) for item in payload["review_region_refs"]
        ),
    )


def _with_wire_defaults(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Fill mechanically empty wire fields without inventing semantic content."""

    result = dict(payload)
    candidates = result.get("candidates")
    if isinstance(candidates, list):
        normalized = []
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                normalized.append(candidate)
                continue
            item = dict(candidate)
            item.setdefault("review_region_refs", [])
            normalized.append(item)
        result["candidates"] = normalized
    transcription_lines = result.get("transcription_lines")
    if isinstance(transcription_lines, list):
        normalized_lines = []
        for line in transcription_lines:
            if not isinstance(line, Mapping):
                normalized_lines.append(line)
                continue
            item = dict(line)
            item.setdefault("review_region_refs", [])
            normalized_lines.append(item)
        result["transcription_lines"] = normalized_lines
    ambiguities = result.get("ambiguities")
    if isinstance(ambiguities, list):
        normalized_ambiguities = []
        for ambiguity in ambiguities:
            if not isinstance(ambiguity, Mapping):
                normalized_ambiguities.append(ambiguity)
                continue
            item = dict(ambiguity)
            item.setdefault("candidate_ids", [])
            normalized_ambiguities.append(item)
        result["ambiguities"] = normalized_ambiguities
    return result


def _expand_prompt_references(
    payload: Mapping[str, Any],
    evidence_pack: MultimodalEvidencePack,
) -> dict[str, Any]:
    evidence_aliases, region_aliases = evidence_pack.prompt_reference_aliases()
    evidence_refs = {alias: full for full, alias in evidence_aliases.items()}
    region_refs = {alias: full for full, alias in region_aliases.items()}

    def expand(values: Any, aliases: Mapping[str, str]) -> Any:
        if not isinstance(values, list):
            return values
        return [aliases.get(str(value), str(value)) for value in values]

    result = dict(payload)
    classification = result.get("classification")
    if isinstance(classification, Mapping):
        item = dict(classification)
        item["evidence_refs"] = expand(item.get("evidence_refs"), evidence_refs)
        result["classification"] = item
    lines = result.get("transcription_lines")
    if isinstance(lines, list):
        normalized_lines = []
        for line in lines:
            if not isinstance(line, Mapping):
                normalized_lines.append(line)
                continue
            item = dict(line)
            item["evidence_refs"] = expand(item.get("evidence_refs"), evidence_refs)
            item["review_region_refs"] = expand(
                item.get("review_region_refs"),
                region_refs,
            )
            normalized_lines.append(item)
        result["transcription_lines"] = normalized_lines
    candidates = result.get("candidates")
    if isinstance(candidates, list):
        normalized_candidates = []
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                normalized_candidates.append(candidate)
                continue
            item = dict(candidate)
            item["evidence_refs"] = expand(item.get("evidence_refs"), evidence_refs)
            item["review_region_refs"] = expand(
                item.get("review_region_refs"),
                region_refs,
            )
            normalized_candidates.append(item)
        result["candidates"] = normalized_candidates
    ambiguities = result.get("ambiguities")
    if isinstance(ambiguities, list):
        normalized_ambiguities = []
        for ambiguity in ambiguities:
            if not isinstance(ambiguity, Mapping):
                normalized_ambiguities.append(ambiguity)
                continue
            item = dict(ambiguity)
            item["evidence_refs"] = expand(item.get("evidence_refs"), evidence_refs)
            item["review_region_refs"] = expand(
                item.get("review_region_refs"),
                region_refs,
            )
            normalized_ambiguities.append(item)
        result["ambiguities"] = normalized_ambiguities
    result["review_region_refs"] = expand(
        result.get("review_region_refs"),
        region_refs,
    )
    return result


def _project_required_review_regions(
    payload: Mapping[str, Any],
    evidence_pack: MultimodalEvidencePack,
) -> tuple[dict[str, Any], tuple[F3ContractNormalization, ...]]:
    """Project the unique F2 review region for mixed/unknown evidence refs."""

    review_region_by_evidence = {
        item.evidence_id: item.region_id
        for item in evidence_pack.region_index
        if item.origin in {"mixed", "unknown"}
    }

    def required_regions(item: Mapping[str, Any]) -> list[str]:
        return [
            review_region_by_evidence[ref]
            for ref in item.get("evidence_refs", [])
            if ref in review_region_by_evidence
        ]

    normalizations: list[F3ContractNormalization] = []

    def merge(
        existing: Any,
        required: Sequence[str],
        path: str,
    ) -> list[str]:
        values = list(existing) if isinstance(existing, list) else []
        added = tuple(
            value
            for value in dict.fromkeys(required)
            if value not in values
        )
        if added:
            normalizations.append(
                F3ContractNormalization(
                    code="extraction.multimodal_review_regions_projected",
                    path=path,
                    added_review_region_refs=added,
                )
            )
        return list(dict.fromkeys([*values, *required]))

    result = dict(payload)
    classification = result.get("classification")
    if isinstance(classification, Mapping):
        result["review_region_refs"] = merge(
            result.get("review_region_refs"),
            required_regions(classification),
            "$.review_region_refs",
        )
    for field in ("transcription_lines", "candidates"):
        records = result.get(field)
        if not isinstance(records, list):
            continue
        normalized = []
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                normalized.append(record)
                continue
            item = dict(record)
            item["review_region_refs"] = merge(
                item.get("review_region_refs"),
                required_regions(item),
                f"$.{field}[{index}].review_region_refs",
            )
            normalized.append(item)
        result[field] = normalized
    return result, tuple(normalizations)


def _validate_patch_authority(
    patch: ProblemExtractionCandidatePatch,
    pack: MultimodalEvidencePack,
) -> F3ContractIssue | None:
    evidence_by_id = pack.evidence_by_id
    region_by_id = pack.region_by_id
    candidate_ids = [item.candidate_id for item in patch.candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        return F3ContractIssue(
            "extraction.multimodal_response_invalid",
            "$.candidates",
            "candidate ids must be unique",
        )
    line_ids = [item.line_id for item in patch.transcription_lines]
    if len(line_ids) != len(set(line_ids)):
        return F3ContractIssue(
            "extraction.multimodal_response_invalid",
            "$.transcription_lines",
            "transcription line ids must be unique",
        )
    ambiguity_ids = [item.ambiguity_id for item in patch.ambiguities]
    if len(ambiguity_ids) != len(set(ambiguity_ids)):
        return F3ContractIssue(
            "extraction.multimodal_response_invalid",
            "$.ambiguities",
            "ambiguity ids must be unique",
        )
    ambiguity_region_refs = {
        ref
        for ambiguity in patch.ambiguities
        for ref in ambiguity.evidence_refs + ambiguity.review_region_refs
    }
    for index, item in enumerate(patch.candidates):
        if item.candidate_type not in _CANDIDATE_TYPES or not item.candidate_id.startswith(
            f"{item.candidate_type}_"
        ):
            return F3ContractIssue(
                "extraction.multimodal_response_invalid",
                f"$.candidates[{index}].candidate_id",
                "candidate id prefix must match candidate_type",
            )
        issue = _validate_region_refs(
            item.review_region_refs,
            region_by_id,
            f"$.candidates[{index}].review_region_refs",
        )
        if issue is not None:
            return issue
        issue = _validate_candidate_evidence(
            item,
            evidence_by_id,
            f"$.candidates[{index}].evidence_refs",
            ambiguity_region_refs,
        )
        if issue is not None:
            return issue
        payload_refs = _candidate_payload_refs(item.payload)
        unknown_payload_refs = sorted(set(payload_refs) - set(candidate_ids))
        if unknown_payload_refs:
            return F3ContractIssue(
                "extraction.evidence_ref_unresolved",
                f"$.candidates[{index}].payload",
                f"payload references unknown candidates: {unknown_payload_refs}",
            )
    issue = _validate_observation_evidence(
        patch.classification.evidence_refs,
        evidence_by_id,
        "$.classification.evidence_refs",
        review_region_refs=patch.review_region_refs,
        ambiguity_region_refs=ambiguity_region_refs,
    )
    if issue is not None:
        return issue
    for index, line in enumerate(patch.transcription_lines):
        issue = _validate_region_refs(
            line.review_region_refs,
            region_by_id,
            f"$.transcription_lines[{index}].review_region_refs",
        )
        if issue is not None:
            return issue
        issue = _validate_observation_evidence(
            line.evidence_refs,
            evidence_by_id,
            f"$.transcription_lines[{index}].evidence_refs",
            review_region_refs=(
                patch.review_region_refs + line.review_region_refs
            ),
            ambiguity_region_refs=ambiguity_region_refs,
        )
        if issue is not None:
            return issue
    known_candidates = set(candidate_ids)
    for index, item in enumerate(patch.ambiguities):
        if set(item.candidate_ids) - known_candidates:
            return F3ContractIssue(
                "extraction.evidence_ref_unresolved",
                f"$.ambiguities[{index}].candidate_ids",
                "ambiguity references an unknown candidate",
            )
        issue = _validate_region_refs(
            item.evidence_refs + item.review_region_refs,
            region_by_id,
            f"$.ambiguities[{index}]",
        )
        if issue is not None:
            return issue
    return _validate_region_refs(
        patch.review_region_refs,
        region_by_id,
        "$.review_region_refs",
    )


def _validate_observation_evidence(
    refs: Sequence[str],
    evidence_by_id: Mapping[str, Any],
    path: str,
    *,
    review_region_refs: Sequence[str] = (),
    ambiguity_region_refs: Sequence[str] = (),
) -> F3ContractIssue | None:
    missing = set(refs) - set(evidence_by_id)
    if missing:
        return F3ContractIssue(
            "extraction.evidence_ref_unresolved",
            path,
            f"unknown evidence refs: {sorted(missing)}",
        )
    handwritten = sorted(
        ref for ref in refs if evidence_by_id[ref].origin == "handwritten"
    )
    if handwritten:
        return F3ContractIssue(
            "extraction.multimodal_evidence_origin_forbidden",
            path,
            f"handwritten observations cannot assert problem facts: {handwritten}",
        )
    review_required = {
        ref
        for ref in refs
        if evidence_by_id[ref].origin in {"mixed", "unknown"}
    }
    if review_required and not review_required.issubset(set(review_region_refs)):
        return F3ContractIssue(
            "extraction.multimodal_evidence_origin_forbidden",
            path,
            "mixed/unknown evidence must also be listed as review regions",
        )
    if review_required and not review_required.issubset(
        set(ambiguity_region_refs)
    ):
        return F3ContractIssue(
            "extraction.multimodal_evidence_origin_forbidden",
            path,
            "mixed/unknown evidence must be covered by an ambiguity",
        )
    return None


def _validate_candidate_evidence(
    candidate: MultimodalCandidate,
    evidence_by_id: Mapping[str, Any],
    path: str,
    ambiguity_region_refs: Sequence[str],
) -> F3ContractIssue | None:
    return _validate_observation_evidence(
        candidate.evidence_refs,
        evidence_by_id,
        path,
        review_region_refs=candidate.review_region_refs,
        ambiguity_region_refs=ambiguity_region_refs,
    )


def _validate_region_refs(
    refs: Sequence[str],
    region_by_id: Mapping[str, Any],
    path: str,
) -> F3ContractIssue | None:
    missing = set(refs) - set(region_by_id)
    if missing:
        return F3ContractIssue(
            "extraction.evidence_ref_unresolved",
            path,
            f"unknown region refs: {sorted(missing)}",
        )
    return None


def _find_forbidden_key(value: Any, path: str = "$") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            next_path = f"{path}.{key}"
            if normalized in _FORBIDDEN_KEYS:
                return next_path
            nested = _find_forbidden_key(item, next_path)
            if nested is not None:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            nested = _find_forbidden_key(item, f"{path}[{index}]")
            if nested is not None:
                return nested
    return None


def _candidate_payload_refs(value: Any) -> tuple[str, ...]:
    refs: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized.endswith("_candidate_id") and isinstance(item, str):
                refs.append(item)
            elif normalized.endswith("_candidate_ids") and isinstance(item, Sequence):
                refs.extend(str(ref) for ref in item if isinstance(ref, str))
            refs.extend(_candidate_payload_refs(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            refs.extend(_candidate_payload_refs(item))
    return tuple(refs)


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _report(
    code: str,
    path: str,
    message: str,
    *,
    normalizations: tuple[F3ContractNormalization, ...] = (),
) -> F3ContractValidationReport:
    return F3ContractValidationReport(
        issues=(F3ContractIssue(code, path, message),),
        normalizations=normalizations,
    )


@lru_cache(maxsize=1)
def _candidate_patch_schema_validator() -> Draft202012Validator:
    path = _repo_root() / "internal/schemas/problem-extraction-candidate-patch.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _json_path(parts: Sequence[object]) -> str:
    return "$" + "".join(f"[{part!r}]" for part in parts)
