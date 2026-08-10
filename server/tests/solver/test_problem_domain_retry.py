from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field, replace
from io import BytesIO
import json
from pathlib import Path
from threading import Event
from typing import Callable

import pytest
from PIL import Image

from shuxueshuo_server.solver.extraction.context import (
    ExtractionAttemptLedger,
    SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND,
)
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    MultimodalProviderImage,
    MultimodalProviderError,
    MultimodalProviderRequest,
    MultimodalProviderResponse,
    ProviderSubAttempt,
    build_multimodal_provider_request,
)
from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDomainError,
    ProblemDraft,
    ProblemRepairPatch,
    ProblemRepairService,
)
from shuxueshuo_server.solver.extraction.problem_domain_service import (
    PROBLEM_DOMAIN_PRIMARY_IMAGE_MAX_EDGE,
    ProblemDomainExtractionService,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.problem_solver_bundle import (
    ProblemBundleAuthorityError,
    VerifiedSolverProblemBundleLoader,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
)

from _problem_extraction_f3_support import make_f3_fixture


ROOT = Path(__file__).resolve().parents[3]


def _domain_payload(case: str = "tj-2026-nankai-yimo-25") -> dict:
    payload = json.loads(
        (ROOT / "internal/problem-domain-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )
    payload["problem_id"] = "synthetic-f2"
    return payload


class _SourceIndependentValidator(ProblemDomainValidator):
    """Exercise domain/runtime validation without the synthetic F2 OCR text."""

    def validate(self, draft, *, evidence_pack=None, expected_problem_id=None):
        return super().validate(
            draft,
            expected_problem_id=expected_problem_id,
        )


ResponseFactory = Callable[[MultimodalProviderRequest], str]


@dataclass
class _SequenceProvider:
    responses: list[str | ResponseFactory | MultimodalProviderError]
    model: str = "recorded-domain-model"
    provider_name: str = "recorded"
    supports_images: bool = True
    response_format_mode: str = "json_schema"
    requests: list[MultimodalProviderRequest] = field(default_factory=list)

    def complete(self, request: MultimodalProviderRequest) -> MultimodalProviderResponse:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("recorded provider response queue is empty")
        item = self.responses.pop(0)
        if isinstance(item, MultimodalProviderError):
            raise item
        text = item(request) if callable(item) else item
        provider_attempt = ProviderSubAttempt(
            provider_attempt=1,
            status="completed",
            response_model=self.model,
            usage={"total_tokens": 10},
            finish_reason="stop",
            visible_content=True,
            latency_ms=1,
        )
        return MultimodalProviderResponse(
            text=text,
            raw_payload={"model": self.model, "content": text},
            request_model=self.model,
            response_model=self.model,
            usage={"total_tokens": 10},
            finish_reason="stop",
            provider_attempts=(provider_attempt,),
            latency_ms=1,
            thinking_mode=request.thinking_mode,
            reasoning_effort=request.reasoning_effort,
            contract_version=request.contract_version,
        )


def _service(tmp_path, store, provider):
    return ProblemDomainExtractionService(
        input_artifact_reader=store,
        output_artifact_store=store,
        provider=provider,
        validator=_SourceIndependentValidator(),
    )


def test_full_selection_transport_image_is_downsampled_without_cropping(tmp_path) -> None:
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    request = build_multimodal_provider_request(
        pack,
        artifact_reader=store,
        expected_problem_id="synthetic-f2",
    )
    source = Image.new("RGB", (100, 2000), "white")
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    content = buffer.getvalue()
    artifact = store.put_bytes(
        kind="selection_crop",
        content=content,
        media_type="image/png",
        suffix=".png",
    )
    image = MultimodalProviderImage(
        image_id="primary:page_1:large",
        page_id="page_1",
        role="primary",
        artifact=artifact,
        content=content,
        width=100,
        height=2000,
    )
    service = _service(tmp_path, store, _SequenceProvider([]))

    prepared = service._prepare_transport_images(
        replace(request, images=(image,))
    )

    assert len(prepared.images) == 1
    actual = prepared.images[0]
    assert actual.role == "primary"
    assert (actual.width, actual.height) == (80, PROBLEM_DOMAIN_PRIMARY_IMAGE_MAX_EDGE)
    assert actual.artifact.kind == "problem_domain_primary_image"
    assert actual.artifact.sha256 != artifact.sha256


def test_first_pass_accepts_one_complete_domain_and_commits_verified_problem(
    tmp_path,
    monkeypatch,
) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    provider = _SequenceProvider([json.dumps(_domain_payload(), ensure_ascii=False)])
    audited_context_ids: list[str] = []
    original_load = VerifiedSolverProblemBundleLoader.load

    def audited_load(self, accepted, artifact_reader, **kwargs):
        audited_context_ids.append(accepted.manifest.context_id)
        return original_load(self, accepted, artifact_reader, **kwargs)

    monkeypatch.setattr(VerifiedSolverProblemBundleLoader, "load", audited_load)

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )

    assert result.accepted
    assert result.verified_problem is not None
    assert result.solver_projection is not None
    assert len(result.attempts) == 1
    assert result.final_context.projection.problem_revision_id == (
        result.verified_problem.revision_id
    )
    assert result.final_context.retry.attempts_used == context.retry.attempts_used + 1
    assert audited_context_ids == [result.final_context.manifest.context_id]
    request = provider.requests[0]
    assert request.contract_version == "problem-domain/v1"
    assert request.thinking_mode == "disabled"
    assert request.reasoning_effort is None
    assert [image.role for image in request.images] == ["primary"]


def test_acceptance_bundle_audit_failure_is_not_exposed_as_success(
    tmp_path,
    monkeypatch,
) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    provider = _SequenceProvider([json.dumps(_domain_payload(), ensure_ascii=False)])
    original_put_json = store.put_json

    def corrupt_projection(*, kind, payload):
        if kind == SOLVER_PROBLEM_PROJECTION_ARTIFACT_KIND:
            payload = deepcopy(payload)
            first = next(iter(payload["manifest"]["runtime_node_sources"]))
            del payload["manifest"]["runtime_node_sources"][first]
        return original_put_json(kind=kind, payload=payload)

    monkeypatch.setattr(store, "put_json", corrupt_projection)

    with pytest.raises(ProblemBundleAuthorityError) as error:
        _service(tmp_path, store, provider).run(
            context,
            attempt_ledger=ExtractionAttemptLedger.for_context(context),
            ancestor_contexts=(fixture.context,),
        )

    assert error.value.code == "planner.problem_projection_manifest_drift"
    assert len(provider.requests) == 1


def test_provider_call_does_not_hold_attempt_ledger_lock(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    provider_entered = Event()
    release_provider = Event()

    def delayed_response(_request: MultimodalProviderRequest) -> str:
        provider_entered.set()
        if not release_provider.wait(timeout=5):
            raise AssertionError("test did not release the provider")
        return json.dumps(_domain_payload(), ensure_ascii=False)

    provider = _SequenceProvider([delayed_response])
    service = _service(tmp_path, store, provider)
    empty = ExtractionAttemptLedger.for_context(context)

    with ThreadPoolExecutor(max_workers=2) as executor:
        run_future = executor.submit(
            service.run,
            context,
            attempt_ledger=empty,
            ancestor_contexts=(fixture.context,),
        )
        assert provider_entered.wait(timeout=2)
        load_future = executor.submit(service.attempt_ledger_store.load, context)
        try:
            observed = load_future.result(timeout=1)
        finally:
            release_provider.set()
        result = run_future.result(timeout=5)

    assert observed == empty
    assert result.accepted


def test_first_pass_canonicalizes_origin_and_ancestor_symbol_before_validation(
    tmp_path,
) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    payload = _domain_payload("tj-2026-heping-yimo-25")
    root = payload["root"]
    root["entities"] = [item for item in root["entities"] if item["id"] != "O"]
    root["facts"] = [
        item
        for item in root["facts"]
        if not (
            item["kind"] == "point_construction"
            and item.get("construction") == "origin"
        )
    ]
    part_i_2 = next(
        child
        for part in root["children"]
        for child in part["children"]
        if child["id"] == "i_2"
    )
    part_i_2["facts"].insert(
        0,
        {
            "kind": "point_construction",
            "point": "point_O",
            "construction": "origin",
        },
    )
    part_ii = next(item for item in root["children"] if item["id"] == "ii")
    part_ii["entities"].append(
        {
            "id": "a_param",
            "kind": "symbol",
            "label": "a",
            "role": "primary_parameter",
        }
    )
    next(item for item in part_ii["goals"] if item["kind"] == "parameter_value")[
        "target"
    ] = "a_param"
    provider = _SequenceProvider([json.dumps(payload, ensure_ascii=False)])

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )

    assert result.accepted, result.attempts[-1].report.to_payload()
    draft = result.attempts[0].resulting_draft
    assert draft is not None
    assert any(item.local_id == "O" for item in draft.graph.root_scope.entities)
    assert all(
        item.local_id != "a_param"
        for item in draft.graph.scope_by_path["problem/ii"].entities
    )
    assert any(
        artifact.kind == "problem_domain_canonicalization"
        for artifact in result.attempts[0].output_artifacts
    )


def test_invalid_family_is_repaired_locally_and_retry_keeps_full_image(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    invalid = _domain_payload()
    expected_family = invalid["family_id"]
    invalid["family_id"] = "QuadraticWeightedPathMinimumSolver"
    invalid_draft = ProblemDraft.create(invalid)

    def repair(_: MultimodalProviderRequest) -> str:
        return json.dumps(
            {
                "schema_version": "problem-repair/v1",
                "base_revision_id": invalid_draft.revision_id,
                "replacements": [
                    {
                        "unit_id": "family",
                        "value": {"family_id": expected_family},
                    }
                ],
                "additions": [],
                "removals": [],
            },
            ensure_ascii=False,
        )

    provider = _SequenceProvider(
        [json.dumps(invalid, ensure_ascii=False), repair]
    )

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        ancestor_contexts=(fixture.context,),
    )

    assert result.accepted
    assert len(result.attempts) == 2
    assert result.attempts[0].resulting_draft is not None
    assert result.attempts[0].report.issues
    assert result.attempts[1].patch is not None
    assert provider.requests[1].contract_version == "problem-repair/v1"
    assert provider.requests[1].thinking_mode == "enabled"
    assert provider.requests[1].reasoning_effort == "low"
    assert any(image.role == "primary" for image in provider.requests[1].images)
    assert result.verified_problem is not None
    assert result.verified_problem.family_id == expected_family
    patch_bytes = len(
        json.dumps(result.attempts[1].patch.to_payload(), separators=(",", ":")).encode()
    )
    draft_bytes = len(
        json.dumps(
            result.attempts[0].resulting_draft.to_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    assert patch_bytes <= draft_bytes * 0.30


def test_ungrounded_mechanism_is_removed_without_rewriting_valid_math() -> None:
    payload = _domain_payload("tj-2026-nankai-yimo-25")
    scope = next(item for item in payload["root"]["children"] if item["id"] == "ii")
    scope["entities"].append(
        {
            "id": "ray_DM",
            "kind": "named_ray",
            "label": "射线DM",
            "origin": "D",
            "through": "M",
        }
    )
    scope["facts"].append(
        {"kind": "point_on_ray", "point": "E", "ray": "ray_DM"}
    )
    invalid = ProblemDomainValidator().validate(ProblemDraft.create(payload)).draft
    ray = next(
        entity for entity in invalid.graph.scope_by_path["problem/ii"].entities
        if entity.local_id == "ray_DM"
    )
    membership = next(
        fact for fact in invalid.graph.scope_by_path["problem/ii"].facts
        if fact.kind == "point_on_ray"
    )
    patch = ProblemRepairPatch.create(
        {
            "schema_version": "problem-repair/v1",
            "base_revision_id": invalid.revision_id,
            "replacements": [],
            "additions": [],
            "removals": [membership.unit_id, ray.unit_id],
        }
    )

    repaired = ProblemRepairService().apply(invalid, patch)
    result = ProblemDomainValidator().validate(repaired)

    assert result.report.ok, result.report.to_payload()
    assert all(
        fact.kind != "point_on_ray"
        for fact in result.draft.graph.scope_by_path["problem/ii"].facts
    )
    assert any(
        fact.kind == "equal_length"
        for fact in result.draft.graph.scope_by_path["problem/ii"].facts
    )


def test_sibling_entity_can_be_relocated_to_common_ancestor_atomically() -> None:
    payload = _domain_payload("tj-2026-heping-yimo-25")
    root = payload["root"]
    origin = next(item for item in root["entities"] if item["id"] == "O")
    origin_fact = next(
        item
        for item in root["facts"]
        if item["kind"] == "point_construction"
        and item["construction"] == "origin"
    )
    root["entities"].remove(origin)
    root["facts"].remove(origin_fact)
    part_ii = next(item for item in root["children"] if item["id"] == "ii")
    part_ii["entities"].append(origin)
    part_ii["facts"].insert(0, origin_fact)
    invalid = ProblemDomainValidator().validate(ProblemDraft.create(payload)).draft
    misplaced = next(
        entity
        for entity in invalid.graph.scope_by_path["problem/ii"].entities
        if entity.local_id == "O"
    )
    companion = next(
        fact
        for fact in invalid.graph.scope_by_path["problem/ii"].facts
        if fact.kind == "point_construction"
        and fact.attributes.get("construction") == "origin"
    )
    patch = ProblemRepairPatch.create(
        {
            "schema_version": "problem-repair/v1",
            "base_revision_id": invalid.revision_id,
            "replacements": [],
            "additions": [
                {
                    "scope_path": "problem",
                    "collection": "entity",
                    "value": origin,
                },
                {
                    "scope_path": "problem",
                    "collection": "fact",
                    "value": origin_fact,
                }
            ],
            "removals": [misplaced.unit_id, companion.unit_id],
        }
    )

    repaired = ProblemRepairService().apply(invalid, patch)
    result = ProblemDomainValidator().validate(repaired)

    assert result.report.ok, result.report.to_payload()
    assert any(
        entity.local_id == "O" for entity in result.draft.graph.root_scope.entities
    )
    assert all(
        entity.local_id != "O"
        for entity in result.draft.graph.scope_by_path["problem/ii"].entities
    )


def test_once_a_draft_exists_full_replacement_is_rejected_and_never_committed(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    invalid = _domain_payload()
    invalid["family_id"] = "QuadraticWeightedPathMinimumSolver"
    full_replacement = json.dumps(_domain_payload(), ensure_ascii=False)
    provider = _SequenceProvider(
        [json.dumps(invalid, ensure_ascii=False), full_replacement]
    )

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        max_attempts=2,
        ancestor_contexts=(fixture.context,),
    )

    assert result.blocked
    assert result.verified_problem is None
    assert result.final_context.projection.verified_problem_artifact_id is None
    assert result.final_context.projection.solver_problem_ir_artifact_id is None
    assert result.attempts[1].request.contract_version == "problem-repair/v1"
    assert result.attempts[1].patch is None
    assert result.attempts[1].report.issues[0].code == (
        "extraction.problem_repair_schema_invalid"
    )


def test_wire_failure_may_retry_one_complete_domain_before_a_draft_exists(
    tmp_path,
) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    provider = _SequenceProvider(
        ["not-json", json.dumps(_domain_payload(), ensure_ascii=False)]
    )

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        max_attempts=2,
        ancestor_contexts=(fixture.context,),
    )

    assert result.accepted
    assert len(result.attempts) == 2
    assert result.attempts[0].resulting_draft is None
    assert result.attempts[0].report.first_issue is not None
    assert result.attempts[0].report.first_issue.code == (
        "extraction.problem_domain_invalid_json"
    )
    assert provider.requests[1].contract_version == "problem-domain/v1"
    assert provider.requests[1].thinking_mode == "disabled"
    assert provider.requests[1].reasoning_effort is None
    assert all(image.role == "primary" for image in provider.requests[1].images)


def test_repeated_transport_timeout_does_not_trigger_semantic_no_progress(
    tmp_path,
) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    provider = _SequenceProvider(
        [
            MultimodalProviderError(
                "extraction.multimodal_provider_timeout",
                "recorded timeout",
                result="timeout",
            ),
            MultimodalProviderError(
                "extraction.multimodal_provider_timeout",
                "recorded timeout",
                result="timeout",
            ),
            json.dumps(_domain_payload(), ensure_ascii=False),
        ]
    )

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        max_attempts=3,
        ancestor_contexts=(fixture.context,),
    )

    assert result.accepted
    assert len(result.attempts) == 3
    assert [item.attempt_record.result for item in result.attempts] == [
        "timeout",
        "timeout",
        "succeeded",
    ]


def test_repeated_no_progress_patch_blocks_deterministically(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    invalid = _domain_payload()
    invalid["family_id"] = "QuadraticWeightedPathMinimumSolver"
    invalid_draft = ProblemDraft.create(invalid)
    no_progress = json.dumps(
        {
            "schema_version": "problem-repair/v1",
            "base_revision_id": invalid_draft.revision_id,
            "replacements": [
                {
                    "unit_id": "family",
                    "value": {"family_id": "QuadraticWeightedPathMinimumSolver"},
                }
            ],
            "additions": [],
            "removals": [],
        },
        ensure_ascii=False,
    )
    provider = _SequenceProvider(
        [json.dumps(invalid, ensure_ascii=False), no_progress, no_progress]
    )

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        max_attempts=3,
        ancestor_contexts=(fixture.context,),
    )

    assert result.blocked
    assert result.blocked_reason == "extraction.problem_retry_no_progress"
    assert len(result.attempts) == 3
    assert result.final_context.retry.status == "blocked"
    assert "extraction.problem_retry_no_progress" in (
        result.final_context.retry.work_item_ids
    )


def test_attempt_limit_produces_explicit_retry_exhausted_context(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    invalid = _domain_payload()
    invalid["family_id"] = "QuadraticWeightedPathMinimumSolver"
    provider = _SequenceProvider([json.dumps(invalid, ensure_ascii=False)])

    result = _service(tmp_path, store, provider).run(
        context,
        attempt_ledger=ExtractionAttemptLedger.for_context(context),
        max_attempts=1,
        ancestor_contexts=(fixture.context,),
    )

    assert result.blocked
    assert result.blocked_reason == "extraction.problem_retry_exhausted"
    assert "extraction.problem_retry_exhausted" in (
        result.final_context.retry.work_item_ids
    )
    assert result.final_context.projection.verified_problem_artifact_id is None


def test_persisted_attempt_ledger_prevents_reusing_an_empty_budget_view(tmp_path) -> None:
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    invalid = _domain_payload()
    invalid["family_id"] = "QuadraticWeightedPathMinimumSolver"
    provider = _SequenceProvider([json.dumps(invalid, ensure_ascii=False)] * 2)
    service = _service(tmp_path, store, provider)
    empty = ExtractionAttemptLedger.for_context(context)

    first = service.run(
        context,
        attempt_ledger=empty,
        max_attempts=1,
        ancestor_contexts=(fixture.context,),
    )
    assert first.blocked
    assert len(provider.requests) == 1

    with pytest.raises(ProblemExtractionContextError) as error:
        service.run(
            context,
            attempt_ledger=empty,
            max_attempts=1,
            ancestor_contexts=(fixture.context,),
        )

    assert error.value.code == "extraction.attempt_ledger_mismatch"
    assert len(provider.requests) == 1


def test_frozen_unit_outside_repair_cone_cannot_be_mutated() -> None:
    validation = _SourceIndependentValidator().validate(
        ProblemDraft.create(_domain_payload())
    )
    assert validation.report.ok
    frozen = next(
        unit_id
        for unit_id in validation.draft.frozen_unit_ids
        if validation.draft.unit_registry[unit_id].unit_kind == "entity"
    )
    record = validation.draft.unit_registry[frozen]
    entity = next(
        item
        for scope in validation.draft.graph.root_scope.iter_scopes()
        for item in scope.entities
        if item.unit_id == frozen
    )
    replacement = entity.wire_payload()
    replacement["label"] = replacement["label"] + " changed"
    patch = ProblemRepairPatch.create(
        {
            "schema_version": "problem-repair/v1",
            "base_revision_id": validation.draft.revision_id,
            "replacements": [{"unit_id": frozen, "value": replacement}],
            "additions": [],
            "removals": [],
        }
    )

    assert record.scope_path
    with pytest.raises(ProblemDomainError) as error:
        ProblemRepairService().apply(validation.draft, patch)

    assert error.value.code == "extraction.problem_frozen_unit_mutation"
