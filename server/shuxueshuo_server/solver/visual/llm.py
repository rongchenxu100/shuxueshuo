"""LLM optimizer for code-generated VisualStepIR.

The optimizer is intentionally a post-processing layer.  Code builds the
VisualStepIR first; the LLM may only append visual annotations/highlights and
adjust focus state.  It cannot change LessonIR, geometry, mathematical facts,
or remove code-generated scene objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import copy
import json
import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonIR
from shuxueshuo_server.solver.runtime._paths import repo_root
from shuxueshuo_server.solver.runtime.llm_clients import LLMPlannerClient

from .compiler import _compile_scene_items
from .models import JsonObject, VisualStepIR, visual_step_ir_from_payload
from .registry import default_component_registry
from .validator import VisualStepIRValidator


@dataclass(frozen=True)
class VisualOptimizationPrompt:
    """Prompt sent to the visual optimization LLM."""

    system: str
    user: str

    @property
    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            {"role": "user", "content": self.user},
        ]


class VisualOptimizationError(RuntimeError):
    """The visual optimization response was not usable."""


class LLMVisualStepOptimizer:
    """Optimize code-generated VisualStepIR with an LLM patch."""

    def __init__(
        self,
        *,
        client: LLMPlannerClient,
        debug_dir: str | Path | None = None,
    ) -> None:
        self.client = client
        self.debug_dir = Path(debug_dir) if debug_dir is not None else None
        self.last_payload: dict[str, Any] | None = None
        self.last_prompt: VisualOptimizationPrompt | None = None
        self.last_raw_response: str | None = None
        self.last_parsed: dict[str, Any] | None = None
        self.last_error: str | None = None

    def optimize(
        self,
        *,
        snapshot: ExplanationSnapshot,
        lesson: LessonIR,
        visual_ir: VisualStepIR,
    ) -> VisualStepIR:
        payload = build_visual_optimizer_payload(
            snapshot=snapshot,
            lesson=lesson,
            visual_ir=visual_ir,
        )
        prompt = render_visual_optimizer_prompt(payload)
        raw = self.client.complete(
            {
                "messages": prompt.messages,
                "problem_id": visual_ir.problem_id,
                "family_id": snapshot.family_id,
                "visual_payload": payload,
            }
        )
        parsed: dict[str, Any] | None = None
        optimized = visual_ir
        error: str | None = None
        try:
            parsed = _parse_json_object(raw)
            optimized = apply_visual_optimization_patch(visual_ir, parsed)
            _assert_visual_patch_safe(optimized)
            VisualStepIRValidator().validate(optimized)
        except Exception as exc:  # pragma: no cover - exercised through fallback behavior
            error = str(exc)
            optimized = _visual_ir_with_optimizer_gap(visual_ir, error)
        self.last_payload = payload
        self.last_prompt = prompt
        self.last_raw_response = raw
        self.last_parsed = parsed
        self.last_error = error
        if self.debug_dir is not None:
            write_visual_optimization_debug_artifacts(
                self.debug_dir,
                payload=payload,
                prompt=prompt,
                raw_response=raw,
                parsed=parsed,
                optimized_visual_ir=optimized,
                error=error,
            )
        return optimized


def build_visual_optimizer_payload(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    visual_ir: VisualStepIR,
) -> dict[str, Any]:
    """Build the LLM-facing visual optimization payload."""
    lesson_steps = {step.id: step for step in lesson.steps}
    visual_steps = []
    for step in visual_ir.steps:
        lesson_step = lesson_steps.get(step.lesson_step_id)
        visual_steps.append(
            {
                "visual_step_id": step.visual_step_id,
                "lesson_step_id": step.lesson_step_id,
                "scope_id": step.scope_id,
                "lesson_title": lesson_step.title if lesson_step else "",
                "lesson_goal": lesson_step.goal if lesson_step else "",
                "lesson_box": list(lesson_step.box) if lesson_step else [],
                "source_step_ids": list(lesson_step.source_step_ids) if lesson_step else [],
                "capability_ids": list(lesson_step.capability_ids) if lesson_step else [],
                "teaching_substep_ids": list(lesson_step.teaching_substep_ids) if lesson_step else [],
                "allowed_geometry_refs": sorted(_allowed_geometry_refs_for_step(visual_ir, step)),
                "scene": step.scene,
            }
        )
    return {
        "task": "optimize_code_generated_visual_steps",
        "problem_id": visual_ir.problem_id,
        "family_id": snapshot.family_id,
        "allowed_geometry_refs": sorted(_allowed_geometry_refs(visual_ir)),
        "base_layers": visual_ir.layers,
        "component_types": sorted(default_component_registry().visual_types),
        "visual_steps": visual_steps,
        "output_schema": {
            "layer_patches": [
                {
                    "layer_ref": "可选；必须来自 base_layers 的 key",
                    "append_elements": ["可选；追加 section/global base layer 元素"],
                }
            ],
            "visual_step_patches": [
                {
                    "lesson_step_id": "必须来自 visual_steps[].lesson_step_id",
                    "append_add": ["可选；追加 scene item，不能删除原对象"],
                    "append_annotations": ["可选；追加 annotation"],
                    "state_overrides": ["可选；仅用于已有对象的教学状态"],
                    "hide": ["可选；隐藏已有 layer 或对象"],
                    "focus": {"primary": [], "dim": []},
                }
            ]
        },
        "rules": [
            "只返回 JSON，不要使用 Markdown 代码块。",
            "你只能优化 VisualStepIR，不要改 LessonIR、数学事实、答案、geometry-spec 或 step 顺序。",
            "不要删除代码生成的 scene.add；只能通过 append_add 追加安全的视觉标注或辅助强调。",
            "可以通过 layer_patches 优化 generated base layers 的显示策略，但不能新增未知 geometry ref。",
            "所有 at/from/to/vertex/rayA/rayB/curveId 必须来自 allowed_geometry_refs。",
            "不要在 append_add 中新增 CoordinateLabel；坐标标签只能由代码从 verified runtime artifacts 生成。",
            "不要发明新点、新线、新坐标或新公式。",
            "优先优化学生注意力：focus、简短 annotation、已有点线的 highlight/muted 状态。",
            "如果没有确定优化，就返回空 visual_step_patches。",
        ],
    }


def render_visual_optimizer_prompt(payload: dict[str, Any]) -> VisualOptimizationPrompt:
    env = Environment(
        loader=FileSystemLoader(str(_default_template_dir())),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["pretty_json"] = _pretty_json
    system = env.get_template("visual-system.jinja").render().strip()
    user = env.get_template("visual-user.jinja").render(payload=payload).strip()
    return VisualOptimizationPrompt(system=system, user=user)


def apply_visual_optimization_patch(visual_ir: VisualStepIR, patch: dict[str, Any]) -> VisualStepIR:
    patches = patch.get("visual_step_patches", [])
    if not isinstance(patches, list):
        raise VisualOptimizationError("visual_step_patches must be a list")
    payload = visual_ir.to_payload()
    layer_patches = patch.get("layer_patches", [])
    if layer_patches is None:
        layer_patches = []
    if not isinstance(layer_patches, list):
        raise VisualOptimizationError("layer_patches must be a list")
    steps = payload.get("steps") or []
    by_lesson = {
        str(step.get("lesson_step_id")): step
        for step in steps
        if isinstance(step, dict)
    }
    by_visual = {
        str(step.get("visual_step_id")): step
        for step in steps
        if isinstance(step, dict)
    }
    allowed_refs = _allowed_geometry_refs(visual_ir)
    step_allowed_refs = {
        step.visual_step_id: _allowed_geometry_refs_for_step(visual_ir, step)
        for step in visual_ir.steps
    }
    step_allowed_refs.update(
        {
            step.lesson_step_id: _allowed_geometry_refs_for_step(visual_ir, step)
            for step in visual_ir.steps
        }
    )
    layers = payload.setdefault("layers", {})
    for item in layer_patches:
        if not isinstance(item, dict):
            raise VisualOptimizationError("layer_patches items must be objects")
        _apply_patch_to_layer(layers, item, allowed_refs)
    for item in patches:
        if not isinstance(item, dict):
            raise VisualOptimizationError("visual_step_patches items must be objects")
        target = by_lesson.get(str(item.get("lesson_step_id") or "")) or by_visual.get(
            str(item.get("visual_step_id") or "")
        )
        if target is None:
            raise VisualOptimizationError(
                f"unknown visual step patch target: {item.get('lesson_step_id') or item.get('visual_step_id')}"
            )
        patch_key = str(item.get("lesson_step_id") or item.get("visual_step_id") or "")
        _apply_patch_to_step(target, item, step_allowed_refs.get(patch_key, allowed_refs))
    payload.setdefault("metadata", {})
    payload["metadata"]["visual_optimizer"] = {
        "applied": True,
        "patch_count": len(patches),
    }
    return visual_step_ir_from_payload(payload)


def write_visual_optimization_debug_artifacts(
    debug_dir: str | Path,
    *,
    payload: dict[str, Any],
    prompt: VisualOptimizationPrompt,
    raw_response: str,
    parsed: dict[str, Any] | None,
    optimized_visual_ir: VisualStepIR,
    error: str | None = None,
) -> None:
    path = Path(debug_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "payload.visual.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (path / "prompt.system.txt").write_text(prompt.system, encoding="utf-8")
    (path / "prompt.user.txt").write_text(prompt.user, encoding="utf-8")
    (path / "raw-response.txt").write_text(raw_response, encoding="utf-8")
    if parsed is not None:
        (path / "parsed-visual-optimization.json").write_text(
            json.dumps(parsed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    (path / "optimized-visual-step-ir.json").write_text(
        json.dumps(optimized_visual_ir.to_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if error is not None:
        (path / "visual-optimization-error.txt").write_text(error, encoding="utf-8")


def _apply_patch_to_step(step: dict[str, Any], patch: dict[str, Any], allowed_refs: set[str]) -> None:
    for forbidden in ("interactions", "parameterized_points", "pointOverrides", "localControls", "timeline", "animation"):
        if forbidden in patch:
            raise VisualOptimizationError(f"LLM visual patches cannot modify {forbidden}")
    scene = step.setdefault("scene", {})
    if "append_add" in patch:
        append_add = _list_of_objects(patch["append_add"], "append_add")
        append_add = _filter_safe_append_add(append_add)
        for item in append_add:
            _assert_scene_item_refs(item, allowed_refs)
        scene.setdefault("add", [])
        scene["add"].extend(copy.deepcopy(append_add))
    if "append_annotations" in patch:
        annotations = _list_of_objects(patch["append_annotations"], "append_annotations")
        scene.setdefault("annotations", [])
        scene["annotations"].extend(copy.deepcopy(annotations))
    if "state_overrides" in patch:
        overrides = _list_of_objects(patch["state_overrides"], "state_overrides")
        scene.setdefault("state_overrides", [])
        scene["state_overrides"].extend(copy.deepcopy(overrides))
    if "hide" in patch:
        hide = patch["hide"]
        if not isinstance(hide, list):
            raise VisualOptimizationError("hide must be a list")
        scene.setdefault("hide", [])
        scene["hide"].extend(str(item) for item in hide)
    if "focus" in patch:
        focus = patch["focus"]
        if not isinstance(focus, dict):
            raise VisualOptimizationError("focus must be an object")
        scene.setdefault("focus", {})
        for key in ("primary", "dim"):
            if key in focus:
                value = focus[key]
                if not isinstance(value, list):
                    raise VisualOptimizationError(f"focus.{key} must be a list")
                refs = [str(item) for item in value]
                for ref in refs:
                    _assert_focus_ref(ref, allowed_refs)
                scene["focus"][key] = refs


def _apply_patch_to_layer(layers: dict[str, Any], patch: dict[str, Any], allowed_refs: set[str]) -> None:
    layer_ref = str(patch.get("layer_ref") or "")
    if layer_ref not in layers:
        raise VisualOptimizationError(f"unknown layer patch target: {layer_ref}")
    append = patch.get("append_elements", [])
    if append is None:
        append = []
    append_items = _list_of_objects(append, "append_elements")
    append_items = _filter_safe_append_add(append_items)
    layer = layers.setdefault(layer_ref, {})
    layer.setdefault("elements", [])
    compiled: list[dict[str, Any]] = []
    for item in append_items:
        if "component" in item:
            _assert_scene_item_refs(item, allowed_refs)
            compiled.extend(_compile_scene_items(item))
        else:
            _assert_low_level_item_refs(item, allowed_refs)
            compiled.append(copy.deepcopy(item))
    layer["elements"].extend(compiled)


def _assert_scene_item_refs(item: dict[str, Any], allowed_refs: set[str]) -> None:
    component = str(item.get("component") or "")
    if component == "VisualGap":
        return
    if default_component_registry().get(component) is None:
        raise VisualOptimizationError(f"unknown visual component: {component}")
    _assert_math_only_visual_label(item)
    if component == "AngleEqualityMarker":
        for nested in item.get("angles") or ():
            if isinstance(nested, dict):
                _assert_scene_item_refs({"component": "AngleArc", **nested}, allowed_refs)
        for nested in item.get("guide_arms") or ():
            if isinstance(nested, dict):
                _assert_scene_item_refs({"component": "DashedLine", **nested}, allowed_refs)
        return
    if component == "EqualAcuteAngleInterceptMarker":
        for nested in item.get("triangle_regions") or ():
            if isinstance(nested, dict):
                for ref in nested.get("vertices") or ():
                    if isinstance(ref, str) and ref not in allowed_refs:
                        raise VisualOptimizationError(f"unknown geometry ref in visual patch: {ref}")
        for nested in item.get("angles") or ():
            if isinstance(nested, dict):
                _assert_scene_item_refs({"component": "AngleArc", **nested}, allowed_refs)
        for nested in item.get("right_angles") or ():
            if isinstance(nested, dict):
                _assert_scene_item_refs({"component": "RightAngle", **nested}, allowed_refs)
        for nested in item.get("lines") or ():
            if isinstance(nested, dict):
                line_component = "DashedLine" if nested.get("style") == "dashed" else "ColoredLine"
                _assert_scene_item_refs({"component": line_component, **nested}, allowed_refs)
        return
    if component == "CongruentTriangleMarker":
        for nested in item.get("triangles") or ():
            if isinstance(nested, dict):
                for ref in nested.get("vertices") or ():
                    if isinstance(ref, str) and ref not in allowed_refs:
                        raise VisualOptimizationError(f"unknown geometry ref in visual patch: {ref}")
        return
    if component == "EquivalentSegmentMarker":
        for nested in item.get("segments") or ():
            if isinstance(nested, dict):
                _assert_scene_item_refs({"component": "ColoredLine", **nested}, allowed_refs)
        return
    for key in ("at", "from", "to", "source", "target", "vertex", "rayA", "rayB", "curveId"):
        value = item.get(key)
        if isinstance(value, str) and value not in allowed_refs:
            raise VisualOptimizationError(f"unknown geometry ref in visual patch: {value}")


def _assert_low_level_item_refs(item: dict[str, Any], allowed_refs: set[str]) -> None:
    _assert_math_only_visual_label(item)
    for key in ("at", "from", "to", "source", "target", "vertex", "rayA", "rayB", "curveId"):
        value = item.get(key)
        if isinstance(value, str) and value not in allowed_refs:
            raise VisualOptimizationError(f"unknown geometry ref in visual layer patch: {value}")


def _assert_math_only_visual_label(item: dict[str, Any]) -> None:
    for key in ("label", "text"):
        value = item.get(key)
        if isinstance(value, str) and re.search(r"[\u4e00-\u9fff]", value):
            raise VisualOptimizationError(
                f"visual {key} must use math notation, not Chinese prose: {value}"
            )


def _assert_focus_ref(ref: str, allowed_refs: set[str]) -> None:
    if ":" not in ref:
        return
    _, value = ref.split(":", 1)
    if value and value not in allowed_refs:
        raise VisualOptimizationError(f"unknown geometry ref in visual focus patch: {value}")


def _filter_safe_append_add(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("component") or "") == "CoordinateLabel":
            continue
        if item.get("persistence") not in (None, "step_only"):
            raise VisualOptimizationError("LLM visual patches cannot create carry_forward objects")
        item = dict(item)
        safe.append(item)
    return safe


def _assert_visual_patch_safe(visual_ir: VisualStepIR) -> None:
    text = json.dumps(visual_ir.to_payload(), ensure_ascii=False)
    for forbidden in ("$problem.", "$question.", "$subquestion.", "<script", "<svg", "<html"):
        if forbidden in text:
            raise VisualOptimizationError(f"unsafe visual optimization contains {forbidden}")


def _visual_ir_with_optimizer_gap(visual_ir: VisualStepIR, error: str) -> VisualStepIR:
    payload = visual_ir.to_payload()
    payload.setdefault("metadata", {})
    payload["metadata"]["visual_optimizer"] = {
        "applied": False,
        "error": error,
    }
    return visual_step_ir_from_payload(payload)


def _list_of_objects(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise VisualOptimizationError(f"{name} must be a list")
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise VisualOptimizationError(f"{name} items must be objects")
        out.append(dict(item))
    return out


def _allowed_geometry_refs(visual_ir: VisualStepIR) -> set[str]:
    refs = set((visual_ir.geometry_spec.get("fixedPoints") or {}).keys())
    refs.update((visual_ir.geometry_spec.get("movingPoints") or {}).keys())
    refs.update(
        str(curve.get("id"))
        for curve in visual_ir.geometry_spec.get("curves") or ()
        if isinstance(curve, dict) and curve.get("id")
    )
    refs.update(visual_ir.layer_registry)
    refs.update(layer_key for layer_key in visual_ir.layer_registry.values())
    return {str(item) for item in refs if item is not None}


def _allowed_geometry_refs_for_step(visual_ir: VisualStepIR, step: Any) -> set[str]:
    refs: set[str] = set()
    layers = visual_ir.layers or {}
    for item in (layers.get("global") or {}).get("elements") or ():
        if isinstance(item, dict):
            refs.update(_item_geometry_refs(item))
    scene = step.scene or {}
    inherits_from = str(scene.get("inherits_from") or "")
    for item in (layers.get(inherits_from) or {}).get("elements") or ():
        if isinstance(item, dict):
            refs.update(_item_geometry_refs(item))
    guide_only_refs: set[str] = set()
    for item in scene.get("add") or ():
        if not isinstance(item, dict):
            continue
        refs.update(_item_geometry_refs(item))
        guide_only_refs.update(str(ref) for ref in item.get("guide_only_refs") or ())
    for interaction in step.interactions or ():
        if not isinstance(interaction, dict):
            continue
        refs.update(
            str(point_id)
            for point_id in (interaction.get("parameterized_points") or {})
            if point_id
        )
    return refs - guide_only_refs


def _item_geometry_refs(item: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for key in ("at", "from", "to", "source", "target", "vertex", "rayA", "rayB", "curveId"):
        value = item.get(key)
        if isinstance(value, str):
            refs.add(value)
    for nested_key in ("angles", "guide_arms", "lines", "right_angles"):
        for nested in item.get(nested_key) or ():
            if isinstance(nested, dict):
                refs.update(_item_geometry_refs(nested))
    for region in item.get("triangle_regions") or ():
        if isinstance(region, dict):
            refs.update(str(ref) for ref in region.get("vertices") or () if isinstance(ref, str))
    return refs


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise VisualOptimizationError("visual optimizer must return a JSON object")
    return parsed


def _default_template_dir() -> Path:
    return repo_root() / "internal" / "llm-prompts"


def _pretty_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
