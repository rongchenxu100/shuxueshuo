from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.context import (
    CONTEXT_SCHEMA_VERSION,
    ExtractionAttemptLedger,
    ProblemExtractionContext,
    SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemPromotionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_context import (
    ProblemDomainContextTransitionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
)

from _problem_extraction_f3_support import make_f3_fixture


ROOT = Path(__file__).resolve().parents[3]


def _domain_payload(case: str = "tj-2026-nankai-yimo-25") -> dict:
    return json.loads(
        (ROOT / "internal/problem-domain-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )


def test_context_v3_accepted_round_trip_has_verified_and_solver_authority(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    validation = ProblemDomainValidator().validate(ProblemDraft.create(_domain_payload()))
    verified = ProblemPromotionService().promote(validation.draft)
    projection = validation.projection
    assert projection is not None
    verified_artifact = store.put_json(kind="verified_problem", payload=verified.to_payload())
    solver_artifact = store.put_json(
        kind=SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
        payload=projection.to_payload(),
    )
    validation_artifact = store.put_json(
        kind="problem_validation_report", payload=validation.report.to_payload()
    )

    accepted = ProblemDomainContextTransitionService().accepted(
        context,
        verified_problem=verified,
        solver_projection=projection,
        verified_artifact=verified_artifact,
        solver_problem_projection_artifact=solver_artifact,
        validation_artifact=validation_artifact,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )
    payload = accepted.to_payload()
    hydrated = ProblemExtractionContext.from_payload(
        payload,
        ancestor_contexts=(fixture.context, context),
    )

    assert hydrated.to_payload() == payload
    assert hydrated.manifest.schema_version == CONTEXT_SCHEMA_VERSION
    assert hydrated.projection.status == "accepted"
    assert hydrated.projection.problem_draft_artifact_id is None
    assert hydrated.projection.solver_problem_projection_artifact_id == (
        hydrated.projection.solver_problem_ir_artifact_id
    )
    assert (
        next(
            item.kind
            for item in hydrated.state.artifacts
            if item.artifact_id
            == hydrated.projection.solver_problem_projection_artifact_id
        )
        == SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND
    )
    assert hydrated.projection.problem_revision_id == verified.revision_id
    assert hydrated.projection.problem_semantic_hash == verified.semantic_hash


def test_context_v3_blocked_round_trip_carries_only_last_draft(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    payload = _domain_payload("tj-2026-hexi-yimo-25")
    payload["family_id"] = "QuadraticPathMinimumSolver"
    validation = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    assert not validation.report.ok
    draft_artifact = store.put_json(kind="problem_draft", payload=validation.draft.to_payload())
    validation_artifact = store.put_json(
        kind="problem_validation_report", payload=validation.report.to_payload()
    )

    blocked = ProblemDomainContextTransitionService().blocked(
        context,
        draft=validation.draft,
        draft_artifact=draft_artifact,
        validation_artifact=validation_artifact,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )

    assert blocked.projection.status == "blocked"
    assert blocked.projection.problem_draft_artifact_id == draft_artifact.artifact_id
    assert blocked.projection.verified_problem_artifact_id is None
    assert blocked.projection.solver_problem_ir_artifact_id is None
    assert blocked.projection.problem_semantic_hash is None
    assert blocked.retry.status == "blocked"
    assert ProblemExtractionContext.from_payload(
        blocked.to_payload(), ancestor_contexts=(fixture.context, context)
    ).to_payload() == blocked.to_payload()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("problem_revision_id", "problem-revision:" + "0" * 64),
        ("verified_problem_artifact_id", "artifact:missing:" + "0" * 64),
        ("problem_semantic_hash", "0" * 64),
    ),
)
def test_context_v3_rejects_projection_authority_tampering(tmp_path, field, value) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    validation = ProblemDomainValidator().validate(ProblemDraft.create(_domain_payload()))
    verified = ProblemPromotionService().promote(validation.draft)
    projection = validation.projection
    assert projection is not None
    accepted = ProblemDomainContextTransitionService().accepted(
        context,
        verified_problem=verified,
        solver_projection=projection,
        verified_artifact=store.put_json(kind="verified_problem", payload=verified.to_payload()),
        solver_problem_projection_artifact=store.put_json(
            kind=SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
            payload=projection.to_payload(),
        ),
        validation_artifact=store.put_json(kind="problem_validation_report", payload=validation.report.to_payload()),
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )
    tampered = deepcopy(accepted.to_payload())
    tampered["projection"][field] = value

    with pytest.raises(ProblemExtractionContextError):
        ProblemExtractionContext.from_payload(
            tampered,
            ancestor_contexts=(fixture.context, context),
        )


def test_context_v2_payload_is_intentionally_rejected() -> None:
    # No persisted production state exists, so v3 is a deliberate hard cut.
    from _problem_extraction_f2_support import make_fixture

    payload = make_fixture().context.to_payload()
    payload["manifest"]["schema_version"] = "problem-extraction-context/v2"

    with pytest.raises(ProblemExtractionContextError):
        ProblemExtractionContext.from_payload(payload)
