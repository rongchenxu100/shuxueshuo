from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pytest

from shuxueshuo_server.solver.extraction.problem_domain_smoke import (
    DEFAULT_F2_INPUT,
    _repo_root,
    _resolve_repo_path,
)
from shuxueshuo_server.solver.lesson_authoring_support import (
    CASE_ID,
    build_recorded_snapshot,
    load_teaching_rubric,
)
from shuxueshuo_server.solver.lesson_teaching_spec_review import (
    REVIEW_SCHEMA,
    build_teaching_spec_review,
    main,
    render_teaching_spec_review_html,
)


ROOT = Path(__file__).resolve().parents[3]
B0 = ROOT / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b0"
B1 = ROOT / "server/tests/solver/fixtures/lesson_scope_authoring_vnext/heping_ermo_b1"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot_and_review():
    root = _repo_root()
    with tempfile.TemporaryDirectory(prefix="lesson-b1-test-authority-") as temp_dir:
        snapshot = build_recorded_snapshot(
            CASE_ID,
            authority_dir=Path(temp_dir),
            f2_root=_resolve_repo_path(root, DEFAULT_F2_INPUT),
        )
    review = build_teaching_spec_review(
        snapshot,
        baseline_snapshot=_json(B0 / "snapshot.json"),
        baseline_snapshot_path=(
            "server/tests/solver/fixtures/lesson_scope_authoring_vnext/"
            "heping_ermo_b0/snapshot.json"
        ),
        rubric=load_teaching_rubric(B0 / "rubric.json"),
    )
    return snapshot, review


def test_review_has_12_occurrence_cards_and_13_materials(snapshot_and_review) -> None:
    _snapshot, review = snapshot_and_review
    assert review["schema_version"] == REVIEW_SCHEMA
    assert review["summary"]["step_card_count"] == 12
    assert review["summary"]["teaching_material_count"] == 13
    assert review["summary"]["function_card_count"] == 11
    assert review["summary"]["macro_card_count"] == 1
    assert review["summary"]["unique_capability_count"] == 9
    assert review["summary"]["review_status"] == "awaiting_human_review"
    assert all(
        card["validation"]["status"] == "ready_for_review"
        for card in review["cards"]
    )


def test_review_compares_b0_step_runtime_generic_and_bound_columns(
    snapshot_and_review,
) -> None:
    _snapshot, review = snapshot_and_review
    card = next(
        item
        for item in review["cards"]
        if item["step_id"] == "derive_path_minimum_ii"
    )
    assert set(card) == {
        "anchor",
        "step_id",
        "owner",
        "capability_id",
        "kind",
        "same_capability_occurrences",
        "previous_plan_step",
        "verified_runtime",
        "generic_spec",
        "bound_suggestions",
        "validation",
    }
    assert card["previous_plan_step"]["args"]
    assert card["verified_runtime"]["inputs"]
    assert card["verified_runtime"]["calculations"]
    assert len(card["generic_spec"]["macro_teaching"]["teaching_units"]) == 2
    assert len(card["bound_suggestions"]) == 2
    assert all(
        "evidence_refs" not in item["verified_runtime"]
        for item in review["cards"]
    )


def test_review_parametric_quadratic_explains_verified_curve_point_substitution(
    snapshot_and_review,
) -> None:
    _snapshot, review = snapshot_and_review
    card = next(
        item
        for item in review["cards"]
        if item["step_id"] == "derive_parametric_parabola_ii"
    )
    generic = json.dumps(card["generic_spec"], ensure_ascii=False)
    bound = json.dumps(card["bound_suggestions"], ensure_ascii=False)
    assert "derive_items" in generic
    assert "{constraint_origin}" in generic
    assert "{constraint_derivation}" in generic
    assert "具体点名、坐标或答案" in generic
    assert "A(－c,0) 在 y＝" in bound
    assert "b＝1－c" in bound


def test_review_macro_reaches_five_of_five_smoke_rubric(snapshot_and_review) -> None:
    _snapshot, review = snapshot_and_review
    evaluation = review["summary"]["rubric_coverage"]
    assert evaluation["coverage_rate"] == 1.0
    assert evaluation["missing"] == []
    assert len(evaluation["covered"]) == 5


def test_review_repeated_capabilities_link_all_occurrences(snapshot_and_review) -> None:
    _snapshot, review = snapshot_and_review
    quadratic_cards = [
        item
        for item in review["cards"]
        if item["capability_id"] == "quadratic_from_constraints"
    ]
    assert len(quadratic_cards) == 2
    assert all(
        card["same_capability_occurrences"]
        == ["derive_parabola_i", "derive_parametric_parabola_ii"]
        for card in quadratic_cards
    )
    assert (
        quadratic_cards[0]["generic_spec"]
        == quadratic_cards[1]["generic_spec"]
    )
    assert (
        quadratic_cards[0]["bound_suggestions"]
        != quadratic_cards[1]["bound_suggestions"]
    )


def test_review_html_is_self_contained_and_has_four_review_columns(
    snapshot_and_review,
) -> None:
    _snapshot, review = snapshot_and_review
    html = render_teaching_spec_review_html(review)
    for heading in (
        "B0 Previous Plan Step",
        "B1 Verified Runtime",
        "Generic Spec",
        "Bound Suggestion",
    ):
        assert heading in html
    assert html.count('class="card"') == 12
    assert "https://" not in html and "http://" not in html
    assert "step-derive_path_minimum_ii" in html


def test_review_json_and_snapshot_v3_match_checked_in_goldens(
    snapshot_and_review,
) -> None:
    snapshot, review = snapshot_and_review
    actual_snapshot = snapshot.to_payload()
    expected_snapshot = _json(B1 / "snapshot.json")
    actual_snapshot["verified_execution_hash"] = "<run-local>"
    expected_snapshot["verified_execution_hash"] = "<run-local>"
    # Witness IDs authenticate source/run provenance as well as mathematics.
    # Keep every evidence payload and its kind in this teaching-content check,
    # without requiring a replay to reuse the original authority identifier.
    for payload in (actual_snapshot, expected_snapshot):
        payload["evidence"] = sorted(
            ((key.split(":", 1)[0], value) for key, value in payload["evidence"].items()),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    assert actual_snapshot == expected_snapshot
    assert review == _json(B1 / "teaching-spec-review.json")


def test_review_cli_writes_create_once_auditable_artifacts(tmp_path: Path) -> None:
    args = [
        "--case",
        CASE_ID,
        "--baseline-snapshot",
        str(B0 / "snapshot.json"),
        "--batch-id",
        "review-test",
        "--output-root",
        str(tmp_path),
    ]
    assert main(args) == 0
    output = tmp_path / "review-test"
    assert {item.name for item in output.iterdir()} == {
        "snapshot.json",
        "teaching-spec-review.json",
        "review.html",
    }
    with pytest.raises(Exception, match="output_exists"):
        main(args)
