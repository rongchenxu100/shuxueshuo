from __future__ import annotations

import json
from pathlib import Path

import sympy as sp

from shuxueshuo_server.solver import load_expected_answers, load_problem_ir, solve_problem
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.projection import problem_from_canonical_input


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
HEXI_EXPECTED = "tests/solver/expected/tj-2026-hexi-yimo-25.expected.json"
XIQING_FIXTURE = "../internal/solver-fixtures/tj-2026-xiqing-yimo-25.json"
XIQING_EXPECTED = "tests/solver/expected/tj-2026-xiqing-yimo-25.expected.json"
HEPING_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-yimo-25.json"
HEPING_EXPECTED = "tests/solver/expected/tj-2026-heping-yimo-25.expected.json"
HEPING_ERMO_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-ermo-25.json"
HEPING_ERMO_EXPECTED = "tests/solver/expected/tj-2026-heping-ermo-25.expected.json"


def test_strategy_recorded_solves_nankai_without_deterministic_planner(monkeypatch) -> None:
    """生产 Strategy recorded 路径不应调用南开 deterministic template。"""
    from shuxueshuo_server.solver.runtime.quadratic_path_planner import (
        QuadraticPathMinimumPlannerV15,
    )

    monkeypatch.setattr(
        QuadraticPathMinimumPlannerV15,
        "plan",
        lambda self, context: (_ for _ in ()).throw(
            AssertionError("deterministic Nankai planner must not run")
        ),
    )
    result = solve_problem(
        load_problem_ir(NANKAI_FIXTURE),
        runtime_config=SolverRuntimeConfig(
            planner_mode="strategy",
            llm_provider="recorded",
        ),
    )
    expected = load_expected_answers(NANKAI_EXPECTED)

    assert result.status == "ok", result.errors
    assert result.answers["i"]["D"] == expected["i"]["D"]
    assert sp.simplify(
        sp.sympify(result.answers["ii_2"]["parabola"])
        - sp.sympify(expected["ii_2"]["parabola"])
    ) == 0
    assert result.answers["ii_2"]["G"] == expected["ii_2"]["G"]


def test_strategy_recorded_solves_hexi_without_deterministic_planner(monkeypatch) -> None:
    """生产 Strategy recorded 路径不应调用河西 deterministic template。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(
            AssertionError("deterministic Hexi planner must not run")
        ),
    )
    result = solve_problem(
        load_problem_ir(HEXI_FIXTURE),
        runtime_config=SolverRuntimeConfig(
            planner_mode="strategy",
            llm_provider="recorded",
        ),
    )

    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEXI_EXPECTED)
    assert "weighted_axis_path_triangle_transform" in result.methods_used
    assert "linked_broken_path_minimum_expression" in result.methods_used


def test_strategy_recorded_solves_xiqing_without_deterministic_planner(monkeypatch) -> None:
    """西青只通过 Strategy recorded 链路求解，不新增 deterministic slice。"""
    from shuxueshuo_server.solver.runtime.hexi_weighted_path_planner import (
        Hexi25WeightedPathPlannerV15,
    )

    monkeypatch.setattr(
        Hexi25WeightedPathPlannerV15,
        "plan",
        lambda self, inputs: (_ for _ in ()).throw(
            AssertionError("deterministic Hexi planner must not run")
        ),
    )
    result = solve_problem(
        load_problem_ir(XIQING_FIXTURE),
        runtime_config=SolverRuntimeConfig(
            planner_mode="strategy",
            llm_provider="recorded",
        ),
    )

    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(XIQING_EXPECTED)
    assert "parameter_from_segment_length" in result.methods_used
    assert "weighted_axis_path_triangle_transform" in result.methods_used
    assert "linked_broken_path_minimum_expression" in result.methods_used
    assert "parameter_from_expression_value" in result.methods_used


def test_strategy_recorded_solves_heping_without_deterministic_planner() -> None:
    """和平只通过 Strategy recorded 链路求解，不新增 deterministic slice。"""
    result = solve_problem(
        load_problem_ir(HEPING_FIXTURE),
        runtime_config=SolverRuntimeConfig(
            planner_mode="strategy",
            llm_provider="recorded",
        ),
    )

    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEPING_EXPECTED)
    assert "angle_sum_equal_angle_candidates" in result.methods_used
    assert "axis_intercept_from_equal_acute_angles" in result.methods_used
    assert "line_parabola_second_intersection_point" in result.methods_used
    assert "equal_length_ray_point" in result.methods_used


def test_strategy_recorded_solves_heping_ermo_without_deterministic_planner() -> None:
    """和平二模只通过 Strategy recorded 链路求解，不新增 deterministic slice。"""
    result = solve_problem(
        load_problem_ir(HEPING_ERMO_FIXTURE),
        runtime_config=SolverRuntimeConfig(
            planner_mode="strategy",
            llm_provider="recorded",
        ),
    )

    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEPING_ERMO_EXPECTED)
    assert "quadratic_axis_parameterized_point" in result.methods_used
    assert "square_adjacent_vertex_from_side" in result.methods_used
    assert "point_candidates_from_curve_point_condition" in result.methods_used
    assert "square_reflection_path_minimum_expression" not in result.methods_used
    assert "square_path_dimension_reduction" in result.methods_used
    assert "parameterized_point_locus_line" in result.methods_used
    assert "broken_path_straightening_candidates" in result.methods_used
    assert "select_straightening_candidate" in result.methods_used
    assert "distance_between_points" in result.methods_used
    assert "evaluate_point_at_parameter" in result.methods_used
    assert "line_locus_minimum_point" in result.methods_used
    assert "square_reflection_extremal_axis_point" not in result.methods_used


def test_strategy_recorded_accepts_point_goal_when_solver_outputs_point_list() -> None:
    """题目解析若把多解点误标成 Point，执行层仍可用 PointList 答案满足它。"""
    raw = json.loads(Path(HEPING_ERMO_FIXTURE).read_text(encoding="utf-8"))["input"]
    for goal in raw["question_goals"]:
        if goal["handle"] == "answer:i_2.E":
            goal["value_type"] = "Point"
            goal["target_handle"] = "point:i_2:E"
            goal["description"] = "第（Ⅰ）②问输出点 E 的坐标"
            break
    problem = problem_from_canonical_input(raw)
    result = solve_problem(
        problem,
        runtime_config=SolverRuntimeConfig(
            planner_mode="strategy",
            llm_provider="recorded",
        ),
    )

    assert result.status == "ok", result.errors
    assert result.answers == load_expected_answers(HEPING_ERMO_EXPECTED)
