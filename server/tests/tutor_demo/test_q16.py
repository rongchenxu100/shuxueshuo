"""Q16: eliminate x, split the fraction by the denominator, then pair y+1 with 9/(y+1)."""

import asyncio
import json
import os

import pytest
import re
import subprocess

from shuxueshuo_server.tutor_demo.contracts import (
    InvalidAction,
    allowed_actions,
    apply_action,
)
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Action, Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    text = (ROOT / "site/1/q16/index.html").read_text()
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
    pair = ("y+1", "9/(y+1)")
    return (
        [operation("method", "elimination")]
        + choose("missing_one")
        + choose("correct")
        + fills("2", "5")
        + fills("-2", "7")
        + fills("-2", "9")
        + choose("unchanged")
        + choose("wrong_constant")
        + choose("fixed_product")
        + fills(*pair)
        + [operation("swap", "product"), operation("submit")]
        + fills(*reversed(pair))
        + fills(*pair)
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q16")
    text = (ROOT / "site/1/q16/index.html").read_text()
    assert "典例" not in text and "4-1" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    for node, expected in zip(
        page["routes"]["elimination"],
        teacher["routes"]["elimination"]["nodes"],
        strict=True,
    ):
        for key in (
            "id",
            "title",
            "question",
            "interaction",
            "expected_answer",
            "feedback",
        ):
            assert node[key] == expected[key]
        assert node["display"] in templates
        assert set(node.get("preview", {}).values()) <= templates
        if node["interaction"]["type"] == "choice":
            options = {o["value"] for o in node["interaction"]["options"]}
            assert set(node.get("preview", {})) == options
        if node.get("board"):
            assert node["board"] in templates
    assert [n["title"] for n in page["routes"]["elimination"]][:3] == [
        "消参",
        "分式分离",
        "凑配表达式",
    ]
    split = re.search(r'<template id="split-board">(.*?)</template>', text, re.S)[1]
    assert re.findall(r'data-fill="(\d+)"', split) == ["0", "1"]
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('class="problem-card" href="/1/q16/"') == 1
    assert "消参法求最值" in home and "条件消元" not in home


def test_fill_component_is_ordered():
    node = load_lesson("q16")["routes"]["elimination"]["nodes"][1]
    specs = allowed_actions(node)
    assert [s["index"] for s in specs[:2]] == [0, 1]
    assert specs[0]["values"] == ["-2", "2", "5", "7", "9"]
    lesson = load_lesson("q16")
    state = json.loads(json.dumps(lesson["initial_state"]))
    state.update(method="elimination", active=1)
    for index, value in enumerate(("9", "-2")):
        apply_action(state, Action(kind="fill", index=index, value=value), lesson)
    try:
        apply_action(state, Action(kind="submit"), lesson)
    except InvalidAction:
        pass
    else:
        raise AssertionError("swapped fill answers must not pass")
    try:
        apply_action(state, Action(kind="fill", index=2, value="9"), lesson)
    except InvalidAction:
        pass
    else:
        raise AssertionError("fill index beyond slot labels must be rejected")


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
        session, tutor = Session(load_lesson("q16")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert errors.count(0) == 2
        assert errors.count(1) == 4
        assert errors.count(2) == 4
        assert errors.count(3) == 2
        assert set(errors) == {0, 1, 2, 3}
        assert view["state"]["active"] == 6
        assert view["state"]["choices"] == {
            "eliminate_form": "correct",
            "rewrite_form": "fixed_product",
        }
        assert view["state"]["pairs"][1] == ["-2", "9"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

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
        session = Session(load_lesson("q16"))
        turns = [
            ["eliminate_expression"],
            ["denominator_multiple"],
            ["remainder_constant"],
            ["fixed_product_rewrite"],
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
            assert view["state"]["active"] == [1, 1, 2, 3][i]
        assert view["state"]["pairs"][1] == ["-2", "9"]
        assert view["state"]["choices"] == {
            "eliminate_form": "correct",
            "rewrite_form": "fixed_product",
        }

    asyncio.run(run())


def test_fill_calculations_cover_all_pairs_and_survive_questions():
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        parse_expr,
        standard_transformations,
        implicit_multiplication_application,
    )
    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["elimination"][1]
    html = (ROOT / "site/1/q16/index.html").read_text()
    templates = dict(re.findall(r'<template id="([^"]+)">(.*?)</template>', html, re.S))
    assert r"\stackrel{?}{=}" in templates["split-board"]
    assert "attempt_calculations" not in json.dumps(load_lesson("q16"))
    y = sp.Symbol("y")

    def parse(text):
        return parse_expr(
            text,
            local_dict={"y": y},
            transformations=standard_transformations
            + (implicit_multiplication_application,),
        )

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(
                reply="先核对所填表达式的展开。",
                intent="question",
                evidence=[],
                actions=[],
            )

    async def run():
        for a in node["interaction"]["terms"]:
            for b in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][a][b]
                block = templates[tid]
                session = Session(load_lesson("q16"))
                view = await session.handle(
                    Event(
                        event_id="ask",
                        kind="text",
                        text="这个展开对吗？",
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
                if [a, b] == ["-2", "9"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [a, b]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", block)
                left, right = lines[0].split("=")
                assert sp.expand(parse(left) - (int(a) * (y + 1) + int(b))) == 0
                assert sp.expand(parse(left) - parse(right)) == 0
                assert sp.expand(parse(right) - (7 - 2 * y)) != 0
                assert lines[1] == right + r"\not\equiv 7-2y"
                for index, value in enumerate(["9" if b != "9" else "7", b]):
                    view = await session.handle(
                        Event(
                            event_id=f"edit-{index}",
                            kind="ui",
                            revision=session.revision,
                            action=operation("fill", value, 1),
                        ),
                        QuestionTutor(),
                    )
                    assert confirmed_pair(view) is None

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q16_fraction_questions_and_complete_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    turns = [
        ("为什么分母不是y，而是y+1？", 0),
        ("x=(7+2y)/(y+1)", 0),
        ("x=(7-2y)/(y+1)", 1),
        ("我刚才填了2和5，请展开我的选择，告诉我哪一部分不对，先不要代我改答案。", 1),
        (
            "分子次数低于分母时，是不是一律先取倒数，再当成原式求最小值？比如1/(y^2+1)。",
            1,
        ),
        (
            "如果分母是y^2+1，可以令t=y+1然后直接逐项除以t吗？另外(y^2+2)/(y^2+1)是不是也能分离？",
            1,
        ),
        ("我确定倍数是-2，常数还没想好", 1),
        ("余下的常数是9", 2),
        ("直接给y和9/(y+1)用基本不等式是不是违法了？", 2),
        ("令t=y+1，原式等于t+9/t-3", 3),
        ("是定和求积", 3),
        ("y+1和9/(y+1)，定积求和", 4),
        ("最小值3", 4),
        ("(y+1)+9/(y+1)≥6，因此x+y≥3", 5),
        ("y+1=-3，所以y=-4取等", 5),
        ("y=2，x=1，满足正数条件和原方程，和是3", 6),
    ]

    async def run():
        session, tutor = Session(load_lesson("q16")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = (
                    [operation("method", "elimination")]
                    if i == 0
                    else fills("2", "5")
                    if i == 3
                    else []
                )
                view = await session.handle(
                    Event(
                        event_id=f"live-{i}",
                        kind="text",
                        text=text,
                        revision=session.revision,
                        lesson_version=1,
                        pending_operations=[
                            {**op, "event_id": f"live-ui-{i}-{j}"}
                            for j, op in enumerate(pending(ops))
                        ],
                    ),
                    tutor,
                )
                print(
                    json.dumps(
                        {
                            "turn": i + 1,
                            "student": text,
                            "active": view["state"]["active"],
                            "reply": view["messages"][-1]["text"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                assert view["state"]["active"] == active
                assert not re.search(r"denominator_multiple|remainder_constant|fixed_product_rewrite|equal_terms|契约", view["messages"][-1]["text"])
                if i == 3:
                    reply = view["messages"][-1]["text"]
                    compact = re.sub(r"\s|\\(?:left|right)", "", reply)
                    assert "2y+7" in compact
                    assert "-2(y+1)+5" not in compact and "-2y+3" not in compact
                if i in (3, 4, 5):
                    assert confirmed_pair(view) == ["2", "5"]
            assert view["state"]["pairs"][1] == ["-2", "9"]
        finally:
            await tutor.close()

    asyncio.run(run())


def test_teacher_contract_exposes_actual_fill_values():
    from shuxueshuo_server.tutor_demo.contracts import node_contract

    lesson = load_lesson("q16")
    state = json.loads(json.dumps(lesson["initial_state"]))
    state.update(method="elimination", active=1)
    state["pairs"][1] = ["2", "5"]
    contract = node_contract(lesson["routes"]["elimination"]["nodes"][1], state)
    assert contract["current_inputs"] == [
        {"index": 0, "label": "分母的倍数", "value": "2"},
        {"index": 1, "label": "余下的常数", "value": "5"},
    ]
    assert contract["expected_answer"]["terms"] == ["-2", "9"]
