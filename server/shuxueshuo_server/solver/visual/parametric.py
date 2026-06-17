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


def _first_equal_length_marker(bindings: VisualRoleBindings) -> JsonObject | None:
    for marker in bindings.equal_length_path_markers:
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
    moving = str(roles.get(moving_role) or "P")
    anchor = str(roles.get(anchor_role) or "A")
    endpoint = str(roles.get(endpoint_role) or "B")
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


def _sympy_pair(value: Any) -> tuple[sp.Expr, sp.Expr] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    locals_ = {"abs": sp.Abs, "sqrt": sp.sqrt}
    try:
        return (
            sp.sympify(str(value[0]).replace("^", "**"), locals=locals_),
            sp.sympify(str(value[1]).replace("^", "**"), locals=locals_),
        )
    except Exception:
        return None


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
