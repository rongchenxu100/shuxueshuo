"""Q15: split the target into two groups, then multiply only the negative-degree group."""

import asyncio
import json
import os

import pytest
import re
import subprocess

from shuxueshuo_server.tutor_demo.contracts import allowed_actions
from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending


def page_config():
    text = (ROOT / "site/1/q15/index.html").read_text()
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
        + fills("-1", "0", "1")
        + fills("0", "-1", "1")
        + fills("whole", "a+b")
        + fills("first", "a+b")
        + fills("second", "a")
        + fills("second", "a+b")
        + fills("2b/a", "2a/b")
        + [operation("swap", "product"), operation("submit")]
        + fills("2a/b", "2b/a")
        + fills("2b/a", "2b/a")
        + fills("2b/a", "2a/b")
    )


def test_page_and_teacher_contract():
    page, teacher = page_config(), load_lesson("q15")
    text = (ROOT / "site/1/q15/index.html").read_text()
    assert "变式" not in text and "3-5" not in text
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
    rewrite = page["routes"]["homogeneous"][1]
    board = re.search(r'<template id="rewrite-scope">(.*?)</template>', text, re.S)[1]
    targets = re.findall(r'data-rewrite-scope="([^"]+)"', board)
    assert targets == [
        o["value"] for o in rewrite["interaction"]["slots"][0]["options"]
    ]
    assert "ones" not in text and "rw-chunk" not in text
    for template in ("degree-board", "homogeneity-done"):
        block = re.search(rf'<template id="{template}">(.*?)</template>', text, re.S)[1]
        assert (
            r"\left(\dfrac ba+\dfrac ab\right)+\left(\dfrac1a+\dfrac1b\right)" in block
        )
    assert (ROOT / "site/1/index.html").read_text().count('class="problem-card" href="/1/q15/"') == 1


def test_rewrite_candidates():
    node = load_lesson("q15")["routes"]["homogeneous"]["nodes"][1]
    specs = allowed_actions(node)
    assert specs[0]["values"] == ["whole", "first", "second"]
    assert specs[1]["values"] == ["a+b", "a", "1"]


def test_local_and_server_replay_wrong_scopes_and_restart():
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
        session, tutor = Session(load_lesson("q15")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert errors.count(0) == 2
        assert errors.count(1) == 6
        assert set(errors) == {0, 1, 2, 4}
        assert view["state"]["active"] == 5
        assert view["state"]["pairs"][:2] == [["0", "-1", "1"], ["second", "a+b"]]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(
                reply="已记录。", intent="answer", evidence=self.evidence, actions=[]
            )

    async def run():
        session = Session(load_lesson("q15"))
        turns = [
            ["zero_group_degree", "negative_group_degree"],
            ["condition_degree"],
            ["second_group_scope"],
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
            assert view["state"]["active"] == [0, 1, 1, 2][i]
        assert view["state"]["pairs"][:2] == [["0", "-1", "1"], ["second", "a+b"]]

    asyncio.run(run())


def test_rewrite_calculations_cover_all_choices_and_survive_questions():
    from .test_q14 import confirmed_pair

    page = page_config()
    text = (ROOT / "site/1/q15/index.html").read_text()
    templates = dict(
        re.findall(r'<template id="([^\"]+)">(.*?)</template>', text, re.S)
    )
    node = page["routes"]["homogeneous"][1]
    assert "attempt_calculations" not in json.dumps(load_lesson("q15"))

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(
                reply="按所选范围展开，再分别检查等价性和次数。",
                intent="question",
                evidence=[],
                actions=[],
            )

    async def run():
        for scope in node["interaction"]["slots"][0]["options"]:
            for factor in node["interaction"]["slots"][1]["options"]:
                pair = [scope["value"], factor["value"]]
                template = node["attempt_calculations"][pair[0]][pair[1]]
                assert template in templates
                session = Session(load_lesson("q15"))
                ops = (
                    [operation("method", "homogeneous")]
                    + fills("0", "-1", "1")
                    + fills(*pair)
                )
                view = await session.handle(
                    Event(
                        event_id="ask",
                        kind="text",
                        text="这样展开是什么，是否等价？",
                        revision=0,
                        lesson_version=1,
                        pending_operations=pending(ops),
                    ),
                    QuestionTutor(),
                )
                if pair == node["expected_answer"]["terms"]:
                    assert template == node["display"]
                    assert view["state"]["active"] == 2
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == pair
                math = re.search(
                    r'<div class="rewrite-calculation-math">(.*?)</div>',
                    templates[template],
                    re.S,
                )[1]
                lines = re.findall(r"<p data-math-text>(.*?)</p>", math)
                assert len(lines) >= 2
                assert lines[0].startswith("$") and not lines[0].startswith("$=")
                assert lines[1].startswith("$=")
                assert not re.search(r"[\u4e00-\u9fff]", math)
                assert 'class="rewrite-calculation-feedback"' in templates[template]
                view = await session.handle(
                    Event(
                        event_id="edit",
                        kind="ui",
                        revision=session.revision,
                        action=operation("fill", "1" if pair[1] != "1" else "a", 1),
                    ),
                    QuestionTutor(),
                )
                assert confirmed_pair(view) is None

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_q15_plain_degree_explanations_and_flow():
    from shuxueshuo_server.tutor_demo.llm import DeepSeekTutor
    from .test_q14 import confirmed_pair

    turns = [
        ("b/a里有分母，为什么不是负一次？请解释怎么判断次数。", 0),
        ("第一组是负一次，第二组零次，条件的次数我还没判断", 0),
        ("第一组零次，第二组负一次", 0),
        ("条件表达式a+b是正一次", 1),
        ("我只给第一组乘a+b，请按我的选择展开，说明每种项的次数。这一步仍等价吗？", 1),
        ("如果只给第二组乘a，是不是已经齐次了？为什么还不能通过？", 1),
        ("先只确定给第二组乘，乘数我还没确定", 1),
        ("乘入a+b，因为a+b=1", 2),
        ("2b/a与2a/b定积求和", 3),
        ("最小值是6", 3),
        ("2b/a+2a/b≥2√((2b/a)(2a/b))=4", 4),
        ("a=-b时取等", 4),
        ("a=b时取等", 5),
    ]

    async def run():
        session, tutor = Session(load_lesson("q15")), DeepSeekTutor()
        try:
            for i, (text, active) in enumerate(turns):
                ops = (
                    [operation("method", "homogeneous")]
                    if i == 0
                    else fills("first", "a+b")
                    if i == 4
                    else []
                )
                view = await session.handle(
                    Event(
                        event_id=f"live-{i}",
                        kind="text",
                        text=text,
                        revision=session.revision,
                        lesson_version=1,
                        pending_operations=[
                            {**op, "event_id": f"live-ui-{i}-{j}"}
                            for j, op in enumerate(pending(ops))
                        ],
                    ),
                    tutor,
                )
                reply = view["messages"][-1]["text"]
                print(
                    json.dumps(
                        {
                            "turn": i + 1,
                            "student": text,
                            "active": view["state"]["active"],
                            "reply": reply,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                assert view["state"]["active"] == active
                assert not re.search(r"\bdeg(?:ree)?\b", reply, re.I)
                if i in (4, 5):
                    assert confirmed_pair(view) == ["first", "a+b"]
        finally:
            await tutor.close()

    asyncio.run(run())
