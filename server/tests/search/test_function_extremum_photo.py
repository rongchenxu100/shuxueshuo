"""T2 real photographs: replay original model turns and exercise the owned API."""
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
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import RecordedWorkflowProvider, forbidden, read
from tests.search.support import authenticated_client, session_for

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent/'fixtures/function-monotonicity-extremum'


def replay_photo(key, output):
    recording = RECORDINGS/key
    manifest = read(recording/'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((recording/name).read_bytes()).hexdigest() == digest
    source = read(recording/'source.json')
    assert sha256((ROOT/source['source']).read_bytes()).hexdigest() == source['source_sha256']
    raw = BytesIO()
    with Image.open(ROOT/source['source']) as im:
        im.crop(source['crop_pixels']).save(raw, format='PNG')
    assert raw.getvalue() == (recording/'original.png').read_bytes()
    ledger = read(recording/'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']] == manifest['call_stages']
    png = (recording/'question.png').read_bytes()
    provider = RecordedWorkflowProvider(recording, ledger, sha256(png).hexdigest())
    result = run_question_image(png, output, provider,
        problem_id=ledger['identity']['binding']['problem_id'], original_png=raw.getvalue())
    assert provider.position == len(ledger['calls'])
    assert result['candidate'] == read(recording/'result.json')['candidate']
    return result


@pytest.mark.parametrize('key', ['a16', 'a07', 'a18', 'b08', 'b10', 'b11', 'b14', 'b16_fixed'])
def test_real_t2_photo_keeps_roles_and_source_spans(key, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_photo(key, tmp_path/'recognition')
    assert result['status'] == 'reviewed_candidate' and result['features_ok']
    second = run_result(stage_one_result(result, key), tmp_path/'stage-two',
                        admission='student_upload', unsupported_root=tmp_path/'unsupported')
    goal, = second['goals']
    assert goal['primary'] == 'type-monotonicity-extremum'
    assert not goal['d1'].get('diagnostics')


@pytest.mark.parametrize('key', ['a14', 'a14_retry'])
def test_retained_photo_failures_are_not_counted_as_passes(key, tmp_path):
    result = replay_photo(key, tmp_path/'recognition')
    # OCR accuracy and solver admission are separate checks. A mistaken formula
    # can be solvable by the existing range route without passing photo acceptance.
    assert 'sqrt(1-2*x)' not in result['candidate']['root']['definitions'][0]
    second = run_result(stage_one_result(result, key), tmp_path/'stage-two',
                        admission='student_upload', unsupported_root=tmp_path/'unsupported')
    assert second['goals'][0].get('primary') != 'type-monotonicity-extremum'
    topic = read(ROOT/'site/data/knowledge-next/topics/function-monotonicity.json')
    assert not any('a14' in problem for problem in topic['problems'])


def test_original_named_set_failure_remains_an_unchanged_historical_record():
    recording = RECORDINGS/'b16'
    manifest = read(recording/'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((recording/name).read_bytes()).hexdigest() == digest
    assert read(recording/'result.json')['status'] != 'reviewed_candidate'
    # The fixed compiler exits this historical workflow earlier. New live
    # acceptance is recorded separately in b16_fixed, without rewriting history.
    assert read(RECORDINGS/'b16_fixed/recording.json')['status'] == 'reviewed_candidate'


@pytest.mark.parametrize('key,kind', [('a16','derived_answer'), ('a07','find_range'), ('b08','find_range')])
def test_t2_owned_lesson_api_and_resume(key, kind, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    root = tmp_path/'search'
    session = session_for(root)
    result = replay_photo(key, root/'replay')
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root/'submissions'/search_id
    directory.mkdir(parents=True)
    save(directory/dev_api.RESULT_FILE, result)
    recording = RECORDINGS/key
    with Image.open(recording/'question.png') as im:
        size = list(im.size)
    save(directory/'crop.json', {'page_id': page_id, 'box': [0,0,1,1], 'crop_size': size,
                               'bytes': (recording/'question.png').stat().st_size})
    for name in ('question.png','original.png'):
        shutil.copyfile(recording/name, directory/name)
    page = root/'pages'/page_id
    page.mkdir(parents=True)
    shutil.copyfile(recording/'original.png', page/'page.png')
    session.repository.register_page(session.user, page_id, {})
    session.repository.create_submission(session.user, search_id, page_id, [0,0,1,1])
    assert session.repository.associate(search_id, build_identity(result))
    run_stage_two(directory, result, provider=forbidden, unsupported_root=root/'unsupported')
    session.repository.set_state(search_id, recognition_state='reviewed', lesson_state='not_started')
    base = '/api/search/problems/'+search_id
    with authenticated_client(root) as client:
        assert client.get(base).status_code == 200
        assert client.post(base+'/lesson/start').status_code == 200
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            lesson = client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed','partial','failed','error','input_error'}:
                break
            time.sleep(.05)
        assert lesson['execution_status'] == 'completed', lesson
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url']).json()
        assert snapshot['goals']['/root/goals/0']['answer']['kind'] == kind
        assert all(s['status'] == 'interactive' for s in snapshot['interaction_states'])
        parts = [p for c in snapshot['interactions'] for p in c['parts']]
        assert parts and all(p.get('stem_board',{}).get('items',[{}, {'math':None}])[1]['math'] is None for p in parts if p.get('stem_board'))
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base+'/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
