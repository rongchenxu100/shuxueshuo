"""Q12: both denominators are substituted, then the homogeneous chain; static/teacher parity."""

import asyncio
import json
import os
import re

import pytest

from shuxueshuo_server.tutor_demo.contracts import allowed_actions
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay, template


def page_text():
    return (ROOT / "site/1/q12/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "substitution")]
        + [operation("fill", "2m+1", 0), operation("submit")]
        + [operation("fill", "n+1", 0), operation("submit")]
        + [operation("fill", "2m+1|n+1", 0), operation("submit")]
        + pair("1", "-1")
        + pair("-1", "1")
        + pair("whole", "x+y")
        + pair("second", "(x+y)/8")
        + pair("whole", "(x+y)/8")
        + pair("y/x", "x/y")
        + [operation("swap", "product"), operation("submit")]
        + pair("x/y", "y/x")
        + pair("y/x", "y/x")
        + pair("y/x", "x/y")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q12"), page_text()
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    for node, expected in zip(
        page["routes"]["substitution"],
        teacher["routes"]["substitution"]["nodes"],
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
        marker = {
            "substitution": "data-sub-target",
            "rewrite": "data-rewrite-scope",
        }.get(node["interaction"]["type"])
        if marker:
            board = template(text, node["board"])
            targets = set(re.findall(rf'{marker}="([^"]+)"', board))
            assert targets == {
                o["value"] for o in node["interaction"]["slots"][0]["options"]
            }
    substitution = teacher["routes"]["substitution"]["nodes"][0]
    combos = [v for v in allowed_actions(substitution)[0]["values"] if v]
    assert combos == ["2m+1", "n+1", "2m+1|n+1"]
    assert set(page["routes"]["substitution"][0]["scope_boards"]) == set(combos)
    assert len(teacher["initial_state"]["pairs"]) == len(page["routes"]["substitution"])
    assert (ROOT / "site/1/index.html").read_text().count('href="/1/q12/"') == 1


def test_local_and_server_replay_single_substitutions_fail():
    ops = pending(
        actions() + [operation("switch_route", "substitution")] + actions()[1:]
    )
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q12")), Tutor()
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
        assert set(errors) == {0, 1, 2, 3, 5}
        assert view["state"]["active"] == 6
        assert view["state"]["pairs"][0] == ["2m+1|n+1", ""]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_denominator_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。", intent="answer", evidence=self.evidence, actions=[]
            )

    async def run():
        session = Session(load_lesson("q12"))
        for i, evidence in enumerate(
            [["first_denominator_target"], ["second_denominator_target"]]
        ):
            view = await session.handle(
                Event(
                    event_id=f"e{i}",
                    revision=session.revision,
                    kind="text",
                    text="本轮证据",
                    lesson_version=1,
                    pending_operations=pending([operation("method", "substitution")])
                    if i == 0
                    else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == i
        assert view["state"]["pairs"][0] == ["2m+1|n+1", ""]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q12_dialogue_and_local_progress():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **kwargs):
            proposal = await super().respond(**kwargs)
            print("proposal: " + proposal.model_dump_json(), flush=True)
            return proposal

    turns = [
        ("从2m+n=6得到(2m+1)+(n+1)=8，是等式两边各加1吗？", 0),
        ("设x=2m+1", 0),
        ("另一个分母设y=n+1", 1),
        ("目标负一次，条件表达式x+y正一次", 2),
        ("给整个式子乘x+y就保持相等了", 2),
        ("只给第二项乘(x+y)/8不也相等吗？请展开并判断每项次数", 2),
        ("这样只乘第二项，整个式子都是零次了", 2),
        ("给整个1/x+1/y乘x+y再除以8", 3),
        ("y/x和x/y定积求和", 4),
        ("最小值是1/2", 4),
        ("y/x+x/y≥2√((y/x)*(x/y))=2", 5),
        ("m=n时取等", 5),
        ("为什么新变量要满足x>1和y>1？", 5),
        ("x=y时取等", 6),
    ]

    async def run():
        session, tutor = Session(load_lesson("q12")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"q12-live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                        lesson_version=1,
                        pending_operations=pending(
                            [
                                operation("method", "substitution"),
                                operation("fill", "n+1", 0),
                                operation("submit"),
                            ]
                        )
                        if i == 0
                        else [],
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
                if i == 1:
                    assert "first_denominator_target" in view["accepted_evidence"]
        finally:
            await tutor.close()

    asyncio.run(run())
