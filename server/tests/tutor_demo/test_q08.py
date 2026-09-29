"""Q08: independent symmetry judgments, ordered substitution, and both routes."""

import asyncio
import json
import os
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.contracts import (
    InvalidAction,
    accept_text_answer,
    validate_answer,
)
from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    html = (ROOT / "site/1/q08/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions(route, switch=False):
    start = [operation("switch_route" if switch else "method", route)]
    if route == "matching":
        start += [
            operation("choice", "plus_six"),
            operation("submit"),
            operation("choice", "minus_four"),
            operation("submit"),
            operation("choice", "plus_four"),
            operation("submit"),
        ]
        a, b = "x+y", "4/(x+y)"
    else:
        start += pair("unchanged", "changed") + pair("unchanged", "unchanged")
        start += pair("xy", "x+y") + pair("x+y", "x-y") + pair("x+y", "xy")
        a, b = "s", "4/s"
    return (
        start
        + pair(a, b)
        + [operation("swap", "product"), operation("submit")]
        + pair(b, a)
        + pair(a, a)
        + pair(b, a)
    )


def test_page_teacher_contract_and_templates_agree():
    page, teacher = page_config(), load_lesson("q08")
    html = (ROOT / "site/1/q08/index.html").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    fixed_ids = [i for i in ids if "{{uid}}" not in i]
    assert len(fixed_ids) == len(set(fixed_ids))
    templates = set(re.findall(r'<template id="([^"]+)"', html))
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    assert set(page["routes"]) == set(teacher["routes"]) == {"matching", "symmetric"}
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
            assert set(node.get("preview", {}).values()) <= templates
            if node.get("board"):
                assert node["board"] in templates
    assert (ROOT / "site/1/index.html").read_text().count('href="/1/q08/"') == 1


def test_local_and_server_replay_errors_and_switch_preserve_completed_attempt():
    ops = pending(actions("matching") + actions("symmetric", switch=True))
    script = """
require(process.argv[1]);
const {lesson, operations} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let view = PracticeContext.create(lesson, 'start');
console.log(JSON.stringify(operations.map(operation => {
  view = PracticeContext.apply(view, operation, lesson); return view;
})));
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
        session, tutor = Session(load_lesson("q08")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append((view["state"]["method"], view["state"]["active"]))
        assert not tutor.calls
        assert ("symmetric", 0) in errors
        assert errors.count(("symmetric", 1)) == 2
        assert view["state"]["active"] == 5
        assert [(a["route"], a["status"]) for a in view["attempts"]] == [
            ("matching", "completed"),
            ("symmetric", "completed"),
        ]

    asyncio.run(run())


def test_ordered_substitution_is_preserved_when_accepting_text():
    lesson = load_lesson("q08")
    state = lesson["initial_state"]
    state.update(method="symmetric", active=1)
    node = lesson["routes"]["symmetric"]["nodes"][1]
    state["pairs"][1] = ["xy", "x+y"]
    with pytest.raises(InvalidAction):
        validate_answer(node, state)
    accept_text_answer(node, state)
    assert state["pairs"][1] == ["x+y", "xy"]
    validate_answer(node, state)


def test_partial_symmetry_evidence_and_atomic_dialogue_sync():
    class EvidenceTutor(Tutor):
        def __init__(self):
            super().__init__()
            self.evidence = ["symmetric_condition"]

        async def respond(self, **kwargs):
            await super().respond(**kwargs)
            return Proposal(
                reply="判断已记录。",
                intent="answer",
                evidence=self.evidence,
                actions=[],
            )

    async def run():
        session, tutor = Session(load_lesson("q08")), EvidenceTutor()
        event = Event(
            event_id="q08-chat",
            revision=0,
            kind="text",
            text="xy=yx，条件没变",
            lesson_version=1,
            pending_operations=pending([operation("method", "symmetric")]),
        )
        before = session.view()
        tutor.fail = True
        with pytest.raises(TutorUnavailable):
            await session.handle(event, tutor)
        assert session.view() == before
        tutor.fail = False
        view = await session.handle(event, tutor)
        assert view["state"]["active"] == 0
        assert tutor.calls[-1]["context"]["node"]["id"] == "symmetry"
        calls = len(tutor.calls)
        assert await session.handle(event, tutor) == view
        assert len(tutor.calls) == calls
        tutor.evidence = ["symmetric_target"]
        view = await session.handle(
            Event(
                event_id="target",
                revision=session.revision,
                kind="text",
                text="目标也不变",
            ),
            tutor,
        )
        assert view["state"]["active"] == 1
        assert not view["accepted_evidence"]
        assert "？" not in view["messages"][-1]["text"]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
@pytest.mark.parametrize(
    "route,turns",
    [
        (
            "symmetric",
            [
                ("为什么要交换变量？", 0),
                ("答案是4", 0),
                ("交换后xy=yx，条件不变", 0),
                ("目标也不变", 1),
                ("s=xy，p=x+y", 1),
                ("s=x+y，p=xy", 2),
                ("s和4/s定积求和", 3),
                ("s+4/s≥2√4=4", 4),
                ("s=4/s", 5),
            ],
        ),
        (
            "matching",
            [
                ("x+y+6/(x+y)", 0),
                ("x+y+4/(x+y)", 1),
                ("定和求积", 1),
                ("定积求和", 2),
                ("分子至少8，分母至少2，所以商至少4", 2),
                ("(x+y)+4/(x+y)≥2√4=4", 3),
                ("x+y=4/(x+y)", 4),
            ],
        ),
    ],
)
def test_live_tutoring_new_contracts(route, turns):
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    async def run():
        session, tutor = Session(load_lesson("q08")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"q08-live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                        lesson_version=1,
                        pending_operations=pending([operation("method", route)])
                        if i == 0
                        else [],
                    ),
                    tutor,
                )
                print(route, view["state"]["active"], view["messages"][-1]["text"])
                assert view["state"]["active"] == active
        finally:
            await tutor.close()

    asyncio.run(run())
