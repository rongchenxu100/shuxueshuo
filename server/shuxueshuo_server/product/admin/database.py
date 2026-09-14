from io import BytesIO
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import psycopg
from psycopg import sql
from sqlalchemy import select, text

from .. import models as m
from ..config import REPO
from ..db import engine, transaction, lock
from ..errors import Conflict, IntegrityFailure
from ..repositories import insert, row, UserContext
from ..storage import LocalArtifactStorage

MUTABLE = {
    'batches': 'name updated_at', 'batch_items': 'initial_build_id', 'sources': 'normalized_artifact_id',
    'problems': 'title visibility current_revision_id latest_build_id current_page_build_id lock_version updated_at',
    'problem_sources': 'matched_revision_id', 'builds': 'resolved_revision_id status started_at finished_at error_code',
    'jobs': 'status execution_epoch active_execution_id lease_expires_at cancel_requested_at delivery_count',
    'job_executions': 'status heartbeat_at finished_at failure_code', 'build_stages': 'status accepted_attempt_id summary',
    'stage_attempts': 'status finished_at manifest_json manifest_artifact_id manifest_sha256 checkpoint_artifact_id',
    'artifacts': 'availability', 'event_streams': 'last_seq min_retained_seq',
    'outbox_messages': 'status attempt_count available_at locked_until publisher_token published_at last_error',
}


def dsn(url):
    return url.replace('postgresql+psycopg://', 'postgresql://', 1)


def bootstrap(settings):
    with psycopg.connect(dsn(settings.url('bootstrap', database='postgres')), autocommit=True) as c:
        for role in ('migration', 'app'):
            name = 'product_' + role
            found = c.execute('SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=%s', (name,)).fetchone()
            if found is None:
                c.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
                    sql.Identifier(name), sql.Literal(settings.credentials[role])))
            elif found != (True, False, False, False):
                raise Conflict('database.role_configuration_conflict')
        owner = c.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='product'").fetchone()
        if owner is None:
            c.execute('CREATE DATABASE product OWNER product_migration')
        elif owner[0] != 'product_migration':
            raise Conflict('database.owner_conflict')
    # Verify existing passwords rather than silently resetting them.
    for role in ('migration', 'app'):
        with psycopg.connect(dsn(settings.url(role))) as c:
            c.execute('SELECT 1')


def migrate(settings):
    config = Config(str(REPO / 'server/alembic.ini'))
    scripts = ScriptDirectory.from_config(config)
    if len(scripts.get_heads()) != 1:
        raise Conflict('migration.multiple_heads')
    db = engine(settings.url('migration'))
    try:
        with db.begin() as c:
            c.execute(text("SET LOCAL lock_timeout = '10s'"))
            lock(c, 'product.alembic')
            config.attributes['connection'] = c
            command.upgrade(config, 'head')
            grant(c)
    finally:
        db.dispose()


def grant(c):
    c.exec_driver_sql('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
    c.exec_driver_sql('GRANT USAGE ON SCHEMA public TO product_app')
    c.exec_driver_sql('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM product_app')
    c.exec_driver_sql('GRANT SELECT ON alembic_version TO product_app')
    for table in m.metadata.tables:
        columns = ','.join('"' + x.name + '"' for x in m.metadata.tables[table].c)
        c.exec_driver_sql(f'REVOKE UPDATE ({columns}) ON "{table}" FROM product_app')
        c.exec_driver_sql(f'GRANT SELECT ON "{table}" TO product_app')
        if table not in ('users', 'workspaces', 'workspace_members'):
            c.exec_driver_sql(f'GRANT INSERT ON "{table}" TO product_app')
        if table in MUTABLE:
            columns = ','.join('"' + x + '"' for x in MUTABLE[table].split())
            c.exec_driver_sql(f'GRANT UPDATE ({columns}) ON "{table}" TO product_app')


def seed(db):
    with transaction(db) as c:
        lock(c, 'product.seed')
        user = row(c, m.users, key='internal') or insert(c, m.users, key='internal', display_name='默认用户')
        workspace = row(c, m.workspaces, slug='default') or insert(c, m.workspaces, slug='default', name='默认工作空间')
        membership = row(c, m.workspace_members, workspace_id=workspace['id'], user_id=user['id'])
        if membership and membership['role'] != 'owner':
            raise Conflict('seed.membership_conflict')
        if not membership:
            insert(c, m.workspace_members, workspace_id=workspace['id'], user_id=user['id'], role='owner')
        return UserContext(workspace['id'], user['id'])


def doctor(settings, *, probe=True, maintenance=False):
    db = engine(settings.url('bootstrap' if maintenance else 'app'))
    storage = LocalArtifactStorage(settings.artifact_root)
    try:
        with transaction(db) as c:
            if maintenance:
                # The migration owner is not an app member; bootstrap can SET ROLE for a maintenance probe.
                c.exec_driver_sql('SET LOCAL ROLE product_app')
            version = c.scalar(text('SHOW server_version'))
            if not version.startswith('17.'):
                raise IntegrityFailure('doctor.postgres_version')
            if c.scalar(text("SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname=current_user")):
                raise IntegrityFailure('doctor.app_privileged')
            if c.scalar(text("SELECT has_schema_privilege(current_user,'public','CREATE')")):
                raise IntegrityFailure('doctor.app_ddl')
            for table in m.metadata.tables:
                if c.scalar(text('SELECT has_table_privilege(current_user,:t,\'DELETE\')'), {'t': table}):
                    raise IntegrityFailure('doctor.app_delete')
                allowed = set(MUTABLE.get(table, '').split())
                for column in m.metadata.tables[table].c:
                    if column.name not in allowed and c.scalar(text("SELECT has_column_privilege(current_user,:t,:c,'UPDATE')"), {'t': table, 'c': column.name}):
                        raise IntegrityFailure('doctor.app_frozen_column')
            user, workspace = row(c, m.users, key='internal'), row(c, m.workspaces, slug='default')
            if not user or not workspace or not row(c, m.workspace_members, workspace_id=workspace['id'], user_id=user['id'], role='owner'):
                raise IntegrityFailure('doctor.seed_missing')
            artifacts = c.execute(select(m.artifacts)).mappings().all()
        migration_db = engine(settings.url('migration'))
        try:
            with migration_db.connect() as c:
                revisions = c.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
            head = ScriptDirectory.from_config(Config(str(REPO / 'server/alembic.ini'))).get_current_head()
            if revisions != [head]:
                raise IntegrityFailure('doctor.revision_mismatch')
        finally:
            migration_db.dispose()
        failures = [str(a['id']) for a in artifacts if not storage.verify(a['storage_key'], a['sha256'], a['size_bytes']).ok]
        if failures:
            raise IntegrityFailure('doctor.artifacts_unavailable:' + ','.join(failures))
        if probe:
            # Isolated probe root, removed after successful no-overwrite/hash checks.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='doctor-', dir=settings.root / 'work') as temporary:
                test_storage = LocalArtifactStorage(temporary)
                stored = test_storage.put_immutable('probe', BytesIO(b'product-doctor'))
                test_storage.put_immutable('probe', BytesIO(b'product-doctor'), stored.sha256)
                if not test_storage.verify('probe', stored.sha256, stored.size_bytes).ok:
                    raise IntegrityFailure('doctor.storage')
        return {'ok': True, 'postgres_version': version, 'revision': head, 'artifacts': len(artifacts),
                'data_dir': str(settings.root), 'orphans': storage.orphan_report(a['storage_key'] for a in artifacts)}
    finally:
        db.dispose()
