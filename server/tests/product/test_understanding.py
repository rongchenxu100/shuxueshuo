"""Real PostgreSQL integration for candidate retention and at-most-once model calls."""
import json
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.api import create_app
from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import Conflict, Forbidden
from shuxueshuo_server.product.execution import ExecutionContext
from shuxueshuo_server.product.repositories import UserContext, row
from shuxueshuo_server.product.understanding import Understanding
from shuxueshuo_server.product.understanding_runtime import run_product
from shuxueshuo_server.product.understanding_storage import (
    DatabaseLedger,
    DatabaseWorkflowStorage,
)

ROOT = Path(__file__).resolve().parents[3]
RECORDINGS = Path(__file__).parent / 'fixtures/math-notation-state-facts-seven-20260917'
IMAGES = ROOT / 'server/tests/solver/fixtures/math-notation-v1/integration-images-20260916'
CASES = ['tj-2026-heping-yimo-25', 'tj-2026-heping-ermo-25', 'tj-2026-hexi-yimo-25',
         'tj-2026-nankai-yimo-25', 'tj-2026-xiqing-yimo-25', 'k-quad', 'function-quantifiers']
OK = {'status': 'confirmed', 'findings': []}


def candidate(facts=None, **root):
    return {'root': {'facts': facts or ['t>0'], **root}, 'match_status': 'unmatched', 'family_id': None, 'match_reason': '独立测试'}


class Recorded:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def prepare_request(self, request):
        return replace(request, timeout=300, max_tokens=16384)

    def complete(self, request):
        self.requests.append(request)
        value = self.responses.pop(0)
        if isinstance(value, BaseException):
            raise value
        raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        usage = {'prompt_tokens': 10, 'completion_tokens': 5, 'completion_tokens_details': {'reasoning_tokens': 2}}
        return SimpleNamespace(text=raw, finish_reason='stop', provider_attempts=({'usage': usage},), raw_payload={'recorded': True},
            metadata_payload=lambda: {'provider': 'recorded', 'request_model': 'recorded', 'usage': usage})


@pytest.fixture
def app(setup, settings, tmp_path, monkeypatch):
    service, ctx, _admin = setup
    monkeypatch.setattr('shuxueshuo_server.product.application.deployment_version', lambda *args: 'understanding-test')
    application = Application(replace(settings, root=tmp_path), service, ctx)
    (tmp_path / 'locks').mkdir()
    return application


def create(a, case=None):
    if case:
        content = (IMAGES / f'{case}.png').read_bytes()
    else:
        image = BytesIO()
        Image.new('RGB', (12, 12), 'white').save(image, format='PNG')
        content = image.getvalue()
    batch = a.create_batch(uuid4().hex)
    upload = a.upload(UUID(batch['id']), uuid4().hex, content, '题目.png', 'image/png')
    pid, sid = UUID(upload['item']['problem_id']), UUID(upload['item']['source_id'])
    u = Understanding(a)
    source = u.source_version(pid, None, [sid], uuid4().hex)
    return u, pid, UUID(source['id'])


def begin(a, pid, source, base=None, mode='extract'):
    result = Understanding(a).start(pid, source, base, mode, uuid4().hex)
    execution = a.service.acquire_execution(a.ctx, UUID(result['job_id']), 'recorded-worker', deployment_version='understanding-test', lease_seconds=300)
    x = ExecutionContext(a, a.ctx, UUID(result['build_id']), execution['id'], execution['epoch'])
    return result, x


@pytest.mark.parametrize('case', CASES)
def test_seven_recorded_outputs_are_saved_and_reviewed(app, case):
    u, pid, source = create(app, case)
    responses = [p.read_text() for p in sorted(RECORDINGS.glob(f'{case}.*.txt'))]
    recorded = Recorded(responses)
    submitted, x = begin(app, pid, source)
    result = run_product(x, recorded)
    summary = u.summary(pid)
    assert summary['candidate']['candidate_json'] == json.loads(responses[0])
    assert summary['candidate_only'] and not summary['solver_ready']
    assert summary['source_reviewed'] == (case != 'k-quad')
    assert result['status'] == ('needs_confirmation' if case == 'k-quad' else 'reviewed_candidate')
    if case in ('k-quad', 'function-quantifiers'):
        assert summary['match_status'] == 'unmatched'
    detail = app.get_problem(pid)
    presentation = detail['presentation']
    expected = 'needs_confirmation' if case == 'k-quad' else 'unsupported' if case == 'function-quantifiers' else 'ready'
    assert presentation['status'] == expected
    assert presentation['phase'] == 'understanding'
    # Frozen responses predate original_text. Do not invent it from their IR.
    assert presentation['title_kind'] == 'image'
    assert presentation['title'] == '原题文字待提取'
    assert presentation['result_id'] == submitted['run_id']
    assert detail['statement_text'] is None
    assert '题目.png' not in presentation['title']
    if case == 'k-quad':
        assert presentation['reason'] == 'missing_figure'  # Takes precedence over unmatched.
    assert app.list_problems()[0]['presentation'] == presentation
    assert detail['updated_at'] >= u.run(UUID(submitted['run_id']))['finished_at']
    assert len(recorded.requests) == (1 if case == 'k-quad' else 2)
    assert len(u.run(UUID(submitted['run_id']))['calls']) == len(recorded.requests)
    with transaction(app.db) as c:
        p = row(c, m.problems, id=pid)
        assert p['current_revision_id'] is p['current_page_build_id'] is p['latest_build_id'] is None
        stages = c.execute(select(m.build_stages.c.stage_key).where(m.build_stages.c.build_id == x.build['id'])).scalars().all()
        assert sorted(stages) == ['extraction', 'source']
        assert row(c, m.builds, id=x.build['id'])['status'] == 'succeeded'
    for request in recorded.requests:
        assert len(request.images) == 1
        wire = request.prompt.system + request.prompt.user_prefix + request.prompt.user_suffix
        assert 'gold' not in wire and 'source_text' not in json.dumps(request.contract_schema)


def test_manual_edit_retains_parse_error_and_invalidates_review(app):
    u, pid, source = create(app)
    _, x = begin(app, pid, source)
    run_product(x, Recorded([candidate(), OK]))
    old = u.summary(pid)['candidate']
    changed = candidate(['t+'])
    new = u.save_candidate(pid, UUID(old['id']), source, changed, 'edit-once')
    assert not new['validation_json']['contract_valid']
    assert u.candidate(pid, UUID(new['id']))['diagnostics'][0]['path'] == '/root/facts/0'
    assert not u.summary(pid)['source_reviewed']
    assert app.get_problem(pid)['presentation']['status'] == 'needs_revision'
    assert app.get_problem(pid)['presentation']['result_id'] is None
    assert u.save_candidate(pid, UUID(old['id']), source, changed, 'edit-once')['id'] == new['id']
    assert len(u.candidates(pid)['candidates']) == 2
    assert u.candidate(pid, UUID(new['id']))['parent_candidate_json'] == old['candidate_json']


def test_manual_candidate_and_idempotency_receipt_rollback_together(app, monkeypatch):
    from shuxueshuo_server.product import application
    u, pid, source = create(app)
    written = []
    original_put = app.service.storage.put_immutable
    def capture(key, *args, **kwargs):
        written.append(key)
        return original_put(key, *args, **kwargs)
    monkeypatch.setattr(app.service.storage, 'put_immutable', capture)
    original_insert = application.insert
    def fail_receipt(c, table, **values):
        if table is m.idempotency_requests:
            raise RuntimeError('injected before idempotency receipt')
        return original_insert(c, table, **values)
    with transaction(app.db) as c:
        before = dict(row(c, m.problems, id=pid))
        events_before = c.scalar(select(func.count()).select_from(m.events).where(m.events.c.workspace_id == app.ctx.workspace_id))
    monkeypatch.setattr(application, 'insert', fail_receipt)
    with pytest.raises(RuntimeError, match='injected before idempotency receipt'):
        u.save_candidate(pid, None, source, candidate(), 'atomic-edit')
    assert not u.candidates(pid)['candidates']
    with transaction(app.db) as c:
        after = row(c, m.problems, id=pid)
        assert after['current_candidate_id'] is None
        assert after['understanding_generation'] == before['understanding_generation']
        assert c.scalar(select(func.count()).select_from(m.events).where(m.events.c.workspace_id == app.ctx.workspace_id)) == events_before
        assert row(c, m.idempotency_requests, workspace_id=app.ctx.workspace_id, operation='understanding.candidate', request_id='atomic-edit') is None
    first_keys = written[:]
    assert first_keys  # Files were written before the database transaction rolled back.
    monkeypatch.setattr(application, 'insert', original_insert)
    saved = u.save_candidate(pid, None, source, candidate(), 'atomic-edit')
    assert written[len(first_keys):] == first_keys  # Retry reuses the immutable paths.
    assert u.save_candidate(pid, None, source, candidate(), 'atomic-edit') == saved
    assert len(u.candidates(pid)['candidates']) == 1
    assert len(written) == 2 * len(first_keys)
    with pytest.raises(Conflict, match='request.content_changed'):
        u.save_candidate(pid, UUID(saved['id']), source, candidate(['t=2']), 'atomic-edit')


def test_concurrent_manual_edit_replays_one_candidate(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    u, pid, source = create(app)
    ready = Barrier(2)
    def submit(_):
        ready.wait(timeout=10)
        return u.save_candidate(pid, None, source, candidate(), 'same-edit')
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    assert [c['id'] for c in u.candidates(pid)['candidates']] == [results[0]['id']]


def test_api_validation_and_source_history(app):
    u, pid, source = create(app)
    with TestClient(create_app(app)) as client:
        prefix = f'/api/product/v1/problems/{pid}'
        invalid = client.post(prefix + '/candidates', headers={'Idempotency-Key': 'bad'}, json={
            'base_candidate_id': None, 'source_version_id': str(source), 'candidate': {'at': 'old'}})
        assert invalid.status_code == 422
        assert invalid.json()['error']['details']
        valid = client.post(prefix + '/candidates', headers={'Idempotency-Key': 'good'}, json={
            'base_candidate_id': None, 'source_version_id': str(source), 'candidate': candidate()})
        assert valid.status_code == 201, valid.text
        stale = client.post(prefix + '/candidates', headers={'Idempotency-Key': 'stale'}, json={
            'base_candidate_id': None, 'source_version_id': str(source), 'candidate': candidate()})
        assert stale.status_code == 409
        image = BytesIO(); Image.new('RGB', (10, 20), 'red').save(image, format='PNG')
        upload = client.post(prefix + '/source-images', files={'image': ('图1.png', image.getvalue(), 'image/png')}, headers={'Idempotency-Key': 'supplement'})
        assert upload.status_code == 201, upload.text
        sid = upload.json()['source_id']
        original = u.summary(pid)['source_version']
        changed = client.post(prefix + '/source-versions', headers={'Idempotency-Key': 'source-new'}, json={
            'base_source_version_id': str(source), 'source_ids': [original['images'][0]['source_id'], sid]})
        assert changed.status_code == 201, changed.text
        assert changed.json()['source_hash'] != original['source_hash']
        assert u.summary(pid)['candidate'] is None
        assert app.get_problem(pid)['presentation']['status'] == 'not_started'
        assert app.get_problem(pid)['presentation']['title_kind'] == 'image'
        assert len(u.candidates(pid)['candidates']) == 1
        assert client.get(prefix + '/source-images/' + sid).content == image.getvalue()


def finding(path='/root', kind='missing_condition'):
    return {'status': 'correction_required', 'findings': [{'path': path, 'kind': kind,
        'source_excerpt': 't>1', 'message': '原图条件不一致'}]}


@pytest.mark.parametrize('responses,status,saved', [
    (['{', {}, candidate(), OK], 'reviewed_candidate', 1),
    (['{', '{}', '[]'], 'workflow.budget_exhausted', 0),
    ([candidate(), {'status': 'uncertain', 'findings': finding()['findings']}], 'needs_confirmation', 1),
    ([candidate(), {'status': 'confirmed', 'findings': finding()['findings']}], 'review.invalid_response', 1),
    ([candidate(), finding('', 'wrong_expression')], 'review.invalid_response', 1),
    ([candidate(), finding('', 'wrong_scope')], 'review.invalid_response', 1),
    ([RuntimeError('injected call failure')], 'workflow.provider_failed', 0),
    ([candidate(['Γ:y=a*x^2', 'P=axis(Γ)∩x_axis'])], 'code_gap', 1),
    ([candidate(), finding(), candidate()], 'workflow.no_progress', 2),
])
def test_failure_records_survive_without_fabricated_candidates(app, responses, status, saved):
    u, pid, source = create(app)
    submitted, x = begin(app, pid, source)
    provider = Recorded(responses)
    result = run_product(x, provider)
    assert result['status'] == status, result
    assert len(u.candidates(pid)['candidates']) == saved
    run = u.run(UUID(submitted['run_id']))
    assert len(run['calls']) == len(provider.requests)
    if status in ('workflow.budget_exhausted', 'workflow.no_progress', 'needs_confirmation', 'code_gap'):
        assert run['status'] == 'completed'
        assert run['task_status'] == 'succeeded'
        summary = u.summary(pid)
        assert not summary['source_reviewed'] and summary['formal_page'] is None
        assert summary['candidate_only'] and not summary['solver_ready']
        assert app.build(UUID(run['build_id']))['page_id'] is None
        assert not app.build(UUID(run['build_id']))['page_current']
    if status in ('workflow.provider_failed', 'review.invalid_response'):
        assert run['status'] == 'failed'
    assert all(c['response_artifact_id'] for c in run['calls'])
    with TestClient(create_app(app)) as client:
        for call in run['calls']:
            response = client.get(f'/api/product/v1/builds/{run["build_id"]}/artifacts/{call["response_artifact_id"]}')
            assert response.status_code == 200
            assert 'response' in response.json()


def test_outside_repair_is_saved_but_not_adopted(app):
    u, pid, source = create(app)
    base = candidate(children=[{'facts': ['s=2']}])
    bad = candidate(['t>0', 't>1'], children=[{'facts': ['s=9']}])
    good = candidate(['t>0', 't>1'], children=[{'facts': ['s=2']}])
    _submitted, x = begin(app, pid, source)
    result = run_product(x, Recorded([base, finding(), bad, good, OK]))
    assert result['source_reviewed']
    assert not result['events'][2]['adopted']
    assert result['events'][2]['change_guard']['violations']
    values = u.candidates(pid)['candidates']
    assert len(values) == 3 and any(c['candidate_json'] == bad for c in values)
    assert u.summary(pid)['candidate']['candidate_json'] == good


def test_validate_and_review_start_from_saved_candidate_without_extract(app):
    u, pid, source = create(app)
    value = u.save_candidate(pid, None, source, candidate(), 'manual')
    _, x = begin(app, pid, source, UUID(value['id']), 'validate')
    provider = Recorded([])
    result = run_product(x, provider)
    assert result['status'] == 'validated_candidate' and not provider.requests
    assert not u.summary(pid)['source_reviewed']
    _, x = begin(app, pid, source, UUID(value['id']), 'review')
    provider = Recorded([OK])
    result = run_product(x, provider)
    assert result['source_reviewed'] and [e['stage'] for e in result['events']] == ['review']
    assert len(u.candidates(pid)['candidates']) == 1


class Crash(BaseException):
    pass


def resume(a, submitted, x):
    a.service.finish_failure(*x.args, 'injected.interruption', interrupted=True)
    execution = a.service.acquire_execution(a.ctx, UUID(submitted['job_id']), 'resumed-worker', deployment_version='understanding-test', lease_seconds=300)
    return ExecutionContext(a, a.ctx, x.build['id'], execution['id'], execution['epoch'])


@pytest.mark.parametrize('boundary', ['reserved', 'receipt', 'registered', 'checkpoint'])
def test_recovery_never_resends_a_reserved_or_completed_call(app, monkeypatch, boundary):
    u, pid, source = create(app)
    submitted, x = begin(app, pid, source)
    provider = Recorded([candidate(), OK])
    if boundary == 'reserved':
        provider.responses = [Crash()]
    elif boundary == 'receipt':
        original = DatabaseLedger.finish
        def crash(self, entry, receipt):
            raise Crash()
        monkeypatch.setattr(DatabaseLedger, 'finish', crash)
    elif boundary == 'registered':
        original = DatabaseWorkflowStorage.proposed
        monkeypatch.setattr(DatabaseWorkflowStorage, 'proposed', lambda *args: (_ for _ in ()).throw(Crash()))
    else:
        from shuxueshuo_server.product import understanding_runtime as runtime
        original = runtime.finish_product
        monkeypatch.setattr(runtime, 'finish_product', lambda *args: (_ for _ in ()).throw(Crash()))
    with pytest.raises(Crash):
        run_product(x, provider)
    first_calls = len(provider.requests)
    if boundary == 'receipt': monkeypatch.setattr(DatabaseLedger, 'finish', original)
    if boundary == 'registered': monkeypatch.setattr(DatabaseWorkflowStorage, 'proposed', original)
    if boundary == 'checkpoint': monkeypatch.setattr(runtime, 'finish_product', original)
    recovered = Recorded([OK] if boundary in ('receipt', 'registered') else [])
    result = run_product(resume(app, submitted, x), recovered)
    if boundary == 'reserved':
        assert result['status'] == 'workflow.outcome_unknown' and not recovered.requests
    else:
        assert result['source_reviewed']
        assert first_calls + len(recovered.requests) == 2
    run = u.run(UUID(submitted['run_id']))
    assert len(run['calls']) == (1 if boundary == 'reserved' else 2)
    with pytest.raises(Conflict):
        app.service.acquire_execution(app.ctx, UUID(submitted['job_id']), 'duplicate', deployment_version='understanding-test')


def test_late_response_is_audited_but_cannot_overwrite_manual_revision(app):
    u, pid, source = create(app)
    submitted, x = begin(app, pid, source)
    class Late(Recorded):
        def complete(self, request):
            self.edited = u.save_candidate(pid, None, source, candidate(['t=99']), 'new-manual')
            return super().complete(request)
    provider = Late([candidate()])
    # The old job is fenced after the external response. Audit still completes.
    with pytest.raises((Conflict, ValueError)):
        run_product(x, provider)
    summary = u.summary(pid)
    assert summary['candidate']['id'] == provider.edited['id']
    assert [c['id'] for c in u.candidates(pid)['candidates']] == [provider.edited['id']]
    run = u.run(UUID(submitted['run_id']))
    assert run['status'] == 'superseded'
    assert run['calls'][0]['response_artifact_id'] and len(provider.requests) == 1


@pytest.mark.parametrize('invalidate', ['source', 'new_run', 'cancel'])
def test_late_response_after_invalidation_is_only_an_audit_record(app, invalidate):
    u, pid, source = create(app)
    original = u.summary(pid)['source_version']['images'][0]['source_id']
    extra = BytesIO()
    Image.new('RGB', (20, 10), 'blue').save(extra, format='PNG')
    sid = UUID(u.upload(pid, extra.getvalue(), 'extra.png', 'image/png', 'extra')['source_id'])
    submitted, x = begin(app, pid, source)
    replacement = []
    class Late(Recorded):
        def complete(self, request):
            if invalidate == 'source':
                u.source_version(pid, source, [UUID(original), sid], 'supplement')
            elif invalidate == 'new_run':
                replacement.append(u.start(pid, source, None, 'extract', 'replacement'))
            else:
                app.service.cancel(app.ctx, x.build['id'])
            return super().complete(request)
    try:
        provider = Late([candidate()])
        with pytest.raises((Conflict, ValueError)):
            run_product(x, provider)
        assert not u.candidates(pid)['candidates']
        assert u.summary(pid)['candidate'] is None
        run = u.run(UUID(submitted['run_id']))
        assert run['status'] == ('cancelled' if invalidate == 'cancel' else 'superseded')
        assert len(provider.requests) == len(run['calls']) == 1
        call = run['calls'][0]
        assert call['response_artifact_id']
        with TestClient(create_app(app)) as client:
            response = client.get(f'/api/product/v1/builds/{run["build_id"]}/artifacts/{call["response_artifact_id"]}')
            assert response.status_code == 200
            assert json.loads(response.json()['response']['text']) == candidate()
    finally:
        for new in replacement:
            app.service.cancel(app.ctx, UUID(new['build_id']))


def test_image_set_order_review_binding_and_request_isolation(app):
    u, pid, source = create(app)
    first = u.summary(pid)['source_version']
    image = BytesIO(); Image.new('RGB', (15, 20), 'blue').save(image, format='PNG')
    sid = UUID(u.upload(pid, image.getvalue(), 'extra.png', 'image/png', 'extra')['source_id'])
    second = u.source_version(pid, source, [UUID(first['images'][0]['source_id']), sid], 'extra-source')
    reversed_source = u.source_version(pid, UUID(second['id']), [sid, UUID(first['images'][0]['source_id'])], 'reverse')
    assert len({first['source_hash'], second['source_hash'], reversed_source['source_hash']}) == 3
    _submitted, x = begin(app, pid, UUID(reversed_source['id']))
    provider = Recorded([candidate(), OK])
    result = run_product(x, provider)
    assert result['source_reviewed']
    for req in provider.requests:
        assert [i.artifact.sha256 for i in req.images] == [i['sha256'] for i in reversed_source['images']]
        assert req.evidence_pack.source_revision_hash == reversed_source['source_hash']
        assert req.evidence_pack.printed_text == req.evidence_pack.recognized_formulas == ()
        assert 'frozen_gold' not in req.prompt.user_prefix
        assert 'expected_missing_figures' not in req.prompt.user_prefix
    u.source_version(pid, UUID(reversed_source['id']), [sid], 'third')
    assert u.summary(pid)['candidate'] is None and not u.summary(pid)['source_reviewed']
    assert len(u.candidates(pid)['candidates']) == 1
    assert u.candidate(pid, UUID(u.candidates(pid)['candidates'][0]['id']))['source_version']['id'] == reversed_source['id']


def test_immutable_history_permissions_and_workspace_boundaries(app, setup):
    service, ctx, admin = setup
    u, pid, source = create(app)
    value = u.save_candidate(pid, None, source, candidate(), 'manual')
    for connection in (service.db, admin):
        for statement in (m.problem_source_versions.update().where(m.problem_source_versions.c.id == source).values(images=[]),
                          m.problem_candidates.update().where(m.problem_candidates.c.id == UUID(value['id'])).values(candidate_json={})):
            with pytest.raises(DBAPIError), transaction(connection) as c:
                c.execute(statement)
    outsider = Understanding(Application(app.settings, service, UserContext(uuid4(), ctx.user_id)))
    with pytest.raises(Forbidden): outsider.summary(pid)


def test_same_problem_concurrent_runs_have_one_winner_and_bounded_slots(app):
    from concurrent.futures import ThreadPoolExecutor
    u, pid, source = create(app)
    with ThreadPoolExecutor(2) as pool:
        runs = list(pool.map(lambda _: u.start(pid, source, None, 'extract', uuid4().hex), range(2)))
    assert len([r for r in runs if u.run(UUID(r['run_id']))['status'] == 'queued']) == 1
    latest = u.summary(pid)['latest_run']
    with transaction(app.db) as c:
        job = row(c, m.jobs, build_id=UUID(latest['build_id']))
    app.service.acquire_execution(app.ctx, job['id'], 'winner', deployment_version='understanding-test', lease_seconds=300)
    with pytest.raises(Conflict, match='execution.already_owned'):
        app.service.acquire_execution(app.ctx, job['id'], 'duplicate', deployment_version='understanding-test')
    app.service.cancel(app.ctx, UUID(latest['build_id']))


def test_global_understanding_concurrency_is_capped_at_three(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from shuxueshuo_server.product.repositories import insert
    # Distinct questions in this workspace, even when their image bytes match.
    u, pid, _source = create(app)
    with transaction(app.db) as c:
        original = row(c, m.problems, id=pid)
    active = []
    try:
        for i in range(4):
            with transaction(app.db) as c:
                p = insert(c, m.problems, workspace_id=app.ctx.workspace_id, owner_user_id=app.ctx.user_id,
                    primary_source_id=original['primary_source_id'], title=f'Concurrency {i}', visibility='private')
                insert(c, m.problem_sources, workspace_id=app.ctx.workspace_id, problem_id=p['id'],
                    source_id=original['primary_source_id'], match_method='manual')
            s = u.source_version(p['id'], None, [original['primary_source_id']], uuid4().hex)
            submitted = u.start(p['id'], UUID(s['id']), None, 'extract', uuid4().hex)
            active.append(submitted)
        ready = Barrier(4)
        def acquire(submitted):
            ready.wait(timeout=10)
            try:
                app.service.acquire_execution(app.ctx, UUID(submitted['job_id']), 'slot-test', deployment_version='understanding-test', lease_seconds=300)
                return 'acquired'
            except Conflict as error:
                assert str(error) == 'execution.capacity'
                return 'capacity'
        with ThreadPoolExecutor(4) as pool:
            assert sorted(pool.map(acquire, active)) == ['acquired'] * 3 + ['capacity']
    finally:
        for submitted in active: app.service.cancel(app.ctx, UUID(submitted['build_id']))


def test_atomic_reservation_prevents_concurrent_paid_sends(app):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from shuxueshuo_server.problem_understanding.workflow_ledger import (
        Budget,
        WorkflowStop,
    )
    from shuxueshuo_server.product.understanding_runtime import build_request
    u, pid, source = create(app)
    submitted, x = begin(app, pid, source)
    x.begin('source'); x.add('source-version.json', u.summary(pid)['source_version']); x.complete('source')
    x.begin('extraction')
    with transaction(app.db) as c:
        run = dict(row(c, m.extraction_runs, id=UUID(submitted['run_id'])))
    request = build_request(app.service, app.ctx, u.summary(pid)['source_version'], run['frozen']['registry'])
    entered, release = Event(), Event()
    class Paused(Recorded):
        def complete(self, request):
            entered.set(); assert release.wait(10)
            return super().complete(request)
    provider = Paused([candidate()])
    store = DatabaseWorkflowStorage(x, run)
    first, second = DatabaseLedger(store, {}, Budget()), DatabaseLedger(store, {}, Budget())
    with ThreadPoolExecutor(2) as pool:
        result = pool.submit(first.complete, 'extract', request, None, provider)
        assert entered.wait(10)
        try:
            with pytest.raises(WorkflowStop, match='workflow.outcome_unknown'):
                second.complete('extract', request, None, provider)
        finally: release.set()
        assert result.result()['text']
    assert len(provider.requests) == 1
    app.service.cancel(app.ctx, x.build['id'])


def test_database_budget_enforces_six_calls_twelve_network_attempts(app):
    u, pid, source = create(app)
    submitted, x = begin(app, pid, source)
    a, b, c = (candidate([f't={i}']) for i in (1, 2, 3))
    wrong = finding('/root/facts/0', 'wrong_expression')
    class TwoAttempts(Recorded):
        def complete(self, request):
            result = super().complete(request)
            result.provider_attempts = ({}, {})
            return result
    result = run_product(x, TwoAttempts([a, wrong, b, wrong, c, wrong]))
    assert result['status'] == 'workflow.budget_exhausted'
    assert result['semantic_calls'] == 6 and result['network_attempts'] == 12
    assert len(u.run(UUID(submitted['run_id']))['calls']) == 6


def test_manual_compilation_artifacts_are_linked_downloadable_and_private(app):
    u, pid, source = create(app)
    value = u.save_candidate(pid, None, source, candidate(), 'manual')
    artifacts = value['validation_json']['artifacts']
    assert {'normalized', 'compiled', 'validation', 'raw'} <= set(artifacts)
    with TestClient(create_app(app)) as client:
        prefix = f'/api/product/v1/problems/{pid}/candidates/{value["id"]}/artifacts/'
        content = client.get(prefix + artifacts['compiled']['artifact_id'])
        assert content.status_code == 200 and content.json()['complete']
        assert client.get(prefix + str(uuid4())).status_code == 403


def test_review_configuration_change_invalidates_confirmation(app, monkeypatch):
    from shuxueshuo_server.product import understanding_runtime as runtime
    u, pid, source = create(app)
    _, x = begin(app, pid, source)
    run_product(x, Recorded([candidate(), OK]))
    assert u.summary(pid)['source_reviewed']
    assert u.summary(pid)['review_stale_reason'] is None
    # An unrelated deployment version does not change the extraction/review configuration.
    monkeypatch.setattr('shuxueshuo_server.product.application.deployment_version', lambda *args: 'frontend-only-update')
    assert u.summary(pid)['source_reviewed']
    changed = runtime.configuration()
    changed['provider']['reasoning_effort'] = 'different'
    monkeypatch.setattr(runtime, 'configuration', lambda: changed)
    assert not u.summary(pid)['source_reviewed']
    assert u.summary(pid)['source_status'] == 'stale'
    assert u.summary(pid)['review_stale_reason'] == 'configuration_changed'


def test_valid_json_with_truncated_finish_is_history_only(app):
    u, pid, source = create(app)
    _, x = begin(app, pid, source)
    class TruncatedFirst(Recorded):
        def complete(self, request):
            response = super().complete(request)
            if len(self.requests) == 1: response.finish_reason = 'length'
            return response
    original, repaired = candidate(['t=9']), candidate(['t=1'])
    result = run_product(x, TruncatedFirst([original, repaired, OK]))
    assert result['source_reviewed'] and result['candidate'] == repaired
    assert not result['events'][0]['adopted']
    assert len(u.candidates(pid)['candidates']) == 2


def test_original_text_is_saved_with_candidate_and_never_fed_as_ocr(app):
    u, pid, source = create(app)
    original = {**candidate(), 'original_text': '已知实数t>0。\n（1）求t的取值范围。'}
    _, x = begin(app, pid, source)
    recorded = Recorded([original, OK])
    run_product(x, recorded)
    saved = u.summary(pid)['candidate']
    assert saved['candidate_json'] == original
    assert u.candidate(pid, UUID(saved['id']))['candidate_json']['original_text'] == original['original_text']
    assert app.get_problem(pid)['presentation']['title'] == '已知实数t>0。 （1）求t的取值范围。'
    assert app.get_problem(pid)['presentation']['title_kind'] == 'source_text'
    assert len(recorded.requests) == 2
    for request in recorded.requests:
        assert request.evidence_pack.printed_text == ()
        assert request.evidence_pack.recognized_formulas == ()
        assert len(request.images) == 1
    assert 'ocr_hints' not in json.loads(recorded.requests[0].prompt.user_prefix)
    assert json.loads(recorded.requests[1].prompt.user_prefix)['candidate']['original_text'] == original['original_text']
    # Revision identity includes the transcription even though math compilation does not.
    changed = {**original, 'original_text': '已知参数t>0。\n（1）求t的取值范围。'}
    manual = u.save_candidate(pid, UUID(saved['id']), source, changed, uuid4().hex)
    assert manual['candidate_hash'] != saved['candidate_hash']
    assert not u.summary(pid)['source_reviewed']
    assert u.candidate(pid, UUID(saved['id']))['candidate_json'] == original
    # A new ordered image source cannot inherit the old wording.
    with transaction(app.db) as c:
        previous_source = row(c, m.problem_source_versions, id=source)
    image = BytesIO()
    Image.new('RGB', (13, 12), 'white').save(image, format='PNG')
    uploaded = u.upload(pid, image.getvalue(), '补图.png', 'image/png', uuid4().hex)
    u.source_version(pid, source, [UUID(previous_source['images'][0]['source_id']), UUID(uploaded['source_id'])], uuid4().hex)
    assert u.summary(pid)['candidate'] is None
    assert app.get_problem(pid)['presentation']['title_kind'] == 'image'
    assert app.get_problem(pid)['presentation']['title'] == '待提取题目'


def test_original_text_survives_a_manual_candidate_with_math_errors(app):
    u, pid, source = create(app)
    original = {**candidate(['t+']), 'original_text': '已知实数t>0。'}
    saved = u.save_candidate(pid, None, source, original, uuid4().hex)
    assert not saved['validation_json']['contract_valid']
    assert u.candidate(pid, UUID(saved['id']))['candidate_json']['original_text'] == original['original_text']
    assert app.get_problem(pid)['presentation']['title'] == original['original_text']
    assert app.get_problem(pid)['presentation']['status'] == 'needs_revision'
