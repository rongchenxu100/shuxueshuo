"""Real DeepSeek FunctionalPlan opt-in for Hexi."""

from __future__ import annotations

import pytest

from _functional_opt_in_support import (
    FUNCTIONAL_OPT_IN_CASES,
    RUN_FUNCTIONAL,
    run_deepseek_functional_opt_in,
)


@pytest.mark.skipif(
    not RUN_FUNCTIONAL,
    reason="set RUN_LLM_INTEGRATION=1 RUN_DEEPSEEK_FUNCTIONAL_PLANNER=1",
)
def test_deepseek_functional_plan_solves_hexi() -> None:
    run_deepseek_functional_opt_in(FUNCTIONAL_OPT_IN_CASES["hexi"])
