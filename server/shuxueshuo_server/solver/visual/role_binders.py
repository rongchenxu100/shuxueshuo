"""Role binding helpers for VisualStepIR generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.lesson_ir import (
    OwnedLessonStep as LessonStep,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    iter_teaching_scopes,
    iter_teaching_sources,
)
from shuxueshuo_server.solver.student_display import student_math_display

from .geometry_naming import (
    GeometryPointScopeNamer,
    axis_parameter_candidate_point_id,
    axis_parameter_point_id,
    locus_line_endpoint_id,
    scope_root,
    square_projection_point_id,
)
from .models import JsonObject
from .parameter_identity import (
    parameterized_point_contexts_by_step,
    value_depends_on_symbol,
)
from .sympy_helpers import sympify_visual_expr, sympy_pair as _shared_sympy_pair


PROJECTION_HELPER_LABEL_CANDIDATES = ("Q", "R", "S", "T", "U", "V", "W")


@dataclass(frozen=True)
class VisualRoleBindings:
    """Verified visual handles available to one Lesson step."""

    point_handles: dict[str, str] = field(default_factory=dict)
    coordinate_texts_by_ref: dict[str, str] = field(default_factory=dict)
    curve_ids: tuple[str, ...] = ()
    translation_markers: tuple[dict[str, Any], ...] = ()
    angle_equalities: tuple[dict[str, Any], ...] = ()
    angle_references: tuple[dict[str, Any], ...] = ()
    axis_parameterized_points: tuple[dict[str, Any], ...] = ()
    axis_x_intercept_points: tuple[dict[str, Any], ...] = ()
    square_adjacent_markers: tuple[dict[str, Any], ...] = ()
    vertex_points: tuple[dict[str, Any], ...] = ()
    axis_intercept_markers: tuple[dict[str, Any], ...] = ()
    x_axis_intercept_points: tuple[dict[str, Any], ...] = ()
    equal_length_path_markers: tuple[dict[str, Any], ...] = ()
    atomic_square_reduction_markers: tuple[dict[str, Any], ...] = ()
    atomic_path_minimum_markers: tuple[dict[str, Any], ...] = ()
    curve_point_candidate_markers: tuple[dict[str, Any], ...] = ()
    evaluated_points: tuple[dict[str, Any], ...] = ()
    line_parabola_intersections: tuple[dict[str, Any], ...] = ()
    # Exact source-local roles used by declarative generic components.  Each
    # record is projected from one TeachingSource's verified refs and values;
    # component renderers never rediscover roles from capability names.
    source_roles: tuple[dict[str, Any], ...] = ()
    source_step_ids: tuple[str, ...] = ()
    capability_ids: tuple[str, ...] = ()

    @property
    def point_names(self) -> set[str]:
        return set(self.point_handles)


class VisualGeometryIndex:
    """Map canonical ProblemIR handles to generated geometry ids."""

    def __init__(self, geometry_spec: JsonObject, problem: JsonObject | None = None) -> None:
        self.geometry_spec = geometry_spec
        self.problem = problem or {}
        self.known_points = set((geometry_spec.get("fixedPoints") or {}).keys())
        self.known_points.update((geometry_spec.get("movingPoints") or {}).keys())
        self.scope_namer = GeometryPointScopeNamer.from_geometry_spec(geometry_spec, self.problem)
        self.entities_by_handle: dict[str, dict[str, Any]] = {}
        self.entities_by_name: dict[str, dict[str, Any]] = {}
        self.facts_by_handle: dict[str, dict[str, Any]] = {}
        for fact in self.problem.get("facts") or ():
            if not isinstance(fact, dict):
                continue
            handle = str(fact.get("handle") or "")
            if handle:
                self.facts_by_handle[handle] = fact
        for entity in self.problem.get("entities") or ():
            if not isinstance(entity, dict):
                continue
            handle = str(entity.get("handle") or "")
            if handle:
                self.entities_by_handle[handle] = entity
            name = str(entity.get("name") or "")
            if name and name not in self.entities_by_name:
                self.entities_by_name[name] = entity
        self.origin_labels = frozenset(
            str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            for entity in self.problem.get("entities") or ()
            if isinstance(entity, dict)
            and entity.get("entity_type") == "point"
            and entity.get("definition") == "coordinate_origin"
            and str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        )

    @classmethod
    def default(
        cls,
        geometry_spec: JsonObject,
        problem: JsonObject | None = None,
    ) -> "VisualGeometryIndex":
        return cls(geometry_spec, problem)

    def geometry_point_name(self, label: str, scope_id: str | None) -> str | None:
        for candidate in self.scope_namer.candidate_ids(label, scope_id):
            if candidate in self.known_points:
                if not self._candidate_visible_in_scope(candidate, scope_id):
                    continue
                return candidate
        return None

    def _candidate_visible_in_scope(self, point_id: str, scope_id: str | None) -> bool:
        meta = (self.geometry_spec.get("pointMeta") or {}).get(point_id)
        if not isinstance(meta, dict):
            return True
        point_root = str(meta.get("scopeRoot") or scope_root(str(meta.get("scopeId") or "")))
        if point_root == "problem":
            return True
        return point_root == scope_root(scope_id)

    def point_for_handle(self, handle: str, scope_id: str | None) -> str | None:
        entity = self.entities_by_handle.get(handle)
        if entity is None:
            return None
        return self.point_for_entity(entity, scope_id)

    def point_for_entity(self, entity: dict[str, Any], scope_id: str | None) -> str | None:
        label = str(entity.get("name") or "")
        if not label:
            label = _handle_tail(str(entity.get("handle") or ""))
        if not label:
            return None
        return self.geometry_point_name(label, scope_id)

    def point_entity_for_name_or_handle(self, value: str) -> dict[str, Any] | None:
        if value in self.entities_by_handle:
            return self.entities_by_handle[value]
        return self.entities_by_name.get(value)


def _public_point_semantic_ref(
    snapshot: ExplanationSnapshot,
    source: Any,
    return_name: str,
) -> str:
    """Return a public point identity without parsing presentation text."""

    target = str(source.output_targets.get(return_name) or "")
    if target:
        return target

    goal_refs = {
        goal.goal_ref
        for scope in iter_teaching_scopes(snapshot.root_scope)
        for goal in scope.goals
        if str(goal.answer_from.get("step_id") or "") == source.source_step_id
        and str(goal.answer_from.get("return") or "") == return_name
    }
    answer_handles = {f"answer:{goal_ref}" for goal_ref in goal_refs}
    targets = {
        str(goal.get("target_handle") or "")
        for goal in (snapshot.problem or {}).get("question_goals") or ()
        if isinstance(goal, dict)
        and str(goal.get("handle") or "") in answer_handles
        and str(goal.get("value_type") or "") == "Point"
    }
    targets.discard("")
    if len(targets) > 1:
        raise ValueError(
            "visual_public_point_output_identity_ambiguous: "
            f"step={source.source_step_id}, return={return_name}, "
            f"targets={sorted(targets)}"
        )
    return next(iter(targets), "")


class VisualRoleBinderRegistry:
    """Bind verified public geometry roles to branch-scoped geometry ids."""

    def __init__(self, geometry_spec: JsonObject, problem: JsonObject | None = None) -> None:
        self.geometry_spec = geometry_spec
        self.index = VisualGeometryIndex.default(geometry_spec, problem)
        self._known_points = set((geometry_spec.get("fixedPoints") or {}).keys())
        self._known_points.update((geometry_spec.get("movingPoints") or {}).keys())
        self._curves = tuple(
            dict(curve)
            for curve in geometry_spec.get("curves") or ()
            if isinstance(curve, dict) and curve.get("id")
        )
        self.facts_by_handle = dict(self.index.facts_by_handle)

    @classmethod
    def default(
        cls,
        geometry_spec: JsonObject,
        problem: JsonObject | None = None,
    ) -> "VisualRoleBinderRegistry":
        return cls(geometry_spec, problem)

    def bind(self, lesson_step: LessonStep, snapshot: ExplanationSnapshot) -> VisualRoleBindings:
        source_steps = {
            str(step.get("step_id")): step
            for step in snapshot.effective_steps
            if isinstance(step, dict) and step.get("step_id")
        }
        labels: set[str] = set()
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step:
                continue
            labels.update(_point_labels_from_step(step))
        labels.update(_point_labels_from_lesson_step(lesson_step))
        labels.update(
            self._minimum_expression_dependency_labels(
                lesson_step,
                snapshot,
                source_steps,
            )
        )
        equal_length_roles = self._equal_length_reduction_roles(
            lesson_step,
            snapshot,
            source_steps,
        )
        labels.update(_point_labels_from_equal_length_roles(equal_length_roles))
        square_path_roles = self._atomic_square_reduction_roles(
            lesson_step,
            snapshot,
        )
        labels.update(_point_labels_from_square_path_roles(square_path_roles))
        atomic_path_roles = self._atomic_path_minimum_roles(
            lesson_step,
            snapshot,
            source_steps,
        )
        labels.update(_point_labels_from_atomic_path_roles(atomic_path_roles))
        labels.update(
            self._linked_square_labels_for_atomic_path(
                lesson_step,
                snapshot,
                source_steps,
                atomic_path_roles,
            )
        )

        point_handles: dict[str, str] = {}
        for label in sorted(labels):
            geometry_name = self.index.geometry_point_name(label, lesson_step.scope_id)
            if geometry_name:
                point_handles[label] = geometry_name

        return VisualRoleBindings(
            point_handles=point_handles,
            coordinate_texts_by_ref=self._coordinate_texts_by_ref(point_handles),
            curve_ids=tuple(self._curve_ids_for_scope(lesson_step.scope_id)),
            translation_markers=tuple(
                self._translation_markers(lesson_step, snapshot, source_steps)
            ),
            angle_equalities=tuple(
                self._angle_equalities(
                    lesson_step,
                    snapshot,
                    source_steps,
                    point_handles,
                )
            ),
            angle_references=tuple(self._angle_references(lesson_step, snapshot)),
            axis_parameterized_points=tuple(
                self._axis_parameterized_points(lesson_step, snapshot)
            ),
            axis_x_intercept_points=tuple(
                self._axis_x_intercept_points(lesson_step, source_steps, point_handles)
            ),
            square_adjacent_markers=tuple(
                self._square_adjacent_markers(lesson_step, snapshot, source_steps)
            ),
            curve_point_candidate_markers=tuple(
                self._curve_point_candidate_markers(lesson_step, snapshot)
            ),
            vertex_points=tuple(self._vertex_points(lesson_step)),
            axis_intercept_markers=tuple(
                self._axis_intercept_markers(lesson_step, source_steps, point_handles)
            ),
            x_axis_intercept_points=tuple(
                self._x_axis_intercept_points(lesson_step)
            ),
            equal_length_path_markers=tuple(
                self._equal_length_path_markers(
                    lesson_step,
                    equal_length_roles,
                    point_handles,
                )
            ),
            atomic_square_reduction_markers=tuple(
                self._atomic_square_reduction_markers(
                    lesson_step,
                    square_path_roles,
                    point_handles,
                )
            ),
            atomic_path_minimum_markers=tuple(
                self._atomic_path_minimum_markers(
                    lesson_step,
                    atomic_path_roles,
                    point_handles,
                    snapshot,
                    source_steps,
                )
            ),
            evaluated_points=tuple(
                self._evaluated_points(
                    lesson_step,
                    source_steps,
                    point_handles,
                )
            ),
            line_parabola_intersections=tuple(
                self._line_parabola_intersections(
                    lesson_step,
                    snapshot,
                )
            ),
            source_roles=self._generic_source_roles(
                lesson_step,
                snapshot,
            ),
            source_step_ids=tuple(lesson_step.source_step_ids),
            capability_ids=tuple(lesson_step.capability_ids),
        )

    def _generic_source_roles(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
    ) -> tuple[dict[str, Any], ...]:
        """Project exact public inputs/outputs for component-owned role binding."""

        sources = {
            source.source_step_id: source
            for source in iter_teaching_sources(snapshot.root_scope)
        }
        result: list[dict[str, Any]] = []
        for source_step_id in lesson_step.source_step_ids:
            source = sources.get(source_step_id)
            if source is None:
                raise ValueError(
                    f"visual_source_role_step_missing: {source_step_id}"
                )
            inputs = {
                name: [
                    self._generic_role_item(
                        item,
                        source=source,
                        input_name=name,
                        sources=sources,
                        snapshot=snapshot,
                        scope_id=lesson_step.scope_id,
                    )
                    for item in items
                ]
                for name, items in source.inputs.items()
            }
            inputs.update(
                self._typed_relation_input_roles(
                    inputs,
                    source=source,
                    scope_id=lesson_step.scope_id,
                )
            )
            outputs = {
                name: self._generic_output_role_item(
                    item,
                    source=source,
                    output_name=name,
                    snapshot=snapshot,
                    scope_id=lesson_step.scope_id,
                )
                for name, item in source.outputs.items()
            }
            result.append(
                {
                    "source_step_id": source.source_step_id,
                    "capability_id": source.capability_id,
                    "inputs": inputs,
                    "outputs": outputs,
                    "calculations": [
                        self._generic_calculation_role(
                            calculation,
                            scope_id=lesson_step.scope_id,
                            source_step_id=source.source_step_id,
                        )
                        for calculation in source.calculations
                    ],
                    "checks": [dict(check) for check in source.checks],
                }
            )
        return tuple(result)

    def _typed_relation_input_roles(
        self,
        inputs: Mapping[str, list[dict[str, Any]]],
        *,
        source: Any,
        scope_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Expose semantic roles declared inside typed public relations.

        Some authored Function calls bind a relation object rather than
        repeating its component points as separate inputs.  Components still
        consume ``anchor``/``reference`` roles, so derive those aliases from
        the typed relation payload and exact target identity—not from the
        capability id, displayed prose, or point-name conventions.
        """

        relations = [
            item
            for items in inputs.values()
            for item in items
            if str(item.get("runtime_type") or "")
            in {"right_angle_equal_length", "midpoint_definition"}
        ]
        if not relations:
            return {}
        if len(relations) != 1:
            raise ValueError("visual_typed_relation_role_ambiguous")
        value = relations[0].get("value")
        if not isinstance(value, Mapping):
            raise ValueError("visual_typed_relation_value_invalid")
        relation_type = str(relations[0].get("runtime_type") or "")

        def point_role(label: str) -> list[dict[str, Any]]:
            geometry_ref = self.index.geometry_point_name(label, scope_id)
            if not geometry_ref:
                same_branch = [
                    str(point_id)
                    for point_id, meta in (
                        self.geometry_spec.get("pointMeta") or {}
                    ).items()
                    if isinstance(meta, Mapping)
                    and str(meta.get("label") or "") == label
                    and scope_root(str(meta.get("scopeId") or ""))
                    == scope_root(scope_id)
                ]
                if len(same_branch) == 1:
                    geometry_ref = same_branch[0]
                elif len(same_branch) > 1:
                    raise ValueError(
                        "visual_typed_relation_point_ambiguous: "
                        f"label={label}, scope={scope_id}, refs={same_branch}"
                    )
            if not geometry_ref:
                raise ValueError(
                    "visual_typed_relation_point_missing: "
                    f"label={label}, scope={scope_id}"
                )
            return [{
                "runtime_type": "Point",
                "label": label,
                "display": label,
                "geometry_ref": geometry_ref,
            }]

        if relation_type == "midpoint_definition":
            endpoints = tuple(str(item) for item in value.get("of") or ())
            if len(endpoints) != 2:
                raise ValueError("visual_midpoint_definition_roles_invalid")
            return {
                "p1": point_role(endpoints[0]),
                "p2": point_role(endpoints[1]),
            }

        angle = tuple(str(item) for item in value.get("angle") or ())
        targets = [
            item
            for name, items in inputs.items()
            if name == "target"
            for item in items
            if str(item.get("label") or "")
        ]
        if not targets:
            output_targets = {
                str(value).rsplit(":", 1)[-1]
                for name, value in source.output_targets.items()
                if name in source.outputs and str(value)
            }
            if len(output_targets) == 1:
                targets = [{"label": next(iter(output_targets))}]
        if len(angle) != 3 or len(targets) != 1:
            raise ValueError("visual_right_angle_equal_length_roles_invalid")
        target = str(targets[0]["label"])
        if target not in {angle[0], angle[2]}:
            raise ValueError("visual_right_angle_equal_length_target_invalid")
        anchor = angle[1]
        reference = angle[2] if target == angle[0] else angle[0]

        return {
            "anchor": point_role(anchor),
            "reference": point_role(reference),
        }

    def _generic_calculation_role(
        self,
        calculation: Any,
        *,
        scope_id: str,
        source_step_id: str,
    ) -> dict[str, Any]:
        """Attach geometry identities to student-safe evidence coordinates.

        Evidence projectors already decide which calculation fields are
        public.  This method only resolves coordinate values against the
        geometry registry; it neither parses display text nor branches on a
        capability id.
        """

        result = dict(calculation) if isinstance(calculation, dict) else {
            "value": calculation
        }
        for key in ("candidates", "points"):
            values = result.get(key)
            if not isinstance(values, (list, tuple)):
                continue
            result[f"{key}_geometry"] = self._geometry_refs_for_point_list(
                values,
                scope_id=scope_id,
                source_step_id=source_step_id,
            )
        for key in ("point", "result", "selected_point"):
            value = result.get(key)
            if _sympy_pair(value) is None:
                continue
            result[f"{key}_geometry_ref"] = self._geometry_point_for_value(
                "",
                value,
                scope_id,
            )
        return result

    def _generic_role_item(
        self,
        item: Any,
        *,
        source: Any,
        input_name: str,
        sources: dict[str, Any],
        snapshot: ExplanationSnapshot,
        scope_id: str,
    ) -> dict[str, Any]:
        role = dict(item) if isinstance(item, dict) else {"value": item}
        runtime_type = str(role.get("runtime_type") or "")
        if runtime_type == "Point":
            ref = role.get("ref")
            semantic_ref = ""
            if isinstance(ref, dict) and ref.get("kind") == "source":
                semantic_ref = str(ref.get("ref") or "")
            elif isinstance(ref, dict) and ref.get("kind") == "step_result":
                producer = sources.get(str(ref.get("step_id") or ""))
                if producer is not None:
                    semantic_ref = _public_point_semantic_ref(
                        snapshot,
                        producer,
                        str(ref.get("return") or ""),
                    )
            label = self._semantic_label_for_ref(semantic_ref)
            point_role = {
                "point": self._geometry_point_for_value(
                    label,
                    role.get("value"),
                    scope_id,
                ),
                "label": label,
            }
            role.update(
                {
                    "geometry_ref": point_role.get("point", ""),
                    "label": point_role.get("label", ""),
                }
            )
        elif runtime_type == "PointList":
            producer_step_id = ""
            ref = role.get("ref")
            if isinstance(ref, dict) and ref.get("kind") == "step_result":
                producer_step_id = str(ref.get("step_id") or "")
            role["geometry_refs"] = self._geometry_refs_for_point_list(
                role.get("value"),
                scope_id=scope_id,
                source_step_id=producer_step_id,
            )
        elif runtime_type in {"Parabola", "QuadraticCurve"}:
            role["curve_id"] = self._curve_id_for_value(
                role.get("value"),
                scope_id=scope_id,
            )
        return role

    def _generic_output_role_item(
        self,
        item: Any,
        *,
        source: Any,
        output_name: str,
        snapshot: ExplanationSnapshot,
        scope_id: str,
    ) -> dict[str, Any]:
        role = dict(item) if isinstance(item, dict) else {"value": item}
        runtime_type = str(role.get("runtime_type") or "")
        if runtime_type == "Point":
            semantic_ref = _public_point_semantic_ref(
                snapshot,
                source,
                output_name,
            )
            label = self._semantic_label_for_ref(semantic_ref)
            geometry_ref = self._geometry_point_for_value(
                label,
                role.get("value"),
                scope_id,
            )
            role.update({"geometry_ref": geometry_ref, "label": label})
        elif runtime_type == "PointList":
            role["geometry_refs"] = self._geometry_refs_for_point_list(
                role.get("value"),
                scope_id=scope_id,
                source_step_id=source.source_step_id,
            )
        elif runtime_type in {"Parabola", "QuadraticCurve"}:
            role["curve_id"] = self._curve_id_for_value(
                role.get("value"),
                scope_id=scope_id,
            )
        return role

    def _geometry_refs_for_point_list(
        self,
        value: Any,
        *,
        scope_id: str,
        source_step_id: str = "",
    ) -> list[dict[str, str]]:
        if not isinstance(value, (list, tuple)):
            return []
        result: list[dict[str, str]] = []
        for index, point_value in enumerate(value, start=1):
            geometry_ref = self._candidate_geometry_ref(
                point_value,
                scope_id=scope_id,
                source_step_id=source_step_id,
                candidate_index=index,
            )
            if not geometry_ref:
                continue
            result.append(
                {
                    "geometry_ref": geometry_ref,
                    "label": self._student_label_for_geometry(geometry_ref),
                }
            )
        return result

    def _candidate_geometry_ref(
        self,
        value: Any,
        *,
        scope_id: str,
        source_step_id: str,
        candidate_index: int,
    ) -> str:
        target = _sympy_pair(value)
        if target is None:
            return ""
        exact: list[str] = []
        for point_id, raw_meta in (self.geometry_spec.get("pointMeta") or {}).items():
            if not isinstance(raw_meta, dict):
                continue
            if source_step_id and str(raw_meta.get("sourceStepId") or "") != source_step_id:
                continue
            if int(raw_meta.get("candidateIndex") or 0) != candidate_index:
                continue
            raw_pair = (self.geometry_spec.get("fixedPoints") or {}).get(point_id)
            if raw_pair is None:
                raw_pair = (self.geometry_spec.get("movingPoints") or {}).get(point_id)
            pair = _sympy_pair(raw_pair)
            if pair is None or not _same_point_pair(target, pair):
                continue
            if self.index._candidate_visible_in_scope(str(point_id), scope_id):
                exact.append(str(point_id))
        if len(exact) > 1:
            raise ValueError(
                "visual_candidate_role_identity_ambiguous: "
                f"source={source_step_id}, index={candidate_index}, refs={sorted(exact)}"
            )
        if exact:
            return exact[0]
        return self._geometry_point_for_value("", value, scope_id)

    def _curve_id_for_value(self, value: Any, *, scope_id: str) -> str:
        try:
            expression = sp.expand(sp.sympify(value))
        except Exception:
            return ""
        x = sp.Symbol("x")
        matches: list[str] = []
        for curve in self._curves:
            curve_id = str(curve.get("id") or "")
            if not curve_id:
                continue
            curve_root = str(
                curve.get("scopeRoot")
                or scope_root(str(curve.get("scopeId") or ""))
            )
            if curve_root != scope_root(scope_id):
                continue
            try:
                candidate = sp.expand(
                    sp.sympify(curve.get("a", 0)) * x**2
                    + sp.sympify(curve.get("b", 0)) * x
                    + sp.sympify(curve.get("c", 0))
                )
            except Exception:
                continue
            if sp.simplify(candidate - expression) == 0:
                matches.append(curve_id)
        if len(matches) > 1:
            raise ValueError(
                "visual_curve_role_identity_ambiguous: "
                f"scope={scope_id}, curves={sorted(matches)}"
            )
        return matches[0] if matches else ""

    def geometry_point_name(self, label: str, scope_id: str | None) -> str | None:
        return self.index.geometry_point_name(label, scope_id)

    def _coordinate_texts_by_ref(self, point_handles: dict[str, str]) -> dict[str, str]:
        coordinates: dict[str, str] = {}
        fixed_points = self.geometry_spec.get("fixedPoints") or {}
        moving_points = self.geometry_spec.get("movingPoints") or {}
        point_meta = self.geometry_spec.get("pointMeta") or {}
        for _, geometry_id in point_handles.items():
            pair = fixed_points.get(geometry_id)
            if pair is None:
                pair = moving_points.get(geometry_id)
            if not _is_point_pair(pair):
                continue
            meta = point_meta.get(geometry_id) if isinstance(point_meta, dict) else None
            label = str((meta or {}).get("label") or geometry_id)
            coordinates[geometry_id] = f"{label}({_coordinate_expr(pair[0])},{_coordinate_expr(pair[1])})"
        return coordinates

    def _curve_ids_for_scope(self, scope_id: str) -> list[str]:
        root = scope_root(scope_id)
        out: list[str] = []
        for curve in self._curves:
            curve_root = str(curve.get("scopeRoot") or scope_root(str(curve.get("scopeId") or "")))
            if curve_root == root:
                out.append(str(curve["id"]))
        return out

    def _minimum_expression_dependency_labels(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> set[str]:
        if "parameter_from_expression_value" not in lesson_step.capability_ids:
            return set()
        labels: set[str] = set()
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step:
                continue
            for handle in step.get("reads") or ():
                if not isinstance(handle, str):
                    continue
                item = snapshot.fact_index.get(handle)
                if not isinstance(item, dict) or item.get("type") != "MinimumExpression":
                    continue
                source_step_id = str(item.get("source_step_id") or "")
                source_step = source_steps.get(source_step_id)
                if not source_step:
                    continue
                labels.update(_point_labels_from_step(source_step))
                witness = next(
                    (
                        item
                        for item in snapshot.macro_evidence
                        if str(item.get("step_id") or "") == source_step_id
                    ),
                    None,
                )
                if witness is not None:
                    labels.update(
                        _point_labels_from_equal_length_roles(
                            _equal_length_roles_from_witness(witness)
                        )
                    )
                labels.update(
                    self._auxiliary_labels_from_method_output(
                        source_step_id,
                        snapshot,
                        labels,
                    )
                )
        return labels

    def _auxiliary_labels_from_method_output(
        self,
        source_step_id: str,
        snapshot: ExplanationSnapshot,
        existing_labels: set[str],
    ) -> set[str]:
        labels: set[str] = set()
        for item in snapshot.fact_index.values():
            if not isinstance(item, dict) or item.get("type") != "Point":
                continue
            if str(item.get("source") or "") != "equal_length_ray_point":
                continue
            for label in self._geometry_labels_for_point_value(item.get("value")):
                if label in existing_labels:
                    continue
                if label in self.index.entities_by_name:
                    continue
                labels.add(label)
        return labels

    def _evaluated_points(
        self,
        lesson_step: LessonStep,
        source_steps: dict[str, dict[str, Any]],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if "evaluate_point_at_parameter" not in lesson_step.capability_ids:
            return []
        markers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step or step.get("recipe_hint") != "evaluate_point_at_parameter":
                continue
            for label in sorted(_point_labels_from_step(step)):
                point = point_handles.get(label)
                if not point or point in seen:
                    continue
                seen.add(point)
                markers.append(
                    {
                        "point": point,
                        "label": label,
                        "display": _coordinate_text_from_boxes(label, lesson_step.box),
                    }
                )
        return markers

    def _line_parabola_intersections(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
    ) -> list[dict[str, Any]]:
        """Bind the intersection diagram from verified refs and point values.

        Student-facing point names are presentation only.  Geometry selection
        uses each TeachingSource's SourceRef/StepResultRef identity plus its
        verified value, so this binder works for arbitrary point names.
        """

        sources = {
            source.source_step_id: source
            for source in iter_teaching_sources(snapshot.root_scope)
        }
        markers: list[dict[str, Any]] = []
        for source_step_id in lesson_step.source_step_ids:
            source = sources.get(source_step_id)
            if (
                source is None
                or source.capability_id
                != "line_parabola_second_intersection_point"
            ):
                continue
            roles = {
                name: self._teaching_input_point_role(
                    source,
                    name,
                    sources=sources,
                    snapshot=snapshot,
                    scope_id=lesson_step.scope_id,
                )
                for name in ("line_p1", "line_p2", "known_point")
            }
            output = source.outputs.get("point")
            output_ref = _public_point_semantic_ref(
                snapshot,
                source,
                "point",
            )
            output_label = self._semantic_label_for_ref(output_ref)
            output_value = output.get("value") if isinstance(output, dict) else None
            target_point = self._geometry_point_for_value(
                output_label,
                output_value,
                lesson_step.scope_id,
            )
            if any(not role.get("point") for role in roles.values()) or not target_point:
                raise ValueError(
                    "visual_line_parabola_role_binding_missing: "
                    f"step={source_step_id}, roles={roles}, target={target_point}"
                )
            markers.append(
                {
                    "source_step_id": source_step_id,
                    "line_p1": roles["line_p1"]["point"],
                    "line_p1_label": roles["line_p1"]["label"],
                    "line_p2": roles["line_p2"]["point"],
                    "line_p2_label": roles["line_p2"]["label"],
                    "known_point": roles["known_point"]["point"],
                    "known_label": roles["known_point"]["label"],
                    "target_point": target_point,
                    "target_label": output_label
                    or self._student_label_for_geometry(target_point),
                    "target_display": _point_display_from_geometry_with_label(
                        output_label or self._student_label_for_geometry(target_point),
                        target_point,
                        self.geometry_spec,
                    ),
                }
            )
        return markers

    def _teaching_input_point_role(
        self,
        source: Any,
        input_name: str,
        *,
        sources: dict[str, Any],
        snapshot: ExplanationSnapshot,
        scope_id: str,
    ) -> dict[str, str]:
        values = tuple(source.inputs.get(input_name, ()))
        if len(values) != 1:
            return {}
        item = values[0]
        ref = item.get("ref")
        semantic_ref = ""
        if isinstance(ref, dict) and ref.get("kind") == "source":
            semantic_ref = str(ref.get("ref") or "")
        elif isinstance(ref, dict) and ref.get("kind") == "step_result":
            producer = sources.get(str(ref.get("step_id") or ""))
            if producer is not None:
                semantic_ref = _public_point_semantic_ref(
                    snapshot,
                    producer,
                    str(ref.get("return") or ""),
                )
        label = self._semantic_label_for_ref(semantic_ref)
        point = self._geometry_point_for_value(
            label,
            item.get("value"),
            scope_id,
        )
        return {"point": point, "label": label} if point else {}

    def _semantic_label_for_ref(self, semantic_ref: str) -> str:
        if not semantic_ref:
            return ""
        entity = self.index.point_entity_for_name_or_handle(semantic_ref)
        if entity is None:
            return ""
        return str(
            entity.get("name")
            or _handle_tail(str(entity.get("handle") or ""))
        )

    def _geometry_point_for_value(
        self,
        label: str,
        value: Any,
        scope_id: str,
    ) -> str:
        target = _sympy_pair(value)
        if target is None:
            return self.index.geometry_point_name(label, scope_id) or ""
        all_points: list[tuple[int, str, Any]] = []
        for point_id, pair in (self.geometry_spec.get("fixedPoints") or {}).items():
            all_points.append((3, str(point_id), pair))
        for point_id, pair in (self.geometry_spec.get("movingPoints") or {}).items():
            all_points.append((1, str(point_id), pair))
        candidates: list[tuple[int, str]] = []
        for base_score, point_id, raw_pair in all_points:
            pair = _sympy_pair(raw_pair)
            if pair is None or not _same_point_pair(target, pair):
                continue
            if not self.index._candidate_visible_in_scope(point_id, scope_id):
                continue
            meta = (self.geometry_spec.get("pointMeta") or {}).get(point_id)
            meta_label = str((meta or {}).get("label") or point_id)
            score = base_score
            if label and meta_label == label:
                score += 3
            if label and point_id == label:
                score += 2
            candidates.append((score, point_id))
        if not candidates:
            return self.index.geometry_point_name(label, scope_id) or ""
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _geometry_labels_for_point_value(self, value: Any) -> set[str]:
        target = _sympy_pair(value)
        if target is None:
            return set()
        labels: set[str] = set()
        all_points = {}
        all_points.update(self.geometry_spec.get("fixedPoints") or {})
        all_points.update(self.geometry_spec.get("movingPoints") or {})
        for label, pair in all_points.items():
            candidate = _sympy_pair(pair)
            if candidate is None:
                continue
            if _same_point_pair(target, candidate):
                labels.add(str(label))
        return labels

    def _translation_markers(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        markers: list[dict[str, Any]] = []
        if "translated_point" not in lesson_step.capability_ids:
            return markers
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step or step.get("recipe_hint") != "translated_point":
                continue
            target_handles = [str(step.get("target") or "")]
            target_handles.extend(
                str(item.get("handle") or "")
                for item in step.get("creates") or ()
                if isinstance(item, dict)
            )
            target_handles.extend(
                str(handle)
                for handle in step.get("reads") or ()
                if isinstance(handle, str)
            )
            for read_handle in dict.fromkeys(target_handles):
                if not isinstance(read_handle, str):
                    continue
                target_entity = self.index.entities_by_handle.get(read_handle)
                if not target_entity or target_entity.get("definition") != "translated_point":
                    continue
                source_raw = str(target_entity.get("of") or target_entity.get("source") or "")
                source_entity = self.index.point_entity_for_name_or_handle(source_raw)
                if source_entity is None:
                    continue
                source = self.index.point_for_entity(source_entity, lesson_step.scope_id)
                target = self.index.point_for_entity(target_entity, lesson_step.scope_id)
                vector = target_entity.get("vector", [
                    target_entity.get("dx", "0"),
                    target_entity.get("dy", "0"),
                ])
                if source and target and isinstance(vector, list) and len(vector) == 2:
                    markers.append(
                        {
                            "source_point": source,
                            "target_point": target,
                            "source_label": self._student_label_for_geometry(source),
                            "target_label": self._student_label_for_geometry(target),
                            "source_display": _point_display_from_geometry(source, self.geometry_spec),
                            "target_display": _point_display_from_geometry(target, self.geometry_spec),
                            "vector": [str(vector[0]), str(vector[1])],
                        }
                    )
        return markers

    def _student_label_for_geometry(self, point_id: str) -> str:
        meta = (self.geometry_spec.get("pointMeta") or {}).get(point_id)
        if isinstance(meta, dict) and str(meta.get("label") or "").strip():
            return str(meta["label"])
        return str(point_id)

    def _square_adjacent_markers(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if "square_adjacent_vertex_from_side" not in lesson_step.capability_ids:
            return []
        markers: list[dict[str, Any]] = []
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step or step.get("recipe_hint") != "square_adjacent_vertex_from_side":
                continue
            square_fact = self._square_fact_for_step(step)
            if square_fact is None:
                continue
            vertices = [
                str(item)
                for item in square_fact.get("vertices") or ()
                if isinstance(item, str) and item
            ]
            if len(vertices) < 4:
                continue
            labels = [_label_from_point_handle_or_entity(handle, self.index) for handle in vertices[:4]]
            if any(not label for label in labels):
                continue
            target_label = _label_from_effective_step(step_id, snapshot)
            axis_labels = self._dynamic_square_labels(
                source_step_id=str(step_id),
                labels=labels,
                target_label=target_label,
                scope_id=lesson_step.scope_id,
                snapshot=snapshot,
            )
            points = [
                self._square_vertex_geometry_ref(label, lesson_step.scope_id, use_axis=label in axis_labels)
                for label in labels
            ]
            if any(not point for point in points):
                continue
            marker = {
                "labels": labels,
                "vertices": points,
                "target_label": target_label,
                "target": points[labels.index(target_label)] if target_label in labels else points[-1],
                "target_display": _square_target_display_from_runtime(
                    source_step_id=step_id,
                    target_label=target_label,
                    snapshot=snapshot,
                ),
                "target_value": _square_target_value_from_runtime(
                    source_step_id=step_id,
                    snapshot=snapshot,
                ),
                "coordinate_triangles": self._square_coordinate_triangles(
                    labels,
                    points,
                    target_label,
                    lesson_step.scope_id,
                ),
                "vertex_displays": {
                    label: _point_display_from_geometry_with_label(label, point, self.geometry_spec)
                    for label, point in zip(labels, points, strict=True)
                },
                "source_step_id": step_id,
            }
            markers.append(marker)
        return markers

    def _dynamic_square_labels(
        self,
        *,
        source_step_id: str,
        labels: list[str],
        target_label: str,
        scope_id: str,
        snapshot: ExplanationSnapshot,
    ) -> set[str]:
        """Resolve dynamic square vertices from public refs and values."""

        sources = {
            source.source_step_id: source
            for source in iter_teaching_sources(snapshot.root_scope)
        }
        source = sources.get(source_step_id)
        if source is None:
            return set()
        contexts = parameterized_point_contexts_by_step(snapshot)
        dynamic: set[str] = set()

        for items in source.inputs.values():
            for item in items:
                if not isinstance(item, dict) or item.get("runtime_type") != "Point":
                    continue
                ref = item.get("resolved_from") or item.get("ref")
                if not isinstance(ref, dict) or ref.get("kind") != "step_result":
                    continue
                producer_id = str(ref.get("step_id") or "")
                value = item.get("value")
                if not any(
                    owner == scope_id and value_depends_on_symbol(value, symbol)
                    for owner, symbol in contexts.get(producer_id, ())
                ):
                    continue
                authored_ref = item.get("ref")
                label = ""
                if isinstance(authored_ref, dict) and authored_ref.get("kind") == "source":
                    label = _label_from_semantic_name(str(authored_ref.get("ref") or ""))
                if label in labels:
                    dynamic.add(label)

        target_value = None
        for result in source.outputs.values():
            if isinstance(result, dict) and result.get("runtime_type") == "Point":
                target_value = result.get("value")
                break
        if target_label in labels and any(
            owner == scope_id and value_depends_on_symbol(target_value, symbol)
            for owner, symbol in contexts.get(source_step_id, ())
        ):
            dynamic.add(target_label)

        # In the ordered square [start, side-end, opposite, adjacent], the
        # opposite vertex varies whenever either adjacent side endpoint does.
        if dynamic and len(labels) >= 3:
            dynamic.add(labels[2])
        return dynamic

    def _linked_square_labels_for_atomic_path(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
        roles_payload: dict[str, Any],
    ) -> set[str]:
        moving = str(roles_payload.get("moving_point") or "")
        if not moving:
            return set()
        marker = self._linked_square_marker_for_atomic_path(
            lesson_step,
            snapshot,
            source_steps,
            target_label=moving,
        )
        if not marker:
            return set()
        return {str(label) for label in marker.get("labels") or () if str(label)}

    def _linked_square_marker_for_atomic_path(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
        *,
        target_label: str,
    ) -> dict[str, Any]:
        if not target_label:
            return {}
        target_root = scope_root(lesson_step.scope_id)
        for step_id, step in source_steps.items():
            if not step or step.get("recipe_hint") != "square_adjacent_vertex_from_side":
                continue
            if scope_root(str(step.get("scope_id") or "")) != target_root:
                continue
            square_fact = self._square_fact_for_step(step)
            if square_fact is None:
                continue
            vertices = [
                str(item)
                for item in square_fact.get("vertices") or ()
                if isinstance(item, str) and item
            ]
            if len(vertices) < 4:
                continue
            labels = [_label_from_point_handle_or_entity(handle, self.index) for handle in vertices[:4]]
            if target_label not in labels or any(not label for label in labels):
                continue
            axis_labels = {
                label
                for label in labels
                if axis_parameter_point_id(label, lesson_step.scope_id)
                in self._known_points
            }
            axis_label = next(
                (label for label in labels if label in axis_labels and label != target_label),
                "",
            )
            axis_value = self._axis_parameter_value_for_step_label(
                step,
                snapshot,
                axis_label,
            )
            target_value = _square_target_value_from_runtime(
                source_step_id=str(step_id),
                snapshot=snapshot,
            )
            if not axis_label or not axis_value or not target_value:
                continue
            points = [
                self._square_vertex_geometry_ref(
                    label,
                    lesson_step.scope_id,
                    use_axis=label in axis_labels,
                )
                for label in labels
            ]
            if any(not point for point in points):
                continue
            return {
                "labels": labels,
                "vertices": points,
                "axis_label": axis_label,
                "axis": points[labels.index(axis_label)],
                "axis_value": axis_value,
                "target_label": target_label,
                "target": points[labels.index(target_label)],
                "target_value": target_value,
                "source_step_id": str(step_id),
            }
        return {}

    def _axis_parameter_value_for_step_label(
        self,
        step: dict[str, Any],
        snapshot: ExplanationSnapshot,
        label: str,
    ) -> list[str]:
        if not label:
            return []
        step_scope_id = str(step.get("scope_id") or "")
        point_id = axis_parameter_point_id(label, step_scope_id)
        pair = self._geometry_point_pair(point_id)
        if pair is None:
            return []
        return [str(pair[0]), str(pair[1])]

    def _curve_point_candidate_markers(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
    ) -> list[dict[str, Any]]:
        if "point_candidates_from_curve_point_condition" not in lesson_step.capability_ids:
            return []
        source_step = next(
            (
                step
                for step in snapshot.effective_steps
                if isinstance(step, dict)
                and str(step.get("step_id") or "") in set(lesson_step.source_step_ids)
                and step.get("recipe_hint") == "point_candidates_from_curve_point_condition"
            ),
            None,
        )
        if source_step is None:
            return []
        target_label = _label_from_effective_step(str(source_step.get("step_id") or ""), snapshot)
        curve_label = _candidate_curve_label(source_step, target_label)
        square_fact = self._square_fact_for_candidate_step(
            str(source_step.get("scope_id") or lesson_step.scope_id),
            target_label,
            curve_label,
        )
        labels: list[str] = []
        if square_fact is not None:
            labels = [
                _label_from_point_handle_or_entity(str(handle), self.index)
                for handle in square_fact.get("vertices") or ()
                if handle
            ][:4]
            if len(labels) < 4 or target_label not in labels:
                labels = []
        markers: list[dict[str, Any]] = []
        for index in range(1, 5):
            target = axis_parameter_candidate_point_id(target_label, lesson_step.scope_id, index)
            if target not in self._known_points:
                continue
            marker: dict[str, Any] = {
                "target_label": target_label,
                "target": target,
                "target_display": _point_display_from_geometry_with_label(
                    target_label,
                    target,
                    self.geometry_spec,
                ),
                "source_step_id": f"{source_step.get('step_id')}:candidate{index}",
            }
            if len(labels) >= 4:
                vertices = [
                    self._candidate_square_vertex_ref(label, lesson_step.scope_id, index)
                    for label in labels
                ]
                if any(not point for point in vertices):
                    markers.append(marker)
                    continue
                marker.update(
                    {
                        "labels": labels,
                        "display_labels": [
                            _candidate_display_label(label, index)
                            if axis_parameter_candidate_point_id(label, lesson_step.scope_id, index) in self._known_points
                            else label
                            for label in labels
                        ],
                        "vertices": vertices,
                        "target": vertices[labels.index(target_label)],
                        "target_display": _point_display_from_geometry_with_label(
                            target_label,
                            vertices[labels.index(target_label)],
                            self.geometry_spec,
                        ),
                        "coordinate_triangles": (),
                        "vertex_displays": {
                            label: _point_display_from_geometry_with_label(label, point, self.geometry_spec)
                            for label, point in zip(labels, vertices, strict=True)
                        },
                    }
                )
            markers.append(marker)
        return markers

    def _square_fact_for_candidate_step(
        self,
        scope_id: str,
        target_label: str,
        curve_label: str,
    ) -> dict[str, Any] | None:
        for fact in self.facts_by_handle.values():
            if not isinstance(fact, dict) or fact.get("type") != "square":
                continue
            if scope_id and str(fact.get("scope_id") or "") != scope_id:
                continue
            labels = [
                _label_from_point_handle_or_entity(str(handle), self.index)
                for handle in fact.get("vertices") or ()
            ]
            if target_label in labels and (not curve_label or curve_label in labels):
                return fact
        return None

    def _candidate_square_vertex_ref(
        self,
        label: str,
        scope_id: str,
        index: int,
    ) -> str:
        candidate_id = axis_parameter_candidate_point_id(label, scope_id, index)
        if candidate_id in self._known_points:
            return candidate_id
        return self.index.geometry_point_name(label, scope_id) or ""

    def _square_coordinate_triangles(
        self,
        labels: list[str],
        points: list[str],
        target_label: str,
        scope_id: str,
    ) -> list[dict[str, Any]]:
        if len(labels) < 4 or len(points) < 4:
            return []
        side = _square_known_side_for_visual_target(labels, target_label)
        if side is None:
            return []
        base_index, side_end_index, target_index = side
        base_label = labels[base_index]
        side_end_label = labels[side_end_index]
        adjacent_label = labels[target_index]
        base = points[base_index]
        side_end = points[side_end_index]
        target = points[target_index]
        side_projection = square_projection_point_id(base_label, side_end_label, scope_id)
        target_projection = square_projection_point_id(base_label, adjacent_label, scope_id)
        if side_projection not in self._known_points or target_projection not in self._known_points:
            return []
        used_labels = set(labels)
        side_projection_ref = self._projection_ref_for_helper(side_projection, scope_id) or side_projection
        side_projection_label = self._projection_label(
            side_projection_ref,
            fallback=_fresh_projection_label(used_labels),
        )
        used_labels.add(side_projection_label)
        target_projection_ref = self._projection_ref_for_helper(target_projection, scope_id) or target_projection
        target_projection_label = self._projection_label(
            target_projection_ref,
            fallback=_fresh_projection_label(used_labels),
        )
        return [
            {
                "handle": f"visual:square-coordinate:{scope_id}:{base_label}{side_end_label}",
                "vertices": [base, side_end, side_projection_ref],
                "projection": side_projection_ref,
                "projection_target": side_end,
                "projection_label": side_projection_label,
                "projection_is_helper": side_projection_ref == side_projection,
                "right_angle": {
                    "vertex": side_projection_ref,
                    "rayA": base,
                    "rayB": side_end,
                },
            },
            {
                "handle": f"visual:square-coordinate:{scope_id}:{base_label}{adjacent_label}",
                "vertices": [base, target, target_projection_ref],
                "projection": target_projection_ref,
                "projection_target": target,
                "projection_label": target_projection_label,
                "projection_is_helper": target_projection_ref == target_projection,
                "right_angle": {
                    "vertex": target_projection_ref,
                    "rayA": base,
                    "rayB": target,
                },
            },
        ]

    def _projection_ref_for_helper(self, helper_id: str, scope_id: str) -> str:
        helper_pair = self._geometry_point_pair(helper_id)
        if helper_pair is None:
            return ""
        candidates: list[tuple[int, str]] = []
        for point_id in sorted(self._known_points):
            if point_id == helper_id:
                continue
            if not self.index._candidate_visible_in_scope(point_id, scope_id):
                continue
            candidate_pair = self._geometry_point_pair(point_id)
            if candidate_pair is None or not _same_point_pair(helper_pair, candidate_pair):
                continue
            meta = (self.geometry_spec.get("pointMeta") or {}).get(point_id)
            score = 10
            if isinstance(meta, dict) and meta.get("visualOnly"):
                score = 2
            candidates.append((score, point_id))
        if not candidates:
            return helper_id
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _geometry_point_pair(self, point_id: str) -> tuple[sp.Expr, sp.Expr] | None:
        raw = (self.geometry_spec.get("fixedPoints") or {}).get(point_id)
        if raw is None:
            raw = (self.geometry_spec.get("movingPoints") or {}).get(point_id)
        return _sympy_pair(raw)

    def _projection_label(self, point_id: str, *, fallback: str) -> str:
        meta = (self.geometry_spec.get("pointMeta") or {}).get(point_id)
        if isinstance(meta, dict) and not meta.get("visualOnly"):
            label = str(meta.get("label") or "")
            if label:
                return label
        return fallback

    def _square_fact_for_step(self, step: dict[str, Any]) -> dict[str, Any] | None:
        for handle in step.get("reads") or ():
            if not isinstance(handle, str):
                continue
            fact = self.facts_by_handle.get(handle)
            if isinstance(fact, dict) and fact.get("type") == "square":
                return fact
        return None

    def _point_items_for_read_handle(
        self,
        handle: str,
        snapshot: ExplanationSnapshot,
        source_step_id: str,
    ) -> list[dict[str, Any]]:
        direct = snapshot.fact_index.get(handle)
        items: list[dict[str, Any]] = []
        if isinstance(direct, dict) and direct.get("type") == "Point":
            items.append(direct)
        tail = handle.rsplit(":", 1)[-1]
        read_entity = self.index.entities_by_handle.get(handle) or {}
        read_label = str(read_entity.get("name") or "")
        step_order = {
            str(step.get("step_id") or ""): index
            for index, step in enumerate(snapshot.effective_steps)
            if isinstance(step, dict)
        }
        current_order = step_order.get(source_step_id, len(step_order))
        current_step = next(
            (
                step
                for step in snapshot.effective_steps
                if isinstance(step, dict)
                and str(step.get("step_id") or "") == source_step_id
            ),
            {},
        )
        current_scope = str(current_step.get("scope_id") or "")
        for item in snapshot.fact_index.values():
            if not isinstance(item, dict) or item.get("type") != "Point":
                continue
            item_handle = str(item.get("handle") or "")
            if item_handle == handle:
                continue
            if item_handle.endswith(f":outputs:{tail}") or item_handle.endswith(f":points:{tail.split('_', 1)[0]}"):
                items.append(item)
                continue
            if str(item.get("source_step_id") or "") == source_step_id and tail in item_handle:
                items.append(item)
                continue
            item_source = str(item.get("source_step_id") or "")
            item_scope = str(item.get("scope_id") or "")
            if (
                read_label
                and str(item.get("name") or "") == read_label
                and step_order.get(item_source, -1) < current_order
                and (
                    item_scope in {current_scope, "problem"}
                    or current_scope.startswith(f"{item_scope}_")
                )
            ):
                items.append(item)
        return items

    def _square_vertex_geometry_ref(
        self,
        label: str,
        scope_id: str,
        *,
        use_axis: bool,
    ) -> str:
        if use_axis:
            axis_id = axis_parameter_point_id(label, scope_id)
            if axis_id in self._known_points:
                return axis_id
        return self.index.geometry_point_name(label, scope_id) or ""

    def _axis_parameterized_points(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
    ) -> list[dict[str, Any]]:
        if "quadratic_axis_parameterized_point" not in lesson_step.capability_ids:
            return []
        markers: list[dict[str, Any]] = []
        sources = {
            source.source_step_id: source
            for source in iter_teaching_sources(snapshot.root_scope)
        }
        for source_step_id in lesson_step.source_step_ids:
            source = sources.get(source_step_id)
            if source is None or source.capability_id != "quadratic_axis_parameterized_point":
                continue
            point = source.outputs.get("point")
            parameter_output = source.outputs.get("parameter")
            value = point.get("value") if isinstance(point, dict) else None
            parameter = (
                str(parameter_output.get("value") or "")
                if isinstance(parameter_output, dict)
                else ""
            )
            if (
                not isinstance(value, (list, tuple))
                or len(value) != 2
                or not parameter
                or not _value_depends_on_symbol(value, parameter)
            ):
                continue
            label = str(source.output_targets.get("point") or "")
            if not label:
                label = _label_from_effective_step(source_step_id, snapshot)
            point_id = axis_parameter_point_id(label, lesson_step.scope_id) if label else ""
            if not label or point_id not in self._known_points:
                continue
            markers.append(
                {
                    "label": label,
                    "point": point_id,
                    "display": _axis_parameterized_point_display(label, value),
                    "value": [str(value[0]), str(value[1])],
                }
            )
        return markers

    def _axis_x_intercept_points(
        self,
        lesson_step: LessonStep,
        source_steps: dict[str, dict[str, Any]],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if "quadratic_axis_x_intercept_point" not in lesson_step.capability_ids:
            return []
        markers: list[dict[str, Any]] = []
        labels: set[str] = set()
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if step:
                labels.update(_point_labels_from_step(step))
        labels.update(_point_labels_from_lesson_step(lesson_step))
        for label in sorted(labels):
            point_id = point_handles.get(label) or self.index.geometry_point_name(
                label,
                lesson_step.scope_id,
            )
            if not point_id:
                continue
            markers.append(
                {
                    "label": label,
                    "point": point_id,
                    "display": _point_display_from_geometry(point_id, self.geometry_spec),
                }
            )
        return markers

    def _x_axis_intercept_points(self, lesson_step: LessonStep) -> list[dict[str, Any]]:
        if "quadratic_x_axis_intercept_point" not in lesson_step.capability_ids:
            return []
        markers: list[dict[str, Any]] = []
        for entity in self.index.entities_by_handle.values():
            if not isinstance(entity, dict):
                continue
            if entity.get("entity_type") != "point":
                continue
            if entity.get("definition") != "x_axis_intercept":
                continue
            point_id = self.index.point_for_entity(entity, lesson_step.scope_id)
            if not point_id:
                continue
            label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            markers.append(
                {
                    "label": label,
                    "point": point_id,
                    "side": str(entity.get("side") or ""),
                    "display": _point_display_from_geometry(point_id, self.geometry_spec),
                }
            )
        return markers

    def _vertex_points(self, lesson_step: LessonStep) -> list[dict[str, Any]]:
        if "quadratic_vertex_point" not in lesson_step.capability_ids:
            return []
        markers: list[dict[str, Any]] = []
        for entity in self.index.entities_by_handle.values():
            if not isinstance(entity, dict):
                continue
            if entity.get("entity_type") != "point":
                continue
            if entity.get("definition") != "vertex":
                continue
            point_id = self.index.point_for_entity(entity, lesson_step.scope_id)
            if not point_id:
                continue
            label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            markers.append(
                {
                    "label": label,
                    "point": point_id,
                    "display": _point_display_from_geometry(point_id, self.geometry_spec),
                }
            )
        return markers

    def _angle_equalities(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if "angle_sum_equal_angle_candidates" not in lesson_step.capability_ids:
            return []
        equalities = _angle_sum_display_equalities_from_source(
            lesson_step,
            snapshot,
            source_steps,
        ) or _visible_angle_equalities(lesson_step)
        out: list[dict[str, Any]] = []
        for left, right in equalities:
            marker = self._angle_equality_marker(left, right, lesson_step.scope_id, point_handles)
            if marker:
                out.append(marker)
        return out

    def _angle_equality_marker(
        self,
        left: str,
        right: str,
        scope_id: str,
        point_handles: dict[str, str],
    ) -> dict[str, Any] | None:
        angles: list[dict[str, Any]] = []
        guide_arms: list[dict[str, Any]] = []
        guide_only_refs: set[str] = set()
        for angle_name in (left, right):
            angle = self._angle_marker(angle_name, scope_id)
            if angle is None:
                return None
            angles.append(angle)
            for arm in self._guide_arms_for_angle(angle_name, scope_id, point_handles):
                guide_arms.append(arm)
                for ref in arm.get("guide_only_refs") or ():
                    guide_only_refs.add(str(ref))
        return {
            "left_angle": left,
            "right_angle": right,
            "angles": angles,
            "guide_arms": guide_arms,
            "guide_only_refs": sorted(guide_only_refs),
        }

    def _angle_marker(self, angle_name: str, scope_id: str) -> dict[str, Any] | None:
        if len(angle_name) != 3:
            return None
        a, vertex, b = angle_name
        ray_a = self.index.geometry_point_name(a, scope_id)
        vertex_ref = self.index.geometry_point_name(vertex, scope_id)
        ray_b = self.index.geometry_point_name(b, scope_id)
        if not ray_a or not vertex_ref or not ray_b:
            return None
        return {
            "name": angle_name,
            "vertex": vertex_ref,
            "rayA": ray_a,
            "rayB": ray_b,
        }

    def _angle_references(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
    ) -> list[dict[str, Any]]:
        if "angle_sum_equal_angle_candidates" not in lesson_step.capability_ids:
            return []
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for angle_name, value in _reference_angles_from_method_output(lesson_step, snapshot):
            marker = self._angle_marker(angle_name, lesson_step.scope_id)
            if marker is None:
                continue
            key = (angle_name, value)
            if key in seen:
                continue
            seen.add(key)
            item = dict(marker)
            item["value"] = value
            out.append(item)
        return out

    def _axis_intercept_markers(
        self,
        lesson_step: LessonStep,
        source_steps: dict[str, dict[str, Any]],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if "axis_intercept_from_equal_acute_angles" not in lesson_step.capability_ids:
            return []
        out: list[dict[str, Any]] = []
        display_equalities = _visible_angle_equalities(lesson_step)
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step or step.get("recipe_hint") != "axis_intercept_from_equal_acute_angles":
                continue
            axis_equality = _axis_angle_equality_from_step(step)
            if not all(axis_equality) and display_equalities:
                axis_equality = display_equalities[0]
            display_line = _display_line_segment_from_lesson_step(lesson_step)
            axis_equality = _axis_intercept_equality(
                axis_equality,
                display_line=display_line,
                result_label=_coordinate_result_label(lesson_step),
            )
            origin_label = self._origin_label_from_step(step) or _origin_label_from_angles(axis_equality)
            if not axis_equality or not origin_label:
                continue
            equality_markers: list[dict[str, Any]] = []
            for left, right in display_equalities or [axis_equality]:
                marker = self._angle_equality_marker(left, right, lesson_step.scope_id, point_handles)
                if marker:
                    if display_line:
                        marker = self._with_display_line_guide(
                            marker,
                            display_line,
                            lesson_step.scope_id,
                        )
                    equality_markers.append(marker)
            axis_sides = self._axis_triangle_sides(axis_equality, origin_label, lesson_step.scope_id)
            right_angles = self._right_angle_markers(axis_equality, origin_label, lesson_step.scope_id)
            if not equality_markers and not axis_sides and not right_angles:
                continue
            out.append(
                {
                    "angle_equalities": equality_markers,
                    "axis_sides": axis_sides,
                    "right_angles": right_angles,
                }
            )
        return out

    def _with_display_line_guide(
        self,
        marker: dict[str, Any],
        line_segment: str,
        scope_id: str,
    ) -> dict[str, Any]:
        if len(line_segment) != 2:
            return marker
        start_label, end_label = line_segment[0], line_segment[1]
        start = self.index.geometry_point_name(start_label, scope_id)
        end = self.index.geometry_point_name(end_label, scope_id)
        if not start or not end:
            return marker
        target_angle = str(marker.get("left_angle") or "")
        if len(target_angle) != 3 or target_angle[1] not in line_segment:
            return marker
        out = dict(marker)
        guide_arms: list[dict[str, Any]] = []
        replaced = False
        for guide in marker.get("guide_arms") or ():
            if not isinstance(guide, dict):
                continue
            item = dict(guide)
            if str(item.get("angle_name") or "") == target_angle:
                item.update(
                    {
                        "handle": f"line:{scope_id}:{line_segment}",
                        "from": start,
                        "to": end,
                        "show_endpoint_refs": [end],
                    }
                )
                replaced = True
            guide_arms.append(item)
        if replaced:
            out["guide_arms"] = guide_arms
        return out

    def _origin_label_from_step(self, step: dict[str, Any]) -> str:
        for handle in step.get("reads") or ():
            if not isinstance(handle, str):
                continue
            entity = self.index.entities_by_handle.get(handle)
            if not entity or entity.get("definition") != "coordinate_origin":
                continue
            return str(entity.get("name") or _handle_tail(handle))
        return ""

    def _axis_triangle_sides(
        self,
        equality: tuple[str, str],
        origin_label: str,
        scope_id: str,
    ) -> list[dict[str, Any]]:
        labels: set[str] = set()
        for angle_name in equality:
            if len(angle_name) == 3 and origin_label in angle_name:
                labels.update(label for label in angle_name if label != origin_label)
        origin = self.index.geometry_point_name(origin_label, scope_id)
        if not origin:
            return []
        out: list[dict[str, Any]] = []
        for label in sorted(labels):
            point = self.index.geometry_point_name(label, scope_id)
            if not point:
                continue
            out.append(
                {
                    "handle": f"line:{scope_id}:{origin_label}{label}",
                    "from": origin,
                    "to": point,
                }
            )
        return out

    def _right_angle_markers(
        self,
        equality: tuple[str, str],
        origin_label: str,
        scope_id: str,
    ) -> list[dict[str, Any]]:
        origin = self.index.geometry_point_name(origin_label, scope_id)
        if not origin:
            return []
        out: list[dict[str, Any]] = []
        for angle_name in equality:
            if len(angle_name) != 3 or origin_label not in angle_name:
                continue
            rays = [
                self.index.geometry_point_name(label, scope_id)
                for label in angle_name
                if label != origin_label
            ]
            rays = [ray for ray in rays if ray]
            if len(rays) != 2:
                continue
            out.append(
                {
                    "name": "".join(sorted(angle_name)),
                    "vertex": origin,
                    "rayA": rays[0],
                    "rayB": rays[1],
                }
            )
        return out

    def _guide_arms_for_angle(
        self,
        angle_name: str,
        scope_id: str,
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if len(angle_name) != 3:
            return []
        a, vertex, b = angle_name
        out: list[dict[str, Any]] = []
        for endpoint in (a, b):
            if _axis_arm(vertex, endpoint, self.index.origin_labels):
                continue
            start = self.index.geometry_point_name(vertex, scope_id)
            end = self.index.geometry_point_name(endpoint, scope_id)
            if not start or not end:
                continue
            guide_only_refs: list[str] = []
            if self._is_guide_only_endpoint(endpoint, point_handles):
                guide_only_refs.append(end)
            show_endpoint_refs: list[str] = []
            if self._is_local_endpoint(endpoint):
                show_endpoint_refs.append(end)
            out.append(
                {
                    "angle_name": angle_name,
                    "handle": f"line:{scope_id}:{vertex}{endpoint}",
                    "from": start,
                    "to": end,
                    "guide_only_refs": guide_only_refs,
                    "show_endpoint_refs": show_endpoint_refs,
                }
            )
        return out

    def _is_local_endpoint(self, label: str) -> bool:
        entity = self.index.entities_by_name.get(label)
        if entity is None:
            return False
        return str(entity.get("scope_id") or "problem") != "problem"

    def _is_guide_only_endpoint(self, label: str, point_handles: dict[str, str]) -> bool:
        if label in point_handles:
            return False
        entity = self.index.entities_by_name.get(label)
        if entity is None:
            return False
        if str(entity.get("scope_id") or "problem") != "problem":
            return True
        return "coordinate" not in entity and entity.get("definition") not in {
            "coordinate_origin",
            "x_axis_intercept",
            "y_axis_intercept",
            "translated_point",
        }

    def _atomic_square_reduction_roles(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, Any]:
        if "quadratic_square_path_minimum" in lesson_step.capability_ids:
            witness = _macro_evidence_for_lesson_step(
                snapshot,
                lesson_step,
                macro_id="quadratic_square_path_minimum",
            )
            if witness is not None:
                chosen = {
                    str(item.get("role") or ""): str(
                        item.get("chosen_ref") or ""
                    )
                    for item in witness.get("role_resolutions", ())
                    if isinstance(item, dict)
                }
                side_start = chosen.get("side_start", "")
                side_end = chosen.get("axis_point", "")
                moving = chosen.get("moving_point", "")
                fixed = chosen.get("fixed_endpoint", "")
                square_fact = next(
                    (
                        fact
                        for fact in snapshot.problem.get("facts", ())
                        if isinstance(fact, dict)
                        and fact.get("type") == "square"
                        and {
                            side_start,
                            side_end,
                            moving,
                        }
                        <= {
                            _label_from_point_handle_or_entity(
                                str(handle), self.index
                            )
                            for handle in fact.get("vertices", ())
                        }
                    ),
                    None,
                )
                midpoint_fact = next(
                    (
                        fact
                        for fact in snapshot.problem.get("facts", ())
                        if isinstance(fact, dict)
                        and fact.get("type") == "midpoint_definition"
                        and {
                            _label_from_point_handle_or_entity(
                                str(handle), self.index
                            )
                            for handle in fact.get("of", ())
                        }
                        == {side_start, side_end}
                    ),
                    None,
                )
                center_fact = next(
                    (
                        fact
                        for fact in snapshot.problem.get("facts", ())
                        if isinstance(fact, dict)
                        and fact.get("type") == "square_center"
                        and (
                            square_fact is None
                            or fact.get("square") == square_fact.get("handle")
                        )
                    ),
                    None,
                )
                midpoint = _label_from_point_handle_or_entity(
                    str((midpoint_fact or {}).get("point") or ""),
                    self.index,
                )
                center = _label_from_point_handle_or_entity(
                    str((center_fact or {}).get("point") or ""),
                    self.index,
                )
                vertices = [
                    _label_from_point_handle_or_entity(str(handle), self.index)
                    for handle in (square_fact or {}).get("vertices", ())
                ]
                if all((side_start, side_end, moving, fixed, midpoint, center)):
                    return {
                        "type": "quadratic_square_path_minimum",
                        "original_path": str(
                            witness.get("original_objective") or ""
                        ),
                        "transformed_path": str(
                            witness.get("reduced_objective") or ""
                        ),
                        "roles": {
                            "side_start": side_start,
                            "side_end": side_end,
                            "midpoint": midpoint,
                            "center": center,
                            "other_fixed": fixed,
                            "moving_vertex": moving,
                            "square_vertices": vertices,
                        },
                        "segments": {
                            "center_midpoint": f"{center}{midpoint}",
                            "midpoint_fixed": f"{midpoint}{fixed}",
                            "fixed_moving": f"{fixed}{moving}",
                            "replacement": f"{side_start}{moving}",
                            "square_side": f"{side_start}{side_end}",
                        },
                        "relations": {},
                    }
        return {}

    def _atomic_square_reduction_markers(
        self,
        lesson_step: LessonStep,
        roles_payload: dict[str, Any],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not roles_payload:
            return []
        roles = roles_payload.get("roles") if isinstance(roles_payload.get("roles"), dict) else {}
        segments = roles_payload.get("segments") if isinstance(roles_payload.get("segments"), dict) else {}
        relations = roles_payload.get("relations") if isinstance(roles_payload.get("relations"), dict) else {}
        side_start = str(roles.get("side_start") or "")
        side_end = str(roles.get("side_end") or "")
        midpoint = str(roles.get("midpoint") or "")
        center = str(roles.get("center") or "")
        other_fixed = str(roles.get("other_fixed") or "")
        moving_vertex = str(roles.get("moving_vertex") or "")
        square_vertices = [
            str(item)
            for item in roles.get("square_vertices") or ()
            if isinstance(item, str) and item
        ]
        if not all((side_start, side_end, midpoint, center, other_fixed, moving_vertex)):
            return []

        def geom(label: str) -> str | None:
            # Macro-local derived square points use a scoped parametric
            # geometry definition.  Prefer it for every role, including
            # midpoint/center, rather than falling back to a later exact point
            # with the same student-facing label.
            axis_id = axis_parameter_point_id(label, lesson_step.scope_id)
            if axis_id in self._known_points:
                return axis_id
            return point_handles.get(label) or self.index.geometry_point_name(label, lesson_step.scope_id)

        refs = {
            label: geom(label)
            for label in {
                side_start,
                side_end,
                midpoint,
                center,
                other_fixed,
                moving_vertex,
                *square_vertices,
            }
            if label
        }
        if not all(refs.get(label) for label in (side_start, side_end, midpoint, center, other_fixed, moving_vertex)):
            return []

        square_side = str(segments.get("square_side") or f"{side_start}{side_end}")
        center_midpoint = str(segments.get("center_midpoint") or f"{center}{midpoint}")
        midpoint_fixed = str(segments.get("midpoint_fixed") or f"{midpoint}{other_fixed}")
        fixed_moving = str(segments.get("fixed_moving") or f"{other_fixed}{moving_vertex}")
        replacement = str(segments.get("replacement") or f"{side_start}{moving_vertex}")
        point_labels = [
            {"label": midpoint, "role": "midpoint"},
            {"label": center, "role": "center"},
        ]
        seen_point_labels = {midpoint, center}
        for label in square_vertices:
            if not label or label == side_start or label in seen_point_labels:
                continue
            point_labels.append(
                {
                    "label": label,
                    "role": "moving_vertex" if label == moving_vertex else "square_vertex",
                }
            )
            seen_point_labels.add(label)

        marker = {
            "roles": {
                "side_start": side_start,
                "side_end": side_end,
                "midpoint": midpoint,
                "center": center,
                "other_fixed": other_fixed,
                "moving_vertex": moving_vertex,
            },
            "role_point_refs": refs,
            "square_vertices": square_vertices,
            "square_outline": [
                refs[label]
                for label in square_vertices
                if refs.get(label)
            ],
            "triangles": [
                {
                    "name": f"Rt△{side_start}{side_end}{other_fixed}",
                    "role": "right_triangle",
                    "vertices": [refs[side_start], refs[other_fixed], refs[side_end]],
                },
                {
                    "name": f"△{side_start}{side_end}{moving_vertex}",
                    "role": "midline_triangle",
                    "vertices": [refs[side_start], refs[side_end], refs[moving_vertex]],
                },
            ],
            "segments": {
                "square_side": _segment_payload_from_label(square_side, geom),
                "center_midpoint": _segment_payload_from_label(center_midpoint, geom),
                "midpoint_fixed": _segment_payload_from_label(midpoint_fixed, geom),
                "fixed_moving": _segment_payload_from_label(fixed_moving, geom),
                "replacement": _segment_payload_from_label(replacement, geom),
            },
            "relations": {
                "center_midpoint_half": _segment_relation_label(
                    str(relations.get("center_midpoint_half_of_replacement") or f"{center_midpoint}={replacement}/2")
                ),
                "midpoint_fixed_half": _segment_relation_label(
                    str(relations.get("midpoint_fixed_half_of_side") or f"{midpoint_fixed}={square_side}/2")
                ),
                "merged_segment": _segment_relation_label(
                    str(relations.get("merged_segment") or f"{center_midpoint}+{midpoint_fixed}={replacement}")
                ),
                "path_equality": _segment_relation_label(
                    str(relations.get("path_equality") or f"{roles_payload.get('original_path', '')}={roles_payload.get('transformed_path', '')}")
                ),
            },
            "point_labels": point_labels,
        }
        return [marker]

    def _atomic_path_minimum_roles(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if "quadratic_square_path_minimum" in lesson_step.capability_ids:
            witness = _macro_evidence_for_lesson_step(
                snapshot,
                lesson_step,
                macro_id="quadratic_square_path_minimum",
            )
            if witness is not None:
                construction = next(
                    (
                        item
                        for item in witness.get("constructions", ())
                        if isinstance(item, dict)
                        and item.get("kind") == "line_reflection"
                    ),
                    None,
                )
                locus = next(
                    (
                        item
                        for item in witness.get("constructions", ())
                        if isinstance(item, dict)
                        and item.get("kind")
                        == "square_midpoint_center_reduction"
                    ),
                    None,
                )
                if construction is not None:
                    return {
                        **construction,
                        "moving_line": str(
                            (locus or {}).get("moving_locus") or ""
                        ),
                        "minimum_expression": str(
                            witness.get("minimum_expression") or ""
                        ),
                    }
        if "weighted_axis_path_minimum" in lesson_step.capability_ids:
            witness = _macro_evidence_for_lesson_step(
                snapshot,
                lesson_step,
                macro_id="weighted_axis_path_minimum",
            )
            if witness is None:
                return {}
            constructions = [
                item
                for item in witness.get("constructions", ())
                if isinstance(item, dict)
                and item.get("kind") == "weighted_right_triangle"
            ]
            if len(constructions) != 1:
                raise ValueError(
                    "visual_weighted_path_construction_invalid: "
                    f"step={lesson_step.lesson_step_id}, "
                    f"observed={len(constructions)}"
                )
            construction = constructions[0]
            student_auxiliary = construction.get("student_auxiliary_point")
            if not isinstance(student_auxiliary, dict):
                raise ValueError(
                    "visual_weighted_path_student_auxiliary_missing: "
                    f"step={lesson_step.lesson_step_id}"
                )
            auxiliary_label = str(student_auxiliary.get("label") or "")
            auxiliary_coordinates = student_auxiliary.get("coordinates")
            if (
                not auxiliary_label
                or not isinstance(auxiliary_coordinates, (list, tuple))
                or len(auxiliary_coordinates) != 2
            ):
                raise ValueError(
                    "visual_weighted_path_student_auxiliary_invalid: "
                    f"step={lesson_step.lesson_step_id}"
                )
            axis_geometry = construction.get("axis_projection_geometry")
            dynamic_constraint = (
                axis_geometry.get("dynamic_constraint")
                if isinstance(axis_geometry, dict)
                else None
            )
            if not isinstance(dynamic_constraint, dict):
                raise ValueError(
                    "visual_weighted_path_dynamic_constraint_missing: "
                    f"step={lesson_step.lesson_step_id}"
                )
            roles = {
                str(item.get("role") or ""): str(item.get("chosen_ref") or "")
                for item in witness.get("role_resolutions", ())
                if isinstance(item, dict)
            }
            required = {
                "fixed_point",
                "curve_point",
                "moving_point",
                "dynamic_parameter",
            }
            missing = sorted(
                role for role in required if not str(roles.get(role) or "")
            )
            if missing:
                raise ValueError(
                    "visual_weighted_path_public_roles_missing: "
                    f"step={lesson_step.lesson_step_id}, missing={missing}"
                )
            return {
                "construction_kind": "weighted_right_triangle",
                "fixed_point": roles["fixed_point"],
                "curve_point": roles["curve_point"],
                "moving_point": roles["moving_point"],
                "dynamic_parameter": roles["dynamic_parameter"],
                "dynamic_constraint": dict(dynamic_constraint),
                "auxiliary_point": auxiliary_label,
                "auxiliary_point_coordinates": [
                    str(item) for item in auxiliary_coordinates
                ],
                "auxiliary_locus": str(
                    construction.get("auxiliary_locus") or ""
                ),
                "weight": str(construction.get("weight") or ""),
                "original_objective": str(
                    witness.get("original_objective") or ""
                ),
                "reduced_objective": (
                    f"{construction.get('weight')}*"
                    f"({roles['curve_point']}{roles['moving_point']}+"
                    f"{auxiliary_label}{roles['moving_point']})"
                ),
                "minimum_expression": str(
                    witness.get("minimum_expression") or ""
                ),
            }
        return {}

    def _atomic_path_minimum_markers(
        self,
        lesson_step: LessonStep,
        roles_payload: dict[str, Any],
        point_handles: dict[str, str],
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not roles_payload:
            return []
        if roles_payload.get("construction_kind") == "weighted_right_triangle":
            return self._weighted_path_minimum_markers(
                lesson_step,
                roles_payload,
                point_handles,
            )
        source = str(roles_payload.get("reflect_source") or "")
        reflected = str(roles_payload.get("reflected_point_name") or "")
        moving = str(roles_payload.get("moving_point") or "")
        other = str(roles_payload.get("other_fixed_point") or "")
        if not all((source, reflected, moving, other)):
            return []

        def geom(label: str) -> str | None:
            axis_id = axis_parameter_point_id(label, lesson_step.scope_id)
            if axis_id in self._known_points:
                return axis_id
            return point_handles.get(label) or self.index.geometry_point_name(
                label, lesson_step.scope_id
            )

        moving_locus = str(roles_payload.get("moving_line") or "")
        source_ref = geom(source)
        reflected_ref = geom(reflected)
        moving_ref = (
            self._dynamic_point_ref_for_label(moving, lesson_step.scope_id, moving_locus)
            or geom(moving)
        )
        other_ref = geom(other)
        if not all((source_ref, reflected_ref, moving_ref, other_ref)):
            return []
        linked_square = self._linked_square_marker_for_atomic_path(
            lesson_step,
            snapshot,
            source_steps,
            target_label=moving,
        )

        def role_geom(label: str) -> str | None:
            if label == moving:
                return moving_ref
            return geom(label)

        transformed_path = str(roles_payload.get("transformed_path") or "")
        straightened_path = str(roles_payload.get("straightened_path") or "")
        segment_equality = str(roles_payload.get("segment_equality") or "")
        minimum_segment = str(roles_payload.get("minimum_segment") or f"{reflected}{other}")
        reflected_pair = _sympy_pair(roles_payload.get("reflected_point"))
        minimum_expr = str(roles_payload.get("minimum_expression") or "")
        if not minimum_expr:
            minimum_expr = ""

        locus_start = locus_line_endpoint_id(moving, lesson_step.scope_id, "start")
        locus_end = locus_line_endpoint_id(moving, lesson_step.scope_id, "end")
        has_locus = locus_start in self._known_points and locus_end in self._known_points
        marker: dict[str, Any] = {
            "roles": {
                "source_point": source,
                "reflected_point": reflected,
                "moving_point": moving,
                "other_fixed_point": other,
            },
            "role_point_refs": {
                source: source_ref,
                reflected: reflected_ref,
                moving: moving_ref,
                other: other_ref,
            },
            "display_labels": {
                reflected: _student_point_label(reflected),
            },
            "original_segments": [
                _segment_payload_from_path_term(segment, role_geom)
                for segment in _path_segment_terms(transformed_path)
            ],
            "straightened_segments": [
                _segment_payload_from_path_term(segment, role_geom)
                for segment in _path_segment_terms(straightened_path)
            ],
            "reflection_segment": _segment_payload_from_endpoint_labels(
                reflected,
                moving,
                role_geom,
            ),
            "source_segment": _segment_payload_from_endpoint_labels(source, moving, role_geom),
            "minimum_segment": _segment_payload_from_path_term(minimum_segment, role_geom)
            or _segment_payload_from_endpoint_labels(reflected, other, role_geom),
            "segment_equality": _student_segment_label(segment_equality),
            "path_equality": _student_path_equality(transformed_path, straightened_path),
            "moving_locus": _line_equation_display({"equation": moving_locus}) if moving_locus else "",
            "locus_line": {
                "from": locus_start,
                "to": locus_end,
                "label": _line_equation_display({"equation": moving_locus}) if moving_locus else "",
            }
            if has_locus
            else {},
            "reflected_display": _point_display_from_pair(_student_point_label(reflected), reflected_pair)
            if reflected_pair
            else "",
            "minimum_expression": student_math_display(minimum_expr, fullwidth_operators=True)
            if minimum_expr
            else "",
        }
        if linked_square:
            marker["linked_square"] = linked_square
        marker["original_segments"] = [
            item for item in marker["original_segments"] if item
        ]
        marker["straightened_segments"] = [
            item for item in marker["straightened_segments"] if item
        ]
        return [marker]

    def _weighted_path_minimum_markers(
        self,
        lesson_step: LessonStep,
        roles_payload: dict[str, Any],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        fixed = str(roles_payload.get("fixed_point") or "")
        curve = str(roles_payload.get("curve_point") or "")
        moving = str(roles_payload.get("moving_point") or "")
        auxiliary = str(roles_payload.get("auxiliary_point") or "")
        if not all((fixed, curve, moving, auxiliary)):
            return []

        def existing_geom(label: str) -> str:
            return str(
                point_handles.get(label)
                or self.index.geometry_point_name(label, lesson_step.scope_id)
                or ""
            )

        fixed_ref = existing_geom(fixed)
        curve_ref = existing_geom(curve)
        if not fixed_ref or not curve_ref:
            return []

        # The moving and auxiliary points are Frame-local constructions.  Raw
        # public labels are temporary role references only; the interaction
        # materializer replaces them with branch-scoped geometry identities
        # before VisualStepIR is serialized.
        role_point_refs = {
            fixed: fixed_ref,
            curve: curve_ref,
            moving: moving,
            auxiliary: auxiliary,
        }

        def segment(start: str, end: str, label: str = "") -> dict[str, str]:
            return {
                "from": role_point_refs[start],
                "to": role_point_refs[end],
                **({"label": label} if label else {}),
            }

        weight = student_math_display(
            str(roles_payload.get("weight") or ""),
            fullwidth_operators=True,
        )
        return [
            {
                "construction_kind": "weighted_right_triangle",
                "roles": {
                    "fixed_point": fixed,
                    "curve_point": curve,
                    "moving_point": moving,
                    "auxiliary_point": auxiliary,
                },
                "role_point_refs": role_point_refs,
                "dynamic_parameter": str(
                    roles_payload.get("dynamic_parameter") or ""
                ),
                "dynamic_constraint": dict(
                    roles_payload.get("dynamic_constraint") or {}
                ),
                "auxiliary_point_coordinates": list(
                    roles_payload.get("auxiliary_point_coordinates") or ()
                ),
                "triangle_outline": [fixed_ref, auxiliary, moving],
                "original_segments": (
                    segment(curve, moving),
                    segment(fixed, moving),
                ),
                "reduced_segments": (
                    segment(curve, moving),
                    segment(auxiliary, moving),
                ),
                "weighted_relation": segment(
                    fixed,
                    moving,
                    f"{fixed}{moving}＝{weight}·{auxiliary}{moving}",
                ),
                "path_equality": _student_path_equality(
                    str(roles_payload.get("original_objective") or ""),
                    str(roles_payload.get("reduced_objective") or ""),
                ),
                "auxiliary_locus": _line_equation_display(
                    {
                        "equation": str(
                            roles_payload.get("auxiliary_locus") or ""
                        )
                    }
                ),
                "minimum_expression": student_math_display(
                    str(roles_payload.get("minimum_expression") or ""),
                    fullwidth_operators=True,
                ),
            }
        ]

    def _dynamic_point_ref_for_label(
        self,
        label: str,
        scope_id: str,
        locus_equation: str,
    ) -> str:
        label = str(label or "")
        if not label:
            return ""
        scored: list[tuple[int, str]] = []
        moving_points = self.geometry_spec.get("movingPoints") or {}
        point_meta = self.geometry_spec.get("pointMeta") or {}
        for point_id, pair in moving_points.items():
            point_id = str(point_id)
            meta = point_meta.get(point_id) if isinstance(point_meta, dict) else None
            if not isinstance(meta, dict):
                continue
            if str(meta.get("label") or point_id) != label:
                continue
            point_root = str(meta.get("scopeRoot") or scope_root(str(meta.get("scopeId") or "")))
            if point_root != scope_root(scope_id):
                continue
            score = 1
            if _point_pair_satisfies_line(pair, locus_equation):
                score += 5
            definition = str(meta.get("definition") or "")
            if definition in {
                "parameterized_point",
                "runtime_point_output",
                "path_attainment_point",
            }:
                score += 2
            raw_semantic_roles = meta.get("semanticRoles", ())
            semantic_roles = (
                {raw_semantic_roles}
                if isinstance(raw_semantic_roles, str)
                else {str(item) for item in raw_semantic_roles}
            )
            if "path_attainment_point" in semantic_roles:
                score += 3
            if meta.get("sourceStepIds"):
                score += 1
            if not meta.get("visualOnly"):
                score += 1
            scored.append((score, point_id))
        if not scored:
            return ""
        best_score = max(score for score, _ in scored)
        winners = sorted(point_id for score, point_id in scored if score == best_score)
        if len(winners) != 1:
            raise ValueError(
                "visual_dynamic_point_provenance_ambiguous: "
                f"label={label}, scope={scope_id}, candidates={winners}"
            )
        return winners[0]

    def _equal_length_reduction_roles(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if "equal_length_ray_path_reduction" not in lesson_step.capability_ids:
            return {}
        if lesson_step.visual_unit_ids and not {
            "path_reduction",
            "minimum_by_segment",
        }.intersection(lesson_step.visual_unit_ids):
            return {}
        witness = _path_minimum_witness_for_lesson_step(snapshot, lesson_step)
        facts = _facts_by_handle(snapshot.problem)
        entities = self.index.entities_by_handle
        for step_id in lesson_step.source_step_ids:
            step = source_steps.get(step_id)
            if not step or step.get("recipe_hint") != "equal_length_ray_path_reduction":
                continue
            roles = _equal_length_roles_from_step(
                step,
                lesson_step,
                facts=facts,
                entities=entities,
                witness=witness,
            )
            if roles:
                return roles
        return {}

    def _equal_length_path_markers(
        self,
        lesson_step: LessonStep,
        roles: dict[str, Any],
        point_handles: dict[str, str],
    ) -> list[dict[str, Any]]:
        if not roles:
            return []

        segment_reference = str(roles.get("segment_reference_point") or "")
        anchor = str(roles.get("anchor") or "")
        ray_moving = str(roles.get("ray_moving_point") or "")
        auxiliary = str(roles.get("auxiliary_point") or "")
        segment_moving = str(roles.get("segment_moving_point") or "")
        fixed = str(roles.get("fixed_point") or "")
        local_override_labels = {segment_moving, ray_moving}

        def geom(label: str) -> str | None:
            point = point_handles.get(label) or self.index.geometry_point_name(
                label,
                lesson_step.scope_id,
            )
            if point:
                return point
            if label in local_override_labels:
                return label
            return None

        has_full_congruence_visual = all(
            geom(label)
            for label in (
                segment_reference,
                anchor,
                ray_moving,
                auxiliary,
                segment_moving,
            )
        )

        original_replace_segment = _segment_payload_from_label(
            str(roles.get("original_replace_segment") or ""),
            geom,
        )
        replacement_segment = _segment_payload_from_label(
            str(roles.get("replacement_segment") or ""),
            geom,
        )
        common_segment = _segment_payload_from_label(
            str(roles.get("common_path_segment") or ""),
            geom,
        )
        minimum_segment = _segment_payload_from_endpoints(
            fixed,
            auxiliary,
            geom,
        )
        role_point_refs = {
            label: geom(label)
            for label in (
                segment_reference,
                anchor,
                ray_moving,
                auxiliary,
                segment_moving,
                fixed,
            )
            if label
        }
        marker: dict[str, Any] = {
            "roles": {
                key: value
                for key, value in roles.items()
                if isinstance(value, (str, int, float)) and str(value)
            },
            "role_point_refs": {
                key: value for key, value in role_point_refs.items() if value
            },
            "triangles": [],
            "point_labels": [
                {"label": segment_moving, "role": "moving_point"},
                {"label": ray_moving, "role": "moving_point"},
                {"label": auxiliary, "role": "auxiliary_point"},
            ],
            "guide_lines": [
                {
                    "label": f"{anchor}{segment_moving}",
                    "from": geom(anchor),
                    "to": geom(segment_moving),
                    "style": "dashed",
                    "role": "anchor_to_segment_moving",
                },
                {
                    "label": f"{anchor}{ray_moving}",
                    "from": geom(anchor),
                    "to": geom(ray_moving),
                    "style": "dashed",
                    "role": "anchor_to_ray_moving",
                },
                {
                    "label": f"{anchor}{auxiliary}",
                    "from": geom(anchor),
                    "to": geom(auxiliary),
                    "style": "solid",
                    "role": "anchor_to_auxiliary",
                },
            ],
            "equivalent_segments": [
                original_replace_segment,
                replacement_segment,
            ],
            "common_path_segment": common_segment,
            "replacement_path_segment": replacement_segment,
            "minimum_segment": minimum_segment,
            "equivalence_label": _equal_segment_label(
                str(roles.get("original_replace_segment") or ""),
                str(roles.get("replacement_segment") or ""),
            ),
        }
        if has_full_congruence_visual:
            marker["triangles"] = [
                {
                    "name": f"△{segment_reference}{anchor}{ray_moving}",
                    "vertices": [geom(segment_reference), geom(anchor), geom(ray_moving)],
                },
                {
                    "name": f"△{auxiliary}{anchor}{segment_moving}",
                    "vertices": [geom(auxiliary), geom(anchor), geom(segment_moving)],
                },
            ]
        if common_segment:
            marker["path_lines"] = [common_segment]
        marker["equivalent_segments"] = [
            item for item in marker["equivalent_segments"] if item
        ]
        marker["guide_lines"] = [
            item for item in marker["guide_lines"] if item.get("from") and item.get("to")
        ]
        if (
            not marker["triangles"]
            and len(marker["equivalent_segments"]) < 2
            and not marker["guide_lines"]
        ):
            return []
        return [marker]


def _handle_tail(handle: str) -> str:
    return handle.rsplit(":", 1)[-1] if handle else ""


def _label_from_point_handle_or_entity(handle: str, index: VisualGeometryIndex) -> str:
    entity = index.entities_by_handle.get(handle)
    if isinstance(entity, dict):
        label = str(entity.get("name") or "")
        if label:
            return label
    return _handle_tail(handle)


def _label_from_effective_step(step_id: str, snapshot: ExplanationSnapshot) -> str:
    if not step_id:
        return ""
    for step in snapshot.effective_steps:
        if not isinstance(step, dict) or step.get("step_id") != step_id:
            continue
        target_labels = _point_labels_from_handle(str(step.get("target") or ""))
        if len(target_labels) == 1:
            return next(iter(target_labels))
        for produced in step.get("produces") or ():
            if not isinstance(produced, dict):
                continue
            handle_labels = _point_labels_from_handle(str(produced.get("handle") or ""))
            if len(handle_labels) == 1:
                return next(iter(handle_labels))
            description_labels = _capital_point_labels(str(produced.get("description") or ""))
            if len(description_labels) == 1:
                return next(iter(description_labels))
    return ""


def _label_from_semantic_name(name: str) -> str:
    labels = _point_labels_from_handle(name)
    return next(iter(labels)) if len(labels) == 1 else ""


def _candidate_curve_label(step: dict[str, Any], target_label: str) -> str:
    scored: list[tuple[int, str]] = []
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        labels = _point_labels_from_handle(handle)
        for label in labels:
            if label == target_label:
                continue
            score = 1 + (2 if "curve" in handle or "parabola" in handle else 0)
            scored.append((score, label))
    if not scored:
        return ""
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0][1]


def _candidate_display_label(label: str, index: int) -> str:
    subscripts = "₀₁₂₃₄₅₆₇₈₉"
    if 0 <= index < len(subscripts):
        return f"{label}{subscripts[index]}"
    return f"{label}{index}"


def _point_labels_from_step(step: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for handle in step.get("reads") or ():
        if isinstance(handle, str):
            labels.update(_point_labels_from_handle(handle))
    if step.get("recipe_hint") == "angle_sum_equal_angle_candidates":
        return labels
    for produced in step.get("produces") or ():
        if isinstance(produced, dict):
            labels.update(_point_labels_from_handle(str(produced.get("handle") or "")))
            description = str(produced.get("description") or "")
            labels.update(_capital_point_labels(description))
    return labels


def _point_labels_from_lesson_step(lesson_step: LessonStep) -> set[str]:
    labels: set[str] = set()
    text_parts = [lesson_step.title, lesson_step.goal, *lesson_step.box]
    text_parts.extend(text for _, text in lesson_step.derive)
    for text in text_parts:
        labels.update(_capital_point_labels(text))
    return labels


def _point_labels_from_handle(handle: str) -> set[str]:
    if not handle:
        return set()
    name = handle.rsplit(":", 1)[-1].split(".", 1)[-1]
    name = re.sub(r"_(coordinate|coord|point|value|expr|expression|candidate|candidates)$", "", name)
    labels = _capital_point_labels(name)
    for chunk in re.findall(r"[A-Z]{2,}", name):
        labels.update(chunk)
    return labels


def _capital_point_labels(text: str) -> set[str]:
    # Single capital letters are conventional point names in the current lesson
    # specs.  We only return labels that can later be mapped to authored geometry.
    labels = set(re.findall(r"(?<![A-Za-z])[A-Z](?![A-Za-z])", text))
    for chunk in re.findall(r"(?<![A-Za-z])([A-Z]{2,})(?![A-Za-z])", text):
        labels.update(chunk)
    return labels


def _facts_by_handle(problem: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for fact in problem.get("facts") or ():
        if not isinstance(fact, dict):
            continue
        handle = str(fact.get("handle") or "")
        if handle:
            out[handle] = fact
    return out


def _equal_length_roles_from_step(
    step: dict[str, Any],
    lesson_step: LessonStep,
    *,
    facts: dict[str, dict[str, Any]],
    entities: dict[str, dict[str, Any]],
    witness: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # The Macro is an atomic teaching source.  Its verified public witness is
    # therefore the canonical source of visual roles; do not require the
    # renderer to reconstruct those roles from runtime-private facts.
    if witness is not None:
        witness_roles = _equal_length_roles_from_witness(witness)
        if witness_roles:
            return witness_roles

    segment_fact: dict[str, Any] | None = None
    ray_fact: dict[str, Any] | None = None
    equal_fact: dict[str, Any] | None = None
    path_fact: dict[str, Any] | None = None
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        fact = facts.get(handle)
        if not fact:
            continue
        fact_type = str(fact.get("type") or "")
        if fact_type == "point_on_segment":
            segment_fact = fact
        elif fact_type == "point_on_ray":
            ray_fact = fact
        elif fact_type == "equal_length_condition":
            equal_fact = fact
        elif fact_type == "path_minimum_target":
            path_fact = fact
    if not segment_fact or not ray_fact or not equal_fact:
        return {}

    segment_moving = _point_label_from_handle(
        str(segment_fact.get("point") or ""),
        entities,
    )
    ray_moving = _point_label_from_handle(str(ray_fact.get("point") or ""), entities)
    segment_entity = entities.get(str(segment_fact.get("segment") or "")) or {}
    ray_entity = entities.get(str(ray_fact.get("ray") or "")) or {}
    segment_endpoints = [
        _point_label_from_handle(str(handle), entities)
        for handle in segment_entity.get("endpoints") or ()
    ]
    ray_origin = _point_label_from_handle(str(ray_entity.get("origin") or ""), entities)
    ray_direction = _point_label_from_handle(str(ray_entity.get("through") or ""), entities)
    equal_terms = [
        str(equal_fact.get("left") or ""),
        str(equal_fact.get("right") or ""),
    ]
    anchor = ray_origin or _common_label_in_segments(equal_terms)
    if not anchor:
        return {}
    segment_reference = next(
        (label for label in segment_endpoints if label and label != anchor),
        "",
    )
    original_path = str((path_fact or {}).get("path") or "")
    original_terms, reduced_terms = _path_terms_from_lesson_step(
        lesson_step,
        original_path,
    )
    if not original_terms:
        original_terms = _segment_terms(original_path)
    common_path = _common_path_term(original_terms, reduced_terms)
    original_replace = _segment_containing_label(original_terms, ray_moving)
    if not original_replace:
        original_replace = next(
            (term for term in original_terms if term not in set(reduced_terms)),
            "",
        )
    replacement = _segment_containing_label(reduced_terms, segment_moving, exclude={common_path})
    if not replacement:
        replacement = next(
            (term for term in reduced_terms if term not in set(original_terms)),
            "",
        )
    auxiliary = _other_endpoint(replacement, segment_moving)
    fixed = _other_endpoint(common_path, segment_moving)
    if witness is not None:
        resolved = {
            str(item.get("role") or ""): str(item.get("chosen_ref") or "").rsplit(".", 1)[-1]
            for item in witness.get("role_resolutions", ())
            if isinstance(item, dict)
        }
        anchor = resolved.get("anchor") or anchor
        segment_reference = resolved.get("reference_point") or segment_reference
        ray_direction = resolved.get("ray_point") or ray_direction
        fixed = resolved.get("fixed_point") or fixed
        constructions = witness.get("constructions", ())
        construction = constructions[0] if constructions else None
        if isinstance(construction, dict):
            auxiliary = str(construction.get("label") or auxiliary)
        original_path = str(witness.get("original_objective") or original_path)
        reduced_path = str(witness.get("reduced_objective") or "")
        if reduced_path:
            reduced_terms = _segment_terms(reduced_path)
            common_path = _segment_containing_label(
                reduced_terms,
                segment_moving,
            )
            replacement = _segment_containing_label(
                reduced_terms,
                auxiliary,
            )
    if not all((segment_moving, ray_moving, segment_reference, auxiliary)):
        return {}
    return {
        "anchor": anchor,
        "segment_moving_point": segment_moving,
        "ray_moving_point": ray_moving,
        "segment_reference_point": segment_reference,
        "ray_direction_point": ray_direction,
        "fixed_point": fixed,
        "auxiliary_point": auxiliary,
        "original_replace_segment": original_replace,
        "replacement_segment": replacement,
        "common_path_segment": common_path,
        "original_path": original_path or "+".join(original_terms),
        "reduced_path": (
            str(witness.get("reduced_objective"))
            if witness is not None and witness.get("reduced_objective")
            else "+".join(reduced_terms)
        ),
        "minimum_expression": (
            str(witness.get("minimum_expression") or "")
            if witness is not None
            else ""
        ),
        "minimizing_points": (
            dict(witness.get("minimizing_points") or {})
            if witness is not None
            else {}
        ),
    }


def _equal_length_roles_from_witness(witness: dict[str, Any]) -> dict[str, Any]:
    resolved = {
        str(item.get("role") or ""): str(item.get("chosen_ref") or "").rsplit(".", 1)[-1]
        for item in witness.get("role_resolutions", ())
        if isinstance(item, dict)
    }
    original_path = str(witness.get("original_objective") or "")
    reduced_path = str(witness.get("reduced_objective") or "")
    original_terms = _segment_terms(original_path)
    reduced_terms = _segment_terms(reduced_path)
    common_path = _common_path_term(original_terms, reduced_terms)

    constructions = [
        item for item in witness.get("constructions", ()) if isinstance(item, dict)
    ]
    construction = next(
        (
            item
            for item in constructions
            if item.get("kind") == "equal_length_point_on_ray"
        ),
        constructions[0] if constructions else None,
    )
    auxiliary = str((construction or {}).get("label") or "")
    segment_reference = resolved.get("reference_point", "")

    original_replace = _segment_containing_label(
        original_terms,
        segment_reference,
        exclude={common_path},
    )
    if not original_replace:
        original_replace = next(
            (term for term in original_terms if term not in set(reduced_terms)),
            "",
        )
    replacement = _segment_containing_label(
        reduced_terms,
        auxiliary,
        exclude={common_path},
    )
    if not replacement:
        replacement = next(
            (term for term in reduced_terms if term not in set(original_terms)),
            "",
        )

    segment_moving = _other_endpoint(replacement, auxiliary)
    ray_moving = _other_endpoint(original_replace, segment_reference)
    fixed = resolved.get("fixed_point", "")
    if not segment_moving and fixed:
        segment_moving = _other_endpoint(common_path, fixed)
    if not fixed and segment_moving:
        fixed = _other_endpoint(common_path, segment_moving)

    required = (
        resolved.get("anchor"),
        segment_moving,
        ray_moving,
        segment_reference,
        auxiliary,
    )
    if not all(required):
        return {}

    return {
        "anchor": resolved["anchor"],
        "segment_moving_point": segment_moving,
        "ray_moving_point": ray_moving,
        "segment_reference_point": segment_reference,
        "ray_direction_point": resolved.get("ray_point", ""),
        "fixed_point": fixed,
        "auxiliary_point": auxiliary,
        "original_replace_segment": original_replace,
        "replacement_segment": replacement,
        "common_path_segment": common_path,
        "original_path": original_path,
        "reduced_path": reduced_path,
        "minimum_expression": str(witness.get("minimum_expression") or ""),
        "minimizing_points": dict(witness.get("minimizing_points") or {}),
    }


def _path_minimum_witness_for_lesson_step(
    snapshot: ExplanationSnapshot,
    lesson_step: LessonStep,
) -> dict[str, Any] | None:
    return _macro_evidence_for_lesson_step(
        snapshot,
        lesson_step,
        macro_id="equal_length_ray_path_reduction",
    )


def _macro_evidence_for_lesson_step(
    snapshot: ExplanationSnapshot,
    lesson_step: LessonStep,
    *,
    macro_id: str,
) -> dict[str, Any] | None:
    source_step_ids = set(lesson_step.source_step_ids)
    for item in snapshot.macro_evidence:
        if item.get("macro_id") != macro_id:
            continue
        if str(item.get("step_id") or "") in source_step_ids:
            return item
    return None


def _point_labels_from_equal_length_roles(roles: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for key in (
        "anchor",
        "segment_moving_point",
        "ray_moving_point",
        "segment_reference_point",
        "ray_direction_point",
        "fixed_point",
        "auxiliary_point",
    ):
        value = str(roles.get(key) or "")
        if value:
            labels.add(value)
    for key in (
        "original_replace_segment",
        "replacement_segment",
        "common_path_segment",
    ):
        labels.update(_capital_point_labels(str(roles.get(key) or "")))
    return labels


def _point_labels_from_square_path_roles(payload: dict[str, Any]) -> set[str]:
    roles = payload.get("roles") if isinstance(payload.get("roles"), dict) else {}
    labels: set[str] = set()
    for key in (
        "side_start",
        "side_end",
        "midpoint",
        "center",
        "other_fixed",
        "moving_vertex",
    ):
        value = str(roles.get(key) or "")
        if value:
            labels.add(value)
    for item in roles.get("square_vertices") or ():
        if isinstance(item, str) and item:
            labels.add(item)
    for key in ("original_path", "transformed_path"):
        labels.update(_capital_point_labels(str(payload.get(key) or "")))
    return labels


def _point_labels_from_atomic_path_roles(payload: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    if payload.get("construction_kind") == "weighted_right_triangle":
        for key in (
            "fixed_point",
            "curve_point",
            "moving_point",
            "auxiliary_point",
        ):
            value = str(payload.get(key) or "")
            if value:
                labels.add(value)
        return labels
    for key in (
        "reflect_source",
        "reflected_point_name",
        "moving_point",
        "other_fixed_point",
    ):
        value = str(payload.get(key) or "")
        if value:
            labels.add(value)
    for key in ("transformed_path", "straightened_path", "segment_equality", "minimum_segment"):
        labels.update(_capital_point_labels(str(payload.get(key) or "")))
    return labels


def _point_label_from_handle(handle: str, entities: dict[str, dict[str, Any]]) -> str:
    entity = entities.get(handle) or {}
    name = str(entity.get("name") or "")
    if name:
        return name
    return _handle_tail(handle)


def _common_label_in_segments(segments: list[str]) -> str:
    if len(segments) < 2:
        return ""
    labels = [set(_capital_point_labels(segment)) for segment in segments if segment]
    if len(labels) < 2:
        return ""
    common = set.intersection(*labels)
    return next(iter(common), "")


def _path_terms_from_lesson_step(
    lesson_step: LessonStep,
    original_path: str,
) -> tuple[list[str], list[str]]:
    texts = [*lesson_step.box, *[text for _, text in lesson_step.derive], lesson_step.title]
    original_norm = _path_norm(original_path)
    original_terms = _segment_terms(original_path)
    for text in texts:
        for left, right in re.findall(
            r"([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})*)\s*=\s*([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})*)",
            text,
        ):
            left_terms = _segment_terms(left)
            right_terms = _segment_terms(right)
            if original_norm and _path_norm("+".join(left_terms)) == original_norm:
                return left_terms, right_terms
            if original_norm and _path_norm("+".join(right_terms)) == original_norm:
                return right_terms, left_terms
            if left_terms and right_terms and (len(left_terms) > 1 or len(right_terms) > 1):
                return left_terms, right_terms
    for text in texts:
        for candidate in re.findall(
            r"(?<![A-Za-z])([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})+)(?![A-Za-z])",
            text,
        ):
            terms = _segment_terms(candidate)
            if not terms:
                continue
            if original_norm and _path_norm("+".join(terms)) == original_norm:
                continue
            if original_terms and set(terms).intersection(original_terms):
                return original_terms, terms
    return (original_terms, [])


def _segment_terms(value: str) -> list[str]:
    return re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", value or "")


def _path_norm(value: str) -> str:
    return "+".join(_segment_terms(value))


def _sympy_pair(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    return _shared_sympy_pair(value)


def _fresh_projection_label(used_labels: set[str]) -> str:
    for label in PROJECTION_HELPER_LABEL_CANDIDATES:
        if label not in used_labels:
            return label
    index = 1
    while True:
        for label in PROJECTION_HELPER_LABEL_CANDIDATES:
            candidate = f"{label}{index}"
            if candidate not in used_labels:
                return candidate
        index += 1


def _square_known_side_for_visual_target(
    labels: list[str],
    target_label: str,
) -> tuple[int, int, int] | None:
    if len(labels) < 4:
        return None
    if target_label == labels[3]:
        return 0, 1, 3
    if target_label == labels[1]:
        return 0, 3, 1
    if target_label == labels[2]:
        return 1, 0, 2
    return None


def _coordinate_text_from_boxes(label: str, boxes: tuple[str, ...]) -> str:
    if not label:
        return ""
    pattern = re.compile(rf"{re.escape(label)}[（(]([^）)]+)[）)]")
    for text in boxes:
        match = pattern.search(str(text))
        if match:
            return f"{label}({match.group(1)})"
    return ""


def _point_display_from_geometry(point_id: str, geometry_spec: JsonObject) -> str:
    meta = (geometry_spec.get("pointMeta") or {}).get(point_id)
    label = (
        str(meta.get("label") or "")
        if isinstance(meta, dict)
        else ""
    )
    return _point_display_from_geometry_with_label(
        label or str(point_id),
        point_id,
        geometry_spec,
    )


def _point_display_from_geometry_with_label(
    label: str,
    point_id: str,
    geometry_spec: JsonObject,
) -> str:
    all_points: dict[str, Any] = {}
    all_points.update(geometry_spec.get("fixedPoints") or {})
    all_points.update(geometry_spec.get("movingPoints") or {})
    pair = _sympy_pair(all_points.get(point_id))
    if pair is None:
        return ""
    return f"{label}({_student_coord(pair[0])},{_student_coord(pair[1])})"


def _axis_parameterized_point_display(label: str, value: Any) -> str:
    pair = _sympy_pair(value)
    if pair is None:
        return f"{label}(t)"
    return _point_display_from_pair(label, pair)


def _square_target_display_from_runtime(
    *,
    source_step_id: str,
    target_label: str,
    snapshot: ExplanationSnapshot,
) -> str:
    if not source_step_id or not target_label:
        return ""
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        if _fact_step_id(item) != source_step_id:
            continue
        pair = _sympy_pair(item.get("value"))
        if pair is not None:
            return _point_display_from_pair(target_label, pair)
    return ""


def _square_target_value_from_runtime(
    *,
    source_step_id: str,
    snapshot: ExplanationSnapshot,
) -> list[str]:
    if not source_step_id:
        return []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        if _fact_step_id(item) != source_step_id:
            continue
        value = item.get("value")
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return [str(value[0]), str(value[1])]
    return []


def _point_display_from_pair(label: str, pair: tuple[sp.Expr, sp.Expr]) -> str:
    return f"{label}({_student_coord(pair[0])},{_student_coord(pair[1])})"


def _value_depends_on_symbol(value: Any, symbol: str) -> bool:
    return value_depends_on_symbol(value, symbol)


def _runtime_line_for_step(step: dict[str, Any], snapshot: ExplanationSnapshot) -> dict[str, Any] | None:
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


def _locus_point_label_for_step(step: dict[str, Any]) -> str:
    for handle in step.get("reads") or ():
        if isinstance(handle, str) and handle.startswith("point:"):
            label = _label_from_runtime_point_handle(handle)
            if label:
                return label
    return ""


def _label_from_locus_target(target: str) -> str:
    name = _handle_tail(target)
    for suffix in ("_locus_line", "_line", "_locus"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return _label_from_semantic_name(name)


def _line_equation_display(line: dict[str, Any]) -> str:
    equation = str(line.get("equation") or "")
    match = re.match(r"\s*([xy])\s*=\s*(.+)\s*$", equation)
    if not match:
        return equation.replace("=", "＝")
    axis, raw_expr = match.groups()
    try:
        expr = sp.factor(
            sp.sympify(
                raw_expr.replace("^", "**"),
                locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs},
            )
        )
    except Exception:
        expr = raw_expr
    return f"{axis}＝{student_math_display(str(expr), fullwidth_operators=True)}"


def _label_from_runtime_point_handle(handle: str) -> str:
    tail = _handle_tail(handle)
    return _label_from_semantic_name(tail)


def _student_coord(value: sp.Expr) -> str:
    text = re.sub(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", "t", sp.sstr(value))
    return student_math_display(text, fullwidth_operators=False)


def _coordinate_expr(value: Any) -> str:
    expr = _sympify_expr(value)
    if expr is None:
        return student_math_display(value, fullwidth_operators=False)
    return _student_coord(expr)


def _is_point_pair(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 2


def _sympify_expr(value: Any) -> sp.Expr | None:
    return sympify_visual_expr(value)


def _same_point_pair(left: tuple[sp.Expr, sp.Expr], right: tuple[sp.Expr, sp.Expr]) -> bool:
    return (
        sp.simplify(left[0] - right[0]) == 0
        and sp.simplify(left[1] - right[1]) == 0
    )


def _point_pair_satisfies_line(value: Any, equation: str) -> bool:
    pair = _sympy_pair(value)
    if pair is None:
        return False
    match = re.match(r"\s*([xy])\s*=\s*(.+)\s*$", str(equation or ""))
    if not match:
        return False
    axis, raw_expr = match.groups()
    expr = _sympify_expr(raw_expr)
    if expr is None:
        return False
    coordinate = pair[0] if axis == "x" else pair[1]
    return sp.simplify(coordinate - expr) == 0


def _common_path_term(original_terms: list[str], reduced_terms: list[str]) -> str:
    reduced = set(reduced_terms)
    return next((term for term in original_terms if term in reduced), "")


def _segment_containing_label(
    terms: list[str],
    label: str,
    *,
    exclude: set[str] | None = None,
) -> str:
    if not label:
        return ""
    excluded = exclude or set()
    return next((term for term in terms if term not in excluded and label in term), "")


def _other_endpoint(segment: str, endpoint: str) -> str:
    if len(segment) != 2 or endpoint not in segment:
        return ""
    return segment[0] if segment[1] == endpoint else segment[1]


def _segment_payload_from_label(
    segment: str,
    geom: Any,
) -> dict[str, Any]:
    if len(segment) != 2:
        return {}
    start = geom(segment[0])
    end = geom(segment[1])
    if not start or not end:
        return {}
    return {"label": segment, "from": start, "to": end}


def _segment_payload_from_endpoints(
    start_label: str,
    end_label: str,
    geom: Any,
) -> dict[str, Any]:
    if not start_label or not end_label:
        return {}
    start = geom(start_label)
    end = geom(end_label)
    if not start or not end:
        return {}
    return {"label": f"{start_label}{end_label}", "from": start, "to": end}


def _path_segment_terms(value: str) -> list[str]:
    terms: list[str] = []
    for part in re.split(r"\s*[+＋]\s*", str(value or "")):
        labels = _point_labels_in_path_term(part)
        if len(labels) == 2:
            terms.append("".join(labels))
    return terms


def _point_labels_in_path_term(term: str) -> list[str]:
    return re.findall(r"[A-Z](?:_prime)?", str(term or ""))


def _segment_payload_from_path_term(term: str, geom: Any) -> dict[str, Any]:
    labels = _point_labels_in_path_term(term)
    if len(labels) != 2:
        return {}
    return _segment_payload_from_endpoint_labels(labels[0], labels[1], geom)


def _segment_payload_from_endpoint_labels(
    start_label: str,
    end_label: str,
    geom: Any,
) -> dict[str, Any]:
    if not start_label or not end_label:
        return {}
    start = geom(start_label)
    end = geom(end_label)
    if not start or not end:
        return {}
    return {
        "label": _student_segment_label(f"{start_label}{end_label}"),
        "from": start,
        "to": end,
    }


def _equal_segment_label(left: str, right: str) -> str:
    if not left or not right:
        return ""
    return f"{left}={right}"


def _student_point_label(label: str) -> str:
    return str(label).replace("_prime", "′")


def _student_segment_label(text: str) -> str:
    return re.sub(r"([A-Z])_prime", r"\1′", str(text or "")).replace("+", "＋")


def _student_path_equality(left: str, right: str) -> str:
    if not left or not right:
        return ""
    return f"{_student_segment_label(left)}={_student_segment_label(right)}"


def _segment_relation_label(text: str) -> str:
    return str(text).strip()


def _visible_angle_equalities(lesson_step: LessonStep) -> list[tuple[str, str]]:
    text_parts = [*lesson_step.box]
    from_box = _angle_equalities_from_texts(text_parts)
    if from_box:
        return from_box
    text_parts = [text for _, text in lesson_step.derive]
    text_parts.append(lesson_step.title)
    return _angle_equalities_from_texts(text_parts)


def _angle_sum_display_equalities_from_source(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
    source_steps: dict[str, dict[str, Any]],
) -> list[tuple[str, str]]:
    facts = _facts_by_handle(snapshot.problem)
    outputs = _angle_sum_outputs_from_method(lesson_step, snapshot)
    source_step_ids = set(lesson_step.source_step_ids)
    out: list[tuple[str, str]] = []
    for step_id in source_step_ids:
        step = source_steps.get(step_id)
        if not step or step.get("recipe_hint") != "angle_sum_equal_angle_candidates":
            continue
        for handle in step.get("reads") or ():
            if not isinstance(handle, str):
                continue
            fact = facts.get(handle)
            if not fact or fact.get("type") != "angle_sum":
                continue
            terms = [str(item) for item in fact.get("angle_terms") or ()]
            if len(terms) != 2 or not all(len(item) == 3 for item in terms):
                continue
            for output in outputs:
                reference_angle = str(output.get("reference_angle") or "")
                candidate = _display_equality_from_angle_sum_terms(terms, reference_angle)
                if candidate:
                    out.append(candidate)
                    break
            if not outputs:
                # Fall back to the canonical method convention when the runtime
                # trace is not available: first term is the shared angle, second
                # term is the reference angle.
                shared, reference = terms
                target = _angle_target_by_replacing_shared_ray(shared, f"{shared[0]}{shared[1]}O")
                if target:
                    out.append((target, reference))
    return _dedupe_angle_equalities(out)


def _angle_sum_outputs_from_method(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> list[dict[str, Any]]:
    source_step_ids = {str(step_id) for step_id in lesson_step.source_step_ids}
    out: list[dict[str, Any]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "AngleEquality":
            continue
        if not _angle_equality_fact_belongs_to_step(item, source_step_ids, lesson_step.scope_id):
            continue
        value = item.get("value")
        if isinstance(value, dict):
            out.append(dict(value))
    return out


def _display_equality_from_angle_sum_terms(
    terms: list[str],
    reference_angle: str,
) -> tuple[str, str] | None:
    if len(reference_angle) != 3:
        return None
    for index, shared in enumerate(terms):
        target = _angle_target_by_replacing_shared_ray(shared, reference_angle)
        if not target:
            continue
        right = terms[1 - index]
        return (target, right)
    return None


def _angle_target_by_replacing_shared_ray(shared: str, reference_angle: str) -> str:
    """Return the display angle for the narrow two-angle-sum case.

    This intentionally only handles structures where ``shared`` and
    ``reference_angle`` have the same vertex and exactly one shared ray.  More
    complex angle-sum facts should fall back to text-based display instead of
    guessing a visual target angle.
    """
    if len(shared) != 3 or len(reference_angle) != 3:
        return ""
    if shared[1] != reference_angle[1]:
        return ""
    shared_rays = {shared[0], shared[2]}
    reference_rays = {reference_angle[0], reference_angle[2]}
    common = shared_rays & reference_rays
    if len(common) != 1:
        return ""
    shared_ray = next(iter(common))
    replacement = next((label for label in reference_rays if label != shared_ray), "")
    target_ray = next((label for label in shared_rays if label != shared_ray), "")
    if not replacement or not target_ray:
        return ""
    return f"{replacement}{shared[1]}{target_ray}"


def _display_line_segment_from_lesson_step(lesson_step: LessonStep) -> str:
    texts = [lesson_step.title, lesson_step.goal, *lesson_step.box]
    texts.extend(text for _, text in lesson_step.derive)
    for text in texts:
        match = re.search(r"直线\s*([A-Z]{2})", text)
        if match:
            return match.group(1)
    return ""


def _coordinate_result_label(lesson_step: LessonStep) -> str:
    for text in (*lesson_step.box, *[item for _, item in lesson_step.derive]):
        match = re.search(r"(?<![A-Za-z])([A-Z])\s*[（(]", str(text))
        if match:
            return match.group(1)
    return ""


def _axis_intercept_equality(
    equality: tuple[str, str],
    *,
    display_line: str,
    result_label: str,
) -> tuple[str, str]:
    if not result_label:
        return equality
    if len(display_line) != 2:
        shared = set(equality[0]) & set(equality[1])
        if len(shared) == 1:
            origin = next(iter(shared))
            candidate = next(
                (
                    angle
                    for angle in equality
                    if len(angle) == 3 and origin in {angle[0], angle[2]}
                ),
                "",
            )
            display_line = "".join(
                label for label in candidate if label != origin
            )
    if len(display_line) != 2:
        return equality
    out: list[str] = []
    for angle in equality:
        if len(angle) != 3 or not all(label in angle for label in display_line):
            out.append(angle)
            continue
        vertex = angle[1]
        replaced = angle
        for endpoint in display_line:
            if endpoint != vertex:
                replaced = angle.replace(endpoint, result_label, 1)
                break
        out.append(replaced)
    return tuple(out) if len(out) == 2 else equality


def _dedupe_angle_equalities(items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _reference_angles_from_method_output(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> list[tuple[str, str]]:
    source_step_ids = {str(step_id) for step_id in lesson_step.source_step_ids}
    out: list[tuple[str, str]] = []
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "AngleEquality":
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        if not _angle_equality_fact_belongs_to_step(item, source_step_ids, lesson_step.scope_id):
            continue
        angle = str(value.get("reference_angle") or "")
        if len(angle) != 3:
            continue
        angle_value = _reference_angle_value(value)
        out.append((angle, angle_value))
    return out


def _axis_angle_equality_from_step(step: dict[str, Any]) -> tuple[str, str]:
    for handle in step.get("reads") or ():
        if not isinstance(handle, str):
            continue
        match = re.search(r"angle_([A-Z]{3})_eq_([A-Z]{3})", handle)
        if match:
            return (match.group(1), match.group(2))
    return ("", "")


def _origin_label_from_angles(equality: tuple[str, str]) -> str:
    left, right = equality
    if len(left) != 3 or len(right) != 3:
        return ""
    shared = set(left) & set(right)
    if len(shared) == 1:
        return next(iter(shared))
    return ""


def _angle_equality_fact_belongs_to_step(
    item: dict[str, Any],
    source_step_ids: set[str],
    scope_id: str,
) -> bool:
    handle = str(item.get("handle") or "")
    if any(handle.startswith(f"runtime:{step_id}:") for step_id in source_step_ids):
        return True
    if str(item.get("source_step_id") or "") in source_step_ids:
        return True
    return (
        str(item.get("source") or "") == "angle_sum_equal_angle_candidates"
        and str(item.get("scope_id") or "") == scope_id
    )


def _reference_angle_value(value: dict[str, Any]) -> str:
    explicit = str(value.get("reference_angle_value") or "").strip()
    if explicit:
        return explicit if explicit.endswith("°") else f"{explicit}°"
    source = str(value.get("source") or "")
    match = re.search(r"=\s*([0-9]+)\s*°", source)
    if match:
        return f"{match.group(1)}°"
    return ""


def _angle_equalities_from_texts(text_parts: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for text in text_parts:
        for left, right in re.findall(
            r"∠\s*([A-Z]{3})\s*[=＝]\s*∠\s*([A-Z]{3})",
            text,
        ):
            item = (left, right)
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
    return out


def _axis_arm(vertex: str, endpoint: str, origin_labels: frozenset[str] | set[str]) -> bool:
    return bool({vertex, endpoint} & set(origin_labels))


def _fact_step_id(item: dict[str, Any]) -> str:
    return str(item.get("source_step_id") or item.get("scope_id") or "")
