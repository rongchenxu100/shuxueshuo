"""The new real photo recording replays recognition and source-mode-preserving M8."""

import time
from hashlib import sha256
from pathlib import Path

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
RECORDING = Path(__file__).parent / 'fixtures/function-equality/domain-first-browser-recorded-20261028'


def test_domain_first_photo_replays_real_extract_review_and_preserves_all_four_options(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    manifest = read(RECORDING / 'recording.json')
    source_file = REPO / manifest['source']
    source = read(source_file)
    upload = REPO / manifest['upload_source']
    assert sha256(upload.read_bytes()).hexdigest() == manifest['upload_source_sha256']
    assert manifest['upload_source_sha256'] == source['files']['source-crop.png']['sha256']
    original = RECORDING / manifest['product_crop_source']['file']
    assert sha256(original.read_bytes()).hexdigest() == manifest['product_crop_source']['sha256']
    with Image.open(upload) as uploaded, Image.open(original) as cropped:
        assert manifest['product_crop']['box'] == [0, 0, 1, 1]
        assert list(uploaded.size) == list(cropped.size) == manifest['product_crop']['page_size']
        assert question_png(cropped) == (RECORDING / 'question.png').read_bytes()
    result = replay_recording(tmp_path / 'replay', RECORDING)
    root = result['candidate']['root']
    assert not any(root.get(key) for key in ('definitions', 'facts', 'children'))
    goal, = root['goals']
    assert (goal['mode'], goal['select_relation'], goal['selection_mode']) == ('groups', 'equal', 'unspecified')
    assert not goal['shared_functions']
    assert [option['label'] for option in goal['options']] == list('ABCD')
    assert all(len(option['functions']) == 2 for option in goal['options'])
    assert not any('domain' in item for option in goal['options'] for item in option['functions'])
    display = public_problem_text(result)
    assert '教材习题改编' not in display
    assert all(f'{label}. ' in display for label in 'ABCD')
    recorded = read(RECORDING / 'lesson-verification.json')
    assert (recorded['status'], recorded['goal_status']) == ('completed', 'solved')
    assert recorded['answer']['correct_labels'] == ['C']
    assert recorded['answer']['selection_mode'] == 'unspecified'


def test_domain_first_photo_api_solves_four_options_without_guessing_original_choice_mode(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    root = tmp_path / 'private-search'
    _, directory = seed_photo_recording(root, RECORDING)
    base = f'/api/search/problems/{directory.name}'
    with authenticated_client(root) as client:
        first = client.get(base)
        assert first.status_code == 200, first.text
        goal, = first.json()['lesson']['goals']
        assert goal['primary'] == 'type-function-equality', goal
        assert goal['walk'] and goal['walk']['bundle']['intro']
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
        stream = lesson['stream']
        response = client.get(stream['snapshot_url'])
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert snapshot['goals']['/root/goals/0']['status'] == 'solved'
        handoff, = snapshot['handoffs']
        assert handoff['available'] is True
        original = handoff['original_choice']
        assert original['kind'] == 'multiple_choice'
        assert original['selection_mode'] == 'unspecified'
        assert original['correct_labels'] == ['C']
        assert [row['verdict'] for row in original['option_verdicts']] == ['different', 'different', 'equal', 'different']
        parts = [part for chunk in snapshot['interactions'] for part in chunk['parts']]
        verdicts = [part for part in parts if part.get('option_context', {}).get('phase') == 'verdict']
        assert [part['option_context']['label'] for part in verdicts] == list('ABCD')
        assert all(part['interaction']['type'] == 'choice' and not part.get('case_path') for part in verdicts)
        correspondences = [part for part in parts if part['interaction'].get('field') == 'correspondence']
        assert [part['option_context']['label'] for part in correspondences] == ['A', 'C']
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        events = client.get(stream['events_url']).json()
        assert events['events'] and events['last_seq'] == snapshot['last_seq']
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base + '/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
        assert client.get(base).json()['lesson']['stream'] == stream
