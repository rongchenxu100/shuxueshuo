"""Canonical ProblemIR 的运行时与 LLM prompt 投影。

本模块是 Strategy Planner 生产化后的输入边界：同一份 ``ProblemIR`` 同时服务
runtime 执行和 LLM 策略规划。LLM 看到的是 canonical Entity / Fact / answer
handle 的轻量视图；RuntimeContext 仍沿用现有 ``ContextBuilder`` 构建。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any, Mapping

from shuxueshuo_server.solver.problem_models import ProblemIR, QuestionGoal
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.models import ContextPath


_CANONICAL_PAYLOAD_KEY = "_canonical_problem_payload"


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

    canonical = problem.data.get(_CANONICAL_PAYLOAD_KEY)
    if isinstance(canonical, Mapping):
        return deepcopy(dict(canonical))

    return {
        "problem_id": problem.problem_id,
        "purpose": "llm_strategy_planner_prompt",
        "title": _problem_title(problem),
        "display": _display_payload(problem),
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


def is_canonical_problem_input(raw: Mapping[str, Any]) -> bool:
    """判断 fixture input 是否是 authored canonical ProblemIR。

    canonical authored input 不再包含旧 runtime ``data``，而是直接保存
    ``scopes/entities/facts/question_goals`` 四张题面事实表。
    """

    required = {
        "problem_id",
        "pattern",
        "problem_type",
        "original_text",
        "scopes",
        "entities",
        "facts",
        "question_goals",
    }
    return required.issubset(raw) and "data" not in raw


def problem_from_canonical_input(raw: Mapping[str, Any]) -> ProblemIR:
    """把 authored canonical ProblemIR 投影为现有 runtime-compatible ProblemIR。

    这是迁移期的核心适配层：fixture 只维护 canonical Entity/Fact/QuestionGoal，
    ContextBuilder 仍读取它熟悉的 runtime view。
    """

    _validate_canonical_input(raw)
    canonical_payload = _canonical_payload(raw)
    symbols, symbol_roles = _symbols_from_entities(canonical_payload["entities"])
    constraints = _constraints_from_facts(canonical_payload["facts"])
    runtime_data = _runtime_data_from_canonical(
        canonical_payload,
        symbols=symbols,
        symbol_roles=symbol_roles,
    )
    runtime_data[_CANONICAL_PAYLOAD_KEY] = canonical_payload
    return ProblemIR(
        problem_id=str(raw["problem_id"]),
        pattern=str(raw["pattern"]),
        problem_type=str(raw["problem_type"]),
        symbols=symbols,
        symbol_roles=symbol_roles,
        original_text=dict(raw["original_text"]),
        display=dict(canonical_payload.get("display") or {}),
        constraints=constraints,
        data=runtime_data,
        solver_config={},
        expected_answers={},
    )


def _validate_canonical_input(raw: Mapping[str, Any]) -> None:
    """做最小 authored canonical shape 校验。"""

    if not is_canonical_problem_input(raw):
        raise ValueError("not a canonical ProblemIR input")
    allowed = {
        "problem_id",
        "pattern",
        "problem_type",
        "display",
        "original_text",
        "scopes",
        "entities",
        "facts",
        "question_goals",
    }
    extra = sorted(set(raw) - allowed)
    if extra:
        raise ValueError("canonical ProblemIR input contains unsupported fields: " + ", ".join(extra))
    for key in ("scopes", "entities", "facts", "question_goals"):
        if not isinstance(raw.get(key), list):
            raise ValueError(f"canonical ProblemIR {key} must be a list")


def _canonical_payload(raw: Mapping[str, Any]) -> dict[str, Any]:
    """把 authored canonical input 归一化成 Strategy prompt payload。"""

    original_text = raw.get("original_text")
    if not isinstance(original_text, Mapping):
        raise ValueError("canonical ProblemIR original_text must be an object")
    problem = ProblemIR(
        problem_id=str(raw["problem_id"]),
        pattern=str(raw["pattern"]),
        problem_type=str(raw["problem_type"]),
        symbols=[],
        original_text=dict(original_text),
        display=dict(raw.get("display") or {}),
    )
    payload = {
        "problem_id": str(raw["problem_id"]),
        "pattern": str(raw["pattern"]),
        "problem_type": str(raw["problem_type"]),
        "purpose": "llm_strategy_planner_prompt",
        "title": _problem_title(problem),
        "display": _display_payload(problem),
        "original_text": _original_text_lines(problem),
        "scopes": deepcopy(list(raw["scopes"])),
        "entities": deepcopy(list(raw["entities"])),
        "facts": deepcopy(list(raw["facts"])),
        "question_goals": deepcopy(list(raw["question_goals"])),
    }
    payload["question_goals"] = _canonical_question_goal_payload(payload)
    return payload


def _canonical_question_goal_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """为 canonical question_goals 补充可由 facts 动态派生的描述。"""
    goals = [dict(item) for item in payload.get("question_goals", []) if isinstance(item, Mapping)]
    scope_labels = {
        str(item.get("scope_id", "")): str(item.get("label", "")).strip()
        for item in payload.get("scopes", [])
        if isinstance(item, Mapping)
    }
    for goal in goals:
        value_type = str(goal.get("value_type", ""))
        if value_type not in {"MinimumExpression", "ParameterValue"}:
            continue
        scope_id = str(goal.get("scope_id", "") or goal.get("valid_scope", "")).strip()
        path = _minimum_path_from_payload(payload, scope_id)
        if not path:
            continue
        label = scope_labels.get(scope_id) or scope_id
        answer_key = str(goal.get("answer_key", "")).strip()
        if value_type == "MinimumExpression":
            goal["description"] = f"{label}输出 {path} 的最小值"
        elif answer_key:
            goal["description"] = f"{label}输出 由 {path} 的最小值求 {answer_key} 的值"
    return goals


def _runtime_data_from_canonical(
    payload: Mapping[str, Any],
    *,
    symbols: list[str],
    symbol_roles: Mapping[str, str],
) -> dict[str, Any]:
    """从 canonical payload 派生当前 ContextBuilder 需要的 data。"""

    entities = [dict(item) for item in payload["entities"] if isinstance(item, Mapping)]
    facts = [dict(item) for item in payload["facts"] if isinstance(item, Mapping)]
    scopes = [dict(item) for item in payload["scopes"] if isinstance(item, Mapping)]
    goals = [dict(item) for item in payload["question_goals"] if isinstance(item, Mapping)]
    entity_items = [_runtime_entity_item(item) for item in entities]
    data: dict[str, Any] = {
        "function": _runtime_function(entities),
        "entities": {
            "items": entity_items,
            "points": _runtime_points(entities, facts),
        },
        "facts": [_runtime_fact(item) for item in facts],
        "relations": _runtime_relations(entities, facts),
        "questions": _runtime_questions(scopes, facts, goals),
    }
    path_problem = _runtime_path_problem(payload, facts)
    if path_problem is not None:
        data["path_problem"] = path_problem
    parameter = _dynamic_parameter(symbols, symbol_roles)
    if parameter is not None:
        data["parameter"] = parameter
    return data


def _symbols_from_entities(entities: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    """从 symbol entity 派生 ProblemIR.symbols / symbol_roles。"""

    result: list[str] = []
    roles: dict[str, str] = {}
    for item in entities:
        if not isinstance(item, Mapping) or item.get("entity_type") != "symbol":
            continue
        name = str(item.get("name") or _handle_name(str(item.get("handle", "")))).strip()
        if not name:
            continue
        result.append(name)
        role = item.get("role")
        if isinstance(role, str) and role:
            roles[name] = role
    return result, roles


def _constraints_from_facts(facts: list[dict[str, Any]]) -> dict[str, str]:
    """从 symbol_constraint fact 派生 ProblemIR.constraints。"""

    constraints: dict[str, str] = {}
    for item in facts:
        if not isinstance(item, Mapping) or item.get("type") != "symbol_constraint":
            continue
        subject = str(item.get("subject", ""))
        name = _handle_name(subject)
        operator = str(item.get("operator", "")).strip()
        value = str(item.get("value", "")).strip()
        if name and operator and value:
            constraints[name] = f"{operator}{value}"
    return constraints


def _runtime_entity_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """给 canonical entity 补 runtime/debug source。"""

    result = dict(item)
    result.setdefault("source", "ProblemIR.entities")
    return result


def _runtime_fact(item: Mapping[str, Any]) -> dict[str, Any]:
    """给 canonical fact 补 runtime/debug source。"""

    result = dict(item)
    if result.get("type") == "point_coordinate" and isinstance(result.get("value"), list):
        result["value"] = [_runtime_expression_value(value) for value in result["value"]]
    result.setdefault("source", "ProblemIR.facts")
    return result


def _runtime_function(entities: list[dict[str, Any]]) -> dict[str, Any]:
    """从 function entity 派生 data.function。"""

    for item in entities:
        if not isinstance(item, Mapping) or item.get("entity_type") != "function":
            continue
        return {
            "id": str(item.get("name") or _handle_name(str(item.get("handle", ""))) or "parabola"),
            "type": str(item.get("function_type") or item.get("type") or "quadratic"),
            "expression": str(item.get("expression") or "a*x**2 + b*x + c"),
            **(
                {"coefficient_relation": str(item["coefficient_relation"])}
                if item.get("coefficient_relation")
                else {}
            ),
        }
    return {"id": "parabola", "type": "quadratic", "expression": "a*x**2 + b*x + c"}


def _runtime_points(
    entities: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """从 point entity 派生 ContextBuilder 的 legacy point index。

    legacy ``data.entities.points`` 是一个 dict，不能天然表达同名不同 scope
    的点。canonical Entity 允许 ``point:problem:A`` 与 ``point:ii:A`` 同时
    存在，因此这里的 dict key 只作为内部唯一索引；真正写入 RuntimeContext
    的点名由 payload["name"] 决定。
    """

    quadrants = _quadrants_by_point_handle(facts)
    points: dict[str, dict[str, Any]] = {}
    for item in entities:
        if not isinstance(item, Mapping) or item.get("entity_type") != "point":
            continue
        name = str(item.get("name") or _handle_name(str(item.get("handle", "")))).strip()
        if not name:
            continue
        payload = {key: deepcopy(value) for key, value in item.items()}
        if isinstance(payload.get("coordinate"), list):
            payload["coordinate"] = [
                _runtime_expression_value(value)
                for value in payload["coordinate"]
            ]
        if isinstance(payload.get("x"), str):
            payload["x"] = _runtime_expression_value(payload["x"])
        for key in (
            "of",
            "source",
            "base",
            "exclude_point",
            "known_point",
            "vertex",
            "adjacent",
            "target",
            "line",
            "mirror_line",
        ):
            if key in payload:
                payload[key] = _runtime_definition_value(payload[key])
        quadrant = quadrants.get(str(item.get("handle", "")))
        if quadrant:
            payload["quadrant"] = quadrant
        payload.setdefault("handle", item.get("handle"))
        payload.setdefault("entity_type", "point")
        payload.setdefault("scope_id", item.get("scope_id", "problem"))
        payload.setdefault("source", "ProblemIR.entities")
        point_key = name
        if point_key in points:
            point_key = f"{payload.get('scope_id', 'problem')}:{name}"
        points[point_key] = payload
    return points


def _quadrants_by_point_handle(facts: list[dict[str, Any]]) -> dict[str, str]:
    """从 orientation_constraint facts 派生 point entity 的 legacy quadrant 字段。"""

    result: dict[str, str] = {}
    for fact in facts:
        if not isinstance(fact, Mapping) or fact.get("type") != "orientation_constraint":
            continue
        subject = str(fact.get("subject", "")).strip()
        quadrant = str(fact.get("quadrant", "")).strip()
        if subject and quadrant:
            result[subject] = quadrant
    return result


def _runtime_relations(
    entities: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从 canonical facts/entities 派生 ContextInventory/ContextBuilder 兼容 relations。"""

    relations: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        relation = _relation_from_fact(fact)
        if relation is not None:
            relations.append(relation)
    for entity in entities:
        if not isinstance(entity, Mapping) or entity.get("entity_type") != "point":
            continue
        definition = str(entity.get("definition", ""))
        if definition == "x_axis_intercept":
            relations.append(
                {
                    "type": "x_axis_intercept_point",
                    "point": _handle_name(str(entity.get("handle", ""))),
                    "curve": _handle_name(str(entity.get("of") or "function:problem:parabola")),
                    "scope": str(entity.get("scope_id") or "problem"),
                }
            )
    return relations


def _relation_from_fact(fact: Mapping[str, Any]) -> dict[str, Any] | None:
    """把常见题设 fact 转成旧 relation 结构。"""

    fact_type = str(fact.get("type", ""))
    scope = str(fact.get("scope_id", "problem"))
    if fact_type == "point_on_curve":
        return {
            "type": "point_on_curve",
            "point": _handle_name(str(fact.get("point", ""))),
            "curve": _handle_name(str(fact.get("curve", ""))),
            "scope": scope,
        }
    if fact_type == "point_on_segment":
        return {
            "type": "point_on_segment",
            "point": _handle_name(str(fact.get("point", ""))),
            "segment": _handle_name(str(fact.get("segment", ""))),
            "scope": scope,
        }
    if fact_type == "point_on_ray":
        return {
            "type": "point_on_ray",
            "point": _handle_name(str(fact.get("point", ""))),
            "ray": _handle_name(str(fact.get("ray", ""))),
            "scope": scope,
        }
    if fact_type == "segment_membership":
        return {
            "type": "segment_membership",
            "point": _handle_name(str(fact.get("point", ""))),
            "segment": _handle_name(str(fact.get("segment", ""))),
            "scope": scope,
        }
    if fact_type == "segment_relation":
        return {
            "type": "segment_relation",
            "left": str(fact.get("left", "")),
            "right": str(fact.get("right", "")),
            "scope": scope,
        }
    if fact_type == "right_angle_equal_length":
        relation = {key: deepcopy(value) for key, value in fact.items() if key not in {"handle", "valid_scope", "description", "source"}}
        relation["scope"] = scope
        if isinstance(relation.get("angle"), list):
            relation["angle"] = [
                _runtime_definition_value(value)
                for value in relation["angle"]
            ]
        if isinstance(relation.get("equal_segments"), list):
            relation["equal_segments"] = [
                _runtime_definition_value(value)
                for value in relation["equal_segments"]
            ]
        return relation
    if fact_type in {"angle_sum", "equal_length_condition"}:
        relation = {key: deepcopy(value) for key, value in fact.items() if key not in {"handle", "valid_scope", "description", "source"}}
        relation["scope"] = scope
        return relation
    return None


def _runtime_path_problem(
    payload: Mapping[str, Any],
    facts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """从 path minimum fact 派生 data.path_problem。"""

    for fact in facts:
        if not isinstance(fact, Mapping):
            continue
        if fact.get("type") not in {"minimum_value", "path_minimum_target"}:
            continue
        path = fact.get("path")
        if not path:
            continue
        value = fact.get("value")
        problem_type = str(payload.get("problem_type", ""))
        pattern = str(payload.get("pattern", ""))
        path_type = "weighted_path_minimum" if "weighted" in (problem_type + pattern) else "two_moving_points_path_minimum"
        return {
            "type": path_type,
            "scope": str(fact.get("scope_id", "problem")),
            "path": str(path),
            **({"value": str(value)} if value else {}),
        }
    return None


def _runtime_questions(
    scopes: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    goals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从 canonical scopes/question_goals/facts 派生 data.questions tree。"""

    nodes: dict[str, dict[str, Any]] = {}
    parents: dict[str, str | None] = {}
    for item in scopes:
        scope_id = str(item.get("scope_id", "")).strip()
        if not scope_id or scope_id == "problem":
            continue
        parent = item.get("parent")
        parents[scope_id] = str(parent) if parent is not None else "problem"
        nodes[scope_id] = {
            "id": scope_id,
            "label": str(item.get("label") or scope_id),
            "asks": list(item.get("asks", [])) if isinstance(item.get("asks"), list) else [],
            "known_coefficients": _known_coefficients_for_scope(scope_id, facts),
            "conditions": _conditions_for_scope(scope_id, facts),
            "goals": [
                _runtime_goal(goal, parents)
                for goal in goals
                if str(goal.get("scope_id", "")) == scope_id
            ],
            "subquestions": [],
        }
    roots: list[dict[str, Any]] = []
    for scope_id, node in nodes.items():
        parent = parents.get(scope_id)
        if parent and parent != "problem" and parent in nodes:
            nodes[parent]["subquestions"].append(node)
        else:
            roots.append(node)
    return roots


def _known_coefficients_for_scope(scope_id: str, facts: list[dict[str, Any]]) -> dict[str, str]:
    """把当前 scope 的 symbol_value facts 派生成旧 known_coefficients。"""

    known: dict[str, str] = {}
    for fact in facts:
        if not isinstance(fact, Mapping) or str(fact.get("scope_id")) != scope_id:
            continue
        if str(fact.get("type", "")) != "symbol_value":
            continue
        subject = str(fact.get("subject", "")).strip()
        name = _handle_name(subject)
        value = fact.get("value")
        if name and value is not None:
            known[name] = str(value)
    return known


def _conditions_for_scope(scope_id: str, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把当前 scope 的题设 fact 暴露给旧 ContextBuilder question.conditions。"""

    result: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, Mapping) or str(fact.get("scope_id")) != scope_id:
            continue
        fact_type = str(fact.get("type", "condition"))
        if fact_type in {"symbol_constraint", "symbol_value", "point_coordinate"}:
            continue
        condition = {
            key: deepcopy(value)
            for key, value in fact.items()
            if key not in {"handle", "valid_scope", "source"}
        }
        condition.setdefault("type", fact_type)
        if fact_type == "length_squared" and isinstance(condition.get("segment"), str):
            condition["segment"] = _segment_endpoint_names_from_handle(condition["segment"])
        condition.setdefault("source", str(fact.get("description", "")))
        result.append(condition)
    return result


def _runtime_goal(goal: Mapping[str, Any], parents: Mapping[str, str | None]) -> dict[str, Any]:
    """把 canonical question goal 派生为旧 QuestionGoal shape。"""

    handle = str(goal.get("handle", "")).strip()
    goal_id = handle.removeprefix("answer:") if handle.startswith("answer:") else handle
    scope_id = str(goal.get("scope_id", "")).strip()
    answer_key = str(goal.get("answer_key") or _answer_key_from_goal_id(goal_id)).strip()
    value_type = str(goal.get("value_type", "")).strip()
    target_handle = goal.get("target_handle")
    target_scope_id = str(goal.get("valid_scope") or scope_id).strip()
    if isinstance(target_handle, str) and target_handle and value_type == "Point":
        target_path = _runtime_path_from_handle(target_handle, parents, container="points")
    else:
        target_path = _runtime_path_for_scope_id(target_scope_id, parents, "outputs", answer_key)
    return {
        "id": goal_id,
        "answer_key": answer_key,
        "target_path": target_path,
        "value_type": value_type,
        "required": bool(goal.get("required", True)),
    }


def _runtime_path_from_handle(
    handle: str,
    parents: Mapping[str, str | None],
    *,
    container: str,
) -> str:
    """把 canonical entity handle 映射成 runtime ContextPath。"""

    parts = handle.split(":")
    if len(parts) != 3:
        raise ValueError(f"invalid scoped handle: {handle}")
    _kind, scope_id, name = parts
    return _runtime_path_for_scope_id(scope_id, parents, container, name)


def _runtime_path_for_scope_id(
    scope_id: str,
    parents: Mapping[str, str | None],
    container: str,
    key: str,
) -> str:
    """按 canonical scope 派生 ContextPath 字符串。"""

    if scope_id == "problem":
        return f"$problem.{container}.{key}"
    parent = parents.get(scope_id)
    prefix = "$question" if parent == "problem" else "$subquestion"
    return f"{prefix}.{scope_id}.{container}.{key}"


def _answer_key_from_goal_id(goal_id: str) -> str:
    """goal 未显式给 answer_key 时，从 id 取最后一段。"""

    if "." in goal_id:
        return goal_id.rsplit(".", 1)[-1]
    if "_" in goal_id:
        return goal_id.rsplit("_", 1)[-1]
    return goal_id


def _dynamic_parameter(
    symbols: list[str],
    symbol_roles: Mapping[str, str],
) -> str | None:
    """从 symbol_roles 派生旧 data.parameter。"""

    for name in symbols:
        if symbol_roles.get(name) == "dynamic_parameter":
            return name
    return None


def _problem_title(problem: ProblemIR) -> str:
    """从题面来源和题号生成稳定标题。"""
    source = str(problem.original_text.get("source", "")).strip()
    number = str(problem.original_text.get("number", "")).strip()
    if source and number:
        return f"{source} 第 {number} 题"
    if source:
        return source
    return problem.problem_id


def _display_payload(problem: ProblemIR) -> dict[str, Any]:
    """题目展示元数据，供页面/讲解层消费。"""
    display = dict(problem.display or {})
    original = dict(problem.original_text or {})
    source = str(original.get("source", "")).strip()
    number = str(original.get("number", "")).strip()
    score = str(original.get("score", "")).strip()
    if source:
        display.setdefault("source", source)
    if number:
        display.setdefault("number", number)
    if score:
        display.setdefault("score", score)
    return display


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
        target_scope_id = ContextPath.parse(goal.target_path).scope_id
        result.append(
            {
                "handle": f"answer:{goal.id}",
                "scope_id": target_scope_id,
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
        path = _minimum_path_for_goal(problem, goal)
        target = f"{path} 的最小值" if path else goal.answer_key
    elif goal.value_type == "ParameterValue":
        path = _minimum_path_for_goal(problem, goal)
        target = (
            f"由 {path} 的最小值求 {goal.answer_key} 的值"
            if path
            else f"{goal.answer_key} 的值"
        )
    else:
        target = goal.answer_key
    return f"{label}输出 {target}"


def _minimum_path_for_goal(problem: ProblemIR, goal: QuestionGoal) -> str | None:
    """从当前 goal 可见的 path minimum fact 中读取路径表达式。"""
    try:
        target_scope_id = ContextPath.parse(goal.target_path).scope_id
    except ValueError:
        target_scope_id = goal.question_id
    visible_scopes = _visible_scopes_for_goal(problem, target_scope_id or goal.question_id)
    facts = [
        fact for fact in problem.data.get("facts", []) or []
        if isinstance(fact, Mapping)
    ]
    for fact_type in ("path_minimum_target", "minimum_value"):
        for scope_id in visible_scopes:
            for fact in facts:
                if str(fact.get("type", "")) != fact_type:
                    continue
                if str(fact.get("scope_id", "problem")) != scope_id:
                    continue
                path = str(fact.get("path", "")).strip()
                if path:
                    return path
    return None


def _minimum_path_from_payload(payload: Mapping[str, Any], scope_id: str) -> str | None:
    """从 canonical payload 中读取当前 scope 可见的路径最值表达式。"""
    visible_scopes = _visible_scopes_from_payload(payload, scope_id)
    facts = [
        fact for fact in payload.get("facts", []) or []
        if isinstance(fact, Mapping)
    ]
    for fact_type in ("path_minimum_target", "minimum_value"):
        for visible_scope in visible_scopes:
            for fact in facts:
                if str(fact.get("type", "")) != fact_type:
                    continue
                if str(fact.get("scope_id", "problem")) != visible_scope:
                    continue
                path = str(fact.get("path", "")).strip()
                if path:
                    return path
    return None


def _visible_scopes_for_goal(problem: ProblemIR, scope_id: str) -> tuple[str, ...]:
    """返回当前 scope 可读的 scope 链：自身 -> 父级 -> problem。"""
    parents = {
        str(item.get("scope_id")): item.get("parent")
        for item in _scope_payload(problem)
        if isinstance(item, Mapping) and item.get("scope_id")
    }
    result: list[str] = []
    current = scope_id or "problem"
    while current and current not in result:
        result.append(current)
        parent = parents.get(current)
        if parent is None:
            break
        current = str(parent)
    if "problem" not in result:
        result.append("problem")
    return tuple(result)


def _visible_scopes_from_payload(payload: Mapping[str, Any], scope_id: str) -> tuple[str, ...]:
    """返回 canonical payload 中当前 scope 可读的 scope 链。"""
    parents = {
        str(item.get("scope_id")): item.get("parent")
        for item in payload.get("scopes", []) or []
        if isinstance(item, Mapping) and item.get("scope_id")
    }
    result: list[str] = []
    current = scope_id or "problem"
    while current and current not in result:
        result.append(current)
        parent = parents.get(current)
        if parent is None:
            break
        current = str(parent)
    if "problem" not in result:
        result.append("problem")
    return tuple(result)


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


def _runtime_expression_value(value: Any) -> Any:
    """把 runtime 表达式位置中的 canonical symbol handle 压成符号名。"""

    if isinstance(value, str) and value.startswith("symbol:"):
        return _handle_name(value)
    return value


def _runtime_definition_value(value: Any) -> Any:
    """把 runtime PointRef definition 中的 canonical handles 压成旧短名。"""

    if isinstance(value, str):
        if re.match(r"^(point|line|segment|ray|function|symbol|angle|circle|polygon):", value):
            return _handle_name(value)
        return value
    if isinstance(value, list):
        return [_runtime_definition_value(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _runtime_definition_value(item)
            for key, item in value.items()
        }
    return value


def _segment_endpoint_names_from_handle(value: str) -> Any:
    """把 canonical segment handle 转成旧 length_squared 条件的端点数组。"""

    name = _handle_name(value)
    if len(name) == 2 and name.isalpha():
        return [name[0], name[1]]
    return value


__all__ = [
    "RuntimeProjection",
    "problem_to_llm_payload",
    "to_llm_problem_payload",
    "to_runtime_problem_ir",
]
