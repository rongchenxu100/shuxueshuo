"""Explicit Stage 4A authoring gate; default production routing stays closed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shuxueshuo_server.solver.basic_inequality_stage4a import (
    load_frozen_authoring_bundle,
)
from shuxueshuo_server.solver.extraction.problem_planner_authority import (
    VerifiedPlannerProblemAuthority,
)
from shuxueshuo_server.solver.extraction.source_identity import thaw_json
from shuxueshuo_server.solver.family.basic_inequality_runtime import (
    STAGE4A_FAMILY_REGISTRY,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
from shuxueshuo_server.solver.runtime.scoped_functional_plan import (
    ScopedFunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    strategy_planner_provider,
)


class RecordedClient:
    def __init__(self, content):
        self.content = content

    def complete(self, payload, **kwargs):
        return self.content


def run(*, gold, problem_ir, output, mode, plan=None):
    # A new directory preserves all failed attempts and their evidence.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    bundle = load_frozen_authoring_bundle(gold, problem_ir)
    (output / "source-provenance.json").write_text(
        json.dumps(thaw_json(bundle.provenance), ensure_ascii=False, indent=2) + "\n"
    )
    if mode == "deepseek":
        config = SolverRuntimeConfig.from_sources(
            planner_mode="strategy",
            llm_provider="deepseek",
            argument_encoding="source-ref",
        )
        client = config.build_llm_client(thinking_effort="low")
    else:
        authority = VerifiedPlannerProblemAuthority.from_bundle(bundle)
        parsed, report = ScopedFunctionalPlanValidator().validate_payload_with_report(
            json.loads(Path(plan).read_text())
        )
        if not report.ok:
            raise ValueError(report.to_payload())
        content = functional_plan_content_from_plan(
            parsed,
            frame=FunctionalPlanAuthorityFrame.from_planning_context(
                authority.planning_context
            ),
        )
        client = RecordedClient(json.dumps(content.to_payload(), ensure_ascii=False))
    runtime = RuntimeOrchestrator(
        family_registry=STAGE4A_FAMILY_REGISTRY,
        default_planner_provider=strategy_planner_provider(
            mode="deepseek",
            client=client,
            argument_encoding="source-ref",
            functional_few_shot_mode="strict_test",
        ),
        max_attempts=3,
        debug_dir=output,
    )
    result = runtime.solve_verified(bundle)
    (output / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str) + "\n"
    )
    return result, runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("recorded", "deepseek"), default="recorded")
    parser.add_argument(
        "--gold",
        type=Path,
        default=SERVER
        / "tests/solver/fixtures/math-notation-v1/basic-inequality/q01.json",
    )
    parser.add_argument(
        "--problem-ir",
        type=Path,
        default=SERVER
        / "tests/solver/fixtures/basic-inequality-problem-ir/v1/q01/problem-ir.json",
    )
    parser.add_argument(
        "--plan",
        type=Path,
        default=SERVER.parent
        / "internal/functional-plan-fixtures/basic-inequality-q01.functional-plan.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result, _ = run(
        gold=args.gold,
        problem_ir=args.problem_ir,
        output=args.output,
        mode=args.mode,
        plan=args.plan,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "answers": result.answers,
                "artifacts": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
