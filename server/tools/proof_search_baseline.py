"""Offline phase-A measurements. Instrumentation observes real proof execution."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
ROOT = SERVER.parent
sys.path.insert(0, str(SERVER))
FIXTURES = SERVER / "tests/solver/fixtures"
ASSETS = FIXTURES / "scoped-proof-search"


def profiles():
    from shuxueshuo_server.solver.math_kernel.constraint_elimination import (
        elimination_context,
    )
    from shuxueshuo_server.solver.math_kernel.proof_kernel import (
        ProofContext,
        ProofLimits,
    )
    from shuxueshuo_server.solver.math_kernel.substitution import substitution_context

    base = ProofContext({})
    return {
        "default": asdict(ProofLimits()),
        "elimination": asdict(elimination_context(base).limits),
        "substitution": asdict(substitution_context(base).limits),
        "elimination_after_substitution": asdict(
            elimination_context(substitution_context(base)).limits
        ),
        "substitution_after_elimination": asdict(
            substitution_context(elimination_context(base)).limits
        ),
    }


class ObserveProofs:
    """Count all charged budgets, including auxiliary checks and replay.

    This aggregate is NOT the main search's reduction count. Keep distinct
    budget objects alive so Python cannot recycle their identities.
    """

    def __enter__(self):
        from shuxueshuo_server.solver.math_kernel import proof_kernel as pk

        self.budgets = {}
        self.goals = Counter()
        self.trace = []
        self.hits = Counter()
        old_use, old_need = pk._Budget.use, pk._Search.need

        def use(budget, field, amount=1):
            self.budgets[id(budget)] = budget
            return old_use(budget, field, amount)

        def need(search, goal):
            self.goals[goal] += 1
            if goal in search.cache:
                self.hits["local"] += 1
            if (
                pk.RULESET_HASH,
                search.context_hash,
                goal,
            ) in search.budget.proven_goals:
                self.hits["shared_same_context"] += 1
            if len(self.trace) < 200:
                self.trace.append(
                    {"goal": pk._text(goal), "context_hash": search.context_hash}
                )
            return old_need(search, goal)

        self.patches = [
            patch.object(pk._Budget, "use", use),
            patch.object(pk._Search, "need", need),
        ]
        for p in self.patches:
            p.start()
        self.started = perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed = perf_counter() - self.started
        for p in reversed(self.patches):
            p.stop()

    def report(self):
        totals = Counter()
        budgets = []
        for budget in self.budgets.values():
            totals.update(budget.counts)
            budgets.append(
                {"limits": asdict(budget.limits), "counts": dict(budget.counts)}
            )
        return {
            "elapsed_seconds": self.elapsed,
            "all_budget_charges": dict(totals),
            "budget_instances": budgets,
            "goal_requests": sum(self.goals.values()),
            "distinct_goal_structures": len(self.goals),
            "cache_hits": dict(self.hits),
            "first_200_goal_requests": self.trace,
            "trace_truncated": sum(self.goals.values()) > len(self.trace),
        }


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def verify_assets():
    manifest = json.loads((ASSETS / "manifest.json").read_text())
    for name, expected in manifest["input_sha256"].items():
        if file_hash(ROOT / name) != expected:
            raise ValueError(f"frozen input changed: {name}")
    return manifest


def run_baseline(output):
    from shuxueshuo_server.solver.math_kernel.bound_chain import replay_bound
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import (
        public_bound,
        verify_bound,
    )
    from tools.run_basic_inequality_stage4a import run
    from tools.run_basic_inequality_stage5c import full_chain_executed

    manifest = verify_assets()
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        "schema_version": "proof-search-baseline/v1",
        "code_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "profiles": profiles(),
        "cases": [],
        "live_llm_calls": 0,
        "input_sha256": manifest["input_sha256"],
        "instrumentation_sha256": file_hash(Path(__file__)),
        "python_version": sys.version,
        "measurement_note": "All budget instances include search, auxiliary checks and replay; not a single global search budget.",
    }
    for case in manifest["cases"]:
        source = json.loads((ROOT / case["input"]).read_text())
        payload = source[case["key"]]
        path = output / case["id"]
        path.mkdir()
        error = None
        observation = ObserveProofs()
        try:
            with observation:
                if case["kind"] == "recorded_plan":
                    plan = {
                        "format": "functional_plan/v2",
                        "root_scope": {
                            "scope_ref": "problem",
                            "steps": payload.get("scope_steps", {}).get("problem", []),
                            "goals": [
                                {"goal_ref": k, **v}
                                for k, v in payload["goal_plans"].items()
                            ],
                        },
                    }
                    plan_path = path / "plan.json"
                    plan_path.write_text(json.dumps(plan, ensure_ascii=False))
                    result, runtime = run(
                        gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
                        problem_ir=FIXTURES
                        / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
                        plan=plan_path,
                        output=path / "execution",
                        mode="recorded",
                    )
                    outcome = {"status": result.status, "answers": result.answers}
                    if result.status == "ok":
                        execution = runtime.last_success_artifacts.verified_functional_execution.to_payload()
                        outcome["full_five_method_chain"] = full_chain_executed(
                            execution
                        )
                else:
                    target = manifest["local_target"]
                    verified = verify_bound(target, payload)
                    (path / "bound.json").write_text(
                        json.dumps(public_bound(verified), ensure_ascii=False, indent=2)
                        + "\n"
                    )
                    replayed = replay_bound(target, public_bound(verified))
                    outcome = {
                        "status": "ok",
                        "bound": verified["bound"],
                        "replay_same_bound": replayed["bound"] == verified["bound"],
                    }
        except Exception as exc:  # noqa: BLE001 - persist diagnostics, then re-raise below
            error = exc
            outcome = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "code": getattr(exc, "code", None),
                "message": str(exc),
            }
        item = {
            "id": case["id"],
            "historical_failure": case["historical_failure"],
            "outcome": outcome,
            "measurement": observation.report(),
        }
        (path / "measurement.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2) + "\n"
        )
        summary["cases"].append(
            {k: v for k, v in item.items() if k != "measurement"}
            | {
                "elapsed_seconds": observation.elapsed,
                "all_budget_charges": item["measurement"]["all_budget_charges"],
            }
        )
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        )
        if error is not None:
            raise RuntimeError(f"baseline regression: {case['id']}") from error
        if (
            outcome["status"] != "ok"
            or (
                case["kind"] == "recorded_plan"
                and outcome["answers"] != {"problem": {"minimum": "4"}}
            )
            or (case["kind"] == "local_bound" and not outcome["replay_same_bound"])
        ):
            raise RuntimeError(f"baseline regression: {case['id']}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run_baseline(args.output), ensure_ascii=False, indent=2))
