"""Versioned evidence for one semantic attempt; never a source of authority.

Only existing stage outputs are serialized. Missing artifacts are explicit,
particularly a rejected candidate versus a previously executed base Plan.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .llm_debug import safe_debug_json, write_debug_json


def _payload(value: Any) -> Any:
    for method_name in ("authority_payload", "to_payload"):
        method = getattr(value, method_name, None)
        if callable(method):
            return method()
    return safe_debug_json(value)


def _issues(report: Any) -> list[Any]:
    return [_payload(item) for item in getattr(report, "issues", ())]


def write_scoped_attempt_evidence(directory: Path, attempt: Any) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    prefix = f"attempt-{attempt.semantic_attempt}"
    artifacts: dict[str, Any] = {}

    def save(role: str, value: Any, reason: str = "stage_not_reached") -> None:
        if value is None:
            artifacts[role] = {"status": "not_available", "reason": reason}
            return
        path = directory / f"{prefix}.{role}.json"
        write_debug_json(path, _payload(value))
        artifacts[role] = {
            "status": "saved", "file": path.name,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }

    execution = getattr(attempt, "execution", None)
    replay = getattr(execution, "replay", None)
    checkpoint = getattr(execution, "checkpoint", None)
    transaction = getattr(replay, "transactional_attempt_result", None)
    canonical = getattr(execution, "canonical_plan", None)
    base_authority = getattr(attempt, "scope_authority", None)
    result_authority = getattr(attempt, "result_scope_authority", None)
    base_checkpoint = getattr(attempt, "base_checkpoint", None)
    base_plan = getattr(attempt, "base_plan", None)
    if base_plan is None and base_authority is not None:
        base_plan = base_authority.base_plan

    prompt = attempt.prompt
    messages = prompt.as_messages() if hasattr(prompt, "as_messages") else getattr(prompt, "messages", None)
    save("request", {"messages": messages, "planner_payload": attempt.payload})
    raw = attempt.raw_response
    if raw is not None:
        try:
            parsed = json.loads(raw)
            parse_error = None
        except (ValueError, TypeError) as exc:
            parsed, parse_error = None, str(exc)
        save("raw-response", {"text": raw, "parsed": parsed, "parse_error": parse_error})
    else:
        save("raw-response", None, "no_visible_response_received")
    save("normalized-response", getattr(attempt, "normalized_response", None), "no_normalized_authoring_response")
    save("normalized-content", getattr(attempt, "normalized_content", None), "no_merged_content_normalization")
    save("math-argument-bindings", getattr(attempt, "math_argument_bindings", ()))
    save("candidate-plan", getattr(attempt, "candidate_plan", None), "no_structurally_assembled_candidate")
    save("compiled-plan", getattr(attempt, "merged_plan", None), "content_contract_not_passed")
    save("canonical-plan", canonical, "no_canonical_plan_from_this_execution")
    save("base-plan", base_plan, "no_previous_execution_base")
    save("base-checkpoint", base_checkpoint, "no_previous_execution_checkpoint")
    save("base-authority", base_authority.debug_payload() if base_authority is not None else None, "not_a_scope_repair")
    save("result-authority", result_authority.debug_payload() if result_authority is not None else None, "no_next_scope_authority")
    save("normalizations", {
        "content": [_payload(item) for item in getattr(attempt, "content_normalizations", ())],
        "authority": [_payload(item) for item in getattr(getattr(execution, "authority_report", None), "normalizations", ())],
        "replay": _payload(getattr(replay, "normalization_report", None)),
        "runtime_equivalent_aliases": [_payload(item) for item in getattr(execution, "runtime_equivalent_aliases", ())],
    })
    save("content-validation", getattr(attempt, "content_validation_report", None))
    save("execution-validation", getattr(execution, "validation_report", None))
    save("execution-authority", getattr(execution, "authority_report", None))
    save("final-plan-contract-validation", getattr(attempt, "final_plan_contract_validation", None))
    save("transaction", transaction, "transaction_not_started")
    save("checkpoint", checkpoint, "execution_did_not_produce_checkpoint")
    save("verified-execution", getattr(execution, "verified_execution", None), "execution_not_verified")
    # This is the versioned checkpoint authority including typed value payloads
    # and signatures, not the prompt-only view. Its runtime_seed is deliberately
    # process-local: persisted evidence alone must not authorize cached execution.
    save("checkpoint-capabilities", {
        "checkpoint_id": getattr(checkpoint, "checkpoint_id", None),
        "authority_round_trip_supported": checkpoint is not None,
        "automatic_cross_process_runtime_restore": False,
        "reason": "runtime_seed remains process-local; deserialization must revalidate authority and cannot grant execution reuse",
    })
    report = getattr(transaction, "execution_report", None)
    previous_seed = getattr(getattr(base_checkpoint, "restore_state", None), "runtime_seed", None)
    previous_ids = set(getattr(previous_seed, "call_ids", ()))
    requested = tuple(getattr(attempt, "requested_restore_call_ids", ()))
    save("reuse", {
        "base_checkpoint_id": getattr(base_checkpoint, "checkpoint_id", None),
        "result_checkpoint_id": getattr(checkpoint, "checkpoint_id", None),
        "requested_call_ids": list(requested),
        "actual_restored_call_ids": list(getattr(attempt, "restored_call_ids", ())),
        "executed_call_ids": list(getattr(report, "executed_call_ids", ())),
        "previous_calls_not_requested": sorted(previous_ids - set(requested)),
        "execution_started": execution is not None,
        "editable_scope_refs": list(getattr(base_authority, "editable_scope_refs", ())),
    })
    error = getattr(attempt, "error", None)
    save("attempt-error", error, "no_attempt_error")
    candidate_rejected = error is not None and raw is not None and execution is None and getattr(attempt, "evidence_phase", "") != "execution_failed"
    save("candidate-error", error if candidate_rejected else None, "not_a_candidate_rejection")
    blockers = []
    blocker_source = None
    for source, issues in (
        ("content-validation", _issues(getattr(attempt, "content_validation_report", None))),
        ("execution-validation", _issues(getattr(execution, "validation_report", None))),
        ("execution-authority", _issues(getattr(execution, "authority_report", None))),
        ("transaction", [_payload(item) for item in getattr(transaction, "root_issues", ())]),
        ("checkpoint", [_payload(item) for item in getattr(checkpoint, "root_issues", ())]),
        ("final-plan-contract-validation", _issues(getattr(getattr(attempt, "final_plan_contract_validation", None), "report", None))),
        ("attempt-error", [_payload(error)] if error is not None else []),
    ):
        if issues:
            blocker_source, blockers = source, issues
            break
    save("blockers", {
        "ordering": "first blocked pipeline stage; transaction.events records call execution order",
        "source": blocker_source, "first_reported": blockers[0] if blockers else None, "issues": blockers,
    })

    metadata = dict(getattr(attempt, "llm_metadata", None) or {})
    reasoning = metadata.pop("provider_reasoning", None)
    save("provider-requests", metadata.pop("provider_requests", None), "adapter_did_not_expose_current_provider_requests")
    save("provider-responses", metadata.pop("provider_responses", None), "adapter_did_not_expose_current_provider_responses")
    save("provider-reasoning", {
        "status": "unavailable" if reasoning is None else (
            "provided" if any(item.get("reasoning_content") for item in reasoning) else "not_returned"
        ),
        "attempts": reasoning,
    })
    save("provider-metadata", metadata)
    # Write the index last. Consumers may verify each hash before using a file.
    write_debug_json(directory / f"{prefix}.evidence-index.json", {
        "schema_version": "functional-attempt-evidence/v1",
        "semantic_attempt": attempt.semantic_attempt,
        "planner_protocol": attempt.planner_protocol,
        "phase": getattr(attempt, "evidence_phase", "completed"),
        "base_plan_hash": getattr(base_authority, "base_plan_hash", None),
        "base_checkpoint_id": getattr(base_checkpoint, "checkpoint_id", None),
        "result_checkpoint_id": getattr(checkpoint, "checkpoint_id", None),
        "artifacts": artifacts,
        "legacy_aliases": {f"{prefix}.functional-plan.json": "raw-response"},
    })
