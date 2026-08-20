"""Run the live Doubao extraction -> verified Bundle -> DeepSeek Solver cold path."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver import load_expected_answers
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DoubaoMultimodalExtractionProvider,
)
from shuxueshuo_server.solver.extraction.problem_cold_path import (
    ProblemColdPathService,
)
from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_debug import (
    ProblemDomainDebugWriter,
)
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    ProblemDomainExtractionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _load_domain_gold,
    _load_f2_context,
    _repo_root,
    _resolve_repo_path,
    _selected_cases,
    _uses_patch_after_first_draft,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.semantic_diff import (
    compare_solver_projection_semantics,
)
from shuxueshuo_server.solver.functional_parity import (
    provenance_parity_signature,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator


DEFAULT_OUTPUT_ROOT = "internal/solver-runs/problem-extraction/problem-cold-path"


@dataclass(frozen=True)
class ColdPathSmokeSampleResult:
    problem_id: str
    sample_index: int
    extraction_accepted: bool
    solver_ok: bool
    extraction_attempt_count: int
    planner_attempt_count: int
    full_question_image_input: bool
    retry_patch_only: bool
    domain_semantic_diff_ok: bool
    solver_projection_diff_ok: bool
    answer_ok: bool
    scope_native_prompt_ok: bool
    authority_ok: bool
    runtime_gate_ok: bool
    provenance_ok: bool
    extraction_usage: Mapping[str, float]
    planner_usage: Mapping[str, int]
    extraction_latency_ms: int
    planner_latency_ms: int
    failures: tuple[str, ...]
    sample_dir: str

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_payload(self) -> dict[str, Any]:
        return {
            "problem_id": self.problem_id,
            "sample_index": self.sample_index,
            "ok": self.ok,
            "extraction_accepted": self.extraction_accepted,
            "solver_ok": self.solver_ok,
            "extraction_attempt_count": self.extraction_attempt_count,
            "planner_attempt_count": self.planner_attempt_count,
            "full_question_image_input": self.full_question_image_input,
            "retry_patch_only": self.retry_patch_only,
            "domain_semantic_diff_ok": self.domain_semantic_diff_ok,
            "solver_projection_diff_ok": self.solver_projection_diff_ok,
            "answer_ok": self.answer_ok,
            "scope_native_prompt_ok": self.scope_native_prompt_ok,
            "authority_ok": self.authority_ok,
            "runtime_gate_ok": self.runtime_gate_ok,
            "provenance_ok": self.provenance_ok,
            "extraction_usage": dict(self.extraction_usage),
            "planner_usage": dict(self.planner_usage),
            "extraction_latency_ms": self.extraction_latency_ms,
            "planner_latency_ms": self.planner_latency_ms,
            "failures": list(self.failures),
            "sample_dir": self.sample_dir,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all")
    parser.add_argument("--samples-per-case", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--extraction-max-attempts", type=int, default=3)
    parser.add_argument("--planner-max-attempts", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--f2-input-dir", default=DEFAULT_F2_INPUT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if min(
        args.samples_per_case,
        args.concurrency,
        args.extraction_max_attempts,
        args.planner_max_attempts,
        args.request_timeout_seconds,
    ) < 1:
        parser.error("sample, attempt, concurrency, and timeout values must be positive")
    if os.environ.get("RUN_LLM_INTEGRATION") != "1":
        parser.error("live cold-path smoke requires RUN_LLM_INTEGRATION=1")

    repo_root = _repo_root()
    f2_root = _resolve_repo_path(repo_root, args.f2_input_dir)
    output_root = _resolve_repo_path(repo_root, args.output_root)
    batch_dir = output_root / args.batch_id
    if batch_dir.exists():
        parser.error(f"batch output already exists: {batch_dir}")
    batch_dir.mkdir(parents=True)
    config = SolverRuntimeConfig.from_sources(
        planner_mode="strategy",
        llm_provider="deepseek",
        max_llm_attempts=args.planner_max_attempts,
        env_file=repo_root / "server/.env",
    )
    if not config.doubao_api_key:
        parser.error("DOUBAO_API_KEY is required for cold-path extraction")
    if not config.deepseek_api_key:
        parser.error("DEEPSEEK_API_KEY is required for cold-path planning")
    cases = _selected_cases(load_gold_corpus().cases, args.case, parser)
    batch_config = {
        "schema_version": "problem-cold-path-smoke-config/v1",
        "batch_id": args.batch_id,
        "case_ids": [item.problem_id for item in cases],
        "samples_per_case": args.samples_per_case,
        "concurrency": args.concurrency,
        "extraction_max_attempts": args.extraction_max_attempts,
        "planner_max_attempts": args.planner_max_attempts,
        "extraction_provider": "doubao",
        "extraction_model": config.doubao_model,
        "planner_provider": "deepseek",
        "planner_model": config.llm_model or config.deepseek_model,
        "planner_protocol": "functional_plan/v1",
        "problem_authority": "verified-solver-problem-bundle/v1",
        "planning_context": "planner-problem-view/v2",
        "retry_checkpoint": "functional-goal-execution-checkpoint/v3",
        "f2_input_dir": str(f2_root),
    }
    _write_json(batch_dir / "batch-config.json", batch_config)

    jobs = [
        (case, sample_index)
        for case in cases
        for sample_index in range(1, args.samples_per_case + 1)
    ]
    results: list[ColdPathSmokeSampleResult] = []
    with ThreadPoolExecutor(max_workers=min(args.concurrency, len(jobs))) as executor:
        futures = {
            executor.submit(
                _run_sample,
                case,
                sample_index,
                batch_dir=batch_dir,
                f2_root=f2_root,
                config=config,
                extraction_max_attempts=args.extraction_max_attempts,
                planner_max_attempts=args.planner_max_attempts,
                request_timeout=args.request_timeout_seconds,
            ): (case.problem_id, sample_index)
            for case, sample_index in jobs
        }
        for future in as_completed(futures):
            problem_id, sample_index = futures[future]
            try:
                item = future.result()
            except Exception as exc:
                sample_dir = batch_dir / problem_id / f"sample-{sample_index:02d}"
                sample_dir.mkdir(parents=True, exist_ok=True)
                item = _failed_sample(
                    problem_id,
                    sample_index,
                    sample_dir,
                    f"unclassified:{exc.__class__.__name__}:{exc}",
                )
                _write_json(sample_dir / "cold-path-result.json", item.to_payload())
            results.append(item)
            print(
                f"{problem_id}/sample-{sample_index:02d}: "
                f"ok={item.ok} extraction={item.extraction_attempt_count} "
                f"planner={item.planner_attempt_count}",
                flush=True,
            )

    summary = _summary(batch_config, results)
    _write_json(batch_dir / "batch-summary.json", summary)
    _write_index(batch_dir, results)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


def _run_sample(
    case: GoldCorpusCase,
    sample_index: int,
    *,
    batch_dir: Path,
    f2_root: Path,
    config: SolverRuntimeConfig,
    extraction_max_attempts: int,
    planner_max_attempts: int,
    request_timeout: float,
) -> ColdPathSmokeSampleResult:
    sample_dir = batch_dir / case.problem_id / f"sample-{sample_index:02d}"
    sample_dir.mkdir(parents=True, exist_ok=True)
    root_context, f2_context = _load_f2_context(case, f2_root)
    input_store = ExtractionArtifactStore(f2_root / "artifacts")
    output_store = ExtractionArtifactStore(sample_dir / "artifacts")
    provider = DoubaoMultimodalExtractionProvider(
        api_key=config.doubao_api_key or "",
        base_url=config.doubao_base_url,
        model=config.doubao_model,
        request_timeout=request_timeout,
    )
    extraction_service = ProblemDomainExtractionService(
        input_artifact_reader=input_store,
        output_artifact_store=output_store,
        provider=provider,
    )
    planner_config = replace(
        config,
        max_llm_attempts=planner_max_attempts,
        llm_debug_dir=str(sample_dir / "planner"),
    )
    orchestrator_box: dict[str, RuntimeOrchestrator] = {}

    def solve_verified(bundle, runtime_config):
        orchestrator = RuntimeOrchestrator(
            family_registry=runtime_config.build_family_registry(),
            planner_providers=runtime_config.build_planner_providers(),
            default_planner_provider=runtime_config.build_default_planner_provider(),
            max_attempts=runtime_config.max_llm_attempts,
            debug_dir=runtime_config.llm_debug_dir,
        )
        orchestrator_box["orchestrator"] = orchestrator
        return orchestrator.solve_verified(bundle)

    cold = ProblemColdPathService(
        extraction_service,
        solver=solve_verified,
    ).run(
        f2_context,
        ExtractionAttemptLedger.for_context(f2_context),
        (root_context,),
        extraction_max_attempts=extraction_max_attempts,
        solver_runtime_config=planner_config,
    )
    ProblemDomainDebugWriter().write(cold.extraction, sample_dir)

    expected_draft = ProblemDraft.create(_load_domain_gold(case.problem_id))
    expected_validation = ProblemDomainValidator().validate(expected_draft)
    actual_graph = (
        cold.extraction.verified_problem.graph
        if cold.extraction.verified_problem
        else None
    )
    domain_ok = bool(
        actual_graph is not None
        and actual_graph.semantic_hash == expected_draft.graph.semantic_hash
    )
    expected_projection = expected_validation.projection
    projection_ok = bool(
        cold.extraction.solver_projection is not None
        and expected_projection is not None
        and compare_solver_projection_semantics(
            expected_projection.canonical_input,
            cold.extraction.solver_projection.canonical_input,
        ).ok
    )
    full_image = bool(cold.extraction.attempts) and all(
        any(image.role == "primary" for image in attempt.request.images)
        for attempt in cold.extraction.attempts
    )
    patch_only = _uses_patch_after_first_draft(cold.extraction.attempts)
    expected_answers = load_expected_answers(
        _repo_root()
        / "server/tests/solver/expected"
        / f"{case.problem_id}.expected.json"
    )
    answer_ok = bool(
        cold.solver_result is not None
        and _semantic_equal(cold.solver_result.answers, expected_answers)
    )
    orchestrator = orchestrator_box.get("orchestrator")
    planner_attempt_count = (
        len(orchestrator.last_session.attempts)
        if orchestrator is not None and orchestrator.last_session is not None
        else 0
    )
    success = orchestrator.last_success_artifacts if orchestrator is not None else None
    authority_ok = bool(
        cold.bundle is not None
        and cold.problem_authority is not None
        and success is not None
        and success.problem_authority is not None
        and success.problem_binding_catalog is not None
        and success.planner_state_context is not None
        and success.problem_authority.bundle.authority_token
        == cold.bundle.authority_token
    )
    runtime_gate_ok = bool(
        cold.solver_result is not None
        and cold.solver_result.ok
        and all(check.ok for check in cold.solver_result.checks)
    )
    provenance_ok = False
    if success is not None:
        replay = success.planner.artifacts.retry_replay_result
        if replay is not None and replay.diagnostic is not None:
            provenance_ok = not provenance_parity_signature(
                replay.diagnostic
            ).integrity_issues
            report = replay.transactional_execution_report
            runtime_gate_ok = bool(
                runtime_gate_ok
                and report is not None
                and report.functional_compile_drift_count == 0
                and report.symbolic_closure_drift_count == 0
            )
    scope_prompt_ok = _scope_native_prompt_ok(sample_dir / "planner")

    failures: list[str] = []
    for ok, code in (
        (cold.accepted, "extraction_not_accepted"),
        (cold.solved, "solver_failed"),
        (full_image, "full_question_image_missing"),
        (patch_only, "semantic_retry_not_patch"),
        (domain_ok, "domain_semantic_diff"),
        (projection_ok, "solver_projection_diff"),
        (answer_ok, "answer_mismatch"),
        (scope_prompt_ok, "scope_native_prompt_invalid"),
        (authority_ok, "problem_authority_incomplete"),
        (runtime_gate_ok, "runtime_gate_failed"),
        (provenance_ok, "provenance_gate_failed"),
    ):
        if not ok:
            failures.append(code)
    item = ColdPathSmokeSampleResult(
        problem_id=case.problem_id,
        sample_index=sample_index,
        extraction_accepted=cold.accepted,
        solver_ok=cold.solved,
        extraction_attempt_count=len(cold.extraction.attempts),
        planner_attempt_count=planner_attempt_count,
        full_question_image_input=full_image,
        retry_patch_only=patch_only,
        domain_semantic_diff_ok=domain_ok,
        solver_projection_diff_ok=projection_ok,
        answer_ok=answer_ok,
        scope_native_prompt_ok=scope_prompt_ok,
        authority_ok=authority_ok,
        runtime_gate_ok=runtime_gate_ok,
        provenance_ok=provenance_ok,
        extraction_usage=cold.extraction_usage or {},
        planner_usage=cold.planner_usage or {},
        extraction_latency_ms=cold.extraction_latency_ms,
        planner_latency_ms=cold.planner_latency_ms,
        failures=tuple(failures),
        sample_dir=str(sample_dir),
    )
    _write_json(sample_dir / "cold-path-result.json", item.to_payload())
    return item


def _scope_native_prompt_ok(planner_dir: Path) -> bool:
    contexts = sorted(planner_dir.glob("attempt-*.payload.problem_planning_context.json"))
    if not contexts or list(planner_dir.glob("attempt-*.payload.problem_ir.json")):
        return False
    for path in contexts:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        if payload.get("schema_version") != "planner-problem-view/v2":
            return False
    return True


def _semantic_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(actual, Mapping) and set(actual) == set(expected) and all(
            _semantic_equal(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, (list, tuple)):
        return isinstance(actual, (list, tuple)) and len(actual) == len(expected) and all(
            _semantic_equal(left, right) for left, right in zip(actual, expected)
        )
    if actual == expected:
        return True
    if isinstance(actual, str) and isinstance(expected, str):
        try:
            return sp.simplify(sp.sympify(actual) - sp.sympify(expected)) == 0
        except (TypeError, ValueError, sp.SympifyError):
            return False
    return False


def _failed_sample(
    problem_id: str,
    sample_index: int,
    sample_dir: Path,
    failure: str,
) -> ColdPathSmokeSampleResult:
    return ColdPathSmokeSampleResult(
        problem_id=problem_id,
        sample_index=sample_index,
        extraction_accepted=False,
        solver_ok=False,
        extraction_attempt_count=0,
        planner_attempt_count=0,
        full_question_image_input=False,
        retry_patch_only=False,
        domain_semantic_diff_ok=False,
        solver_projection_diff_ok=False,
        answer_ok=False,
        scope_native_prompt_ok=False,
        authority_ok=False,
        runtime_gate_ok=False,
        provenance_ok=False,
        extraction_usage={},
        planner_usage={},
        extraction_latency_ms=0,
        planner_latency_ms=0,
        failures=(failure,),
        sample_dir=str(sample_dir),
    )


def _summary(
    config: Mapping[str, Any],
    results: Sequence[ColdPathSmokeSampleResult],
) -> dict[str, Any]:
    total = len(results)
    extraction_usage: dict[str, float] = {}
    planner_usage: dict[str, int] = {}
    for item in results:
        for key, value in item.extraction_usage.items():
            extraction_usage[key] = extraction_usage.get(key, 0.0) + value
        for key, value in item.planner_usage.items():
            planner_usage[key] = planner_usage.get(key, 0) + value
    return {
        **dict(config),
        "schema_version": "problem-cold-path-smoke-summary/v1",
        "ok": total > 0 and all(item.ok for item in results),
        "sample_count": total,
        "passed_count": sum(item.ok for item in results),
        "extraction_accepted_count": sum(item.extraction_accepted for item in results),
        "solver_passed_count": sum(item.solver_ok for item in results),
        "full_question_image_input_rate": (
            round(sum(item.full_question_image_input for item in results) / total, 6)
            if total
            else 0.0
        ),
        "scope_native_prompt_rate": (
            round(sum(item.scope_native_prompt_ok for item in results) / total, 6)
            if total
            else 0.0
        ),
        "configuration_error_count": sum(
            any("configuration" in failure for failure in item.failures)
            for item in results
        ),
        "unclassified_error_count": sum(
            any(failure.startswith("unclassified:") for failure in item.failures)
            for item in results
        ),
        "extraction_usage": extraction_usage,
        "planner_usage": planner_usage,
        "extraction_latency_ms": sum(item.extraction_latency_ms for item in results),
        "planner_latency_ms": sum(item.planner_latency_ms for item in results),
        "cases": [
            item.to_payload()
            for item in sorted(results, key=lambda value: (value.problem_id, value.sample_index))
        ],
        "review_index": "review.html",
    }


def _write_index(
    batch_dir: Path,
    results: Sequence[ColdPathSmokeSampleResult],
) -> None:
    links = "".join(
        f'<li><a href="{Path(item.sample_dir).relative_to(batch_dir).as_posix()}/review.html">'
        f"{item.problem_id}/sample-{item.sample_index:02d}</a> · "
        f"{'PASS' if item.ok else 'FAIL'}</li>"
        for item in sorted(results, key=lambda value: (value.problem_id, value.sample_index))
    )
    (batch_dir / "review.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Problem cold path</title>'
        '<style>body{font:15px system-ui;max-width:900px;margin:32px auto;line-height:1.6}</style>'
        "<h1>图片到求解 Cold Path 审查</h1><ul>" + links + "</ul>",
        encoding="utf-8",
    )


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
