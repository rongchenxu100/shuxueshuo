from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
from shuxueshuo_server.solver.extraction.problem_domain_canonicalization import (
    ProblemDomainCanonicalizer,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)


ROOT = Path(__file__).resolve().parents[3]
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-heping-yimo-25",
)


def _gold(case: str = "tj-2026-heping-yimo-25") -> dict:
    return json.loads(
        (ROOT / "internal/problem-domain-fixtures" / f"{case}.json").read_text(
            encoding="utf-8"
        )
    )


def _scope(payload: dict, scope_id: str) -> dict:
    pending = [payload["root"]]
    while pending:
        current = pending.pop()
        if current["id"] == scope_id:
            return current
        pending.extend(reversed(current["children"]))
    raise AssertionError(f"scope {scope_id!r} not found")


@pytest.mark.parametrize("case", CASES)
def test_five_authored_domain_graphs_are_already_canonical(case: str) -> None:
    draft = ProblemDraft.create(_gold(case))

    result = ProblemDomainCanonicalizer().canonicalize(draft)

    assert result.actions == ()
    assert result.draft.revision_id == draft.revision_id
    assert result.draft.semantic_hash == draft.semantic_hash


def test_quadratic_origin_is_declared_once_at_problem_scope_even_when_model_omits_entity() -> None:
    payload = _gold()
    root = payload["root"]
    root["entities"] = [item for item in root["entities"] if item["id"] != "O"]
    root["facts"] = [
        item
        for item in root["facts"]
        if not (
            item["kind"] == "point_construction"
            and item.get("construction") == "origin"
        )
    ]
    part_i_2 = _scope(payload, "i_2")
    part_i_2["facts"].insert(
        0,
        {
            "kind": "point_construction",
            "point": "point_O",
            "construction": "origin",
        },
    )

    canonicalization = ProblemDomainCanonicalizer().canonicalize(
        ProblemDraft.create(payload)
    )
    draft = canonicalization.draft
    root = draft.graph.root_scope

    assert [item.local_id for item in root.entities].count("O") == 1
    assert any(
        item.kind == "point_construction"
        and item.attributes.get("construction") == "origin"
        and item.attributes.get("point") == "O"
        for item in root.facts
    )
    assert not any(
        item.kind == "point_construction"
        and item.attributes.get("construction") == "origin"
        for scope in root.children
        for child_scope in scope.iter_scopes()
        for item in child_scope.facts
    )
    assert {
        item.code for item in canonicalization.actions
    } >= {"declare_coordinate_origin", "promote_coordinate_origin_fact"}
    validation = ProblemDomainValidator().validate(draft)
    assert validation.report.ok, validation.report.to_payload()


def test_ancestor_entity_redeclaration_is_merged_and_local_facts_are_retargeted() -> None:
    payload = _gold()
    part_ii = _scope(payload, "ii")
    part_ii["entities"].append(
        {
            "id": "a_param",
            "kind": "symbol",
            "label": "a",
            "role": "primary_parameter",
        }
    )
    part_ii["facts"].append(
        {"kind": "symbol_value", "symbol": "a_param", "value": "2"}
    )
    next(item for item in part_ii["goals"] if item["kind"] == "parameter_value")[
        "target"
    ] = "a_param"

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))
    part_ii_scope = result.draft.graph.scope_by_path["problem/ii"]

    assert all(item.local_id != "a_param" for item in part_ii_scope.entities)
    assert any(
        item.kind == "symbol_value"
        and item.attributes.get("symbol") == "a"
        and item.attributes.get("value") == "2"
        for item in part_ii_scope.facts
    )
    assert next(
        item for item in part_ii_scope.goals if item.kind == "parameter_value"
    ).attributes["target"] == "a"
    assert any(
        item.code == "merge_lexical_entity"
        and item.source_local_id == "a_param"
        and item.target_local_id == "a"
        for item in result.actions
    )


def test_scope_local_assignments_remain_distinct_runtime_facts_after_symbol_merge() -> None:
    payload = _gold()
    part_i = _scope(payload, "i")
    part_ii = _scope(payload, "ii")
    part_i["entities"].append(
        {"id": "a_i", "kind": "symbol", "label": "a", "role": "parameter"}
    )
    part_ii["entities"].append(
        {"id": "a_ii", "kind": "symbol", "label": "a", "role": "parameter"}
    )
    part_i["facts"].append(
        {"kind": "symbol_value", "symbol": "a_i", "value": "1"}
    )
    part_ii["facts"].append(
        {"kind": "symbol_value", "symbol": "a_ii", "value": "2"}
    )

    draft = ProblemDomainCanonicalizer().canonicalize(
        ProblemDraft.create(payload)
    ).draft
    projection = ProblemDomainProjector().project_graph(
        draft.graph,
        revision_id=draft.revision_id,
        semantic_hash=draft.semantic_hash,
    )
    values = [
        item
        for item in projection.canonical_input["facts"]
        if item["type"] == "symbol_value" and item["value"] in {"1", "2"}
    ]

    assert len(values) == 2
    assert len({item["subject"] for item in values}) == 1
    assert {item["scope_id"] for item in values} == {"i", "ii"}
    assert len({item["handle"] for item in values}) == 2


def test_same_label_entities_in_sibling_scopes_are_not_merged_without_ancestor() -> None:
    payload = _gold()
    part_i = _scope(payload, "i")
    part_ii = _scope(payload, "ii")
    part_i["entities"].append(
        {"id": "t_i", "kind": "symbol", "label": "t", "role": "parameter"}
    )
    part_ii["entities"].append(
        {"id": "t_ii", "kind": "symbol", "label": "t", "role": "parameter"}
    )

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert any(
        item.local_id == "t_i"
        for item in result.draft.graph.scope_by_path["problem/i"].entities
    )
    assert any(
        item.local_id == "t_ii"
        for item in result.draft.graph.scope_by_path["problem/ii"].entities
    )
    assert not any(
        item.source_local_id in {"t_i", "t_ii"} for item in result.actions
    )


def test_same_kind_and_label_with_conflicting_identity_attributes_is_not_merged() -> None:
    payload = _gold()
    root = payload["root"]
    root["entities"].append(
        {
            "id": "ray_Q",
            "kind": "named_ray",
            "label": "射线Q",
            "origin": "A",
            "through": "B",
        }
    )
    part_ii = _scope(payload, "ii")
    part_ii["entities"].append(
        {
            "id": "ray_Q_child",
            "kind": "named_ray",
            "label": "射线Q",
            "origin": "C",
            "through": "D",
        }
    )

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert any(
        item.local_id == "ray_Q_child"
        for item in result.draft.graph.scope_by_path["problem/ii"].entities
    )


def test_non_quadratic_graph_does_not_invent_a_coordinate_origin() -> None:
    payload = _gold()
    payload["root"]["entities"] = [
        item
        for item in payload["root"]["entities"]
        if item["kind"] != "quadratic_function" and item["id"] != "O"
    ]
    payload["root"]["facts"] = [
        item
        for item in payload["root"]["facts"]
        if item["kind"] != "function_expression"
        and not (
            item["kind"] == "point_construction"
            and item.get("construction") == "origin"
        )
    ]

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert all(item.local_id != "O" for item in result.draft.graph.root_scope.entities)
    assert not any(item.code.startswith("declare_coordinate_origin") for item in result.actions)


def test_quadratic_graph_drops_coordinate_origin_not_referenced_by_source_or_relations() -> None:
    payload = _gold("tj-2026-nankai-yimo-25")
    payload["root"]["entities"].append(
        {"id": "O", "kind": "point", "label": "O", "role": "origin"}
    )
    payload["root"]["facts"].append(
        {"kind": "point_construction", "point": "O", "construction": "origin"}
    )
    expected = ProblemDraft.create(_gold("tj-2026-nankai-yimo-25"))

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert result.draft.semantic_hash == expected.semantic_hash
    assert all(item.local_id != "O" for item in result.draft.graph.root_scope.entities)
    assert any(
        item.code == "drop_unreferenced_coordinate_origin"
        for item in result.actions
    )


def test_symmetry_axis_and_x_axis_memberships_canonicalize_to_intercept() -> None:
    gold = _gold("tj-2026-nankai-yimo-25")
    payload = json.loads(json.dumps(gold))
    root = payload["root"]
    root["facts"] = [
        fact
        for fact in root["facts"]
        if not (
            fact["kind"] == "point_construction"
            and fact["construction"] == "axis_x_intercept"
            and fact["point"] == "D"
        )
    ]
    root["facts"].extend(
        (
            {"kind": "point_on_axis", "point": "D", "axis": "x"},
            {
                "kind": "point_on_axis",
                "point": "D",
                "axis": "symmetry",
                "curve": "parabola",
            },
        )
    )
    expected = ProblemDraft.create(gold)

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert result.draft.semantic_hash == expected.semantic_hash
    assert [item.code for item in result.actions].count(
        "canonicalize_axis_x_intersection"
    ) == 1
    validation = ProblemDomainValidator().validate(result.draft)
    assert validation.report.ok, validation.report.to_payload()


def test_compound_range_and_given_minimum_materialize_solver_primitive_facts() -> None:
    gold = _gold("tj-2026-heping-yimo-25")
    payload = json.loads(json.dumps(gold))
    part_i_2 = _scope(payload, "i_2")
    part_i_2["facts"] = [
        item for item in part_i_2["facts"] if item["kind"] != "symbol_constraint"
    ]
    part_ii = _scope(payload, "ii")
    part_ii["facts"] = [
        item for item in part_ii["facts"] if item["kind"] != "minimum_target"
    ]
    expected = ProblemDraft.create(gold)

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert result.draft.semantic_hash == expected.semantic_hash
    assert [item.code for item in result.actions].count(
        "materialize_x_range_constraint"
    ) == 2
    assert [item.code for item in result.actions].count(
        "materialize_minimum_target"
    ) == 1
    validation = ProblemDomainValidator().validate(result.draft)
    assert validation.report.ok, validation.report.to_payload()


def test_unbounded_x_range_materializes_only_the_finite_constraint() -> None:
    gold = _gold("tj-2026-hexi-yimo-25")
    payload = json.loads(json.dumps(gold))
    part3 = _scope(payload, "iii")
    part3["facts"] = [
        item
        for item in part3["facts"]
        if not (
            item["kind"] == "symbol_constraint" and item["symbol"] == "n"
        )
    ]
    part3["facts"].append(
        {
            "kind": "point_on_curve_with_x",
            "point": "N",
            "curve": "parabola",
            "x_symbol": "n",
            "x_range": ["0", "+inf"],
        }
    )
    part3["facts"].append(
        {
            "kind": "symbol_constraint",
            "symbol": "n",
            "operator": "<",
            "value": "+inf",
        }
    )
    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    canonical_part3 = next(
        scope
        for scope in result.draft.graph.root_scope.iter_scopes()
        if scope.local_id == "iii"
    )
    n_constraints = [
        fact
        for fact in canonical_part3.facts
        if fact.kind == "symbol_constraint" and fact.attributes["symbol"] == "n"
    ]
    assert [
        (fact.attributes["operator"], fact.attributes["value"])
        for fact in n_constraints
    ] == [(">", "0")]
    assert [item.code for item in result.actions].count(
        "materialize_x_range_constraint"
    ) == 1
    assert [item.code for item in result.actions].count(
        "drop_unbounded_symbol_constraint"
    ) == 1
    replay = ProblemDomainCanonicalizer().canonicalize(result.draft)
    assert replay.draft.semantic_hash == result.draft.semantic_hash


def test_given_minimum_materializes_target_for_non_parameter_goal() -> None:
    gold = _gold("tj-2026-heping-ermo-25")
    payload = json.loads(json.dumps(gold))
    part_ii = _scope(payload, "ii")
    part_ii["facts"] = [
        item for item in part_ii["facts"] if item["kind"] != "minimum_target"
    ]
    expected = ProblemDraft.create(gold)

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert result.draft.semantic_hash == expected.semantic_hash
    assert [item.code for item in result.actions].count(
        "materialize_minimum_target"
    ) == 1
    validation = ProblemDomainValidator().validate(result.draft)
    assert validation.report.ok, validation.report.to_payload()


def test_square_center_materializes_both_diagonal_memberships() -> None:
    gold = _gold("tj-2026-heping-ermo-25")
    payload = json.loads(json.dumps(gold))
    part_ii = _scope(payload, "ii")
    part_ii["facts"] = [
        item for item in part_ii["facts"] if item["kind"] != "point_on_segment"
    ]
    expected = ProblemDraft.create(gold)

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert result.draft.semantic_hash == expected.semantic_hash
    assert [item.code for item in result.actions].count(
        "materialize_square_center_membership"
    ) == 2
    validation = ProblemDomainValidator().validate(result.draft)
    assert validation.report.ok, validation.report.to_payload()


def test_minimum_value_goal_materializes_its_solver_target_fact() -> None:
    gold = _gold("tj-2026-nankai-yimo-25")
    payload = json.loads(json.dumps(gold))
    part_ii = _scope(payload, "ii")
    part_ii["facts"] = [
        item for item in part_ii["facts"] if item["kind"] != "minimum_target"
    ]
    expected = ProblemDraft.create(gold)

    result = ProblemDomainCanonicalizer().canonicalize(ProblemDraft.create(payload))

    assert result.draft.semantic_hash == expected.semantic_hash
    assert any(
        item.code == "materialize_shared_minimum_target"
        for item in result.actions
    )
    validation = ProblemDomainValidator().validate(result.draft)
    assert validation.report.ok, validation.report.to_payload()
