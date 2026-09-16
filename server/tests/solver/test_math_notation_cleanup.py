"""Retired output paths must not become implicit fallbacks or dependencies."""

import ast
import json
from pathlib import Path

import pytest
from _math_notation_test_support import Recorded

from shuxueshuo_server.problem_understanding import notation_contract
from shuxueshuo_server.problem_understanding.batch_smoke import (
    NOTATION_FIXTURES,
    TEST_IMAGES,
    prepare_fixture,
)
from shuxueshuo_server.problem_understanding.smoke import run
from shuxueshuo_server.problem_understanding.wire import components

RETIRED = {
    "acceptance",
    "authoring",
    "comparison",
    "contracts",
    "equivalence",
    "geometry_consistency",
    "intersections",
    "measure",
    "normalization",
    "prompt",
    "service",
    "validation",
}


@pytest.mark.parametrize("contract", [None, "problem-domain/v2", "guess"])
def test_retired_and_missing_versions_are_rejected_explicitly(contract):
    with pytest.raises(ValueError, match="unsupported extraction contract"):
        components(contract)


def test_retired_fixture_cannot_select_a_legacy_provider_call(tmp_path):
    fixture = prepare_fixture("k-quad", tmp_path)
    provenance = json.loads((fixture / "provenance.json").read_text())
    provenance["output_contract"] = "problem-domain/v2"
    (fixture / "provenance.json").write_text(json.dumps(provenance))
    provider = Recorded("{}")
    with pytest.raises(ValueError, match="unsupported extraction contract"):
        run(fixture, tmp_path / "run", provider, [])
    assert provider.calls == 0
    assert not (tmp_path / "run/semantic-call-reserved.json").exists()


def test_retired_preparation_rejected_before_writing_fixtures(tmp_path):
    target = tmp_path / "unused"
    with pytest.raises(ValueError, match="unsupported extraction contract"):
        prepare_fixture("k-quad", target, contract="problem-domain/v2")
    assert not target.exists()


def test_active_modules_have_no_retired_imports_and_images_use_current_fixture_root():
    package = Path(notation_contract.__file__).parent
    for name in RETIRED:
        assert not (package / (name + ".py")).exists()
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                assert node.module not in RETIRED, (path, node.module)
    assert TEST_IMAGES.parent == NOTATION_FIXTURES
