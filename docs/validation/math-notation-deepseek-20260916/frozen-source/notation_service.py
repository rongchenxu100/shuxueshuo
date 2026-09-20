"""Versioned candidate artifacts and rendering for mathematical notation."""

import json
from html import escape

from .identity import revision
from .notation_compile import NotationValidator
from .notation_contract import CONTRACT
from .notation_semantics import canonical
from .service import continuation_policy, strict_json
from .validation import validate_match


def parse_candidate(
    raw,
    *,
    problem_id,
    source_sha256,
    registry_snapshot,
    registered_families,
    store=None,
):
    result = {
        "schema_version": "problem-ir-candidate/v1",
        "contract": CONTRACT,
        "candidate_only": True,
        "source_reviewed": False,
        "solver_ready": False,
        "binding": {
            "problem_id": problem_id,
            "source_sha256": source_sha256,
            "registry_snapshot": registry_snapshot,
        },
        "objects": {},
        "reports": {},
        "artifacts": {},
        "contract_valid": False,
        "continuation": {"status": "invalid_candidate", "blocked": True},
    }

    def save(name, data):
        if store:
            result["artifacts"][name] = store.put_json(
                kind="notation_" + name, payload=data
            ).to_payload()

    if store:
        result["artifacts"]["raw"] = store.put_bytes(
            kind="notation_raw",
            content=raw.encode(),
            media_type="text/plain",
            suffix=".txt",
        ).to_payload()
    try:
        payload = strict_json(raw)
    except (ValueError, RecursionError) as exc:
        result["reports"]["json"] = {"ok": False, "issues": [str(exc)]}
        return result
    save("candidate", payload)
    result["revision"] = revision(payload)
    report = NotationValidator().validate(payload)
    if report.ok:
        try:
            comparison = canonical(report)
            report.well_definedness_obligations.extend(
                {"code": "algebra_domain", "condition": json.loads(item)}
                for item in comparison["well_definedness"]
            )
            result["semantic_revision"] = revision(comparison)
            save("canonical", comparison)
        except (ValueError, TypeError, RecursionError) as exc:
            report.issues.append(
                {
                    "path": "/root",
                    "code": "notation.semantic_invalid",
                    "message": str(exc),
                }
            )
    result["reports"]["ir"] = report.payload()
    result["reports"]["match"] = (
        validate_match(payload, registered_families)
        if isinstance(payload, dict)
        else {"ok": False}
    )
    if report.ok:
        ir = {"root": report.normalized["root"]}
        result["objects"]["ir"] = ir
        result["units"] = report.units
        save("ir", ir)
        save(
            "compiled",
            {
                "schema_version": "bound-math-notation/v1",
                "root": report.semantic,
                "defaults": report.defaults,
                "objects": report.objects,
                "well_definedness_obligations": report.well_definedness_obligations,
            },
        )
        result["continuation"] = continuation_policy(ir["root"])
        save("continuation", result["continuation"])
    if result["reports"]["match"]["ok"]:
        result["objects"]["match"] = {
            k: payload[k] for k in ("family_id", "match_status", "match_reason")
        }
    result["contract_valid"] = report.ok and result["reports"]["match"]["ok"]
    save("validation", result["reports"])
    return result


def render(payload):
    report = NotationValidator().validate(payload)
    if not report.ok:
        raise ValueError("render.invalid_notation")

    def text(value):
        return escape(
            value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        )

    def scope(value):
        rows = ["<section><h2>" + text(value["label"] or "题目") + "</h2>"]
        for field, title in (
            ("definitions", "定义"),
            ("facts", "条件"),
            ("goals", "所求"),
            ("uncertainties", "待确认"),
        ):
            if value[field]:
                rows.append(
                    "<h3>"
                    + title
                    + "</h3><ul>"
                    + "".join("<li>" + text(x) + "</li>" for x in value[field])
                    + "</ul>"
                )
        return (
            "".join(rows) + "".join(scope(c) for c in value["children"]) + "</section>"
        )

    continuation = continuation_policy(report.normalized["root"])
    return (
        '<!doctype html><html lang="zh"><meta charset="utf-8"><title>简洁题意候选</title>'
        "<style>body{max-width:1000px;margin:40px auto;font:18px/1.7 system-ui;padding:0 20px}section{border-left:2px solid #ddd;padding-left:20px}li{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
        "<h1>简洁题意候选</h1>"
        + (
            "<aside>" + text(continuation["message"]) + "</aside>"
            if continuation["blocked"]
            else ""
        )
        + scope(report.normalized["root"])
        + "<p>题型："
        + text(payload.get("family_id") or "未匹配")
        + "</p><p>仅提取与校验；未进入求解流程。</p></html>"
    )
