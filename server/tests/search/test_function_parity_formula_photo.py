"""FP-T3 original-photo provenance, live failures and zero-network course regression."""
import json
import subprocess
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
import sympy as sp
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
RECORDINGS = Path(__file__).parent / 'fixtures/function-parity-formula'
RETRIED = {'a03', 'a04', 'a06', 'a09', 'a15'}
# Independently calculated from the printed questions; never model inputs.
GOLD = {
    'a03': [('value', '-2', None)],
    'a04': [('formula', 'x**2+4*Abs(x)', None)],
    'a06': [('value', '5', None)],
    'a07': [('formula', 'x**2-x', 'Interval.open(-oo, 0)')],
    'a08': [('formula', '-x**2-3*x+1', 'Interval.open(-oo, 0)')],
    'a09': [('value', '-15', None), ('formula', '-2*x**2-x', 'Interval(-oo, 0)')],
    'a12': [('value', '-4', None)],
    'a13': [('value', '-3', None)],
    'a15': [('value', '-8', None)],
}


def recording_for(key):
    if key == 'a15':
        return RECORDINGS / 'a15-recheck' / key
    return RECORDINGS / ('fixed' if key in RETRIED else 'initial') / key


def assert_answers(key, goals):
    assert set(goals) == {f'/root/goals/{i}' for i in range(len(GOLD[key]))}
    x = sp.Symbol('x', real=True)
    for i, (kind, expression, requested) in enumerate(GOLD[key]):
        answer = goals[f'/root/goals/{i}']['answer']
        if kind == 'value':
            assert answer['kind'] == 'find_value' and answer['status'] == 'complete'
            assert answer['value']['expression'] == expression
        else:
            assert answer['kind'] == 'find_function_formula' and answer['status'] == 'determined_on_domain'
            assert sp.simplify(sp.sympify(answer['expression']['expression'], locals={'x': x})
                               - sp.sympify(expression, locals={'x': x})) == 0
            assert (answer.get('requested_domain') or {}).get('expression') == requested
            if key == 'a04':
                assert answer['declared_domain'] is None and answer['determined_domain'] is None
                assert answer['domain_identity'] == 'declared_symmetric_domain'


def test_original_photos_and_all_live_attempts_remain_immutable():
    for attempt, keys in [('initial', GOLD), ('fixed', RETRIED), ('a15-recheck', ['a15'])]:
        directory = RECORDINGS / attempt
        for upload in read(directory / 'uploads.json'):
            assert sha256((ROOT / upload['source']).read_bytes()).hexdigest() == upload['source_sha256']
            for name, digest in {upload['file']: upload['sha256'], **upload['artifacts']}.items():
                assert sha256((directory / name).read_bytes()).hexdigest() == digest
            assert len(upload['artifacts']) == 2  # Actual OCR and segmentation, not a seeded candidate.
        for key in keys:
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
            assert ledger['calls'][0]['stage'] == 'extract' and ledger['calls'][-1]['stage'] == 'review'
            assert len(ledger['calls']) == manifest['historical_semantic_calls']
            assert sum(c['network_attempts'] for c in ledger['calls']) == manifest['historical_network_attempts']
            for call in ledger['calls']:
                name = 'workflow/' + call['response_file']
                response = read(recording / name)
                assert response['metadata']['provider'] == 'deepseek'
                assert response['raw_payload']['usage']['total_tokens'] > 0
                assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][name]
            api = manifest['api_acceptance']
            if recording == recording_for(key):
                assert api['source_located'] and api['interactions_ready']
                assert api['execution_status'] == 'completed'
                assert api['same_stream_on_reopen'] and api['same_snapshot_on_reopen']
                assert_answers(key, read(recording / 'snapshot.json')['goals'])
            elif attempt == 'fixed' and key == 'a15':
                # Keep the actual timeout, even though the same input passes replay.
                assert api['execution_status'] == 'completed' and not api['interactions_ready']
                snapshot = read(recording / 'snapshot.json')
                assert_answers(key, snapshot['goals'])
                assert all(row['reason'] == 'compile_timeout' for row in snapshot['interactions'])
            else:
                assert api['lesson_status'] == 'unsupported' or not api['source_located']


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


@pytest.mark.parametrize('key', sorted(RETRIED))
def test_first_live_transcriptions_now_bind_all_original_goals(key, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay(RECORDINGS / 'initial' / key, tmp_path / 'recognition')
    second = run_result(stage_one_result(result, key), tmp_path / 'stage-two', admission='student_upload',
                        provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    assert len(second['goals']) == len(GOLD[key])
    assert all(g['status'] == 'resolved' and not g['d1']['diagnostics'] for g in second['goals'])


@pytest.fixture(scope='module')
def execution_db(tmp_path_factory):
    return session_for(tmp_path_factory.mktemp('fp-t3-photo-regression')).repository.db


@pytest.mark.parametrize('key', GOLD)
def test_live_transcription_executes_exports_grades_and_resumes(key, tmp_path, monkeypatch, execution_db):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay(recording_for(key), tmp_path / 'recognition')
    second = run_result(stage_one_result(result, key), tmp_path / 'stage-two', admission='student_upload',
                        provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    shown = present_lesson(second, result['features'], result['candidate']['original_text'], candidate=result['candidate'])
    assert len(shown['goals']) == len(GOLD[key])
    assert all(g['d1']['rows'] and not g['d1'].get('diagnostics') for g in shown['goals'])
    output = tmp_path / 'stage-three'
    with storage_context(execution_db):
        executed = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
        assert executed['status'] == 'completed'
        assert all(g['status'] == 'solved' for g in executed['goals'])
        assert_answers(key, {g['target_ref']: g for g in executed['goals']})
        snapshot = open_store(output).snapshot()
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert runner.resume_sample(output)['goals'] == executed['goals']
        assert open_store(output).snapshot()['handoffs'] == snapshot['handoffs']
    evidence = export_course(output, 'function-parity-' + key)
    (tmp_path / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False))
    staging = read(ROOT / 'internal/senior-high/authored-courses/function-parity-t3-staged-20261111/pending-topic.json')
    source = next(row['course_source'] for row in staging['pending'] if row['id'] == 'function-parity-' + key)
    (tmp_path / 'source.json').write_text(json.dumps(source, ensure_ascii=False))
    route = 'function-symmetry' if GOLD[key][0][0] == 'value' else 'parity-extension'
    checked = subprocess.run(['node', str(ROOT / 'tools/tests/fixtures/parity-parameter-course-check.mjs'),
                              str(tmp_path / 'evidence.json'), str(tmp_path / 'source.json'), route],
                             capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr
