from copy import deepcopy
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import pytest

from shuxueshuo_server.product.storage import LocalArtifactStorage
from shuxueshuo_server.product.errors import ProductError, Conflict
from shuxueshuo_server.product.pipelines import V1, validate, PipelineRegistry, affected, reusable


def test_atomic_concurrent_no_overwrite(tmp_path):
    s = LocalArtifactStorage(tmp_path / 'with spaces')
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: s.put_immutable('w/source/a', BytesIO(b'image')), range(8)))
    assert len({r.sha256 for r in results}) == 1
    with pytest.raises(Conflict):
        s.put_immutable('w/source/a', BytesIO(b'changed'))
    assert s.open('w/source/a').read() == b'image'
    assert not list((s.root / '.tmp').iterdir())
    assert s.orphan_report([]) == ['w/source/a']


@pytest.mark.parametrize('key', ['/etc/passwd', '../escape', 'a/../b', 'a//b', 'a\\b', '.tmp/x'])
def test_invalid_key(tmp_path, key):
    with pytest.raises(ProductError):
        LocalArtifactStorage(tmp_path).put_immutable(key, BytesIO(b'x'))


def test_symlink_and_partial_failure(tmp_path):
    root = tmp_path / 'data'
    root.mkdir()
    (root / 'escape').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(OSError):
        LocalArtifactStorage(root).put_immutable('escape/stolen', BytesIO(b'x'))
    class Broken:
        def read(self, size):
            raise OSError('interrupted write')
    with pytest.raises(OSError):
        LocalArtifactStorage(root).put_immutable('incomplete', Broken())
    assert not (root / 'incomplete').exists()
    assert not list((root / '.tmp').iterdir())


def test_pipeline_evolution():
    registry = PipelineRegistry()
    changed = deepcopy(V1)
    changed['stages'].append(dict(stage_key='page_check', title='页面检查', ordinal=10, contract_version='v1', depends_on=['page']))
    changed['completion']['required_stages'].append('page_check')
    registry.register('problem_lesson', 'v2', changed)
    assert len(registry.get('problem_lesson', 'v1')['stages']) == 9
    with pytest.raises(Conflict):
        registry.register('problem_lesson', 'v1', changed)
    assert affected(changed, ['page']) == ['page', 'page_check']
    with pytest.raises(Conflict):
        affected(V1, ['deleted_stage'])
    manifest = dict(inputs={}, resources={}, config={}, upstream={})
    assert reusable(V1, changed, 'source', manifest, manifest)
    changed['stages'][0]['contract_version'] = 'v2'
    assert not reusable(V1, changed, 'source', manifest, manifest)


@pytest.mark.parametrize('change', ['cycle', 'duplicate', 'ordinal', 'completion'])
def test_invalid_pipeline(change):
    snapshot = deepcopy(V1)
    if change == 'cycle': snapshot['stages'][0]['depends_on'] = ['page']
    if change == 'duplicate': snapshot['stages'][1]['stage_key'] = 'source'
    if change == 'ordinal': snapshot['stages'][1]['ordinal'] = 1
    if change == 'completion': snapshot['completion']['required_stages'] = ['missing']
    with pytest.raises(ProductError): validate(snapshot)
