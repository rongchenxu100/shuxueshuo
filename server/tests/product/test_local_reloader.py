"""Manual local service restart helpers."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shuxueshuo_server.product.admin import runtime
from shuxueshuo_server.product.admin.reloader import _interesting


def test_interesting_filters_pycache_and_keeps_python():
    assert _interesting('/repo/server/shuxueshuo_server/product/runner.py')
    assert not _interesting('/repo/server/shuxueshuo_server/product/__pycache__/runner.cpython-311.pyc')
    assert not _interesting('/repo/server/.venv/lib/python.py')


def test_restart_python_services_skips_when_versions_match(tmp_path, monkeypatch):
    (tmp_path / 'locks').mkdir()
    (tmp_path / 'config').mkdir()
    (tmp_path / 'logs').mkdir()
    version = 'abc123'
    config = SimpleNamespace(settings=SimpleNamespace(root=tmp_path, url=lambda: 'unused'), values={'API_PORT': '8000'})
    monkeypatch.setattr(runtime, 'Application', Mock(return_value=Mock(service=object(), close=Mock())))
    monkeypatch.setattr(runtime, 'deployment', lambda _: version)
    monkeypatch.setattr(runtime, 'process_state', lambda _: {
        name: {'pid': 1, 'signature': 'sig', 'version': version, 'running': True}
        for name in runtime.PYTHON_SERVICES
    })
    stop = Mock()
    spawn = Mock()
    monkeypatch.setattr(runtime, 'stop_named', stop)
    monkeypatch.setattr(runtime, 'spawn_named', spawn)
    result = runtime.restart_python_services(config)
    assert result == {'ok': True, 'skipped': True, 'version': version}
    stop.assert_not_called()
    spawn.assert_not_called()


def test_restart_python_services_bounces_on_mismatch(tmp_path, monkeypatch):
    (tmp_path / 'locks').mkdir()
    (tmp_path / 'config').mkdir()
    (tmp_path / 'logs').mkdir()
    config = SimpleNamespace(settings=SimpleNamespace(root=tmp_path, url=lambda: 'unused'), values={'API_PORT': '8000'})
    monkeypatch.setattr(runtime, 'Application', Mock(return_value=Mock(service=object(), close=Mock())))
    monkeypatch.setattr(runtime, 'deployment', lambda _: 'new-version')
    monkeypatch.setattr(runtime, 'process_state', lambda _: {
        'api': {'pid': 1, 'signature': 'sig', 'version': 'old', 'running': True},
        'publisher': {'pid': 2, 'signature': 'sig', 'version': 'old', 'running': True},
        'worker': {'pid': 3, 'signature': 'sig', 'version': 'old', 'running': True},
    })
    stop = Mock()
    spawn = Mock()
    wait = Mock()
    monkeypatch.setattr(runtime, 'stop_named', stop)
    monkeypatch.setattr(runtime, 'spawn_named', spawn)
    monkeypatch.setattr(runtime, 'wait_python_ready', wait)
    result = runtime.restart_python_services(config)
    assert result['ok'] and result['version'] == 'new-version'
    stop.assert_called_once_with(config, runtime.PYTHON_SERVICES)
    spawn.assert_called_once_with(config, 'new-version', runtime.PYTHON_SERVICES)
    wait.assert_called_once_with(config, 'new-version')


def test_restart_queue_services_skips_api_wait(tmp_path, monkeypatch):
    (tmp_path / 'locks').mkdir()
    (tmp_path / 'config').mkdir()
    config = SimpleNamespace(settings=SimpleNamespace(root=tmp_path, url=lambda: 'unused'), values={'API_PORT': '8000'})
    monkeypatch.setattr(runtime, 'Application', Mock(return_value=Mock(service=object(), close=Mock())))
    monkeypatch.setattr(runtime, 'deployment', lambda _: 'new-version')
    states = [
        {
            'publisher': {'pid': 2, 'signature': 'sig', 'version': 'old', 'running': True},
            'worker': {'pid': 3, 'signature': 'sig', 'version': 'old', 'running': True},
        },
        {
            'publisher': {'pid': 4, 'signature': 'sig', 'version': 'new-version', 'running': True},
            'worker': {'pid': 5, 'signature': 'sig', 'version': 'new-version', 'running': True},
        },
        {
            'publisher': {'pid': 4, 'signature': 'sig', 'version': 'new-version', 'running': True},
            'worker': {'pid': 5, 'signature': 'sig', 'version': 'new-version', 'running': True},
        },
    ]
    monkeypatch.setattr(runtime, 'process_state', lambda _: states.pop(0) if len(states) > 1 else states[0])
    stop = Mock()
    spawn = Mock()
    wait = Mock()
    monkeypatch.setattr(runtime, 'stop_named', stop)
    monkeypatch.setattr(runtime, 'spawn_named', spawn)
    monkeypatch.setattr(runtime, 'wait_python_ready', wait)
    monkeypatch.setattr(runtime.time, 'sleep', lambda _: None)
    result = runtime.restart_python_services(config, services=runtime.QUEUE_SERVICES)
    assert result['ok'] and result['version'] == 'new-version'
    stop.assert_called_once_with(config, runtime.QUEUE_SERVICES)
    wait.assert_not_called()


def test_local_fail_stale_deployments_is_noop(monkeypatch):
    from shuxueshuo_server.product import transport
    monkeypatch.setenv('PRODUCT_MODE', 'local')
    assert transport.fail_stale_deployments(Mock(), 'v') == 0


def test_restart_python_services_skips_while_draining(tmp_path):
    (tmp_path / 'locks').mkdir()
    (tmp_path / 'locks' / 'services-draining').touch()
    config = SimpleNamespace(settings=SimpleNamespace(root=tmp_path))
    assert runtime.restart_python_services(config) == {'ok': False, 'reason': 'draining'}
