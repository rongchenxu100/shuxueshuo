import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from shuxueshuo_server.learning import api, graph_walk, practice


def test_native_contract_accepts_verified_equivalent_options_without_client_pass_flag():
    decision = {'id': 'intersection', 'interaction': {'type': 'choice', 'field': 'domain', 'options': [
        {'value': 'interval'}, {'value': 'set-builder'}, {'value': 'wrong-endpoint'}]},
        'expected_answer': {'one_of': ['interval', 'set-builder']}}
    assert graph_walk.grade(decision, {'value': 'interval'}, 'direct') == 'passed'
    assert graph_walk.grade(decision, {'value': 'set-builder'}, 'direct') == 'passed'
    assert graph_walk.grade(decision, {'value': 'wrong-endpoint'}, 'direct') == 'wrong'
    with pytest.raises(HTTPException):
        graph_walk.grade(decision, {'value': 'wrong-endpoint', 'passed': True}, 'direct')


def test_native_position_selection_requires_both_sources_and_rejects_duplicates():
    decision = {'interaction': {'type': 'multi'}, 'expected_answer': {'required': ['root', 'denominator'],
        'allowed': ['root', 'denominator']}}
    assert graph_walk.grade(decision, {'value': ['root']}, 'direct') == 'wrong'
    assert graph_walk.grade(decision, {'value': ['root', 'denominator']}, 'direct') == 'passed'
    assert graph_walk.grade(decision, {'value': ['root', 'root', 'denominator']}, 'direct') == 'wrong'


@pytest.mark.parametrize('kind', ['plane', 'grid'])
@pytest.mark.parametrize('bad', [{}, []])
def test_native_position_payload_rejects_nested_objects(kind, bad):
    decision = {'interaction': {'type': kind}, 'expected_answer': {}}
    value = [bad, 'free'] + (['direct'] if kind == 'plane' else [])
    with pytest.raises(HTTPException) as error:
        graph_walk.grade(decision, {'value': value}, 'direct')
    assert error.value.status_code == 422


def test_real_static_course_replay_values_grade_with_the_server_contract():
    root = Path(__file__).resolve().parents[3]
    bundle = json.loads((root / 'site/data/graph-walk/function-concepts-q15.json').read_text())
    replay = json.loads((root / 'site/data/graph-walk/function-concepts-q15.replay.json').read_text())
    route = replay['routes'][0]
    decisions = {step['id']: step for step in bundle['intro'] + bundle['routes'][route]['steps']}
    for action in replay['actions']:
        assert graph_walk.grade(decisions[action['decision']], {'value': action['answer']}, route) == 'passed'


def test_native_attempt_reads_its_frozen_version_without_loading_legacy_teacher(monkeypatch):
    contract = {'schema': graph_walk.SCHEMA, 'problemId': 'function-concepts-q15', 'bundleVersion': 'v1',
        'intro': [{'id': 'D3', 'interaction': {'type': 'read'}, 'expected_answer': {}}],
        'routes': {'direct': {'steps': [{'id': 'solve', 'interaction': {'type': 'choice'}, 'expected_answer': {'one_of': ['yes']}}]}}}
    graph_walk.validate_contract(contract, 'function-concepts-q15')
    attempt = {'route_id': 'direct', 'problem_context': {'_graph_walk': deepcopy(contract)}}
    monkeypatch.setattr(practice, 'load_lesson', lambda *_: pytest.fail('native attempts must not load a tutor fixture'))
    contract['routes']['direct']['steps'][0]['expected_answer'] = {'one_of': ['new']}
    assert [step['id'] for step in practice.nodes(attempt)] == ['D3', 'solve']
    assert practice.nodes(attempt)[1]['expected_answer'] == {'one_of': ['yes']}
    with pytest.raises(ValueError, match='identity'):
        graph_walk.validate_contract(contract, 'different-problem')


def test_native_recording_grades_retries_and_restores_without_a_teacher_file():
    from sqlalchemy import text

    from shuxueshuo_server.learning.content import load_content, publish
    from shuxueshuo_server.product.config import Settings
    from shuxueshuo_server.product.db import engine, transaction

    root = os.getenv('PRODUCT_TEST_DATA_DIR')
    if not root:
        pytest.skip('Requires independent PostgreSQL')
    db = engine(Settings.load('local', root, os.environ['PRODUCT_TEST_INSTANCE']).url('migration'))
    pid, uid, aid = 'native-contract-probe', uuid4(), uuid4()
    intro = {'id': 'D3', 'title': '确认方法', 'question': '进入已验证路线', 'interaction': {'type': 'read'}, 'expected_answer': {}}
    final = {'id': 'intersection', 'title': '求交集', 'question': '选择等价结果',
        'interaction': {'type': 'choice', 'options': [
            {'value': 'interval'}, {'value': 'set-builder'}, {'value': 'wrong'}]},
        'expected_answer': {'one_of': ['interval', 'set-builder']}}
    contract = {'schema': graph_walk.SCHEMA, 'problemId': pid, 'bundleVersion': 'verified-v1',
        'intro': [intro], 'routes': {'direct': {'steps': [final]}}}
    class RollbackProbe(Exception):
        pass
    try:
        with pytest.raises(RollbackProbe), transaction(db) as c:
            publish(c, load_content())
            c.execute(text('INSERT INTO users(id,key,display_name) VALUES(:id,:key,:name)'),
                {'id': uid, 'key': str(uid), 'name': 'Native contract test'})
            c.execute(text('''INSERT INTO practice_problems(id,label,path,lesson_file,statement_md,problem_data,contract_hash,association_hash)
                VALUES(:id,'test','/test/','native','test',CAST(:body AS jsonb),'test','test')'''),
                {'id': pid, 'body': json.dumps({'_graph_walk': contract})})
            c.execute(text('''INSERT INTO practice_routes(problem_id,route_id,label,methods,association_hash)
                VALUES(:id,'direct','test','["method-amgm-direct"]','test')'''), {'id': pid})
            for index, step in enumerate([intro, final]):
                c.execute(text('''INSERT INTO practice_steps(problem_id,route_id,step_id,title,position,refs,reason)
                    VALUES(:id,'direct',:step,:title,:position,'[]','native test')'''),
                    {'id': pid, 'step': step['id'], 'title': step['title'], 'position': index + 1})
            started = practice.start(db, uid, pid, 'direct', aid)
            assert started['active_step'] == 'D3'
            auth = SimpleNamespace(db=db)
            with pytest.raises(HTTPException) as unearned:
                api.complete(pid, api.CompleteBody(), {'id': str(uid)}, auth)
            assert unearned.value.status_code == 409
            with pytest.raises(HTTPException):
                practice.submit(db, uid, aid, uuid4(), 'intersection', {'value': 'interval'})
            practice.submit(db, uid, aid, uuid4(), 'D3', {'value': 'read'})
            wrong = uuid4()
            for _ in range(2):
                result = practice.submit(db, uid, aid, wrong, 'intersection', {'value': 'wrong'})
            assert result['steps'][-1]['wrong_count'] == 1
            finished = practice.submit(db, uid, aid, uuid4(), 'intersection', {'value': 'set-builder'})
            assert finished['status'] == 'completed'
            assert finished['steps'][-1]['answer'] == {'value': 'set-builder'}
            assert api.complete(pid, api.CompleteBody(), {'id': str(uid)}, auth)['practiced']
            assert c.scalar(text('SELECT practiced FROM student_learning_marks WHERE user_id=:u AND problem_id=:p'), {'u': uid, 'p': pid})
            # Rewinding the view never replaces the first established result.
            reread = practice.submit(db, uid, aid, uuid4(), 'intersection', {'value': 'wrong'})
            assert reread['steps'][-1]['answer'] == {'value': 'set-builder'}
            assert reread['steps'][-1]['wrong_count'] == 1
            raise RollbackProbe()
    finally:
        db.dispose()
