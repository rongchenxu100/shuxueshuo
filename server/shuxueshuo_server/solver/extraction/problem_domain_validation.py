"""Domain validation, verification stamps, and repair-cone construction."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

import sympy as sp

from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDomainError,
    ProblemDraft,
    ProblemFact,
    ProblemGoal,
    ProblemScope,
    ProblemValidationIssue,
    ProblemValidationReport,
    ProblemVerificationStamp,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainIndex,
    ProblemDomainProjector,
    ResolvedDomainEntity,
    SolverProblemProjection,
)
from shuxueshuo_server.solver.extraction.problem_ir_runtime_preflight import (
    ProblemIRRuntimeReadinessValidator,
)
from shuxueshuo_server.solver.family import DEFAULT_FAMILY_REGISTRY
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.extraction.source_identity import stable_hash


_VALIDATOR_IDS = (
    "scope/v1",
    "lexical-reference/v1",
    "expression/v1",
    "entity-use/v1",
    "source-literal/v1",
    "source-kind/v1",
    "fact-redundancy/v1",
    "curve-ordinate/v1",
    "definition-conflict/v1",
    "goal/v1",
    "printed-source/v1",
    "family-contract/v1",
    "runtime-projection/v1",
    "method-readiness/v1",
    "context-build/v1",
)


_DOMAIN_ENTITY_RUNTIME_TYPES = {
    "symbol": "symbol",
    "point": "point",
    "quadratic_function": "function",
    "named_line": "line",
    "named_ray": "ray",
    "polygon": "polygon",
    "scalar_expression": "expression",
}

_DOMAIN_FACT_RUNTIME_TYPES = {
    "point_on_curve": "point_on_curve",
    "point_on_curve_with_x": "point_on_curve_with_x_coordinate",
    "point_on_segment": "point_on_segment",
    "point_on_ray": "point_on_ray",
    "quadrant_membership": "orientation_constraint",
    "midpoint": "midpoint_definition",
    "angle_sum": "angle_sum",
    "equal_length": "equal_length_condition",
    "square": "square",
    "square_center": "square_center",
    "minimum_target": "path_minimum_target",
    "minimum_value_given": "minimum_value",
}


@dataclass(frozen=True)
class ProblemDomainValidationResult:
    draft: ProblemDraft
    report: ProblemValidationReport
    projection: SolverProblemProjection | None

    @property
    def ok(self) -> bool:
        return self.report.ok and self.projection is not None


class ProblemDomainValidator:
    """Validate all independent boundaries and never invoke Planner/Solver."""

    def __init__(
        self,
        *,
        projector: ProblemDomainProjector | None = None,
        runtime_readiness: ProblemIRRuntimeReadinessValidator | None = None,
    ) -> None:
        self.projector = projector or ProblemDomainProjector()
        self.runtime_readiness = runtime_readiness or ProblemIRRuntimeReadinessValidator()

    def validate(
        self,
        draft: ProblemDraft,
        *,
        evidence_pack: MultimodalEvidencePack | None = None,
        expected_problem_id: str | None = None,
    ) -> ProblemDomainValidationResult:
        issues: list[ProblemValidationIssue] = []
        dependencies: dict[str, set[str]] = {
            unit_id: set() for unit_id in draft.unit_registry
        }
        if (
            expected_problem_id is not None
            and draft.graph.problem_id != expected_problem_id
        ):
            issues.append(
                _issue(
                    "extraction.problem_id_mismatch",
                    (draft.graph.root_scope.unit_id,),
                    f"problem_id must be {expected_problem_id!r}, got {draft.graph.problem_id!r}",
                    "copy the supplied problem_id exactly",
                )
            )
        projection: SolverProblemProjection | None = None
        index: ProblemDomainIndex | None = None

        try:
            index = ProblemDomainIndex(draft.graph)
        except ProblemDomainError as exc:
            issues.append(
                _issue(
                    "extraction.problem_scope_invalid",
                    (draft.graph.root_scope.unit_id,),
                    exc.message,
                    "rename the colliding scope or entity local id",
                )
            )

        if index is not None:
            issues.extend(_validate_scope_tree(draft, index, dependencies))
            issues.extend(_validate_references(draft, index, dependencies))
            issues.extend(_validate_expressions(draft, index, dependencies))
            issues.extend(_validate_entity_usage(draft, dependencies))
            issues.extend(
                _validate_source_literals(
                    draft,
                    index,
                    dependencies,
                    evidence_pack=evidence_pack,
                )
            )
            issues.extend(_validate_redundant_source_facts(draft, index, dependencies))
            issues.extend(
                _validate_redundant_curve_ordinate_placeholders(
                    draft,
                    index,
                    dependencies,
                )
            )
            issues.extend(
                _validate_redundant_curve_x_coordinates(
                    draft,
                    index,
                )
            )
            issues.extend(_validate_definition_conflicts(draft, index, dependencies))
            issues.extend(_validate_goals(draft, index, dependencies))

        if evidence_pack is not None:
            text_issue = _validate_printed_text_coverage(draft, evidence_pack)
            if text_issue is not None:
                issues.append(text_issue)

        family = next(
            (
                item
                for item in DEFAULT_FAMILY_REGISTRY.families
                if item.family_id == draft.graph.family_id
            ),
            None,
        )
        if family is None:
            issues.append(
                _issue(
                    "extraction.problem_family_unresolved",
                    ("family",),
                    f"unknown family {draft.graph.family_id!r}",
                    "choose one family_id from the supplied family catalog",
                )
            )

        # Projection is attempted even after semantic findings when references are
        # sufficiently complete. This surfaces family/runtime gaps in the same retry.
        if index is not None:
            try:
                projection = self.projector.project_graph(
                    draft.graph,
                    revision_id=draft.revision_id,
                    semantic_hash=draft.semantic_hash,
                )
            except ProblemDomainError as exc:
                issues.append(
                    _issue(
                        "extraction.problem_runtime_projection_failed",
                        (draft.graph.root_scope.unit_id,),
                        exc.message,
                        "repair the referenced domain units; code will not synthesize missing semantics",
                    )
                )

        if family is not None:
            dependencies["family"].update(
                unit_id
                for unit_id, record in draft.unit_registry.items()
                if record.unit_kind in {"entity", "fact", "goal"}
            )
            issues.extend(
                _validate_family_contract(
                    draft,
                    family=family,
                    evidence_pack=evidence_pack,
                )
            )

        runtime_context = None
        if projection is not None:
            try:
                runtime_context = ContextBuilder().build(projection.problem)
            except Exception as exc:
                issues.append(
                    _issue(
                        "extraction.problem_context_build_failed",
                        (draft.graph.root_scope.unit_id,),
                        f"ContextBuilder rejected the projected problem: {exc}",
                        "repair the source unit named by the projection error",
                    )
                )

        if projection is not None and family is not None and runtime_context is not None:
            try:
                readiness = self.runtime_readiness.validate(
                    projection.canonical_input,
                    problem=projection.problem,
                    family=family,
                    context=runtime_context,
                )
            except Exception as exc:
                readiness = ()
                issues.append(
                    _issue(
                        "extraction.problem_runtime_preflight_failed",
                        ("family",),
                        f"runtime preflight configuration failed: {exc}",
                        "fix the family preflight contract",
                        retryable=False,
                    )
                )
            for item in readiness:
                source_units = _runtime_issue_units(projection, item.path)
                issues.append(
                    _issue(
                        item.code.replace("problem_ir", "problem"),
                        source_units or ("family",),
                        item.message,
                        "supply the missing source-visible method inputs in the owning scope",
                        retryable=item.retryable,
                    )
                )

        report = ProblemValidationReport(
            issues=_dedupe_issues(issues),
            validator_ids=_VALIDATOR_IDS,
        )
        stamps, repairable = _verification_state(draft, report, dependencies)
        validated = draft.with_validation(report, stamps, repairable)
        return ProblemDomainValidationResult(validated, report, projection)


def _validate_scope_tree(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        parent_path = index.parent_path[scope.path_id]
        if parent_path is not None:
            dependencies[scope.unit_id].add(index.scope_by_path[parent_path].unit_id)
        child_ids = [item.local_id for item in scope.children]
        if len(child_ids) != len(set(child_ids)):
            issues.append(
                _issue(
                    "extraction.problem_scope_invalid",
                    (scope.unit_id,),
                    "sibling scope ids must be unique",
                    "rename the duplicate child scope id",
                )
            )
        local_ids = [item.local_id for item in scope.entities]
        if len(local_ids) != len(set(local_ids)):
            issues.append(
                _issue(
                    "extraction.problem_entity_duplicate",
                    (scope.unit_id,),
                    "entity local ids must be unique within a scope",
                    "rename or merge the duplicate entity",
                )
            )
        ancestor_ids = {
            entity.local_id
            for path in index.ancestor_paths(scope.path_id)[1:]
            for entity in index.scope_by_path[path].entities
        }
        ancestor_labels = {
            _normalize_identity_label(entity.label): entity
            for path in index.ancestor_paths(scope.path_id)[1:]
            for entity in index.scope_by_path[path].entities
            if _normalize_identity_label(entity.label)
        }
        for entity in scope.entities:
            dependencies[entity.unit_id].add(scope.unit_id)
            if entity.local_id in ancestor_ids:
                issues.append(
                    _issue(
                        "extraction.problem_scope_shadow",
                        (entity.unit_id,),
                        f"entity id {entity.local_id!r} shadows an ancestor",
                        "reuse the visible ancestor entity, or use a genuinely different source identity",
                        dependency_unit_ids=(scope.unit_id,),
                    )
                )
            ancestor = ancestor_labels.get(_normalize_identity_label(entity.label))
            if ancestor is not None and ancestor.local_id != entity.local_id:
                issues.append(
                    _issue(
                        "extraction.problem_scope_shadow",
                        (entity.unit_id,),
                        f"entity label {entity.label!r} redeclares ancestor entity {ancestor.local_id!r}",
                        "remove the child declaration and point its facts/goals at the visible ancestor entity",
                        dependency_unit_ids=(ancestor.unit_id, scope.unit_id),
                    )
                )
        for fact in scope.facts:
            dependencies[fact.unit_id].add(scope.unit_id)
        for goal in scope.goals:
            dependencies[goal.unit_id].add(scope.unit_id)
    return tuple(issues)


def _validate_references(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        for entity in scope.entities:
            specs: list[tuple[str, Any, tuple[str, ...]]] = []
            attrs = entity.attributes
            if entity.kind == "named_line":
                specs.append(("points", attrs.get("points"), ("point",)))
            elif entity.kind == "named_ray":
                specs.extend(
                    (
                        ("origin", attrs.get("origin"), ("point",)),
                        ("through", attrs.get("through"), ("point",)),
                    )
                )
            elif entity.kind == "polygon":
                specs.append(("vertices", attrs.get("vertices"), ("point",)))
            issues.extend(
                _resolve_specs(
                    index,
                    scope,
                    entity.unit_id,
                    specs,
                    dependencies,
                )
            )
        for fact in scope.facts:
            issues.extend(
                _resolve_specs(
                    index,
                    scope,
                    fact.unit_id,
                    _fact_reference_specs(fact),
                    dependencies,
                )
            )
        for goal in scope.goals:
            expected = {
                "point_coordinate": ("point",),
                "quadratic_equation": ("quadratic_function",),
                "parameter_value": ("symbol",),
            }.get(goal.kind)
            specs = (
                [("target", goal.attributes.get("target"), expected)]
                if expected is not None
                else _length_sum_reference_specs(goal.attributes.get("expression"))
            )
            issues.extend(
                _resolve_specs(
                    index,
                    scope,
                    goal.unit_id,
                    specs,
                    dependencies,
                )
            )
    return tuple(issues)


def _resolve_specs(
    index: ProblemDomainIndex,
    scope: ProblemScope,
    owner_unit_id: str,
    specs: Sequence[tuple[str, Any, tuple[str, ...] | None]],
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    for field, value, expected in specs:
        if value is None:
            continue
        values = value if isinstance(value, (tuple, list)) else (value,)
        for raw in values:
            if not isinstance(raw, str):
                continue
            try:
                resolved = index.resolve(scope.path_id, raw)
            except ProblemDomainError:
                if tuple(expected or ()) == ("symbol",):
                    try:
                        resolved = index.resolve_symbol_name(scope.path_id, raw)
                    except ProblemDomainError:
                        resolved = None
                else:
                    resolved = None
            if resolved is None:
                misplaced = index.out_of_scope_matches(
                    scope.path_id,
                    raw,
                    expected,
                )
                misplaced_unit_ids = tuple(
                    item.entity.unit_id for item in misplaced
                )
                companion_unit_ids = _identity_definition_companion_unit_ids(
                    misplaced
                )
                dependency_unit_ids: tuple[str, ...] = ()
                placement_note = ""
                if misplaced:
                    common_path = index.lowest_common_ancestor_path(
                        scope.path_id,
                        *(item.scope.path_id for item in misplaced),
                    )
                    dependency_unit_ids = (
                        index.scope_by_path[common_path].unit_id,
                    )
                    locations = ", ".join(
                        sorted({item.scope.path_id for item in misplaced})
                    )
                    placement_note = (
                        f"; matching source identity exists outside lexical scope "
                        f"at {locations!r}"
                    )
                issues.append(
                    _issue(
                        "extraction.problem_reference_unresolved",
                        (
                            owner_unit_id,
                            *misplaced_unit_ids,
                            *companion_unit_ids,
                        ),
                        f"{field} references {raw!r}, which is not visible from {scope.path_id!r}; sibling access is forbidden{placement_note}",
                        (
                            "move the matching declaration to the nearest common ancestor, "
                            "declare the entity in a visible scope, or correct the local reference"
                        ),
                        dependency_unit_ids=dependency_unit_ids,
                    )
                )
                continue
            dependencies[owner_unit_id].add(resolved.entity.unit_id)
            if expected is not None and resolved.entity.kind not in expected:
                issues.append(
                    _issue(
                        "extraction.problem_reference_type_mismatch",
                        (owner_unit_id, resolved.entity.unit_id),
                        f"{field} requires {list(expected)!r}, but {raw!r} is {resolved.entity.kind!r}",
                        "replace the reference with a visible entity of the required type",
                    )
                )
    return tuple(issues)


def _identity_definition_companion_unit_ids(
    misplaced: Sequence[ResolvedDomainEntity],
) -> tuple[str, ...]:
    """Return source-definition facts that must move with a misplaced identity."""

    result: list[str] = []
    for resolved in misplaced:
        entity = resolved.entity
        for fact in resolved.scope.facts:
            if fact.kind == "point_construction":
                reference = fact.attributes.get("point")
            elif fact.kind == "function_expression":
                reference = fact.attributes.get("function")
            else:
                continue
            if reference == entity.local_id:
                result.append(fact.unit_id)
    return tuple(sorted(set(result)))


def _fact_reference_specs(
    fact: ProblemFact,
) -> list[tuple[str, Any, tuple[str, ...] | None]]:
    a = fact.attributes
    direct: dict[str, dict[str, tuple[str, ...]]] = {
        "function_expression": {"function": ("quadratic_function",), "variable": ("symbol",)},
        "equation": {"symbols": ("symbol",)},
        "symbol_constraint": {"symbol": ("symbol",)},
        "symbol_value": {"symbol": ("symbol",)},
        "point_coordinate": {"point": ("point",)},
        "point_on_curve": {"point": ("point",), "curve": ("quadratic_function",)},
        "point_on_curve_with_x": {"point": ("point",), "curve": ("quadratic_function",), "x_symbol": ("symbol",)},
        "point_on_axis": {"point": ("point",), "curve": ("quadratic_function",)},
        "point_on_segment": {"point": ("point",)},
        "point_on_ray": {"point": ("point",)},
        "quadrant_membership": {"point": ("point",)},
        "midpoint": {"point": ("point",)},
        "square": {"polygon": ("polygon",)},
        "square_center": {"point": ("point",), "square": ("polygon",)},
    }
    specs: list[tuple[str, Any, tuple[str, ...] | None]] = [
        (field, a.get(field), expected)
        for field, expected in direct.get(fact.kind, {}).items()
        if a.get(field) is not None
    ]
    if fact.kind == "square":
        orientation = a.get("orientation")
        if isinstance(orientation, Mapping):
            specs.append(
                ("orientation.point", orientation.get("point"), ("point",))
            )
    if fact.kind == "point_construction":
        specs.append(("point", a.get("point"), ("point",)))
        construction = str(a.get("construction", ""))
        if a.get("owner") is not None:
            owner_type = (
                ("point",)
                if construction == "translated_point"
                else ("quadratic_function",)
            )
            specs.append(("owner", a.get("owner"), owner_type))
        if a.get("exclude_point") is not None:
            specs.append(("exclude_point", a.get("exclude_point"), ("point",)))
    for key in ("segment", "left", "right", "side"):
        value = a.get(key)
        if isinstance(value, Mapping) and "start" in value:
            specs.extend(_segment_reference_specs(value))
        elif isinstance(value, Mapping) and "segment" in value:
            specs.extend(_segment_reference_specs(value["segment"]))
    if fact.kind == "right_angle":
        specs.extend(_angle_reference_specs(a.get("angle")))
    if fact.kind == "angle_sum":
        for angle in a.get("angles", ()):
            specs.extend(_angle_reference_specs(angle))
    if fact.kind in {"minimum_target", "minimum_value_given"}:
        specs.extend(_length_sum_reference_specs(a.get("expression")))
    if fact.kind == "point_on_ray" and isinstance(a.get("ray"), str):
        specs.append(("ray", a.get("ray"), ("named_ray",)))
    elif fact.kind == "point_on_ray" and isinstance(a.get("ray"), Mapping):
        specs.extend(
            (
                ("ray.origin", a["ray"].get("origin"), ("point",)),
                ("ray.through", a["ray"].get("through"), ("point",)),
            )
        )
    return specs


def _segment_reference_specs(value: Any) -> list[tuple[str, Any, tuple[str, ...]]]:
    if not isinstance(value, Mapping):
        return []
    return [
        ("segment.start", value.get("start"), ("point",)),
        ("segment.end", value.get("end"), ("point",)),
    ]


def _angle_reference_specs(value: Any) -> list[tuple[str, Any, tuple[str, ...]]]:
    if not isinstance(value, Mapping):
        return []
    return [
        ("angle.start", value.get("start"), ("point",)),
        ("angle.vertex", value.get("vertex"), ("point",)),
        ("angle.end", value.get("end"), ("point",)),
    ]


def _length_sum_reference_specs(value: Any) -> list[tuple[str, Any, tuple[str, ...]]]:
    if not isinstance(value, Mapping):
        return []
    return [
        spec
        for term in value.get("terms", ())
        if isinstance(term, Mapping)
        for spec in _segment_reference_specs(term.get("segment"))
    ]


def _validate_expressions(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        units: Iterable[Any] = (*scope.entities, *scope.facts, *scope.goals)
        for unit in units:
            for field, expression in _expression_values(unit):
                try:
                    free_names = _free_symbol_names(expression)
                except Exception as exc:
                    issues.append(
                        _issue(
                            "extraction.problem_expression_invalid",
                            (unit.unit_id,),
                            f"{field} is not a supported algebra expression: {exc}",
                            "rewrite the expression using explicit * and ** syntax",
                        )
                    )
                    continue
                for name in free_names:
                    try:
                        resolved = index.resolve_kind(scope.path_id, name, ("symbol",))
                    except ProblemDomainError:
                        issues.append(
                            _issue(
                                "extraction.problem_expression_symbol_unresolved",
                                (unit.unit_id,),
                                f"{field} uses symbol {name!r}, which is not visible from {scope.path_id!r}",
                                "declare the symbol in this scope or an ancestor, or correct the expression",
                            )
                        )
                        continue
                    dependencies[unit.unit_id].add(resolved.entity.unit_id)
    return tuple(issues)


def _validate_entity_usage(
    draft: ProblemDraft,
    dependencies: Mapping[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    """Reject decorative entities that carry no mathematical relationship.

    Source-visible segments and angles are value objects. Declaring an unused
    ``named_line`` for every length term widens identity without adding source
    semantics, while an unused Symbol commonly represents the left-hand ``y``
    of an already-declared function expression. Every Entity therefore needs at
    least one typed consumer: another Entity, Fact, Goal, or expression.
    """

    referenced = {
        dependency_id
        for owner_id, dependency_ids in dependencies.items()
        if owner_id in draft.unit_registry
        for dependency_id in dependency_ids
        if dependency_id in draft.unit_registry
        and draft.unit_registry[owner_id].unit_kind in {"entity", "fact", "goal"}
    }
    return tuple(
        _issue(
            "extraction.problem_entity_unreferenced",
            (entity.unit_id,),
            f"entity {entity.local_id!r} is not used by any Entity, Fact, Goal, or expression",
            "remove the decorative entity, or reference it from the source-visible mathematical relation that gives it identity",
        )
        for scope in draft.graph.root_scope.iter_scopes()
        for entity in scope.entities
        if entity.unit_id not in referenced
    )


def _expression_values(unit: Any) -> Iterable[tuple[str, str]]:
    payload = unit.wire_payload()

    def visit(value: Any, path: str) -> Iterable[tuple[str, str]]:
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                if key in {
                    "expression",
                    "value",
                    "scale",
                    "x_expression",
                }:
                    if isinstance(child, str):
                        yield child_path, child
                    elif isinstance(child, Sequence) and not isinstance(child, (str, bytes)):
                        for index, item in enumerate(child):
                            if isinstance(item, str):
                                yield f"{child_path}[{index}]", item
                else:
                    yield from visit(child, child_path)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, child in enumerate(value):
                yield from visit(child, f"{path}[{index}]")

    yield from visit(payload, "$")


def _free_symbol_names(value: str) -> tuple[str, ...]:
    text = str(value).strip().replace("^", "**")
    parts = text.split("=", 1)
    expression = sp.sympify(parts[0], evaluate=False)
    if len(parts) == 2:
        expression = expression - sp.sympify(parts[1], evaluate=False)
    return tuple(sorted(str(item) for item in expression.free_symbols))


def _validate_source_literals(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: Mapping[str, set[str]],
    *,
    evidence_pack: MultimodalEvidencePack | None,
) -> tuple[ProblemValidationIssue, ...]:
    """Require model-created source identities to be visible in the question.

    Internal local ids are intentionally absent from this check. The source label
    is the model's claim that an object was named by the question; an expression
    such as ``b+2`` therefore cannot be smuggled in as a new atomic Symbol.
    """

    issues: list[ProblemValidationIssue] = []
    trusted_observation_text = _evidence_source_text(evidence_pack)
    for scope in draft.graph.root_scope.iter_scopes():
        source = _normalize_text(
            "".join(
                line
                for scope_path in reversed(index.ancestor_paths(scope.path_id))
                for line in index.scope_by_path[scope_path].source_text
            )
        )
        for entity in scope.entities:
            if entity.kind == "quadratic_function":
                continue
            if entity.kind == "point" and any(
                fact.kind == "point_construction"
                and fact.attributes.get("construction") == "origin"
                and str(fact.attributes.get("point", "")) == entity.local_id
                for fact in scope.facts
            ):
                # A coordinate-origin construction is itself the typed source
                # identity. The visual axes can establish O even when OCR omits
                # the isolated diagram label.
                continue
            label = str(entity.label).strip()
            normalized = _normalize_text(label)
            if entity.kind == "symbol":
                simple_symbol = re.fullmatch(r"[^\W\d_]", label) is not None
                trusted_composite_symbol = bool(
                    not simple_symbol
                    and trusted_observation_text
                    and normalized in trusted_observation_text
                )
                if not simple_symbol and not trusted_composite_symbol:
                    issues.append(
                        _issue(
                            "extraction.problem_source_literal_unresolved",
                            _entity_and_direct_consumers(entity.unit_id, dependencies),
                            f"symbol label {label!r} is not one source-grounded atomic symbol",
                            "remove solver-style ordinate placeholders and keep algebraic expressions inside point or fact values",
                        )
                    )
                    continue
            source_tokens = _source_identity_tokens(label)
            literal_grounded = bool(
                (normalized and normalized in source)
                or (source_tokens and any(token in source for token in source_tokens))
            )
            if literal_grounded:
                kind_markers = {
                    "named_line": ("直线", "line"),
                    "named_ray": ("射线", "ray"),
                }.get(entity.kind)
                if kind_markers and not any(
                    _normalize_text(marker) in source for marker in kind_markers
                ):
                    affected_units = _entity_and_direct_consumers(
                        entity.unit_id,
                        dependencies,
                    )
                    issues.append(
                        _issue(
                            "extraction.problem_source_kind_ungrounded",
                            affected_units,
                            f"{entity.kind} {label!r} has no matching source type marker {list(kind_markers)!r}",
                            "remove the invented named object and use SegmentTerm/RayTerm only when that source relation is actually printed",
                        )
                    )
                continue
            issues.append(
                _issue(
                    "extraction.problem_source_literal_unresolved",
                    _entity_and_direct_consumers(entity.unit_id, dependencies),
                    f"entity source label {label!r} is not visible in scope source text",
                    "replace the label with the printed source name or remove the invented entity",
                )
            )
    return tuple(issues)


def _entity_and_direct_consumers(
    entity_unit_id: str,
    dependencies: Mapping[str, set[str]],
) -> tuple[str, ...]:
    """Authorize one atomic repair for an invented identity and its relations."""

    return tuple(
        dict.fromkeys(
            (
                entity_unit_id,
                *sorted(
                    unit_id
                    for unit_id, source_ids in dependencies.items()
                    if entity_unit_id in source_ids
                    and unit_id.startswith(("fact:", "goal:"))
                ),
            )
        )
    )


def _validate_redundant_source_facts(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    """Reject a source relation repeated in two domain fact shapes.

    ``square.orientation`` is the runtime-facing form of a printed placement such
    as ``G在x轴下方``.  Repeating that same literal as ``quadrant_membership``
    creates two mutable authorities for one source statement.
    """

    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        visible_facts = tuple(
            fact
            for scope_path in index.ancestor_paths(scope.path_id)
            for fact in index.scope_by_path[scope_path].facts
        )
        square_orientations: list[tuple[ProblemFact, str, str]] = []
        for square in visible_facts:
            if square.kind != "square":
                continue
            orientation = square.attributes.get("orientation")
            if not isinstance(orientation, Mapping):
                continue
            point_ref = str(orientation.get("point", ""))
            try:
                oriented_point = index.resolve_kind(
                    scope.path_id, point_ref, ("point",)
                )
            except ProblemDomainError:
                continue
            square_orientations.append(
                (
                    square,
                    oriented_point.entity.unit_id,
                    _semantic_orientation(str(orientation.get("relation", ""))),
                )
            )
        for fact in scope.facts:
            if fact.kind != "quadrant_membership":
                continue
            point_ref = str(fact.attributes["point"])
            try:
                point = index.resolve_kind(scope.path_id, point_ref, ("point",))
            except ProblemDomainError:
                continue
            quadrant = _semantic_orientation(str(fact.attributes["quadrant"]))
            for square, point_unit_id, relation in square_orientations:
                if point.entity.unit_id == point_unit_id and quadrant == relation:
                    dependencies[fact.unit_id].add(square.unit_id)
                    issues.append(
                        _issue(
                            "extraction.problem_fact_redundant",
                            (fact.unit_id,),
                            "quadrant_membership repeats the placement already carried by square.orientation",
                            "remove the duplicate quadrant_membership and keep one source authority",
                            dependency_unit_ids=(square.unit_id,),
                        )
                    )
                    break
    return tuple(issues)


def _validate_redundant_curve_ordinate_placeholders(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: Mapping[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    """Reject a private y placeholder that adds no source-level relation."""

    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        constructions: dict[str, ProblemFact] = {}
        coordinates: dict[str, ProblemFact] = {}
        for fact in scope.facts:
            point = fact.attributes.get("point")
            if not isinstance(point, str):
                continue
            try:
                point_unit_id = index.resolve_kind(
                    scope.path_id,
                    point,
                    ("point",),
                ).entity.unit_id
            except ProblemDomainError:
                continue
            if (
                fact.kind == "point_construction"
                and fact.attributes.get("construction") == "curve_at_x"
            ):
                constructions[point_unit_id] = fact
            elif fact.kind == "point_coordinate":
                coordinates[point_unit_id] = fact

        for point_unit_id in sorted(set(constructions).intersection(coordinates)):
            coordinate = coordinates[point_unit_id]
            value = coordinate.attributes.get("value")
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                continue
            if len(value) != 2 or not isinstance(value[1], str):
                continue
            try:
                ordinate = index.resolve_symbol_name(scope.path_id, value[1])
            except ProblemDomainError:
                continue
            other_consumers = {
                unit_id
                for unit_id, source_ids in dependencies.items()
                if ordinate.entity.unit_id in source_ids
                and unit_id != coordinate.unit_id
            }
            if other_consumers:
                continue
            issues.append(
                _issue(
                    "extraction.problem_fact_redundant",
                    (coordinate.unit_id, ordinate.entity.unit_id),
                    "curve_at_x already carries the point abscissa; its private ordinate placeholder is unused",
                    "remove the redundant point_coordinate and private ordinate Symbol; retain curve_at_x as the source relation",
                    dependency_unit_ids=(constructions[point_unit_id].unit_id,),
                )
            )
    return tuple(issues)


def _validate_redundant_curve_x_coordinates(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
) -> tuple[ProblemValidationIssue, ...]:
    """Require one explicit source encoding for a point with a known coordinate."""

    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        memberships: dict[str, ProblemFact] = {}
        coordinates: dict[str, ProblemFact] = {}
        for fact in scope.facts:
            if fact.kind not in {"point_on_curve_with_x", "point_coordinate"}:
                continue
            point = fact.attributes.get("point")
            if not isinstance(point, str):
                continue
            try:
                point_unit_id = index.resolve_kind(
                    scope.path_id,
                    point,
                    ("point",),
                ).entity.unit_id
            except ProblemDomainError:
                continue
            if fact.kind == "point_on_curve_with_x":
                memberships[point_unit_id] = fact
            else:
                coordinates[point_unit_id] = fact

        for point_unit_id in sorted(set(memberships).intersection(coordinates)):
            membership = memberships[point_unit_id]
            coordinate = coordinates[point_unit_id]
            issues.append(
                _issue(
                    "extraction.problem_fact_redundant",
                    (membership.unit_id, coordinate.unit_id),
                    (
                        "point_on_curve_with_x and point_coordinate encode the same "
                        "point abscissa through competing source authorities"
                    ),
                    (
                        "retain point_coordinate; remove point_on_curve_with_x when "
                        "the source only places the point on an axis, or replace it "
                        "with point_on_curve when the source explicitly also says "
                        "the point lies on the curve"
                    ),
                    dependency_unit_ids=(point_unit_id,),
                )
            )
    return tuple(issues)


def _source_identity_tokens(label: str) -> tuple[str, ...]:
    """Extract literal Latin/math names from a descriptive entity label.

    Labels such as ``坐标原点O`` and ``顶点P`` are descriptive wrappers around
    source identities. Their letter token is sufficient grounding; this function
    never invents a missing object or infers a relationship.
    """

    normalized = unicodedata.normalize("NFKC", str(label))
    return tuple(
        dict.fromkeys(
            _normalize_text(item)
            for item in re.findall(r"[A-Za-z]+(?:_[A-Za-z0-9]+)?", normalized)
            if _normalize_text(item)
        )
    )


def _validate_definition_conflicts(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    for scope in draft.graph.root_scope.iter_scopes():
        by_point: dict[str, list[ProblemFact]] = {}
        by_symbol: dict[str, list[ProblemFact]] = {}
        for fact in scope.facts:
            point = fact.attributes.get("point")
            if isinstance(point, str) and fact.kind in {
                "point_construction",
                "point_coordinate",
            }:
                try:
                    key = index.resolve_kind(scope.path_id, point, ("point",)).entity.unit_id
                except ProblemDomainError:
                    continue
                by_point.setdefault(key, []).append(fact)
            symbol = fact.attributes.get("symbol")
            if isinstance(symbol, str) and fact.kind == "symbol_value":
                try:
                    key = index.resolve_kind(scope.path_id, symbol, ("symbol",)).entity.unit_id
                except ProblemDomainError:
                    continue
                by_symbol.setdefault(key, []).append(fact)

        for point_id, facts in by_point.items():
            constructions = [item for item in facts if item.kind == "point_construction"]
            coordinates = [item for item in facts if item.kind == "point_coordinate"]
            if len({item.semantic_signature for item in constructions}) > 1:
                issues.append(
                    _issue(
                        "extraction.problem_definition_conflict",
                        tuple(item.unit_id for item in constructions),
                        "one point has multiple incompatible constructions in the same scope",
                        "keep one source-visible construction and remove the conflicting fact",
                    )
                )
            coordinate_values = {
                tuple(str(value) for value in item.attributes["value"])
                for item in coordinates
            }
            if len(coordinate_values) > 1:
                issues.append(
                    _issue(
                        "extraction.problem_definition_conflict",
                        tuple(item.unit_id for item in coordinates),
                        "one point has conflicting coordinates in the same scope",
                        "replace the incorrect coordinate fact",
                    )
                )
            for construction in constructions:
                for coordinate in coordinates:
                    conflict = _construction_coordinate_conflict(
                        construction,
                        coordinate,
                    )
                    if conflict:
                        issues.append(
                            _issue(
                                "extraction.problem_definition_conflict",
                                (construction.unit_id, coordinate.unit_id, point_id),
                                conflict,
                                "make the point construction and coordinate describe the same source object",
                            )
                        )
        for symbol_id, facts in by_symbol.items():
            values = {str(item.attributes["value"]) for item in facts}
            if len(values) > 1:
                issues.append(
                    _issue(
                        "extraction.problem_definition_conflict",
                        (*tuple(item.unit_id for item in facts), symbol_id),
                        "one symbol has conflicting values in the same scope",
                        "keep the value stated for this subquestion only",
                    )
                )
    return tuple(issues)


def _construction_coordinate_conflict(
    construction: ProblemFact,
    coordinate: ProblemFact,
) -> str | None:
    kind = str(construction.attributes["construction"])
    values = tuple(str(item).replace(" ", "") for item in coordinate.attributes["value"])
    if kind == "origin" and values != ("0", "0"):
        return "origin must have coordinate (0,0)"
    if kind in {"x_axis_intercept", "axis_x_intercept"} and values[1] != "0":
        return "x-axis point must have y-coordinate 0"
    if kind == "y_axis_intercept" and values[0] != "0":
        return "y-axis point must have x-coordinate 0"
    return None


def _validate_goals(
    draft: ProblemDraft,
    index: ProblemDomainIndex,
    dependencies: dict[str, set[str]],
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    answer_keys: set[tuple[str, str]] = set()
    for scope in draft.graph.root_scope.iter_scopes():
        for goal in scope.goals:
            key = (scope.path_id, goal.answer_key)
            if key in answer_keys:
                issues.append(
                    _issue(
                        "extraction.problem_goal_invalid",
                        (goal.unit_id,),
                        f"answer_key {goal.answer_key!r} is duplicated in {scope.path_id!r}",
                        "use one atomic goal per answer value",
                    )
                )
            answer_keys.add(key)
            if goal.kind == "minimum_value":
                dependencies[goal.unit_id].update(
                    item.unit_id
                    for candidate_path in index.ancestor_paths(scope.path_id)
                    for item in index.scope_by_path[candidate_path].facts
                    if item.kind == "minimum_target"
                )
    return tuple(issues)


def _validate_family_contract(
    draft: ProblemDraft,
    *,
    family: Any,
    evidence_pack: MultimodalEvidencePack | None,
) -> tuple[ProblemValidationIssue, ...]:
    issues: list[ProblemValidationIssue] = []
    entity_counts, fact_counts = _family_source_primitive_counts(draft)
    missing: list[str] = []
    source_text = _family_source_text(draft, evidence_pack)
    for requirement in family.required_source_requirements:
        counts = entity_counts if requirement.primitive_kind == "entity_type" else fact_counts
        observed = sum(counts.get(item, 0) for item in requirement.primitive_types)
        if observed < requirement.min_count:
            missing.append(
                f"{requirement.primitive_kind} {list(requirement.primitive_types)}: {requirement.description}"
            )
            continue
        if requirement.source_authority == "printed_source":
            markers = tuple(_normalize_text(item) for item in requirement.printed_source_markers)
            if not any(marker and marker in source_text for marker in markers):
                issues.append(
                    _issue(
                        "extraction.problem_family_source_ungrounded",
                        ("family",),
                        f"{family.family_id} requires a printed source marker from {list(requirement.printed_source_markers)!r}",
                        "select a family whose use_when is explicitly visible in the question",
                    )
                )
    if missing:
        addition_scopes = tuple(
            scope.unit_id for scope in draft.graph.root_scope.iter_scopes()
        )
        issues.append(
            _issue(
                "extraction.problem_family_contract_mismatch",
                ("family",),
                f"selected family {family.family_id} is missing required source primitives: {missing}",
                "repair the missing source fact/entity or select the family actually described by the image",
                dependency_unit_ids=addition_scopes,
            )
        )

    domain_facts = [
        fact
        for scope in draft.graph.root_scope.iter_scopes()
        for fact in scope.facts
    ]
    weighted_facts = tuple(
        fact
        for fact in domain_facts
        if fact.kind == "minimum_target"
        and any(
            str(term["scale"]).replace(" ", "") not in {"1", "1.0", "(1)"}
            for term in fact.attributes["expression"]["terms"]
        )
    )
    has_weight = bool(weighted_facts)
    square_facts = tuple(fact for fact in domain_facts if fact.kind == "square")
    has_square = bool(square_facts)
    ray_entities = tuple(
        entity
        for scope in draft.graph.root_scope.iter_scopes()
        for entity in scope.entities
        if entity.kind == "named_ray"
    )
    ray_memberships = tuple(
        fact for fact in domain_facts if fact.kind == "point_on_ray"
    )
    equal_lengths = tuple(
        fact for fact in domain_facts if fact.kind == "equal_length"
    )
    has_ray_mechanism = bool(ray_entities and ray_memberships and equal_lengths)
    ray_mechanism_units = tuple(
        item.unit_id for item in (*ray_entities, *ray_memberships)
    )
    mismatch = None
    mismatch_dependencies: tuple[str, ...] = ()
    if family.family_id == "QuadraticWeightedPathMinimumSolver" and not has_weight:
        mismatch = "weighted family requires a non-unit coefficient inside the minimum target"
    elif family.family_id == "QuadraticSquareReflectionPathMinimumSolver" and not has_square:
        mismatch = "square-reflection family requires an explicit square fact"
    elif family.family_id == "QuadraticEqualLengthRayPathMinimumSolver" and not has_ray_mechanism:
        mismatch = "equal-length-ray family requires a named ray, ray membership, and equal length"
    elif family.family_id == "QuadraticPathMinimumSolver" and (has_weight or has_square or has_ray_mechanism):
        mismatch = "ordinary path family cannot absorb weighted, square, or equal-length-ray mechanisms"
        mismatch_dependencies = tuple(
            dict.fromkeys(
                (
                    *(fact.unit_id for fact in weighted_facts),
                    *(fact.unit_id for fact in square_facts),
                    *ray_mechanism_units,
                )
            )
        )
    if mismatch:
        issues.append(
            _issue(
                "extraction.problem_family_contract_mismatch",
                ("family",),
                mismatch,
                "remove source-ungrounded mechanism units, or replace only family_id when every retained mechanism is explicitly printed",
                dependency_unit_ids=mismatch_dependencies,
            )
        )
    return tuple(issues)


def _family_source_primitive_counts(
    draft: ProblemDraft,
) -> tuple[dict[str, int], dict[str, int]]:
    """Count source primitives without depending on a successful runtime projection."""

    entity_counts: dict[str, int] = {}
    fact_counts: dict[str, int] = {}
    for scope in draft.graph.root_scope.iter_scopes():
        for entity in scope.entities:
            primitive_types = {
                entity.kind,
                _DOMAIN_ENTITY_RUNTIME_TYPES.get(entity.kind, entity.kind),
            }
            for primitive_type in primitive_types:
                entity_counts[primitive_type] = entity_counts.get(primitive_type, 0) + 1
        for fact in scope.facts:
            primitive_types = {
                fact.kind,
                _DOMAIN_FACT_RUNTIME_TYPES.get(fact.kind, fact.kind),
            }
            for primitive_type in primitive_types:
                fact_counts[primitive_type] = fact_counts.get(primitive_type, 0) + 1
    return entity_counts, fact_counts


def _family_source_text(
    draft: ProblemDraft,
    evidence_pack: MultimodalEvidencePack | None,
) -> str:
    if evidence_pack is not None:
        return _normalize_text("".join(item.text for item in evidence_pack.printed_text))
    return _normalize_text("".join(draft.graph.original_text_lines))


def _evidence_source_text(
    evidence_pack: MultimodalEvidencePack | None,
) -> str:
    if evidence_pack is None:
        return ""
    return _normalize_text(
        "".join(
            (
                *(item.text for item in evidence_pack.printed_text),
                *(item.latex for item in evidence_pack.recognized_formulas),
            )
        )
    )


def _validate_printed_text_coverage(
    draft: ProblemDraft,
    evidence_pack: MultimodalEvidencePack,
) -> ProblemValidationIssue | None:
    candidate = _normalize_text(
        "".join(
            (
                draft.graph.source.question_number,
                draft.graph.source.score or "",
                *draft.graph.original_text_lines,
            )
        )
    )
    for item in evidence_pack.printed_text:
        source = _normalize_text(item.text)
        if len(source) < 4:
            continue
        if _question_header_is_covered(item.text, draft):
            continue
        if _text_is_covered(source, candidate):
            continue
        region = next(
            (
                record.region_id
                for record in evidence_pack.region_index
                if record.evidence_id == item.observation_id
            ),
            None,
        )
        return _issue(
            "extraction.problem_text_incomplete",
            (draft.graph.root_scope.unit_id,),
            f"high-confidence printed OCR is not covered: {item.text!r}",
            "restore the missing source text from the full image",
            region_refs=((region,) if region is not None else ()),
        )
    return None


def _question_header_is_covered(text: str, draft: ProblemDraft) -> bool:
    normalized = _normalize_text(text)
    if len(normalized) > 16 or "题" not in normalized:
        return False
    number = _normalize_text(draft.graph.source.question_number)
    score = _normalize_text(draft.graph.source.score or "")
    if not number or number not in normalized:
        return False
    return "分" not in normalized or bool(score and score in normalized)


def _text_is_covered(source: str, candidate: str) -> bool:
    if source in candidate:
        return True
    if not candidate:
        return False
    if len(candidate) <= len(source):
        return SequenceMatcher(None, source, candidate, autojunk=False).ratio() >= 0.82
    width = len(source)
    return any(
        SequenceMatcher(
            None,
            source,
            candidate[start : start + width],
            autojunk=False,
        ).ratio()
        >= 0.82
        for start in range(0, len(candidate) - width + 1)
    )


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\\(?:left|right|angle|circ|sqrt|dfrac|frac)\b", "", normalized)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", normalized).lower()


def _semantic_orientation(value: str) -> str:
    normalized = _normalize_text(value)
    if "x轴下方" in normalized or "belowxaxis" in normalized:
        return "below_x_axis"
    if "x轴上方" in normalized or "abovexaxis" in normalized:
        return "above_x_axis"
    if "y轴左侧" in normalized or "leftofyaxis" in normalized:
        return "left_of_y_axis"
    if "y轴右侧" in normalized or "rightofyaxis" in normalized:
        return "right_of_y_axis"
    return normalized


def _normalize_identity_label(value: str) -> str:
    """Normalize source identity wrappers while preserving mathematical case."""

    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", normalized)


def _runtime_issue_units(
    projection: SolverProblemProjection,
    path: str,
) -> tuple[str, ...]:
    match = re.match(r"^\$\.facts\[(\d+)\]", path)
    if match is None:
        return ()
    index = int(match.group(1))
    facts = projection.canonical_input.get("facts", ())
    if index >= len(facts):
        return ()
    handle = str(facts[index].get("handle", ""))
    return projection.manifest.runtime_node_sources.get(handle, ())


def _verification_state(
    draft: ProblemDraft,
    report: ProblemValidationReport,
    dependencies: Mapping[str, set[str]],
) -> tuple[dict[str, ProblemVerificationStamp], tuple[str, ...]]:
    invalid = {
        unit_id
        for issue in report.issues
        for unit_id in issue.unit_ids
        if unit_id in draft.unit_registry
    }
    dependent: set[str] = set()
    changed = True
    while changed:
        changed = False
        for unit_id, source_ids in dependencies.items():
            if unit_id in invalid or unit_id in dependent:
                continue
            if source_ids.intersection(invalid | dependent):
                dependent.add(unit_id)
                changed = True

    stamps: dict[str, ProblemVerificationStamp] = {}
    for unit_id, record in draft.unit_registry.items():
        dependency_signatures = tuple(
            sorted(
                draft.unit_registry[item].semantic_signature
                for item in dependencies.get(unit_id, set())
                if item in draft.unit_registry
            )
        )
        status = (
            "invalid"
            if unit_id in invalid
            else "dependent"
            if unit_id in dependent
            else "verified"
        )
        candidate = ProblemVerificationStamp(
            unit_id=unit_id,
            semantic_signature=record.semantic_signature,
            validator_ids=_VALIDATOR_IDS,
            dependency_signatures=dependency_signatures,
            status=status,
        )
        previous = draft.verification_stamps.get(unit_id)
        stamps[unit_id] = previous if previous == candidate else candidate

    repairable = set(invalid) | set(dependent)
    for issue in report.issues:
        repairable.update(
            item for item in issue.dependency_unit_ids if item in draft.unit_registry
        )
    repairable.update(
        f"scope:{record.scope_path}"
        for unit_id in tuple(repairable)
        if (record := draft.unit_registry.get(unit_id)) is not None
    )
    return stamps, tuple(sorted(repairable))


def _issue(
    code: str,
    unit_ids: Sequence[str],
    message: str,
    repair_action: str,
    *,
    dependency_unit_ids: Sequence[str] = (),
    region_refs: Sequence[str] = (),
    retryable: bool = True,
) -> ProblemValidationIssue:
    return ProblemValidationIssue(
        code=code,
        unit_ids=tuple(dict.fromkeys(unit_ids)),
        dependency_unit_ids=tuple(dict.fromkeys(dependency_unit_ids)),
        message=message,
        repair_action=repair_action,
        region_refs=tuple(dict.fromkeys(region_refs)),
        retryable=retryable,
    )


def _dedupe_issues(
    issues: Sequence[ProblemValidationIssue],
) -> tuple[ProblemValidationIssue, ...]:
    by_signature: dict[str, ProblemValidationIssue] = {}
    for issue in issues:
        signature = stable_hash(issue.to_payload())
        by_signature.setdefault(signature, issue)
    return tuple(
        sorted(
            by_signature.values(),
            key=lambda item: (item.code, item.unit_ids, item.message),
        )
    )


__all__ = [
    "ProblemDomainValidationResult",
    "ProblemDomainValidator",
]
