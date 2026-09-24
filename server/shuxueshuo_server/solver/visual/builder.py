"""VS1 forward builder from LessonIR to VisualStepIR."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from hashlib import sha256
from typing import Any, Callable, Mapping
import copy
import json
import math
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonIR,
    OwnedLessonStep as LessonStep,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    iter_teaching_scopes,
    iter_teaching_sources,
    teaching_source_owners,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.student_display import student_math_display

from .models import (
    JsonObject,
    VisualFrame,
    VisualObject,
    VisualStep,
    VisualStepIR,
)
from .math_state import FrameMathStateResolver, resolve_attainment_constraints
from .recursive_state import (
    BranchVisualState,
    RecursiveVisualStateResolver,
    VisualStepResolution,
    context_copy,
    geometry_refs_from_scene_item,
    visual_objects_from_scene_items,
)
from .animation import AnimationTimelineBuilder
from .lesson_shell import (
    generated_lesson_shell as _generated_lesson_shell,
    lesson_data_from_lesson_ir as _lesson_data_from_lesson_ir,
    _merge_condition_with_first_subquestion,
    parameter_name as _parameter_name,
    _problem_lines_with_answers,
)
from .palette import (
    COLOR_ACCENT,
    COLOR_CANDIDATE_REGION_FILL,
    COLOR_CANDIDATE_REGION_FILL_FAINT,
    COLOR_CANDIDATE_REGION_FILL_SUBTLE,
    COLOR_CANDIDATE_REGION_STROKE,
    COLOR_CANDIDATE_REGION_STROKE_FAINT,
    COLOR_CANDIDATE_REGION_STROKE_MUTED,
    COLOR_CANDIDATE_REGION_STROKE_SOFT,
    COLOR_CONSTRAINT,
    COLOR_CONSTRAINT_REGION_FILL,
    COLOR_CONSTRAINT_REGION_STROKE,
    COLOR_COORDINATE_TRIANGLE_FILL,
    COLOR_CURVE,
    COLOR_MUTED,
    COLOR_PATH_REGION_FILL,
    COLOR_PATH_REGION_STROKE,
    COLOR_PATH,
    COLOR_RESULT_REGION_FILL,
    COLOR_RESULT_REGION_STROKE,
    COLOR_RESULT_REGION_STROKE_FAINT,
    COLOR_RESULT,
    COLOR_TEXT,
)
from .parametric import CandidateHitResolver, ParametricExpressionResolver
from .parameter_identity import (
    parameterized_point_contexts_by_step,
    value_depends_on_symbol,
    verified_parameter_values_from_source,
)
from .viewport import SemanticViewportResolver
from .scene_items import (
    dedupe_scene_items as _dedupe_scene_items,
    focus_handles as _focus_handles,
)
from .geometry_naming import (
    GeometryPointScopeNamer,
    axis_parameter_candidate_point_id,
    axis_parameter_point_id,
    locus_line_endpoint_id,
    scope_root as _shared_scope_root,
    scope_lineage,
    scoped_point_id,
    square_projection_point_id,
)
from .role_binders import VisualGeometryIndex, VisualRoleBinderRegistry, VisualRoleBindings
from .role_binders import _public_point_semantic_ref
from .sympy_helpers import sympy_pair


@dataclass(frozen=True)
class GeneratedVisualBase:
    """Generated geometry/page shell for recursive VisualStepIR v2."""

    geometry_spec: JsonObject
    lesson_data: JsonObject
    default_t: float

    @classmethod
    def from_snapshot(cls, snapshot: ExplanationSnapshot, lesson: LessonIR) -> "GeneratedVisualBase":
        geometry_spec = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
        # The base shell must not sample an early diagram from a final answer.
        # Frame-local parameter contracts provide the actual display defaults.
        default_t = 0.75
        lesson_data = _generated_lesson_shell(snapshot=snapshot, lesson=lesson, default_t=default_t)
        return cls(
            geometry_spec=geometry_spec,
            lesson_data=lesson_data,
            default_t=default_t,
        )


@dataclass(frozen=True)
class _SceneBuildContext:
    lesson_step: LessonStep
    bindings: VisualRoleBindings
    coordinate_texts: dict[str, str] | None
    capabilities: frozenset[str]
    substeps: frozenset[str]
    template_items: tuple[JsonObject, ...] = ()

    @property
    def points(self) -> dict[str, str]:
        return self.bindings.point_handles


@dataclass(frozen=True)
class _VisualContextPolicy:
    """Internal context intent projected from selected VisualSpec templates."""

    roles: tuple[tuple[str, JsonObject], ...] = ()
    include_exact_dependencies: bool = True
    dependency_components: frozenset[str] | None = None
    suppress_point_definitions_when_exact: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _PointVisualStyle:
    color: str = COLOR_ACCENT
    dx: int = 14
    dy: int = -18


POINT_ACTIVE = _PointVisualStyle(color=COLOR_ACCENT)
POINT_RESULT = _PointVisualStyle(color=COLOR_RESULT)
POINT_AUXILIARY = _PointVisualStyle(color=COLOR_RESULT, dy=18)
POINT_MOVING = _PointVisualStyle(color=COLOR_ACCENT)
POINT_CONTEXT = _PointVisualStyle(color=COLOR_MUTED)


class GeometrySpecBuilder:
    """Generate a minimal renderable geometry-spec from successful runtime facts."""

    def build(self, *, snapshot: ExplanationSnapshot, lesson: LessonIR) -> JsonObject:
        parameter_name = _parameter_name(snapshot)
        default_t = 0.75
        fixed_points, moving_points, point_meta = _geometry_points_from_snapshot(snapshot, lesson, default_t)
        _add_anonymous_result_points(
            snapshot=snapshot, lesson=lesson, fixed=fixed_points, moving=moving_points,
            point_meta=point_meta, parameter_name=parameter_name,
        )
        curves = _curves_from_snapshot(snapshot)
        _add_curve_vertex_feature_points(
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            curves=curves,
            parameter_name=parameter_name,
        )
        _add_defined_points_from_curves(
            snapshot=snapshot,
            lesson=lesson,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            curves=curves,
            parameter_name=parameter_name,
        )
        _add_square_path_witness_points(
            snapshot=snapshot,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        _add_square_corner_points(
            snapshot=snapshot,
            lesson=lesson,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        _add_square_structural_points(
            snapshot=snapshot,
            lesson=lesson,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        _add_axis_parameter_candidate_points(
            snapshot=snapshot,
            lesson=lesson,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        _add_public_candidate_geometry(
            snapshot=snapshot,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        _add_public_construction_auxiliary_geometry(
            snapshot=snapshot,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        _add_endpoint_replacement_witness_geometry(
            snapshot=snapshot,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
        )
        # A point discovered first through its final evaluated output can later
        # acquire the earlier symbolic definition from a curve/relationship.
        # One semantic geometry id must have exactly one registry definition;
        # the symbolic definition plus the Frame-local parameter value covers
        # both the early and evaluated states.
        for geometry_id in moving_points:
            fixed_points.pop(geometry_id, None)
        domain = _domain_from_geometry_points(
            fixed_points,
            moving_points,
            curves,
            parameter_name,
            default_t,
        )
        fixed_points = dict(sorted(fixed_points.items()))
        moving_points = dict(sorted(moving_points.items()))
        point_meta = dict(sorted(point_meta.items()))
        expression_env = _expression_env_from_geometry(
            fixed_points=fixed_points,
            moving_points=moving_points,
            curves=curves,
            parameter_name=parameter_name,
        )
        return {
            "version": 1,
            "id": snapshot.problem_id,
            "domain": domain,
            "movingParam": parameter_name,
            "expressionEnv": expression_env,
            "fixedPoints": fixed_points,
            "movingPoints": moving_points,
            "pointMeta": point_meta,
            "curves": curves,
            "derivedIntersections": [],
        }


class VisualStepBuilder:
    """Build recursive, complete-frame VisualStepIR from verified artifacts."""

    def build(
        self,
        *,
        snapshot: ExplanationSnapshot,
        lesson: LessonIR,
        generated_base: GeneratedVisualBase | None = None,
        teaching_visual_specs=None,
    ) -> VisualStepIR:
        base = generated_base or GeneratedVisualBase.from_snapshot(snapshot, lesson)
        lesson_data = _lesson_data_from_lesson_ir(
            lesson,
            base.lesson_data,
            snapshot=snapshot,
        )
        binder = VisualRoleBinderRegistry.default(base.geometry_spec, snapshot.problem)
        state_result = RecursiveVisualStateResolver(snapshot).resolve(
            lesson,
            lambda lesson_step, state: _visual_step_resolution(
                lesson_step,
                state=state,
                snapshot=snapshot,
                geometry_spec=base.geometry_spec,
                bindings=binder.bind(lesson_step, snapshot),
            ),
        )
        visual_ir = VisualStepIR(
            problem_id=lesson.problem_id,
            source_snapshot_hash=lesson.source_snapshot_hash,
            source_lesson_hash=_stable_payload_hash(lesson.to_payload()),
            geometry_registry=copy.deepcopy(base.geometry_spec),
            root_scope=state_result.root_scope,
            compile_lesson_data=lesson_data,
            state_authority=state_result.authority,
            metadata={
                "source": "recursive_visual_step_builder",
                "base_source": "generated",
                "scene_model": "recursive_complete_frames",
            },
        )

        from .teaching_diagrams import bind_lesson_diagrams
        return bind_lesson_diagrams(
            visual_ir, lesson, snapshot, registry=teaching_visual_specs
        )


def _geometry_points_from_snapshot(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    default_t: float,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, JsonObject]]:
    parameter_name = _parameter_name(snapshot)
    parameter_scope = _parameter_scope_id(snapshot)
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    parameterized_point_contexts = parameterized_point_contexts_by_step(snapshot)
    fixed: dict[str, list[str]] = {}
    moving: dict[str, list[str]] = {}
    point_meta: dict[str, JsonObject] = {}

    def record_point_definition(geometry_id: str, pair: list[str]) -> None:
        """Keep one authoritative geometry definition per semantic point.

        A later evaluation step may materialize ``A(-5, 0)`` from the earlier
        public definition ``A(-c, 0)``.  The registry must retain the symbolic
        definition; the branch-local value ``c=5`` makes it exact at the later
        Frame.  Storing the same id in both fixedPoints and movingPoints makes
        debug/review consumers see whichever map they happen to inspect first.
        """

        if _pair_depends_on_parameter(pair, parameter_name):
            moving[geometry_id] = pair
            fixed.pop(geometry_id, None)
        elif geometry_id not in moving:
            fixed[geometry_id] = pair

    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        coordinate = entity.get("coordinate")
        definition = str(entity.get("definition") or "")
        if _is_point_value(coordinate):
            pair = _page_point_pair(coordinate)
            scope_id = (
                parameter_scope
                if parameter_scope and _pair_depends_on_parameter(pair, parameter_name)
                else str(entity.get("scope_id") or "problem")
            )
            geometry_id = (
                axis_parameter_point_id(label, scope_id)
                if entity.get("definition") == "axis_x_intercept"
                else namer.scope_namer.geometry_id(label, scope_id)
            )
            record_point_definition(geometry_id, pair)
            point_meta.setdefault(
                geometry_id,
                {
                    "label": label,
                    "scopeId": scope_id,
                    "scopeRoot": _scope_root(scope_id),
                    "definition": definition or "given_point",
                    "sourceRef": str(entity.get("handle") or ""),
                },
            )
        elif definition == "coordinate_origin":
            fixed.setdefault(label or "O", ["0", "0"])
            point_meta.setdefault(
                label or "O",
                {
                    "label": label or "O",
                    "scopeId": str(entity.get("scope_id") or "problem"),
                    "scopeRoot": "problem",
                    "definition": "coordinate_origin",
                    "sourceRef": str(entity.get("handle") or ""),
                },
            )

    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        value = item.get("value")
        if not _is_point_value(value):
            continue
        label = namer.point_id_for_fact(item)
        if not label:
            continue
        pair = _page_point_pair(value)
        scope_id = namer._visual_scope_for_fact(item)
        source_step_id = namer._source_step_id_for_fact(item)
        matching_parameter_contexts = {
            context
            for context in parameterized_point_contexts.get(source_step_id, frozenset())
            if context[0] == scope_id
            and value_depends_on_symbol(pair, context[1])
        }
        if len(matching_parameter_contexts) > 1:
            raise ValueError(
                "visual_parameterized_point_context_ambiguous: "
                f"step={source_step_id}, scope={scope_id}, "
                f"contexts={sorted(matching_parameter_contexts)}"
            )
        if matching_parameter_contexts:
            raw_label = namer._raw_label_for_fact(item)
            geometry_id = axis_parameter_point_id(raw_label or label, scope_id)
            parameter = next(iter(matching_parameter_contexts))[1]
            point_meta[geometry_id] = {
                **namer.scope_namer.point_meta(raw_label or label, scope_id),
                "definition": "parameterized_point",
                "parameterSymbol": parameter,
                "sourceStepIds": [source_step_id],
            }
            record_point_definition(geometry_id, pair)
            continue
        point_meta[label] = {
            **namer.point_meta_for_fact(item),
            "definition": "runtime_point_output",
            "sourceStepIds": [source_step_id] if source_step_id else [],
        }
        record_point_definition(label, pair)

    return dict(sorted(fixed.items())), dict(sorted(moving.items())), dict(sorted(point_meta.items()))


def _teaching_source_owner_rows(
    snapshot: ExplanationSnapshot,
) -> list[tuple[str, str | None, Any]]:
    rows: list[tuple[str, str | None, Any]] = []

    def visit(scope: Any) -> None:
        rows.extend((scope.scope_ref, None, source) for source in scope.steps)
        for goal in scope.goals:
            rows.extend((scope.scope_ref, goal.goal_ref, source) for source in goal.steps)
        for child in scope.children:
            visit(child)

    visit(snapshot.root_scope)
    return rows


def _add_defined_points_from_curves(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    curves: list[JsonObject],
    parameter_name: str,
) -> None:
    """Materialize drawable points whose definitions are now determined by a curve.

    Runtime only emits points that a Functional call explicitly asks for. The page,
    however, often needs sibling definition points for context, such as the
    other x-axis intercept of the same parabola.  This derives only from
    ProblemIR point definitions and already computed scoped curves.
    """
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    point_entities = [
        entity
        for entity in (snapshot.problem or {}).get("entities") or ()
        if isinstance(entity, dict)
        and entity.get("entity_type") == "point"
        and entity.get("definition") in {"x_axis_intercept", "axis_x_intercept"}
    ]
    if not point_entities:
        return
    for curve in curves:
        roots = _numeric_x_axis_roots_for_curve(curve)
        scope_id = str(curve.get("scopeId") or curve.get("scopeRoot") or "")
        for entity in point_entities:
            label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            if not label:
                continue
            pair = _defined_point_pair_for_curve_entity(entity, curve, roots)
            if pair is None:
                continue
            geometry_id = (
                axis_parameter_point_id(label, scope_id)
                if entity.get("definition") == "axis_x_intercept"
                else namer.scope_namer.geometry_id(label, scope_id)
            )
            if _pair_depends_on_parameter(pair, parameter_name):
                moving.setdefault(geometry_id, pair)
            else:
                fixed.setdefault(geometry_id, pair)
            point_meta.setdefault(
                geometry_id,
                {
                    **namer.scope_namer.point_meta(label, scope_id),
                    "definition": str(entity.get("definition") or ""),
                    "sourceCurveId": str(curve.get("id") or ""),
                    "sourceRef": str(entity.get("handle") or ""),
                },
            )


def _add_curve_vertex_feature_points(
    *,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    curves: list[JsonObject],
    parameter_name: str,
) -> None:
    """Register every quadratic vertex as a finite visual feature.

    Some problems ask for "the vertex" without assigning it a point letter.
    The runtime result is still verified, so the page needs a stable geometry
    reference that the vertex visual can reveal without inventing a label.
    """

    x = sp.Symbol("x")
    for curve in curves:
        curve_id = str(curve.get("id") or "")
        scope_id = str(curve.get("scopeId") or curve.get("scopeRoot") or "")
        if not curve_id:
            continue
        try:
            expression = (
                sp.sympify(str(curve.get("a") or "0")) * x**2
                + sp.sympify(str(curve.get("b") or "0")) * x
                + sp.sympify(str(curve.get("c") or "0"))
            )
            coefficient = sp.expand(expression).coeff(x, 2)
            if sp.simplify(coefficient) == 0:
                continue
            vertex_x = sp.simplify(
                -sp.expand(expression).coeff(x, 1) / (2 * coefficient)
            )
            vertex_y = sp.simplify(expression.subs(x, vertex_x))
        except Exception:
            continue
        point_id = f"{curve_id}_vertex"
        pair = [_page_expr(vertex_x), _page_expr(vertex_y)]
        if _pair_depends_on_parameter(pair, parameter_name):
            moving.setdefault(point_id, pair)
        else:
            fixed.setdefault(point_id, pair)
        point_meta.setdefault(
            point_id,
            {
                "label": "",
                "scopeId": scope_id,
                "scopeRoot": _scope_root(scope_id),
                "definition": "curve_vertex_feature",
                "sourceCurveId": curve_id,
                "display": f"({_point_value_text((vertex_x, vertex_y))})",
                "visualOnly": True,
            },
        )


def _add_square_corner_points(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    all_points = {**fixed, **moving}
    for fact in (snapshot.problem or {}).get("facts") or ():
        if not isinstance(fact, dict) or fact.get("type") != "square":
            continue
        vertices = [
            str(item)
            for item in fact.get("vertices") or ()
            if isinstance(item, str) and item
        ]
        if len(vertices) < 4:
            continue
        labels = [_label_from_square_vertex_handle(handle, snapshot) for handle in vertices[:4]]
        if any(not label for label in labels):
            continue
        # A problem-level square relation may be instantiated independently in
        # several question branches.  Build one drawable square per branch
        # that has actually produced at least one of its vertices; never let a
        # later branch's K/E/G definition become the earlier branch's object.
        scopes = _square_instance_scopes(labels, point_meta)
        for scope_id in scopes:
            axis_parameter_square = any(
                axis_parameter_point_id(label, scope_id) in all_points
                for label in labels
            )
            point_ids = [
                _square_geometry_point_id(
                    label,
                    scope_id,
                    all_points,
                    prefer_axis=axis_parameter_square and index == 2,
                )
                for index, label in enumerate(labels)
            ]
            start_id, end_id, opposite_id, target_id = point_ids
            start = all_points.get(start_id)
            end = all_points.get(end_id)
            target = all_points.get(target_id)
            if start is None or end is None or target is None:
                continue
            if opposite_id in all_points:
                opposite = all_points[opposite_id]
            else:
                opposite = _derive_square_fourth_vertex(
                    start=start,
                    end=end,
                    adjacent=target,
                )
                if opposite is None:
                    continue
                if _pair_depends_on_parameter(opposite, parameter_name):
                    moving.setdefault(opposite_id, opposite)
                else:
                    fixed.setdefault(opposite_id, opposite)
                all_points[opposite_id] = opposite
                point_meta.setdefault(
                    opposite_id,
                    namer.scope_namer.point_meta(labels[2], scope_id),
                )
            _add_square_projection_point(
                fixed=fixed,
                moving=moving,
                all_points=all_points,
                point_meta=point_meta,
                point_id=square_projection_point_id(labels[0], labels[1], scope_id),
                label=f"{labels[0]}{labels[1]}_projection",
                scope_id=scope_id,
                pair=[end[0], start[1]],
                parameter_name=parameter_name,
            )
            _add_square_projection_point(
                fixed=fixed,
                moving=moving,
                all_points=all_points,
                point_meta=point_meta,
                point_id=square_projection_point_id(labels[0], labels[3], scope_id),
                label=f"{labels[0]}{labels[3]}_projection",
                scope_id=scope_id,
                pair=[target[0], start[1]],
                parameter_name=parameter_name,
            )


def _square_instance_scopes(
    labels: list[str],
    point_meta: dict[str, JsonObject],
) -> tuple[str, ...]:
    scopes: list[str] = []
    for meta in point_meta.values():
        if not isinstance(meta, dict) or str(meta.get("label") or "") not in labels:
            continue
        scope = str(meta.get("scopeId") or "")
        if scope and scope != "problem" and scope not in scopes:
            scopes.append(scope)
    # Prefer the most specific branches.  A parent definition remains visible
    # to a child through normal scope lookup and does not create a second
    # square instance on its own.
    return tuple(
        scope
        for scope in sorted(scopes, key=lambda value: (value.count("_"), value))
        if not any(other.startswith(f"{scope}_") for other in scopes)
    )


def _add_square_structural_points(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    all_points = {**fixed, **moving}
    facts = {
        str(fact.get("handle")): fact
        for fact in (snapshot.problem or {}).get("facts") or ()
        if isinstance(fact, dict) and fact.get("handle")
    }
    for fact in facts.values():
        if fact.get("type") != "midpoint_definition":
            continue
        point_label = _label_from_square_vertex_handle(str(fact.get("point") or ""), snapshot)
        endpoints = [
            _label_from_square_vertex_handle(str(handle), snapshot)
            for handle in fact.get("of") or ()
            if handle
        ]
        if not point_label or len(endpoints) != 2:
            continue
        scope_id = str(fact.get("scope_id") or "")
        start = all_points.get(_structural_point_ref(endpoints[0], scope_id, all_points))
        end = all_points.get(_structural_point_ref(endpoints[1], scope_id, all_points))
        if start is None or end is None:
            continue
        _add_structural_visual_point(
            fixed=fixed,
            moving=moving,
            all_points=all_points,
            point_meta=point_meta,
            point_id=namer.scope_namer.geometry_id(point_label, scope_id),
            label=point_label,
            scope_id=scope_id,
            pair=_midpoint_pair(start, end),
            parameter_name=parameter_name,
        )
    for fact in facts.values():
        if fact.get("type") != "square_center":
            continue
        point_label = _label_from_square_vertex_handle(str(fact.get("point") or ""), snapshot)
        square = facts.get(str(fact.get("square") or ""))
        if not point_label or not isinstance(square, dict):
            continue
        vertices = [
            _label_from_square_vertex_handle(str(handle), snapshot)
            for handle in square.get("vertices") or ()
            if handle
        ]
        if len(vertices) < 4:
            continue
        scope_id = str(fact.get("scope_id") or square.get("scope_id") or "")
        diagonal = (vertices[1], vertices[3])
        start = all_points.get(_structural_point_ref(diagonal[0], scope_id, all_points))
        end = all_points.get(_structural_point_ref(diagonal[1], scope_id, all_points))
        if start is None or end is None:
            continue
        _add_structural_visual_point(
            fixed=fixed,
            moving=moving,
            all_points=all_points,
            point_meta=point_meta,
            point_id=namer.scope_namer.geometry_id(point_label, scope_id),
            label=point_label,
            scope_id=scope_id,
            pair=_midpoint_pair(start, end),
            parameter_name=parameter_name,
        )


def _structural_point_ref(label: str, scope_id: str, all_points: dict[str, list[str]]) -> str:
    axis_id = axis_parameter_point_id(label, scope_id)
    if axis_id in all_points:
        return axis_id
    return _square_geometry_point_id(label, scope_id, all_points)


def _midpoint_pair(start: list[str], end: list[str]) -> list[str]:
    import sympy as sp

    return [
        _page_expr((sp.sympify(str(start[index])) + sp.sympify(str(end[index]))) / 2)
        for index in (0, 1)
    ]


def _add_structural_visual_point(
    *,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    all_points: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    point_id: str,
    label: str,
    scope_id: str,
    pair: list[str],
    parameter_name: str,
) -> None:
    if point_id in all_points:
        return
    if _pair_depends_on_parameter(pair, parameter_name):
        moving[point_id] = pair
    else:
        fixed[point_id] = pair
    all_points[point_id] = pair
    point_meta.setdefault(
        point_id,
        {
            "label": label,
            "scopeId": scope_id,
            "scopeRoot": _scope_root(scope_id),
            "visualOnly": True,
        },
    )


def _add_axis_parameter_candidate_points(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    all_points = {**fixed, **moving}
    candidate_source_steps = {
        source.source_step_id
        for source in iter_teaching_sources(snapshot.root_scope)
        if any(
            str(output.get("runtime_type") or "") == "PointList"
            for output in source.outputs.values()
        )
    }
    for step in snapshot.effective_steps:
        if (
            not isinstance(step, dict)
            or str(step.get("step_id") or "") not in candidate_source_steps
        ):
            continue
        scope_id = str(step.get("scope_id") or "")
        target_label = _candidate_target_label(step)
        if not target_label:
            continue
        target_pair = _candidate_point_pair_for_label(step, snapshot, target_label)
        curve_label, curve_pair = _candidate_curve_point(step, snapshot, target_label)
        parameter = _candidate_axis_parameter(target_pair, curve_pair)
        candidates = _candidate_point_list(step, snapshot)
        if target_pair is None or parameter is None or not candidates:
            continue
        candidates = _sort_candidate_points(candidates, target_pair, parameter)
        square = _square_fact_for_candidate_step(snapshot, scope_id, target_label, curve_label)
        square_labels = (
            [_label_from_square_vertex_handle(handle, snapshot) for handle in square.get("vertices", ())[:4]]
            if square
            else []
        )
        for index, candidate in enumerate(candidates, start=1):
            parameter_value = _candidate_parameter_value(target_pair, candidate, parameter)
            if parameter_value is None:
                continue
            target_id = axis_parameter_candidate_point_id(target_label, scope_id, index)
            _add_candidate_point(
                fixed=fixed,
                moving=moving,
                all_points=all_points,
                point_meta=point_meta,
                point_id=target_id,
                label=target_label,
                scope_id=scope_id,
                pair=[_page_expr(candidate[0]), _page_expr(candidate[1])],
                candidate_index=index,
                parameter_name=parameter_name,
            )
            candidate_pairs: dict[str, list[str]] = {target_label: [_page_expr(candidate[0]), _page_expr(candidate[1])]}
            if curve_label and curve_pair is not None:
                curve_candidate = [
                    _page_expr(sp_expr.subs(parameter, parameter_value))
                    for sp_expr in curve_pair
                ]
                candidate_pairs[curve_label] = curve_candidate
                _add_candidate_point(
                    fixed=fixed,
                    moving=moving,
                    all_points=all_points,
                    point_meta=point_meta,
                    point_id=axis_parameter_candidate_point_id(curve_label, scope_id, index),
                    label=curve_label,
                    scope_id=scope_id,
                    pair=curve_candidate,
                    candidate_index=index,
                    parameter_name=parameter_name,
                )
            if len(square_labels) >= 4:
                _add_square_candidate_vertices(
                    labels=square_labels,
                    scope_id=scope_id,
                    candidate_index=index,
                    candidate_pairs=candidate_pairs,
                    fixed=fixed,
                    moving=moving,
                    all_points=all_points,
                    point_meta=point_meta,
                    namer=namer,
                    parameter_name=parameter_name,
                )


def _add_public_candidate_geometry(
    *,
    snapshot: ExplanationSnapshot,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    """Register public candidate coordinates by typed source provenance.

    Candidate lists are hypothetical alternatives, so they have identities
    distinct from the selected mathematical point even when one coordinate
    later coincides with that point.  Their identity comes from the public
    producer step and candidate position, never from a displayed label.
    """

    owners = teaching_source_owners(snapshot.root_scope)
    all_points = {**fixed, **moving}
    for source in iter_teaching_sources(snapshot.root_scope):
        owner = owners.get(source.source_step_id)
        if owner is None:
            raise ValueError(
                "visual_candidate_source_owner_missing: "
                f"{source.source_step_id}"
            )
        scope_id = owner[0]
        candidate_lists: list[list[Any]] = []
        for output in source.outputs.values():
            if str(output.get("runtime_type") or "") != "PointList":
                continue
            raw = output.get("value")
            if isinstance(raw, (list, tuple)):
                candidate_lists.append(list(raw))
        for calculation in source.calculations:
            for key in ("candidates", "points"):
                raw = calculation.get(key)
                if isinstance(raw, (list, tuple)):
                    candidate_lists.append(list(raw))

        unique_lists: list[list[Any]] = []
        signatures: set[str] = set()
        for candidates in candidate_lists:
            signature = json.dumps(
                candidates,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
            if signature in signatures:
                continue
            signatures.add(signature)
            unique_lists.append(candidates)

        base_label = _candidate_source_label(source)
        for group_index, candidates in enumerate(unique_lists, start=1):
            for candidate_index, raw_point in enumerate(candidates, start=1):
                if not _is_point_value(raw_point):
                    continue
                point_id = scoped_point_id(
                    (
                        f"candidate_{_safe_visual_token(source.source_step_id)}_"
                        f"{group_index}_{candidate_index}"
                    ),
                    scope_id,
                )
                pair = _page_point_pair(raw_point)
                label = (
                    f"{base_label}{_student_candidate_suffix(candidate_index)}"
                    if base_label
                    else f"候选{candidate_index}"
                )
                if _pair_depends_on_parameter(pair, parameter_name):
                    moving[point_id] = pair
                    fixed.pop(point_id, None)
                else:
                    fixed[point_id] = pair
                    moving.pop(point_id, None)
                all_points[point_id] = pair
                point_meta[point_id] = {
                    "label": label,
                    "scopeId": scope_id,
                    "scopeRoot": _scope_root(scope_id),
                    "definition": "public_candidate",
                    "sourceStepId": source.source_step_id,
                    "candidateGroup": group_index,
                    "candidateIndex": candidate_index,
                    "visualOnly": True,
                }


def _add_anonymous_result_points(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    """Materialize consumed anonymous Point returns by exact producer identity."""
    sources = tuple(iter_teaching_sources(snapshot.root_scope))
    owners = teaching_source_owners(snapshot.root_scope)
    used_labels = {str(meta.get("label") or "") for meta in point_meta.values()}
    used_labels.update(str(e.get("name") or "") for e in (snapshot.problem or {}).get("entities", ()))
    consumed = {
        (str(ref.get("step_id")), str(ref.get("return")))
        for source in sources
        for values in source.inputs.values()
        for value in values
        if isinstance((ref := value.get("ref")), dict)
        and ref.get("kind") == "step_result"
    }
    for source in sources:
        scope_id = owners[source.source_step_id][0]
        for return_name, output in source.outputs.items():
            if (source.source_step_id, return_name) not in consumed:
                continue
            if output.get("runtime_type") != "Point" or not _is_point_value(output.get("value")):
                continue
            if _problem_point_handles_for_output(
                source, return_name, snapshot=snapshot, scope_id=scope_id,
            ):
                continue
            identity = json.dumps([scope_id, source.source_step_id, return_name])
            point_id = "point_result_" + sha256(identity.encode()).hexdigest()[:24]
            pair = _page_point_pair(output["value"])
            labels = {
                label
                for step in lesson.steps
                if source.source_step_id in step.source_step_ids
                for label in _coordinate_conclusion_labels_for_value(step, ",".join(pair))
            }
            preferred = next(iter(labels)) if len(labels) == 1 else None
            label = preferred if preferred and preferred not in used_labels else next(
                (letter for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if letter not in used_labels),
                "",
            )
            if not label:
                suffix = len(used_labels)
                while f"P{suffix}" in used_labels:
                    suffix += 1
                label = f"P{suffix}"
            used_labels.add(label)
            (moving if _pair_depends_on_parameter(pair, parameter_name) else fixed)[point_id] = pair
            point_meta[point_id] = {
                "label": label,
                "scopeId": scope_id,
                "scopeRoot": _scope_root(scope_id),
                "definition": "anonymous_step_result",
                "sourceStepId": source.source_step_id,
                "returnName": return_name,
                "visualOnly": True,
            }


def _add_public_construction_auxiliary_geometry(
    *,
    snapshot: ExplanationSnapshot,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    """Register proof-construction points carried by verified calculations.

    Candidate-producing methods may expose perpendicular-foot constructions
    that are essential to the student proof but are not semantic problem
    entities.  Preserve their typed source/role identity so coincident points
    (for example a foot at the origin) remain independently labelable.
    """

    owners = teaching_source_owners(snapshot.root_scope)
    for source in iter_teaching_sources(snapshot.root_scope):
        owner = owners.get(source.source_step_id)
        if owner is None:
            raise ValueError(
                "visual_construction_source_owner_missing: "
                f"{source.source_step_id}"
            )
        scope_id = owner[0]
        for calculation in source.calculations:
            geometry = calculation.get("geometry")
            if not isinstance(geometry, Mapping):
                continue
            if (
                str(geometry.get("kind") or "")
                != "axis_projection_candidate_construction"
            ):
                continue

            auxiliary_points: list[tuple[str, int, Any, Mapping[str, Any]]] = []
            student_reference = geometry.get("student_reference_projection")
            if isinstance(student_reference, Mapping):
                auxiliary_points.append(
                    (
                        "reference_projection",
                        0,
                        student_reference.get("coordinates")
                        or geometry.get("reference_projection"),
                        student_reference,
                    )
                )
            for branch_index, branch in enumerate(
                geometry.get("candidate_branches") or (),
                start=1,
            ):
                if not isinstance(branch, Mapping):
                    continue
                student_projection = branch.get("student_projection")
                if not isinstance(student_projection, Mapping):
                    continue
                auxiliary_points.append(
                    (
                        "candidate_projection",
                        branch_index,
                        student_projection.get("coordinates")
                        or branch.get("projection"),
                        student_projection,
                    )
                )

            for role, branch_index, raw_point, student_point in auxiliary_points:
                if not _is_point_value(raw_point):
                    continue
                role_token = role
                if branch_index:
                    role_token = f"{role}_{branch_index}"
                point_id = scoped_point_id(
                    (
                        f"construction_{_safe_visual_token(source.source_step_id)}_"
                        f"{role_token}"
                    ),
                    scope_id,
                )
                pair = _page_point_pair(raw_point)
                if _pair_depends_on_parameter(pair, parameter_name):
                    moving[point_id] = pair
                    fixed.pop(point_id, None)
                else:
                    fixed[point_id] = pair
                    moving.pop(point_id, None)
                point_meta[point_id] = {
                    "label": str(student_point.get("label") or ""),
                    "scopeId": scope_id,
                    "scopeRoot": _scope_root(scope_id),
                    "definition": "public_construction_auxiliary",
                    "sourceStepId": source.source_step_id,
                    "constructionRole": role,
                    "branchIndex": branch_index,
                    "visualOnly": True,
                }


def _add_endpoint_replacement_witness_geometry(
    *,
    snapshot: ExplanationSnapshot,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    """Materialize a representative verified endpoint-replacement diagram."""

    owners = teaching_source_owners(snapshot.root_scope)
    known_points = {**fixed, **moving}

    def point_pair(label: str, scope_id: str) -> tuple[sp.Expr, sp.Expr] | None:
        candidates: list[tuple[int, str]] = []
        for point_id, meta in point_meta.items():
            if not isinstance(meta, Mapping) or str(meta.get("label") or "") != label:
                continue
            meta_scope = str(meta.get("scopeId") or "")
            meta_root = str(meta.get("scopeRoot") or _scope_root(meta_scope))
            if meta_scope != scope_id and meta_root != _scope_root(scope_id):
                continue
            definition = str(meta.get("definition") or "")
            priority = {
                "runtime_point_output": 5,
                "given_point": 4,
                "axis_x_intercept": 3,
                "public_candidate": 2,
            }.get(definition, 1)
            candidates.append((priority, point_id))
        for _, point_id in sorted(candidates, reverse=True):
            pair = _sympy_point_pair(known_points.get(point_id))
            if pair is not None:
                return pair
        return None

    for witness in snapshot.macro_evidence:
        source_step_id = str(witness.get("step_id") or "")
        construction = next(
            (
                item
                for item in witness.get("constructions") or ()
                if isinstance(item, Mapping)
                and item.get("kind") == "existing_fixed_endpoint_replacement"
            ),
            None,
        )
        if not isinstance(construction, Mapping):
            continue
        owner = owners.get(source_step_id)
        if owner is None:
            raise ValueError(
                "visual_endpoint_replacement_source_owner_missing: "
                f"{source_step_id}"
            )
        scope_id = owner[0]
        certificate = (
            construction.get("geometry_certificate")
            if isinstance(construction, Mapping)
            else None
        )
        roles = certificate.get("roles") if isinstance(certificate, Mapping) else None
        if not isinstance(roles, Mapping):
            continue
        anchor_label = str(roles.get("right_vertex") or "")
        first_vertex_label = str(roles.get("first_leg_vertex") or "")
        second_vertex_label = str(roles.get("second_leg_vertex") or "")
        anchor = point_pair(anchor_label, scope_id)
        first_vertex = point_pair(first_vertex_label, scope_id)
        second_vertex = point_pair(second_vertex_label, scope_id)
        if anchor is None or first_vertex is None or second_vertex is None:
            raise ValueError(
                "visual_endpoint_replacement_frame_points_missing: "
                f"step={source_step_id}"
            )

        ratio = sp.Rational(3, 4)
        one_minus = 1 - ratio

        def interpolate(
            start: tuple[sp.Expr, sp.Expr],
            end: tuple[sp.Expr, sp.Expr],
            amount: sp.Expr,
        ) -> tuple[sp.Expr, sp.Expr]:
            return (
                sp.simplify(start[0] + amount * (end[0] - start[0])),
                sp.simplify(start[1] + amount * (end[1] - start[1])),
            )

        first_leg_point = interpolate(anchor, first_vertex, 2 * one_minus)
        moving_point = interpolate(first_vertex, second_vertex, ratio)
        first_projection = interpolate(anchor, first_vertex, one_minus)
        second_projection = interpolate(anchor, second_vertex, ratio)
        student_first_projection = certificate.get("student_first_leg_projection")
        student_second_projection = certificate.get("student_second_leg_projection")
        visual_points = (
            (
                "first_leg_moving_point",
                str(roles.get("first_leg_moving_point") or ""),
                first_leg_point,
            ),
            (
                "hypotenuse_moving_point",
                str(roles.get("hypotenuse_moving_point") or ""),
                moving_point,
            ),
            (
                "first_leg_projection",
                str(
                    (student_first_projection or {}).get("label")
                    if isinstance(student_first_projection, Mapping)
                    else ""
                ),
                first_projection,
            ),
            (
                "second_leg_projection",
                str(
                    (student_second_projection or {}).get("label")
                    if isinstance(student_second_projection, Mapping)
                    else ""
                ),
                second_projection,
            ),
        )
        for construction_role, label, pair in visual_points:
            if not label:
                raise ValueError(
                    "visual_endpoint_replacement_student_label_missing: "
                    f"step={source_step_id}, role={construction_role}"
                )
            point_id = scoped_point_id(
                (
                    f"endpoint_replacement_{_safe_visual_token(source_step_id)}_"
                    f"{construction_role}"
                ),
                scope_id,
            )
            page_pair = [_page_expr(pair[0]), _page_expr(pair[1])]
            if _pair_depends_on_parameter(page_pair, parameter_name):
                moving[point_id] = page_pair
                fixed.pop(point_id, None)
            else:
                fixed[point_id] = page_pair
                moving.pop(point_id, None)
            known_points[point_id] = page_pair
            point_meta[point_id] = {
                "label": label,
                "scopeId": scope_id,
                "scopeRoot": _scope_root(scope_id),
                "definition": "endpoint_replacement_construction",
                "sourceStepId": source_step_id,
                "constructionRole": construction_role,
                "visualOnly": True,
            }


def _candidate_source_label(source: Any) -> str:
    targets = {
        str(value)
        for value in source.output_targets.values()
        if str(value)
    }
    if len(targets) == 1:
        return _label_from_semantic_name(next(iter(targets)))
    point_ref_names = {
        str(value.get("name") or "")
        for values in source.inputs.values()
        for item in values
        if str(item.get("runtime_type") or "") in {"PointRef", "Point"}
        and isinstance((value := item.get("value")), Mapping)
        and str(value.get("entity_type") or "point") == "point"
        and str(value.get("name") or "")
    }
    if len(point_ref_names) == 1:
        return next(iter(point_ref_names))
    return ""


def _student_candidate_suffix(index: int) -> str:
    digits = str(max(1, int(index)))
    return digits.translate(str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉"))


def _add_square_path_witness_points(
    *,
    snapshot: ExplanationSnapshot,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
) -> None:
    all_points = {**fixed, **moving}
    steps = {
        str(step.get("step_id") or ""): step
        for step in snapshot.effective_steps
        if isinstance(step, dict)
    }
    for witness in snapshot.macro_evidence:
        scope_id = str(
            steps.get(str(witness.get("step_id") or ""), {}).get(
                "scope_id", ""
            )
        )
        role_values = {
            str(item.get("role") or ""): str(item.get("chosen_ref") or "")
            for item in witness.get("role_resolutions", ())
            if isinstance(item, dict)
        }
        if not {
            "side_start",
            "axis_point",
            "moving_point",
            "fixed_endpoint",
        }.issubset(role_values):
            continue
        construction_kinds = {
            str(item.get("kind") or "")
            for item in witness.get("constructions", ())
            if isinstance(item, dict)
        }
        if not {
            "square_midpoint_center_reduction",
            "line_reflection",
        }.issubset(construction_kinds):
            continue
        square_fact = _square_fact_for_witness_roles(
            snapshot,
            role_values=role_values,
            scope_id=scope_id,
        )
        if isinstance(square_fact, dict):
            square_labels = [
                _label_from_square_vertex_handle(str(handle), snapshot)
                for handle in square_fact.get("vertices") or ()
            ]
            side_start = role_values.get("side_start", "")
            moving_label = role_values.get("moving_point", "")
            if (
                len(square_labels) >= 4
                and side_start in square_labels
                and moving_label in square_labels
            ):
                start_id = _geometry_id_for_label_and_scope(
                    side_start,
                    scope_id,
                    point_meta,
                    prefer_axis=False,
                )
                moving_id = _geometry_id_for_label_and_scope(
                    moving_label,
                    scope_id,
                    point_meta,
                    prefer_axis=False,
                )
                start_pair = all_points.get(start_id)
                moving_pair = all_points.get(moving_id)
                if start_pair is not None and moving_pair is not None:
                    start_index = square_labels.index(side_start)
                    side_end_label = square_labels[(start_index + 1) % 4]
                    opposite_label = square_labels[(start_index + 2) % 4]
                    # The ordered square vertices determine the +90° turn from
                    # the previous side (moving -> start) to start -> side_end.
                    side_end_pair, opposite_pair = _ordered_square_pairs_from_adjacent(
                        start_pair,
                        moving_pair,
                    )
                    if side_end_pair is not None and opposite_pair is not None:
                        side_end_id = axis_parameter_point_id(side_end_label, scope_id)
                        opposite_id = axis_parameter_point_id(opposite_label, scope_id)
                        _add_structural_visual_point(
                            fixed=fixed,
                            moving=moving,
                            all_points=all_points,
                            point_meta=point_meta,
                            point_id=side_end_id,
                            label=side_end_label,
                            scope_id=scope_id,
                            pair=side_end_pair,
                            parameter_name=parameter_name,
                        )
                        _add_structural_visual_point(
                            fixed=fixed,
                            moving=moving,
                            all_points=all_points,
                            point_meta=point_meta,
                            point_id=opposite_id,
                            label=opposite_label,
                            scope_id=scope_id,
                            pair=opposite_pair,
                            parameter_name=parameter_name,
                        )
                        midpoint_label = _point_label_for_relation(
                            snapshot,
                            relation_type="midpoint_definition",
                            relation_ref=role_values.get("midpoint_definition", ""),
                            scope_id=scope_id,
                        )
                        center_label = _point_label_for_relation(
                            snapshot,
                            relation_type="square_center",
                            relation_ref=role_values.get("square_center", ""),
                            scope_id=scope_id,
                        )
                        if midpoint_label:
                            _add_structural_visual_point(
                                fixed=fixed,
                                moving=moving,
                                all_points=all_points,
                                point_meta=point_meta,
                                point_id=axis_parameter_point_id(midpoint_label, scope_id),
                                label=midpoint_label,
                                scope_id=scope_id,
                                pair=_midpoint_pair(start_pair, side_end_pair),
                                parameter_name=parameter_name,
                            )
                        if center_label:
                            _add_structural_visual_point(
                                fixed=fixed,
                                moving=moving,
                                all_points=all_points,
                                point_meta=point_meta,
                                point_id=axis_parameter_point_id(center_label, scope_id),
                                label=center_label,
                                scope_id=scope_id,
                                pair=_midpoint_pair(side_end_pair, moving_pair),
                                parameter_name=parameter_name,
                            )
        fixed_label = next(
            (
                str(item.get("chosen_ref") or "")
                for item in witness.get("role_resolutions", ())
                if isinstance(item, dict)
                and item.get("role") == "fixed_endpoint"
            ),
            "",
        )
        fixed_id = _geometry_id_for_label_and_scope(
            fixed_label,
            scope_id,
            point_meta,
            prefer_axis=False,
        )
        fixed_pair = all_points.get(fixed_id)
        if fixed_label and fixed_pair is not None:
            _add_structural_visual_point(
                fixed=fixed,
                moving=moving,
                all_points=all_points,
                point_meta=point_meta,
                point_id=axis_parameter_point_id(fixed_label, scope_id),
                label=fixed_label,
                scope_id=scope_id,
                pair=list(fixed_pair),
                parameter_name=parameter_name,
            )
        construction = next(
            (
                item
                for item in witness.get("constructions", ())
                if isinstance(item, dict)
                and item.get("kind") == "line_reflection"
            ),
            None,
        )
        if construction is None:
            continue
        locus = next(
            (
                item
                for item in witness.get("constructions", ())
                if isinstance(item, dict)
                and item.get("kind") == "square_midpoint_center_reduction"
            ),
            None,
        )
        moving_label = role_values.get("moving_point", "")
        moving_id = _geometry_id_for_label_and_scope(
            moving_label,
            scope_id,
            point_meta,
            prefer_axis=False,
        )
        moving_pair = all_points.get(moving_id)
        if moving_id and moving_id in point_meta:
            meta = dict(point_meta[moving_id])
            raw_semantic_roles = meta.get("semanticRoles", ())
            semantic_roles = (
                (raw_semantic_roles,)
                if isinstance(raw_semantic_roles, str)
                else tuple(raw_semantic_roles)
            )
            meta["semanticRoles"] = sorted(
                {
                    *(
                        str(item)
                        for item in semantic_roles
                        if str(item)
                    ),
                    "path_attainment_point",
                }
            )
            source_step_id = str(witness.get("step_id") or "")
            raw_source_steps = meta.get("sourceStepIds", ())
            source_steps = (
                (raw_source_steps,)
                if isinstance(raw_source_steps, str)
                else tuple(raw_source_steps)
            )
            meta["sourceStepIds"] = list(
                dict.fromkeys(
                    [
                        *(
                            str(item)
                            for item in source_steps
                            if str(item)
                        ),
                        *(item for item in (source_step_id,) if item),
                    ]
                )
            )
            point_meta[moving_id] = meta
        locus_y = _horizontal_locus_y(
            str((locus or {}).get("moving_locus") or "")
        )
        if moving_label and moving_pair is not None and locus_y is not None:
            for side, delta in (("start", -4), ("end", 4)):
                _add_structural_visual_point(
                    fixed=fixed,
                    moving=moving,
                    all_points=all_points,
                    point_meta=point_meta,
                    point_id=locus_line_endpoint_id(moving_label, scope_id, side),
                    label=f"{moving_label}_locus_{side}",
                    scope_id=scope_id,
                    pair=[
                        _page_expr(sp.sympify(str(moving_pair[0])) + delta),
                        _page_expr(locus_y),
                    ],
                    parameter_name=parameter_name,
                )
        label = str(construction.get("reflected_point_name") or "")
        pair = construction.get("reflected_point")
        if not label or not isinstance(pair, list | tuple) or len(pair) != 2:
            continue
        point_id = GeometryPointScopeNamer(
            problem_point_names=frozenset(),
            label_roots={},
        ).geometry_id(label.replace("′", "_prime"), scope_id)
        _add_structural_visual_point(
            fixed=fixed,
            moving=moving,
            all_points=all_points,
            point_meta=point_meta,
            point_id=point_id,
            label=_student_point_label(point_id),
            scope_id=scope_id,
            pair=[str(item) for item in pair],
            parameter_name=parameter_name,
        )


def _horizontal_locus_y(equation: str) -> sp.Expr | None:
    match = re.fullmatch(r"\s*y\s*=\s*(.+?)\s*", str(equation))
    if not match:
        return None
    try:
        return sp.sympify(match.group(1).replace("^", "**"))
    except Exception:
        return None


def _ordered_square_pairs_from_adjacent(
    start: list[str],
    previous: list[str],
) -> tuple[list[str] | None, list[str] | None]:
    if len(start) != 2 or len(previous) != 2:
        return None, None
    try:
        sx, sy = (sp.sympify(str(value)) for value in start)
        px, py = (sp.sympify(str(value)) for value in previous)
        # start -> previous rotated counter-clockwise gives start -> next for
        # the ordered square vertices [start, next, opposite, previous].
        dx = px - sx
        dy = py - sy
        side_end = [sp.simplify(sx - dy), sp.simplify(sy + dx)]
        opposite = [sp.simplify(px - dy), sp.simplify(py + dx)]
        return (
            [_page_expr(value) for value in side_end],
            [_page_expr(value) for value in opposite],
        )
    except Exception:
        return None, None


def _square_fact_for_witness_roles(
    snapshot: ExplanationSnapshot,
    *,
    role_values: dict[str, str],
    scope_id: str,
) -> dict[str, Any] | None:
    required_handles = {
        _resolve_problem_point_handle(snapshot, role_values.get(role, ""), scope_id)
        for role in ("side_start", "axis_point", "moving_point")
    }
    required_handles.discard("")
    if len(required_handles) != 3:
        raise ValueError(
            "visual_quadratic_square_witness_roles_invalid: "
            f"scope={scope_id}, roles={role_values}"
        )
    matches: list[dict[str, Any]] = []
    for fact in (snapshot.problem or {}).get("facts") or ():
        if not isinstance(fact, dict) or fact.get("type") != "square":
            continue
        vertices = {
            _resolve_problem_point_handle(snapshot, str(item), scope_id)
            for item in fact.get("vertices") or ()
        }
        vertices.discard("")
        if required_handles <= vertices:
            matches.append(fact)
    if len(matches) > 1:
        raise ValueError(
            "visual_quadratic_square_witness_square_ambiguous: "
            f"scope={scope_id}, matches={[item.get('handle') for item in matches]}"
        )
    if not matches:
        raise ValueError(
            "visual_quadratic_square_witness_square_missing: "
            f"scope={scope_id}, roles={sorted(required_handles)}"
        )
    return matches[0]


def _resolve_problem_point_handle(
    snapshot: ExplanationSnapshot,
    semantic_ref: str,
    scope_id: str,
) -> str:
    item = _resolve_problem_semantic_item(
        snapshot,
        semantic_ref=semantic_ref,
        scope_id=scope_id,
        collection="entities",
        expected_type="point",
    )
    return str(item.get("handle") or "") if item is not None else ""


def _resolve_problem_semantic_item(
    snapshot: ExplanationSnapshot,
    *,
    semantic_ref: str,
    scope_id: str,
    collection: str,
    expected_type: str,
) -> dict[str, Any] | None:
    ref = str(semantic_ref or "")
    if not ref:
        return None
    lineage = scope_lineage(scope_id)
    scored: list[tuple[int, dict[str, Any]]] = []
    for raw in (snapshot.problem or {}).get(collection) or ():
        if not isinstance(raw, dict):
            continue
        item_type = str(raw.get("entity_type") or raw.get("type") or "")
        if item_type != expected_type:
            continue
        handle = str(raw.get("handle") or "")
        name = str(raw.get("name") or "")
        handle_tail = handle.rsplit(":", 1)[-1] if handle else ""
        if ref == handle:
            semantic_score = 300
        elif ref == name:
            semantic_score = 200
        elif ref == handle_tail:
            semantic_score = 100
        else:
            continue
        item_scope = str(raw.get("scope_id") or "problem")
        if item_scope not in lineage:
            continue
        scope_score = len(lineage) - lineage.index(item_scope)
        scored.append((semantic_score + scope_score, raw))
    if not scored:
        return None
    best_score = max(score for score, _ in scored)
    winners = [item for score, item in scored if score == best_score]
    if len(winners) != 1:
        raise ValueError(
            "visual_problem_semantic_ref_ambiguous: "
            f"ref={ref}, scope={scope_id}, "
            f"matches={sorted(str(item.get('handle') or '') for item in winners)}"
        )
    return winners[0]


def _point_label_for_relation(
    snapshot: ExplanationSnapshot,
    *,
    relation_type: str,
    relation_ref: str,
    scope_id: str,
) -> str:
    fact = _resolve_problem_semantic_item(
        snapshot,
        semantic_ref=relation_ref,
        scope_id=scope_id,
        collection="facts",
        expected_type=relation_type,
    )
    if not isinstance(fact, dict):
        return ""
    return _label_from_square_vertex_handle(str(fact.get("point") or ""), snapshot)


def _geometry_id_for_label_and_scope(
    label: str,
    scope_id: str,
    point_meta: dict[str, JsonObject],
    *,
    prefer_axis: bool,
) -> str:
    matches = [
        str(point_id)
        for point_id, meta in point_meta.items()
        if isinstance(meta, dict)
        and str(meta.get("label") or "") == label
        and str(meta.get("scopeId") or "") == scope_id
    ]
    if prefer_axis:
        axis = axis_parameter_point_id(label, scope_id)
        if axis in matches:
            return axis
    non_axis = [item for item in matches if item != axis_parameter_point_id(label, scope_id)]
    if len(non_axis) == 1:
        return non_axis[0]
    if len(matches) == 1:
        return matches[0]
    return GeometryPointScopeNamer(
        problem_point_names=frozenset(),
        label_roots={},
    ).geometry_id(label, scope_id)


def _runtime_line_for_locus_step(step: dict[str, Any], snapshot: ExplanationSnapshot) -> dict[str, Any] | None:
    step_id = str(step.get("step_id") or "")
    target_tail = _handle_tail(str(step.get("target") or ""))
    fallback: dict[str, Any] | None = None
    for handle, item in snapshot.fact_index.items():
        if not isinstance(item, dict) or item.get("type") != "Line":
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        if step_id and _fact_step_id(item) == step_id:
            return value
        if target_tail and (
            str(item.get("name") or "") == target_tail
            or str(handle).endswith(f":outputs:{target_tail}")
        ):
            fallback = value
    return fallback


def _locus_line_endpoint_pairs(
    line: dict[str, Any],
    domain: JsonObject,
) -> tuple[list[str], list[str]] | None:
    start = _sympy_point_pair(line.get("start_point"))
    direction = _sympy_point_pair(line.get("direction"))
    if start is None or direction is None:
        return None
    min_x = sp.sympify(str(domain.get("minX", -5)))
    max_x = sp.sympify(str(domain.get("maxX", 5)))
    min_y = sp.sympify(str(domain.get("minY", -5)))
    max_y = sp.sympify(str(domain.get("maxY", 5)))
    if sp.simplify(direction[1]) == 0:
        return ([_page_expr(min_x), _page_expr(start[1])], [_page_expr(max_x), _page_expr(start[1])])
    if sp.simplify(direction[0]) == 0:
        return ([_page_expr(start[0]), _page_expr(min_y)], [_page_expr(start[0]), _page_expr(max_y)])
    return (
        [_page_expr(start[0] - 10 * direction[0]), _page_expr(start[1] - 10 * direction[1])],
        [_page_expr(start[0] + 10 * direction[0]), _page_expr(start[1] + 10 * direction[1])],
    )


def _sympy_point_pair(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    return sympy_pair(value)


def _locus_point_label_for_step(step: dict[str, Any]) -> str:
    for handle in step.get("reads") or ():
        if isinstance(handle, str) and handle.startswith("point:"):
            return _label_from_semantic_name(_handle_tail(handle))
    return ""


def _label_from_locus_target(target: str) -> str:
    name = _handle_tail(target)
    for suffix in ("_locus_line", "_line", "_locus"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return _label_from_semantic_name(name)


def _add_candidate_point(
    *,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    all_points: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    point_id: str,
    label: str,
    scope_id: str,
    pair: list[str],
    candidate_index: int,
    parameter_name: str,
) -> None:
    if _pair_depends_on_parameter(pair, parameter_name):
        moving[point_id] = pair
    else:
        fixed[point_id] = pair
    all_points[point_id] = pair
    point_meta[point_id] = {
        "label": label,
        "scopeId": scope_id,
        "scopeRoot": _scope_root(scope_id),
        "candidateIndex": candidate_index,
        "visualOnly": True,
    }


def _add_square_candidate_vertices(
    *,
    labels: list[str],
    scope_id: str,
    candidate_index: int,
    candidate_pairs: dict[str, list[str]],
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    all_points: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    namer: GeometryPointNamer,
    parameter_name: str,
) -> None:
    if len(labels) < 4:
        return
    start_label, end_label, opposite_label, adjacent_label = labels[:4]
    for label in labels[:4]:
        if label in candidate_pairs:
            point_id = axis_parameter_candidate_point_id(label, scope_id, candidate_index)
            _add_candidate_point(
                fixed=fixed,
                moving=moving,
                all_points=all_points,
                point_meta=point_meta,
                point_id=point_id,
                label=label,
                scope_id=scope_id,
                pair=candidate_pairs[label],
                candidate_index=candidate_index,
                parameter_name=parameter_name,
            )
    start = _candidate_or_existing_pair(start_label, scope_id, candidate_index, candidate_pairs, all_points, namer)
    end = _candidate_or_existing_pair(end_label, scope_id, candidate_index, candidate_pairs, all_points, namer)
    adjacent = _candidate_or_existing_pair(adjacent_label, scope_id, candidate_index, candidate_pairs, all_points, namer)
    if start is None or end is None or adjacent is None:
        return
    opposite_id = axis_parameter_candidate_point_id(opposite_label, scope_id, candidate_index)
    if opposite_label in candidate_pairs:
        opposite = candidate_pairs[opposite_label]
    elif opposite_id in all_points:
        opposite = all_points[opposite_id]
    else:
        opposite = _derive_square_fourth_vertex(start=start, end=end, adjacent=adjacent)
    if opposite is None:
        return
    _add_candidate_point(
        fixed=fixed,
        moving=moving,
        all_points=all_points,
        point_meta=point_meta,
        point_id=opposite_id,
        label=opposite_label,
        scope_id=scope_id,
        pair=opposite,
        candidate_index=candidate_index,
        parameter_name=parameter_name,
    )


def _candidate_or_existing_pair(
    label: str,
    scope_id: str,
    candidate_index: int,
    candidate_pairs: dict[str, list[str]],
    all_points: dict[str, list[str]],
    namer: GeometryPointNamer,
) -> list[str] | None:
    if label in candidate_pairs:
        return candidate_pairs[label]
    candidate_id = axis_parameter_candidate_point_id(label, scope_id, candidate_index)
    if candidate_id in all_points:
        return all_points[candidate_id]
    geometry_id = _square_geometry_point_id(label, scope_id, all_points)
    return all_points.get(geometry_id)


def _candidate_target_label(step: dict[str, Any]) -> str:
    for raw in (
        str(step.get("target") or ""),
        *(str(item.get("handle") or "") for item in step.get("produces") or () if isinstance(item, dict)),
    ):
        label = _label_from_semantic_name(_handle_tail(raw))
        if label:
            return label
    return ""


def _candidate_point_pair_for_label(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    label: str,
) -> tuple[Any, Any] | None:
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        if _label_from_semantic_name(_handle_tail(handle)) != label:
            continue
        pair = _candidate_point_pair_for_handle(handle, snapshot)
        if pair is not None:
            return pair
    return None


def _candidate_curve_point(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
    target_label: str,
) -> tuple[str, tuple[Any, Any] | None]:
    scored: list[tuple[int, str, tuple[Any, Any]]] = []
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if not isinstance(fact, dict) or fact.get("type") != "Point":
            continue
        label = _label_from_semantic_name(_handle_tail(handle))
        if not label or label == target_label:
            continue
        pair = _candidate_point_pair_for_handle(handle, snapshot)
        if pair is None:
            continue
        score = 1 + (2 if "curve" in handle or "parabola" in handle else 0)
        scored.append((score, label, pair))
    if not scored:
        return "", None
    scored.sort(key=lambda item: item[0], reverse=True)
    _, label, pair = scored[0]
    return label, pair


def _candidate_point_pair_for_handle(
    handle: str,
    snapshot: ExplanationSnapshot,
) -> tuple[Any, Any] | None:
    fact = snapshot.fact_index.get(handle)
    pair = _sympy_pair_value((fact or {}).get("value") if isinstance(fact, dict) else None)
    if pair is not None:
        return pair
    source_step_id = str((fact or {}).get("source_step_id") or "") if isinstance(fact, dict) else ""
    tail = _handle_tail(handle)
    scope = _canonical_scope_from_handle(handle)
    candidates: list[tuple[int, tuple[Any, Any]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        item_handle = str(item.get("handle") or "")
        score = 0
        if source_step_id and _fact_step_id(item) == source_step_id:
            score = 9
        elif item_handle.endswith(f":outputs:{tail}") and (not scope or str(item.get("scope_id") or "") == scope):
            score = 8
        elif item_handle.endswith(f":points:{tail}") and (not scope or str(item.get("scope_id") or "") == scope):
            score = 7
        if score <= 0:
            continue
        pair = _sympy_pair_value(item.get("value"))
        if pair is not None:
            candidates.append((score, pair))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _candidate_axis_parameter(
    *pairs: tuple[Any, Any] | None,
) -> Any | None:
    symbols: set[Any] = set()
    for pair in pairs:
        if pair is None:
            continue
        for coord in pair:
            symbols.update(getattr(coord, "free_symbols", set()))
    candidates = sorted(
        (symbol for symbol in symbols if str(symbol).startswith("_axis_param_") or str(symbol) == "t"),
        key=str,
    )
    return candidates[0] if len(candidates) == 1 else None


def _candidate_point_list(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> list[tuple[Any, Any]]:
    step_id = str(step.get("step_id") or "")
    target_tail = _handle_tail(str(step.get("target") or ""))
    scored: list[tuple[int, list[tuple[Any, Any]]]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "PointList":
            continue
        points = _sympy_point_list_value(item.get("value"))
        if not points:
            continue
        score = 0
        if _fact_step_id(item) == step_id:
            score += 10
        if _fact_step_id(item) == step_id:
            score += 5
        if target_tail and str(item.get("handle") or "").endswith(f":outputs:{target_tail}"):
            score += 3
        if score > 0:
            scored.append((score, points))
    if not scored:
        return []
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _sort_candidate_points(
    candidates: list[tuple[Any, Any]],
    target_pair: tuple[Any, Any],
    parameter: Any,
) -> list[tuple[Any, Any]]:
    def sort_key(point: tuple[Any, Any]) -> tuple[float, str]:
        value = _candidate_parameter_value(target_pair, point, parameter)
        try:
            numeric = float(__import__("sympy").N(value)) if value is not None else float("-inf")
        except Exception:
            numeric = float("-inf")
        return (-numeric, str(point))

    return sorted(candidates, key=sort_key)


def _candidate_parameter_value(
    target_pair: tuple[Any, Any],
    candidate: tuple[Any, Any],
    parameter: Any,
) -> Any | None:
    try:
        import sympy as sp
    except Exception:
        return None
    for expr, value in zip(target_pair, candidate, strict=True):
        if parameter not in getattr(expr, "free_symbols", set()):
            continue
        solutions = sp.solve(sp.Eq(expr, value), parameter)
        if solutions:
            return sp.simplify(solutions[0])
    return None


def _square_fact_for_candidate_step(
    snapshot: ExplanationSnapshot,
    scope_id: str,
    target_label: str,
    curve_label: str,
) -> dict[str, Any] | None:
    for fact in (snapshot.problem or {}).get("facts") or ():
        if not isinstance(fact, dict) or fact.get("type") != "square":
            continue
        if scope_id and str(fact.get("scope_id") or "") != scope_id:
            continue
        labels = [_label_from_square_vertex_handle(str(handle), snapshot) for handle in fact.get("vertices", ())]
        if target_label in labels and (not curve_label or curve_label in labels):
            return fact
    return None


def _sympy_pair_value(value: Any) -> tuple[Any, Any] | None:
    if not _is_point_value(value):
        return None
    return sympy_pair(value, axis_parameter_alias="t")


def _sympy_point_list_value(value: Any) -> list[tuple[Any, Any]]:
    if not isinstance(value, list | tuple):
        return []
    return [pair for item in value if (pair := _sympy_pair_value(item)) is not None]


def _canonical_scope_from_handle(handle: str) -> str:
    parts = str(handle).split(":")
    return parts[1] if len(parts) > 2 else ""


def _label_from_square_vertex_handle(handle: str, snapshot: ExplanationSnapshot) -> str:
    for entity in (snapshot.problem or {}).get("entities") or ():
        if isinstance(entity, dict) and str(entity.get("handle") or "") == handle:
            return str(entity.get("name") or _handle_tail(handle))
    return _handle_tail(handle)


def _add_square_projection_point(
    *,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    all_points: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    point_id: str,
    label: str,
    scope_id: str,
    pair: list[str],
    parameter_name: str,
) -> None:
    if point_id in all_points:
        return
    if _pair_depends_on_parameter(pair, parameter_name):
        moving[point_id] = pair
    else:
        fixed[point_id] = pair
    all_points[point_id] = pair
    point_meta.setdefault(
        point_id,
        {
            "label": label,
            "scopeId": scope_id,
            "scopeRoot": _scope_root(scope_id),
            "visualOnly": True,
        },
    )


def _square_geometry_point_id(
    label: str,
    scope_id: str,
    all_points: dict[str, list[str]],
    *,
    prefer_axis: bool = False,
) -> str:
    axis_id = axis_parameter_point_id(label, scope_id)
    if prefer_axis or axis_id in all_points:
        return axis_id
    namer = GeometryPointScopeNamer(problem_point_names=frozenset(), label_roots={})
    for visible_scope in scope_lineage(scope_id):
        candidate = namer.geometry_id(label, visible_scope)
        if candidate in all_points:
            return candidate
        axis_candidate = axis_parameter_point_id(label, visible_scope)
        if axis_candidate in all_points:
            return axis_candidate
    return namer.geometry_id(label, scope_id)


def _derive_square_fourth_vertex(
    *,
    start: list[str],
    end: list[str],
    adjacent: list[str],
) -> list[str] | None:
    if len(start) != 2 or len(end) != 2 or len(adjacent) != 2:
        return None
    try:
        import sympy as sp

        return [
            _page_expr(
                sp.simplify(
                    sp.sympify(str(end[index]))
                    + sp.sympify(str(adjacent[index]))
                    - sp.sympify(str(start[index]))
                )
            )
            for index in (0, 1)
        ]
    except Exception:
        return None


def _defined_point_pair_for_curve_entity(
    entity: JsonObject,
    curve: JsonObject,
    roots: list[Any],
) -> list[str] | None:
    definition = str(entity.get("definition") or "")
    if definition == "x_axis_intercept":
        root = _select_x_axis_root_for_entity(entity, roots)
        if root is None:
            return None
        return [_page_expr(root), "0"]
    if definition == "axis_x_intercept":
        axis_x = _axis_x_for_curve(curve)
        if axis_x is None:
            return None
        return [_page_expr(axis_x), "0"]
    return None


def _axis_x_for_curve(curve: JsonObject) -> Any | None:
    import sympy as sp

    try:
        a = sp.sympify(str(curve.get("a") or "0"))
        b = sp.sympify(str(curve.get("b") or "0"))
    except Exception:
        return None
    if sp.simplify(a) == 0:
        return None
    return sp.simplify(-b / (2 * a))


def _numeric_x_axis_roots_for_curve(curve: JsonObject) -> list[Any]:
    import sympy as sp

    try:
        a = sp.sympify(str(curve.get("a") or "0"))
        b = sp.sympify(str(curve.get("b") or "0"))
        c = sp.sympify(str(curve.get("c") or "0"))
    except Exception:
        return []
    if sp.simplify(a) == 0:
        return []
    x = sp.Symbol("x")
    roots = [sp.simplify(root) for root in sp.solve(sp.Eq(a * x * x + b * x + c, 0), x)]
    real_roots = [root for root in roots if root.is_real is not False]

    def representative_value(item: Any) -> tuple[int, float, str]:
        try:
            sample = item.subs({symbol: 1 for symbol in item.free_symbols})
            return (0, float(sp.N(sample)), str(item))
        except Exception:
            return (1, 0.0, str(item))

    return sorted(real_roots, key=representative_value)


def _select_x_axis_root_for_entity(entity: JsonObject, roots: list[Any]) -> Any | None:
    if not roots:
        return None
    side = str(entity.get("side") or "").strip().lower()
    if side == "left":
        return roots[0]
    if side == "right":
        return roots[-1]
    if len(roots) == 1:
        return roots[0]
    return None


class GeometryPointNamer:
    """Assign stable geometry point ids from canonical labels and visible scope.

    Runtime fact handles are an implementation detail.  The visual id is derived
    from the mathematical point label plus its question scope.  If a problem-level
    point receives different values in different top-level questions, the first
    part uses a scoped suffix such as ``B1`` while the later part can keep ``B``.
    """

    def __init__(self, *, snapshot: ExplanationSnapshot, lesson: LessonIR) -> None:
        self.snapshot = snapshot
        self.lesson = lesson
        self.steps_by_id = {
            str(step.get("step_id")): step
            for step in snapshot.effective_steps
            if isinstance(step, dict) and step.get("step_id")
        }
        self.facts_by_handle = {
            str(fact.get("handle")): fact
            for fact in (snapshot.problem or {}).get("facts") or ()
            if isinstance(fact, dict) and fact.get("handle")
        }
        self.entities_by_handle = {
            str(entity.get("handle")): entity
            for entity in (snapshot.problem or {}).get("entities") or ()
            if isinstance(entity, dict) and entity.get("handle")
        }
        self.problem_point_names = {
            str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            for entity in (snapshot.problem or {}).get("entities") or ()
            if isinstance(entity, dict)
            and entity.get("entity_type") == "point"
            and str(entity.get("scope_id") or "") == "problem"
        }
        self.label_roots = self._collect_label_roots()
        self.scope_namer = GeometryPointScopeNamer(
            problem_point_names=frozenset(self.problem_point_names),
            label_roots={key: frozenset(value) for key, value in self.label_roots.items()},
        )

    def point_id_for_fact(self, item: dict[str, Any]) -> str:
        label = self._raw_label_for_fact(item)
        if not label:
            return ""
        scope_id = self._visual_scope_for_fact(item)
        return self.scope_namer.geometry_id(label, scope_id)

    def point_meta_for_fact(self, item: dict[str, Any]) -> JsonObject:
        label = self._raw_label_for_fact(item)
        scope_id = self._visual_scope_for_fact(item)
        meta = self.scope_namer.point_meta(label, scope_id)
        display_label = _student_point_label(label)
        if display_label:
            meta["label"] = display_label
        return meta

    def _collect_label_roots(self) -> dict[str, set[str]]:
        roots: dict[str, set[str]] = {}
        for item in self.snapshot.fact_index.values():
            if not isinstance(item, dict) or item.get("type") != "Point":
                continue
            if not _is_point_value(item.get("value")):
                continue
            label = self._raw_label_for_fact(item)
            if not label:
                continue
            roots.setdefault(label, set()).add(_scope_root(self._visual_scope_for_fact(item)))
        return roots

    def _raw_label_for_fact(self, item: dict[str, Any]) -> str:
        name = str(item.get("name") or "")
        if name == "equal_length_auxiliary_point":
            auxiliary = self._auxiliary_label_from_equal_length_witness(item)
            if auxiliary:
                return auxiliary
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*(?:_prime)?", name):
            return name
        source_step_id = self._source_step_id_for_fact(item)
        label = _label_from_effective_step(source_step_id, self.snapshot)
        if label:
            return label
        if name:
            label = _label_from_semantic_name(name)
            if label:
                return label
        return ""

    def _visual_scope_for_fact(self, item: dict[str, Any]) -> str:
        stable_problem_scope = self._stable_problem_scope_for_fact(item)
        if stable_problem_scope:
            return stable_problem_scope
        source_step_id = self._source_step_id_for_fact(item)
        step = self.steps_by_id.get(source_step_id)
        if isinstance(step, dict) and step.get("scope_id"):
            return str(step["scope_id"])
        return str(item.get("scope_id") or "")

    def _stable_problem_scope_for_fact(self, item: dict[str, Any]) -> str:
        label = self._scope_guard_label_for_fact(item)
        if label not in self.problem_point_names:
            return ""
        roots = set(getattr(self, "label_roots", {}).get(label, frozenset()))
        if roots and not ({"ii", "iii"} & roots):
            return "problem"
        if not roots and str(item.get("scope_id") or "") == "problem":
            return "problem"
        return ""

    def _scope_guard_label_for_fact(self, item: dict[str, Any]) -> str:
        name = str(item.get("name") or "")
        label = _label_from_semantic_name(name)
        if label:
            return label
        source_step_id = self._source_step_id_for_fact(item)
        return _label_from_effective_step(source_step_id, self.snapshot)

    def _source_step_id_for_fact(self, item: dict[str, Any]) -> str:
        explicit = str(item.get("source_step_id") or "")
        if explicit:
            return explicit
        scope_id = str(item.get("scope_id") or "")
        if scope_id in self.steps_by_id:
            return scope_id
        source_method = str(item.get("source") or "")
        if source_method:
            method_matches = [
                step_id
                for step_id, step in self.steps_by_id.items()
                if any(
                    source.capability_id == source_method
                    and source.source_step_id == step_id
                    for source in iter_teaching_sources(self.snapshot.root_scope)
                )
            ]
            matches = [
                step_id
                for step_id in method_matches
                if _scope_root(str(self.steps_by_id[step_id].get("scope_id") or "")) == _scope_root(scope_id)
            ]
            if len(matches) == 1:
                return matches[0]
            if len(method_matches) == 1:
                return method_matches[0]
        return ""

    def _auxiliary_label_from_equal_length_witness(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        if not source_step_id:
            return ""
        matches: list[str] = []
        for witness in self.snapshot.macro_evidence:
            if str(witness.get("step_id") or "") != source_step_id:
                continue
            for construction in witness.get("constructions") or ():
                if not isinstance(construction, Mapping):
                    continue
                if str(construction.get("kind") or "") != "equal_length_point_on_ray":
                    continue
                label = str(construction.get("label") or "")
                if label:
                    matches.append(label)
        unique = sorted(set(matches))
        if len(unique) > 1:
            raise ValueError(
                "visual_equal_length_auxiliary_identity_ambiguous: "
                f"step={source_step_id}, labels={unique}"
            )
        return unique[0] if unique else ""

def _student_point_label(label: str) -> str:
    return str(label).replace("_prime", "′")


def _same_point_pair_value(left: tuple[Any, Any], right: tuple[Any, Any]) -> bool:
    try:
        left_pair = (sp.sympify(str(left[0])), sp.sympify(str(left[1])))
        right_pair = (sp.sympify(str(right[0])), sp.sympify(str(right[1])))
        return (
            sp.simplify(left_pair[0] - right_pair[0]) == 0
            and sp.simplify(left_pair[1] - right_pair[1]) == 0
        )
    except Exception:
        return False


def _label_from_effective_step(step_id: str, snapshot: ExplanationSnapshot) -> str:
    if not step_id:
        return ""
    for step in snapshot.effective_steps:
        if not isinstance(step, dict) or step.get("step_id") != step_id:
            continue
        target = str(step.get("target") or "")
        labels = _point_labels_from_handle_text(target)
        if len(labels) == 1:
            return next(iter(labels))
        for produced in step.get("produces") or ():
            if not isinstance(produced, dict):
                continue
            labels = _point_labels_from_handle_text(str(produced.get("handle") or ""))
            if len(labels) == 1:
                return next(iter(labels))
            description_labels = _capital_point_labels(str(produced.get("description") or ""))
            if len(description_labels) == 1:
                return next(iter(description_labels))
    return ""


def _label_from_semantic_name(name: str) -> str:
    labels = _point_labels_from_handle_text(name)
    return next(iter(labels)) if len(labels) == 1 else ""


def _curves_from_snapshot(snapshot: ExplanationSnapshot) -> list[JsonObject]:
    steps_by_id = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    source_order = {step_id: index for index, step_id in enumerate(steps_by_id)}
    sources = {s.source_step_id: s for s in iter_teaching_sources(snapshot.root_scope)}
    def object_ref(item):
        entities = [entity for entity in (snapshot.problem or {}).get("entities", ())
                    if entity.get("entity_type") == "function"]
        named = {str(e["handle"]) for e in entities if e.get("name") == item.get("name")}
        if len(named) == 1:
            return next(iter(named))
        step = steps_by_id.get(str(item.get("source_step_id")), {})
        inputs = {str(e["handle"]) for e in entities if e.get("handle") in step.get("reads", ())}
        # A renamed closed result can refine the curve read by its producer.
        # Never merge unrelated curves merely because their equations coincide.
        source = sources.get(str(item.get("source_step_id")))
        if len(inputs) == 1 and source is not None:
            substitutions = {sp.Symbol(k): sp.sympify(v)
                             for k, v in verified_parameter_values_from_source(source).items()}
            for items in source.inputs.values():
                for value in items:
                    ref = value.get("ref", {})
                    if value.get("runtime_type") == "ParameterValue" and ref.get("kind") == "source":
                        symbol = str(ref.get("ref") or "")
                        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", symbol):
                            substitutions[sp.Symbol(symbol)] = sp.sympify(value["value"])
            curves = [value for items in source.inputs.values() for value in items
                      if value.get("runtime_type") == "Parabola"]
            if len(curves) == 1 and sp.simplify(
                sp.sympify(curves[0]["value"]).subs(substitutions) - sp.sympify(item["value"])
            ) == 0:
                return next(iter(inputs))
        return (f"step-result:{item['source_step_id']}:{item.get('name', '')}"
                if item.get("source_step_id") else str(item.get("handle") or ""))
    curves_by_key = {}
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Parabola":
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        coeffs = _parabola_coefficients(value)
        if coeffs is None:
            continue
        scope_id = _curve_scope_for_fact(item, steps_by_id)
        key = (scope_id, object_ref(item), coeffs)
        rank = _curve_fact_rank(item)
        if key in curves_by_key and curves_by_key[key][2] >= rank:
            continue
        curves_by_key[key] = (item, coeffs, rank)

    curves_by_id: dict[str, JsonObject] = {}
    for item, coeffs, _rank in curves_by_key.values():
        scope_id = _curve_scope_for_fact(item, steps_by_id)
        curve_id = _curve_id_for_fact(item, scope_id, curves_by_id)
        curves_by_id[curve_id] = {
            "id": curve_id,
            "type": "parabola",
            "scopeId": scope_id,
            "scopeRoot": _scope_root(scope_id),
            "sourceHandle": str(item.get("handle") or ""),
            "objectRef": object_ref(item),
            "stateRevision": source_order.get(str(item.get("source_step_id")), -1),
            "a": coeffs[0],
            "b": coeffs[1],
            "c": coeffs[2],
        }
    return list(curves_by_id.values())


def _curve_scope_for_fact(item: dict[str, Any], steps_by_id: dict[str, dict[str, Any]]) -> str:
    source_step_id = str(item.get("source_step_id") or "")
    if source_step_id in steps_by_id:
        return str(steps_by_id[source_step_id].get("scope_id") or item.get("scope_id") or "")
    scope_id = str(item.get("scope_id") or "")
    if scope_id in steps_by_id:
        return str(steps_by_id[scope_id].get("scope_id") or scope_id)
    handle = str(item.get("handle") or "")
    match = re.match(r"runtime:([^:]+):", handle)
    if match and match.group(1) in steps_by_id:
        return str(steps_by_id[match.group(1)].get("scope_id") or scope_id)
    return scope_id


def _curve_fact_rank(item: dict[str, Any]) -> int:
    handle = str(item.get("handle") or "")
    if ":outputs:" in handle:
        return 3
    if handle.startswith("fact:") or handle.startswith("answer:"):
        return 2
    if ":temp:" in handle:
        return 1
    return 0


def _curve_id_for_fact(item: dict[str, Any], scope_id: str, existing: dict[str, JsonObject]) -> str:
    scope_root = _scope_root(scope_id or "problem")
    raw_name = str(item.get("name") or _handle_tail(str(item.get("handle") or "")) or "parabola")
    semantic = re.sub(r"[^A-Za-z0-9_]+", "_", raw_name).strip("_") or "parabola"
    if "parabola" not in semantic.lower():
        semantic = f"{semantic}_parabola"
    base = f"curve_{scope_root}_{semantic}"
    candidate = base
    index = 2
    while candidate in existing:
        index += 1
        candidate = f"{base}_{index}"
    return candidate


def _parabola_coefficients(expression: str) -> tuple[str, str, str] | None:
    try:
        import sympy as sp

        x = sp.Symbol("x")
        expr = sp.sympify(expression)
        poly = sp.Poly(expr, x)
        return tuple(_page_expr(poly.coeff_monomial(x ** power)) for power in (2, 1, 0))  # type: ignore[return-value]
    except Exception:
        return None


def _domain_from_geometry_points(
    fixed_points: dict[str, list[str]],
    moving_points: dict[str, list[str]],
    curves: list[JsonObject],
    parameter_name: str,
    default_t: float,
) -> JsonObject:
    samples: list[tuple[float, float]] = []
    env = {parameter_name: default_t}
    for pair in [*fixed_points.values(), *moving_points.values()]:
        point = _evaluate_page_pair(pair, env)
        if point is not None:
            samples.append(point)
    samples.extend(_curve_sample_points(curves, env))
    if not samples:
        return {"minX": -5.0, "maxX": 5.0, "minY": -5.0, "maxY": 5.0}
    xs = [point[0] for point in samples]
    ys = [point[1] for point in samples]
    x_span = max(max(xs) - min(xs), 1.0)
    y_span = max(max(ys) - min(ys), 1.0)
    margin = max(0.8, min(1.8, max(x_span, y_span) * 0.18))
    return {
        "minX": round(min(xs) - margin, 3),
        "maxX": round(max(xs) + margin, 3),
        "minY": round(min(ys) - margin, 3),
        "maxY": round(max(ys) + margin, 3),
    }


def _curve_sample_points(curves: list[JsonObject], env: dict[str, float]) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    for curve in curves:
        if not isinstance(curve, dict) or curve.get("type") != "parabola":
            continue
        coeffs = _evaluate_curve_coefficients(curve, env)
        if coeffs is None:
            continue
        a, b, c = coeffs
        if abs(a) < 1e-9:
            continue
        vertex_x = -b / (2 * a)
        samples.append((vertex_x, a * vertex_x * vertex_x + b * vertex_x + c))
        samples.append((0.0, c))
        discriminant = b * b - 4 * a * c
        if discriminant >= -1e-9:
            root_delta = max(discriminant, 0.0) ** 0.5
            samples.append(((-b - root_delta) / (2 * a), 0.0))
            samples.append(((-b + root_delta) / (2 * a), 0.0))
    return samples


def _evaluate_curve_coefficients(
    curve: JsonObject,
    env: dict[str, float],
) -> tuple[float, float, float] | None:
    try:
        import sympy as sp

        substitutions = {sp.Symbol(key): value for key, value in env.items()}
        values = []
        for key in ("a", "b", "c"):
            value = sp.sympify(str(curve.get(key) or "0")).subs(substitutions)
            values.append(float(sp.N(value)))
        return (values[0], values[1], values[2])
    except Exception:
        return None


def _parameter_scope_id(snapshot: ExplanationSnapshot) -> str:
    for item in snapshot.fact_index.values():
        if isinstance(item, dict) and item.get("type") == "ParameterValue":
            scope_id = str(item.get("scope_id") or "")
            if scope_id:
                return scope_id
    return ""


def _page_point_pair(value: Any) -> list[str]:
    return [_page_expr(value[0]), _page_expr(value[1])]


def _page_expr(value: Any) -> str:
    text = str(value).strip()
    try:
        import sympy as sp

        text = str(sp.simplify(sp.sympify(text)))
    except Exception:
        pass
    text = text.replace("Abs(", "abs(")
    text = text.replace(" ", "")
    return _expand_integer_powers(text)


def _expression_env_from_geometry(
    *,
    fixed_points: dict[str, list[str]],
    moving_points: dict[str, list[str]],
    curves: list[JsonObject],
    parameter_name: str,
) -> list[JsonObject]:
    names: set[str] = set()
    for pair in (*fixed_points.values(), *moving_points.values()):
        for expr in pair:
            names.update(_free_identifier_names(str(expr)))
    for curve in curves:
        for key in ("a", "b", "c"):
            names.update(_free_identifier_names(str(curve.get(key) or "")))
    names.discard(parameter_name)
    names.discard("t")
    names.discard("S3")
    names.discard("sqrt")
    names.discard("abs")
    return [{"name": name, "expr": str(name)} for name in sorted(names)]


def _free_identifier_names(expr: str) -> set[str]:
    return {
        name
        for name in re.findall(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)", expr)
        if not name.startswith("_axis_param_")
    }


def _expand_integer_powers(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        base = match.group("atom") or match.group("group")
        exponent = int(match.group("exponent"))
        if exponent < 0:
            return match.group(0)
        if exponent == 0:
            return "1"
        if exponent == 1:
            return base
        factor = base if match.group("atom") else f"({base})"
        return "(" + "*".join(factor for _ in range(exponent)) + ")"

    pattern = re.compile(
        r"(?:(?P<atom>\b[A-Za-z_][A-Za-z0-9_]*\b)|\((?P<group>[^()]+)\))\*\*(?P<exponent>\d+)"
    )
    previous = None
    while previous != text:
        previous = text
        text = pattern.sub(repl, text)
    return text


def _evaluate_page_pair(pair: list[str], env: dict[str, float]) -> tuple[float, float] | None:
    try:
        import sympy as sp

        locals_ = {"abs": sp.Abs, "sqrt": sp.sqrt}
        substitutions = {sp.Symbol(key): value for key, value in env.items()}
        x = sp.sympify(str(pair[0]).replace("^", "**"), locals=locals_).subs(substitutions)
        y = sp.sympify(str(pair[1]).replace("^", "**"), locals=locals_).subs(substitutions)
        return (float(sp.N(x)), float(sp.N(y)))
    except Exception:
        return None


def _pair_depends_on_parameter(pair: list[str], parameter_name: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(parameter_name)}(?![A-Za-z0-9_])")
    return any(pattern.search(str(part)) for part in pair)


def _handle_tail(handle: str) -> str:
    return handle.rsplit(":", 1)[-1].split(".", 1)[-1]


def _visual_step_resolution(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
    bindings: VisualRoleBindings,
) -> VisualStepResolution:
    # A parameter-producing step changes the mathematical state *at this
    # step*.  Use that verified value while resolving its retained frame and
    # every later frame, but never look ahead to a Goal/final answer.
    render_state = state.clone()
    render_state.parameters.update(
        _parameter_values_produced_by_lesson_step(lesson_step, snapshot)
    )
    coordinate_texts = _verified_coordinate_texts_for_lesson_step(
        lesson_step,
        snapshot,
    )
    visible_coordinate_texts_by_ref = _visible_coordinate_texts_by_ref(
        coordinate_texts,
        geometry_spec,
        parameter_values=render_state.parameters,
    )
    frame_units = _visual_frame_unit_groups(lesson_step)
    frames: list[VisualFrame] = []
    published: tuple[VisualObject, ...] = ()
    visibility_reasons: dict[str, str] = {}
    mode = "scene"

    for frame_index, unit_keys in enumerate(frame_units, start=1):
        frame_step = _lesson_step_for_visual_units(lesson_step, unit_keys)
        frame_bindings = replace(
            bindings,
            coordinate_texts_by_ref={
                ref: text
                for ref, text in visible_coordinate_texts_by_ref.items()
                if ref in set(bindings.point_handles.values())
            },
        )
        interactions = ParametricExpressionResolver(
            geometry_spec=geometry_spec,
            default_t=_branch_default_parameter_value(
                render_state,
                geometry_spec=geometry_spec,
                snapshot=snapshot,
            ),
        ).interactions_for_step(
            frame_step,
            frame_bindings,
            interaction_specs=_visual_interaction_specs_for_lesson_step(
                frame_step
            ),
        )
        raw_items = _tagged_scene_items_for_lesson_step(
            frame_step,
            snapshot=snapshot,
            bindings=frame_bindings,
            coordinate_texts=coordinate_texts,
        )
        raw_items = _restrict_coordinate_labels_to_visible_facts(
            raw_items,
            visible_coordinate_texts_by_ref,
        )
        raw_items, interactions, auxiliary_ref_map = (
            _materialize_frame_visual_auxiliaries(
                raw_items,
                interactions,
                lesson_step=frame_step,
                geometry_spec=geometry_spec,
            )
        )
        equivalent_ref_map = _equivalent_labeled_geometry_ref_map(
            raw_items,
            geometry_spec,
        )
        if equivalent_ref_map:
            raw_items = _replace_visual_geometry_refs(
                raw_items,
                equivalent_ref_map,
            )
            interactions = _replace_visual_geometry_refs(
                interactions,
                equivalent_ref_map,
            )
            auxiliary_ref_map = {
                **auxiliary_ref_map,
                **equivalent_ref_map,
            }
        raw_items = _dedupe_scene_items(
            [
                *raw_items,
                *_interaction_constraint_carrier_items(interactions),
            ]
        )
        raw_items = _close_standalone_angle_dependencies(raw_items)
        raw_items = _studentize_scene_point_labels(raw_items, geometry_spec)
        raw_items = _hide_redundant_point_names(raw_items)
        current = visual_objects_from_scene_items(
            raw_items,
            owner_scope_ref=lesson_step.scope_id,
            source_step_ids=tuple(lesson_step.source_step_ids),
        )
        suppressed_point_refs = _suppressed_current_point_refs(
            frame_step,
            snapshot=snapshot,
            geometry_spec=geometry_spec,
        )
        if suppressed_point_refs:
            current = tuple(
                item
                for item in current
                if not set(item.geometry_refs).intersection(suppressed_point_refs)
            )
        # Resolve the new frame as an increment over the immediately preceding
        # complete frame in this exact branch.  At Goal entry that frame is
        # the direct parent Scope's end state; inside a Goal it is the previous
        # Goal step.  The serialized Frame remains complete and independently
        # renderable -- the browser never performs carry-forward itself.
        inherited_context = tuple(
            context_copy(item)
            for item in render_state.last_frame
        )
        inherited_context = _prune_superseded_candidate_context(
            inherited_context,
            current=current,
            geometry_spec=geometry_spec,
        )
        inherited_reason = _branch_frame_inheritance_reason(
            frame_step,
            render_state,
        )
        for item in inherited_context:
            visibility_reasons[item.visual_object_id] = inherited_reason
        supplemental_context = (
            _visual_context_for_step(
                frame_step,
                state=render_state,
                current=current,
                snapshot=snapshot,
                geometry_spec=geometry_spec,
            )
            if current
            else ()
        )
        context = _merge_frame_objects(inherited_context, supplemental_context)
        context = _prune_superseded_candidate_context(
            context,
            current=current,
            geometry_spec=geometry_spec,
        )
        context = _refresh_context_coordinate_labels(
            context,
            visible_coordinate_texts_by_ref,
        )
        calculation_continuation = _is_path_result_calculation_continuation(
            lesson_step,
            context,
        )
        scene_current = (
            _path_result_calculation_updates(current)
            if calculation_continuation
            else current
        )
        objects = _merge_frame_objects(context, scene_current)
        objects = _coalesce_visible_point_objects(objects)
        if not objects:
            if render_state.last_frame:
                mode = "retain"
                objects = tuple(context_copy(item) for item in render_state.last_frame)
                for item in objects:
                    visibility_reasons[item.visual_object_id] = (
                        "retain_previous_frame_for_non_geometric_step"
                    )
            else:
                mode = "none"
                continue
        for item in context:
            visibility_reasons.setdefault(
                item.visual_object_id,
                _context_visibility_reason(
                    frame_step,
                    item,
                ),
            )
        for item in scene_current:
            visibility_reasons[item.visual_object_id] = "current_visual_spec_result_or_requirement"
        persistent_current = visual_objects_from_scene_items(
            [
                item
                for item in raw_items
                if _scene_item_persists(item, raw_items)
            ],
            owner_scope_ref=lesson_step.scope_id,
            source_step_ids=tuple(lesson_step.source_step_ids),
        )
        if suppressed_point_refs:
            persistent_current = tuple(
                item
                for item in persistent_current
                if not set(item.geometry_refs).intersection(suppressed_point_refs)
            )
        if calculation_continuation:
            persistent_current = _path_result_calculation_updates(
                persistent_current
            )
        published = _merge_frame_objects(context, persistent_current)
        published = _coalesce_visible_point_objects(published)
        math_resolver = FrameMathStateResolver(geometry_spec, snapshot.problem or {}, lesson_step.scope_id)
        objects, object_replacements = math_resolver.project(objects)
        published, _ = math_resolver.project(published)
        local_parameters = _local_parameters_for_frame(
            lesson_step=frame_step,
            state=render_state,
            geometry_spec=geometry_spec,
            objects=objects,
            snapshot=snapshot,
        )
        visible_interactions = _interactions_for_visible_objects(
            interactions,
            objects,
        )
        local_parameters = _merge_local_parameter_contracts(
            local_parameters,
            visible_interactions,
            source_step_ids=tuple(lesson_step.source_step_ids),
        )
        local_parameters = _inherit_local_parameter_defaults(
            local_parameters,
            render_state.last_local_parameters,
            active_interactions=visible_interactions,
            objects=objects,
            geometry_spec=geometry_spec,
            parameter_values=render_state.parameters,
        )
        constraints = {c["parameter"]: c for c in render_state.mathematical_constraints}
        for interaction in visible_interactions:
            if interaction.get("attainment_constraint"):
                constraint = interaction["attainment_constraint"]
                constraints[constraint["parameter"]] = constraint
        render_state.mathematical_constraints = tuple(constraints.values())
        local_parameters, constraint_audit = resolve_attainment_constraints(
            local_parameters, render_state.mathematical_constraints,
            active_parameters={str(i.get("parameter")) for i in visible_interactions},
        )
        timeline = AnimationTimelineBuilder().timeline_for_step(
            frame_step,
            frame_bindings,
            interactions=interactions,
        )
        timeline = _replace_visual_geometry_refs(timeline, auxiliary_ref_map)
        timeline = _replace_visual_geometry_refs(timeline, object_replacements)
        timeline = _studentize_timeline(timeline, geometry_spec)
        frame = VisualFrame(
            frame_id=f"frame:{lesson_step.id}:{frame_index}",
            caption=_visual_frame_caption(frame_step, unit_keys, frame_index),
            teaching_unit_keys=tuple(unit_keys),
            viewport=SemanticViewportResolver().resolve(
                objects=objects,
                geometry_spec=geometry_spec,
                local_parameters=local_parameters,
                parameter_values=render_state.parameters,
            ),
            objects=objects,
            local_parameters=local_parameters,
            timeline=timeline if timeline.get("mode") != "none" else None,
            metadata={
                "annotations": _annotations_for_lesson_step(frame_step),
                "mathematical_state": {
                    "schema_version": "visual-math-state/v1",
                    "scope_id": lesson_step.scope_id,
                    "source_step_ids": list(lesson_step.source_step_ids),
                    "verified_parameters": dict(render_state.parameters),
                    "object_replacements": object_replacements,
                    "constraints": constraint_audit,
                },
            },
        )
        frames.append(frame)
        # The serialized Frame is complete, but only carry-forward objects
        # become the next branch state.  VisualSpec ``step_only`` helpers are
        # intentionally visible for this teaching stage and then disappear.

    step = VisualStep(
        visual_step_id=f"visual:{lesson_step.id}",
        lesson_step_id=lesson_step.id,
        visual_mode=mode,
        frames=tuple(frames),
        metadata={"step_extra": {}},
    )
    return VisualStepResolution(
        step=step,
        published_objects=tuple(_dedupe_visual_objects(list(published))),
        visibility_reasons=visibility_reasons,
        mathematical_constraints=render_state.mathematical_constraints,
    )


def _prune_superseded_candidate_context(
    inherited: tuple[VisualObject, ...],
    *,
    current: tuple[VisualObject, ...],
    geometry_spec: JsonObject,
) -> tuple[VisualObject, ...]:
    """Replace an upstream candidate set with the selected branch diagram."""

    point_meta = geometry_spec.get("pointMeta") or {}
    selected_groups: set[tuple[str, int]] = set()
    selected_source_steps: set[str] = set()
    for item in current:
        if item.role.startswith("candidate:selected_result:"):
            selected_source_steps.add(item.role.split(":", 2)[-1])
        if item.role == "candidate:selected" and item.geometry_refs:
            meta = point_meta.get(item.geometry_refs[0])
            if (
                isinstance(meta, dict)
                and meta.get("definition") == "public_candidate"
            ):
                source_step_id = str(meta.get("sourceStepId") or "")
                candidate_group = int(meta.get("candidateGroup") or 1)
                if source_step_id:
                    selected_groups.add((source_step_id, candidate_group))
                    selected_source_steps.add(source_step_id)
    if not selected_groups and not selected_source_steps:
        return inherited

    superseded_refs = {
        str(point_ref)
        for point_ref, raw_meta in point_meta.items()
        if isinstance(raw_meta, dict)
        and (
            (
                raw_meta.get("definition") == "public_candidate"
                and (
                    str(raw_meta.get("sourceStepId") or ""),
                    int(raw_meta.get("candidateGroup") or 1),
                )
                in selected_groups
            )
            or (
                raw_meta.get("definition")
                == "public_construction_auxiliary"
                and str(raw_meta.get("sourceStepId") or "")
                in selected_source_steps
            )
        )
    }

    def is_superseded(item: VisualObject) -> bool:
        if set(item.geometry_refs).intersection(superseded_refs):
            return True
        return any(
            item.role.startswith(f"candidate_construction:{source_step_id}:")
            for source_step_id in selected_source_steps
        )

    return tuple(
        item
        for item in inherited
        if not is_superseded(item)
    )


def _refresh_context_coordinate_labels(
    objects: tuple[VisualObject, ...],
    visible_coordinate_texts_by_ref: Mapping[str, str],
) -> tuple[VisualObject, ...]:
    """Re-evaluate inherited labels when a verified parameter closes."""

    result: list[VisualObject] = []
    for item in objects:
        if item.component != "CoordinateLabel" or len(item.geometry_refs) != 1:
            result.append(item)
            continue
        text = visible_coordinate_texts_by_ref.get(item.geometry_refs[0])
        if not text:
            result.append(item)
            continue
        payload = copy.deepcopy(item.component_payload)
        payload["text"] = text
        result.append(
            replace(
                item,
                component_payload=payload,
                display_label=text,
            )
        )
    return tuple(result)


def _materialize_frame_visual_auxiliaries(
    raw_items: list[JsonObject],
    interactions: tuple[JsonObject, ...],
    *,
    lesson_step: LessonStep,
    geometry_spec: JsonObject,
) -> tuple[list[JsonObject], tuple[JsonObject, ...], dict[str, str]]:
    """Give slider-generated points exact branch-scoped geometry identity.

    Legacy marker payloads use the student label (for example ``M``) as a
    temporary role value.  It is never allowed to survive as geometry
    identity in v2.  The parameter interaction supplies the actual formula;
    this function registers that formula and rewrites only geometry-reference
    positions to the scoped id.
    """

    fixed = geometry_spec.setdefault("fixedPoints", {})
    moving = geometry_spec.setdefault("movingPoints", {})
    point_meta = geometry_spec.setdefault("pointMeta", {})
    known = set(fixed) | set(moving)
    ref_map: dict[str, str] = {}

    for item in raw_items:
        if not isinstance(item, dict) or item.get("component") != "Point":
            continue
        raw_ref = str(item.get("at") or "")
        metadata = item.get("metadata")
        if (
            not raw_ref
            or raw_ref in known
            or not isinstance(metadata, dict)
        ):
            continue
        definition_pair = metadata.get("definition_pair")
        label = str(
            metadata.get("student_label")
            or item.get("labelText")
            or ""
        ).strip()
        if (
            not isinstance(definition_pair, list)
            or len(definition_pair) != 2
            or not label
        ):
            continue
        expression_pair = [
            str(definition_pair[0]),
            str(definition_pair[1]),
        ]
        scoped_ref = scoped_point_id(label, lesson_step.scope_id)
        existing = moving.get(scoped_ref) or fixed.get(scoped_ref)
        if existing is not None and list(existing) != expression_pair:
            raise ValueError(
                "visual_auxiliary_geometry_identity_conflict: "
                f"{scoped_ref}: {existing} != {expression_pair}"
            )
        parameter_name = str(geometry_spec.get("movingParam") or "")
        if parameter_name and _pair_depends_on_parameter(
            expression_pair,
            parameter_name,
        ):
            moving[scoped_ref] = expression_pair
            fixed.pop(scoped_ref, None)
        else:
            fixed[scoped_ref] = expression_pair
            moving.pop(scoped_ref, None)
        point_meta[scoped_ref] = {
            "label": label,
            "scopeId": lesson_step.scope_id,
            "scopeRoot": _scope_root(lesson_step.scope_id),
            "definition": "visual_auxiliary_construction_point",
            "sourceStepIds": list(lesson_step.source_step_ids),
        }
        ref_map[raw_ref] = scoped_ref
        known.add(scoped_ref)

    for interaction in interactions:
        parameterized = interaction.get("parameterized_points")
        if not isinstance(parameterized, dict):
            continue
        for raw_ref, payload in parameterized.items():
            raw_ref = str(raw_ref or "")
            if not raw_ref or raw_ref in known or not isinstance(payload, dict):
                continue
            expression = payload.get("expression")
            if not isinstance(expression, list) or len(expression) != 2:
                continue
            label = _student_point_label(raw_ref)
            scoped_ref = scoped_point_id(label, lesson_step.scope_id)
            existing = moving.get(scoped_ref) or fixed.get(scoped_ref)
            expression_pair = [str(expression[0]), str(expression[1])]
            if existing is not None and list(existing) != expression_pair:
                meta = point_meta.get(scoped_ref)
                source_ids = {
                    str(item)
                    for item in (
                        meta.get("sourceStepIds", ())
                        if isinstance(meta, dict)
                        else ()
                    )
                }
                same_public_object = (
                    isinstance(meta, dict)
                    and str(meta.get("label") or "") == label
                    and bool(
                        source_ids.intersection(lesson_step.source_step_ids)
                    )
                )
                if not same_public_object:
                    raise ValueError(
                        "visual_geometry_identity_conflict: "
                        f"{scoped_ref}: {existing} != {expression_pair}"
                    )
                # One public point may have a symbolic, Frame-local state and
                # a later verified exact/attainment state.  Preserve the
                # registry definition and let this interaction override the
                # same semantic geometry identity only in the current Frame.
                ref_map[raw_ref] = scoped_ref
                continue
            moving[scoped_ref] = expression_pair
            point_meta[scoped_ref] = {
                "label": label,
                "scopeId": lesson_step.scope_id,
                "scopeRoot": _scope_root(lesson_step.scope_id),
                "definition": "visual_auxiliary_parameterized_point",
                "sourceStepIds": list(lesson_step.source_step_ids),
            }
            ref_map[raw_ref] = scoped_ref
            known.add(scoped_ref)
    if not ref_map:
        return raw_items, interactions, {}
    return (
        _replace_visual_geometry_refs(raw_items, ref_map),
        _replace_visual_geometry_refs(interactions, ref_map),
        ref_map,
    )


def _equivalent_labeled_geometry_ref_map(
    items: list[JsonObject],
    geometry_spec: JsonObject,
) -> dict[str, str]:
    """Coalesce visible aliases of one labeled mathematical point.

    Curve-derived landmarks and runtime points may intentionally have
    different registry ids.  When the public label and exact coordinate pair
    agree in one frame, rendering both identities only creates duplicate
    points and labels.  Blank-label visual features and differently labeled
    coincident points remain distinct.
    """

    known_points = {
        **(geometry_spec.get("fixedPoints") or {}),
        **(geometry_spec.get("movingPoints") or {}),
    }
    point_meta = geometry_spec.get("pointMeta") or {}
    visible_refs = {
        ref
        for item in items
        if isinstance(item, Mapping)
        for ref in geometry_refs_from_scene_item(item)
        if ref in known_points
    }
    groups: dict[str, list[str]] = {}
    for point_ref in visible_refs:
        meta = point_meta.get(point_ref)
        label = str((meta or {}).get("label") or "").strip()
        if label:
            groups.setdefault(label, []).append(point_ref)

    definition_priority = {
        "runtime_point_output": 5,
        "given_point": 4,
        "public_candidate": 3,
        "axis_x_intercept": 2,
    }
    ref_map: dict[str, str] = {}
    for refs in groups.values():
        equivalent_groups: list[list[str]] = []
        for point_ref in refs:
            pair = _sympy_point_pair(known_points.get(point_ref))
            if pair is None:
                continue
            matching = next(
                (
                    group
                    for group in equivalent_groups
                    if (
                        (candidate_pair := _sympy_point_pair(
                            known_points.get(group[0])
                        ))
                        is not None
                        and _same_point_pair_value(pair, candidate_pair)
                    )
                ),
                None,
            )
            if matching is None:
                equivalent_groups.append([point_ref])
            else:
                matching.append(point_ref)
        for group in equivalent_groups:
            if len(group) < 2:
                continue
            canonical = max(
                group,
                key=lambda ref: (
                    definition_priority.get(
                        str((point_meta.get(ref) or {}).get("definition") or ""),
                        1,
                    ),
                    -len(ref),
                    ref,
                ),
            )
            ref_map.update(
                {point_ref: canonical for point_ref in group if point_ref != canonical}
            )
    return ref_map


def _hide_redundant_point_names(items: list[JsonObject]) -> list[JsonObject]:
    """A coordinate label already names its point; hide a second name label."""

    coordinate_refs = {
        str(item.get("at") or "")
        for item in items
        if isinstance(item, dict)
        and item.get("component") == "CoordinateLabel"
        and item.get("at")
    }
    result = copy.deepcopy(items)
    for item in result:
        if (
            isinstance(item, dict)
            and item.get("component") == "Point"
            and str(item.get("at") or "") in coordinate_refs
        ):
            item["showLabel"] = False
    return result


def _is_path_result_calculation_continuation(
    lesson_step: LessonStep,
    context: tuple[VisualObject, ...],
) -> bool:
    """Keep a completed shortest path as the scene for later arithmetic.

    A parameter-solving or substitution step may have its own generic visual
    marker (for example, it may redraw the segment whose length produced the
    parameter).  Once the preceding geometry step has already established a
    shortest-path result, that marker is supporting algebra rather than a new
    construction.  The completed path is therefore the more faithful visual
    state to carry through those calculation-only steps.
    """

    return (
        _visual_continuation_policy_for_lesson_step(lesson_step)
        == "preserve_prior_path_scene"
    ) and any(
        item.role.startswith("path_result:") for item in context
    )


def _path_result_calculation_updates(
    current: tuple[VisualObject, ...],
) -> tuple[VisualObject, ...]:
    """Apply only genuine scene updates after a shortest-path construction.

    Later parameter-solving and substitution methods may emit generic segment
    markers of their own.  Those would replace the just-completed geometry
    story with a new diagram even though the student is only doing arithmetic.
    Preserve the prior frame instead; a newly evaluated curve remains a real
    scene update and is allowed through.  Moving points and their incident
    segments already reference verified parameterized geometry, so changing
    the branch parameter moves them together without redrawing the scene.
    """

    return tuple(
        item
        for item in current
        if item.component in {"Parabola", "AxisOfSymmetry"}
    )


def _coalesce_visible_point_objects(
    objects: tuple[VisualObject, ...],
) -> tuple[VisualObject, ...]:
    """Keep one rendered point per geometry ref and one label per point."""

    coordinate_refs = {
        item.geometry_refs[0]
        for item in objects
        if item.component == "CoordinateLabel" and len(item.geometry_refs) == 1
    }
    result: list[VisualObject] = []
    point_indexes: dict[str, int] = {}
    for item in objects:
        if item.component != "Point" or len(item.geometry_refs) != 1:
            result.append(item)
            continue
        point_ref = item.geometry_refs[0]
        payload = copy.deepcopy(item.component_payload)
        if point_ref in coordinate_refs:
            payload["showLabel"] = False
        normalized = replace(item, component_payload=payload)
        prior_index = point_indexes.get(point_ref)
        if prior_index is None:
            point_indexes[point_ref] = len(result)
            result.append(normalized)
            continue
        prior = result[prior_index]
        if prior.state == "context" and normalized.state == "focus":
            result[prior_index] = normalized
    return tuple(result)


def _studentize_scene_point_labels(
    items: list[JsonObject],
    geometry_spec: JsonObject,
) -> list[JsonObject]:
    """Replace geometry registry identifiers with the public point label.

    Geometry ids intentionally carry branch identity (for example
    ``point_M_i`` and ``point_M_ii``).  They are suitable as references but
    must never become student-facing labels.  This pass is entirely driven by
    ``pointMeta`` and therefore does not guess from a problem-specific letter.
    """

    point_meta = geometry_spec.get("pointMeta") or {}
    result = copy.deepcopy(items)
    for item in result:
        if not isinstance(item, dict):
            continue
        geometry_ref = str(item.get("at") or "")
        meta = point_meta.get(geometry_ref)
        if not isinstance(meta, dict):
            continue
        item_metadata = item.get("metadata")
        if (
            isinstance(item_metadata, dict)
            and item_metadata.get("preserve_student_label") is True
        ):
            continue
        label = str(meta.get("label") or "").strip()
        if not label:
            continue
        component = str(item.get("component") or "")
        if component == "Point":
            current = str(item.get("labelText") or "").strip()
            if not current or current == geometry_ref or _looks_private_geometry_label(current):
                item["labelText"] = label
            continue
        if component != "CoordinateLabel":
            continue
        text = str(item.get("text") or "").strip()
        if not text.startswith(f"{geometry_ref}(") and not _looks_private_geometry_label(text):
            continue
        match = re.search(r"\((.*)\)$", text)
        if match:
            item["text"] = f"{label}({match.group(1)})"
    return result


def _studentize_timeline(
    timeline: JsonObject,
    geometry_spec: JsonObject,
) -> JsonObject:
    """Keep animation refs exact while exposing only public point labels."""

    result = copy.deepcopy(timeline)
    for beat in result.get("beats") or ():
        if not isinstance(beat, dict):
            continue
        patch = beat.get("scene_patch")
        if not isinstance(patch, dict):
            continue
        items = patch.get("add")
        if isinstance(items, list):
            patch["add"] = _studentize_scene_point_labels(items, geometry_spec)
    return result


def _looks_private_geometry_label(text: str) -> bool:
    head = text.split("(", 1)[0]
    return bool(
        re.fullmatch(
            r"(?:point|geometry|curve)_[A-Za-z0-9_]+",
            head,
        )
    )


_NON_GEOMETRY_TEXT_KEYS = frozenset(
    {
        "caption",
        "component",
        "definition",
        "detail",
        "display",
        "id",
        "kind",
        "label",
        "labelText",
        "name",
        "note",
        "role",
        "summary",
        "text",
        "type",
        "var",
    }
)


def _replace_visual_geometry_refs(value: Any, ref_map: dict[str, str]) -> Any:
    """Rewrite temporary point labels only where a payload stores refs."""

    if not ref_map:
        return copy.deepcopy(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "parameterized_points" and isinstance(item, dict):
                result[key] = {
                    ref_map.get(str(point_ref), str(point_ref)): (
                        _replace_visual_geometry_refs(payload, ref_map)
                    )
                    for point_ref, payload in item.items()
                }
            elif key in _NON_GEOMETRY_TEXT_KEYS:
                result[key] = copy.deepcopy(item)
            else:
                result[key] = _replace_visual_geometry_refs(item, ref_map)
        return result
    if isinstance(value, list):
        return [_replace_visual_geometry_refs(item, ref_map) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_visual_geometry_refs(item, ref_map) for item in value)
    if isinstance(value, str):
        return ref_map.get(value, value)
    return copy.deepcopy(value)


def _parameter_values_produced_by_lesson_step(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> dict[str, str]:
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    values: dict[str, str] = {}
    for step_id in lesson_step.source_step_ids:
        source = sources.get(step_id)
        if source is None:
            continue
        values.update(verified_parameter_values_from_source(source))
    return values


def _lesson_step_has_exact_point_output(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> bool:
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    for step_id in lesson_step.source_step_ids:
        source = sources.get(step_id)
        if source is None:
            continue
        for output in source.outputs.values():
            if str(output.get("runtime_type") or "") != "Point":
                continue
            value = output.get("value")
            if not isinstance(value, list | tuple) or len(value) != 2:
                continue
            try:
                if not any(sp.sympify(str(item)).free_symbols for item in value):
                    return True
            except Exception:
                continue
    return False


def _suppressed_current_point_refs(
    lesson_step: LessonStep,
    *,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
) -> frozenset[str]:
    policy = _visual_context_policy_for_lesson_step(lesson_step)
    if (
        not policy.suppress_point_definitions_when_exact
        or not _lesson_step_has_exact_point_output(lesson_step, snapshot)
    ):
        return frozenset()
    return frozenset(
        str(point_id)
        for point_id, meta in (geometry_spec.get("pointMeta") or {}).items()
        if isinstance(meta, dict)
        and str(meta.get("definition") or "")
        in policy.suppress_point_definitions_when_exact
    )


def _visual_step_for_lesson_step(
    lesson_step: LessonStep,
    *,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
    bindings: VisualRoleBindings,
) -> VisualStep:
    """Compatibility helper for focused unit tests; production uses resolver."""

    return _visual_step_resolution(
        lesson_step,
        state=BranchVisualState(),
        snapshot=snapshot,
        geometry_spec=geometry_spec,
        bindings=bindings,
    ).step


def _visual_frame_unit_groups(lesson_step: LessonStep) -> tuple[tuple[str, ...], ...]:
    """Render one complete Frame per accepted LessonStep.

    Teaching/visual separation is resolved before LessonIR assembly.  Re-splitting
    Macro units here would create a second, capability-shaped boundary system and
    let LessonIR claim one teaching step while the page silently shows several.
    """

    unit_keys = tuple(lesson_step.teaching_unit_keys)
    return (unit_keys,)


def _lesson_step_for_visual_units(
    lesson_step: LessonStep,
    unit_keys: tuple[str, ...],
) -> LessonStep:
    return type(lesson_step)(
        replace(lesson_step.step, teaching_unit_keys=tuple(unit_keys)),
        lesson_step.scope_ref,
        lesson_step.goal_ref,
    )


def _tagged_scene_items_for_lesson_step(
    lesson_step: LessonStep,
    *,
    snapshot: ExplanationSnapshot,
    bindings: VisualRoleBindings,
    coordinate_texts: dict[str, str],
) -> list[JsonObject]:
    sources = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    recipe_capabilities = {
        capability_id
        for capability_id in lesson_step.capability_ids
        if _recipe_visual_spec(capability_id) is not None
    }
    if recipe_capabilities or len(lesson_step.source_step_ids) <= 1:
        items = _scene_add_for_lesson_step(
            lesson_step,
            bindings,
            coordinate_texts=coordinate_texts,
        )
        return [
            {**item, "_source_step_ids": list(lesson_step.source_step_ids)}
            for item in items
        ]

    result: list[JsonObject] = []
    for source_step_id in lesson_step.source_step_ids:
        source = sources.get(source_step_id)
        if source is None:
            continue
        unit_keys = tuple(
            unit_key
            for unit_key in lesson_step.teaching_unit_keys
            if unit_key.startswith(f"{source.capability_id}/")
        )
        isolated = type(lesson_step)(
            replace(
                lesson_step.step,
                source_step_ids=(source_step_id,),
                capability_ids=(source.capability_id,),
                teaching_unit_keys=unit_keys,
            ),
            lesson_step.scope_ref,
            lesson_step.goal_ref,
        )
        for item in _scene_add_for_lesson_step(
            isolated,
            bindings,
            coordinate_texts=coordinate_texts,
        ):
            result.append({**item, "_source_step_ids": [source_step_id]})
    return _dedupe_scene_items(result)


def _visual_context_for_step(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    current: tuple[VisualObject, ...],
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
) -> tuple[VisualObject, ...]:
    policy = _visual_context_policy_for_lesson_step(lesson_step)
    current_ids = {item.visual_object_id for item in current}
    selected: list[VisualObject] = []

    def add(item: VisualObject) -> None:
        if item.visual_object_id in current_ids:
            return
        if any(existing.visual_object_id == item.visual_object_id for existing in selected):
            return
        selected.append(context_copy(item))

    dependency_steps = _input_dependency_step_ids(lesson_step, snapshot)
    if policy.include_exact_dependencies:
        for item in state.available.values():
            if (
                policy.dependency_components is not None
                and item.component not in policy.dependency_components
            ):
                continue
            source_steps = {
                str(ref.get("step_id") or "")
                for ref in item.source_refs
                if isinstance(ref, dict)
            }
            if source_steps.intersection(dependency_steps):
                add(item)

    for role, options in policy.roles:
        if role == "input_curve":
            curve_ids = _context_curve_geometry_ids(
                lesson_step,
                state=state,
                snapshot=snapshot,
                geometry_spec=geometry_spec,
            )
            for item in state.available.values():
                if item.component == "Parabola" and set(item.geometry_refs).intersection(
                    curve_ids
                ):
                    add(item)
            continue
        if role == "x_axis_points":
            for item in state.available.values():
                if _visual_point_is_on_x_axis(item, geometry_spec):
                    add(item)
            continue
        if role == "curve_x_intercepts":
            for item in _curve_x_intercept_context_objects(
                lesson_step,
                state=state,
                snapshot=snapshot,
                geometry_spec=geometry_spec,
            ):
                add(item)
            continue
        if role == "curve_axis":
            for item in _axis_intercept_context_objects(
                lesson_step,
                state=state,
                snapshot=snapshot,
                geometry_spec=geometry_spec,
            ):
                add(item)
            continue
        if role == "square_predecessor":
            for item in _square_predecessor_context(
                lesson_step,
                state=state,
                snapshot=snapshot,
                geometry_spec=geometry_spec,
                options=options,
            ):
                add(item)
            continue
        if role == "connected_dependency_geometry":
            for item in _connected_dependency_context_objects(
                state=state,
                current=current,
                dependency_steps=dependency_steps,
            ):
                add(item)
            continue
        if role == "prior_curve_vertex":
            # A previously verified landmark of the same mathematical curve
            # may be reused without importing the producer Goal's whole scene.
            for item in _prior_verified_curve_vertex_context_objects(
                lesson_step,
                state=state,
                current=current,
                snapshot=snapshot,
                geometry_spec=geometry_spec,
            ):
                add(item)
            continue
        raise ValueError(
            "visual_context_role_unknown: "
            f"role={role}, capabilities={list(lesson_step.capability_ids)}"
        )

    return tuple(selected)


def _prior_verified_curve_vertex_context_objects(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    current: tuple[VisualObject, ...],
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
) -> tuple[VisualObject, ...]:
    """Project earlier public curve vertices as narrow cross-Goal context.

    The join uses the verified input curve expression and the public Point
    value.  A point letter alone is never enough to select geometry.
    """

    visible_curve_ids = {
        geometry_ref
        for item in (*tuple(state.available.values()), *current)
        if item.component == "Parabola"
        for geometry_ref in item.geometry_refs
    }
    if not visible_curve_ids:
        return ()
    curves = {
        str(curve.get("id") or ""): curve
        for curve in geometry_spec.get("curves") or ()
        if isinstance(curve, dict)
        and str(curve.get("id") or "") in visible_curve_ids
    }
    if not curves:
        return ()

    rows = _teaching_source_owner_rows(snapshot)
    source_order = {
        source.source_step_id: index
        for index, (_scope_ref, _goal_ref, source) in enumerate(rows)
    }
    current_positions = [
        source_order[step_id]
        for step_id in lesson_step.source_step_ids
        if step_id in source_order
    ]
    if not current_positions:
        return ()
    current_start = min(current_positions)
    geometry_index = VisualGeometryIndex(geometry_spec, snapshot.problem)
    known_pairs = {
        str(point_id): _sympy_pair_value(pair)
        for collection in ("fixedPoints", "movingPoints")
        for point_id, pair in (geometry_spec.get(collection) or {}).items()
    }
    raw: list[JsonObject] = []
    seen_refs: set[str] = set()

    for index, (source_scope, _source_goal, source) in enumerate(rows):
        if index >= current_start:
            continue
        matching_curves = tuple(
            curve
            for curve in curves.values()
            if _teaching_source_reads_curve(source, curve)
        )
        if len(matching_curves) != 1:
            continue
        vertex_pair = _curve_vertex_pair(matching_curves[0])
        if vertex_pair is None:
            continue
        for return_name, output in source.outputs.items():
            if not isinstance(output, dict) or str(output.get("runtime_type") or "") != "Point":
                continue
            output_pair = _sympy_pair_value(output.get("value"))
            if output_pair is None or not _same_point_pair_value(output_pair, vertex_pair):
                continue
            target_handles = _problem_point_handles_for_output(
                source,
                return_name,
                snapshot=snapshot,
                scope_id=source_scope,
            )
            if len(target_handles) != 1:
                continue
            target_handle = next(iter(target_handles))
            entity = _resolve_problem_semantic_item(
                snapshot,
                semantic_ref=target_handle,
                scope_id=source_scope,
                collection="entities",
                expected_type="point",
            )
            if entity is None:
                continue
            label = str(
                entity.get("name")
                or _handle_tail(str(entity.get("handle") or ""))
            )
            point_ref = geometry_index.point_for_handle(
                target_handle,
                lesson_step.scope_id,
            )
            if not point_ref or point_ref in seen_refs:
                continue
            geometry_pair = known_pairs.get(point_ref)
            if geometry_pair is None or not _same_point_pair_value(
                geometry_pair,
                output_pair,
            ):
                continue
            seen_refs.add(point_ref)
            raw.append(
                {
                    "component": "Point",
                    "handle": f"point:{point_ref}",
                    "at": point_ref,
                    "labelText": label,
                    "color": COLOR_MUTED,
                    "dx": 14,
                    "dy": -18,
                    "role": "curve_vertex",
                    "_source_step_ids": [source.source_step_id],
                }
            )

    return tuple(
        context_copy(item)
        for item in visual_objects_from_scene_items(
            raw,
            owner_scope_ref=lesson_step.scope_id,
            source_step_ids=tuple(
                dict.fromkeys(
                    str(step_id)
                    for item in raw
                    for step_id in item.get("_source_step_ids") or ()
                )
            ),
            focus=False,
        )
    )


def _teaching_source_reads_curve(source: Any, curve: JsonObject) -> bool:
    curve_expression = _curve_expression(curve)
    if curve_expression is None:
        return False
    for values in source.inputs.values():
        for value in values:
            if not isinstance(value, dict):
                continue
            if str(value.get("runtime_type") or "") not in {
                "Parabola",
                "QuadraticCurve",
                "QuadraticFunction",
            }:
                continue
            try:
                candidate = sp.sympify(str(value.get("value") or ""))
            except Exception:
                continue
            if sp.simplify(candidate - curve_expression) == 0:
                return True
    return False


def _curve_expression(curve: JsonObject) -> sp.Expr | None:
    try:
        x = sp.Symbol("x")
        return sp.simplify(
            sp.sympify(str(curve.get("a") or "0")) * x**2
            + sp.sympify(str(curve.get("b") or "0")) * x
            + sp.sympify(str(curve.get("c") or "0"))
        )
    except Exception:
        return None


def _curve_vertex_pair(curve: JsonObject) -> tuple[sp.Expr, sp.Expr] | None:
    try:
        a = sp.sympify(str(curve.get("a") or "0"))
        b = sp.sympify(str(curve.get("b") or "0"))
        c = sp.sympify(str(curve.get("c") or "0"))
        if sp.simplify(a) == 0:
            return None
        x_value = sp.simplify(-b / (2 * a))
        return x_value, sp.simplify(a * x_value**2 + b * x_value + c)
    except Exception:
        return None


def _input_dependency_step_ids(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> set[str]:
    source_by_id = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    dependencies: set[str] = set()
    for source_step_id in lesson_step.source_step_ids:
        source = source_by_id.get(source_step_id)
        if source is None:
            continue
        for values in source.inputs.values():
            for value in values:
                for ref_key in ("ref", "resolved_from"):
                    ref = value.get(ref_key)
                    if not isinstance(ref, dict) or ref.get("kind") != "step_result":
                        continue
                    step_id = str(ref.get("step_id") or "")
                    if step_id:
                        dependencies.add(step_id)
    return dependencies


def _merge_frame_objects(
    context: tuple[VisualObject, ...],
    current: tuple[VisualObject, ...],
) -> tuple[VisualObject, ...]:
    by_id: dict[str, VisualObject] = {}
    order: list[str] = []
    for item in (*context, *current):
        if item.visual_object_id not in by_id:
            order.append(item.visual_object_id)
        previous = by_id.get(item.visual_object_id)
        if previous is None or item.state == "focus":
            by_id[item.visual_object_id] = item
    return tuple(by_id[object_id] for object_id in order)


def _scene_item_persists(
    item: JsonObject,
    scene_items: list[JsonObject],
) -> bool:
    """Project VisualSpec persistence without adding it to VisualStepIR.

    Coordinate labels inherit the lifetime of the mathematical point they
    annotate.  This prevents a label from surviving after a ``step_only``
    construction point has correctly left the next incremental Frame.
    """

    if str(item.get("persistence") or "") == "step_only":
        return False
    if str(item.get("component") or "") != "CoordinateLabel":
        return True
    point_ref = str(item.get("at") or "")
    if not point_ref:
        return True
    matching_points = [
        candidate
        for candidate in scene_items
        if str(candidate.get("component") or "") == "Point"
        and str(candidate.get("at") or "") == point_ref
    ]
    return not matching_points or any(
        str(candidate.get("persistence") or "") != "step_only"
        for candidate in matching_points
    )


def _dedupe_visual_objects(items: list[VisualObject]) -> list[VisualObject]:
    by_id: dict[str, VisualObject] = {}
    order: list[str] = []
    for item in items:
        if item.visual_object_id not in by_id:
            order.append(item.visual_object_id)
        by_id[item.visual_object_id] = item
    return [by_id[object_id] for object_id in order]


def _context_visibility_reason(
    lesson_step: LessonStep,
    item: VisualObject,
) -> str:
    if item.role == "curve_vertex":
        return "prior_verified_curve_vertex_context"
    dependency_steps = {
        str(ref.get("step_id") or "")
        for ref in item.source_refs
        if isinstance(ref, dict)
    }
    if dependency_steps.intersection(lesson_step.source_step_ids):
        return "current_component_input"
    return "ancestor_or_exact_dependency_context"


def _branch_frame_inheritance_reason(
    lesson_step: LessonStep,
    state: BranchVisualState,
) -> str:
    """Explain why the preceding complete Frame is visible here.

    A Goal's first step receives the completed entry state of its direct
    Scope.  Later steps in that Goal receive the preceding Goal step.  Scope
    steps follow the same rule within their own container.  The resolver has
    already cloned branches, so none of these reasons can imply sibling
    carry-forward.
    """

    if not state.last_frame:
        return "no_inherited_frame"
    current = (
        f"goal:{lesson_step.goal_ref}"
        if lesson_step.goal_ref is not None
        else f"scope:{lesson_step.scope_ref}"
    )
    if state.last_container_ref == current:
        return (
            "previous_step_in_same_goal"
            if lesson_step.goal_ref is not None
            else "previous_step_in_same_scope"
        )
    return (
        "direct_scope_entry_frame"
        if lesson_step.goal_ref is not None
        else "ancestor_scope_entry_frame"
    )


def _visual_point_is_on_x_axis(
    item: VisualObject,
    geometry_spec: JsonObject,
) -> bool:
    if item.component != "Point" or not item.geometry_refs:
        return False
    pair = _geometry_point_pair(geometry_spec, item.geometry_refs[0])
    if pair is None:
        return False
    try:
        return sp.simplify(sp.sympify(str(pair[1]))) == 0
    except Exception:
        return False


def _context_curve_geometry_ids(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
) -> frozenset[str]:
    """Resolve the current mathematical curve without a capability switch.

    A typed curve input is authoritative.  A construction Method that does
    not consume the curve directly may reuse the sole curve already visible
    in its exact branch.  Multiple matches are an authority error rather than
    a cue to pick the first registry entry.
    """

    input_expressions: list[sp.Expr] = []
    source_by_id = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    for step_id in lesson_step.source_step_ids:
        source = source_by_id.get(step_id)
        if source is None:
            continue
        for values in source.inputs.values():
            for value in values:
                if str(value.get("runtime_type") or "") not in {
                    "Parabola",
                    "QuadraticCurve",
                    "QuadraticFunction",
                }:
                    continue
                expression = _public_curve_expression(value.get("value"))
                if expression is not None:
                    input_expressions.append(expression)

    visible_curve_ids = {
        geometry_ref
        for item in state.available.values()
        if item.component == "Parabola"
        for geometry_ref in item.geometry_refs
    }
    visible_scopes = set(scope_lineage(lesson_step.scope_id))
    matches = {
        str(curve.get("id") or "")
        for curve in geometry_spec.get("curves") or ()
        if isinstance(curve, dict)
        and (
            str(curve.get("id") or "") in visible_curve_ids
            or str(curve.get("scopeId") or "problem") in visible_scopes
        )
        and any(
            _same_curve_expression(expression, curve)
            for expression in input_expressions
        )
    }
    matches.discard("")
    if input_expressions and not matches:
        raise ValueError(
            "visual_context_input_curve_missing: "
            f"steps={list(lesson_step.source_step_ids)}"
        )
    if len(matches) > 1:
        raise ValueError(
            "visual_context_input_curve_ambiguous: "
            f"steps={list(lesson_step.source_step_ids)}, curves={sorted(matches)}"
        )
    if matches:
        return frozenset(matches)

    if len(visible_curve_ids) > 1:
        raise ValueError(
            "visual_context_branch_curve_ambiguous: "
            f"steps={list(lesson_step.source_step_ids)}, "
            f"curves={sorted(visible_curve_ids)}"
        )
    return frozenset(visible_curve_ids)


def _public_curve_expression(value: Any) -> sp.Expr | None:
    if isinstance(value, dict):
        value = value.get("expression") or value.get("equation")
    try:
        return sp.simplify(sp.sympify(str(value)))
    except Exception:
        return None


def _same_curve_expression(expression: sp.Expr, curve: JsonObject) -> bool:
    candidate = _curve_expression(curve)
    return candidate is not None and sp.simplify(expression - candidate) == 0


def _square_predecessor_context(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
    options: JsonObject,
) -> tuple[VisualObject, ...]:
    """Select a square anchor through exact entity refs and vertex order."""

    source_by_id = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    target_handles: set[str] = set()
    co_vertex_handles: set[str] = set()
    for step_id in lesson_step.source_step_ids:
        source = source_by_id.get(step_id)
        if source is None:
            continue
        target_output = str(options.get("target_output") or "")
        if target_output:
            target_handles.update(
                _problem_point_handles_for_output(
                    source,
                    target_output,
                    snapshot=snapshot,
                    scope_id=lesson_step.scope_id,
                )
            )
        target_input = str(options.get("target_input") or "")
        if target_input:
            target_handles.update(
                _problem_point_handles_for_input(
                    source,
                    target_input,
                    sources=source_by_id,
                    snapshot=snapshot,
                    scope_id=lesson_step.scope_id,
                )
            )
        co_vertex_input = str(options.get("co_vertex_input") or "")
        if co_vertex_input:
            co_vertex_handles.update(
                _problem_point_handles_for_input(
                    source,
                    co_vertex_input,
                    sources=source_by_id,
                    snapshot=snapshot,
                    scope_id=lesson_step.scope_id,
                )
            )
    if len(target_handles) != 1:
        if not target_handles:
            return ()
        raise ValueError(
            "visual_square_predecessor_target_ambiguous: "
            f"steps={list(lesson_step.source_step_ids)}, targets={sorted(target_handles)}"
        )

    target_handle = next(iter(target_handles))
    matches: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    for fact in (snapshot.problem or {}).get("facts") or ():
        if not isinstance(fact, dict) or fact.get("type") != "square":
            continue
        vertices = tuple(
            _resolve_problem_point_handle(snapshot, str(item), lesson_step.scope_id)
            for item in fact.get("vertices") or ()
        )
        if target_handle not in vertices:
            continue
        if co_vertex_handles and not co_vertex_handles.intersection(vertices):
            continue
        matches.append((fact, vertices))
    if len(matches) > 1:
        raise ValueError(
            "visual_square_predecessor_square_ambiguous: "
            f"target={target_handle}, squares="
            f"{sorted(str(fact.get('handle') or '') for fact, _ in matches)}"
        )
    if not matches:
        return ()

    _, vertices = matches[0]
    predecessor_handle = vertices[(vertices.index(target_handle) - 1) % len(vertices)]
    geometry_id = VisualGeometryIndex(
        geometry_spec,
        snapshot.problem,
    ).point_for_handle(predecessor_handle, lesson_step.scope_id)
    if not geometry_id:
        return ()
    return tuple(
        context_copy(item)
        for item in state.available.values()
        if item.component == "Point" and geometry_id in item.geometry_refs
    )


def _problem_point_handles_for_input(
    source: Any,
    input_name: str,
    *,
    sources: dict[str, Any],
    snapshot: ExplanationSnapshot,
    scope_id: str,
) -> set[str]:
    handles: set[str] = set()
    for value in source.inputs.get(input_name, ()):
        ref = value.get("ref")
        semantic_ref = ""
        if isinstance(ref, dict) and ref.get("kind") == "source":
            semantic_ref = str(ref.get("ref") or "")
        elif isinstance(ref, dict) and ref.get("kind") == "step_result":
            producer = sources.get(str(ref.get("step_id") or ""))
            if producer is not None:
                semantic_ref = str(
                    producer.output_targets.get(str(ref.get("return") or "")) or ""
                )
        if not semantic_ref:
            continue
        handle = _resolve_problem_point_handle(snapshot, semantic_ref, scope_id)
        if handle:
            handles.add(handle)
    return handles


def _problem_point_handles_for_output(
    source: Any,
    return_name: str,
    *,
    snapshot: ExplanationSnapshot,
    scope_id: str,
) -> set[str]:
    semantic_ref = _public_point_semantic_ref(snapshot, source, return_name)
    if semantic_ref:
        handle = _resolve_problem_point_handle(snapshot, semantic_ref, scope_id)
        return {handle} if handle else set()

    goal_refs = {
        goal.goal_ref
        for scope in iter_teaching_scopes(snapshot.root_scope)
        for goal in scope.goals
        if str(goal.answer_from.get("step_id") or "") == source.source_step_id
        and str(goal.answer_from.get("return") or "") == return_name
    }
    target_handles = {
        str(goal.get("target_handle") or "")
        for goal in (snapshot.problem or {}).get("question_goals") or ()
        if isinstance(goal, dict)
        and str(goal.get("handle") or "")
        in {f"answer:{goal_ref}" for goal_ref in goal_refs}
    }
    target_handles.discard("")
    return target_handles


def _connected_dependency_context_objects(
    *,
    state: BranchVisualState,
    current: tuple[VisualObject, ...],
    dependency_steps: set[str],
) -> tuple[VisualObject, ...]:
    target_refs = {
        geometry_ref
        for item in current
        if item.component == "Point"
        for geometry_ref in item.geometry_refs
    }
    connected: list[VisualObject] = []
    for item in state.available.values():
        if item.component not in {
            "ColoredLine",
            "DashedLine",
            "DistanceMarker",
            "LocusLine",
            "OutlineRegion",
        }:
            continue
        if not set(item.geometry_refs).intersection(target_refs):
            continue
        if not any(
            isinstance(ref, dict)
            and str(ref.get("step_id") or "") in dependency_steps
            for ref in item.source_refs
        ):
            continue
        connected.append(item)
    endpoint_refs = {
        geometry_ref
        for item in connected
        for geometry_ref in item.geometry_refs
    }
    return tuple(
        context_copy(item)
        for item in state.available.values()
        if item in connected
        or (
            item.component == "Point"
            and bool(set(item.geometry_refs).intersection(endpoint_refs))
        )
    )


def _axis_intercept_context_objects(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
) -> tuple[VisualObject, ...]:
    curve_ids = _context_curve_geometry_ids(
        lesson_step,
        state=state,
        snapshot=snapshot,
        geometry_spec=geometry_spec,
    )
    if not curve_ids:
        return ()
    curve_id = next(iter(curve_ids))
    curve = next(
        (
            item
            for item in geometry_spec.get("curves") or ()
            if isinstance(item, dict)
            and str(item.get("id") or "") == curve_id
        ),
        None,
    )
    if curve is None:
        return ()
    scope_ref = str(curve.get("scopeId") or lesson_step.scope_id)
    point_ids = [
        str(point_id)
        for point_id, meta in (geometry_spec.get("pointMeta") or {}).items()
        if isinstance(meta, dict)
        and meta.get("definition") == "axis_x_intercept"
        and str(meta.get("sourceCurveId") or "") == str(curve.get("id") or "")
        and str(meta.get("scopeId") or "") == scope_ref
    ]
    if len(point_ids) != 1:
        return ()
    point_id = point_ids[0]
    pair = _geometry_point_pair(geometry_spec, point_id)
    if pair is None:
        return ()
    label = str(
        ((geometry_spec.get("pointMeta") or {}).get(point_id) or {}).get("label")
        or ""
    )
    if not label:
        return ()
    raw = [
        {
            "component": "AxisOfSymmetry",
            "handle": f"axis:{curve.get('id')}",
            "curveId": str(curve.get("id") or ""),
            "color": COLOR_MUTED,
            "width": 1.5,
            "dash": "7 6",
            "role": "curve:axis",
            "_source_step_ids": list(lesson_step.source_step_ids),
        },
        {
            "component": "Point",
            "handle": f"point:{point_id}",
            "at": point_id,
            "labelText": label,
            "color": COLOR_MUTED,
            "dx": 14,
            "dy": -18,
            "role": "axis_x_intercept",
            "_source_step_ids": list(lesson_step.source_step_ids),
        }
    ]
    return tuple(
        context_copy(item)
        for item in visual_objects_from_scene_items(
            raw,
            owner_scope_ref=scope_ref,
            source_step_ids=tuple(lesson_step.source_step_ids),
            focus=False,
        )
    )


def _curve_x_intercept_context_objects(
    lesson_step: LessonStep,
    *,
    state: BranchVisualState,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
) -> tuple[VisualObject, ...]:
    """Expose already determined x-intercepts required by a vertex diagram.

    The geometry is selected through the current branch's curve provenance,
    never through a point letter.  This keeps the companion intercept visible
    in the vertex frame without publishing it into sibling/descendant state.
    """

    curve_ids = _context_curve_geometry_ids(
        lesson_step,
        state=state,
        snapshot=snapshot,
        geometry_spec=geometry_spec,
    )
    if not curve_ids:
        return ()
    curve_id = next(iter(curve_ids))
    curve = next(
        (
            item
            for item in geometry_spec.get("curves") or ()
            if isinstance(item, dict)
            and str(item.get("id") or "") == curve_id
        ),
        None,
    )
    if curve is None:
        return ()
    expression = _curve_expression(curve)
    if expression is None:
        return ()
    return tuple(
        context_copy(item)
        for item in state.available.values()
        if item.component == "Point"
        and any(
            _point_pair_is_x_intercept_of_curve(
                _geometry_point_pair(geometry_spec, geometry_ref),
                expression,
            )
            for geometry_ref in item.geometry_refs
        )
    )


def _point_pair_is_x_intercept_of_curve(
    pair: list[str] | None,
    curve: sp.Expr,
) -> bool:
    if pair is None:
        return False
    try:
        x_value = sp.sympify(str(pair[0]))
        y_value = sp.sympify(str(pair[1]))
        return sp.simplify(y_value) == 0 and sp.simplify(
            curve.subs(sp.Symbol("x"), x_value)
        ) == 0
    except Exception:
        return False


def _local_parameters_for_frame(
    *,
    lesson_step: LessonStep,
    state: BranchVisualState,
    geometry_spec: JsonObject,
    objects: tuple[VisualObject, ...],
    snapshot: ExplanationSnapshot,
) -> tuple[JsonObject, ...]:
    expressions_by_ref: dict[str, tuple[str, ...]] = {}
    for item in objects:
        for geometry_ref in item.geometry_refs:
            pair = _geometry_point_pair(geometry_spec, geometry_ref)
            if pair is not None:
                expressions_by_ref[geometry_ref] = tuple(str(value) for value in pair)
            curve = next(
                (
                    curve
                    for curve in geometry_spec.get("curves") or ()
                    if isinstance(curve, dict) and str(curve.get("id") or "") == geometry_ref
                ),
                None,
            )
            if curve is not None:
                expressions_by_ref[geometry_ref] = tuple(
                    str(curve.get(key) or "") for key in ("a", "b", "c")
                )
    symbols: set[str] = set()
    for expressions in expressions_by_ref.values():
        for expression in expressions:
            try:
                symbols.update(str(symbol) for symbol in sp.sympify(expression).free_symbols)
            except Exception:
                continue
    symbols.discard("x")
    result: list[JsonObject] = []
    for name in sorted(symbols):
        if name in state.parameters:
            exact_value = str(state.parameters[name])
            numeric_value = _numeric_parameter_value(exact_value)
            result.append(
                {
                    "name": name,
                    "mathematical_domain": {
                        "kind": "exact",
                        "value": exact_value,
                    },
                    "display_window": {
                        "min": numeric_value,
                        "max": numeric_value,
                        "step": 0,
                    },
                    "default_value": numeric_value,
                    "source_refs": [
                        {"kind": "verified_parameter_state", "name": name}
                    ],
                    "controls": [],
                    "parameterized_points": {},
                    "landmarks": [],
                    "note": "",
                }
            )
            continue
        mathematical_domain, window, default = _parameter_domain_and_window(
            name,
            snapshot,
        )
        interactive_source_step_ids = _interactive_point_parameter_source_step_ids(
            name=name,
            lesson_step=lesson_step,
            snapshot=snapshot,
        )
        parameterized_points = {
            geometry_ref: {
                "expression": list(expressions),
                "source": {
                    "kind": "visible_geometry",
                    "geometry_ref": geometry_ref,
                },
            }
            for geometry_ref, expressions in expressions_by_ref.items()
            if any(_expression_uses_symbol(expression, name) for expression in expressions)
            and len(expressions) == 2
        }
        landmarks = (
            CandidateHitResolver(geometry_spec).landmarks_for_parameter(
                lesson_step=lesson_step,
                snapshot=snapshot,
                parameter=name,
                parameterized_points=parameterized_points,
                objects=objects,
                parameter_values=state.parameters,
            )
            if interactive_source_step_ids
            else ()
        )
        if interactive_source_step_ids:
            window = _display_window_with_landmarks(window, landmarks)
        landmark_epsilon = max(float(window["step"]) / 2, 1e-6)
        landmarks = tuple(
            {**landmark, "epsilon": landmark_epsilon}
            for landmark in landmarks
        )
        result.append(
            {
                "name": name,
                "mathematical_domain": mathematical_domain,
                "display_window": window,
                "default_value": default,
                "source_refs": [
                    {"kind": "functional_step", "step_id": step_id}
                    for step_id in (
                        interactive_source_step_ids or lesson_step.source_step_ids
                    )
                ],
                "controls": (
                    [
                        {
                            "var": name,
                            "label": f"参数 {name}（示意）",
                            "min": window["min"],
                            "max": window["max"],
                            "step": window["step"],
                            "scale": 1,
                            "precision": 2,
                        }
                    ]
                    if interactive_source_step_ids
                    else []
                ),
                "parameterized_points": parameterized_points,
                "landmarks": list(landmarks),
                "note": (
                    "拖动仅用于观察当前步骤中的参数变化，不改变数学定义域。"
                    if interactive_source_step_ids
                    else ""
                ),
            }
        )
    return tuple(result)


def _interactive_point_parameter_source_step_ids(
    *,
    name: str,
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> tuple[str, ...]:
    """Return verified producers that make ``name`` a moving-point control.

    A free symbol is not automatically interactive.  It becomes a slider only
    when a visible producer in this exact branch publicly returns both the
    symbol and a Point whose coordinates depend on it.  This distinguishes a
    moving-point coordinate such as ``E(-1,t)`` from a problem coefficient such
    as ``c`` in a family of parabolas without consulting either symbol's name.
    """

    rows = _teaching_source_owner_rows(snapshot)
    order = {
        source.source_step_id: index
        for index, (_scope_ref, _goal_ref, source) in enumerate(rows)
    }
    current_positions = [
        order[step_id]
        for step_id in lesson_step.source_step_ids
        if step_id in order
    ]
    if not current_positions:
        return ()
    current_position = max(current_positions)
    current_lineage = set(scope_lineage(lesson_step.scope_id))
    producers: list[str] = []
    parameter = sp.Symbol(name)

    for index, (scope_ref, goal_ref, source) in enumerate(rows):
        if index > current_position or scope_ref not in current_lineage:
            continue
        if scope_ref == lesson_step.scope_id:
            if goal_ref not in {None, lesson_step.goal_ref}:
                continue
        elif goal_ref is not None:
            # Goal-local state never becomes an ancestor-scope interaction.
            continue

        returns_symbol = any(
            str(output.get("runtime_type") or "") == "Symbol"
            and str(output.get("value") or output.get("display") or "").strip()
            == name
            for output in source.outputs.values()
            if isinstance(output, dict)
        )
        if not returns_symbol:
            continue
        returns_parameterized_point = False
        for output in source.outputs.values():
            if not isinstance(output, dict) or str(output.get("runtime_type") or "") != "Point":
                continue
            pair = sympy_pair(output.get("value"), axis_parameter_alias=name)
            if pair is not None and any(parameter in value.free_symbols for value in pair):
                returns_parameterized_point = True
                break
        if returns_parameterized_point:
            producers.append(source.source_step_id)

    return tuple(dict.fromkeys(producers))


def _numeric_parameter_value(value: str) -> float:
    try:
        return float(sp.N(sp.sympify(str(value))))
    except Exception as exc:
        raise ValueError(
            f"visual_exact_parameter_not_numeric: {value}"
        ) from exc


def _merge_local_parameter_contracts(
    contracts: tuple[JsonObject, ...],
    interactions: tuple[JsonObject, ...],
    *,
    source_step_ids: tuple[str, ...],
) -> tuple[JsonObject, ...]:
    by_name = {str(item.get("name") or ""): copy.deepcopy(item) for item in contracts}
    for interaction in interactions:
        name = str(interaction.get("parameter") or "")
        if not name:
            continue
        domain = interaction.get("domain") if isinstance(interaction.get("domain"), dict) else {}
        if name in by_name:
            current = by_name[name]
            if interaction.get("controls"):
                current["controls"] = copy.deepcopy(interaction.get("controls") or [])
                current["source_refs"] = [
                    {"kind": "functional_step", "step_id": step_id}
                    for step_id in source_step_ids
                ]
                current["note"] = str(interaction.get("note") or "")
            if interaction.get("mathematical_domain"):
                current["mathematical_domain"] = copy.deepcopy(
                    interaction["mathematical_domain"]
                )
            if domain:
                current["display_window"] = {
                    "min": domain.get("min", 0),
                    "max": domain.get("max", 1),
                    "step": domain.get("step", 0.01),
                }
                current["default_value"] = domain.get("default", 0.5)
            current["parameterized_points"] = {
                **copy.deepcopy(current.get("parameterized_points") or {}),
                **copy.deepcopy(interaction.get("parameterized_points") or {}),
            }
            continue
        by_name[name] = {
            "name": name,
            "mathematical_domain": copy.deepcopy(
                interaction.get("mathematical_domain")
                or {"kind": "closed_interval", "min": 0, "max": 1}
            ),
            "display_window": {
                "min": domain.get("min", 0),
                "max": domain.get("max", 1),
                "step": domain.get("step", 0.01),
            },
            "default_value": domain.get("default", 0.5),
            "source_refs": [
                {"kind": "functional_step", "step_id": step_id}
                for step_id in source_step_ids
            ],
            "controls": copy.deepcopy(interaction.get("controls") or []),
            "parameterized_points": copy.deepcopy(
                interaction.get("parameterized_points") or {}
            ),
            "landmarks": [],
            "note": str(interaction.get("note") or ""),
        }
    return tuple(by_name[name] for name in sorted(by_name) if name)


def _inherit_local_parameter_defaults(
    contracts: tuple[JsonObject, ...],
    previous: tuple[JsonObject, ...],
    *,
    active_interactions: tuple[JsonObject, ...],
    objects: tuple[VisualObject, ...],
    geometry_spec: JsonObject,
    parameter_values: Mapping[str, str],
) -> tuple[JsonObject, ...]:
    """Preserve the preceding diagram state across calculation-only steps.

    A later step may add only a scalar conclusion while retaining the same
    parameterized points.  Reconstructing local parameters from the geometry
    registry would reset those points to an unrelated demonstration value.
    We carry a default only when the parameter controls at least one identical
    visible geometry ref and the current step has no new interaction for it.
    """

    if not contracts or not previous:
        return contracts
    active_names = {
        str(item.get("parameter") or "")
        for item in active_interactions
        if str(item.get("parameter") or "")
    }
    visible_refs = {
        geometry_ref
        for item in objects
        for geometry_ref in item.geometry_refs
    }
    previous_by_name = {
        str(item.get("name") or ""): item
        for item in previous
        if str(item.get("name") or "")
    }
    result: list[JsonObject] = []
    for contract in contracts:
        current = copy.deepcopy(contract)
        name = str(current.get("name") or "")
        prior = previous_by_name.get(name)
        if name in active_names or prior is None:
            result.append(current)
            continue
        if str((current.get("mathematical_domain") or {}).get("kind") or "") == "exact":
            result.append(current)
            continue
        attainment_default = _released_interaction_attainment_default(
            name=name,
            previous=prior,
            visible_refs=visible_refs,
            geometry_spec=geometry_spec,
            parameter_values=parameter_values,
        )
        if attainment_default is not None:
            window = current.get("display_window") or {}
            minimum = float(window.get("min", attainment_default))
            maximum = float(window.get("max", attainment_default))
            if minimum <= attainment_default <= maximum:
                current["default_value"] = attainment_default
                result.append(current)
                continue
        current_refs = {
            str(ref)
            for ref in (current.get("parameterized_points") or {})
            if str(ref) in visible_refs
        }
        previous_refs = {
            str(ref)
            for ref in (prior.get("parameterized_points") or {})
            if str(ref) in visible_refs
        }
        if current_refs.intersection(previous_refs) and prior.get("default_value") is not None:
            current["default_value"] = copy.deepcopy(prior["default_value"])
        result.append(current)
    return tuple(result)


def _released_interaction_attainment_default(
    *,
    name: str,
    previous: JsonObject,
    visible_refs: set[str],
    geometry_spec: JsonObject,
    parameter_values: Mapping[str, str],
) -> float | None:
    """Snap a released moving-point control to its verified attainment point.

    During an interactive minimum step a point may be overridden by a free
    axis parameter.  A later calculation-only step restores the registry's
    verified attainment coordinates.  Solving the former override against
    those coordinates keeps linked auxiliary points in the same equality
    state instead of retaining an arbitrary slider demonstration value.
    """

    if not name:
        return None
    parameter = sp.Symbol(name)
    try:
        substitutions = {
            sp.Symbol(key): sp.sympify(str(value))
            for key, value in parameter_values.items()
            if key != name
        }
    except Exception:
        return None
    candidates: list[sp.Expr] = []
    for point_ref, payload in (previous.get("parameterized_points") or {}).items():
        if str(point_ref) not in visible_refs or not isinstance(payload, Mapping):
            continue
        previous_pair = sympy_pair(payload.get("expression"))
        current_pair = sympy_pair(_geometry_point_pair(geometry_spec, str(point_ref)))
        if previous_pair is None or current_pair is None:
            continue
        prior = tuple(sp.simplify(value.subs(substitutions)) for value in previous_pair)
        attained = tuple(sp.simplify(value.subs(substitutions)) for value in current_pair)
        if not any(parameter in value.free_symbols for value in prior):
            continue
        if any(parameter in value.free_symbols or value.free_symbols for value in attained):
            continue
        try:
            solutions = sp.solve(
                [sp.Eq(left, right) for left, right in zip(prior, attained, strict=True)],
                [parameter],
                dict=True,
            )
        except Exception:
            continue
        for solution in solutions:
            value = sp.simplify(solution.get(parameter))
            if value is None or value.free_symbols or value.is_real is False:
                continue
            candidates.append(value)
    if not candidates:
        return None
    first = candidates[0]
    if any(sp.simplify(candidate - first) != 0 for candidate in candidates[1:]):
        return None
    try:
        numeric = float(sp.N(first))
    except Exception:
        return None
    return numeric if math.isfinite(numeric) else None


def _interactions_for_visible_objects(
    interactions: tuple[JsonObject, ...],
    objects: tuple[VisualObject, ...],
) -> tuple[JsonObject, ...]:
    """Keep local point overrides inside the complete Frame boundary."""

    visible_refs = {
        ref
        for item in objects
        for ref in item.geometry_refs
    }
    result: list[JsonObject] = []
    for interaction in interactions:
        projected = copy.deepcopy(interaction)
        parameterized = projected.get("parameterized_points")
        if isinstance(parameterized, dict):
            projected["parameterized_points"] = {
                str(ref): payload
                for ref, payload in parameterized.items()
                if str(ref) in visible_refs
            }
        result.append(projected)
    return tuple(result)


def _display_window_with_landmarks(
    window: JsonObject,
    landmarks: tuple[JsonObject, ...],
) -> JsonObject:
    """Ensure every verified landmark is reachable by the local control."""

    values = [
        float(item["value"])
        for item in landmarks
        if isinstance(item.get("value"), (int, float))
        and math.isfinite(float(item["value"]))
    ]
    if not values:
        return window
    original_minimum = float(window["min"])
    original_maximum = float(window["max"])
    candidate_minimum = min(values)
    candidate_maximum = max(values)
    minimum = min(original_minimum, candidate_minimum)
    maximum = max(original_maximum, candidate_maximum)
    span = max(maximum - minimum, 1.0)
    padding = max(float(window["step"]), span * 0.04)
    return {
        "min": round(
            minimum - padding if candidate_minimum < original_minimum else minimum,
            6,
        ),
        "max": round(
            maximum + padding if candidate_maximum > original_maximum else maximum,
            6,
        ),
        "step": window["step"],
    }


def _parameter_domain_and_window(
    name: str,
    snapshot: ExplanationSnapshot,
) -> tuple[JsonObject, JsonObject, float]:
    for fact in (snapshot.problem or {}).get("facts") or ():
        if not isinstance(fact, dict) or fact.get("type") != "symbol_constraint":
            continue
        subject = _handle_tail(str(fact.get("subject") or ""))
        if subject != name:
            continue
        operator = str(fact.get("operator") or "")
        try:
            bound = float(sp.N(sp.sympify(str(fact.get("value")))))
        except Exception:
            break
        if operator in {">", ">="}:
            start = bound if operator == ">=" else bound + 0.1
            end = start + 6.0
            return (
                {"kind": "inequality", "expression": f"{name}{operator}{fact.get('value')}"},
                {"min": round(start, 4), "max": round(end, 4), "step": 0.05},
                round(start + (end - start) / 3, 4),
            )
        if operator in {"<", "<="}:
            end = bound if operator == "<=" else bound - 0.1
            start = end - 6.0
            return (
                {"kind": "inequality", "expression": f"{name}{operator}{fact.get('value')}"},
                {"min": round(start, 4), "max": round(end, 4), "step": 0.05},
                round(start + 2 * (end - start) / 3, 4),
            )
    return (
        {"kind": "real"},
        {"min": -4.0, "max": 4.0, "step": 0.05},
        0.0,
    )


def _visual_frame_caption(
    lesson_step: LessonStep,
    unit_keys: tuple[str, ...],
    frame_index: int,
) -> str:
    del unit_keys
    return lesson_step.nav_title if frame_index == 1 else f"{lesson_step.nav_title}·阶段{frame_index}"


def _geometry_point_pair(
    geometry_spec: JsonObject,
    point_id: str,
) -> list[str] | None:
    pair = (geometry_spec.get("fixedPoints") or {}).get(point_id)
    if pair is None:
        pair = (geometry_spec.get("movingPoints") or {}).get(point_id)
    if isinstance(pair, list) and len(pair) == 2:
        return [str(pair[0]), str(pair[1])]
    return None


def _expression_uses_symbol(expression: str, name: str) -> bool:
    try:
        return sp.Symbol(name) in sp.sympify(str(expression)).free_symbols
    except Exception:
        return False


def _branch_default_parameter_value(
    state: BranchVisualState,
    *,
    geometry_spec: JsonObject,
    snapshot: ExplanationSnapshot,
) -> float:
    """Use the same primary-parameter value as the frame being rendered."""

    name = str(geometry_spec.get("movingParam") or "")
    if name and name in state.parameters:
        try:
            return float(sp.N(sp.sympify(state.parameters[name])))
        except Exception:
            pass
    if name:
        _mathematical_domain, _display_window, default = (
            _parameter_domain_and_window(name, snapshot)
        )
        return default
    return 0.75


def _safe_visual_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "problem"


def _stable_payload_hash(payload: Any) -> str:
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _scene_add_for_lesson_step(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    *,
    coordinate_texts: dict[str, str] | None = None,
) -> list[JsonObject]:
    context = _SceneBuildContext(
        lesson_step=lesson_step,
        bindings=bindings,
        coordinate_texts=coordinate_texts,
        capabilities=frozenset(lesson_step.capability_ids),
        substeps=frozenset(lesson_step.visual_unit_ids),
    )
    add = _scene_items_from_visual_specs(context)
    return _dedupe_scene_items(add)


def _scene_items_from_visual_specs(context: _SceneBuildContext) -> list[JsonObject]:
    template_items = (
        *_method_visual_template_items(context.capabilities, context.bindings),
        *_recipe_visual_template_items(context.capabilities, context.substeps, context.bindings),
    )
    return list(template_items)


def _method_visual_template_items(
    capabilities: set[str],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for capability_id in sorted(capabilities):
        spec = _method_visual_spec(capability_id)
        if spec is None:
            continue
        for template in spec.scene_templates:
            renderer = _METHOD_VISUAL_TEMPLATE_RENDERERS.get(str(template.get("component") or ""))
            if renderer is not None:
                items.extend(
                    renderer(
                        {**template, "_source_capability_id": capability_id},
                        bindings,
                    )
                )
    return items


def _recipe_visual_template_items(
    capabilities: set[str],
    substeps: set[str],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for capability_id in sorted(capabilities):
        spec = _recipe_visual_spec(capability_id)
        if spec is None:
            continue
        visual = spec.visual
        if visual is None:
            continue
        template_keys = sorted(substeps) if substeps else sorted(visual.teaching_substep_templates)
        for substep_id in template_keys:
            for template in visual.teaching_substep_templates.get(substep_id, ()):
                renderer = _RECIPE_VISUAL_TEMPLATE_RENDERERS.get(str(template.get("component") or ""))
                if renderer is not None:
                    items.extend(
                        renderer(
                            {
                                **template,
                                "_source_capability_id": capability_id,
                                "_source_unit_id": substep_id,
                            },
                            bindings,
                        )
                    )
    return items


def _visual_interaction_specs_for_lesson_step(
    lesson_step: LessonStep,
) -> tuple[JsonObject, ...]:
    """Read internal interaction intent from the selected VisualSpec templates.

    A visual component opts into an interaction; capability names, point
    labels and free-symbol names never make a frame interactive by themselves.
    The metadata remains code-side and is not serialized into LessonIR or the
    LLM-facing teaching contracts.
    """

    result: list[JsonObject] = []
    for capability_id, template in _selected_visual_templates(lesson_step):
        raw = template.get("local_interaction")
        if raw is None:
            continue
        if not isinstance(raw, dict) or not str(raw.get("kind") or ""):
            raise ValueError(
                "visual_local_interaction_spec_invalid: "
                f"{capability_id}: {raw!r}"
            )
        record = copy.deepcopy(raw)
        record["source_component"] = str(template.get("component") or "")
        if record not in result:
            result.append(record)
    return tuple(result)


def _selected_visual_templates(
    lesson_step: LessonStep,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Return the exact Method/Recipe templates selected by a Lesson step."""

    result: list[tuple[str, dict[str, Any]]] = []
    for capability_id in sorted(set(lesson_step.capability_ids)):
        method = _method_visual_spec(capability_id)
        if method is not None:
            result.extend(
                (capability_id, template)
                for template in method.scene_templates
            )
            continue
        recipe = _recipe_visual_spec(capability_id)
        visual = recipe.visual if recipe is not None else None
        if visual is None:
            continue
        unit_ids = tuple(lesson_step.visual_unit_ids)
        keys = unit_ids or tuple(sorted(visual.teaching_substep_templates))
        result.extend(
            (capability_id, template)
            for key in keys
            for template in visual.teaching_substep_templates.get(key, ())
        )
    return tuple(result)


def _visual_continuation_policy_for_lesson_step(
    lesson_step: LessonStep,
) -> str:
    """Resolve continuation behavior from code-owned visual specs.

    The generic builder understands only the internal policy vocabulary; it
    never switches on a public Function or Macro id.  Multiple capabilities
    may be merged into one Lesson step, so non-empty policies must agree.
    """

    policies = {
        str(spec.continuation_policy)
        for capability_id in set(lesson_step.capability_ids)
        if (spec := _method_visual_spec(capability_id)) is not None
        and str(spec.continuation_policy)
    }
    if len(policies) > 1:
        raise ValueError(
            "visual_continuation_policy_conflict: "
            f"step={lesson_step.lesson_step_id}, policies={sorted(policies)}"
        )
    return next(iter(policies), "")


def _visual_context_policy_for_lesson_step(
    lesson_step: LessonStep,
) -> _VisualContextPolicy:
    roles: list[tuple[str, JsonObject]] = []
    seen_roles: set[str] = set()
    include_exact_dependencies = False
    dependency_components: set[str] = set()
    all_templates_filter_dependencies = True
    has_template = False
    suppressed_definitions: set[str] = set()

    for capability_id, template in _selected_visual_templates(lesson_step):
        has_template = True
        if template.get("include_exact_dependencies") is not False:
            include_exact_dependencies = True

        raw_components = template.get("dependency_components")
        if raw_components is None:
            all_templates_filter_dependencies = False
        elif not isinstance(raw_components, (list, tuple)):
            raise ValueError(
                "visual_context_dependency_components_invalid: "
                f"{capability_id}: {raw_components!r}"
            )
        else:
            dependency_components.update(str(item) for item in raw_components if str(item))

        raw_suppressed = template.get("suppress_point_definitions_when_exact", ())
        if not isinstance(raw_suppressed, (list, tuple)):
            raise ValueError(
                "visual_context_suppressed_definitions_invalid: "
                f"{capability_id}: {raw_suppressed!r}"
            )
        suppressed_definitions.update(str(item) for item in raw_suppressed if str(item))

        raw_roles = template.get("context_roles", ())
        if not isinstance(raw_roles, (list, tuple)):
            raise ValueError(
                "visual_context_roles_invalid: "
                f"{capability_id}: {raw_roles!r}"
            )
        for raw_role in raw_roles:
            if isinstance(raw_role, str):
                kind = raw_role
                options: JsonObject = {}
            elif isinstance(raw_role, dict):
                kind = str(raw_role.get("kind") or "")
                options = {
                    str(key): copy.deepcopy(value)
                    for key, value in raw_role.items()
                    if key != "kind"
                }
            else:
                raise ValueError(
                    "visual_context_role_invalid: "
                    f"{capability_id}: {raw_role!r}"
                )
            if not kind:
                raise ValueError(
                    "visual_context_role_kind_missing: "
                    f"{capability_id}: {raw_role!r}"
                )
            signature = json.dumps(
                {"kind": kind, **options},
                ensure_ascii=False,
                sort_keys=True,
            )
            if signature in seen_roles:
                continue
            seen_roles.add(signature)
            roles.append((kind, options))

    return _VisualContextPolicy(
        roles=tuple(roles),
        include_exact_dependencies=(
            include_exact_dependencies if has_template else True
        ),
        dependency_components=(
            frozenset(dependency_components)
            if has_template and all_templates_filter_dependencies
            else None
        ),
        suppress_point_definitions_when_exact=frozenset(suppressed_definitions),
    )


def _interaction_constraint_carrier_items(
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    """Render exact constraint geometry required by a local interaction.

    The interaction resolver, not a student-facing label or free-form lesson
    sentence, identifies the mathematical carrier.  This keeps a moving point
    visibly attached to its verified axis/locus without requiring every
    VisualSpec to repeat a per-object visibility flag.
    """

    result: list[JsonObject] = []
    for interaction in interactions:
        carriers = interaction.get("constraint_carriers")
        if carriers is None:
            continue
        if not isinstance(carriers, list):
            raise ValueError(
                "visual_interaction_constraint_carriers_invalid: "
                f"{carriers!r}"
            )
        for carrier in carriers:
            if not isinstance(carrier, dict):
                raise ValueError(
                    "visual_interaction_constraint_carrier_invalid: "
                    f"{carrier!r}"
                )
            kind = str(carrier.get("kind") or "")
            if kind in {"segment", "ray"}:
                start = str(carrier.get("from") or "")
                end = str(carrier.get("to") or "")
                moving_point = str(carrier.get("moving_point") or "")
                if not start or not end or not moving_point:
                    raise ValueError(
                        "visual_interaction_constraint_carrier_endpoints_missing: "
                        f"{carrier!r}"
                    )
                result.append(
                    {
                        "component": "ColoredLine" if kind == "segment" else "DashedLine",
                        "role": f"motion_carrier:{kind}:{moving_point}",
                        "handle": f"motion-carrier:{kind}:{start}-{end}",
                        "from": start,
                        "to": end,
                        "color": COLOR_CONSTRAINT,
                        "width": 1.8,
                        "dash": "" if kind == "segment" else "7 5",
                        "persistence": str(
                            carrier.get("persistence") or "carry_forward"
                        ),
                        "decay_state": "muted",
                        "metadata": {
                            "low_level_type": (
                                "coloredLine" if kind == "segment" else "dashedLine"
                            ),
                            "semantic_source": "interaction_constraint_carrier",
                        },
                    }
                )
                continue
            if kind != "curve_axis":
                raise ValueError(
                    "visual_interaction_constraint_carrier_kind_unknown: "
                    f"{kind or '<empty>'}"
                )
            curve_id = str(carrier.get("curve_id") or "")
            if not curve_id:
                raise ValueError(
                    "visual_interaction_constraint_carrier_curve_missing"
                )
            result.append(
                {
                    "component": "AxisOfSymmetry",
                    "handle": f"axis:{curve_id}",
                    "curveId": curve_id,
                    "color": COLOR_MUTED,
                    "width": 1.5,
                    "dash": "7 6",
                    "persistence": "step_only",
                    "decay_state": "muted",
                    "metadata": {
                        "low_level_type": "axisOfSymmetry",
                        "semantic_source": "interaction_constraint_carrier",
                    },
                }
            )
    return result


def _close_standalone_angle_dependencies(
    scene_items: list[JsonObject],
) -> list[JsonObject]:
    """Keep every standalone angle attached to both defining rays.

    An angle arc is not meaningful geometry by itself.  Its two carrier
    segments inherit the angle's lifetime, so a carried-forward angle can
    never outlive the sides that define it.  Composite angle components own
    their support internally and therefore do not need this projection.
    """

    result = copy.deepcopy(scene_items)
    line_indices: dict[frozenset[str], list[int]] = {}
    for index, item in enumerate(result):
        component = str(item.get("component") or "")
        if component not in {"ColoredLine", "DashedLine", "DistanceMarker"}:
            continue
        start = str(item.get("from") or "")
        end = str(item.get("to") or "")
        if start and end:
            line_indices.setdefault(frozenset((start, end)), []).append(index)

    for item in scene_items:
        if str(item.get("component") or "") not in {"AngleArc", "RightAngle"}:
            continue
        vertex = str(item.get("vertex") or "")
        persistence = str(item.get("persistence") or "carry_forward")
        for ray_key in ("rayA", "rayB"):
            ray = str(item.get(ray_key) or "")
            edge = frozenset((vertex, ray))
            if not vertex or not ray or vertex == ray:
                continue
            existing_indices = line_indices.get(edge, [])
            if existing_indices:
                if persistence != "step_only":
                    support = result[existing_indices[0]]
                    if str(support.get("persistence") or "carry_forward") == "step_only":
                        support["persistence"] = "carry_forward"
                        support.setdefault("decay_state", "muted")
                continue
            line_indices[edge] = [len(result)]
            result.append(
                {
                    "component": "ColoredLine",
                    "role": "angle_support",
                    "handle": f"angle-support:{vertex}-{ray}",
                    "from": vertex,
                    "to": ray,
                    "color": COLOR_MUTED,
                    "width": 1.25,
                    "persistence": persistence,
                    "decay_state": str(item.get("decay_state") or "muted"),
                    "state": "muted",
                    "metadata": {
                        "low_level_type": "coloredLine",
                        "semantic_source": "angle_dependency_closure",
                    },
                }
            )
    return _dedupe_scene_items(result)


@lru_cache(maxsize=1)
def _method_spec_registry() -> MethodSpecRegistry:
    return MethodSpecRegistry.load_from_code()


def _method_visual_spec(method_id: str):
    try:
        return _method_spec_registry().require(method_id).visual
    except KeyError:
        return None


@lru_cache(maxsize=1)
def _recipe_spec_registry() -> RecipeSpecRegistry:
    return RecipeSpecRegistry.load_from_code()


def _recipe_visual_spec(recipe_id: str):
    return _recipe_spec_registry().get(recipe_id)


def _translation_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    source_role = str(template.get("source_role") or "source_point")
    target_role = str(template.get("target_role") or "target_point")
    vector_role = str(template.get("vector_role") or "vector")
    for marker in bindings.translation_markers:
        source = str(marker.get(source_role) or "")
        target = str(marker.get(target_role) or "")
        vector = marker.get(vector_role)
        if not source or not target:
            continue
        items.append(
            {
                "component": "TranslationMarker",
                "source": source,
                "target": target,
                "vector": list(vector) if isinstance(vector, list) else [],
                "label": _translation_label(vector),
                "color": COLOR_CONSTRAINT,
                "width": 1.8,
                "dash": "5 5",
                "dx": 16,
                "dy": -10,
                "persistence": str(template.get("persistence") or "step_only"),
            }
        )
        items.extend(
            _point_with_optional_label_items(
                point=target,
                label=str(marker.get("target_label") or ""),
                display=str(marker.get("target_display") or ""),
                color=COLOR_RESULT,
                persistence=str(template.get("persistence") or "carry_forward"),
                label_dy=-30,
            )
        )
    return items


def _axis_parameterized_point_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    axis_color = str(template.get("axis_color") or COLOR_MUTED)
    point_color = str(template.get("point_color") or COLOR_ACCENT)
    items.extend(_axis_of_symmetry_items(bindings, color=axis_color, persistence=persistence))
    for marker in bindings.axis_parameterized_points:
        point = str(marker.get("point") or "")
        label = str(marker.get("label") or "")
        display = str(marker.get("display") or "")
        if not point:
            continue
        items.extend(
            _point_with_optional_label_items(
                point=point,
                label=label,
                display=display,
                color=point_color,
                persistence=persistence,
                label_dy=-28,
            )
        )
    return items


def _quadratic_axis_x_intercept_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    axis_color = str(template.get("axis_color") or COLOR_MUTED)
    point_color = str(template.get("point_color") or COLOR_RESULT)
    items.extend(_axis_of_symmetry_items(bindings, color=axis_color, persistence=persistence))
    for marker in bindings.axis_x_intercept_points:
        point = str(marker.get("point") or "")
        label = str(marker.get("label") or "")
        display = str(marker.get("display") or "")
        if not point:
            continue
        items.extend(
            _point_with_optional_label_items(
                point=point,
                label=label,
                display=display,
                color=point_color,
                persistence=persistence,
                label_dy=-24,
            )
        )
    return items


def _axis_of_symmetry_items(
    bindings: VisualRoleBindings,
    *,
    color: str,
    persistence: str,
) -> list[JsonObject]:
    return [
        {
            "component": "AxisOfSymmetry",
            "handle": f"axis:{curve_id}",
            "curveId": curve_id,
            "color": color,
            "width": 1.5,
            "dash": "7 6",
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "axisOfSymmetry"},
        }
        for curve_id in bindings.curve_ids
    ]


def _point_with_optional_label_items(
    *,
    point: str,
    label: str,
    display: str,
    color: str,
    persistence: str,
    label_dy: int,
) -> list[JsonObject]:
    items: list[JsonObject] = [
        {
            "component": "Point",
            "handle": f"point:{point}",
            "at": point,
            "labelText": label,
            "color": color,
            "dx": 14,
            "dy": -18,
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "point"},
        }
    ]
    if display:
        items.append(
            {
                "component": "CoordinateLabel",
                "at": point,
                "text": display,
                "dx": 14,
                "dy": label_dy,
                "metadata": {"low_level_type": "coordinateLabel"},
            }
        )
    return items


def _quadratic_vertex_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    axis_persistence = str(template.get("axis_persistence") or persistence)
    vertex_persistence = str(template.get("vertex_persistence") or persistence)
    axis_color = str(template.get("axis_color") or COLOR_MUTED)
    vertex_color = str(template.get("vertex_color") or COLOR_RESULT)
    for curve_id in bindings.curve_ids:
        items.append(
            {
                "component": "AxisOfSymmetry",
                "handle": f"axis:{curve_id}",
                "curveId": curve_id,
                "color": axis_color,
                "width": 1.5,
                "dash": "7 6",
                "persistence": axis_persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "axisOfSymmetry"},
            }
        )
    for marker in bindings.vertex_points:
        point = str(marker.get("point") or "")
        label = str(marker.get("label") or "")
        display = str(marker.get("display") or "")
        if not point:
            continue
        items.append(
            {
                "component": "Point",
                "handle": f"point:{point}",
                "at": point,
                "labelText": label,
                "color": vertex_color,
                "dx": 14,
                "dy": -18,
                "persistence": vertex_persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
        if display:
            items.append(
                {
                    "component": "CoordinateLabel",
                    "at": point,
                    "text": display,
                    "dx": 14,
                    "dy": -34,
                    "metadata": {"low_level_type": "coordinateLabel"},
                }
            )
    return items


def _quadratic_x_axis_intercept_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    point_color = str(template.get("point_color") or COLOR_RESULT)
    context_color = str(template.get("context_color") or COLOR_TEXT)
    target_refs = set(bindings.point_handles.values())
    for marker in bindings.x_axis_intercept_points:
        point = str(marker.get("point") or "")
        label = str(marker.get("label") or "")
        display = str(marker.get("display") or "")
        if not point:
            continue
        is_target = point in target_refs
        items.append(
            {
                "component": "Point",
                "handle": f"point:{point}",
                "at": point,
                "labelText": label,
                "color": point_color if is_target else context_color,
                "dx": 14,
                "dy": -18,
                "persistence": persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
        if display:
            items.append(
                {
                    "component": "CoordinateLabel",
                    "at": point,
                    "text": display,
                    "dx": 14,
                    "dy": -24,
                    "metadata": {"low_level_type": "coordinateLabel"},
                }
            )
    return items


def _square_adjacent_vertex_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    fill = str(template.get("fill") or COLOR_CANDIDATE_REGION_FILL)
    color = str(template.get("color") or COLOR_CANDIDATE_REGION_STROKE)
    edge_color = str(template.get("edge_color") or COLOR_CONSTRAINT)
    target_color = str(template.get("target_color") or COLOR_RESULT)
    context_color = str(template.get("context_color") or COLOR_TEXT)
    for marker in bindings.square_adjacent_markers:
        vertices = [str(point) for point in marker.get("vertices") or () if point]
        labels = [str(label) for label in marker.get("labels") or () if label]
        if len(vertices) != 4 or len(labels) != 4:
            continue
        source_step_id = str(marker.get("source_step_id") or "square")
        items.extend(
            _square_coordinate_triangle_items(
                marker,
                source_step_id,
                fill=str(template.get("coordinate_triangle_fill") or COLOR_COORDINATE_TRIANGLE_FILL),
                color=str(template.get("coordinate_triangle_color") or COLOR_RESULT_REGION_STROKE),
            )
        )
        region_handle = f"visual:square:{source_step_id}:region"
        items.append(
            {
                "component": "OutlineRegion",
                "handle": region_handle,
                "vertices": vertices,
                "fill": fill,
                "color": color,
                "width": 1.2,
                "dash": "",
                "persistence": persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "outlineRegion"},
            }
        )
        for start, end in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
            items.append(
                {
                    "component": "ColoredLine",
                    "handle": f"line:{source_step_id}:{start}-{end}",
                    "from": start,
                    "to": end,
                    "color": edge_color,
                    "width": 2.0,
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "coloredLine"},
                }
            )
        target = str(marker.get("target") or "")
        target_label = str(marker.get("target_label") or "")
        display_labels = [
            str(label)
            for label in marker.get("display_labels", labels)
        ]
        if len(display_labels) != len(labels):
            display_labels = labels
        vertex_displays = (
            marker.get("vertex_displays")
            if isinstance(marker.get("vertex_displays"), dict)
            else {}
        )
        target_display = str(marker.get("target_display") or "")
        for point, label, display_label in zip(vertices, labels, display_labels, strict=True):
            is_target = bool(target and point == target)
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{point}",
                    "at": point,
                    "labelText": display_label,
                    "color": target_color if is_target else context_color,
                    "dx": 14,
                    "dy": 18 if is_target else -18,
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
            display = target_display if is_target and target_display else str(vertex_displays.get(label) or "")
            if is_target and display:
                items.append(
                    {
                        "component": "CoordinateLabel",
                        "at": point,
                        "text": display,
                        "dx": 14,
                        "dy": 34,
                        "metadata": {"low_level_type": "coordinateLabel"},
                    }
                )
        if target_label and target_label not in labels and target:
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{target}",
                    "at": target,
                    "labelText": target_label,
                    "color": target_color,
                    "dx": 14,
                    "dy": 18,
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
        items.extend(_square_right_angle_items(vertices, source_step_id))
    return items


def _curve_point_candidate_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    fill = str(template.get("fill") or COLOR_CANDIDATE_REGION_FILL_SUBTLE)
    color = str(template.get("color") or COLOR_CANDIDATE_REGION_STROKE_SOFT)
    edge_color = str(template.get("edge_color") or COLOR_CONSTRAINT)
    target_color = str(template.get("target_color") or COLOR_RESULT)
    context_color = str(template.get("context_color") or COLOR_TEXT)
    for marker in bindings.curve_point_candidate_markers:
        vertices = [str(point) for point in marker.get("vertices") or () if point]
        labels = [str(label) for label in marker.get("labels") or () if label]
        source_step_id = str(marker.get("source_step_id") or "curve_candidate")
        target = str(marker.get("target") or "")
        target_label = str(marker.get("target_label") or "")
        target_display = str(marker.get("target_display") or "")
        if len(vertices) == 4 and len(labels) == 4:
            items.append(
                {
                    "component": "OutlineRegion",
                    "handle": f"visual:curve_candidate:{source_step_id}:region",
                    "vertices": vertices,
                    "fill": fill,
                    "color": color,
                    "width": 1.2,
                    "dash": "",
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "outlineRegion"},
                }
            )
            for start, end in zip(vertices, (*vertices[1:], vertices[0]), strict=True):
                items.append(
                    {
                        "component": "ColoredLine",
                        "handle": f"line:{source_step_id}:{start}-{end}",
                        "from": start,
                        "to": end,
                        "color": edge_color,
                        "width": 2.0,
                        "persistence": persistence,
                        "decay_state": "muted",
                        "metadata": {"low_level_type": "coloredLine"},
                    }
                )
            display_labels = [
                str(label)
                for label in marker.get("display_labels", labels)
            ]
            if len(display_labels) != len(labels):
                display_labels = labels
            vertex_displays = (
                marker.get("vertex_displays")
                if isinstance(marker.get("vertex_displays"), dict)
                else {}
            )
            for point, label, display_label in zip(vertices, labels, display_labels, strict=True):
                is_target = bool(target and point == target)
                items.append(
                    {
                        "component": "Point",
                        "handle": f"point:{point}",
                        "at": point,
                        "labelText": display_label,
                        "color": target_color if is_target else context_color,
                        "dx": 14,
                        "dy": 18 if is_target else -18,
                        "persistence": persistence,
                        "decay_state": "muted",
                        "metadata": {"low_level_type": "point"},
                    }
                )
                display = target_display if is_target and target_display else str(vertex_displays.get(label) or "")
                if is_target and display:
                    items.append(
                        {
                            "component": "CoordinateLabel",
                            "at": point,
                            "text": display,
                            "dx": 14,
                            "dy": 34,
                            "metadata": {"low_level_type": "coordinateLabel"},
                        }
                    )
            continue
        if target:
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{target}",
                    "at": target,
                    "labelText": target_label,
                    "color": target_color,
                    "dx": 14,
                    "dy": 18,
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
            if target_display:
                items.append(
                    {
                        "component": "CoordinateLabel",
                        "at": target,
                        "text": target_display,
                        "dx": 14,
                        "dy": 34,
                        "metadata": {"low_level_type": "coordinateLabel"},
                    }
                )
    return items


def _atomic_square_path_reduction_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    square_fill = str(template.get("square_fill") or COLOR_CONSTRAINT_REGION_FILL)
    square_color = str(template.get("square_color") or COLOR_CONSTRAINT_REGION_STROKE)
    right_fill = str(template.get("right_triangle_fill") or COLOR_CANDIDATE_REGION_FILL)
    midline_fill = str(template.get("midline_triangle_fill") or COLOR_RESULT_REGION_FILL)
    half_color = str(template.get("half_segment_color") or "#7c3aed")
    path_color = str(template.get("path_segment_color") or COLOR_ACCENT)
    replacement_color = str(template.get("replacement_color") or COLOR_RESULT)
    show_half_segment_labels = bool(template.get("show_half_segment_labels", False))
    for marker in bindings.atomic_square_reduction_markers:
        marker_start = len(items)
        square_outline = [
            str(point)
            for point in marker.get("square_outline") or ()
            if point
        ]
        if len(square_outline) >= 4:
            items.append(
                {
                    "component": "OutlineRegion",
                    "handle": f"visual:square-path:square-outline:{'-'.join(square_outline)}",
                    "vertices": square_outline,
                    "fill": square_fill,
                    "color": square_color,
                    "width": 1.5,
                    "dash": "",
                    "persistence": "step_only",
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "outlineRegion"},
                }
            )
        for triangle in marker.get("triangles") or ():
            if not isinstance(triangle, dict):
                continue
            vertices = [str(point) for point in triangle.get("vertices") or () if point]
            if len(vertices) != 3:
                continue
            role = str(triangle.get("role") or "")
            items.append(
                {
                    "component": "OutlineRegion",
                    "handle": f"visual:square-path:{role}:{'-'.join(vertices)}",
                    "vertices": vertices,
                    "fill": right_fill if role == "right_triangle" else midline_fill,
                    "color": COLOR_CANDIDATE_REGION_STROKE_MUTED if role == "right_triangle" else COLOR_RESULT_REGION_STROKE,
                    "width": 1.2,
                    "dash": "",
                    "persistence": "step_only",
                    "metadata": {"low_level_type": "outlineRegion"},
                }
            )
        segments = marker.get("segments") if isinstance(marker.get("segments"), dict) else {}
        items.extend(_square_path_line_items(segments.get("center_midpoint"), color=half_color, persistence="step_only"))
        items.extend(_square_path_line_items(segments.get("midpoint_fixed"), color=half_color, persistence="step_only"))
        items.extend(_square_path_line_items(segments.get("fixed_moving"), color=path_color, persistence=persistence))
        items.extend(_square_path_line_items(segments.get("replacement"), color=replacement_color, persistence=persistence, width=2.4))
        if show_half_segment_labels:
            relations = marker.get("relations") if isinstance(marker.get("relations"), dict) else {}
            items.extend(
                _distance_marker_from_segment_payload(
                    _segment_with_label(segments.get("center_midpoint"), str(relations.get("center_midpoint_half") or "")),
                    color=half_color,
                    offset_px=16,
                )
            )
            items.extend(
                _distance_marker_from_segment_payload(
                    _segment_with_label(segments.get("midpoint_fixed"), str(relations.get("midpoint_fixed_half") or "")),
                    color=half_color,
                    offset_px=-16,
                )
            )
        refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        side_start = str(roles.get("side_start") or "")
        side_end = str(roles.get("side_end") or "")
        other_fixed = str(roles.get("other_fixed") or "")
        if side_start and side_end and other_fixed:
            vertex = str(refs.get(other_fixed) or "")
            ray_a = str(refs.get(side_start) or "")
            ray_b = str(refs.get(side_end) or "")
            if vertex and ray_a and ray_b:
                items.append(
                    {
                        "component": "RightAngle",
                        "handle": f"right-angle:square-path:{vertex}",
                        "vertex": vertex,
                        "rayA": ray_a,
                        "rayB": ray_b,
                        "size": 10,
                        "color": COLOR_CONSTRAINT,
                        "persistence": "step_only",
                        "metadata": {"low_level_type": "rightAngle"},
                    }
                )
        point_roles = marker.get("point_labels") if isinstance(marker.get("point_labels"), list) else []
        for point_role in point_roles:
            if not isinstance(point_role, dict):
                continue
            label = str(point_role.get("label") or "")
            point = str(refs.get(label) or "")
            if not label or not point:
                continue
            role = str(point_role.get("role") or "")
            point_persistence = persistence if role == "moving_vertex" else "step_only"
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{point}",
                    "at": point,
                    "labelText": label,
                    "color": COLOR_RESULT if role == "moving_vertex" else COLOR_TEXT,
                    "dx": 14,
                    "dy": 18 if role == "moving_vertex" else -18,
                    "persistence": point_persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
        items.extend(
            _missing_semantic_role_point_items(
                items[marker_start:],
                marker,
                default_persistence="step_only",
                persistent_roles={"moving_vertex": persistence},
            )
        )
        _assert_semantic_visual_closure(
            component="AtomicSquarePathReductionMarker",
            marker=marker,
            rendered_items=items[marker_start:],
            required_segments=tuple(
                segments.get(key)
                for key in (
                    "center_midpoint",
                    "midpoint_fixed",
                    "fixed_moving",
                    "replacement",
                )
            ),
        )
    return items


def _square_path_line_items(
    segment: Any,
    *,
    color: str,
    persistence: str,
    width: float = 2.0,
) -> list[JsonObject]:
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    if not start or not end:
        return []
    return [
        {
            "component": "ColoredLine",
            "handle": _line_handle(segment),
            "from": start,
            "to": end,
            "color": color,
            "width": width,
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "coloredLine"},
        }
    ]


def _segment_with_label(segment: Any, label: str) -> JsonObject:
    if not isinstance(segment, dict):
        return {}
    out = dict(segment)
    if label:
        out["label"] = label
    return out


def _square_coordinate_triangle_items(
    marker: dict[str, Any],
    source_step_id: str,
    *,
    fill: str,
    color: str,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for index, raw in enumerate(marker.get("coordinate_triangles") or ()):
        if not isinstance(raw, dict):
            continue
        vertices = [str(point) for point in raw.get("vertices") or () if point]
        if len(vertices) != 3:
            continue
        handle = str(raw.get("handle") or f"visual:square-coordinate:{source_step_id}:{index}")
        items.append(
            {
                "component": "OutlineRegion",
                "handle": handle,
                "vertices": vertices,
                "fill": fill,
                "color": color,
                "width": 1.0,
                "dash": "4 4",
                "persistence": "step_only",
                "metadata": {"low_level_type": "outlineRegion"},
            }
        )
        projection = str(raw.get("projection") or "")
        projection_target = str(raw.get("projection_target") or "")
        if projection and projection_target:
            items.append(
                {
                    "component": "DashedLine",
                    "handle": f"line:{source_step_id}:projection:{projection}-{projection_target}",
                    "from": projection,
                    "to": projection_target,
                    "color": color,
                    "width": 1.2,
                    "dash": "4 5",
                    "persistence": "step_only",
                    "metadata": {"low_level_type": "dashedLine"},
                }
            )
        projection_label = str(raw.get("projection_label") or "")
        if projection and projection_label and raw.get("projection_is_helper"):
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{projection}",
                    "at": projection,
                    "labelText": projection_label,
                    "color": COLOR_MUTED,
                    "dx": 12,
                    "dy": -12,
                    "persistence": "step_only",
                    "metadata": {"low_level_type": "point"},
                }
            )
        right_angle = raw.get("right_angle")
        if isinstance(right_angle, dict):
            vertex = str(right_angle.get("vertex") or "")
            ray_a = str(right_angle.get("rayA") or "")
            ray_b = str(right_angle.get("rayB") or "")
            if vertex and ray_a and ray_b:
                items.append(
                    {
                        "component": "RightAngle",
                        "handle": f"right-angle:{source_step_id}:coordinate:{index}",
                        "vertex": vertex,
                        "rayA": ray_a,
                        "rayB": ray_b,
                        "size": 8,
                        "color": color,
                        "persistence": "step_only",
                        "metadata": {"low_level_type": "rightAngle"},
                    }
                )
    return items


def _square_right_angle_items(vertices: list[str], source_step_id: str) -> list[JsonObject]:
    if len(vertices) != 4:
        return []
    specs = (
        (vertices[0], vertices[1], vertices[3]),
        (vertices[1], vertices[0], vertices[2]),
    )
    return [
        {
            "component": "RightAngle",
            "handle": f"right-angle:{source_step_id}:{vertex}",
            "vertex": vertex,
            "rayA": ray_a,
            "rayB": ray_b,
            "size": 10,
            "color": COLOR_CONSTRAINT,
            "persistence": "step_only",
            "metadata": {"low_level_type": "rightAngle"},
        }
        for vertex, ray_a, ray_b in specs
    ]


def _congruent_triangle_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        triangles = [
            dict(triangle)
            for triangle in marker.get("triangles") or ()
            if isinstance(triangle, dict)
        ]
        if triangles:
            items.append(
                {
                    "component": "CongruentTriangleMarker",
                    "triangles": triangles,
                    "fill": str(template.get("fill") or COLOR_CANDIDATE_REGION_FILL_FAINT),
                    "color": str(template.get("color") or COLOR_CANDIDATE_REGION_STROKE_FAINT),
                    "width": float(template.get("width") or 1.0),
                    "dash": str(template.get("dash") or ""),
                    "state": "muted",
                    "persistence": "step_only",
                }
            )
        for line in marker.get("path_lines") or ():
            if isinstance(line, dict):
                items.append(
                    {
                        "component": "ColoredLine",
                        "handle": _line_handle(line),
                        "from": line.get("from"),
                        "to": line.get("to"),
                        "color": COLOR_PATH,
                        "width": 2.2,
                        "persistence": "carry_forward",
                        "decay_state": "muted",
                        "metadata": {"low_level_type": "coloredLine"},
                    }
                )
        for line in marker.get("guide_lines") or ():
            if not isinstance(line, dict):
                continue
            component = "DashedLine" if line.get("style") == "dashed" else "ColoredLine"
            carry = line.get("role") == "anchor_to_auxiliary"
            item: JsonObject = {
                "component": component,
                "from": line.get("from"),
                "to": line.get("to"),
                "color": COLOR_MUTED if component == "DashedLine" else COLOR_CONSTRAINT,
                "width": 1.35 if component == "DashedLine" else 2.0,
                "dash": "5 6",
                "persistence": "carry_forward" if carry else "step_only",
                "metadata": {
                    "low_level_type": "dashedLine" if component == "DashedLine" else "coloredLine"
                },
            }
            if carry:
                item["handle"] = _line_handle(line)
                item["decay_state"] = "muted"
            items.append(item)
        for raw_label in marker.get("point_labels") or ():
            if isinstance(raw_label, dict):
                label = str(raw_label.get("label") or "")
                role = str(raw_label.get("role") or "")
            else:
                label = str(raw_label)
                role = ""
            point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
            point = bindings.point_handles.get(label) or point_refs.get(label)
            if not point:
                continue
            style = _point_style_for_role(role)
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{point}",
                    "at": point,
                    "labelText": label,
                    "color": style.color,
                    "dx": style.dx,
                    "dy": style.dy,
                    "persistence": "carry_forward",
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
    return items


def _point_style_for_role(role: str) -> _PointVisualStyle:
    if role in {"locus_start_point", "locus_end_point"}:
        return POINT_CONTEXT
    if role == "auxiliary_point":
        return POINT_AUXILIARY
    if role in {"result_point", "reflected_point"}:
        return POINT_RESULT
    if role in {"moving_point", "moving_vertex"}:
        return POINT_MOVING
    return POINT_ACTIVE


def _missing_semantic_role_point_items(
    rendered_items: list[JsonObject],
    marker: JsonObject,
    *,
    default_persistence: str,
    persistent_roles: dict[str, str] | None = None,
) -> list[JsonObject]:
    """Close a component's exact semantic point graph.

    A marker's role binder is the authority for both the student-facing role
    and the branch-scoped geometry identity.  Every declared point role must
    therefore have a visible Point component.  Deduplication is performed by
    the exact geometry ref, never by a point label or stringified coordinate.
    """

    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    refs = (
        marker.get("role_point_refs")
        if isinstance(marker.get("role_point_refs"), dict)
        else {}
    )
    display_labels = (
        marker.get("display_labels")
        if isinstance(marker.get("display_labels"), dict)
        else {}
    )
    existing_refs = {
        str(item.get("at") or "")
        for item in rendered_items
        if isinstance(item, dict) and item.get("component") == "Point"
    }
    result: list[JsonObject] = []
    for role, raw_label in roles.items():
        label = str(raw_label or "")
        point_ref = str(refs.get(label) or "")
        if not label or not point_ref:
            raise ValueError(
                "visual_semantic_point_role_unresolved: "
                f"{role}: label={label!r}, ref={point_ref!r}"
            )
        if point_ref in existing_refs:
            continue
        style = _point_style_for_role(str(role))
        persistence = (persistent_roles or {}).get(
            str(role),
            default_persistence,
        )
        result.append(
            {
                "component": "Point",
                "handle": f"point:{point_ref}",
                "at": point_ref,
                "labelText": str(display_labels.get(label) or label),
                "color": style.color,
                "dx": style.dx,
                "dy": style.dy,
                "persistence": persistence,
                "decay_state": "muted",
                "metadata": {
                    "low_level_type": "point",
                    "semantic_role": str(role),
                },
            }
        )
        existing_refs.add(point_ref)
    return result


def _assert_semantic_visual_closure(
    *,
    component: str,
    marker: JsonObject,
    rendered_items: list[JsonObject],
    required_segments: tuple[Any, ...],
) -> None:
    """Fail loudly if a semantic component silently drops a point or edge."""

    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    refs = (
        marker.get("role_point_refs")
        if isinstance(marker.get("role_point_refs"), dict)
        else {}
    )
    expected_points = {
        str(refs.get(str(label)) or "")
        for label in roles.values()
        if str(label or "")
    }
    expected_points.discard("")
    rendered_points = {
        str(item.get("at") or "")
        for item in rendered_items
        if isinstance(item, dict) and item.get("component") == "Point"
    }
    missing_points = sorted(expected_points - rendered_points)

    rendered_edges = {
        frozenset((str(item.get("from") or ""), str(item.get("to") or "")))
        for item in rendered_items
        if isinstance(item, dict)
        and item.get("component") in {"ColoredLine", "DashedLine"}
        and item.get("from")
        and item.get("to")
    }
    missing_edges: list[tuple[str, str]] = []
    for segment in required_segments:
        if not isinstance(segment, dict):
            raise ValueError(
                "visual_semantic_segment_unresolved: "
                f"{component}: {segment!r}"
            )
        start = str(segment.get("from") or "")
        end = str(segment.get("to") or "")
        if not start or not end:
            raise ValueError(
                "visual_semantic_segment_unresolved: "
                f"{component}: {segment!r}"
            )
        if frozenset((start, end)) not in rendered_edges:
            missing_edges.append((start, end))

    if missing_points or missing_edges:
        raise ValueError(
            "visual_semantic_closure_incomplete: "
            f"{component}: points={missing_points!r}, edges={missing_edges!r}"
        )


def _equivalent_segment_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        if marker.get("kind") == "coupled_endpoint_replacement":
            items.extend(
                _coupled_endpoint_replacement_marker_items(template, marker)
            )
            continue
        segments = [
            dict(segment)
            for segment in marker.get("equivalent_segments") or ()
            if isinstance(segment, dict)
        ]
        if len(segments) < 2:
            continue
        items.append(
            {
                "component": "EquivalentSegmentMarker",
                "segments": segments,
                "label": str(template.get("label") or marker.get("equivalence_label") or ""),
                "color": str(template.get("color") or COLOR_ACCENT),
                "width": float(template.get("width") or 2.25),
                "dx": int(template.get("dx") or 12),
                "dy": int(template.get("dy") or -16),
                "persistence": "step_only",
            }
        )
    return items


def _coupled_endpoint_replacement_marker_items(
    template: dict[str, Any],
    marker: dict[str, Any],
) -> list[JsonObject]:
    """Render the certificate that turns ``EG`` into the equal segment ``DG``."""

    persistence = str(template.get("persistence") or "step_only")
    labels = marker.get("labels") if isinstance(marker.get("labels"), dict) else {}
    refs = marker.get("refs") if isinstance(marker.get("refs"), dict) else {}
    required_roles = {
        "anchor",
        "first_vertex",
        "second_vertex",
        "first_leg_moving",
        "moving",
        "first_projection",
        "second_projection",
        "other_fixed",
    }
    if not required_roles.issubset(refs):
        raise ValueError(
            "visual_endpoint_replacement_marker_roles_missing: "
            f"{sorted(required_roles - set(refs))}"
        )
    items: list[JsonObject] = [
        {
            "component": "OutlineRegion",
            "vertices": list(marker.get("projection_rectangle") or ()),
            "fill": COLOR_RESULT_REGION_FILL,
            "color": COLOR_RESULT_REGION_STROKE,
            "width": 1.8,
            "persistence": persistence,
            "metadata": {"low_level_type": "outlineRegion"},
        }
    ]
    for start_role, end_role, role in (
        ("anchor", "first_vertex", "endpoint_frame:first_leg"),
        ("anchor", "second_vertex", "endpoint_frame:second_leg"),
        ("first_vertex", "second_vertex", "endpoint_frame:hypotenuse"),
    ):
        line = _line_item(
            str(refs[start_role]),
            str(refs[end_role]),
            color=COLOR_MUTED,
            width=1.8,
            persistence=persistence,
            role=role,
        )
        if line is not None:
            items.append(line)
    for projection_role in ("first_projection", "second_projection"):
        line = _line_item(
            str(refs["moving"]),
            str(refs[projection_role]),
            color=COLOR_CONSTRAINT,
            width=1.7,
            persistence=persistence,
            dash="5 5",
            role=f"endpoint_frame:{projection_role}",
        )
        if line is not None:
            items.append(line)
        items.append(
            {
                "component": "RightAngle",
                "vertex": str(refs[projection_role]),
                "rayA": str(refs["anchor"]),
                "rayB": str(refs["moving"]),
                "color": COLOR_CONSTRAINT,
                "size": 8,
                "persistence": persistence,
                "metadata": {"low_level_type": "rightAngle"},
            }
        )
    segments = [
        dict(segment)
        for segment in marker.get("equivalent_segments") or ()
        if isinstance(segment, dict)
    ]
    if len(segments) == 2:
        items.append(
            {
                "component": "EquivalentSegmentMarker",
                "segments": segments,
                "label": str(marker.get("equivalence_label") or ""),
                "color": COLOR_ACCENT,
                "width": 2.5,
                "dx": 12,
                "dy": -16,
                "persistence": persistence,
            }
        )
    common_path = marker.get("common_path_segment")
    items.extend(
        _line_from_segment_payload(
            common_path,
            color=COLOR_PATH,
            width=2.5,
            persistence=persistence,
        )
    )
    for role in (
        "anchor",
        "first_vertex",
        "second_vertex",
        "first_leg_moving",
        "moving",
        "first_projection",
        "second_projection",
        "other_fixed",
    ):
        color = (
            COLOR_RESULT
            if role in {"first_leg_moving", "moving"}
            else COLOR_MUTED
        )
        items.extend(
            _point_with_optional_label_items(
                point=str(refs[role]),
                label=str(labels.get(role) or ""),
                display="",
                color=color,
                persistence=persistence,
                label_dy=-24,
            )
        )
    return items


def _path_minimum_triangle_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        point_refs = (
            marker.get("role_point_refs")
            if isinstance(marker.get("role_point_refs"), dict)
            else {}
        )
        vertices = [
            point_refs.get(str(roles.get("fixed_point") or "")),
            point_refs.get(str(roles.get("segment_moving_point") or "")),
            point_refs.get(str(roles.get("auxiliary_point") or "")),
        ]
        if not all(vertices):
            continue
        items.append(
            {
                "component": "OutlineRegion",
                "handle": f"visual:path_minimum_triangle:{'-'.join(str(vertex) for vertex in vertices)}",
                "vertices": vertices,
                "fill": str(template.get("fill") or COLOR_RESULT_REGION_FILL),
                "color": str(template.get("color") or COLOR_RESULT_REGION_STROKE_FAINT),
                "width": float(template.get("width") or 1.0),
                "dash": str(template.get("dash") or ""),
                "persistence": "step_only",
                "metadata": {"low_level_type": "outlineRegion"},
            }
        )
        minimum_segment = marker.get("minimum_segment")
        items.extend(
            _line_from_segment_payload(
                minimum_segment,
                color=COLOR_RESULT,
                width=2.8,
            )
        )
        items.extend(
            _distance_marker_from_segment_payload(
                minimum_segment,
                color=COLOR_RESULT,
                width=2.8,
            )
        )
        if isinstance(minimum_segment, dict):
            auxiliary_ref = str(minimum_segment.get("to") or "")
            if auxiliary_ref:
                items.extend(
                    _bound_point_items_for_refs(
                        bindings,
                        {auxiliary_ref},
                        style=POINT_AUXILIARY,
                    )
                )
    return items


def _auxiliary_ray_guide_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        for line in marker.get("guide_lines") or ():
            if not isinstance(line, dict) or line.get("role") != "anchor_to_auxiliary":
                continue
            items.append(
                {
                    "component": "ColoredLine",
                    "handle": _line_handle(line),
                    "from": line.get("from"),
                    "to": line.get("to"),
                    "color": str(template.get("color") or COLOR_CONSTRAINT),
                    "width": float(template.get("width") or 2.0),
                    "dash": str(template.get("dash") or "5 6"),
                    "persistence": "carry_forward",
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "coloredLine"},
                }
            )
    return items


def _atomic_path_minimum_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    locus_color = str(template.get("locus_color") or COLOR_CONSTRAINT)
    reflected_color = str(template.get("reflected_color") or COLOR_RESULT)
    path_color = str(template.get("path_color") or COLOR_PATH)
    triangle_fill = str(template.get("triangle_fill") or COLOR_RESULT_REGION_FILL)
    for marker in bindings.atomic_path_minimum_markers:
        marker_start = len(items)
        is_coupled = (
            marker.get("construction_kind")
            == "coupled_segment_endpoint_replacement"
        )
        if marker.get("construction_kind") == "weighted_right_triangle":
            items.extend(
                _weighted_path_minimum_marker_items(
                    template,
                    marker,
                    persistence=persistence,
                    path_color=path_color,
                    auxiliary_color=reflected_color,
                    triangle_fill=triangle_fill,
                )
            )
            continue
        locus = marker.get("locus_line") if isinstance(marker.get("locus_line"), dict) else {}
        locus_from = str(locus.get("from") or "")
        locus_to = str(locus.get("to") or "")
        if locus_from and locus_to:
            items.append(
                {
                    "component": "LocusLine",
                    "role": "locus:line",
                    "handle": f"line:broken-path:locus:{locus_from}-{locus_to}",
                    "from": locus_from,
                    "to": locus_to,
                    "color": locus_color,
                    "width": 2.0,
                    "dash": "7 5",
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "dashedLine"},
                }
            )
            label = str(locus.get("label") or "")
            if label:
                items.append(
                    {
                        "component": "CoordinateLabel",
                        "role": "locus:label",
                        "at": locus_to,
                        "text": label,
                        "dx": -170,
                        "dy": -14,
                        "metadata": {"low_level_type": "coordinateLabel"},
                    }
                )

        point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
        display_labels = marker.get("display_labels") if isinstance(marker.get("display_labels"), dict) else {}
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        reflected_label = str(roles.get("reflected_point") or "")
        moving_label = str(roles.get("moving_point") or "")
        other_label = str(roles.get("other_fixed_point") or "")
        triangle_vertices = [
            str(point_refs.get(other_label) or ""),
            str(point_refs.get(reflected_label) or ""),
            str(point_refs.get(moving_label) or ""),
        ]
        if all(triangle_vertices) and len(set(triangle_vertices)) == 3:
            items.append(
                {
                    "component": "OutlineRegion",
                    "handle": f"region:broken-path:{'-'.join(triangle_vertices)}",
                    "vertices": triangle_vertices,
                    "fill": triangle_fill,
                    "color": reflected_color,
                    "width": 1.0,
                    "persistence": "step_only",
                    "metadata": {"low_level_type": "outlineRegion"},
                }
            )

        straightened_pairs = {
            frozenset(
                (
                    str(segment.get("from") or ""),
                    str(segment.get("to") or ""),
                )
            )
            for segment in marker.get("straightened_segments") or ()
            if isinstance(segment, dict)
            and segment.get("from")
            and segment.get("to")
        }
        for segment in marker.get("original_segments") or ():
            segment_pair = (
                frozenset(
                    (
                        str(segment.get("from") or ""),
                        str(segment.get("to") or ""),
                    )
                )
                if isinstance(segment, dict)
                else frozenset()
            )
            is_common_result_segment = is_coupled and segment_pair in straightened_pairs
            items.extend(
                _line_from_segment_payload(
                    segment,
                    color=path_color,
                    width=2.0,
                    persistence=persistence,
                    role=(
                        "path_result:common_segment"
                        if is_common_result_segment
                        else "path_construction:original_segment"
                        if is_coupled
                        else ""
                    ),
                )
            )

        reflection_segment = marker.get("reflection_segment")
        items.extend(
            _dashed_line_from_segment_payload(
                reflection_segment,
                color=reflected_color,
                width=2.2,
                role=(
                    "path_result:straightened_segment"
                    if is_coupled
                    else ""
                ),
            )
        )
        equality = str(marker.get("segment_equality") or "")
        if equality:
            items.extend(
                _distance_marker_from_segment_payload(
                    _segment_with_label(reflection_segment, equality),
                    color=reflected_color,
                    width=2.2,
                    offset_px=-18,
                    persistence=persistence,
                )
            )

        minimum_segment = marker.get("minimum_segment")
        items.extend(
            _line_from_segment_payload(
                minimum_segment,
                color=reflected_color,
                width=2.8,
                role="path_result:minimum_segment" if is_coupled else "",
            )
        )
        items.extend(
            _distance_marker_from_segment_payload(
                minimum_segment,
                color=reflected_color,
                width=2.8,
                offset_px=16,
                persistence=persistence,
            )
        )

        reflected_ref = str(point_refs.get(reflected_label) or "")
        if reflected_ref:
            display_label = str(display_labels.get(reflected_label) or reflected_label)
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{reflected_ref}",
                    "at": reflected_ref,
                    "labelText": display_label,
                    "role": (
                        "path_result:reflected_point"
                        if is_coupled
                        else ""
                    ),
                    "color": reflected_color,
                    "dx": 14,
                    "dy": 18,
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
            reflected_display = str(marker.get("reflected_display") or "")
            if reflected_display:
                items.append(
                    {
                        "component": "CoordinateLabel",
                        "at": reflected_ref,
                        "text": reflected_display,
                        "dx": 14,
                        "dy": 34,
                        "metadata": {"low_level_type": "coordinateLabel"},
                    }
                )
        missing_points = _missing_semantic_role_point_items(
            items[marker_start:],
            marker,
            default_persistence=persistence,
        )
        if is_coupled:
            for point in missing_points:
                semantic_role = str(
                    (point.get("metadata") or {}).get("semantic_role") or ""
                )
                point["role"] = (
                    f"path_result:{semantic_role}"
                    if semantic_role in {"moving_point", "other_fixed_point"}
                    else f"path_construction:{semantic_role}"
                )
        items.extend(missing_points)
        _assert_semantic_visual_closure(
            component="AtomicPathMinimumMarker",
            marker=marker,
            rendered_items=items[marker_start:],
            required_segments=(
                *tuple(marker.get("original_segments") or ()),
                marker.get("reflection_segment"),
                marker.get("minimum_segment"),
            ),
        )
    return items


def _weighted_path_minimum_marker_items(
    template: dict[str, Any],
    marker: dict[str, Any],
    *,
    persistence: str,
    path_color: str,
    auxiliary_color: str,
    triangle_fill: str,
) -> list[JsonObject]:
    """Render a weighted path from its public witness-bound point roles."""

    items: list[JsonObject] = []
    refs = (
        marker.get("role_point_refs")
        if isinstance(marker.get("role_point_refs"), dict)
        else {}
    )
    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    moving_label = str(roles.get("moving_point") or "")
    auxiliary_label = str(roles.get("auxiliary_point") or "")
    moving_ref = str(refs.get(moving_label) or "")
    auxiliary_ref = str(refs.get(auxiliary_label) or "")
    vertices = [
        str(item) for item in marker.get("triangle_outline") or () if str(item)
    ]
    if len(vertices) == 3 and len(set(vertices)) == 3:
        items.append(
            {
                "component": "OutlineRegion",
                "handle": f"region:weighted-path:{'-'.join(vertices)}",
                "vertices": vertices,
                "fill": triangle_fill,
                "color": auxiliary_color,
                "width": 1.2,
                "persistence": "step_only",
                "metadata": {"low_level_type": "outlineRegion"},
            }
        )

    unit_id = str(template.get("_source_unit_id") or "")
    segments_key = (
        "reduced_segments" if unit_id == "domain_minimum" else "original_segments"
    )
    for segment in marker.get(segments_key) or ():
        items.extend(
            _line_from_segment_payload(
                segment,
                color=path_color,
                width=2.4,
            )
        )
    if unit_id == "domain_minimum":
        items.extend(
            _line_from_segment_payload(
                marker.get("auxiliary_locus_segment"),
                color=auxiliary_color,
                width=1.8,
            )
        )
        items.extend(
            _dashed_line_from_segment_payload(
                marker.get("minimum_segment"),
                color=auxiliary_color,
                width=1.8,
            )
        )
    relation = marker.get("weighted_relation")
    items.extend(
        _distance_marker_from_segment_payload(
            relation,
            color=auxiliary_color,
            width=2.0,
            offset_px=18,
            persistence="step_only",
        )
    )
    for label, geometry_ref, dy in (
        (moving_label, moving_ref, 18),
        (auxiliary_label, auxiliary_ref, -18),
    ):
        if not label or not geometry_ref:
            continue
        items.append(
            {
                "component": "Point",
                "handle": f"point:{geometry_ref}",
                "at": geometry_ref,
                "labelText": label,
                "color": auxiliary_color,
                "dx": 14,
                "dy": dy,
                "persistence": persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
    return items


def _angle_equality_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.angle_equalities:
        angles = marker.get("angles")
        if not isinstance(angles, list) or len(angles) < 2:
            continue
        items.append(
            {
                "component": "AngleEqualityMarker",
                "angles": [dict(angle) for angle in angles if isinstance(angle, dict)],
                "guide_arms": [
                    _angle_guide_arm_payload(guide)
                    for guide in marker.get("guide_arms") or ()
                    if isinstance(guide, dict)
                ],
                "guide_only_refs": list(marker.get("guide_only_refs") or ()),
                "label": str(template.get("label") or "α"),
                "color": COLOR_PATH,
                "guideColor": COLOR_MUTED,
                "radius": 34,
                "labelRadius": 48,
                "guideWidth": 1.25,
                "guideDash": "4 7",
                "state": "muted",
                "persistence": "step_only",
            }
        )
        items.extend(_carry_forward_angle_guide_arm_items(marker))
    return items


def _carry_forward_angle_guide_arm_items(marker: JsonObject) -> list[JsonObject]:
    out: list[JsonObject] = []
    for guide in marker.get("guide_arms") or ():
        if not isinstance(guide, dict):
            continue
        handle = str(guide.get("handle") or "")
        start = str(guide.get("from") or "")
        end = str(guide.get("to") or "")
        if not handle or not start or not end:
            continue
        out.append(
            {
                "component": "DashedLine",
                "handle": handle,
                "from": start,
                "to": end,
                "color": COLOR_MUTED,
                "width": 1.25,
                "dash": "4 7",
                "state": "muted",
                "persistence": "carry_forward",
                "decay_state": "muted",
                "metadata": {"low_level_type": "dashedLine"},
            }
        )
    return out


def _angle_reference_items(
    bindings: VisualRoleBindings,
    *,
    show_reference_triangle: bool = False,
) -> list[JsonObject]:
    out: list[JsonObject] = []
    for marker in bindings.angle_references:
        vertices = [
            str(marker.get("rayA") or ""),
            str(marker.get("vertex") or ""),
            str(marker.get("rayB") or ""),
        ]
        if show_reference_triangle and all(vertices) and len(set(vertices)) == 3:
            out.append(
                {
                    "component": "OutlineRegion",
                    "vertices": vertices,
                    "fill": COLOR_COORDINATE_TRIANGLE_FILL,
                    "color": COLOR_CONSTRAINT,
                    "width": 1.8,
                    "dash": "",
                    "state": "muted",
                    "persistence": "step_only",
                    "metadata": {"low_level_type": "outlineRegion"},
                }
            )
        item: JsonObject = {
            "component": "AngleArc",
            "vertex": marker.get("vertex"),
            "rayA": marker.get("rayA"),
            "rayB": marker.get("rayB"),
            "color": COLOR_CONSTRAINT,
            "radius": 43,
            "metadata": {"low_level_type": "angleArc"},
        }
        value = str(marker.get("value") or "")
        if value:
            item["label"] = value
            item["labelRadius"] = 60
        out.append(item)
    return out


def _angle_equality_template_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    marker_items = _angle_equality_marker_items(template, bindings)
    refs = _point_marker_refs_from_scene_items(tuple(marker_items))
    return [
        *marker_items,
        *_angle_reference_items(
            bindings,
            show_reference_triangle=True,
        ),
        *_bound_point_items_for_refs(bindings, refs, style=POINT_ACTIVE),
        *_bound_coordinate_items_for_refs(bindings, refs),
    ]


def _equal_acute_angle_intercept_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    show_angles = bool(template.get("show_angles", True))
    show_right_angles = bool(template.get("show_right_angles", True))
    for marker in bindings.axis_intercept_markers:
        triangle_regions: list[JsonObject] = []
        lines: list[JsonObject] = []
        angles: list[JsonObject] = []
        right_angles: list[JsonObject] = []
        for equality in marker.get("angle_equalities") or ():
            if not isinstance(equality, dict):
                continue
            target_angle = str(equality.get("left_angle") or "")
            for guide in equality.get("guide_arms") or ():
                if not isinstance(guide, dict):
                    continue
                handle = str(guide.get("handle") or "")
                is_target_line = str(guide.get("angle_name") or "") == target_angle
                lines.append(
                    {
                        "handle": handle,
                        "from": guide.get("from"),
                        "to": guide.get("to"),
                        "style": "solid" if is_target_line else "dashed",
                        "color": COLOR_ACCENT if is_target_line else COLOR_MUTED,
                        "width": 2.2 if is_target_line else 1.35,
                        "dash": "4 7",
                        "show_endpoint_refs": list(guide.get("show_endpoint_refs") or ()),
                    }
                )
            if show_angles:
                for angle in equality.get("angles") or ():
                    if isinstance(angle, dict):
                        angles.append(dict(angle))
        for side in marker.get("axis_sides") or ():
            if not isinstance(side, dict):
                continue
            lines.append(
                {
                    "handle": side.get("handle"),
                    "from": side.get("from"),
                    "to": side.get("to"),
                    "style": "solid",
                    "color": COLOR_MUTED,
                    "width": 1.25,
                }
            )
        for angle in marker.get("right_angles") or ():
            if not isinstance(angle, dict):
                continue
            if show_right_angles:
                right_angles.append(dict(angle))
            vertices = [
                str(angle.get("rayA") or ""),
                str(angle.get("vertex") or ""),
                str(angle.get("rayB") or ""),
            ]
            if all(vertices):
                triangle_regions.append(
                    {
                        "vertices": vertices,
                        "fill": COLOR_PATH_REGION_FILL,
                        "color": COLOR_PATH_REGION_STROKE,
                        "width": 1.0,
                        "dash": "",
                    }
                )
        if not lines and not angles and not right_angles:
            continue
        items.append(
            {
                "component": "EqualAcuteAngleInterceptMarker",
                "triangle_regions": triangle_regions,
                "lines": lines,
                "angles": angles,
                "right_angles": right_angles,
                "label": str(template.get("label") or "α"),
                "color": COLOR_PATH,
                "rightAngleColor": COLOR_CONSTRAINT,
                "rightAngleSize": 10,
                "state": "highlight",
                "persistence": "step_only",
            }
        )
        refs = _point_marker_refs_from_scene_items(tuple(items[-1:]))
        target_ref = str(marker.get("target_intercept") or "")
        target_label = str(marker.get("target_label") or "")
        if target_ref:
            items.extend(
                _bound_point_items_for_refs(
                    bindings,
                    refs - {target_ref},
                    style=POINT_CONTEXT,
                )
            )
            items.extend(
                _point_with_optional_label_items(
                    point=target_ref,
                    label=target_label,
                    display=str(bindings.coordinate_texts_by_ref.get(target_ref) or ""),
                    color=COLOR_RESULT,
                    persistence="carry_forward",
                    label_dy=-28,
                )
            )
        else:
            items.extend(_bound_point_items_for_refs(bindings, refs, style=POINT_ACTIVE))
        items.extend(
            _bound_coordinate_items_for_refs(
                bindings,
                refs - ({target_ref} if target_ref else set()),
            )
        )
    return items


def _bound_point_items_for_refs(
    bindings: VisualRoleBindings,
    refs: set[str],
    *,
    style: _PointVisualStyle,
) -> list[JsonObject]:
    labels = {
        geometry_ref: label
        for label, geometry_ref in bindings.point_handles.items()
    }
    return [
        {
            "component": "Point",
            "handle": f"point:{geometry_ref}",
            "at": geometry_ref,
            "labelText": labels[geometry_ref],
            "color": style.color,
            "dx": style.dx,
            "dy": style.dy,
            "persistence": "carry_forward",
            "decay_state": "muted",
            "metadata": {"low_level_type": "point"},
        }
        for geometry_ref in sorted(refs)
        if geometry_ref in labels
    ]


def _bound_coordinate_items_for_refs(
    bindings: VisualRoleBindings,
    refs: set[str],
) -> list[JsonObject]:
    return [
        {
            "component": "CoordinateLabel",
            "at": geometry_ref,
            "text": bindings.coordinate_texts_by_ref[geometry_ref],
            "dx": 14,
            "dy": -30,
            "metadata": {"low_level_type": "coordinateLabel"},
        }
        for geometry_ref in sorted(refs)
        if geometry_ref in bindings.coordinate_texts_by_ref
    ]


def _angle_guide_arm_payload(guide: dict[str, Any]) -> JsonObject:
    return {
        "handle": guide.get("handle"),
        "from": guide.get("from"),
        "to": guide.get("to"),
        "guide_only_refs": list(guide.get("guide_only_refs") or ()),
        "show_endpoint_refs": list(guide.get("show_endpoint_refs") or ()),
    }


def _parabola_items(bindings: VisualRoleBindings) -> list[JsonObject]:
    items: list[JsonObject] = []
    for curve_id in bindings.curve_ids:
        items.append(
            {
                "component": "Parabola",
                "curveId": curve_id,
                "color": COLOR_CURVE,
                "width": 2.4,
                "metadata": {"low_level_type": "parabola"},
            }
        )
    return items


def _quadratic_curve_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    """Render the curve and the verified points constraining that curve."""

    return [
        *_parabola_items(bindings),
        *_point_items(
            bindings.point_handles,
            tuple(sorted(bindings.point_handles)),
            style=POINT_CONTEXT,
        ),
    ]


def _point_items(
    points: dict[str, str],
    preferred: tuple[str, ...],
    *,
    style: _PointVisualStyle = POINT_ACTIVE,
) -> list[JsonObject]:
    out: list[JsonObject] = []
    for label in preferred:
        at = points.get(label)
        if not at:
            continue
        out.append(
            {
                "component": "Point",
                "handle": f"point:{at}",
                "at": at,
                "labelText": label,
                "color": style.color,
                "dx": style.dx,
                "dy": style.dy,
                "persistence": "carry_forward",
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
    return out


def _point_items_for_geometry_refs(
    context: _SceneBuildContext,
    refs: set[str],
    *,
    style: _PointVisualStyle = POINT_ACTIVE,
) -> list[JsonObject]:
    labels_by_ref = {geometry_ref: label for label, geometry_ref in context.points.items()}
    out: list[JsonObject] = []
    for ref in sorted(refs):
        label = labels_by_ref.get(ref)
        if not label:
            continue
        out.append(
            {
                "component": "Point",
                "handle": f"point:{ref}",
                "at": ref,
                "labelText": label,
                "color": style.color,
                "dx": style.dx,
                "dy": style.dy,
                "persistence": "carry_forward",
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
    return out


def _point_items_for_coordinate_conclusions(
    context: _SceneBuildContext,
    boxes: tuple[str, ...],
    *,
    style: _PointVisualStyle = POINT_RESULT,
) -> list[JsonObject]:
    labels = _labels_with_coordinate_text(context.points, boxes, context.coordinate_texts)
    return _point_items(context.points, tuple(sorted(labels)), style=style)


def _labels_with_coordinate_text(
    points: dict[str, str],
    boxes: tuple[str, ...],
    coordinate_texts: dict[str, str] | None = None,
) -> set[str]:
    text = " ".join(boxes)
    labels: set[str] = set()
    for label, at in points.items():
        if (coordinate_texts or {}).get(at) or (coordinate_texts or {}).get(label) or _coordinate_for_label(label, text):
            labels.add(label)
    return labels


def _point_marker_refs_from_scene_items(items: tuple[JsonObject, ...]) -> set[str]:
    refs: set[str] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        for key in ("guide_only_refs", "show_endpoint_refs"):
            for ref in item.get(key) or ():
                if isinstance(ref, str) and ref:
                    refs.add(ref)
        for key in (
            "angles",
            "guide_arms",
            "lines",
            "right_angles",
            "triangle_regions",
            "triangles",
            "segments",
        ):
            for nested in item.get(key) or ():
                visit(nested)

    for item in items:
        visit(item)
    return refs


def _coordinate_labels(
    points: dict[str, str],
    boxes: tuple[str, ...],
    coordinate_texts: dict[str, str] | None = None,
    *,
    allowed_refs: set[str] | None = None,
) -> list[JsonObject]:
    out: list[JsonObject] = []
    text = " ".join(boxes)
    for label, at in sorted(points.items()):
        if allowed_refs is not None and at not in allowed_refs and label not in allowed_refs:
            continue
        coordinate = (
            (coordinate_texts or {}).get(label)
            or (coordinate_texts or {}).get(at)
            or _coordinate_for_label(label, text)
        )
        if not coordinate:
            continue
        if _is_origin_coordinate_label(label, coordinate):
            continue
        out.append(
            {
                "component": "CoordinateLabel",
                "at": at,
                "text": coordinate,
                "dx": 14,
                "dy": -24,
                "metadata": {"low_level_type": "coordinateLabel"},
            }
        )
    return out


def _angle_coordinate_label_refs(items: tuple[JsonObject, ...]) -> set[str]:
    allowed: set[str] = set()
    excluded: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("component") != "AngleEqualityMarker":
            continue
        for angle in item.get("angles") or ():
            if not isinstance(angle, dict):
                continue
            for key in ("vertex", "rayA", "rayB"):
                value = str(angle.get(key) or "")
                if value:
                    allowed.add(value)
        for guide in item.get("guide_arms") or ():
            if not isinstance(guide, dict):
                continue
            for value in guide.get("show_endpoint_refs") or ():
                if value:
                    excluded.add(str(value))
            for value in guide.get("guide_only_refs") or ():
                if value:
                    excluded.add(str(value))
        for value in item.get("guide_only_refs") or ():
            if value:
                excluded.add(str(value))
    return allowed - excluded


def _equal_acute_intercept_coordinate_label_refs(items: tuple[JsonObject, ...]) -> set[str]:
    allowed: set[str] = set()
    excluded: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or item.get("component") != "EqualAcuteAngleInterceptMarker":
            continue
        for region in item.get("triangle_regions") or ():
            if not isinstance(region, dict):
                continue
            allowed.update(str(value) for value in region.get("vertices") or () if value)
        for line in item.get("lines") or ():
            if not isinstance(line, dict):
                continue
            for key in ("from", "to"):
                value = str(line.get(key) or "")
                if value:
                    allowed.add(value)
            for value in line.get("show_endpoint_refs") or ():
                if value:
                    excluded.add(str(value))
    return allowed - excluded


def _is_origin_coordinate_label(label: str, coordinate: str) -> bool:
    if label != "O":
        return False
    normalized = re.sub(r"\s+", "", coordinate)
    return normalized in {"O(0,0)", "O(0,0.0)", "O(0.0,0)", "O(0.0,0.0)"}


def _derive_texts(lesson_step: LessonStep) -> tuple[str, ...]:
    return tuple(text for _, text in lesson_step.derive)


def _minimum_distance_items(context: _SceneBuildContext) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in context.bindings.equal_length_path_markers:
        items.extend(_line_from_segment_payload(marker.get("common_path_segment"), color=COLOR_PATH, width=2.4))
        items.extend(
            _line_from_segment_payload(
                marker.get("replacement_path_segment"),
                color=COLOR_RESULT,
                width=2.4,
            )
        )
        minimum_segment = marker.get("minimum_segment")
        items.extend(
            _line_from_segment_payload(
                minimum_segment,
                color=COLOR_RESULT,
                width=2.8,
            )
        )
        items.extend(
            _distance_marker_from_segment_payload(
                minimum_segment,
                color=COLOR_RESULT,
                width=2.8,
            )
        )
        if isinstance(minimum_segment, dict):
            auxiliary_ref = str(minimum_segment.get("to") or "")
            if auxiliary_ref:
                items.extend(
                    _point_items_for_geometry_refs(
                        context,
                        {auxiliary_ref},
                        style=POINT_AUXILIARY,
                    )
                )
    return items


def _evaluated_point_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    point_color = str(template.get("point_color") or COLOR_RESULT)
    for marker in bindings.evaluated_points:
        point = str(marker.get("point") or "")
        label = str(marker.get("label") or "")
        display = str(marker.get("display") or "")
        if not point:
            continue
        items.extend(
            _point_with_optional_label_items(
                point=point,
                label=label,
                display=display,
                color=point_color,
                persistence=persistence,
                label_dy=-28,
            )
        )
    return items


def _line_parabola_intersection_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    """Render a line/curve intersection from typed role bindings."""

    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    line_color = str(template.get("line_color") or COLOR_ACCENT)
    target_color = str(template.get("target_color") or COLOR_RESULT)
    for marker in bindings.line_parabola_intersections:
        known = str(marker.get("known_point") or "")
        target = str(marker.get("target_point") or "")
        if not known or not target:
            continue
        source_step_id = str(marker.get("source_step_id") or "intersection")
        items.append(
            {
                "component": "ColoredLine",
                "handle": f"line:intersection:{source_step_id}",
                "from": known,
                "to": target,
                "color": line_color,
                "width": 2.2,
                "state": "highlight",
                "persistence": persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "coloredLine"},
            }
        )
        construction_points = {
            str(marker.get(role) or ""): str(marker.get(f"{role}_label") or "")
            for role in ("line_p1", "line_p2")
            if str(marker.get(role) or "") not in {"", known, target}
        }
        for point, label in construction_points.items():
            items.extend(
                _point_with_optional_label_items(
                    point=point,
                    label=label,
                    display="",
                    color=COLOR_MUTED,
                    persistence=persistence,
                    label_dy=-28,
                )
            )
        items.extend(
            _point_with_optional_label_items(
                point=target,
                label=str(marker.get("target_label") or ""),
                display=str(marker.get("target_display") or ""),
                color=target_color,
                persistence=persistence,
                label_dy=-28,
            )
        )
    return items


def _generic_source_records(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> tuple[dict[str, Any], ...]:
    capability_id = str(template.get("_source_capability_id") or "")
    records = tuple(
        record
        for record in bindings.source_roles
        if not capability_id
        or str(record.get("capability_id") or "") == capability_id
    )
    return records


def _generic_input_items(
    record: dict[str, Any],
    role_name: str,
) -> tuple[dict[str, Any], ...]:
    raw = (record.get("inputs") or {}).get(role_name, ())
    return tuple(item for item in raw if isinstance(item, dict))


def _generic_input_item(
    record: dict[str, Any],
    role_name: str,
) -> dict[str, Any]:
    items = _generic_input_items(record, role_name)
    return items[0] if len(items) == 1 else {}


def _generic_output_item(
    record: dict[str, Any],
    role_name: str,
) -> dict[str, Any]:
    raw = (record.get("outputs") or {}).get(role_name)
    return raw if isinstance(raw, dict) else {}


def _template_applies_to_record(
    template: dict[str, Any],
    record: dict[str, Any],
) -> bool:
    condition = template.get("when")
    if condition is None:
        return True
    if not isinstance(condition, dict) or set(condition) != {"output_present"}:
        raise ValueError(f"visual_template_condition_invalid: {condition!r}")
    output_name = str(condition.get("output_present") or "")
    return bool(output_name and output_name in (record.get("outputs") or {}))


def _generic_point_items(
    role: dict[str, Any],
    *,
    color: str,
    persistence: str,
    coordinate: bool = True,
) -> list[JsonObject]:
    point = str(role.get("geometry_ref") or "")
    if not point:
        return []
    label = str(role.get("label") or "")
    display = str(role.get("display") or "") if coordinate else ""
    return _point_with_optional_label_items(
        point=point,
        label=label,
        display=display,
        color=color,
        persistence=persistence,
        label_dy=-30,
    )


def _generic_candidate_roles(
    record: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    for output in (record.get("outputs") or {}).values():
        if not isinstance(output, dict):
            continue
        refs = output.get("geometry_refs")
        if isinstance(refs, list) and refs:
            return tuple(item for item in refs if isinstance(item, dict))
    for input_values in (record.get("inputs") or {}).values():
        for item in input_values if isinstance(input_values, list) else ():
            if not isinstance(item, dict):
                continue
            refs = item.get("geometry_refs")
            if isinstance(refs, list) and refs:
                return tuple(part for part in refs if isinstance(part, dict))
    for calculation in record.get("calculations") or ():
        if not isinstance(calculation, dict):
            continue
        for key in ("candidates_geometry", "points_geometry"):
            refs = calculation.get(key)
            if isinstance(refs, list) and refs:
                return tuple(item for item in refs if isinstance(item, dict))
    return ()


def _generic_curve_items(
    role: dict[str, Any],
    *,
    persistence: str,
) -> list[JsonObject]:
    curve_id = str(role.get("curve_id") or "")
    if not curve_id:
        return []
    return [
        {
            "component": "Parabola",
            "curveId": curve_id,
            "color": COLOR_CURVE,
            "width": 2.4,
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "parabola"},
        }
    ]


def _line_item(
    start: str,
    end: str,
    *,
    color: str,
    width: float,
    persistence: str,
    dash: str = "",
    role: str = "",
) -> JsonObject | None:
    if not start or not end or start == end:
        return None
    return {
        "component": "DashedLine" if dash else "ColoredLine",
        "role": role,
        "handle": f"line:{start}:{end}:{role or 'segment'}",
        "from": start,
        "to": end,
        "color": color,
        "width": width,
        "dash": dash,
        "persistence": persistence,
        "decay_state": "muted",
        "metadata": {
            "low_level_type": "dashedLine" if dash else "coloredLine"
        },
    }


def _distance_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "step_only")
    endpoint_roles = tuple(str(item) for item in template.get("endpoint_roles") or ())
    output_role = str(template.get("output_role") or "distance")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        if len(endpoint_roles) != 2:
            continue
        endpoints = [_generic_input_item(record, role) for role in endpoint_roles]
        refs = [str(item.get("geometry_ref") or "") for item in endpoints]
        if not all(refs):
            continue
        line = _line_item(
            refs[0], refs[1], color=COLOR_RESULT, width=2.6,
            persistence=persistence, role="distance:target",
        )
        if line is not None:
            result.append(line)
        distance = _generic_output_item(record, output_role)
        result.append(
            {
                "component": "DistanceMarker",
                "from": refs[0],
                "to": refs[1],
                "label": str(distance.get("display") or distance.get("value") or ""),
                "color": COLOR_RESULT,
                "width": 2.6,
                "offsetPx": 16,
                "persistence": persistence,
                "metadata": {"low_level_type": "distanceMarker"},
            }
        )
        for endpoint in endpoints:
            result.extend(
                _generic_point_items(
                    endpoint,
                    color=COLOR_ACCENT,
                    persistence=persistence,
                    coordinate=False,
                )
            )
    return result


def _midpoint_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    endpoint_roles = tuple(str(item) for item in template.get("endpoint_roles") or ())
    output_role = str(template.get("output_role") or "midpoint")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        if len(endpoint_roles) != 2:
            continue
        endpoints = [_generic_input_item(record, name) for name in endpoint_roles]
        refs = [str(item.get("geometry_ref") or "") for item in endpoints]
        midpoint = _generic_output_item(record, output_role)
        midpoint_ref = str(midpoint.get("geometry_ref") or "")
        if not all(refs) or not midpoint_ref:
            continue
        line = _line_item(
            refs[0], refs[1], color=COLOR_CONSTRAINT, width=2.0,
            persistence=persistence, role="midpoint:source_segment",
        )
        if line is not None:
            result.append(line)
        for endpoint in endpoints:
            result.extend(
                _generic_point_items(
                    endpoint,
                    color=COLOR_MUTED,
                    persistence=persistence,
                    coordinate=False,
                )
            )
        result.extend(
            _generic_point_items(
                midpoint,
                color=COLOR_RESULT,
                persistence=persistence,
            )
        )
        for start, end in ((refs[0], midpoint_ref), (midpoint_ref, refs[1])):
            result.append(
                {
                    "component": "DistanceMarker",
                    "from": start,
                    "to": end,
                    "label": "=",
                    "color": COLOR_RESULT,
                    "width": 1.8,
                    "offsetPx": 13,
                    "persistence": persistence,
                    "metadata": {"low_level_type": "distanceMarker"},
                }
            )
    return result


def _line_intersection_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    output_role = str(template.get("output_role") or "intersection")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        for line_index, template_key in enumerate(("line1_roles", "line2_roles"), start=1):
            names = tuple(str(item) for item in template.get(template_key) or ())
            if len(names) != 2:
                continue
            roles = [_generic_input_item(record, name) for name in names]
            refs = [str(item.get("geometry_ref") or "") for item in roles]
            if all(refs):
                line = _line_item(
                    refs[0], refs[1], color=COLOR_CONSTRAINT, width=2.0,
                    persistence=persistence, role=f"intersection:line{line_index}",
                )
                if line is not None:
                    result.append(line)
                for role in roles:
                    result.extend(
                        _generic_point_items(
                            role,
                            color=COLOR_MUTED,
                            persistence=persistence,
                            coordinate=False,
                        )
                    )
        result.extend(
            _generic_point_items(
                _generic_output_item(record, output_role),
                color=COLOR_RESULT,
                persistence=persistence,
            )
        )
    return result


def _point_on_parabola_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    curve_role = str(template.get("input_curve_role") or "parabola")
    output_role = str(template.get("output_role") or "point")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        result.extend(
            _generic_curve_items(
                _generic_input_item(record, curve_role),
                persistence=persistence,
            )
        )
        result.extend(
            _generic_point_items(
                _generic_output_item(record, output_role),
                color=COLOR_RESULT,
                persistence=persistence,
            )
        )
    return result


def _quadratic_axis_relation_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    output_role = str(template.get("output_role") or "axis_point")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        curve_roles = [
            item
            for values in (record.get("inputs") or {}).values()
            for item in values
            if isinstance(item, dict) and str(item.get("curve_id") or "")
        ]
        curve_ids: list[str] = []
        for curve in curve_roles:
            result.extend(_generic_curve_items(curve, persistence=persistence))
            curve_id = str(curve.get("curve_id") or "")
            curve_ids.append(curve_id)
        if not curve_ids:
            result.extend(
                _quadratic_context_marker_items(template, bindings)
            )
            curve_ids.extend(bindings.curve_ids)
        if not curve_ids:
            axis_point = _generic_output_item(record, output_role)
            value = axis_point.get("value")
            if _is_point_value(value):
                x_expression = _page_expr(value[0])
                result.append(
                    {
                        "component": "AxisOfSymmetry",
                        "handle": f"axis:x={x_expression}",
                        "xExpr": x_expression,
                        "color": COLOR_CONSTRAINT,
                        "width": 1.6,
                        "dash": "7 6",
                        "persistence": persistence,
                        "decay_state": "muted",
                        "metadata": {"low_level_type": "axisOfSymmetry"},
                    }
                )
        for curve_id in curve_ids:
            result.append(
                {
                    "component": "AxisOfSymmetry",
                    "handle": f"axis:{curve_id}",
                    "curveId": curve_id,
                    "color": COLOR_CONSTRAINT,
                    "width": 1.6,
                    "dash": "7 6",
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "axisOfSymmetry"},
                }
            )
        result.extend(
            _generic_point_items(
                _generic_output_item(record, output_role),
                color=COLOR_RESULT,
                persistence=persistence,
            )
        )
    return result


def _quadratic_context_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    """Show the sole verified in-scope parabola as muted diagram context."""

    persistence = str(template.get("persistence") or "carry_forward")
    color = str(template.get("context_color") or COLOR_MUTED)
    return [
        {
            "component": "Parabola",
            "curveId": curve_id,
            "color": color,
            "width": 2.2,
            "state": "context",
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "parabola"},
        }
        for curve_id in bindings.curve_ids
    ]


def _quadratic_y_axis_intercept_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    return _point_on_parabola_marker_items(template, bindings)


def _evaluated_parabola_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    output_role = str(template.get("output_role") or "evaluated_parabola")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        if not _template_applies_to_record(template, record):
            continue
        result.extend(
            _generic_curve_items(
                _generic_output_item(record, output_role),
                persistence=persistence,
            )
        )
    return result


def _segment_parameter_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "step_only")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        for kind, key in (
            ("target", "segment_roles"),
            ("reference", "reference_segment_roles"),
        ):
            names = tuple(str(item) for item in template.get(key) or ())
            if len(names) != 2:
                continue
            roles = [_generic_input_item(record, name) for name in names]
            refs = [str(item.get("geometry_ref") or "") for item in roles]
            if not all(refs):
                continue
            line = _line_item(
                refs[0], refs[1],
                color=COLOR_RESULT if kind == "target" else COLOR_CONSTRAINT,
                width=2.5 if kind == "target" else 2.0,
                persistence=persistence,
                role=f"parameter_length:{kind}",
            )
            if line is not None:
                result.append(line)
            for role in roles:
                result.extend(
                    _generic_point_items(
                        role,
                        color=COLOR_ACCENT,
                        persistence=persistence,
                        coordinate=False,
                    )
                )
        condition = _generic_input_item(record, "condition")
        target_names = tuple(
            str(item) for item in template.get("segment_roles") or ()
        )
        if len(target_names) == 2:
            target_refs = [
                str(_generic_input_item(record, name).get("geometry_ref") or "")
                for name in target_names
            ]
            if all(target_refs):
                result.append(
                    {
                        "component": "DistanceMarker",
                        "from": target_refs[0],
                        "to": target_refs[1],
                        "label": str(condition.get("display") or ""),
                        "color": COLOR_RESULT,
                        "width": 2.5,
                        "offsetPx": 16,
                        "persistence": persistence,
                        "metadata": {"low_level_type": "distanceMarker"},
                    }
                )
    return result


def _ray_equal_length_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    role_names = {
        key: str(template.get(key) or default)
        for key, default in (
            ("anchor_role", "anchor"),
            ("ray_role", "ray_point"),
            ("reference_role", "reference_point"),
            ("output_role", "point"),
        )
    }
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        anchor = _generic_input_item(record, role_names["anchor_role"])
        ray = _generic_input_item(record, role_names["ray_role"])
        reference = _generic_input_item(record, role_names["reference_role"])
        target = _generic_output_item(record, role_names["output_role"])
        anchor_ref = str(anchor.get("geometry_ref") or "")
        ray_ref = str(ray.get("geometry_ref") or "")
        reference_ref = str(reference.get("geometry_ref") or "")
        target_ref = str(target.get("geometry_ref") or "")
        for start, end, role, color, dash in (
            (anchor_ref, ray_ref, "equal_ray:direction", COLOR_MUTED, "5 6"),
            (anchor_ref, reference_ref, "equal_ray:reference", COLOR_CONSTRAINT, ""),
            (anchor_ref, target_ref, "equal_ray:result", COLOR_RESULT, ""),
        ):
            line = _line_item(
                start, end, color=color, width=2.2,
                persistence=persistence, dash=dash, role=role,
            )
            if line is not None:
                result.append(line)
        for role, color in (
            (anchor, COLOR_ACCENT),
            (ray, COLOR_MUTED),
            (reference, COLOR_CONSTRAINT),
            (target, COLOR_RESULT),
        ):
            result.extend(
                _generic_point_items(
                    role,
                    color=color,
                    persistence=persistence,
                    coordinate=role is target,
                )
            )
        if anchor_ref and reference_ref and target_ref:
            for end in (reference_ref, target_ref):
                result.append(
                    {
                        "component": "DistanceMarker",
                        "from": anchor_ref,
                        "to": end,
                        "label": "=",
                        "color": COLOR_RESULT,
                        "width": 2.0,
                        "offsetPx": 14,
                        "persistence": persistence,
                        "metadata": {"low_level_type": "distanceMarker"},
                    }
                )
    return result


def _rotated_candidate_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    input_roles = tuple(str(item) for item in template.get("input_roles") or ())
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        record_start = len(result)
        anchor = _generic_input_item(record, input_roles[0]) if input_roles else {}
        reference = (
            _generic_input_item(record, input_roles[1])
            if len(input_roles) > 1
            else {}
        )
        anchor_ref = str(anchor.get("geometry_ref") or "")
        reference_ref = str(reference.get("geometry_ref") or "")
        candidates = _generic_candidate_roles(record)
        construction = next(
            (
                calculation.get("construction_geometry")
                for calculation in record.get("calculations") or ()
                if isinstance(calculation, dict)
                and isinstance(calculation.get("construction_geometry"), dict)
            ),
            {},
        )
        if anchor_ref and reference_ref:
            line = _line_item(
                anchor_ref, reference_ref, color=COLOR_CONSTRAINT, width=2.1,
                persistence=persistence, role="right_equal:reference",
            )
            if line is not None:
                result.append(line)
            result.append(
                {
                    "component": "DistanceMarker",
                    "from": anchor_ref,
                    "to": reference_ref,
                    "label": "=",
                    "color": COLOR_CONSTRAINT,
                    "width": 2.0,
                    "offsetPx": 14,
                    "persistence": persistence,
                    "metadata": {"low_level_type": "distanceMarker"},
                }
            )
        branches = construction.get("candidate_branches") or ()
        for candidate_index, candidate in enumerate(candidates):
            candidate_ref = str(candidate.get("geometry_ref") or "")
            if anchor_ref and candidate_ref:
                line = _line_item(
                    anchor_ref, candidate_ref, color=COLOR_RESULT, width=2.1,
                    persistence=persistence, role="right_equal:candidate",
                )
                if line is not None:
                    result.append(line)
                if reference_ref:
                    result.append(
                        {
                            "component": "RightAngle",
                            "vertex": anchor_ref,
                            "rayA": reference_ref,
                            "rayB": candidate_ref,
                            "color": COLOR_CONSTRAINT,
                            "size": 10,
                            "persistence": persistence,
                            "metadata": {"low_level_type": "rightAngle"},
                        }
                    )
                    result.append(
                        {
                            "component": "DistanceMarker",
                            "from": anchor_ref,
                            "to": candidate_ref,
                            "label": "=",
                            "color": COLOR_RESULT,
                            "width": 2.0,
                            "offsetPx": 14,
                            "persistence": persistence,
                            "metadata": {"low_level_type": "distanceMarker"},
                        }
                    )
            result.extend(
                _generic_point_items(
                    {
                        "geometry_ref": candidate_ref,
                        "label": candidate.get("label"),
                    },
                    color=COLOR_RESULT,
                    persistence=persistence,
                    coordinate=False,
                )
            )
            branch = (
                branches[candidate_index]
                if candidate_index < len(branches)
                and isinstance(branches[candidate_index], dict)
                else {}
            )
            projection = branch.get("projection") or {}
            projection_ref = str(projection.get("geometry_ref") or "")
            projection_line = _line_item(
                candidate_ref,
                projection_ref,
                color=COLOR_MUTED,
                width=1.6,
                persistence=persistence,
                dash="5 5",
                role="right_equal:candidate_projection",
            )
            if projection_line is not None:
                result.append(projection_line)
            result.extend(
                _generic_point_items(
                    projection,
                    color=COLOR_MUTED,
                    persistence=persistence,
                    coordinate=False,
                )
            )
            if (
                anchor_ref
                and projection_ref
                and candidate_ref
                and anchor_ref != projection_ref
                and candidate_ref != projection_ref
            ):
                result.append(
                    {
                        "component": "RightAngle",
                        "vertex": projection_ref,
                        "rayA": anchor_ref,
                        "rayB": candidate_ref,
                        "color": COLOR_MUTED,
                        "size": 8,
                        "persistence": persistence,
                        "metadata": {"low_level_type": "rightAngle"},
                    }
                )
        reference_projection = construction.get("reference_projection") or {}
        reference_projection_ref = str(
            reference_projection.get("geometry_ref") or ""
        )
        reference_projection_line = _line_item(
            reference_ref,
            reference_projection_ref,
            color=COLOR_MUTED,
            width=1.6,
            persistence=persistence,
            dash="5 5",
            role="right_equal:reference_projection",
        )
        if reference_projection_line is not None:
            result.append(reference_projection_line)
        result.extend(
            _generic_point_items(
                reference_projection,
                color=COLOR_MUTED,
                persistence=persistence,
                coordinate=False,
            )
        )
        if (
            anchor_ref
            and reference_projection_ref
            and reference_ref
            and anchor_ref != reference_projection_ref
            and reference_ref != reference_projection_ref
        ):
            result.append(
                {
                    "component": "RightAngle",
                    "vertex": reference_projection_ref,
                    "rayA": anchor_ref,
                    "rayB": reference_ref,
                    "color": COLOR_MUTED,
                    "size": 8,
                    "persistence": persistence,
                    "metadata": {"low_level_type": "rightAngle"},
                }
            )
        for role in (anchor, reference):
            result.extend(
                _generic_point_items(
                    role,
                    color=COLOR_MUTED,
                    persistence=persistence,
                    coordinate=False,
                )
            )
        source_step_id = str(record.get("source_step_id") or "")
        for item in result[record_start:]:
            original_role = str(
                item.get("role") or item.get("component") or "object"
            )
            item["role"] = (
                f"candidate_construction:{source_step_id}:{original_role}"
            )
    return result


def _candidate_selection_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        candidates = _generic_candidate_roles(record)
        selected = next(
            (
                item
                for item in (record.get("outputs") or {}).values()
                if isinstance(item, dict)
                and str(item.get("runtime_type") or "") == "Point"
            ),
            {},
        )
        selected_value = selected.get("value")
        selected_candidates = [
            candidate
            for candidate in candidates
            if _same_point_pair_value(
                _sympy_point_pair(candidate.get("value")) or (),
                _sympy_point_pair(selected_value) or (),
            )
        ]
        if len(selected_candidates) != 1:
            raise ValueError(
                "visual_candidate_selection_identity_invalid: "
                f"source={record.get('source_step_id')}, "
                f"matches={len(selected_candidates)}"
            )
        selected_items = _generic_point_items(
            selected,
            color=COLOR_RESULT,
            persistence=persistence,
        )
        for item in selected_items:
            if item.get("component") != "Point":
                continue
            item["role"] = (
                "candidate:selected_result:"
                f"{record.get('source_step_id') or ''}"
            )
        result.extend(selected_items)
    return result


def _curve_candidate_filter_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    result: list[JsonObject] = []
    records = {
        str(record.get("source_step_id") or ""): record
        for record in _generic_source_records(template, bindings)
    }
    if bindings.curve_candidate_selection_markers:
        for marker in bindings.curve_candidate_selection_markers:
            source_step_id = str(marker.get("source_step_id") or "")
            record = records.get(source_step_id, {})
            for values in (record.get("inputs") or {}).values():
                for role in values if isinstance(values, list) else ():
                    if isinstance(role, dict):
                        result.extend(
                            _generic_curve_items(role, persistence="step_only")
                        )
            candidates = marker.get("candidates")
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                selected = candidate.get("selected") is True
                point_ref = str(candidate.get("geometry_ref") or "")
                label = str(candidate.get("label") or "")
                if not point_ref or not label:
                    continue
                result.append(
                    {
                        "component": "Point",
                        "role": (
                            "candidate:selected" if selected else "candidate:rejected"
                        ),
                        "handle": f"point:{point_ref}",
                        "at": point_ref,
                        "labelText": label,
                        "color": COLOR_RESULT if selected else COLOR_MUTED,
                        "dx": 14,
                        "dy": -18,
                        "persistence": "step_only",
                        "metadata": {
                            "low_level_type": "point",
                            "preserve_student_label": True,
                            "candidate_decision": (
                                "retain" if selected else "reject"
                            ),
                        },
                    }
                )
        return _dedupe_scene_items(result)

    for record in _generic_source_records(template, bindings):
        for values in (record.get("inputs") or {}).values():
            for role in values if isinstance(values, list) else ():
                if not isinstance(role, dict):
                    continue
                result.extend(_generic_curve_items(role, persistence="step_only"))
        for candidate in _generic_candidate_roles(record):
            result.extend(
                _generic_point_items(
                    {
                        "geometry_ref": candidate.get("geometry_ref"),
                        "label": candidate.get("label"),
                    },
                    color=COLOR_ACCENT,
                    persistence="step_only",
                    coordinate=False,
                )
            )
    return result


def _solved_curve_candidate_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    persistence = str(template.get("persistence") or "carry_forward")
    result: list[JsonObject] = []
    for record in _generic_source_records(template, bindings):
        for output in (record.get("outputs") or {}).values():
            if not isinstance(output, dict):
                continue
            result.extend(_generic_curve_items(output, persistence=persistence))
            if str(output.get("runtime_type") or "") == "Point":
                result.extend(
                    _generic_point_items(
                        output,
                        color=COLOR_RESULT,
                        persistence=persistence,
                    )
                )
    return result


def _empty_visual_template_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    return []


_VisualTemplateRenderer = Callable[[dict[str, Any], VisualRoleBindings], list[JsonObject]]

_METHOD_VISUAL_TEMPLATE_RENDERERS: dict[str, _VisualTemplateRenderer] = {
    "AngleEqualityMarker": _angle_equality_template_items,
    "AxisParameterizedPointMarker": _axis_parameterized_point_marker_items,
    "CurvePointCandidateMarker": _curve_point_candidate_marker_items,
    "DistanceBetweenPointsMarker": _distance_marker_items,
    "EqualLengthRayPointMarker": _ray_equal_length_marker_items,
    "EqualAcuteAngleInterceptMarker": _equal_acute_angle_intercept_marker_items,
    "EvaluatedParabolaMarker": _evaluated_parabola_marker_items,
    "EvaluatedPointMarker": _evaluated_point_marker_items,
    "LineIntersectionMarker": _line_intersection_marker_items,
    "LineParabolaIntersectionMarker": _line_parabola_intersection_marker_items,
    "MidpointMarker": _midpoint_marker_items,
    "PointOnParabolaMarker": _point_on_parabola_marker_items,
    "QuadraticCurveMarker": _quadratic_curve_marker_items,
    "QuadraticAxisRelationMarker": _quadratic_axis_relation_marker_items,
    "QuadraticAxisXInterceptMarker": _quadratic_axis_x_intercept_marker_items,
    "QuadraticVertexMarker": _quadratic_vertex_marker_items,
    "QuadraticXAxisInterceptMarker": _quadratic_x_axis_intercept_marker_items,
    "QuadraticYAxisInterceptMarker": _quadratic_y_axis_intercept_marker_items,
    "RightAngleEqualLengthCandidatesMarker": (
        _rotated_candidate_marker_items
    ),
    "SegmentParameterMarker": _segment_parameter_marker_items,
    "SquareAdjacentVertexMarker": _square_adjacent_vertex_marker_items,
    "TranslationAnimation": _empty_visual_template_items,
    "TranslationMarker": _translation_marker_items,
}

_RECIPE_VISUAL_TEMPLATE_RENDERERS: dict[str, _VisualTemplateRenderer] = {
    "AuxiliaryRayGuideMarker": _auxiliary_ray_guide_marker_items,
    "AtomicPathMinimumMarker": _atomic_path_minimum_marker_items,
    "CongruentTriangleMarker": _congruent_triangle_marker_items,
    "EquivalentSegmentMarker": _equivalent_segment_marker_items,
    "PathMinimumTriangleMarker": _path_minimum_triangle_marker_items,
    "QuadraticContextMarker": _quadratic_context_marker_items,
    "AtomicSquarePathReductionMarker": _atomic_square_path_reduction_marker_items,
    "CandidateSelectionMarker": _candidate_selection_marker_items,
    "CurveCandidateFilterMarker": _curve_candidate_filter_marker_items,
    "RightAngleEqualLengthCandidatesMarker": (
        _rotated_candidate_marker_items
    ),
    "SolvedCurveCandidateMarker": _solved_curve_candidate_marker_items,
}
def _line_if_points(
    points: dict[str, str],
    start: str,
    end: str,
    *,
    color: str,
    width: float,
    handle: str | None = None,
    state: str | None = None,
) -> list[JsonObject]:
    if start not in points or end not in points:
        return []
    item: JsonObject = {
        "component": "ColoredLine",
        "handle": handle or f"line:{points[start]}:{points[end]}",
        "from": points[start],
        "to": points[end],
        "color": color,
        "width": width,
        "persistence": "carry_forward",
        "decay_state": "muted",
        "metadata": {"low_level_type": "coloredLine"},
    }
    if handle:
        item["handle"] = handle
    if state:
        item["state"] = state
    return [item]


def _line_from_segment_payload(
    segment: Any,
    *,
    color: str,
    width: float,
    persistence: str = "carry_forward",
    role: str = "",
) -> list[JsonObject]:
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    if not start or not end:
        return []
    return [
        {
            "component": "ColoredLine",
            "handle": _line_handle(segment),
            "from": start,
            "to": end,
            "color": color,
            "width": width,
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "coloredLine"},
            **({"role": role} if role else {}),
        }
    ]


def _dashed_line_from_segment_payload(
    segment: Any,
    *,
    color: str,
    width: float,
    persistence: str = "carry_forward",
    role: str = "",
) -> list[JsonObject]:
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    if not start or not end:
        return []
    return [
        {
            "component": "DashedLine",
            "handle": _line_handle(segment),
            "from": start,
            "to": end,
            "color": color,
            "width": width,
            "dash": "5 6",
            "persistence": persistence,
            "decay_state": "muted",
            "metadata": {"low_level_type": "dashedLine"},
            **({"role": role} if role else {}),
        }
    ]


def _line_handle(segment: dict[str, Any]) -> str:
    label = str(segment.get("label") or "")
    if label:
        return f"line:{label}"
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    return f"line:{start}:{end}"


def _dashed_line_if_points(points: dict[str, str], start: str, end: str) -> list[JsonObject]:
    if start not in points or end not in points:
        return []
    return [
        {
            "component": "DashedLine",
            "from": points[start],
            "to": points[end],
            "color": COLOR_MUTED,
            "width": 1.6,
            "dash": "5 5",
            "metadata": {"low_level_type": "dashedLine"},
        }
    ]


def _distance_marker(
    points: dict[str, str],
    start: str,
    end: str,
    label: str,
    *,
    color: str,
    width: float = 2.2,
    offset_px: int = 16,
) -> list[JsonObject]:
    if start not in points or end not in points:
        return []
    return [
        {
            "component": "DistanceMarker",
            "handle": f"distance:{points[start]}:{points[end]}:{label}",
            "from": points[start],
            "to": points[end],
            "label": label,
            "color": color,
            "width": width,
            "offsetPx": offset_px,
            "persistence": "step_only",
        }
    ]


def _distance_marker_from_segment_payload(
    segment: Any,
    *,
    color: str,
    width: float = 2.2,
    offset_px: int = 16,
    persistence: str = "step_only",
) -> list[JsonObject]:
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    label = str(segment.get("label") or "")
    if not start or not end or not label:
        return []
    return [
        {
            "component": "DistanceMarker",
            "handle": f"distance:{start}:{end}:{label}",
            "from": start,
            "to": end,
            "label": label,
            "color": color,
            "width": width,
            "offsetPx": offset_px,
            "persistence": persistence,
        }
    ]


def _annotations_for_lesson_step(lesson_step: LessonStep) -> list[JsonObject]:
    if not lesson_step.box:
        return []
    return [
        {
            "type": "label",
            "target": lesson_step.id,
            "text_source": "lesson_step.box",
            "index": 0,
        }
    ]


def _coordinate_for_label(label: str, text: str) -> str:
    import re

    match = re.search(rf"{label}\(([^)]+)\)", text)
    if not match:
        return ""
    return f"{label}({match.group(1)})"


def _translation_label(vector: Any) -> str:
    if not isinstance(vector, list) or len(vector) != 2:
        return "v"
    dx = _plain_number_text(vector[0])
    dy = _plain_number_text(vector[1])
    if _is_zero_text(dy) and not _is_zero_text(dx):
        return f"-{_abs_text(dx)}" if dx.startswith("-") else f"+{_abs_text(dx)}"
    if _is_zero_text(dx) and not _is_zero_text(dy):
        return f"dy={dy}"
    return f"v=({dx},{dy})"


def _plain_number_text(value: Any) -> str:
    text = str(value).strip().replace(" ", "")
    return text or "0"


def _is_zero_text(value: str) -> bool:
    return value in {"0", "0.0", "+0", "-0"}


def _abs_text(value: str) -> str:
    return value[1:] if value.startswith("-") else value


def _verified_coordinate_texts_for_lesson_step(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> dict[str, str]:
    source_steps = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    source_order = {
        str(step.get("step_id")): index
        for index, step in enumerate(snapshot.effective_steps)
        if isinstance(step, dict) and step.get("step_id")
    }
    source_indexes = [
        source_order[step_id]
        for step_id in lesson_step.source_step_ids
        if step_id in source_order
    ]
    visible_prefix_index = max(source_indexes) if source_indexes else -1
    runtime_points_by_source: dict[str, list[tuple[str, str]]] = {}
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict):
            continue
        if item.get("type") != "Point":
            continue
        source_key = _point_fact_source_key(item, source_order)
        value = item.get("value")
        if not source_key or not _is_point_value(value):
            continue
        runtime_points_by_source.setdefault(source_key, []).append(
            (_point_value_text(value), str(item.get("handle") or ""))
        )

    coordinates: dict[str, str] = {}
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        if entity.get("definition") == "coordinate_origin":
            continue
        value = entity.get("coordinate")
        if not _is_point_value(value):
            continue
        label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        if label:
            coordinates.setdefault(label, f"{label}({_point_value_text(value).replace(', ', ',')})")
    lesson_root = _scope_root(lesson_step.scope_id)
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        source_key = _point_fact_source_key(item, source_order)
        if not source_key or source_order.get(source_key, 10**9) > visible_prefix_index:
            continue
        fact_root = _scope_root(str(item.get("scope_id") or ""))
        source_step = source_steps.get(source_key)
        source_root = (
            _scope_root(str(source_step.get("scope_id") or ""))
            if isinstance(source_step, dict)
            else fact_root
        )
        if fact_root not in {lesson_root, "problem"} and source_root != lesson_root:
            continue
        value = item.get("value")
        if not _is_point_value(value):
            continue
        label = _point_label_for_runtime_coordinate_fact(item, source_steps, source_key)
        if label:
            coordinates[label] = f"{label}({_point_value_text(value)})"
    for source_step_id in lesson_step.source_step_ids:
        source_step = source_steps.get(source_step_id)
        if not source_step:
            continue
        labels = _point_labels_for_coordinate_source(source_step)
        values = runtime_points_by_source.get(source_step_id, ())
        if len(values) != 1:
            continue
        if len(labels) != 1:
            labels = _coordinate_conclusion_labels_for_value(
                lesson_step,
                values[0][0],
            )
        if len(labels) != 1:
            continue
        label = next(iter(labels))
        coordinates[label] = f"{label}({values[0][0]})"
    return coordinates


def _coordinate_conclusion_labels_for_value(
    lesson_step: LessonStep,
    value_text: str,
) -> set[str]:
    """Bind a verified anonymous Point output to its student-facing label.

    Some runtime methods return an auxiliary point without a public output
    target.  LessonIR still names that point in its verified coordinate
    conclusion.  We accept the label only when both displayed components
    equal the runtime result after student-format normalization.
    """

    value_parts = [part.strip() for part in str(value_text).split(",")]
    if len(value_parts) != 2:
        return set()
    expected = tuple(
        _normalized_student_coordinate_component(student_math_display(part))
        for part in value_parts
    )
    result: set[str] = set()
    texts = [*lesson_step.box, *[text for _, text in lesson_step.derive]]
    pattern = re.compile(
        r"(?<![A-Za-z])([A-Z])\s*[（(]\s*([^,，()（）]+)\s*[,，]\s*([^()（）]+)\s*[）)]"
    )
    for text in texts:
        for label, x_text, y_text in pattern.findall(str(text)):
            actual = (
                _normalized_student_coordinate_component(x_text),
                _normalized_student_coordinate_component(y_text),
            )
            if actual == expected:
                result.add(label)
    return result


def _normalized_student_coordinate_component(value: Any) -> str:
    return (
        str(value)
        .strip()
        .replace(" ", "")
        .replace("－", "-")
        .replace("−", "-")
        .replace("＋", "+")
        .replace("，", ",")
    )


def _visible_coordinate_texts_by_ref(
    coordinate_texts: dict[str, str],
    geometry_spec: JsonObject,
    *,
    parameter_values: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Map only already-known coordinate facts to renderable geometry ids.

    The geometry registry intentionally contains points discovered later in
    the solution so that every frame can reference stable identities.  Registry
    presence is therefore not permission to display a coordinate.  Visibility
    is derived from the verified source-step prefix above and joined to ids
    through ``pointMeta``.
    """

    result: dict[str, str] = {}
    point_meta = geometry_spec.get("pointMeta") or {}
    known_refs = {
        *map(str, (geometry_spec.get("fixedPoints") or {}).keys()),
        *map(str, (geometry_spec.get("movingPoints") or {}).keys()),
    }
    for geometry_ref in sorted(known_refs):
        meta = point_meta.get(geometry_ref)
        label = str((meta or {}).get("label") or "") if isinstance(meta, dict) else ""
        text = coordinate_texts.get(geometry_ref) or coordinate_texts.get(label)
        if text:
            pair = _geometry_point_pair(geometry_spec, geometry_ref)
            resolved = _student_coordinate_with_parameters(
                label,
                pair,
                parameter_values or {},
            )
            if resolved:
                text = resolved
            result[geometry_ref] = text
    return result


def _student_coordinate_with_parameters(
    label: str,
    pair: list[str] | None,
    parameter_values: Mapping[str, str],
) -> str:
    """Evaluate an already-visible coordinate under verified frame state."""

    if not label or pair is None or len(pair) != 2:
        return ""
    substitutions: dict[sp.Symbol, sp.Expr] = {}
    try:
        substitutions = {
            sp.Symbol(str(name)): sp.sympify(str(value))
            for name, value in parameter_values.items()
        }
        values = tuple(
            sp.simplify(sp.sympify(str(component)).subs(substitutions))
            for component in pair
        )
    except Exception:
        return ""
    return (
        f"{label}("
        + ",".join(
            student_math_display(value, fullwidth_operators=True)
            for value in values
        )
        + ")"
    )


def _restrict_coordinate_labels_to_visible_facts(
    items: list[JsonObject],
    visible_coordinate_texts_by_ref: dict[str, str],
) -> list[JsonObject]:
    """Prevent a scene component from revealing a later coordinate result."""

    result: list[JsonObject] = []
    for item in items:
        if str(item.get("component") or "") != "CoordinateLabel":
            result.append(item)
            continue
        geometry_ref = str(item.get("at") or "")
        text = visible_coordinate_texts_by_ref.get(geometry_ref)
        if not text:
            continue
        visible = copy.deepcopy(item)
        visible["text"] = text
        result.append(visible)
    return result


def _point_label_for_runtime_coordinate_fact(
    item: dict[str, Any],
    source_steps: dict[str, dict[str, Any]],
    source_key: str | None = None,
) -> str:
    source_step_id = source_key or str(item.get("source_step_id") or "")
    source_step = source_steps.get(source_step_id)
    if source_step:
        labels = _point_labels_for_coordinate_source(source_step)
        if len(labels) == 1:
            return next(iter(labels))
    name = str(item.get("name") or "")
    if name:
        labels = _point_labels_from_handle_text(name)
        if len(labels) == 1:
            return next(iter(labels))
    handle = str(item.get("handle") or "")
    labels = _point_labels_from_handle_text(handle)
    if len(labels) == 1:
        return next(iter(labels))
    return ""


def _point_fact_source_key(
    item: dict[str, Any],
    source_order: dict[str, int],
) -> str:
    source_step_id = str(item.get("source_step_id") or "")
    if source_step_id in source_order:
        return source_step_id
    scope_id = str(item.get("scope_id") or "")
    if scope_id in source_order:
        return scope_id
    return ""


def _point_labels_for_coordinate_source(step: dict[str, Any]) -> set[str]:
    target = step.get("target")
    if isinstance(target, str):
        target_labels = _point_labels_from_handle_text(target)
        if len(target_labels) == 1:
            return target_labels
    labels: set[str] = set()
    for produced in step.get("produces") or ():
        if not isinstance(produced, dict):
            continue
        handle = str(produced.get("handle") or "")
        handle_labels = _point_labels_from_handle_text(handle)
        if len(handle_labels) == 1:
            return handle_labels
        labels.update(handle_labels)
        description = str(produced.get("description") or "")
        labels.update(_capital_point_labels(description))
    return labels


def _point_labels_from_handle_text(handle: str) -> set[str]:
    name = handle.rsplit(":", 1)[-1].split(".", 1)[-1]
    name = re.sub(r"_(coordinate|coord|point|value|expr|expression|candidate|candidates)$", "", name)
    labels = _capital_point_labels(name)
    for chunk in re.findall(r"[A-Z]{2,}", name):
        labels.update(chunk)
    return labels


def _capital_point_labels(text: str) -> set[str]:
    labels = set(re.findall(r"(?<![A-Za-z])[A-Z](?![A-Za-z])", text))
    for chunk in re.findall(r"(?<![A-Za-z])([A-Z]{2,})(?![A-Za-z])", text):
        labels.update(chunk)
    return labels


def _is_point_value(value: Any) -> bool:
    return isinstance(value, list | tuple) and len(value) == 2


def _is_point_list_value(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and bool(value)
        and all(_is_point_value(item) for item in value)
        and not all(not isinstance(item, list | tuple) for item in value)
    )


def _point_value_text(value: Any) -> str:
    return ", ".join(
        student_math_display(item, fullwidth_operators=True)
        for item in value
    )


def _scope_root(scope_id: str) -> str:
    return _shared_scope_root(scope_id)


def _fact_step_id(item: dict[str, Any]) -> str:
    return str(item.get("source_step_id") or item.get("scope_id") or "")


def _expression_env_handles(expression_env: Any) -> tuple[str, ...]:
    if isinstance(expression_env, dict):
        return tuple(str(key) for key in expression_env)
    if isinstance(expression_env, list):
        out: list[str] = []
        for item in expression_env:
            if isinstance(item, dict) and item.get("name"):
                out.append(str(item["name"]))
            elif isinstance(item, str):
                out.append(item)
        return tuple(out)
    return ()
