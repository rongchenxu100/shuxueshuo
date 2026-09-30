"""Q18: complete the condition to (2a+1)(b+1)=4, eliminate the whole 2a+1, then use AM-GM."""

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
    text = (ROOT / "site/1/q18/index.html").read_text()
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
    pair = ("b/4", "1/b")
    return (
        [operation("method", "elimination")]
        + fills("3")
        + fills("5")
        + fills("4")
        + choose("flipped")
        + choose("stale")
        + choose("correct")
        + fills(*pair)
        + [operation("swap", "product"), operation("submit")]
        + fills(*reversed(pair))
        + fills(*pair)
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q18")
    text = (ROOT / "site/1/q18/index.html").read_text()
    assert "典例" not in text and "变式" not in text
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
        "配因式", "消参", "观察和积结构", "应用基本不等式", "验证取等",
    ]
    factor = re.search(r'<template id="factor-board">(.*?)</template>', text, re.S)[1]
    assert re.findall(r'data-fill="(\d+)"', factor) == ["0"]
    assert page["routes"]["elimination"][0]["interaction"]["slot_labels"] == ["乘积的值"]
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('href="/1/q18/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


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
        session, tutor = Session(load_lesson("q18")), Tutor()
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
        assert view["state"]["pairs"][0][0] == "4"
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_single_slot_fill_rejects_out_of_range_index():
    async def run():
        session = Session(load_lesson("q18"))
        for op in pending([operation("method", "elimination"), operation("fill", "4", 1)]):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), Tutor()
            )
        return view

    view = asyncio.run(run())
    assert view["state"]["pairs"][0] == ["", ""]
    assert view["state"]["feedback"]


def test_single_fill_calculation_survives_dialogue_but_requires_reconfirmation():
    from .test_q14 import confirmed_pair
    from shuxueshuo_server.tutor_demo.contracts import node_contract

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先展开，再比较所填的值。", intent="question", evidence=[], actions=[])

    page = page_config()
    node = page["routes"]["elimination"][0]
    html = (ROOT / "site/1/q18/index.html").read_text()
    templates = dict(re.findall(r'<template id="([^"]+)">(.*?)</template>', html, re.S))
    assert r"\stackrel{?}{=}" in templates["factor-board"]
    assert set(node["attempt_calculations"]) == set(node["interaction"]["terms"])
    assert node["attempt_calculations"]["4"] == node["display"]

    async def run():
        for value in ("2", "3", "5", "6"):
            template = templates[node["attempt_calculations"][value]]
            assert "(2a+1)(b+1)=2ab+2a+b+1" in template
            assert f"3+1=4\\ne {value}" in template
            session = Session(load_lesson("q18"))
            view = await session.handle(Event(
                event_id="ask", kind="text", text="我填的哪里错了？", revision=0,
                lesson_version=1,
                pending_operations=pending([operation("method", "elimination")] + fills(value)),
            ), QuestionTutor())
            assert view["state"]["active"] == 0
            assert confirmed_pair(view) == [value, ""]
            contract = node_contract(load_lesson("q18")["routes"]["elimination"]["nodes"][0], view["state"])
            assert contract["current_inputs"] == [{"index": 0, "label": "乘积的值", "value": value}]
            # Editing and even changing back requires confirmation again.
            for i, chosen in enumerate(("4", value)):
                op = operation("fill", chosen, 0)
                view = await session.handle(Event(event_id=f"edit-{i}", kind="ui", action=op, revision=session.revision), QuestionTutor())
                assert confirmed_pair(view) is None
            view = await session.handle(Event(event_id="reconfirm", kind="ui", action=operation("submit"), revision=session.revision), QuestionTutor())
            assert confirmed_pair(view) == [value, ""]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q18_wrong_fill_three_term_amgm_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ("我在乘积值里填了3，请按我的填写展开核对，不要替我改选。", 0),
        ("左边加1，右边也加1，乘积是4", 1),
        ("1/(2a+1)=4/(b+1)", 1),
        ("1/(2a+1)=(b+1)/4", 2),
        ("直接对1/(2a+1)和1/b用基本不等式就违法了吗？", 2),
        ("b/4与1/b，定积求和", 3),
        ("我想把b/4、1/b、1/4三个正项一起用三项基本不等式，得到原式≥3乘以1/16的立方根。这么做有错吗，能取到吗？", 3),
        ("那原式≥1是不是也成立？", 3),
        ("所以原式最小值是1", 3),
        ("b/4+1/b≥2√(1/4)=1，加回1/4，原式≥5/4", 4),
        ("b=-2时取等", 4),
        ("b=2，a=1/6，满足原条件", 5),
    ]

    async def run():
        session, tutor = Session(load_lesson("q18")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(Event(
                    event_id=f"live-{i}", kind="text", text=text,
                    revision=session.revision, lesson_version=1,
                    pending_operations=pending([operation("method", "elimination")] + fills("3")) if i == 0 else [],
                ), tutor)
                reply = view["messages"][-1]["text"]
                print(json.dumps({"turn": i + 1, "student": text, "active": view["state"]["active"], "reply": reply, "model_reply": tutor.proposal.reply, "evidence": tutor.proposal.evidence}, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active
                assert not re.search(r"\\n(?![A-Za-z])", reply)
                assert not re.search(r"(?:^|\n)\s*}\s*(?:$|\n)", reply)
                assert not re.search(r"factor_constant|eliminate_expression|amgm_relation|equal_terms|契约", reply)
                if i == 0:
                    assert confirmed_pair(view) == ["3", ""]
                    assert tutor.proposal.evidence == []
                    assert "3+1=4" in re.sub(r"\s", "", reply)
                if i == 4:
                    assert re.search("成立|合法|可以", reply)
                    assert "\\ge" in reply or "≥" in reply
                    assert not re.search(r"不能对.*用基本不等式", reply)
                if i == 6:
                    assert tutor.proposal.intent == "question" and not tutor.proposal.evidence
                    assert re.search("成立|合法|没.*错|可以", reply)
                    assert "b=1" in reply.replace(" ", "") and "b=4" in reply.replace(" ", "")
                    assert re.search("不能|无法|不可能|矛盾|取不到", reply)
        finally:
            await tutor.close()

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
        session = Session(load_lesson("q18"))
        turns = [["factor_constant"], ["eliminate_expression"], ["fixed_product_structure"]]
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
            assert view["state"]["active"] == [1, 2, 3][i]
        assert view["state"]["pairs"][0][0] == "4"
        assert view["state"]["choices"]["eliminate_form"] == "correct"

    asyncio.run(run())
