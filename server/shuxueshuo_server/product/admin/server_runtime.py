"""Server P2 service helpers executed inside the admin container."""
from pathlib import Path
import os

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


def doctor(runtime):
    result = database.doctor(runtime.settings)
    with Connection(runtime.broker_url, connect_timeout=5) as connection:
        connection.ensure_connection(max_retries=0)
    ocr = Path(runtime.values['OCR_PYTHON'])
    return {
        **result,
        'broker': True,
        'broker_host': runtime.broker_host,
        'broker_port': runtime.values['BROKER_PORT'],
        'ocr_python_configured': ocr.is_file(),
        'product_mode': os.environ.get('PRODUCT_MODE', runtime.settings.mode),
    }
