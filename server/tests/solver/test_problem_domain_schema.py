from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from shuxueshuo_server.solver.extraction.problem_domain import (
    PROBLEM_DOMAIN_CONTRACT,
    PROBLEM_DOMAIN_MAX_FACTS_PER_SCOPE,
    PROBLEM_DOMAIN_MAX_SOURCE_LINES_PER_SCOPE,
    PROBLEM_DOMAIN_MAX_TEXT_LENGTH,
    ProblemDomainError,
    ProblemDraft,
    problem_domain_schema,
    problem_repair_schema,
)


ROOT = Path(__file__).resolve().parents[3]


def _payload() -> dict:
    return {
        "schema_version": PROBLEM_DOMAIN_CONTRACT,
        "problem_id": "synthetic-domain",
        "family_id": "QuadraticPathMinimumSolver",
        "source": {"question_number": "25", "score": "12"},
        "root": {
            "id": "problem",
            "label": "整题",
            "source_text": ["已知抛物线 y=ax^2+bx+c。"],
            "entities": [
                {"id": "x", "kind": "symbol", "label": "x", "role": "function_variable"},
                {"id": "a", "kind": "symbol", "label": "a", "role": "quadratic_coefficient"},
                {"id": "parabola", "kind": "quadratic_function", "label": "抛物线"},
                {"id": "A", "kind": "point", "label": "A"},
            ],
            "facts": [
                {
                    "kind": "function_expression",
                    "function": "parabola",
                    "variable": "x",
                    "expression": "a*x**2+b*x",
                },
                {"kind": "point_on_curve", "point": "A", "curve": "parabola"},
            ],
            "goals": [],
            "children": [
                {
                    "id": "i",
                    "label": "第（Ⅰ）问",
                    "source_text": ["求点 A 的坐标。"],
                    "entities": [],
                    "facts": [],
                    "goals": [
                        {"kind": "point_coordinate", "answer_key": "A", "target": "A"}
                    ],
                    "children": [],
                }
            ],
        },
    }


def test_problem_domain_schema_is_compact_and_round_trips() -> None:
    draft = ProblemDraft.create(_payload())

    assert draft.graph.wire_payload() == _payload()
    assert ProblemDraft.from_payload(draft.to_payload()).to_payload() == draft.to_payload()
    compact_schema = json.dumps(
        problem_domain_schema(), ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert len(compact_schema) <= 20_000


@pytest.mark.parametrize(
    ("filename", "runtime_schema"),
    (
        ("problem-domain.schema.json", problem_domain_schema),
        ("problem-repair.schema.json", problem_repair_schema),
    ),
)
def test_checked_in_schema_snapshot_matches_runtime_authority(
    filename,
    runtime_schema,
) -> None:
    checked_in = json.loads(
        (ROOT / "internal/schemas" / filename).read_text(encoding="utf-8")
    )

    assert checked_in == runtime_schema(), (
        f"{filename} drifted; run server/tools/sync_problem_domain_schemas.py"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("pattern", "path-minimum"),
        ("problem_type", "quadratic_path_minimum"),
        ("scope_id", "problem"),
        ("valid_scope", "problem"),
        ("handle", "point:problem:A"),
    ),
)
def test_problem_domain_wire_rejects_runtime_and_flat_scope_fields(field, value) -> None:
    payload = _payload()
    payload["root"][field] = value

    with pytest.raises(ProblemDomainError) as error:
        ProblemDraft.create(payload)

    assert error.value.code == "extraction.problem_domain_schema_invalid"


def test_fact_and_goal_ids_are_not_model_fields() -> None:
    payload = _payload()
    payload["root"]["facts"][0]["id"] = "fact_1"
    with pytest.raises(ProblemDomainError):
        ProblemDraft.create(payload)

    payload = _payload()
    payload["root"]["children"][0]["goals"][0]["id"] = "goal_1"
    with pytest.raises(ProblemDomainError):
        ProblemDraft.create(payload)


def test_control_characters_fail_at_wire_boundary() -> None:
    payload = _payload()
    payload["root"]["source_text"][0] += "\x08"
    with pytest.raises(ProblemDomainError):
        ProblemDraft.create(payload)


def test_square_orientation_requires_typed_axis_placement() -> None:
    payload = json.loads(
        (
            ROOT
            / "internal/problem-domain-fixtures"
            / "tj-2026-heping-ermo-25.json"
        ).read_text(encoding="utf-8")
    )
    square = next(
        fact for fact in payload["root"]["facts"] if fact["kind"] == "square"
    )
    square["orientation"] = "G在x轴下方"

    with pytest.raises(ProblemDomainError) as error:
        ProblemDraft.create(payload)

    assert error.value.code == "extraction.problem_domain_schema_invalid"


def test_discriminated_union_reports_missing_polygon_vertices() -> None:
    payload = json.loads(
        (
            ROOT
            / "internal/problem-domain-fixtures"
            / "tj-2026-heping-ermo-25.json"
        ).read_text(encoding="utf-8")
    )
    polygon = next(
        entity
        for entity in payload["root"]["entities"]
        if entity["kind"] == "polygon"
    )
    del polygon["vertices"]

    with pytest.raises(ProblemDomainError) as error:
        ProblemDraft.create(payload)

    assert error.value.code == "extraction.problem_domain_schema_invalid"
    assert error.value.path.startswith("$.root.entities[")
    assert "'vertices' is a required property" in error.value.message


@pytest.mark.parametrize(
    ("path", "mutate"),
    (
        (
            "source_text",
            lambda root: root.__setitem__(
                "source_text",
                ["题面"] * (PROBLEM_DOMAIN_MAX_SOURCE_LINES_PER_SCOPE + 1),
            ),
        ),
        (
            "facts",
            lambda root: root.__setitem__(
                "facts",
                [deepcopy(root["facts"][0])]
                * (PROBLEM_DOMAIN_MAX_FACTS_PER_SCOPE + 1),
            ),
        ),
        (
            "text_length",
            lambda root: root.__setitem__(
                "label", "题" * (PROBLEM_DOMAIN_MAX_TEXT_LENGTH + 1)
            ),
        ),
    ),
)
def test_problem_domain_wire_rejects_unbounded_provider_output(
    path: str,
    mutate,
) -> None:
    payload = _payload()
    mutate(payload["root"])

    with pytest.raises(ProblemDomainError) as error:
        ProblemDraft.create(payload)

    assert error.value.code == "extraction.problem_domain_schema_invalid", path


def test_wrong_contract_or_unknown_family_fails_schema() -> None:
    payload = _payload()
    payload["schema_version"] = "problem-ir-authoring/v2"
    with pytest.raises(ProblemDomainError):
        ProblemDraft.create(payload)

    payload = _payload()
    payload["family_id"] = "ImaginaryFamily"
    with pytest.raises(ProblemDomainError):
        ProblemDraft.create(payload)


def test_duplicate_fact_is_deterministically_deduplicated() -> None:
    payload = _payload()
    payload["root"]["facts"].append(deepcopy(payload["root"]["facts"][0]))
    draft = ProblemDraft.create(payload)

    assert len(draft.graph.root_scope.facts) == 2
    assert len(draft.graph.wire_payload()["root"]["facts"]) == 2


def test_discussed_quadratic_example_is_a_stable_nested_domain_fixture() -> None:
    path = (
        ROOT
        / "internal/problem-domain-fixtures"
        / "synthetic-discussed-quadratic-minimum-25.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    draft = ProblemDraft.create(payload)
    goal_count = sum(
        len(scope.goals) for scope in draft.graph.root_scope.iter_scopes()
    )

    assert draft.graph.problem_id == "synthetic-discussed-quadratic-minimum-25"
    assert draft.graph.source.score == "12"
    assert goal_count == 6
    assert ProblemDraft.from_payload(draft.to_payload()).to_payload() == draft.to_payload()
