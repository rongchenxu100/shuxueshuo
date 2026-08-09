from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from test_problem_domain_schema import _payload


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_FIXTURES = ROOT / "internal/problem-domain-fixtures"
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-heping-yimo-25",
)


def _gold(case: str) -> dict:
    return json.loads((DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES)
def test_five_authored_domain_graphs_pass_full_pure_preflight(case: str) -> None:
    result = ProblemDomainValidator().validate(ProblemDraft.create(_gold(case)))

    assert result.report.ok, result.report.to_payload()
    assert result.projection is not None
    assert all(
        stamp.status == "verified"
        for stamp in result.draft.verification_stamps.values()
    )
    assert result.draft.repairable_unit_ids == ()


def test_lexical_scope_reads_ancestors_but_rejects_siblings_and_shadowing() -> None:
    payload = _payload()
    payload["root"]["children"].append(
        {
            "id": "ii",
            "label": "第（Ⅱ）问",
            "source_text": ["求点 B。"],
            "entities": [{"id": "B", "kind": "point", "label": "B"}],
            "facts": [],
            "goals": [],
            "children": [],
        }
    )
    payload["root"]["children"][0]["facts"] = [
        {"kind": "point_on_curve", "point": "B", "curve": "parabola"}
    ]
    payload["root"]["children"][0]["entities"] = [
        {"id": "a", "kind": "symbol", "label": "a", "role": "parameter"}
    ]

    report = ProblemDomainValidator().validate(ProblemDraft.create(payload)).report
    codes = {item.code for item in report.issues}

    assert "extraction.problem_reference_unresolved" in codes
    assert "extraction.problem_scope_shadow" in codes


def test_sibling_identity_placement_enters_reference_repair_authority() -> None:
    payload = _gold("tj-2026-heping-yimo-25")
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

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_reference_unresolved"
        and "references 'O'" in item.message
    )
    misplaced = next(
        entity
        for entity in result.draft.graph.scope_by_path["problem/ii"].entities
        if entity.local_id == "O"
    )
    companion = next(
        fact
        for fact in result.draft.graph.scope_by_path["problem/ii"].facts
        if fact.kind == "point_construction"
        and fact.attributes.get("construction") == "origin"
    )

    assert misplaced.unit_id in issue.unit_ids
    assert companion.unit_id in issue.unit_ids
    assert result.draft.graph.root_scope.unit_id in issue.dependency_unit_ids
    assert misplaced.unit_id in result.draft.repairable_unit_ids
    assert result.draft.graph.root_scope.unit_id in result.draft.repairable_unit_ids


def test_child_cannot_redeclare_ancestor_source_identity_under_a_new_id() -> None:
    payload = _payload()
    payload["root"]["children"][0]["entities"] = [
        {
            "id": "local_a",
            "kind": "symbol",
            "label": "a",
            "role": "primary_parameter",
        }
    ]
    payload["root"]["children"][0]["goals"] = [
        {"kind": "parameter_value", "answer_key": "a", "target": "local_a"}
    ]

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert any(
        item.code == "extraction.problem_scope_shadow"
        and "redeclares ancestor" in item.message
        for item in result.report.issues
    )


def test_decorative_named_lines_and_function_left_hand_symbol_are_rejected() -> None:
    payload = _payload()
    payload["root"]["source_text"].append("连接 AB，函数记为 y。")
    payload["root"]["entities"].extend(
        (
            {
                "id": "line_AB",
                "kind": "named_line",
                "label": "AB",
                "points": ["A", "B"],
            },
            {
                "id": "y",
                "kind": "symbol",
                "label": "y",
                "role": "function_variable",
            },
        )
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    unused = {
        unit_id
        for issue in result.report.issues
        if issue.code == "extraction.problem_entity_unreferenced"
        for unit_id in issue.unit_ids
    }
    entities = {
        entity.local_id: entity.unit_id
        for entity in result.draft.graph.root_scope.entities
    }

    assert entities["line_AB"] in unused
    assert entities["y"] in unused


def test_typed_reference_and_expression_symbol_fail_together() -> None:
    payload = _payload()
    payload["root"]["facts"][1] = {
        "kind": "point_on_curve",
        "point": "a",
        "curve": "parabola",
    }
    payload["root"]["facts"][0]["expression"] = "a*x**2+missing*x"

    report = ProblemDomainValidator().validate(ProblemDraft.create(payload)).report
    codes = {item.code for item in report.issues}

    assert "extraction.problem_reference_type_mismatch" in codes
    assert "extraction.problem_expression_symbol_unresolved" in codes


def test_symbol_source_label_can_back_expression_and_typed_symbol_references() -> None:
    payload = _gold("tj-2026-hexi-yimo-25")
    symbol = next(
        item for item in payload["root"]["entities"] if item["id"] == "x"
    )
    symbol["id"] = "function_variable"

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert result.report.ok, result.report.to_payload()


def test_duplicate_symbol_source_label_is_rejected_before_reference_guessing() -> None:
    payload = _gold("tj-2026-hexi-yimo-25")
    payload["root"]["entities"].append(
        {
            "id": "other_x",
            "kind": "symbol",
            "label": "x",
            "role": "function_variable",
        }
    )

    report = ProblemDomainValidator().validate(ProblemDraft.create(payload)).report

    assert any(
        item.code == "extraction.problem_scope_invalid"
        and "runtime handle collision" in item.message
        for item in report.issues
    )


def test_algebraic_expression_cannot_be_disguised_as_an_atomic_symbol() -> None:
    payload = _payload()
    payload["root"]["entities"].append(
        {
            "id": "b_plus_2",
            "kind": "symbol",
            "label": "b+2",
            "role": "parameter",
        }
    )
    payload["root"]["facts"].append(
        {
            "kind": "point_coordinate",
            "point": "A",
            "value": ["b_plus_2", "0"],
        }
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_source_literal_unresolved"
    )

    pseudo_symbol = next(
        item
        for item in result.draft.graph.root_scope.entities
        if item.local_id == "b_plus_2"
    )
    assert issue.unit_ids[0] == pseudo_symbol.unit_id
    assert any(unit_id.startswith("fact:") for unit_id in issue.unit_ids)
    assert pseudo_symbol.unit_id in result.draft.repairable_unit_ids


def test_unused_curve_ordinate_placeholder_is_a_repairable_redundancy() -> None:
    payload = _payload()
    payload["root"]["source_text"].append("点 A 的横坐标为 a，记纵坐标为 d。")
    payload["root"]["entities"].append(
        {"id": "d", "kind": "symbol", "label": "d", "role": "parameter"}
    )
    payload["root"]["facts"].extend(
        (
            {
                "kind": "point_construction",
                "point": "A",
                "construction": "curve_at_x",
                "owner": "parabola",
                "x_expression": "a",
            },
            {"kind": "point_coordinate", "point": "A", "value": ["a", "d"]},
        )
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_fact_redundant"
        and "private ordinate placeholder" in item.message
    )
    ordinate = next(
        entity for entity in result.draft.graph.root_scope.entities
        if entity.local_id == "d"
    )
    coordinate = next(
        fact for fact in result.draft.graph.root_scope.facts
        if fact.kind == "point_coordinate" and fact.attributes["value"] == ("a", "d")
    )

    assert set(issue.unit_ids) == {ordinate.unit_id, coordinate.unit_id}
    assert set(issue.unit_ids).issubset(result.draft.repairable_unit_ids)


def test_curve_x_membership_cannot_compete_with_complete_coordinate_authority() -> None:
    payload = _gold("tj-2026-hexi-yimo-25")
    part3 = next(item for item in payload["root"]["children"] if item["id"] == "iii")
    part3["facts"].append(
        {
            "kind": "point_on_curve_with_x",
            "point": "N",
            "curve": "parabola",
            "x_symbol": "n",
            "x_range": ["0", "+inf"],
        }
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_fact_redundant"
        and "competing source authorities" in item.message
    )
    scope = next(
        item
        for item in result.draft.graph.root_scope.iter_scopes()
        if item.local_id == "iii"
    )
    membership = next(
        fact for fact in scope.facts if fact.kind == "point_on_curve_with_x"
    )
    coordinate = next(
        fact
        for fact in scope.facts
        if fact.kind == "point_coordinate" and fact.attributes["point"] == "N"
    )

    assert set(issue.unit_ids) == {membership.unit_id, coordinate.unit_id}
    assert set(issue.unit_ids).issubset(result.draft.repairable_unit_ids)


def test_descriptive_point_label_is_grounded_by_its_printed_name_token() -> None:
    payload = _payload()
    payload["root"]["source_text"].append("坐标原点为 O，抛物线顶点为 P。")
    payload["root"]["entities"].extend(
        (
            {"id": "O", "kind": "point", "label": "坐标原点O"},
            {"id": "P", "kind": "point", "label": "顶点P"},
        )
    )

    report = ProblemDomainValidator().validate(ProblemDraft.create(payload)).report

    point_ids = {
        item.unit_id
        for item in ProblemDraft.create(payload).graph.root_scope.entities
        if item.local_id in {"O", "P"}
    }
    assert not any(
        item.code == "extraction.problem_source_literal_unresolved"
        and point_ids.intersection(item.unit_ids)
        for item in report.issues
    )


def test_descriptive_point_label_still_rejects_an_unprinted_name() -> None:
    payload = _payload()
    payload["root"]["entities"].append(
        {"id": "Z", "kind": "point", "label": "顶点Z"}
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    point = next(
        item for item in result.draft.graph.root_scope.entities if item.local_id == "Z"
    )

    assert any(
        item.code == "extraction.problem_source_literal_unresolved"
        and item.unit_ids == (point.unit_id,)
        for item in result.report.issues
    )


def test_named_ray_requires_an_explicit_source_type_marker() -> None:
    payload = _payload()
    payload["root"]["source_text"].append("连接 A、B。")
    payload["root"]["entities"].append(
        {
            "id": "ray_AB",
            "kind": "named_ray",
            "label": "射线AB",
            "origin": "A",
            "through": "B",
        }
    )
    payload["root"]["facts"].append(
        {"kind": "point_on_ray", "point": "A", "ray": "ray_AB"}
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    ray = next(
        item
        for item in result.draft.graph.root_scope.entities
        if item.local_id == "ray_AB"
    )

    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_source_kind_ungrounded"
    )
    assert issue.unit_ids[0] == ray.unit_id
    assert any(unit_id.startswith("fact:") for unit_id in issue.unit_ids)


def test_square_orientation_is_not_repeated_as_quadrant_membership() -> None:
    payload = _gold("tj-2026-heping-ermo-25")
    square = next(
        fact for fact in payload["root"]["facts"] if fact["kind"] == "square"
    )
    square["orientation"] = {
        "point": "G",
        "relation": "below_x_axis",
    }
    payload["root"]["facts"].append(
        {"kind": "quadrant_membership", "point": "G", "quadrant": "x轴下方"}
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert any(
        item.code == "extraction.problem_fact_redundant"
        for item in result.report.issues
    )


def test_conflicting_point_coordinates_are_unit_scoped() -> None:
    payload = _payload()
    payload["root"]["facts"].extend(
        (
            {"kind": "point_coordinate", "point": "A", "value": ["0", "0"]},
            {"kind": "point_coordinate", "point": "A", "value": ["1", "0"]},
        )
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_definition_conflict"
    )

    assert len(issue.unit_ids) == 2
    assert set(issue.unit_ids).issubset(result.draft.repairable_unit_ids)
    assert result.draft.graph.root_scope.unit_id in result.draft.repairable_unit_ids


def test_llm_selected_family_is_validated_but_never_auto_replaced() -> None:
    payload = _gold("tj-2026-hexi-yimo-25")
    payload["family_id"] = "QuadraticPathMinimumSolver"

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert result.draft.graph.family_id == "QuadraticPathMinimumSolver"
    assert any(
        item.code == "extraction.problem_family_contract_mismatch"
        for item in result.report.issues
    )


def test_family_contract_is_reported_even_when_runtime_projection_fails() -> None:
    payload = _gold("tj-2026-heping-ermo-25")
    payload["family_id"] = "QuadraticPathMinimumSolver"
    payload["root"]["facts"].append(
        {
            "kind": "point_coordinate",
            "point": "missing_point",
            "value": ["0", "0"],
        }
    )

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    codes = {item.code for item in result.report.issues}

    assert result.projection is None
    assert "extraction.problem_runtime_projection_failed" in codes
    assert "extraction.problem_family_contract_mismatch" in codes


def test_ungrounded_ray_repair_cone_does_not_unfreeze_independent_equal_length() -> None:
    payload = _gold("tj-2026-nankai-yimo-25")
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

    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    equal_length = next(
        fact for fact in result.draft.graph.scope_by_path["problem/ii"].facts
        if fact.kind == "equal_length"
    )

    assert any(
        item.code == "extraction.problem_source_kind_ungrounded"
        for item in result.report.issues
    )
    assert equal_length.unit_id not in result.draft.repairable_unit_ids
    assert result.draft.verification_stamps[equal_length.unit_id].status == "verified"


def test_missing_family_primitive_authorizes_addition_without_unfreezing_graph() -> None:
    payload = _gold("tj-2026-nankai-yimo-25")

    def remove_minimum_facts(scope: dict) -> None:
        scope["facts"] = [
            fact
            for fact in scope["facts"]
            if fact["kind"] not in {"minimum_target", "minimum_value_given"}
        ]
        for child in scope["children"]:
            remove_minimum_facts(child)

    remove_minimum_facts(payload["root"])
    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    issue = next(
        item
        for item in result.report.issues
        if item.code == "extraction.problem_family_contract_mismatch"
    )

    assert issue.unit_ids == ("family",)
    assert issue.dependency_unit_ids
    assert all(
        result.draft.verification_stamps[unit_id].status == "verified"
        for unit_id, record in result.draft.unit_registry.items()
        if record.unit_kind in {"entity", "fact"}
    )
    assert set(issue.dependency_unit_ids).issubset(result.draft.repairable_unit_ids)


def test_fact_and_goal_reordering_does_not_change_validation_authority() -> None:
    payload = _gold("tj-2026-nankai-yimo-25")
    reordered = deepcopy(payload)
    reordered["root"]["facts"].reverse()
    reordered["root"]["goals"].reverse()
    first = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    second = ProblemDomainValidator().validate(ProblemDraft.create(reordered))

    assert first.report.to_payload() == second.report.to_payload()
    assert first.draft.revision_id == second.draft.revision_id
