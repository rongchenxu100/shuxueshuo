"""Transport, image-dependent live probe, and the shared five-case acceptance gate."""
import base64
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from shuxueshuo_server.solver.extraction.multimodal_provider import (
    DeepSeekMultimodalExtractionProvider, MultimodalProviderError,
    MultimodalExtractionPrompt, MultimodalProviderImage,
    build_multimodal_provider_request, create_vision_provider, vision_effective_config,
)
from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
from _problem_extraction_f3_support import make_f3_fixture

CASES = tuple('tj-2026-' + district + '-25' for district in
              ('heping-yimo', 'heping-ermo', 'hexi-yimo', 'nankai-yimo', 'xiqing-yimo'))


def response(text='{"value":7}', finish='stop', usage=None):
    return SimpleNamespace(model='deepseek-flash', usage=usage,
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, reasoning_content='not business JSON'), finish_reason=finish)])


def client_factory(outputs, calls, init):
    def factory(**options):
        init.update(options)
        def create(**options):
            calls.append(options)
            item = outputs.pop(0)
            if isinstance(item, Exception): raise item
            return item
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return factory


def request_fixture(tmp_path):
    _, _, _, store, pack = make_f3_fixture(tmp_path)
    return store, build_multimodal_provider_request(pack, artifact_reader=store,
        expected_problem_id='synthetic-f2', response_format_mode='json_object')


@pytest.mark.parametrize('contract', ['problem-domain/v1', 'problem-repair/v1', 'problem-source-review/v1'])
def test_actual_image_transport_and_audit_agree(tmp_path, contract):
    store, req = request_fixture(tmp_path)
    if contract != 'problem-domain/v1':
        from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
        from test_problem_domain_retry import _domain_payload
        draft = ProblemDraft.create(_domain_payload())
        if contract == 'problem-repair/v1':
            req = build_multimodal_provider_request(req.evidence_pack, artifact_reader=store,
                expected_problem_id='synthetic-f2', current_draft=draft, response_format_mode='json_object')
        else:
            from shuxueshuo_server.solver.extraction.problem_source_review import build_review_request
            req = build_review_request(draft, req.evidence_pack, store, {"differences": []}, 'json_object')
    assert req.contract_version == contract
    req = replace(req, images=(*req.images, replace(req.images[0], role='zoom')))
    calls, init = [], {}
    provider = create_vision_provider(SolverRuntimeConfig(deepseek_api_key='test', doubao_api_key=None),
        client_factory=client_factory([response()], calls, init))
    req = provider.prepare_request(req)
    result = provider.complete(req)
    audit = req.redacted_payload()
    sent = calls[0]
    assert init['max_retries'] == 0 and init['timeout'] == 300
    for key in ('model', 'response_format', 'stream', 'max_tokens', 'timeout', 'reasoning_effort'):
        assert sent[key] == audit[key]
    assert sent['max_tokens'] == 16384 and sent['stream'] is False
    assert 'temperature' not in sent and 'temperature' not in audit
    assert sent['extra_body'] == {'thinking': {'type': 'enabled'}}
    assert audit['thinking'] == {'type': 'enabled'} and audit['reasoning_effort'] == 'low'
    parts = [p['image_url'] for p in sent['messages'][1]['content'] if p['type'] == 'image_url']
    assert len(parts) == len(req.images)
    for part, image in zip(parts, req.images, strict=True):
        assert part['detail'] == 'high'
        assert sha256(base64.b64decode(part['url'].split(',')[1])).hexdigest() == image.artifact.sha256
    assert result.text == '{"value":7}' and result.usage is None
    assert result.thinking_mode == 'enabled' and result.reasoning_effort == 'low'


@pytest.mark.parametrize('mutation', ['missing', 'corrupt', 'hash', 'dimensions', 'oversize'])
def test_invalid_images_never_make_a_network_call(tmp_path, mutation):
    _, req = request_fixture(tmp_path)
    image = req.images[0]
    if mutation == 'missing': req = replace(req, images=())
    if mutation == 'corrupt':
        image = replace(image, content=b'broken', artifact=replace(image.artifact, sha256=sha256(b'broken').hexdigest()))
    if mutation == 'hash': image = replace(image, content=image.content + b'x')
    if mutation == 'dimensions': image = replace(image, width=1)
    if mutation == 'oversize': image = replace(image, content=b'X' * (32 * 1024**2 + 1))
    if mutation != 'missing': req = replace(req, images=(image,))
    calls = []
    provider = DeepSeekMultimodalExtractionProvider(api_key='test', base_url='https://api.deepseek.com',
        client_factory=client_factory([], calls, {}))
    with pytest.raises(MultimodalProviderError, match='image|vision'):
        provider.complete(req)
    assert not calls


@pytest.mark.parametrize('status', [429, 500, 503, 'timeout', 400])
def test_network_retries_bounded(tmp_path, status):
    _, req = request_fixture(tmp_path)
    err = TimeoutError('timeout') if status == 'timeout' else Exception('transport failed')
    if status != 'timeout': err.status_code = status
    calls = []
    provider = DeepSeekMultimodalExtractionProvider(api_key='test', base_url='https://api.deepseek.com',
        client_factory=client_factory([err, err], calls, {}), sleeper=lambda _: None)
    with pytest.raises(MultimodalProviderError) as caught: provider.complete(req)
    assert len(calls) == (1 if status == 400 else 2)
    assert len(caught.value.provider_attempts) == len(calls)
    assert provider.last_usage is None


def test_empty_content_cannot_use_reasoning(tmp_path):
    _, req = request_fixture(tmp_path)
    provider = DeepSeekMultimodalExtractionProvider(api_key='test', base_url='https://api.deepseek.com',
        client_factory=client_factory([response(None), response('')], [], {}), sleeper=lambda _: None)
    with pytest.raises(MultimodalProviderError, match='visible JSON'): provider.complete(req)


@pytest.mark.parametrize('text,finish', [('{} trailing', 'stop'), ('{}', 'length'), ('{"family_id":false}', 'stop')])
def test_invalid_response_rejected_by_production_chain(tmp_path, text, finish):
    from shuxueshuo_server.solver.extraction.context import ExtractionAttemptLedger
    from shuxueshuo_server.solver.extraction.problem_domain_service import ProblemDomainExtractionService
    fixture, _, context, store, _ = make_f3_fixture(tmp_path)
    provider = create_vision_provider(SolverRuntimeConfig(deepseek_api_key='test'),
        client_factory=client_factory([response(text, finish)], [], {}))
    run = ProblemDomainExtractionService(input_artifact_reader=store, output_artifact_store=store, provider=provider).run(
        context, attempt_ledger=ExtractionAttemptLedger.for_context(context), ancestor_contexts=(fixture.context,), max_attempts=1)
    assert not run.accepted
    assert run.attempts[0].provider_response.raw_payload
    assert run.attempts[0].provider_response.text == text


def test_vision_config_independent_and_frozen(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('DEEPSEEK_API_KEY=test\nDEEPSEEK_MODEL=solver-other\nDEEPSEEK_BASE_URL=https://solver.example\nDEEPSEEK_VISION_TIMEOUT=120\nDEEPSEEK_VISION_MAX_TOKENS=10000\n')
    for key in ('DEEPSEEK_MODEL', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_VISION_TIMEOUT', 'DEEPSEEK_VISION_MAX_TOKENS'):
        monkeypatch.delenv(key, raising=False)
    cfg = SolverRuntimeConfig.from_sources(env_file=env)
    assert cfg.deepseek_model == 'solver-other'
    frozen = vision_effective_config(cfg)
    assert frozen['model'] == 'deepseek-flash' and frozen['base_url'] == 'https://api.deepseek.com'
    provider = create_vision_provider(replace(cfg, deepseek_vision_timeout=300), frozen_config=frozen,
        client_factory=client_factory([], [], {}))
    assert provider.request_timeout == 120 and provider.max_output_tokens == 10000
    with pytest.raises(ValueError): create_vision_provider(cfg, frozen_config={**frozen, 'thinking': {'type': 'disabled'}})


def live_config():
    if os.environ.get('RUN_LLM_INTEGRATION') != '1': pytest.skip('requires RUN_LLM_INTEGRATION=1')
    config = SolverRuntimeConfig.from_sources()
    assert config.deepseek_api_key, 'RUN_LLM_INTEGRATION=1 requires DEEPSEEK_API_KEY'
    return config


@pytest.mark.live_llm
def test_real_vision_depends_on_image_without_ocr(tmp_path):
    config = live_config()
    output = Path(os.environ.get('DEEPSEEK_VISION_LIVE_OUTPUT', str(tmp_path))) / 'image-dependency'
    store, template = request_fixture(output)
    provider = create_vision_provider(config)
    prompt = MultimodalExtractionPrompt(system='Read the number in the image. Return only JSON, for example {"value":0}.',
        user_prefix='What number is shown?', user_suffix='Return one integer in the value field.')
    observations = []
    for index, value in enumerate((37, 82)):
        img = Image.new('RGB', (400, 200), 'white')
        ImageDraw.Draw(img).text((110, 40), str(value), font=ImageFont.load_default(size=90), fill='black')
        buffer = BytesIO(); img.save(buffer, format='PNG'); data = buffer.getvalue()
        artifact = store.put_bytes(kind='selection_crop', content=data, media_type='image/png', suffix='.png')
        image = MultimodalProviderImage(image_id='image', page_id='page', role='primary', artifact=artifact,
            content=data, width=400, height=200)
        pack = replace(template.evidence_pack, images=(replace(template.evidence_pack.images[0],
            image_id=image.image_id, page_id=image.page_id, artifact=artifact, width=400, height=200),))
        req = provider.prepare_request(replace(template, evidence_pack=pack, prompt=prompt, images=(image,), contract_schema={}))
        store.put_json(kind='vision_probe_request', payload=req.redacted_payload())
        result = provider.complete(req)
        store.put_json(kind='vision_probe_response', payload=dict(result.raw_payload))
        actual = json.loads(result.text)
        observations.append({'sample': index, 'sha256': artifact.sha256, 'actual': actual, 'metadata': result.metadata_payload()})
        assert result.finish_reason == 'stop' and actual == {'value': value}
    (output / 'summary.json').write_text(json.dumps(observations, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('case_id', CASES)
def test_shared_smoke_with_recorded_external_responses(tmp_path, monkeypatch, case_id):
    from shuxueshuo_server.solver.extraction import problem_domain_smoke as smoke
    from shuxueshuo_server.solver.extraction.gold_corpus import load_gold_corpus
    def factory(config, **kwargs):
        provider = create_vision_provider(config, client_factory=client_factory([], [], {}))
        def create(**options):
            suffix = options['messages'][1]['content'][-1]['text']
            if '"binding"' in suffix and 'problem-source-review/v1' in suffix:
                data = json.loads(suffix)
                key = data['binding']
                scope = next(k for k, v in data['units'].items() if v['kind'] == 'scope')
                return response(json.dumps({'schema_version': 'problem-source-review/v1', 'binding': key,
                    'status': 'confirmed', 'findings': [{'unit_ids': [scope], 'source_text': smoke._load_domain_gold(case_id)['root']['source_text'][0], 'message': 'Recorded gold confirms the printed question.', 'regions': [{'region_id': None, 'page_id': 'page_1', 'bbox': [0, 0, 1, 1]}]}]}))
            return response(json.dumps(smoke._load_domain_gold(case_id), ensure_ascii=False))
        provider._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        return provider
    monkeypatch.setattr(smoke, 'create_vision_provider', factory)
    result = smoke._run_sample(next(c for c in load_gold_corpus().cases if c.problem_id == case_id), 1,
        batch_dir=tmp_path, f2_root=None, config=SolverRuntimeConfig(deepseek_api_key='recorded'),
        max_attempts=3, provider_name='deepseek', request_timeout=300)
    assert result.ok, result.to_payload()
    assert result.full_question_image_input and result.network_attempt_count <= 12


def test_complete_multipage_input_preserves_order_and_rejects_missing_page(tmp_path):
    from _problem_extraction_f3_support import make_multi_page_f3_fixture
    _, _, store, pack = make_multi_page_f3_fixture(tmp_path)
    req = build_multimodal_provider_request(pack, artifact_reader=store,
        expected_problem_id='multipage', response_format_mode='json_object')
    calls = []
    provider = create_vision_provider(SolverRuntimeConfig(deepseek_api_key='test'),
        client_factory=client_factory([response()], calls, {}))
    provider.complete(req)
    sent = [p['image_url'] for p in calls[0]['messages'][1]['content'] if p['type'] == 'image_url']
    assert [sha256(base64.b64decode(p['url'].split(',')[1])).hexdigest() for p in sent] == [i.artifact.sha256 for i in pack.images]
    for images in (req.images[:1], tuple(reversed(req.images))):
        with pytest.raises(MultimodalProviderError, match='primary images'):
            provider.complete(replace(req, images=images))
    assert len(calls) == 1


def test_opted_in_live_gate_missing_key_is_failure(monkeypatch):
    monkeypatch.setenv('RUN_LLM_INTEGRATION', '1')
    monkeypatch.setattr(SolverRuntimeConfig, 'from_sources', lambda **_: SolverRuntimeConfig(deepseek_api_key=None))
    with pytest.raises(AssertionError, match='DEEPSEEK_API_KEY'):
        live_config()
