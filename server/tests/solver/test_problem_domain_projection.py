from __future__ import annotations

import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.problem_domain import (
    ProblemDraft,
    ProblemPromotionService,
    VerifiedProblem,
)
from shuxueshuo_server.solver.extraction.problem_domain_projection import (
    ProblemDomainProjector,
)
from shuxueshuo_server.solver.extraction.problem_domain_validation import (
    ProblemDomainValidator,
)
from shuxueshuo_server.solver.extraction.semantic_diff import (
    compare_solver_projection_semantics,
)
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from test_problem_domain_schema import _payload


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_FIXTURES = ROOT / "internal/problem-domain-fixtures"
SOLVER_FIXTURES = ROOT / "internal/solver-fixtures"
CASES = (
    "tj-2026-nankai-yimo-25",
    "tj-2026-heping-ermo-25",
    "tj-2026-xiqing-yimo-25",
    "tj-2026-hexi-yimo-25",
    "tj-2026-heping-yimo-25",
)


def _validated(case: str):
    payload = json.loads(
        (DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )
    result = ProblemDomainValidator().validate(ProblemDraft.create(payload))
    assert result.report.ok, result.report.to_payload()
    return result


def _rename_scope_ids(scope: dict, *, local_id: str = "root") -> None:
    scope["id"] = local_id
    for position, child in enumerate(scope["children"], start=1):
        _rename_scope_ids(child, local_id=f"{local_id}_part{position}")


def _rename_goal_answer_keys(scope: dict, *, prefix: str = "answer") -> None:
    for position, goal in enumerate(scope["goals"], start=1):
        goal["answer_key"] = f"{prefix}_{position}"
    for position, child in enumerate(scope["children"], start=1):
        _rename_goal_answer_keys(child, prefix=f"{prefix}_{position}")


@pytest.mark.parametrize("case", CASES)
def test_verified_domain_projects_to_constructible_solver_problem(case: str) -> None:
    validation = _validated(case)
    verified = ProblemPromotionService().promote(validation.draft)

    projection = ProblemDomainProjector().project(verified)
    expected = json.loads(
        (SOLVER_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )["input"]

    assert projection.canonical_input["problem_id"] == expected["problem_id"]
    assert projection.canonical_input["pattern"] == expected["pattern"]
    assert projection.canonical_input["problem_type"] == expected["problem_type"]
    assert projection.canonical_input["original_text"]["number"] == validation.draft.graph.source.question_number
    assert projection.canonical_input["original_text"]["lines"] == list(
        validation.draft.graph.original_text_lines
    )
    assert ContextBuilder().build(projection.problem) is not None
    assert VerifiedProblem.from_payload(verified.to_payload()).to_payload() == verified.to_payload()


@pytest.mark.parametrize("case", CASES)
def test_runtime_scope_identity_does_not_depend_on_model_local_scope_ids(
    case: str,
) -> None:
    expected = _validated(case)
    payload = json.loads(
        (DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )
    _rename_scope_ids(payload["root"])

    actual = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert actual.report.ok, actual.report.to_payload()
    assert expected.projection is not None and actual.projection is not None
    assert actual.projection.canonical_input == expected.projection.canonical_input


@pytest.mark.parametrize("case", CASES)
def test_runtime_answer_identity_is_derived_from_goal_semantics(case: str) -> None:
    expected = _validated(case)
    payload = json.loads(
        (DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )
    _rename_goal_answer_keys(payload["root"])

    actual = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert actual.report.ok, actual.report.to_payload()
    assert expected.projection is not None and actual.projection is not None
    assert actual.projection.canonical_input == expected.projection.canonical_input


def test_primary_parameter_in_function_projects_as_quadratic_coefficient() -> None:
    case = "tj-2026-heping-yimo-25"
    expected = _validated(case)
    payload = json.loads(
        (DOMAIN_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )
    parameter = next(
        entity for entity in payload["root"]["entities"] if entity["id"] == "a"
    )
    parameter["role"] = "primary_parameter"

    actual = ProblemDomainValidator().validate(ProblemDraft.create(payload))

    assert actual.report.ok, actual.report.to_payload()
    assert expected.projection is not None and actual.projection is not None
    assert actual.projection.canonical_input == expected.projection.canonical_input
    runtime_context = ContextBuilder().build(actual.projection.problem)
    coefficients = runtime_context.read_path(
        "$problem.symbol_lists.quadratic_coefficients",
        from_scope_id="problem",
    ).value
    assert [symbol.name for symbol in coefficients] == ["a", "b"]


@pytest.mark.parametrize("case", CASES)
def test_every_projected_runtime_node_has_source_unit_provenance(case: str) -> None:
    projection = _validated(case).projection
    assert projection is not None
    sources = projection.manifest.runtime_node_sources

    for collection in ("entities", "facts", "question_goals"):
        for item in projection.canonical_input[collection]:
            assert item["handle"] in sources
            assert sources[item["handle"]]
    assert all(projection.manifest.value_object_sources.values())


@pytest.mark.parametrize("case", CASES)
def test_domain_projection_is_semantically_equivalent_to_existing_solver_gold(
    case: str,
) -> None:
    projection = _validated(case).projection
    assert projection is not None
    expected = json.loads(
        (SOLVER_FIXTURES / f"{case}.json").read_text(encoding="utf-8")
    )["input"]

    report = compare_solver_projection_semantics(
        expected,
        projection.canonical_input,
    )

    assert report.ok, report.to_payload()


def test_equivalent_curve_point_and_intercept_authoring_have_one_semantic_view() -> None:
    expected_payload = json.loads(
        (DOMAIN_FIXTURES / "tj-2026-heping-yimo-25.json").read_text(
            encoding="utf-8"
        )
    )
    variant_payload = json.loads(json.dumps(expected_payload, ensure_ascii=False))
    root = variant_payload["root"]
    point_on_curve_a = next(
        fact
        for fact in root["facts"]
        if fact["kind"] == "point_on_curve" and fact["point"] == "A"
    )
    root["facts"].remove(point_on_curve_a)
    root["facts"].append(
        {
            "kind": "point_construction",
            "point": "A",
            "construction": "x_axis_intercept",
            "owner": "parabola",
        }
    )
    part_i = next(item for item in root["children"] if item["id"] == "i")
    part_i_2 = next(item for item in part_i["children"] if item["id"] == "i_2")
    curve_with_x = next(
        fact for fact in part_i_2["facts"] if fact["kind"] == "point_on_curve_with_x"
    )
    part_i_2["facts"].remove(curve_with_x)
    part_i_2["facts"].append(
        {
            "kind": "point_construction",
            "point": "E",
            "construction": "curve_at_x",
            "owner": "parabola",
            "x_expression": "m",
        }
    )

    expected = ProblemDomainValidator().validate(
        ProblemDraft.create(expected_payload)
    )
    variant = ProblemDomainValidator().validate(
        ProblemDraft.create(variant_payload)
    )

    assert expected.report.ok and variant.report.ok
    assert expected.draft.graph.semantic_hash == variant.draft.graph.semantic_hash
    assert expected.projection is not None and variant.projection is not None
    report = compare_solver_projection_semantics(
        expected.projection.canonical_input,
        variant.projection.canonical_input,
    )
    assert report.ok, report.to_payload()


def test_ancestor_value_object_is_reused_without_sibling_identity_leakage() -> None:
    projection = _validated("tj-2026-heping-ermo-25").projection
    assert projection is not None
    segments = [
        item
        for item in projection.canonical_input["entities"]
        if item["entity_type"] == "segment" and item["name"] == "AE"
    ]

    assert {item["scope_id"] for item in segments} == {"problem"}
    assert len({item["handle"] for item in segments}) == 1


def test_family_source_goal_contract_derives_point_list_from_visible_square() -> None:
    projection = _validated("tj-2026-heping-ermo-25").projection
    assert projection is not None
    goals = {
        (item["scope_id"], item["answer_key"]): item["value_type"]
        for item in projection.canonical_input["question_goals"]
    }

    assert goals[("i_2", "E")] == "PointList"
    assert goals[("ii", "E")] == "Point"


def test_curve_at_x_projects_an_explicit_point_on_curve_fact() -> None:
    projection = _validated("tj-2026-hexi-yimo-25").projection
    assert projection is not None
    point_m = next(
        item
        for item in projection.canonical_input["entities"]
        if item.get("entity_type") == "point"
        and item.get("scope_id") == "iii"
        and item.get("name") == "M"
    )

    assert any(
        fact.get("type") == "point_on_curve"
        and fact.get("point") == point_m["handle"]
        for fact in projection.canonical_input["facts"]
    )


def test_square_center_can_reference_square_fact_from_ancestor_scope() -> None:
    payload = _payload()
    next(item for item in payload["root"]["entities"] if item["id"] == "A")[
        "label"
    ] = "点A"
    payload["root"]["entities"].append(
        {"id": "b", "kind": "symbol", "label": "b", "role": "quadratic_coefficient"}
    )
    payload["root"]["entities"].extend(
        {"id": name, "kind": "point", "label": f"点{name}"}
        for name in ("B", "C", "D")
    )
    payload["root"]["entities"].append(
        {
            "id": "square_ABCD",
            "kind": "polygon",
            "label": "ABCD",
            "vertices": ["A", "B", "C", "D"],
        }
    )
    payload["root"]["facts"].append(
        {
            "kind": "square",
            "polygon": "square_ABCD",
            "side": {"start": "A", "end": "B"},
            "orientation": {
                "point": "D",
                "relation": "below_x_axis",
            },
        }
    )
    child = payload["root"]["children"][0]
    child["entities"].append({"id": "K", "kind": "point", "label": "点K"})
    child["facts"].append(
        {"kind": "square_center", "point": "K", "square": "square_ABCD"}
    )

    draft = ProblemDraft.create(payload)
    projection = ProblemDomainProjector().project_graph(draft.graph)

    center = next(
        item
        for item in projection.canonical_input["facts"]
        if item["type"] == "square_center"
    )
    assert center["square"].startswith("fact:problem:")
    assert any(
        item["entity_type"] == "segment" and item["name"] == "AB"
        for item in projection.canonical_input["entities"]
    )
