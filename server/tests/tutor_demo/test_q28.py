"""Q28: range of x+y under x^2+y^2-xy=1 via symmetry, sum-product substitution and p<=s^2/4."""

import asyncio
import json
import re
import os

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay, template

TITLES = ["识别对称结构", "和积换元", "改写条件", "选不等式", "解出范围", "验证端点"]
CHOICES = {"condition_form": "minus_3p", "inequality_form": "p_le", "range_form": "closed"}


def page_text():
    return (ROOT / "site/1/q28/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def choose(value):
    return [operation("choice", value), operation("submit")]


def actions():
    return (
        [operation("method", "symmetric")]
        + pair("unchanged", "changed")
        + pair("unchanged", "unchanged")
        + pair("xy", "x+y")
        + pair("x+y", "xy")
        + choose("minus_2p")
        + choose("minus_p")
        + choose("minus_3p")
        + choose("s_ge")
        + choose("p_le")
        + choose("positive")
        + choose("upper_only")
        + choose("closed")
        + pair("x", "-y")
        + pair("x", "y")
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q28"), page_text()
    assert "典例" not in text and "变式" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    nodes = page["routes"]["symmetric"]
    for node, expected in zip(nodes, teacher["routes"]["symmetric"]["nodes"], strict=True):
        for key in ("id", "title", "question", "interaction", "expected_answer", "feedback"):
            assert node[key] == expected[key]
        assert node["display"] in templates
        if node.get("board"):
            assert node["board"] in templates
        if node["interaction"]["type"] == "choice":
            assert set(node["preview"]) == {o["value"] for o in node["interaction"]["options"]}
            assert set(node["preview"].values()) <= templates
    assert [n["title"] for n in nodes] == TITLES
    assert set(teacher["initial_state"]["choices"]) == set(CHOICES)
    assert re.findall(r'data-judgment="(\d)"', template(text, nodes[0]["board"])) == ["0", "1"]
    assert "[-2,2]" in template(text, page["completion"])
    assert len(teacher["initial_state"]["pairs"]) == len(nodes)
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('href="/1/q28/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_wrong_answers_and_restart():
    ops = pending(actions() + [operation("switch_route", "symmetric")] + actions()[1:])
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q28")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(
                Event(**op, kind="ui", revision=session.revision), tutor
            )
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append(view["state"]["active"])
        assert set(errors) == {0, 1, 2, 3, 4, 5}
        assert view["state"]["active"] == 6
        assert view["state"]["choices"] == CHOICES
        assert view["state"]["pairs"][1] == ["x+y", "xy"]
        assert all(a["status"] == "completed" for a in view["attempts"])
        assert not tutor.calls

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(reply="已记录。", intent="answer", evidence=self.evidence, actions=[])

    async def run():
        session = Session(load_lesson("q28"))
        turns = [
            ["symmetric_condition"],
            ["symmetric_target"],
            ["sum_definition", "product_definition"],
            ["condition_in_sp"],
            ["sum_product_inequality"],
        ]
        for i, evidence in enumerate(turns):
            view = await session.handle(
                Event(
                    event_id=f"e{i}", revision=session.revision, kind="text", text="本轮证据", lesson_version=1,
                    pending_operations=pending([operation("method", "symmetric")]) if i == 0 else [],
                ),
                EvidenceTutor(evidence),
            )
            assert view["state"]["active"] == [0, 1, 2, 3, 4][i]
        assert view["state"]["pairs"][0] == ["unchanged", "unchanged"]
        assert view["state"]["pairs"][1] == ["x+y", "xy"]
        assert view["state"]["choices"]["condition_form"] == "minus_3p"
        assert view["state"]["choices"]["inequality_form"] == "p_le"

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_domain_questions_and_full_route():
    from .reciprocal_live import replay

    turns = [
        ('条件交换后不变', 0, False, [('method', 'symmetric')], ['symmetric_condition']),
        ('目标交换后也不变', 1, False, [], ['symmetric_target']),
        ('令s=x+y', 1, False, [], ['sum_definition']),
        ('p=xy', 2, False, [], ['product_definition']),
        ('条件是s²-2p=1', 2, False, [('choice', 'minus_2p')], []),
        ('应该是s²-3p=1', 3, False, [], ['condition_in_sp']),
        ('如果x=0,y=1，在这一组值上s≥2√p也成立吧？这是不是说明零也可以用？我只问这一组，不是说全域成立。', 3, True, [('choice', 's_ge')], []),
        ('x=y=-1满足原条件吗？这时候s≥2√p为什么不成立？', 3, True, [], []),
        ('x=1/√3,y=-1/√3满足条件，此时p=-1/3，√p还有实数意义吗？', 3, True, [], []),
        ('由(x-y)²≥0，得到p≤s²/4，对所有实数都成立', 4, False, [], ['sum_product_inequality']),
        ('s≤2', 4, False, [('choice', 'upper_only')], []),
        ('完整范围是-2≤s≤2', 5, False, [], ['closed_range']),
        ('两个端点能取到，就足以说明中间每个值都能取到吗？', 5, True, [], []),
        ('取x=-y来得到端点', 5, False, [('fill', 'x', 0), ('fill', '-y', 1)], []),
        ('x=y=1时取到2，x=y=-1时取到-2', 6, False, [], ['equal_terms']),
    ]
    view = asyncio.run(replay("q28", turns))
    # These dialogues concern sqrt(p); silently changing it invalidates the explanation.
    for message in view["messages"]:
        assert not re.search(r"sqrt\s*\{?\s*-\s*p", message.get("text", "")), message


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_first_question_after_local_choices():
    from .reciprocal_live import replay

    turns = [
        ('x=0,y=1时，s≥2√p也成立吧？这里只核对零值，不改我的选项。', 3, True, [('method', 'symmetric'), ('fill', 'unchanged', 0), ('fill', 'unchanged', 1), ('submit',), ('fill', 'x+y', 0), ('fill', 'xy', 1), ('submit',), ('choice', 'minus_3p'), ('submit',), ('choice', 's_ge')], []),
    ]
    view = asyncio.run(replay("q28", turns))
    # These dialogues concern sqrt(p); silently changing it invalidates the explanation.
    for message in view["messages"]:
        assert not re.search(r"sqrt\s*\{?\s*-\s*p", message.get("text", "")), message
