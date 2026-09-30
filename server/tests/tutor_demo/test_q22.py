"""Q22: substitute both target denominators, express the condition as a+2b=1, then the homogeneous chain."""

import asyncio
import json
import os
import re

import pytest

from shuxueshuo_server.tutor_demo.contracts import allowed_actions
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay, template

TITLES = ["双换元", "用新元表示条件", "识别齐次结构", "配齐次式", "观察和积结构", "应用基本不等式", "验证取等"]


def page_text():
    return (ROOT / "site/1/q22/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "substitution")]
        + [operation("fill", "2x-y", 0), operation("submit")]
        + [operation("fill", "x+2y", 0), operation("submit")]
        + [operation("fill", "2x-y|x+2y", 0), operation("submit")]
        + pair("4", "3")
        + pair("2", "1")
        + pair("1", "2")
        + pair("1", "-1")
        + pair("-1", "-1")
        + pair("-1", "1")
        + pair("whole", "2a+b")
        + pair("first", "a+2b")
        + pair("whole", "a+2b")
        + pair("2b/a", "2a/b")
        + [operation("swap", "product"), operation("submit")]
        + pair("2a/b", "2b/a")
        + pair("2b/a", "2b/a")
        + pair("2b/a", "2a/b")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q22"), page_text()
    assert "典例" not in text and "变式" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    nodes = page["routes"]["substitution"]
    for node, expected in zip(nodes, teacher["routes"]["substitution"]["nodes"], strict=True):
        for key in ("id", "title", "question", "interaction", "expected_answer", "feedback"):
            assert node[key] == expected[key]
        assert node["display"] in templates
        assert set(node.get("scope_boards", {}).values()) <= templates
        if node.get("board"):
            assert node["board"] in templates
        marker = {
            "substitution": "data-sub-target",
            "rewrite": "data-rewrite-scope",
        }.get(node["interaction"]["type"])
        if marker:
            board = template(text, node["board"])
            targets = set(re.findall(rf'{marker}="([^"]+)"', board))
            assert targets == {
                o["value"] for o in node["interaction"]["slots"][0]["options"]
            }
    assert [n["title"] for n in nodes] == TITLES
    substitution = teacher["routes"]["substitution"]["nodes"][0]
    combos = [v for v in allowed_actions(substitution)[0]["values"] if v]
    assert combos == ["2x-y", "x+2y", "2x-y|x+2y"]
    assert set(nodes[0]["scope_boards"]) == set(combos)
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('href="/1/q22/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(
        actions() + [operation("switch_route", "substitution")] + actions()[1:]
    )
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q22")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert errors.count(0) == 4
        assert set(errors) == {0, 1, 2, 3, 4, 6}
        assert view["state"]["active"] == 7
        assert view["state"]["pairs"][0] == ["2x-y|x+2y", ""]
        assert view["state"]["pairs"][1] == ["1", "2"]
        assert view["state"]["pairs"][2] == ["-1", "1"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_expansion_check():
    import sympy as sp
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["substitution"][1]
    html = page_text()
    templates = dict(re.findall(r'<template id="([^"]+)">\n?(.*?)\n?\s*</template>', html, re.S))
    assert r"\stackrel{?}{=}" in templates["express-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q22"))
    x, y = sp.symbols("x y")
    target = 4 * x + 3 * y

    def parse(text):
        text = re.sub(r"(\d)([xy(])", r"\1*\2", text)
        return sp.sympify(text, locals={"x": x, "y": y})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对展开结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q22"))
                view = await session.handle(
                    Event(
                        event_id="ask",
                        kind="text",
                        text="这个对吗？",
                        revision=0,
                        lesson_version=1,
                        pending_operations=pending(
                            [operation("method", "substitution"), operation("fill", "2x-y|x+2y", 0), operation("submit")]
                            + pair(p, q)
                        ),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["1", "2"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = lines[0].split("=")
                fill = sp.Integer(p) * (2 * x - y) + sp.Integer(q) * (x + 2 * y)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - target) != 0
                assert lines[1] == mine + r"\not\equiv 4x+3y"

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。", intent="answer", evidence=self.evidence, actions=[]
            )

    async def run():
        session = Session(load_lesson("q22"))
        turns = [
            ["first_denominator_target"],
            ["second_denominator_target"],
            ["a_coefficient"],
            ["b_coefficient"],
            ["target_degree"],
            ["condition_degree"],
        ]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}",
                    revision=session.revision,
                    kind="text",
                    text="本轮证据",
                    lesson_version=1,
                    pending_operations=pending([operation("method", "substitution")])
                    if i == 0
                    else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [0, 1, 1, 2, 2, 3][i]
        assert view["state"]["pairs"][0] == ["2x-y|x+2y", ""]
        assert view["state"]["pairs"][1] == ["1", "2"]
        assert view["state"]["pairs"][2] == ["-1", "1"]

    asyncio.run(run())

def test_rewrite_expansions_and_confirmed_feedback():
    """All scope/factor combinations expand correctly and preserve student input."""
    import sympy as sp
    from .test_q14 import confirmed_pair
    node = page_config()["routes"]["substitution"][3]
    html = page_text()
    a, b = sp.symbols("a b", positive=True)

    def parse(latex):
        latex = latex.replace(r"\left", "").replace(r"\right", "").replace(r"\cdot", "*")
        latex = re.sub(r"\\frac\s*([0-9ab])\s*([0-9ab])", r"((\1)/(\2))", latex)
        latex = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", latex)
        latex = re.sub(r"(\d)([ab])", r"\1*\2", latex).replace(")(", ")*(")
        return sp.sympify(latex, locals={"a": a, "b": b})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="按当前选择展开核对。", intent="question", evidence=[], actions=[])

    async def run():
        for scope in ("whole", "first", "second"):
            for factor in ("a+2b", "2a+b", "1"):
                tid = node["attempt_calculations"][scope][factor]
                session = Session(load_lesson("q22"))
                ops = [operation("method", "substitution"), operation("fill", "2x-y|x+2y", 0), operation("submit")]
                ops += pair("1", "2") + pair("-1", "1") + pair(scope, factor)
                view = await session.handle(Event(
                    event_id="question", kind="text", text="按我刚才选的式子解释，不要替我改。",
                    revision=0, lesson_version=1, pending_operations=pending(ops),
                ), QuestionTutor())
                if [scope, factor] == node["expected_answer"]["terms"]:
                    assert view["state"]["active"] == 4
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 3
                assert confirmed_pair(view) == [scope, factor]
                block = template(html, tid)
                math = re.search(r'<div class="rewrite-calculation-math">(.*?)</div>', block, re.S)[1]
                lines = re.findall(r'<p data-math-text>\$(.*?)\$</p>', math)
                f = sp.sympify(re.sub(r"(\d)([ab])", r"\1*\2", factor), locals={"a": a, "b": b})
                actual = {"whole": (1/a+2/b)*f, "first": f/a+2/b, "second": 1/a+2*f/b}[scope]
                assert sp.simplify(parse(lines[0]) - actual) == 0
                assert sp.simplify(parse(lines[1][1:]) - actual) == 0
                difference = sp.simplify((actual-1/a-2/b).subs(b, (1-a)/2))
                assert (difference == 0) == (factor != "2a+b")
                assert 'class="rewrite-calculation-feedback"' in block
                view = await session.handle(Event(
                    event_id="edit", kind="ui", revision=session.revision,
                    action=operation("fill", "second" if scope != "second" else "first", 0),
                ), QuestionTutor())
                assert confirmed_pair(view) is None
    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q22_expansion_weak_bound_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ("先令a=2x-y，另一个还没想好", 0),
        ("再令b=x+2y", 1),
        ("我填4和3，请按实际填写展开，别替我改。", 1),
        ("a的系数是1，另一个待定", 1),
        ("b的系数是2", 2),
        ("目标里有两个分式，所以是负二次吗？", 2),
        ("目标负一次，条件正一次", 3),
        ("只给1/a乘a+2b，请按我选择的展开，值改变了吗？别替我改。", 3),
        ("只给2/b乘a+2b又会怎样？请按选择展开解释，别改选择。", 3),
        ("整体乘2a+b，请展开看看，值是否保持？我先不改选择。", 3),
        ("但a=b=1/3时，2a+b也等于1啊，不能说它永远不等于1吧？", 3),
        ("直接乘常数1呢？", 3),
        ("给整个1/a+2/b乘a+2b", 4),
        ("2b/a和2a/b积为4，定积求和", 5),
        ("原式大于等于4也成立吧？4也是下界吧？这里只讨论这个判断。", 5),
        ("所以最小值是4", 5),
        ("2b/a+2a/b≥2√4=4，原式≥5+4=9", 6),
        ("x=y时取等", 6),
        ("x=1/5，y=1/15，两个分母均为1/3，满足条件", 7),
    ]

    async def run():
        session, tutor = Session(load_lesson("q22")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = {0: [operation("method", "substitution")], 2: pair("4", "3"),
                       7: pair("first", "a+2b"), 8: pair("second", "a+2b"),
                       9: pair("whole", "2a+b"), 11: pair("whole", "1")}.get(i, [])
                view = await session.handle(Event(
                    event_id=f"live-{i}", kind="text", text=text, revision=session.revision,
                    lesson_version=1,
                    pending_operations=[{**op, "event_id": f"live-ui-{i}-{j}"} for j, op in enumerate(pending(ops))],
                ), tutor)
                reply = view["messages"][-1]["text"]
                print(json.dumps({"turn": i+1, "student": text, "active": view["state"]["active"],
                                  "reply": reply, "model_reply": tutor.proposal.reply,
                                  "evidence": tutor.proposal.evidence}, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active
                assert not re.search(r"whole_scope|unit_factor|a_coefficient|b_coefficient|契约", reply)
                if i in (2, 5, 7, 8, 9, 10, 11, 14):
                    assert not tutor.proposal.evidence and not tutor.proposal.actions
                if i in (2, 7, 8, 9, 11):
                    assert confirmed_pair(view) == [ops[0]["value"], ops[1]["value"]]
                if i == 2:
                    assert "11x" in reply.replace(" ", "") and "2y" in reply.replace(" ", "")
                if i in (7, 8):
                    assert re.search("不变|没有变|没有改变|不改值|等价|等值|保持|不改变.*值", reply)
                    assert not re.search("值改变了|不保持|不相等|不等价", reply)
                    assert re.search("负一次|负1次|混合|次数不|不是零次|不全是零次", reply)
                if i == 14:
                    assert re.search("成立|也是.*下界|是.*下界", reply)
                    assert re.search("较弱|不紧|更紧|最优|最小值", reply)
                    assert not re.search("4.{0,8}不是.{0,6}下界", reply)
                if i in (14, 15):
                    for wording in (reply, tutor.proposal.reply):
                        plain = re.sub(r"[\s${}\\]", "", wording)
                        assert not re.search("4不是原式的下界|4并非原式的下界", plain)
                if i == 18:
                    plain = re.sub(r"[\s$]", "", tutor.proposal.reply)
                    assert not re.search(r"2x-y=(?:1/5|\\frac\{?1\}?\{?5\}?)(?![0-9+−-])", plain)
        finally:
            await tutor.close()
    asyncio.run(run())
