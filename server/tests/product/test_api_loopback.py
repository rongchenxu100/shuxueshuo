"""Server-container peer checks for Docker published loopback ports."""
from types import SimpleNamespace

import pytest

from shuxueshuo_server.product.api import check_peer
from shuxueshuo_server.product.errors import Forbidden


def _conn(host, client, origin=None):
    headers = {}
    if origin:
        headers['origin'] = origin
    return SimpleNamespace(
        client=SimpleNamespace(host=client),
        url=SimpleNamespace(hostname=host),
        headers=headers,
    )


def test_local_requires_loopback_peer(monkeypatch):
    monkeypatch.delenv('PRODUCT_IN_CONTAINER', raising=False)
    monkeypatch.setenv('PRODUCT_MODE', 'local')
    check_peer(_conn('127.0.0.1', '127.0.0.1'))
    with pytest.raises(Forbidden, match='access.loopback_only'):
        check_peer(_conn('127.0.0.1', '172.18.0.1'))


def test_server_container_allows_docker_nat_peer(monkeypatch):
    monkeypatch.setenv('PRODUCT_IN_CONTAINER', '1')
    monkeypatch.setenv('PRODUCT_MODE', 'server')
    check_peer(_conn('127.0.0.1', '172.18.0.1'))
    check_peer(_conn('api', '172.18.0.4'))
    with pytest.raises(Forbidden, match='access.loopback_only'):
        check_peer(_conn('evil.example', '172.18.0.1'))


def test_server_container_allows_public_studio_origin(monkeypatch):
    monkeypatch.setenv('PRODUCT_IN_CONTAINER', '1')
    monkeypatch.setenv('PRODUCT_MODE', 'server')
    monkeypatch.delenv('PRODUCT_PUBLIC_ORIGINS', raising=False)
    check_peer(_conn('127.0.0.1', '172.18.0.1', origin='https://studio.shuxueshuo.com'))
    with pytest.raises(Forbidden, match='access.origin_rejected'):
        check_peer(_conn('127.0.0.1', '172.18.0.1', origin='https://evil.example'))
    monkeypatch.setenv('PRODUCT_PUBLIC_ORIGINS', 'https://studio.shuxueshuo.com,https://other.example')
    check_peer(_conn('127.0.0.1', '172.18.0.1', origin='https://other.example'))


def test_local_rejects_public_studio_origin(monkeypatch):
    monkeypatch.delenv('PRODUCT_IN_CONTAINER', raising=False)
    monkeypatch.setenv('PRODUCT_MODE', 'local')
    with pytest.raises(Forbidden, match='access.origin_rejected'):
        check_peer(_conn('127.0.0.1', '127.0.0.1', origin='https://studio.shuxueshuo.com'))
