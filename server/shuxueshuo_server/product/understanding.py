"""Versioned mathematical candidates; independent of verified Solver revisions."""
import json
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi.encoders import jsonable_encoder
from jsonschema import Draft202012Validator
from PIL import Image
from sqlalchemy import and_, or_, select

from shuxueshuo_server.problem_understanding.notation_contract import CONTRACT, schema
from shuxueshuo_server.problem_understanding.notation_service import parse_candidate
from shuxueshuo_server.problem_understanding.workflow_diagnostics import diagnose
from shuxueshuo_server.solver.extraction.multimodal_provider import (
    problem_domain_family_catalog,
)

from . import models as m
from .db import digest, transaction
from .errors import Conflict, Forbidden, ProductError
from .repositories import insert, problem, row, scoped
from .services import append_event, now, update


def public(value):
    """Do not expose artifact storage locators or provider secrets in summaries."""
    if isinstance(value, dict):
        return {k: public(v) for k, v in value.items() if k not in ('locator', 'storage_key', 'receipt_key')}
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    return jsonable_encoder(value)


def registry():
    return jsonable_encoder(problem_domain_family_catalog())


def parse(candidate, problem_id, source_hash, families=None, store=None):
    families = registry() if families is None else families
    return parse_candidate(json.dumps(candidate, ensure_ascii=False), problem_id=str(problem_id),
        source_sha256=source_hash, registry_snapshot=digest(families),
        registered_families=[f['family_id'] for f in families], store=store)


def check_shape(candidate):
    errors = sorted(Draft202012Validator(schema()).iter_errors(candidate), key=lambda e: str(e.path))
    if errors:
        error = ProductError('candidate.schema_invalid')
        error.details = [{'path': '/' + '/'.join(str(x).replace('~', '~0').replace('/', '~1') for x in e.path),
                          'message': e.message} for e in errors[:30]]
        raise error


def candidate_state(p, candidate, run, config, *, local=False):
    """Shared current-version status for the detail page and workspace list."""
    result = run['result_json'] if run and run['result_json'] else {}
    bound = bool(run and candidate and run['candidate_id'] == candidate['id'] and
        candidate['source_version_id'] == p['current_source_version_id'] and
        run['source_version_id'] == p['current_source_version_id'] and
        run['generation'] == p['understanding_generation'])
    valid_review = bool(bound and run['status'] == 'completed' and result.get('source_reviewed') and
        (local or run['frozen'] == config))
    stale_reason = None
    if result.get('source_reviewed') and not valid_review:
        if not bound:
            stale_reason = 'candidate_or_source_changed'
        elif run['status'] != 'completed':
            stale_reason = 'run_not_completed'
        else:
            stale_reason = 'configuration_changed'
    validation = candidate['validation_json'] if candidate else {}
    current_result = result if bound else {}
    return {
        'parse_status': current_result.get('parse_status', 'valid' if validation.get('contract_valid') else 'invalid' if candidate else 'unavailable'),
        'source_reviewed': valid_review,
        'review_stale_reason': stale_reason,
        'source_status': result.get('source_status', 'not_reviewed') if valid_review or not result.get('source_reviewed') else 'stale',
        'match_status': candidate['candidate_json'].get('match_status') if candidate else None,
        'diagnostics': result.get('diagnostics', []) if run else diagnose(validation, candidate['candidate_json']) if candidate else [],
    }


class Understanding:
    def __init__(self, application):
        self.app, self.service, self.ctx = application, application.service, application.ctx
        self.db = self.service.db

    def owned(self, c, table, identity, problem_id):
        value = scoped(c, table, self.ctx, identity)
        if value['problem_id'] != problem_id:
            raise Forbidden('understanding.wrong_problem')
        return value

    def supersede(self, c, p):
        active = c.execute(select(m.extraction_runs).where(m.extraction_runs.c.problem_id == p['id'],
            m.extraction_runs.c.status.in_(['queued', 'running']))).mappings().all()
        for run in active:
            update(c, m.extraction_runs, run['id'], status='superseded', finished_at=now(c))
            self.service.cancel(self.ctx, run['build_id'])
            append_event(c, self.ctx.workspace_id, 'build', run['build_id'], 'understanding.superseded', {})
        return p['understanding_generation'] + 1

    def upload(self, problem_id, content, filename, media_type, key):
        if not content or len(content) > 20 * 1024**2:
            raise ProductError('upload.size')
        with Image.open(BytesIO(content)) as image:
            if Image.MIME.get(image.format) != media_type or media_type not in ('image/png', 'image/jpeg', 'image/webp'):
                raise ProductError('upload.media_type')
            if image.width * image.height > 25_000_000 or getattr(image, 'n_frames', 1) != 1:
                raise ProductError('upload.image')
            metadata = {'width': image.width, 'height': image.height}
            image.verify()
        hashed = sha256(content).hexdigest()
        def perform():
            with transaction(self.db) as c:
                problem(c, self.ctx, problem_id, write=True, lock=True)
                prior = c.execute(select(m.sources).join(m.problem_sources, m.problem_sources.c.source_id == m.sources.c.id)
                    .join(m.artifacts, m.artifacts.c.id == m.sources.c.original_artifact_id)
                    .where(m.problem_sources.c.problem_id == problem_id, m.artifacts.c.sha256 == hashed)).mappings().first()
                if prior:
                    return {'source_id': str(prior['id'])}
                sid, aid = uuid4(), uuid4()
                storage_key = f'workspaces/{self.ctx.workspace_id}/sources/{sid}/{aid}'
                saved = self.service.storage.put_immutable(storage_key, BytesIO(content), hashed)
                self.service.artifacts.register({'id': aid, 'workspace_id': self.ctx.workspace_id, 'owner_user_id': self.ctx.user_id,
                    'artifact_type': 'source_original', 'storage_key': storage_key, 'sha256': hashed, 'size_bytes': saved.size_bytes,
                    'content_type': media_type, 'access_class': 'private'}, c)
                insert(c, m.sources, id=sid, workspace_id=self.ctx.workspace_id, owner_user_id=self.ctx.user_id,
                    original_artifact_id=aid, filename=PurePosixPath(filename.replace('\\', '/')).name,
                    media_type=media_type, metadata=metadata)
                insert(c, m.problem_sources, workspace_id=self.ctx.workspace_id, problem_id=problem_id,
                    source_id=sid, match_method='manual')
                return {'source_id': str(sid)}
        return self.app.request('understanding.upload', key, {'problem_id': str(problem_id), 'sha256': hashed,
            'filename': filename, 'media_type': media_type}, perform)

    def source_version(self, problem_id, base_id, source_ids, key):
        if not source_ids or len(source_ids) > 600 or len(set(source_ids)) != len(source_ids):
            raise ProductError('source.invalid_image_list')
        def perform():
            with transaction(self.db) as c:
                p = problem(c, self.ctx, problem_id, write=True, lock=True)
                if p['current_source_version_id'] != base_id:
                    raise Conflict('source.base_changed')
                images = []
                for sid in source_ids:
                    if not row(c, m.problem_sources, problem_id=problem_id, source_id=sid):
                        raise Forbidden('source.not_linked')
                    source = scoped(c, m.sources, self.ctx, sid)
                    art = self.service.artifacts.verified(c, self.ctx, source['original_artifact_id'])
                    images.append({'source_id': str(sid), 'artifact_id': str(art['id']), 'sha256': art['sha256'],
                        'filename': source['filename'], 'media_type': art['content_type'], **source['metadata']})
                source_hash = digest([{'source_id': i['source_id'], 'sha256': i['sha256']} for i in images])
                if base_id:
                    prior = self.owned(c, m.problem_source_versions, base_id, problem_id)
                    if prior['source_hash'] == source_hash:
                        return public(dict(prior))
                generation = self.supersede(c, p)
                version = insert(c, m.problem_source_versions, workspace_id=self.ctx.workspace_id, problem_id=problem_id,
                    parent_version_id=base_id, images=images, source_hash=source_hash, created_by_user_id=self.ctx.user_id)
                update(c, m.problems, problem_id, current_source_version_id=version['id'], current_candidate_id=None,
                    latest_extraction_run_id=None, understanding_generation=generation, updated_at=now(c))
                append_event(c, self.ctx.workspace_id, 'problem', problem_id, 'understanding.source_saved', {'source_version_id': str(version['id'])})
                return public(dict(version))
        return self.app.request('understanding.source_version', key, jsonable_encoder(
            {'problem_id': problem_id, 'base': base_id, 'sources': source_ids}), perform)

    def save_candidate(self, problem_id, base_id, source_id, candidate, key):
        from .understanding_storage import CandidateArtifacts
        check_shape(candidate)
        with transaction(self.db) as c:
            problem(c, self.ctx, problem_id, write=True)
            source = self.owned(c, m.problem_source_versions, source_id, problem_id)
        # Business rows and the idempotency receipt commit in one app.request transaction.
        # Stable identities also reuse immutable files if that transaction rolls back.
        candidate_id = uuid5(NAMESPACE_URL, 'understanding.candidate:' + digest(jsonable_encoder(
            [self.ctx.workspace_id, self.ctx.user_id, problem_id, key])))
        artifacts = CandidateArtifacts(candidate_id)
        validation = parse(candidate, problem_id, source['source_hash'], store=artifacts)
        def perform():
            with transaction(self.db) as c:
                p = problem(c, self.ctx, problem_id, write=True, lock=True)
                if p['current_candidate_id'] != base_id or p['current_source_version_id'] != source_id:
                    raise Conflict('candidate.base_changed')
                generation = self.supersede(c, p)
                value = insert(c, m.problem_candidates, id=candidate_id, workspace_id=self.ctx.workspace_id, problem_id=problem_id,
                    source_version_id=source_id, parent_candidate_id=base_id, kind='manual', candidate_json=candidate,
                    candidate_hash=digest(candidate), contract_version=CONTRACT, validation_json=validation, created_by_user_id=self.ctx.user_id)
                artifacts.persist(self.service, self.ctx, c)
                update(c, m.problems, problem_id, current_candidate_id=value['id'], latest_extraction_run_id=None,
                    understanding_generation=generation, updated_at=now(c))
                append_event(c, self.ctx.workspace_id, 'problem', problem_id, 'understanding.candidate_saved', {'candidate_id': str(value['id'])})
                return public(dict(value))
        return self.app.request('understanding.candidate', key, jsonable_encoder(
            {'problem_id': problem_id, 'base': base_id, 'source': source_id, 'candidate': candidate}), perform)

    def start(self, problem_id, source_id, base_id, mode, key):
        if mode not in ('extract', 'review', 'validate') or (mode != 'extract' and base_id is None):
            raise ProductError('understanding.invalid_mode')
        from .understanding_runtime import configuration, target_dependencies
        config = configuration()
        def perform():
            with transaction(self.db) as c:
                p = problem(c, self.ctx, problem_id, write=True, lock=True)
                if p['current_candidate_id'] != base_id or p['current_source_version_id'] != source_id:
                    raise Conflict('candidate.base_changed')
                source = self.owned(c, m.problem_source_versions, source_id, problem_id)
                if base_id:
                    candidate = self.owned(c, m.problem_candidates, base_id, problem_id)
                    if candidate['source_version_id'] != source_id:
                        raise Conflict('candidate.source_changed')
                generation = self.supersede(c, p)
                target = target_dependencies(source, base_id, config)
                submitted = self.service.submit_build(self.ctx, problem_id, request_id='understanding:' + key,
                    source_id=UUID(source['images'][0]['source_id']), base_revision_id=p['current_revision_id'],
                    pipeline_key='problem_understanding', pipeline_version='v1', **target)
                run = insert(c, m.extraction_runs, workspace_id=self.ctx.workspace_id, problem_id=problem_id,
                    source_version_id=source_id, base_candidate_id=base_id, candidate_id=base_id if mode != 'extract' else None,
                    generation=generation, mode=mode, status='queued', frozen=config, build_id=UUID(submitted['build_id']))
                update(c, m.problems, problem_id, latest_extraction_run_id=run['id'], understanding_generation=generation,
                    updated_at=now(c))
                return {'run_id': str(run['id']), **submitted}
        return self.app.request('understanding.run', key, jsonable_encoder(
            {'problem_id': problem_id, 'source': source_id, 'base': base_id, 'mode': mode}), perform)

    def candidates(self, problem_id, limit=20, before=None):
        if not 1 <= limit <= 100:
            raise ProductError('query.limit')
        with transaction(self.db) as c:
            problem(c, self.ctx, problem_id)
            query = select(m.problem_candidates).where(m.problem_candidates.c.problem_id == problem_id)
            if before:
                cursor = self.owned(c, m.problem_candidates, before, problem_id)
                query = query.where(or_(m.problem_candidates.c.created_at < cursor['created_at'], and_(
                    m.problem_candidates.c.created_at == cursor['created_at'], m.problem_candidates.c.id < before)))
            values = [public(dict(v)) for v in c.execute(query.order_by(
                m.problem_candidates.c.created_at.desc(), m.problem_candidates.c.id.desc()).limit(limit)).mappings()]
            return {'candidates': values, 'next_cursor': values[-1]['id'] if len(values) == limit else None}

    def candidate(self, problem_id, candidate_id):
        with transaction(self.db) as c:
            problem(c, self.ctx, problem_id)
            value = dict(self.owned(c, m.problem_candidates, candidate_id, problem_id))
            parent = row(c, m.problem_candidates, id=value['parent_candidate_id']) if value['parent_candidate_id'] else None
            value['parent_candidate_json'] = parent['candidate_json'] if parent else None
            value['source_version'] = dict(self.owned(c, m.problem_source_versions, value['source_version_id'], problem_id))
            value['diagnostics'] = diagnose(value['validation_json'], value['candidate_json'])
            return public(value)

    def runs(self, problem_id, limit=20, before=None):
        with transaction(self.db) as c:
            problem(c, self.ctx, problem_id)
            query = select(m.extraction_runs).where(m.extraction_runs.c.problem_id == problem_id)
            if before:
                cursor = self.owned(c, m.extraction_runs, before, problem_id)
                query = query.where(or_(m.extraction_runs.c.created_at < cursor['created_at'], and_(
                    m.extraction_runs.c.created_at == cursor['created_at'], m.extraction_runs.c.id < before)))
            values = [public(dict(v)) for v in c.execute(query.order_by(
                m.extraction_runs.c.created_at.desc(), m.extraction_runs.c.id.desc()).limit(limit)).mappings()]
            return {'runs': values, 'next_cursor': values[-1]['id'] if len(values) == limit else None}

    def run(self, run_id):
        with transaction(self.db) as c:
            run = dict(scoped(c, m.extraction_runs, self.ctx, run_id))
            problem(c, self.ctx, run['problem_id'])
            run['calls'] = [dict(v) for v in c.execute(select(m.extraction_call_reservations)
                .where(m.extraction_call_reservations.c.run_id == run_id).order_by(m.extraction_call_reservations.c.number)).mappings()]
            build = scoped(c, m.builds, self.ctx, run['build_id'])
            run['task_status'] = build['status']
            run['task_error'] = build['error_code']
            run['deployment_version'] = build['deployment_version']
            run['artifacts'] = [dict(v) for v in c.execute(select(m.artifacts.c.id, m.artifacts.c.artifact_type,
                m.artifacts.c.sha256, m.artifacts.c.size_bytes, m.artifacts.c.content_type).where(
                    m.artifacts.c.producer_build_id == run['build_id'])).mappings()]
            run['diagnostics'] = [dict(v) for v in c.execute(select(m.diagnostics).where(m.diagnostics.c.build_id == run['build_id'])).mappings()]
            return public(run)

    def summary(self, problem_id):
        from .application import latest_notation_page_id
        from .understanding_runtime import configuration
        from .runtime_binding import binding_state
        with transaction(self.db) as c:
            p = problem(c, self.ctx, problem_id)
            source = row(c, m.problem_source_versions, id=p['current_source_version_id']) if p['current_source_version_id'] else None
            candidate = row(c, m.problem_candidates, id=p['current_candidate_id']) if p['current_candidate_id'] else None
            run = row(c, m.extraction_runs, id=p['latest_extraction_run_id']) if p['latest_extraction_run_id'] else None
            state = candidate_state(p, candidate, run, configuration(), local=self.app.settings.mode == 'local')
            page_id = p['current_page_build_id'] or latest_notation_page_id(c, problem_id)
            page = row(c, m.page_builds, id=page_id) if page_id else None
            admission = binding_state(c, p)
            return public({'problem_id': problem_id, 'candidate_only': True, **admission,
                'source_version': dict(source) if source else None, 'candidate': dict(candidate) if candidate else None,
                'latest_run': self.run(run['id']) if run else None,
                **state,
                'primary_source_id': p['primary_source_id'],
                'formal_page': {k: page[k] for k in ('id', 'build_id', 'revision_id')} if page else None,
                'current_revision_id': p['current_revision_id'],
                'current_page_build_id': page_id})
