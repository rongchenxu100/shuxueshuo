"""Benchmark adapter. Gold stays outside the extraction coordinator."""

import json
from dataclasses import asdict
from hashlib import sha256
from html import escape
from pathlib import Path

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

from .candidate_common import validate_match
from .identity import revision
from .notation_compile import NotationValidator
from .notation_semantics import evaluate
from .smoke import build_request
from .workflow import frozen_files, run_workflow
from .workflow_ledger import Budget, save
from .workflow_usage import stages as usage_stages


def freeze_inputs(fixture, request, registry):
    policy_path = fixture / "acceptance-policy.json"
    provenance = json.loads((fixture / "provenance.json").read_text())
    return {
        "files": frozen_files(),
        "gold_sha256": sha256((fixture / "gold.json").read_bytes()).hexdigest(),
        "policy": json.loads(policy_path.read_text()) if policy_path.exists() else None,
        "image_sha256": [item.artifact.sha256 for item in request.images],
        "request_hash": revision(request.redacted_payload()),
        "registry_hash": revision(registry),
        "case_id": provenance["case_id"],
        "workflow": "review-repair",
        "budget": asdict(Budget()),
        "model": request.model,
        "image_transport": request.image_transport,
        "thinking": request.thinking_payload(),
        "reasoning_effort": request.reasoning_effort,
        "timeout": request.timeout,
        "max_tokens": request.max_tokens,
        "network_attempts_per_call": 2,
        "sdk_retries": 0,
    }


def assess(expected, candidate, policy):
    if not isinstance(candidate, dict):
        return {"ok": False, "reason": "no_candidate"}
    result = evaluate(expected, candidate, policy)
    result["match_correct"] = all(
        candidate.get(k) == expected[k] for k in ("match_status", "family_id")
    )
    result["passed"] = result["ok"] and result["match_correct"]
    return result


def run(fixture, output, provider, registry):
    output = Path(output)
    expected = json.loads((fixture / "gold.json").read_text())
    policy_path = fixture / "acceptance-policy.json"
    policy = json.loads(policy_path.read_text()) if policy_path.exists() else None
    if (
        not NotationValidator().validate(expected).ok
        or not evaluate(expected, expected, policy)["ok"]
    ):
        raise ValueError("invalid frozen gold")
    if not validate_match(expected, [f["family_id"] for f in registry])["ok"]:
        raise ValueError("invalid gold match")
    request = provider.prepare_request(
        build_request(fixture, ExtractionArtifactStore(output / "inputs"), registry)
    )
    provenance = json.loads((fixture / "provenance.json").read_text())
    frozen = freeze_inputs(fixture, request, registry)
    batch_path = output.parent / "frozen-batch.json"
    if batch_path.exists():
        batch = json.loads(batch_path.read_text())
        if batch["cases"].get(provenance["case_id"]) != frozen:
            raise ValueError("workflow.frozen_batch_changed")
    frozen_path = output / "frozen-workflow.json"
    if frozen_path.exists() and json.loads(frozen_path.read_text()) != frozen:
        raise ValueError("workflow.frozen_batch_changed")
    save(frozen_path, frozen)
    result = run_workflow(
        request,
        provider,
        output / "workflow",
        registry,
        problem_id=provenance["case_id"],
    )
    first = assess(expected, result["first_candidate"], policy)
    final = assess(expected, result["candidate"], policy)
    first["passed"] = bool(
        first.get("passed") and result["first_finish_reason"] == "stop"
    )
    save(output / "first-acceptance.json", first)
    save(output / "final-acceptance.json", final)
    stages = usage_stages(output / "workflow")
    missing = any(d.get("code") == "missing_figure" for d in result["diagnostics"])
    terminal_ok = result["status"] == "reviewed_candidate" or (
        missing and result["status"] == "needs_confirmation"
    )
    summary = {
        k: result[k]
        for k in (
            "candidate_only",
            "solver_ready",
            "source_reviewed",
            "status",
            "source_status",
            "parse_status",
            "match_status",
            "continuation",
            "semantic_calls",
            "network_attempts",
            "content_calls",
            "review_calls",
            "file_api_calls",
        )
    }
    summary.update(
        case_id=provenance["case_id"],
        workflow="review-repair",
        image_transport=request.image_transport,
        first_passed=first["passed"],
        passed=bool(final.get("passed") and terminal_ok),
        final_semantics_passed=bool(final.get("passed")),
        strict_semantics_passed=bool(final.get("strict", {}).get("ok")),
        accepted_omissions=final.get("accepted_omissions", []),
        stages=stages,
        elapsed_seconds=round(sum(r["seconds"] for r in stages.values()), 3),
        missing_figure_blocked=missing and result["continuation"]["blocked"],
    )
    save(output / "summary.json", summary)
    details = "".join(
        "<details><summary>调用 "
        + str(e["call"])
        + " · "
        + escape(e["stage"])
        + "</summary><pre>"
        + escape(json.dumps(e, ensure_ascii=False, indent=2))
        + "</pre></details>"
        for e in result["events"]
    )
    (output / "outputs.html").write_text(
        "<!doctype html><meta charset=utf-8><title>抽取复核与修复</title><style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:20px}summary{cursor:pointer}</style><h1>"
        + escape(provenance["case_id"])
        + "</h1><pre>"
        + escape(json.dumps(summary, ensure_ascii=False, indent=2))
        + "</pre><h2>首轮候选</h2><pre>"
        + escape(json.dumps(result["first_candidate"], ensure_ascii=False, indent=2))
        + "</pre><h2>最终候选</h2><pre>"
        + escape(json.dumps(result["candidate"], ensure_ascii=False, indent=2))
        + "</pre>"
        + details
    )
    return summary
