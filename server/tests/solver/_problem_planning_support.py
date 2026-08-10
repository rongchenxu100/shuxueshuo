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
from shuxueshuo_server.solver.extraction.problem_planning_binding import (
    ProblemPlanningBindingCatalogBuilder,
)
from shuxueshuo_server.solver.extraction.problem_planning_context import (
    ProblemPlanningContextProjector,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    VerifiedSolverProblemBundleLoader,
)
from shuxueshuo_server.solver.runtime.handle_registry import (
    CanonicalHandleRegistry,
)
from shuxueshuo_server.solver.runtime.functional_plan_reconciliation import (
    FunctionalPlanReconciler,
)
from shuxueshuo_server.solver.runtime.functional_plan_validation import (
    FunctionalPlanValidator,
)
from shuxueshuo_server.solver.runtime.planner_state_context import (
    initial_planner_state_context,
)
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload
from shuxueshuo_server.solver.runtime.strategy_payload import (
    build_strategy_probe_inputs,
)

from _problem_extraction_f3_support import make_f3_fixture


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_FIXTURES = ROOT / "internal/problem-domain-fixtures"
SCOPE_NATIVE_FIXTURES = ROOT / "internal/functional-plan-scope-native-fixtures"
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


def planning_binding_fixture(tmp_path: Path, *, case: str = CASES[0]):
    root, parent, accepted, store, *_ = accepted_bundle_fixture(
        tmp_path,
        case=case,
    )
    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
    )
    planning_context = ProblemPlanningContextProjector().project(bundle)
    problem = bundle.build_solver_problem()
    inputs = build_strategy_probe_inputs(problem)
    problem_payload = problem_to_llm_payload(problem)
    registry = CanonicalHandleRegistry.from_problem_payload(problem_payload)
    planner_context = initial_planner_state_context(
        inputs,
        problem_payload=problem_payload,
        handle_registry=registry,
    )
    binding_catalog = ProblemPlanningBindingCatalogBuilder().build(
        bundle,
        planning_context,
        planner_context,
        registry,
    )
    return (
        bundle,
        planning_context,
        problem,
        inputs,
        problem_payload,
        registry,
        planner_context,
        binding_catalog,
    )


def scope_native_reconciliation_fixture(
    tmp_path: Path,
    *,
    case: str = CASES[0],
    plan_payload: dict | None = None,
):
    fixture = planning_binding_fixture(tmp_path, case=case)
    (
        _bundle,
        _planning_context,
        _problem,
        inputs,
        _problem_payload,
        registry,
        planner_context,
        binding_catalog,
    ) = fixture
    payload = plan_payload or json.loads(
        (SCOPE_NATIVE_FIXTURES / f"{case}.functional-plan.json").read_text(
            encoding="utf-8"
        )
    )
    plan, validation = FunctionalPlanValidator().validate_payload_with_report(
        payload,
        handle_registry=registry,
        question_goals=inputs.question_goals,
    )
    assert validation.ok and plan is not None, validation.to_payload()
    reconciliation = FunctionalPlanReconciler().reconcile(
        plan,
        planner_state_context=planner_context,
        family_spec=inputs.family_spec,
        method_specs=inputs.method_specs,
        handle_registry=registry,
        question_goals=inputs.question_goals,
        problem_binding_catalog=binding_catalog,
    )
    return (*fixture, plan, validation, reconciliation)
