"""Authenticated teaching API. Local login: uv run python tools/run_site.py --help."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from ..auth.api import install_auth, require_origin, require_user, service
from ..auth.config import AuthConfig
from ..auth.service import AuthService
from ..learning import practice
from .limits import BudgetedTutor, BudgetUnavailable, CallBudget, DialogueLimited
from .llm import DeepSeekTutor, TutorUnavailable
from .session import Conflict, Event, InvalidAction, Sessions


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_id: str = "basic-inequality-q01"
    practice_attempt_id: UUID | None = None
    content_version: str | None = Field(default=None, min_length=1, max_length=100)
    practice_version: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def bound_practice_requires_version(self):
        if self.practice_attempt_id is not None and self.content_version is None and self.practice_version is None:
            raise ValueError('关联练习时必须提供内容版本。')
        return self


def require_tutor_user(
    request: Request,
    user: Annotated[dict, Depends(require_user)],
    auth: Annotated[AuthService, Depends(service)],
):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request, auth)
    return user


TutorUser = Annotated[dict, Depends(require_tutor_user)]


def create_router(tutor=None, budget=None, *, explanation_interpreter=None, enable_explanation=False):
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
    async def start(body: Start, user: TutorUser, request: Request):
        try:
            session = sessions.prepare(body.lesson_id, owner_user_id=user['id'])
            if body.practice_attempt_id:
                await run_in_threadpool(
                    practice.restore_session,
                    service(request).db,
                    UUID(user['id']),
                    body.practice_attempt_id,
                    session,
                    body.content_version,
                    body.practice_version,
                )
            view = session.view()
            if body.practice_attempt_id:
                view.update(content_version=session.learning_content_version,
                            confirmed_choices=session.learning_confirmed_choices)
            sessions.register(session)
            return view
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
            bound_attempt = getattr(session, 'learning_practice_attempt_id', None)
            if bound_attempt is not None and body.kind != 'ui' and body.practice_attempt_id != bound_attempt:
                raise HTTPException(409, '导师会话与练习编号不一致，请重新打开导师。')
            if body.kind != "ui" and session.lock.locked():
                raise DialogueLimited("session_busy", "老师正在回复，请稍后再试。", 2)
            # Reuse the site's authenticated database pool; no second database URL.
            ledger = budget if budget is not None else CallBudget(service(request).db)
            budgeted = BudgetedTutor(tutor, ledger, session_id, user_id=user['id'])
            responder = budgeted
            if body.practice_attempt_id is not None:
                if body.kind == "ui" or not body.practice_step_id:
                    raise InvalidAction("学习记录需要明确的对话步骤。")
                route = await run_in_threadpool(
                    practice.begin_dialogue,
                    service(request).db,
                    UUID(user['id']),
                    body.practice_attempt_id,
                    body,
                    body.practice_step_id,
                    session.lesson["id"],
                )

                class BoundTutor:
                    async def respond(self, **kwargs):
                        context = kwargs["context"]
                        actual = context["node"]
                        if context["state"]["method"] != route or (
                            actual and actual["id"] != body.practice_step_id
                        ):
                            raise InvalidAction(
                                "对话内容与记录步骤不一致，请刷新后继续。"
                            )
                        return await budgeted.respond(**kwargs)

                responder = BoundTutor()
            result = await session.handle(body, responder)
            if body.practice_attempt_id is not None:
                delivery = await run_in_threadpool(
                    practice.finish_dialogue,
                    service(request).db,
                    UUID(user['id']),
                    body.practice_attempt_id,
                    body,
                    body.practice_step_id,
                    result,
                )
                result = dict(
                    result,
                    learning_delivery={
                        "attempt_id": str(body.practice_attempt_id),
                        "event_id": delivery,
                    },
                )
            # A header keeps idempotent replays byte-identical to the original body.
            if isinstance(budgeted.remaining, int):
                response.headers["X-Tutor-Calls-Remaining"] = str(budgeted.remaining)
            return {key: value for key, value in result.items() if key != "learning_intent"}
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

    if enable_explanation:
        from .explanation.api import create_explanation_router

        router.include_router(create_explanation_router(require_tutor_user, explanation_interpreter, budget))
    return router


def create_app(tutor=None, budget=None, *, auth=None, explanation_interpreter=None, enable_explanation=False):
    """Standalone entry fails closed without auth; use tools/run_site.py for login."""
    app = FastAPI(title="数学说 Q01 tutor demo")
    install_auth(app, auth=auth, config=auth.config if auth else AuthConfig())
    app.include_router(create_router(tutor, budget, explanation_interpreter=explanation_interpreter,
                                    enable_explanation=enable_explanation))
    site = Path(__file__).resolve().parents[3] / "site"
    for url, relative, name in (
        ("/1", "1", "basic-inequality"),
        ("/2", "2", "quadratic-always"),
        ("/topics", "topics", "topics"),
        ("/nav", "nav", "junior-library"),
        ("/knowledge", "knowledge", "knowledge"),
        ("/assets/css", "assets/css", "site-css"),
        ("/assets/practice", "assets/practice", "practice-assets"),
        ("/assets/student-explanation", "assets/student-explanation", "student-explanation-assets"),
        ("/assets/auth", "assets/auth", "auth-assets"),
        ("/assets/learning", "assets/learning", "learning-assets"),
        ("/demo", "demo", "legacy-demo"),
    ):
        directory = site / relative
        if directory.is_dir():
            app.mount(url, StaticFiles(directory=directory, html=True), name=name)
    return app


app = create_app()
