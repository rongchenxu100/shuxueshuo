"""Five fixed items, immutable first answers, reversible latest-completed mastery."""

import json
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from ..product.db import lock, transaction
from . import assessment, associations


def one(c, sql, **values):
    return c.execute(text(sql), values).mappings().first()


def owned(c, aid, user, *, locked=False):
    a = one(
        c,
        "SELECT * FROM knowledge_drill_attempts WHERE id=:id AND user_id=:user"
        + (" FOR UPDATE" if locked else ""),
        id=aid,
        user=user,
    )
    if not a:
        raise HTTPException(404, "没有找到这轮练习。")
    return a


def view(c, a):
    items = []
    for row in c.execute(
        text("""SELECT r.* FROM knowledge_drill_answers r
      WHERE r.attempt_id=:id ORDER BY r.position"""),
        {"id": a["id"]},
    ).mappings():
        row = dict(row) | row['item_snapshot']
        item = {
            k: row[k]
            for k in (
                "position",
                "item_id",
                "selected",
                "is_correct",
                "answered_at",
                "statement_md",
                "question_type",
                "node_id",
                "entry_id",
                "content_hash",
            )
        }
        # Authored IDs such as "right" must not disclose the answer before submission.
        public_ids = {
            o["value"]: f"option-{i}" for i, o in enumerate(row["options"], 1)
        }
        item["options"] = [
            {"value": public_ids[o["value"]], "label": o["label"]}
            for o in row["options"]
        ]
        item["selected"] = (
            [public_ids[v] for v in row["selected"]]
            if row["selected"] is not None
            else None
        )
        if row["answered_at"]:
            answer = row["answer_spec"]["selected"]
            notes = [
                o["feedback"]
                for o in row["options"]
                if o["value"] in row["selected"] and o["value"] not in answer
            ]
            if not row["is_correct"] and not notes:
                notes = ["正确选项还没有选全。"]
            item.update(
                answer=[public_ids[v] for v in answer],
                feedback=notes,
                explanation=row["explanation_md"],
            )
        items.append(item)
    return dict(a, items=items)


def start(db, user, node, aid, previous=None, *, content_version=None, drill_version=None):
    with transaction(db) as c:
        lock(c, 'learning.publish', shared=True)
        current_version = associations.content_metadata(c)['content_version']
        # Retain the global check for legacy clients. New clients bind only to
        # this node's pool; the release version remains an audit field.
        if drill_version is None:
            associations.require_content(c, content_version if content_version is not None else current_version)
        lock(c, "drill", str(user), node)
        exists = one(c, "SELECT * FROM knowledge_drill_attempts WHERE id=:id", id=aid)
        if exists:
            if exists["user_id"] != UUID(str(user)) or exists["node_id"] != node:
                raise HTTPException(409, "练习编号已用于其他请求。")
            return view(c, exists)
        target = one(
            c, "SELECT id FROM knowledge_nodes WHERE id=:n AND is_active", n=node
        )
        if not target:
            raise HTTPException(404, "本节点已停用，不能开始新练习。")
        if not one(c, "SELECT id FROM knowledge_nodes WHERE id=:n AND kind IN ('knowledge','skill','method','problem_type')", n=node):
            raise HTTPException(422, '本类节点不单独评估掌握状态。')
        pool = list(c.execute(text(
            "SELECT * FROM knowledge_drill_items WHERE node_id=:node AND is_active ORDER BY item_id"
        ), {"node": node}).mappings())
        version = pool_hash(pool)
        if drill_version is not None and drill_version != version:
            raise HTTPException(409, {
                'code': 'learning_drill_changed',
                'message': '本节点的检测题已更新，请刷新后重新开始。',
                'drill_version': version,
            })
        current = one(
            c,
            "SELECT * FROM knowledge_drill_attempts WHERE user_id=:user AND node_id=:node AND status='in_progress' FOR UPDATE",
            user=user,
            node=node,
        )
        if previous:
            old = owned(c, previous, user, locked=True)
            if old["node_id"] != node or (current and current["id"] != previous):
                raise HTTPException(409, "练习已更新，请刷新后重试。")
        elif current:
            return view(c, current)
        if len(pool) < 5:
            raise HTTPException(409, "本节点可用题目不足五道。")
        if current:
            c.execute(
                text(
                    "UPDATE knowledge_drill_attempts SET status='closed',updated_at=clock_timestamp() WHERE id=:id"
                ),
                {"id": current["id"]},
            )
        a = one(
            c,
            "INSERT INTO knowledge_drill_attempts(id,user_id,node_id,content_version,association_hash) VALUES(:id,:user,:node,:version,:hash) RETURNING *",
            id=aid,
            user=user,
            node=node,
            version=current_version,
            hash=version,
        )
        for i, item in enumerate(secrets.SystemRandom().sample(pool, 5), 1):
            c.execute(
                text(
                    """INSERT INTO knowledge_drill_answers(attempt_id,position,item_id,node_id,entry_id,content_hash,item_snapshot)
                    VALUES(:id,:i,:item,:node,:entry,:hash,CAST(:snapshot AS jsonb))"""
                ),
                {'id': aid, 'i': i, 'item': item['item_id'], 'node': item['node_id'],
                 'entry': item['entry_id'], 'hash': item['content_hash'],
                 'snapshot': json.dumps({k: item[k] for k in (
                     'statement_md', 'question_type', 'options', 'answer_spec', 'explanation_md', 'origin')}, ensure_ascii=False)},
            )
        return view(c, a)


def answer(db, user, aid, position, selected):
    with transaction(db) as c:
        a = owned(c, aid, user, locked=True)
        row = one(
            c,
            """SELECT r.* FROM knowledge_drill_answers r
          WHERE attempt_id=:id AND position=:p""",
            id=aid,
            p=position,
        )
        if not row:
            raise HTTPException(404, "题目不属于本轮练习。")
        row = dict(row) | row['item_snapshot']
        public_ids = {
            f"option-{i}": o["value"] for i, o in enumerate(row["options"], 1)
        }
        if (
            len(set(selected)) != len(selected)
            or not set(selected) <= public_ids.keys()
            or (row["question_type"] != "multi" and len(selected) != 1)
        ):
            raise HTTPException(422, "请选择本题有效选项。")
        picked = sorted(public_ids[v] for v in selected)
        if row["answered_at"]:
            if picked != row["selected"]:
                raise HTTPException(409, "首答已保存，不能覆盖；可开始新一轮练习。")
            return view(c, a)
        if a["status"] != "in_progress":
            raise HTTPException(409, "本轮已结束。")
        c.execute(
            text("""UPDATE knowledge_drill_answers SET selected=CAST(:selected AS jsonb),is_correct=:correct,answered_at=clock_timestamp()
          WHERE attempt_id=:id AND position=:p AND answered_at IS NULL"""),
            {
                "selected": json.dumps(picked),
                "correct": picked == sorted(row["answer_spec"]["selected"]),
                "id": aid,
                "p": position,
            },
        )
        count = c.scalar(
            text(
                "SELECT count(*) FROM knowledge_drill_answers WHERE attempt_id=:id AND answered_at IS NOT NULL"
            ),
            {"id": aid},
        )
        if count == 5:
            a = one(
                c,
                "UPDATE knowledge_drill_attempts SET status='completed',completed_at=clock_timestamp(),updated_at=clock_timestamp() WHERE id=:id RETURNING *",
                id=aid,
            )
            assessment.evaluate_node(c, user, a['node_id'])
        else:
            a = one(c, "UPDATE knowledge_drill_attempts SET updated_at=clock_timestamp() WHERE id=:id RETURNING *", id=aid)
        return view(c, a)


def statuses(c, user):
    result = []
    for row in c.execute(
        text("""SELECT n.id AS node_id,n.kind,n.label,s.status,s.probability,s.strategy_version,s.evaluated_at,
      s.evidence_position,s.evidence_attempt_id AS attempt_id,a.completed_at,s.correct_count,
      (SELECT jsonb_agg(jsonb_build_object('item_id',q.item_id,'node_id',q.node_id,
          'entry_id',q.entry_id,'content_hash',q.content_hash) ORDER BY q.item_id)
       FROM knowledge_drill_items q WHERE q.node_id=n.id AND q.is_active) AS drill_pool,
      EXISTS(SELECT 1 FROM knowledge_drill_attempts p WHERE p.user_id=:user AND p.node_id=n.id AND p.status='in_progress') AS in_progress
      FROM knowledge_nodes n
      LEFT JOIN student_node_assessments s ON s.node_id=n.id AND s.user_id=:user
      LEFT JOIN knowledge_drill_attempts a ON a.id=s.evidence_attempt_id
      WHERE n.is_active AND n.kind IN ('knowledge','skill','method','problem_type') ORDER BY n.id"""),
        {"user": user},
    ).mappings():
        row = dict(row)
        pool = row.pop('drill_pool') or []
        row['item_count'] = len(pool)
        result.append(
            dict(
                row,
                status=row['status'] or 'unassessed',
                source="drill_first_answers",
                strategy_version=row['strategy_version'] or assessment.STRATEGY,
                eligible=row['item_count'] >= 5,
                drill_available=row['item_count'] >= 5,
                drill_count=row['item_count'],
                drill_version=pool_hash(pool),
            )
        )
    return result


def pool_hash(pool):
    from ..product.db import digest
    return digest([{'item_id': q['item_id'], 'node_id': q['node_id'],
                    'entry_id': q['entry_id'], 'content_hash': q['content_hash']} for q in pool])
