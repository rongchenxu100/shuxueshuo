"""Product use cases. External calls and expensive domain validation precede transactions."""
from .pipelines import CURRENT_PIPELINE_VERSION
from datetime import timedelta
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
import json
import re

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from . import models as m
from .db import transaction, lock, digest
from .errors import Conflict, Forbidden, IntegrityFailure, ProductError
from .pipelines import PipelineRegistry, fingerprint, reusable, validate
from .repositories import ArtifactRepository, UserContext, insert, row, member, scoped, problem
from .storage import parts


def clean_config(value):
    if isinstance(value, dict):
        public_fields = {'stage_key', 'pipeline_key', 'artifact_key', 'max_tokens', 'input_tokens', 'output_tokens',
                         'prompt_tokens', 'completion_tokens', 'total_tokens', 'max_output_tokens'}
        return {str(k): '[REDACTED]' if str(k) not in public_fields and re.search(r'key|password|secret|token|authorization|cookie', str(k), re.I)
                else clean_config(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean_config(v) for v in value]
    if isinstance(value, str) and re.search(r'(?i)(bearer\s|sk-[\w-]+|://[^/\s]+:[^/\s]+@)', value):
        return '[REDACTED]'
    return value


def now(c):
    return c.scalar(select(func.clock_timestamp()))


def update(c, t, resource_id, **values):
    c.execute(t.update().where(t.c.id == resource_id).values(**values))


def append_event(c, workspace_id, kind, aggregate_id, event_type, payload):
    streams = {(kind, aggregate_id)}
    problem_id = aggregate_id if kind == 'problem' else None
    if kind == 'build':
        problem_id = c.scalar(select(m.builds.c.problem_id).where(m.builds.c.id == aggregate_id))
    if problem_id:
        streams.update(('batch', bid) for bid in c.scalars(select(m.batch_items.c.batch_id).where(m.batch_items.c.problem_id == problem_id).distinct()))
    result = None
    for stream_kind, identity in sorted(streams, key=lambda x: (x[0], str(x[1]))):
        value = _append_event(c, workspace_id, stream_kind, identity, event_type,
            payload if (stream_kind, identity) == (kind, aggregate_id) else
            {'aggregate_kind': kind, 'aggregate_id': str(aggregate_id), **payload})
        if (stream_kind, identity) == (kind, aggregate_id): result = value
    return result


def _append_event(c, workspace_id, kind, aggregate_id, event_type, payload):
    c.execute(pg_insert(m.event_streams).values(workspace_id=workspace_id, stream_kind=kind,
        aggregate_id=aggregate_id).on_conflict_do_nothing(index_elements=['workspace_id', 'stream_kind', 'aggregate_id']))
    stream = c.execute(select(m.event_streams).filter_by(workspace_id=workspace_id,
        stream_kind=kind, aggregate_id=aggregate_id).with_for_update()).mappings().one()
    seq = stream['last_seq'] + 1
    update(c, m.event_streams, stream['id'], last_seq=seq)
    return insert(c, m.events, workspace_id=workspace_id, stream_id=stream['id'], seq=seq,
                  event_type=event_type, schema_version='product-event/v1', payload=clean_config(payload))


class ProductService:
    def __init__(self, db, storage, registry=None):
        self.db, self.storage = db, storage
        self.artifacts = ArtifactRepository(storage)
        self.registry = registry or PipelineRegistry()

    def create_batch(self, ctx, name=None):
        with transaction(self.db) as c:
            member(c, ctx)
            batch = insert(c, m.batches, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id, name=name)
            append_event(c, ctx.workspace_id, 'batch', batch['id'], 'batch.created', {})
            return dict(batch)

    def get_problem(self, ctx, problem_id):
        with transaction(self.db) as c:
            return dict(problem(c, ctx, problem_id))

    def list_problems(self, ctx, *, limit=50, before=None):
        from sqlalchemy import or_, and_
        if not 1 <= limit <= 100:
            raise ProductError('query.limit')
        with transaction(self.db) as c:
            member(c, ctx)
            query = select(m.problems).where(m.problems.c.workspace_id == ctx.workspace_id,
                or_(m.problems.c.owner_user_id == ctx.user_id, m.problems.c.visibility == 'workspace'))
            if before:
                timestamp, identity = before
                query = query.where(or_(m.problems.c.updated_at < timestamp,
                    and_(m.problems.c.updated_at == timestamp, m.problems.c.id < identity)))
            return [dict(r) for r in c.execute(query.order_by(m.problems.c.updated_at.desc(), m.problems.c.id.desc()).limit(limit)).mappings()]

    def get_revision(self, ctx, problem_id, revision_id):
        with transaction(self.db) as c:
            problem(c, ctx, problem_id)
            revision = scoped(c, m.problem_revisions, ctx, revision_id)
            if revision['problem_id'] != problem_id:
                raise Forbidden('revision.wrong_problem')
            return dict(revision)

    def build_history(self, ctx, problem_id, limit=50):
        if not 1 <= limit <= 100:
            raise ProductError('query.limit')
        with transaction(self.db) as c:
            problem(c, ctx, problem_id)
            return [dict(r) for r in c.execute(select(m.builds).filter_by(workspace_id=ctx.workspace_id, problem_id=problem_id)
                .order_by(m.builds.c.created_at.desc(), m.builds.c.id.desc()).limit(limit)).mappings()]

    def reference_upload(self, ctx, batch_id, content, filename, media_type):
        from PIL import Image
        if not content or len(content) > 20 * 1024 * 1024:
            raise ProductError('upload.size')
        with Image.open(BytesIO(content)) as image:
            detected = Image.MIME.get(image.format)
            if detected not in ('image/png', 'image/jpeg', 'image/webp') or detected != media_type:
                raise ProductError('upload.media_type')
            if image.width * image.height > 25_000_000 or getattr(image, 'n_frames', 1) != 1:
                raise ProductError('upload.image')
            metadata = {'width': image.width, 'height': image.height}
            image.verify()
        from hashlib import sha256
        file_hash = sha256(content).hexdigest()
        filename = PurePosixPath(filename.replace('\\', '/')).name
        with transaction(self.db) as c:
            batch = scoped(c, m.batches, ctx, batch_id, lock=True)
            if batch['owner_user_id'] != ctx.user_id:
                raise Forbidden('batch.private')
            lock(c, 'upload', str(ctx.workspace_id), str(ctx.user_id), file_hash)
            candidates = c.execute(select(m.problems.c.id, m.sources.c.id.label('source_id')).select_from(
                m.problems.join(m.problem_sources, m.problem_sources.c.problem_id == m.problems.c.id)
                .join(m.sources, m.sources.c.id == m.problem_sources.c.source_id)
                .join(m.artifacts, m.artifacts.c.id == m.sources.c.original_artifact_id)).where(
                    m.problems.c.workspace_id == ctx.workspace_id, m.problems.c.owner_user_id == ctx.user_id,
                    m.sources.c.owner_user_id == ctx.user_id, m.artifacts.c.sha256 == file_hash)).mappings().all()
            ids = sorted({str(x['id']) for x in candidates})
            audit = {'filename': filename, 'media_type': detected, 'file_sha256': file_hash}
            if len(ids) > 1:
                sid, aid = uuid4(), uuid4()
                key = f'workspaces/{ctx.workspace_id}/sources/{sid}/{aid}'
                stored = self.storage.put_immutable(key, BytesIO(content), file_hash)
                self.artifacts.register(dict(id=aid, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id,
                    artifact_type='source_original', storage_key=key, sha256=stored.sha256, size_bytes=stored.size_bytes,
                    content_type=detected, access_class='private'), c)
                insert(c, m.sources, id=sid, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id,
                    original_artifact_id=aid, filename=filename, media_type=detected,
                    metadata={**metadata, 'pending_batch_id': str(batch_id), 'candidate_ids': ids})
                append_event(c, ctx.workspace_id, 'batch', batch_id, 'upload.ambiguous', {**audit, 'source_id': str(sid), 'candidates': ids})
                return {'status': 'ambiguous', 'source_id': str(sid), 'candidate_ids': ids}
            if candidates:
                chosen = sorted(candidates, key=lambda x: str(x['source_id']))[0]
                problem_id, source_id = chosen['id'], chosen['source_id']
                source = scoped(c, m.sources, ctx, source_id)
                self.artifacts.verified(c, ctx, source['original_artifact_id'])
                status = 'reused'
            else:
                source_id, artifact_id, problem_id = uuid4(), uuid4(), uuid4()
                key = f'workspaces/{ctx.workspace_id}/sources/{source_id}/{artifact_id}'
                stored = self.storage.put_immutable(key, BytesIO(content), file_hash)
                self.artifacts.register(dict(id=artifact_id, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id,
                    artifact_type='source_original', storage_key=key, sha256=stored.sha256, size_bytes=stored.size_bytes,
                    content_type=detected, access_class='private'), c)
                insert(c, m.sources, id=source_id, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id,
                       original_artifact_id=artifact_id, filename=filename, media_type=detected, metadata=metadata)
                insert(c, m.problems, id=problem_id, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id, primary_source_id=source_id)
                insert(c, m.problem_sources, workspace_id=ctx.workspace_id, problem_id=problem_id, source_id=source_id, match_method='initial')
                status = 'created'
            position = c.scalar(select(func.coalesce(func.max(m.batch_items.c.position), 0)).where(m.batch_items.c.batch_id == batch_id)) + 1
            item = insert(c, m.batch_items, workspace_id=ctx.workspace_id, batch_id=batch_id, position=position,
                          problem_id=problem_id, source_id=source_id)
            append_event(c, ctx.workspace_id, 'batch', batch_id, 'upload.' + status,
                         {**audit, 'batch_item_id': str(item['id']), 'problem_id': str(problem_id)})
            return {'status': status, 'item': dict(item)}

    def save_revision(self, ctx, problem_id, base_revision_id, domain, *, origin_build_id=None, execution_id=None, epoch=None):
        from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft, ProblemPromotionService
        from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
        with transaction(self.db) as c:
            p = problem(c, ctx, problem_id, write=True)
            base = row(c, m.problem_revisions, id=base_revision_id, problem_id=problem_id) if base_revision_id else None
            if p['current_revision_id'] != base_revision_id:
                raise Conflict('revision.base_changed')
        draft = ProblemDraft.create(domain, parent_revision_id=base['verified_json']['revision_id'] if base else None)
        checked = ProblemDomainValidator().validate(draft, expected_problem_id=base['domain_json']['problem_id'] if base else domain.get('problem_id'))
        if not checked.ok:
            raise ProductError('revision.validation_failed')
        verified = ProblemPromotionService().promote(checked.draft).to_payload()
        from shuxueshuo_server.review.problem_edit import diff
        with transaction(self.db) as c:
            p = problem(c, ctx, problem_id, write=True, lock=True)
            if p['current_revision_id'] != base_revision_id:
                raise Conflict('revision.base_changed')
            build = None
            if origin_build_id:
                build, _ = self._guard(c, ctx, origin_build_id, execution_id, epoch)
                if build['problem_id'] != problem_id:
                    raise Conflict('revision.wrong_build')
                if p['latest_build_id'] != origin_build_id:
                    raise Conflict('revision.extraction_superseded')
                if build['requested_revision_id'] != base_revision_id:
                    raise Conflict('revision.build_base_changed')
            if base and base['semantic_hash'] == verified['semantic_hash']:
                if build:
                    self._bind_revision(c, ctx, build, base['id'])
                return dict(base)
            if build and build['resolved_revision_id'] is not None:
                raise Conflict('build.revision_already_bound')
            revision = insert(c, m.problem_revisions, workspace_id=ctx.workspace_id, problem_id=problem_id,
                revision_no=(base['revision_no'] + 1 if base else 1), parent_revision_id=base_revision_id,
                kind='extracted' if build or not base else 'manual', domain_json=verified['graph'], verified_json=verified,
                semantic_hash=verified['semantic_hash'], schema_version=verified['graph']['schema_version'],
                human_diff=diff(base['domain_json'], verified['graph']) if base and not build else None,
                created_by_user_id=ctx.user_id, origin_build_id=origin_build_id)
            update(c, m.problems, problem_id, current_revision_id=revision['id'], current_page_build_id=None,
                   lock_version=p['lock_version'] + 1, updated_at=now(c))
            if build:
                self._bind_revision(c, ctx, build, revision['id'])
            append_event(c, ctx.workspace_id, 'problem', problem_id, 'revision.saved', {'revision_id': str(revision['id'])})
            return dict(revision)

    def _bind_revision(self, c, ctx, build, revision_id):
        if build['resolved_revision_id'] == revision_id:
            return
        if build['resolved_revision_id'] is not None:
            raise Conflict('build.revision_already_bound')
        update(c, m.builds, build['id'], resolved_revision_id=revision_id)
        c.execute(m.problem_sources.update().where(m.problem_sources.c.problem_id == build['problem_id'],
            m.problem_sources.c.source_id == build['source_id'], m.problem_sources.c.matched_revision_id.is_(None))
            .values(matched_revision_id=revision_id))
        append_event(c, ctx.workspace_id, 'build', build['id'], 'build.revision_bound', {'revision_id': str(revision_id)})

    def bind_requested_revision(self, ctx, build_id, execution_id, epoch):
        """Explicitly accept the frozen revision when extraction is skipped/reused."""
        with transaction(self.db) as c:
            build, _ = self._guard(c, ctx, build_id, execution_id, epoch)
            if build['requested_revision_id'] is None:
                raise Conflict('build.requested_revision_missing')
            revision = scoped(c, m.problem_revisions, ctx, build['requested_revision_id'])
            if revision['problem_id'] != build['problem_id']:
                raise Conflict('revision.wrong_build')
            self._bind_revision(c, ctx, build, revision['id'])
            return dict(revision)

    def submit_build(self, ctx, problem_id, *, request_id, source_id, base_revision_id,
                     dependencies, config, deployment_version, from_stage='source', pipeline_key='problem_lesson',
                     pipeline_version=CURRENT_PIPELINE_VERSION, parent_build_id=None, batch_item_id=None, retry_budget=None):
        snapshot = self.registry.get(pipeline_key, pipeline_version)
        if from_stage not in {s['stage_key'] for s in snapshot['stages']}:
            raise Conflict('pipeline.repreview_required')
        if not deployment_version or not isinstance(dependencies, dict):
            raise ProductError('build.frozen_inputs_required')
        config = clean_config(config)
        request = dict(problem_id=str(problem_id), source_id=str(source_id), base_revision_id=str(base_revision_id),
            dependencies=dependencies, config=config, deployment_version=deployment_version, from_stage=from_stage,
            pipeline_key=pipeline_key, pipeline_version=pipeline_version, parent_build_id=str(parent_build_id),
            batch_item_id=str(batch_item_id), retry_budget=retry_budget or {'deliveries': 3})
        request_hash = digest(request)
        with transaction(self.db) as c:
            member(c, ctx)
            lock(c, 'request', str(ctx.workspace_id), str(ctx.user_id), 'build', request_id)
            existing = row(c, m.idempotency_requests, workspace_id=ctx.workspace_id, user_id=ctx.user_id, operation='build', request_id=request_id)
            if existing:
                if existing['request_hash'] != request_hash:
                    raise Conflict('request.content_changed')
                problem(c, ctx, problem_id, write=True)
                return existing['response_json']
            p = problem(c, ctx, problem_id, write=True, lock=True)
            if p['current_revision_id'] != base_revision_id:
                raise Conflict('revision.base_changed')
            source = scoped(c, m.sources, ctx, source_id)
            self.artifacts.verified(c, ctx, source['original_artifact_id'])
            if not row(c, m.problem_sources, workspace_id=ctx.workspace_id, problem_id=problem_id, source_id=source_id):
                raise Conflict('source.not_linked')
            if parent_build_id:
                parent = scoped(c, m.builds, ctx, parent_build_id)
                if parent['problem_id'] != problem_id:
                    raise Conflict('build.wrong_parent')
            if batch_item_id:
                item = scoped(c, m.batch_items, ctx, batch_item_id, lock=True)
                batch = scoped(c, m.batches, ctx, item['batch_id'])
                if batch['owner_user_id'] != ctx.user_id or item['problem_id'] != problem_id or item['source_id'] != source_id:
                    raise Conflict('batch_item.initial_build_conflict')
                if item['initial_build_id']:
                    old = scoped(c, m.builds, ctx, item['initial_build_id'])
                    if any(old[k] != v for k, v in {'requested_revision_id': base_revision_id, 'effective_config': config,
                        'target_dependencies': dependencies, 'deployment_version': deployment_version, 'pipeline_key': pipeline_key,
                        'pipeline_version': pipeline_version, 'parent_build_id': parent_build_id, 'from_stage': from_stage}.items()):
                        raise Conflict('batch_item.initial_build_conflict')
                    job = row(c, m.jobs, build_id=old['id'])
                    response = {'build_id': str(old['id']), 'job_id': str(job['id'])}
                    insert(c, m.idempotency_requests, workspace_id=ctx.workspace_id, user_id=ctx.user_id, operation='build',
                        request_id=request_id, request_hash=request_hash, resource_type='build', resource_id=old['id'], response_json=response)
                    return response
            lock(c, 'pipeline', pipeline_key, pipeline_version)
            prior = c.execute(select(m.builds.c.pipeline_snapshot).where(m.builds.c.pipeline_key == pipeline_key,
                m.builds.c.pipeline_version == pipeline_version).limit(1)).scalar()
            if prior is not None and prior != snapshot:
                raise Conflict('pipeline.version_redefined')
            build = insert(c, m.builds, workspace_id=ctx.workspace_id, problem_id=problem_id, source_id=source_id,
                parent_build_id=parent_build_id, requested_revision_id=base_revision_id, resolved_revision_id=None,
                pipeline_key=pipeline_key, pipeline_version=pipeline_version, pipeline_snapshot=snapshot, from_stage=from_stage,
                target_dependencies=dependencies, effective_config=config, deployment_version=deployment_version,
                target_fingerprint=fingerprint(pipeline_key, pipeline_version, snapshot, dependencies, config,
                    {'source_id': str(source_id), 'revision_id': str(base_revision_id)}), status='queued')
            for s in snapshot['stages']:
                insert(c, m.build_stages, workspace_id=ctx.workspace_id, build_id=build['id'], stage_key=s['stage_key'], ordinal=s['ordinal'], status='pending')
            budget = request['retry_budget']
            if type(budget.get('deliveries')) is not int or budget['deliveries'] < 1:
                raise ProductError('job.invalid_budget')
            job = insert(c, m.jobs, workspace_id=ctx.workspace_id, build_id=build['id'], status='queued', retry_budget=budget)
            current_page_id = p['current_page_build_id']
            if current_page_id:
                page = row(c, m.page_builds, id=current_page_id)
                page_build = row(c, m.builds, id=page['build_id'])
                if page_build['target_fingerprint'] != build['target_fingerprint']:
                    current_page_id = None
            update(c, m.problems, problem_id, latest_build_id=build['id'], current_page_build_id=current_page_id,
                   lock_version=p['lock_version'] + 1, updated_at=now(c))
            if batch_item_id:
                item = scoped(c, m.batch_items, ctx, batch_item_id, lock=True)
                batch = scoped(c, m.batches, ctx, item['batch_id'])
                if batch['owner_user_id'] != ctx.user_id or item['problem_id'] != problem_id or item['source_id'] != source_id or item['initial_build_id']:
                    raise Conflict('batch_item.initial_build_conflict')
                update(c, m.batch_items, batch_item_id, initial_build_id=build['id'])
            response = {'build_id': str(build['id']), 'job_id': str(job['id'])}
            insert(c, m.idempotency_requests, workspace_id=ctx.workspace_id, user_id=ctx.user_id, operation='build',
                   request_id=request_id, request_hash=request_hash, resource_type='build', resource_id=build['id'], response_json=response)
            append_event(c, ctx.workspace_id, 'build', build['id'], 'build.queued', response)
            insert(c, m.outbox_messages, workspace_id=ctx.workspace_id, job_id=job['id'], message_type='job.execute',
                   protocol_version='product-job/v1', payload=response, dedupe_key='execute:' + str(job['id']), available_at=now(c))
            return response

    def _guard(self, c, ctx, build_id, execution_id, epoch):
        build = scoped(c, m.builds, ctx, build_id)
        problem(c, ctx, build['problem_id'], write=True)
        job = c.execute(select(m.jobs).where(m.jobs.c.build_id == build_id).with_for_update()).mappings().one()
        if job['status'] != 'running' or job['cancel_requested_at'] or job['active_execution_id'] != execution_id or job['execution_epoch'] != epoch or not job['lease_expires_at'] or job['lease_expires_at'] <= now(c):
            raise Conflict('execution.fenced')
        execution = row(c, m.job_executions, id=execution_id)
        if not execution or execution['status'] != 'running':
            raise Conflict('execution.not_running')
        # A competing binding may have committed while this transaction waited for the job lock.
        return scoped(c, m.builds, ctx, build_id), job

    def acquire_execution(self, ctx, job_id, worker_id, *, deployment_version, lease_seconds=60):
        if not 1 <= lease_seconds <= 3600:
            raise ProductError('execution.lease')
        with transaction(self.db) as c:
            job = scoped(c, m.jobs, ctx, job_id, lock=True)
            build = scoped(c, m.builds, ctx, job['build_id'])
            problem(c, ctx, build['problem_id'], write=True)
            if build['deployment_version'] != deployment_version or self.registry.get(build['pipeline_key'], build['pipeline_version']) != build['pipeline_snapshot']:
                raise Conflict('execution.incompatible_environment')
            timestamp = now(c)
            if job['status'] not in ('queued', 'running', 'interrupted') or job['cancel_requested_at']:
                raise Conflict('job.terminal')
            if job['status'] == 'running' and job['lease_expires_at'] > timestamp:
                raise Conflict('execution.already_owned')
            if job['delivery_count'] >= job['retry_budget']['deliveries']:
                if job['active_execution_id']:
                    update(c, m.job_executions, job['active_execution_id'], status='interrupted', finished_at=timestamp, failure_code='job.budget_exhausted')
                    c.execute(m.stage_attempts.update().where(m.stage_attempts.c.execution_id == job['active_execution_id'],
                        m.stage_attempts.c.status == 'running').values(status='interrupted', finished_at=timestamp))
                update(c, m.jobs, job_id, status='failed', lease_expires_at=None)
                update(c, m.builds, build['id'], status='failed', finished_at=timestamp, error_code='job.budget_exhausted')
                c.execute(m.build_stages.update().where(m.build_stages.c.build_id == build['id'],
                    m.build_stages.c.status != 'succeeded').values(status='failed'))
                append_event(c, ctx.workspace_id, 'build', build['id'], 'build.failed', {'code': 'job.budget_exhausted'})
                return {'status': 'failed', 'code': 'job.budget_exhausted'}
            if job['active_execution_id']:
                update(c, m.job_executions, job['active_execution_id'], status='interrupted', finished_at=timestamp, failure_code='execution.lease_expired')
                c.execute(m.stage_attempts.update().where(m.stage_attempts.c.execution_id == job['active_execution_id'],
                    m.stage_attempts.c.status == 'running').values(status='interrupted', finished_at=timestamp))
                c.execute(m.build_stages.update().where(m.build_stages.c.build_id == build['id'],
                    m.build_stages.c.status == 'running').values(status='interrupted'))
            execution = insert(c, m.job_executions, workspace_id=ctx.workspace_id, job_id=job_id, epoch=job['execution_epoch'] + 1,
                worker_id=worker_id, status='running', started_at=timestamp, heartbeat_at=timestamp)
            update(c, m.jobs, job_id, status='running', execution_epoch=execution['epoch'], active_execution_id=execution['id'],
                   lease_expires_at=timestamp + timedelta(seconds=lease_seconds), delivery_count=job['delivery_count'] + 1)
            update(c, m.builds, build['id'], status='running', started_at=build['started_at'] or timestamp)
            append_event(c, ctx.workspace_id, 'build', build['id'], 'execution.started', {'epoch': execution['epoch']})
            return dict(execution)

    def heartbeat(self, ctx, build_id, execution_id, epoch, lease_seconds=60):
        if not 1 <= lease_seconds <= 3600:
            raise ProductError('execution.lease')
        with transaction(self.db) as c:
            _, job = self._guard(c, ctx, build_id, execution_id, epoch)
            timestamp = now(c)
            update(c, m.jobs, job['id'], lease_expires_at=timestamp + timedelta(seconds=lease_seconds))
            update(c, m.job_executions, execution_id, heartbeat_at=timestamp)

    def cancel(self, ctx, build_id):
        with transaction(self.db) as c:
            build = scoped(c, m.builds, ctx, build_id)
            problem(c, ctx, build['problem_id'], write=True)
            job = c.execute(select(m.jobs).where(m.jobs.c.build_id == build_id).with_for_update()).mappings().one()
            if job['status'] in ('succeeded', 'failed', 'cancelled'):
                return
            timestamp = now(c)
            update(c, m.jobs, job['id'], status='cancelled', cancel_requested_at=timestamp, lease_expires_at=None)
            update(c, m.builds, build_id, status='cancelled', finished_at=timestamp)
            if job['active_execution_id']:
                update(c, m.job_executions, job['active_execution_id'], status='cancelled', finished_at=timestamp)
                c.execute(m.stage_attempts.update().where(m.stage_attempts.c.execution_id == job['active_execution_id'],
                    m.stage_attempts.c.status == 'running').values(status='cancelled', finished_at=timestamp))
            c.execute(m.build_stages.update().where(m.build_stages.c.build_id == build_id,
                m.build_stages.c.status != 'succeeded').values(status='cancelled'))
            append_event(c, ctx.workspace_id, 'build', build_id, 'build.cancelled', {})

    def finish_failure(self, ctx, build_id, execution_id, epoch, code, *, interrupted=False):
        with transaction(self.db) as c:
            _, job = self._guard(c, ctx, build_id, execution_id, epoch)
            status = 'interrupted' if interrupted else 'failed'
            update(c, m.jobs, job['id'], status=status, lease_expires_at=None)
            update(c, m.builds, build_id, status=status, error_code=code, finished_at=now(c))
            update(c, m.job_executions, execution_id, status=status, failure_code=code, finished_at=now(c))
            c.execute(m.stage_attempts.update().where(m.stage_attempts.c.execution_id == execution_id,
                m.stage_attempts.c.status == 'running').values(status=status, finished_at=now(c)))
            c.execute(m.build_stages.update().where(m.build_stages.c.build_id == build_id,
                m.build_stages.c.status != 'succeeded').values(status=status))
            append_event(c, ctx.workspace_id, 'build', build_id, 'build.' + status, {'code': code})

    def fail_incompatible_deployment(self, ctx, build_id, code='execution.incompatible_environment'):
        """Fail queued/running builds that a restarted deployment can no longer execute."""
        with transaction(self.db) as c:
            build = scoped(c, m.builds, ctx, build_id)
            problem(c, ctx, build['problem_id'], write=True)
            job = c.execute(select(m.jobs).where(m.jobs.c.build_id == build_id).with_for_update()).mappings().one()
            if job['status'] in ('succeeded', 'failed', 'cancelled'):
                return dict(job)
            timestamp = now(c)
            if job['active_execution_id']:
                update(c, m.job_executions, job['active_execution_id'], status='failed', finished_at=timestamp, failure_code=code)
                c.execute(m.stage_attempts.update().where(m.stage_attempts.c.execution_id == job['active_execution_id'],
                    m.stage_attempts.c.status == 'running').values(status='failed', finished_at=timestamp))
            update(c, m.jobs, job['id'], status='failed', lease_expires_at=None)
            update(c, m.builds, build_id, status='failed', error_code=code, finished_at=timestamp)
            c.execute(m.build_stages.update().where(m.build_stages.c.build_id == build_id,
                m.build_stages.c.status != 'succeeded').values(status='failed'))
            append_event(c, ctx.workspace_id, 'build', build_id, 'build.failed', {'code': code})
            return dict(row(c, m.jobs, id=job['id']))

    def register_artifact(self, ctx, build_id, execution_id, epoch, *, content, artifact_type, content_type,
                          schema_version=None, access_class='private', attempt_id=None):
        allowed_page_types = {'page_html': {'text/html'}, 'page_css': {'text/css'},
            'page_js': {'text/javascript', 'application/javascript'}, 'page_svg': {'image/svg+xml'},
            'page_image': {'image/png', 'image/jpeg', 'image/webp'}, 'page_font': {'font/woff', 'font/woff2'}}
        if access_class == 'page' and content_type not in allowed_page_types.get(artifact_type, set()):
            raise Forbidden('artifact.private_type_in_page')
        artifact_id = uuid4()
        # Authorize before writing, and fence again before committing the reference.
        with transaction(self.db) as c:
            self._guard(c, ctx, build_id, execution_id, epoch)
            self._running_attempt(c, ctx, build_id, execution_id, attempt_id)
        key = f'workspaces/{ctx.workspace_id}/builds/{build_id}/{artifact_id}'
        stored = self.storage.put_immutable(key, BytesIO(content))
        with transaction(self.db) as c:
            self._guard(c, ctx, build_id, execution_id, epoch)
            self._running_attempt(c, ctx, build_id, execution_id, attempt_id)
            return dict(self.artifacts.register(dict(id=artifact_id, workspace_id=ctx.workspace_id, owner_user_id=ctx.user_id,
                producer_build_id=build_id, producer_attempt_id=attempt_id, artifact_type=artifact_type, storage_key=key, sha256=stored.sha256,
                size_bytes=stored.size_bytes, content_type=content_type, schema_version=schema_version, access_class=access_class), c))

    def _running_attempt(self, c, ctx, build_id, execution_id, attempt_id):
        if attempt_id is None:
            raise Conflict('stage.attempt_required')
        attempt = scoped(c, m.stage_attempts, ctx, attempt_id)
        stage = scoped(c, m.build_stages, ctx, attempt['build_stage_id'])
        if stage['build_id'] != build_id or attempt['execution_id'] != execution_id or attempt['kind'] != 'executed' or attempt['status'] != 'running':
            raise Conflict('stage.attempt_not_running')
        return attempt

    def _produced_artifact(self, c, ctx, artifact_id, build_id, attempt_id):
        artifact = self.artifacts.verified(c, ctx, artifact_id)
        if artifact['producer_build_id'] != build_id or artifact['producer_attempt_id'] != attempt_id:
            raise Conflict('artifact.producer_mismatch')
        return artifact

    @staticmethod
    def _output_signature(outputs):
        return [(str(o['artifact_id']), o.get('role', 'output'), o['name']) for o in outputs]

    def _attempt_outputs(self, c, attempt_id):
        return list(c.execute(select(m.stage_artifacts).filter_by(stage_attempt_id=attempt_id)
                             .order_by(m.stage_artifacts.c.position)).mappings())

    def _verify_accepted_provenance(self, c, ctx, attempt, problem_id):
        """Check the full reuse lineage, including records written before this guard."""
        seen = set()
        while True:
            if attempt['id'] in seen:
                raise IntegrityFailure('stage.reuse_cycle')
            seen.add(attempt['id'])
            stage = scoped(c, m.build_stages, ctx, attempt['build_stage_id'])
            build = scoped(c, m.builds, ctx, stage['build_id'])
            if build['problem_id'] != problem_id or stage['accepted_attempt_id'] != attempt['id'] or stage['status'] != 'succeeded' or attempt['status'] != 'succeeded':
                raise Conflict('stage.reuse_incompatible')
            outputs = self._attempt_outputs(c, attempt['id'])
            artifact_ids = {attempt['manifest_artifact_id'], attempt['checkpoint_artifact_id'], *(o['artifact_id'] for o in outputs)}
            if attempt['kind'] == 'executed':
                for aid in artifact_ids:
                    self._produced_artifact(c, ctx, aid, build['id'], attempt['id'])
                if any(o['reused_from_artifact_id'] is not None for o in outputs):
                    raise IntegrityFailure('stage.executed_reuse_reference')
                return
            old = scoped(c, m.stage_attempts, ctx, attempt['reused_from_attempt_id'])
            if any(attempt[k] != old[k] for k in ('manifest_artifact_id', 'checkpoint_artifact_id')) or self._output_signature(outputs) != self._output_signature(self._attempt_outputs(c, old['id'])) or any(o['reused_from_artifact_id'] != o['artifact_id'] for o in outputs):
                raise IntegrityFailure('stage.reuse_evidence_mismatch')
            attempt = old

    def begin_stage(self, ctx, build_id, execution_id, epoch, stage_key):
        with transaction(self.db) as c:
            build, _ = self._guard(c, ctx, build_id, execution_id, epoch)
            stage = c.execute(select(m.build_stages).filter_by(build_id=build_id, stage_key=stage_key).with_for_update()).mappings().one()
            if stage['status'] == 'succeeded':
                raise Conflict('stage.already_completed')
            current = c.execute(select(m.stage_attempts).filter_by(build_stage_id=stage['id'], execution_id=execution_id, status='running')).mappings().first()
            if current:
                return dict(current)
            definition = next(s for s in build['pipeline_snapshot']['stages'] if s['stage_key'] == stage_key)
            if any(row(c, m.build_stages, build_id=build_id, stage_key=k)['status'] != 'succeeded' for k in definition['depends_on']):
                raise Conflict('stage.upstream_incomplete')
            number = c.scalar(select(func.coalesce(func.max(m.stage_attempts.c.attempt_no), 0)).where(m.stage_attempts.c.build_stage_id == stage['id'])) + 1
            attempt = insert(c, m.stage_attempts, workspace_id=ctx.workspace_id, build_stage_id=stage['id'], execution_id=execution_id,
                attempt_no=number, kind='executed', status='running', started_at=now(c))
            update(c, m.build_stages, stage['id'], status='running')
            append_event(c, ctx.workspace_id, 'build', build_id, 'stage.running', {'stage_key': stage_key, 'attempt_id': str(attempt['id'])})
            return dict(attempt)

    def fail_stage(self, ctx, build_id, execution_id, epoch, attempt_id, code):
        with transaction(self.db) as c:
            self._guard(c, ctx, build_id, execution_id, epoch)
            attempt = scoped(c, m.stage_attempts, ctx, attempt_id)
            stage = scoped(c, m.build_stages, ctx, attempt['build_stage_id'])
            if stage['build_id'] != build_id or attempt['execution_id'] != execution_id or attempt['status'] != 'running':
                raise Conflict('stage.attempt_not_running')
            update(c, m.stage_attempts, attempt_id, status='failed', finished_at=now(c))
            update(c, m.build_stages, stage['id'], status='failed')
            append_event(c, ctx.workspace_id, 'build', build_id, 'stage.failed', {'stage_key': stage['stage_key'], 'code': code})

    def commit_stage(self, ctx, build_id, execution_id, epoch, stage_key, *, manifest_artifact_id,
                     checkpoint_artifact_id, outputs, reused_from_attempt_id=None, attempt_id=None):
        with transaction(self.db) as c:
            build, _ = self._guard(c, ctx, build_id, execution_id, epoch)
            stage = c.execute(select(m.build_stages).filter_by(build_id=build_id, stage_key=stage_key).with_for_update()).mappings().one()
            if stage['status'] == 'succeeded':
                accepted = row(c, m.stage_attempts, id=stage['accepted_attempt_id'])
                if (accepted['manifest_artifact_id'] == manifest_artifact_id and accepted['checkpoint_artifact_id'] == checkpoint_artifact_id
                    and accepted['reused_from_attempt_id'] == reused_from_attempt_id
                    and (attempt_id is None or accepted['id'] == attempt_id)
                    and self._output_signature(outputs) == self._output_signature(self._attempt_outputs(c, accepted['id']))):
                    self._verify_accepted_provenance(c, ctx, accepted, build['problem_id'])
                    return dict(accepted)
                raise Conflict('stage.already_completed')
            running = c.execute(select(m.stage_attempts).filter_by(build_stage_id=stage['id'], status='running')).mappings().all()
            if reused_from_attempt_id:
                if attempt_id is not None or running:
                    raise Conflict('stage.reuse_while_running')
            else:
                # Omitting the ID may complete an existing attempt, never create a second one.
                if attempt_id is None and len(running) == 1:
                    attempt_id = running[0]['id']
                attempt = self._running_attempt(c, ctx, build_id, execution_id, attempt_id)
                if attempt['build_stage_id'] != stage['id'] or len(running) != 1:
                    raise Conflict('stage.attempt_not_running')
                for aid in {manifest_artifact_id, checkpoint_artifact_id, *(o['artifact_id'] for o in outputs)}:
                    self._produced_artifact(c, ctx, aid, build_id, attempt_id)
            definition = next(s for s in build['pipeline_snapshot']['stages'] if s['stage_key'] == stage_key)
            for key in definition['depends_on']:
                if row(c, m.build_stages, build_id=build_id, stage_key=key)['status'] != 'succeeded':
                    raise Conflict('stage.upstream_incomplete')
            artifact = self.artifacts.verified(c, ctx, manifest_artifact_id)
            self.artifacts.verified(c, ctx, checkpoint_artifact_id)
            with self.storage.open(artifact['storage_key']) as stream:
                manifest = json.load(stream)
            if manifest.get('stage_key') != stage_key or manifest.get('contract_version') != definition['contract_version']:
                raise IntegrityFailure('stage.manifest_contract')
            expected = build['target_dependencies'].get(stage_key)
            if not isinstance(expected, dict) or any(k not in expected or manifest.get(k) != expected[k] for k in ('inputs', 'resources', 'config', 'upstream')):
                raise IntegrityFailure('stage.dependencies_mismatch')
            if reused_from_attempt_id:
                old = scoped(c, m.stage_attempts, ctx, reused_from_attempt_id)
                old_stage = scoped(c, m.build_stages, ctx, old['build_stage_id'])
                old_build = scoped(c, m.builds, ctx, old_stage['build_id'])
                problem(c, ctx, old_build['problem_id'], write=True)
                if old_build['id'] == build_id or old['status'] != 'succeeded' or old_stage['stage_key'] != stage_key or old_build['problem_id'] != build['problem_id'] or not reusable(
                    old_build['pipeline_snapshot'], build['pipeline_snapshot'], stage_key, old['manifest_json'], manifest):
                    raise Conflict('stage.reuse_incompatible')
                self._verify_accepted_provenance(c, ctx, old, build['problem_id'])
                if old['checkpoint_artifact_id'] != checkpoint_artifact_id or old['manifest_artifact_id'] != manifest_artifact_id:
                    raise IntegrityFailure('stage.reuse_evidence_mismatch')
                if self._output_signature(outputs) != self._output_signature(self._attempt_outputs(c, old['id'])):
                    raise IntegrityFailure('stage.reuse_outputs_mismatch')
            attempt_no = c.scalar(select(func.coalesce(func.max(m.stage_attempts.c.attempt_no), 0)).where(m.stage_attempts.c.build_stage_id == stage['id'])) + 1
            completion = dict(status='succeeded', finished_at=now(c), manifest_json=manifest,
                manifest_artifact_id=manifest_artifact_id, manifest_sha256=artifact['sha256'],
                checkpoint_artifact_id=checkpoint_artifact_id)
            if attempt_id:
                update(c, m.stage_attempts, attempt_id, **completion)
                attempt = row(c, m.stage_attempts, id=attempt_id)
            else:
                attempt = insert(c, m.stage_attempts, workspace_id=ctx.workspace_id, build_stage_id=stage['id'],
                    execution_id=execution_id, attempt_no=attempt_no, kind='reused' if reused_from_attempt_id else 'executed',
                    started_at=now(c), reused_from_attempt_id=reused_from_attempt_id, **completion)
            for position, output in enumerate(outputs, 1):
                self.artifacts.verified(c, ctx, output['artifact_id'])
                insert(c, m.stage_artifacts, workspace_id=ctx.workspace_id, stage_attempt_id=attempt['id'],
                    artifact_id=output['artifact_id'], role=output.get('role', 'output'), name=output['name'], position=position,
                    reused_from_artifact_id=output['artifact_id'] if reused_from_attempt_id else None)
            if reused_from_attempt_id:
                for ref in c.execute(select(m.stage_call_refs).filter_by(stage_attempt_id=reused_from_attempt_id)).mappings():
                    insert(c, m.stage_call_refs, workspace_id=ctx.workspace_id, stage_attempt_id=attempt['id'], model_call_id=ref['model_call_id'], relation='reused')
            update(c, m.build_stages, stage['id'], status='succeeded', accepted_attempt_id=attempt['id'])
            append_event(c, ctx.workspace_id, 'build', build_id, 'stage.succeeded', {'stage_key': stage_key, 'attempt_id': str(attempt['id'])})
            return dict(attempt)

    def link_artifacts(self, ctx, build_id, execution_id, epoch, artifact_id, depends_on_artifact_id, kind):
        with transaction(self.db) as c:
            self._guard(c, ctx, build_id, execution_id, epoch)
            for aid in (artifact_id, depends_on_artifact_id):
                self.artifacts.verified(c, ctx, aid)
            c.execute(pg_insert(m.artifact_dependencies).values(workspace_id=ctx.workspace_id, artifact_id=artifact_id,
                depends_on_artifact_id=depends_on_artifact_id, kind=kind).on_conflict_do_nothing(index_elements=['artifact_id', 'depends_on_artifact_id', 'kind']))

    def finish_page(self, ctx, build_id, execution_id, epoch, *, entry_artifact_id, package_manifest_artifact_id, assets):
        with transaction(self.db) as c:
            # Consistent lock order with revision save: problem before execution/job.
            build = scoped(c, m.builds, ctx, build_id)
            p = problem(c, ctx, build['problem_id'], write=True, lock=True)
            build, job = self._guard(c, ctx, build_id, execution_id, epoch)
            snapshot = validate(build['pipeline_snapshot'])
            stages = c.execute(select(m.build_stages).filter_by(build_id=build_id)).mappings().all()
            if {(s['stage_key'], s['ordinal']) for s in stages} != {(s['stage_key'], s['ordinal']) for s in snapshot['stages']}:
                raise IntegrityFailure('pipeline.stage_rows_drift')
            by_key = {s['stage_key']: s for s in stages}
            for key in snapshot['completion']['required_stages']:
                s = by_key[key]
                if s['status'] != 'succeeded' or not s['accepted_attempt_id']:
                    raise IntegrityFailure('page.incomplete_stage')
                attempt = row(c, m.stage_attempts, id=s['accepted_attempt_id'])
                self._verify_accepted_provenance(c, ctx, attempt, build['problem_id'])
                for field in ('manifest_artifact_id', 'checkpoint_artifact_id'):
                    self.artifacts.verified(c, ctx, attempt[field])
            for required in snapshot['completion']['required_artifacts']:
                attempt_id = by_key[required['stage_key']]['accepted_attempt_id']
                refs = c.execute(select(m.stage_artifacts).filter_by(stage_attempt_id=attempt_id, role='output', name=required['name'])).mappings().all()
                if not refs or not any(self.artifacts.verified(c, ctx, r['artifact_id'])['schema_version'] == required['schema_version'] for r in refs):
                    raise IntegrityFailure('page.required_artifact')
            if build['resolved_revision_id'] is None:
                raise IntegrityFailure('page.revision_missing')
            entry = self.artifacts.verified(c, ctx, entry_artifact_id, page=True)
            package = self.artifacts.verified(c, ctx, package_manifest_artifact_id)
            if entry['content_type'] != 'text/html' or package['schema_version'] != 'product-page/v1':
                raise IntegrityFailure('page.package_contract')
            with self.storage.open(package['storage_key']) as stream:
                manifest = json.load(stream)
            expected_assets = {path: str(artifact_id) for path, artifact_id in assets.items()}
            if manifest.get('schema_version') != 'product-page/v1' or manifest.get('assets') != expected_assets or manifest.get('entry_artifact_id') != str(entry_artifact_id):
                raise IntegrityFailure('page.manifest_mismatch')
            if assets.get('index.html') != entry_artifact_id:
                raise IntegrityFailure('page.entry_missing')
            accepted_ids = {s['accepted_attempt_id'] for s in stages if s['accepted_attempt_id']}
            for artifact_id in {entry_artifact_id, package_manifest_artifact_id, *assets.values()}:
                if not c.execute(select(m.stage_artifacts.c.id).where(m.stage_artifacts.c.stage_attempt_id.in_(accepted_ids),
                    m.stage_artifacts.c.artifact_id == artifact_id, m.stage_artifacts.c.role == 'output')).first():
                    raise IntegrityFailure('page.unaccepted_resource')
            page = insert(c, m.page_builds, workspace_id=ctx.workspace_id, build_id=build_id, revision_id=build['resolved_revision_id'],
                entry_artifact_id=entry_artifact_id, package_manifest_artifact_id=package_manifest_artifact_id, package_sha256=package['sha256'])
            for path, artifact_id in assets.items():
                parts(path)
                self.artifacts.verified(c, ctx, artifact_id, page=True)
                insert(c, m.page_assets, workspace_id=ctx.workspace_id, page_build_id=page['id'], relative_path=path, artifact_id=artifact_id)
            update(c, m.builds, build_id, status='succeeded', finished_at=now(c))
            update(c, m.jobs, job['id'], status='succeeded', lease_expires_at=None)
            update(c, m.job_executions, execution_id, status='succeeded', finished_at=now(c))
            if p['latest_build_id'] == build_id and p['current_revision_id'] == build['resolved_revision_id']:
                update(c, m.problems, p['id'], current_page_build_id=page['id'], lock_version=p['lock_version'] + 1, updated_at=now(c))
            append_event(c, ctx.workspace_id, 'build', build_id, 'build.succeeded', {'page_build_id': str(page['id'])})
            return dict(page)

    def page_resource(self, ctx, page_id, relative_path='index.html'):
        parts(relative_path)
        with transaction(self.db) as c:
            page = scoped(c, m.page_builds, ctx, page_id)
            build = scoped(c, m.builds, ctx, page['build_id'])
            problem(c, ctx, build['problem_id'])
            asset = row(c, m.page_assets, page_build_id=page_id, relative_path=relative_path)
            if asset is None:
                raise Forbidden('page.resource_not_registered')
            return dict(self.artifacts.verified(c, ctx, asset['artifact_id'], page=True))

    def review(self, ctx, page_id, decision, comment=None, supersedes_id=None):
        with transaction(self.db) as c:
            page = scoped(c, m.page_builds, ctx, page_id)
            build = scoped(c, m.builds, ctx, page['build_id'])
            problem(c, ctx, build['problem_id'], write=True)
            review = dict(insert(c, m.review_decisions, workspace_id=ctx.workspace_id, page_build_id=page_id,
                revision_id=page['revision_id'], reviewer_user_id=ctx.user_id, decision=decision, comment=comment, supersedes_id=supersedes_id))
            append_event(c, ctx.workspace_id, 'build', build['id'], 'page.reviewed',
                         {'page_id': str(page_id), 'review_id': str(review['id']), 'decision': decision})
            return review

    def record_call(self, ctx, build_id, execution_id, epoch, attempt_id, audit_artifact_id, **fields):
        allowed = {'provider', 'request_model', 'response_model', 'provider_version', 'provider_request_id',
                   'call_kind', 'started_at', 'duration_ms', 'status', 'usage_json', 'input_tokens', 'output_tokens',
                   'request_artifact_id', 'response_artifact_id'}
        if set(fields) - allowed:
            raise ProductError('call.unknown_fields')
        with transaction(self.db) as c:
            self._guard(c, ctx, build_id, execution_id, epoch)
            attempt = scoped(c, m.stage_attempts, ctx, attempt_id)
            stage = scoped(c, m.build_stages, ctx, attempt['build_stage_id'])
            if attempt['execution_id'] != execution_id or attempt['kind'] != 'executed' or attempt['status'] != 'running' or stage['build_id'] != build_id:
                raise Conflict('call.origin_mismatch')
            for aid in [audit_artifact_id, fields.get('request_artifact_id'), fields.get('response_artifact_id')]:
                if aid:
                    self._produced_artifact(c, ctx, aid, build_id, attempt_id)
            # Stable audit identity prevents a retried recorder from double-counting usage.
            lock(c, 'call.audit', str(audit_artifact_id))
            existing = row(c, m.model_calls, audit_artifact_id=audit_artifact_id)
            if existing:
                if existing['origin_attempt_id'] != attempt_id or any(existing[k] != v for k, v in fields.items()):
                    raise Conflict('call.audit_conflict')
                return dict(existing)
            call = insert(c, m.model_calls, workspace_id=ctx.workspace_id, origin_attempt_id=attempt_id,
                          audit_artifact_id=audit_artifact_id, **fields)
            insert(c, m.stage_call_refs, workspace_id=ctx.workspace_id, stage_attempt_id=attempt_id, model_call_id=call['id'], relation='executed')
            return dict(call)

    def record_diagnostic(self, ctx, build_id, execution_id, epoch, *, code, message, severity='error', stage_attempt_id=None, evidence_artifact_id=None, details=None):
        with transaction(self.db) as c:
            self._guard(c, ctx, build_id, execution_id, epoch)
            if stage_attempt_id:
                attempt = scoped(c, m.stage_attempts, ctx, stage_attempt_id)
                stage = scoped(c, m.build_stages, ctx, attempt['build_stage_id'])
                if stage['build_id'] != build_id:
                    raise Conflict('diagnostic.attempt_mismatch')
            if evidence_artifact_id:
                self.artifacts.verified(c, ctx, evidence_artifact_id)
            return dict(insert(c, m.diagnostics, workspace_id=ctx.workspace_id, build_id=build_id,
                stage_attempt_id=stage_attempt_id, code=code, message=message, severity=severity,
                evidence_artifact_id=evidence_artifact_id, details=clean_config(details)))

    def build_snapshot(self, ctx, build_id):
        with transaction(self.db) as c:
            build = scoped(c, m.builds, ctx, build_id)
            problem(c, ctx, build['problem_id'])
            # Stream lock synchronizes snapshot with commits appending events.
            stream = c.execute(select(m.event_streams).filter_by(workspace_id=ctx.workspace_id,
                stream_kind='build', aggregate_id=build_id).with_for_update()).mappings().first()
            build = scoped(c, m.builds, ctx, build_id)
            stages = c.execute(select(m.build_stages).filter_by(build_id=build_id).order_by(m.build_stages.c.ordinal)).mappings().all()
            titles = {s['stage_key']: s['title'] for s in validate(build['pipeline_snapshot'])['stages']}
            return {'build': dict(build), 'stages': [{**s, 'title': titles[s['stage_key']]} for s in stages],
                    'last_seq': stream['last_seq'] if stream else 0}

    def read_events(self, ctx, kind, aggregate_id, after=0, limit=100):
        if after < 0 or not 1 <= limit <= 1000:
            raise ProductError('events.range')
        with transaction(self.db) as c:
            if kind == 'build':
                b = scoped(c, m.builds, ctx, aggregate_id)
                problem(c, ctx, b['problem_id'])
            elif kind == 'problem':
                problem(c, ctx, aggregate_id)
            elif kind == 'batch':
                b = scoped(c, m.batches, ctx, aggregate_id)
                if b['owner_user_id'] != ctx.user_id:
                    raise Forbidden('batch.private')
            else:
                raise ProductError('events.unknown_stream')
            stream = row(c, m.event_streams, workspace_id=ctx.workspace_id, stream_kind=kind, aggregate_id=aggregate_id)
            if not stream:
                return []
            return [dict(x) for x in c.execute(select(m.events).where(m.events.c.stream_id == stream['id'],
                m.events.c.seq > after).order_by(m.events.c.seq).limit(limit)).mappings()]
