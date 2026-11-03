"""Image-only extraction/review/repair. No benchmark or Solver dependencies."""

from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from .candidate_common import strict_json
from .identity import revision
from .notation_contract import CONTRACT, ROOT, schema
from .notation_service import parse_candidate
from .review_contract import (
    FILES,
    ReviewFamilyCatalogError,
    request_for,
    review_family_context,
    validate_review,
)
from .workflow_diagnostics import (
    diagnose,
    review_diagnostics,
    uncertainty_diagnostics,
)
from .workflow_ledger import Budget, WorkflowStop
from .workflow_storage import FileWorkflowStorage


class RepairResponseError(ValueError):
    """Reject a contract-specific repair without changing the current candidate."""

    def __init__(self, diagnostics):
        super().__init__('repair.invalid_response')
        self.diagnostics = diagnostics


def frozen_files():
    """Bind file identities and bytes without binding the checkout location."""
    package = Path(__file__).resolve().parent
    implementation = [
        *(
            p
            for p in package.glob("*.py")
            if p.name
            not in {
                "runtime_binding.py",
                "runtime_lowering.py",
                "compact_planner_input.py",
            }
        ),
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


class MathNotationWorkflowContract:
    """The existing contract remains the default for every production caller."""

    def validate_request(self, request, registry, mode):
        if request.contract_version != CONTRACT or request.contract_schema != schema():
            raise WorkflowStop("workflow.unsupported_or_stale_contract")
        try:
            if mode != "validate":
                review_family_context(registry)
        except ReviewFamilyCatalogError as exc:
            raise WorkflowStop(str(exc)) from exc

    def schema(self):
        return schema()

    def frozen_files(self):
        return frozen_files()

    def parse(self, raw, *, problem_id, source_hash, registry, store):
        return parse_candidate(
            raw,
            problem_id=problem_id,
            source_sha256=source_hash,
            registry_snapshot=revision(registry),
            registered_families=[f["family_id"] for f in registry],
            store=store,
        )

    def request_for(self, *args, **kwargs):
        return request_for(*args, **kwargs)

    def validate_review(self, raw, candidate):
        return validate_review(raw, candidate)

    def invalid_review_feedback(self):
        """Legacy contracts stop immediately on a malformed source review."""
        return

    def diagnose(self, parsed, candidate):
        return diagnose(parsed, candidate)

    def review_diagnostics(self, review, candidate):
        return review_diagnostics(review, candidate)

    def repair_diagnostics(self, current, proposed, diagnostics):
        return []

    def result_fields(self, current):
        return {"match_status": current.get("match_status") if current else None}

    def continuation_fields(self, current):
        return {"unmatched": bool(current and current["match_status"] == "unmatched")}


def run_workflow(
    request,
    provider,
    output,
    registry,
    *,
    problem_id,
    budget=None,
    storage=None,
    initial_candidate=None,
    mode="extract",
    source_hash=None,
    contract_adapter=None,
):
    if mode not in ("extract", "review", "validate") or (
        mode != "extract" and initial_candidate is None
    ):
        raise WorkflowStop("workflow.invalid_mode")
    contract = contract_adapter or MathNotationWorkflowContract()
    contract.validate_request(request, registry, mode)
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
        "files": contract.frozen_files(),
        "mode": mode,
        "initial_candidate": revision(initial_candidate)
        if initial_candidate is not None
        else None,
        "source_hash": source_hash or prepared.evidence_pack.source_revision_hash,
    }
    # Concurrency/stale-input failures occur before any shared result mutation.
    with storage.ledger(binding, budget) as ledger:
        return _run(
            prepared,
            provider,
            storage,
            registry,
            problem_id,
            ledger,
            budget,
            initial_candidate,
            mode,
            contract,
        )


def _run(
    request,
    provider,
    storage,
    registry,
    problem_id,
    ledger,
    budget,
    initial_candidate,
    mode,
    contract,
):
    current, parsed, first = None, None, None
    stage, diagnostics, feedback = "extract", [], []
    source_status, source_reviewed, status = "not_reviewed", False, "in_progress"
    seen, events = set(), []
    first_response, last_review = None, None
    store = storage.artifacts

    def parse(raw):
        return contract.parse(
            raw,
            problem_id=problem_id,
            source_hash=ledger.binding["source_hash"],
            registry=registry,
            store=store,
        )

    try:
        if initial_candidate is not None and mode != "extract":
            import json

            current = first = initial_candidate
            parsed = parse(json.dumps(current, ensure_ascii=False))
            seen.add(revision(current))
            diagnostics = [
                *uncertainty_diagnostics(current),
                *contract.diagnose(parsed, current),
            ]
            if mode == "validate":
                status = (
                    "validated_candidate"
                    if not diagnostics
                    else "needs_confirmation"
                    if any(d["action"] == "needs_confirmation" for d in diagnostics)
                    else "invalid_candidate"
                )
            elif any(d["action"] == "needs_confirmation" for d in diagnostics):
                status = "needs_confirmation"
            elif diagnostics:
                stage = "repair"
            else:
                stage = "review"
        while True:
            if status != "in_progress":
                break
            storage.guard()
            if contract.frozen_files() != ledger.binding["files"]:
                raise WorkflowStop("workflow.stale_binding")
            outgoing = (
                request
                if stage == "extract"
                else contract.request_for(
                    request,
                    stage,
                    current,
                    registry,
                    diagnostics,
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
                "diagnostics": diagnostics,
                "adopted": False,
            }
            events.append(event)
            if stage == "extract":
                first_response = response
                storage.save("first-response.json", response)
            if stage == "review":
                try:
                    if response["finish_reason"] != "stop":
                        raise ValueError("review.invalid_finish_reason")
                    review = contract.validate_review(response["text"], current)
                except (
                    ValueError,
                    KeyError,
                    IndexError,
                    RecursionError,
                    ValidationError,
                ) as exc:
                    event["review_validation"] = {
                        "ok": False,
                        "code": "review.invalid_response",
                        "error_type": type(exc).__name__,
                    }
                    review_feedback = contract.invalid_review_feedback()
                    if review_feedback is None:
                        raise WorkflowStop("review.invalid_response") from exc
                    # A format retry reviews the same immutable candidate; it
                    # cannot adopt a candidate smuggled into the bad response.
                    source_status, source_reviewed = "invalid_response", False
                    feedback = review_feedback
                    event["review_retry_feedback"] = feedback
                    continue
                last_review = {"revision": base_revision, **review}
                event["review"] = last_review
                storage.save("latest-review.json", last_review)
                source_status = review["status"]
                if source_status == "confirmed":
                    source_reviewed = True
                    status = "reviewed_candidate"
                    break
                diagnostics = contract.review_diagnostics(review, current)
                event["diagnostics"] = diagnostics
                if any(d["action"] == "needs_confirmation" for d in diagnostics):
                    status = "needs_confirmation"
                    break
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
                if Draft202012Validator(contract.schema()).is_valid(truncated):
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
                feedback = [{"code": "response.truncated"}]
                stage = "repair"
                continue
            candidate_text = response["text"]
            repair_response = getattr(contract, "repair_response", None)
            if stage == "repair" and repair_response is not None:
                try:
                    candidate_text = repair_response(outgoing, candidate_text, current, diagnostics)
                except RepairResponseError as exc:
                    event["repair_rejected"] = feedback = exc.diagnostics
                    if any(d.get("action") == "needs_confirmation" for d in feedback):
                        diagnostics, status = feedback, "needs_confirmation"
                        break
                    continue
            # Keep the provider's raw reply in the ledger. A contract may expand
            # a bounded patch; adoption and fresh source review still use the
            # complete candidate and the existing repair-authority checks.
            proposed_parse = parse(candidate_text)
            try:
                proposed = strict_json(candidate_text)
            except (ValueError, RecursionError):
                proposed = None
            if stage == "extract":
                first = proposed
                storage.save("first-parsed.json", proposed_parse)
            event["parse"] = proposed_parse
            shape_valid = Draft202012Validator(contract.schema()).is_valid(proposed)
            if not shape_valid:
                new_diagnostics = contract.diagnose(proposed_parse, proposed)
                if current is None:
                    diagnostics = new_diagnostics
                feedback = new_diagnostics
                stage = "repair"
                continue
            storage.proposed(proposed, proposed_parse, ledger.position)
            if stage == "repair" and current is not None:
                repair_issues = contract.repair_diagnostics(
                    current, proposed, diagnostics
                )
                if repair_issues:
                    event["repair_rejected"] = repair_issues
                    feedback = repair_issues
                    continue
            exact = revision(proposed)
            if exact in seen:
                raise WorkflowStop("workflow.oscillation")
            seen.add(exact)
            # Atomic adoption follows schema and semantic review checks.
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
            diagnostics = [*source_diagnostics, *contract.diagnose(parsed, current)]
            event["diagnostics"] = diagnostics
            # A code gap is an unsupported or unprovable construct, not a
            # candidate-edit request. Repairing the other findings cannot make
            # the problem supported, so any code gap stops the workflow instead
            # of spending the budget on a candidate that will still fail.
            if any(
                diagnostic.get("action") == "code_gap" for diagnostic in diagnostics
            ):
                status = "code_gap"
                break
            if any(d.get("action") == "needs_confirmation" for d in diagnostics):
                status = "needs_confirmation"
                break
            if diagnostics:
                stage = "repair"
            else:
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
        **contract.result_fields(current),
        "continuation": {
            "blocked": status != "reviewed_candidate",
            "reason": status,
            **contract.continuation_fields(current),
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
