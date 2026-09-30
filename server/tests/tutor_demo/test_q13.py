"""Q13: three-slot degree recognition and a single-term unit factor."""

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
from shuxueshuo_server.tutor_demo.llm import Action, Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    text = (ROOT / "site/1/q13/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', text, re.DOTALL)[1]
    )


def fills(*values):
    return [operation("fill", value, i) for i, value in enumerate(values)] + [
        operation("submit")
    ]


def actions():
    return (
        [operation("method", "homogeneous")]
        + fills("-1", "-1", "1")
        + fills("-1", "0", "1")
        + fills("whole", "2a+b")
        + fills("second", "2a+b")
        + fills("first", "a+b")
        + fills("first", "1")
        + fills("first", "2a+b")
        + fills("b/a", "a/b")
        + [operation("swap", "product"), operation("submit")]
        + fills("a/b", "b/a")
        + fills("b/a", "b/a")
        + fills("b/a", "a/b")
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q13")
    text = (ROOT / "site/1/q13/index.html").read_text()
    assert "典例" not in text and "3-5" not in text
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
    homogeneity = page["routes"]["homogeneous"][0]
    board = re.search(r'<template id="degree-board">(.*?)</template>', text, re.S)[1]
    assert re.findall(r'data-degree="(\d)"', board) == ["0", "1", "2"]
    assert len(homogeneity["interaction"]["slot_labels"]) == 3
    assert (ROOT / "site/1/index.html").read_text().count('class="problem-card" href="/1/q13/"') == 1


def test_local_and_server_replay_three_degrees_and_wrong_scopes():
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
        session, tutor = Session(load_lesson("q13")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert errors.count(1) == 8
        assert set(errors) == {0, 1, 2, 4}
        assert view["state"]["active"] == 5
        assert view["state"]["pairs"][0] == ["-1", "0", "1"]
        assert len(view["attempts"]) == 2
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_slot_count_follows_slot_labels():
    lesson = load_lesson("q13")
    homogeneity, rewrite = lesson["routes"]["homogeneous"]["nodes"][:2]
    assert [spec.get("index") for spec in allowed_actions(homogeneity)] == [
        0,
        1,
        2,
        None,
    ]
    state = json.loads(json.dumps(lesson["initial_state"]))
    state["method"] = "homogeneous"
    with pytest.raises(InvalidAction):
        apply_action(state, Action(kind="fill", index=3, value="0"), lesson)
    state["pairs"][0] = ["-1", "0"]
    with pytest.raises(InvalidAction):
        validate_answer(homogeneity, state)
    accept_text_answer(homogeneity, state)
    assert state["pairs"][0] == ["-1", "0", "1"]
    state["active"] = 1
    with pytest.raises(InvalidAction):
        apply_action(state, Action(kind="fill", index=2, value="2a+b"), lesson)
    assert [spec["values"] for spec in allowed_actions(rewrite)[:2]] == [
        ["whole", "first", "second"],
        ["2a+b", "a+b", "1"],
    ]


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。", intent="answer", evidence=self.evidence, actions=[]
            )

    async def run():
        session = Session(load_lesson("q13"))
        turns = [
            ["first_term_degree"],
            ["second_term_degree"],
            ["condition_degree"],
            ["first_scope"],
            ["unit_factor"],
        ]
        for i, evidence in enumerate(turns):
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
            assert view["state"]["active"] == [0, 0, 1, 1, 2][i]
        assert view["state"]["pairs"][0] == ["-1", "0", "1"]
        assert view["state"]["pairs"][1] == ["first", "2a+b"]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q13_partial_homogeneity_and_valid_lower_bound():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **kwargs):
            proposal = await super().respond(**kwargs)
            print("proposal: " + proposal.model_dump_json(), flush=True)
            return proposal

    turns = [
        ("a/b有分母，为什么不是负一次？", 0),
        ("第一项1/a是负一次", 0),
        ("第二项a/b是零次", 0),
        ("条件表达式2a+b是正一次", 1),
        (
            "我直接用基本不等式得到原式≥2/√b，又因为0<b<1，所以原式>2。这不也是常数下界吗？",
            1,
        ),
        ("整个式子乘2a+b不也相等吗？请展开并判断各项次数。", 1),
        ("只给第一项乘a+b，就既保持值又配成零次了", 1),
        ("作用范围选第一项1/a", 1),
        ("乘入2a+b，因为它等于1", 2),
        ("b/a和a/b是定和求积", 2),
        ("应该是b/a和a/b定积求和", 3),
        ("最小值是4", 3),
        ("b/a+a/b≥2√((b/a)(a/b))=2", 4),
        ("1/a=a/b时取等", 4),
        ("a=-b时取等", 4),
        ("a=b时取等", 5),
    ]

    async def run():
        session, tutor = Session(load_lesson("q13")), RecordingTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"q13-live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                        lesson_version=1,
                        pending_operations=pending(
                            [operation("method", "homogeneous")]
                            + fills("-1", "-1", "1")
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
                    assert view["accepted_evidence"] == ["first_term_degree"]
                if i == 2:
                    assert set(view["accepted_evidence"]) == {
                        "first_term_degree",
                        "second_term_degree",
                    }
                if i == 7:
                    assert view["accepted_evidence"] == ["first_scope"]
        finally:
            await tutor.close()

    asyncio.run(run())
