from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
import os
import time

from celery.exceptions import Reject
from kombu import Connection
import pytest
from sqlalchemy import select

from shuxueshuo_server.product import models as m
from shuxueshuo_server.product.application import Application
from shuxueshuo_server.product.db import transaction
from shuxueshuo_server.product.errors import Conflict
from shuxueshuo_server.product.repositories import row
from shuxueshuo_server.product.runtime_config import RuntimeConfig
from shuxueshuo_server.product.services import now
from shuxueshuo_server.product.transport import celery_app, queue_for, publish_once, recover_expired, supervise


def build(setup, settings, version='offline-runner-v1'):
    from PIL import Image
    from io import BytesIO
    from test_runner import offline_discover
    s, ctx, admin = setup
    def discover(*args): return {**offline_discover(*args), 'deployment_version': version}
    a = Application(settings, s, ctx, discover=discover)
    batch = a.create_batch('batch')
    content = BytesIO(); Image.new('RGB', (8, 8)).save(content, format='PNG')
    item = a.upload(UUID(batch['id']), 'upload', content.getvalue(), 'fixture.png', 'image/png')['item']
    b = a.submit(UUID(item['problem_id']), UUID(item['source_id']), UUID(item['id']), 'build')
    return a, {k: UUID(v) for k, v in b.items()}, admin


@pytest.fixture
def runtime(settings):
    if os.environ.get('PRODUCT_TEST_BROKER') != '1': pytest.skip('explicit dedicated broker opt-in required')
    r = RuntimeConfig.load(settings)
    assert r.values['BROKER_VHOST'] != 'product_local'
    with Connection(r.broker_url, connect_timeout=3) as c: c.ensure_connection(max_retries=0)
    from kombu import pools
    pools.reset()
    return r


def test_confirm_loss_republishes_and_stale_token_is_fenced(setup, settings, runtime, monkeypatch):
    from shuxueshuo_server.product import transport
    from shuxueshuo_server.product.outbox import reserve, acknowledge
    a, b, admin = build(setup, settings)
    with transaction(a.db) as c:
        target = row(c, m.outbox_messages, job_id=b['job_id'])
    # Isolate this publisher reservation from other tests' intentionally pending jobs.
    def own_reserve(c, **_):
        record = row(c, m.outbox_messages, id=target['id'])
        token = uuid4()
        c.execute(m.outbox_messages.update().where(m.outbox_messages.c.id == target['id']).values(status='publishing', publisher_token=token,
            locked_until=now(c) + timedelta(seconds=30), attempt_count=record['attempt_count'] + 1))
        return [{**record, 'publisher_token': token}]
    monkeypatch.setattr(transport, 'reserve', own_reserve)
    version = 'fault-' + uuid4().hex
    client = celery_app(runtime, version)
    original_send = client.send_task
    def send_then_lose(*args, **kwargs):
        kwargs['queue'] = client.conf.task_queues[0]; kwargs['routing_key'] = queue_for(version)
        original_send(*args, **kwargs)
        raise ConnectionError('confirm response lost after broker accepted')
    monkeypatch.setattr(client, 'send_task', send_then_lose)
    assert publish_once(a, client) == 1
    with transaction(a.db) as c:
        failed = row(c, m.outbox_messages, id=target['id'])
        assert failed['status'] == 'pending'
    def resend(*args, **kwargs):
        kwargs['queue'] = client.conf.task_queues[0]; kwargs['routing_key'] = queue_for(version)
        return original_send(*args, **kwargs)
    monkeypatch.setattr(client, 'send_task', resend)
    assert publish_once(a, client) == 1
    with transaction(a.db) as c:
        assert row(c, m.outbox_messages, id=target['id'])['status'] == 'published'
        with pytest.raises(Conflict): acknowledge(c, target['id'], failed['publisher_token'], confirmed=True)
    with client.connection_for_read() as c:
        q = client.conf.task_queues[0](c)
        try:
            messages = [q.get(no_ack=False), q.get(no_ack=False)]
            assert all(messages) and messages[0].payload == messages[1].payload
            for msg in messages: msg.ack()
            assert q.get() is None
        finally: q.delete()
    a.service.cancel(a.ctx, b['build_id'])


def test_delivery_recovery_epoch_cancel_and_budget(setup, settings, monkeypatch):
    a, b, admin = build(setup, settings)
    version = 'offline-runner-v1'
    message = {'protocol_version': 'product-job/v1', **{k: str(v) for k, v in b.items()}}
    monkeypatch.setattr('shuxueshuo_server.product.transport.load_application', lambda: a)
    execution = a.service.acquire_execution(a.ctx, b['job_id'], 'worker', deployment_version=version)
    # Real supervisor deduplicates before attempting to spawn a process.
    supervise(None, version, message)
    with transaction(a.db) as c: assert row(c, m.jobs, id=b['job_id'])['delivery_count'] == 1
    for epoch in (1, 2, 3):
        with transaction(admin) as c:
            c.execute(m.jobs.update().where(m.jobs.c.id == b['job_id']).values(lease_expires_at=now(c) - timedelta(seconds=1)))
        recover_expired(a); recover_expired(a)
        with transaction(a.db) as c:
            records = c.execute(select(m.outbox_messages).where(m.outbox_messages.c.dedupe_key == f"recover:{b['job_id']}:{epoch}")).all()
            assert len(records) == 1
        acquired = a.service.acquire_execution(a.ctx, b['job_id'], 'replacement', deployment_version=version)
        with pytest.raises(Conflict): a.service.heartbeat(a.ctx, b['build_id'], execution['id'], execution['epoch'])
    assert acquired['status'] == 'failed'
    assert a.build(b['build_id'])['error_code'] == 'job.budget_exhausted'
    with pytest.raises(Reject): supervise(None, version, {'protocol_version': 'unknown'})


def test_durable_queue_survives_native_broker_restart(runtime):
    from shuxueshuo_server.product.admin import broker
    client = celery_app(runtime, 'restart-' + uuid4().hex)
    client.send_task('product.execute', args=[{'offline': True}], retry=False)
    broker.stop(runtime)
    broker.start(runtime)
    with client.connection_for_read() as c:
        q = client.conf.task_queues[0](c)
        try:
            message = q.get(no_ack=False)
            assert message is not None and message.payload[0] == [{'offline': True}]
            message.ack()
        finally: q.delete()


def test_killed_worker_recovers_with_new_epoch_without_duplicate_execution(setup, settings, runtime, tmp_path):
    import signal
    import subprocess
    import sys
    from pathlib import Path
    version = 'fault-' + uuid4().hex
    a, b, admin = build(setup, settings, version)
    client = celery_app(runtime, version)
    marker = tmp_path / 'child.pid'
    workers, children = [], []
    def launch():
        log = (tmp_path / f'worker-{len(workers)}.log').open('ab')
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('worker_fault_entry.py')), version, str(marker)],
            env=runtime.environment(), stdout=log, stderr=log, start_new_session=True)
        log.close(); workers.append(process)
        return process
    def await_epoch(epoch):
        until = time.monotonic() + 30
        while time.monotonic() < until:
            with transaction(a.db) as c: job = row(c, m.jobs, id=b['job_id'])
            if job['execution_epoch'] == epoch and marker.exists():
                children.append(int(marker.read_text())); return job
            time.sleep(.1)
        pytest.fail('worker failed to acquire expected execution')
    with client.connection_for_write() as c:
        client.conf.task_queues[0](c).declare()
        client.conf.task_queues[0](c).purge()
    try:
        first = launch()
        msg = {'protocol_version': 'product-job/v1', **{k: str(v) for k, v in b.items()}}
        client.send_task('product.execute', args=[msg], retry=False)
        initial = await_epoch(1)
        os.killpg(first.pid, signal.SIGKILL); first.wait(10)
        marker.unlink()
        with transaction(admin) as c:
            c.execute(m.jobs.update().where(m.jobs.c.id == b['job_id']).values(lease_expires_at=now(c) - timedelta(seconds=1)))
        recover_expired(a)
        launch()
        # Both broker redelivery and the recovery outbox may dispatch; the job lock arbitrates.
        publish_once(a, client)
        replacement = await_epoch(2)
        client.send_task('product.execute', args=[msg], retry=False)
        with pytest.raises(Conflict):
            a.service.begin_stage(a.ctx, b['build_id'], initial['active_execution_id'], 1, 'source')
        a.service.cancel(a.ctx, b['build_id'])
        with transaction(a.db) as c:
            assert row(c, m.jobs, id=b['job_id'])['delivery_count'] == 2
    finally:
        a.service.cancel(a.ctx, b['build_id'])
        for process in workers:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(15)
                except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL); process.wait()
        for pid in children:
            try: os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError: pass
        with client.connection_for_write() as c: client.conf.task_queues[0](c).delete()
