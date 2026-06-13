"""VS0 reverse/forward compiler for existing authored lesson JSON."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import copy

from .models import JsonObject, VisualStep, VisualStepIR
from .registry import LayerRegistry, default_layer_registry, low_level_for_visual_type, visual_type_for_low_level


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

    steps: dict[str, Any] = {}
    for visual_step in visual_ir.steps:
        scene = visual_step.scene or {}
        raw_step: dict[str, Any] = copy.deepcopy(visual_step.metadata.get("step_extra") or {})
        add = [_compile_scene_item(item) for item in scene.get("add") or ()]
        if add:
            raw_step["add"] = add
        hide = scene.get("hide") or ()
        if hide:
            raw_step["hideLayers"] = list(hide)
        steps[visual_step.lesson_step_id] = raw_step

    step_decorations: dict[str, Any] = {}
    if visual_ir.metadata.get("step_decorations_comment") is not None:
        step_decorations["_comment"] = visual_ir.metadata.get("step_decorations_comment")
    step_decorations["layers"] = layers
    step_decorations["steps"] = steps

    return CompiledVisualArtifacts(
        geometry_spec=copy.deepcopy(visual_ir.geometry_spec),
        step_decorations=step_decorations,
        lesson_data=copy.deepcopy(visual_ir.lesson_data),
    )


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


def _compile_scene_item(item: JsonObject) -> JsonObject:
    raw = copy.deepcopy(item)
    metadata = raw.pop("metadata", {}) or {}
    component = str(raw.pop("component"))
    low_level_type = metadata.get("low_level_type") or low_level_for_visual_type(component)
    if low_level_type is None:
        raise ValueError(f"cannot compile component without low-level type: {component}")
    raw["type"] = low_level_type
    return raw


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
