"""Run domain-only multimodal extraction acceptance without Planner or Solver."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    ProblemExtractionContext,
)
from shuxueshuo_server.solver.extraction.f0_adapter import (
    build_f0_extraction_context_seed,
)
from shuxueshuo_server.solver.extraction.gold_corpus import (
    GoldCorpusCase,
    load_gold_corpus,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MULTIMODAL_MAX_OUTPUT_TOKENS,
    MULTIMODAL_PASS1_THINKING_MODE,
    MULTIMODAL_RETRY_REASONING_EFFORT,
    MULTIMODAL_RETRY_THINKING_MODE,
    PASS1_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    DeepSeekTextProblemDomainProvider,
    DoubaoMultimodalExtractionProvider,
    problem_domain_family_catalog,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    problem_domain_provider_schema,
    problem_repair_provider_schema,
)
from shuxueshuo_server.solver.extraction.problem_domain_debug import (
    ProblemDomainDebugWriter,
)
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    ProblemDomainExtractionAttemptResult,
    ProblemDomainExtractionRunResult,
    ProblemDomainExtractionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.semantic_diff import (
    compare_solver_projection_semantics,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig


DEFAULT_F2_INPUT = "internal/solver-runs/problem-extraction/f2-problem-domain-input"


@dataclass(frozen=True)
class ProblemDomainSmokeSampleResult:
    problem_id: str
    sample_index: int
    accepted: bool
    attempt_count: int
    final_issue_code: str | None
    provider: str
    source_input_complete: bool
    full_question_image_input: bool
    retry_patch_only: bool
    family_ok: bool
    domain_semantic_diff_ok: bool
    solver_projection_diff_ok: bool
    usage: Mapping[str, float]
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
            "accepted": self.accepted,
            "attempt_count": self.attempt_count,
            "final_issue_code": self.final_issue_code,
            "provider": self.provider,
            "source_input_complete": self.source_input_complete,
            "full_question_image_input": self.full_question_image_input,
            "retry_patch_only": self.retry_patch_only,
            "family_ok": self.family_ok,
            "domain_semantic_diff_ok": self.domain_semantic_diff_ok,
            "solver_projection_diff_ok": self.solver_projection_diff_ok,
            "usage": dict(self.usage),
            "failures": list(self.failures),
            "sample_dir": self.sample_dir,
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all")
    parser.add_argument("--samples-per-case", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--provider", choices=("doubao", "deepseek"), default="doubao")
    parser.add_argument("--request-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--f2-input-dir", default=DEFAULT_F2_INPUT)
    parser.add_argument(
        "--output-root",
        default="internal/solver-runs/problem-extraction/problem-domain",
    )
    args = parser.parse_args(argv)
    if min(
        args.samples_per_case,
        args.max_attempts,
        args.concurrency,
        args.request_timeout_seconds,
    ) < 1:
        parser.error("sample, attempt, and concurrency values must be positive")
    if os.environ.get("RUN_LLM_INTEGRATION") != "1":
        parser.error("live Problem domain smoke requires RUN_LLM_INTEGRATION=1")

    repo_root = _repo_root()
    f2_root = _resolve_repo_path(repo_root, args.f2_input_dir)
    output_root = _resolve_repo_path(repo_root, args.output_root)
    batch_dir = output_root / args.batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    config = SolverRuntimeConfig.from_sources(env_file=repo_root / "server/.env")
    provider_model = (
        config.doubao_model if args.provider == "doubao" else config.deepseek_model
    )
    cases = _selected_cases(load_gold_corpus().cases, args.case, parser)
    batch_config = {
        "schema_version": "problem-domain-smoke-config/v1",
        "batch_id": args.batch_id,
        "case_ids": [item.problem_id for item in cases],
        "samples_per_case": args.samples_per_case,
        "max_attempts": args.max_attempts,
        "concurrency": args.concurrency,
        "provider": args.provider,
        "model": provider_model,
        "source_input_mode": (
            "full_question_image" if args.provider == "doubao" else "trusted_ocr_text"
        ),
        "request_timeout_seconds": args.request_timeout_seconds,
        "thinking_policy": {
            "pass1": {"type": MULTIMODAL_PASS1_THINKING_MODE},
            "semantic_retry": {
                "type": MULTIMODAL_RETRY_THINKING_MODE,
                "reasoning_effort": MULTIMODAL_RETRY_REASONING_EFFORT,
            },
        },
        "response_formats": ["problem-domain/v1", "problem-repair/v1"],
        "transport_response_format": (
            "json_schema" if args.provider == "doubao" else "json_object"
        ),
        "temperature": 0,
        "max_output_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
        "prompt_hash": stable_hash(
            {
                "pass1_system": PASS1_SYSTEM_PROMPT,
                "repair_system": REPAIR_SYSTEM_PROMPT,
                "domain_schema": problem_domain_provider_schema(),
                "repair_schema": problem_repair_provider_schema(),
                "family_catalog": problem_domain_family_catalog(),
            }
        ),
        "f2_input_dir": str(f2_root),
        "planner_call_count": 0,
        "solver_call_count": 0,
    }
    _write_json(batch_dir / "batch-config.json", batch_config)

    jobs = [
        (case, sample_index)
        for case in cases
        for sample_index in range(1, args.samples_per_case + 1)
    ]
    results: list[ProblemDomainSmokeSampleResult] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                _run_sample,
                case,
                sample_index,
                batch_dir=batch_dir,
                f2_root=f2_root,
                config=config,
                max_attempts=args.max_attempts,
                provider_name=args.provider,
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
                item = ProblemDomainSmokeSampleResult(
                    problem_id=problem_id,
                    sample_index=sample_index,
                    accepted=False,
                    attempt_count=0,
                    final_issue_code=None,
                    provider=args.provider,
                    source_input_complete=False,
                    full_question_image_input=False,
                    retry_patch_only=False,
                    family_ok=False,
                    domain_semantic_diff_ok=False,
                    solver_projection_diff_ok=False,
                    usage={},
                    failures=(f"unclassified:{exc.__class__.__name__}:{exc}",),
                    sample_dir=str(sample_dir),
                )
                _write_json(sample_dir / "sample-result.json", item.to_payload())
            results.append(item)
            print(
                f"{problem_id}/sample-{sample_index:02d}: "
                f"ok={item.ok} attempts={item.attempt_count}"
            )

    summary = _batch_summary(batch_config, results)
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
    max_attempts: int,
    provider_name: str,
    request_timeout: float,
) -> ProblemDomainSmokeSampleResult:
    sample_dir = batch_dir / case.problem_id / f"sample-{sample_index:02d}"
    sample_dir.mkdir(parents=True, exist_ok=True)
    parent, context = _load_f2_context(case, f2_root)
    input_store = ExtractionArtifactStore(f2_root / "artifacts")
    output_store = ExtractionArtifactStore(sample_dir / "artifacts")
    provider = (
        DoubaoMultimodalExtractionProvider(
            api_key=config.doubao_api_key or "",
            base_url=config.doubao_base_url,
            model=config.doubao_model,
            request_timeout=request_timeout,
        )
        if provider_name == "doubao"
        else DeepSeekTextProblemDomainProvider(
            api_key=config.deepseek_api_key or "",
            base_url=config.deepseek_base_url,
            model=config.deepseek_model,
            request_timeout=request_timeout,
        )
    )
    run = ProblemDomainExtractionService(
        input_artifact_reader=input_store,
        output_artifact_store=output_store,
        provider=provider,
    ).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        max_attempts=max_attempts,
        ancestor_contexts=(parent,),
    )
    ProblemDomainDebugWriter().write(run, sample_dir)

    expected_draft = ProblemDraft.create(_load_domain_gold(case.problem_id))
    expected_validation = ProblemDomainValidator().validate(expected_draft)
    expected_projection = expected_validation.projection
    actual_graph = run.verified_problem.graph if run.verified_problem is not None else None
    domain_ok = bool(
        actual_graph is not None
        and actual_graph.semantic_hash == expected_draft.graph.semantic_hash
    )
    family_ok = bool(
        actual_graph is not None
        and actual_graph.family_id == expected_draft.graph.family_id
    )
    projection_ok = bool(
        run.solver_projection is not None
        and expected_projection is not None
        and compare_solver_projection_semantics(
            expected_projection.canonical_input,
            run.solver_projection.canonical_input,
        ).ok
    )
    full_image = bool(run.attempts) and all(
        any(image.role == "primary" for image in attempt.request.images)
        for attempt in run.attempts
    )
    text_only = bool(run.attempts) and all(
        not attempt.request.images for attempt in run.attempts
    )
    source_input_complete = full_image if provider_name == "doubao" else text_only
    retry_patch_only = _uses_patch_after_first_draft(run.attempts)
    final_issue = _final_issue(run)
    failures: list[str] = []
    if not run.accepted:
        failures.append(final_issue or "not_accepted")
    if not source_input_complete:
        failures.append("source_input_incomplete")
    if not retry_patch_only:
        failures.append("semantic_retry_not_patch")
    if not family_ok:
        failures.append("family_mismatch")
    if not domain_ok:
        failures.append("domain_semantic_diff")
    if not projection_ok:
        failures.append("solver_projection_diff")
    item = ProblemDomainSmokeSampleResult(
        problem_id=case.problem_id,
        sample_index=sample_index,
        accepted=run.accepted,
        attempt_count=len(run.attempts),
        final_issue_code=final_issue,
        provider=provider_name,
        source_input_complete=source_input_complete,
        full_question_image_input=full_image,
        retry_patch_only=retry_patch_only,
        family_ok=family_ok,
        domain_semantic_diff_ok=domain_ok,
        solver_projection_diff_ok=projection_ok,
        usage=_usage(run),
        failures=tuple(failures),
        sample_dir=str(sample_dir),
    )
    _write_json(sample_dir / "sample-result.json", item.to_payload())
    return item


def _uses_patch_after_first_draft(
    attempts: Sequence[ProblemDomainExtractionAttemptResult],
) -> bool:
    """Require patch retries only after a schema-valid Draft exists."""

    draft_exists = False
    for attempt in attempts:
        if draft_exists and (
            attempt.request.contract_version != "problem-repair/v1"
            or attempt.patch is None
        ):
            return False
        if attempt.resulting_draft is not None:
            draft_exists = True
    return True


def _load_f2_context(
    case: GoldCorpusCase,
    f2_root: Path,
) -> tuple[ProblemExtractionContext, ProblemExtractionContext]:
    path = f2_root / case.problem_id / "problem-extraction-context.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    _relocate_artifacts(payload, f2_root / "artifacts")
    parent = build_f0_extraction_context_seed(
        case,
        semantic_config=payload["dependency"]["semantic_config"],
        attempt_budget=int(payload["retry"]["attempt_budget"]),
    ).context
    context = ProblemExtractionContext.from_payload(payload, ancestor_contexts=(parent,))
    return parent, context


def _relocate_artifacts(payload: dict[str, Any], root: Path) -> None:
    for artifact in payload["state"]["artifacts"]:
        digest = str(artifact["sha256"])
        old = artifact.get("locator")
        suffix = Path(old).suffix if old else _artifact_suffix(artifact)
        target = root / digest[:2] / f"{digest}{suffix}"
        if not target.is_file():
            raise FileNotFoundError(target)
        artifact["locator"] = str(target.resolve())


def _artifact_suffix(artifact: Mapping[str, Any]) -> str:
    return ".json" if artifact.get("media_type") == "application/json" else ".png"


def _load_domain_gold(problem_id: str) -> Mapping[str, Any]:
    path = _repo_root() / "internal/problem-domain-fixtures" / f"{problem_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _final_issue(run: ProblemDomainExtractionRunResult) -> str | None:
    if not run.attempts:
        return run.blocked_reason
    issue = run.attempts[-1].report.first_issue
    return issue.code if issue is not None else run.blocked_reason


def _usage(run: ProblemDomainExtractionRunResult) -> dict[str, float]:
    totals: dict[str, float] = {}
    for attempt in run.attempts:
        response = attempt.provider_response
        if response is None or response.usage is None:
            continue
        for key, value in response.usage.items():
            if isinstance(value, (int, float)):
                totals[key] = totals.get(key, 0) + value
    return totals


def _batch_summary(
    config: Mapping[str, Any],
    results: Sequence[ProblemDomainSmokeSampleResult],
) -> dict[str, Any]:
    total = len(results)
    usage: dict[str, float] = {}
    for item in results:
        for key, value in item.usage.items():
            usage[key] = usage.get(key, 0) + value
    return {
        "schema_version": "problem-domain-smoke-summary/v1",
        "batch_id": config["batch_id"],
        "ok": total > 0 and all(item.ok for item in results),
        "sample_count": total,
        "passed_count": sum(item.ok for item in results),
        "accepted_count": sum(item.accepted for item in results),
        "source_input_complete_rate": (
            round(sum(item.source_input_complete for item in results) / total, 6)
            if total
            else 0.0
        ),
        "full_question_image_input_rate": (
            round(sum(item.full_question_image_input for item in results) / total, 6)
            if total
            else 0.0
        ),
        "semantic_retry_patch_output_rate": (
            round(sum(item.retry_patch_only for item in results) / total, 6)
            if total
            else 0.0
        ),
        "family_match_count": sum(item.family_ok for item in results),
        "domain_semantic_diff_zero_count": sum(
            item.domain_semantic_diff_ok for item in results
        ),
        "solver_projection_diff_zero_count": sum(
            item.solver_projection_diff_ok for item in results
        ),
        "configuration_error_count": sum(
            any("config" in value for value in item.failures) for item in results
        ),
        "unclassified_error_count": sum(
            any(value.startswith("unclassified:") for value in item.failures)
            for item in results
        ),
        "planner_call_count": 0,
        "solver_call_count": 0,
        "usage": usage,
        "cases": [
            item.to_payload()
            for item in sorted(
                results, key=lambda value: (value.problem_id, value.sample_index)
            )
        ],
        "review_index": "review.html",
    }


def _write_index(
    batch_dir: Path,
    results: Sequence[ProblemDomainSmokeSampleResult],
) -> None:
    links = "".join(
        f'<li><a href="{Path(item.sample_dir).relative_to(batch_dir).as_posix()}/review.html">'
        f"{item.problem_id}/sample-{item.sample_index:02d}</a> · "
        f"{'PASS' if item.ok else 'FAIL'}</li>"
        for item in sorted(
            results, key=lambda value: (value.problem_id, value.sample_index)
        )
    )
    (batch_dir / "review.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Problem domain review</title>'
        '<style>body{font:15px system-ui;max-width:900px;margin:32px auto;line-height:1.6}</style>'
        "<h1>Problem 领域提取审查</h1><ul>" + links + "</ul>",
        encoding="utf-8",
    )


def _selected_cases(
    cases: Sequence[GoldCorpusCase],
    selection: str,
    parser: argparse.ArgumentParser,
) -> tuple[GoldCorpusCase, ...]:
    requested = (
        {item.problem_id for item in cases}
        if selection == "all"
        else {item.strip() for item in selection.split(",") if item.strip()}
    )
    selected = tuple(item for item in cases if item.problem_id in requested)
    missing = requested - {item.problem_id for item in selected}
    if missing or not selected:
        parser.error(f"unknown or empty case selection: {sorted(missing or requested)}")
    return selected


def _resolve_repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return (repo_root / path if not path.is_absolute() else path).resolve()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
