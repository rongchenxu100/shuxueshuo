"""No paid calls: recorded planner + valid domain fixtures through product checkpoints."""
from io import BytesIO
import json
from pathlib import Path
import shutil
import sys
from uuid import UUID

from PIL import Image
import pytest
from sqlalchemy import select

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.execution import ExecutionContext
from shuxueshuo_server.product.runner import StageRunner
from shuxueshuo_server.product.repositories import row
from shuxueshuo_server.product.errors import IntegrityFailure


def fixture_domain(tmp_path):
    helper = str(Path(__file__).resolve().parents[1] / 'solver')
    sys.path.insert(0, helper)
    try:
        from _problem_planning_support import accepted_bundle_fixture
        return accepted_bundle_fixture(tmp_path, case='tj-2026-heping-yimo-25')
    finally: sys.path.remove(helper)


def offline_discover(source, revision, snapshot):
    return {'deployment_version': 'offline-runner-v1', 'config': {}, 'dependencies': {
        s['stage_key']: {'inputs': {'source': source['sha256']}, 'resources': {}, 'config': {}, 'upstream': {}}
        for s in snapshot['stages']}}


@pytest.fixture
def run_context(setup, settings, tmp_path, monkeypatch):
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.review.replay import ARCHIVE, archive_bytes, EVIDENCE, evidence_checkpoint
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.explanation.scope_lesson import ScopeLessonAuthoringService
    from shuxueshuo_server.solver.explanation.lesson_ir import RecursiveLessonIRAssembler
    from shuxueshuo_server.solver.explanation.models import explanation_snapshot_from_payload
    def forbidden_legacy(*args, **kwargs): raise AssertionError('product must not initialize legacy SQLite persistence')
    monkeypatch.setattr('shuxueshuo_server.review.store.ReviewStore.__init__', forbidden_legacy)
    monkeypatch.setattr('shuxueshuo_server.review.versions.Versions.__init__', forbidden_legacy)
    s, ctx, admin = setup
    app = Application(settings, s, ctx, discover=offline_discover)
    monkeypatch.setattr('shuxueshuo_server.product.execution.dependencies', offline_discover)
    batch = app.create_batch('batch')
    image = BytesIO(); Image.new('RGB', (8, 8), 'white').save(image, format='PNG')
    uploaded = app.upload(UUID(batch['id']), 'upload', image.getvalue(), 'offline.png', 'image/png')
    item = uploaded['item']
    submitted = app.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), 'build')
    def context():
        execution = s.acquire_execution(ctx, UUID(submitted['job_id']), 'test', deployment_version='offline-runner-v1', lease_seconds=3600)
        result = ExecutionContext(app, ctx, UUID(submitted['build_id']), execution['id'], execution['epoch'])
        result.config = SolverRuntimeConfig(planner_mode='strategy', llm_provider='recorded')
        return result
    x = context()
    root, observation, final, store, verified, *_ = fixture_domain(tmp_path / 'fixture')
    shutil.copytree(store.root, x.work / 'extraction-artifacts', dirs_exist_ok=True)
    runner = StageRunner(x)
    def source():
        x.add('规范化图片', image.getvalue(), mime='image/png')
        x.add('Source / selection / initial Context', root)
        x.validate_restored('source')
        return '有效离线来源 fixture'
    def observe():
        x.add('Observation Context', observation)
        x.add(ARCHIVE, archive_bytes(store.root), mime='application/zip')
        x.validate_restored('observation')
        return '有效离线观察 fixture'
    def extract():
        x.add('Extraction Context', final)
        x.add('VerifiedProblem', verified)
        x.add(ARCHIVE, archive_bytes(store.root), mime='application/zip')
        x.pending_revision = verified.to_payload()['graph']
        x.bundle()
        return '通过领域校验的 fixture'
    def solve():
        runtime = RuntimeOrchestrator(family_registry=x.config.build_family_registry(),
            default_planner_provider=x.config.build_default_planner_provider(), max_attempts=x.config.max_llm_attempts)
        result = runtime.solve_verified(x.bundle())
        assert result.ok, result.errors
        x.add('VerifiedFunctionalPlanExecution', runtime.last_success_artifacts.verified_functional_execution)
        x.add(EVIDENCE, evidence_checkpoint(runtime.last_success_artifacts))
        return 'recorded planner，真实数学执行'
    def lesson():
        class RecordedInvalidContent:
            def complete(self, request): return '{}'
        snapshot = explanation_snapshot_from_payload(x.read('evidence', 'ExplanationSnapshot'))
        generation = ScopeLessonAuthoringService(client=RecordedInvalidContent()).generate(snapshot)
        built = RecursiveLessonIRAssembler().assemble(snapshot, generation.projection, generation.validation)
        assert generation.validation.fallback_used
        x.add('LessonIR（实际采用）', built.lesson)
        return '经过校验的确定性 fallback'
    runner.adapters.update(source=source, observation=observe, extraction=extract, solver=solve, lesson=lesson)
    return app, x, runner, context, admin


def test_offline_nine_stages_and_typed_restore(run_context):
    app, x, runner, _, _ = run_context
    runner.run()
    dto = app.build(x.build['id'])
    assert dto['status'] == 'succeeded' and dto['page_current']
    assert all(s['status'] == 'succeeded' for s in dto['stages'])
    assert len(dto['stages']) == 9
    # Restore into a separate scratch root, without invoking a provider or solver.
    x.work = x.work.parent / (x.work.name + '-restore')
    x.work.mkdir()
    x.refs = {}
    with transaction(app.db) as c:
        stages = c.execute(select(m.build_stages).where(m.build_stages.c.build_id == x.build['id']).order_by(m.build_stages.c.ordinal)).mappings().all()
        attempts = [row(c, m.stage_attempts, id=s['accepted_attempt_id']) for s in stages]
    for stage, attempt in zip(stages, attempts): x.restore(stage, attempt)
    assert b'<html' in x.bytes('page', 'page_html')
    assert b'/Users/' not in x.bytes('page', 'page_html')
    assert app.service.page_resource(app.ctx, UUID(dto['page_id']), 'index.html')['content_type'] == 'text/html'
    # Hash-valid but untyped content is rejected before being reused.
    original = x.read
    x.read = lambda stage, name: {} if stage == 'source' else original(stage, name)
    with pytest.raises((ValueError, KeyError, TypeError)): x.validate_restored('source')


def test_rebuild_preview_restores_typed_prefix_and_reuses_without_models(run_context):
    app, x, runner, _, _ = run_context
    runner.run()
    preview = app.rebuild_preview(x.build['id'], 'page')
    assert preview['reuse_stages'] == [s['stage_key'] for s in x.build['pipeline_snapshot']['stages'][:-1]]
    child = app.rebuild(x.build['id'], 'page', preview['fingerprint'], 'rebuild')
    execution = app.service.acquire_execution(app.ctx, UUID(child['job_id']), 'test', deployment_version='offline-runner-v1', lease_seconds=3600)
    context = ExecutionContext(app, app.ctx, UUID(child['build_id']), execution['id'], execution['epoch'])
    context.config = x.config
    StageRunner(context).run()
    assert app.build(context.build['id'])['status'] == 'succeeded'
    assert not app.build(x.build['id'])['page_current']
    assert app.build(context.build['id'])['page_current']
    with transaction(app.db) as c:
        reused = c.execute(select(m.stage_attempts).where(m.stage_attempts.c.execution_id == execution['id'], m.stage_attempts.c.kind == 'reused')).all()
        assert len(reused) == 8


def test_call_budget_persists_across_execution_recovery(run_context):
    from types import SimpleNamespace
    from shuxueshuo_server.product.execution import AuditedClient
    from shuxueshuo_server.product.errors import ProductError
    app, x, _, acquire, _ = run_context
    # Supply a frozen test-only call contract without changing any database record.
    def configure(context):
        context.build = {**context.build, 'effective_config': {'source': {'semantic_budget': 1, 'network_budget': 2}}}
        context.guard = lambda **_: app.service.heartbeat(*context.args, lease_seconds=3600)
        context.begin('source')
        class Provider:
            provider_name = 'offline-test'
            model = 'offline-test'
            def __init__(self): self._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: 'response')))
            def complete(self, request): return self._client.chat.completions.create(**request)
        return AuditedClient(Provider(), context)
    first = configure(x)
    assert first.complete({'messages': ['same']}) == 'response'
    app.service.finish_failure(*x.args, 'test.crash', interrupted=True)
    recovered = acquire()
    second = configure(recovered)
    assert second.complete({'messages': ['same']}) == 'response'
    with pytest.raises(ProductError, match='model.budget_exhausted'): second.complete({'messages': ['same']})
    with pytest.raises(ProductError, match='model.budget_exhausted'): second.complete({'messages': ['changed']})
    with transaction(app.db) as c:
        calls = c.execute(select(m.model_calls).where(m.model_calls.c.workspace_id == app.ctx.workspace_id)).mappings().all()
        assert len(calls) == 3 and sum(r['status'] == 'succeeded' for r in calls) == 2
        assert all(r['input_tokens'] is None and r['output_tokens'] is None for r in calls)
    app.service.cancel(app.ctx, x.build['id'])


def test_manual_revision_is_revalidated_without_extraction_provider(run_context):
    from copy import deepcopy
    app, x, runner, _, _ = run_context
    runner.run()
    with transaction(app.db) as c:
        p = row(c, m.problems, id=x.build['problem_id'])
        rev = row(c, m.problem_revisions, id=p['current_revision_id'])
    changed = deepcopy(rev['domain_json']); changed['root']['source_text'][0] += '（人工校对）'
    saved = app.save_revision(p['id'], rev['id'], changed, 'manual')
    preview = app.rebuild_preview(x.build['id'], 'extraction')
    child = app.rebuild(x.build['id'], 'extraction', preview['fingerprint'], 'manual-build')
    execution = app.service.acquire_execution(app.ctx, UUID(child['job_id']), 'test', deployment_version='offline-runner-v1', lease_seconds=3600)
    context = ExecutionContext(app, app.ctx, UUID(child['build_id']), execution['id'], execution['epoch'])
    context.config = x.config
    runner = StageRunner(context)
    class StopAfterExtraction(Exception): pass
    def stop(): raise StopAfterExtraction()
    runner.adapters['projection'] = stop
    with pytest.raises(StopAfterExtraction): runner.run()
    dto = app.build(context.build['id'])
    assert dto['resolved_revision_id'] == saved['id']
    assert dto['stages'][2]['status'] == 'succeeded'
    assert not app.build(x.build['id'])['page_current']
    app.service.cancel(app.ctx, context.build['id'])
