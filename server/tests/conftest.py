"""Shared PostgreSQL quota fixture, isolated from the local preview ledger."""
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine


@pytest.fixture
def budget_db():
    root = os.getenv('PRODUCT_TEST_DATA_DIR')
    if not root:
        pytest.skip('Requires an independently migrated PRODUCT_TEST_DATA_DIR')
    settings = Settings.load('local', root, os.getenv('PRODUCT_TEST_INSTANCE', 'auth-stage1'))
    admin = engine(settings.url('migration'))
    schema = 'test_tutor_' + uuid4().hex
    with admin.begin() as c:
        for number in (1, 2):
            c.execute(insert(m.users).values(id=UUID(int=number), key=f'tutor-test-{number}', display_name='quota test').on_conflict_do_nothing())
        c.exec_driver_sql(f'CREATE SCHEMA {schema}')
        c.exec_driver_sql(f'SET LOCAL search_path TO {schema}, public')
        c.execute(text((Path(__file__).parents[1] / 'alembic/versions/0006_tutor_usage.sql').read_text()))
        c.exec_driver_sql(f'GRANT USAGE ON SCHEMA {schema} TO product_app')
        for name, columns in [('tutor_daily_usage', 'calls'), ('tutor_user_daily_usage', 'calls'), ('tutor_session_usage', 'calls, retry_at')]:
            c.exec_driver_sql(f'GRANT SELECT, INSERT ON {schema}.{name} TO product_app')
            c.exec_driver_sql(f'GRANT UPDATE ({columns}) ON {schema}.{name} TO product_app')
    db = create_engine(settings.url(), isolation_level='READ COMMITTED', hide_parameters=True,
                       connect_args={'options': f'-c timezone=UTC -c search_path={schema},public'})
    try:
        yield db
    finally:
        db.dispose()
        with admin.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA {schema} CASCADE')
        admin.dispose()
