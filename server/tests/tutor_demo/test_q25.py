"""Q25: substitute t=x+1, split term by term, then AM-GM; the minimum is 5 at x=1."""

import asyncio
import json
import re
import os

import pytest

from shuxueshuo_server.tutor_demo.contracts import allowed_actions
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay, template

TITLES = ["换元", "分式分离", "观察和积结构", "应用基本不等式", "验证取等"]


def page_text():
    return (ROOT / "site/1/q25/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "split")]
        + [operation("fill", "x", 0), operation("submit")]
        + [operation("fill", "x+1", 0), operation("submit")]
        + pair("3", "6")
        + pair("4", "1")
        + pair("1", "4")
        + pair("t", "4/t")
        + [operation("swap", "product"), operation("submit")]
        + pair("4/t", "t")
        + pair("t", "t")
        + pair("t", "4/t")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q25"), page_text()
    assert "典例" not in text and "变式" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    nodes = page["routes"]["split"]
    for node, expected in zip(nodes, teacher["routes"]["split"]["nodes"], strict=True):
        for key in ("id", "title", "question", "interaction", "expected_answer", "feedback"):
            assert node[key] == expected[key]
        assert node["display"] in templates
        if node.get("board"):
            assert node["board"] in templates
    assert [n["title"] for n in nodes] == TITLES
    assert set(nodes[1]["attempt_calculations"]) == set(nodes[1]["interaction"]["terms"])
    assert all(set(row.values()) <= templates for row in nodes[1]["attempt_calculations"].values())
    assert set(nodes[0]["scope_boards"].values()) <= templates
    board = template(text, nodes[0]["board"])
    assert set(re.findall(r'data-sub-target="([^"]+)"', board)) == {"x+1", "x"}
    combos = [v for v in allowed_actions(teacher["routes"]["split"]["nodes"][0])[0]["values"] if v]
    assert set(combos) == set(nodes[0]["scope_boards"])
    assert "$5$" in template(text, page["completion"])
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('href="/1/q25/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(actions() + [operation("switch_route", "split")] + actions()[1:])
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q25")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert set(errors) == {0, 1, 2, 4}
        assert view["state"]["active"] == 5
        assert view["state"]["pairs"][0] == ["x+1", ""]
        assert view["state"]["pairs"][1] == ["1", "4"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_multiply_back_check():
    import sympy as sp
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["split"][1]
    templates = dict(re.findall(r'<template id="([^"]+)">\n?(.*?)\n?\s*</template>', page_text(), re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q25"))
    x = sp.Symbol("t")

    def parse(text):
        text = text.replace(r"\left(", "(").replace(r"\right)", ")")
        text = re.sub(r"\\frac(\d)t", r"(\1/t)", text)
        text = text.replace("^", "**")
        text = re.sub(r"(\d)t", r"\1*t", text)
        text = re.sub(r"t\(", "t*(", text)
        return sp.sympify(text, locals={"t": x})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对乘回的结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q25"))
                view = await session.handle(
                    Event(
                        event_id="ask", kind="text", text="这个对吗？", revision=0, lesson_version=1,
                        pending_operations=pending([operation("method", "split"), operation("fill", "x+1", 0), operation("submit")] + pair(p, q)),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["1", "4"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = (side.strip("{}") for side in lines[0].split("="))
                fill = x * (x + sp.Integer(p) + sp.Integer(q) / x)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - (x**2 + x + 4)) != 0
                assert lines[1] == mine + r"\not\equiv t^2+t+4"

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(reply="已记录。", intent="answer", evidence=self.evidence, actions=[])

    async def run():
        session = Session(load_lesson("q25"))
        turns = [["denominator_target"], ["constant_term"], ["reciprocal_coefficient"], ["fixed_product_structure"]]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}", revision=session.revision, kind="text", text="本轮证据", lesson_version=1,
                    pending_operations=pending([operation("method", "split")]) if i == 0 else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [1, 1, 2, 3][i]
        assert view["state"]["pairs"][0] == ["x+1", ""]
        assert view["state"]["pairs"][1] == ["1", "4"]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_dialogue_errors_questions_and_completion():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ('我选了t=x。仍然可以拆成t²/(t+1)+3t/(t+1)+6/(t+1)吧？只问是否合法，不要改选择。', 0, 'question', [('method', 'split'), ('fill', 'x', 0), ('submit',)]),
        ('设t=x+1', 1, 'answer', []),
        ('我填常数3、倒数系数6，按我的选择乘回检查，不要替我改。', 1, 'question', [('fill', '3', 0), ('fill', '6', 1), ('submit',)]),
        ('常数是1，另一个待定', 1, 'answer', []),
        ('倒数系数4', 2, 'answer', []),
        ('定和求积', 2, 'answer', []),
        ('t和4/t定积求和', 3, 'answer', []),
        ('y≥4也成立吧，4也是下界吧？只讨论这个判断。', 3, 'question', []),
        ('所以最小值就是4', 3, 'answer', []),
        ('t+4/t≥2√(t·4/t)=4，所以y≥5', 4, 'answer', []),
        ('那x=5', 4, 'answer', []),
        ('t=-2时取等', 4, 'answer', []),
        ('x=1时取等', 5, 'answer', []),
    ]

    async def run():
        session, tutor = Session(load_lesson("q25")), RecordingTutor()
        try:
            for i, (text, active, intent, operations) in enumerate(turns):
                ops = [operation(*op) for op in operations]
                view = await session.handle(Event(
                    event_id=f"live-{i}", kind="text", text=text, revision=session.revision,
                    lesson_version=1,
                    pending_operations=[{**op, "event_id": f"ui-{i}-{j}"} for j, op in enumerate(pending(ops))],
                ), tutor)
                reply = view["messages"][-1]["text"]
                record = {"turn": i+1, "student": text, "active": view["state"]["active"],
                          "reply": reply, "model_reply": tutor.proposal.reply,
                          "evidence": tutor.proposal.evidence,
                          "actions": [a.model_dump() for a in tutor.proposal.actions]}
                print(json.dumps(record, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active, record
                assert not re.search("constant_term|reciprocal_coefficient|equal_terms|契约|未能对应到当前可执行的操作", reply)
                if intent == "question":
                    assert not tutor.proposal.evidence and not tutor.proposal.actions, record
                if operations and operations[-1][0] == "submit":
                    selected = [op[1] for op in operations if op[0] == "fill"]
                    assert confirmed_pair(view)[:len(selected)] == selected
                if i == 0:
                    assert re.search("可以|合法|成立|正确", reply)
                    assert not re.search("不能逐项相除|不能逐项拆|不合法", reply)
                if i == 2:
                    assert re.search(r"t(?:\^2|²).*\+3t.*\+6", re.sub(r"[\s{}]", "", reply))
                    # A wrong attempt must not be asserted equal to the original.
                    plain = re.sub(r"[\s${}\\]", "", reply).replace("frac", "").replace("left", "").replace("right", "")
                    assert "t^2+t+4t=t+3+6t" not in plain, record
                if i == 3:
                    assert tutor.proposal.evidence == ["constant_term"], record
                    assert not tutor.proposal.actions, record
                if i == 5:
                    assert not tutor.proposal.evidence and not tutor.proposal.actions, record
                if i in (7, 8):
                    plain = re.sub(r"[\s${}\\]", "", reply)
                    assert re.search("下界", plain)
                    assert "最小的下界" not in plain, record
                    assert not re.search(r"(?<!不能说)(?<!不得说)4(?:不是|并非)[^。；，]{0,8}下界", plain)
                if i == 7:
                    assert re.search("成立|正确|是的|没错|确实|较弱下界", reply)
                    assert not re.search(r"y>1.{0,15}(当然|所以|因此|于是).{0,10}y(?:ge|≥)4", plain), record
        finally:
            await tutor.close()
    asyncio.run(run())
