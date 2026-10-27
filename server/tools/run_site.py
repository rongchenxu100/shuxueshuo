"""Same-origin local site + login + tutor, without starting Studio/workers.

Run from server/: uv run python tools/run_site.py
Uses the persistent local product instance and serves http://127.0.0.1:8779/.
Install/migrate it first (see docs/site-login-local-testing.md).
Student search (/lab/search/) segments pages with the local OCR interpreter;
running stage one on a chosen question also needs RUN_LLM_INTEGRATION=1.
"""

import argparse
import os
import secrets
from contextlib import asynccontextmanager
from types import SimpleNamespace

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.exceptions import HTTPException

from shuxueshuo_server.auth.api import install_auth
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.product.admin import native
from shuxueshuo_server.product.admin.cli import instance_lock
from shuxueshuo_server.product.application import schema_head
from shuxueshuo_server.product.config import REPO, Settings, write_private
from shuxueshuo_server.product.db import engine
from shuxueshuo_server.search.admission import SearchLimits
from shuxueshuo_server.search.application import install_search
from shuxueshuo_server.tutor_demo.api import create_router


class LocalModelBudget:
    """No application call quota in this loopback-only development entry point."""

    def reserve(self, session_id, *, user_id):
        return None

    def failed(self, session_id):
        pass


class SiteStaticFiles(StaticFiles):
    """Mirror the public Nginx cache and namespace redirect policy locally."""

    async def get_response(self, path, scope):
        if path == 'knowledge-next':
            target = '/knowledge/'
        elif path.startswith('knowledge-next/') and not (
            path == 'knowledge-next/assets' or path.startswith('knowledge-next/assets/')
        ):
            target = '/knowledge/' + path.removeprefix('knowledge-next/')
        else:
            target = None
        if target is not None:
            if scope['path'].endswith('/') and not target.endswith('/'):
                target += '/'
            query = scope.get('query_string', b'').decode('latin-1')
            return RedirectResponse(
                target + ('?' + query if query else ''), status_code=301,
                headers={'Cache-Control': 'no-cache'},
            )
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            error.headers = {**(error.headers or {}), 'Cache-Control': 'no-cache'}
            raise
        response.headers['Cache-Control'] = 'no-cache'
        return response


def create_local_app(settings, config):
    if settings.mode != "local" or config.environment != "development":
        raise ValueError("run_site.py requires local development configuration")

    @asynccontextmanager
    async def lifespan(app):
        db = engine(settings.url())
        try:
            with db.connect() as connection:
                if (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    != schema_head()
                ):
                    raise RuntimeError(
                        "Migrate the local database before starting the login site"
                    )
            app.state.product = SimpleNamespace(db=db, settings=settings)
            yield
        finally:
            db.dispose()

    app = FastAPI(lifespan=lifespan)
    install_auth(app, config=config)
    app.include_router(create_router(budget=LocalModelBudget(), enable_explanation=True))
    # Same loopback-only policy as LocalModelBudget: no daily search LLM quotas.
    install_search(app, settings=settings, admission_config=SearchLimits.local_development())
    app.mount("/", SiteStaticFiles(directory=REPO / "site", html=True), name="site")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", help="Defaults to the persistent local product data directory"
    )
    parser.add_argument("--instance", default="local")
    parser.add_argument("--port", type=int, default=8779, help="Website port (default: 8779)")
    parser.add_argument("--sms", choices=["mock", "aliyun_sms"], default="mock")
    args = parser.parse_args()
    settings = Settings.load("local", args.data_dir, args.instance)
    if not (settings.pgdata / "PG_VERSION").is_file():
        raise RuntimeError(
            "Install the local database first; see docs/site-login-local-testing.md"
        )
    with instance_lock(settings.root):
        native.start(settings)
    load_dotenv(REPO / "server/.env")
    # Private per-instance secret survives restarts. Never print it.
    private = settings.root / "config/student-auth.env"
    if not private.exists():
        write_private(private, {"AUTH_SECRET": secrets.token_urlsafe(48)})
    if private.stat().st_mode & 0o077:
        raise RuntimeError("student-auth.env must have private permissions")
    load_dotenv(private, override=True)
    os.environ.update(
        PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED="1",
        AUTH_SMS_MODE=args.sms,
        AUTH_ENVIRONMENT="development",
        AUTH_ORIGIN=f"http://127.0.0.1:{args.port}",
        AUTH_COOKIE_SECURE="0",
        AUTH_MOCK_DIRECTORY=str(settings.root / "work/mock-sms"),
    )
    config = AuthConfig.from_env()
    print(f"Local site: http://127.0.0.1:{args.port}/", flush=True)
    print(
        f"Database: 127.0.0.1:{settings.port}/product; instance: {settings.instance}",
        flush=True,
    )
    print(f"Persistent data: {settings.root}", flush=True)
    if args.sms == "mock":
        print(f"Mock SMS files: {config.mock_directory} (local only, do not share)")
    uvicorn.run(
        create_local_app(settings, config),
        host="127.0.0.1",
        port=args.port,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
