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


def equality_contract(relation='equal', truths=('different', 'different', 'equal', 'equal')):
    steps = []
    for index, verdict in enumerate(truths):
        label = 'ABCD'[index]
        scope = {'option_id': label, 'label': label, 'target_ref': '/root/goals/0',
                 'left_ref': f'{label}/f', 'right_ref': f'{label}/g'}
        steps.extend([
            {'id': f'{label}-evidence', 'option_context': scope | {'phase': 'evidence'},
             'interaction': {'type': 'read'}, 'expected_answer': {}},
            {'id': f'{label}-verdict', 'option_context': scope | {'phase': 'verdict'},
             'interaction': {'type': 'choice', 'options': [{'value': 'equal'}, {'value': 'different'}]},
             'expected_answer': {'one_of': [verdict]}},
        ])
    labels = list('ABCD'[:len(truths)])
    steps.append({'id': 'final', 'source': 'original_choice', 'select_relation': relation, 'target_ref': '/root/goals/0',
                  'require_complete_options': labels,
                  'interaction': {'type': graph_walk.EXACT_CHOICE, 'options': [{'value': label} for label in labels]},
                  'expected_answer': {'option_labels': labels,
                                      'correct_labels': [label for label, verdict in zip(labels, truths) if verdict == relation]}})
    return {'schema': graph_walk.SCHEMA, 'problemId': 'q20', 'bundleVersion': 'v1',
            'intro': [], 'routes': {'equality': {'steps': steps}}}


def test_original_multiple_is_exact_and_does_not_inherit_step_multi_semantics():
    contract = equality_contract()
    graph_walk.validate_contract(contract, 'q20')
    decision = contract['routes']['equality']['steps'][-1]
    for answer in [['C', 'D'], ['D', 'C']]:
        assert graph_walk.grade(decision, {'value': answer}, 'equality') == 'passed'
    for answer in [[], ['C'], ['A', 'C', 'D'], ['C', 'C', 'D'], ['C', 'D', 'Z']]:
        assert graph_walk.grade(decision, {'value': answer}, 'equality') == 'wrong'
    for answer in ['CD', None, [1]]:
        with pytest.raises(HTTPException) as error:
            graph_walk.grade(decision, {'value': answer}, 'equality')
        assert error.value.status_code == 422
    mixed = deepcopy(decision)
    mixed['expected_answer']['allowed'] = ['A', 'C', 'D']
    with pytest.raises(HTTPException):
        graph_walk.grade(mixed, {'value': ['C', 'D']}, 'equality')
    step = {'interaction': {'type': 'multi'}, 'expected_answer': {'required': ['A'], 'allowed': ['A', 'B']}}
    assert graph_walk.grade(step, {'value': ['A', 'B']}, 'equality') == 'passed'


def test_original_multiple_polarity_empty_set_and_all_prerequisite_evidence():
    for relation, truths, answer in [('different', ('different', 'different', 'equal', 'equal'), ['A', 'B']),
                                     ('equal', ('different', 'different'), [])]:
        contract = equality_contract(relation, truths)
        graph_walk.validate_contract(contract, 'q20')
        steps = contract['routes']['equality']['steps']
        assert graph_walk.grade(steps[-1], {'value': answer}, 'equality') == 'passed'
        for passed in ([], [row['id'] for row in steps if row['id'].endswith('verdict')],
                       [row['id'] for row in steps[1:-1]]):
            with pytest.raises(HTTPException) as error:
                graph_walk.ensure_option_prerequisites(contract, 'equality', steps[-1], passed)
            assert error.value.status_code == 409
        graph_walk.ensure_option_prerequisites(contract, 'equality', steps[-1], [row['id'] for row in steps[:-1]])


@pytest.mark.parametrize('mutation', ['missing-evidence', 'wrong-scope', 'duplicate-option', 'wrong-polarity'])
def test_original_multiple_contract_rejects_incomplete_or_mixed_option_evidence(mutation):
    contract = equality_contract()
    steps = contract['routes']['equality']['steps']
    if mutation == 'missing-evidence':
        steps.pop(0)
    elif mutation == 'wrong-scope':
        steps[1]['option_context']['right_ref'] = 'B/g'
    elif mutation == 'duplicate-option':
        steps[-1]['require_complete_options'][1] = 'A'
    else:
        steps[-1]['select_relation'] = 'different'
    with pytest.raises(ValueError):
        graph_walk.validate_contract(contract, 'q20')


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
    borrowed = {'id': 'borrow', 'title': '选择子方法', 'question': '选择适用的方法',
        'interaction': {'type': 'plane', 'x': {'options': [{'value': 'real'}]},
            'y': {'options': [{'value': 'free'}]}, 'methods': [
                {'value': 'discriminant', 'cells': [['real', 'free']], 'route': 'direct'},
                {'value': 'separation', 'cells': [['real', 'free']]}]},
        'expected_answer': {'cell': ['real', 'free'], 'method': 'discriminant'},
        'alternatives': {'separation': {'message': '适用，但尚未展开。'}}}
    contract = {'schema': graph_walk.SCHEMA, 'problemId': pid, 'bundleVersion': 'verified-v1',
        'intro': [intro], 'routes': {'direct': {'steps': [borrowed, final]}}}
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
            for index, step in enumerate([intro, borrowed, final]):
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
            uncovered_id = uuid4()
            for _ in range(2):
                uncovered = practice.submit(db, uid, aid, uncovered_id, 'borrow',
                                            {'value': ['real', 'free', 'separation']})
            step = next(row for row in uncovered['steps'] if row['step_id'] == 'borrow')
            assert step['wrong_count'] == 0 and step['submit_count'] == 1
            assert step['passed'] is False and 'answer' not in step
            assert uncovered['active_step'] == 'borrow' and uncovered['status'] == 'in_progress'
            assert not c.scalar(text('SELECT practiced FROM student_learning_marks WHERE user_id=:u AND problem_id=:p'),
                                {'u': uid, 'p': pid})
            assert c.scalar(text("SELECT payload->>'result' FROM student_practice_events WHERE related_event_id=:id AND event_type='grade'"),
                            {'id': uncovered_id}) == 'uncovered'
            practice.submit(db, uid, aid, uuid4(), 'borrow', {'value': ['real', 'free', 'discriminant']})
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


def test_equality_recording_enforces_evidence_locked_verdicts_and_exact_final():
    from sqlalchemy import text

    from shuxueshuo_server.learning.content import load_content, publish
    from shuxueshuo_server.product.config import Settings
    from shuxueshuo_server.product.db import engine, transaction

    root = os.getenv('PRODUCT_TEST_DATA_DIR')
    if not root:
        pytest.skip('Requires independent PostgreSQL')
    db = engine(Settings.load('local', root, os.environ['PRODUCT_TEST_INSTANCE']).url('migration'))
    pid, uid, aid = f'equality-contract-probe-{uuid4()}', uuid4(), uuid4()
    contract = equality_contract()
    contract['problemId'] = pid
    steps = contract['routes']['equality']['steps']
    graph_walk.validate_contract(contract, pid)

    class RollbackProbe(Exception):
        pass

    try:
        with pytest.raises(RollbackProbe), transaction(db) as c:
            publish(c, load_content())
            c.execute(text('INSERT INTO users(id,key,display_name) VALUES(:id,:key,:name)'),
                      {'id': uid, 'key': str(uid), 'name': 'Equality contract test'})
            c.execute(text('''INSERT INTO practice_problems(id,label,path,lesson_file,statement_md,problem_data,contract_hash,association_hash)
                VALUES(:id,'test','/test/','native','test',CAST(:body AS jsonb),'test','test')'''),
                      {'id': pid, 'body': json.dumps({'_graph_walk': contract})})
            c.execute(text('''INSERT INTO practice_routes(problem_id,route_id,label,methods,association_hash)
                VALUES(:id,'equality','test','["method-function-equality"]','test')'''), {'id': pid})
            for index, step in enumerate(steps):
                c.execute(text('''INSERT INTO practice_steps(problem_id,route_id,step_id,title,position,refs,reason)
                    VALUES(:id,'equality',:step,:title,:position,'[]','native test')'''),
                          {'id': pid, 'step': step['id'], 'title': step['id'], 'position': index + 1})
            started = practice.start(db, uid, pid, 'equality', aid)
            assert started['active_step'] == 'A-evidence'
            with pytest.raises(HTTPException) as premature:
                practice.submit(db, uid, aid, uuid4(), 'final', {'value': ['C', 'D']})
            assert premature.value.status_code == 409
            for step in steps[:-1]:
                answer = 'read' if step['interaction']['type'] == 'read' else step['expected_answer']['one_of'][0]
                identity = uuid4()
                if step['interaction']['type'] == 'choice':
                    wrong = practice.submit(db, uid, aid, uuid4(), step['id'],
                                            {'value': 'different' if answer == 'equal' else 'equal'})
                    assert wrong['active_step'] == step['id'] and wrong['status'] == 'in_progress'
                practice.submit(db, uid, aid, identity, step['id'], {'value': answer})
                # Repeated delivery is idempotent, but a new attempt cannot edit locked work.
                practice.submit(db, uid, aid, identity, step['id'], {'value': answer})
                with pytest.raises(HTTPException) as locked:
                    practice.submit(db, uid, aid, uuid4(), step['id'], {'value': answer})
                assert locked.value.status_code == 409
            for answer in [[], ['C'], ['A', 'C', 'D'], ['C', 'C', 'D'], ['C', 'D', 'Z']]:
                wrong = practice.submit(db, uid, aid, uuid4(), 'final', {'value': answer})
                assert wrong['active_step'] == 'final' and wrong['status'] == 'in_progress'
            identity = uuid4()
            completed = practice.submit(db, uid, aid, identity, 'final', {'value': ['D', 'C']})
            assert completed['status'] == 'completed'
            assert completed['steps'][-1]['answer'] == {'value': ['D', 'C']}
            assert practice.submit(db, uid, aid, identity, 'final', {'value': ['D', 'C']})['status'] == 'completed'
            raise RollbackProbe()
    finally:
        db.dispose()
