"""PostgreSQL authority for private search access, history and lifecycle."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from PIL import Image
from sqlalchemy.dialects.postgresql import insert

from ..product.db import transaction
from ..product.models import metadata
from .admission import ACTIVE, TICKETS, SearchAdmission
from .recovery import STATE, RecoveryJournal, entry_key
from .storage import SearchError, SearchStorage

PROBLEMS = metadata.tables['search_problems']
PAGES = metadata.tables['search_pages']
SUBMISSIONS = metadata.tables['search_submissions']
RELATIONS = metadata.tables['student_search_problems']
UNLINKED_SUMMARIES = {
    'queued': '等待识别的题目',
    'running': '识别中的题目',
    'reviewed': '已识别的题目',
    'needs_confirmation': '待确认的题目',
    'failed': '识别失败的题目',
    'interrupted': '识别已中断的题目',
}


def user_uuid(user):
    return UUID(str(user['id'] if isinstance(user, dict) else user))


class _LinkExpired(Exception):
    pass


class SearchRepository:
    def __init__(self, db, root, *, clock=None, initialize_recovery=True, admission_disabled=False,
                 admission_config=None):
        self.db = db
        self.storage = SearchStorage(root)
        self.root = self.storage.root
        self.clock = clock or (lambda: datetime.now(UTC))
        self.admission = None if admission_disabled else SearchAdmission(
            db, config=admission_config, clock=self.clock)
        self.recovery = RecoveryJournal(self.root)
        if initialize_recovery:
            self.recovery.initialize(db)

    def lifecycle_lock(self, search_id, *, blocking=False):
        return self.storage.lifecycle_lock(search_id, blocking=blocking)

    def _page(self, connection, user, page_id, *, locked=False, require_image=False):
        self.recovery.validate_state(connection)
        statement = sa.select(PAGES).where(PAGES.c.id == page_id, PAGES.c.user_id == user_uuid(user))
        if locked:
            statement = statement.with_for_update()
        value = connection.execute(statement).mappings().first()
        if value is None:
            raise SearchError('page.not_found', 404)
        value = dict(value)
        if value['expires_at'] <= self.clock():
            value['image_state'] = 'expired'
        if require_image and value['image_state'] != 'active':
            raise SearchError('page.expired', 410)
        value['path'] = self.storage.path(value['storage_key'])
        return value

    def page(self, user, page_id, *, require_image=True):
        with transaction(self.db) as connection:
            return self._page(connection, user, page_id, require_image=require_image)

    def _decorate(self, connection, row, *, deletion_snapshot=None):
        deleted = (self.recovery.is_deleted(connection, row) if deletion_snapshot is None
                   else entry_key(row) in deletion_snapshot.deleted_keys)
        if deleted:
            raise SearchError('search.not_found', 404)
        value = dict(row)
        value['search_id'] = value['id']
        value['path'] = self.storage.path(value['storage_key'])
        if value['expires_at'] <= self.clock():
            value['artifact_state'] = 'expired'
            value['lesson_status'] = 'expired'
        value['image_state'] = value['artifact_state']
        value['problem_status'] = None
        value['statement'] = None
        if value['problem_id']:
            problem = connection.execute(sa.select(PROBLEMS).where(PROBLEMS.c.id == value['problem_id'])).mappings().one()
            value['problem_status'] = problem['status']
            value['statement'] = problem['statement'] if problem['status'] == 'active' else None
        if (value['lesson_status'] == 'ready' and value['artifact_state'] == 'active'
                and value['problem_status'] != 'disabled' and not self.lesson_artifacts_available(value)):
            value['lesson_status'] = 'unavailable'
        return value

    def submission(self, user, search_id, *, require_artifacts=False):
        with transaction(self.db) as connection:
            row = connection.execute(sa.select(SUBMISSIONS).where(
                SUBMISSIONS.c.id == search_id, SUBMISSIONS.c.user_id == user_uuid(user))).mappings().first()
            if row is None or (row['problem_id'] is None and row['expires_at'] <= self.clock()):
                raise SearchError('search.not_found', 404)
            value = self._decorate(connection, row)
            if require_artifacts:
                if value['problem_status'] == 'disabled':
                    raise SearchError('problem.disabled', 410)
                if value['artifact_state'] != 'active':
                    raise SearchError('search.expired', 410)
            return value

    def register_page(self, user, page_id, metadata, *, parent_page_id=None):
        key = self.storage.page_key(page_id)
        digest = self.storage.digest(key + '/page.png')
        with Image.open(self.storage.path(key + '/page.png')) as source:
            width, height = source.size
        now = self.clock()
        with transaction(self.db) as connection:
            parent = self._page(connection, user, parent_page_id, locked=True, require_image=True) if parent_page_id else None
            connection.execute(PAGES.insert().values(
                id=page_id, user_id=user_uuid(user), parent_page_id=parent_page_id,
                root_page_id=parent['root_page_id'] if parent else page_id,
                storage_key=key, sha256=digest, width=width, height=height,
                metadata={name: metadata[name] for name in ('orientation', 'rotation_count', 'rotation_reference', 'mode') if name in metadata},
                created_at=now, expires_at=parent['expires_at'] if parent else now + timedelta(hours=24)))
        return self.page(user, page_id)

    def find_request(self, user, request_id):
        if not request_id:
            return None
        with transaction(self.db) as connection:
            row = connection.execute(sa.select(SUBMISSIONS).where(
                SUBMISSIONS.c.user_id == user_uuid(user), SUBMISSIONS.c.client_request_id == request_id)).mappings().first()
            return self._decorate(connection, row) if row else None

    def create_submission(self, user, search_id, page_id, box, *, client_request_id=None, admit=False):
        key = self.storage.submission_key(search_id)
        digest = self.storage.digest(key + '/question.png')
        original = self.storage.digest(key + '/original.png')
        with Image.open(self.storage.path(key + '/question.png')) as image:
            width, height = image.size
        now = self.clock()
        with transaction(self.db) as connection:
            self._page(connection, user, page_id, locked=True, require_image=True)
            statement = insert(SUBMISSIONS).values(
                id=search_id, user_id=user_uuid(user), page_id=page_id, crop_box=box,
                storage_key=key, crop_sha256=digest, original_sha256=original, width=width, height=height,
                client_request_id=client_request_id, created_at=now, updated_at=now, expires_at=now + timedelta(days=30))
            row = connection.execute(statement.on_conflict_do_nothing(
                index_elements=['user_id', 'client_request_id']).returning(SUBMISSIONS)).mappings().first()
            created = row is not None
            if row is None:
                row = connection.execute(sa.select(SUBMISSIONS).where(
                    SUBMISSIONS.c.user_id == user_uuid(user), SUBMISSIONS.c.client_request_id == client_request_id)).mappings().one()
                self._queue(connection, page_id, key, search_id=search_id)
            value = self._decorate(connection, row)
            if admit and created:
                try:
                    value['admission_ticket'] = self.admission.reserve(user, 'generation', search_id,
                        request_id=client_request_id, connection=connection)
                except SearchError as exc:
                    if exc.code == 'search.request_conflict':
                        raise SearchError('search.request_retired', 409) from exc
                    raise
                if not value['admission_ticket'].created:
                    raise SearchError('search.request_retired', 409)
            return value, created

    def admitted_submission_live(self, ticket):
        with transaction(self.db) as connection:
            row = connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.id == ticket.search_id)).mappings().first()
            return self._live(connection, row)

    def start_admitted(self, ticket):
        with transaction(self.db) as connection:
            row = self._locked_submission(connection, ticket.search_id)
            if not self._live(connection, row):
                self.admission.cancel(ticket.id, connection=connection)
                return False
            return self.admission.start(ticket.id, connection=connection)

    def require_admitted_model_call(self, ticket):
        self.admission.require_generation_enabled()
        if not self.admitted_submission_live(ticket):
            raise SearchError('search.not_found', 404)

    def interrupt_admitted(self, ticket):
        with transaction(self.db) as connection:
            row = self._locked_submission(connection, ticket.search_id)
            if row is None:
                return
            self.admission._control(connection)
            other = connection.scalar(sa.select(TICKETS.c.id).where(
                TICKETS.c.search_id == ticket.search_id, TICKETS.c.id != UUID(ticket.id),
                TICKETS.c.state.in_(ACTIVE)).limit(1))
            if other is not None:
                return
            values = {}
            if ticket.kind == 'generation' and row['recognition_status'] in {'queued', 'running'}:
                values['recognition_status'] = 'interrupted'
            if row['lesson_status'] == 'running':
                values['lesson_status'] = 'interrupted'
            if values:
                connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == ticket.search_id).values(
                    **values, error_code='search.interrupted', updated_at=self.clock()))

    def reserve_lesson(self, user, search_id, kind, request_id=None):
        with transaction(self.db) as connection:
            row = self._locked_submission(connection, search_id)
            if row is None or row['user_id'] != user_uuid(user) or not self._live(connection, row):
                raise SearchError('search.not_found', 404)
            ticket = self.admission.reserve(user, kind, search_id, request_id=request_id, connection=connection)
            if ticket.created:
                self.set_state(search_id, lesson_state='running')
            return ticket

    def _locked_submission(self, connection, search_id):
        hint = connection.execute(sa.select(SUBMISSIONS.c.page_id, SUBMISSIONS.c.user_id).where(SUBMISSIONS.c.id == search_id)).first()
        if hint is None:
            return None
        self._page(connection, hint.user_id, hint.page_id, locked=True)
        return connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.id == search_id).with_for_update()).mappings().first()

    def _live(self, connection, row):
        if row is None or row['artifact_state'] != 'active' or row['expires_at'] <= self.clock():
            return False
        if self.recovery.is_deleted(connection, row):
            return False
        if row['problem_id']:
            return connection.scalar(sa.select(PROBLEMS.c.status).where(PROBLEMS.c.id == row['problem_id'])) == 'active'
        return True

    def link_identity(self, search_id, identity):
        with transaction(self.db) as connection:
            try:
                with connection.begin_nested():
                    return self._link_identity(connection, search_id, identity)
            except _LinkExpired:
                return None

    def _link_identity(self, connection, search_id, identity):
        row = self._locked_submission(connection, search_id)
        if not self._live(connection, row):
            return None
        connection.execute(insert(PROBLEMS).values(
            id=uuid4(), identity_version=identity['identity_version'], fingerprint=identity['fingerprint'],
            identity_json=identity['identity'], statement=identity['statement'], structured_problem=identity['structured_problem']
        ).on_conflict_do_nothing(index_elements=['identity_version', 'fingerprint']))
        problem = connection.execute(sa.select(PROBLEMS).where(
            PROBLEMS.c.identity_version == identity['identity_version'], PROBLEMS.c.fingerprint == identity['fingerprint']
        ).with_for_update()).mappings().one()
        if row['expires_at'] <= self.clock():
            raise _LinkExpired
        if problem['identity_json'] != identity['identity']:
            raise SearchError('identity.fingerprint_conflict', 500)
        if problem['status'] != 'active':
            raise SearchError('problem.disabled', 410)
        if row['problem_id'] and row['problem_id'] != problem['id']:
            raise SearchError('identity.submission_already_linked', 409)
        connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == search_id).values(
            problem_id=problem['id'], recognition_status='reviewed', updated_at=self.clock()))
        statement = insert(RELATIONS).values(user_id=row['user_id'], problem_id=problem['id'],
            first_searched_at=row['created_at'], last_searched_at=row['created_at'])
        connection.execute(statement.on_conflict_do_update(index_elements=['user_id', 'problem_id'], set_={
            'first_searched_at': sa.func.least(RELATIONS.c.first_searched_at, statement.excluded.first_searched_at),
            'last_searched_at': sa.func.greatest(RELATIONS.c.last_searched_at, statement.excluded.last_searched_at)}))
        if row['expires_at'] <= self.clock():
            raise _LinkExpired
        return dict(problem)

    associate = link_identity

    def set_state(self, search_id, *, recognition_state=None, lesson_state=None,
                  recognition_status=None, lesson_status=None, error_code=None):
        with transaction(self.db) as connection:
            row = self._locked_submission(connection, search_id)
            if not self._live(connection, row):
                return False
            values = {'updated_at': self.clock(), 'error_code': error_code}
            recognition = recognition_status or recognition_state
            lesson = lesson_status or lesson_state
            if recognition:
                values['recognition_status'] = recognition
            if lesson:
                values['lesson_status'] = lesson
            connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == search_id).values(**values))
            return True

    def history(self, user, *, limit=20, offset=0):
        limit, offset = max(1, min(100, int(limit))), max(0, int(offset))
        owner = user_uuid(user)
        with transaction(self.db) as connection:
            snapshot = self.recovery.validate_state(connection)
            deleted = [(UUID(owner_id), identifier, datetime.fromisoformat(created))
                       for owner_id, identifier, created in snapshot.keys_by_owner.get(str(owner), ())]
            visible = sa.not_(sa.tuple_(SUBMISSIONS.c.user_id, SUBMISSIONS.c.id, SUBMISSIONS.c.created_at).in_(deleted))
            group_key = sa.func.coalesce(sa.cast(SUBMISSIONS.c.problem_id, sa.Text), SUBMISSIONS.c.id)
            linked = sa.select(sa.cast(RELATIONS.c.problem_id, sa.Text).label('group_key'),
                RELATIONS.c.last_searched_at.label('recent_at')).where(RELATIONS.c.user_id == owner,
                    sa.select(SUBMISSIONS.c.id).where(SUBMISSIONS.c.user_id == RELATIONS.c.user_id,
                        SUBMISSIONS.c.problem_id == RELATIONS.c.problem_id, visible).correlate(RELATIONS).exists())
            unlinked = sa.select(SUBMISSIONS.c.id.label('group_key'), SUBMISSIONS.c.created_at.label('recent_at')).where(
                SUBMISSIONS.c.user_id == owner, SUBMISSIONS.c.problem_id.is_(None), SUBMISSIONS.c.expires_at > self.clock(), visible)
            history_groups = linked.union_all(unlinked).subquery('search_history')
            page_groups = (sa.select(history_groups)
                .order_by(history_groups.c.recent_at.desc(), history_groups.c.group_key.desc())
                .limit(limit + 1).offset(offset).cte('history_groups'))
            rows = connection.execute(sa.select(SUBMISSIONS, page_groups.c.group_key, page_groups.c.recent_at)
                .join(page_groups, group_key == page_groups.c.group_key).where(SUBMISSIONS.c.user_id == owner, visible)
                .order_by(page_groups.c.recent_at.desc(), page_groups.c.group_key.desc(),
                          SUBMISSIONS.c.created_at.desc(), SUBMISSIONS.c.id.desc())).mappings().all()
            groups = {}
            snapshot = self.recovery.validate_state(connection)
            latest_deletions = snapshot.deleted_keys
            for row in rows:
                if entry_key(row) in latest_deletions:
                    continue
                groups.setdefault(row['group_key'], []).append(row)
            keys = list(groups)
            items = []
            item_members = {}
            for key in keys[:limit]:
                members = groups[key]
                latest = members[0]
                usable = [row for row in members if row['lesson_status'] == 'ready'
                          and row['artifact_state'] == 'active' and row['expires_at'] > self.clock()
                          and self.lesson_artifacts_available(row)]
                chosen = self._decorate(connection, usable[0] if usable else latest, deletion_snapshot=snapshot)
                item_members[chosen['id']] = (entry_key(chosen), entry_key(latest))
                disabled = chosen['problem_status'] == 'disabled'
                latest_lesson = ('expired' if latest['expires_at'] <= self.clock() else
                                 'unavailable' if latest['lesson_status'] == 'ready' and not any(
                                     row['id'] == latest['id'] for row in usable) else latest['lesson_status'])
                latest_status = ('disabled' if disabled else 'expired' if latest['expires_at'] <= self.clock()
                                 else latest_lesson if latest_lesson != 'not_started'
                                 else latest['recognition_status'])
                summary = chosen['statement'] or UNLINKED_SUMMARIES.get(latest['recognition_status'], '拍题记录')
                items.append({'search_id': chosen['id'], 'problem_id': str(chosen['problem_id']) if chosen['problem_id'] else None,
                    'summary': '题目已下线，请重新拍摄' if disabled else summary[:160],
                    'last_searched_at': latest['recent_at'].isoformat(), 'latest_status': latest_status,
                    'recognition_status': latest['recognition_status'],
                    'lesson_status': latest_lesson,
                    'lesson_available': bool(usable) and not disabled, 'image_state': chosen['artifact_state']})
            latest_deletions = self.recovery.validate_state(connection).deleted_keys
            items = [item for item in items
                     if not any(member in latest_deletions for member in item_members[item['search_id']])]
            keys = [key for key in keys if any(entry_key(row) not in latest_deletions for row in groups[key])]
        return {'user_id': str(owner), 'items': items, 'has_more': len(keys) > limit}

    def lesson_artifacts_available(self, row):
        directory = self.storage.path(row['storage_key'])
        if not all((directory / name).is_file() for name in ('result.json', 'crop.json', 'question.png')):
            return False
        attempts = [path for path in directory.glob('stage-two-*') if path.name.removeprefix('stage-two-').isdigit()]
        if not attempts:
            return False
        latest = max(attempts, key=lambda path: int(path.name.removeprefix('stage-two-')))
        if not all((latest / name).is_file() for name in ('stage-two-result.json', 'stage-three/run.json',
                   'stage-three/frozen.json', 'stage-three/stage-three-result.json')):
            return False
        try:
            run_id = json.loads((latest / 'stage-three/run.json').read_text())['run_id']
        except (OSError, ValueError, KeyError, TypeError):
            return False
        runs = metadata.tables['lesson_runs']
        with transaction(self.db) as connection:
            return connection.scalar(sa.select(runs.c.run_id).where(
                runs.c.run_id == run_id, runs.c.submission_id == row['id'])) is not None

    def _queue(self, connection, page_id, key, *, search_id=None):
        entries = connection.scalar(sa.select(PAGES.c.pending_cleanup_keys).where(PAGES.c.id == page_id).with_for_update())
        entries = list(entries)
        if not any(entry['key'] == key for entry in entries):
            entries.append({'key': key, 'search_id': search_id, 'attempts': 0})
            connection.execute(PAGES.update().where(PAGES.c.id == page_id).values(pending_cleanup_keys=entries))

    def delete(self, user, search_id):
        owner = user_uuid(user)
        with transaction(self.db) as connection:
            target = connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.id == search_id, SUBMISSIONS.c.user_id == owner)).mappings().first()
            if target is None:
                raise SearchError('search.not_found', 404)
            if self.recovery.is_deleted(connection, target):
                raise SearchError('search.not_found', 404)
            condition = sa.and_(SUBMISSIONS.c.user_id == owner,
                SUBMISSIONS.c.problem_id == target['problem_id'] if target['problem_id'] else SUBMISSIONS.c.id == search_id)
            hints = connection.execute(sa.select(SUBMISSIONS.c.id, SUBMISSIONS.c.page_id).where(condition)).all()
            for page_id in sorted({hint.page_id for hint in hints}):
                self._page(connection, owner, page_id, locked=True)
            rows = connection.execute(sa.select(SUBMISSIONS).where(
                SUBMISSIONS.c.id.in_([hint.id for hint in hints])).order_by(SUBMISSIONS.c.id).with_for_update()).mappings().all()
            self.recovery.append(connection, rows)
            identifiers = self._delete_rows(connection, rows)
        return {'deleted_search_ids': identifiers}

    def _delete_rows(self, connection, rows):
        for row in rows:
            self._queue(connection, row['page_id'], row['storage_key'], search_id=row['id'])
        identifiers = [row['id'] for row in rows]
        if self.admission is not None:
            self.admission.cancel_for_submissions(identifiers, connection=connection)
        connection.execute(SUBMISSIONS.delete().where(SUBMISSIONS.c.id.in_(identifiers)))
        for owner, problem_id in sorted({(row['user_id'], row['problem_id']) for row in rows if row['problem_id']}):
            relation = sa.and_(RELATIONS.c.user_id == owner, RELATIONS.c.problem_id == problem_id)
            connection.execute(sa.select(RELATIONS).where(relation).with_for_update()).first()
            remaining = connection.execute(sa.select(sa.func.min(SUBMISSIONS.c.created_at), sa.func.max(SUBMISSIONS.c.created_at)).where(
                SUBMISSIONS.c.user_id == owner, SUBMISSIONS.c.problem_id == problem_id)).one()
            if remaining[0] is None:
                connection.execute(RELATIONS.delete().where(relation))
            else:
                connection.execute(RELATIONS.update().where(relation).values(first_searched_at=remaining[0], last_searched_at=remaining[1]))
        return identifiers

    def replay_deletions(self, snapshot=None):
        snapshot = snapshot or self.recovery.snapshot()
        with transaction(self.db) as connection:
            self.recovery.validate_state(connection, snapshot)
            if connection.scalar(sa.select(STATE.c.replayed_sequence)) >= snapshot.cursor['sequence']:
                return {'deleted_search_ids': []}
            keys = snapshot.deleted_keys
            if not keys:
                return {'deleted_search_ids': []}
            identifiers = sorted({identifier for _, identifier, _ in keys})
            hints = connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.id.in_(identifiers))).mappings().all()
            hints = [row for row in hints if entry_key(row) in keys]
            for page_id in sorted({row['page_id'] for row in hints}):
                connection.execute(sa.select(PAGES.c.id).where(PAGES.c.id == page_id).with_for_update()).first()
            rows = connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.id.in_([row['id'] for row in hints]))
                                      .order_by(SUBMISSIONS.c.id).with_for_update()).mappings().all()
            rows = [row for row in rows if entry_key(row) in keys]
            state = connection.execute(sa.select(STATE).with_for_update()).mappings().one()
            deleted = self._delete_rows(connection, rows)
            if state['sequence'] <= snapshot.cursor['sequence']:
                connection.execute(STATE.update().values(sequence=snapshot.cursor['sequence'],
                    digest=snapshot.cursor['digest'], replayed_sequence=snapshot.cursor['sequence']))
            elif state['replayed_sequence'] < snapshot.cursor['sequence']:
                connection.execute(STATE.update().values(replayed_sequence=snapshot.cursor['sequence']))
        return {'deleted_search_ids': deleted}

    def recover(self):
        self.replay_deletions()
        with transaction(self.db) as connection:
            identifiers = connection.scalars(sa.select(SUBMISSIONS.c.id).where(sa.or_(
                SUBMISSIONS.c.recognition_status.in_(['queued', 'running']), SUBMISSIONS.c.lesson_status == 'running'))).all()
        recovered = 0
        for search_id in identifiers:
            try:
                with self.lifecycle_lock(search_id), transaction(self.db) as connection:
                    row = self._locked_submission(connection, search_id)
                    if (row is None or row['expires_at'] <= self.clock()
                            or (row['recognition_status'] not in {'queued', 'running'} and row['lesson_status'] != 'running')):
                        continue
                    values = {'error_code': 'search.interrupted', 'updated_at': self.clock()}
                    if row['recognition_status'] in {'queued', 'running'}:
                        values['recognition_status'] = 'interrupted'
                    if row['lesson_status'] == 'running':
                        values['lesson_status'] = 'interrupted'
                    connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == search_id).values(**values))
                    recovered += 1
            except SearchError as exc:
                if exc.code != 'search.running':
                    raise
        return recovered

    def cleanup(self):
        self.replay_deletions()
        now = self.clock()
        expired_submission = sa.and_(SUBMISSIONS.c.expires_at <= now, sa.or_(
            SUBMISSIONS.c.artifact_state == 'active', SUBMISSIONS.c.problem_id.is_(None)))
        pending_page = sa.or_(
            sa.and_(PAGES.c.expires_at <= now, PAGES.c.image_state == 'active'),
            PAGES.c.id.in_(sa.select(SUBMISSIONS.c.page_id).where(expired_submission)))
        with transaction(self.db) as connection:
            expired_ids = []
            page_ids = connection.scalars(sa.select(PAGES.c.id).where(pending_page)
                .order_by(PAGES.c.id)).all()
            for page_id in page_ids:
                page = connection.execute(sa.select(PAGES).where(PAGES.c.id == page_id, pending_page)
                    .with_for_update()).mappings().first()
                if page is None:
                    continue
                if page['expires_at'] <= now and page['image_state'] == 'active':
                    connection.execute(PAGES.update().where(PAGES.c.id == page_id).values(image_state='expired'))
                    if self.storage.path(page['storage_key']).exists():
                        self._queue(connection, page_id, page['storage_key'])
                rows = connection.execute(sa.select(SUBMISSIONS).where(SUBMISSIONS.c.page_id == page_id, expired_submission)
                    .order_by(SUBMISSIONS.c.id).with_for_update()).mappings().all()
                for row in rows:
                    expired_ids.append(row['id'])
                    runs = metadata.tables['lesson_runs']
                    connection.execute(runs.delete().where(runs.c.submission_id == row['id']))
                    if self.storage.path(row['storage_key']).exists():
                        self._queue(connection, page_id, row['storage_key'], search_id=row['id'])
                    if row['problem_id']:
                        if row['artifact_state'] == 'active':
                            connection.execute(SUBMISSIONS.update().where(SUBMISSIONS.c.id == row['id']).values(
                                artifact_state='expired', lesson_status='expired', updated_at=now))
                    else:
                        connection.execute(SUBMISSIONS.delete().where(SUBMISSIONS.c.id == row['id']))
            if self.admission is not None:
                self.admission.cancel_for_submissions(expired_ids, connection=connection, error_code='search.expired')
        with transaction(self.db) as connection:
            pending = connection.execute(sa.select(PAGES.c.id, PAGES.c.pending_cleanup_keys).where(
                sa.func.jsonb_array_length(PAGES.c.pending_cleanup_keys) > 0)).all()
        removed = 0
        for page_id, entries in pending:
            for entry in entries:
                try:
                    lease = self.storage.cleanup_lock(entry['search_id']) if entry.get('search_id') else self.storage.page_lock(page_id)
                except SearchError as exc:
                    if exc.code == 'search.running':
                        continue
                    raise
                error = None
                with lease:
                    try:
                        self.storage.remove(entry['key'])
                        removed += 1
                    except (OSError, SearchError) as exc:
                        error = getattr(exc, 'code', type(exc).__name__)
                    with transaction(self.db) as connection:
                        current = connection.scalar(sa.select(PAGES.c.pending_cleanup_keys).where(PAGES.c.id == page_id).with_for_update())
                        updated = []
                        for item in current:
                            if item['key'] != entry['key']:
                                updated.append(item)
                            elif error:
                                updated.append({**item, 'attempts': item.get('attempts', 0) + 1, 'last_error_code': error})
                        connection.execute(PAGES.update().where(PAGES.c.id == page_id).values(pending_cleanup_keys=updated))
        pending_keys = {entry['key'] for _, entries in pending for entry in entries}
        return {'removed': removed, 'orphans_removed': self.cleanup_orphans(pending_keys=pending_keys)}

    def cleanup_orphans(self, *, pending_keys=()):
        removed = 0
        cutoff = (self.clock() - timedelta(hours=1)).timestamp()
        for category, table in (('pages', PAGES), ('submissions', SUBMISSIONS)):
            for path in self.storage.path(category).iterdir():
                key = f'{category}/{path.name}'
                if key in pending_keys:
                    continue
                try:
                    if path.is_symlink() or not path.is_dir():
                        continue
                    modified_at = path.stat().st_mtime
                except FileNotFoundError:
                    continue
                try:
                    lease = self.storage.page_lock(path.name) if category == 'pages' else self.storage.cleanup_lock(path.name)
                except SearchError:
                    continue
                with lease:
                    with transaction(self.db) as connection:
                        registered = connection.execute(sa.select(table).where(table.c.id == path.name)).mappings().first()
                    if registered is None:
                        if modified_at >= cutoff:
                            continue
                    elif registered['image_state' if category == 'pages' else 'artifact_state'] != 'expired':
                        continue
                    try:
                        self.storage.remove(key)
                    except (OSError, SearchError):
                        if registered is not None:
                            with transaction(self.db) as connection:
                                self._queue(connection, registered['id'] if category == 'pages' else registered['page_id'],
                                    key, search_id=registered['id'] if category == 'submissions' else None)
                        continue
                    removed += 1
        return removed

    def disable(self, problem_id):
        with transaction(self.db) as connection:
            result = connection.execute(PROBLEMS.update().where(PROBLEMS.c.id == UUID(str(problem_id))).values(status='disabled'))
            if not result.rowcount:
                raise SearchError('problem.not_found', 404)
