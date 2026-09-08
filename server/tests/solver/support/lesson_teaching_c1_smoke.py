"""F5-F5C1 test-only Lesson LLM smoke and review harness.

The harness reuses the B2 projection and B3 Scope Lesson service verbatim.  It
adds only multi-case orchestration, test-only case metadata and rubrics,
aggregate metrics and a human-review index; it never injects rubric content
into a provider request or ships the case catalog in the runtime package.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
import math
import os
from pathlib import Path
from statistics import median
import tempfile
from time import perf_counter
from typing import Any, Callable, Literal, Mapping, Sequence

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    build_projection_audit,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_authoring_support import (
    DEFAULT_OUTPUT_ROOT,
    build_recorded_snapshot,
    load_teaching_rubric,
)
from shuxueshuo_server.solver.lesson_scope_content_smoke import (
    run_scope_lesson_batch,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    LLMPlannerClient,
)


C1_BATCH_CONFIG_CONTRACT = "lesson-teaching-c1-config/v1"
C1_BATCH_SUMMARY_CONTRACT = "lesson-teaching-c1-summary/v1"
C1_REVIEW_CONTRACT = "lesson-teaching-c1-review/v1"
C1_CASE_IDS = (
    "tj-2026-heping-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-nankai-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-xiqing-yimo-25",
)
C1_CASE_LABELS = {
    "tj-2026-heping-yimo-25": "等长射线路径 · 和平一模",
    "tj-2026-heping-ermo-25": "正方形反射路径 · 和平二模",
    "tj-2026-nankai-yimo-25": "耦合端点路径 · 南开一模",
    "tj-2026-hexi-yimo-25": "加权轴路径 · 河西一模",
    "tj-2026-xiqing-yimo-25": "加权轴路径 · 西青一模",
}
C1_RUBRIC_ROOT = Path(
    "server/tests/solver/fixtures/lesson_scope_authoring_vnext/five_case_c1/rubrics"
)

SmokeMode = Literal["recorded", "live"]


class LessonTeachingC1SmokeError(RuntimeError):
    """The five-case C1 batch cannot be generated atomically."""


@dataclass(frozen=True)
class LessonTeachingC1Case:
    problem_id: str
    snapshot: ExplanationSnapshot
    rubric: Mapping[str, Any]
    prompt_hash: str


def scope_lesson_prompt_hash(snapshot: ExplanationSnapshot) -> str:
    """Build the exact provider prompt hash using the production B2 builder."""

    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    if projection.diagnostics:
        raise LessonTeachingC1SmokeError(
            "lesson_teaching_c1_projection_diagnostic: "
            f"{snapshot.problem_id}:"
            f"{[item.code for item in projection.diagnostics]}"
        )
    output_schema = lesson_scope_content_schema(projection.plan)
    prompt = render_annotated_teaching_prompt(
        projection.plan,
        authority=projection.authority,
        output_schema=output_schema,
    )
    audit = build_projection_audit(
        projection,
        prompt=prompt,
        output_schema=output_schema,
    )
    return str(audit["hashes"]["prompt"])


def build_c1_cases(
    *,
    root: Path,
    authority_root: Path,
    case_ids: Sequence[str] = C1_CASE_IDS,
) -> tuple[LessonTeachingC1Case, ...]:
    """Rebuild recorded verified Snapshots and pair them with test-only rubrics."""

    unknown = sorted(set(case_ids) - set(C1_CASE_IDS))
    if unknown:
        raise LessonTeachingC1SmokeError(
            f"lesson_teaching_c1_unknown_cases: {unknown}"
        )
    cases: list[LessonTeachingC1Case] = []
    for problem_id in case_ids:
        snapshot = build_recorded_snapshot(
            problem_id,
            authority_dir=authority_root / problem_id,
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
        rubric_path = root / C1_RUBRIC_ROOT / f"{problem_id}.json"
        rubric = load_teaching_rubric(rubric_path)
        if rubric["problem_id"] != problem_id:
            raise LessonTeachingC1SmokeError(
                "lesson_teaching_c1_rubric_problem_mismatch: "
                f"{problem_id}:{rubric['problem_id']}"
            )
        cases.append(
            LessonTeachingC1Case(
                problem_id=problem_id,
                snapshot=snapshot,
                rubric=rubric,
                prompt_hash=scope_lesson_prompt_hash(snapshot),
            )
        )
    return tuple(cases)


def run_teaching_c1_batch(
    cases: Sequence[LessonTeachingC1Case],
    *,
    mode: SmokeMode,
    batch_dir: Path,
    samples_per_case: int,
    concurrency: int,
    max_transport_attempts: int,
    thinking_effort: Literal["disabled", "low"] = "disabled",
    client_factory: Callable[[str, str], LLMPlannerClient] | None = None,
    batch_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every case with one shared concurrency budget and aggregate results."""

    if not cases:
        raise LessonTeachingC1SmokeError("lesson_teaching_c1_cases_empty")
    if min(samples_per_case, concurrency, max_transport_attempts) < 1:
        raise LessonTeachingC1SmokeError(
            "lesson_teaching_c1_configuration_invalid: counts must be positive"
        )
    problem_ids = [item.problem_id for item in cases]
    if len(problem_ids) != len(set(problem_ids)):
        raise LessonTeachingC1SmokeError(
            "lesson_teaching_c1_duplicate_problem_id"
        )
    if batch_dir.exists():
        raise LessonTeachingC1SmokeError(
            f"lesson_teaching_c1_output_exists: {batch_dir}"
        )
    batch_dir.mkdir(parents=True)
    _write_json(batch_dir / "batch-config.json", dict(batch_config or {}))

    outer_workers = min(len(cases), concurrency)
    per_case_concurrency = min(
        samples_per_case,
        max(1, concurrency // outer_workers),
    )
    started = perf_counter()
    summaries: dict[str, Mapping[str, Any]] = {}
    failures: list[dict[str, Any]] = []

    def run_case(case: LessonTeachingC1Case) -> Mapping[str, Any]:
        scoped_client_factory: Callable[[str], LLMPlannerClient] | None = None
        if mode == "live":
            if client_factory is None:
                raise LessonTeachingC1SmokeError(
                    "lesson_teaching_c1_live_client_missing"
                )

            def scoped_client_factory(sample_id: str) -> LLMPlannerClient:
                return client_factory(case.problem_id, sample_id)

        return run_scope_lesson_batch(
            case.snapshot,
            case.rubric,
            mode=mode,
            batch_dir=batch_dir / "cases" / case.problem_id,
            samples_per_case=samples_per_case,
            concurrency=per_case_concurrency,
            max_transport_attempts=max_transport_attempts,
            thinking_effort=thinking_effort,
            reviewed_prompt_hash=case.prompt_hash,
            client_factory=scoped_client_factory,
            batch_config={
                "schema_version": C1_BATCH_CONFIG_CONTRACT,
                "problem_id": case.problem_id,
                "samples_per_case": samples_per_case,
                "concurrency": per_case_concurrency,
                "thinking": thinking_effort,
                "prompt_hash": case.prompt_hash,
                "rubric_is_evaluation_only": True,
            },
        )

    with ThreadPoolExecutor(max_workers=outer_workers) as pool:
        futures = {pool.submit(run_case, case): case for case in cases}
        for future in as_completed(futures):
            case = futures[future]
            try:
                summaries[case.problem_id] = future.result()
            except Exception as exc:
                failure = {
                    "problem_id": case.problem_id,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
                failures.append(failure)
                target = batch_dir / "cases" / case.problem_id
                target.mkdir(parents=True, exist_ok=True)
                _write_json(target / "case-failure.json", failure)

    ordered_summaries = [
        summaries[case.problem_id]
        for case in cases
        if case.problem_id in summaries
    ]
    summary = _aggregate_summary(
        cases=cases,
        case_summaries=ordered_summaries,
        failures=failures,
        mode=mode,
        samples_per_case=samples_per_case,
        concurrency=concurrency,
        thinking_effort=thinking_effort,
        wall_seconds=round(perf_counter() - started, 6),
    )
    review = {
        "schema_version": C1_REVIEW_CONTRACT,
        "status": summary["review_status"],
        "summary": summary,
        "cases": [
            {
                "problem_id": item["problem_id"],
                "label": C1_CASE_LABELS[item["problem_id"]],
                "summary": item,
                "review_path": f"cases/{item['problem_id']}/review.html",
            }
            for item in ordered_summaries
        ],
        "failures": failures,
    }
    _write_json(batch_dir / "batch-summary.json", summary)
    _write_json(batch_dir / "review.json", review)
    _write_text(batch_dir / "review.html", render_teaching_c1_review_html(review))
    return summary


def _aggregate_summary(
    *,
    cases: Sequence[LessonTeachingC1Case],
    case_summaries: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    mode: SmokeMode,
    samples_per_case: int,
    concurrency: int,
    thinking_effort: Literal["disabled", "low"],
    wall_seconds: float,
) -> dict[str, Any]:
    expected_samples = len(cases) * samples_per_case
    samples = [
        sample
        for summary in case_summaries
        for sample in summary.get("samples", [])
    ]
    usage = {
        key: sum(
            int(summary.get("usage", {}).get(key) or 0)
            for summary in case_summaries
        )
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    provider_latencies = [
        float(sample["provider_duration_seconds"])
        for sample in samples
        if isinstance(sample.get("provider_duration_seconds"), (int, float))
    ]
    total_latencies = [
        float(sample["duration_seconds"])
        for sample in samples
        if isinstance(sample.get("duration_seconds"), (int, float))
    ]
    histogram: dict[str, int] = {}
    for sample in samples:
        for count, occurrences in sample.get(
            "source_step_count_histogram", {}
        ).items():
            histogram[str(count)] = histogram.get(str(count), 0) + int(
                occurrences
            )
    automated_gate_ok = bool(
        len(case_summaries) == len(cases)
        and not failures
        and len(samples) == expected_samples
        and all(bool(item.get("automated_gate_ok")) for item in case_summaries)
    )
    return {
        "schema_version": C1_BATCH_SUMMARY_CONTRACT,
        "mode": mode,
        "case_count": len(cases),
        "case_ids": [item.problem_id for item in cases],
        "samples_per_case": samples_per_case,
        "sample_count": expected_samples,
        "completed_sample_count": len(samples),
        "concurrency": concurrency,
        "thinking": thinking_effort,
        "semantic_attempt_count": sum(
            int(item.get("semantic_attempt_count") or 0)
            for item in case_summaries
        ),
        "transport_request_count": sum(
            int(item.get("transport_request_count") or 0)
            for item in case_summaries
        ),
        "automated_gate_ok": automated_gate_ok,
        "direct_acceptance_count": sum(
            bool(sample.get("direct_acceptance")) for sample in samples
        ),
        "contract_pass_count": sum(
            bool(sample.get("contract_pass")) for sample in samples
        ),
        "authority_pass_count": sum(
            bool(sample.get("authority_pass")) for sample in samples
        ),
        "rubric_full_coverage_count": sum(
            float(sample.get("teaching_coverage_rate") or 0.0) == 1.0
            for sample in samples
        ),
        "fallback_count": sum(
            bool(sample.get("fallback_used")) for sample in samples
        ),
        "syntax_repair_count": sum(
            bool(sample.get("syntax_repaired")) for sample in samples
        ),
        "source_step_completion_repair_count": sum(
            bool(sample.get("source_step_completion_repaired"))
            for sample in samples
        ),
        "independent_material_merge_repair_count": sum(
            bool(sample.get("independent_material_merge_repaired"))
            for sample in samples
        ),
        "unclassified_failure_count": len(failures)
        + sum(
            int(item.get("unclassified_failure_count") or 0)
            for item in case_summaries
        ),
        "source_step_count_histogram": histogram,
        "usage": usage,
        "latency": {
            "provider_sum_seconds": round(sum(provider_latencies), 6),
            "provider_p50_seconds": _percentile(provider_latencies, 0.50),
            "provider_p95_seconds": _percentile(provider_latencies, 0.95),
            "sample_sum_seconds": round(sum(total_latencies), 6),
            "sample_p50_seconds": _percentile(total_latencies, 0.50),
            "sample_p95_seconds": _percentile(total_latencies, 0.95),
            "batch_wall_seconds": wall_seconds,
        },
        "prompt_hashes": {
            item.problem_id: item.prompt_hash for item in cases
        },
        "case_summaries": [dict(item) for item in case_summaries],
        "failures": [dict(item) for item in failures],
        "review_status": (
            "awaiting_human_review"
            if automated_gate_ok
            else "requires_failure_analysis"
        ),
        "human_review_approved": False,
    }


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    if quantile == 0.5:
        return round(float(median(values)), 6)
    ordered = sorted(values)
    position = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(float(ordered[position]), 6)


def render_teaching_c1_review_html(review: Mapping[str, Any]) -> str:
    summary = review["summary"]
    case_cards = "".join(
        _render_case_card(item) for item in review["cases"]
    )
    failures = ""
    if review["failures"]:
        failures = (
            '<section class="failures"><h2>Case failures</h2><pre>'
            + _json_text(review["failures"])
            + "</pre></section>"
        )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5C1 五题 Teaching-only Review</title>
<style>
:root{{--bg:#f1eee8;--paper:#fffdf9;--ink:#172033;--muted:#667085;--line:#d6cec0;--nav:#172033;--good:#047857;--bad:#b42318}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,system-ui,-apple-system,"PingFang SC",sans-serif}}
header{{position:sticky;top:0;z-index:3;background:var(--nav);color:white;padding:16px 22px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
header h1{{font-size:20px;margin:0 14px 0 0}}.stat{{border:1px solid #ffffff35;background:#ffffff12;border-radius:9px;padding:6px 9px}}
main{{max-width:1500px;margin:0 auto;padding:22px}}.case{{background:var(--paper);border:1px solid var(--line);border-radius:14px;margin-bottom:18px;padding:16px}}
.case h2{{margin:0 0 4px}}.case-id{{color:var(--muted)}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px;margin:14px 0}}
.metric{{background:#f7f5f0;border-radius:9px;padding:9px}}.metric strong{{display:block;font-size:18px}}table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;border-top:1px solid var(--line);padding:8px;vertical-align:top}}a.open{{display:inline-block;background:var(--nav);color:white;text-decoration:none;border-radius:8px;padding:8px 12px;margin-top:12px}}
.good{{color:var(--good)}}.bad{{color:var(--bad)}}pre{{white-space:pre-wrap;word-break:break-word;background:#f7f5f0;padding:10px;border-radius:8px}}
@media(max-width:720px){{header{{position:static}}main{{padding:12px}}table{{display:block;overflow:auto}}}}
</style></head><body>
<header><h1>F5-F5C1 五题 Teaching-only Review</h1>
<div class="stat">自动门禁 {summary['direct_acceptance_count']}/{summary['sample_count']}</div>
<div class="stat">Rubric 完整 {summary['rubric_full_coverage_count']}/{summary['sample_count']}</div>
<div class="stat">Fallback {summary['fallback_count']}</div>
<div class="stat">Tokens {summary['usage']['total_tokens']}</div>
<div class="stat">Wall {summary['latency']['batch_wall_seconds']}s</div></header>
<main>{case_cards}{failures}<section><h2>Aggregate JSON</h2><pre>{_json_text(summary)}</pre></section></main>
</body></html>"""


def _render_case_card(item: Mapping[str, Any]) -> str:
    summary = item["summary"]
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(sample['sample_id']))}</td>"
        f"<td>{'✓' if sample['direct_acceptance'] else '✗'}</td>"
        f"<td>{escape(str(sample['lesson_step_count']))}</td>"
        f"<td>{escape(str(sample['source_step_count_histogram']))}</td>"
        f"<td>{escape(str(sample['teaching_coverage_rate']))}</td>"
        f"<td>{escape(str(sample['usage'].get('total_tokens')))}</td>"
        f"<td>{escape(str(sample['provider_duration_seconds']))}s</td>"
        f"<td>{escape(', '.join(sample['missing_teaching_points']) or '—')}</td>"
        "</tr>"
        for sample in summary.get("samples", [])
    )
    return (
        f'<section class="case" id="{escape(str(item["problem_id"]))}">'
        f'<h2>{escape(str(item["label"]))}</h2>'
        f'<div class="case-id">{escape(str(item["problem_id"]))}</div>'
        '<div class="metrics">'
        f'<div class="metric"><strong>{summary["direct_acceptance_count"]}/'
        f'{summary["sample_count"]}</strong>直接接受</div>'
        f'<div class="metric"><strong>{summary["rubric_full_coverage_count"]}/'
        f'{summary["sample_count"]}</strong>Rubric 完整</div>'
        f'<div class="metric"><strong>{summary["fallback_count"]}</strong>Fallback</div>'
        f'<div class="metric"><strong>{summary["usage"]["total_tokens"]}</strong>Tokens</div>'
        "</div>"
        '<table><thead><tr><th>Sample</th><th>Direct</th><th>Steps</th>'
        '<th>合并分布</th><th>Coverage</th><th>Tokens</th><th>Provider</th>'
        f'<th>Missing</th></tr></thead><tbody>{rows}</tbody></table>'
        f'<a class="open" href="{escape(str(item["review_path"]))}">'
        "打开三份正文横向 Review →</a></section>"
    )


def _json_text(value: Any) -> str:
    return escape(json.dumps(value, ensure_ascii=False, indent=2))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("recorded", "live"), required=True)
    parser.add_argument(
        "--case",
        choices=("all", *C1_CASE_IDS),
        default="all",
    )
    parser.add_argument("--samples-per-case", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=15)
    parser.add_argument("--max-transport-attempts", type=int, default=2)
    parser.add_argument(
        "--thinking",
        choices=("disabled", "low"),
        default="disabled",
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if min(
        args.samples_per_case,
        args.concurrency,
        args.max_transport_attempts,
    ) < 1:
        parser.error("sample, concurrency and transport counts must be positive")
    if args.mode == "live" and os.environ.get("RUN_LLM_INTEGRATION") != "1":
        parser.error("live C1 smoke requires RUN_LLM_INTEGRATION=1")

    root = _repo_root()
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    if output_dir.exists():
        parser.error(f"batch output already exists: {output_dir}")
    case_ids = C1_CASE_IDS if args.case == "all" else (args.case,)
    with tempfile.TemporaryDirectory(prefix="lesson-c1-authority-") as temp_dir:
        cases = build_c1_cases(
            root=root,
            authority_root=Path(temp_dir),
            case_ids=case_ids,
        )

    batch_config: dict[str, Any] = {
        "schema_version": C1_BATCH_CONFIG_CONTRACT,
        "batch_id": args.batch_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": args.mode,
        "case_ids": list(case_ids),
        "samples_per_case": args.samples_per_case,
        "concurrency": args.concurrency,
        "max_transport_attempts": args.max_transport_attempts,
        "semantic_attempts": 1,
        "thinking": args.thinking,
        "same_problem_few_shot": False,
        "rubric_is_evaluation_only": True,
        "prompt_hashes": {item.problem_id: item.prompt_hash for item in cases},
        "output_dir": str(output_dir),
    }
    if args.dry_run:
        print(json.dumps(batch_config, ensure_ascii=False, indent=2))
        return 0

    client_factory: Callable[[str, str], LLMPlannerClient] | None = None
    if args.mode == "live":
        config = SolverRuntimeConfig.from_sources(
            planner_mode="strategy",
            llm_provider="deepseek",
            env_file=root / "server/.env",
        )
        if not config.deepseek_api_key:
            parser.error("DEEPSEEK_API_KEY is required for live C1 smoke")
        batch_config.update(
            {
                "provider": "deepseek",
                "model": config.llm_model or config.deepseek_model,
                "sdk_max_retries": 0,
                "reasoning_only_empty_response_retry": False,
            }
        )

        def client_factory(_problem_id: str, _sample_id: str) -> LLMPlannerClient:
            return DeepSeekPlannerClient(
                api_key=str(config.deepseek_api_key),
                base_url=config.deepseek_base_url,
                model=config.llm_model or config.deepseek_model,
                sdk_max_retries=0,
                reasoning_only_empty_response_retry=False,
            )
    else:
        batch_config.update({"provider": "recorded", "model": None})

    summary = run_teaching_c1_batch(
        cases,
        mode=args.mode,
        batch_dir=output_dir,
        samples_per_case=args.samples_per_case,
        concurrency=args.concurrency,
        max_transport_attempts=args.max_transport_attempts,
        thinking_effort=args.thinking,
        client_factory=client_factory,
        batch_config=batch_config,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["automated_gate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "C1_BATCH_CONFIG_CONTRACT",
    "C1_BATCH_SUMMARY_CONTRACT",
    "C1_CASE_IDS",
    "C1_REVIEW_CONTRACT",
    "LessonTeachingC1Case",
    "LessonTeachingC1SmokeError",
    "build_c1_cases",
    "main",
    "render_teaching_c1_review_html",
    "run_teaching_c1_batch",
    "scope_lesson_prompt_hash",
]
