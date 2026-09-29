"""Q07: signed radical rewrite, static errors and on-demand synchronization."""

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
    html = (ROOT / "site/1/q07/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def actions():
    return [
        operation("method", "matching"),
        operation("choice", "positive_root"),
        operation("submit"),
        operation("choice", "missing_root"),
        operation("submit"),
        operation("choice", "negative_root"),
        operation("submit"),
        operation("fill", "9-x^2", 0),
        operation("fill", "x^2", 1),
        operation("swap", "product"),
        operation("submit"),
        operation("swap", "sum"),
        operation("submit"),
        operation("fill", "x^2", 0),
        operation("fill", "x^2", 1),
        operation("submit"),
        operation("fill", "9-x^2", 0),
        operation("submit"),
        operation("choice", "upper"),
        operation("submit"),
        operation("choice", "positive"),
        operation("submit"),
        operation("choice", "lower"),
        operation("submit"),
        operation("fill", "9-x^2", 0),
        operation("fill", "9-x^2", 1),
        operation("submit"),
        operation("fill", "x^2", 1),
        operation("submit"),
    ]


def test_page_teacher_and_templates_agree():
    page, teacher = page_config(), load_lesson("q07")
    html = (ROOT / "site/1/q07/index.html").read_text()
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
    assert len(page["routes"]["matching"]) == 5
    assert page["routes"]["matching"][0]["title"] == "凑配表达式"
    amgm = page["routes"]["matching"][2]["interaction"]
    assert amgm["terms"] == ["x^2", "9-x^2"]
    assert "/1/q07/" in (ROOT / "site/1/index.html").read_text()


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
        session, tutor = Session(load_lesson("q07")), Tutor()
        for browser, op in zip(local, operations, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
        assert not tutor.calls
        assert local[2]["state"]["active"] == local[4]["state"]["active"] == 0
        for index, stage in [(10, 1), (15, 2), (19, 3), (21, 3), (26, 4)]:
            assert local[index]["state"]["active"] == stage
            assert local[index]["state"]["feedback"]
        assert view["state"]["active"] == 5
        assert view["attempts"][-1]["status"] == "completed"
        assert view["state"]["pairs"][4] == ["9-x^2", "x^2"]

    asyncio.run(run())


def test_dialogue_sync_is_atomic_and_retry_does_not_duplicate_progress():
    async def run():
        session, tutor = Session(load_lesson("q07")), Tutor()
        event = Event(
            event_id="q07-chat",
            revision=0,
            kind="text",
            text="为什么取等时要让这两项相等？",
            lesson_version=1,
            pending_operations=pending(actions()[:24]),
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
        assert context["node"]["expected_answer"]["terms"] == ["x^2", "9-x^2"]
        assert len(tutor.calls[-1]["completed"]) == 4
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
                ([], "答案-9/2"),
                ([], "y=√(x²(9-x²))"),
                (["signed_rewrite"], "y=-√(x²(9-x²))"),
            ],
        ),
        (1, [([], "两项为正"), (["fixed_sum_structure"], "x²与9-x²定和求积")]),
        (2, [([], "答案-9/2"), (["amgm_relation"], "9≥2√(x²(9-x²))")]),
        (3, [([], "y≤-9/2"), (["negative_lower_bound"], "取负后y≥-9/2")]),
        (4, [([], "x=3√2/2"), ([], "为什么相等？"), (["equal_terms"], "x²=9-x²")]),
    ],
)
def test_evidence_gates_only_complete_current_node(stage, inputs):
    """Stub proposals verify evidence gating, not model understanding."""

    class ContractTutor:
        proposal = None

        async def respond(self, **kwargs):
            return self.proposal

    async def run():
        session, tutor = Session(load_lesson("q07")), ContractTutor()
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
    os.getenv("RUN_TUTOR_LIVE") != "1",
    reason="Explicit live-test opt-in required",
)
def test_live_signed_rewrite_and_bound():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    async def run():
        session, tutor = Session(load_lesson("q07")), DeepSeekTutor()
        await session.handle(
            Event(
                event_id="choose-route",
                revision=0,
                kind="ui",
                action=operation("method", "matching"),
            ),
            Tutor(),
        )
        try:
            cases = [
                ("用凑配法，我不明白为什么要在根号前加负号？", 0),
                ("我觉得y=√(x²(9-x²))，x放进根号平方就行", 0),
                ("x<0，所以x=-√(x²)，原式y=-√(x²(9-x²))", 1),
                ("x²和9-x²两个正数和为9，是定和求积", 2),
                ("9=x²+(9-x²)≥2√(x²(9-x²))", 3),
                ("所以y≤-9/2", 3),
                ("取负数后方向反过来，y≥-9/2", 4),
                ("x²=9-x²时取等", 5),
            ]
            for i, (text, active) in enumerate(cases):
                view = await session.handle(
                    Event(
                        event_id=f"live-{i}",
                        revision=session.revision,
                        kind="text",
                        text=text,
                    ),
                    tutor,
                )
                print(view["state"]["active"], view["messages"][-1]["text"])
                assert view["state"]["active"] == active
        finally:
            await tutor.close()

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(
    os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live-test opt-in required"
)
def test_live_equality_after_local_practice():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor

    class RecordingTutor(DeepSeekTutor):
        async def respond(self, **kwargs):
            self.proposal = await super().respond(**kwargs)
            return self.proposal

    async def run():
        session, tutor = Session(load_lesson("q07")), RecordingTutor()
        try:
            view = await session.handle(
                Event(
                    event_id="sync-live",
                    revision=0,
                    kind="text",
                    text="x²=9-x²时取等",
                    lesson_version=1,
                    pending_operations=pending(actions()[:24]),
                ),
                tutor,
            )
            assert view["state"]["active"] == 5, tutor.proposal.model_dump()
        finally:
            await tutor.close()

    asyncio.run(run())
