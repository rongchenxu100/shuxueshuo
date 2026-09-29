"""Q09: real-domain sign cases, scaled AM-GM, and either elimination variable."""

import asyncio
import json
import os
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.llm import TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    html = (ROOT / "site/1/q09/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def choose(value):
    return [operation("choice", value), operation("submit")]


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions(route, variable="a", technique="square", switch=False):
    start = [operation("switch_route" if switch else "method", route)]
    start += choose("swapped") + choose("six") + choose("linear")
    if route == "matching":
        return (
            start
            + choose("positive")
            + choose("negative")
            + choose("split")
            + pair("a", "b")
            + [operation("swap", "product")]
            + pair("2a", "3b")
            + [operation("swap", "sum"), operation("submit")]
            + pair("a", "b")
            + pair("3b", "2a")
            + pair("a", "b")
            + pair("2a", "3b")
        )
    return start + choose(variable) + choose(technique) + choose("no") + choose("yes")


def test_contract_templates_and_primary_route():
    p, t = page_config(), load_lesson("q09")
    html = (ROOT / "site/1/q09/index.html").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    templates = set(re.findall(r'<template id="([^"]+)"', html))
    for key in ("id", "version", "methods"):
        assert p[key] == t[key]
    assert p["methods"][0]["id"] == "matching"
    assert p["completion"] in templates
    for route, nodes in p["routes"].items():
        for n, expected in zip(nodes, t["routes"][route]["nodes"], strict=True):
            for key in (
                "id",
                "title",
                "question",
                "interaction",
                "expected_answer",
                "feedback",
            ):
                assert n[key] == expected[key]
            display = n["display"]
            assert (
                {display}
                if isinstance(display, str)
                else set(display["options"].values())
            ) <= templates
            if n.get("board"):
                assert n["board"] in templates
    assert (ROOT / "site/1/index.html").read_text().count('href="/1/q09/"') == 1


@pytest.mark.parametrize(
    "variable,technique",
    [("a", "square"), ("a", "vertex"), ("b", "square"), ("b", "vertex")],
)
def test_both_routes_match_local_and_server(variable, technique):
    operations = pending(
        actions("matching") + actions("elimination", variable, technique, switch=True)
    )
    script = """
require(process.argv[1]);
const {lesson,operations}=JSON.parse(require('fs').readFileSync(0,'utf8'));
let view=PracticeContext.create(lesson,'start');
console.log(JSON.stringify(operations.map(op=>{view=PracticeContext.apply(view,op,lesson);return view;})));
"""
    local = json.loads(
        subprocess.run(
            ["node", "-e", script, str(ROOT / "site/assets/practice/context.js")],
            input=json.dumps({"lesson": page_config(), "operations": operations}),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    async def run():
        session, tutor = Session(load_lesson("q09")), Tutor()
        errors = []
        for browser, op in zip(local, operations, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append((view["state"]["method"], view["state"]["active"]))
        assert errors.count(("matching", 1)) == 2
        assert (
            ("matching", 2) in errors
            and ("matching", 3) in errors
            and ("matching", 4) in errors
        )
        assert ("elimination", 3) in errors
        assert [(a["route"], a["status"]) for a in view["attempts"]] == [
            ("matching", "completed"),
            ("elimination", "completed"),
        ]
        assert view["state"]["choices"]["variable"] == variable
        assert view["state"]["choices"]["technique"] == technique
        assert not tutor.calls

    asyncio.run(run())


def test_sync_failure_retry_preserves_sign_case_context():
    async def run():
        session, tutor = Session(load_lesson("q09")), Tutor()
        ops = pending([operation("method", "matching")] + choose("linear"))
        event = Event(
            event_id="q09-question",
            revision=0,
            kind="text",
            text="为什么不能直接说都是正数？",
            lesson_version=1,
            pending_operations=ops,
        )
        before = session.view()
        tutor.fail = True
        with pytest.raises(TutorUnavailable):
            await session.handle(event, tutor)
        assert session.view() == before
        tutor.fail = False
        view = await session.handle(event, tutor)
        assert view["state"]["active"] == 1
        assert tutor.calls[-1]["context"]["node"]["id"] == "sign"
        assert "a≠0,b≠0" in tutor.calls[-1]["context"]["completed_results"]
        count = len(tutor.calls)
        assert await session.handle(event, tutor) == view
        assert len(tutor.calls) == count

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
@pytest.mark.parametrize(
    "route,turns",
    [
        (
            "matching",
            [
                ("2a+3b=1", 1),
                ("为什么不能直接说a,b都是正数？", 1),
                ("由和是1可以断定a,b都正", 1),
                ("ab<0时是负数；ab>0时两数同号，和2a+3b是正数，所以都正", 2),
                ("2a和3b定和求积", 3),
                ("1=2a+3b≥2√(6ab)", 4),
                ("a=b取等", 4),
                ("2a=3b取等", 5),
            ],
        ),
        (
            "elimination",
            [
                ("2a+3b=1", 1),
                ("消去a，a=(1-3b)/2", 2),
                ("配方得到1/24-3/2*(b-1/6)^2", 3),
                ("两个数非零，代回原式(4-2)(6-3)=6，满足", 4),
            ],
        ),
    ],
)
def test_live_tutoring(route, turns):
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    async def run():
        session, tutor = Session(load_lesson("q09")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"q09-{i}",
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
