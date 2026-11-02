"""Original B05-v2 photograph, genuine model-call replay and the owned photo API."""

import time
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw

from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.question_image import question_png
from tests.search.function_equality_recording import (
    forbidden,
    read,
    replay_recording,
    seed_photo_recording,
)
from tests.search.support import authenticated_client

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / 'internal/senior-high/source-images/function-formula-a0-20261101'
RECORDING = Path(__file__).parent / 'fixtures/function-formula/b05-v2-recorded-20261101'
TARGET = '/root/goals/0'


def test_original_pixels_and_question_only_polygon_are_bound_to_real_model_calls():
    source, recording = read(SOURCE/'manifest.json'), read(RECORDING/'recording.json')
    page = REPO/source['page']['file']
    assert sha256(page.read_bytes()).hexdigest() == source['page']['sha256']
    crop = source['crop']
    with Image.open(page) as original, Image.open(SOURCE/crop['file']) as saved:
        box = crop['xyxy']
        region = original.convert('RGB').crop(box)
        mask = Image.new('L', region.size, 0)
        ImageDraw.Draw(mask).polygon([(x-box[0], y-box[1]) for x, y in crop['source_polygon']], fill=255)
        expected = Image.composite(region, Image.new('RGB', region.size, 'white'), mask)
        assert saved.convert('RGB').tobytes() == expected.tobytes()
        assert question_png(saved) == (RECORDING/'question.png').read_bytes()
    assert recording['upload_source_sha256'] == crop['sha256']
    assert recording['historical_semantic_calls'] == 2
    assert recording['call_stages'] == ['extract', 'review']
    assert recording['usage'] == 'development_regression_not_unseen_holdout'


def test_recorded_photo_preserves_unknown_function_and_radical_grouping(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_recording(tmp_path/'replay', RECORDING)
    root = result['candidate']['root']
    assert not root['definitions'] and not root['facts']
    assert root['goals'] == [{'kind': 'find_function_formula', 'function': 'f', 'variable': 'x',
                              'relation': 'f(sqrt(x)+1)=2*x+1'}]
    feature = next(row['value'] for row in result['features'] if row['feature_id'] == 'function_formula')
    assert feature['structure_supported'] and 'expression' not in feature


def test_photo_api_completes_and_recovers_four_formula_cards(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    root = tmp_path/'search'
    _, directory = seed_photo_recording(root, RECORDING)
    base = f'/api/search/problems/{directory.name}'
    with authenticated_client(root) as client:
        response = client.get(base)
        assert response.status_code == 200, response.text
        goal, = response.json()['lesson']['goals']
        assert goal['primary'] == 'type-function-formula'
        assert not goal['d1'].get('diagnostics')
        assert [step['id'] for step in goal['walk']['bundle']['intro']] == ['D1', 'D2']
        assert client.post(base+'/lesson/start').status_code == 200
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            lesson = client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}:
                break
            time.sleep(0.05)
        assert lesson['execution_status'] == 'completed', lesson
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url']).json()
        answer = snapshot['goals'][TARGET]['answer']
        assert answer['kind'] == 'find_function_formula'
        assert answer['status'] == 'determined_on_domain'
        assert answer['expression']['expression'] == '2*t**2 - 4*t + 3'
        assert answer['source_domain']['expression'] == 'Interval(0, oo)'
        assert answer['determined_domain']['expression'] == 'Interval(1, oo)'
        assert answer['declared_domain'] is None
        parts = [part for chunk in snapshot['interactions'] for part in chunk['parts']]
        assert len(parts) == len(snapshot['math_steps']) == 4
        assert all(part['stem_board']['items'][1]['math'] is None for part in parts)
        assert all(part['completion_board']['items'][1]['math'] for part in parts)
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert snapshot['handoffs'][0]['available']
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base+'/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
