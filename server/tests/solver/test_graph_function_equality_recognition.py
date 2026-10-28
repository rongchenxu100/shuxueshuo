"""Constructed Q20 source/feature/recognition/reading tests, not photo evidence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.graph_lesson.stage_two.contracts import validate_input
from shuxueshuo_server.graph_lesson.stage_two.fragments import build_d1
from shuxueshuo_server.graph_lesson.stage_two.recognition import (
    derive_knowledge,
    evaluate_types,
)
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.search.lesson import present_lesson
from tests.solver.test_graph_stage_two_input_values import accepted

FIXTURE = Path(__file__).parent / "fixtures/function-equality/q20-candidate.json"


def candidate():
    return json.loads(FIXTURE.read_text())


def envelope(value=None):
    value = candidate() if value is None else value
    features = extract_features(value)
    assert features["ok"], features
    # A structural fixture in the existing accepted envelope, not a new
    # source-reviewed/live provider run.
    output = accepted()
    output.update(candidate=value, features=features["features"])
    return output


def feature(value, name):
    return next(row for row in value["features"] if row["feature_id"] == name)


def test_q20_stage_one_to_stage_two_without_scalar_goal_symbol(tmp_path):
    value = envelope()
    assert "symbol" not in feature(value, "goal")["value"]
    checked = validate_input(value)
    assert checked["ok"], checked
    result = run_result(value, tmp_path / "q20", verify=True)
    assert result["status"] == "completed"
    goal = result["goals"][0]
    assert goal["primary"] == "type-function-equality"
    assert goal["primary_source"] == "program"
    assert goal["supported"] == ["type-function-equality"]
    assert result["llm"]["new_semantic_calls"] == 0
    assert not goal["d1"]["diagnostics"]
    assert [row["text"] for row in goal["d1"]["fragments"]] == ["表示同一个函数"]


def test_comparison_reading_and_initial_workspaces_do_not_reveal_verdicts(tmp_path):
    value = envelope()
    result = run_result(value, tmp_path / "q20")
    section = present_lesson(result, value["features"], value["candidate"]["original_text"],
                             candidate=value["candidate"])["goals"][0]
    assert section["d1"]["interaction"] == "choice"
    assert len(section["d1"]["rows"]) == 1
    assert next(option for option in section["d1"]["rows"][0]["options"] if option["correct"])["text"] == "逐项判断，再选出表示相同函数的选项"
    bundle = section["walk"]["bundle"]
    assert [row["option_id"] for row in bundle["option_workspaces"]] == ["A", "B", "C", "D"]
    assert all(set(row) == {"option_id", "label", "text"} for row in bundle["option_workspaces"])
    assert bundle["intro"][0]["feedback"]["answer"] == section["d1"]["feedback"]
    assert "输入还是输出" not in bundle["intro"][0]["feedback"]["answer"]
    assert not any(key in json.dumps(bundle["option_workspaces"]) for key in ("correct_labels", "verdict", "relation"))


@pytest.mark.parametrize("wording", ["表示不同函数", "不表示同一个函数", "不是同一函数"])
def test_different_polarity_is_read_from_goal_not_q20_answer(tmp_path, wording):
    c = candidate()
    c["root"]["goals"][0]["select_relation"] = "different"
    c["original_text"] = c["original_text"].replace("表示同一个函数", wording)
    value = envelope(c)
    result = run_result(value, tmp_path / "different")
    section = present_lesson(result, value["features"], c["original_text"], candidate=c)["goals"][0]
    correct = next(option for option in section["d1"]["rows"][0]["options"] if option["correct"])
    assert correct["text"] == "逐项判断，再选出表示不相同函数的选项"
    assert result["goals"][0]["d1"]["fragments"][0]["text"] == wording


def test_direct_pair_has_no_fabricated_selection_polarity(tmp_path):
    c = candidate()
    goal = c["root"]["goals"][0]
    goal.update(mode="pair", select_relation=None, selection_mode="none", options=goal["options"][:1])
    c["original_text"] = "判断两个函数是否表示同一函数：$f(x)=x$，$g(x)=(\\sqrt{x})^2$"
    value = envelope(c)
    assert validate_input(value)["ok"]
    result = run_result(value, tmp_path / "pair")
    section = present_lesson(result, value["features"], c["original_text"], candidate=c)["goals"][0]
    assert section["d1"]["question"] == "题目要求我们判断什么？"
    assert "判断是否为同一函数" in next(option["text"] for option in section["d1"]["rows"][0]["options"] if option["correct"])


@pytest.mark.parametrize("change", [
    lambda goal: goal.update(completeness="incomplete"),
    lambda goal: goal.update(select_relation="unknown"),
    lambda goal: goal["options"][0]["functions"][0].update(definition="f(x)=abs(x^2)"),
])
def test_unresolved_input_never_becomes_supported_t1(change):
    c = candidate()
    change(c["root"]["goals"][0])
    value = envelope(c)
    checked = validate_input(value)
    assert checked["ok"], checked
    report = next(row for row in evaluate_types(value["features"]) if row["type_id"] == "type-function-equality")
    assert report["status"] == "conflict"
    assert derive_knowledge(value["features"])["items"] == []


@pytest.mark.parametrize("change", [
    lambda value: value.pop("options"),
    lambda value: value.update(structure_supported="true"),
    lambda value: value.update(unregistered=True),
    lambda value: value["options"][0].pop("left"),
    lambda value: value["options"][0]["left"].pop("expression_ast"),
    lambda value: value["options"][0]["right"].update(explicit_domain=1),
    lambda value: value["options"][0]["right"].update(expression_ast="abs(x)"),
])
def test_corrupt_comparison_feature_shapes_fail_before_recognition(change):
    value = envelope()
    change(feature(value, "function_comparison")["value"])
    checked = validate_input(value)
    assert not checked["ok"]
    assert any(row["code"] == "input.feature_value" for row in checked["diagnostics"])


def test_comparison_feature_is_required_and_scalar_symbol_forbidden():
    value = envelope()
    feature(value, "goal")["value"]["symbol"] = "x"
    assert not validate_input(value)["ok"]
    value = envelope()
    value["features"] = [row for row in value["features"] if row["feature_id"] != "function_comparison"]
    assert any(row["code"] == "input.features_incomplete" and "function_comparison" in row["message"]
               for row in validate_input(value)["diagnostics"])


def test_d1_never_reads_repeated_option_function_names_as_shared_definitions():
    value = envelope()
    frozen = deepcopy(value["candidate"])
    knowledge = derive_knowledge(value["features"])
    d1 = build_d1(value["candidate"], "/root/goals/0", value["features"], knowledge)
    assert not d1["diagnostics"]
    assert all(fragment["fragment_kind"] == "goal" for fragment in d1["fragments"])
    assert {ref for fragment in d1["fragments"] for ref in fragment["knowledge_refs"]} == {"function-concept#identity", "function-concept#elements"}
    assert value["candidate"] == frozen
