import sympy as sp

from shuxueshuo_server.solver import load_expected_answers, load_problem_ir, solve_problem
from shuxueshuo_server.solver.family import QUADRATIC_PATH_MINIMUM_FAMILY
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
    QuadraticPathMinimumPlannerV15,
)


FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
HEXI_EXPECTED = "tests/solver/expected/tj-2026-hexi-yimo-25.expected.json"
METHODS_USED = [
    "quadratic_axis_from_relation",
    "quadratic_from_constraints",
    "right_angle_equal_length_candidates",
    "select_point_by_quadrant_constraint",
    "parameter_from_segment_length",
    "quadratic_from_constraints",
    "midpoint_point",
    "two_moving_points_path_reduction",
    "broken_path_straightening_candidates",
    "select_straightening_candidate",
    "distance_between_points",
    "parameter_from_minimum_value",
    "quadratic_from_constraints",
    "line_intersection_point",
]
HEXI_METHODS_USED = [
    "quadratic_from_constraints",
    "quadratic_vertex_point",
    "quadratic_from_constraints",
    "quadratic_y_axis_intercept_point",
    "right_angle_equal_length_candidates",
    "filter_point_candidates_by_quadratic_curve",
    "parameter_from_curve_point_on_quadratic",
    "quadratic_from_constraints",
    "point_on_parabola_at_x",
    "weighted_axis_path_triangle_transform",
    "linked_broken_path_geometric_minimum",
]


def test_runtime_orchestrator_solves_nankai_25_with_v15_runtime() -> None:
    problem = load_problem_ir(FIXTURE)
    expected = load_expected_answers(EXPECTED)
    result = solve_problem(
        problem,
        runtime_config=SolverRuntimeConfig(planner_mode="deterministic"),
    )

    assert problem.expected_answers == {}
    assert result.status == "ok"
    assert result.solver_family == "QuadraticPathMinimumSolver"
    assert result.methods_used == METHODS_USED
    assert all(check.ok for check in result.checks)
    assert result.trace is not None
    assert len(result.trace.steps) == len(METHODS_USED)
    q1_parameter_index = result.methods_used.index("parameter_from_segment_length")
    quadratic_indexes = [
        index
        for index, method_id in enumerate(result.methods_used)
        if method_id == "quadratic_from_constraints"
    ]
    q1_parabola_index = quadratic_indexes[1]
    assert q1_parameter_index < q1_parabola_index
    assert result.methods_used.index("midpoint_point") > q1_parabola_index
    assert "two_moving_points_path_reduction" in result.methods_used
    assert "square_opposite_point" not in result.methods_used

    axis_point = next(key for key in expected["i"] if key != "parabola")
    result_point = next(key for key in expected["ii_2"] if key != "parabola")

    assert result.answers["i"][axis_point] == expected["i"][axis_point]
    assert sp.simplify(sp.sympify(result.answers["i"]["parabola"]) - sp.sympify(expected["i"]["parabola"])) == 0

    assert sp.simplify(sp.sympify(result.answers["ii_1"]["parabola"]) - sp.sympify(expected["ii_1"]["parabola"])) == 0
    assert result.answers["ii_1"]["min_value"] == expected["ii_1"]["min_value"]

    assert sp.simplify(sp.sympify(result.answers["ii_2"]["parabola"]) - sp.sympify(expected["ii_2"]["parabola"])) == 0
    assert result.answers["ii_2"][result_point] == expected["ii_2"][result_point]


def test_runtime_orchestrator_solves_hexi_25_with_weighted_runtime() -> None:
    problem = load_problem_ir(HEXI_FIXTURE)
    expected = load_expected_answers(HEXI_EXPECTED)
    result = solve_problem(
        problem,
        runtime_config=SolverRuntimeConfig(planner_mode="deterministic"),
    )

    assert problem.expected_answers == {}
    assert result.status == "ok"
    assert result.solver_family == "QuadraticWeightedPathMinimumSolver"
    assert result.methods_used == HEXI_METHODS_USED
    assert all(check.ok for check in result.checks)
    assert result.trace is not None
    assert len(result.trace.steps) == len(HEXI_METHODS_USED)

    assert result.answers == expected
    assert result.answers["i"]["P"] == expected["i"]["P"]
    assert result.answers["ii"]["D"] == expected["ii"]["D"]
    assert result.answers["iii"]["b"] == expected["iii"]["b"]
    assert "parabola" not in result.answers["i"]
    assert "b" not in result.answers["ii"]
    assert "N" not in result.answers["iii"]
    assert "weighted_axis_path_triangle_transform" in result.methods_used
    assert "linked_broken_path_geometric_minimum" in result.methods_used


def test_unsupported_problem_returns_unsupported() -> None:
    problem = load_problem_ir(FIXTURE)
    unsupported = type(problem)(
        problem_id="unsupported",
        pattern="moving-point-rotation-area",
        problem_type=problem.problem_type,
        symbols=problem.symbols,
    )

    result = solve_problem(unsupported)

    assert result.status == "unsupported"
    assert result.solver_family is None


def test_runtime_orchestrator_fails_when_planner_provider_is_missing() -> None:
    """family 命中但没有 planner provider 时，应返回可读失败原因。"""
    problem = load_problem_ir(FIXTURE)

    result = RuntimeOrchestrator(
        planner_providers={},
        default_planner_provider=None,
    ).solve(problem)

    assert result.status == "failed"
    assert result.solver_family == "QuadraticPathMinimumSolver"
    assert "planner provider not found" in result.errors[0]


def test_runtime_orchestrator_builds_generic_planner_inputs() -> None:
    """Orchestrator 应构造完整 PlannerInputs 再调用 GenericPlanner。"""
    problem = load_problem_ir(FIXTURE)
    captured = {}

    def provider(context):
        class CapturingPlanner:
            def plan(self, inputs):
                captured["inputs"] = inputs
                return QuadraticPathMinimumPlannerV15().plan(context)

        return CapturingPlanner()

    result = RuntimeOrchestrator(
        planner_providers={QUADRATIC_PATH_MINIMUM_FAMILY.family_id: provider},
    ).solve(problem)

    assert result.status == "ok"
    inputs = captured["inputs"]
    assert inputs.problem_id == "tj-2026-nankai-yimo-25"
    assert inputs.family_spec is QUADRATIC_PATH_MINIMUM_FAMILY
    assert inputs.question_goals
    assert not hasattr(inputs, "planner_goals")
    assert inputs.context_inventory.planning_signals
    assert inputs.context_inventory.find_path("$problem.points.D") is not None
    assert inputs.method_specs.require("right_angle_equal_length_candidates")


def test_orchestrator_no_longer_reads_planner_answer_paths() -> None:
    """答案由 QuestionGoal/ResultBuilder 收集，不再由 planner 决定。"""

    class PlannerWithExplodingAnswerPaths(QuadraticPathMinimumPlannerV15):
        def answer_paths(self):
            raise AssertionError("orchestrator should not call planner.answer_paths")

    problem = load_problem_ir(FIXTURE)

    def provider(context):
        class Adapter:
            def plan(self, inputs):
                return PlannerWithExplodingAnswerPaths().plan(context)

            def answer_paths(self):
                raise AssertionError("orchestrator should not call planner.answer_paths")

        return Adapter()

    result = RuntimeOrchestrator(
        planner_providers={QUADRATIC_PATH_MINIMUM_FAMILY.family_id: provider},
    ).solve(problem)

    assert result.status == "ok"
    assert result.answers["ii_2"]["G"] == ["4", "-13/3"]
