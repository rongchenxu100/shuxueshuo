"""FP-T5 real-photo provenance and offline, complete-course regression."""
import json
import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.search.lesson import present_lesson, stage_one_result
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
)
from tests.search.support import session_for
from tools.export_graph_walk_course import export_course

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/function-symmetry'
# Checked independently from printed conditions, never supplied to the model.
GOLD = {'a10': ['0', '1'], 'a14': ['0']}
FINAL_ATTEMPTS = {'a10': 'initial', 'a14': 'initial'}


def recording_for(key):
    return RECORDINGS / FINAL_ATTEMPTS[key] / key


def assert_answers(key, goals):
    assert set(goals) == {f'/root/goals/{i}' for i in range(len(GOLD[key]))}
    for i, expected in enumerate(GOLD[key]):
        goal = goals[f'/root/goals/{i}']
        assert goal['status'] == 'solved'
        assert goal['answer']['status'] == 'complete'
        assert goal['answer']['value']['expression'] == expected


def test_source_photos_and_all_real_attempts_are_immutable():
    attempts = sorted(RECORDINGS.glob('*/summary.json'))
    assert attempts
    accepted = set()
    for summary_file in attempts:
        directory = summary_file.parent
        for upload in read(directory / 'uploads.json'):
            assert sha256((ROOT / upload['source']).read_bytes()).hexdigest() == upload['source_sha256']
            for name, digest in {upload['file']: upload['sha256'], **upload['artifacts']}.items():
                assert sha256((directory / name).read_bytes()).hexdigest() == digest
            assert len(upload['artifacts']) == 2
        for row in read(summary_file)['cases']:
            key = row['case']
            recording = directory / key
            manifest, source = read(recording / 'recording.json'), read(recording / 'source.json')
            for name, digest in manifest['files'].items():
                assert sha256((recording / name).read_bytes()).hexdigest() == digest
            assert sha256((ROOT / source['source']).read_bytes()).hexdigest() == source['source_sha256']
            raw = BytesIO()
            with Image.open(ROOT / source['source']) as image:
                image.crop(source['crop_pixels']).save(raw, format='PNG')
            assert raw.getvalue() == (recording / 'original.png').read_bytes()
            ledger = read(recording / 'workflow/ledger.json')
            assert ledger['calls'][0]['stage'] == 'extract'
            assert len(ledger['calls']) == manifest['historical_semantic_calls']
            assert sum(c['network_attempts'] for c in ledger['calls']) == manifest['historical_network_attempts']
            for call in ledger['calls']:
                name = 'workflow/' + call['response_file']
                response = read(recording / name)
                assert response['metadata']['provider'] == 'deepseek'
                assert response['raw_payload']['usage']['total_tokens'] > 0
                assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][name]
            if recording == recording_for(key):
                accepted.add(key)
                api = manifest['api_acceptance']
                assert api['source_located'] and api['interactions_ready']
                assert api['recognition_status'] == 'reviewed' and api['execution_status'] == 'completed'
                assert api['same_stream_on_reopen'] and api['same_snapshot_on_reopen']
                assert_answers(key, read(recording / 'snapshot.json')['goals'])
    assert accepted == set(GOLD)


def replay(recording, output):
    historical = read(recording / 'result.json')
    ledger = read(recording / 'workflow/ledger.json')
    provider = RecordedWorkflowProvider(recording, ledger, expected_image_hashes(historical))
    result = run_question_image((recording / 'question.png').read_bytes(), output, provider,
                               problem_id=ledger['identity']['binding']['problem_id'],
                               original_png=(recording / 'original.png').read_bytes())
    assert provider.position == len(ledger['calls'])
    assert result['candidate'] == historical['candidate']
    assert result['source_reviewed'] and result['features_ok']
    return result


@pytest.fixture(scope='module')
def execution_db(tmp_path_factory):
    return session_for(tmp_path_factory.mktemp('fp-t5-photo-regression')).repository.db


@pytest.mark.parametrize('key', GOLD)
@pytest.mark.stage_three_db
def test_real_transcription_executes_grades_and_resumes_all_goals(key, tmp_path, monkeypatch, execution_db):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay(recording_for(key), tmp_path / 'recognition')
    second = run_result(stage_one_result(result, key), tmp_path / 'stage-two', admission='student_upload',
                        provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    shown = present_lesson(second, result['features'], result['candidate']['original_text'], candidate=result['candidate'])
    assert len(shown['goals']) == len(GOLD[key])
    assert all(g['primary'] == 'type-function-symmetry' for g in shown['goals'])
    assert all(g['d1']['rows'] and not g['d1'].get('diagnostics') for g in shown['goals'])
    output = tmp_path / 'stage-three'
    with storage_context(execution_db):
        executed = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
        assert executed['status'] == 'completed'
        assert_answers(key, {g['target_ref']: g for g in executed['goals']})
        snapshot = open_store(output).snapshot()
        assert snapshot['interaction_states']
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert runner.resume_sample(output)['goals'] == executed['goals']
        assert open_store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, 'function-parity-' + key)
    (tmp_path / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False))
    staging = read(ROOT / 'internal/senior-high/authored-courses/function-parity-t5-staged-20261112/pending-topic.json')
    source = next(row['course_source'] for row in staging['pending'] if row['id'] == 'function-parity-' + key)
    assert (source.get('targetRefs') or [source['targetRef']]) == [g['target_ref'] for g in executed['goals']]
    (tmp_path / 'source.json').write_text(json.dumps(source, ensure_ascii=False))
    checked = subprocess.run(['node', str(ROOT / 'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                              str(tmp_path / 'evidence.json'), str(tmp_path / 'source.json'), 'function-symmetry'],
                             capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert json.loads(checked.stdout)['targets'] == [g['target_ref'] for g in executed['goals']]
