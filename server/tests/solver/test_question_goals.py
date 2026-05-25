"""QuestionGoal 解析测试。

这些测试确保最终答案目标来自 ProblemIR 的 question tree，而不是 planner 内部
硬编码的 answer_paths。
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.problem_models import ProblemIR
from shuxueshuo_server.solver.question_goals import (
    QuestionGoalError,
    extract_question_goals,
)


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"


def _problem_with_data(problem: ProblemIR, data: dict) -> ProblemIR:
    """复制 ProblemIR，只替换 data，方便制造非法 goal 样例。"""
    return ProblemIR(
        problem_id=problem.problem_id,
        pattern=problem.pattern,
        problem_type=problem.problem_type,
        symbols=problem.symbols,
        constraints=problem.constraints,
        data=data,
        solver_config=problem.solver_config,
        expected_answers=problem.expected_answers,
    )


def test_extracts_nankai_question_goals_in_question_order() -> None:
    """canonical 南开 fixture 应按问题顺序声明最终答案目标。"""
    problem = load_problem_ir(NANKAI_FIXTURE)

    goals = extract_question_goals(problem)

    assert [(goal.question_id, goal.answer_key) for goal in goals] == [
        ("i", "D"),
        ("i", "parabola"),
        ("ii_1", "parabola"),
        ("ii_1", "min_value"),
        ("ii_2", "parabola"),
        ("ii_2", "G"),
    ]
    assert goals[0].target_path == "$problem.points.D"
    assert goals[-1].value_type == "Point"
    assert all(goal.required for goal in goals)
    assert problem.expected_answers == {}


def test_rejects_duplicate_goal_id() -> None:
    """goal.id 是全题唯一标识，重复会让错误定位变得模糊。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    data = deepcopy(problem.data)
    question_i = data["questions"][0]
    duplicate = dict(question_i["goals"][0])
    duplicate["answer_key"] = "D_copy"
    question_i["goals"].append(duplicate)

    with pytest.raises(QuestionGoalError, match="duplicate question goal id"):
        extract_question_goals(_problem_with_data(problem, data))


def test_rejects_duplicate_answer_key_in_same_question() -> None:
    """同一问下 answer_key 重复会覆盖 SolverResult.answers 字段。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    data = deepcopy(problem.data)
    question_i = data["questions"][0]
    duplicate = dict(question_i["goals"][0])
    duplicate["id"] = "i.axis_point.copy"
    question_i["goals"].append(duplicate)

    with pytest.raises(QuestionGoalError, match="duplicate answer key"):
        extract_question_goals(_problem_with_data(problem, data))


def test_rejects_invalid_target_path() -> None:
    """target_path 必须是合法 ContextPath，不能是裸答案或任意字符串。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    data = deepcopy(problem.data)
    data["questions"][0]["goals"][0]["target_path"] = "D=(1,0)"

    with pytest.raises(QuestionGoalError, match="target_path is invalid"):
        extract_question_goals(_problem_with_data(problem, data))
