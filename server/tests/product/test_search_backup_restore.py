"""Real PostgreSQL dump/restore rehearsals; no network model or SMS providers."""

import json
import os
import secrets
import shutil
import socket
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
import sqlalchemy as sa
from PIL import Image

from shuxueshuo_server.auth.config import AuthConfig
from shuxueshuo_server.auth.service import AuthError, AuthService
from shuxueshuo_server.auth.sms import MockSms
from shuxueshuo_server.graph_lesson.stage_three.events import EventStore
from shuxueshuo_server.graph_lesson.stage_three.storage import storage_context
from shuxueshuo_server.product import models
from shuxueshuo_server.product.admin import cli, database, native
from shuxueshuo_server.product.admin.backup import backup, restore_data
from shuxueshuo_server.product.admin.search_backup import prune_backups
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import canonical, engine
from shuxueshuo_server.product.errors import Conflict, IntegrityFailure
from shuxueshuo_server.search.admission import SearchAdmission, SearchLimits, TICKETS
from shuxueshuo_server.search.repository import PROBLEMS, SUBMISSIONS, SearchError, SearchRepository


pytestmark = pytest.mark.skipif(os.getenv('RUN_SEARCH_BACKUP_RESTORE_TEST') != '1',
                               reason='Explicit isolated native PostgreSQL backup rehearsal')
NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)


@pytest.fixture
def clusters(tmp_path):
    active, engines = [], []

    def create(name, *, initialized=True):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        settings = Settings.load('local', tmp_path / name, name, port, initialize=True)
        native.start(settings)
        active.append(settings)
        database.bootstrap(settings)
        if initialized:
            database.migrate(settings)
            migration = engine(settings.url('migration'))
            try:
                database.seed(migration)
            finally:
                migration.dispose()
        return settings

    def repository(settings, instant=NOW):
        connection = engine(settings.url())
        engines.append(connection)
        return SearchRepository(connection, settings.root / 'work/search/private-v1', clock=lambda: instant)

    try:
        yield SimpleNamespace(create=create, repository=repository)
    finally:
        for connection in engines:
            connection.dispose()
        for settings in reversed(active):
            native.stop(settings)


def student(repo):
    with repo.db.begin() as connection:
        return connection.scalar(sa.text('SELECT register_student_phone(:phone,:identifier)'),
                                 {'phone': '139' + ''.join(str(secrets.randbelow(10)) for _ in range(8)), 'identifier': uuid4()})


def page(repo, owner, *, parent=None):
    identifier = secrets.token_hex(6)
    directory = repo.storage.path(repo.storage.page_key(identifier))
    directory.mkdir()
    Image.new('RGB', (120, 160), 'white').save(directory / 'page.png')
    (directory / 'ocr.json').write_text('{"fixture":"private OCR"}')
    repo.register_page(owner, identifier, {}, parent_page_id=parent)
    return identifier


def submission(repo, owner, *, source=None, public=None, ready=False):
    identifier = secrets.token_hex(6)
    source = source or page(repo, owner)
    directory = repo.storage.path(repo.storage.submission_key(identifier))
    directory.mkdir()
    for name in ('original.png', 'question.png'):
        Image.new('RGB', (80, 60), 'white').save(directory / name)
    row, _created = repo.create_submission(owner, identifier, source, [0, 0, 1, 1], client_request_id=uuid4().hex)
    if public:
        repo.link_identity(identifier, public)
    if ready:
        for name in ('result.json', 'crop.json', 'stage-two-1/stage-two-result.json',
                     'stage-two-1/stage-three/frozen.json', 'stage-two-1/stage-three/stage-three-result.json'):
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{}')
        identity = {'run_id': uuid4().hex, 'lesson_version': 'offline-backup-fixture',
                    'input_sha256': 'a' * 64, 'revisions': {'fixture': 'b' * 64}}
        output = directory / 'stage-two-1/stage-three'
        (output / 'run.json').write_text(json.dumps(identity))
        with storage_context(repo.db, identifier, clock=repo.clock):
            EventStore(output, identity, create=True)
        repo.set_state(identifier, lesson_status='ready')
    return repo.submission(owner, row['id'])


def identity():
    value = {'identity_version': 1, 'stem': 'fixture ' + uuid4().hex}
    return {'identity_version': 1, 'fingerprint': sha256(canonical(value).encode()).hexdigest(),
            'identity': value, 'statement': '已知 x > 0，求解。', 'structured_problem': {'condition': 'x > 0'}}


def missing(repo, owner, identifier):
    with pytest.raises(SearchError) as rejected:
        repo.submission(owner, identifier)
    assert rejected.value.status == 404


def role_login(settings):
    with psycopg.connect(database.dsn(settings.url('bootstrap'))) as connection:
        return connection.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname='product_app'").fetchone()[0]


def test_restore_preserves_consumed_admission_quota_releases_queue_and_closes_generation(clusters):
    settings = clusters.create('quota-source')
    repo = clusters.repository(settings)
    first, second = student(repo), student(repo)
    first_row, second_row = submission(repo, first), submission(repo, second)
    admission = SearchAdmission(repo.db, config=SearchLimits(generation_account_daily=1), clock=repo.clock)
    admission.set_generation_enabled(True)
    running = admission.reserve(first, 'generation', first_row['id'], request_id='started')
    queued = admission.reserve(second, 'generation', second_row['id'], request_id='queued')
    admission.start(running.id)
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    manifest = json.loads((Path(saved['backup']) / 'manifest.json').read_text())
    assert manifest['counts']['search_admission_tickets'] == 2
    restored = clusters.create('quota-target', initialized=False)
    result = restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW + timedelta(minutes=1))
    assert result['search']['admission_recovered'] == {'cancelled': 0, 'interrupted': 1}
    recovered = clusters.repository(restored, NOW + timedelta(minutes=1))
    limits = SearchAdmission(recovered.db, config=admission.config, clock=recovered.clock)
    assert not limits.generation_enabled()
    assert limits.ticket_states([running.id, queued.id]) == {running.id: 'interrupted', queued.id: 'cancelled'}
    with recovered.db.connect() as connection:
        rows = {str(row.id): row for row in connection.execute(sa.select(TICKETS))}
    assert rows[running.id].consumed and not rows[queued.id].consumed
    limits.set_generation_enabled(True)
    with pytest.raises(SearchError, match='search.daily_generation_limit'):
        limits.reserve(first, 'generation', first_row['id'])
    assert limits.reserve(second, 'generation', second_row['id']).created


def test_pre_admission_v2_backup_upgrades_and_starts_with_generation_closed(clusters):
    settings = clusters.create('previous-source')
    repo = clusters.repository(settings)
    owner = student(repo)
    original = submission(repo, owner)
    repo.db.dispose()
    migration = engine(settings.url('migration'))
    try:
        with migration.begin() as connection:
            connection.exec_driver_sql('DROP TABLE search_admission_tickets, search_admission_control')
            connection.exec_driver_sql("UPDATE alembic_version SET version_num = '0015_search_recovery'")
    finally:
        migration.dispose()
    saved = backup(settings, now=NOW)
    restored = clusters.create('previous-target', initialized=False)
    assert restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW)['ok']
    recovered = clusters.repository(restored)
    assert recovered.submission(owner, original['id'])['id'] == original['id']
    assert not SearchAdmission(recovered.db).generation_enabled()
    with recovered.db.connect() as connection:
        assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == '0017_knowledge_collections'
        assert connection.scalar(sa.select(sa.func.count()).select_from(TICKETS)) == 0


def test_snapshot_delete_restore_isolated_ready_course_and_new_authority(clusters):
    settings = clusters.create('source')
    repo = clusters.repository(settings)
    first, second = student(repo), student(repo)
    source_page = page(repo, first)
    rotated = page(repo, first, parent=source_page)
    shared = identity()
    deleted = submission(repo, first, source=source_page, public=shared, ready=True)
    duplicate = submission(repo, first, source=rotated, public=shared, ready=True)
    neighbor = submission(repo, first, source=source_page, public=identity(), ready=True)
    other_user = submission(repo, second, public=shared, ready=True)
    queued = submission(repo, first, source=source_page)
    repo.set_state(queued['id'], recognition_status='running', lesson_status='running')
    config = AuthConfig(mode='mock', environment='test', origin='https://testserver', secret='fixture-secret-' * 4)
    auth = AuthService(repo.db, config, MockSms(), clock=lambda: NOW)
    challenge = auth.send('13800001234', 'offline-fixture')
    _logged_in, token = auth.verify('13800001234', UUID(challenge['challenge_id']),
                                    auth.sms.messages[challenge['challenge_id']][1], 'offline-fixture')
    assert auth.current_user(token)
    unused_challenge = auth.send('13800001235', 'offline-unused-fixture')
    unused_code = auth.sms.messages[unused_challenge['challenge_id']][1]
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    removed = repo.delete(first, deleted['id'])
    assert set(removed['deleted_search_ids']) == {deleted['id'], duplicate['id']}
    repo.cleanup()
    assert repo.page(first, source_page)['expires_at'] == repo.page(first, rotated)['expires_at'] == NOW + timedelta(hours=24)
    reshot = submission(repo, first, source=source_page, public=shared, ready=True)
    journal_before = repo.recovery.path.read_bytes()
    source_authority = repo.recovery.snapshot().authority_id
    repo.db.dispose()
    restored = clusters.create('restored', initialized=False)
    result = restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW + timedelta(minutes=1))
    assert result['ok'] and set(result['search']['deleted_search_ids']) == {deleted['id'], duplicate['id']}
    assert role_login(restored)
    recovered = clusters.repository(restored, NOW + timedelta(minutes=1))
    for row in (deleted, duplicate, reshot):
        missing(recovered, first, row['id'])
        assert not recovered.storage.path(row['storage_key']).exists()
    missing(recovered, second, neighbor['id'])
    assert recovered.submission(second, other_user['id'])['lesson_status'] == 'ready'
    assert recovered.submission(first, neighbor['id'])['lesson_status'] == 'ready'
    assert next(item for item in recovered.history(first)['items'] if item['search_id'] == neighbor['id'])['lesson_available']
    assert recovered.page(first, source_page)['expires_at'] == NOW + timedelta(hours=24)
    assert recovered.page(first, rotated)['expires_at'] == NOW + timedelta(hours=24)
    interrupted = recovered.submission(first, queued['id'])
    assert interrupted['recognition_status'] == interrupted['lesson_status'] == 'interrupted'
    output = recovered.storage.path(neighbor['storage_key']) / 'stage-two-1/stage-three'
    with storage_context(recovered.db, neighbor['id'], clock=recovered.clock):
        restored_store = EventStore(output, json.loads((output / 'run.json').read_text()))
        assert restored_store.events() == []
    with recovered.db.connect() as connection:
        assert connection.scalar(sa.select(sa.func.count()).select_from(models.lesson_runs)) == 2
        assert connection.scalar(sa.select(sa.func.count()).select_from(models.metadata.tables['lesson_metadata'])) == 8
        assert connection.scalar(sa.select(sa.func.count()).select_from(PROBLEMS)) == 2
    restored_auth = AuthService(recovered.db, config, MockSms(), clock=lambda: NOW + timedelta(minutes=1))
    assert restored_auth.current_user(token) is None
    with pytest.raises(AuthError):
        restored_auth.verify('13800001235', UUID(unused_challenge['challenge_id']), unused_code, 'offline-unused-fixture')
    assert recovered.recovery.snapshot().authority_id != source_authority
    assert repo.recovery.path.read_bytes() == journal_before
    recovered.db.dispose()
    second_backup = backup(settings, now=NOW + timedelta(minutes=1))
    second_restore = clusters.create('reshot', initialized=False)
    restore_data(second_restore, second_backup['backup'], search_recovery_root=repo.root, now=NOW + timedelta(minutes=2))
    latest = clusters.repository(second_restore, NOW + timedelta(minutes=2))
    assert latest.submission(first, reshot['id'])['lesson_status'] == 'ready'
    missing(latest, first, deleted['id'])


@pytest.mark.parametrize('elapsed', [timedelta(hours=24), timedelta(days=30)])
def test_restore_original_expiry_boundaries_without_retention_extension(clusters, elapsed):
    settings = clusters.create('source')
    repo = clusters.repository(settings)
    owner = student(repo)
    source_page = page(repo, owner)
    rotated = page(repo, owner, parent=source_page)
    linked = submission(repo, owner, source=source_page, public=identity(), ready=True)
    unlinked = submission(repo, owner, source=rotated)
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    if elapsed == timedelta(hours=24):
        pruned = prune_backups(settings, now=NOW + elapsed)
        assert pruned['pruned_search_files'] == 4 and not pruned['failures']
    restored = clusters.create('restored', initialized=False)
    restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW + elapsed)
    recovered = clusters.repository(restored, NOW + elapsed)
    for identifier in (source_page, rotated):
        assert recovered.page(owner, identifier, require_image=False)['image_state'] == 'expired'
        assert not recovered.storage.path(recovered.storage.page_key(identifier)).exists()
        with pytest.raises(SearchError) as rejected:
            recovered.page(owner, identifier)
        assert rejected.value.status == 410
    if elapsed == timedelta(days=30):
        expired = recovered.submission(owner, linked['id'])
        assert expired['lesson_status'] == expired['artifact_state'] == 'expired'
        assert expired['statement'] == '已知 x > 0，求解。'
        missing(recovered, owner, unlinked['id'])
        assert not recovered.storage.path(linked['storage_key']).exists()
        with recovered.db.connect() as connection:
            assert connection.scalar(sa.select(sa.func.count()).select_from(models.lesson_runs)) == 0
            assert connection.scalar(sa.select(sa.func.count()).select_from(models.metadata.tables['lesson_metadata'])) == 0
    else:
        assert recovered.submission(owner, linked['id'])['lesson_status'] == 'ready'
        assert recovered.submission(owner, unlinked['id'])['recognition_status'] == 'interrupted'


@pytest.mark.parametrize('failure', ['missing_journal', 'corrupt_journal', 'wrong_authority', 'stale_journal',
                                    'corrupt_dump', 'missing_private_file', 'legacy_search_backup',
                                    'omitted_required_entry', 'wrong_required_hash'])
def test_restore_validation_failure_stays_fenced_and_resume_cannot_bypass(clusters, tmp_path, failure):
    settings = clusters.create('source')
    repo = clusters.repository(settings)
    owner = student(repo)
    row = submission(repo, owner, public=identity(), ready=True)
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    source = Path(saved['backup'])
    authority = repo.root
    if failure == 'missing_journal':
        authority = None
    elif failure in {'corrupt_journal', 'wrong_authority', 'stale_journal'}:
        authority = tmp_path / 'independent-authority'
        shutil.copytree(repo.root / 'recovery', authority / 'recovery')
        journal = authority / 'recovery/deletions.jsonl'
        if failure == 'corrupt_journal':
            journal.write_text('{invalid\n')
        elif failure == 'wrong_authority':
            header = {'schema_version': 'search-deletions/v1', 'authority_id': str(uuid4()), 'sequence': 0}
            journal.write_text(canonical({**header, 'digest': sha256(canonical(header).encode()).hexdigest()}) + '\n')
        else:
            repo.delete(owner, row['id'])
            repo.db.dispose()
            source = Path(backup(settings, now=NOW)['backup'])
    elif failure == 'corrupt_dump':
        with (source / 'database.dump').open('ab') as stream:
            stream.write(b'corrupt')
    elif failure == 'missing_private_file':
        (source / 'search' / row['storage_key'] / 'question.png').unlink()
    elif failure == 'legacy_search_backup':
        manifest = json.loads((source / 'manifest.json').read_text())
        manifest['schema_version'] = 'product-backup/v1'
        (source / 'manifest.json').write_text(json.dumps(manifest))
    else:
        manifest = json.loads((source / 'manifest.json').read_text())
        key = row['storage_key'] + '/question.png'
        path = source / 'search' / key
        if failure == 'omitted_required_entry':
            manifest['search_files'] = [entry for entry in manifest['search_files'] if entry['storage_key'] != key]
            path.unlink()
        else:
            content = b'not the database registered crop'
            path.write_bytes(content)
            entry = next(entry for entry in manifest['search_files'] if entry['storage_key'] == key)
            entry.update(sha256=sha256(content).hexdigest(), size_bytes=len(content))
        (source / 'manifest.json').write_text(json.dumps(manifest))
    restored = clusters.create('refused', initialized=False)
    with pytest.raises((IntegrityFailure, SearchError)):
        restore_data(restored, source, search_recovery_root=authority, now=NOW)
    assert not role_login(restored)
    assert (restored.root / 'locks/restore-incomplete').is_file()
    with pytest.raises(Conflict, match='restore'):
        cli.execute(restored, SimpleNamespace(command='resume'))
    assert not role_login(restored)


def test_backup_rejects_live_application_connections_and_reopens_admission(clusters):
    settings = clusters.create('source')
    app = engine(settings.url())
    try:
        with app.connect() as connection:
            connection.execute(sa.text('SELECT 1'))
            with pytest.raises(Conflict, match='stop_application_connections_first'):
                backup(settings, now=NOW)
        assert role_login(settings)
    finally:
        app.dispose()


def test_restore_copy_failure_after_database_import_cannot_open_target(clusters, monkeypatch):
    from shuxueshuo_server.product.admin import backup as backup_module

    settings = clusters.create('source')
    repo = clusters.repository(settings)
    submission(repo, student(repo), public=identity(), ready=True)
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    restored = clusters.create('refused', initialized=False)
    reached = []

    def fail_copy(*_args, **_kwargs):
        assert not role_login(restored)
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(database.dsn(restored.url()))
        migration = engine(restored.url('migration'))
        try:
            with migration.connect() as connection:
                assert connection.scalar(sa.select(sa.func.count()).select_from(SUBMISSIONS)) == 1
        finally:
            migration.dispose()
        reached.append(True)
        raise OSError('offline injected copy failure')

    monkeypatch.setattr(backup_module, 'restore_search_files', fail_copy)
    with pytest.raises(OSError, match='injected copy failure'):
        restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW)
    assert reached == [True] and not role_login(restored)
    with pytest.raises(Conflict, match='restore'):
        cli.execute(restored, SimpleNamespace(command='resume'))


def test_restore_pending_cleanup_failure_cannot_open_target(clusters, monkeypatch):
    settings = clusters.create('source')
    repo = clusters.repository(settings)
    owner = student(repo)
    row = submission(repo, owner, public=identity(), ready=True)
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    repo.delete(owner, row['id'])
    repo.db.dispose()
    restored = clusters.create('refused', initialized=False)
    real_cleanup = SearchRepository.cleanup

    def incomplete_cleanup(current):
        if current.root == restored.root / 'work/search/private-v1':
            return {'removed': 0, 'orphans_removed': 0}
        return real_cleanup(current)

    monkeypatch.setattr(SearchRepository, 'cleanup', incomplete_cleanup)
    with pytest.raises(IntegrityFailure, match='search_cleanup_incomplete'):
        restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW)
    assert not role_login(restored)
    with pytest.raises(Conflict, match='restore'):
        cli.execute(restored, SimpleNamespace(command='resume'))


def test_recorded_q01_course_http_reads_after_restore_without_original_paths(clusters):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from shuxueshuo_server.auth.api import cookie_name
    from shuxueshuo_server.graph_lesson.stage_two.runner import replay_run
    from shuxueshuo_server.problem_understanding.workflow_ledger import save
    from shuxueshuo_server.search import dev_api, stage_three
    from tests.search.test_lesson import search_result
    from tests.solver.test_graph_stage_three_recorded import Q01_SELECTION

    settings = clusters.create('recorded-source')
    repo = clusters.repository(settings)
    config = AuthConfig(mode='mock', environment='test', origin='https://testserver', secret='recorded-backup-' * 4)
    source_auth = AuthService(repo.db, config, MockSms(), clock=lambda: NOW)
    challenge = source_auth.send('13800009999', 'offline-recorded-source')
    owner, _source_token = source_auth.verify('13800009999', UUID(challenge['challenge_id']),
                                             source_auth.sms.messages[challenge['challenge_id']][1], 'offline-recorded-source')
    page_id, search_id = secrets.token_hex(6), secrets.token_hex(6)
    directory = repo.storage.path(repo.storage.submission_key(search_id))
    directory.mkdir()
    save(directory / dev_api.RESULT_FILE, {**search_result('q01'), 'question_sha256': 'recorded', 'sent_image_sha256': ['recorded']})
    save(directory / 'crop.json', {'page_id': page_id})
    replay = replay_run(Q01_SELECTION, directory / 'stage-two-1')
    assert replay['replay_comparison']['ok']
    assert replay['llm']['new_semantic_calls'] == replay['llm']['new_network_attempts'] == 0
    shutil.copyfile(directory / 'stage-two-1/source.png', directory / 'question.png')
    shutil.copyfile(directory / 'question.png', directory / 'original.png')
    page_directory = repo.storage.path(repo.storage.page_key(page_id))
    page_directory.mkdir()
    shutil.copyfile(directory / 'question.png', page_directory / 'page.png')
    repo.register_page(owner, page_id, {})
    repo.create_submission(owner, search_id, page_id, [0, 0, 1, 1])
    repo.set_state(search_id, recognition_status='reviewed', lesson_status='running')
    output = directory / 'stage-two-1/stage-three'
    with storage_context(repo.db, search_id, clock=repo.clock):
        result = stage_three.run_stage_three(directory / 'stage-two-1')
        assert result['status'] == 'completed'
        assert result['llm']['new_semantic_calls'] == result['llm']['new_network_attempts'] == 0
        expected_snapshot = stage_three.open_store(output).snapshot()
        expected_events = stage_three.event_page(output, 0)
        expected_presentation = stage_three.presentation(directory, search_id)
    assert expected_snapshot['math_steps'] and expected_events['events']
    assert expected_presentation['execution_status'] == 'completed'
    repo.set_state(search_id, lesson_status='ready')
    assert repo.submission(owner, search_id)['problem_id'] is None
    repo.db.dispose()
    saved = backup(settings, now=NOW)
    manifest = json.loads((Path(saved['backup']) / 'manifest.json').read_text())
    assert not any(entry['storage_key'].endswith('.lock') for entry in manifest['search_files'])
    (repo.root / 'submissions').rename(settings.root / 'work/quarantined-original-submissions')
    restored = clusters.create('recorded-restored', initialized=False)
    assert restore_data(restored, saved['backup'], search_recovery_root=repo.root, now=NOW + timedelta(minutes=1))['ok']
    recovered = clusters.repository(restored, NOW + timedelta(minutes=1))
    auth = AuthService(recovered.db, config, MockSms(), clock=recovered.clock)
    challenge = auth.send('13800009999', 'offline-recorded-restored')
    restored_owner, token = auth.verify('13800009999', UUID(challenge['challenge_id']),
                                      auth.sms.messages[challenge['challenge_id']][1], 'offline-recorded-restored')
    assert restored_owner['id'] == owner['id']
    app = FastAPI()
    app.state.student_auth = auth
    app.state.search_repository = recovered
    app.include_router(dev_api.create_search_router(recovered.root))
    with TestClient(app, base_url=config.origin, headers={'Origin': config.origin}) as client:
        client.cookies.set(cookie_name(config), token)
        response = client.get(f'/api/search/problems/{search_id}')
        assert response.status_code == 200, response.text
        lesson = response.json()['lesson']
        assert lesson['execution_status'] == 'completed' and lesson['goals']
        assert lesson['stream'] == expected_presentation['stream']
        stream = lesson['stream']
        snapshot = client.get(stream['snapshot_url'])
        events = client.get(stream['events_url'], params={'after_seq': 0})
        assert snapshot.status_code == events.status_code == 200
        assert snapshot.json() == expected_snapshot
        assert events.json() == expected_events
        assert snapshot.headers['Cache-Control'] == events.headers['Cache-Control'] == 'no-store'
        assert client.get('/api/search/problems').json()['items'][0]['lesson_available']
        assert client.get(f'/api/search/problems/{search_id}').json()['lesson'] == lesson
    assert not directory.exists()
