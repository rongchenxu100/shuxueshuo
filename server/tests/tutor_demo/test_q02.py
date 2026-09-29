"""Q02: real-valued reciprocal squares, static routes and teacher synchronization."""

import asyncio
import json
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    html = (ROOT / "site/1/q02/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def direct_actions():
    return [
        operation("method", "direct"),
        operation("fill", "1/x^2", 0),
        operation("fill", "x^2", 1),
        operation("submit"),  # Wrong orientation must not advance.
        operation("swap", "product"),
        operation("submit"),
        operation("fill", "x^2", 0),
        operation("fill", "x^2", 1),
        operation("submit"),  # Duplicate terms must not advance.
        operation("fill", "1/x^2", 1),
        operation("submit"),
    ]


def square_actions():
    return [
        operation("method", "square"),
        operation("choice", "sum"),
        operation("submit"),  # Valid identity, insufficient sharp bound.
        operation("choice", "difference"),
        operation("submit"),
    ]


def test_page_and_teacher_agree_and_templates_resolve():
    page, teacher = page_config(), load_lesson("q02")
    html = (ROOT / "site/1/q02/index.html").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    templates = set(re.findall(r'<template id="([^"]+)"', html))
    assert page["completion"] in templates
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    assert set(page["routes"]) == set(teacher["routes"])
    for route, nodes in page["routes"].items():
        assert len(nodes) == len(teacher["routes"][route]["nodes"])
        for student, tutor in zip(nodes, teacher["routes"][route]["nodes"]):
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
            assert set(student["interaction"].get("term_labels", {})) <= set(
                student["interaction"].get("terms", [])
            )
    assert "/1/q02/" in (ROOT / "site/1/index.html").read_text()


def test_local_and_server_routes_match_at_every_operation():
    actions = (
        direct_actions()
        + [
            operation("fill", "1/x^2", 0),
            operation("fill", "x^2", 1),
            operation("submit"),
            operation("switch_route", "square"),
        ]
        + square_actions()[1:]
        + [
            operation("fill", "1/x", 0),
            operation("fill", "1/x", 1),
            operation("submit"),
            operation("fill", "x", 1),
            operation("submit"),
            operation("switch_route", "direct"),
        ]
    )
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
            input=json.dumps({"lesson": page_config(), "operations": pending(actions)}),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    async def run():
        session, tutor = Session(load_lesson("q02")), Tutor()
        for browser, op in zip(local, pending(actions)):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
        assert not tutor.calls
        assert [a["status"] for a in view["attempts"]] == [
            "completed",
            "completed",
            "learning",
        ]
        assert [len(a["completed"]) for a in view["attempts"]] == [3, 2, 0]
        assert local[3]["state"]["active"] == 0
        assert local[8]["state"]["active"] == 1
        assert view["state"]["pairs"] == [["", ""]] * 3

    asyncio.run(run())


@pytest.mark.parametrize(
    "route,actions", [("direct", direct_actions()), ("square", square_actions())]
)
def test_first_dialogue_receives_local_history_atomically(route, actions):
    async def run():
        session, tutor = Session(load_lesson("q02")), Tutor()
        event = Event(
            event_id="chat",
            revision=0,
            kind="text",
            text="这里需要两项为正吗？",
            lesson_version=1,
            pending_operations=pending(actions),
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
        assert context["state"]["method"] == route
        assert context["node"]["expected_answer"]["terms"] == (
            ["x^2", "1/x^2"] if route == "direct" else ["x", "1/x"]
        )
        assert len(context["completed_results"]) > 0
        assert len(tutor.calls[-1]["completed"]) == (2 if route == "direct" else 1)
        calls = len(tutor.calls)
        assert await session.handle(event, tutor) == view
        assert len(tutor.calls) == calls

    asyncio.run(run())


@pytest.mark.parametrize(
    "route,stage,inputs",
    [
        (
            "direct",
            0,
            [
                ([], "2"),
                (["positive_terms"], "这两项为正"),
                (["positive_terms", "fixed_product", "sum_target"], "定积求和"),
            ],
        ),
        ("direct", 1, [([], "答案2"), (["amgm_relation"], "x²+1/x²≥2√(x²·1/x²)=2")]),
        ("direct", 2, [([], "为什么相等？"), (["equal_terms"], "x²=1/x²")]),
        ("square", 0, [([], "试一下配方"), (["square_strategy"], "(x-1/x)²")]),
        ("square", 1, [([], "x=0"), (["zero_square"], "x=1/x")]),
    ],
)
def test_node_evidence_gate_and_completion_stop_at_current_step(route, stage, inputs):
    """Stub proposals verify contract execution, not the model's semantic accuracy."""

    class ContractTutor:
        proposal = None

        async def respond(self, **kwargs):
            return self.proposal

    async def run():
        tutor = ContractTutor()
        session = Session(load_lesson("q02"))
        session.state.update(method=route, active=stage)
        for i, (evidence, text) in enumerate(inputs):
            tutor.proposal = Proposal(
                reply="继续追问下一步？", intent="answer", evidence=evidence, actions=[]
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
                    == session.lesson["routes"][route]["nodes"][stage][
                        "completion_reply"
                    ]
                )
                assert "？" not in view["messages"][-1]["text"]

    asyncio.run(run())
