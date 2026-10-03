"""Same-origin local site + login + tutor, without starting Studio/workers.

Run from server/: uv run python tools/run_site.py --data-dir /private/tmp/sss-auth-stage1 --instance auth-stage1
Install/migrate the independent product instance first (see docs/site-login-local-testing.md).
"""

import argparse
import os
import secrets
from contextlib import asynccontextmanager
from types import SimpleNamespace

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from shuxueshuo_server.auth.api import install_auth
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.product.config import REPO, Settings, write_private
from shuxueshuo_server.product.db import engine
from shuxueshuo_server.tutor_demo.api import create_router


def create_local_app(settings, config):
    @asynccontextmanager
    async def lifespan(app):
        db = engine(settings.url())
        try:
            with db.connect() as connection:
                if (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    != "0005_student_auth"
                ):
                    raise RuntimeError(
                        "Migrate the local database before starting the login site"
                    )
            app.state.product = SimpleNamespace(db=db)
            yield
        finally:
            db.dispose()

    app = FastAPI(lifespan=lifespan)
    install_auth(app, config=config)
    app.include_router(create_router())
    app.mount("/", StaticFiles(directory=REPO / "site", html=True), name="site")
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--instance", default="auth-stage1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--sms", choices=["mock", "aliyun_sms"], default="mock")
    args = parser.parse_args()
    settings = Settings.load("local", args.data_dir, args.instance)
    load_dotenv(REPO / "server/.env")
    # Private per-instance secret survives restarts. Never print it.
    private = settings.root / "config/student-auth.env"
    if not private.exists():
        write_private(private, {"AUTH_SECRET": secrets.token_urlsafe(48)})
    if private.stat().st_mode & 0o077:
        raise RuntimeError("student-auth.env must have private permissions")
    load_dotenv(private, override=True)
    os.environ.update(
        AUTH_SMS_MODE=args.sms,
        AUTH_ENVIRONMENT="development",
        AUTH_ORIGIN=f"http://127.0.0.1:{args.port}",
        AUTH_COOKIE_SECURE="0",
        AUTH_MOCK_DIRECTORY=str(settings.root / "work/mock-sms"),
    )
    config = AuthConfig.from_env()
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
