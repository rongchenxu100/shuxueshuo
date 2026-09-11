"""python -m shuxueshuo_server.product.admin.cli --mode local COMMAND"""
import argparse
from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import subprocess
import sys

from sqlalchemy.exc import SQLAlchemyError
import psycopg

from ..config import Settings
from ..db import engine
from ..errors import Conflict, IntegrityFailure, ProductError
from . import database, native


@contextmanager
def instance_lock(root):
    directory = root / 'locks'
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / 'admin.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Conflict('admin.instance_busy') from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def main(argv=None):
    p = argparse.ArgumentParser(description='Product P1 administration (no Review import)')
    p.add_argument('--mode', required=True, choices=['local', 'server'])
    p.add_argument('--data-dir')
    p.add_argument('--instance')
    p.add_argument('--port', type=int)
    p.add_argument('--pg-bin')
    p.add_argument('command', choices=['configure', 'install', 'deploy', 'resume', 'bootstrap', 'migrate', 'seed', 'doctor', 'status', 'db-start', 'db-stop', 'backup', 'restore'])
    p.add_argument('--backup')
    p.add_argument('--target')
    args = p.parse_args(argv)
    try:
        initialize = args.command in ('configure', 'install', 'restore')
        if args.command == 'restore':
            if not args.target or not args.backup or not args.data_dir or args.target == (args.instance or args.mode):
                raise ProductError('restore.requires_new_target_and_data_dir')
            if (Path(args.data_dir) / 'config').exists():
                raise Conflict('restore.target_already_installed')
            args.instance = args.target
        settings = Settings.load(args.mode, args.data_dir, args.instance, args.port, initialize=initialize, pg_bin=args.pg_bin)
        with instance_lock(settings.root):
            result = execute(settings, args)
        print(json.dumps(result or {'ok': True}, ensure_ascii=False, default=str))
        return 0
    except IntegrityFailure as exc:
        print(str(exc), file=sys.stderr)
        return 5
    except (ProductError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 4 if str(exc).startswith('migration.') else 2
    except (SQLAlchemyError, psycopg.Error, subprocess.CalledProcessError) as exc:
        # Drivers/commands may contain secrets in their exception text. Never echo it.
        print(f'operation failed: {type(exc).__name__}; inspect the instance logs', file=sys.stderr)
        return 4 if args.command in ('migrate', 'install') else 3
    except Exception as exc:
        print(f'operation failed: {type(exc).__name__}', file=sys.stderr)
        return 4 if args.command in ('migrate', 'install') else 5


def execute(settings, args):
    operation = args.command
    if operation == 'deploy':
        from .backup import backup, stopped_writes
        with stopped_writes(settings, keep_on_failure=True):
            saved = backup(settings, fenced=True)
            database.migrate(settings)
            result = database.doctor(settings, maintenance=True)
        return {**result, **saved}
    if operation == 'resume':
        result = database.doctor(settings, maintenance=True)
        with psycopg.connect(database.dsn(settings.url('bootstrap')), autocommit=True) as c:
            c.execute('ALTER ROLE product_app LOGIN')
        return result
    if operation == 'configure':
        return {'ok': True, 'data_dir': str(settings.root), 'instance': settings.instance}
    if operation in ('db-start', 'db-stop'):
        if settings.mode != 'local':
            raise ProductError('use_server_compose_for_database_lifecycle')
        return (native.start if operation == 'db-start' else native.stop)(settings)
    if operation == 'status':
        return {'instance': settings.instance, 'data_dir': str(settings.root),
                'running': native.status(settings) if settings.mode == 'local' else database.doctor(settings, probe=False)['ok']}
    if operation in ('install', 'restore'):
        if settings.mode == 'local':
            native.start(settings)
        database.bootstrap(settings)
    if operation == 'bootstrap':
        return database.bootstrap(settings)
    if operation in ('install', 'migrate'):
        database.migrate(settings)
    if operation in ('install', 'seed'):
        db = engine(settings.url('migration'))
        try:
            context = database.seed(db)
        finally:
            db.dispose()
        if operation == 'seed':
            return {'workspace_id': context.workspace_id, 'user_id': context.user_id}
    if operation in ('install', 'doctor'):
        return database.doctor(settings)
    if operation == 'backup':
        from .backup import backup
        return backup(settings)
    if operation == 'restore':
        from .backup import restore_data
        return restore_data(settings, args.backup)


if __name__ == '__main__':
    sys.exit(main())
