"""Retained real A17 calls and their deterministic extraction/course replay."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from shuxueshuo_server.graph_lesson.stage_three import runner
from shuxueshuo_server.graph_lesson.stage_three.preview import open_store
from shuxueshuo_server.graph_lesson.stage_two.runner import run_result
from shuxueshuo_server.search.lesson import present_lesson, stage_one_result
from shuxueshuo_server.search.question_image import expected_image_hashes
from shuxueshuo_server.search.stage_one import run_question_image
from tests.search.function_equality_recording import (
    RecordedWorkflowProvider,
    forbidden,
    read,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/function-parity-parameter'


@pytest.mark.parametrize('attempt', ['initial', 'fixed', 'r3-acceptance'])
def test_original_photo_and_real_calls_are_immutable(attempt):
    directory = RECORDINGS / attempt
    recording = directory / 'a17'
    manifest = read(recording / 'recording.json')
    for name, digest in manifest['files'].items():
        assert sha256((recording / name).read_bytes()).hexdigest() == digest
    source = read(recording / 'source.json')
    assert sha256((ROOT / source['source']).read_bytes()).hexdigest() == source['source_sha256']
    raw = BytesIO()
    with Image.open(ROOT / source['source']) as image:
        image.crop(source['crop_pixels']).save(raw, format='PNG')
    assert raw.getvalue() == (recording / 'original.png').read_bytes()
    upload, = read(directory / 'uploads.json')
    for name, digest in {upload['file']: upload['sha256'], **upload['artifacts']}.items():
        assert sha256((directory / name).read_bytes()).hexdigest() == digest
    assert set(upload['artifacts']) == {'page-02/ocr.json', 'page-02/segments.json'}
    ledger = read(recording / 'workflow/ledger.json')
    assert [c['stage'] for c in ledger['calls']] == ['extract', 'review']
    assert manifest['historical_semantic_calls'] == manifest['historical_network_attempts'] == 2
    for call in ledger['calls']:
        name = 'workflow/' + call['response_file']
        response = read(recording / name)
        assert sha256(response['text'].encode()).hexdigest() == manifest['response_text_sha256'][name]
        assert response['metadata']['provider'] == 'deepseek'
        assert response['raw_payload']['usage']['total_tokens'] > 0
    accepted = manifest['api_acceptance']
    if attempt != 'initial':
        assert accepted['source_located'] and accepted['interactions_ready']
        assert accepted['execution_status'] == 'completed'
        assert accepted['same_stream_on_reopen'] and accepted['same_snapshot_on_reopen']
    else:
        assert not accepted['source_located'] and not accepted['interactions_ready']


@pytest.mark.parametrize('attempt', ['fixed', 'r3-acceptance'])
def test_live_model_result_replays_through_verified_course_and_resume(attempt, tmp_path, monkeypatch):
    monkeypatch.setattr('shuxueshuo_server.problem_understanding.batch_smoke.live_provider_factory', forbidden)
    recording = RECORDINGS / attempt / 'a17'
    historical = read(recording / 'result.json')
    ledger = read(recording / 'workflow/ledger.json')
    provider = RecordedWorkflowProvider(recording, ledger, expected_image_hashes(historical))
    result = run_question_image((recording / 'question.png').read_bytes(), tmp_path / 'recognition', provider,
        problem_id=ledger['identity']['binding']['problem_id'], original_png=(recording / 'original.png').read_bytes())
    assert provider.position == 2
    assert result['candidate'] == historical['candidate']
    assert result['source_reviewed'] and result['features_ok']
    root = result['candidate']['root']
    assert root['definitions'] == ['f(x)=x^2+(2-m)*x+m^2+12']
    assert root['facts'] == ['parity(f,even)']  # The handwritten 2 is not a given.
    assert root['goals'] == [{'kind': 'find_value', 'expression': 'm'}]
    second = run_result(stage_one_result(result, 'fp-t2-a17'), tmp_path / 'stage-two',
                        admission='student_upload', provider=forbidden, unsupported_root=tmp_path / 'unsupported')
    shown = present_lesson(second, result['features'], result['candidate']['original_text'], candidate=result['candidate'])
    goal, = shown['goals']
    assert goal['primary'] == 'type-parity-parameter'
    assert goal['d1']['rows'] and '偶函数' in goal['d1']['summary']
    assert goal['walk']['bundle']['intro'][0]['id'] == 'D1'
    output = tmp_path / 'stage-three'
    executed = runner.run_sample(tmp_path / 'stage-two/stage-two-result.json', output)
    assert executed['status'] == 'completed'
    answer = executed['goals'][0]['answer']
    assert answer['kind'] == 'find_value' and answer['result_type'] == 'parameter_value'
    assert answer['parameter'] == 'm' and answer['value']['expression'] == '2'
    before = open_store(output).snapshot()
    assert len(before['handoffs']) == 1
    assert all(r['status'] == 'interactive' for r in before['interaction_states'])
    runner.resume_sample(output)
    assert open_store(output).snapshot()['handoffs'] == before['handoffs']
