"""Real FP-T1 photo provenance and deterministic regression of both child goals."""

import re
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
import sympy as sp
from PIL import Image

from shuxueshuo_server.graph_lesson.function_parity import (
    inspect_parity_target,
    solve,
    verify,
)
from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.problem_understanding.notation_parser import parse
from shuxueshuo_server.search.lesson import present_lesson, stage_one_result
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    image_hashes,
    read,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/function-parity'
# Independently read/solved printed goals; these are never passed to the model.
GOLD = [('x/(x^2+1)', 'odd_only'), ('abs(x)+x^2', 'even_only')]
TARGETS = [f'/root/children/{i}/goals/0' for i in range(2)]


def checked_recording(attempt):
    recording = RECORDINGS / attempt / 'a01'
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
    assert [c['stage'] for c in ledger['calls']] == manifest['call_stages'] == ['extract', 'review']
    assert len(ledger['calls']) == manifest['historical_semantic_calls'] == 2
    assert sum(c['network_attempts'] for c in ledger['calls']) == manifest['historical_network_attempts'] == 2
    hashes = expected_image_hashes(read(recording / 'result.json'))
    assert hashes == [sha256((recording / 'question.png').read_bytes()).hexdigest()]
    for call in ledger['calls']:
        assert call['status'] == 'completed'
        request = read(recording / 'workflow' / call['directory'] / 'request.json')
        assert image_hashes(request) == hashes
        response_name = 'workflow/' + call['response_file']
        response = read(recording / response_name)
        assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][response_name]
        assert response['metadata']['provider'] == 'deepseek'
        assert response['raw_payload']['usage']['total_tokens'] > 0
    review = read(recording / 'workflow/latest-review.json')
    assert review['status'] == 'confirmed' and review['findings'] == []
    return recording


def replay_photo(attempt, output):
    recording = checked_recording(attempt)
    ledger = read(recording / 'workflow/ledger.json')
    historical = read(recording / 'result.json')
    provider = RecordedWorkflowProvider(recording, ledger, expected_image_hashes(historical))
    result = run_question_image(
        (recording / 'question.png').read_bytes(), output, provider,
        problem_id=ledger['identity']['binding']['problem_id'],
        original_png=(recording / 'original.png').read_bytes())
    assert provider.position == 2
    assert result['candidate'] == historical['candidate']
    assert result['source_reviewed'] and result['features_ok']
    return result


def test_original_ocr_and_initial_failure_are_retained():
    for attempt in ('initial', 'method-admission', 'interaction-timeout', 'fixed'):
        directory = RECORDINGS / attempt
        upload, = read(directory / 'uploads.json')
        assert sha256((directory / upload['file']).read_bytes()).hexdigest() == upload['sha256']
        assert sha256((ROOT / upload['source']).read_bytes()).hexdigest() == upload['source_sha256']
        for name, digest in upload['artifacts'].items():
            assert sha256((directory / name).read_bytes()).hexdigest() == digest
        assert set(upload['artifacts']) == {'page-01/ocr.json', 'page-01/segments.json'}
        response = read(directory / upload['file'])
        assert response['status_code'] == 200
        assert response['body']['orientation']['rotation_degrees'] == 0
        assert response['body']['mode'] == 'numbered' and len(response['body']['regions']) == 11
    initial = checked_recording('initial')
    assert read(initial / 'recording.json')['api_acceptance']['lesson_status'] == 'unsupported'
    assert not (initial / 'snapshot.json').exists()
    second = checked_recording('method-admission')
    assert read(second / 'recording.json')['api_acceptance']['lesson_status'] == 'failed'
    timed = checked_recording('interaction-timeout')
    assert read(timed / 'recording.json')['api_acceptance']['lesson_status'] == 'ready'
    assert any(card.get('reason') == 'compile_timeout' for card in read(timed / 'snapshot.json')['interactions'])
    directory = RECORDINGS / 'diagnostics'
    for name, digest in read(directory / 'manifest.json')['files'].items():
        assert sha256((directory / name).read_bytes()).hexdigest() == digest
    failed = read(directory / 'method-admission-stage-three.json')
    assert all(g['status'] == 'execution_error' for g in failed['goals'])


@pytest.mark.parametrize('attempt', ['initial', 'method-admission', 'fixed'])
def test_real_model_transcription_reaches_two_independent_parity_routes(attempt, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    result = replay_photo(attempt, tmp_path / 'recognition')
    value = result['candidate']
    assert len(value['root']['children']) == 2 and not value['root'].get('goals')
    for index, (expression, classification) in enumerate(GOLD):
        child = value['root']['children'][index]
        goal, = child['goals']
        assert goal['kind'] == 'determine_function_parity'
        assert parse(goal['expression']) == parse(expression)
        assert not child.get('facts')  # Handwritten 奇 / 偶 are not given properties.
        described = inspect_parity_target(value, TARGETS[index])
        assert described['structure_supported'], described['reason']
        solved = solve(described)
        assert solved['domain'] == sp.S.Reals and solved['classification'] == classification
        assert verify(described, solved)['status'] == 'verified'
    second = run_result(stage_one_result(result, 'fp-t1-a01'), tmp_path / 'stage-two',
                        admission='student_upload', provider=forbidden,
                        unsupported_root=tmp_path / 'unsupported')
    assert second['status'] == 'completed'
    assert [goal['target_ref'] for goal in second['goals']] == TARGETS
    assert all(goal['status'] == 'resolved' and goal['primary'] == 'type-function-parity'
               and goal['d1']['fragments'] and not goal['d1']['diagnostics'] for goal in second['goals'])
    presented = present_lesson(second, result['features'], value['original_text'], candidate=value)
    for index, goal in enumerate(presented['goals']):
        row, = goal['d1']['rows']
        assert TARGETS[index] + '/expression' in row['source_refs']
        assert all(not ref.startswith(f'/root/children/{1-index}/') for ref in row['source_refs'])
        assert goal['d1']['summary'].endswith('判断函数的奇偶性。')
        assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'


def test_two_photo_subquestions_publish_independently_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    # Regress the exact initially failing shape, including repeated definitions.
    result = replay_photo('initial', tmp_path / 'recognition')
    run_result(stage_one_result(result, 'fp-t1-a01'), tmp_path / 'stage-two',
               admission='student_upload', provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    output = tmp_path / 'stage-three'
    executed = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert executed['status'] == 'completed'
    assert [g['target_ref'] for g in executed['goals']] == TARGETS
    assert [g['answer']['classification'] for g in executed['goals']] == [v for _, v in GOLD]
    assert all(g['status'] == 'solved' and all(r['status'] == 'verified' for r in g['routes'])
               for g in executed['goals'])
    routes = list(output.glob('goals/*/routes/*.json'))
    assert len(routes) == 2
    for path in routes:
        assert read(path)['constraint_context']['processing']['status'] == 'complete'
    before = open_store(output).snapshot()['handoffs']
    assert len(before) == 2
    assert all(row['status'] == 'interactive' for row in open_store(output).snapshot()['interaction_states'])
    runner.resume_sample(output)
    assert open_store(output).snapshot()['handoffs'] == before


def test_live_lesson_snapshot_and_reopen_evidence():
    # These immutable API records come from the fresh live run, not this replay.
    recording = checked_recording('fixed')
    evidence = read(recording / 'recording.json')['api_acceptance']
    assert evidence['lesson_status'] == 'ready' and evidence['execution_status'] == 'completed'
    assert evidence['source_located'] and evidence['interactions_ready']
    assert evidence['same_stream_on_reopen'] and evidence['same_snapshot_on_reopen']
    snapshot = read(recording / 'snapshot.json')
    assert all(row['status'] == 'interactive' for row in snapshot['interaction_states'])
    assert [row['answer']['classification'] for row in snapshot['handoffs']] == [v for _, v in GOLD]


@pytest.mark.parametrize('domain,role,label', [
    ('[-2,1]', 'declared', '定义域'), ('[-1,1]', 'restriction', '题给输入范围'),
])
def test_parity_reading_card_keeps_the_supplied_domain(domain, role, label, tmp_path):
    from tests.solver.test_graph_function_parity_recognition import candidate, recognize

    value = candidate('x^2', input_domain=domain, domain_role=role)
    prepared, second = recognize(value, tmp_path)
    goal, = present_lesson(second, prepared['features'], value['original_text'], candidate=value)['goals']
    assert label in goal['d1']['summary']
    rendered_domain = re.findall(r'\$([^$]+)\$', goal['d1']['summary'])[1]
    assert parse(rendered_domain.replace(r'\left', '').replace(r'\right', '')) == parse(domain)
    row, = goal['d1']['rows']
    assert '/root/goals/0/input_domain' in row['source_refs']
