"""Native local process lifecycle. PID identities prevent stopping unrelated services."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from kombu import Connection
from sqlalchemy import select, func

from ..application import Application
from ..config import REPO
from ..db import engine, transaction
from ..errors import ProductError
from .. import models as m
from ..runtime_config import RuntimeConfig
from ..transport import deployment, celery_app
from . import native, broker, database


# Frontend keeps its own HMR. These are the services that can be restarted manually.
PYTHON_SERVICES = ('worker', 'publisher', 'api')
QUEUE_SERVICES = ('worker', 'publisher')
# Code changes do not trigger automatic restarts in local development. Keep
# the legacy reloader in the stop list so an old instance is cleaned up once.
ALL_SERVICES = ('reloader', 'frontend', 'api', 'publisher', 'worker')


def signature(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def process_state(runtime):
    path = runtime.settings.root / 'config/processes.json'
    records = json.loads(path.read_text()) if path.exists() else {}
    return {name: {**record, 'running': signature(record['pid']) == record['signature']} for name, record in records.items()}


def _save_records(runtime, records):
    path = runtime.settings.root / 'config/processes.json'
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(records, indent=2))
    path.chmod(0o600)


def heartbeats(runtime, version):
    records, result = process_state(runtime), {}
    for name in ('worker', 'publisher'):
        path = runtime.settings.root / 'locks' / (name + '-heartbeat.json')
        try: data = json.loads(path.read_text())
        except (OSError, ValueError): data = {}
        result[name] = bool(records.get(name, {}).get('running') and data.get('pid') == records[name]['pid']
            and data.get('version') == version and 0 <= time.time() - data.get('at', 0) < 30)
    return result


def verify_dependencies(runtime):
    import shutil
    for tool in ('node', 'npm'):
        if not shutil.which(tool): raise ProductError('runtime.missing_' + tool)
    if not Path(runtime.values['OCR_PYTHON']).is_file(): raise ProductError('runtime.ocr_missing')
    check = subprocess.run([runtime.values['OCR_PYTHON'], '-c',
        'import paddle,paddleocr; from shuxueshuo_server.solver.extraction.paddle_worker import PaddleF2ProviderWorker; PaddleF2ProviderWorker().manifests()'],
        env=runtime.environment(), capture_output=True, timeout=60)
    if check.returncode: raise ProductError('runtime.ocr_import_failed')
    processes = subprocess.check_output(['ps', '-axo', 'command='], text=True)
    if any(line.strip().split(' ')[0].endswith(('python', 'python3', 'python3.11', 'python3.12')) and
           '-m shuxueshuo_server.review.worker' in line for line in processes.splitlines()):
        raise ProductError('runtime.legacy_worker_running')


def doctor(runtime, *, require_processes=True):
    result = database.doctor(runtime.settings)
    verify_dependencies(runtime)
    with Connection(runtime.broker_url, connect_timeout=5) as connection: connection.ensure_connection(max_retries=0)
    a = Application(runtime.settings)
    try:
        version = deployment(a.service)
        client = celery_app(runtime, version)
        with client.connection_for_write() as connection:
            for queue in client.conf.task_queues: queue(connection).declare()
        with transaction(a.db) as c:
            pending = c.scalar(select(func.count()).select_from(m.outbox_messages).where(m.outbox_messages.c.status.in_(['pending', 'publishing'])))
            expired = c.scalar(select(func.count()).select_from(m.jobs).where(m.jobs.c.status == 'running', m.jobs.c.lease_expires_at < func.now()))
        processes = process_state(runtime)
        live = heartbeats(runtime, version)
        ready = (
            all(processes.get(name, {}).get('running') and processes[name]['version'] == version
                for name in ('api', 'worker', 'publisher'))
            and bool(processes.get('frontend', {}).get('running'))
            and all(live.values())
        )
        if require_processes and not ready: raise ProductError('runtime.process_or_heartbeat_not_ready')
        return {**result, 'broker': True, 'deployment_version': version, 'outbox_pending': pending, 'expired_leases': expired,
                'heartbeats': live, 'processes': processes}
    finally: a.close()


def _service_commands(runtime):
    ports = {'api': int(runtime.values['API_PORT']), 'frontend': int(runtime.values['FRONTEND_PORT'])}
    return {
        'worker': [sys.executable, '-m', 'shuxueshuo_server.product.transport', 'worker'],
        'publisher': [sys.executable, '-m', 'shuxueshuo_server.product.transport', 'publisher'],
        'api': [sys.executable, '-m', 'uvicorn', 'shuxueshuo_server.main:app', '--host', '127.0.0.1', '--port', str(ports['api'])],
        'frontend': ['npm', 'run', 'dev', '--', '--hostname', '127.0.0.1', '--port', str(ports['frontend'])],
        'reloader': [sys.executable, '-m', 'shuxueshuo_server.product.admin.reloader'],
    }, ports


def _service_env(runtime):
    env = runtime.environment()
    env['PRODUCT_API_ORIGIN'] = f"http://127.0.0.1:{runtime.values['API_PORT']}"
    env['NEXT_PUBLIC_PRODUCT_WS_ORIGIN'] = f"ws://127.0.0.1:{runtime.values['API_PORT']}"
    return env


def stop_named(runtime, names, *, timeout=30):
    """SIGTERM selected tracked processes and wait until their PID signatures change."""
    records = process_state(runtime)
    for name in names:
        record = records.get(name)
        if not record or not record['running']:
            continue
        try:
            os.killpg(record['pid'], signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.monotonic() + timeout
        while signature(record['pid']) == record['signature']:
            if time.monotonic() >= deadline:
                raise ProductError('runtime.stop_timeout_' + name)
            time.sleep(.2)
    records = process_state(runtime)
    for name in names:
        records.pop(name, None)
    _save_records(runtime, records)
    return records


def spawn_named(runtime, version, names):
    """Start missing tracked processes and record them under ``version``."""
    commands, ports = _service_commands(runtime)
    records = process_state(runtime)
    env = _service_env(runtime)
    for name in names:
        if records.get(name, {}).get('running'):
            continue
        if name in ports:
            with socket.socket() as probe:
                try:
                    probe.bind(('127.0.0.1', ports[name]))
                except OSError as exc:
                    raise ProductError(f'runtime.{name}_port_in_use') from exc
        command = commands[name]
        cwd = REPO / ('frontend' if name == 'frontend' else 'server')
        with (runtime.settings.root / 'logs' / f'{name}.log').open('ab') as log:
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log, start_new_session=True)
        records[name] = {'pid': child.pid, 'signature': signature(child.pid), 'version': version}
        _save_records(runtime, records)
        time.sleep(.5)
        if child.poll() is not None:
            raise ProductError('runtime.' + name + '_exited')
    return records


def wait_python_ready(runtime, version, *, timeout=60, require_heartbeats=False):
    import httpx
    deadline = time.monotonic() + timeout
    api = f"http://127.0.0.1:{runtime.values['API_PORT']}/api/product/v1/health"
    while time.monotonic() < deadline:
        records = process_state(runtime)
        running = all(records.get(name, {}).get('running') and records[name].get('version') == version
                      for name in PYTHON_SERVICES)
        try:
            with httpx.Client(timeout=2) as client:
                healthy = running and client.get(api).status_code == 200
        except httpx.HTTPError:
            healthy = False
        if healthy and (not require_heartbeats or all(heartbeats(runtime, version).values())):
            return True
        time.sleep(.5)
    raise ProductError('runtime.start_timeout')


def restart_python_services(runtime, *, services=PYTHON_SERVICES):
    """Manually bounce selected local services onto the current fingerprint."""
    if (runtime.settings.root / 'locks/services-draining').exists():
        return {'ok': False, 'reason': 'draining'}
    a = Application(runtime.settings)
    try:
        version = deployment(a.service)
    finally:
        a.close()
    records = process_state(runtime)
    if all(records.get(name, {}).get('running') and records[name].get('version') == version for name in services):
        return {'ok': True, 'skipped': True, 'version': version}
    stop_named(runtime, services)
    spawn_named(runtime, version, services)
    if set(services) & set(PYTHON_SERVICES):
        # Only wait on API when it was part of the bounce; queue-only restarts
        # are triggered from inside a live API request.
        if 'api' in services:
            wait_python_ready(runtime, version)
        else:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                records = process_state(runtime)
                if all(records.get(name, {}).get('running') and records[name].get('version') == version for name in services):
                    break
                time.sleep(.2)
            else:
                raise ProductError('runtime.start_timeout')
    # Frontend keeps its own HMR; only refresh the recorded fingerprint so doctor stays green.
    records = process_state(runtime)
    frontend = records.get('frontend')
    if frontend and frontend.get('running'):
        records['frontend'] = {**frontend, 'version': version}
        _save_records(runtime, records)
    return {'ok': True, 'version': version, 'processes': process_state(runtime)}


def start(runtime):
    verify_dependencies(runtime)
    native.start(runtime.settings)
    broker.start(runtime)
    doctor(runtime, require_processes=False)
    records = process_state(runtime)
    a = Application(runtime.settings)
    try: version = deployment(a.service)
    finally: a.close()
    for name, record in records.items():
        if name == 'reloader':
            continue
        if record['running'] and record['version'] != version: raise ProductError('runtime.version_changed_stop_first')
    spawn_named(runtime, version, ('worker', 'publisher', 'api', 'frontend'))
    import httpx
    for _ in range(60):
        try:
            with httpx.Client(timeout=2) as client:
                if all(heartbeats(runtime, version).values()) and client.get(f"http://127.0.0.1:{runtime.values['API_PORT']}/api/product/v1/health").status_code == 200 and client.get(f"http://127.0.0.1:{runtime.values['FRONTEND_PORT']}/review/runs").status_code == 200:
                    (runtime.settings.root / 'locks/services-draining').unlink(missing_ok=True)
                    return {'ok': True, 'url': f"http://127.0.0.1:{runtime.values['FRONTEND_PORT']}/review/runs", 'processes': process_state(runtime)}
        except httpx.HTTPError: pass
        time.sleep(.5)
    raise ProductError('runtime.start_timeout')


def stop(runtime):
    (runtime.settings.root / 'locks/services-draining').touch()
    # Stop the old processes before migrating. Application requires the new schema,
    # while draining only needs the jobs table shared by both versions.
    db = engine(runtime.settings.url())
    try:
        for _ in range(30):
            with transaction(db) as c:
                count = c.scalar(select(func.count()).select_from(m.jobs).where(m.jobs.c.status.in_(['queued', 'running'])))
            if not count: break
            time.sleep(1)
        else: raise ProductError('runtime.drain_timeout_tasks_retained')
    finally: db.dispose()
    stop_named(runtime, ALL_SERVICES)
    broker.stop(runtime)
    return {'ok': True, 'postgres_running': native.status(runtime.settings), 'processes': process_state(runtime)}


def execute(settings, operation):
    if settings.mode == 'server':
        from .server_runtime import execute as execute_server
        return execute_server(settings, operation)
    if settings.mode != 'local':
        raise ProductError('runtime.local_only')
    runtime = RuntimeConfig.load(settings, initialize=operation == 'services-install')
    if operation == 'services-install':
        verify_dependencies(runtime)
        database.migrate(settings)
        broker.configure(runtime)
        return {'ok': True}
    if operation == 'services-start':
        return start(runtime)
    if operation == 'services-stop':
        return stop(runtime)
    if operation == 'services-doctor':
        return doctor(runtime)
    return {
        'processes': process_state(runtime),
        'broker_running': broker.status(runtime),
        'postgres_running': native.status(settings),
    }
