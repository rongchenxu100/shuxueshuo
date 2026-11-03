"""G1: genuine B09 photo replay, source binding and the owned lesson API."""
import shutil
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.search import dev_api, figures, reviewed_figures
from shuxueshuo_server.search.identity import IdentityUnavailable, build_identity
from shuxueshuo_server.search.stage_one import (
    run_legacy_question_image as run_question_image,
)
from shuxueshuo_server.search.storage import SearchError
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
    replay_recording,
    seed_photo_recording,
)
from tests.search.support import authenticated_client

RECORDING = Path(__file__).parent/'fixtures/function-graph/b09-recorded-20261102'
TARGET = '/root/goals/0'


def test_actual_missing_option_photo_stops_before_lesson_admission(tmp_path):
    recording = RECORDING.parent/'b09-missing-d-recorded-20261102'
    manifest = read(recording/'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((recording/name).read_bytes()).hexdigest() == digest
    ledger = read(recording/'workflow/ledger.json')
    png = (recording/'question.png').read_bytes()
    provider = RecordedWorkflowProvider(recording, ledger, sha256(png).hexdigest())
    result = run_question_image(png, tmp_path/'missing', provider,
                                problem_id=ledger['identity']['binding']['problem_id'])
    assert provider.position == len(ledger['calls']) == 1
    assert result['status'] == 'needs_confirmation' and not result['features_ok']
    assert result.get('figure_binding') is None
    assert result['confirmation_diagnostics'][0]['code'] == 'occluded'
    with pytest.raises(IdentityUnavailable): build_identity(result)


def test_actual_page_with_explanation_uses_only_original_four_options(tmp_path):
    recording = RECORDING.parent/'b09-with-analysis-recorded-20261102'
    result = replay_recording(tmp_path/'analysis', recording)
    public = result['public_candidate']['public_content']
    assert len(public['figure_regions']) == 4
    # In this actual page, original choices occupy the upper 42%; the explanation is below.
    assert all(row['box'][3] <= .42 for row in public['figure_regions'])
    goal = result['candidate']['root']['goals'][0]
    assert [o['label'] for o in goal['options']] == list('ABCD')
    assert [(o['facts']['vertex']['x'], o['facts']['vertex']['y']) for o in goal['options']] == [
        ('1','1'), ('-1','1'), ('-1','-1'), ('1','-1')]


def test_reviewed_photograph_binds_every_original_option_and_rejects_stale_sources(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_recording(tmp_path/'replay', RECORDING)
    assert result['figure_binding']['candidate_revision'] == result['reviewed_candidate_revision']
    assert [o['label'] for o in result['figure_binding']['option_figures']] == list('ABCD')
    assert len({o['sha256'] for o in result['figure_binding']['option_figures']}) == 4
    identity = build_identity(result)
    changed = deepcopy(result)
    changed['figure_binding']['option_figures'][1]['sha256'] = '0'*64
    assert build_identity(changed) != identity  # same words, different original picture
    for change in ('missing', 'revision', 'label'):
        bad = deepcopy(result)
        if change == 'missing': del bad['figure_binding']
        elif change == 'revision': bad['figure_binding']['candidate_revision'] = '0'*64
        else: bad['figure_binding']['option_figures'][0]['label'] = 'B'
        with pytest.raises(IdentityUnavailable): build_identity(bad)
    shutil.copyfile(RECORDING/'question.png', tmp_path/'replay/original.png')
    with pytest.raises(SearchError, match='figure.source_changed'): figures.manifest_for(tmp_path/'replay')


def test_incomplete_options_and_unreviewed_pages_do_not_install_figures(tmp_path):
    result = read(RECORDING/'result.json')
    for change in ('unreviewed', 'missing_page'):
        bad = deepcopy(result)
        if change == 'unreviewed': bad['source_reviewed'] = False
        else:
            bad['public_candidate']['public_content']['completeness'] = 'incomplete'
            bad['reviewed_candidate_revision'] = revision(bad['public_candidate'])
        assert reviewed_figures.install(tmp_path, bad) is None
        assert not (tmp_path/figures.MANIFEST).exists()


def test_photo_api_completes_graph_cards_with_original_options_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    root = tmp_path/'search'
    _, directory = seed_photo_recording(root, RECORDING)
    base = f'/api/search/problems/{directory.name}'
    with authenticated_client(root) as client:
        response = client.get(base)
        assert response.status_code == 200, response.text
        display = response.json()['figures']
        goal, = response.json()['lesson']['goals']
        assert goal['primary'] == 'type-function-graph'
        assert not goal['d1'].get('diagnostics')
        for image in display['figures']:
            fetched = client.get(image['image_url'])
            assert fetched.status_code == 200 and fetched.headers['content-type'] == 'image/png'
        assert client.post(base+'/lesson/start').status_code == 200
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            lesson = client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}: break
            time.sleep(.05)
        assert lesson['execution_status'] == 'completed', lesson
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url']).json()
        answer = snapshot['goals'][TARGET]['answer']
        assert answer['kind'] == 'select_function_graph' and answer['correct_labels'] == ['A']
        assert answer['correct_option_id'] == 'option-a'
        parts = [part for chunk in snapshot['interactions'] for part in chunk['parts']]
        assert len(parts) == 4 and len(snapshot['math_steps']) == 3
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert parts[-1]['figure_choices'] == ['option-a','option-b','option-c','option-d']
        assert all(p['stem_board']['items'][1]['math'] is None for p in parts)
        assert snapshot['handoffs'][0]['available']
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base+'/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
