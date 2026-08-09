"""Human-readable debug artifacts for Problem domain extraction and repair."""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any, Mapping

from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MULTIMODAL_MAX_OUTPUT_TOKENS,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemRepairPatch,
)
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    ProblemDomainExtractionAttemptResult,
    ProblemDomainExtractionRunResult,
)
from shuxueshuo_server.solver.extraction.source_identity import thaw_json


class ProblemDomainDebugWriter:
    """Write one complete, redacted audit mirror without creating authority."""

    def write(
        self,
        result: ProblemDomainExtractionRunResult,
        output_dir: str | Path,
    ) -> Path:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        image_paths: dict[str, str] = {}
        previous_draft: ProblemDraft | None = None
        for attempt in result.attempts:
            prefix = f"attempt-{attempt.attempt_number}"
            _write_json(
                root / f"{prefix}.prompt.json",
                {
                    "system": attempt.request.prompt.system,
                    "user": attempt.request.prompt.user_debug,
                    "contract_schema": dict(attempt.request.contract_schema),
                    "response_format": dict(attempt.request.response_format),
                },
            )
            (root / f"{prefix}.prompt.system.md").write_text(
                attempt.request.prompt.system + "\n", encoding="utf-8"
            )
            (root / f"{prefix}.prompt.user.md").write_text(
                attempt.request.prompt.user_debug + "\n", encoding="utf-8"
            )
            _write_json(
                root / f"{prefix}.payload.evidence-pack.json",
                attempt.request.evidence_pack.prompt_payload(),
            )
            _write_json(
                root / f"{prefix}.provider-request.redacted.json",
                attempt.request.redacted_payload(),
            )
            _write_json(
                root / f"{prefix}.response-schema.json",
                {
                    "contract_version": attempt.request.contract_version,
                    "transport_response_format": dict(
                        attempt.request.response_format
                    ),
                    "schema": dict(attempt.request.contract_schema),
                },
            )
            for index, image in enumerate(attempt.request.images, start=1):
                suffix = ".png" if image.artifact.media_type == "image/png" else ".jpg"
                name = f"{prefix}.input-{index:02d}-{image.role}{suffix}"
                (root / name).write_bytes(image.content)
                image_paths[f"{prefix}:{index}"] = name
            self._write_provider_files(root, prefix, attempt)
            _write_json(
                root / f"{prefix}.problem-domain.json",
                (
                    attempt.resulting_draft.graph.wire_payload()
                    if attempt.resulting_draft is not None
                    else None
                ),
            )
            _write_json(
                root / f"{prefix}.problem-repair.json",
                attempt.patch.to_payload() if attempt.patch is not None else None,
            )
            _write_json(
                root / f"{prefix}.problem-draft.json",
                (
                    attempt.resulting_draft.to_payload()
                    if attempt.resulting_draft is not None
                    else None
                ),
            )
            _write_json(
                root / f"{prefix}.validation.json",
                attempt.report.to_payload(),
            )
            _write_json(
                root / f"{prefix}.repair-cone.json",
                _repair_cone_payload(attempt.resulting_draft),
            )
            _write_json(
                root / f"{prefix}.semantic-diff.json",
                _draft_diff(previous_draft, attempt.resulting_draft, attempt.patch),
            )
            _write_json(
                root / f"{prefix}.solver-projection.json",
                attempt.projection.to_payload() if attempt.projection is not None else None,
            )
            _write_json(
                root / f"{prefix}.attempt-ledger.json",
                attempt.attempt_record.authority_payload(),
            )
            _write_json(
                root / f"{prefix}.structured-error.json",
                dict(attempt.structured_error) if attempt.structured_error else None,
            )
            if attempt.resulting_draft is not None:
                previous_draft = attempt.resulting_draft

        _write_json(root / "context-before.json", result.base_context.to_payload())
        _write_json(root / "context-final.json", result.final_context.to_payload())
        _write_json(
            root / "verified-problem.json",
            (
                result.verified_problem.to_payload()
                if result.verified_problem is not None
                else None
            ),
        )
        _write_json(
            root / "solver-problem-ir.json",
            (
                result.solver_projection.to_payload()
                if result.solver_projection is not None
                else None
            ),
        )
        _write_json(root / "run-result.json", _run_payload(result))
        review = root / "review.html"
        review.write_text(_review_html(result, image_paths), encoding="utf-8")
        return review

    @staticmethod
    def _write_provider_files(
        root: Path,
        prefix: str,
        attempt: ProblemDomainExtractionAttemptResult,
    ) -> None:
        if attempt.provider_response is None:
            _write_json(root / f"{prefix}.provider-response.json", {})
            (root / f"{prefix}.raw-response.txt").write_text("", encoding="utf-8")
            _write_json(
                root / f"{prefix}.llm-metadata.json",
                _failed_provider_metadata(attempt),
            )
            return
        _write_json(
            root / f"{prefix}.provider-response.json",
            dict(attempt.provider_response.raw_payload),
        )
        (root / f"{prefix}.raw-response.txt").write_text(
            attempt.provider_response.text,
            encoding="utf-8",
        )
        _write_json(
            root / f"{prefix}.llm-metadata.json",
            attempt.provider_response.metadata_payload(),
        )


def _repair_cone_payload(draft: ProblemDraft | None) -> dict[str, Any] | None:
    if draft is None:
        return None
    return {
        "revision_id": draft.revision_id,
        "frozen_unit_ids": list(draft.frozen_unit_ids),
        "repairable_unit_ids": list(draft.repairable_unit_ids),
        "units": [
            {
                **draft.unit_registry[unit_id].to_payload(),
                "status": draft.verification_stamps[unit_id].status,
                "dependency_signatures": list(
                    draft.verification_stamps[unit_id].dependency_signatures
                ),
            }
            for unit_id in sorted(draft.verification_stamps)
        ],
        "issues": [item.to_payload() for item in draft.validation_report.issues],
    }


def _draft_diff(
    before: ProblemDraft | None,
    after: ProblemDraft | None,
    patch: ProblemRepairPatch | None,
) -> dict[str, Any]:
    before_units = before.unit_registry if before is not None else {}
    after_units = after.unit_registry if after is not None else {}
    changed = sorted(
        unit_id
        for unit_id in set(before_units).intersection(after_units)
        if before_units[unit_id].semantic_signature
        != after_units[unit_id].semantic_signature
    )
    return {
        "before_revision_id": before.revision_id if before is not None else None,
        "after_revision_id": after.revision_id if after is not None else None,
        "patch_id": patch.patch_id if patch is not None else None,
        "added_unit_ids": sorted(set(after_units) - set(before_units)),
        "removed_unit_ids": sorted(set(before_units) - set(after_units)),
        "changed_unit_ids": changed,
    }


def _failed_provider_metadata(
    attempt: ProblemDomainExtractionAttemptResult,
) -> dict[str, Any]:
    usage = dict(attempt.attempt_record.usage)
    provider_attempts = usage.get("provider_attempts")
    return {
        "provider": attempt.attempt_record.provider,
        "request_model": usage.get("request_model"),
        "response_model": None,
        "usage": None,
        "finish_reason": None,
        "thinking_mode": attempt.request.thinking_mode,
        "reasoning_effort": attempt.request.reasoning_effort,
        "response_format": attempt.request.contract_version,
        "temperature": 0,
        "max_output_tokens": MULTIMODAL_MAX_OUTPUT_TOKENS,
        "provider_attempts": (
            thaw_json(provider_attempts)
            if isinstance(provider_attempts, (list, tuple))
            else []
        ),
        "latency_ms": attempt.attempt_record.latency_ms,
    }


def _run_payload(result: ProblemDomainExtractionRunResult) -> dict[str, Any]:
    return {
        "accepted": result.accepted,
        "blocked": result.blocked,
        "blocked_reason": result.blocked_reason,
        "attempt_count": len(result.attempts),
        "problem_revision_id": result.final_context.projection.problem_revision_id,
        "problem_semantic_hash": result.final_context.projection.problem_semantic_hash,
        "family_id": result.final_context.projection.family_id,
        "attempts": [item.to_payload() for item in result.attempts],
    }


def _review_html(
    result: ProblemDomainExtractionRunResult,
    image_paths: Mapping[str, str],
) -> str:
    sections: list[str] = []
    previous: ProblemDraft | None = None
    for attempt in result.attempts:
        prefix = f"attempt-{attempt.attempt_number}"
        images = "".join(
            f'<figure><img src="{escape(image_paths[f"{prefix}:{index}"])}" '
            f'alt="{escape(image.role)}"><figcaption>{escape(image.role)} · '
            f'{escape(image.page_id)}</figcaption></figure>'
            for index, image in enumerate(attempt.request.images, start=1)
        )
        first = attempt.report.first_issue
        error = (
            f"{first.code} · {first.message} · {first.repair_action}"
            if first is not None
            else "通过"
        )
        draft_payload = (
            attempt.resulting_draft.graph.wire_payload()
            if attempt.resulting_draft is not None
            else None
        )
        patch_payload = attempt.patch.to_payload() if attempt.patch is not None else None
        cone = _repair_cone_payload(attempt.resulting_draft)
        diff = _draft_diff(previous, attempt.resulting_draft, attempt.patch)
        response_format = dict(attempt.request.response_format)
        json_schema = response_format.get("json_schema", {})
        schema_name = (
            json_schema.get("name")
            if isinstance(json_schema, Mapping)
            else None
        )
        schema_summary = (
            f"{schema_name or attempt.request.contract_version} · "
            f"transport={response_format.get('type', 'unknown')} · "
            f"strict={json_schema.get('strict', False) if isinstance(json_schema, Mapping) else False}"
        )
        sections.append(
            f"""<section><h2>Attempt {attempt.attempt_number} · {escape(attempt.request.contract_version)}</h2>
            <div class="images">{images}</div>
            <p><strong>Validator:</strong> {escape(error)}</p>
            <details><summary>Response schema · {escape(schema_summary)}</summary><pre>{escape(json.dumps({'transport_response_format': response_format, 'schema': dict(attempt.request.contract_schema)}, ensure_ascii=False, indent=2))}</pre></details>
            <details><summary>System prompt</summary><pre>{escape(attempt.request.prompt.system)}</pre></details>
            <details><summary>User prompt</summary><pre>{escape(attempt.request.prompt.user_debug)}</pre></details>
            <h3>模型输出</h3><pre>{escape(json.dumps(patch_payload or draft_payload, ensure_ascii=False, indent=2))}</pre>
            <h3>Patch 前后差异</h3><pre>{escape(json.dumps(diff, ensure_ascii=False, indent=2))}</pre>
            <h3>冻结单元与 repair cone</h3><pre>{escape(json.dumps(cone, ensure_ascii=False, indent=2))}</pre></section>"""
        )
        if attempt.resulting_draft is not None:
            previous = attempt.resulting_draft
    status = "ACCEPTED" if result.accepted else "BLOCKED"
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
    <title>Problem domain review</title><style>
    body{{font:15px system-ui;line-height:1.55;max-width:1280px;margin:28px auto;padding:0 20px;color:#18212f}}
    section{{border-top:1px solid #ccd4df;padding:22px 0}} .images{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
    img{{max-width:100%;border:1px solid #aeb9c8}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:12px}}
    </style></head><body><h1>Problem Domain Extraction · {status}</h1>
    <p>完整题图、领域树、冻结单元、局部 patch 和 validator 结果按轮次展示。</p>{''.join(sections)}</body></html>"""


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = ["ProblemDomainDebugWriter"]
