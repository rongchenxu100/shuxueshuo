"""G4: retain real photo uncertainty; separately test authored figure binding."""
import json
import shutil
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from shuxueshuo_server.problem_understanding.identity import revision
from shuxueshuo_server.problem_understanding.workflow_diagnostics import (
    uncertainty_diagnostics,
)
from shuxueshuo_server.search import dev_api, figures, reviewed_figures
from shuxueshuo_server.search.identity import (
    EXTRACTION_CONTRACT,
    IdentityUnavailable,
    build_identity,
    mathematical_candidate,
    public_structure_errors,
)
from shuxueshuo_server.search.stage_one import (
    run_legacy_question_image as run_question_image,
)
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
    seed_photo_recording,
)
from tests.search.support import authenticated_client

ROOT = Path(__file__).resolve().parents[3]
RECORDING = Path(__file__).parent/'fixtures/function-graph/b09-v3-uncertain-recorded-20261102'
TARGET = '/root/goals/0'


def test_actual_reviewed_schematic_photo_reaches_owned_lesson_and_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr(dev_api, 'run_question_image', forbidden)
    recording = RECORDING.parent/'b09-v3-reviewed-recorded-20261102'
    root = tmp_path/'search'
    _, directory = seed_photo_recording(root, recording)
    result = read(directory/'result.json')
    assert result['source_reviewed'] and len(result['sent_image_sha256']) == 2
    assert result['figure_binding']['statement_figures']
    assert not result.get('detail_attempt')  # This live run never used the new detail fallback.
    goal = result['candidate']['root']['goals'][0]
    assert goal['source_graph']['facts']['x_intercept'] == {'x': '0', 'evidence': 'origin'}
    assert [(o['label'], o['facts']['x_intercept']['x']) for o in goal['options']] == [
        ('A', '2'), ('B', '-2'), ('C', '2'), ('D', '-2')]
    base = f'/api/search/problems/{directory.name}'
    with authenticated_client(root) as client:
        response = client.get(base)
        assert response.status_code == 200, response.text
        display = response.json()['figures']
        assert len([f for f in display['figures'] if f['role'] == 'statement']) == 1
        for figure in display['figures']:
            fetched = client.get(figure['image_url'])
            assert fetched.status_code == 200 and fetched.headers['content-type'] == 'image/png'
        assert client.post(base+'/lesson/start').status_code == 200
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            lesson = client.get(base).json()['lesson']
            if lesson.get('execution_status') in {'completed', 'partial', 'failed', 'error', 'input_error'}:
                break
            time.sleep(.05)
        assert lesson['execution_status'] == 'completed', lesson
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url']).json()
        answer = snapshot['goals'][TARGET]['answer']
        assert answer['kind'] == 'select_function_graph' and answer['correct_labels'] == ['C']
        assert answer['correct_option_id'] == 'option-c'
        parts = [p for chunk in snapshot['interactions'] for p in chunk['parts']]
        assert all(p.get('show_source_graph') for p in parts)
        assert all(not p.get('graph') and not p.get('completion_graph') for p in parts)
        assert parts[-1]['figure_choices'] == ['option-a', 'option-b', 'option-c', 'option-d']
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        assert snapshot['handoffs'][0]['available']
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base+'/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot


def test_actual_dual_view_failure_keeps_all_uncertainties_and_both_image_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    recording = RECORDING.parent/'b09-v3-original-view-recorded-20261102'
    manifest = read(recording/'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((recording/name).read_bytes()).hexdigest() == digest
    ledger = read(recording/'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']] == ['extract']
    png, original = [(recording/name).read_bytes() for name in ('question.png', 'original.png')]
    hashes = [sha256(content).hexdigest() for content in (png, original)]
    assert ledger['identity']['binding']['images'] == hashes
    provider = RecordedWorkflowProvider(recording, ledger, hashes)
    result = run_question_image(png, tmp_path, provider,
        problem_id=ledger['identity']['binding']['problem_id'], original_png=original)
    historical = read(recording/'result.json')
    assert result['image_inputs'] == historical['image_inputs']
    assert result['sent_image_sha256'] == hashes
    assert result['public_candidate'] == historical['public_candidate']
    assert result['confirmation_diagnostics'] == historical['confirmation_diagnostics']
    assert len(result['confirmation_diagnostics']) == 5 and provider.position == 1
    assert result['status'] == 'needs_confirmation' and not result['source_reviewed']
    assert not result['features_ok'] and not result.get('figure_binding')
    with pytest.raises(IdentityUnavailable): build_identity(result)


def test_actual_uncertain_intercept_stops_before_historic_repair_attempts(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    manifest = read(RECORDING/'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((RECORDING/name).read_bytes()).hexdigest() == digest
    ledger = read(RECORDING/'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']] == ['extract', 'repair', 'repair']
    png = (RECORDING/'question.png').read_bytes()
    provider = RecordedWorkflowProvider(RECORDING, ledger, sha256(png).hexdigest())
    result = run_question_image(png, tmp_path/'replay', provider,
                                problem_id=ledger['identity']['binding']['problem_id'])
    # Keep all historic calls immutable, but the fixed workflow must never ask
    # the model to repair away a source-image ambiguity from the first response.
    assert provider.position == 1
    first = json.loads(read(RECORDING/'workflow'/ledger['calls'][0]['response_file'])['text'])
    assert result['public_candidate'] == first
    assert result['status'] == 'needs_confirmation' and not result['source_reviewed']
    assert not result['features_ok'] and not result.get('figure_binding')
    diagnostic, = result['confirmation_diagnostics']
    assert diagnostic['code'] == 'ambiguous'
    assert diagnostic['path'] == TARGET+'/source_graph/uncertainties/0'
    assert '原点' in diagnostic['message']
    with pytest.raises(IdentityUnavailable): build_identity(result)
    # The same protection applies to option facts and nested subquestions.
    nested = {'root': {'children': [{'goals': [{**first['root']['goals'][0],
        'source_graph': {}, 'options': [{'label': 'D', 'uncertainties': ['交点被遮挡']}]}]}]}}
    finding, = uncertainty_diagnostics(nested)
    assert finding['path'] == '/root/children/0/goals/0/options/0/uncertainties/0'
    assert finding['message'] == '选项 D：交点被遮挡'
    # Structurally malformed fields still belong to schema diagnostics.
    assert not uncertainty_diagnostics({'root': {'goals': None}})
    assert not uncertainty_diagnostics({'root': {'goals': [{'kind': 'select_function_graph',
        'source_graph': {'uncertainties': None}, 'options': None}]}})


def test_authored_source_graph_is_required_and_part_of_picture_identity(tmp_path):
    # An authored contract unit fixture, explicitly NOT a successful photo replay.
    authored = read(ROOT/'internal/senior-high/authored-courses/function-graph-g4-20261102/b09-v3.json')['candidate']
    display = read(ROOT/'site/assets/question-figures/fr-t2-b09-v3/question-figures.json')
    goal = authored['root']['goals'][0]
    public = {'completeness': 'complete', 'privacy': 'separated', 'figure': 'represented',
        'scopes': [{'scope_ref': '/root', 'statement': authored['original_text'], 'choices': [{
            'target_ref': TARGET, 'status': 'complete', 'selection_mode': goal['selection_mode'],
            'options': [{'label': o['label'], 'text': '见原图'} for o in goal['options']]}]}],
        'figure_regions': [{k: r[k] for k in ('target_ref', 'option_id', 'label', 'box')}
                           for r in display['figures'] if r['role'] == 'option'],
        'statement_figure_regions': [{k: r[k] for k in ('target_ref', 'box')}
                                     for r in display['figures'] if r['role'] == 'statement']}
    candidate = {**authored, 'public_content': public}
    shutil.copyfile(RECORDING/'original.png', tmp_path/'original.png')
    result = {'status': 'reviewed_candidate', 'source_reviewed': True,
        'output_contract': EXTRACTION_CONTRACT, 'public_candidate': candidate,
        'candidate': mathematical_candidate(candidate), 'reviewed_candidate_revision': revision(candidate),
        'question_sha256': sha256((RECORDING/'question.png').read_bytes()).hexdigest()}
    result['sent_image_sha256'] = [result['question_sha256']]
    assert not public_structure_errors(candidate)
    result['figure_binding'] = reviewed_figures.install(tmp_path, result)
    binding = result['figure_binding']
    assert binding and len(binding['statement_figures']) == 1
    original = next(r for r in figures.present(tmp_path, 'abcdef012345')['figures'] if r['role'] == 'statement')
    assert sha256(figures.image_bytes(tmp_path, original['id'])).hexdigest() == binding['statement_figures'][0]['sha256']
    identity = build_identity(result)
    changed = deepcopy(result)
    changed['figure_binding']['statement_figures'][0]['sha256'] = '0'*64
    assert build_identity(changed) != identity  # same words/options, different given graph
    del changed['figure_binding']['statement_figures']
    with pytest.raises(IdentityUnavailable, match='unbound_source_graph'): build_identity(changed)
    bad = deepcopy(candidate)
    del bad['public_content']['statement_figure_regions']
    assert any(p.endswith('statement_figure_regions') for p, _ in public_structure_errors(bad))
