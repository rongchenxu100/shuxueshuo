"""和平 25 的 Strategy Planner 线上链路测试。

默认测试只检查 fixture/projection/recorded，不访问网络。真实 DeepSeek 联调需显式开启：

    cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
      RUN_DEEPSEEK_HEPING_STRATEGY_PLANNER=1 \
      uv run pytest tests/solver/test_deepseek_strategy_planner_heping.py -q -s
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
    QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_planner import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
)


RUN_DEEPSEEK_HEPING_STRATEGY_PLANNER = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_STRATEGY_PLANNER") == "1"
    and os.getenv("RUN_DEEPSEEK_HEPING_STRATEGY_PLANNER") == "1"
)
ROOT = Path(__file__).resolve().parents[3]
HEPING_FIXTURE = "../internal/solver-fixtures/tj-2026-heping-yimo-25.json"
HEPING_EXPECTED = "tests/solver/expected/tj-2026-heping-yimo-25.expected.json"
DEBUG_DIR = ROOT / "internal/solver-runs/strategy-planner-deepseek-heping"


def test_heping_strategy_probe_uses_equal_length_ray_family() -> None:
    """和平由 ProblemIR metadata 命中等长射线路径最值 family。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)

    assert inputs.family_spec.family_id == QUADRATIC_EQUAL_LENGTH_RAY_PATH_MINIMUM_FAMILY.family_id
    assert inputs.family_spec.match.matches(problem)


def test_heping_strategy_payload_contains_equal_length_ray_capabilities() -> None:
    """和平 prompt payload 应来自 canonical ProblemIR，且不暴露 runtime path/expected。"""
    problem = load_problem_ir(HEPING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = problem_to_llm_payload(problem)
    payload = StrategyPayloadBuilder().build(inputs, problem_payload=llm_problem)
    prompt = StrategyPromptRenderer().render(payload)

    method_ids = {
        method["method_id"]
        for method in payload["method_catalog"]["methods"]
    }
    fact_handles = {fact["handle"] for fact in payload["problem_ir"]["facts"]}

    assert "angle_sum_equal_angle_candidates" in method_ids
    assert "axis_intercept_from_equal_acute_angles" in method_ids
    assert "line_parabola_second_intersection_point" in method_ids
    assert "equal_length_ray_point" in method_ids
    assert "parameter_from_expression_value" in method_ids
    assert "fact:i_2:angle_sum_CBE_ACO_45" in fact_handles
    assert "fact:ii:M_on_segment_BC" in fact_handles
    assert "fact:ii:N_on_ray_CD" in fact_handles
    assert "fact:ii:CN_eq_CM" in fact_handles
    assert "fact:ii:G_on_ray_CD_with_CG_eq_CB" not in fact_handles
    assert "fact:problem:C_coordinate_value" not in fact_handles
    assert "fact:problem:D_coordinate_value" not in fact_handles
    assert "OM+BN" in prompt.user
    assert "$question" not in prompt.user
    assert "target_path" not in prompt.user
    assert "expected" not in prompt.user


def test_recorded_heping_strategy_step_intents_solve_expected_answers() -> None:
    """和平 recorded StepIntent 应完整执行出题面答案。"""
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


@pytest.mark.skipif(
    not RUN_DEEPSEEK_HEPING_STRATEGY_PLANNER,
    reason="DeepSeek Heping strategy planner integration is opt-in",
)
def test_deepseek_strategy_planner_heping_full_loop() -> None:
    """真实 DeepSeek 输出 StepIntent 后，必须完整执行出和平答案。"""
    _reset_debug_dir(DEBUG_DIR)
    problem = load_problem_ir(HEPING_FIXTURE)
    expected = load_expected_answers(HEPING_EXPECTED)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        llm_debug_dir=str(DEBUG_DIR),
        allow_same_problem_few_shot=False,
    )

    result = solve_problem(problem, runtime_config=config)

    print("DeepSeek Heping strategy status:", result.status)
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
