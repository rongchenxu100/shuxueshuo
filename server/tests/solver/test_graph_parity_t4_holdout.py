"""FP-T4 R4 holdouts and their regressions compile, grade and replay in isolation; none is published."""
import json
import subprocess

import pytest

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.runner import resume_sample
from tools.import_authored_graph_course import import_course

FOLDER = ROOT/'internal/senior-high/authored-courses/function-parity-t4-holdout-20261111'
MANIFEST = json.loads((FOLDER/'manifest.json').read_text())


def test_holdouts_are_not_staged_or_public():
    staged = json.loads((ROOT/'internal/senior-high/authored-courses/function-parity-t4-staged-20261111/'
                         'pending-topic.json').read_text())
    topic = json.loads((ROOT/'site/data/knowledge-next/topics/function-parity.json').read_text())
    ids = {row['id'] for row in MANIFEST['holdouts']}
    assert not ids & {row['id'] for rows in staged.values() if isinstance(rows, list) for row in rows
                      if isinstance(row, dict)}
    assert not ids & set(topic['problems'])
    classes = {row['class'] for row in MANIFEST['holdouts'] if row['first_run'] == 'passed'}
    assert classes == {'half_axis_reflection', 'same_side_comparison', 'abstract_sign'}


@pytest.mark.parametrize('entry', MANIFEST['holdouts'], ids=lambda v: v['id'])
@pytest.mark.stage_three_db
def test_holdout_answer_replay_and_course(entry, tmp_path):
    record = json.loads((ROOT/entry['authored_source']).read_text())
    assert record['problem_id'] == entry['id']
    source = tmp_path/'authored.json'
    source.write_bytes((ROOT/entry['authored_source']).read_bytes())
    evidence, recording = tmp_path/'evidence.json', tmp_path/'recording'
    answer = import_course(source, recording, evidence)['answer']
    goal, = resume_sample(recording/'execution')['goals']
    assert goal['status'] == 'solved' and goal['answer'] == answer
    assert answer['set']['expression'] == record['expected']['expression']
    cards = json.dumps(json.loads(evidence.read_text()), ensure_ascii=False)
    assert '左' not in cards and '右' not in cards
    course = tmp_path/'source.json'
    course.write_text(json.dumps({'schemaVersion': 1, 'problemId': entry['id'], 'title': entry['id'],
                                  'preview': True, 'page': f"/lab/graph-walk/{entry['id']}/",
                                  'topicHref': '/topics/function-parity/',
                                  'targetRef': '/root/goals/0', 'authoringSource': entry['authored_source'],
                                  'evidence': str(evidence)}, ensure_ascii=False))
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                            str(evidence), str(course), entry['route']], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout+check.stderr
