from __future__ import annotations

import json

import pytest

from shuxueshuo_server.solver.extraction.multimodal_candidates import (
    parse_candidate_patch,
)

from _problem_extraction_f3_support import (
    make_f3_fixture,
    valid_candidate_json,
    valid_candidate_payload,
)


def test_valid_candidate_patch_is_wire_only_and_stable(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)

    patch, report = parse_candidate_patch(valid_candidate_json(pack), pack)

    assert report.ok
    assert patch is not None
    assert {item.candidate_type for item in patch.candidates} == {
        "scope",
        "entity",
        "fact",
        "goal",
    }
    assert patch.patch_id == parse_candidate_patch(
        valid_candidate_json(pack),
        pack,
    )[0].patch_id  # type: ignore[union-attr]


def test_invalid_json_and_problem_ir_output_fail_contract(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)

    patch, invalid_json = parse_candidate_patch("```json\n{}\n```", pack)
    payload = valid_candidate_payload(pack)
    payload["problem_ir"] = {}
    _, problem_ir = parse_candidate_patch(json.dumps(payload), pack)

    assert patch is None
    assert invalid_json.issues[0].code == "extraction.multimodal_response_invalid_json"
    assert problem_ir.issues[0].code == "extraction.multimodal_response_invalid"


def test_unknown_evidence_and_free_geometry_fail_closed(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    unknown = valid_candidate_payload(pack)
    unknown["candidates"][0]["evidence_refs"] = ["observation:missing"]
    geometry = valid_candidate_payload(pack)
    geometry["candidates"][0]["payload"]["polygon"] = [[0, 0], [1, 1]]

    _, unknown_report = parse_candidate_patch(json.dumps(unknown), pack)
    _, geometry_report = parse_candidate_patch(json.dumps(geometry), pack)

    assert unknown_report.issues[0].code == "extraction.evidence_ref_unresolved"
    assert geometry_report.issues[0].code == "extraction.multimodal_forbidden_output"


def test_nonprinted_evidence_can_only_be_review_context(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path, colored_ink=True)
    nonprinted = next(item for item in pack.region_index if item.origin != "printed")
    payload = valid_candidate_payload(pack)
    payload["candidates"][0]["evidence_refs"] = [nonprinted.evidence_id]
    payload["candidates"][0]["review_region_refs"] = [nonprinted.region_id]

    _, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.issues[0].code == "extraction.multimodal_evidence_origin_forbidden"


def test_low_confidence_ocr_cannot_assert_candidate_as_printed(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(
        tmp_path,
        printed_text_confidence=0.7,
    )
    uncertain = next(
        item
        for item in pack.region_index
        if item.kind == "text" and item.confidence == 0.7
    )
    payload = valid_candidate_payload(pack)
    payload["candidates"][0]["evidence_refs"] = [uncertain.evidence_id]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert patch is None
    assert uncertain.origin == "unknown"
    assert report.issues[0].code == (
        "extraction.multimodal_evidence_origin_forbidden"
    )


def test_ocr_missed_visual_object_can_use_review_tile_as_proposed_evidence(
    tmp_path,
) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    tile = next(
        item
        for item in pack.region_index
        if item.kind == "visual_review_tile:r1c1"
    )
    payload = valid_candidate_payload(pack)
    candidate = payload["candidates"][1]
    candidate["payload"] = {"kind": "point", "label": "A"}
    candidate["evidence_refs"] = [tile.evidence_id]
    candidate["review_region_refs"] = [tile.region_id]
    payload["ambiguities"] = [
        {
            "ambiguity_id": "ambiguity_visual_label_A",
            "code": "diagram_label_requires_visual_confirmation",
            "candidate_ids": [],
            "evidence_refs": [tile.evidence_id],
            "review_region_refs": [tile.region_id],
            "message": "point label is visible but has no OCR observation",
        }
    ]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.ok
    assert patch is not None
    assert patch.candidates[1].evidence_refs == (tile.evidence_id,)
    assert patch.candidates[1].review_region_refs == (tile.region_id,)


def test_visual_review_tile_cannot_assert_fact_without_ambiguity(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    tile = next(
        item
        for item in pack.region_index
        if item.kind == "visual_review_tile:r1c1"
    )
    payload = valid_candidate_payload(pack)
    payload["candidates"][1]["evidence_refs"] = [tile.evidence_id]
    payload["candidates"][1]["review_region_refs"] = [tile.region_id]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert patch is None
    assert report.issues[0].code == (
        "extraction.multimodal_evidence_origin_forbidden"
    )


def test_ambiguity_must_reference_known_candidate_and_region(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    payload = valid_candidate_payload(pack)
    payload["ambiguities"] = [
        {
            "ambiguity_id": "ambiguity_1",
            "code": "label_unclear",
            "candidate_ids": ["entity_missing"],
            "evidence_refs": [],
            "review_region_refs": [pack.region_index[0].region_id],
            "message": "label is unclear",
        }
    ]

    _, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.issues[0].code == "extraction.evidence_ref_unresolved"


def test_mixed_evidence_requires_matching_review_and_ambiguity(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path, colored_ink=True)
    mixed = next(
        item for item in pack.region_index if item.origin in {"mixed", "unknown"}
    )
    payload = valid_candidate_payload(pack)
    candidate = payload["candidates"][1]
    candidate["evidence_refs"] = [mixed.evidence_id]
    candidate["review_region_refs"] = []
    payload["ambiguities"] = [
        {
            "ambiguity_id": "ambiguity_mixed_entity",
            "code": "source_region_requires_review",
            "evidence_refs": [mixed.evidence_id],
            "review_region_refs": [mixed.region_id],
            "message": "printed content overlaps uncertain ink",
        }
    ]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.ok
    assert patch is not None
    assert patch.ambiguities[0].candidate_ids == ()
    assert patch.candidates[1].review_region_refs == (mixed.region_id,)


@pytest.mark.parametrize(
    ("target", "expected_path"),
    (
        ("classification", "$.review_region_refs"),
        ("transcription", "$.transcription_lines[0].review_region_refs"),
    ),
)
def test_mixed_classification_and_transcription_are_normalized_but_audited(
    tmp_path,
    target,
    expected_path,
) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path, colored_ink=True)
    mixed = next(
        item for item in pack.region_index if item.origin in {"mixed", "unknown"}
    )
    payload = valid_candidate_payload(pack)
    if target == "classification":
        payload["classification"]["evidence_refs"] = [mixed.evidence_id]
        payload["review_region_refs"] = []
    else:
        payload["transcription_lines"][0]["evidence_refs"] = [mixed.evidence_id]
        payload["transcription_lines"][0]["review_region_refs"] = []
    payload["ambiguities"] = [
        {
            "ambiguity_id": f"ambiguity_mixed_{target}",
            "code": "source_region_requires_review",
            "candidate_ids": [],
            "evidence_refs": [mixed.evidence_id],
            "review_region_refs": [mixed.region_id],
            "message": "printed content overlaps uncertain ink",
        }
    ]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.ok
    assert patch is not None
    assert report.normalized_review_region_count == 1
    assert report.normalizations[0].path == expected_path
    if target == "classification":
        assert patch.review_region_refs == (mixed.region_id,)
    else:
        assert patch.transcription_lines[0].review_region_refs == (
            mixed.region_id,
        )


@pytest.mark.parametrize("target", ("classification", "transcription"))
def test_mixed_classification_and_transcription_still_require_ambiguity(
    tmp_path,
    target,
) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path, colored_ink=True)
    mixed = next(
        item for item in pack.region_index if item.origin in {"mixed", "unknown"}
    )
    payload = valid_candidate_payload(pack)
    if target == "classification":
        payload["classification"]["evidence_refs"] = [mixed.evidence_id]
    else:
        payload["transcription_lines"][0]["evidence_refs"] = [mixed.evidence_id]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert patch is None
    assert report.issues[0].code == (
        "extraction.multimodal_evidence_origin_forbidden"
    )


def test_candidate_payload_references_must_resolve_within_patch(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    payload = valid_candidate_payload(pack)
    payload["candidates"][2]["payload"]["subject_candidate_id"] = (
        "entity_missing"
    )

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert patch is None
    assert report.issues[0].code == "extraction.evidence_ref_unresolved"


def test_empty_review_refs_default_and_math_coordinates_are_allowed(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    payload = valid_candidate_payload(pack)
    candidate = payload["candidates"][1]
    candidate.pop("review_region_refs")
    candidate["payload"]["coordinates"] = [-1, 0]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.ok
    assert patch is not None
    assert patch.candidates[1].review_region_refs == ()
    assert patch.candidates[1].to_payload()["payload"]["coordinates"] == [-1, 0]


def test_prompt_local_evidence_aliases_expand_to_canonical_identity(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    payload = valid_candidate_payload(pack)
    full_ref = payload["candidates"][0]["evidence_refs"][0]
    evidence_aliases, _ = pack.prompt_reference_aliases()
    payload["candidates"][0]["evidence_refs"] = [evidence_aliases[full_ref]]

    patch, report = parse_candidate_patch(json.dumps(payload), pack)

    assert report.ok
    assert patch is not None
    assert patch.candidates[0].evidence_refs == (full_ref,)
