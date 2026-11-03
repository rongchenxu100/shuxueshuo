"""The actual page-bend failure must retain its photo and never start a lesson."""
import secrets
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from shuxueshuo_server.search.identity import IdentityUnavailable, build_identity
from shuxueshuo_server.search.stage_one import (
    run_legacy_question_image as run_question_image,
)
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
)
from tests.search.support import authenticated_client, session_for

RECORDING = Path(__file__).parent/'fixtures/function-graph/b09-v2-occluded-recorded-20261102'


def test_occluded_original_photo_keeps_diagnostic_and_cannot_generate_course(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
    manifest = read(RECORDING/'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((RECORDING/name).read_bytes()).hexdigest() == digest
    ledger = read(RECORDING/'workflow/ledger.json')
    png = (RECORDING/'question.png').read_bytes()
    root = tmp_path/'search'
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    directory = root/'submissions'/search_id
    directory.mkdir(parents=True)
    shutil.copyfile(RECORDING/'original.png', directory/'original.png')
    shutil.copyfile(RECORDING/'crop.json', directory/'crop.json')
    provider = RecordedWorkflowProvider(RECORDING, ledger, sha256(png).hexdigest())
    result = run_question_image(png, directory, provider,
                                problem_id=ledger['identity']['binding']['problem_id'])
    assert provider.position == len(ledger['calls']) == 1
    assert result['status'] == 'needs_confirmation' and not result['source_reviewed']
    assert not result['features_ok'] and not result.get('figure_binding')
    assert result['public_candidate'] == read(RECORDING/'workflow/candidate.json')
    assert result['confirmation_diagnostics'][0]['code'] == 'occluded'
    with pytest.raises(IdentityUnavailable):
        build_identity(result)

    session = session_for(root)
    page = root/'pages'/page_id
    page.mkdir(parents=True)
    shutil.copyfile(RECORDING/'original.png', page/'page.png')
    session.repository.register_page(session.user, page_id, {})
    session.repository.create_submission(session.user, search_id, page_id, [0, 0, 1, 1])
    session.repository.set_state(search_id, recognition_state='needs_confirmation', error_code='occluded')
    base = f'/api/search/problems/{search_id}'
    with authenticated_client(root) as client:
        response = client.get(base)
        assert response.status_code == 200, response.text
        problem = response.json()
        assert problem['status'] == 'needs_confirmation' and problem['outcome'] == 'unclear'
        assert not problem.get('lesson') and not problem['problem_id']
        assert any('D' in row['message'] and row['kind'] == 'occluded' for row in problem['findings'])
        source, = problem['figures']['figures']
        assert source['role'] == 'source'
        original = client.get(source['image_url'])
        assert original.status_code == 200
        assert original.content == (RECORDING/'original.png').read_bytes()
        assert client.post(base+'/lesson/start').status_code == 409
        assert not list(directory.glob('stage-two-*'))
