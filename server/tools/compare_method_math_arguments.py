"""Frozen Method-argument equivalence and 5 x 2 x 3 Planner comparison.

Run offline first; run live only after the full offline Solver gates pass.
Live uses existing semantic/transport retries and records all provider attempts.
No extraction, source review, paid explanation, or product admission is run.
"""

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server/tests/solver"))

from _math_runtime_binding_support import (
    CASES,
    assert_expected,
    binding,
    candidate,
    execution_audit,
    replay,
    replay_errors,
    reviewed_authority,
)

from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.functional_attempt_evidence import (
    write_scoped_attempt_evidence,
)
from shuxueshuo_server.solver.runtime.functional_plan_capabilities import (
    FunctionalCapabilityCatalog,
)
from shuxueshuo_server.solver.runtime.functional_plan_content import (
    FunctionalPlanAuthorityFrame,
    FunctionalPlanContentCompiler,
    functional_plan_content_from_plan,
)
from shuxueshuo_server.solver.runtime.llm_debug import safe_debug_json, write_debug_json
from shuxueshuo_server.solver.runtime.method_math_arguments import (
    MATH_EXPRESSIONS,
    SOURCE_REFS,
    MethodMathArgumentResolver,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    StrategyPlanner,
)


def digest(value):
    return sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_debug_json(path, value)


def code_fingerprint():
    paths = set()
    for directory in (
        "server/shuxueshuo_server/solver/runtime",
        "server/shuxueshuo_server/problem_understanding",
        "internal/functional-few-shots-v2",
        "internal/functional-few-shots-v2-math",
        "internal/llm-prompts",
    ):
        paths.update(
            p
            for p in (ROOT / directory).rglob("*")
            if p.suffix in (".py", ".json", ".jinja")
        )
    return digest(
        {
            str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)
        }
    )


def planner(bound, encoding, **kwargs):
    return StrategyPlanner(
        ContextBuilder().build(bound.bundle.build_solver_problem()),
        problem_authority=reviewed_authority(bound),
        argument_encoding=encoding,
        **kwargs,
    )


def offline(output):
    checks = []
    for case in CASES:
        for authored in (False, True):
            origin = "authored" if authored else "recorded"
            bound = binding(case, authored)
            catalog = FunctionalCapabilityCatalog.from_family_spec(
                bound.inputs.family_spec, bound.inputs.method_specs
            )
            resolver = MethodMathArgumentResolver(
                bound.bundle, bound.planning_context, bound.binding_catalog, catalog
            )
            frame = FunctionalPlanAuthorityFrame.from_planning_context(
                bound.planning_context
            )
            with TemporaryDirectory(prefix="method-math-equivalence-") as tmp:
                old = replay(case, bound, Path(tmp) / "source")
                assert old.status == "accepted", replay_errors(old)
                content = functional_plan_content_from_plan(
                    old.final_plan, frame=frame
                ).to_payload()
                math, _ = resolver.transform(content, encode=True)
                canonical, audit = resolver.transform(math)
                assert canonical == content
                math_dir = Path(tmp) / "math"
                save(math_dir / f"{case}.functional-plan-content.json", math)
                new = planner(
                    bound, MATH_EXPRESSIONS, scoped_functional_plan_fixture_dir=math_dir
                ).run_scoped(bound.inputs, max_attempts=1)
            assert new.status == "accepted", replay_errors(new)
            assert new.final_plan.to_payload() == old.final_plan.to_payload()
            before, after = execution_audit(bound, old), execution_audit(bound, new)
            assert before == after
            assert_expected(case, bound, new)
            folder = output / "offline" / case / origin
            for name, data in (
                ("candidate", candidate(case, authored)),
                ("source-content", content),
                ("math-content", math),
                ("bindings", audit),
                ("execution-audit", after),
            ):
                save(folder / f"{name}.json", data)
            checks.append(
                {
                    "case": case,
                    "origin": origin,
                    "status": "passed",
                    "canonical_plan_sha256": digest(new.final_plan.to_payload()),
                    "execution_audit_sha256": digest(after),
                    "bindings": len(audit),
                }
            )
            print(case, origin, "equivalent", flush=True)
    save(
        output / "offline.json",
        {
            "checks": checks,
            "status": "passed",
            "model_calls": 0,
            "code_fingerprint": code_fingerprint(),
            "current_product_admission": False,
        },
    )


def live_job(output_string, case, encoding, sample, frozen_digest):
    output = Path(output_string)
    label = "math" if encoding == MATH_EXPRESSIONS else "source"
    folder = output / "live" / case / label / str(sample)
    result_path = folder / "result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text())
        assert result["frozen_digest"] == frozen_digest
        return result
    # An interrupted paid attempt is not automatically resubmitted.
    started = folder / "started.json"
    if started.exists() and tuple(folder.glob("attempt-*.evidence-index.json")):
        raise RuntimeError(
            f"Unfinished run requires evidence review before resuming: {folder}"
        )
    save(
        started,
        {
            "case": case,
            "encoding": encoding,
            "sample": sample,
            "frozen_digest": frozen_digest,
        },
    )
    bound = binding(case)
    config = SolverRuntimeConfig.from_sources(
        llm_provider="deepseek", max_llm_attempts=3
    )
    client = config.build_llm_client(thinking_effort="low")
    started_at = time.monotonic()
    observed = {}

    def observe(attempt):
        observed[attempt.semantic_attempt] = attempt
        write_scoped_attempt_evidence(folder, attempt)

    failure = None
    try:
        result = planner(bound, encoding, mode="deepseek", client=client).run_scoped(
            bound.inputs,
            max_attempts=config.max_llm_attempts,
            attempt_observer=observe,
        )
    except Exception as exc:  # noqa: BLE001 - persist terminal worker failures without retrying
        # Runtime failures remain terminal under the original rules. Serialize
        # them here so a non-pickleable exception cannot kill unrelated workers.
        result = None
        failure = {"type": type(exc).__name__, "message": str(exc)}
    elapsed = time.monotonic() - started_at
    answer_match = False
    answer_error = None
    status = result.status if result is not None else "execution_failed"
    if status == "accepted":
        try:
            assert_expected(case, bound, result)
            answer_match = True
        except AssertionError as exc:
            answer_error = str(exc)
        save(folder / "execution-audit.json", execution_audit(bound, result))
    tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage_complete = True
    attempts = []
    run_attempts = (
        result.attempts
        if result is not None
        else tuple(observed[k] for k in sorted(observed))
    )
    for attempt in run_attempts:
        metadata = attempt.llm_metadata or {}
        usage = metadata.get("usage")
        usage_complete = usage_complete and usage is not None
        for key in tokens:
            tokens[key] += (usage or {}).get(key) or 0
        errors = _attempt_error_payloads(attempt)
        attempts.append(
            {
                "attempt": attempt.semantic_attempt,
                "protocol": attempt.planner_protocol,
                "errors": errors,
                "provider_requests": len(metadata.get("provider_requests") or []),
                "usage": usage,
            }
        )
    first = run_attempts[0] if run_attempts else None
    first_success = bool(
        first
        and first.execution
        and first.execution.verified_execution
        and first.final_plan_contract_validation
        and first.final_plan_contract_validation.ok
    )
    record = {
        "case": case,
        "encoding": encoding,
        "sample": sample,
        "frozen_digest": frozen_digest,
        "status": status,
        "terminal_exception": failure,
        "first_success": first_success,
        "final_success": status == "accepted" and answer_match,
        "answers_match": answer_match,
        "answer_error": answer_error,
        "semantic_attempts": len(attempts),
        "retries": max(0, len(attempts) - 1),
        "seconds": elapsed,
        "tokens": tokens if usage_complete else None,
        "observed_tokens": tokens,
        "usage_complete": usage_complete,
        "attempts": attempts,
    }
    record = safe_debug_json(record)
    save(result_path, record)
    return record


def _attempt_error_payloads(attempt: Any) -> list[dict[str, Any]]:
    """Collect one semantic attempt's diagnostics from every replay layer.

    The checkpoint is not guaranteed to carry the transactional root issue:
    goal verification and Method failures can be present only on the replay's
    transactional attempt result.  The old report therefore emitted
    ``errors=[]`` for real blocked attempts.  Keep the report additive and
    de-duplicate equivalent envelopes by their stable JSON representation.
    """

    candidates: list[Any] = []
    if attempt.error is not None:
        candidates.append(attempt.error)
    execution = attempt.execution
    if execution is not None:
        checkpoint = execution.checkpoint
        if checkpoint is not None:
            candidates.extend(checkpoint.root_issues)
        replay = execution.replay
        if replay is not None:
            candidates.extend(replay.goal_verification_issues)
            transactional = replay.transactional_attempt_result
            if transactional is not None:
                candidates.extend(transactional.root_issues)
            report = replay.transactional_execution_report
            if report is not None:
                candidates.extend(report.compatibility_mismatches)

    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidates:
        if hasattr(item, "to_payload"):
            item = item.to_payload()
        elif hasattr(item, "to_authority_payload"):
            item = item.to_authority_payload()
        if not isinstance(item, Mapping):
            continue
        payload = dict(item)
        key = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        payloads.append(payload)
    return payloads


def pages(output, page_output):
    """Drive both encodings through the existing Solver -> Snapshot boundary."""
    from shuxueshuo_server.solver.explanation.snapshot import ExplanationSnapshotBuilder
    from shuxueshuo_server.solver.lesson_capability_coverage_review import (
        _build_case,
        _write_case,
    )
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
        strategy_planner_provider,
    )

    checks = []
    for case in CASES:
        bound = binding(case)
        folder = output / "offline" / case / "recorded"
        catalog = FunctionalCapabilityCatalog.from_family_spec(
            bound.inputs.family_spec, bound.inputs.method_specs
        )
        frame = FunctionalPlanAuthorityFrame.from_planning_context(
            bound.planning_context
        )
        content = json.loads((folder / "source-content.json").read_text())
        compiled = FunctionalPlanContentCompiler().compile_payload(
            content, frame=frame, capability_catalog=catalog
        )
        assert compiled.report.ok
        snapshots = []
        with TemporaryDirectory(prefix="method-math-page-") as temp:
            fixtures = Path(temp)
            save(fixtures / f"{case}.functional-plan.json", compiled.plan.to_payload())
            save(
                fixtures / f"{case}.functional-plan-content.json",
                json.loads((folder / "math-content.json").read_text()),
            )
            for encoding in (SOURCE_REFS, MATH_EXPRESSIONS):
                orchestrator = RuntimeOrchestrator(
                    default_planner_provider=strategy_planner_provider(
                        mode="recorded",
                        argument_encoding=encoding,
                        scoped_functional_plan_fixture_dir=fixtures,
                    ),
                    max_attempts=1,
                )
                result = orchestrator.solve_verified(reviewed_authority(bound).bundle)
                assert result.status == "ok", result.errors
                snapshots.append(
                    ExplanationSnapshotBuilder().build(
                        orchestrator.last_success_artifacts
                    )
                )
        assert snapshots[0].to_payload() == snapshots[1].to_payload()
        built = _build_case(snapshots[1])
        destination = page_output / case
        _write_case(destination.resolve(), built)
        audit = json.loads((destination / "audit.json").read_text())
        checks.append({"case": case, "snapshot_identical": True, **audit})
        print(
            case,
            "identical Snapshot; LessonIR, VisualStepIR and page passed",
            flush=True,
        )
    save(
        page_output / "equivalence.json",
        {"model_calls": 0, "checks": checks, "current_product_admission": False},
    )


def report(output, records, frozen):
    records = sorted(records, key=lambda r: (r["case"], r["encoding"], r["sample"]))
    summary = {}
    for mode in (SOURCE_REFS, MATH_EXPRESSIONS):
        rows = [r for r in records if r["encoding"] == mode]
        interrupted = [r for r in rows if r["status"] == "interrupted_response_unknown"]
        resolved = len(rows) - len(interrupted)
        final_successes = sum(r["final_success"] for r in rows)
        timed = [r for r in rows if r["seconds"] is not None]
        error_codes = {}
        for row in rows:
            for attempt in row["attempts"]:
                for error in attempt["errors"]:
                    code = error.get("code", "unknown")
                    error_codes[code] = error_codes.get(code, 0) + 1
        summary[mode] = {
            "runs": len(rows),
            "first_successes": sum(r["first_success"] for r in rows),
            "final_successes": final_successes,
            "resolved_runs": resolved,
            "final_success_rate_observed": final_successes / resolved
            if resolved
            else None,
            "final_success_rate_lower_bound": final_successes / len(rows)
            if rows
            else None,
            "retries": sum(r["retries"] for r in rows),
            "binding_errors": sum(
                "math_argument" in str(e.get("code", ""))
                or "binding" in str(e.get("code", ""))
                for r in rows
                for a in r["attempts"]
                for e in a["errors"]
            ),
            "usage_complete": all(r["usage_complete"] for r in rows),
            "observed_tokens": {
                k: sum(r["observed_tokens"][k] for r in rows)
                for k in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
            "total_run_seconds": sum(r["seconds"] for r in timed),
            "timed_runs": len(timed),
            "mean_timed_run_seconds": (
                sum(r["seconds"] for r in timed) / len(timed) if timed else None
            ),
            "timing_complete": all(r["seconds"] is not None for r in rows),
            "interrupted_runs": len(interrupted),
            "attempt_error_codes": error_codes,
        }
    save(
        output / "live-report.json",
        {
            "frozen": frozen,
            "summary": summary,
            "runs": records,
            "current_product_admission": False,
            "paid_extraction_calls": 0,
            "paid_explanation_calls": 0,
        },
    )
    return summary


def live(output, workers):
    gate = json.loads((output / "offline.json").read_text())
    assert gate["status"] == "passed" and len(gate["checks"]) == 10
    assert gate["code_fingerprint"] == code_fingerprint(), (
        "Repeat offline equivalence after code changes"
    )
    config = SolverRuntimeConfig.from_sources(
        llm_provider="deepseek", max_llm_attempts=3
    )
    frozen = {
        "code_fingerprint": code_fingerprint(),
        "cases": {c: digest(candidate(c)) for c in CASES},
        "model": config.llm_model or config.deepseek_model,
        "base_url": config.deepseek_base_url,
        "thinking_effort": "low",
        "request_timeout": 120,
        "sdk_max_retries": "provider_default",
        "reasoning_only_empty_response_retry": True,
        "semantic_attempt_budget": config.max_llm_attempts,
        "encodings": [SOURCE_REFS, MATH_EXPRESSIONS],
        "samples_per_case_and_encoding": 3,
        "authority": "frozen_input_with_synthetic_test_admission",
    }
    frozen_path = output / "frozen.json"
    if frozen_path.exists():
        assert json.loads(frozen_path.read_text()) == frozen, (
            "Frozen comparison configuration changed"
        )
    else:
        save(frozen_path, frozen)
    records = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs = [
            pool.submit(live_job, str(output), c, e, s, digest(frozen))
            for s in range(1, 4)
            for c in CASES
            for e in (SOURCE_REFS, MATH_EXPRESSIONS)
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
    assert len(records) == 30
    print(
        json.dumps(report(output, records, frozen), ensure_ascii=False, indent=2),
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("offline", "live", "pages", "report"), default="offline"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page-output", type=Path)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.workers <= 3:
        parser.error("workers must be between 1 and 3")
    output = args.output.resolve()
    if args.phase == "offline":
        offline(output)
    elif args.phase == "pages":
        pages(output, (args.page_output or output / "pages").resolve())
    elif args.phase == "report":
        rows = [
            json.loads(p.read_text())
            for p in sorted((output / "live").glob("*/*/*/result.json"))
        ]
        print(
            json.dumps(
                report(output, rows, json.loads((output / "frozen.json").read_text())),
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        live(output, args.workers)


if __name__ == "__main__":
    main()
