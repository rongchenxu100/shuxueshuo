"""Build the F5-F5B4 recursive LessonIR and its human-review artifact."""

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
    build_projection_audit,
    lesson_scope_content_schema,
    render_annotated_teaching_prompt,
)
from shuxueshuo_server.solver.explanation.lesson_ir import (
    LessonIR,
    RecursiveLessonBuildResult,
    RecursiveLessonIRAssembler,
)
from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    iter_teaching_sources,
    teaching_source_owners,
)
from shuxueshuo_server.solver.explanation.scope_lesson import (
    LessonScopeContentValidator,
)
from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.extraction.source_identity import stable_hash
from shuxueshuo_server.solver.lesson_authoring_support import (
    CASE_ID,
    DEFAULT_OUTPUT_ROOT,
    build_recorded_snapshot,
    evaluate_teaching_rows,
    load_teaching_rubric,
)
from shuxueshuo_server.solver.visual import (
    CompiledVisualArtifacts,
    VisualStepBuilder,
    VisualStepIR,
    VisualStepIRValidator,
    forward_compile,
)


REVIEW_CONTRACT = "lesson-recursive-ir-review/v1"
ASSEMBLY_AUDIT_CONTRACT = "lesson-recursive-ir-assembly-audit/v1"
DEFAULT_BATCH_ID = "f5-f5b4-heping-recursive-lesson-review"
REVIEWED_PROMPT_HASH = (
    "a4826d362374ffacf405a4188c7a63b4d516a5bd67bba8c61272390b027fa257"
)


class LessonRecursiveIRReviewError(ValueError):
    """The B4 review artifact cannot be generated safely."""


@dataclass(frozen=True)
class _ReviewBranch:
    build: RecursiveLessonBuildResult
    visual_ir: VisualStepIR
    compiled: CompiledVisualArtifacts


@dataclass(frozen=True)
class LessonRecursiveIRReviewArtifacts:
    snapshot: ExplanationSnapshot
    approved: _ReviewBranch
    fallback: _ReviewBranch
    audit: Mapping[str, Any]
    review: Mapping[str, Any]


def build_recursive_lesson_review(
    snapshot: ExplanationSnapshot,
    *,
    approved_scope_content: Mapping[str, Any],
    rubric: Mapping[str, Any],
) -> LessonRecursiveIRReviewArtifacts:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    output_schema = lesson_scope_content_schema(projection.plan)
    prompt = render_annotated_teaching_prompt(
        projection.plan,
        authority=projection.authority,
        output_schema=output_schema,
    )
    projection_audit = build_projection_audit(
        projection,
        prompt=prompt,
        output_schema=output_schema,
    )
    prompt_hash = str(projection_audit["hashes"]["prompt"])
    if prompt_hash != REVIEWED_PROMPT_HASH:
        raise LessonRecursiveIRReviewError(
            "lesson_recursive_ir_review_prompt_hash_drift: "
            f"expected={REVIEWED_PROMPT_HASH}, observed={prompt_hash}"
        )

    validator = LessonScopeContentValidator(
        plan=projection.plan,
        authority=projection.authority,
    )
    approved_validation = validator.validate_payload(approved_scope_content)
    if not approved_validation.direct_acceptance:
        raise LessonRecursiveIRReviewError(
            "lesson_recursive_ir_review_approved_body_rejected"
        )
    fallback_validation = validator.validate_payload(
        validator.deterministic_fallback
    )
    assembler = RecursiveLessonIRAssembler()
    approved_build = assembler.assemble(
        snapshot,
        projection,
        approved_validation,
    )
    fallback_build = assembler.assemble(
        snapshot,
        projection,
        fallback_validation,
    )
    approved = _visual_branch(snapshot, approved_build)
    fallback = _visual_branch(snapshot, fallback_build)

    approved_evaluation = _evaluate_recursive_lesson(
        approved.build.lesson,
        rubric,
    )
    fallback_evaluation = _evaluate_recursive_lesson(
        fallback.build.lesson,
        rubric,
    )
    topology_equal = _scope_shape(approved.build.lesson.root_scope) == _scope_shape(
        fallback.build.lesson.root_scope
    )
    audit = {
        "schema_version": ASSEMBLY_AUDIT_CONTRACT,
        "status": "ready_for_human_review",
        "human_review_approved": False,
        "hashes": {
            "snapshot": approved.build.lesson.source_snapshot_hash,
            "prompt": prompt_hash,
            "annotated_plan": projection_audit["hashes"]["annotated_plan"],
            "approved_lesson_ir": stable_hash(
                approved.build.lesson.to_payload()
            ),
            "fallback_lesson_ir": stable_hash(
                fallback.build.lesson.to_payload()
            ),
        },
        "counts": {
            "scope_count": len(approved.build.lesson.traversal.scope_by_ref),
            "goal_count": len(approved.build.lesson.traversal.goal_by_ref),
            "approved_lesson_step_count": len(approved.build.lesson.steps),
            "fallback_lesson_step_count": len(fallback.build.lesson.steps),
            "approved_visual_step_count": len(approved.visual_ir.steps),
            "fallback_visual_step_count": len(fallback.visual_ir.steps),
        },
        "checks": {
            "prompt_hash_unchanged": prompt_hash == REVIEWED_PROMPT_HASH,
            "topology_equal": topology_equal,
            "approved_materials_consumed_once": _material_positions_complete(
                projection.authority,
                approved.build.assembly_authority,
            ),
            "fallback_materials_consumed_once": _material_positions_complete(
                projection.authority,
                fallback.build.assembly_authority,
            ),
            "approved_rubric_5_of_5": approved_evaluation["coverage_rate"] == 1.0,
            "fallback_rubric_5_of_5": fallback_evaluation["coverage_rate"] == 1.0,
        },
        "rubric": {
            "approved": approved_evaluation,
            "fallback": fallback_evaluation,
        },
        "forbidden_fields": _forbidden_lesson_fields(
            approved.build.lesson.to_payload()
        ),
    }
    expected_counts = {
        "scope_count": 5,
        "goal_count": 4,
        "approved_lesson_step_count": 12,
        "fallback_lesson_step_count": 13,
        "approved_visual_step_count": 12,
        "fallback_visual_step_count": 13,
    }
    if audit["counts"] != expected_counts:
        raise LessonRecursiveIRReviewError(
            "lesson_recursive_ir_review_counts_invalid: "
            f"{audit['counts']}"
        )
    if not all(audit["checks"].values()) or audit["forbidden_fields"]:
        raise LessonRecursiveIRReviewError(
            "lesson_recursive_ir_review_audit_failed: "
            + json.dumps(audit, ensure_ascii=False)
        )

    review = _build_review_payload(
        snapshot,
        approved=approved,
        fallback=fallback,
        approved_scope_content=approved_scope_content,
        audit=audit,
    )
    return LessonRecursiveIRReviewArtifacts(
        snapshot=snapshot,
        approved=approved,
        fallback=fallback,
        audit=audit,
        review=review,
    )


def _visual_branch(
    snapshot: ExplanationSnapshot,
    build: RecursiveLessonBuildResult,
) -> _ReviewBranch:
    visual_ir = VisualStepBuilder().build(
        snapshot=snapshot,
        lesson=build.lesson,
    )
    VisualStepIRValidator().validate(visual_ir, lesson=build.lesson)
    return _ReviewBranch(
        build=build,
        visual_ir=visual_ir,
        compiled=forward_compile(visual_ir),
    )


def _evaluate_recursive_lesson(
    lesson: LessonIR,
    rubric: Mapping[str, Any],
) -> Mapping[str, Any]:
    rows = [
        {
            "id": row.lesson_step_id,
            **row.step.to_payload(),
        }
        for row in lesson.steps
    ]
    return evaluate_teaching_rows(
        rows,
        rubric,
        problem_id=lesson.problem_id,
    )


def _material_positions_complete(
    projection_authority: Mapping[str, Any],
    assembly_authority: Mapping[str, Any],
) -> bool:
    containers = projection_authority.get("containers")
    lesson_steps = assembly_authority.get("lesson_steps")
    if not isinstance(containers, Mapping) or not isinstance(lesson_steps, Mapping):
        return False
    observed: dict[str, list[int]] = {str(key): [] for key in containers}
    for row in lesson_steps.values():
        if not isinstance(row, Mapping):
            return False
        container_ref = str(row.get("container_ref") or "")
        if container_ref not in observed:
            return False
        observed[container_ref].extend(
            int(value) for value in row.get("material_positions") or ()
        )
    return all(
        sorted(observed[container_ref]) == list(range(len(records)))
        for container_ref, records in containers.items()
    )


def _scope_shape(scope: Any) -> tuple[Any, ...]:
    return (
        scope.scope_ref,
        tuple(goal.goal_ref for goal in scope.goals),
        tuple(_scope_shape(child) for child in scope.children),
    )


def _forbidden_lesson_fields(payload: Mapping[str, Any]) -> list[str]:
    forbidden = {
        "scope_id",
        "sections",
        "trace_refs",
        "gaps",
        "teaching_substep_ids",
        "family_id",
        "evidence_refs",
        "unit_id",
    }
    hits: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                if str(key) in forbidden:
                    hits.add(str(key))
                visit(item)
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            for item in value:
                visit(item)

    visit(payload)
    return sorted(hits)


def _build_review_payload(
    snapshot: ExplanationSnapshot,
    *,
    approved: _ReviewBranch,
    fallback: _ReviewBranch,
    approved_scope_content: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    source_by_id = {
        source.source_step_id: source
        for source in iter_teaching_sources(snapshot.root_scope)
    }
    owners = teaching_source_owners(snapshot.root_scope)
    approved_bound = {
        (container_ref, tuple(row.material_positions)): row
        for container_ref, rows in approved.build.validation.bound_steps.items()
        for row in rows
    }
    cards: list[dict[str, Any]] = []
    for row in approved.build.lesson.steps:
        authority = approved.build.assembly_authority["lesson_steps"][row.id]
        material_positions = tuple(authority["material_positions"])
        bound = approved_bound[(authority["container_ref"], material_positions)]
        canonical_sources = []
        for source_step_id in row.source_step_ids:
            source = source_by_id[source_step_id]
            scope_ref, goal_ref = owners[source_step_id]
            canonical_sources.append(
                {
                    "step_id": source_step_id,
                    "capability_id": source.capability_id,
                    "owner": {
                        "scope_ref": scope_ref,
                        "goal_ref": goal_ref,
                    },
                    "intent": source.intent,
                    "inputs": source.inputs,
                    "outputs": source.outputs,
                }
            )
        cards.append(
            {
                "anchor": _anchor(row.id),
                "container_ref": authority["container_ref"],
                "lesson_step_id": row.id,
                "b3_source_steps": list(bound.teaching_step_refs),
                "material_positions": list(material_positions),
                "canonical_sources": canonical_sources,
                "lesson_step": row.step.to_payload(),
                "b3_accepted_step": bound.content_payload(),
            }
        )
    return {
        "schema_version": REVIEW_CONTRACT,
        "status": "awaiting_human_review",
        "summary": dict(audit),
        "scope_tree": _scope_review_tree(approved.build.lesson.root_scope),
        "cards": cards,
        "answer_links": _answer_links(snapshot, approved.build.lesson),
        "topology_comparison": {
            "approved": _scope_review_tree(approved.build.lesson.root_scope),
            "deterministic_fallback": _scope_review_tree(
                fallback.build.lesson.root_scope
            ),
        },
        "raw_artifacts": {
            "approved_scope_content": copy.deepcopy(approved_scope_content),
            "approved_lesson_ir": approved.build.lesson.to_payload(),
            "fallback_lesson_ir": fallback.build.lesson.to_payload(),
            "approved_assembly_authority": copy.deepcopy(
                approved.build.assembly_authority
            ),
            "fallback_assembly_authority": copy.deepcopy(
                fallback.build.assembly_authority
            ),
            "approved_visual_step_ir": approved.visual_ir.to_payload(),
            "fallback_visual_step_ir": fallback.visual_ir.to_payload(),
        },
    }


def _scope_review_tree(scope: Any) -> dict[str, Any]:
    return {
        "scope_ref": scope.scope_ref,
        "step_ids": [step.lesson_step_id for step in scope.steps],
        "goals": {
            goal.goal_ref: [step.lesson_step_id for step in goal.steps]
            for goal in scope.goals
        },
        "children": [_scope_review_tree(child) for child in scope.children],
    }


def _answer_links(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    traversal = lesson.traversal

    def visit(scope: Any) -> None:
        for goal in scope.goals:
            producer = str(goal.answer_from.get("step_id") or "")
            matches = [
                row
                for row in traversal.preorder_steps
                if producer in row.source_step_ids
            ]
            rows.append(
                {
                    "goal_ref": goal.goal_ref,
                    "answer_from": dict(goal.answer_from),
                    "verified_answer": copy.deepcopy(
                        snapshot.answers.get(goal.goal_ref)
                    ),
                    "producer_step_id": producer,
                    "lesson_step_id": matches[0].id if len(matches) == 1 else None,
                    "lesson_box": list(matches[0].box) if len(matches) == 1 else [],
                }
            )
        for child in scope.children:
            visit(child)

    visit(snapshot.root_scope)
    return rows


def write_recursive_lesson_review(
    artifacts: LessonRecursiveIRReviewArtifacts,
    *,
    output_dir: Path,
) -> None:
    if output_dir.exists():
        raise LessonRecursiveIRReviewError(
            f"lesson_recursive_ir_review_output_exists: {output_dir}"
        )
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "assembly-audit.json", artifacts.audit)
    _write_json(output_dir / "review.json", artifacts.review)
    _write_branch(output_dir / "approved", artifacts.approved)
    _write_branch(
        output_dir / "deterministic-fallback",
        artifacts.fallback,
    )
    (output_dir / "review.html").write_text(
        _render_review_html(artifacts.review),
        encoding="utf-8",
    )


def _write_branch(output_dir: Path, branch: _ReviewBranch) -> None:
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "lesson-ir.json", branch.build.lesson.to_payload())
    _write_json(
        output_dir / "lesson-assembly-authority.json",
        branch.build.assembly_authority,
    )
    _write_json(output_dir / "visual-step-ir.json", branch.visual_ir.to_payload())
    lesson_data = copy.deepcopy(branch.compiled.lesson_data)
    lesson_data.setdefault("meta", {})["outputPath"] = str(
        output_dir / "lesson.html"
    )
    _write_json(output_dir / "geometry-spec.json", branch.compiled.geometry_spec)
    _write_json(
        output_dir / "step-decorations.json",
        branch.compiled.step_decorations,
    )
    _write_json(output_dir / "lesson-data.json", lesson_data)
    root = _repo_root()
    subprocess.run(
        ["node", str(root / "tools/validate-geometry-spec.mjs"), str(output_dir)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["node", str(root / "tools/build-lesson-page.mjs"), str(output_dir)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if not (output_dir / "lesson.html").exists():
        raise LessonRecursiveIRReviewError(
            f"lesson_recursive_ir_review_page_missing: {output_dir}"
        )


def _write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _render_review_html(review: Mapping[str, Any]) -> str:
    summary = review["summary"]
    counts = summary["counts"]
    cards = review["cards"]
    navigation = "".join(
        f'<a href="#{escape(card["anchor"])}">'
        f'{escape(card["lesson_step_id"])}</a>'
        for card in cards
    )
    articles = "".join(_render_card(card) for card in cards)
    answer_rows = "".join(
        "<tr>"
        f'<td>{escape(str(row["goal_ref"]))}</td>'
        f'<td><code>{escape(str(row["producer_step_id"]))}</code></td>'
        f'<td><a href="#{escape(_anchor(str(row["lesson_step_id"])))}">'
        f'{escape(str(row["lesson_step_id"]))}</a></td>'
        f'<td>{escape("；".join(row["lesson_box"]))}</td>'
        "</tr>"
        for row in review["answer_links"]
    )
    raw = review["raw_artifacts"]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5B4 Recursive LessonIR Review</title>
<style>
:root{{--ink:#172033;--muted:#667085;--line:#d8dce5;--paper:#fbfaf7;--panel:#fff;--accent:#0b63ce;--ok:#087b5b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{position:sticky;top:0;z-index:2;background:#142039;color:#fff;padding:16px 24px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}}
header h1{{font-size:20px;margin:0 14px 0 0}}.badge{{border:1px solid #60708f;border-radius:10px;padding:6px 10px}}
.layout{{display:grid;grid-template-columns:260px minmax(0,1fr);max-width:1500px;margin:auto}}
nav{{position:sticky;top:77px;height:calc(100vh - 77px);overflow:auto;padding:20px;border-right:1px solid var(--line)}}nav a{{display:block;color:var(--ink);padding:5px;text-decoration:none;word-break:break-all}}nav a:hover{{color:var(--accent)}}
main{{padding:22px}}.panel,article{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin:0 0 20px;overflow:hidden}}
.panel{{padding:20px}}article>h2{{font-size:18px;margin:0;padding:16px 20px;border-bottom:1px solid var(--line)}}
.meta{{color:var(--muted);font-size:13px}}.columns{{display:grid;grid-template-columns:1fr 1fr}}.column{{padding:18px;min-width:0}}.column+ .column{{border-left:1px solid var(--line)}}
h3{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}pre{{white-space:pre-wrap;word-break:break-word;background:#f5f5f2;border-radius:9px;padding:14px;font-size:12px;max-height:640px;overflow:auto}}
.lesson h4{{margin:10px 0 4px}}.derive{{padding-left:22px}}.box{{background:#eaf8f3;color:#075f49;border-radius:8px;padding:10px;margin-top:10px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}code{{font-size:12px}}details{{margin:14px 0}}iframe{{width:100%;height:720px;border:1px solid var(--line);border-radius:10px}}
@media(max-width:900px){{.layout{{display:block}}nav{{position:static;height:auto;border-right:0}}.columns{{grid-template-columns:1fr}}.column+ .column{{border-left:0;border-top:1px solid var(--line)}}}}
</style></head><body>
<header><h1>F5-F5B4 Recursive LessonIR Review</h1>
<span class="badge">{counts["scope_count"]} Scope / {counts["goal_count"]} Goal</span>
<span class="badge">approved {counts["approved_lesson_step_count"]} steps</span>
<span class="badge">fallback {counts["fallback_lesson_step_count"]} steps</span>
<span class="badge">Rubric 5/5</span><span class="badge">等待人工审阅</span></header>
<div class="layout"><nav><strong>Lesson Steps</strong>{navigation}</nav><main>
<section class="panel"><h2>组装门禁</h2><pre>{escape(json.dumps(summary,ensure_ascii=False,indent=2))}</pre></section>
<section class="panel"><h2>Goal answer_from → producer → LessonStep box</h2><table><thead><tr><th>Goal</th><th>Producer</th><th>LessonStep</th><th>Box</th></tr></thead><tbody>{answer_rows}</tbody></table></section>
<section class="panel"><h2>Approved / deterministic topology</h2><pre>{escape(json.dumps(review["topology_comparison"],ensure_ascii=False,indent=2))}</pre></section>
{articles}
<section class="panel"><h2>编译页面</h2><p><a href="approved/lesson.html">打开 approved 页面</a> · <a href="deterministic-fallback/lesson.html">打开 fallback 页面</a></p><iframe src="approved/lesson.html"></iframe></section>
<section class="panel"><h2>Raw recursive artifacts</h2>
<details><summary>Approved LessonIR</summary><pre>{escape(json.dumps(raw["approved_lesson_ir"],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>Deterministic fallback LessonIR</summary><pre>{escape(json.dumps(raw["fallback_lesson_ir"],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>Approved assembly authority</summary><pre>{escape(json.dumps(raw["approved_assembly_authority"],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>Deterministic fallback assembly authority</summary><pre>{escape(json.dumps(raw["fallback_assembly_authority"],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>Approved VisualStepIR</summary><pre>{escape(json.dumps(raw["approved_visual_step_ir"],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>Deterministic fallback VisualStepIR</summary><pre>{escape(json.dumps(raw["fallback_visual_step_ir"],ensure_ascii=False,indent=2))}</pre></details>
<details><summary>B3 accepted Scope Content</summary><pre>{escape(json.dumps(raw["approved_scope_content"],ensure_ascii=False,indent=2))}</pre></details>
</section></main></div></body></html>"""


def _render_card(card: Mapping[str, Any]) -> str:
    lesson = card["lesson_step"]
    derive = "".join(
        f"<li>{escape(str(marker))} {escape(str(text))}</li>"
        for marker, text in lesson["derive"]
    )
    box = "<br>".join(escape(str(item)) for item in lesson["box"])
    return f"""<article id="{escape(card['anchor'])}">
<h2>{escape(card['lesson_step_id'])}<div class="meta">{escape(card['container_ref'])} · materials {escape(str(card['material_positions']))}</div></h2>
<div class="columns"><section class="column"><h3>B3 accepted body + canonical source</h3>
<p class="meta">B3 local source_steps: {escape(', '.join(card['b3_source_steps']))}</p>
<pre>{escape(json.dumps(card['canonical_sources'],ensure_ascii=False,indent=2))}</pre>
<details><summary>B3 accepted step</summary><pre>{escape(json.dumps(card['b3_accepted_step'],ensure_ascii=False,indent=2))}</pre></details></section>
<section class="column lesson"><h3>Recursive LessonIR</h3>
<p class="meta">source: {escape(', '.join(lesson['source_step_ids']))}<br>capability: {escape(', '.join(lesson['capability_ids']))}<br>unit: {escape(', '.join(lesson['teaching_unit_keys']))}</p>
<h4>{escape(lesson['title'])}</h4><div class="meta">nav: {escape(lesson['nav_title'])}</div><p>{escape(lesson['goal'])}</p>
<ol class="derive">{derive}</ol><div class="box">{box}</div>
<details><summary>LessonStep JSON</summary><pre>{escape(json.dumps(lesson,ensure_ascii=False,indent=2))}</pre></details></section></div></article>"""


def _anchor(value: str) -> str:
    return "lesson-" + "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in value
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default=CASE_ID)
    parser.add_argument(
        "--scope-content",
        default=(
            "tests/solver/fixtures/lesson_scope_authoring_vnext/"
            "heping_ermo_b3/scope-content.json"
        ),
    )
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser


def _resolve_cli_input(repo_root: Path, value: str) -> Path:
    """Resolve documented ``cd server`` inputs without making cwd mandatory."""

    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    return (repo_root / path).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.case != CASE_ID:
        raise SystemExit(f"F5-F5B4 supports only --case {CASE_ID}")
    root = _repo_root()
    scope_content_path = _resolve_cli_input(root, args.scope_content)
    rubric_path = (
        root
        / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
        "heping_ermo_b0/rubric.json"
    )
    with tempfile.TemporaryDirectory(prefix="lesson-b4-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            args.case,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    artifacts = build_recursive_lesson_review(
        snapshot,
        approved_scope_content=json.loads(
            scope_content_path.read_text(encoding="utf-8")
        ),
        rubric=load_teaching_rubric(rubric_path),
    )
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    write_recursive_lesson_review(artifacts, output_dir=output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "review_html": str(output_dir / "review.html"),
                **dict(artifacts.audit["counts"]),
                "human_review_approved": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSEMBLY_AUDIT_CONTRACT",
    "DEFAULT_BATCH_ID",
    "LessonRecursiveIRReviewArtifacts",
    "LessonRecursiveIRReviewError",
    "REVIEW_CONTRACT",
    "build_recursive_lesson_review",
    "write_recursive_lesson_review",
]
