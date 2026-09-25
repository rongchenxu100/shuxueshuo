"""Run four frozen authoring cases; preserve every attempt in a new directory."""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from tools.run_basic_inequality_stage4a import run

CASES = ("q01", "q03", "q07", "q08")


def call_accounting(output):
    records = []
    for path in sorted(output.glob("attempt-*.provider-metadata.json")):
        metadata = json.loads(path.read_text())
        records.append(
            {
                "attempt": metadata["semantic_attempt"],
                "provider_invocation_id": metadata.get("provider_invocation_id"),
                "request_model": metadata.get("request_model"),
                "response_model": metadata.get("response_model"),
                "usage": metadata.get("usage") or {},
            }
        )
    return {
        "calls": records,
        "usage": {
            key: sum((r["usage"].get(key) or 0) for r in records)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        },
        "attempt_count": len(list(output.glob("attempt-*.raw-response.txt"))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("recorded", "deepseek"), default="recorded")
    parser.add_argument("--case", choices=(*CASES, "all"), default="all")
    parser.add_argument("--samples", type=int, choices=(1, 2), default=2)
    parser.add_argument("--replay-from", type=Path)
    args = parser.parse_args()
    if args.replay_from and args.mode == "deepseek":
        parser.error("--replay-from requires recorded mode")
    args.output.mkdir(parents=True, exist_ok=False)
    fixtures = SERVER / "tests/solver/fixtures"

    def execute(job):
        case, sample = job
        output = args.output / f"{case}-{sample:02d}"
        start = time.monotonic()
        result, _ = run(
            gold=fixtures / f"math-notation-v1/basic-inequality/{case}.json",
            problem_ir=fixtures
            / f"basic-inequality-problem-ir/v1/{case}/problem-ir.json",
            output=output,
            mode=args.mode,
            plan=fixtures / f"basic-inequality-stage4/{case}.json",
            replay_from=args.replay_from / f"{case}-{sample:02d}"
            if args.replay_from
            else None,
        )
        record = {
            "case": case,
            "sample": sample,
            "status": result.status,
            "answers": result.answers,
            "elapsed_seconds": time.monotonic() - start,
            "output": str(output),
            **call_accounting(output),
        }
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return record

    cases = CASES if args.case == "all" else (args.case,)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                execute,
                [(case, n) for case in cases for n in range(1, args.samples + 1)],
            )
        )
    (args.output / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    return 0 if all(r["status"] == "ok" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
