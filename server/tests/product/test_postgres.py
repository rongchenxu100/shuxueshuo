from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4
import json

from PIL import Image
import pytest
from sqlalchemy import select, text, func
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import Conflict, Forbidden, IntegrityFailure, ProductError
from shuxueshuo_server.product.repositories import insert, row, UserContext
from shuxueshuo_server.product.services import append_event
from shuxueshuo_server.product.admin.database import seed
from shuxueshuo_server.product.outbox import reserve, acknowledge


def upload(service, ctx):
    content = BytesIO()
    Image.new('RGB', (4, 4)).save(content, format='PNG')
    batch = service.create_batch(ctx)
    return service.reference_upload(ctx, batch['id'], content.getvalue(), 'test.png', 'image/png')['item']


def submit(service, ctx, item, revision_id=None, **overrides):
    dependencies = {s['stage_key']: dict(inputs={}, resources={'test': 'v1'}, config={}, upstream={})
                    for s in service.registry.get('problem_lesson', 'v1')['stages']}
    args = dict(request_id=uuid4().hex, source_id=item['source_id'], base_revision_id=revision_id,
        dependencies=dependencies, config={}, deployment_version='test-v1')
    args.update(overrides)
    result = service.submit_build(ctx, item['problem_id'], **args)
    return {k: UUID(v) for k, v in result.items()}


def test_seed_idempotent_and_only_three_defaults(setup):
    _, _, admin = setup
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(lambda _: seed(admin), range(3)))
    assert len(set(results)) == 1
    with transaction(admin) as c:
        assert c.scalar(select(func.count()).select_from(m.users).where(m.users.c.key == 'internal')) == 1
        assert c.scalar(select(func.count()).select_from(m.workspaces).where(m.workspaces.c.slug == 'default')) == 1


def test_same_file_concurrent_reference(setup):
    s, ctx, _ = setup
    with ThreadPoolExecutor(4) as pool:
        items = list(pool.map(lambda _: upload(s, ctx), range(4)))
    assert len({x['problem_id'] for x in items}) == 1
    assert len({x['id'] for x in items}) == 4
    with transaction(s.db) as c:
        assert c.scalar(select(func.count()).select_from(m.builds).where(m.builds.c.workspace_id == ctx.workspace_id)) == 0


def test_role_and_immutable_guards(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    for statement in [text('CREATE TABLE not_allowed (id int)'), m.sources.update().where(m.sources.c.id == item['source_id']).values(filename='overwrite'),
                      m.problems.delete().where(m.problems.c.id == item['problem_id'])]:
        with pytest.raises(DBAPIError), transaction(s.db) as c:
            c.execute(statement)
    outsider = UserContext(ctx.workspace_id, uuid4())
    with pytest.raises(Forbidden): s.create_batch(outsider)


def test_foreign_keys_require_same_problem_and_space(setup):
    s, ctx, admin = setup
    a = upload(s, ctx)
    other = s.create_batch(ctx)
    with pytest.raises(DBAPIError), transaction(s.db) as c:
        insert(c, m.batch_items, workspace_id=uuid4(), batch_id=other['id'], position=1,
               source_id=a['source_id'], problem_id=a['problem_id'])
    with pytest.raises(DBAPIError), transaction(s.db) as c:
        insert(c, m.batch_items, workspace_id=ctx.workspace_id, batch_id=other['id'], position=0,
               source_id=a['source_id'], problem_id=a['problem_id'])


def test_build_idempotency_fencing_cancel(setup):
    s, ctx, admin = setup
    item = upload(s, ctx)
    result = submit(s, ctx, item, request_id='stable')
    assert submit(s, ctx, item, request_id='stable') == result
    with pytest.raises(Conflict): submit(s, ctx, item, request_id='stable', config={'changed': True})
    first = s.acquire_execution(ctx, result['job_id'], 'worker1', deployment_version='test-v1')
    with pytest.raises(Conflict): s.acquire_execution(ctx, result['job_id'], 'worker2', deployment_version='test-v1')
    with transaction(admin) as c:
        c.execute(m.jobs.update().where(m.jobs.c.id == result['job_id']).values(lease_expires_at=func.now() - text("interval '1 second'")))
    second = s.acquire_execution(ctx, result['job_id'], 'worker2', deployment_version='test-v1')
    assert second['epoch'] == first['epoch'] + 1
    with pytest.raises(Conflict): s.heartbeat(ctx, result['build_id'], first['id'], first['epoch'])
    s.cancel(ctx, result['build_id'])
    with pytest.raises(Conflict): s.heartbeat(ctx, result['build_id'], second['id'], second['epoch'])
    assert s.build_snapshot(ctx, result['build_id'])['build']['status'] == 'cancelled'


def test_events_rollback_and_outbox_token(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    result = submit(s, ctx, item)
    with pytest.raises(RuntimeError), transaction(s.db) as c:
        append_event(c, ctx.workspace_id, 'build', result['build_id'], 'should.rollback', {})
        raise RuntimeError()
    assert [e['seq'] for e in s.read_events(ctx, 'build', result['build_id'])] == [1]
    with transaction(s.db) as c:
        messages = reserve(c, limit=1000)
        message = next(x for x in messages if x['job_id'] == result['job_id'])
    with pytest.raises(Conflict), transaction(s.db) as c:
        acknowledge(c, message['id'], uuid4(), confirmed=True)
    with transaction(s.db) as c:
        acknowledge(c, message['id'], message['publisher_token'], confirmed=True)
        acknowledge(c, message['id'], message['publisher_token'], confirmed=True)


def test_revision_validation_and_cas(setup, domain):
    s, ctx, _ = setup
    item = upload(s, ctx)
    revision = s.save_revision(ctx, item['problem_id'], None, domain)
    assert revision['domain_json'] == revision['verified_json']['graph']
    assert s.save_revision(ctx, item['problem_id'], revision['id'], domain)['id'] == revision['id']
    changed = deepcopy(domain)
    changed['root']['source_text'][0] += '（人工校对）'
    def save():
        try: return s.save_revision(ctx, item['problem_id'], revision['id'], changed)['id']
        except Conflict: return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: save(), range(2)))
    assert results.count('conflict') == 1
    with pytest.raises(Conflict): s.save_revision(ctx, item['problem_id'], revision['id'], domain)


@pytest.mark.parametrize('superseded', [False, True])
@pytest.mark.parametrize('reuse_page', [False, True])
def test_complete_page_and_resource_access(setup, domain, superseded, reuse_page):
    s, ctx, _ = setup
    item = upload(s, ctx)
    revision = s.save_revision(ctx, item['problem_id'], None, domain)
    result = submit(s, ctx, item, revision['id'])
    execution = s.acquire_execution(ctx, result['job_id'], 'worker', deployment_version='test-v1')
    args = (ctx, result['build_id'], execution['id'], execution['epoch'])
    s.bind_requested_revision(*args)
    def artifact(value, kind, schema=None, page=False, mime='application/json'):
        return s.register_artifact(*args, content=value if isinstance(value, bytes) else json.dumps(value).encode(),
            artifact_type=kind, content_type=mime, schema_version=schema, access_class='page' if page else 'private', attempt_id=attempt['id'])
    for stage in s.registry.get('problem_lesson', 'v1')['stages']:
        attempt = s.begin_stage(*args, stage['stage_key'])
        manifest = artifact(dict(stage_key=stage['stage_key'], contract_version='v1', inputs={}, resources={'test': 'v1'}, config={}, upstream={}), 'manifest')
        checkpoint = artifact({'recorded': True}, 'checkpoint')
        outputs = []
        if stage['stage_key'] == 'page':
            html = artifact(b'<!doctype html><title>Test</title><p>Recorded fixture</p>', 'page_html', page=True, mime='text/html')
            assets = {'index.html': html['id']}
            package = artifact(dict(schema_version='product-page/v1', entry_artifact_id=str(html['id']),
                assets={k: str(v) for k,v in assets.items()}), 'page_manifest', 'product-page/v1')
            outputs = [{'name': 'page_html', 'artifact_id': html['id']}, {'name': 'page_manifest', 'artifact_id': package['id']}]
        s.commit_stage(*args, stage['stage_key'], manifest_artifact_id=manifest['id'], checkpoint_artifact_id=checkpoint['id'], outputs=outputs)
    if superseded:
        submit(s, ctx, item, revision['id'])
    page = s.finish_page(*args, entry_artifact_id=html['id'], package_manifest_artifact_id=package['id'], assets=assets)
    if reuse_page:
        original_stages = s.build_snapshot(ctx, result['build_id'])['stages']
        result, args = running_build(s, ctx, item, revision['id'], parent_build_id=result['build_id'])
        s.bind_requested_revision(*args)
        for stage in original_stages:
            with transaction(s.db) as c:
                accepted = row(c, m.stage_attempts, id=stage['accepted_attempt_id'])
                outputs = s._attempt_outputs(c, accepted['id'])
            s.commit_stage(*args, stage['stage_key'], manifest_artifact_id=accepted['manifest_artifact_id'],
                           checkpoint_artifact_id=accepted['checkpoint_artifact_id'], outputs=outputs,
                           reused_from_attempt_id=accepted['id'])
        if superseded: submit(s, ctx, item, revision['id'])
        page = s.finish_page(*args, entry_artifact_id=html['id'], package_manifest_artifact_id=package['id'], assets=assets)
    assert s.page_resource(ctx, page['id'])['content_type'] == 'text/html'
    with pytest.raises(Forbidden): s.page_resource(ctx, page['id'], 'raw.json')
    s.review(ctx, page['id'], 'approved')
    with transaction(s.db) as c:
        assert row(c, m.problems, id=item['problem_id'])['current_page_build_id'] == (None if superseded else page['id'])
    if not superseded:
        # A new request with identical effective inputs retains the valid old page on failure.
        newer = submit(s, ctx, item, revision['id'])
        newer_execution = s.acquire_execution(ctx, newer['job_id'], 'new-worker', deployment_version='test-v1')
        s.finish_failure(ctx, newer['build_id'], newer_execution['id'], newer_execution['epoch'], 'test.failure')
        assert s.get_problem(ctx, item['problem_id'])['current_page_build_id'] == page['id']
        submit(s, ctx, item, revision['id'], config={'presentation': 'changed'})
        assert s.get_problem(ctx, item['problem_id'])['current_page_build_id'] is None
    changed = deepcopy(domain)
    changed['root']['source_text'][0] += '（修订）'
    s.save_revision(ctx, item['problem_id'], revision['id'], changed)
    with transaction(s.db) as c:
        assert row(c, m.problems, id=item['problem_id'])['current_page_build_id'] is None
    assert s.page_resource(ctx, page['id'])['id'] == html['id']


def test_failed_attempt_call_audit_and_diagnostics(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    result = submit(s, ctx, item)
    execution = s.acquire_execution(ctx, result['job_id'], 'worker', deployment_version='test-v1')
    args = (ctx, result['build_id'], execution['id'], execution['epoch'])
    attempt = s.begin_stage(*args, 'source')
    assert s.begin_stage(*args, 'source')['id'] == attempt['id']
    audit = s.register_artifact(*args, content=b'{"error":"test provider failed"}', artifact_type='call_audit', content_type='application/json', attempt_id=attempt['id'])
    call = s.record_call(*args, attempt['id'], audit['id'], call_kind='observation', provider='offline-fixture', status='failed')
    assert s.record_call(*args, attempt['id'], audit['id'], call_kind='observation', provider='offline-fixture', status='failed')['id'] == call['id']
    assert call['input_tokens'] is None
    s.record_diagnostic(*args, code='provider.failed', message='offline fault injection', stage_attempt_id=attempt['id'], evidence_artifact_id=audit['id'])
    s.fail_stage(*args, attempt['id'], 'provider.failed')
    s.finish_failure(*args, 'provider.failed')
    with pytest.raises(Conflict): s.record_call(*args, attempt['id'], audit['id'], call_kind='observation', status='failed')


def test_definition_versions_and_deferred_stage_set(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    old = submit(s, ctx, item)
    snapshot = s.registry.get('problem_lesson', 'v1')
    snapshot['stages'][0]['title'] = '新版来源展示'
    s.registry.register('problem_lesson', 'v2', snapshot)
    new = submit(s, ctx, item, pipeline_version='v2')
    assert s.build_snapshot(ctx, old['build_id'])['stages'][0]['title'] != s.build_snapshot(ctx, new['build_id'])['stages'][0]['title']
    with pytest.raises(DBAPIError), transaction(s.db) as c:
        insert(c, m.build_stages, workspace_id=ctx.workspace_id, build_id=old['build_id'], stage_key='unregistered', ordinal=10, status='pending')
    with pytest.raises(Conflict): submit(s, ctx, item, from_stage='removed')


def test_concurrent_stream_sequences(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    result = submit(s, ctx, item)
    def append(i):
        with transaction(s.db) as c:
            return append_event(c, ctx.workspace_id, 'build', result['build_id'], 'test.event', {'i': i})['seq']
    with ThreadPoolExecutor(4) as pool:
        numbers = list(pool.map(append, range(12)))
    assert sorted(numbers) == list(range(2, 14))
    snapshot = s.build_snapshot(ctx, result['build_id'])
    assert snapshot['last_seq'] == 13
    assert [e['seq'] for e in s.read_events(ctx, 'build', result['build_id'], after=7)] == list(range(8, 14))


def test_private_raw_cannot_become_page(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    result = submit(s, ctx, item)
    e = s.acquire_execution(ctx, result['job_id'], 'worker', deployment_version='test-v1')
    with pytest.raises(Forbidden):
        s.register_artifact(ctx, result['build_id'], e['id'], e['epoch'], content=b'secret raw',
                            artifact_type='raw', content_type='text/html', access_class='page')


def test_ambiguous_source_and_distinct_owner(setup):
    s, ctx, admin = setup
    first = upload(s, ctx)
    with transaction(admin) as c:
        second = insert(c, m.problems, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id, primary_source_id=first['source_id'])
        insert(c, m.problem_sources, workspace_id=ctx.workspace_id, problem_id=second['id'], source_id=first['source_id'], match_method='manual')
        other = insert(c, m.users, key=uuid4().hex, display_name='other')
        insert(c, m.workspace_members, workspace_id=ctx.workspace_id, user_id=other['id'], role='member')
    content = BytesIO(); Image.new('RGB', (4, 4)).save(content, format='PNG')
    batch = s.create_batch(ctx)
    result = s.reference_upload(ctx, batch['id'], content.getvalue(), 'again.png', 'image/png')
    assert result['status'] == 'ambiguous' and len(result['candidate_ids']) == 2
    another = upload(s, UserContext(ctx.workspace_id, other['id']))
    assert another['problem_id'] not in (first['problem_id'], second['id'])
    other_ctx = UserContext(ctx.workspace_id, other['id'])
    assert [p['id'] for p in s.list_problems(other_ctx)] == [another['problem_id']]
    with pytest.raises(Forbidden): s.get_problem(other_ctx, first['problem_id'])
    with transaction(admin) as c:
        c.execute(m.problems.update().where(m.problems.c.id == first['problem_id']).values(visibility='workspace'))
    assert s.get_problem(other_ctx, first['problem_id'])['visibility'] == 'workspace'


def test_missing_stage_prevents_page_success(setup, domain):
    s, ctx, _ = setup
    item = upload(s, ctx)
    r = s.save_revision(ctx, item['problem_id'], None, domain)
    result = submit(s, ctx, item, r['id'])
    e = s.acquire_execution(ctx, result['job_id'], 'worker', deployment_version='test-v1')
    with pytest.raises(IntegrityFailure):
        s.finish_page(ctx, result['build_id'], e['id'], e['epoch'], entry_artifact_id=uuid4(), package_manifest_artifact_id=uuid4(), assets={})


def test_file_survives_database_rollback_as_reported_orphan(setup):
    s, ctx, _ = setup
    aid, sid = uuid4(), uuid4()
    key = f'workspaces/{ctx.workspace_id}/sources/{sid}/{aid}'
    stored = s.storage.put_immutable(key, BytesIO(b'orphan fault injection'))
    with pytest.raises(RuntimeError), transaction(s.db) as c:
        s.artifacts.register(dict(id=aid, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id,
            artifact_type='source_original', storage_key=key, sha256=stored.sha256,
            size_bytes=stored.size_bytes, content_type='image/png', access_class='private'), c)
        raise RuntimeError('rollback after file registration')
    with transaction(s.db) as c:
        assert row(c, m.artifacts, id=aid) is None
    assert key in s.storage.orphan_report([])


def test_reused_attempt_references_original_call(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    first = submit(s, ctx, item)
    e = s.acquire_execution(ctx, first['job_id'], 'worker', deployment_version='test-v1')
    args = (ctx, first['build_id'], e['id'], e['epoch'])
    attempt = s.begin_stage(*args, 'source')
    def artifact(content, kind):
        return s.register_artifact(*args, content=json.dumps(content).encode(), artifact_type=kind, content_type='application/json', attempt_id=attempt['id'])
    audit = artifact({'provider': 'offline-fixture', 'usage': {'input': 7}}, 'call_audit')
    call = s.record_call(*args, attempt['id'], audit['id'], call_kind='test', status='succeeded', input_tokens=7)
    manifest = artifact(dict(stage_key='source', contract_version='v1', inputs={}, resources={'test': 'v1'}, config={}, upstream={}), 'manifest')
    checkpoint = artifact({'offline': True}, 'checkpoint')
    accepted = s.commit_stage(*args, 'source', attempt_id=attempt['id'], manifest_artifact_id=manifest['id'],
                             checkpoint_artifact_id=checkpoint['id'], outputs=[{'artifact_id': checkpoint['id'], 'name': 'checkpoint'}])
    second = submit(s, ctx, item, parent_build_id=first['build_id'])
    e2 = s.acquire_execution(ctx, second['job_id'], 'worker2', deployment_version='test-v1')
    reused = s.commit_stage(ctx, second['build_id'], e2['id'], e2['epoch'], 'source',
        manifest_artifact_id=manifest['id'], checkpoint_artifact_id=checkpoint['id'], outputs=[{'artifact_id': checkpoint['id'], 'name': 'checkpoint'}], reused_from_attempt_id=accepted['id'])
    assert reused['kind'] == 'reused'
    with transaction(s.db) as c:
        assert c.scalar(select(func.count()).select_from(m.model_calls).where(m.model_calls.c.workspace_id == ctx.workspace_id)) == 1
        assert row(c, m.stage_call_refs, stage_attempt_id=reused['id'], model_call_id=call['id'])['relation'] == 'reused'
        assert row(c, m.stage_artifacts, stage_attempt_id=reused['id'], artifact_id=checkpoint['id'])['reused_from_artifact_id'] == checkpoint['id']
    # Corrupted original checkpoint must block any further reuse.
    checkpoint_path = s.storage.root / checkpoint['storage_key']
    original = checkpoint_path.read_bytes()
    try:
        checkpoint_path.write_bytes(b'corrupt fault injection')
        third = submit(s, ctx, item)
        e3 = s.acquire_execution(ctx, third['job_id'], 'worker3', deployment_version='test-v1')
        with pytest.raises(IntegrityFailure):
            s.commit_stage(ctx, third['build_id'], e3['id'], e3['epoch'], 'source', manifest_artifact_id=manifest['id'],
                checkpoint_artifact_id=checkpoint['id'], outputs=[], reused_from_attempt_id=accepted['id'])
    finally:
        checkpoint_path.write_bytes(original)


def running_build(s, ctx, item, revision_id=None, **options):
    build = submit(s, ctx, item, revision_id, **options)
    execution = s.acquire_execution(ctx, build['job_id'], 'regression', deployment_version='test-v1')
    return build, (ctx, build['build_id'], execution['id'], execution['epoch'])


def stage_materials(s, args, stage_key='source'):
    attempt = s.begin_stage(*args, stage_key)
    def artifact(value, kind):
        return s.register_artifact(*args, attempt_id=attempt['id'], content=json.dumps(value).encode(),
                                   artifact_type=kind, content_type='application/json')['id']
    manifest = artifact(dict(stage_key=stage_key, contract_version='v1', inputs={}, resources={'test': 'v1'}, config={}, upstream={}), 'manifest')
    checkpoint = artifact({'fixture': True}, 'checkpoint')
    html = s.register_artifact(*args, attempt_id=attempt['id'], content=b'<!doctype html><title>Fixture</title>',
                              artifact_type='page_html', content_type='text/html', access_class='page')['id']
    return attempt, dict(manifest_artifact_id=manifest, checkpoint_artifact_id=checkpoint,
                         outputs=[{'artifact_id': html, 'name': 'page_html'}])


@pytest.mark.parametrize('foreign_problem', [False, True])
@pytest.mark.parametrize('field', ['manifest_artifact_id', 'checkpoint_artifact_id', 'output'])
def test_executed_stage_rejects_foreign_build_artifacts(setup, foreign_problem, field):
    s, ctx, admin = setup
    item = upload(s, ctx)
    _, first_args = running_build(s, ctx, item)
    _, foreign = stage_materials(s, first_args)
    if foreign_problem:
        with transaction(admin) as c:
            p = insert(c, m.problems, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id, primary_source_id=item['source_id'])
            insert(c, m.problem_sources, workspace_id=ctx.workspace_id, problem_id=p['id'], source_id=item['source_id'], match_method='manual')
        item = {**item, 'problem_id': p['id']}
    build, args = running_build(s, ctx, item)
    attempt, local = stage_materials(s, args)
    bad = {**local, field: foreign[field]} if field != 'output' else {**local, 'outputs': foreign['outputs']}
    with pytest.raises(Conflict, match='artifact.producer_mismatch'):
        s.commit_stage(*args, 'source', **bad)
    with transaction(s.db) as c:
        assert row(c, m.stage_attempts, id=attempt['id'])['status'] == 'running'
        assert row(c, m.build_stages, build_id=build['build_id'], stage_key='source')['accepted_attempt_id'] is None
    with pytest.raises(IntegrityFailure):
        s.finish_page(*args, entry_artifact_id=foreign['outputs'][0]['artifact_id'], package_manifest_artifact_id=uuid4(), assets={})


def test_attempt_ownership_implicit_commit_and_replay(setup):
    s, ctx, _ = setup
    _, args = running_build(s, ctx, upload(s, ctx))
    old, old_materials = stage_materials(s, args)
    s.fail_stage(*args, old['id'], 'test.retry')
    current, materials = stage_materials(s, args)
    with pytest.raises(Conflict, match='artifact.producer_mismatch'):
        s.commit_stage(*args, 'source', **old_materials)
    accepted = s.commit_stage(*args, 'source', **materials)
    assert accepted['id'] == current['id']
    assert s.commit_stage(*args, 'source', **materials)['id'] == accepted['id']
    with pytest.raises(Conflict): s.commit_stage(*args, 'source', **{**materials, 'outputs': []})
    with transaction(s.db) as c:
        attempts = list(c.execute(select(m.stage_attempts).where(m.stage_attempts.c.build_stage_id == current['build_stage_id'])).mappings())
        assert len(attempts) == 2 and {a['status'] for a in attempts} == {'failed', 'succeeded'}


def test_registration_requires_live_matching_attempt(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    _, args = running_build(s, ctx, item)
    _, other_args = running_build(s, ctx, item)
    other = s.begin_stage(*other_args, 'source')
    for attempt_id in (None, other['id']):
        with pytest.raises(Conflict):
            s.register_artifact(*args, attempt_id=attempt_id, content=b'{}', artifact_type='checkpoint', content_type='application/json')
    with pytest.raises(Conflict, match='stage.attempt_required'):
        s.commit_stage(*args, 'source', manifest_artifact_id=uuid4(), checkpoint_artifact_id=uuid4(), outputs=[])


def test_reuse_only_accepts_complete_source_outputs(setup):
    s, ctx, _ = setup
    item = upload(s, ctx)
    _, args = running_build(s, ctx, item)
    _, material = stage_materials(s, args)
    old = s.commit_stage(*args, 'source', **material)
    _, new_args = running_build(s, ctx, item)
    for outputs in ([], [{**material['outputs'][0], 'name': 'mislabelled'}]):
        with pytest.raises(IntegrityFailure, match='stage.reuse_outputs_mismatch'):
            s.commit_stage(*new_args, 'source', **{**material, 'outputs': outputs}, reused_from_attempt_id=old['id'])
    attempt = s.begin_stage(*new_args, 'source')
    with pytest.raises(Conflict, match='stage.reuse_while_running'):
        s.commit_stage(*new_args, 'source', **material, reused_from_attempt_id=old['id'])
    s.fail_stage(*new_args, attempt['id'], 'use-recovery-instead')
    reused = s.commit_stage(*new_args, 'source', **material, reused_from_attempt_id=old['id'])
    _, third_args = running_build(s, ctx, item)
    assert s.commit_stage(*third_args, 'source', **material, reused_from_attempt_id=reused['id'])['kind'] == 'reused'


@pytest.mark.parametrize('changed', [False, True])
def test_extraction_binds_final_revision_with_existing_base(setup, domain, changed):
    s, ctx, _ = setup
    item = upload(s, ctx)
    base = s.save_revision(ctx, item['problem_id'], None, domain)
    build, args = running_build(s, ctx, item, base['id'])
    snapshot = s.build_snapshot(ctx, build['build_id'])['build']
    assert snapshot['requested_revision_id'] == base['id'] and snapshot['resolved_revision_id'] is None
    target = deepcopy(domain)
    if changed: target['root']['source_text'][0] += '（重新提取）'
    result = s.save_revision(ctx, item['problem_id'], base['id'], target,
                             origin_build_id=build['build_id'], execution_id=args[2], epoch=args[3])
    assert (result['id'] != base['id']) == changed
    assert s.build_snapshot(ctx, build['build_id'])['build']['resolved_revision_id'] == result['id']
    if changed:
        assert result['kind'] == 'extracted' and result['human_diff'] is None and result['parent_revision_id'] == base['id']
        with pytest.raises(Conflict, match='build.revision_already_bound'): s.bind_requested_revision(*args)
    else:
        assert s.bind_requested_revision(*args)['id'] == base['id']
    with transaction(s.db) as c:
        assert c.scalar(select(func.count()).select_from(m.problem_revisions).where(m.problem_revisions.c.problem_id == item['problem_id'])) == (2 if changed else 1)
    assert [e['event_type'] for e in s.read_events(ctx, 'build', build['build_id'])].count('build.revision_bound') == 1


def test_noop_revision_still_checks_execution_and_build_ownership(setup, domain):
    s, ctx, _ = setup
    item = upload(s, ctx)
    base = s.save_revision(ctx, item['problem_id'], None, domain)
    build, args = running_build(s, ctx, item, base['id'])
    with pytest.raises(Conflict):
        s.save_revision(ctx, item['problem_id'], base['id'], domain,
                        origin_build_id=build['build_id'], execution_id=args[2], epoch=args[3] + 1)
    submit(s, ctx, item, base['id'])
    with pytest.raises(Conflict, match='revision.extraction_superseded'):
        s.save_revision(ctx, item['problem_id'], base['id'], domain,
                        origin_build_id=build['build_id'], execution_id=args[2], epoch=args[3])
    assert s.build_snapshot(ctx, build['build_id'])['build']['resolved_revision_id'] is None


def test_concurrent_requested_revision_binding_is_idempotent(setup, domain):
    s, ctx, _ = setup
    item = upload(s, ctx)
    base = s.save_revision(ctx, item['problem_id'], None, domain)
    build, args = running_build(s, ctx, item, base['id'])
    with ThreadPoolExecutor(3) as pool:
        revisions = list(pool.map(lambda _: s.bind_requested_revision(*args)['id'], range(3)))
    assert revisions == [base['id']] * 3
    assert [e['event_type'] for e in s.read_events(ctx, 'build', build['build_id'])].count('build.revision_bound') == 1


def test_expired_execution_artifacts_cannot_be_claimed_by_new_attempt(setup):
    s, ctx, admin = setup
    build, args = running_build(s, ctx, upload(s, ctx))
    old, material = stage_materials(s, args)
    with transaction(admin) as c:
        c.execute(m.jobs.update().where(m.jobs.c.id == build['job_id']).values(lease_expires_at=func.now() - text("interval '1 second'")))
    new = s.acquire_execution(ctx, build['job_id'], 'replacement', deployment_version='test-v1')
    new_args = (ctx, build['build_id'], new['id'], new['epoch'])
    assert s.build_snapshot(ctx, build['build_id'])['stages'][0]['status'] == 'interrupted'
    s.begin_stage(*new_args, 'source')
    with pytest.raises(Conflict, match='artifact.producer_mismatch'):
        s.commit_stage(*new_args, 'source', **material)
    with transaction(s.db) as c:
        assert row(c, m.stage_attempts, id=old['id'])['status'] == 'interrupted'


@pytest.mark.parametrize('interrupted', [False, True])
def test_failure_closes_stages_and_preserves_success(setup, interrupted):
    s, ctx, _ = setup
    build, args = running_build(s, ctx, upload(s, ctx))
    _, material = stage_materials(s, args)
    s.commit_stage(*args, 'source', **material)
    attempt = s.begin_stage(*args, 'observation')
    s.finish_failure(*args, 'test.failure', interrupted=interrupted)
    expected = 'interrupted' if interrupted else 'failed'
    snapshot = s.build_snapshot(ctx, build['build_id'])
    assert snapshot['build']['status'] == expected
    assert [x['status'] for x in snapshot['stages']] == ['succeeded'] + [expected] * 8
    with transaction(s.db) as c:
        assert row(c, m.stage_attempts, id=attempt['id'])['status'] == expected


def test_exhausted_delivery_closes_stages(setup):
    s, ctx, admin = setup
    build, args = running_build(s, ctx, upload(s, ctx), retry_budget={'deliveries': 1})
    s.begin_stage(*args, 'source')
    with transaction(admin) as c:
        c.execute(m.jobs.update().where(m.jobs.c.id == build['job_id']).values(lease_expires_at=func.now() - text("interval '1 second'")))
    assert s.acquire_execution(ctx, build['job_id'], 'retry', deployment_version='test-v1')['status'] == 'failed'
    assert {stage['status'] for stage in s.build_snapshot(ctx, build['build_id'])['stages']} == {'failed'}
