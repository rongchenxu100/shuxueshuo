"""Run locally: uv run uvicorn shuxueshuo_server.tutor_demo.api:app --port 8766."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from .llm import DeepSeekTutor, TutorUnavailable
from .session import Conflict, Event, InvalidAction, Sessions


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_id: str = "q01"


def create_router(tutor=None):
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

    router = APIRouter(prefix="/api/tutor-demo", lifespan=lifespan)

    @router.post("/sessions", status_code=201)
    async def start(body: Start):
        try:
            return sessions.create(body.lesson_id).view()
        except KeyError:
            raise HTTPException(404, "没有找到这道题。") from None
        except InvalidAction as exc:
            raise HTTPException(429, str(exc)) from None

    @router.get("/sessions/{session_id}")
    async def read(session_id: str):
        try:
            return sessions.get(session_id).view()
        except KeyError:
            raise HTTPException(404, "会话已过期，请重新体验。") from None

    @router.post("/sessions/{session_id}/events")
    async def event(session_id: str, body: Event):
        try:
            session = sessions.get(session_id)
            return await session.handle(body, tutor)
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


def create_app(tutor=None):
    """Standalone local development entry point; production uses create_router."""
    app = FastAPI(title="数学说 Q01 tutor demo")
    app.include_router(create_router(tutor))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    demo = Path(__file__).resolve().parents[3] / "site/demo"
    if demo.is_dir():
        app.mount("/demo", StaticFiles(directory=demo), name="demo")
    return app


app = create_app()
