"""Q04: negative terms, static errors and on-demand synchronization."""

import asyncio
import json
import re
import subprocess

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    html = (ROOT / "site/1/q04/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def actions():
    return [
        operation("method", "direct"),
        operation("choice", "lost_outer_minus"),
        operation("submit"),
        operation("choice", "wrong_constant"),
        operation("submit"),
        operation("choice", "positive_sum"),
        operation("submit"),
        operation("fill", "x", 0),
        operation("fill", "4/x", 1),
        operation("submit"),  # Negative terms cannot use positive AM-GM.
        operation("fill", "-4/x", 0),
        operation("fill", "-x", 1),
        operation("submit"),  # Reversed positive pair is accepted.
        operation("choice", "lower"),
        operation("submit"),  # Negating must reverse the inequality.
        operation("choice", "upper"),
        operation("submit"),
        operation("fill", "-x", 0),
        operation("fill", "-x", 1),
        operation("submit"),
        operation("fill", "-4/x", 0),
        operation("submit"),
    ]


def test_page_teacher_and_templates_agree():
    page, teacher = page_config(), load_lesson("q04")
    html = (ROOT / "site/1/q04/index.html").read_text()
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
        assert set(student.get("preview", {}).values()) <= templates
        if student.get("board"):
            assert student["board"] in templates
        assert set(student["interaction"].get("term_labels", {})) <= set(
            student["interaction"].get("terms", [])
        )
    assert len(page["routes"]["direct"]) == 4
    assert page["routes"]["direct"][0]["title"] == "整理表达式"
    amgm = page["routes"]["direct"][1]["interaction"]
    assert amgm["terms"] == ["x", "4/x", "-x", "-4/x"]
    assert amgm["positive_terms"] == ["-x", "-4/x"]
    assert "/1/q04/" in (ROOT / "site/1/index.html").read_text()


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
        session, tutor = Session(load_lesson("q04")), Tutor()
        for browser, op in zip(local, operations, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
        assert not tutor.calls
        assert local[2]["state"]["active"] == local[4]["state"]["active"] == 0
        assert local[9]["state"]["active"] == 1
        assert local[14]["state"]["active"] == 2
        assert local[19]["state"]["active"] == 3
        assert view["state"]["active"] == 4
        assert view["attempts"][-1]["status"] == "completed"
        assert view["state"]["pairs"][3] == ["-4/x", "-x"]

    asyncio.run(run())


def test_dialogue_sync_is_atomic_and_retry_does_not_duplicate_progress():
    async def run():
        session, tutor = Session(load_lesson("q04")), Tutor()
        event = Event(
            event_id="q04-chat",
            revision=0,
            kind="text",
            text="为什么不等号要反向？",
            lesson_version=1,
            pending_operations=pending(actions()[:13]),
        )
        before = session.view()
        tutor.fail = True
        with pytest.raises(TutorUnavailable):
            await session.handle(event, tutor)
        assert session.view() == before
        tutor.fail = False
        view = await session.handle(event, tutor)
        context = tutor.calls[-1]["context"]
        assert context["node"]["id"] == "bound"
        assert context["node"]["expected_answer"]["one_of"] == ["upper"]
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
                ([], "答案C"),
                (["positive_rewrite"], "把前两项提负号，原式=-((-x)+(-4/x))-4"),
            ],
        ),
        (1, [([], "x+4/x≥4"), (["amgm_relation"], "(-x)+(-4/x)≥4")]),
        (2, [([], "为什么反向？"), ([], "原式≥-8"), (["upper_bound"], "原式≤-8")]),
        (3, [([], "x=2"), ([], "选C"), (["equal_terms"], "-x=-4/x")]),
    ],
)
def test_evidence_gates_only_complete_current_node(stage, inputs):
    """Stub proposals verify evidence gating, not model understanding."""

    class ContractTutor:
        proposal = None

        async def respond(self, **kwargs):
            return self.proposal

    async def run():
        session, tutor = Session(load_lesson("q04")), ContractTutor()
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


def test_positive_badges_exclude_negative_candidates_and_preserve_existing_lessons():
    script = """
global.window = global;
require(process.argv[1]);
const lessons = JSON.parse(require('fs').readFileSync(0, 'utf8'));
console.log(JSON.stringify(lessons.map(component => PracticeComponents.amgm({
  slot: () => '<span>?</span>', terms: component.terms,
  positiveTerms: component.positive_terms, termLabels: component.term_labels
}).split('<div class="visual-board')[0])));
"""
    components = [
        load_lesson(id)["routes"]["direct"]["nodes"][1]["interaction"]
        for id in ["q01", "q02", "q03", "q04"]
    ]
    badges = json.loads(
        subprocess.run(
            ["node", "-e", script, str(ROOT / "site/assets/practice/components.js")],
            input=json.dumps(components),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )
    for component, html in zip(components, badges, strict=True):
        labels = component.get("term_labels", {})
        expected = component.get("positive_terms", component["terms"])
        assert html.count("&gt; 0") == len(expected)
        assert re.findall(r"<span data-math-text>(.*?)</span>", html) == [
            labels.get(term, term) for term in expected
        ]
