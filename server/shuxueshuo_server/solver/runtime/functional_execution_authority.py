"""Verified, scope-native execution evidence for FunctionalPlan v2."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Sequence, TypeAlias

from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.macro_runtime_search import (
    MacroRoleResolution,
    MacroRuntimeSearchReport,
    macro_runtime_search_report_schema,
)

if TYPE_CHECKING:
    from shuxueshuo_server.solver.extraction.problem_planning_context import (
        ProblemPlanningContext,
    )


PATH_MINIMUM_WITNESS_CONTRACT = "path-minimum-witness/v1"
PATH_MINIMUM_PROMPT_WITNESS_CONTRACT = "path-minimum-prompt-witness/v1"
MACRO_SEARCH_EXECUTION_EVIDENCE_CONTRACT = (
    "macro-search-execution-evidence/v1"
)
VERIFIED_FUNCTIONAL_PLAN_EXECUTION_CONTRACT = (
    "verified-functional-plan-execution/v1"
)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(child)
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            }
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ValueError(
        "Functional execution evidence must contain JSON-compatible values"
    )


def thaw_json(value: Any) -> Any:
    """Return a mutable, JSON-safe copy of recursively frozen evidence."""

    if isinstance(value, Mapping):
        return {str(key): thaw_json(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw_json(item) for item in value]
    return value


def _nonempty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be an array")
    result = tuple(value)
    if not all(isinstance(item, Mapping) for item in result):
        raise ValueError(f"{field_name} items must be objects")
    return result


@dataclass(frozen=True)
class PathMinimumWitness:
    """Authenticated geometric proof and minimizer evidence for a path Macro."""

    step_id: str
    macro_id: str
    original_objective: str
    reduced_objective: str
    role_resolutions: tuple[MacroRoleResolution, ...]
    constructions: tuple[Mapping[str, Any], ...]
    equivalence_proof: tuple[str, ...]
    legal_domain: tuple[str, ...]
    minimum_strategy: str
    minimum_expression: str
    minimizing_points: Mapping[str, Any]
    attainment_checks: tuple[Mapping[str, Any], ...]
    macro_search_report: MacroRuntimeSearchReport
    provenance_signature: str
    schema_version: str = PATH_MINIMUM_WITNESS_CONTRACT
    witness_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != PATH_MINIMUM_WITNESS_CONTRACT:
            raise ValueError("unsupported PathMinimumWitness contract")
        for name in (
            "step_id",
            "macro_id",
            "original_objective",
            "reduced_objective",
            "minimum_strategy",
            "minimum_expression",
            "provenance_signature",
        ):
            _nonempty(getattr(self, name), name)
        if self.macro_search_report.macro_id != self.macro_id:
            raise ValueError("Path witness and Macro search report identify different Macros")
        if tuple(self.role_resolutions) != tuple(
            self.macro_search_report.role_resolutions
        ):
            raise ValueError("Path witness role resolutions drifted from search authority")
        roles = tuple(item.role for item in self.role_resolutions)
        if len(roles) != len(set(roles)):
            raise ValueError("Path witness role resolutions must be unique")
        if not self.equivalence_proof:
            raise ValueError("Path witness requires an equivalence proof")
        if not self.legal_domain:
            raise ValueError("Path witness requires a legal domain")
        if not self.attainment_checks:
            raise ValueError("Path witness requires attainment checks")
        object.__setattr__(
            self,
            "constructions",
            tuple(_freeze_json(item) for item in self.constructions),
        )
        object.__setattr__(
            self,
            "minimizing_points",
            _freeze_json(self.minimizing_points),
        )
        object.__setattr__(
            self,
            "attainment_checks",
            tuple(_freeze_json(item) for item in self.attainment_checks),
        )
        object.__setattr__(self, "equivalence_proof", tuple(self.equivalence_proof))
        object.__setattr__(self, "legal_domain", tuple(self.legal_domain))
        object.__setattr__(
            self,
            "witness_id",
            stable_hash(self._payload(include_witness_id=False)),
        )

    def _payload(self, *, include_witness_id: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "macro_id": self.macro_id,
            "original_objective": self.original_objective,
            "reduced_objective": self.reduced_objective,
            "role_resolutions": [
                item.to_payload() for item in self.role_resolutions
            ],
            "constructions": [thaw_json(item) for item in self.constructions],
            "equivalence_proof": list(self.equivalence_proof),
            "legal_domain": list(self.legal_domain),
            "minimum_strategy": self.minimum_strategy,
            "minimum_expression": self.minimum_expression,
            "minimizing_points": thaw_json(self.minimizing_points),
            "attainment_checks": [
                thaw_json(item) for item in self.attainment_checks
            ],
            "macro_search_report": self.macro_search_report.to_payload(),
            "provenance_signature": self.provenance_signature,
        }
        if include_witness_id:
            payload["witness_id"] = self.witness_id
        return payload

    def authority_payload(self) -> dict[str, Any]:
        return self._payload(include_witness_id=True)

    def to_payload(self) -> dict[str, Any]:
        return self.authority_payload()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "PathMinimumWitness":
        expected = {
            "schema_version",
            "step_id",
            "macro_id",
            "original_objective",
            "reduced_objective",
            "role_resolutions",
            "constructions",
            "equivalence_proof",
            "legal_domain",
            "minimum_strategy",
            "minimum_expression",
            "minimizing_points",
            "attainment_checks",
            "macro_search_report",
            "provenance_signature",
            "witness_id",
        }
        if set(payload) != expected:
            raise ValueError("PathMinimumWitness payload fields do not match contract")
        report_payload = payload.get("macro_search_report")
        if not isinstance(report_payload, Mapping):
            raise ValueError("macro_search_report must be an object")
        role_payloads = _mapping_sequence(
            payload.get("role_resolutions"), "role_resolutions"
        )
        witness = cls(
            schema_version=_nonempty(payload.get("schema_version"), "schema_version"),
            step_id=_nonempty(payload.get("step_id"), "step_id"),
            macro_id=_nonempty(payload.get("macro_id"), "macro_id"),
            original_objective=_nonempty(
                payload.get("original_objective"), "original_objective"
            ),
            reduced_objective=_nonempty(
                payload.get("reduced_objective"), "reduced_objective"
            ),
            role_resolutions=tuple(
                MacroRoleResolution(
                    role=_nonempty(item.get("role"), "role"),
                    authored_ref=(
                        str(item["authored_ref"])
                        if item.get("authored_ref") is not None
                        else None
                    ),
                    chosen_ref=_nonempty(item.get("chosen_ref"), "chosen_ref"),
                    corrected=bool(item.get("corrected")),
                )
                for item in role_payloads
            ),
            constructions=_mapping_sequence(
                payload.get("constructions"), "constructions"
            ),
            equivalence_proof=tuple(
                _nonempty(item, "equivalence_proof item")
                for item in _sequence(payload.get("equivalence_proof"), "equivalence_proof")
            ),
            legal_domain=tuple(
                _nonempty(item, "legal_domain item")
                for item in _sequence(payload.get("legal_domain"), "legal_domain")
            ),
            minimum_strategy=_nonempty(
                payload.get("minimum_strategy"), "minimum_strategy"
            ),
            minimum_expression=_nonempty(
                payload.get("minimum_expression"), "minimum_expression"
            ),
            minimizing_points=_required_mapping(
                payload.get("minimizing_points"), "minimizing_points"
            ),
            attainment_checks=_mapping_sequence(
                payload.get("attainment_checks"), "attainment_checks"
            ),
            macro_search_report=MacroRuntimeSearchReport.from_payload(report_payload),
            provenance_signature=_nonempty(
                payload.get("provenance_signature"), "provenance_signature"
            ),
        )
        if payload.get("witness_id") != witness.witness_id:
            raise ValueError("PathMinimumWitness content hash drift")
        return witness


@dataclass(frozen=True)
class PathMinimumPromptWitness:
    """Prompt-safe projection of one authenticated path-minimum witness."""

    step_id: str
    macro_id: str
    original_objective: str
    reduced_objective: str
    role_resolutions: tuple[Mapping[str, Any], ...]
    constructions: tuple[Mapping[str, Any], ...]
    equivalence_proof: tuple[str, ...]
    legal_domain: tuple[str, ...]
    minimum_strategy: str
    minimum_expression: str
    minimizing_points: Mapping[str, Any]
    attainment_checks: tuple[Mapping[str, Any], ...]
    repair_action: str
    schema_version: str = PATH_MINIMUM_PROMPT_WITNESS_CONTRACT

    def __post_init__(self) -> None:
        if self.schema_version != PATH_MINIMUM_PROMPT_WITNESS_CONTRACT:
            raise ValueError("unsupported PathMinimumPromptWitness contract")
        for name in (
            "step_id",
            "macro_id",
            "original_objective",
            "reduced_objective",
            "minimum_strategy",
            "minimum_expression",
            "repair_action",
        ):
            _nonempty(getattr(self, name), name)
        object.__setattr__(
            self,
            "role_resolutions",
            tuple(_freeze_json(item) for item in self.role_resolutions),
        )
        object.__setattr__(
            self,
            "constructions",
            tuple(_freeze_json(item) for item in self.constructions),
        )
        object.__setattr__(
            self,
            "minimizing_points",
            _freeze_json(self.minimizing_points),
        )
        object.__setattr__(
            self,
            "attainment_checks",
            tuple(_freeze_json(item) for item in self.attainment_checks),
        )
        object.__setattr__(self, "equivalence_proof", tuple(self.equivalence_proof))
        object.__setattr__(self, "legal_domain", tuple(self.legal_domain))

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "macro_id": self.macro_id,
            "original_objective": self.original_objective,
            "reduced_objective": self.reduced_objective,
            "role_resolutions": [
                thaw_json(item) for item in self.role_resolutions
            ],
            "constructions": [thaw_json(item) for item in self.constructions],
            "equivalence_proof": list(self.equivalence_proof),
            "legal_domain": list(self.legal_domain),
            "minimum_strategy": self.minimum_strategy,
            "minimum_expression": self.minimum_expression,
            "minimizing_points": thaw_json(self.minimizing_points),
            "attainment_checks": [
                thaw_json(item) for item in self.attainment_checks
            ],
            "repair_action": self.repair_action,
        }


class PathMinimumPromptWitnessProjector:
    """Translate internal path authority into the sole retry-safe wire."""

    def project(
        self,
        witness: PathMinimumWitness,
        planning_context: "ProblemPlanningContext",
    ) -> PathMinimumPromptWitness:
        prompt_ref_by_runtime_id = {
            authority.runtime_node_id: authority.semantic_ref.ref
            for authority in planning_context.ref_authorities.values()
            if authority.usage == "input"
        }
        prompt_refs = frozenset(prompt_ref_by_runtime_id.values())

        def prompt_ref(value: str | None, *, required: bool) -> str | None:
            if value is None:
                return None
            projected = prompt_ref_by_runtime_id.get(value, value)
            if projected in prompt_refs:
                return projected
            if required or ":" in projected:
                raise ValueError(
                    "Path witness role cannot be projected to a prompt-visible ref"
                )
            return projected

        role_resolutions = tuple(
            {
                "role": item.role,
                "authored_ref": prompt_ref(item.authored_ref, required=False),
                "chosen_ref": prompt_ref(item.chosen_ref, required=True),
                "corrected": item.corrected,
            }
            for item in witness.role_resolutions
        )
        attainment_checks = tuple(
            {
                "strategy": str(item.get("strategy", "")),
                "feasible": bool(item.get("feasible")),
                **(
                    {"expression": str(item["expression"])}
                    if item.get("expression") is not None
                    else {}
                ),
                "checks": [
                    {
                        "check": str(check.get("check", "")),
                        "passed": bool(check.get("passed")),
                        **(
                            {"parameter": str(check["parameter"])}
                            if check.get("parameter") is not None
                            else {}
                        ),
                    }
                    for check in item.get("checks", ())
                    if isinstance(check, Mapping)
                ],
            }
            for item in witness.attainment_checks
        )
        result = PathMinimumPromptWitness(
            step_id=witness.step_id,
            macro_id=witness.macro_id,
            original_objective=witness.original_objective,
            reduced_objective=witness.reduced_objective,
            role_resolutions=role_resolutions,
            constructions=tuple(
                thaw_json(item) for item in witness.constructions
            ),
            equivalence_proof=witness.equivalence_proof,
            legal_domain=witness.legal_domain,
            minimum_strategy=witness.minimum_strategy,
            minimum_expression=witness.minimum_expression,
            minimizing_points=thaw_json(witness.minimizing_points),
            attainment_checks=attainment_checks,
            repair_action="reuse_verified_path_witness",
        )
        _audit_prompt_witness(result.to_payload(), planning_context)
        return result


@dataclass(frozen=True)
class MacroSearchExecutionEvidence:
    """Generic execution evidence shared by every runtime-search Macro."""

    step_id: str
    report: MacroRuntimeSearchReport
    schema_version: str = MACRO_SEARCH_EXECUTION_EVIDENCE_CONTRACT
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MACRO_SEARCH_EXECUTION_EVIDENCE_CONTRACT:
            raise ValueError("unsupported Macro search execution evidence")
        _nonempty(self.step_id, "step_id")
        object.__setattr__(
            self,
            "evidence_id",
            stable_hash(self._payload(include_evidence_id=False)),
        )

    def _payload(self, *, include_evidence_id: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "step_id": self.step_id,
            "report": self.report.to_payload(),
        }
        if include_evidence_id:
            payload["evidence_id"] = self.evidence_id
        return payload

    def authority_payload(self) -> dict[str, Any]:
        return self._payload(include_evidence_id=True)

    def to_payload(self) -> dict[str, Any]:
        return self.authority_payload()

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> "MacroSearchExecutionEvidence":
        if set(payload) != {
            "schema_version",
            "step_id",
            "report",
            "evidence_id",
        }:
            raise ValueError("Macro search evidence payload fields do not match contract")
        report = _required_mapping(payload.get("report"), "report")
        evidence = cls(
            schema_version=_nonempty(payload.get("schema_version"), "schema_version"),
            step_id=_nonempty(payload.get("step_id"), "step_id"),
            report=MacroRuntimeSearchReport.from_payload(report),
        )
        if payload.get("evidence_id") != evidence.evidence_id:
            raise ValueError("Macro search execution evidence hash drift")
        return evidence


FunctionalExecutionEvidence: TypeAlias = (
    PathMinimumWitness | MacroSearchExecutionEvidence
)


def functional_execution_evidence_from_payload(
    payload: Mapping[str, Any],
) -> FunctionalExecutionEvidence:
    schema_version = payload.get("schema_version")
    if schema_version == PATH_MINIMUM_WITNESS_CONTRACT:
        return PathMinimumWitness.from_payload(payload)
    if schema_version == MACRO_SEARCH_EXECUTION_EVIDENCE_CONTRACT:
        return MacroSearchExecutionEvidence.from_payload(payload)
    raise ValueError("unsupported Functional execution evidence contract")


def functional_execution_evidence_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            path_minimum_witness_schema(include_document_header=False),
            macro_search_execution_evidence_schema(include_document_header=False),
        ]
    }


def path_minimum_witness_schema(
    *, include_document_header: bool = True
) -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    report = _embedded_report_schema()
    schema: dict[str, Any] = {
        "title": "PathMinimumWitness",
        "type": "object",
        "required": [
            "schema_version",
            "step_id",
            "macro_id",
            "original_objective",
            "reduced_objective",
            "role_resolutions",
            "constructions",
            "equivalence_proof",
            "legal_domain",
            "minimum_strategy",
            "minimum_expression",
            "minimizing_points",
            "attainment_checks",
            "macro_search_report",
            "provenance_signature",
            "witness_id",
        ],
        "properties": {
            "schema_version": {"const": PATH_MINIMUM_WITNESS_CONTRACT},
            "step_id": nonempty,
            "macro_id": nonempty,
            "original_objective": nonempty,
            "reduced_objective": nonempty,
            "role_resolutions": report["properties"]["role_resolutions"],
            "constructions": {
                "type": "array",
                "items": {"type": "object"},
            },
            "equivalence_proof": {
                "type": "array",
                "minItems": 1,
                "items": nonempty,
            },
            "legal_domain": {
                "type": "array",
                "minItems": 1,
                "items": nonempty,
            },
            "minimum_strategy": nonempty,
            "minimum_expression": nonempty,
            "minimizing_points": {"type": "object"},
            "attainment_checks": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "object"},
            },
            "macro_search_report": report,
            "provenance_signature": nonempty,
            "witness_id": nonempty,
        },
        "additionalProperties": False,
    }
    if include_document_header:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "path-minimum-witness.schema.json",
            **schema,
        }
    return schema


def path_minimum_prompt_witness_schema() -> dict[str, Any]:
    """Return the embedded retry-safe witness schema."""

    nonempty = {"type": "string", "minLength": 1}
    nullable_nonempty = {"anyOf": [nonempty, {"type": "null"}]}
    return {
        "title": "PathMinimumPromptWitness",
        "type": "object",
        "required": [
            "schema_version",
            "step_id",
            "macro_id",
            "original_objective",
            "reduced_objective",
            "role_resolutions",
            "constructions",
            "equivalence_proof",
            "legal_domain",
            "minimum_strategy",
            "minimum_expression",
            "minimizing_points",
            "attainment_checks",
            "repair_action",
        ],
        "properties": {
            "schema_version": {"const": PATH_MINIMUM_PROMPT_WITNESS_CONTRACT},
            "step_id": nonempty,
            "macro_id": nonempty,
            "original_objective": nonempty,
            "reduced_objective": nonempty,
            "role_resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "role",
                        "authored_ref",
                        "chosen_ref",
                        "corrected",
                    ],
                    "properties": {
                        "role": nonempty,
                        "authored_ref": nullable_nonempty,
                        "chosen_ref": nonempty,
                        "corrected": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "constructions": {"type": "array", "items": {"type": "object"}},
            "equivalence_proof": {
                "type": "array",
                "minItems": 1,
                "items": nonempty,
            },
            "legal_domain": {
                "type": "array",
                "minItems": 1,
                "items": nonempty,
            },
            "minimum_strategy": nonempty,
            "minimum_expression": nonempty,
            "minimizing_points": {"type": "object"},
            "attainment_checks": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["strategy", "feasible", "checks"],
                    "properties": {
                        "strategy": nonempty,
                        "feasible": {"type": "boolean"},
                        "expression": nonempty,
                        "checks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["check", "passed"],
                                "properties": {
                                    "check": nonempty,
                                    "passed": {"type": "boolean"},
                                    "parameter": nonempty,
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "repair_action": nonempty,
        },
        "additionalProperties": False,
    }


def macro_search_execution_evidence_schema(
    *, include_document_header: bool = True
) -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    schema: dict[str, Any] = {
        "title": "MacroSearchExecutionEvidence",
        "type": "object",
        "required": ["schema_version", "step_id", "report", "evidence_id"],
        "properties": {
            "schema_version": {
                "const": MACRO_SEARCH_EXECUTION_EVIDENCE_CONTRACT
            },
            "step_id": nonempty,
            "report": _embedded_report_schema(),
            "evidence_id": nonempty,
        },
        "additionalProperties": False,
    }
    if include_document_header:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "macro-search-execution-evidence.schema.json",
            **schema,
        }
    return schema


def _embedded_report_schema() -> dict[str, Any]:
    report = dict(macro_runtime_search_report_schema())
    for key in ("$schema", "$id", "title"):
        report.pop(key, None)
    return report


def _required_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _audit_prompt_witness(
    payload: Mapping[str, Any],
    planning_context: "ProblemPlanningContext",
) -> None:
    forbidden = {
        planning_context.planning_context_id,
        planning_context.problem_revision_id,
        planning_context.problem_semantic_hash,
        planning_context.bundle_authority_token.bundle_id,
        *(
            authority.runtime_node_id
            for authority in planning_context.ref_authorities.values()
        ),
        *(
            source_id
            for authority in planning_context.ref_authorities.values()
            for source_id in authority.source_unit_ids
        ),
    }

    def strings(value: Any) -> Sequence[str]:
        if isinstance(value, Mapping):
            return tuple(
                item for child in value.values() for item in strings(child)
            )
        if isinstance(value, (tuple, list)):
            return tuple(item for child in value for item in strings(child))
        return (value,) if isinstance(value, str) else ()

    leaked = tuple(sorted(forbidden & set(strings(payload))))
    if leaked:
        raise ValueError("Path minimum prompt witness leaked internal authority")


def _sequence(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be an array")
    return tuple(value)


def canonical_json(value: Any) -> str:
    """Expose stable JSON encoding for evidence/debug tests."""

    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "FunctionalExecutionEvidence",
    "MACRO_SEARCH_EXECUTION_EVIDENCE_CONTRACT",
    "MacroSearchExecutionEvidence",
    "PATH_MINIMUM_PROMPT_WITNESS_CONTRACT",
    "PATH_MINIMUM_WITNESS_CONTRACT",
    "PathMinimumPromptWitness",
    "PathMinimumPromptWitnessProjector",
    "PathMinimumWitness",
    "VERIFIED_FUNCTIONAL_PLAN_EXECUTION_CONTRACT",
    "canonical_json",
    "functional_execution_evidence_from_payload",
    "functional_execution_evidence_schema",
    "macro_search_execution_evidence_schema",
    "path_minimum_prompt_witness_schema",
    "path_minimum_witness_schema",
    "thaw_json",
]
