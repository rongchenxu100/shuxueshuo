"""Shared helpers for explanation role binders."""

from __future__ import annotations

import re
from typing import Any


def roles_from_trace(group: Any) -> dict[str, str]:
    fragments = [
        fragment
        for trace in group.traces
        for fragment in trace.trace_fragments
        if isinstance(fragment, dict)
    ]
    first = fragments[0] if fragments else {}
    return {
        "goal": str(first.get("goal", "")),
        "reason": str(first.get("reason", "")),
        "calculation": str(first.get("calculation", "")),
        "conclusion": str(first.get("conclusion", "")),
    }


def generic_must_not_invent() -> list[str]:
    return [
        "不得新增题目中不存在、draft 中也没有给出的点名、线段名或事实。",
        "不得新增数值、答案或坐标。",
        "不得把 method trace 中的临时变量当作学生讲解里的已知对象。",
    ]


def format_template(template: str, roles: dict[str, Any]) -> str:
    values = {
        key: role_text(value)
        for key, value in roles.items()
    }
    return _SafeFormatDict(values).format(template)


def role_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("label") or value.get("handle") or "")
    return str(value)


def after_equals(text: str) -> str:
    if "=" not in text:
        return ""
    return text.split("=", 1)[1].strip()


def minimum_expression_from_conclusion(text: str) -> str:
    match = re.search(r"为\s*(.+)$", text)
    return match.group(1).strip() if match else ""


def parameter_assignment(text: str) -> tuple[str, str]:
    match = re.search(r"([a-zA-Z\u03b1-\u03c9])\s*=\s*([^,，；;]+)", text)
    if not match:
        return "", ""
    return match.group(1), match.group(2).strip()


def handle_name(handle: str) -> str:
    return handle.rsplit(":", 1)[-1]


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"

    def format(self, template: str) -> str:
        return template.format_map(self)
