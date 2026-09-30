"""Q30: minimum of a+2b under 2ab=a+2b+3, via constructed symmetry or elimination and splitting."""

import asyncio
import json
import re
import os

import pytest

from shuxueshuo_server.tutor_demo.llm import Proposal
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson

from .test_local_practice import ROOT, Tutor, operation, pending
from .test_q11 import local_replay, template

TITLES = {
    "symmetric": ["识别对称结构", "构造对称", "和积换元", "改写条件", "选不等式", "解不等式", "验证取等"],
    "elimination": ["消元定范围", "分式分离", "观察和积结构", "应用基本不等式", "验证取等"],
}
CHOICES = {
    "construct_form": "x_a_y_2b",
    "condition_form": "plus_3",
    "inequality_form": "s_ge",
    "solve_form": "ge_6",
    "a_range": "gt_1",
}


def page_text():
    return (ROOT / "site/1/q30/index.html").read_text()


def page_config():
    return json.loads(
        re.search(r'id="practice-config">\s*(.*?)</script>', page_text(), re.DOTALL)[1]
    )


def pair(a, b):
    return [operation("fill", a, 0), operation("fill", b, 1), operation("submit")]


def choose(value):
    return [operation("choice", value), operation("submit")]


def symmetric_actions():
    return (
        [operation("method", "symmetric")]
        + pair("unchanged", "changed")
        + pair("changed", "changed")
        + choose("x_2a_y_b")
        + choose("x_2a_y_2b")
        + choose("x_a_y_2b")
        + pair("xy", "x+y")
        + pair("x+y", "xy")
        + choose("minus_3")
        + choose("double_p")
        + choose("plus_3")
        + choose("p_ge")
        + choose("s_ge")
        + choose("both")
        + choose("between")
        + choose("ge_6")
        + pair("x", "x")
        + pair("x", "y")
    )


def elimination_actions():
    a, b = "a-1", "4/(a-1)"
    return (
        [operation("switch_route", "elimination")]
        + choose("gt_0")
        + choose("ne_1")
        + choose("gt_1")
        + pair("3", "1")
        + pair("4", "2")
        + pair(a, b)
        + [operation("swap", "product"), operation("submit")]
        + pair(b, a)
        + pair(a, a)
        + pair(a, b)
    )


def test_page_and_teacher_contract():
    page, teacher, text = page_config(), load_lesson("q30"), page_text()
    assert "典例" not in text and "变式" not in text
    for key in ("id", "version", "methods"):
        assert page[key] == teacher[key]
    assert set(page["routes"]) == set(teacher["routes"]) == set(TITLES)
    templates = set(re.findall(r'<template id="([^"]+)"', text))
    assert page["completion"] in templates
    for route, nodes in page["routes"].items():
        for node, expected in zip(nodes, teacher["routes"][route]["nodes"], strict=True):
            for key in ("id", "title", "question", "interaction", "expected_answer", "feedback"):
                assert node[key] == expected[key]
            assert node["display"] in templates
            if node.get("board"):
                assert node["board"] in templates
            if node["interaction"]["type"] == "choice":
                assert set(node["preview"]) == {o["value"] for o in node["interaction"]["options"]}
                assert set(node["preview"].values()) <= templates
        assert [n["title"] for n in nodes] == TITLES[route]
    assert set(teacher["initial_state"]["choices"]) == set(CHOICES)
    assert len(teacher["initial_state"]["pairs"]) == max(len(n) for n in page["routes"].values())
    inequality = page["routes"]["symmetric"][4]
    assert inequality["expected_answer"]["one_of"] == ["p_le", "s_ge"]
    assert re.findall(r'data-judgment="(\d)"', template(text, page["routes"]["symmetric"][0]["board"])) == ["0", "1"]
    assert re.findall(r'data-fill="(\d)"', template(text, "elimination-split-board")) == ["0", "1"]
    assert "最小值为 $6$" in template(text, page["completion"])
    for block in re.findall(r"<template[^>]*>(.*?)</template>", text, re.S):
        for math in re.findall(r"\$[^$]*\$", block):
            assert "<" not in math, math
    home = (ROOT / "site/1/index.html").read_text()
    assert home.count('class="problem-card" href="/1/q30/"') == 1
    cards = len(re.findall(r'class="problem-card" href="/1/q\d+/"', home))
    assert f"共 <strong>{cards}</strong> 题" in home


def test_local_and_server_replay_both_routes_with_wrong_answers():
    ops = pending(symmetric_actions() + elimination_actions())
    local = local_replay(page_config(), ops)

    async def run():
        session, tutor = Session(load_lesson("q30")), Tutor()
        errors = []
        for browser, op in zip(local, ops, strict=True):
            view = await session.handle(Event(**op, kind="ui", revision=session.revision), tutor)
            assert view["state"] == browser["state"]
            assert len(view["completed"]) == len(browser["completed"])
            if view["state"]["feedback"]:
                errors.append((view["state"]["method"], view["state"]["active"]))
        assert {a for m, a in errors if m == "symmetric"} == {0, 1, 2, 3, 4, 5, 6}
        assert {0, 1, 2} <= {a for m, a in errors if m == "elimination"}
        assert view["state"]["method"] == "elimination"
        assert view["state"]["active"] == 5
        assert view["state"]["choices"]["a_range"] == "gt_1"
        assert view["state"]["pairs"][1] == ["4", "2"]
        assert [(a["route"], a["status"]) for a in view["attempts"]] == [
            ("symmetric", "completed"),
            ("elimination", "completed"),
        ]
        assert not tutor.calls

    asyncio.run(run())


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_symmetric_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('交换a和b后，条件会改变', 0, False, [('method', 'symmetric')], ['condition_changes']),
        ('目标也改变', 1, False, [], ['target_changes']),
        ('令x=2a,y=b', 1, False, [('choice', 'x_2a_y_b')], []),
        ('这样换元是不合法，还是没有达到对称目的？', 1, True, [], []),
        ('令x=a,y=2b', 2, False, [], ['symmetric_construction']),
        ('s=x+y', 2, False, [], ['sum_definition']),
        ('p=xy', 3, False, [], ['product_definition']),
        ('条件是2p=s+3', 3, False, [('choice', 'double_p')], []),
        ('应当是p=s+3', 4, False, [], ['condition_in_sp']),
        ('s≥2√p也成立吗？这里只问原因，不提交答案。', 4, True, [('choice', 'p_ge')], []),
        ('我选s≥2√p，因为x和y都是正数', 5, False, [], ['sum_product_inequality']),
        ('s≤-2或s≥6', 5, False, [('choice', 'both')], []),
        ('为什么要舍去负数的那一支？', 5, True, [], []),
        ('因为s=x+y>0，所以s≥6', 6, False, [], ['s_range']),
        ('a=2b时取等，代回得到a=3,b=3/2', 7, False, [], ['equal_terms']),
    ]
    view = asyncio.run(replay('q30', turns))
    assert view['state']['choices']['inequality_form'] == 's_ge'


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_elimination_dialogue():
    from .reciprocal_live import replay

    turns = [
        ('a>0', 0, False, [('method', 'elimination'), ('choice', 'gt_0')], []),
        ('a=1为什么不行？', 0, True, [], []),
        ('2b(a-1)=a+3>0且b>0，所以a>1', 1, False, [], ['a_range']),
        ('我填3和1，这两个数为什么不对？请按我的选择乘回核对。', 1, True, [('fill', '3', 0), ('fill', '1', 1), ('submit',)], []),
        ('系数应该填4', 1, False, [], ['reciprocal_coefficient']),
        ('常数是2', 2, False, [], ['split_constant']),
        ('a-1和4/(a-1)是两个正项，积为4，是定积求和', 3, False, [], ['fixed_product_structure']),
        ('a+2b的最小值是4', 3, False, [], []),
        ('两项之和≥4，再加外面的2，所以a+2b≥6', 4, False, [], ['amgm_relation']),
        ('a-1=-2也满足平方等于4，为什么不能取？', 4, True, [], []),
        ('a-1=2，因此a=3,b=3/2时取等', 5, False, [], ['equal_terms']),
    ]
    view = asyncio.run(replay('q30', turns))
    assert view['state']['pairs'][1] == ['4', '2']


@pytest.mark.live_llm
@pytest.mark.skipif(os.getenv("RUN_TUTOR_LIVE") != "1", reason="Explicit live opt-in")
def test_live_alternative_inequality_after_local_progress():
    from .reciprocal_live import replay

    ops = [('method', 'symmetric'), ('fill', 'changed', 0), ('fill', 'changed', 1), ('submit',),
           ('choice', 'x_a_y_2b'), ('submit',), ('fill', 'x+y', 0), ('fill', 'xy', 1), ('submit',),
           ('choice', 'plus_3'), ('submit',), ('choice', 's_ge')]
    turns = [
        ('我当前选的s≥2√p与p≤s²/4等价吗？只是提问，先不要替我提交。', 4, True, ops, []),
        ('我改选p≤s²/4，由(x-y)²≥0可得', 5, False, [], ['sum_product_inequality']),
    ]
    view = asyncio.run(replay('q30', turns))
    assert view['state']['choices']['inequality_form'] == 'p_le'


def test_confirmed_fill_shows_authored_multiply_back_check():
    import sympy as sp
    from sympy.parsing.sympy_parser import (
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    from .test_q14 import confirmed_pair

    node = page_config()["routes"]["elimination"][1]
    html = page_text()
    templates = dict(re.findall(r'<template id="([^"]+)">(.*?)</template>', html, re.S))
    assert "attempt_calculations" not in json.dumps(load_lesson("q30"))
    a = sp.Symbol("a")

    def arg(text, i):
        if text[i] != "{":
            return text[i], i + 1
        depth = 0
        for j in range(i, len(text)):
            depth += {"{": 1, "}": -1}.get(text[j], 0)
            if depth == 0:
                return text[i + 1 : j], j + 1

    def plain(text):
        text = text.replace(r"\left", "").replace(r"\right", "")
        out, i = "", 0
        while i < len(text):
            if text.startswith(r"\frac", i):
                num, i = arg(text, i + 5)
                den, i = arg(text, i)
                out += f"(({plain(num)})/({plain(den)}))"
            elif text[i] in "{}":
                i += 1
            else:
                out += text[i]
                i += 1
        return out

    def parse(text):
        return parse_expr(
            plain(text).replace("^", "**"),
            local_dict={"a": a},
            transformations=standard_transformations + (implicit_multiplication_application,),
        )

    class QuestionTutor:
        async def respond(self, **kwargs):
            return Proposal(reply="先核对乘回结果。", intent="question", evidence=[], actions=[])

    target = a**2 + 3

    async def run():
        for p in node["interaction"]["terms"]:
            for q in node["interaction"]["terms"]:
                tid = node["attempt_calculations"][p][q]
                session = Session(load_lesson("q30"))
                view = await session.handle(
                    Event(
                        event_id="ask", kind="text", text="这个对吗？", revision=0, lesson_version=1,
                        pending_operations=pending(
                            [operation("method", "elimination")] + choose("gt_1") + pair(p, q)
                        ),
                    ),
                    QuestionTutor(),
                )
                if [p, q] == ["4", "2"]:
                    assert view["state"]["active"] == 2
                    assert tid == node["display"]
                    continue
                assert view["state"]["active"] == 1
                assert confirmed_pair(view) == [p, q]
                lines = re.findall(r"<p data-math-text>\$(.*?)\$</p>", templates[tid])
                left, right = lines[0].split("=")
                assert sp.simplify(parse(left) - target) == 0 and sp.expand(parse(right) - target) == 0
                attempt = sp.expand(sp.cancel((a - 1) * ((a - 1) + sp.Integer(p) / (a - 1) + sp.Integer(q))))
                mine = lines[2].strip("{}").removeprefix("=")
                assert sp.simplify(parse(lines[1]) - attempt) == 0
                assert sp.expand(parse(mine) - attempt) == 0
                assert sp.expand(attempt - target) != 0
                assert lines[3] == mine + r"\not\equiv a^2+3"

    asyncio.run(run())


def test_partial_evidence_accumulates_across_turns():
    class EvidenceTutor:
        def __init__(self, evidence):
            self.evidence = evidence

        async def respond(self, **kwargs):
            return Proposal(reply="已记录。", intent="answer", evidence=self.evidence, actions=[])

    async def run():
        for route, turns, actives in (
            ("symmetric", [["condition_changes"], ["target_changes"], ["symmetric_construction"], ["sum_definition", "product_definition"], ["condition_in_sp"]], [0, 1, 2, 3, 4]),
            ("elimination", [["a_range"], ["reciprocal_coefficient"], ["split_constant"]], [1, 1, 2]),
        ):
            session = Session(load_lesson("q30"))
            for i, evidence in enumerate(turns):
                view = await session.handle(
                    Event(
                        event_id=f"{route}-{i}", revision=session.revision, kind="text", text="本轮证据", lesson_version=1,
                        pending_operations=pending([operation("method", route)]) if i == 0 else [],
                    ),
                    EvidenceTutor(evidence),
                )
                assert view["state"]["active"] == actives[i]
            if route == "symmetric":
                assert view["state"]["pairs"][0] == ["changed", "changed"]
                assert view["state"]["pairs"][2] == ["x+y", "xy"]
                assert view["state"]["choices"]["construct_form"] == "x_a_y_2b"
                assert view["state"]["choices"]["condition_form"] == "plus_3"
            else:
                assert view["state"]["choices"]["a_range"] == "gt_1"
                assert view["state"]["pairs"][1] == ["4", "2"]

    asyncio.run(run())
