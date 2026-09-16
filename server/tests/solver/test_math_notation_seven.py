"""The same compact IR gate for five known families and two unmatched problems."""

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest
from _math_notation_test_support import Recorded
from PIL import Image

from shuxueshuo_server.problem_understanding.batch_smoke import (
    CASES,
    NOTATION_FIXTURES,
    REPO,
    TEST_IMAGES,
    live_provider_factory,
    preflight,
    prepare_fixture,
)
from shuxueshuo_server.problem_understanding.smoke import build_request, run
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    problem_domain_family_catalog,
)


@pytest.mark.parametrize("case", CASES)
def test_seven_fixtures_replay_through_shared_gate(tmp_path, case):
    fixture = prepare_fixture(case, tmp_path)
    registry = list(problem_domain_family_catalog())
    provider = Recorded((fixture / "gold.json").read_text())
    preflight(fixture, tmp_path, provider, registry)
    summary = run(fixture, tmp_path / "run", provider, registry)
    assert summary["passed"] and summary["match_correct"]
    assert not summary["solver_ready"] and provider.calls == 1
    request = json.loads((tmp_path / "run/request.json").read_text())
    images = [p for p in request["messages"][1]["content"] if p["type"] == "image_url"]
    assert len(images) == 1 and images[0]["image_url"]["detail"] == "high"
    assert images[0]["image"]["media_type"] == "image/png"
    if case == "k-quad":
        assert summary["continuation"]["blocked"]
        assert summary["continuation"]["error_code"] == "extraction.missing_figure"
        assert len(summary["continuation"]["missing_figures"]) == 4
        assert (fixture / "acceptance-policy.json").read_bytes() == (
            NOTATION_FIXTURES / (case + ".acceptance-policy.json")
        ).read_bytes()
    else:
        assert not summary["continuation"]["blocked"]


@pytest.mark.parametrize("case", CASES)
def test_reviewed_pixels_reach_request_without_old_ocr_or_expected_answers(
    tmp_path, case
):
    manifest = json.loads((TEST_IMAGES / "manifest.json").read_text())
    selected = manifest["cases"][case]
    source = REPO / selected["source"]
    assert sha256(source.read_bytes()).hexdigest() == selected["source_sha256"]
    prepared = TEST_IMAGES / selected["file"]
    with Image.open(source) as original, Image.open(prepared) as actual:
        expected = (
            original.crop(selected["crop_box"]) if selected["crop_box"] else original
        )
        assert actual.size == expected.size
        assert actual.tobytes() == expected.tobytes()
    fixture = prepare_fixture(case, tmp_path)
    request = build_request(fixture, ExtractionArtifactStore(tmp_path / "request"), [])
    assert request.images[0].content == prepared.read_bytes()
    payload = json.loads(request.prompt.user_prefix)
    assert payload["auxiliary_text_origin"] == "image_only_no_ocr"
    assert payload["ocr_hints"]["pages"] == [
        {"page": 1, "lines": [], "formula_candidates": [], "notes": []}
    ]
    assert "expected_missing_figures" not in request.prompt.user_prefix
    assert "intentional_missing_figures_1_to_4" not in request.prompt.user_prefix
    if case in ("k-quad", "function-quantifiers"):
        assert prepared.read_bytes() == source.read_bytes()


def test_tampered_selected_image_fails_before_request(tmp_path, monkeypatch):
    from shuxueshuo_server.problem_understanding import batch_smoke

    manifest = json.loads((TEST_IMAGES / "manifest.json").read_text())
    case = CASES[0]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / manifest["cases"][case]["file"]).write_bytes(b"wrong image")
    monkeypatch.setattr(batch_smoke, "TEST_IMAGES", tmp_path)
    with pytest.raises(ValueError, match="selected image hash mismatch"):
        prepare_fixture(case, tmp_path / "output")


@pytest.mark.live_llm
@pytest.mark.parametrize("case", CASES)
def test_deepseek_seven_math_notation_extraction(tmp_path, case):
    if os.getenv("RUN_LLM_INTEGRATION") != "1":
        pytest.skip("real DeepSeek integration disabled")
    provider = live_provider_factory()()  # Enabled but missing dependencies must fail.
    output = Path(os.getenv("UNDERSTANDING_SEVEN_OUTPUT", str(tmp_path))) / case
    fixture = prepare_fixture(case, output)
    registry = list(problem_domain_family_catalog())
    preflight(fixture, output, provider, registry)
    summary = run(fixture, output, provider, registry)
    assert summary["passed"], summary
