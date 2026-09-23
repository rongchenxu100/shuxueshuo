"""Opt-in real Planner gate for the explicitly admitted Stage 4A path."""

import json
import os
from pathlib import Path

import pytest

from tools.run_basic_inequality_stage4a import run


@pytest.mark.live_llm
@pytest.mark.skipif(
    os.getenv("RUN_LLM_INTEGRATION") != "1", reason="set RUN_LLM_INTEGRATION=1"
)
def test_real_planner_closes_q01(tmp_path):
    server = Path(__file__).resolve().parents[2]
    fixtures = server / "tests/solver/fixtures"
    result, runtime = run(
        gold=fixtures / "math-notation-v1/basic-inequality/q01.json",
        problem_ir=fixtures / "basic-inequality-problem-ir/v1/q01/problem-ir.json",
        output=tmp_path / "deepseek-q01",
        mode="deepseek",
    )
    expected = json.loads(
        (fixtures / "basic-inequality-problem-ir/v1/q01/expected.json").read_text()
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {"problem": {"maximum": expected["answer"]}}
    assert runtime.last_success_artifacts is not None
    assert runtime.last_success_artifacts.verified_functional_execution is not None
    assert all(check.ok for check in result.checks)
