import json
import re
import time
from copy import deepcopy
from pathlib import Path

import pytest

from shuxueshuo_server.graph_lesson.stage_one.features import extract_features
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.lesson import (
    present_lesson,
    run_stage_two,
    stage_one_result,
    tex,
)
from tests.search.support import authenticated_client
from tests.search.test_identity import reviewed_result

RECORDED = Path(__file__).parents[1] / "solver/fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02"
PAGE = Path(__file__).parent / "fixtures/segment-pages/two-column"


def search_result(case):
    """What search/stage_one.py writes for a reviewed student upload of a recorded case."""
    value = json.loads((RECORDED / case / "sample-01/stage-one-result.json").read_text(encoding="utf-8"))
    return {"status": value["statuses"]["extraction"], "source_reviewed": True, "candidate": value["candidate"],
            "features": value["features"], "features_ok": value["statuses"]["features"]}


def lesson(case, tmp_path, result=None, provider=None):
    result = result or search_result(case)
    directory = tmp_path / case
    directory.mkdir()
    stage_two = run_stage_two(directory, result, provider=provider, unsupported_root=tmp_path / "unsupported")
    return present_lesson(stage_two, result["features"], result["candidate"]["original_text"],
                          candidate=result["candidate"])


def test_student_input_never_claims_gold_evaluation():
    statuses = stage_one_result(search_result("q04"), "abc")["statuses"]
    assert statuses["admission"] == "student_upload"
    assert "evaluation" not in statuses and "passed" not in statuses


def test_saved_plain_question_can_generate_and_retry_without_rewriting_recognition(tmp_path):
    result = search_result('q04')
    original = deepcopy(result)
    def no_selection():
        raise AssertionError('this recorded question has one supported type')
    for attempt in ('initial', 'retry'):
        output = run_stage_two(tmp_path / attempt, result, provider=no_selection,
                               unsupported_root=tmp_path / 'unsupported')
        assert output['status'] == 'completed', output['input_diagnostics']
        assert output['goals'][0]['primary'] == 'type-quantified-quadratic'
    assert result == original


@pytest.mark.parametrize("case", ["q02", "q03", "q04", "q05", "q06", "q07", "q08", "q09", "q10", "q11"])
def test_every_row_has_one_correct_reading_and_whole_formulas(case, tmp_path):
    for goal in lesson(case, tmp_path)["goals"]:
        if goal["status"] != "resolved":
            continue
        assert [row["kind"] for row in goal["d1"]["rows"]] == ["quantifier", "relation", "goal"]
        assert goal["d1"]["summary"].startswith("合起来：")
        for row in goal["d1"]["rows"]:
            assert sum(o["correct"] for o in row["options"]) == 1 and len(row["options"]) >= 2
            assert all(o["violates"] and o["feedback"] for o in row["options"] if not o["correct"])
            assert row["knowledge_refs"]
            for quote in row["quote"]:
                assert len(re.findall(r"(?<!\\)\$", quote["text"])) % 2 == 0, quote
        roles = {o["role"] for o in goal["d2"]}
        assert "primary" in roles
        primary = next(o for o in goal["d2"] if o["role"] == "primary")
        assert primary["type_id"] == goal["primary"] and primary["reasons"]


def correct(row):
    return next(o["text"] for o in row["options"] if o["correct"])


def test_variable_swap_reads_as_linear_in_the_quantified_variable(tmp_path):
    (goal,) = lesson("q08", tmp_path)["goals"]
    rows = {row["kind"]: row for row in goal["d1"]["rows"]}
    assert correct(rows["quantifier"]) == "$[1,3]$ 里的每一个 $m$ 都要满足"
    assert correct(rows["relation"]) == "关于 $m$ 是一次式，关于 $x$ 是二次式"
    assert correct(rows["goal"]) == "求 $x$ 能取哪些值"


@pytest.mark.parametrize(("kind", "noun"), [("find_minimum", "最小值"), ("find_maximum", "最大值")])
@pytest.mark.parametrize("request_verb", ["", "求"])
def test_parameter_extremum_keeps_the_requested_goal_in_reading_and_feedback(tmp_path, kind, noun, request_verb):
    sign = "+" if kind == "find_minimum" else "-"
    candidate = {
        "original_text": f"若不等式 $x^2{sign}ax+1≥0$ 对一切 $x∈(0,1/2]$ 恒成立，则{request_verb}实数 $a$ 的{noun}为 ______。",
        "root": {"facts": [f"∀x∈(0,1/2]: x^2{sign}a*x+1≥0"], "goals": [{"kind": kind, "expression": "a"}]},
    }
    extracted = extract_features(candidate)
    assert extracted["ok"], extracted["diagnostics"]
    result = {"status": "reviewed_candidate", "source_reviewed": True, "candidate": candidate,
              "features": extracted["features"], "features_ok": True}

    def no_selection():
        raise AssertionError("the uniquely supported quantified-quadratic type does not need an LLM")

    (goal,) = lesson("extremum", tmp_path, result=result, provider=no_selection)["goals"]
    assert goal["status"] == "resolved" and goal["primary"] == "type-quantified-quadratic"
    rows = {row["kind"]: row for row in goal["d1"]["rows"]}
    assert set(rows) == {"quantifier", "relation", "goal"}
    assert correct(rows["goal"]) == f"求参数 $a$ 的{noun}"
    assert rows["goal"]["quote"][0]["text"] == f"{request_verb}实数 $a$ 的{noun}"
    assert goal["d1"]["summary"].endswith(f"求参数 $a$ 的{noun}。")
    assert "取值范围" not in goal["d1"]["summary"]
    assert sum(option["correct"] for option in rows["goal"]["options"]) == 1
    for option in rows["goal"]["options"]:
        if not option["correct"]:
            assert option["violates"] == "goal" and f"$a$ 的{noun}" in option["feedback"]


def test_one_formula_holding_two_rows_quotes_each_part(tmp_path):
    (goal,) = lesson("q06", tmp_path)["goals"]
    quotes = [row["quote"][0]["text"] for row in goal["d1"]["rows"][:2]]
    assert quotes == ["$∀x<0$", "$x^2+ax+2≥0$"]


def test_existential_on_an_interval(tmp_path):
    (goal,) = lesson("q05", tmp_path)["goals"]
    row = goal["d1"]["rows"][0]
    assert correct(row) == "在 $(1,2)$ 里能找到一个 $x$ 满足就行"
    assert [q["text"] for q in row["quote"]] == ["$1<x<2$", "有解"]


def test_unsupported_part_has_no_reading_rows(tmp_path):
    first, second = lesson("q11", tmp_path)["goals"]
    assert first["status"] == "unsupported" and first["d1"]["rows"] == [] and "d2" not in first
    assert second["status"] == "resolved"


def test_rows_without_known_features_are_left_out(tmp_path):
    result = search_result("q04")
    for row in result["features"]:
        if row["feature_id"] == "domain":
            row.update(status="unknown", value=None, diagnostics=[{"code": "test.unknown"}])
    (goal,) = lesson("q04", tmp_path, result)["goals"]
    assert [row["kind"] for row in goal["d1"]["rows"]] == ["relation", "goal"]
    assert goal["d1"]["summary"] == ""


def test_failed_selection_is_reported_per_goal(tmp_path):
    def broken():
        raise RuntimeError("provider down")

    result = lesson("q01", tmp_path, provider=broken)
    assert result["status"] == "failed"
    assert [g["status"] for g in result["goals"]] == ["selection_failed"]
    assert result["goals"][0]["walk"] is None


@pytest.mark.parametrize("case", ["q02", "q04", "q05", "q06", "q10", "q11"])
def test_each_resolved_part_walks_its_own_rows_and_types(case, tmp_path):
    goals = lesson(case, tmp_path)["goals"]
    for goal in goals:
        walk = goal["walk"]
        if goal["status"] != "resolved":
            assert walk is None
            continue
        bundle, replay = walk["bundle"], walk["replay"]
        d1, d2 = bundle["intro"]
        assert d1["expected_answer"]["terms"] == [next(o["id"] for o in row["options"] if o["correct"])
                                                  for row in goal["d1"]["rows"]]
        assert [o["value"] for o in d2["interaction"]["options"]] == [o["type_id"] for o in goal["d2"]]
        assert d2["expected_answer"]["one_of"] == [goal["primary"]]
        assert {o["type_id"] for o in goal["d2"] if o["role"] == "alternative"} == set(d2["alternatives"])
        assert [a["answer"] for a in replay["actions"]] == [d1["expected_answer"]["terms"], goal["primary"]]
        assert replay["bundleVersion"] == bundle["bundleVersion"] and replay["routes"] == []
        assert bundle["routes"] == {} and bundle["pending"]["title"]
        ids = {n["id"] for n in bundle["graph"]["nodes"]}
        edges = {e["id"] for e in bundle["graph"]["edges"]}
        assert set(d1["effects"]["nodes"] + d1["candidateNodes"] + d2["candidateNodes"]) <= ids
        assert d2["effects"]["edges"] and set(d2["effects"]["edges"]) <= edges
    walks = [g["walk"]["bundle"]["problemId"] for g in goals if g["walk"]]
    assert len(set(walks)) == len(walks)


def test_a_part_without_reading_rows_still_walks_the_type_choice(tmp_path):
    result = search_result("q04")
    for row in result["features"]:
        if row["feature_id"] == "bound_vars":
            row.update(status="unknown", value=None, diagnostics=[{"code": "test.unknown"}])
    (goal,) = lesson("q04", tmp_path, result)["goals"]
    assert goal["d1"]["rows"] == []
    assert [d["id"] for d in goal["walk"]["bundle"]["intro"]] == ["D2"]
    assert [a["decision"] for a in goal["walk"]["replay"]["actions"]] == ["D2"]


@pytest.fixture
def client(tmp_path, monkeypatch):
    recorded = json.loads((PAGE / "ocr.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(dev_api.OcrClient, "observe", lambda self, path: recorded)
    monkeypatch.setenv("RUN_LLM_INTEGRATION", "1")
    monkeypatch.setattr("shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory",
                        lambda name, **_kwargs: (lambda: object()))
    return authenticated_client(tmp_path)


def start(client, monkeypatch, case):
    def fake_run(png, output, provider, *, problem_id, original_png=None, read_graph_details=False):
        result = {**search_result(case), "question_sha256": "a", "sent_image_sha256": ["a"]}
        candidate = deepcopy(result["candidate"])
        children = candidate["root"].get("children", [])
        body = candidate["original_text"]
        public_scopes = [{"scope_ref": "/root", "statement": body.split(children[0]["label"])[0] if children else body,
                          "choices": [{"target_ref": f"/root/goals/{index}", "status": "none", "selection_mode": "none", "options": []}
                                      for index, _goal in enumerate(candidate["root"].get("goals", []))]}]
        for index, child in enumerate(children):
            statement = body.split(child["label"], 1)[1]
            if index + 1 < len(children):
                statement = statement.split(children[index + 1]["label"], 1)[0]
            public_scopes.append({"scope_ref": f"/root/children/{index}", "statement": statement,
                                  "choices": [{"target_ref": f"/root/children/{index}/goals/{number}", "status": "none",
                                               "selection_mode": "none", "options": []} for number, _goal in enumerate(child.get("goals", []))]})
        candidate["public_content"] = {"completeness": "complete", "privacy": "separated", "figure": "not_required", "scopes": public_scopes}
        result.update(reviewed_result(candidate))
        (output / dev_api.RESULT_FILE).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return result

    monkeypatch.setattr(dev_api, "run_question_image", fake_run)
    page = client.post("/api/search/pages", content=(PAGE / "page.png").read_bytes()).json()
    return client.post("/api/search/problems", json={"page_id": page["page_id"],
                                                     "box": page["regions"][0]["box"]}).json()["search_id"]


def wait(client, sid, *, timeout_seconds=30):
    # Wait for the background execution to finish before fixtures are torn down.
    # This wall-clock allowance includes worker startup and persisted exports;
    # the per-route calculation and verification budgets remain unchanged.
    deadline = time.monotonic() + timeout_seconds
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/api/search/problems/{sid}").json()
        lesson = status.get("lesson", {})
        if (status["state"] == "done" and lesson.get("status") != "running"
                and lesson.get("execution_status") not in {"starting", "running"}):
            return status
        time.sleep(0.05)
    raise AssertionError(f"lesson did not finish: {status}")


def test_status_carries_the_lesson_after_stage_two(client, monkeypatch, tmp_path):
    sid = start(client, monkeypatch, "q10")
    # Both goals now execute three routes, including the classified interval path.
    status = wait(client, sid, timeout_seconds=90)
    assert status["outcome"] == "ok" and status["lesson"]["status"] == "completed"
    assert [g["label"] for g in status["lesson"]["goals"]] == ["（1）", "（2）"]
    assert all(len(g["d1"]["rows"]) == 3 for g in status["lesson"]["goals"])


def test_retry_reruns_stage_two_only_into_a_new_attempt(client, monkeypatch, tmp_path):
    sid = start(client, monkeypatch, "q04")
    wait(client, sid)
    assert client.post(f"/api/search/problems/{sid}/lesson").json() == {"status": "running"}
    assert wait(client, sid)["lesson"]["status"] == "completed"
    directory = tmp_path / "submissions" / sid
    assert sorted(p.name for p in directory.glob("stage-two-*")) == ["stage-two-1", "stage-two-2"]


def test_tex_turns_only_lone_number_pairs_into_fractions():
    assert tex("(0,1/2]") == r"(0,\frac{1}{2}]"
    assert tex("(0,-1/2]") == r"(0,-\frac{1}{2}]"
    for value in ("a/2/3", "1/2/3", "sqrt(4)/2/3", "sqrt(4)/-2/3", "a/+2/3", "a/--2/3", "a/+-2/3", "a/-+-2/3"):
        assert r"\frac" not in tex(value), value


def test_tex_turns_sqrt_into_latex():
    assert tex("[0,sqrt(2)]") == r"[0,\sqrt{2}]"
    assert tex("√(2)") == r"\sqrt{2}"
    assert tex("[0,sqrt(sqrt(2) + 2)]") == r"[0,\sqrt{\sqrt{2}+2}]"
    assert tex("[0,Abs(a)]") == r"[0,\left|a\right|]"
    assert tex("2**(1/3)") == r"2^{\frac{1}{3}}"
    assert tex("[pi,2*pi]") == r"[\pi ,2\pi ]"
    assert tex("2*sqrt(2)") == r"2\sqrt{2}"
    assert tex("3*Abs(a)") == r"3\left|a\right|"
    assert tex("2√(3)") == r"2\sqrt{3}"
    assert tex("2*3") == r"2\times 3"
    assert tex("a*sqrt(a^2+1)") == r"a\sqrt{a^{2}+1}"
    assert tex("a*Abs(c)") == r"a\left|c\right|"
    assert tex("sqrt(2)*3") == r"\sqrt{2}\cdot 3"


@pytest.mark.parametrize(("bound", "shown"), [
    ("sqrt(2+sqrt(2))", r"\sqrt{\sqrt{2}+2}"),
    ("sqrt(a^2)", r"\left|a\right|"),
    ("a*sqrt(a^2+1)", r"a\sqrt{a^{2}+1}"),
])
def test_normalized_interval_endpoints_render_as_math(tmp_path, bound, shown):
    candidate = {
        "original_text": f"若不等式 $x^2+bx+1≥0$ 对一切 $x∈[0,{bound}]$ 恒成立，求实数 $b$ 的取值范围。",
        "root": {"facts": [f"∀x∈[0,{bound}]: x^2+b*x+1>=0"], "goals": [{"kind": "find_range", "symbol": "b"}]},
    }
    extracted = extract_features(candidate)
    assert extracted["ok"], extracted["diagnostics"]
    result = {"status": "reviewed_candidate", "source_reviewed": True, "candidate": candidate,
              "features": extracted["features"], "features_ok": True}

    def no_selection():
        raise AssertionError("the uniquely supported quantified-quadratic type does not need an LLM")

    (goal,) = lesson("endpoint", tmp_path, result=result, provider=no_selection)["goals"]
    row = next(row for row in goal["d1"]["rows"] if row["kind"] == "quantifier")
    texts = [option["text"] + option.get("feedback", "") for option in row["options"]]
    assert any(shown in text for text in texts)
    assert not any(re.search(r"(?<!\\)(sqrt|Abs)", text) for text in texts)


def test_variable_swap_with_degree_zero_is_not_called_linear(tmp_path):
    candidate = {
        "original_text": "若不等式 $x^2+m≥m+1$ 对任意实数 $m$ 恒成立，求实数 $x$ 的取值范围。",
        "root": {"facts": ["∀m∈ℝ: x^2+m>=m+1"], "goals": [{"kind": "find_range", "symbol": "x"}]},
    }
    extracted = extract_features(candidate)
    assert extracted["ok"], extracted["diagnostics"]
    result = {"status": "reviewed_candidate", "source_reviewed": True, "candidate": candidate,
              "features": extracted["features"], "features_ok": True}

    def no_selection():
        raise AssertionError("the uniquely supported quantified-quadratic type does not need an LLM")

    (goal,) = lesson("swap-zero", tmp_path, result=result, provider=no_selection)["goals"]
    assert goal["status"] == "resolved"
    rows = {row["kind"]: row for row in goal["d1"]["rows"]}
    assert correct(rows["relation"]) == "关于 $m$ 是常数（与 $m$ 无关），关于 $x$ 是二次式"
    assert "一次" not in correct(rows["relation"])
