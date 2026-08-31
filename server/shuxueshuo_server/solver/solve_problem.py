"""CLI for verified Strategy bundles and explicit ProblemIR debug fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from shuxueshuo_server.solver.engine import solve_problem, solve_problem_ir_debug
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    VerifiedSolverProblemBundleLoader,
)
from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.config import (
    SolverRuntimeConfig,
    SolverRuntimeConfigError,
)
from shuxueshuo_server.solver.runtime.llm_clients import LLMClientConfigurationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Solve an accepted problem bundle or a deterministic debug fixture."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--fixture",
        help="ProblemIR fixture for the explicit deterministic debug entry.",
    )
    source.add_argument(
        "--accepted-context",
        help="Accepted problem-extraction-context/v3 JSON for Strategy solving.",
    )
    parser.add_argument(
        "--ancestor-context",
        action="append",
        default=[],
        help="Ancestor Context JSON in root-to-parent order; repeat for each ancestor.",
    )
    parser.add_argument(
        "--artifact-root",
        help="Content-addressed extraction artifact store for --accepted-context.",
    )
    parser.add_argument(
        "--planner",
        choices=("deterministic", "strategy"),
        help="Planner mode. Defaults to strategy.",
    )
    parser.add_argument(
        "--llm-provider",
        choices=("recorded", "deepseek"),
        help=(
            "Strategy provider. recorded skips real LLM and uses authored "
            "FunctionalPlan fixtures."
        ),
    )
    parser.add_argument(
        "--llm-model",
        help=(
            "Override the provider model when --planner strategy "
            "--llm-provider deepseek is selected."
        ),
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
        if args.fixture:
            if runtime_config.planner_mode != "deterministic":
                raise SolverRuntimeConfigError(
                    "planner.problem_bundle_required: --fixture is only available "
                    "with --planner deterministic"
                )
            problem = load_problem_ir(args.fixture)
            result = solve_problem_ir_debug(problem, runtime_config=runtime_config)
        else:
            if runtime_config.planner_mode != "strategy":
                raise SolverRuntimeConfigError(
                    "--accepted-context requires --planner strategy"
                )
            if not args.artifact_root:
                raise SolverRuntimeConfigError(
                    "--accepted-context requires --artifact-root"
                )
            ancestors = _load_context_chain(args.ancestor_context)
            accepted_payload = json.loads(
                Path(args.accepted_context).read_text(encoding="utf-8")
            )
            accepted = ProblemExtractionContext.from_payload(
                accepted_payload,
                ancestor_contexts=ancestors,
            )
            bundle = VerifiedSolverProblemBundleLoader().load(
                accepted,
                ExtractionArtifactStore(args.artifact_root),
                ancestor_contexts=ancestors,
            )
            result = solve_problem(bundle, runtime_config=runtime_config)
    except (SolverRuntimeConfigError, LLMClientConfigurationError, ValueError, OSError) as exc:
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


def _load_context_chain(paths: list[str]) -> tuple[ProblemExtractionContext, ...]:
    ancestors: list[ProblemExtractionContext] = []
    for raw_path in paths:
        payload = json.loads(Path(raw_path).read_text(encoding="utf-8"))
        ancestors.append(
            ProblemExtractionContext.from_payload(
                payload,
                ancestor_contexts=tuple(ancestors),
            )
        )
    return tuple(ancestors)


if __name__ == "__main__":
    raise SystemExit(main())
