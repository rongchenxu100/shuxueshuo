"""Local interaction parameterization for VisualStepIR VS2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import re

import sympy as sp

from shuxueshuo_server.solver.explanation.models import LessonStep

from .models import JsonObject
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
    ) -> tuple[JsonObject, ...]:
        axis_locus = self._axis_square_locus_interaction(lesson_step, bindings)
        if axis_locus:
            return (axis_locus,)
        broken_path = self._broken_path_interaction(lesson_step, bindings)
        if broken_path:
            return (broken_path,)
        if "equal_length_ray_path_reduction" not in lesson_step.capability_ids:
            return ()
        marker = _first_equal_length_marker(bindings)
        if marker is None:
            return ()
        interaction = self._equal_length_interaction(lesson_step, marker)
        return (interaction,) if interaction else ()

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
        substeps = set(lesson_step.teaching_substep_ids)
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
        }

    def _axis_square_locus_interaction(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
    ) -> JsonObject | None:
        if "parameterized_point_locus_line" not in lesson_step.capability_ids:
            return None
        axis_marker = next(
            (item for item in bindings.axis_parameterized_points if isinstance(item, dict)),
            None,
        )
        square_marker = next(
            (item for item in bindings.square_adjacent_markers if isinstance(item, dict)),
            None,
        )
        locus_marker = next(
            (item for item in bindings.locus_lines if isinstance(item, dict)),
            None,
        )
        if axis_marker is None or square_marker is None or locus_marker is None:
            return None
        axis_point = str(axis_marker.get("point") or "")
        target_point = str(square_marker.get("target") or "")
        if not axis_point or not target_point:
            return None
        axis_value = axis_marker.get("value")
        target_value = square_marker.get("target_value")
        if not _is_pair(axis_value) or not _is_pair(target_value):
            return None
        parameter = _axis_parameter_symbol((*axis_value, *target_value))
        if not parameter:
            return None

        axis_expr = _pair_with_local_parameter(axis_value, parameter, self.local_parameter)
        target_expr = _pair_with_local_parameter(target_value, parameter, self.local_parameter)
        if axis_expr is None or target_expr is None:
            return None
        default_value = self._axis_parameter_default(axis_point, axis_value, parameter)
        domain = self._axis_parameter_domain(default_value)
        point_overrides: dict[str, JsonObject] = {
            axis_point: {
                "expression": _format_pair(axis_expr),
                "source": {
                    "type": "quadratic_axis_parameterized_point",
                    "role": "axis_parameter_point",
                    "parameter": parameter,
                },
            },
            target_point: {
                "expression": _format_pair(target_expr),
                "source": {
                    "type": "parameterized_point_locus_line",
                    "role": "locus_moving_point",
                    "parameter": parameter,
                },
            },
        }
        opposite = self._square_opposite_override(
            square_marker=square_marker,
            axis_label=str(axis_marker.get("label") or ""),
            axis_expr=axis_expr,
            target_expr=target_expr,
        )
        if opposite is not None:
            opposite_point, opposite_expr = opposite
            point_overrides[opposite_point] = {
                "expression": _format_pair(opposite_expr),
                "source": {
                    "type": "square_adjacent_vertex_from_side",
                    "role": "opposite_square_vertex",
                    "parameter": parameter,
                },
            }
        point_overrides.update(
            self._square_projection_overrides(
                square_marker=square_marker,
                point_overrides=point_overrides,
            )
        )
        target_label = str(locus_marker.get("label") or square_marker.get("target_label") or "")
        display_parameter = "t" if parameter.startswith("_axis_param_") else parameter
        target_text = f"动点 {target_label}" if target_label else "动点"
        return {
            "id": f"{lesson_step.id}:locus_local_slider",
            "component": "LocalSlider",
            "parameter": self.local_parameter,
            "domain": domain,
            "controls": [
                {
                    "var": self.local_parameter,
                    "label": f"{target_text}：参数 {display_parameter}",
                    "min": domain["min"],
                    "max": domain["max"],
                    "step": domain["step"],
                    "scale": 1,
                    "precision": 2,
                }
            ],
            "note": f"拖动参数，观察 {target_text} 始终在同一条轨迹直线上。",
            "parameterized_points": point_overrides,
        }

    def _broken_path_interaction(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
    ) -> JsonObject | None:
        if "broken_path_straightening_minimum_expression" not in lesson_step.capability_ids:
            return None
        marker = _first_broken_path_marker(bindings)
        if marker is None:
            return None
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
        moving = _point_ref(roles, point_refs, "moving_point")
        reflected = _point_ref(roles, point_refs, "reflected_point")
        other = _point_ref(roles, point_refs, "other_fixed_point")
        if not all((moving, reflected, other)):
            return None
        locus = marker.get("locus_line") if isinstance(marker.get("locus_line"), dict) else {}
        locus_start = str(locus.get("from") or "")
        locus_end = str(locus.get("to") or "")
        if not locus_start or not locus_end:
            return None
        start_expr = self._point_expr(locus_start)
        end_expr = self._point_expr(locus_end)
        if start_expr is None or end_expr is None:
            return None
        u = sp.Symbol(self.local_parameter)
        moving_expr = _interpolate(start_expr, end_expr, u)
        point_overrides: dict[str, JsonObject] = {
            moving: {
                "expression": _format_pair(moving_expr),
                "source": {
                    "type": "broken_path_straightening_minimum_expression",
                    "role": "moving_point",
                    "locus_start": locus_start,
                    "locus_end": locus_end,
                },
            },
        }
        point_overrides.update(
            self._linked_square_point_overrides(
                marker=marker,
                moving_ref=moving,
                moving_expr=moving_expr,
            )
        )
        default_u = self._default_u_on_locus_between_segment(
            locus_start=locus_start,
            locus_end=locus_end,
            segment_start=reflected,
            segment_end=other,
        )
        moving_label = str(roles.get("moving_point") or "")
        moving_text = f"动点 {moving_label}" if moving_label else "动点"
        locus_label = str(locus.get("label") or marker.get("moving_locus") or "轨迹线")
        return {
            "id": f"{lesson_step.id}:broken_path_local_slider",
            "component": "LocalSlider",
            "parameter": self.local_parameter,
            "domain": {
                "min": 0,
                "max": 1,
                "step": 0.01,
                "default": default_u,
            },
            "controls": [
                _control(
                    var=self.local_parameter,
                    label=f"{moving_text}：沿 {locus_label}",
                )
            ],
            "note": "拖动动点，观察折线路径何时拉直取最小值。",
            "parameterized_points": point_overrides,
        }

    def _linked_square_point_overrides(
        self,
        *,
        marker: JsonObject,
        moving_ref: str,
        moving_expr: tuple[sp.Expr, sp.Expr],
    ) -> dict[str, JsonObject]:
        square_marker = marker.get("linked_square") if isinstance(marker.get("linked_square"), dict) else {}
        if not square_marker:
            return {}
        target_value = square_marker.get("target_value")
        axis_value = square_marker.get("axis_value")
        parameter = _axis_parameter_symbol((*axis_value, *target_value)) if _is_pair(axis_value) and _is_pair(target_value) else ""
        if not parameter:
            return {}
        parameter_expr = _solve_parameter_from_pair(target_value, moving_expr, parameter)
        if parameter_expr is None:
            return {}
        axis_expr = _substitute_parameter_pair(axis_value, parameter, parameter_expr)
        if axis_expr is None:
            return {}

        out: dict[str, JsonObject] = {}
        axis_point = str(square_marker.get("axis") or "")
        if axis_point and axis_point != moving_ref:
            out[axis_point] = {
                "expression": _format_pair(axis_expr),
                "source": {
                    "type": "square_adjacent_vertex_from_side",
                    "role": "linked_axis_vertex",
                    "parameter": parameter,
                },
            }
        opposite = self._square_opposite_override(
            square_marker=square_marker,
            axis_label=str(square_marker.get("axis_label") or ""),
            axis_expr=axis_expr,
            target_expr=moving_expr,
        )
        if opposite is not None:
            opposite_point, opposite_expr = opposite
            if opposite_point and opposite_point != moving_ref:
                out[opposite_point] = {
                    "expression": _format_pair(opposite_expr),
                    "source": {
                        "type": "square_adjacent_vertex_from_side",
                        "role": "linked_opposite_vertex",
                        "parameter": parameter,
                    },
                }
        return out

    def _square_opposite_override(
        self,
        *,
        square_marker: JsonObject,
        axis_label: str,
        axis_expr: tuple[sp.Expr, sp.Expr],
        target_expr: tuple[sp.Expr, sp.Expr],
    ) -> tuple[str, tuple[sp.Expr, sp.Expr]] | None:
        labels = [str(item) for item in square_marker.get("labels") or ()]
        vertices = [str(item) for item in square_marker.get("vertices") or ()]
        target_label = str(square_marker.get("target_label") or "")
        if len(labels) != 4 or len(vertices) != 4 or not axis_label or not target_label:
            return None
        if axis_label not in labels or target_label not in labels:
            return None
        axis_index = labels.index(axis_label)
        target_index = labels.index(target_label)
        base_index = (axis_index - 1) % 4
        if labels[(target_index + 1) % 4] != labels[base_index]:
            candidate = (axis_index + 1) % 4
            if labels[(target_index - 1) % 4] == labels[candidate]:
                base_index = candidate
            else:
                return None
        opposite_indices = [
            index
            for index in range(4)
            if index not in {axis_index, target_index, base_index}
        ]
        if len(opposite_indices) != 1:
            return None
        opposite_point = vertices[opposite_indices[0]]
        base_expr = self._point_expr(vertices[base_index])
        if base_expr is None:
            return None
        return (
            opposite_point,
            (
                sp.simplify(axis_expr[0] + target_expr[0] - base_expr[0]),
                sp.simplify(axis_expr[1] + target_expr[1] - base_expr[1]),
            ),
        )

    def _square_projection_overrides(
        self,
        *,
        square_marker: JsonObject,
        point_overrides: dict[str, JsonObject],
    ) -> dict[str, JsonObject]:
        expressions_by_point: dict[str, tuple[sp.Expr, sp.Expr]] = {}
        for point_id, payload in point_overrides.items():
            if not isinstance(payload, dict):
                continue
            pair = _sympy_pair(payload.get("expression"))
            if pair is not None:
                expressions_by_point[str(point_id)] = pair

        out: dict[str, JsonObject] = {}
        for raw in square_marker.get("coordinate_triangles") or ():
            if not isinstance(raw, dict):
                continue
            projection = str(raw.get("projection") or "")
            projection_target = str(raw.get("projection_target") or "")
            vertices = [str(item) for item in raw.get("vertices") or () if item]
            if not projection or not projection_target or projection in point_overrides:
                continue
            if len(vertices) < 3 or vertices[2] != projection:
                continue
            base_expr = expressions_by_point.get(vertices[0]) or self._point_expr(vertices[0])
            target_expr = expressions_by_point.get(projection_target)
            if base_expr is None or target_expr is None:
                continue
            out[projection] = {
                "expression": _format_pair((target_expr[0], base_expr[1])),
                "source": {
                    "type": "square_adjacent_vertex_from_side",
                    "role": "coordinate_projection",
                    "target": projection_target,
                },
            }
        return out

    def _axis_parameter_default(
        self,
        point_id: str,
        value: Any,
        parameter: str,
    ) -> float:
        pair = self._point_expr(point_id)
        if pair is None or not _is_pair(value):
            return 0.5
        for index, raw in enumerate(value[:2]):
            if parameter in str(raw):
                try:
                    parameter_name = str(self.geometry_spec.get("movingParam") or "t")
                    substitutions = {sp.Symbol(parameter_name): self.default_t}
                    return round(float(sp.N(pair[index].subs(substitutions))), 6)
                except Exception:
                    return 0.5
        return 0.5

    def _axis_parameter_domain(self, default_value: float) -> JsonObject:
        if not math.isfinite(default_value):
            default_value = 0.5
        minimum = round(default_value - 2.0, 6)
        maximum = round(default_value + 2.0, 6)
        return {
            "min": minimum,
            "max": maximum,
            "step": 0.01,
            "default": round(default_value, 6),
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

    def _default_u_on_locus_between_segment(
        self,
        *,
        locus_start: str,
        locus_end: str,
        segment_start: str,
        segment_end: str,
    ) -> float:
        points = {
            "locus_start": self._numeric_point(locus_start),
            "locus_end": self._numeric_point(locus_end),
            "segment_start": self._numeric_point(segment_start),
            "segment_end": self._numeric_point(segment_end),
        }
        if any(value is None for value in points.values()):
            return 0.5
        locus_start_pt = points["locus_start"]
        locus_end_pt = points["locus_end"]
        segment_start_pt = points["segment_start"]
        segment_end_pt = points["segment_end"]
        assert locus_start_pt is not None
        assert locus_end_pt is not None
        assert segment_start_pt is not None
        assert segment_end_pt is not None
        v = (
            locus_end_pt[0] - locus_start_pt[0],
            locus_end_pt[1] - locus_start_pt[1],
        )
        w = (
            segment_end_pt[0] - segment_start_pt[0],
            segment_end_pt[1] - segment_start_pt[1],
        )
        diff = (
            segment_start_pt[0] - locus_start_pt[0],
            segment_start_pt[1] - locus_start_pt[1],
        )
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


def _first_equal_length_marker(bindings: VisualRoleBindings) -> JsonObject | None:
    for marker in bindings.equal_length_path_markers:
        if isinstance(marker, dict) and isinstance(marker.get("roles"), dict):
            return marker
    return None


def _first_broken_path_marker(bindings: VisualRoleBindings) -> JsonObject | None:
    for marker in bindings.broken_path_minimum_markers:
        if isinstance(marker, dict) and isinstance(marker.get("roles"), dict):
            return marker
    return None


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
