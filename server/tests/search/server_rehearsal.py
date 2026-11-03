"""Explicit offline adapters and black-box checks; excluded from production images."""

import argparse
import importlib.util
import json
import os
import secrets
import shutil
import ssl
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

FIXTURES = Path('/rehearsal')
DATA = Path('/var/lib/shuxueshuo')
ORIGIN = 'https://shuxueshuo.com'
DEFAULT_LIMITS = {
    'generation_account_daily': 10, 'rerun_account_daily': 3,
    'generation_global_daily': 100, 'rerun_global_daily': 50,
    'generation_account_concurrency': 1, 'generation_workers': 2, 'generation_queue_size': 4,
    'upload_account_limit': 2, 'upload_global_limit': 10,
}


def require_offline():
    if os.getenv('SEARCH_OFFLINE_REHEARSAL') != '1':
        raise RuntimeError('Offline fixture API requires SEARCH_OFFLINE_REHEARSAL=1')


def controls():
    require_offline()
    directory = DATA / 'work/rehearsal-controls'
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def wait_for(predicate, message, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise TimeoutError(message)


def wait_gate(name):
    path = controls() / name
    wait_for(lambda: not path.exists(), 'Offline fixture gate was not released: ' + name, timeout=60)


@contextmanager
def tracked_upload(original, admission, user_id):
    with original(admission, user_id) as lease:
        marker = controls() / f'upload-{user_id}-{uuid4().hex}'
        marker.touch()
        try:
            yield lease
        finally:
            marker.unlink(missing_ok=True)


def forbidden(*_args, **_kwargs):
    raise AssertionError('Offline rehearsal forbids live models and real SMS')


def api():
    require_offline()
    import uvicorn

    from shuxueshuo_server.auth import api as auth_api
    from shuxueshuo_server.auth.sms import MockSms
    from shuxueshuo_server.graph_lesson.stage_one.runner import candidate_features
    from shuxueshuo_server.graph_lesson.stage_two import selection
    from shuxueshuo_server.graph_lesson.stage_two.runner import replay_run
    from shuxueshuo_server.problem_understanding import batch_smoke
    from shuxueshuo_server.problem_understanding.identity import revision
    from shuxueshuo_server.problem_understanding.workflow_ledger import save
    from shuxueshuo_server.search import dev_api, stage_three
    from shuxueshuo_server.search.admission import SearchLimits
    from shuxueshuo_server.search.identity import (
        EXTRACTION_CONTRACT,
        mathematical_candidate,
    )
    from shuxueshuo_server.search.upload_admission import UploadAdmission
    from shuxueshuo_server.solver.extraction import multimodal_provider
    from shuxueshuo_server.solver.extraction.request_guard import (
        check_model_request,
        require_model_request_scope,
    )

    assert asdict(SearchLimits.from_env()) == DEFAULT_LIMITS
    original_admit = UploadAdmission.admit
    UploadAdmission.admit = lambda admission, user_id: tracked_upload(original_admit, admission, user_id)

    def fixture_provider(*_args, **_kwargs):
        require_model_request_scope()
        check_model_request()
        return lambda: object()

    auth_api.AliyunSms = lambda _config: MockSms(DATA / 'work/rehearsal-sms')
    batch_smoke.live_provider_factory = fixture_provider
    selection.live_provider_factory = lambda *_args, **_kwargs: forbidden
    multimodal_provider._default_client_factory = forbidden

    def recognize(png, directory, _provider, *, problem_id, original_png=None, read_graph_details=False):
        wait_gate('generation-hold')
        check_model_request()
        candidate = json.loads((FIXTURES / 'candidate.json').read_text())
        candidate['public_content'] = {
            'completeness': 'complete', 'privacy': 'separated', 'figure': 'not_required',
            'scopes': [{'scope_ref': '/root', 'statement': candidate['original_text'],
                        'choices': [{'target_ref': '/root/goals/0', 'status': 'none',
                                     'selection_mode': 'none', 'options': []}]}],
        }
        projected = mathematical_candidate(candidate)
        features = candidate_features(projected)
        result = {
            'status': 'reviewed_candidate', 'source_reviewed': True, 'output_contract': EXTRACTION_CONTRACT,
            'candidate': projected, 'public_candidate': candidate, 'reviewed_candidate_revision': revision(candidate),
            'question_sha256': sha256(png).hexdigest(), 'sent_image_sha256': [sha256(png).hexdigest()],
            'review_findings': [], 'features': features['features'], 'features_ok': features['ok'],
            'elapsed_seconds': 0, 'offline_fixture': 'synthetic-review-not-model-evidence',
        }
        save(directory / dev_api.RESULT_FILE, result)
        return result

    def classify(directory, *_args, **_kwargs):
        check_model_request()
        output = directory / f'stage-two-{len(stage_three.attempts(directory)) + 1}'
        result = replay_run(FIXTURES / 'recording', output)
        assert result['replay_comparison']['ok'] and result['llm']['new_network_attempts'] == 0
        return result

    dev_api.run_question_image = recognize
    dev_api.run_stage_two = classify
    from shuxueshuo_server.main import app

    uvicorn.run(app, host='0.0.0.0', port=8000, proxy_headers=True,
                forwarded_allow_ips='127.0.0.1', access_log=False)


def ocr():
    require_offline()
    from PIL import Image

    specification = importlib.util.spec_from_file_location('rehearsal_sidecar', FIXTURES / 'sidecar_server.py')
    sidecar = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(sidecar)

    def observe(image, *, auto_orient=True):
        wait_gate('ocr-hold')
        with Image.open(image) as source:
            width, height = source.size
        scale = min(1.0, 1600 / max(width, height))
        width, height = round(width * scale), round(height * scale)
        return {'width': width, 'height': height, 'lines': [], 'layout': [], 'latency_ms': {'detect': 0},
                'orientation': {'status': 'upright' if auto_orient else 'manual', 'rotation_degrees': 0,
                                'predicted_degrees': 0 if auto_orient else None, 'confidence': 1.0}}

    sidecar.warmup = lambda: None
    sidecar.infer_search = observe
    raise SystemExit(sidecar.main())


def client():
    import httpx

    return httpx.Client(base_url=ORIGIN, verify=False, trust_env=False, timeout=180,
                        headers={'Origin': ORIGIN})


def checked(response, code=200):
    assert response.status_code == code, (response.status_code, response.text[:500])
    return response.json()


def login(browser, phone):
    challenge = checked(browser.post('/api/auth/sms/send', json={'phone': phone}))
    message = json.loads((DATA / f"work/rehearsal-sms/{challenge['challenge_id']}.json").read_text())
    response = browser.post('/api/auth/sms/verify', json={
        'phone': phone, 'challenge_id': challenge['challenge_id'], 'code': message['code'],
    })
    checked(response)
    cookie = response.headers['set-cookie'].lower()
    assert '__host-sss_session=' in cookie and 'secure' in cookie and 'httponly' in cookie
    user = checked(browser.get('/api/auth/me'))['user']
    browser.headers['X-Search-User'] = user['id']
    return user


def wait_lesson(browser, search_id):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        detail = checked(browser.get(f'/api/search/problems/{search_id}'))
        if detail['lesson_status'] == 'ready':
            return detail
        assert detail['lesson_status'] not in {'failed', 'unsupported', 'unavailable', 'interrupted'}, detail
        time.sleep(0.5)
    raise TimeoutError('Recorded lesson did not finish')


def database(role='app'):
    from shuxueshuo_server.product.config import Settings
    from shuxueshuo_server.product.db import engine

    return engine(Settings.load('server', instance='search-rehearsal').url(role))


def maintenance(*arguments):
    subprocess.run([sys.executable, '-m', 'shuxueshuo_server.search.maintenance',
                    '--mode', 'server', '--instance', 'search-rehearsal', *arguments], check=True)


def wait_admission_idle(user_id):
    from sqlalchemy import text

    database_engine = database()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with database_engine.connect() as connection:
                remaining = connection.scalar(text(
                    "SELECT count(*) FROM search_admission_tickets WHERE user_id=:user "
                    "AND state IN ('reserved', 'running')"), {'user': user_id})
            if remaining == 0:
                return
            time.sleep(0.05)
        raise TimeoutError('Offline admission tasks did not finish')
    finally:
        database_engine.dispose()


def admission_rows(search_ids=None):
    import sqlalchemy as sa

    from shuxueshuo_server.search.admission import TICKETS

    database_engine = database()
    try:
        statement = sa.select(TICKETS)
        if search_ids is not None:
            statement = statement.where(TICKETS.c.search_id.in_(search_ids))
        with database_engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]
    finally:
        database_engine.dispose()


def seed_consumed(connection, user_id, kind, count, *, now=None):
    from shuxueshuo_server.search.admission import QUOTA_TIMEZONE, TICKETS

    require_offline()
    if kind not in ('generation', 'rerun') or type(count) is not int or count < 0:
        raise ValueError('Invalid offline quota fixture')
    now = now or datetime.now(UTC)
    rows = [{
        'id': uuid4(), 'user_id': UUID(str(user_id)), 'search_id': 'offline-quota-' + uuid4().hex,
        'kind': kind, 'request_id': 'offline-fixture-' + uuid4().hex,
        'quota_day': now.astimezone(QUOTA_TIMEZONE).date(), 'accepted_at': now,
        'state': 'finished', 'consumed': True, 'started_at': now, 'finished_at': now,
        'error_code': 'offline.fixture.preconsumed',
    } for _index in range(count)]
    if rows:
        connection.execute(TICKETS.insert(), rows)
    return count


def fill_quota(user_id, kind, target, *, account=True):
    import sqlalchemy as sa

    from shuxueshuo_server.search.admission import QUOTA_TIMEZONE, TICKETS

    require_offline()
    database_engine = database()
    try:
        with database_engine.begin() as connection:
            statement = sa.select(sa.func.count()).select_from(TICKETS).where(
                TICKETS.c.kind == kind, TICKETS.c.consumed.is_(True),
                TICKETS.c.quota_day == datetime.now(UTC).astimezone(QUOTA_TIMEZONE).date())
            if account:
                statement = statement.where(TICKETS.c.user_id == UUID(str(user_id)))
            existing = connection.scalar(statement)
            assert existing <= target, (kind, existing, target)
            return seed_consumed(connection, user_id, kind, target - existing)
    finally:
        database_engine.dispose()


def exercise_upload_capacity(browsers, users, image, checks):
    gate = controls() / 'ocr-hold'
    gate.touch()
    with ThreadPoolExecutor(max_workers=10) as pool:
        pending = []
        try:
            pending.extend(pool.submit(browsers[0].post, '/api/search/pages', content=image) for _index in range(2))
            wait_for(lambda: len(list(controls().glob(f"upload-{users[0]['id']}-*"))) == 2,
                     'Two account upload slots were not acquired')
            rejected = checked(browsers[0].post('/api/search/pages', content=image), 429)
            assert rejected['detail'] == 'search.upload_busy'
            for browser in browsers[1:5]:
                pending.extend(pool.submit(browser.post, '/api/search/pages', content=image) for _index in range(2))
            wait_for(lambda: len(list(controls().glob('upload-*'))) == 10,
                     'Ten global upload slots were not acquired')
            rejected = checked(browsers[5].post('/api/search/pages', content=image), 429)
            assert rejected['detail'] == 'search.upload_busy'
        finally:
            gate.unlink(missing_ok=True)
        for response in pending:
            checked(response.result(timeout=60))
    wait_for(lambda: not list(controls().glob('upload-*')), 'Upload slots were not released')
    checks.append('real HTTPS upload admission: per-account 2 and global 10; rejected requests do not enter OCR')


def exercise_generation_capacity(browsers, users, pages, checks):
    gate = controls() / 'generation-hold'
    gate.touch()
    search_ids = []
    try:
        for index, browser in enumerate(browsers[:6]):
            request = {'page_id': pages[index]['page_id'], 'box': [0, 0, 1, 1],
                       'client_request_id': 'offline-queue-' + str(index)}
            search_ids.append(checked(browser.post('/api/search/problems', json=request))['search_id'])
        wait_for(lambda: sorted(row['state'] for row in admission_rows(search_ids)) ==
                 ['reserved'] * 4 + ['running'] * 2, 'Expected two running and four waiting tasks')
        for index, expected in ((0, 'search.account_busy'), (6, 'search.queue_full')):
            rejected = checked(browsers[index].post('/api/search/problems', json={
                'page_id': pages[index]['page_id'], 'box': [0, 0, 1, 1],
                'client_request_id': 'offline-full-' + str(index),
            }), 429)
            assert rejected['detail'] == expected
        maintenance('generation-stop')
        rows = admission_rows(search_ids)
        assert sum(row['state'] == 'cancelled' and not row['consumed'] for row in rows) == 4
        assert sum(row['state'] == 'running' and row['consumed'] for row in rows) == 2
    finally:
        gate.unlink(missing_ok=True)
    for user in users[:6]:
        wait_admission_idle(user['id'])
    rows = admission_rows(search_ids)
    assert sum(row['consumed'] for row in rows) == 2
    assert sum(row['state'] == 'cancelled' for row in rows) == 4
    maintenance('generation-enable')
    checks.append('real task admission: account 1, global 2 running + 4 waiting; hot stop cancels four unconsumed reservations')


def exercise():
    from PIL import Image
    from sqlalchemy import text
    from websockets.sync.client import connect

    from shuxueshuo_server.search.admission import SearchLimits
    from shuxueshuo_server.search.repository import SearchRepository

    require_offline()
    assert asdict(SearchLimits.from_env()) == DEFAULT_LIMITS
    checks = []
    with ExitStack() as stack:
        browser, other = stack.enter_context(client()), stack.enter_context(client())
        health = checked(browser.get('/api/health'))
        assert health['accepting'] is True and health['draining'] is False
        assert browser.get('/lab/search/').status_code == 200
        checked(browser.get('/api/search/problems'), 401)
        user = login(browser, '19900000001')
        checks.append('production HTTPS login and secure cookie with fixture-only SMS')
        image = (FIXTURES / 'recording/source.png').read_bytes()
        assert len(image) > 4096
        page = checked(browser.post('/api/search/pages', content=image))
        with Image.new('RGB', (6000, 4000), 'white') as photograph, BytesIO() as encoded:
            photograph.save(encoded, format='JPEG')
            photograph_bytes = encoded.getvalue()
            large_page = checked(browser.post('/api/search/pages', content=photograph_bytes))
        assert (large_page['width'], large_page['height']) == (4096, 2731)
        normalized = DATA / 'work/search/private-v1/pages' / large_page['page_id'] / 'source.png'
        with Image.open(normalized) as source:
            assert source.size == (4096, 2731) and source.mode == 'RGB'
        assert normalized.stat().st_size < 64 * 1024 * 1024
        checks.append('24MP JPEG normalizes before real sidecar path and image validation')
        with Image.new('1', (8000, 4000), 1) as boundary, BytesIO() as encoded:
            boundary.save(encoded, format='PNG')
            boundary_page = checked(browser.post('/api/search/pages', content=encoded.getvalue()))
        assert (boundary_page['width'], boundary_page['height']) == (4096, 2048)
        checks.append('exact 32MP low-bit-depth PNG is accepted and normalized')
        oversized_pixels = bytearray(photograph_bytes)
        frame = oversized_pixels.index(b'\xff\xc0')
        oversized_pixels[frame + 5:frame + 9] = (4000).to_bytes(2, 'big') + (8001).to_bytes(2, 'big')
        with Image.open(BytesIO(oversized_pixels)) as header:
            assert header.size == (8001, 4000)
        rejected = checked(browser.post('/api/search/pages', content=bytes(oversized_pixels)), 413)
        assert rejected['detail'] == 'page.pixels'
        checks.append('above-32MP JPEG header is rejected before decoding or sidecar inference')
        rotated = checked(browser.post(f"/api/search/pages/{page['page_id']}/rotate", json={'degrees': 90}))
        assert rotated['page_id'] != page['page_id']
        checked(browser.post('/api/search/pages', content=image, headers={'Origin': 'https://invalid.example'}), 403)
        oversized = browser.post('/api/search/pages', content=b'x' * (20 * 1024 * 1024 + 1))
        assert oversized.status_code == 413
        request = {'page_id': page['page_id'], 'box': [0, 0, 1, 1], 'client_request_id': 'offline-image-request'}
        rejected = checked(browser.post('/api/search/problems', json=request), 503)
        assert rejected['detail'] == 'search.generation_paused'
        assert not admission_rows()
        maintenance('generation-enable')
        checks.append('production defaults 10/3 account, 100/50 global; expense switch initially closed and explicitly enabled by CLI')
        first = checked(browser.post('/api/search/problems', json=request))['search_id']
        assert checked(browser.post('/api/search/problems', json=request))['search_id'] == first
        ready = wait_lesson(browser, first)
        assert ready['user_id'] == user['id'] and ready['problem_id']
        stream = ready['lesson']['stream']
        assert checked(browser.get(stream['snapshot_url']))['run_id'] == stream['run_id']
        event_response = browser.get(stream['events_url'])
        checked(event_response)
        assert 'no-store' in event_response.headers['cache-control']
        cookie = '; '.join(f'{key}={value}' for key, value in browser.cookies.items())
        path = stream['websocket_url']
        url = path if path.startswith('wss://') else 'wss://shuxueshuo.com' + path
        with connect(url, ssl=ssl._create_unverified_context(), origin=ORIGIN,
                     additional_headers={'Cookie': cookie}, open_timeout=15) as websocket:
            assert websocket.recv(timeout=15)
        checks.append('real sidecar HTTP upload/rotation, request idempotency, recorded lesson and TLS WebSocket')
        wait_admission_idle(user['id'])
        browsers = [stack.enter_context(client()) for _index in range(7)]
        users = [login(current, f'199000000{index + 10:02d}') for index, current in enumerate(browsers)]
        pages = [checked(current.post('/api/search/pages', content=image)) for current in browsers]
        exercise_upload_capacity(browsers, users, image, checks)
        exercise_generation_capacity(browsers, users, pages, checks)
        seeded = {'account_generation': fill_quota(user['id'], 'generation', 9)}
        boundary = checked(browser.post('/api/search/problems', json={
            **request, 'client_request_id': 'account-generation-boundary',
        }))['search_id']
        wait_lesson(browser, boundary)
        wait_admission_idle(user['id'])
        rejected = checked(browser.post('/api/search/problems', json={**request, 'client_request_id': 'over-quota'}), 429)
        assert rejected['detail'] == 'search.daily_generation_limit'
        seeded['account_rerun'] = fill_quota(user['id'], 'rerun', 2)
        rerun = {'client_request_id': 'offline-rerun'}
        checked(browser.post(f'/api/search/problems/{first}/lesson', json=rerun))
        ready = wait_lesson(browser, first)
        wait_admission_idle(user['id'])
        assert checked(browser.post(f'/api/search/problems/{first}/lesson', json=rerun))['duplicate'] is True
        rejected = checked(browser.post(f'/api/search/problems/{first}/lesson',
                                        json={'client_request_id': 'over-rerun-quota'}), 429)
        assert rejected['detail'] == 'search.daily_rerun_limit'
        checks.append('default account limits: last generation 10 and rerun 3 accepted, next rejected; explicit preconsumed offline ledger fixtures')
        seeded['global_generation'] = fill_quota(users[0]['id'], 'generation', 99, account=False)
        global_request = {'page_id': pages[6]['page_id'], 'box': [0, 0, 1, 1],
                          'client_request_id': 'global-generation-boundary'}
        global_search = checked(browsers[6].post('/api/search/problems', json=global_request))['search_id']
        wait_lesson(browsers[6], global_search)
        wait_admission_idle(users[6]['id'])
        rejected = checked(browsers[6].post('/api/search/problems', json={
            **global_request, 'client_request_id': 'over-global-generation',
        }), 429)
        assert rejected['detail'] == 'search.global_generation_limit'
        seeded['global_rerun'] = fill_quota(users[0]['id'], 'rerun', 49, account=False)
        checked(browsers[6].post(f'/api/search/problems/{global_search}/lesson',
                               json={'client_request_id': 'global-rerun-boundary'}))
        wait_lesson(browsers[6], global_search)
        wait_admission_idle(users[6]['id'])
        rejected = checked(browsers[6].post(f'/api/search/problems/{global_search}/lesson',
                                          json={'client_request_id': 'over-global-rerun'}), 429)
        assert rejected['detail'] == 'search.global_rerun_limit'
        checks.append('default global limits: last generation 100 and rerun 50 accepted, next rejected; explicit preconsumed offline ledger fixtures')
        maintenance('generation-stop')
        try:
            rejected = checked(browser.post('/api/search/problems',
                                            json={**request, 'client_request_id': 'paused-request'}), 503)
            assert rejected['detail'] == 'search.generation_paused'
            checked(browser.get(f'/api/search/problems/{first}'))
            checked(browser.get('/api/search/problems'))
        finally:
            maintenance('generation-enable')
        checks.append('operator expense stop rejects generation while preserving private reads')
        login(other, '19900000002')
        checked(other.get(f'/api/search/problems/{first}'), 404)
        assert checked(other.get('/api/search/problems'))['items'] == []
        checks.append('production account isolation and authenticated history')
        draining = DATA / 'locks/services-draining'
        draining.touch()
        try:
            health = checked(browser.get('/api/health'))
            assert health['draining'] is True and health['accepting'] is False
            checked(browser.post('/api/search/pages', content=image), 503)
            checked(browser.post(f'/api/search/problems/{first}/lesson'), 503)
            checked(browser.get(f'/api/search/problems/{first}'))
        finally:
            draining.unlink()
        assert checked(browser.get('/api/health'))['accepting'] is True
        checks.append('draining rejects new work but permits private reads')
        maintenance('disable', ready['problem_id'])
        assert checked(browser.get(f'/api/search/problems/{first}'))['outcome'] == 'disabled'
        deleted = checked(browser.delete(f'/api/search/problems/{first}'))
        assert set(deleted['deleted_search_ids']) == {first, boundary}
        checked(browser.get(f'/api/search/problems/{first}'), 404)
        assert browser.get(page['image_url']).status_code == 200
        checks.append('server operator disable, deletion and source-page retention')
        database_engine = database()
        try:
            repository = SearchRepository(database_engine, DATA / 'work/search/private-v1')
            pending = secrets.token_hex(6)
            directory = repository.storage.path(repository.storage.submission_key(pending))
            directory.mkdir()
            for filename in ('question.png', 'original.png'):
                shutil.copyfile(FIXTURES / 'recording/source.png', directory / filename)
            (directory / 'crop.json').write_text(json.dumps({'page_id': page['page_id']}))
            repository.create_submission(user, pending, page['page_id'], [0, 0, 1, 1], client_request_id='interrupted-fixture')
            with database_engine.connect() as connection:
                assert connection.scalar(text('SELECT count(*) FROM lesson_runs WHERE submission_id=:id'), {'id': first}) == 0
        finally:
            database_engine.dispose()
        migration = database('migration')
        try:
            with migration.begin() as connection:
                connection.execute(text('UPDATE search_pages SET created_at=:created, expires_at=:expired WHERE id=:id'),
                                   {'created': datetime.now(UTC) - timedelta(days=2),
                                    'expired': datetime.now(UTC) - timedelta(days=1), 'id': rotated['page_id']})
        finally:
            migration.dispose()
        maintenance('generation-stop')
        usage = {kind: sum(row['kind'] == kind and row['consumed'] for row in admission_rows())
                 for kind in ('generation', 'rerun')}
        assert usage == {'generation': 100, 'rerun': 50}
        state = {'checks': checks, 'pending': pending, 'expired_page': rotated['page_id'], 'user_id': user['id'],
                 'cookies': dict(browser.cookies.items()), 'usage': usage, 'fixture_seeded_tickets': seeded,
                 'page_id': page['page_id'], 'limits': DEFAULT_LIMITS}
        path = DATA / 'work/rehearsal-state.json'
        path.write_text(json.dumps(state))
        path.chmod(0o600)


def recovery():
    from sqlalchemy import text

    require_offline()
    state = json.loads((DATA / 'work/rehearsal-state.json').read_text())
    with client() as browser:
        browser.cookies.update(state['cookies'])
        browser.headers['X-Search-User'] = state['user_id']
        detail = checked(browser.get('/api/search/problems/' + state['pending']))
        assert detail['recognition_status'] == 'interrupted'
        checked(browser.get(f"/api/search/pages/{state['expired_page']}/image"), 410)
        rejected = checked(browser.post('/api/search/problems', json={
            'page_id': state['page_id'], 'box': [0, 0, 1, 1], 'client_request_id': 'restart-still-paused',
        }), 503)
        assert rejected['detail'] == 'search.generation_paused'
    expired = DATA / 'work/search/private-v1/pages' / state['expired_page']
    assert not expired.exists()
    database_engine = database()
    try:
        with database_engine.connect() as connection:
            assert connection.scalar(text('SELECT image_state FROM search_pages WHERE id=:id'),
                                     {'id': state['expired_page']}) == 'expired'
    finally:
        database_engine.dispose()
    usage = {kind: sum(row['kind'] == kind and row['consumed'] for row in admission_rows())
             for kind in ('generation', 'rerun')}
    assert usage == state['usage'] == {'generation': 100, 'rerun': 50}
    state['checks'].append('expense stop remains closed after API restart; consumed 100/50 ledger survives deletion and restart')
    state['checks'].append('restart recovery, persistent production session and startup expiry cleanup')
    (DATA / 'work/rehearsal-report.json').write_text(json.dumps(state['checks'], ensure_ascii=False, indent=2))
    print(json.dumps({'passed': True, 'checks': state['checks']}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['api', 'ocr', 'exercise', 'recovery'])
    options = parser.parse_args()
    globals()[options.mode]()
