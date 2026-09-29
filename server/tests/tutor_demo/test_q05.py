"""Q05: exponential terms, static errors and on-demand synchronization."""

import asyncio
import json
import re
import subprocess

import pytest
from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    html = (ROOT / "site/1/q05/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def actions():
    return [
        operation("method", "direct"),
        operation("fill", "a", 0),
        operation("fill", "b", 1),
        operation("submit"),  # Correct observation about a+b, different target.
        operation("fill", "2^a", 0),
        operation("fill", "2^b", 1),
        operation("submit"),  # Exponential terms are not fixed-sum.
        operation("swap", "product"),
        operation("submit"),
        operation("fill", "2^b", 0),  # Reversed pair is equivalent.
        operation("fill", "2^a", 1),
        operation("submit"),
        operation("fill", "2^a", 0),
        operation("fill", "2^a", 1),
        operation("submit"),  # Repeating one term doesn't express equality of both.
        operation("fill", "2^b", 1),
        operation("submit"),
    ]


def test_page_teacher_and_templates_agree():
    page, teacher = page_config(), load_lesson("q05")
    html = (ROOT / "site/1/q05/index.html").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    templates = set(re.findall(r'<template id="([^"]+)"', html))
    assert page["completion"] in templates
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    assert set(page["routes"]) == set(teacher["routes"]) == {"direct"}
    for student, tutor in zip(
        page["routes"]["direct"], teacher["routes"]["direct"]["nodes"], strict=True
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
        assert student["expected_answer"]["terms"] == ["2^a", "2^b"]
        assert set(student["interaction"]["term_labels"]) == set(
            student["interaction"]["terms"]
        )
    assert page["routes"]["direct"][0]["question"] == "这两项是定和求积，还是定积求和？"
    assert page["routes"]["direct"][0]["interaction"]["terms"] == [
        "a",
        "b",
        "2^a",
        "2^b",
    ]
    for stage in (1, 2):
        assert page["routes"]["direct"][stage]["interaction"]["terms"] == ["2^a", "2^b"]
    assert "/1/q05/" in (ROOT / "site/1/index.html").read_text()


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
        session, tutor = Session(load_lesson("q05")), Tutor()
        for browser, op in zip(local, operations, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
        assert not tutor.calls
        assert local[3]["state"]["active"] == local[6]["state"]["active"] == 0
        assert local[14]["state"]["active"] == 2
        assert view["state"]["active"] == 3
        assert view["attempts"][-1]["status"] == "completed"
        assert view["state"]["pairs"][2] == ["2^a", "2^b"]

    asyncio.run(run())


def test_dialogue_sync_is_atomic_and_retry_does_not_duplicate_progress():
    async def run():
        session, tutor = Session(load_lesson("q05")), Tutor()
        event = Event(
            event_id="q05-chat",
            revision=0,
            kind="text",
            text="a、b可能为负，为什么还能取等？",
            lesson_version=1,
            pending_operations=pending(actions()[:12]),
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
        assert context["node"]["expected_answer"]["terms"] == ["2^a", "2^b"]
        assert len(tutor.calls[-1]["completed"]) == 2
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
                ([], "a+b固定，所以对a、b定和求积"),
                (["fixed_product"], "积固定"),
                (["fixed_product", "sum_target"], "这是定积求和"),
            ],
        ),
        (
            1,
            [
                ([], "答案4√2"),
                ([], "2^a+2^b=8"),
                (["amgm_relation"], "2^a+2^b≥2√(2^a·2^b)"),
            ],
        ),
        (2, [([], "为什么两项相等？"), ([], "a=b=3"), (["equal_terms"], "a=b")]),
    ],
)
def test_evidence_gates_only_complete_current_node(stage, inputs):
    """Stub proposals verify evidence gating, not model understanding."""

    class ContractTutor:
        proposal = None

        async def respond(self, **kwargs):
            return self.proposal

    async def run():
        session, tutor = Session(load_lesson("q05")), ContractTutor()
        session.state.update(method="direct", active=stage)
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
                    == session.lesson["routes"]["direct"]["nodes"][stage][
                        "completion_reply"
                    ]
                )
                assert "？" not in view["messages"][-1]["text"]

    asyncio.run(run())
