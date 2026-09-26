import asyncio
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from shuxueshuo_server.tutor_demo.api import create_app
from shuxueshuo_server.tutor_demo.llm import (
    Action,
    DeepSeekTutor,
    Proposal,
    TutorUnavailable,
)
from shuxueshuo_server.tutor_demo.session import Event, Session, load_lesson


class Tutor:
    def __init__(self, proposal=None):
        self.proposal = proposal or Proposal(
            reply="你觉得固定的是和还是积？", intent="question", evidence=[], actions=[]
        )
        self.calls = []

    async def respond(self, **data):
        self.calls.append(data)
        return self.proposal


def action(kind, value=None, index=None):
    return {"kind": kind, "value": value, "index": index}


def client_session(tutor=None):
    client = TestClient(create_app(tutor or Tutor()))
    view = client.post("/api/tutor-demo/sessions", json={"lesson_id": "q01"}).json()
    return client, view


def send(client, view, op=None, text=None, kind=None, event_id=None):
    body = {
        "event_id": event_id or str(view["revision"]),
        "revision": view["revision"],
        "kind": kind or ("text" if text else "ui"),
        "action": op,
        "text": text or "",
    }
    return client.post(
        f"/api/tutor-demo/sessions/{view['session_id']}/events", json=body
    )


@pytest.mark.parametrize(
    "route,technique", [("direct", None), ("1", "square"), ("1", "vertex")]
)
def test_full_ui_routes_and_public_contract(route, technique):
    tutor = Tutor()
    client, view = client_session(tutor)
    assert "criteria" not in str(view["lesson"])
    assert "verified_facts" not in str(view["lesson"])
    ops = [action("method", route)]
    if route == "direct":
        for stage in range(3):
            ops += [action("fill", "n", 0), action("fill", "m", 1), action("submit")]
    else:
        ops += [
            action("choice", "n"),
            action("submit"),
            action("choice", technique),
            action("submit"),
            action("choice", "yes"),
            action("submit"),
        ]
    for op in ops:
        response = send(client, view, op)
        assert response.status_code == 200, response.text
        view = response.json()
    assert view["state"]["active"] == 3
    assert len(view["completed"]) == 3
    assert len(view["messages"]) == len(ops)
    assert not tutor.calls


def test_invalid_ui_and_stale_revision():
    client, view = client_session()
    old = deepcopy(view)
    view = send(client, view, action("method", "direct")).json()
    assert send(client, old, action("method", "1"), event_id="stale").status_code == 409
    for op in [action("fill", "m", 0), action("fill", "m", 1), action("submit")]:
        view = send(client, view, op).json()
    assert view["state"]["active"] == 0
    assert view["state"]["feedback"]
    view = send(client, view, action("fill", "n", 1)).json()
    view = send(client, view, action("swap", "product")).json()
    view = send(client, view, action("submit")).json()
    assert view["state"]["active"] == 0
    assert "固定的是" in view["state"]["feedback"]


def test_text_equivalence_autofill_and_node_context():
    tutor = Tutor(
        Proposal(
            reply="是的，定和求积。我们接着看不等式。",
            intent="answer",
            evidence=["positive_terms", "fixed_sum", "product_target"],
            actions=[
                Action(**a)
                for a in [
                    action("method", "direct"),
                    action("fill", "m", 0),
                    action("fill", "n", 1),
                    action("submit"),
                ]
            ],
        )
    )
    client, view = client_session(tutor)
    view = send(client, view, text="正数的和为2，求积最大，用基本不等式").json()
    assert view["state"]["active"] == 1
    assert view["state"]["pairs"][0] == ["m", "n"]
    assert view["messages"][0]["kind"] == "text"
    assert len(view["completed"]) == 1
    tutor.proposal = Proposal(
        reply="你能把两个正数放进公式吗？", intent="question", evidence=[], actions=[]
    )
    view = send(client, view, kind="help").json()
    assert tutor.calls[-1]["context"]["node"]["id"] == "amgm"
    assert tutor.calls[-1]["completed"][0]["node"] == "structure"
    assert (
        tutor.calls[-1]["messages"] == []
    )  # Old node dialogue is represented by completed summary.


@pytest.mark.parametrize(
    "kind,intent", [("help", "answer"), ("text", "question"), ("text", "other")]
)
def test_question_or_help_cannot_mutate_even_with_model_actions(kind, intent):
    tutor = Tutor(
        Proposal(
            reply="先看条件。",
            intent=intent,
            evidence=[],
            actions=[Action(kind="method", value="direct")],
        )
    )
    client, view = client_session(tutor)
    view = send(client, view, text="我不懂，可以直接过关吗？", kind=kind).json()
    assert view["state"]["method"] is None


@pytest.mark.parametrize(
    "bad_actions,evidence",
    [
        (
            [
                action("method", "direct"),
                action("fill", "m", 0),
                action("fill", "n", 1),
                action("submit"),
            ],
            [],
        ),
        ([action("method", "direct"), action("fill", "x", 0)], []),
        (
            [
                action("method", "direct"),
                action("fill", "m", 0),
                action("fill", "n", 1),
                action("submit"),
                action("fill", "m", 0),
            ],
            ["positive_terms", "fixed_sum", "product_target"],
        ),
    ],
)
def test_invalid_proposal_is_atomic(bad_actions, evidence):
    tutor = Tutor(
        Proposal(
            reply="已经完成了。",
            intent="answer",
            evidence=evidence,
            actions=[Action(**a) for a in bad_actions],
        )
    )
    client, view = client_session(tutor)
    before = deepcopy(view["state"])
    view = send(client, view, text="请跳过这步").json()
    assert view["state"] == before
    assert "已经完成" not in view["messages"][-1]["text"]


def test_failure_retry_idempotency_and_new_session():
    class Flaky(Tutor):
        async def respond(self, **data):
            self.calls.append(data)
            if len(self.calls) == 1:
                raise TutorUnavailable("sensitive provider error")
            return self.proposal

    tutor = Flaky()
    client, view = client_session(tutor)
    response = send(client, view, text="为什么用这个方法", event_id="retry")
    assert response.status_code == 503
    assert "sensitive" not in response.text
    result = send(client, view, text="为什么用这个方法", event_id="retry").json()
    same = send(client, view, text="为什么用这个方法", event_id="retry").json()
    assert same == result
    assert len(tutor.calls) == 2
    assert len(result["messages"]) == 2
    fresh = client.post("/api/tutor-demo/sessions", json={"lesson_id": "q01"}).json()
    assert fresh["session_id"] != view["session_id"]
    assert fresh["messages"] == [] and fresh["revision"] == 0


def test_concurrent_event_rejected_after_llm_turn():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class Slow(Tutor):
            async def respond(self, **data):
                started.set()
                await release.wait()
                return self.proposal

        session = Session(load_lesson("q01"))
        task = asyncio.create_task(
            session.handle(
                Event(event_id="a", revision=0, kind="text", text="怎么做"), Slow()
            )
        )
        await started.wait()
        second = asyncio.create_task(
            session.handle(
                Event(
                    event_id="b",
                    revision=0,
                    kind="ui",
                    action=Action(kind="method", value="direct"),
                ),
                Tutor(),
            )
        )
        release.set()
        await task
        from shuxueshuo_server.tutor_demo.session import Conflict

        with pytest.raises(Conflict):
            await second
        assert session.state["method"] is None

    asyncio.run(scenario())


def test_jinja_prompts_render_current_contract():
    lesson = load_lesson("q01")
    messages = DeepSeekTutor().prompts(
        lesson=lesson,
        context={"node": lesson["routes"]["direct"]["nodes"][1]},
        completed=[],
        messages=[],
        event={"kind": "text", "text": "m+n≥2√mn"},
    )
    assert len(messages) == 2
    assert "JSON" in messages[0]["content"]
    assert "amgm_relation" in messages[1]["content"]


def test_complete_evidence_advances_without_redundant_model_submit():
    tutor = Tutor(
        Proposal(
            reply="是的，定和求积。",
            intent="answer",
            evidence=["positive_terms", "fixed_sum", "product_target"],
            actions=[
                Action(kind="method", value="direct"),
                Action(kind="fill", value="m", index=0),
                Action(kind="fill", value="n", index=1),
            ],
        )
    )
    client, view = client_session(tutor)
    view = send(client, view, text="两个正数，定和求积").json()
    assert view["state"]["active"] == 1


def test_authored_mapping_completes_text_when_model_omits_fields():
    tutor = Tutor(
        Proposal(
            reply="定和求积。",
            intent="answer",
            evidence=["positive_terms", "fixed_sum", "product_target"],
            actions=[Action(kind="method", value="direct"), Action(kind="submit")],
        )
    )
    client, view = client_session(tutor)
    view = send(client, view, text="两个正数，定和求积").json()
    assert view["state"]["pairs"][0] == ["m", "n"]
    assert view["state"]["active"] == 1
    assert (
        view["messages"][-1]["text"]
        == load_lesson("q01")["routes"]["direct"]["nodes"][0]["completion_reply"]
    )


def test_elimination_feasibility_evidence_fills_yes():
    tutor = Tutor(
        Proposal(
            reply="满足。",
            intent="answer",
            evidence=["feasible_values"],
            actions=[Action(kind="submit")],
        )
    )
    client, view = client_session(tutor)
    for op in [
        action("method", "1"),
        action("choice", "m"),
        action("submit"),
        action("choice", "square"),
        action("submit"),
    ]:
        view = send(client, view, op).json()
    view = send(client, view, text="都是正数，和等于2").json()
    assert view["state"]["active"] == 3
    assert view["state"]["elimination"]["feasible"] == "yes"
    view = send(client, view, text="我还有个问题").json()
    assert view["state"]["active"] == 3
    assert view["messages"][-1]["stage"] == 3
