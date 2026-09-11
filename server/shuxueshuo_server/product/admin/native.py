import os
from pathlib import Path
import socket
import subprocess
import tempfile

from ..errors import Conflict, ProductError


def run(settings, tool, *args, check=True):
    return subprocess.run([str(settings.pg_bin / tool), *map(str, args)], check=check, capture_output=True, text=True)


def init(settings):
    settings.check_native()
    if os.geteuid() == 0:
        raise ProductError('postgres.must_run_as_nonroot')
    if settings.pgdata.exists():
        version = settings.pgdata / 'PG_VERSION'
        if not version.exists() or version.read_text().strip() != '17':
            raise Conflict('postgres.incomplete_or_incompatible_pgdata')
        return
    with tempfile.NamedTemporaryFile(mode='w', dir=settings.root / 'config') as password:
        password.write(settings.credentials['bootstrap'])
        password.flush()
        run(settings, 'initdb', '-D', settings.pgdata, '-U', 'product_bootstrap', '--encoding=UTF8',
            '--locale=C', '--auth-local=scram-sha-256', '--auth-host=scram-sha-256', '--pwfile', password.name)
    with (settings.pgdata / 'postgresql.conf').open('a') as config:
        config.write(f"\nlisten_addresses = '127.0.0.1'\nport = {settings.port}\nunix_socket_directories = ''\ntimezone = 'UTC'\n")


def status(settings):
    settings.check_native()
    return run(settings, 'pg_ctl', '-D', settings.pgdata, 'status', check=False).returncode == 0


def start(settings):
    init(settings)
    if status(settings):
        return
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', settings.port))
        except OSError:
            raise Conflict('postgres.port_in_use') from None
    run(settings, 'pg_ctl', '-D', settings.pgdata, '-l', settings.root / 'logs/postgres.log', '-w', '-t', '30', 'start')


def stop(settings):
    if status(settings):
        run(settings, 'pg_ctl', '-D', settings.pgdata, '-w', '-t', '30', '-m', 'fast', 'stop')
