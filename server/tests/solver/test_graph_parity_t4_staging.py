"""Staged FP-T4 questions compile, grade and replay in isolation without publishing links."""
import json
import subprocess

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.runner import resume_sample
from tools.import_authored_graph_course import import_course

STAGING = ROOT/'internal/senior-high/authored-courses/function-parity-t4-staged-20261111/pending-topic.json'
MANIFEST = json.loads(STAGING.read_text())


def test_staged_questions_are_not_public_yet():
    topic = json.loads((ROOT/'site/data/knowledge-next/topics/function-parity.json').read_text())
    ids = {entry['id'] for entry in MANIFEST['pending']}
    assert not ids & set(topic['problems'])
    assert not any(ids & set(group['problems']) for group in topic['groups'])
    assert not any((ROOT/'site/data/graph-walk'/f'{i}.source.json').exists() for i in ids)
    for entry in MANIFEST['pending']:
        record = json.loads((ROOT/entry['authored_source']).read_text())
        source = entry['course_source']
        expected = record['expected'].get('goals') or [record['expected']]
        assert (source.get('targetRefs') or [source['targetRef']]) == [
            f'/root/goals/{i}' for i in range(len(expected))]


@pytest.mark.parametrize('entry', MANIFEST['pending'], ids=lambda v: v['id'])
@pytest.mark.stage_three_db
def test_pending_question_answers_replays_and_grades(entry, tmp_path):
    source_path = ROOT/entry['authored_source']
    record = json.loads(source_path.read_text())
    assert record['problem_id'] == entry['id'] == entry['course_source']['problemId']
    isolated = tmp_path/'authored.json'
    isolated.write_bytes(source_path.read_bytes())
    evidence, recording = tmp_path/'evidence.json', tmp_path/'recording'
    import_course(isolated, recording, evidence)
    goals = resume_sample(recording/'execution')['goals']
    expected = record['expected'].get('goals') or [record['expected']]
    assert len(goals) == len(expected) and all(goal['status'] == 'solved' for goal in goals)
    x = sp.Symbol('x', real=True)
    for goal, gold in zip(goals, expected):
        if gold['type'] == 'type-parity-inequality':
            assert goal['answer']['set']['expression'] == gold['set_expression']
        else:
            got = sp.sympify(goal['answer']['expression']['expression'], locals={'x': x})
            assert sp.expand(got - sp.sympify(gold['expression'], locals={'x': x})) == 0
    text = json.dumps(json.loads(evidence.read_text())['stream'], ensure_ascii=False)
    assert '左' not in text and '右' not in text
    course = tmp_path/'source.json'
    assert (entry['course_source'].get('targetRefs') or [entry['course_source']['targetRef']]) == [
        goal['target_ref'] for goal in goals]
    course.write_text(json.dumps(entry['course_source'], ensure_ascii=False))
    route = 'parity-extension' if expected[0]['type'] == 'type-parity-formula' else 'parity-inequality'
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                           str(evidence), str(course), route], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout+check.stderr
    assert json.loads(check.stdout)['targets'] == [goal['target_ref'] for goal in goals]
