from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.context import (
    ExtractionArtifactRef,
    ExtractionAttemptLedger,
    ProblemExtractionContextBuilder,
    ExtractionState,
    SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemPromotionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_context import (
    ProblemDomainContextTransitionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    SolverProblemProjection,
    solver_problem_projection_schema,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityError,
    ProblemBundleAuthorityToken,
    VerifiedSolverProblemBundleLoader,
    _audit_projection_manifest,
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


def _domain_payload(case: str) -> dict:
    return json.loads(
        (DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )


def _accepted_fixture(
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
        ProblemDraft.create(_domain_payload(case))
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


@pytest.mark.parametrize("case", CASES)
def test_five_accepted_contexts_load_deterministic_bundles(tmp_path, case) -> None:
    root, parent, accepted, store, verified, projection, _ = _accepted_fixture(
        tmp_path / case,
        case=case,
    )
    loader = VerifiedSolverProblemBundleLoader()

    first = loader.load(accepted, store, ancestor_contexts=(root, parent))
    second = loader.load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
        expected_token=first.authority_token,
    )

    assert first.authority_token == second.authority_token
    assert first.authority_token.problem_revision_id == verified.revision_id
    assert first.projection_manifest.to_payload() == projection.manifest.to_payload()
    unit_ids = {
        item["unit_id"]
        for item in verified.to_payload()["unit_registry"]
        if item["unit_kind"] != "family"
    }
    assert set(first.projection_index.source_unit_runtime_nodes) == unit_ids
    assert all(first.projection_index.source_unit_runtime_nodes.values())


def test_bundle_accepts_audited_child_with_nonterminal_acceptance_event(
    tmp_path,
) -> None:
    root, parent, accepted, store, _, _, _ = _accepted_fixture(tmp_path)
    audited = ProblemExtractionContextBuilder.trusted_child(
        accepted,
        state=accepted.state,
        attempt_ledger=ExtractionAttemptLedger.for_context(accepted),
        event="bundle_materialized",
        event_payload={"audit": "passed"},
        ancestor_contexts=(root, parent),
        producer="problem_bundle_audit",
        producer_version="v1",
        projection=accepted.projection,
        retry=accepted.retry,
    )

    bundle = VerifiedSolverProblemBundleLoader().load(
        audited,
        store,
        ancestor_contexts=(root, parent, accepted),
    )

    assert audited.events[-1].event == "bundle_materialized"
    assert bundle.authority_token.extraction_context_id == audited.manifest.context_id


def test_folded_function_and_point_facts_keep_runtime_provenance(tmp_path) -> None:
    root, parent, accepted, store, verified, _, _ = _accepted_fixture(
        tmp_path,
        case="tj-2026-heping-yimo-25",
    )
    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
    )
    facts = [
        fact
        for scope in verified.graph.root_scope.iter_scopes()
        for fact in scope.facts
        if fact.kind in {"function_expression", "point_construction"}
    ]

    assert facts
    for fact in facts:
        handles = bundle.projection_index.source_unit_runtime_nodes[fact.unit_id]
        assert any(handle.startswith(("function:", "point:")) for handle in handles)


def test_bundle_materializes_fresh_solver_problem_instances(tmp_path) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path)
    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
    )

    first = bundle.build_solver_problem()
    first.original_text["lines"].append("pollution")
    second = bundle.build_solver_problem()

    assert "pollution" not in second.original_text["lines"]
    assert "pollution" not in bundle.canonical_solver_input["original_text"]["lines"]


def test_pending_context_cannot_form_bundle(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            context,
            store,
            ancestor_contexts=(fixture.context,),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


def test_old_unversioned_solver_projection_is_rejected(tmp_path) -> None:
    payload = ProblemDomainValidator().validate(
        ProblemDraft.create(_domain_payload(CASES[0]))
    ).projection.to_payload()
    del payload["schema_version"]
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path,
        projection_payload=payload,
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


def test_bundle_rejects_wrong_artifact_media_type(tmp_path) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path,
        projection_ref_update=lambda ref: replace(ref, media_type="text/plain"),
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


def test_bundle_rejects_corrupted_artifact_bytes(tmp_path) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path)
    artifact_id = accepted.projection.solver_problem_projection_artifact_id
    artifact = next(item for item in accepted.state.artifacts if item.artifact_id == artifact_id)
    assert artifact.locator is not None
    Path(artifact.locator).write_bytes(b"{}")

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


def test_bundle_rejects_artifact_locator_outside_store(tmp_path) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path)
    artifact_id = accepted.projection.solver_problem_projection_artifact_id
    artifacts = tuple(
        replace(item, locator=str(tmp_path / "outside.json"))
        if item.artifact_id == artifact_id
        else item
        for item in accepted.state.artifacts
    )
    escaped = replace(
        accepted,
        state=ExtractionState(
            artifacts=artifacts,
            evidence=accepted.state.evidence,
            issues=accepted.state.issues,
        ),
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            escaped,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


def test_bundle_rejects_validly_hashed_malformed_json(tmp_path) -> None:
    root, parent, _, store, verified, projection, validation = _accepted_fixture(
        tmp_path
    )
    malformed = store.put_bytes(
        kind=SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
        content=b"{",
        media_type="application/json",
        suffix=".json",
    )
    accepted = ProblemDomainContextTransitionService().accepted(
        parent,
        verified_problem=verified,
        solver_projection=projection,
        verified_artifact=store.put_json(
            kind="verified_problem", payload=verified.to_payload()
        ),
        solver_problem_projection_artifact=malformed,
        validation_artifact=store.put_json(
            kind="problem_validation_report",
            payload=validation.report.to_payload(),
        ),
        attempt_ledger=ExtractionAttemptLedger.for_context(parent),
        ancestor_contexts=(root,),
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


def test_validation_artifact_must_equal_verified_proof(tmp_path) -> None:
    validation = ProblemDomainValidator().validate(
        ProblemDraft.create(_domain_payload(CASES[0]))
    )
    payload = validation.report.to_payload()
    payload["validator_ids"] = []
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path,
        validation_payload=payload,
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_bundle_invalid"


@pytest.mark.parametrize("mutation", ("missing_node", "unknown_source", "goal_alias"))
def test_manifest_drift_fails_loud(tmp_path, mutation) -> None:
    validation = ProblemDomainValidator().validate(
        ProblemDraft.create(_domain_payload("tj-2026-nankai-yimo-25"))
    )
    payload = validation.projection.to_payload()
    sources = payload["manifest"]["runtime_node_sources"]
    if mutation == "missing_node":
        del sources[next(iter(sources))]
    elif mutation == "unknown_source":
        sources[next(iter(sources))] = ["fact:missing:" + "0" * 64]
    else:
        answer_handles = sorted(key for key in sources if key.startswith("answer:"))
        assert len(answer_handles) >= 2
        sources[answer_handles[1]] = list(sources[answer_handles[0]])
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path,
        projection_payload=payload,
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_projection_manifest_drift"


def test_manifest_revision_drift_fails_loud(tmp_path) -> None:
    validation = ProblemDomainValidator().validate(
        ProblemDraft.create(_domain_payload(CASES[0]))
    )
    payload = validation.projection.to_payload()
    payload["manifest"]["problem_revision_id"] = "problem-revision:" + "0" * 64
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path,
        projection_payload=payload,
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_revision_drift"


def test_value_object_sources_must_match_synthesized_runtime_entity(tmp_path) -> None:
    validation = ProblemDomainValidator().validate(
        ProblemDraft.create(_domain_payload(CASES[0]))
    )
    payload = validation.projection.to_payload()
    fact_handle = next(
        key
        for key in payload["manifest"]["runtime_node_sources"]
        if key.startswith("fact:")
    )
    payload["manifest"]["value_object_sources"][fact_handle] = list(
        payload["manifest"]["runtime_node_sources"][fact_handle]
    )
    root, parent, accepted, store, *_ = _accepted_fixture(
        tmp_path,
        projection_payload=payload,
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
        )

    assert error.value.code == "planner.problem_projection_manifest_drift"


def test_value_object_audit_uses_provenance_instead_of_runtime_entity_type(
    tmp_path,
) -> None:
    _, _, _, _, verified, projection, _ = _accepted_fixture(tmp_path)
    canonical = deepcopy(projection.canonical_input)
    value_handle = next(iter(projection.manifest.value_object_sources))
    value_entity = next(
        item for item in canonical["entities"] if item["handle"] == value_handle
    )
    value_entity["entity_type"] = "future_value_object"
    future_projection = SolverProblemProjection(
        canonical_input=canonical,
        problem=projection.problem,
        manifest=projection.manifest,
    )

    index = _audit_projection_manifest(verified, future_projection)

    assert value_handle in index.value_object_handles


def test_expected_bundle_token_detects_stale_restore(tmp_path) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path)
    expected = ProblemBundleAuthorityToken(
        extraction_context_id=accepted.manifest.context_id,
        dependency_hash=accepted.dependency.dependency_hash,
        problem_revision_id=str(accepted.projection.problem_revision_id),
        problem_semantic_hash=str(accepted.projection.problem_semantic_hash),
        bundle_id="verified-solver-problem-bundle:" + "0" * 64,
    )

    with pytest.raises(ProblemBundleAuthorityError) as error:
        VerifiedSolverProblemBundleLoader().load(
            accepted,
            store,
            ancestor_contexts=(root, parent),
            expected_token=expected,
        )

    assert error.value.code == "planner.problem_revision_drift"


def test_artifact_locator_relocation_does_not_change_bundle_identity(tmp_path) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path / "first")
    loader = VerifiedSolverProblemBundleLoader()
    first = loader.load(accepted, store, ancestor_contexts=(root, parent))
    second_store = ExtractionArtifactStore(tmp_path / "second" / "artifacts")
    replaced_refs: dict[str, ExtractionArtifactRef] = {}
    for artifact in accepted.state.artifacts:
        if artifact.media_type != "application/json":
            continue
        moved = second_store.put_bytes(
            kind=artifact.kind,
            content=store.read_bytes(artifact),
            media_type="application/json",
            suffix=".json",
        )
        replaced_refs[artifact.artifact_id] = moved
    relocated = replace(
        accepted,
        state=ExtractionState(
            artifacts=tuple(
                replaced_refs.get(item.artifact_id, item)
                for item in accepted.state.artifacts
            ),
            evidence=accepted.state.evidence,
            issues=accepted.state.issues,
        ),
    )

    second = loader.load(
        relocated,
        second_store,
        ancestor_contexts=(root, parent),
    )

    assert second.authority_token == first.authority_token


def test_solver_projection_schema_snapshot_matches_runtime_authority() -> None:
    checked_in = json.loads(
        (
            ROOT
            / "internal/schemas/solver-problem-projection.schema.json"
        ).read_text(encoding="utf-8")
    )

    assert checked_in == solver_problem_projection_schema()


def test_bundle_load_does_not_revalidate_reproject_plan_or_solve(
    tmp_path,
    monkeypatch,
) -> None:
    root, parent, accepted, store, *_ = _accepted_fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("forbidden subsystem was called while loading bundle")

    monkeypatch.setattr(
        "shuxueshuo_server.solver.extraction.problem_domain_validation."
        "ProblemDomainValidator.validate",
        forbidden,
    )
    monkeypatch.setattr(
        "shuxueshuo_server.solver.extraction.problem_domain_projection."
        "ProblemDomainProjector.project",
        forbidden,
    )
    monkeypatch.setattr(
        "shuxueshuo_server.solver.runtime.orchestrator.RuntimeOrchestrator.solve",
        forbidden,
    )

    bundle = VerifiedSolverProblemBundleLoader().load(
        accepted,
        store,
        ancestor_contexts=(root, parent),
    )

    assert bundle.authority_token.bundle_id.startswith(
        "verified-solver-problem-bundle:"
    )
