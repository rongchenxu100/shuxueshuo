"""从 QuestionGoal 构建 SolverResult.answers。

ResultBuilder 是 Phase 3 新增的答案汇总层。Planner 只负责生成 StepPlan，executor
只负责执行 method 和写 RuntimeContext；最终每一问输出哪些字段，由 ProblemIR 的
QuestionGoal 决定。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sympy as sp

from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import ContextPath, PlanExecutionResult, TypedValue


class ResultBuilderError(RuntimeError):
    """答案收集失败时抛出的错误。"""


class ResultBuilder:
    """按 QuestionGoal 从 RuntimeContext 中读取最终答案。"""

    def build(
        self,
        context: RuntimeContext,
        execution: PlanExecutionResult,
        question_goals: list[QuestionGoal],
    ) -> dict[str, dict[str, object]]:
        """构建 ``SolverResult.answers``。

        ``execution`` 当前只作为接口边界保留：后续 ResultBuilder 可以用它补充
        method provenance 或只收集执行过步骤产生的结果。首版答案值仍以
        RuntimeContext 为唯一事实源。
        """
        _ = execution
        answers: dict[str, dict[str, object]] = {}
        for goal in question_goals:
            try:
                typed_value = _read_goal_value(context, goal)
            except (KeyError, PermissionError, TypeError, ValueError) as exc:
                if goal.required:
                    raise ResultBuilderError(
                        f"required answer goal {goal.id} failed: {exc}"
                    ) from exc
                continue
            value = typed_value.value
            try:
                _validate_resolved_answer_value(goal, typed_value)
            except ResultBuilderError:
                if goal.required:
                    raise
                continue
            if typed_value.type == "PointList":
                value = _sorted_point_list(value)
            answers.setdefault(goal.question_id, {})[goal.answer_key] = context.to_answer_value(value)
        return answers

    def build_from_verified_goal_results(
        self,
        context: RuntimeContext,
        question_goals: list[QuestionGoal],
        goal_results: Mapping[str, TypedValue],
    ) -> dict[str, dict[str, object]]:
        """Serialize exact typed results selected by canonical ``answer_from``.

        Scope-native execution already proved the producer, return, closure,
        and provenance.  Reading Context paths again would reintroduce a
        second answer-selection authority, especially when an ancestor entity
        intentionally remains open while a child Goal publishes a closed
        result.
        """

        answers: dict[str, dict[str, object]] = {}
        for goal in question_goals:
            typed_value = goal_results.get(goal.id)
            if typed_value is None:
                if goal.required:
                    raise ResultBuilderError(
                        f"required answer goal {goal.id} has no verified result"
                    )
                continue
            compatible = typed_value.type == goal.value_type or (
                goal.value_type == "Point"
                and typed_value.type == "PointList"
            )
            if not compatible:
                if goal.required:
                    raise ResultBuilderError(
                        f"required answer goal {goal.id} expected "
                        f"{goal.value_type}, got {typed_value.type}"
                    )
                continue
            try:
                _validate_resolved_answer_value(goal, typed_value)
            except ResultBuilderError:
                if goal.required:
                    raise
                continue
            value = typed_value.value
            if typed_value.type == "PointList":
                value = _sorted_point_list(value)
            answers.setdefault(goal.question_id, {})[goal.answer_key] = (
                context.to_answer_value(value)
            )
        return answers


def _read_goal_value(context: RuntimeContext, goal: QuestionGoal) -> TypedValue:
    """Read the verified Goal publication, then its entity target.

    A scoped transaction can leave an ancestor entity in an open state while
    publishing a closed Goal-local answer. Candidate-producing methods may
    publish a PointList for a Point Goal, which remains a typed compatibility
    fallback before reading the named entity state.
    """
    publication_path = _output_answer_path(context, goal)
    publication_types = (
        ("Point", "PointList")
        if goal.value_type == "Point"
        else (goal.value_type,)
    )
    for expected_type in publication_types:
        try:
            return context.read_path(
                publication_path,
                from_scope_id=goal.question_id,
                expected_type=expected_type,
            )
        except (KeyError, PermissionError, TypeError, ValueError):
            pass
    return context.read_path(
        goal.target_path,
        from_scope_id=goal.question_id,
        expected_type=goal.value_type,
    )


def _output_answer_path(context: RuntimeContext, goal: QuestionGoal) -> str:
    scope = context.get_scope(goal.question_id)
    if scope.scope_type == "problem":
        return f"$problem.outputs.{goal.answer_key}"
    if scope.scope_type == "question":
        return f"$question.{goal.question_id}.outputs.{goal.answer_key}"
    if scope.scope_type == "subquestion":
        return f"$subquestion.{goal.question_id}.outputs.{goal.answer_key}"
    parsed = ContextPath.parse(goal.target_path)
    return f"$step.{parsed.scope_id}.outputs.{goal.answer_key}"


def _sorted_point_list(value: Any) -> Any:
    """PointList 是解集语义，对外答案按坐标值稳定排序。"""
    if not isinstance(value, list):
        return value
    if not all(isinstance(point, tuple) and len(point) == 2 for point in value):
        return value
    return sorted(value, key=_point_sort_key)


def _point_sort_key(point: tuple[Any, Any]) -> tuple[Any, Any]:
    return (_expr_sort_key(point[0]), _expr_sort_key(point[1]))


def _expr_sort_key(value: Any) -> tuple[int, float | str]:
    expr = sp.sympify(value)
    if not expr.free_symbols:
        try:
            return (0, float(sp.N(expr)))
        except TypeError:
            pass
    return (1, sp.sstr(expr))


def _validate_resolved_answer_value(
    goal: QuestionGoal,
    typed_value: TypedValue,
) -> None:
    """Required scalar/point answers must be fully determined before reporting ok."""
    if goal.value_type not in {"Point", "PointList", "ParameterValue"}:
        return
    symbols = _free_symbol_names(typed_value.value)
    if not symbols:
        return
    symbol_text = ",".join(symbols)
    raise ResultBuilderError(
        "answer_unresolved: "
        f"goal={goal.id}; "
        f"answer_key={goal.answer_key}; "
        f"value_type={goal.value_type}; "
        f"unresolved_symbols={symbol_text}"
    )


def _free_symbol_names(value: Any) -> tuple[str, ...]:
    """Collect free SymPy symbols from nested answer values."""
    symbols: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                visit(key)
                visit(child)
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                visit(child)
            return
        try:
            expr = sp.sympify(item)
        except (TypeError, ValueError, sp.SympifyError):
            return
        symbols.update(symbol.name for symbol in expr.free_symbols)

    visit(value)
    return tuple(sorted(symbols))
