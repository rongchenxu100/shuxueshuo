from __future__ import annotations

import json
from pathlib import Path

from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
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

from _problem_extraction_f3_support import make_f3_fixture


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_FIXTURES = ROOT / "internal/problem-domain-fixtures"
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-heping-yimo-25",
)


def domain_payload(case: str) -> dict:
    return json.loads(
        (DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )


def accepted_bundle_fixture(
    tmp_path: Path,
    *,
    case: str = CASES[0],
    verified_payload: dict | None = None,
    projection_payload: dict | None = None,
    validation_payload: dict | None = None,
    verified_ref_update=None,
    projection_ref_update=None,
    validation_ref_update=None,
):
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    validation = ProblemDomainValidator().validate(
        ProblemDraft.create(domain_payload(case))
    )
    assert validation.report.ok and validation.projection is not None
    verified = ProblemPromotionService().promote(validation.draft)
    projection = validation.projection
    verified_ref = store.put_json(
        kind="verified_problem",
        payload=verified_payload or verified.to_payload(),
    )
    projection_ref = store.put_json(
        kind=SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
        payload=projection_payload or projection.to_payload(),
    )
    validation_ref = store.put_json(
        kind="problem_validation_report",
        payload=validation_payload or validation.report.to_payload(),
    )
    if verified_ref_update is not None:
        verified_ref = verified_ref_update(verified_ref)
    if projection_ref_update is not None:
        projection_ref = projection_ref_update(projection_ref)
    if validation_ref_update is not None:
        validation_ref = validation_ref_update(validation_ref)
    accepted = ProblemDomainContextTransitionService().accepted(
        context,
        verified_problem=verified,
        solver_projection=projection,
        verified_artifact=verified_ref,
        solver_problem_projection_artifact=projection_ref,
        validation_artifact=validation_ref,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )
    return fixture.context, context, accepted, store, verified, projection, validation

