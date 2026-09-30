"""Q23: split (x^2-x+4)/x term by term, then the fixed-product AM-GM chain."""

import asyncio
import json
import os

import pytest
import re

from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay

TITLES = ["分式分离", "观察和积结构", "应用基本不等式", "验证取等"]


def page_text():
    return (ROOT / "site/1/q23/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "split")]
        + pair("1", "4")
        + pair("4", "-1")
        + pair("-1", "4")
        + pair("x", "4/x")
        + [operation("swap", "product"), operation("submit")]
        + pair("4/x", "x")
        + pair("x", "x")
        + pair("x", "4/x")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q23"), page_text()
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
    assert set(nodes[0]["attempt_calculations"]) == set(nodes[0]["interaction"]["terms"])
    assert all(set(row.values()) <= templates for row in nodes[0]["attempt_calculations"].values())
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('href="/1/q23/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(actions() + [operation("switch_route", "split")] + actions()[1:])
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q23")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert set(errors) == {0, 1, 3}
        assert view["state"]["active"] == 4
        assert view["state"]["pairs"][0] == ["-1", "4"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_multiply_back_check():
    import sympy as sp
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["split"][0]
    templates = dict(re.findall(r'<template id="([^"]+)">\n?(.*?)\n?\s*</template>', page_text(), re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q23"))
    x = sp.Symbol("x")

    def parse(text):
        text = text.replace(r"\left(", "(").replace(r"\right)", ")")
        text = re.sub(r"\\frac(\d)x", r"(\1/x)", text)
        text = text.replace("^", "**")
        text = re.sub(r"(\d)x", r"\1*x", text)
        text = re.sub(r"x\(", "x*(", text)
        return sp.sympify(text, locals={"x": x})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对乘回的结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q23"))
                view = await session.handle(
                    Event(
                        event_id="ask", kind="text", text="这个对吗？", revision=0, lesson_version=1,
                        pending_operations=pending([operation("method", "split")] + pair(p, q)),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["-1", "4"]:
                    assert view["state"]["active"] == 1
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 0
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = (side.strip("{}") for side in lines[0].split("="))
                fill = x * (x + sp.Integer(p) + sp.Integer(q) / x)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - (x**2 - x + 4)) != 0
                assert lines[1] == mine + r"\not\equiv x^2-x+4"

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(reply="已记录。", intent="answer", evidence=self.evidence, actions=[])

    async def run():
        session = Session(load_lesson("q23"))
        turns = [["constant_term"], ["reciprocal_coefficient"], ["fixed_product_structure"]]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}", revision=session.revision, kind="text", text="本轮证据", lesson_version=1,
                    pending_operations=pending([operation("method", "split")]) if i == 0 else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [0, 1, 2][i]
        assert view["state"]["pairs"][0] == ["-1", "4"]

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

    turns = [('我填常数1、倒数系数4，请按我的填写乘回核对，不要替我改。', 0, 'question', [('method', 'split'), ('fill', '1', 0), ('fill', '4', 1), ('submit',)]), ('常数应为-1，另一个待定', 0, 'answer', []), ('倒数系数是4', 1, 'answer', []), ('定和求积', 1, 'answer', []), ('x和4/x定积求和', 2, 'answer', []), ('不分离，先用x²+4≥4x再除以x，也能得到y≥3吧？只讨论方法。', 2, 'question', []), ('y≥4也成立吗？', 2, 'question', []), ('对x和4/x用基本不等式：y≥2√(x·4/x)-1。根号化简交给系统。', 3, 'answer', []), ('x=-2时取等', 3, 'answer', []), ('x=2', 4, 'answer', [])]

    async def run():
        session, tutor = Session(load_lesson("q23")), RecordingTutor()
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
                assert not re.search("constant_term|reciprocal_coefficient|equal_terms|契约", reply)
                if intent == "question":
                    assert not tutor.proposal.evidence and not tutor.proposal.actions, record
                if operations and operations[-1][0] == "submit":
                    selected = [op[1] for op in operations if op[0] == "fill"]
                    assert confirmed_pair(view)[:len(selected)] == selected
                if i == 0:
                    assert re.search(r"x(?:\^2|²).*\+x.*\+4", reply.replace(" ", ""))
                if i == 5:
                    assert re.search("正确|成立|可以|可行|对的", reply)
                if i == 6:
                    assert re.search("不成立|不是|不能|不对", reply)
        finally:
            await tutor.close()
    asyncio.run(run())
