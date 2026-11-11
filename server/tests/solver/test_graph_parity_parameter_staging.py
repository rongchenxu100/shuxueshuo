"""Staged topic questions compile and grade without publishing unfinished links."""
import json
import subprocess

import pytest
import sympy as sp

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.runner import resume_sample
from tools.import_authored_graph_course import import_course

STAGING = ROOT/'internal/senior-high/authored-courses/function-parity-t2-staged-20261111/pending-topic.json'
MANIFEST = json.loads(STAGING.read_text())


@pytest.mark.parametrize('entry', MANIFEST['pending'], ids=lambda v: v['id'])
def test_pending_question_has_verified_answer_and_replay(entry, tmp_path):
    source_path = ROOT/entry['authored_source']
    record = json.loads(source_path.read_text())
    assert record['problem_id'] == entry['id'] == entry['course_source']['problemId']
    # A temporary record cannot update a public source's authoringSource, even
    # after this representative is eventually published in the unified build.
    isolated_source = tmp_path/'authored.json'
    isolated_source.write_bytes(source_path.read_bytes())
    evidence = tmp_path/'evidence.json'
    recording = tmp_path/'recording'
    result = import_course(isolated_source, recording, evidence)
    answer = result['answer']
    expected = record['expected']
    if 'joint_values' in expected:
        assert answer['result_type'] == 'parameter_family'
        family, = answer['families']
        assert [a['value']['expression'] for a in family['assignments']] == expected['joint_values']
        assert family['free_parameters'] == expected['free_parameters']
        assert family['nonzero'] == expected['nonzero']
    else:
        wanted = (sp.FiniteSet(*expected['parameter_values']) if 'parameter_values' in expected
                  else sp.sympify(expected['parameter_set']))
        actual = answer['parameter_set'] if answer.get('result_type') == 'parameter_value' else answer['set']
        assert sp.sympify(actual['expression']) == wanted
    resumed = resume_sample(recording/'execution')['goals'][0]
    assert resumed['status'] == 'solved' and resumed['answer'] == answer
    course_source = tmp_path/'source.json'
    course_source.write_text(json.dumps(entry['course_source'], ensure_ascii=False))
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                            str(evidence), str(course_source)], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout+check.stderr
