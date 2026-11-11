"""Staged FP-T3 questions compile and grade in isolation without publishing links."""
import json
import subprocess

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.runner import resume_sample
from tools.import_authored_graph_course import import_course

STAGING = ROOT/'internal/senior-high/authored-courses/function-parity-t3-staged-20261111/pending-topic.json'
MANIFEST = json.loads(STAGING.read_text())


def test_staged_questions_are_not_public_yet():
    topic = json.loads((ROOT/'site/data/knowledge-next/topics/function-parity.json').read_text())
    ids = {entry['id'] for entry in MANIFEST['pending'] + MANIFEST['partial']}
    assert not ids & set(topic['problems'])
    assert not any(ids & set(group['problems']) for group in topic['groups'])
    assert not any((ROOT/'site/data/graph-walk'/f'{i}.source.json').exists() for i in ids)


@pytest.mark.parametrize('entry', [e for e in MANIFEST['partial'] if 'authored_source' in e], ids=lambda v: v['id'])
def test_partial_record_verifies_only_its_finished_goals(entry):
    from shuxueshuo_server.graph_lesson.parity_extension_math import solve, verify
    from shuxueshuo_server.graph_lesson.stage_three.context import build_context
    record = json.loads((ROOT/entry['authored_source']).read_text())
    x = sp.Symbol('x', real=True)
    for target, status in entry['goals'].items():
        desc = build_context(record['candidate'], target).get('parity_extension_goal') or {}
        if status != 'math_and_execution_verified':
            assert not desc.get('structure_supported')
            continue
        model = solve(desc)
        expected = record['expected']['goals'][target]['expression']
        assert verify(desc, model)
        assert sp.expand(model['answer_expression'] - sp.sympify(expected, locals={'x': x})) == 0


@pytest.mark.parametrize('entry', MANIFEST['pending'], ids=lambda v: v['id'])
def test_pending_question_has_verified_answer_and_replay(entry, tmp_path):
    source_path = ROOT/entry['authored_source']
    record = json.loads(source_path.read_text())
    assert record['problem_id'] == entry['id'] == entry['course_source']['problemId']
    isolated_source = tmp_path/'authored.json'
    isolated_source.write_bytes(source_path.read_bytes())
    evidence = tmp_path/'evidence.json'
    recording = tmp_path/'recording'
    answer = import_course(isolated_source, recording, evidence)['answer']
    resumed = resume_sample(recording/'execution')['goals']
    assert all(goal['status'] == 'solved' for goal in resumed) and resumed[0]['answer'] == answer
    answers = {goal['target_ref']: goal['answer'] for goal in resumed}
    expected = record['expected'].get('goals') or {'/root/goals/0': record['expected']}
    assert set(answers) == set(expected)
    x = sp.Symbol('x', real=True)
    for target, gold in expected.items():
        if 'value' in gold:
            assert answers[target]['kind'] == 'find_value' and answers[target]['status'] == 'complete'
            assert answers[target]['value']['expression'] == gold['value']
        else:
            got = answers[target]
            assert got['kind'] == 'find_function_formula' and got['status'] == 'determined_on_domain'
            assert sp.expand(sp.sympify(got['expression']['expression'], locals={'x': x})
                             - sp.sympify(gold['expression'], locals={'x': x})) == 0
    course_source = tmp_path/'source.json'
    course_source.write_text(json.dumps(entry['course_source'], ensure_ascii=False))
    route = 'function-symmetry' if 'value' in expected['/root/goals/0'] else 'parity-extension'
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                            str(evidence), str(course_source), route],
                           capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout+check.stderr
