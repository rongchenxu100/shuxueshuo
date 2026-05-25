"""Method Solver public interface."""

from shuxueshuo_server.solver.engine import solve_problem
from shuxueshuo_server.solver.fixtures import load_expected_answers, load_problem_ir
from shuxueshuo_server.solver.contracts import CheckResult, DerivationStep
from shuxueshuo_server.solver.problem_models import ProblemIR, QuestionGoal
from shuxueshuo_server.solver.question_goals import (
    QuestionGoalError,
    extract_question_goals,
)
from shuxueshuo_server.solver.result_models import (
    DerivationTrace,
    EquationRecord,
    Fact,
    MethodResult,
    SolverResult,
)

__all__ = [
    "CheckResult",
    "DerivationStep",
    "DerivationTrace",
    "EquationRecord",
    "Fact",
    "MethodResult",
    "ProblemIR",
    "QuestionGoal",
    "QuestionGoalError",
    "SolverResult",
    "extract_question_goals",
    "load_expected_answers",
    "load_problem_ir",
    "solve_problem",
]
