"""Semantic, focus-driven viewport selection for complete visual frames.

Unbounded geometry is rendered *inside* the chosen viewport; it never grows
the viewport merely because a curve, axis, ray, or locus is present.  Finite
focus geometry and the structural context connected to it are the framing
authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import math

import sympy as sp

from .models import JsonObject, VisualObject


_UNBOUNDED_COMPONENTS = frozenset(
    {
        "AxisOfSymmetry",
        "LocusLine",
        "Parabola",
        "Ray",
    }
)


@dataclass(frozen=True)
class SemanticViewportResolver:
    """Fit a viewport around finite teaching focus, not registry extent."""

    minimum_span_x: float = 4.0
    minimum_span_y: float = 6.0
    padding_ratio: float = 0.18

    def resolve(
        self,
        *,
        objects: tuple[VisualObject, ...],
        geometry_spec: JsonObject,
        local_parameters: tuple[JsonObject, ...],
        parameter_values: Mapping[str, str],
    ) -> JsonObject:
        point_pairs = _point_pairs(geometry_spec)
        environments = _evaluation_environments(local_parameters, parameter_values)
        attention_refs = self.attention_geometry_refs(
            objects=objects,
            geometry_spec=geometry_spec,
            local_parameters=local_parameters,
        )
        samples = _evaluate_refs(attention_refs, point_pairs, environments)

        if not samples:
            fallback = geometry_spec.get("domain")
            if isinstance(fallback, dict) and {
                "minX",
                "maxX",
                "minY",
                "maxY",
            } <= set(fallback):
                return dict(fallback)
            return {"minX": -2.0, "maxX": 2.0, "minY": -2.0, "maxY": 2.0}

        return self._fit(samples)

    def attention_geometry_refs(
        self,
        *,
        objects: tuple[VisualObject, ...],
        geometry_spec: JsonObject,
        local_parameters: tuple[JsonObject, ...],
    ) -> set[str]:
        """Return finite geometry that is authoritative for scene framing."""

        point_pairs = _point_pairs(geometry_spec)
        visible_refs = {
            ref
            for item in objects
            for ref in item.geometry_refs
            if ref in point_pairs
        }
        finite_objects = tuple(
            item for item in objects if not _is_unbounded_visual(item)
        )
        focus_refs = {
            ref
            for item in finite_objects
            if item.state == "focus"
            for ref in item.geometry_refs
            if ref in point_pairs
        }
        parameterized_refs = {
            str(ref)
            for contract in local_parameters
            for ref in (contract.get("parameterized_points") or {})
            if str(ref) in point_pairs and str(ref) in visible_refs
        }
        attention_refs = set(focus_refs | parameterized_refs)

        # Bring in the rest of a finite construction (for example the fixed
        # vertex of a square) whenever one of its vertices is already part of
        # the focus.  This is a geometry-reference closure, never a label or
        # capability-name heuristic.
        changed = True
        while changed:
            changed = False
            for item in finite_objects:
                refs = {ref for ref in item.geometry_refs if ref in point_pairs}
                if not refs or not refs.intersection(attention_refs):
                    continue
                before = len(attention_refs)
                attention_refs.update(refs)
                changed = changed or len(attention_refs) != before

        if len(attention_refs) < 2:
            attention_refs.update(
                ref
                for item in finite_objects
                if item.state == "context"
                for ref in item.geometry_refs
                if ref in point_pairs
            )
        return attention_refs

    def _fit(self, samples: list[tuple[float, float]]) -> JsonObject:
        min_x = min(point[0] for point in samples)
        max_x = max(point[0] for point in samples)
        min_y = min(point[1] for point in samples)
        max_y = max(point[1] for point in samples)
        span_x = max(self.minimum_span_x, max_x - min_x)
        span_y = max(self.minimum_span_y, max_y - min_y)
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        half_x = span_x * (0.5 + self.padding_ratio)
        half_y = span_y * (0.5 + self.padding_ratio)
        return {
            "minX": round(center_x - half_x, 4),
            "maxX": round(center_x + half_x, 4),
            "minY": round(center_y - half_y, 4),
            "maxY": round(center_y + half_y, 4),
        }


def _is_unbounded_visual(item: VisualObject) -> bool:
    return item.component in _UNBOUNDED_COMPONENTS or item.role.startswith("locus:")


def _point_pairs(geometry_spec: JsonObject) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for collection in ("fixedPoints", "movingPoints"):
        for ref, raw in (geometry_spec.get(collection) or {}).items():
            if isinstance(raw, list) and len(raw) == 2:
                result[str(ref)] = (str(raw[0]), str(raw[1]))
    return result


def _evaluation_environments(
    local_parameters: tuple[JsonObject, ...],
    parameter_values: Mapping[str, str],
) -> list[dict[str, float]]:
    base: dict[str, float] = {}
    for name, value in parameter_values.items():
        numeric = _numeric(value)
        if numeric is not None:
            base[str(name)] = numeric
    for contract in local_parameters:
        name = str(contract.get("name") or "")
        numeric = _numeric(contract.get("default_value"))
        if name and numeric is not None:
            base[name] = numeric

    result = [dict(base)]
    for contract in local_parameters:
        name = str(contract.get("name") or "")
        if not name:
            continue
        landmarks = contract.get("landmarks") or ()
        sample_values = [item.get("value") for item in landmarks if isinstance(item, dict)]
        # An interactive moving-point construction must remain complete at
        # both ends of the control.  Render-only symbolic parameters have no
        # controls and are sampled only at their deterministic default.
        window = contract.get("display_window") or {}
        if contract.get("controls"):
            sample_values.extend((window.get("min"), window.get("max")))
        for value in sample_values:
            numeric = _numeric(value)
            if numeric is not None:
                result.append({**base, name: numeric})

    unique: list[dict[str, float]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    for environment in result:
        key = tuple(sorted(environment.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(environment)
    return unique


def _evaluate_refs(
    refs: set[str],
    point_pairs: Mapping[str, tuple[str, str]],
    environments: list[dict[str, float]],
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for ref in refs:
        pair = point_pairs.get(ref)
        if pair is None:
            continue
        for environment in environments:
            point = _evaluate_pair(pair, environment)
            if point is not None:
                result.append(point)
    return result


def _evaluate_pair(
    pair: tuple[str, str],
    environment: Mapping[str, float],
) -> tuple[float, float] | None:
    try:
        substitutions = {sp.Symbol(name): value for name, value in environment.items()}
        values = tuple(sp.sympify(value).subs(substitutions) for value in pair)
        if any(value.free_symbols for value in values):
            return None
        numeric = tuple(float(sp.N(value)) for value in values)
        if not all(math.isfinite(value) and abs(value) < 10_000 for value in numeric):
            return None
        return numeric[0], numeric[1]
    except Exception:
        return None


def _numeric(value: Any) -> float | None:
    try:
        numeric = float(sp.N(sp.sympify(str(value))))
        return numeric if math.isfinite(numeric) else None
    except Exception:
        return None


__all__ = ["SemanticViewportResolver"]
