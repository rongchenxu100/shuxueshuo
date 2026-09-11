from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import select, func

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.api import create_app
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import Conflict
from shuxueshuo_server.product.repositories import row, insert


def discover(source, revision, snapshot):
    return {'deployment_version': 'offline-api-v1', 'config': {}, 'dependencies': {
        s['stage_key']: {'inputs': {'source': source['sha256']}, 'resources': {}, 'config': {}, 'upstream': {}}
        for s in snapshot['stages']}}


@pytest.fixture
def api(setup, settings, tmp_path):
    from dataclasses import replace
    s, ctx, admin = setup
    # HTTP lifecycle markers belong to this test, independent of native service stop/start.
    settings = replace(settings, root=tmp_path)
    (tmp_path / 'work').mkdir()
    (tmp_path / 'locks').mkdir()
    application = Application(settings, s, ctx, discover=discover)
    with TestClient(create_app(application)) as client:
        yield application, client, admin


def create(client, suffix=''):
    h = lambda op: {'Idempotency-Key': op + suffix}
    batch = client.post('/api/product/v1/batches', json={'name': 'test'}, headers=h('batch')).json()
    image = BytesIO(); Image.new('RGB', (8, 8), 'white').save(image, format='PNG')
    uploaded = client.post(f"/api/product/v1/batches/{batch['id']}/uploads", headers=h('upload'), files={'image': ('question.png', image.getvalue(), 'image/png')})
    assert uploaded.status_code == 201, uploaded.text
    return batch, uploaded.json(), image.getvalue()


def test_upload_and_first_build_idempotency(api):
    a, client, _ = api
    batch, uploaded, content = create(client)
    item = uploaded['item']
    assert uploaded['status'] == 'created'
    replay = client.post(f"/api/product/v1/batches/{batch['id']}/uploads", headers={'Idempotency-Key': 'upload'}, files={'image': ('question.png', content, 'image/png')})
    assert replay.json() == uploaded
    assert client.get('/api/product/v1/requests/upload/upload').json()['response'] == uploaded
    result = client.post(f"/api/product/v1/problems/{item['problem_id']}/builds", json={'source_id': item['source_id'], 'batch_item_id': item['id']}, headers={'Idempotency-Key': 'build'})
    assert result.status_code == 202, result.text
    def submit(key): return a.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), key)
    with ThreadPoolExecutor(3) as pool: results = list(pool.map(submit, ['second', 'third', 'fourth']))
    assert all(r == result.json() for r in results)
    build = client.get('/api/product/v1/builds/' + result.json()['build_id']).json()
    assert len(build['stages']) == 9 and build['status'] == 'queued'
    assert 'effective_config' not in build and 'target_dependencies' not in build
    assert client.get('/api/product/v1/batches/' + batch['id']).json()['items'][0]['status'] == 'queued'
    _, repeated, _ = create(client, 'again')
    assert repeated['status'] == 'reused' and repeated['item']['problem_id'] == item['problem_id']
    with transaction(a.db) as c:
        assert c.scalar(select(func.count()).select_from(m.builds).where(m.builds.c.workspace_id == a.ctx.workspace_id)) == 1


def test_nested_request_rolls_back_business_and_outbox(api):
    a, client, _ = api
    _, uploaded, _ = create(client)
    item = uploaded['item']
    def fail():
        a.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), 'nested')
        raise RuntimeError('fault after task submission')
    with pytest.raises(RuntimeError): a.request('fault', 'key', {}, fail)
    with transaction(a.db) as c:
        assert c.scalar(select(func.count()).select_from(m.builds).where(m.builds.c.workspace_id == a.ctx.workspace_id)) == 0
        assert c.scalar(select(func.count()).select_from(m.outbox_messages).where(m.outbox_messages.c.workspace_id == a.ctx.workspace_id)) == 0


def test_revision_replay_and_conflict(api, domain):
    a, client, _ = api
    _, uploaded, _ = create(client)
    pid = UUID(uploaded['item']['problem_id'])
    base = a.service.save_revision(a.ctx, pid, None, domain)
    changed = deepcopy(domain); changed['root']['source_text'][0] += '（校对）'
    body = {'base_revision_id': str(base['id']), 'domain': changed}
    response = client.post(f'/api/product/v1/problems/{pid}/revisions', json=body, headers={'Idempotency-Key': 'revision'})
    assert response.status_code == 200, response.text
    assert client.post(f'/api/product/v1/problems/{pid}/revisions', json=body, headers={'Idempotency-Key': 'revision'}).json() == response.json()
    assert client.post(f'/api/product/v1/problems/{pid}/revisions', json={**body, 'domain': domain}, headers={'Idempotency-Key': 'revision'}).status_code == 409


def test_problem_list_exposes_current_source_wording_and_actual_build_status(api, domain):
    a, client, _ = api
    _, uploaded, _ = create(client)
    item = uploaded['item']; pid = UUID(item['problem_id'])
    before = client.get(f'/api/product/v1/problems/{pid}').json()
    assert before['statement_text'] is None
    assert before['source_filename'] == 'question.png'
    assert before['latest_build_status'] is None
    base = a.service.save_revision(a.ctx, pid, None, domain)
    expected = []
    def collect(node):
        expected.extend(t.strip() for t in node.get('source_text', []) if t.strip())
        for child in node.get('children', []): collect(child)
    collect(domain['root'])
    a.submit(pid, UUID(item['source_id']), UUID(item['id']), 'list-build')
    listing = client.get('/api/product/v1/problems').json()['problems']
    assert len(listing) == 1  # Other test workspaces remain private.
    assert listing[0]['statement_text'] == '\n'.join(expected)
    assert listing[0]['latest_build_status'] == 'queued'
    assert 'domain_json' not in listing[0]
    changed = deepcopy(domain); changed['root']['source_text'][0] += '（题干校对）'
    a.service.save_revision(a.ctx, pid, base['id'], changed)
    detail = client.get(f'/api/product/v1/problems/{pid}').json()
    assert '（题干校对）' in detail['statement_text']
    assert detail['statement_text'] == client.get('/api/product/v1/problems').json()['problems'][0]['statement_text']


def test_http_and_websocket_identity_boundaries(api):
    _, client, _ = api
    assert client.get('/api/product/v1/problems', headers={'Origin': 'https://evil.invalid'}).status_code == 403
    assert client.get('/api/product/v1/problems', headers={'Host': 'evil.invalid', 'X-Forwarded-For': '127.0.0.1'}).status_code == 403
    assert client.post('/api/product/v1/batches', json={'owner_user_id': str(uuid4())}, headers={'Idempotency-Key': 'bad'}).status_code == 422
    assert client.get('/api/review/runs').status_code == 404


def test_websocket_snapshot_replay_and_cancel(api):
    a, client, _ = api
    batch, uploaded, _ = create(client)
    item = uploaded['item']
    result = a.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), 'build')
    with client.websocket_connect('/api/product/v1/ws') as socket:
        socket.send_json({'streams': [{'kind': 'build', 'id': result['build_id']}, {'kind': 'batch', 'id': batch['id']}]})
        first = socket.receive_json(); second = socket.receive_json()
        assert first['type'] == second['type'] == 'snapshot'
        assert first['data']['status'] == 'queued'
        a.service.cancel(a.ctx, UUID(result['build_id']))
        for _ in range(10):
            event = socket.receive_json()
            if event.get('event_type') == 'build.cancelled' and event['kind'] == 'build': break
        else: pytest.fail('cancel event missing')
    replay = client.get('/api/product/v1/events', params={'kind': 'build', 'aggregate_id': result['build_id'], 'after': first['data']['last_seq']})
    assert replay.json()['events'][0]['event_type'] == 'build.cancelled'
    assert client.get('/api/product/v1/events', params={'kind': 'build', 'aggregate_id': result['build_id'], 'after': 9999}).status_code == 409


def test_ambiguous_source_is_retained_and_resolution_is_idempotent(api):
    a, client, admin = api
    _, first, _ = create(client)
    item = first['item']
    with transaction(admin) as c:
        p = insert(c, m.problems, workspace_id=a.ctx.workspace_id, owner_user_id=a.ctx.user_id, primary_source_id=UUID(item['source_id']))
        insert(c, m.problem_sources, workspace_id=a.ctx.workspace_id, problem_id=p['id'], source_id=UUID(item['source_id']), match_method='manual')
    batch, ambiguous, _ = create(client, 'ambiguous')
    assert ambiguous['status'] == 'ambiguous' and ambiguous['source_id']
    path = '/api/product/v1/sources/' + ambiguous['source_id'] + '/resolve'
    resolved = client.post(path, json={'problem_id': item['problem_id']}, headers={'Idempotency-Key': 'resolve'})
    assert resolved.status_code == 200, resolved.text
    assert client.post(path, json={'problem_id': item['problem_id']}, headers={'Idempotency-Key': 'resolve'}).json() == resolved.json()
    assert client.post(path, json={'problem_id': str(p['id'])}, headers={'Idempotency-Key': 'other'}).status_code == 409
    assert len(client.get('/api/product/v1/batches/' + batch['id']).json()['items']) == 1


def test_draining_blocks_writes_but_keeps_queries(api):
    a, client, _ = api
    (a.settings.root / 'locks/services-draining').touch()
    assert client.get('/api/product/v1/problems').status_code == 200
    response = client.post('/api/product/v1/batches', json={}, headers={'Idempotency-Key': 'draining'})
    assert response.status_code == 503 and response.json()['error']['code'] == 'service.draining'


def test_invalid_length_and_problem_snapshot_watermark(api):
    a, client, _ = api
    assert client.post('/api/product/v1/batches', json={}, headers={'Idempotency-Key': 'bad-length', 'Content-Length': 'invalid'}).status_code == 422
    _, uploaded, _ = create(client)
    pid = uploaded['item']['problem_id']
    snapshot = client.get('/api/product/v1/problems/' + pid).json()
    assert isinstance(snapshot['last_seq'], int)
    with client.websocket_connect('/api/product/v1/ws') as ws:
        ws.send_json({'streams': [{'kind': 'problem', 'id': pid}]})
        event = ws.receive_json()
        assert event['type'] == 'snapshot' and event['data']['last_seq'] == snapshot['last_seq']


def test_stage_event_keys_and_failed_artifact_names_are_preserved(api):
    from shuxueshuo_server.product.services import clean_config, append_event
    a, client, _ = api
    _, uploaded, _ = create(client)
    item = uploaded['item']
    build = a.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), 'build')
    execution = a.service.acquire_execution(a.ctx, UUID(build['job_id']), 'test', deployment_version='offline-api-v1')
    args = (a.ctx, UUID(build['build_id']), execution['id'], execution['epoch'])
    attempt = a.service.begin_stage(*args, 'source')
    artifact = a.service.register_artifact(*args, attempt_id=attempt['id'], content=b'{}', artifact_type='validation', content_type='application/json')
    with transaction(a.db) as c:
        append_event(c, a.ctx.workspace_id, 'build', UUID(build['build_id']), 'artifact.registered',
            {'stage_key': 'source', 'artifact_id': str(artifact['id']), 'name': '来源校验报告', 'role': 'validation'})
    a.service.finish_failure(*args, 'test.failure')
    data = a.build(UUID(build['build_id']))
    assert data['artifacts'][0]['name'] == '来源校验报告'
    events = a.events('build', UUID(build['build_id']))
    assert next(e for e in events if e['event_type'] == 'stage.running')['payload']['stage_key'] == 'source'
    assert clean_config({'max_tokens': 12, 'api_key': 'secret', 'authorization': 'secret'}) == {
        'max_tokens': 12, 'api_key': '[REDACTED]', 'authorization': '[REDACTED]'}


def test_environment_fingerprints_extracted_and_manual_revisions(api, domain):
    a, client, _ = api
    _, uploaded, _ = create(client)
    item = uploaded['item']
    pid = UUID(item['problem_id'])
    sid = UUID(item['source_id'])
    seen = []
    original = a.discover
    def capture(source, revision, snapshot):
        seen.append(revision)
        return original(source, revision, snapshot)
    a.discover = capture
    assert a.environment(pid, sid)[2]
    assert seen[-1] is None
    extracted = a.service.save_revision(a.ctx, pid, None, domain)
    assert extracted['kind'] == 'extracted'
    assert a.environment(pid, sid)[2]
    assert seen[-1] == {
        'id': str(extracted['id']),
        'semantic_hash': extracted['semantic_hash'],
        'kind': 'extracted',
    }
    changed = deepcopy(domain)
    changed['root']['source_text'][0] += '（校对）'
    manual = a.save_revision(pid, extracted['id'], changed, 'manual-edit')
    assert manual['kind'] == 'manual'
    assert a.environment(pid, sid)[2]
    assert seen[-1]['id'] == manual['id'] and seen[-1]['kind'] == 'manual'


def test_rebuild_preview_reruns_extraction_when_resolved_revision_diverges(api, domain):
    a, client, _ = api
    _, uploaded, _ = create(client)
    item = uploaded['item']
    pid = UUID(item['problem_id'])
    first = a.service.save_revision(a.ctx, pid, None, domain)
    build = a.submit(pid, UUID(item['source_id']), UUID(item['id']), 'build')
    execution = a.service.acquire_execution(a.ctx, UUID(build['job_id']), 'test', deployment_version='offline-api-v1')
    args = (a.ctx, UUID(build['build_id']), execution['id'], execution['epoch'])
    for stage_key in [s['stage_key'] for s in a.service.registry.get('problem_lesson', 'v1')['stages']]:
        attempt = a.service.begin_stage(*args, stage_key)
        manifest = a.service.register_artifact(*args, attempt_id=attempt['id'], content=b'{"ok":true}',
            artifact_type='manifest', content_type='application/json')
        checkpoint = a.service.register_artifact(*args, attempt_id=attempt['id'], content=b'{"schema_version":"product-checkpoint/v1"}',
            artifact_type='checkpoint', content_type='application/json')
        # Bypass commit_stage contracts: mark the stage accepted with the registered artifacts.
        with transaction(a.db) as c:
            c.execute(m.stage_attempts.update().where(m.stage_attempts.c.id == attempt['id']).values(
                status='succeeded', finished_at=func.now(), manifest_json={'stage_key': stage_key},
                manifest_artifact_id=manifest['id'], manifest_sha256=manifest['sha256'],
                checkpoint_artifact_id=checkpoint['id']))
            c.execute(m.build_stages.update().where(m.build_stages.c.build_id == UUID(build['build_id']),
                m.build_stages.c.stage_key == stage_key).values(status='succeeded', accepted_attempt_id=attempt['id']))
    with transaction(a.db) as c:
        c.execute(m.builds.update().where(m.builds.c.id == UUID(build['build_id'])).values(
            status='succeeded', resolved_revision_id=first['id'], finished_at=func.now()))
        c.execute(m.jobs.update().where(m.jobs.c.id == UUID(build['job_id'])).values(status='succeeded', lease_expires_at=None))
        c.execute(m.job_executions.update().where(m.job_executions.c.id == execution['id']).values(
            status='succeeded', finished_at=func.now()))
    newer = deepcopy(domain)
    newer['root']['source_text'][0] += '（新提取）'
    second = a.service.save_revision(a.ctx, pid, first['id'], newer)
    assert second['id'] != first['id']
    preview = a.rebuild_preview(UUID(build['build_id']))
    assert 'extraction' in preview['rerun_stages']
    assert any(r['code'] == 'build.revision_changed' for r in preview['reasons'])
