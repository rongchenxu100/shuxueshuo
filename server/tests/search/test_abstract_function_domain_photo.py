"""Replay Q25's real browser photo and owned API, with all model I/O forbidden."""

import time
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.lesson import public_problem_text
from shuxueshuo_server.search.question_image import question_png
from tests.search.function_equality_recording import (
    forbidden,
    read,
    replay_recording,
    seed_photo_recording,
)
from tests.search.support import authenticated_client

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / 'internal/senior-high/source-images/function-concepts-q25'
RECORDING_ROOT = Path(__file__).parent / 'fixtures/abstract-function-domain'
RECORDINGS = [RECORDING_ROOT / name for name in (
    'q25-browser-recorded-20261028',
    'q25-final-browser-recorded-20261028',
)]
FINAL_RECORDING = RECORDINGS[-1]
TARGET = '/root/goals/0'


def test_q25_corrected_crop_preserves_pixels_and_retains_rejected_truncation():
    source = read(SOURCE / 'manifest.json')
    assert source['crop']['xyxy'] == [100, 500, 649, 535]
    assert source['previous_crop']['xyxy'] == [50, 455, 717, 522]
    assert source['previous_crop']['status'] == 'rejected_truncated_question'
    assert source['previous_crop']['sha256'] == 'bb88f6a4fccf17b002697f2afdd776ba21838287e3bdb0b135a6b182f6ad559e'
    assert source['previous_crop']['sha256'] != source['crop']['sha256']
    page_file = SOURCE / source['page']['file']
    assert sha256(page_file.read_bytes()).hexdigest() == source['page']['sha256']
    with Image.open(page_file) as page:
        for name in ('crop', 'previous_crop'):
            crop = source[name]
            crop_file = SOURCE / crop['file']
            assert sha256(crop_file.read_bytes()).hexdigest() == crop['sha256']
            with Image.open(crop_file) as image:
                assert list(image.size) == crop['size']
                assert image.convert('RGB').tobytes() == page.crop(crop['xyxy']).convert('RGB').tobytes()
    # Successful recording uses the corrected source, never the retained bad crop.
    for recording in RECORDINGS:
        manifest = read(recording / 'recording.json')
        assert manifest['source'] == str((SOURCE / 'manifest.json').relative_to(REPO))
        assert manifest['upload_source_sha256'] == source['crop']['sha256']
        assert REPO / manifest['upload_source'] == SOURCE / source['crop']['file']


@pytest.mark.parametrize('recording', RECORDINGS, ids=lambda path: path.name)
def test_q25_photo_replays_every_real_call_and_preserves_known_and_requested_domains(tmp_path, monkeypatch, recording):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    manifest = read(recording / 'recording.json')
    assert manifest['call_stages'] == ['extract', 'review']
    assert manifest['historical_semantic_calls'] == 2
    upload = REPO / manifest['upload_source']
    original = recording / manifest['product_crop_source']['file']
    assert sha256(upload.read_bytes()).hexdigest() == manifest['upload_source_sha256']
    assert sha256(original.read_bytes()).hexdigest() == manifest['product_crop_source']['sha256']
    with Image.open(upload) as uploaded, Image.open(original) as cropped:
        assert manifest['product_crop']['box'] == [0, 0, 1, 1]
        assert list(uploaded.size) == list(cropped.size) == manifest['product_crop']['page_size']
        assert question_png(cropped) == (recording / 'question.png').read_bytes()
    result = replay_recording(tmp_path / 'replay', recording)
    root = result['candidate']['root']
    assert not any(root.get(key) for key in ('definitions', 'facts', 'children'))
    goal, = root['goals']
    assert goal == {'kind': 'find_abstract_domain', 'known_call': 'f(x)',
                    'known_domain': '[-3,2]', 'strength': 'exact', 'target_call': 'f(2*x-1)'}
    feature = next(row['value'] for row in result['features'] if row['feature_id'] == 'abstract_function_domain')
    assert feature['structure_supported'] and feature['known_form'] == 'identity'
    assert feature['known_variable'] == feature['variable'] == 'x'
    assert (feature['target_slope'], feature['target_intercept']) == ('2', '-1')
    display = public_problem_text(result)
    assert '例8' not in display
    assert '[-3,2]' in display and 'f(2x-1)' in display
    assert '3/2' not in display


def test_q25_photo_api_exposes_reading_solves_and_recovers_all_teaching_decisions(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    root = tmp_path / 'private-search'
    _, directory = seed_photo_recording(root, FINAL_RECORDING)
    base = f'/api/search/problems/{directory.name}'
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal, = first.json()['lesson']['goals']
        assert goal['primary'] == 'type-abstract-function-domain'
        assert not goal['d1'].get('diagnostics')
        assert len(goal['d1']['rows']) == 1
        assert len(goal['d1']['givens']) == 1
        intro = goal['walk']['bundle']['intro']
        assert [step['id'] for step in intro] == ['D1', 'D2']
        reading = intro[0]
        assert reading['interaction']['type'] == 'choice'
        assert 'f(x)' in reading['question'] and '[-3,2]' in reading['question']
        assert 'f(2x-1)' in reading['question']
        assert any('自变量 $x$' in option['label'] for option in reading['interaction']['options'])
        assert reading['effects']['nodes'] == ['function-concept']
        assert client.post(base + '/lesson/start').status_code == 200
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            response = client.get(base)
            assert response.status_code == 200, response.text
            lesson = response.json()['lesson']
            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}:
                break
            time.sleep(0.05)
        assert lesson['execution_status'] == 'completed', lesson
        assert lesson['goals'][0]['walk']['bundle']['intro'][0] == reading
        stream = lesson['stream']
        response = client.get(stream['snapshot_url'])
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert snapshot['goals'][TARGET]['status'] == 'solved'
        handoff, = snapshot['handoffs']
        assert handoff['available'] is True
        assert handoff['answer']['kind'] == 'find_abstract_domain'
        assert handoff['answer']['set']['expression'] == 'Interval(-1, 3/2)'
        parts = [part for chunk in snapshot['interactions'] for part in chunk['parts']]
        assert len(parts) == 4
        method_cards = parts[:-1]
        assert [part['interaction']['field'] for part in method_cards] == [
            'known_object', 'input_condition', 'domain_answer',
        ]
        assert all(part['interaction']['type'] == 'choice' for part in method_cards)
        completed_cards = [step['highlight'] for step in snapshot['math_steps']
                           if step.get('display_unit') in {'abstract_align', 'abstract_condition', 'abstract_conclusion'}]
        assert len(completed_cards) == len(method_cards)
        for part, completed in zip(method_cards, completed_cards):
            board = part['stem_board']
            assert board['layout'] == completed['layout'] == 'derivation'
            assert board['connector'] == completed['connector'] == '⇒'
            assert board['caption'] == completed['caption']
            assert board['caption'] and board['caption'] != '对照板'
            assert 'lines' not in board
            assert len(board['items']) == len(completed['items']) == 2
            assert board['items'][0]['label'] == completed['items'][0]['label']
            assert board['items'][0]['math'] == completed['items'][0]['math']
            assert board['items'][0].get('note', '') == completed['items'][0].get('note', '')
            assert isinstance(board['items'][0]['math'], str) and board['items'][0]['math']
            assert board['items'][1]['math'] is None
            assert board['items'][1]['label'] == completed['items'][1]['label']
            assert isinstance(completed['items'][1]['math'], str) and completed['items'][1]['math']
            assert completed['items'][1]['math'] not in {'待求', '—'}
        # The condition step cites the target function; the final card's answer
        # slot stays blank until that step completes, rather than showing a
        # persistent board containing the result of the whole method.
        assert 'f(2' in str(method_cards[1]['stem_board'])
        assert 'f(2' in method_cards[2]['stem_board']['items'][1]['label']
        assert r'\frac{3}{2}' not in str(method_cards[2]['stem_board'])
        assert r'\frac{3}{2}' in completed_cards[2]['items'][1]['math']
        assert [row['kind'] for row in snapshot['selection_chunks']] == ['D3', 'D4']
        assert len(intro) + 1 + len(parts) == 7  # D1, D2, D3, three method cards, boundary check.
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        events = client.get(stream['events_url']).json()
        assert events['events'] and events['last_seq'] == snapshot['last_seq']
        # Refresh/restart must reuse the committed snapshot; no silent rerun.
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base + '/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
        assert client.get(base).json()['lesson']['stream'] == stream
