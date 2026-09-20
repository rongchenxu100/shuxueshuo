"""Offline regression against immutable model responses, never fresh LLM calls."""

import json
from hashlib import sha256
from pathlib import Path

import pytest
from _math_notation_test_support import assert_removed_at_rejected

from shuxueshuo_server.problem_understanding.candidate_common import strict_json
from shuxueshuo_server.problem_understanding.notation_semantics import evaluate
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate
from shuxueshuo_server.solver.extraction.artifacts import ExtractionArtifactStore

FIXTURES = Path(__file__).parent / "fixtures/math-notation-v1"
RECORDED = FIXTURES / "recorded-latest-20260916"
MANIFEST = json.loads((RECORDED / "manifest.json").read_text())


@pytest.mark.parametrize("entry", MANIFEST["cases"], ids=lambda row: row["case"])
def test_original_seven_responses_offline_regression(entry, tmp_path):
    case = entry["case"]
    raw = (RECORDED / f"{case}.txt").read_bytes()
    gold = (RECORDED / f"{case}.gold.json").read_bytes()
    assert sha256(raw).hexdigest() == entry["raw_sha256"]
    assert sha256(gold).hexdigest() == entry["gold_sha256"]
    actual, expected = strict_json(raw.decode()), json.loads(gold)
    policy = None
    if "policy_sha256" in entry:
        saved = (RECORDED / f"{case}.policy.json").read_bytes()
        assert sha256(saved).hexdigest() == entry["policy_sha256"]
        policy = json.loads(saved)
    result = evaluate(expected, actual, policy)
    parsed = parse_candidate(
        raw.decode(),
        problem_id=case,
        source_sha256="0" * 64,
        registry_snapshot="0" * 64,
        registered_families=[expected["family_id"]] if expected["family_id"] else [],
        store=ExtractionArtifactStore(tmp_path),
    )
    assert parsed["candidate_only"] and not parsed["solver_ready"]
    if assert_removed_at_rejected(expected, actual):
        assert not result["ok"]
        return  # Frozen historical scores are not current-contract acceptance.
    assert result["ok"] is entry["expected_offline_passed"], result
    assert parsed["reports"]["match"]["ok"]
    assert actual["match_status"] == expected["match_status"]
    assert actual["family_id"] == expected["family_id"]
    if entry["expected_offline_passed"]:
        assert parsed["contract_valid"] and not parsed["continuation"]["blocked"]
    else:
        assert case == "k-quad"
        assert not parsed["contract_valid"]
        issues = result["strict"]["actual_issues"]
        assert any(e["message"] == "type.intersection" for e in issues)
        assert len(issues) == 1  # Endpoint signatures removed seven cascade errors.
        # Invalid notation blocks this response, but does not count as successful
        # detection of the intentionally absent diagrams.
        assert parsed["continuation"]["blocked"]
        assert parsed["continuation"]["status"] == "invalid_candidate"
        assert parsed["continuation"].get("error_code") != "extraction.missing_figure"
    if case in ("tj-2026-hexi-yimo-25", "tj-2026-xiqing-yimo-25"):
        assert parsed["reports"]["ir"]["coordinate_bindings"]
    if case == "tj-2026-heping-ermo-25":
        rules = {p["rule"] for p in parsed["reports"]["ir"]["normalization_proofs"]}
        assert {
            "quadratic_axis_unique",
            "nondegenerate_parallelogram_diagonals",
        } <= rules


def test_original_live_outcomes_remain_distinct_from_offline_results():
    assert MANIFEST["network_calls"] == 0
    assert len(MANIFEST["cases"]) == 7
    assert sum(c["live_passed"] for c in MANIFEST["cases"]) == 2
    assert sum(c["expected_offline_passed"] for c in MANIFEST["cases"]) == 5
