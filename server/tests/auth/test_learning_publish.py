"""Structured publisher acceptance against an independent PostgreSQL instance."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from queue import Queue
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.learning import (
    assessment,
    associations,
    content,
    drills,
    practice,
)
from shuxueshuo_server.learning.content import (
    KEYS,
    load_content,
    publish,
    validate_graph,
)
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import digest, engine, lock, transaction
from shuxueshuo_server.tutor_demo.session import Session, load_lesson


@pytest.fixture(scope='module')
def authored():
    return load_content()


def version(rows):
    rows['_meta']['content_version'] = digest({name: rows[name] for name in KEYS})
    return rows


@pytest.fixture
def publisher():
    root = os.getenv('PRODUCT_TEST_DATA_DIR')
    if not root:
        pytest.skip('Requires independent PostgreSQL')
    db = engine(Settings.load('local', root, os.getenv('PRODUCT_TEST_INSTANCE', 'auth-stage1')).url('migration'))
    yield db
    db.dispose()


@pytest.fixture
def connection(publisher):
    # All test content/evidence changes roll back, even when assertions fail.
    with publisher.connect() as c:
        tx = c.begin()
        try:
            yield c
        finally:
            tx.rollback()


@pytest.mark.parametrize('invalid', [
    'duplicate_node', 'invalid_kind', 'invalid_subtype', 'missing_endpoint',
    'self_edge', 'invalid_relation', 'uses_direction', 'prerequisite_types',
    'duplicate_edge', 'prerequisite_cycle', 'chapter_object', 'rule_knowledge',
])
def test_direct_publishing_rejects_invalid_graph_before_transaction(invalid):
    nodes = [
        {'id': 'k1', 'kind': 'knowledge'}, {'id': 'k2', 'kind': 'knowledge'},
        {'id': 'm', 'kind': 'method'}, {'id': 's', 'kind': 'skill'},
        {'id': 'c', 'kind': 'chapter'},
        {'id': 'r', 'kind': 'judgment_rule', 'subtype': 'method_selection'},
    ]
    edges = [{'source_id': 'k1', 'target_id': 'k2', 'relation_type': 'prerequisite'}]
    if invalid == 'duplicate_node':
        nodes.append(dict(nodes[0]))
    elif invalid == 'invalid_kind':
        nodes[0]['kind'] = 'other'
    elif invalid == 'invalid_subtype':
        nodes[0]['subtype'] = 'technique'
    elif invalid == 'missing_endpoint':
        edges[0]['source_id'] = 'missing'
    elif invalid == 'self_edge':
        edges[0]['target_id'] = 'k1'
    elif invalid == 'invalid_relation':
        edges[0]['relation_type'] = 'other'
    elif invalid == 'uses_direction':
        edges[0].update(target_id='s', relation_type='uses')
    elif invalid == 'prerequisite_types':
        edges[0]['source_id'] = 'm'
    elif invalid == 'duplicate_edge':
        edges.append(dict(edges[0]))
    elif invalid == 'chapter_object':
        edges[0].update(source_id='c', relation_type='contains')
    elif invalid == 'rule_knowledge':
        edges[0].update(source_id='r', relation_type='uses')
    else:
        edges.append({'source_id': 'k2', 'target_id': 'k1', 'relation_type': 'prerequisite'})
    with pytest.raises(ValueError):
        publish(None, {'knowledge_nodes': nodes, 'knowledge_edges': edges})


def test_shared_export_has_complete_next_content(authored):
    assert len(authored['practice_problems']) == 40
    assert len(authored['practice_routes']) == 51
    assert len(authored['practice_steps']) == 266
    assert len(authored['knowledge_nodes']) == 92
    assert len(authored['knowledge_drill_items']) == 177
    assert authored['_meta']['counts']['eligible_drill_nodes'] == 16
    assert len({q['item_id'] for q in authored['knowledge_drill_items']}) == 177
    assert len([q for q in authored['knowledge_drill_items'] if q['node_id'] == 'amgm-formula']) == 1
    assert len(set(validate_graph(authored['knowledge_nodes'], authored['knowledge_edges']).values())) == 9


@pytest.mark.parametrize('change', ['missing_entry', 'missing_resource', 'unmapped_tip', 'wrong_method_kind', 'invalid_answer', 'version'])
def test_invalid_export_is_rejected_without_database(authored, change):
    rows = deepcopy(authored)
    step = next(s for s in rows['practice_steps'] if s['problem_id'] == 'basic-inequality-q01' and s['route_id'] == 'direct' and s['step_id'] == 'structure')
    if change == 'missing_entry':
        step['refs'] = ['amgm-formula#missing']
    elif change == 'missing_resource':
        step['tip']['resource'] = 'missing-resource'
    elif change == 'unmapped_tip':
        step['refs'] = ['inequality-properties']
    elif change == 'wrong_method_kind':
        rows['practice_routes'][0]['methods'] = ['amgm-formula']
    elif change == 'invalid_answer':
        rows['knowledge_drill_items'][0]['answer_spec']['selected'] = ['missing-option']
    else:
        rows['_meta']['content_version'] = 'not-the-export'
    if change != 'version':
        version(rows)
    with pytest.raises(ValueError):
        publish(None, rows)


@pytest.mark.parametrize('field', ['unexpected', 'id) VALUES (NULL); DELETE FROM users; --'])
def test_export_rejects_unknown_columns_before_opening_transaction(authored, field):
    rows = deepcopy(authored)
    rows['knowledge_nodes'][0][field] = 'invalid'
    with pytest.raises(ValueError, match='invalid public content fields'):
        publish(None, version(rows))


@pytest.mark.parametrize('table,keys', [
    ('users', ['id']),
    ('knowledge_nodes; DELETE FROM users', ['id']),
    ('knowledge_nodes', ['id) DO NOTHING; DELETE FROM users; --']),
])
def test_writer_rejects_unregistered_tables_and_keys(table, keys):
    with pytest.raises(ValueError, match='invalid public content table or key'):
        content._write(None, table, {'id': 'invalid'}, keys)


def test_writer_revalidation_rolls_back_prior_changes(publisher, authored, monkeypatch):
    publish(publisher, authored)
    original = content._write

    def changed_during_publication(c, name, row, keys):
        if name == 'knowledge_drill_items':
            row = {**row, 'unexpected': 'invalid'}
        original(c, name, row, keys)

    rows = deepcopy(authored)
    rows['knowledge_nodes'][0]['label'] = 'INVALID FIELD MUST ROLLBACK'
    monkeypatch.setattr(content, '_write', changed_during_publication)
    with pytest.raises(ValueError, match='invalid public content fields'):
        publish(publisher, version(rows))
    with transaction(publisher) as c:
        assert not c.scalar(text("SELECT count(*) FROM knowledge_nodes WHERE label='INVALID FIELD MUST ROLLBACK'"))
        assert associations.content_metadata(c)['content_version'] == authored['_meta']['content_version']


def test_import_repeat_and_transaction_rollback(publisher, authored):
    before = publish(publisher, authored)
    assert publish(publisher, authored) == before
    with transaction(publisher) as c:
        previous = c.scalar(text('SELECT count(*) FROM learning_content_releases'))
    changed = deepcopy(authored)
    changed['knowledge_nodes'][0]['label'] = 'MUST ROLLBACK'
    changed['knowledge_entries'][0]['position'] = -1
    with pytest.raises(DBAPIError):
        publish(publisher, version(changed))
    with transaction(publisher) as c:
        assert c.scalar(text("SELECT count(*) FROM knowledge_nodes WHERE label='MUST ROLLBACK'")) == 0
        assert c.scalar(text('SELECT count(*) FROM learning_content_releases')) == previous
    changed = deepcopy(authored)
    changed['practice_problems'][0]['contract_hash'] = 'different'
    with pytest.raises(ValueError, match='teaching contract changed'):
        publish(publisher, version(changed))


def student(c):
    user = uuid4()
    c.execute(text('INSERT INTO users(id,key,display_name) VALUES(:id,:key,:name)'),
              {'id': user, 'key': 'publish-test-' + str(user), 'name': 'Publisher test'})
    return user


@pytest.fixture
def content_readers(publisher, authored):
    publish(publisher, authored)
    with transaction(publisher) as c:
        users = [student(c) for _ in range(3)]
    pid, route, node = 'basic-inequality-q01', 'direct', 'method-amgm-direct'
    aid = practice.start(publisher, users[2], pid, route, uuid4())['id']
    current = authored['_meta']['content_version']
    try:
        yield [
            lambda: practice.start(publisher, users[0], pid, route, uuid4(), content_version=current),
            lambda: drills.start(publisher, users[1], node, uuid4(), content_version=current),
            lambda: practice.restore_session(publisher, users[2], aid, Session(load_lesson(pid)), current),
        ]
    finally:
        with transaction(publisher) as c:
            for user in users:
                params = {'u': user}
                for table in ('student_step_results', 'student_practice_events'):
                    c.execute(text(f'DELETE FROM {table} WHERE attempt_id IN (SELECT id FROM student_practice_attempts WHERE user_id=:u)'), params)
                c.execute(text('DELETE FROM student_practice_attempts WHERE user_id=:u'), params)
                c.execute(text('DELETE FROM knowledge_drill_answers WHERE attempt_id IN (SELECT id FROM knowledge_drill_attempts WHERE user_id=:u)'), params)
                c.execute(text('DELETE FROM knowledge_drill_attempts WHERE user_id=:u'), params)


def test_content_readers_share_publication_lock(publisher, content_readers):
    # Keep a fourth reader open: an accidental exclusive start/restore lock
    # cannot finish while this transaction remains alive.
    with ThreadPoolExecutor(max_workers=3) as pool, transaction(publisher) as c:
        lock(c, 'learning.publish', shared=True)
        pending = [pool.submit(read) for read in content_readers]
        for call in pending:
            call.result(timeout=5)


def test_exclusive_publication_blocks_readers_before_attempt_locks(publisher, content_readers):
    attempted = Queue()

    def before_lock(_conn, _cursor, statement, _parameters, _context, _many):
        if statement == 'SELECT pg_advisory_xact_lock_shared(%(key)s)':
            attempted.put(True)

    event.listen(publisher, 'before_cursor_execute', before_lock)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            with transaction(publisher) as c:
                lock(c, 'learning.publish')
                pending = [pool.submit(read) for read in content_readers]
                for _ in pending:
                    attempted.get(timeout=5)
                assert not any(call.done() for call in pending)
            for call in pending:
                call.result(timeout=5)
    finally:
        event.remove(publisher, 'before_cursor_execute', before_lock)


def test_real_publisher_waits_for_shared_reader_and_commits_after_release(publisher, authored):
    attempted = Event()

    def before_lock(_conn, _cursor, statement, _parameters, _context, _many):
        if statement == 'SELECT pg_advisory_xact_lock(%(key)s)':
            attempted.set()

    event.listen(publisher, 'before_cursor_execute', before_lock)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction(publisher) as c:
                lock(c, 'learning.publish', shared=True)
                pending = pool.submit(publish, publisher, authored)
                assert attempted.wait(5)
                assert not pending.done()
            assert pending.result(timeout=5)['knowledge_nodes'] == len(authored['knowledge_nodes'])
    finally:
        event.remove(publisher, 'before_cursor_execute', before_lock)


def test_mixed_content_readers_and_publishers_have_no_lock_order_deadlock(publisher, authored, content_readers):
    # Exercise the actual entry points, including restored attempt row locks,
    # while publishers repeatedly acquire the same gate exclusively.
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = []
        for _ in range(3):
            pending.extend(pool.submit(read) for read in content_readers)
            pending.append(pool.submit(publish, publisher, authored))
        for call in pending:
            call.result(timeout=10)


def test_association_change_closes_only_affected_route_preserves_evidence(connection, authored):
    c, user = connection, student(connection)
    publish(c, authored)
    pid = 'basic-inequality-q01'
    attempts = {}
    for rid in ('direct', 'elimination'):
        snapshot = associations.snapshot(c, pid, rid)
        aid = attempts[rid] = uuid4()
        c.execute(text("""INSERT INTO student_practice_attempts(id,user_id,problem_id,route_id,problem_context,content_version,association_hash,association_snapshot)
            VALUES(:id,:u,:p,:r,'{}',:v,:h,CAST(:s AS jsonb))"""),
            {'id': aid, 'u': user if rid == 'direct' else student(c), 'p': pid, 'r': rid, 'v': authored['_meta']['content_version'], 'h': snapshot['association_hash'], 's': json.dumps(snapshot)})
    c.execute(text("""INSERT INTO student_step_results(attempt_id,step_id,passed,submit_count,wrong_count,hint_used,last_grading_source,last_submitted_at,summary_through_sequence)
        VALUES(:a,'structure',true,1,0,false,'rule',now(),1)"""), {'a': attempts['direct']})
    before = practice.evidence(c, user, 'amgm-formula')['evidence']
    assert before
    # Pure prose publishes a new content version but leaves both rounds in progress.
    prose = deepcopy(authored)
    prose['knowledge_nodes'][0]['summary'] += '（修订说明）'
    publish(c, version(prose))
    assert c.scalar(text("SELECT count(*) FROM student_practice_attempts WHERE id IN (:direct,:elimination) AND status='in_progress'"), attempts) == 2
    changed = deepcopy(authored)
    step = next(s for s in changed['practice_steps'] if (s['problem_id'], s['route_id'], s['step_id']) == (pid, 'direct', 'structure'))
    step['refs'], step['tip'] = ['inequality-properties'], None
    route = next(r for r in changed['practice_routes'] if (r['problem_id'], r['route_id']) == (pid, 'direct'))
    route['association_hash'] = digest(step['refs'])
    publish(c, version(changed))
    statuses = dict(c.execute(text('SELECT route_id,status FROM student_practice_attempts WHERE id IN (:direct,:elimination)'), attempts).all())
    assert statuses == {'direct': 'closed', 'elimination': 'in_progress'}
    after = practice.evidence(c, user, 'amgm-formula')['evidence']
    assert after[0]['refs'] == before[0]['refs']
    assert after[0]['attempt_id'] == before[0]['attempt_id']
    assert not practice.evidence(c, user, 'inequality-properties')['evidence']


def test_drill_reassignment_closes_open_round_and_preserves_target_and_state(connection, authored):
    c, user = connection, student(connection)
    publish(c, authored)
    item = next(q for q in authored['knowledge_drill_items'] if q['node_id'] == 'method-amgm-direct')
    active, completed = uuid4(), uuid4()
    for aid, status in ((active, 'in_progress'), (completed, 'completed')):
        c.execute(text("""INSERT INTO knowledge_drill_attempts(id,user_id,node_id,status,completed_at,content_version,association_hash)
            VALUES(:id,:u,:n,:s,CASE WHEN :s='completed' THEN clock_timestamp() END,:v,'pool')"""),
            {'id': aid, 'u': user, 'n': item['node_id'], 's': status, 'v': authored['_meta']['content_version']})
    c.execute(text("""INSERT INTO knowledge_drill_answers(attempt_id,position,item_id,node_id,entry_id,content_hash,item_snapshot,selected,is_correct,answered_at)
        VALUES(:a,1,:item,:n,:e,:h,CAST(:snapshot AS jsonb),'[]',true,now())"""),
        {'a': active, 'item': item['item_id'], 'n': item['node_id'], 'e': item['entry_id'], 'h': item['content_hash'], 'snapshot': json.dumps(item)})
    c.execute(text("""INSERT INTO student_node_assessments(user_id,node_id,status,strategy_version,evidence_attempt_id,evidence_position,correct_count)
        VALUES(:u,:n,'mastered','drill_round_v1',:a,5,5)"""), {'u': user, 'n': item['node_id'], 'a': completed})
    before = dict(c.execute(text('SELECT id,updated_at FROM knowledge_drill_attempts WHERE user_id=:u'), {'u': user}).all())
    changed = deepcopy(authored)
    moving = next(q for q in changed['knowledge_drill_items'] if q['item_id'] == item['item_id'])
    moving['node_id'], moving['entry_id'] = 'amgm-formula', None
    publish(c, version(changed))
    assert c.scalar(text('SELECT status FROM knowledge_drill_attempts WHERE id=:id'), {'id': active}) == 'closed'
    assert c.scalar(text('SELECT status FROM student_node_assessments WHERE user_id=:u'), {'u': user}) == 'mastered'
    assert practice.evidence(c, user, item['node_id'])['drills'][0]['item_id'] == item['item_id']
    assert not practice.evidence(c, user, 'amgm-formula')['drills']
    assert c.scalar(text('SELECT node_id FROM knowledge_drill_answers WHERE attempt_id=:a'), {'a': active}) == item['node_id']
    after = dict(c.execute(text('SELECT id,updated_at FROM knowledge_drill_attempts WHERE user_id=:u'), {'u': user}).all())
    assert after[active] > before[active]
    assert after[completed] == before[completed]


def test_drill_first_answers_update_activity_once_and_closure_updates_time(publisher, authored, auth):
    publish(publisher, authored)
    with transaction(publisher) as c:
        user = student(c)
    aid, node = uuid4(), 'method-amgm-direct'
    try:
        current = drills.start(auth.db, user, node, aid)
        assert current['updated_at'] >= current['started_at']
        with transaction(publisher) as c:
            fixed = c.execute(text('SELECT position,item_snapshot FROM knowledge_drill_answers WHERE attempt_id=:a ORDER BY position'), {'a': aid}).mappings().all()
        for row in fixed:
            selected = [f'option-{i}' for i, option in enumerate(row['item_snapshot']['options'], 1)
                        if option['value'] in row['item_snapshot']['answer_spec']['selected']]
            previous = current['updated_at']
            current = drills.answer(auth.db, user, aid, row['position'], selected)
            assert current['updated_at'] > previous
            assert drills.answer(auth.db, user, aid, row['position'], selected)['updated_at'] == current['updated_at']
        assert current['status'] == 'completed'
        assert current['updated_at'] >= current['completed_at']
        next_round = drills.start(auth.db, user, node, uuid4())
        drills.start(auth.db, user, node, uuid4(), next_round['id'])
        with transaction(publisher) as c:
            closed = drills.owned(c, next_round['id'], user)
            assert closed['status'] == 'closed' and closed['updated_at'] > next_round['updated_at']
            assert drills.owned(c, aid, user)['updated_at'] == current['updated_at']
    finally:
        with transaction(publisher) as c:
            c.execute(text('DELETE FROM student_node_assessments WHERE user_id=:u'), {'u': user})
            c.execute(text('DELETE FROM knowledge_drill_answers WHERE attempt_id IN (SELECT id FROM knowledge_drill_attempts WHERE user_id=:u)'), {'u': user})
            c.execute(text('DELETE FROM knowledge_drill_attempts WHERE user_id=:u'), {'u': user})


def test_drill_activity_migration_backfills_existing_records(publisher):
    migration = (Path(__file__).resolve().parents[2] / 'alembic/versions/0012_drill_updated_at.sql').read_text()
    with publisher.connect() as c, c.begin():
        c.exec_driver_sql('CREATE TEMP TABLE knowledge_drill_attempts(id int PRIMARY KEY,started_at timestamptz NOT NULL,completed_at timestamptz) ON COMMIT DROP')
        c.exec_driver_sql('CREATE TEMP TABLE knowledge_drill_answers(attempt_id int,answered_at timestamptz) ON COMMIT DROP')
        c.exec_driver_sql("""INSERT INTO knowledge_drill_attempts VALUES
            (1,'2026-10-13T01:00:00Z',NULL),
            (2,'2026-10-13T01:00:00Z',NULL),
            (3,'2026-10-13T01:00:00Z','2026-10-13T03:00:00Z')""")
        c.exec_driver_sql("INSERT INTO knowledge_drill_answers VALUES (2,'2026-10-13T02:00:00Z'),(3,'2026-10-13T02:00:00Z')")
        c.execute(text(migration))
        assert c.execute(text('SELECT id,extract(hour from updated_at) FROM knowledge_drill_attempts ORDER BY id')).all() == [(1, 1), (2, 2), (3, 3)]
        c.exec_driver_sql("INSERT INTO knowledge_drill_attempts(id,started_at) VALUES (4,clock_timestamp())")
        assert c.scalar(text('SELECT updated_at IS NOT NULL FROM knowledge_drill_attempts WHERE id=4'))


def test_removed_content_is_retired_and_memberships_pruned(connection, authored):
    c = connection
    expanded = deepcopy(authored)
    extra = {**deepcopy(authored['knowledge_nodes'][0]), 'id': 'temporary-publisher-node'}
    extra['body'] = {**extra['body'], 'id': extra['id']}
    expanded['knowledge_nodes'].append(extra)
    expanded['practice_topics'].append({'id': 'temporary-topic', 'label': 'temporary', 'path': '/temporary/', 'body': {}, 'groups': [], 'is_active': True})
    expanded['practice_topic_problems'].append({'topic_id': 'temporary-topic', 'problem_id': authored['practice_problems'][0]['id'], 'position': 0})
    publish(c, version(expanded))
    publish(c, authored)
    assert c.scalar(text("SELECT is_active FROM knowledge_nodes WHERE id='temporary-publisher-node'")) is False
    assert c.scalar(text("SELECT is_active FROM practice_topics WHERE id='temporary-topic'")) is False
    assert c.scalar(text("SELECT count(*) FROM practice_topic_problems WHERE topic_id='temporary-topic'")) == 0


def test_identity_migration_preserves_records_and_rejects_collision(publisher):
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/0008_practice_identity.sql"
    ).read_text()
    # A temporary table shadows only this connection's table. No student data is touched.
    with publisher.connect() as c, c.begin():
        c.exec_driver_sql(
            "CREATE TEMP TABLE student_learning_marks(user_id uuid,problem_id text,practiced boolean,learning_status text,PRIMARY KEY(user_id,problem_id)) ON COMMIT DROP"
        )
        user = uuid4()
        c.execute(
            text(
                "INSERT INTO student_learning_marks VALUES(:u,'q01',true,'mastered'),(:u,'quadratic-always-q01',true,'needs_review')"
            ),
            {"u": user},
        )
        c.execute(text(migration))
        actual = c.execute(
            text(
                "SELECT problem_id,practiced,learning_status FROM student_learning_marks ORDER BY problem_id"
            )
        ).all()
        assert actual == [
            ("basic-inequality-q01", True, "mastered"),
            ("quadratic-always-q01", True, "needs_review"),
        ]
        c.exec_driver_sql("DROP TABLE practice_id_migration")
        c.execute(text(migration))
        assert (
            c.execute(
                text(
                    "SELECT problem_id,practiced,learning_status FROM student_learning_marks ORDER BY problem_id"
                )
            ).all()
            == actual
        )
        c.exec_driver_sql("DROP TABLE practice_id_migration")
        c.execute(
            text(
                "INSERT INTO student_learning_marks VALUES(:u,'q01',false,'unmarked')"
            ),
            {"u": user},
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            c.execute(text(migration))
        assert c.scalar(text("SELECT count(*) FROM student_learning_marks")) == 3




def test_integrity_migration_preserves_display_time_and_raw_text(publisher):
    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/0010_learning_record_integrity.sql"
    ).read_text()
    with publisher.connect() as c, c.begin():
        c.exec_driver_sql(
            "CREATE TEMP TABLE knowledge_nodes(id text PRIMARY KEY) ON COMMIT DROP"
        )
        c.exec_driver_sql(
            "CREATE TEMP TABLE student_practice_events(id int PRIMARY KEY,event_type text,payload jsonb) ON COMMIT DROP"
        )
        c.exec_driver_sql("INSERT INTO knowledge_nodes VALUES ('existing')")
        c.exec_driver_sql("""INSERT INTO student_practice_events VALUES
          (1,'hint','{"role":"tutor","text":"原始提示","displayed_at":"2026-10-08T01:02:03Z"}'),
          (2,'answer','{"value":"wrong"}'),
          (3,'message','{"role":"tutor","text":"原始对话"}')""")
        c.execute(text(migration))
        events = (
            c.execute(text("SELECT * FROM student_practice_events ORDER BY id"))
            .mappings()
            .all()
        )
        assert events[0]["payload"] == {"role": "tutor", "text": "原始提示"}
        assert events[0]["displayed_at"].isoformat() == "2026-10-08T01:02:03+00:00"
        assert (
            events[1]["payload"] == {"value": "wrong"}
            and events[1]["displayed_at"] is None
        )
        assert (
            events[2]["payload"] == {"role": "tutor", "text": "原始对话"}
            and events[2]["displayed_at"] is None
        )
        assert c.scalar(text("SELECT is_active FROM knowledge_nodes")) is True
        with pytest.raises(DBAPIError), c.begin_nested():
            c.exec_driver_sql(
                "UPDATE student_practice_events SET displayed_at=now() WHERE id=2"
            )


def test_retired_problem_history_does_not_read_current_teacher_file(connection, authored, monkeypatch):
    c, user = connection, student(connection)
    publish(c, authored)
    pid, rid, aid = 'basic-inequality-q01', 'direct', uuid4()
    snapshot = associations.snapshot(c, pid, rid)
    problem = next(p for p in authored['practice_problems'] if p['id'] == pid)
    c.execute(text("""INSERT INTO student_practice_attempts(id,user_id,problem_id,route_id,problem_context,content_version,association_hash,association_snapshot)
        VALUES(:id,:u,:p,:r,CAST(:ctx AS jsonb),:v,:h,CAST(:s AS jsonb))"""),
        {'id': aid, 'u': user, 'p': pid, 'r': rid, 'ctx': json.dumps(problem['problem_data']),
         'v': authored['_meta']['content_version'], 'h': snapshot['association_hash'], 's': json.dumps(snapshot)})
    c.execute(text("""INSERT INTO student_step_results(attempt_id,step_id,passed,submit_count,wrong_count,hint_used,last_grading_source,last_submitted_at,summary_through_sequence)
        VALUES(:a,'structure',true,1,0,false,'llm',now(),1)"""), {'a': aid})
    # A retired teacher file is absent from the next published release.
    def removed(_pid):
        raise FileNotFoundError('teacher file removed')
    monkeypatch.setattr(practice, 'load_lesson', removed)
    current = c.execute(text('SELECT * FROM student_practice_attempts WHERE id=:a'), {'a': aid}).mappings().one()
    assert practice.result(c, current)['steps'][0]['passed'] is True
    assert practice.evidence(c, user, 'amgm-formula')['evidence'][0]['attempt_id'] == aid
    assert practice.confirmed_choices(c, current) == {}


def test_rebuild_keeps_completion_arriving_between_source_and_projection_reads(publisher, authored):
    publish(publisher, authored)
    with transaction(publisher) as c:
        user = student(c)
    aid, ready, resume = uuid4(), Event(), Event()
    node = 'method-amgm-direct'
    try:
        drills.start(publisher, user, node, aid, content_version=authored['_meta']['content_version'])
        with transaction(publisher) as c:
            rows = c.execute(text('SELECT position,item_snapshot FROM knowledge_drill_answers WHERE attempt_id=:a ORDER BY position'), {'a': aid}).mappings().all()
            selected = {row['position']: [f'option-{i}' for i, o in enumerate(row['item_snapshot']['options'], 1)
                        if o['value'] in row['item_snapshot']['answer_spec']['selected']] for row in rows}
        for position in range(1, 5):
            drills.answer(publisher, user, aid, position, selected[position])

        def before_projection(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith('SELECT user_id,node_id FROM student_node_assessments') and not ready.is_set():
                ready.set()
                assert resume.wait(10), 'concurrent completion did not arrive'

        event.listen(publisher, 'before_cursor_execute', before_projection)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(assessment.rebuild, publisher, user)
                assert ready.wait(10), 'rebuild did not reach the projection read'
                try:
                    drills.answer(publisher, user, aid, 5, selected[5])
                finally:
                    resume.set()
                assert pending.result(timeout=10)['removed'] == 0
        finally:
            event.remove(publisher, 'before_cursor_execute', before_projection)
            resume.set()
        with transaction(publisher) as c:
            status = c.execute(text('SELECT status,evidence_attempt_id FROM student_node_assessments WHERE user_id=:u AND node_id=:n'), {'u': user, 'n': node}).mappings().one()
            assert status['status'] == 'mastered' and status['evidence_attempt_id'] == aid
    finally:
        with transaction(publisher) as c:
            c.execute(text('DELETE FROM student_node_assessments WHERE user_id=:u'), {'u': user})
            c.execute(text('DELETE FROM knowledge_drill_answers WHERE attempt_id=:a'), {'a': aid})
            c.execute(text('DELETE FROM knowledge_drill_attempts WHERE id=:a'), {'a': aid})
            # Product user history is deliberately immutable; this disposable
            # instance retains the isolated test identity, like auth fixtures do.
