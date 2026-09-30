"""Q27: minimize 1/y, substitute t=2x+1, split term by term, apply AM-GM, then convert back to y."""

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

TITLES = ["转化目标", "换元", "分式分离", "观察和积结构", "应用基本不等式", "验证取等", "换回 y"]
CHOICES = {"transform_target": "min_reciprocal", "back_to_y": "reciprocal_back"}


def page_text():
    return (ROOT / "site/1/q27/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def choose(value):
    return [operation("choice", value), operation("submit")]


def before_split():
    return [operation("method", "reciprocal")] + choose("min_reciprocal") + [operation("fill", "2x+1", 0), operation("submit")]


def actions():
    return (
        [operation("method", "reciprocal")]
        + choose("max_reciprocal")
        + choose("min_reciprocal")
        + [operation("fill", "x", 0), operation("submit")]
        + [operation("fill", "2x+1", 0), operation("submit")]
        + pair("2", "5")
        + pair("5", "-2")
        + pair("-2", "5")
        + pair("t", "5/t")
        + [operation("swap", "product"), operation("submit")]
        + pair("5/t", "t")
        + pair("t", "t")
        + pair("t", "5/t")
        + choose("forgot_back")
        + choose("forgot_both")
        + choose("reciprocal_back")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q27"), page_text()
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
        if node["interaction"]["type"] == "choice":
            assert set(node["preview"]) == {o["value"] for o in node["interaction"]["options"]}
            assert set(node["preview"].values()) <= templates
    assert [n["title"] for n in nodes] == TITLES
    assert set(teacher["initial_state"]["choices"]) == set(CHOICES)
    assert set(nodes[2]["attempt_calculations"]) == set(nodes[2]["interaction"]["terms"])
    assert all(set(row.values()) <= templates for row in nodes[2]["attempt_calculations"].values())
    assert set(nodes[1]["scope_boards"].values()) <= templates
    board = template(text, nodes[1]["board"])
    assert set(re.findall(r'data-sub-target="([^"]+)"', board)) == {"2x+1", "x"}
    combos = [v for v in allowed_actions(teacher["routes"]["reciprocal"]["nodes"][1])[0]["values"] if v]
    assert set(combos) == set(nodes[1]["scope_boards"])
    assert r"\frac{\sqrt5+1}{2}" in template(text, page["completion"])
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('class="problem-card" href="/1/q27/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(actions() + [operation("switch_route", "reciprocal")] + actions()[1:])
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q27")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert set(errors) == {0, 1, 2, 3, 5, 6}
        assert view["state"]["active"] == 7
        assert view["state"]["choices"] == CHOICES
        assert view["state"]["pairs"][1] == ["2x+1", ""]
        assert view["state"]["pairs"][2] == ["-2", "5"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_multiply_back_check():
    import sympy as sp
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["reciprocal"][2]
    templates = dict(re.findall(r'<template id="([^"]+)">\n?(.*?)\n?\s*</template>', page_text(), re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q27"))
    t = sp.Symbol("t")

    def parse(text):
        text = text.replace(r"\left(", "(").replace(r"\right)", ")")
        text = re.sub(r"\\frac(\d)t", r"(\1/t)", text)
        text = text.replace("^", "**")
        text = re.sub(r"(\d)t", r"\1*t", text)
        text = re.sub(r"t\(", "t*(", text)
        return sp.sympify(text, locals={"t": t})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对乘回的结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q27"))
                view = await session.handle(
                    Event(
                        event_id="ask", kind="text", text="这个对吗？", revision=0, lesson_version=1,
                        pending_operations=pending(before_split() + pair(p, q)),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["-2", "5"]:
                    assert view["state"]["active"] == 3
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 2
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = (side.strip("{}") for side in lines[0].split("="))
                fill = t * (t + sp.Integer(p) + sp.Integer(q) / t)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - (t**2 - 2 * t + 5)) != 0
                assert lines[1] == mine + r"\not\equiv t^2-2t+5"

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(reply="已记录。", intent="answer", evidence=self.evidence, actions=[])

    async def run():
        session = Session(load_lesson("q27"))
        turns = [["reciprocal_target"], ["denominator_target"], ["constant_term"], ["reciprocal_coefficient"]]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}", revision=session.revision, kind="text", text="本轮证据", lesson_version=1,
                    pending_operations=pending([operation("method", "reciprocal")]) if i == 0 else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [1, 2, 2, 3][i]
        assert view["state"]["choices"]["transform_target"] == "min_reciprocal"
        assert view["state"]["pairs"][1] == ["2x+1", ""]
        assert view["state"]["pairs"][2] == ["-2", "5"]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_dialogue_errors_questions_and_completion():
    from .reciprocal_live import replay

    turns = [
        ('x>0时分母x²+1没有最小值，1只是取不到的下界，对吗？不要改我的选择。', 0, True,
         [('method', 'reciprocal'), ('choice', 'min_denominator'), ('submit',)], []),
        ('1/y是否有最大值？y有没有最小值？', 0, True, [], []),
        ('求1/y的最小值', 1, False, [], ['reciprocal_target']),
        ('我选t=x，仍能拆成t²/(2t+1)+1/(2t+1)吧？只问是否合法，不要代我换元。', 1, True,
         [('fill', 'x', 0), ('submit',)], []),
        ('令t=2x+1', 2, False, [], ['denominator_target']),
        ('我填2和5，按我的式子乘回t核对，不要替我改。', 2, True,
         [('fill', '2', 0), ('fill', '5', 1), ('submit',)], []),
        ('常数是-2，另一个待定', 2, False, [], ['constant_term']),
        ('1/t的系数是5', 3, False, [], ['reciprocal_coefficient']),
        ('定和求积', 3, False, [], []),
        ('t与5/t定积求和', 4, False, [], ['fixed_product_structure']),
        ('t+5/t≥2√5', 5, False, [], ['amgm_relation']),
        ('t>0就够了吗，为什么要保留t>1？只是问范围。', 5, True, [], []),
        ('t=-√5时取等', 5, False, [], []),
        ('x=(√5-1)/2时取等', 6, False, [], ['equal_terms']),
        ('所以y的最大值是(√5-1)/2', 6, False, [], []),
        ('y的最大值为2/(√5-1)', 7, False, [], ['reciprocal_back']),
    ]
    asyncio.run(replay('q27', turns))
