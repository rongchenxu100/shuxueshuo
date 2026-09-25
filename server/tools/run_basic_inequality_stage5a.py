"""Source-transcribed q29 M08 acceptance: independent Planner runs, replay and lesson."""

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


def m08_executed(execution):
    if isinstance(execution, dict):
        if (execution.get("status") == "runtime_verified"
            and execution.get("authored_step", {}).get("capability_id") == "eliminate_by_constraint"
            and any(e.get("schema_version") == "elimination-teaching-evidence/v1" for e in execution.get("evidence", []))):
            return True
        return any(m08_executed(value) for value in execution.values())
    if isinstance(execution, list):
        return any(m08_executed(value) for value in execution)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
        "gold": fixtures / "basic-inequality-stage5a/q29/notation.json",
        "problem_ir": fixtures / "basic-inequality-stage5a/q29/problem-ir.json",
        "input_mode": "transcribed",
        "plan": fixtures / "basic-inequality-stage5a/q29/plan.json",
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
        record["m08_executed"] = False
        if result.status == "ok":
            execution = runtime.last_success_artifacts.verified_functional_execution.to_payload()
            record["m08_executed"] = m08_executed(execution)
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
        "m08_covered": any(r["m08_executed"] for r in results),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if args.lesson != "none":
        source = next(
            (r for r in results if r["m08_executed"] and r.get("replay_ok")), None
        )
        if source:
            build(
                output=args.output / "lesson",
                mode=args.lesson,
                case="q29",
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
        and summary["m08_covered"]
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
