"""RuntimeConfig broker targeting for local host vs server containers."""
import os
from pathlib import Path

import pytest

from shuxueshuo_server.product.config import Settings, write_private
from shuxueshuo_server.product.runtime_config import RuntimeConfig


def _settings(tmp_path, mode='local'):
    root = tmp_path / mode
    root.mkdir()
    for name in ('config', 'artifacts', 'work', 'backups', 'logs', 'locks'):
        (root / name).mkdir()
    write_private(root / 'config' / ('local.env' if mode == 'local' else 'compose.env'), {
        'PRODUCT_INSTANCE': mode if mode == 'local' else 'server',
        'PRODUCT_DATA_DIR': str(root),
        'PRODUCT_DB_PORT': '5432',
        'PRODUCT_PG_BIN_DIR': '/usr/bin',
    })
    for role in ('app', 'migration', 'bootstrap'):
        write_private(root / 'config' / f'{role}.env', {f'PRODUCT_{role.upper()}_PASSWORD': 'x'})
    return Settings.load(mode, str(root), 'local' if mode == 'local' else 'server', 5432)


def test_server_runtime_initialize_skips_rabbitmq_bin(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCT_RABBITMQ_BIN', raising=False)
    monkeypatch.setenv('REVIEW_OCR_PYTHON', '/opt/ocr/python')
    settings = _settings(tmp_path, 'server')
    runtime = RuntimeConfig.load(settings, initialize=True)
    assert runtime.values['RABBITMQ_BIN'] == ''
    assert runtime.values['OCR_PYTHON'] == '/opt/ocr/python'
    assert runtime.values['BROKER_HOST'] == '127.0.0.1'
    assert runtime.broker_host == '127.0.0.1'
    assert ':5672/' in runtime.broker_url


def test_server_runtime_default_ocr_is_app_wrapper(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCT_RABBITMQ_BIN', raising=False)
    monkeypatch.delenv('REVIEW_OCR_PYTHON', raising=False)
    settings = _settings(tmp_path, 'server')
    runtime = RuntimeConfig.load(settings, initialize=True)
    assert runtime.values['OCR_PYTHON'] == '/app/bin/ocr-python'


def test_server_container_environment_keeps_app_ocr(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCT_RABBITMQ_BIN', raising=False)
    monkeypatch.setenv('REVIEW_OCR_PYTHON', '/home/host/.venv-ocr/bin/python')
    settings = _settings(tmp_path, 'server')
    runtime = RuntimeConfig.load(settings, initialize=True)
    assert runtime.values['OCR_PYTHON'] == '/home/host/.venv-ocr/bin/python'
    monkeypatch.setenv('PRODUCT_IN_CONTAINER', '1')
    monkeypatch.setenv('REVIEW_OCR_PYTHON', '/app/bin/ocr-python')
    env = runtime.environment()
    assert env['REVIEW_OCR_PYTHON'] == '/app/bin/ocr-python'


def test_server_broker_host_inside_container(tmp_path, monkeypatch):
    monkeypatch.setenv('REVIEW_OCR_PYTHON', '/opt/ocr/python')
    settings = _settings(tmp_path, 'server')
    runtime = RuntimeConfig.load(settings, initialize=True)
    monkeypatch.setenv('PRODUCT_IN_CONTAINER', '1')
    assert runtime.broker_host == 'rabbitmq'
    assert runtime.broker_port == '5672'
    assert '@rabbitmq:5672/' in runtime.broker_url


def test_local_runtime_requires_rabbitmq_bin(tmp_path, monkeypatch):
    monkeypatch.setenv('PRODUCT_RABBITMQ_BIN', str(tmp_path / 'missing-sbin'))
    monkeypatch.setenv('REVIEW_OCR_PYTHON', str(tmp_path / 'ocr'))
    Path(tmp_path / 'ocr').write_text('x')
    settings = _settings(tmp_path, 'local')
    with pytest.raises(Exception):
        RuntimeConfig.load(settings, initialize=True)


def test_worker_concurrency_defaults_file_override_and_environment(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCT_WORKER_CONCURRENCY', raising=False)
    settings = _settings(tmp_path, 'server')
    runtime = RuntimeConfig.load(settings, initialize=True)
    assert runtime.worker_concurrency == 1
    values = {k: v for k, v in runtime.values.items() if k != 'WORKER_CONCURRENCY'}
    (settings.root / 'config/runtime.env').unlink()
    write_private(settings.root / 'config/runtime.env', values)
    assert RuntimeConfig.load(settings).worker_concurrency == 1  # existing installations
    (settings.root / 'config/runtime.env').unlink()
    write_private(settings.root / 'config/runtime.env', {**values, 'WORKER_CONCURRENCY': '2'})
    assert RuntimeConfig.load(settings).environment()['PRODUCT_WORKER_CONCURRENCY'] == '2'
    monkeypatch.setenv('PRODUCT_WORKER_CONCURRENCY', '3')
    assert RuntimeConfig.load(settings).worker_concurrency == 3


@pytest.mark.parametrize('value', ['0', '-1', '17', '2.5', '', 'many', '２'])
def test_worker_concurrency_rejects_invalid_configuration(tmp_path, monkeypatch, value):
    from shuxueshuo_server.product.errors import ProductError
    settings = _settings(tmp_path, 'server')
    RuntimeConfig.load(settings, initialize=True)
    monkeypatch.setenv('PRODUCT_WORKER_CONCURRENCY', value)
    with pytest.raises(ProductError, match='runtime.worker_concurrency'):
        RuntimeConfig.load(settings)
