"""Planner-style debug artifacts and visual review for F3 attempts."""

from __future__ import annotations

import html
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw

from shuxueshuo_server.solver.extraction.f3_attempt import (
    F3ExtractionAttemptResult,
)
from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    ExtractionArtifactReader,
)
from shuxueshuo_server.solver.runtime.llm_debug import (
    contains_secret_or_data_url,
    write_common_llm_attempt,
    write_debug_json,
)


class F3AttemptDebugWriter:
    def write(
        self,
        result: F3ExtractionAttemptResult,
        directory: str | Path,
        *,
        attempt_index: int,
        input_artifact_reader: ExtractionArtifactReader,
    ) -> tuple[Path, ...]:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        prefix = f"attempt-{attempt_index}"
        request_payload = result.request.redacted_payload()
        if contains_secret_or_data_url(request_payload):
            raise RuntimeError("F3 debug request contains a secret or image data URL")
        metadata = _metadata_payload(result)
        write_common_llm_attempt(
            target,
            prefix=prefix,
            system_prompt=result.request.prompt.system,
            user_prompt=result.request.prompt.user_debug,
            prompt_payload=request_payload,
            raw_response=(
                result.provider_response.text
                if result.provider_response is not None
                else ""
            ),
            metadata=metadata,
        )
        write_debug_json(
            target / f"{prefix}.payload.evidence-pack.json",
            result.evidence_pack.to_payload(),
        )
        write_debug_json(
            target / f"{prefix}.payload.region-index.json",
            result.evidence_pack.prompt_payload()["region_index"],
        )
        image_manifest = [item.redacted_payload() for item in result.request.images]
        write_debug_json(
            target / f"{prefix}.input-manifest.json",
            {"images": image_manifest, "full_question_image_rate": 1.0},
        )
        write_debug_json(
            target / f"{prefix}.provider-request.redacted.json",
            request_payload,
        )
        write_debug_json(
            target / f"{prefix}.provider-response.json",
            (
                dict(result.provider_response.raw_payload)
                if result.provider_response is not None
                else None
            ),
        )
        write_debug_json(
            target / f"{prefix}.candidate-patch.json",
            (
                {
                    "patch_id": result.candidate_patch.patch_id,
                    "candidate_patch": result.candidate_patch.to_payload(),
                }
                if result.candidate_patch is not None
                else None
            ),
        )
        write_debug_json(
            target / f"{prefix}.contract-validation.json",
            result.validation_report.to_payload(),
        )
        write_debug_json(
            target / f"{prefix}.attempt-ledger.json",
            {
                "base_context_id": result.attempt_ledger.base_context_id,
                "attempts": [
                    item.authority_payload()
                    for item in result.attempt_ledger.attempts
                ],
            },
        )
        write_debug_json(
            target / f"{prefix}.context-before.json",
            result.context.to_payload(),
        )
        write_debug_json(
            target / f"{prefix}.structured-error.json",
            result.structured_error,
        )
        provider_attempts = (
            result.provider_response.provider_attempts
            if result.provider_response is not None
            else ()
        )
        if not provider_attempts:
            provider_attempts = tuple(
                _subattempt_from_payload(item)
                for item in result.attempt.usage.get("provider_attempts", ())
                if isinstance(item, Mapping)
            )
        for item in provider_attempts:
            write_debug_json(
                target
                / f"{prefix}.provider-attempt-{item['provider_attempt'] if isinstance(item, Mapping) else item.provider_attempt}.json",
                item if isinstance(item, Mapping) else item.to_payload(),
            )
        image_paths, overlay_paths = _write_images(
            result,
            target,
            prefix,
            input_artifact_reader,
        )
        review_path = target / "review.html"
        review_path.write_text(
            _review_html(
                result,
                prefix,
                image_paths,
                overlay_paths,
            ),
            encoding="utf-8",
        )
        return tuple(sorted(target.iterdir()))


def _metadata_payload(result: F3ExtractionAttemptResult) -> dict[str, Any]:
    metadata = (
        result.provider_response.metadata_payload()
        if result.provider_response is not None
        else {
            "provider": result.attempt.provider,
            "request_model": result.attempt.usage.get("request_model"),
            "response_model": None,
            "usage": None,
            "provider_attempts": result.attempt.usage.get("provider_attempts", []),
            "latency_ms": result.attempt.latency_ms,
        }
    )
    metadata.update(
        {
            "attempt_id": result.attempt.attempt_id,
            "attempt_result": result.attempt.result,
            "extractor_contract": "problem-extraction-candidate-patch/v1",
            "evidence_pack_id": result.evidence_pack.evidence_pack_id,
            "image_count": len(result.request.images),
            "image_bytes": sum(len(item.content) for item in result.request.images),
            "image_hashes": [item.artifact.sha256 for item in result.request.images],
            "model_contract_clean": not result.validation_report.normalizations,
            "normalized_review_region_count": (
                result.validation_report.normalized_review_region_count
            ),
        }
    )
    return metadata


def _write_images(
    result: F3ExtractionAttemptResult,
    target: Path,
    prefix: str,
    reader: ExtractionArtifactReader,
) -> tuple[list[Path], list[Path]]:
    image_paths: list[Path] = []
    overlay_paths: list[Path] = []
    candidate_evidence = _candidate_evidence_map(result)
    for index, image_input in enumerate(result.evidence_pack.images, start=1):
        content = reader.read_bytes(image_input.artifact)
        image_path = target / f"{prefix}.input.page-{index:02d}.png"
        image_path.write_bytes(content)
        image_paths.append(image_path)
        image = Image.open(BytesIO(content)).convert("RGB")
        draw = ImageDraw.Draw(image, "RGBA")
        crop_bbox = _selection_bbox(result, image_input.page_id)
        for region in result.evidence_pack.region_index:
            if region.page_id != image_input.page_id:
                continue
            referenced_types = candidate_evidence.get(region.evidence_id, ())
            if (
                region.kind.startswith("visual_review_tile:")
                and not referenced_types
            ):
                continue
            points = _crop_points(region.polygon, crop_bbox, image.size)
            color = _candidate_color(referenced_types)
            draw.line(points + [points[0]], fill=color, width=3)
            label = ",".join(referenced_types) or region.kind
            draw.text(points[0], label[:48], fill=color)
        overlay_path = target / f"{prefix}.input-overlay.page-{index:02d}.png"
        image.save(overlay_path, format="PNG")
        overlay_paths.append(overlay_path)
    return image_paths, overlay_paths


def _selection_bbox(
    result: F3ExtractionAttemptResult,
    page_id: str,
) -> tuple[float, float, float, float]:
    regions = tuple(
        item for item in result.context.selection.regions if item.page_id == page_id
    )
    return (
        min(x for item in regions for x, _ in item.polygon),
        min(y for item in regions for _, y in item.polygon),
        max(x for item in regions for x, _ in item.polygon),
        max(y for item in regions for _, y in item.polygon),
    )


def _crop_points(
    polygon: tuple[tuple[float, float], ...],
    crop_bbox: tuple[float, float, float, float],
    size: tuple[int, int],
) -> list[tuple[int, int]]:
    left, top, right, bottom = crop_bbox
    width = max(right - left, 1e-9)
    height = max(bottom - top, 1e-9)
    return [
        (
            round((x - left) / width * size[0]),
            round((y - top) / height * size[1]),
        )
        for x, y in polygon
    ]


def _candidate_evidence_map(
    result: F3ExtractionAttemptResult,
) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {}
    if result.candidate_patch is None:
        return {}
    for candidate in result.candidate_patch.candidates:
        for evidence_id in candidate.evidence_refs:
            mapping.setdefault(evidence_id, []).append(candidate.candidate_type)
    return {key: tuple(sorted(set(value))) for key, value in mapping.items()}


def _candidate_color(types: tuple[str, ...]) -> tuple[int, int, int, int]:
    if "goal" in types:
        return (220, 45, 45, 230)
    if "fact" in types:
        return (125, 70, 190, 230)
    if "entity" in types:
        return (0, 135, 90, 230)
    if "scope" in types:
        return (25, 100, 220, 230)
    return (100, 100, 100, 170)


def _review_html(
    result: F3ExtractionAttemptResult,
    prefix: str,
    image_paths: list[Path],
    overlay_paths: list[Path],
) -> str:
    image_html = "".join(
        f'<figure><img src="{html.escape(path.name)}"><figcaption>{html.escape(path.name)}</figcaption></figure>'
        for path in image_paths
    )
    overlay_html = "".join(
        f'<figure><img src="{html.escape(path.name)}"><figcaption>{html.escape(path.name)}</figcaption></figure>'
        for path in overlay_paths
    )
    candidate_rows = ""
    if result.candidate_patch is not None:
        candidate_rows = "".join(
            "<tr>"
            f"<td>{html.escape(item.candidate_type)}</td>"
            f"<td><code>{html.escape(item.candidate_id)}</code></td>"
            f"<td>{html.escape(', '.join(item.evidence_refs))}</td>"
            f"<td><pre>{html.escape(json.dumps(item.to_payload()['payload'], ensure_ascii=False, indent=2))}</pre></td>"
            "</tr>"
            for item in result.candidate_patch.candidates
        )
    raw = result.provider_response.text if result.provider_response else ""
    validation = json.dumps(
        result.validation_report.to_payload(),
        ensure_ascii=False,
        indent=2,
    )
    metadata = json.dumps(_metadata_payload(result), ensure_ascii=False, indent=2)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>F3 attempt review</title>
<style>
body{{font:15px system-ui;max-width:1180px;margin:28px auto;line-height:1.5;color:#202124;padding:0 20px}}
nav a{{margin-right:18px}} section{{border-top:1px solid #d8dde5;padding:22px 0}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:16px}}
img{{max-width:100%;border:1px solid #bbc3cf}} table{{width:100%;border-collapse:collapse}}
th,td{{border:1px solid #d8dde5;padding:8px;vertical-align:top;text-align:left}} pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
.ok{{color:#08783e}} .bad{{color:#b42318}} code{{background:#f1f3f5;padding:2px 4px}}
</style></head><body>
<h1>F3 多模态提取审查</h1>
<p class="{'ok' if result.ok else 'bad'}">attempt={html.escape(result.attempt.attempt_id)} · result={html.escape(result.attempt.result)} · contract={'PASS' if result.validation_report.ok else 'FAIL'}</p>
<nav><a href="#input">实际输入</a><a href="#prompt">Prompt</a><a href="#response">响应</a><a href="#candidates">Candidates</a><a href="#validation">错误与用量</a></nav>
<section id="input"><h2>1. 实际发送的完整题目图</h2><div class="gallery">{image_html}</div>
<h3>Candidate / evidence overlay</h3><div class="gallery">{overlay_html}</div></section>
<section id="prompt"><h2>2. Prompt 与辅助观察</h2>
<h3>System</h3><pre>{html.escape(result.request.prompt.system)}</pre>
<h3>User</h3><pre>{html.escape(result.request.prompt.user_debug)}</pre></section>
<section id="response"><h2>3. Provider 原始响应</h2><pre>{html.escape(raw)}</pre></section>
<section id="candidates"><h2>4. Candidate → evidence</h2><table><thead><tr><th>type</th><th>id</th><th>evidence</th><th>payload</th></tr></thead><tbody>{candidate_rows}</tbody></table></section>
<section id="validation"><h2>5. Contract error 与调用元数据</h2><h3>Validation</h3><pre>{html.escape(validation)}</pre><h3>Metadata</h3><pre>{html.escape(metadata)}</pre></section>
<footer><code>{html.escape(prefix)}</code></footer></body></html>"""


def _subattempt_from_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return dict(payload)
