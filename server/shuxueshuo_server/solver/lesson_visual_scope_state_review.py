"""Generate the F5-F5B4V recursive visual-state human review artifact."""

from __future__ import annotations

import argparse
import copy
from html import escape
import json
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

import sympy as sp

from shuxueshuo_server.solver.explanation import lesson_ir_from_payload
from shuxueshuo_server.solver.explanation.lesson_ir import LessonIR
from shuxueshuo_server.solver.explanation.models import ExplanationSnapshot
from shuxueshuo_server.solver.explanation.models import (
    explanation_snapshot_content_hash,
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
)
from shuxueshuo_server.solver.visual import (
    VisualStepBuilder,
    VisualStepIR,
    VisualStepIRValidator,
    forward_compile,
)
from shuxueshuo_server.solver.visual.viewport import SemanticViewportResolver


REVIEW_CONTRACT = "lesson-visual-scope-state-review/v1"
DEFAULT_BATCH_ID = "f5-f5b4v-heping-recursive-visual-review"


class LessonVisualScopeStateReviewError(ValueError):
    """The deterministic recursive visual review could not be built safely."""


def build_visual_scope_state_review(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
) -> tuple[VisualStepIR, Mapping[str, Any]]:
    visual_ir = VisualStepBuilder().build(snapshot=snapshot, lesson=lesson)
    VisualStepIRValidator().validate(visual_ir, lesson=lesson)
    visual_by_lesson = {step.lesson_step_id: step for step in visual_ir.steps}
    lesson_rows = list(lesson.steps)
    cards: list[dict[str, Any]] = []
    for row in lesson_rows:
        visual_step = visual_by_lesson[row.id]
        authority = visual_ir.state_authority["steps"][row.id]
        reasons = {
            str(item["visual_object_id"]): str(item["reason"])
            for item in authority.get("visible") or ()
        }
        cards.append(
            {
                "anchor": _anchor(row.id),
                "scope_ref": row.scope_id,
                "goal_ref": row.goal_ref,
                "lesson_step_id": row.id,
                "source_step_ids": list(row.source_step_ids),
                "title": row.title,
                "visual_mode": visual_step.visual_mode,
                "available_before": list(authority.get("available_before") or ()),
                "available_after": list(authority.get("available_after") or ()),
                "parameter_values_before": dict(
                    authority.get("parameter_values_before") or {}
                ),
                "parameter_values_after": dict(
                    authority.get("parameter_values_after") or {}
                ),
                "frames": [
                    _frame_review_payload(
                        frame,
                        visual_ir.geometry_registry,
                        reasons=reasons,
                    )
                    for frame in visual_step.frames
                ],
            }
        )

    checks = _heping_visual_checks(snapshot, lesson, visual_ir)
    review = {
        "schema_version": REVIEW_CONTRACT,
        "status": "awaiting_human_review",
        "human_review_approved": False,
        "hashes": {
            "snapshot": lesson.source_snapshot_hash,
            "lesson_ir": stable_hash(lesson.to_payload()),
            "visual_step_ir": stable_hash(visual_ir.to_payload()),
        },
        "counts": {
            "scope_count": len(visual_ir.traversal.scope_by_ref),
            "goal_count": len(visual_ir.traversal.goal_by_ref),
            "lesson_step_count": len(lesson_rows),
            "visual_step_count": len(visual_ir.steps),
            "visual_frame_count": sum(
                len(step.frames) for step in visual_ir.steps
            ),
        },
        "checks": checks,
        "scope_tree": _scope_tree(visual_ir.root_scope),
        "cards": cards,
    }
    expected_counts = {
        "scope_count": 5,
        "goal_count": 4,
        "lesson_step_count": 12,
        "visual_step_count": 12,
        "visual_frame_count": 12,
    }
    if review["counts"] != expected_counts:
        raise LessonVisualScopeStateReviewError(
            f"visual_scope_review_counts_invalid: {review['counts']}"
        )
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise LessonVisualScopeStateReviewError(
            f"visual_scope_review_gate_failed: {failed}"
        )
    return visual_ir, review


def _frame_review_payload(
    frame: Any,
    geometry: Mapping[str, Any],
    *,
    reasons: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "frame_id": frame.frame_id,
        "caption": frame.caption,
        "teaching_unit_keys": list(frame.teaching_unit_keys),
        "viewport": copy.deepcopy(frame.viewport),
        "local_parameters": copy.deepcopy(list(frame.local_parameters)),
        "objects": [
            {
                "visual_object_id": item.visual_object_id,
                "component": item.component,
                "display_label": item.display_label,
                "role": item.role,
                "state": item.state,
                "reason": reasons.get(item.visual_object_id, "current_visual_spec"),
                "geometry_refs": list(item.geometry_refs),
                "geometry": [
                    _geometry_review_value(geometry, ref)
                    for ref in item.geometry_refs
                ],
                "source_refs": copy.deepcopy(list(item.source_refs)),
            }
            for item in frame.objects
        ],
    }


def _geometry_review_value(geometry: Mapping[str, Any], ref: str) -> Any:
    point = (geometry.get("fixedPoints") or {}).get(ref)
    if point is None:
        point = (geometry.get("movingPoints") or {}).get(ref)
    if point is not None:
        return {
            "geometry_ref": ref,
            "kind": "point",
            "value": copy.deepcopy(point),
            "meta": copy.deepcopy((geometry.get("pointMeta") or {}).get(ref) or {}),
        }
    curve = next(
        (
            item
            for item in geometry.get("curves") or ()
            if isinstance(item, Mapping) and str(item.get("id") or "") == ref
        ),
        None,
    )
    return {
        "geometry_ref": ref,
        "kind": "curve" if curve is not None else "unknown",
        "value": copy.deepcopy(curve),
    }


def _heping_visual_checks(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    visual_ir: VisualStepIR,
) -> dict[str, bool]:
    source_to_visual: dict[str, list[Any]] = {}
    for lesson_row, visual_step in zip(lesson.steps, visual_ir.steps, strict=True):
        for source_step_id in lesson_row.source_step_ids:
            source_to_visual.setdefault(source_step_id, []).append(visual_step)

    def only_step(source_step_id: str) -> Any:
        rows = source_to_visual[source_step_id]
        if len(rows) != 1:
            raise LessonVisualScopeStateReviewError(
                "visual_scope_review_source_step_ambiguous: "
                f"{source_step_id}: {len(rows)}"
            )
        return rows[0]

    geometry = visual_ir.geometry_registry
    point_meta = geometry.get("pointMeta") or {}

    def labels(frame: Any) -> set[str]:
        return {
            str((point_meta.get(ref) or {}).get("label") or "")
            for item in frame.objects
            for ref in item.geometry_refs
            if ref in point_meta
        }

    first = only_step("derive_parabola_i").frames[0]
    vertex = only_step("derive_vertex_P_i").frames[0]
    square_step = only_step("derive_square_vertex_G_i")
    square = square_step.frames[0]
    candidate = only_step("solve_axis_point_candidates_i").frames[0]
    macro_frames = tuple(
        frame
        for visual_step in source_to_visual["derive_path_minimum_ii"]
        for frame in visual_step.frames
    )
    solve_parameter = only_step("solve_parameter_c_ii").frames[0]
    recover = only_step("recover_target_point_E_ii").frames[0]
    axis_points = {
        str(meta.get("scopeId") or ""): point_id
        for point_id, meta in point_meta.items()
        if isinstance(meta, Mapping)
        and meta.get("definition") == "axis_x_intercept"
    }
    ii_refs = {
        ref
        for visual_step in visual_ir.steps
        if visual_ir.traversal.owner_by_step_id[visual_step.lesson_step_id][0] == "ii"
        for frame in visual_step.frames
        for item in frame.objects
        for ref in item.geometry_refs
    }
    i_owned_refs = {
        point_id
        for point_id, meta in point_meta.items()
        if isinstance(meta, Mapping)
        and str(meta.get("scopeRoot") or "") == "i"
    }
    i2_refs = {
        ref
        for visual_step in visual_ir.steps
        if visual_ir.traversal.owner_by_step_id[visual_step.lesson_step_id][0] == "i_2"
        for frame in visual_step.frames
        for item in frame.objects
        for ref in item.geometry_refs
    }
    duplicate_lines = any(
        _frame_has_duplicate_lines(frame)
        for visual_step in visual_ir.steps
        for frame in visual_step.frames
    )
    all_points_in_view = all(
        _frame_finite_points_in_view(frame, geometry)
        for visual_step in visual_ir.steps
        for frame in visual_step.frames
    )
    return {
        "recursive_topology_preserved": _scope_tree(visual_ir.root_scope)
        == _lesson_scope_tree(lesson.root_scope),
        "lesson_steps_match_frames": len(visual_ir.steps) == len(lesson.steps)
        and sum(len(item.frames) for item in visual_ir.steps) == len(lesson.steps),
        "s1_no_m_or_k": not {"M", "K"}.intersection(labels(first)),
        "s2_uses_i_axis_intersection": axis_points.get("i")
        in {ref for item in vertex.objects for ref in item.geometry_refs},
        "m_i_and_m_ii_are_distinct": bool(axis_points.get("i"))
        and bool(axis_points.get("ii"))
        and axis_points["i"] != axis_points["ii"],
        "no_a1_heuristic_ids": "A1" not in point_meta
        and not any(
            re.fullmatch(r"[A-Za-z][0-9]+", str(key))
            for key in point_meta
        ),
        "prior_curve_vertex_imported_without_sibling_scene_leak": any(
            item.role == "curve_vertex"
            and any(
                str((point_meta.get(ref) or {}).get("label") or "") == "P"
                for ref in item.geometry_refs
            )
            and item.source_refs
            == ({"kind": "functional_step", "step_id": "derive_vertex_P_i"},)
            for item in square.objects
        ),
        "scope_i_does_not_leak_to_ii": not ii_refs.intersection(i_owned_refs),
        # A complete Frame may contain step-local proof helpers (projection
        # triangles, Q and right-angle marks) that intentionally disappear.
        # The next incremental Frame must retain exactly the objects published
        # by the recursive state authority, not every object rendered once.
        "candidate_frame_retains_square_and_focuses_two_candidates": set(
            visual_ir.state_authority["steps"][square_step.lesson_step_id][
                "available_after"
            ]
        ).issubset({item.visual_object_id for item in candidate.objects})
        and sum(
            1
            for item in candidate.objects
            if item.component == "Point"
            and item.display_label == "E"
            and item.state == "focus"
        )
        == 2,
        "macro_has_two_distinct_frames": len(macro_frames) == 2
        and macro_frames[0].teaching_unit_keys != macro_frames[1].teaching_unit_keys,
        "macro_reflection_excludes_square_helpers": not {
            "E",
            "K",
            "F",
            "H",
        }.intersection(labels(macro_frames[1])),
        "parameter_solution_retains_reflection_only": {
            item.component for item in solve_parameter.objects
        }.issuperset({"DashedLine", "DistanceMarker"})
        and not {"E", "K", "F", "H"}.intersection(labels(solve_parameter)),
        "parameter_solution_is_exact_without_slider": any(
            item.get("name") == "c"
            and item.get("mathematical_domain", {}).get("kind") == "exact"
            and item.get("controls") == []
            for item in solve_parameter.local_parameters
        ),
        "only_moving_point_parameter_has_slider": any(
            item.get("name") == "t" and item.get("controls")
            for item in square.local_parameters
        )
        and not any(
            item.get("name") == "c" and item.get("controls")
            for visual_step in visual_ir.steps
            for frame in visual_step.frames
            for item in frame.local_parameters
        ),
        "recovered_square_retains_goal_context": axis_points.get("ii")
        in {ref for item in recover.objects for ref in item.geometry_refs},
        "no_duplicate_lines_per_frame": not duplicate_lines,
        "all_finite_points_inside_viewport": all_points_in_view,
    }


def _frame_has_duplicate_lines(frame: Any) -> bool:
    seen: set[tuple[str, ...]] = set()
    for item in frame.objects:
        if item.component not in {"ColoredLine", "DashedLine"}:
            continue
        refs = tuple(sorted(item.geometry_refs[:2]))
        if refs in seen:
            return True
        seen.add(refs)
    return False


def _frame_finite_points_in_view(frame: Any, geometry: Mapping[str, Any]) -> bool:
    base_env = {
        str(item.get("name")): float(item.get("default_value"))
        for item in frame.local_parameters
        if item.get("name") and item.get("default_value") is not None
    }
    environments = [base_env]
    for parameter in frame.local_parameters:
        if not parameter.get("controls"):
            continue
        name = str(parameter.get("name") or "")
        window = parameter.get("display_window") or {}
        for value in (window.get("min"), window.get("max")):
            if name and isinstance(value, (int, float)):
                environments.append({**base_env, name: float(value)})
    viewport = frame.viewport
    attention_refs = SemanticViewportResolver().attention_geometry_refs(
        objects=frame.objects,
        geometry_spec=dict(geometry),
        local_parameters=frame.local_parameters,
    )
    for ref in attention_refs:
        pair = (geometry.get("fixedPoints") or {}).get(ref)
        if pair is None:
            pair = (geometry.get("movingPoints") or {}).get(ref)
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        for env in environments:
            try:
                values = [
                    float(
                        sp.N(
                            sp.sympify(str(value)).subs(
                                {
                                    sp.Symbol(name): number
                                    for name, number in env.items()
                                }
                            )
                        )
                    )
                    for value in pair
                ]
            except Exception:
                continue
            if not (
                float(viewport["minX"]) <= values[0] <= float(viewport["maxX"])
                and float(viewport["minY"]) <= values[1] <= float(viewport["maxY"])
            ):
                return False
    return True


def _scope_tree(scope: Any) -> dict[str, Any]:
    return {
        "scope_ref": scope.scope_ref,
        "steps": [item.lesson_step_id for item in scope.steps],
        "goals": {
            goal.goal_ref: [item.lesson_step_id for item in goal.steps]
            for goal in scope.goals
        },
        "children": [_scope_tree(child) for child in scope.children],
    }


def _lesson_scope_tree(scope: Any) -> dict[str, Any]:
    return {
        "scope_ref": scope.scope_ref,
        "steps": [item.lesson_step_id for item in scope.steps],
        "goals": {
            goal.goal_ref: [item.lesson_step_id for item in goal.steps]
            for goal in scope.goals
        },
        "children": [_lesson_scope_tree(child) for child in scope.children],
    }


def write_visual_scope_state_review(
    snapshot: ExplanationSnapshot,
    lesson: LessonIR,
    visual_ir: VisualStepIR,
    review: Mapping[str, Any],
    *,
    output_dir: Path,
) -> None:
    if output_dir.exists():
        raise LessonVisualScopeStateReviewError(
            f"visual_scope_review_output_exists: {output_dir}"
        )
    output_dir.mkdir(parents=True)
    compiled = forward_compile(visual_ir)
    lesson_data = copy.deepcopy(compiled.lesson_data)
    lesson_data.setdefault("meta", {})["outputPath"] = str(output_dir / "lesson.html")
    _write_json(output_dir / "snapshot.json", snapshot.to_payload())
    _write_json(output_dir / "lesson-ir.json", lesson.to_payload())
    _write_json(output_dir / "visual-step-ir.json", visual_ir.to_payload())
    _write_json(output_dir / "visual-state-authority.json", visual_ir.state_authority)
    _write_json(output_dir / "geometry-spec.json", compiled.geometry_spec)
    _write_json(output_dir / "step-decorations.json", compiled.step_decorations)
    _write_json(output_dir / "lesson-data.json", lesson_data)
    _write_json(output_dir / "review.json", review)
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
    (output_dir / "review.html").write_text(
        _render_review_html(review),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _render_review_html(review: Mapping[str, Any]) -> str:
    nav = "".join(
        f'<a href="#{escape(str(card["anchor"]))}">{escape(str(card["title"]))}</a>'
        for card in review["cards"]
    )
    cards = "".join(_render_card(card) for card in review["cards"])
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>F5-F5B4V Recursive Visual State Review</title><style>
:root{{--ink:#172033;--muted:#667085;--line:#d9dde6;--paper:#f5f2e9;--panel:#fff;--focus:#0b63ce;--context:#6b7280;--ok:#087b5b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{position:sticky;top:0;z-index:3;background:#142039;color:#fff;padding:14px 22px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}}header h1{{font-size:20px;margin:0 14px 0 0}}.badge{{border:1px solid #647493;border-radius:9px;padding:5px 9px}}
.layout{{display:grid;grid-template-columns:245px minmax(0,1fr);max-width:1700px;margin:auto}}nav{{position:sticky;top:68px;height:calc(100vh - 68px);overflow:auto;padding:18px;border-right:1px solid var(--line)}}nav a{{display:block;padding:5px;color:var(--ink);text-decoration:none}}main{{padding:20px}}.panel,.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:18px;overflow:hidden}}.panel{{padding:18px}}.card h2{{margin:0;padding:15px 18px;border-bottom:1px solid var(--line);font-size:18px}}.meta{{font-size:12px;color:var(--muted)}}
.frame{{padding:17px}}.frame+.frame{{border-top:4px solid #e9edf4}}.params{{background:#f4f7fb;border-radius:8px;padding:9px;margin:8px 0}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:7px;border-bottom:1px solid #e5e7eb;text-align:left;vertical-align:top}}code{{word-break:break-all}}.focus{{color:var(--focus);font-weight:700}}.context{{color:var(--context)}}pre{{white-space:pre-wrap;word-break:break-word;background:#f6f6f3;border-radius:8px;padding:12px;max-height:650px;overflow:auto}}iframe{{width:100%;height:850px;border:1px solid var(--line);border-radius:10px}}
@media(max-width:900px){{.layout{{display:block}}nav{{position:static;height:auto;border:0}}}}
</style></head><body><header><h1>F5-F5B4V Recursive Visual State Review</h1>
<span class="badge">{escape(str(review["counts"]["lesson_step_count"]))} LessonStep / {escape(str(review["counts"]["visual_frame_count"]))} Frame</span><span class="badge">递归 Scope 状态</span><span class="badge">等待人工审阅</span></header>
<div class="layout"><nav><strong>步骤导航</strong>{nav}</nav><main>
<section class="panel"><h2>自动门禁</h2><pre>{escape(json.dumps({"counts":review["counts"],"checks":review["checks"],"hashes":review["hashes"]},ensure_ascii=False,indent=2))}</pre></section>
{cards}<section class="panel"><h2>实际课程页面</h2><p><a href="lesson.html">在新页面打开</a></p><iframe src="lesson.html"></iframe></section>
<section class="panel"><h2>递归 Scope 树</h2><pre>{escape(json.dumps(review["scope_tree"],ensure_ascii=False,indent=2))}</pre></section>
</main></div></body></html>"""


def _render_card(card: Mapping[str, Any]) -> str:
    frames = "".join(_render_frame(frame) for frame in card["frames"])
    return f"""<article class="card" id="{escape(str(card['anchor']))}"><h2>{escape(str(card['title']))}
<div class="meta">{escape(str(card['scope_ref']))}{' / '+escape(str(card['goal_ref'])) if card.get('goal_ref') else ''} · {escape(str(card['lesson_step_id']))} · {escape(str(card['visual_mode']))}</div></h2>
<div class="frame"><div class="meta">source: {escape(', '.join(card['source_step_ids']))}</div>
<div class="params">available before {len(card['available_before'])} → after {len(card['available_after'])}<br>parameter before {escape(json.dumps(card['parameter_values_before'],ensure_ascii=False))} → after {escape(json.dumps(card['parameter_values_after'],ensure_ascii=False))}</div></div>{frames}</article>"""


def _render_frame(frame: Mapping[str, Any]) -> str:
    parameters = "；".join(
        f"{item['name']}={item['default_value']} ({item['mathematical_domain']['kind']}, controls={len(item['controls'])})"
        for item in frame["local_parameters"]
    ) or "无"
    rows = "".join(
        "<tr>"
        f'<td class="{escape(str(item["state"]))}">{escape(str(item["state"]))}</td>'
        f'<td>{escape(str(item["component"]))}</td>'
        f'<td>{escape(str(item.get("display_label") or ""))}</td>'
        f'<td><code>{escape(", ".join(item["geometry_refs"]))}</code></td>'
        f'<td>{escape(str(item["reason"]))}</td>'
        "</tr>"
        for item in frame["objects"]
    )
    return f"""<section class="frame"><h3>{escape(str(frame.get('caption') or frame['frame_id']))}</h3>
<div class="meta">unit: {escape(', '.join(frame['teaching_unit_keys']))}</div><div class="params">局部参数：{escape(parameters)}<br>viewport: {escape(json.dumps(frame['viewport'],ensure_ascii=False))}</div>
<table><thead><tr><th>状态</th><th>组件</th><th>标签</th><th>geometry refs</th><th>可见原因</th></tr></thead><tbody>{rows}</tbody></table>
<details><summary>完整 Frame 数据</summary><pre>{escape(json.dumps(frame,ensure_ascii=False,indent=2))}</pre></details></section>"""


def _anchor(value: str) -> str:
    return "visual-" + "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in value
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default=CASE_ID)
    parser.add_argument(
        "--lesson-ir",
        default=(
            "internal/solver-runs/explanation-builder-deepseek-scope-vnext/"
            "f5-f5b4-heping-recursive-lesson-review/approved/lesson-ir.json"
        ),
    )
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    return parser


def _resolve_cli_input(repo_root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    cwd_candidate = (Path.cwd() / path).resolve()
    return cwd_candidate if cwd_candidate.exists() else (repo_root / path).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.case != CASE_ID:
        raise SystemExit(f"F5-F5B4V supports only --case {CASE_ID}")
    root = _repo_root()
    lesson_path = _resolve_cli_input(root, args.lesson_ir)
    lesson = lesson_ir_from_payload(json.loads(lesson_path.read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory(prefix="lesson-b4v-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            args.case,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    if lesson.source_snapshot_hash != explanation_snapshot_content_hash(snapshot):
        raise LessonVisualScopeStateReviewError(
            "visual_scope_review_snapshot_hash_mismatch"
        )
    visual_ir, review = build_visual_scope_state_review(snapshot, lesson)
    output_dir = _resolve_repo_path(root, args.output_root) / args.batch_id
    write_visual_scope_state_review(
        snapshot,
        lesson,
        visual_ir,
        review,
        output_dir=output_dir,
    )
    print(
        json.dumps(
            {
                "output_dir": str(output_dir),
                "review_html": str(output_dir / "review.html"),
                **review["counts"],
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
    "DEFAULT_BATCH_ID",
    "LessonVisualScopeStateReviewError",
    "REVIEW_CONTRACT",
    "build_visual_scope_state_review",
    "write_visual_scope_state_review",
]
