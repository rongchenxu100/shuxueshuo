"""QuestionGoal 解析与校验。

Phase 3 开始，最终答案结构不再由 planner 的 ``answer_paths()`` 决定，而是由
``ProblemIR.data.questions[].goals`` 明确声明。这个模块只做输入侧解析，不读取
RuntimeContext，也不验证答案是否已经求出。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shuxueshuo_server.solver.problem_models import ProblemIR, QuestionGoal
from shuxueshuo_server.solver.runtime.models import ContextPath


class QuestionGoalError(ValueError):
    """QuestionGoal 结构非法时抛出的错误。"""


def extract_question_goals(problem: ProblemIR) -> list[QuestionGoal]:
    """从 ProblemIR 的 question tree 中按题目顺序提取 QuestionGoal。

    这里会递归扫描 ``questions`` 和 ``subquestions``。解析阶段只校验结构、唯一性
    和 ContextPath 格式；路径是否存在、类型是否匹配，需要等 method 执行完成后由
    ResultBuilder 读取 RuntimeContext 时判断。
    """
    goals: list[QuestionGoal] = []
    seen_goal_ids: set[str] = set()
    seen_answer_keys: set[tuple[str, str]] = set()

    def visit(raw_question: Mapping[str, Any]) -> None:
        question_id = _required_string(raw_question, "id", owner="question")
        raw_goals = raw_question.get("goals", [])
        if not isinstance(raw_goals, list):
            raise QuestionGoalError(f"question {question_id} goals must be a list")
        for raw_goal in raw_goals:
            goal = _parse_goal(question_id, raw_goal)
            if goal.id in seen_goal_ids:
                raise QuestionGoalError(f"duplicate question goal id: {goal.id}")
            answer_key = (goal.question_id, goal.answer_key)
            if answer_key in seen_answer_keys:
                raise QuestionGoalError(
                    f"duplicate answer key in question {goal.question_id}: {goal.answer_key}"
                )
            seen_goal_ids.add(goal.id)
            seen_answer_keys.add(answer_key)
            goals.append(goal)
        raw_children = raw_question.get("subquestions", [])
        if not isinstance(raw_children, list):
            raise QuestionGoalError(f"question {question_id} subquestions must be a list")
        for child in raw_children:
            if not isinstance(child, Mapping):
                raise QuestionGoalError(f"subquestion of {question_id} must be an object")
            visit(child)

    raw_questions = problem.data.get("questions", [])
    if not isinstance(raw_questions, list):
        raise QuestionGoalError("ProblemIR.data.questions must be a list")
    for raw_question in raw_questions:
        if not isinstance(raw_question, Mapping):
            raise QuestionGoalError("question must be an object")
        visit(raw_question)
    return goals


def _parse_goal(question_id: str, raw_goal: object) -> QuestionGoal:
    """把单个 goal 字典转换成强类型 QuestionGoal。"""
    if not isinstance(raw_goal, Mapping):
        raise QuestionGoalError(f"goal in question {question_id} must be an object")
    goal_id = _required_string(raw_goal, "id", owner=f"question {question_id} goal")
    answer_key = _required_string(raw_goal, "answer_key", owner=goal_id)
    target_path = _required_string(raw_goal, "target_path", owner=goal_id)
    value_type = _required_string(raw_goal, "value_type", owner=goal_id)
    if "required" not in raw_goal:
        raise QuestionGoalError(f"goal {goal_id} missing required field: required")
    required = raw_goal["required"]
    if not isinstance(required, bool):
        raise QuestionGoalError(f"goal {goal_id} required must be boolean")
    try:
        ContextPath.parse(target_path)
    except ValueError as exc:
        raise QuestionGoalError(f"goal {goal_id} target_path is invalid: {target_path}") from exc
    return QuestionGoal(
        question_id=question_id,
        id=goal_id,
        answer_key=answer_key,
        target_path=target_path,
        value_type=value_type,
        required=required,
    )


def _required_string(raw: Mapping[str, Any], key: str, *, owner: str) -> str:
    """读取必填字符串字段，并给出带 owner 的错误信息。"""
    if key not in raw:
        raise QuestionGoalError(f"{owner} missing required field: {key}")
    value = raw[key]
    if not isinstance(value, str) or not value:
        raise QuestionGoalError(f"{owner} field {key} must be a non-empty string")
    return value
