"""Run isolated DeepSeek FunctionalPlan integration samples concurrently."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Sequence


SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent
DEFAULT_TEST_PATH = "tests/solver/test_deepseek_functional_planner_nankai.py"
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "internal"
    / "solver-runs"
    / "strategy-planner-deepseek-functional-nankai"
    / "batches"
)


@dataclass(frozen=True)
class BatchSample:
    sample_id: str
    debug_dir: Path


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    batch_id = args.batch_id or datetime.now().strftime("batch-%Y%m%d-%H%M%S")
    _validate_path_component(batch_id, "batch id")
    output_root = Path(args.output_root).expanduser().resolve()
    batch_dir = output_root / batch_id
    samples = tuple(
        BatchSample(f"sample-{index:02d}", batch_dir / f"sample-{index:02d}")
        for index in range(1, args.samples + 1)
    )
    config = {
        "batch_id": batch_id,
        "samples": args.samples,
        "concurrency": min(args.concurrency, args.samples),
        "max_attempts": args.max_attempts,
        "timeout_seconds": args.timeout_seconds,
        "batch_dir": str(batch_dir),
        "test_path": args.test_path,
    }
    if args.dry_run:
        print(json.dumps({**config, "sample_dirs": [str(s.debug_dir) for s in samples]}, indent=2))
        return 0
    if batch_dir.exists():
        raise SystemExit(f"batch output already exists: {batch_dir}")
    batch_dir.mkdir(parents=True)
    _write_json(batch_dir / "batch-config.json", config)
    started_at = datetime.now().astimezone().isoformat()
    print(
        f"Starting {len(samples)} samples with concurrency={config['concurrency']} "
        f"in {batch_dir}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=config["concurrency"]) as executor:
        futures = {
            executor.submit(
                _run_sample,
                sample,
                test_path=args.test_path,
                max_attempts=args.max_attempts,
                timeout_seconds=args.timeout_seconds,
            ): sample
            for sample in samples
        }
        for future in as_completed(futures):
            sample = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"[{sample.sample_id}] {result['outcome']} "
                f"attempts={result['attempt_count']} "
                f"duration={result['duration_seconds']}s",
                flush=True,
            )
    results.sort(key=lambda item: item["sample_id"])
    summary = {
        **config,
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(),
        "passed": sum(item["outcome"] == "passed" for item in results),
        "failed": sum(item["outcome"] != "passed" for item in results),
        "samples_result": results,
    }
    _write_json(batch_dir / "batch-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["failed"] == 0 else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated FunctionalPlan DeepSeek pytest samples.",
    )
    parser.add_argument("--samples", type=_positive_int, default=3)
    parser.add_argument("--concurrency", type=_positive_int, default=3)
    parser.add_argument("--max-attempts", type=_positive_int, default=3)
    parser.add_argument("--timeout-seconds", type=_positive_int, default=1800)
    parser.add_argument("--batch-id")
    parser.add_argument("--test-path", default=DEFAULT_TEST_PATH)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def _validate_path_component(value: str, label: str) -> None:
    if not value or Path(value).name != value or value in {".", ".."}:
        raise SystemExit(f"invalid {label}: {value!r}")


def _run_sample(
    sample: BatchSample,
    *,
    test_path: str,
    max_attempts: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "RUN_LLM_INTEGRATION": "1",
            "RUN_DEEPSEEK_FUNCTIONAL_PLANNER": "1",
            "DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS": str(max_attempts),
            "DEEPSEEK_FUNCTIONAL_PLANNER_DEBUG_DIR": str(sample.debug_dir),
            "DEEPSEEK_FUNCTIONAL_PLANNER_SAMPLE_ID": sample.sample_id,
            "PYTHONUNBUFFERED": "1",
        }
    )
    command = [sys.executable, "-m", "pytest", test_path, "-q", "-s"]
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            cwd=SERVER_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        return_code = 124
        stdout = _decode_timeout_output(exc.stdout)
        stderr = _decode_timeout_output(exc.stderr)
    duration = round(time.monotonic() - started, 2)
    sample.debug_dir.mkdir(parents=True, exist_ok=True)
    (sample.debug_dir / "pytest.stdout.log").write_text(stdout, encoding="utf-8")
    (sample.debug_dir / "pytest.stderr.log").write_text(stderr, encoding="utf-8")
    result_payload = _read_json(sample.debug_dir / "sample-result.json") or {}
    outcome = (
        "passed"
        if return_code == 0 and result_payload.get("status") == "ok"
        else ("timeout" if timed_out else "failed")
    )
    answers = result_payload.get("answers") or {}
    return {
        "sample_id": sample.sample_id,
        "outcome": outcome,
        "return_code": return_code,
        "attempt_count": result_payload.get(
            "attempt_count",
            len(tuple(sample.debug_dir.glob("attempt-*.raw-response.txt"))),
        ),
        "duration_seconds": duration,
        "answer_signature": _answer_signature(answers) if answers else None,
        "answers": answers,
        "first_error": _first_structured_error(sample.debug_dir),
        "llm": _llm_summary(sample.debug_dir),
        "debug_dir": str(sample.debug_dir),
        "stdout_log": str(sample.debug_dir / "pytest.stdout.log"),
        "stderr_log": str(sample.debug_dir / "pytest.stderr.log"),
    }


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _answer_signature(answers: Any) -> str:
    return json.dumps(
        answers,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _first_structured_error(debug_dir: Path) -> dict[str, Any] | None:
    for path in sorted(debug_dir.glob("attempt-*.structured-error.json")):
        payload = _read_json(path)
        if isinstance(payload, dict):
            return {
                key: payload.get(key)
                for key in ("stage", "code", "message", "retryable")
                if key in payload
            }
    return None


def _llm_summary(debug_dir: Path) -> dict[str, Any]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    models: list[str] = []
    for path in sorted(debug_dir.glob("attempt-*.llm-metadata.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        model = payload.get("response_model") or payload.get("request_model")
        if isinstance(model, str) and model not in models:
            models.append(model)
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
    return {"models": models, "usage": totals}


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
