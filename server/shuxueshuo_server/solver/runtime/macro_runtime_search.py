"""Bounded, isolated candidate selection for runtime-search Macros."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.family.models import MacroSearchSpec


@dataclass(frozen=True)
class MacroExecutionCandidate:
    candidate_id: str
    roles: Mapping[str, str]
    call_count: int = 0
    symbolic_complexity: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "roles", MappingProxyType(dict(self.roles)))

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "roles": dict(sorted(self.roles.items())),
            "call_count": self.call_count,
            "symbolic_complexity": self.symbolic_complexity,
        }


@dataclass(frozen=True)
class MacroCandidateEvaluation:
    candidate_id: str
    passed: bool
    output_signature: str | None = None
    checks: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "passed": self.passed,
            "output_signature": self.output_signature,
            "checks": list(self.checks),
        }


@dataclass(frozen=True)
class MacroRoleResolution:
    role: str
    authored_ref: str | None
    chosen_ref: str
    corrected: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "authored_ref": self.authored_ref,
            "chosen_ref": self.chosen_ref,
            "corrected": self.corrected,
        }


@dataclass(frozen=True)
class MacroRuntimeSearchReport:
    schema_version: str
    macro_id: str
    candidate_builder_id: str
    validation_policy_id: str
    winner_candidate_id: str
    role_resolutions: tuple[MacroRoleResolution, ...]
    evaluations: tuple[MacroCandidateEvaluation, ...]
    search_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != "macro-runtime-search-report/v1":
            raise ValueError("unsupported Macro runtime-search report")
        for name, value in (
            ("macro_id", self.macro_id),
            ("candidate_builder_id", self.candidate_builder_id),
            ("validation_policy_id", self.validation_policy_id),
            ("winner_candidate_id", self.winner_candidate_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        candidate_ids = tuple(item.candidate_id for item in self.evaluations)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Macro evaluation candidate ids must be unique")
        winner = tuple(
            item
            for item in self.evaluations
            if item.candidate_id == self.winner_candidate_id
        )
        if len(winner) != 1 or not winner[0].passed:
            raise ValueError("Macro winner must be one successful evaluation")
        roles = tuple(item.role for item in self.role_resolutions)
        if len(roles) != len(set(roles)):
            raise ValueError("Macro role resolutions must be unique")
        payload = self._payload(include_signature=False)
        object.__setattr__(self, "search_signature", _stable_hash(payload))

    def _payload(self, *, include_signature: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "macro_id": self.macro_id,
            "candidate_builder_id": self.candidate_builder_id,
            "validation_policy_id": self.validation_policy_id,
            "winner_candidate_id": self.winner_candidate_id,
            "role_resolutions": [item.to_payload() for item in self.role_resolutions],
            "evaluations": [item.to_payload() for item in self.evaluations],
        }
        if include_signature:
            payload["search_signature"] = self.search_signature
        return payload

    def to_payload(self) -> dict[str, Any]:
        return self._payload(include_signature=True)

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "MacroRuntimeSearchReport":
        if payload.get("schema_version") != "macro-runtime-search-report/v1":
            raise ValueError("unsupported Macro runtime-search report")
        allowed = {
            "schema_version",
            "macro_id",
            "candidate_builder_id",
            "validation_policy_id",
            "winner_candidate_id",
            "role_resolutions",
            "evaluations",
            "search_signature",
        }
        unexpected = set(payload) - allowed
        if unexpected:
            raise ValueError(
                "unexpected Macro runtime-search report fields: "
                + ", ".join(sorted(unexpected))
            )
        report = cls(
            schema_version="macro-runtime-search-report/v1",
            macro_id=_required_string(payload, "macro_id"),
            candidate_builder_id=_required_string(
                payload,
                "candidate_builder_id",
            ),
            validation_policy_id=_required_string(
                payload,
                "validation_policy_id",
            ),
            winner_candidate_id=_required_string(
                payload,
                "winner_candidate_id",
            ),
            role_resolutions=tuple(
                MacroRoleResolution(
                    role=_required_string(item, "role"),
                    authored_ref=(
                        str(item["authored_ref"])
                        if item.get("authored_ref") is not None
                        else None
                    ),
                    chosen_ref=_required_string(item, "chosen_ref"),
                    corrected=_required_bool(item, "corrected"),
                )
                for item in _mapping_items(payload.get("role_resolutions"))
            ),
            evaluations=tuple(
                MacroCandidateEvaluation(
                    candidate_id=_required_string(item, "candidate_id"),
                    passed=_required_bool(item, "passed"),
                    output_signature=(
                        str(item["output_signature"])
                        if item.get("output_signature") is not None
                        else None
                    ),
                    checks=tuple(str(value) for value in item.get("checks", ())),
                )
                for item in _mapping_items(payload.get("evaluations"))
            ),
        )
        if payload.get("search_signature") != report.search_signature:
            raise ValueError("Macro runtime-search report signature drift")
        return report


def macro_runtime_search_report_schema() -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "macro-runtime-search-report.schema.json",
        "title": "MacroRuntimeSearchReport",
        "type": "object",
        "required": [
            "schema_version",
            "macro_id",
            "candidate_builder_id",
            "validation_policy_id",
            "winner_candidate_id",
            "role_resolutions",
            "evaluations",
            "search_signature",
        ],
        "properties": {
            "schema_version": {"const": "macro-runtime-search-report/v1"},
            "macro_id": nonempty,
            "candidate_builder_id": nonempty,
            "validation_policy_id": nonempty,
            "winner_candidate_id": nonempty,
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
                        "authored_ref": {
                            "anyOf": [nonempty, {"type": "null"}],
                        },
                        "chosen_ref": nonempty,
                        "corrected": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
            },
            "evaluations": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": [
                        "candidate_id",
                        "passed",
                        "output_signature",
                        "checks",
                    ],
                    "properties": {
                        "candidate_id": nonempty,
                        "passed": {"type": "boolean"},
                        "output_signature": {
                            "anyOf": [nonempty, {"type": "null"}],
                        },
                        "checks": {
                            "type": "array",
                            "items": nonempty,
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "search_signature": nonempty,
        },
        "additionalProperties": False,
    }


class MacroRuntimeSearchError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryability: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryability = retryability
        self.details = dict(details or {})


MacroCandidateEvaluator = Callable[
    [MacroExecutionCandidate],
    MacroCandidateEvaluation,
]


class MacroRuntimeSearchService:
    """Evaluate bounded candidates and select only a runtime-proven winner.

    The evaluator must execute each candidate in a disposable shadow context.
    This service only owns ordering, ambiguity and deterministic selection; it
    never commits the evaluator's result. The caller cleanly replays the winner.
    """

    def search(
        self,
        *,
        macro_id: str,
        spec: MacroSearchSpec,
        candidates: Sequence[MacroExecutionCandidate],
        authored_roles: Mapping[str, str],
        evaluator: MacroCandidateEvaluator,
    ) -> tuple[MacroExecutionCandidate, MacroRuntimeSearchReport]:
        unknown_authored_roles = set(authored_roles) - set(spec.searchable_roles)
        if unknown_authored_roles:
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                "Macro authored roles are outside its declared search contract",
                retryability="configuration",
                details={
                    "macro_id": macro_id,
                    "unknown_roles": sorted(unknown_authored_roles),
                },
            )
        if not candidates:
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                "Macro candidate builder produced no candidates",
                retryability="configuration",
                details={"macro_id": macro_id},
            )
        if len(candidates) > spec.max_candidates:
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                "Macro candidate builder exceeded its declared budget",
                retryability="configuration",
                details={
                    "macro_id": macro_id,
                    "candidate_count": len(candidates),
                    "max_candidates": spec.max_candidates,
                },
            )
        by_id = {item.candidate_id: item for item in candidates}
        if len(by_id) != len(candidates):
            raise MacroRuntimeSearchError(
                "planner.macro_contract_invalid",
                "Macro candidate ids must be unique",
                retryability="configuration",
                details={"macro_id": macro_id},
            )
        for candidate in candidates:
            missing_roles = tuple(
                role
                for role in spec.searchable_roles
                if not candidate.roles.get(role)
            )
            if missing_roles:
                raise MacroRuntimeSearchError(
                    "planner.macro_contract_invalid",
                    "Macro candidate omitted declared searchable roles",
                    retryability="configuration",
                    details={
                        "macro_id": macro_id,
                        "candidate_id": candidate.candidate_id,
                        "missing_roles": list(missing_roles),
                    },
                )
        ordered = sorted(
            candidates,
            key=lambda item: (
                0 if _matches_authored_roles(item, authored_roles) else 1,
                item.candidate_id,
            ),
        )
        evaluations: list[MacroCandidateEvaluation] = []
        valid: list[tuple[MacroExecutionCandidate, MacroCandidateEvaluation]] = []
        for candidate in ordered:
            evaluation = evaluator(candidate)
            if evaluation.candidate_id != candidate.candidate_id:
                raise MacroRuntimeSearchError(
                    "planner.macro_contract_invalid",
                    "Macro evaluator returned a mismatched candidate id",
                    retryability="configuration",
                    details={"macro_id": macro_id},
                )
            evaluations.append(evaluation)
            if evaluation.passed:
                if not evaluation.output_signature:
                    raise MacroRuntimeSearchError(
                        "planner.macro_contract_invalid",
                        "Successful Macro candidate omitted its runtime output signature",
                        retryability="configuration",
                        details={"macro_id": macro_id},
                    )
                valid.append((candidate, evaluation))
        if not valid:
            raise MacroRuntimeSearchError(
                "functional.macro_search_no_valid_candidate",
                "No Macro candidate passed runtime validation",
                retryability="planner_repairable",
                details={
                    "macro_id": macro_id,
                    "candidates": [item.to_payload() for item in evaluations],
                },
            )
        signatures = {evaluation.output_signature for _, evaluation in valid}
        if len(signatures) != 1:
            raise MacroRuntimeSearchError(
                "functional.macro_search_ambiguous",
                "Multiple non-equivalent Macro candidates passed runtime validation",
                retryability="planner_repairable",
                details={
                    "macro_id": macro_id,
                    "valid_candidates": [candidate.candidate_id for candidate, _ in valid],
                },
            )
        winner = min(
            (candidate for candidate, _ in valid),
            key=lambda item: (
                item.call_count,
                item.symbolic_complexity,
                item.candidate_id,
            ),
        )
        resolutions = tuple(
            MacroRoleResolution(
                role=role,
                authored_ref=authored_roles.get(role),
                chosen_ref=winner.roles[role],
                corrected=(
                    role in authored_roles
                    and authored_roles[role] != winner.roles[role]
                ),
            )
            for role in spec.searchable_roles
        )
        report = MacroRuntimeSearchReport(
            schema_version="macro-runtime-search-report/v1",
            macro_id=macro_id,
            candidate_builder_id=spec.candidate_builder_id,
            validation_policy_id=spec.validation_policy_id,
            winner_candidate_id=winner.candidate_id,
            role_resolutions=resolutions,
            evaluations=tuple(evaluations),
        )
        return winner, report


def runtime_verified_macro_report(
    *,
    macro_id: str,
    spec: MacroSearchSpec,
    authored_roles: Mapping[str, str],
    chosen_roles: Mapping[str, str],
    runtime_outputs: Sequence[Any],
    check_names: Sequence[str],
    call_count: int,
) -> MacroRuntimeSearchReport:
    """Authenticate one Macro path after its isolated runtime succeeded.

    Candidate-producing Macros already execute their internal alternatives in
    a disposable transaction. This adapter records the surviving public role
    assignment and output equivalence through the same bounded-search service
    used by multi-graph Macro implementations.
    """

    roles = {
        role: chosen_roles.get(role, authored_roles.get(role, ""))
        for role in spec.searchable_roles
    }
    output_signature = _stable_hash(
        {"outputs": [_canonical_runtime_value(item) for item in runtime_outputs]}
    )
    candidate = MacroExecutionCandidate(
        candidate_id=_stable_hash(
            {
                "macro_id": macro_id,
                "roles": dict(sorted(roles.items())),
                "output_signature": output_signature,
            }
        ),
        roles=roles,
        call_count=call_count,
        symbolic_complexity=_symbolic_complexity(runtime_outputs),
    )
    _, report = MacroRuntimeSearchService().search(
        macro_id=macro_id,
        spec=spec,
        candidates=(candidate,),
        authored_roles=authored_roles,
        evaluator=lambda item: MacroCandidateEvaluation(
            candidate_id=item.candidate_id,
            passed=True,
            output_signature=output_signature,
            checks=tuple(check_names),
        ),
    )
    return report


def _matches_authored_roles(
    candidate: MacroExecutionCandidate,
    authored_roles: Mapping[str, str],
) -> bool:
    return all(candidate.roles.get(role) == value for role, value in authored_roles.items())


def _stable_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_runtime_value(value: Any) -> Any:
    if isinstance(value, sp.Basic):
        return {"sympy": sp.srepr(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_runtime_value(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_runtime_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return {"type": type(value).__name__, "repr": repr(value)}


def _symbolic_complexity(values: Sequence[Any]) -> int:
    return sum(
        int(sp.count_ops(item))
        for value in values
        for item in _iter_sympy_values(value)
    )


def _iter_sympy_values(value: Any) -> tuple[sp.Basic, ...]:
    if isinstance(value, sp.Basic):
        return (value,)
    if isinstance(value, Mapping):
        return tuple(
            item
            for child in value.values()
            for item in _iter_sympy_values(child)
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            item for child in value for item in _iter_sympy_values(child)
        )
    return ()


def _mapping_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("Macro runtime-search report collection must be a list")
    result = tuple(value)
    if not all(isinstance(item, Mapping) for item in result):
        raise ValueError("Macro runtime-search report item must be an object")
    return result


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_bool(payload: Mapping[str, Any], name: str) -> bool:
    value = payload.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


__all__ = [
    "MacroCandidateEvaluation",
    "MacroExecutionCandidate",
    "MacroRoleResolution",
    "MacroRuntimeSearchError",
    "MacroRuntimeSearchReport",
    "MacroRuntimeSearchService",
    "macro_runtime_search_report_schema",
    "runtime_verified_macro_report",
]
