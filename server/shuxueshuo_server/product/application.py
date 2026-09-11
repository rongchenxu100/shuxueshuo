"""Product request use cases. Network/model work belongs exclusively to the worker."""
from datetime import datetime
from hashlib import sha256
import json
import os
import subprocess
from uuid import UUID

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, text

from . import models as m
from .config import Settings, REPO
from .db import engine, transaction, lock, digest
from .errors import Conflict, Forbidden, IntegrityFailure, ProductError
from .pipelines import affected, fingerprint
from .repositories import UserContext, insert, row, scoped, problem
from .services import ProductService, append_event
from .storage import LocalArtifactStorage


def public(row_value, *fields):
    return jsonable_encoder({k: row_value[k] for k in fields}) if row_value else None


def statement_text(domain):
    """Keep the reviewed source wording and subquestion order, without solver answers."""
    lines = []
    def visit(node):
        lines.extend(t.strip() for t in node.get('source_text', []) if isinstance(t, str) and t.strip())
        for child in node.get('children', []):
            visit(child)
    if domain:
        visit(domain.get('root', {}))
    return '\n'.join(lines) or None


def dependencies(source, revision_id, snapshot):
    """Public allowlisted effective settings; source discovery never reads business history."""
    from shuxueshuo_server.review.dependencies import probe
    discovered = probe()
    config = {k: dict(v['config']) for k, v in discovered['stages'].items()}
    # Interpreter paths are local routing configuration, not public content.
    interpreter = os.environ.get('REVIEW_OCR_PYTHON', str(REPO / 'server/.venv-ocr/bin/python'))
    observed = subprocess.run([interpreter, '-c',
        'import json; from shuxueshuo_server.solver.extraction.paddle_worker import PaddleF2ProviderWorker; print(json.dumps([m.to_payload() for m in PaddleF2ProviderWorker().manifests()]))'],
        cwd=REPO / 'server', env={**os.environ, 'PYTHONPATH': str(REPO / 'server')}, capture_output=True, text=True, timeout=60)
    if observed.returncode: raise ProductError('configuration.ocr_manifest_unavailable')
    config['observation'] = {'interpreter_fingerprint': digest(config['observation']), 'providers': json.loads(observed.stdout)}
    for key, limit in (('extraction', 3), ('solver', config['solver']['max_attempts']), ('lesson', 1)):
        config[key]['semantic_budget'] = limit
        config[key]['network_budget'] = limit * 2
        config[key]['sdk_retries'] = 0
    resources = {k: v['resources'] for k, v in discovered['stages'].items()}
    runtime = {str(p.relative_to(REPO)): sha256(p.read_bytes()).hexdigest()
               for p in sorted((REPO / 'server/shuxueshuo_server/product').rglob('*.py'))}
    resources['source']['product_runtime'] = digest(runtime)
    version = digest({'code': runtime, 'domain': resources, 'uv': sha256((REPO / 'server/uv.lock').read_bytes()).hexdigest()})
    target, upstream = {}, {}
    for index, stage in enumerate(snapshot['stages']):
        key = stage['stage_key']
        target[key] = {'inputs': {'source_sha256': source['sha256'], 'revision': revision_id if index >= 2 else None},
            'resources': resources.get(key, {}), 'config': config.get(key, {}),
            'upstream': {k: upstream[k] for k in stage['depends_on']}}
        upstream[key] = digest(target[key])
    return {'dependencies': target, 'config': config, 'deployment_version': version}


class Application:
    def __init__(self, settings, service=None, context=None, discover=dependencies):
        self.settings = settings
        self.service = service or ProductService(engine(settings.url()), LocalArtifactStorage(settings.artifact_root))
        self.db = self.service.db
        self.discover = discover
        with transaction(self.db) as c:
            if c.scalar(text('SELECT version_num FROM alembic_version')) != '0002_product_runtime_indexes':
                raise Conflict('migration.upgrade_required')
            if context is None:
                user = row(c, m.users, key='internal')
                workspace = row(c, m.workspaces, slug='default')
                if not user or not workspace: raise Conflict('seed.missing')
                context = UserContext(workspace['id'], user['id'])
                member = row(c, m.workspace_members, workspace_id=context.workspace_id, user_id=context.user_id)
                if not member or member['role'] != 'owner':
                    raise Conflict('seed.owner_conflict')
        self.ctx = context

    def close(self):
        self.db.dispose()

    def request(self, operation, key, content, perform):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ProductError('request.idempotency_key_required')
        hashed = digest(jsonable_encoder(content))
        with transaction(self.db) as c:
            lock(c, 'request', str(self.ctx.workspace_id), str(self.ctx.user_id), operation, key)
            old = row(c, m.idempotency_requests, workspace_id=self.ctx.workspace_id, user_id=self.ctx.user_id, operation=operation, request_id=key)
            if old:
                if old['request_hash'] != hashed: raise Conflict('request.content_changed')
                return old['response_json']
            result = jsonable_encoder(perform())
            insert(c, m.idempotency_requests, workspace_id=self.ctx.workspace_id, user_id=self.ctx.user_id,
                   operation=operation, request_id=key, request_hash=hashed, response_json=result)
            return result

    def create_batch(self, key, name=None):
        return self.request('batch.create', key, {'name': name}, lambda: public(self.service.create_batch(self.ctx, name), 'id', 'name', 'created_at'))

    def upload(self, batch_id, key, content, filename, media_type):
        def perform():
            result = self.service.reference_upload(self.ctx, batch_id, content, filename, media_type)
            if result.get('item'):
                result['item'] = public(result['item'], 'id', 'batch_id', 'position', 'problem_id', 'source_id', 'initial_build_id')
                result['problem'] = self.get_problem(UUID(result['item']['problem_id']))
            return result
        return self.request('upload', key, {'batch_id': batch_id, 'sha256': sha256(content).hexdigest(),
                           'filename': filename, 'media_type': media_type}, perform)

    def resolve(self, source_id, problem_id, key):
        def perform():
            with transaction(self.db) as c:
                source = scoped(c, m.sources, self.ctx, source_id, lock=True)
                if source['owner_user_id'] != self.ctx.user_id: raise Forbidden('source.private')
                meta = source['metadata']
                if str(problem_id) not in meta.get('candidate_ids', []): raise Conflict('source.invalid_candidate')
                p = problem(c, self.ctx, problem_id, write=True)
                batch_id = UUID(meta['pending_batch_id'])
                batch = scoped(c, m.batches, self.ctx, batch_id, lock=True)
                if batch['owner_user_id'] != self.ctx.user_id: raise Forbidden('batch.private')
                existing = row(c, m.batch_items, source_id=source_id, batch_id=batch_id)
                if existing:
                    if existing['problem_id'] != problem_id: raise Conflict('source.already_resolved')
                    return {'status': 'reused', 'item': public(existing, 'id', 'batch_id', 'problem_id', 'source_id')}
                original = self.service.artifacts.verified(c, self.ctx, source['original_artifact_id'])
                candidates = c.execute(select(m.artifacts.c.sha256).select_from(m.problem_sources.join(m.sources,
                    m.sources.c.id == m.problem_sources.c.source_id).join(m.artifacts, m.artifacts.c.id == m.sources.c.original_artifact_id))
                    .where(m.problem_sources.c.problem_id == p['id'])).scalars().all()
                if original['sha256'] not in candidates: raise Conflict('source.candidates_changed')
                insert(c, m.problem_sources, workspace_id=self.ctx.workspace_id, problem_id=problem_id, source_id=source_id, match_method='manual')
                position = c.scalar(select(func.coalesce(func.max(m.batch_items.c.position), 0)).where(m.batch_items.c.batch_id == batch_id)) + 1
                item = insert(c, m.batch_items, workspace_id=self.ctx.workspace_id, batch_id=batch_id,
                              problem_id=problem_id, source_id=source_id, position=position)
                append_event(c, self.ctx.workspace_id, 'batch', batch_id, 'upload.resolved', {'problem_id': str(problem_id), 'item_id': str(item['id'])})
                return {'status': 'reused', 'item': public(item, 'id', 'batch_id', 'problem_id', 'source_id')}
        return self.request('source.resolve', key, {'source_id': source_id, 'problem_id': problem_id}, perform)

    def problem_summaries(self, c, records):
        if not records:
            return []
        joined = m.problems.outerjoin(m.problem_revisions, m.problems.c.current_revision_id == m.problem_revisions.c.id).outerjoin(
            m.sources, m.problems.c.primary_source_id == m.sources.c.id).outerjoin(m.builds, m.problems.c.latest_build_id == m.builds.c.id)
        details = {r['id']: r for r in c.execute(select(m.problems.c.id, m.problem_revisions.c.domain_json,
            m.sources.c.filename, m.builds.c.status).select_from(joined).where(
            m.problems.c.workspace_id == self.ctx.workspace_id, m.problems.c.id.in_([p['id'] for p in records]))).mappings()}
        return [{**public(p, 'id', 'title', 'primary_source_id', 'current_revision_id', 'latest_build_id', 'current_page_build_id', 'updated_at'),
            'statement_text': statement_text(details[p['id']]['domain_json']),
            'source_filename': details[p['id']]['filename'], 'latest_build_status': details[p['id']]['status']} for p in records]

    def list_problems(self, *, limit=50, before=None):
        records = self.service.list_problems(self.ctx, limit=limit, before=before)
        with transaction(self.db) as c:
            return self.problem_summaries(c, records)

    def get_problem(self, problem_id):
        with transaction(self.db) as c:
            p = problem(c, self.ctx, problem_id)
            stream = c.execute(select(m.event_streams).filter_by(workspace_id=self.ctx.workspace_id,
                stream_kind='problem', aggregate_id=problem_id).with_for_update()).mappings().first()
            return {**self.problem_summaries(c, [p])[0], 'last_seq': stream['last_seq'] if stream else 0}

    def batch(self, batch_id):
        with transaction(self.db) as c:
            batch = scoped(c, m.batches, self.ctx, batch_id)
            if batch['owner_user_id'] != self.ctx.user_id: raise Forbidden('batch.private')
            stream = c.execute(select(m.event_streams).filter_by(workspace_id=self.ctx.workspace_id, stream_kind='batch', aggregate_id=batch_id).with_for_update()).mappings().first()
            items = []
            for item in c.execute(select(m.batch_items).where(m.batch_items.c.batch_id == batch_id).order_by(m.batch_items.c.position)).mappings():
                p = problem(c, self.ctx, item['problem_id'])
                bid = item['initial_build_id'] or p['latest_build_id']
                b = row(c, m.builds, id=bid) if bid else None
                items.append({**public(item, 'id', 'position', 'problem_id', 'source_id', 'initial_build_id'),
                    'build_id': str(bid) if bid else None, 'status': b['status'] if b else 'unbuilt', 'current_page_build_id': str(p['current_page_build_id']) if p['current_page_build_id'] else None})
            return {**public(batch, 'id', 'name', 'created_at'), 'items': items, 'last_seq': stream['last_seq'] if stream else 0}

    def revision_preview(self, problem_id, base_id, domain):
        from shuxueshuo_server.review.problem_edit import validate, diff
        base = self.service.get_revision(self.ctx, problem_id, base_id)
        if self.service.get_problem(self.ctx, problem_id)['current_revision_id'] != base_id: raise Conflict('revision.base_changed')
        checked, verified = validate(domain, {'verified': base['verified_json'], 'domain': base['domain_json']})
        return {'ok': checked.ok, 'base_revision_id': str(base_id), 'diagnostics': checked.report.to_payload(),
                'diff': diff(base['domain_json'], checked.draft.graph.wire_payload()),
                'affected_stages': [s['stage_key'] for s in self.service.registry.get('problem_lesson', 'v1')['stages'][2:]] if verified and base['semantic_hash'] != verified.semantic_hash else []}

    def save_revision(self, problem_id, base_id, domain, key):
        return self.request('revision.save', key, {'problem_id': problem_id, 'base_id': base_id, 'domain': domain},
            lambda: public(self.service.save_revision(self.ctx, problem_id, base_id, domain), 'id', 'revision_no', 'kind', 'domain_json', 'semantic_hash'))

    def environment(self, problem_id, source_id=None):
        with transaction(self.db) as c:
            p = problem(c, self.ctx, problem_id, write=True)
            source = scoped(c, m.sources, self.ctx, source_id or p['primary_source_id'])
            original = self.service.artifacts.verified(c, self.ctx, source['original_artifact_id'])
            revision = row(c, m.problem_revisions, id=p['current_revision_id']) if p['current_revision_id'] else None
        snapshot = self.service.registry.get('problem_lesson', 'v1')
        # Fingerprint every current revision (manual or extracted). Leaving extracted
        # revisions as null lets rebuild reuse a stale extraction checkpoint while
        # bind_requested_revision attaches a newer meaning.
        revision_input = (
            {'id': str(revision['id']), 'semantic_hash': revision['semantic_hash'], 'kind': revision['kind']}
            if revision else None
        )
        return p, source, self.discover(original, revision_input, snapshot)

    def submit(self, problem_id, source_id, batch_item_id, key):
        p, source, target = self.environment(problem_id, source_id)
        # The outer request stores the caller's intent, not a freshly observed version on replay.
        return self.request('build.create', key, {'problem_id': problem_id, 'source_id': source_id, 'batch_item_id': batch_item_id},
            lambda: self.service.submit_build(self.ctx, problem_id, request_id='api:' + key,
                source_id=source['id'], base_revision_id=p['current_revision_id'], batch_item_id=batch_item_id, **target))

    def rebuild_preview(self, build_id, requested_stage=None):
        original = self.service.build_snapshot(self.ctx, build_id)['build']
        p, source, target = self.environment(original['problem_id'], original['source_id'])
        snapshot = self.service.registry.get('problem_lesson', 'v1')
        keys = [s['stage_key'] for s in snapshot['stages']]
        if requested_stage is not None and requested_stage not in keys: raise Conflict('pipeline.repreview_required')
        reasons, reuse = [], []
        with transaction(self.db) as c:
            rows = {r['stage_key']: r for r in c.execute(select(m.build_stages).where(m.build_stages.c.build_id == build_id)).mappings()}
            current_revision = str(p['current_revision_id']) if p['current_revision_id'] else None
            resolved_revision = str(original['resolved_revision_id']) if original.get('resolved_revision_id') else None
            for key in keys:
                stage = rows.get(key)
                if not stage or stage['status'] != 'succeeded': reasons.append({'stage': key, 'code': 'stage.incomplete'})
                elif original['target_dependencies'].get(key) != target['dependencies'][key]: reasons.append({'stage': key, 'code': 'build.dependencies_changed'})
                elif key == 'extraction' and resolved_revision != current_revision:
                    # Parent extraction produced a different meaning than the rebuild request.
                    reasons.append({'stage': key, 'code': 'build.revision_changed'})
                else:
                    attempt = row(c, m.stage_attempts, id=stage['accepted_attempt_id'])
                    try: self.service._verify_accepted_provenance(c, self.ctx, attempt, p['id'])
                    except (ProductError, OSError): reasons.append({'stage': key, 'code': 'checkpoint.unavailable'})
            if requested_stage: reasons.append({'stage': requested_stage, 'code': 'user.requested'})
        rerun = affected(snapshot, [r['stage'] for r in reasons])
        reuse = [k for k in keys if k not in rerun]
        if reuse:
            from pathlib import Path
            from tempfile import TemporaryDirectory
            from .execution import ExecutionContext
            with TemporaryDirectory(prefix='preview-', dir=self.settings.root / 'work') as directory:
                decoder = ExecutionContext.preview(self, original, Path(directory))
                for key in reuse:
                    with transaction(self.db) as c:
                        attempt = row(c, m.stage_attempts, id=rows[key]['accepted_attempt_id'])
                    try: decoder.restore(rows[key], attempt)
                    except (ProductError, ValueError, KeyError, TypeError, OSError):
                        reasons.append({'stage': key, 'code': 'checkpoint.typed_validation_failed'})
                        rerun = affected(snapshot, [r['stage'] for r in reasons])
                        reuse = [k for k in keys if k not in rerun]
                        break
        result = {'build_id': str(build_id), 'problem_id': str(p['id']), 'base_revision_id': str(p['current_revision_id']) if p['current_revision_id'] else None,
            'requested_stage': requested_stage, 'reuse_stages': reuse, 'rerun_stages': rerun, 'reasons': reasons,
            'model_stages': [k for k in rerun if k in ('extraction', 'solver', 'lesson')],
            'available': bool(rerun) and original['status'] in ('succeeded', 'failed', 'interrupted', 'cancelled'), 'target': target}
        result['fingerprint'] = digest(result)
        return result

    def rebuild(self, build_id, requested_stage, preview_fingerprint, key):
        preview = self.rebuild_preview(build_id, requested_stage)
        def perform():
            if not preview['available'] or preview['fingerprint'] != preview_fingerprint: raise Conflict('build.repreview_required')
            original = self.service.build_snapshot(self.ctx, build_id)['build']
            if self.rebuild_preview(build_id, requested_stage)['fingerprint'] != preview_fingerprint: raise Conflict('build.repreview_required')
            return self.service.submit_build(self.ctx, original['problem_id'], request_id='api:' + key,
                source_id=original['source_id'], base_revision_id=UUID(preview['base_revision_id']) if preview['base_revision_id'] else None,
                parent_build_id=build_id, from_stage=preview['rerun_stages'][0], **preview['target'])
        return self.request('build.rebuild', key, {'build_id': build_id, 'fingerprint': preview_fingerprint, 'stage': requested_stage}, perform)

    def build(self, build_id):
        snapshot = self.service.build_snapshot(self.ctx, build_id)
        with transaction(self.db) as c:
            b = snapshot['build']
            p = problem(c, self.ctx, b['problem_id'])
            page = row(c, m.page_builds, build_id=build_id)
            labels = {}
            stream = row(c, m.event_streams, workspace_id=self.ctx.workspace_id, stream_kind='build', aggregate_id=build_id)
            if stream:
                labels = {event['artifact_id']: event for event in c.execute(select(m.events.c.payload).where(
                    m.events.c.stream_id == stream['id'], m.events.c.event_type == 'artifact.registered')).scalars()}
            artifacts = []
            attempts = []
            for stage in snapshot['stages']:
                for attempt in c.execute(select(m.stage_attempts).where(m.stage_attempts.c.build_stage_id == stage['id']).order_by(m.stage_attempts.c.attempt_no)).mappings():
                    attempts.append(public(attempt, 'id', 'build_stage_id', 'attempt_no', 'kind', 'status', 'started_at', 'finished_at'))
                    # Include unfinished attempts for live diagnosis, without exposing storage keys.
                    refs = self.service._attempt_outputs(c, attempt['id'])
                    if not refs:
                        refs = [{'artifact_id': a['id'], 'name': labels.get(str(a['id']), {}).get('name', a['artifact_type']),
                            'role': labels.get(str(a['id']), {}).get('role', 'raw')} for a in c.execute(select(m.artifacts).where(m.artifacts.c.producer_attempt_id == attempt['id'])).mappings()]
                    for ref in refs:
                        a = row(c, m.artifacts, id=ref['artifact_id'])
                        artifacts.append({**public(a, 'id', 'artifact_type', 'content_type', 'size_bytes', 'sha256'),
                            'stage_key': stage['stage_key'], 'attempt_id': str(attempt['id']), 'name': ref['name'], 'role': ref['role']})
            return {**public(b, 'id', 'problem_id', 'source_id', 'parent_build_id', 'status', 'created_at', 'started_at', 'finished_at',
                'requested_revision_id', 'resolved_revision_id', 'error_code', 'pipeline_key', 'pipeline_version'),
                'stages': [public(s, 'id', 'stage_key', 'title', 'ordinal', 'status', 'summary') for s in snapshot['stages']],
                'attempts': attempts, 'artifacts': artifacts, 'last_seq': snapshot['last_seq'],
                'reviews': [public(r, 'id', 'decision', 'comment', 'created_at', 'supersedes_id') for r in c.execute(
                    select(m.review_decisions).where(m.review_decisions.c.page_build_id == page['id']).order_by(m.review_decisions.c.created_at)).mappings()] if page else [],
                'page_id': str(page['id']) if page else None,
                'page_current': bool(page and page['id'] == p['current_page_build_id'])}

    def events(self, kind, aggregate_id, after=0):
        records = self.service.read_events(self.ctx, kind, aggregate_id, after=after)
        with transaction(self.db) as c:
            stream = row(c, m.event_streams, workspace_id=self.ctx.workspace_id, stream_kind=kind, aggregate_id=aggregate_id)
            if stream and (after < stream['min_retained_seq'] - 1 or after > stream['last_seq']): raise Conflict('events.resnapshot_required')
        return [public(e, 'seq', 'event_type', 'schema_version', 'payload', 'created_at') for e in records]


def load_application():
    import os
    return Application(Settings.load(os.environ.get('PRODUCT_MODE', 'local'), instance=os.environ.get('PRODUCT_INSTANCE')))
