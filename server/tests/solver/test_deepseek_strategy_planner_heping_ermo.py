"""和平二模 25 的 Strategy Planner 线上链路测试。

默认测试只检查 fixture/projection/family，不访问网络。真实 DeepSeek 联调需显式开启：

    cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
      RUN_DEEPSEEK_HEPING_ERMO_STRATEGY_PLANNER=1 \
      uv run pytest tests/solver/test_deepseek_strategy_planner_heping_ermo.py -q -s
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from shuxueshuo_server.solver import (
    load_expected_answers,
    load_problem_ir,
    solve_problem,
)
from shuxueshuo_server.solver.family import (
    QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_planner import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
)


RUN_DEEPSEEK_HEPING_ERMO_STRATEGY_PLANNER = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_STRATEGY_PLANNER") == "1"
    and os.getenv("RUN_DEEPSEEK_HEPING_ERMO_STRATEGY_PLANNER") == "1"
)
ROOT = Path(__file__).resolve().parents[3]
HEPING_ERMO_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-ermo-25.json"
HEPING_ERMO_EXPECTED = "tests/solver/expected/tj-2026-heping-ermo-25.expected.json"
DEBUG_DIR = ROOT / "internal/solver-runs/strategy-planner-deepseek-heping-ermo"


def test_heping_ermo_strategy_probe_uses_square_reflection_family() -> None:
    """和平二模由 ProblemIR metadata 命中正方形反射路径最值 family。"""
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)

    assert inputs.family_spec.family_id == QUADRATIC_SQUARE_REFLECTION_PATH_MINIMUM_FAMILY.family_id
    assert inputs.family_spec.match.matches(problem)


def test_heping_ermo_strategy_payload_contains_text_faithful_problem_ir() -> None:
    """和平二模 prompt payload 应来自 canonical ProblemIR，且不暴露 runtime path/expected。"""
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = problem_to_llm_payload(problem)
    payload = StrategyPayloadBuilder().build(inputs, problem_payload=llm_problem)
    prompt = StrategyPromptRenderer().render(payload)

    method_ids = {
        method["method_id"]
        for method in payload["method_catalog"]["methods"]
    }
    recipe_ids = {
        recipe["recipe_id"]
        for recipe in payload["recipe_catalog"]["recipes"]
    }
    fact_handles = {fact["handle"] for fact in payload["problem_ir"]["facts"]}
    entity_handles = {entity["handle"] for entity in payload["problem_ir"]["entities"]}

    assert "quadratic_from_constraints" in method_ids
    assert "quadratic_vertex_point" in method_ids
    assert "quadratic_x_axis_intercept_point" in method_ids
    assert "parameter_from_expression_value" in method_ids
    assert "quadratic_axis_parameterized_point" in method_ids
    assert "square_adjacent_vertex_from_side" in method_ids
    assert "point_candidates_from_curve_point_condition" in method_ids
    assert "midpoint_point" in method_ids
    old_coarse_method_id = "square_axis_side_curve_point" + "_candidates"
    assert old_coarse_method_id not in method_ids
    old_coarse_recipe_id = "axis_square_vertex_curve_point" + "_candidates"
    assert old_coarse_recipe_id not in recipe_ids
    assert "broken_path_straightening_minimum_expression" in recipe_ids
    assert "fact:ii:path_minimum_value_given" in fact_handles
    assert "fact:ii:square_AEKG" in fact_handles
    assert "point:ii:F" in entity_handles
    assert "point:ii:H" in entity_handles
    assert "HF+FM+MG" in prompt.user
    assert "$question" not in prompt.user
    assert "target_path" not in prompt.user
    assert "expected" not in prompt.user


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_ERMO_STRATEGY_PLANNER,
    reason="DeepSeek Heping ermo strategy planner integration is opt-in",
)
def test_deepseek_strategy_planner_heping_ermo_full_loop() -> None:
    """真实 DeepSeek 输出 StepIntent 后，必须完整执行出和平二模答案。"""
    _reset_debug_dir(DEBUG_DIR)
    problem = load_problem_ir(HEPING_ERMO_FIXTURE)
    expected = load_expected_answers(HEPING_ERMO_EXPECTED)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        llm_debug_dir=str(DEBUG_DIR),
        allow_same_problem_few_shot=False,
    )

    result = solve_problem(problem, runtime_config=config)

    print("DeepSeek Heping ermo strategy status:", result.status)
    print(json.dumps(result.answers, ensure_ascii=False, indent=2))
    if result.run_log:
        print(json.dumps(result.run_log, ensure_ascii=False, indent=2, default=str))
    assert result.status == "ok", result.errors
    assert result.answers == expected


def _reset_debug_dir(path: Path) -> None:
    """真实 LLM 测试开始前清空 debug 目录，避免旧 attempt 混入本轮结果。"""
    if path.exists():
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)
