"""Real PostgreSQL + OTP cookies for minimal learning marks."""
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from test_auth import login

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.db import transaction


def complete(client, problem='q01'):
    return client.post(f'/api/learning/marks/{problem}/complete', json={})


def status(client, value, problem='q01'):
    return client.put(f'/api/learning/marks/{problem}/status', json={'learning_status': value})


def test_learning_defaults_completion_status_and_chapter_isolation(client, auth, phone):
    login(client, auth, phone)
    assert client.get('/api/learning/marks').json() == {'marks': []}
    default = client.get('/api/learning/marks/q01').json()
    assert default == {'problem_id': 'q01', 'practiced': False, 'learning_status': 'unmarked'}
    assert status(client, 'mastered').status_code == 409
    first = complete(client)
    assert first.status_code == 200
    assert first.json()['practiced'] is True
    assert complete(client).json() == first.json()
    for value in ['mastered', 'needs_review', 'unmarked']:
        assert status(client, value).json()['learning_status'] == value
        assert complete(client).json()['learning_status'] == value
    assert client.get('/api/learning/marks/quadratic-always-q01').json()['practiced'] is False
    assert complete(client, 'quadratic-always-q01').status_code == 200
    assert len(client.get('/api/learning/marks').json()['marks']) == 2
    assert first.headers['cache-control'] == 'no-store'


def test_learning_auth_origin_validation_and_owner_guard(client, auth, phone):
    assert client.get('/api/learning/marks').status_code == 401
    assert complete(client).status_code == 401
    assert status(client, 'mastered').status_code == 401
    user = login(client, auth, phone).json()['user']
    for method, path, body in [('post','complete', {}), ('put','status', {'learning_status': 'mastered'})]:
        assert getattr(client, method)(f'/api/learning/marks/q01/{path}', json=body, headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/learning/marks/q01/complete', json={}, headers={'X-Learning-User': 'other-account'}).status_code == 409
    assert client.get('/api/learning/marks/q01', headers={'X-Learning-User': 'other-account'}).status_code == 409
    for body in [{'user_id': user['id']}, {'practiced': False}, {'answers': ['m']}]:
        assert client.post('/api/learning/marks/q01/complete', json=body).status_code == 422
    assert status(client, 'unknown').status_code == 422
    assert complete(client, 'missing-question').status_code == 404
    assert client.get('/api/learning/marks/missing-question').status_code == 404
    assert client.post('/api/learning/marks/q01/complete', content='x'*4097).status_code == 413
    complete(client)
    status(client, 'mastered')
    login(client, auth, '138' + phone[3:])
    assert client.get('/api/learning/marks').json() == {'marks': []}
    assert status(client, 'needs_review').status_code == 409


def test_concurrent_completion_preserves_evaluation_and_database_constraints(client, auth, phone):
    user = login(client, auth, phone).json()['user']
    complete(client)
    def call(i):
        return complete(client) if i % 2 else status(client, 'mastered')
    with ThreadPoolExecutor(6) as pool:
        assert all(response.status_code == 200 for response in pool.map(call, range(12)))
    assert client.get('/api/learning/marks/q01').json()['learning_status'] == 'mastered'
    auth.db.dispose()  # A fresh connection sees the saved record.
    assert client.get('/api/learning/marks/q01').json()['practiced'] is True
    with transaction(auth.db) as c:
        rows = c.execute(select(m.student_learning_marks).where(m.student_learning_marks.c.user_id == UUID(user['id']))).all()
        assert len(rows) == 1
    with pytest.raises(DBAPIError), transaction(auth.db) as c:
        c.execute(update(m.student_learning_marks).where(m.student_learning_marks.c.user_id == UUID(user['id'])).values(practiced=False))
    assert client.post('/api/auth/logout').status_code == 204
    assert client.get('/api/learning/marks').status_code == 401
