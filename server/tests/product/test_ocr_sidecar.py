"""OCR invocation via PRODUCT_OCR_URL sidecar vs local REVIEW_OCR_PYTHON."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from shuxueshuo_server.product.errors import ProductError
from shuxueshuo_server.product.runner import StageRunner


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status = status

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_ocr_uses_sidecar_when_url_set(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'source-journal.json').write_text(json.dumps([]))
    x = SimpleNamespace(
        work=work,
        build={'source_id': '11111111-1111-4111-8111-111111111111'},
        add=MagicMock(),
    )
    monkeypatch.setenv('PRODUCT_OCR_URL', 'http://ocr:8080')

    def fake_urlopen(request, timeout=0):
        assert request.full_url == 'http://ocr:8080/v1/observe'
        body = json.loads(request.data.decode())
        assert body['phase'] == 'source'
        assert body['work_dir'] == str(work)
        return _FakeResponse({'ok': True, 'exit_code': 0, 'stdout': '', 'stderr': ''})

    monkeypatch.setattr('shuxueshuo_server.product.runner.urllib.request.urlopen', fake_urlopen)
    StageRunner(x).ocr('source')
    assert x.add.call_args.args[0] == 'OCR 进程日志'
    assert x.add.call_args.args[1]['via'] == 'sidecar'


def test_ocr_sidecar_nonzero_exit_raises(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    work.mkdir()
    x = SimpleNamespace(
        work=work,
        build={'source_id': '11111111-1111-4111-8111-111111111111'},
        add=MagicMock(),
    )
    monkeypatch.setenv('PRODUCT_OCR_URL', 'http://ocr:8080')
    monkeypatch.setattr(
        'shuxueshuo_server.product.runner.urllib.request.urlopen',
        lambda *a, **k: _FakeResponse({'ok': False, 'exit_code': 1, 'stdout': '', 'stderr': 'boom'}),
    )
    with pytest.raises(ProductError, match='observation.provider_failed'):
        StageRunner(x).ocr('source')


def test_ocr_without_url_requires_interpreter(tmp_path, monkeypatch):
    monkeypatch.delenv('PRODUCT_OCR_URL', raising=False)
    monkeypatch.setenv('REVIEW_OCR_PYTHON', str(tmp_path / 'missing-python'))
    x = SimpleNamespace(
        work=tmp_path,
        build={'source_id': '11111111-1111-4111-8111-111111111111'},
        add=MagicMock(),
    )
    with pytest.raises(ProductError, match='configuration.ocr_missing'):
        StageRunner(x).ocr('source')
