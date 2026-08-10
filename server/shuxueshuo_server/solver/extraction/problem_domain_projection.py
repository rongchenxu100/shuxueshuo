"""Deterministic projection from verified problem-domain graphs to Solver ProblemIR."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from jsonschema import Draft202012Validator
import sympy as sp

from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDomainError,
    ProblemEntity,
    ProblemFact,
    ProblemGoal,
    ProblemGraph,
    ProblemScope,
    VerifiedProblem,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input
from shuxueshuo_server.solver.extraction.source_identity import (
    stable_hash,
    thaw_json,
)


SOLVER_PROBLEM_PROJECTION_CONTRACT = "solver-problem-projection/v1"


_ENTITY_RUNTIME_KIND = {
    "symbol": "symbol",
    "point": "point",
    "quadratic_function": "function",
    "named_line": "line",
    "named_ray": "ray",
    "polygon": "polygon",
    "scalar_expression": "expression",
}


def _normalized_source_name(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()


@dataclass(frozen=True)
class RuntimeProjectionManifest:
    problem_id: str
    family_id: str
    problem_revision_id: str
    problem_semantic_hash: str
    runtime_node_sources: Mapping[str, tuple[str, ...]]
    value_object_sources: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "runtime_node_sources",
            _freeze_source_mapping(self.runtime_node_sources),
        )
        object.__setattr__(
            self,
            "value_object_sources",
            _freeze_source_mapping(self.value_object_sources),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "family_id": self.family_id,
            "problem_revision_id": self.problem_revision_id,
            "problem_semantic_hash": self.problem_semantic_hash,
            "runtime_node_sources": {
                key: list(value)
                for key, value in sorted(self.runtime_node_sources.items())
            },
            "value_object_sources": {
                key: list(value)
                for key, value in sorted(self.value_object_sources.items())
            },
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RuntimeProjectionManifest":
        return cls(
            problem_id=str(payload["problem_id"]),
            family_id=str(payload["family_id"]),
            problem_revision_id=str(payload["problem_revision_id"]),
            problem_semantic_hash=str(payload["problem_semantic_hash"]),
            runtime_node_sources=_source_mapping_from_payload(
                payload["runtime_node_sources"],
                "$.manifest.runtime_node_sources",
            ),
            value_object_sources=_source_mapping_from_payload(
                payload["value_object_sources"],
                "$.manifest.value_object_sources",
            ),
        )


@dataclass(frozen=True)
class SolverProblemProjection:
    canonical_input: Mapping[str, Any]
    problem: ProblemIR
    manifest: RuntimeProjectionManifest

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SOLVER_PROBLEM_PROJECTION_CONTRACT,
            "canonical_input": deepcopy(dict(self.canonical_input)),
            "manifest": self.manifest.to_payload(),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SolverProblemProjection":
        errors = sorted(
            _solver_problem_projection_validator().iter_errors(payload),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            first = errors[0]
            path = "$" + "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}"
                for part in first.absolute_path
            )
            raise ProblemDomainError(
                "extraction.problem_projection_failed",
                path,
                first.message,
            )
        canonical_input = payload["canonical_input"]
        manifest_payload = payload["manifest"]
        assert isinstance(canonical_input, Mapping)
        assert isinstance(manifest_payload, Mapping)
        try:
            problem = problem_from_canonical_input(canonical_input)
        except Exception as exc:
            raise ProblemDomainError(
                "extraction.problem_projection_failed",
                "$.canonical_input",
                f"Solver ProblemIR projection failed: {exc}",
            ) from exc
        manifest = RuntimeProjectionManifest.from_payload(manifest_payload)
        if manifest.problem_id != str(canonical_input["problem_id"]):
            raise ProblemDomainError(
                "extraction.problem_projection_failed",
                "$.manifest.problem_id",
                "projection manifest problem_id differs from canonical input",
            )
        return cls(
            canonical_input=canonical_input,
            problem=problem,
            manifest=manifest,
        )

    @property
    def projection_hash(self) -> str:
        return stable_hash(self.to_payload())


def solver_problem_projection_schema() -> dict[str, Any]:
    source_mapping = {
        "type": "object",
        "minProperties": 1,
        "additionalProperties": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "solver-problem-projection.schema.json",
        "title": "Solver Problem Projection",
        "type": "object",
        "required": ["schema_version", "canonical_input", "manifest"],
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": SOLVER_PROBLEM_PROJECTION_CONTRACT},
            "canonical_input": {"type": "object"},
            "manifest": {
                "type": "object",
                "required": [
                    "problem_id",
                    "family_id",
                    "problem_revision_id",
                    "problem_semantic_hash",
                    "runtime_node_sources",
                    "value_object_sources",
                ],
                "additionalProperties": False,
                "properties": {
                    "problem_id": {"type": "string", "minLength": 1},
                    "family_id": {"type": "string", "minLength": 1},
                    "problem_revision_id": {
                        "type": "string",
                        "pattern": "^(problem-revision:[a-f0-9]{64}|unverified)$",
                    },
                    "problem_semantic_hash": {
                        "type": "string",
                        "pattern": "^[a-f0-9]{64}$",
                    },
                    "runtime_node_sources": source_mapping,
                    "value_object_sources": {
                        **source_mapping,
                        "minProperties": 0,
                    },
                },
            },
        },
    }


def _solver_problem_projection_validator() -> Draft202012Validator:
    schema = solver_problem_projection_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _freeze_source_mapping(
    value: Mapping[str, Sequence[str]],
) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType(
        {
            str(key): tuple(sorted({str(item) for item in sources}))
            for key, sources in sorted(value.items())
        }
    )


def _source_mapping_from_payload(
    value: Any,
    path: str,
) -> Mapping[str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise ProblemDomainError(
            "extraction.problem_projection_failed",
            path,
            "source mapping must be an object",
        )
    return {
        str(key): tuple(str(item) for item in sources)
        for key, sources in value.items()
    }


@dataclass(frozen=True)
class ResolvedDomainEntity:
    scope: ProblemScope
    entity: ProblemEntity
    canonical_scope_id: str
    handle: str


class ProblemDomainIndex:
    """Lexical scope and typed identity authority shared by validation/projection."""

    def __init__(self, graph: ProblemGraph) -> None:
        self.graph = graph
        scopes = tuple(graph.root_scope.iter_scopes())
        self.scope_by_path = {scope.path_id: scope for scope in scopes}
        self.scope_by_unit_id = {scope.unit_id: scope for scope in scopes}
        self.parent_path = {
            scope.path_id: (
                "/".join(scope.path[:-1]) if len(scope.path) > 1 else None
            )
            for scope in scopes
        }
        local_scope_counts: dict[str, int] = {}
        for scope in scopes:
            local_scope_counts[scope.local_id] = local_scope_counts.get(scope.local_id, 0) + 1
        self.canonical_scope_ids = {
            scope.path_id: (
                scope.local_id
                if local_scope_counts[scope.local_id] == 1
                else "_".join(scope.path)
            )
            for scope in scopes
        }
        self.entities_by_scope: dict[str, dict[str, ProblemEntity]] = {}
        self.entity_by_unit_id: dict[str, ResolvedDomainEntity] = {}
        self.entity_by_handle: dict[str, ResolvedDomainEntity] = {}
        for scope in scopes:
            local = {item.local_id: item for item in scope.entities}
            self.entities_by_scope[scope.path_id] = local
            for entity in scope.entities:
                runtime_kind = _ENTITY_RUNTIME_KIND.get(entity.kind, entity.kind)
                tail = _handle_tail(entity)
                handle = f"{runtime_kind}:{self.canonical_scope_ids[scope.path_id]}:{tail}"
                resolved = ResolvedDomainEntity(
                    scope=scope,
                    entity=entity,
                    canonical_scope_id=self.canonical_scope_ids[scope.path_id],
                    handle=handle,
                )
                self.entity_by_unit_id[entity.unit_id] = resolved
                if handle in self.entity_by_handle:
                    raise ProblemDomainError(
                        "extraction.problem_projection_failed",
                        "$.root",
                        f"runtime handle collision {handle!r}",
                    )
                self.entity_by_handle[handle] = resolved

    def ancestor_paths(self, scope_path: str) -> tuple[str, ...]:
        result: list[str] = []
        current: str | None = scope_path
        while current is not None:
            result.append(current)
            current = self.parent_path[current]
        return tuple(result)

    def resolve(self, scope_path: str, local_id: str) -> ResolvedDomainEntity:
        for candidate_scope in self.ancestor_paths(scope_path):
            entity = self.entities_by_scope[candidate_scope].get(local_id)
            if entity is not None:
                return self.entity_by_unit_id[entity.unit_id]
        raise ProblemDomainError(
            "extraction.problem_reference_unresolved",
            f"$.root[{scope_path}]",
            f"entity reference {local_id!r} is not visible from {scope_path!r}",
        )

    def out_of_scope_matches(
        self,
        scope_path: str,
        reference: str,
        expected: Sequence[str] | None = None,
    ) -> tuple[ResolvedDomainEntity, ...]:
        """Find exact source identities that exist outside the lexical scope chain."""

        visible_paths = set(self.ancestor_paths(scope_path))
        normalized_reference = _normalized_source_name(reference)
        matches: list[ResolvedDomainEntity] = []
        for resolved in self.entity_by_unit_id.values():
            if resolved.scope.path_id in visible_paths:
                continue
            entity = resolved.entity
            same_identity = entity.local_id == reference
            if tuple(expected or ()) == ("symbol",):
                same_identity = same_identity or (
                    entity.kind == "symbol"
                    and _normalized_source_name(entity.label) == normalized_reference
                )
            if not same_identity:
                continue
            if expected is not None and entity.kind not in expected:
                continue
            matches.append(resolved)
        return tuple(
            sorted(
                matches,
                key=lambda item: (item.scope.path_id, item.entity.unit_id),
            )
        )

    def lowest_common_ancestor_path(self, *scope_paths: str) -> str:
        if not scope_paths:
            raise ValueError("at least one scope path is required")
        split_paths = [path.split("/") for path in scope_paths]
        common: list[str] = []
        for parts in zip(*split_paths):
            if len(set(parts)) != 1:
                break
            common.append(parts[0])
        if not common:
            raise ProblemDomainError(
                "extraction.problem_scope_invalid",
                "$.root",
                f"scope paths do not share a root: {scope_paths!r}",
            )
        return "/".join(common)

    def resolve_kind(
        self,
        scope_path: str,
        local_id: str,
        expected: Sequence[str],
    ) -> ResolvedDomainEntity:
        if tuple(expected) == ("symbol",):
            return self.resolve_symbol_name(scope_path, local_id)
        resolved = self.resolve(scope_path, local_id)
        if resolved.entity.kind not in expected:
            raise ProblemDomainError(
                "extraction.problem_reference_type_mismatch",
                f"$.root[{scope_path}]",
                f"{local_id!r} is {resolved.entity.kind!r}, expected {list(expected)!r}",
            )
        return resolved

    def resolve_symbol_name(
        self,
        scope_path: str,
        reference: str,
    ) -> ResolvedDomainEntity:
        """Resolve a Symbol by local id or its unique printed label.

        Algebraic expressions naturally use source names such as ``x`` and ``a``.
        Requiring those strings to duplicate model-local ids adds no semantic
        authority, so Symbol references alone also accept the nearest unique label.
        Other entity kinds remain local-id-only.
        """

        try:
            resolved = self.resolve(scope_path, reference)
        except ProblemDomainError as error:
            if error.code != "extraction.problem_reference_unresolved":
                raise
        else:
            if resolved.entity.kind != "symbol":
                raise ProblemDomainError(
                    "extraction.problem_reference_type_mismatch",
                    f"$.root[{scope_path}]",
                    f"{reference!r} is {resolved.entity.kind!r}, expected ['symbol']",
                )
            return resolved

        normalized = _normalized_source_name(reference)
        for candidate_scope in self.ancestor_paths(scope_path):
            matches = [
                self.entity_by_unit_id[entity.unit_id]
                for entity in self.entities_by_scope[candidate_scope].values()
                if entity.kind == "symbol"
                and _normalized_source_name(entity.label) == normalized
            ]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise ProblemDomainError(
                    "extraction.problem_reference_ambiguous",
                    f"$.root[{scope_path}]",
                    f"symbol label {reference!r} matches multiple entities in {candidate_scope!r}",
                )
        raise ProblemDomainError(
            "extraction.problem_reference_unresolved",
            f"$.root[{scope_path}]",
            f"symbol reference {reference!r} is not visible from {scope_path!r}",
        )


class ProblemDomainProjector:
    def project(self, problem: VerifiedProblem) -> SolverProblemProjection:
        return self.project_graph(
            problem.graph,
            revision_id=problem.revision_id,
            semantic_hash=problem.semantic_hash,
        )

    def project_graph(
        self,
        graph: ProblemGraph,
        *,
        revision_id: str = "unverified",
        semantic_hash: str | None = None,
    ) -> SolverProblemProjection:
        index = ProblemDomainIndex(graph)
        family = next(
            (
                item
                for item in DEFAULT_FAMILY_REGISTRY.families
                if item.family_id == graph.family_id
            ),
            None,
        )
        if family is None or len(family.match.patterns) != 1 or len(family.match.problem_types) != 1:
            raise ProblemDomainError(
                "extraction.problem_family_unresolved",
                "$.family_id",
                "selected family must provide one pattern and one problem_type",
            )

        runtime_sources: dict[str, set[str]] = {}
        value_sources: dict[str, set[str]] = {}
        segments = _SegmentMaterializer(index, runtime_sources, value_sources)
        facts_by_scope = {
            scope.path_id: tuple(scope.facts) for scope in graph.root_scope.iter_scopes()
        }
        fact_handle_by_unit = {
            fact.unit_id: _fact_handle(index, scope, fact)
            for scope in graph.root_scope.iter_scopes()
            for fact in scope.facts
        }

        canonical_entities: list[dict[str, Any]] = []
        for scope in graph.root_scope.iter_scopes():
            for entity in scope.entities:
                resolved = index.entity_by_unit_id[entity.unit_id]
                payload, source_unit_ids = self._project_entity(
                    resolved,
                    facts_by_scope=facts_by_scope,
                    index=index,
                )
                canonical_entities.append(payload)
                runtime_sources.setdefault(resolved.handle, set()).update(source_unit_ids)

        canonical_facts: list[dict[str, Any]] = []
        paired_units: set[str] = set()
        for scope in graph.root_scope.iter_scopes():
            right_angles = [item for item in scope.facts if item.kind == "right_angle"]
            equal_lengths = [item for item in scope.facts if item.kind == "equal_length"]
            if len(right_angles) == 1 and len(equal_lengths) == 1:
                right = right_angles[0]
                equal = equal_lengths[0]
                handle = _combined_fact_handle(index, scope, right, equal)
                angle = _angle_handles(index, scope.path_id, right.attributes["angle"])
                left = segments.materialize(scope, equal.attributes["left"], equal.unit_id)
                right_segment = segments.materialize(
                    scope, equal.attributes["right"], equal.unit_id
                )
                canonical_facts.append(
                    {
                        "handle": handle,
                        "type": "right_angle_equal_length",
                        "scope_id": index.canonical_scope_ids[scope.path_id],
                        "valid_scope": index.canonical_scope_ids[scope.path_id],
                        "description": "直角与等长条件",
                        "angle": list(angle),
                        "equal_segments": [left, right_segment],
                    }
                )
                runtime_sources[handle] = {right.unit_id, equal.unit_id}
                paired_units.update((right.unit_id, equal.unit_id))

            for fact in scope.facts:
                if fact.unit_id in paired_units or fact.kind == "function_expression":
                    continue
                if (
                    fact.kind == "point_construction"
                    and fact.attributes.get("construction") != "curve_at_x"
                ):
                    continue
                projected = self._project_fact(
                    scope,
                    fact,
                    index=index,
                    segments=segments,
                    fact_handle_by_unit=fact_handle_by_unit,
                )
                if projected is None:
                    continue
                canonical_facts.append(projected)
                runtime_sources.setdefault(str(projected["handle"]), set()).add(fact.unit_id)

        canonical_entities.extend(segments.entities)

        canonical_goals: list[dict[str, Any]] = []
        for scope in graph.root_scope.iter_scopes():
            for goal in scope.goals:
                projected = self._project_goal(
                    scope,
                    goal,
                    index=index,
                    segments=segments,
                    family_id=graph.family_id,
                    canonical_facts=canonical_facts,
                )
                canonical_goals.append(projected)
                runtime_sources.setdefault(str(projected["handle"]), set()).add(goal.unit_id)

        scopes = [
            {
                "scope_id": index.canonical_scope_ids[scope.path_id],
                "label": scope.label,
                "parent": (
                    index.canonical_scope_ids[index.parent_path[scope.path_id]]
                    if index.parent_path[scope.path_id] is not None
                    else None
                ),
                **(
                    {"asks": [goal.answer_key for goal in scope.goals]}
                    if scope.goals
                    else {}
                ),
            }
            for scope in graph.root_scope.iter_scopes()
        ]
        for scope in graph.root_scope.iter_scopes():
            runtime_sources.setdefault(
                f"scope:{index.canonical_scope_ids[scope.path_id]}", set()
            ).add(scope.unit_id)

        canonical_input: dict[str, Any] = {
            "problem_id": graph.problem_id,
            "pattern": family.match.patterns[0],
            "problem_type": family.match.problem_types[0],
            "original_text": {
                "number": graph.source.question_number,
                **({"score": graph.source.score} if graph.source.score is not None else {}),
                "lines": list(graph.original_text_lines),
            },
            "scopes": scopes,
            "entities": canonical_entities,
            "facts": canonical_facts,
            "question_goals": canonical_goals,
        }
        projected_source_units = {
            source_unit_id
            for source_unit_ids in runtime_sources.values()
            for source_unit_id in source_unit_ids
        }
        required_source_units = {
            unit_id
            for scope in graph.root_scope.iter_scopes()
            for unit_id in (
                scope.unit_id,
                *(item.unit_id for item in scope.entities),
                *(item.unit_id for item in scope.facts),
                *(item.unit_id for item in scope.goals),
            )
        }
        missing_source_units = sorted(required_source_units - projected_source_units)
        if missing_source_units:
            raise ProblemDomainError(
                "extraction.problem_projection_failed",
                "$.manifest.runtime_node_sources",
                "source unit has no runtime projection: " + missing_source_units[0],
            )
        try:
            runtime_problem = problem_from_canonical_input(canonical_input)
        except Exception as exc:
            raise ProblemDomainError(
                "extraction.problem_projection_failed",
                "$",
                f"Solver ProblemIR projection failed: {exc}",
            ) from exc
        return SolverProblemProjection(
            canonical_input=canonical_input,
            problem=runtime_problem,
            manifest=RuntimeProjectionManifest(
                problem_id=graph.problem_id,
                family_id=graph.family_id,
                problem_revision_id=revision_id,
                problem_semantic_hash=semantic_hash or graph.semantic_hash,
                runtime_node_sources={
                    key: tuple(sorted(value)) for key, value in runtime_sources.items()
                },
                value_object_sources={
                    key: tuple(sorted(value)) for key, value in value_sources.items()
                },
            ),
        )

    @staticmethod
    def _project_entity(
        resolved: ResolvedDomainEntity,
        *,
        facts_by_scope: Mapping[str, tuple[ProblemFact, ...]],
        index: ProblemDomainIndex,
    ) -> tuple[dict[str, Any], tuple[str, ...]]:
        entity = resolved.entity
        scope_path = resolved.scope.path_id
        source_unit_ids = {entity.unit_id}
        base: dict[str, Any] = {
            "handle": resolved.handle,
            "entity_type": _ENTITY_RUNTIME_KIND[entity.kind],
            "name": _handle_tail(entity),
            "scope_id": resolved.canonical_scope_id,
            "description": entity.label,
        }
        attrs = entity.attributes
        if entity.kind == "symbol":
            base["role"] = str(attrs["role"])
            return base, tuple(sorted(source_unit_ids))
        if entity.kind == "quadratic_function":
            expression_fact = _visible_fact_for_entity(
                index,
                scope_path,
                "function_expression",
                "function",
                entity.local_id,
            )
            if expression_fact is None:
                raise ProblemDomainError(
                    "extraction.problem_projection_failed",
                    f"$.root[{scope_path}].entities[{entity.local_id}]",
                    "quadratic function is missing function_expression",
                )
            source_unit_ids.add(expression_fact.unit_id)
            base.update(
                {
                    "function_type": "quadratic",
                    "expression": str(expression_fact.attributes["expression"]),
                }
            )
            equation = next(
                (
                    fact
                    for candidate_scope in index.ancestor_paths(scope_path)
                    for fact in facts_by_scope[candidate_scope]
                    if fact.kind == "equation"
                ),
                None,
            )
            if equation is not None:
                base["coefficient_relation"] = str(equation.attributes["expression"])
                source_unit_ids.add(equation.unit_id)
            return base, tuple(sorted(source_unit_ids))
        if entity.kind == "named_ray":
            base["origin"] = index.resolve_kind(
                scope_path, str(attrs["origin"]), ("point",)
            ).handle
            base["through"] = index.resolve_kind(
                scope_path, str(attrs["through"]), ("point",)
            ).handle
            return base, tuple(sorted(source_unit_ids))
        if entity.kind == "named_line":
            base["points"] = [
                index.resolve_kind(scope_path, str(item), ("point",)).handle
                for item in attrs["points"]
            ]
            return base, tuple(sorted(source_unit_ids))
        if entity.kind == "polygon":
            base.update(
                {
                    "shape": "polygon",
                    "vertices": [
                        index.resolve_kind(scope_path, str(item), ("point",)).handle
                        for item in attrs["vertices"]
                    ],
                }
            )
            return base, tuple(sorted(source_unit_ids))
        if entity.kind == "scalar_expression":
            base["expression"] = str(attrs["expression"])
            return base, tuple(sorted(source_unit_ids))
        if entity.kind != "point":
            return base, tuple(sorted(source_unit_ids))

        relevant = _facts_targeting_entity(index, scope_path, entity.local_id)
        coordinate = next((fact for fact in relevant if fact.kind == "point_coordinate"), None)
        construction = next((fact for fact in relevant if fact.kind == "point_construction"), None)
        relation = next(
            (
                fact
                for fact in relevant
                if fact.kind
                in {
                    "point_on_curve_with_x",
                    "point_on_segment",
                    "point_on_ray",
                    "point_on_axis",
                    "midpoint",
                    "square",
                    "square_center",
                }
            ),
            None,
        )
        if coordinate is not None:
            base["coordinate"] = [str(item) for item in coordinate.attributes["value"]]
            source_unit_ids.add(coordinate.unit_id)
        if construction is not None:
            _apply_point_construction(base, construction, scope_path, index)
            source_unit_ids.add(construction.unit_id)
        elif relation is not None:
            _apply_relation_owned_point_definition(base, relation, scope_path, index)
            source_unit_ids.add(relation.unit_id)
        return base, tuple(sorted(source_unit_ids))

    @staticmethod
    def _project_fact(
        scope: ProblemScope,
        fact: ProblemFact,
        *,
        index: ProblemDomainIndex,
        segments: "_SegmentMaterializer",
        fact_handle_by_unit: Mapping[str, str],
    ) -> dict[str, Any] | None:
        attrs = thaw_json(fact.attributes)
        scope_id = index.canonical_scope_ids[scope.path_id]
        base = {
            "handle": fact_handle_by_unit[fact.unit_id],
            "scope_id": scope_id,
            "valid_scope": scope_id,
            "description": fact.kind.replace("_", " "),
        }
        kind = fact.kind
        if kind == "equation":
            return {
                **base,
                "type": "coefficient_relation",
                "equation": str(attrs["expression"]),
                "subjects": [
                    index.resolve_kind(scope.path_id, str(item), ("symbol",)).handle
                    for item in attrs["symbols"]
                ],
            }
        if kind == "symbol_constraint":
            return {
                **base,
                "type": "symbol_constraint",
                "subject": index.resolve_kind(
                    scope.path_id, str(attrs["symbol"]), ("symbol",)
                ).handle,
                "operator": str(attrs["operator"]),
                "value": str(attrs["value"]),
            }
        if kind == "symbol_value":
            return {
                **base,
                "type": "symbol_value",
                "subject": index.resolve_kind(
                    scope.path_id, str(attrs["symbol"]), ("symbol",)
                ).handle,
                "value": str(attrs["value"]),
            }
        if kind == "point_coordinate":
            return {
                **base,
                "type": "point_coordinate",
                "subject": index.resolve_kind(
                    scope.path_id, str(attrs["point"]), ("point",)
                ).handle,
                "value": [str(item) for item in attrs["value"]],
            }
        if kind == "point_construction":
            if attrs.get("construction") != "curve_at_x":
                return None
            point = index.resolve_kind(
                scope.path_id, str(attrs["point"]), ("point",)
            ).handle
            curve = index.resolve_kind(
                scope.path_id,
                str(attrs["owner"]),
                ("quadratic_function",),
            ).handle
            try:
                x_symbol = index.resolve_symbol_name(
                    scope.path_id,
                    str(attrs["x_expression"]),
                )
            except ProblemDomainError:
                x_symbol = None
            interval = (
                _visible_symbol_interval(index, scope.path_id, x_symbol)
                if x_symbol is not None
                else None
            )
            if x_symbol is not None and interval is not None:
                return {
                    **base,
                    "type": "point_on_curve_with_x_coordinate",
                    "point": point,
                    "curve": curve,
                    "x_symbol": x_symbol.handle,
                    "x_range": list(interval),
                }
            return {
                **base,
                "type": "point_on_curve",
                "point": point,
                "curve": curve,
            }
        if kind == "point_on_curve":
            return {
                **base,
                "type": "point_on_curve",
                "point": index.resolve_kind(
                    scope.path_id, str(attrs["point"]), ("point",)
                ).handle,
                "curve": index.resolve_kind(
                    scope.path_id, str(attrs["curve"]), ("quadratic_function",)
                ).handle,
            }
        if kind == "point_on_curve_with_x":
            return {
                **base,
                "type": "point_on_curve_with_x_coordinate",
                "point": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                "curve": index.resolve_kind(scope.path_id, str(attrs["curve"]), ("quadratic_function",)).handle,
                "x_symbol": index.resolve_kind(scope.path_id, str(attrs["x_symbol"]), ("symbol",)).handle,
                "x_range": [str(item) for item in attrs["x_range"]],
            }
        if kind == "point_on_axis":
            if attrs["axis"] == "symmetry":
                return {
                    **base,
                    "type": "axis_membership",
                    "point": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                    "axis_of": index.resolve_kind(scope.path_id, str(attrs["curve"]), ("quadratic_function",)).handle,
                }
            return None
        if kind == "point_on_segment":
            return {
                **base,
                "type": "point_on_segment",
                "point": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                "segment": segments.materialize(scope, attrs["segment"], fact.unit_id),
            }
        if kind == "point_on_ray":
            ray = attrs["ray"]
            if isinstance(ray, str):
                ray_handle = index.resolve_kind(scope.path_id, ray, ("named_ray",)).handle
            else:
                ray_handle = _ray_handle_from_term(index, scope, ray)
            return {
                **base,
                "type": "point_on_ray",
                "point": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                "ray": ray_handle,
            }
        if kind == "quadrant_membership":
            return {
                **base,
                "type": "orientation_constraint",
                "subject": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                "quadrant": str(attrs["quadrant"]),
            }
        if kind == "midpoint":
            term = attrs["segment"]
            return {
                **base,
                "type": "midpoint_definition",
                "point": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                "of": list(_segment_endpoint_handles(index, scope.path_id, term)),
            }
        if kind == "angle_sum":
            return {
                **base,
                "type": "angle_sum",
                "angle_terms": [
                    _angle_name(index, scope.path_id, item) for item in attrs["angles"]
                ],
                "value": str(attrs["value"]),
            }
        if kind == "equal_length":
            return {
                **base,
                "type": "equal_length_condition",
                "left": segments.name(scope, attrs["left"]),
                "right": segments.name(scope, attrs["right"]),
            }
        if kind == "length_value":
            segment_handle = segments.materialize(scope, attrs["segment"], fact.unit_id)
            if int(attrs["power"]) == 2:
                return {**base, "type": "length_squared", "segment": segment_handle, "value": str(attrs["value"])}
            try:
                squared_value = sp.sstr(
                    sp.simplify(sp.sympify(str(attrs["value"])) ** 2)
                )
            except (TypeError, ValueError, sp.SympifyError) as exc:
                raise ProblemDomainError(
                    "extraction.problem_projection_failed",
                    f"$.root[{scope.path_id}].facts[{fact.unit_id}]",
                    "length value cannot be projected to squared length",
                ) from exc
            return {
                **base,
                "type": "length_squared",
                "segment": segment_handle,
                "value": squared_value,
            }
        if kind == "length_relation":
            left = attrs["left"]
            right = attrs["right"]
            left_handle = segments.materialize(scope, left["segment"], fact.unit_id)
            right_handle = segments.materialize(scope, right["segment"], fact.unit_id)
            left_scale = str(left["scale"])
            right_scale = str(right["scale"])
            if _is_one(left_scale) and not _is_one(right_scale):
                return {
                    **base,
                    "type": "segment_length_relation",
                    "left_segment": left_handle,
                    "right_segment": right_handle,
                    "scale": right_scale,
                }
            return {
                **base,
                "type": "segment_relation",
                "left": _scaled_length_name(segments, scope, left),
                "right": _scaled_length_name(segments, scope, right),
                "left_term": {"scale": left_scale, "segment": list(_segment_endpoint_handles(index, scope.path_id, left["segment"]))},
                "right_term": {"scale": right_scale, "segment": list(_segment_endpoint_handles(index, scope.path_id, right["segment"]))},
            }
        if kind == "square":
            polygon = index.resolve_kind(scope.path_id, str(attrs["polygon"]), ("polygon",))
            vertices = [
                index.resolve_kind(scope.path_id, str(item), ("point",)).handle
                for item in polygon.entity.attributes["vertices"]
            ]
            return {
                **base,
                "type": "square",
                "vertices": vertices,
                "side": segments.materialize(scope, attrs["side"], fact.unit_id),
                "orientation": _runtime_orientation(attrs["orientation"]),
            }
        if kind == "square_center":
            square_ref = str(attrs["square"])
            square_fact = next(
                (
                    item
                    for candidate_path in index.ancestor_paths(scope.path_id)
                    for item in index.scope_by_path[candidate_path].facts
                    if item.kind == "square" and str(item.attributes["polygon"]) == square_ref
                ),
                None,
            )
            if square_fact is None:
                raise ProblemDomainError(
                    "extraction.problem_projection_failed",
                    f"$.root[{scope.path_id}]",
                    "square_center has no matching square fact",
                )
            return {
                **base,
                "type": "square_center",
                "point": index.resolve_kind(scope.path_id, str(attrs["point"]), ("point",)).handle,
                "square": fact_handle_by_unit[square_fact.unit_id],
            }
        if kind == "minimum_target":
            expression_terms = tuple(attrs["expression"]["terms"])
            projected = {
                **base,
                "type": "path_minimum_target",
                "path": _length_sum_name(segments, scope, attrs["expression"]),
            }
            # Solver ProblemIR's legacy ``terms`` shape cannot encode weights and
            # is authoritative whenever present. Keep a weighted path as text so
            # the shared parser sees every term and its coefficient.
            if all(_is_one(str(item["scale"])) for item in expression_terms):
                projected["terms"] = [
                    list(_segment_endpoint_handles(index, scope.path_id, item["segment"]))
                    for item in expression_terms
                ]
            return projected
        if kind == "minimum_value_given":
            return {
                **base,
                "type": "minimum_value",
                "path": _length_sum_name(segments, scope, attrs["expression"]),
                "value": str(attrs["value"]),
            }
        return None

    @staticmethod
    def _project_goal(
        scope: ProblemScope,
        goal: ProblemGoal,
        *,
        index: ProblemDomainIndex,
        segments: "_SegmentMaterializer",
        family_id: str,
        canonical_facts: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        scope_id = index.canonical_scope_ids[scope.path_id]
        handle = f"answer:{scope_id}.{goal.answer_key}"
        base: dict[str, Any] = {
            "handle": handle,
            "scope_id": scope_id,
            "answer_key": goal.answer_key,
            "required": True,
            "description": f"{scope.label}输出{goal.answer_key}",
        }
        attrs = thaw_json(goal.attributes)
        if goal.kind == "point_coordinate":
            target = index.resolve_kind(scope.path_id, str(attrs["target"]), ("point",))
            value_type = _source_goal_value_type(
                family_id=family_id,
                scope_path=scope.path_id,
                target_handle=target.handle,
                facts=canonical_facts,
                index=index,
                default="Point",
            )
            return {**base, "value_type": value_type, "target_handle": target.handle}
        if goal.kind == "quadratic_equation":
            target = index.resolve_kind(
                scope.path_id, str(attrs["target"]), ("quadratic_function",)
            )
            return {
                **base,
                "value_type": "Parabola",
                "valid_scope": target.canonical_scope_id,
            }
        if goal.kind == "parameter_value":
            index.resolve_kind(
                scope.path_id,
                str(attrs["target"]),
                ("symbol",),
            )
            return {**base, "value_type": "ParameterValue"}
        if goal.kind == "minimum_value":
            _length_sum_name(segments, scope, attrs["expression"])
            return {**base, "value_type": "MinimumExpression"}
        raise ProblemDomainError(
            "extraction.problem_projection_failed",
            f"$.root[{scope.path_id}].goals",
            f"unsupported goal kind {goal.kind!r}",
        )


class _SegmentMaterializer:
    def __init__(
        self,
        index: ProblemDomainIndex,
        runtime_sources: dict[str, set[str]],
        value_sources: dict[str, set[str]],
    ) -> None:
        self.index = index
        self.runtime_sources = runtime_sources
        self.value_sources = value_sources
        self.by_scope: dict[str, dict[str, str]] = {
            path: {} for path in index.scope_by_path
        }
        self.entities: list[dict[str, Any]] = []

    def materialize(
        self,
        scope: ProblemScope,
        value: Mapping[str, Any] | Any,
        source_unit_id: str,
    ) -> str:
        raw = thaw_json(value) if not isinstance(value, dict) else value
        endpoints = _segment_endpoint_handles(self.index, scope.path_id, raw)
        signature = stable_hash(sorted(endpoints))
        for ancestor in self.index.ancestor_paths(scope.path_id):
            existing = self.by_scope[ancestor].get(signature)
            if existing is not None:
                self.runtime_sources.setdefault(existing, set()).add(source_unit_id)
                self.value_sources.setdefault(existing, set()).add(source_unit_id)
                return existing
        scope_id = self.index.canonical_scope_ids[scope.path_id]
        name = _segment_name_from_handles(self.index, endpoints)
        handle = f"segment:{scope_id}:{name}"
        self.by_scope[scope.path_id][signature] = handle
        self.entities.append(
            {
                "handle": handle,
                "entity_type": "segment",
                "name": name,
                "scope_id": scope_id,
                "endpoints": list(endpoints),
                "description": f"线段 {name}",
            }
        )
        self.runtime_sources.setdefault(handle, set()).add(source_unit_id)
        self.value_sources.setdefault(handle, set()).add(source_unit_id)
        return handle

    def name(self, scope: ProblemScope, value: Mapping[str, Any] | Any) -> str:
        raw = thaw_json(value) if not isinstance(value, dict) else value
        return _segment_name_from_handles(
            self.index,
            _segment_endpoint_handles(self.index, scope.path_id, raw),
        )


def _facts_targeting_entity(
    index: ProblemDomainIndex,
    scope_path: str,
    entity_local_id: str,
) -> tuple[ProblemFact, ...]:
    result: list[ProblemFact] = []
    target = index.resolve(scope_path, entity_local_id)
    # Entity metadata is owned by its declaration scope. A descendant may add a
    # local fact about an ancestor entity, but that fact must not rewrite the
    # ancestor's canonical definition or leak into a sibling branch.
    candidate_scope = index.scope_by_path[target.scope.path_id]
    for fact in candidate_scope.facts:
        if fact.kind == "square":
            orientation = fact.attributes.get("orientation")
            value = (
                orientation.get("point")
                if isinstance(orientation, Mapping)
                else None
            )
            if isinstance(value, str):
                try:
                    resolved = index.resolve(candidate_scope.path_id, value)
                except ProblemDomainError:
                    pass
                else:
                    if resolved.entity.unit_id == target.entity.unit_id:
                        result.append(fact)
                        continue
        for key in ("point", "function", "symbol"):
            value = fact.attributes.get(key)
            if not isinstance(value, str):
                continue
            try:
                resolved = index.resolve(candidate_scope.path_id, value)
            except ProblemDomainError:
                continue
            if resolved.entity.unit_id == target.entity.unit_id:
                result.append(fact)
                break
    return tuple(result)


def _visible_symbol_interval(
    index: ProblemDomainIndex,
    scope_path: str,
    target: ResolvedDomainEntity,
) -> tuple[str, str] | None:
    bounds: dict[str, str] = {}
    for candidate_path in index.ancestor_paths(scope_path):
        scope = index.scope_by_path[candidate_path]
        for fact in scope.facts:
            if fact.kind != "symbol_constraint":
                continue
            raw_symbol = fact.attributes.get("symbol")
            if not isinstance(raw_symbol, str):
                continue
            try:
                resolved = index.resolve_symbol_name(candidate_path, raw_symbol)
            except ProblemDomainError:
                continue
            if resolved.entity.unit_id != target.entity.unit_id:
                continue
            operator = str(fact.attributes.get("operator"))
            side = (
                "lower"
                if operator in {">", ">="}
                else "upper"
                if operator in {"<", "<="}
                else None
            )
            if side is None or side in bounds:
                return None
            bounds[side] = str(fact.attributes.get("value"))
    if set(bounds) != {"lower", "upper"}:
        return None
    return bounds["lower"], bounds["upper"]


def _visible_fact_for_entity(
    index: ProblemDomainIndex,
    scope_path: str,
    kind: str,
    field: str,
    local_id: str,
) -> ProblemFact | None:
    target = index.resolve(scope_path, local_id)
    for candidate_path in index.ancestor_paths(scope_path):
        scope = index.scope_by_path[candidate_path]
        for fact in scope.facts:
            if fact.kind != kind:
                continue
            value = fact.attributes.get(field)
            if not isinstance(value, str):
                continue
            if index.resolve(candidate_path, value).entity.unit_id == target.entity.unit_id:
                return fact
    return None


def _apply_point_construction(
    payload: dict[str, Any],
    fact: ProblemFact,
    scope_path: str,
    index: ProblemDomainIndex,
) -> None:
    attrs = thaw_json(fact.attributes)
    construction = str(attrs["construction"])
    mapping = {
        "origin": "coordinate_origin",
        "vertex": "vertex",
        "x_axis_intercept": "x_axis_intercept",
        "y_axis_intercept": "y_axis_intercept",
        "axis_x_intercept": "axis_x_intercept",
        "translated_point": "translated_point",
        "curve_at_x": "point_on_parabola_at_x",
    }
    payload["definition"] = mapping[construction]
    owner = attrs.get("owner")
    if isinstance(owner, str):
        payload["of"] = index.resolve(scope_path, owner).handle
    if attrs.get("exclude_point"):
        payload["exclude_point"] = index.resolve_kind(
            scope_path, str(attrs["exclude_point"]), ("point",)
        ).handle
    for key in ("side", "vector"):
        if key in attrs:
            payload[key] = deepcopy(attrs[key])
    if construction == "curve_at_x":
        payload["x"] = str(attrs["x_expression"])


def _apply_relation_owned_point_definition(
    payload: dict[str, Any],
    fact: ProblemFact,
    scope_path: str,
    index: ProblemDomainIndex,
) -> None:
    attrs = thaw_json(fact.attributes)
    if fact.kind == "point_on_curve_with_x":
        payload.update(
            {
                "definition": "point_on_curve_with_x_coordinate",
                "of": index.resolve_kind(
                    scope_path, str(attrs["curve"]), ("quadratic_function",)
                ).handle,
                "x_symbol": index.resolve_kind(
                    scope_path, str(attrs["x_symbol"]), ("symbol",)
                ).handle,
                "x_range": deepcopy(attrs["x_range"]),
            }
        )
    elif fact.kind == "point_on_segment":
        payload["definition"] = "point_on_segment"
    elif fact.kind == "point_on_ray":
        payload["definition"] = "point_on_ray"
    elif fact.kind == "point_on_axis":
        payload["definition"] = "point_on_axis"
        if attrs.get("curve"):
            payload["of"] = index.resolve_kind(
                scope_path, str(attrs["curve"]), ("quadratic_function",)
            ).handle
    elif fact.kind == "midpoint":
        payload["definition"] = "midpoint"
        payload["of"] = list(
            _segment_endpoint_handles(index, scope_path, attrs["segment"])
        )
    elif fact.kind == "square_center":
        payload["definition"] = "square_diagonal_intersection"
    elif fact.kind == "square":
        payload["definition"] = "square_adjacent_vertex"
        orientation = attrs.get("orientation")
        if isinstance(orientation, Mapping):
            payload["orientation"] = deepcopy(dict(orientation))


def _segment_endpoint_handles(
    index: ProblemDomainIndex,
    scope_path: str,
    value: Mapping[str, Any] | Any,
) -> tuple[str, str]:
    raw = thaw_json(value) if not isinstance(value, Mapping) else value
    return (
        index.resolve_kind(scope_path, str(raw["start"]), ("point",)).handle,
        index.resolve_kind(scope_path, str(raw["end"]), ("point",)).handle,
    )


def _angle_handles(
    index: ProblemDomainIndex,
    scope_path: str,
    value: Mapping[str, Any] | Any,
) -> tuple[str, str, str]:
    raw = thaw_json(value) if not isinstance(value, Mapping) else value
    return (
        index.resolve_kind(scope_path, str(raw["start"]), ("point",)).handle,
        index.resolve_kind(scope_path, str(raw["vertex"]), ("point",)).handle,
        index.resolve_kind(scope_path, str(raw["end"]), ("point",)).handle,
    )


def _angle_name(index: ProblemDomainIndex, scope_path: str, value: Any) -> str:
    return "".join(
        _handle_tail(index.entity_by_handle[handle].entity)
        for handle in _angle_handles(index, scope_path, value)
    )


def _ray_handle_from_term(
    index: ProblemDomainIndex,
    scope: ProblemScope,
    value: Mapping[str, Any],
) -> str:
    origin = index.resolve_kind(scope.path_id, str(value["origin"]), ("point",))
    through = index.resolve_kind(scope.path_id, str(value["through"]), ("point",))
    return (
        f"ray:{index.canonical_scope_ids[scope.path_id]}:"
        f"{_handle_tail(origin.entity)}{_handle_tail(through.entity)}"
    )


def _segment_name_from_handles(
    index: ProblemDomainIndex, endpoints: Sequence[str]
) -> str:
    return "".join(_handle_tail(index.entity_by_handle[item].entity) for item in endpoints)


def _scaled_length_name(
    segments: _SegmentMaterializer,
    scope: ProblemScope,
    value: Mapping[str, Any],
) -> str:
    name = segments.name(scope, value["segment"])
    scale = str(value["scale"])
    return name if _is_one(scale) else f"{scale}*{name}"


def _length_sum_name(
    segments: _SegmentMaterializer,
    scope: ProblemScope,
    value: Mapping[str, Any] | Any,
) -> str:
    raw = thaw_json(value) if not isinstance(value, Mapping) else value
    return "+".join(
        _scaled_length_name(segments, scope, item) for item in raw["terms"]
    )


def _fact_handle(index: ProblemDomainIndex, scope: ProblemScope, fact: ProblemFact) -> str:
    scope_id = index.canonical_scope_ids[scope.path_id]
    return f"fact:{scope_id}:{fact.kind}_{fact.unit_id.rsplit(':', 1)[-1][:12]}"


def _combined_fact_handle(
    index: ProblemDomainIndex,
    scope: ProblemScope,
    first: ProblemFact,
    second: ProblemFact,
) -> str:
    scope_id = index.canonical_scope_ids[scope.path_id]
    digest = stable_hash(sorted((first.unit_id, second.unit_id)))[:12]
    return f"fact:{scope_id}:right_angle_equal_length_{digest}"


def _handle_tail(entity: ProblemEntity) -> str:
    label = re.sub(r"\s+", "", entity.label)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", label):
        return label
    if entity.kind == "quadratic_function":
        return "parabola"
    if entity.kind in {"point", "named_line", "named_ray", "polygon"}:
        source_names = re.findall(r"[A-Za-z]+(?:_[A-Za-z0-9]+)?", label)
        if len(source_names) == 1:
            return source_names[0]
    return entity.local_id


def _is_one(value: str) -> bool:
    return re.sub(r"\s+", "", value) in {"1", "1.0", "(1)"}


def _runtime_orientation(value: Mapping[str, Any]) -> str:
    relation = str(value.get("relation", ""))
    if relation not in {
        "above_x_axis",
        "below_x_axis",
        "left_of_y_axis",
        "right_of_y_axis",
    }:
        raise ProblemDomainError(
            "extraction.problem_projection_failed",
            "$.facts.square.orientation",
            f"unsupported square axis placement {relation!r}",
        )
    return relation


def _source_goal_value_type(
    *,
    family_id: str,
    scope_path: str,
    target_handle: str,
    facts: Sequence[Mapping[str, Any]],
    index: ProblemDomainIndex,
    default: str,
) -> str:
    family = next(
        (
            item
            for item in DEFAULT_FAMILY_REGISTRY.families
            if item.family_id == family_id
        ),
        None,
    )
    if family is None:
        return default
    for contract in family.source_goal_contracts:
        if _source_goal_selector_matches(
            contract.selector_id,
            scope_path=scope_path,
            target_handle=target_handle,
            facts=facts,
            index=index,
        ):
            return contract.expected_value_type
    return default


def _source_goal_selector_matches(
    selector_id: str,
    *,
    scope_path: str,
    target_handle: str,
    facts: Sequence[Mapping[str, Any]],
    index: ProblemDomainIndex,
) -> bool:
    if selector_id != "square_curve_point_candidates":
        raise ProblemDomainError(
            "extraction.problem_projection_failed",
            "$.family.source_goal_contracts",
            f"unknown source goal selector {selector_id!r}",
        )
    visible_scope_ids = {
        index.canonical_scope_ids[path] for path in index.ancestor_paths(scope_path)
    }
    squares = [item for item in facts if item.get("type") == "square"]
    visible_curve_points = {
        str(item.get("point", ""))
        for item in facts
        if item.get("type") == "point_on_curve"
        and item.get("scope_id") in visible_scope_ids
        and item.get("point") != target_handle
    }
    return any(
        target_handle in set(square.get("vertices", ()))
        and bool(set(square.get("vertices", ())).intersection(visible_curve_points))
        for square in squares
        if square.get("scope_id") in visible_scope_ids
    )


__all__ = [
    "ProblemDomainIndex",
    "ProblemDomainProjector",
    "ResolvedDomainEntity",
    "RuntimeProjectionManifest",
    "SolverProblemProjection",
]
