"""Shared candidate JSON, match validation and missing-figure gating."""

import json

from jsonschema import Draft202012Validator

from .notation_contract import schema


def continuation_policy(root):
    """A missing figure blocks processing even when the literal IR is valid.

    This is a server decision, never an LLM adoption/readiness claim. The
    production coordinator must consume it when this isolated entry is wired in.
    """
    missing = []

    def walk(scope, path):
        for item in scope["uncertainties"]:
            if item["kind"] == "missing_figure":
                missing.append(
                    {"scope": path, "label": scope["label"], "text": item["text"]}
                )
        for i, child in enumerate(scope["children"]):
            walk(child, f"{path}.c{i}")

    walk(root, "r")
    return {
        "status": "needs_confirmation" if missing else "candidate_only",
        "blocked": bool(missing),
        "error_code": "extraction.missing_figure" if missing else None,
        "user_action": "supplement_image" if missing else None,
        "message": "题目引用的图形未提供或尚不能确认，已保留提取的题意并停止后续处理。请确认图片是否包含对应图形，必要时补充完整题目图片。"
        if missing
        else None,
        "missing_figures": missing,
    }


def strict_json(raw):
    def pairs(items):
        d = {}
        for k, v in items:
            if k in d:
                raise ValueError("duplicate JSON key")
            d[k] = v
        return d

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


def validate_match(payload, registered_families):
    contract = schema()
    names = ("family_id", "match_status", "match_reason")
    match_shape = {
        "type": "object",
        "properties": {k: contract["properties"][k] for k in names},
        "required": list(names),
        "additionalProperties": False,
    }
    issues = [
        "match.schema_invalid"
        for _ in Draft202012Validator(match_shape).iter_errors(
            {k: payload[k] for k in names if k in payload}
        )
    ]
    status = payload.get("match_status")
    family = payload.get("family_id")
    reason = payload.get("match_reason")
    if status not in ("matched", "unmatched"):
        issues.append("match.invalid_status")
    if not isinstance(reason, str) or not reason.strip():
        issues.append("match.reason_required")
    if status == "matched" and family not in registered_families:
        issues.append("match.unknown_family")
    if status == "unmatched" and family is not None:
        issues.append("match.unmatched_family_must_be_null")
    if not all(k in payload for k in ("family_id", "match_status", "match_reason")):
        issues.append("match.fields_required")
    return {"ok": not issues, "issues": issues}
