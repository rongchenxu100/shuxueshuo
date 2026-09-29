"""Student HTML and teacher JSON agree; dialogue replays local operations atomically."""

import asyncio
import json
import re
import subprocess
from pathlib import Path

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal, TutorUnavailable
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

ROOT = Path(__file__).resolve().parents[3]


def page_config():
    html = (ROOT / "site/1/q01/index.html").read_text()
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', html, re.DOTALL)[1]
    )


def operation(kind, value=None, index=None):
    return {"kind": kind, "value": value, "index": index}


def pending(actions):
    return [
        {"event_id": f"local-{i}", "action": action} for i, action in enumerate(actions)
    ]


class Tutor:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def respond(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise TutorUnavailable()
        return Proposal(
            reply="取等条件决定上界能否取到。",
            intent="question",
            evidence=[],
            actions=[],
        )


def first_two_steps():
    return [operation("method", "direct")] + [
        action
        for _ in range(2)
        for action in (
            operation("fill", "m", 0),
            operation("fill", "n", 1),
            operation("submit"),
        )
    ]


def test_html_component_contract_matches_teacher_definition():
    page, teacher = page_config(), load_lesson("q01")
    html = (ROOT / "site/1/q01/index.html").read_text()
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), (
        "HTML template IDs must not collide with page containers"
    )
    assert f'<template id="{page["completion"]}">' in html
    assert (page["id"], page["version"], page["methods"]) == (
        teacher["id"],
        teacher["version"],
        teacher["methods"],
    )
    for route, nodes in page["routes"].items():
        assert len(nodes) == len(teacher["routes"][route]["nodes"])
        for node, expected in zip(nodes, teacher["routes"][route]["nodes"]):
            for key in (
                "id",
                "title",
                "question",
                "interaction",
                "expected_answer",
                "feedback",
            ):
                assert node[key] == expected[key], (route, node["id"], key)


@pytest.mark.parametrize("variable,technique", [("m", "square"), ("n", "vertex")])
def test_local_state_matches_server_including_errors_and_route_switch(
    variable, technique
):
    actions = [
        operation("method", "direct"),
        operation("fill", "m", 0),
        operation("fill", "m", 1),
        operation("submit"),
        operation("fill", "n", 1),
        operation("swap", "product"),
        operation("submit"),
        operation("swap", "sum"),
        operation("submit"),
    ]
    actions += [
        action
        for _ in range(2)
        for action in (
            operation("fill", "n", 0),
            operation("fill", "m", 1),
            operation("submit"),
        )
    ]
    actions += [
        operation("switch_route", "1"),
        operation("choice", variable),
        operation("submit"),
        operation("choice", technique),
        operation("submit"),
        operation("choice", "no"),
        operation("submit"),
        operation("choice", "yes"),
        operation("submit"),
    ]
    script = """
require(process.argv[1]);
const {lesson, operations} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
let view = PracticeContext.create(lesson, 'start');
console.log(JSON.stringify(operations.map(operation => {
  view = PracticeContext.apply(view, operation, lesson); return view.state;
})));
"""
    actual = json.loads(
        subprocess.run(
            ["node", "-e", script, str(ROOT / "site/assets/practice/context.js")],
            input=json.dumps({"lesson": page_config(), "operations": pending(actions)}),
            text=True,
            capture_output=True,
            check=True,
        ).stdout
    )

    async def run():
        session, tutor = Session(load_lesson("q01")), Tutor()
        for local, op in zip(actual, pending(actions)):
            result = await session.handle(
                Event(**op, revision=session.revision, kind="ui"), tutor
            )
            assert local == result["state"]
        assert not tutor.calls

    asyncio.run(run())


def test_first_dialogue_replays_progress_once_and_retry_is_idempotent():
    async def run():
        session, tutor = Session(load_lesson("q01")), Tutor()
        event = Event(
            event_id="chat",
            revision=0,
            kind="text",
            text="为什么要验证取等？",
            lesson_version=page_config()["version"],
            pending_operations=pending(first_two_steps()),
        )
        response = await session.handle(event, tutor)
        assert tutor.calls[0]["context"]["state"]["active"] == 2
        assert len(tutor.calls[0]["completed"]) == 2
        assert response["state"]["active"] == 2
        assert await session.handle(event, tutor) == response
        assert len(tutor.calls) == 1
        assert len([m for m in session.messages if m["kind"] == "ui"]) == 7

    asyncio.run(run())


def test_failed_dialogue_does_not_partially_commit_batch():
    async def run():
        session, tutor = Session(load_lesson("q01")), Tutor()
        tutor.fail = True
        event = Event(
            event_id="retry",
            revision=0,
            kind="help",
            lesson_version=page_config()["version"],
            pending_operations=pending(first_two_steps()),
        )
        before = session.view()
        with pytest.raises(TutorUnavailable):
            await session.handle(event, tutor)
        assert session.view() == before
        tutor.fail = False
        assert (await session.handle(event, tutor))["state"]["active"] == 2

    asyncio.run(run())


def test_wrong_answer_is_not_trusted_and_version_mismatch_cannot_commit():
    async def run():
        session, tutor = Session(load_lesson("q01")), Tutor()
        event = Event(
            event_id="wrong",
            revision=0,
            kind="text",
            text="我对了吗？",
            lesson_version=page_config()["version"],
            pending_operations=pending(
                [
                    operation("method", "direct"),
                    operation("fill", "m", 0),
                    operation("fill", "m", 1),
                    operation("submit"),
                ]
            ),
        )
        assert (await session.handle(event, tutor))["state"]["active"] == 0
        assert tutor.calls[-1]["completed"] == []
        before = session.view()
        from shuxueshuo_server.tutor_demo.contracts import InvalidAction

        with pytest.raises(InvalidAction, match="版本"):
            await session.handle(
                event.model_copy(
                    update={
                        "event_id": "outdated",
                        "revision": session.revision,
                        "lesson_version": -1,
                    }
                ),
                tutor,
            )
        assert session.view() == before

    asyncio.run(run())


def test_local_tail_after_retry_is_preserved_without_reusing_previous_step_inputs():
    script = """
require(process.argv[1]);
const lesson = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const C = PracticeContext;
let view = C.create(lesson, 'initial');
const add = (kind, value, index) => {
  const operation = {event_id: crypto.randomUUID(), action: {kind, value, index}, position: C.position(view)};
  view = C.apply(view, operation, lesson); return operation;
};
add('method', 'direct');
const before = structuredClone(view);
const tail = [add('fill', 'm', 0), add('fill', 'n', 1), add('submit'), add('fill', 'n', 0)];
// A hint changes no progress; retain the complete local tail.
let result = C.reconcile(before, tail, lesson);
if (JSON.stringify(result.view.state) !== JSON.stringify(view.state) || result.remaining.length !== 4) throw Error('lost local work');
// An answer already completed stage 0; ignore stage 0 fills, retain stage 1 fill.
const confirmed = tail.slice(0, 3).reduce((current, op) => C.apply(current, op, lesson), before);
result = C.reconcile(confirmed, tail, lesson);
if (result.view.state.active !== 1 || result.view.state.pairs[1][0] !== 'n' || result.remaining.length !== 1) throw Error('reused old input');
"""
    subprocess.run(
        ["node", "-e", script, str(ROOT / "site/assets/practice/context.js")],
        input=json.dumps(page_config()),
        text=True,
        capture_output=True,
        check=True,
    )


def test_batch_position_mismatch_and_duplicate_ids_are_atomic():
    async def run():
        session, tutor = Session(load_lesson("q01")), Tutor()
        ops = pending(first_two_steps())
        ops[1]["position"] = {"route": "direct", "stage": 2, "attempt": 0}
        event = Event(
            event_id="bad-position",
            revision=0,
            kind="help",
            lesson_version=page_config()["version"],
            pending_operations=ops,
        )
        before = session.view()
        from shuxueshuo_server.tutor_demo.contracts import InvalidAction

        with pytest.raises(InvalidAction, match="步骤不一致"):
            await session.handle(event, tutor)
        assert session.view() == before
        ops = pending(first_two_steps())
        ops[1]["event_id"] = ops[0]["event_id"]
        event = Event(
            event_id="duplicate",
            revision=0,
            kind="help",
            lesson_version=page_config()["version"],
            pending_operations=ops,
        )
        with pytest.raises(InvalidAction, match="编号"):
            await session.handle(event, tutor)
        assert session.view() == before
        assert not tutor.calls

    asyncio.run(run())
