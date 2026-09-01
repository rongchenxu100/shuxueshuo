"""Generate the F5-F5B2 Annotated Teaching Plan and Prompt review page."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.explanation.annotated_teaching import (
    AnnotatedTeachingPlanProjector,
    AnnotatedTeachingProjection,
    AnnotatedTeachingPrompt,
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
from shuxueshuo_server.solver.lesson_scope_authoring_smoke import (
    CASE_ID,
    DEFAULT_OUTPUT_ROOT,
    build_recorded_snapshot,
    evaluate_lesson_teaching,
    load_teaching_rubric,
)


REVIEW_SCHEMA = "lesson-annotated-teaching-review/v1"
DEFAULT_BATCH_ID = "f5-f5b2-heping-annotated-review"


class LessonAnnotatedTeachingReviewError(ValueError):
    """The B2 review artifact cannot be generated atomically."""


@dataclass(frozen=True)
class LessonAnnotatedTeachingReviewArtifacts:
    snapshot: ExplanationSnapshot
    projection: AnnotatedTeachingProjection
    output_schema: Mapping[str, Any]
    prompt: AnnotatedTeachingPrompt
    audit: Mapping[str, Any]
    review: Mapping[str, Any]


def build_annotated_teaching_review(
    snapshot: ExplanationSnapshot,
    *,
    rubric: Mapping[str, Any],
) -> LessonAnnotatedTeachingReviewArtifacts:
    projection = AnnotatedTeachingPlanProjector().project(snapshot)
    output_schema = lesson_scope_content_schema(projection.plan)
    prompt = render_annotated_teaching_prompt(
        projection.plan,
        output_schema=output_schema,
    )
    audit = build_projection_audit(
        projection,
        prompt=prompt,
        output_schema=output_schema,
    )
    if audit["status"] != "ready_for_human_review":
        raise LessonAnnotatedTeachingReviewError(
            "lesson_annotated_teaching_review_audit_invalid: "
            + json.dumps(audit, ensure_ascii=False)
        )
    plan_payload = projection.plan.to_payload()
    cards = _review_cards(plan_payload["root_scope"])
    rubric_evaluation = evaluate_lesson_teaching(
        _pseudo_lesson_for_rubric(
            problem_id=snapshot.problem_id,
            cards=cards,
        ),
        rubric,
    )
    review = {
        "schema_version": REVIEW_SCHEMA,
        "summary": {
            **dict(audit["counts"]),
            "rubric_coverage": rubric_evaluation,
            "prompt_chars": dict(audit["prompt_chars"]),
            "review_status": "awaiting_human_review",
        },
        "scope_tree": _scope_tree(plan_payload["root_scope"]),
        "answers": _answer_review_rows(plan_payload),
        "cards": cards,
        "raw_artifacts": {
            "annotated_plan": "sample-01/annotated-teaching-plan.json",
            "prompt_system": "sample-01/prompt.system.md",
            "prompt_user": "sample-01/prompt.user.md",
            "output_schema": "sample-01/output-schema.json",
            "projection_audit": "sample-01/projection-audit.json",
        },
    }
    if len(cards) != 12 or audit["counts"]["teaching_material_count"] != 13:
        raise LessonAnnotatedTeachingReviewError(
            "lesson_annotated_teaching_review_cardinality_invalid"
        )
    if rubric_evaluation["coverage_rate"] != 1.0:
        raise LessonAnnotatedTeachingReviewError(
            "lesson_annotated_teaching_review_rubric_incomplete: "
            f"{rubric_evaluation['missing']}"
        )
    return LessonAnnotatedTeachingReviewArtifacts(
        snapshot=snapshot,
        projection=projection,
        output_schema=output_schema,
        prompt=prompt,
        audit=audit,
        review=review,
    )


def _review_cards(root_scope: Mapping[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    def append_step(
        step: Mapping[str, Any],
        *,
        scope_ref: str,
        goal_ref: str | None,
    ) -> None:
        materials = list(step.get("teaching_materials") or ())
        cards.append(
            {
                "anchor": f"step-{step['step_id']}",
                "step_id": str(step["step_id"]),
                "capability_id": str(step["capability_id"]),
                "owner": {
                    "scope_ref": scope_ref,
                    "goal_ref": goal_ref,
                },
                "intent": step.get("intent"),
                "inputs": dict(step.get("inputs") or {}),
                "execution": dict(step.get("execution") or {}),
                "teaching_materials": materials,
                "material_count": len(materials),
            }
        )

    def visit(scope: Mapping[str, Any]) -> None:
        scope_ref = str(scope["scope_ref"])
        for step in scope.get("steps", ()):
            append_step(step, scope_ref=scope_ref, goal_ref=None)
        for goal_ref, goal in (scope.get("goals") or {}).items():
            for step in goal.get("steps", ()):
                append_step(
                    step,
                    scope_ref=scope_ref,
                    goal_ref=str(goal_ref),
                )
        for child in scope.get("children", ()):
            visit(child)

    visit(root_scope)
    return cards


def _scope_tree(scope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope_ref": str(scope["scope_ref"]),
        "step_ids": [str(item["step_id"]) for item in scope.get("steps", ())],
        "goals": {
            str(goal_ref): [
                str(item["step_id"]) for item in goal.get("steps", ())
            ]
            for goal_ref, goal in (scope.get("goals") or {}).items()
        },
        "children": [_scope_tree(child) for child in scope.get("children", ())],
    }


def _answer_review_rows(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    goal_by_ref: dict[str, Mapping[str, Any]] = {}

    def visit(scope: Mapping[str, Any]) -> None:
        goal_by_ref.update(
            {
                str(goal_ref): goal
                for goal_ref, goal in (scope.get("goals") or {}).items()
            }
        )
        for child in scope.get("children", ()):
            visit(child)

    visit(plan["root_scope"])
    return [
        {
            "goal_ref": goal_ref,
            "required_answer": dict(goal_by_ref[goal_ref]["required_answer"]),
            "answer_from": dict(goal_by_ref[goal_ref]["answer_from"]),
            "verified_answer": dict(answer),
        }
        for goal_ref, answer in plan["answers"].items()
    ]


def _pseudo_lesson_for_rubric(
    *,
    problem_id: str,
    cards: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for card in cards:
        for index, material in enumerate(card["teaching_materials"]):
            steps.append(
                {
                    "id": f"b2-{card['step_id']}-{index + 1}",
                    "source_step_ids": [card["step_id"]],
                    "title": material["suggested_title"],
                    "nav_title": material["suggested_nav_title"],
                    "goal": material["suggested_goal"],
                    "derive": material["suggested_derive"],
                    "box": material["suggested_box"],
                }
            )
    return {"problem_id": problem_id, "steps": steps}


def render_annotated_teaching_review_html(
    artifacts: LessonAnnotatedTeachingReviewArtifacts,
) -> str:
    review = artifacts.review
    summary = review["summary"]
    cards = review["cards"]
    nav = "".join(
        f'<a href="#{escape(str(card["anchor"]))}">'
        f'<span>{escape(str(card["step_id"]))}</span>'
        f'<small>{escape(str(card["capability_id"]))}</small></a>'
        for card in cards
    )
    cards_html = "".join(_render_card(card) for card in cards)
    answers_html = "".join(
        "<article class=\"answer\">"
        f"<h3>{escape(str(item['goal_ref']))}</h3>"
        f"<pre>{_json_text(item)}</pre></article>"
        for item in review["answers"]
    )
    plan_payload = artifacts.projection.plan.to_payload()
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5B2 Annotated Teaching Review</title>
<style>
:root{{--bg:#f2efe8;--paper:#fffdf8;--ink:#182135;--muted:#667085;--line:#d7d0c3;--blue:#1d4ed8;--green:#047857;--nav:#172033}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif}}
header{{position:sticky;top:0;z-index:10;background:var(--nav);color:#fff;padding:16px 24px;display:flex;align-items:center;gap:22px;box-shadow:0 2px 12px #0003}}
header h1{{font-size:20px;margin:0}} .stats{{display:flex;gap:10px;flex-wrap:wrap}} .stat{{border:1px solid #ffffff2d;background:#ffffff12;border-radius:9px;padding:6px 10px}}
.tabs{{margin-left:auto;display:flex;gap:7px}} button{{border:1px solid #ffffff42;background:#ffffff12;color:white;border-radius:8px;padding:7px 10px;cursor:pointer}} button.active{{background:#fff;color:var(--nav)}}
.layout{{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:calc(100vh - 76px)}} aside{{position:sticky;top:76px;height:calc(100vh - 76px);overflow:auto;padding:16px 12px;background:#e9e4da;border-right:1px solid var(--line)}} aside a{{display:block;text-decoration:none;color:var(--ink);padding:7px 9px;border-radius:8px}} aside a:hover{{background:#fff}} aside span,aside small{{display:block}} aside small{{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
main{{padding:22px;min-width:0}} .panel[hidden]{{display:none}} .answers{{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;margin-bottom:20px}} .answer{{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:12px}} .answer h3{{margin:0 0 8px}}
.card{{background:var(--paper);border:1px solid var(--line);border-radius:15px;margin-bottom:22px;overflow:hidden;box-shadow:0 6px 20px #2631420c}} .card-head{{padding:16px 18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:16px}} .card h2{{margin:0;font-size:18px}} .meta{{color:var(--muted)}} .count{{color:var(--green);font-weight:700}}
.columns{{display:grid;grid-template-columns:repeat(3,minmax(300px,1fr));overflow-x:auto}} .column{{padding:15px;border-right:1px solid var(--line);min-width:300px}} .column:last-child{{border:0}} .column h3{{font-size:12px;letter-spacing:.08em;color:var(--muted);text-transform:uppercase;margin:0 0 10px}}
pre{{margin:0;white-space:pre-wrap;word-break:break-word;background:#f4f2ed;border-radius:9px;padding:11px;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}} .material{{border-left:3px solid var(--green);padding-left:12px;margin:0 0 17px}} .material h4{{font-size:16px;margin:0}} .material .nav{{font-size:12px;color:var(--muted)}} .material ol{{padding-left:20px}} .box{{background:#ecfdf5;color:#065f46;border-radius:7px;padding:7px 9px;margin-top:6px}}
.raw{{max-width:1500px;margin:auto}} .raw h2{{margin-top:0}} .raw pre{{background:var(--paper);border:1px solid var(--line);max-height:none}}
@media(max-width:1100px){{header{{position:static;flex-wrap:wrap}} .tabs{{margin-left:0}} .layout{{grid-template-columns:1fr}} aside{{position:static;height:auto}} .columns{{grid-template-columns:1fr}} .column{{border-right:0;border-bottom:1px solid var(--line)}} .answers{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<header><h1>F5-F5B2 Annotated Teaching Review</h1><div class="stats">
<div class="stat">{summary['scope_count']} 个 Scope</div><div class="stat">{summary['step_count']} 个 Step</div>
<div class="stat">{summary['teaching_material_count']} 份材料</div><div class="stat">Rubric {len(summary['rubric_coverage']['covered'])}/5</div>
<div class="stat">Prompt {summary['prompt_chars']['total']:,} chars</div></div>
<div class="tabs"><button class="active" data-tab="cards">逐步审阅</button><button data-tab="plan">Raw Plan</button><button data-tab="prompt">Actual Prompt</button><button data-tab="schema">Schema / Audit</button></div></header>
<div class="layout"><aside>{nav}</aside><main>
<section class="panel" data-panel="cards"><div class="answers">{answers_html}</div>{cards_html}</section>
<section class="panel raw" data-panel="plan" hidden><h2>annotated-teaching-plan.json</h2><pre>{_json_text(plan_payload)}</pre></section>
<section class="panel raw" data-panel="prompt" hidden><h2>prompt.system.md</h2><pre>{escape(artifacts.prompt.system)}</pre><h2>prompt.user.md</h2><pre>{escape(artifacts.prompt.user)}</pre></section>
<section class="panel raw" data-panel="schema" hidden><h2>output-schema.json</h2><pre>{_json_text(artifacts.output_schema)}</pre><h2>projection-audit.json</h2><pre>{_json_text(artifacts.audit)}</pre></section>
</main></div>
<script>for(const b of document.querySelectorAll('[data-tab]')){{b.onclick=()=>{{document.querySelectorAll('[data-tab]').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('[data-panel]').forEach(p=>p.hidden=p.dataset.panel!==b.dataset.tab)}}}}</script>
</body></html>"""


def _render_card(card: Mapping[str, Any]) -> str:
    materials = "".join(
        _render_material(material, index=index)
        for index, material in enumerate(card["teaching_materials"], start=1)
    )
    owner = card["owner"]
    return f"""<article class="card" id="{escape(str(card['anchor']))}">
<div class="card-head"><div><h2>{escape(str(card['step_id']))}</h2><div class="meta">{escape(str(owner['scope_ref']))} / {escape(str(owner['goal_ref'] or 'scope-owned'))} · {escape(str(card['capability_id']))}</div><div>{escape(str(card['intent'] or ''))}</div></div><div class="count">{card['material_count']} 份材料</div></div>
<div class="columns"><section class="column"><h3>1 · Exact Inputs</h3><pre>{_json_text(card['inputs'])}</pre></section>
<section class="column"><h3>2 · Verified Execution</h3><pre>{_json_text(card['execution'])}</pre></section>
<section class="column"><h3>3 · LLM-facing Teaching Materials</h3>{materials}</section></div></article>"""


def _render_material(material: Mapping[str, Any], *, index: int) -> str:
    derive = "".join(
        f"<li><strong>{escape(str(item[0]))}</strong> {escape(str(item[1]))}</li>"
        for item in material["suggested_derive"]
    )
    boxes = "".join(
        f'<div class="box">{escape(str(item))}</div>'
        for item in material["suggested_box"]
    )
    return f"""<div class="material"><div class="nav">Material {index} · {escape(str(material['suggested_nav_title']))}</div><h4>{escape(str(material['suggested_title']))}</h4><p>{escape(str(material['suggested_goal']))}</p><ol>{derive}</ol>{boxes}</div>"""


def _json_text(value: Any) -> str:
    return escape(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False))


def write_annotated_teaching_review(
    artifacts: LessonAnnotatedTeachingReviewArtifacts,
    *,
    output_dir: Path,
) -> None:
    if output_dir.exists():
        raise LessonAnnotatedTeachingReviewError(
            f"lesson_annotated_teaching_review_output_exists: {output_dir}"
        )
    sample_dir = output_dir / "sample-01"
    sample_dir.mkdir(parents=True)
    _write_json(sample_dir / "snapshot.json", artifacts.snapshot.to_payload())
    _write_json(
        sample_dir / "teaching-authority.json",
        artifacts.projection.authority,
    )
    _write_json(
        sample_dir / "annotated-teaching-plan.json",
        artifacts.projection.plan.to_payload(),
    )
    _write_json(sample_dir / "output-schema.json", artifacts.output_schema)
    (sample_dir / "prompt.system.md").write_text(
        artifacts.prompt.system + "\n",
        encoding="utf-8",
    )
    (sample_dir / "prompt.user.md").write_text(
        artifacts.prompt.user + "\n",
        encoding="utf-8",
    )
    _write_json(sample_dir / "projection-audit.json", artifacts.audit)
    _write_json(output_dir / "review.json", artifacts.review)
    (output_dir / "review.html").write_text(
        render_annotated_teaching_review_html(artifacts),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default=CASE_ID)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.case != CASE_ID:
        raise SystemExit(f"F5-F5B2 supports only --case {CASE_ID}")
    root = _repo_root()
    rubric_path = (
        root
        / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
        "heping_ermo_b0/rubric.json"
    )
    with tempfile.TemporaryDirectory(prefix="lesson-b2-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            args.case,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    artifacts = build_annotated_teaching_review(
        snapshot,
        rubric=load_teaching_rubric(rubric_path),
    )
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    write_annotated_teaching_review(artifacts, output_dir=output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                **dict(artifacts.review["summary"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_BATCH_ID",
    "LessonAnnotatedTeachingReviewArtifacts",
    "LessonAnnotatedTeachingReviewError",
    "REVIEW_SCHEMA",
    "build_annotated_teaching_review",
    "render_annotated_teaching_review_html",
    "write_annotated_teaching_review",
]
