import copy
import json
from pathlib import Path

import pytest

from shuxueshuo_server.review import dependencies as deps
from shuxueshuo_server.review.rebuild import plan, submit, BuildGuard
from shuxueshuo_server.review.problem_edit import preview, editable
from shuxueshuo_server.review.versions import Versions, Conflict
from shuxueshuo_server.review.store import ReviewStore, REPO
from test_review_versions import create


def seed(store):
    from shuxueshuo_server.solver.extraction.problem_domain import ProblemDraft, ProblemPromotionService
    from shuxueshuo_server.solver.extraction.problem_domain_validation import ProblemDomainValidator
    run = create(store)
    store.claim()
    raw = json.loads((REPO / 'internal/problem-domain-fixtures/tj-2026-hexi-yimo-25.json').read_text())
    result = ProblemDomainValidator().validate(ProblemDraft.create(raw))
    assert result.ok
    verified = ProblemPromotionService().promote(result.draft)
    store.add(run, 'extraction', 'output', 'VerifiedProblem', verified.to_payload())
    store.finish(run, error='fixture stop')
    return run


def test_human_preview_save_noop_invalid_and_stale(tmp_path):
    store = ReviewStore(tmp_path)
    run = seed(store)
    body = editable(store, run)
    old = store.get(run)
    result = preview(store, run, body, save=True)
    assert result['ok'] and not result['affected_stages']
    assert result['base_revision_id'] == body['base_revision_id']
    invalid = {**body, 'domain': {**body['domain'], 'family_id': 'unknown-family'}}
    assert not preview(store, run, invalid, save=True)['ok']
    assert editable(store, run)['base_revision_id'] == body['base_revision_id']
    modified = copy.deepcopy(body)
    modified['domain']['root']['source_text'][0] += '（人工校对）'
    saved = preview(store, run, modified, save=True)
    assert saved['ok'] and saved['affected_stages'][0] == 'extraction'
    assert saved['base_revision_id'] != body['base_revision_id']
    with pytest.raises(Conflict): preview(store, run, body, save=True)
    assert store.get(run) == old
    assert len(store.list()) == 1  # saving never schedules paid work


def test_unknown_old_manifest_and_stale_plan(tmp_path, monkeypatch):
    store = ReviewStore(tmp_path)
    run = seed(store)
    snap = deps.probe()
    monkeypatch.setattr(deps, 'probe', lambda: snap)
    previewed = plan(store, run, 'page')
    assert previewed['rerun_stages'][0] == 'source'
    assert previewed['page_validity'] == 'unknown'
    changed = copy.deepcopy(snap)
    changed['stages']['page']['config']['test'] = True
    monkeypatch.setattr(deps, 'probe', lambda: changed)
    with pytest.raises(Conflict): submit(store, run, previewed)
    assert len(store.list()) == 1


def test_manual_revision_changes_plan_without_extraction_llm(tmp_path):
    store = ReviewStore(tmp_path)
    run = seed(store)
    body = editable(store, run)
    body['domain']['root']['source_text'][0] += '（人工校对）'
    assert preview(store, run, body, save=True)['ok']
    result = plan(store, run)
    assert any(r['code'] == 'build.problem_changed' for r in result['reasons'])
    assert 'extraction' not in result['model_stages']
    assert 'solver' in result['model_stages']


def test_guard_detects_inflight_change_and_saves_evidence(tmp_path, monkeypatch):
    store = ReviewStore(tmp_path)
    run = create(store)
    store.claim()
    snap = deps.probe()
    monkeypatch.setattr(deps, 'probe', lambda: snap)
    guard = BuildGuard(store, run)
    changed = copy.deepcopy(snap)
    changed['stages']['visual']['resources']['test-spec'] = 'changed'
    monkeypatch.setattr(deps, 'probe', lambda: changed)
    with pytest.raises(ValueError, match='build.source_changed'): guard.complete('source')
    assert store.get(run)['artifacts'][-1]['name'] == '构建依赖变化证据'
    assert not store.get(run)['page_url']


def test_revision_routes_keep_read_preview_and_save_separate(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from shuxueshuo_server.review.api import router
    store = ReviewStore(tmp_path)
    run = seed(store)
    app = FastAPI()
    app.state.review_store = store
    app.include_router(router)
    client = TestClient(app)
    url = '/api/review/runs/' + run
    body = client.get(url + '/problem').json()
    assert 'verification_proof' not in body['domain']
    assert 'runtime' not in body['domain']
    assert client.post(url + '/problem/preview', json=body).json()['ok']
    assert client.post(url + '/problem/revisions', json={**body, 'base_revision_id': 'old'}).status_code == 409
    assert client.post(url + '/rebuild', json={'fingerprint': 'old'}).status_code == 409
    assert len(store.list()) == 1
    assert client.get(url + '/problem', headers={'Origin': 'https://example.com'}).status_code == 403
    assert client.post(url + '/problem/revisions', json=body, headers={'Origin': 'https://example.com'}).status_code == 403


def test_noop_semantic_reordering_does_not_invalidate(tmp_path):
    store = ReviewStore(tmp_path)
    run = seed(store)
    body = editable(store, run)
    body['domain']['root']['entities'].reverse()
    saved = preview(store, run, body, save=True)
    assert saved['ok']
    assert saved['base_revision_id'] == body['base_revision_id']
    assert not saved['affected_stages']
