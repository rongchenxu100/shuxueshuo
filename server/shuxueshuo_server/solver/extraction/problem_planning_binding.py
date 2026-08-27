"""Bind F5-B source authority to typed Functional runtime identity."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal, Mapping, Sequence

from shuxueshuo_server.solver.contracts import (
    EntityIdentitySourceSpec,
    PreviousOutputIdentityDerivationSpec,
    SourceObjectIdentityDerivationSpec,
)
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
FUNCTIONAL_PROBLEM_BINDING_LEDGER_CONTRACT = (
    "functional-problem-binding-ledger/v1"
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
    functional_direct_sources = [
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
            )
        ]
    functional_call_result_source = {
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
    functional_source = {
        "oneOf": [
            *functional_direct_sources,
            functional_call_result_source,
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
                    "return_allocation",
                ]
            },
            "selection_policy": {
                "enum": ["exact", "latest", "identity_only"]
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
    relation_binding = {
        "type": "object",
        "required": [
            "call_id",
            "method_id",
            "relation_kind",
            "point_arg_name",
            "point_item_index",
            "curve_arg_name",
            "semantic_ref",
            "runtime_node_id",
            "source_unit_ids",
            "condition_id",
            "owner_scope_id",
            "point_math_object_id",
            "curve_math_object_id",
        ],
        "properties": {
            "call_id": nonempty_string,
            "method_id": nonempty_string,
            "relation_kind": {"const": "point_on_curve"},
            "point_arg_name": nonempty_string,
            "point_item_index": {"type": "integer", "minimum": 0},
            "curve_arg_name": nonempty_string,
            "semantic_ref": {"$ref": "#/$defs/semantic_ref"},
            "runtime_node_id": nonempty_string,
            "source_unit_ids": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": nonempty_string,
            },
            "condition_id": nonempty_string,
            "owner_scope_id": nonempty_string,
            "point_math_object_id": {"$ref": "#/$defs/math_object_id"},
            "curve_math_object_id": {"$ref": "#/$defs/math_object_id"},
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
            "relation_bindings",
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
            "relation_bindings": {
                "type": "array",
                "items": relation_binding,
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
            "relation_binding": relation_binding,
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
class FunctionalProblemRelationBinding:
    call_id: str
    method_id: str
    relation_kind: str
    point_arg_name: str
    point_item_index: int
    curve_arg_name: str
    semantic_ref: SemanticRef
    runtime_node_id: str
    source_unit_ids: tuple[str, ...]
    condition_id: str
    owner_scope_id: str
    point_math_object_id: MathObjectId
    curve_math_object_id: MathObjectId

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "method_id": self.method_id,
            "relation_kind": self.relation_kind,
            "point_arg_name": self.point_arg_name,
            "point_item_index": self.point_item_index,
            "curve_arg_name": self.curve_arg_name,
            "semantic_ref": self.semantic_ref.to_payload(),
            "runtime_node_id": self.runtime_node_id,
            "source_unit_ids": list(self.source_unit_ids),
            "condition_id": self.condition_id,
            "owner_scope_id": self.owner_scope_id,
            "point_math_object_id": self.point_math_object_id.to_payload(),
            "curve_math_object_id": self.curve_math_object_id.to_payload(),
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
    relation_bindings: tuple[FunctionalProblemRelationBinding, ...]
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

    def relations_for_call(
        self,
        call_id: str,
    ) -> tuple[FunctionalProblemRelationBinding, ...]:
        return tuple(
            item for item in self.relation_bindings if item.call_id == call_id
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
                "relations": [
                    item.to_payload()
                    for item in self.relations_for_call(call_id)
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
            for source_units in (
                *(
                    item.source_unit_ids
                    for item in self.inputs_for_call(call_id)
                    if item.source_kind == "problem_source"
                ),
                *(
                    item.source_unit_ids
                    for item in self.relations_for_call(call_id)
                ),
            )
            for source_unit_id in source_units
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
            "relation_bindings": [
                item.to_payload() for item in self.relation_bindings
            ],
            "return_bindings": [
                item.to_payload() for item in self.return_bindings
            ],
            "binding_signature": self.binding_signature,
        }

    def call_binding(
        self,
        call_id: str,
        *,
        status: Literal["pending_macro", "finalized"] = "finalized",
    ) -> "FunctionalProblemCallBinding":
        goal_ids = self.call_goal_bindings.get(call_id)
        if not goal_ids:
            raise _error(
                "functional.call_goal_unresolved",
                f"$.calls[{call_id!r}]",
                "call has no Goal authority",
            )
        return FunctionalProblemCallBinding(
            planning_context_id=self.planning_context_id,
            problem_revision_id=self.problem_revision_id,
            problem_semantic_hash=self.problem_semantic_hash,
            planner_state_context_id=self.planner_state_context_id,
            call_id=call_id,
            goal_unit_ids=tuple(goal_ids),
            input_bindings=self.inputs_for_call(call_id),
            relation_bindings=self.relations_for_call(call_id),
            return_bindings=self.returns_for_call(call_id),
            status=status,
        )


@dataclass(frozen=True)
class FunctionalProblemCallBinding:
    """One finalized or pending F5-C call authority."""

    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    planner_state_context_id: str
    call_id: str
    goal_unit_ids: tuple[str, ...]
    input_bindings: tuple[FunctionalProblemInputBinding, ...]
    relation_bindings: tuple[FunctionalProblemRelationBinding, ...]
    return_bindings: tuple[FunctionalProblemReturnBinding, ...]
    status: Literal["pending_macro", "finalized"] = "finalized"
    macro_preparation_signature: str | None = None
    macro_search_signature: str | None = None
    authored_roles: Mapping[str, str] = field(default_factory=dict)
    chosen_roles: Mapping[str, str] = field(default_factory=dict)
    binding_signature: str = field(init=False)

    def __post_init__(self) -> None:
        if self.status == "pending_macro" and self.macro_preparation_signature:
            raise ValueError("pending Macro binding cannot have a winner signature")
        if self.status == "pending_macro" and self.macro_search_signature:
            raise ValueError("pending Macro binding cannot have a search signature")
        if self.status == "finalized" and self.chosen_roles and not (
            self.macro_preparation_signature
        ):
            raise ValueError("chosen Macro roles require preparation authority")
        object.__setattr__(
            self,
            "goal_unit_ids",
            tuple(sorted(set(self.goal_unit_ids))),
        )
        object.__setattr__(
            self,
            "input_bindings",
            tuple(
                sorted(
                    self.input_bindings,
                    key=lambda item: (item.arg_name, item.item_index),
                )
            ),
        )
        object.__setattr__(
            self,
            "relation_bindings",
            tuple(
                sorted(
                    self.relation_bindings,
                    key=lambda item: (
                        item.method_id,
                        item.point_arg_name,
                        item.point_item_index,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "return_bindings",
            tuple(sorted(self.return_bindings, key=lambda item: item.return_name)),
        )
        object.__setattr__(
            self,
            "authored_roles",
            MappingProxyType(dict(sorted(self.authored_roles.items()))),
        )
        object.__setattr__(
            self,
            "chosen_roles",
            MappingProxyType(dict(sorted(self.chosen_roles.items()))),
        )
        object.__setattr__(
            self,
            "binding_signature",
            stable_hash(self.authority_payload(include_signature=False)),
        )

    def authority_payload(self, *, include_signature: bool = True) -> dict[str, Any]:
        payload = {
            "planning_context_id": self.planning_context_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "planner_state_context_id": self.planner_state_context_id,
            "call_id": self.call_id,
            "goal_unit_ids": list(self.goal_unit_ids),
            "status": self.status,
            "input_bindings": [item.to_payload() for item in self.input_bindings],
            "relation_bindings": [
                item.to_payload() for item in self.relation_bindings
            ],
            "return_bindings": [item.to_payload() for item in self.return_bindings],
            "macro_preparation_signature": self.macro_preparation_signature,
            "macro_search_signature": self.macro_search_signature,
            "authored_roles": dict(self.authored_roles),
            "chosen_roles": dict(self.chosen_roles),
        }
        if include_signature:
            payload["binding_signature"] = self.binding_signature
        return payload

    def source_provenance(self) -> ProblemCallSourceProvenance:
        if self.status != "finalized":
            raise _error(
                "planner.problem_call_binding_pending",
                f"$.calls[{self.call_id!r}]",
                "runtime-search call has no finalized winner binding",
            )
        source_unit_ids = {
            source_id
            for sources in (
                *(
                    item.source_unit_ids
                    for item in self.input_bindings
                    if item.source_kind == "problem_source"
                ),
                *(item.source_unit_ids for item in self.relation_bindings),
            )
            for source_id in sources
        }
        return ProblemCallSourceProvenance(
            planning_context_id=self.planning_context_id,
            problem_revision_id=self.problem_revision_id,
            problem_semantic_hash=self.problem_semantic_hash,
            canonical_call_id=self.call_id,
            goal_unit_ids=self.goal_unit_ids,
            input_source_unit_ids=tuple(sorted(source_unit_ids)),
            call_binding_signature=self.binding_signature,
            macro_search_signature=self.macro_search_signature,
            macro_role_resolutions=tuple(
                (
                    role,
                    self.authored_roles.get(role),
                    chosen_ref,
                )
                for role, chosen_ref in self.chosen_roles.items()
            ),
        )


@dataclass(frozen=True)
class FunctionalProblemBindingDraft:
    planning_context_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    planner_state_context_id: str
    calls: Mapping[str, FunctionalProblemCallBinding]
    catalog_signature: str
    source_catalog: Any | None = field(default=None, repr=False, compare=False)
    draft_signature: str = field(init=False)

    def __post_init__(self) -> None:
        calls = MappingProxyType(dict(sorted(self.calls.items())))
        object.__setattr__(self, "calls", calls)
        object.__setattr__(
            self,
            "draft_signature",
            stable_hash(
                {
                    "planning_context_id": self.planning_context_id,
                    "problem_revision_id": self.problem_revision_id,
                    "problem_semantic_hash": self.problem_semantic_hash,
                    "planner_state_context_id": self.planner_state_context_id,
                    "catalog_signature": self.catalog_signature,
                    "calls": {
                        key: value.authority_payload()
                        for key, value in calls.items()
                    },
                }
            ),
        )


@dataclass(frozen=True)
class FunctionalProblemBindingLedger:
    """Immutable per-call finalization ledger behind the v1 aggregate payload."""

    draft: FunctionalProblemBindingDraft
    calls: Mapping[str, FunctionalProblemCallBinding]
    schema_version: str = FUNCTIONAL_PROBLEM_BINDING_LEDGER_CONTRACT
    ledger_signature: str = field(init=False)

    def __post_init__(self) -> None:
        calls = MappingProxyType(dict(sorted(self.calls.items())))
        if set(calls) != set(self.draft.calls):
            raise ValueError("F5-C ledger and draft contain different calls")
        object.__setattr__(self, "calls", calls)
        object.__setattr__(
            self,
            "ledger_signature",
            stable_hash(
                {
                    "schema_version": self.schema_version,
                    "draft_signature": self.draft.draft_signature,
                    "calls": {
                        key: value.authority_payload()
                        for key, value in calls.items()
                    },
                }
            ),
        )

    @classmethod
    def from_context(
        cls,
        context: FunctionalProblemBindingContext,
        *,
        pending_macro_call_ids: Sequence[str] = (),
        catalog: "ProblemPlanningBindingCatalog | None" = None,
    ) -> "FunctionalProblemBindingLedger":
        pending = frozenset(pending_macro_call_ids)
        calls = {
            call_id: context.call_binding(
                call_id,
                status=("pending_macro" if call_id in pending else "finalized"),
            )
            for call_id in context.call_goal_bindings
        }
        draft = FunctionalProblemBindingDraft(
            planning_context_id=context.planning_context_id,
            problem_revision_id=context.problem_revision_id,
            problem_semantic_hash=context.problem_semantic_hash,
            planner_state_context_id=context.planner_state_context_id,
            calls=calls,
            catalog_signature=(
                catalog.binding_signature
                if catalog is not None
                else context.binding_signature
            ),
            source_catalog=catalog,
        )
        return cls(draft=draft, calls=calls)

    def call_binding(self, call_id: str) -> FunctionalProblemCallBinding:
        try:
            return self.calls[call_id]
        except KeyError as exc:
            raise _error(
                "functional.call_goal_unresolved",
                f"$.calls[{call_id!r}]",
                "F5-C ledger has no call binding",
            ) from exc

    def finalize_macro(
        self,
        call_id: str,
        *,
        preparation_authority: Any,
    ) -> "FunctionalProblemBindingLedger":
        current = self.call_binding(call_id)
        if current.status != "pending_macro":
            raise _error(
                "planner.macro_binding_finalization_invalid",
                f"$.calls[{call_id!r}]",
                "only pending runtime-search calls can be finalized",
            )
        if preparation_authority.call_id != call_id:
            raise _error(
                "planner.macro_binding_finalization_invalid",
                f"$.calls[{call_id!r}]",
                "Macro preparation belongs to another call",
            )
        if (
            preparation_authority.planning_context_id
            != current.planning_context_id
            or preparation_authority.problem_revision_id
            != current.problem_revision_id
            or preparation_authority.problem_semantic_hash
            != current.problem_semantic_hash
        ):
            raise _error(
                "planner.problem_revision_drift",
                f"$.calls[{call_id!r}]",
                "Macro preparation and F5-C draft identify different Problem authority",
            )
        chosen_roles = dict(preparation_authority.winner.candidate.roles)
        catalog = self.draft.source_catalog
        if not isinstance(catalog, ProblemPlanningBindingCatalog):
            raise _error(
                "planner.macro_binding_finalization_invalid",
                f"$.calls[{call_id!r}]",
                "F5-C draft has no immutable source catalog",
            )
        finalized_inputs = _finalize_macro_role_inputs(
            current,
            chosen_roles=chosen_roles,
            catalog=catalog,
        )
        finalized = replace(
            current,
            status="finalized",
            input_bindings=finalized_inputs,
            macro_preparation_signature=(
                preparation_authority.preparation_signature
            ),
            macro_search_signature=(
                preparation_authority.search_report.search_signature
            ),
            authored_roles=dict(preparation_authority.authored_roles),
            chosen_roles=chosen_roles,
        )
        calls = dict(self.calls)
        calls[call_id] = finalized
        return FunctionalProblemBindingLedger(draft=self.draft, calls=calls)

    def aggregate_context(self, *, require_complete: bool = True) -> FunctionalProblemBindingContext:
        if require_complete:
            pending = [
                call_id
                for call_id, binding in self.calls.items()
                if binding.status != "finalized"
            ]
            if pending:
                raise _error(
                    "planner.problem_call_binding_pending",
                    "$.calls",
                    f"pending F5-C call bindings remain: {pending}",
                )
        inputs = tuple(
            item for binding in self.calls.values() for item in binding.input_bindings
        )
        relations = tuple(
            item
            for binding in self.calls.values()
            for item in binding.relation_bindings
        )
        returns = tuple(
            item
            for binding in self.calls.values()
            for item in binding.return_bindings
        )
        call_goals = {
            call_id: binding.goal_unit_ids
            for call_id, binding in self.calls.items()
        }
        payload = {
            "schema_version": FUNCTIONAL_PROBLEM_BINDING_CONTEXT_CONTRACT,
            "planning_context_id": self.draft.planning_context_id,
            "problem_revision_id": self.draft.problem_revision_id,
            "problem_semantic_hash": self.draft.problem_semantic_hash,
            "planner_state_context_id": self.draft.planner_state_context_id,
            "call_goal_bindings": {
                key: list(value) for key, value in sorted(call_goals.items())
            },
            "input_bindings": [item.to_payload() for item in inputs],
            "relation_bindings": [item.to_payload() for item in relations],
            "return_bindings": [item.to_payload() for item in returns],
        }
        return FunctionalProblemBindingContext(
            planning_context_id=self.draft.planning_context_id,
            problem_revision_id=self.draft.problem_revision_id,
            problem_semantic_hash=self.draft.problem_semantic_hash,
            planner_state_context_id=self.draft.planner_state_context_id,
            call_goal_bindings=call_goals,
            input_bindings=inputs,
            relation_bindings=relations,
            return_bindings=returns,
            binding_signature=stable_hash(payload),
        )


def _finalize_macro_role_inputs(
    call: FunctionalProblemCallBinding,
    *,
    chosen_roles: Mapping[str, str],
    catalog: "ProblemPlanningBindingCatalog",
) -> tuple[FunctionalProblemInputBinding, ...]:
    result = list(call.input_bindings)
    by_key = {(item.arg_name, item.item_index): index for index, item in enumerate(result)}
    for role, chosen_ref in sorted(chosen_roles.items()):
        source = _problem_source_binding_for_runtime_ref(
            catalog,
            chosen_ref,
            goal_unit_ids=call.goal_unit_ids,
        )
        replacement = FunctionalProblemInputBinding(
            call_id=call.call_id,
            arg_name=role,
            item_index=0,
            source_kind="problem_source",
            selection_policy=(
                "exact"
                if source.typed_sources
                and min(
                    source.typed_sources,
                    key=lambda item: {
                        "state_version": 0,
                        "math_object": 1,
                        "condition": 2,
                        "answer_target": 3,
                    }[item.kind],
                ).kind
                == "state_version"
                else "identity_only"
            ),
            semantic_ref=source.semantic_ref,
            runtime_node_id=source.runtime_node_id,
            source_unit_ids=source.source_unit_ids,
            typed_source=_functional_source_for_problem_binding(source),
        )
        key = (role, 0)
        if key in by_key:
            result[by_key[key]] = replacement
        else:
            result.append(replacement)
    return tuple(result)


def _problem_source_binding_for_runtime_ref(
    catalog: "ProblemPlanningBindingCatalog",
    chosen_ref: str,
    *,
    goal_unit_ids: Sequence[str],
) -> ProblemPlanningSourceBinding:
    local = chosen_ref.rsplit(":", 1)[-1]
    candidates = tuple(
        binding
        for binding in catalog.bindings.values()
        if (
            binding.runtime_node_id == chosen_ref
            or binding.semantic_ref.ref == chosen_ref
            or binding.semantic_ref.ref == local
            or any(
                item.math_object_id is not None
                and item.math_object_id.value == chosen_ref
                for item in binding.typed_sources
            )
        )
        and set(goal_unit_ids).intersection(binding.visible_goal_unit_ids)
    )
    unique = {
        (item.runtime_node_id, item.semantic_ref.ref): item
        for item in candidates
    }
    if len(unique) != 1:
        raise _error(
            "planner.macro_binding_finalization_invalid",
            "$.winner.roles",
            f"chosen Macro role {chosen_ref!r} has {len(unique)} F5-C sources",
        )
    return next(iter(unique.values()))


def _functional_source_for_problem_binding(
    binding: ProblemPlanningSourceBinding,
) -> FunctionalArgSourceIdentity:
    priority = {"state_version": 0, "math_object": 1, "condition": 2, "answer_target": 3}
    selected = min(binding.typed_sources, key=lambda item: priority[item.kind])
    if selected.kind == "state_version" and selected.state_version_id is not None:
        return FunctionalArgSourceIdentity(
            kind="state_version",
            state_version_id=selected.state_version_id,
        )
    if selected.kind == "condition" and selected.condition_id is not None:
        return FunctionalArgSourceIdentity(
            kind="condition",
            condition_id=selected.condition_id,
        )
    if selected.math_object_id is not None:
        return FunctionalArgSourceIdentity(
            kind="math_object",
            math_object_id=selected.math_object_id,
        )
    raise _error(
        "planner.macro_binding_finalization_invalid",
        "$.winner.roles",
        "chosen Macro role has no executable typed source",
    )

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

    def verify_authority(self) -> None:
        payload = self.authority_payload()
        signature = str(payload.pop("binding_signature"))
        if stable_hash(payload) != signature:
            raise _error(
                "planner.problem_source_binding_drift",
                "$.binding_signature",
                "binding catalog content no longer matches its authority signature",
            )

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
        self.verify_authority()
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
    logical_bindings = {
        (
            item.key.call_id,
            item.key.arg_name,
            item.key.item_index,
        ): item
        for item in functional_binding_context.bindings
    }
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
            input_path = (
                f"$.calls[{call_id!r}].args"
                f"[{binding.key.arg_name!r}]"
                f"[{binding.key.item_index}]"
            )
            if binding.source.kind == "call_result":
                _audit_implicit_same_object_call_result(
                    source_binding=source_binding,
                    source=binding.source,
                    consumer_call_id=call_id,
                    consumer_goal_binding=call_goals,
                    reconciled_calls=reconciled,
                    goal_bindings=goal_bindings,
                    catalog=catalog,
                    path=input_path,
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
            computed_source = _audit_computed_state_source(
                source_binding=source_binding,
                typed_source=binding.source,
                consumer_call_id=call_id,
                consumer_goal_binding=call_goals,
                reconciled_calls=reconciled,
                goal_bindings=goal_bindings,
                catalog=catalog,
                path=input_path,
            )
            if computed_source is not None:
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
            effective_semantic_ref = wire_ref
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
                    reconciled_call = reconciled.get(call_id)
                    searchable_roles = (
                        dict(reconciled_call.authored_macro_roles)
                        if reconciled_call is not None
                        else {}
                    )
                    if binding.key.arg_name not in searchable_roles:
                        raise _error(
                            "planner.problem_source_binding_drift",
                            (
                                f"$.calls[{call_id!r}].args"
                                f"[{binding.key.arg_name!r}]"
                            ),
                            "C3 selected a state for a different source object",
                        )
                    if supporting.scoped_key not in call_goals.allowed_ref_keys:
                        raise _error(
                            "functional.semantic_ref_not_visible_for_goal",
                            (
                                f"$.calls[{call_id!r}].args"
                                f"[{binding.key.arg_name!r}]"
                            ),
                            "Macro search selected an object outside Goal authority",
                        )
                    source_binding = supporting
                    source_units = set(supporting.source_unit_ids)
                    effective_semantic_ref = supporting.semantic_ref
                else:
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
                    semantic_ref=effective_semantic_ref,
                    runtime_node_id=source_binding.runtime_node_id,
                    source_unit_ids=tuple(sorted(source_units)),
                    typed_source=binding.source,
                )
            )
            continue
        if (
            isinstance(wire_ref, CallResultRef)
            and binding.source.kind == "state_version"
        ):
            producer = reconciled.get(wire_ref.from_call)
            allocation = next(
                (
                    item
                    for item in (producer.returns if producer is not None else ())
                    if item.return_name == wire_ref.return_name
                ),
                None,
            )
            if (
                allocation is None
                or allocation.selected_version_id
                != binding.source.state_version_id
            ):
                raise _error(
                    "planner.problem_source_binding_drift",
                    f"$.calls[{call_id!r}].args",
                    (
                        "CallResultRef does not resolve to the exact typed "
                        "StateVersion selected by Method input authority"
                    ),
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
        input_path = (
            f"$.calls[{call_id!r}].args"
            f"[{binding.key.arg_name!r}]"
        )
        declaration = binding.input_binding
        if (
            declaration is not None
            and isinstance(
                declaration.derivation,
                PreviousOutputIdentityDerivationSpec,
            )
        ):
            reconciled_call = reconciled.get(call_id)
            allocation = next(
                (
                    item
                    for item in (
                        reconciled_call.returns
                        if reconciled_call is not None
                        else ()
                    )
                    if item.return_name
                    == declaration.derivation.output_name
                ),
                None,
            )
            allocation_object_id = (
                allocation.math_object_id
                if allocation is not None
                else None
            )
            if (
                allocation is None
                or allocation_object_id is None
                or binding.source.kind != "math_object"
                or binding.source.math_object_id != allocation_object_id
            ):
                raise _error(
                    "planner.method_input_view_authority_drift",
                    input_path,
                    "output identity differs from its canonical return allocation",
                )
            inputs.append(
                FunctionalProblemInputBinding(
                    call_id=call_id,
                    arg_name=binding.key.arg_name,
                    item_index=binding.key.item_index,
                    source_kind="return_allocation",
                    selection_policy="identity_only",
                    semantic_ref=allocation.bound_ref,
                    runtime_node_id=(
                        allocation.object_ref
                        or allocation_object_id.value
                    ),
                    typed_source=binding.source,
                )
            )
            continue
        if (
            binding.binding_authority == "compiler"
            and binding.source.kind == "math_object"
            and binding.source.math_object_id is not None
            and declaration is not None
            and isinstance(declaration.source, EntityIdentitySourceSpec)
            and binding.key.arg_name == "target"
            and declaration.source.arg_name == "target"
        ):
            shared_allocations = tuple(
                allocation
                for consumer_call_id, consumer_call in wire_calls.items()
                if any(
                    isinstance(ref, CallResultRef)
                    and ref.from_call == call_id
                    for refs in consumer_call.args.values()
                    for ref in refs
                )
                for allocation in (
                    reconciled.get(consumer_call_id).returns
                    if reconciled.get(consumer_call_id) is not None
                    else ()
                )
                if allocation.math_object_id == binding.source.math_object_id
            )
            unique_allocations = {
                (item.call_id, item.return_name): item
                for item in shared_allocations
            }
            if len(unique_allocations) > 1:
                raise _error(
                    "planner.method_input_view_authority_drift",
                    input_path,
                    "relation output maps to multiple Point return allocations",
                )
            if unique_allocations:
                allocation = next(iter(unique_allocations.values()))
                inputs.append(
                    FunctionalProblemInputBinding(
                        call_id=call_id,
                        arg_name=binding.key.arg_name,
                        item_index=binding.key.item_index,
                        source_kind="return_allocation",
                        selection_policy="identity_only",
                        semantic_ref=allocation.bound_ref,
                        runtime_node_id=(
                            allocation.object_ref
                            or binding.source.math_object_id.value
                        ),
                        typed_source=binding.source,
                    )
                )
                continue
        if (
            declaration is not None
            and isinstance(
                declaration.derivation,
                SourceObjectIdentityDerivationSpec,
            )
        ):
            try:
                derived_object_binding = _authority_for_c3_source(
                    catalog,
                    binding.source,
                    goal_unit_ids=call_goals.effective_goal_unit_ids,
                    path=input_path,
                )
            except ProblemPlanningBindingError as exc:
                if (
                    exc.code != "planner.problem_source_binding_unresolved"
                    or "maps to 0" not in exc.message
                ):
                    raise
                derived_object_binding = None
            if derived_object_binding is not None:
                inputs.append(
                    FunctionalProblemInputBinding(
                        call_id=call_id,
                        arg_name=binding.key.arg_name,
                        item_index=binding.key.item_index,
                        source_kind="problem_source",
                        selection_policy=binding.selection_policy,
                        semantic_ref=derived_object_binding.semantic_ref,
                        runtime_node_id=derived_object_binding.runtime_node_id,
                        source_unit_ids=derived_object_binding.source_unit_ids,
                        typed_source=binding.source,
                    )
                )
                continue
            upstream = logical_bindings.get(
                (
                    call_id,
                    declaration.derivation.source_input,
                    binding.key.item_index,
                )
            )
            if upstream is None:
                raise _error(
                    "planner.method_input_view_authority_missing",
                    input_path,
                    "source-object identity derivation has no upstream binding",
                )
            computed_upstream = _call_result_source_for_exact_state(
                upstream.source,
                consumer_call_id=call_id,
                reconciled_calls=reconciled,
                path=input_path,
            )
            if computed_upstream is not None:
                source_binding = _problem_binding_for_state_object(
                    catalog,
                    upstream.source,
                    goal_unit_ids=call_goals.effective_goal_unit_ids,
                    path=input_path,
                )
                _audit_implicit_same_object_call_result(
                    source_binding=source_binding,
                    source=computed_upstream,
                    consumer_call_id=call_id,
                    consumer_goal_binding=call_goals,
                    reconciled_calls=reconciled,
                    goal_bindings=goal_bindings,
                    catalog=catalog,
                    path=input_path,
                )
                inputs.append(
                    FunctionalProblemInputBinding(
                        call_id=call_id,
                        arg_name=binding.key.arg_name,
                        item_index=binding.key.item_index,
                        source_kind="call_result",
                        selection_policy=binding.selection_policy,
                        semantic_ref=source_binding.semantic_ref,
                        runtime_node_id=source_binding.runtime_node_id,
                        typed_source=binding.source,
                    )
                )
                continue
            source_binding = _authority_for_c3_source(
                catalog,
                upstream.source,
                goal_unit_ids=call_goals.effective_goal_unit_ids,
                path=input_path,
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
            continue
        computed_source = _call_result_source_for_exact_state(
            binding.source,
            consumer_call_id=call_id,
            reconciled_calls=reconciled,
            path=input_path,
        )
        if computed_source is not None:
            source_binding = _problem_binding_for_state_object(
                catalog,
                binding.source,
                goal_unit_ids=call_goals.effective_goal_unit_ids,
                path=input_path,
            )
            _audit_implicit_same_object_call_result(
                source_binding=source_binding,
                source=computed_source,
                consumer_call_id=call_id,
                consumer_goal_binding=call_goals,
                reconciled_calls=reconciled,
                goal_bindings=goal_bindings,
                catalog=catalog,
                path=input_path,
            )
            inputs.append(
                FunctionalProblemInputBinding(
                    call_id=call_id,
                    arg_name=binding.key.arg_name,
                    item_index=binding.key.item_index,
                    source_kind="call_result",
                    selection_policy=binding.selection_policy,
                    semantic_ref=source_binding.semantic_ref,
                    runtime_node_id=source_binding.runtime_node_id,
                    typed_source=binding.source,
                )
            )
            continue
        source_binding = _authority_for_c3_source(
            catalog,
            binding.source,
            goal_unit_ids=call_goals.effective_goal_unit_ids,
            path=input_path,
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

    relations: list[FunctionalProblemRelationBinding] = []
    for relation in functional_binding_context.relation_bindings:
        call_goals = goal_bindings.calls.get(relation.call_id)
        if call_goals is None:
            raise _error(
                "functional.call_goal_unresolved",
                f"$.calls[{relation.call_id!r}].relations",
                "relation binding belongs to a call with no Goal authority",
            )
        if (
            relation.point_math_object_id is None
            or relation.curve_math_object_id is None
        ):
            raise _error(
                "planner.problem_source_binding_drift",
                f"$.calls[{relation.call_id!r}].relations",
                "relation binding has no exact Point/curve MathObject identity",
            )
        source_binding = _authority_for_c3_source(
            catalog,
            FunctionalArgSourceIdentity(
                kind="condition",
                condition_id=relation.condition_id,
            ),
            goal_unit_ids=call_goals.effective_goal_unit_ids,
            path=(
                f"$.calls[{relation.call_id!r}].args"
                f"[{relation.point_arg_name!r}]"
                f"[{relation.point_item_index}]"
            ),
        )
        if (
            source_binding.semantic_ref.ref != relation.condition_ref
            or source_binding.semantic_ref.kind
            != relation.condition_ref_kind
            or source_binding.owner_scope_id != relation.owner_scope_id
        ):
            raise _error(
                "planner.problem_source_binding_drift",
                f"$.calls[{relation.call_id!r}].relations",
                "resolved relation differs from F5-B Condition authority",
            )
        relations.append(
            FunctionalProblemRelationBinding(
                call_id=relation.call_id,
                method_id=relation.method_id,
                relation_kind=relation.relation_kind,
                point_arg_name=relation.point_arg_name,
                point_item_index=relation.point_item_index,
                curve_arg_name=relation.curve_arg_name,
                semantic_ref=source_binding.semantic_ref,
                runtime_node_id=source_binding.runtime_node_id,
                source_unit_ids=source_binding.source_unit_ids,
                condition_id=relation.condition_id,
                owner_scope_id=source_binding.owner_scope_id,
                point_math_object_id=relation.point_math_object_id,
                curve_math_object_id=relation.curve_math_object_id,
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
        canonical_return_refs = dict(wire_call.return_bindings)
        canonical_return_refs.update(
            {
                allocation.return_name: allocation.bound_ref
                for allocation in call.returns
                if allocation.bound_ref is not None
                and allocation.return_name not in canonical_return_refs
            }
        )
        for return_name, semantic_ref in canonical_return_refs.items():
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
    relation_bindings = tuple(
        sorted(
            relations,
            key=lambda item: (
                item.call_id,
                item.point_arg_name,
                item.point_item_index,
                item.curve_arg_name,
                item.condition_id,
            ),
        )
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
        "relation_bindings": [
            item.to_payload() for item in relation_bindings
        ],
        "return_bindings": [item.to_payload() for item in return_bindings],
    }
    return FunctionalProblemBindingContext(
        planning_context_id=catalog.planning_context_id,
        problem_revision_id=catalog.problem_revision_id,
        problem_semantic_hash=catalog.problem_semantic_hash,
        planner_state_context_id=catalog.planner_state_context_id,
        call_goal_bindings=call_goal_bindings,
        input_bindings=input_bindings,
        relation_bindings=relation_bindings,
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
    derived_entity_conditions = tuple(
        item
        for item in planner_state_context.state.conditions
        if node_kind == "entity"
        and item.canonical_handle is None
        and handle in dict(item.object_roles).get("point", ())
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
            for condition in derived_entity_conditions:
                result.append(
                    ProblemTypedSourceIdentity(
                        kind="condition",
                        runtime_type=condition.value_type,
                        condition_id=condition.condition_id,
                    )
                )
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
    call_order = _topologically_order_reconciled_calls(reconciled_calls)
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
        (
            producer_call_id
            if candidate.selected_version_id == allocation.selected_version_id
            else (candidate.canonical_producer_call_id or candidate_call_id),
            producer_return_name
            if candidate.selected_version_id == allocation.selected_version_id
            else candidate.return_name,
        )
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
    canonical_prior_results = tuple(dict.fromkeys(compatible_prior_results))
    if not canonical_prior_results or canonical_prior_results[-1] != (
        producer_call_id,
        producer_return_name,
    ):
        raise _error(
            "planner.problem_source_binding_drift",
            path,
            "implicit dynamic source is not the latest Goal-visible object state",
        )


def _topologically_order_reconciled_calls(
    reconciled_calls: Mapping[str, FunctionalCallReconciliation],
) -> tuple[str, ...]:
    """Recover execution order from exact resolved input authorities.

    Mapping order is authored Plan order, not execution order. Hidden
    Condition reads can place an authored-later call before an earlier
    consumer, so F5-C audits must follow the typed producer DAG.
    """

    authored_order = tuple(reconciled_calls)
    dependencies = {
        call_id: {
            value.source_call_id
            for values in call.resolved_args.values()
            for value in values
            if value.source_call_id in reconciled_calls
            and value.source_call_id != call_id
        }
        for call_id, call in reconciled_calls.items()
    }
    ordered: list[str] = []
    completed: set[str] = set()
    pending = set(authored_order)
    while pending:
        ready = tuple(
            call_id
            for call_id in authored_order
            if call_id in pending
            and dependencies[call_id].issubset(completed)
        )
        if not ready:
            raise _error(
                "planner.problem_source_binding_drift",
                "$.calls",
                "typed input authorities contain a cyclic producer graph",
            )
        ordered.extend(ready)
        completed.update(ready)
        pending.difference_update(ready)
    return tuple(ordered)


def _call_result_source_for_exact_state(
    source: FunctionalArgSourceIdentity,
    *,
    consumer_call_id: str,
    reconciled_calls: Mapping[str, FunctionalCallReconciliation],
    path: str,
) -> FunctionalArgSourceIdentity | None:
    """Resolve a pinned computed state to its unique earlier public return."""

    if source.kind != "state_version" or source.state_version_id is None:
        return None
    call_order = tuple(reconciled_calls)
    if consumer_call_id not in reconciled_calls:
        raise _error(
            "functional.call_goal_unresolved",
            path,
            f"consumer call {consumer_call_id!r} has no reconciliation authority",
        )
    prior_call_ids = call_order[: call_order.index(consumer_call_id)]
    matches = tuple(
        (
            call_id,
            allocation.return_name,
            allocation.canonical_producer_call_id or call_id,
        )
        for call_id in prior_call_ids
        for allocation in reconciled_calls[call_id].returns
        if allocation.selected_version_id == source.state_version_id
    )
    if not matches:
        return None
    canonical_matches = tuple(
        dict.fromkeys(
            (canonical_call_id, return_name)
            for _call_id, return_name, canonical_call_id in matches
        )
    )
    if len(canonical_matches) != 1:
        raise _error(
            "planner.problem_source_binding_drift",
            path,
            (
                "exact StateVersion maps to multiple earlier call returns: "
                f"version={source.state_version_id.to_payload()}, "
                f"returns={list(matches)}, "
                f"canonical_returns={list(canonical_matches)}"
            ),
        )
    producer_call_id, return_name = canonical_matches[0]
    return FunctionalArgSourceIdentity(
        kind="call_result",
        source_call_id=producer_call_id,
        source_return_name=return_name,
    )


def _problem_binding_for_state_object(
    catalog: ProblemPlanningBindingCatalog,
    source: FunctionalArgSourceIdentity,
    *,
    goal_unit_ids: Sequence[str],
    path: str,
) -> ProblemPlanningSourceBinding:
    """Recover the named Problem entity behind a computed StateVersion."""

    if source.kind != "state_version" or source.state_version_id is None:
        raise _error(
            "planner.problem_source_binding_unresolved",
            path,
            "computed source has no exact StateVersion identity",
        )
    object_id = source.state_version_id.slot_id.logical_key.object_id
    required_goals = set(goal_unit_ids)
    candidates = tuple(
        binding
        for binding in catalog.bindings.values()
        if binding.usage == "input"
        and required_goals.issubset(binding.visible_goal_unit_ids)
        and any(
            typed.math_object_id == object_id
            for typed in binding.typed_sources
        )
    )
    named_candidates = tuple(
        binding
        for binding in candidates
        if binding.semantic_ref.kind != "fact"
    )
    preferred = named_candidates or candidates
    by_runtime_node = {
        binding.runtime_node_id: binding for binding in preferred
    }
    if len(by_runtime_node) != 1:
        raise _error(
            "planner.problem_source_binding_unresolved",
            path,
            (
                "computed StateVersion object maps to "
                f"{len(by_runtime_node)} Goal-visible source authorities: "
                f"object={object_id.to_payload()}, "
                f"goals={sorted(required_goals)}"
            ),
        )
    return next(iter(by_runtime_node.values()))


def _audit_computed_state_source(
    *,
    source_binding: ProblemPlanningSourceBinding,
    typed_source: FunctionalArgSourceIdentity,
    consumer_call_id: str,
    consumer_goal_binding: ProblemCallGoalBinding,
    reconciled_calls: Mapping[str, FunctionalCallReconciliation],
    goal_bindings: ProblemPlanGoalBindings,
    catalog: ProblemPlanningBindingCatalog,
    path: str,
) -> FunctionalArgSourceIdentity | None:
    call_result_source = _call_result_source_for_exact_state(
        typed_source,
        consumer_call_id=consumer_call_id,
        reconciled_calls=reconciled_calls,
        path=path,
    )
    if call_result_source is None:
        return None
    _audit_implicit_same_object_call_result(
        source_binding=source_binding,
        source=call_result_source,
        consumer_call_id=consumer_call_id,
        consumer_goal_binding=consumer_goal_binding,
        reconciled_calls=reconciled_calls,
        goal_bindings=goal_bindings,
        catalog=catalog,
        path=path,
    )
    return call_result_source


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
    if (
        source.kind == "math_object"
        and source.math_object_id is not None
        and len(by_runtime_node) > 1
    ):
        entity_candidates = {
            key: item
            for key, item in by_runtime_node.items()
            if key == source.math_object_id.value
        }
        if len(entity_candidates) == 1:
            by_runtime_node = entity_candidates
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
    "FUNCTIONAL_PROBLEM_BINDING_LEDGER_CONTRACT",
    "PROBLEM_PLANNING_BINDING_CATALOG_CONTRACT",
    "FunctionalProblemBindingContext",
    "FunctionalProblemBindingDraft",
    "FunctionalProblemBindingLedger",
    "FunctionalProblemCallBinding",
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
