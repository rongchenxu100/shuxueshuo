"""Portable logical backups. Original instance and artifact keys remain untouched."""
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from io import BytesIO
import json
import os
import shutil
import subprocess
from uuid import uuid4

import psycopg
from sqlalchemy import select

from .. import models as m
from ..db import engine, transaction
from ..errors import Conflict, IntegrityFailure
from ..storage import LocalArtifactStorage, parts
from .database import dsn, doctor, grant


@contextmanager
def stopped_writes(settings, *, keep_on_failure=False):
    """P1 owns one app role. Fence new logins; reject live app sessions, never kill them."""
    with psycopg.connect(dsn(settings.url('bootstrap')), autocommit=True) as c:
        c.execute('SELECT pg_advisory_lock(1783392101)')
        enabled = c.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='product_app'").fetchone()[0]
        if not enabled:
            raise Conflict('backup.app_already_in_maintenance')
        c.execute('ALTER ROLE product_app NOLOGIN')
        succeeded = False
        try:
            if c.execute("SELECT count(*) FROM pg_stat_activity WHERE usename='product_app'").fetchone()[0]:
                raise Conflict('backup.stop_application_connections_first')
            yield
            succeeded = True
        finally:
            if succeeded or not keep_on_failure:
                c.execute('ALTER ROLE product_app LOGIN')
            c.execute('SELECT pg_advisory_unlock(1783392101)')


def pg_tool(settings, tool, *args):
    from sqlalchemy.engine import make_url
    url = make_url(settings.url('migration'))
    env = {**os.environ, 'PGHOST': url.host, 'PGPORT': str(url.port), 'PGUSER': url.username,
           'PGPASSWORD': url.password, 'PGDATABASE': url.database}
    subprocess.run([str(settings.pg_bin / tool), *map(str, args)], env=env, check=True, capture_output=True)


def backup(settings, *, fenced=False):
    identity = uuid4().hex
    temp = settings.root / 'backups' / (identity + '.incomplete')
    temp.mkdir(mode=0o700)
    storage = LocalArtifactStorage(settings.artifact_root)
    target = LocalArtifactStorage(temp / 'artifacts')
    with nullcontext() if fenced else stopped_writes(settings):
        db = engine(settings.url('migration'))
        try:
            with transaction(db) as c:
                rows = c.execute(select(m.artifacts)).mappings().all()
                counts = {name: c.scalar(select(__import__('sqlalchemy').func.count()).select_from(t)) for name, t in m.metadata.tables.items()}
                revision = c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one()
            pg_tool(settings, 'pg_dump', '--format=custom', '--no-owner', '--no-acl', '--file', temp / 'database.dump')
            artifacts = []
            for row in rows:
                with storage.open(row['storage_key']) as stream:
                    saved = target.put_immutable(row['storage_key'], stream, row['sha256'])
                if saved.size_bytes != row['size_bytes']:
                    raise IntegrityFailure('backup.artifact_size')
                artifacts.append(asdict(saved))
            dump_hash = sha256((temp / 'database.dump').read_bytes()).hexdigest()
            manifest = dict(schema_version='product-backup/v1', revision=revision, counts=counts,
                application_version=os.environ.get('PRODUCT_RELEASE_ID', 'development'),
                database_sha256=dump_hash, artifacts=artifacts, complete=True)
            (temp / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            for name in ('database.dump', 'manifest.json'):
                with (temp / name).open('rb') as f:
                    os.fsync(f.fileno())
            os.rename(temp, temp.with_suffix(''))
            return {'backup': str(temp.with_suffix('')), 'artifacts': len(artifacts)}
        finally:
            db.dispose()


def restore_data(settings, source):
    source = Path(source).resolve()
    manifest = json.loads((source / 'manifest.json').read_text())
    if manifest.get('schema_version') != 'product-backup/v1' or not manifest.get('complete'):
        raise IntegrityFailure('restore.incomplete_backup')
    if sha256((source / 'database.dump').read_bytes()).hexdigest() != manifest['database_sha256']:
        raise IntegrityFailure('restore.dump_hash')
    db = engine(settings.url('migration'))
    try:
        with db.connect() as c:
            if c.exec_driver_sql("SELECT count(*) FROM pg_tables WHERE schemaname='public'").scalar():
                raise Conflict('restore.target_database_not_empty')
        storage = LocalArtifactStorage(settings.artifact_root)
        if storage.orphan_report([]):
            raise Conflict('restore.target_artifacts_not_empty')
        original = LocalArtifactStorage(source / 'artifacts')
        for artifact in manifest['artifacts']:
            parts(artifact['storage_key'])
            if not original.verify(artifact['storage_key'], artifact['sha256'], artifact['size_bytes']).ok:
                raise IntegrityFailure('restore.artifact_hash')
        pg_tool(settings, 'pg_restore', '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                '--dbname', 'product', source / 'database.dump')
        for artifact in manifest['artifacts']:
            with original.open(artifact['storage_key']) as stream:
                storage.put_immutable(artifact['storage_key'], stream, artifact['sha256'])
        with transaction(db) as c:
            grant(c)
            for name, expected in manifest['counts'].items():
                actual = c.scalar(select(__import__('sqlalchemy').func.count()).select_from(m.metadata.tables[name]))
                if actual != expected:
                    raise IntegrityFailure('restore.row_count')
            if c.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() != manifest['revision']:
                raise IntegrityFailure('restore.revision')
        return doctor(settings)
    finally:
        db.dispose()
