"""Offline experiment only; no production changes and no live LLM calls."""
import argparse
from functools import cached_property
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "server/tools"))
import run_basic_inequality_stage4a as runner
from shuxueshuo_server.solver.math_kernel.proof_facts import VerifiedMathFact
from shuxueshuo_server.solver.runtime.scoped_proof_facts import FactCommit, FactSnapshot, ProofCallAuthority

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--mode", choices=("baseline", "no-debug", "metadata-cache"), required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

# Deliberate process-local experiment. A production cache also needs explicit
# deep-immutability contracts, invalidation/adversarial tests and bounded lifetime.
if args.mode == "metadata-cache":
    for cls, fields in (
        (VerifiedMathFact, ("statement_key", "fact_id")),
        (FactCommit, ("commit_id",)),
        (FactSnapshot, ("committed_manifest_hash",)),
        (ProofCallAuthority, ("fingerprint",)),
    ):
        for field in fields:
            prop = cached_property(getattr(cls, field).fget)
            prop.__set_name__(cls, field)
            setattr(cls, field, prop)

OriginalRuntime = runner.RuntimeOrchestrator
class MeasuredRuntime(OriginalRuntime):
    def __init__(self, *a, **kw):
        if args.mode != "baseline":
            kw["debug_dir"] = None
        super().__init__(*a, **kw)
runner.RuntimeOrchestrator = MeasuredRuntime
fixture = ROOT / "server/tests/solver/fixtures"
start = perf_counter()
result, runtime = runner.run(
    gold=fixture / "math-notation-v1/basic-inequality/q30.json",
    problem_ir=fixture / "basic-inequality-problem-ir/v1/q30/problem-ir.json",
    plan=fixture / "basic-inequality-stage5c/q30.json",
    output=args.output,
    mode="recorded",
    proof_protocol="scoped-facts/v2",
)
elapsed = perf_counter() - start
assert result.status == "ok", result.to_dict()
assert result.answers == {"problem": {"minimum": "4"}}
store = runtime.last_success_artifacts.context.proof_facts
payload = json.dumps(store.to_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
summary = {
    "mode": args.mode,
    "seconds": elapsed,
    "attempt_duration_ms": result.to_dict()["run_log"]["attempts"][0]["duration_ms"],
    "answers": result.answers,
    "commits": len(store.snapshot.commits),
    "requirements": sum(len(c.requirements) for c in store.snapshot.commits),
    "proof_snapshot_sha256": hashlib.sha256(payload).hexdigest(),
    "live_llm_calls": 0,
    "note": "One cold process, all mathematical checks retained. Timing excludes summary serialization below.",
}
(args.output / "measurement.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
