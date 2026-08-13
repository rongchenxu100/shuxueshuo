"""Scope-native Planner view derived from an authenticated problem bundle."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from jsonschema import Draft202012Validator

from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemGoal,
    ProblemScope,
    ProblemUnitRecord,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityToken,
    VerifiedSolverProblemBundle,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    FrozenJson,
    freeze_json,
    stable_hash,
    thaw_json,
)
from shuxueshuo_server.solver.runtime.strategy_models import SemanticRef


PROBLEM_PLANNING_CONTEXT_CONTRACT = "problem-planning-context/v1"
PLANNER_PROBLEM_VIEW_CONTRACT = "planner-problem-view/v2"


def planner_problem_view_schema() -> dict[str, Any]:
    """Return the strict, prompt-only Planner problem view contract."""

    semantic_item = {
        "type": "object",
        "required": ["ref", "kind"],
        "properties": {
            "ref": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "minLength": 1},
        },
        # Type-specific source fields are generated from authenticated domain data.
        "additionalProperties": True,
    }
    goal = {
        "type": "object",
        "required": ["kind", "goal_ref", "answer_type"],
        "properties": {
            "kind": {
                "enum": [
                    "point_coordinate",
                    "quadratic_equation",
                    "parameter_value",
                    "minimum_value",
                ]
            },
            "goal_ref": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The unique Goal identity. FunctionalPlan.goal_ref must "
                    "copy this value exactly; a scope id or target name is "
                    "not a Goal identity."
                ),
            },
            "target_ref": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "The visible Problem object answered by this Goal. Use "
                    "this SemanticRef for capability object-identity inputs; "
                    "goal_ref is not an input SemanticRef."
                ),
            },
            "expression": {"type": "object", "minProperties": 1},
            "answer_type": {"type": "string", "minLength": 1},
        },
        "allOf": [
            {
                "if": {
                    "properties": {
                        "kind": {
                            "enum": [
                                "point_coordinate",
                                "quadratic_equation",
                                "parameter_value",
                            ]
                        }
                    },
                    "required": ["kind"],
                },
                "then": {"required": ["target_ref"]},
            },
            {
                "if": {
                    "properties": {"kind": {"const": "minimum_value"}},
                    "required": ["kind"],
                },
                "then": {"required": ["expression"]},
            },
        ],
        "additionalProperties": False,
    }
    scope = {
        "type": "object",
        "required": ["id", "text"],
        "properties": {
            "id": {"type": "string", "minLength": 1},
            "text": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "entities": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/semantic_item"},
            },
            "facts": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/semantic_item"},
            },
            "goals": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/goal"},
            },
            "children": {
                "type": "array",
                "minItems": 1,
                "items": {"$ref": "#/$defs/scope"},
            },
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "planner-problem-view.schema.json",
        "title": "PlannerProblemView prompt payload",
        "type": "object",
        "required": [
            "schema_version",
            "problem_id",
            "family_id",
            "source",
            "root_scope",
        ],
        "properties": {
            "schema_version": {"const": PLANNER_PROBLEM_VIEW_CONTRACT},
            "problem_id": {"type": "string", "minLength": 1},
            "family_id": {"type": "string", "minLength": 1},
            "source": {
                "type": "object",
                "required": ["question_number", "score"],
                "properties": {
                    "question_number": {"type": "string"},
                    "score": {
                        "anyOf": [{"type": "string"}, {"type": "null"}]
                    },
                },
                "additionalProperties": False,
            },
            "root_scope": {"$ref": "#/$defs/scope"},
        },
        "$defs": {
            "semantic_item": semantic_item,
            "goal": goal,
            "scope": scope,
        },
        "additionalProperties": False,
    }


class ProblemPlanningContextError(ValueError):
    """A non-retryable failure while deriving the Planner problem view."""

    retryable = False

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


@dataclass(frozen=True)
class ProblemPlanningSourceUnit:
    source_unit_id: str
    payload: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        frozen = freeze_json(self.payload)
        if not isinstance(frozen, Mapping):
            raise TypeError("planning source unit payload must be an object")
        object.__setattr__(self, "payload", frozen)

    def authority_payload(self) -> dict[str, Any]:
        return {
            "source_unit_id": self.source_unit_id,
            "payload": thaw_json(self.payload),
        }

    def to_prompt_payload(self) -> dict[str, Any]:
        payload = thaw_json(self.payload)
        assert isinstance(payload, dict)
        return payload


@dataclass(frozen=True)
class ScopedSourceRefKey:
    owner_scope_id: str
    local_ref: str
    kind: str

    def __post_init__(self) -> None:
        if not self.owner_scope_id or not self.local_ref or not self.kind:
            raise TypeError("scoped source ref key fields must be non-empty")

    def sort_key(self) -> tuple[str, str, str]:
        return (self.owner_scope_id, self.local_ref, self.kind)

    def to_payload(self) -> dict[str, str]:
        return {
            "owner_scope_id": self.owner_scope_id,
            "local_ref": self.local_ref,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class PlanningReadAuthority:
    semantic_ref: SemanticRef
    runtime_node_id: str
    source_unit_ids: tuple[str, ...]
    owner_scope_id: str
    visible_goal_unit_ids: tuple[str, ...]
    usage: str

    def __post_init__(self) -> None:
        if self.usage not in {"input", "answer"}:
            raise TypeError("planning read authority usage must be input or answer")
        object.__setattr__(
            self,
            "source_unit_ids",
            tuple(sorted(set(self.source_unit_ids))),
        )
        object.__setattr__(
            self,
            "visible_goal_unit_ids",
            tuple(sorted(set(self.visible_goal_unit_ids))),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "semantic_ref": self.semantic_ref.to_payload(),
            "runtime_node_id": self.runtime_node_id,
            "source_unit_ids": list(self.source_unit_ids),
            "owner_scope_id": self.owner_scope_id,
            "visible_goal_unit_ids": list(self.visible_goal_unit_ids),
            "usage": self.usage,
        }

    @property
    def scoped_key(self) -> ScopedSourceRefKey:
        return ScopedSourceRefKey(
            self.owner_scope_id,
            self.semantic_ref.ref,
            self.semantic_ref.kind,
        )


@dataclass(frozen=True)
class ProblemPlanningScope:
    source_scope_unit_id: str
    scope_id: str
    parent_scope_id: str | None
    label: str
    source_text: tuple[str, ...]
    entities: tuple[ProblemPlanningSourceUnit, ...]
    facts: tuple[ProblemPlanningSourceUnit, ...]
    available_refs: tuple[SemanticRef, ...]
    visible_goal_unit_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_text", tuple(self.source_text))
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "facts", tuple(self.facts))
        object.__setattr__(self, "available_refs", tuple(self.available_refs))
        object.__setattr__(
            self,
            "visible_goal_unit_ids",
            tuple(sorted(set(self.visible_goal_unit_ids))),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "source_scope_unit_id": self.source_scope_unit_id,
            "scope_id": self.scope_id,
            "parent_scope_id": self.parent_scope_id,
            "label": self.label,
            "source_text": list(self.source_text),
            "entities": [item.authority_payload() for item in self.entities],
            "facts": [item.authority_payload() for item in self.facts],
            "available_refs": [item.to_payload() for item in self.available_refs],
            "visible_goal_unit_ids": list(self.visible_goal_unit_ids),
        }

@dataclass(frozen=True)
class ProblemPlanningGoalView:
    goal_unit_id: str
    goal_kind: str
    answer_key: str
    owner_scope_id: str
    scope_path: tuple[str, ...]
    visible_scope_ids: tuple[str, ...]
    answer_ref: SemanticRef
    semantic_reads: tuple[SemanticRef, ...]
    goal_payload: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_path", tuple(self.scope_path))
        object.__setattr__(self, "visible_scope_ids", tuple(self.visible_scope_ids))
        object.__setattr__(self, "semantic_reads", tuple(self.semantic_reads))
        frozen = freeze_json(self.goal_payload)
        if not isinstance(frozen, Mapping):
            raise TypeError("planning goal payload must be an object")
        object.__setattr__(self, "goal_payload", frozen)

    def authority_payload(self) -> dict[str, Any]:
        return {
            "goal_unit_id": self.goal_unit_id,
            "goal_kind": self.goal_kind,
            "answer_key": self.answer_key,
            "owner_scope_id": self.owner_scope_id,
            "scope_path": list(self.scope_path),
            "visible_scope_ids": list(self.visible_scope_ids),
            "answer_ref": self.answer_ref.to_payload(),
            "semantic_reads": [item.to_payload() for item in self.semantic_reads],
            "goal_payload": thaw_json(self.goal_payload),
        }


@dataclass(frozen=True)
class ProblemPlanningContext:
    schema_version: str
    planning_context_id: str
    bundle_authority_token: ProblemBundleAuthorityToken
    problem_id: str
    family_id: str
    source: Mapping[str, FrozenJson]
    scopes: tuple[ProblemPlanningScope, ...]
    goal_views: tuple[ProblemPlanningGoalView, ...]
    ref_authorities: Mapping[ScopedSourceRefKey, PlanningReadAuthority]

    def __post_init__(self) -> None:
        frozen_source = freeze_json(self.source)
        if not isinstance(frozen_source, Mapping):
            raise TypeError("planning source must be an object")
        object.__setattr__(self, "source", frozen_source)
        object.__setattr__(self, "scopes", tuple(self.scopes))
        object.__setattr__(self, "goal_views", tuple(self.goal_views))
        object.__setattr__(
            self,
            "ref_authorities",
            MappingProxyType(
                dict(
                    sorted(
                        self.ref_authorities.items(),
                        key=lambda item: item[0].sort_key(),
                    )
                )
            ),
        )

    def authority_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "planning_context_id": self.planning_context_id,
            "bundle_authority_token": self.bundle_authority_token.to_payload(),
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "source": thaw_json(self.source),
            "scopes": [scope.authority_payload() for scope in self.scopes],
            "goal_views": [goal.authority_payload() for goal in self.goal_views],
            "ref_authorities": [
                value.authority_payload()
                for value in self.ref_authorities.values()
            ],
        }

    @property
    def problem_revision_id(self) -> str:
        return self.bundle_authority_token.problem_revision_id

    @property
    def problem_semantic_hash(self) -> str:
        return self.bundle_authority_token.problem_semantic_hash

    def input_authorities_for_goal(
        self,
        goal_unit_id: str,
    ) -> tuple[PlanningReadAuthority, ...]:
        """Return the only input catalog F5-C may bind for one Goal."""

        goal = self._goal_view(goal_unit_id)
        allowed_refs = {item.ref for item in goal.semantic_reads}
        result = tuple(
            authority
            for authority in self.ref_authorities.values()
            if authority.usage == "input"
            and goal_unit_id in authority.visible_goal_unit_ids
            and authority.semantic_ref.ref in allowed_refs
        )
        if {item.semantic_ref.ref for item in result} != allowed_refs:
            raise _error(
                "planner.problem_planning_projection_drift",
                "$.ref_authorities",
                f"Goal {goal_unit_id!r} SemanticRef catalog has drifted",
            )
        return result

    def answer_authority_for_goal(
        self,
        goal_unit_id: str,
    ) -> PlanningReadAuthority:
        """Return the unique answer authority for one Goal."""

        goal = self._goal_view(goal_unit_id)
        matches = tuple(
            authority
            for authority in self.ref_authorities.values()
            if authority.usage == "answer"
            and authority.visible_goal_unit_ids == (goal_unit_id,)
            and authority.semantic_ref == goal.answer_ref
        )
        if len(matches) != 1:
            raise _error(
                "planner.problem_planning_projection_drift",
                "$.ref_authorities",
                f"Goal {goal_unit_id!r} answer authority has drifted",
            )
        return matches[0]

    def resolve_input_authority(
        self,
        *,
        scope_id: str,
        local_ref: str,
        goal_unit_ids: Sequence[str] = (),
    ) -> PlanningReadAuthority:
        """Resolve one prompt SourceRef through lexical scope authority."""

        scope_parents = {
            scope.scope_id: scope.parent_scope_id for scope in self.scopes
        }
        if scope_id not in scope_parents:
            raise _error(
                "planner.problem_scope_visibility_drift",
                "$.scopes",
                f"unknown SourceRef resolution scope {scope_id!r}",
            )
        scope_path: list[str] = []
        current: str | None = scope_id
        while current is not None:
            scope_path.append(current)
            current = scope_parents[current]
        goal_ids = frozenset(goal_unit_ids)
        matches = tuple(
            authority
            for authority in self.ref_authorities.values()
            if authority.usage == "input"
            and authority.semantic_ref.ref == local_ref
            and authority.owner_scope_id in scope_path
            and (
                not goal_ids
                or goal_ids.issubset(authority.visible_goal_unit_ids)
            )
        )
        if len(matches) != 1:
            code = (
                "planner.problem_source_binding_unresolved"
                if not matches
                else "planner.problem_planning_ref_ambiguous"
            )
            raise _error(
                code,
                "$.ref_authorities",
                (
                    f"SourceRef {local_ref!r} has no visible authority from "
                    f"scope {scope_id!r}"
                    if not matches
                    else (
                        f"SourceRef {local_ref!r} resolves to multiple "
                        f"authorities from scope {scope_id!r}"
                    )
                ),
            )
        return matches[0]

    def _goal_view(self, goal_unit_id: str) -> ProblemPlanningGoalView:
        matches = [item for item in self.goal_views if item.goal_unit_id == goal_unit_id]
        if len(matches) != 1:
            raise _error(
                "planner.problem_planning_context_invalid",
                "$.goal_views",
                f"unknown or duplicate Goal unit {goal_unit_id!r}",
            )
        return matches[0]

    def to_prompt_payload(
        self,
        *,
        goal_unit_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        selected_goal_ids = (
            {item.goal_unit_id for item in self.goal_views}
            if goal_unit_ids is None
            else set(goal_unit_ids)
        )
        known_goal_ids = {item.goal_unit_id for item in self.goal_views}
        if not selected_goal_ids or not selected_goal_ids <= known_goal_ids:
            raise _error(
                "planner.problem_planning_context_invalid",
                "$.goal_views",
                "prompt projection references unknown or empty Goal authority",
            )
        selected_goals = tuple(
            item
            for item in self.goal_views
            if item.goal_unit_id in selected_goal_ids
        )
        scopes_by_id = {scope.scope_id: scope for scope in self.scopes}
        included_scope_ids = {
            scope_id
            for goal in selected_goals
            for scope_id in goal.visible_scope_ids
        }
        root_scope_ids = [
            scope.scope_id
            for scope in self.scopes
            if scope.parent_scope_id is None and scope.scope_id in included_scope_ids
        ]
        if len(root_scope_ids) != 1:
            raise _error(
                "planner.problem_scope_visibility_drift",
                "$.scopes",
                "prompt scope selection must contain exactly one root",
            )
        source_units = {
            unit.source_unit_id: unit.to_prompt_payload()
            for scope in self.scopes
            for unit in (*scope.entities, *scope.facts)
        }
        fact_authority_source_ids = {
            source_id
            for authority in self.ref_authorities.values()
            if authority.usage == "input" and authority.semantic_ref.kind == "fact"
            for source_id in authority.source_unit_ids
        }
        entities_by_scope: dict[str, list[dict[str, Any]]] = {
            scope_id: [] for scope_id in included_scope_ids
        }
        facts_by_scope: dict[str, list[dict[str, Any]]] = {
            scope_id: [] for scope_id in included_scope_ids
        }
        for authority in self.ref_authorities.values():
            if (
                authority.usage != "input"
                or authority.owner_scope_id not in included_scope_ids
                or not selected_goal_ids.intersection(
                    authority.visible_goal_unit_ids
                )
            ):
                continue
            item = _prompt_semantic_item(
                authority,
                source_units=source_units,
                fact_authority_source_ids=fact_authority_source_ids,
            )
            target = (
                facts_by_scope
                if authority.semantic_ref.kind == "fact"
                else entities_by_scope
            )
            target[authority.owner_scope_id].append(item)

        goals_by_scope: dict[str, list[dict[str, Any]]] = {
            scope_id: [] for scope_id in included_scope_ids
        }
        for goal in selected_goals:
            goals_by_scope[goal.owner_scope_id].append(_prompt_goal(goal))
        children_by_scope: dict[str, list[str]] = {
            scope_id: [] for scope_id in included_scope_ids
        }
        for scope in self.scopes:
            if (
                scope.scope_id in included_scope_ids
                and scope.parent_scope_id in included_scope_ids
            ):
                children_by_scope[scope.parent_scope_id].append(scope.scope_id)

        def project_scope(scope_id: str) -> dict[str, Any]:
            scope = scopes_by_id[scope_id]
            payload: dict[str, Any] = {
                "id": scope.scope_id,
                "text": list(scope.source_text),
            }
            entities = sorted(
                entities_by_scope[scope_id],
                key=lambda item: (str(item["kind"]), str(item["ref"])),
            )
            facts = sorted(
                facts_by_scope[scope_id],
                key=lambda item: (str(item["kind"]), str(item["ref"])),
            )
            goals = goals_by_scope[scope_id]
            children = [
                project_scope(child_id)
                for child_id in children_by_scope[scope_id]
            ]
            if entities:
                payload["entities"] = entities
            if facts:
                payload["facts"] = facts
            if goals:
                payload["goals"] = goals
            if children:
                payload["children"] = children
            return payload

        return {
            "schema_version": PLANNER_PROBLEM_VIEW_CONTRACT,
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "source": thaw_json(self.source),
            "root_scope": project_scope(root_scope_ids[0]),
        }


def _prompt_semantic_item(
    authority: PlanningReadAuthority,
    *,
    source_units: Mapping[str, Mapping[str, Any]],
    fact_authority_source_ids: set[str],
) -> dict[str, Any]:
    source_pairs = sorted(
        (
            (source_id, source_units[source_id])
            for source_id in authority.source_unit_ids
            if source_id in source_units
        ),
        key=lambda item: (stable_hash(item[1]), item[0]),
    )
    payloads = [payload for _, payload in source_pairs]
    if not payloads:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.ref_authorities",
            f"SemanticRef {authority.semantic_ref.ref!r} has no prompt source",
        )
    ref = authority.semantic_ref
    prompt_kind = ref.value_type if ref.kind == "fact" else ref.kind
    result: dict[str, Any] = {
        "ref": ref.ref,
        "kind": prompt_kind or ref.kind,
    }
    entity_payloads = [payload for payload in payloads if "id" in payload]
    fact_payloads = [payload for payload in payloads if "id" not in payload]
    if ref.kind == "fact":
        if len(fact_payloads) == 1:
            result.update(
                {
                    key: thaw_json(value)
                    for key, value in fact_payloads[0].items()
                    if key not in {"kind", "ref"}
                }
            )
        elif fact_payloads:
            result["components"] = [
                thaw_json(payload) for payload in fact_payloads
            ]
        else:
            raise _error(
                "planner.problem_planning_projection_drift",
                "$.ref_authorities",
                f"Fact ref {ref.ref!r} has no source Fact",
            )
        return result

    if len(entity_payloads) > 1:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.ref_authorities",
            f"Entity ref {ref.ref!r} has multiple source Entities",
        )
    if entity_payloads:
        entity = entity_payloads[0]
        local_id = str(entity.get("id", ""))
        for key, value in entity.items():
            if key in {"id", "kind"}:
                continue
            if key == "label" and str(value) in {local_id, ref.ref}:
                continue
            result[key] = thaw_json(value)
    elif ref.kind == "segment":
        segment = _segment_for_prompt_ref(ref.ref, fact_payloads)
        if segment is not None:
            result.update(segment)

    definitions = [
        _compact_entity_definition(ref.ref, payload)
        for source_id, payload in source_pairs
        if "id" not in payload and source_id not in fact_authority_source_ids
    ]
    definitions = [item for item in definitions if item]
    if len(definitions) == 1:
        result["definition"] = definitions[0]
    elif definitions:
        result["definitions"] = definitions
    return result


def _compact_entity_definition(
    semantic_ref: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    result = {
        key: thaw_json(value)
        for key, value in payload.items()
        if key not in {"kind", "ref"}
    }
    for key in ("function", "point"):
        if result.get(key) == semantic_ref:
            result.pop(key)
    return result


def _segment_for_prompt_ref(
    semantic_ref: str,
    payloads: Sequence[Mapping[str, Any]],
) -> dict[str, str] | None:
    candidates: list[tuple[str, str]] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if set(("start", "end")) <= set(value):
                start = value.get("start")
                end = value.get("end")
                if isinstance(start, str) and isinstance(end, str):
                    candidate = (start, end)
                    if candidate not in candidates:
                        candidates.append(candidate)
            for child in value.values():
                visit(child)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                visit(child)

    for payload in payloads:
        visit(payload)
    normalized_ref = _ref_token(semantic_ref).lower()
    matches = [
        (start, end)
        for start, end in candidates
        if _ref_token(f"{start}{end}").lower() == normalized_ref
        or _ref_token(f"{end}{start}").lower() == normalized_ref
    ]
    if len(matches) != 1:
        return None
    return {"start": matches[0][0], "end": matches[0][1]}


def _prompt_goal(goal: ProblemPlanningGoalView) -> dict[str, Any]:
    source = thaw_json(goal.goal_payload)
    assert isinstance(source, dict)
    result: dict[str, Any] = {"kind": goal.goal_kind}
    for key, value in source.items():
        if key in {"answer_key", "kind"}:
            continue
        result["target_ref" if key == "target" else key] = value
    if not goal.answer_ref.value_type:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.goal_views",
            f"Goal {goal.goal_unit_id!r} has no answer value type",
        )
    result["goal_ref"] = goal.answer_ref.ref
    result["answer_type"] = goal.answer_ref.value_type
    return result


@dataclass(frozen=True)
class _RuntimeNode:
    runtime_node_id: str
    node_kind: str
    owner_scope_id: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class _RefCandidate:
    runtime_node: _RuntimeNode
    base_ref: str
    kind: str
    value_type: str | None
    source_unit_ids: tuple[str, ...]
    usage: str


class ProblemPlanningContextProjector:
    """Derive a complete scope-aware Planner view without running runtime code."""

    def project(
        self,
        bundle: VerifiedSolverProblemBundle,
        *,
        expected_token: ProblemBundleAuthorityToken | None = None,
    ) -> ProblemPlanningContext:
        if expected_token is not None and bundle.authority_token != expected_token:
            raise _error(
                "planner.problem_revision_drift",
                "$.bundle_authority_token",
                "problem bundle differs from the expected authority token",
            )

        graph = bundle.verified_problem.graph
        records = _unit_records(bundle)
        scope_records = _scope_records(graph.root_scope, bundle)
        scope_by_runtime_id = {
            item.scope_id: item for item in scope_records
        }
        scope_path_by_runtime_id = _runtime_scope_paths(scope_records)
        runtime_nodes = _canonical_runtime_nodes(bundle)
        goals = _goal_records(
            graph.root_scope,
            scope_records,
            bundle,
            runtime_nodes,
        )
        if not goals:
            raise _error(
                "planner.problem_planning_context_invalid",
                "$.goal_views",
                "verified problem has no goals",
            )
        visible_goals_by_scope = _visible_goals_by_scope(
            scope_records,
            goals,
            scope_path_by_runtime_id,
        )
        _validate_goal_ownership(scope_records, visible_goals_by_scope)

        _audit_runtime_coverage(bundle, runtime_nodes, records, scope_records)
        candidates = _ref_candidates(
            bundle,
            runtime_nodes,
            records,
            scope_path_by_runtime_id,
        )
        authorities = _materialize_ref_authorities(
            candidates,
            visible_goals_by_scope=visible_goals_by_scope,
            scope_paths=scope_path_by_runtime_id,
        )
        prompt_source_payloads = _canonical_prompt_source_payloads(
            graph.root_scope,
            bundle=bundle,
            runtime_nodes=runtime_nodes,
            authorities=authorities,
        )
        refs_by_scope: dict[str, list[SemanticRef]] = {
            scope_id: [] for scope_id in scope_by_runtime_id
        }
        for authority in authorities.values():
            if authority.usage == "input":
                refs_by_scope[authority.owner_scope_id].append(authority.semantic_ref)

        planning_scopes = tuple(
            ProblemPlanningScope(
                source_scope_unit_id=item.source_scope.unit_id,
                scope_id=item.scope_id,
                parent_scope_id=item.parent_scope_id,
                label=item.source_scope.label,
                source_text=item.source_scope.source_text,
                entities=tuple(
                    ProblemPlanningSourceUnit(
                        entity.unit_id,
                        prompt_source_payloads[entity.unit_id],
                    )
                    for entity in sorted(
                        item.source_scope.entities,
                        key=lambda entity: (
                            stable_hash(prompt_source_payloads[entity.unit_id]),
                            entity.unit_id,
                        ),
                    )
                ),
                facts=tuple(
                    ProblemPlanningSourceUnit(
                        fact.unit_id,
                        prompt_source_payloads[fact.unit_id],
                    )
                    for fact in sorted(
                        item.source_scope.facts,
                        key=lambda fact: (
                            stable_hash(prompt_source_payloads[fact.unit_id]),
                            fact.unit_id,
                        ),
                    )
                ),
                available_refs=tuple(
                    sorted(
                        refs_by_scope[item.scope_id],
                        key=lambda ref: (ref.kind, ref.ref),
                    )
                ),
                visible_goal_unit_ids=visible_goals_by_scope[item.scope_id],
            )
            for item in scope_records
        )
        goal_views = tuple(
            _goal_view(
                goal,
                scope_records=scope_records,
                authorities=authorities,
                scope_path_by_runtime_id=scope_path_by_runtime_id,
                prompt_source_payloads=prompt_source_payloads,
            )
            for goal in goals
        )
        _audit_source_coverage(
            records,
            planning_scopes=planning_scopes,
            goal_views=goal_views,
        )
        _audit_goal_read_catalog(
            planning_scopes=planning_scopes,
            goal_views=goal_views,
            authorities=authorities,
        )
        _audit_authority_visibility(
            authorities,
            scope_path_by_runtime_id=scope_path_by_runtime_id,
            records=records,
            scope_records=scope_records,
        )

        identity_payload = {
            "schema_version": PROBLEM_PLANNING_CONTEXT_CONTRACT,
            "bundle_authority_token": bundle.authority_token.to_payload(),
            "problem_id": graph.problem_id,
            "family_id": graph.family_id,
            "source": graph.source.to_payload(),
            "scopes": [item.authority_payload() for item in planning_scopes],
            "goal_views": [item.authority_payload() for item in goal_views],
            "ref_authorities": [
                value.authority_payload()
                for value in authorities.values()
            ],
        }
        context = ProblemPlanningContext(
            schema_version=PROBLEM_PLANNING_CONTEXT_CONTRACT,
            planning_context_id=(
                "problem-planning-context:" + stable_hash(identity_payload)
            ),
            bundle_authority_token=bundle.authority_token,
            problem_id=graph.problem_id,
            family_id=graph.family_id,
            source=graph.source.to_payload(),
            scopes=planning_scopes,
            goal_views=goal_views,
            ref_authorities=authorities,
        )
        _audit_prompt_payload(
            context.to_prompt_payload(),
            forbidden_values=_internal_authority_values(bundle, records, runtime_nodes),
        )
        return context


@dataclass(frozen=True)
class _ScopeRecord:
    source_scope: ProblemScope
    scope_id: str
    parent_scope_id: str | None


@dataclass(frozen=True)
class _GoalRecord:
    source_goal: ProblemGoal
    owner_scope_id: str
    answer_runtime_node_id: str
    answer_key: str


def _unit_records(bundle: VerifiedSolverProblemBundle) -> dict[str, ProblemUnitRecord]:
    payload = bundle.verified_problem.to_payload()
    result = {
        str(item["unit_id"]): ProblemUnitRecord.from_payload(item)
        for item in payload["unit_registry"]
    }
    if len(result) != len(payload["unit_registry"]):
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.verified_problem.unit_registry",
            "source unit registry contains duplicate ids",
        )
    return result


def _scope_records(
    root: ProblemScope,
    bundle: VerifiedSolverProblemBundle,
) -> tuple[_ScopeRecord, ...]:
    result: list[_ScopeRecord] = []
    for scope in root.iter_scopes():
        scope_id = bundle.projection_index.scope_runtime_id_by_unit.get(scope.unit_id)
        if scope_id is None:
            raise _error(
                "planner.problem_planning_projection_drift",
                "$.projection_index.scope_runtime_id_by_unit",
                f"source scope {scope.unit_id!r} has no runtime scope",
            )
        parent_scope_id = None
        if len(scope.path) > 1:
            parent_path = "/".join(scope.path[:-1])
            parent = bundle.verified_problem.graph.scope_by_path.get(parent_path)
            if parent is None:
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    "$.scopes",
                    f"scope {scope.path_id!r} has no source parent",
                )
            parent_scope_id = bundle.projection_index.scope_runtime_id_by_unit.get(
                parent.unit_id
            )
        result.append(_ScopeRecord(scope, scope_id, parent_scope_id))
    if len({item.scope_id for item in result}) != len(result):
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.scopes",
            "multiple source scopes map to one runtime scope",
        )
    return tuple(result)


def _runtime_scope_paths(
    scope_records: Sequence[_ScopeRecord],
) -> dict[str, tuple[str, ...]]:
    by_id = {item.scope_id: item for item in scope_records}
    result: dict[str, tuple[str, ...]] = {}
    for scope_id in by_id:
        path: list[str] = []
        current: str | None = scope_id
        seen: set[str] = set()
        while current is not None:
            if current in seen or current not in by_id:
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    "$.scopes",
                    f"runtime scope ancestry is invalid at {current!r}",
                )
            seen.add(current)
            path.append(current)
            current = by_id[current].parent_scope_id
        result[scope_id] = tuple(reversed(path))
    roots = {path[0] for path in result.values() if path}
    if len(roots) != 1:
        raise _error(
            "planner.problem_scope_visibility_drift",
            "$.scopes",
            "planning scopes must form one rooted tree",
        )
    return result


def _goal_records(
    root: ProblemScope,
    scope_records: Sequence[_ScopeRecord],
    bundle: VerifiedSolverProblemBundle,
    runtime_nodes: Mapping[str, _RuntimeNode],
) -> tuple[_GoalRecord, ...]:
    scope_id_by_unit = {
        item.source_scope.unit_id: item.scope_id for item in scope_records
    }
    result: list[_GoalRecord] = []
    # Child scope order is semantic; Goal arrays within one scope are not.
    for scope in root.iter_scopes():
        owner_scope_id = scope_id_by_unit[scope.unit_id]
        for goal in sorted(
            scope.goals,
            key=lambda item: (
                bundle.projection_index.goal_answer_handle_by_unit.get(
                    item.unit_id,
                    "",
                ),
                item.unit_id,
            ),
        ):
            runtime_id = bundle.projection_index.goal_answer_handle_by_unit.get(
                goal.unit_id
            )
            if runtime_id is None:
                raise _error(
                    "planner.problem_planning_projection_drift",
                    "$.projection_index.goal_answer_handle_by_unit",
                    f"Goal {goal.unit_id!r} has no answer mapping",
                )
            runtime_node = runtime_nodes.get(runtime_id)
            answer_key = (
                str(runtime_node.payload.get("answer_key", ""))
                if runtime_node is not None
                else ""
            )
            if (
                runtime_node is None
                or runtime_node.node_kind != "goal"
                or runtime_node.owner_scope_id != owner_scope_id
                or not answer_key
            ):
                raise _error(
                    "planner.problem_planning_projection_drift",
                    "$.projection_index.goal_answer_handle_by_unit",
                    f"Goal {goal.unit_id!r} runtime answer mapping is invalid",
                )
            result.append(
                _GoalRecord(goal, owner_scope_id, runtime_id, answer_key)
            )
    return tuple(result)


def _visible_goals_by_scope(
    scope_records: Sequence[_ScopeRecord],
    goals: Sequence[_GoalRecord],
    scope_paths: Mapping[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for scope in scope_records:
        result[scope.scope_id] = tuple(
            goal.source_goal.unit_id
            for goal in goals
            if scope.scope_id in scope_paths[goal.owner_scope_id]
        )
    return result


def _validate_goal_ownership(
    scope_records: Sequence[_ScopeRecord],
    visible_goals_by_scope: Mapping[str, tuple[str, ...]],
) -> None:
    for scope in scope_records:
        if not scope.source_scope.children and not visible_goals_by_scope[scope.scope_id]:
            raise _error(
                "planner.problem_planning_context_invalid",
                "$.scopes",
                f"leaf scope {scope.scope_id!r} has no Goal",
            )


def _canonical_runtime_nodes(
    bundle: VerifiedSolverProblemBundle,
) -> dict[str, _RuntimeNode]:
    payload = bundle.canonical_solver_input
    result: dict[str, _RuntimeNode] = {}
    for row in _mapping_rows(payload.get("scopes"), "$.canonical_input.scopes"):
        scope_id = str(row.get("scope_id", ""))
        _insert_runtime_node(
            result,
            _RuntimeNode(f"scope:{scope_id}", "scope", scope_id, row),
        )
    for collection, node_kind in (
        ("entities", "entity"),
        ("facts", "fact"),
        ("question_goals", "goal"),
    ):
        for row in _mapping_rows(
            payload.get(collection), f"$.canonical_input.{collection}"
        ):
            runtime_id = str(row.get("handle", ""))
            owner_scope_id = str(row.get("scope_id", ""))
            _insert_runtime_node(
                result,
                _RuntimeNode(runtime_id, node_kind, owner_scope_id, row),
            )
    return result


def _insert_runtime_node(
    result: dict[str, _RuntimeNode],
    node: _RuntimeNode,
) -> None:
    if not node.runtime_node_id or node.runtime_node_id in result:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.canonical_input",
            f"runtime node id is missing or duplicate: {node.runtime_node_id!r}",
        )
    result[node.runtime_node_id] = node


def _audit_runtime_coverage(
    bundle: VerifiedSolverProblemBundle,
    runtime_nodes: Mapping[str, _RuntimeNode],
    records: Mapping[str, ProblemUnitRecord],
    scope_records: Sequence[_ScopeRecord],
) -> None:
    manifest_nodes = set(bundle.projection_index.runtime_node_source_units)
    if manifest_nodes != set(runtime_nodes):
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.projection_index.runtime_node_source_units",
            "runtime projection index does not cover canonical runtime nodes",
        )
    scope_runtime_ids = {
        f"scope:{item.scope_id}" for item in scope_records
    }
    indexed_scope_ids = {
        f"scope:{value}"
        for value in bundle.projection_index.scope_runtime_id_by_unit.values()
    }
    if scope_runtime_ids != indexed_scope_ids:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.projection_index.scope_runtime_id_by_unit",
            "scope projection index differs from canonical scopes",
        )
    for item in scope_records:
        runtime_scope = runtime_nodes[f"scope:{item.scope_id}"]
        runtime_parent = runtime_scope.payload.get("parent")
        if runtime_parent != item.parent_scope_id:
            raise _error(
                "planner.problem_scope_visibility_drift",
                f"$.canonical_input.scopes[{item.scope_id!r}]",
                "runtime scope parent differs from the verified scope tree",
            )
    unknown_sources = {
        source_id
        for source_ids in bundle.projection_index.runtime_node_source_units.values()
        for source_id in source_ids
        if source_id not in records
    }
    if unknown_sources:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.projection_index.runtime_node_source_units",
            f"runtime node references unknown source unit {sorted(unknown_sources)[0]!r}",
        )
    expected_reverse: dict[str, list[str]] = {
        unit_id: []
        for unit_id, record in records.items()
        if record.unit_kind != "family"
    }
    for runtime_id, source_ids in (
        bundle.projection_index.runtime_node_source_units.items()
    ):
        for source_id in source_ids:
            if source_id in expected_reverse:
                expected_reverse[source_id].append(runtime_id)
    normalized_reverse = {
        source_id: tuple(sorted(runtime_ids))
        for source_id, runtime_ids in expected_reverse.items()
    }
    if dict(bundle.projection_index.source_unit_runtime_nodes) != normalized_reverse:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.projection_index.source_unit_runtime_nodes",
            "forward and reverse runtime provenance indexes differ",
        )
    goal_unit_ids = {
        unit_id for unit_id, record in records.items() if record.unit_kind == "goal"
    }
    if set(bundle.projection_index.goal_answer_handle_by_unit) != goal_unit_ids:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.projection_index.goal_answer_handle_by_unit",
            "Goal answer index does not cover every source Goal exactly once",
        )


def _ref_candidates(
    bundle: VerifiedSolverProblemBundle,
    runtime_nodes: Mapping[str, _RuntimeNode],
    records: Mapping[str, ProblemUnitRecord],
    scope_paths: Mapping[str, tuple[str, ...]],
) -> tuple[_RefCandidate, ...]:
    result: list[_RefCandidate] = []
    entity_bases: dict[str, str] = {}
    for runtime_id, node in runtime_nodes.items():
        if node.node_kind != "entity":
            continue
        source_ids = bundle.projection_index.runtime_node_source_units[runtime_id]
        source_entity = next(
            (records[item] for item in source_ids if records[item].unit_kind == "entity"),
            None,
        )
        raw_name = str(node.payload.get("name", "")) or (
            source_entity.local_id if source_entity is not None else ""
        )
        base = _ref_token(raw_name or _runtime_semantic_name(runtime_id))
        entity_bases[runtime_id] = base
        result.append(
            _RefCandidate(
                runtime_node=node,
                base_ref=base,
                kind=str(node.payload.get("entity_type", "entity")),
                value_type=None,
                source_unit_ids=source_ids,
                usage="input",
            )
        )

    runtime_ids = set(runtime_nodes)
    fact_base_cache: dict[str, str] = {}

    def fact_base(runtime_id: str, visiting: frozenset[str] = frozenset()) -> str:
        cached = fact_base_cache.get(runtime_id)
        if cached is not None:
            return cached
        if runtime_id in visiting:
            return _semantic_name(str(runtime_nodes[runtime_id].payload.get("type", "fact")))
        node = runtime_nodes[runtime_id]
        references = _runtime_references(node.payload, runtime_ids)
        names: list[str] = []
        for reference in references:
            referenced = runtime_nodes[reference]
            if referenced.node_kind == "scope":
                continue
            if referenced.node_kind == "entity":
                names.append(_semantic_name(entity_bases[reference]))
            elif referenced.node_kind == "fact":
                names.append(fact_base(reference, visiting | {runtime_id}))
        fact_type = _semantic_name(str(node.payload.get("type", "fact")))
        value = "_".join(_unique_ordered((fact_type, *names)))
        fact_base_cache[runtime_id] = value
        return value

    for runtime_id, node in runtime_nodes.items():
        if node.node_kind != "fact":
            continue
        result.append(
            _RefCandidate(
                runtime_node=node,
                base_ref=fact_base(runtime_id),
                kind="fact",
                value_type=str(node.payload.get("type", "fact")),
                source_unit_ids=(
                    bundle.projection_index.runtime_node_source_units[runtime_id]
                ),
                usage="input",
            )
        )

    goal_by_unit = {
        goal.unit_id: (scope, goal)
        for scope in bundle.verified_problem.graph.root_scope.iter_scopes()
        for goal in scope.goals
    }
    for goal_unit_id, runtime_id in sorted(
        bundle.projection_index.goal_answer_handle_by_unit.items()
    ):
        node = runtime_nodes.get(runtime_id)
        source = goal_by_unit.get(goal_unit_id)
        if node is None or node.node_kind != "goal" or source is None:
            raise _error(
                "planner.problem_planning_projection_drift",
                "$.projection_index.goal_answer_handle_by_unit",
                f"Goal mapping is unresolved for {goal_unit_id!r}",
            )
        _, goal = source
        answer_key = str(node.payload.get("answer_key", ""))
        if not answer_key:
            raise _error(
                "planner.problem_planning_projection_drift",
                "$.canonical_input.question_goals",
                f"Goal {goal.unit_id!r} has no canonical answer key",
            )
        base = f"{node.owner_scope_id}.{_ref_token(answer_key)}"
        result.append(
            _RefCandidate(
                runtime_node=node,
                base_ref=base,
                kind="answer",
                value_type=str(node.payload.get("value_type", "")) or None,
                source_unit_ids=(
                    bundle.projection_index.runtime_node_source_units[runtime_id]
                ),
                usage="answer",
            )
        )

    non_scope_nodes = {
        runtime_id
        for runtime_id, node in runtime_nodes.items()
        if node.node_kind != "scope"
    }
    candidate_nodes = {item.runtime_node.runtime_node_id for item in result}
    if non_scope_nodes != candidate_nodes or len(candidate_nodes) != len(result):
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.ref_authorities",
            "every non-scope runtime node must produce exactly one SemanticRef",
        )
    for item in result:
        if item.runtime_node.owner_scope_id not in scope_paths:
            raise _error(
                "planner.problem_scope_visibility_drift",
                "$.ref_authorities",
                f"runtime node {item.runtime_node.runtime_node_id!r} has unknown owner scope",
            )
    return tuple(result)


def _canonical_prompt_source_payloads(
    root: ProblemScope,
    *,
    bundle: VerifiedSolverProblemBundle,
    runtime_nodes: Mapping[str, _RuntimeNode],
    authorities: Mapping[ScopedSourceRefKey, PlanningReadAuthority],
) -> Mapping[str, Mapping[str, Any]]:
    authority_by_runtime_id = {
        authority.runtime_node_id: authority for authority in authorities.values()
    }
    entity_ref_by_unit: dict[str, str] = {}
    for scope in root.iter_scopes():
        for entity in scope.entities:
            runtime_ids = bundle.projection_index.source_unit_runtime_nodes.get(
                entity.unit_id,
                (),
            )
            refs = {
                authority_by_runtime_id[runtime_id].semantic_ref.ref
                for runtime_id in runtime_ids
                if runtime_id in runtime_nodes
                and runtime_nodes[runtime_id].node_kind == "entity"
                and runtime_id in authority_by_runtime_id
            }
            if len(refs) != 1:
                raise _error(
                    "planner.problem_planning_projection_drift",
                    "$.ref_authorities",
                    f"source Entity {entity.unit_id!r} has no unique prompt ref",
                )
            entity_ref_by_unit[entity.unit_id] = next(iter(refs))

    result: dict[str, Mapping[str, Any]] = {}

    def visit(scope: ProblemScope, inherited_refs: Mapping[str, str]) -> None:
        visible_refs = dict(inherited_refs)
        for entity in scope.entities:
            visible_refs[entity.local_id] = entity_ref_by_unit[entity.unit_id]
        for item in (*scope.entities, *scope.facts, *scope.goals):
            payload = _rewrite_prompt_source_refs(item.wire_payload(), visible_refs)
            assert isinstance(payload, Mapping)
            result[item.unit_id] = MappingProxyType(dict(payload))
        for child in scope.children:
            visit(child, visible_refs)

    visit(root, {})
    return MappingProxyType(dict(sorted(result.items())))


def _rewrite_prompt_source_refs(
    value: Any,
    refs: Mapping[str, str],
    *,
    key: str | None = None,
) -> Any:
    if isinstance(value, str):
        if key in {
            "axis",
            "construction",
            "kind",
            "label",
            "operator",
            "orientation",
            "quadrant",
            "role",
        }:
            return value
        if value in refs:
            return refs[value]
        result = value
        for source, target in sorted(
            refs.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            result = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
                target,
                result,
            )
        return result
    if isinstance(value, Mapping):
        return {
            str(item_key): _rewrite_prompt_source_refs(
                item,
                refs,
                key=str(item_key),
            )
            for item_key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            _rewrite_prompt_source_refs(item, refs, key=key)
            for item in value
        ]
    return value


def _materialize_ref_authorities(
    candidates: Sequence[_RefCandidate],
    *,
    visible_goals_by_scope: Mapping[str, tuple[str, ...]],
    scope_paths: Mapping[str, tuple[str, ...]],
) -> Mapping[ScopedSourceRefKey, PlanningReadAuthority]:
    grouped: dict[tuple[str, str, str], list[_RefCandidate]] = {}
    for item in candidates:
        grouped.setdefault(
            (
                item.runtime_node.owner_scope_id,
                item.base_ref,
                item.usage,
            ),
            [],
        ).append(item)

    final_names: dict[str, str] = {}
    for (_scope_id, name, _usage), items in grouped.items():
        ordered = sorted(
            items,
            key=lambda item: (
                stable_hash(
                    {"payload": dict(item.runtime_node.payload)}
                ),
                item.runtime_node.runtime_node_id,
            ),
        )
        for index, item in enumerate(ordered, start=1):
            final_names[item.runtime_node.runtime_node_id] = (
                name if len(ordered) == 1 else f"{name}_{index}"
            )

    result: dict[ScopedSourceRefKey, PlanningReadAuthority] = {}
    for item in candidates:
        runtime_id = item.runtime_node.runtime_node_id
        ref_name = final_names[runtime_id]
        key = ScopedSourceRefKey(
            item.runtime_node.owner_scope_id,
            ref_name,
            item.kind,
        )
        if key in result:
            raise _error(
                "planner.problem_planning_ref_ambiguous",
                "$.ref_authorities",
                (
                    f"SourceRef {ref_name!r} maps to multiple runtime nodes "
                    f"inside scope {key.owner_scope_id!r}"
                ),
            )
        visible_goals = (
            (item.source_unit_ids[0],)
            if item.usage == "answer"
            else visible_goals_by_scope[item.runtime_node.owner_scope_id]
        )
        result[key] = PlanningReadAuthority(
            semantic_ref=SemanticRef(
                ref=ref_name,
                kind=item.kind,
                value_type=item.value_type,
            ),
            runtime_node_id=runtime_id,
            source_unit_ids=item.source_unit_ids,
            owner_scope_id=item.runtime_node.owner_scope_id,
            visible_goal_unit_ids=visible_goals,
            usage=item.usage,
        )

    input_names_by_scope: dict[str, set[str]] = {}
    for authority in result.values():
        if authority.usage == "input":
            input_names_by_scope.setdefault(authority.owner_scope_id, set()).add(
                authority.semantic_ref.ref
            )
    for authority in result.values():
        if authority.usage != "input":
            continue
        path = scope_paths[authority.owner_scope_id]
        shadowed_ancestors = tuple(
            scope_id
            for scope_id in path[:-1]
            if authority.semantic_ref.ref in input_names_by_scope.get(scope_id, set())
        )
        if shadowed_ancestors:
            raise _error(
                "planner.problem_planning_ref_ambiguous",
                "$.ref_authorities",
                (
                    f"SourceRef {authority.semantic_ref.ref!r} in scope "
                    f"{authority.owner_scope_id!r} shadows ancestor scope "
                    f"{shadowed_ancestors[-1]!r}"
                ),
            )
    return MappingProxyType(
        dict(sorted(result.items(), key=lambda item: item[0].sort_key()))
    )


def _goal_view(
    goal: _GoalRecord,
    *,
    scope_records: Sequence[_ScopeRecord],
    authorities: Mapping[ScopedSourceRefKey, PlanningReadAuthority],
    scope_path_by_runtime_id: Mapping[str, tuple[str, ...]],
    prompt_source_payloads: Mapping[str, Mapping[str, Any]],
) -> ProblemPlanningGoalView:
    answer_authorities = [
        authority
        for authority in authorities.values()
        if authority.usage == "answer"
        and authority.runtime_node_id == goal.answer_runtime_node_id
    ]
    if len(answer_authorities) != 1:
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.goal_views",
            f"Goal {goal.source_goal.unit_id!r} does not have exactly one answer ref",
        )
    if answer_authorities[0].source_unit_ids != (goal.source_goal.unit_id,):
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.goal_views",
            f"Goal {goal.source_goal.unit_id!r} answer provenance has drifted",
        )
    path = scope_path_by_runtime_id[goal.owner_scope_id]
    known_scope_ids = {item.scope_id for item in scope_records}
    if any(scope_id not in known_scope_ids for scope_id in path):
        raise _error(
            "planner.problem_scope_visibility_drift",
            "$.goal_views",
            "Goal scope path contains an unknown scope",
        )
    return ProblemPlanningGoalView(
        goal_unit_id=goal.source_goal.unit_id,
        goal_kind=goal.source_goal.kind,
        answer_key=goal.answer_key,
        owner_scope_id=goal.owner_scope_id,
        scope_path=path,
        visible_scope_ids=path,
        answer_ref=answer_authorities[0].semantic_ref,
        semantic_reads=tuple(
            sorted(
                (
                    authority.semantic_ref
                    for authority in authorities.values()
                    if authority.usage == "input"
                    and goal.source_goal.unit_id in authority.visible_goal_unit_ids
                ),
                key=lambda item: (item.kind, item.ref),
            )
        ),
        goal_payload=prompt_source_payloads[goal.source_goal.unit_id],
    )


def _audit_source_coverage(
    records: Mapping[str, ProblemUnitRecord],
    *,
    planning_scopes: Sequence[ProblemPlanningScope],
    goal_views: Sequence[ProblemPlanningGoalView],
) -> None:
    represented: list[str] = []
    for scope in planning_scopes:
        represented.append(scope.source_scope_unit_id)
        represented.extend(item.source_unit_id for item in scope.entities)
        represented.extend(item.source_unit_id for item in scope.facts)
    represented.extend(goal.goal_unit_id for goal in goal_views)
    expected = {
        unit_id for unit_id, record in records.items() if record.unit_kind != "family"
    }
    if set(represented) != expected or len(represented) != len(set(represented)):
        raise _error(
            "planner.problem_planning_projection_drift",
            "$.scopes",
            "source scope/entity/fact/goal coverage is incomplete or duplicated",
        )


def _audit_authority_visibility(
    authorities: Mapping[ScopedSourceRefKey, PlanningReadAuthority],
    *,
    scope_path_by_runtime_id: Mapping[str, tuple[str, ...]],
    records: Mapping[str, ProblemUnitRecord],
    scope_records: Sequence[_ScopeRecord],
) -> None:
    runtime_scope_by_source_path = {
        item.source_scope.path_id: item.scope_id for item in scope_records
    }
    for scoped_key, authority in authorities.items():
        if scoped_key != authority.scoped_key:
            raise _error(
                "planner.problem_planning_ref_ambiguous",
                "$.ref_authorities",
                "scoped SourceRef authority key differs from its payload",
            )
        owner_path = scope_path_by_runtime_id[authority.owner_scope_id]
        for source_unit_id in authority.source_unit_ids:
            record = records.get(source_unit_id)
            if record is None:
                raise _error(
                    "planner.problem_planning_projection_drift",
                    "$.ref_authorities",
                    f"SemanticRef references unknown source unit {source_unit_id!r}",
                )
            source_scope_id = runtime_scope_by_source_path.get(record.scope_path)
            if source_scope_id is None:
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    "$.ref_authorities",
                    f"source unit {source_unit_id!r} has no runtime scope",
                )
            source_path = scope_path_by_runtime_id[source_scope_id]
            if not (
                _is_prefix(source_path, owner_path)
                or _is_prefix(owner_path, source_path)
            ):
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    "$.ref_authorities",
                    f"runtime node {authority.runtime_node_id!r} crosses sibling scopes",
                )
        if authority.usage == "answer" and len(authority.visible_goal_unit_ids) != 1:
            raise _error(
                "planner.problem_scope_visibility_drift",
                "$.ref_authorities",
                "answer refs must be visible to exactly one Goal",
            )


def _audit_goal_read_catalog(
    *,
    planning_scopes: Sequence[ProblemPlanningScope],
    goal_views: Sequence[ProblemPlanningGoalView],
    authorities: Mapping[ScopedSourceRefKey, PlanningReadAuthority],
) -> None:
    scopes = {item.scope_id: item for item in planning_scopes}
    for goal in goal_views:
        expected_refs = {
            ref.ref
            for scope_id in goal.visible_scope_ids
            for ref in scopes[scope_id].available_refs
        }
        actual_refs = {item.ref for item in goal.semantic_reads}
        if actual_refs != expected_refs or len(actual_refs) != len(goal.semantic_reads):
            raise _error(
                "planner.problem_scope_visibility_drift",
                "$.goal_views",
                f"Goal {goal.goal_unit_id!r} read catalog differs from visible scopes",
            )
        for ref in goal.semantic_reads:
            matches = tuple(
                authority
                for authority in authorities.values()
                if authority.semantic_ref == ref
                and authority.usage == "input"
                and authority.owner_scope_id in goal.visible_scope_ids
                and goal.goal_unit_id in authority.visible_goal_unit_ids
            )
            if len(matches) != 1:
                raise _error(
                    "planner.problem_scope_visibility_drift",
                    "$.goal_views",
                    f"Goal {goal.goal_unit_id!r} includes an unauthorized SemanticRef",
                )


def _audit_prompt_payload(
    payload: Mapping[str, Any],
    *,
    forbidden_values: set[str],
) -> None:
    forbidden_keys = {
        "source_unit_id",
        "source_unit_ids",
        "runtime_node_id",
        "artifact_id",
        "bundle_authority_token",
        "authority_token",
        "math_object_id",
        "state_version_id",
    }

    errors = sorted(
        Draft202012Validator(planner_problem_view_schema()).iter_errors(
            payload
        ),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        first = errors[0]
        raise _error(
            "planner.problem_planning_context_invalid",
            _json_path(first.absolute_path),
            first.message,
        )

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                normalized = str(key).lower()
                if normalized in forbidden_keys:
                    raise _error(
                        "planner.problem_planning_context_invalid",
                        path,
                        f"prompt payload exposes internal field {key!r}",
                    )
                visit(item, f"{path}.{key}")
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, str) and value in forbidden_values:
            raise _error(
                "planner.problem_planning_context_invalid",
                path,
                "prompt payload exposes an internal authority value",
            )

    visit(payload, "$")


def _internal_authority_values(
    bundle: VerifiedSolverProblemBundle,
    records: Mapping[str, ProblemUnitRecord],
    runtime_nodes: Mapping[str, _RuntimeNode],
) -> set[str]:
    token = bundle.authority_token
    result = {
        *records,
        *runtime_nodes,
        token.extraction_context_id,
        token.dependency_hash,
        token.problem_revision_id,
        token.problem_semantic_hash,
        token.bundle_id,
    }
    for payload in bundle.artifact_refs.authority_payload().values():
        artifact_id = payload.get("artifact_id")
        if isinstance(artifact_id, str):
            result.add(artifact_id)
    return result


def _json_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def _runtime_references(
    payload: Mapping[str, Any],
    runtime_ids: set[str],
) -> tuple[str, ...]:
    result: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            if value in runtime_ids and value not in result:
                result.append(value)
        elif isinstance(value, Mapping):
            for key, item in value.items():
                if key not in {"handle", "scope_id", "valid_scope"}:
                    visit(item)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for item in value:
                visit(item)

    visit(payload)
    return tuple(result)


def _runtime_semantic_name(runtime_id: str) -> str:
    parts = runtime_id.split(":")
    return parts[-1] if parts else runtime_id


def _semantic_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_").lower()
    return normalized or "value"


def _ref_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r"[^0-9A-Za-z_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "value"


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return tuple(result)


def _is_prefix(left: Sequence[str], right: Sequence[str]) -> bool:
    return len(left) <= len(right) and tuple(right[: len(left)]) == tuple(left)


def _mapping_rows(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise _error(
            "planner.problem_planning_projection_drift",
            path,
            "canonical collection must be an array",
        )
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise _error(
                "planner.problem_planning_projection_drift",
                f"{path}[{index}]",
                "canonical row must be an object",
            )
        result.append(item)
    return tuple(result)


def _error(code: str, path: str, message: str) -> ProblemPlanningContextError:
    return ProblemPlanningContextError(code, path, message)
