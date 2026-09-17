"""Image-only extraction/review/repair. No benchmark or Solver dependencies."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from .candidate_common import strict_json
from .identity import revision
from .notation_contract import CONTRACT, ROOT, schema
from .notation_service import parse_candidate
from .repair_guard import guard_changes
from .review_contract import (
    FILES,
    ReviewFamilyCatalogError,
    request_for,
    review_family_context,
    validate_review,
)
from .workflow_diagnostics import (
    diagnose,
    repair_permissions,
    review_diagnostics,
    uncertainty_diagnostics,
)
from .workflow_ledger import Budget, WorkflowStop
from .workflow_storage import FileWorkflowStorage


def frozen_files():
    """Bind file identities and bytes without binding the checkout location."""
    package = Path(__file__).resolve().parent
    implementation = [
        *package.glob("*.py"),
        package.parent / "solver/extraction/multimodal_provider.py",
        package.parent / "solver/extraction/deepseek_files.py",
    ]
    return {
        "templates": {
            p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in FILES
        },
        "implementation": {
            p.relative_to(package.parent).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in sorted(implementation)
        },
    }


def run_workflow(request, provider, output, registry, *, problem_id, budget=None,
                 storage=None, initial_candidate=None, mode="extract", source_hash=None):
    if mode not in ("extract", "review", "validate") or (mode != "extract" and initial_candidate is None):
        raise WorkflowStop("workflow.invalid_mode")
    if request.contract_version != CONTRACT or request.contract_schema != schema():
        raise WorkflowStop("workflow.unsupported_or_stale_contract")
    # A new family needs source-review guidance before any paid workflow call.
    try:
        if mode != 'validate':
            review_family_context(registry)
    except ReviewFamilyCatalogError as exc:
        raise WorkflowStop(str(exc)) from exc
    budget = budget or Budget()
    storage = storage or FileWorkflowStorage(output)
    prepared = provider.prepare_request(request)
    if (
        not 0 < prepared.max_tokens <= 16_384
        or prepared.timeout is None
        or not 0 < prepared.timeout <= 300
    ):
        raise WorkflowStop("workflow.invalid_transport_budget")
    binding = {
        "request_hash": revision(prepared.redacted_payload()),
        "problem_id": problem_id,
        "images": [i.artifact.sha256 for i in prepared.images],
        "registry": revision(registry),
        "files": frozen_files(),
        "mode": mode,
        "initial_candidate": revision(initial_candidate) if initial_candidate is not None else None,
        "source_hash": source_hash or prepared.evidence_pack.source_revision_hash,
    }
    # Concurrency/stale-input failures occur before any shared result mutation.
    with storage.ledger(binding, budget) as ledger:
        return _run(prepared, provider, storage, registry, problem_id, ledger, budget, initial_candidate, mode)


def _run(request, provider, storage, registry, problem_id, ledger, budget, initial_candidate, mode):
    current, parsed, first = None, None, None
    stage, diagnostics, allowed, feedback = "extract", [], [], []
    source_status, source_reviewed, status = "not_reviewed", False, "in_progress"
    seen, events = set(), []
    first_response, last_review = None, None
    store = storage.artifacts

    def parse(raw):
        return parse_candidate(
            raw,
            problem_id=problem_id,
            source_sha256=ledger.binding['source_hash'],
            registry_snapshot=revision(registry),
            registered_families=[f["family_id"] for f in registry],
            store=store,
        )

    try:
        if initial_candidate is not None and mode != 'extract':
            import json
            current = first = initial_candidate
            parsed = parse(json.dumps(current, ensure_ascii=False))
            seen.add(revision(current))
            diagnostics = [*uncertainty_diagnostics(current), *diagnose(parsed, current)]
            if mode == 'validate':
                status = 'validated_candidate' if not diagnostics else 'needs_confirmation' if any(
                    d['action'] == 'needs_confirmation' for d in diagnostics) else 'invalid_candidate'
            elif any(d['action'] == 'needs_confirmation' for d in diagnostics):
                status = 'needs_confirmation'
            elif diagnostics:
                allowed = repair_permissions(current, diagnostics)
                stage = 'repair'
                if not allowed:
                    status = 'code_gap'
            else:
                stage = 'review'
        while True:
            if status != 'in_progress':
                break
            storage.guard()
            if frozen_files() != ledger.binding["files"]:
                raise WorkflowStop("workflow.stale_binding")
            outgoing = (
                request
                if stage == "extract"
                else request_for(
                    request,
                    stage,
                    current,
                    registry,
                    diagnostics,
                    allowed,
                    feedback,
                    validation=parsed,
                )
            )
            base_revision = revision(current) if current is not None else None
            response = ledger.complete(stage, outgoing, base_revision, provider)
            event = {
                "call": ledger.position,
                "stage": stage,
                "base_revision": base_revision,
                "allowed_changes": allowed,
                "diagnostics": diagnostics,
                "adopted": False,
            }
            events.append(event)
            if stage == "extract":
                first_response = response
                storage.save("first-response.json", response)
            if stage == "review":
                if response["finish_reason"] != "stop":
                    raise WorkflowStop("review.invalid_response")
                try:
                    review = validate_review(response["text"], current)
                except (
                    ValueError,
                    KeyError,
                    IndexError,
                    RecursionError,
                    ValidationError,
                ) as exc:
                    raise WorkflowStop("review.invalid_response") from exc
                last_review = {"revision": base_revision, **review}
                event["review"] = last_review
                storage.save("latest-review.json", last_review)
                source_status = review["status"]
                if source_status == "confirmed":
                    source_reviewed = True
                    status = "reviewed_candidate"
                    break
                diagnostics = review_diagnostics(review, current)
                event["diagnostics"] = diagnostics
                if any(d["action"] == "needs_confirmation" for d in diagnostics):
                    status = "needs_confirmation"
                    break
                allowed = repair_permissions(current, diagnostics)
                feedback = []
                stage = "repair"
                continue

            if response["finish_reason"] != "stop":
                event["wire_error"] = "response.truncated_or_invalid_finish"
                # A structurally complete response is still useful history even
                # when its transport finish marker prevents adoption.
                try:
                    truncated = strict_json(response["text"])
                except (ValueError, RecursionError):
                    truncated = None
                if Draft202012Validator(schema()).is_valid(truncated):
                    event["parse"] = parse(response["text"])
                    storage.proposed(truncated, event["parse"], ledger.position)
                if current is None:
                    diagnostics = [
                        {
                            "stage": "json",
                            "code": "response.truncated",
                            "path": "",
                            "action": "repair",
                            "message": "上一轮输出截断，按原图输出完整简洁 JSON。",
                        }
                    ]
                    allowed = [{"path": "", "mode": "reextract"}]
                feedback = [{"code": "response.truncated"}]
                stage = "repair"
                continue
            proposed_parse = parse(response["text"])
            try:
                proposed = strict_json(response["text"])
            except (ValueError, RecursionError):
                proposed = None
            if stage == "extract":
                first = proposed
                storage.save("first-parsed.json", proposed_parse)
            event["parse"] = proposed_parse
            shape_valid = Draft202012Validator(schema()).is_valid(proposed)
            if not shape_valid:
                new_diagnostics = diagnose(proposed_parse, proposed)
                if current is None:
                    diagnostics = new_diagnostics
                    allowed = [{"path": "", "mode": "reextract"}]
                feedback = new_diagnostics
                stage = "repair"
                continue
            storage.proposed(proposed, proposed_parse, ledger.position)
            if current is not None:
                guard = guard_changes(current, proposed, allowed)
                event["change_guard"] = guard
                if not guard["ok"]:
                    feedback = guard["violations"]
                    signature = revision({"proposal": proposed, "violations": feedback})
                    if signature in seen:
                        raise WorkflowStop("workflow.no_progress")
                    seen.add(signature)
                    stage = "repair"
                    continue
                if guard_changes(current, proposed, [])["ok"]:
                    raise WorkflowStop("workflow.no_progress")
            exact = revision(proposed)
            if exact in seen:
                raise WorkflowStop("workflow.oscillation")
            seen.add(exact)
            # Atomic adoption only after both shape and change-authority checks.
            storage.adopt(proposed, proposed_parse, ledger.position)
            current, parsed = proposed, proposed_parse
            source_status, source_reviewed = "not_reviewed", False
            event.update(adopted=True, revision=exact)
            storage.save("candidate.json", current)
            storage.save("parsed.json", parsed)
            source_diagnostics = uncertainty_diagnostics(current)
            if any(d["action"] == "needs_confirmation" for d in source_diagnostics):
                diagnostics = source_diagnostics
                status = (
                    "code_gap"
                    if any(d["action"] == "code_gap" for d in diagnostics)
                    else "needs_confirmation"
                )
                event["diagnostics"] = diagnostics
                break
            diagnostics = [*source_diagnostics, *diagnose(parsed, current)]
            event["diagnostics"] = diagnostics
            if diagnostics:
                allowed = repair_permissions(current, diagnostics)
                if not allowed:
                    status = "code_gap"
                    break
                stage = "repair"
            else:
                allowed = []
                stage = "review"
            feedback = []
    except WorkflowStop as exc:
        status = str(exc)
        if stage == "review":
            source_status = "failed"
    except Exception as exc:  # noqa: BLE001 - preserve internal failure without requesting semantic edits
        # Internal errors never become instructions to change the mathematics.
        status = "workflow.internal_error"
        diagnostics = [
            {"stage": "internal", "code": type(exc).__name__, "action": "code_gap"}
        ]
    result = {
        "schema_version": "problem-math-workflow/v1",
        "candidate_only": True,
        "solver_ready": False,
        "status": status,
        "source_status": source_status,
        "source_reviewed": source_reviewed,
        "parse_status": "valid" if parsed and parsed["contract_valid"] else "invalid",
        "match_status": current.get("match_status") if current else None,
        "continuation": {
            "blocked": status != "reviewed_candidate",
            "reason": status,
            "unmatched": bool(current and current["match_status"] == "unmatched"),
        },
        "diagnostics": diagnostics,
        "budget": asdict(budget),
        **ledger.counts(),
        "first_candidate": first,
        "candidate": current,
        "parsed": parsed,
        "first_finish_reason": first_response["finish_reason"]
        if first_response
        else None,
        "review": last_review,
        "events": events,
    }
    storage.save("workflow-result.json", result)
    return result
