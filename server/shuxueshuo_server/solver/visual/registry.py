"""Registries used by VisualStepIR validation and VS0 compilation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComponentTypeSpec:
    """A VisualStepIR component and its low-level rendering targets."""

    visual_type: str
    compiles_to: tuple[str, ...]
    required_roles: tuple[str, ...] = ()
    optional_roles: tuple[str, ...] = ()
    children: tuple[dict[str, Any], ...] = ()


class ComponentTypeSpecRegistry:
    """Validate and look up component specs.

    The registry intentionally rejects duplicate visual_type registrations.
    VS0 registers the flat DistanceMarker fallback only; the future composition
    version is represented in docs, not in the default registry.
    """

    def __init__(self, specs: tuple[ComponentTypeSpec, ...] = ()) -> None:
        self._specs: dict[str, ComponentTypeSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ComponentTypeSpec) -> None:
        if spec.visual_type in self._specs:
            raise ValueError(f"duplicate visual component type: {spec.visual_type}")
        self._specs[spec.visual_type] = spec

    def get(self, visual_type: str) -> ComponentTypeSpec | None:
        return self._specs.get(visual_type)

    def require(self, visual_type: str) -> ComponentTypeSpec:
        spec = self.get(visual_type)
        if spec is None:
            raise KeyError(visual_type)
        return spec

    @property
    def visual_types(self) -> tuple[str, ...]:
        return tuple(self._specs)

    @property
    def low_level_types(self) -> set[str]:
        out: set[str] = set()
        for spec in self._specs.values():
            out.update(spec.compiles_to)
        return out


class LayerRegistry:
    """Mapping between semantic layer refs and existing step-decorations keys."""

    def __init__(self, semantic_to_layer: dict[str, str]) -> None:
        if "global" not in semantic_to_layer:
            raise ValueError("layer registry must define global")
        self.semantic_to_layer = dict(semantic_to_layer)
        self.layer_to_semantic = {value: key for key, value in semantic_to_layer.items()}

    def require_layer_key(self, semantic_ref: str) -> str:
        try:
            return self.semantic_to_layer[semantic_ref]
        except KeyError as exc:
            raise KeyError(f"unknown semantic layer ref: {semantic_ref}") from exc

    def semantic_for_layer_key(self, layer_key: str) -> str:
        return self.layer_to_semantic.get(layer_key, f"layer:{layer_key}")


LOW_LEVEL_TO_VISUAL_TYPE: dict[str, str] = {
    "angleArc": "AngleArc",
    "axisOfSymmetry": "AxisOfSymmetry",
    "basePoly": "BasePolygon",
    "coloredLine": "ColoredLine",
    "coordinateLabel": "CoordinateLabel",
    "curvePoint": "CurvePoint",
    "dashedLine": "DashedLine",
    "derivedPoint": "DerivedPoint",
    "grid": "Grid",
    "movingPoint": "MovingPoint",
    "outlineRegion": "OutlineRegion",
    "parabola": "Parabola",
    "point": "Point",
    "polygon": "Polygon",
    "ray": "Ray",
    "rightAngle": "RightAngle",
    "segment": "Segment",
    "vertex": "Vertex",
}

VISUAL_TYPE_TO_LOW_LEVEL: dict[str, str] = {
    visual_type: low_level for low_level, visual_type in LOW_LEVEL_TO_VISUAL_TYPE.items()
}


def visual_type_for_low_level(low_level_type: str) -> str:
    return LOW_LEVEL_TO_VISUAL_TYPE.get(
        low_level_type,
        "".join(part.capitalize() for part in low_level_type.replace("-", "_").split("_")),
    )


def low_level_for_visual_type(visual_type: str) -> str | None:
    return VISUAL_TYPE_TO_LOW_LEVEL.get(visual_type)


def default_component_registry() -> ComponentTypeSpecRegistry:
    specs = [
        ComponentTypeSpec(visual_type=visual_type, compiles_to=(low_level,))
        for low_level, visual_type in LOW_LEVEL_TO_VISUAL_TYPE.items()
    ]
    specs.extend(
        [
            ComponentTypeSpec(
                visual_type="DistanceMarker",
                compiles_to=("segment", "coordinateLabel"),
                required_roles=("from", "to"),
                optional_roles=("label",),
            ),
            ComponentTypeSpec(
                visual_type="VisualGap",
                compiles_to=("dashedLine", "coordinateLabel"),
                required_roles=("expected_role",),
                optional_roles=("reason",),
            ),
            ComponentTypeSpec(
                visual_type="TranslationMarker",
                compiles_to=("dashedLine", "coordinateLabel"),
                required_roles=("source", "target"),
                optional_roles=("vector", "label"),
            ),
            ComponentTypeSpec(
                visual_type="AngleEqualityMarker",
                compiles_to=("angleArc", "dashedLine"),
                required_roles=("angles",),
                optional_roles=("guide_arms", "label"),
            ),
            ComponentTypeSpec(
                visual_type="EqualAcuteAngleInterceptMarker",
                compiles_to=("outlineRegion", "coloredLine", "dashedLine", "angleArc", "rightAngle"),
                required_roles=(),
                optional_roles=("triangle_regions", "lines", "angles", "right_angles", "label"),
            ),
            ComponentTypeSpec(
                visual_type="CongruentTriangleMarker",
                compiles_to=("outlineRegion",),
                required_roles=("triangles",),
                optional_roles=("fill", "color"),
            ),
            ComponentTypeSpec(
                visual_type="EquivalentSegmentMarker",
                compiles_to=("coloredLine", "coordinateLabel"),
                required_roles=("segments",),
                optional_roles=("label",),
            ),
            ComponentTypeSpec(
                visual_type="PathMinimumTriangleMarker",
                compiles_to=("outlineRegion",),
                required_roles=("vertices",),
                optional_roles=("fill", "color"),
            ),
            ComponentTypeSpec(
                visual_type="SquareAdjacentVertexMarker",
                compiles_to=("outlineRegion", "coloredLine", "point", "coordinateLabel", "rightAngle"),
                required_roles=("vertices",),
                optional_roles=("target", "target_display", "vertex_displays", "coordinate_triangles"),
            ),
            ComponentTypeSpec(
                visual_type="SquarePathDimensionMarker",
                compiles_to=("outlineRegion", "coloredLine", "point", "rightAngle"),
                required_roles=("square_outline", "triangles", "segments"),
                optional_roles=("relations", "point_labels"),
            ),
            ComponentTypeSpec(
                visual_type="LocusLineMarker",
                compiles_to=("dashedLine", "coordinateLabel"),
                required_roles=("from", "to"),
                optional_roles=("label", "label_anchor", "label_dx", "label_dy"),
            ),
        ]
    )
    return ComponentTypeSpecRegistry(tuple(specs))


def default_layer_registry() -> LayerRegistry:
    return LayerRegistry(
        {
            "global": "global",
            "section:i": "partI",
            "section:ii": "partII",
        }
    )
