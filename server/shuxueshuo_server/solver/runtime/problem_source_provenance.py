"""Problem-source authority consumed by one canonical Functional call."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence


PROBLEM_CALL_SOURCE_PROVENANCE_CONTRACT = (
    "problem-call-source-provenance/v1"
)


class ProblemSourceProvenanceError(RuntimeError):
    """A runtime write no longer matches its F5-C Problem authority."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class ProblemCallSourceProvenance:
    """Immutable direct Problem-source reads for one Functional call."""

    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    canonical_call_id: str
    goal_unit_ids: tuple[str, ...]
    input_source_unit_ids: tuple[str, ...]
    call_binding_signature: str
    macro_search_signature: str | None = None
    macro_role_resolutions: tuple[
        tuple[str, str | None, str], ...
    ] = ()

    def __post_init__(self) -> None:
        for name, value in (
            ("planning_context_id", self.planning_context_id),
            ("problem_revision_id", self.problem_revision_id),
            ("problem_semantic_hash", self.problem_semantic_hash),
            ("canonical_call_id", self.canonical_call_id),
            ("call_binding_signature", self.call_binding_signature),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        goals = _canonical_ids(self.goal_unit_ids, name="goal_unit_ids")
        sources = _canonical_ids(
            self.input_source_unit_ids,
            name="input_source_unit_ids",
            allow_empty=True,
        )
        object.__setattr__(self, "goal_unit_ids", goals)
        object.__setattr__(self, "input_source_unit_ids", sources)
        if self.macro_search_signature is not None and not (
            isinstance(self.macro_search_signature, str)
            and self.macro_search_signature
        ):
            raise ValueError("macro_search_signature must be non-empty")
        object.__setattr__(
            self,
            "macro_role_resolutions",
            tuple(sorted(self.macro_role_resolutions)),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROBLEM_CALL_SOURCE_PROVENANCE_CONTRACT,
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "canonical_call_id": self.canonical_call_id,
            "goal_unit_ids": list(self.goal_unit_ids),
            "input_source_unit_ids": list(self.input_source_unit_ids),
            "call_binding_signature": self.call_binding_signature,
            "macro_search_signature": self.macro_search_signature,
            "macro_role_resolutions": [
                {
                    "role": role,
                    "authored_ref": authored_ref,
                    "chosen_ref": chosen_ref,
                }
                for role, authored_ref, chosen_ref in self.macro_role_resolutions
            ],
        }

    def to_payload(self) -> dict[str, Any]:
        return self.authority_payload()

    def semantic_signature(self) -> str:
        payload = self.authority_payload()
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def with_macro_search(
        self,
        *,
        search_signature: str,
        role_resolutions: Sequence[tuple[str, str | None, str]],
        additional_source_unit_ids: Sequence[str] = (),
    ) -> "ProblemCallSourceProvenance":
        binding_signature = _macro_binding_signature(
            self.call_binding_signature,
            search_signature,
        )
        return ProblemCallSourceProvenance(
            planning_context_id=self.planning_context_id,
            problem_revision_id=self.problem_revision_id,
            problem_semantic_hash=self.problem_semantic_hash,
            canonical_call_id=self.canonical_call_id,
            goal_unit_ids=self.goal_unit_ids,
            input_source_unit_ids=tuple(
                sorted(
                    {
                        *self.input_source_unit_ids,
                        *additional_source_unit_ids,
                    }
                )
            ),
            call_binding_signature=binding_signature,
            macro_search_signature=search_signature,
            macro_role_resolutions=tuple(role_resolutions),
        )

    def extends_base_authority(
        self,
        base: "ProblemCallSourceProvenance",
    ) -> bool:
        """Return whether this is the same F5-C authority plus runtime proof."""

        return (
            self.planning_context_id == base.planning_context_id
            and self.problem_revision_id == base.problem_revision_id
            and self.problem_semantic_hash == base.problem_semantic_hash
            and self.canonical_call_id == base.canonical_call_id
            and self.goal_unit_ids == base.goal_unit_ids
            and set(base.input_source_unit_ids).issubset(
                self.input_source_unit_ids
            )
            and (
                (
                    self.call_binding_signature
                    == base.call_binding_signature
                    and self.macro_search_signature is None
                )
                or self.macro_search_signature is not None
                and self.call_binding_signature
                == _macro_binding_signature(
                    base.call_binding_signature,
                    self.macro_search_signature,
                )
            )
        )

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> "ProblemCallSourceProvenance":
        if payload.get("schema_version") != (
            PROBLEM_CALL_SOURCE_PROVENANCE_CONTRACT
        ):
            raise ValueError("unsupported Problem call-source provenance contract")
        allowed = {
            "schema_version",
            "planning_context_id",
            "problem_revision_id",
            "problem_semantic_hash",
            "canonical_call_id",
            "goal_unit_ids",
            "input_source_unit_ids",
            "call_binding_signature",
            "macro_search_signature",
            "macro_role_resolutions",
        }
        unexpected = set(payload) - allowed
        if unexpected:
            raise ValueError(
                "unexpected Problem call-source provenance fields: "
                f"{', '.join(sorted(unexpected))}"
            )
        return cls(
            planning_context_id=_required_string(
                payload,
                "planning_context_id",
            ),
            problem_revision_id=_required_string(
                payload,
                "problem_revision_id",
            ),
            problem_semantic_hash=_required_string(
                payload,
                "problem_semantic_hash",
            ),
            canonical_call_id=_required_string(
                payload,
                "canonical_call_id",
            ),
            goal_unit_ids=_string_items(payload, "goal_unit_ids"),
            input_source_unit_ids=_string_items(
                payload,
                "input_source_unit_ids",
            ),
            call_binding_signature=_required_string(
                payload,
                "call_binding_signature",
            ),
            macro_search_signature=(
                str(payload["macro_search_signature"])
                if payload.get("macro_search_signature") is not None
                else None
            ),
            macro_role_resolutions=tuple(
                (
                    _required_string(item, "role"),
                    (
                        str(item["authored_ref"])
                        if item.get("authored_ref") is not None
                        else None
                    ),
                    _required_string(item, "chosen_ref"),
                )
                for item in _mapping_items(
                    payload.get("macro_role_resolutions", ())
                )
            ),
        )


def problem_call_source_provenance_schema() -> dict[str, Any]:
    nonempty = {"type": "string", "minLength": 1}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "problem-call-source-provenance.schema.json",
        "title": "ProblemCallSourceProvenance",
        "type": "object",
        "required": [
            "schema_version",
            "planning_context_id",
            "problem_revision_id",
            "problem_semantic_hash",
            "canonical_call_id",
            "goal_unit_ids",
            "input_source_unit_ids",
            "call_binding_signature",
            "macro_search_signature",
            "macro_role_resolutions",
        ],
        "properties": {
            "schema_version": {
                "const": PROBLEM_CALL_SOURCE_PROVENANCE_CONTRACT,
            },
            "planning_context_id": nonempty,
            "problem_revision_id": nonempty,
            "problem_semantic_hash": nonempty,
            "canonical_call_id": nonempty,
            "goal_unit_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty,
            },
            "input_source_unit_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": nonempty,
            },
            "call_binding_signature": nonempty,
            "macro_search_signature": {
                "anyOf": [nonempty, {"type": "null"}],
            },
            "macro_role_resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["role", "authored_ref", "chosen_ref"],
                    "properties": {
                        "role": nonempty,
                        "authored_ref": {
                            "anyOf": [nonempty, {"type": "null"}],
                        },
                        "chosen_ref": nonempty,
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


def _canonical_ids(
    values: tuple[str, ...],
    *,
    name: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if any(not isinstance(item, str) or not item for item in values):
        raise ValueError(f"{name} must contain non-empty strings")
    result = tuple(sorted(values))
    if len(result) != len(set(result)):
        raise ValueError(f"{name} must not contain duplicates")
    if not allow_empty and not result:
        raise ValueError(f"{name} must not be empty")
    return result


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _macro_binding_signature(base: str, search_signature: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "base": base,
                "macro_search_signature": search_signature,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _string_items(payload: Mapping[str, Any], name: str) -> tuple[str, ...]:
    value = payload.get(name)
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must contain non-empty strings")
    return tuple(value)


def _mapping_items(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of objects")
    result = tuple(value)
    if not all(isinstance(item, Mapping) for item in result):
        raise ValueError("expected a list of objects")
    return result


__all__ = [
    "PROBLEM_CALL_SOURCE_PROVENANCE_CONTRACT",
    "ProblemCallSourceProvenance",
    "ProblemSourceProvenanceError",
    "problem_call_source_provenance_schema",
]
