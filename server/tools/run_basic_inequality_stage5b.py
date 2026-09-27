"""Frozen q25/q12 M07 acceptance: independent Planner runs, replay and lesson."""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SERVER / "tools"))
from run_basic_inequality_stage4 import call_accounting
from run_basic_inequality_stage4a import run
from run_basic_inequality_stage4b import build


def m07_executed(execution):
    if isinstance(execution, dict):
        if (
            execution.get("status") == "runtime_verified"
            and execution.get("authored_step", {}).get("capability_id")
            == "substitute_expressions"
            and any(
                e.get("schema_version") == "substitution-teaching-evidence/v1"
                for e in execution.get("evidence", [])
            )
        ):
            return True
        return any(m07_executed(value) for value in execution.values())
    if isinstance(execution, list):
        return any(m07_executed(value) for value in execution)
    return False


def verified_method_dependencies(execution):
    """Report actual verified producer/consumer edges, independent of step names."""
    methods = {}

    def visit(value):
        if isinstance(value, dict):
            if value.get("status") == "runtime_verified" and value.get("authored_step"):
                step = value["authored_step"]
                methods[step["step_id"]] = step["capability_id"]
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(execution.get("root_scope", {}))
    return [
        {
            "producer": methods[p],
            "consumer": methods[c],
            "producer_step": p,
            "consumer_step": c,
        }
        for c, producers in execution.get("dependency_graph", {}).items()
        for p in producers
        if p in methods and c in methods
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("q25", "q12"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("recorded", "deepseek"), default="recorded")
    parser.add_argument("--samples", type=int, choices=(1, 2), default=2)
    parser.add_argument(
        "--lesson", choices=("none", "deterministic", "deepseek"), default="none"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    fixtures = SERVER / "tests/solver/fixtures"
    common = {
        "gold": fixtures / f"math-notation-v1/basic-inequality/{args.case}.json",
        "problem_ir": fixtures
        / f"basic-inequality-problem-ir/v1/{args.case}/problem-ir.json",
        "plan": fixtures / f"basic-inequality-stage5b/{args.case}.json",
    }
    started = time.monotonic()

    def execute(sample):
        output = args.output / f"planner-{sample:02d}"
        call_start = time.monotonic()
        result, runtime = run(**common, output=output, mode=args.mode)
        record = dict(
            sample=sample,
            status=result.status,
            answers=result.answers,
            elapsed_seconds=time.monotonic() - call_start,
            output=str(output),
            **call_accounting(output),
        )
        record["m07_executed"] = False
        if result.status == "ok":
            execution = runtime.last_success_artifacts.verified_functional_execution.to_payload()
            record["m07_executed"] = m07_executed(execution)
            record["verified_method_dependencies"] = verified_method_dependencies(
                execution
            )
            replay, _ = run(
                **common,
                output=args.output / f"replay-{sample:02d}",
                mode="recorded",
                replay_from=output,
            )
            record["replay_ok"] = (
                replay.status == "ok" and replay.answers == result.answers
            )
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return record

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(1, args.samples + 1)))
    summary = {
        "runs": results,
        "wall_seconds": time.monotonic() - started,
        "call_seconds": sum(r["elapsed_seconds"] for r in results),
        "usage": {
            k: sum(r["usage"][k] for r in results)
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "first_attempt_success": sum(
            r["status"] == "ok" and r["attempt_count"] == 1 for r in results
        ),
        "successful_runs": sum(r["status"] == "ok" for r in results),
        "m07_covered": any(r["m07_executed"] for r in results),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if args.lesson != "none":
        source = next(
            (r for r in results if r["m07_executed"] and r.get("replay_ok")), None
        )
        if source:
            build(
                output=args.output / "lesson",
                mode=args.lesson,
                case=args.case,
                plan=common["plan"],
                replay_from=source["output"],
            )
            summary["lesson"] = json.loads(
                (args.output / "lesson/summary.json").read_text()
            )
            summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
            )
    return (
        0
        if summary["successful_runs"] == args.samples
        and summary["m07_covered"]
        and all(r.get("replay_ok") for r in results)
        and (
            args.lesson == "none"
            or (
                summary.get("lesson")
                and not summary["lesson"]["lesson"].get("fallback_used", True)
            )
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
