from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import inspect
import json
from pathlib import Path

from PIL import Image
from jsonschema import Draft202012Validator
import pytest

from shuxueshuo_server.solver.extraction.f0_adapter import (
    build_f0_extraction_context_seed,
)
from shuxueshuo_server.solver.extraction.gold_corpus import load_gold_corpus
from shuxueshuo_server.solver.extraction.source_identity import (
    EXTRACTION_CONTRACT_VERSION,
    ExtractionDependencyManifest,
    ProblemExtractionContextError,
    ProblemSourceFingerprintService,
    SelectionRegion,
    SourceAssetInput,
    SourceSelection,
)


def _png_bytes(
    color: str = "white",
    *,
    metadata: bool = False,
) -> bytes:
    image = Image.new("RGB", (4, 3), color)
    output = BytesIO()
    if metadata:
        image.getexif()[270] = "metadata-only-change"
        image.save(output, format="PNG", exif=image.getexif())
    else:
        image.save(output, format="PNG")
    return output.getvalue()


def _asset(
    page_id: str = "page_1",
    *,
    content: bytes | None = None,
    locator: str | None = "first.png",
) -> SourceAssetInput:
    return SourceAssetInput(
        page_id=page_id,
        media_type="image/png",
        content_bytes=content or _png_bytes(),
        locator=locator,
    )


def _selection(source, *, offset: float = 0.0, reverse: bool = False):
    regions = [
        SelectionRegion(
            region_id="question",
            page_id="page_1",
            polygon=(
                (0.1 + offset, 0.1),
                (0.9, 0.1),
                (0.9, 0.9),
                (0.1 + offset, 0.9),
            ),
        ),
        SelectionRegion(
            region_id="figure",
            page_id="page_1",
            polygon=((0.2, 0.2), (0.3, 0.2), (0.3, 0.3), (0.2, 0.3)),
        ),
    ]
    if reverse:
        regions.reverse()
    return SourceSelection.create(
        source,
        mode="user_confirmed",
        revision=1,
        regions=regions,
        included_block_ids=("block_b", "block_a"),
    )


def test_source_identity_ignores_locator_but_revision_tracks_raw_bytes() -> None:
    service = ProblemSourceFingerprintService()
    first = service.fingerprint((_asset(locator="one.png"),))
    renamed = service.fingerprint((_asset(locator="https://example.test/two.png"),))
    reencoded = service.fingerprint(
        (_asset(content=_png_bytes(metadata=True), locator="three.png"),)
    )

    assert first.source_id == renamed.source_id == reencoded.source_id
    assert first.source_revision_hash == renamed.source_revision_hash
    assert first.source_revision_hash != reencoded.source_revision_hash


def test_source_identity_normalizes_exif_orientation() -> None:
    canonical = Image.new("RGBA", (3, 2))
    canonical.putdata(
        [
            (255, 0, 0, 255),
            (0, 255, 0, 255),
            (0, 0, 255, 255),
            (255, 255, 0, 255),
            (255, 0, 255, 255),
            (0, 255, 255, 255),
        ]
    )
    normal_output = BytesIO()
    canonical.save(normal_output, format="PNG")

    stored = canonical.transpose(Image.Transpose.ROTATE_90)
    stored.getexif()[274] = 6
    oriented_output = BytesIO()
    stored.save(oriented_output, format="PNG", exif=stored.getexif())

    service = ProblemSourceFingerprintService()
    normal = service.fingerprint((_asset(content=normal_output.getvalue()),))
    oriented = service.fingerprint((_asset(content=oriented_output.getvalue()),))

    assert normal.source_id == oriented.source_id
    assert normal.source_revision_hash != oriented.source_revision_hash


def test_visible_pixel_and_page_order_change_source_identity() -> None:
    service = ProblemSourceFingerprintService()
    white = _png_bytes("white")
    black = _png_bytes("black")
    first = service.fingerprint(
        (_asset("page_1", content=white), _asset("page_2", content=black))
    )
    pixel_changed = service.fingerprint(
        (_asset("page_1", content=black), _asset("page_2", content=black))
    )
    reordered = service.fingerprint(
        (_asset("page_2", content=black), _asset("page_1", content=white))
    )

    assert len({first.source_id, pixel_changed.source_id, reordered.source_id}) == 3


def test_page_rekey_preserves_visual_source_but_changes_revision() -> None:
    service = ProblemSourceFingerprintService()
    white = _png_bytes("white")
    black = _png_bytes("black")
    original = service.fingerprint(
        (_asset("page_1", content=white), _asset("page_2", content=black))
    )
    rekeyed = service.fingerprint(
        (_asset("page_2", content=white), _asset("page_1", content=black))
    )

    assert original.source_id == rekeyed.source_id
    assert original.source_revision_hash != rekeyed.source_revision_hash


def test_selection_order_is_canonical_but_geometry_changes_identity() -> None:
    source = ProblemSourceFingerprintService().fingerprint((_asset(),))
    first = _selection(source)
    reordered = _selection(source, reverse=True)
    adjusted = _selection(source, offset=0.01)

    assert first.selection_id == reordered.selection_id
    assert first.regions == reordered.regions
    assert first.included_block_ids == ("block_a", "block_b")
    assert adjusted.selection_id != first.selection_id


def test_dependency_tracks_revision_selection_contract_config_and_upstream() -> None:
    service = ProblemSourceFingerprintService()
    source = service.fingerprint((_asset(),))
    reencoded = service.fingerprint((_asset(content=_png_bytes(metadata=True)),))
    selection = _selection(source)
    reencoded_selection = _selection(reencoded)
    baseline = ExtractionDependencyManifest.create(source, selection)

    revision_changed = ExtractionDependencyManifest.create(
        reencoded,
        reencoded_selection,
    )
    selection_changed = ExtractionDependencyManifest.create(
        source,
        _selection(source, offset=0.01),
    )
    config_changed = ExtractionDependencyManifest.create(
        source,
        selection,
        semantic_config={"formula_profile": "v2"},
    )
    upstream_changed = ExtractionDependencyManifest.create(
        source,
        selection,
        upstream_context_ids=("ctx_previous",),
    )

    assert len(
        {
            baseline.dependency_hash,
            revision_changed.dependency_hash,
            selection_changed.dependency_hash,
            config_changed.dependency_hash,
            upstream_changed.dependency_hash,
        }
    ) == 5
    with pytest.raises(
        ProblemExtractionContextError,
        match="extraction.dependency_hash_mismatch",
    ):
        ExtractionDependencyManifest.create(
            source,
            selection,
            extraction_contract_version=EXTRACTION_CONTRACT_VERSION + ".next",
        )


@pytest.mark.parametrize(
    "asset",
    (
        SourceAssetInput("page_1", "application/pdf", b"%PDF"),
        SourceAssetInput("page_1", "image/png", b"not-an-image"),
    ),
)
def test_source_rejects_unsupported_or_unreadable_media(asset) -> None:
    with pytest.raises(ProblemExtractionContextError, match="extraction.source_invalid"):
        ProblemSourceFingerprintService().fingerprint((asset,))


def test_source_rejects_duplicate_page_ids() -> None:
    with pytest.raises(ProblemExtractionContextError, match="duplicate page id"):
        ProblemSourceFingerprintService().fingerprint((_asset(), _asset()))


@pytest.mark.parametrize(
    "polygon",
    (
        ((-0.1, 0.1), (0.9, 0.1), (0.9, 0.9)),
        ((0.1, 0.1), (0.2, 0.2), (0.3, 0.3)),
    ),
)
def test_selection_rejects_out_of_bounds_or_zero_area_polygon(polygon) -> None:
    source = ProblemSourceFingerprintService().fingerprint((_asset(),))
    with pytest.raises(
        ProblemExtractionContextError,
        match="extraction.selection_invalid",
    ):
        SourceSelection.create(
            source,
            mode="user_confirmed",
            revision=0,
            regions=(SelectionRegion("question", "page_1", polygon),),
        )


def test_source_and_selection_payload_tampering_fail_loud() -> None:
    source = ProblemSourceFingerprintService().fingerprint((_asset(),))
    selection = _selection(source)

    with pytest.raises(
        ProblemExtractionContextError,
        match="extraction.source_fingerprint_mismatch",
    ):
        replace(source, source_id="source:" + "0" * 64).validate()
    with pytest.raises(
        ProblemExtractionContextError,
        match="extraction.selection_invalid",
    ):
        replace(selection, selection_hash="0" * 64).validate(source)


def test_five_f0_cases_match_fixed_f1_fingerprints_without_model_calls() -> None:
    repo_root = Path(__file__).parents[3]
    fixture = json.loads(
        (repo_root / "internal/source-images/f1-fingerprints-v1.json").read_text(
            encoding="utf-8"
        )
    )
    schema = json.loads(
        (
            repo_root
            / "internal/schemas/problem-extraction-f1-fingerprints.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(fixture)

    actual = {
        case.problem_id: build_f0_extraction_context_seed(
            case
        ).fingerprint_payload()
        for case in load_gold_corpus().cases
    }

    assert actual == fixture["cases"]
    adapter_source = inspect.getsource(build_f0_extraction_context_seed)
    assert all(
        token not in adapter_source
        for token in ("PP-DocLayout", "OCR", "DeepSeek", "OpenAI", "provider")
    )


def test_f0_pixel_or_selection_mutation_breaks_fixed_fingerprint() -> None:
    case = load_gold_corpus().cases[0]
    seed = build_f0_extraction_context_seed(case)
    page = seed.source.pages[0]
    source_path = Path(__file__).parents[3] / str(page.locator)
    with Image.open(source_path) as image:
        changed = image.convert("RGBA")
        changed.putpixel((0, 0), (1, 2, 3, 255))
        output = BytesIO()
        changed.save(output, format="PNG")
    changed_source = ProblemSourceFingerprintService().fingerprint(
        (
            SourceAssetInput(
                page.page_id,
                "image/png",
                output.getvalue(),
                page.locator,
            ),
        )
    )
    changed_selection = SourceSelection.create(
        seed.source,
        mode="authored_gold",
        revision=1,
        regions=(
            replace(
                seed.selection.regions[0],
                polygon=((0.02, 0.02), (0.9, 0.02), (0.9, 0.9), (0.02, 0.9)),
            ),
        ),
    )

    assert changed_source.source_id != seed.source.source_id
    assert changed_selection.selection_id != seed.selection.selection_id


def test_f0_adapter_rejects_manifest_sha_drift() -> None:
    case = load_gold_corpus().cases[0]
    page = replace(case.manifest.pages[0], sha256="0" * 64)
    mutated = replace(
        case,
        manifest=replace(case.manifest, pages=(page,)),
    )

    with pytest.raises(ProblemExtractionContextError) as exc_info:
        build_f0_extraction_context_seed(mutated)

    assert exc_info.value.code == "extraction.source_fingerprint_mismatch"
