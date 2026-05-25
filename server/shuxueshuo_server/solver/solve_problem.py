"""CLI for running Method Solver fixtures."""

from __future__ import annotations

import argparse
import json
import sys

from shuxueshuo_server.solver.engine import solve_problem
from shuxueshuo_server.solver.fixtures import load_problem_ir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve a hand-written ProblemIR fixture.")
    parser.add_argument("--fixture", required=True, help="Path to a ProblemIR fixture JSON file.")
    args = parser.parse_args(argv)

    problem = load_problem_ir(args.fixture)
    result = solve_problem(problem)
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
