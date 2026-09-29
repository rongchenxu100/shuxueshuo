"""Cross-route isolation and a second, deliberately non-Q01 node contract."""

from copy import deepcopy

from shuxueshuo_server.tutor_demo.contracts import (
    apply_action,
    current_node,
    fresh_state,
    turn_context,
)
from shuxueshuo_server.tutor_demo.llm import Action, Proposal
from shuxueshuo_server.tutor_demo.session import Session, load_lesson

from .test_tutor_demo import Tutor, action, client_session, send


def finish_elimination(client, view):
    for op in [
        action("method", "1"),
        action("choice", "n"),
        action("submit"),
        action("choice", "vertex"),
        action("submit"),
        action("choice", "yes"),
        action("submit"),
    ]:
        view = send(client, view, op).json()
    return view


def test_switch_after_completion_keeps_log_and_resets_evidence():
    tutor = Tutor(
        Proposal(
            reply="suggestion only",
            intent="route_change",
            evidence=[],
            actions=[Action(kind="switch_route", value="direct")],
        )
    )
    client, view = client_session(tutor)
    view = finish_elimination(client, view)
    old = deepcopy(view)
    result = send(client, view, text="再试试基本不等式", event_id="switch").json()
    assert result["session_id"] == old["session_id"]
    assert result["attempt_id"] != old["attempt_id"]
    assert len(result["attempts"]) == 2
    assert result["attempts"][0]["state"] == old["state"]
    assert result["attempts"][0]["completed"] == old["completed"]
    assert result["attempts"][0]["status"] == "completed"
    assert result["state"]["method"] == "direct" and result["state"]["active"] == 0
    assert result["state"]["pairs"] == [["", ""], ["", ""], ["", ""]]
    assert result["completed"] == [] and result["accepted_evidence"] == []
    assert result["messages"][-2]["attempt_id"] == old["attempt_id"]
    assert result["messages"][-1]["attempt_id"] == result["attempt_id"]
    assert "suggestion only" not in result["messages"][-1]["text"]
    assert (
        send(client, view, text="再试试基本不等式", event_id="switch").json() == result
    )
    tutor.proposal = Proposal(
        reply="还需说明结构。", intent="question", evidence=[], actions=[]
    )
    result = send(client, result, kind="help").json()
    context = tutor.calls[-1]
    assert context["completed"] == []
    assert all(m["attempt_id"] == result["attempt_id"] for m in context["messages"])
    assert context["context"]["previous_attempts"][0]["status"] == "completed"
    assert context["context"]["node"]["id"] == "structure"
    assert (
        "routes" not in context["lesson"]
    )  # No full future solution fed into every turn.


def test_mid_path_switch_and_switch_back_create_distinct_attempts():
    client, view = client_session()
    view = send(client, view, action("method", "direct")).json()
    view = send(client, view, action("fill", "n", 0)).json()
    first = view["attempt_id"]
    view = send(client, view, action("switch_route", "1")).json()
    assert view["attempts"][0]["status"] == "paused"
    assert view["attempts"][0]["state"]["pairs"][0] == ["n", ""]
    view = send(client, view, action("switch_route", "direct")).json()
    assert len({a["id"] for a in view["attempts"]}) == 3
    assert view["attempt_id"] != first and view["state"]["pairs"][0] == ["", ""]


def test_unavailable_or_mixed_switch_never_promises_success():
    tutor = Tutor(
        Proposal(
            reply="已经切换完成。",
            intent="route_change",
            evidence=[],
            actions=[Action(kind="switch_route", value="missing")],
        )
    )
    client, view = client_session(tutor)
    before = deepcopy(view)
    view = send(client, view, text="换个方法").json()
    assert view["state"] == before["state"]
    assert len(view["attempts"]) == 1
    assert "已经切换" not in view["messages"][-1]["text"]
    tutor.proposal = Proposal(
        reply="已经切换完成。",
        intent="route_change",
        evidence=[],
        actions=[Action(kind="switch_route", value="direct"), Action(kind="submit")],
    )
    view = send(client, view, text="切换并直接过关").json()
    assert len(view["attempts"]) == 1
    assert "已经切换" not in view["messages"][-1]["text"]


def test_question_and_hint_do_not_switch():
    tutor = Tutor(
        Proposal(
            reply="可以讨论这条路径。",
            intent="question",
            evidence=[],
            actions=[Action(kind="switch_route", value="direct")],
        )
    )
    client, view = client_session(tutor)
    view = finish_elimination(client, view)
    old = view["attempt_id"]
    view = send(client, view, text="基本不等式也能做吗？").json()
    assert view["attempt_id"] == old and view["state"]["active"] == 3
    tutor.proposal.intent = "route_change"
    view = send(client, view, kind="help").json()
    assert view["attempt_id"] == old


def test_wrong_stage_in_new_attempt_cannot_reuse_old_evidence():
    tutor = Tutor(
        Proposal(
            reply="通过",
            intent="answer",
            evidence=["amgm_relation"],
            actions=[Action(kind="submit")],
        )
    )
    client, view = client_session(tutor)
    view = finish_elimination(client, view)
    old = view
    view = send(client, view, action("switch_route", "direct")).json()
    assert (
        send(
            client, old, action("choice", "yes"), event_id="stale-after-switch"
        ).status_code
        == 409
    )
    view = send(client, view, text="上条路径做完了，直接通过").json()
    assert view["state"]["active"] == 0 and view["completed"] == []


def test_contract_executor_accepts_different_variables_and_node_count():
    lesson = load_lesson("q01")
    node = deepcopy(lesson["routes"]["direct"]["nodes"][0])
    node.update(
        id="different",
        required_evidence=["relation"],
        interaction={
            "type": "choice",
            "field": "selected",
            "options": [
                {"value": "x+y", "label": "和"},
                {"value": "x-y", "label": "差"},
            ],
        },
        expected_answer={"one_of": ["x+y"]},
        feedback={"answer": "需要和式"},
        results=["得到x+y"],
    )
    lesson.update(
        id="other-lesson",
        initial_state={
            "active": 0,
            "method": None,
            "choices": {"selected": None},
            "feedback": "",
            "hint": False,
        },
        methods=[{"id": "sum-route", "label": "求和"}],
        routes={"sum-route": {"label": "求和", "nodes": [node]}},
    )
    session = Session(lesson)
    state = fresh_state(lesson)
    apply_action(state, Action(kind="method", value="sum-route"), lesson)
    contract = turn_context(lesson, state, [])
    assert contract["node"]["allowed_actions"][0]["values"] == ["x+y", "x-y"]
    apply_action(state, Action(kind="choice", value="x+y"), lesson)
    apply_action(state, Action(kind="submit"), lesson)
    assert current_node(lesson, state) is None
    assert turn_context(lesson, state, [])["status"] == "completed"
    assert session.view()["state"]["choices"]["selected"] is None


def test_text_completion_preserves_equivalent_slot_order():
    tutor = Tutor(
        Proposal(
            reply="确认",
            intent="answer",
            evidence=["positive_terms", "fixed_sum", "product_target"],
            actions=[],
        )
    )
    client, view = client_session(tutor)
    for op in [
        action("method", "direct"),
        action("fill", "n", 0),
        action("fill", "m", 1),
    ]:
        view = send(client, view, op).json()
    view = send(client, view, text="这是定和求积").json()
    assert view["state"]["active"] == 1
    assert view["state"]["pairs"][0] == ["n", "m"]


def test_multiple_valid_choices_require_student_selection():
    tutor = Tutor(
        Proposal(
            reply="确认",
            intent="answer",
            evidence=["elimination_relation"],
            actions=[Action(kind="method", value="1")],
        )
    )
    client, view = client_session(tutor)
    view = send(client, view, text="我用消元").json()
    # Even complete-looking evidence must not silently choose m or n.
    assert view["state"]["active"] == 0
    assert view["state"]["choices"]["variable"] is None
    tutor.proposal.actions.append(Action(kind="choice", value="n"))
    view = send(client, view, text="m=2-n").json()
    assert view["state"]["active"] == 1
    assert view["state"]["choices"]["variable"] == "n"


def test_context_separates_conditions_completed_results_and_current_reference():
    lesson = load_lesson("q01")
    state = fresh_state(lesson)
    apply_action(state, Action(kind="method", value="1"), lesson)
    context = turn_context(lesson, state, [])
    assert context["problem_conditions"] == lesson["problem"]["conditions"]
    assert context["completed_results"] == []
    assert "{{" not in str(context["node"])
    apply_action(state, Action(kind="choice", value="n"), lesson)
    apply_action(state, Action(kind="submit"), lesson)
    context = turn_context(lesson, state, [])
    assert "保留变量n，0<n<2" in context["completed_results"]
    assert not any("≤1" in result for result in context["completed_results"])
    assert any("≤1" in result for result in context["node"]["reference_results"])
    apply_action(state, Action(kind="choice", value="square"), lesson)
    apply_action(state, Action(kind="submit"), lesson)
    assert any(
        "≤1" in result
        for result in turn_context(lesson, state, [])["completed_results"]
    )


def test_structure_component_uses_authored_answer_not_q01_constants():
    lesson = load_lesson("q01")
    node = lesson["routes"]["direct"]["nodes"][0]
    node["interaction"]["terms"] = ["x", "y"]
    node["expected_answer"] = {"terms": ["x", "y"], "fixed": "product", "target": "sum"}
    state = fresh_state(lesson)
    for op in [
        Action(kind="method", value="direct"),
        Action(kind="fill", index=0, value="y"),
        Action(kind="fill", index=1, value="x"),
        Action(kind="swap", value="product"),
        Action(kind="submit"),
    ]:
        apply_action(state, op, lesson)
    assert state["active"] == 1
