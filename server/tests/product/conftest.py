import os
from pathlib import Path
from uuid import uuid4
import sys

import pytest

from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine, transaction
from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.repositories import insert, UserContext
from shuxueshuo_server.product.services import ProductService
from shuxueshuo_server.product.storage import LocalArtifactStorage


@pytest.fixture
def settings():
    root = os.environ.get('PRODUCT_TEST_DATA_DIR')
    if not root:
        pytest.skip('Set PRODUCT_TEST_DATA_DIR to an independently installed product test instance')
    instance = os.environ.get('PRODUCT_TEST_INSTANCE', 'p1-test')
    return Settings.load('local', root, instance)


@pytest.fixture
def setup(settings, tmp_path):
    admin = engine(settings.url('migration'))
    db = engine(settings.url())
    with transaction(admin) as c:
        u = insert(c, m.users, key=uuid4().hex, display_name='test')
        w = insert(c, m.workspaces, slug=uuid4().hex, name='test')
        insert(c, m.workspace_members, workspace_id=w['id'], user_id=u['id'], role='owner')
    ctx = UserContext(w['id'], u['id'])
    # Keep registered test artifacts under the dedicated instance for backup verification.
    service = ProductService(db, LocalArtifactStorage(settings.artifact_root))
    yield service, ctx, admin
    db.dispose()
    admin.dispose()


@pytest.fixture
def domain():
    helper_dir = Path(__file__).resolve().parents[1] / 'solver'
    sys.path.insert(0, str(helper_dir))
    try:
        from _problem_planning_support import domain_payload, CASES
        return domain_payload(CASES[0])
    finally:
        sys.path.remove(str(helper_dir))
