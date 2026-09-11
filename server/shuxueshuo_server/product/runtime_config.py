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
            write_private(path, {'BROKER_PORT': os.environ.get('PRODUCT_BROKER_PORT', '5672'),
                'BROKER_USER': 'product_' + settings.instance, 'BROKER_PASSWORD': secrets.token_urlsafe(32),
                'BROKER_VHOST': 'product_' + settings.instance, 'BROKER_COOKIE': secrets.token_hex(24),
                'API_PORT': os.environ.get('PRODUCT_API_PORT', '8000'), 'FRONTEND_PORT': os.environ.get('PRODUCT_FRONTEND_PORT', '3000'),
                'OCR_PYTHON': os.environ.get('REVIEW_OCR_PYTHON', str(REPO / 'server/.venv-ocr/bin/python')),
                'RABBITMQ_BIN': os.environ.get('PRODUCT_RABBITMQ_BIN', '/opt/homebrew/opt/rabbitmq/sbin')})
        if path.stat().st_mode & 0o077: raise ProductError('runtime.permissions')
        values = dict(dotenv_values(path))
        for key in ('BROKER_PORT', 'API_PORT', 'FRONTEND_PORT'):
            if not 1024 <= int(values[key]) <= (45000 if key == 'BROKER_PORT' else 65535): raise ProductError('runtime.port')
        return cls(settings, values)

    @property
    def broker_url(self):
        v = self.values
        return f"amqp://{quote(v['BROKER_USER'], safe='')}:{quote(v['BROKER_PASSWORD'], safe='')}@127.0.0.1:{v['BROKER_PORT']}/{quote(v['BROKER_VHOST'], safe='')}"

    def environment(self):
        return {**os.environ, 'PRODUCT_MODE': 'local', 'PRODUCT_DATA_DIR': str(self.settings.root),
                'PRODUCT_INSTANCE': self.settings.instance, 'PRODUCT_API_PORT': self.values['API_PORT'],
                'PRODUCT_FRONTEND_PORT': self.values['FRONTEND_PORT'], 'REVIEW_OCR_PYTHON': self.values['OCR_PYTHON'],
                'PYTHONPATH': str(REPO / 'server'), 'PYTHONUNBUFFERED': '1', 'REVIEW_BACKEND': 'product'}


def load_runtime():
    settings = Settings.load(os.environ.get('PRODUCT_MODE', 'local'), instance=os.environ.get('PRODUCT_INSTANCE'))
    return RuntimeConfig.load(settings)
