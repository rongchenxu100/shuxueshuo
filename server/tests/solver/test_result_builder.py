"""ResultBuilder 答案收集测试。"""

from __future__ import annotations

import pytest
import sympy as sp

from shuxueshuo_server.solver.fixtures import load_expected_answers, load_problem_ir
from shuxueshuo_server.solver.math_kernel import SympyKernel
from shuxueshuo_server.solver.problem_models import QuestionGoal
from shuxueshuo_server.solver.question_goals import extract_question_goals
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.executor import (
    DeclarationValidator,
    InvocationExecutor,
)
from shuxueshuo_server.solver.runtime.method_specs import MethodSpecRegistry
from shuxueshuo_server.solver.runtime.methods import default_stateless_registry
from shuxueshuo_server.solver.runtime.models import PlanExecutionResult, TypedValue
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)
from shuxueshuo_server.solver.runtime.result_builder import (
    ResultBuilder,
    ResultBuilderError,
)


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"


def _executed_nankai_context():
    """执行完整南开 StepPlan，返回可供 ResultBuilder 读取的 context。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    kernel = SympyKernel()
    context = ContextBuilder(kernel).build(problem)
    specs = MethodSpecRegistry.load_from_code()
    executor = InvocationExecutor(
        specs,
        methods=default_stateless_registry(),
        kernel=kernel,
    )
    output = QuadraticPathMinimumPlannerV15().plan(context)
    DeclarationValidator().validate_declarations(context, output.context_declarations)
    context.apply_declarations(output.context_declarations)
    execution = executor.execute_plan(context, output.step_plans)
    return problem, context, execution


def test_result_builder_collects_nankai_answers_from_question_goals() -> None:
    """ResultBuilder 应输出与当前黄金答案完全一致的 JSON 结构。"""
    problem, context, execution = _executed_nankai_context()

    answers = ResultBuilder().build(
        context,
        execution,
        extract_question_goals(problem),
    )

    assert answers == load_expected_answers(EXPECTED)


def test_result_builder_fails_for_missing_required_goal() -> None:
    """required=true 的目标缺失时，solver 应能拿到清晰失败原因。"""
    _problem, context, execution = _executed_nankai_context()
    goals = [
        QuestionGoal(
            question_id="ii_1",
            id="missing.required",
            answer_key="missing",
            target_path="$subquestion.ii_1.outputs.missing",
            value_type="ParameterValue",
            required=True,
        )
    ]

    with pytest.raises(ResultBuilderError, match="missing.required"):
        ResultBuilder().build(context, execution, goals)


def test_result_builder_fails_for_type_mismatch() -> None:
    """value_type 与目标路径实际类型不一致时必须失败。"""
    _problem, context, execution = _executed_nankai_context()
    goals = [
        QuestionGoal(
            question_id="ii_2",
            id="type.mismatch",
            answer_key="G",
            target_path="$question.ii.points.G",
            value_type="Parabola",
            required=True,
        )
    ]

    with pytest.raises(ResultBuilderError, match="type.mismatch"):
        ResultBuilder().build(context, execution, goals)


def test_result_builder_skips_missing_optional_goal() -> None:
    """required=false 的目标缺失时跳过，不污染 answers。"""
    _problem, context, execution = _executed_nankai_context()
    goals = [
        QuestionGoal(
            question_id="ii_1",
            id="missing.optional",
            answer_key="optional",
            target_path="$subquestion.ii_1.outputs.optional",
            value_type="ParameterValue",
            required=False,
        )
    ]

    answers = ResultBuilder().build(context, execution, goals)

    assert answers == {}


def test_result_builder_sorts_point_list_answers_by_coordinate_value() -> None:
    """PointList 是无序解集，对外 answers 应稳定按坐标值排序。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    context = ContextBuilder(SympyKernel()).build(problem)
    sqrt6 = sp.sqrt(6)
    context.write_path(
        "$question.i.outputs.point_list",
        TypedValue("PointList", [(-1, 2 + sqrt6), (-1, 2 - sqrt6)], source="test"),
        from_scope_id="i",
        allow_overwrite=True,
    )
    goals = [
        QuestionGoal(
            question_id="i",
            id="i.point_list",
            answer_key="E",
            target_path="$question.i.outputs.point_list",
            value_type="PointList",
            required=True,
        )
    ]

    answers = ResultBuilder().build(context, PlanExecutionResult(), goals)

    assert answers == {"i": {"E": [["-1", "2 - sqrt(6)"], ["-1", "2 + sqrt(6)"]]}}


def test_result_builder_fails_required_point_answer_with_free_symbol() -> None:
    """最终 Point 答案不能残留动点参数，否则会误报求解成功。"""
    problem = load_problem_ir(NANKAI_FIXTURE)
    context = ContextBuilder(SympyKernel()).build(problem)
    context.write_path(
        "$question.i.outputs.unresolved_point",
        TypedValue(
            "Point",
            (sp.Integer(1), sp.Symbol("_axis_param_E")),
            source="test",
        ),
        from_scope_id="i",
    )
    goals = [
        QuestionGoal(
            question_id="i",
            id="answer:i.unresolved_point",
            answer_key="P",
            target_path="$question.i.outputs.unresolved_point",
            value_type="Point",
            required=True,
        )
    ]

    with pytest.raises(ResultBuilderError, match="answer_unresolved:.*_axis_param_E"):
        ResultBuilder().build(context, PlanExecutionResult(), goals)
