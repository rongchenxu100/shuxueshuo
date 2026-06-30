"""VS1 forward builder from LessonIR to VisualStepIR."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
import copy
import json
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonIR, LessonStep
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry

from .models import JsonObject, VisualStep, VisualStepIR
from .animation import AnimationTimelineBuilder
from .lesson_shell import (
    default_t as _default_t,
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
from .parametric import ParametricExpressionResolver
from .registry import default_layer_registry
from .scene_items import (
    dedupe_scene_items as _dedupe_scene_items,
    focus_handles as _focus_handles,
    visual_gap as _visual_gap,
)
from .geometry_naming import (
    GeometryPointScopeNamer,
    axis_parameter_candidate_point_id,
    axis_parameter_point_id,
    locus_line_endpoint_id,
    scope_root as _shared_scope_root,
    square_projection_point_id,
)
from .role_binders import VisualGeometryIndex, VisualRoleBinderRegistry, VisualRoleBindings
from .sympy_helpers import sympy_pair


@dataclass(frozen=True)
class VisualAuthoringBase:
    """Authored geometry/page shell.

    This remains available for VS0 round-trip/golden comparison.  The VS1
    product path should use GeneratedVisualBase instead.
    """

    geometry_spec: JsonObject
    lesson_data: JsonObject
    step_decorations: JsonObject

    @classmethod
    def from_lesson_spec_dir(cls, path: str | Path) -> "VisualAuthoringBase":
        base = Path(path)
        return cls(
            geometry_spec=json.loads((base / "geometry-spec.json").read_text(encoding="utf-8")),
            lesson_data=json.loads((base / "lesson-data.json").read_text(encoding="utf-8")),
            step_decorations=json.loads((base / "step-decorations.json").read_text(encoding="utf-8")),
        )


@dataclass(frozen=True)
class GeneratedVisualBase:
    """Generated geometry/page shell for the VS1 product path."""

    geometry_spec: JsonObject
    lesson_data: JsonObject
    layers: dict[str, JsonObject]
    default_t: float

    @classmethod
    def from_snapshot(cls, snapshot: ExplanationSnapshot, lesson: LessonIR) -> "GeneratedVisualBase":
        geometry_spec = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
        default_t = _parameter_default_value(snapshot)
        lesson_data = _generated_lesson_shell(snapshot=snapshot, lesson=lesson, default_t=default_t)
        layers = BaseSceneBuilder().build(
            geometry_spec=geometry_spec,
            lesson=lesson,
            snapshot=snapshot,
        )
        return cls(
            geometry_spec=geometry_spec,
            lesson_data=lesson_data,
            layers=layers,
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
class _SceneVisualRule:
    handler: Callable[[_SceneBuildContext], list[JsonObject]]
    capability_ids: tuple[str, ...] = ()
    substep_ids: tuple[str, ...] = ()
    recipe_without_substeps: tuple[str, ...] = ()

    def applies(self, context: _SceneBuildContext) -> bool:
        if self.capability_ids and context.capabilities.intersection(self.capability_ids):
            return True
        if self.substep_ids and context.substeps.intersection(self.substep_ids):
            return True
        if self.recipe_without_substeps and not context.substeps:
            return bool(context.capabilities.intersection(self.recipe_without_substeps))
        return False


@dataclass(frozen=True)
class _PointVisualStyle:
    color: str = COLOR_ACCENT
    dx: int = 14
    dy: int = -18


POINT_ACTIVE = _PointVisualStyle(color=COLOR_ACCENT)
POINT_RESULT = _PointVisualStyle(color=COLOR_RESULT)
POINT_AUXILIARY = _PointVisualStyle(color=COLOR_RESULT, dy=18)
POINT_MOVING = _PointVisualStyle(color=COLOR_ACCENT)


class GeometrySpecBuilder:
    """Generate a minimal renderable geometry-spec from successful runtime facts."""

    def build(self, *, snapshot: ExplanationSnapshot, lesson: LessonIR) -> JsonObject:
        parameter_name = _parameter_name(snapshot)
        default_t = _parameter_default_value(snapshot)
        fixed_points, moving_points, point_meta = _geometry_points_from_snapshot(snapshot, lesson, default_t)
        curves = _curves_from_snapshot(snapshot)
        _add_defined_points_from_curves(
            snapshot=snapshot,
            lesson=lesson,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            curves=curves,
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
        domain = _domain_from_geometry_points(
            fixed_points,
            moving_points,
            curves,
            parameter_name,
            default_t,
        )
        _add_locus_line_endpoint_points(
            snapshot=snapshot,
            lesson=lesson,
            fixed=fixed_points,
            moving=moving_points,
            point_meta=point_meta,
            parameter_name=parameter_name,
            domain=domain,
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


class BaseSceneBuilder:
    """Generate global and section base layers from generated geometry."""

    def build(
        self,
        *,
        geometry_spec: JsonObject,
        lesson: LessonIR,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, JsonObject]:
        layers: dict[str, JsonObject] = {
            "global": {"elements": [{"type": "grid"}]},
        }
        section_step_ids: dict[str, list[str]] = {}
        for step in lesson.steps:
            section_step_ids.setdefault(_scope_root(step.scope_id), []).append(step.id)

        for section_scope, step_ids in sorted(section_step_ids.items()):
            index = VisualGeometryIndex.default(geometry_spec, snapshot.problem)
            layers[f"section:{section_scope}"] = {
                "elements": _base_elements_for_section(
                    section_scope,
                    geometry_spec,
                    snapshot=snapshot,
                    index=index,
                ),
                "stepIds": step_ids,
                "stepStartsWith": step_ids,
            }
        return layers


class VisualStepBuilder:
    """Build static VisualStepIR from successful explanation artifacts."""

    def build(
        self,
        *,
        snapshot: ExplanationSnapshot,
        lesson: LessonIR,
        authoring_base: VisualAuthoringBase | None = None,
        generated_base: GeneratedVisualBase | None = None,
    ) -> VisualStepIR:
        base = generated_base
        legacy_authoring_base = authoring_base
        if base is None:
            if legacy_authoring_base is None:
                base = GeneratedVisualBase.from_snapshot(snapshot, lesson)
            else:
                base = GeneratedVisualBase(
                    geometry_spec=legacy_authoring_base.geometry_spec,
                    lesson_data=legacy_authoring_base.lesson_data,
                    layers=_layers_for_lesson(lesson, legacy_authoring_base.step_decorations),
                    default_t=_default_t(legacy_authoring_base.lesson_data),
                )
        lesson_data = _lesson_data_from_lesson_ir(lesson, base.lesson_data)
        layers = copy.deepcopy(base.layers)
        binder = VisualRoleBinderRegistry.default(base.geometry_spec, snapshot.problem)
        steps = tuple(
            _visual_step_for_lesson_step(
                lesson_step,
                snapshot=snapshot,
                geometry_spec=base.geometry_spec,
                bindings=binder.bind(lesson_step, snapshot),
            )
            for lesson_step in lesson.steps
        )
        return VisualStepIR(
            version=1,
            problem_id=lesson.problem_id,
            geometry_spec=copy.deepcopy(base.geometry_spec),
            lesson_data=lesson_data,
            layers=layers,
            layer_registry=dict(default_layer_registry().semantic_to_layer),
            steps=steps,
            metadata={
                "source": "vs1_visual_step_builder",
                "base_source": "generated" if legacy_authoring_base is None else "authored_legacy",
                "scene_model": "section_accumulator",
            },
        )


def _layers_for_lesson(lesson: LessonIR, base_step_decorations: JsonObject) -> dict[str, JsonObject]:
    raw_layers = copy.deepcopy((base_step_decorations or {}).get("layers") or {})
    registry = default_layer_registry()
    layers: dict[str, JsonObject] = {}
    for layer_key, raw_layer in raw_layers.items():
        semantic_ref = registry.semantic_for_layer_key(str(layer_key))
        if semantic_ref == "global" or semantic_ref.startswith("section:"):
            layers[semantic_ref] = raw_layer

    layers.setdefault("global", {"elements": [{"type": "grid"}]})
    section_roots = sorted({_scope_root(step.scope_id) for step in lesson.steps})
    for section_root in section_roots:
        semantic_ref = f"section:{section_root}"
        layer = layers.setdefault(semantic_ref, {"elements": []})
        layer["stepIds"] = [
            step.id for step in lesson.steps if _scope_root(step.scope_id) == section_root
        ]
        layer["stepStartsWith"] = [
            step.id for step in lesson.steps if _scope_root(step.scope_id) == section_root
        ]
    return layers


def _geometry_points_from_snapshot(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    default_t: float,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, JsonObject]]:
    parameter_name = _parameter_name(snapshot)
    parameter_scope = _parameter_scope_id(snapshot)
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    axis_parameter_samples = _axis_parameter_samples(snapshot, namer)
    fixed: dict[str, list[str]] = {}
    moving: dict[str, list[str]] = {}
    point_meta: dict[str, JsonObject] = {}

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
            geometry_id = namer.scope_namer.geometry_id(label, scope_id)
            fixed.setdefault(geometry_id, pair)
            point_meta.setdefault(
                geometry_id,
                {"label": label, "scopeId": scope_id, "scopeRoot": _scope_root(scope_id)},
            )
        elif definition == "coordinate_origin":
            fixed.setdefault(label or "O", ["0", "0"])
            point_meta.setdefault(
                label or "O",
                {"label": label or "O", "scopeId": str(entity.get("scope_id") or "problem"), "scopeRoot": "problem"},
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
        if _pair_has_internal_axis_parameter(pair):
            scope_id = namer._visual_scope_for_fact(item)
            visual_pair = _axis_parameter_visual_pair(pair, axis_parameter_samples, scope_id)
            if visual_pair is None:
                continue
            raw_label = namer._raw_label_for_fact(item)
            geometry_id = axis_parameter_point_id(raw_label or label, scope_id)
            point_meta[geometry_id] = namer.scope_namer.point_meta(raw_label or label, scope_id)
            if _pair_depends_on_parameter(visual_pair, parameter_name):
                moving[geometry_id] = visual_pair
            else:
                fixed[geometry_id] = visual_pair
            continue
        point_meta[label] = namer.point_meta_for_fact(item)
        if _pair_depends_on_parameter(pair, parameter_name):
            moving[label] = pair
        else:
            fixed[label] = pair

    _move_duplicate_dynamic_points(fixed, moving, parameter_name)
    return dict(sorted(fixed.items())), dict(sorted(moving.items())), dict(sorted(point_meta.items()))


def _axis_parameter_samples(
    snapshot: ExplanationSnapshot,
    namer: GeometryPointNamer,
) -> dict[tuple[str, str], str]:
    samples: dict[tuple[str, str], str] = {}
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        if item.get("source") != "quadratic_axis_parameterized_point":
            continue
        value = item.get("value")
        if not _is_point_value(value):
            continue
        pair = _page_point_pair(value)
        parameter = _axis_parameter_symbol(pair)
        if not parameter:
            continue
        label = namer._raw_label_for_fact(item)
        scope_id = namer._visual_scope_for_fact(item)
        candidate = _answer_candidate_for_axis_parameter(
            snapshot.answers.get(scope_id),
            label=label,
            parameter_pair=pair,
        )
        if candidate is None:
            continue
        samples[(scope_id, parameter)] = candidate
    return samples


def _axis_parameter_symbol(pair: list[str]) -> str:
    for expr in pair:
        match = re.search(r"(?<![A-Za-z0-9_])(_axis_param_[A-Za-z0-9_]+)", str(expr))
        if match:
            return match.group(1)
    return ""


def _answer_candidate_for_axis_parameter(
    answers_for_scope: Any,
    *,
    label: str,
    parameter_pair: list[str],
) -> str | None:
    if not isinstance(answers_for_scope, dict) or not label:
        return None
    raw_answer = answers_for_scope.get(label)
    candidates: list[Any]
    if _is_point_list_value(raw_answer):
        candidates = list(raw_answer)
    elif _is_point_value(raw_answer):
        candidates = [raw_answer]
    else:
        return None
    parameter_index = _axis_parameter_index(parameter_pair)
    if parameter_index is None:
        return None
    candidate = _representative_point_candidate(candidates, parameter_index)
    if candidate is None:
        return None
    return _page_expr(candidate[parameter_index])


def _axis_parameter_index(pair: list[str]) -> int | None:
    for index, expr in enumerate(pair):
        if re.search(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", str(expr)):
            return index
    return None


def _representative_point_candidate(candidates: list[Any], parameter_index: int) -> Any | None:
    valid = [candidate for candidate in candidates if _is_point_value(candidate)]
    if not valid:
        return None
    try:
        import sympy as sp

        return max(
            valid,
            key=lambda item: float(sp.N(sp.sympify(str(item[parameter_index])))),
        )
    except Exception:
        return valid[0]


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

    Runtime only emits points that a StepIntent explicitly asks for.  The page,
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
            geometry_id = namer.scope_namer.geometry_id(label, scope_id)
            if _pair_depends_on_parameter(pair, parameter_name):
                moving.setdefault(geometry_id, pair)
            else:
                fixed.setdefault(geometry_id, pair)
            point_meta.setdefault(
                geometry_id,
                namer.scope_namer.point_meta(label, scope_id),
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
        scope_id = str(fact.get("scope_id") or "")
        labels = [_label_from_square_vertex_handle(handle, snapshot) for handle in vertices[:4]]
        if any(not label for label in labels):
            continue
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
        if opposite_id in all_points:
            opposite = all_points[opposite_id]
        else:
            start = all_points.get(start_id)
            end = all_points.get(end_id)
            target = all_points.get(target_id)
            if start is None or end is None or target is None:
                continue
            opposite = _derive_square_fourth_vertex(start=start, end=end, adjacent=target)
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
        start = all_points.get(start_id)
        end = all_points.get(end_id)
        target = all_points.get(target_id)
        if start is None or end is None or target is None or opposite is None:
            continue
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
    for step in snapshot.effective_steps:
        if not isinstance(step, dict) or step.get("recipe_hint") != "point_candidates_from_curve_point_condition":
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


def _add_locus_line_endpoint_points(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    point_meta: dict[str, JsonObject],
    parameter_name: str,
    domain: JsonObject,
) -> None:
    source_ids = {
        source_id
        for step in lesson.steps
        for source_id in step.source_step_ids
        if "parameterized_point_locus_line" in step.capability_ids
    }
    if not source_ids:
        return
    effective_steps = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    all_points = {**fixed, **moving}
    for source_id in sorted(source_ids):
        step = effective_steps.get(source_id)
        if not step:
            continue
        line = _runtime_line_for_locus_step(step, snapshot)
        if not isinstance(line, dict):
            continue
        label = _locus_point_label_for_step(step) or _label_from_locus_target(str(step.get("target") or ""))
        if not label:
            continue
        endpoints = _locus_line_endpoint_pairs(line, domain)
        if endpoints is None:
            continue
        scope_id = str(step.get("scope_id") or "")
        for side, pair in zip(("start", "end"), endpoints, strict=True):
            point_id = locus_line_endpoint_id(label, scope_id, side)
            _add_structural_visual_point(
                fixed=fixed,
                moving=moving,
                all_points=all_points,
                point_meta=point_meta,
                point_id=point_id,
                label="",
                scope_id=scope_id,
                pair=pair,
                parameter_name=parameter_name,
            )


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
        if step_id and str(item.get("scope_id") or "") == step_id:
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
    geometry_id = namer.scope_namer.geometry_id(label, scope_id)
    return all_points.get(geometry_id) or all_points.get(label)


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
        if source_step_id and str(item.get("scope_id") or "") == source_step_id:
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
        if str(item.get("scope_id") or "") == step_id:
            score += 10
        if str(item.get("source_step_id") or "") == step_id:
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
    if any(expr.free_symbols for expr in (a, b, c)):
        return []
    if sp.simplify(a) == 0:
        return []
    x = sp.Symbol("x")
    roots = [sp.simplify(root) for root in sp.solve(sp.Eq(a * x * x + b * x + c, 0), x)]
    real_roots = [root for root in roots if root.is_real is not False]
    return sorted(real_roots, key=lambda item: float(sp.N(item)))


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
            auxiliary = (
                self._auxiliary_label_from_equal_length_roles(item)
                or self._auxiliary_label_from_equal_length_lesson(item)
            )
            if auxiliary:
                return auxiliary
        if str(item.get("source") or "") == "select_straightening_candidate":
            reflected = self._reflected_label_from_straightening_candidate(item)
            if reflected:
                return reflected
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
                    trace.method_id == source_method and trace.source_step_id == step_id
                    for trace in self.snapshot.teaching_trace
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

    def _auxiliary_label_from_equal_length_lesson(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        if not source_step_id:
            return ""
        texts = self._equal_length_lesson_texts(source_step_id)
        for text in texts:
            match = re.search(r"构造(?:辅助点|点)?\s*([A-Z][A-Za-z0-9_]*)", text)
            if match:
                return match.group(1)
        for text in texts:
            match = re.search(r"\b([A-Z][A-Za-z0-9_]*)\(", text)
            if match:
                return match.group(1)
        return ""

    def _auxiliary_label_from_equal_length_roles(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        source_step = self.steps_by_id.get(source_step_id)
        if not source_step or source_step.get("recipe_hint") != "equal_length_ray_path_reduction":
            return ""
        segment_moving = ""
        ray_moving = ""
        anchor = ""
        for handle in source_step.get("reads") or ():
            if not isinstance(handle, str):
                continue
            fact = self.facts_by_handle.get(handle)
            if not fact:
                continue
            fact_type = str(fact.get("type") or "")
            if fact_type == "point_on_segment":
                segment_moving = self._point_label_from_entity_handle(str(fact.get("point") or ""))
            elif fact_type == "point_on_ray":
                ray_moving = self._point_label_from_entity_handle(str(fact.get("point") or ""))
                ray_entity = self.entities_by_handle.get(str(fact.get("ray") or "")) or {}
                anchor = anchor or self._point_label_from_entity_handle(
                    str(ray_entity.get("origin") or "")
                )
            elif fact_type == "equal_length_condition":
                anchor = anchor or _common_label_in_segments(
                    [
                        str(fact.get("left") or ""),
                        str(fact.get("right") or ""),
                    ]
                )
        if not segment_moving:
            return ""

        for text in self._equal_length_lesson_texts(source_step_id):
            for left, right in re.findall(
                r"([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})*)\s*=\s*([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})*)",
                text,
            ):
                auxiliary = _auxiliary_label_from_path_equation(
                    left,
                    right,
                    segment_moving=segment_moving,
                    ray_moving=ray_moving,
                    anchor=anchor,
                )
                if auxiliary:
                    return auxiliary
        return ""

    def _equal_length_lesson_texts(self, source_step_id: str) -> list[str]:
        texts: list[str] = []
        for step in self.lesson.steps:
            if source_step_id not in step.source_step_ids:
                continue
            if "equal_length_ray_path_reduction" not in step.capability_ids:
                continue
            texts.append(step.title)
            texts.extend(text for _tag, text in step.derive)
            texts.extend(step.box)
        return texts

    def _point_label_from_entity_handle(self, handle: str) -> str:
        entity = self.entities_by_handle.get(handle) or {}
        return str(entity.get("name") or _handle_tail(handle))

    def _reflected_label_from_straightening_candidate(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        item_pair = _sympy_pair_value(item.get("value"))
        fallback = ""
        for fact in self.snapshot.fact_index.values():
            if not isinstance(fact, dict) or fact.get("type") != "StraighteningCandidate":
                continue
            value = fact.get("value")
            if not isinstance(value, dict):
                continue
            label = str(value.get("reflected_point_name") or "")
            if not label:
                continue
            if not fallback:
                fallback = label
            fact_step_id = self._source_step_id_for_fact(fact)
            if source_step_id and fact_step_id and fact_step_id != source_step_id:
                continue
            reflected_pair = _sympy_pair_value(value.get("reflected_point"))
            if item_pair is not None and reflected_pair is not None and not _same_point_pair_value(item_pair, reflected_pair):
                continue
            return label
        if item_pair is not None:
            return ""
        return fallback


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


def _move_duplicate_dynamic_points(
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    parameter_name: str,
) -> None:
    for label in list(fixed):
        pair = fixed[label]
        if _pair_depends_on_parameter(pair, parameter_name):
            moving[label] = fixed.pop(label)
    for label in set(fixed).intersection(moving):
        fixed.pop(label, None)


def _auxiliary_label_from_path_equation(
    left: str,
    right: str,
    *,
    segment_moving: str,
    ray_moving: str,
    anchor: str = "",
) -> str:
    left_terms = _segment_terms(left)
    right_terms = _segment_terms(right)
    if not left_terms or not right_terms:
        return ""

    common_terms = set(left_terms).intersection(right_terms)
    reduced_terms: list[str] = []
    if ray_moving and any(ray_moving in term for term in left_terms):
        reduced_terms = right_terms
    elif ray_moving and any(ray_moving in term for term in right_terms):
        reduced_terms = left_terms
    else:
        for terms in (left_terms, right_terms):
            candidates = [
                term
                for term in terms
                if term not in common_terms and segment_moving in term
            ]
            if candidates:
                reduced_terms = terms
                break

    for term in reduced_terms:
        if term in common_terms or segment_moving not in term:
            continue
        auxiliary = _other_endpoint(term, segment_moving)
        if auxiliary and auxiliary != anchor:
            return auxiliary
    return ""


def _segment_terms(value: str) -> list[str]:
    return re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", value or "")


def _common_label_in_segments(segments: list[str]) -> str:
    labels = [set(_capital_point_labels(segment)) for segment in segments if segment]
    if len(labels) < 2:
        return ""
    common = set.intersection(*labels)
    return next(iter(common), "")


def _other_endpoint(segment: str, endpoint: str) -> str:
    if len(segment) != 2 or endpoint not in segment:
        return ""
    return segment[0] if segment[1] == endpoint else segment[1]


def _curves_from_snapshot(snapshot: ExplanationSnapshot) -> list[JsonObject]:
    steps_by_id = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    curves_by_key: dict[tuple[str, tuple[str, str, str]], tuple[dict[str, Any], tuple[str, str, str], int]] = {}
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
        key = (_scope_root(scope_id), coeffs)
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


def _base_elements_for_section(
    section_scope: str,
    geometry_spec: JsonObject,
    *,
    snapshot: ExplanationSnapshot,
    index: VisualGeometryIndex,
) -> list[JsonObject]:
    elements: list[JsonObject] = []
    for curve_id in _curve_ids_for_section(geometry_spec, section_scope):
        elements.append(
            {
                "type": "parabola",
                "curveId": curve_id,
                "color": COLOR_CURVE,
                "width": 2.2,
            }
        )
    elements.extend(_base_relation_elements(section_scope, snapshot, index))
    elements.extend(_base_point_elements(section_scope, snapshot, index))
    return _dedupe_low_level_elements(elements)


def _curve_ids_for_section(geometry_spec: JsonObject, section_scope: str) -> list[str]:
    out: list[str] = []
    for curve in geometry_spec.get("curves") or ():
        if not isinstance(curve, dict) or not curve.get("id"):
            continue
        scope_root = str(curve.get("scopeRoot") or _scope_root(str(curve.get("scopeId") or "")))
        if scope_root == section_scope:
            out.append(str(curve["id"]))
    return out


def _base_relation_elements(
    section_scope: str,
    snapshot: ExplanationSnapshot,
    index: VisualGeometryIndex,
) -> list[JsonObject]:
    elements: list[JsonObject] = []
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or not _entity_visible_in_section(entity, section_scope):
            continue
        entity_type = str(entity.get("entity_type") or "")
        if entity_type == "segment":
            points = _relation_endpoint_points(entity.get("endpoints"), section_scope, index)
            if points is None or not _relation_uses_problem_points(entity, index):
                continue
            start, end = points
            elements.append(
                {
                    "type": "coloredLine",
                    "from": start,
                    "to": end,
                    "color": COLOR_MUTED,
                    "width": 1.6,
                }
            )
        elif entity_type == "ray":
            points = _relation_endpoint_points(
                (entity.get("origin"), entity.get("through")),
                section_scope,
                index,
            )
            if points is None or not _relation_uses_problem_points(entity, index):
                continue
            origin, through = points
            elements.append(
                {
                    "type": "coloredLine",
                    "from": origin,
                    "to": through,
                    "color": COLOR_MUTED,
                    "width": 1.4,
                }
            )
    return elements


def _base_point_elements(
    section_scope: str,
    snapshot: ExplanationSnapshot,
    index: VisualGeometryIndex,
) -> list[JsonObject]:
    elements: list[JsonObject] = []
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        if str(entity.get("scope_id") or "problem") != "problem":
            continue
        if entity.get("definition") == "coordinate_origin":
            continue
        geometry_id = index.point_for_entity(entity, section_scope)
        if not geometry_id:
            continue
        label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        elements.append(
            {
                "type": "point",
                "at": geometry_id,
                "labelText": label,
                "color": COLOR_MUTED if geometry_id in (index.geometry_spec.get("movingPoints") or {}) else COLOR_TEXT,
                "dx": 10,
                "dy": -12,
            }
        )
    return elements


def _entity_visible_in_section(entity: dict[str, Any], section_scope: str) -> bool:
    scope_id = str(entity.get("scope_id") or "problem")
    if scope_id == "problem":
        return True
    return _scope_root(scope_id) == section_scope


def _relation_endpoint_points(
    raw_endpoints: Any,
    section_scope: str,
    index: VisualGeometryIndex,
) -> tuple[str, str] | None:
    if not isinstance(raw_endpoints, (list, tuple)) or len(raw_endpoints) != 2:
        return None
    start = index.point_for_handle(str(raw_endpoints[0]), section_scope)
    end = index.point_for_handle(str(raw_endpoints[1]), section_scope)
    if not start or not end:
        return None
    return (start, end)


def _relation_uses_problem_points(entity: dict[str, Any], index: VisualGeometryIndex) -> bool:
    handles: list[str] = []
    endpoints = entity.get("endpoints")
    if isinstance(endpoints, list):
        handles.extend(str(item) for item in endpoints)
    for key in ("origin", "through"):
        if entity.get(key):
            handles.append(str(entity[key]))
    for handle in handles:
        point = index.entities_by_handle.get(handle)
        if point is None or point.get("entity_type") != "point":
            return False
        if str(point.get("scope_id") or "problem") != "problem":
            return False
    return bool(handles)


def _dedupe_low_level_elements(elements: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    out: list[JsonObject] = []
    for item in elements:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        line_key = ""
        if item.get("type") == "coloredLine":
            endpoints = sorted([str(item.get("from") or ""), str(item.get("to") or "")])
            line_key = f"coloredLine:{endpoints[0]}:{endpoints[1]}"
        key = line_key or key
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _parameter_default_value(snapshot: ExplanationSnapshot) -> float:
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "ParameterValue":
            continue
        try:
            import sympy as sp

            return float(sp.N(sp.sympify(str(item.get("value")))))
        except Exception:
            continue
    return 0.75


def _parameter_scope_id(snapshot: ExplanationSnapshot) -> str:
    for item in snapshot.fact_index.values():
        if isinstance(item, dict) and item.get("type") == "ParameterValue":
            scope_id = str(item.get("scope_id") or "")
            if scope_id:
                return scope_id
    return ""


def _page_point_pair(value: Any) -> list[str]:
    return [_page_expr(value[0]), _page_expr(value[1])]


def _axis_parameter_visual_pair(
    pair: list[str],
    samples: dict[tuple[str, str], str],
    scope_id: str,
) -> list[str] | None:
    if len(pair) != 2:
        return None
    parameter = _axis_parameter_symbol(pair)
    sample = samples.get((scope_id, parameter), "")
    return [
        _replace_axis_parameter_with_sample(pair[0], sample),
        _replace_axis_parameter_with_sample(pair[1], sample),
    ]


def _replace_axis_parameter_with_sample(expr: str, sample: str = "") -> str:
    replaced = re.sub(
        r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+",
        sample or "1",
        str(expr),
    )
    return _page_expr(replaced)


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


def _pair_has_internal_axis_parameter(pair: list[str]) -> bool:
    return any(re.search(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", str(part)) for part in pair)


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


def _visual_step_for_lesson_step(
    lesson_step: LessonStep,
    *,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
    bindings: VisualRoleBindings,
) -> VisualStep:
    interactions = ParametricExpressionResolver(
        geometry_spec=geometry_spec,
        default_t=_parameter_default_value(snapshot),
    ).interactions_for_step(lesson_step, bindings)
    timeline = AnimationTimelineBuilder().timeline_for_step(
        lesson_step,
        bindings,
        interactions=interactions,
    )
    coordinate_texts = _verified_coordinate_texts_for_lesson_step(
        lesson_step,
        snapshot,
    )
    for key, value in bindings.coordinate_texts_by_ref.items():
        coordinate_texts.setdefault(key, value)
    scene_add = _scene_add_for_lesson_step(
        lesson_step,
        bindings,
        coordinate_texts=coordinate_texts,
    )
    scene = {
        "inherits_from": f"section:{_scope_root(lesson_step.scope_id)}",
        "add": scene_add,
        "state_overrides": _state_overrides_for_lesson_step(lesson_step),
        "hide": _hide_handles_for_lesson_step(
            lesson_step,
            snapshot,
            geometry_spec,
            scene_add=scene_add,
        ),
        "focus": {
            "primary": _focus_handles(scene_add),
            "dim": [],
        },
        "annotations": _annotations_for_lesson_step(lesson_step),
    }
    return VisualStep(
        visual_step_id=f"visual:{lesson_step.id}",
        lesson_step_id=lesson_step.id,
        scope_id=lesson_step.scope_id,
        geometry_context={
            "coordinate_system": "cartesian_2d",
            "domain": copy.deepcopy(geometry_spec.get("domain") or {}),
            "domain_override": None,
            "moving_param": geometry_spec.get("movingParam"),
            "expression_env_handles": _expression_env_handles(geometry_spec.get("expressionEnv")),
            "panels": [],
        },
        scene=scene,
        interactions=interactions,
        timeline=timeline,
        metadata={"step_extra": {}},
    )


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
        substeps=frozenset(lesson_step.teaching_substep_ids),
    )
    add = _scene_items_from_visual_specs(context)
    if not add:
        add = [_visual_gap("visual_role", "No static visual spec matched this Lesson step.")]
    return _dedupe_scene_items(add)


def _scene_items_from_visual_specs(context: _SceneBuildContext) -> list[JsonObject]:
    template_items = (
        *_method_visual_template_items(context.capabilities, context.bindings),
        *_recipe_visual_template_items(context.capabilities, context.substeps, context.bindings),
    )
    context = replace(context, template_items=tuple(template_items))
    add: list[JsonObject] = list(template_items)
    for rule in _scene_visual_rules():
        if rule.applies(context):
            add.extend(rule.handler(context))
    return add


def _quadratic_from_constraints_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    if {
        "quadratic_vertex_point",
        "quadratic_x_axis_intercept_point",
    }.intersection(context.capabilities):
        return [*_parabola_items(context.bindings)]
    return [
        *_parabola_items(context.bindings),
        *_coordinate_labels(
            context.points,
            (*context.lesson_step.box, *_derive_texts(context.lesson_step)),
            context.coordinate_texts,
        ),
    ]


def _coordinate_result_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return _coordinate_labels(context.points, context.lesson_step.box, context.coordinate_texts)


def _angle_sum_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_point_items_for_geometry_refs(
            context,
            _point_marker_refs_from_scene_items(context.template_items),
            style=POINT_ACTIVE,
        ),
        *_coordinate_labels(
            context.points,
            (*context.lesson_step.box, *_derive_texts(context.lesson_step)),
            context.coordinate_texts,
            allowed_refs=_angle_coordinate_label_refs(context.template_items),
        ),
    ]


def _axis_intercept_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_point_items_for_geometry_refs(
            context,
            _point_marker_refs_from_scene_items(context.template_items),
            style=POINT_ACTIVE,
        ),
        *_point_items_for_coordinate_conclusions(
            context,
            context.lesson_step.box,
            style=POINT_RESULT,
        ),
        *_coordinate_labels(
            context.points,
            context.lesson_step.box,
            context.coordinate_texts,
            allowed_refs=_equal_acute_intercept_coordinate_label_refs(context.template_items),
        ),
    ]


def _line_parabola_intersection_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_line_if_points(
            context.points,
            "B",
            "E",
            color=COLOR_ACCENT,
            width=2.2,
            handle=_angle_arm_handle(context.lesson_step.scope_id, "BE"),
            state="highlight",
        ),
        *_point_items(context.points, ("E",), style=POINT_RESULT),
        *_point_items(context.points, ("F",), style=POINT_ACTIVE),
        *_coordinate_labels(context.points, context.lesson_step.box, context.coordinate_texts),
    ]


def _equal_length_reduction_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return []


def _minimum_distance_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return _minimum_distance_items(context)


def _parameter_result_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    if "evaluate_point_at_parameter" in context.capabilities:
        return []
    return _parameter_result_items(
        context.points,
        context.lesson_step.box,
        context.coordinate_texts,
    )


@lru_cache(maxsize=1)
def _scene_visual_rules() -> tuple[_SceneVisualRule, ...]:
    return (
        _SceneVisualRule(
            capability_ids=("quadratic_from_constraints",),
            handler=_quadratic_from_constraints_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=(
                "quadratic_y_axis_intercept_point",
                "translated_point",
            ),
            handler=_coordinate_result_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("angle_sum_equal_angle_candidates",),
            handler=_angle_sum_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("axis_intercept_from_equal_acute_angles",),
            handler=_axis_intercept_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("line_parabola_second_intersection_point",),
            handler=_line_parabola_intersection_visual_items,
        ),
        _SceneVisualRule(
            substep_ids=("path_reduction",),
            recipe_without_substeps=("equal_length_ray_path_reduction",),
            handler=_equal_length_reduction_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("distance_between_points",),
            substep_ids=("minimum_by_segment",),
            recipe_without_substeps=("equal_length_ray_path_reduction",),
            handler=_minimum_distance_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("parameter_from_expression_value", "parameter_from_minimum_value"),
            handler=_parameter_result_visual_items,
        ),
    )


def _hide_handles_for_lesson_step(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
    *,
    scene_add: list[JsonObject] | None = None,
) -> list[str]:
    hide: list[str] = []
    hide.extend(
        _same_label_point_current_hides(
            scene_add or [],
            lesson_step,
            geometry_spec,
        )
    )
    hide.extend(_same_label_point_carry_hides(scene_add or [], geometry_spec))
    if "point_candidates_from_curve_point_condition" not in lesson_step.capability_ids:
        return list(dict.fromkeys(hide))
    source_steps = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    namer = GeometryPointScopeNamer.from_geometry_spec(geometry_spec, snapshot.problem)
    known_points = set((geometry_spec.get("fixedPoints") or {}).keys())
    known_points.update((geometry_spec.get("movingPoints") or {}).keys())
    for step_id in lesson_step.source_step_ids:
        step = source_steps.get(step_id)
        if not step:
            continue
        for handle in step.get("reads") or ():
            if not isinstance(handle, str):
                continue
            fact = snapshot.fact_index.get(handle)
            square_source = str((fact or {}).get("source_step_id") or "") if isinstance(fact, dict) else ""
            square_step = source_steps.get(square_source)
            if not square_step or square_step.get("recipe_hint") != "square_adjacent_vertex_from_side":
                continue
            square = _square_fact_for_step_handles(square_step, snapshot)
            if square is None:
                continue
            labels = [_label_from_square_vertex_handle(str(item), snapshot) for item in square.get("vertices", ())[:4]]
            if len(labels) != 4 or any(not label for label in labels):
                continue
            vertices = [
                _primary_square_vertex_id(label, lesson_step.scope_id, known_points, namer)
                for label in labels
            ]
            if any(not point for point in vertices):
                continue
            hide.append(f"visual:square:{square_source}:region")
            hide.extend(f"point:{point}" for point in vertices)
            hide.extend(
                f"line:{square_source}:{start}-{end}"
                for start, end in zip(vertices, (*vertices[1:], vertices[0]), strict=True)
            )
    return list(dict.fromkeys(hide))


def _same_label_point_current_hides(
    scene_add: list[JsonObject],
    lesson_step: LessonStep,
    geometry_spec: JsonObject,
) -> list[str]:
    """Hide same-step point variants that share a student-facing label.

    Merged teaching steps can legitimately mention a parameterized point and a
    later evaluated point with the same name.  The diagram should show the one
    supported by the current step's visible derive/box text, not both.
    """

    points_by_label: dict[str, set[str]] = {}
    label_texts_by_point: dict[str, list[str]] = {}
    for item in scene_add:
        if not isinstance(item, dict):
            continue
        component = str(item.get("component") or item.get("type") or "")
        if component == "Point":
            point_id = str(item.get("at") or "")
            label = str(item.get("labelText") or _point_label_from_geometry(point_id, geometry_spec) or "")
            if point_id and label:
                points_by_label.setdefault(label, set()).add(point_id)
            continue
        if component == "CoordinateLabel":
            point_id = str(item.get("at") or "")
            text = str(item.get("text") or "")
            if point_id and text:
                label_texts_by_point.setdefault(point_id, []).append(text)

    visible_texts = {
        _normalize_visual_text(text)
        for text in (
            *lesson_step.box,
            *(body for _, body in lesson_step.derive),
        )
        if str(text)
    }
    hides: list[str] = []
    for _, point_ids in points_by_label.items():
        if len(point_ids) <= 1:
            continue
        keep = max(
            sorted(point_ids),
            key=lambda point_id: _same_label_point_score(
                point_id,
                label_texts_by_point.get(point_id, ()),
                visible_texts,
            ),
        )
        hides.extend(f"point:{point_id}" for point_id in sorted(point_ids) if point_id != keep)
    return hides


def _same_label_point_score(
    point_id: str,
    label_texts: list[str] | tuple[str, ...],
    visible_texts: set[str],
) -> tuple[int, int, int, str]:
    score = 0
    symbolic = 0
    for text in label_texts:
        normalized = _normalize_visual_text(text)
        if any(normalized and (normalized in visible or visible in normalized) for visible in visible_texts):
            score += 100
        if _looks_parameterized_coordinate(text):
            symbolic = 1
    if "axis" in point_id:
        score += 2
    return (score, symbolic, len(label_texts), point_id)


def _looks_parameterized_coordinate(text: str) -> bool:
    normalized = _normalize_visual_text(text)
    return any(token in normalized for token in ("t", "c", "a", "b", "u"))


def _normalize_visual_text(text: Any) -> str:
    return (
        str(text)
        .replace(" ", "")
        .replace("，", ",")
        .replace("（", "(")
        .replace("）", ")")
        .replace("－", "-")
        .replace("＋", "+")
        .replace("＝", "=")
        .replace("²", "^2")
    )


def _same_label_point_carry_hides(
    scene_add: list[JsonObject],
    geometry_spec: JsonObject,
) -> list[str]:
    """Hide carried point variants when the current step draws the same label.

    A later step can replace a parameterized point with its evaluated point, or
    the other way around for a construction proof.  The visible label is the
    student-facing identity, while geometry ids may differ.  Hiding same-label
    carry variants keeps the diagram from showing two ``E`` or two ``G`` marks
    at almost the same place without hard-coding the letters.
    """

    current_by_label: dict[str, set[str]] = {}
    for item in scene_add:
        if not isinstance(item, dict):
            continue
        component = str(item.get("component") or item.get("type") or "")
        if component != "Point":
            continue
        point_id = str(item.get("at") or "")
        label = str(item.get("labelText") or _point_label_from_geometry(point_id, geometry_spec) or "")
        if not point_id or not label:
            continue
        current_by_label.setdefault(label, set()).add(point_id)
    if not current_by_label:
        return []

    known_by_label: dict[str, set[str]] = {}
    point_ids = set((geometry_spec.get("fixedPoints") or {}).keys())
    point_ids.update((geometry_spec.get("movingPoints") or {}).keys())
    for point_id in point_ids:
        label = _point_label_from_geometry(str(point_id), geometry_spec)
        if label:
            known_by_label.setdefault(label, set()).add(str(point_id))

    hides: list[str] = []
    for label, current_ids in current_by_label.items():
        for point_id in sorted(known_by_label.get(label, set()) - current_ids):
            hides.append(f"point:{point_id}")
    return hides


def _point_label_from_geometry(point_id: str, geometry_spec: JsonObject) -> str:
    meta = (geometry_spec.get("pointMeta") or {}).get(point_id) or {}
    label = str(meta.get("label") or "")
    if label:
        return label
    match = re.match(r"([A-Z][A-Za-z0-9_′]*)", point_id)
    return match.group(1) if match else ""


def _square_fact_for_step_handles(
    step: dict[str, Any],
    snapshot: ExplanationSnapshot,
) -> dict[str, Any] | None:
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        fact = snapshot.fact_index.get(handle)
        if isinstance(fact, dict) and fact.get("type") == "square":
            return fact
        for problem_fact in (snapshot.problem or {}).get("facts") or ():
            if (
                isinstance(problem_fact, dict)
                and str(problem_fact.get("handle") or "") == handle
                and problem_fact.get("type") == "square"
            ):
                return problem_fact
    return None


def _primary_square_vertex_id(
    label: str,
    scope_id: str,
    known_points: set[str],
    namer: GeometryPointScopeNamer,
) -> str:
    axis_id = axis_parameter_point_id(label, scope_id)
    if axis_id in known_points:
        return axis_id
    geometry_id = namer.geometry_id(label, scope_id)
    if geometry_id in known_points:
        return geometry_id
    return label if label in known_points else ""


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
                items.extend(renderer(template, bindings))
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
                    items.extend(renderer(template, bindings))
    return items


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


def _locus_line_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    color = str(template.get("color") or COLOR_CONSTRAINT)
    persistence = str(template.get("persistence") or "carry_forward")
    for marker in bindings.locus_lines:
        start = str(marker.get("from") or "")
        end = str(marker.get("to") or "")
        if not start or not end:
            continue
        handle = f"line:locus:{marker.get('source_step_id') or start + '-' + end}"
        items.append(
            {
                "component": "DashedLine",
                "handle": handle,
                "from": start,
                "to": end,
                "color": color,
                "width": float(template.get("width") or 2.0),
                "dash": str(template.get("dash") or "7 5"),
                "persistence": persistence,
                "decay_state": "muted",
                "metadata": {"low_level_type": "dashedLine"},
            }
        )
        equation = str(marker.get("equation") or "")
        label_point = _locus_line_label_point(template, marker, start, end)
        if equation and label_point:
            items.append(
                {
                    "component": "CoordinateLabel",
                    "at": label_point,
                    "text": equation,
                    "dx": int(template.get("label_dx") or 18),
                    "dy": int(template.get("label_dy") or 36),
                    "metadata": {"low_level_type": "coordinateLabel"},
                }
            )
    return items


def _line_locus_minimum_point_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    locus_color = str(template.get("locus_color") or COLOR_CONSTRAINT)
    minimum_line_color = str(template.get("minimum_line_color") or COLOR_RESULT)
    target_color = str(template.get("target_color") or COLOR_RESULT)
    show_locus_label = bool(template.get("show_locus_label", False))
    for marker in bindings.line_locus_minimum_markers:
        source_step_id = str(marker.get("source_step_id") or "line-locus-minimum")
        locus_line = marker.get("locus_line") if isinstance(marker.get("locus_line"), dict) else {}
        locus_start = str(locus_line.get("from") or "")
        locus_end = str(locus_line.get("to") or "")
        if locus_start and locus_end:
            items.append(
                {
                    "component": "DashedLine",
                    "handle": f"line:line-locus-minimum:{source_step_id}:locus",
                    "from": locus_start,
                    "to": locus_end,
                    "color": locus_color,
                    "width": 2.0,
                    "dash": "7 5",
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "dashedLine"},
                }
            )
            equation = str(locus_line.get("equation") or "")
            if show_locus_label and equation:
                items.append(
                    {
                        "component": "CoordinateLabel",
                        "at": locus_end,
                        "text": equation,
                        "dx": -170,
                        "dy": -14,
                        "metadata": {"low_level_type": "coordinateLabel"},
                    }
                )

        minimum_segment = (
            marker.get("minimum_segment")
            if isinstance(marker.get("minimum_segment"), dict)
            else {}
        )
        minimum_start = str(minimum_segment.get("from") or "")
        minimum_end = str(minimum_segment.get("to") or "")
        minimum_label = str(minimum_segment.get("label") or "")
        if minimum_start and minimum_end:
            items.append(
                {
                    "component": "ColoredLine",
                    "handle": f"line:line-locus-minimum:{source_step_id}:minimum",
                    "from": minimum_start,
                    "to": minimum_end,
                    "color": minimum_line_color,
                    "width": 2.8,
                    "persistence": persistence,
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "coloredLine"},
                }
            )
            if minimum_label:
                items.append(
                    {
                        "component": "Segment",
                        "handle": f"segment:line-locus-minimum:{source_step_id}:minimum",
                        "from": minimum_start,
                        "to": minimum_end,
                        "label": minimum_label,
                        "color": minimum_line_color,
                        "width": 2.8,
                        "offsetPx": 16,
                        "persistence": "step_only",
                        "metadata": {"low_level_type": "segment"},
                    }
                )

        target_point = str(marker.get("target_point") or "")
        if target_point:
            items.extend(
                _point_with_optional_label_items(
                    point=target_point,
                    label=str(marker.get("target_label") or ""),
                    display=str(marker.get("target_display") or ""),
                    color=target_color,
                    persistence=persistence,
                    label_dy=34,
                )
            )
    return items


def _locus_line_label_point(
    template: dict[str, Any],
    marker: dict[str, Any],
    start: str,
    end: str,
) -> str:
    anchor = str(template.get("label_anchor") or "moving_point")
    if anchor in {"start", "line_start"}:
        return start
    if anchor in {"end", "line_end"}:
        return end
    return str(marker.get("moving_point") or "")


def _square_path_dimension_marker_items(
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
    for marker in bindings.square_path_dimension_markers:
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
    if role == "auxiliary_point":
        return POINT_AUXILIARY
    if role == "result_point":
        return POINT_RESULT
    if role == "moving_point":
        return POINT_MOVING
    return POINT_ACTIVE


def _equivalent_segment_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
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


def _broken_path_straightening_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    persistence = str(template.get("persistence") or "carry_forward")
    locus_color = str(template.get("locus_color") or COLOR_CONSTRAINT)
    reflected_color = str(template.get("reflected_color") or COLOR_RESULT)
    path_color = str(template.get("path_color") or COLOR_PATH)
    triangle_fill = str(template.get("triangle_fill") or COLOR_RESULT_REGION_FILL)
    for marker in bindings.broken_path_minimum_markers:
        locus = marker.get("locus_line") if isinstance(marker.get("locus_line"), dict) else {}
        locus_from = str(locus.get("from") or "")
        locus_to = str(locus.get("to") or "")
        if locus_from and locus_to:
            items.append(
                {
                    "component": "DashedLine",
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

        for segment in marker.get("original_segments") or ():
            items.extend(
                _line_from_segment_payload(
                    segment,
                    color=path_color,
                    width=2.0,
                )
            )

        reflection_segment = marker.get("reflection_segment")
        items.extend(
            _dashed_line_from_segment_payload(
                reflection_segment,
                color=reflected_color,
                width=2.2,
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
                )
            )

        minimum_segment = marker.get("minimum_segment")
        items.extend(
            _line_from_segment_payload(
                minimum_segment,
                color=reflected_color,
                width=2.8,
            )
        )
        items.extend(
            _distance_marker_from_segment_payload(
                minimum_segment,
                color=reflected_color,
                width=2.8,
                offset_px=16,
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


def _angle_reference_items(bindings: VisualRoleBindings) -> list[JsonObject]:
    out: list[JsonObject] = []
    for marker in bindings.angle_references:
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
    return _angle_equality_marker_items(template, bindings) + _angle_reference_items(bindings)


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
    return items


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
    "EqualAcuteAngleInterceptMarker": _equal_acute_angle_intercept_marker_items,
    "EvaluatedPointMarker": _evaluated_point_marker_items,
    "LineLocusMinimumPointMarker": _line_locus_minimum_point_marker_items,
    "LocusLineMarker": _locus_line_marker_items,
    "QuadraticAxisXInterceptMarker": _quadratic_axis_x_intercept_marker_items,
    "QuadraticVertexMarker": _quadratic_vertex_marker_items,
    "QuadraticXAxisInterceptMarker": _quadratic_x_axis_intercept_marker_items,
    "SquareAdjacentVertexMarker": _square_adjacent_vertex_marker_items,
    "SquarePathDimensionMarker": _square_path_dimension_marker_items,
    "TranslationAnimation": _empty_visual_template_items,
    "TranslationMarker": _translation_marker_items,
}

_RECIPE_VISUAL_TEMPLATE_RENDERERS: dict[str, _VisualTemplateRenderer] = {
    "AuxiliaryRayGuideMarker": _auxiliary_ray_guide_marker_items,
    "BrokenPathStraighteningMarker": _broken_path_straightening_marker_items,
    "CongruentTriangleMarker": _congruent_triangle_marker_items,
    "EquivalentSegmentMarker": _equivalent_segment_marker_items,
    "PathMinimumTriangleMarker": _path_minimum_triangle_marker_items,
}


def _parameter_result_items(
    points: dict[str, str],
    boxes: tuple[str, ...],
    coordinate_texts: dict[str, str] | None = None,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    items.extend(_point_items(points, ("G",), style=POINT_AUXILIARY))
    items.extend(_point_items(points, ("B",), style=POINT_RESULT))
    items.extend(_line_if_points(points, "O", "G", color=COLOR_RESULT, width=2.8))
    items.extend(_line_if_points(points, "C", "G", color=COLOR_CONSTRAINT, width=2.2))
    items.extend(_distance_marker(points, "O", "G", "OG", color=COLOR_RESULT, width=2.8))
    items.extend(_coordinate_labels(points, boxes, coordinate_texts))
    return items


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
            "persistence": "carry_forward",
            "decay_state": "muted",
            "metadata": {"low_level_type": "coloredLine"},
        }
    ]


def _dashed_line_from_segment_payload(
    segment: Any,
    *,
    color: str,
    width: float,
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
            "persistence": "carry_forward",
            "decay_state": "muted",
            "metadata": {"low_level_type": "dashedLine"},
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
            "persistence": "step_only",
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


def _state_overrides_for_lesson_step(lesson_step: LessonStep) -> list[JsonObject]:
    if "axis_intercept_from_equal_acute_angles" not in lesson_step.capability_ids:
        return []
    return [
        {
            "handle": _angle_arm_handle(lesson_step.scope_id, "BE"),
            "state": "highlight",
        }
    ]


def _angle_arm_handle(scope_id: str, name: str) -> str:
    return f"line:{scope_id}:{name}"


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
        if len(labels) != 1 or len(values) != 1:
            continue
        label = next(iter(labels))
        coordinates[label] = f"{label}({values[0][0]})"
    return coordinates


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
    return f"{value[0]}, {value[1]}"


def _scope_root(scope_id: str) -> str:
    return _shared_scope_root(scope_id)


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
