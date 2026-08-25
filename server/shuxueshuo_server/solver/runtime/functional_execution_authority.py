"""Verified, scope-native execution evidence for FunctionalPlan v3."""

from __future__ import annotations

from typing import Any, Mapping, TypeAlias

from shuxueshuo_server.solver.runtime.functional_subplan import (
    VerifiedSubplanExecution,
)

VERIFIED_FUNCTIONAL_PLAN_EXECUTION_CONTRACT = (
    "verified-functional-plan-execution/v2"
)


FunctionalExecutionEvidence: TypeAlias = VerifiedSubplanExecution


def functional_execution_evidence_from_payload(
    payload: Mapping[str, Any],
) -> FunctionalExecutionEvidence:
    schema_version = payload.get("schema_version")
    if schema_version == "verified-subplan-execution/v2":
        return VerifiedSubplanExecution.from_payload(payload)
    raise ValueError("unsupported Functional execution evidence contract")


def functional_execution_evidence_schema() -> dict[str, Any]:
    return verified_subplan_execution_schema(include_document_header=False)


def verified_subplan_execution_schema(
    *,
    include_document_header: bool = True,
) -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    verification = {
        "type": "object",
        "required": ["passed", "check_code", "expected", "observed", "evidence"],
        "properties": {
            "passed": {"type": "boolean"},
            "check_code": nonempty,
            "expected": {},
            "observed": {},
            "evidence": {"type": "array", "items": nonempty},
        },
        "additionalProperties": False,
    }
    evaluation = {
        "type": "object",
        "required": [
            "candidate_id",
            "passed",
            "standard_outputs",
            "verification",
            "failure_code",
            "shadow_execution_signature",
            "output_signature",
        ],
        "properties": {
            "candidate_id": nonempty,
            "passed": {"type": "boolean"},
            "standard_outputs": {"type": "object"},
            "verification": {"type": "array", "items": verification},
            "failure_code": {"type": ["string", "null"]},
            "shadow_execution_signature": {"type": ["string", "null"]},
            "output_signature": {"type": ["string", "null"]},
        },
        "additionalProperties": False,
    }
    report = {
        "type": "object",
        "required": [
            "schema_version",
            "macro_id",
            "winner_candidate_id",
            "equivalent_candidate_ids",
            "evaluations",
            "report_signature",
        ],
        "properties": {
            "schema_version": {"const": "candidate-search-report/v1"},
            "macro_id": nonempty,
            "winner_candidate_id": nonempty,
            "equivalent_candidate_ids": {
                "type": "array",
                "items": nonempty,
                "uniqueItems": True,
            },
            "evaluations": {"type": "array", "minItems": 1, "items": evaluation},
            "report_signature": nonempty,
        },
        "additionalProperties": False,
    }
    fragment = {
        "type": "object",
        "required": [
            "source",
            "scope_id",
            "steps",
            "exports",
            "dependency_envelope",
            "blueprint_id",
            "fragment_signature",
        ],
        "properties": {
            "source": {"enum": ["macro", "llm"]},
            "scope_id": nonempty,
            "steps": {"type": "array", "minItems": 1, "items": {"type": "object"}},
            "exports": {"type": "object"},
            "dependency_envelope": {
                "type": "array",
                "items": nonempty,
                "uniqueItems": True,
            },
            "blueprint_id": {"type": ["string", "null"]},
            "fragment_signature": nonempty,
        },
        "additionalProperties": False,
    }
    witness = {
        "type": "object",
        "required": [
            "schema_version",
            "standard_entities",
            "standard_conditions",
            "standard_results",
            "provenance",
            "witness_signature",
        ],
        "properties": {
            "schema_version": {"const": "verified-subplan-witness/v1"},
            "standard_entities": {"type": "object", "additionalProperties": nonempty},
            "standard_conditions": {"type": "object", "additionalProperties": nonempty},
            "standard_results": {"type": "object"},
            "provenance": {"type": "array", "items": {"type": "object"}},
            "witness_signature": nonempty,
        },
        "additionalProperties": False,
    }
    selection = {
        "oneOf": [
            {
                "type": "object",
                "required": [
                    "kind",
                    "macro_id",
                    "preparation_signature",
                    "search_report",
                ],
                "properties": {
                    "kind": {"const": "macro_search"},
                    "macro_id": nonempty,
                    "preparation_signature": nonempty,
                    "search_report": report,
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["kind", "source", "owner_ref"],
                "properties": {
                    "kind": {"const": "single_fragment"},
                    "source": {"const": "llm"},
                    "owner_ref": nonempty,
                },
                "additionalProperties": False,
            },
        ]
    }
    clean_execution = {
        "type": "object",
        "required": [
            "member_step_ids",
            "fragment_execution_signature",
            "exported_results",
            "verification",
            "provenance",
            "clean_signature",
        ],
        "properties": {
            "member_step_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty,
            },
            "fragment_execution_signature": nonempty,
            "exported_results": {"type": "object"},
            "verification": {"type": "array", "items": verification},
            "provenance": {"type": "array", "items": {"type": "object"}},
            "clean_signature": nonempty,
        },
        "additionalProperties": False,
    }
    schema: dict[str, Any] = {
        "title": "VerifiedSubplanExecution",
        "type": "object",
        "required": [
            "schema_version",
            "plan_id",
            "scope_id",
            "selected_fragment",
            "selection",
            "clean_execution",
            "witness",
            "output_signature",
            "execution_signature",
        ],
        "properties": {
            "schema_version": {"const": "verified-subplan-execution/v2"},
            "plan_id": nonempty,
            "scope_id": nonempty,
            "selected_fragment": fragment,
            "selection": selection,
            "clean_execution": clean_execution,
            "witness": witness,
            "output_signature": nonempty,
            "execution_signature": nonempty,
        },
        "additionalProperties": False,
    }
    if include_document_header:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "verified-subplan-execution.schema.json",
            **schema,
        }
    return schema



__all__ = [
    "FunctionalExecutionEvidence",
    "VERIFIED_FUNCTIONAL_PLAN_EXECUTION_CONTRACT",
    "functional_execution_evidence_from_payload",
    "functional_execution_evidence_schema",
    "verified_subplan_execution_schema",
]
