"""西青 25 的 Strategy Planner 线上链路测试。

默认测试只检查 fixture/projection/family，不访问网络。真实 DeepSeek 联调需显式开启：

    cd server && RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_STRATEGY_PLANNER=1 \
      RUN_DEEPSEEK_XIQING_STRATEGY_PLANNER=1 \
      uv run pytest tests/solver/test_deepseek_strategy_planner_xiqing.py -q -s
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
from shuxueshuo_server.solver.family import QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_planner import (
    StrategyPayloadBuilder,
    StrategyPromptRenderer,
    build_strategy_probe_inputs,
)


RUN_DEEPSEEK_XIQING_STRATEGY_PLANNER = (
    os.getenv("RUN_LLM_INTEGRATION") == "1"
    and os.getenv("RUN_DEEPSEEK_STRATEGY_PLANNER") == "1"
    and os.getenv("RUN_DEEPSEEK_XIQING_STRATEGY_PLANNER") == "1"
)
ROOT = Path(__file__).resolve().parents[3]
XIQING_FIXTURE = "../internal/solver-fixtures/tj-2026-xiqing-yimo-25.json"
XIQING_EXPECTED = "tests/solver/expected/tj-2026-xiqing-yimo-25.expected.json"
DEBUG_DIR = ROOT / "internal/solver-runs/strategy-planner-deepseek-xiqing"


def test_xiqing_strategy_probe_uses_weighted_family() -> None:
    """西青由 ProblemIR metadata 命中 weighted path family。"""
    problem = load_problem_ir(XIQING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)

    assert inputs.family_spec.family_id == QUADRATIC_WEIGHTED_PATH_MINIMUM_FAMILY.family_id
    assert inputs.family_spec.match.matches(problem)
    assert not inputs.family_spec.enabled_problem_ids


def test_xiqing_strategy_payload_contains_weight_2_problem_ir() -> None:
    """西青 prompt payload 应来自 canonical ProblemIR，且不暴露 runtime path/expected。"""
    problem = load_problem_ir(XIQING_FIXTURE)
    inputs = build_strategy_probe_inputs(problem)
    llm_problem = problem_to_llm_payload(problem)
    payload = StrategyPayloadBuilder().build(inputs, problem_payload=llm_problem)
    prompt = StrategyPromptRenderer().render(payload)

    method_ids = {
        method["method_id"]
        for method in payload["method_catalog"]["methods"]
    }
    fact_handles = {fact["handle"] for fact in payload["problem_ir"]["facts"]}

    assert "parameter_from_segment_length" in method_ids
    assert "weighted_axis_path_triangle_transform" in method_ids
    assert "linked_broken_path_minimum_expression" in method_ids
    assert "parameter_from_expression_value" in method_ids
    assert "fact:ii_2:path_minimum_value_given" in fact_handles
    assert "2DM+AM" in prompt.user
    assert "$question" not in prompt.user
    assert "target_path" not in prompt.user
    assert "expected" not in prompt.user


@pytest.mark.skipif(
    not RUN_DEEPSEEK_XIQING_STRATEGY_PLANNER,
    reason="DeepSeek Xiqing strategy planner integration is opt-in",
)
def test_deepseek_strategy_planner_xiqing_full_loop() -> None:
    """真实 DeepSeek 输出 StepIntent 后，必须完整执行出西青答案。"""
    _reset_debug_dir(DEBUG_DIR)
    problem = load_problem_ir(XIQING_FIXTURE)
    expected = load_expected_answers(XIQING_EXPECTED)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        llm_debug_dir=str(DEBUG_DIR),
        allow_same_problem_few_shot=False,
    )

    result = solve_problem(problem, runtime_config=config)

    print("DeepSeek Xiqing strategy status:", result.status)
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
