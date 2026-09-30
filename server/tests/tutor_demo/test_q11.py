"""Q11: target substitution, then the Q10 homogeneous chain, with static/teacher parity."""

import asyncio
import copy
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

REPLAY = """
require(process.argv[1]);
const {lesson, operations} = JSON.parse(require('fs').readFileSync(0,'utf8'));
let view=PracticeContext.create(lesson,'start');
console.log(JSON.stringify(operations.map(op=>{view=PracticeContext.apply(view,op,lesson);return view;})));
"""


def page_text():
    return (ROOT / "site/1/q11/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def template(text, name):
    return re.search(rf'<template id="{name}">(.*?)</template>', text, re.S).group(1)


def local_replay(lesson, ops):
    return json.loads(
        subprocess.run(
            ["node", "-e", REPLAY, str(ROOT / "site/assets/practice/context.js")],
            input=json.dumps({"lesson": lesson, "operations": ops}),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def actions():
    return (
        [operation("method", "substitution")]
        + [operation("fill", "a", 0), operation("submit")]
        + [operation("fill", "", 0), operation("fill", "a+1", 0), operation("submit")]
        + pair("1", "-1")
        + pair("-1", "1")
        + pair("whole", "t+b")
        + pair("first", "(t+b)/3")
        + pair("whole", "(t+b)/3")
        + pair("2b/t", "4t/b")
        + [operation("swap", "product"), operation("submit")]
        + pair("4t/b", "2b/t")
        + pair("2b/t", "2b/t")
        + pair("2b/t", "4t/b")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q11"), page_text()
    assert len(page["methods"]) == 1
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
    substitution = page["routes"]["substitution"][0]
    assert set(substitution["scope_boards"]) == {"a+1", "a"}
    assert len(teacher["initial_state"]["pairs"]) == len(page["routes"]["substitution"])
    assert (ROOT / "site/1/index.html").read_text().count('class="problem-card" href="/1/q11/"') == 1


def test_local_and_server_replay_wrong_target_and_restart():
    ops = pending(
        actions() + [operation("switch_route", "substitution")] + actions()[1:]
    )
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q11")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert set(errors) == {0, 1, 2, 3, 5}
        assert view["state"]["active"] == 6
        assert view["state"]["pairs"][0] == ["a+1", ""]
        assert len(view["attempts"]) == 2
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q11_dialogue_and_local_progress():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    turns = [
        ("为什么只令t=a不合适？", 0),
        ("设t=a+1", 1),
        ("目标是负一次", 1),
        ("条件表达式t+b是正一次", 2),
        ("给整个式子乘t+b就相等了", 2),
        ("只给第一项乘(t+b)/3，不也相等吗？", 2),
        ("只给第一项乘(t+b)/3，整个式子就都是零次了", 2),
        ("给整个式子乘t+b，再除以3，保持值不变", 3),
        ("定积求和", 4),
        ("最小值是2+4根号2/3", 4),
        ("2b/t+4t/b≥2√((2b/t)*(4t/b))=4√2", 5),
        ("t=b就能取等", 5),
        ("为什么还要检查t>1？", 5),
        ("2b/t=4t/b时取等，也就是b=√2t", 6),
    ]

    async def run():
        session, tutor = Session(load_lesson("q11")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"q11-live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                        lesson_version=1,
                        pending_operations=pending(
                            [
                                operation("method", "substitution"),
                                operation("fill", "a", 0),
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
                if i == 0:
                    assert view["state"]["pairs"][0] == ["a", ""]
                if i == 2:
                    assert "target_degree" in view["accepted_evidence"]
        finally:
            await tutor.close()

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
@pytest.mark.parametrize(
    "question",
    [
        "只给第一项乘(t+b)/3，请展开并逐项判断次数，这样还和原式相等吗？",
        "只给第二项乘(t+b)/3，请展开并逐项判断次数，为什么还不是零次齐次式？",
        "2b/(3t)和4t/(3b)都有分母，应该都是负一次吧？为什么？",
    ],
)
def test_live_q11_degree_questions(question):
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    async def run():
        session, tutor = Session(load_lesson("q11")), DeepSeekTutor()
        try:
            view = await session.handle(
                Event(
                    event_id="degree-question",
                    revision=0,
                    kind="text",
                    text=question,
                    lesson_version=1,
                    pending_operations=pending(
                        [
                            operation("method", "substitution"),
                            operation("fill", "a+1", 0),
                            operation("submit"),
                        ]
                        + pair("-1", "1")
                    ),
                ),
                tutor,
            )
            print(
                json.dumps(
                    {
                        "student": question,
                        "active": view["state"]["active"],
                        "reply": view["messages"][-1]["text"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            assert view["state"]["active"] == 2
            assert view["state"]["pairs"][2] == ["", ""]
            assert not view["accepted_evidence"]
        finally:
            await tutor.close()

    asyncio.run(run())


def test_single_target_slot_domain():
    lesson = load_lesson("q11")
    node = lesson["routes"]["substitution"]["nodes"][0]
    assert allowed_actions(node)[0]["values"] == ["", "a+1", "a"]
    assert [spec.get("index") for spec in allowed_actions(node)] == [0, None]
    state = copy.deepcopy(lesson["initial_state"])
    state.update(method="substitution")
    for index, value in [(0, "a+1|a"), (0, "t"), (1, "a+1")]:
        with pytest.raises(InvalidAction):
            apply_action(state, Action(kind="fill", index=index, value=value), lesson)
    state["pairs"][0] = ["a", ""]
    with pytest.raises(InvalidAction):
        validate_answer(node, state)
    accept_text_answer(node, state)
    assert state["pairs"][0] == ["a+1", ""]


def two_target_lessons():
    """A synthetic two-substitution node: t and u may be chosen together, in option order."""
    slot = {
        "label": "换元对象",
        "names": ["t", "u"],
        "options": [{"value": v, "label": v} for v in ("a+1", "b+2", "a")],
    }
    page, teacher = page_config(), load_lesson("q11")
    for node in (
        page["routes"]["substitution"][0],
        teacher["routes"]["substitution"]["nodes"][0],
    ):
        node["interaction"]["slots"] = [copy.deepcopy(slot)]
        node["expected_answer"] = {"terms": ["a+1|b+2"]}
    return page, teacher


def test_two_targets_are_canonical_on_both_sides():
    page, teacher = two_target_lessons()
    node = teacher["routes"]["substitution"]["nodes"][0]
    values = allowed_actions(node)[0]["values"]
    assert "a+1|b+2" in values and "b+2|a+1" not in values
    assert "a+1|b+2|a" not in values
    ops = pending(
        [operation("method", "substitution")]
        + [operation("fill", v, 0) for v in ("b+2|a+1", "a+1|b+2|a", "a+1")]
        + [operation("submit"), operation("fill", "a+1|b+2", 0), operation("submit")]
    )
    local = local_replay(page, ops)

    async def run():
        session = Session(teacher)
        results = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), Tutor()
            )
            for key in ("active", "pairs", "method"):
                assert view["state"][key] == browser["state"][key]
            assert bool(view["state"]["feedback"]) == bool(browser["state"]["feedback"])
            results.append(
                (
                    view["state"]["active"],
                    view["state"]["pairs"][0][0],
                    bool(view["state"]["feedback"]),
                )
            )
        assert results == [
            (0, "", False),
            (0, "", True),
            (0, "", True),
            (0, "a+1", False),
            (0, "a+1", True),
            (0, "a+1|b+2", False),
            (1, "a+1|b+2", False),
        ]

    asyncio.run(run())


def test_substitution_evidence_binds_target_then_advances():
    class EvidenceTutor:
        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。",
                intent="answer",
                evidence=["substitution_target"],
                actions=[],
            )

    async def run():
        session = Session(load_lesson("q11"))
        view = await session.handle(
            Event(
                event_id="e0",
                revision=0,
                kind="text",
                text="设t=a+1",
                lesson_version=1,
                pending_operations=pending([operation("method", "substitution")]),
            ),
            EvidenceTutor(),
        )
        assert view["state"]["active"] == 1
        assert view["state"]["pairs"][0] == ["a+1", ""]

    asyncio.run(run())
