"""VS0 reverse/forward compiler for existing authored lesson JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import copy

from .models import JsonObject, VisualStep, VisualStepIR
from .registry import LayerRegistry, default_layer_registry, low_level_for_visual_type, visual_type_for_low_level
from .geometry_naming import scope_root
from .scene_accumulator import resolved_steps_with_carry_forward


@dataclass(frozen=True)
class CompiledVisualArtifacts:
    geometry_spec: JsonObject
    step_decorations: JsonObject
    lesson_data: JsonObject


def reverse_compile(
    geometry_spec: JsonObject,
    step_decorations: JsonObject,
    lesson_data: JsonObject,
    *,
    layer_registry: LayerRegistry | None = None,
) -> VisualStepIR:
    """Build a VisualStepIR from existing authored lesson artifacts."""

    registry = layer_registry or default_layer_registry()
    semantic_layers = _reverse_layers(step_decorations, registry)
    semantic_to_layer = dict(registry.semantic_to_layer)
    for semantic_ref in semantic_layers:
        if semantic_ref.startswith("layer:") and semantic_ref not in semantic_to_layer:
            semantic_to_layer[semantic_ref] = semantic_ref.removeprefix("layer:")
    lesson_steps = lesson_data.get("steps") or []
    lesson_order = [str(item["id"]) for item in lesson_steps if isinstance(item, dict) and item.get("id")]
    deco_steps = step_decorations.get("steps") or {}
    ordered_step_ids = [step_id for step_id in lesson_order if step_id in deco_steps]
    ordered_step_ids.extend(step_id for step_id in deco_steps if step_id not in ordered_step_ids)

    steps = tuple(
        _reverse_step(
            step_id,
            deco_steps.get(step_id) or {},
            geometry_spec,
            lesson_data,
            step_decorations,
            registry,
        )
        for step_id in ordered_step_ids
    )
    return VisualStepIR(
        version=1,
        problem_id=str((lesson_data.get("meta") or {}).get("id") or geometry_spec.get("id") or ""),
        geometry_spec=copy.deepcopy(geometry_spec),
        lesson_data=copy.deepcopy(lesson_data),
        layers=semantic_layers,
        layer_registry=semantic_to_layer,
        steps=steps,
        metadata={
            "source": "reverse_compile",
            "step_decorations_comment": step_decorations.get("_comment"),
        },
    )


def forward_compile(visual_ir: VisualStepIR) -> CompiledVisualArtifacts:
    """Compile VS0 VisualStepIR back to authored lesson JSON artifacts."""

    layer_registry = LayerRegistry(visual_ir.layer_registry or default_layer_registry().semantic_to_layer)
    layers: dict[str, Any] = {}
    for semantic_ref, layer in visual_ir.layers.items():
        layer_key = layer_registry.require_layer_key(semantic_ref)
        layers[layer_key] = copy.deepcopy(layer)

    visual_steps = visual_ir.steps
    use_scene_accumulator = visual_ir.metadata.get("scene_model") == "section_accumulator"
    if use_scene_accumulator:
        visual_steps = resolved_steps_with_carry_forward(visual_steps)

    lesson_data = copy.deepcopy(visual_ir.lesson_data)
    lesson_steps_by_id = {
        str(item.get("id")): item
        for item in lesson_data.get("steps") or ()
        if isinstance(item, dict) and item.get("id")
    }
    policies = lesson_data.setdefault("policies", {})
    steps: dict[str, Any] = {}
    carried_overrides_by_scope: dict[str, JsonObject] = {}
    carried_values_by_scope: dict[str, JsonObject] = {}
    for visual_step in visual_steps:
        scene = visual_step.scene or {}
        raw_step: dict[str, Any] = copy.deepcopy(visual_step.metadata.get("step_extra") or {})
        add = [
            compiled
            for item in scene.get("add") or ()
            for compiled in _compile_scene_items(item)
        ]
        if add:
            raw_step["add"] = add
        hide = scene.get("hide") or ()
        if hide:
            raw_step["hideLayers"] = list(hide)
        _compile_interactions(
            visual_step,
            raw_step=raw_step,
            lesson_step=lesson_steps_by_id.get(visual_step.lesson_step_id),
            policies=policies,
        )
        _compile_timeline(
            visual_step,
            lesson_step=lesson_steps_by_id.get(visual_step.lesson_step_id),
        )
        if use_scene_accumulator:
            scope_key = scope_root(visual_step.scope_id)
            _inherit_local_point_overrides_if_needed(
                visual_step,
                raw_step=raw_step,
                lesson_step=lesson_steps_by_id.get(visual_step.lesson_step_id),
                carried_overrides=carried_overrides_by_scope.get(scope_key, {}),
                carried_values=carried_values_by_scope.get(scope_key, {}),
            )
            if raw_step.get("pointOverrides"):
                carried_overrides_by_scope[scope_key] = copy.deepcopy(raw_step["pointOverrides"])
                local_controls = (lesson_steps_by_id.get(visual_step.lesson_step_id) or {}).get("localControls")
                if isinstance(local_controls, dict) and isinstance(local_controls.get("values"), dict):
                    carried_values_by_scope[scope_key] = copy.deepcopy(local_controls["values"])
        steps[visual_step.lesson_step_id] = raw_step

    step_decorations: dict[str, Any] = {}
    if visual_ir.metadata.get("step_decorations_comment") is not None:
        step_decorations["_comment"] = visual_ir.metadata.get("step_decorations_comment")
    step_decorations["layers"] = layers
    step_decorations["steps"] = steps

    return CompiledVisualArtifacts(
        geometry_spec=copy.deepcopy(visual_ir.geometry_spec),
        step_decorations=step_decorations,
        lesson_data=lesson_data,
    )


def _compile_interactions(
    visual_step: VisualStep,
    *,
    raw_step: JsonObject,
    lesson_step: JsonObject | None,
    policies: JsonObject,
) -> None:
    for interaction in visual_step.interactions or ():
        if not isinstance(interaction, dict):
            continue
        component = str(interaction.get("component") or "")
        if component in {"LocalSlider", "LinkedControls"}:
            _compile_local_slider_interaction(
                visual_step,
                interaction,
                raw_step=raw_step,
                lesson_step=lesson_step,
                policies=policies,
            )
        elif component == "MainSlider":
            raw_policy = interaction.get("raw_policy")
            if isinstance(raw_policy, dict):
                policies[visual_step.lesson_step_id] = copy.deepcopy(raw_policy)


def _compile_local_slider_interaction(
    visual_step: VisualStep,
    interaction: JsonObject,
    *,
    raw_step: JsonObject,
    lesson_step: JsonObject | None,
    policies: JsonObject,
) -> None:
    point_overrides = raw_step.setdefault("pointOverrides", {})
    for point_id, payload in (interaction.get("parameterized_points") or {}).items():
        if not isinstance(payload, dict):
            continue
        expression = payload.get("expression")
        if isinstance(expression, list) and len(expression) >= 2:
            point_overrides[str(point_id)] = [str(expression[0]), str(expression[1])]

    if lesson_step is None:
        return
    raw_local = interaction.get("raw_local_controls")
    if isinstance(raw_local, dict):
        lesson_step["localControls"] = copy.deepcopy(raw_local)
        return
    parameter = str(interaction.get("parameter") or "")
    domain = interaction.get("domain") if isinstance(interaction.get("domain"), dict) else {}
    default_value = domain.get("default", 0.5)
    controls = [
        copy.deepcopy(control)
        for control in interaction.get("controls") or ()
        if isinstance(control, dict)
    ]
    if not parameter or not controls:
        return
    lesson_step["localControls"] = {
        "values": {parameter: default_value},
        "note": str(interaction.get("note") or ""),
        "controls": controls,
    }
    policies[visual_step.lesson_step_id] = {
        "movable": False,
        "range": [lesson_step.get("t", 0), lesson_step.get("t", 0)],
    }


def _compile_timeline(
    visual_step: VisualStep,
    *,
    lesson_step: JsonObject | None,
) -> None:
    if lesson_step is None:
        return
    timeline = visual_step.timeline
    if not isinstance(timeline, dict) or timeline.get("mode", "none") == "none":
        lesson_step.pop("animation", None)
        return
    compiled = copy.deepcopy(timeline)
    beats: list[JsonObject] = []
    for beat in compiled.get("beats") or ():
        if not isinstance(beat, dict):
            continue
        patch = beat.get("scene_patch")
        if isinstance(patch, dict):
            patch["add"] = [
                raw_item
                for item in patch.get("add") or ()
                if isinstance(item, dict)
                for raw_item in _compile_scene_items(item)
            ]
            if "hide" in patch:
                patch["hide"] = [str(item) for item in patch.get("hide") or ()]
            if "state_overrides" in patch:
                patch["state_overrides"] = [
                    copy.deepcopy(item)
                    for item in patch.get("state_overrides") or ()
                    if isinstance(item, dict)
                ]
        beats.append(beat)
    compiled.pop("frames", None)
    compiled["beats"] = beats
    lesson_step["animation"] = compiled


def _inherit_local_point_overrides_if_needed(
    visual_step: VisualStep,
    *,
    raw_step: JsonObject,
    lesson_step: JsonObject | None,
    carried_overrides: JsonObject,
    carried_values: JsonObject,
) -> None:
    if raw_step.get("pointOverrides") or not carried_overrides:
        return
    refs = _geometry_refs_from_step(raw_step)
    if not refs.intersection(carried_overrides):
        return
    raw_step["pointOverrides"] = copy.deepcopy(carried_overrides)
    if lesson_step is not None and carried_values and "localControls" not in lesson_step:
        lesson_step["localControls"] = {
            "values": copy.deepcopy(carried_values),
            "controls": [],
        }


def _geometry_refs_from_step(raw_step: JsonObject) -> set[str]:
    refs: set[str] = set()
    for item in raw_step.get("add") or ():
        if isinstance(item, dict):
            refs.update(_geometry_refs_from_item(item))
    return refs


def _geometry_refs_from_item(item: JsonObject) -> set[str]:
    refs: set[str] = set()
    for key in ("at", "from", "to", "vertex", "rayA", "rayB", "anchor"):
        value = item.get(key)
        if isinstance(value, str):
            refs.add(value)
    if isinstance(item.get("vertices"), list):
        refs.update(str(value) for value in item["vertices"] if isinstance(value, str))
    for key in ("angles", "guide_arms", "lines", "right_angles", "segments", "triangles"):
        for nested in item.get(key) or ():
            if isinstance(nested, dict):
                refs.update(_geometry_refs_from_item(nested))
    return refs


def _reverse_layers(step_decorations: JsonObject, registry: LayerRegistry) -> dict[str, JsonObject]:
    out: dict[str, JsonObject] = {}
    for layer_key, layer in (step_decorations.get("layers") or {}).items():
        semantic_ref = registry.semantic_for_layer_key(str(layer_key))
        out[semantic_ref] = copy.deepcopy(layer)
    return out


def _reverse_step(
    step_id: str,
    step_deco: JsonObject,
    geometry_spec: JsonObject,
    lesson_data: JsonObject,
    step_decorations: JsonObject,
    registry: LayerRegistry,
) -> VisualStep:
    lesson_step = _lesson_step(lesson_data, step_id)
    inherits_from = _semantic_layer_for_step(step_id, step_decorations, registry)
    add = [_reverse_element(item) for item in step_deco.get("add") or ()]
    hide = list(step_deco.get("hideLayers") or ())
    scene = {
        "inherits_from": inherits_from,
        "add": add,
        "state_overrides": [],
        "hide": hide,
        "focus": {"primary": [], "dim": []},
        "annotations": [],
    }
    geometry_context = {
        "coordinate_system": "cartesian_2d",
        "domain": copy.deepcopy(geometry_spec.get("domain") or {}),
        "domain_override": copy.deepcopy(lesson_step.get("domain")) if isinstance(lesson_step, dict) else None,
        "moving_param": geometry_spec.get("movingParam"),
        "expression_env_handles": _expression_env_handles(geometry_spec.get("expressionEnv")),
        "panels": [],
    }
    interactions = tuple(_reverse_interactions(step_id, lesson_step, lesson_data))
    step_extra = {key: copy.deepcopy(value) for key, value in step_deco.items() if key not in {"add", "hideLayers"}}
    return VisualStep(
        visual_step_id=f"visual:{step_id}",
        lesson_step_id=step_id,
        scope_id=_scope_for_step(step_id, step_decorations, registry),
        geometry_context=geometry_context,
        scene=scene,
        interactions=interactions,
        timeline={"mode": "none"},
        metadata={"step_extra": step_extra},
    )


def _reverse_element(item: JsonObject) -> JsonObject:
    out = copy.deepcopy(item)
    low_level_type = str(out.pop("type", ""))
    out["component"] = visual_type_for_low_level(low_level_type)
    out.setdefault("metadata", {})
    out["metadata"]["low_level_type"] = low_level_type
    return out


def _compile_scene_items(item: JsonObject) -> list[JsonObject]:
    raw = copy.deepcopy(item)
    metadata = raw.pop("metadata", {}) or {}
    component = str(raw.pop("component"))
    # Handles are VisualStepIR reconciliation keys. Existing step-decorations
    # low-level schema does not accept them, so they are consumed before emit.
    raw.pop("handle", None)
    raw.pop("state", None)
    raw.pop("persistence", None)
    raw.pop("decay_state", None)
    raw.pop("guide_only_refs", None)
    raw.pop("show_endpoint_refs", None)
    if component == "VisualGap":
        return []
    compiled: list[JsonObject]
    if component == "DistanceMarker":
        compiled = [_compile_distance_marker(raw)]
    elif component == "TranslationMarker":
        compiled = _compile_translation_marker(raw)
    elif component == "AngleEqualityMarker":
        compiled = _compile_angle_equality_marker(raw)
    elif component == "EqualAcuteAngleInterceptMarker":
        compiled = _compile_equal_acute_angle_intercept_marker(raw)
    elif component == "CongruentTriangleMarker":
        compiled = _compile_congruent_triangle_marker(raw)
    elif component == "EquivalentSegmentMarker":
        compiled = _compile_equivalent_segment_marker(raw)
    else:
        low_level_type = metadata.get("low_level_type") or low_level_for_visual_type(component)
        if low_level_type is None:
            raise ValueError(f"cannot compile component without low-level type: {component}")
        raw["type"] = low_level_type
        compiled = [raw]
    return compiled


def _compile_distance_marker(raw: JsonObject) -> JsonObject:
    return {
        "type": "segment",
        "from": raw.get("from"),
        "to": raw.get("to"),
        "label": raw.get("label") or raw.get("text") or "",
        "color": raw.get("color"),
        "width": raw.get("width", 2.0),
        "offsetPx": raw.get("offsetPx", 16),
    }


def _compile_translation_marker(raw: JsonObject) -> list[JsonObject]:
    source = raw.get("source")
    target = raw.get("target")
    label = raw.get("label") or "v"
    return [
        {
            "type": "dashedLine",
            "from": source,
            "to": target,
            "color": raw.get("color"),
            "width": raw.get("width", 1.6),
            "dash": raw.get("dash", "5 5"),
        },
        {
            "type": "coordinateLabel",
            "at": target,
            "text": label,
            "dx": raw.get("dx", 16),
            "dy": raw.get("dy", -10),
        },
    ]


def _compile_angle_equality_marker(raw: JsonObject) -> list[JsonObject]:
    label = raw.get("label") or "α"
    color = raw.get("color")
    guide_color = raw.get("guideColor") or raw.get("guide_color") or color
    out: list[JsonObject] = []
    for guide in raw.get("guide_arms") or ():
        if not isinstance(guide, dict):
            continue
        line = {
            "type": "dashedLine",
            "from": guide.get("from"),
            "to": guide.get("to"),
            "color": guide.get("color") or guide_color,
            "width": guide.get("width", raw.get("guideWidth", 1.4)),
            "dash": guide.get("dash", raw.get("guideDash", "4 6")),
        }
        out.append(line)
    for angle in raw.get("angles") or ():
        if not isinstance(angle, dict):
            continue
        out.append(
            {
                "type": "angleArc",
                "vertex": angle.get("vertex"),
                "rayA": angle.get("rayA"),
                "rayB": angle.get("rayB"),
                "color": angle.get("color") or color,
                "radius": angle.get("radius", raw.get("radius", 34)),
                "label": angle.get("label") or label,
                "labelRadius": angle.get("labelRadius", raw.get("labelRadius", 48)),
            }
        )
    return out


def _compile_equal_acute_angle_intercept_marker(raw: JsonObject) -> list[JsonObject]:
    label = raw.get("label") or "α"
    color = raw.get("color")
    out: list[JsonObject] = []
    for region in raw.get("triangle_regions") or ():
        if not isinstance(region, dict):
            continue
        out.append(
            {
                "type": "outlineRegion",
                "vertices": list(region.get("vertices") or ()),
                "fill": region.get("fill"),
                "color": region.get("color"),
                "width": region.get("width", 1.0),
                "dash": region.get("dash", ""),
            }
        )
    for line in raw.get("lines") or ():
        if not isinstance(line, dict):
            continue
        line_type = "dashedLine" if line.get("style") == "dashed" else "coloredLine"
        item = {
            "type": line_type,
            "from": line.get("from"),
            "to": line.get("to"),
            "color": line.get("color"),
            "width": line.get("width", 1.6),
        }
        if line_type == "dashedLine":
            item["dash"] = line.get("dash", "4 7")
        out.append(item)
    for angle in raw.get("angles") or ():
        if not isinstance(angle, dict):
            continue
        out.append(
            {
                "type": "angleArc",
                "vertex": angle.get("vertex"),
                "rayA": angle.get("rayA"),
                "rayB": angle.get("rayB"),
                "color": angle.get("color") or color,
                "radius": angle.get("radius", raw.get("radius", 34)),
                "label": angle.get("label") or label,
                "labelRadius": angle.get("labelRadius", raw.get("labelRadius", 48)),
            }
        )
    for right_angle in raw.get("right_angles") or ():
        if not isinstance(right_angle, dict):
            continue
        out.append(
            {
                "type": "rightAngle",
                "vertex": right_angle.get("vertex"),
                "rayA": right_angle.get("rayA"),
                "rayB": right_angle.get("rayB"),
                "size": right_angle.get("size", raw.get("rightAngleSize", 10)),
                "color": right_angle.get("color") or raw.get("rightAngleColor"),
            }
        )
    return out


def _compile_congruent_triangle_marker(raw: JsonObject) -> list[JsonObject]:
    out: list[JsonObject] = []
    for triangle in raw.get("triangles") or ():
        if not isinstance(triangle, dict):
            continue
        out.append(
            {
                "type": "outlineRegion",
                "vertices": list(triangle.get("vertices") or ()),
                "fill": triangle.get("fill") or raw.get("fill"),
                "color": triangle.get("color") or raw.get("color"),
                "width": triangle.get("width", raw.get("width", 1.0)),
                "dash": triangle.get("dash", raw.get("dash", "")),
            }
        )
    return out


def _compile_equivalent_segment_marker(raw: JsonObject) -> list[JsonObject]:
    out: list[JsonObject] = []
    segments = [item for item in raw.get("segments") or () if isinstance(item, dict)]
    color = raw.get("color")
    width = raw.get("width", 2.2)
    offset_px = raw.get("offsetPx", 18)
    for index, segment in enumerate(segments):
        out.append(
            {
                "type": "coloredLine",
                "from": segment.get("from"),
                "to": segment.get("to"),
                "color": segment.get("color") or color,
                "width": segment.get("width", width),
            }
        )
        out.append(
            {
                "type": "segment",
                "from": segment.get("from"),
                "to": segment.get("to"),
                "label": segment.get("label") or raw.get("label") or "",
                "color": segment.get("color") or color,
                "width": raw.get("measureWidth", 1.6),
                "offsetPx": segment.get(
                    "offsetPx",
                    offset_px if index == 0 else -offset_px,
                ),
                "style": "dimension",
                "rotateWithLine": False,
                "extraNormal": 8,
            }
        )
    return out


def _reverse_interactions(step_id: str, lesson_step: JsonObject, lesson_data: JsonObject) -> list[JsonObject]:
    interactions: list[JsonObject] = []
    local_controls = lesson_step.get("localControls") if isinstance(lesson_step, dict) else None
    if local_controls:
        controls = local_controls.get("controls") or []
        vars_ = {control.get("var") for control in controls if isinstance(control, dict)}
        interactions.append(
            {
                "id": f"{step_id}:localControls",
                "component": "LinkedControls" if len(vars_) == 1 and len(controls) > 1 else "LocalSlider",
                "parameter": next(iter(vars_)) if len(vars_) == 1 else None,
                "raw_local_controls": copy.deepcopy(local_controls),
            }
        )
    policy = (lesson_data.get("policies") or {}).get(step_id)
    if policy and policy.get("movable"):
        interactions.append(
            {
                "id": f"{step_id}:mainSlider",
                "component": "MainSlider",
                "parameter": (lesson_data.get("ui") or {}).get("paramLabelPrefix") or "t",
                "raw_policy": copy.deepcopy(policy),
            }
        )
    return interactions


def _lesson_step(lesson_data: JsonObject, step_id: str) -> JsonObject:
    for item in lesson_data.get("steps") or ():
        if isinstance(item, dict) and item.get("id") == step_id:
            return item
    return {}


def _semantic_layer_for_step(step_id: str, step_decorations: JsonObject, registry: LayerRegistry) -> str:
    for layer_key, layer in (step_decorations.get("layers") or {}).items():
        step_ids = layer.get("stepIds") or ()
        if any(step_id == str(candidate) for candidate in step_ids):
            return registry.semantic_for_layer_key(str(layer_key))
    for layer_key, layer in (step_decorations.get("layers") or {}).items():
        prefixes = layer.get("stepStartsWith") or ()
        if any(step_id.startswith(str(prefix)) for prefix in prefixes):
            return registry.semantic_for_layer_key(str(layer_key))
    return "global"


def _scope_for_step(step_id: str, step_decorations: JsonObject, registry: LayerRegistry) -> str | None:
    semantic = _semantic_layer_for_step(step_id, step_decorations, registry)
    if semantic.startswith("section:"):
        return semantic.removeprefix("section:")
    return None


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
