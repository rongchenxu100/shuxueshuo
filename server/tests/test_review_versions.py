from io import BytesIO
import json

from PIL import Image
import pytest

from shuxueshuo_server.review.store import ReviewStore
from shuxueshuo_server.review.versions import Versions, Conflict


def create(store, parent=None, enqueue=True):
    out = BytesIO()
    Image.new('RGB', (2, 2)).save(out, format='PNG')
    return store.create(out.getvalue(), 'image/png', 'p.png', parent_run_id=parent, enqueue=enqueue)['id']


def test_chain_identity_and_prepare_does_not_replace_latest(tmp_path):
    store = ReviewStore(tmp_path)
    a = create(store)
    versions = Versions(store)
    b = create(store, a, enqueue=False)
    assert versions.info(b)['id'] == versions.info(a)['id']
    assert versions.info(b)['latest_run_id'] == a
    c = create(store)
    assert versions.info(c)['id'] != versions.info(a)['id']
    versions.enqueue(b, base_revision_id=None, target={'stages': {}})
    assert versions.info(a)['latest_run_id'] == b


def test_revision_cas_noop_and_publication_race(tmp_path):
    store = ReviewStore(tmp_path)
    a = create(store)
    versions = Versions(store)
    store.add(a, 'extraction', 'output', 'VerifiedProblem', {'graph': {}, 'semantic_hash': 'first'})
    versions.capture(a)
    original = versions.info(a)['revision_id']
    assert versions.save(a, original, {'semantic_hash': 'first'})['id'] == original
    new = versions.save(a, original, {'semantic_hash': 'second'})
    with pytest.raises(Conflict): versions.save(a, original, {'semantic_hash': 'third'})
    b = create(store, a, enqueue=False)
    with pytest.raises(Conflict): versions.enqueue(b, base_revision_id=original, target={})
    target = {'stages': {s['id']: {'resources': {}, 'config': {}} for s in store.get(a)['stages']}}
    versions.enqueue(b, base_revision_id=new['id'], target=target)
    # A cannot publish after B is requested, even with matching dependencies.
    for run in (a, b):
        with store.edit(run) as doc:
            doc['target_dependencies'] = target
            doc['status'] = 'succeeded'
            for s in doc['stages']: s['manifest'] = {'resources': {}, 'config': {}}
        assert versions.info(a)['page_run_id'] == (None if run == a else b)
    # A new draft invalidates B without altering any historical run.
    old_doc = store.get(b)
    versions.save(b, new['id'], {'semantic_hash': 'third'})
    assert store.get(b) == old_doc


def test_migrate_legacy_without_rewriting_history(tmp_path):
    store = ReviewStore(tmp_path)
    a = create(store)
    b = create(store, a)
    old = store.get(a)
    with store.connect() as db:
        db.execute('DELETE FROM review_run_versions')
        db.execute('DELETE FROM review_subjects')
    versions = Versions(store)
    assert versions.info(a)['id'] == versions.info(b)['id']
    assert store.get(a) == old
    assert versions.info(b)['page_run_id'] is None
