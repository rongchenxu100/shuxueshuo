"""Shared site auth routes; require_user is reusable by subsequent feature routers."""

import ipaddress
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from .config import AuthConfig
from .service import AuthError, AuthService
from .sms import AliyunSms, MockSms


def cookie_name(config):
    return "__Host-sss_session" if config.secure else "sss_dev_session"


def service(request: Request):
    value = getattr(request.app.state, "student_auth", None)
    if value is None:
        raise HTTPException(503, "登录服务暂未开放。")
    return value


def require_user(request: Request, auth: Annotated[AuthService, Depends(service)]):
    user = auth.current_user(request.cookies.get(cookie_name(auth.config)))
    if user is None:
        raise HTTPException(401, "请先登录。")
    return user


def require_origin(request: Request, auth: Annotated[AuthService, Depends(service)]):
    if request.headers.get("origin") != auth.config.origin:
        raise HTTPException(403, "请求来源不受支持，请从网站页面重试。")
    return auth


def client_ip(request):
    # Uvicorn resolves forwarding headers only from configured trusted proxies.
    # Do not parse user-supplied X-Forwarded-For in the application.
    return request.client.host if request.client else "unknown"


class SendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(pattern=r"^1[3-9][0-9]{9}$", max_length=11)


class VerifyBody(SendBody):
    challenge_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$", max_length=6)


class AuthBoundary(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth_path = request.url.path.startswith("/api/auth/")
        tutor_path = request.url.path.startswith("/api/tutor-demo/")
        learning_path = request.url.path.startswith("/api/learning/")
        if not (auth_path or tutor_path or learning_path):
            return await call_next(request)
        auth = getattr(request.app.state, "student_auth", None)
        if auth and auth.config.mode == "mock":
            try:
                local = ipaddress.ip_address(client_ip(request)).is_loopback
            except ValueError:
                local = (
                    auth.config.environment == "test"
                    and client_ip(request) == "testclient"
                )
            if not local:
                return JSONResponse(
                    {"detail": "测试登录仅限本机。"},
                    403,
                    headers={"Cache-Control": "no-store"},
                )
        length = request.headers.get("content-length", "0")
        max_bytes = 512 * 1024 if tutor_path else 4096
        if not length.isdigit() or int(length) > max_bytes:
            return JSONResponse(
                {"detail": "请求过大。"}, 413, headers={"Cache-Control": "no-store"}
            )
        # Also bound chunked input before Pydantic reads it; never echo OTP inputs.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > max_bytes:
                return JSONResponse(
                    {"detail": "请求过大。"}, 413, headers={"Cache-Control": "no-store"}
                )
        request._body = bytes(body)
        try:
            response = await call_next(request)
        except AuthError as exc:
            response = JSONResponse(
                {"code": exc.code, "detail": exc.message},
                exc.status,
                headers={"Retry-After": str(exc.retry_after)}
                if exc.retry_after
                else {},
            )
        except (SQLAlchemyError, OSError):
            response = JSONResponse({"detail": "登录服务暂不可用，请稍后重试。"}, 503)
        response.headers["Cache-Control"] = "no-store"
        return response


def install_auth(app, *, auth=None, config=None):
    config = config or (auth.config if auth else AuthConfig.from_env())
    previous_validation = app.exception_handlers.get(RequestValidationError)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc):
        if request.url.path.startswith("/api/auth/"):
            return JSONResponse({"detail": "请检查手机号和六位验证码。"}, 422)
        if previous_validation:
            return await previous_validation(request, exc)
        raise exc

    @asynccontextmanager
    async def lifespan(app):
        if auth is not None:
            app.state.student_auth = auth
        elif config.mode != "disabled":
            product = getattr(app.state, "product", None)
            if product is None:
                raise RuntimeError("Enabled auth requires a migrated product database")
            sms = (
                MockSms(config.mock_directory)
                if config.mode == "mock"
                else AliyunSms(config)
            )
            if config.mode == "mock" and config.mock_directory is None:
                raise RuntimeError("Local mock SMS requires AUTH_MOCK_DIRECTORY")
            app.state.student_auth = AuthService(product.db, config, sms)
        else:
            app.state.student_auth = None
        yield

    router = APIRouter(prefix="/api/auth", lifespan=lifespan)

    @router.get("/me")
    def me(request: Request):
        current = getattr(request.app.state, "student_auth", None)
        return {
            "enabled": current is not None,
            "user": current.current_user(
                request.cookies.get(cookie_name(current.config))
            )
            if current
            else None,
        }

    @router.post("/sms/send")
    def send(
        body: SendBody,
        request: Request,
        auth: Annotated[AuthService, Depends(require_origin)],
    ):
        return auth.send(body.phone, client_ip(request))

    @router.post("/sms/verify")
    def verify(
        body: VerifyBody,
        request: Request,
        response: Response,
        auth: Annotated[AuthService, Depends(require_origin)],
    ):
        name = cookie_name(auth.config)
        user, token = auth.verify(
            body.phone,
            body.challenge_id,
            body.code,
            client_ip(request),
            request.cookies.get(name),
        )
        response.set_cookie(
            name,
            token,
            max_age=auth.config.session_seconds,
            httponly=True,
            secure=auth.config.secure,
            samesite="lax",
            path="/",
        )
        return {"user": user}

    @router.post("/logout", status_code=204)
    async def logout(
        request: Request, auth: Annotated[AuthService, Depends(require_origin)]
    ):
        name = cookie_name(auth.config)
        await run_in_threadpool(auth.logout, request.cookies.get(name))
        response = Response(status_code=204)
        response.delete_cookie(
            name, path="/", secure=auth.config.secure, httponly=True, samesite="lax"
        )
        return response

    from ..learning.api import router as learning_router

    app.include_router(learning_router)
    app.include_router(router)
    app.add_middleware(AuthBoundary)
