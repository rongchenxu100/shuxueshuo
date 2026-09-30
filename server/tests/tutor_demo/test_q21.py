"""Q21: substitute both denominators, express the target as x+y, then the homogeneous chain."""

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

TITLES = ["双换元", "用新元表示目标", "识别齐次结构", "配齐次式", "观察和积结构", "应用基本不等式", "验证取等"]


def page_text():
    return (ROOT / "site/1/q21/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "substitution")]
        + [operation("fill", "4a+b", 0), operation("submit")]
        + [operation("fill", "a+2b", 0), operation("submit")]
        + [operation("fill", "4a+b|a+2b", 0), operation("submit")]
        + pair("5", "3")
        + pair("1", "2")
        + pair("1", "1")
        + pair("-1", "1")
        + pair("1", "-1")
        + pair("whole", "1/x+1/y")
        + pair("first", "(1/x+1/y)/3")
        + pair("whole", "(1/x+1/y)/3")
        + pair("y/x", "x/y")
        + [operation("swap", "product"), operation("submit")]
        + pair("x/y", "y/x")
        + pair("y/x", "y/x")
        + pair("y/x", "x/y")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q21"), page_text()
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
    assert combos == ["4a+b", "a+2b", "4a+b|a+2b"]
    assert set(nodes[0]["scope_boards"]) == set(combos)
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('href="/1/q21/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(
        actions() + [operation("switch_route", "substitution")] + actions()[1:]
    )
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q21")), Tutor()
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
        assert view["state"]["pairs"][0] == ["4a+b|a+2b", ""]
        assert view["state"]["pairs"][1] == ["1", "1"]
        assert view["state"]["pairs"][2] == ["1", "-1"]
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
    assert "attempt_calculations" not in json.dumps(load_lesson("q21"))
    a, b = sp.symbols("a b")
    target = 5 * a + 3 * b

    def parse(text):
        text = re.sub(r"(\d)([ab(])", r"\1*\2", text)
        return sp.sympify(text, locals={"a": a, "b": b})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对展开结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q21"))
                view = await session.handle(
                    Event(
                        event_id="ask",
                        kind="text",
                        text="这个对吗？",
                        revision=0,
                        lesson_version=1,
                        pending_operations=pending(
                            [operation("method", "substitution"), operation("fill", "4a+b|a+2b", 0), operation("submit")]
                            + pair(p, q)
                        ),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["1", "1"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = lines[0].split("=")
                fill = sp.Integer(p) * (4 * a + b) + sp.Integer(q) * (a + 2 * b)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - target) != 0
                assert lines[1] == mine + r"\not\equiv 5a+3b"

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
        session = Session(load_lesson("q21"))
        turns = [
            ["first_denominator_target"],
            ["second_denominator_target"],
            ["x_coefficient"],
            ["y_coefficient"],
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
        assert view["state"]["pairs"][0] == ["4a+b|a+2b", ""]
        assert view["state"]["pairs"][1] == ["1", "1"]
        assert view["state"]["pairs"][2] == ["1", "-1"]

    asyncio.run(run())


def test_rewrite_expansions_and_confirmed_feedback():
    """All scope/factor combinations expand correctly and preserve student input."""
    import sympy as sp
    from .test_q14 import confirmed_pair
    node = page_config()["routes"]["substitution"][3]
    html = page_text()
    x, y = sp.symbols("x y", positive=True)

    def parse(latex):
        latex = latex.replace(r"\left", "").replace(r"\right", "").replace(r"\cdot", "*")
        latex = re.sub(r"\\frac\s*([0-9xy])\s*([0-9xy])", r"((\1)/(\2))", latex)
        latex = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", latex)
        latex = re.sub(r"(\d)([xy])", r"\1*\2", latex).replace(")(", ")*(")
        return sp.sympify(latex, locals={"x": x, "y": y})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="按当前选择展开核对。", intent="question", evidence=[], actions=[])

    async def run():
        for scope in ("whole", "first", "second"):
            for factor in ("(1/x+1/y)/3", "1/x+1/y", "1"):
                tid = node["attempt_calculations"][scope][factor]
                session = Session(load_lesson("q21"))
                ops = [operation("method", "substitution"), operation("fill", "4a+b|a+2b", 0), operation("submit")]
                ops += pair("1", "1") + pair("1", "-1") + pair(scope, factor)
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
                f = sp.sympify(factor, locals={"x": x, "y": y})
                actual = {"whole": (x+y)*f, "first": x*f+y, "second": x+y*f}[scope]
                assert sp.simplify(parse(lines[0]) - actual) == 0
                assert sp.simplify(parse(lines[1][1:]) - actual) == 0
                difference = sp.simplify((actual-x-y).subs(y, x/(3*x-1)))
                assert (difference == 0) == (factor != "1/x+1/y")
                assert 'class="rewrite-calculation-feedback"' in block
                view = await session.handle(Event(
                    event_id="edit", kind="ui", revision=session.revision,
                    action=operation("fill", "second" if scope != "second" else "first", 0),
                ), QuestionTutor())
                assert confirmed_pair(view) is None
    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q21_actual_inputs_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ("我只想先令x=4a+b，另一个还没想好", 0),
        ("再令y=a+2b", 1),
        ("我填5和3，请按这两个数展开解释，不要替我改。", 1),
        ("x的系数是1，y的系数还没确定", 1),
        ("y的系数也是1", 2),
        ("x+y有两项，所以是二次吗？", 2),
        ("目标是正一次，条件表达式是负一次", 3),
        ("我只给x乘(1/x+1/y)/3，请按我的选择展开。这样值变了吗？不要替我改。", 3),
        ("我改成给整个x+y乘1/x+1/y，请按当前选择展开，值保持了吗？不要替我改。", 3),
        ("只给y乘(1/x+1/y)/3会怎样？请展开说明，先不改我的选择。", 3),
        ("直接乘常数1呢？为什么还不行？", 3),
        ("我给整个x+y乘1/x+1/y，再整体除以3", 4),
        ("y/x和x/y的积为1，是定积求和", 5),
        ("最小值是4/3", 5),
        ("y/x+x/y≥2，所以原式≥2/3+2/3=4/3", 6),
        ("a=b时取等", 6),
        ("a=2/21，b=2/7，两个分母都是2/3", 7),
    ]

    async def run():
        session, tutor = Session(load_lesson("q21")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = {0: [operation("method", "substitution")], 2: pair("5", "3"),
                       7: pair("first", "(1/x+1/y)/3"), 8: pair("whole", "1/x+1/y"),
                       9: pair("second", "(1/x+1/y)/3"), 10: pair("whole", "1")}.get(i, [])
                view = await session.handle(Event(
                    event_id=f"live-{i}", kind="text", text=text, revision=session.revision,
                    lesson_version=1,
                    pending_operations=[{**op, "event_id": f"live-ui-{i}-{j}"} for j, op in enumerate(pending(ops))],
                ), tutor)
                reply = view["messages"][-1]["text"]
                print(json.dumps({"turn": i+1, "student": text, "active": view["state"]["active"], "reply": reply,
                                  "model_reply": tutor.proposal.reply, "evidence": tutor.proposal.evidence}, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active
                assert not re.search(r"whole_scope|unit_factor|x_coefficient|y_coefficient|契约", reply)
                if i in (2, 5, 7, 8, 9, 10):
                    assert not tutor.proposal.evidence and not tutor.proposal.actions
                if i in (2, 7, 8, 9, 10):
                    assert confirmed_pair(view) == [ops[0]["value"], ops[1]["value"]]
                if i == 2:
                    assert "23a" in reply.replace(" ", "") and "11b" in reply.replace(" ", "")
                if i in (7, 9):
                    assert re.search("不变|没有变|不改值|等价|保持值|值保持|值不改变|不改变.*值", reply)
                    assert not re.search("值改变了|不保持|不相等|不等价", reply)
                    assert re.search("一次|1.*次|混合|不是零次|不全是零次", reply)
                if i == 8:
                    assert "3" in reply and re.search("不等价|三倍|3.*倍|改变", reply)
        finally:
            await tutor.close()
    asyncio.run(run())
