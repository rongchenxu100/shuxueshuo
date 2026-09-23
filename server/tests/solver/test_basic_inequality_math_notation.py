"""Offline stage-0 contract and replay gates for the basic-inequality family."""

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

import pytest
from jsonschema import Draft202012Validator
from PIL import Image
from _math_notation_test_support import Recorded

from shuxueshuo_server.problem_understanding.notation_compile import NotationValidator
from shuxueshuo_server.problem_understanding.notation_contract import (
    SYSTEM_PATH,
    expression_catalog,
    schema,
)
from shuxueshuo_server.problem_understanding.notation_family_catalog import (
    CATALOG_PATH,
    notation_family_catalog,
)
from shuxueshuo_server.problem_understanding.notation_semantics import canonical, compare


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/solver/fixtures/math-notation-v1/basic-inequality"
CASES = ("q01", "q03", "q07", "q08", "q12", "q17", "q20", "q25", "q30", "q31")
FORBIDDEN = (
    "term1",
    "term2",
    "transformed_target",
    "right_angle",
    "amgm_bound",
    "angle(A,B,C)",
)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_notation_catalog_is_source_owned_and_runtime_independent():
    catalog = notation_family_catalog()
    ids = [item["family_id"] for item in catalog]
    assert ids[-1] == "basic_inequality"
    assert len(ids) == len(set(ids)) == 5
    assert {"QuadraticPathMinimumSolver", "QuadraticWeightedPathMinimumSolver"} <= set(ids)
    assert "DEFAULT_FAMILY_REGISTRY" not in CATALOG_PATH.read_text(encoding="utf-8")


def test_basic_prompt_prefers_direct_math_and_hides_internal_fields():
    text = SYSTEM_PATH.read_text(encoding="utf-8")
    catalog = json.dumps(expression_catalog(), ensure_ascii=False)
    combined = text + catalog
    for direct in ("a > 0", "b > 0", "a + b = 2", "max", "min", "∠ABC = 90°"):
        assert direct in combined
    # Negative rules may name internal fields so the model knows what not to
    # emit.  They must not appear in the expression examples themselves.
    examples = json.dumps(
        [entry.get("examples", []) for entry in expression_catalog().get("expressions", [])],
        ensure_ascii=False,
    )
    for forbidden in FORBIDDEN:
        assert forbidden not in examples
    assert "不要要求或推荐模型构造解析器内部的 angle 调用" in text


@pytest.mark.parametrize("case", CASES)
def test_basic_gold_is_schema_valid_direct_math_and_compiles(case):
    gold = json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema()).validate(gold)
    assert gold["family_id"] == "basic_inequality"
    assert gold["match_status"] == "matched"
    assert gold["original_text"].strip()
    assert not any(any(token in text for token in FORBIDDEN) for text in _strings(gold))
    report = NotationValidator().validate(gold)
    assert report.ok, report.payload()
    assert canonical(report)


def test_basic_fixture_manifest_is_image_only_and_frozen():
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["cases"] == list(CASES)
    assert manifest["image_only"] is True
    assert manifest["gold_review"]["status"] == "human_confirmed"
    for case in CASES:
        entry = manifest["images"][case]
        image = FIXTURES / entry["file"]
        assert image.is_file()
        assert sha256(image.read_bytes()).hexdigest() == entry["sha256"]
        with Image.open(image) as opened:
            assert opened.format == "PNG"
            assert list(opened.size) == entry["size"]
        assert sha256((FIXTURES / f"{case}.json").read_bytes()).hexdigest() == manifest[
            "gold_sha256"
        ][case]


def test_product_few_shot_binds_only_the_two_source_variables():
    examples = [
        json.loads(text)
        for text in re.findall(
            r"```json\n(.*?)\n```", SYSTEM_PATH.read_text(encoding="utf-8"), re.DOTALL
        )
    ]
    example = next(item for item in examples if "uv=6" in item["original_text"])
    report = NotationValidator().validate(example)
    assert report.ok, report.payload()
    assert {(item["name"], item["kind"]) for item in report.objects} == {
        ("u", "scalar"), ("v", "scalar")
    }
    assert example["root"]["goals"][0]["expression"] == "(u*v)^2/(u+v)+u*(v+1)"


def test_q20_product_and_independent_xy_symbol_are_not_equivalent():
    gold = json.loads((FIXTURES / "q20.json").read_text(encoding="utf-8"))
    assert compare(gold, gold)["ok"]
    ambiguous = deepcopy(gold)
    ambiguous["root"]["facts"][2] = "(x-y)^2 = (xy)^3"
    report = NotationValidator().validate(ambiguous)
    assert report.ok, report.payload()
    assert {item["name"] for item in report.objects} == {"x", "y", "xy"}
    result = compare(gold, ambiguous)
    assert not result["ok"]
    assert result["classification"] == "not_proven_equivalent"
    assert {item["path"] for item in result["differences"]} == {"/root/facts"}


@pytest.mark.parametrize("case", CASES)
def test_basic_gold_replays_through_image_only_gate(tmp_path, case):
    from shuxueshuo_server.problem_understanding.basic_inequality_smoke import (
        prepare_fixture,
    )
    from shuxueshuo_server.problem_understanding.batch_smoke import preflight
    from shuxueshuo_server.problem_understanding.smoke import run

    fixture = prepare_fixture(case, tmp_path / case)
    registry = list(notation_family_catalog())
    provider = Recorded((fixture / "gold.json").read_text(encoding="utf-8"))
    preflight(fixture, tmp_path / case, provider, registry)
    summary = run(fixture, tmp_path / case / "run", provider, registry)
    assert summary["passed"], summary
    assert summary["match_correct"]
    assert summary["candidate_only"] and not summary["solver_ready"]
    assert provider.calls == 1
