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
@pytest.mark.parametrize("case", ["q01", "q03", "q07", "q08"])
@pytest.mark.parametrize("sample", [1, 2])
def test_real_planner_closes_representatives(case, sample, tmp_path):
    server = Path(__file__).resolve().parents[2]
    fixtures = server / "tests/solver/fixtures"
    result, runtime = run(
        gold=fixtures / f"math-notation-v1/basic-inequality/{case}.json",
        problem_ir=fixtures / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
        output=tmp_path / f"deepseek-{case}-{sample}",
        mode="deepseek",
    )
    expected = json.loads(
        (fixtures / f"basic-inequality-problem-ir/v1/{case}/expected.json").read_text()
    )
    assert result.status == "ok", result.to_dict()
    assert result.answers == {
        "problem": {"maximum" if case == "q01" else "minimum": expected["answer"]}
    }
    assert runtime.last_success_artifacts is not None
    assert runtime.last_success_artifacts.verified_functional_execution is not None
    assert all(check.ok for check in result.checks)
