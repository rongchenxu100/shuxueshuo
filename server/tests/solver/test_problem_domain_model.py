from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDomainError,
    ProblemDraft,
    ProblemPromotionService,
    ProblemValidationIssue,
    ProblemValidationReport,
    ProblemVerificationStamp,
    VerifiedProblem,
)
from test_problem_domain_schema import _payload


ROOT = Path(__file__).resolve().parents[3]


def test_fact_and_goal_reordering_does_not_drift_identity() -> None:
    payload = _payload()
    payload["root"]["goals"] = [
        {"kind": "quadratic_equation", "answer_key": "parabola", "target": "parabola"}
    ]
    first = ProblemDraft.create(payload)
    reordered = deepcopy(payload)
    reordered["root"]["facts"].reverse()
    reordered["root"]["goals"].reverse()
    second = ProblemDraft.create(reordered)

    assert first.semantic_hash == second.semantic_hash
    assert first.revision_id == second.revision_id
    assert set(first.unit_registry) == set(second.unit_registry)


def test_source_text_and_child_order_are_revision_authority() -> None:
    first = ProblemDraft.create(_payload())
    changed = _payload()
    changed["root"]["source_text"][0] += "补充条件"
    assert ProblemDraft.create(changed).revision_id != first.revision_id
    assert ProblemDraft.create(changed).semantic_hash != first.semantic_hash

    two_children = _payload()
    two_children["root"]["children"].append(
        {
            "id": "ii",
            "label": "第（Ⅱ）问",
            "source_text": ["求 a。"],
            "entities": [],
            "facts": [],
            "goals": [{"kind": "parameter_value", "answer_key": "a", "target": "a"}],
            "children": [],
        }
    )
    reordered = deepcopy(two_children)
    reordered["root"]["children"].reverse()
    assert ProblemDraft.create(two_children).revision_id != ProblemDraft.create(reordered).revision_id


def test_source_text_punctuation_and_spacing_do_not_cause_semantic_drift() -> None:
    first = ProblemDraft.create(_payload())
    changed = _payload()
    changed["root"]["source_text"][0] = "已知抛物线， y = a*x**2 + b*x + c"

    second = ProblemDraft.create(changed)

    assert second.revision_id != first.revision_id
    assert second.semantic_hash == first.semantic_hash


def test_source_text_line_segmentation_does_not_cause_semantic_drift() -> None:
    first = ProblemDraft.create(_payload())
    changed = _payload()
    changed["root"]["source_text"] = ["已知抛物线", "y=ax^2+bx+c。"]

    second = ProblemDraft.create(changed)

    assert second.revision_id != first.revision_id
    assert second.semantic_hash == first.semantic_hash


def test_typed_square_orientation_is_semantically_significant() -> None:
    payload = json.loads(
        (
            ROOT
            / "internal/problem-domain-fixtures"
            / "tj-2026-heping-ermo-25.json"
        ).read_text(encoding="utf-8")
    )
    first = ProblemDraft.create(payload)
    changed = deepcopy(payload)
    square = next(
        fact for fact in changed["root"]["facts"] if fact["kind"] == "square"
    )
    square["orientation"]["relation"] = "above_x_axis"

    second = ProblemDraft.create(changed)

    assert second.revision_id != first.revision_id
    assert second.semantic_hash != first.semantic_hash


def test_curve_at_x_and_coordinate_plus_curve_membership_share_semantics() -> None:
    payload = json.loads(
        (
            ROOT
            / "internal/problem-domain-fixtures"
            / "tj-2026-nankai-yimo-25.json"
        ).read_text(encoding="utf-8")
    )
    first = ProblemDraft.create(payload)
    changed = deepcopy(payload)
    scope = changed["root"]["children"][1]
    membership = next(
        fact
        for fact in scope["facts"]
        if fact["kind"] == "point_on_curve" and fact["point"] == "M"
    )
    scope["facts"].remove(membership)
    scope["facts"].append(
        {
            "kind": "point_construction",
            "point": "M",
            "construction": "curve_at_x",
            "owner": "parabola",
            "x_expression": "m",
        }
    )

    second = ProblemDraft.create(changed)

    assert second.revision_id != first.revision_id
    assert second.semantic_hash == first.semantic_hash


def test_consistent_local_id_rename_changes_revision_not_semantics() -> None:
    first = ProblemDraft.create(_payload())
    renamed = _payload()
    symbol = next(
        item for item in renamed["root"]["entities"] if item["id"] == "a"
    )
    symbol["id"] = "coefficient_a"
    expression = next(
        item
        for item in renamed["root"]["facts"]
        if item["kind"] == "function_expression"
    )
    expression["expression"] = "coefficient_a*x**2+b*x"

    second = ProblemDraft.create(renamed)

    assert second.revision_id != first.revision_id
    assert second.semantic_hash == first.semantic_hash


def test_display_labels_answer_keys_and_source_name_wrappers_are_not_math_drift() -> None:
    first = ProblemDraft.create(_payload())
    changed = _payload()
    changed["root"]["label"] = "题目整体"
    changed["root"]["children"][0]["label"] = "第一问"
    changed["root"]["children"][0]["goals"][0]["answer_key"] = "answer_A"
    point = next(item for item in changed["root"]["entities"] if item["id"] == "A")
    point["id"] = "point_A"
    point["label"] = "点A"
    changed["root"]["facts"][1]["point"] = "point_A"
    changed["root"]["children"][0]["goals"][0]["target"] = "point_A"

    second = ProblemDraft.create(changed)

    assert second.revision_id != first.revision_id
    assert second.semantic_hash == first.semantic_hash




def test_verified_problem_round_trip_preserves_internal_unit_identity() -> None:
    draft = ProblemDraft.create(_payload())
    stamps = {
        unit_id: ProblemVerificationStamp(
            unit_id,
            record.semantic_signature,
            ("test",),
            (),
            "verified",
        )
        for unit_id, record in draft.unit_registry.items()
    }
    verified = ProblemPromotionService().promote(
        draft.with_validation(ProblemValidationReport(), stamps, ())
    )

    restored = type(verified).from_payload(verified.to_payload())

    assert restored.to_payload() == verified.to_payload()


def test_verified_problem_cannot_be_constructed_without_promotion() -> None:
    draft = ProblemDraft.create(_payload())

    with pytest.raises(TypeError, match="promotion"):
        VerifiedProblem(
            graph=draft.graph,
            revision_id=draft.revision_id,
            parent_revision_id=None,
            semantic_hash=draft.semantic_hash,
            family_id=draft.graph.family_id,
            verification_proof={},
            _authority=object(),
        )


def test_problem_draft_registries_are_truly_immutable() -> None:
    draft = ProblemDraft.create(_payload())

    with pytest.raises(TypeError):
        draft.unit_registry["injected"] = next(iter(draft.unit_registry.values()))
    with pytest.raises(TypeError):
        draft.verification_stamps["injected"] = ProblemVerificationStamp(
            "injected", "0" * 64, (), (), "verified"
        )








def _repairable_draft(
    *,
    unit_ids: tuple[str, ...],
    dependency_unit_ids: tuple[str, ...] = (),
) -> ProblemDraft:
    draft = ProblemDraft.create(_payload())
    issue = ProblemValidationIssue(
        code="extraction.synthetic_invalid",
        unit_ids=unit_ids,
        dependency_unit_ids=dependency_unit_ids,
        message="synthetic repair boundary",
        repair_action="repair only the named invalid units",
    )
    report = ProblemValidationReport(issues=(issue,), validator_ids=("test",))
    repairable = (*unit_ids, *dependency_unit_ids, "scope:problem")
    return draft.with_validation(report, {}, repairable)












def test_semantic_hash_strips_only_the_root_header_not_its_body() -> None:
    plain = _payload()
    with_header = json.loads(json.dumps(plain, ensure_ascii=False))
    original = plain["root"]["source_text"][0]
    with_header["root"]["source_text"] = [f"（25）（本小题12分）{original}"]

    plain_graph = ProblemDraft.create(plain).graph
    header_graph = ProblemDraft.create(with_header).graph

    assert plain_graph.semantic_hash == header_graph.semantic_hash

    changed = json.loads(json.dumps(with_header, ensure_ascii=False))
    changed["root"]["source_text"] = ["（25）（本小题12分）另一道题的正文"]
    assert ProblemDraft.create(changed).graph.semantic_hash != plain_graph.semantic_hash


def test_semantic_hash_ignores_scope_local_question_markers() -> None:
    payload = json.loads(
        (
            ROOT
            / "internal/problem-domain-fixtures"
            / "tj-2026-nankai-yimo-25.json"
        ).read_text(encoding="utf-8")
    )
    without_markers = deepcopy(payload)
    part_i, part_ii = without_markers["root"]["children"]
    part_i["source_text"][0] = part_i["source_text"][0].removeprefix("（Ⅰ）")
    part_ii["source_text"][0] = part_ii["source_text"][0].removeprefix("（Ⅱ）")
    part_ii["children"][0]["source_text"][0] = part_ii["children"][0][
        "source_text"
    ][0].removeprefix("①")
    part_ii["children"][1]["source_text"][0] = part_ii["children"][1][
        "source_text"
    ][0].removeprefix("②")

    expected = ProblemDraft.create(payload)
    actual = ProblemDraft.create(without_markers)

    assert actual.revision_id != expected.revision_id
    assert actual.semantic_hash == expected.semantic_hash
