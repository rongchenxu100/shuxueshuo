from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from shuxueshuo_server.product import transport, models as m
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import Conflict


def test_worker_cli_and_celery_use_the_same_configured_limit(monkeypatch):
    runtime = SimpleNamespace(worker_concurrency=2, broker_url='memory://', settings=SimpleNamespace(instance='test'))
    app = transport.celery_app(runtime, 'test')
    assert app.conf.worker_concurrency == 2
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
    captured = []
    monkeypatch.setattr(app, 'worker_main', lambda args: captured.append(args))
    monkeypatch.setattr(transport, 'celery_app', lambda *_: app)
    monkeypatch.setattr(transport, 'load_runtime', lambda: runtime)
    monkeypatch.setattr(transport, 'load_application', lambda: SimpleNamespace(service=None, close=lambda: None))
    monkeypatch.setattr(transport, 'deployment', lambda *_: 'test')
    monkeypatch.setattr(transport.heartbeat_sent, 'connect', lambda *_ , **__: None)
    monkeypatch.setattr(transport.worker_ready, 'connect', lambda *_ , **__: None)
    monkeypatch.setattr(transport.sys, 'argv', ['transport', 'worker'])
    transport.main()
    assert '--concurrency=2' in captured[0]
    app.close()


def test_celery_thread_worker_starts_second_task_while_first_is_waiting(monkeypatch):
    """Real Celery thread pool, in-memory transport; no external RabbitMQ claim."""
    from celery.contrib.testing.worker import start_worker
    runtime = SimpleNamespace(worker_concurrency=2, broker_url='memory://')
    app = transport.celery_app(runtime, 'parallel-' + uuid4().hex)
    both_started, release, finished = Barrier(3), Event(), Barrier(3)
    def execute(*_):
        both_started.wait(timeout=10)
        assert release.wait(10)
        finished.wait(timeout=10)
    monkeypatch.setattr(transport, 'supervise', execute)
    try:
        with start_worker(app, pool=app.conf.worker_pool, concurrency=app.conf.worker_concurrency,
                          perform_ping_check=False, shutdown_timeout=15):
            try:
                for n in range(2): app.send_task('product.execute', args=[{'n': n}])
                both_started.wait(timeout=10)
                release.set()
                finished.wait(timeout=10)
            finally:
                release.set()
    finally:
        app.close()


def test_two_builds_execute_concurrently_but_duplicate_delivery_and_cancel_are_fenced(setup):
    """Actual PostgreSQL leases and distinct execution IDs, no model calls."""
    from test_postgres import upload, submit
    service, ctx, _ = setup
    item = upload(service, ctx)
    builds = [submit(service, ctx, item) for _ in range(2)]
    ready, release = Barrier(3), Event()
    executions = {}
    def execute(build):
        execution = service.acquire_execution(ctx, build['job_id'], 'parallel-test', deployment_version='test-v1')
        executions[build['build_id']] = execution
        ready.wait(timeout=10)
        assert release.wait(10)
        return execution
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(execute, b) for b in builds]
        try:
            ready.wait(timeout=10)
            assert len({e['id'] for e in executions.values()}) == 2
            for build in builds:
                with pytest.raises(Conflict, match='execution.already_owned'):
                    service.acquire_execution(ctx, build['job_id'], 'duplicate', deployment_version='test-v1')
            service.cancel(ctx, builds[0]['build_id'])
            first, second = [executions[b['build_id']] for b in builds]
            with pytest.raises(Conflict):
                service.heartbeat(ctx, builds[0]['build_id'], first['id'], first['epoch'])
            service.heartbeat(ctx, builds[1]['build_id'], second['id'], second['epoch'])
            with transaction(service.db) as c:
                counts = c.execute(select(m.jobs.c.delivery_count).where(m.jobs.c.id.in_([b['job_id'] for b in builds]))).scalars().all()
            assert counts == [1, 1]
        finally:
            release.set()
            for b in builds: service.cancel(ctx, b['build_id'])
        for f in futures: f.result(timeout=10)
