"""The published parity pages must save and restore with the real learning contract."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import test_learning_publish as publishing
from sqlalchemy import ForeignKeyConstraint, create_engine, text
from sqlalchemy.schema import AddConstraint

from shuxueshuo_server.learning import compatibility, content, practice
from shuxueshuo_server.product.db import digest, transaction
from shuxueshuo_server.product.models import metadata

ROOT = Path(__file__).resolve().parents[3]
authored = publishing.authored
database_instance = publishing.publisher


@pytest.fixture
def publisher(database_instance):
    # Old exercises may already exist in the shared test instance under earlier
    # contracts. Test this publication in its own schema, without replacing them.
    schema = 'test_parity_publication_' + uuid4().hex
    with database_instance.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA {schema}')
        connection.exec_driver_sql(f'SET LOCAL search_path TO {schema}, public')
        # Clone the migrated DDL, including database defaults used by raw SQL.
        # Metadata's Python-side defaults are insufficient for publication.
        for name in metadata.tables:
            connection.exec_driver_sql(f'CREATE TABLE "{name}" (LIKE public."{name}" INCLUDING ALL)')
        for table in metadata.tables.values():
            for constraint in table.constraints:
                if isinstance(constraint, ForeignKeyConstraint):
                    connection.execute(AddConstraint(constraint))
    scoped = create_engine(database_instance.url, isolation_level='READ COMMITTED',
                           hide_parameters=True,
                           connect_args={'options': f'-c timezone=UTC -c search_path={schema},public'})
    try:
        yield scoped
    finally:
        scoped.dispose()
        with database_instance.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')


def test_all_published_parity_pages_save_and_resume(publisher, authored):
    topic = json.loads((ROOT / 'site/data/knowledge-next/topics/function-parity.json').read_text())
    assert len(topic['problems']) == 31

    class Rollback(Exception):
        pass

    try:
        # This is an independent database, and all test progress and catalog writes roll back.
        with transaction(publisher) as connection:
            content.publish(connection, authored)
            user = publishing.student(connection)
            for pid, entry in topic['problems'].items():
                bundle = json.loads((ROOT / ('site' + entry['bundle'])).read_text())
                replay = json.loads((ROOT / f'site/data/graph-walk/{pid}.replay.json').read_text())
                meta = compatibility.metadata(compatibility.published(connection, pid))
                assert meta['page_contract_hash'] == digest(compatibility.page_contract(bundle)), pid
                route, = replay['routes']
                started = practice.start(publisher, user, pid, route, uuid4(), practice_version=meta['practice_version'])
                for index, action in enumerate(replay['actions']):
                    saved = practice.submit(publisher, user, started['id'], uuid4(), action['decision'],
                                            {'value': action['answer']})
                    assert saved['steps'][index]['passed'], (pid, action['decision'])
                    if index == len(replay['actions']) // 2:
                        resumed = practice.start(publisher, user, pid, route, uuid4(),
                                                 practice_version=meta['practice_version'])
                        assert resumed['id'] == started['id']
                        assert resumed['steps'] == saved['steps']
                assert saved['status'] == 'completed', pid
                assert all(step['passed'] for step in saved['steps']), pid
                attempt = practice.owned(connection, started['id'], user)
                compatibility.require_attempt(connection, attempt, meta['practice_version'])
                assert practice.result(connection, attempt)['status'] == 'completed'
            raise Rollback
    except Rollback:
        pass


@pytest.mark.parametrize('change', ['reorder', 'insert', 'remove'])
def test_same_course_can_change_step_order_and_count(publisher, authored, change):
    pid, route_id = 'basic-inequality-q01', 'direct'
    changed = deepcopy(authored)
    problem = next(row for row in changed['practice_problems'] if row['id'] == pid)
    nodes = problem['problem_data']['_lesson']['routes'][route_id]['nodes']
    def matches(row):
        return (row['problem_id'], row['route_id']) == (pid, route_id)
    original = sorted((row for row in authored['practice_steps'] if matches(row)), key=lambda row: row['position'])
    if change == 'reorder':
        nodes[0], nodes[1] = nodes[1], nodes[0]
    elif change == 'insert':
        nodes.insert(0, {**deepcopy(nodes[0]), 'id': 'new-introduction'})
        changed['practice_steps'].append({**deepcopy(original[0]), 'step_id': 'new-introduction'})
        changed['practice_step_nodes'].extend([
            {**row, 'step_id': 'new-introduction'} for row in authored['practice_step_nodes']
            if matches(row) and row['step_id'] == original[0]['step_id']
        ])
    else:
        removed = nodes.pop(0)['id']
        for table in ('practice_steps', 'practice_step_nodes'):
            changed[table] = [row for row in changed[table] if not (matches(row) and row['step_id'] == removed)]
    positions = {node['id']: index for index, node in enumerate(nodes)}
    for step in changed['practice_steps']:
        if matches(step):
            step['position'] = positions[step['step_id']]
    problem['contract_hash'] = digest(problem['problem_data']['_lesson'])
    problem['problem_data']['contract_hash'] = problem['contract_hash']
    problem['association_hash'] = digest(positions)
    next(row for row in changed['practice_routes'] if matches(row))['association_hash'] = digest(positions)
    publishing.version(changed)

    with transaction(publisher) as connection:
        content.publish(connection, authored)
        user = publishing.student(connection)
        before = compatibility.metadata(compatibility.published(connection, pid))
        attempt = practice.start(publisher, user, pid, route_id, uuid4(), practice_version=before['practice_version'])
        content.publish(connection, changed)
        content.publish(connection, changed)  # Repeating the publication is safe.
        actual = connection.execute(text('SELECT step_id,position FROM practice_steps WHERE problem_id=:pid AND route_id=:route'),
                                    {'pid': pid, 'route': route_id})
        assert dict(actual.all()) == positions
        assert practice.owned(connection, attempt['id'], user)['status'] == 'closed'
        current = compatibility.metadata(compatibility.published(connection, pid))
        assert current['practice_version'] != before['practice_version']
        assert practice.start(publisher, user, pid, route_id, uuid4(), practice_version=current['practice_version'])['id'] != attempt['id']
        content.publish(connection, authored)  # Restoring the previous release also reuses positions.
        actual = connection.execute(text('SELECT step_id,position FROM practice_steps WHERE problem_id=:pid AND route_id=:route'),
                                    {'pid': pid, 'route': route_id})
        assert dict(actual.all()) == {row['step_id']: row['position'] for row in original}
