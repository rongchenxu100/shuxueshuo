"""The real photo transcription reaches bounded recognition and shared reading."""

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.search import walk
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import present_lesson, run_stage_two
from tests.search.function_domain_recording import revalidate_recording


def test_photo_recording_revalidates_and_builds_domain_reading(tmp_path):
    result = revalidate_recording()
    candidate = result["candidate"]
    assert candidate["root"]["facts"] == []
    assert candidate["root"]["goals"] == [{"kind": "find_domain", "object": "f"}]
    assert "定义域" in build_identity(result)["statement"]

    def forbidden():
        raise AssertionError("the uniquely supported type must not need an LLM")

    stage_two = run_stage_two(tmp_path, result, provider=forbidden,
                              unsupported_root=tmp_path / "unsupported")
    # The generic polynomial reader rejects \frac, while the domain-specific
    # original-tree matcher has positively located this exact valid formula.
    assert any(item["code"] == "d1.unsupported_surface_command"
               for item in stage_two["goals"][0]["d1"]["diagnostics"])
    lesson = present_lesson(stage_two, result["features"], candidate["original_text"],
                            "function-concepts-q15", candidate=candidate)
    (goal,) = lesson["goals"]
    assert goal["status"] == "resolved"
    assert goal["primary"] == "type-function-domain"
    assert [row["kind"] for row in goal["d1"]["rows"]] == ["goal"]
    assert goal["d1"]["summary"] == "定义域是自变量的取值集合。本题需要找出所有使原解析式有意义的 $x$。"
    for row in goal["d1"]["rows"]:
        assert sum(option["correct"] for option in row["options"]) == 1
        assert row["knowledge_refs"] and row["fragment_ids"]
        assert all(option["feedback"] for option in row["options"] if not option["correct"])
    (given,) = goal["d1"]["givens"]
    assert given["kind"] == "expression" and "options" not in given
    assert given["source_ref"] == "/root/definitions/0"
    assert {"square-root-expression#meaning", "rational-expression#meaning"} <= set(given["knowledge_refs"])
    for quote in given["quote"]:
        # Presentation adds complete math delimiters without moving the bound source span.
        assert candidate["original_text"][quote["start"]:quote["end"]].strip("$") == quote["text"].strip("$")
    assert_domain_choice(goal, "x", "f")
    bundle = goal["walk"]["bundle"]
    assert bundle["problem"]["givens"] == goal["d1"]["givens"]
    assert bundle["problem"]["text"] == candidate["original_text"]
    clues = {"function-concept", "square-root-expression", "rational-expression"}
    assert set(bundle["intro"][0]["effects"]["nodes"]) == clues
    assert {f"type-function-domain|involves|{node}" for node in clues} <= {
        edge["id"] for edge in bundle["graph"]["edges"]}
    assert [step["id"] for step in bundle["intro"]] == ["D1", "D2"]
    assert not any(stage_two["llm"].values())


def assert_domain_choice(goal, variable, function):
    (row,) = goal["d1"]["rows"]
    assert {option["text"] for option in row["options"]} == {
        f"自变量 ${variable}$ 的取值范围", f"函数值 ${function}({variable})$ 的取值范围"}
    right = next(option["id"] for option in row["options"] if option["correct"])
    d1 = goal["walk"]["bundle"]["intro"][0]
    given_texts = [item["text"] for item in goal["d1"]["givens"] if item.get("text")]
    assert d1["question"] == "\n\n".join([*given_texts, "题目要求“定义域”，也就是要确定什么？"])
    assert d1["interaction"]["type"] == "choice" and d1["interaction"]["field"] == "reading"
    assert "slots" not in d1["interaction"]
    assert d1["expected_answer"] == {"one_of": [right]}
    wrong = next(option for option in d1["interaction"]["options"] if option["value"] != right)
    assert "值域" in wrong["feedback"] and "定义域是自变量" in wrong["feedback"]
    assert d1["effects"]["results"] == [goal["d1"]["summary"]]
    action = goal["walk"]["replay"]["actions"][0]
    assert action == {"decision": "D1", "answer": right, "reason": goal["d1"]["summary"]}
    assert isinstance(action["answer"], str)


def domain_lesson(tmp_path, candidate):
    features = extract_features(candidate)
    assert features["ok"], features
    result = {"status": "reviewed_candidate", "source_reviewed": True, "candidate": candidate,
              "features": features["features"], "features_ok": True}

    def forbidden():
        raise AssertionError("a supported concrete domain requires no LLM selection")

    stage_two = run_stage_two(tmp_path, result, provider=forbidden, unsupported_root=tmp_path / "unsupported")
    lesson = present_lesson(stage_two, features["features"], candidate["original_text"], candidate=candidate)
    (goal,) = lesson["goals"]
    return goal


@pytest.mark.parametrize("variable,function", [("t", "g"), ("u", "h")])
def test_single_domain_choice_uses_canonical_function_and_variable(tmp_path, variable, function):
    expression = f"{function}({variable})=sqrt({variable}-1)/({variable}-2)"
    value = {"original_text": f"求函数 ${expression}$ 的定义域。",
             "root": {"definitions": [expression], "goals": [{"kind": "find_domain", "object": function}]}}
    goal = domain_lesson(tmp_path, value)
    assert_domain_choice(goal, variable, function)
    assert goal["d1"]["summary"].endswith(f"${variable}$。")
    assert "$x$" not in goal["d1"]["summary"]


@pytest.mark.parametrize("input_domain", ["[0,1]", "(-∞,3]", "ℝ"])
def test_explicit_range_is_given_information_not_an_extra_question(tmp_path, input_domain):
    value = {"original_text": f"已知 $t∈{input_domain}$，求函数 $g(t)=sqrt(t-1)/(t-2)$ 的定义域。",
             "root": {"definitions": ["g(t)=sqrt(t-1)/(t-2)"],
                      "goals": [{"kind": "find_domain", "object": "g", "input_domain": input_domain}]}}
    goal = domain_lesson(tmp_path, value)
    assert_domain_choice(goal, "t", "g")
    assert len(goal["d1"]["rows"]) == 1
    givens = {item["kind"]: item for item in goal["d1"]["givens"]}
    assert set(givens) == {"expression", "given_domain"}
    given = givens["given_domain"]
    assert given["source_ref"] == "/root/goals/0/input_domain"
    assert given["source_refs"] == ["/root/goals/0/input_domain"]
    assert given["text"].startswith(r"题设输入范围：$t\in ")
    assert given["text"] in goal["walk"]["bundle"]["intro"][0]["question"]
    assert "options" not in given and given["input_domain_ast"]
    assert goal["d1"]["summary"].endswith("题设另给的输入范围也要同时满足。")
    assert goal["walk"]["bundle"]["problem"]["text"] == value["original_text"]
    assert [step["id"] for step in goal["walk"]["bundle"]["intro"]] == ["D1", "D2"]


@pytest.mark.parametrize("source", [
    r"求函数 $f(x)=\frac{\sqrt{x-1}}{x-3}$ 的定义域。",
    r"求函数 $f(x)=\frac{\sqrt{x-1}}{x-2}$ 的定义域。另有 $f(x)=x-1$。",
    r"求函数 $f(x)=\unknown{\frac{\sqrt{x-1}}{x-2}}$ 的定义域。",
])
def test_display_only_expression_still_requires_original_source_binding(tmp_path, source):
    value = {"original_text": source,
             "root": {"definitions": ["f(x)=sqrt(x-1)/(x-2)"], "goals": [{"kind": "find_domain", "object": "f"}]}}
    goal = domain_lesson(tmp_path, value)
    assert [row["kind"] for row in goal["d1"]["rows"]] == ["goal"]
    assert goal["d1"]["givens"] == []
    assert any(item["code"] == "d1.function_definition_not_uniquely_located" for item in goal["d1"]["diagnostics"])
    assert goal["walk"] is None


def test_direct_method_is_in_walk_without_a_judgment_node(monkeypatch):
    nodes = [{"id": "type-domain", "kind": "problem_type"},
             {"id": "method-domain", "kind": "method"},
             {"id": "domain-meaning", "kind": "knowledge"}]
    edges = [{"id": "type-domain|candidate|method-domain", "from": "type-domain",
              "to": "method-domain", "type": "candidate"},
             {"id": "type-domain|involves|domain-meaning", "from": "type-domain",
              "to": "domain-meaning", "type": "involves"}]
    monkeypatch.setattr(walk, "_graph", lambda: {"nodes": {n["id"]: n for n in nodes},
                                                "edges": {e["id"]: e for e in edges}})
    graph, _, _ = walk.subgraph(["domain-meaning"], ["type-domain"], "type-domain")
    assert {node["id"] for node in graph["nodes"]} == {node["id"] for node in nodes}
    assert not any(node["kind"] == "judgment_rule" for node in graph["nodes"])
    assert any(edge["type"] == "candidate" for edge in graph["edges"])
