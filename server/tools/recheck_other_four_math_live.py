"""Run the four non-Heping-Yimo cases with math-expression arguments.

The comparison baseline is the source-ref rows from the frozen five-case live
batch.  This keeps the same model, input digest, and three semantic samples
while changing only the Method argument encoding.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from compare_method_math_arguments import (
    MATH_EXPRESSIONS,
    candidate,
    code_fingerprint,
    digest,
    live_job,
    save,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
)
BASELINE_REPORT = Path(
    "../docs/validation/method-math-arguments-20260917/live-report.json"
)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _delta(new: float | None, old: float | None) -> dict[str, float | None]:
    if new is None or old is None:
        return {"new": new, "old": old, "delta": None, "percent": None}
    return {
        "new": new,
        "old": old,
        "delta": new - old,
        "percent": ((new - old) / old * 100) if old else None,
    }


def compare(records: list[dict], baseline: dict) -> dict:
    old_rows = {
        (row["case"], row["sample"]): row
        for row in baseline["runs"]
        if row["encoding"] == "source-ref" and row["case"] in CASES
    }
    new_rows = {
        (row["case"], row["sample"]): row
        for row in records
    }
    cases = {}
    for case in CASES:
        rows = []
        for sample in range(1, 4):
            old = old_rows[(case, sample)]
            new = new_rows[(case, sample)]
            rows.append(
                {
                    "sample": sample,
                    "old_status": old["status"],
                    "new_status": new["status"],
                    "old_final_success": old["final_success"],
                    "new_final_success": new["final_success"],
                    "old_retries": old["retries"],
                    "new_retries": new["retries"],
                    "seconds": _delta(new["seconds"], old["seconds"]),
                    "prompt_tokens": _delta(
                        (new.get("observed_tokens") or {}).get("prompt_tokens"),
                        (old.get("observed_tokens") or {}).get("prompt_tokens"),
                    ),
                    "completion_tokens": _delta(
                        (new.get("observed_tokens") or {}).get("completion_tokens"),
                        (old.get("observed_tokens") or {}).get("completion_tokens"),
                    ),
                    "total_tokens": _delta(
                        (new.get("observed_tokens") or {}).get("total_tokens"),
                        (old.get("observed_tokens") or {}).get("total_tokens"),
                    ),
                }
            )
        cases[case] = {
            "samples": rows,
            "old_final_successes": sum(item["old_final_success"] for item in rows),
            "new_final_successes": sum(item["new_final_success"] for item in rows),
            "old_total_seconds": sum(item["seconds"]["old"] for item in rows),
            "new_total_seconds": sum(item["seconds"]["new"] for item in rows),
            "old_total_tokens": sum(item["total_tokens"]["old"] for item in rows),
            "new_total_tokens": sum(item["total_tokens"]["new"] for item in rows),
        }

    old_all = [old_rows[(case, sample)] for case in CASES for sample in range(1, 4)]
    new_all = [new_rows[(case, sample)] for case in CASES for sample in range(1, 4)]
    old_seconds = [row["seconds"] for row in old_all if row["seconds"] is not None]
    new_seconds = [row["seconds"] for row in new_all if row["seconds"] is not None]
    old_tokens = [row["observed_tokens"]["total_tokens"] for row in old_all if row.get("observed_tokens")]
    new_tokens = [row["observed_tokens"]["total_tokens"] for row in new_all if row.get("observed_tokens")]
    return {
        "baseline_encoding": "source-ref",
        "new_encoding": MATH_EXPRESSIONS,
        "cases": cases,
        "aggregate": {
            "runs": len(new_all),
            "old_final_successes": sum(row["final_success"] for row in old_all),
            "new_final_successes": sum(row["final_success"] for row in new_all),
            "seconds": _delta(sum(new_seconds), sum(old_seconds)),
            "mean_seconds": _delta(_mean(new_seconds), _mean(old_seconds)),
            "total_tokens": _delta(sum(new_tokens), sum(old_tokens)),
            "mean_tokens": _delta(_mean(new_tokens), _mean(old_tokens)),
            "prompt_tokens": _delta(
                sum(row["observed_tokens"]["prompt_tokens"] for row in new_all),
                sum(row["observed_tokens"]["prompt_tokens"] for row in old_all),
            ),
            "completion_tokens": _delta(
                sum(row["observed_tokens"]["completion_tokens"] for row in new_all),
                sum(row["observed_tokens"]["completion_tokens"] for row in old_all),
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--baseline", type=Path, default=BASELINE_REPORT)
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        parser.error("workers must be between 1 and 3")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(args.baseline.resolve().read_text())
    config = SolverRuntimeConfig.from_sources(
        llm_provider="deepseek", max_llm_attempts=3
    )
    frozen = {
        "kind": "other-four-math-recheck",
        "baseline_report": str(args.baseline.resolve()),
        "code_fingerprint": code_fingerprint(),
        "cases": {case: digest(candidate(case)) for case in CASES},
        "model": config.llm_model or config.deepseek_model,
        "base_url": config.deepseek_base_url,
        "thinking_effort": "low",
        "request_timeout": 120,
        "sdk_max_retries": "provider_default",
        "reasoning_only_empty_response_retry": True,
        "semantic_attempt_budget": config.max_llm_attempts,
        "encodings": [MATH_EXPRESSIONS],
        "samples_per_case_and_encoding": 3,
    }
    save(output / "frozen.json", frozen)
    frozen_digest = digest(frozen)
    records: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [
            pool.submit(live_job, str(output), case, MATH_EXPRESSIONS, sample, frozen_digest)
            for case in CASES
            for sample in range(1, 4)
        ]
        for job in as_completed(jobs):
            row = job.result()
            records.append(row)
            print(row["case"], row["sample"], row["status"], row["semantic_attempts"], flush=True)
    records.sort(key=lambda row: (row["case"], row["sample"]))
    save(output / "records.json", records)
    comparison = compare(records, baseline)
    save(output / "comparison.json", comparison)
    print(json.dumps(comparison["aggregate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
