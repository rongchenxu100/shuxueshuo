"""Q17: eliminate m^2 as a whole, split by a monomial denominator, then use AM-GM directly."""

import asyncio
import json
import os
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    text = (ROOT / "site/1/q17/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', text, re.DOTALL)[1]
    )


def fills(*values):
    return [operation("fill", value, i) for i, value in enumerate(values)] + [
        operation("submit")
    ]


def choose(value):
    return [operation("choice", value), operation("submit")]


def actions():
    pair = ("1/(5n^2)", "4n^2/5")
    return (
        [operation("method", "elimination")]
        + choose("missing_five")
        + choose("wrong_sign")
        + choose("correct")
        + fills("1/5", "-1/5")
        + fills("1/5", "6/5")
        + fills("1/5", "4/5")
        + fills(*pair)
        + [operation("swap", "product"), operation("submit")]
        + fills(*reversed(pair))
        + fills(*pair)
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q17")
    text = (ROOT / "site/1/q17/index.html").read_text()
    assert "典例" not in text and "例4-2" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    for node, expected in zip(
        page["routes"]["elimination"], teacher["routes"]["elimination"]["nodes"], strict=True
    ):
        for key in ("id", "title", "question", "interaction", "expected_answer", "feedback"):
            assert node[key] == expected[key]
        assert node["display"] in templates
        if node["interaction"]["type"] == "choice":
            options = {o["value"] for o in node["interaction"]["options"]}
            assert set(node["preview"]) == options
            assert set(node["preview"].values()) <= templates
        if node.get("board"):
            assert node["board"] in templates
    assert [n["title"] for n in page["routes"]["elimination"]] == [
        "消参", "分式分离", "观察和积结构", "应用基本不等式", "验证取等",
    ]
    split = re.search(r'<template id="split-board">(.*?)</template>', text, re.S)[1]
    assert re.findall(r'data-fill="(\d+)"', split) == ["0", "1"]
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    assert (ROOT / "site/1/index.html").read_text().count('class="problem-card" href="/1/q17/"') == 1


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(
        actions() + [operation("switch_route", "elimination")] + actions()[1:]
    )
    script = """
require(process.argv[1]);
const {lesson, operations} = JSON.parse(require('fs').readFileSync(0,'utf8'));
let view=PracticeContext.create(lesson,'start');
console.log(JSON.stringify(operations.map(op=>{view=PracticeContext.apply(view,op,lesson);return view;})));
"""
    local = json.loads(
        subprocess.run(
            ["node", "-e", script, str(ROOT / "site/assets/practice/context.js")],
            input=json.dumps({"lesson": page_config(), "operations": ops}),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    async def run():
        session, tutor = Session(load_lesson("q17")), Tutor()
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
        assert errors.count(1) == 4
        assert errors.count(2) == 2
        assert set(errors) == {0, 1, 2}
        assert view["state"]["active"] == 5
        assert view["state"]["choices"] == {"eliminate_form": "correct"}
        assert view["state"]["pairs"][1] == ["1/5", "4/5"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q17_degree_explanation_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ("m²明明是二次，为什么这里说是一次？原条件左边关于m、n一共是几次？", 0),
        ("那为什么不把n²看成整体，先消去n²？", 0),
        ("题目没说n不等于0，可以直接除以n²吗？m、n一定都是正数吗？", 0),
        ("m²=(1-n⁴)/n²", 0),
        ("m²=(1-n⁴)/(5n²)", 1),
        ("我填了1/5和-1/5，请按我的填写通分，看看错在哪，不要替我改选。", 1),
        ("1/n²的系数是1/5，另一个还没算好", 1),
        ("n²的系数是4/5", 2),
        ("这两项是定和求积", 2),
        ("1/(5n²)和4n²/5，定积求和，积为4/25", 3),
        ("最小值是4/5", 3),
        ("1/(5n²)+4n²/5≥2√(4/25)=4/5", 4),
        ("n²=-1/2时取等", 4),
        ("n²=1/2，m²=3/10，满足原条件", 5),
    ]

    async def run():
        session, tutor = Session(load_lesson("q17")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = [operation("method", "elimination")] if i == 0 else fills("1/5", "-1/5") if i == 5 else []
                view = await session.handle(
                    Event(
                        event_id=f"live-{i}", kind="text", text=text,
                        revision=session.revision, lesson_version=1,
                        pending_operations=[{**op, "event_id": f"live-ui-{i}-{j}"} for j, op in enumerate(pending(ops))],
                    ), tutor,
                )
                reply = view["messages"][-1]["text"]
                print(json.dumps({"turn": i + 1, "student": text, "active": view["state"]["active"], "reply": reply, "model_reply": tutor.proposal.reply, "evidence": tutor.proposal.evidence}, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active
                assert not re.search(r"eliminate_expression|reciprocal_coefficient|square_coefficient|equal_terms|契约", reply)
                if i == 0:
                    assert "二次" in reply and "四次" in reply and "一次" in reply
                    assert "整体" in reply or "u" in reply
                if i == 5:
                    assert confirmed_pair(view) == ["1/5", "-1/5"]
                    assert tutor.proposal.intent == "question"
                    assert tutor.proposal.evidence == []
                    compact = re.sub(r"\s|\\(?:left|right)", "", reply)
                    assert re.search(r"\\(?:d?frac)\{1[-−]n\^\{?4\}?\}\{5n\^\{?2\}?\}", compact)
                if i == 6:
                    assert "reciprocal_coefficient" in tutor.proposal.evidence
                    assert "square_coefficient" not in tutor.proposal.evidence
            assert view["state"]["pairs"][1] == ["1/5", "4/5"]
        finally:
            await tutor.close()

    asyncio.run(run())


def test_confirmed_fill_shows_authored_common_denominator_check():
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["elimination"][1]
    html = (ROOT / "site/1/q17/index.html").read_text()
    templates = dict(re.findall(r'<template id="([^"]+)">(.*?)</template>', html, re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q17"))
    assert "\\frac45" not in load_lesson("q17")["routes"]["elimination"]["nodes"][1]["feedback"]["terms"]
    n = sp.Symbol("n")
    actual = (1 - n**4) / (5 * n**2) + n**2

    def arg(text, i):
        if text[i] != "{":
            return text[i], i + 1
        depth = 0
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                return text[i + 1 : j], j + 1

    def plain(text):
        out, i = "", 0
        while i < len(text):
            if text.startswith(r"\frac", i):
                num, i = arg(text, i + 5)
                den, i = arg(text, i)
                out += f"(({plain(num)})/({plain(den)}))"
            else:
                out += text[i]
                i += 1
        return out

    def parse(text):
        return parse_expr(
            plain(text).replace("^", "**"),
            local_dict={"n": n},
            transformations=standard_transformations
            + (implicit_multiplication_application,),
        )

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对通分结果。", intent="question", evidence=[], actions=[])

    async def run():
        for a in node["interaction"]["terms"]:
            for b in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][a][b]
                session = Session(load_lesson("q17"))
                view = await session.handle(
                    Event(
                        event_id="ask",
                        kind="text",
                        text="这个对吗？",
                        revision=0,
                        lesson_version=1,
                        pending_operations=pending(
                            [operation("method", "elimination")]
                            + choose("correct")
                            + fills(a, b)
                        ),
                    ),
                    QuestionTutor(),
                )
                if [a, b] == ["1/5", "4/5"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [a, b]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = lines[0].split("=")
                fill = sp.Rational(a) / n**2 + sp.Rational(b) * n**2
                assert sp.simplify(parse(left) - fill) == 0
                assert sp.simplify(parse(mine) - fill) == 0
                assert sp.simplify(fill - actual) != 0
                assert lines[2] == mine + r"\not\equiv\frac{1+4n^4}{5n^2}"

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
        session = Session(load_lesson("q17"))
        turns = [["eliminate_expression"], ["reciprocal_coefficient"], ["square_coefficient"]]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}",
                    revision=session.revision,
                    kind="text",
                    text="本轮证据",
                    lesson_version=1,
                    pending_operations=pending([operation("method", "elimination")])
                    if i == 0
                    else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [1, 1, 2][i]
        assert view["state"]["pairs"][1] == ["1/5", "4/5"]

    asyncio.run(run())
