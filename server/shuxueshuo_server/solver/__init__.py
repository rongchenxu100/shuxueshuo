"""Method Solver public interface, loaded lazily to keep checker imports isolated."""

from importlib import import_module

_EXPORT_MODULES = {
    "CheckResult": "contracts",
    "DerivationStep": "contracts",
    "DerivationTrace": "result_models",
    "EquationRecord": "result_models",
    "Fact": "result_models",
    "MethodResult": "result_models",
    "ProblemIR": "problem_models",
    "QuestionGoal": "problem_models",
    "QuestionGoalError": "question_goals",
    "SolverResult": "result_models",
    "extract_question_goals": "question_goals",
    "load_expected_answers": "fixtures",
    "load_problem_ir": "fixtures",
    "solve_problem": "engine",
    "solve_problem_ir_debug": "engine",
}


def __getattr__(name):
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))


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
    "solve_problem_ir_debug",
]
