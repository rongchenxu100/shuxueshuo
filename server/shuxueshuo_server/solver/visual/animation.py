"""Animation timeline generation for VisualStepIR VS3."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from shuxueshuo_server.solver.explanation.models import LessonStep
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry

from .models import JsonObject
from .palette import (
    COLOR_ACCENT,
    COLOR_CONGRUENT_REGION_FILL,
    COLOR_CONGRUENT_REGION_STROKE,
    COLOR_CONSTRAINT,
    COLOR_MUTED,
    COLOR_PATH,
    COLOR_RESULT_REGION_FILL_EMPHASIS,
    COLOR_RESULT_REGION_STROKE_SOFT,
    COLOR_RESULT,
)
from .role_binders import VisualRoleBindings


@dataclass(frozen=True)
class AnimationTimelineBuilder:
    """Build deterministic, role-bound animation timelines for supported steps."""

    def timeline_for_step(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
        *,
        interactions: tuple[JsonObject, ...] = (),
    ) -> JsonObject:
        beats: list[JsonObject] = []
        beats.extend(self._method_beats(lesson_step, bindings))
        beats.extend(self._recipe_beats(lesson_step, bindings, interactions=interactions))
        if not beats:
            return {"mode": "none"}
        return {
            "mode": "manual_then_interactive",
            "trigger": {"label": "播放演示"},
            "beats": beats,
            "on_complete": {"enable_interactions": bool(interactions)},
        }

    def _method_beats(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
    ) -> list[JsonObject]:
        beats: list[JsonObject] = []
        for capability_id in lesson_step.capability_ids:
            visual = _method_visual(capability_id)
            if visual is None:
                continue
            for template in visual.timeline_templates:
                if template.get("component") == "TranslationAnimation":
                    beats.extend(_translation_beats(lesson_step, bindings))
        return beats

    def _recipe_beats(
        self,
        lesson_step: LessonStep,
        bindings: VisualRoleBindings,
        *,
        interactions: tuple[JsonObject, ...],
    ) -> list[JsonObject]:
        beats: list[JsonObject] = []
        substeps = tuple(lesson_step.teaching_substep_ids)
        for capability_id in lesson_step.capability_ids:
            recipe = _recipe_spec(capability_id)
            visual = recipe.visual if recipe is not None else None
            if visual is None:
                continue
            for substep_id in substeps:
                for template in visual.teaching_substep_timeline_templates.get(substep_id, ()):
                    component = template.get("component")
                    if component == "EqualLengthPointConstruction":
                        beats.extend(_equal_length_point_construction_beats(lesson_step, bindings, interactions))
                    elif component == "CongruentTriangleReveal":
                        beats.extend(_congruent_triangle_reveal_beats(lesson_step, bindings, interactions))
                    elif component == "EquivalentSegmentEmphasis":
                        beats.extend(_equivalent_segment_emphasis_beats(lesson_step, bindings, interactions))
                    elif component == "PathReplacementReveal":
                        beats.extend(_path_replacement_reveal_beats(lesson_step, bindings, interactions))
                    elif component == "MovingPointSweepToMinimum":
                        beats.extend(_moving_point_sweep_to_minimum_beats(lesson_step, bindings, interactions))
                    elif component == "MinimumSegmentReveal":
                        beats.extend(_minimum_segment_reveal_beats(lesson_step, bindings, interactions))
        _keep_only_first_replace_add(beats)
        return beats


def _translation_beats(lesson_step: LessonStep, bindings: VisualRoleBindings) -> list[JsonObject]:
    beats: list[JsonObject] = []
    for index, marker in enumerate(bindings.translation_markers):
        source = str(marker.get("source_point") or "")
        target = str(marker.get("target_point") or "")
        vector = marker.get("vector")
        if not source or not target:
            continue
        label = _translation_label(vector)
        source_display = str(marker.get("source_display") or "") or _point_display(source, lesson_step)
        target_display = str(marker.get("target_display") or "") or _point_display(target, lesson_step)
        beats.extend(
            [
                _beat(
                    lesson_step,
                    f"translation-{index}-source",
                    source_display,
                    [["∵", source_display]],
                    [_point(source, color=COLOR_CONSTRAINT)],
                    transition_type="fade",
                ),
                _beat(
                    lesson_step,
                    f"translation-{index}-move",
                    f"{_point_label(source)} → {_point_label(target)}",
                    [["∵", f"{_point_label(target)} 是 {_point_label(source)} 平移 {label} 得到"]],
                    [
                        _point(source, color=COLOR_CONSTRAINT),
                        {
                            "component": "TranslationMarker",
                            "source": source,
                            "target": target,
                            "vector": list(vector) if isinstance(vector, list) else [],
                            "label": label,
                            "color": COLOR_CONSTRAINT,
                            "width": 1.8,
                            "dash": "5 5",
                        },
                        {
                            "component": "MovingPoint",
                            "from": source,
                            "to": target,
                            "labelText": "",
                            "showLabel": False,
                            "color": COLOR_RESULT,
                            "r": 6.2,
                        },
                    ],
                    transition_type="tween",
                ),
                _beat(
                    lesson_step,
                    f"translation-{index}-target",
                    target_display,
                    [["∴", target_display]],
                    [
                        _point(source, color=COLOR_CONSTRAINT),
                        _point(target, color=COLOR_RESULT),
                        {
                            "component": "TranslationMarker",
                            "source": source,
                            "target": target,
                            "vector": list(vector) if isinstance(vector, list) else [],
                            "label": label,
                            "color": COLOR_CONSTRAINT,
                            "width": 1.8,
                            "dash": "5 5",
                        },
                    ],
                    transition_type="fade_draw",
                ),
            ]
        )
    return beats


def _equal_length_point_construction_beats(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    marker = _first_equal_length_marker(bindings)
    if marker is None:
        return []
    auxiliary = _point_for_role(marker, "auxiliary_point")
    if not auxiliary:
        return []
    u_default = _u_default(interactions)
    extension_lines = _construction_extension_lines(marker)
    equal_segments, equality_label = _construction_equal_segments(marker)
    context = _moving_context_items(marker, include_auxiliary=False)
    with_auxiliary = _moving_context_items(marker, include_auxiliary=True)
    return [
        _beat(
            lesson_step,
            "equal-length-extend-carrier",
            "extend carrier",
            [["作", _carrier_line_text(marker)]],
            [
                *context,
                *_line_items(extension_lines, color=COLOR_MUTED, dashed=True),
            ],
            transition_type="fade_draw",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            replace_add=True,
        ),
        _beat(
            lesson_step,
            "equal-length-transfer",
            "transfer length",
            [["作", _equal_length_construction_text(marker, equality_label)]],
            [
                *with_auxiliary,
                *_line_items(extension_lines, color=COLOR_MUTED, dashed=True),
                *_distance_markers(equal_segments, color=COLOR_CONSTRAINT),
            ],
            transition_type="fade_draw",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            replace_add=True,
        ),
    ]


def _congruent_triangle_reveal_beats(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    marker = _first_equal_length_marker(bindings)
    if marker is None:
        return []
    triangles = [dict(item) for item in marker.get("triangles") or () if isinstance(item, dict)]
    if not triangles:
        return []
    u_default = _u_default(interactions)
    context = _moving_context_items(marker, include_auxiliary=True)
    beats: list[JsonObject] = []
    for index in range(len(triangles)):
        visible = triangles[: index + 1]
        derive: list[list[str]] = []
        if index == len(triangles) - 1:
            reason = _triangle_reason_text(marker)
            if reason:
                derive.append(["∵", reason])
            names = [str(item.get("name") or "") for item in visible if item.get("name")]
            if len(names) >= 2:
                derive.append(["∴", f"{names[0]}≅{names[1]}（SAS）"])
            else:
                derive.append(["∴", "对应三角形全等"])
        beats.append(
            _beat(
                lesson_step,
                f"congruent-triangle-{index + 1}",
                "congruent triangles",
                derive,
                [
                    *context,
                    _congruent_marker({**marker, "triangles": visible}),
                ],
                transition_type="fade",
                local_vars_tween=_u_tween(interactions, u_default, u_default),
                replace_add=True,
            )
        )
    return beats


def _equivalent_segment_emphasis_beats(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    marker = _first_equal_length_marker(bindings)
    if marker is None or not marker.get("equivalent_segments"):
        return []
    u_default = _u_default(interactions)
    label = str(marker.get("equivalence_label") or "")
    return [
        _beat(
            lesson_step,
            "equivalent-segment-emphasis",
            "equivalent segments",
            [["∴", label]] if label else [["∴", "两段距离相等"]],
            [
                *_moving_context_items(marker, include_auxiliary=True),
                _equivalent_segment_marker(marker),
            ],
            transition_type="fade_draw",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            replace_add=True,
        ),
    ]


def _path_replacement_reveal_beats(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    marker = _first_equal_length_marker(bindings)
    if marker is None:
        return []
    u_default = _u_default(interactions)
    path_lines = [dict(item) for item in marker.get("path_lines") or () if isinstance(item, dict)]
    replacement = marker.get("replacement_path_segment")
    if isinstance(replacement, dict):
        path_lines.append(dict(replacement))
    if not path_lines:
        return []
    beats = [
        _beat(
            lesson_step,
            "path-replacement-reveal",
            "path replacement",
            [["∴", f"{_path_equivalence_text(marker)}，转化为单动点路径"]],
            [
                *_moving_context_items(marker, include_auxiliary=True),
                *_line_items(path_lines, color=COLOR_PATH, dashed=False),
            ],
            transition_type="fade_draw",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            replace_add=True,
        ),
    ]
    if _has_local_parameter(interactions):
        u_left, u_right, u_default = _u_sweep_values(interactions)
        beats.append(
            _beat(
                lesson_step,
                "path-replacement-sweep",
                "sweep converted path",
                [],
                [
                    *_moving_context_items(marker, include_auxiliary=True),
                    *_line_items(path_lines, color=COLOR_PATH, dashed=False),
                ],
                transition_type="tween",
                local_vars_tween=_u_keyframes(interactions, (u_default, u_right, u_left, u_default)),
                duration_ms=2800,
                transition_duration_ms=2600,
                replace_add=True,
            )
        )
    return beats


def _moving_point_sweep_to_minimum_beats(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    marker = _first_equal_length_marker(bindings)
    if marker is None:
        return []
    u_left, u_right, u_default = _u_sweep_values(interactions)
    path_lines = _reduced_path_lines(marker)
    context = _moving_context_items(marker, include_auxiliary=True)
    hide_minimum_refs = _minimum_segment_hide_refs(marker)
    if not _has_local_parameter(interactions):
        return [
            _beat(
                lesson_step,
                "path-minimum-reduced-path",
                "reduced path",
                [["∵", _path_equivalence_text(marker)]],
                [
                    *context,
                    *_line_items(path_lines, color=COLOR_PATH, dashed=False),
                    _path_minimum_triangle(marker),
                ],
                transition_type="fade_draw",
                replace_add=True,
                hide=hide_minimum_refs,
            )
        ]
    return [
        _beat(
            lesson_step,
            "path-minimum-reduced-path",
            "reduced path",
            [["∵", _path_equivalence_text(marker)]],
            [
                *context,
                *_line_items(path_lines, color=COLOR_PATH, dashed=False),
            ],
            transition_type="fade_draw",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            hide=hide_minimum_refs,
        ),
        _beat(
            lesson_step,
            "path-minimum-sweep",
            "sweep moving point",
            [["∵", _moving_point_sweep_text(marker)]],
            [
                *context,
                *_line_items(path_lines, color=COLOR_PATH, dashed=False),
            ],
            transition_type="tween",
            local_vars_tween=_u_keyframes(interactions, (u_default, u_right, u_left, u_default)),
            duration_ms=3200,
            transition_duration_ms=3000,
            hide=hide_minimum_refs,
        ),
        _beat(
            lesson_step,
            "path-minimum-return",
            "return to minimum",
            [["∴", _minimum_position_text(marker)]],
            [
                *context,
                *_line_items(path_lines, color=COLOR_PATH, dashed=False),
                _path_minimum_triangle(marker),
            ],
            transition_type="tween",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            hide=hide_minimum_refs,
        ),
    ]


def _minimum_segment_reveal_beats(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    interactions: tuple[JsonObject, ...],
) -> list[JsonObject]:
    marker = _first_equal_length_marker(bindings)
    if marker is None:
        return []
    minimum_segment = marker.get("minimum_segment")
    if not isinstance(minimum_segment, dict):
        return []
    u_default = _u_default(interactions)
    path_lines = _reduced_path_lines(marker)
    hide_minimum_refs = _minimum_segment_hide_refs(marker)
    return [
        _beat(
            lesson_step,
            "path-minimum-result",
            "minimum segment",
            [["∴", f"最小值 = {minimum_segment.get('label') or ''}".strip()]],
            [
                *_moving_context_items(marker, include_auxiliary=True),
                *_line_items(path_lines, color=COLOR_PATH, dashed=False),
                _path_minimum_triangle(marker),
                _distance_marker(minimum_segment, color=COLOR_RESULT),
            ],
            transition_type="fade_draw",
            local_vars_tween=_u_tween(interactions, u_default, u_default),
            hide=hide_minimum_refs,
        ),
    ]


def _beat(
    lesson_step: LessonStep,
    beat_id: str,
    caption: str,
    derive: list[list[str]],
    add: list[JsonObject],
    *,
    transition_type: str,
    local_vars_tween: JsonObject | None = None,
    hide: list[str] | None = None,
    replace_add: bool = False,
    duration_ms: int = 1000,
    transition_duration_ms: int = 700,
) -> JsonObject:
    scene_patch: JsonObject = {
        "add": [item for item in add if item],
        "hide": list(hide or ()),
        "state_overrides": [],
    }
    if replace_add:
        scene_patch["replace_add"] = True
    return {
        "id": f"{lesson_step.id}:{beat_id}",
        "duration_ms": duration_ms,
        "caption": caption,
        "derive": derive,
        "scene_patch": scene_patch,
        "transition": {
            "type": transition_type,
            "duration_ms": transition_duration_ms,
            "easing": "easeInOutCubic",
            "local_vars": dict(local_vars_tween or {}),
        },
    }


def _point(point_id: str, *, color: str) -> JsonObject:
    return {
        "component": "Point",
        "at": point_id,
        "labelText": _point_label(point_id),
        "color": color,
        "dx": 12,
        "dy": -14,
        "metadata": {"low_level_type": "point"},
    }


def _line_items(lines: list[JsonObject], *, color: str, dashed: bool) -> list[JsonObject]:
    out: list[JsonObject] = []
    for line in lines:
        start = str(line.get("from") or "")
        end = str(line.get("to") or "")
        if not start or not end:
            continue
        out.append(
            {
                "component": "DashedLine" if dashed else "ColoredLine",
                "from": start,
                "to": end,
                "color": color,
                "width": 1.6 if dashed else 2.2,
                "dash": "5 6" if dashed else "",
                "metadata": {"low_level_type": "dashedLine" if dashed else "coloredLine"},
            }
        )
    return out


def _congruent_marker(marker: JsonObject) -> JsonObject:
    return {
        "component": "CongruentTriangleMarker",
        "triangles": [
            dict(item) for item in marker.get("triangles") or () if isinstance(item, dict)
        ],
        "fill": COLOR_CONGRUENT_REGION_FILL,
        "color": COLOR_CONGRUENT_REGION_STROKE,
    }


def _equivalent_segment_marker(marker: JsonObject) -> JsonObject:
    return {
        "component": "EquivalentSegmentMarker",
        "segments": [
            dict(item)
            for item in marker.get("equivalent_segments") or ()
            if isinstance(item, dict)
        ],
        "label": str(marker.get("equivalence_label") or ""),
        "color": COLOR_ACCENT,
        "width": 2.4,
    }


def _path_minimum_triangle(marker: JsonObject) -> JsonObject:
    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
    vertices = [
        _role_point(roles, point_refs, "fixed_point"),
        _role_point(roles, point_refs, "segment_moving_point"),
        _role_point(roles, point_refs, "auxiliary_point"),
    ]
    return {
        "component": "OutlineRegion",
        "vertices": [item for item in vertices if item],
        "fill": COLOR_RESULT_REGION_FILL_EMPHASIS,
        "color": COLOR_RESULT_REGION_STROKE_SOFT,
        "metadata": {"low_level_type": "outlineRegion"},
    }


def _distance_marker(segment: JsonObject, *, color: str) -> JsonObject:
    return {
        "component": "DistanceMarker",
        "handle": _distance_marker_handle(segment),
        "from": segment.get("from"),
        "to": segment.get("to"),
        "label": segment.get("label") or "",
        "color": color,
        "width": 2.6,
        "offsetPx": 18,
    }


def _minimum_segment_hide_refs(marker: JsonObject) -> list[str]:
    segment = marker.get("minimum_segment")
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    label = str(segment.get("label") or "")
    refs: list[str] = []
    if start and end:
        refs.extend((f"line:{start}:{end}", f"line:{end}:{start}"))
    if start and end and label:
        refs.extend((
            _distance_marker_handle(segment),
            f"distance:{end}:{start}:{label}",
        ))
    return list(dict.fromkeys(refs))


def _distance_marker_handle(segment: JsonObject) -> str:
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    label = str(segment.get("label") or "")
    return f"distance:{start}:{end}:{label}"


def _distance_markers(segments: list[JsonObject], *, color: str) -> list[JsonObject]:
    return [_distance_marker(segment, color=color) for segment in segments if segment]


def _keep_only_first_replace_add(beats: list[JsonObject]) -> None:
    seen = False
    for beat in beats:
        patch = beat.get("scene_patch") if isinstance(beat, dict) else None
        if not isinstance(patch, dict) or not patch.get("replace_add"):
            continue
        if seen:
            patch.pop("replace_add", None)
            continue
        seen = True


def _moving_context_items(marker: JsonObject, *, include_auxiliary: bool) -> list[JsonObject]:
    items: list[JsonObject] = []
    for role in ("segment_moving_point", "ray_moving_point"):
        point = _point_for_role(marker, role)
        if point:
            items.append(_point(point, color=COLOR_ACCENT))
    if include_auxiliary:
        auxiliary = _point_for_role(marker, "auxiliary_point")
        if auxiliary:
            items.append(_point(auxiliary, color=COLOR_RESULT))
    return items


def _construction_extension_lines(marker: JsonObject) -> list[JsonObject]:
    out: list[JsonObject] = []
    for line in marker.get("guide_lines") or ():
        if not isinstance(line, dict):
            continue
        if line.get("role") == "anchor_to_auxiliary":
            out.append(dict(line))
    return out


def _construction_equal_segments(marker: JsonObject) -> tuple[list[JsonObject], str]:
    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    anchor_label = str(roles.get("anchor") or "")
    reference_label = str(roles.get("segment_reference_point") or "")
    auxiliary_label = str(roles.get("auxiliary_point") or "")
    anchor = _point_for_role(marker, "anchor")
    reference = _point_for_role(marker, "segment_reference_point")
    auxiliary = _point_for_role(marker, "auxiliary_point")
    if not anchor or not reference or not auxiliary:
        return ([], "")
    reference_segment = {
        "from": anchor,
        "to": reference,
        "label": f"{anchor_label}{reference_label}",
    }
    constructed_segment = {
        "from": anchor,
        "to": auxiliary,
        "label": f"{anchor_label}{auxiliary_label}",
    }
    return (
        [reference_segment, constructed_segment],
        f"{constructed_segment['label']}={reference_segment['label']}",
    )


def _role_label(marker: JsonObject, role: str) -> str:
    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    return str(roles.get(role) or "")


def _segment_label(marker: JsonObject, key: str) -> str:
    segment = marker.get(key)
    return str(segment.get("label") or "") if isinstance(segment, dict) else ""


def _carrier_line_text(marker: JsonObject) -> str:
    anchor = _role_label(marker, "anchor")
    direction = _role_label(marker, "ray_direction_point")
    if anchor and direction:
        return f"沿{anchor}{direction}所在方向作辅助线"
    return "沿承载射线方向作辅助线"


def _equal_length_construction_text(marker: JsonObject, equality_label: str) -> str:
    auxiliary = _role_label(marker, "auxiliary_point")
    if auxiliary and equality_label:
        return f"取点{auxiliary}，使{equality_label}"
    if equality_label:
        return f"作等长线段，使{equality_label}"
    return "作等长线段"


def _triangle_reason_text(marker: JsonObject) -> str:
    anchor = _role_label(marker, "anchor")
    ray_moving = _role_label(marker, "ray_moving_point")
    segment_moving = _role_label(marker, "segment_moving_point")
    parts: list[str] = []
    if anchor and segment_moving and ray_moving:
        parts.append(f"{anchor}{ray_moving}={anchor}{segment_moving}")
    _, equality_label = _construction_equal_segments(marker)
    if equality_label:
        parts.append(equality_label)
    return "，".join(parts) or "对应边相等"


def _moving_point_sweep_text(marker: JsonObject) -> str:
    moving = _role_label(marker, "segment_moving_point")
    reference = _role_label(marker, "segment_reference_point")
    anchor = _role_label(marker, "anchor")
    auxiliary = _role_label(marker, "auxiliary_point")
    if moving and anchor and reference and auxiliary:
        return f"{moving}在{anchor}{reference}上运动，{auxiliary}为固定点"
    return "动点在定线上运动，辅助点固定"


def _minimum_position_text(marker: JsonObject) -> str:
    fixed = _role_label(marker, "fixed_point")
    moving = _role_label(marker, "segment_moving_point")
    auxiliary = _role_label(marker, "auxiliary_point")
    if fixed and moving and auxiliary:
        return f"当{fixed}、{moving}、{auxiliary}共线时路径最短"
    return "当动点落在两端连线方向上时路径最短"


def _reduced_path_lines(marker: JsonObject) -> list[JsonObject]:
    lines = [dict(item) for item in marker.get("path_lines") or () if isinstance(item, dict)]
    replacement = marker.get("replacement_path_segment")
    if isinstance(replacement, dict):
        lines.append(dict(replacement))
    return lines


def _path_equivalence_text(marker: JsonObject) -> str:
    common = marker.get("common_path_segment")
    replacement = marker.get("replacement_path_segment")
    original = marker.get("equivalent_segments") or ()
    common_label = str(common.get("label") or "") if isinstance(common, dict) else ""
    replacement_label = str(replacement.get("label") or "") if isinstance(replacement, dict) else ""
    original_label = ""
    if original and isinstance(original[0], dict):
        original_label = str(original[0].get("label") or "")
    if common_label and original_label and replacement_label:
        return f"{common_label}+{original_label}={common_label}+{replacement_label}"
    label = str(marker.get("equivalence_label") or "")
    return label or "路径转化为单动点问题"


def _first_equal_length_marker(bindings: VisualRoleBindings) -> JsonObject | None:
    for marker in bindings.equal_length_path_markers:
        if isinstance(marker, dict) and isinstance(marker.get("roles"), dict):
            return marker
    return None


def _point_for_role(marker: JsonObject, role: str) -> str:
    roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
    point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
    return _role_point(roles, point_refs, role)


def _role_point(roles: JsonObject, point_refs: JsonObject, role: str) -> str:
    label = str(roles.get(role) or "")
    if not label:
        return ""
    return str(point_refs.get(label) or label)


def _u_default(interactions: tuple[JsonObject, ...]) -> float:
    default = 0.5
    for interaction in interactions:
        domain = interaction.get("domain") if isinstance(interaction, dict) else None
        if isinstance(domain, dict):
            try:
                default = float(domain.get("default", default))
            except Exception:
                default = 0.5
            break
    return round(max(0.0, min(1.0, default)), 4)


def _has_local_parameter(interactions: tuple[JsonObject, ...], parameter: str = "u") -> bool:
    for interaction in interactions:
        if not isinstance(interaction, dict):
            continue
        if str(interaction.get("parameter") or "") == parameter:
            return True
        for control in interaction.get("controls") or ():
            if isinstance(control, dict) and str(control.get("var") or "") == parameter:
                return True
    return False


def _u_tween(interactions: tuple[JsonObject, ...], start: float, end: float) -> JsonObject | None:
    if not _has_local_parameter(interactions):
        return None
    return {"u": {"from": start, "to": end}}


def _u_keyframes(interactions: tuple[JsonObject, ...], values: tuple[float, ...]) -> JsonObject | None:
    if not _has_local_parameter(interactions) or not values:
        return None
    if len(values) == 1:
        return _u_tween(interactions, values[0], values[0])
    step = 1.0 / (len(values) - 1)
    return {
        "u": {
            "keyframes": [
                {"at": round(index * step, 4), "value": round(float(value), 4)}
                for index, value in enumerate(values)
            ]
        }
    }


def _u_sweep_values(interactions: tuple[JsonObject, ...]) -> tuple[float, float, float]:
    default = _u_default(interactions)
    left = min(0.25, max(0.05, default * 0.45))
    right = max(0.75, min(0.95, default + (1.0 - default) * 0.72))
    if right <= left:
        left, right = 0.15, 0.85
    return (round(left, 4), round(right, 4), default)


def _point_label(point_id: str) -> str:
    text = str(point_id)
    return text.rstrip("0123456789") or text


def _point_display(point_id: str, lesson_step: LessonStep) -> str:
    label = _point_label(point_id)
    for text in (*lesson_step.box, *_derive_texts(lesson_step)):
        phrase = _coordinate_phrase_for_label(label, str(text))
        if phrase:
            return phrase
    return label


def _derive_texts(lesson_step: LessonStep) -> tuple[str, ...]:
    out: list[str] = []
    for line in lesson_step.derive:
        if isinstance(line, (list, tuple)) and len(line) >= 2:
            out.append(str(line[1]))
    return tuple(out)


def _coordinate_phrase_for_label(label: str, text: str) -> str:
    marker = f"{label}("
    start = text.find(marker)
    if start < 0:
        return ""
    depth = 0
    for index in range(start + len(label), len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1].replace(" ", "")
    return ""


def _translation_label(vector: Any) -> str:
    if not isinstance(vector, list) or len(vector) != 2:
        return "v"
    dx = str(vector[0])
    dy = str(vector[1])
    if dy in {"0", "0.0"}:
        return f"+{dx}" if not dx.startswith("-") else dx
    return f"({dx},{dy})"


@lru_cache(maxsize=1)
def _method_registry() -> MethodSpecRegistry:
    return MethodSpecRegistry.load_from_code()


def _method_visual(method_id: str):
    try:
        return _method_registry().require(method_id).visual
    except KeyError:
        return None


@lru_cache(maxsize=1)
def _recipe_registry() -> RecipeSpecRegistry:
    return RecipeSpecRegistry.load_from_code()


def _recipe_spec(recipe_id: str):
    return _recipe_registry().get(recipe_id)
