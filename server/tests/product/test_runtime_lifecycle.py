"""Stopping a previous release must work before its database is migrated."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shuxueshuo_server.product.admin import runtime
from shuxueshuo_server.product.errors import ProductError


@pytest.fixture
def stopping(tmp_path, monkeypatch):
    (tmp_path / 'locks').mkdir()
    settings = SimpleNamespace(root=tmp_path, url=lambda: 'unused')
    config = SimpleNamespace(settings=settings)
    db, connection = Mock(), Mock()

    @contextmanager
    def transaction(value):
        assert value is db
        yield connection

    application = Mock(side_effect=AssertionError('The new Application requires migration first'))
    broker_stop, kill = Mock(), Mock()
    monkeypatch.setattr(runtime, 'Application', application)
    monkeypatch.setattr(runtime, 'engine', lambda _: db)
    monkeypatch.setattr(runtime, 'transaction', transaction)
    monkeypatch.setattr(runtime, 'process_state', lambda _: {})
    monkeypatch.setattr(runtime.time, 'sleep', lambda _: None)
    monkeypatch.setattr(runtime.os, 'killpg', kill)
    monkeypatch.setattr(runtime.broker, 'stop', broker_stop)
    monkeypatch.setattr(runtime.native, 'status', lambda _: True)
    return config, db, connection, application, broker_stop, kill


@pytest.mark.parametrize('counts', [[0], [1, 0]])
def test_stop_drains_previous_release_without_loading_new_application(stopping, counts):
    config, db, connection, application, broker_stop, _ = stopping
    connection.scalar.side_effect = counts
    assert runtime.stop(config)['ok']
    assert connection.scalar.call_count == len(counts)
    application.assert_not_called()
    db.dispose.assert_called_once()
    broker_stop.assert_called_once_with(config)
    assert (config.settings.root / 'locks/services-draining').exists()


def test_stop_retains_processes_if_tasks_do_not_drain(stopping):
    config, db, connection, _, broker_stop, kill = stopping
    connection.scalar.return_value = 1
    with pytest.raises(ProductError, match='runtime.drain_timeout_tasks_retained'):
        runtime.stop(config)
    db.dispose.assert_called_once()
    broker_stop.assert_not_called()
    kill.assert_not_called()
