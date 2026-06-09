"""题目输入模型。

本模块只描述 solver 的输入边界：题目被结构化抽取以后，应该以什么形状交给
SolverFamily。它不关心求解过程、method 调用、trace 或最终答案。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QuestionGoal:
    """题目某一问需要收集的最终答案目标。

    ``QuestionGoal`` 属于输入 IR 语义：它只说明“这一问最终要输出哪个字段，
    这个字段来自哪个 ContextPath”。它不保存答案值，也不描述求解步骤。

    - ``question_id``：goal 所属的大问或小问 id，例如 ``ii_1``；
    - ``id``：全题唯一的 goal id，便于错误定位；
    - ``answer_key``：写入 ``SolverResult.answers[question_id]`` 的字段名；
    - ``target_path``：执行完成后读取的 ContextPath；
    - ``value_type``：读取 target path 时要求的 runtime 类型；
    - ``required``：缺失时是否使求解失败。
    """

    question_id: str
    id: str
    answer_key: str
    target_path: str
    value_type: str
    required: bool = True


@dataclass(frozen=True)
class ProblemIR:
    """SolverFamily 的结构化题目输入。

    目前的 ``ProblemIR`` 主要来自手写 fixture；后续接入 LLM 抽取、题库解析或
    lesson spec 解析时，也应该尽量产出同一份 IR，避免 solver 主链路关心来源。

    - ``problem_id``：题目唯一标识；
    - ``pattern`` / ``problem_type``：粗粒度题型路由信息；
    - ``original_text``：题面原文，给 LLM Planner 判断小问语义和目标；
    - ``symbols`` / ``constraints`` / ``data``：由 RuntimeProjection 从
      canonical authored fixture 派生的 runtime-compatible view；新 fixture
      不再手写这些字段；
    - ``solver_config``：历史兼容字段。新 fixture 不再写 planner hints，运行时默认空字典；
    - ``expected_answers``：测试期望值，运行时求解不读取。
    """

    problem_id: str
    pattern: str
    problem_type: str
    symbols: list[str]
    symbol_roles: dict[str, str] = field(default_factory=dict)
    original_text: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    solver_config: dict[str, Any] = field(default_factory=dict)
    expected_answers: dict[str, Any] = field(default_factory=dict)
