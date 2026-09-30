"""Q10: degree recognition and scoped multiplication, with static/teacher parity."""

import asyncio
import json
import os
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.contracts import (
    InvalidAction,
    accept_text_answer,
    allowed_actions,
    apply_action,
    validate_answer,
)
from shuxueshuo_server.tutor_demo.llm import Action, Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    text = (ROOT / "site/1/q10/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', text, re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "homogeneous")]
        + pair("1", "-1")
        + pair("-1", "1")
        + pair("whole", "1")
        + pair("first", "x+5y")
        + pair("second", "x+5y")
        + pair("whole", "x+y")
        + pair("whole", "x+5y")
        + pair("25y/x", "4x/y")
        + [operation("swap", "product"), operation("submit")]
        + pair("4x/y", "25y/x")
        + pair("25y/x", "25y/x")
        + pair("25y/x", "4x/y")
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q10")
    text = (ROOT / "site/1/q10/index.html").read_text()
    assert "典例" not in text and "3-1" not in text
    assert len(page["methods"]) == 1
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    for node, expected in zip(
        page["routes"]["homogeneous"],
        teacher["routes"]["homogeneous"]["nodes"],
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
        assert set(node.get("scope_boards", {}).values()) <= templates
        if node.get("board"):
            assert node["board"] in templates
        if node["interaction"]["type"] == "rewrite" and node.get("board"):
            board = re.search(rf'<template id="{node["board"]}">(.*?)</template>', text, re.S).group(1)
            targets = set(re.findall(r'data-rewrite-scope="([^"]+)"', board))
            assert targets == {option["value"] for option in node["interaction"]["slots"][0]["options"]}
    assert (ROOT / "site/1/index.html").read_text().count('href="/1/q10/"') == 1


def test_local_and_server_replay_wrong_scopes_factors_and_restart():
    ops = pending(
        actions() + [operation("switch_route", "homogeneous")] + actions()[1:]
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
        session, tutor = Session(load_lesson("q10")), Tutor()
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
        assert len(view["attempts"]) == 2
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_rewrite_slot_candidate_domains_are_separate():
    lesson = load_lesson("q10")
    node = lesson["routes"]["homogeneous"]["nodes"][1]
    specs = allowed_actions(node)
    assert specs[0]["values"] == ["whole", "first", "second"]
    assert specs[1]["values"] == ["x+5y", "x+y", "1"]
    state = json.loads(json.dumps(lesson["initial_state"]))
    state.update(method="homogeneous", active=1)
    for index, value in [(0, "x+5y"), (1, "whole")]:
        with pytest.raises(InvalidAction):
            apply_action(state, Action(kind="fill", index=index, value=value), lesson)
    state["pairs"][1] = ["whole", "1"]
    with pytest.raises(InvalidAction):
        validate_answer(node, state)
    accept_text_answer(node, state)
    assert state["pairs"][1] == ["whole", "x+5y"]


def test_partial_evidence_does_not_skip_rewrite_or_recognition():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。", intent="answer", evidence=self.evidence, actions=[]
            )

    async def run():
        session = Session(load_lesson("q10"))
        for i, evidence in enumerate(
            [["target_degree"], ["condition_degree"], ["whole_scope"], ["unit_factor"]]
        ):
            view = await session.handle(
                Event(
                    event_id=f"e{i}",
                    revision=session.revision,
                    kind="text",
                    text="本轮证据",
                    lesson_version=1,
                    pending_operations=pending([operation("method", "homogeneous")])
                    if i == 0
                    else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [0, 1, 1, 2][i]
        assert view["state"]["pairs"][1] == ["whole", "x+5y"]

    asyncio.run(run())


def test_dialogue_sync_retry_is_atomic_at_rewrite():
    async def run():
        session, tutor = Session(load_lesson("q10")), Tutor()
        event = Event(
            event_id="question",
            revision=0,
            kind="text",
            text="只给第一项乘这个1，不也相等吗？",
            lesson_version=1,
            pending_operations=pending(
                [operation("method", "homogeneous")]
                + pair("-1", "1")
                + pair("first", "x+5y")
            ),
        )
        before = session.view()
        tutor.fail = True
        with pytest.raises(TutorUnavailable):
            await session.handle(event, tutor)
        assert session.view() == before
        tutor.fail = False
        view = await session.handle(event, tutor)
        assert view["state"]["active"] == 1
        assert view["state"]["pairs"][1] == ["first", "x+5y"]
        assert tutor.calls[-1]["context"]["node"]["id"] == "rewrite"
        count = len(tutor.calls)
        assert await session.handle(event, tutor) == view
        assert len(tutor.calls) == count

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q10_evidence_and_wrong_local_rewrite():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    turns = [
        ("目标是负一次，条件左边是正一次，乘起来为零次", 1),
        ("只给第一项乘x+5y，不也是相等的吗？", 1),
        ("那就只给第一项乘x+5y，这样整个式子都为零次了", 1),
        ("给整个5/x+4/y乘x+5y，因为它等于1", 2),
        ("25y/x与4x/y，定积求和", 3),
        ("25y/x+4x/y≥2√((25y/x)*(4x/y))=20", 4),
        ("x=y就能取等", 4),
        ("25y/x=4x/y时取等，也就是2x=5y", 5),
    ]

    async def run():
        session, tutor = Session(load_lesson("q10")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                        lesson_version=1,
                        pending_operations=pending([operation("method", "homogeneous")])
                        if i == 0
                        else [],
                    ),
                    tutor,
                )
                print(view["state"]["active"], view["messages"][-1]["text"])
                assert view["state"]["active"] == active
        finally:
            await tutor.close()

    asyncio.run(run())
