"""Role binding helpers for VisualStepIR generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonStep

from .geometry_naming import GeometryPointScopeNamer, scope_root
from .models import JsonObject


@dataclass(frozen=True)
class VisualRoleBindings:
    """Verified visual handles available to one Lesson step."""

    point_handles: dict[str, str] = field(default_factory=dict)
    curve_ids: tuple[str, ...] = ()
    translation_markers: tuple[dict[str, Any], ...] = ()
    angle_equalities: tuple[dict[str, Any], ...] = ()
    angle_references: tuple[dict[str, Any], ...] = ()
    axis_intercept_markers: tuple[dict[str, Any], ...] = ()
    equal_length_path_markers: tuple[dict[str, Any], ...] = ()
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
        for entity in self.problem.get("entities") or ():
            if not isinstance(entity, dict):
                continue
            handle = str(entity.get("handle") or "")
            if handle:
                self.entities_by_handle[handle] = entity
            name = str(entity.get("name") or "")
            if name and name not in self.entities_by_name:
                self.entities_by_name[name] = entity

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
                return candidate
        return None

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


class VisualRoleBinderRegistry:
    """Bind canonical handles to existing authored geometry names.

    VS1 intentionally uses the authored geometry base as the source of drawable
    point ids.  If a runtime handle cannot be mapped to that base, the builder
    should emit a VisualGap instead of inventing a point.
    """

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

        point_handles: dict[str, str] = {}
        for label in sorted(labels):
            geometry_name = self.index.geometry_point_name(label, lesson_step.scope_id)
            if geometry_name:
                point_handles[label] = geometry_name

        return VisualRoleBindings(
            point_handles=point_handles,
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
            axis_intercept_markers=tuple(
                self._axis_intercept_markers(lesson_step, source_steps, point_handles)
            ),
            equal_length_path_markers=tuple(
                self._equal_length_path_markers(
                    lesson_step,
                    equal_length_roles,
                    point_handles,
                )
            ),
            source_step_ids=tuple(lesson_step.source_step_ids),
            capability_ids=tuple(lesson_step.capability_ids),
        )

    def geometry_point_name(self, label: str, scope_id: str | None) -> str | None:
        return self.index.geometry_point_name(label, scope_id)

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
            for read_handle in step.get("reads") or ():
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
                            "source_display": _point_display_from_geometry(source, self.geometry_spec),
                            "target_display": _point_display_from_geometry(target, self.geometry_spec),
                            "vector": [str(vector[0]), str(vector[1])],
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
            origin_label = self._origin_label_from_step(step) or _origin_label_from_angles(axis_equality)
            if not axis_equality or not origin_label:
                continue
            equality_markers: list[dict[str, Any]] = []
            display_line = _display_line_segment_from_lesson_step(lesson_step)
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
            if _axis_arm(vertex, endpoint):
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

    def _equal_length_reduction_roles(
        self,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        source_steps: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if "equal_length_ray_path_reduction" not in lesson_step.capability_ids:
            return {}
        if lesson_step.teaching_substep_ids and not {
            "path_reduction",
            "minimum_by_segment",
        }.intersection(lesson_step.teaching_substep_ids):
            return {}
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
) -> dict[str, Any]:
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
        "original_path": "+".join(original_terms),
        "reduced_path": "+".join(reduced_terms),
    }


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
    if not isinstance(value, list | tuple) or len(value) != 2:
        return None
    x = _sympify_expr(value[0])
    y = _sympify_expr(value[1])
    if x is None or y is None:
        return None
    return (x, y)


def _point_display_from_geometry(point_id: str, geometry_spec: JsonObject) -> str:
    all_points: dict[str, Any] = {}
    all_points.update(geometry_spec.get("fixedPoints") or {})
    all_points.update(geometry_spec.get("movingPoints") or {})
    pair = _sympy_pair(all_points.get(point_id))
    if pair is None:
        return ""
    label = str(point_id).rstrip("0123456789") or str(point_id)
    return f"{label}({_student_coord(pair[0])},{_student_coord(pair[1])})"


def _student_coord(value: sp.Expr) -> str:
    return sp.sstr(value).replace("**2", "²").replace("*", "")


def _sympify_expr(value: Any) -> sp.Expr | None:
    try:
        text = str(value).replace("^", "**")
        text = re.sub(r"\babs\s*\(", "Abs(", text)
        text = re.sub(r"\b([A-Za-z_][A-Za-z0-9_]*)\*\1\b", r"\1**2", text)
        return sp.simplify(
            sp.sympify(
                text,
                locals={"sqrt": sp.sqrt, "Abs": sp.Abs, "abs": sp.Abs},
            )
        )
    except Exception:
        return None


def _same_point_pair(left: tuple[sp.Expr, sp.Expr], right: tuple[sp.Expr, sp.Expr]) -> bool:
    return (
        sp.simplify(left[0] - right[0]) == 0
        and sp.simplify(left[1] - right[1]) == 0
    )


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


def _equal_segment_label(left: str, right: str) -> str:
    if not left or not right:
        return ""
    return f"{left}={right}"


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
        angle_value = _reference_angle_value(value) or "45°"
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
    source = str(value.get("source") or "")
    match = re.search(r"=\s*([0-9]+)\s*°", source)
    if match:
        return f"{match.group(1)}°"
    return ""


def _angle_equalities_from_texts(text_parts: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for text in text_parts:
        for left, right in re.findall(r"∠\s*([A-Z]{3})\s*=\s*∠\s*([A-Z]{3})", text):
            item = (left, right)
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
    return out


def _axis_arm(vertex: str, endpoint: str) -> bool:
    return "O" in {vertex, endpoint}
