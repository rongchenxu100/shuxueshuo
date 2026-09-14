"""Generate the F5-F5C0 all-public-capability human review artifact.

The review is deterministic.  Recorded Solver executions and three real
stateless Method executions pass through the normal Snapshot -> Teaching ->
LessonIR -> VisualStepIR -> page pipeline; no Lesson LLM is called.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
)
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonAuthoringPipeline,
    RecursiveLessonBuildResult,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingSource,
    iter_teaching_sources,
    teaching_source_owners,
)
from shuxueshuo_server.solver.explanation.teaching_specs import (
    TeachingSpecBinder,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.lesson_authoring_support import (
    DEFAULT_OUTPUT_ROOT,
    build_recorded_snapshot,
)
from shuxueshuo_server.solver.lesson_capability_coverage import (
    build_lesson_capability_coverage,
)
from shuxueshuo_server.solver.lesson_capability_synthetic import (
    SyntheticCapabilityScenario,
    build_synthetic_capability_scenarios,
)
from shuxueshuo_server.solver.runtime.methods import ALL_METHOD_SPEC_SOURCES
from shuxueshuo_server.solver.runtime.recipes import ALL_RECIPE_SPEC_SOURCES
from shuxueshuo_server.solver.visual import (
    CompiledVisualArtifacts,
    VisualStepBuilder,
    VisualStepIR,
    VisualStepIRValidator,
    forward_compile,
)


REVIEW_CONTRACT = "lesson-capability-coverage-review/v1"
OCCURRENCE_FIXTURE_CONTRACT = "lesson-capability-occurrences/v1"
SYNTHETIC_FIXTURE_CONTRACT = "lesson-capability-synthetic-scenarios/v1"
ARTIFACT_HASH_FIXTURE_CONTRACT = "lesson-capability-artifact-hashes/v1"
DEFAULT_BATCH_ID = "f5-f5c0-public-capability-review"
RECORDED_CASE_IDS = (
    "tj-2026-heping-ermo-25",
    "tj-2026-heping-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-nankai-yimo-25",
    "tj-2026-xiqing-yimo-25",
)


class LessonCapabilityCoverageReviewError(ValueError):
    """The C0 review cannot be generated as a complete atomic artifact."""


@dataclass(frozen=True)
class CapabilityReviewCase:
    snapshot: ExplanationSnapshot
    projection_payload: Mapping[str, Any]
    lesson_build: RecursiveLessonBuildResult
    visual_ir: VisualStepIR
    compiled: CompiledVisualArtifacts
    source_reviews: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class LessonCapabilityCoverageReviewArtifacts:
    coverage: Mapping[str, Any]
    review: Mapping[str, Any]
    recorded: Mapping[str, CapabilityReviewCase]
    synthetic: Mapping[str, CapabilityReviewCase]


def build_capability_coverage_review(
    *,
    snapshots: Sequence[ExplanationSnapshot],
    synthetic_scenarios: Mapping[str, SyntheticCapabilityScenario],
) -> LessonCapabilityCoverageReviewArtifacts:
    """Build all C0 artifacts in memory and enforce the 29-capability gate."""

    recorded = {
        snapshot.problem_id: _build_case(snapshot)
        for snapshot in snapshots
    }
    synthetic = {
        capability_id: _build_case(scenario.snapshot)
        for capability_id, scenario in sorted(synthetic_scenarios.items())
    }
    coverage = build_lesson_capability_coverage(
        snapshots=snapshots,
        synthetic_scenarios={
            capability_id: scenario.coverage_payload()
            for capability_id, scenario in synthetic_scenarios.items()
        },
        require_complete=True,
    )
    summary = coverage["summary"]
    expected = {
        "public_capability_count": 29,
        "public_function_count": 23,
        "public_macro_count": 6,
        "recorded_coverage_count": 26,
        "synthetic_coverage_count": 3,
        "complete_coverage_count": 29,
        "diagnostic_count": 0,
    }
    if summary != expected:
        raise LessonCapabilityCoverageReviewError(
            "lesson_capability_review_summary_invalid: "
            f"expected={expected}, observed={summary}"
        )

    cards = _capability_cards(coverage, recorded=recorded, synthetic=synthetic)
    if len(cards) != 29:
        raise LessonCapabilityCoverageReviewError(
            f"lesson_capability_review_card_count_invalid: {len(cards)}"
        )
    review = {
        "schema_version": REVIEW_CONTRACT,
        "status": "awaiting_human_review",
        "human_review_approved": False,
        "summary": dict(summary),
        "registry_fingerprint": coverage["registry_fingerprint"],
        "recorded_cases": [
            _case_summary(item) for item in recorded.values()
        ],
        "synthetic_cases": [
            _case_summary(item) for item in synthetic.values()
        ],
        "cards": cards,
        "internal_capabilities": copy.deepcopy(
            coverage["internal_capabilities"]
        ),
    }
    return LessonCapabilityCoverageReviewArtifacts(
        coverage=coverage,
        review=review,
        recorded=recorded,
        synthetic=synthetic,
    )


def capability_coverage_fixture_payloads(
    artifacts: LessonCapabilityCoverageReviewArtifacts,
) -> Mapping[str, Mapping[str, Any]]:
    """Return the normalized checked-in C0 baselines.

    The payloads contain semantic hashes and typed coverage data only.  They
    deliberately exclude generated HTML, output paths and other batch-local
    values so the fixtures remain byte-stable across rebuild locations.
    """

    coverage = copy.deepcopy(dict(artifacts.coverage))
    capabilities = coverage["capabilities"]
    occurrences = {
        capability_id: copy.deepcopy(card["recorded_occurrences"])
        for capability_id, card in capabilities.items()
    }
    synthetic = {
        capability_id: copy.deepcopy(card["synthetic_scenario"])
        for capability_id, card in capabilities.items()
        if card["synthetic_scenario"] is not None
    }
    return {
        "capability-coverage.json": coverage,
        "recorded-occurrences.json": {
            "schema_version": OCCURRENCE_FIXTURE_CONTRACT,
            "registry_fingerprint": coverage["registry_fingerprint"],
            "capabilities": occurrences,
        },
        "synthetic-scenarios.json": {
            "schema_version": SYNTHETIC_FIXTURE_CONTRACT,
            "registry_fingerprint": coverage["registry_fingerprint"],
            "scenarios": synthetic,
        },
        "artifact-hashes.json": {
            "schema_version": ARTIFACT_HASH_FIXTURE_CONTRACT,
            "source_batch": DEFAULT_BATCH_ID,
            "registry_fingerprint": coverage["registry_fingerprint"],
            "summary": copy.deepcopy(coverage["summary"]),
            "recorded_cases": copy.deepcopy(
                artifacts.review["recorded_cases"]
            ),
            "synthetic_cases": copy.deepcopy(
                artifacts.review["synthetic_cases"]
            ),
        },
    }


def _build_case(snapshot: ExplanationSnapshot) -> CapabilityReviewCase:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    if projection.diagnostics:
        raise LessonCapabilityCoverageReviewError(
            "lesson_capability_review_projection_diagnostic: "
            f"{snapshot.problem_id}:{[item.code for item in projection.diagnostics]}"
        )
    lesson_build = LessonAuthoringPipeline().build(snapshot)
    visual_ir = VisualStepBuilder().build(
        snapshot=snapshot,
        lesson=lesson_build.lesson,
    )
    VisualStepIRValidator().validate(visual_ir, lesson=lesson_build.lesson)
    compiled = forward_compile(visual_ir)
    return CapabilityReviewCase(
        snapshot=snapshot,
        projection_payload=projection.plan.to_payload(),
        lesson_build=lesson_build,
        visual_ir=visual_ir,
        compiled=compiled,
        source_reviews=_source_review_rows(
            snapshot,
            lesson_build=lesson_build,
            visual_ir=visual_ir,
        ),
    )


def _source_review_rows(
    snapshot: ExplanationSnapshot,
    *,
    lesson_build: RecursiveLessonBuildResult,
    visual_ir: VisualStepIR,
) -> Mapping[str, Mapping[str, Any]]:
    binder = TeachingSpecBinder()
    owners = teaching_source_owners(snapshot.root_scope)
    lesson_by_source: dict[str, list[Any]] = {}
    for row in lesson_build.lesson.steps:
        for source_step_id in row.source_step_ids:
            lesson_by_source.setdefault(source_step_id, []).append(row)
    visual_by_lesson = {
        row.lesson_step_id: row for row in visual_ir.steps
    }
    result: dict[str, Mapping[str, Any]] = {}
    for source in iter_teaching_sources(snapshot.root_scope):
        selection = binder.bind_source_selection(source, snapshot=snapshot)
        lesson_rows = lesson_by_source.get(source.source_step_id, [])
        scope_ref, goal_ref = owners[source.source_step_id]
        result[source.source_step_id] = {
            "problem_id": snapshot.problem_id,
            "owner": {"scope_ref": scope_ref, "goal_ref": goal_ref},
            "teaching_source": source.to_payload(),
            "generic_spec": binder.generic_spec_payload(source),
            "bound_materials": [item.to_payload() for item in selection.units],
            "lesson_steps": [row.step.to_payload() for row in lesson_rows],
            "visual_steps": [
                visual_by_lesson[row.id].to_payload()
                for row in lesson_rows
            ],
        }
    return result


def _capability_cards(
    coverage: Mapping[str, Any],
    *,
    recorded: Mapping[str, CapabilityReviewCase],
    synthetic: Mapping[str, CapabilityReviewCase],
) -> list[dict[str, Any]]:
    method_specs = {
        item.method_id: item.to_payload() for item in ALL_METHOD_SPEC_SOURCES
    }
    recipe_specs = {
        item.recipe_id: item.to_payload() for item in ALL_RECIPE_SPEC_SOURCES
    }
    cards: list[dict[str, Any]] = []
    for capability_id, audit in coverage["capabilities"].items():
        occurrences: list[dict[str, Any]] = []
        for item in audit["recorded_occurrences"]:
            case = recorded[str(item["problem_id"])]
            review = case.source_reviews[str(item["step_id"])]
            occurrences.append(
                {
                    **copy.deepcopy(review),
                    "artifact": f"cases/{item['problem_id']}/lesson.html",
                }
            )
        if audit["synthetic_scenario"] is not None:
            case = synthetic[capability_id]
            if len(case.source_reviews) != 1:
                raise LessonCapabilityCoverageReviewError(
                    "lesson_synthetic_review_source_count_invalid: "
                    f"{capability_id}:{len(case.source_reviews)}"
                )
            review = next(iter(case.source_reviews.values()))
            occurrences.append(
                {
                    **copy.deepcopy(review),
                    "artifact": f"synthetic/{capability_id}/lesson.html",
                }
            )
        spec = (
            method_specs.get(str(audit["source_id"]))
            if audit["kind"] == "function"
            else recipe_specs.get(str(audit["source_id"]))
        )
        if spec is None:
            raise LessonCapabilityCoverageReviewError(
                f"lesson_capability_review_spec_missing: {capability_id}"
            )
        cards.append(
            {
                "anchor": _anchor(capability_id),
                "capability_id": capability_id,
                "kind": audit["kind"],
                "families": list(audit["families"]),
                "public_contract": copy.deepcopy(audit["public_contract"]),
                "teaching_disposition": audit["teaching_disposition"],
                "visual_disposition": audit["visual_disposition"],
                "raw_spec": spec,
                "occurrences": occurrences,
                "diagnostics": list(audit["diagnostics"]),
            }
        )
    return cards


def _case_summary(case: CapabilityReviewCase) -> dict[str, Any]:
    lesson = case.lesson_build.lesson
    return {
        "problem_id": case.snapshot.problem_id,
        "snapshot_hash": stable_hash(
            _snapshot_semantic_payload(case.snapshot)
        ),
        "annotated_plan_hash": stable_hash(case.projection_payload),
        "lesson_ir_hash": stable_hash(lesson.to_payload()),
        "visual_step_ir_hash": stable_hash(case.visual_ir.to_payload()),
        "source_step_count": len(case.source_reviews),
        "lesson_step_count": len(lesson.steps),
        "visual_frame_count": sum(
            len(step.frames) for step in case.visual_ir.steps
        ),
    }


def _snapshot_semantic_payload(
    snapshot: ExplanationSnapshot,
) -> Mapping[str, Any]:
    """Return the complete teaching snapshot without its runtime envelope link.

    ``verified_execution_hash`` authenticates one concrete execution-authority
    artifact.  That artifact includes process-local invocation identities, so
    its hash may change when the same verified mathematics is replayed.  C0
    baselines audit the Snapshot teaching content itself; every other field
    remains covered by the semantic hash.
    """

    payload = copy.deepcopy(snapshot.to_payload())
    payload.pop("verified_execution_hash", None)
    return payload


def write_capability_coverage_review(
    artifacts: LessonCapabilityCoverageReviewArtifacts,
    *,
    output_dir: Path,
) -> None:
    if output_dir.exists():
        raise LessonCapabilityCoverageReviewError(
            f"lesson_capability_review_output_exists: {output_dir}"
        )
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "capability-coverage.json", artifacts.coverage)
    _write_json(output_dir / "review.json", artifacts.review)
    for problem_id, case in artifacts.recorded.items():
        _write_case(output_dir / "cases" / problem_id, case)
    for capability_id, case in artifacts.synthetic.items():
        target = output_dir / "synthetic" / capability_id
        _write_case(target, case)
        only_source = next(iter(case.source_reviews.values()))
        _write_json(target / "teaching-source.json", only_source["teaching_source"])
        _write_json(target / "bound-material.json", {
            "materials": only_source["bound_materials"]
        })
        (target / "review.html").write_text(
            _render_synthetic_review(capability_id, only_source),
            encoding="utf-8",
        )
    (output_dir / "review.html").write_text(
        render_capability_coverage_review_html(artifacts.review),
        encoding="utf-8",
    )


def _write_case(output_dir: Path, case: CapabilityReviewCase) -> None:
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "snapshot.json", case.snapshot.to_payload())
    _write_json(
        output_dir / "annotated-teaching-plan.json",
        case.projection_payload,
    )
    _write_json(
        output_dir / "deterministic-lesson-ir.json",
        case.lesson_build.lesson.to_payload(),
    )
    _write_json(output_dir / "visual-step-ir.json", case.visual_ir.to_payload())
    _write_json(
        output_dir / "lesson-assembly-authority.json",
        case.lesson_build.assembly_authority,
    )
    lesson_data = copy.deepcopy(case.compiled.lesson_data)
    lesson_data.setdefault("meta", {})["outputPath"] = str(
        output_dir / "lesson.html"
    )
    _write_json(output_dir / "geometry-spec.json", case.compiled.geometry_spec)
    _write_json(
        output_dir / "step-decorations.json",
        case.compiled.step_decorations,
    )
    _write_json(output_dir / "lesson-data.json", lesson_data)
    audit = {
        "schema_version": "lesson-capability-case-audit/v1",
        **_case_summary(case),
        "source_steps": sorted(case.source_reviews),
        "diagnostics": [],
    }
    _write_json(output_dir / "audit.json", audit)
    root = _repo_root()
    for command in (
        ["node", str(root / "tools/validate-geometry-spec.mjs"), str(output_dir)],
        ["node", str(root / "tools/build-lesson-page.mjs"), str(output_dir)],
    ):
        subprocess.run(
            command,
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    if not (output_dir / "lesson.html").is_file():
        raise LessonCapabilityCoverageReviewError(
            f"lesson_capability_review_page_missing: {output_dir}"
        )


def render_capability_coverage_review_html(review: Mapping[str, Any]) -> str:
    summary = review["summary"]
    cards = review["cards"]
    nav = "".join(
        f'<a href="#{escape(str(card["anchor"]))}">'
        f'<b>{escape(str(card["capability_id"]))}</b>'
        f'<small>{escape(str(card["kind"]))}</small></a>'
        for card in cards
    )
    articles = "".join(_render_capability_card(card) for card in cards)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5C0 Public Capability Review</title><style>
:root{{--ink:#172033;--muted:#667085;--line:#d8dee8;--paper:#f4f1e8;--panel:#fff;--nav:#142039;--ok:#087b5b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{position:sticky;top:0;z-index:5;background:var(--nav);color:#fff;padding:14px 22px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}header h1{{font-size:20px;margin:0 12px 0 0}}.badge{{border:1px solid #667593;border-radius:9px;padding:5px 9px}}.layout{{display:grid;grid-template-columns:280px minmax(0,1fr);max-width:1900px;margin:auto}}nav{{position:sticky;top:65px;height:calc(100vh - 65px);overflow:auto;padding:16px;border-right:1px solid var(--line)}}nav a{{display:flex;justify-content:space-between;gap:8px;color:var(--ink);text-decoration:none;padding:6px 4px;border-bottom:1px solid #e5e7eb}}nav small{{color:var(--muted)}}main{{padding:20px}}article,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:18px;overflow:hidden}}article>h2,.panel{{padding:16px}}article>h2{{margin:0;border-bottom:1px solid var(--line);font-size:18px}}.meta{{font-size:12px;color:var(--muted)}}.cols{{display:grid;grid-template-columns:1fr 1.35fr}}.col{{padding:16px;min-width:0}}.col+.col{{border-left:1px solid var(--line)}}pre{{white-space:pre-wrap;word-break:break-word;background:#f6f6f3;padding:12px;border-radius:8px;max-height:620px;overflow:auto}}details{{margin:10px 0}}iframe{{width:100%;height:680px;border:1px solid var(--line);border-radius:10px}}.ok{{color:var(--ok);font-weight:700}}.occurrence{{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}}
@media(max-width:950px){{.layout,.cols{{display:block}}nav{{position:static;height:auto}}.col+.col{{border-left:0;border-top:1px solid var(--line)}}}}
</style></head><body><header><h1>F5-F5C0 全部公开能力 Review</h1>
<span class="badge">{summary['public_function_count']} Function</span><span class="badge">{summary['public_macro_count']} Macro</span><span class="badge">recorded {summary['recorded_coverage_count']} + synthetic {summary['synthetic_coverage_count']}</span><span class="badge">等待人工审阅</span></header>
<div class="layout"><nav>{nav}</nav><main><section class="panel"><h2>覆盖门禁</h2><pre>{escape(json.dumps(summary,ensure_ascii=False,indent=2))}</pre></section>{articles}
<section class="panel"><h2>Internal-only Method</h2><p>以下 Method 不在 Family Catalog 的 Planner 公开集合内，只验证它们不会成为顶层 TeachingSource。</p><pre>{escape(json.dumps(review['internal_capabilities'],ensure_ascii=False,indent=2))}</pre></section>
</main></div></body></html>"""


def _render_capability_card(card: Mapping[str, Any]) -> str:
    occurrences = "".join(_render_occurrence(item) for item in card["occurrences"])
    diagnostics = card["diagnostics"]
    state = '<span class="ok">coverage complete</span>' if not diagnostics else escape(str(diagnostics))
    return f"""<article id="{escape(str(card['anchor']))}"><h2>{escape(str(card['capability_id']))} <span class="meta">{escape(str(card['kind']))} · {escape(', '.join(card['families']))}</span></h2>
<div class="cols"><section class="col"><h3>公开合同与通用 Spec</h3><p>{state}<br>Teaching: {escape(str(card['teaching_disposition']))} · Visual: {escape(str(card['visual_disposition']))}</p>
<details><summary>Public contract</summary><pre>{escape(json.dumps(card['public_contract'],ensure_ascii=False,indent=2))}</pre></details>
<details open><summary>Method / Recipe Spec</summary><pre>{escape(json.dumps(card['raw_spec'],ensure_ascii=False,indent=2))}</pre></details></section>
<section class="col"><h3>实际绑定与最终 Frame</h3>{occurrences}</section></div></article>"""


def _render_occurrence(item: Mapping[str, Any]) -> str:
    owner = item["owner"]
    return f"""<div class="occurrence"><h4>{escape(str(item['problem_id']))} · {escape(str(item['teaching_source']['step_id']))}</h4>
<p class="meta">{escape(str(owner['scope_ref']))}{' / '+escape(str(owner['goal_ref'])) if owner.get('goal_ref') else ''}</p>
<details open><summary>绑定后的教学材料</summary><pre>{escape(json.dumps(item['bound_materials'],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>Verified TeachingSource</summary><pre>{escape(json.dumps(item['teaching_source'],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>最终 Lesson / Visual</summary><pre>{escape(json.dumps({'lesson_steps':item['lesson_steps'],'visual_steps':item['visual_steps']},ensure_ascii=False,indent=2))}</pre></details>
<details><summary>渲染页面</summary><p><a href="{escape(str(item['artifact']))}">打开页面</a></p><iframe loading="lazy" src="{escape(str(item['artifact']))}"></iframe></details></div>"""


def _render_synthetic_review(
    capability_id: str,
    source: Mapping[str, Any],
) -> str:
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(capability_id)} synthetic review</title><style>body{{font:14px/1.5 sans-serif;margin:24px}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:12px}}iframe{{width:100%;height:760px}}</style></head><body><h1>{escape(capability_id)}</h1><h2>TeachingSource</h2><pre>{escape(json.dumps(source['teaching_source'],ensure_ascii=False,indent=2))}</pre><h2>Bound material</h2><pre>{escape(json.dumps(source['bound_materials'],ensure_ascii=False,indent=2))}</pre><h2>Rendered page</h2><iframe src="lesson.html"></iframe></body></html>"""


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _anchor(value: str) -> str:
    return "capability-" + "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in value
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="all")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.case != "all":
        raise SystemExit("F5-F5C0 requires --case all")
    root = _repo_root()
    snapshots: list[ExplanationSnapshot] = []
    with tempfile.TemporaryDirectory(prefix="lesson-c0-authority-") as temp_dir:
        authority_root = Path(temp_dir)
        for problem_id in RECORDED_CASE_IDS:
            snapshots.append(
                build_recorded_snapshot(
                    problem_id,
                    authority_dir=authority_root / problem_id,
                    f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
                )
            )
    artifacts = build_capability_coverage_review(
        snapshots=snapshots,
        synthetic_scenarios=build_synthetic_capability_scenarios(),
    )
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    write_capability_coverage_review(artifacts, output_dir=output_dir)
    print(json.dumps({
        "output_dir": str(output_dir),
        "review_html": str(output_dir / "review.html"),
        **dict(artifacts.coverage["summary"]),
        "human_review_approved": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_HASH_FIXTURE_CONTRACT",
    "DEFAULT_BATCH_ID",
    "OCCURRENCE_FIXTURE_CONTRACT",
    "RECORDED_CASE_IDS",
    "REVIEW_CONTRACT",
    "SYNTHETIC_FIXTURE_CONTRACT",
    "CapabilityReviewCase",
    "LessonCapabilityCoverageReviewArtifacts",
    "LessonCapabilityCoverageReviewError",
    "build_capability_coverage_review",
    "capability_coverage_fixture_payloads",
    "render_capability_coverage_review_html",
    "write_capability_coverage_review",
]
