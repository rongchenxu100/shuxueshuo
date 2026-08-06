"""Static, deterministic human review packs for F2 observations."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageDraw, ImageOps

from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
from shuxueshuo_server.solver.extraction.observations import (
    Polygon,
    SourceObservation,
)


@dataclass(frozen=True)
class ObservationReviewCase:
    problem_id: str
    observation: SourceObservation
    context: ProblemExtractionContext
    page_images: Mapping[str, bytes]


def render_observation_review_pack(
    cases: Sequence[ObservationReviewCase],
    output_dir: str | Path,
) -> tuple[Path, ...]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index_rows = []
    for case in sorted(cases, key=lambda item: item.problem_id):
        before = case.context.to_payload()
        case_dir = target / case.problem_id
        overlay_dir = case_dir / "overlays"
        crop_dir = case_dir / "crops"
        overlay_dir.mkdir(parents=True, exist_ok=True)
        crop_dir.mkdir(parents=True, exist_ok=True)
        observation_path = case_dir / "source-observation.json"
        observation_path.write_text(
            json.dumps(case.observation.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(observation_path)
        overlay_paths = []
        for page in case.observation.pages:
            image_bytes = case.page_images[page.page_id]
            for layer in ("layout", "selection_ocr", "formula", "ink"):
                path = overlay_dir / f"{page.page_id}-{layer}.png"
                _render_overlay(case, page.page_id, image_bytes, layer, path)
                written.append(path)
                overlay_paths.append(path.relative_to(case_dir).as_posix())
        crop_paths = _copy_formula_crops(case, crop_dir)
        written.extend(crop_paths)
        summary = _review_summary(case, overlay_paths, crop_paths)
        summary_path = case_dir / "review-summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(summary_path)
        review_path = case_dir / "review.html"
        review_path.write_text(_review_html(case, summary), encoding="utf-8")
        written.append(review_path)
        index_rows.append(
            f'<li><a href="{html.escape(case.problem_id)}/review.html">{html.escape(case.problem_id)}</a> '
            f'({len(case.observation.text_spans)} spans, {len(case.observation.issues)} issues)</li>'
        )
        if case.context.to_payload() != before:
            raise RuntimeError("review rendering mutated ProblemExtractionContext")
    index = target / "index.html"
    index.write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>F2 source review</title>"
        "<style>body{font:15px system-ui;max-width:960px;margin:32px auto;line-height:1.5;color:#1d1d1f}"
        "li{margin:10px 0}code{background:#f3f4f6;padding:2px 5px}</style>"
        "<h1>F2 SourceObservation 人工审查</h1>"
        "<p>逐题检查区域、OCR、公式、笔迹/遮挡和 issues。页面顶部有审查清单，"
        "每个结果表紧跟对应 overlay；这一步不审查数学实体、事实或答案。</p><ul>"
        + "".join(index_rows)
        + "</ul>",
        encoding="utf-8",
    )
    written.append(index)
    return tuple(sorted(written))


def _render_overlay(
    case: ObservationReviewCase,
    page_id: str,
    image_bytes: bytes,
    layer: str,
    target: Path,
) -> None:
    image = ImageOps.exif_transpose(Image.open(BytesIO(image_bytes))).convert("RGB")
    if layer == "ink":
        image = _overlay_ink_mask(case, page_id, image)
    draw = ImageDraw.Draw(image, "RGBA")
    if layer == "layout":
        for region in case.context.selection.regions:
            if region.page_id == page_id:
                _draw_polygon(
                    draw,
                    region.polygon,
                    image.size,
                    (40, 90, 255, 230),
                    "selection",
                    width=5,
                )
        for item in case.observation.layout_blocks:
            if item.page_id == page_id:
                _draw_polygon(draw, item.polygon, image.size, (0, 150, 220, 190), item.kind)
        for proposal in case.observation.proposals:
            for proposal_page, polygon in zip(proposal.page_ids, proposal.polygons, strict=False):
                if proposal_page == page_id:
                    _draw_polygon(draw, polygon, image.size, (0, 180, 80, 220), f"Q{proposal.question_label}")
    elif layer == "selection_ocr":
        for region in case.context.selection.regions:
            if region.page_id == page_id:
                _draw_polygon(draw, region.polygon, image.size, (40, 90, 255, 230), "selection", width=5)
        for item in case.observation.text_spans:
            if item.page_id == page_id:
                color = {
                    "printed": (20, 160, 70, 190),
                    "handwritten": (230, 90, 20, 210),
                    "mixed": (220, 40, 160, 220),
                    "unknown": (120, 120, 120, 190),
                }[item.origin]
                _draw_polygon(draw, item.polygon, image.size, color, str(item.reading_order))
    elif layer == "formula":
        for item in case.observation.formulas:
            if item.page_id == page_id:
                _draw_polygon(draw, item.polygon, image.size, (150, 45, 220, 220), item.status, width=4)
    elif layer == "ink":
        for item in case.observation.ink_origins:
            if item.page_id == page_id and _polygon_bbox_area(item.polygon) <= 0.08:
                color = (240, 120, 0, 210) if item.origin == "handwritten" else (220, 30, 150, 210)
                _draw_polygon(draw, item.polygon, image.size, color, item.origin, width=4)
        for item in case.observation.occlusions:
            if item.page_id == page_id:
                _draw_polygon(draw, item.polygon, image.size, (200, 0, 0, 230), item.severity, width=6)
    image.save(target, format="PNG", optimize=False)


def _overlay_ink_mask(
    case: ObservationReviewCase,
    page_id: str,
    image: Image.Image,
) -> Image.Image:
    artifact_by_id = {item.artifact_id: item for item in case.context.state.artifacts}
    mask_ids = {
        item.mask_artifact_id
        for item in case.observation.ink_origins
        if item.page_id == page_id and item.mask_artifact_id is not None
    }
    result = image.convert("RGBA")
    for mask_id in sorted(mask_ids):
        artifact = artifact_by_id.get(mask_id)
        if artifact is None or artifact.locator is None:
            raise RuntimeError(f"handwriting mask artifact is unavailable: {mask_id}")
        content = Path(artifact.locator).read_bytes()
        if sha256(content).hexdigest() != artifact.sha256:
            raise RuntimeError("handwriting mask artifact hash mismatch")
        mask = Image.open(BytesIO(content)).convert("L")
        if mask.size != result.size:
            mask = mask.resize(result.size, Image.Resampling.NEAREST)
        alpha = mask.point(lambda value: 96 if value else 0)
        tint = Image.new("RGBA", result.size, (240, 120, 0, 0))
        tint.putalpha(alpha)
        result = Image.alpha_composite(result, tint)
    return result.convert("RGB")


def _polygon_bbox_area(polygon: Polygon) -> float:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def _draw_polygon(
    draw: ImageDraw.ImageDraw,
    polygon: Polygon,
    size: tuple[int, int],
    color: tuple[int, int, int, int],
    label: str,
    *,
    width: int = 3,
) -> None:
    points = [(round(x * size[0]), round(y * size[1])) for x, y in polygon]
    draw.line(points + [points[0]], fill=color, width=width)
    left = min(point[0] for point in points)
    top = min(point[1] for point in points)
    draw.rectangle((left, max(0, top - 16), left + max(36, len(label) * 7), top), fill=(255, 255, 255, 210))
    draw.text((left + 2, max(0, top - 15)), label, fill=color)


def _copy_formula_crops(case: ObservationReviewCase, crop_dir: Path) -> list[Path]:
    artifacts = {item.artifact_id: item for item in case.context.state.artifacts}
    written = []
    for formula in case.observation.formulas:
        if formula.crop_artifact_id is None:
            raise RuntimeError(
                f"formula {formula.observation_id} has no crop artifact"
            )
        artifact = artifacts.get(formula.crop_artifact_id)
        if artifact is None or artifact.locator is None:
            raise RuntimeError(
                f"formula crop artifact is unavailable: {formula.crop_artifact_id}"
            )
        content = Path(artifact.locator).read_bytes()
        if sha256(content).hexdigest() != artifact.sha256:
            raise RuntimeError("formula crop artifact hash mismatch")
        target = crop_dir / f"{formula.observation_id.rsplit(':', 1)[-1]}.png"
        target.write_bytes(content)
        written.append(target)
    return written


def _review_summary(
    case: ObservationReviewCase,
    overlays: Sequence[str],
    crop_paths: Sequence[Path],
) -> dict[str, object]:
    return {
        "problem_id": case.problem_id,
        "source_id": case.observation.source_id,
        "selection_id": case.observation.selection_id,
        "observation_hash": case.observation.observation_hash,
        "context_id": case.context.manifest.context_id,
        "counts": {
            "pages": len(case.observation.pages),
            "layout_blocks": len(case.observation.layout_blocks),
            "text_spans": len(case.observation.text_spans),
            "formulas": len(case.observation.formulas),
            "ink_origins": len(case.observation.ink_origins),
            "occlusions": len(case.observation.occlusions),
            "proposals": len(case.observation.proposals),
            "issues": len(case.observation.issues),
        },
        "origin_counts": {
            origin: sum(item.origin == origin for item in case.observation.spatial_observations)
            for origin in ("printed", "handwritten", "mixed", "unknown")
        },
        "issues": [item.to_payload() for item in case.observation.issues],
        "providers": [item.to_payload() for item in case.observation.providers],
        "overlays": list(overlays),
        "formula_crops": [item.name for item in crop_paths],
        "review_boundaries": {
            "included": ["geometry", "selection", "layout", "ocr", "formula", "origin", "occlusion"],
            "excluded": ["route", "scope", "entity", "fact", "goal", "ProblemIR"],
        },
        "human_review_checklist": [
            {
                "id": "region",
                "label": "目标题区域完整，未混入相邻题、页眉或页脚",
            },
            {
                "id": "ocr",
                "label": "所有印刷题面文字均被识别，逐行文本与图片一致",
            },
            {
                "id": "formula",
                "label": "公式 crop 属于印刷题面，LaTeX 与图片一致；非印刷公式被保守标记",
            },
            {
                "id": "ink",
                "label": "学生笔迹未被标为 printed，重叠与遮挡分类合理",
            },
            {
                "id": "issues",
                "label": "typed issues 与图片现状一致且没有未解释的 blocking issue",
            },
        ],
    }


def _formula_preview(value: str | None, *, limit: int = 320) -> str:
    if not value:
        return "unresolved"
    if len(value) <= limit:
        return value
    return value[:limit] + " ... [truncated; full output in source-observation.json]"


def _formula_issue_reason(
    case: ObservationReviewCase,
    formula_id: str,
) -> str | None:
    for issue in case.observation.issues:
        if issue.code != "extraction.formula_observation_unresolved":
            continue
        if issue.details.get("formula_observation_id") == formula_id:
            reason = issue.details.get("reason")
            return str(reason) if reason is not None else "provider_result_unresolved"
    return None


def _formula_result_html(
    case: ObservationReviewCase,
    formula: object,
) -> str:
    status = str(getattr(formula, "status"))
    latex = getattr(formula, "latex")
    if status == "recognized":
        return f"<code>{html.escape(_formula_preview(latex))}</code>"
    reason = _formula_issue_reason(case, str(getattr(formula, "observation_id")))
    raw = _formula_preview(latex, limit=160)
    details = ""
    if latex:
        details = (
            "<details><summary>查看已拒绝的模型原始输出</summary>"
            f"<code>{html.escape(raw)}</code></details>"
        )
    return (
        '<strong class="rejected">未采纳</strong>'
        f" · {html.escape(reason or 'unresolved')}"
        f"{details}"
    )


def _review_html(case: ObservationReviewCase, summary: Mapping[str, object]) -> str:
    overlay_paths = tuple(str(item) for item in summary["overlays"])  # type: ignore[index]

    def overlay_cards(layer: str) -> str:
        return "".join(
            f'<figure><a href="{html.escape(path)}"><img src="{html.escape(path)}"></a>'
            f'<figcaption>{html.escape(path)}</figcaption></figure>'
            for path in overlay_paths
            if path.endswith(f"-{layer}.png")
        )

    layout_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.page_id)}</td><td>{html.escape(item.kind)}</td>"
        f"<td>{item.confidence:.3f}</td><td>{html.escape(item.provider_label)}</td>"
        "</tr>"
        for item in case.observation.layout_blocks
    ) or '<tr><td colspan="4">none</td></tr>'
    proposal_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.question_label)}</td>"
        f"<td>{html.escape(', '.join(item.page_ids))}</td>"
        f"<td>{item.confidence:.3f}</td>"
        f"<td>{html.escape(', '.join(item.reason_codes))}</td>"
        f"<td>{str(item.requires_confirmation).lower()}</td>"
        "</tr>"
        for item in case.observation.proposals
    ) or '<tr><td colspan="5">none</td></tr>'
    text_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.page_id)}</td><td>{item.reading_order}</td>"
        f"<td>{html.escape(item.origin)}</td>"
        f"<td>{item.confidence:.3f}</td><td>{html.escape(item.text)}</td>"
        "</tr>"
        for item in case.observation.text_spans
        if item.observation_id in case.observation.selected_observation_ids
    ) or '<tr><td colspan="5">none</td></tr>'
    formula_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.page_id)}</td><td>{html.escape(item.origin)}</td>"
        f"<td>{html.escape(item.status)}</td><td>{item.confidence:.3f}</td>"
        f"<td><code>{html.escape(item.source_text_hint or 'layout formula block')}</code></td>"
        f"<td>{_formula_result_html(case, item)}</td>"
        "</tr>"
        for item in case.observation.formulas
    ) or '<tr><td colspan="6">none</td></tr>'
    crop_names = tuple(str(item) for item in summary["formula_crops"])  # type: ignore[index]
    formula_crop_cards = "".join(
        '<figure class="crop">'
        f'<a href="crops/{html.escape(crop_name)}"><img src="crops/{html.escape(crop_name)}"></a>'
        f"<figcaption>{html.escape(formula.origin)} · {html.escape(formula.status)} · "
        f"期望 <code>{html.escape(formula.source_text_hint or 'layout formula block')}</code> · "
        f"{_formula_result_html(case, formula)}</figcaption></figure>"
        for formula, crop_name in zip(
            case.observation.formulas,
            crop_names,
            strict=False,
        )
    ) or "<p>无公式 crop。</p>"
    ink_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.page_id)}</td><td>{html.escape(item.origin)}</td>"
        f"<td>{item.confidence:.3f}</td>"
        f"<td>{len(item.overlap_observation_ids)}</td>"
        "</tr>"
        for item in case.observation.ink_origins
    ) or '<tr><td colspan="4">none</td></tr>'
    occlusion_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.page_id)}</td><td>{html.escape(item.severity)}</td>"
        f"<td>{item.overlap_ratio:.3f}</td><td>{len(item.target_observation_ids)}</td>"
        "</tr>"
        for item in case.observation.occlusions
    ) or '<tr><td colspan="4">none</td></tr>'
    issue_rows = "".join(
        "<li><details>"
        f"<summary><code>{html.escape(item.code)}</code> "
        f"blocking={str(item.blocking).lower()} retryable={str(item.retryable).lower()}</summary>"
        f"<pre>{html.escape(json.dumps(item.to_payload(), ensure_ascii=False, indent=2, sort_keys=True))}</pre>"
        "</details></li>"
        for item in case.observation.issues
    ) or "<li>none</li>"
    checklist = "".join(
        f'<label><input type="checkbox"> {html.escape(str(item["label"]))}</label>'
        for item in summary["human_review_checklist"]  # type: ignore[index]
    )
    return f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(case.problem_id)} F2 review</title>
<style>
*{{box-sizing:border-box}}body{{font:14px system-ui;margin:0;color:#1d1d1f;background:#f7f8fa}}
main{{max-width:1440px;margin:0 auto;padding:24px}}h1,h2,h3{{letter-spacing:0}}
nav{{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #d8dbe2;padding:12px 24px}}
nav a{{margin-right:18px;color:#1856a5;text-decoration:none;font-weight:600}}
.meta{{display:grid;grid-template-columns:130px minmax(0,1fr);gap:6px;max-width:1100px}}
.checklist{{display:grid;gap:10px;background:#fff;border:1px solid #d8dbe2;padding:16px}}
.checklist label{{display:block}}section{{scroll-margin-top:64px;margin:24px 0;padding:20px;background:#fff;border:1px solid #d8dbe2}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}}
figure{{margin:0;border:1px solid #d8dbe2;padding:8px;background:#fff}}figure img{{display:block;width:100%;height:68vh;object-fit:contain;background:#f4f4f4}}
figure.crop img{{height:220px}}figcaption{{margin-top:6px;color:#555}}
.legend{{display:flex;flex-wrap:wrap;gap:12px;margin:10px 0}}.legend span{{padding:4px 8px;border:1px solid #ddd}}
.table-wrap{{max-height:68vh;overflow:auto;border:1px solid #ddd}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:#f1f3f5}}
code{{white-space:pre-wrap;overflow-wrap:anywhere}}pre{{white-space:pre-wrap;background:#f5f5f5;padding:10px}}
.rejected{{color:#a22}}details{{margin-top:5px}}
.boundary{{color:#666}}@media(max-width:700px){{main{{padding:12px}}nav{{padding:10px 12px}}figure img{{height:auto}}}}
</style>
<nav><a href="#checklist">签核清单</a><a href="#region">区域</a><a href="#ocr">OCR</a><a href="#formula">公式</a><a href="#ink">笔迹/遮挡</a><a href="#issues">Issues</a></nav>
<main><h1>{html.escape(case.problem_id)}</h1>
<div class="meta"><b>Observation</b><code>{case.observation.observation_hash}</code>
<b>Context</b><code>{case.context.manifest.context_id}</code>
<b>Selection</b><code>{case.observation.selection_id}</code></div>
<section id="checklist"><h2>人工签核清单</h2><div class="checklist">{checklist}</div>
<p>发现问题时记录：题目、层、page、OCR order 或 issue code。勾选仅用于本次浏览，不会修改 Context。</p></section>
<section id="region"><h2>1. 区域与版面</h2><p>确认蓝色 selection 和绿色题号 proposal 完整覆盖目标题，且未吞入相邻题、页眉或页脚。</p>
<div class="gallery">{overlay_cards("layout")}</div>
<h3>Layout blocks</h3><div class="table-wrap"><table><tr><th>page</th><th>kind</th><th>confidence</th><th>provider label</th></tr>{layout_rows}</table></div>
<h3>Problem proposals</h3><div class="table-wrap"><table><tr><th>question</th><th>pages</th><th>confidence</th><th>reasons</th><th>confirm</th></tr>{proposal_rows}</table></div></section>
<section id="ocr"><h2>2. 印刷 OCR</h2><p>图片框上的数字对应 reading order。逐行核对文字；绿色为 printed，橙色 handwritten，粉色 mixed，灰色 unknown。</p>
<div class="legend"><span>绿色 printed</span><span>橙色 handwritten</span><span>粉色 mixed</span><span>灰色 unknown</span></div>
<div class="gallery">{overlay_cards("selection_ocr")}</div>
<div class="table-wrap"><table><tr><th>page</th><th>order</th><th>origin</th><th>confidence</th><th>text</th></tr>{text_rows}</table></div></section>
<section id="formula"><h2>3. 公式 OCR</h2><p>先核对 crop 是否真的是印刷公式，再核对 LaTeX。mixed/handwritten/unknown 不应被当作已识别印刷公式。</p>
<div class="gallery">{overlay_cards("formula")}</div><h3>Formula crops</h3><div class="gallery">{formula_crop_cards}</div>
<div class="table-wrap"><table><tr><th>page</th><th>origin</th><th>status</th><th>confidence</th><th>期望印刷片段</th><th>结果</th></tr>{formula_rows}</table></div></section>
<section id="ink"><h2>4. 笔迹与遮挡</h2><p>半透明橙色像素是精确 ink mask；外框只标紧凑墨迹组件。确认学生书写没有被升级为 printed；红框只表示与题面文字的局部遮挡。</p>
<div class="gallery">{overlay_cards("ink")}</div>
<h3>Ink origins</h3><div class="table-wrap"><table><tr><th>page</th><th>origin</th><th>confidence</th><th>overlap count</th></tr>{ink_rows}</table></div>
<h3>Occlusions</h3><div class="table-wrap"><table><tr><th>page</th><th>severity</th><th>overlap</th><th>target count</th></tr>{occlusion_rows}</table></div></section>
<section id="issues"><h2>5. Typed issues</h2><ul>{issue_rows}</ul></section>
<p class="boundary">本页只审查 source observations，不审查 route、entity、fact、scope、goal 或 ProblemIR。</p></main>
"""
