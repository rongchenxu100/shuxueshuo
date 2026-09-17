"""At-least-once transport; all authoritative task state lives in PostgreSQL."""
from .pipelines import CURRENT_PIPELINE_VERSION
from datetime import timedelta
import os
import signal
import subprocess
import sys
import time
from uuid import UUID

from celery import Celery
from celery.signals import heartbeat_sent, worker_ready
from celery.exceptions import Reject
from kombu import Exchange, Queue
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .application import load_application, dependencies
from .config import REPO
from .db import transaction
from . import models as m
from .errors import Conflict, ProductError
from .outbox import reserve, acknowledge
from .repositories import UserContext, row
from .runtime_config import load_runtime
from .services import now
from .runtime_status import pulse


def deployment(service):
    from .application import deployment_version
    return deployment_version()


def queue_for(version): return 'product.build.' + version


def celery_app(runtime, version):
    queue = queue_for(version)
    app = Celery('product', broker=runtime.broker_url)
    app.conf.update(task_serializer='json', accept_content=['json'], result_serializer='json', task_ignore_result=True,
        task_acks_late=True, task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
        broker_transport_options={'confirm_publish': True}, broker_connection_retry_on_startup=True,
        broker_heartbeat=30, task_default_delivery_mode='persistent', task_create_missing_queues=False,
        task_queues=(Queue(queue, Exchange('product', durable=True), routing_key=queue, durable=True,
                          queue_arguments={'x-queue-type': 'classic'}),),
        task_default_queue=queue, task_default_exchange='product', task_default_routing_key=queue,
        worker_pool='threads', worker_concurrency=runtime.worker_concurrency, worker_hijack_root_logger=False,
        worker_enable_remote_control=False)
    @app.task(name='product.execute')
    def execute(message): return supervise(runtime, version, message)
    return app


def context_for(c, build):
    p = row(c, m.problems, id=build['problem_id'])
    return UserContext(build['workspace_id'], p['owner_user_id'])


def supervise(runtime, version, message):
    if not isinstance(message, dict) or set(message) != {'protocol_version', 'job_id', 'build_id'} or message['protocol_version'] != 'product-job/v1':
        raise Reject('product.invalid_message', requeue=False)
    try: job_id, build_id = UUID(message['job_id']), UUID(message['build_id'])
    except (ValueError, TypeError): raise Reject('product.invalid_identity', requeue=False) from None
    a = load_application()
    try:
        with transaction(a.db) as c:
            job = row(c, m.jobs, id=job_id)
            build = row(c, m.builds, id=build_id)
            if not job or not build or job['build_id'] != build_id: raise Reject('product.unknown_job', requeue=False)
            ctx = context_for(c, build)
        try: execution = a.service.acquire_execution(ctx, job_id, f'local:{os.getpid()}', deployment_version=version, lease_seconds=90)
        except Conflict as exc:
            if str(exc) in ('execution.already_owned', 'job.terminal'): return
            if str(exc) == 'execution.capacity':
                raise Reject('execution.capacity', requeue=True) from None
            if str(exc) == 'execution.incompatible_environment':
                a.service.fail_incompatible_deployment(ctx, build_id)
                return
            raise Reject('product.incompatible_worker', requeue=False) from None
        if execution['status'] == 'failed': return
        args = (ctx, build_id, execution['id'], execution['epoch'])
        env = runtime.environment()
        log_path = runtime.settings.root / 'logs' / (str(execution['id']) + '.log')
        with log_path.open('ab') as log:
            child = subprocess.Popen([sys.executable, '-m', 'shuxueshuo_server.product.runner', str(build_id),
                str(execution['id']), str(execution['epoch'])], cwd=REPO / 'server', env=env, stdout=log, stderr=log,
                start_new_session=True)
            started, heartbeat = time.monotonic(), 0
            while child.poll() is None:
                if time.monotonic() - started > 3600:
                    a.service.finish_failure(*args, 'build.timeout')
                    os.killpg(child.pid, signal.SIGTERM)
                    break
                if time.monotonic() - heartbeat >= 10:
                    try: a.service.heartbeat(*args, lease_seconds=90)
                    except Exception:
                        os.killpg(child.pid, signal.SIGTERM)
                        break
                    heartbeat = time.monotonic()
                time.sleep(.5)
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
            if child.returncode:
                try:
                    with transaction(a.db) as c:
                        a.service.finish_failure(*args, 'execution.process_failed', interrupted=True)
                        recovery_message(c, job_id, build_id, ctx.workspace_id, execution['epoch'])
                except Conflict: pass
    finally: a.close()


def recovery_message(c, job_id, build_id, workspace_id, epoch):
    c.execute(pg_insert(m.outbox_messages).values(workspace_id=workspace_id, job_id=job_id,
        message_type='job.execute', protocol_version='product-job/v1',
        payload={'build_id': str(build_id), 'job_id': str(job_id)},
        dedupe_key=f'recover:{job_id}:{epoch}', available_at=now(c)).on_conflict_do_nothing(index_elements=['dedupe_key']))


def recover_expired(a):
    with transaction(a.db) as c:
        expired = c.execute(select(m.jobs).where(m.jobs.c.status == 'running', m.jobs.c.lease_expires_at <= now(c),
            m.jobs.c.cancel_requested_at.is_(None)).order_by(m.jobs.c.lease_expires_at).limit(100).with_for_update(skip_locked=True)).mappings().all()
        for job in expired:
            recovery_message(c, job['id'], job['build_id'], job['workspace_id'], job['execution_epoch'])
        return len(expired)


def fail_stale_deployments(a, current_version):
    """Fail builds frozen to a retired deployment instead of publishing into dead queues."""
    with transaction(a.db) as c:
        builds = c.execute(select(m.builds).where(
            m.builds.c.deployment_version != current_version,
            m.builds.c.id.in_(select(m.jobs.c.build_id).where(m.jobs.c.status.in_(('queued', 'running', 'interrupted')))),
        ).limit(50)).mappings().all()
        targets = [(dict(build), row(c, m.problems, id=build['problem_id'])['owner_user_id']) for build in builds]
    for build, owner_user_id in targets:
        a.service.fail_incompatible_deployment(UserContext(build['workspace_id'], owner_user_id), build['id'])
    return len(targets)


def publish_once(a, client, current_version=None):
    current_version = current_version or deployment(a.service)
    with transaction(a.db) as c: messages = reserve(c, limit=20)
    for message in messages:
        with transaction(a.db) as c:
            build = row(c, m.builds, id=UUID(message['payload']['build_id']))
            owner = row(c, m.problems, id=build['problem_id'])['owner_user_id'] if build else None
        if not build:
            with transaction(a.db) as c:
                try: acknowledge(c, message['id'], message['publisher_token'], confirmed=True, error=None)
                except Conflict: pass
            continue
        if build['deployment_version'] != current_version:
            a.service.fail_incompatible_deployment(UserContext(build['workspace_id'], owner), build['id'])
            with transaction(a.db) as c:
                try: acknowledge(c, message['id'], message['publisher_token'], confirmed=True, error=None)
                except Conflict: pass
            continue
        try:
            queue = queue_for(build['deployment_version'])
            client.send_task('product.execute', args=[{'protocol_version': message['protocol_version'], **message['payload']}],
                task_id=str(message['id']), queue=Queue(queue, Exchange('product', durable=True), routing_key=queue,
                durable=True, queue_arguments={'x-queue-type': 'classic'}), routing_key=queue, retry=False)
            confirmed, error = True, None
        except Exception as exc: confirmed, error = False, type(exc).__name__
        with transaction(a.db) as c:
            try: acknowledge(c, message['id'], message['publisher_token'], confirmed=confirmed, error=error)
            except Conflict: pass
    return len(messages)


def main():
    runtime = load_runtime()
    a = load_application()
    version = deployment(a.service)
    client = celery_app(runtime, version)
    if sys.argv[1] == 'worker':
        def worker_pulse(**_): pulse(runtime, 'worker', version)
        heartbeat_sent.connect(worker_pulse, weak=False)
        worker_ready.connect(worker_pulse, weak=False)
        a.close()
        client.worker_main(['worker', '--pool=threads', f'--concurrency={runtime.worker_concurrency}', '--loglevel=WARNING', '--without-gossip', '--without-mingle', '-n', f'product-{runtime.settings.instance}@%h'])
        return
    stop = False
    def terminate(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    last_recover = 0
    try:
        while not stop:
            try:
                if time.monotonic() - last_recover >= 15:
                    fail_stale_deployments(a, version)
                    recover_expired(a)
                    last_recover = time.monotonic()
                publish_once(a, client, version)
                pulse(runtime, 'publisher', version)
            except Exception as exc: print('publisher:', type(exc).__name__, flush=True)
            time.sleep(.5)
    finally: a.close()


if __name__ == '__main__': main()
