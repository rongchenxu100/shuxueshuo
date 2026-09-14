from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import Barrier

import pytest

from shuxueshuo_server.product.dependency_cache import ReleaseDependencyCache
from shuxueshuo_server.product.errors import Conflict
from shuxueshuo_server.review.dependencies import inventory


@pytest.fixture
def release(tmp_path, monkeypatch):
    monkeypatch.setenv('PRODUCT_MODE', 'server')
    monkeypatch.setenv('PRODUCT_IN_CONTAINER', '1')
    monkeypatch.setenv('PRODUCT_RELEASE_ID', 'test-release')
    code = tmp_path / 'server/shuxueshuo_server/solver/example.py'
    code.parent.mkdir(parents=True)
    code.write_text('value = 1')
    return tmp_path, code


def test_release_reuses_discovery_across_concurrent_requests_without_sharing_mutable_data(release):
    root, _ = release
    cache, calls, barrier = ReleaseDependencyCache(), [], Barrier(4)
    def discover():
        calls.append(1)
        return {'resources': inventory(root)}
    def get(_):
        barrier.wait(timeout=5)
        return cache.get(root, discover)
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(get, range(4)))
    assert len(calls) == 1 and all(r == results[0] for r in results)
    expected = deepcopy(results[0])
    results[0]['resources'].clear()
    assert cache.get(root, discover) == expected
    # Fresh/recovered worker processes must validate independently.
    assert ReleaseDependencyCache().get(root, discover) == expected
    assert len(calls) == 2


@pytest.mark.parametrize('change', ['same_size_mtime', 'add', 'rename', 'remove', 'env_file', 'environment', 'release'])
def test_changes_invalidate_release_snapshot(release, monkeypatch, change):
    root, code = release
    cache, calls = ReleaseDependencyCache(), []
    def discover():
        calls.append(1)
        return {'generation': len(calls)}
    assert cache.get(root, discover)['generation'] == 1
    if change == 'same_size_mtime':
        stat = code.stat()
        code.write_text('value = 2')
        os.utime(code, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    elif change == 'add': code.with_name('new.py').write_text('value = 1')
    elif change == 'rename': code.rename(code.with_name('renamed.py'))
    elif change == 'remove': code.unlink()
    elif change == 'env_file': (root / 'server/.env').write_text('DEEPSEEK_MODEL=other')
    elif change == 'environment': monkeypatch.setenv('DOUBAO_MODEL', 'changed')
    else: monkeypatch.setenv('PRODUCT_RELEASE_ID', 'next-release')
    assert cache.get(root, discover)['generation'] == 2


@pytest.mark.parametrize('key,value', [('PRODUCT_MODE', 'local'), ('PRODUCT_IN_CONTAINER', '0'), ('PRODUCT_RELEASE_ID', '')])
def test_non_release_development_keeps_fresh_discovery(release, monkeypatch, key, value):
    root, _ = release
    monkeypatch.setenv(key, value)
    cache, calls = ReleaseDependencyCache(), []
    def discover(): calls.append(1); return {}
    cache.get(root, discover); cache.get(root, discover)
    assert len(calls) == 2


def test_mid_discovery_change_and_exception_do_not_cache_or_fall_back(release):
    root, code = release
    cache = ReleaseDependencyCache()
    cache.get(root, lambda: {'old': True})
    code.write_text('value = 2')
    def changed(): code.write_text('value = 3'); return {'unsafe': True}
    with pytest.raises(Conflict, match='environment_changed'): cache.get(root, changed)
    def broken(): raise RuntimeError('discovery failed')
    with pytest.raises(RuntimeError): cache.get(root, broken)
    assert cache.get(root, lambda: {'new': True}) == {'new': True}


def test_product_dependencies_keep_inputs_and_live_ocr_outside_cache(release, monkeypatch):
    import json
    from io import BytesIO
    from shuxueshuo_server.product import application, dependency_cache
    from shuxueshuo_server.review.dependencies import KEYS
    root, _ = release
    (root / 'server/uv.lock').write_text('test')
    monkeypatch.setattr(application, 'REPO', root)
    monkeypatch.setattr(dependency_cache, 'REPO', root)
    monkeypatch.setattr(dependency_cache, '_CACHE', ReleaseDependencyCache())
    monkeypatch.setenv('PRODUCT_OCR_URL', 'http://recorded-ocr')
    calls, ocr_calls = [], []
    def discover():
        calls.append(1)
        return {'stages': {k: {'resources': {}, 'config': {'max_attempts': 3} if k == 'solver' else {}} for k in KEYS}}
    monkeypatch.setattr(dependency_cache, 'probe', discover)
    providers = [{'revision': 'one'}]
    def manifests(*a, **kw):
        ocr_calls.append(1)
        return BytesIO(json.dumps({'providers': providers}).encode())
    monkeypatch.setattr(application.urllib.request, 'urlopen', manifests)
    pipeline = {'stages': [{'stage_key': k, 'depends_on': []} for k in KEYS]}
    first = application.dependencies({'sha256': 'image1'}, 'revision1', pipeline)
    second = application.dependencies({'sha256': 'image2'}, 'revision2', pipeline)
    assert first['deployment_version'] == second['deployment_version']
    assert first['dependencies']['extraction']['inputs'] != second['dependencies']['extraction']['inputs']
    providers[0]['revision'] = 'two'
    third = application.dependencies({'sha256': 'image2'}, 'revision2', pipeline)
    assert third['config']['observation'] != second['config']['observation']
    assert len(calls) == 1 and len(ocr_calls) == 3


def test_guard_still_fences_cancellation_and_changed_release_with_cached_discovery(run_context, release, monkeypatch):
    from test_runner import offline_discover
    root, code = release
    app, x, _, _, _ = run_context
    cache, calls = ReleaseDependencyCache(), []
    def discover(): calls.append(1); return inventory(root)
    first = cache.get(root, discover)
    def dependencies(*args):
        current = cache.get(root, discover)
        return {**offline_discover(*args), 'deployment_version': 'offline-runner-v1' if current == first else 'changed'}
    monkeypatch.setattr('shuxueshuo_server.product.execution.dependencies', dependencies)
    x.guard(); x.guard()
    assert len(calls) == 1
    code.write_text('value = 2')
    with pytest.raises(Conflict, match='environment_changed'): x.guard()
    app.service.cancel(app.ctx, x.build['id'])
    with pytest.raises(Conflict): x.guard(code=False)


from test_runner import run_context  # noqa: E402,F401
