"""Private instance runtime configuration; no secrets in frozen build settings."""
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
from urllib.parse import quote

from dotenv import dotenv_values

from .config import Settings, REPO, write_private
from .errors import ProductError


@dataclass(frozen=True)
class RuntimeConfig:
    settings: Settings
    values: dict

    @classmethod
    def load(cls, settings, *, initialize=False):
        path = settings.root / 'config/runtime.env'
        if not path.exists():
            if not initialize: raise ProductError('runtime.not_installed')
            defaults = {
                'BROKER_PORT': os.environ.get('PRODUCT_BROKER_PORT', '5672'),
                'BROKER_HOST': os.environ.get('PRODUCT_BROKER_HOST', '127.0.0.1'),
                'BROKER_USER': 'product_' + settings.instance,
                'BROKER_PASSWORD': secrets.token_urlsafe(32),
                'BROKER_VHOST': 'product_' + settings.instance,
                'BROKER_COOKIE': secrets.token_hex(24),
                'API_PORT': os.environ.get('PRODUCT_API_PORT', '8000'),
                'FRONTEND_PORT': os.environ.get('PRODUCT_FRONTEND_PORT', '3000'),
                'WORKER_CONCURRENCY': os.environ.get('PRODUCT_WORKER_CONCURRENCY', '1'),
                'OCR_PYTHON': os.environ.get(
                    'REVIEW_OCR_PYTHON',
                    '/app/bin/ocr-python' if settings.mode == 'server'
                    else str(REPO / 'server/.venv-ocr/bin/python')),
            }
            if settings.mode == 'local':
                defaults['RABBITMQ_BIN'] = os.environ.get(
                    'PRODUCT_RABBITMQ_BIN', '/opt/homebrew/opt/rabbitmq/sbin')
            else:
                # Server broker runs in Compose; no host rabbitmq sbin is required.
                defaults['RABBITMQ_BIN'] = os.environ.get('PRODUCT_RABBITMQ_BIN', '')
            write_private(path, defaults)
        if path.stat().st_mode & 0o077: raise ProductError('runtime.permissions')
        values = dict(dotenv_values(path))
        values.setdefault('BROKER_HOST', '127.0.0.1')
        values.setdefault('RABBITMQ_BIN', '')
        values.setdefault('WORKER_CONCURRENCY', '1')
        # Validate overrides before any worker starts or private defaults are used.
        concurrency = os.environ.get('PRODUCT_WORKER_CONCURRENCY', values['WORKER_CONCURRENCY'])
        if not isinstance(concurrency, str) or not concurrency.isascii() or not concurrency.isdecimal() or not 1 <= int(concurrency) <= 16:
            raise ProductError('runtime.worker_concurrency')
        values['WORKER_CONCURRENCY'] = str(int(concurrency))
        for key in ('BROKER_PORT', 'API_PORT', 'FRONTEND_PORT'):
            if not 1024 <= int(values[key]) <= (45000 if key == 'BROKER_PORT' else 65535):
                raise ProductError('runtime.port')
        if settings.mode == 'local' and not Path(values['RABBITMQ_BIN']).is_dir():
            raise ProductError('runtime.rabbitmq_bin_missing')
        return cls(settings, values)

    @property
    def worker_concurrency(self):
        return int(self.values.get('WORKER_CONCURRENCY', '1'))

    @property
    def broker_host(self):
        if os.environ.get('PRODUCT_IN_CONTAINER') == '1' and self.settings.mode == 'server':
            return 'rabbitmq'
        return self.values.get('BROKER_HOST', '127.0.0.1')

    @property
    def broker_port(self):
        if os.environ.get('PRODUCT_IN_CONTAINER') == '1' and self.settings.mode == 'server':
            return '5672'
        return self.values['BROKER_PORT']

    @property
    def broker_url(self):
        v = self.values
        return (
            f"amqp://{quote(v['BROKER_USER'], safe='')}:{quote(v['BROKER_PASSWORD'], safe='')}"
            f"@{self.broker_host}:{self.broker_port}/{quote(v['BROKER_VHOST'], safe='')}"
        )

    def environment(self):
        # Prefer in-container PRODUCT_OCR_URL (sidecar). Fall back to REVIEW_OCR_PYTHON
        # for Mac/local direct Paddle installs; do not overwrite with a stale host path
        # from runtime.env when the container already injects OCR settings.
        if os.environ.get('PRODUCT_IN_CONTAINER') == '1' and self.settings.mode == 'server':
            ocr = os.environ.get('REVIEW_OCR_PYTHON') or self.values.get('OCR_PYTHON') or ''
        else:
            ocr = self.values['OCR_PYTHON']
        env = {
            **os.environ,
            'PRODUCT_MODE': self.settings.mode,
            'PRODUCT_DATA_DIR': str(self.settings.root),
            'PRODUCT_INSTANCE': self.settings.instance,
            'PRODUCT_API_PORT': self.values['API_PORT'],
            'PRODUCT_FRONTEND_PORT': self.values['FRONTEND_PORT'],
            'PRODUCT_WORKER_CONCURRENCY': str(self.worker_concurrency),
            'PYTHONPATH': str(REPO / 'server'),
            'PYTHONUNBUFFERED': '1',
            'REVIEW_BACKEND': 'product',
        }
        if ocr:
            env['REVIEW_OCR_PYTHON'] = ocr
        return env


def load_runtime():
    settings = Settings.load(os.environ.get('PRODUCT_MODE', 'local'), instance=os.environ.get('PRODUCT_INSTANCE'))
    return RuntimeConfig.load(settings)
