"""Q06: constant-preserving rewrite, static errors and on-demand synchronization."""

import asyncio
import json
import os
import re
import subprocess

import pytest
from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    html = (ROOT / "site/1/q06/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def actions():
    return [
        operation("method", "matching"),
        operation("choice", "missing_constant"),
        operation("submit"),
        operation("choice", "wrong_constant"),
        operation("submit"),
        operation("choice", "fixed_product"),
        operation("submit"),
        operation("fill", "2(x-1)", 0),
        operation("fill", "2/(x-1)", 1),
        operation("submit"),  # Incorrect fixed-sum choice stays on structure.
        operation("swap", "product"),
        operation("fill", "2/(x-1)", 0),
        operation("fill", "2(x-1)", 1),
        operation("submit"),  # Reversed pair, correct fixed product.
        operation("fill", "2(x-1)", 0),
        operation("fill", "2(x-1)", 1),
        operation("submit"),
        operation("fill", "2/(x-1)", 0),
        operation("submit"),  # Reversed pair is accepted.
        operation("fill", "2/(x-1)", 0),
        operation("fill", "2/(x-1)", 1),
        operation("submit"),
        operation("fill", "2(x-1)", 1),
        operation("submit"),
    ]


def test_page_teacher_and_templates_agree():
    page, teacher = page_config(), load_lesson("q06")
    html = (ROOT / "site/1/q06/index.html").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    templates = set(re.findall(r'<template id="([^"]+)"', html))
    assert page["completion"] in templates
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    assert set(page["routes"]) == set(teacher["routes"]) == {"matching"}
    for student, tutor in zip(
        page["routes"]["matching"], teacher["routes"]["matching"]["nodes"], strict=True
    ):
        for key in (
            "id",
            "title",
            "question",
            "interaction",
            "expected_answer",
            "feedback",
        ):
            assert student[key] == tutor[key]
        assert student["display"] in templates
        assert set(student.get("preview", {}).values()) <= templates
        if student.get("board"):
            assert student["board"] in templates
        assert set(student["interaction"].get("term_labels", {})) <= set(
            student["interaction"].get("terms", [])
        )
    assert len(page["routes"]["matching"]) == 4
    assert page["routes"]["matching"][0]["title"] == "凑配表达式"
    amgm = page["routes"]["matching"][2]["interaction"]
    assert amgm["terms"] == ["2(x-1)", "2/(x-1)"]
    assert "/1/q06/" in (ROOT / "site/1/index.html").read_text()


def test_local_and_server_states_match_with_errors_and_reversed_terms():
    script = """
require(process.argv[1]);
const {lesson, operations} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let view = PracticeContext.create(lesson, 'start');
console.log(JSON.stringify(operations.map(operation => {
  view = PracticeContext.apply(view, operation, lesson); return view;
})));
"""
    operations = pending(actions())
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
        session, tutor = Session(load_lesson("q06")), Tutor()
        for browser, op in zip(local, operations, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
        assert not tutor.calls
        assert local[2]["state"]["active"] == local[4]["state"]["active"] == 0
        assert local[9]["state"]["active"] == 1
        assert local[16]["state"]["active"] == 2
        assert local[21]["state"]["active"] == 3
        assert view["state"]["active"] == 4
        assert view["attempts"][-1]["status"] == "completed"
        assert view["state"]["pairs"][3] == ["2/(x-1)", "2(x-1)"]

    asyncio.run(run())


def test_dialogue_sync_is_atomic_and_retry_does_not_duplicate_progress():
    async def run():
        session, tutor = Session(load_lesson("q06")), Tutor()
        event = Event(
            event_id="q06-chat",
            revision=0,
            kind="text",
            text="为什么取等时要让这两项相等？",
            lesson_version=2,
            pending_operations=pending(actions()[:19]),
        )
        before = session.view()
        tutor.fail = True
        with pytest.raises(TutorUnavailable):
            await session.handle(event, tutor)
        assert session.view() == before
        tutor.fail = False
        view = await session.handle(event, tutor)
        context = tutor.calls[-1]["context"]
        assert context["node"]["id"] == "equality"
        assert context["node"]["expected_answer"]["terms"] == ["2(x-1)", "2/(x-1)"]
        assert len(tutor.calls[-1]["completed"]) == 3
        assert context["completed_results"]
        calls = len(tutor.calls)
        assert await session.handle(event, tutor) == view
        assert len(tutor.calls) == calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "stage,inputs",
    [
        (
            0,
            [
                ([], "用基本不等式"),
                ([], "答案6"),
                ([], "2(x-1)+2/(x-1)"),
                (["fixed_product_rewrite"], "2(x-1)+2/(x-1)+2"),
            ],
        ),
        (
            1,
            [
                ([], "两项都为正"),
                ([], "定和求积"),
                (["fixed_product_structure"], "这两项定积求和"),
            ],
        ),
        (2, [([], "答案6"), (["amgm_relation"], "2(x-1)+2/(x-1)≥4")]),
        (3, [([], "x=0"), ([], "为什么相等？"), (["equal_terms"], "x-1=1/(x-1)")]),
    ],
)
def test_evidence_gates_only_complete_current_node(stage, inputs):
    """Stub proposals verify evidence gating, not model understanding."""

    class ContractTutor:
        proposal = None

        async def respond(self, **kwargs):
            return self.proposal

    async def run():
        session, tutor = Session(load_lesson("q06")), ContractTutor()
        session.state.update(method="matching", active=stage)
        for i, (evidence, text) in enumerate(inputs):
            tutor.proposal = Proposal(
                reply="继续问下一步？", intent="answer", evidence=evidence, actions=[]
            )
            view = await session.handle(
                Event(
                    event_id=str(i), revision=session.revision, kind="text", text=text
                ),
                tutor,
            )
            if i < len(inputs) - 1:
                assert view["state"]["active"] == stage
            else:
                assert view["state"]["active"] == stage + 1
                assert (
                    view["messages"][-1]["text"]
                    == session.lesson["routes"]["matching"]["nodes"][stage][
                        "completion_reply"
                    ]
                )
                assert "？" not in view["messages"][-1]["text"]

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(
    os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live-test opt-in required"
)
def test_live_structure_after_local_rewrite():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    async def run():
        session, tutor = Session(load_lesson("q06")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(
                [
                    ("我选的这两项是定和求积", 1),
                    ("应该是定积求和，2(x-1)与2/(x-1)的积是4", 2),
                    ("2(x-1)+2/(x-1)≥2√4=4", 3),
                    ("x-1=1/(x-1)时取等", 4),
                ]
            ):
                view = await session.handle(
                    Event(
                        event_id=f"q06-v2-live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                        lesson_version=2,
                        pending_operations=pending(actions()[:7]) if i == 0 else [],
                    ),
                    tutor,
                )
                print(view["state"]["active"], view["messages"][-1]["text"])
                assert view["state"]["active"] == active
        finally:
            await tutor.close()

    asyncio.run(run())
