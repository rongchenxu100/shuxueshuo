"""Stage artifact sink, persistent call budgets and authenticated checkpoint restoration."""
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import time
from uuid import UUID, uuid4
from zipfile import ZipFile
from types import SimpleNamespace
from collections.abc import Mapping

from sqlalchemy import select, func

from . import models as m
from .application import dependencies
from .db import transaction, digest
from .errors import Conflict, IntegrityFailure, ProductError
from .repositories import row, scoped
from .services import append_event


def payload(value):
    if hasattr(value, 'to_payload'): return payload(value.to_payload())
    if isinstance(value, Mapping): return {k: payload(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [payload(x) for x in value]
    return value


def require_source_review_config(build):
    """Frozen legacy budgets cannot run a different extraction policy."""
    config = build['effective_config'].get('extraction', {})
    if any(config.get(key) != limit for key, limit in {
        'draft_budget': 3, 'review_budget': 3, 'semantic_budget': 6, 'network_budget': 12}.items()):
        raise Conflict('extraction.rebuild_required')


class ExecutionContext:
    @classmethod
    def preview(cls, application, build, work):
        """Read-only checkpoint decoder; never grants execution or registers output."""
        from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
        value = cls.__new__(cls)
        value.app, value.service, value.ctx = application, application.service, application.ctx
        value.build, value.work, value.refs = build, work, {}
        value.config = SolverRuntimeConfig.from_sources(planner_mode='strategy', llm_provider='deepseek', allow_same_problem_few_shot=False)
        return value

    def __init__(self, application, context, build_id, execution_id, epoch):
        self.app, self.service, self.ctx = application, application.service, context
        self.args = (context, build_id, execution_id, epoch)
        with transaction(self.service.db) as c:
            self.build, _ = self.service._guard(c, *self.args)
            source = scoped(c, m.sources, context, self.build['source_id'])
            self.source = self.service.artifacts.verified(c, context, source['original_artifact_id'])
        self.work = application.settings.root / 'work' / str(execution_id)
        self.work.mkdir(parents=True, exist_ok=True)
        self.refs, self.outputs, self.stage_key, self.attempt = {}, [], None, None
        self.pending_revision = None
        from shuxueshuo_server.solver.runtime.config import SolverRuntimeConfig
        self.config = SolverRuntimeConfig.from_sources(planner_mode='strategy', llm_provider='deepseek', allow_same_problem_few_shot=False)
        self.secrets = [s for s in (self.config.deepseek_api_key, self.config.doubao_api_key) if s]

    def guard(self, *, code=True):
        with transaction(self.service.db) as c: self.service._guard(c, *self.args)
        if code:
            if any(s['stage_key'] == 'extraction' and s['contract_version'] != 'v2'
                   for s in self.build['pipeline_snapshot']['stages']):
                raise Conflict('extraction.rebuild_required')
            target = dependencies(self.source, self.build['requested_revision_id'], self.build['pipeline_snapshot'])
            if target['deployment_version'] != self.build['deployment_version'] or target['config'] != self.build['effective_config']:
                raise Conflict('build.environment_changed')

    def begin(self, stage_key):
        self.guard()
        self.stage_key, self.outputs = stage_key, []
        self.consumed = {self.source['id']} if stage_key == 'source' else set()
        self.attempt = self.service.begin_stage(*self.args, stage_key)

    def redact(self, value):
        if isinstance(value, bytes): return value
        if isinstance(value, dict):
            return {k: '[REDACTED]' if re.search(r'(?i)(api_key|password|authorization|cookie|secret)', str(k)) else self.redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)): return [self.redact(v) for v in value]
        if isinstance(value, str):
            for secret in self.secrets: value = value.replace(secret, '[REDACTED]')
        return value

    def add(self, name, value, role='output', mime='application/json', kind=None, schema=None, page=False):
        value = self.redact(payload(value))
        content = value if isinstance(value, bytes) else value.encode() if mime.startswith('text/') and isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode()
        artifact = self.service.register_artifact(*self.args, attempt_id=self.attempt['id'], content=content,
            artifact_type=kind or role, content_type=mime, schema_version=schema, access_class='page' if page else 'private')
        ref = {'artifact_id': artifact['id'], 'name': name, 'role': role}
        self.outputs.append(ref)
        self.refs[(self.stage_key, name)] = ref
        with transaction(self.service.db) as c:
            append_event(c, self.ctx.workspace_id, 'build', self.build['id'], 'artifact.registered',
                         {'stage_key': self.stage_key, 'artifact_id': str(artifact['id']), 'name': name, 'role': role})
        return artifact

    def bytes(self, stage_key, name):
        ref = self.refs.get((stage_key, name))
        if not ref: raise IntegrityFailure('checkpoint.missing_output')
        with transaction(self.service.db) as c:
            artifact = self.service.artifacts.verified(c, self.ctx, UUID(str(ref['artifact_id'])))
        if hasattr(self, 'consumed') and stage_key != self.stage_key: self.consumed.add(artifact['id'])
        with self.service.storage.open(artifact['storage_key']) as f: return f.read()

    def read(self, stage_key, name): return json.loads(self.bytes(stage_key, name))

    def complete(self, summary):
        self.guard()
        saved = list(self.outputs)
        checkpoint = self.add('checkpoint', {'schema_version': 'product-checkpoint/v1', 'stage_key': self.stage_key,
            'outputs': [{**r, 'artifact_id': str(r['artifact_id'])} for r in saved]}, role='validation', kind='checkpoint', schema='product-checkpoint/v1')
        manifest = self.add('manifest', {'stage_key': self.stage_key, 'contract_version': next(s['contract_version'] for s in self.build['pipeline_snapshot']['stages'] if s['stage_key'] == self.stage_key),
            **self.build['target_dependencies'][self.stage_key], 'observed_artifacts': [str(r['artifact_id']) for r in saved],
            'observed_inputs': sorted(str(aid) for aid in self.consumed)}, role='validation', kind='manifest')
        with transaction(self.service.db) as c:
            for aid in self.consumed:
                self.service.link_artifacts(*self.args, manifest['id'], aid, 'build_input')
            for ref in saved:
                self.service.link_artifacts(*self.args, ref['artifact_id'], manifest['id'], 'audit')
            if self.stage_key == 'extraction' and self.pending_revision is not None:
                self.service.save_revision(self.ctx, self.build['problem_id'], self.build['requested_revision_id'],
                    self.pending_revision, origin_build_id=self.build['id'], execution_id=self.args[2], epoch=self.args[3])
            result = self.service.commit_stage(*self.args, self.stage_key, attempt_id=self.attempt['id'],
                manifest_artifact_id=manifest['id'], checkpoint_artifact_id=checkpoint['id'], outputs=self.outputs)
            c.execute(m.build_stages.update().where(m.build_stages.c.id == self.attempt['build_stage_id']).values(summary=summary))
        return result

    def restore(self, stage, attempt):
        with transaction(self.service.db) as c:
            self.service._verify_accepted_provenance(c, self.ctx, attempt, self.build['problem_id'])
            refs = self.service._attempt_outputs(c, attempt['id'])
            checkpoint = self.service.artifacts.verified(c, self.ctx, attempt['checkpoint_artifact_id'])
        with self.service.storage.open(checkpoint['storage_key']) as f: data = json.load(f)
        if data.get('schema_version') != 'product-checkpoint/v1' or data.get('stage_key') != stage['stage_key']:
            raise IntegrityFailure('checkpoint.contract')
        recorded = [(str(r['artifact_id']), r['name'], r['role']) for r in refs if r['artifact_id'] not in (attempt['manifest_artifact_id'], attempt['checkpoint_artifact_id'])]
        if recorded != [(r['artifact_id'], r['name'], r['role']) for r in data['outputs']]: raise IntegrityFailure('checkpoint.output_map')
        for ref in refs: self.refs[(stage['stage_key'], ref['name'])] = dict(ref)
        archive = self.refs.get((stage['stage_key'], 'Extraction artifact checkpoint/v1'))
        if archive:
            root = self.work / 'extraction-artifacts'
            with ZipFile(BytesIO(self.bytes(stage['stage_key'], 'Extraction artifact checkpoint/v1'))) as zipped:
                if sum(e.file_size for e in zipped.infolist()) > 512 * 1024 * 1024: raise IntegrityFailure('checkpoint.archive_size')
                for entry in zipped.infolist():
                    if not re.fullmatch(r'[a-f0-9]{2}/[a-f0-9]{64}\.[a-z0-9]+', entry.filename): raise IntegrityFailure('checkpoint.archive_path')
                    content = zipped.read(entry)
                    path = root / entry.filename
                    if path.stem != sha256(content).hexdigest() or path.parent.name != path.stem[:2]: raise IntegrityFailure('checkpoint.archive_hash')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)
        self.validate_restored(stage['stage_key'])

    def contexts(self):
        from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
        initial = ProblemExtractionContext.from_payload(self.read('source', 'Source / selection / initial Context'))
        observation = ProblemExtractionContext.from_payload(self.read('observation', 'Observation Context'), ancestor_contexts=(initial,))
        ancestors = [initial, observation]
        if ('extraction', 'Extraction Context ancestry') in self.refs:
            for raw in self.read('extraction', 'Extraction Context ancestry'):
                if raw['manifest']['context_id'] not in {x.manifest.context_id for x in ancestors}:
                    ancestors.append(ProblemExtractionContext.from_payload(raw, ancestor_contexts=tuple(ancestors)))
        return initial, observation, tuple(ancestors)

    def bundle(self):
        from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
        from shuxueshuo_server.solver.extraction.problem_solver_bundle import VerifiedSolverProblemBundleLoader
        from shuxueshuo_server.review.replay import extraction_store
        _, _, ancestors = self.contexts()
        final = ProblemExtractionContext.from_payload(self.read('extraction', 'Extraction Context'), ancestor_contexts=ancestors)
        return VerifiedSolverProblemBundleLoader().load(final, extraction_store(self.work / 'extraction-artifacts'), ancestor_contexts=ancestors)

    def validate_restored(self, key):
        from shuxueshuo_server.solver.extraction.context import ProblemExtractionContext
        if key == 'source': ProblemExtractionContext.from_payload(self.read('source', 'Source / selection / initial Context'))
        if key == 'observation': self.contexts()
        if key in ('extraction', 'projection'): self.bundle()
        if key == 'solver':
            from shuxueshuo_server.review.replay import restore_evidence, EVIDENCE
            restore_evidence(self.bundle(), self.read('solver', 'VerifiedFunctionalPlanExecution'), self.read('solver', EVIDENCE), self.config)
        if key == 'evidence':
            from shuxueshuo_server.solver.explanation.models import explanation_snapshot_from_payload
            explanation_snapshot_from_payload(self.read('evidence', 'ExplanationSnapshot'))
        if key == 'lesson':
            from shuxueshuo_server.solver.explanation.lesson_ir import lesson_ir_from_payload
            lesson_ir_from_payload(self.read('lesson', 'LessonIR（实际采用）'))
        if key == 'visual':
            from dataclasses import replace
            from shuxueshuo_server.solver.visual.models import visual_step_ir_from_payload
            from shuxueshuo_server.solver.visual.validator import VisualStepIRValidator
            from shuxueshuo_server.solver.explanation.lesson_ir import lesson_ir_from_payload
            visual = replace(visual_step_ir_from_payload(self.read('visual', 'VisualStepIR')),
                compile_lesson_data=self.read('visual', 'lesson-data.json'))
            VisualStepIRValidator().validate(visual,
                lesson=lesson_ir_from_payload(self.read('lesson', 'LessonIR（实际采用）')))
        if key == 'page':
            from shuxueshuo_server.review.pipeline import inspect_page
            inspect_page(self.bytes('page', 'page_html'))


class AuditedClient:
    def __init__(self, client, context):
        self.client, self.context = client, context
        if hasattr(client, '_client'):
            sdk = client._client
            if hasattr(sdk, 'with_options'): sdk = sdk.with_options(max_retries=0)
            create = sdk.chat.completions.create
            def audited_create(**options):
                self.reserve('model.network_started', 'network_budget')
                return create(**options)
            client._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=audited_create)))

    def __getattr__(self, name): return getattr(self.client, name)

    def reserve(self, code, budget, call_id=None, request_hash=None):
        x = self.context
        x.guard()
        limit = x.build['effective_config'][x.stage_key][budget]
        with transaction(x.service.db) as c:
            x.service._guard(c, *x.args)
            previous = c.execute(select(m.diagnostics.c.details).where(m.diagnostics.c.build_id == x.build['id'],
                m.diagnostics.c.code == code, m.diagnostics.c.details['stage'].astext == x.stage_key)).scalars().all()
            known = {r.get('request_hash') for r in previous}
            used = len(known) if request_hash else len(previous)
            if used >= limit and (not request_hash or request_hash not in known): raise ProductError('model.budget_exhausted')
            x.service.record_diagnostic(*x.args, code=code, message='模型请求已开始；没有结束记录时结果未知。', severity='info',
                stage_attempt_id=x.attempt['id'], details={'stage': x.stage_key, 'call_id': call_id or str(uuid4()), 'request_hash': request_hash})

    def complete(self, request):
        x = self.context
        call_id = str(uuid4())
        req = request.redacted_payload() if hasattr(request, 'redacted_payload') else request
        review_key = None
        if x.stage_key == 'extraction':
            require_source_review_config(x.build)
            review = getattr(request, 'contract_version', None) == 'problem-source-review/v1'
            if review:
                review_key = json.loads(request.prompt.user_suffix)['binding']
                cached = self._restore_source_review(review_key)
                if cached is not None:
                    return cached
            self.reserve('model.review_started' if review else 'model.draft_started',
                         'review_budget' if review else 'draft_budget', call_id, review_key)
        self.reserve('model.call_started', 'semantic_budget', call_id,
                     None if x.stage_key == 'extraction' else digest(payload(req)))
        request_ref = x.add(f'{call_id} 实际请求', req, role='input')
        for image in getattr(request, 'images', []): x.add(f'{call_id} 图片 {image.role}', image.content, role='input', mime=image.artifact.media_type)
        started, result, failed, response_ref = time.monotonic(), None, False, None
        for field, value in (('last_usage', None), ('last_response_model', None), ('last_provider_attempts', ())):
            if hasattr(self.client, field): setattr(self.client, field, value)
        try:
            result = self.client.complete(request)
            response_ref = x.add(f'{call_id} 原始返回', result.text if hasattr(result, 'text') else result, role='raw', mime='text/plain')
            if hasattr(result, 'raw_payload'): x.add(f'{call_id} provider payload', result.raw_payload, role='raw')
            if review_key:
                replay = x.add('source-review-replay:' + review_key, {
                    'text': result.text, 'raw_payload': dict(result.raw_payload),
                    'metadata': result.metadata_payload()}, role='call')
                x.service.record_diagnostic(*x.args, code='model.review_completed',
                    message='视觉复核响应已持久化。', severity='info', stage_attempt_id=x.attempt['id'],
                    details={'binding': review_key, 'artifact_id': str(replay['id'])})
            return result
        except Exception:
            failed = True
            raise
        finally:
            meta = result.metadata_payload() if hasattr(result, 'metadata_payload') else {
                'provider': getattr(self.client, 'provider_name', None), 'request_model': getattr(self.client, 'model', None),
                'response_model': getattr(self.client, 'last_response_model', None),
                'usage': getattr(self.client, 'last_usage', None),
                'provider_attempts': getattr(self.client, 'last_provider_attempts', None)}
            audit = x.add(f'{call_id} 调用记录', {**meta, 'call_id': call_id, 'duration_seconds': time.monotonic() - started,
                          'status': 'failed' if failed else 'succeeded'}, role='call', kind='call_audit')
            usage = meta.get('usage') or {}
            x.service.record_call(*x.args, x.attempt['id'], audit['id'], call_kind=x.stage_key,
                provider=meta.get('provider'), request_model=meta.get('request_model'), response_model=meta.get('response_model'),
                status='failed' if failed else 'succeeded', duration_ms=int((time.monotonic() - started) * 1000),
                request_artifact_id=request_ref['id'], response_artifact_id=response_ref['id'] if response_ref else None,
                input_tokens=usage.get('prompt_tokens', usage.get('input_tokens')), output_tokens=usage.get('completion_tokens', usage.get('output_tokens')), usage_json=meta.get('usage'))

    def _restore_source_review(self, key):
        """A fenced worker may reuse an audited response, never repeat an unknown call."""
        from shuxueshuo_server.solver.extraction.multimodal_provider import MultimodalProviderResponse
        x = self.context
        with transaction(x.service.db) as c:
            x.service._guard(c, *x.args)
            prior = c.execute(select(m.diagnostics.c.details).where(
                m.diagnostics.c.build_id == x.build['id'],
                m.diagnostics.c.code == 'model.review_started',
                m.diagnostics.c.details['request_hash'].astext == key)).first()
            if not prior:
                return None
            completed = c.execute(select(m.diagnostics.c.details).where(
                m.diagnostics.c.build_id == x.build['id'], m.diagnostics.c.code == 'model.review_completed',
                m.diagnostics.c.details['binding'].astext == key)).scalar()
            if not completed:
                raise ProductError('model.source_review_outcome_unknown')
            artifact_id = UUID(completed['artifact_id'])
            artifact = x.service.artifacts.verified(c, x.ctx, artifact_id)
            if artifact['producer_build_id'] != x.build['id']:
                raise IntegrityFailure('model.source_review_wrong_build')
        with x.service.storage.open(artifact['storage_key']) as f:
            saved = json.load(f)
        meta = saved['metadata']
        return MultimodalProviderResponse(text=saved['text'], raw_payload=saved['raw_payload'],
            request_model=meta['request_model'], response_model=meta['response_model'], usage={},
            finish_reason=meta['finish_reason'], provider_attempts=(), latency_ms=0,
            thinking_mode=meta['thinking_mode'], reasoning_effort=meta['reasoning_effort'],
            contract_version='problem-source-review/v1', provider_name=meta['provider'],
            transport={key: meta[key] for key in ('max_output_tokens', 'timeout', 'stream', 'temperature', 'transport_response_format', 'image_detail') if key in meta})

    def restore_source_review(self, request):
        """Only restore an existing audited response; never reserve or call."""
        require_source_review_config(self.context.build)
        if self.context.stage_key != 'extraction' or request.contract_version != 'problem-source-review/v1':
            raise ProductError('model.source_review_invalid_request')
        return self._restore_source_review(json.loads(request.prompt.user_suffix)['binding'])
