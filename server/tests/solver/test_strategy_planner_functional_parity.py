from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from shuxueshuo_server.solver.deepseek_functional_batch import (
    FUNCTIONAL_BATCH_CASES,
)
from shuxueshuo_server.solver.functional_parity import (
    FunctionalParityRunner,
    compare_provenance_signatures,
    provenance_parity_signature,
)
from shuxueshuo_server.solver.runtime.strategy_models import (
    PlannerRetryIssue,
    PlannerRetryState,
    StateWriteProvenance,
    StepIntentExecutionDiagnostic,
)
from shuxueshuo_server.solver.runtime.session import (
    structured_error_from_exception,
)
from shuxueshuo_server.solver.runtime.strategy_replay import (
    PlannerRetryReplayResult,
)
from shuxueshuo_server.solver.runtime.strategy_runtime_planner import (
    _functional_planner_execution_error,
)
from shuxueshuo_server.solver.state_semantics import state_semantic_lineage
from shuxueshuo_server.solver.state_semantics import StateObjectRoleBinding


@pytest.mark.parametrize("case_id", tuple(FUNCTIONAL_BATCH_CASES))
def test_recorded_and_authored_functional_fixtures_have_provenance_parity(
    case_id: str,
) -> None:
    report = FunctionalParityRunner().compare_fixture(
        FUNCTIONAL_BATCH_CASES[case_id]
    )

    assert report.ok, report.to_payload()


def test_answer_identity_mismatch_is_reported() -> None:
    recorded = provenance_parity_signature(
        _diagnostic(_answer_write(step_id="recorded"))
    )
    functional = provenance_parity_signature(
        _diagnostic(
            replace(
                _answer_write(step_id="functional"),
                object_ref="point:part:Other",
            )
        )
    )

    mismatches = compare_provenance_signatures(recorded, functional)

    assert [item.path for item in mismatches] == [
        "answers.answer:part.point.object_ref",
        "logical_states.point:part:P/coordinate/Point",
    ]


def test_step_ids_and_source_handles_do_not_affect_provenance_parity() -> None:
    recorded = provenance_parity_signature(
        _diagnostic(_answer_write(step_id="recorded"))
    )
    functional = provenance_parity_signature(
        _diagnostic(
            replace(
                _answer_write(step_id="functional"),
                source_handles=("fact:part:renamed_alias",),
            )
        )
    )

    assert compare_provenance_signatures(recorded, functional) == ()


def test_duplicate_create_writers_in_one_logical_scope_are_rejected() -> None:
    first = replace(
        _answer_write(step_id="first"),
        produced_handle="fact:part:first_coordinate",
    )
    second = replace(
        first,
        step_id="second",
        produced_handle="answer:part.point",
    )

    signature = provenance_parity_signature(
        _diagnostic(first, second)
    )

    assert signature.integrity_issues == (
        "duplicate logical-state writer: "
        "point:part:P/coordinate/Point@part at second",
    )


def test_answer_identity_policy_role_evidence_and_dependency_are_required() -> None:
    recorded_write = replace(
        _answer_write(step_id="recorded"),
        dependency_object_refs=("point:problem:Source",),
        lineage=state_semantic_lineage(
            semantic_roles=("extremal_point",),
            evidence_tags=("minimum_witness",),
            object_roles=(
                StateObjectRoleBinding(
                    role="moving_object",
                    object_refs=("point:part:P",),
                ),
            ),
        ),
    )
    functional_write = replace(
        _answer_write(step_id="functional"),
        identity_policy="derived_role",
        lineage=state_semantic_lineage(),
    )

    mismatches = compare_provenance_signatures(
        provenance_parity_signature(_diagnostic(recorded_write)),
        provenance_parity_signature(_diagnostic(functional_write)),
    )

    assert [item.path for item in mismatches] == [
        "answers.answer:part.point.identity_policy",
        "answers.answer:part.point.semantic_roles",
        "answers.answer:part.point.evidence_tags",
        "answers.answer:part.point.dependency_object_refs",
        "answers.answer:part.point.object_roles.moving_object",
    ]


def test_functional_answer_missing_recorded_semantic_role_is_rejected() -> None:
    recorded_write = replace(
        _answer_write(step_id="recorded"),
        lineage=state_semantic_lineage(
            semantic_roles=("extremal_point",),
        ),
    )
    functional_write = _answer_write(step_id="functional")

    mismatches = compare_provenance_signatures(
        provenance_parity_signature(_diagnostic(recorded_write)),
        provenance_parity_signature(_diagnostic(functional_write)),
    )

    assert [item.path for item in mismatches] == [
        "answers.answer:part.point.semantic_roles",
    ]


def test_logical_state_writer_and_transition_sequence_are_compared() -> None:
    recorded = provenance_parity_signature(
        _diagnostic(_answer_write(step_id="recorded"))
    )
    first = replace(
        _answer_write(step_id="first"),
        produced_handle="fact:part:point",
    )
    transitioned_answer = replace(
        _answer_write(step_id="second"),
        write_mode="transition",
        previous_write_step_id="first",
    )
    functional = provenance_parity_signature(
        _diagnostic(first, transitioned_answer)
    )

    paths = {
        item.path
        for item in compare_provenance_signatures(recorded, functional)
    }

    assert (
        "logical_states.point:part:P/coordinate/Point.writer_count"
        in paths
    )
    assert (
        "logical_states.point:part:P/coordinate/Point.write_modes"
        in paths
    )


def test_missing_answer_reachable_logical_state_is_reported() -> None:
    source = replace(
        _answer_write(step_id="source"),
        produced_handle="fact:part:source_coordinate",
        object_ref="point:part:Source",
        state_slot_id="point:part:Source.coordinate@part:Point",
    )
    recorded_answer = replace(
        _answer_write(step_id="recorded"),
        lineage=state_semantic_lineage(
            semantic_roles=("point",),
            source_state_slot_ids=(source.state_slot_id,),
        ),
    )
    recorded = provenance_parity_signature(
        _diagnostic(source, recorded_answer)
    )
    functional = provenance_parity_signature(
        _diagnostic(_answer_write(step_id="functional"))
    )

    paths = [
        item.path
        for item in compare_provenance_signatures(recorded, functional)
    ]

    assert paths == [
        "logical_states.point:part:Source/coordinate/Point"
    ]


def test_logical_state_writer_count_includes_cross_scope_writes() -> None:
    first = replace(
        _answer_write(step_id="first"),
        produced_handle="fact:left:point",
        scope_id="left",
        state_slot_id="point:part:P.coordinate@left:Point",
    )
    second = replace(
        _answer_write(step_id="second"),
        scope_id="right",
        state_slot_id=first.state_slot_id,
        source_state_slot_ids=(first.state_slot_id,),
    )

    signature = provenance_parity_signature(
        _diagnostic(first, second),
        scope_parents={
            "problem": None,
            "left": "problem",
            "right": "problem",
        },
    )

    assert signature.logical_states[0].writer_count == 2


def test_logical_state_scope_must_cover_recorded_visibility() -> None:
    recorded = provenance_parity_signature(
        _diagnostic(
            replace(_answer_write(step_id="recorded"), scope_id="left")
        ),
        scope_parents={
            "problem": None,
            "left": "problem",
            "right": "problem",
        },
    )
    functional = provenance_parity_signature(
        _diagnostic(
            replace(_answer_write(step_id="functional"), scope_id="right")
        ),
        scope_parents={
            "problem": None,
            "left": "problem",
            "right": "problem",
        },
    )

    paths = [
        item.path
        for item in compare_provenance_signatures(recorded, functional)
    ]

    assert paths == [
        "logical_states.point:part:P/coordinate/Point.scopes"
    ]


def test_typed_functional_failure_preserves_root_layer_and_code() -> None:
    issue = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="functional.object_identity_mismatch",
        step_id="bad_call",
        message="objects differ",
    )
    replay = PlannerRetryReplayResult(
        attempt=1,
        retry_state=PlannerRetryState(
            attempt=1,
            baseline_draft=None,
            issues=(issue, issue),
            candidate_format="functional_plan",
        ),
    )

    exc = _functional_planner_execution_error(replay)
    error = structured_error_from_exception(stage="planner", exc=exc)

    assert error.stage == "functional_reconciliation"
    assert error.code == "functional.object_identity_mismatch"
    assert error.step_id == "bad_call"
    assert error.details["candidate_format"] == "functional_plan"
    assert error.details["root_issues"] == [issue.to_payload()]


def test_trial_blocker_is_primary_and_configuration_root_disables_retry() -> None:
    configuration = PlannerRetryIssue(
        layer="functional_reconciliation",
        code="planner_configuration_error",
        step_id="config_call",
        message="missing adapter",
    )
    replay = PlannerRetryReplayResult(
        attempt=1,
        retry_state=PlannerRetryState(
            attempt=1,
            baseline_draft=None,
            issues=(configuration,),
            candidate_format="functional_plan",
        ),
    )
    blocker = SimpleNamespace(
        stage="trial_execution",
        code="function.arg_type_mismatch",
        message="wrong runtime input",
        retryable=True,
        step_id="trial_call",
        capability_id="synthetic",
        details={"arg": "point"},
    )

    exc = _functional_planner_execution_error(replay, blocker=blocker)
    error = structured_error_from_exception(stage="planner", exc=exc)

    assert error.stage == "trial_execution"
    assert error.code == "function.arg_type_mismatch"
    assert error.retryable is False
    assert error.details["root_issues"] == [configuration.to_payload()]


def _answer_write(*, step_id: str) -> StateWriteProvenance:
    return StateWriteProvenance(
        step_id=step_id,
        scope_id="part",
        capability_id="synthetic_point",
        produced_handle="answer:part.point",
        output_key="point",
        runtime_type="Point",
        identity_policy="target_object",
        identity_role="point",
        object_ref="point:part:P",
        source_handles=("point:part:P",),
        state_slot_id="point:part:P.coordinate@part:Point",
        write_mode="create",
        lineage=state_semantic_lineage(semantic_roles=("point",)),
    )


def _diagnostic(
    *writes: StateWriteProvenance,
) -> StepIntentExecutionDiagnostic:
    return StepIntentExecutionDiagnostic(
        ok=True,
        state_write_provenance=tuple(writes),
    )
