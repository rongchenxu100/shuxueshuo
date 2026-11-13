"""A release can change without invalidating unrelated exercises or their evidence."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
import test_learning_publish as publishing
from fastapi import HTTPException
from sqlalchemy import text
from test_auth import login
from test_learning_publish import student, version

from shuxueshuo_server.learning import compatibility, content, practice
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.tutor_demo.api import create_router
from shuxueshuo_server.tutor_demo.session import Session, load_lesson

PID = 'basic-inequality-q01'
authored = publishing.authored
publisher = publishing.publisher


@pytest.fixture
def isolated(publisher, authored):
    class Rollback(Exception):
        pass
    try:
        with transaction(publisher) as c:
            content.publish(c, authored)
            yield publisher, c, student(c)
            raise Rollback
    except Rollback:
        pass


@pytest.mark.parametrize('pid', [PID, 'function-concepts-q23b-v2'])
def test_unrelated_publication_preserves_start_submit_retry_restore(isolated, authored, pid):
    db, c, user = isolated
    p = compatibility.published(c, pid)
    original = compatibility.metadata(p)
    course = p['problem_data'].get('_graph_walk') or p['problem_data']['_lesson']
    route = next(iter(course['routes']))
    first = practice.start(db, user, pid, route, uuid4(), practice_version=original['practice_version'])
    changed = deepcopy(authored)
    changed['knowledge_nodes'][0]['summary'] += ' 与本题无关的说明修改。'
    content.publish(c, version(changed))
    assert compatibility.metadata(compatibility.published(c, pid)) == original
    resumed = practice.start(db, user, pid, route, uuid4(), content_version='old-release', practice_version=original['practice_version'])
    assert resumed['id'] == first['id']
    a = practice.owned(c, first['id'], user)
    compatibility.require_attempt(c, a, original['practice_version'])
    step = practice.nodes(a)[0]
    if p['problem_data'].get('_graph_walk'):
        answer = {'value': step['expected_answer']['one_of'][0]}
    else:
        answer = {'terms': step['expected_answer']['terms'], 'fixed': step['expected_answer']['fixed']}
    event = uuid4()
    saved = practice.submit(db, user, first['id'], event, step['id'], answer)
    repeated = practice.submit(db, user, first['id'], event, step['id'], answer)
    assert saved == repeated
    assert saved['steps'][0]['passed']
    assert saved['content_version'] == first['content_version']
    if pid == PID:
        session = Session(load_lesson(PID))
        practice.restore_session(db, user, first['id'], session, 'old-release', original['practice_version'])
        assert session.state['active'] == 1
        assert session.lesson == a['problem_context']['_lesson']


def test_cosmetic_publish_preserves_snapshot_and_grading_change_replaces_in_place(isolated, authored):
    db, c, user = isolated
    original = compatibility.metadata(compatibility.published(c, PID))
    first = practice.start(db, user, PID, 'direct', uuid4(), practice_version=original['practice_version'])
    frozen = practice.owned(c, first['id'], user)['problem_context']
    changed = deepcopy(authored)
    p = next(row for row in changed['practice_problems'] if row['id'] == PID)
    step = p['problem_data']['_lesson']['routes']['direct']['nodes'][0]
    step['feedback']['answer'] = '改进说明，不改变判定。'
    p['contract_hash'] = 'changed-source'
    content.publish(c, version(changed))
    assert compatibility.metadata(compatibility.published(c, PID)) == original
    assert practice.owned(c, first['id'], user)['problem_context'] == frozen
    session = Session(load_lesson(PID))
    practice.restore_session(db, user, first['id'], session, practice_version=original['practice_version'])
    assert session.lesson == frozen['_lesson']
    step['expected_answer']['fixed'] = 'product'
    p['contract_hash'] = 'changed-grading'
    content.publish(c, version(changed))
    updated = compatibility.metadata(compatibility.published(c, PID))
    assert updated['practice_version'] != original['practice_version']
    old = practice.owned(c, first['id'], user)
    assert old['problem_context'] == frozen
    assert practice.result(c, old)['status'] == 'closed'
    with pytest.raises(HTTPException) as error:
        practice.restore_session(db, user, first['id'], Session(load_lesson(PID)), practice_version=updated['practice_version'])
    assert error.value.status_code == 409


def test_only_the_changed_question_is_rejected_and_history_remains_readable(isolated):
    db, c, user = isolated
    p = compatibility.published(c, PID)
    original = compatibility.metadata(p)
    first = practice.start(db, user, PID, 'direct', uuid4(), practice_version=original['practice_version'])
    frozen = practice.owned(c, first['id'], user)['problem_context']
    # Simulate a mismatched installation independently of the publisher guard.
    data = deepcopy(p['problem_data'])
    data['_lesson']['routes']['direct']['nodes'][0]['expected_answer']['fixed'] = 'product'
    c.execute(text('UPDATE practice_problems SET problem_data=CAST(:data AS jsonb) WHERE id=:id'), {'id': PID, 'data': json.dumps(data)})
    with pytest.raises(HTTPException) as error:
        practice.start(db, user, PID, 'direct', uuid4(), practice_version=original['practice_version'])
    assert error.value.detail['code'] == 'practice_content_changed'
    other = compatibility.metadata(compatibility.published(c, 'quadratic-always-q01'))
    practice.start(db, user, 'quadratic-always-q01', 'discriminant', uuid4(), practice_version=other['practice_version'])
    old = practice.owned(c, first['id'], user)
    assert old['problem_context'] == frozen
    assert practice.result(c, old)['status'] == 'in_progress'


def test_public_metadata_and_api_validate_only_requested_problem(client, auth, phone):
    meta = client.get(f'/api/learning/content/problems/{PID}')
    assert meta.status_code == 200
    data = meta.json()
    assert set(data) == {'id', 'page_contract_hash', 'practice_version', 'content_version'}
    login(client, auth, phone)
    body = {'id': str(uuid4()), 'problem_id': PID, 'route_id': 'direct', 'content_version': 'old-release',
            'practice_version': data['practice_version']}
    response = client.post('/api/learning/practice', json=body)
    assert response.status_code == 200, response.text
    assert client.get(f"/api/learning/practice/{body['id']}", params={'practice_version': data['practice_version']}).status_code == 200
    for action in ('start', 'restore'):
        bad = 'f' * 64
        rejected = (client.post('/api/learning/practice', json={**body, 'practice_version': bad}) if action == 'start'
                    else client.get(f"/api/learning/practice/{body['id']}", params={'practice_version': bad}))
        assert rejected.status_code == 409
    assert client.get(f"/api/learning/practice/{body['id']}").status_code == 200


def test_bound_tutor_accepts_problem_version_without_global_release(client, app, auth, phone):
    app.include_router(create_router(tutor=object()))
    login(client, auth, phone)
    token = client.get(f'/api/learning/content/problems/{PID}').json()['practice_version']
    body = {'id': str(uuid4()), 'problem_id': PID, 'route_id': 'direct', 'practice_version': token}
    started = client.post('/api/learning/practice', json=body)
    assert started.status_code == 200, started.text
    session_body = {'lesson_id': PID, 'practice_attempt_id': started.json()['id'], 'practice_version': token}
    response = client.post('/api/tutor-demo/sessions', json=session_body)
    assert response.status_code == 201, response.text
    assert response.json()['state']['method'] == 'direct'
    rejected = client.post('/api/tutor-demo/sessions', json={**session_body, 'practice_version': 'f' * 64})
    assert rejected.status_code == 409
