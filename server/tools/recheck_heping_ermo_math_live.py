"""Recheck tj-2026-heping-ermo-25 math-expression/v1 x3 under current code.

Writes to a new output directory. Does not touch
internal/solver-runs/method-math-arguments-20260917 or its docs validation tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_method_math_arguments import (  # noqa: E402
    MATH_EXPRESSIONS,
    candidate,
    code_fingerprint,
    digest,
    live_job,
    report,
    save,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig  # noqa: E402

CASE = "tj-2026-heping-ermo-25"


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
        "kind": "heping-ermo-math-recheck",
        "baseline_batch": "method-math-arguments-20260917",
        "baseline_note": (
            "Subset recheck only. Does not replace or overwrite the original "
            "5x2x3 batch evidence under method-math-arguments-20260917."
        ),
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
        assert json.loads(frozen_path.read_text()) == frozen, (
            "Frozen recheck configuration changed; use a fresh output directory"
        )
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
    assert len(records) == 3
    summary = report(output, records, frozen)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
