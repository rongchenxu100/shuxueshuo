from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from types import MappingProxyType

from PIL import Image
import pytest

from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ExtractionAttemptLedger,
    ExtractionAttemptRecord,
    ExtractionCandidateChange,
    ExtractionCandidateRecord,
    ExtractionDecision,
    ExtractionEvidenceRecord,
    ExtractionIssue,
    ExtractionRetryState,
    ExtractionState,
    ExtractionStatePatch,
    ProblemExtractionContext,
    ProblemExtractionContextBuilder,
    ProblemExtractionContextTransitionService,
    _context_id,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ExtractionDependencyManifest,
    ProblemExtractionContextError,
    ProblemSourceFingerprintService,
    SelectionRegion,
    SourceAssetInput,
    SourceSelection,
    stable_hash,
)


def _source_context(*, with_state: bool = False, attempt_budget: int = 3):
    output = BytesIO()
    Image.new("RGB", (8, 6), "white").save(output, format="PNG")
    source = ProblemSourceFingerprintService().fingerprint(
        (
            SourceAssetInput(
                "page_1",
                "image/png",
                output.getvalue(),
                "repo://source.png",
            ),
        )
    )
    selection = SourceSelection.create(
        source,
        mode="authored_gold",
        revision=0,
        regions=(
            SelectionRegion(
                "question_25",
                "page_1",
                ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)),
            ),
        ),
    )
    dependency = ExtractionDependencyManifest.create(
        source,
        selection,
        semantic_config={"contract": {"formula": "v1"}},
    )
    state = _state() if with_state else ExtractionState()
    return ProblemExtractionContextBuilder.initial(
        source=source,
        selection=selection,
        dependency=dependency,
        state=state,
        retry=ExtractionRetryState(status="ready", attempt_budget=attempt_budget),
        quality={"coverage": {"candidate_count": len(state.candidates)}},
    )


def _state(*, authorized: bool = False) -> ExtractionState:
    artifact = ExtractionArtifactRef(
        artifact_id="artifact_observation",
        kind="source_observation",
        sha256="a" * 64,
        media_type="application/json",
        byte_size=42,
        locator="artifact://observation",
    )
    evidence = ExtractionEvidenceRecord(
        evidence_id="evidence_1",
        artifact_id=artifact.artifact_id,
        page_id="page_1",
        payload={"bbox": [0.1, 0.1, 0.2, 0.2]},
    )
    candidate = ExtractionCandidateRecord(
        candidate_id="entity_A",
        candidate_type="entity",
        status="accepted",
        evidence_refs=(evidence.evidence_id,),
        locked=True,
        payload={"label": "A", "attributes": {"kind": "point"}},
    )
    issues = (
        ExtractionIssue(
            issue_id="issue_revise_A",
            code="extraction.source_conflict",
            blocking=True,
            retryable=True,
            candidate_ids=(candidate.candidate_id,),
            evidence_ids=(evidence.evidence_id,),
            authorized_revision_candidate_ids=(candidate.candidate_id,),
        ),
    ) if authorized else ()
    return ExtractionState(
        artifacts=(artifact,),
        evidence=(evidence,),
        entity_candidates=(candidate,),
        issues=issues,
    )


def _attempt(context, *, attempt_id: str = "attempt_1", result: str = "timeout"):
    artifact = ExtractionArtifactRef(
        artifact_id=f"artifact_{attempt_id}",
        kind="provider_response",
        sha256="b" * 64,
        media_type="application/json",
        byte_size=0,
    )
    return ExtractionAttemptRecord(
        attempt_id=attempt_id,
        base_context_id=context.manifest.context_id,
        provider="recorded-provider",
        route="text_semantic_required",
        input_artifact_refs=(),
        output_artifact_refs=(artifact,),
        result=result,
        usage={"input_tokens": 100, "output_tokens": 0},
        latency_ms=10,
    )


def test_context_schema_round_trip_is_stable_and_returns_fresh_payloads() -> None:
    context = _source_context(with_state=True)
    payload = context.to_payload()
    restored = ProblemExtractionContext.from_payload(payload)

    assert restored == context
    assert restored.to_payload() == payload
    assert ProblemExtractionContext.from_payload(restored.to_payload()) == restored

    payload["quality"]["coverage"]["candidate_count"] = 99
    payload["state"]["entity_candidates"][0]["payload"]["label"] = "changed"

    assert context.quality["coverage"]["candidate_count"] == 1
    assert context.state.entity_candidates[0].payload["label"] == "A"
    assert isinstance(context.quality, MappingProxyType)
    assert isinstance(context.state.entity_candidates[0].payload, MappingProxyType)
    with pytest.raises(TypeError):
        context.quality["new"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    (
        (
            lambda payload: payload["source"].__setitem__(
                "source_id", "source:" + "0" * 64
            ),
            "extraction.source_fingerprint_mismatch",
        ),
        (
            lambda payload: payload["selection"].__setitem__(
                "selection_hash", "0" * 64
            ),
            "extraction.selection_invalid",
        ),
        (
            lambda payload: payload["dependency"].__setitem__(
                "dependency_hash", "0" * 64
            ),
            "extraction.dependency_hash_mismatch",
        ),
        (
            lambda payload: payload["state"]["entity_candidates"][0][
                "payload"
            ].__setitem__("label", "B"),
            "extraction.context_hash_mismatch",
        ),
        (
            lambda payload: payload["manifest"].__setitem__(
                "context_id", "extraction-context:" + "0" * 64
            ),
            "extraction.context_hash_mismatch",
        ),
        (
            lambda payload: payload["manifest"].__setitem__(
                "parent_context_id", "extraction-context:" + "1" * 64
            ),
            "extraction.context_lineage_unresolved",
        ),
    ),
)
def test_context_tampering_fails_at_typed_authority_boundary(
    mutate,
    expected_code: str,
) -> None:
    payload = deepcopy(_source_context(with_state=True).to_payload())
    mutate(payload)

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContext.from_payload(payload)

    assert exc_info.value.code == expected_code


def test_context_schema_rejects_missing_required_field() -> None:
    payload = _source_context().to_payload()
    payload.pop("retry")

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContext.from_payload(payload)

    assert exc_info.value.code == "extraction.context_hash_mismatch"
    assert "retry" in exc_info.value.message


def test_context_rejects_duplicate_candidate_identity_across_types() -> None:
    state = _state()
    duplicate = replace(
        state.entity_candidates[0],
        candidate_type="fact",
    )
    state = replace(state, fact_candidates=(duplicate,))

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        _build_with_state(state)

    assert exc_info.value.code == "extraction.candidate_duplicate"


def test_context_rejects_dangling_evidence_and_artifact_refs() -> None:
    state = _state()
    dangling_candidate = replace(
        state.entity_candidates[0],
        evidence_refs=("missing_evidence",),
    )
    with pytest.raises(ProblemExtractionContextError) as candidate_error:
        _build_with_state(replace(state, entity_candidates=(dangling_candidate,)))
    assert candidate_error.value.code == "extraction.evidence_ref_unresolved"

    dangling_evidence = replace(state.evidence[0], artifact_id="missing_artifact")
    with pytest.raises(ProblemExtractionContextError) as artifact_error:
        _build_with_state(replace(state, evidence=(dangling_evidence,)))
    assert artifact_error.value.code == "extraction.evidence_ref_unresolved"


def test_provider_failure_only_appends_attempt_ledger() -> None:
    context = _source_context()
    ledger = ExtractionAttemptLedger.for_context(context)
    updated = ledger.append(context, _attempt(context))

    assert updated.base_context_id == context.manifest.context_id
    assert len(updated.attempts) == 1
    assert updated.attempts[0].result == "timeout"
    assert context.attempt_refs == ()
    assert context.manifest.parent_context_id is None


def test_attempt_ledger_is_idempotent_and_rejects_drift_or_wrong_base() -> None:
    context = _source_context()
    ledger = ExtractionAttemptLedger.for_context(context)
    attempt = _attempt(context)
    once = ledger.append(context, attempt)

    assert once.append(context, attempt) is once
    with pytest.raises(ProblemExtractionContextError) as drift:
        once.append(context, replace(attempt, latency_ms=11))
    assert drift.value.code == "extraction.attempt_ledger_mismatch"

    other = _source_context()
    other = replace(
        other,
        manifest=replace(
            other.manifest,
            context_id="extraction-context:" + "f" * 64,
        ),
    )
    with pytest.raises(ProblemExtractionContextError) as wrong_base:
        ledger.append(other, attempt)
    assert wrong_base.value.code == "extraction.attempt_ledger_mismatch"


def test_semantic_patch_is_atomic_deterministic_and_creates_child_context() -> None:
    context = _source_context(with_state=True)
    ledger = ExtractionAttemptLedger.for_context(context).append(
        context,
        _attempt(context, result="succeeded"),
    )
    goal = ExtractionCandidateRecord(
        candidate_id="goal_A",
        candidate_type="goal",
        status="proposed",
        evidence_refs=("evidence_1",),
        locked=False,
        payload={"target": "entity_A"},
    )
    patch = ExtractionStatePatch(
        patch_id="patch_add_goal",
        base_context_id=context.manifest.context_id,
        candidate_changes=(
            ExtractionCandidateChange("upsert", goal.candidate_id, goal),
        ),
        decisions=(
            ExtractionDecision(
                decision_id="decision_add_goal",
                action="accept_candidate_patch",
                candidate_ids=(goal.candidate_id,),
                evidence_ids=("evidence_1",),
            ),
        ),
    )
    service = ProblemExtractionContextTransitionService()

    first = service.apply_patch(context, patch, attempt_ledger=ledger)
    second = service.apply_patch(context, patch, attempt_ledger=ledger)

    assert first == second
    assert first.manifest.context_id == second.manifest.context_id
    assert first.manifest.parent_context_id == context.manifest.context_id
    assert {item.candidate_id for item in first.state.goal_candidates} == {"goal_A"}
    assert first.attempt_refs == (ledger.attempts[0].to_ref(),)
    assert first.retry.attempts_used == 1
    assert context.state.goal_candidates == ()

    with pytest.raises(ProblemExtractionContextError) as reapplied:
        service.apply_patch(
            first,
            patch,
            attempt_ledger=ledger,
            ancestor_contexts=(context,),
        )
    assert reapplied.value.code == "extraction.patch_base_mismatch"


def test_successive_patches_preserve_attempt_lineage_and_cumulative_usage() -> None:
    context = _source_context()
    service = ProblemExtractionContextTransitionService()
    first_ledger = ExtractionAttemptLedger.for_context(context).append(
        context,
        _attempt(context, attempt_id="attempt_1", result="succeeded"),
    )
    first = service.apply_patch(
        context,
        ExtractionStatePatch("patch_1", context.manifest.context_id),
        attempt_ledger=first_ledger,
    )
    second_ledger = ExtractionAttemptLedger.for_context(first).append(
        first,
        _attempt(first, attempt_id="attempt_2", result="succeeded"),
    )

    second = service.apply_patch(
        first,
        ExtractionStatePatch("patch_2", first.manifest.context_id),
        attempt_ledger=second_ledger,
        ancestor_contexts=(context,),
    )

    assert second.attempt_refs == (
        first_ledger.attempts[0].to_ref(),
        second_ledger.attempts[0].to_ref(),
    )
    assert second.retry.attempts_used == 2
    assert (
        ProblemExtractionContext.from_payload(
            second.to_payload(),
            ancestor_contexts=(context, first),
        )
        == second
    )


def test_attempt_budget_is_enforced_by_ledger_transition_and_hydrate() -> None:
    no_budget = _source_context(attempt_budget=0)
    attempt = _attempt(no_budget, result="succeeded")

    with pytest.raises(ProblemExtractionContextError) as append_error:
        ExtractionAttemptLedger.for_context(no_budget).append(no_budget, attempt)
    assert append_error.value.code == "extraction.attempt_ledger_mismatch"

    direct_ledger = ExtractionAttemptLedger(
        base_context_id=no_budget.manifest.context_id,
        attempts=(attempt,),
    )
    with pytest.raises(ProblemExtractionContextError) as transition_error:
        ProblemExtractionContextTransitionService().apply_patch(
            no_budget,
            ExtractionStatePatch("patch_over_budget", no_budget.manifest.context_id),
            attempt_ledger=direct_ledger,
        )
    assert transition_error.value.code == "extraction.attempt_ledger_mismatch"

    context = _source_context(attempt_budget=1)
    ledger = ExtractionAttemptLedger.for_context(context).append(
        context,
        _attempt(context, result="succeeded"),
    )
    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        ExtractionStatePatch("patch_at_budget", context.manifest.context_id),
        attempt_ledger=ledger,
    )
    with pytest.raises(ProblemExtractionContextError) as cumulative_error:
        ExtractionAttemptLedger.for_context(child).append(
            child,
            _attempt(child, attempt_id="attempt_2", result="succeeded"),
        )
    assert cumulative_error.value.code == "extraction.attempt_ledger_mismatch"

    payload = child.to_payload()
    payload["retry"]["attempt_budget"] = 0

    with pytest.raises(ProblemExtractionContextError) as hydrate_error:
        ProblemExtractionContext.from_payload(
            payload,
            ancestor_contexts=(context,),
        )
    assert hydrate_error.value.code == "extraction.attempt_ledger_mismatch"


def test_patch_cannot_create_a_new_locked_accepted_candidate() -> None:
    state = _state()
    context = _build_with_state(replace(state, entity_candidates=()))
    candidate = state.entity_candidates[0]
    patch = ExtractionStatePatch(
        patch_id="patch_inject_locked_A",
        base_context_id=context.manifest.context_id,
        candidate_changes=(
            ExtractionCandidateChange("upsert", candidate.candidate_id, candidate),
        ),
    )

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContextTransitionService().apply_patch(
            context,
            patch,
            attempt_ledger=ExtractionAttemptLedger.for_context(context),
        )

    assert exc_info.value.code == "extraction.locked_candidate_mutation"


def test_attempt_ref_hash_tampering_fails_at_attempt_boundary() -> None:
    context = _source_context(attempt_budget=1)
    ledger = ExtractionAttemptLedger.for_context(context).append(
        context,
        _attempt(context, result="succeeded"),
    )
    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        ExtractionStatePatch("patch_with_attempt", context.manifest.context_id),
        attempt_ledger=ledger,
    )
    payload = child.to_payload()
    payload["attempt_refs"][0]["attempt_hash"] = "f" * 64

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContext.from_payload(
            payload,
            ancestor_contexts=(context,),
        )

    assert exc_info.value.code == "extraction.attempt_ledger_mismatch"


def test_attempt_ref_artifact_tampering_fails_at_attempt_boundary() -> None:
    context = _source_context(attempt_budget=1)
    ledger = ExtractionAttemptLedger.for_context(context).append(
        context,
        _attempt(context, result="succeeded"),
    )
    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        ExtractionStatePatch("patch_with_attempt", context.manifest.context_id),
        attempt_ledger=ledger,
    )
    payload = child.to_payload()
    payload["attempt_refs"][0]["authority"]["output_artifact_refs"][0][
        "sha256"
    ] = "c" * 64

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContext.from_payload(
            payload,
            ancestor_contexts=(context,),
        )

    assert exc_info.value.code == "extraction.attempt_ledger_mismatch"


def test_attempt_ref_rejects_self_consistent_foreign_base_context() -> None:
    context = _source_context(attempt_budget=1)
    ledger = ExtractionAttemptLedger.for_context(context).append(
        context,
        _attempt(context, result="succeeded"),
    )
    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        ExtractionStatePatch("patch_with_attempt", context.manifest.context_id),
        attempt_ledger=ledger,
    )
    payload = child.to_payload()
    authority = payload["attempt_refs"][0]["authority"]
    authority["base_context_id"] = "extraction-context:" + "0" * 64
    payload["attempt_refs"][0]["attempt_hash"] = stable_hash(authority)

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContext.from_payload(
            payload,
            ancestor_contexts=(context,),
        )

    assert exc_info.value.code == "extraction.attempt_ledger_mismatch"


def test_child_hydrate_requires_exact_parent_context_lineage() -> None:
    context = _source_context()
    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        ExtractionStatePatch("patch_child", context.manifest.context_id),
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )

    with pytest.raises(ProblemExtractionContextError) as missing_parent:
        ProblemExtractionContext.from_payload(child.to_payload())
    assert missing_parent.value.code == "extraction.context_lineage_unresolved"

    payload = child.to_payload()
    payload["manifest"]["ancestor_context_ids"].insert(
        0,
        "extraction-context:" + "0" * 64,
    )
    with pytest.raises(ProblemExtractionContextError) as forged_ancestor:
        ProblemExtractionContext.from_payload(
            payload,
            ancestor_contexts=(context,),
        )
    assert forged_ancestor.value.code == "extraction.context_lineage_unresolved"


def test_grandchild_hydrate_requires_root_to_parent_lineage() -> None:
    root = _source_context()
    service = ProblemExtractionContextTransitionService()
    parent = service.apply_patch(
        root,
        ExtractionStatePatch("patch_parent", root.manifest.context_id),
        attempt_ledger=ExtractionAttemptLedger.for_context(root),
    )
    child = service.apply_patch(
        parent,
        ExtractionStatePatch("patch_child", parent.manifest.context_id),
        attempt_ledger=ExtractionAttemptLedger.for_context(parent),
        ancestor_contexts=(root,),
    )

    with pytest.raises(ProblemExtractionContextError) as incomplete_lineage:
        ProblemExtractionContext.from_payload(
            child.to_payload(),
            ancestor_contexts=(parent,),
        )

    assert incomplete_lineage.value.code == "extraction.context_lineage_unresolved"


def test_child_rejects_parent_with_internally_inconsistent_state() -> None:
    context = _source_context(with_state=True)
    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        ExtractionStatePatch("patch_child", context.manifest.context_id),
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )
    phantom = replace(
        context.state.entity_candidates[0],
        candidate_id="ent_PHANTOM",
        payload={"label": "PHANTOM"},
    )
    tampered_parent = replace(
        context,
        state=replace(
            context.state,
            entity_candidates=context.state.entity_candidates + (phantom,),
        ),
    )

    with pytest.raises(ProblemExtractionContextError) as hydrate_error:
        ProblemExtractionContext.from_payload(
            child.to_payload(),
            ancestor_contexts=(tampered_parent,),
        )
    assert hydrate_error.value.code == "extraction.context_hash_mismatch"

    with pytest.raises(ProblemExtractionContextError) as transition_error:
        ProblemExtractionContextTransitionService().apply_patch(
            tampered_parent,
            ExtractionStatePatch(
                "patch_from_tampered_parent",
                tampered_parent.manifest.context_id,
            ),
            attempt_ledger=ExtractionAttemptLedger.for_context(tampered_parent),
        )
    assert transition_error.value.code == "extraction.context_hash_mismatch"


def test_non_root_context_requires_complete_lineage_to_continue_transition() -> None:
    root = _source_context()
    child = ProblemExtractionContextTransitionService().apply_patch(
        root,
        ExtractionStatePatch("patch_child", root.manifest.context_id),
        attempt_ledger=ExtractionAttemptLedger.for_context(root),
    )
    ghost_id = "extraction-context:" + "f" * 64
    provisional_manifest = replace(
        child.manifest,
        context_id="",
        parent_context_id=ghost_id,
        ancestor_context_ids=(ghost_id,),
    )
    forged = replace(
        child,
        manifest=replace(
            provisional_manifest,
            context_id=_context_id(
                manifest=provisional_manifest,
                selection=child.selection,
                decisions=child.decisions,
                events=child.events,
                attempt_refs=child.attempt_refs,
                retry=child.retry,
                projection=child.projection,
                quality=child.quality,
            ),
        ),
    )

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContextTransitionService().apply_patch(
            forged,
            ExtractionStatePatch(
                "patch_from_ghost_lineage",
                forged.manifest.context_id,
            ),
            attempt_ledger=ExtractionAttemptLedger.for_context(forged),
        )

    assert exc_info.value.code == "extraction.context_lineage_unresolved"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("mode", "user_adjusted"),
        ("revision", 2),
        ("parent_selection_id", "selection:" + "a" * 64),
    ),
)
def test_selection_audit_tampering_invalidates_context(
    field: str,
    value: object,
) -> None:
    context = _source_context()
    payload = context.to_payload()
    original_selection_id = payload["selection"]["selection_id"]
    payload["selection"][field] = value

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContext.from_payload(payload)

    assert payload["selection"]["selection_id"] == original_selection_id
    assert exc_info.value.code == "extraction.context_hash_mismatch"


def test_locked_candidate_requires_explicit_blocking_issue_authorization() -> None:
    context = _source_context(with_state=True)
    revised = replace(
        context.state.entity_candidates[0],
        payload={"label": "A_prime"},
    )
    patch = ExtractionStatePatch(
        patch_id="patch_revise_A",
        base_context_id=context.manifest.context_id,
        candidate_changes=(
            ExtractionCandidateChange("upsert", revised.candidate_id, revised),
        ),
    )
    service = ProblemExtractionContextTransitionService()
    ledger = ExtractionAttemptLedger.for_context(context)

    with pytest.raises(ProblemExtractionContextError) as locked:
        service.apply_patch(context, patch, attempt_ledger=ledger)
    assert locked.value.code == "extraction.locked_candidate_mutation"
    assert context.state.entity_candidates[0].payload["label"] == "A"


def test_blocking_issue_can_authorize_locked_candidate_revision() -> None:
    context = _build_with_state(_state(authorized=True))
    revised = replace(
        context.state.entity_candidates[0],
        payload={"label": "A_prime"},
    )
    patch = ExtractionStatePatch(
        patch_id="patch_revise_A",
        base_context_id=context.manifest.context_id,
        candidate_changes=(
            ExtractionCandidateChange("upsert", revised.candidate_id, revised),
        ),
        issue_resolutions=("issue_revise_A",),
        decisions=(
            ExtractionDecision(
                "decision_revise_A",
                "revise_candidate",
                candidate_ids=(revised.candidate_id,),
                evidence_ids=("evidence_1",),
            ),
        ),
    )

    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        patch,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )

    assert child.state.entity_candidates[0].payload["label"] == "A_prime"
    assert child.state.issues == ()


def test_historical_decision_does_not_prevent_authorized_candidate_removal() -> None:
    state = _state(authorized=True)
    remove_issue = replace(state.issues[0], issue_id="issue_remove_A")
    context = _build_with_state(
        replace(state, issues=state.issues + (remove_issue,))
    )
    revised = replace(
        context.state.entity_candidates[0],
        payload={"label": "A_prime"},
    )
    service = ProblemExtractionContextTransitionService()
    first = service.apply_patch(
        context,
        ExtractionStatePatch(
            patch_id="patch_revise_A",
            base_context_id=context.manifest.context_id,
            candidate_changes=(
                ExtractionCandidateChange("upsert", revised.candidate_id, revised),
            ),
            issue_resolutions=("issue_revise_A",),
            decisions=(
                ExtractionDecision(
                    "decision_revise_A",
                    "revise_candidate",
                    candidate_ids=(revised.candidate_id,),
                    evidence_ids=("evidence_1",),
                ),
            ),
        ),
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )

    second = service.apply_patch(
        first,
        ExtractionStatePatch(
            patch_id="patch_remove_A",
            base_context_id=first.manifest.context_id,
            candidate_changes=(
                ExtractionCandidateChange("remove", revised.candidate_id),
            ),
            issue_resolutions=("issue_remove_A",),
        ),
        attempt_ledger=ExtractionAttemptLedger.for_context(first),
        ancestor_contexts=(context,),
    )

    assert second.state.entity_candidates == ()
    assert second.decisions == first.decisions
    assert (
        ProblemExtractionContext.from_payload(
            second.to_payload(),
            ancestor_contexts=(context, first),
        )
        == second
    )


@pytest.mark.parametrize("include_unchanged_upsert", (False, True))
def test_authorized_issue_requires_an_effective_candidate_revision(
    include_unchanged_upsert: bool,
) -> None:
    context = _build_with_state(_state(authorized=True))
    candidate_changes = ()
    if include_unchanged_upsert:
        candidate = context.state.entity_candidates[0]
        candidate_changes = (
            ExtractionCandidateChange("upsert", candidate.candidate_id, candidate),
        )
    patch = ExtractionStatePatch(
        patch_id="patch_empty_revision",
        base_context_id=context.manifest.context_id,
        candidate_changes=candidate_changes,
        issue_resolutions=("issue_revise_A",),
    )

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ProblemExtractionContextTransitionService().apply_patch(
            context,
            patch,
            attempt_ledger=ExtractionAttemptLedger.for_context(context),
        )

    assert exc_info.value.code == "extraction.patch_base_mismatch"


def test_blocking_issue_can_be_explicitly_dismissed_as_false_positive() -> None:
    context = _build_with_state(_state(authorized=True))
    patch = ExtractionStatePatch(
        patch_id="patch_dismiss_false_positive",
        base_context_id=context.manifest.context_id,
        issue_resolutions=("issue_revise_A",),
        decisions=(
            ExtractionDecision(
                decision_id="decision_dismiss_issue_revise_A",
                action="dismiss_issue_false_positive",
                candidate_ids=("entity_A",),
                evidence_ids=("evidence_1",),
                payload={"issue_id": "issue_revise_A"},
            ),
        ),
    )

    child = ProblemExtractionContextTransitionService().apply_patch(
        context,
        patch,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
    )

    assert child.state.entity_candidates == context.state.entity_candidates
    assert child.state.issues == ()


def test_attempt_record_rejects_bad_artifact_ref() -> None:
    context = _source_context()
    attempt = _attempt(context)
    bad_artifact = replace(attempt.output_artifact_refs[0], sha256="bad")

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        ExtractionAttemptLedger.for_context(context).append(
            context,
            replace(attempt, output_artifact_refs=(bad_artifact,)),
        )

    assert exc_info.value.code == "extraction.attempt_ledger_mismatch"


def _build_with_state(state: ExtractionState):
    baseline = _source_context()
    return ProblemExtractionContextBuilder.initial(
        source=baseline.source,
        selection=baseline.selection,
        dependency=baseline.dependency,
        state=state,
        retry=ExtractionRetryState(status="ready", attempt_budget=3),
    )
