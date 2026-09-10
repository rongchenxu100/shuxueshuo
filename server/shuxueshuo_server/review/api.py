"""Loopback-only review API; requests never execute generation work."""
import asyncio
import json
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.datastructures import UploadFile

from .store import MAX_BYTES, ReviewStore, TERMINAL

router = APIRouter(prefix="/api/review")


def store_for(request: Request):
    client = request.client.host if request.client else ""
    if client not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "Review 仅供本机访问")
    host = request.url.hostname
    if host not in {"localhost", "127.0.0.1", "::1"} and not (client == "testclient" and host == "testserver"):
        raise HTTPException(403, "Review 仅供本机访问")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, "跨来源请求被拒绝")
    return getattr(request.app.state, "review_store", None) or ReviewStore()


def checked_get(store, run_id):
    try:
        return store.get(run_id)
    except KeyError:
        raise HTTPException(404, "运行不存在") from None


def created(doc):
    run_id = doc["id"]
    return {"schema_version": "review-start/v1", "run_id": run_id,
            "review_url": f"/review/runs/{run_id}",
            "events_url": f"/api/review/runs/{run_id}/events"}


@router.post("/runs", status_code=202)
async def upload(request: Request):
    store = store_for(request)
    # Bound the complete multipart body before parsing (including non-file parts).
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES + 65536:
            raise HTTPException(413, "图片须在 20 MiB 以内")
    async def receive():
        return {"type": "http.request", "body": bytes(body), "more_body": False}
    bounded = Request(request.scope, receive)
    try:
        async with bounded.form(max_files=1, max_fields=0) as form:
            image = form.get("image")
            if not isinstance(image, UploadFile):
                raise HTTPException(422, "请选择一张完整单题截图")
            content = await image.read(MAX_BYTES + 1)
            doc = await asyncio.to_thread(store.create, content, image.content_type or "", image.filename, enqueue=False)
            from .versions import Versions
            from .dependencies import probe
            target = await asyncio.to_thread(probe)
            Versions(store).enqueue(doc['id'], base_revision_id=None, target=target)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return created(doc)


@router.get("/runs")
def runs(request: Request):
    return {"schema_version": "review-list/v1", "runs": store_for(request).list()}


@router.get("/runs/{run_id}")
def detail(run_id: str, request: Request):
    from .replay import availability
    store = store_for(request)
    doc = checked_get(store, run_id)
    return {**doc, "rerun_options": availability(store, doc)}


@router.post("/runs/{run_id}/rerun", status_code=202)
def rerun(run_id: str, request: Request, from_stage: str | None = None):
    store = store_for(request)
    checked_get(store, run_id)
    try:
        from .rebuild import plan, submit
        preview = plan(store, run_id, from_stage or 'source')
        if from_stage and preview['rerun_stages'][0] != from_stage:
            raise ValueError('需要从 ' + preview['rerun_stages'][0] + ' 提前重跑；请先查看重建影响范围')
        return created(submit(store, run_id, preview))
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/runs/{run_id}/events")
async def events(run_id: str, request: Request):
    store = store_for(request)
    checked_get(store, run_id)
    try:
        after = max(0, int(request.headers.get("last-event-id", request.query_params.get("after", "0"))))
    except ValueError:
        raise HTTPException(422, "invalid event cursor") from None
    async def stream():
        cursor = after
        while not await request.is_disconnected():
            # Read state before events so terminal delivery cannot lose the last update.
            doc = await asyncio.to_thread(store.get, run_id)
            rows = await asyncio.to_thread(store.events, run_id, cursor)
            for event in rows:
                cursor = event["seq"]
                yield f"id: {cursor}\nevent: update\ndata: {json.dumps(event)}\n\n"
            if doc["status"] in TERMINAL and len(rows) < 100:
                yield "event: done\ndata: {}\n\n"
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
def artifact(run_id: str, artifact_id: str, request: Request):
    store = store_for(request)
    try:
        ref, content = store.read(run_id, artifact_id)
    except KeyError:
        raise HTTPException(404, "产物不存在") from None
    except ValueError:
        raise HTTPException(409, "产物完整性检查失败") from None
    media = ref["media_type"]
    # Only registered page route can execute HTML; debug artifacts are inert.
    if media not in {"application/json", "image/png", "image/jpeg", "image/webp"}:
        media = "text/plain"
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
    if "download" in request.query_params:
        headers["Content-Disposition"] = f'attachment; filename="{artifact_id}"'
    return Response(content, media_type=media, headers=headers)


@router.get("/runs/{run_id}/page/{path:path}")
def page(run_id: str, path: str, request: Request):
    store = store_for(request)
    doc = checked_get(store, run_id)
    ref = next((a for a in doc["artifacts"] if a.get("page_path") == path), None)
    if doc["status"] != "succeeded" or ref is None:
        raise HTTPException(404, "页面尚未通过完整校验")
    _, content = store.read(run_id, ref["id"])
    return Response(content, media_type=ref["media_type"], headers={
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        "Content-Security-Policy": "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'",
    })


@router.get('/runs/{run_id}/problem')
def problem(run_id: str, request: Request):
    from .problem_edit import editable
    store = store_for(request)
    checked_get(store, run_id)
    try:
        return editable(store, run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/runs/{run_id}/problem/{action}')
async def edit_problem(run_id: str, action: str, request: Request):
    from .problem_edit import preview
    from .versions import Conflict
    store = store_for(request)
    checked_get(store, run_id)
    if action not in {'preview', 'revisions'}: raise HTTPException(404, '未知操作')
    try:
        body = await request.json()
        if not isinstance(body, dict): raise ValueError('需要 JSON 对象')
        return await asyncio.to_thread(preview, store, run_id, body, save=action == 'revisions')
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/runs/{run_id}/rebuild-plan')
def rebuild_plan(run_id: str, request: Request, requested_stage: str | None = None):
    from .rebuild import plan
    store = store_for(request)
    checked_get(store, run_id)
    try:
        return plan(store, run_id, requested_stage)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/runs/{run_id}/rebuild', status_code=202)
async def rebuild(run_id: str, request: Request):
    from .rebuild import submit
    store = store_for(request)
    checked_get(store, run_id)
    try:
        body = await request.json()
        if not isinstance(body, dict): raise ValueError('需要 JSON 对象')
        return created(await asyncio.to_thread(submit, store, run_id, body))
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
