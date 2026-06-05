from __future__ import annotations

import sympy as sp

from shuxueshuo_server.solver import load_expected_answers, load_problem_ir, solve_problem
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


NANKAI_FIXTURE = "../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"
NANKAI_EXPECTED = "tests/solver/expected/tj-2026-nankai-yimo-25.expected.json"
HEXI_FIXTURE = "../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"
HEXI_EXPECTED = "tests/solver/expected/tj-2026-hexi-yimo-25.expected.json"


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
