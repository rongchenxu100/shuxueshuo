"""Bind F5-B source authority to typed Functional runtime identity."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.extraction.problem_planning_context import (
    PlanningReadAuthority,
    ProblemPlanningContext,
    ScopedSourceRefKey,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainIndex,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityToken,
    VerifiedSolverProblemBundle,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.functional_plan_models import (
    CallResultRef,
    FunctionalCallReconciliation,
    FunctionalPlan,
    PublishedGoalCallResultRef,
)
from shuxueshuo_server.solver.runtime.functional_binding_context import (
    FunctionalArgBinding,
    FunctionalArgSourceIdentity,
    FunctionalBindingContext,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    PlannerStateContext,
    StateSlot,
)
from shuxueshuo_server.solver.runtime.runtime_type_compatibility import (
    runtime_type_compatible,
)
from shuxueshuo_server.solver.runtime.problem_source_provenance import (
    ProblemCallSourceProvenance,
)
from shuxueshuo_server.solver.runtime.semantic_reads import (
    SemanticReadCatalogItem,
)
from shuxueshuo_server.solver.runtime.state_identity import (
    MathObjectId,
    StateVersionId,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef


ProblemTypedSourceKind = Literal[
    "math_object",
    "state_version",
    "condition",
    "answer_target",
]

PROBLEM_PLANNING_BINDING_CATALOG_CONTRACT = (
    "problem-planning-binding-catalog/v1"
)
FUNCTIONAL_PROBLEM_BINDING_CONTEXT_CONTRACT = (
    "functional-problem-binding-context/v1"
)


def _problem_binding_schema_defs() -> dict[str, Any]:
    nonempty_string = {"type": "string", "minLength": 1}
    math_object_id = {
        "type": "object",
        "required": ["value", "kind", "origin_scope_id"],
        "properties": {
            "value": nonempty_string,
            "kind": nonempty_string,
            "origin_scope_id": nonempty_string,
        },
        "additionalProperties": False,
    }
    logical_state_key = {
        "type": "object",
        "required": ["object_id", "state_kind", "runtime_type"],
        "properties": {
            "object_id": {"$ref": "#/$defs/math_object_id"},
            "state_kind": nonempty_string,
            "runtime_type": nonempty_string,
        },
        "additionalProperties": False,
    }
    state_slot_id = {
        "type": "object",
        "required": ["logical_key", "storage_scope_id"],
        "properties": {
            "logical_key": {"$ref": "#/$defs/logical_state_key"},
            "storage_scope_id": nonempty_string,
        },
        "additionalProperties": False,
    }
    state_version_id = {
        "type": "object",
        "required": ["slot_id", "ordinal"],
        "properties": {
            "slot_id": {"$ref": "#/$defs/state_slot_id"},
            "ordinal": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    }
    semantic_ref = {
        "type": "object",
        "required": ["ref", "kind"],
        "properties": {
            "ref": nonempty_string,
            "kind": nonempty_string,
            "value_type": nonempty_string,
        },
        "additionalProperties": False,
    }
    problem_typed_source = {
        "oneOf": [
            {
                "type": "object",
                "required": ["kind", "math_object_id"],
                "properties": {
                    "kind": {"const": kind},
                    "runtime_type": nonempty_string,
                    "math_object_id": {"$ref": "#/$defs/math_object_id"},
                },
                "additionalProperties": False,
            }
            for kind in ("math_object", "answer_target")
        ]
        + [
            {
                "type": "object",
                "required": ["kind", "state_version_id", "state_slot_id"],
                "properties": {
                    "kind": {"const": "state_version"},
                    "runtime_type": nonempty_string,
                    "math_object_id": {"$ref": "#/$defs/math_object_id"},
                    "state_version_id": {
                        "$ref": "#/$defs/state_version_id"
                    },
                    "state_slot_id": nonempty_string,
                },
                "additionalProperties": False,
            },
            {
                "type": "object",
                "required": ["kind", "condition_id"],
                "properties": {
                    "kind": {"const": "condition"},
                    "runtime_type": nonempty_string,
                    "condition_id": nonempty_string,
                },
                "additionalProperties": False,
            },
        ]
    }
    functional_source = {
        "oneOf": [
            {
                "type": "object",
                "required": ["kind", field],
                "properties": {
                    "kind": {"const": kind},
                    field: schema,
                },
                "additionalProperties": False,
            }
            for kind, field, schema in (
                (
                    "state_version",
                    "state_version_id",
                    {"$ref": "#/$defs/state_version_id"},
                ),
                ("condition", "condition_id", nonempty_string),
                (
                    "math_object",
                    "math_object_id",
                    {"$ref": "#/$defs/math_object_id"},
                ),
                (
                    "compiler_selector",
                    "compiler_selector_id",
                    nonempty_string,
                ),
            )
        ]
        + [
            {
                "type": "object",
                "required": [
                    "kind",
                    "source_call_id",
                    "source_return_name",
                ],
                "properties": {
                    "kind": {"const": "call_result"},
                    "source_call_id": nonempty_string,
                    "source_return_name": nonempty_string,
                },
                "additionalProperties": False,
            }
        ]
    }
    return {
        "math_object_id": math_object_id,
        "logical_state_key": logical_state_key,
        "state_slot_id": state_slot_id,
        "state_version_id": state_version_id,
        "semantic_ref": semantic_ref,
        "problem_typed_source": problem_typed_source,
        "functional_source": functional_source,
        "scoped_source_ref_key": {
            "type": "object",
            "required": ["owner_scope_id", "local_ref", "kind"],
            "properties": {
                "owner_scope_id": nonempty_string,
                "local_ref": nonempty_string,
                "kind": nonempty_string,
            },
            "additionalProperties": False,
        },
    }


def problem_planning_binding_catalog_schema() -> dict[str, Any]:
    """Return the strict internal F5-C source-binding authority wire."""

    nonempty_string = {"type": "string", "minLength": 1}
    binding = {
        "type": "object",
        "required": [
            "semantic_ref",
            "runtime_node_id",
            "source_unit_ids",
            "owner_scope_id",
            "visible_goal_unit_ids",
            "usage",
            "typed_sources",
        ],
        "properties": {
            "semantic_ref": {"$ref": "#/$defs/semantic_ref"},
            "runtime_node_id": nonempty_string,
            "source_unit_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty_string,
            },
            "owner_scope_id": nonempty_string,
            "visible_goal_unit_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty_string,
            },
            "usage": {"enum": ["input", "answer"]},
            "typed_sources": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/problem_typed_source"},
            },
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "problem-planning-binding-catalog.schema.json",
        "title": "ProblemPlanningBindingCatalog authority payload",
        "type": "object",
        "required": [
            "schema_version",
            "planning_context_id",
            "bundle_authority_token",
            "planner_state_context_id",
            "problem_id",
            "family_id",
            "bindings",
            "goal_input_refs",
            "goal_answer_refs",
            "goal_visible_scope_ids",
            "scope_parent_ids",
            "binding_signature",
        ],
        "properties": {
            "schema_version": {
                "const": PROBLEM_PLANNING_BINDING_CATALOG_CONTRACT
            },
            "planning_context_id": nonempty_string,
            "bundle_authority_token": {
                "type": "object",
                "required": [
                    "extraction_context_id",
                    "dependency_hash",
                    "problem_revision_id",
                    "problem_semantic_hash",
                    "bundle_id",
                ],
                "properties": {
                    key: nonempty_string
                    for key in (
                        "extraction_context_id",
                        "dependency_hash",
                        "problem_revision_id",
                        "problem_semantic_hash",
                        "bundle_id",
                    )
                },
                "additionalProperties": False,
            },
            "planner_state_context_id": nonempty_string,
            "problem_id": nonempty_string,
            "family_id": nonempty_string,
            "bindings": {
                "type": "array",
                "minItems": 1,
                "items": binding,
            },
            "goal_input_refs": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/scoped_source_ref_key"},
                },
            },
            "goal_answer_refs": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "$ref": "#/$defs/scoped_source_ref_key"
                },
            },
            "goal_visible_scope_ids": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": nonempty_string,
                },
            },
            "scope_parent_ids": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "anyOf": [nonempty_string, {"type": "null"}],
                },
            },
            "binding_signature": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
        },
        "$defs": {**_problem_binding_schema_defs(), "binding": binding},
        "additionalProperties": False,
    }


def functional_problem_binding_context_schema() -> dict[str, Any]:
    """Return the strict reconciliation sidecar wire consumed by F5-D."""

    nonempty_string = {"type": "string", "minLength": 1}
    nullable_semantic_ref = {
        "anyOf": [{"$ref": "#/$defs/semantic_ref"}, {"type": "null"}]
    }
    nullable_functional_source = {
        "anyOf": [{"$ref": "#/$defs/functional_source"}, {"type": "null"}]
    }
    input_binding = {
        "type": "object",
        "required": [
            "call_id",
            "arg_name",
            "item_index",
            "source_kind",
            "selection_policy",
            "semantic_ref",
            "runtime_node_id",
            "source_unit_ids",
            "typed_source",
        ],
        "properties": {
            "call_id": nonempty_string,
            "arg_name": nonempty_string,
            "item_index": {"type": "integer", "minimum": 0},
            "source_kind": {
                "enum": [
                    "problem_source",
                    "call_result",
                    "compiler_selector",
                ]
            },
            "selection_policy": {
                "enum": ["exact", "latest", "identity_only", "compiler"]
            },
            "semantic_ref": nullable_semantic_ref,
            "runtime_node_id": {
                "anyOf": [nonempty_string, {"type": "null"}]
            },
            "source_unit_ids": {
                "type": "array",
                "uniqueItems": True,
                "items": nonempty_string,
            },
            "typed_source": nullable_functional_source,
        },
        "additionalProperties": False,
    }
    return_binding = {
        "type": "object",
        "required": [
            "call_id",
            "return_name",
            "semantic_ref",
            "runtime_node_id",
            "source_unit_ids",
            "goal_unit_id",
            "math_object_id",
        ],
        "properties": {
            "call_id": nonempty_string,
            "return_name": nonempty_string,
            "semantic_ref": {"$ref": "#/$defs/semantic_ref"},
            "runtime_node_id": nonempty_string,
            "source_unit_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty_string,
            },
            "goal_unit_id": {
                "anyOf": [nonempty_string, {"type": "null"}]
            },
            "math_object_id": {"$ref": "#/$defs/math_object_id"},
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "functional-problem-binding-context.schema.json",
        "title": "FunctionalProblemBindingContext sidecar",
        "type": "object",
        "required": [
            "schema_version",
            "planning_context_id",
            "problem_revision_id",
            "problem_semantic_hash",
            "planner_state_context_id",
            "call_goal_bindings",
            "input_bindings",
            "return_bindings",
            "binding_signature",
        ],
        "properties": {
            "schema_version": {
                "const": FUNCTIONAL_PROBLEM_BINDING_CONTEXT_CONTRACT
            },
            "planning_context_id": nonempty_string,
            "problem_revision_id": nonempty_string,
            "problem_semantic_hash": nonempty_string,
            "planner_state_context_id": nonempty_string,
            "call_goal_bindings": {
                "type": "object",
                "minProperties": 1,
                "additionalProperties": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": nonempty_string,
                },
            },
            "input_bindings": {
                "type": "array",
                "items": input_binding,
            },
            "return_bindings": {
                "type": "array",
                "items": return_binding,
            },
            "binding_signature": {
                "type": "string",
                "pattern": "^[0-9a-f]{64}$",
            },
        },
        "$defs": {
            **_problem_binding_schema_defs(),
            "input_binding": input_binding,
            "return_binding": return_binding,
        },
        "additionalProperties": False,
    }


class ProblemPlanningBindingError(ValueError):
    """A problem authority cannot be bound without guessing."""

    def __init__(
        self,
        code: str,
        path: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        self.retryable = retryable
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class ProblemTypedSourceIdentity:
    kind: ProblemTypedSourceKind
    runtime_type: str | None = None
    math_object_id: MathObjectId | None = None
    state_version_id: StateVersionId | None = None
    condition_id: str | None = None
    state_slot_id: str | None = None

    def __post_init__(self) -> None:
        populated = {
            "math_object": self.math_object_id is not None,
            "state_version": self.state_version_id is not None,
            "condition": self.condition_id is not None,
            "answer_target": self.math_object_id is not None,
        }
        if not populated[self.kind]:
            raise TypeError(f"typed problem source {self.kind!r} is incomplete")
        if self.kind == "state_version" and self.state_slot_id is None:
            raise TypeError("state-version problem source has no state slot")

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind}
        if self.runtime_type is not None:
            payload["runtime_type"] = self.runtime_type
        if self.math_object_id is not None:
            payload["math_object_id"] = self.math_object_id.to_payload()
        if self.state_version_id is not None:
            payload["state_version_id"] = self.state_version_id.to_payload()
        if self.condition_id is not None:
            payload["condition_id"] = self.condition_id
        if self.state_slot_id is not None:
            payload["state_slot_id"] = self.state_slot_id
        return payload


@dataclass(frozen=True)
class ProblemPlanningSourceBinding:
    semantic_ref: SemanticRef
    runtime_node_id: str
    source_unit_ids: tuple[str, ...]
    owner_scope_id: str
    visible_goal_unit_ids: tuple[str, ...]
    usage: str
    typed_sources: tuple[ProblemTypedSourceIdentity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "source_unit_ids", tuple(sorted(set(self.source_unit_ids)))
        )
        object.__setattr__(
            self,
            "visible_goal_unit_ids",
            tuple(sorted(set(self.visible_goal_unit_ids))),
        )
        object.__setattr__(self, "typed_sources", tuple(self.typed_sources))

    def authority_payload(self) -> dict[str, Any]:
        return {
            "semantic_ref": self.semantic_ref.to_payload(),
            "runtime_node_id": self.runtime_node_id,
            "source_unit_ids": list(self.source_unit_ids),
            "owner_scope_id": self.owner_scope_id,
            "visible_goal_unit_ids": list(self.visible_goal_unit_ids),
            "usage": self.usage,
            "typed_sources": [item.to_payload() for item in self.typed_sources],
        }

    @property
    def scoped_key(self) -> ScopedSourceRefKey:
        return ScopedSourceRefKey(
            self.owner_scope_id,
            self.semantic_ref.ref,
            self.semantic_ref.kind,
        )


@dataclass(frozen=True)
class ProblemPlanBindingIssue:
    code: str
    message: str
    call_id: str | None = None
    scope_id: str | None = None
    details: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ProblemCallGoalBinding:
    call_id: str
    goal_unit_ids: tuple[str, ...]
    effective_goal_unit_ids: tuple[str, ...]
    allowed_ref_keys: tuple[ScopedSourceRefKey, ...]

    @property
    def goal_reachable(self) -> bool:
        return bool(self.goal_unit_ids)


@dataclass(frozen=True)
class ProblemPlanGoalBindings:
    calls: Mapping[str, ProblemCallGoalBinding]
    issues: tuple[ProblemPlanBindingIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "calls", MappingProxyType(dict(sorted(self.calls.items())))
        )
        object.__setattr__(self, "issues", tuple(self.issues))

    def allowed_ref_keys_by_call(
        self,
    ) -> Mapping[str, frozenset[ScopedSourceRefKey]]:
        return MappingProxyType(
            {
                call_id: frozenset(item.allowed_ref_keys)
                for call_id, item in self.calls.items()
            }
        )


@dataclass(frozen=True)
class FunctionalProblemInputBinding:
    call_id: str
    arg_name: str
    item_index: int
    source_kind: str
    selection_policy: str
    semantic_ref: SemanticRef | None = None
    runtime_node_id: str | None = None
    source_unit_ids: tuple[str, ...] = ()
    typed_source: FunctionalArgSourceIdentity | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "arg_name": self.arg_name,
            "item_index": self.item_index,
            "source_kind": self.source_kind,
            "selection_policy": self.selection_policy,
            "semantic_ref": (
                self.semantic_ref.to_payload()
                if self.semantic_ref is not None
                else None
            ),
            "runtime_node_id": self.runtime_node_id,
            "source_unit_ids": list(self.source_unit_ids),
            "typed_source": (
                self.typed_source.to_payload()
                if self.typed_source is not None
                else None
            ),
        }


@dataclass(frozen=True)
class FunctionalProblemReturnBinding:
    call_id: str
    return_name: str
    semantic_ref: SemanticRef
    runtime_node_id: str
    source_unit_ids: tuple[str, ...]
    goal_unit_id: str | None
    math_object_id: MathObjectId

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "return_name": self.return_name,
            "semantic_ref": self.semantic_ref.to_payload(),
            "runtime_node_id": self.runtime_node_id,
            "source_unit_ids": list(self.source_unit_ids),
            "goal_unit_id": self.goal_unit_id,
            "math_object_id": self.math_object_id.to_payload(),
        }


@dataclass(frozen=True)
class FunctionalProblemBindingContext:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    planner_state_context_id: str
    call_goal_bindings: Mapping[str, tuple[str, ...]]
    input_bindings: tuple[FunctionalProblemInputBinding, ...]
    return_bindings: tuple[FunctionalProblemReturnBinding, ...]
    binding_signature: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "call_goal_bindings",
            MappingProxyType(dict(sorted(self.call_goal_bindings.items()))),
        )

    def inputs_for_call(
        self,
        call_id: str,
    ) -> tuple[FunctionalProblemInputBinding, ...]:
        return tuple(
            item for item in self.input_bindings if item.call_id == call_id
        )

    def input_binding_for(
        self,
        call_id: str,
        arg_name: str,
        item_index: int,
    ) -> FunctionalProblemInputBinding | None:
        return next(
            (
                item
                for item in self.input_bindings
                if item.call_id == call_id
                and item.arg_name == arg_name
                and item.item_index == item_index
            ),
            None,
        )

    def returns_for_call(
        self,
        call_id: str,
    ) -> tuple[FunctionalProblemReturnBinding, ...]:
        return tuple(
            item for item in self.return_bindings if item.call_id == call_id
        )

    def call_binding_signature(self, call_id: str) -> str:
        goal_ids = self.call_goal_bindings.get(call_id)
        if not goal_ids:
            raise _error(
                "functional.call_goal_unresolved",
                f"$.calls[{call_id!r}]",
                "call has no Goal authority",
            )
        return stable_hash(
            {
                "planning_context_id": self.planning_context_id,
                "problem_revision_id": self.problem_revision_id,
                "problem_semantic_hash": self.problem_semantic_hash,
                "call_id": call_id,
                "goal_unit_ids": list(goal_ids),
                "inputs": [
                    item.to_payload()
                    for item in self.inputs_for_call(call_id)
                ],
                "returns": [
                    item.to_payload()
                    for item in self.returns_for_call(call_id)
                ],
            }
        )

    def source_provenance_for_call(
        self,
        call_id: str,
    ) -> ProblemCallSourceProvenance:
        goal_ids = self.call_goal_bindings.get(call_id)
        if not goal_ids:
            raise _error(
                "functional.call_goal_unresolved",
                f"$.calls[{call_id!r}]",
                "call has no Goal authority",
            )
        source_unit_ids = {
            source_unit_id
            for item in self.inputs_for_call(call_id)
            if item.source_kind == "problem_source"
            for source_unit_id in item.source_unit_ids
        }
        return ProblemCallSourceProvenance(
            planning_context_id=self.planning_context_id,
            problem_revision_id=self.problem_revision_id,
            problem_semantic_hash=self.problem_semantic_hash,
            canonical_call_id=call_id,
            goal_unit_ids=tuple(goal_ids),
            input_source_unit_ids=tuple(sorted(source_unit_ids)),
            call_binding_signature=self.call_binding_signature(call_id),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": FUNCTIONAL_PROBLEM_BINDING_CONTEXT_CONTRACT,
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "planner_state_context_id": self.planner_state_context_id,
            "call_goal_bindings": {
                call_id: list(goal_ids)
                for call_id, goal_ids in self.call_goal_bindings.items()
            },
            "input_bindings": [
                item.to_payload() for item in self.input_bindings
            ],
            "return_bindings": [
                item.to_payload() for item in self.return_bindings
            ],
            "binding_signature": self.binding_signature,
        }


@dataclass(frozen=True)
class ProblemPlanningBindingCatalog:
    planning_context_id: str
    bundle_authority_token: ProblemBundleAuthorityToken
    planner_state_context_id: str
    problem_id: str
    family_id: str
    bindings: Mapping[ScopedSourceRefKey, ProblemPlanningSourceBinding]
    goal_input_refs: Mapping[str, tuple[ScopedSourceRefKey, ...]]
    goal_answer_refs: Mapping[str, ScopedSourceRefKey]
    goal_visible_scope_ids: Mapping[str, tuple[str, ...]]
    scope_parent_ids: Mapping[str, str | None]
    binding_signature: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bindings",
            MappingProxyType(
                dict(
                    sorted(
                        self.bindings.items(),
                        key=lambda item: item[0].sort_key(),
                    )
                )
            ),
        )
        object.__setattr__(
            self,
            "goal_input_refs",
            MappingProxyType(dict(sorted(self.goal_input_refs.items()))),
        )
        object.__setattr__(
            self,
            "goal_answer_refs",
            MappingProxyType(dict(sorted(self.goal_answer_refs.items()))),
        )
        object.__setattr__(
            self,
            "goal_visible_scope_ids",
            MappingProxyType(dict(sorted(self.goal_visible_scope_ids.items()))),
        )
        object.__setattr__(
            self,
            "scope_parent_ids",
            MappingProxyType(dict(sorted(self.scope_parent_ids.items()))),
        )

    @property
    def problem_revision_id(self) -> str:
        return self.bundle_authority_token.problem_revision_id

    @property
    def problem_semantic_hash(self) -> str:
        return self.bundle_authority_token.problem_semantic_hash

    def authority_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PROBLEM_PLANNING_BINDING_CATALOG_CONTRACT,
            "planning_context_id": self.planning_context_id,
            "bundle_authority_token": self.bundle_authority_token.to_payload(),
            "planner_state_context_id": self.planner_state_context_id,
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "bindings": [
                value.authority_payload()
                for value in self.bindings.values()
            ],
            "goal_input_refs": {
                key: [item.to_payload() for item in value]
                for key, value in self.goal_input_refs.items()
            },
            "goal_answer_refs": {
                key: value.to_payload()
                for key, value in self.goal_answer_refs.items()
            },
            "goal_visible_scope_ids": {
                key: list(value)
                for key, value in self.goal_visible_scope_ids.items()
            },
            "scope_parent_ids": dict(self.scope_parent_ids),
            "binding_signature": self.binding_signature,
        }

    def resolve_input_binding(
        self,
        *,
        scope_id: str,
        local_ref: str,
        goal_unit_ids: Sequence[str] = (),
    ) -> ProblemPlanningSourceBinding:
        path = self._scope_path(scope_id)
        goal_ids = frozenset(goal_unit_ids)
        matches = tuple(
            binding
            for key, binding in self.bindings.items()
            if binding.usage == "input"
            and key.local_ref == local_ref
            and key.owner_scope_id in path
            and (
                not goal_ids
                or goal_ids.issubset(binding.visible_goal_unit_ids)
            )
        )
        if len(matches) != 1:
            code = (
                "planner.problem_source_binding_unresolved"
                if not matches
                else "planner.problem_source_binding_drift"
            )
            raise _error(
                code,
                "$.bindings",
                (
                    f"SourceRef {local_ref!r} has no visible binding from "
                    f"scope {scope_id!r}"
                    if not matches
                    else (
                        f"SourceRef {local_ref!r} resolves to multiple "
                        f"bindings from scope {scope_id!r}"
                    )
                ),
            )
        return matches[0]

    def answer_binding_for_goal(
        self,
        goal_unit_id: str,
    ) -> ProblemPlanningSourceBinding:
        key = self.goal_answer_refs.get(goal_unit_id)
        binding = self.bindings.get(key) if key is not None else None
        if binding is None or binding.usage != "answer":
            raise _error(
                "planner.problem_source_binding_unresolved",
                "$.goal_answer_refs",
                f"Goal {goal_unit_id!r} has no answer binding",
            )
        return binding

    def _scope_path(self, scope_id: str) -> tuple[str, ...]:
        if scope_id not in self.scope_parent_ids:
            raise _error(
                "planner.problem_scope_visibility_drift",
                "$.scope_parent_ids",
                f"unknown binding resolution scope {scope_id!r}",
            )
        result: list[str] = []
        seen: set[str] = set()
        current: str | None = scope_id
        while current is not None:
            if current in seen or current not in self.scope_parent_ids:
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    "$.scope_parent_ids",
                    "binding catalog scope ancestry is invalid",
                )
            seen.add(current)
            result.append(current)
            current = self.scope_parent_ids[current]
        return tuple(reversed(result))

    def semantic_read_items(self) -> tuple[SemanticReadCatalogItem, ...]:
        result: list[SemanticReadCatalogItem] = []
        for binding in self.bindings.values():
            for source in binding.typed_sources:
                if (
                    binding.semantic_ref.kind != "fact"
                    and source.kind == "state_version"
                ):
                    continue
                result.append(
                    SemanticReadCatalogItem(
                        handle=binding.runtime_node_id,
                        kind=binding.semantic_ref.kind,
                        ref=binding.semantic_ref.ref,
                        scope=(
                            source.state_version_id.slot_id.storage_scope_id
                            if source.state_version_id is not None
                            else binding.owner_scope_id
                        ),
                        valid_scope=(
                            source.state_version_id.slot_id.storage_scope_id
                            if source.state_version_id is not None
                            else binding.owner_scope_id
                        ),
                        value_type=(
                            binding.semantic_ref.value_type
                            or source.runtime_type
                        ),
                        state_slot_id=source.state_slot_id,
                        condition_id=source.condition_id,
                        source_context_id=self.planner_state_context_id,
                        math_object_id=source.math_object_id,
                        state_version_id=source.state_version_id,
                        authority_scope_id=binding.owner_scope_id,
                    )
                )
        return tuple(result)

    def identity_only_ref_keys(self) -> frozenset[ScopedSourceRefKey]:
        """Return prompt refs that name an object but carry no source state."""

        return frozenset(
            key
            for key, binding in self.bindings.items()
            if binding.usage == "input"
            and binding.typed_sources
            and all(
                source.kind == "math_object"
                for source in binding.typed_sources
            )
        )

    def source_units_for_identity(
        self,
        *,
        math_object_id: MathObjectId | None = None,
        state_version_id: StateVersionId | None = None,
        condition_id: str | None = None,
    ) -> tuple[str, ...]:
        result: set[str] = set()
        for binding in self.bindings.values():
            for source in binding.typed_sources:
                if (
                    math_object_id is not None
                    and source.math_object_id == math_object_id
                ) or (
                    state_version_id is not None
                    and source.state_version_id == state_version_id
                ) or (
                    condition_id is not None
                    and source.condition_id == condition_id
                ):
                    result.update(binding.source_unit_ids)
        return tuple(sorted(result))

    def bind_plan(
        self,
        plan: FunctionalPlan,
        *,
        require_goal_reachable: bool = False,
        additional_dependencies: Mapping[str, Sequence[str]] | None = None,
        authored_goal_unit_ids: Mapping[str, Sequence[str]] | None = None,
    ) -> ProblemPlanGoalBindings:
        return _bind_plan_goals(
            self,
            plan,
            require_goal_reachable=require_goal_reachable,
            additional_dependencies=additional_dependencies,
            authored_goal_unit_ids=authored_goal_unit_ids,
        )


class ProblemPlanningBindingCatalogBuilder:
    """Map authenticated source/runtime nodes to one typed Context snapshot."""

    def build(
        self,
        bundle: VerifiedSolverProblemBundle,
        planning_context: ProblemPlanningContext,
        planner_state_context: PlannerStateContext,
        handle_registry: CanonicalHandleRegistry,
        *,
        expected_token: ProblemBundleAuthorityToken | None = None,
    ) -> ProblemPlanningBindingCatalog:
        _audit_authority_inputs(
            bundle,
            planning_context,
            planner_state_context,
            handle_registry,
            expected_token=expected_token,
        )
        authorities, goal_inputs, goal_answers, goal_scopes = (
            _planning_authorities(planning_context)
        )
        runtime_nodes = _canonical_runtime_nodes(bundle.canonical_solver_input)
        goal_target_handles = _goal_target_handles(bundle)
        bindings: dict[ScopedSourceRefKey, ProblemPlanningSourceBinding] = {}
        for ref_key, authority in sorted(
            authorities.items(),
            key=lambda item: item[0].sort_key(),
        ):
            node = runtime_nodes.get(authority.runtime_node_id)
            if node is None:
                raise _error(
                    "planner.problem_source_binding_unresolved",
                    "$.ref_authorities",
                    f"runtime node {authority.runtime_node_id!r} is absent",
                )
            node_kind, payload = node
            owner_scope_id = str(payload.get("scope_id", ""))
            if owner_scope_id != authority.owner_scope_id:
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    f"$.ref_authorities[{ref_key.local_ref!r}]",
                    "runtime node owner differs from planning authority",
                )
            typed_sources = _typed_sources_for_node(
                authority,
                node_kind=node_kind,
                runtime_node_payload=payload,
                planner_state_context=planner_state_context,
                goal_target_handle=_goal_target_handle_for_authority(
                    authority,
                    goal_target_handles,
                ),
            )
            bindings[ref_key] = ProblemPlanningSourceBinding(
                semantic_ref=authority.semantic_ref,
                runtime_node_id=authority.runtime_node_id,
                source_unit_ids=authority.source_unit_ids,
                owner_scope_id=authority.owner_scope_id,
                visible_goal_unit_ids=authority.visible_goal_unit_ids,
                usage=authority.usage,
                typed_sources=typed_sources,
            )
        payload = {
            "schema_version": PROBLEM_PLANNING_BINDING_CATALOG_CONTRACT,
            "planning_context_id": planning_context.planning_context_id,
            "bundle_authority_token": bundle.authority_token.to_payload(),
            "planner_state_context_id": (
                planner_state_context.manifest.context_id
            ),
            "problem_id": planning_context.problem_id,
            "family_id": planning_context.family_id,
            "bindings": [
                value.authority_payload()
                for _key, value in sorted(
                    bindings.items(),
                    key=lambda item: item[0].sort_key(),
                )
            ],
            "goal_input_refs": {
                key: [item.to_payload() for item in value]
                for key, value in sorted(goal_inputs.items())
            },
            "goal_answer_refs": {
                key: value.to_payload()
                for key, value in sorted(goal_answers.items())
            },
            "goal_visible_scope_ids": {
                key: list(value) for key, value in sorted(goal_scopes.items())
            },
            "scope_parent_ids": {
                scope.scope_id: scope.parent_scope_id
                for scope in planning_context.scopes
            },
        }
        return ProblemPlanningBindingCatalog(
            planning_context_id=planning_context.planning_context_id,
            bundle_authority_token=bundle.authority_token,
            planner_state_context_id=planner_state_context.manifest.context_id,
            problem_id=planning_context.problem_id,
            family_id=planning_context.family_id,
            bindings=bindings,
            goal_input_refs=goal_inputs,
            goal_answer_refs=goal_answers,
            goal_visible_scope_ids=goal_scopes,
            scope_parent_ids={
                scope.scope_id: scope.parent_scope_id
                for scope in planning_context.scopes
            },
            binding_signature=stable_hash(payload),
        )


def build_functional_problem_binding_context(
    catalog: ProblemPlanningBindingCatalog,
    plan: FunctionalPlan,
    calls: Sequence[FunctionalCallReconciliation],
    functional_binding_context: FunctionalBindingContext,
    goal_bindings: ProblemPlanGoalBindings | None = None,
    *,
    allow_implicit_same_object_call_result: bool = True,
) -> FunctionalProblemBindingContext:
    goal_bindings = goal_bindings or catalog.bind_plan(
        plan,
        require_goal_reachable=True,
    )
    if goal_bindings.issues:
        first = goal_bindings.issues[0]
        raise _error(
            first.code,
            f"$.calls[{first.call_id!r}]",
            first.message,
        )
    wire_calls = {call.call_id: call for call in plan.calls}
    call_scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    reconciled = {call.call_id: call for call in calls}
    inputs: list[FunctionalProblemInputBinding] = []
    for binding in functional_binding_context.bindings:
        call_id = binding.key.call_id
        call_goals = goal_bindings.calls.get(call_id)
        if call_goals is None:
            raise _error(
                "functional.call_goal_unresolved",
                f"$.calls[{call_id!r}]",
                "C3 binding belongs to a call with no Goal authority",
            )
        wire_call = wire_calls.get(call_id)
        wire_values = (
            wire_call.args.get(binding.key.arg_name, ())
            if wire_call is not None
            else ()
        )
        wire_ref = (
            wire_values[binding.key.item_index]
            if binding.key.item_index < len(wire_values)
            else None
        )
        if isinstance(wire_ref, SemanticRef):
            source_binding = _binding_for_semantic_ref(
                catalog,
                wire_ref,
                scope_id=call_scopes[call_id],
                goal_unit_ids=call_goals.effective_goal_unit_ids,
            )
            if source_binding.scoped_key not in call_goals.allowed_ref_keys:
                raise _error(
                    "functional.semantic_ref_not_visible_for_goal",
                    (
                        f"$.calls[{call_id!r}].args"
                        f"[{binding.key.arg_name!r}]"
                    ),
                    f"SemanticRef {wire_ref.ref!r} is outside Goal authority",
                )
            if binding.source.kind == "call_result":
                if not allow_implicit_same_object_call_result:
                    raise _error(
                        "functional.dynamic_source_ref_requires_step_result",
                        (
                            f"$.calls[{call_id!r}].args"
                            f"[{binding.key.arg_name!r}]"
                            f"[{binding.key.item_index}]"
                        ),
                        (
                            "a FunctionalPlan v2 SourceRef resolved to a "
                            "dynamic call result; use an explicit "
                            "StepResultRef"
                        ),
                        retryable=True,
                        details={
                            "localizable_step_issue": True,
                            "stage": "reconciliation_binding",
                            "step_id": call_id,
                            "call_id": call_id,
                            "arg_name": binding.key.arg_name,
                            "item_index": binding.key.item_index,
                            "source_ref": wire_ref.ref,
                            "required_step_result": {
                                "step_id": binding.source.source_call_id,
                                "return": (
                                    binding.source.source_return_name
                                ),
                            },
                        },
                    )
                _audit_implicit_same_object_call_result(
                    source_binding=source_binding,
                    source=binding.source,
                    consumer_call_id=call_id,
                    consumer_goal_binding=call_goals,
                    reconciled_calls=reconciled,
                    goal_bindings=goal_bindings,
                    catalog=catalog,
                    path=(
                        f"$.calls[{call_id!r}].args"
                        f"[{binding.key.arg_name!r}]"
                        f"[{binding.key.item_index}]"
                    ),
                )
                inputs.append(
                    FunctionalProblemInputBinding(
                        call_id=call_id,
                        arg_name=binding.key.arg_name,
                        item_index=binding.key.item_index,
                        source_kind="call_result",
                        selection_policy=binding.selection_policy,
                        semantic_ref=wire_ref,
                        runtime_node_id=source_binding.runtime_node_id,
                        typed_source=binding.source,
                    )
                )
                continue
            source_units = set(source_binding.source_unit_ids)
            if not _binding_accepts_c3_source(
                source_binding,
                binding.source,
            ):
                supporting = _authority_for_c3_source(
                    catalog,
                    binding.source,
                    goal_unit_ids=call_goals.effective_goal_unit_ids,
                    path=(
                        f"$.calls[{call_id!r}].args"
                        f"[{binding.key.arg_name!r}]"
                    ),
                )
                if not _same_source_object(source_binding, supporting):
                    raise _error(
                        "planner.problem_source_binding_drift",
                        (
                            f"$.calls[{call_id!r}].args"
                            f"[{binding.key.arg_name!r}]"
                        ),
                        "C3 selected a state for a different source object",
                    )
                source_units.update(supporting.source_unit_ids)
            elif binding.source.kind == "state_version":
                for supporting in _supporting_authorities_for_c3_source(
                    catalog,
                    binding.source,
                    goal_unit_ids=call_goals.effective_goal_unit_ids,
                    exclude_runtime_node=source_binding.runtime_node_id,
                ):
                    if _same_source_object(source_binding, supporting):
                        source_units.update(supporting.source_unit_ids)
            inputs.append(
                FunctionalProblemInputBinding(
                    call_id=call_id,
                    arg_name=binding.key.arg_name,
                    item_index=binding.key.item_index,
                    source_kind="problem_source",
                    selection_policy=binding.selection_policy,
                    semantic_ref=wire_ref,
                    runtime_node_id=source_binding.runtime_node_id,
                    source_unit_ids=tuple(sorted(source_units)),
                    typed_source=binding.source,
                )
            )
            continue
        if binding.source.kind == "call_result":
            if wire_ref is not None and (
                not isinstance(wire_ref, CallResultRef)
                or wire_ref.from_call != binding.source.source_call_id
                or wire_ref.return_name
                != binding.source.source_return_name
            ):
                raise _error(
                    "planner.problem_source_binding_drift",
                    f"$.calls[{call_id!r}].args",
                    "C3 CallResult source differs from the Functional wire",
                )
            inputs.append(
                FunctionalProblemInputBinding(
                    call_id=call_id,
                    arg_name=binding.key.arg_name,
                    item_index=binding.key.item_index,
                    source_kind="call_result",
                    selection_policy=binding.selection_policy,
                    typed_source=binding.source,
                )
            )
            continue
        if binding.source.kind == "compiler_selector":
            inputs.append(
                FunctionalProblemInputBinding(
                    call_id=call_id,
                    arg_name=binding.key.arg_name,
                    item_index=binding.key.item_index,
                    source_kind="compiler_selector",
                    selection_policy=binding.selection_policy,
                    typed_source=binding.source,
                )
            )
            continue
        source_binding = _authority_for_c3_source(
            catalog,
            binding.source,
            goal_unit_ids=call_goals.effective_goal_unit_ids,
            path=(
                f"$.calls[{call_id!r}].args"
                f"[{binding.key.arg_name!r}]"
            ),
        )
        inputs.append(
            FunctionalProblemInputBinding(
                call_id=call_id,
                arg_name=binding.key.arg_name,
                item_index=binding.key.item_index,
                source_kind="problem_source",
                selection_policy=binding.selection_policy,
                semantic_ref=source_binding.semantic_ref,
                runtime_node_id=source_binding.runtime_node_id,
                source_unit_ids=source_binding.source_unit_ids,
                typed_source=binding.source,
            )
        )

    answer_to_goal = {
        (ref_key.local_ref, ref_key.kind): goal_id
        for goal_id, ref_key in catalog.goal_answer_refs.items()
    }
    returns: list[FunctionalProblemReturnBinding] = []
    for call_id, wire_call in wire_calls.items():
        call = reconciled.get(call_id)
        if call is None:
            continue
        allocations = {item.return_name: item for item in call.returns}
        call_goals = goal_bindings.calls[call_id]
        for return_name, semantic_ref in wire_call.return_bindings.items():
            allocation = allocations.get(return_name)
            if allocation is None or allocation.math_object_id is None:
                raise _error(
                    "planner.problem_source_binding_drift",
                    f"$.calls[{call_id!r}].returns[{return_name!r}]",
                    "B1 allocation has no MathObjectId",
                )
            source_binding = _binding_for_return_semantic_ref(
                catalog,
                semantic_ref,
                scope_id=call_scopes[call_id],
                goal_unit_ids=call_goals.effective_goal_unit_ids,
            )
            expected_object_ids = {
                item.math_object_id
                for item in source_binding.typed_sources
                if item.math_object_id is not None
            }
            if allocation.math_object_id not in expected_object_ids:
                raise _error(
                    "planner.problem_source_binding_drift",
                    f"$.calls[{call_id!r}].returns[{return_name!r}]",
                    "B1 return target differs from Problem authority",
                )
            goal_id = answer_to_goal.get(
                (semantic_ref.ref, semantic_ref.kind)
            )
            if goal_id is not None and goal_id not in call_goals.goal_unit_ids:
                raise _error(
                    "functional.answer_ref_goal_mismatch",
                    f"$.calls[{call_id!r}].returns[{return_name!r}]",
                    "answer return is not in the call Goal closure",
                )
            returns.append(
                FunctionalProblemReturnBinding(
                    call_id=call_id,
                    return_name=return_name,
                    semantic_ref=semantic_ref,
                    runtime_node_id=source_binding.runtime_node_id,
                    source_unit_ids=source_binding.source_unit_ids,
                    goal_unit_id=goal_id,
                    math_object_id=allocation.math_object_id,
                )
            )

    call_goal_bindings = {
        call_id: binding.goal_unit_ids
        for call_id, binding in goal_bindings.calls.items()
    }
    input_bindings = tuple(
        sorted(inputs, key=lambda item: (item.call_id, item.arg_name, item.item_index))
    )
    return_bindings = tuple(
        sorted(returns, key=lambda item: (item.call_id, item.return_name))
    )
    payload = {
        "schema_version": FUNCTIONAL_PROBLEM_BINDING_CONTEXT_CONTRACT,
        "planning_context_id": catalog.planning_context_id,
        "problem_revision_id": catalog.problem_revision_id,
        "problem_semantic_hash": catalog.problem_semantic_hash,
        "planner_state_context_id": catalog.planner_state_context_id,
        "call_goal_bindings": {
            key: list(value) for key, value in sorted(call_goal_bindings.items())
        },
        "input_bindings": [item.to_payload() for item in input_bindings],
        "return_bindings": [item.to_payload() for item in return_bindings],
    }
    return FunctionalProblemBindingContext(
        planning_context_id=catalog.planning_context_id,
        problem_revision_id=catalog.problem_revision_id,
        problem_semantic_hash=catalog.problem_semantic_hash,
        planner_state_context_id=catalog.planner_state_context_id,
        call_goal_bindings=call_goal_bindings,
        input_bindings=input_bindings,
        return_bindings=return_bindings,
        binding_signature=stable_hash(payload),
    )


def _audit_authority_inputs(
    bundle: VerifiedSolverProblemBundle,
    planning_context: ProblemPlanningContext,
    planner_state_context: PlannerStateContext,
    handle_registry: CanonicalHandleRegistry,
    *,
    expected_token: ProblemBundleAuthorityToken | None,
) -> None:
    if expected_token is not None and bundle.authority_token != expected_token:
        raise _error(
            "planner.problem_revision_drift",
            "$.bundle_authority_token",
            "bundle differs from the expected authority token",
        )
    if planning_context.bundle_authority_token != bundle.authority_token:
        raise _error(
            "planner.problem_revision_drift",
            "$.planning_context.bundle_authority_token",
            "planning Context was not derived from this bundle",
        )
    if (
        planning_context.problem_id != bundle.verified_problem.graph.problem_id
        or planner_state_context.manifest.problem_id != planning_context.problem_id
    ):
        raise _error(
            "planner.problem_source_binding_drift",
            "$.problem_id",
            "problem identity differs across binding authorities",
        )
    if (
        planning_context.family_id != bundle.verified_problem.family_id
        or planner_state_context.manifest.family_id != planning_context.family_id
    ):
        raise _error(
            "planner.problem_source_binding_drift",
            "$.family_id",
            "family differs across binding authorities",
        )
    if stable_hash(
        _problem_authority_payload(planner_state_context.state.problem_ir)
    ) != stable_hash(_problem_authority_payload(bundle.canonical_solver_input)):
        raise _error(
            "planner.problem_revision_drift",
            "$.planner_state_context.state.problem_ir",
            "PlannerStateContext does not contain the bundle canonical input",
        )
    canonical_scopes = {
        str(item.get("scope_id", "")): item.get("parent")
        for item in bundle.canonical_solver_input.get("scopes", ())
        if isinstance(item, Mapping)
    }
    if (
        set(canonical_scopes) != set(planner_state_context.state.scope_graph.scope_ids)
        or canonical_scopes
        != dict(planner_state_context.state.scope_graph.scope_parents)
    ):
        raise _error(
            "planner.problem_scope_visibility_drift",
            "$.planner_state_context.state.scope_graph",
            "Planner scope graph differs from the verified problem",
        )
    runtime_handles = {
        str(item.get("handle", ""))
        for collection in ("entities", "facts", "question_goals")
        for item in bundle.canonical_solver_input.get(collection, ())
        if isinstance(item, Mapping)
    }
    if not runtime_handles.issubset(handle_registry.initial_handles):
        raise _error(
            "planner.problem_source_binding_drift",
            "$.handle_registry",
            "canonical runtime nodes are absent from the handle registry",
        )


def _planning_authorities(
    planning_context: ProblemPlanningContext,
) -> tuple[
    dict[ScopedSourceRefKey, PlanningReadAuthority],
    dict[str, tuple[ScopedSourceRefKey, ...]],
    dict[str, ScopedSourceRefKey],
    dict[str, tuple[str, ...]],
]:
    authorities: dict[ScopedSourceRefKey, PlanningReadAuthority] = {}
    goal_inputs: dict[str, tuple[ScopedSourceRefKey, ...]] = {}
    goal_answers: dict[str, ScopedSourceRefKey] = {}
    goal_scopes: dict[str, tuple[str, ...]] = {}
    for goal in planning_context.goal_views:
        inputs = planning_context.input_authorities_for_goal(goal.goal_unit_id)
        answer = planning_context.answer_authority_for_goal(goal.goal_unit_id)
        goal_inputs[goal.goal_unit_id] = tuple(
            sorted(
                (item.scoped_key for item in inputs),
                key=ScopedSourceRefKey.sort_key,
            )
        )
        goal_answers[goal.goal_unit_id] = answer.scoped_key
        goal_scopes[goal.goal_unit_id] = tuple(goal.visible_scope_ids)
        for item in (*inputs, answer):
            previous = authorities.get(item.scoped_key)
            if previous is not None and previous != item:
                raise _error(
                    "planner.problem_source_binding_drift",
                    "$.ref_authorities",
                    (
                        f"SourceRef {item.semantic_ref.ref!r} has conflicting "
                        f"authority in scope {item.owner_scope_id!r}"
                    ),
                )
            authorities[item.scoped_key] = item
    return authorities, goal_inputs, goal_answers, goal_scopes


def _problem_authority_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    original = payload.get("original_text", ())
    if isinstance(original, Mapping):
        original = original.get("lines", ())

    def semantic(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                str(key): semantic(child)
                for key, child in value.items()
                if key not in {"display", "description", "source"}
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return [semantic(item) for item in value]
        return value

    return {
        "problem_id": payload.get("problem_id"),
        "pattern": payload.get("pattern"),
        "problem_type": payload.get("problem_type"),
        "original_text": semantic(original),
        "scopes": semantic(payload.get("scopes", ())),
        "entities": semantic(payload.get("entities", ())),
        "facts": semantic(payload.get("facts", ())),
        "question_goals": semantic(payload.get("question_goals", ())),
    }


def _canonical_runtime_nodes(
    payload: Mapping[str, Any],
) -> dict[str, tuple[str, Mapping[str, Any]]]:
    result: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for collection, kind in (
        ("entities", "entity"),
        ("facts", "fact"),
        ("question_goals", "goal"),
    ):
        for item in payload.get(collection, ()):
            if not isinstance(item, Mapping):
                continue
            handle = str(item.get("handle", ""))
            if not handle or handle in result:
                raise _error(
                    "planner.problem_source_binding_drift",
                    f"$.canonical_input.{collection}",
                    f"runtime handle is missing or duplicate: {handle!r}",
                )
            result[handle] = (kind, item)
    return result


def _typed_sources_for_node(
    authority: PlanningReadAuthority,
    *,
    node_kind: str,
    runtime_node_payload: Mapping[str, Any],
    planner_state_context: PlannerStateContext,
    goal_target_handle: str | None = None,
) -> tuple[ProblemTypedSourceIdentity, ...]:
    handle = authority.runtime_node_id
    projected_target = runtime_node_payload.get("target_handle")
    target_handle = (
        str(projected_target)
        if isinstance(projected_target, str)
        else goal_target_handle
    )
    if node_kind == "goal" and target_handle is None:
        goal_id = handle.removeprefix("answer:")
        owner_scope_id = str(runtime_node_payload.get("scope_id", ""))
        if not goal_id or not owner_scope_id:
            raise _error(
                "planner.problem_source_binding_unresolved",
                f"$.runtime_nodes[{handle!r}]",
                "value-only Goal has no stable answer identity",
            )
        return (
            ProblemTypedSourceIdentity(
                kind="answer_target",
                math_object_id=MathObjectId(
                    value=f"question_goal:{goal_id}",
                    kind="answer",
                    origin_scope_id=owner_scope_id,
                ),
            ),
        )
    object_handle = target_handle if node_kind == "goal" else handle
    objects = tuple(
        item
        for item in planner_state_context.state.math_objects
        if item.canonical_handle == object_handle
    )
    conditions = tuple(
        item
        for item in planner_state_context.state.conditions
        if item.canonical_handle == handle
    )
    slots = tuple(
        item
        for item in planner_state_context.state.state_slots
        if item.canonical_handle == handle
    )
    result: list[ProblemTypedSourceIdentity] = []
    if node_kind in {"entity", "goal"}:
        if len(objects) != 1 or objects[0].math_object_id is None:
            raise _error(
                "planner.problem_source_binding_unresolved",
                f"$.runtime_nodes[{handle!r}]",
                "runtime object does not map to one MathObjectId",
            )
        result.append(
            ProblemTypedSourceIdentity(
                kind=("answer_target" if node_kind == "goal" else "math_object"),
                math_object_id=objects[0].math_object_id,
            )
        )
        if node_kind == "entity":
            object_id = objects[0].math_object_id
            for slot in planner_state_context.state.state_slots:
                if (
                    slot.logical_state_key is None
                    or slot.logical_state_key.object_id != object_id
                ):
                    continue
                source_version_id = _pinned_source_version_id(
                    slot,
                    runtime_node_id=handle,
                )
                result.append(
                    ProblemTypedSourceIdentity(
                        kind="state_version",
                        runtime_type=slot.runtime_type,
                        math_object_id=object_id,
                        state_version_id=source_version_id,
                        state_slot_id=slot.slot_id,
                    )
                )
    if node_kind == "fact":
        for condition in conditions:
            result.append(
                ProblemTypedSourceIdentity(
                    kind="condition",
                    runtime_type=condition.value_type,
                    condition_id=condition.condition_id,
                )
            )
        for slot in slots:
            source_version_id = _pinned_source_version_id(
                slot,
                runtime_node_id=handle,
            )
            result.append(
                ProblemTypedSourceIdentity(
                    kind="state_version",
                    runtime_type=slot.runtime_type,
                    math_object_id=(
                        slot.logical_state_key.object_id
                        if slot.logical_state_key is not None
                        else None
                    ),
                    state_version_id=source_version_id,
                    state_slot_id=slot.slot_id,
                )
            )
        if not result:
            raise _error(
                "planner.problem_source_binding_unresolved",
                f"$.runtime_nodes[{handle!r}]",
                "runtime fact maps to neither ConditionId nor StateVersionId",
            )
    return tuple(result)


def _pinned_source_version_id(
    slot: StateSlot,
    *,
    runtime_node_id: str,
) -> StateVersionId:
    """Return the immutable source snapshot, never the current latest state."""

    if slot.typed_slot_id is None or slot.logical_state_key is None:
        raise _error(
            "planner.problem_source_binding_unresolved",
            f"$.runtime_nodes[{runtime_node_id!r}]",
            "source state has no typed StateSlotId",
        )
    source_version_id = StateVersionId(slot.typed_slot_id, 0)
    if slot.latest_version_id != source_version_id or slot.write_history:
        raise _error(
            "planner.problem_source_binding_drift",
            f"$.runtime_nodes[{runtime_node_id!r}]",
            (
                "source state has evolved beyond its ordinal-0 snapshot; "
                "reuse the original ProblemPlanningBindingCatalog"
            ),
        )
    return source_version_id


def _goal_target_handles(
    bundle: VerifiedSolverProblemBundle,
) -> dict[str, str]:
    """Resolve source Goal targets without extending canonical Solver wire."""

    index = ProblemDomainIndex(bundle.verified_problem.graph)
    result: dict[str, str] = {}
    for scope in bundle.verified_problem.graph.root_scope.iter_scopes():
        for goal in scope.goals:
            target = goal.attributes.get("target")
            if not isinstance(target, str):
                continue
            result[goal.unit_id] = index.resolve(scope.path_id, target).handle
    return result


def _goal_target_handle_for_authority(
    authority: PlanningReadAuthority,
    goal_target_handles: Mapping[str, str],
) -> str | None:
    mapped = tuple(
        (unit_id, goal_target_handles[unit_id])
        for unit_id in authority.source_unit_ids
        if unit_id in goal_target_handles
    )
    if not mapped:
        return None
    if len(mapped) != 1:
        raise _error(
            "planner.problem_source_binding_drift",
            f"$.ref_authorities[{authority.semantic_ref.ref!r}]",
            (
                "answer authority maps multiple source Goal units: "
                f"{[unit_id for unit_id, _handle in mapped]}"
            ),
        )
    return mapped[0][1]


def _binding_for_semantic_ref(
    catalog: ProblemPlanningBindingCatalog,
    ref: SemanticRef,
    *,
    scope_id: str,
    goal_unit_ids: Sequence[str],
) -> ProblemPlanningSourceBinding:
    binding = catalog.resolve_input_binding(
        scope_id=scope_id,
        local_ref=ref.ref,
        goal_unit_ids=goal_unit_ids,
    )
    if binding.semantic_ref.kind != ref.kind:
        raise _error(
            "planner.problem_source_binding_unresolved",
            f"$.bindings[{ref.ref!r}]",
            "SemanticRef has no exact Problem authority",
        )
    return binding


def _binding_for_return_semantic_ref(
    catalog: ProblemPlanningBindingCatalog,
    ref: SemanticRef,
    *,
    scope_id: str,
    goal_unit_ids: Sequence[str],
) -> ProblemPlanningSourceBinding:
    answer_matches = tuple(
        catalog.answer_binding_for_goal(goal_id)
        for goal_id in goal_unit_ids
        if goal_id in catalog.goal_answer_refs
        and catalog.goal_answer_refs[goal_id].local_ref == ref.ref
        and catalog.goal_answer_refs[goal_id].kind == ref.kind
    )
    if len(answer_matches) == 1:
        return answer_matches[0]
    return _binding_for_semantic_ref(
        catalog,
        ref,
        scope_id=scope_id,
        goal_unit_ids=goal_unit_ids,
    )


def _audit_implicit_same_object_call_result(
    *,
    source_binding: ProblemPlanningSourceBinding,
    source: FunctionalArgSourceIdentity,
    consumer_call_id: str,
    consumer_goal_binding: ProblemCallGoalBinding,
    reconciled_calls: Mapping[str, FunctionalCallReconciliation],
    goal_bindings: ProblemPlanGoalBindings,
    catalog: ProblemPlanningBindingCatalog,
    path: str,
) -> None:
    """Authorize a SemanticRef lowered to one exact prior object state."""

    producer_call_id = source.source_call_id
    producer_return_name = source.source_return_name
    call_order = tuple(reconciled_calls)
    if (
        producer_call_id is None
        or producer_return_name is None
        or producer_call_id not in reconciled_calls
        or consumer_call_id not in reconciled_calls
        or call_order.index(producer_call_id)
        >= call_order.index(consumer_call_id)
    ):
        raise _error(
            "planner.problem_source_binding_drift",
            path,
            "implicit dynamic source is not one exact earlier call result",
        )

    allocations = tuple(
        item
        for item in reconciled_calls[producer_call_id].returns
        if item.return_name == producer_return_name
    )
    if len(allocations) != 1 or allocations[0].math_object_id is None:
        raise _error(
            "planner.problem_source_binding_drift",
            path,
            "implicit dynamic source has no unique object-bearing return",
        )
    allocation = allocations[0]
    source_object_ids = {
        item.math_object_id
        for item in source_binding.typed_sources
        if item.math_object_id is not None
    }
    if (
        source_binding.usage != "input"
        or len(source_object_ids) != 1
        or allocation.math_object_id not in source_object_ids
    ):
        raise _error(
            "planner.problem_source_binding_drift",
            path,
            "computed return does not preserve the SemanticRef object identity",
        )

    consumer_goal_ids = set(
        consumer_goal_binding.effective_goal_unit_ids
    )
    producer_goal_binding = goal_bindings.calls.get(producer_call_id)
    if (
        producer_goal_binding is None
        or not consumer_goal_ids.issubset(
            producer_goal_binding.effective_goal_unit_ids
        )
    ):
        raise _error(
            "planner.problem_scope_visibility_drift",
            path,
            "computed return is outside the consumer call Goal authority",
        )
    invisible_goals = tuple(
        sorted(
            goal_id
            for goal_id in consumer_goal_ids
            if allocation.valid_scope
            not in catalog.goal_visible_scope_ids.get(goal_id, ())
        )
    )
    if invisible_goals:
        raise _error(
            "planner.problem_scope_visibility_drift",
            path,
            (
                "computed return scope is not visible to consumer Goals: "
                f"{list(invisible_goals)}"
            ),
        )

    compatible_prior_results = tuple(
        (candidate_call_id, candidate.return_name)
        for candidate_call_id in call_order[: call_order.index(consumer_call_id)]
        for candidate_goal_binding in (
            goal_bindings.calls.get(candidate_call_id),
        )
        if candidate_goal_binding is not None
        and consumer_goal_ids.issubset(
            candidate_goal_binding.effective_goal_unit_ids
        )
        for candidate in reconciled_calls[candidate_call_id].returns
        if candidate.math_object_id == allocation.math_object_id
        and runtime_type_compatible(
            allocation.runtime_type,
            candidate.runtime_type,
        )
        and all(
            candidate.valid_scope
            in catalog.goal_visible_scope_ids.get(goal_id, ())
            for goal_id in consumer_goal_ids
        )
    )
    if not compatible_prior_results or compatible_prior_results[-1] != (
        producer_call_id,
        producer_return_name,
    ):
        raise _error(
            "planner.problem_source_binding_drift",
            path,
            "implicit dynamic source is not the latest Goal-visible object state",
        )


def _typed_source_matches_c3(
    source: ProblemTypedSourceIdentity,
    c3_source: FunctionalArgSourceIdentity,
) -> bool:
    if c3_source.kind == "state_version":
        return source.state_version_id == c3_source.state_version_id
    if c3_source.kind == "condition":
        return source.condition_id == c3_source.condition_id
    if c3_source.kind == "math_object":
        return source.math_object_id == c3_source.math_object_id
    return False


def _binding_accepts_c3_source(
    binding: ProblemPlanningSourceBinding,
    source: FunctionalArgSourceIdentity,
) -> bool:
    return any(
        _typed_source_matches_c3(item, source)
        for item in binding.typed_sources
    )


def _authority_for_c3_source(
    catalog: ProblemPlanningBindingCatalog,
    source: FunctionalArgSourceIdentity,
    *,
    goal_unit_ids: Sequence[str],
    path: str = "$.functional_binding_context",
) -> ProblemPlanningSourceBinding:
    required_goals = set(goal_unit_ids)
    candidates = tuple(
        binding
        for binding in catalog.bindings.values()
        if binding.usage == "input"
        and required_goals.issubset(binding.visible_goal_unit_ids)
        and _binding_accepts_c3_source(binding, source)
    )
    by_runtime_node = {
        item.runtime_node_id: item for item in candidates
    }
    if source.kind == "state_version" and len(by_runtime_node) > 1:
        state_fact_candidates = {
            key: item
            for key, item in by_runtime_node.items()
            if item.semantic_ref.kind == "fact"
        }
        if len(state_fact_candidates) == 1:
            by_runtime_node = state_fact_candidates
    if len(by_runtime_node) != 1:
        raise _error(
            "planner.problem_source_binding_unresolved",
            path,
            (
                "C3 source maps to "
                f"{len(by_runtime_node)} Goal-visible runtime nodes: "
                f"source={source.to_payload()}, goals={sorted(required_goals)}"
            ),
        )
    return next(iter(by_runtime_node.values()))


def _supporting_authorities_for_c3_source(
    catalog: ProblemPlanningBindingCatalog,
    source: FunctionalArgSourceIdentity,
    *,
    goal_unit_ids: Sequence[str],
    exclude_runtime_node: str,
) -> tuple[ProblemPlanningSourceBinding, ...]:
    required_goals = set(goal_unit_ids)
    return tuple(
        binding
        for binding in catalog.bindings.values()
        if binding.runtime_node_id != exclude_runtime_node
        and binding.usage == "input"
        and required_goals.issubset(binding.visible_goal_unit_ids)
        and _binding_accepts_c3_source(binding, source)
    )


def _same_source_object(
    direct: ProblemPlanningSourceBinding,
    supporting: ProblemPlanningSourceBinding,
) -> bool:
    direct_ids = {
        item.math_object_id
        for item in direct.typed_sources
        if item.math_object_id is not None
    }
    supporting_ids = {
        item.math_object_id
        for item in supporting.typed_sources
        if item.math_object_id is not None
    }
    return bool(direct_ids & supporting_ids)


def _bind_plan_goals(
    catalog: ProblemPlanningBindingCatalog,
    plan: FunctionalPlan,
    *,
    require_goal_reachable: bool,
    additional_dependencies: Mapping[str, Sequence[str]] | None,
    authored_goal_unit_ids: Mapping[str, Sequence[str]] | None,
) -> ProblemPlanGoalBindings:
    calls = {call.call_id: call for call in plan.calls}
    scopes = {
        call.call_id: scope.scope_id
        for scope in plan.scopes
        for call in scope.calls
    }
    answer_to_goal = {
        (ref_key.local_ref, ref_key.kind): goal_id
        for goal_id, ref_key in catalog.goal_answer_refs.items()
    }
    goals_by_call: dict[str, set[str]] = {call_id: set() for call_id in calls}
    dependencies: dict[str, set[str]] = {call_id: set() for call_id in calls}
    non_propagating_dependencies: set[tuple[str, str]] = set()
    for consumer_id, producer_ids in (additional_dependencies or {}).items():
        if consumer_id not in dependencies:
            continue
        dependencies[consumer_id].update(
            producer_id for producer_id in producer_ids if producer_id in calls
        )
    issues: list[ProblemPlanBindingIssue] = []
    for call_id, goal_ids in (authored_goal_unit_ids or {}).items():
        if call_id not in calls:
            continue
        visible_scope_ids = {
            goal_id: self_scopes
            for goal_id, self_scopes in catalog.goal_visible_scope_ids.items()
        }
        for goal_id in goal_ids:
            if (
                goal_id not in catalog.goal_input_refs
                or scopes.get(call_id) not in visible_scope_ids.get(goal_id, ())
            ):
                issues.append(
                    ProblemPlanBindingIssue(
                        "planner.problem_scope_visibility_drift",
                        "authored call Goal is outside its execution scope",
                        call_id=call_id,
                        scope_id=scopes.get(call_id),
                        details={"goal_unit_id": goal_id},
                    )
                )
                continue
            goals_by_call[call_id].add(goal_id)
    for call in calls.values():
        for values in call.args.values():
            for value in values:
                if isinstance(value, CallResultRef):
                    dependencies[call.call_id].add(value.from_call)
                    if isinstance(value, PublishedGoalCallResultRef):
                        non_propagating_dependencies.add(
                            (call.call_id, value.from_call)
                        )
        for binding in call.return_bindings.values():
            if binding.kind != "answer":
                continue
            goal_id = answer_to_goal.get((binding.ref, binding.kind))
            if goal_id is None:
                issues.append(
                    ProblemPlanBindingIssue(
                        "functional.answer_ref_goal_mismatch",
                        f"answer ref {binding.ref!r} is not owned by a GoalView",
                        call_id=call.call_id,
                        scope_id=scopes.get(call.call_id),
                        details={"semantic_ref": binding.to_payload()},
                    )
                )
                continue
            goals_by_call[call.call_id].add(goal_id)
    changed = True
    while changed:
        changed = False
        for consumer_id, producer_ids in dependencies.items():
            for producer_id in producer_ids:
                if (
                    consumer_id,
                    producer_id,
                ) in non_propagating_dependencies:
                    continue
                if producer_id not in goals_by_call:
                    continue
                before = len(goals_by_call[producer_id])
                goals_by_call[producer_id].update(goals_by_call[consumer_id])
                changed = changed or len(goals_by_call[producer_id]) != before

    result: dict[str, ProblemCallGoalBinding] = {}
    for call_id, call in calls.items():
        reachable = tuple(sorted(goals_by_call[call_id]))
        candidate_goals = tuple(
            sorted(
                goal_id
                for goal_id, visible_scopes in catalog.goal_visible_scope_ids.items()
                if scopes.get(call_id) in visible_scopes
            )
        )
        effective_goals = reachable or candidate_goals
        if not effective_goals:
            issues.append(
                ProblemPlanBindingIssue(
                    "functional.call_goal_unresolved",
                    "call is not anchored to any GoalView",
                    call_id=call_id,
                    scope_id=scopes.get(call_id),
                    details={
                        "repair_action": "connect_to_goal_or_remove_call",
                        "repair_call_ids": [call_id],
                        "repair_guidance": (
                            "If this computation is required, connect one of "
                            "its returns to a downstream Goal-producing call "
                            "with CallResultRef. Otherwise remove the call."
                        ),
                    },
                )
            )
            allowed: set[ScopedSourceRefKey] = set()
        else:
            allowed_sets = [
                set(catalog.goal_input_refs[goal_id])
                for goal_id in effective_goals
            ]
            allowed = set.intersection(*allowed_sets)
        if require_goal_reachable and not reachable:
            issues.append(
                ProblemPlanBindingIssue(
                    "functional.call_goal_unresolved",
                    "retained call does not contribute to a required Goal",
                    call_id=call_id,
                    scope_id=scopes.get(call_id),
                    details={
                        "repair_action": "connect_to_goal_or_remove_call",
                        "repair_call_ids": [call_id],
                        "repair_guidance": (
                            "A retained call must reach an answer producer "
                            "through CallResultRef dependencies. Connect its "
                            "return to that chain or delete the unused call."
                        ),
                    },
                )
            )
        for arg_name, values in call.args.items():
            for value in values:
                if not isinstance(value, SemanticRef):
                    continue
                try:
                    source_binding = catalog.resolve_input_binding(
                        scope_id=scopes[call_id],
                        local_ref=value.ref,
                        goal_unit_ids=effective_goals,
                    )
                except ProblemPlanningBindingError:
                    source_binding = None
                if (
                    source_binding is None
                    or source_binding.semantic_ref.kind != value.kind
                    or source_binding.scoped_key not in allowed
                ):
                    issues.append(
                        ProblemPlanBindingIssue(
                            "functional.semantic_ref_not_visible_for_goal",
                            (
                                f"SemanticRef {value.ref!r} is not visible to all "
                                f"Goals served by call {call_id!r}"
                            ),
                            call_id=call_id,
                            scope_id=scopes.get(call_id),
                            details={
                                "arg_name": arg_name,
                                "semantic_ref": value.to_payload(),
                                "goal_unit_ids": list(effective_goals),
                            },
                        )
                    )
        for return_name, binding in call.return_bindings.items():
            if binding.kind == "answer":
                goal_id = answer_to_goal.get((binding.ref, binding.kind))
                if goal_id is not None and goal_id not in effective_goals:
                    issues.append(
                        ProblemPlanBindingIssue(
                            "functional.answer_ref_goal_mismatch",
                            "answer binding is outside the call Goal closure",
                            call_id=call_id,
                            scope_id=scopes.get(call_id),
                            details={"return_name": return_name},
                        )
                    )
                continue
            try:
                return_target = catalog.resolve_input_binding(
                    scope_id=scopes[call_id],
                    local_ref=binding.ref,
                    goal_unit_ids=effective_goals,
                )
            except ProblemPlanningBindingError:
                return_target = None
            if (
                return_target is not None
                and return_target.semantic_ref.kind == binding.kind
                and return_target.scoped_key in allowed
            ):
                continue
            issues.append(
                ProblemPlanBindingIssue(
                    "functional.semantic_ref_not_visible_for_goal",
                    (
                        f"return target {binding.ref!r} is not visible to all "
                        f"Goals served by call {call_id!r}"
                    ),
                    call_id=call_id,
                    scope_id=scopes.get(call_id),
                    details={"return_name": return_name},
                )
            )
        result[call_id] = ProblemCallGoalBinding(
            call_id=call_id,
            goal_unit_ids=reachable,
            effective_goal_unit_ids=effective_goals,
            allowed_ref_keys=tuple(
                sorted(allowed, key=ScopedSourceRefKey.sort_key)
            ),
        )
    return ProblemPlanGoalBindings(result, tuple(issues))


def _error(
    code: str,
    path: str,
    message: str,
    *,
    retryable: bool = False,
    details: Mapping[str, Any] | None = None,
) -> ProblemPlanningBindingError:
    return ProblemPlanningBindingError(
        code,
        path,
        message,
        retryable=retryable,
        details=details,
    )


__all__ = [
    "FUNCTIONAL_PROBLEM_BINDING_CONTEXT_CONTRACT",
    "PROBLEM_PLANNING_BINDING_CATALOG_CONTRACT",
    "FunctionalProblemBindingContext",
    "FunctionalProblemInputBinding",
    "FunctionalProblemReturnBinding",
    "ProblemCallGoalBinding",
    "ProblemPlanBindingIssue",
    "ProblemPlanGoalBindings",
    "ProblemPlanningBindingCatalog",
    "ProblemPlanningBindingCatalogBuilder",
    "ProblemPlanningBindingError",
    "ProblemPlanningSourceBinding",
    "ProblemTypedSourceIdentity",
    "build_functional_problem_binding_context",
    "functional_problem_binding_context_schema",
    "problem_planning_binding_catalog_schema",
]
