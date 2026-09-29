"""Compare frozen real requests using the internal layered search, never live LLM.

The legacy run reconstructs exact Method-local contexts only. New searches run
independently; failures are saved and never repaired by the legacy result.
Outer witness drivers are excluded from this historical request comparison;
current Runtime, Method and witness migration are covered by E/F3 tests.
The archived search uses the current checker/accounting, so rerun costs are not
a byte-for-byte reconstruction of historical performance measurements.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from tools.proof_search_baseline import FIXTURES, ROOT, profiles, verify_assets
from tools.proof_search_legacy import HistoricalRequests, LegacySearch


def measure(output):
    from shuxueshuo_server.solver.math_kernel.inequality_evidence import verify_bound
    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
    from shuxueshuo_server.solver.math_kernel.proof_search import run_scheduled_request
    from shuxueshuo_server.solver.math_kernel.proof_types import _Budget
    from tools.run_basic_inequality_stage4a import run

    manifest = verify_assets()
    output.mkdir(parents=True, exist_ok=False)
    summary = {
        "schema_version": "layered-search-measurement/v1",
        "input_sha256": manifest["input_sha256"],
        "profiles": profiles(),
        "live_llm_calls": 0,
        "mode": "frozen-request-shadow",
        "cases": [],
    }
    any_failure = False
    for case in manifest["cases"]:
        path = output / case["id"]
        path.mkdir()
        source = json.loads((ROOT / case["input"]).read_text())[case["key"]]
        requests = []
        original = LegacySearch.__init__

        def observe(
            self, context, request, original=original, requests=requests, **kwargs
        ):
            result = original(self, context, request, **kwargs)
            requests.append((context, request, self.budget.limits))
            return result

        start = perf_counter()
        with patch.object(LegacySearch, "__init__", observe), HistoricalRequests():
            if case["kind"] == "local_bound":
                verified = verify_bound(manifest["local_target"], source)
                old_outcome = {"bound": verified["bound"]}
            else:
                plan = {
                    "format": "functional_plan/v2",
                    "root_scope": {
                        "scope_ref": "problem",
                        "steps": source.get("scope_steps", {}).get("problem", []),
                        "goals": [
                            {"goal_ref": k, **v}
                            for k, v in source["goal_plans"].items()
                        ],
                    },
                }
                plan_path = path / "plan.json"
                plan_path.write_text(json.dumps(plan, ensure_ascii=False))
                result, _ = run(
                    gold=FIXTURES / "math-notation-v1/basic-inequality/q30.json",
                    problem_ir=FIXTURES
                    / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
                    plan=plan_path,
                    output=path / "legacy",
                    mode="recorded",
                    proof_protocol="bound-conditions/v1",
                )
                old_outcome = {"status": result.status, "answers": result.answers}
        legacy_elapsed = perf_counter() - start
        rows = []
        totals = Counter()
        failures = []
        start = perf_counter()

        def forbidden(*a, **kw):
            raise AssertionError("layered search invoked legacy fallback")

        with patch.object(LegacySearch, "core", forbidden):
            for i, (context, request, limits) in enumerate(requests):
                if request["kind"] == "witness":
                    rows.append(
                        {"request": request, "status": "witness_driver_stage_e"}
                    )
                    continue
                item = run_scheduled_request(context, request, budget=_Budget(limits))
                replay = (
                    replay_proof(item.result.proof, context)
                    if item.result.status == "proved"
                    else None
                )
                if item.result.status != "proved" or replay.status != "proved":
                    failures.append(
                        {
                            "request": i,
                            "kind": request["kind"],
                            "result": item.result.to_payload(),
                        }
                    )
                totals.update(item.diagnostics["counts"])
                rows.append(
                    {
                        "context": {
                            "symbols": sorted(context.symbols),
                            "scope_id": context.scope_id,
                            "limits": asdict(context.limits),
                            "premises": {
                                k: {
                                    "source": p.source,
                                    "source_path": p.source_path,
                                    "step": p.step,
                                }
                                for k, p in context.premises.items()
                            },
                        },
                        "effective_limits": asdict(limits),
                        "request": request,
                        "result": item.result.to_payload(),
                        "replay": replay.status if replay else None,
                        "diagnostics": item.diagnostics,
                    }
                )
        with gzip.open(
            path / "requests-proofs-traces.json.gz", "wt", encoding="utf-8"
        ) as file:
            json.dump(rows, file, ensure_ascii=False)
        result = {
            "id": case["id"],
            "legacy_outcome": old_outcome,
            "legacy_seconds": legacy_elapsed,
            "requests": len(requests),
            "witness_drivers_deferred": sum(
                q["kind"] == "witness" for _, q, _ in requests
            ),
            "new_seconds": perf_counter() - start,
            "counts": dict(totals),
            "failures": failures,
        }
        summary["cases"].append(result)
        any_failure |= bool(failures)
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            case["id"], len(requests), "requests", len(failures), "failures", flush=True
        )
    if any_failure:
        raise RuntimeError("layered search regression; inspect persisted failures")
    return summary


def replay_saved(directory):
    """Replay archived local certificates with both search engines forbidden."""
    from dataclasses import replace
    from hashlib import sha256

    import sympy as sp
    from shuxueshuo_server.solver.math_kernel.expression_parser import (
        parse_math_relation,
    )
    from shuxueshuo_server.solver.math_kernel.proof_checker import replay_proof
    from shuxueshuo_server.solver.math_kernel.proof_search import SearchScheduler
    from shuxueshuo_server.solver.math_kernel.proof_types import (
        ProofContext,
        ProofLimits,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("archived replay invoked search")

    report = {"proved": 0, "deferred_witness_drivers": 0, "archives": {}}
    with (
        patch.object(LegacySearch, "need", forbidden),
        patch.object(SearchScheduler, "prove", forbidden),
    ):
        for path in sorted(directory.glob("live*.json.gz")):
            report["archives"][path.name] = sha256(path.read_bytes()).hexdigest()
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                rows = json.load(stream)
            for row in rows:
                if row.get("status") == "witness_driver_stage_e":
                    report["deferred_witness_drivers"] += 1
                    continue
                raw = row["context"]
                symbols = {name: sp.Symbol(name, real=True) for name in raw["symbols"]}
                context = ProofContext(
                    symbols,
                    {
                        key: replace(
                            parse_math_relation(value["source"], symbols),
                            source_path=value["source_path"],
                            step=value["step"],
                        )
                        for key, value in raw["premises"].items()
                    },
                    ProofLimits(**raw["limits"]),
                    raw["scope_id"],
                )
                result = replay_proof(row["result"]["proof"], context)
                if result.status != "proved":
                    raise RuntimeError(f"archived replay failed: {path.name}: {result}")
                report["proved"] += 1
    if not report["archives"]:
        raise ValueError("no archived certificates found")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--replay-saved", type=Path)
    args = parser.parse_args()
    if args.replay_saved:
        print(json.dumps(replay_saved(args.replay_saved), indent=2))
    else:
        measure(args.output)
