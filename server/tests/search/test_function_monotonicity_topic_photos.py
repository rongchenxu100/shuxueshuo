"""Whole worksheet acceptance: immutable real calls, then current offline/API regression."""

import secrets
import shutil
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two, stage_one_result
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.segmentation import segment
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    image_hashes,
    read,
)
from tests.search.function_monotonicity_topic_gold import (
    KEYS,
    assert_answers,
    assert_function_transcription,
)
from tests.search.support import authenticated_client, session_for

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / 'fixtures/function-monotonicity-topic'
COMPLETE = [key for key in KEYS if key not in {'a14', 'b06'}]


def recording_for(key):
    return FIXTURES / read(FIXTURES / 'accepted.json')[key]


def checked_recording(recording):
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
    hashes = [sha256((recording / 'question.png').read_bytes()).hexdigest()]
    for call in ledger['calls']:
        request = read(recording / 'workflow' / call['directory'] / 'request.json')
        assert image_hashes(request) == hashes
        name = 'workflow/' + call['response_file']
        response = read(recording / name)
        assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][name]
        assert response['metadata']['provider'] == 'deepseek'
        assert response['raw_payload']['usage']['total_tokens'] > 0
    return ledger


def replay(key, output):
    recording = recording_for(key)
    ledger = checked_recording(recording)
    historical = read(recording / 'result.json')
    provider = RecordedWorkflowProvider(recording, ledger, expected_image_hashes(historical))
    result = run_question_image(
        (recording / 'question.png').read_bytes(), output, provider,
        problem_id=ledger['identity']['binding']['problem_id'],
        original_png=(recording / 'original.png').read_bytes())
    assert provider.position == len(ledger['calls'])
    assert result['candidate'] == historical['candidate']
    return result


@pytest.mark.parametrize('key', COMPLETE)
def test_real_photo_source_answers_and_current_owned_lesson(key, tmp_path, monkeypatch):
    """Real historical model evidence plus current generation/start/reopen APIs; no LLM fallback."""
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    recording = recording_for(key)
    evidence = read(recording / 'recording.json')['api_acceptance']
    assert evidence['lesson_status'] == 'ready' and evidence['execution_status'] == 'completed'
    assert evidence['source_located'] and evidence['interactions_ready']
    assert evidence['same_stream_on_reopen'] and evidence['same_snapshot_on_reopen']
    assert_answers(key, read(recording / 'snapshot.json'))
    root = tmp_path / 'search'
    result = replay(key, root / 'replay')
    assert result['status'] == 'reviewed_candidate' and result['features_ok']
    assert_function_transcription(key, result['candidate'])
    session = session_for(root)
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root / 'submissions' / search_id
    directory.mkdir(parents=True)
    save(directory / dev_api.RESULT_FILE, result)
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
        assert_answers(key, snapshot)
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base + '/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot


def test_printed_local_monotonicity_does_not_invent_a_complete_domain(tmp_path):
    result = replay('b06', tmp_path / 'replay')
    assert result['status'] == 'reviewed_candidate'
    mono = result['candidate']['root']['goals'][0]['function_monotonicity']
    assert 'function_domain' not in mono
    second = run_result(stage_one_result(result, 'b06'), tmp_path / 'stage-two',
                        admission='student_upload', unsupported_root=tmp_path / 'unsupported')
    assert not any(g['status'] == 'resolved' for g in second['goals'])
    assert read(recording_for('b06') / 'recording.json')['api_acceptance']['lesson_status'] == 'unsupported'


def test_wrong_radical_extent_is_not_counted_as_a_successful_photo():
    # Even a model's "confirmed" is not enough: the independently read printed
    # radical stops after 1-2x. Retain every failed reading rather than fixing
    # its JSON and presenting that as a successful OCR/model run.
    assert 'a14' not in read(FIXTURES / 'accepted.json')
    for batch in ('second', 'retry', 'fourth'):
        recording = FIXTURES / batch / 'a14'
        checked_recording(recording)
        value = read(recording / 'result.json')['candidate']
        with pytest.raises(AssertionError):
            assert_function_transcription('a14', value)
        assert read(recording / 'recording.json')['api_acceptance']['lesson_status'] != 'ready'


def test_all_historical_attempts_and_image_probes_remain_immutable():
    for path in FIXTURES.rglob('recording.json'):
        manifest = read(path)
        for name, digest in manifest['files'].items():
            assert sha256((path.parent / name).read_bytes()).hexdigest() == digest
    for name in ('original', 'upscale'):
        recording = FIXTURES / 'a14-image-probes' / name
        manifest = read(recording / 'recording.json')
        assert manifest['outcome'] == 'root_extent_incorrect'
        assert sha256((FIXTURES / manifest['source_recording'] / 'original.png').read_bytes()).hexdigest() == manifest['original_sha256']
        with pytest.raises(AssertionError):
            assert_function_transcription('a14', read(recording / 'result.json')['candidate'])


@pytest.mark.parametrize('page,numbers', [(1, range(1, 10)), (2, range(10, 19)),
                                         (3, range(1, 9)), (4, range(9, 17))])
def test_real_ocr_locates_every_printed_question(page, numbers):
    directory = FIXTURES / 'ocr'
    record = read(directory / 'manifest.json')[str(page)]
    assert record['detector_side'] == 960
    assert sha256((ROOT / record['source']).read_bytes()).hexdigest() == record['source_sha256']
    path = directory / record['file']
    assert sha256(path.read_bytes()).hexdigest() == record['sha256']
    observed = read(path)
    assert observed['latency_ms']['detect'] > 0
    result = segment(observed)
    assert result.mode == 'numbered'
    assert [r['number'] for r in result.regions] == list(numbers)
