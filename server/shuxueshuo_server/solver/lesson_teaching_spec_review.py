"""Generate the F5-F5B1 Heping Teaching Spec review artifact."""

from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

from shuxueshuo_server.solver.explanation.models import (
    ExplanationSnapshot,
    TeachingScope,
    iter_teaching_scopes,
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
from shuxueshuo_server.solver.lesson_authoring_support import (
    CASE_ID,
    DEFAULT_OUTPUT_ROOT,
    build_recorded_snapshot,
    evaluate_lesson_teaching,
    load_teaching_rubric,
)
from shuxueshuo_server.solver.runtime.macro_atomicity import (
    contains_private_path_projection_marker,
)


REVIEW_SCHEMA = "lesson-teaching-spec-review/v1"
DEFAULT_BATCH_ID = "f5-f5b1-heping-spec-review"


class LessonTeachingSpecReviewError(ValueError):
    """The review artifact cannot be built without hiding an inconsistency."""


def build_teaching_spec_review(
    snapshot: ExplanationSnapshot,
    *,
    baseline_snapshot: Mapping[str, Any],
    baseline_snapshot_path: str,
    rubric: Mapping[str, Any],
) -> dict[str, Any]:
    previous = _previous_steps(baseline_snapshot)
    sources = tuple(iter_teaching_sources(snapshot.root_scope))
    if tuple(previous) != tuple(source.source_step_id for source in sources):
        raise LessonTeachingSpecReviewError(
            "lesson_teaching_review_baseline_step_order_drift"
        )
    owners = teaching_source_owners(snapshot.root_scope)
    by_capability: dict[str, list[str]] = {}
    for source in sources:
        by_capability.setdefault(source.capability_id, []).append(
            source.source_step_id
        )

    binder = TeachingSpecBinder()
    cards: list[dict[str, Any]] = []
    pseudo_lesson_steps: list[dict[str, Any]] = []
    material_count = 0
    for source in sources:
        generic = binder.generic_spec_payload(source)
        bound = binder.bind_source(source, snapshot=snapshot)
        material_count += len(bound)
        suggestions = [item.to_payload() for item in bound]
        validation = _review_validation(
            source_payload=source.to_payload(),
            generic_spec=generic,
            bound_suggestions=suggestions,
        )
        scope_ref, goal_ref = owners[source.source_step_id]
        kind = str(generic["kind"])
        card = {
            "anchor": f"step-{source.source_step_id}",
            "step_id": source.source_step_id,
            "owner": {
                "scope_ref": scope_ref,
                "goal_ref": goal_ref,
            },
            "capability_id": source.capability_id,
            "kind": kind,
            "same_capability_occurrences": list(
                by_capability[source.capability_id]
            ),
            "previous_plan_step": previous[source.source_step_id],
            "verified_runtime": source.to_payload(),
            "generic_spec": generic,
            "bound_suggestions": suggestions,
            "validation": validation,
        }
        cards.append(card)
        for index, suggestion in enumerate(suggestions):
            pseudo_lesson_steps.append(
                {
                    "id": f"review-{source.source_step_id}-{index + 1}",
                    "source_step_ids": [source.source_step_id],
                    **suggestion,
                }
            )

    rubric_result = evaluate_lesson_teaching(
        {
            "problem_id": snapshot.problem_id,
            "steps": pseudo_lesson_steps,
        },
        rubric,
    )
    if material_count != 13 or len(cards) != 12:
        raise LessonTeachingSpecReviewError(
            "lesson_teaching_review_cardinality_invalid: "
            f"cards={len(cards)}, materials={material_count}"
        )
    if rubric_result["coverage_rate"] != 1.0:
        raise LessonTeachingSpecReviewError(
            "lesson_teaching_review_macro_rubric_incomplete: "
            f"missing={rubric_result['missing']}"
        )
    return {
        "schema_version": REVIEW_SCHEMA,
        "problem_id": snapshot.problem_id,
        "snapshot_schema_version": snapshot.schema_version,
        "canonical_plan_hash": snapshot.canonical_plan_hash,
        "baseline_snapshot_path": baseline_snapshot_path,
        "summary": {
            "scope_count": len(tuple(iter_teaching_scopes(snapshot.root_scope))),
            "step_card_count": len(cards),
            "teaching_material_count": material_count,
            "function_card_count": sum(
                item["kind"] == "function" for item in cards
            ),
            "macro_card_count": sum(item["kind"] == "macro" for item in cards),
            "unique_capability_count": len(by_capability),
            "rubric_coverage": rubric_result,
            "review_status": "awaiting_human_review",
        },
        "scope_tree": _scope_tree(snapshot.root_scope),
        "cards": cards,
    }


def _previous_steps(
    baseline_snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    if baseline_snapshot.get("schema_version") != "explanation-snapshot/v2":
        raise LessonTeachingSpecReviewError(
            "lesson_teaching_review_baseline_must_be_historical_v2"
        )
    result: dict[str, dict[str, Any]] = {}

    def visit_scope(scope: Mapping[str, Any]) -> None:
        for raw in scope.get("scope_steps", ()):
            remember(raw)
        goals = scope.get("goals") or {}
        if not isinstance(goals, Mapping):
            raise LessonTeachingSpecReviewError(
                "lesson_teaching_review_baseline_goals_invalid"
            )
        for goal in goals.values():
            if not isinstance(goal, Mapping):
                raise LessonTeachingSpecReviewError(
                    "lesson_teaching_review_baseline_goal_invalid"
                )
            for raw in goal.get("steps", ()):
                remember(raw)
        for child in scope.get("children", ()):
            if not isinstance(child, Mapping):
                raise LessonTeachingSpecReviewError(
                    "lesson_teaching_review_baseline_scope_invalid"
                )
            visit_scope(child)

    def remember(raw: Any) -> None:
        if not isinstance(raw, Mapping):
            raise LessonTeachingSpecReviewError(
                "lesson_teaching_review_baseline_step_invalid"
            )
        step_id = str(raw.get("source_step_id") or "")
        if not step_id or step_id in result:
            raise LessonTeachingSpecReviewError(
                "lesson_teaching_review_baseline_step_identity_invalid"
            )
        public_results = raw.get("public_results") or {}
        result[step_id] = {
            "step_id": step_id,
            "capability_id": str(raw.get("capability_id") or ""),
            "intent": raw.get("intent"),
            "args": raw.get("args") or {},
            "output_targets": raw.get("output_targets") or {},
            "return_contract": {
                str(name): str(item.get("runtime_type") or "")
                for name, item in public_results.items()
                if isinstance(item, Mapping)
            },
        }

    root = baseline_snapshot.get("root_scope")
    if not isinstance(root, Mapping):
        raise LessonTeachingSpecReviewError(
            "lesson_teaching_review_baseline_root_invalid"
        )
    visit_scope(root)
    return result


def _scope_tree(scope: TeachingScope) -> dict[str, Any]:
    return {
        "scope_ref": scope.scope_ref,
        "scope_step_ids": [item.source_step_id for item in scope.steps],
        "goals": {
            goal.goal_ref: [item.source_step_id for item in goal.steps]
            for goal in scope.goals
        },
        "children": [_scope_tree(item) for item in scope.children],
    }


def _review_validation(
    *,
    source_payload: Mapping[str, Any],
    generic_spec: Mapping[str, Any],
    bound_suggestions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    generic_text = json.dumps(generic_spec, ensure_ascii=False)
    bound_text = "\n".join(_string_leaves(bound_suggestions))
    issues: list[str] = []
    if "和平" in generic_text or "tj-2026" in generic_text:
        issues.append("problem_specific_text_in_generic_spec")
    if "{" in bound_text or "}" in bound_text:
        issues.append("unresolved_placeholder")
    if contains_private_path_projection_marker(source_payload) or (
        contains_private_path_projection_marker(bound_suggestions)
    ):
        issues.append("private_runtime_identity_leak")
    return {
        "status": "ready_for_review" if not issues else "invalid",
        "issues": issues,
        "unresolved_placeholders": [],
        "problem_specific_generic_text": "problem_specific_text_in_generic_spec"
        in issues,
        "private_identity_leak": "private_runtime_identity_leak" in issues,
    }


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [
            item
            for child in value.values()
            for item in _string_leaves(child)
        ]
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [item for child in value for item in _string_leaves(child)]
    return [value] if isinstance(value, str) else []


def render_teaching_spec_review_html(review: Mapping[str, Any]) -> str:
    summary = review["summary"]
    cards = review["cards"]
    nav = "".join(
        (
            f'<a href="#{escape(str(card["anchor"]))}" '
            f'data-kind="{escape(str(card["kind"]))}">'
            f'<span>{escape(str(card["step_id"]))}</span>'
            f'<small>{escape(str(card["capability_id"]))}</small></a>'
        )
        for card in cards
    )
    card_html = "".join(_render_card(card) for card in cards)
    rubric = summary["rubric_coverage"]
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5B1 Teaching Spec Review</title>
<style>
:root{{--bg:#f4f1ea;--paper:#fffdf8;--ink:#172033;--muted:#6b7280;--line:#d7d0c4;--blue:#1d4ed8;--green:#047857;--amber:#b45309}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,"PingFang SC",sans-serif}}
header{{position:sticky;top:0;z-index:5;background:#172033;color:white;padding:18px 28px;display:flex;gap:24px;align-items:center;box-shadow:0 2px 12px #0002}}
header h1{{font-size:20px;margin:0}} .stats{{display:flex;gap:14px;flex-wrap:wrap}} .stat{{background:#ffffff18;border:1px solid #ffffff2c;border-radius:10px;padding:7px 11px}}
.layout{{display:grid;grid-template-columns:270px minmax(0,1fr);min-height:100vh}} aside{{padding:20px 14px;border-right:1px solid var(--line);background:#ebe6dc;position:sticky;top:80px;height:calc(100vh - 80px);overflow:auto}}
.filters{{display:flex;gap:6px;margin-bottom:12px}} button{{border:1px solid #b8b0a2;background:white;border-radius:999px;padding:5px 9px;cursor:pointer}} button.active{{background:#172033;color:white}}
aside a{{display:block;color:var(--ink);text-decoration:none;padding:8px;border-radius:8px;margin:3px 0}} aside a:hover{{background:#fff}} aside span,aside small{{display:block}} aside small{{color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
main{{padding:24px;min-width:0}} .card{{background:var(--paper);border:1px solid var(--line);border-radius:16px;margin:0 0 26px;box-shadow:0 7px 22px #2631420d;overflow:hidden}}
.card-head{{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:16px;align-items:flex-start}} .card h2{{font-size:18px;margin:0 0 3px}} .meta{{color:var(--muted)}} .badge{{display:inline-block;border-radius:999px;padding:4px 9px;font-weight:700;background:#dbeafe;color:#1e40af}} .badge.macro{{background:#fef3c7;color:#92400e}}
.repeat{{margin-top:8px;font-size:12px}} .repeat a{{color:var(--blue)}} .columns{{display:grid;grid-template-columns:repeat(4,minmax(270px,1fr));gap:0;overflow-x:auto}} .column{{padding:16px;border-right:1px solid var(--line);min-width:270px}} .column:last-child{{border:0}} .column h3{{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 12px}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f5f3ee;border-radius:10px;padding:12px;margin:0;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}}
.suggestion{{border-left:3px solid var(--green);padding:2px 0 2px 12px;margin-bottom:18px}} .suggestion h4{{margin:0 0 2px;font-size:16px}} .suggestion .nav-title{{color:var(--muted);font-size:12px}} .suggestion p{{margin:8px 0}} .derive{{margin:8px 0 8px 22px;padding:0}} .derive li{{margin:5px 0}} .box{{background:#ecfdf5;color:#065f46;border-radius:8px;padding:8px 10px;margin-top:8px}}
.status{{font-weight:700;color:var(--green)}}
@media(max-width:1300px){{.columns{{grid-template-columns:repeat(2,minmax(0,1fr));overflow:visible}} .column:nth-child(2){{border-right:0}} .column:nth-child(-n+2){{border-bottom:1px solid var(--line)}}}}
@media(max-width:900px){{.layout{{grid-template-columns:1fr}} aside{{position:static;height:auto;border-right:0}} header{{position:static}} .columns{{grid-template-columns:1fr}} .column{{border-right:0;border-bottom:1px solid var(--line)}} .column:last-child{{border-bottom:0}}}}
</style></head><body>
<header><h1>F5-F5B1 Teaching Spec Review</h1><div class="stats">
<div class="stat">12 个 Plan Step 卡片</div><div class="stat">13 份教学材料</div>
<div class="stat">Rubric {len(rubric["covered"])}/5</div><div class="stat">状态：等待人工审阅</div></div></header>
<div class="layout"><aside><div class="filters"><button class="active" data-filter="all">全部</button><button data-filter="function">Function</button><button data-filter="macro">Macro</button></div>{nav}</aside><main>{card_html}</main></div>
<script>
for(const b of document.querySelectorAll('button[data-filter]')){{b.onclick=()=>{{document.querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');const f=b.dataset.filter;document.querySelectorAll('.card').forEach(c=>c.hidden=f!=='all'&&c.dataset.kind!==f);document.querySelectorAll('aside a').forEach(a=>a.hidden=f!=='all'&&a.dataset.kind!==f)}}}}
</script></body></html>"""


def _render_card(card: Mapping[str, Any]) -> str:
    occurrences = card["same_capability_occurrences"]
    repeat = " · ".join(
        f'<a href="#step-{escape(str(item))}">{escape(str(item))}</a>'
        for item in occurrences
    )
    suggestions = "".join(
        _render_suggestion(item, step_id=str(card["step_id"]))
        for item in card["bound_suggestions"]
    )
    return f"""<article class="card" id="{escape(str(card['anchor']))}" data-kind="{escape(str(card['kind']))}">
<div class="card-head"><div><h2>{escape(str(card['step_id']))}</h2><div class="meta">{escape(str(card['owner']['scope_ref']))} / {escape(str(card['owner']['goal_ref'] or 'scope-owned'))} · {escape(str(card['capability_id']))}</div><div class="repeat">同 capability 对照：{repeat}</div></div><span class="badge {escape(str(card['kind']))}">{escape(str(card['kind']))}</span></div>
<div class="columns"><section class="column"><h3>1 · B0 Previous Plan Step</h3>{_json_pre(card['previous_plan_step'])}</section>
<section class="column"><h3>2 · B1 Verified Runtime</h3>{_json_pre(card['verified_runtime'])}</section>
<section class="column"><h3>3 · Generic Spec</h3>{_json_pre(card['generic_spec'])}</section>
<section class="column"><h3>4 · Bound Suggestion</h3><div class="status">{escape(str(card['validation']['status']))}</div>{suggestions}</section></div></article>"""


def _render_suggestion(item: Mapping[str, Any], *, step_id: str) -> str:
    derive = "".join(
        f"<li><strong>{escape(str(pair[0]))}</strong> {escape(str(pair[1]))}</li>"
        for pair in item["derive"]
    )
    boxes = "".join(
        f'<div class="box">{escape(str(value))}</div>' for value in item["box"]
    )
    anchor = (
        "unit-"
        + step_id.replace("/", "--")
        + "--"
        + str(item["unit_key"]).replace("/", "--")
    )
    return f"""<div class="suggestion" id="{escape(anchor)}"><div class="nav-title">{escape(str(item['nav_title']))}</div><h4>{escape(str(item['title']))}</h4><p>{escape(str(item['goal']))}</p><ol class="derive">{derive}</ol>{boxes}</div>"""


def _json_pre(value: Any) -> str:
    return "<pre>" + escape(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)
    ) + "</pre>"


def write_teaching_spec_review(
    review: Mapping[str, Any],
    *,
    snapshot: ExplanationSnapshot,
    output_dir: Path,
) -> None:
    if output_dir.exists():
        raise LessonTeachingSpecReviewError(
            f"lesson_teaching_review_output_exists: {output_dir}"
        )
    output_dir.mkdir(parents=True)
    (output_dir / "snapshot.json").write_text(
        json.dumps(snapshot.to_payload(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "teaching-spec-review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "review.html").write_text(
        render_teaching_spec_review_html(review),
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default=CASE_ID)
    parser.add_argument("--baseline-snapshot", required=True)
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.case != CASE_ID:
        raise SystemExit(f"F5-F5B1 supports only --case {CASE_ID}")
    root = _repo_root()
    baseline_path = Path(args.baseline_snapshot)
    if not baseline_path.is_absolute():
        cwd_candidate = (Path.cwd() / baseline_path).resolve()
        baseline_path = (
            cwd_candidate
            if cwd_candidate.exists()
            else _resolve_repo_path(root, args.baseline_snapshot)
        )
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    rubric_path = baseline_path.with_name("rubric.json")
    rubric = load_teaching_rubric(rubric_path)
    with tempfile.TemporaryDirectory(prefix="lesson-b1-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            args.case,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    review = build_teaching_spec_review(
        snapshot,
        baseline_snapshot=baseline,
        baseline_snapshot_path=str(baseline_path.relative_to(root)),
        rubric=rubric,
    )
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    write_teaching_spec_review(review, snapshot=snapshot, output_dir=output_dir)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                **review["summary"],
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
    "LessonTeachingSpecReviewError",
    "REVIEW_SCHEMA",
    "build_teaching_spec_review",
    "render_teaching_spec_review_html",
    "write_teaching_spec_review",
]
