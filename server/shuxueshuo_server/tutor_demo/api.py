"""Authenticated teaching API. Local login: uv run python tools/run_site.py --help."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from ..auth.api import install_auth, require_origin, require_user, service
from ..auth.config import AuthConfig
from ..auth.service import AuthService
from .limits import BudgetedTutor, BudgetUnavailable, CallBudget, DialogueLimited
from .llm import DeepSeekTutor, TutorUnavailable
from .session import Conflict, Event, InvalidAction, Sessions


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_id: str = "q01"


def require_tutor_user(
    request: Request,
    user: Annotated[dict, Depends(require_user)],
    auth: Annotated[AuthService, Depends(service)],
):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request, auth)
    return user


TutorUser = Annotated[dict, Depends(require_tutor_user)]


def create_router(tutor=None, budget=None):
    """Share the same API and cleanup lifecycle with the production app."""
    tutor = tutor or DeepSeekTutor()
    sessions = Sessions()

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if hasattr(tutor, "close"):
                await tutor.close()

    router = APIRouter(prefix="/api/tutor-demo", lifespan=lifespan,
                       dependencies=[Depends(require_tutor_user)])

    @router.post("/sessions", status_code=201)
    async def start(body: Start, user: TutorUser):
        try:
            return sessions.create(body.lesson_id, owner_user_id=user['id']).view()
        except KeyError:
            raise HTTPException(404, "没有找到这道题。") from None
        except InvalidAction as exc:
            raise HTTPException(429, str(exc)) from None

    @router.get("/sessions/{session_id}")
    async def read(session_id: str, user: TutorUser):
        try:
            return sessions.get(session_id, owner_user_id=user['id']).view()
        except KeyError:
            raise HTTPException(404, "会话已过期，请重新体验。") from None

    @router.post("/sessions/{session_id}/events")
    async def event(session_id: str, body: Event, user: TutorUser, request: Request, response: Response):
        try:
            session = sessions.get(session_id, owner_user_id=user['id'])
            if body.kind != "ui" and session.lock.locked():
                raise DialogueLimited("session_busy", "老师正在回复，请稍后再试。", 2)
            # Reuse the site's authenticated database pool; no second database URL.
            ledger = budget if budget is not None else CallBudget(service(request).db)
            budgeted = BudgetedTutor(tutor, ledger, session_id, user_id=user['id'])
            result = await session.handle(body, budgeted)
            # A header keeps idempotent replays byte-identical to the original body.
            if isinstance(budgeted.remaining, int):
                response.headers["X-Tutor-Calls-Remaining"] = str(budgeted.remaining)
            return result
        except DialogueLimited as exc:
            return JSONResponse(status_code=429, content={
                "detail": str(exc), "code": exc.code, "retry_after": exc.retry_after,
            }, headers={"Retry-After": str(exc.retry_after)} if exc.retry_after else {})
        except BudgetUnavailable:
            raise HTTPException(503, "老师交流暂不可用，可以继续点选练习。") from None
        except KeyError:
            raise HTTPException(404, "会话已过期，请重新体验。") from None
        except Conflict as exc:
            return JSONResponse(
                status_code=409,
                content={"detail": str(exc), "snapshot": session.view()},
            )
        except InvalidAction as exc:
            raise HTTPException(422, str(exc)) from None
        except TutorUnavailable:
            raise HTTPException(503, "老师暂时未能回复，请保留输入并重试。") from None

    return router


def create_app(tutor=None, budget=None, *, auth=None):
    """Standalone entry fails closed without auth; use tools/run_site.py for login."""
    app = FastAPI(title="数学说 Q01 tutor demo")
    install_auth(app, auth=auth, config=auth.config if auth else AuthConfig())
    app.include_router(create_router(tutor, budget))
    site = Path(__file__).resolve().parents[3] / "site"
    for url, relative, name in (
        ("/1", "1", "basic-inequality"),
        ("/2", "2", "quadratic-always"),
        ("/topics", "topics", "topics"),
        ("/assets/practice", "assets/practice", "practice-assets"),
        ("/assets/auth", "assets/auth", "auth-assets"),
        ("/demo", "demo", "legacy-demo"),
    ):
        directory = site / relative
        if directory.is_dir():
            app.mount(url, StaticFiles(directory=directory, html=True), name=name)
    return app


app = create_app()
