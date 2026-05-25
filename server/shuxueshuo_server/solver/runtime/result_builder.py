"""从 QuestionGoal 构建 SolverResult.answers。

ResultBuilder 是 Phase 3 新增的答案汇总层。Planner 只负责生成 StepPlan，executor
只负责执行 method 和写 RuntimeContext；最终每一问输出哪些字段，由 ProblemIR 的
QuestionGoal 决定。
"""

from __future__ import annotations

from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.runtime.context import RuntimeContext
from shuxueshuo_server.solver.runtime.models import PlanExecutionResult


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
                typed_value = context.read_path(
                    goal.target_path,
                    from_scope_id=goal.question_id,
                    expected_type=goal.value_type,
                )
            except (KeyError, PermissionError, TypeError, ValueError) as exc:
                if goal.required:
                    raise ResultBuilderError(
                        f"required answer goal {goal.id} failed: {exc}"
                    ) from exc
                continue
            answers.setdefault(goal.question_id, {})[goal.answer_key] = (
                context.to_answer_value(typed_value.value)
            )
        return answers
