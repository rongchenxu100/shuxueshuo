from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from shuxueshuo_server.product.api import create_app
from shuxueshuo_server.product.repositories import UserContext
from test_runner import run_context  # noqa: F401


@pytest.fixture
def page_client(run_context):
    app, x, runner, _, admin = run_context
    runner.run()
    page_id = app.build(x.build['id'])['page_id']
    with TestClient(create_app(app)) as client:
        yield app, client, admin, page_id


def test_page_etag_revalidation_and_headers(page_client):
    app, client, _, page_id = page_client
    url = f'/api/product/v1/pages/{page_id}/index.html'
    first = client.get(url)
    assert first.status_code == 200 and b'<html' in first.content
    ref = app.service.page_resource(app.ctx, UUID(page_id), 'index.html')
    etag = first.headers['etag']
    assert etag == f'W/"{ref["sha256"]}"'
    assert int(first.headers['content-length']) == len(first.content)
    assert first.headers['cache-control'] == 'private, no-cache'
    assert first.headers['vary'] == 'Accept-Encoding'
    for value in [etag, etag[2:], f'"old", {etag}', '*']:
        repeated = client.get(url, headers={'If-None-Match': value})
        assert repeated.status_code == 304 and repeated.content == b''
        assert 'content-length' not in repeated.headers
        for key in ['etag', 'cache-control', 'vary', 'content-security-policy', 'x-content-type-options']:
            assert repeated.headers[key] == first.headers[key]
    for value in ['"old"', ref['sha256'], f'W/"{ref["sha256"]}extra"']:
        changed = client.get(url, headers={'If-None-Match': value})
        assert changed.status_code == 200 and changed.content == first.content
    assert client.get(f'/api/product/v1/pages/{uuid4()}/index.html', headers={'If-None-Match': '*'}).status_code == 404
    assert client.get(f'/api/product/v1/pages/{page_id}/unregistered.html', headers={'If-None-Match': '*'}).status_code == 403


def test_matching_etag_never_bypasses_unauthorized_user(page_client, monkeypatch):
    app, client, _, page_id = page_client
    url = f'/api/product/v1/pages/{page_id}/index.html'
    etag = client.get(url).headers['etag']
    # A different caller presents the previous user's validator. Membership is
    # checked by the real repository before any 304 can be returned.
    monkeypatch.setattr(app, 'ctx', UserContext(app.ctx.workspace_id, uuid4()))
    response = client.get(url, headers={'If-None-Match': etag})
    assert response.status_code == 403 and 'etag' not in response.headers


def test_matching_etag_never_bypasses_artifact_integrity(page_client, monkeypatch):
    from shuxueshuo_server.product.storage import VerificationResult
    app, client, _, page_id = page_client
    url = f'/api/product/v1/pages/{page_id}/index.html'
    etag = client.get(url).headers['etag']
    monkeypatch.setattr(app.service.storage, 'verify', lambda *_: VerificationResult(False, 'corrupt'))
    response = client.get(url, headers={'If-None-Match': etag})
    assert response.status_code not in (200, 304) and 'etag' not in response.headers
