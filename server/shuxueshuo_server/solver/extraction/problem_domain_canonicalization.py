"""Deterministic identity canonicalization for extracted ProblemDraft graphs.

The model remains responsible for source mathematics.  This module only
normalizes identities that are already provably the same in the lexical graph:

* the coordinate origin ``O`` in a quadratic coordinate problem; and
* an entity redeclared with the same kind and source label below an ancestor;
* explicit compound facts whose Solver projection requires their primitive
  equivalents (an ``x_range`` and a given minimum target).

Sibling scopes are intentionally isolated.  Scope-local value facts remain in
their authored scopes, so one canonical Symbol may still acquire different
runtime StateVersions in different subproblems.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import json
import re
from typing import Any, Mapping, MutableMapping, Sequence
import unicodedata

from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemVerificationStamp,
)


_REFERENCE_FIELDS = {
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
_REFERENCE_ARRAY_FIELDS = {"symbols", "vertices", "points"}
_EXPRESSION_FIELDS = {
    "expression",
    "value",
    "scale",
    "x_expression",
    "vector",
    "x_range",
}
_POSITIVE_INFINITY_TOKENS = frozenset(
    {"inf", "+inf", "infinity", "+infinity", "oo", "+oo", "∞", "+∞"}
)
_NEGATIVE_INFINITY_TOKENS = frozenset(
    {"-inf", "-infinity", "-oo", "-∞"}
)


@dataclass(frozen=True)
class ProblemDomainCanonicalizationAction:
    code: str
    source_scope_path: str
    source_local_id: str
    target_scope_path: str
    target_local_id: str

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "source_scope_path": self.source_scope_path,
            "source_local_id": self.source_local_id,
            "target_scope_path": self.target_scope_path,
            "target_local_id": self.target_local_id,
        }


@dataclass(frozen=True)
class ProblemDomainCanonicalizationResult:
    draft: ProblemDraft
    actions: tuple[ProblemDomainCanonicalizationAction, ...] = ()


@dataclass(frozen=True)
class _VisibleEntity:
    scope_path: str
    payload: Mapping[str, Any]

    @property
    def local_id(self) -> str:
        return str(self.payload["id"])


class ProblemDomainCanonicalizer:
    """Canonicalize source identities without solving or inventing relations."""

    def canonicalize(self, draft: ProblemDraft) -> ProblemDomainCanonicalizationResult:
        original = draft.graph.wire_payload()
        payload = deepcopy(original)
        actions: list[ProblemDomainCanonicalizationAction] = []

        root = payload["root"]
        _promote_quadratic_coordinate_origin(root, actions)
        _merge_lexical_entity_redeclarations(
            root,
            path=(),
            inherited_by_identity={},
            inherited_aliases={},
            actions=actions,
        )
        _materialize_equivalent_primitive_facts(
            root,
            path=(),
            visible_minimum_targets=frozenset(),
            represented_minimum_targets=_represented_minimum_targets(root),
            visible_polygons={},
            visible_squares=frozenset(),
            actions=actions,
        )

        if payload == original:
            return ProblemDomainCanonicalizationResult(draft=draft)

        canonical = ProblemDraft.create(
            payload,
            parent_revision_id=draft.parent_revision_id,
        )
        reusable_stamps: dict[str, ProblemVerificationStamp] = {
            unit_id: stamp
            for unit_id, stamp in draft.verification_stamps.items()
            if unit_id in canonical.unit_registry
            and unit_id in draft.unit_registry
            and canonical.unit_registry[unit_id].semantic_signature
            == draft.unit_registry[unit_id].semantic_signature
        }
        canonical = replace(canonical, verification_stamps=reusable_stamps)
        return ProblemDomainCanonicalizationResult(
            draft=canonical,
            actions=tuple(actions),
        )


def _promote_quadratic_coordinate_origin(
    root: MutableMapping[str, Any],
    actions: list[ProblemDomainCanonicalizationAction],
) -> None:
    scopes = tuple(_iter_scope_payloads(root))
    if not _is_quadratic_coordinate_graph(scopes):
        return

    root_path = str(root["id"])
    point_candidates: list[tuple[str, MutableMapping[str, Any]]] = []
    origin_fact_refs: list[str] = []
    reference_aliases: list[str] = []
    for path, scope in scopes:
        for entity in scope.get("entities", ()):
            if (
                isinstance(entity, MutableMapping)
                and entity.get("kind") == "point"
                and (
                    _is_origin_o_name(str(entity.get("id", "")))
                    or _is_origin_o_name(str(entity.get("label", "")))
                )
            ):
                point_candidates.append((path, entity))
        for fact in scope.get("facts", ()):
            if (
                isinstance(fact, Mapping)
                and fact.get("kind") == "point_construction"
                and fact.get("construction") == "origin"
                and isinstance(fact.get("point"), str)
                and _is_origin_o_name(str(fact["point"]))
            ):
                origin_fact_refs.append(str(fact["point"]))
        reference_aliases.extend(_origin_reference_aliases(scope))

    source_mentions_origin = _source_mentions_coordinate_origin(scopes)
    if not source_mentions_origin and not reference_aliases:
        _drop_unreferenced_coordinate_origin(scopes, actions)
        return

    aliases = tuple(
        dict.fromkeys(
            (
                *(str(entity["id"]) for _, entity in point_candidates),
                *origin_fact_refs,
                *reference_aliases,
                *(("O",) if source_mentions_origin else ()),
            )
        )
    )
    if not aliases:
        return

    root_candidates = [
        entity for path, entity in point_candidates if path == root_path
    ]
    if len(root_candidates) > 1 and not all(
        _entities_compatible(root_candidates[0], entity)
        for entity in root_candidates[1:]
    ):
        # Leave genuine ambiguity for the validator instead of guessing.
        return

    source_path = root_path
    if root_candidates:
        canonical_entity = root_candidates[0]
    elif point_candidates:
        source_path, source_entity = point_candidates[0]
        canonical_entity = deepcopy(source_entity)
        root.setdefault("entities", []).append(canonical_entity)
    else:
        preferred = next(
            (item for item in aliases if item == "O"),
            aliases[0],
        )
        canonical_entity = {"id": preferred, "kind": "point", "label": "O"}
        root.setdefault("entities", []).append(canonical_entity)

    canonical_id = str(canonical_entity["id"])
    alias_map = {alias: canonical_id for alias in aliases if alias != canonical_id}
    _rewrite_scope_tree(root, alias_map)

    kept_root_entities: list[Mapping[str, Any]] = []
    seen_canonical = False
    for entity in root.get("entities", ()):
        is_origin_point = (
            isinstance(entity, Mapping)
            and entity.get("kind") == "point"
            and (
                str(entity.get("id", "")) == canonical_id
                or _is_origin_o_name(str(entity.get("label", "")))
            )
        )
        if is_origin_point:
            if seen_canonical:
                actions.append(
                    ProblemDomainCanonicalizationAction(
                        code="merge_coordinate_origin",
                        source_scope_path=root_path,
                        source_local_id=str(entity.get("id", "")),
                        target_scope_path=root_path,
                        target_local_id=canonical_id,
                    )
                )
                continue
            entity = canonical_entity
            seen_canonical = True
        kept_root_entities.append(entity)
    root["entities"] = kept_root_entities

    for path, scope in scopes:
        if path != root_path:
            retained: list[Mapping[str, Any]] = []
            for entity in scope.get("entities", ()):
                if (
                    isinstance(entity, Mapping)
                    and entity.get("kind") == "point"
                    and (
                        str(entity.get("id", "")) in aliases
                        or _is_origin_o_name(str(entity.get("label", "")))
                    )
                ):
                    actions.append(
                        ProblemDomainCanonicalizationAction(
                            code="promote_coordinate_origin",
                            source_scope_path=path,
                            source_local_id=str(entity.get("id", "")),
                            target_scope_path=root_path,
                            target_local_id=canonical_id,
                        )
                    )
                    continue
                retained.append(entity)
            scope["entities"] = retained

    root_origin_fact: Mapping[str, Any] | None = None
    for path, scope in scopes:
        retained_facts: list[Mapping[str, Any]] = []
        for fact in scope.get("facts", ()):
            is_origin_fact = (
                isinstance(fact, Mapping)
                and fact.get("kind") == "point_construction"
                and fact.get("construction") == "origin"
                and str(fact.get("point", "")) == canonical_id
            )
            if is_origin_fact and path == root_path and root_origin_fact is None:
                root_origin_fact = fact
                retained_facts.append(fact)
            elif is_origin_fact:
                actions.append(
                    ProblemDomainCanonicalizationAction(
                        code="promote_coordinate_origin_fact",
                        source_scope_path=path,
                        source_local_id=canonical_id,
                        target_scope_path=root_path,
                        target_local_id=canonical_id,
                    )
                )
            else:
                retained_facts.append(fact)
        scope["facts"] = retained_facts
    if root_origin_fact is None:
        root.setdefault("facts", []).append(
            {
                "kind": "point_construction",
                "point": canonical_id,
                "construction": "origin",
            }
        )
        actions.append(
            ProblemDomainCanonicalizationAction(
                code="declare_coordinate_origin",
                source_scope_path=source_path,
                source_local_id=canonical_id,
                target_scope_path=root_path,
                target_local_id=canonical_id,
            )
        )


def _merge_lexical_entity_redeclarations(
    scope: MutableMapping[str, Any],
    *,
    path: tuple[str, ...],
    inherited_by_identity: Mapping[tuple[str, str], _VisibleEntity],
    inherited_aliases: Mapping[str, str],
    actions: list[ProblemDomainCanonicalizationAction],
) -> None:
    scope_path_tuple = (*path, str(scope["id"]))
    scope_path = "/".join(scope_path_tuple)
    visible = dict(inherited_by_identity)
    aliases = dict(inherited_aliases)
    kept_entities: list[MutableMapping[str, Any]] = []

    for raw_entity in scope.get("entities", ()):
        entity = _rewrite_mapping(raw_entity, aliases)
        key = (
            str(entity.get("kind", "")),
            _normalize_identity_label(str(entity.get("label", ""))),
        )
        existing = visible.get(key) if key[0] and key[1] else None
        if existing is not None and _entities_compatible(existing.payload, entity):
            source_id = str(entity["id"])
            target_id = existing.local_id
            if source_id != target_id:
                aliases[source_id] = target_id
            actions.append(
                ProblemDomainCanonicalizationAction(
                    code="merge_lexical_entity",
                    source_scope_path=scope_path,
                    source_local_id=source_id,
                    target_scope_path=existing.scope_path,
                    target_local_id=target_id,
                )
            )
            continue
        kept_entities.append(entity)
        if key[0] and key[1]:
            visible[key] = _VisibleEntity(scope_path=scope_path, payload=entity)

    aliases = _collapse_aliases(aliases)
    scope["entities"] = [
        _rewrite_mapping(entity, aliases) for entity in kept_entities
    ]
    scope["facts"] = [
        _rewrite_mapping(fact, aliases) for fact in scope.get("facts", ())
    ]
    scope["goals"] = [
        _rewrite_mapping(goal, aliases) for goal in scope.get("goals", ())
    ]
    for child in scope.get("children", ()):
        _merge_lexical_entity_redeclarations(
            child,
            path=scope_path_tuple,
            inherited_by_identity=visible,
            inherited_aliases=aliases,
            actions=actions,
        )


def _materialize_equivalent_primitive_facts(
    scope: MutableMapping[str, Any],
    *,
    path: tuple[str, ...],
    visible_minimum_targets: frozenset[str],
    represented_minimum_targets: frozenset[str],
    visible_polygons: Mapping[str, tuple[str, ...]],
    visible_squares: frozenset[str],
    actions: list[ProblemDomainCanonicalizationAction],
) -> None:
    """Expand source-equivalent compound facts without deriving new mathematics."""

    scope_path_tuple = (*path, str(scope["id"]))
    scope_path = "/".join(scope_path_tuple)
    facts: list[Mapping[str, Any]] = []
    for source_fact in scope.get("facts", ()):
        fact = deepcopy(source_fact)
        if _is_tautological_infinite_constraint(fact):
            symbol = str(fact.get("symbol", ""))
            operator = str(fact.get("operator", ""))
            actions.append(
                ProblemDomainCanonicalizationAction(
                    code="drop_unbounded_symbol_constraint",
                    source_scope_path=scope_path,
                    source_local_id=f"symbol_constraint:{symbol}:{operator}",
                    target_scope_path=scope_path,
                    target_local_id=f"x_range:{symbol}",
                )
            )
            continue
        facts.append(fact)
    facts = _canonicalize_axis_x_intersection_facts(
        facts,
        scope_path=scope_path,
        actions=actions,
    )
    known = {_stable_payload(item) for item in facts}
    polygons = dict(visible_polygons)
    polygons.update(
        {
            str(entity["id"]): tuple(str(item) for item in entity["vertices"])
            for entity in scope.get("entities", ())
            if isinstance(entity, Mapping)
            and entity.get("kind") == "polygon"
            and isinstance(entity.get("id"), str)
            and isinstance(entity.get("vertices"), Sequence)
            and not isinstance(entity.get("vertices"), (str, bytes))
        }
    )
    squares = set(visible_squares)
    squares.update(
        str(fact["polygon"])
        for fact in facts
        if fact.get("kind") == "square" and isinstance(fact.get("polygon"), str)
    )
    minimum_targets = set(visible_minimum_targets)
    minimum_targets.update(
        _stable_payload({"expression": fact["expression"]})
        for fact in facts
        if fact.get("kind") == "minimum_target"
        and isinstance(fact.get("expression"), Mapping)
    )
    additions: list[Mapping[str, Any]] = []
    solves_parameter = any(
        isinstance(goal, Mapping) and goal.get("kind") == "parameter_value"
        for goal in scope.get("goals", ())
    )
    minimum_value_goals = tuple(
        goal
        for goal in scope.get("goals", ())
        if isinstance(goal, Mapping)
        and goal.get("kind") == "minimum_value"
        and isinstance(goal.get("expression"), Mapping)
    )

    def append_if_missing(
        candidate: Mapping[str, Any],
        *,
        action_code: str,
        source_name: str,
        target_name: str,
    ) -> None:
        signature = _stable_payload(candidate)
        if signature in known:
            return
        known.add(signature)
        additions.append(deepcopy(candidate))
        actions.append(
            ProblemDomainCanonicalizationAction(
                code=action_code,
                source_scope_path=scope_path,
                source_local_id=source_name,
                target_scope_path=scope_path,
                target_local_id=target_name,
            )
        )

    for expression in _shared_child_minimum_target_expressions(scope):
        append_if_missing(
            {
                "kind": "minimum_target",
                "expression": deepcopy(expression),
            },
            action_code="materialize_shared_minimum_target",
            source_name="descendant_minimum_requirements",
            target_name="minimum_target",
        )
        minimum_targets.add(_stable_payload({"expression": expression}))

    for fact in facts:
        kind = fact.get("kind")
        if kind == "point_on_curve_with_x":
            x_range = fact.get("x_range")
            symbol = fact.get("x_symbol")
            if (
                isinstance(x_range, Sequence)
                and not isinstance(x_range, (str, bytes))
                and len(x_range) == 2
                and isinstance(symbol, str)
            ):
                lower, upper = x_range
                for operator, value, is_lower in (
                    (">", lower, True),
                    ("<", upper, False),
                ):
                    if _is_unbounded_x_range_endpoint(value, is_lower=is_lower):
                        continue
                    append_if_missing(
                        {
                            "kind": "symbol_constraint",
                            "symbol": symbol,
                            "operator": operator,
                            "value": deepcopy(value),
                        },
                        action_code="materialize_x_range_constraint",
                        source_name=f"point_on_curve_with_x:{symbol}",
                        target_name=f"symbol_constraint:{symbol}:{operator}",
                    )
        elif (
            kind == "minimum_value_given"
            and isinstance(fact.get("expression"), Mapping)
            and (
                solves_parameter
                or _stable_payload({"expression": fact["expression"]})
                not in represented_minimum_targets
            )
            and _stable_payload({"expression": fact["expression"]})
            not in minimum_targets
        ):
            append_if_missing(
                {
                    "kind": "minimum_target",
                    "expression": deepcopy(fact["expression"]),
                },
                action_code="materialize_minimum_target",
                source_name="minimum_value_given",
                target_name="minimum_target",
            )
            minimum_targets.add(
                _stable_payload({"expression": fact["expression"]})
            )
        elif kind == "square_center":
            square = str(fact.get("square", ""))
            point = fact.get("point")
            vertices = polygons.get(square, ())
            if square in squares and isinstance(point, str) and len(vertices) == 4:
                for start, end in (
                    (vertices[0], vertices[2]),
                    (vertices[1], vertices[3]),
                ):
                    append_if_missing(
                        {
                            "kind": "point_on_segment",
                            "point": point,
                            "segment": {"start": start, "end": end},
                        },
                        action_code="materialize_square_center_membership",
                        source_name=f"square_center:{point}",
                        target_name=f"point_on_segment:{start}:{end}",
                    )

    for goal in minimum_value_goals:
        signature = _stable_payload({"expression": goal["expression"]})
        if signature not in minimum_targets:
            append_if_missing(
                {
                    "kind": "minimum_target",
                    "expression": deepcopy(goal["expression"]),
                },
                action_code="materialize_minimum_goal_target",
                source_name="goal:minimum_value",
                target_name="minimum_target",
            )
            minimum_targets.add(signature)

    scope["facts"] = [*facts, *additions]
    for child in scope.get("children", ()):
        _materialize_equivalent_primitive_facts(
            child,
            path=scope_path_tuple,
            visible_minimum_targets=frozenset(minimum_targets),
            represented_minimum_targets=represented_minimum_targets,
            visible_polygons=polygons,
            visible_squares=frozenset(squares),
            actions=actions,
        )


def _infinity_token(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"\s+", "", value).lower().replace("\\infty", "∞")


def _is_unbounded_x_range_endpoint(value: object, *, is_lower: bool) -> bool:
    token = _infinity_token(value)
    if is_lower:
        return token in _NEGATIVE_INFINITY_TOKENS
    return token in _POSITIVE_INFINITY_TOKENS


def _is_tautological_infinite_constraint(fact: Mapping[str, Any]) -> bool:
    if fact.get("kind") != "symbol_constraint":
        return False
    token = _infinity_token(fact.get("value"))
    operator = fact.get("operator")
    return bool(
        (operator in {"<", "<="} and token in _POSITIVE_INFINITY_TOKENS)
        or (operator in {">", ">="} and token in _NEGATIVE_INFINITY_TOKENS)
    )


def _canonicalize_axis_x_intersection_facts(
    facts: Sequence[Mapping[str, Any]],
    *,
    scope_path: str,
    actions: list[ProblemDomainCanonicalizationAction],
) -> list[Mapping[str, Any]]:
    by_point: dict[str, dict[str, list[tuple[int, Mapping[str, Any]]]]] = {}
    for index, fact in enumerate(facts):
        if fact.get("kind") != "point_on_axis":
            continue
        point = fact.get("point")
        axis = fact.get("axis")
        if not isinstance(point, str) or axis not in {"x", "symmetry"}:
            continue
        by_point.setdefault(point, {"x": [], "symmetry": []})[str(axis)].append(
            (index, fact)
        )

    removed_indexes: set[int] = set()
    additions: list[Mapping[str, Any]] = []
    for point, memberships in sorted(by_point.items()):
        x_axis = memberships["x"]
        symmetry = memberships["symmetry"]
        curves = {
            str(fact.get("curve"))
            for _, fact in symmetry
            if isinstance(fact.get("curve"), str)
        }
        if not x_axis or not symmetry or len(curves) != 1:
            continue
        curve = next(iter(curves))
        removed_indexes.update(index for index, _ in (*x_axis, *symmetry))
        candidate = {
            "kind": "point_construction",
            "point": point,
            "construction": "axis_x_intercept",
            "owner": curve,
        }
        if _stable_payload(candidate) not in {
            _stable_payload(fact) for fact in facts
        }:
            additions.append(candidate)
        actions.append(
            ProblemDomainCanonicalizationAction(
                code="canonicalize_axis_x_intersection",
                source_scope_path=scope_path,
                source_local_id=f"point_on_axes:{point}",
                target_scope_path=scope_path,
                target_local_id=f"axis_x_intercept:{point}",
            )
        )
    return [
        *(
            fact
            for index, fact in enumerate(facts)
            if index not in removed_indexes
        ),
        *additions,
    ]


def _represented_minimum_targets(root: Mapping[str, Any]) -> frozenset[str]:
    result: set[str] = set()
    for _, scope in _iter_scope_payloads(root):
        for fact in scope.get("facts", ()):
            if (
                isinstance(fact, Mapping)
                and fact.get("kind") == "minimum_target"
                and isinstance(fact.get("expression"), Mapping)
            ):
                result.add(_stable_payload({"expression": fact["expression"]}))
        for goal in scope.get("goals", ()):
            if (
                isinstance(goal, Mapping)
                and goal.get("kind") == "minimum_value"
                and isinstance(goal.get("expression"), Mapping)
            ):
                result.add(_stable_payload({"expression": goal["expression"]}))
    return frozenset(result)


def _shared_child_minimum_target_expressions(
    scope: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    """Return minimum expressions required by two immediate child branches."""

    by_signature: dict[str, tuple[Mapping[str, Any], set[str]]] = {}
    for child in scope.get("children", ()):
        if not isinstance(child, Mapping):
            continue
        branch_id = str(child.get("id", ""))
        for _, descendant in _iter_scope_payloads(child):
            values = (
                *(
                    fact.get("expression")
                    for fact in descendant.get("facts", ())
                    if isinstance(fact, Mapping)
                    and fact.get("kind")
                    in {"minimum_target", "minimum_value_given"}
                ),
                *(
                    goal.get("expression")
                    for goal in descendant.get("goals", ())
                    if isinstance(goal, Mapping)
                    and goal.get("kind") == "minimum_value"
                ),
            )
            for expression in values:
                if not isinstance(expression, Mapping):
                    continue
                signature = _stable_payload({"expression": expression})
                existing = by_signature.get(signature)
                branches = existing[1] if existing is not None else set()
                branches.add(branch_id)
                by_signature[signature] = (expression, branches)
    return tuple(
        expression
        for signature, (expression, branches) in sorted(by_signature.items())
        if len(branches) >= 2
    )


def _stable_payload(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _iter_scope_payloads(
    scope: MutableMapping[str, Any],
    path: tuple[str, ...] = (),
) -> Sequence[tuple[str, MutableMapping[str, Any]]]:
    current = (*path, str(scope["id"]))
    result: list[tuple[str, MutableMapping[str, Any]]] = [
        ("/".join(current), scope)
    ]
    for child in scope.get("children", ()):
        result.extend(_iter_scope_payloads(child, current))
    return tuple(result)


def _is_quadratic_coordinate_graph(
    scopes: Sequence[tuple[str, Mapping[str, Any]]],
) -> bool:
    has_function = any(
        entity.get("kind") == "quadratic_function"
        for _, scope in scopes
        for entity in scope.get("entities", ())
        if isinstance(entity, Mapping)
    )
    has_function_expression = any(
        fact.get("kind") == "function_expression"
        for _, scope in scopes
        for fact in scope.get("facts", ())
        if isinstance(fact, Mapping)
    )
    return has_function and has_function_expression


def _origin_reference_aliases(scope: Mapping[str, Any]) -> list[str]:
    result: list[str] = []

    def visit(value: Any, field_name: str = "") -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in {"source_text", "label"}:
                    continue
                visit(child, str(key))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for child in value:
                visit(child, field_name)
        elif (
            isinstance(value, str)
            and (field_name in _REFERENCE_FIELDS or field_name in _REFERENCE_ARRAY_FIELDS)
            and _is_origin_o_name(value)
        ):
            result.append(value)

    visit(scope.get("entities", ()))
    visit(
        tuple(
            fact
            for fact in scope.get("facts", ())
            if not (
                isinstance(fact, Mapping)
                and fact.get("kind") == "point_construction"
                and fact.get("construction") == "origin"
            )
        )
    )
    visit(scope.get("goals", ()))
    return result


def _source_mentions_coordinate_origin(
    scopes: Sequence[tuple[str, Mapping[str, Any]]],
) -> bool:
    return any(
        "O" in unicodedata.normalize("NFKC", str(line))
        for _, scope in scopes
        for line in scope.get("source_text", ())
    )


def _drop_unreferenced_coordinate_origin(
    scopes: Sequence[tuple[str, MutableMapping[str, Any]]],
    actions: list[ProblemDomainCanonicalizationAction],
) -> None:
    for path, scope in scopes:
        retained_entities: list[Mapping[str, Any]] = []
        for entity in scope.get("entities", ()):
            if (
                isinstance(entity, Mapping)
                and entity.get("kind") == "point"
                and (
                    _is_origin_o_name(str(entity.get("id", "")))
                    or _is_origin_o_name(str(entity.get("label", "")))
                )
            ):
                actions.append(
                    ProblemDomainCanonicalizationAction(
                        code="drop_unreferenced_coordinate_origin",
                        source_scope_path=path,
                        source_local_id=str(entity.get("id", "")),
                        target_scope_path=path,
                        target_local_id="",
                    )
                )
                continue
            retained_entities.append(entity)
        scope["entities"] = retained_entities
        scope["facts"] = [
            fact
            for fact in scope.get("facts", ())
            if not (
                isinstance(fact, Mapping)
                and fact.get("kind") == "point_construction"
                and fact.get("construction") == "origin"
                and _is_origin_o_name(str(fact.get("point", "")))
            )
        ]


def _rewrite_scope_tree(scope: MutableMapping[str, Any], aliases: Mapping[str, str]) -> None:
    scope["entities"] = [
        _rewrite_mapping(entity, aliases) for entity in scope.get("entities", ())
    ]
    scope["facts"] = [
        _rewrite_mapping(fact, aliases) for fact in scope.get("facts", ())
    ]
    scope["goals"] = [
        _rewrite_mapping(goal, aliases) for goal in scope.get("goals", ())
    ]
    for child in scope.get("children", ()):
        _rewrite_scope_tree(child, aliases)


def _rewrite_mapping(value: Mapping[str, Any], aliases: Mapping[str, str]) -> dict[str, Any]:
    return {
        str(key): _rewrite_value(child, aliases, field_name=str(key))
        for key, child in value.items()
    }


def _rewrite_value(value: Any, aliases: Mapping[str, str], *, field_name: str) -> Any:
    if field_name in {"source_text", "label"}:
        return deepcopy(value)
    if isinstance(value, Mapping):
        return {
            str(key): _rewrite_value(child, aliases, field_name=str(key))
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [
            _rewrite_value(child, aliases, field_name=field_name)
            for child in value
        ]
    if not isinstance(value, str):
        return value
    if field_name in _REFERENCE_FIELDS or field_name in _REFERENCE_ARRAY_FIELDS:
        return aliases.get(value, value)
    if field_name in _EXPRESSION_FIELDS:
        result = value
        for source, target in sorted(
            aliases.items(), key=lambda pair: (-len(pair[0]), pair[0])
        ):
            result = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(source)}(?![A-Za-z0-9_])",
                target,
                result,
            )
        return result
    return value


def _entities_compatible(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("kind") != right.get("kind"):
        return False
    if _normalize_identity_label(str(left.get("label", ""))) != _normalize_identity_label(
        str(right.get("label", ""))
    ):
        return False
    ignored = {"id", "kind", "label"}
    if left.get("kind") in {"symbol", "point"}:
        ignored.add("role")
    left_attributes = {key: value for key, value in left.items() if key not in ignored}
    right_attributes = {key: value for key, value in right.items() if key not in ignored}
    return left_attributes == right_attributes


def _collapse_aliases(aliases: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in aliases:
        target = aliases[source]
        seen = {source}
        while target in aliases and target not in seen:
            seen.add(target)
            target = aliases[target]
        result[source] = target
    return result


def _normalize_identity_label(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).casefold()


def _is_origin_o_name(value: str) -> bool:
    normalized = _normalize_identity_label(value)
    reduced = normalized.replace("_", "")
    for prefix in (
        "coordinateorigin",
        "originpoint",
        "point",
        "坐标原点",
        "原点",
        "点",
    ):
        if reduced.startswith(prefix):
            reduced = reduced[len(prefix) :]
    return reduced == "o"
