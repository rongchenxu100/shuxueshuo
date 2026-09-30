"""Q19: eliminate b, split the fraction, complete to (a-1)+36/(a-1)+37, then use AM-GM."""

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
    text = (ROOT / "site/1/q19/index.html").read_text()
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
    pair = ("a-1", "36/(a-1)")
    return (
        [operation("method", "elimination")]
        + choose("wrong_sign")
        + choose("flipped")
        + choose("correct")
        + fills("9", "36")
        + fills("36", "-36")
        + fills("36", "36")
        + choose("unchanged")
        + choose("wrong_constant")
        + choose("fixed_product")
        + fills(*pair)
        + [operation("swap", "product"), operation("submit")]
        + fills(*reversed(pair))
        + fills(*pair)
    )


def test_choice_feedback_is_not_repeated_but_identical_dialogue_is_kept():
    script = r"""
const fs = require('fs'), assert = require('assert');
require(process.argv[1]);
const lesson = JSON.parse(fs.readFileSync(0, 'utf8'));
const runtime = fs.readFileSync(process.argv[2], 'utf8');
const code = runtime.slice(runtime.indexOf('  function conversation('), runtime.indexOf('  function acceptSnapshot('));
const render = new Function('lesson', 'snapshot', 'state', 'escapeHTML', 'attempt', code + ';return conversation(0, attempt);');
let view = PracticeContext.create(lesson, 'attempt');
for (const action of [{kind:'method',value:'elimination'}, {kind:'choice',value:'wrong_sign'}, {kind:'submit'}]) {
  view = PracticeContext.apply(view, {action,event_id:JSON.stringify(action)}, lesson);
}
const before = JSON.stringify(view);
assert.strictEqual(render(lesson, view, view.state, String, null), '');
assert.strictEqual(JSON.stringify(view), before); // The model still receives the original Context.
const feedback = lesson.routes.elimination[0].feedback.answer;
view.messages.push({role:'student',kind:'text',text:'为什么？',attempt_id:'attempt',stage:0,route:'elimination'});
view.messages.push({role:'assistant',kind:'text',text:feedback,attempt_id:'attempt',stage:0,route:'elimination'});
let html = render(lesson, view, view.state, String, null);
assert.strictEqual((html.match(/chat-message assistant/g)||[]).length, 1);
assert(html.includes(feedback)); // Identical real replies must not disappear.
const archived = {id:'attempt', route:'elimination', messages:view.messages};
html = render(lesson, view, {...view.state, active:1}, String, archived);
assert.strictEqual((html.match(/chat-message assistant/g)||[]).length, 1);
assert(html.includes('conversation-history'));
"""
    subprocess.run(
        ["node", "-e", script, str(ROOT / "site/assets/practice/context.js"), str(ROOT / "site/assets/practice/runtime.js")],
        input=json.dumps(page_config()), text=True, capture_output=True, check=True,
    )


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q19_wrong_answers_partial_evidence_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **data):
            self.proposal = await super().respond(**data)
            return self.proposal

    turns = [
        ("我选了b=9a/(a+1)，为什么不对？先解释，不要替我改选。", 0),
        ("我也可以消a，得到a=b/(b-9)，是吗？", 0),
        ("b=9a/(a-1)", 1),
        ("我填了36和-36，请按我的实际填写展开，看看哪部分错了，不要替我改。", 1),
        ("倍数是36，常数还没确定", 1),
        ("余下的常数也是36", 2),
        ("直接对a和36/(a-1)用基本不等式不成立吗？", 2),
        ("原式=(a-1)+36/(a-1)+36", 2),
        ("应改成(a-1)+36/(a-1)+37", 3),
        ("是定和求积", 3),
        ("a-1和36/(a-1)，定积求和", 4),
        ("最小值49", 4),
        ("(a-1)+36/(a-1)≥2√36=12，所以a+4b≥49", 5),
        ("a-1=-6，即a=-5时取等", 5),
        ("a=7，b=21/2，满足原条件", 6),
    ]

    async def run():
        session, tutor = Session(load_lesson("q19")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = [operation("method", "elimination")] + choose("wrong_sign") if i == 0 else fills("36", "-36") if i == 3 else []
                view = await session.handle(Event(
                    event_id=f"live-{i}", kind="text", text=text,
                    revision=session.revision, lesson_version=1,
                    pending_operations=[{**op, "event_id": f"live-ui-{i}-{j}"} for j, op in enumerate(pending(ops))],
                ), tutor)
                reply = view["messages"][-1]["text"]
                print(json.dumps({"turn": i + 1, "student": text, "active": view["state"]["active"], "reply": reply, "model_reply": tutor.proposal.reply, "evidence": tutor.proposal.evidence}, ensure_ascii=False), flush=True)
                assert view["state"]["active"] == active
                assert not re.search(r"denominator_multiple|remainder_constant|fixed_product_rewrite|equal_terms|契约", reply)
                assert not re.search(r"\\n(?![A-Za-z])", reply)
                if i in (0, 1, 3, 6):
                    # An alternative route can be classified as "other"; neither
                    # discussion classification may submit an answer or advance.
                    assert tutor.proposal.intent in ("question", "other") and not tutor.proposal.evidence
                if i == 3:
                    assert confirmed_pair(view) == ["36", "-36"]
                    assert "36a-72" in reply.replace(" ", "").replace("−", "-")
                if i == 4:
                    assert "denominator_multiple" in tutor.proposal.evidence
                    assert "remainder_constant" not in tutor.proposal.evidence
                if i == 6:
                    assert re.search("成立|可以|合法", reply)
            assert view["state"]["pairs"][1] == ["36", "36"]
        finally:
            await tutor.close()

    asyncio.run(run())


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q19")
    text = (ROOT / "site/1/q19/index.html").read_text()
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
        "消参", "分式分离", "凑配表达式", "观察和积结构", "应用基本不等式", "验证取等",
    ]
    split = re.search(r'<template id="split-board">(.*?)</template>', text, re.S)[1]
    assert re.findall(r'data-fill="(\d+)"', split) == ["0", "1"]
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('class="problem-card" href="/1/q19/"') == 1
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
        session, tutor = Session(load_lesson("q19")), Tutor()
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
        assert errors.count(2) == 4
        assert errors.count(3) == 2
        assert set(errors) == {0, 1, 2, 3}
        assert view["state"]["active"] == 6
        assert view["state"]["choices"] == {"eliminate_form": "correct", "rewrite_form": "fixed_product"}
        assert view["state"]["pairs"][1] == ["36", "36"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_confirmed_fill_shows_authored_expansion_check():
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["elimination"][1]
    html = (ROOT / "site/1/q19/index.html").read_text()
    templates = dict(re.findall(r'<template id="([^"]+)">(.*?)</template>', html, re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q19"))
    a = sp.Symbol("a")

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
            local_dict={"a": a},
            transformations=standard_transformations
            + (implicit_multiplication_application,),
        )

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对展开结果。", intent="question", evidence=[], actions=[])

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q19"))
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
                if [p, q] == ["36", "36"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, mine = lines[0].split("=")
                fill = sp.Integer(p) * (a - 1) + sp.Integer(q)
                assert sp.expand(parse(left) - fill) == 0
                assert sp.expand(parse(mine) - fill) == 0
                assert sp.expand(fill - 36 * a) != 0
                assert lines[1] == mine + r"\not\equiv 36a"

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
        session = Session(load_lesson("q19"))
        turns = [["eliminate_expression"], ["denominator_multiple"], ["remainder_constant"], ["fixed_product_rewrite"]]
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
            assert view["state"]["active"] == [1, 1, 2, 3][i]
        assert view["state"]["pairs"][1] == ["36", "36"]
        assert view["state"]["choices"]["rewrite_form"] == "fixed_product"

    asyncio.run(run())
