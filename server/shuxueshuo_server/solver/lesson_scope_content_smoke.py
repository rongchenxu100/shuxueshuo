"""F5-F5B3 recorded/live Scope Lesson generation and review harness."""

from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import tempfile
from time import perf_counter
from typing import Any, Callable, Literal, Mapping, Sequence

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlan,
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
    ScopeLessonAuthoringService,
    ScopeLessonGenerationResult,
    evaluate_scope_lesson_content,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import (
    CASE_ID,
    DEFAULT_OUTPUT_ROOT,
    build_recorded_snapshot,
    load_teaching_rubric,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from shuxueshuo_server.solver.runtime.llm_clients import (
    DeepSeekPlannerClient,
    LLMPlannerClient,
)


BATCH_CONFIG_CONTRACT = "lesson-scope-smoke-config/v1"
SAMPLE_RESULT_CONTRACT = "lesson-scope-smoke-sample/v1"
BATCH_SUMMARY_CONTRACT = "lesson-scope-smoke-summary/v1"
REVIEW_CONTRACT = "lesson-scope-output-review/v1"

SmokeMode = Literal["recorded", "live"]


class LessonScopeSmokeError(RuntimeError):
    """The B3 harness cannot produce a complete auditable sample."""


@dataclass(frozen=True)
class ScopeLessonSmokeSample:
    sample_id: str
    generation: ScopeLessonGenerationResult
    evaluation: Mapping[str, Any]
    result: Mapping[str, Any]


class _RecordedScopeLessonClient:
    provider_name = "recorded"
    model = "recorded-scope-lesson"
    last_response_model = "recorded-scope-lesson"
    last_provider_attempts: tuple[Mapping[str, Any], ...] = ()

    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = json.dumps(response, ensure_ascii=False)
        self.calls: list[Mapping[str, Any]] = []
        self.last_usage: dict[str, int] = {}

    def complete(self, payload: dict[str, Any]) -> str:
        self.calls.append(copy.deepcopy(payload))
        return self.response


def run_scope_lesson_batch(
    snapshot: ExplanationSnapshot,
    rubric: Mapping[str, Any],
    *,
    mode: SmokeMode,
    batch_dir: Path,
    samples_per_case: int,
    concurrency: int,
    max_transport_attempts: int,
    thinking_effort: Literal["disabled", "low"] = "disabled",
    reviewed_prompt_hash: str,
    client_factory: Callable[[str], LLMPlannerClient] | None = None,
    batch_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if min(samples_per_case, concurrency, max_transport_attempts) < 1:
        raise LessonScopeSmokeError(
            "lesson_scope_smoke_configuration_invalid: counts must be positive"
        )
    if batch_dir.exists():
        raise LessonScopeSmokeError(
            f"lesson_scope_smoke_output_exists: {batch_dir}"
        )
    batch_dir.mkdir(parents=True)
    _write_json(batch_dir / "batch-config.json", dict(batch_config or {}))

    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    recorded_content = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    ).deterministic_fallback

    def make_client(sample_id: str) -> LLMPlannerClient:
        if mode == "recorded":
            return _RecordedScopeLessonClient(recorded_content)
        if client_factory is None:
            raise LessonScopeSmokeError(
                "lesson_scope_live_client_missing: live mode requires client factory"
            )
        return client_factory(sample_id)

    sample_ids = [
        f"sample-{index:02d}" for index in range(1, samples_per_case + 1)
    ]
    runs: list[ScopeLessonSmokeSample] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=min(concurrency, samples_per_case)
    ) as pool:
        futures = {
            pool.submit(
                _run_sample,
                snapshot,
                rubric,
                sample_id=sample_id,
                sample_dir=batch_dir / sample_id,
                client=make_client(sample_id),
                max_transport_attempts=max_transport_attempts,
                thinking_effort=thinking_effort,
                reviewed_prompt_hash=reviewed_prompt_hash,
            ): sample_id
            for sample_id in sample_ids
        }
        for future in as_completed(futures):
            sample_id = futures[future]
            try:
                runs.append(future.result())
            except Exception as exc:
                failures.append(
                    _write_unclassified_failure(
                        batch_dir / sample_id,
                        sample_id=sample_id,
                        error=exc,
                    )
                )
    runs.sort(key=lambda item: item.sample_id)
    failures.sort(key=lambda item: str(item["sample_id"]))

    summary = _batch_summary(
        mode=mode,
        runs=runs,
        failures=failures,
        expected_samples=samples_per_case,
    )
    review = build_scope_lesson_review(
        projection.plan,
        runs=runs,
        failures=failures,
        summary=summary,
    )
    _write_json(batch_dir / "batch-summary.json", summary)
    _write_json(batch_dir / "review.json", review)
    _write_text(
        batch_dir / "review.html",
        render_scope_lesson_review_html(review),
    )
    return summary


def _run_sample(
    snapshot: ExplanationSnapshot,
    rubric: Mapping[str, Any],
    *,
    sample_id: str,
    sample_dir: Path,
    client: LLMPlannerClient,
    max_transport_attempts: int,
    thinking_effort: Literal["disabled", "low"],
    reviewed_prompt_hash: str,
) -> ScopeLessonSmokeSample:
    started = perf_counter()
    sample_dir.mkdir(parents=True, exist_ok=False)
    generation = ScopeLessonAuthoringService(
        client=client,
        max_transport_attempts=max_transport_attempts,
        thinking_effort=thinking_effort,
        reviewed_prompt_hash=reviewed_prompt_hash,
    ).generate(snapshot)
    evaluation = evaluate_scope_lesson_content(
        generation.validation,
        problem_id=snapshot.problem_id,
        rubric=rubric,
    )
    _write_sample_artifacts(
        sample_dir,
        snapshot=snapshot,
        generation=generation,
        evaluation=evaluation,
    )
    duration = round(perf_counter() - started, 6)
    bound_steps = [
        step
        for items in generation.validation.bound_steps.values()
        for step in items
    ]
    histogram: dict[str, int] = {}
    for step in bound_steps:
        key = str(step.material_count)
        histogram[key] = histogram.get(key, 0) + 1
    automated_gate = bool(
        generation.validation.direct_acceptance
        and evaluation["contract"]["pass"]
        and evaluation["authority"]["pass"]
        and evaluation["teaching_quality"]["coverage_rate"] == 1.0
    )
    metadata = generation.metadata_payload()
    result = {
        "schema_version": SAMPLE_RESULT_CONTRACT,
        "problem_id": snapshot.problem_id,
        "sample_id": sample_id,
        "completion_ok": automated_gate,
        "direct_acceptance": generation.validation.direct_acceptance,
        "contract_pass": evaluation["contract"]["pass"],
        "authority_pass": evaluation["authority"]["pass"],
        "fallback_used": generation.validation.fallback_used,
        "syntax_repaired": generation.validation.syntax_repaired,
        "source_step_completion_repaired": (
            generation.validation.source_step_completion_repaired
        ),
        "appended_suffix": generation.validation.appended_suffix,
        "scope_sources": dict(generation.validation.scope_sources),
        "semantic_attempt_count": generation.semantic_attempt_count,
        "transport_request_count": len(generation.transport_attempts),
        "provider_response_received": bool(generation.raw_response.strip()),
        "usage": generation.usage,
        "provider_duration_seconds": metadata["provider_duration_seconds"],
        "duration_seconds": duration,
        "scope_count": len(generation.validation.scope_sources),
        "lesson_step_count": len(bound_steps),
        "source_step_count_histogram": histogram,
        "teaching_coverage_rate": evaluation["teaching_quality"][
            "coverage_rate"
        ],
        "covered_teaching_points": evaluation["teaching_quality"][
            "required_points"
        ]["covered"],
        "missing_teaching_points": evaluation["teaching_quality"][
            "required_points"
        ]["missing"],
        "unexpected_objects": evaluation["authority"]["unexpected_objects"],
        "prompt_hash": generation.projection_audit["hashes"]["prompt"],
        "prompt_chars": dict(generation.projection_audit["prompt_chars"]),
        "human_review_status": "awaiting_human_review",
        "sample_dir": str(sample_dir),
    }
    _write_json(sample_dir / "sample-result.json", result)
    return ScopeLessonSmokeSample(
        sample_id=sample_id,
        generation=generation,
        evaluation=evaluation,
        result=result,
    )


def _write_sample_artifacts(
    sample_dir: Path,
    *,
    snapshot: ExplanationSnapshot,
    generation: ScopeLessonGenerationResult,
    evaluation: Mapping[str, Any],
) -> None:
    _write_json(sample_dir / "snapshot.json", snapshot.to_payload())
    _write_json(
        sample_dir / "teaching-authority.json",
        generation.projection.authority,
    )
    _write_json(
        sample_dir / "annotated-teaching-plan.json",
        generation.projection.plan.to_payload(),
    )
    _write_json(sample_dir / "output-schema.json", generation.output_schema)
    _write_text(
        sample_dir / "prompt.system.md",
        generation.prompt.system + "\n",
    )
    _write_text(
        sample_dir / "prompt.user.md",
        generation.prompt.user + "\n",
    )
    _write_json(
        sample_dir / "projection-audit.json",
        generation.projection_audit,
    )
    for attempt in generation.transport_attempts:
        prefix = f"transport-attempt-{attempt.transport_attempt:02d}"
        _write_text(
            sample_dir / f"{prefix}.raw-response.txt",
            attempt.raw_response,
        )
        _write_json(
            sample_dir / f"{prefix}.metadata.json",
            attempt.to_payload(),
        )
        _write_json(
            sample_dir / attempt.reasoning_debug_filename,
            attempt.reasoning_debug_payload(),
        )
    _write_text(sample_dir / "raw-response.txt", generation.raw_response)
    if generation.validation.repaired_response is not None:
        _write_text(
            sample_dir / "syntax-repaired-response.txt",
            generation.validation.repaired_response,
        )
    if generation.validation.parsed_response is not None:
        _write_json(
            sample_dir / "parsed-scope-content.json",
            generation.validation.parsed_response,
        )
    _write_json(
        sample_dir / "validation-diagnostics.json",
        generation.validation.to_payload(),
    )
    _write_json(
        sample_dir / "accepted-scope-content.json",
        generation.validation.accepted_content,
    )
    _write_json(
        sample_dir / "deterministic-fallback.json",
        generation.deterministic_fallback,
    )
    _write_json(sample_dir / "lesson-evaluation.json", evaluation)
    _write_json(sample_dir / "llm-metadata.json", generation.metadata_payload())


def _batch_summary(
    *,
    mode: SmokeMode,
    runs: Sequence[ScopeLessonSmokeSample],
    failures: Sequence[Mapping[str, Any]],
    expected_samples: int,
) -> dict[str, Any]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for run in runs:
        for key in usage:
            value = run.result.get("usage", {}).get(key)
            if isinstance(value, int):
                usage[key] += value
    automated_passed = sum(
        bool(run.result["completion_ok"]) for run in runs
    )
    prompt_hashes = sorted(
        {str(run.result["prompt_hash"]) for run in runs}
    )
    return {
        "schema_version": BATCH_SUMMARY_CONTRACT,
        "mode": mode,
        "problem_id": CASE_ID,
        "sample_count": expected_samples,
        "completed_sample_count": len(runs),
        "unclassified_failure_count": len(failures),
        "automated_gate_passed": automated_passed,
        "automated_gate_ok": (
            len(runs) == expected_samples
            and not failures
            and automated_passed == expected_samples
        ),
        "direct_acceptance_count": sum(
            bool(run.result["direct_acceptance"]) for run in runs
        ),
        "contract_pass_count": sum(
            bool(run.result["contract_pass"]) for run in runs
        ),
        "authority_pass_count": sum(
            bool(run.result["authority_pass"]) for run in runs
        ),
        "rubric_5_of_5_count": sum(
            float(run.result["teaching_coverage_rate"]) == 1.0
            for run in runs
        ),
        "fallback_count": sum(
            bool(run.result["fallback_used"]) for run in runs
        ),
        "syntax_repair_count": sum(
            bool(run.result["syntax_repaired"]) for run in runs
        ),
        "source_step_completion_repair_count": sum(
            bool(run.result["source_step_completion_repaired"])
            for run in runs
        ),
        "semantic_attempt_count": sum(
            int(run.result["semantic_attempt_count"]) for run in runs
        ),
        "transport_request_count": sum(
            int(run.result["transport_request_count"]) for run in runs
        ),
        "usage": usage,
        "provider_duration_seconds": round(
            sum(
                float(run.result["provider_duration_seconds"])
                for run in runs
            ),
            6,
        ),
        "total_duration_seconds": round(
            sum(float(run.result["duration_seconds"]) for run in runs),
            6,
        ),
        "prompt_hashes": prompt_hashes,
        "review_status": (
            "awaiting_human_review"
            if len(runs) == expected_samples and not failures
            else "automated_gate_failed"
        ),
        "human_review_approved": False,
        "samples": [dict(run.result) for run in runs],
        "failures": [dict(item) for item in failures],
    }


def build_scope_lesson_review(
    plan: AnnotatedTeachingPlan,
    *,
    runs: Sequence[ScopeLessonSmokeSample],
    failures: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    samples = [
        {
            "sample_id": run.sample_id,
            "result": dict(run.result),
            "raw_response": run.generation.raw_response,
            "repaired_response": run.generation.validation.repaired_response,
            "parsed_response": _json_clone(
                run.generation.validation.parsed_response
            ),
            "accepted_content": _json_clone(
                run.generation.validation.accepted_content
            ),
            "validation": run.generation.validation.to_payload(),
            "evaluation": _json_clone(run.evaluation),
            "metadata": run.generation.metadata_payload(),
            "bound_steps": {
                key: [item.review_payload() for item in items]
                for key, items in run.generation.validation.bound_steps.items()
            },
        }
        for run in runs
    ]
    return {
        "schema_version": REVIEW_CONTRACT,
        "status": "awaiting_human_review",
        "summary": _json_clone(summary),
        "containers": _input_containers(plan),
        "samples": samples,
        "failures": [dict(item) for item in failures],
    }


def render_scope_lesson_review_html(review: Mapping[str, Any]) -> str:
    summary = review["summary"]
    samples = review["samples"]
    containers = review["containers"]
    nav = "".join(
        f'<a href="#{escape(_anchor(str(item["container_ref"])))}">'
        f'<span>{escape(str(item["label"]))}</span>'
        f'<small>{escape(str(item["container_ref"]))}</small></a>'
        for item in containers
    )
    comparisons = "".join(
        _render_container_comparison(container, samples)
        for container in containers
    )
    raw_panels = "".join(
        '<article class="raw-sample">'
        f'<h2>{escape(str(sample["sample_id"]))}</h2>'
        f'<pre>{escape(str(sample["raw_response"]))}</pre></article>'
        for sample in samples
    )
    audits = "".join(
        '<article class="raw-sample">'
        f'<h2>{escape(str(sample["sample_id"]))}</h2>'
        '<h3>Validation</h3>'
        f'<pre>{_json_text(sample["validation"])}</pre>'
        '<h3>Evaluation</h3>'
        f'<pre>{_json_text(sample["evaluation"])}</pre>'
        '</article>'
        for sample in samples
    )
    prompt_panel = ""
    if samples:
        prompt_panel = (
            '<h2>Prompt / authority hashes</h2>'
            f'<pre>{_json_text(samples[0]["metadata"].get("hashes", {}))}</pre>'
            '<p>实际 Prompt 文件保存在每个 sample 目录；三份必须具有同一 hash。</p>'
        )
    columns = len(samples) + 1
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5B3 Scope Lesson Output Review</title>
<style>
:root{{--bg:#f1eee8;--paper:#fffdf9;--ink:#172033;--muted:#667085;--line:#d6cec0;--nav:#172033;--good:#047857;--bad:#b42318;--warn:#b54708}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,system-ui,-apple-system,"PingFang SC",sans-serif}}
header{{position:sticky;top:0;z-index:8;background:var(--nav);color:white;padding:14px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
header h1{{font-size:19px;margin:0 12px 0 0}}.stat{{border:1px solid #ffffff35;background:#ffffff12;border-radius:9px;padding:6px 9px}}.tabs{{margin-left:auto;display:flex;gap:6px}}button{{border:1px solid #ffffff40;background:#ffffff12;color:white;border-radius:8px;padding:7px 9px;cursor:pointer}}button.active{{background:white;color:var(--nav)}}
.layout{{display:grid;grid-template-columns:250px minmax(0,1fr)}}aside{{position:sticky;top:70px;height:calc(100vh - 70px);overflow:auto;background:#e7e1d7;border-right:1px solid var(--line);padding:14px 10px}}aside a{{display:block;text-decoration:none;color:var(--ink);padding:7px 9px;border-radius:8px}}aside a:hover{{background:white}}aside span,aside small{{display:block}}aside small{{color:var(--muted)}}main{{padding:20px;min-width:0}}.panel[hidden]{{display:none}}
.container{{background:var(--paper);border:1px solid var(--line);border-radius:14px;margin-bottom:22px;overflow:hidden}}.container>h2{{margin:0;padding:14px 16px;border-bottom:1px solid var(--line);font-size:17px}}.compare{{display:grid;grid-template-columns:repeat({columns},minmax(330px,1fr));overflow-x:auto}}.column{{padding:14px;border-right:1px solid var(--line);min-width:330px}}.column:last-child{{border:0}}.column h3{{margin:0 0 9px;font-size:13px;color:var(--muted)}}
.material,.lesson-step{{border-left:3px solid #2563eb;padding:7px 10px;margin-bottom:13px;background:#f8fafc;border-radius:0 8px 8px 0}}.lesson-step{{border-color:var(--good)}}.lesson-step.fallback{{border-color:var(--bad)}}.badge{{display:inline-block;border-radius:999px;padding:2px 7px;font-size:11px;background:#ecfdf3;color:var(--good);margin:0 4px 5px 0}}.badge.bad{{background:#fef3f2;color:var(--bad)}}.badge.warn{{background:#fffaeb;color:var(--warn)}}h4{{margin:3px 0}}.nav-title{{color:var(--muted);font-size:12px}}ol{{padding-left:20px}}.box{{background:#ecfdf3;color:#065f46;border-radius:6px;padding:5px 7px;margin-top:5px}}pre{{white-space:pre-wrap;word-break:break-word;background:#f7f5f0;border:1px solid var(--line);border-radius:9px;padding:10px;font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}}.raw-sample{{max-width:1400px;margin:0 auto 20px}}
@media(max-width:900px){{header{{position:static}}.layout{{grid-template-columns:1fr}}aside{{position:static;height:auto}}.compare{{grid-template-columns:1fr}}.column{{border-right:0;border-bottom:1px solid var(--line)}}}}
</style></head><body>
<header><h1>F5-F5B3 Scope Lesson Output Review</h1>
<div class="stat">自动门禁 {summary['automated_gate_passed']}/{summary['sample_count']}</div>
<div class="stat">直接接受 {summary['direct_acceptance_count']}/{summary['sample_count']}</div>
<div class="stat">Rubric 5/5 × {summary['rubric_5_of_5_count']}</div>
<div class="stat">Fallback {summary['fallback_count']}</div>
<div class="stat">单步补齐 {summary['source_step_completion_repair_count']}</div>
<div class="stat">状态：等待人工审阅</div>
<div class="tabs"><button class="active" data-tab="compare">横向对比</button><button data-tab="raw">Raw</button><button data-tab="audit">校验/评测</button><button data-tab="metrics">指标</button><button data-tab="prompt">Prompt Hash</button></div></header>
<div class="layout"><aside>{nav}</aside><main>
<section class="panel" data-panel="compare">{comparisons}</section>
<section class="panel" data-panel="raw" hidden>{raw_panels}</section>
<section class="panel" data-panel="audit" hidden>{audits}</section>
<section class="panel" data-panel="metrics" hidden><pre>{_json_text(summary)}</pre></section>
<section class="panel" data-panel="prompt" hidden>{prompt_panel}</section>
</main></div>
<script>for(const b of document.querySelectorAll('[data-tab]')){{b.onclick=()=>{{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.tab)}}}}</script>
</body></html>"""


def _render_container_comparison(
    container: Mapping[str, Any],
    samples: Sequence[Mapping[str, Any]],
) -> str:
    ref = str(container["container_ref"])
    materials = "".join(
        _render_material(item, index=index)
        for index, item in enumerate(container["materials"])
    ) or "<p>无本地 teaching material</p>"
    columns = [
        '<section class="column"><h3>B2 输入材料</h3>'
        + materials
        + "</section>"
    ]
    for sample in samples:
        steps = sample["bound_steps"].get(ref, [])
        source = _scope_source_for_container(
            sample["result"]["scope_sources"],
            ref,
        )
        rendered = "".join(
            _render_bound_step(item, fallback=source != "llm")
            for item in steps
        ) or "<p>无输出步骤</p>"
        columns.append(
            '<section class="column">'
            f'<h3>{escape(str(sample["sample_id"]))} · '
            f'{"accepted" if source == "llm" else "fallback"}</h3>'
            + rendered
            + "</section>"
        )
    return (
        f'<article class="container" id="{escape(_anchor(ref))}">'
        f'<h2>{escape(str(container["label"]))} · {escape(ref)}</h2>'
        f'<div class="compare">{"".join(columns)}</div></article>'
    )


def _render_material(material: Mapping[str, Any], *, index: int) -> str:
    derive = "".join(
        f'<li>{escape(str(item))}</li>' for item in material["derive"]
    )
    boxes = "".join(
        f'<div class="box">{escape(str(item))}</div>'
        for item in material["conclusions"]
    )
    return (
        '<div class="material">'
        f'<div class="nav-title">{escape(str(material.get("step_ref") or f"s{index + 1}"))} · '
        f'{escape(str(material["nav_title"]))}</div>'
        f'<h4>{escape(str(material["title"]))}</h4>'
        f'<p>{escape(str(material["goal"]))}</p>'
        f'<ol>{derive}</ol>{boxes}</div>'
    )


def _render_bound_step(step: Mapping[str, Any], *, fallback: bool) -> str:
    derive = "".join(
        f'<li><strong>{escape(str(item[0]))}</strong> '
        f'{escape(str(item[1]))}</li>'
        for item in step["derive"]
    )
    boxes = "".join(
        f'<div class="box">{escape(str(item))}</div>'
        for item in step["box"]
    )
    badge_class = "bad" if fallback else ""
    return (
        f'<div class="lesson-step {"fallback" if fallback else ""}">'
        f'<span class="badge {badge_class}">'
        f'{"fallback" if fallback else "accepted"}</span>'
        f'<span class="badge">source steps '
        f'{escape(str(step["source_steps"]))}</span>'
        f'<div class="nav-title">{escape(str(step["nav_title"]))}</div>'
        f'<h4>{escape(str(step["title"]))}</h4>'
        f'<p>{escape(str(step["goal"]))}</p>'
        f'<div class="nav-title">source: '
        f'{escape(", ".join(step["source_step_ids"]))}</div>'
        f'<ol>{derive}</ol>{boxes}</div>'
    )


def _input_containers(plan: AnnotatedTeachingPlan) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for scope in _iter_scopes(plan.root_scope):
        scope_materials = _review_materials(scope.steps)
        goal_rows = [
            (
                goal.goal_ref,
                _review_materials(goal.steps),
            )
            for goal in scope.goals
        ]
        if scope_materials or any(materials for _, materials in goal_rows):
            if scope_materials:
                result.append(
                    {
                        "container_ref": f"scope:{scope.scope_ref}",
                        "label": f"Scope {scope.scope_ref} 共享步骤",
                        "materials": scope_materials,
                    }
                )
            result.extend(
                {
                    "container_ref": f"goal:{goal_ref}",
                    "label": f"Goal {goal_ref}",
                    "materials": materials,
                }
                for goal_ref, materials in goal_rows
                if materials
            )
    return result


def _review_materials(steps: Sequence[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for step in steps:
        for material in step.teaching_materials:
            result.append(
                {
                    "step_ref": f"s{len(result) + 1}",
                    **material.to_payload(),
                }
            )
    return result


def _iter_scopes(root: Any) -> tuple[Any, ...]:
    result: list[Any] = []

    def visit(scope: Any) -> None:
        result.append(scope)
        for child in scope.children:
            visit(child)

    visit(root)
    return tuple(result)


def _scope_source_for_container(
    scope_sources: Mapping[str, Any],
    container_ref: str,
) -> str:
    if container_ref.startswith("scope:"):
        return str(
            scope_sources.get(
                container_ref.removeprefix("scope:"),
                "unknown",
            )
        )
    goal_ref = container_ref.removeprefix("goal:")
    return str(scope_sources.get(goal_ref.rsplit(".", 1)[0], "unknown"))


def _write_unclassified_failure(
    sample_dir: Path,
    *,
    sample_id: str,
    error: Exception,
) -> dict[str, Any]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SAMPLE_RESULT_CONTRACT,
        "problem_id": CASE_ID,
        "sample_id": sample_id,
        "completion_ok": False,
        "direct_acceptance": False,
        "unclassified_error": f"{error.__class__.__name__}: {error}",
        "human_review_status": "blocked_by_unclassified_error",
        "sample_dir": str(sample_dir),
    }
    _write_json(sample_dir / "sample-result.json", payload)
    return payload


def _anchor(value: str) -> str:
    return "container-" + "".join(
        character if character.isalnum() else "-" for character in value
    )


def _json_text(value: Any) -> str:
    return escape(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)
    )


def _json_clone(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("recorded", "live"), required=True)
    parser.add_argument("--case", default=CASE_ID)
    parser.add_argument("--samples-per-case", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
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
    if args.case != CASE_ID:
        parser.error(f"F5-F5B3 supports only --case {CASE_ID}")
    if min(
        args.samples_per_case,
        args.concurrency,
        args.max_transport_attempts,
    ) < 1:
        parser.error(
            "sample, concurrency and transport counts must be positive"
        )
    if args.mode == "live" and os.environ.get("RUN_LLM_INTEGRATION") != "1":
        parser.error(
            "live Scope Lesson smoke requires RUN_LLM_INTEGRATION=1"
        )

    root = _repo_root()
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    fixture_root = (
        root
        / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
        "heping_ermo_b0"
    )
    b2_audit_path = (
        root
        / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
        "heping_ermo_b2/projection-audit.json"
    )
    reviewed_prompt_hash = str(
        json.loads(b2_audit_path.read_text(encoding="utf-8"))["hashes"][
            "prompt"
        ]
    )
    batch_config: dict[str, Any] = {
        "schema_version": BATCH_CONFIG_CONTRACT,
        "batch_id": args.batch_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": args.mode,
        "case_ids": [args.case],
        "samples_per_case": args.samples_per_case,
        "concurrency": min(args.concurrency, args.samples_per_case),
        "max_transport_attempts": args.max_transport_attempts,
        "semantic_attempts": 1,
        "thinking": args.thinking,
        "same_problem_few_shot": False,
        "reviewed_prompt_hash": reviewed_prompt_hash,
        "output_dir": str(output_dir),
    }
    if args.dry_run:
        print(json.dumps(batch_config, ensure_ascii=False, indent=2))
        return 0
    if output_dir.exists():
        parser.error(f"batch output already exists: {output_dir}")

    with tempfile.TemporaryDirectory(
        prefix="lesson-b3-authority-"
    ) as temp_dir:
        snapshot = build_recorded_snapshot(
            args.case,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    rubric = load_teaching_rubric(fixture_root / "rubric.json")

    client_factory: Callable[[str], LLMPlannerClient] | None = None
    if args.mode == "live":
        config = SolverRuntimeConfig.from_sources(
            planner_mode="strategy",
            llm_provider="deepseek",
            env_file=root / "server/.env",
        )
        if not config.deepseek_api_key:
            parser.error(
                "DEEPSEEK_API_KEY is required for live Scope Lesson smoke"
            )
        batch_config.update(
            {
                "provider": "deepseek",
                "model": config.llm_model or config.deepseek_model,
                "sdk_max_retries": 0,
                "reasoning_only_empty_response_retry": False,
            }
        )

        def client_factory(_sample_id: str) -> LLMPlannerClient:
            return DeepSeekPlannerClient(
                api_key=str(config.deepseek_api_key),
                base_url=config.deepseek_base_url,
                model=config.llm_model or config.deepseek_model,
                sdk_max_retries=0,
                reasoning_only_empty_response_retry=False,
            )
    else:
        batch_config.update({"provider": "recorded", "model": None})

    summary = run_scope_lesson_batch(
        snapshot,
        rubric,
        mode=args.mode,
        batch_dir=output_dir,
        samples_per_case=args.samples_per_case,
        concurrency=args.concurrency,
        max_transport_attempts=args.max_transport_attempts,
        thinking_effort=args.thinking,
        reviewed_prompt_hash=reviewed_prompt_hash,
        client_factory=client_factory,
        batch_config=batch_config,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["automated_gate_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BATCH_CONFIG_CONTRACT",
    "BATCH_SUMMARY_CONTRACT",
    "REVIEW_CONTRACT",
    "SAMPLE_RESULT_CONTRACT",
    "LessonScopeSmokeError",
    "ScopeLessonSmokeSample",
    "build_scope_lesson_review",
    "main",
    "render_scope_lesson_review_html",
    "run_scope_lesson_batch",
]
