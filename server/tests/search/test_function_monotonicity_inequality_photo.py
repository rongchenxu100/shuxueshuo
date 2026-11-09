"""Fresh T3 photo evidence, retained failures and zero-network regression."""
import secrets
import shutil
import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
import sympy as sp
from PIL import Image

from shuxueshuo_server.graph_lesson.monotonicity_inequality_math import solve, verify
from shuxueshuo_server.graph_lesson.piecewise_inequality import (
    independent_verify,
    solve_two_input_cases,
)
from shuxueshuo_server.graph_lesson.stage_three.context import build_context
from shuxueshuo_server.graph_lesson.stage_three.trajectory import decode_value
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.search import dev_api
from shuxueshuo_server.search.identity import build_identity
from shuxueshuo_server.search.lesson import run_stage_two, stage_one_result
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
)
from tests.search.support import authenticated_client, session_for

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/function-monotonicity-inequality'
# Independently checked against printed questions, never supplied to the model.
GOLD = {
    'b01': ('f(2*x)<f(x+1)', sp.Interval.open(0, 1)),
    'b02': ('f(x-1)>f(1-3*x)', sp.Interval.Lopen(sp.Rational(1, 2), sp.Rational(2, 3))),
    'b03': ('f(x^2+x+3)>f(3*x^2-3)', sp.Interval.open(sp.Rational(-3, 2), 2)),
    'b04': ('f(m^2+2)>f(2*m+5)', sp.Interval.open(-1, 3)),
    'b05': ('f(2*x-1)>f(1/3)', sp.Interval.Ropen(sp.Rational(1, 2), sp.Rational(2, 3))),
    'b09': ('f(x^2-2*x)<f(3*x-4)', sp.Interval.open(1, 4)),
    'b12': ('f(1-x^2)>f(2*x)', sp.Interval.open(-1, sp.sqrt(2)-1)),
    'b13': ('f(2*x-1)<f(1/3)', sp.Interval.Ropen(sp.Rational(1, 2), sp.Rational(2, 3))),
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
    return recording


def replay_photo(key, output):
    recording = checked_recording(key)
    ledger = read(recording / 'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']] == read(recording / 'recording.json')['call_stages']
    png = (recording / 'question.png').read_bytes()
    provider = RecordedWorkflowProvider(recording, ledger, sha256(png).hexdigest())
    result = run_question_image(png, output, provider,
                                problem_id=ledger['identity']['binding']['problem_id'],
                                original_png=(recording / 'original.png').read_bytes())
    assert provider.position == len(ledger['calls'])
    assert result['candidate'] == read(recording / 'result.json')['candidate']
    return result


@pytest.mark.parametrize('key', GOLD)
def test_live_photo_evidence_replays_into_correct_original_goal(key, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_photo(key, tmp_path / 'recognition')
    assert result['status'] == 'reviewed_candidate' and result['features_ok']
    candidate = result['candidate']
    relation, expected = GOLD[key]
    assert parse(relation) in [parse(fact) for fact in candidate['root']['facts']]
    second = run_result(stage_one_result(result, key), tmp_path / 'stage-two',
                        admission='student_upload', unsupported_root=tmp_path / 'unsupported')
    assert second['status'] == 'completed'
    assert all(g['status'] == 'resolved' and not g['d1']['diagnostics'] for g in second['goals'])
    target = '/root/goals/1' if key == 'b09' else '/root/goals/0'
    context = build_context(candidate, target)
    if key == 'b12':
        assert second['goals'][-1]['primary'] == 'type-piecewise-function'
        actual = solve_two_input_cases(context['piecewise_inequality'])['outputs']['feasible_set']
        assert independent_verify(candidate, target, context, actual)['status'] == 'verified'
    else:
        assert second['goals'][-1]['primary'] == 'type-monotonicity-inequality'
        description = context['mono_inequality_goal']
        model = solve(description)
        assert verify(description, model)
        actual = model['feasible_set']
    assert actual == expected
    # These files came from real API calls, not the above offline replay.
    evidence = read(RECORDINGS / key / 'recording.json')['api_acceptance']
    assert evidence['lesson_status'] == 'ready' and evidence['execution_status'] == 'completed'
    assert evidence['same_stream_on_reopen'] and evidence['same_snapshot_on_reopen']
    snapshot = read(RECORDINGS / key / 'snapshot.json')
    saved = snapshot['goals'][target]['feasible_set']
    if 'exact' in saved:
        assert decode_value(saved['exact']) == expected
    else:
        assert saved['expression'] == str(expected)
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    if key == 'b09':
        assert second['goals'][0]['primary'] == 'type-function-evaluation'
        assert len(snapshot['goals']) == 2
        assert snapshot['goals']['/root/goals/0']['answer']['value']['expression'] == '15'


def test_original_local_monotonicity_does_not_publish_a_complete_answer(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_photo('b06', tmp_path / 'recognition')
    assert result['status'] == 'reviewed_candidate'
    mono = result['candidate']['root']['goals'][0]['function_monotonicity']
    assert mono['domain'] == '(-1,1)' and 'function_domain' not in mono
    context = build_context(result['candidate'], '/root/goals/0')
    assert context['mono_inequality_goal']['reason'] == 'mono_ineq.incomplete_domain_coverage'
    evidence = read(RECORDINGS / 'b06/recording.json')['api_acceptance']
    assert evidence['lesson_status'] == 'unsupported'
    assert not (RECORDINGS / 'b06/snapshot.json').exists()


@pytest.mark.parametrize('key', ['b03-initial', 'b06-initial', 'b09-initial', 'b12-initial'])
def test_first_live_failures_remain_unchanged_evidence(key):
    recording = checked_recording(key)
    assert read(recording / 'recording.json')['api_acceptance']['lesson_status'] != 'ready'


@pytest.mark.parametrize('key', ['b05', 'b09'])
def test_corrected_source_cards_complete_and_reopen_through_owned_api(key, tmp_path, monkeypatch):
    """Revalidate the exact live transcription that exposed the last source-card gap."""
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    root = tmp_path / 'search'
    session = session_for(root)
    result = replay_photo(key, root / 'replay')
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    session.search_id = search_id
    directory = root / 'submissions' / search_id
    directory.mkdir(parents=True)
    save(directory / dev_api.RESULT_FILE, result)
    recording = RECORDINGS / key
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
        target = '/root/goals/1' if key == 'b09' else '/root/goals/0'
        assert decode_value(snapshot['goals'][target]['feasible_set']['exact']) == GOLD[key][1]
        if key == 'b09':
            assert snapshot['goals']['/root/goals/0']['answer']['value']['expression'] == '15'
        assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
        monkeypatch.setattr('shuxueshuo_server.search.stage_three.runner.run_sample', forbidden)
        assert client.post(base + '/lesson/start').json()['stream'] == stream
        assert client.get(stream['snapshot_url']).json() == snapshot
        save(tmp_path / 'api-revalidation.json', {
            'source_recording': key, 'recognition_result_sha256': sha256((recording / 'result.json').read_bytes()).hexdigest(),
            'mode': 'recorded_recognition_current_lesson_api_no_new_model_calls',
            'lesson': lesson, 'snapshot': snapshot, 'reopened_same_stream_and_snapshot': True,
        })
