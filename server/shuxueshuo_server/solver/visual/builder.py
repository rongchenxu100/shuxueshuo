"""VS1 forward builder from LessonIR to VisualStepIR."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
import copy
import json
import re

from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonIR, LessonStep
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.recipes import RecipeSpecRegistry
from shuxueshuo_server.solver.student_display import student_math_display

from .models import JsonObject, VisualStep, VisualStepIR
from .animation import AnimationTimelineBuilder
from .parametric import ParametricExpressionResolver
from .registry import default_layer_registry
from .geometry_naming import GeometryPointScopeNamer, scope_root as _shared_scope_root
from .role_binders import VisualGeometryIndex, VisualRoleBinderRegistry, VisualRoleBindings


COLOR_TEXT = "#1f2937"
COLOR_MUTED = "#64748b"
COLOR_CURVE = "#2563eb"
COLOR_PATH = "#7c3aed"
COLOR_RESULT = "#b45309"
COLOR_ACCENT = "#dc2626"
COLOR_CONSTRAINT = "#0f766e"


@dataclass(frozen=True)
class VisualAuthoringBase:
    """Authored geometry/page shell.

    This remains available for VS0 round-trip/golden comparison.  The VS1
    product path should use GeneratedVisualBase instead.
    """

    geometry_spec: JsonObject
    lesson_data: JsonObject
    step_decorations: JsonObject

    @classmethod
    def from_lesson_spec_dir(cls, path: str | Path) -> "VisualAuthoringBase":
        base = Path(path)
        return cls(
            geometry_spec=json.loads((base / "geometry-spec.json").read_text(encoding="utf-8")),
            lesson_data=json.loads((base / "lesson-data.json").read_text(encoding="utf-8")),
            step_decorations=json.loads((base / "step-decorations.json").read_text(encoding="utf-8")),
        )


@dataclass(frozen=True)
class GeneratedVisualBase:
    """Generated geometry/page shell for the VS1 product path."""

    geometry_spec: JsonObject
    lesson_data: JsonObject
    layers: dict[str, JsonObject]
    default_t: float

    @classmethod
    def from_snapshot(cls, snapshot: ExplanationSnapshot, lesson: LessonIR) -> "GeneratedVisualBase":
        geometry_spec = GeometrySpecBuilder().build(snapshot=snapshot, lesson=lesson)
        default_t = _parameter_default_value(snapshot)
        lesson_data = _generated_lesson_shell(snapshot=snapshot, lesson=lesson, default_t=default_t)
        layers = BaseSceneBuilder().build(
            geometry_spec=geometry_spec,
            lesson=lesson,
            snapshot=snapshot,
        )
        return cls(
            geometry_spec=geometry_spec,
            lesson_data=lesson_data,
            layers=layers,
            default_t=default_t,
        )


@dataclass(frozen=True)
class _SceneBuildContext:
    lesson_step: LessonStep
    bindings: VisualRoleBindings
    coordinate_texts: dict[str, str] | None
    capabilities: frozenset[str]
    substeps: frozenset[str]
    template_items: tuple[JsonObject, ...] = ()

    @property
    def points(self) -> dict[str, str]:
        return self.bindings.point_handles


@dataclass(frozen=True)
class _SceneVisualRule:
    handler: Callable[[_SceneBuildContext], list[JsonObject]]
    capability_ids: tuple[str, ...] = ()
    substep_ids: tuple[str, ...] = ()
    recipe_without_substeps: tuple[str, ...] = ()

    def applies(self, context: _SceneBuildContext) -> bool:
        if self.capability_ids and context.capabilities.intersection(self.capability_ids):
            return True
        if self.substep_ids and context.substeps.intersection(self.substep_ids):
            return True
        if self.recipe_without_substeps and not context.substeps:
            return bool(context.capabilities.intersection(self.recipe_without_substeps))
        return False


@dataclass(frozen=True)
class _PointVisualStyle:
    color: str = COLOR_ACCENT
    dx: int = 14
    dy: int = -18


POINT_ACTIVE = _PointVisualStyle(color=COLOR_ACCENT)
POINT_RESULT = _PointVisualStyle(color=COLOR_RESULT)
POINT_AUXILIARY = _PointVisualStyle(color=COLOR_RESULT, dy=18)
POINT_MOVING = _PointVisualStyle(color=COLOR_ACCENT)


class GeometrySpecBuilder:
    """Generate a minimal renderable geometry-spec from successful runtime facts."""

    def build(self, *, snapshot: ExplanationSnapshot, lesson: LessonIR) -> JsonObject:
        parameter_name = _parameter_name(snapshot)
        default_t = _parameter_default_value(snapshot)
        fixed_points, moving_points, point_meta = _geometry_points_from_snapshot(snapshot, lesson, default_t)
        curves = _curves_from_snapshot(snapshot)
        domain = _domain_from_geometry_points(fixed_points, moving_points, parameter_name, default_t)
        return {
            "version": 1,
            "id": snapshot.problem_id,
            "domain": domain,
            "movingParam": parameter_name,
            "expressionEnv": [],
            "fixedPoints": fixed_points,
            "movingPoints": moving_points,
            "pointMeta": point_meta,
            "curves": curves,
            "derivedIntersections": [],
        }


class BaseSceneBuilder:
    """Generate global and section base layers from generated geometry."""

    def build(
        self,
        *,
        geometry_spec: JsonObject,
        lesson: LessonIR,
        snapshot: ExplanationSnapshot,
    ) -> dict[str, JsonObject]:
        layers: dict[str, JsonObject] = {
            "global": {"elements": [{"type": "grid"}]},
        }
        section_step_ids: dict[str, list[str]] = {}
        for step in lesson.steps:
            section_step_ids.setdefault(_scope_root(step.scope_id), []).append(step.id)

        for section_scope, step_ids in sorted(section_step_ids.items()):
            index = VisualGeometryIndex.default(geometry_spec, snapshot.problem)
            layers[f"section:{section_scope}"] = {
                "elements": _base_elements_for_section(
                    section_scope,
                    geometry_spec,
                    snapshot=snapshot,
                    index=index,
                ),
                "stepIds": step_ids,
                "stepStartsWith": step_ids,
            }
        return layers


class VisualStepBuilder:
    """Build static VisualStepIR from successful explanation artifacts."""

    def build(
        self,
        *,
        snapshot: ExplanationSnapshot,
        lesson: LessonIR,
        authoring_base: VisualAuthoringBase | None = None,
        generated_base: GeneratedVisualBase | None = None,
    ) -> VisualStepIR:
        base = generated_base
        legacy_authoring_base = authoring_base
        if base is None:
            if legacy_authoring_base is None:
                base = GeneratedVisualBase.from_snapshot(snapshot, lesson)
            else:
                base = GeneratedVisualBase(
                    geometry_spec=legacy_authoring_base.geometry_spec,
                    lesson_data=legacy_authoring_base.lesson_data,
                    layers=_layers_for_lesson(lesson, legacy_authoring_base.step_decorations),
                    default_t=_default_t(legacy_authoring_base.lesson_data),
                )
        lesson_data = _lesson_data_from_lesson_ir(lesson, base.lesson_data)
        layers = copy.deepcopy(base.layers)
        binder = VisualRoleBinderRegistry.default(base.geometry_spec, snapshot.problem)
        steps = tuple(
            _visual_step_for_lesson_step(
                lesson_step,
                snapshot=snapshot,
                geometry_spec=base.geometry_spec,
                bindings=binder.bind(lesson_step, snapshot),
            )
            for lesson_step in lesson.steps
        )
        return VisualStepIR(
            version=1,
            problem_id=lesson.problem_id,
            geometry_spec=copy.deepcopy(base.geometry_spec),
            lesson_data=lesson_data,
            layers=layers,
            layer_registry=dict(default_layer_registry().semantic_to_layer),
            steps=steps,
            metadata={
                "source": "vs1_visual_step_builder",
                "base_source": "generated" if legacy_authoring_base is None else "authored_legacy",
                "scene_model": "section_accumulator",
            },
        )


def _lesson_data_from_lesson_ir(lesson: LessonIR, base_lesson_data: JsonObject) -> JsonObject:
    out = copy.deepcopy(base_lesson_data)
    section_titles = {
        section.scope_id: section.title
        for section in lesson.sections
    }
    out.setdefault("meta", {})
    out["meta"]["id"] = lesson.problem_id
    steps: list[dict[str, Any]] = []
    policies: dict[str, Any] = {}
    labels: dict[str, str] = {}
    section_counts: dict[str, int] = {}
    for step in lesson.steps:
        section = section_titles.get(step.scope_id, step.scope_id)
        section_counts[section] = section_counts.get(section, 0) + 1
        local_index = section_counts[section]
        t_value = _default_t(base_lesson_data)
        steps.append(
            {
                "id": step.id,
                "section": section,
                "title": _display_title(local_index, step.title),
                "t": t_value,
                "derive": [list(item) for item in step.derive],
                "box": list(step.box),
            }
        )
        policies[step.id] = {"movable": False, "range": [t_value, t_value]}
        labels[step.id] = _short_label(local_index, step)
    out["steps"] = steps
    out["policies"] = policies
    out["stepLabels"] = labels
    return out


def _layers_for_lesson(lesson: LessonIR, base_step_decorations: JsonObject) -> dict[str, JsonObject]:
    raw_layers = copy.deepcopy((base_step_decorations or {}).get("layers") or {})
    registry = default_layer_registry()
    layers: dict[str, JsonObject] = {}
    for layer_key, raw_layer in raw_layers.items():
        semantic_ref = registry.semantic_for_layer_key(str(layer_key))
        if semantic_ref == "global" or semantic_ref.startswith("section:"):
            layers[semantic_ref] = raw_layer

    layers.setdefault("global", {"elements": [{"type": "grid"}]})
    section_roots = sorted({_scope_root(step.scope_id) for step in lesson.steps})
    for section_root in section_roots:
        semantic_ref = f"section:{section_root}"
        layer = layers.setdefault(semantic_ref, {"elements": []})
        layer["stepIds"] = [
            step.id for step in lesson.steps if _scope_root(step.scope_id) == section_root
        ]
        layer["stepStartsWith"] = [
            step.id for step in lesson.steps if _scope_root(step.scope_id) == section_root
        ]
    return layers


def _generated_lesson_shell(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    default_t: float,
) -> JsonObject:
    problem = snapshot.problem or {}
    display = problem.get("display") if isinstance(problem.get("display"), dict) else {}
    title = str(problem.get("title") or snapshot.problem_id)
    lines = _problem_original_lines(problem, snapshot.problem_id)
    section_titles = {section.scope_id: section.title for section in lesson.sections}
    summary = (
        str(display.get("summary") or "").strip()
        or str(problem.get("summary") or "").strip()
        or _problem_summary(
            title=title,
            problem=problem,
            lines=lines,
        )
    )
    page_title = str(display.get("page_title") or "").strip() or _page_title(title, problem)
    breadcrumb_title = str(display.get("breadcrumb_title") or "").strip() or _breadcrumb_title(title)
    return {
        "meta": {
            "id": snapshot.problem_id,
            "outputPath": f"internal/solver-runs/{snapshot.problem_id}.html",
            "pageTitle": page_title,
            "pageDescription": summary,
            "breadcrumbTitle": breadcrumb_title,
            "defaultT": default_t,
            "classification": {
                "pattern": str(problem.get("pattern") or snapshot.family_id),
                "methods": sorted({cap for step in lesson.steps for cap in step.capability_ids}),
            },
        },
        "problem": {
            "summary": summary,
            "lines": _problem_lines_with_answers(
                title=title,
                display=display,
                problem=problem,
                lines=lines,
                answers=snapshot.answers,
            ),
        },
        "ui": {
            "sliderLabel": "参数",
            "paramLabelPrefix": f"{_parameter_name(snapshot)}=",
            "goToProblemMode": "doubleScroll",
            "groupTitles": dict(section_titles),
            "defaultT": default_t,
        },
        "steps": [],
        "policies": {},
        "stepLabels": {},
    }


def _problem_original_lines(problem: JsonObject, problem_id: str) -> list[str]:
    original_text = problem.get("original_text") or []
    if isinstance(original_text, str):
        return [original_text]
    if isinstance(original_text, list):
        return [str(item) for item in original_text if str(item).strip()]
    if isinstance(original_text, dict):
        lines = original_text.get("lines")
        if isinstance(lines, list):
            return [str(item) for item in lines if str(item).strip()]
        text = original_text.get("text")
        if isinstance(text, str) and text.strip():
            return [text.strip()]
    return [problem_id]


def _problem_lines_with_answers(
    *,
    title: str,
    display: JsonObject,
    problem: JsonObject,
    lines: list[str],
    answers: dict[str, Any],
) -> list[JsonObject]:
    normalized_lines = _merge_condition_with_first_subquestion(lines)
    if normalized_lines:
        normalized_lines[0] = _prefix_problem_number(title, display, normalized_lines[0])
    answer_displays = _answer_displays_from_question_goals(problem, answers)
    answer_start = max(0, len(normalized_lines) - len(answer_displays))
    out: list[JsonObject] = []
    for index, line in enumerate(normalized_lines):
        item: JsonObject = {"text": line}
        answer_index = index - answer_start
        if 0 <= answer_index < len(answer_displays):
            answer = answer_displays[answer_index]
            item.update(answer)
        out.append(item)
    return out


def _merge_condition_with_first_subquestion(lines: list[str]) -> list[str]:
    out: list[str] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _is_parent_question_intro(current) and _is_first_child_question(next_line):
            out.append(f"{current.rstrip('。；;，,')}，{next_line}")
            index += 2
            continue
        out.append(current)
        index += 1
    return out


def _is_parent_question_intro(line: str) -> bool:
    text = line.strip()
    return bool(
        re.match(r"^（(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[一二三四五六七八九十]+|\d+)）", text)
    )


def _is_first_child_question(line: str) -> bool:
    text = line.strip()
    return bool(re.match(r"^(?:①|1[.．、]|（1）|\(1\))", text))


def _prefix_problem_number(title: str, display: JsonObject, first_line: str) -> str:
    if re.match(r"^（?\d+）", first_line.strip()):
        return first_line
    number = str(display.get("number") or "").strip() or _problem_number(title)
    if not number:
        return first_line
    score = str(display.get("score") or "").strip()
    score_text = f"（本小题 {score} 分）" if score else ""
    return f"（{number}）{score_text}{first_line}"


def _answer_displays_from_question_goals(
    problem: JsonObject,
    answers: dict[str, Any],
) -> list[JsonObject]:
    out: list[JsonObject] = []
    for goal in problem.get("question_goals") or ():
        if not isinstance(goal, dict):
            continue
        scope_id = str(goal.get("scope_id") or "").strip()
        answer_key = str(goal.get("answer_key") or "").strip()
        value_type = str(goal.get("value_type") or "").strip()
        values = answers.get(scope_id)
        if not scope_id or not answer_key or not isinstance(values, dict):
            continue
        if answer_key not in values:
            continue
        handle = str(goal.get("handle") or f"answer:{scope_id}_{answer_key}")
        out.append(
            {
                "answerId": _answer_dom_id(handle),
                "answer": _student_answer_display(answer_key, values[answer_key], value_type),
            }
        )
    return out


def _answer_dom_id(handle: str) -> str:
    text = str(handle).removeprefix("answer:")
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return f"answer_{text or 'value'}"


def _student_answer_display(answer_key: str, value: Any, value_type: str) -> str:
    if value_type == "Parabola" or answer_key == "parabola":
        return f"y＝{_student_math_expr(value)}"
    if value_type == "Point" or _is_point_value(value):
        point_name = answer_key if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", answer_key) else ""
        point_prefix = point_name or "点"
        return f"{point_prefix}({_student_point_pair(value)})"
    if value_type == "MinimumExpression":
        return f"最小值＝{_student_math_expr(value)}"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", answer_key):
        return f"{answer_key}＝{_student_math_expr(value)}"
    return _student_math_expr(value)


def _problem_summary(*, title: str, problem: JsonObject, lines: list[str]) -> str:
    number = _problem_number(title)
    source = _problem_source(title)
    family = "二次函数综合" if "quadratic" in str(problem.get("problem_type") or "") else "数学综合"
    text = " ".join(lines)
    topics: list[str] = []
    if "解析式" in text:
        topics.append("解析式")
    if "∠" in text or "角" in text:
        topics.append("角度条件")
    path = _path_minimum_text(text)
    if path:
        topics.append(f"{path} 路径最值")
    if not topics:
        topics.append("综合解题")
    prefix = f"第 {number} 题" if number else "本题"
    if source:
        prefix += f"（{source}）"
    topic_text = topics[0] if len(topics) == 1 else f"{'、'.join(topics[:-1])}与{topics[-1]}"
    topic_text = topic_text.replace("与OM", "与 OM")
    return f"{prefix}{family}：{topic_text}。"


def _path_minimum_text(text: str) -> str:
    match = re.search(r"([A-Z]{1,2})\s*[+＋]\s*([A-Z]{1,2}).{0,12}最小值", text)
    if match:
        return f"{match.group(1)}+{match.group(2)}"
    return ""


def _page_title(title: str, problem: JsonObject) -> str:
    base = re.sub(r"第\s*(\d+)\s*题", r"第 \1 题", title).strip()
    if "quadratic" in str(problem.get("problem_type") or "") and "二次函数综合" not in base:
        base = f"{base}（二次函数综合）"
    return base


def _breadcrumb_title(title: str) -> str:
    text = re.sub(r"第\s*(\d+)\s*题", r"第 \1 题", title).strip()
    return re.sub(r"^(\d{4})\s*年\s*", r"\1 ", text).strip()


def _problem_number(title: str) -> str:
    match = re.search(r"第\s*(\d+)\s*题", title)
    return match.group(1) if match else ""


def _problem_source(title: str) -> str:
    match = re.match(r"(.+?)第\s*\d+\s*题", title)
    if not match:
        return ""
    return re.sub(r"^(\d{4})\s*年", r"\1 ", match.group(1).strip())


def _student_point_pair(value: Any) -> str:
    if _is_point_value(value):
        return f"{_student_math_expr(value[0])}, {_student_math_expr(value[1])}"
    return _student_math_expr(value)


def _student_math_expr(value: Any) -> str:
    return student_math_display(value, fullwidth_operators=True)


def _geometry_points_from_snapshot(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    default_t: float,
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, JsonObject]]:
    parameter_name = _parameter_name(snapshot)
    namer = GeometryPointNamer(snapshot=snapshot, lesson=lesson)
    fixed: dict[str, list[str]] = {}
    moving: dict[str, list[str]] = {}
    point_meta: dict[str, JsonObject] = {}

    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        coordinate = entity.get("coordinate")
        definition = str(entity.get("definition") or "")
        if _is_point_value(coordinate):
            fixed.setdefault(label, _page_point_pair(coordinate))
            point_meta.setdefault(
                label,
                {"label": label, "scopeId": str(entity.get("scope_id") or "problem"), "scopeRoot": "problem"},
            )
        elif definition == "coordinate_origin":
            fixed.setdefault(label or "O", ["0", "0"])
            point_meta.setdefault(
                label or "O",
                {"label": label or "O", "scopeId": str(entity.get("scope_id") or "problem"), "scopeRoot": "problem"},
            )

    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        value = item.get("value")
        if not _is_point_value(value):
            continue
        label = namer.point_id_for_fact(item)
        if not label:
            continue
        pair = _page_point_pair(value)
        point_meta[label] = namer.point_meta_for_fact(item)
        if _pair_depends_on_parameter(pair, parameter_name):
            moving[label] = pair
        else:
            fixed[label] = pair

    _move_duplicate_dynamic_points(fixed, moving, parameter_name)
    return dict(sorted(fixed.items())), dict(sorted(moving.items())), dict(sorted(point_meta.items()))


class GeometryPointNamer:
    """Assign stable geometry point ids from canonical labels and visible scope.

    Runtime fact handles are an implementation detail.  The visual id is derived
    from the mathematical point label plus its question scope.  If a problem-level
    point receives different values in different top-level questions, the first
    part uses a scoped suffix such as ``B1`` while the later part can keep ``B``.
    """

    def __init__(self, *, snapshot: ExplanationSnapshot, lesson: LessonIR) -> None:
        self.snapshot = snapshot
        self.lesson = lesson
        self.steps_by_id = {
            str(step.get("step_id")): step
            for step in snapshot.effective_steps
            if isinstance(step, dict) and step.get("step_id")
        }
        self.facts_by_handle = {
            str(fact.get("handle")): fact
            for fact in (snapshot.problem or {}).get("facts") or ()
            if isinstance(fact, dict) and fact.get("handle")
        }
        self.entities_by_handle = {
            str(entity.get("handle")): entity
            for entity in (snapshot.problem or {}).get("entities") or ()
            if isinstance(entity, dict) and entity.get("handle")
        }
        self.problem_point_names = {
            str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
            for entity in (snapshot.problem or {}).get("entities") or ()
            if isinstance(entity, dict)
            and entity.get("entity_type") == "point"
            and str(entity.get("scope_id") or "") == "problem"
        }
        self.label_roots = self._collect_label_roots()
        self.scope_namer = GeometryPointScopeNamer(
            problem_point_names=frozenset(self.problem_point_names),
            label_roots={key: frozenset(value) for key, value in self.label_roots.items()},
        )

    def point_id_for_fact(self, item: dict[str, Any]) -> str:
        label = self._raw_label_for_fact(item)
        if not label:
            return ""
        scope_id = self._visual_scope_for_fact(item)
        return self.scope_namer.geometry_id(label, scope_id)

    def point_meta_for_fact(self, item: dict[str, Any]) -> JsonObject:
        label = self._raw_label_for_fact(item)
        scope_id = self._visual_scope_for_fact(item)
        return self.scope_namer.point_meta(label, scope_id)

    def _collect_label_roots(self) -> dict[str, set[str]]:
        roots: dict[str, set[str]] = {}
        for item in self.snapshot.fact_index.values():
            if not isinstance(item, dict) or item.get("type") != "Point":
                continue
            if not _is_point_value(item.get("value")):
                continue
            label = self._raw_label_for_fact(item)
            if not label:
                continue
            roots.setdefault(label, set()).add(_scope_root(self._visual_scope_for_fact(item)))
        return roots

    def _raw_label_for_fact(self, item: dict[str, Any]) -> str:
        name = str(item.get("name") or "")
        if name == "equal_length_auxiliary_point":
            auxiliary = (
                self._auxiliary_label_from_equal_length_roles(item)
                or self._auxiliary_label_from_equal_length_lesson(item)
            )
            if auxiliary:
                return auxiliary
        source_step_id = self._source_step_id_for_fact(item)
        label = _label_from_effective_step(source_step_id, self.snapshot)
        if label:
            return label
        if name:
            label = _label_from_semantic_name(name)
            if label:
                return label
        return ""

    def _visual_scope_for_fact(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        step = self.steps_by_id.get(source_step_id)
        if isinstance(step, dict) and step.get("scope_id"):
            return str(step["scope_id"])
        return str(item.get("scope_id") or "")

    def _source_step_id_for_fact(self, item: dict[str, Any]) -> str:
        explicit = str(item.get("source_step_id") or "")
        if explicit:
            return explicit
        scope_id = str(item.get("scope_id") or "")
        if scope_id in self.steps_by_id:
            return scope_id
        source_method = str(item.get("source") or "")
        if source_method:
            matches = [
                step_id
                for step_id, step in self.steps_by_id.items()
                if any(
                    trace.method_id == source_method and trace.source_step_id == step_id
                    for trace in self.snapshot.teaching_trace
                )
                and _scope_root(str(step.get("scope_id") or "")) == _scope_root(scope_id)
            ]
            if len(matches) == 1:
                return matches[0]
        return ""

    def _auxiliary_label_from_equal_length_lesson(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        if not source_step_id:
            return ""
        texts = self._equal_length_lesson_texts(source_step_id)
        for text in texts:
            match = re.search(r"构造(?:辅助点|点)?\s*([A-Z][A-Za-z0-9_]*)", text)
            if match:
                return match.group(1)
        for text in texts:
            match = re.search(r"\b([A-Z][A-Za-z0-9_]*)\(", text)
            if match:
                return match.group(1)
        return ""

    def _auxiliary_label_from_equal_length_roles(self, item: dict[str, Any]) -> str:
        source_step_id = self._source_step_id_for_fact(item)
        source_step = self.steps_by_id.get(source_step_id)
        if not source_step or source_step.get("recipe_hint") != "equal_length_ray_path_reduction":
            return ""
        segment_moving = ""
        ray_moving = ""
        anchor = ""
        for handle in source_step.get("reads") or ():
            if not isinstance(handle, str):
                continue
            fact = self.facts_by_handle.get(handle)
            if not fact:
                continue
            fact_type = str(fact.get("type") or "")
            if fact_type == "point_on_segment":
                segment_moving = self._point_label_from_entity_handle(str(fact.get("point") or ""))
            elif fact_type == "point_on_ray":
                ray_moving = self._point_label_from_entity_handle(str(fact.get("point") or ""))
                ray_entity = self.entities_by_handle.get(str(fact.get("ray") or "")) or {}
                anchor = anchor or self._point_label_from_entity_handle(
                    str(ray_entity.get("origin") or "")
                )
            elif fact_type == "equal_length_condition":
                anchor = anchor or _common_label_in_segments(
                    [
                        str(fact.get("left") or ""),
                        str(fact.get("right") or ""),
                    ]
                )
        if not segment_moving:
            return ""

        for text in self._equal_length_lesson_texts(source_step_id):
            for left, right in re.findall(
                r"([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})*)\s*=\s*([A-Z]{2}(?:\s*[+＋]\s*[A-Z]{2})*)",
                text,
            ):
                auxiliary = _auxiliary_label_from_path_equation(
                    left,
                    right,
                    segment_moving=segment_moving,
                    ray_moving=ray_moving,
                    anchor=anchor,
                )
                if auxiliary:
                    return auxiliary
        return ""

    def _equal_length_lesson_texts(self, source_step_id: str) -> list[str]:
        texts: list[str] = []
        for step in self.lesson.steps:
            if source_step_id not in step.source_step_ids:
                continue
            if "equal_length_ray_path_reduction" not in step.capability_ids:
                continue
            texts.append(step.title)
            texts.extend(text for _tag, text in step.derive)
            texts.extend(step.box)
        return texts

    def _point_label_from_entity_handle(self, handle: str) -> str:
        entity = self.entities_by_handle.get(handle) or {}
        return str(entity.get("name") or _handle_tail(handle))


def _label_from_effective_step(step_id: str, snapshot: ExplanationSnapshot) -> str:
    if not step_id:
        return ""
    for step in snapshot.effective_steps:
        if not isinstance(step, dict) or step.get("step_id") != step_id:
            continue
        target = str(step.get("target") or "")
        labels = _point_labels_from_handle_text(target)
        if len(labels) == 1:
            return next(iter(labels))
        for produced in step.get("produces") or ():
            if not isinstance(produced, dict):
                continue
            labels = _point_labels_from_handle_text(str(produced.get("handle") or ""))
            if len(labels) == 1:
                return next(iter(labels))
            description_labels = _capital_point_labels(str(produced.get("description") or ""))
            if len(description_labels) == 1:
                return next(iter(description_labels))
    return ""


def _label_from_semantic_name(name: str) -> str:
    labels = _point_labels_from_handle_text(name)
    return next(iter(labels)) if len(labels) == 1 else ""


def _move_duplicate_dynamic_points(
    fixed: dict[str, list[str]],
    moving: dict[str, list[str]],
    parameter_name: str,
) -> None:
    for label in list(fixed):
        pair = fixed[label]
        if _pair_depends_on_parameter(pair, parameter_name):
            moving[label] = fixed.pop(label)


def _auxiliary_label_from_path_equation(
    left: str,
    right: str,
    *,
    segment_moving: str,
    ray_moving: str,
    anchor: str = "",
) -> str:
    left_terms = _segment_terms(left)
    right_terms = _segment_terms(right)
    if not left_terms or not right_terms:
        return ""

    common_terms = set(left_terms).intersection(right_terms)
    reduced_terms: list[str] = []
    if ray_moving and any(ray_moving in term for term in left_terms):
        reduced_terms = right_terms
    elif ray_moving and any(ray_moving in term for term in right_terms):
        reduced_terms = left_terms
    else:
        for terms in (left_terms, right_terms):
            candidates = [
                term
                for term in terms
                if term not in common_terms and segment_moving in term
            ]
            if candidates:
                reduced_terms = terms
                break

    for term in reduced_terms:
        if term in common_terms or segment_moving not in term:
            continue
        auxiliary = _other_endpoint(term, segment_moving)
        if auxiliary and auxiliary != anchor:
            return auxiliary
    return ""


def _segment_terms(value: str) -> list[str]:
    return re.findall(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", value or "")


def _common_label_in_segments(segments: list[str]) -> str:
    labels = [set(_capital_point_labels(segment)) for segment in segments if segment]
    if len(labels) < 2:
        return ""
    common = set.intersection(*labels)
    return next(iter(common), "")


def _other_endpoint(segment: str, endpoint: str) -> str:
    if len(segment) != 2 or endpoint not in segment:
        return ""
    return segment[0] if segment[1] == endpoint else segment[1]


def _curves_from_snapshot(snapshot: ExplanationSnapshot) -> list[JsonObject]:
    steps_by_id = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    curves_by_key: dict[tuple[str, tuple[str, str, str]], tuple[dict[str, Any], tuple[str, str, str], int]] = {}
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Parabola":
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        coeffs = _parabola_coefficients(value)
        if coeffs is None:
            continue
        scope_id = _curve_scope_for_fact(item, steps_by_id)
        key = (_scope_root(scope_id), coeffs)
        rank = _curve_fact_rank(item)
        if key in curves_by_key and curves_by_key[key][2] >= rank:
            continue
        curves_by_key[key] = (item, coeffs, rank)

    curves_by_id: dict[str, JsonObject] = {}
    for item, coeffs, _rank in curves_by_key.values():
        scope_id = _curve_scope_for_fact(item, steps_by_id)
        curve_id = _curve_id_for_fact(item, scope_id, curves_by_id)
        curves_by_id[curve_id] = {
            "id": curve_id,
            "type": "parabola",
            "scopeId": scope_id,
            "scopeRoot": _scope_root(scope_id),
            "sourceHandle": str(item.get("handle") or ""),
            "a": coeffs[0],
            "b": coeffs[1],
            "c": coeffs[2],
        }
    return list(curves_by_id.values())


def _curve_scope_for_fact(item: dict[str, Any], steps_by_id: dict[str, dict[str, Any]]) -> str:
    source_step_id = str(item.get("source_step_id") or "")
    if source_step_id in steps_by_id:
        return str(steps_by_id[source_step_id].get("scope_id") or item.get("scope_id") or "")
    scope_id = str(item.get("scope_id") or "")
    if scope_id in steps_by_id:
        return str(steps_by_id[scope_id].get("scope_id") or scope_id)
    handle = str(item.get("handle") or "")
    match = re.match(r"runtime:([^:]+):", handle)
    if match and match.group(1) in steps_by_id:
        return str(steps_by_id[match.group(1)].get("scope_id") or scope_id)
    return scope_id


def _curve_fact_rank(item: dict[str, Any]) -> int:
    handle = str(item.get("handle") or "")
    if ":outputs:" in handle:
        return 3
    if handle.startswith("fact:") or handle.startswith("answer:"):
        return 2
    if ":temp:" in handle:
        return 1
    return 0


def _curve_id_for_fact(item: dict[str, Any], scope_id: str, existing: dict[str, JsonObject]) -> str:
    scope_root = _scope_root(scope_id or "problem")
    raw_name = str(item.get("name") or _handle_tail(str(item.get("handle") or "")) or "parabola")
    semantic = re.sub(r"[^A-Za-z0-9_]+", "_", raw_name).strip("_") or "parabola"
    if "parabola" not in semantic.lower():
        semantic = f"{semantic}_parabola"
    base = f"curve_{scope_root}_{semantic}"
    candidate = base
    index = 2
    while candidate in existing:
        index += 1
        candidate = f"{base}_{index}"
    return candidate


def _parabola_coefficients(expression: str) -> tuple[str, str, str] | None:
    try:
        import sympy as sp

        x = sp.Symbol("x")
        expr = sp.sympify(expression)
        poly = sp.Poly(expr, x)
        return tuple(_page_expr(poly.coeff_monomial(x ** power)) for power in (2, 1, 0))  # type: ignore[return-value]
    except Exception:
        return None


def _domain_from_geometry_points(
    fixed_points: dict[str, list[str]],
    moving_points: dict[str, list[str]],
    parameter_name: str,
    default_t: float,
) -> JsonObject:
    samples: list[tuple[float, float]] = []
    env = {parameter_name: default_t}
    for pair in [*fixed_points.values(), *moving_points.values()]:
        point = _evaluate_page_pair(pair, env)
        if point is not None:
            samples.append(point)
    if not samples:
        return {"minX": -5.0, "maxX": 5.0, "minY": -5.0, "maxY": 5.0}
    xs = [point[0] for point in samples]
    ys = [point[1] for point in samples]
    x_span = max(max(xs) - min(xs), 1.0)
    y_span = max(max(ys) - min(ys), 1.0)
    margin = max(0.8, min(1.8, max(x_span, y_span) * 0.18))
    return {
        "minX": round(min(xs) - margin, 3),
        "maxX": round(max(xs) + margin, 3),
        "minY": round(min(ys) - margin, 3),
        "maxY": round(max(ys) + margin, 3),
    }


def _base_elements_for_section(
    section_scope: str,
    geometry_spec: JsonObject,
    *,
    snapshot: ExplanationSnapshot,
    index: VisualGeometryIndex,
) -> list[JsonObject]:
    elements: list[JsonObject] = []
    for curve_id in _curve_ids_for_section(geometry_spec, section_scope):
        elements.append(
            {
                "type": "parabola",
                "curveId": curve_id,
                "color": COLOR_CURVE,
                "width": 2.2,
            }
        )
    elements.extend(_base_relation_elements(section_scope, snapshot, index))
    elements.extend(_base_point_elements(section_scope, snapshot, index))
    return _dedupe_low_level_elements(elements)


def _curve_ids_for_section(geometry_spec: JsonObject, section_scope: str) -> list[str]:
    out: list[str] = []
    for curve in geometry_spec.get("curves") or ():
        if not isinstance(curve, dict) or not curve.get("id"):
            continue
        scope_root = str(curve.get("scopeRoot") or _scope_root(str(curve.get("scopeId") or "")))
        if scope_root == section_scope:
            out.append(str(curve["id"]))
    return out


def _base_relation_elements(
    section_scope: str,
    snapshot: ExplanationSnapshot,
    index: VisualGeometryIndex,
) -> list[JsonObject]:
    elements: list[JsonObject] = []
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or not _entity_visible_in_section(entity, section_scope):
            continue
        entity_type = str(entity.get("entity_type") or "")
        if entity_type == "segment":
            points = _relation_endpoint_points(entity.get("endpoints"), section_scope, index)
            if points is None or not _relation_uses_problem_points(entity, index):
                continue
            start, end = points
            elements.append(
                {
                    "type": "coloredLine",
                    "from": start,
                    "to": end,
                    "color": COLOR_MUTED,
                    "width": 1.6,
                }
            )
        elif entity_type == "ray":
            points = _relation_endpoint_points(
                (entity.get("origin"), entity.get("through")),
                section_scope,
                index,
            )
            if points is None or not _relation_uses_problem_points(entity, index):
                continue
            origin, through = points
            elements.append(
                {
                    "type": "coloredLine",
                    "from": origin,
                    "to": through,
                    "color": COLOR_MUTED,
                    "width": 1.4,
                }
            )
    return elements


def _base_point_elements(
    section_scope: str,
    snapshot: ExplanationSnapshot,
    index: VisualGeometryIndex,
) -> list[JsonObject]:
    elements: list[JsonObject] = []
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        if str(entity.get("scope_id") or "problem") != "problem":
            continue
        if entity.get("definition") == "coordinate_origin":
            continue
        geometry_id = index.point_for_entity(entity, section_scope)
        if not geometry_id:
            continue
        label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        elements.append(
            {
                "type": "point",
                "at": geometry_id,
                "labelText": label,
                "color": COLOR_MUTED if geometry_id in (index.geometry_spec.get("movingPoints") or {}) else COLOR_TEXT,
                "dx": 10,
                "dy": -12,
            }
        )
    return elements


def _entity_visible_in_section(entity: dict[str, Any], section_scope: str) -> bool:
    scope_id = str(entity.get("scope_id") or "problem")
    if scope_id == "problem":
        return True
    return _scope_root(scope_id) == section_scope


def _relation_endpoint_points(
    raw_endpoints: Any,
    section_scope: str,
    index: VisualGeometryIndex,
) -> tuple[str, str] | None:
    if not isinstance(raw_endpoints, (list, tuple)) or len(raw_endpoints) != 2:
        return None
    start = index.point_for_handle(str(raw_endpoints[0]), section_scope)
    end = index.point_for_handle(str(raw_endpoints[1]), section_scope)
    if not start or not end:
        return None
    return (start, end)


def _relation_uses_problem_points(entity: dict[str, Any], index: VisualGeometryIndex) -> bool:
    handles: list[str] = []
    endpoints = entity.get("endpoints")
    if isinstance(endpoints, list):
        handles.extend(str(item) for item in endpoints)
    for key in ("origin", "through"):
        if entity.get(key):
            handles.append(str(entity[key]))
    for handle in handles:
        point = index.entities_by_handle.get(handle)
        if point is None or point.get("entity_type") != "point":
            return False
        if str(point.get("scope_id") or "problem") != "problem":
            return False
    return bool(handles)


def _dedupe_low_level_elements(elements: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    out: list[JsonObject] = []
    for item in elements:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        line_key = ""
        if item.get("type") == "coloredLine":
            endpoints = sorted([str(item.get("from") or ""), str(item.get("to") or "")])
            line_key = f"coloredLine:{endpoints[0]}:{endpoints[1]}"
        key = line_key or key
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _parameter_name(snapshot: ExplanationSnapshot) -> str:
    for item in snapshot.fact_index.values():
        if isinstance(item, dict) and item.get("type") == "ParameterValue":
            name = str(item.get("name") or "")
            if name:
                return name
            handle = str(item.get("handle") or "")
            if handle:
                return handle.rsplit(":", 1)[-1]
    return "t"


def _parameter_default_value(snapshot: ExplanationSnapshot) -> float:
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "ParameterValue":
            continue
        try:
            import sympy as sp

            return float(sp.N(sp.sympify(str(item.get("value")))))
        except Exception:
            continue
    return 0.75


def _page_point_pair(value: Any) -> list[str]:
    return [_page_expr(value[0]), _page_expr(value[1])]


def _page_expr(value: Any) -> str:
    text = str(value).strip()
    try:
        import sympy as sp

        text = str(sp.simplify(sp.sympify(text)))
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


def _evaluate_page_pair(pair: list[str], env: dict[str, float]) -> tuple[float, float] | None:
    try:
        import sympy as sp

        locals_ = {"abs": sp.Abs, "sqrt": sp.sqrt}
        substitutions = {sp.Symbol(key): value for key, value in env.items()}
        x = sp.sympify(str(pair[0]).replace("^", "**"), locals=locals_).subs(substitutions)
        y = sp.sympify(str(pair[1]).replace("^", "**"), locals=locals_).subs(substitutions)
        return (float(sp.N(x)), float(sp.N(y)))
    except Exception:
        return None


def _pair_depends_on_parameter(pair: list[str], parameter_name: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(parameter_name)}(?![A-Za-z0-9_])")
    return any(pattern.search(str(part)) for part in pair)


def _handle_tail(handle: str) -> str:
    return handle.rsplit(":", 1)[-1].split(".", 1)[-1]


def _visual_step_for_lesson_step(
    lesson_step: LessonStep,
    *,
    snapshot: ExplanationSnapshot,
    geometry_spec: JsonObject,
    bindings: VisualRoleBindings,
) -> VisualStep:
    interactions = ParametricExpressionResolver(
        geometry_spec=geometry_spec,
        default_t=_parameter_default_value(snapshot),
    ).interactions_for_step(lesson_step, bindings)
    timeline = AnimationTimelineBuilder().timeline_for_step(
        lesson_step,
        bindings,
        interactions=interactions,
    )
    scene_add = _scene_add_for_lesson_step(
        lesson_step,
        bindings,
        coordinate_texts=_verified_coordinate_texts_for_lesson_step(
            lesson_step,
            snapshot,
        ),
    )
    scene = {
        "inherits_from": f"section:{_scope_root(lesson_step.scope_id)}",
        "add": scene_add,
        "state_overrides": _state_overrides_for_lesson_step(lesson_step),
        "hide": [],
        "focus": {
            "primary": _focus_handles(scene_add),
            "dim": [],
        },
        "annotations": _annotations_for_lesson_step(lesson_step),
    }
    return VisualStep(
        visual_step_id=f"visual:{lesson_step.id}",
        lesson_step_id=lesson_step.id,
        scope_id=lesson_step.scope_id,
        geometry_context={
            "coordinate_system": "cartesian_2d",
            "domain": copy.deepcopy(geometry_spec.get("domain") or {}),
            "domain_override": None,
            "moving_param": geometry_spec.get("movingParam"),
            "expression_env_handles": _expression_env_handles(geometry_spec.get("expressionEnv")),
            "panels": [],
        },
        scene=scene,
        interactions=interactions,
        timeline=timeline,
        metadata={"step_extra": {}},
    )


def _scene_add_for_lesson_step(
    lesson_step: LessonStep,
    bindings: VisualRoleBindings,
    *,
    coordinate_texts: dict[str, str] | None = None,
) -> list[JsonObject]:
    context = _SceneBuildContext(
        lesson_step=lesson_step,
        bindings=bindings,
        coordinate_texts=coordinate_texts,
        capabilities=frozenset(lesson_step.capability_ids),
        substeps=frozenset(lesson_step.teaching_substep_ids),
    )
    add = _scene_items_from_visual_specs(context)
    if not add:
        add = [_visual_gap("visual_role", "No static visual spec matched this Lesson step.")]
    return _dedupe_scene_items(add)


def _scene_items_from_visual_specs(context: _SceneBuildContext) -> list[JsonObject]:
    template_items = (
        *_method_visual_template_items(context.capabilities, context.bindings),
        *_recipe_visual_template_items(context.capabilities, context.substeps, context.bindings),
    )
    context = replace(context, template_items=tuple(template_items))
    add: list[JsonObject] = list(template_items)
    for rule in _scene_visual_rules():
        if rule.applies(context):
            add.extend(rule.handler(context))
    return add


def _quadratic_from_constraints_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_parabola_items(context.bindings),
        *_coordinate_labels(
            context.points,
            (*context.lesson_step.box, *_derive_texts(context.lesson_step)),
            context.coordinate_texts,
        ),
    ]


def _coordinate_result_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return _coordinate_labels(context.points, context.lesson_step.box, context.coordinate_texts)


def _angle_sum_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_point_items_for_geometry_refs(
            context,
            _point_marker_refs_from_scene_items(context.template_items),
            style=POINT_ACTIVE,
        ),
        *_coordinate_labels(
            context.points,
            (*context.lesson_step.box, *_derive_texts(context.lesson_step)),
            context.coordinate_texts,
        ),
    ]


def _axis_intercept_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_point_items_for_geometry_refs(
            context,
            _point_marker_refs_from_scene_items(context.template_items),
            style=POINT_ACTIVE,
        ),
        *_point_items_for_coordinate_conclusions(
            context,
            context.lesson_step.box,
            style=POINT_RESULT,
        ),
        *_coordinate_labels(context.points, context.lesson_step.box, context.coordinate_texts),
    ]


def _line_parabola_intersection_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return [
        *_line_if_points(
            context.points,
            "B",
            "E",
            color=COLOR_ACCENT,
            width=2.2,
            handle=_angle_arm_handle(context.lesson_step.scope_id, "BE"),
            state="highlight",
        ),
        *_point_items(context.points, ("E",), style=POINT_RESULT),
        *_point_items(context.points, ("F",), style=POINT_ACTIVE),
        *_coordinate_labels(context.points, context.lesson_step.box, context.coordinate_texts),
    ]


def _equal_length_reduction_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return []


def _minimum_distance_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return _minimum_distance_items(context)


def _parameter_result_visual_items(context: _SceneBuildContext) -> list[JsonObject]:
    return _parameter_result_items(
        context.points,
        context.lesson_step.box,
        context.coordinate_texts,
    )


@lru_cache(maxsize=1)
def _scene_visual_rules() -> tuple[_SceneVisualRule, ...]:
    return (
        _SceneVisualRule(
            capability_ids=("quadratic_from_constraints",),
            handler=_quadratic_from_constraints_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=(
                "quadratic_y_axis_intercept_point",
                "translated_point",
                "quadratic_x_axis_intercept_point",
            ),
            handler=_coordinate_result_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("angle_sum_equal_angle_candidates",),
            handler=_angle_sum_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("axis_intercept_from_equal_acute_angles",),
            handler=_axis_intercept_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("line_parabola_second_intersection_point",),
            handler=_line_parabola_intersection_visual_items,
        ),
        _SceneVisualRule(
            substep_ids=("path_reduction",),
            recipe_without_substeps=("equal_length_ray_path_reduction",),
            handler=_equal_length_reduction_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("distance_between_points",),
            substep_ids=("minimum_by_segment",),
            recipe_without_substeps=("equal_length_ray_path_reduction",),
            handler=_minimum_distance_visual_items,
        ),
        _SceneVisualRule(
            capability_ids=("parameter_from_expression_value", "parameter_from_minimum_value"),
            handler=_parameter_result_visual_items,
        ),
    )


def _method_visual_template_items(
    capabilities: set[str],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for capability_id in sorted(capabilities):
        spec = _method_visual_spec(capability_id)
        if spec is None:
            continue
        for template in spec.scene_templates:
            if template.get("component") == "TranslationMarker":
                items.extend(_translation_marker_items(template, bindings))
            elif template.get("component") == "AngleEqualityMarker":
                items.extend(_angle_equality_marker_items(template, bindings))
                items.extend(_angle_reference_items(bindings))
            elif template.get("component") == "EqualAcuteAngleInterceptMarker":
                items.extend(_equal_acute_angle_intercept_marker_items(template, bindings))
    return items


def _recipe_visual_template_items(
    capabilities: set[str],
    substeps: set[str],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for capability_id in sorted(capabilities):
        spec = _recipe_visual_spec(capability_id)
        if spec is None:
            continue
        visual = spec.visual
        if visual is None:
            continue
        template_keys = sorted(substeps) if substeps else sorted(visual.teaching_substep_templates)
        for substep_id in template_keys:
            for template in visual.teaching_substep_templates.get(substep_id, ()):
                component = template.get("component")
                if component == "CongruentTriangleMarker":
                    items.extend(_congruent_triangle_marker_items(template, bindings))
                elif component == "EquivalentSegmentMarker":
                    items.extend(_equivalent_segment_marker_items(template, bindings))
                elif component == "PathMinimumTriangleMarker":
                    items.extend(_path_minimum_triangle_marker_items(template, bindings))
                elif component == "AuxiliaryRayGuideMarker":
                    items.extend(_auxiliary_ray_guide_marker_items(template, bindings))
    return items


@lru_cache(maxsize=1)
def _method_spec_registry() -> MethodSpecRegistry:
    return MethodSpecRegistry.load_from_code()


def _method_visual_spec(method_id: str):
    try:
        return _method_spec_registry().require(method_id).visual
    except KeyError:
        return None


@lru_cache(maxsize=1)
def _recipe_spec_registry() -> RecipeSpecRegistry:
    return RecipeSpecRegistry.load_from_code()


def _recipe_visual_spec(recipe_id: str):
    return _recipe_spec_registry().get(recipe_id)


def _translation_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    source_role = str(template.get("source_role") or "source_point")
    target_role = str(template.get("target_role") or "target_point")
    vector_role = str(template.get("vector_role") or "vector")
    for marker in bindings.translation_markers:
        source = str(marker.get(source_role) or "")
        target = str(marker.get(target_role) or "")
        vector = marker.get(vector_role)
        if not source or not target:
            continue
        items.append(
            {
                "component": "TranslationMarker",
                "source": source,
                "target": target,
                "vector": list(vector) if isinstance(vector, list) else [],
                "label": _translation_label(vector),
                "color": COLOR_CONSTRAINT,
                "width": 1.8,
                "dash": "5 5",
                "dx": 16,
                "dy": -10,
                "persistence": str(template.get("persistence") or "step_only"),
            }
        )
    return items


def _congruent_triangle_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        triangles = [
            dict(triangle)
            for triangle in marker.get("triangles") or ()
            if isinstance(triangle, dict)
        ]
        if triangles:
            items.append(
                {
                    "component": "CongruentTriangleMarker",
                    "triangles": triangles,
                    "fill": str(template.get("fill") or "rgba(14, 165, 233, 0.10)"),
                    "color": str(template.get("color") or "rgba(14, 165, 233, 0.34)"),
                    "width": float(template.get("width") or 1.0),
                    "dash": str(template.get("dash") or ""),
                    "state": "muted",
                    "persistence": "step_only",
                }
            )
        for line in marker.get("path_lines") or ():
            if isinstance(line, dict):
                items.append(
                    {
                        "component": "ColoredLine",
                        "handle": _line_handle(line),
                        "from": line.get("from"),
                        "to": line.get("to"),
                        "color": COLOR_PATH,
                        "width": 2.2,
                        "persistence": "carry_forward",
                        "decay_state": "muted",
                        "metadata": {"low_level_type": "coloredLine"},
                    }
                )
        for line in marker.get("guide_lines") or ():
            if not isinstance(line, dict):
                continue
            component = "DashedLine" if line.get("style") == "dashed" else "ColoredLine"
            carry = line.get("role") == "anchor_to_auxiliary"
            item: JsonObject = {
                "component": component,
                "from": line.get("from"),
                "to": line.get("to"),
                "color": COLOR_MUTED if component == "DashedLine" else COLOR_CONSTRAINT,
                "width": 1.35 if component == "DashedLine" else 2.0,
                "dash": "5 6",
                "persistence": "carry_forward" if carry else "step_only",
                "metadata": {
                    "low_level_type": "dashedLine" if component == "DashedLine" else "coloredLine"
                },
            }
            if carry:
                item["handle"] = _line_handle(line)
                item["decay_state"] = "muted"
            items.append(item)
        for raw_label in marker.get("point_labels") or ():
            if isinstance(raw_label, dict):
                label = str(raw_label.get("label") or "")
                role = str(raw_label.get("role") or "")
            else:
                label = str(raw_label)
                role = ""
            point_refs = marker.get("role_point_refs") if isinstance(marker.get("role_point_refs"), dict) else {}
            point = bindings.point_handles.get(label) or point_refs.get(label)
            if not point:
                continue
            style = _point_style_for_role(role)
            items.append(
                {
                    "component": "Point",
                    "handle": f"point:{point}",
                    "at": point,
                    "labelText": label,
                    "color": style.color,
                    "dx": style.dx,
                    "dy": style.dy,
                    "persistence": "carry_forward",
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "point"},
                }
            )
    return items


def _point_style_for_role(role: str) -> _PointVisualStyle:
    if role == "auxiliary_point":
        return POINT_AUXILIARY
    if role == "result_point":
        return POINT_RESULT
    if role == "moving_point":
        return POINT_MOVING
    return POINT_ACTIVE


def _equivalent_segment_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        segments = [
            dict(segment)
            for segment in marker.get("equivalent_segments") or ()
            if isinstance(segment, dict)
        ]
        if len(segments) < 2:
            continue
        items.append(
            {
                "component": "EquivalentSegmentMarker",
                "segments": segments,
                "label": str(template.get("label") or marker.get("equivalence_label") or ""),
                "color": str(template.get("color") or COLOR_ACCENT),
                "width": float(template.get("width") or 2.25),
                "dx": int(template.get("dx") or 12),
                "dy": int(template.get("dy") or -16),
                "persistence": "step_only",
            }
        )
    return items


def _path_minimum_triangle_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        roles = marker.get("roles") if isinstance(marker.get("roles"), dict) else {}
        point_refs = (
            marker.get("role_point_refs")
            if isinstance(marker.get("role_point_refs"), dict)
            else {}
        )
        vertices = [
            point_refs.get(str(roles.get("fixed_point") or "")),
            point_refs.get(str(roles.get("segment_moving_point") or "")),
            point_refs.get(str(roles.get("auxiliary_point") or "")),
        ]
        if not all(vertices):
            continue
        items.append(
            {
                "component": "OutlineRegion",
                "handle": f"visual:path_minimum_triangle:{'-'.join(str(vertex) for vertex in vertices)}",
                "vertices": vertices,
                "fill": str(template.get("fill") or "rgba(180, 83, 9, 0.10)"),
                "color": str(template.get("color") or "rgba(180, 83, 9, 0.25)"),
                "width": float(template.get("width") or 1.0),
                "dash": str(template.get("dash") or ""),
                "persistence": "step_only",
                "metadata": {"low_level_type": "outlineRegion"},
            }
        )
    return items


def _auxiliary_ray_guide_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.equal_length_path_markers:
        for line in marker.get("guide_lines") or ():
            if not isinstance(line, dict) or line.get("role") != "anchor_to_auxiliary":
                continue
            items.append(
                {
                    "component": "ColoredLine",
                    "handle": _line_handle(line),
                    "from": line.get("from"),
                    "to": line.get("to"),
                    "color": str(template.get("color") or COLOR_CONSTRAINT),
                    "width": float(template.get("width") or 2.0),
                    "dash": str(template.get("dash") or "5 6"),
                    "persistence": "carry_forward",
                    "decay_state": "muted",
                    "metadata": {"low_level_type": "coloredLine"},
                }
            )
    return items


def _angle_equality_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in bindings.angle_equalities:
        angles = marker.get("angles")
        if not isinstance(angles, list) or len(angles) < 2:
            continue
        items.append(
            {
                "component": "AngleEqualityMarker",
                "angles": [dict(angle) for angle in angles if isinstance(angle, dict)],
                "guide_arms": [
                    _angle_guide_arm_payload(guide)
                    for guide in marker.get("guide_arms") or ()
                    if isinstance(guide, dict)
                ],
                "guide_only_refs": list(marker.get("guide_only_refs") or ()),
                "label": str(template.get("label") or "α"),
                "color": COLOR_PATH,
                "guideColor": COLOR_MUTED,
                "radius": 34,
                "labelRadius": 48,
                "guideWidth": 1.25,
                "guideDash": "4 7",
                "state": "muted",
                "persistence": "step_only",
            }
        )
        items.extend(_carry_forward_angle_guide_arm_items(marker))
    return items


def _carry_forward_angle_guide_arm_items(marker: JsonObject) -> list[JsonObject]:
    out: list[JsonObject] = []
    for guide in marker.get("guide_arms") or ():
        if not isinstance(guide, dict):
            continue
        handle = str(guide.get("handle") or "")
        start = str(guide.get("from") or "")
        end = str(guide.get("to") or "")
        if not handle or not start or not end:
            continue
        out.append(
            {
                "component": "DashedLine",
                "handle": handle,
                "from": start,
                "to": end,
                "color": COLOR_MUTED,
                "width": 1.25,
                "dash": "4 7",
                "state": "muted",
                "persistence": "carry_forward",
                "decay_state": "muted",
                "metadata": {"low_level_type": "dashedLine"},
            }
        )
    return out


def _angle_reference_items(bindings: VisualRoleBindings) -> list[JsonObject]:
    out: list[JsonObject] = []
    for marker in bindings.angle_references:
        out.append(
            {
                "component": "AngleArc",
                "vertex": marker.get("vertex"),
                "rayA": marker.get("rayA"),
                "rayB": marker.get("rayB"),
                "color": COLOR_CONSTRAINT,
                "radius": 43,
                "label": marker.get("value") or "45°",
                "labelRadius": 60,
                "metadata": {"low_level_type": "angleArc"},
            }
        )
    return out


def _equal_acute_angle_intercept_marker_items(
    template: dict[str, Any],
    bindings: VisualRoleBindings,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    show_angles = bool(template.get("show_angles", True))
    show_right_angles = bool(template.get("show_right_angles", True))
    for marker in bindings.axis_intercept_markers:
        triangle_regions: list[JsonObject] = []
        lines: list[JsonObject] = []
        angles: list[JsonObject] = []
        right_angles: list[JsonObject] = []
        for equality in marker.get("angle_equalities") or ():
            if not isinstance(equality, dict):
                continue
            target_angle = str(equality.get("left_angle") or "")
            for guide in equality.get("guide_arms") or ():
                if not isinstance(guide, dict):
                    continue
                handle = str(guide.get("handle") or "")
                is_target_line = str(guide.get("angle_name") or "") == target_angle
                lines.append(
                    {
                        "handle": handle,
                        "from": guide.get("from"),
                        "to": guide.get("to"),
                        "style": "solid" if is_target_line else "dashed",
                        "color": COLOR_ACCENT if is_target_line else COLOR_MUTED,
                        "width": 2.2 if is_target_line else 1.35,
                        "dash": "4 7",
                        "show_endpoint_refs": list(guide.get("show_endpoint_refs") or ()),
                    }
                )
            if show_angles:
                for angle in equality.get("angles") or ():
                    if isinstance(angle, dict):
                        angles.append(dict(angle))
        for side in marker.get("axis_sides") or ():
            if not isinstance(side, dict):
                continue
            lines.append(
                {
                    "handle": side.get("handle"),
                    "from": side.get("from"),
                    "to": side.get("to"),
                    "style": "solid",
                    "color": COLOR_MUTED,
                    "width": 1.25,
                }
            )
        for angle in marker.get("right_angles") or ():
            if not isinstance(angle, dict):
                continue
            if show_right_angles:
                right_angles.append(dict(angle))
            vertices = [
                str(angle.get("rayA") or ""),
                str(angle.get("vertex") or ""),
                str(angle.get("rayB") or ""),
            ]
            if all(vertices):
                triangle_regions.append(
                    {
                        "vertices": vertices,
                        "fill": "rgba(124, 58, 237, 0.10)",
                        "color": "rgba(124, 58, 237, 0.28)",
                        "width": 1.0,
                        "dash": "",
                    }
                )
        if not lines and not angles and not right_angles:
            continue
        items.append(
            {
                "component": "EqualAcuteAngleInterceptMarker",
                "triangle_regions": triangle_regions,
                "lines": lines,
                "angles": angles,
                "right_angles": right_angles,
                "label": str(template.get("label") or "α"),
                "color": COLOR_PATH,
                "rightAngleColor": COLOR_CONSTRAINT,
                "rightAngleSize": 10,
                "state": "highlight",
                "persistence": "step_only",
            }
        )
    return items


def _angle_guide_arm_payload(guide: dict[str, Any]) -> JsonObject:
    return {
        "handle": guide.get("handle"),
        "from": guide.get("from"),
        "to": guide.get("to"),
        "guide_only_refs": list(guide.get("guide_only_refs") or ()),
        "show_endpoint_refs": list(guide.get("show_endpoint_refs") or ()),
    }


def _parabola_items(bindings: VisualRoleBindings) -> list[JsonObject]:
    items: list[JsonObject] = []
    for curve_id in bindings.curve_ids:
        items.append(
            {
                "component": "Parabola",
                "curveId": curve_id,
                "color": COLOR_CURVE,
                "width": 2.4,
                "metadata": {"low_level_type": "parabola"},
            }
        )
    return items


def _point_items(
    points: dict[str, str],
    preferred: tuple[str, ...],
    *,
    style: _PointVisualStyle = POINT_ACTIVE,
) -> list[JsonObject]:
    out: list[JsonObject] = []
    for label in preferred:
        at = points.get(label)
        if not at:
            continue
        out.append(
            {
                "component": "Point",
                "handle": f"point:{at}",
                "at": at,
                "labelText": label,
                "color": style.color,
                "dx": style.dx,
                "dy": style.dy,
                "persistence": "carry_forward",
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
    return out


def _point_items_for_geometry_refs(
    context: _SceneBuildContext,
    refs: set[str],
    *,
    style: _PointVisualStyle = POINT_ACTIVE,
) -> list[JsonObject]:
    labels_by_ref = {geometry_ref: label for label, geometry_ref in context.points.items()}
    out: list[JsonObject] = []
    for ref in sorted(refs):
        label = labels_by_ref.get(ref)
        if not label:
            continue
        out.append(
            {
                "component": "Point",
                "handle": f"point:{ref}",
                "at": ref,
                "labelText": label,
                "color": style.color,
                "dx": style.dx,
                "dy": style.dy,
                "persistence": "carry_forward",
                "decay_state": "muted",
                "metadata": {"low_level_type": "point"},
            }
        )
    return out


def _point_items_for_coordinate_conclusions(
    context: _SceneBuildContext,
    boxes: tuple[str, ...],
    *,
    style: _PointVisualStyle = POINT_RESULT,
) -> list[JsonObject]:
    labels = _labels_with_coordinate_text(context.points, boxes, context.coordinate_texts)
    return _point_items(context.points, tuple(sorted(labels)), style=style)


def _labels_with_coordinate_text(
    points: dict[str, str],
    boxes: tuple[str, ...],
    coordinate_texts: dict[str, str] | None = None,
) -> set[str]:
    text = " ".join(boxes)
    labels: set[str] = set()
    for label in points:
        if (coordinate_texts or {}).get(label) or _coordinate_for_label(label, text):
            labels.add(label)
    return labels


def _point_marker_refs_from_scene_items(items: tuple[JsonObject, ...]) -> set[str]:
    refs: set[str] = set()

    def visit(item: Any) -> None:
        if not isinstance(item, dict):
            return
        for key in ("guide_only_refs", "show_endpoint_refs"):
            for ref in item.get(key) or ():
                if isinstance(ref, str) and ref:
                    refs.add(ref)
        for key in (
            "angles",
            "guide_arms",
            "lines",
            "right_angles",
            "triangle_regions",
            "triangles",
            "segments",
        ):
            for nested in item.get(key) or ():
                visit(nested)

    for item in items:
        visit(item)
    return refs


def _coordinate_labels(
    points: dict[str, str],
    boxes: tuple[str, ...],
    coordinate_texts: dict[str, str] | None = None,
) -> list[JsonObject]:
    out: list[JsonObject] = []
    text = " ".join(boxes)
    for label, at in sorted(points.items()):
        coordinate = (coordinate_texts or {}).get(label) or _coordinate_for_label(label, text)
        if not coordinate:
            continue
        if _is_origin_coordinate_label(label, coordinate):
            continue
        out.append(
            {
                "component": "CoordinateLabel",
                "at": at,
                "text": coordinate,
                "dx": 14,
                "dy": -24,
                "metadata": {"low_level_type": "coordinateLabel"},
            }
        )
    return out


def _is_origin_coordinate_label(label: str, coordinate: str) -> bool:
    if label != "O":
        return False
    normalized = re.sub(r"\s+", "", coordinate)
    return normalized in {"O(0,0)", "O(0,0.0)", "O(0.0,0)", "O(0.0,0.0)"}


def _derive_texts(lesson_step: LessonStep) -> tuple[str, ...]:
    return tuple(text for _, text in lesson_step.derive)


def _minimum_distance_items(context: _SceneBuildContext) -> list[JsonObject]:
    items: list[JsonObject] = []
    for marker in context.bindings.equal_length_path_markers:
        items.extend(_line_from_segment_payload(marker.get("common_path_segment"), color=COLOR_PATH, width=2.4))
        items.extend(
            _line_from_segment_payload(
                marker.get("replacement_path_segment"),
                color=COLOR_RESULT,
                width=2.4,
            )
        )
        minimum_segment = marker.get("minimum_segment")
        items.extend(
            _line_from_segment_payload(
                minimum_segment,
                color=COLOR_RESULT,
                width=2.8,
            )
        )
        items.extend(
            _distance_marker_from_segment_payload(
                minimum_segment,
                color=COLOR_RESULT,
                width=2.8,
            )
        )
        if isinstance(minimum_segment, dict):
            auxiliary_ref = str(minimum_segment.get("to") or "")
            if auxiliary_ref:
                items.extend(
                    _point_items_for_geometry_refs(
                        context,
                        {auxiliary_ref},
                        style=POINT_AUXILIARY,
                    )
                )
    return items


def _parameter_result_items(
    points: dict[str, str],
    boxes: tuple[str, ...],
    coordinate_texts: dict[str, str] | None = None,
) -> list[JsonObject]:
    items: list[JsonObject] = []
    items.extend(_point_items(points, ("G",), style=POINT_AUXILIARY))
    items.extend(_point_items(points, ("B",), style=POINT_RESULT))
    items.extend(_line_if_points(points, "O", "G", color=COLOR_RESULT, width=2.8))
    items.extend(_line_if_points(points, "C", "G", color=COLOR_CONSTRAINT, width=2.2))
    items.extend(_distance_marker(points, "O", "G", "OG", color=COLOR_RESULT, width=2.8))
    items.extend(_coordinate_labels(points, boxes, coordinate_texts))
    return items


def _line_if_points(
    points: dict[str, str],
    start: str,
    end: str,
    *,
    color: str,
    width: float,
    handle: str | None = None,
    state: str | None = None,
) -> list[JsonObject]:
    if start not in points or end not in points:
        return []
    item: JsonObject = {
        "component": "ColoredLine",
        "handle": handle or f"line:{points[start]}:{points[end]}",
        "from": points[start],
        "to": points[end],
        "color": color,
        "width": width,
        "persistence": "carry_forward",
        "decay_state": "muted",
        "metadata": {"low_level_type": "coloredLine"},
    }
    if handle:
        item["handle"] = handle
    if state:
        item["state"] = state
    return [item]


def _line_from_segment_payload(
    segment: Any,
    *,
    color: str,
    width: float,
) -> list[JsonObject]:
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    if not start or not end:
        return []
    return [
        {
            "component": "ColoredLine",
            "handle": _line_handle(segment),
            "from": start,
            "to": end,
            "color": color,
            "width": width,
            "persistence": "carry_forward",
            "decay_state": "muted",
            "metadata": {"low_level_type": "coloredLine"},
        }
    ]


def _line_handle(segment: dict[str, Any]) -> str:
    label = str(segment.get("label") or "")
    if label:
        return f"line:{label}"
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    return f"line:{start}:{end}"


def _dashed_line_if_points(points: dict[str, str], start: str, end: str) -> list[JsonObject]:
    if start not in points or end not in points:
        return []
    return [
        {
            "component": "DashedLine",
            "from": points[start],
            "to": points[end],
            "color": COLOR_MUTED,
            "width": 1.6,
            "dash": "5 5",
            "metadata": {"low_level_type": "dashedLine"},
        }
    ]


def _distance_marker(
    points: dict[str, str],
    start: str,
    end: str,
    label: str,
    *,
    color: str,
    width: float = 2.2,
    offset_px: int = 16,
) -> list[JsonObject]:
    if start not in points or end not in points:
        return []
    return [
        {
            "component": "DistanceMarker",
            "handle": f"distance:{points[start]}:{points[end]}:{label}",
            "from": points[start],
            "to": points[end],
            "label": label,
            "color": color,
            "width": width,
            "offsetPx": offset_px,
            "persistence": "step_only",
        }
    ]


def _distance_marker_from_segment_payload(
    segment: Any,
    *,
    color: str,
    width: float = 2.2,
    offset_px: int = 16,
) -> list[JsonObject]:
    if not isinstance(segment, dict):
        return []
    start = str(segment.get("from") or "")
    end = str(segment.get("to") or "")
    label = str(segment.get("label") or "")
    if not start or not end or not label:
        return []
    return [
        {
            "component": "DistanceMarker",
            "handle": f"distance:{start}:{end}:{label}",
            "from": start,
            "to": end,
            "label": label,
            "color": color,
            "width": width,
            "offsetPx": offset_px,
            "persistence": "step_only",
        }
    ]


def _annotations_for_lesson_step(lesson_step: LessonStep) -> list[JsonObject]:
    if not lesson_step.box:
        return []
    return [
        {
            "type": "label",
            "target": lesson_step.id,
            "text_source": "lesson_step.box",
            "index": 0,
        }
    ]


def _state_overrides_for_lesson_step(lesson_step: LessonStep) -> list[JsonObject]:
    if "axis_intercept_from_equal_acute_angles" not in lesson_step.capability_ids:
        return []
    return [
        {
            "handle": _angle_arm_handle(lesson_step.scope_id, "BE"),
            "state": "highlight",
        }
    ]


def _angle_arm_handle(scope_id: str, name: str) -> str:
    return f"line:{scope_id}:{name}"


def _focus_handles(scene_add: list[JsonObject]) -> list[str]:
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


def _visual_gap(expected_role: str, reason: str) -> JsonObject:
    return {
        "component": "VisualGap",
        "expected_role": expected_role,
        "reason": reason,
        "state": "gap",
    }


def _dedupe_scene_items(items: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    out: list[JsonObject] = []
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _coordinate_for_label(label: str, text: str) -> str:
    import re

    match = re.search(rf"{label}\(([^)]+)\)", text)
    if not match:
        return ""
    return f"{label}({match.group(1)})"


def _translation_label(vector: Any) -> str:
    if not isinstance(vector, list) or len(vector) != 2:
        return "v"
    dx = _plain_number_text(vector[0])
    dy = _plain_number_text(vector[1])
    if _is_zero_text(dy) and not _is_zero_text(dx):
        return f"-{_abs_text(dx)}" if dx.startswith("-") else f"+{_abs_text(dx)}"
    if _is_zero_text(dx) and not _is_zero_text(dy):
        return f"dy={dy}"
    return f"v=({dx},{dy})"


def _plain_number_text(value: Any) -> str:
    text = str(value).strip().replace(" ", "")
    return text or "0"


def _is_zero_text(value: str) -> bool:
    return value in {"0", "0.0", "+0", "-0"}


def _abs_text(value: str) -> str:
    return value[1:] if value.startswith("-") else value


def _verified_coordinate_texts_for_lesson_step(
    lesson_step: LessonStep,
    snapshot: ExplanationSnapshot,
) -> dict[str, str]:
    source_steps = {
        str(step.get("step_id")): step
        for step in snapshot.effective_steps
        if isinstance(step, dict) and step.get("step_id")
    }
    source_order = {
        str(step.get("step_id")): index
        for index, step in enumerate(snapshot.effective_steps)
        if isinstance(step, dict) and step.get("step_id")
    }
    source_indexes = [
        source_order[step_id]
        for step_id in lesson_step.source_step_ids
        if step_id in source_order
    ]
    visible_prefix_index = max(source_indexes) if source_indexes else -1
    runtime_points_by_source: dict[str, list[tuple[str, str]]] = {}
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict):
            continue
        if item.get("type") != "Point":
            continue
        source_key = _point_fact_source_key(item, source_order)
        value = item.get("value")
        if not source_key or not _is_point_value(value):
            continue
        runtime_points_by_source.setdefault(source_key, []).append(
            (_point_value_text(value), str(item.get("handle") or ""))
        )

    coordinates: dict[str, str] = {}
    for entity in (snapshot.problem or {}).get("entities") or ():
        if not isinstance(entity, dict) or entity.get("entity_type") != "point":
            continue
        if entity.get("definition") == "coordinate_origin":
            continue
        value = entity.get("coordinate")
        if not _is_point_value(value):
            continue
        label = str(entity.get("name") or _handle_tail(str(entity.get("handle") or "")))
        if label:
            coordinates.setdefault(label, f"{label}({_point_value_text(value).replace(', ', ',')})")
    for item in snapshot.fact_index.values():
        if not isinstance(item, dict) or item.get("type") != "Point":
            continue
        source_key = _point_fact_source_key(item, source_order)
        if not source_key or source_order.get(source_key, 10**9) > visible_prefix_index:
            continue
        value = item.get("value")
        if not _is_point_value(value):
            continue
        label = _point_label_for_runtime_coordinate_fact(item, source_steps, source_key)
        if label:
            coordinates[label] = f"{label}({_point_value_text(value)})"
    for source_step_id in lesson_step.source_step_ids:
        source_step = source_steps.get(source_step_id)
        if not source_step:
            continue
        labels = _point_labels_for_coordinate_source(source_step)
        values = runtime_points_by_source.get(source_step_id, ())
        if len(labels) != 1 or len(values) != 1:
            continue
        label = next(iter(labels))
        coordinates[label] = f"{label}({values[0][0]})"
    return coordinates


def _point_label_for_runtime_coordinate_fact(
    item: dict[str, Any],
    source_steps: dict[str, dict[str, Any]],
    source_key: str | None = None,
) -> str:
    source_step_id = source_key or str(item.get("source_step_id") or "")
    source_step = source_steps.get(source_step_id)
    if source_step:
        labels = _point_labels_for_coordinate_source(source_step)
        if len(labels) == 1:
            return next(iter(labels))
    name = str(item.get("name") or "")
    if name:
        labels = _point_labels_from_handle_text(name)
        if len(labels) == 1:
            return next(iter(labels))
    handle = str(item.get("handle") or "")
    labels = _point_labels_from_handle_text(handle)
    if len(labels) == 1:
        return next(iter(labels))
    return ""


def _point_fact_source_key(
    item: dict[str, Any],
    source_order: dict[str, int],
) -> str:
    source_step_id = str(item.get("source_step_id") or "")
    if source_step_id in source_order:
        return source_step_id
    scope_id = str(item.get("scope_id") or "")
    if scope_id in source_order:
        return scope_id
    return ""


def _point_labels_for_coordinate_source(step: dict[str, Any]) -> set[str]:
    target = step.get("target")
    if isinstance(target, str):
        target_labels = _point_labels_from_handle_text(target)
        if len(target_labels) == 1:
            return target_labels
    labels: set[str] = set()
    for produced in step.get("produces") or ():
        if not isinstance(produced, dict):
            continue
        handle = str(produced.get("handle") or "")
        handle_labels = _point_labels_from_handle_text(handle)
        if len(handle_labels) == 1:
            return handle_labels
        labels.update(handle_labels)
        description = str(produced.get("description") or "")
        labels.update(_capital_point_labels(description))
    return labels


def _point_labels_from_handle_text(handle: str) -> set[str]:
    name = handle.rsplit(":", 1)[-1].split(".", 1)[-1]
    name = re.sub(r"_(coordinate|coord|point|value|expr|expression|candidate|candidates)$", "", name)
    labels = _capital_point_labels(name)
    for chunk in re.findall(r"[A-Z]{2,}", name):
        labels.update(chunk)
    return labels


def _capital_point_labels(text: str) -> set[str]:
    labels = set(re.findall(r"(?<![A-Za-z])[A-Z](?![A-Za-z])", text))
    for chunk in re.findall(r"(?<![A-Za-z])([A-Z]{2,})(?![A-Za-z])", text):
        labels.update(chunk)
    return labels


def _is_point_value(value: Any) -> bool:
    return isinstance(value, list | tuple) and len(value) == 2


def _point_value_text(value: Any) -> str:
    return f"{value[0]}, {value[1]}"


def _scope_root(scope_id: str) -> str:
    return _shared_scope_root(scope_id)


def _default_t(base_lesson_data: JsonObject) -> float:
    for container in (base_lesson_data.get("meta") or {}, base_lesson_data.get("ui") or {}):
        if "defaultT" in container:
            try:
                return float(container["defaultT"])
            except (TypeError, ValueError):
                continue
    for step in base_lesson_data.get("steps") or ():
        if isinstance(step, dict) and "t" in step:
            try:
                return float(step["t"])
            except (TypeError, ValueError):
                continue
    return 0.75


def _short_label(index: int, step: LessonStep) -> str:
    label = step.nav_title or _strip_step_prefix(step.title)
    label = _strip_leading_nav_number(label)
    return f"{index} {label[:12]}".strip()


def _display_title(index: int, title: str) -> str:
    title = str(title).strip()
    body = _strip_step_prefix(title)
    if not body:
        body = title or "讲解步骤"
    return f"第{index}步：{body}"


def _strip_step_prefix(text: str) -> str:
    return re.sub(r"^第\s*\d+\s*步\s*[:：]?\s*", "", str(text)).strip()


def _strip_leading_nav_number(text: str) -> str:
    return re.sub(r"^\s*(?:第\s*)?\d+\s*(?:步)?\s*[:：.、]?\s*", "", str(text)).strip()


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
