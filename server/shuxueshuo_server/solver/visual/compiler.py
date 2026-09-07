"""Forward compiler for recursive complete-frame VisualStepIR v2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import copy

from .models import JsonObject, VisualFrame, VisualObject, VisualStep, VisualStepIR
from .palette import COLOR_MUTED
from .registry import low_level_for_visual_type


_CONTEXT_OPACITY = 0.58
_CONTEXT_REGION_FILL = "rgba(100, 116, 139, 0.08)"


@dataclass(frozen=True)
class CompiledVisualArtifacts:
    geometry_spec: JsonObject
    step_decorations: JsonObject
    lesson_data: JsonObject


def reverse_compile(
    geometry_spec: JsonObject,
    step_decorations: JsonObject,
    lesson_data: JsonObject,
) -> VisualStepIR:
    """The retired flat page artifacts are not a v2 authority."""

    raise ValueError("visual_step_ir_v1_reverse_compile_retired")


def forward_compile(visual_ir: VisualStepIR) -> CompiledVisualArtifacts:
    """Compile complete frames; no prior scene or DOM state is consulted."""

    if visual_ir.schema_version != "visual-step-ir/v2":
        raise ValueError("visual_step_ir_legacy_contract_rejected")
    lesson_data = copy.deepcopy(visual_ir.lesson_data)
    lesson_steps_by_id = {
        str(item.get("id")): item
        for item in lesson_data.get("steps") or ()
        if isinstance(item, dict) and item.get("id")
    }
    policies = lesson_data.setdefault("policies", {})
    steps: dict[str, Any] = {}
    for visual_step in visual_ir.steps:
        raw_step: dict[str, Any] = copy.deepcopy(visual_step.metadata.get("step_extra") or {})
        raw_step["visualMode"] = visual_step.visual_mode
        compiled_frames = [
            _compile_complete_frame(frame)
            for frame in visual_step.frames
        ]
        raw_step["visualFrames"] = compiled_frames
        _compile_frame_local_parameters(
            visual_step,
            lesson_step=lesson_steps_by_id.get(visual_step.lesson_step_id),
            policies=policies,
        )
        steps[visual_step.lesson_step_id] = raw_step

    step_decorations: dict[str, Any] = {}
    if visual_ir.metadata.get("step_decorations_comment") is not None:
        step_decorations["_comment"] = visual_ir.metadata.get("step_decorations_comment")
    step_decorations["steps"] = steps

    return CompiledVisualArtifacts(
        geometry_spec=copy.deepcopy(visual_ir.geometry_spec),
        step_decorations=step_decorations,
        lesson_data=lesson_data,
    )


def _compile_complete_frame(frame: VisualFrame) -> JsonObject:
    coordinate_labeled_points = frozenset(
        visual_object.geometry_refs[0]
        for visual_object in frame.objects
        if visual_object.component == "CoordinateLabel"
        and len(visual_object.geometry_refs) == 1
    )
    add = [{"type": "grid"}]
    add.extend(
        [
        compiled
        for visual_object in frame.objects
        for compiled in _compile_visual_object(
            visual_object,
            coordinate_labeled_points=coordinate_labeled_points,
        )
        ]
    )
    result: JsonObject = {
        "id": frame.frame_id,
        "caption": frame.caption or "",
        "teachingUnitKeys": list(frame.teaching_unit_keys),
        "domain": copy.deepcopy(frame.viewport),
        "add": _dedupe_compiled_items(add),
        "localValues": {
            str(parameter.get("name")): parameter.get("default_value")
            for parameter in frame.local_parameters
            if str(parameter.get("name") or "")
        },
        "pointOverrides": {},
        "curveOverrides": {},
    }
    parameter_landmarks: list[JsonObject] = []
    for parameter in frame.local_parameters:
        parameter_name = str(parameter.get("name") or "")
        parameter_landmarks.extend(
            {
                "parameter": parameter_name,
                "value": landmark["value"],
                "exactValue": landmark["exact_value"],
                "display": landmark["display"],
                "epsilon": landmark["epsilon"],
                "candidateGeometryRefs": copy.deepcopy(
                    landmark["candidate_geometry_refs"]
                ),
                "highlightGeometryRefs": copy.deepcopy(
                    landmark["highlight_geometry_refs"]
                ),
            }
            for landmark in parameter.get("landmarks") or ()
        )
        for point_id, payload in (parameter.get("parameterized_points") or {}).items():
            expression = payload.get("expression") if isinstance(payload, dict) else None
            if isinstance(expression, list) and len(expression) == 2:
                result["pointOverrides"][str(point_id)] = [str(expression[0]), str(expression[1])]
        name = str(parameter.get("name") or "")
        if not name:
            continue
        for visual_object in frame.objects:
            for curve_id in visual_object.geometry_refs:
                if not curve_id.startswith("curve_"):
                    continue
                result["curveOverrides"].setdefault(curve_id, {})["parameter"] = name
    if not result["pointOverrides"]:
        result.pop("pointOverrides")
    if not result["curveOverrides"]:
        result.pop("curveOverrides")
    if not result["localValues"]:
        result.pop("localValues")
    if parameter_landmarks:
        result["parameterLandmarks"] = parameter_landmarks
    if frame.timeline is not None:
        result["animation"] = _compiled_timeline(frame.timeline)
    return result


def _compile_visual_object(
    visual_object: VisualObject,
    *,
    coordinate_labeled_points: frozenset[str],
) -> list[JsonObject]:
    """Compile one object using resolved geometry identity, never label text.

    A point marker and a coordinate annotation are complementary renderings of
    the same mathematical point.  When the Frame contains both components for
    the exact same geometry ref, the marker remains visible but yields its
    short name to the more informative coordinate annotation.
    """

    scene_item = visual_object.to_scene_item()
    if (
        visual_object.component
        in {"Point", "DerivedPoint", "MovingPoint", "Vertex", "CurvePoint"}
        and len(visual_object.geometry_refs) == 1
        and visual_object.geometry_refs[0] in coordinate_labeled_points
    ):
        scene_item["showLabel"] = False
    return _compile_scene_items(scene_item)


def _compile_frame_local_parameters(
    visual_step: VisualStep,
    *,
    lesson_step: JsonObject | None,
    policies: JsonObject,
) -> None:
    if lesson_step is None:
        return
    by_name: dict[str, JsonObject] = {}
    for frame in visual_step.frames:
        for parameter in frame.local_parameters:
            name = str(parameter.get("name") or "")
            if name and parameter.get("controls") and name not in by_name:
                by_name[name] = parameter
    if not by_name:
        lesson_step.pop("localControls", None)
        return
    values = {
        name: parameter.get("default_value")
        for name, parameter in by_name.items()
    }
    controls: list[JsonObject] = []
    for parameter in by_name.values():
        landmarks = [
            {
                "value": landmark["value"],
                "display": landmark["display"],
                "epsilon": landmark["epsilon"],
            }
            for landmark in parameter.get("landmarks") or ()
        ]
        for control in parameter.get("controls") or ():
            if not isinstance(control, dict):
                continue
            compiled_control = copy.deepcopy(control)
            if landmarks:
                compiled_control["landmarks"] = copy.deepcopy(landmarks)
            controls.append(compiled_control)
    notes = [
        str(parameter.get("note") or "")
        for parameter in by_name.values()
        if str(parameter.get("note") or "")
    ]
    lesson_step["localControls"] = {
        "values": values,
        "controls": controls,
        "note": " ".join(dict.fromkeys(notes)),
    }
    policies[visual_step.lesson_step_id] = {
        "movable": False,
        "range": [lesson_step.get("t", 0), lesson_step.get("t", 0)],
    }


def _compiled_timeline(timeline: JsonObject) -> JsonObject:
    compiled = copy.deepcopy(timeline)
    beats: list[JsonObject] = []
    for beat in compiled.get("beats") or ():
        if not isinstance(beat, dict):
            continue
        patch = beat.get("scene_patch")
        if isinstance(patch, dict):
            patch["add"] = [
                raw
                for item in patch.get("add") or ()
                if isinstance(item, dict)
                for raw in _compile_scene_items(item)
            ]
        beats.append(beat)
    compiled.pop("frames", None)
    compiled["beats"] = beats
    return compiled


def _dedupe_compiled_items(items: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    result: list[JsonObject] = []
    for item in items:
        semantic = copy.deepcopy(item)
        if semantic.get("type") in {"coloredLine", "dashedLine", "segment"}:
            endpoints = sorted(
                [str(semantic.get("from") or ""), str(semantic.get("to") or "")]
            )
            key = f"line:{endpoints[0]}:{endpoints[1]}:{semantic.get('label') or ''}"
        else:
            key = repr(sorted(semantic.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _compile_scene_items(item: JsonObject) -> list[JsonObject]:
    raw = copy.deepcopy(item)
    metadata = raw.pop("metadata", {}) or {}
    component = str(raw.pop("component"))
    # Handles are VisualStepIR reconciliation keys. Existing step-decorations
    # low-level schema does not accept them, so they are consumed before emit.
    raw.pop("handle", None)
    visual_state = str(raw.pop("state", "focus"))
    raw.pop("persistence", None)
    raw.pop("decay_state", None)
    raw.pop("guide_only_refs", None)
    raw.pop("show_endpoint_refs", None)
    raw.pop("role", None)
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
    # A context distance marker keeps its mathematical segment available but
    # no longer repeats the relation being taught by an earlier focus frame.
    # This is driven by semantic component/state, never by label text.  When a
    # base line with the same endpoint identities is also present, the normal
    # endpoint-based compiled-item dedupe collapses the now-unlabelled marker.
    if component == "DistanceMarker" and visual_state == "context":
        for item in compiled:
            item.pop("label", None)
    return _apply_visual_state(compiled, visual_state)


def _apply_visual_state(
    compiled: list[JsonObject],
    visual_state: str,
) -> list[JsonObject]:
    """Translate the v2 semantic state into deterministic page styling.

    ``focus`` keeps the component's authored palette. ``context`` remains
    visible but is deliberately muted. Visibility itself is still determined
    exclusively by membership in the complete Frame object list.
    """

    if visual_state == "focus":
        return compiled
    if visual_state != "context":
        raise ValueError(f"visual_object_state_invalid: {visual_state}")

    for item in compiled:
        item_type = str(item.get("type") or "")
        if item_type == "grid":
            continue
        item["opacity"] = min(float(item.get("opacity", 1.0)), _CONTEXT_OPACITY)
        item["color"] = COLOR_MUTED
        if item_type in {"outlineRegion", "cutRegion"}:
            item["fill"] = _CONTEXT_REGION_FILL
        if "originColor" in item:
            item["originColor"] = COLOR_MUTED
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
