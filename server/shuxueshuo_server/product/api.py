"""Loopback HTTP/WebSocket boundary. No model execution in an HTTP request."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import FastAPI, APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import UploadFile

from .application import Application, load_application, public
from .db import transaction
from . import models as m
from .errors import ProductError, Conflict, Forbidden, NotFound, IntegrityFailure
from .repositories import scoped, row, problem

router = APIRouter(prefix='/api/product/v1')
LOOPBACK = {'127.0.0.1', '::1', 'localhost', 'testclient', 'testserver'}
# Compose service DNS used by admin doctor / in-network probes on the server.
SERVER_INTERNAL_HOSTS = {'api'}
DEFAULT_PUBLIC_ORIGINS = 'https://studio.shuxueshuo.com'


def _public_origins():
    raw = os.environ.get('PRODUCT_PUBLIC_ORIGINS', DEFAULT_PUBLIC_ORIGINS)
    return {part.strip() for part in raw.split(',') if part.strip()}


def check_peer(connection):
    """Local: real loopback peer. Server containers: host publish is 127.0.0.1; Docker NATs the peer."""
    if not connection.client:
        raise Forbidden('access.loopback_only')
    host = connection.url.hostname
    client = connection.client.host
    server_container = (
        os.environ.get('PRODUCT_IN_CONTAINER') == '1'
        and os.environ.get('PRODUCT_MODE', 'local') == 'server'
    )
    if host in LOOPBACK:
        if client not in LOOPBACK and not server_container:
            raise Forbidden('access.loopback_only')
    elif server_container and host in SERVER_INTERNAL_HOSTS:
        pass
    else:
        raise Forbidden('access.loopback_only')
    origin = connection.headers.get('origin')
    allowed = {f'http://{name}:{port}' for name in ('localhost', '127.0.0.1') for port in
               (os.environ.get('PRODUCT_FRONTEND_PORT', '3000'), os.environ.get('PRODUCT_API_PORT', '8000'))}
    if server_container:
        allowed |= _public_origins()
    if origin and origin not in allowed:
        raise Forbidden('access.origin_rejected')


def app_for(request):
    check_peer(request)
    if not hasattr(request.app.state, 'product'): raise HTTPException(503, '产品服务尚未就绪')
    return request.app.state.product


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Batch(Input):
    name: str | None = Field(default=None, max_length=200)


class Resolve(Input):
    problem_id: UUID


class Revision(Input):
    base_revision_id: UUID
    domain: dict


class Build(Input):
    source_id: UUID
    batch_item_id: UUID | None = None


class Preview(Input):
    requested_stage: str | None = None


class Rebuild(Preview):
    fingerprint: str


class Review(Input):
    decision: Literal['approved', 'rejected', 'revoked']
    comment: str | None = Field(default=None, max_length=10000)
    supersedes_id: UUID | None = None


def error_response(exc, request):
    status = 409 if isinstance(exc, Conflict) else 403 if isinstance(exc, Forbidden) else 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, IntegrityFailure) else 422
    code = str(exc) if isinstance(exc, ProductError) else 'request.invalid'
    messages = {'request.content_changed': '同一请求标识的内容发生变化，请重新操作。',
        'build.repreview_required': '题意或运行条件已变化，请刷新重建预览。',
        'revision.base_changed': '题意已有新版本，请刷新后修改。', 'execution.fenced': '本次执行已失效。',
        'access.loopback_only': '当前服务仅允许本机访问。', 'events.resnapshot_required': '请重新加载当前状态。'}
    return JSONResponse({'error': {'code': code, 'message': messages.get(code, '操作未完成，请检查输入、权限或最新任务状态。'),
        'details': getattr(exc, 'details', None),
        'request_id': getattr(request.state, 'request_id', str(uuid4()))}}, status_code=status)


def create_app(application=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.product = application or await asyncio.to_thread(load_application)
        try: yield
        finally:
            if application is None: app.state.product.close()
    app = FastAPI(title='数学说产品服务', version='0.2.0', lifespan=lifespan)
    if application is not None: app.state.product = application
    app.include_router(router)
    @app.middleware('http')
    async def boundary(request, call_next):
        request.state.request_id = str(uuid4())
        try:
            if request.url.path.startswith('/api/product/'):
                check_peer(request)
                if request.method not in ('GET', 'HEAD', 'OPTIONS') and (app_for(request).settings.root / 'locks/services-draining').exists():
                    return JSONResponse({'error': {'code': 'service.draining', 'message': '服务正在停止接收新请求。'}}, status_code=503)
                length = request.headers.get('content-length')
                if length and (not length.isdigit()): raise ProductError('request.invalid_length')
                if length and int(length) > 21 * 1024 * 1024:
                    return JSONResponse({'error': {'code': 'upload.size', 'message': '图片须在 20 MiB 以内。'}}, status_code=413)
            return await call_next(request)
        except ProductError as exc: return error_response(exc, request)
        except (SQLAlchemyError, OSError):
            return JSONResponse({'error': {'code': 'service.unavailable', 'message': '服务暂不可用，请稍后重试。', 'request_id': request.state.request_id}}, status_code=503)
    @app.exception_handler(ProductError)
    async def product_error(request, exc): return error_response(exc, request)
    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc): return error_response(ValueError(), request)
    @app.exception_handler(ValueError)
    async def invalid_value(request, exc): return error_response(exc, request)
    return app


@router.get('/health')
def health(request: Request):
    a = app_for(request)
    with transaction(a.db) as c: c.execute(select(1))
    return {'status': 'ok', 'mode': 'product'}


@router.get('/requests/{operation}/{request_id}')
def request_status(operation: str, request_id: str, request: Request):
    a = app_for(request)
    if operation not in ('upload', 'batch.create', 'build.create', 'build.rebuild', 'revision.save', 'source.resolve', 'page.review',
                         'understanding.upload', 'understanding.source_version', 'understanding.candidate', 'understanding.run', 'runtime_binding.run'):
        raise ProductError('request.operation')
    with transaction(a.db) as c:
        record = row(c, m.idempotency_requests, workspace_id=a.ctx.workspace_id, user_id=a.ctx.user_id, operation=operation, request_id=request_id)
        return {'found': record is not None, 'response': record['response_json'] if record else None}


@router.post('/batches', status_code=201)
def create_batch(body: Batch, request: Request, idempotency_key: str = Header()):
    return app_for(request).create_batch(idempotency_key, body.name)


@router.get('/batches/{batch_id}')
def batch(batch_id: UUID, request: Request): return app_for(request).batch(batch_id)


@router.post('/batches/{batch_id}/uploads', status_code=201)
async def upload(batch_id: UUID, request: Request, idempotency_key: str = Header()):
    a = app_for(request)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 20 * 1024 * 1024 + 65536: raise HTTPException(413, '图片须在 20 MiB 以内')
    async def receive(): return {'type': 'http.request', 'body': bytes(raw), 'more_body': False}
    bounded = Request(request.scope, receive)
    async with bounded.form(max_files=1, max_fields=0) as form:
        file = form.get('image')
        if not isinstance(file, UploadFile): raise ProductError('upload.image_required')
        content = await file.read()
        return await asyncio.to_thread(a.upload, batch_id, idempotency_key, content, file.filename or 'image', file.content_type or '')


@router.post('/sources/{source_id}/resolve')
def resolve(source_id: UUID, body: Resolve, request: Request, idempotency_key: str = Header()):
    return app_for(request).resolve(source_id, body.problem_id, idempotency_key)


@router.get('/problems')
def problems(request: Request, limit: int = Query(50, ge=1, le=100), before_time: str | None = None, before_id: UUID | None = None):
    from datetime import datetime
    a = app_for(request)
    if bool(before_time) != bool(before_id): raise ProductError('query.cursor')
    before = (datetime.fromisoformat(before_time), before_id) if before_time else None
    return {'problems': a.list_problems(limit=limit, before=before)}


@router.get('/problems/{problem_id}')
def get_problem(problem_id: UUID, request: Request): return app_for(request).get_problem(problem_id)


class SourceVersionInput(Input):
    base_source_version_id: UUID | None
    source_ids: list[UUID] = Field(min_length=1, max_length=600)


class CandidateInput(Input):
    base_candidate_id: UUID | None
    source_version_id: UUID
    candidate: dict


class ExtractionRunInput(Input):
    base_candidate_id: UUID | None
    source_version_id: UUID
    mode: Literal['extract', 'review', 'validate'] = 'extract'


def understanding_for(request):
    from .understanding import Understanding
    return Understanding(app_for(request))


class RuntimeBindingRunInput(Input):
    candidate_id: UUID
    source_version_id: UUID


@router.post('/problems/{problem_id}/runtime-binding-runs', status_code=202)
def runtime_binding_start(problem_id: UUID, body: RuntimeBindingRunInput, request: Request, idempotency_key: str = Header()):
    from .runtime_binding import RuntimeBindings
    return RuntimeBindings(app_for(request)).start(problem_id, body.candidate_id, body.source_version_id, idempotency_key)


@router.get('/problems/{problem_id}/runtime-binding-runs')
def runtime_binding_runs(problem_id: UUID, request: Request, limit: int = 20, before: UUID | None = None):
    from .runtime_binding import RuntimeBindings
    return RuntimeBindings(app_for(request)).runs(problem_id, limit, before)


@router.get('/runtime-binding-runs/{run_id}')
def runtime_binding_run(run_id: UUID, request: Request):
    from .runtime_binding import RuntimeBindings
    return RuntimeBindings(app_for(request)).run(run_id)


@router.get('/problems/{problem_id}/understanding')
def understanding_summary(problem_id: UUID, request: Request):
    return understanding_for(request).summary(problem_id)


@router.post('/problems/{problem_id}/source-images', status_code=201)
async def understanding_upload(problem_id: UUID, request: Request, idempotency_key: str = Header()):
    form = await request.form()
    image = form.get('image')
    if not isinstance(image, UploadFile):
        raise ProductError('upload.missing_image')
    content = await image.read(20 * 1024**2 + 1)
    return await asyncio.to_thread(understanding_for(request).upload, problem_id, content,
                                  image.filename or 'image', image.content_type, idempotency_key)


@router.get('/problems/{problem_id}/source-images/{source_id}')
def understanding_image(problem_id: UUID, source_id: UUID, request: Request):
    a = app_for(request)
    with transaction(a.db) as c:
        problem(c, a.ctx, problem_id)
        if not row(c, m.problem_sources, problem_id=problem_id, source_id=source_id):
            raise Forbidden('source.not_linked')
        source = scoped(c, m.sources, a.ctx, source_id)
        artifact = a.service.artifacts.verified(c, a.ctx, source['original_artifact_id'])
    with a.service.storage.open(artifact['storage_key']) as stream:
        content = stream.read()
    return Response(content, media_type=artifact['content_type'], headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/problems/{problem_id}/source-versions', status_code=201)
def understanding_source(problem_id: UUID, body: SourceVersionInput, request: Request, idempotency_key: str = Header()):
    return understanding_for(request).source_version(problem_id, body.base_source_version_id, body.source_ids, idempotency_key)


@router.get('/problems/{problem_id}/candidates')
def understanding_candidates(problem_id: UUID, request: Request, limit: int = 20, before: UUID | None = None):
    return understanding_for(request).candidates(problem_id, limit, before)


@router.get('/problems/{problem_id}/candidates/{candidate_id}')
def understanding_candidate(problem_id: UUID, candidate_id: UUID, request: Request):
    return understanding_for(request).candidate(problem_id, candidate_id)


@router.get('/problems/{problem_id}/candidates/{candidate_id}/artifacts/{artifact_id}')
def understanding_candidate_artifact(problem_id: UUID, candidate_id: UUID, artifact_id: UUID, request: Request):
    a = app_for(request)
    candidate = understanding_for(request).candidate(problem_id, candidate_id)
    allowed = {v['artifact_id'] for v in candidate['validation_json'].get('artifacts', {}).values()}
    if str(artifact_id) not in allowed:
        raise Forbidden('artifact.not_in_candidate')
    with transaction(a.db) as c:
        artifact = a.service.artifacts.verified(c, a.ctx, artifact_id)
    with a.service.storage.open(artifact['storage_key']) as stream:
        content = stream.read()
    return Response(content, media_type=artifact['content_type'], headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/problems/{problem_id}/candidates', status_code=201)
def understanding_edit(problem_id: UUID, body: CandidateInput, request: Request, idempotency_key: str = Header()):
    return understanding_for(request).save_candidate(problem_id, body.base_candidate_id, body.source_version_id, body.candidate, idempotency_key)


@router.post('/problems/{problem_id}/extraction-runs', status_code=202)
def understanding_start(problem_id: UUID, body: ExtractionRunInput, request: Request, idempotency_key: str = Header()):
    return understanding_for(request).start(problem_id, body.source_version_id, body.base_candidate_id, body.mode, idempotency_key)


@router.get('/extraction-runs/{run_id}')
def understanding_run(run_id: UUID, request: Request):
    return understanding_for(request).run(run_id)


@router.get('/problems/{problem_id}/extraction-runs')
def understanding_runs(problem_id: UUID, request: Request, limit: int = 20, before: UUID | None = None):
    if not 1 <= limit <= 100:
        raise ProductError('query.limit')
    return understanding_for(request).runs(problem_id, limit, before)


@router.get('/problems/{problem_id}/revisions/{revision_id}')
def revision(problem_id: UUID, revision_id: UUID, request: Request):
    a = app_for(request)
    return public(a.service.get_revision(a.ctx, problem_id, revision_id), 'id', 'revision_no', 'kind', 'domain_json', 'human_diff', 'created_at')


@router.post('/problems/{problem_id}/revision-preview')
def revision_preview(problem_id: UUID, body: Revision, request: Request):
    return app_for(request).revision_preview(problem_id, body.base_revision_id, body.domain)


@router.post('/problems/{problem_id}/revisions')
def revision_save(problem_id: UUID, body: Revision, request: Request, idempotency_key: str = Header()):
    return app_for(request).save_revision(problem_id, body.base_revision_id, body.domain, idempotency_key)


@router.post('/problems/{problem_id}/builds', status_code=202)
def build_submit(problem_id: UUID, body: Build, request: Request, idempotency_key: str = Header()):
    return app_for(request).submit(problem_id, body.source_id, body.batch_item_id, idempotency_key)


@router.get('/problems/{problem_id}/builds')
def history(problem_id: UUID, request: Request):
    a = app_for(request)
    return {'builds': [public(b, 'id', 'status', 'created_at', 'resolved_revision_id', 'error_code') for b in a.service.build_history(a.ctx, problem_id)]}


@router.get('/builds/{build_id}')
def build(build_id: UUID, request: Request): return app_for(request).build(build_id)


@router.post('/builds/{build_id}/rebuild-preview')
def rebuild_preview(build_id: UUID, body: Preview, request: Request):
    result = app_for(request).rebuild_preview(build_id, body.requested_stage)
    return {k: v for k, v in result.items() if k != 'target'}


@router.post('/builds/{build_id}/rebuild', status_code=202)
def rebuild(build_id: UUID, body: Rebuild, request: Request, idempotency_key: str = Header()):
    return app_for(request).rebuild(build_id, body.requested_stage, body.fingerprint, idempotency_key)


@router.post('/builds/{build_id}/cancel')
def cancel(build_id: UUID, request: Request):
    a = app_for(request)
    a.service.cancel(a.ctx, build_id)
    return a.build(build_id)


@router.get('/builds/{build_id}/artifacts/{artifact_id}')
def artifact(build_id: UUID, artifact_id: UUID, request: Request):
    a = app_for(request)
    with transaction(a.db) as c:
        b = scoped(c, m.builds, a.ctx, build_id)
        problem(c, a.ctx, b['problem_id'])
        ref = a.service.artifacts.verified(c, a.ctx, artifact_id)
        if ref['producer_build_id'] != build_id:
            accepted = c.execute(select(m.stage_artifacts.c.id).select_from(m.stage_artifacts.join(m.stage_attempts,
                m.stage_attempts.c.id == m.stage_artifacts.c.stage_attempt_id).join(m.build_stages, m.build_stages.c.accepted_attempt_id == m.stage_attempts.c.id))
                .where(m.build_stages.c.build_id == build_id, m.stage_artifacts.c.artifact_id == artifact_id)).first()
            if not accepted: raise Forbidden('artifact.not_in_build')
    with a.service.storage.open(ref['storage_key']) as f: content = f.read()
    mime = ref['content_type'] if ref['content_type'] in ('application/json', 'image/png', 'image/jpeg', 'image/webp') else 'text/plain'
    return Response(content, media_type=mime, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/pages/{page_id}/')
@router.get('/pages/{page_id}/{path:path}')
def page(page_id: UUID, request: Request, path: str = 'index.html'):
    a = app_for(request)
    # Authorize and verify the artifact before honoring a conditional request.
    # Weak validators identify the same content across identity/gzip encodings.
    ref = a.service.page_resource(a.ctx, page_id, path)
    etag = f'W/"{ref["sha256"]}"'
    headers = {'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, no-cache',
        'ETag': etag, 'Vary': 'Accept-Encoding',
        'Content-Security-Policy': "sandbox allow-scripts; default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'none'; base-uri 'none'; form-action 'none'"}
    condition = ','.join(request.headers.getlist('if-none-match')).strip()
    if condition == '*' or any(tag.strip() in (etag, etag[2:]) for tag in condition.split(',')):
        return Response(status_code=304, headers=headers)
    def chunks():
        with a.service.storage.open(ref['storage_key']) as f:
            while chunk := f.read(65536): yield chunk
    return StreamingResponse(chunks(), media_type=ref['content_type'],
        headers={**headers, 'Content-Length': str(ref['size_bytes'])})


@router.post('/pages/{page_id}/reviews')
def review(page_id: UUID, body: Review, request: Request, idempotency_key: str = Header()):
    a = app_for(request)
    def perform():
        result = a.service.review(a.ctx, page_id, body.decision, body.comment, body.supersedes_id)
        return public(result, 'id', 'decision', 'created_at')
    return a.request('page.review', idempotency_key, {'page_id': page_id, **body.model_dump()}, perform)


@router.get('/events')
def events(request: Request, kind: Literal['build', 'problem', 'batch'], aggregate_id: UUID, after: int = Query(0, ge=0)):
    return {'events': app_for(request).events(kind, aggregate_id, after)}


@router.websocket('/ws')
async def websocket(ws: WebSocket):
    try:
        a = app_for(ws)
        await ws.accept()
        subscriptions = await asyncio.wait_for(ws.receive_json(), timeout=15)
        if set(subscriptions) != {'streams'} or not 1 <= len(subscriptions['streams']) <= 20: raise ProductError('events.subscriptions')
        cursors = []
        for sub in subscriptions['streams']:
            kind, identity = sub['kind'], UUID(sub['id'])
            if kind not in ('build', 'batch', 'problem'): raise ProductError('events.stream_kind')
            if sub.get('after') is None:
                snapshot = await asyncio.to_thread(a.build if kind == 'build' else a.batch if kind == 'batch' else a.get_problem, identity)
                await asyncio.wait_for(ws.send_json({'type': 'snapshot', 'kind': kind, 'id': str(identity), 'data': snapshot}), 5)
                after = snapshot['last_seq']
            else: after = int(sub['after'])
            cursors.append([kind, identity, after])
        while True:
            for cursor in cursors:
                kind, identity, after = cursor
                for event in await asyncio.to_thread(a.events, kind, identity, after):
                    await asyncio.wait_for(ws.send_json({'type': 'event', 'kind': kind, 'id': str(identity), **event}), 5)
                    cursor[2] = event['seq']
            await asyncio.wait_for(ws.send_json({'type': 'heartbeat'}), 5)
            await asyncio.sleep(.5)
    except (WebSocketDisconnect, RuntimeError): return
    except (ProductError, ValueError, KeyError, TypeError, asyncio.TimeoutError) as exc:
        if ws.application_state.name == 'CONNECTED':
            try:
                await asyncio.wait_for(ws.send_json({'type': 'resnapshot_required' if isinstance(exc, Conflict) else 'error', 'code': str(exc) if isinstance(exc, ProductError) else 'events.invalid'}), 2)
            except (RuntimeError, asyncio.TimeoutError): pass
        try: await ws.close(code=1013 if isinstance(exc, asyncio.TimeoutError) else 1008)
        except RuntimeError: pass
