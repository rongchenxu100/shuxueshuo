"""Real T4 photo evidence and deterministic OCR-to-lesson regression."""

import secrets
import shutil
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
import sympy as sp
from PIL import Image

from shuxueshuo_server.graph_lesson.extremum_math import domain
from shuxueshuo_server.graph_lesson.monotonicity_parameter_math import solve, verify
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two, stage_one_result
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    image_hashes,
    read,
)
from tests.search.support import authenticated_client, session_for

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/function-monotonicity-parameter'
TARGET = '/root/goals/0'
# Independently transcribed/solved printed questions; never sent to the model.
GOLD = {
    'a05': ('x^2-m*x+5', '[1,2]', 'increasing', sp.Interval(-sp.oo, 2)),
    'a06': ('piecewise(x^2-a*x+a/2,x>=1,(2*a+4)*x-5,x<1)', 'ℝ',
            'increasing', sp.Interval.Lopen(-2, sp.Rational(4, 5))),
    'a08': ('piecewise(-x^2+a*x-a,x>2,1-a*x,x<=2)', 'ℝ',
            'decreasing', sp.Interval.Lopen(0, sp.Rational(5, 3))),
    'a09': ('x^2-2*(a-1)*x+2', '(-∞,4]', 'decreasing', sp.Interval(5, sp.oo)),
    'a10': ('piecewise(a/x,0<x<=1,x-a/x-2,x>1)', '(0,+∞)',
            'increasing', sp.Interval(-1, sp.Rational(-1, 2))),
    'a11': ('a*x^2-2*x+3', '[2,+∞)', 'decreasing', sp.Interval(-sp.oo, 0)),
    'a13': ('sqrt(a*x^2+2*x-5*a+5)', '(-∞,-2]',
            'decreasing', sp.Interval(sp.Rational(1, 2), 1)),
    'a17': ('piecewise((3*a-1)*x+4*a,x<1,a/x,x>=1)', 'ℝ',
            'decreasing', sp.Interval.Ropen(sp.Rational(1, 6), sp.Rational(1, 3))),
}


def checked_recording(key):
    recording = RECORDINGS / key
    manifest = read(recording / 'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((recording / name).read_bytes()).hexdigest() == digest
    source = read(recording / 'source.json')
    assert sha256((ROOT / source['source']).read_bytes()).hexdigest() == source['source_sha256']
    raw = BytesIO()
    with Image.open(ROOT / source['source']) as image:
        image.crop(source['crop_pixels']).save(raw, format='PNG')
    assert raw.getvalue() == (recording / 'original.png').read_bytes()
    ledger = read(recording / 'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']] == manifest['call_stages']
    assert len(ledger['calls']) == manifest['historical_semantic_calls']
    assert sum(c.get('network_attempts', 0) for c in ledger['calls']) == manifest['historical_network_attempts']
    hashes = expected_image_hashes(read(recording / 'result.json'))
    assert hashes[0] == sha256((recording / 'question.png').read_bytes()).hexdigest()
    for call in ledger['calls']:
        request = read(recording / 'workflow' / call['directory'] / 'request.json')
        assert image_hashes(request) == hashes
        response_name = 'workflow/' + call['response_file']
        response = read(recording / response_name)
        assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][response_name]
        assert response['metadata']['provider'] == 'deepseek'
        assert response['raw_payload']['usage']['total_tokens'] > 0
    return recording


def replay_photo(key, output):
    recording = checked_recording(key)
    ledger = read(recording / 'workflow/ledger.json')
    historical = read(recording / 'result.json')
    provider = RecordedWorkflowProvider(recording, ledger, expected_image_hashes(historical))
    result = run_question_image(
        (recording / 'question.png').read_bytes(), output, provider,
        problem_id=ledger['identity']['binding']['problem_id'],
        original_png=(recording / 'original.png').read_bytes())
    assert provider.position == len(ledger['calls'])
    assert result['candidate'] == historical['candidate']
    return result


def test_original_page_upload_ocr_evidence_is_preserved():
    directory = RECORDINGS / 'uploads'
    records = read(directory / 'manifest.json')['uploads']
    assert len(records) == 6
    for record in records:
        assert sha256((directory / record['file']).read_bytes()).hexdigest() == record['sha256']
        assert sha256((ROOT / record['source']).read_bytes()).hexdigest() == record['source_sha256']
        response = read(directory / record['file'])
        assert response['status_code'] == 200
        assert response['body']['orientation']['rotation_degrees'] == 0
        assert response['body']['mode'] == 'numbered' and len(response['body']['regions']) == 9


@pytest.mark.parametrize('key', GOLD)
def test_fresh_photo_transcription_math_and_lesson_evidence(key, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_photo(key, tmp_path / 'recognition')
    assert result['status'] == 'reviewed_candidate' and result['features_ok']
    candidate = result['candidate']
    assert len(candidate['root']['goals']) == 1
    goal = candidate['root']['goals'][0]
    assert goal['kind'] == 'find_range' and goal['symbol'] == ('m' if key == 'a05' else 'a')
    description = build_context(candidate, TARGET)['mono_parameter_goal']
    req = description['requirement']
    expression, interval, direction, expected = GOLD[key]
    assert parse(req['expression']) == parse(expression)
    assert domain(parse(req['input_domain'])) == domain(parse(interval))
    assert req['direction'] == direction and req['strict'] is True
    second = run_result(stage_one_result(result, key), tmp_path / 'stage-two',
                        admission='student_upload', unsupported_root=tmp_path / 'unsupported')
    assert second['status'] == 'completed'
    assert all(g['status'] == 'resolved' and g['primary'] == 'type-monotonicity-parameter'
               and not g['d1']['diagnostics'] for g in second['goals'])
    model = solve(description)
    assert model['feasible_set'] == expected and verify(description, model)
    # The API files below are immutable evidence of fresh live calls, not replay.
    evidence = read(RECORDINGS / key / 'recording.json')['api_acceptance']
    assert evidence['lesson_status'] == 'ready' and evidence['execution_status'] == 'completed'
    assert evidence['source_located'] and evidence['interactions_ready']
    assert evidence['same_stream_on_reopen'] and evidence['same_snapshot_on_reopen']
    snapshot = read(RECORDINGS / key / 'snapshot.json')
    assert decode_value(snapshot['goals'][TARGET]['feasible_set']['exact']) == expected
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])


@pytest.mark.parametrize('key', [
    'a08-initial', 'a11-initial', 'a13-initial', 'a17-initial',
    'a08-confirmation', 'a13-source-card', 'a17-card-error',
])
def test_live_failures_remain_unchanged_evidence(key):
    recording = checked_recording(key)
    evidence = read(recording / 'recording.json')['api_acceptance']
    assert evidence['lesson_status'] != 'ready'
    assert not (recording / 'snapshot.json').exists()
    if key == 'a08-confirmation':
        assert evidence['recognition_status'] == 'needs_confirmation'
        assert read(recording / 'recording.json')['call_stages'] == ['extract']


@pytest.mark.parametrize('key,recording_key', [
    ('a11', 'a11'), ('a08', 'a08'), ('a10', 'a10'), ('a13', 'a13'),
    ('a13', 'a13-source-card'), ('a17', 'a17-card-error'),
])
def test_photo_recognition_generates_and_reopens_owned_lesson(key, recording_key, tmp_path, monkeypatch):
    """Current API integration for all four families, using recorded model I/O."""
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    root = tmp_path / 'search'
    session = session_for(root)
    result = replay_photo(recording_key, root / 'replay')
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root / 'submissions' / search_id
    directory.mkdir(parents=True)
    save(directory / dev_api.RESULT_FILE, result)
    recording = RECORDINGS / recording_key
    with Image.open(recording / 'question.png') as image:
        size = list(image.size)
    save(directory / 'crop.json', {'page_id': page_id, 'box': [0, 0, 1, 1], 'crop_size': size,
                                   'bytes': (recording / 'question.png').stat().st_size})
    for name in ('question.png', 'original.png'):
        shutil.copyfile(recording / name, directory / name)
    page = root / 'pages' / page_id
    page.mkdir(parents=True)
    shutil.copyfile(recording / 'original.png', page / 'page.png')
    session.repository.register_page(session.user, page_id, {})
    session.repository.create_submission(session.user, search_id, page_id, [0, 0, 1, 1])
    assert session.repository.associate(search_id, build_identity(result))
    run_stage_two(directory, result, provider=forbidden, unsupported_root=root / 'unsupported')
    session.repository.set_state(search_id, recognition_state='reviewed', lesson_state='not_started')
    base = '/api/search/problems/' + search_id
    with authenticated_client(root) as client:
        assert client.post(base + '/lesson/start').status_code == 200
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            lesson = client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}:
                break
            time.sleep(.05)
        assert lesson['execution_status'] == 'completed', lesson
        assert all(g['d1']['rows'] and not g['d1'].get('diagnostics') for g in lesson['goals'])
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url']).json()
        assert decode_value(snapshot['goals'][TARGET]['feasible_set']['exact']) == GOLD[key][3]
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base + '/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
