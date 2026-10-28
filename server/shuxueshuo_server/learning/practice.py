"""Persistent route evidence; grades are produced only by rules or the trusted tutor."""

import json
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import text

from ..product.db import lock, transaction
from ..tutor_demo.contracts import InvalidAction, apply_action, fresh_state, slot_count
from ..tutor_demo.llm import Action
from ..tutor_demo.session import load_lesson
from . import associations, graph_walk
from .drills import one
from .identity import canonical_id


def eid(value, suffix):
    return uuid5(NAMESPACE_URL, f"practice:{value}:{suffix}")


def owned(c, aid, user):
    a = one(
        c,
        "SELECT * FROM student_practice_attempts WHERE id=:id AND user_id=:u FOR UPDATE",
        id=aid,
        u=user,
    )
    if not a:
        raise HTTPException(404, "没有找到本次练习。")
    return a


def lesson(a):
    # Retired problems may no longer have a teacher file. The private contract was
    # fixed with the attempt, so history never depends on today's filesystem.
    if graph_walk.snapshot(a):
        raise HTTPException(409, '本题使用图谱交互课包，请从题页继续。')
    return a['problem_context'].get('_lesson') or load_lesson(a['problem_id'])


def nodes(a):
    if contract := graph_walk.snapshot(a):
        return graph_walk.route_steps(contract, a['route_id'])
    return lesson(a)['routes'][a['route_id']]['nodes']


def node(a, step):
    n = next((n for n in nodes(a) if n["id"] == step), None)
    if not n:
        raise HTTPException(422, "步骤不属于本次路线。")
    return n


def append(c, a, identity, step, kind, payload, related=None):
    old = one(c, "SELECT * FROM student_practice_events WHERE id=:id", id=identity)
    if old:
        if (
            old["attempt_id"] != a["id"]
            or old["step_id"] != step
            or old["event_type"] != kind
            or old["payload"] != payload
            or old["related_event_id"] != related
        ):
            raise HTTPException(409, "同一事件编号不能用于不同输入。")
        return old
    seq = c.scalar(
        text(
            "SELECT coalesce(max(sequence),0)+1 FROM student_practice_events WHERE attempt_id=:a"
        ),
        {"a": a["id"]},
    )
    return one(
        c,
        """INSERT INTO student_practice_events(id,attempt_id,step_id,sequence,event_type,payload,related_event_id)
      VALUES(:id,:a,:s,:seq,:kind,CAST(:payload AS jsonb),:related) RETURNING *""",
        id=identity,
        a=a["id"],
        s=step,
        seq=seq,
        kind=kind,
        payload=json.dumps(payload, ensure_ascii=False),
        related=related,
    )


def context(c, a, step):
    saved = one(
        c,
        "SELECT * FROM student_practice_events WHERE id=:id",
        id=eid(a["id"], step + ":context"),
    )
    if saved:
        return saved
    n = node(a, step)
    return append(
        c,
        a,
        eid(a["id"], step + ":context"),
        step,
        "context",
        {k: n[k] for k in ("question", "interaction", "expected_answer", "criteria") if k in n},
    )


def active_step(c, a):
    passed = set(
        c.execute(
            text(
                "SELECT step_id FROM student_step_results WHERE attempt_id=:a AND passed"
            ),
            {"a": a["id"]},
        ).scalars()
    )
    return next((n["id"] for n in nodes(a) if n["id"] not in passed), None)


def passing_rule_answers_for_attempts(c, attempt_ids):
    """Observed submissions only; a tutor conclusion carries no selected option."""
    answers = {}
    if not attempt_ids:
        return answers
    for row in c.execute(text('''
        SELECT r.attempt_id,r.step_id,input.payload AS answer FROM student_step_results r
        JOIN student_practice_events g ON g.attempt_id=r.attempt_id
          AND g.step_id=r.step_id AND g.sequence=r.summary_through_sequence
          AND g.event_type='grade' AND g.payload->>'result'='passed'
          AND g.payload->>'source'='rule'
        JOIN student_practice_events input ON input.id=g.related_event_id
          AND input.attempt_id=r.attempt_id AND input.step_id=r.step_id
          AND input.event_type='answer' AND input.sequence<g.sequence
        WHERE r.attempt_id=ANY(:attempts) AND r.passed'''),
                         {'attempts': list(attempt_ids)}).mappings():
        answers.setdefault(row['attempt_id'], {})[row['step_id']] = row['answer']
    return answers


def passing_rule_answers(c, a):
    return passing_rule_answers_for_attempts(c, [a['id']]).get(a['id'], {})


def confirmed_choices(c, a):
    return choices_from_rule_answers(a, passing_rule_answers(c, a))


def choices_from_rule_answers(a, answers):
    if graph_walk.snapshot(a):
        # Native routes already fix their references; they have no legacy
        # conditional-association fields to synthesize from student answers.
        return {}
    return {n['interaction']['field']: answers[n['id']]['value'] for n in nodes(a)
            if n['interaction']['type'] == 'choice' and n['id'] in answers}


def passed_answers(c, a):
    """Use the exact passing rule submission, or an established standard conclusion."""
    if graph_walk.snapshot(a):
        return passing_rule_answers(c, a)
    route = {n["id"]: n for n in nodes(a)}
    answers = {}
    for row in c.execute(
        text("""SELECT r.step_id,input.payload AS answer
          FROM student_step_results r
          LEFT JOIN student_practice_events g ON g.attempt_id=r.attempt_id
            AND g.step_id=r.step_id AND g.sequence=r.summary_through_sequence
            AND g.event_type='grade' AND g.payload->>'result'='passed'
            AND g.payload->>'source'='rule'
          LEFT JOIN student_practice_events input ON input.id=g.related_event_id
            AND input.attempt_id=r.attempt_id AND input.step_id=r.step_id
            AND input.event_type='answer' AND input.sequence<g.sequence
          WHERE r.attempt_id=:a AND r.passed"""),
        {"a": a["id"]},
    ).mappings():
        n = route[row["step_id"]]
        expected = n["expected_answer"]
        fallback = (
            {"value": expected["one_of"][0]}
            if n["interaction"]["type"] == "choice"
            else {
                "terms": list(expected["terms"]),
                **(
                    {"fixed": expected["fixed"]}
                    if n["interaction"]["type"] == "structure"
                    else {}
                ),
            }
        )
        answers[row["step_id"]] = fallback | (row["answer"] or {})
    return answers


def result(c, a):
    answers = passed_answers(c, a)
    steps = [
        dict(r, **({"answer": answers[r["step_id"]]} if r["passed"] else {}))
        for r in c.execute(
            text(
                "SELECT * FROM student_step_results WHERE attempt_id=:a ORDER BY last_submitted_at"
            ),
            {"a": a["id"]},
        ).mappings()
    ]
    return {
        k: a[k]
        for k in (
            "id",
            "problem_id",
            "route_id",
            "status",
            "started_at",
            "completed_at",
            "content_version",
        )
    } | {"steps": steps, "active_step": active_step(c, a),
         'confirmed_choices': confirmed_choices(c, a),
         'associations': a['association_snapshot']}


def start(db, user, pid, route, identity, previous=None, *, content_version=None):
    pid = canonical_id(pid)
    with transaction(db) as c:
        lock(c, 'learning.publish', shared=True)
        current_version = associations.content_metadata(c)['content_version']
        associations.require_content(c, content_version if content_version is not None else current_version)
        lock(c, "practice", str(user), pid)
        old = one(
            c, "SELECT * FROM student_practice_attempts WHERE id=:id", id=identity
        )
        if old:
            if (
                old["user_id"] != user
                or old["problem_id"] != pid
                or old["route_id"] != route
            ):
                raise HTTPException(409, "尝试编号已被使用。")
            return result(c, old)
        current = one(
            c,
            "SELECT * FROM student_practice_attempts WHERE user_id=:u AND problem_id=:p AND status='in_progress' FOR UPDATE",
            u=user,
            p=pid,
        )
        if previous:
            old = owned(c, previous, user)
            if old["problem_id"] != pid or (current and current["id"] != previous):
                if current and old["problem_id"] == pid:
                    raise_start_conflict(current)
                raise HTTPException(409, "练习已更新，请刷新后重试。")
        elif current:
            if current["route_id"] != route:
                raise_start_conflict(current)
            return result(c, current)
        p = one(c, "SELECT * FROM practice_problems WHERE id=:p AND is_active", p=pid)
        if not p:
            raise HTTPException(404, "题目或路线不可用于新练习。")
        snapshot = associations.snapshot(c, pid, route)
        snapshot.update(problem_label=p['label'], problem_path=p['path'])
        if current:
            c.execute(
                text(
                    "UPDATE student_practice_attempts SET status='closed',updated_at=clock_timestamp() WHERE id=:id"
                ),
                {"id": current["id"]},
            )
        a = one(
            c,
            """INSERT INTO student_practice_attempts(id,user_id,problem_id,route_id,problem_context,
              content_version,association_hash,association_snapshot)
          VALUES(:id,:u,:p,:r,CAST(:ctx AS jsonb),:version,:hash,CAST(:snapshot AS jsonb)) RETURNING *""",
            id=identity,
            u=user,
            p=pid,
            r=route,
            ctx=json.dumps(p["problem_data"], ensure_ascii=False),
            version=current_version,
            hash=snapshot['association_hash'],
            snapshot=json.dumps(snapshot, ensure_ascii=False),
        )
        context(c, a, nodes(a)[0]["id"])
        return result(c, a)


def raise_start_conflict(current):
    raise HTTPException(
        409,
        {
            "code": "practice_route_conflict",
            "message": "本题已有进行中的练习，请选择继续原路线或重新开始。",
            "current_attempt": {
                "id": str(current["id"]),
                "route_id": current["route_id"],
            },
        },
    )


def grade(c, a, step, source_id, outcome, source):
    identity = eid(source_id, "grade")
    if one(c, "SELECT id FROM student_practice_events WHERE id=:id", id=identity):
        return
    event = append(
        c, a, identity, step, "grade", {"result": outcome, "source": source}, source_id
    )
    # Discussion after passing is evidence but never overwrites the original step result.
    old = one(
        c,
        "SELECT * FROM student_step_results WHERE attempt_id=:a AND step_id=:s",
        a=a["id"],
        s=step,
    )
    if old and old["passed"]:
        return
    c.execute(
        text("""INSERT INTO student_step_results(attempt_id,step_id,passed,submit_count,wrong_count,last_grading_source,last_submitted_at,summary_through_sequence)
      VALUES(:a,:s,:passed,1,:wrong,:source,clock_timestamp(),:seq)
      ON CONFLICT(attempt_id,step_id) DO UPDATE SET passed=excluded.passed,submit_count=student_step_results.submit_count+1,
      wrong_count=student_step_results.wrong_count+excluded.wrong_count,last_grading_source=excluded.last_grading_source,
      last_submitted_at=excluded.last_submitted_at,summary_through_sequence=excluded.summary_through_sequence"""),
        {
            "a": a["id"],
            "s": step,
            "passed": outcome == "passed",
            "wrong": int(outcome == "wrong"),
            "source": source,
            "seq": event["sequence"],
        },
    )
    refresh_hint(c, a, step)
    if a["status"] == "in_progress" and active_step(c, a) is None:
        c.execute(
            text(
                "UPDATE student_practice_attempts SET status='completed',completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": a["id"]},
        )
        c.execute(
            text("""INSERT INTO student_learning_marks(user_id,problem_id,practiced) VALUES(:u,:p,true)
          ON CONFLICT(user_id,problem_id) DO UPDATE SET practiced=true"""),
            {"u": a["user_id"], "p": a["problem_id"]},
        )
    else:
        c.execute(
            text(
                "UPDATE student_practice_attempts SET updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": a["id"]},
        )


def ensure_current(c, a, step):
    node(a, step)
    if a["status"] != "in_progress" or active_step(c, a) != step:
        raise HTTPException(409, "步骤已更新，请继续当前步骤。")


def submit(db, user, aid, identity, step, answer):
    with transaction(db) as c:
        a = owned(c, aid, user)
        old = one(c, "SELECT * FROM student_practice_events WHERE id=:id", id=identity)
        if not old:
            revisiting = graph_walk.snapshot(a) and a['status'] != 'closed' and one(c,
                'SELECT step_id FROM student_step_results WHERE attempt_id=:a AND step_id=:s AND passed', a=aid, s=step)
            if revisiting and (node(a, step).get('option_context') or
                               node(a, step)['interaction']['type'] == graph_walk.EXACT_CHOICE or
                               node(a, step).get('require_complete_options')):
                raise HTTPException(409, '已完成的选项仅供回看；如需重做，请重新练习。')
            if not revisiting:
                ensure_current(c, a, step)
        n = node(a, step)
        if graph_walk.snapshot(a):
            if not old and (n['interaction']['type'] == graph_walk.EXACT_CHOICE or n.get('require_complete_options')):
                passed_ids = c.execute(text('SELECT step_id FROM student_step_results WHERE attempt_id=:a AND passed'),
                                       {'a': aid}).scalars().all()
                graph_walk.ensure_option_prerequisites(graph_walk.snapshot(a), a['route_id'], n, passed_ids)
            outcome = graph_walk.grade(n, answer, a['route_id'])
            ctx = context(c, a, step)
            append(c, a, identity, step, 'answer', answer, ctx['id'])
            if not old:
                grade(c, a, step, identity, outcome, 'rule')
            updated = owned(c, aid, user)
            next_step = active_step(c, updated)
            if next_step:
                context(c, updated, next_step)
            return result(c, updated)
        contract = lesson(a)
        state = fresh_state(contract)
        state["method"] = a["route_id"]
        state["active"] = next(i for i, x in enumerate(nodes(a)) if x["id"] == step)
        comp = n["interaction"]
        actions = []
        if comp["type"] == "choice":
            if set(answer) != {"value"} or not isinstance(answer.get("value"), str):
                raise HTTPException(422, "选择题需要一个选项。")
            actions = [Action(kind="choice", value=answer["value"])]
        else:
            if (
                set(answer) - {"terms", "fixed"}
                or not isinstance(answer.get("terms"), list)
                or len(answer["terms"]) != slot_count(comp)
                or any(not isinstance(v, str) for v in answer["terms"])
                or ("fixed" in answer and answer["fixed"] not in ("sum", "product"))
            ):
                raise HTTPException(422, "请提交本步选项。")
            actions = [
                Action(kind="fill", index=i, value=v)
                for i, v in enumerate(answer["terms"])
                if v
            ]
            if comp["type"] == "structure":
                actions.append(Action(kind="swap", value=answer.get("fixed", "sum")))
        try:
            for action in actions:
                apply_action(state, action, contract)
        except (InvalidAction, ValueError) as exc:
            raise HTTPException(422, "选项不属于本步。") from exc
        ctx = context(c, a, step)
        append(c, a, identity, step, "answer", answer, ctx["id"])
        if old:
            return result(c, a)
        try:
            apply_action(state, Action(kind="submit"), contract)
            outcome = "passed"
        except InvalidAction:
            outcome = (
                "incomplete"
                if (comp["type"] != "choice" and any(not x for x in answer["terms"]))
                else "wrong"
            )
        grade(c, a, step, identity, outcome, "rule")
        updated = owned(c, aid, user)
        next_step = active_step(c, updated)
        if next_step:
            context(c, updated, next_step)
        return result(c, updated)


def begin_dialogue(db, user, aid, event, step, problem_id):
    with transaction(db) as c:
        a = owned(c, aid, user)
        node(a, step)
        if a["problem_id"] != canonical_id(problem_id):
            raise HTTPException(409, "对话题目与练习记录不一致。")
        if not one(
            c,
            "SELECT id FROM student_practice_events WHERE id=:id",
            id=eid(f"{aid}:{event.event_id}", "student"),
        ):
            if a["status"] == "closed":
                raise HTTPException(409, "本次练习已关闭。")
            if a["status"] == "in_progress" and active_step(c, a) != step:
                raise HTTPException(409, "对话步骤与练习进度不一致。")
        context(c, a, step)
        append(
            c,
            a,
            eid(f"{aid}:{event.event_id}", "student"),
            step,
            "message",
            {
                "role": "student",
                "text": event.text if event.kind == "text" else "给点提示",
                "channel": "text",
            },
        )
        return a["route_id"]


def finish_dialogue(db, user, aid, event, step, response):
    with transaction(db) as c:
        a = owned(c, aid, user)
        student = eid(f"{aid}:{event.event_id}", "student")
        reply = (
            response["messages"][-1]["text"]
            if response["messages"] and response["messages"][-1]["role"] == "assistant"
            else ""
        )
        identity = eid(f"{aid}:{event.event_id}", "teacher")
        append(
            c,
            a,
            identity,
            step,
            "hint" if event.kind == "help" else "message",
            {"role": "tutor", "text": reply},
            student,
        )
        passed = any(
            x["node"] == step and x["route"] == a["route_id"]
            for x in response["completed"]
        )
        if (
            event.kind == "text"
            and a["status"] == "in_progress"
            and response.get("learning_intent") == "answer"
        ):
            grade(c, a, step, student, "passed" if passed else "incomplete", "llm")
        c.execute(
            text(
                "UPDATE student_practice_attempts SET updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": aid},
        )
        return str(identity)


def refresh_hint(c, a, step):
    # Only acknowledged display before the successful grading time counts.
    c.execute(
        text("""UPDATE student_step_results r SET hint_used=EXISTS(
      SELECT 1 FROM student_practice_events h WHERE h.attempt_id=r.attempt_id AND h.step_id=r.step_id
      AND h.event_type='hint' AND h.displayed_at IS NOT NULL
      AND (NOT r.passed OR h.displayed_at<=r.last_submitted_at))
      WHERE r.attempt_id=:a AND r.step_id=:s"""),
        {"a": a["id"], "s": step},
    )


def acknowledge(db, user, aid, identity):
    with transaction(db) as c:
        a = owned(c, aid, user)
        e = one(
            c,
            "SELECT * FROM student_practice_events WHERE id=:id AND attempt_id=:a AND (event_type='hint' OR payload->>'role'='tutor')",
            id=identity,
            a=aid,
        )
        if not e:
            raise HTTPException(404, "没有找到待确认内容。")
        c.execute(
            text(
                "UPDATE student_practice_events SET displayed_at=clock_timestamp() WHERE id=:id AND displayed_at IS NULL"
            ),
            {"id": identity},
        )
        refresh_hint(c, a, e["step_id"])
        c.execute(
            text(
                "UPDATE student_practice_attempts SET updated_at=clock_timestamp() WHERE id=:a"
            ),
            {"a": aid},
        )
        return {"saved": True}


def restore_session(db, user, aid, session, content_version=None):
    """Restore confirmed conclusions and original dialogue, never unsubmitted input."""
    from copy import deepcopy

    with transaction(db) as c:
        lock(c, 'learning.publish', shared=True)
        if content_version is not None:
            associations.require_content(c, content_version)
        a = owned(c, aid, user)
        if a["problem_id"] != session.lesson["id"] or a["status"] == "closed":
            raise HTTPException(409, "练习题目或状态已改变。")
        session.learning_practice_attempt_id = a['id']
        session.learning_content_version = a['content_version']
        session.learning_confirmed_choices = confirmed_choices(c, a)
        session.state["method"] = a["route_id"]
        answers = passed_answers(c, a)
        route = nodes(a)
        for index, n in enumerate(route):
            if n["id"] not in answers:
                break
            # Already established conclusions are supplied by the system on resume;
            # they are not new answers and are never written as new evidence.
            answer = answers[n["id"]]
            if n["interaction"]["type"] == "choice":
                session.state["choices"][n["interaction"]["field"]] = answer["value"]
            else:
                session.state["pairs"][index] = list(answer["terms"])
                if n["interaction"]["type"] == "structure":
                    session.state["swapped"] = answer["fixed"] == "product"
            session.state["active"] = index + 1
            session.completed.append(
                {
                    "stage": index,
                    "route": a["route_id"],
                    "node": n["id"],
                    "state": deepcopy(session.state),
                    "evidence": n["required_evidence"],
                }
            )
        positions = {n["id"]: i for i, n in enumerate(route)}
        for event in c.execute(
            text(
                "SELECT * FROM student_practice_events WHERE attempt_id=:a AND event_type IN ('message','hint') ORDER BY sequence"
            ),
            {"a": aid},
        ).mappings():
            p = event["payload"]
            session.messages.append(
                {
                    "role": "student" if p["role"] == "student" else "assistant",
                    "kind": "text",
                    "text": p["text"],
                    "stage": positions[event["step_id"]],
                    "route": a["route_id"],
                    "attempt_id": session.attempt_id,
                    "revision": 0,
                }
            )
        session.messages = session.messages[-200:]


def shown_reference(db, user, aid, identity, step, node_id, ref=None, resource_id=None):
    """Accept only a registered step reference, never client-authored tutor text."""
    with transaction(db) as c:
        a = owned(c, aid, user)
        node(a, step)
        if a["status"] == "closed":
            raise HTTPException(409, "本次练习已关闭。")
        if step != active_step(c, a) and not one(c, '''SELECT step_id FROM student_step_results
                WHERE attempt_id=:a AND step_id=:s AND passed''', a=aid, s=step):
            raise HTTPException(409, '请先完成前面的步骤，再查看本步提示。')
        old = one(c, 'SELECT * FROM student_practice_events WHERE id=:id', id=identity)
        requested = ref or node_id
        if old:
            if (old['attempt_id'] != aid or old['step_id'] != step
                    or old['payload'].get('ref') != requested
                    or old['payload'].get('resource_id') != resource_id):
                raise HTTPException(409, '同一事件编号不能用于不同输入。')
            return {'saved': True}
        if requested.split('#')[0] != node_id:
            raise HTTPException(422, '节点与条目引用不一致。')
        snapshot = a['association_snapshot']['steps'].get(step)
        choices = confirmed_choices(c, a)
        choice_nodes = [n for n in nodes(a) if n['interaction']['type'] == 'choice'
                        and 'field' in n['interaction']]
        options = {n['interaction']['field']: [o['value'] for o in n['interaction']['options']]
                   for n in choice_nodes}
        passed_steps = set(c.execute(text('''SELECT step_id FROM student_step_results
            WHERE attempt_id=:a AND passed'''), {'a': aid}).scalars())
        passed_fields = {n['interaction']['field'] for n in choice_nodes if n['id'] in passed_steps}
        tips = associations.select(snapshot.get('tip') if snapshot else None, choices, options, passed_fields)
        allowed = [b['value'] for b in tips['actual'] + tips['candidates']]
        tip = next((t for t in allowed if (t['ref'] == requested or
                   (ref is None and t['ref'].split('#')[0] == node_id))
                   and (resource_id is None or t.get('resource') == resource_id)), None)
        if not tip:
            raise HTTPException(422, '提示不属于本步已确认或可展示的关联。')
        reference = one(c, 'SELECT label,summary FROM knowledge_nodes WHERE id=:n', n=node_id)
        if not reference:
            raise HTTPException(422, '提示节点不存在。')
        # This endpoint is called only after the visible dialog has loaded successfully.
        append(
            c,
            a,
            identity,
            step,
            "hint",
            {
                "role": "tutor",
                "source": "node_explainer",
                "node_id": node_id,
                'ref': requested,
                'resource_id': resource_id,
                # Context comes from the authored snapshot; never accept client text.
                'text': reference['summary'],
                'candidate': not any(b['value'] == tip for b in tips['actual']),
            },
        )
        c.execute(
            text(
                "UPDATE student_practice_events SET displayed_at=clock_timestamp() WHERE id=:id AND displayed_at IS NULL"
            ),
            {"id": identity},
        )
        refresh_hint(c, a, step)
        return {"saved": True}


def evidence(c, user, node_id, entry=None):
    """History follows the recorded route snapshot, never today's mutable mapping."""
    exists = one(c, 'SELECT id FROM knowledge_nodes WHERE id=:n', n=node_id)
    if not exists:
        raise HTTPException(404, '没有找到节点。')
    # A dialogue or an acknowledged explainer can precede the first answer.
    # Context events alone are not observations: starting a round must not
    # manufacture evidence for an untouched step.
    # Filter by the historical node/entry references before loading step events.
    # Conditional references are candidates here; the confirmed choices below
    # still decide attribution. Displayed candidates remain display evidence.
    rows = c.execute(text('''WITH owned_attempts AS MATERIALIZED (
        SELECT * FROM student_practice_attempts WHERE user_id=:u
    ), observed AS (
        SELECT r.attempt_id,r.step_id FROM student_step_results r
        JOIN owned_attempts a ON a.id=r.attempt_id
        UNION
        SELECT e.attempt_id,e.step_id FROM student_practice_events e
        JOIN owned_attempts a ON a.id=e.attempt_id
        WHERE e.event_type IN ('answer','grade','message','hint')
    ), candidates AS (
        SELECT a.*,o.step_id FROM owned_attempts a JOIN observed o ON o.attempt_id=a.id
        WHERE EXISTS (
            SELECT 1 FROM jsonb_path_query(jsonb_build_array(
                a.association_snapshot->'types',a.association_snapshot->'methods',
                a.association_snapshot->'steps'->o.step_id->'refs'), '$.**') AS ref(value)
            WHERE jsonb_typeof(value)='string' AND (
                value #>> '{}' = :target OR
                (:whole_node AND split_part(value #>> '{}','#',1)=:n))
        ) OR EXISTS (
            SELECT 1 FROM student_practice_events h
            WHERE h.attempt_id=a.id AND h.step_id=o.step_id
              AND h.event_type='hint' AND h.payload->>'source'='node_explainer'
              AND h.displayed_at IS NOT NULL AND (
                COALESCE(h.payload->>'ref',h.payload->>'node_id')=:target OR
                (:whole_node AND split_part(
                    COALESCE(h.payload->>'ref',h.payload->>'node_id'),'#',1)=:n))
        )
    ) SELECT a.*,COALESCE(r.passed,false) AS passed,
        COALESCE(r.submit_count,0) AS submit_count,COALESCE(r.wrong_count,0) AS wrong_count,
        COALESCE(r.hint_used,e.hint_displayed,false) AS hint_used,
        r.last_submitted_at,r.last_grading_source,e.last_activity_at,e.shown_references
        FROM candidates a
        LEFT JOIN student_step_results r ON r.attempt_id=a.id AND r.step_id=a.step_id
        LEFT JOIN LATERAL (
            SELECT max(created_at) AS last_activity_at,
                bool_or(event_type='hint' AND displayed_at IS NOT NULL) AS hint_displayed,
                COALESCE(jsonb_agg(payload ORDER BY sequence) FILTER (
                    WHERE event_type='hint' AND payload->>'source'='node_explainer'
                    AND displayed_at IS NOT NULL),'[]'::jsonb) AS shown_references
            FROM student_practice_events WHERE attempt_id=a.id AND step_id=a.step_id
        ) e ON true
        ORDER BY e.last_activity_at DESC NULLS LAST,a.id DESC,a.step_id'''),
        {'u': user, 'n': node_id, 'target': node_id if entry is None else f'{node_id}#{entry}',
         'whole_node': entry is None}).mappings().all()
    answers = passing_rule_answers_for_attempts(c, {a['id'] for a in rows})
    result_rows, choices_by_attempt = [], {}
    for a in rows:
        snapshot = a['association_snapshot']
        step = snapshot.get('steps', {}).get(a['step_id'])
        if not step:
            continue
        if a['id'] not in choices_by_attempt:
            choices_by_attempt[a['id']] = choices_from_rule_answers(a, answers.get(a['id'], {}))
        choices = choices_by_attempt[a['id']]
        refs = associations.resolved_refs(step.get('refs'), choices)
        # A performed route is contextual evidence for its methods and type only.
        refs += associations.resolved_refs(snapshot.get('methods'), choices)
        refs += snapshot.get('types', [])
        context_match = any(associations.matches_ref(ref, node_id, entry) for ref in refs)
        # A displayed candidate is searchable as a display, but is never added
        # to the actually resolved method/skill references above.
        shown = [{'ref': p.get('ref') or p['node_id'],
                  'resource_id': p.get('resource_id'), 'candidate': p.get('candidate', False)}
                 for p in a['shown_references']]
        if not context_match and not any(
                associations.matches_ref(p['ref'], node_id, entry) for p in shown):
            continue
        row = {key: a[key] for key in ('problem_id', 'route_id', 'status', 'step_id',
               'passed', 'submit_count', 'wrong_count', 'hint_used', 'last_submitted_at',
               'last_grading_source', 'content_version', 'last_activity_at')}
        row.update(attempt_id=a['id'], label=snapshot.get('problem_label'),
                   path=snapshot.get('problem_path'), title=step['title'],
                   refs=list(dict.fromkeys(refs)), shown_references=shown,
                   source='practice_context' if context_match else 'shown_reference')
        result_rows.append(row)
        if len(result_rows) == 50:
            break
    # Drill evidence contains the original target even after reassignment of an item.
    drills = c.execute(text('''SELECT a.id AS attempt_id,a.status,a.content_version,
        r.position,r.item_id,r.node_id,r.entry_id,r.content_hash,r.selected,r.is_correct,r.answered_at
        FROM knowledge_drill_answers r JOIN knowledge_drill_attempts a ON a.id=r.attempt_id
        WHERE a.user_id=:u AND r.node_id=:n AND r.answered_at IS NOT NULL ''' +
        ('AND r.entry_id=:entry ' if entry is not None else '') +
        'ORDER BY r.answered_at DESC,a.id DESC LIMIT 50'),
        {'u': user, 'n': node_id, **({'entry': entry} if entry is not None else {})}).mappings()
    return {'evidence': result_rows, 'drills': [dict(row) for row in drills]}
