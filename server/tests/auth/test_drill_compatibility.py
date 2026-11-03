"""A drill depends on its node's question pool, not every published article."""

from copy import deepcopy
from uuid import uuid4

import pytest
import test_practice_compatibility as practice_tests
from fastapi import HTTPException
from sqlalchemy import text
from test_auth import login
from test_learning_publish import version

from shuxueshuo_server.learning import content, drills
from shuxueshuo_server.product.db import digest

authored = practice_tests.authored
publisher = practice_tests.publisher
isolated = practice_tests.isolated
NODE = 'method-amgm-direct'


def node_state(c, user, node=NODE):
    return next(row for row in drills.statuses(c, user) if row['node_id'] == node)


def test_api_accepts_node_pool_version_without_global_release(client, auth, phone):
    login(client, auth, phone)
    states = client.get('/api/learning/nodes').json()['nodes']
    current = next(row for row in states if row['node_id'] == NODE)
    assert len(current['drill_version']) == 64
    assert all('drill_pool' not in row for row in states)
    payload = {'id': str(uuid4()), 'node_id': NODE, 'drill_version': current['drill_version']}
    response = client.post('/api/learning/drills', json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['association_hash'] == current['drill_version']
    assert client.post('/api/learning/drills', json=payload).json() == response.json()
    # The scoped version wins even when a cached caller also sends a release ID.
    resumed = client.post('/api/learning/drills', json={**payload, 'id': str(uuid4()), 'content_version': 'old-release'})
    assert resumed.status_code == 200
    assert resumed.json()['id'] == response.json()['id']


def test_unrelated_publication_preserves_drill_start_resume_and_answers(isolated, authored):
    db, c, user = isolated
    original = node_state(c, user)['drill_version']
    started = drills.start(db, user, NODE, uuid4(), drill_version=original)
    changed = deepcopy(authored)
    changed['knowledge_nodes'][0]['summary'] += ' 补充解释。'
    other = next(q for q in changed['knowledge_drill_items'] if q['node_id'] != NODE)
    other['explanation_md'] += ' 补充反馈。'
    other['content_hash'] = digest(other['explanation_md'])
    content.publish(c, version(changed))
    assert node_state(c, user)['drill_version'] == original
    resumed = drills.start(db, user, NODE, uuid4(), drill_version=original)
    assert resumed['id'] == started['id']
    saved = drills.answer(db, user, started['id'], 1, ['option-1'])
    assert saved['items'][0]['answered_at']
    assert saved['content_version'] == started['content_version']
    next_round = drills.start(db, user, NODE, uuid4(), started['id'], drill_version=original)
    assert next_round['content_version'] == changed['_meta']['content_version']
    assert next_round['association_hash'] == original


@pytest.mark.parametrize('change', ['grading', 'membership'])
def test_changed_pool_rejects_stale_new_round_but_preserves_snapshot(isolated, authored, change):
    db, c, user = isolated
    original = node_state(c, user)['drill_version']
    aid = uuid4()
    started = drills.start(db, user, NODE, aid, drill_version=original)
    changed = deepcopy(authored)
    item = next(q for q in changed['knowledge_drill_items'] if q['node_id'] == NODE)
    if change == 'grading':
        choices = [o['value'] for o in item['options']]
        item['answer_spec']['selected'] = [next(v for v in choices if v not in item['answer_spec']['selected'])]
        for option in item['options']:
            option['feedback'] = option.get('feedback') or '请检查所用条件。'
        item['content_hash'] = digest(item['answer_spec'])
    else:
        item['node_id'], item['entry_id'] = 'amgm-formula', None
    content.publish(c, version(changed))
    current = node_state(c, user)['drill_version']
    assert current != original
    requested = uuid4()
    with pytest.raises(HTTPException) as error:
        drills.start(db, user, NODE, requested, drill_version=original)
    assert error.value.detail['code'] == 'learning_drill_changed'
    assert not c.scalar(text('SELECT count(*) FROM knowledge_drill_attempts WHERE id=:id'), {'id': requested})
    # Retrying an acknowledged ID reads its immutable round; it cannot regrade it.
    old = drills.start(db, user, NODE, aid, drill_version=original)
    assert old['items'] == started['items']
    assert old['status'] == 'closed'
    assert drills.start(db, user, NODE, requested, drill_version=current)['association_hash'] == current
