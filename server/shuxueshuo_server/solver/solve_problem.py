"""CLI for running Method Solver fixtures."""

from __future__ import annotations

import argparse
import json
import sys

from shuxueshuo_server.solver.engine import solve_problem
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.config import (
    SolverRuntimeConfig,
    SolverRuntimeConfigError,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMClientConfigurationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve a hand-written ProblemIR fixture.")
    parser.add_argument("--fixture", required=True, help="Path to a ProblemIR fixture JSON file.")
    parser.add_argument(
        "--planner",
        choices=("deterministic", "strategy"),
        help="Planner mode. Defaults to strategy.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("recorded", "deepseek"),
        help="Strategy provider. recorded skips real LLM and uses executable StepIntent fixtures.",
    )
    parser.add_argument(
        "--llm-model",
        help="Override the provider model when --planner strategy --llm-provider deepseek is selected.",
    )
    parser.add_argument(
        "--llm-max-attempts",
        type=int,
        help="Maximum DeepSeek planning attempts when --planner strategy is selected.",
    )
    parser.add_argument(
        "--llm-debug-dir",
        help="Directory for per-attempt LLM planner debug artifacts.",
    )
    args = parser.parse_args(argv)

    try:
        runtime_config = SolverRuntimeConfig.from_sources(
            planner_mode=args.planner,
            llm_provider=args.llm_provider,
            llm_model=args.llm_model,
            max_llm_attempts=args.llm_max_attempts,
            llm_debug_dir=args.llm_debug_dir,
        )
        problem = load_problem_ir(args.fixture)
        result = solve_problem(problem, runtime_config=runtime_config)
    except (SolverRuntimeConfigError, LLMClientConfigurationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    payload = result.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not result.ok:
        failed = [check.name for check in result.checks if not check.ok]
        if failed:
            print("Failed checks: " + ", ".join(failed), file=sys.stderr)
        if result.errors:
            print("Errors: " + "; ".join(result.errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
