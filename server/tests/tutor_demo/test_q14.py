"""Q14: multiply by the unit condition directly, or substitute t=1/y first."""

import asyncio
import json
import os
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.contracts import allowed_actions
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    text = (ROOT / "site/1/q14/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', text, re.DOTALL)[1]
    )


def fills(*values):
    return [operation("fill", value, i) for i, value in enumerate(values)] + [
        operation("submit")
    ]


def tail(first, second):
    return (
        fills(first, second)
        + [operation("swap", "product"), operation("submit")]
        + fills(second, first)
        + fills(first, first)
        + fills(first, second)
    )


def actions(route, switch=False):
    start = [operation("switch_route" if switch else "method", route)]
    if route == "direct":
        return (
            start
            + fills("first", "1/x+4y")
            + fills("second", "1/x+4y")
            + fills("whole", "1/x+y")
            + fills("whole", "1/x+4y")
            + tail("4xy", "1/(xy)")
        )
    return (
        start
        + fills("x")
        + fills("y")
        + fills("1/y")
        + fills("-1", "1")
        + fills("1", "-1")
        + fills("first", "1/x+4/t")
        + fills("whole", "1/x+1/t")
        + fills("whole", "1/x+4/t")
        + tail("4x/t", "t/x")
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q14")
    text = (ROOT / "site/1/q14/index.html").read_text()
    assert "变式" not in text and "3-1" not in text
    ids = re.findall(r'\bid="([^"]+)"', text)
    assert len(ids) == len(set(ids))
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    assert [m["id"] for m in page["methods"]] == ["direct", "substitution"]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    for route, nodes in page["routes"].items():
        for node, expected in zip(
            nodes, teacher["routes"][route]["nodes"], strict=True
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
            assert set(node.get("scope_boards", {}).values()) <= templates
            if node.get("board"):
                assert node["board"] in templates
            if node["interaction"]["type"] in ("rewrite", "substitution") and node.get(
                "board"
            ):
                board = re.search(
                    rf'<template id="{node["board"]}">(.*?)</template>', text, re.S
                )[1]
                attr = (
                    "rewrite-scope"
                    if node["interaction"]["type"] == "rewrite"
                    else "sub-target"
                )
                targets = re.findall(rf'data-{attr}="([^"]+)"', board)
                assert targets == [
                    o["value"] for o in node["interaction"]["slots"][0]["options"]
                ]
    assert len(teacher["initial_state"]["pairs"]) == 6
    assert (ROOT / "site/1/index.html").read_text().count('class="problem-card" href="/1/q14/"') == 1


def test_substitution_candidates_are_single_targets():
    node = load_lesson("q14")["routes"]["substitution"]["nodes"][0]
    assert allowed_actions(node)[0]["values"] == ["", "x", "1/y", "y"]


def test_both_routes_match_local_and_server():
    ops = pending(actions("direct") + actions("substitution", switch=True))
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
        session, tutor = Session(load_lesson("q14")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append((view["state"]["method"], view["state"]["active"]))
        assert errors.count(("direct", 0)) == 3
        assert {("direct", 1), ("direct", 3)} <= set(errors)
        assert errors.count(("substitution", 0)) == 2
        assert errors.count(("substitution", 1)) == 1
        assert errors.count(("substitution", 2)) == 2
        assert {("substitution", 3), ("substitution", 5)} <= set(errors)
        assert [(a["route"], a["status"]) for a in view["attempts"]] == [
            ("direct", "completed"),
            ("substitution", "completed"),
        ]
        assert not tutor.calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "route,turns,active",
    [
        ("direct", [["whole_scope"], ["unit_factor"]], [0, 1]),
        (
            "substitution",
            [["reciprocal_target"], ["target_degree"], ["condition_degree"]],
            [1, 1, 2],
        ),
    ],
)
def test_evidence_accumulates_across_turns(route, turns, active):
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。", intent="answer", evidence=self.evidence, actions=[]
            )

    async def run():
        session = Session(load_lesson("q14"))
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}",
                    revision=session.revision,
                    kind="text",
                    text="本轮证据",
                    lesson_version=1,
                    pending_operations=pending([operation("method", route)])
                    if i == 0
                    else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == active[i]
        if route == "direct":
            assert view["state"]["pairs"][0] == ["whole", "1/x+4y"]
        else:
            assert view["state"]["pairs"][0][0] == "1/y"
            assert view["state"]["pairs"][1] == ["1", "-1"]

    asyncio.run(run())


def test_every_rewrite_combination_has_authored_calculation():
    page = page_config()
    text = (ROOT / "site/1/q14/index.html").read_text()
    templates = dict(
        re.findall(r'<template id="([^\"]+)">(.*?)</template>', text, re.S)
    )
    for route in page["routes"].values():
        node = next(n for n in route if n["interaction"]["type"] == "rewrite")
        scopes, factors = node["interaction"]["slots"]
        for scope in scopes["options"]:
            for factor in factors["options"]:
                pair = [scope["value"], factor["value"]]
                template = node["attempt_calculations"][pair[0]][pair[1]]
                assert template in templates
                if pair == node["expected_answer"]["terms"]:
                    assert template == node["display"]
                    continue
                html = templates[template]
                math = re.search(
                    r'<div class="rewrite-calculation-math">(.*?)</div>', html, re.S
                )[1]
                lines = re.findall(r"<p data-math-text>(.*?)</p>", math)
                assert len(lines) >= 2
                # The equal sign expands the chosen expression, never equates a
                # possibly invalid candidate to the original problem expression.
                assert lines[0].startswith("$") and not lines[0].startswith("$=")
                assert lines[1].startswith("$=")
                assert not re.search(r"[\u4e00-\u9fff]", math)
                assert 'class="rewrite-calculation-feedback"' in html
    teacher = load_lesson("q14")
    assert "attempt_calculations" not in json.dumps(teacher)


def confirmed_pair(view):
    script = """
require(process.argv[1]);
console.log(JSON.stringify(PracticeContext.confirmedPair(JSON.parse(require('fs').readFileSync(0,'utf8')))));
"""
    return json.loads(
        subprocess.run(
            ["node", "-e", script, str(ROOT / "site/assets/practice/context.js")],
            input=json.dumps(view),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )


def test_calculation_survives_dialogue_but_clears_on_edits_and_route_changes():
    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(
                reply="展开后的两项积为4x，仍随变量变化。",
                intent="question",
                evidence=[],
                actions=[],
            )

    async def run():
        session = Session(load_lesson("q14"))
        tutor = QuestionTutor()
        ops = [operation("method", "direct")] + fills("first", "1/x+4y")
        for i, op in enumerate(ops):
            view = await session.handle(
                Event(
                    event_id=f"ui-{i}", kind="ui", revision=session.revision, action=op
                ),
                tutor,
            )
        assert confirmed_pair(view) == ["first", "1/x+4y"]
        for kind in ["text", "help"]:
            view = await session.handle(
                Event(
                    event_id=kind,
                    kind=kind,
                    text="为什么这样不行？" if kind == "text" else "",
                    revision=session.revision,
                    lesson_version=1,
                    pending_operations=[],
                ),
                tutor,
            )
            assert not view["state"]["feedback"]
            assert confirmed_pair(view) == ["first", "1/x+4y"]
        view = await session.handle(
            Event(
                event_id="edit",
                kind="ui",
                revision=session.revision,
                action=operation("fill", "second", 0),
            ),
            tutor,
        )
        assert confirmed_pair(view) is None
        view = await session.handle(
            Event(
                event_id="edit-back",
                kind="ui",
                revision=session.revision,
                action=operation("fill", "first", 0),
            ),
            tutor,
        )
        assert confirmed_pair(view) is None
        view = await session.handle(
            Event(
                event_id="submit-again",
                kind="ui",
                revision=session.revision,
                action=operation("submit"),
            ),
            tutor,
        )
        assert confirmed_pair(view) == ["first", "1/x+4y"]
        view = await session.handle(
            Event(
                event_id="switch",
                kind="ui",
                revision=session.revision,
                action=operation("switch_route", "substitution"),
            ),
            tutor,
        )
        assert confirmed_pair(view) is None

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
@pytest.mark.parametrize("route", ["direct", "substitution"])
def test_live_q14_dialogue_and_confirmed_calculation(route):
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **kwargs):
            proposal = await super().respond(**kwargs)
            print("proposal: " + proposal.model_dump_json(), flush=True)
            return proposal

    lower_bound = "我对原式用基本不等式得到x+1/y≥2√(x/y)，由x>1、0<y<1/4得到原式>4，这不也是常数下界吗？"
    if route == "direct":
        initial = [operation("method", route)] + fills("first", "1/x+4y")
        turns = [
            ("我只给第一项乘条件表达式，为什么这样不行？请按我的选择展开。", 0),
            ("所以这个改写仍然等价，只是还没有凑出积为定值的两项，对吗？", 0),
            ("先只确定作用范围是整个式子，乘数我还没决定", 0),
            ("乘入1/x+4y，因为它等于1", 1),
            (lower_bound, 1),
            ("4xy与1/(xy)定积求和", 2),
            ("最小值是9", 2),
            ("4xy+1/(xy)≥2√(4xy/(xy))=4", 3),
            ("x=1/y时取等", 3),
            ("xy=1/2时取等", 4),
        ]
        pair = ["first", "1/x+4y"]
    else:
        initial = (
            [operation("method", route)]
            + fills("1/y")
            + fills("1", "-1")
            + fills("first", "1/x+4/t")
        )
        turns = [
            ("我只给第一项乘1/x+4/t，为什么还不齐次？请展开后逐项说明次数。", 2),
            ("那把整个式子乘1/x+1/t，虽然齐次，但是否还等价？", 2),
            ("先只确定作用范围是整个式子，乘数我还没决定", 2),
            ("乘入1/x+4/t，因为它等于1", 3),
            (lower_bound, 3),
            ("4x/t与t/x定积求和", 4),
            ("最小值9", 4),
            ("4x/t+t/x≥2√((4x/t)(t/x))=4", 5),
            ("t=x时取等", 5),
            ("t=2x时取等", 6),
        ]
        pair = ["first", "1/x+4/t"]

    async def run():
        session, tutor = Session(load_lesson("q14")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"{route}-{i}",
                        kind="text",
                        text=text,
                        revision=session.revision,
                        lesson_version=1,
                        pending_operations=pending(initial) if i == 0 else [],
                    ),
                    tutor,
                )
                print(
                    json.dumps(
                        {
                            "route": route,
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
                if i < 2:
                    assert confirmed_pair(view) == pair
                if i == 2:
                    assert "whole_scope" in view["accepted_evidence"]
        finally:
            await tutor.close()

    asyncio.run(run())
