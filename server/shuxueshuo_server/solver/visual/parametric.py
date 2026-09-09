"""Local interaction parameterization for VisualStepIR VS2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import math
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.lesson_ir import (
    OwnedLessonStep as LessonStep,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingSource,
    iter_teaching_sources,
)

from .models import JsonObject, VisualObject
from .role_binders import VisualRoleBindings
from .sympy_helpers import sympy_pair as _shared_sympy_pair


@dataclass(frozen=True)
class ParametricExpressionResolver:
    """Resolve method/recipe visual roles into local slider point overrides."""

    geometry_spec: JsonObject
    default_t: float = 0.75
    local_parameter: str = "u"

    def interactions_for_step(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
        *,
        interaction_specs: Sequence[Mapping[str, Any]] = (),
    ) -> tuple[JsonObject, ...]:
        result: list[JsonObject] = []
        if "equal_length_ray_path_reduction" in lesson_step.capability_ids:
            marker = _first_equal_length_marker(bindings)
            if marker is not None:
                interaction = self._equal_length_interaction(lesson_step, marker)
                if interaction:
                    result.append(interaction)
        for spec in interaction_specs:
            kind = str(spec.get("kind") or "")
            if kind == "square_axis_motion":
                interaction = self._square_axis_motion_interaction(
                    lesson_step,
                    bindings,
                )
                error_code = "visual_square_axis_motion_unresolved"
            elif kind == "weighted_axis_motion":
                interaction = self._weighted_axis_motion_interaction(
                    lesson_step,
                    bindings,
                )
                error_code = "visual_weighted_axis_motion_unresolved"
            elif kind == "coupled_segment_motion":
                interaction = self._coupled_segment_motion_interaction(
                    lesson_step,
                    bindings,
                )
                error_code = "visual_coupled_segment_motion_unresolved"
            else:
                raise ValueError(
                    f"visual_local_interaction_kind_unknown: {kind or '<empty>'}"
                )
            if interaction is None:
                raise ValueError(
                    f"{error_code}: "
                    f"{lesson_step.lesson_step_id}"
                )
            result.append(interaction)
        return tuple(_unique_interactions(result))

    def _coupled_segment_motion_interaction(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
    ) -> JsonObject | None:
        """Link a segment point to every certificate-derived dependent point."""

        marker = _first_coupled_segment_motion_marker(bindings)
        if marker is None:
            return None
        motion = (
            marker.get("coupled_motion")
            if isinstance(marker.get("coupled_motion"), dict)
            else {}
        )
        moving_ref = str(motion.get("moving_ref") or "")
        moving_label = str(motion.get("moving_label") or "")
        dependent_label = str(motion.get("dependent_label") or "")
        segment_start = str(motion.get("segment_start") or "")
        segment_end = str(motion.get("segment_end") or "")
        start_expr = self._point_expr(segment_start)
        end_expr = self._point_expr(segment_end)
        if (
            not moving_ref
            or not moving_label
            or start_expr is None
            or end_expr is None
        ):
            return None

        parameter_name = _fresh_local_parameter_name(self.geometry_spec)
        parameter = sp.Symbol(parameter_name)
        moving_expr = _interpolate(start_expr, end_expr, parameter)
        parameterized_points: dict[str, JsonObject] = {
            moving_ref: {
                "expression": _format_pair(moving_expr),
                "source": {
                    "type": "coupled_segment_motion",
                    "role": "hypotenuse_moving_point",
                    "segment_start": segment_start,
                    "segment_end": segment_end,
                },
            }
        }
        carriers: list[JsonObject] = [
            {
                "kind": "segment",
                "moving_point": moving_ref,
                "from": segment_start,
                "to": segment_end,
                "persistence": "step_only",
            }
        ]

        anchor_ref = str(motion.get("anchor") or "")
        first_leg_moving_ref = str(motion.get("first_leg_moving") or "")
        first_projection_ref = str(motion.get("first_projection") or "")
        second_projection_ref = str(motion.get("second_projection") or "")
        anchor_expr = self._point_expr(anchor_ref) if anchor_ref else None
        if (
            anchor_expr is not None
            and first_leg_moving_ref
            and first_projection_ref
            and second_projection_ref
        ):
            one_minus = 1 - parameter
            parameterized_points.update(
                {
                    first_leg_moving_ref: {
                        "expression": _format_pair(
                            _interpolate(anchor_expr, start_expr, 2 * one_minus)
                        ),
                        "source": {
                            "type": "coupled_segment_motion",
                            "role": "first_leg_moving_point",
                        },
                    },
                    first_projection_ref: {
                        "expression": _format_pair(
                            _interpolate(anchor_expr, start_expr, one_minus)
                        ),
                        "source": {
                            "type": "coupled_segment_motion",
                            "role": "first_leg_projection",
                        },
                    },
                    second_projection_ref: {
                        "expression": _format_pair(
                            _interpolate(anchor_expr, end_expr, parameter)
                        ),
                        "source": {
                            "type": "coupled_segment_motion",
                            "role": "second_leg_projection",
                        },
                    },
                }
            )
            carriers.append(
                {
                    "kind": "segment",
                    "moving_point": first_leg_moving_ref,
                    "from": anchor_ref,
                    "to": segment_start,
                    "persistence": "step_only",
                }
            )

        domain = (
            marker.get("motion_domain")
            if isinstance(marker.get("motion_domain"), dict)
            else {}
        )
        try:
            minimum = float(sp.N(sp.sympify(str(domain.get("min") or 0))))
            maximum = float(sp.N(sp.sympify(str(domain.get("max") or 1))))
            default = float(
                sp.N(sp.sympify(str(domain.get("default") or "1/2")))
            )
        except (sp.SympifyError, TypeError, ValueError):
            return None
        attainment = _shared_sympy_pair(marker.get("attainment_point"))
        if attainment is not None:
            for index in range(2):
                delta = sp.simplify(end_expr[index] - start_expr[index])
                if delta == 0:
                    continue
                ratio = sp.simplify(
                    (attainment[index] - start_expr[index]) / delta
                )
                if not ratio.free_symbols:
                    candidate = float(sp.N(ratio))
                    if minimum <= candidate <= maximum:
                        default = candidate
                break

        return {
            "id": f"{lesson_step.id}:coupled_segment_motion",
            "component": "LocalSlider",
            "parameter": parameter_name,
            "mathematical_domain": {
                "kind": "closed_interval",
                "min": minimum,
                "max": maximum,
            },
            "domain": {
                "min": minimum,
                "max": maximum,
                "step": 0.01,
                "default": round(default, 6),
            },
            "controls": [
                {
                    "var": parameter_name,
                    "label": (
                        f"动点 {moving_label}（{dependent_label} 联动）"
                        if dependent_label
                        else f"动点 {moving_label}"
                    ),
                    "min": minimum,
                    "max": maximum,
                    "step": 0.01,
                    "scale": 1,
                    "precision": 2,
                }
            ],
            "note": (
                f"拖动{moving_label}，观察"
                f"{dependent_label or '相关动点'}与路径同步变化。"
            ),
            "parameterized_points": parameterized_points,
            "constraint_carriers": carriers,
        }

    def _weighted_axis_motion_interaction(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
    ) -> JsonObject | None:
        """Animate the verified weighted construction with one local axis point.

        The public witness owns the moving-point role, its parameter, and the
        auxiliary-point formula.  This method only assigns a finite viewport-
        derived demonstration window; it never chooses a student point name
        or reconstructs the weighted geometry from presentation text.
        """

        marker = _first_weighted_axis_motion_marker(bindings)
        if marker is None:
            return None
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        refs = (
            marker.get("role_point_refs")
            if isinstance(marker.get("role_point_refs"), dict)
            else {}
        )
        moving_label = str(roles.get("moving_point") or "")
        auxiliary_label = str(roles.get("auxiliary_point") or "")
        moving_ref = str(refs.get(moving_label) or "")
        auxiliary_ref = str(refs.get(auxiliary_label) or "")
        parameter_name = str(marker.get("dynamic_parameter") or "")
        dynamic_constraint = marker.get("dynamic_constraint")
        raw_formula = marker.get("auxiliary_point_coordinates")
        if (
            not moving_label
            or not auxiliary_label
            or not moving_ref
            or not auxiliary_ref
            or not parameter_name
            or not isinstance(dynamic_constraint, dict)
            or not isinstance(raw_formula, (list, tuple))
            or len(raw_formula) != 2
        ):
            return None
        parameter = sp.Symbol(parameter_name)
        try:
            auxiliary = (
                sp.sympify(str(raw_formula[0]), locals={"sqrt": sp.sqrt}),
                sp.sympify(str(raw_formula[1]), locals={"sqrt": sp.sqrt}),
            )
        except (sp.SympifyError, TypeError, ValueError):
            return None
        allowed = {parameter}
        if set(auxiliary[0].free_symbols) - allowed or set(auxiliary[1].free_symbols) - allowed:
            return None

        domain = self.geometry_spec.get("domain") or {}
        try:
            viewport_min = float(domain["minX"])
            viewport_max = float(domain["maxX"])
        except (KeyError, TypeError, ValueError):
            return None
        if not math.isfinite(viewport_min) or not math.isfinite(viewport_max):
            return None
        width = viewport_max - viewport_min
        if width <= 0:
            return None
        margin = width * 0.12
        step = max(width / 240, 0.01)
        constrained = _constraint_domain_and_window(
            parameter_name=parameter_name,
            constraint=dynamic_constraint,
            viewport_min=viewport_min + margin,
            viewport_max=viewport_max - margin,
            step=step,
        )
        if constrained is None:
            return None
        mathematical_domain, minimum, maximum, default = constrained
        controls = (
            []
            if mathematical_domain.get("kind") == "exact"
            else [
                {
                    "var": parameter_name,
                    "label": f"动点 {moving_label}",
                    "min": round(minimum, 6),
                    "max": round(maximum, 6),
                    "step": round(step, 6),
                    "scale": 1,
                    "precision": 2,
                }
            ]
        )
        return {
            "id": f"{lesson_step.id}:weighted_axis_motion",
            "component": "LocalSlider",
            "parameter": parameter_name,
            "mathematical_domain": mathematical_domain,
            "domain": {
                "min": round(minimum, 6),
                "max": round(maximum, 6),
                "step": round(step, 6),
                "default": round(default, 6),
            },
            "controls": controls,
            "note": (
                f"拖动{moving_label}，观察辅助点{auxiliary_label}与等价路径同步变化。"
            ),
            "parameterized_points": {
                moving_ref: {
                    "expression": [parameter_name, "0"],
                    "source": {
                        "type": "weighted_axis_path_minimum",
                        "role": "moving_point",
                    },
                },
                auxiliary_ref: {
                    "expression": _format_pair(auxiliary),
                    "source": {
                        "type": "weighted_axis_path_minimum",
                        "role": "student_auxiliary_point",
                    },
                },
            },
        }

    def _square_axis_motion_interaction(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
    ) -> JsonObject | None:
        """Derive a square's moving vertex from verified semantic roles.

        The axis-side endpoint moves on the line through ``other_fixed``.  The
        square orientation is recovered from the verified current geometry;
        no problem id, student-facing point name or attainment value selects
        the formulas.  The local parameter is a normalized signed displacement
        along that axis, so its finite slider window is only a demonstration
        window while the mathematical domain remains real.
        """

        marker = _first_square_axis_motion_marker(bindings)
        if marker is None:
            return None
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        refs = (
            marker.get("role_point_refs")
            if isinstance(marker.get("role_point_refs"), dict)
            else {}
        )
        anchor_label = str(roles.get("side_start") or "")
        axis_label = str(roles.get("side_end") or "")
        moving_label = str(roles.get("moving_vertex") or "")
        fixed_label = str(roles.get("other_fixed") or "")
        midpoint_label = str(roles.get("midpoint") or "")
        center_label = str(roles.get("center") or "")
        anchor = str(refs.get(anchor_label) or "")
        axis_point = str(refs.get(axis_label) or "")
        moving = str(refs.get(moving_label) or "")
        fixed = str(refs.get(fixed_label) or "")
        midpoint = str(refs.get(midpoint_label) or "")
        center = str(refs.get(center_label) or "")
        square_vertices = tuple(
            str(item) for item in marker.get("square_outline") or () if str(item)
        )
        if not all((anchor, axis_point, moving, fixed)) or len(square_vertices) != 4:
            return None
        curve_ids = tuple(dict.fromkeys(str(item) for item in bindings.curve_ids if item))
        if len(curve_ids) != 1:
            raise ValueError(
                "visual_square_axis_motion_constraint_carrier_ambiguous: "
                f"{lesson_step.lesson_step_id}: {curve_ids!r}"
            )

        anchor_expr = self._point_expr(anchor)
        axis_expr = self._point_expr(axis_point)
        moving_expr = self._point_expr(moving)
        fixed_expr = self._point_expr(fixed)
        if None in (anchor_expr, axis_expr, moving_expr, fixed_expr):
            return None
        assert anchor_expr is not None
        assert axis_expr is not None
        assert moving_expr is not None
        assert fixed_expr is not None

        parameter_name = _fresh_local_parameter_name(self.geometry_spec)
        parameter = sp.Symbol(parameter_name)
        dynamic_axis = _axis_motion_point(
            anchor=anchor_expr,
            current=axis_expr,
            axis_foot=fixed_expr,
            parameter=parameter,
        )
        if dynamic_axis is None:
            return None
        orientation = _square_rotation_orientation(
            anchor=anchor_expr,
            adjacent=axis_expr,
            moving=moving_expr,
        )
        if orientation == 0:
            return None
        side = (
            sp.simplify(dynamic_axis[0] - anchor_expr[0]),
            sp.simplify(dynamic_axis[1] - anchor_expr[1]),
        )
        rotated = (
            (side[1], -side[0])
            if orientation < 0
            else (-side[1], side[0])
        )
        dynamic_moving = (
            sp.simplify(anchor_expr[0] + rotated[0]),
            sp.simplify(anchor_expr[1] + rotated[1]),
        )
        opposite_refs = tuple(
            ref
            for ref in square_vertices
            if ref not in {anchor, axis_point, moving}
        )
        if len(opposite_refs) != 1:
            return None
        opposite = opposite_refs[0]
        dynamic_opposite = (
            sp.simplify(dynamic_axis[0] + dynamic_moving[0] - anchor_expr[0]),
            sp.simplify(dynamic_axis[1] + dynamic_moving[1] - anchor_expr[1]),
        )
        parameterized_points: dict[str, JsonObject] = {
            axis_point: _interaction_point(dynamic_axis, "axis_side_endpoint"),
            moving: _interaction_point(dynamic_moving, "moving_square_vertex"),
            opposite: _interaction_point(dynamic_opposite, "opposite_square_vertex"),
        }
        if midpoint:
            parameterized_points[midpoint] = _interaction_point(
                _midpoint(anchor_expr, dynamic_axis),
                "side_midpoint",
            )
        if center:
            parameterized_points[center] = _interaction_point(
                _midpoint(dynamic_axis, dynamic_moving),
                "square_center",
            )

        return {
            "id": f"{lesson_step.id}:square_axis_motion",
            "component": "LocalSlider",
            "parameter": parameter_name,
            "mathematical_domain": {"kind": "real"},
            "domain": {
                "min": -1.25,
                "max": 1.25,
                "step": 0.01,
                "default": 0.35,
            },
            "controls": [
                {
                    "var": parameter_name,
                    "label": _square_motion_control_label(
                        moving=moving_label,
                        axis_point=axis_label,
                        axis_foot=fixed_label,
                        anchor=anchor_label,
                    ),
                    "min": -1.25,
                    "max": 1.25,
                    "step": 0.01,
                    "scale": 1,
                    "precision": 2,
                }
            ],
            "note": _square_motion_note(axis_point=axis_label, moving=moving_label),
            "parameterized_points": parameterized_points,
            # Internal visual-authority metadata.  The public local-parameter
            # contract intentionally does not serialize this field.
            "constraint_carriers": [
                {
                    "kind": "curve_axis",
                    "curve_id": curve_ids[0],
                }
            ],
        }

    def _equal_length_interaction(
        self,
        lesson_step: LessonStep,
        marker: JsonObject,
    ) -> JsonObject | None:
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
        anchor = _point_ref(roles, point_refs, "anchor")
        reference = _point_ref(roles, point_refs, "segment_reference_point")
        segment_moving = _point_ref(roles, point_refs, "segment_moving_point")
        ray_moving = _point_ref(roles, point_refs, "ray_moving_point")
        auxiliary = _point_ref(roles, point_refs, "auxiliary_point")
        fixed = _point_ref(roles, point_refs, "fixed_point")
        if not all((anchor, reference, segment_moving, ray_moving, auxiliary)):
            return None

        anchor_expr = self._point_expr(anchor)
        reference_expr = self._point_expr(reference)
        auxiliary_expr = self._point_expr(auxiliary)
        if anchor_expr is None or reference_expr is None or auxiliary_expr is None:
            return None

        u = sp.Symbol(self.local_parameter)
        segment_expr = _interpolate(anchor_expr, reference_expr, u)
        ray_expr = _interpolate(anchor_expr, auxiliary_expr, u)
        default_u = self._default_u(
            anchor=anchor,
            reference=reference,
            auxiliary=auxiliary,
            fixed=fixed,
        )
        substeps = set(lesson_step.visual_unit_ids)
        is_minimum = "minimum_by_segment" in substeps
        controls = [
            _control(
                var=self.local_parameter,
                label=_control_label(
                    roles,
                    moving_role="segment_moving_point",
                    anchor_role="anchor",
                    endpoint_role="segment_reference_point",
                ),
            )
        ]
        component = "LocalSlider"
        note = "拖动动点，观察单动点路径何时取最小值。"
        if not is_minimum:
            component = "LinkedControls"
            controls.append(
                _control(
                    var=self.local_parameter,
                    label=_control_label(
                        roles,
                        moving_role="ray_moving_point",
                        anchor_role="anchor",
                        endpoint_role="auxiliary_point",
                    ),
                )
            )
            note = "拖动线段上的动点，射线上的动点按等长条件联动。"
        return {
            "id": f"{lesson_step.id}:equal_length_local_slider",
            "component": component,
            "parameter": self.local_parameter,
            "mathematical_domain": {
                "kind": "closed_interval",
                "min": 0,
                "max": 1,
            },
            "domain": {
                "min": 0,
                "max": 1,
                "step": 0.01,
                "default": default_u,
            },
            "controls": controls,
            "note": note,
            "parameterized_points": {
                segment_moving: {
                    "expression": _format_pair(segment_expr),
                    "source": {
                        "type": "equal_length_ray_path_reduction",
                        "role": "segment_moving_point",
                        "anchor": anchor,
                        "endpoint": reference,
                    },
                },
                ray_moving: {
                    "expression": _format_pair(ray_expr),
                    "source": {
                        "type": "equal_length_ray_path_reduction",
                        "role": "ray_moving_point",
                        "anchor": anchor,
                        "endpoint": auxiliary,
                    },
                },
            },
            # The moving-point formulas own their exact geometric carriers.
            # Keeping these beside the interaction prevents a renderer from
            # showing a movable point after hiding the segment or ray that
            # defines its legal positions.
            "constraint_carriers": [
                {
                    "kind": "segment",
                    "moving_point": segment_moving,
                    "from": anchor,
                    "to": reference,
                },
                {
                    "kind": "ray",
                    "moving_point": ray_moving,
                    "from": anchor,
                    "to": auxiliary,
                },
            ],
        }

    def _point_expr(self, point_id: str) -> tuple[sp.Expr, sp.Expr] | None:
        pair = (self.geometry_spec.get("fixedPoints") or {}).get(point_id)
        if pair is None:
            pair = (self.geometry_spec.get("movingPoints") or {}).get(point_id)
        return _sympy_pair(pair)

    def _default_u(
        self,
        *,
        anchor: str,
        reference: str,
        auxiliary: str,
        fixed: str | None,
    ) -> float:
        if not fixed:
            return 0.5
        points = {
            "anchor": self._numeric_point(anchor),
            "reference": self._numeric_point(reference),
            "auxiliary": self._numeric_point(auxiliary),
            "fixed": self._numeric_point(fixed),
        }
        if any(value is None for value in points.values()):
            return 0.5
        anchor_pt = points["anchor"]
        reference_pt = points["reference"]
        auxiliary_pt = points["auxiliary"]
        fixed_pt = points["fixed"]
        assert anchor_pt is not None
        assert reference_pt is not None
        assert auxiliary_pt is not None
        assert fixed_pt is not None
        v = (reference_pt[0] - anchor_pt[0], reference_pt[1] - anchor_pt[1])
        w = (auxiliary_pt[0] - fixed_pt[0], auxiliary_pt[1] - fixed_pt[1])
        diff = (fixed_pt[0] - anchor_pt[0], fixed_pt[1] - anchor_pt[1])
        denom = _cross(v, w)
        if abs(denom) < 1e-9:
            return 0.5
        u_value = _cross(diff, w) / denom
        if not math.isfinite(u_value):
            return 0.5
        return round(max(0.0, min(1.0, u_value)), 6)

    def _numeric_point(self, point_id: str) -> tuple[float, float] | None:
        pair = self._point_expr(point_id)
        if pair is None:
            return None
        parameter_name = str(self.geometry_spec.get("movingParam") or "t")
        substitutions = {sp.Symbol(parameter_name): self.default_t}
        try:
            x = float(sp.N(pair[0].subs(substitutions)))
            y = float(sp.N(pair[1].subs(substitutions)))
        except Exception:
            return None
        if not math.isfinite(x) or not math.isfinite(y):
            return None
        return (x, y)


@dataclass(frozen=True)
class CandidateHitResolver:
    """Derive parameter landmarks from verified candidate-point results.

    A Method only opts into its ordinary candidate visual component.  This
    resolver discovers the parameter/candidate correspondence from public
    runtime values and exact geometry; no point letter, problem id, or answer
    value is authored in a visual spec.
    """

    geometry_spec: JsonObject

    def landmarks_for_parameter(
        self,
        *,
        lesson_step: LessonStep,
        snapshot: ExplanationSnapshot,
        parameter: str,
        parameterized_points: Mapping[str, Any],
        objects: tuple[VisualObject, ...],
        parameter_values: Mapping[str, str],
    ) -> tuple[JsonObject, ...]:
        if not parameter or not parameterized_points:
            return ()
        source_ids = set(lesson_step.source_step_ids)
        # Candidate semantics are discovered from the verified public values:
        # one parametric Point input plus one finite Point collection output.
        # A capability id, point label, problem id, or fixed answer must never
        # be the switch that enables this behavior.
        sources = tuple(
            source
            for source in iter_teaching_sources(snapshot.root_scope)
            if source.source_step_id in source_ids
        )
        if not sources:
            return ()

        visible_refs = {
            ref
            for item in objects
            for ref in item.geometry_refs
        }
        highlight_refs = tuple(
            sorted(str(ref) for ref in parameterized_points if str(ref) in visible_refs)
        )
        landmarks: list[JsonObject] = []
        for source in sources:
            projection = _candidate_parameter_projection(
                source,
                parameter=parameter,
                parameter_values=parameter_values,
            )
            for candidate_index, (candidate, exact_value) in enumerate(projection, start=1):
                numeric = _numeric_expr(exact_value)
                if numeric is None:
                    continue
                candidate_refs = _matching_candidate_geometry_refs(
                    self.geometry_spec,
                    candidate,
                    visible_refs=visible_refs,
                    candidate_index=candidate_index,
                )
                landmarks.append(
                    {
                        "value": numeric,
                        "exact_value": _page_expr(exact_value),
                        "display": _student_expr(exact_value),
                        "epsilon": 1e-6,
                        "candidate_geometry_refs": list(candidate_refs),
                        "highlight_geometry_refs": list(
                            dict.fromkeys((*highlight_refs, *candidate_refs))
                        ),
                    }
                )
        return tuple(landmarks)


def _first_equal_length_marker(bindings: VisualRoleBindings) -> JsonObject | None:
    for marker in bindings.equal_length_path_markers:
        if isinstance(marker, dict) and isinstance(marker.get("roles"), dict):
            return marker
    return None


def _first_square_axis_motion_marker(
    bindings: VisualRoleBindings,
) -> JsonObject | None:
    for marker in bindings.atomic_square_reduction_markers:
        if (
            isinstance(marker, dict)
            and isinstance(marker.get("roles"), dict)
            and isinstance(marker.get("role_point_refs"), dict)
        ):
            return marker
    return None


def _first_weighted_axis_motion_marker(
    bindings: VisualRoleBindings,
) -> JsonObject | None:
    for marker in bindings.atomic_path_minimum_markers:
        if (
            isinstance(marker, dict)
            and marker.get("construction_kind") == "weighted_right_triangle"
            and isinstance(marker.get("roles"), dict)
            and isinstance(marker.get("role_point_refs"), dict)
        ):
            return marker
    return None


def _first_coupled_segment_motion_marker(
    bindings: VisualRoleBindings,
) -> JsonObject | None:
    for marker in (
        *bindings.equal_length_path_markers,
        *bindings.atomic_path_minimum_markers,
    ):
        if (
            isinstance(marker, dict)
            and marker.get("construction_kind")
            in {None, "", "coupled_segment_endpoint_replacement"}
            and isinstance(marker.get("coupled_motion"), dict)
        ):
            return marker
    return None


def _constraint_domain_and_window(
    *,
    parameter_name: str,
    constraint: Mapping[str, Any],
    viewport_min: float,
    viewport_max: float,
    step: float,
) -> tuple[JsonObject, float, float, float] | None:
    """Intersect a finite demonstration window with verified math authority."""

    operator = str(constraint.get("operator") or "")
    try:
        bound_expression = sp.sympify(str(constraint.get("value")))
        if bound_expression.free_symbols:
            return None
        bound = float(sp.N(bound_expression))
    except (TypeError, ValueError, sp.SympifyError):
        return None
    if not math.isfinite(bound):
        return None
    span = max(viewport_max - viewport_min, 1.0)
    expression = f"{parameter_name}{operator}{sp.sstr(bound_expression)}"
    mathematical_domain: JsonObject = {
        "kind": "inequality",
        "expression": expression,
    }
    if operator in {">", ">="}:
        legal_start = bound + step if operator == ">" else bound
        minimum = max(viewport_min, legal_start)
        maximum = (
            viewport_max
            if viewport_max > minimum
            else minimum + span
        )
    elif operator in {"<", "<="}:
        legal_end = bound - step if operator == "<" else bound
        maximum = min(viewport_max, legal_end)
        minimum = (
            viewport_min
            if viewport_min < maximum
            else maximum - span
        )
    elif operator in {"=", "=="}:
        return (
            {"kind": "exact", "value": sp.sstr(bound_expression)},
            bound,
            bound,
            bound,
        )
    else:
        return None
    if not all(math.isfinite(item) for item in (minimum, maximum)):
        return None
    if maximum <= minimum:
        return None
    default = minimum + (maximum - minimum) / 2
    return mathematical_domain, minimum, maximum, default


def _axis_motion_point(
    *,
    anchor: tuple[sp.Expr, sp.Expr],
    current: tuple[sp.Expr, sp.Expr],
    axis_foot: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
) -> tuple[sp.Expr, sp.Expr] | None:
    """Parameterize the point on its verified axis without using its answer.

    For a vertical (respectively horizontal) axis, one side-scale from the
    anchor to the axis foot supplies a dimensionless demonstration parameter.
    The current point is used only to identify the axis direction.
    """

    dx = sp.simplify(current[0] - axis_foot[0])
    dy = sp.simplify(current[1] - axis_foot[1])
    if dx == 0 and dy != 0:
        scale = sp.simplify(axis_foot[0] - anchor[0])
        if scale == 0:
            scale = dy
        return (
            sp.simplify(axis_foot[0]),
            sp.simplify(axis_foot[1] + parameter * scale),
        )
    if dy == 0 and dx != 0:
        scale = sp.simplify(axis_foot[1] - anchor[1])
        if scale == 0:
            scale = dx
        return (
            sp.simplify(axis_foot[0] + parameter * scale),
            sp.simplify(axis_foot[1]),
        )
    return None


def _square_rotation_orientation(
    *,
    anchor: tuple[sp.Expr, sp.Expr],
    adjacent: tuple[sp.Expr, sp.Expr],
    moving: tuple[sp.Expr, sp.Expr],
) -> int:
    side = (
        sp.simplify(adjacent[0] - anchor[0]),
        sp.simplify(adjacent[1] - anchor[1]),
    )
    clockwise = (
        sp.simplify(anchor[0] + side[1]),
        sp.simplify(anchor[1] - side[0]),
    )
    counterclockwise = (
        sp.simplify(anchor[0] - side[1]),
        sp.simplify(anchor[1] + side[0]),
    )
    if _symbolic_pair_equal(moving, clockwise):
        return -1
    if _symbolic_pair_equal(moving, counterclockwise):
        return 1
    return 0


def _symbolic_pair_equal(
    left: tuple[sp.Expr, sp.Expr],
    right: tuple[sp.Expr, sp.Expr],
) -> bool:
    return all(sp.simplify(a - b) == 0 for a, b in zip(left, right, strict=True))


def _midpoint(
    left: tuple[sp.Expr, sp.Expr],
    right: tuple[sp.Expr, sp.Expr],
) -> tuple[sp.Expr, sp.Expr]:
    return (
        sp.simplify((left[0] + right[0]) / 2),
        sp.simplify((left[1] + right[1]) / 2),
    )


def _interaction_point(
    expression: tuple[sp.Expr, sp.Expr],
    role: str,
) -> JsonObject:
    return {
        "expression": _format_pair(expression),
        "source": {
            "type": "square_axis_motion",
            "role": role,
        },
    }


def _fresh_local_parameter_name(geometry_spec: Mapping[str, Any]) -> str:
    occupied: set[str] = {"x"}
    for collection in ("fixedPoints", "movingPoints"):
        for pair in (geometry_spec.get(collection) or {}).values():
            if not isinstance(pair, list | tuple):
                continue
            for expression in pair:
                try:
                    occupied.update(
                        str(symbol) for symbol in sp.sympify(expression).free_symbols
                    )
                except Exception:
                    continue
    for candidate in ("u", "v", "w", "s", "r"):
        if candidate not in occupied:
            return candidate
    index = 1
    while f"u{index}" in occupied:
        index += 1
    return f"u{index}"


def _square_motion_control_label(
    *,
    moving: str,
    axis_point: str,
    axis_foot: str,
    anchor: str,
) -> str:
    if all((moving, axis_point, axis_foot, anchor)):
        return f"动点 {moving}：{axis_foot}{axis_point}/{anchor}{axis_foot}"
    return f"动点 {moving}" if moving else "正方形动点"


def _square_motion_note(*, axis_point: str, moving: str) -> str:
    if axis_point and moving:
        return f"拖动 {axis_point}，观察正方形与动点 {moving} 的联动关系。"
    return "拖动轴上点，观察正方形动点的联动关系。"


def _unique_interactions(items: Sequence[JsonObject]) -> list[JsonObject]:
    result: list[JsonObject] = []
    by_id: dict[str, JsonObject] = {}
    for item in items:
        interaction_id = str(item.get("id") or "")
        previous = by_id.get(interaction_id)
        if previous is not None:
            if previous != item:
                raise ValueError(
                    f"visual_local_interaction_identity_conflict: {interaction_id}"
                )
            continue
        by_id[interaction_id] = item
        result.append(item)
    return result


def _point_ref(roles: dict[str, Any], point_refs: dict[str, Any], role: str) -> str | None:
    label = str(roles.get(role) or "")
    if not label:
        return None
    return str(point_refs.get(label) or label)


def _control(*, var: str, label: str) -> JsonObject:
    return {
        "var": var,
        "label": label,
        "min": 0,
        "max": 1,
        "step": 0.01,
        "scale": 1,
        "precision": 2,
    }


def _control_label(
    roles: dict[str, Any],
    *,
    moving_role: str,
    anchor_role: str,
    endpoint_role: str,
) -> str:
    moving = str(roles.get(moving_role) or "")
    anchor = str(roles.get(anchor_role) or "")
    endpoint = str(roles.get(endpoint_role) or "")
    if not moving or not anchor or not endpoint:
        return f"动点 {moving}" if moving else "动点参数"
    return f"动点 {moving}：{anchor}{moving}/{anchor}{endpoint}"


def _interpolate(
    start: tuple[sp.Expr, sp.Expr],
    end: tuple[sp.Expr, sp.Expr],
    parameter: sp.Symbol,
) -> tuple[sp.Expr, sp.Expr]:
    return (
        sp.simplify(start[0] + parameter * (end[0] - start[0])),
        sp.simplify(start[1] + parameter * (end[1] - start[1])),
    )


def _format_pair(pair: tuple[sp.Expr, sp.Expr]) -> list[str]:
    return [_page_expr(pair[0]), _page_expr(pair[1])]


def _is_pair(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= 2


def _axis_parameter_symbol(values: tuple[Any, ...]) -> str:
    for value in values:
        match = re.search(r"(?<![A-Za-z0-9_])_axis_param_[A-Za-z0-9_]+", str(value))
        if match:
            return match.group(0)
    return ""


def _pair_with_local_parameter(
    value: Any,
    parameter: str,
    local_parameter: str,
) -> tuple[sp.Expr, sp.Expr] | None:
    if not _is_pair(value) or not parameter:
        return None
    return _shared_sympy_pair(value, axis_parameter_alias=local_parameter)


def _solve_parameter_from_pair(
    value: Any,
    target_expr: tuple[sp.Expr, sp.Expr],
    parameter: str,
) -> sp.Expr | None:
    pair = _sympy_pair(value)
    if pair is None or not parameter:
        return None
    symbol = sp.Symbol(parameter)
    for source, target in zip(pair, target_expr, strict=True):
        if symbol not in source.free_symbols:
            continue
        try:
            solutions = sp.solve(sp.Eq(source, target), symbol)
        except Exception:
            solutions = []
        if solutions:
            return sp.simplify(solutions[0])
    return None


def _substitute_parameter_pair(
    value: Any,
    parameter: str,
    replacement: sp.Expr,
) -> tuple[sp.Expr, sp.Expr] | None:
    pair = _sympy_pair(value)
    if pair is None or not parameter:
        return None
    symbol = sp.Symbol(parameter)
    return (
        sp.simplify(pair[0].subs(symbol, replacement)),
        sp.simplify(pair[1].subs(symbol, replacement)),
    )


def _candidate_parameter_projection(
    source: TeachingSource,
    *,
    parameter: str,
    parameter_values: Mapping[str, str],
) -> tuple[tuple[tuple[sp.Expr, sp.Expr], sp.Expr], ...]:
    candidates = _candidate_output_pairs(source)
    if not candidates:
        return ()
    substitutions = {
        sp.Symbol(name): sp.sympify(str(value))
        for name, value in parameter_values.items()
        if name != parameter
    }
    mappings: list[tuple[tuple[sp.Expr, sp.Expr], tuple[sp.Expr, ...]]] = []
    for values in source.inputs.values():
        for item in values:
            pair = _sympy_pair(item.get("value")) if isinstance(item, Mapping) else None
            if pair is None or sp.Symbol(parameter) not in set().union(
                *(value.free_symbols for value in pair)
            ):
                continue
            prepared = tuple(sp.simplify(value.subs(substitutions)) for value in pair)
            solutions: list[sp.Expr] = []
            for candidate in candidates:
                solution = _unique_pair_parameter_solution(
                    prepared,
                    candidate,
                    parameter,
                )
                if solution is None:
                    break
                solutions.append(solution)
            if len(solutions) == len(candidates):
                mappings.append((prepared, tuple(solutions)))
    if len(mappings) != 1:
        return ()
    return tuple(zip(candidates, mappings[0][1], strict=True))


def _candidate_output_pairs(source: TeachingSource) -> tuple[tuple[sp.Expr, sp.Expr], ...]:
    collections: list[tuple[tuple[sp.Expr, sp.Expr], ...]] = []
    for output in source.outputs.values():
        value = output.get("value") if isinstance(output, Mapping) else None
        if not isinstance(value, (list, tuple)) or not value:
            continue
        pairs = tuple(pair for item in value if (pair := _sympy_pair(item)) is not None)
        if len(pairs) == len(value):
            collections.append(pairs)
    return collections[0] if len(collections) == 1 else ()


def _unique_pair_parameter_solution(
    source: tuple[sp.Expr, sp.Expr],
    target: tuple[sp.Expr, sp.Expr],
    parameter: str,
) -> sp.Expr | None:
    symbol = sp.Symbol(parameter)
    possible: set[sp.Expr] = set()
    for source_value, target_value in zip(source, target, strict=True):
        if symbol not in source_value.free_symbols:
            if sp.simplify(source_value - target_value) != 0:
                return None
            continue
        try:
            possible.update(
                sp.simplify(value)
                for value in sp.solve(sp.Eq(source_value, target_value), symbol)
            )
        except Exception:
            return None
    valid = [
        value
        for value in possible
        if all(
            sp.simplify(source_value.subs(symbol, value) - target_value) == 0
            for source_value, target_value in zip(source, target, strict=True)
        )
    ]
    return valid[0] if len(valid) == 1 else None


def _matching_candidate_geometry_refs(
    geometry_spec: JsonObject,
    candidate: tuple[sp.Expr, sp.Expr],
    *,
    visible_refs: set[str],
    candidate_index: int,
) -> tuple[str, ...]:
    result: list[str] = []
    point_meta = geometry_spec.get("pointMeta") or {}
    points = {
        **(geometry_spec.get("fixedPoints") or {}),
        **(geometry_spec.get("movingPoints") or {}),
    }
    for ref, raw in points.items():
        ref = str(ref)
        if ref not in visible_refs:
            continue
        meta = point_meta.get(ref) if isinstance(point_meta, dict) else None
        if not isinstance(meta, dict) or meta.get("candidateIndex") != candidate_index:
            continue
        pair = _sympy_pair(raw)
        if pair is None:
            continue
        if all(
            sp.simplify(observed - expected) == 0
            for observed, expected in zip(pair, candidate, strict=True)
        ):
            result.append(ref)
    return tuple(sorted(result))


def _numeric_expr(value: sp.Expr) -> float | None:
    if value.free_symbols:
        return None
    try:
        numeric = float(sp.N(value))
    except Exception:
        return None
    return numeric if math.isfinite(numeric) else None


def _student_expr(value: sp.Expr) -> str:
    text = _page_expr(value)
    return re.sub(r"sqrt\(([^()]+)\)", r"√\1", text)


def _sympy_pair(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    return _shared_sympy_pair(value)


def _page_expr(value: Any) -> str:
    text = str(value).strip()
    try:
        text = str(sp.simplify(sp.sympify(text, locals={"abs": sp.Abs, "sqrt": sp.sqrt})))
    except Exception:
        pass
    text = text.replace("Abs(", "abs(")
    text = text.replace(" ", "")
    return _expand_integer_powers(text)


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


def _cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]
