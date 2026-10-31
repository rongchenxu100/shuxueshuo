from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from shuxueshuo_server.product.config import Settings, default_root
from shuxueshuo_server.product.db import engine
from tools.solver_test_profiles import marker_for_test_file


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        marker_name = marker_for_test_file(Path(str(item.path)).name)
        if marker_name is not None:
            item.add_marker(getattr(pytest.mark, marker_name))


@pytest.fixture(scope="module", autouse=True)
def stage_three_storage(request, tmp_path_factory):
    name = Path(str(request.fspath)).name
    # Only selected tests opt mixed unit/integration modules into PostgreSQL.
    # Keep module scope so recorded module fixtures also use the isolated store.
    marked = any(item.path == request.node.path and item.get_closest_marker("stage_three_db")
                 for item in request.session.items)
    if not (name.startswith("test_graph_stage_three")
            or name == "test_interaction_scheduler_failures_store.py" or marked):
        yield None
        return
    root = os.environ.get("PRODUCT_TEST_DATA_DIR")
    instance = os.environ.get("PRODUCT_TEST_INSTANCE")
    if not root or not instance:
        pytest.fail("Stage-three tests require an independently migrated PRODUCT_TEST_DATA_DIR and PRODUCT_TEST_INSTANCE", pytrace=False)
    if Path(root).expanduser().resolve() == default_root("local").resolve() or os.environ.get("PRODUCT_IN_CONTAINER") == "1":
        pytest.fail("Stage-three tests must not use the daily or container database", pytrace=False)
    from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context

    settings = Settings.load("local", root, instance)
    admin = engine(settings.url("migration"))
    schema = "test_stage_three_" + uuid4().hex
    migrations = Path(__file__).parents[2] / "alembic/versions"
    with admin.begin() as connection:
        assert connection.scalar(text("SELECT to_regclass('public.lesson_runs')")), "Apply the PostgreSQL executor migration to the isolated test instance first"
        connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
        connection.exec_driver_sql(f"SET LOCAL search_path TO {schema}, public")
        for name in ('0013_student_search.sql', '0014_lesson_execution.sql', '0015_search_recovery.sql', '0016_search_admission.sql'):
            connection.exec_driver_sql((migrations / name).read_text())
        connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA {schema} TO product_app")
        connection.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {schema} TO product_app")
        connection.exec_driver_sql(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO product_app")
    database = create_engine(settings.url(), isolation_level="READ COMMITTED", pool_pre_ping=True,
                             hide_parameters=True, connect_args={"options": f"-c timezone=UTC -c search_path={schema},public"})
    from shuxueshuo_server.search.repository import SearchRepository
    SearchRepository(database, tmp_path_factory.mktemp('stage-three-private') / 'private-v1')
    try:
        with pytest.MonkeyPatch.context() as environment:
            environment.setenv("PRODUCT_TEST_SCHEMA", schema)
            with storage_context(database):
                yield database
    finally:
        database.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA {schema} CASCADE")
        admin.dispose()


@pytest.fixture(autouse=True)
def stage_three_run_cleanup(stage_three_storage):
    if stage_three_storage is None:
        yield
        return
    with stage_three_storage.connect() as connection:
        retained = set(connection.execute(text("SELECT run_id FROM lesson_runs")).scalars())
    try:
        yield
    finally:
        with stage_three_storage.begin() as connection:
            created = set(connection.execute(text("SELECT run_id FROM lesson_runs")).scalars()) - retained
            if created:
                connection.execute(text("DELETE FROM lesson_runs WHERE run_id = ANY(:run_ids)"), {"run_ids": list(created)})
