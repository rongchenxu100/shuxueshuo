"""Published T5 questions preserve their original goals and verified course recipe."""
import json
import subprocess

import pytest

from shuxueshuo_server.graph_lesson.stage_three.contracts import ROOT
from shuxueshuo_server.graph_lesson.stage_three.runner import resume_sample
from tools.import_authored_graph_course import import_course

STAGING = ROOT/'internal/senior-high/authored-courses/function-parity-t5-staged-20261112/pending-topic.json'
MANIFEST = json.loads(STAGING.read_text())


def test_published_staging_preserves_all_original_goals():
    topic = json.loads((ROOT/'site/data/knowledge-next/topics/function-parity.json').read_text())
    assert MANIFEST['publish_state'] == 'published'
    for entry in MANIFEST['pending']:
        assert topic['problems'][entry['id']] == entry['topic_entry']
        assert json.loads((ROOT/f"site/data/graph-walk/{entry['id']}.source.json").read_text()) == entry['course_source']
        record = json.loads((ROOT/entry['authored_source']).read_text())
        goals = record['candidate']['root']['goals']
        source = entry['course_source']
        assert (source.get('targetRefs') or [source['targetRef']]) == [f'/root/goals/{i}' for i in range(len(goals))]


@pytest.mark.parametrize('entry', MANIFEST['pending'], ids=lambda e: e['id'])
@pytest.mark.stage_three_db
def test_staged_course_grading_replay_and_math_rendering(entry, tmp_path):
    original = ROOT/entry['authored_source']
    record = json.loads(original.read_text())
    isolated = tmp_path/'authored.json'
    isolated.write_bytes(original.read_bytes())
    evidence, recording = tmp_path/'evidence.json', tmp_path/'recording'
    import_course(isolated, recording, evidence)
    goals = resume_sample(recording/'execution')['goals']
    assert len(goals) == len(record['expected']['goals'])
    for g, gold in zip(goals, record['expected']['goals']):
        assert g['status'] == 'solved', g
        assert g['primary'] == gold['type']
        assert g['answer']['value']['expression'] == gold['value']
    source = tmp_path/'source.json'
    source.write_text(json.dumps(entry['course_source'], ensure_ascii=False))
    check = subprocess.run(['node', str(ROOT/'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                            str(evidence), str(source), 'function-symmetry'], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout+check.stderr
    assert json.loads(check.stdout)['targets'] == [g['target_ref'] for g in goals]
