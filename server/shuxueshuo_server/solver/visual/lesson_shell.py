"""Lesson-data shell helpers for generated VisualStepIR pages."""

from __future__ import annotations

from typing import Any
import copy
import re

from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot, LessonIR, LessonStep
from shuxueshuo_server.solver.student_display import student_math_display

from .geometry_naming import scope_root as _scope_root
from .models import JsonObject


def lesson_data_from_lesson_ir(lesson: LessonIR, base_lesson_data: JsonObject) -> JsonObject:
    out = copy.deepcopy(base_lesson_data)
    section_titles = _section_titles_for_lesson(lesson, base_lesson_data)
    out.setdefault("meta", {})
    out["meta"]["id"] = lesson.problem_id
    ui = out.setdefault("ui", {})
    ui["groupTitles"] = _runtime_group_titles(section_titles)
    steps: list[dict[str, Any]] = []
    policies: dict[str, Any] = {}
    labels: dict[str, str] = {}
    section_counts: dict[str, int] = {}
    for step in lesson.steps:
        section = section_titles.get(step.scope_id, step.scope_id)
        section_counts[section] = section_counts.get(section, 0) + 1
        local_index = section_counts[section]
        t_value = default_t(base_lesson_data)
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


def generated_lesson_shell(
    *,
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    default_t: float,
) -> JsonObject:
    problem = snapshot.problem or {}
    display = problem.get("display") if isinstance(problem.get("display"), dict) else {}
    title = str(problem.get("title") or snapshot.problem_id)
    lines = _problem_original_lines(problem, snapshot.problem_id)
    problem_lines = _problem_lines_with_answers(
        title=title,
        display=display,
        problem=problem,
        lines=lines,
        answers=snapshot.answers,
    )
    section_titles = _section_titles_for_lesson(
        lesson,
        {"problem": {"lines": problem_lines}},
    )
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
            "lines": problem_lines,
        },
        "ui": {
            "sliderLabel": "参数",
            "paramLabelPrefix": f"{parameter_name(snapshot)}=",
            "goToProblemMode": "doubleScroll",
            "groupTitles": dict(section_titles),
            "defaultT": default_t,
        },
        "steps": [],
        "policies": {},
        "stepLabels": {},
    }


def default_t(base_lesson_data: JsonObject) -> float:
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


def parameter_name(snapshot: ExplanationSnapshot) -> str:
    for item in snapshot.fact_index.values():
        if isinstance(item, dict) and item.get("type") == "ParameterValue":
            name = str(item.get("name") or "")
            if name and name != "parameter_value":
                return name
            handle = str(item.get("handle") or "")
            if handle:
                tail = handle.rsplit(":", 1)[-1]
                tail = re.sub(r"_value$", "", tail)
                if tail and tail != "parameter_value":
                    return tail
    return "t"


def _section_titles_for_lesson(lesson: LessonIR, lesson_data: JsonObject) -> dict[str, str]:
    problem_lines = _lesson_problem_line_texts(lesson_data)
    out: dict[str, str] = {}
    for section in lesson.sections:
        title = str(section.title or section.scope_id)
        goal = _question_target_for_section(
            title=title,
            scope_id=section.scope_id,
            problem_lines=problem_lines,
        )
        if not goal:
            goal = _first_step_nav_title_for_section(lesson, section.scope_id)
        if goal and _section_title_needs_goal(title):
            title = f"{title}：{goal}"
        out[section.scope_id] = title
    return out


def _runtime_group_titles(section_titles: dict[str, str]) -> dict[str, str]:
    out = dict(section_titles)
    for title in section_titles.values():
        out[title] = title
    return out


def _lesson_problem_line_texts(lesson_data: JsonObject) -> list[str]:
    problem = lesson_data.get("problem") if isinstance(lesson_data.get("problem"), dict) else {}
    lines: list[str] = []
    for raw in problem.get("lines") or ():
        if isinstance(raw, dict):
            text = str(raw.get("text") or "").strip()
        else:
            text = str(raw).strip()
        if text:
            lines.append(text)
    return lines


def _section_title_needs_goal(title: str) -> bool:
    text = title.strip()
    return bool(re.fullmatch(r"第[（(][^）)]+[）)](?:[①②③④⑤⑥⑦⑧⑨⑩])?问", text))


def _question_target_for_section(
    *,
    title: str,
    scope_id: str,
    problem_lines: list[str],
) -> str:
    marker = _section_marker_from_title(title)
    parent = marker[0] if marker else _parent_marker_from_scope(scope_id)
    child = marker[1] if marker else _child_marker_from_scope(scope_id)
    candidates: list[str] = []
    if child:
        candidates.extend(line for line in problem_lines if child in line)
    if parent:
        parent_markers = (f"（{parent}）", f"({parent})")
        candidates.extend(
            line
            for line in problem_lines
            if any(parent_marker in line for parent_marker in parent_markers)
        )
    for line in candidates:
        tail = line
        if child and child in tail:
            tail = tail.split(child, 1)[1]
        elif parent:
            for parent_marker in (f"（{parent}）", f"({parent})"):
                if parent_marker in tail:
                    tail = tail.split(parent_marker, 1)[1]
                    break
        target = _target_clause_from_question_text(tail)
        if target:
            return target
    return ""


def _section_marker_from_title(title: str) -> tuple[str, str] | None:
    match = re.match(
        r"^第[（(](?P<parent>[^）)]+)[）)](?P<child>[①②③④⑤⑥⑦⑧⑨⑩])?问$",
        title.strip(),
    )
    if not match:
        return None
    return (match.group("parent"), match.group("child") or "")


def _parent_marker_from_scope(scope_id: str) -> str:
    root = _scope_root(scope_id)
    return {
        "i": "Ⅰ",
        "ii": "Ⅱ",
        "iii": "Ⅲ",
        "iv": "Ⅳ",
    }.get(root, "")


def _child_marker_from_scope(scope_id: str) -> str:
    match = re.search(r"_(\d+)$", str(scope_id))
    if not match:
        return ""
    return {
        "1": "①",
        "2": "②",
        "3": "③",
        "4": "④",
        "5": "⑤",
        "6": "⑥",
        "7": "⑦",
        "8": "⑧",
        "9": "⑨",
        "10": "⑩",
    }.get(match.group(1), "")


def _target_clause_from_question_text(text: str) -> str:
    cleaned = str(text).strip()
    cleaned = re.sub(r"^[，,；;。.\s]+", "", cleaned)
    cleaned = re.sub(r"[；;。.\s]+$", "", cleaned)
    if not cleaned:
        return ""
    for keyword in ("求", "证明", "判断", "确定", "写出", "说明"):
        index = cleaned.rfind(keyword)
        if index >= 0:
            return cleaned[index:].strip(" ，,；;。.")
    return cleaned


def _first_step_nav_title_for_section(lesson: LessonIR, scope_id: str) -> str:
    step_ids = {
        step_id
        for section in lesson.sections
        if section.scope_id == scope_id
        for step_id in section.steps
    }
    for step in lesson.steps:
        if step.id in step_ids or step.scope_id == scope_id:
            nav_title = str(step.nav_title or "").strip()
            if nav_title:
                return nav_title
            return str(step.title or "").strip()
    return ""


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
    grouped: dict[str, list[JsonObject]] = {}
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
        grouped.setdefault(scope_id, []).append(
            {
                "answerId": _answer_dom_id(handle),
                "answer": _student_answer_display(answer_key, values[answer_key], value_type),
            }
        )
    out: list[JsonObject] = []
    for scope_id, entries in grouped.items():
        if len(entries) == 1:
            out.append(entries[0])
            continue
        out.append(
            {
                "answerId": _answer_dom_id(f"answer:{scope_id}"),
                "answer": "，".join(str(entry["answer"]) for entry in entries if entry.get("answer")),
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
    if value_type == "PointList" or _is_point_list_value(value):
        point_name = answer_key if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", answer_key) else ""
        point_prefix = point_name or "点"
        return " 或 ".join(
            f"{point_prefix}({_student_point_pair(point)})"
            for point in _sorted_display_points(value)
            if _is_point_value(point)
        )
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


def _sorted_display_points(value: Any) -> list[Any]:
    points = [item for item in value if _is_point_value(item)]
    try:
        import sympy as sp

        return sorted(
            points,
            key=lambda item: tuple(float(sp.N(sp.sympify(str(coord)))) for coord in reversed(item)),
            reverse=True,
        )
    except Exception:
        return points


def _student_math_expr(value: Any) -> str:
    return student_math_display(value, fullwidth_operators=True)


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


def _is_point_value(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and len(value) == 2
        and not any(isinstance(item, dict) for item in value)
    )


def _is_point_list_value(value: Any) -> bool:
    return (
        isinstance(value, list | tuple)
        and bool(value)
        and all(_is_point_value(item) for item in value)
        and not all(not isinstance(item, list | tuple) for item in value)
    )
