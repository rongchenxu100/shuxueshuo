from __future__ import annotations

from dataclasses import replace

import pytest

from shuxueshuo_server.solver.extraction.multimodal_evidence import (
    MultimodalEvidencePack,
    MultimodalEvidencePackBuilder,
)
from shuxueshuo_server.solver.extraction.source_identity import (
    ProblemExtractionContextError,
    stable_hash,
)

from _problem_extraction_f3_support import (
    make_f3_fixture,
    make_multi_page_f3_fixture,
)


def test_single_page_evidence_pack_has_one_complete_primary_image(tmp_path) -> None:
    _, result, context, store, pack = make_f3_fixture(tmp_path)

    assert len(pack.images) == 1
    assert pack.images[0].role == "primary"
    assert pack.images[0].artifact.kind == "selection_crop"
    assert pack.images[0].page_id == "page_1"
    assert pack.source_id == context.source.source_id
    assert pack.observation_hash == result.observation.observation_hash
    assert pack.printed_text
    assert pack.region_index
    visual_tiles = tuple(
        item
        for item in pack.region_index
        if item.kind.startswith("visual_review_tile:")
    )
    assert len(visual_tiles) == 16
    assert all(
        item.origin == "unknown" and item.confidence == 0.0
        for item in visual_tiles
    )
    assert pack.to_payload() == MultimodalEvidencePackBuilder().build(
        context,
        artifact_reader=store,
        observation=result.observation,
    ).to_payload()


def test_multi_page_selection_emits_one_primary_image_per_page_in_source_order(
    tmp_path,
) -> None:
    _, _, _, pack = make_multi_page_f3_fixture(tmp_path)

    assert [item.page_id for item in pack.images] == ["page_1", "page_2"]
    assert all(item.role == "primary" for item in pack.images)
    assert {item.page_id for item in pack.printed_text} == {"page_1", "page_2"}
    visual_tiles = tuple(
        item
        for item in pack.region_index
        if item.kind.startswith("visual_review_tile:")
    )
    assert len(visual_tiles) == 32
    assert {item.page_id for item in visual_tiles} == {"page_1", "page_2"}


def test_evidence_pack_loads_source_observation_from_context_artifact(tmp_path) -> None:
    _, _, context, store, expected = make_f3_fixture(tmp_path)

    actual = MultimodalEvidencePackBuilder().build(
        context,
        artifact_reader=store,
    )

    assert actual == expected


def test_evidence_pack_round_trip_and_prompt_compaction_are_stable(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path, colored_ink=True)

    restored = MultimodalEvidencePack.from_payload(pack.to_payload())
    prompt = restored.prompt_payload()
    prompt_region_ids = {
        item["region_id"] for item in prompt["region_index"]
    }

    assert restored.to_payload() == pack.to_payload()
    assert prompt == pack.prompt_payload()
    assert prompt["origin_summary"]
    assert all(
        item["origin"] != "handwritten"
        for item in prompt["region_index"]
    )
    assert len(prompt["region_index"]) < len(pack.region_index)
    assert all(
        item["evidence_id"].startswith("e")
        and item["region_id"].startswith("r")
        and len(item["evidence_id"]) == 4
        and len(item["region_id"]) == 4
        for item in prompt["region_index"]
    )
    assert all(
        item["evidence_id"].startswith("e")
        for item in prompt["printed_text"]
    )
    assert all(
        set(item["region_refs"]) <= prompt_region_ids
        for item in prompt["unresolved_items"]
    )


def test_evidence_pack_hydrate_rejects_malformed_or_unlinked_prompt_evidence(
    tmp_path,
) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    malformed = pack.to_payload()
    malformed.pop("base_context_id")
    unlinked = replace(
        pack,
        printed_text=(
            replace(pack.printed_text[0], observation_id="observation:missing"),
            *pack.printed_text[1:],
        ),
    )
    unlinked = replace(
        unlinked,
        evidence_pack_id=f"evidence-pack:{stable_hash(unlinked.authority_payload())}",
    )

    with pytest.raises(ProblemExtractionContextError) as malformed_error:
        MultimodalEvidencePack.from_payload(malformed)
    with pytest.raises(ProblemExtractionContextError) as unlinked_error:
        unlinked.validate()

    assert malformed_error.value.code == "extraction.multimodal_evidence_pack_invalid"
    assert unlinked_error.value.code == "extraction.evidence_ref_unresolved"


@pytest.mark.parametrize("mutation", ["unknown_page", "zero_area"])
def test_region_index_must_close_over_primary_pages_and_positive_geometry(
    tmp_path,
    mutation,
) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path)
    region = pack.region_index[0]
    if mutation == "unknown_page":
        region = replace(region, page_id="page_missing")
    else:
        region = replace(
            region,
            polygon=((0.1, 0.1), (0.2, 0.2), (0.3, 0.3)),
        )
    drifted = replace(pack, region_index=(region, *pack.region_index[1:]))
    drifted = replace(
        drifted,
        evidence_pack_id=f"evidence-pack:{stable_hash(drifted.authority_payload())}",
    )

    with pytest.raises(ProblemExtractionContextError) as error:
        drifted.validate()

    assert error.value.code == "extraction.multimodal_evidence_pack_invalid"


def test_missing_selection_crop_fails_loud(tmp_path) -> None:
    _, result, context, store, _ = make_f3_fixture(tmp_path)
    state = replace(
        context.state,
        artifacts=tuple(
            item for item in context.state.artifacts if item.kind != "selection_crop"
        ),
    )
    drifted = replace(context, state=state)

    with pytest.raises(ProblemExtractionContextError) as error:
        MultimodalEvidencePackBuilder().build(
            drifted,
            artifact_reader=store,
            observation=result.observation,
        )

    assert error.value.code == "extraction.multimodal_full_image_missing"


def test_nonprinted_math_is_a_work_item_not_printed_prompt_evidence(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(tmp_path, colored_ink=True)

    nonprinted = {
        item.region_id
        for item in pack.region_index
        if item.origin != "printed"
    }
    prompt_printed = {item.observation_id for item in pack.printed_text}

    assert nonprinted.isdisjoint(prompt_printed)
    assert any(
        nonprinted.intersection(item.region_refs)
        for item in pack.unresolved_items
    )


def test_low_confidence_printed_ocr_is_unknown_review_evidence(tmp_path) -> None:
    _, _, _, _, pack = make_f3_fixture(
        tmp_path,
        printed_text_confidence=0.7,
    )
    region = next(
        item
        for item in pack.region_index
        if item.kind == "text" and item.confidence == 0.7
    )

    assert region.origin == "unknown"
    assert region.evidence_id not in {
        item.observation_id for item in pack.printed_text
    }
    assert any(
        item.code == "extraction.observation_confidence_low"
        and region.region_id in item.region_refs
        for item in pack.unresolved_items
    )


def test_visual_review_tiles_are_stable_ocr_independent_prompt_regions(
    tmp_path,
) -> None:
    _, result, context, store, first = make_f3_fixture(tmp_path)
    second = MultimodalEvidencePackBuilder().build(
        context,
        artifact_reader=store,
        observation=result.observation,
    )
    first_tiles = tuple(
        item
        for item in first.region_index
        if item.kind.startswith("visual_review_tile:")
    )
    second_tiles = tuple(
        item
        for item in second.region_index
        if item.kind.startswith("visual_review_tile:")
    )
    prompt_kinds = {item["kind"] for item in first.prompt_payload()["region_index"]}

    assert first_tiles == second_tiles
    assert len(first_tiles) == 16
    assert {"visual_review_tile:r1c1", "visual_review_tile:r4c4"} <= prompt_kinds
    assert not {
        item.evidence_id for item in first_tiles
    }.intersection(item.observation_id for item in first.printed_text)


def test_observation_identity_drift_fails_before_provider(tmp_path) -> None:
    _, result, context, store, _ = make_f3_fixture(tmp_path)
    drifted = replace(
        result.observation,
        observation_hash="0" * 64,
    )

    with pytest.raises(ProblemExtractionContextError):
        MultimodalEvidencePackBuilder().build(
            context,
            artifact_reader=store,
            observation=drifted,
        )
