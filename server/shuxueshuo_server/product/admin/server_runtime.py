"""Server P2 service helpers executed inside the admin container."""
from pathlib import Path
import json
import os
import urllib.error
import urllib.request

from kombu import Connection

from ..errors import ProductError
from ..runtime_config import RuntimeConfig
from . import database


def execute(settings, operation):
    if settings.mode != 'server':
        raise ProductError('runtime.server_only')
    if operation == 'services-install':
        runtime = RuntimeConfig.load(settings, initialize=True)
        database.migrate(settings)
        return {
            'ok': True,
            'broker': 'docker',
            'broker_port': runtime.values['BROKER_PORT'],
            'broker_vhost': runtime.values['BROKER_VHOST'],
            'ocr_python': runtime.values['OCR_PYTHON'],
        }
    runtime = RuntimeConfig.load(settings)
    if operation == 'services-doctor':
        return doctor(runtime)
    if operation == 'services-status':
        return {
            'ok': True,
            'broker_url_host': runtime.broker_host,
            'broker_port': runtime.values['BROKER_PORT'],
            'runtime_installed': True,
        }
    raise ProductError('runtime.use_host_compose_for_' + operation.replace('-', '_'))


def _ocr_configured(path_value, *, mode):
    if not path_value:
        return False
    path = Path(path_value)
    if path.is_file():
        return True
    # Server: admin cannot see app-image or host wrapper paths; start validates OCR image.
    if mode == 'server':
        return True
    return path_value == '/app/bin/ocr-python' or path_value.endswith('/bin/ocr-python')


def _api_health():
    try:
        with urllib.request.urlopen('http://api:8000/api/product/v1/health', timeout=5) as response:
            body = json.loads(response.read().decode())
        return {'api': True, 'api_health': body}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return {'api': False, 'api_error': type(exc).__name__}


def doctor(runtime):
    result = database.doctor(runtime.settings)
    with Connection(runtime.broker_url, connect_timeout=5) as connection:
        connection.ensure_connection(max_retries=0)
    return {
        **result,
        'broker': True,
        'broker_host': runtime.broker_host,
        'broker_port': runtime.values['BROKER_PORT'],
        'ocr_python': runtime.values['OCR_PYTHON'],
        'ocr_python_configured': _ocr_configured(runtime.values['OCR_PYTHON'], mode=runtime.settings.mode),
        'product_mode': os.environ.get('PRODUCT_MODE', runtime.settings.mode),
        **_api_health(),
    }
