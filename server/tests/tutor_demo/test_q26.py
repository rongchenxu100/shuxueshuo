"""Q26: maximize y=2x/(x^2+4) by minimizing 1/y, splitting term by term, then AM-GM."""

import asyncio
import json
import re
import os

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay, template

TITLES = ["转化目标", "分式分离", "观察和积结构", "应用基本不等式", "验证取等"]


def page_text():
    return (ROOT / "site/1/q26/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def choose(value):
    return [operation("choice", value), operation("submit")]


def actions():
    return (
        [operation("method", "reciprocal")]
        + choose("max_reciprocal")
        + choose("min_denominator")
        + choose("min_reciprocal")
        + pair("2", "4")
        + pair("1", "2")
        + pair("1/2", "2")
        + pair("x/2", "2/x")
        + [operation("swap", "product"), operation("submit")]
        + pair("2/x", "x/2")
        + pair("x/2", "x/2")
        + pair("x/2", "2/x")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q26"), page_text()
    assert "典例" not in text and "变式" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    nodes = page["routes"]["reciprocal"]
    for node, expected in zip(nodes, teacher["routes"]["reciprocal"]["nodes"], strict=True):
        for key in ("id", "title", "question", "interaction", "expected_answer", "feedback"):
            assert node[key] == expected[key]
        assert node["display"] in templates
        if node.get("board"):
            assert node["board"] in templates
    assert [n["title"] for n in nodes] == TITLES
    options = {o["value"] for o in nodes[0]["interaction"]["options"]}
    assert set(nodes[0]["preview"]) == options
    assert set(nodes[0]["preview"].values()) <= templates
    assert set(teacher["initial_state"]["choices"]) == {nodes[0]["interaction"]["field"]}
    assert set(nodes[1]["attempt_calculations"]) == set(nodes[1]["interaction"]["terms"])
    assert all(set(row.values()) <= templates for row in nodes[1]["attempt_calculations"].values())
    assert r"\frac12" in template(text, page["completion"])
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('class="problem-card" href="/1/q26/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(actions() + [operation("switch_route", "reciprocal")] + actions()[1:])
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q26")), Tutor()
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
        assert view["state"]["choices"] == {"transform_target": "min_reciprocal"}
        assert view["state"]["pairs"][1] == ["1/2", "2"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_multiply_back_check():
    import sympy as sp
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["reciprocal"][1]
    templates = dict(re.findall(r'<template id="([^"]+)">\n?(.*?)\n?\s*</template>', page_text(), re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q26"))
    x = sp.Symbol("x")

    def parse(text):
        text = text.replace(r"\left(", "(").replace(r"\right)", ")")
        text = text.replace(r"\frac1{2x}", "(1/(2*x))").replace(r"\frac12", "(1/2)")
        text = re.sub(r"\\frac(\d)x", r"(\1/x)", text)
        text = text.replace("^", "**")
        text = re.sub(r"([\d)])x", r"\1*x", text)
        text = re.sub(r"x\(", "x*(", text)
        return sp.sympify(text, locals={"x": x})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对乘回的结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q26"))
                view = await session.handle(
                    Event(
                        event_id="ask", kind="text", text="这个对吗？", revision=0, lesson_version=1,
                        pending_operations=pending([operation("method", "reciprocal")] + choose("min_reciprocal") + pair(p, q)),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["1/2", "2"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = (side.strip("{}") for side in lines[0].split("="))
                fill = 2 * x * (sp.Rational(p) * x + sp.Rational(q) / x)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - (x**2 + 4)) != 0
                assert lines[1] == mine + r"\not\equiv x^2+4"

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(reply="已记录。", intent="answer", evidence=self.evidence, actions=[])

    async def run():
        session = Session(load_lesson("q26"))
        turns = [["reciprocal_target"], ["x_coefficient"], ["reciprocal_coefficient"], ["fixed_product_structure"]]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}", revision=session.revision, kind="text", text="本轮证据", lesson_version=1,
                    pending_operations=pending([operation("method", "reciprocal")]) if i == 0 else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [1, 1, 2, 3][i]
        assert view["state"]["choices"] == {"transform_target": "min_reciprocal"}
        assert view["state"]["pairs"][1] == ["1/2", "2"]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_dialogue_errors_questions_and_completion():
    from .reciprocal_live import replay

    turns = [
        ('我选求分母最小值。但x>0，4只是下界，取不到吧？只解释，不要改选择。', 0, True,
         [('method', 'reciprocal'), ('choice', 'min_denominator'), ('submit',)], []),
        ('那1/y有最大值、y有最小值吗？', 0, True, [], []),
        ('应该求1/y的最小值', 1, False, [], ['reciprocal_target']),
        ('按我填的2和4乘回去检查，暂时不要替我改。', 1, True,
         [('fill', '2', 0), ('fill', '4', 1), ('submit',)], []),
        ('x的系数是1/2，另一个待定', 1, False, [], ['x_coefficient']),
        ('1/x的系数是2', 2, False, [], ['reciprocal_coefficient']),
        ('定和求积', 2, False, [], []),
        ('x/2和2/x是定积求和', 3, False, [], ['fixed_product_structure']),
        ('为什么1/y≥2要变成y≤1/2？只解释方向。', 3, True, [], []),
        ('x/2+2/x≥2√((x/2)(2/x))=2', 4, False, [], ['amgm_relation']),
        ('x=-2时取等', 4, False, [], []),
        ('x=2时取等', 5, False, [], ['equal_terms']),
    ]
    asyncio.run(replay('q26', turns))
