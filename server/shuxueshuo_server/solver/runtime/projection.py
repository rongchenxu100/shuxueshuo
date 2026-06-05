"""Canonical ProblemIR 的运行时与 LLM prompt 投影。

本模块是 Strategy Planner 生产化后的输入边界：同一份 ``ProblemIR`` 同时服务
runtime 执行和 LLM 策略规划。LLM 看到的是 canonical Entity / Fact / answer
handle 的轻量视图；RuntimeContext 仍沿用现有 ``ContextBuilder`` 构建。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from shuxueshuo_server.solver.problem_models import ProblemIR, QuestionGoal
from shuxueshuo_server.solver.question_goals import extract_question_goals


@dataclass(frozen=True)
class RuntimeProjection:
    """从 canonical ProblemIR 派生 runtime 与 LLM 两个视图。

    首版不替代 ``ContextBuilder``：``to_runtime_problem_ir`` 直接返回原题目，
    让现有 RuntimeContext 构建逻辑继续工作。新增的
    ``to_llm_problem_payload`` 则生成 Strategy prompt 的唯一题目事实源。
    """

    problem: ProblemIR

    def to_runtime_problem_ir(self) -> ProblemIR:
        """返回可交给 ``ContextBuilder`` 的 runtime-compatible ProblemIR。"""
        return self.problem

    def to_llm_problem_payload(self) -> dict[str, Any]:
        """返回 Strategy Planner prompt 使用的 canonical handle payload。"""
        return problem_to_llm_payload(self.problem)


def problem_to_llm_payload(problem: ProblemIR) -> dict[str, Any]:
    """从 canonical ProblemIR 生成 LLM ProblemIR payload。

    输出不包含 RuntimeContext 的 ``ContextPath``、expected answer、method chain 或
    planner hints。所有可读题设对象都通过 ``entities[]`` / ``facts[]`` 中的
    canonical handle 表达。
    """

    return {
        "problem_id": problem.problem_id,
        "purpose": "llm_strategy_planner_prompt",
        "title": _problem_title(problem),
        "original_text": _original_text_lines(problem),
        "scopes": _scope_payload(problem),
        "entities": _entity_payload(problem),
        "facts": _fact_payload(problem),
        "question_goals": _question_goal_payload(problem, extract_question_goals(problem)),
    }


def to_llm_problem_payload(problem: ProblemIR) -> dict[str, Any]:
    """兼容命名：显式表示这是从 ProblemIR 投影到 LLM payload。"""
    return problem_to_llm_payload(problem)


def to_runtime_problem_ir(problem: ProblemIR) -> ProblemIR:
    """兼容命名：首版 runtime 投影仍是原 ProblemIR。"""
    return problem


def _problem_title(problem: ProblemIR) -> str:
    """从题面来源和题号生成稳定标题。"""
    source = str(problem.original_text.get("source", "")).strip()
    number = str(problem.original_text.get("number", "")).strip()
    if source and number:
        return f"{source}第 {number} 题"
    if source:
        return source
    return problem.problem_id


def _original_text_lines(problem: ProblemIR) -> list[str]:
    """读取题面原文行。"""
    lines = problem.original_text.get("lines", [])
    if isinstance(lines, list):
        return [str(line) for line in lines]
    text = problem.original_text.get("text")
    if isinstance(text, str) and text.strip():
        return [text.strip()]
    return []


def _scope_payload(problem: ProblemIR) -> list[dict[str, Any]]:
    """从 question tree 派生 LLM 可读 scope hierarchy。"""
    scopes: list[dict[str, Any]] = [
        {"scope_id": "problem", "label": "整题", "parent": None}
    ]

    def visit(question: Mapping[str, Any], parent: str) -> None:
        scope_id = str(question.get("id", "")).strip()
        if not scope_id:
            return
        label = str(question.get("label", "")).strip() or scope_id
        if question.get("subquestions"):
            label = f"{label}公共条件"
        scopes.append({"scope_id": scope_id, "label": label, "parent": parent})
        for child in question.get("subquestions", []) or []:
            if isinstance(child, Mapping):
                visit(child, scope_id)

    for raw_question in problem.data.get("questions", []) or []:
        if isinstance(raw_question, Mapping):
            visit(raw_question, "problem")
    return scopes


def _entity_payload(problem: ProblemIR) -> list[dict[str, str]]:
    """生成给 LLM 看的实体表，保留 handle/type/scope/description。"""
    raw_entities = problem.data.get("entities", {})
    items = raw_entities.get("items", []) if isinstance(raw_entities, Mapping) else []
    result: list[dict[str, str]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        handle = str(raw.get("handle", "")).strip()
        entity_type = str(raw.get("entity_type", "")).strip()
        scope_id = str(raw.get("scope_id", "")).strip()
        if not handle or not entity_type or not scope_id:
            continue
        result.append(
            {
                "handle": handle,
                "entity_type": entity_type,
                "scope_id": scope_id,
                "description": _entity_description(problem, raw),
            }
        )
    return result


def _fact_payload(problem: ProblemIR) -> list[dict[str, str]]:
    """生成给 LLM 看的题设 fact 表。"""
    result: list[dict[str, str]] = []
    for raw in problem.data.get("facts", []) or []:
        if not isinstance(raw, Mapping):
            continue
        handle = str(raw.get("handle", "")).strip()
        fact_type = str(raw.get("type", "")).strip()
        scope_id = str(raw.get("scope_id", "")).strip()
        valid_scope = str(raw.get("valid_scope", scope_id)).strip()
        if not handle or not fact_type or not scope_id:
            continue
        result.append(
            {
                "handle": handle,
                "type": fact_type,
                "scope_id": scope_id,
                "valid_scope": valid_scope or scope_id,
                "description": _fact_description(raw),
            }
        )
    return result


def _question_goal_payload(
    problem: ProblemIR,
    question_goals: list[QuestionGoal],
) -> list[dict[str, str]]:
    """把 QuestionGoal 转成 answer handle 表，避免暴露 target_path。"""
    labels = _question_labels(problem)
    result: list[dict[str, str]] = []
    for goal in question_goals:
        label = labels.get(goal.question_id, goal.question_id)
        result.append(
            {
                "handle": f"answer:{goal.id}",
                "scope_id": goal.question_id,
                "answer_key": goal.answer_key,
                "value_type": goal.value_type,
                "description": _goal_description(problem, label, goal),
            }
        )
    return result


def _question_labels(problem: ProblemIR) -> dict[str, str]:
    """收集 question/subquestion label。"""
    labels: dict[str, str] = {}

    def visit(question: Mapping[str, Any]) -> None:
        scope_id = str(question.get("id", "")).strip()
        if scope_id:
            labels[scope_id] = str(question.get("label", "")).strip() or scope_id
        for child in question.get("subquestions", []) or []:
            if isinstance(child, Mapping):
                visit(child)

    for raw_question in problem.data.get("questions", []) or []:
        if isinstance(raw_question, Mapping):
            visit(raw_question)
    return labels


def _entity_description(problem: ProblemIR, raw: Mapping[str, Any]) -> str:
    """把 canonical entity 压缩成 LLM 友好的描述。"""
    entity_type = str(raw.get("entity_type", ""))
    name = str(raw.get("name", "")).strip()
    handle = str(raw.get("handle", ""))
    if entity_type == "function":
        expression = str(raw.get("expression", "") or problem.data.get("function", {}).get("expression", ""))
        if expression:
            return "抛物线 y=" + _compact_expression(expression)
    if entity_type == "symbol":
        role = problem.symbol_roles.get(name) or problem.symbol_roles.get(_handle_name(handle))
        constraint = problem.constraints.get(name) or problem.constraints.get(_handle_name(handle))
        return _symbol_description(name or _handle_name(handle), role=role, constraint=constraint, problem=problem)
    description = str(raw.get("description", "")).strip()
    if description:
        return _strip_name_prefix(description, name or _handle_name(handle))
    return name or handle


def _fact_description(raw: Mapping[str, Any]) -> str:
    """把 fact description 做轻量清理。"""
    description = str(raw.get("description", "")).strip()
    fact_type = str(raw.get("type", "")).strip()
    if fact_type in {"symbol_constraint", "coefficient_relation"}:
        return _compact_expression(description)
    return description


def _goal_description(problem: ProblemIR, label: str, goal: QuestionGoal) -> str:
    """生成 answer handle 的可读说明。"""
    if goal.value_type == "Point":
        target = _point_goal_description(problem, goal) or f"{goal.answer_key} 的坐标"
    elif goal.value_type == "Parabola":
        target = "抛物线解析式"
    elif goal.value_type == "MinimumExpression":
        target = "EG+FG 的最小值" if goal.answer_key in {"min_value", "minimum_value"} else goal.answer_key
    elif goal.value_type == "ParameterValue":
        target = f"{goal.answer_key} 的值"
    else:
        target = goal.answer_key
    return f"{label}输出 {target}"


def _point_goal_description(problem: ProblemIR, goal: QuestionGoal) -> str | None:
    """从 QuestionGoal target_path 反推点实体描述，避免按点名写特殊规则。"""
    handle = _point_handle_from_target_path(goal.target_path)
    if handle is None:
        return None
    raw_entities = problem.data.get("entities", {})
    items = raw_entities.get("items", []) if isinstance(raw_entities, Mapping) else []
    for raw in items:
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("handle", "")).strip() != handle:
            continue
        name = str(raw.get("name", "") or _handle_name(handle)).strip()
        description = _entity_description(problem, raw)
        if description and description != name and not _is_location_membership_description(description):
            return f"{description}坐标"
        return f"{name} 的坐标" if name else None
    return None


def _point_handle_from_target_path(target_path: str) -> str | None:
    """把 ``$question.i.points.P`` 这类目标路径映射为 canonical point handle。"""
    parts = target_path.split(".")
    if len(parts) == 3 and parts[0] == "$problem" and parts[1] == "points":
        scope = "problem"
        name = parts[2]
    elif len(parts) == 4 and parts[0] in {"$question", "$subquestion"} and parts[2] == "points":
        scope = parts[1]
        name = parts[3]
    else:
        return None
    if not scope or not name:
        return None
    return f"point:{scope}:{name}"


def _is_location_membership_description(description: str) -> bool:
    """识别“点在线/曲线上”这类不适合作为 answer 名称的实体说明。"""
    compact = re.sub(r"\s+", "", description)
    if "在线段" in compact or "在射线" in compact or "在直线" in compact:
        return True
    return "在" in compact and ("抛物线" in compact or "曲线" in compact)


def _symbol_description(
    name: str,
    *,
    role: str | None,
    constraint: str | None,
    problem: ProblemIR,
) -> str:
    """根据 symbol_roles 生成稳定的符号说明。"""
    if role == "function_variable":
        return "函数自变量"
    if role == "quadratic_coefficient":
        text = {
            "a": "二次项系数",
            "b": "一次项系数",
            "c": "常数项",
        }.get(name, f"二次函数系数 {name}")
        if constraint and name == "b":
            return f"{text}，{name}{constraint}"
        return text
    if role == "dynamic_parameter":
        # 若某个点以该符号作为 x 坐标，优先说明它是对应动点参数。
        point_name = _point_name_for_coordinate_symbol(problem, name)
        if point_name:
            if constraint and constraint in {">0", ">=0"}:
                return f"{point_name} 的横坐标参数，{name}{constraint}"
            return f"{point_name} 的横坐标参数"
        if constraint:
            return f"动点参数，{name}{constraint}"
        return "动点参数"
    if constraint:
        return f"符号 {name}，{name}{constraint}"
    return f"符号 {name}"


def _point_name_for_coordinate_symbol(problem: ProblemIR, symbol_name: str) -> str | None:
    """从 entity 坐标中反查以某个符号为 x 坐标的点。"""
    raw_entities = problem.data.get("entities", {})
    items = raw_entities.get("items", []) if isinstance(raw_entities, Mapping) else []
    for raw in items:
        if not isinstance(raw, Mapping) or raw.get("entity_type") != "point":
            continue
        coordinate = raw.get("coordinate")
        if isinstance(coordinate, list) and coordinate:
            first = str(coordinate[0]).removeprefix("symbol:problem:")
            if first == symbol_name:
                return str(raw.get("name") or _handle_name(str(raw.get("handle", ""))))
    return None


def _compact_expression(text: str) -> str:
    """压缩数学表达式中的空白。"""
    return re.sub(r"\s+", "", str(text))


def _strip_name_prefix(description: str, name: str) -> str:
    """去掉 ``D 是`` 这类重复前缀，让实体表更紧凑。"""
    if name and description.startswith(f"{name} 是"):
        return description[len(f"{name} 是") :]
    return description


def _handle_name(handle: str) -> str:
    """读取 canonical handle 的 name 部分。"""
    return handle.rsplit(":", 1)[-1] if ":" in handle else handle


__all__ = [
    "RuntimeProjection",
    "problem_to_llm_payload",
    "to_llm_problem_payload",
    "to_runtime_problem_ir",
]
