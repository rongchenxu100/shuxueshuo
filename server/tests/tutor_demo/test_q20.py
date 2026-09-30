"""Q20: eliminate m, split, complete, derive n>3 from m>2, then use AM-GM."""

import asyncio
import json
import os
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending

TITLES = ["消参", "分式分离", "凑配表达式", "判断两项为正", "观察和积结构", "应用基本不等式", "验证取等"]


def page_config():
    text = (ROOT / "site/1/q20/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', text, re.DOTALL)[1]
    )


def fills(*values):
    return [operation("fill", value, i) for i, value in enumerate(values)] + [
        operation("submit")
    ]


def choose(value):
    return [operation("choice", value), operation("submit")]


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q20_weak_bound_positivity_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ("我选了(3n+7)/(n-3)，为什么不对？先解释，不要替我改选。", 0),
        ("m=(7-3n)/(3-n)", 1),
        ("我填了3和-2，请按实际填写展开，看看哪里错，不要替我改。", 1),
        ("倍数是3，常数还没确定", 1),
        ("余下的常数是2", 2),
        ("先假设已证明n>3，直接对2n和2/(n-3)用基本不等式不成立吗？", 2),
        ("n/(n-3)>1，所以两项和≥4√(n/(n-3))>4，原式>7，这不就是定值下界吗？", 2),
        ("那最小值就是7吗？", 2),
        ("原式=2(n-3)+2/(n-3)+3", 2),
        ("原式=2(n-3)+2/(n-3)+9", 3),
        ("因为n>1，所以n-3>0", 3),
        ("m-2=(n-1)/(n-3)>0，n-1>0，所以n>3", 4),
        ("是定和求积", 4),
        ("2(n-3)和2/(n-3)，定积求和", 5),
        ("最小值13", 5),
        ("2(n-3)+2/(n-3)≥2√4=4，所以m+2n≥13", 6),
        ("n=2也满足(n-3)^2=1，所以在n=2取等", 6),
        ("n=4，m=5，满足原条件", 7),
    ]

    async def run():
        session, tutor = Session(load_lesson("q20")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = [operation("method", "elimination")] + choose("wrong_sign") if i == 0 else fills("3", "-2") if i == 2 else []
                view = await session.handle(Event(
                    event_id=f"live-{i}", kind="text", text=text,
                    revision=session.revision, lesson_version=1,
                    pending_operations=[{**op, "event_id": f"live-ui-{i}-{j}"} for j, op in enumerate(pending(ops))],
                ), tutor)
                reply = view["messages"][-1]["text"]
                print(json.dumps({"turn": i+1, "student": text, "active": view["state"]["active"], "reply": reply, "model_reply": tutor.proposal.reply, "evidence": tutor.proposal.evidence}, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active
                assert not re.search(r"denominator_multiple|remainder_constant|fixed_product_rewrite|positive_basis|equal_terms|契约", reply)
                assert not re.search(r"\\n(?![A-Za-z])", reply)
                if i in (0, 2, 5, 6, 7):
                    # Verify the behavioral contract: discussion must not supply
                    # answer evidence or actions, regardless of intent wording.
                    assert not tutor.proposal.evidence and not tutor.proposal.actions
                if i == 2:
                    assert confirmed_pair(view) == ["3", "-2"]
                    assert "3n-11" in reply.replace(" ", "").replace("−", "-")
                if i == 3:
                    assert tutor.proposal.evidence == ["denominator_multiple"]
                if i in (5, 6):
                    assert re.search("成立|可以|合法|正确|对的|没错", reply)
                if i == 6:
                    assert "7" in reply and re.search("较弱|不紧|粗|最优|最小值", reply)
            assert view["state"]["pairs"][1] == ["3", "2"]
        finally:
            await tutor.close()

    asyncio.run(run())


def actions():
    pair = ("2(n-3)", "2/(n-3)")
    return (
        [operation("method", "elimination")]
        + choose("wrong_sign")
        + choose("half_flip")
        + choose("correct")
        + fills("3", "-2")
        + fills("-7", "2")
        + fills("3", "2")
        + choose("unchanged")
        + choose("wrong_constant")
        + choose("fixed_product")
        + choose("from_n")
        + choose("cannot")
        + choose("from_m")
        + fills(*pair)
        + [operation("swap", "product"), operation("submit")]
        + fills(*reversed(pair))
        + fills(*pair)
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q20")
    text = (ROOT / "site/1/q20/index.html").read_text()
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
    assert [n["title"] for n in page["routes"]["elimination"]] == TITLES
    assert set(teacher["initial_state"]["choices"]) == {
        n["interaction"]["field"]
        for n in page["routes"]["elimination"]
        if n["interaction"]["type"] == "choice"
    }
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('class="problem-card" href="/1/q20/"') == 1
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
        session, tutor = Session(load_lesson("q20")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        for stage in (0, 1, 2, 3):
            assert errors.count(stage) == 4
        assert errors.count(4) == 2
        assert set(errors) == {0, 1, 2, 3, 4}
        assert view["state"]["active"] == 7
        assert view["state"]["choices"] == {
            "eliminate_form": "correct",
            "rewrite_form": "fixed_product",
            "positive_basis": "from_m",
        }
        assert view["state"]["pairs"][1] == ["3", "2"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_expansion_check():
    import sympy as sp
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["elimination"][1]
    html = (ROOT / "site/1/q20/index.html").read_text()
    templates = dict(re.findall(r'<template id="([^"]+)">(.*?)</template>', html, re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q20"))
    n = sp.Symbol("n")

    def parse(text):
        return sp.sympify(re.sub(r"(\d)\(", r"\1*(", re.sub(r"(\d)n", r"\1*n", text)), locals={"n": n})

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对展开结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q20"))
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
                            + fills(p, q)
                        ),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["3", "2"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = lines[0].split("=")
                fill = sp.Integer(p) * (n - 3) + sp.Integer(q)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - (3 * n - 7)) != 0
                assert lines[1] == mine + r"\not\equiv 3n-7"

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
        session = Session(load_lesson("q20"))
        turns = [
            ["eliminate_expression"],
            ["denominator_multiple"],
            ["remainder_constant"],
            ["fixed_product_rewrite"],
            ["positive_basis"],
        ]
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
            assert view["state"]["active"] == [1, 1, 2, 3, 4][i]
        assert view["state"]["pairs"][1] == ["3", "2"]
        assert view["state"]["choices"]["positive_basis"] == "from_m"

    asyncio.run(run())
