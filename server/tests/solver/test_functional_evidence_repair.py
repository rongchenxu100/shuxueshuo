from __future__ import annotations

from types import SimpleNamespace

from shuxueshuo_server.solver.runtime.functional_repair_feedback import (
    apply_capability_repair_feedback,
    CapabilityRepairFeedbackContext,
    CapabilityRepairFeedbackProviderError,
    ExpressionStateTransitionFeedbackProvider,
    LineIntersectionEvidenceFeedbackProvider,
    _validated_feedback,
    validate_capability_repair_feedback_provider_ids,
)
from shuxueshuo_server.solver.runtime.strategy_models import PlannerRetryIssue
import pytest


def test_line_intersection_provider_only_enhances_existing_issue() -> None:
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.evidence_closure_unproven",
        step_id="intersect",
        message="evidence is incomplete",
    )
    contribution = LineIntersectionEvidenceFeedbackProvider().build(
        CapabilityRepairFeedbackContext(
            capability_id="line_intersection_point",
            capability_kind="function",
            issue=issue,
            evidence_evaluation={
                "missing_roles": ["straightened_endpoint_2"],
                "missing_evidence_tags": [],
                "missing_object_roles": [],
                "matched_roles": ["straightened_endpoint_1"],
            },
            compatible_refs=("straighten.straightened_endpoint_2",),
            repair_call_ids=("evaluate_endpoint", "intersect"),
            locked_call_ids=("straighten",),
        )
    )

    assert contribution is not None
    payload = _validated_feedback(
        contribution,
        known_call_ids={"straighten", "evaluate_endpoint", "intersect"},
        locked_call_ids={"straighten"},
    )
    assert payload["compatible_refs"] == [
        "straighten.straightened_endpoint_2"
    ]
    assert payload["additional_repair_call_ids"] == [
        "evaluate_endpoint",
        "intersect",
    ]
    assert issue.code == "functional.evidence_closure_unproven"


def test_expression_provider_explains_dynamic_state_transition() -> None:
    issue = PlannerRetryIssue(
        layer="trial_execution",
        code="function.transition_previous_write_mismatch",
        step_id="evaluate_state",
        message="state chain conflict",
        details={
            "error_code": "function.transition_previous_write_mismatch",
            "state_value_type": "Parabola",
            "expected_previous_call_id": "shared_state",
            "actual_previous_call_id": "alternate_state",
            "consumer_call_id": "evaluate_state",
        },
    )

    contribution = ExpressionStateTransitionFeedbackProvider().build(
        CapabilityRepairFeedbackContext(
            capability_id="evaluate_expression_at_parameter",
            capability_kind="function",
            issue=issue,
            repair_call_ids=("alternate_state", "evaluate_state"),
            locked_call_ids=("shared_state",),
        )
    )

    assert contribution is not None
    assert "Parabola" in contribution.explanation
    assert contribution.expected == {
        "previous_call": "shared_state",
        "consumer_call": "evaluate_state",
    }
    assert contribution.actual == {"previous_call": "alternate_state"}
    assert contribution.additional_repair_call_ids == (
        "alternate_state",
        "evaluate_state",
    )


def test_expression_provider_explains_symbol_identity_mismatch() -> None:
    issue = PlannerRetryIssue(
        layer="trial_execution",
        code="function.substitution_symbol_mismatch",
        step_id="evaluate_expression",
        message="wrong Symbol identity",
        details={
            "error_code": "function.substitution_symbol_mismatch",
            "parameter_name": "a",
            "free_symbol_names": ["m"],
        },
    )

    contribution = ExpressionStateTransitionFeedbackProvider().build(
        CapabilityRepairFeedbackContext(
            capability_id="evaluate_expression_at_parameter",
            capability_kind="function",
            issue=issue,
            compatible_refs=("solve_m.parameter_value",),
            repair_call_ids=("evaluate_expression",),
        )
    )

    assert contribution is not None
    assert contribution.expected == {"free_symbols": ["m"]}
    assert contribution.actual == {"parameter": "a"}
    assert contribution.compatible_refs == ("solve_m.parameter_value",)


def test_feedback_rejects_internal_state_identifiers() -> None:
    from shuxueshuo_server.solver.runtime.functional_repair_feedback import (
        CapabilityRepairFeedbackContribution,
    )

    with pytest.raises(
        CapabilityRepairFeedbackProviderError,
        match="provider returned internal",
    ):
        _validated_feedback(
            CapabilityRepairFeedbackContribution(
                explanation="read StateSlot internal state",
            ),
            known_call_ids=set(),
            locked_call_ids=set(),
        )


def test_feedback_service_preserves_issue_authority_and_locked_calls() -> None:
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.evidence_closure_unproven",
        step_id="intersect",
        message="evidence is incomplete",
        details={
            "evidence_gap": {
                "missing_roles": ["straightened_endpoint_2"],
                "missing_evidence_tags": [],
                "missing_object_roles": [],
                "matched_roles": [],
            },
            "compatible_refs": ["straighten.straightened_endpoint_2"],
            "repair_call_ids": ["straighten", "evaluate_endpoint", "intersect"],
            "locked_result_refs": ["locked_from_attach.point"],
            "locked_context_call_ids": ["locked_from_attach"],
        },
    )
    call = SimpleNamespace(
        call_id="intersect",
        capability_id="line_intersection_point",
    )
    plan = SimpleNamespace(
        calls=(
            SimpleNamespace(
                call_id="straighten",
                capability_id="straightening",
            ),
            SimpleNamespace(
                call_id="evaluate_endpoint",
                capability_id="evaluate_point",
            ),
            SimpleNamespace(
                call_id="locked_from_attach",
                capability_id="existing_point",
            ),
            call,
        )
    )
    capability = SimpleNamespace(
        capability_id="line_intersection_point",
        kind="function",
        source=SimpleNamespace(
            repair_feedback_provider_id="line_intersection_evidence"
        ),
    )
    catalog = SimpleNamespace(
        get=lambda capability_id: (
            capability if capability_id == capability.capability_id else None
        )
    )
    reconciliation = SimpleNamespace(
        dependency_graph={"intersect": ("evaluate_endpoint",)}
    )

    enriched = apply_capability_repair_feedback(
        (issue,),
        plan=plan,
        reconciliation=reconciliation,
        catalog=catalog,
        locked_call_ids=("straighten", "locked_from_attach"),
    )

    assert enriched[0].code == issue.code
    assert enriched[0].layer == issue.layer
    assert enriched[0].details["repair_feedback"][
        "additional_repair_call_ids"
    ] == ["evaluate_endpoint", "intersect"]
    assert "straighten" not in enriched[0].details["repair_call_ids"]
    assert enriched[0].details["locked_context_call_ids"] == [
        "locked_from_attach",
        "straighten",
    ]
    assert enriched[0].details["locked_result_refs"] == [
        "locked_from_attach.point"
    ]


def test_feedback_service_without_provider_uses_generic_issue_unchanged() -> None:
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.arg_type_mismatch",
        step_id="call",
        message="wrong type",
    )
    call = SimpleNamespace(call_id="call", capability_id="capability")
    capability = SimpleNamespace(
        capability_id="capability",
        kind="function",
        source=SimpleNamespace(repair_feedback_provider_id=None),
    )

    enriched = apply_capability_repair_feedback(
        (issue,),
        plan=SimpleNamespace(calls=(call,)),
        reconciliation=SimpleNamespace(dependency_graph={}),
        catalog=SimpleNamespace(get=lambda _capability_id: capability),
        locked_call_ids=(),
    )

    assert enriched == (issue,)


def test_closed_state_issue_uses_bounded_generic_feedback() -> None:
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.arg_state_open",
        step_id="consume_state",
        message="input state remains open",
        details={
            "arg": "point",
            "producer_call_id": "produce_open_state",
            "free_symbol_refs": ["symbol:parameter"],
            "repair_call_ids": [
                "produce_open_state",
                "consume_state",
            ],
        },
    )
    calls = (
        SimpleNamespace(
            call_id="produce_open_state",
            capability_id="producer",
        ),
        SimpleNamespace(
            call_id="consume_state",
            capability_id="consumer",
        ),
    )
    capability = SimpleNamespace(
        capability_id="consumer",
        kind="function",
        source=SimpleNamespace(repair_feedback_provider_id=None),
    )

    enriched = apply_capability_repair_feedback(
        (issue,),
        plan=SimpleNamespace(calls=calls),
        reconciliation=SimpleNamespace(
            dependency_graph={
                "produce_open_state": (),
                "consume_state": ("produce_open_state",),
            }
        ),
        catalog=SimpleNamespace(
            get=lambda capability_id: (
                capability if capability_id == "consumer" else None
            )
        ),
        locked_call_ids=(),
    )

    feedback = enriched[0].details["repair_feedback"]
    assert feedback["expected"]["form"] == "closed_state"
    assert feedback["actual"]["free_parameters"] == ["symbol:parameter"]
    assert feedback["additional_repair_call_ids"] == [
        "produce_open_state",
        "consume_state",
    ]
    assert len(enriched[0].hints) == 2


def test_unknown_feedback_provider_fails_catalog_preflight() -> None:
    with pytest.raises(
        CapabilityRepairFeedbackProviderError,
        match="unknown provider",
    ):
        validate_capability_repair_feedback_provider_ids(("missing",))
