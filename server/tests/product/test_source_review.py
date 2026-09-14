"""Persistent review audit and execution fencing on an isolated PostgreSQL instance."""
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import ProductError
from shuxueshuo_server.product.execution import AuditedClient
from shuxueshuo_server.solver.extraction.multimodal_provider import MultimodalProviderResponse

from test_runner import run_context  # noqa: F401


class Request:
    contract_version = 'problem-source-review/v1'
    images = ()

    def __init__(self, key):
        self.prompt = SimpleNamespace(user_suffix=json.dumps({'binding': key}))

    def redacted_payload(self):
        return {'binding': json.loads(self.prompt.user_suffix)['binding'], 'contract': self.contract_version}


class Provider:
    model = 'recorded-source-review'
    provider_name = 'recorded'

    def __init__(self, *, crash=False):
        self.calls = 0
        self.crash = crash

    def complete(self, request):
        self.calls += 1
        if self.crash:
            raise TimeoutError('recorded timeout')
        return MultimodalProviderResponse(text='{"status":"confirmed"}', raw_payload={'recorded': True},
            request_model=self.model, response_model=self.model, usage={'input_tokens': 10, 'output_tokens': 5},
            finish_reason='stop', provider_attempts=(), latency_ms=1, thinking_mode='disabled',
            reasoning_effort=None, contract_version=request.contract_version, provider_name=self.provider_name)


def prepare(run_context):
    app, x, runner, acquire, _ = run_context
    for key in ['source', 'observation']:
        x.begin(key)
        x.complete(runner.adapters[key]())
    def configure(context, provider):
        context.build = {**context.build, 'effective_config': {'extraction': {
            'draft_budget': 3, 'review_budget': 3, 'semantic_budget': 6, 'network_budget': 12}}}
        context.guard = lambda **_: app.service.heartbeat(*context.args, lease_seconds=3600)
        context.begin('extraction')
        return AuditedClient(provider, context)
    return app, x, acquire, configure


def test_review_response_replays_after_uncommitted_stage_recovery(run_context):
    app, x, acquire, configure = prepare(run_context)
    first_provider = Provider()
    first = configure(x, first_provider).complete(Request('same-image-and-revision'))
    app.service.finish_failure(*x.args, 'test.interrupted', interrupted=True)
    recovered = acquire()
    second_provider = Provider()
    second = configure(recovered, second_provider).complete(Request('same-image-and-revision'))
    assert first.text == second.text and first_provider.calls == 1 and second_provider.calls == 0
    with transaction(app.db) as c:
        calls = c.execute(select(m.model_calls).join(m.stage_attempts,
            m.model_calls.c.origin_attempt_id == m.stage_attempts.c.id).join(m.build_stages,
            m.stage_attempts.c.build_stage_id == m.build_stages.c.id).where(m.build_stages.c.build_id == x.build['id'])).mappings().all()
    assert len(calls) == 1 and calls[0]['input_tokens'] == 10 and calls[0]['output_tokens'] == 5
    app.service.cancel(app.ctx, x.build['id'])


def test_unknown_review_outcome_is_not_reissued_after_recovery(run_context):
    app, x, acquire, configure = prepare(run_context)
    with pytest.raises(TimeoutError): configure(x, Provider(crash=True)).complete(Request('unknown-outcome'))
    app.service.finish_failure(*x.args, 'test.interrupted', interrupted=True)
    second_provider = Provider()
    with pytest.raises(ProductError, match='source_review_outcome_unknown'):
        configure(acquire(), second_provider).complete(Request('unknown-outcome'))
    assert second_provider.calls == 0
    app.service.cancel(app.ctx, x.build['id'])


@pytest.mark.parametrize('crash_at', ['validation', 'result_artifact', 'state_commit'])
def test_audited_success_recovers_when_source_reviewer_file_is_still_started(run_context, tmp_path, monkeypatch, crash_at):
    from dataclasses import replace
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'solver'))
    from test_problem_source_review import recorded_input, corrected_payload, review_response
    from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft
    from shuxueshuo_server.solver.extraction import problem_source_review as review_module
    app, x, acquire, configure = prepare(run_context)
    _, context, store, pack = recorded_input(tmp_path)
    draft = ProblemDraft.create(corrected_payload())
    class ImageProvider(Provider):
        supports_images = True
        response_format_mode = 'json_object'
        def complete(self, request):
            return replace(super().complete(request), text=review_response(request))
    first_provider = ImageProvider()
    args = dict(context_id=context.manifest.context_id, draft=draft, pack=pack,
        reader=store, differences=review_module.source_differences(draft, pack))
    def crash(*args, **kwargs): raise KeyboardInterrupt('process loss after audited success')
    with monkeypatch.context() as patch:
        if crash_at == 'validation':
            patch.setattr(review_module, 'validate_review', crash)
        elif crash_at == 'result_artifact':
            original = store.put_json
            def put(**kwargs):
                if kwargs['kind'] == 'problem_source_review_result': crash()
                return original(**kwargs)
            patch.setattr(store, 'put_json', put)
        else:
            original = review_module.SourceReviewer._save
            def save(path, state):
                if any('artifact' in entry for entry in state.values()): crash()
                return original(path, state)
            patch.setattr(review_module.SourceReviewer, '_save', staticmethod(save))
        with pytest.raises(KeyboardInterrupt):
            review_module.SourceReviewer(store).review(**args, provider=configure(x, first_provider))
    app.service.finish_failure(*x.args, 'test.interrupted', interrupted=True)
    recovered = acquire()
    second_provider = ImageProvider()
    report, _ = review_module.SourceReviewer(store).review(**args, provider=configure(recovered, second_provider))
    assert report['status'] == 'confirmed', report
    assert first_provider.calls == 1 and second_provider.calls == 0
    with transaction(app.db) as c:
        diagnostics = c.execute(select(m.diagnostics.c.code).where(m.diagnostics.c.build_id == x.build['id'])).scalars().all()
        calls = c.execute(select(m.model_calls).where(m.model_calls.c.origin_attempt_id == x.attempt['id'])).mappings().all()
    assert diagnostics.count('model.review_started') == diagnostics.count('model.call_started') == 1
    assert len(calls) == 1 and calls[0]['input_tokens'] == 10
    app.service.cancel(app.ctx, x.build['id'])


def test_legacy_extraction_config_requires_new_build_without_spending_budget(run_context):
    from copy import deepcopy
    from shuxueshuo_server.product.execution import ExecutionContext
    from shuxueshuo_server.product.runner import StageRunner
    app, x, _, configure = prepare(run_context)
    provider = Provider()
    client = configure(x, provider)
    old_config = {'extraction': {'semantic_budget': 3, 'network_budget': 6}}
    x.build = {**x.build, 'effective_config': deepcopy(old_config)}
    with pytest.raises(ProductError, match='extraction.rebuild_required'):
        client.complete(Request('legacy-review'))
    with pytest.raises(ProductError, match='extraction.rebuild_required'):
        StageRunner(x).extraction()
    assert provider.calls == 0 and x.build['effective_config'] == old_config
    x.build['pipeline_snapshot'] = deepcopy(x.build['pipeline_snapshot'])
    next(s for s in x.build['pipeline_snapshot']['stages'] if s['stage_key'] == 'extraction')['contract_version'] = 'v1'
    with pytest.raises(ProductError, match='extraction.rebuild_required'):
        ExecutionContext.guard(x)
    with transaction(app.db) as c:
        assert not c.execute(select(m.diagnostics.c.id).where(m.diagnostics.c.build_id == x.build['id'],
            m.diagnostics.c.code == 'model.call_started')).first()
    app.service.cancel(app.ctx, x.build['id'])


def test_review_and_network_budgets_survive_new_execution(run_context):
    app, x, acquire, configure = prepare(run_context)
    provider = Provider()
    client = configure(x, provider)
    for i in range(3): client.complete(Request(str(i)))
    for _ in range(12): client.reserve('model.network_started', 'network_budget')
    app.service.finish_failure(*x.args, 'test.interrupted', interrupted=True)
    client = configure(acquire(), provider)
    with pytest.raises(ProductError, match='model.budget_exhausted'): client.complete(Request('fourth'))
    with pytest.raises(ProductError, match='model.budget_exhausted'): client.reserve('model.network_started', 'network_budget')
    assert provider.calls == 3
    app.service.cancel(app.ctx, x.build['id'])


def test_three_drafts_plus_three_reviews_share_six_call_limit(run_context):
    app, x, acquire, configure = prepare(run_context)
    class DraftRequest(Request):
        contract_version = 'problem-domain/v1'
    provider = Provider()
    client = configure(x, provider)
    for i in range(3):
        client.complete(DraftRequest(f'draft-{i}'))
        client.complete(Request(f'review-{i}'))
    app.service.finish_failure(*x.args, 'test.interrupted', interrupted=True)
    recovered = configure(acquire(), provider)
    with pytest.raises(ProductError, match='model.budget_exhausted'):
        recovered.complete(DraftRequest('fourth-draft'))
    with pytest.raises(ProductError, match='model.budget_exhausted'):
        recovered.reserve('model.call_started', 'semantic_budget')
    assert provider.calls == 6
    app.service.cancel(app.ctx, x.build['id'])


@pytest.mark.parametrize('review_case', ['valid', 'string_null', 'invalid', 'timeout', 'uncertain'])
def test_recorded_image_extraction_through_nine_stages_and_checkpoint_restore(setup, settings, tmp_path, monkeypatch, review_case):
    import shutil
    from pathlib import Path
    from uuid import UUID
    from shuxueshuo_server.product.application import Application
    from shuxueshuo_server.product.execution import ExecutionContext
    from shuxueshuo_server.product.runner import StageRunner
    from shuxueshuo_server.product.repositories import row
    from shuxueshuo_server.review.replay import ARCHIVE, archive_bytes, EVIDENCE, evidence_checkpoint
    from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
    from shuxueshuo_server.solver.runtime.orchestrator import RuntimeOrchestrator
    from shuxueshuo_server.solver.explanation.models import explanation_snapshot_from_payload
    from shuxueshuo_server.solver.explanation.scope_lesson import ScopeLessonAuthoringService
    from shuxueshuo_server.solver.explanation.lesson_ir import RecursiveLessonIRAssembler
    from test_runner import offline_discover
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'solver'))
    from test_problem_source_review import recorded_input, corrected_payload, review_response, FIXTURE
    from test_problem_domain_retry import _SequenceProvider
    initial, observation, store, _ = recorded_input(tmp_path / 'recorded')
    def review(request):
        if review_case == 'timeout': raise TimeoutError('recorded review timeout')
        value = json.loads(review_response(request, 'uncertain' if review_case == 'uncertain' else 'confirmed'))
        if review_case == 'string_null': value['findings'][0]['regions'][0]['region_id'] = 'null'
        if review_case == 'invalid': value['findings'][0]['regions'][0]['region_id'] = 'unknown-region'
        return json.dumps(value, ensure_ascii=False)
    client = _SequenceProvider([json.dumps(corrected_payload()), review])
    monkeypatch.setattr('shuxueshuo_server.solver.extraction.multimodal_provider.DoubaoMultimodalExtractionProvider', lambda **_: client)
    def discover(*args):
        found = offline_discover(*args)
        found['config'] = {'extraction': {'draft_budget': 3, 'review_budget': 3, 'semantic_budget': 6, 'network_budget': 12}}
        return found
    monkeypatch.setattr('shuxueshuo_server.product.execution.dependencies', discover)
    service, ctx, _ = setup
    app = Application(settings, service, ctx, discover=discover)
    batch = app.create_batch('recorded-batch')
    item = app.upload(UUID(batch['id']), 'image', (FIXTURE / 'source.png').read_bytes(), 'heping.png', 'image/png')['item']
    submitted = app.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), 'recorded-build')
    execution = service.acquire_execution(ctx, UUID(submitted['job_id']), 'recorded', deployment_version='offline-runner-v1', lease_seconds=3600)
    x = ExecutionContext(app, ctx, UUID(submitted['build_id']), execution['id'], execution['epoch'])
    x.config = SolverRuntimeConfig(planner_mode='strategy', llm_provider='recorded', doubao_api_key='recorded-no-network')
    shutil.copytree(store.root, x.work / 'extraction-artifacts', dirs_exist_ok=True)
    runner = StageRunner(x)
    def source():
        x.add('规范化图片', (FIXTURE / 'source.png').read_bytes(), mime='image/png')
        x.add('Source / selection / initial Context', initial)
        return 'recorded source'
    def observe():
        x.add('Observation Context', observation)
        x.add(ARCHIVE, archive_bytes(store.root), mime='application/zip')
        return 'real observation adapters with recorded OCR'
    def solve():
        runtime = RuntimeOrchestrator(family_registry=x.config.build_family_registry(),
            default_planner_provider=x.config.build_default_planner_provider(), max_attempts=x.config.max_llm_attempts)
        result = runtime.solve_verified(x.bundle())
        assert result.ok, result.errors
        x.add('VerifiedFunctionalPlanExecution', runtime.last_success_artifacts.verified_functional_execution)
        x.add(EVIDENCE, evidence_checkpoint(runtime.last_success_artifacts))
        return 'recorded planner with real solver'
    def lesson():
        snapshot = explanation_snapshot_from_payload(x.read('evidence', 'ExplanationSnapshot'))
        generation = ScopeLessonAuthoringService(client=SimpleNamespace(complete=lambda _: '{}')).generate(snapshot)
        built = RecursiveLessonIRAssembler().assemble(snapshot, generation.projection, generation.validation)
        x.add('LessonIR（实际采用）', built.lesson)
        return 'validated lesson fallback'
    runner.adapters.update(source=source, observation=observe, solver=solve, lesson=lesson)
    if review_case in ('invalid', 'timeout', 'uncertain'):
        expected = {'invalid': 'extraction.problem_source_review_invalid',
                    'timeout': 'extraction.problem_source_review_failed',
                    'uncertain': 'extraction.problem_source_uncertain'}[review_case]
        with pytest.raises(ProductError, match=expected):
            runner.run()
        app.service.finish_failure(*x.args, expected)
        dto = app.build(x.build['id'])
        assert dto['status'] == 'failed'
        assert dto['error_code'] == expected
        audit = x.read('extraction', 'attempt 1 原图复核报告')
        assert not audit['adopted']
        assert audit['review']['status'] == ('uncertain' if review_case == 'uncertain' else 'failed')
        assert len(client.requests) == 2
        assert not any(a['name'] == 'VerifiedProblem' for a in dto['artifacts'])
        return
    runner.run()
    dto = app.build(x.build['id'])
    assert dto['status'] == 'succeeded' and len(dto['stages']) == 9
    assert len(client.requests) == 2 and client.requests[1].contract_version == 'problem-source-review/v1'
    assert any(a['name'].startswith('source-review-replay:') for a in dto['artifacts'])
    report_artifact = next(a for a in dto['artifacts'] if a['artifact_type'] == 'problem_source_review')
    with transaction(app.db) as c:
        assert row(c, m.artifacts, id=UUID(report_artifact['id']))['schema_version'] == 'problem-source-review-audit/v1'
    review_audit = x.read('extraction', 'attempt 1 原图复核报告')
    assert review_audit['adopted'] and review_audit['review']['status'] == 'confirmed'
    if review_case == 'string_null':
        assert review_audit['review']['model_status'] == 'confirmed'
        assert review_audit['review']['normalizations'] == [{'path': '/findings/0/regions/0/region_id',
            'rule': 'region_id_string_null', 'before': 'null', 'after': None}]
    assert x.build['effective_config']['extraction']['semantic_budget'] == 6
    with transaction(app.db) as c:
        stages = c.execute(select(m.build_stages).where(m.build_stages.c.build_id == x.build['id']).order_by(m.build_stages.c.ordinal)).mappings().all()
        attempts = [row(c, m.stage_attempts, id=s['accepted_attempt_id']) for s in stages]
        calls = c.execute(select(m.model_calls).where(m.model_calls.c.origin_attempt_id == stages[2]['accepted_attempt_id'])).mappings().all()
    assert len(calls) == 2 and all(c['status'] == 'succeeded' for c in calls)
    x.work = tmp_path / 'fresh-checkpoint-restore'
    x.work.mkdir()
    x.refs = {}
    for stage, attempt in zip(stages, attempts):
        x.restore(stage, attempt)
    assert b'<html' in x.bytes('page', 'page_html') and len(client.requests) == 2
