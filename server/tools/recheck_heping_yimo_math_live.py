"""Recheck tj-2026-heping-yimo-25 math-expression/v1 three times."""

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
    report,
    save,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


CASE = "tj-2026-heping-yimo-25"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        parser.error("workers must be between 1 and 3")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = SolverRuntimeConfig.from_sources(
        llm_provider="deepseek", max_llm_attempts=3
    )
    frozen = {
        "kind": "heping-yimo-math-recheck",
        "baseline_batch": "method-math-arguments-20260917",
        "code_fingerprint": code_fingerprint(),
        "cases": {CASE: digest(candidate(CASE))},
        "model": config.llm_model or config.deepseek_model,
        "base_url": config.deepseek_base_url,
        "thinking_effort": "low",
        "request_timeout": 120,
        "sdk_max_retries": "provider_default",
        "reasoning_only_empty_response_retry": True,
        "semantic_attempt_budget": config.max_llm_attempts,
        "encodings": [MATH_EXPRESSIONS],
        "samples_per_case_and_encoding": 3,
        "authority": "frozen_input_with_synthetic_test_admission",
    }
    frozen_path = output / "frozen.json"
    if frozen_path.exists():
        if json.loads(frozen_path.read_text()) != frozen:
            raise RuntimeError("Frozen comparison configuration changed")
    else:
        save(frozen_path, frozen)

    frozen_digest = digest(frozen)
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [
            pool.submit(
                live_job, str(output), CASE, MATH_EXPRESSIONS, sample, frozen_digest
            )
            for sample in range(1, 4)
        ]
        for job in as_completed(jobs):
            row = job.result()
            records.append(row)
            report(output, records, frozen)
            print(
                row["case"],
                row["encoding"],
                row["sample"],
                row["status"],
                row["semantic_attempts"],
                flush=True,
            )
    if len(records) != 3:
        raise RuntimeError(f"expected 3 records, got {len(records)}")
    print(json.dumps(report(output, records, frozen), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
