import json
import re
from pathlib import Path

import pytest

FIXTURES = [
    Path("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"),
    Path("../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"),
    Path("../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"),
]

QUADRATIC_PATH_FIXTURES = [
    Path("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"),
    Path("../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"),
]
WEIGHTED_PATH_FIXTURE = Path("../internal/solver-fixtures/tj-2026-hexi-yimo-25.json")


@pytest.mark.parametrize("fixture_path", FIXTURES)
def test_solver_fixture_keeps_problem_input_separate_from_expected_answers(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["$schema"] == "../schemas/solver-problem-ir.schema.json"
    assert "input" in fixture
    assert "expected" not in fixture
    assert "expected_answers" not in fixture
    assert_no_chinese_keys(fixture)

    data = fixture["input"]["data"]
    original_text = fixture["input"]["original_text"]

    assert original_text["number"] == "25"
    assert len(original_text["lines"]) >= 4
    assert fixture["input"]["symbol_roles"]["x"] == "function_variable"

    assert "solver_config" not in data

    serialized_data = json.dumps(data, ensure_ascii=False)
    assert "right_angle_equal_length_point" not in serialized_data
    assert "D_prime" not in serialized_data
    assert "T_prime" not in serialized_data
    assert "minimum_segment" not in serialized_data
    assert "method_plan" not in serialized_data
    assert "horse-drinking" not in serialized_data


@pytest.mark.parametrize("fixture_path", QUADRATIC_PATH_FIXTURES)
def test_quadratic_path_fixtures_use_path_problem_instead_of_solver_config(fixture_path: Path) -> None:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    data = fixture["input"]["data"]
    path_problem = data["path_problem"]

    assert fixture["input"]["symbol_roles"]["m"] == "dynamic_parameter"
    assert "solver_config" not in fixture["input"]
    assert path_problem["type"] == "two_moving_points_path_minimum"
    assert path_problem["scope"] in {"ii", "b"}
    assert path_problem["path"] in {"EG+FG", "PR+WR"}
    assert "minimum_segment" not in path_problem
    assert "intersection_lines" not in path_problem
    assert "auxiliary_points" not in path_problem


def test_weighted_path_fixture_uses_path_problem_instead_of_solver_config() -> None:
    fixture = json.loads(WEIGHTED_PATH_FIXTURE.read_text(encoding="utf-8"))
    path_problem = fixture["input"]["data"]["path_problem"]

    assert fixture["input"]["pattern"] == "weighted-path-minimum"
    assert fixture["input"]["problem_type"] == "quadratic_weighted_path_minimum"
    assert "solver_config" not in fixture["input"]
    assert path_problem == {
        "type": "weighted_path_minimum",
        "scope": "iii",
        "path": "sqrt(2)*MN+AN",
        "value": "21/4",
    }


def test_hexi_fixture_goals_only_include_problem_asks() -> None:
    """QuestionGoal 只表达题面最终作答目标，不收集中间推导量。"""
    fixture = json.loads(WEIGHTED_PATH_FIXTURE.read_text(encoding="utf-8"))
    questions = fixture["input"]["data"]["questions"]

    assert [
        (question["id"], [goal["answer_key"] for goal in question.get("goals", [])])
        for question in questions
    ] == [
        ("i", ["P"]),
        ("ii", ["D"]),
        ("iii", ["b"]),
    ]


def test_nankai_fixture_preserves_original_question_structure() -> None:
    fixture = json.loads(FIXTURES[0].read_text(encoding="utf-8"))
    data = fixture["input"]["data"]
    original_text = fixture["input"]["original_text"]
    question_i = next(question for question in data["questions"] if question["id"] == "i")
    question_ii = next(question for question in data["questions"] if question["id"] == "ii")

    assert "2a＋b＝0" in original_text["lines"][0]
    assert question_i["label"] == "第（Ⅰ）问"
    assert [child["id"] for child in question_ii["subquestions"]] == ["ii_1", "ii_2"]
    assert [goal["answer_key"] for goal in question_i["goals"]] == ["D", "parabola"]
    assert [goal["answer_key"] for goal in question_ii["subquestions"][0]["goals"]] == [
        "parabola",
        "min_value",
    ]


def test_nankai_fixture_uses_neutral_right_angle_relation() -> None:
    fixture = json.loads(FIXTURES[0].read_text(encoding="utf-8"))
    data = fixture["input"]["data"]

    assert data["entities"]["points"]["N"]["definition"] == "unknown"
    relation = next(
        item for item in data["relations"]
        if item["type"] == "right_angle_equal_length"
    )
    assert relation["angle"] == ["M", "D", "N"]
    assert relation["equal_segments"] == [["D", "M"], ["D", "N"]]


def assert_no_chinese_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert re.search(r"[\u4e00-\u9fff]", key) is None, f"Chinese key found: {key}"
            assert_no_chinese_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_chinese_keys(child)
