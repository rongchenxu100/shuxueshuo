import os
import secrets
from datetime import UTC, datetime
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from shuxueshuo_server.auth.api import install_auth, require_user
from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthService
from shuxueshuo_server.auth.sms import MockSms
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine


@pytest.fixture
def config():
    return AuthConfig(
        mode="mock",
        environment="test",
        origin="https://testserver",
        secret=secrets.token_urlsafe(48),
    )


@pytest.fixture
def auth(config):
    root = os.getenv("PRODUCT_TEST_DATA_DIR")
    if not root:
        pytest.skip("Requires an independently migrated PRODUCT_TEST_DATA_DIR")
    settings = Settings.load(
        "local", root, os.getenv("PRODUCT_TEST_INSTANCE", "auth-stage1")
    )
    db = engine(settings.url())
    now = [datetime.now(UTC)]
    service = AuthService(db, config, MockSms(), clock=lambda: now[0])
    service.test_time = now
    yield service
    db.dispose()


@pytest.fixture
def phone():
    return "139" + "".join(str(secrets.randbelow(10)) for _ in range(8))


@pytest.fixture
def app(auth):
    value = FastAPI()
    install_auth(value, auth=auth)

    @value.get("/protected")
    def protected(user: Annotated[dict, Depends(require_user)]):
        return user

    return value


@pytest.fixture
def client(app):
    with TestClient(
        app, base_url="https://testserver", headers={"Origin": "https://testserver"}
    ) as client:
        yield client
