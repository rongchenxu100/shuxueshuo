"""q30 mixed-bound acceptance: independent Planner calls, replay and lesson."""

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


def mixed_chain_executed(execution):
    edges = verified_method_dependencies(execution)
    quadratic = {
        e["consumer_step"]
        for e in edges
        if e["producer"] == "apply_two_term_amgm"
        and e["consumer"] == "bound_univariate_quadratic"
    }
    return any(
        e["producer_step"] in quadratic and e["consumer"] == "apply_two_term_amgm"
        for e in edges
    )


def full_chain_executed(execution):
    """Require connected, verified consumption across all five calls."""
    route = (
        "organize_expressions",
        "apply_two_term_amgm",
        "bound_univariate_quadratic",
        "apply_two_term_amgm",
        "close_equality_and_restore",
    )
    edges = verified_method_dependencies(execution)
    frontier = {e["producer_step"] for e in edges if e["producer"] == route[0]}
    for producer, consumer in zip(route, route[1:]):
        frontier = {
            e["consumer_step"] for e in edges
            if e["producer_step"] in frontier
            and e["producer"] == producer and e["consumer"] == consumer
        }
    return bool(frontier)


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
    parser.add_argument("--case", choices=("q30",), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("recorded", "deepseek"), default="recorded")
    parser.add_argument("--samples", type=int, choices=(1, 2, 3), default=2)
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
        "plan": fixtures / f"basic-inequality-stage5c/{args.case}.json",
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
        record["mixed_chain_executed"] = False
        record["full_chain_executed"] = False
        if result.status == "ok":
            execution = runtime.last_success_artifacts.verified_functional_execution.to_payload()
            record["mixed_chain_executed"] = mixed_chain_executed(execution)
            record["full_chain_executed"] = full_chain_executed(execution)
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
        "mixed_chain_covered": any(r["mixed_chain_executed"] for r in results),
        "full_chain_successful_runs": sum(r["full_chain_executed"] for r in results),
    }
    summary_path = args.output / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    if args.lesson != "none":
        source = next(
            (r for r in results if r["mixed_chain_executed"] and r.get("replay_ok")),
            None,
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
        and summary["mixed_chain_covered"]
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
