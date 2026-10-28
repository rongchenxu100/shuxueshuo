"""Authenticated student search backed by PostgreSQL and private files."""

import asyncio
import json
import logging
import math
import os
import re
import secrets
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, nullcontext
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from shuxueshuo_server.auth.api import (
    cookie_name,
    require_origin,
    require_user,
    service,
)
from shuxueshuo_server.auth.service import AuthService
from shuxueshuo_server.graph_lesson.stage_three.events import CursorExpired
from shuxueshuo_server.graph_lesson.stage_three.storage import (
    RunNotFound,
    RunUnavailable,
    StorageContextRequired,
    require_storage_context,
    storage_context,
)
from shuxueshuo_server.problem_understanding.workflow_ledger import save
from shuxueshuo_server.solver.extraction.request_guard import (
    require_model_request_scope,
)

from . import stage_three
from .admission import SearchLimits
from .identity import IdentityUnavailable, build_identity
from .lesson import present_lesson, public_problem_text, run_stage_two
from .ocr_client import OcrClient, OcrWorkerError
from .page_orientation import rotate_clockwise
from .question_image import question_png
from .repository import SearchError
from .segmentation import segment
from .stage_one import (
    RESULT_FILE,
    ledger_calls,
    reviewing_candidate,
    run_question_image,
)
from .task_runner import SearchTaskRunner

MAX_UPLOAD = 20 * 1024 * 1024
MAX_UPLOAD_PIXELS = 32_000_000
IMAGE_PREPARE_LOCK = threading.Lock()
PAGE_SIDE = 4096
PREVIEW_SIDE = 1600
MAX_PAGE_ROTATIONS = 8
WS_AUTH_INTERVAL = 3.0
WS_POLL_MIN_INTERVAL = 0.15
WS_POLL_MAX_INTERVAL = 3.0
ID = re.compile(r"^[0-9a-f]{12}$")
FAILURES = {"missing_figure": "figure", "unreadable": "unclear", "ambiguous": "unclear"}
LOGGER = logging.getLogger(__name__)


async def execution_storage_scope():
    with require_storage_context():
        yield


def search_user(request: Request, user: Annotated[dict, Depends(require_user)],
                auth: Annotated[AuthService, Depends(service)]):
    expected = request.headers.get("X-Search-User")
    if expected and expected != str(user["id"]):
        raise HTTPException(409, "search.account_changed")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request, auth)
    if request.method == "POST":
        require_accepting(request.app)
    request.state.search_user = user
    return user


def require_accepting(app):
    drain_path = getattr(app.state, "search_drain_path", None)
    if not getattr(app.state, "search_accepting", True) or (drain_path is not None and drain_path.exists()):
        raise HTTPException(503, "service.draining")


def repository(request):
    value = getattr(request.app.state, "search_repository", None)
    if value is None:
        raise HTTPException(503, "search.unavailable")
    return value


def image_response(path, media_type):
    stream = path.open("rb")

    def chunks():
        try:
            while chunk := stream.read(65536):
                yield chunk
        finally:
            stream.close()

    return StreamingResponse(chunks(), media_type=media_type)


class SearchRoute(APIRoute):
    def __init__(self, *args, dependencies=None, **kwargs):
        dependencies = list(dependencies or [])
        if not any(dependency.dependency is search_user for dependency in dependencies):
            dependencies.append(Depends(search_user))
        super().__init__(*args, dependencies=dependencies, **kwargs)

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request):
            try:
                repo = repository(request)
                with storage_context(repo.db, request.path_params.get("search_id"), clock=repo.clock):
                    response = await handler(request)
            except SearchError as exc:
                response = JSONResponse({"detail": exc.code}, status_code=exc.status)
            except HTTPException as exc:
                response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                                        headers=exc.headers)
            except RunNotFound:
                response = JSONResponse({"detail": "search.not_found"}, status_code=404)
            except RunUnavailable as exc:
                response = JSONResponse({"detail": exc.code}, status_code=410)
            except (SQLAlchemyError, OSError, StorageContextRequired):
                LOGGER.exception("Student search storage operation failed")
                response = JSONResponse({"detail": "search.storage_unavailable"}, status_code=503)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


class ProblemRequest(BaseModel):
    page_id: str
    box: list[float] = Field(min_length=4, max_length=4)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


class RotatePageRequest(BaseModel):
    degrees: int = Field(strict=True, gt=0, le=270, multiple_of=90)


class LessonRequest(BaseModel):
    client_request_id: str | None = Field(default=None, min_length=1, max_length=128)


def _save_preview(page, path):
    """Publish a bounded preview atomically, also for legacy pages on first read."""
    with IMAGE_PREPARE_LOCK:
        preview = page.copy()
        preview.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".jpg", delete=False) as output:
            temporary = Path(output.name)
            preview.save(output, format="JPEG", quality=85, optimize=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _observed_orientation(observed, *, manual=False):
    """Reject inconsistent worker metadata before publishing an image/box pair."""
    if "orientation" not in observed:
        # Old recorded observations and worker stubs describe the original frame.
        return {"status": "upright", "rotation_degrees": 0,
                "predicted_degrees": None, "confidence": None}
    orientation = observed["orientation"]
    if not isinstance(orientation, dict):
        raise OcrWorkerError("orientation.invalid")
    status = orientation.get("status")
    rotation = orientation.get("rotation_degrees")
    predicted = orientation.get("predicted_degrees")
    confidence = orientation.get("confidence")
    statuses = {"upright", "corrected", "uncertain", "manual"} if manual else {"upright", "corrected", "uncertain"}
    if (type(status) is not str or status not in statuses
            or type(rotation) is not int or rotation not in {0, 90, 180, 270}
            or (predicted is not None and (type(predicted) is not int or predicted not in {0, 90, 180, 270}))
            or (confidence is not None and (type(confidence) not in {int, float}
                                           or not 0 <= confidence <= 1 or not math.isfinite(confidence)))
            or ((status == "corrected") != (rotation != 0))):
        raise OcrWorkerError("orientation.invalid")
    return {"status": status, "rotation_degrees": rotation,
            "predicted_degrees": predicted, "confidence": confidence}


def create_search_router(root, *, stage_three_hooks=None):
    ocr = OcrClient()
    limits = SearchLimits.from_env()
    executor = ThreadPoolExecutor(max_workers=limits.generation_workers, thread_name_prefix="search-stage-one")
    runs = SearchTaskRunner(executor, limits.generation_workers, limits.generation_queue_size)
    lesson_errors, judging = {}, set()
    errors_lock = threading.Lock()
    @asynccontextmanager
    async def lifespan(app):
        app.state.search_task_runner = runs
        stopped = asyncio.Event()

        async def reap():
            while not stopped.is_set():
                try:
                    await asyncio.wait_for(stopped.wait(), timeout=1)
                except TimeoutError:
                    try:
                        await run_in_threadpool(runs.reap)
                    except Exception:
                        LOGGER.exception('Search queue cancellation will retry')

        reaper = asyncio.create_task(reap())
        try:
            yield
        finally:
            app.state.search_accepting = False
            stopped.set()
            await reaper
            try:
                await run_in_threadpool(runs.shutdown)
            finally:
                await run_in_threadpool(ocr.close)

    router = APIRouter(prefix="/api/search", route_class=SearchRoute, lifespan=lifespan,
                       dependencies=[Depends(execution_storage_scope)])

    def page_dir(request, page_id):
        return repository(request).page(request.state.search_user, page_id)["path"]

    def problem_dir(request, search_id, *, for_execution=False):
        row = repository(request).submission(request.state.search_user, search_id, require_artifacts=True)
        if for_execution and row["lesson_status"] == "unavailable":
            raise HTTPException(409, "lesson.execution_unavailable")
        return row["path"]

    def prepare_page(source, repo, user, **options):
        page_id = secrets.token_hex(6)
        with repo.storage.page_lock(page_id):
            return write_page(source, repo, user, page_id, **options)

    def write_page(source, repo, user, page_id, *, parent_page_id=None, manual_degrees=None, rotation_count=0):
        """Run the complete image/OCR/artifact pipeline on one worker thread.

        source.png is bounded EXIF-normalized upload input, or an already
        manually rotated parent page. Worker angles refer to that source; public
        manual angles instead refer to the immutable parent page.png.
        """
        directory = repo.storage.path(repo.storage.page_key(page_id))
        directory.mkdir(parents=True)
        source.save(directory / "source.png")
        try:
            if manual_degrees is None:
                observed = ocr.observe(directory / "source.png")
            else:
                observed = ocr.observe(directory / "source.png", auto_orient=False)
            orientation = _observed_orientation(observed, manual=manual_degrees is not None)
            save(directory / "ocr.json", observed)
            if manual_degrees is not None:
                if orientation["rotation_degrees"]:
                    raise OcrWorkerError("orientation.manual_auto_rotation")
                page = source
                orientation = {"status": "manual", "rotation_degrees": manual_degrees,
                               "predicted_degrees": None, "confidence": None}
            else:
                with IMAGE_PREPARE_LOCK:
                    page = rotate_clockwise(source, orientation["rotation_degrees"])
        except OcrWorkerError as exc:
            LOGGER.exception("Student page OCR failed")
            raise HTTPException(503, "ocr.unavailable") from exc
        result = segment(observed)
        payload = {"page_id": page_id, "image_url": f"/api/search/pages/{page_id}/image",
                   "preview_url": f"/api/search/pages/{page_id}/preview",
                   "width": page.width, "height": page.height, "orientation": orientation,
                   "rotation_reference": "parent_page" if manual_degrees is not None else "upload_after_exif",
                   "rotation_count": rotation_count,
                   "mode": result.mode, "regions": result.regions, "diagnostics": result.diagnostics,
                   "latency_ms": observed["latency_ms"]}
        if parent_page_id is not None:
            payload["parent_page_id"] = parent_page_id
        page.save(directory / "page.png")
        _save_preview(page, directory / "preview.jpg")
        save(directory / "segments.json", payload)
        repo.register_page(user, page_id, payload, parent_page_id=parent_page_id)
        return payload

    def prepare_upload(body, repo, user, lease=None):
        with lease.hold() if lease is not None else nullcontext():
            return process_upload(body, repo, user)

    def process_upload(body, repo, user):
        try:
            with IMAGE_PREPARE_LOCK, warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(body)) as image:
                    if image.width * image.height > MAX_UPLOAD_PIXELS:
                        raise HTTPException(413, "page.pixels")
                    scale = min(1.0, PAGE_SIDE / max(image.size))
                    image.draft("RGB", (max(1, round(image.width * scale)), max(1, round(image.height * scale))))
                    image.thumbnail((PAGE_SIDE, PAGE_SIDE), Image.Resampling.LANCZOS)
                    page = ImageOps.exif_transpose(image).convert("RGB")
                    page.info.clear()
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise HTTPException(413, "page.pixels") from exc
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(400, "page.not_an_image") from exc
        return prepare_page(page, repo, user)

    @router.post("/pages")
    async def upload_page(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_UPLOAD:
                raise HTTPException(413, "page.size")
        if not body:
            raise HTTPException(400, "page.size")
        return await run_in_threadpool(prepare_upload, bytes(body), repository(request), request.state.search_user,
                                       getattr(request.state, 'search_upload_lease', None))

    @router.post("/pages/{page_id}/rotate")
    def rotate_page(page_id: str, body: RotatePageRequest, request: Request):
        lease = getattr(request.state, 'search_upload_lease', None)
        with lease.hold() if lease is not None else nullcontext():
            return process_rotation(page_id, body, request)

    def process_rotation(page_id, body, request):
        page_dir(request, page_id)
        with repository(request).storage.page_lock(page_id, blocking=True):
            directory = page_dir(request, page_id)
            manifest = json.loads((directory / "segments.json").read_text(encoding="utf-8"))
            count = manifest.get("rotation_count", 0)
            if type(count) is not int or count < 0:
                raise HTTPException(409, "page.rotation_metadata_invalid")
            if count >= MAX_PAGE_ROTATIONS:
                raise HTTPException(409, "page.rotation_limit")
            with IMAGE_PREPARE_LOCK, Image.open(directory / "page.png") as page:
                page.thumbnail((PAGE_SIDE, PAGE_SIDE), Image.Resampling.LANCZOS)
                source = rotate_clockwise(page.convert("RGB"), body.degrees)
                source.info.clear()
        return prepare_page(source, repository(request), request.state.search_user,
                            parent_page_id=page_id, manual_degrees=body.degrees, rotation_count=count + 1)

    @router.get("/pages/{page_id}/image")
    def page_image(page_id: str, request: Request):
        page_dir(request, page_id)
        with repository(request).storage.page_lock(page_id, blocking=True):
            return image_response(page_dir(request, page_id) / "page.png", "image/png")

    @router.get("/pages/{page_id}/preview")
    def page_preview(page_id: str, request: Request):
        page_dir(request, page_id)
        with repository(request).storage.page_lock(page_id, blocking=True):
            return image_response(page_dir(request, page_id) / "preview.jpg", "image/jpeg")

    @router.post("/problems")
    def start_problem(body: ProblemRequest, request: Request):
        repo, user = repository(request), request.state.search_user
        existing = repo.find_request(user, body.client_request_id) if body.client_request_id else None
        if existing is not None:
            return {"search_id": existing["id"]}
        directory = page_dir(request, body.page_id)
        if not all(math.isfinite(value) for value in body.box):
            raise HTTPException(400, "box.invalid")
        x0, y0, x1, y1 = (min(1.0, max(0.0, v)) for v in body.box)
        if x1 - x0 < 0.02 or y1 - y0 < 0.01:
            raise HTTPException(400, "box.too_small")
        if os.getenv("RUN_LLM_INTEGRATION") != "1":
            raise HTTPException(503, "stage_one.disabled")
        with repo.storage.page_lock(body.page_id, blocking=True):
            directory = page_dir(request, body.page_id)
            with IMAGE_PREPARE_LOCK, Image.open(directory / "page.png") as page:
                width, height = page.size
                crop = page.crop((round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height)))
                png = question_png(crop)
        with Image.open(BytesIO(png)) as sent:
            size = list(sent.size)
        search_id = secrets.token_hex(6)
        output = repo.storage.path(repo.storage.submission_key(search_id))
        lifecycle = repo.storage.lifecycle_lock(search_id)
        try:
            require_accepting(request.app)
            output.mkdir(parents=True)
            crop.save(output / "original.png")
            save(output / "crop.json", {"page_id": body.page_id, "box": [x0, y0, x1, y1], "page_size": [width, height],
                                        "crop_size": size, "bytes": len(png)})
            (output / "question.png").write_bytes(png)
            submission, created = repo.create_submission(user, search_id, body.page_id,
                                                         [x0, y0, x1, y1], client_request_id=body.client_request_id,
                                                         admit=True)
        except (SearchError, HTTPException):
            try:
                repo.storage.remove(repo.storage.submission_key(search_id))
            finally:
                lifecycle.close()
            raise
        except BaseException:
            lifecycle.close()
            raise
        if not created:
            lifecycle.close()
            return {"search_id": submission["id"]}
        ticket = submission['admission_ticket']

        def cancelled():
            try:
                repo.set_state(search_id, recognition_state="interrupted", error_code="search.interrupted")
            finally:
                with errors_lock:
                    judging.discard(search_id)
                lifecycle.close()

        def work():
            from shuxueshuo_server.problem_understanding.batch_smoke import (
                live_provider_factory,
            )

            try:
                require_model_request_scope()
                if not repo.set_state(search_id, recognition_state="running"):
                    return
                # The image's code tree is read-only in containers; the cache lives in the data root.
                provider = live_provider_factory(
                    "deepseek", file_cache_dir=repo.storage.root.parent / "deepseek-files-cache")()
                result = run_question_image(png, output, provider, problem_id=search_id)
                if result is None:
                    result = stage_three.read(output / RESULT_FILE)
                if result["status"] == "reviewed_candidate":
                    try:
                        identity = build_identity(result)
                    except IdentityUnavailable as exc:
                        repo.set_state(search_id, recognition_state="needs_confirmation", error_code=exc.code)
                        return
                    if not repo.associate(search_id, identity):
                        return
                    judge(search_id, output, result, repo=repo)
                else:
                    status = "needs_confirmation" if result["status"] in {"needs_confirmation", "ambiguous", "missing_figure", "unreadable"} else "failed"
                    repo.set_state(search_id, recognition_state=status, error_code=result["status"])
            except SearchError as exc:
                repo.set_state(search_id, recognition_state="failed", error_code=exc.code)
            except Exception:
                LOGGER.exception("Student question recognition failed")
                repo.set_state(search_id, recognition_state="failed", error_code="search.recognition_failed")
            finally:
                with errors_lock:
                    judging.discard(search_id)
                lifecycle.close()

        # Marked before result.json can appear, so a poll never sees "done" without stage two.
        with errors_lock:
            judging.add(search_id)
        try:
            runs.submit(ticket, repo, work, cancelled)
        except BaseException:
            try:
                runs.cancel_unstarted(ticket, repo)
                repo.set_state(search_id, recognition_state="interrupted", error_code="search.queue_failed")
            finally:
                with errors_lock:
                    judging.discard(search_id)
                lifecycle.close()
            raise
        return {"search_id": search_id, "crop_size": size}

    def judge(search_id, directory, result, lease=None, *, repo):
        """Stage two: usually program-only; one LLM call only when several types hold."""
        from shuxueshuo_server.graph_lesson.stage_two.selection import (
            live_provider_factory,
        )

        with errors_lock:
            judging.add(search_id)
            lesson_errors.pop(search_id, None)
        try:
            require_model_request_scope()
            if not repo.set_state(search_id, lesson_state="running"):
                return
            lease = lease or stage_three.acquire_problem(directory)
            run_stage_two(directory, result, provider=live_provider_factory(),
                          unsupported_root=directory / "unsupported")
            if not repo.set_state(search_id, lesson_state="running"):
                return
            with storage_context(repo.db, search_id, clock=repo.clock):
                stage_three.run_stage_three(stage_three.latest_attempt(directory), hooks=stage_three_hooks)
                finish_lesson(repo, search_id, directory)
        except Exception as exc:
            LOGGER.exception("Student lesson generation failed")
            repo.set_state(search_id, lesson_state="failed", error_code="search.lesson_failed")
            with errors_lock:
                lesson_errors[search_id] = _message(exc)
        finally:
            if lease is not None:
                stage_three.release_problem(lease)
            with errors_lock:
                judging.discard(search_id)

    def finish_lesson(repo, search_id, directory):
        attempt = stage_three.latest_attempt(directory)
        stage_two = stage_three.read(attempt / stage_three.RESULT) if attempt else {}
        output = attempt / "stage-three" if attempt else directory
        final = output / "stage-three-result.json"
        if stage_two.get("status") == "input_error" or any(goal.get("status") == "selection_failed" for goal in stage_two.get("goals", [])):
            status = "failed"
        elif not any(goal.get("status") == "resolved" for goal in stage_two.get("goals", [])):
            status = "unsupported"
        elif not final.is_file() or stage_three.has_pending_interactions(output):
            status = "interrupted"
        else:
            result = stage_three.read(final)
            usable = any(goal.get("status") == "solved" and any(route.get("status") == "verified"
                         for route in goal.get("routes", [])) for goal in result.get("goals", []))
            if result.get("status") == "completed" and usable and stage_three.stream_descriptor(search_id, output):
                status = "ready"
            elif result.get("status") == "completed" and not usable:
                status = "unsupported"
            else:
                status = "failed"
        repo.set_state(search_id, lesson_state=status)

    def lesson(search_id, directory, result):
        if stage_three.pending_retry(directory) is not None:
            return {"status": "running", "execution_status": "starting", "stream": None}
        attempt = stage_three.latest_attempt(directory)
        stage_two = (stage_three.read(attempt / stage_three.RESULT)
                     if attempt is not None and (attempt / stage_three.RESULT).is_file() else None)
        with errors_lock:
            running, error = search_id in judging, lesson_errors.get(search_id)
        if stage_two is None:
            if running:
                return {"status": "running", "execution_status": "not_started", "stream": None}
            return {"status": "error", "message": error or "stage_two.missing"}
        presented = present_lesson(stage_two, result.get("features", []),
                                   (result.get("candidate") or {}).get("original_text", ""), search_id,
                                   candidate=result.get("candidate"), display_text=public_problem_text(result))
        presented.update(stage_three.presentation(directory, search_id, running=running, attempt=attempt))
        if error:
            presented["execution_error"] = error
        return presented

    @router.post("/problems/{search_id}/lesson")
    def retry_lesson(search_id: str, request: Request, body: LessonRequest | None = None):
        """Rerun stage two only (no image reading) after a judging failure."""
        repo = repository(request)
        directory = problem_dir(request, search_id, for_execution=True)
        row = repo.submission(request.state.search_user, search_id)
        if row["recognition_status"] != "reviewed":
            raise HTTPException(409, "stage_one.not_reviewed")
        request_id = body.client_request_id if body else None
        existing = repo.admission.find_request(request.state.search_user, 'rerun', request_id) if request_id else None
        if existing is not None:
            if existing.search_id != search_id:
                raise HTTPException(409, 'search.request_conflict')
            return {'status': row['lesson_status'], 'duplicate': True}
        with errors_lock:
            if search_id in judging:
                return {"status": "running"}
        lifecycle = repo.storage.lifecycle_lock(search_id)
        try:
            problem_dir(request, search_id, for_execution=True)
            if not (directory / RESULT_FILE).is_file():
                raise HTTPException(409, "stage_one.not_done")
            result = json.loads((directory / RESULT_FILE).read_text(encoding="utf-8"))
            if result["status"] != "reviewed_candidate":
                raise HTTPException(409, "stage_one.not_reviewed")
            lease = stage_three.acquire_problem(directory)
        except stage_three.LessonBusy as exc:
            lifecycle.close()
            raise HTTPException(409, str(exc)) from exc
        except BaseException:
            lifecycle.close()
            raise
        ticket = None
        try:
            require_accepting(request.app)
            ticket = repo.reserve_lesson(request.state.search_user, search_id, 'rerun', request_id)
            if not ticket.created:
                stage_three.release_problem(lease)
                lifecycle.close()
                return {'status': row['lesson_status'], 'duplicate': True}
            stage_three.reserve_retry(directory)
        except BaseException:
            try:
                if ticket is not None and ticket.created:
                    runs.cancel_unstarted(ticket, repo)
                    repo.set_state(search_id, lesson_state='interrupted')
            finally:
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()
            raise
        with errors_lock:
            judging.add(search_id)
            lesson_errors.pop(search_id, None)
        def work():
            try:
                judge(search_id, directory, result, lease, repo=repo)
            finally:
                with errors_lock:
                    judging.discard(search_id)
                lifecycle.close()

        def cancelled():
            try:
                repo.set_state(search_id, lesson_state='interrupted', error_code='search.interrupted')
            finally:
                with errors_lock:
                    judging.discard(search_id)
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()

        try:
            runs.submit(ticket, repo, work, cancelled)
        except BaseException:
            try:
                runs.cancel_unstarted(ticket, repo)
                repo.set_state(search_id, lesson_state="interrupted")
            finally:
                with errors_lock:
                    judging.discard(search_id)
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()
            raise
        return {"status": "running"}

    def queue_execution(search_id, directory, operation, *, repo, user, app, validate=None):
        with errors_lock:
            if search_id in judging:
                raise HTTPException(409, "lesson.running")
        lifecycle = repo.storage.lifecycle_lock(search_id)
        try:
            row = repo.submission(user, search_id, require_artifacts=True)
            if row["lesson_status"] == "unavailable":
                raise HTTPException(409, "lesson.execution_unavailable")
            lease = stage_three.acquire_problem(directory)
        except stage_three.LessonBusy as exc:
            lifecycle.close()
            raise HTTPException(409, str(exc)) from exc
        except BaseException:
            lifecycle.close()
            raise
        # The request may have read the previous attempt just before a
        # retry acquired this lease. Validate its identity while reserved,
        # before queueing work or changing the in-memory running marker.
        ticket = None
        try:
            require_accepting(app)
            if validate is not None:
                validate()
            ticket = repo.reserve_lesson(user, search_id, 'continuation')
        except stage_three.LessonConflict as exc:
            try:
                stage_three.release_problem(lease)
            finally:
                lifecycle.close()
            raise HTTPException(409, str(exc)) from exc
        except BaseException:
            try:
                if ticket is not None:
                    runs.cancel_unstarted(ticket, repo)
            finally:
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()
            raise
        with errors_lock:
            judging.add(search_id)
            lesson_errors.pop(search_id, None)

        def work():
            try:
                if not repo.set_state(search_id, lesson_state="running"):
                    return
                with storage_context(repo.db, search_id, clock=repo.clock):
                    operation()
                    finish_lesson(repo, search_id, directory)
            except Exception as exc:
                LOGGER.exception("Student lesson continuation failed")
                repo.set_state(search_id, lesson_state="failed", error_code="search.lesson_failed")
                with errors_lock:
                    lesson_errors[search_id] = _message(exc)
            finally:
                with errors_lock:
                    judging.discard(search_id)
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()

        def cancelled():
            try:
                repo.set_state(search_id, lesson_state='interrupted', error_code='search.interrupted')
            finally:
                with errors_lock:
                    judging.discard(search_id)
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()

        try:
            runs.submit(ticket, repo, work, cancelled)
        except BaseException:
            try:
                runs.cancel_unstarted(ticket, repo)
                repo.set_state(search_id, lesson_state="interrupted")
            finally:
                with errors_lock:
                    judging.discard(search_id)
                try:
                    stage_three.release_problem(lease)
                finally:
                    lifecycle.close()
            raise

    def locate_run(request, search_id, run_id, *, for_execution=False):
        directory = problem_dir(request, search_id, for_execution=for_execution)
        try:
            return directory, stage_three.find_run(directory, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, "lesson.run_not_found") from exc

    @router.post("/problems/{search_id}/lesson/start")
    def start_existing_lesson(search_id: str, request: Request):
        """Explicitly start stage three for an already saved stage-two attempt."""
        directory = problem_dir(request, search_id, for_execution=True)
        attempt = stage_three.latest_attempt(directory)
        if attempt is None or not (attempt / stage_three.RESULT).is_file():
            raise HTTPException(409, "stage_two.not_done")
        if (attempt / "stage-three").exists():
            return stage_three.presentation(directory, search_id)
        queue_execution(search_id, directory, lambda: stage_three.run_stage_three(attempt, hooks=stage_three_hooks),
                        repo=repository(request), user=request.state.search_user, app=request.app,
                        validate=lambda: stage_three.assert_current_attempt(directory, attempt))
        return {"status": "running", **stage_three.presentation(directory, search_id, running=True)}

    @router.post("/problems/{search_id}/lesson/{run_id}/resume")
    def resume_lesson(search_id: str, run_id: str, request: Request):
        directory, output = locate_run(request, search_id, run_id, for_execution=True)
        try:
            stage_three.assert_resumable(directory, output)
        except stage_three.LessonConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        if (output / "stage-three-result.json").is_file() and not stage_three.has_pending_interactions(output):
            return {"status": "completed", **stage_three.presentation(directory, search_id)}
        queue_execution(search_id, directory,
                        lambda: stage_three.resume_stage_three(directory, run_id, hooks=stage_three_hooks),
                        repo=repository(request), user=request.state.search_user, app=request.app,
                        validate=lambda: stage_three.assert_resumable(directory, output))
        return {"status": "running", "stream": stage_three.stream_descriptor(search_id, output)}

    @router.get("/problems/{search_id}/lesson/{run_id}/snapshot")
    def lesson_snapshot(search_id: str, run_id: str, request: Request):
        problem_dir(request, search_id)
        with repository(request).storage.read_lock(search_id):
            _directory, output = locate_run(request, search_id, run_id)
            if stage_three.stream_descriptor(search_id, output, strict=True) is None:
                raise HTTPException(409, "lesson.stream_not_ready")
            return JSONResponse(stage_three.open_store(output).snapshot(), headers={"Cache-Control": "no-store"})

    def expired_payload(exc):
        return {"error": "events.cursor_expired", "cursor_expired": True, "minimum_seq": exc.minimum_seq}

    @router.get("/problems/{search_id}/lesson/{run_id}/events")
    def lesson_events(search_id: str, run_id: str, request: Request, after_seq: int = 0):
        problem_dir(request, search_id)
        try:
            with repository(request).storage.read_lock(search_id):
                _directory, output = locate_run(request, search_id, run_id)
                if stage_three.stream_descriptor(search_id, output, strict=True) is None:
                    raise HTTPException(409, "lesson.stream_not_ready")
                payload = stage_three.event_page(output, after_seq)
        except CursorExpired as exc:
            return JSONResponse(expired_payload(exc), status_code=409, headers={"Cache-Control": "no-store"})
        except RunUnavailable:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    @router.websocket("/problems/{search_id}/lesson/{run_id}/ws")
    async def lesson_websocket(websocket: WebSocket, search_id: str, run_id: str, after: int = 0):
        accepted = False
        next_authorization = 0.0

        def authorize():
            auth = service(websocket)
            require_origin(websocket, auth)
            user = auth.current_user(websocket.cookies.get(cookie_name(auth.config)))
            if user is None:
                raise HTTPException(401, "search.login_required")
            websocket.state.search_user = user
            return locate_run(websocket, search_id, run_id)

        def read_events():
            nonlocal next_authorization
            repo = repository(websocket)
            with storage_context(repo.db, search_id, clock=repo.clock), repo.storage.read_lock(search_id):
                try:
                    payload = stage_three.event_page(output, after)
                except (RunNotFound, OSError, ValueError):
                    authorize()
                    raise
                if first or payload["events"] or monotonic() >= next_authorization:
                    authorize()
                    next_authorization = monotonic() + WS_AUTH_INTERVAL
                return payload

        try:
            _directory, output = await run_in_threadpool(authorize)
            repo = repository(websocket)
            def descriptor():
                with storage_context(repo.db, search_id, clock=repo.clock):
                    return stage_three.stream_descriptor(search_id, output, strict=True)
            if await run_in_threadpool(descriptor) is None:
                raise HTTPException(409, "lesson.stream_not_ready")
            await websocket.accept()
            accepted = True
            first = True
            poll_interval = WS_POLL_MIN_INTERVAL
            loop = asyncio.get_running_loop()
            while True:
                payload = await run_in_threadpool(read_events)
                if first or payload["events"]:
                    await websocket.send_json(payload)
                    after = payload["last_seq"]
                    first = False
                poll_interval = (WS_POLL_MIN_INTERVAL if payload["events"]
                                 else min(poll_interval * 2, WS_POLL_MAX_INTERVAL))
                deadline = loop.time() + min(poll_interval, max(0.0, next_authorization - monotonic()))
                while (remaining := deadline - loop.time()) > 0:
                    try:
                        await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
                    except TimeoutError:
                        break
        except CursorExpired as exc:
            await websocket.send_json(expired_payload(exc))
            await websocket.close(code=4009)
        except (RunNotFound, RunUnavailable) as exc:
            if accepted:
                await websocket.send_json({"error": exc.code})
            await websocket.close(code=4404 if isinstance(exc, RunNotFound) else 4410)
        except (HTTPException, SearchError, ValueError) as exc:
            status = getattr(exc, "status_code", 400)
            if accepted:
                await websocket.send_json({"error": getattr(exc, "detail", getattr(exc, "code", "search.stream_invalid"))})
            await websocket.close(code={401: 4401, 403: 4403, 404: 4404, 410: 4410}.get(status, 4400))
        except (SQLAlchemyError, OSError, StorageContextRequired):
            await websocket.close(code=1011)
        except WebSocketDisconnect:
            pass

    @router.get("/problems")
    def history(request: Request, limit: int = Query(default=20, ge=1, le=100),
                offset: int = Query(default=0, ge=0)):
        return repository(request).history(request.state.search_user, limit=limit, offset=offset)

    @router.delete("/problems/{search_id}")
    def delete_problem(search_id: str, request: Request):
        repo = repository(request)
        result = repo.delete(request.state.search_user, search_id)
        with errors_lock:
            for identifier in result["deleted_search_ids"]:
                lesson_errors.pop(identifier, None)
        return result

    @router.get("/problems/{search_id}")
    def problem_status(search_id: str, request: Request):
        repository(request).submission(request.state.search_user, search_id)
        with repository(request).storage.read_lock(search_id):
            return describe_problem(search_id, request)

    def describe_problem(search_id, request):
        row = repository(request).submission(request.state.search_user, search_id)
        directory = row["path"]
        state = {"search_id": search_id, "user_id": str(row["user_id"]),
                 "problem_id": str(row["problem_id"]) if row["problem_id"] else None,
                 "statement": row["statement"], "recognition_status": row["recognition_status"],
                 "lesson_status": row["lesson_status"], "artifact_state": row["artifact_state"]}
        unavailable = "disabled" if row["problem_status"] == "disabled" or row["error_code"] == "problem.disabled" else "expired" if row["artifact_state"] != "active" else "unavailable" if row["lesson_status"] == "unavailable" else None
        if unavailable:
            return {**state, "state": "done", "status": unavailable, "outcome": unavailable,
                    "original_text": row["statement"] or "", "lesson": None}
        calls = ledger_calls(directory / "workflow")
        state.update(calls=[{"stage": stage, "status": status} for stage, status in calls],
                     crop=stage_three.read(directory / "crop.json"))
        if row["recognition_status"] == "interrupted" or (row["recognition_status"] == "failed" and not (directory / RESULT_FILE).is_file()):
            return {**state, "state": "done", "status": row["recognition_status"],
                    "outcome": "error", "error_code": row["error_code"]}
        if (directory / RESULT_FILE).exists():
            result = json.loads((directory / RESULT_FILE).read_text(encoding="utf-8"))
            presented = _present(result)
            if row["recognition_status"] == "failed" and presented["outcome"] == "ok":
                presented.update(outcome="error", status="failed", error_code=row["error_code"])
            if row["recognition_status"] in {"queued", "running"}:
                return {**state, "state": "running", "preview": result.get("candidate")}
            if row["recognition_status"] == "needs_confirmation" and presented["outcome"] == "ok":
                presented.update(outcome="unclear", status="needs_confirmation", error_code=row["error_code"])
            if presented["outcome"] == "ok" and row["recognition_status"] == "reviewed":
                presented["lesson"] = lesson(search_id, directory, result)
            return {**state, "state": "done", **presented}
        if row["recognition_status"] not in {"queued", "running"}:
            return {**state, "state": "done", "status": row["recognition_status"], "outcome": "unclear"}
        candidate = reviewing_candidate(directory / "workflow")
        preview = {"original_text": candidate.get("original_text"), "parts": _parts(candidate),
                   "root": candidate.get("root")} if candidate else None
        return {**state, "state": "running", "preview": preview}

    @router.get("/problems/{search_id}/image")
    def problem_image(search_id: str, request: Request):
        problem_dir(request, search_id)
        with repository(request).storage.read_lock(search_id):
            return image_response(problem_dir(request, search_id) / "question.png", "image/png")

    return router


def _present(result):
    """What the problem page needs, plus the image identity check."""
    status = result["status"]
    findings = [{"kind": f["kind"], "source_excerpt": f["source_excerpt"], "message": f["message"]}
                for f in result.get("review_findings", [])]
    # Uncertainties the model declared while extracting (before any review).
    findings += [{"kind": d["code"], "source_excerpt": "", "message": d.get("message", "")}
                 for d in result.get("confirmation_diagnostics", [])]
    if status == "reviewed_candidate":
        outcome = "ok"
    elif status == "needs_confirmation":
        kinds = [FAILURES.get(f["kind"]) for f in findings]
        outcome = "figure" if "figure" in kinds else "unclear"
    elif status == "code_gap" or (status != "workflow.internal_error" and result.get("unsupported_diagnostics")):
        # A run stopped by budget or oscillation while the last candidate still
        # used unsupported mathematics is unsupported, not a system failure.
        outcome = "unsupported"
    else:
        outcome = "error"
    candidate = result.get("candidate") or {}
    return {
        "status": status,
        "outcome": outcome,
        "original_text": candidate.get("original_text"),
        "parts": _parts(candidate),
        "root": candidate.get("root"),
        "findings": findings,
        "features": [{"feature_id": f["feature_id"], "scope": f["scope"], "status": f["status"]}
                     for f in result.get("features", [])],
        "image_check": {
            "question_sha256": result["question_sha256"],
            "sent_image_sha256": result["sent_image_sha256"],
            "verified": result["sent_image_sha256"] == [result["question_sha256"]],
        },
        "elapsed_seconds": result.get("elapsed_seconds"),
    }


def _message(exc):
    return "search.lesson_failed"


def _parts(candidate):
    labels = [child.get("label") for child in (candidate.get("root") or {}).get("children", [])]
    return [label for label in labels if label]
