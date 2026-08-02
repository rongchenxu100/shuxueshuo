"""Run isolated DeepSeek FunctionalPlan integration samples concurrently."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable, Sequence

from shuxueshuo_server.solver.runtime.planner_failure_classification import (
    is_planner_configuration_failure_code,
)


SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent
DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT
    / "internal"
    / "solver-runs"
    / "strategy-planner-deepseek-functional-parity"
    / "batches"
)


@dataclass(frozen=True)
class FunctionalBatchCase:
    case_id: str
    problem_id: str
    test_slug: str

    @property
    def test_path(self) -> str:
        slug = self.test_slug.replace("-", "_")
        return f"tests/solver/test_deepseek_functional_planner_{slug}.py"

    @property
    def problem_fixture_path(self) -> Path:
        return REPO_ROOT / "internal" / "solver-fixtures" / f"{self.problem_id}.json"

    @property
    def expected_path(self) -> Path:
        return (
            SERVER_ROOT
            / "tests"
            / "solver"
            / "expected"
            / f"{self.problem_id}.expected.json"
        )

    @property
    def functional_fixture_path(self) -> Path:
        return (
            REPO_ROOT
            / "internal"
            / "functional-plan-fixtures"
            / f"{self.problem_id}.functional-plan.json"
        )

    @property
    def recorded_step_intent_path(self) -> Path:
        return (
            REPO_ROOT
            / "internal"
            / "solver-fixtures"
            / f"{self.problem_id}.executable-step-intents.json"
        )

    @property
    def default_debug_dir(self) -> Path:
        return (
            REPO_ROOT
            / "internal"
            / "solver-runs"
            / f"strategy-planner-deepseek-functional-{self.test_slug}"
        )


FUNCTIONAL_BATCH_CASES: dict[str, FunctionalBatchCase] = {
    item.case_id: item
    for item in (
        FunctionalBatchCase("nankai", "tj-2026-nankai-yimo-25", "nankai"),
        FunctionalBatchCase(
            "heping-ermo",
            "tj-2026-heping-ermo-25",
            "heping-ermo",
        ),
        FunctionalBatchCase("xiqing", "tj-2026-xiqing-yimo-25", "xiqing"),
        FunctionalBatchCase("hexi", "tj-2026-hexi-yimo-25", "hexi"),
        FunctionalBatchCase("heping", "tj-2026-heping-yimo-25", "heping"),
    )
}
DEFAULT_TEST_PATH = FUNCTIONAL_BATCH_CASES["nankai"].test_path
KNOWN_FAILURE_LAYERS = {
    "replay",
    "functional_validation",
    "functional_elaboration",
    "functional_reconciliation",
    "semantic_reads",
    "handle_resolution",
    "validation",
    "normalization",
    "candidate_resolution",
    "trial_execution",
    "goal_verification",
    "answer_check",
    "context",
    "planner",
    "declaration_validation",
    "execution",
    "result_builder",
    "answer_assertion",
    "test_harness",
    "provider",
}
UNCLASSIFIED_FAILURE_CODES = {
    "planner_failed",
    "unclassified_planner_failure",
    "unclassified_test_failure",
}


@dataclass(frozen=True)
class BatchSample:
    case: FunctionalBatchCase
    sample_id: str
    debug_dir: Path
    test_path: str


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.aggregate_batches:
        return _aggregate_main(args)
    if args.case == "all" and args.test_path is not None:
        raise SystemExit("--test-path can only be used with a single --case")
    batch_id = args.batch_id or datetime.now().strftime("batch-%Y%m%d-%H%M%S")
    _validate_path_component(batch_id, "batch id")
    output_root = Path(args.output_root).expanduser().resolve()
    batch_dir = output_root / batch_id
    selected_cases = _selected_cases(args.case)
    samples_per_case = args.samples or args.samples_per_case
    samples = _batch_samples(
        selected_cases,
        samples_per_case=samples_per_case,
        batch_dir=batch_dir,
        test_path_override=args.test_path,
    )
    source_fingerprint = _source_fingerprint()
    config = {
        "batch_id": batch_id,
        "case": args.case,
        "cases": [item.case_id for item in selected_cases],
        "samples": len(samples),
        "samples_per_case": samples_per_case,
        "concurrency": min(args.concurrency, len(samples)),
        "max_attempts": args.max_attempts,
        "functional_transaction_mode": args.functional_transaction_mode,
        "functional_symbolic_closure_mode": (
            args.functional_symbolic_closure_mode
        ),
        "timeout_seconds": args.timeout_seconds,
        "batch_dir": str(batch_dir),
        "test_path": args.test_path or (
            selected_cases[0].test_path if len(selected_cases) == 1 else None
        ),
        "source_fingerprint": source_fingerprint,
    }
    if args.dry_run:
        print(
            json.dumps(
                {
                    **config,
                    "sample_dirs": [str(item.debug_dir) for item in samples],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if batch_dir.exists():
        raise SystemExit(f"batch output already exists: {batch_dir}")
    batch_dir.mkdir(parents=True)
    _write_json(batch_dir / "batch-config.json", config)
    started_at = datetime.now().astimezone().isoformat()
    print(
        f"Starting {len(samples)} samples across {len(selected_cases)} case(s) "
        f"with concurrency={config['concurrency']} in {batch_dir}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=config["concurrency"]) as executor:
        futures = {
            executor.submit(
                _run_sample,
                sample,
                max_attempts=args.max_attempts,
                timeout_seconds=args.timeout_seconds,
                source_fingerprint=source_fingerprint,
                functional_transaction_mode=(
                    args.functional_transaction_mode
                ),
                functional_symbolic_closure_mode=(
                    args.functional_symbolic_closure_mode
                ),
            ): sample
            for sample in samples
        }
        for future in as_completed(futures):
            sample = futures[future]
            result = future.result()
            results.append(result)
            print(
                f"[{sample.case.case_id}/{sample.sample_id}] {result['outcome']} "
                f"attempts={result['attempt_count']} "
                f"duration={result['duration_seconds']}s",
                flush=True,
            )
    results.sort(key=lambda item: (item["case_id"], item["sample_id"]))
    per_case = {
        case.case_id: _case_metrics(
            [item for item in results if item["case_id"] == case.case_id],
            max_attempts=args.max_attempts,
        )
        for case in selected_cases
    }
    summary = {
        **config,
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(),
        "passed": sum(item["outcome"] == "passed" for item in results),
        "failed": sum(item["outcome"] != "passed" for item in results),
        "symbolic_closure_execution_count": sum(
            item.get("symbolic_closure_execution_count", 0)
            for item in results
        ),
        "symbolic_closure_drift_count": sum(
            item.get("symbolic_closure_drift_count", 0)
            for item in results
        ),
        "symbolic_closure_execution_by_capability": _sum_counter_payloads(
            item.get("symbolic_closure_execution_by_capability", {})
            for item in results
        ),
        "symbolic_closure_drift_by_capability": _sum_counter_payloads(
            item.get("symbolic_closure_drift_by_capability", {})
            for item in results
        ),
        "per_case": per_case,
        "stage1_gate_passed": all(
            item["stage1_gate_passed"] for item in per_case.values()
        ),
        "stage2_gate_passed": all(
            item["stage2_gate_passed"] for item in per_case.values()
        ),
        "samples_result": results,
    }
    if samples_per_case >= 10:
        summary["active_gate"] = "stage2"
        summary["active_gate_passed"] = summary["stage2_gate_passed"]
    elif samples_per_case >= 3:
        summary["active_gate"] = "stage1"
        summary["active_gate_passed"] = summary["stage1_gate_passed"]
    else:
        summary["active_gate"] = "smoke"
        summary["active_gate_passed"] = all(
            item["failed"] == 0
            and item["configuration_error_count"] == 0
            and item["compatible"]
            for item in per_case.values()
        )
    _apply_symbolic_closure_activity_gate(summary)
    _write_json(batch_dir / "batch-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["active_gate_passed"] else 1


def _apply_symbolic_closure_activity_gate(
    summary: dict[str, Any],
) -> None:
    required = (
        summary.get("functional_symbolic_closure_mode") == "authoritative"
    )
    passed = (
        not required
        or int(summary.get("symbolic_closure_execution_count", 0) or 0) > 0
    )
    summary["symbolic_closure_activity_gate_required"] = required
    summary["symbolic_closure_activity_gate_passed"] = passed
    summary["active_gate_passed"] = bool(
        summary.get("active_gate_passed")
    ) and passed


def _aggregate_main(args: argparse.Namespace) -> int:
    batch_dirs = tuple(
        Path(item).expanduser().resolve()
        for item in args.aggregate_batches
    )
    report_id = args.report_id or datetime.now().strftime(
        "parity-%Y%m%d-%H%M%S"
    )
    _validate_path_component(report_id, "report id")
    output_root = Path(args.output_root).expanduser().resolve()
    report_dir = output_root / report_id
    if report_dir.exists():
        raise SystemExit(f"parity report output already exists: {report_dir}")
    try:
        summary = aggregate_batch_summaries(batch_dirs)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["stage2_gate_passed"] else 1
    report_dir.mkdir(parents=True)
    summary["report_id"] = report_id
    summary["report_dir"] = str(report_dir)
    _write_json(report_dir / "parity-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if summary["stage2_gate_passed"] else 1


def aggregate_batch_summaries(
    batch_dirs: Sequence[Path],
) -> dict[str, Any]:
    """Aggregate compatible sample records without mixing execution cohorts."""
    if not batch_dirs:
        raise ValueError("at least one batch directory is required")
    accepted_source: dict[str, Any] | None = None
    selected_keys: dict[str, str] = {}
    accepted_results: list[dict[str, Any]] = []
    rejected_cohorts: list[dict[str, Any]] = []
    sample_keys: set[str] = set()
    source_batches: list[str] = []
    for batch_dir in batch_dirs:
        summary_path = batch_dir / "batch-summary.json"
        summary = _read_json(summary_path)
        if not isinstance(summary, dict):
            raise ValueError(f"invalid batch summary: {summary_path}")
        if int(summary.get("max_attempts", 0) or 0) != 3:
            raise ValueError(
                f"batch must use max_attempts=3: {summary_path}"
            )
        batch_id = str(summary.get("batch_id") or batch_dir.name)
        source_batches.append(batch_id)
        source = summary.get("source_fingerprint")
        if not isinstance(source, dict):
            rejected_cohorts.append(
                {
                    "batch_id": batch_id,
                    "reason": "missing_source_fingerprint",
                }
            )
            continue
        if accepted_source is None:
            accepted_source = dict(source)
        elif source != accepted_source:
            rejected_cohorts.append(
                {
                    "batch_id": batch_id,
                    "reason": "source_fingerprint_mismatch",
                    "source_fingerprint": source,
                }
            )
            continue
        results = summary.get("samples_result")
        if not isinstance(results, list):
            raise ValueError(f"batch has no sample records: {summary_path}")
        for raw_result in results:
            if not isinstance(raw_result, dict):
                continue
            result = dict(raw_result)
            case_id = str(result.get("case_id") or "")
            sample_id = str(result.get("sample_id") or "")
            sample_key = f"{batch_id}/{case_id}/{sample_id}"
            if sample_key in sample_keys:
                raise ValueError(f"duplicate parity sample: {sample_key}")
            sample_keys.add(sample_key)
            compatibility_key = result.get("fingerprints", {}).get(
                "compatibility_key"
            )
            if not isinstance(compatibility_key, str) or not compatibility_key:
                rejected_cohorts.append(
                    {
                        "sample_key": sample_key,
                        "case_id": case_id,
                        "reason": "missing_compatibility_key",
                    }
                )
                continue
            selected = selected_keys.setdefault(case_id, compatibility_key)
            if compatibility_key != selected:
                rejected_cohorts.append(
                    {
                        "sample_key": sample_key,
                        "case_id": case_id,
                        "reason": "compatibility_key_mismatch",
                        "compatibility_key": compatibility_key,
                        "selected_compatibility_key": selected,
                    }
                )
                continue
            result["source_batch_id"] = batch_id
            result["sample_key"] = sample_key
            accepted_results.append(result)
    per_case = {
        case_id: _case_metrics(
            [
                item
                for item in accepted_results
                if item.get("case_id") == case_id
            ],
            max_attempts=3,
        )
        for case_id in FUNCTIONAL_BATCH_CASES
    }
    stage2_gate_passed = (
        not rejected_cohorts
        and all(item["stage2_gate_passed"] for item in per_case.values())
    )
    return {
        "schema_version": "functional_parity/v1",
        "source_batches": source_batches,
        "source_fingerprint": accepted_source,
        "accepted_samples": len(accepted_results),
        "rejected_cohorts": rejected_cohorts,
        "selected_compatibility_keys": selected_keys,
        "per_case": per_case,
        "stage2_gate_passed": stage2_gate_passed,
        "samples_result": accepted_results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run isolated FunctionalPlan DeepSeek pytest samples.",
    )
    parser.add_argument(
        "--case",
        choices=(*FUNCTIONAL_BATCH_CASES, "all"),
        default="nankai",
    )
    parser.add_argument("--samples-per-case", type=_positive_int, default=3)
    parser.add_argument(
        "--samples",
        type=_positive_int,
        help="legacy single-case alias for --samples-per-case",
    )
    parser.add_argument("--concurrency", type=_positive_int, default=3)
    parser.add_argument("--max-attempts", type=_positive_int, default=3)
    parser.add_argument(
        "--functional-transaction-mode",
        choices=(
            "legacy",
            "shadow",
            "execution_shadow",
            "context_shadow",
            "context_authoritative",
        ),
        default="legacy",
    )
    parser.add_argument(
        "--functional-symbolic-closure-mode",
        choices=("disabled", "shadow", "authoritative"),
        default="disabled",
    )
    parser.add_argument("--timeout-seconds", type=_positive_int, default=1800)
    parser.add_argument("--batch-id")
    parser.add_argument("--test-path")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument(
        "--aggregate-batches",
        nargs="+",
        help="aggregate existing batch directories without running network tests",
    )
    parser.add_argument("--report-id")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _selected_cases(case_id: str) -> tuple[FunctionalBatchCase, ...]:
    if case_id == "all":
        return tuple(FUNCTIONAL_BATCH_CASES.values())
    return (FUNCTIONAL_BATCH_CASES[case_id],)


def _batch_samples(
    cases: Sequence[FunctionalBatchCase],
    *,
    samples_per_case: int,
    batch_dir: Path,
    test_path_override: str | None,
) -> tuple[BatchSample, ...]:
    return tuple(
        BatchSample(
            case=case,
            sample_id=f"sample-{index:02d}",
            debug_dir=batch_dir / case.case_id / f"sample-{index:02d}",
            test_path=test_path_override or case.test_path,
        )
        for case in cases
        for index in range(1, samples_per_case + 1)
    )


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
    max_attempts: int,
    timeout_seconds: int,
    source_fingerprint: dict[str, Any],
    functional_transaction_mode: str,
    functional_symbolic_closure_mode: str,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "RUN_LLM_INTEGRATION": "1",
            "RUN_DEEPSEEK_FUNCTIONAL_PLANNER": "1",
            "DEEPSEEK_STRATEGY_PLANNER_MAX_ATTEMPTS": str(max_attempts),
            "DEEPSEEK_FUNCTIONAL_PLANNER_DEBUG_DIR": str(sample.debug_dir),
            "DEEPSEEK_FUNCTIONAL_PLANNER_SAMPLE_ID": sample.sample_id,
            "FUNCTIONAL_TRANSACTION_MODE": functional_transaction_mode,
            "FUNCTIONAL_SYMBOLIC_CLOSURE_MODE": (
                functional_symbolic_closure_mode
            ),
            "PYTHONUNBUFFERED": "1",
        }
    )
    command = [sys.executable, "-m", "pytest", sample.test_path, "-q", "-s"]
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
    errors = _structured_errors(sample.debug_dir)
    if result_payload.get("expected_match") is False:
        errors.append(
            {
                "stage": "answer_assertion",
                "code": "expected_mismatch",
                "message": result_payload.get("expected_mismatch"),
                "retryable": False,
            }
        )
    for failure in result_payload.get("gate_failures", ()):
        if isinstance(failure, dict):
            errors.append(dict(failure))
    if return_code != 0 and not errors:
        errors.append(
            {
                "stage": "test_harness",
                "code": "unclassified_test_failure",
                "message": "pytest failed without a structured planner or gate error",
                "retryable": False,
            }
        )
    llm = _llm_summary(sample.debug_dir)
    fingerprints = _sample_fingerprints(
        sample,
        source_fingerprint=source_fingerprint,
        models=llm["models"],
        functional_transaction_mode=functional_transaction_mode,
        functional_symbolic_closure_mode=(
            functional_symbolic_closure_mode
        ),
    )
    return {
        "case_id": sample.case.case_id,
        "problem_id": sample.case.problem_id,
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
        "expected_match": result_payload.get("expected_match"),
        "expected_mismatch": result_payload.get("expected_mismatch"),
        "sample_gates_passed": result_payload.get("gates_passed"),
        "sample_gate_checks": result_payload.get("gate_checks"),
        "symbolic_closure_execution_count": int(
            result_payload.get("symbolic_closure_execution_count", 0) or 0
        ),
        "symbolic_closure_drift_count": int(
            result_payload.get("symbolic_closure_drift_count", 0) or 0
        ),
        "symbolic_closure_execution_by_capability": dict(
            result_payload.get(
                "symbolic_closure_execution_by_capability", {}
            )
            or {}
        ),
        "symbolic_closure_drift_by_capability": dict(
            result_payload.get("symbolic_closure_drift_by_capability", {})
            or {}
        ),
        "first_error": errors[0] if errors else None,
        "structured_errors": errors,
        "llm": llm,
        "fingerprints": fingerprints,
        "debug_dir": str(sample.debug_dir),
        "stdout_log": str(sample.debug_dir / "pytest.stdout.log"),
        "stderr_log": str(sample.debug_dir / "pytest.stderr.log"),
    }


def _sum_counter_payloads(
    payloads: Iterable[object],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            counts[str(key)] = counts.get(str(key), 0) + int(value or 0)
    return dict(sorted(counts.items()))


def _case_metrics(
    results: Sequence[dict[str, Any]],
    *,
    max_attempts: int,
) -> dict[str, Any]:
    total = len(results)
    passed = sum(item["outcome"] == "passed" for item in results)
    pass_at_1_count = sum(
        item["outcome"] == "passed" and item.get("attempt_count") == 1
        for item in results
    )
    successful_gate_failures = sum(
        item["outcome"] == "passed"
        and item.get("sample_gates_passed") is not True
        for item in results
    )
    primary_counts: Counter[str] = Counter()
    root_counts: Counter[str] = Counter()
    layer_counts: Counter[str] = Counter()
    code_counts: Counter[str] = Counter()
    configuration_errors = 0
    unclassified_errors = 0
    for result in results:
        for error in result.get("structured_errors", ()):
            primary_stage, primary_code = _failure_key(error)
            primary_counts[f"{primary_stage}/{primary_code}"] += 1
            roots = _root_issues(error)
            for root in roots:
                stage, code = _failure_key(root)
                root_counts[f"{stage}/{code}"] += 1
                layer_counts[stage] += 1
                code_counts[code] += 1
                if is_planner_configuration_failure_code(code):
                    configuration_errors += 1
                if _is_unclassified_failure(stage, code):
                    unclassified_errors += 1
    signatures = Counter(
        item["answer_signature"]
        for item in results
        if item.get("answer_signature") is not None
    )
    attempts = Counter(str(item.get("attempt_count", 0)) for item in results)
    models = sorted(
        {
            model
            for item in results
            for model in item.get("llm", {}).get("models", ())
        }
    )
    tokens = {
        key: sum(
            int(item.get("llm", {}).get("usage", {}).get(key, 0) or 0)
            for item in results
        )
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    compatibility_keys = sorted(
        {
            str(item.get("fingerprints", {}).get("compatibility_key"))
            for item in results
            if item.get("fingerprints", {}).get("compatibility_key")
        }
    )
    compatible = len(compatibility_keys) <= 1
    pass_rate = passed / total if total else 0.0
    pass_at_1 = pass_at_1_count / total if total else 0.0
    average_duration = (
        round(sum(float(item["duration_seconds"]) for item in results) / total, 2)
        if total
        else 0.0
    )
    average_attempts = (
        round(sum(int(item.get("attempt_count", 0)) for item in results) / total, 2)
        if total
        else 0.0
    )
    average_tokens = {
        key: round(value / total, 2) if total else 0.0
        for key, value in tokens.items()
    }
    metrics = {
        "samples": total,
        "passed": passed,
        "failed": total - passed,
        "pass_at_1": pass_at_1,
        "pass_at_max_attempts": pass_rate,
        "max_attempts": max_attempts,
        "attempt_distribution": dict(sorted(attempts.items())),
        "error_frequency": dict(sorted(root_counts.items())),
        "primary_error_frequency": dict(sorted(primary_counts.items())),
        "root_issue_frequency": dict(sorted(root_counts.items())),
        "failure_frequency_by_layer": dict(sorted(layer_counts.items())),
        "failure_frequency_by_code": dict(sorted(code_counts.items())),
        "configuration_error_count": configuration_errors,
        "unclassified_error_count": unclassified_errors,
        "successful_sample_gate_failure_count": successful_gate_failures,
        "answer_signatures": dict(sorted(signatures.items())),
        "average_duration_seconds": average_duration,
        "average_attempts": average_attempts,
        "tokens": tokens,
        "average_tokens": average_tokens,
        "models": models,
        "compatibility_keys": compatibility_keys,
        "compatible": compatible,
    }
    if max_attempts == 3:
        metrics["pass_at_3"] = pass_rate
    metrics["stage1_gate_passed"] = (
        total >= 3
        and pass_rate == 1.0
        and configuration_errors == 0
        and unclassified_errors == 0
        and successful_gate_failures == 0
        and compatible
    )
    metrics["stage2_gate_passed"] = (
        total >= 10
        and pass_rate >= 0.9
        and configuration_errors == 0
        and unclassified_errors == 0
        and successful_gate_failures == 0
        and compatible
    )
    return metrics


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
    errors = _structured_errors(debug_dir)
    return errors[0] if errors else None


def _structured_errors(debug_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(debug_dir.glob("attempt-*.structured-error.json")):
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        result.append(
            {
                key: payload.get(key)
                for key in ("stage", "code", "message", "retryable", "details")
                if key in payload
            }
        )
    return result


def _failure_key(error: dict[str, Any]) -> tuple[str, str]:
    return (
        str(error.get("layer") or error.get("stage") or "unknown"),
        str(error.get("code") or "unknown"),
    )


def _root_issues(error: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    details = error.get("details")
    raw_roots = details.get("root_issues") if isinstance(details, dict) else None
    roots = raw_roots if isinstance(raw_roots, list) else [error]
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for item in roots:
        if not isinstance(item, dict):
            continue
        stage, code = _failure_key(item)
        step_id = item.get("step_id")
        key = (stage, code, str(step_id) if step_id is not None else None)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return tuple(result) or (error,)


def _is_unclassified_failure(stage: str, code: str) -> bool:
    return (
        stage not in KNOWN_FAILURE_LAYERS
        or code in UNCLASSIFIED_FAILURE_CODES
        or stage == "unknown"
        or code == "unknown"
    )


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


def _source_fingerprint() -> dict[str, Any]:
    revision = _git_output("rev-parse", "HEAD")
    dirty = bool(_git_output("status", "--porcelain"))
    source_paths: list[Path] = sorted(
        (SERVER_ROOT / "shuxueshuo_server" / "solver").rglob("*.py")
    )
    source_paths.extend(sorted((REPO_ROOT / "internal" / "llm-prompts").glob("*.jinja")))
    evaluation_paths = [
        SERVER_ROOT / "tests" / "solver" / "_functional_opt_in_support.py",
        SERVER_ROOT / "tests" / "solver" / "test_deepseek_functional_batch.py",
    ]
    evaluation_paths.extend(
        SERVER_ROOT / case.test_path
        for case in FUNCTIONAL_BATCH_CASES.values()
    )
    return {
        "git_revision": revision,
        "worktree_dirty": dirty,
        "solver_source_sha256": _hash_files(source_paths),
        "evaluation_source_sha256": _hash_files(evaluation_paths),
    }


def _sample_fingerprints(
    sample: BatchSample,
    *,
    source_fingerprint: dict[str, Any],
    models: Sequence[str],
    functional_transaction_mode: str,
    functional_symbolic_closure_mode: str,
) -> dict[str, Any]:
    prompt_paths = (
        sample.debug_dir / "attempt-1.prompt.system.md",
        sample.debug_dir / "attempt-1.prompt.user.md",
    )
    catalog_path = sample.debug_dir / "attempt-1.payload.functional_capability_catalog.json"
    fixture_paths = (
        sample.case.problem_fixture_path,
        sample.case.functional_fixture_path,
        sample.case.recorded_step_intent_path,
        sample.case.expected_path,
    )
    payload = {
        **source_fingerprint,
        "prompt_sha256": _hash_files(prompt_paths),
        "catalog_sha256": _hash_files((catalog_path,)),
        "fixture_sha256": _hash_files(fixture_paths),
        "models": list(models),
        "functional_transaction_mode": functional_transaction_mode,
        "functional_symbolic_closure_mode": (
            functional_symbolic_closure_mode
        ),
    }
    payload["compatibility_key"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def _hash_files(paths: Iterable[Path]) -> str | None:
    existing = [path for path in paths if path.exists() and path.is_file()]
    if not existing:
        return None
    digest = hashlib.sha256()
    for path in sorted(existing):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_output(*args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


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
