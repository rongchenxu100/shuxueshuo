import json
import re
from pathlib import Path

import pytest

from shuxueshuo_server.solver.fixtures import load_problem_ir
from shuxueshuo_server.solver.runtime.context import ContextBuilder
from shuxueshuo_server.solver.runtime.projection import problem_to_llm_payload

FIXTURES = [
    Path("../internal/solver-fixtures/tj-2026-nankai-yimo-25.json"),
    Path("../internal/solver-fixtures/tj-2026-nankai-yimo-25-alt-labels.json"),
    Path("../internal/solver-fixtures/tj-2026-hexi-yimo-25.json"),
    Path("../internal/solver-fixtures/tj-2026-heping-yimo-25.json"),
]
LEGACY_FIXTURES = FIXTURES[:-1]
CANONICAL_FIXTURE = Path("../internal/solver-fixtures/tj-2026-heping-yimo-25.json")

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

    original_text = fixture["input"]["original_text"]

    assert original_text["number"] == "25"
    assert len(original_text["lines"]) >= 4
    if "symbol_roles" in fixture["input"]:
        assert fixture["input"]["symbol_roles"]["x"] == "function_variable"

    assert "solver_config" not in fixture["input"]

    serialized_data = json.dumps(fixture["input"], ensure_ascii=False)
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


@pytest.mark.parametrize("fixture_path", LEGACY_FIXTURES)
def test_solver_fixtures_store_first_class_entities_and_facts(fixture_path: Path) -> None:
    """ProblemIR 必须显式保存 canonical Entity / Fact，而不是运行时临时推导。"""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    data = fixture["input"]["data"]
    entities = data["entities"]["items"]
    facts = data["facts"]

    entity_handles = [entity["handle"] for entity in entities]
    fact_handles = [fact["handle"] for fact in facts]

    assert entity_handles
    assert fact_handles
    assert len(entity_handles) == len(set(entity_handles))
    assert len(fact_handles) == len(set(fact_handles))
    assert all(re.match(r"^(point|line|segment|ray|function|symbol|angle|circle|polygon):", handle) for handle in entity_handles)
    assert all(handle.startswith("fact:") for handle in fact_handles)
    assert not any(handle.startswith(("value:", "relation:", "condition:", "constraint:")) for handle in entity_handles + fact_handles)

    for entity in entities:
        expected = f"{entity['entity_type']}:{entity['scope_id']}:{entity['name']}"
        assert entity["handle"] == expected
        assert entity["source"]
        assert entity["description"]

    for fact in facts:
        assert fact["handle"].startswith(f"fact:{fact['scope_id']}:")
        assert fact["valid_scope"]
        assert fact["source"]
        assert fact["description"]


@pytest.mark.parametrize("fixture_path", LEGACY_FIXTURES)
def test_legacy_point_index_also_carries_canonical_entity_metadata(fixture_path: Path) -> None:
    """保留给 ContextBuilder 的 points 索引也必须带 canonical 元数据。"""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    points = fixture["input"]["data"]["entities"]["points"]

    for point_name, point in points.items():
        assert point["handle"].endswith(f":{point_name}")
        assert point["entity_type"] == "point"
        assert point["scope_id"]
        assert point["source"] == "ProblemIR.data.entities.points"


def test_canonical_heping_fixture_has_single_problem_fact_source() -> None:
    """Canonical authored fixture 不再手写 runtime 兼容索引。"""
    fixture = json.loads(CANONICAL_FIXTURE.read_text(encoding="utf-8"))
    data = fixture["input"]

    assert set(data) == {
        "problem_id",
        "pattern",
        "problem_type",
        "original_text",
        "scopes",
        "entities",
        "facts",
        "question_goals",
    }
    serialized = json.dumps(data, ensure_ascii=False)
    assert '"data"' not in serialized
    assert '"target_path"' not in serialized
    assert '"relations"' not in serialized
    assert '"points"' not in serialized
    assert "$question" not in serialized
    assert "$subquestion" not in serialized


def test_canonical_heping_fixture_projects_to_runtime_and_llm_views() -> None:
    """同一 canonical fixture 能派生 runtime context 和 LLM payload。"""
    problem = load_problem_ir(CANONICAL_FIXTURE)
    context = ContextBuilder().build(problem)
    payload = problem_to_llm_payload(problem)

    assert "i_2" in context.scopes
    assert "B" in context.problem_scope.container("points")
    assert "D" in context.problem_scope.container("points")
    assert {goal["handle"] for goal in payload["question_goals"]} == {
        "answer:i_1_parabola",
        "answer:i_2_E",
        "answer:ii_a",
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "target_path" not in serialized
    assert "$question" not in serialized


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

    fact_handles = {fact["handle"] for fact in data["facts"]}
    entity_handles = {entity["handle"] for entity in data["entities"]["items"]}
    assert "point:ii:E" in entity_handles
    assert "point:ii:G" in entity_handles
    assert "fact:ii:right_angle_equal_length_MDN" in fact_handles
    assert "fact:ii:segment_E_on_DM" in fact_handles
    assert "fact:ii:segment_G_on_MN" in fact_handles


def assert_no_chinese_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert re.search(r"[\u4e00-\u9fff]", key) is None, f"Chinese key found: {key}"
            assert_no_chinese_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_chinese_keys(child)
