"""Small scene item helpers shared by VisualStepIR builders."""

from __future__ import annotations

from typing import Any
import json

from .models import JsonObject
from .palette import COLOR_ACCENT, COLOR_PATH, COLOR_RESULT


def focus_handles(scene_add: list[JsonObject]) -> list[str]:
    refs: list[str] = []

    def add_ref(value: Any) -> None:
        ref = str(value or "")
        if ref and ref not in refs:
            refs.append(ref)

    for item in scene_add:
        component = str(item.get("component") or "")
        if component in {"Point", "CoordinateLabel"}:
            add_ref(item.get("at"))
        elif component in {"TranslationMarker"}:
            add_ref(item.get("source"))
            add_ref(item.get("target"))
        elif component in {"DistanceMarker"}:
            add_ref(item.get("from"))
            add_ref(item.get("to"))
        elif component in {"ColoredLine", "DashedLine"}:
            if item.get("state") == "highlight" or item.get("color") in {
                COLOR_ACCENT,
                COLOR_RESULT,
                COLOR_PATH,
            }:
                add_ref(item.get("from"))
                add_ref(item.get("to"))
        elif component == "AngleEqualityMarker":
            guide_only_refs = {str(ref) for ref in item.get("guide_only_refs") or ()}
            for angle in item.get("angles") or ():
                if not isinstance(angle, dict):
                    continue
                for key in ("vertex", "rayA", "rayB"):
                    ref = str(angle.get(key) or "")
                    if ref and ref not in guide_only_refs:
                        add_ref(ref)
        elif component == "EqualAcuteAngleInterceptMarker":
            for line in item.get("lines") or ():
                if isinstance(line, dict):
                    add_ref(line.get("from"))
                    add_ref(line.get("to"))
            for angle in item.get("angles") or ():
                if not isinstance(angle, dict):
                    continue
                for key in ("vertex", "rayA", "rayB"):
                    add_ref(angle.get(key))
    return [f"point:{ref}" for ref in refs[:4]]


def visual_gap(expected_role: str, reason: str) -> JsonObject:
    return {
        "component": "VisualGap",
        "expected_role": expected_role,
        "reason": reason,
        "state": "gap",
    }


def dedupe_scene_items(items: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    out: list[JsonObject] = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
